from __future__ import annotations
import tkinter as tk
from enum import Enum, auto
import logging
import sys


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


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

class State(Enum):
    IDLE = auto()                    # Door closed, waiting for a new request
    OUTBOUND = auto()                # Door open (1st time) - tablar moving to delivery position
    AT_DELIVERY_POSITION = auto()    # Door closed - QR gets scanned immediately here, then waits while user loads/unloads
    CAPTURING_AND_STITCHING = auto() # Door open (2nd time) - take photos + stitch before tablar starts moving
    RETURNING = auto()               # Tray driving back into the warehouse, door closing

class flow_controll:
    def __init__(self, app: gui.App):
        self.app = app
        self.state = State.IDLE
        self.current_tablar_number: str | None = None

        self.sensor = hall_sensor.HallSensor(on_change=self._on_door_change)

        self._update_status()

    def _update_status(self) -> None:
        texts = {
            State.IDLE: "IDLE - waiting for Door to open",
            State.OUTBOUND: "tray is moving to final position",
            State.AT_DELIVERY_POSITION: f"tray is on final position - tray # {self.current_tablar_number}",
            State.CAPTURING_AND_STITCHING: "capature tray content",
            State.RETURNING: "tray is moving back",
        }
        
        logging.info(f"Condition: {self.state.name}")

        self.app.set_status(texts[self.state])
        self.app.refresh()


    def _handle_outbound_start(self) -> None:
        """IDLE -> OUTBOUND. First door open."""
        self.state = State.OUTBOUND
        self._update_status()

    def _handle_delivery_arrival(self) -> None:
        qr_result = qr_code_scanner.wait_for_qr()
        if qr_result is None:
            logging.error("No QR-Code found - Capture skipped.")
            self.app.log_event("Error: No QR-Code found")
        else:
            self.current_tablar_number = qr_result.data

        self.state = State.AT_DELIVERY_POSITION  
        self._update_status()


    def _handle_return_trigger(self) -> None:
        self.state = State.CAPTURING_AND_STITCHING
        self._update_status()

        if self.current_tablar_number is None:
            logging.warning("No tray-number available (QR scan failed earlier) - skipping capture.")
            self.app.log_event("Capture skipped (no tray-nummer)")
        else:
            result = camera_stitching.capture_and_stitch(
                config.USB_CAMERA_DEVICES, tablar_number=self.current_tablar_number
            )
            if result.success:
                logging.info(f"Capture saved: {result.panorama_path}")
                self.app.log_event(f"Capture saved: {result.panorama_path.name}")
            else:
                logging.error(f"Capture failed: {result.error_message}")
                self.app.log_event(f"Error: {result.error_message}")

        self.state = State.RETURNING
        self._update_status()


    def _handle_returned(self) -> None:
        """RETURNING -> IDLE. Door final closing, tray is in warehouse."""
        self.current_tablar_number = None
        self.state = State.IDLE
        self._update_status()


    def _on_door_change(self, is_open: bool) -> None:
        if is_open and self.state == State.IDLE:
            self._handle_outbound_start()
        elif not is_open and self.state == State.OUTBOUND:
            self._handle_delivery_arrival()
        elif is_open and self.state == State.AT_DELIVERY_POSITION:
            self._handle_return_trigger()
        elif not is_open and self.state == State.RETURNING:
            self._handle_returned()

def main() -> None:
    camera_stitching.create_shelf_folders()

    root = tk.Tk()
    app = gui.App(root)
    flow_controll(app)
    root.mainloop()

if __name__ == "__main__":
    main()
