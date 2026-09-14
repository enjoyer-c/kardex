"""
Wraps the ribbon camera (Raspberry Pi HQ Camera) for QR code scanning.
Captures still images via picamera2 and decodes QR codes with pyzbar.
"""

from dataclasses import dataclass
from typing import Optional
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
 
def _init_camera() -> "Picamera2":
    picam = Picamera2()
    still_config = picam.create_still_configuration(
        main={"size": config.QR_CAPTURE_SIZE, "format": "RGB888"}
    )
    picam.configure(still_config)
    picam.start()
    time.sleep(1) 
    return picam

def scan_frame(frame) -> Optional[QRResult]:
    """Looks for a QR code in a single frame (RGB array from picamera2).
    Returns the first QR code found, or None if none is detected.
    """
    # picamera2 delivers RGB, not BGR - COLOR_RGB2GRAY (not BGR2GRAY!)
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    results = [r for r in decode(gray) if r.type == "QRCODE"]
 
    if not results:
        return None
 
    obj = results[0]  
    return QRResult(data=obj.data.decode("utf-8"), qr_type=obj.type)
 
def wait_for_qr(timeout_s: float = config.QR_SCAN_TIMEOUT_S) -> Optional[QRResult]:
    """Repeatedly captures frames and tries to decode a QR code, until
    either one is found or the timeout is reached.
    """
    if not HAS_PICAMERA:
        print("[qr_code_scanner] picamera2 not available - cannot scan.")
        return None
 
    picam = _init_camera()
    try:
        start = time.monotonic()
        while time.monotonic() - start < timeout_s:
            frame = picam.capture_array()
            result = scan_frame(frame)
            if result is not None:
                return result
        return None
    finally:
        picam.stop()
        picam.close()
