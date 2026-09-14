"""

"""


from dataclasses import dataclass
from pathlib import Path
import cv2
from datetime import datetime

import config


@dataclass
class StitchResult:
    success: bool
    panorama_path: Path | None = None
    error_message: str | None = None

def create_shelf_folders() -> None:
    """Creates one output folder per shelf number, if it doesn't exist yet.
    Meant to be called once at program startup."""
    for shelf_number in range(config.SHELF_LOWER_LIMIT, config.SHELF_UPPER_LIMIT + 1):
        folder = config.OUTPUT_DIR / str(shelf_number)
        folder.mkdir(parents=True, exist_ok=True)

def open_camera(index: int) -> cv2.VideoCapture:
    return cv2.VideoCapture(index, config.CAP_BACKEND)

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

def capture_and_stitch(camera_indices: list[int], tablar_number: str) -> StitchResult:
    """Captures one frame from each camera, stitches them, and saves the result."""
    cams = [open_camera(i) for i in camera_indices]

    try:
        failed_cameras = [i for i, cam in zip(camera_indices, cams) if not cam.isOpened()]
        if failed_cameras:
            return StitchResult(success=False, error_message=f"Camera(s) failed to open: {failed_cameras}")

        for cam in cams:
            warmup(cam)

        frames = []
        for i, cam in zip(camera_indices, cams):
            ret, frame = cam.read()
            if not ret:
                return StitchResult(success=False, error_message=f"Camera {i}: failed to read frame")
            frames.append(frame)

        output_dir = config.OUTPUT_DIR / tablar_number
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime(config.TIMESTAMP_FORMAT)

        # Stitching SCANS mode assumes cameras are facing the same flat surface
        stitcher = cv2.Stitcher_create(config.STITCHER_MODE)
        stitcher.setPanoConfidenceThresh(config.STICHER_CONFIDENCE_THRESHOLD)
        status, panorama = stitcher.stitch(frames)

        if status != cv2.Stitcher_OK:
            return StitchResult(success=False, error_message=f"Stitching failed, status code: {status}")

        pano_path = output_dir / f"finalFrame_{timestamp}.jpg"
        cv2.imwrite(str(pano_path), panorama)

        enforce_max_images(output_dir, config.MAX_IMAGES_PER_TABLAR)

        return StitchResult(success=True, panorama_path=pano_path)

    finally:
        for cam in cams:
            cam.release()


