"""
Builds the final tray picture from the USB cameras. The cameras themselves stay open permanently (see camera_streams.py).
Two steps, so the photos can be taken FIRST and saved only once it's clear which tray they belong to (QR code):
    grab_frames()      - newest frame of every camera, all at the same moment (fast, ~0.1 s)
    combine_and_save() - stitch / side by side, save under the tray number
capture_and_stitch() does both at once (manual capture, tray number is already known).
"""

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
    frames_taken_at: float | None = None   # time.monotonic() when the frames were taken (for the log)


@dataclass
class FrameSet:
    """The frames of all cameras from one moment, in camera order."""
    frames: list
    taken_at: float        # time.monotonic() - for measuring the delay to the door signal
    taken_wall: datetime   # wall-clock time - goes into the file name

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


def grab_frames(camera_devices: list[str]) -> tuple[FrameSet | None, str | None]:
    """Takes the newest frame of every camera from the running streams, all at (almost) the same moment.
    Returns (FrameSet, None) or (None, error text)."""
    if not camera_devices:
        return None, "No USB cameras configured - please run Camera Setup"

    # Cameras plugged in after startup get a stream now (then the first frame takes a moment)
    camera_streams.ensure(camera_devices)

    results: list[tuple["cv2.typing.MatLike | None", str | None] | None] = [None] * len(camera_devices)

    def _worker(index: int, device: str) -> None:
        try:
            results[index] = camera_streams.get_frame(device, wait_s=config.USB_CAMERA_FIRST_FRAME_TIMEOUT_S)
        except Exception as exc:
            results[index] = (None, f"Unexpected error on {device}: {exc}")

    # One thread per camera, so all frames are decoded at the same moment
    threads = [threading.Thread(target=_worker, args=(i, device)) for i, device in enumerate(camera_devices)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    frames = []
    for frame, error_message in results:
        if frame is None:
            return None, error_message
        frames.append(frame)
    return FrameSet(frames=frames, taken_at=time.monotonic(), taken_wall=datetime.now()), None


def combine_and_save(frame_set: FrameSet, tray_number: str) -> StitchResult:
    """Combines the frames (stitch or side by side, see Camera Setup) and saves them under the tray number."""
    t_start = time.monotonic()
    output_dir = config.OUTPUT_DIR / tray_number
    output_dir.mkdir(parents=True, exist_ok=True)

    panorama_mode = get_panorama_mode()
    if panorama_mode == "stitch":
        stitcher = cv2.Stitcher_create(config.STITCHER_MODE)
        stitcher.setPanoConfidenceThresh(config.STICHER_CONFIDENCE_THRESHOLD)
        status, panorama = stitcher.stitch(frame_set.frames)
        if status != cv2.Stitcher_OK:
            return StitchResult(success=False, error_message=f"Stitching failed, status code: {status}")
    elif panorama_mode == "side_by_side":
        panorama = _side_by_side(frame_set.frames)
    else:
        return StitchResult(success=False, error_message=f"Unknown picture mode: '{panorama_mode}'")

    # File name = the moment the photos were TAKEN, not when saving finished
    timestamp = frame_set.taken_wall.strftime(config.TIMESTAMP_FORMAT)
    pano_path = output_dir / f"finalFrame_{timestamp}.jpg"
    if not cv2.imwrite(str(pano_path), panorama):
        return StitchResult(success=False, error_message=f"Could not save image: {pano_path}")

    enforce_max_images(output_dir, config.MAX_IMAGES_PER_TRAY)
    logging.info("  details: combining + saving took %.0f ms (%s)", (time.monotonic() - t_start) * 1000, panorama_mode)

    return StitchResult(success=True, panorama_path=pano_path, frames_taken_at=frame_set.taken_at)


def capture_and_stitch(camera_devices: list[str], tray_number: str) -> StitchResult:
    """Both steps at once - for the manual capture, where the tray number is already known."""
    frame_set, error = grab_frames(camera_devices)
    if frame_set is None:
        return StitchResult(success=False, error_message=error)
    return combine_and_save(frame_set, tray_number)