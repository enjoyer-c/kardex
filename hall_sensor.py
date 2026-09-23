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
 
        if not IS_RPI:
            print("[hall_sensor] Not running - sensor disabled.")
            return


        self._button = Button(
            config.HALL_SENSOR_GPIO,
            pull_up=True,
            bounce_time=config.HALL_SENSOR_BOUNCE_TIME_MS / 1000.0,
        )
 
        self._button.when_pressed = self._handle_change
        self._button.when_released = self._handle_change
 
        self._handle_change()  # evaluate initial state on startup


    def _handle_change(self) -> None:
        self._is_open = not self._button.is_pressed
 
        if self._on_change:
            self._on_change(self._is_open)

 
    def is_open(self) -> bool:
        return self._is_open

