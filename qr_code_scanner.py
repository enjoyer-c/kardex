"""
Ribbon camera (Raspberry Pi HQ Camera) for QR code scanning, via picamera2 + pyzbar.

The camera runs permanently (start_stream at program start). A scan only takes the newest
frames and decodes them - no camera start, no waiting for exposure.
Only the ribbon-cam live preview (Camera Setup) stops the stream for a while, because two
programs can't use the camera at the same time - see stop_stream / start_stream.
"""

from dataclasses import dataclass
from typing import Optional
import logging
import threading
import time

import cv2
from pyzbar.pyzbar import decode

import config


try:
    from picamera2 import Picamera2
    HAS_PICAMERA = True
except (ImportError, ModuleNotFoundError):
    HAS_PICAMERA = False


@dataclass
class QRResult:
    data: str
    qr_type: str


_picam: "Picamera2 | None" = None
_lock = threading.Lock()   # start / stop / scan never at the same time


def start_stream() -> Optional[str]:
    """Opens the ribbon camera and keeps it running. Returns None on success, otherwise an error text.
    Does nothing if it's already running."""
    global _picam
    if not HAS_PICAMERA:
        return "picamera2 is not installed - trays can't be detected"
    with _lock:
        if _picam is not None:
            return None
        try:
            picam = Picamera2()
            picam.configure(picam.create_video_configuration(
                main={"size": config.QR_CAPTURE_SIZE, "format": "RGB888"}
            ))
            picam.start()
        except Exception as exc:
            return f"Ribbon cam could not be started: {exc}"
        _picam = picam
    logging.info("Ribbon cam stream started")
    return None


def stop_stream() -> None:
    """Releases the ribbon camera (e.g. for the live preview or at program end)."""
    global _picam
    with _lock:
        if _picam is None:
            return
        try:
            _picam.stop()
            _picam.close()
        except Exception:
            logging.exception("Ribbon cam could not be stopped cleanly")
        _picam = None
    logging.info("Ribbon cam stream stopped")


def scan_frame(frame) -> Optional[QRResult]:
    """Looks for a QR code in a single frame (RGB array from picamera2). Returns the first QR code found, or None."""
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    results = [r for r in decode(gray) if r.type == "QRCODE"]
    if not results:
        return None
    return QRResult(data=results[0].data.decode("utf-8"), qr_type=results[0].type)


def scan_now(window_s: float = config.QR_SCAN_WINDOW_S) -> Optional[QRResult]:
    """Reads the newest frames of the running stream until a QR code is found or window_s is over.
    Returns None if there is no QR code. Raises RuntimeError if the camera isn't running."""
    with _lock:
        if _picam is None:
            raise RuntimeError("Ribbon cam is not running (live preview open?)")
        end = time.monotonic() + window_s
        while True:
            result = scan_frame(_picam.capture_array())
            if result is not None or time.monotonic() >= end:
                return result