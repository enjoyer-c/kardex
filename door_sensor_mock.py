"""
Mock door sensor for Windows testing.
Simulates the magnetic door sensor via keyboard input instead of GPIO.
Press Enter in the console to toggle between "door open" and "door closed".
"""

from typing import Callable, Optional
import threading


class DoorSensor:
    def __init__(self, on_change: Optional[Callable[[bool], None]] = None):
        self._on_change = on_change
        self._is_open = False

        print("[door_sensor_mock] Press Enter to toggle the door (open/closed).")

        # Like the real sensor: report the initial state once at startup
        if self._on_change:
            self._on_change(self._is_open)

        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self) -> None:
        while True:
            input()  # wait for the Enter key
            self._is_open = not self._is_open
            state_text = "OPEN" if self._is_open else "CLOSED"
            print(f"[door_sensor_mock] Door: {state_text}")

            if self._on_change:
                self._on_change(self._is_open)

    def is_open(self) -> bool:
        return self._is_open