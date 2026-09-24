# Kardex Shuttle Logistics System

Automated high-bay warehouse system: detects tray movement via a door sensor, identifies trays via QR code, photographs the tray contents with USB cameras (stitched into a panorama), and maintains a searchable inventory.

Runs cross-platform: real hardware on the Raspberry Pi, simulated hardware (mock modules) on Windows for development/testing without any sensors/cameras attached.

---

## Setup (Raspberry Pi)

chmod +x setup_pi.sh
./setup_pi.sh

Installs system and Python packages, creates a .venv (--system-site-packages, so picamera2 can access the system-wide libcamera libraries).

Important: never run Setup_RibbonCAM.py / Setup_USBCAM.py at the same time as main.py - both would try to open the same camera hardware simultaneously.

Afterwards:
source .venv/bin/activate
python3 main.py

---

## Modules

### config.py
Central configuration, platform-aware (Windows dev machine vs. Pi - the same file works unchanged on both).

- Paths: BASE_DIR (Linux: the folder config.py itself lives in; Windows: a hardcoded development path), OUTPUT_DIR (captures, on the Pi located on the external SSD), INVENTORY_FILE, LOG_DIR/LOG_FILE
- Hardware: HALL_SENSOR_GPIO (pin 17 / physical pin 11), USB_CAMERA_RESOLUTION, QR_CAPTURE_SIZE
- Camera order: USB_CAMERA_DEVICES is loaded at program startup from camera_order.json (set via the Camera Setup window); without a saved file, an automatic /dev/v4l/by-path discovery is used as a fallback
- Processing: stitching mode/confidence threshold, TRAY_LOWER_LIMIT/TRAY_UPPER_LIMIT (1-50)

### main.py
Drives the state-machine flow and connects hardware events to the GUI.

- 5 states: IDLE, OUTBOUND, AT_DELIVERY_POSITION, CAPTURING_AND_STITCHING, RETURNING - see Process Flow below
- Only the exact intended (door action + current state) combinations trigger a transition; anything else is silently ignored
- QR scanning, automatic capture, and manual capture each run in their own background thread, so the GUI stays usable while they run (searching, scrolling the table)
- Door sensor events arrive from a background thread (gpiozero) and are routed back to the Tk main thread before touching any GUI code
- Manual capture is guarded twice: blocked during the automatic flow and against itself , since the state stays IDLE throughout a manual capture
- If no tray QR code is detected, nothing is photographed - jumps straight to RETURNING
- Logging: RotatingFileHandler (max. 5 MB, up to 3 backups) plus console output; a global Tkinter exception handler ensures even unhandled GUI errors always end up in the log file
- Linux: the window is maximized on startup (-zoomed, with a fallback to manually setting the screen resolution)
- Worker threads always report back to the main thread, even if they crash (wrapped in try/except, logged via logging.exception)
- After a background operation finishes, the door sensor's current state is checked to catch up on a door event that arrived while the thread was busy


### camera_stitching.py
Drives the USB cameras and stitches the panorama.

- Each camera is individually opened, warmed up, read, and released again for every single capture
- Cameras are read in PARALLEL (one thread per camera) instead of one after another
- A lock (_capture_lock) prevents overlapping captures - a second attempt while one is already running is rejected immediately with an error, instead of waiting or colliding
- Stitching via OpenCV's Stitcher; if a camera or the stitching itself fails, the whole attempt aborts with an error message
- The result is saved with a timestamp under OUTPUT_DIR/<tray_number>/; at most MAX_IMAGES_PER_TRAY images per tray are kept, the oldest ones are deleted automatically
- exclusive_cameras(): reserves all USB cameras using the SAME _capture_lock as capture_and_stitch used by Camera Setup's search, so a running search and a running capture can never touch the cameras at the same time.


### camera_setup.py
Helper module for the Camera Setup window (camera identification and ordering).

- Camera discovery via /dev/v4l/by-path (not by-id, since identical camera models often report the same or an empty serial number, which would cause collisions)
- Some cameras (including the Logitech C920 used here) expose more than one video interface per physical unit - filtered out via deduplication plus an actual functional test (using camera_stitching.capture_one), so only genuinely usable cameras are shown
- The saved order is stored as camera_order.json in the project folder
- discover_cameras() now returns {device: image} directly


### qr_code_scanner.py
Ribbon camera (Pi HQ Camera) for QR code detection.

- Only runs on the Pi
- Repeatedly reads frames and tries to decode them until a QR code is found or QR_SCAN_TIMEOUT_S is reached
- Barcode types other than QR are ignored
- No match found -> returns None
- Camera hardware is always released cleanly via finally

### hall_sensor.py
Door sensor (magnetic contact) via GPIO.

- pull_up=True: the pin sits electrically high, the magnet pulls it low -> is_pressed means the door is CLOSED -> is_open = not is_pressed
- when_pressed/when_released both use the same internal method, since either event requires re-evaluating the same state
- State is actively read once at startup, instead of waiting for the first event

### inventory.py
Reads/writes the plain-text inventory list (inventory.txt, one description per line, in tray order).

- Converts between 0-based line numbering and 1-based tray numbering (enumerate(..., start=TRAY_LOWER_LIMIT) and index = tray_number - TRAY_LOWER_LIMIT respectively)
- Missing file -> empty list instead of a crash; invalid tray number in update_description -> ValueError
- validates/normalizes tray number ("01" → "1"), rejects anything that isn't a plain integer within TRAY_LOWER_LIMIT/TRAY_UPPER_LIMIT. Prevents duplicate folders for the same tray (e.g. "1" vs "01")


### gui.py
Tkinter interface.

- Status display (color-coded per state), searchable tray table with a live image preview below it (updates on click or arrow-key navigation)
- Right-click a row to rename its description
- Popups (History, Manual Capture, Camera Setup) all follow the same pattern: if the window already exists, it's brought to the front instead of being rebuilt
- The search box and image preview are debounced, so they don't reload on every single keystroke/arrow-key press
- Arrow keys control the tray table even when, e.g., the search box currently has focus
- Manual Capture: fallback tray-number entry for when the automatic door-sensor flow doesn't trigger
- Camera Setup: shows a snapshot of each detected USB camera, allows reordering via arrow buttons, plus a button for the ribbon-cam live stream
- Refresh All re-discovers from scratch
- Camera Setup only allowed while the system is IDLE


---

## Process Flow

1. IDLE
Door is closed, system waits for a new request.

2. OUTBOUND
Door opens (1st time) -> tray moves out of the rack into the delivery position.

3. AT_DELIVERY_POSITION
Door closes -> QR code scan runs in a background thread (GUI stays usable in the meantime).
No QR found -> error logged, tray number stays empty.
System then waits while the user loads/unloads the tray.

4. CAPTURING_AND_STITCHING
Door opens (2nd time) -> capture+stitching runs in a background thread. Both USB cameras each take one picture in parallel, get stitched into a panorama, result is saved with a timestamp - before the tray starts moving back.
No tray QR detected -> capture is skipped.

5. RETURNING
Door closes, tray drives back into the rack.

6. back to IDLE
Tray number is reset.

---

## Known Limitations

- Parallelism of the USB camera threads with more than 2 cameras at once not yet verified on real hardware (USB bandwidth)
- cv2.Stitcher is computationally heavier than simple side-by-side concatenation - chosen deliberately (quality over performance), noticeably slower on weaker hardware