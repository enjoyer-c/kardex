"""
Hall sensor module for detecting whether the door of the kardex shuttle is open or closed.
Calls the optional on_change callback with a bool (True = open) on every state change.
"""

from typing import Callable, Optional

import config


try:
    from gpiozero import Button
    IS_RPI = True
except (ImportError, ModuleNotFoundError):
    IS_RPI = False


class HallSensor:
    def __init__(self, on_change: Optional[Callable[[bool], None]] = None):
        self._on_change = on_change
        self._is_open = False

        # None = sensor set up fine. Otherwise holds a readable error
        # message - main.py shows it in the History, so a missing sensor
        # doesn't go unnoticed (without it, the door flow never starts)
        self.error_message: Optional[str] = None
 
        if not IS_RPI:
            self.error_message = (
                "Hall sensor NOT available - gpiozero is not installed. "
                "Door detection is disabled!"
            )
            return

        try:
            self._button = Button(
                config.HALL_SENSOR_GPIO,
                pull_up=True,
                bounce_time=config.HALL_SENSOR_BOUNCE_TIME_MS / 1000.0,
            )
        except Exception as exc:
            # e.g. GPIO already in use by another program, or no GPIO
            # access - previously this crashed the whole program on startup
            self.error_message = (
                f"Hall sensor NOT available - GPIO {config.HALL_SENSOR_GPIO} "
                f"could not be set up ({exc}). Door detection is disabled!"
            )
            return
 
        self._button.when_pressed = self._handle_change
        self._button.when_released = self._handle_change
 
        self._handle_change()  # evaluate initial state on startup

    def _handle_change(self) -> None:
        self._is_open = not self._button.is_pressed
 
        if self._on_change:
            self._on_change(self._is_open)

    def is_open(self) -> bool:
        return self._is_open

    # --- TEMP door test (remove together with config.DOOR_TEST_BUTTON) ---
    def simulate_toggle(self) -> None:
        """TEMPORARY, for testing without a magnet: flips the door state
        and fires on_change exactly like a real sensor event would.
        Works even if the real sensor isn't available (error_message set).
        A real magnet event afterwards overrides the simulated state again."""
        self._is_open = not self._is_open
        if self._on_change:
            self._on_change(self._is_open)