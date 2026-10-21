"""
Ribbon camera (Raspberry Pi HQ Camera) for QR code scanning.

The camera runs permanently AND is scanned permanently: a background thread reads every newest frame and looks for
a QR code (see _scan_loop). So when the door opens, the answer is usually already there - scan_now() only has to look
at what the loop has seen around the door signal, it never starts the camera or waits for exposure.

Two QR readers, one after another (see scan_frame) - each one fails on different pictures:
    aruco   OpenCV's QRCodeDetectorAruco (OpenCV >= 4.7) - reads our labels on the reflective metal best
    zbar    pyzbar - fallback, often reads the code first while the tray is arriving
Which readers are active is written to the log when the stream starts (without aruco = OpenCV too old).

Only the ribbon-cam live preview (Camera Setup) stops the stream for a while, because two programs can't use the
camera at the same time - see stop_stream / start_stream.

Note on colors: picamera2's "RGB888" format delivers the pixels in B, G, R order - i.e. exactly what OpenCV expects.
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
    reader: str = "aruco"         # which reader found it (see scan_frame) - for the log
    points: list | None = None    # corners [(x, y), ...] in the frame, if the reader reports them (live preview outline)
    seen_at: float = 0.0          # time.monotonic() when the frame was taken


# --- Readers ------------------------------------------------------------------------

_aruco_detector = cv2.QRCodeDetectorAruco() if hasattr(cv2, "QRCodeDetectorAruco") else None


def _aruco(gray):
    data, points, _ = _aruco_detector.detectAndDecode(gray)
    if not data:
        return None
    corners = [(int(x), int(y)) for x, y in points.reshape(-1, 2)] if points is not None else None
    return data, corners


def _zbar(gray):
    for r in decode(gray):
        if r.type == "QRCODE":
            return r.data.decode("utf-8"), [(p.x, p.y) for p in r.polygon]
    return None


# Order: main reader first, the fallback only runs if it found nothing
READERS = [("aruco", _aruco), ("zbar", _zbar)] if _aruco_detector is not None else [("zbar", _zbar)]
MAIN_READER = READERS[0][0]


def reader_names() -> str:
    return ", ".join(name for name, _ in READERS)


def scan_frame(frame) -> Optional[QRResult]:
    """Looks for a QR code in a single frame (BGR array from picamera2). Returns the first QR code found, or None.
    A reader that crashes is skipped - the next one still gets its chance."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    for name, read in READERS:
        try:
            found = read(gray)
        except Exception:
            logging.exception("QR reader '%s' crashed", name)
            continue
        if found:
            data, points = found
            return QRResult(data=data, qr_type="QRCODE", reader=name, points=points)
    return None


# --- Camera + permanent scanning ----------------------------------------------------

_picam: "Picamera2 | None" = None
_start_stop_lock = threading.Lock()     # start_stream / stop_stream never at the same time
_stop_event = threading.Event()
_thread: threading.Thread | None = None

# Shared between the scan loop and scan_now - always accessed with _cond held
_cond = threading.Condition()
_last_frame_time = 0.0          # time.monotonic() when the newest scanned frame was taken
_hits: list[QRResult] = []      # QR codes seen in the last seconds (oldest first)


def _open_camera() -> "Picamera2":
    picam = Picamera2()
    try:
        picam.configure(picam.create_video_configuration(
            main={"size": config.QR_CAPTURE_SIZE, "format": "RGB888"}
        ))
        picam.start()
    except Exception:
        picam.close()   # otherwise the camera stays "busy" until the program ends
        raise
    return picam


def _close_camera(picam) -> None:
    try:
        picam.stop()
        picam.close()
    except Exception:
        logging.exception("Ribbon cam could not be stopped cleanly")


