"""
Camera setup helper: lets the user identify connected USB cameras via
a live snapshot and assign left/right order - needed because plain
USB port order isn't stable if the cameras ever get unplugged/swapped,
and by-id device names alone don't say which physical camera is which.
"""

from pathlib import Path
import json
import cv2

import config


def discover_cameras(max_cameras: int = 4) -> list[str]:
    """Returns by-id device paths of currently connected USB cameras,
    in whatever order udev happens to report them"""
    by_id_dir = Path("/dev/v4l/by-id")
    if not by_id_dir.exists():
        return []
    devices = sorted(str(p) for p in by_id_dir.iterdir() if p.name.endswith("video-index0"))
    return devices[:max_cameras]


def short_name(device: str) -> str:
    """Shortens a by-id device path down to just the readable part,
    e.g. 'usb-046d_HD_Pro_Webcam_C920_ABC123' instead of the full path."""
    name = Path(device).name
    return name.replace("-video-index0", "")


def capture_snapshot(device: str):
    """Grabs a single frame from the given camera device for preview
    purposes. Returns None if the camera can't be opened/read."""
    cam = cv2.VideoCapture(device, config.CAP_BACKEND)
    try:
        if not cam.isOpened():
            return None
        for _ in range(5):  # a few throwaway frames so exposure settles
            cam.read()
        ret, frame = cam.read()
        return frame if ret else None
    finally:
        cam.release()


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