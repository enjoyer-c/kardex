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
    def __init__(self, app: gui.App):
        self.app = app
        self.state = State.IDLE
        self.current_tray_number: str | None = None
        # Tracks a manual capture separately from self.state, since
        # manual capture never changes self.state (stays IDLE) - needed
        # so a second manual-capture click while one is still running
        # in the background gets a clean, friendly rejection instead of
        # relying only on camera_stitching's lower-level lock.
        self._manual_capture_in_progress = False

        # on_change fires on gpiozero's own background thread (or the
        # mock's threading.Thread) - root.after(0, ...) marshals it back
        # onto the Tk main thread before any GUI code runs, since Tkinter
        # widgets are not thread-safe to touch from elsewhere.
        self.sensor = hall_sensor.HallSensor(
            on_change=lambda is_open: self.app.root.after(0, self._on_door_change, is_open)
        )
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
        background thread so the GUI (search, arrow-key browsing, etc.)
        stays usable while it runs, instead of freezing for however
        long the scan takes (usually near-instant, but up to
        QR_SCAN_TIMEOUT_S in the worst case)."""
        threading.Thread(target=self._qr_scan_worker, daemon=True).start()

    def _qr_scan_worker(self) -> None:
        qr_result = qr_code_scanner.wait_for_qr()
        # Hand the result back to the Tk main thread - GUI/state must
        # only ever be touched from there.
        self.app.root.after(0, self._on_qr_scan_done, qr_result)

    def _on_qr_scan_done(self, qr_result) -> None:
        if qr_result is None:
            self.app.log_event("Error: No QR-Code found", level=logging.ERROR)
        else:
            self.current_tray_number = qr_result.data

        self.state = State.AT_DELIVERY_POSITION
        self._update_status()


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

    def _capture_worker(self, tray_number: str) -> None:
        result = camera_stitching.capture_and_stitch(
            config.USB_CAMERA_DEVICES, tray_number=tray_number
        )
        self.app.root.after(0, self._on_capture_done, result)

    def _on_capture_done(self, result) -> None:
        if result.success:
            self.app.log_event(f"Capture saved: {result.panorama_path.name}")
        else:
            self.app.log_event(f"Error: {result.error_message}", level=logging.ERROR)

        self.state = State.RETURNING
        self._update_status()


    def _handle_returned(self) -> None:
        """RETURNING -> IDLE. Door final closing, tray is in warehouse."""
        self.current_tray_number = None
        self.state = State.IDLE
        self._update_status()


    def _handle_manual_capture_request(self, tray_number: str) -> None:
        """Triggered from the GUI's manual-capture button. Only allowed
        while IDLE and no other manual capture is already running, so
        it can't collide with the automatic door-sensor flow or with
        itself (which both also drive the cameras)."""

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
        result = camera_stitching.capture_and_stitch(
            config.USB_CAMERA_DEVICES, tray_number=tray_number
        )
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


def _handle_callback_exception(exc, val, tb) -> None:
    logging.error("Unhandled GUI exception:\n%s", "".join(traceback.format_exception(exc, val, tb)))


def main() -> None:
    camera_stitching.create_tray_folders()

    root = tk.Tk()
    root.report_callback_exception = _handle_callback_exception
    if sys.platform.startswith("linux"):
        root.attributes("-fullscreen", True)
        root.bind("<Escape>", lambda event: root.attributes("-fullscreen", False))

    app = gui.App(root)
    app.load_history_from_log_file(config.LOG_FILE)
    flow_controll(app)
    root.mainloop()


if __name__ == "__main__":
    main()