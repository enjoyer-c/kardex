"""
Central configuration:
- System
- USB-Cams
- QR-Cam
- Door Sensor
- Data
- Inventory
- GUI
- Logging
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
CAMERA_ORDER_FILE = BASE_DIR / "camera_order.json"  # Saved left-to-right camera order.
SETTINGS_FILE = BASE_DIR / "settings.json"          # Settings changed via the GUI


USB_CAMERA_FOURCC = "MJPG"
USB_CAMERA_RESOLUTION = (1280, 720)
USB_CAMERA_FPS = 15

USB_CAMERA_MAX_FRAME_AGE_S = 1.0        # a frame older than this is never used for a photo [s]
USB_CAMERA_RECONNECT_S = 2.0            # pause before a lost/unplugged camera is opened again [s]
USB_CAMERA_FIRST_FRAME_TIMEOUT_S = 5.0  # max wait for the first frame of a just started stream [s]
CAMERA_SETUP_PREVIEW_REFRESH_MS = 500   # how often the Camera Setup window updates [ms]
ROTATE_IMAGE_180 = True                 # every frame is turned

   # Fixed camera settings
USB_CAMERA_CONTROLS = {
       "focus_automatic_continuous": 0,     # autofocus off
       "focus_absolute": 0,                 # 0 = infinity, higher = closer
       "white_balance_automatic": 0,
       "white_balance_temperature": 4000,   
       "exposure_dynamic_framerate": 0,     # frame rate must not drop in low light
    }

SEAM_OVERLAP_PX = [390, 410, 520]   # Fallback default values


# --- QR-Code-Cam -----------------------------------------------------------
QR_CAPTURE_SIZE = (1332, 990)   

QR_SCAN_WINDOW_S = 2.0                 # a QR code counts if seen up to this long AFTER the door signal [s]
QR_RECENT_S = 1.0                      # or up to this long BEFORE it (code was already there) [s]
QR_SCAN_GRACE_S = 2.0                  # extra time to finish scanning the last frame of the window
QR_SCAN_INTERVAL_S = 0.1               # minimum time between two scans
QR_GONE_S = 1.0                        # log "QR code out of view" only after this long without a code
QR_CAMERA_RESTART_AFTER = 5            # restart the ribbon cam after this many failed frames in a row
QR_FRAME_TIMEOUT_S = 3.0               # a frame that takes longer counts as a camera error

# --- Door-Sensor -----------------------------------------------------------
DOOR_SENSOR_GPIO = 17                  #Pin11
DOOR_SENSOR_BOUNCE_TIME_MS = 350

DOOR_SENSOR_INVERTED = True             

DOOR_TEST_BUTTON = False               # shows a "TEST: Toggle Door" button in the GUI 

# --- Data -----------------------------------------------------------------
if sys.platform.startswith("linux"):
    SSD_DIR = Path("/mnt/kardex_ssd")
    OUTPUT_DIR = SSD_DIR / "captures"
else:
    SSD_DIR = BASE_DIR
    OUTPUT_DIR = BASE_DIR / "captures"

TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

MAX_IMAGES_PER_TRAY = 3

TRAY_LOWER_LIMIT = 1
TRAY_UPPER_LIMIT = 50

# --- Inventory ------------------------------------------------------------
INVENTORY_FILE = BASE_DIR / "inventory.txt"

# --- GUI: image preview magnifier -------------------------------------------
SEARCH_DEBOUNCE_MS = 300        # wait time after the last keystroke before the search runs [ms]
PREVIEW_DEBOUNCE_MS = 150       # Waiting time after search (arrow-keys) for loading the actual image
LENS_UPDATE_MS = 20             # Magnifier redraws time
LENS_SIZE = 300                 # diameter of the magnifier circle [px]
LENS_ZOOM = 2                   # magnification relative to the preview

# --- Logging ----------------------------------------------------------
LOG_DIR = SSD_DIR / "logs"
LOG_FILE = LOG_DIR / "kardex.log"
LOCK_FILE = Path("/tmp/kardex.lock")      # prevents the program from running twice