## Config (`config.py`)
- System & paths: cross-platform base directory (`BASE_DIR`), output folder (`OUTPUT_DIR`), inventory file (`INVENTORY_FILE`)
- Hardware: GPIO pins (e.g. hall sensor on pin 24), USB camera indices/resolutions
- Processing: image stitching mode, confidence threshold, shelf limits (1 to 50)

## Camera Stitching (`camera_stitching.py`)
- Captures one frame per camera; falls back to a synthetic frame if a camera is unavailable
- Stitches all frames into a panorama via OpenCV `Stitcher`; falls back to side-by-side concatenation if stitching fails
- Saves the result with a timestamp under `OUTPUT_DIR/<shelf_number>/`
- Enforces a max number of stored images per shelf (oldest gets deleted)

## GUI (`gui.py`)
- Tkinter interface: search bar, live status display, and history button (top);
  scrollable table listing all trays with descriptions 
- Live search filters the table as you type
- Right-click a row to rename its description
- Double-click a row to open the most recently captured image for that tray
- History window logs status/events with timestamps

## Hall Sensor (`hall_sensor.py`)
- Detects open/closed state via GPIO hall sensor
- `on_change` callback fires on state change; `is_open()` returns current state

## Inventory (`inventory.py`)
- Reads/writes the plain-text inventory list (`Inventory.txt`), one description per line in shelf order



## Process Flow

# =============================================================================
# PROCESS LOGIC
# =============================================================================
#
# 1. IDLE
#    Door is closed, system waits for a new request.
#
# 2. OUTBOUND
#    Door opens (1st time) -> tray moves out of the rack
#    into the delivery position.
#
# 3. AT_DELIVERY_POSITION
#    Door closes -> QR code is scanned to identify the tray. 
#    No QR found -> log (logging.error) -> retry.
#    System then waits while the user loads/unloads the tray.
#
# 4. CAPTURING_AND_STITCHING
#    Door opens (2nd time) -> all USB cameras each take one
#    picture, images are stitched, result is saved with a
#    timestamp - before the tray starts moving back.
#    Max. 3 stored images per tray number - oldest is deleted
#    when the limit is exceeded.
#
# 5. RETURNING
#    Door closes, tray drives back into the rack.
#
# 6. back to IDLE
#
# =============================================================================



