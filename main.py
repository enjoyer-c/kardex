from __future__ import annotations
from dataclasses import dataclass
import tkinter as tk
import logging
import sys
import logging.handlers
import threading
import time
import traceback

import config
import gui
import inventory
import camera_setup

if sys.platform.startswith("win32"):
    import door_sensor_mock as door_sensor
    import qr_code_scanner_mock as qr_code_scanner
    import camera_stitching_mock as camera_stitching
else:
    import door_sensor
    import qr_code_scanner
    import camera_stitching

config.LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    # Milliseconds in every line - needed to measure the time between door signal and photo
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.handlers.RotatingFileHandler(
            config.LOG_FILE, maxBytes=5_000_000, backupCount=3
        ),
        logging.StreamHandler(),
    ],
)
# picamera2 writes several lines ("Camera now open", "Camera started", ...) whenever the camera starts - only keep its warnings/errors
logging.getLogger("picamera2").setLevel(logging.WARNING)

@dataclass
class DoorCapture:
    """Everything that happened after one door opening - collected in the background thread, evaluated in the Tk main thread."""
    photo_delay_s: float | None = None    # photos taken how long after the door signal
    photo_error: str | None = None        # USB cameras failed
    qr_duration_s: float = 0.0
    qr_data: str | None = None            # raw QR content (None = no QR code)
    qr_error: str | None = None           # ribbon cam failed
    tray_number: str | None = None        # valid, normalized tray number from the QR code
    result: object = None                 # StitchResult if the photos were saved
    crash: str | None = None              # unexpected exception


