"""
Mock QR scanner for Windows testing - always returns tray number "1",
"""

from dataclasses import dataclass
from typing import Optional

import config


@dataclass
class QRResult:
    data: str
    qr_type: str


def wait_for_qr(timeout_s: float = config.QR_SCAN_TIMEOUT_S) -> Optional[QRResult]:
    print("[qr_code_scanner_mock] Simulierter QR-Scan - liefert Tablar 1")
    return QRResult(data="1", qr_type="QRCODE")