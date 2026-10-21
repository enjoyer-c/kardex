"""
Keeps every USB camera open permanently and continuously pulls frames in the background.

grab() only fetches the raw frame from the driver, retrieve() decodes it.
"""

from __future__ import annotations

import subprocess
import sys
import logging
import threading
import time
from pathlib import Path

import cv2

import config

def apply_controls(device: str) -> None:
    """Sets USB_CAMERA_CONTROLS via v4l2-ctl - one call per control, in dict order
    (the C920 rejects focus_absolute while autofocus is still on)."""
    if not sys.platform.startswith("linux"):
        return   # Windows dev: no v4l2-ctl
    for name, value in config.USB_CAMERA_CONTROLS.items():
        try:
            result = subprocess.run(
                ["v4l2-ctl", "-d", device, "-c", f"{name}={value}"],
                capture_output=True, text=True, timeout=2,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logging.warning("Camera control %s=%s could not be set (%s): %s", name, value, exc, device)
            continue
        if result.returncode != 0:
            logging.warning("Camera control %s=%s failed (%s): %s", name, value, result.stderr.strip(), device)


def open_camera(device: str) -> cv2.VideoCapture:
    cam = cv2.VideoCapture(device, config.CAP_BACKEND)
    cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*config.USB_CAMERA_FOURCC))
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, config.USB_CAMERA_RESOLUTION[0])
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, config.USB_CAMERA_RESOLUTION[1])
    if config.USB_CAMERA_FPS:
        cam.set(cv2.CAP_PROP_FPS, config.USB_CAMERA_FPS)
    if cam.isOpened():
        apply_controls(device)
    return cam


class CameraStream:
    """One permanently open USB camera with its own background thread."""

    def __init__(self, device: str):
        self.device = device
        # Protects self._cam: grab() (background thread) and retrieve() (capture) must never run at the same time
        self._lock = threading.Lock()
        self._cam: cv2.VideoCapture | None = None
        self._last_grab = 0.0          # time.monotonic() of the last successful grab
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"cam-{Path(device).name}"
        )
        self._thread.start()

    # --- Background thread ----------------------------------------------------

    def _run(self) -> None:
        was_connected = False
        while self._running:
            if self._cam is None:
                cam = open_camera(self.device)
                if not cam.isOpened():
                    cam.release()
                    self._sleep(config.USB_CAMERA_RECONNECT_S)
                    continue
                with self._lock:
                    self._cam = cam
                logging.info("USB camera stream started: %s", self.device)
                was_connected = True

            with self._lock:
                ok = self._cam.grab()
                if ok:
                    self._last_grab = time.monotonic()

            if not ok:
                if was_connected:
                    logging.warning("USB camera delivers no frames - trying to reconnect: %s", self.device)
                    was_connected = False
                self._close()
                self._sleep(config.USB_CAMERA_RECONNECT_S)

        self._close()

    def _close(self) -> None:
        with self._lock:
            if self._cam is not None:
                self._cam.release()
                self._cam = None

    def _sleep(self, seconds: float) -> None:
        """Sleep that ends early when stop() is called."""
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            time.sleep(0.1)

    # --- Called from other threads -------------------------------------------

    def stop(self) -> None:
        """Ends the background thread - it releases the camera itself. Doesn't wait."""
        self._running = False

    def latest_frame(self) -> tuple["cv2.typing.MatLike | None", str | None]:
        """Decodes the newest grabbed frame. Returns (frame, None) or (None, error text)."""
        # Timeout: if the camera hangs inside grab() (e.g. just unplugged), don't block the capture
        if not self._lock.acquire(timeout=0.5):
            return None, f"Camera not responding: {self.device}"
        try:
            if self._cam is None:
                return None, f"Camera not connected: {self.device}"
            age = time.monotonic() - self._last_grab
            if age > config.USB_CAMERA_MAX_FRAME_AGE_S:
                return None, f"Camera delivers no fresh frames (last one {age:.1f}s old): {self.device}"
            ok, frame = self._cam.retrieve()
        finally:
            self._lock.release()

        if not ok or frame is None:
            return None, f"Camera frame could not be decoded: {self.device}"
        return frame, None


# --- All streams --------------------------------------------------------------

_streams: dict[str, CameraStream] = {}
_streams_lock = threading.Lock()


def sync(devices: list[str]) -> None:
    """Makes exactly these devices stream: starts missing streams, stops the ones not listed anymore."""
    with _streams_lock:
        for device in list(_streams):
            if device not in devices:
                _streams.pop(device).stop()
                logging.info("USB camera stream stopped: %s", device)
        for device in devices:
            if device not in _streams:
                _streams[device] = CameraStream(device)


def ensure(devices: list[str]) -> None:
    """Starts streams for devices that don't have one yet. Never stops anything."""
    with _streams_lock:
        for device in devices:
            if device not in _streams:
                _streams[device] = CameraStream(device)


def stop_all() -> None:
    with _streams_lock:
        for stream in _streams.values():
            stream.stop()
        _streams.clear()


def get_frame(device: str, wait_s: float = 0.0) -> tuple["cv2.typing.MatLike | None", str | None]:
    """Newest frame of one camera. With wait_s > 0, waits that long for a first fresh frame"""
    with _streams_lock:
        stream = _streams.get(device)
    if stream is None:
        return None, f"No stream running for camera: {device}"

    deadline = time.monotonic() + wait_s
    while True:
        frame, error = stream.latest_frame()
        if frame is not None or time.monotonic() >= deadline:
            return frame, error
        time.sleep(0.05)