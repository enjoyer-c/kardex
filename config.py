"""
Central configuration for the Kardex project.

Platform-aware (Windows dev machine vs. Raspberry Pi)
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
USB_CAMERA_FOURCC = "MJPG"
USB_CAMERA_RESOLUTION = (1280, 720)
USB_CAMERA_FPS = 15                     # frame rate of the permanent streams (lower = less USB bandwidth/CPU; None = camera default)

# Saved left-to-right camera order. Loading it lives in camera_setup.py
CAMERA_ORDER_FILE = BASE_DIR / "camera_order.json"

# Seam Overlaps settings
SETTINGS_FILE = BASE_DIR / "settings.json"


# The USB cameras stream
USB_CAMERA_MAX_FRAME_AGE_S = 1.0        # a frame older than this is never used for a photo [s]
USB_CAMERA_RECONNECT_S = 2.0            # pause before a lost/unplugged camera is opened again [s]
USB_CAMERA_FIRST_FRAME_TIMEOUT_S = 5.0  # max wait for the first frame of a JUST started stream [s]
CAMERA_SETUP_PREVIEW_REFRESH_MS = 1000   # how often the Camera Setup window updates its camera pictures [ms]

# --- Combining the camera images --------------------------------------------
# Overlap per seam between neighbouring cameras in pixels
SEAM_OVERLAP_PX = [390, 410, 520] #Default -> Cam Settings overrule

MAX_IMAGES_PER_TRAY = 3

# --- QR-Code-Cam -----------------------------------------------------------
QR_CAPTURE_SIZE = (1332, 990)   
# The ribbon cam runs permanently. When the door opens, it looks for a QR code for at most this long (~2.5sec tray stand still)
QR_SCAN_WINDOW_S = 1.0

# --- Door-Sensor -----------------------------------------------------------
DOOR_SENSOR_GPIO = 17 #Pin11
DOOR_SENSOR_BOUNCE_TIME_MS = 350

DOOR_SENSOR_INVERTED = True #Direction of the contact. True -> NC contact

# TEMP door test: shows a "TEST: Toggle Door" button in the GUI that
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