def _scan_loop() -> None:
    """Background thread: newest frame -> scan -> remember the result. Runs until stop_stream().
    Never dies on an error: camera errors lead to a camera restart, everything else is logged and the loop continues."""
    global _picam, _last_frame_time
    errors_in_a_row = 0
    visible: str | None = None      # QR content currently in view (for the "in view / out of view" log lines)
    last_seen = 0.0

    while not _stop_event.is_set():
        loop_start = time.monotonic()
        try:
            frame = _picam.capture_array()
            taken = time.monotonic()
            errors_in_a_row = 0
        except Exception as exc:
            errors_in_a_row += 1
            logging.warning("Ribbon cam: could not read a frame (%s)", exc)
            if errors_in_a_row >= config.QR_CAMERA_RESTART_AFTER:
                logging.error("Ribbon cam: %d errors in a row - restarting the camera", errors_in_a_row)
                _close_camera(_picam)
                try:
                    _picam = _open_camera()
                    errors_in_a_row = 0
                    logging.info("Ribbon cam restarted")
                except Exception as restart_exc:
                    logging.error("Ribbon cam restart failed: %s", restart_exc)
            _stop_event.wait(0.5)
            continue

        try:
            result = scan_frame(frame)
        except Exception:
            logging.exception("QR scan crashed")
            result = None

        with _cond:
            _last_frame_time = taken
            if result is not None:
                result.seen_at = taken
                _hits.append(result)
            # Only keep what scan_now could still ask for
            while _hits and taken - _hits[0].seen_at > config.QR_SCAN_WINDOW_S + config.QR_RECENT_S + 5:
                _hits.pop(0)
            _cond.notify_all()

        # Log when a code comes into view / leaves - shows the exact timing next to the door events in the log.
        # "Out of view" only after QR_GONE_S without a code, so a single unreadable frame doesn't spam the log.
        if result is not None:
            last_seen = taken
            if result.data != visible:
                visible = result.data
                logging.info("  details: QR code in view: '%s' (reader: %s)", result.data, result.reader)
        elif visible is not None and taken - last_seen > config.QR_GONE_S:
            logging.info("  details: QR code '%s' out of view", visible)
            visible = None

        rest = config.QR_SCAN_INTERVAL_S - (time.monotonic() - loop_start)
        if rest > 0:
            _stop_event.wait(rest)


def start_stream() -> Optional[str]:
    """Opens the ribbon camera and starts the permanent scanning. Returns None on success, otherwise an error text.
    Does nothing if it's already running."""
    global _picam, _thread
    if not HAS_PICAMERA:
        return "picamera2 is not installed - trays can't be detected"
    with _start_stop_lock:
        if _thread is not None and _thread.is_alive():
            return None
        try:
            _picam = _open_camera()
        except Exception as exc:
            _picam = None
            return f"Ribbon cam could not be started: {exc}"
        with _cond:
            _hits.clear()
        _stop_event.clear()
        _thread = threading.Thread(target=_scan_loop, name="qr-scan", daemon=True)
        _thread.start()
    logging.info("Ribbon cam stream started (QR readers: %s)", reader_names())
    if _aruco_detector is None:
        logging.warning("OpenCV %s has no aruco QR reader (needs >= 4.7) - only zbar is used", cv2.__version__)
    return None


def stop_stream() -> None:
    """Stops the scanning and releases the ribbon camera (e.g. for the live preview or at program end)."""
    global _picam, _thread
    with _start_stop_lock:
        if _thread is None:
            return
        _stop_event.set()
        with _cond:
            _cond.notify_all()   # wake up a waiting scan_now
        _thread.join(timeout=5)
        _thread = None
        if _picam is not None:
            _close_camera(_picam)
            _picam = None
    logging.info("Ribbon cam stream stopped")


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


# --- Door opening -------------------------------------------------------------------

def scan_now(signal_time: float | None = None, window_s: float = config.QR_SCAN_WINDOW_S) -> Optional[QRResult]:
    """Which QR code is in front of the camera at the door opening (signal_time = time.monotonic() of the door signal)?

    Accepts a code seen from QR_RECENT_S BEFORE the signal (usually it's already there -> answer immediately)
    up to window_s AFTER the signal. Waits until a frame from the end of that window was scanned, so the whole
    window is really covered. Returns the first code seen in that window, or None.
    Raises RuntimeError if the ribbon cam isn't running."""
    if signal_time is None:
        signal_time = time.monotonic()
    window_start = signal_time - config.QR_RECENT_S
    window_end = signal_time + window_s
    give_up = window_end + config.QR_SCAN_GRACE_S    # scanning one frame can take a moment on the Pi

    with _cond:
        while True:
            if not is_running():
                raise RuntimeError("Ribbon cam is not running (live preview open?)")
            for hit in _hits:
                if window_start <= hit.seen_at <= window_end:
                    return hit
            if _last_frame_time >= window_end or time.monotonic() >= give_up:
                return None
            _cond.wait(timeout=0.5)