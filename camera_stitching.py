"""
Handles the USB cameras and panorama stitching.
Cameras are opened, warmed up, read, and released on every single
capture - NOT kept open persistently.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import threading
import cv2
from datetime import datetime

import config


@dataclass
class StitchResult:
    success: bool
    panorama_path: Path | None = None
    error_message: str | None = None

_capture_lock = threading.Lock()


class CamerasBusyError(RuntimeError):
    """Raised by exclusive_cameras() if the cameras are already in use."""


@contextmanager
def exclusive_cameras():
    """Reserves ALL USB cameras for the duration of the with-block, using
    the same lock as capture_and_stitch - so e.g. the Camera Setup can
    never open a camera while a real capture is running (or vice versa).
    Non-blocking, same as capture_and_stitch: if the cameras are already
    in use, CamerasBusyError is raised immediately instead of waiting."""
    if not _capture_lock.acquire(blocking=False):
        raise CamerasBusyError("Cameras are busy - a capture is currently running")
    try:
        yield
    finally:
        _capture_lock.release()


def create_tray_folders() -> None:
    """Creates one output folder per tray number, if it doesn't exist yet.
    Meant to be called once at program startup."""
    for tray_number in range(config.TRAY_LOWER_LIMIT, config.TRAY_UPPER_LIMIT + 1):
        folder = config.OUTPUT_DIR / str(tray_number)
        folder.mkdir(parents=True, exist_ok=True)


def open_camera(device: str) -> cv2.VideoCapture:
    cam = cv2.VideoCapture(device, config.CAP_BACKEND)
    cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*config.USB_CAMERA_FOURCC))
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, config.USB_CAMERA_RESOLUTION[0])
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, config.USB_CAMERA_RESOLUTION[1])
    return cam


def warmup(cam: cv2.VideoCapture, frames: int = config.USB_CAMERA_WARMUP_FRAMES) -> None:
    """Reads and discards a number of frames to let exposure/focus settle."""
    for _ in range(frames):
        cam.read()


def enforce_max_images(output_dir: Path, max_images: int) -> None:
    """Deletes the oldest panorama images if more than max_images are stored."""
    images = sorted(output_dir.glob("finalFrame_*.jpg"))
    while len(images) > max_images:
        oldest = images.pop(0)
        oldest.unlink()


def capture_one(device: str) -> tuple[bool, "cv2.typing.MatLike | None", str | None]:
    """Opens a single camera, captures one frame, and releases it again
    before returning (open -> warmup -> read -> release).
    Returns (success, frame, error_message).
    """
    cam = open_camera(device)
    try:
        if not cam.isOpened():
            return False, None, f"Camera failed to open: {device}"

        warmup(cam)

        ret, frame = cam.read()
        if not ret:
            return False, None, f"Camera {device}: failed to read frame"

        return True, frame, None
    finally:
        cam.release()


def capture_and_stitch(camera_devices: list[str], tray_number: str) -> StitchResult:
    """Captures one frame from each camera IN PARALLEL. Each camera is still 
    individually opened. Stitches captures, and saves the result. Refuses to run
    if a capture is already in progress."""

    if not _capture_lock.acquire(blocking=False):
        return StitchResult(success=False, error_message="Capture already in progress - request ignored")

    try:
        results: list[tuple[bool, "cv2.typing.MatLike | None", str | None] | None] = [None] * len(camera_devices)

        def _worker(index: int, device: str) -> None:
            try:
                results[index] = capture_one(device)
            except Exception as exc:
                results[index] = (False, None, f"Unexpected error on {device}: {exc}")

        threads = [
            threading.Thread(target=_worker, args=(i, device))
            for i, device in enumerate(camera_devices)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        frames = []
        for success, frame, error_message in results:
            if not success:
                return StitchResult(success=False, error_message=error_message)
            frames.append(frame)

        output_dir = config.OUTPUT_DIR / tray_number
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime(config.TIMESTAMP_FORMAT)

        stitcher = cv2.Stitcher_create(config.STITCHER_MODE)
        stitcher.setPanoConfidenceThresh(config.STICHER_CONFIDENCE_THRESHOLD)
        status, panorama = stitcher.stitch(frames)

        if status != cv2.Stitcher_OK:
            return StitchResult(success=False, error_message=f"Stitching failed, status code: {status}")

        pano_path = output_dir / f"finalFrame_{timestamp}.jpg"

        # imwrite doesn't raise on failure (disk full, SSD gone, no write
        # permission) - it just returns False. Without this check the
        # capture would be reported as "saved" although no file exists.
        # Also important: enforce_max_images below must NOT run then,
        # otherwise it would delete an old image without a new one.
        if not cv2.imwrite(str(pano_path), panorama):
            return StitchResult(success=False, error_message=f"Could not save image: {pano_path}")

        enforce_max_images(output_dir, config.MAX_IMAGES_PER_TRAY)

        return StitchResult(success=True, panorama_path=pano_path)
    finally:
        _capture_lock.release()