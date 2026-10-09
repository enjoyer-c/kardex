"""
Central configuration for the Kardex project.
Platform-aware (Windows dev machine vs. Raspberry Pi), so the same file works unchanged on both without manual edits.
"""

from pathlib import Path
import cv2
import sys

# --- System -------------------------------------------------------
if sys.platform.startswith("win32"):
    BASE_DIR = Path.home() / "Kardex" / "neuesKardexSystem" / "dev"
else:
    BASE_DIR = Path(__file__).resolve().parent  


if sys.platform.startswith("linux"):
    CAP_BACKEND = cv2.CAP_V4L2
elif sys.platform.startswith("win32"):
    CAP_BACKEND = cv2.CAP_DSHOW
else:
    CAP_BACKEND = cv2.CAP_ANY

# --- USB-Cams ---------------------------------------------------------------
# Saved left-to-right camera order. Loading it lives in camera_setup.py - see camera_setup.get_camera_devices()
CAMERA_ORDER_FILE = BASE_DIR / "camera_order.json"

# Settings changed via the GUI (currently: picture mode stitch / side by side)
SETTINGS_FILE = BASE_DIR / "settings.json"

USB_CAMERA_FOURCC = "MJPG"
USB_CAMERA_RESOLUTION = (1280, 720)
USB_CAMERA_FPS = 15                     # frame rate of the permanent streams (lower = less USB bandwidth/CPU; None = camera default)

# The USB cameras stay open permanently (camera_streams.py) - a capture only takes the newest frame
USB_CAMERA_MAX_FRAME_AGE_S = 1.0        # a frame older than this is never used for a photo [s]
USB_CAMERA_RECONNECT_S = 2.0            # pause before a lost/unplugged camera is opened again [s]
USB_CAMERA_FIRST_FRAME_TIMEOUT_S = 5.0  # max wait for the first frame of a JUST started stream [s]
CAMERA_SETUP_PREVIEW_REFRESH_MS = 500   # how often the Camera Setup window updates its camera pictures [ms]

# --- Stitching -------------------------------------------------------------
# How the single camera images are combined into one picture:
#   "stitch"       - OpenCV stitcher (removes overlaps, can fail on low-texture images, e.g. an empty tray)
#   "side_by_side" - images simply placed next to each other in camera order (never fails, fast)
# Can be switched in the Camera Setup window - the choice is saved in SETTINGS_FILE.
# This value is only the default, used until a choice has been saved there.
PANORAMA_MODE = "stitch"

STITCHER_MODE = cv2.Stitcher_SCANS      #vaible modes: SCANS or PANORAMA
STICHER_CONFIDENCE_THRESHOLD = 0.5      #Default = 1.0

MAX_IMAGES_PER_TRAY = 3

# --- QR-Code-Cam -----------------------------------------------------------
QR_CAPTURE_SIZE = (1332, 990)   
QR_SCAN_TIMEOUT_S = 6.0                 # max waiting time for QR-Code [s] - tray is already standing when the door closes
QR_SCAN_INTERVAL_S = 0.1                # pause between two scan attempts [s]

# --- Door-Sensor -----------------------------------------------------------
DOOR_SENSOR_GPIO = 17 #Pin11
DOOR_SENSOR_BOUNCE_TIME_MS = 350

# Direction of the contact. False: contact closed (magnet present) = door CLOSED.
# True: the other way round (e.g. NC contact) -> Testen !!!!!!!!!!!!!
DOOR_SENSOR_INVERTED = True

# TEMP door test: shows a "TEST: Toggle Door" button in the GUI that
# simulates the magnet (open/close). Set to False to hide it again.
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

# --- GUI: image preview magnifier -------------------------------------------
SEARCH_DEBOUNCE_MS = 300    # wait time after the last keystroke before the search runs [ms]
PREVIEW_DEBOUNCE_MS = 150 # Waiting time after search (arrow-keys) for loading the actual image
LENS_UPDATE_MS = 20       # Magnifier redraws at most every 20 ms while the mouse moves (mouse events come much faster)
LENS_SIZE = 300     # diameter of the magnifier circle [px]
LENS_ZOOM = 2     # magnification relative to the preview (~2 = about the original resolution)

# --- Logging ----------------------------------------------------------
LOG_DIR = SSD_DIR / "logs"
LOG_FILE = LOG_DIR / "kardex.log"