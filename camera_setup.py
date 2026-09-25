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


def _connected_camera_paths() -> list[str]:
    """by-path device paths of all connected USB video devices (only
    video-index0, duplicates removed). Does NOT open any camera - just
    looks at /dev/v4l/by-path, so it's instant. Empty list on systems
    without /dev/v4l/by-path (e.g. Windows).

    Uses by-path (not by-id): identical camera models (e.g. two
    Logitech C920s) often report the same or an empty serial number,
    which makes udev's by-id names collide - by-path is keyed to the
    physical USB port instead, so it stays unique even for identical
    camera models.
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
            continue  # just another name for a device we already have
        seen_targets.add(target)
        paths.append(str(p))
    return paths


def get_camera_devices() -> list[str]:
    """The camera devices to capture with, in left-to-right order: the
    order saved via Camera Setup, or - if none has been saved yet - all
    connected cameras in by-path order as a fallback.
    Read fresh on every call (cheap: one small JSON file), so a newly
    saved order is used right away without any restart."""
    return load_camera_order() or _connected_camera_paths()


def discover_cameras(max_cameras: int = 4) -> dict[str, "cv2.typing.MatLike"]:
    """Returns {device path: preview frame} for all unique, actually-usable
    connected USB cameras, in discovery order. The frame from the
    functional test doubles as the preview image, so every camera only
    has to be opened (and warmed up) ONCE.

    Holds the camera lock for the whole search - raises CamerasBusyError
    if a capture is currently running. Blocks for several seconds (warmup
    frames per camera) - call it from a background thread, not from Tk.
    """
    found: dict[str, "cv2.typing.MatLike"] = {}

    with camera_stitching.exclusive_cameras():
        for candidate in _connected_camera_paths():
            success, frame, _error = camera_stitching.capture_one(candidate)
            if not success:
                continue  # opens but can't actually deliver a frame (e.g. secondary interface)

            found[candidate] = frame

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