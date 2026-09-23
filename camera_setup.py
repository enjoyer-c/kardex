"""
Camera setup helper: lets the user identify connected USB cameras via
a live snapshot and assign left/right order - needed because plain
USB port order isn't stable if the cameras ever get unplugged/swapped,
and by-id device names alone don't say which physical camera is which
"""

from pathlib import Path
import json

import config
import camera_stitching


def discover_cameras(max_cameras: int = 4) -> list[str]:
    """Returns unique, actually-usable by-path device paths of
    connected USB cameras.

    Uses by-path (not by-id): identical camera models (e.g. two
    Logitech C920s) often report the same or an empty serial number,
    which makes udev's by-id names collide - by-path is keyed to the
    physical USB port instead, so it stays unique even for identical
    camera models.
    """
    by_path_dir = Path("/dev/v4l/by-path")
    if not by_path_dir.exists():
        return []

    candidates = sorted(
        p for p in by_path_dir.iterdir()
        if p.name.endswith("video-index0") and "-usb-" in p.name
    )

    seen_targets: set[str] = set()
    usable: list[str] = []
    for candidate in candidates:
        target = str(candidate.resolve())
        if target in seen_targets:
            continue  # just another name for a device we already have

        success, _frame, _error = camera_stitching.capture_one(str(candidate))
        if not success:
            continue  # opens but can't actually deliver a frame (e.g. secondary interface)

        seen_targets.add(target)
        usable.append(str(candidate))

        if len(usable) >= max_cameras:
            break

    return usable


def short_name(device: str) -> str:
    """Shortens a by-path device path down to just the last, most
    distinguishing segment, for display purposes."""
    name = Path(device).name
    return name.replace("-video-index0", "")


def capture_snapshot(device: str):
    """Grabs a single frame from the given camera device for preview
    purposes, using the exact same open/warmup/read logic as a real
    capture, so the preview is always
    representative of what an actual capture would get."""
    success, frame, _error_message = camera_stitching.capture_one(device)
    return frame if success else None


def load_camera_order() -> list[str]:
    """Returns the saved camera order, or an empty list if none has
    been saved yet."""
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