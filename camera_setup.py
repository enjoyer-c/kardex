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
# Re-exported, so the GUI can catch it without importing camera_stitching
CamerasBusyError = camera_stitching.CamerasBusyError


def discover_cameras(max_cameras: int = 4) -> dict[str, "cv2.typing.MatLike"]:
    """Returns {device path: preview frame} for all unique, actually-usable
    connected USB cameras, in discovery order. The frame from the
    functional test doubles as the preview image, so every camera only
    has to be opened (and warmed up) ONCE.

    Holds the camera lock for the whole search - raises CamerasBusyError
    if a capture is currently running. Blocks for several seconds (warmup
    frames per camera) - call it from a background thread, not from Tk.

    Uses by-path (not by-id): identical camera models (e.g. two
    Logitech C920s) often report the same or an empty serial number,
    which makes udev's by-id names collide - by-path is keyed to the
    physical USB port instead, so it stays unique even for identical
    camera models.
    """
    by_path_dir = Path("/dev/v4l/by-path")
    if not by_path_dir.exists():
        return {}

    candidates = sorted(
        p for p in by_path_dir.iterdir()
        if p.name.endswith("video-index0") and "-usb-" in p.name
    )

    seen_targets: set[str] = set()
    found: dict[str, "cv2.typing.MatLike"] = {}

    with camera_stitching.exclusive_cameras():
        for candidate in candidates:
            target = str(candidate.resolve())
            if target in seen_targets:
                continue 

            success, frame, _error = camera_stitching.capture_one(str(candidate))
            if not success:
                continue 

            seen_targets.add(target)
            found[str(candidate)] = frame

            if len(found) >= max_cameras:
                break

    return found


def check_saved_order() -> str | None:
    """Compares the saved camera order (camera_order.json) with the
    cameras that are connected right now. Returns a warning text if
    they don't match (camera missing / new camera / nothing saved yet),
    or None if everything fits.

    Only looks at the /dev/v4l/by-path entries - does NOT open any
    camera, so it's fast enough to run at every program start.
    Does nothing on systems without /dev/v4l/by-path (e.g. Windows).
    """
    by_path_dir = Path("/dev/v4l/by-path")
    if not by_path_dir.exists():
        return None

    connected: list[str] = []
    seen_targets: set[str] = set()
    for p in sorted(by_path_dir.iterdir()):
        if not (p.name.endswith("video-index0") and "-usb-" in p.name):
            continue
        target = str(p.resolve())
        if target in seen_targets:
            continue  # just another name for a device we already have
        seen_targets.add(target)
        connected.append(str(p))

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
    """Shortens a by-path device path down to just the last, most
    distinguishing segment, for display purposes."""
    name = Path(device).name
    return name.replace("-video-index0", "")


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