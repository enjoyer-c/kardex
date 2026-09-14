"""
Mock hall sensor for Windows testing.

Simulates the magnetic door sensor via keyboard input instead of GPIO.
Press Enter in the console to toggle between "door open" and "door
closed" - mirrors the on_change(bool) callback behavior of the real
hall_sensor.HallSensor exactly, so main.py doesn't need to know which
version is active.

Note: on_change is called from a background thread (the one listening
for Enter), not the Tkinter main thread. Simple StringVar updates via
app.set_status()/log_event() tend to work in practice, but this isn't
officially thread-safe - if you see odd GUI behavior (freezes,
flicker), that's the likely cause. For a test tool this is an
acceptable trade-off; flag it if it becomes a real problem.
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
            input()  # wartet auf Enter-Tastendruck in der Konsole
            self._is_open = not self._is_open
            state_text = "OFFEN" if self._is_open else "ZU"
            print(f"[hall_sensor_mock] Tuer ist jetzt: {state_text}")

            if self._on_change:
                self._on_change(self._is_open)

    def is_open(self) -> bool:
        return self._is_open