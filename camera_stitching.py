"""
Builds the final tray picture from the USB cameras. The cameras themselves stay open permanently (see camera_streams.py) -
a capture only takes the newest frame of each camera, then stitches / places them side by side and saves the result.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import json
import logging
import threading
import time
import cv2
from datetime import datetime

import config
import camera_streams


@dataclass
class StitchResult:
    success: bool
    panorama_path: Path | None = None
    error_message: str | None = None

_capture_lock = threading.Lock()

PANORAMA_MODES = ("stitch", "side_by_side")


def get_panorama_mode() -> str:
    """Current picture mode: the one chosen in the Camera Setup window (saved in SETTINGS_FILE),
    or config.PANORAMA_MODE if nothing was saved yet or the file is unreadable.
    Read fresh on every capture, so a change in the GUI applies to the very next capture."""
    try:
        with open(config.SETTINGS_FILE, "r", encoding="utf-8") as f:
            mode = json.load(f).get("panorama_mode")
        if mode in PANORAMA_MODES:
            return mode
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return config.PANORAMA_MODE


def set_panorama_mode(mode: str) -> None:
    """Saves the picture mode chosen in the Camera Setup window. Raises ValueError for an unknown mode, OSError if the file can't be written.
    Other keys in the settings file are kept."""
    if mode not in PANORAMA_MODES:
        raise ValueError(f"Unknown picture mode: '{mode}'")

    settings = {}
    try:
        with open(config.SETTINGS_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            settings = loaded
    except (OSError, json.JSONDecodeError):
        pass

    settings["panorama_mode"] = mode
    config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


class CamerasBusyError(RuntimeError):
    """Raised by exclusive_cameras() if the cameras are already in use."""


@contextmanager
def exclusive_cameras():
    """Makes sure only one capture runs at a time. Non-blocking: if a capture is already running,
    CamerasBusyError is raised immediately instead of waiting."""
    if not _capture_lock.acquire(blocking=False):
        raise CamerasBusyError("A capture is already running")
    try:
        yield
    finally:
        _capture_lock.release()


def create_tray_folders() -> None:
    """Creates one output folder per tray number, if it doesn't exist yet."""
    for tray_number in range(config.TRAY_LOWER_LIMIT, config.TRAY_UPPER_LIMIT + 1):
        folder = config.OUTPUT_DIR / str(tray_number)
        folder.mkdir(parents=True, exist_ok=True)


def enforce_max_images(output_dir: Path, max_images: int) -> None:
    """Deletes the oldest panorama images if more than max_images are stored."""
    images = sorted(output_dir.glob("finalFrame_*.jpg"))
    while len(images) > max_images:
        oldest = images.pop(0)
        oldest.unlink()


def _side_by_side(frames: list) -> "cv2.typing.MatLike":
    """Places the frames next to each other, left to right in camera order (= the order set in Camera Setup).
    All frames are scaled to the smallest height first, since hconcat needs equal heights."""
    height = min(frame.shape[0] for frame in frames)
    resized = [
        frame if frame.shape[0] == height
        else cv2.resize(frame, (int(frame.shape[1] * height / frame.shape[0]), height))
        for frame in frames
    ]
    return cv2.hconcat(resized)


def capture_and_stitch(camera_devices: list[str], tray_number: str) -> StitchResult:
    """Takes the newest frame of each camera (all at the same moment), combines and saves them.
    Refuses to run if another capture is already running."""
    try:
        with exclusive_cameras():
            return _capture_and_stitch_locked(camera_devices, tray_number)
    except CamerasBusyError as exc:
        return StitchResult(success=False, error_message=str(exc))


def _capture_and_stitch_locked(camera_devices: list[str], tray_number: str) -> StitchResult:
    """The actual capture + stitch. Only ever called while exclusive_cameras() holds the camera lock (see capture_and_stitch)."""
    if not camera_devices:
        return StitchResult(success=False, error_message="No USB cameras configured - please run Camera Setup")

    t_start = time.monotonic()
    # Cameras plugged in after startup get a stream now (then the first frame takes a moment)
    camera_streams.ensure(camera_devices)

    results: list[tuple["cv2.typing.MatLike | None", str | None] | None] = [None] * len(camera_devices)

    def _worker(index: int, device: str) -> None:
        try:
            results[index] = camera_streams.get_frame(device, wait_s=config.USB_CAMERA_FIRST_FRAME_TIMEOUT_S)
        except Exception as exc:
            results[index] = (None, f"Unexpected error on {device}: {exc}")

    # One thread per camera, so all frames are decoded at (almost) the same moment
    threads = [
        threading.Thread(target=_worker, args=(i, device))
        for i, device in enumerate(camera_devices)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    frames = []
    for frame, error_message in results:
        if frame is None:
            return StitchResult(success=False, error_message=error_message)
        frames.append(frame)
    t_frames = time.monotonic()

    output_dir = config.OUTPUT_DIR / tray_number
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime(config.TIMESTAMP_FORMAT)

    panorama_mode = get_panorama_mode()
    if panorama_mode == "stitch":
        stitcher = cv2.Stitcher_create(config.STITCHER_MODE)
        stitcher.setPanoConfidenceThresh(config.STICHER_CONFIDENCE_THRESHOLD)
        status, panorama = stitcher.stitch(frames)

        if status != cv2.Stitcher_OK:
            return StitchResult(success=False, error_message=f"Stitching failed, status code: {status}")
    elif panorama_mode == "side_by_side":
        panorama = _side_by_side(frames)
    else:
        return StitchResult(success=False, error_message=f"Unknown PANORAMA_MODE in config: '{panorama_mode}'")

    pano_path = output_dir / f"finalFrame_{timestamp}.jpg"


    if not cv2.imwrite(str(pano_path), panorama):
        return StitchResult(success=False, error_message=f"Could not save image: {pano_path}")

    enforce_max_images(output_dir, config.MAX_IMAGES_PER_TRAY)

    # Timing in the log file - the photo moment is t_frames; stitching/saving afterwards doesn't matter for the tray position
    logging.info(
        "Capture tray %s: frames taken after %.0f ms, combined + saved after another %.0f ms (%s)",
        tray_number, (t_frames - t_start) * 1000, (time.monotonic() - t_frames) * 1000, panorama_mode,
    )

    return StitchResult(success=True, panorama_path=pano_path)