class flow_controll:
    """Reacts to the door sensor and GUI actions. The whole logic is ONE rule:

    Door OPENS  -> immediately take the USB photos, then read the QR code (ribbon cam, runs permanently).
                   QR code found = save the photos under this tray number, no QR code = discard them.
    Door CLOSES -> nothing.

    Nothing is remembered between two door events - every opening is complete on its own.
    """

    def __init__(self, app: gui.App):
        self.app = app

        self._door_open: bool | None = None   # last known door state (None until the first sensor event)
        self._capture_running = False         # door OR manual capture in progress

        self.sensor = door_sensor.DoorSensor(
            # The signal time is taken HERE, in the sensor thread - the log can then show how long it took until the photo
            on_change=lambda is_open: self.app.root.after(0, self._on_door_change, is_open, time.monotonic())
        )

        # If the door sensor couldn't be set up, show it in the History; otherwise nobody notices that door detection isn't working.
        sensor_error = getattr(self.sensor, "error_message", None)
        if sensor_error:
            self.app.log_event(sensor_error, level=logging.ERROR)
            self.app.set_error("sensor", "Door sensor not available - no automatic photos")

        # Ribbon cam runs permanently from now on - a scan then only reads the newest frames
        ribbon_error = qr_code_scanner.start_stream()
        if ribbon_error:
            self.app.log_event(ribbon_error, level=logging.ERROR)
            self.app.set_error("ribbon", "Ribbon cam (QR) not available - no automatic photos")
        # The live preview in Camera Setup needs the camera for itself - the GUI releases / restarts it with these
        self.app.ribbon_cam_release = qr_code_scanner.stop_stream
        self.app.ribbon_cam_restart = qr_code_scanner.start_stream

        # Any USB cameras connected at all?
        camera_error = camera_setup.check_cameras_connected()
        if camera_error:
            self.app.log_event(camera_error, level=logging.ERROR)
            self.app.set_error("usb_cameras", camera_error)

        # Saved USB camera order still matches the connected cameras?
        camera_warning = camera_setup.check_saved_order()
        if camera_warning:
            self.app.log_event(camera_warning, level=logging.WARNING)

        self.app.on_manual_capture = self._handle_manual_capture_request

        # TEMP door test - only the real sensor has simulate_toggle (on Windows the mock's Enter key does the same job)
        if config.DOOR_TEST_BUTTON and hasattr(self.sensor, "simulate_toggle"):
            self.app.on_simulate_door = self._simulate_door

    # --- Door events ----------------------------------------------------------

    def _on_door_change(self, is_open: bool, signal_time: float) -> None:
        state_text = "OPENED" if is_open else "CLOSED"

        # First event = the sensor reports its state at program start - not a real door movement
        if self._door_open is None:
            self._door_open = is_open
            self.app.log_event(f"Door state at startup: {state_text}")
            return

        # Same state as last time = no real change (e.g. a repeated sensor event)
        if is_open == self._door_open:
            return
        self._door_open = is_open

        delay_ms = (time.monotonic() - signal_time) * 1000
        self.app.log_event(f"===== DOOR {state_text} ===== (signal handled after {delay_ms:.0f} ms)")

        if not is_open:
            return   # door closes -> nothing to do

        if self._capture_running:
            self.app.log_event("Previous capture still running - this door opening is ignored", level=logging.WARNING)
            return
        self._capture_running = True
        threading.Thread(target=self._door_capture_worker, args=(signal_time,), daemon=True).start()

    def _door_capture_worker(self, signal_time: float) -> None:
        """Background thread: photos FIRST (the tray starts moving ~2.5 s after the door opens), then the QR code,
        then save or discard. ALWAYS reports back to the Tk main thread - otherwise _capture_running would stay True forever."""
        outcome = DoorCapture()
        try:
            # 1. USB photos - right now, before anything else
            frame_set, outcome.photo_error = camera_stitching.grab_frames(camera_setup.get_camera_devices())
            if frame_set is not None:
                outcome.photo_delay_s = frame_set.taken_at - signal_time

            # 2. QR code - which tray is this?
            t_qr = time.monotonic()
            try:
                qr_result = qr_code_scanner.scan_now()
                if qr_result is not None:
                    outcome.qr_data = qr_result.data
                    # QR content comes from outside - only accept valid tray numbers, normalized ("01" -> "1")
                    outcome.tray_number = inventory.normalize_tray_number(qr_result.data)
            except RuntimeError as exc:          # camera not running (e.g. live preview open)
                outcome.qr_error = str(exc)
            except Exception as exc:
                logging.exception("QR scan crashed")
                outcome.qr_error = f"QR scan failed: {exc}"
            outcome.qr_duration_s = time.monotonic() - t_qr

            # 3. Save - only with photos AND a valid tray number, otherwise the photos are simply discarded
            if frame_set is not None and outcome.tray_number is not None:
                outcome.result = camera_stitching.combine_and_save(frame_set, outcome.tray_number)
        except Exception as exc:
            logging.exception("Door capture crashed")
            outcome.crash = str(exc)

        self.app.root.after(0, self._on_door_capture_done, outcome)

    def _on_door_capture_done(self, outcome: DoorCapture) -> None:
        self._capture_running = False
        log = self.app.log_event

        if outcome.crash:
            log(f"Capture CRASHED: {outcome.crash}", level=logging.ERROR)
            self.app.set_error("capture", "Last capture failed - see History")
            return

        if outcome.photo_delay_s is not None:
            log(f"Photos taken {outcome.photo_delay_s:.2f} s after the door signal")
        else:
            log(f"Photos FAILED: {outcome.photo_error}", level=logging.ERROR)

        # Red banner while the ribbon cam fails - disappears with the next scan that works again
        if outcome.qr_error:
            log(f"QR scan FAILED: {outcome.qr_error} -> photos discarded", level=logging.ERROR)
            self.app.set_error("ribbon_scan", "QR scan failed - see History")
            return
        self.app.clear_error("ribbon_scan")

        if outcome.qr_data is None:
            log(f"No QR code (looked for {outcome.qr_duration_s:.1f} s) -> no tray at the front, photos discarded")
            return
        if outcome.tray_number is None:
            log(f"QR code contains no valid tray number: '{outcome.qr_data}' -> photos discarded", level=logging.ERROR)
            return
        log(f"QR code: tray {outcome.tray_number} (read in {outcome.qr_duration_s:.2f} s)")

        if outcome.result is None:
            # QR found, but no photos (USB cameras failed - already logged above)
            self.app.set_error("capture", f"Last capture failed (tray {outcome.tray_number}) - see History")
            return
        self._report_saved(outcome.result, outcome.tray_number)

    def _report_saved(self, result, tray_number: str) -> None:
        """Common end of the door capture and the manual capture."""
        if result.success:
            self.app.clear_error("capture")
            self.app.log_event(f"Capture saved for tray {tray_number}: {result.panorama_path.name}")
            self.app.update_tray_row(int(tray_number))   # only this tray's row gets refreshed
        else:
            self.app.set_error("capture", f"Last capture failed (tray {tray_number}) - see History")
            self.app.log_event(f"Capture FAILED for tray {tray_number}: {result.error_message}", level=logging.ERROR)

    # --- Manual capture -------------------------------------------------------

    def _handle_manual_capture_request(self, tray_number: str) -> None:
        """Triggered from the GUI's manual-capture button. Allowed any time, except while another capture is running."""
        if self._capture_running:
            self.app.log_event("Manual capture rejected - a capture is already running", level=logging.WARNING)
            return

        self.app.log_event(f"Manual capture started for tray {tray_number}")
        self._capture_running = True
        threading.Thread(target=self._manual_capture_worker, args=(tray_number,), daemon=True).start()

    def _manual_capture_worker(self, tray_number: str) -> None:
        try:
            result = camera_stitching.capture_and_stitch(camera_setup.get_camera_devices(), tray_number=tray_number)
        except Exception as exc:
            logging.exception("Manual capture crashed")
            result = camera_stitching.StitchResult(success=False, error_message=f"Capture crashed: {exc}")
        self.app.root.after(0, self._on_manual_capture_done, result, tray_number)

    def _on_manual_capture_done(self, result, tray_number: str) -> None:
        self._capture_running = False
        self._report_saved(result, tray_number)

    # --- TEMP door test (remove together with config.DOOR_TEST_BUTTON) ---
    def _simulate_door(self) -> None:
        self.sensor.simulate_toggle()
        state_text = "OPEN" if self.sensor.is_open() else "CLOSED"
        self.app.log_event(f"TEST: door simulated {state_text}", level=logging.WARNING)


