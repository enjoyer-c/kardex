from __future__ import annotations
import tkinter as tk
from enum import Enum, auto
import logging
import sys
import logging.handlers
import threading
import traceback

import config
import gui
import inventory
import camera_setup

if sys.platform.startswith("win32"):
    import hall_sensor_mock as hall_sensor
    import qr_code_scanner_mock as qr_code_scanner
    import camera_stitching_mock as camera_stitching
else:
    import hall_sensor
    import qr_code_scanner
    import camera_stitching

config.LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.handlers.RotatingFileHandler(
            config.LOG_FILE, maxBytes=5_000_000, backupCount=3
        ),
        logging.StreamHandler(),
    ],
)

class State(Enum):
    IDLE = auto()                    # Door closed, waiting for a new request
    OUTBOUND = auto()                # Door open (1st time) - tray moving to delivery position
    AT_DELIVERY_POSITION = auto()    # Door closed - QR gets scanned immediately here, then waits while user loads/unloads
    CAPTURING_AND_STITCHING = auto() # Door open (2nd time) - take photos + stitch before tray starts moving
    RETURNING = auto()               # Tray driving back into the warehouse, door closing

class flow_controll:
    """Owns the state machine and reacts to hardware events and GUI actions by
    driving transitions between states, triggering QR scans and camera captures as needed."""
        
    def __init__(self, app: gui.App):
        self.app = app
        self.state = State.IDLE
        self.current_tray_number: str | None = None
        self._manual_capture_in_progress = False

        self.sensor = hall_sensor.HallSensor(
            on_change=lambda is_open: self.app.root.after(0, self._on_door_change, is_open)
        )

        # If the hall sensor couldn't be set up, show it in the History -
        # otherwise nobody notices that door detection isn't working.
        # getattr: the Windows mock doesn't have this attribute
        sensor_error = getattr(self.sensor, "error_message", None)
        if sensor_error:
            self.app.log_event(sensor_error, level=logging.ERROR)

        # Saved USB camera order still matches the connected cameras?
        # (e.g. a camera was unplugged or moved to another USB port)
        camera_warning = camera_setup.check_saved_order()
        if camera_warning:
            self.app.log_event(camera_warning, level=logging.WARNING)
        self.app.on_manual_capture = self._handle_manual_capture_request

        self._update_status()

    def _update_status(self) -> None:
        texts = {
            State.IDLE: "IDLE - waiting for Door to open",
            State.OUTBOUND: "DELIVERY - tray is moving",
            State.AT_DELIVERY_POSITION: f"tray #{self.current_tray_number}",
            State.CAPTURING_AND_STITCHING: "CAPTURE - final image is beeing taken",
            State.RETURNING: "RETURNING - tray is moving back",
        }

        self.app.set_status(texts[self.state], self.state.name)
        self.app.refresh()

    def _handle_outbound_start(self) -> None:
        """IDLE -> OUTBOUND. First door open."""
        self.state = State.OUTBOUND
        self._update_status()

    def _handle_delivery_arrival(self) -> None:
        """Door closed at delivery position - starts the QR scan in a
        background thread so the GUI stays usable while it runs."""
        threading.Thread(target=self._qr_scan_worker, daemon=True).start()

    def _qr_scan_worker(self) -> None:
        """Runs in a background thread. ALWAYS reports back to the Tk
        main thread - even if the scan crashes - otherwise the state
        machine would stay stuck in OUTBOUND forever."""
        qr_result = None
        error_message = None
        try:
            qr_result = qr_code_scanner.wait_for_qr()
        except Exception as exc:
            # logging is thread-safe - writes the full traceback to the log file
            logging.exception("QR scan worker crashed")
            error_message = f"QR scan failed: {exc}"

        self.app.root.after(0, self._on_qr_scan_done, qr_result, error_message)

    def _on_qr_scan_done(self, qr_result, error_message: str | None = None) -> None:
        if error_message is not None:
            self.app.log_event(f"Error: {error_message}", level=logging.ERROR)
        elif qr_result is None:
            self.app.log_event("Error: No QR-Code found", level=logging.ERROR)
        else:
            # QR content comes from outside - only accept valid tray
            # numbers, normalized ("01" -> "1"). Invalid content is
            # treated like "no QR found", so the capture gets skipped.
            tray_number = inventory.normalize_tray_number(qr_result.data)
            if tray_number is None:
                self.app.log_event(
                    f"Error: QR-Code contains no valid tray number: '{qr_result.data}'",
                    level=logging.ERROR,
                )
            else:
                self.current_tray_number = tray_number

        self.state = State.AT_DELIVERY_POSITION
        self._update_status()

        # Door events that arrived WHILE the scan was running were
        # ignored (state was still OUTBOUND). If the door is already
        # open again by now, catch up on the missed "2nd door open".
        if self.sensor.is_open():
            self.app.log_event("Door opened during QR scan - continuing with capture")
            self._handle_return_trigger()

    def _handle_return_trigger(self) -> None:
        """Door open (2nd time) - starts the capture+stitch in a
        background thread, same reasoning as the QR scan above."""
        self.state = State.CAPTURING_AND_STITCHING
        self._update_status()

        if self.current_tray_number is None:
            self.app.log_event("Capture skipped (no tray-nummer)", level=logging.WARNING)
            self.state = State.RETURNING
            self._update_status()
            return

        threading.Thread(
            target=self._capture_worker, args=(self.current_tray_number,), daemon=True
        ).start()

    def _run_capture_safely(self, tray_number: str):
        """Wraps capture_and_stitch so it ALWAYS returns a StitchResult,
        even if something inside crashes (cv2.error, disk full, ...).
        Used by both the automatic and the manual capture worker."""
        try:
            return camera_stitching.capture_and_stitch(
                config.USB_CAMERA_DEVICES, tray_number=tray_number
            )
        except Exception as exc:
            logging.exception("Capture worker crashed")
            return camera_stitching.StitchResult(
                success=False, error_message=f"Capture crashed: {exc}"
            )

    def _capture_worker(self, tray_number: str) -> None:
        result = self._run_capture_safely(tray_number)
        self.app.root.after(0, self._on_capture_done, result)

    def _on_capture_done(self, result) -> None:
        if result.success:
            self.app.log_event(f"Capture saved: {result.panorama_path.name}")
            # Table's "Last Capture" column should reflect the new
            # capture immediately, same as after a manual capture
            self.app._populate_tray_table(self.app.search_var.get())
        else:
            self.app.log_event(f"Error: {result.error_message}", level=logging.ERROR)

        self.state = State.RETURNING
        self._update_status()

        # Same catch-up as after the QR scan: if the door already
        # closed while capturing/stitching, that event was ignored -
        # the tray is already back, so go straight to IDLE.
        if not self.sensor.is_open():
            self.app.log_event("Door closed during capture - returning to IDLE")
            self._handle_returned()

    def _handle_returned(self) -> None:
        """RETURNING -> IDLE. Door final closing, tray is in warehouse."""
        self.current_tray_number = None
        self.state = State.IDLE
        self._update_status()

    def _handle_manual_capture_request(self, tray_number: str) -> None:
        """Triggered from the GUI's manual-capture button. Only allowed
        while IDLE and no other manual capture is already running, so
        it can't collide with the automatic door-sensor flow or with itself."""

        if self.state != State.IDLE:
            self.app.log_event("Manual capture rejected - system is busy", level=logging.WARNING)
            return

        if self._manual_capture_in_progress:
            self.app.log_event("Manual capture rejected - already running", level=logging.WARNING)
            return

        self._manual_capture_in_progress = True
        self.app.log_event(f"Manual capture started for tray {tray_number}")

        threading.Thread(
            target=self._manual_capture_worker, args=(tray_number,), daemon=True
        ).start()

    def _manual_capture_worker(self, tray_number: str) -> None:
        result = self._run_capture_safely(tray_number)
        self.app.root.after(0, self._on_manual_capture_done, result)

    def _on_manual_capture_done(self, result) -> None:
        if result.success:
            self.app.log_event(f"Manual capture saved: {result.panorama_path.name}")
        else:
            self.app.log_event(f"Error: {result.error_message}", level=logging.ERROR)

        self._manual_capture_in_progress = False
        self.app._populate_tray_table(self.app.search_var.get())

    def _on_door_change(self, is_open: bool) -> None:
        if is_open and self.state == State.IDLE:
            self._handle_outbound_start()
        elif not is_open and self.state == State.OUTBOUND:
            self._handle_delivery_arrival()
        elif is_open and self.state == State.AT_DELIVERY_POSITION:
            self._handle_return_trigger()
        elif not is_open and self.state == State.RETURNING:
            self._handle_returned()


def _set_windows_app_id() -> None:
    """Windows groups taskbar icons by an "AppUserModelID". Without its
    own ID, the program counts as python.exe and the taskbar shows the
    Python icon - no matter what iconphoto() sets. Must be called BEFORE
    the first Tk window is created. Does nothing on Linux."""
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
    flow_controll(app)
    root.mainloop()


if __name__ == "__main__":
    main()