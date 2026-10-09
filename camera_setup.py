"""
Camera setup helper: lets the user identify connected USB cameras via a live snapshot and assign left/right
"""

from pathlib import Path
import json
import sys
import time

import config
import camera_stitching
import camera_streams
# Re-exported, so the GUI can use them without importing camera_stitching
get_panorama_mode = camera_stitching.get_panorama_mode
set_panorama_mode = camera_stitching.set_panorama_mode


def _connected_camera_paths() -> list[str]:
    """by-path device paths of all connected USB video devices (only video-index0, duplicates removed). Does NOT open any camera. 
    Uses by-path (not by-id): identical camera models often report the same or an empty serial number, by-path is keyed to the physical USB port instead, so it stays unique even for identical camera models.
    """
    by_path_dir = Path("/dev/v4l/by-path")
    if not by_path_dir.exists():
        return []

    paths: list[str] = []
    seen_targets: set[str] = set()
    for p in sorted(by_path_dir.iterdir()):
        if not (p.name.endswith("video-index0") and "-usb-" in p.name):
            continue
        target = str(p.resolve())
        if target in seen_targets:
            continue
        seen_targets.add(target)
        paths.append(str(p))
    return paths


def get_camera_devices() -> list[str]:
    """The camera devices to capture with, in left-to-right order: the order saved via Camera Setup, or all connected cameras in by-path order as a fallback.
    Read fresh on every call, so a newly saved order is used right away without any restart.
    """
    return load_camera_order() or _connected_camera_paths()


def start_camera_streams() -> None:
    """Program start: opens all connected USB cameras and keeps them streaming (see camera_streams.py).
    Does nothing on systems without /dev/v4l/by-path (e.g. Windows)."""
    camera_streams.sync(_connected_camera_paths())


def stop_camera_streams() -> None:
    """Program end: releases all USB cameras."""
    camera_streams.stop_all()


def discover_cameras(max_cameras: int = 4) -> dict[str, "cv2.typing.MatLike"]:
    """Returns {device path: preview frame} for all connected USB cameras that deliver frames, in discovery order.

    Takes the frames from the permanently running streams - no camera is opened or closed here, so this
    doesn't disturb a capture and is fast. Newly plugged-in cameras get a stream, unplugged ones lose theirs.
    Only waits (up to USB_CAMERA_FIRST_FRAME_TIMEOUT_S) for streams that were just started.
    """
    candidates = _connected_camera_paths()
    camera_streams.sync(candidates)

    found: dict[str, "cv2.typing.MatLike"] = {}
    deadline = time.monotonic() + config.USB_CAMERA_FIRST_FRAME_TIMEOUT_S
    while True:
        for device in candidates:
            if device not in found:
                frame, _error = camera_streams.get_frame(device)
                if frame is not None:
                    found[device] = frame
        if len(found) == len(candidates) or time.monotonic() >= deadline:
            break
        time.sleep(0.1)

    ordered = [device for device in candidates if device in found][:max_cameras]
    return {device: found[device] for device in ordered}


def get_preview_frames(devices: list[str]) -> dict[str, "cv2.typing.MatLike"]:
    """Newest frame of each given camera, for the live preview in Camera Setup. Cameras without a fresh frame are left out."""
    frames = {}
    for device in devices:
        frame, _error = camera_streams.get_frame(device)
        if frame is not None:
            frames[device] = frame
    return frames


def check_cameras_connected() -> str | None:
    """Startup check: is at least one USB camera connected? Returns an error text if not, otherwise None.
    Only on Linux - on Windows the mock modules are used and /dev/v4l doesn't exist.
    """
    if not sys.platform.startswith("linux"):
        return None
    if not _connected_camera_paths():
        return "No USB cameras found"
    return None


def check_saved_order() -> str | None:
    """Compares the saved camera order (camera_order.json) with the cameras that are connected right now. 
    Returns a warning text if they don't match, or None if everything fits.

    Only looks at the /dev/v4l/by-path entries. Does nothing on systems without /dev/v4l/by-path (e.g. Windows).
    """
    if not Path("/dev/v4l/by-path").exists():
        return None

    connected = _connected_camera_paths()
    saved = load_camera_order()
    if not saved:
        return "No camera order saved yet - please run Camera Setup."

    missing = [d for d in saved if d not in connected]
    new = [d for d in connected if d not in saved]
    if not missing and not new:
        return None

    parts = []
    if missing:
        parts.append("missing: " + ", ".join(short_name(d) for d in missing))
    if new:
        parts.append("new: " + ", ".join(short_name(d) for d in new))
    return "Camera order changed (" + "; ".join(parts) + ") - please check Camera Setup."


def short_name(device: str) -> str:
    """Shortens a by-path device path down to just the last, most distinguishing segment, for display purposes.
    """
    name = Path(device).name
    return name.replace("-video-index0", "")


def load_camera_order() -> list[str]:
    """Returns the saved camera order, or an empty list if none has been saved yet.
    """
    if not config.CAMERA_ORDER_FILE.exists():
        return []
    try:
        with open(config.CAMERA_ORDER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        devices = data.get("devices", [])
        if isinstance(devices, list) and all(isinstance(d, str) for d in devices):
            return devices
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_camera_order(order: list[str]) -> None:
    config.CAMERA_ORDER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.CAMERA_ORDER_FILE, "w", encoding="utf-8") as f:
        json.dump({"devices": order}, f, indent=2)