def _set_windows_app_id() -> None:
    """Windows groups taskbar icons by an "AppUserModelID". Without its own ID, the program counts as python.exe and the taskbar shows the
    Python icon. Must be called BEFORE the first Tk window is created. Does nothing on Linux."""
    if not sys.platform.startswith("win32"):
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GSI.Kardex.ShuttleSystem")
    except (AttributeError, OSError) as exc:
        logging.warning("Could not set Windows AppUserModelID: %s", exc)


def _handle_callback_exception(exc, val, tb) -> None:
    logging.error("Unhandled GUI exception:\n%s", "".join(traceback.format_exception(exc, val, tb)))


def main() -> None:
    camera_stitching.create_tray_folders()

    # Open all USB cameras NOW and keep them streaming - a capture then only takes the newest frame
    camera_setup.start_camera_streams()

    _set_windows_app_id()
    root = tk.Tk(className="Kardex")
    root.report_callback_exception = _handle_callback_exception
    if sys.platform.startswith("linux"):
        try:
            root.attributes("-zoomed", True)
        except tk.TclError:
            root.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")

    app = gui.App(root)
    app.load_history_from_log_file(config.LOG_FILE)
    app.log_event("################ Program started ################")
    flow_controll(app)
    try:
        root.mainloop()
    finally:
        camera_setup.stop_camera_streams()
        qr_code_scanner.stop_stream()


if __name__ == "__main__":
    main()