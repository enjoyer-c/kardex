"""
Mock QR scanner for Windows testing - always finds tray number "1".
"""

from dataclasses import dataclass
from typing import Optional

import config


@dataclass
class QRResult:
    data: str
    qr_type: str


def start_stream() -> Optional[str]:
    return None


def stop_stream() -> None:
    pass


def scan_now(window_s: float = config.QR_SCAN_WINDOW_S) -> Optional[QRResult]:
    print("[qr_code_scanner_mock] Simulates a QR scan - delivers tray 1")
    return QRResult(data="1", qr_type="QRCODE")