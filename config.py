"""
Central configuration for the Kardex project.
Platform-aware (Windows dev machine vs. Raspberry Pi), so the same
file works unchanged on both without manual edits.
"""


from pathlib import Path
import cv2
import sys
import json

# --- System -------------------------------------------------------
if sys.platform.startswith("win32"):
    BASE_DIR = Path(r"C:\Users\mjansson\Kardex\neuesKardexSystem\dev")
else:
    BASE_DIR = Path(__file__).resolve().parent  


if sys.platform.startswith("linux"):
    CAP_BACKEND = cv2.CAP_V4L2
elif sys.platform.startswith("win32"):
    CAP_BACKEND = cv2.CAP_DSHOW
else:
    CAP_BACKEND = cv2.CAP_ANY

# --- USB-Cams ---------------------------------------------------------------
CAMERA_ORDER_FILE = BASE_DIR / "camera_order.json"

def _load_camera_devices() -> list[str]:
    """Loads the saved camera order (set via the Camera Setup window).
    If none has been saved yet, falls back to auto-discovering
    connected cameras via /dev/v4l/by-path (board-independent, unlike
    by-path being tied to the physical port - by-id was tried first
    but collides for identical camera models like two Logitech C920s,
    which often report the same or an empty serial number).
    """
    if CAMERA_ORDER_FILE.exists():
        try:
            with open(CAMERA_ORDER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            devices = data.get("devices", [])
            if isinstance(devices, list) and all(isinstance(d, str) for d in devices):
                return devices
        except (json.JSONDecodeError, OSError):
            pass
 
    by_path_dir = Path("/dev/v4l/by-path")
    if by_path_dir.exists():
        return sorted(
            str(p) for p in by_path_dir.iterdir()
            if p.name.endswith("video-index0") and "-usb-" in p.name
        )
    return []

USB_CAMERA_DEVICES = _load_camera_devices()
USB_CAMERA_FOURCC = "MJPG"
USB_CAMERA_RESOLUTION = (1280, 720)
USB_CAMERA_WARMUP_FRAMES = 15

# --- Stitching -------------------------------------------------------------
STITCHER_MODE = cv2.Stitcher_SCANS      #vaible modes: SCANS or PANORAMA
STICHER_CONFIDENCE_THRESHOLD = 0.5      #Default = 1.0

MAX_IMAGES_PER_TRAY = 3

# --- QR-Code-Cam -----------------------------------------------------------
QR_CAPTURE_SIZE = (1332, 990)   
QR_SCAN_TIMEOUT_S = 10.0                # max waiting time for QR-Code [s]

# --- Hall-Sensor -----------------------------------------------------------
HALL_SENSOR_GPIO = 17 #Pin11
HALL_SENSOR_BOUNCE_TIME_MS = 350

# --- Data -----------------------------------------------------------------
if sys.platform.startswith("linux"):
    SSD_DIR = Path("/mnt/kardex_ssd")
    OUTPUT_DIR = SSD_DIR / "captures"
else:
    SSD_DIR = BASE_DIR
    OUTPUT_DIR = BASE_DIR / "captures"

TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

TRAY_LOWER_LIMIT = 1
TRAY_UPPER_LIMIT = 50

# --- Inventory ------------------------------------------------------------
INVENTORY_FILE = BASE_DIR / "inventory.txt"

# --- Logging ----------------------------------------------------------
LOG_DIR = SSD_DIR / "logs"
LOG_FILE = LOG_DIR / "kardex.log"