"""
Ribbon camera (Raspberry Pi HQ Camera) for QR code scanning, via picamera2 + pyzbar.

The camera runs permanently (start_stream at program start). A scan only takes the newest
frames and decodes them - no camera start, no waiting for exposure.
Only the ribbon-cam live preview (Camera Setup) stops the stream for a while, because two
programs can't use the camera at the same time - see stop_stream / start_stream.
"""

from dataclasses import dataclass
from datetime import datetime
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
    reader: str = "zbar"   # which reader found it (see scan_frame) - for the log


_cv2_qr_detector = cv2.QRCodeDetector()


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


def _zbar(gray) -> Optional[str]:
    results = [r for r in decode(gray) if r.type == "QRCODE"]
    return results[0].data.decode("utf-8") if results else None


def _opencv(gray) -> Optional[str]:
    data, _points, _ = _cv2_qr_detector.detectAndDecode(gray)
    return data or None


def scan_frame(frame) -> Optional[QRResult]:
    """Looks for a QR code in a single frame (RGB array from picamera2). Returns the first QR code found, or None.
    Tries several readers - zbar first (fast); only if it finds nothing:
      - zbar on the inverted picture (zbar can't read white-on-black codes)
      - the OpenCV QR reader (works differently, reads some codes zbar misses)"""
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    readers = (
        ("zbar", lambda: _zbar(gray)),
        ("zbar inverted", lambda: _zbar(255 - gray)),
        ("opencv", lambda: _opencv(gray)),
    )
    for name, read in readers:
        try:
            data = read()
        except Exception:
            logging.exception("QR reader '%s' crashed", name)
            continue
        if data:
            return QRResult(data=data, qr_type="QRCODE", reader=name)
    return None


def _save_debug_frame(frame) -> Optional[str]:
    """Saves what the ribbon cam saw when no QR code was found, so it can be checked afterwards.
    Keeps only the newest QR_DEBUG_KEEP pictures. Returns the file name, or None if saving failed."""
    try:
        config.QR_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        path = config.QR_DEBUG_DIR / f"no_qr_{datetime.now().strftime(config.TIMESTAMP_FORMAT)}.jpg"
        cv2.imwrite(str(path), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        old = sorted(config.QR_DEBUG_DIR.glob("no_qr_*.jpg"))
        for file in old[:-config.QR_DEBUG_KEEP]:
            file.unlink()
        return path.name
    except Exception:
        logging.exception("Could not save the QR debug picture")
        return None


def scan_now(window_s: float = config.QR_SCAN_WINDOW_S) -> Optional[QRResult]:
    """Reads the newest frames of the running stream until a QR code is found or window_s is over.
    Returns None if there is no QR code. Raises RuntimeError if the camera isn't running."""
    with _lock:
        if _picam is None:
            raise RuntimeError("Ribbon cam is not running (live preview open?)")
        end = time.monotonic() + window_s
        while True:
            frame = _picam.capture_array()
            result = scan_frame(frame)
            if result is not None:
                if result.reader != "zbar":
                    logging.info("  details: QR code only readable with the '%s' reader", result.reader)
                return result
            if time.monotonic() >= end:
                saved = _save_debug_frame(frame)
                if saved:
                    logging.info("  details: no QR code - ribbon cam picture saved as %s/%s", config.QR_DEBUG_DIR.name, saved)
                return None