"""
Mock camera_stitching for Windows testing.

Tries to use real webcams (built-in laptop camera, or USB webcams
plugged into the PC) via DirectShow. If a camera at a given index
isn't available, a synthetic placeholder frame is generated instead,
so the rest of the pipeline (stitching, saving, shelf folders) can
still be exercised without any real camera hardware attached.

camera_devices is accepted (for interface compatibility with the real
capture_and_stitch, which main.py calls with config.USB_CAMERA_DEVICES
- meaningless on Windows) but ignored; MOCK_CAMERA_INDICES below
controls which cameras are actually tried.
"""

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import cv2
import numpy as np

import config

@dataclass
class StitchResult:
    success: bool
    panorama_path: Path | None = None
    error_message: str | None = None


# Adjust to however many real webcams you have plugged in for testing.
# Indices beyond what's actually connected simply fall back to a
# synthetic frame - safe to leave at [0, 1] even with only one camera.
MOCK_CAMERA_INDICES = [0, 1]


def create_shelf_folders() -> None:
    for shelf_number in range(config.SHELF_LOWER_LIMIT, config.SHELF_UPPER_LIMIT + 1):
        folder = config.OUTPUT_DIR / str(shelf_number)
        folder.mkdir(parents=True, exist_ok=True)


def _capture_real(index: int):
    """Tries to grab one frame from a real webcam. Returns None if the
    camera isn't available or doesn't deliver a frame."""
    cam = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    try:
        if not cam.isOpened():
            return None
        for _ in range(5):  # quick warmup
            cam.read()
        ret, frame = cam.read()
        return frame if ret else None
    finally:
        cam.release()


def _synthetic_frame(label: str):
    """Generates a plain placeholder image with a text label, used
    whenever no real camera is available at a given index."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:] = (60, 60, 60)
    cv2.putText(frame, label, (40, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
    return frame


def capture_and_stitch(camera_devices, tablar_number: str) -> StitchResult:
    frames = []
    for i, index in enumerate(MOCK_CAMERA_INDICES):
        frame = _capture_real(index)
        if frame is None:
            print(f"[camera_stitching_mock] Kamera {index} nicht verfuegbar - synthetisches Bild.")
            frame = _synthetic_frame(f"Mock Cam {i + 1} - Tablar {tablar_number}")
        frames.append(frame)

    output_dir = config.OUTPUT_DIR / tablar_number
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime(config.TIMESTAMP_FORMAT)

    if len(frames) >= 2:
        stitcher = cv2.Stitcher_create(config.STITCHER_MODE)
        stitcher.setPanoConfidenceThresh(config.STICHER_CONFIDENCE_THRESHOLD)
        status, panorama = stitcher.stitch(frames)

        if status != cv2.Stitcher_OK:
            # Fallback: just place the frames side by side, so the mock
            # still produces a usable file even if "real" stitching
            # fails (e.g. two synthetic frames have no matchable
            # features at all).
            print(f"[camera_stitching_mock] Stitching fehlgeschlagen (Code {status}) - Bilder werden nebeneinandergesetzt.")
            h = min(f.shape[0] for f in frames)
            resized = [cv2.resize(f, (int(f.shape[1] * h / f.shape[0]), h)) for f in frames]
            panorama = np.concatenate(resized, axis=1)
    else:
        panorama = frames[0]

    pano_path = output_dir / f"finalFrame_{timestamp}.jpg"
    cv2.imwrite(str(pano_path), panorama)

    return StitchResult(success=True, panorama_path=pano_path)


if __name__ == "__main__":
    create_shelf_folders()
    result = capture_and_stitch([], tablar_number="TestTablar01")
    print(result)