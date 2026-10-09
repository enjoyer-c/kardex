"""
Mock camera_stitching for Windows testing.
Only grabbing the frames is replaced (webcam at index 0/1, or a placeholder image) -
combining and saving is the real code from camera_stitching.py, so both behave the same.
"""

from datetime import datetime
import time

import cv2
import numpy as np

from camera_stitching import (   # noqa: F401 - re-exported, main.py uses them via this module
    FrameSet, StitchResult, combine_and_save, create_tray_folders,
)

MOCK_CAMERA_INDICES = [0, 1]


def _capture_real(index: int):
    """One frame from a real webcam, or None if there's none at this index."""
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
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:] = (60, 60, 60)
    cv2.putText(frame, label, (40, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
    return frame


def grab_frames(camera_devices) -> tuple[FrameSet | None, str | None]:
    frames = []
    for i, index in enumerate(MOCK_CAMERA_INDICES):
        frame = _capture_real(index)
        frames.append(frame if frame is not None else _synthetic_frame(f"Mock Cam {i + 1}"))
    return FrameSet(frames=frames, taken_at=time.monotonic(), taken_wall=datetime.now()), None


def capture_and_stitch(camera_devices, tray_number: str) -> StitchResult:
    frame_set, error = grab_frames(camera_devices)
    if frame_set is None:
        return StitchResult(success=False, error_message=error)
    return combine_and_save(frame_set, tray_number)