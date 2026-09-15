"""
Mock hall sensor for Windows testing.

Simulates the magnetic door sensor via keyboard input instead of GPIO.
Press Enter in the console to toggle between "door open" and "door
closed"
"""

from typing import Callable, Optional
import threading


class HallSensor:
    def __init__(self, on_change: Optional[Callable[[bool], None]] = None):
        self._on_change = on_change
        self._is_open = False

        print("[hall_sensor_mock] Enter druecken zum Umschalten der Tuer (offen/zu).")

        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self) -> None:
        while True:
            input()  # wait for ENTER key 
            self._is_open = not self._is_open
            state_text = "OFFEN" if self._is_open else "ZU"
            print(f"[hall_sensor_mock] Tuer ist jetzt: {state_text}")

            if self._on_change:
                self._on_change(self._is_open)

    def is_open(self) -> bool:
        return self._is_open