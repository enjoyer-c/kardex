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

# Settings changed via the GUI (currently: seam overlaps from Camera Setup)
SETTINGS_FILE = BASE_DIR / "settings.json"

USB_CAMERA_FOURCC = "MJPG"
USB_CAMERA_RESOLUTION = (1280, 720)
USB_CAMERA_FPS = 15                     # frame rate of the permanent streams (lower = less USB bandwidth/CPU; None = camera default)

# The USB cameras stay open permanently (camera_streams.py) - a capture only takes the newest frame
USB_CAMERA_MAX_FRAME_AGE_S = 1.0        # a frame older than this is never used for a photo [s]
USB_CAMERA_RECONNECT_S = 2.0            # pause before a lost/unplugged camera is opened again [s]
USB_CAMERA_FIRST_FRAME_TIMEOUT_S = 5.0  # max wait for the first frame of a JUST started stream [s]
CAMERA_SETUP_PREVIEW_REFRESH_MS = 500   # how often the Camera Setup window updates its camera pictures [ms]
ROTATE_IMAGE_180 = True   # cameras see the tray upside down - turn the final picture

   # Fixed camera settings - the automatics make every camera look different
USB_CAMERA_CONTROLS = {
       "focus_automatic_continuous": 0,   # autofocus off
       "focus_absolute": 0,              # 0 = infinity, higher = closer
       "white_balance_automatic": 0,
       "white_balance_temperature": 4000,
       "exposure_dynamic_framerate": 0,   # frame rate must not drop in low light
    }

# --- Combining the camera images --------------------------------------------
# Overlap per seam between neighbouring cameras in pixels (one value less than cameras) - see camera_capture.py.
# These are only the defaults: the values set in the Camera Setup window are saved in SETTINGS_FILE and used from then on.
SEAM_OVERLAP_PX = [390, 410, 520]

MAX_IMAGES_PER_TRAY = 3

# --- QR-Code-Cam -----------------------------------------------------------
QR_CAPTURE_SIZE = (1332, 990)   
# The ribbon cam runs AND is scanned permanently (see qr_code_scanner.py). At a door opening, a QR code counts if it
# was seen between QR_RECENT_S before and QR_SCAN_WINDOW_S after the door signal (the tray still stands ~2.5 s).
QR_SCAN_WINDOW_S = 2.0
QR_RECENT_S = 1.0
QR_SCAN_GRACE_S = 2.0                   # extra time to finish scanning the last frame of the window (scanning is slower on the Pi)
QR_SCAN_INTERVAL_S = 0.1                # minimum time between two scans (usually the scan itself takes longer)
QR_GONE_S = 1.0                         # log "QR code out of view" only after this long without a code
QR_CAMERA_RESTART_AFTER = 5             # restart the ribbon cam after this many failed frames in a row
QR_FRAME_TIMEOUT_S = 3.0               # a frame that takes longer counts as a camera error

# --- Door-Sensor -----------------------------------------------------------
DOOR_SENSOR_GPIO = 17 #Pin11
DOOR_SENSOR_BOUNCE_TIME_MS = 350
# Direction of the contact. False: contact closed (magnet present) = door CLOSED.
# True: the other way round (e.g. NC contact) - live test 09.10.: door events were reported reversed
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
LOCK_FILE = Path("/tmp/kardex.lock")      # prevents the program from running twice (see main.py)
QR_DEBUG_DIR = LOG_DIR / "qr_debug"     # pictures saved with 's' in the ribbon cam live preview