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
    """Creates one output folder per tray number, if it doesn't exist yet.
    Meant to be called once at program startup."""
    for shelf_number in range(config.SHELF_LOWER_LIMIT, config.SHELF_UPPER_LIMIT + 1):
        folder = config.OUTPUT_DIR / str(shelf_number)
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
    before returning. Cameras are handled strictly one at a time (open
    -> warmup -> read -> release) rather than all at once, since two
    C920s streaming simultaneously overwhelm the USB bandwidth even
    with MJPEG + a powered hub.

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

def capture_and_stitch(camera_devices: list[str], tablar_number: str) -> StitchResult:
    """Captures one frame from each camera (one at a time, not
    simultaneously - see capture_one), stitches them, and saves the
    result."""
    frames = []
    for device in camera_devices:
        success, frame, error_message = capture_one(device)
        if not success:
            return StitchResult(success=False, error_message=error_message)
        frames.append(frame)

    output_dir = config.OUTPUT_DIR / tablar_number
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime(config.TIMESTAMP_FORMAT)

    stitcher = cv2.Stitcher_create(config.STITCHER_MODE)
    stitcher.setPanoConfidenceThresh(config.STICHER_CONFIDENCE_THRESHOLD)
    status, panorama = stitcher.stitch(frames)

    if status != cv2.Stitcher_OK:
        return StitchResult(success=False, error_message=f"Stitching failed, status code: {status}")

    pano_path = output_dir / f"finalFrame_{timestamp}.jpg"
    cv2.imwrite(str(pano_path), panorama)

    enforce_max_images(output_dir, config.MAX_IMAGES_PER_TABLAR)

    return StitchResult(success=True, panorama_path=pano_path)



