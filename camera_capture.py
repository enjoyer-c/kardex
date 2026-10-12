"""
Builds the final tray picture from the USB cameras. The cameras themselves stay open permanently.
Two steps, so the photos can be taken FIRST and saved only once it's clear which tray they belong to (QR code):
    grab_frames()      - newest frame of every camera, all at the same moment (fast, ~0.1 s)
    combine_and_save() - crop the overlaps, put the images side by side, save under the tray number
capture_and_save() does both at once (manual capture, tray number is already known).

Combining - one overlap value per seam (= border between two neighbouring cameras):
    Half of the overlap is cut off the RIGHT of the left camera, the other half off the LEFT of the
    right camera. The outer edges stay untouched, so the picture stays centered.

    Cam 1          Cam 2          Cam 3          Cam 4
    [     |cut] [cut|    |cut] [cut|    |cut] [cut|     ]
          seam 1         seam 2         seam 3

    The values are set in the Camera Setup window (saved in SETTINGS_FILE), defaults in config.py.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import logging
import threading
import time

import cv2

import config
import camera_streams


@dataclass
class CaptureResult:
    success: bool
    image_path: Path | None = None
    error_message: str | None = None
    frames_taken_at: float | None = None   # time.monotonic() when the frames were taken (for the log)


@dataclass
class FrameSet:
    """The frames of all cameras from one moment, in camera order."""
    frames: list
    taken_at: float        # time.monotonic() - for measuring the delay to the door signal
    taken_wall: datetime   # wall-clock time - goes into the file name


# --- Overlap values (one per seam) -----------------------------------------------

def _read_settings() -> dict:
    try:
        with open(config.SETTINGS_FILE, "r", encoding="utf-8") as f:
            settings = json.load(f)
        return settings if isinstance(settings, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_seam_overlaps() -> list[int]:
    """Overlap per seam - as saved in Camera Setup, otherwise the defaults from config.py.
    Read fresh on every capture, so a change in Camera Setup applies to the very next photo."""
    overlaps = _read_settings().get("seam_overlap_px")
    if isinstance(overlaps, list) and all(isinstance(v, int) for v in overlaps):
        return overlaps
    return list(config.SEAM_OVERLAP_PX)


def save_seam_overlaps(overlaps: list[int]) -> None:
    """Saves the overlaps from Camera Setup. Other keys in the settings file are kept."""
    settings = _read_settings()
    settings["seam_overlap_px"] = [int(v) for v in overlaps]
    config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


# --- Combining --------------------------------------------------------------------

def crop_and_combine(frames: list, overlaps: list[int], show_seams: bool = False):
    """Crops the overlaps and puts the frames side by side (see module docstring).
    Raises ValueError if the values don't fit the frames (wrong count, nothing left after cutting).
    show_seams draws a red line where two images meet - only for the Camera Setup preview, never in a saved photo."""
    if len(overlaps) != len(frames) - 1:
        raise ValueError(f"{len(frames)} cameras need {len(frames) - 1} overlap values, got {len(overlaps)}")

    height = min(frame.shape[0] for frame in frames)   # hconcat needs equal heights
    cropped = []
    for i, frame in enumerate(frames):
        width = frame.shape[1]
        cut_left = overlaps[i - 1] - overlaps[i - 1] // 2 if i > 0 else 0   # right half of the seam before
        cut_right = overlaps[i] // 2 if i < len(frames) - 1 else 0           # left half of the seam after
        if cut_left < 0 or cut_right < 0 or cut_left + cut_right >= width:
            raise ValueError(f"Camera {i + 1}: cutting {cut_left} + {cut_right} px doesn't fit {width} px")
        cropped.append(frame[:height, cut_left:width - cut_right])

    combined = cv2.hconcat(cropped)

    if show_seams:
        x = 0
        for frame in cropped[:-1]:
            x += frame.shape[1]
            cv2.line(combined, (x, 0), (x, height - 1), (0, 0, 255), 2)
    return combined


def combine(frames: list) -> "cv2.typing.MatLike":
    """The final picture with the saved overlaps. If they don't fit (e.g. a camera is missing),
    the frames are put side by side UNCUT - better an uncut picture than none."""
    overlaps = load_seam_overlaps()
    try:
        return crop_and_combine(frames, overlaps)
    except ValueError as exc:
        logging.warning("Seam overlaps don't fit (%s) - saved uncut, please check Camera Setup", exc)
        return crop_and_combine(frames, [0] * (len(frames) - 1))


# --- Capture --------------------------------------------------------------------

def create_tray_folders() -> None:
    """Creates one output folder per tray number, if it doesn't exist yet."""
    for tray_number in range(config.TRAY_LOWER_LIMIT, config.TRAY_UPPER_LIMIT + 1):
        folder = config.OUTPUT_DIR / str(tray_number)
        folder.mkdir(parents=True, exist_ok=True)


def enforce_max_images(output_dir: Path, max_images: int) -> None:
    """Deletes the oldest images if more than max_images are stored."""
    images = sorted(output_dir.glob("finalFrame_*.jpg"))
    while len(images) > max_images:
        oldest = images.pop(0)
        oldest.unlink()


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


def combine_and_save(frame_set: FrameSet, tray_number: str) -> CaptureResult:
    """Combines the frames (see combine) and saves them under the tray number."""
    t_start = time.monotonic()
    output_dir = config.OUTPUT_DIR / tray_number
    output_dir.mkdir(parents=True, exist_ok=True)

    image = combine(frame_set.frames)

    # File name = the moment the photos were TAKEN, not when saving finished
    timestamp = frame_set.taken_wall.strftime(config.TIMESTAMP_FORMAT)
    image_path = output_dir / f"finalFrame_{timestamp}.jpg"
    if not cv2.imwrite(str(image_path), image):
        return CaptureResult(success=False, error_message=f"Could not save image: {image_path}")

    enforce_max_images(output_dir, config.MAX_IMAGES_PER_TRAY)
    logging.info("  details: combining + saving took %.0f ms", (time.monotonic() - t_start) * 1000)

    return CaptureResult(success=True, image_path=image_path, frames_taken_at=frame_set.taken_at)


def capture_and_save(camera_devices: list[str], tray_number: str) -> CaptureResult:
    """Both steps at once - for the manual capture, where the tray number is already known."""
    frame_set, error = grab_frames(camera_devices)
    if frame_set is None:
        return CaptureResult(success=False, error_message=error)
    return combine_and_save(frame_set, tray_number)