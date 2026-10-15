"""
Mock QR scanner for Windows testing - always finds tray number "1".
"""

from dataclasses import dataclass
from typing import Optional
import time

import config


@dataclass
class QRResult:
    data: str
    qr_type: str
    reader: str = "zbar"
    points: list | None = None
    seen_at: float = 0.0


def start_stream() -> Optional[str]:
    return None


def stop_stream() -> None:
    pass


def is_running() -> bool:
    return True


def scan_now(signal_time: float | None = None, window_s: float = config.QR_SCAN_WINDOW_S) -> Optional[QRResult]:
    print("[qr_code_scanner_mock] Simulates a QR scan - delivers tray 1")
    return QRResult(data="1", qr_type="QRCODE", seen_at=time.monotonic())