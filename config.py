"""
Central configuration for the Kardex project.
Platform-aware (Windows dev machine vs. Raspberry Pi), so the same
file works unchanged on both without manual edits.
"""


from pathlib import Path
import cv2
import sys

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
# Saved left-to-right camera order (written by the Camera Setup window).
# Loading it (plus the fallback discovery) lives in camera_setup.py -
# see camera_setup.get_camera_devices()
CAMERA_ORDER_FILE = BASE_DIR / "camera_order.json"

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

# TEMP door test: shows a "TEST: Toggle Door" button in the GUI that simulates the magnet (open/close). Set to False to hide it again.
DOOR_TEST_BUTTON = True


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