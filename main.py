from __future__ import annotations
import tkinter as tk
import logging
import sys
import logging.handlers
import subprocess
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
# picamera2 writes 6 lines ("Camera now open", "Camera started", ...) on every QR scan - only keep its warnings/errors
logging.getLogger("picamera2").setLevel(logging.WARNING)

class flow_controll:
    """Reacts to the door sensor and GUI actions. The whole logic is two rules:

    - Door CLOSES -> ribbon cam checks once (for up to QR_SCAN_TIMEOUT_S):
      QR code visible = this tray is at the front, no code = no tray.
    - Door OPENS  -> if a tray is at the front: take photos immediately.
    """

    def __init__(self, app: gui.App):
        self.app = app

        self.current_tray_number: str | None = None

        # Last known door state  (None until the first sensor event)
        self._door_open: bool | None = None

        self._scan_running = False
        self._rescan_requested = False   # door closed again while a scan was running
        self._capture_running = False    # automatic OR manual capture in progress
        self._capture_pending = False    # door opened again while a capture was running
        self._door_opened_at: float | None = None   # time.monotonic() of the last door-open SIGNAL (for the log)

        self.sensor = door_sensor.DoorSensor(
            # The signal time is taken HERE, in the sensor thread - the log can then show how long it took until the photo
            on_change=lambda is_open: self.app.root.after(0, self._on_door_change, is_open, time.monotonic())
        )

        # If the door sensor couldn't be set up, show it in the History; otherwise nobody notices that door detection isn't working.
        sensor_error = getattr(self.sensor, "error_message", None)
        if sensor_error:
            self.app.log_event(sensor_error, level=logging.ERROR)
            self.app.set_error("sensor", "Door sensor not available - no automatic photos")

        # Ribbon cam usable at all? Without picamera2 every scan finds "nothing" -> no tray is ever detected.
        # getattr: the Windows mock doesn't have this attribute
        if not getattr(qr_code_scanner, "HAS_PICAMERA", True):
            self.app.log_event("Ribbon cam not available - picamera2 is not installed. Trays can't be detected!", level=logging.ERROR)
            self.app.set_error("ribbon_missing", "Ribbon cam (QR) not available")

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

        # TEMP door test - only the real sensor has simulate_toggle(on Windows the mock's Enter key does the same job)
        if config.DOOR_TEST_BUTTON and hasattr(self.sensor, "simulate_toggle"):
            self.app.on_simulate_door = self._simulate_door

    # --- Door events ----------------------------------------------------------

    def _on_door_change(self, is_open: bool, signal_time: float | None = None) -> None:
        # Same state as last time = no real change (e.g. a repeated sensor event)
        if is_open == self._door_open:
            return
        self._door_open = is_open
        if signal_time is None:
            signal_time = time.monotonic()

        # Every door signal as its own, easy to spot line (also in the History)
        delay_ms = (time.monotonic() - signal_time) * 1000
        self.app.log_event(f"===== DOOR {'OPENED' if is_open else 'CLOSED'} ===== (signal handled after {delay_ms:.0f} ms)")
        if is_open:
            self._door_opened_at = signal_time

        if is_open:
            self._handle_door_opened()
        else:
            self._handle_door_closed()

    def _handle_door_closed(self) -> None:
        """Door closed -> check with the ribbon cam which tray (if any) is at the front now. Also happens once at program start, since the sensor reports its initial state."""
        if self._scan_running:
            self._rescan_requested = True
            return
        self._start_qr_scan()

    def _handle_door_opened(self) -> None:
        """Door opened -> photos, but only if a tray is at the front."""
        if self.current_tray_number is None:
            if not self._scan_running:
                self.app.log_event("No tray known at the front -> no photos")
            else:
                self.app.log_event("QR scan still running -> photos follow as soon as it finds a tray")
            # If a scan is still running, _on_qr_scan_done catches up on the photos as soon as it finds a tray
            return
        self._start_capture(self.current_tray_number, self._door_opened_at)

    # --- QR scan (ribbon cam) -------------------------------------------------

    def _start_qr_scan(self) -> None:
        # Forget the previous tray FIRST: after a door close, only what the camera sees counts.
        self.current_tray_number = None
        self._scan_running = True
        self.app.log_event("QR scan started")

        # The ribbon cam live preview (Camera Setup) blocks the camera -> close it first, otherwise the scan fails
        preview_process = self.app.close_ribbon_cam_preview()
        if preview_process is not None:
            self.app.log_event("Ribbon cam preview closed automatically - camera needed for QR scan", level=logging.WARNING)

        threading.Thread(target=self._qr_scan_worker, args=(preview_process,), daemon=True).start()

    def _qr_scan_worker(self, preview_process: subprocess.Popen | None = None) -> None:
        """Runs in a background thread. ALWAYS reports back to the Tk main thread - even if the scan crashes - otherwise _scan_running would stay True forever."""
        qr_result = None
        error_message = None
        t_start = time.monotonic()
        try:
            if preview_process is not None:
                # Wait until the preview has really released the camera (kill it if it doesn't react)
                try:
                    preview_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    preview_process.kill()
                    preview_process.wait()
            qr_result = qr_code_scanner.wait_for_qr()
        except Exception as exc:
            # logging is thread-safe - writes the full traceback to the log file
            logging.exception("QR scan worker crashed")
            error_message = f"QR scan failed: {exc}"

        self.app.root.after(0, self._on_qr_scan_done, qr_result, error_message, time.monotonic() - t_start)

    def _on_qr_scan_done(self, qr_result, error_message: str | None = None, duration_s: float = 0.0) -> None:
        self._scan_running = False

        # Red banner while the ribbon cam keeps failing - disappears with the next scan that works again
        if error_message is not None:
            self.app.set_error("ribbon_scan", "QR scan failed - see History")
        else:
            self.app.clear_error("ribbon_scan")

        if error_message is not None:
            self.app.log_event(f"QR scan FAILED after {duration_s:.1f} s: {error_message}", level=logging.ERROR)
        elif qr_result is None:
            # Normal case, e.g. after a tray went back in - not an error anymore
            self.app.log_event(f"QR scan done after {duration_s:.1f} s: no QR code -> no tray at the front")
        else:
            # QR content comes from outside - only accept valid tray numbers, normalized ("01" -> "1")
            tray_number = inventory.normalize_tray_number(qr_result.data)
            if tray_number is None:
                self.app.log_event(
                    f"QR scan done after {duration_s:.1f} s: QR code contains no valid tray number: '{qr_result.data}'",
                    level=logging.ERROR,
                )
            else:
                self.current_tray_number = tray_number
                self.app.log_event(f"QR scan done after {duration_s:.1f} s: tray {tray_number} at the front")

        # Door closed again (after opening) while we were scanning: this result may already be outdated - look again
        if self._rescan_requested:
            self._rescan_requested = False
            if self._door_open is False:
                self._start_qr_scan()
                return

        # Door opened while the scan was still running: the photos were skipped back then -> take them now
        if self._door_open and self.current_tray_number is not None:
            self.app.log_event("Door had opened during the QR scan - taking photos now")
            self._start_capture(self.current_tray_number, self._door_opened_at)

    # --- Capture (USB cameras) ------------------------------------------------

    def _start_capture(self, tray_number: str, door_opened_at: float | None = None) -> None:
        """door_opened_at: time of the door signal that triggered this capture (None for a manual capture) - only for the log."""
        if self._capture_running:
            # e.g. false trigger photo still running, and the door opens again for real -> that one must not get lost, it's the final one
            self._capture_pending = True
            self.app.log_event("Capture already running - another one follows right after")
            return

        self._capture_running = True
        threading.Thread(target=self._capture_worker, args=(tray_number, door_opened_at), daemon=True).start()

    def _run_capture_safely(self, tray_number: str):
        """Wraps capture_and_stitch so it ALWAYS returns a StitchResult, even if something inside crashes.
        Used by both the automatic and the manual capture."""
        try:
            return camera_stitching.capture_and_stitch(
                camera_setup.get_camera_devices(), tray_number=tray_number
            )
        except Exception as exc:
            logging.exception("Capture worker crashed")
            return camera_stitching.StitchResult(
                success=False, error_message=f"Capture crashed: {exc}"
            )

    def _capture_worker(self, tray_number: str, door_opened_at: float | None = None) -> None:
        result = self._run_capture_safely(tray_number)
        self.app.root.after(0, self._on_capture_done, result, tray_number, door_opened_at)

    def _on_capture_done(self, result, tray_number: str, door_opened_at: float | None = None) -> None:
        self._capture_running = False

        # Red banner after a failed capture (a photo is missing!) - disappears with the next successful capture
        if result.success:
            self.app.clear_error("capture")
        else:
            self.app.set_error("capture", f"Last capture failed (tray {tray_number}) - see History")

        if result.success:
            # THE number that matters: how long after the door signal were the photos taken?
            frames_taken_at = getattr(result, "frames_taken_at", None)   # the Windows mock doesn't have it
            if door_opened_at is not None and frames_taken_at is not None:
                self.app.log_event(f"Photos of tray {tray_number} taken {frames_taken_at - door_opened_at:.2f} s after the door signal")
            self.app.log_event(f"Capture saved for tray {tray_number}: {result.panorama_path.name}")
            # Only this tray's row  gets refreshed
            self.app.update_tray_row(int(tray_number))
        else:
            self.app.log_event(f"Capture FAILED for tray {tray_number}: {result.error_message}", level=logging.ERROR)

        if self._capture_pending:
            self._capture_pending = False
            # Only if a tray is still known - if the door closed in between and the scan found nothing, there's nothing to photograph
            if self.current_tray_number is not None:
                self._start_capture(self.current_tray_number, self._door_opened_at)
                return

    # --- Manual capture -------------------------------------------------------

    def _handle_manual_capture_request(self, tray_number: str) -> None:
        """Triggered from the GUI's manual-capture button. Allowed any time, except while another capture (automatic or manual) is running."""
        if self._capture_running:
            self.app.log_event("Manual capture rejected - a capture is already running", level=logging.WARNING)
            return

        self.app.log_event(f"Manual capture started for tray {tray_number}")
        self._start_capture(tray_number)

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


if __name__ == "__main__":
    main()