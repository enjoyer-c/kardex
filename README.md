# Kardex Shuttle Logistics System

Automated high-bay warehouse add-on: a door sensor detects door movement, a ribbon camera identifies the tray via QR code, USB cameras capture the tray contents (stitched or side by side), and a GUI provides a searchable inventory with image preview.

Runs on a Raspberry Pi 4 and on Windows with mock modules for development.


## Process Flow

One rule, triggered by the door opening. Nothing is remembered between two door events - every opening is complete on its own.

| Door event | Action |
|---|---|
| **opens** | 1. USB cameras: newest frame of every camera, right away (~0.1 s after the signal)<br>2. Ribbon cam: looks for a QR code (max. `QR_SCAN_WINDOW_S`)<br>3. QR code with a valid tray number → photos saved under it. No QR code → photos discarded |
| **closes** | nothing |

Typical cycle:

1. Tray is ordered → door opens → nothing in front of the ribbon cam → photos discarded → tray moves out → door closes
2. Tray is sent back → door opens → photos + QR code of the standing tray → saved → tray moves in (~2.5 s after the door opened) → door closes

Both cameras run permanently, so nothing has to be started when the door opens. The tray number and the photos come from the same moment, so a photo can never end up under the wrong tray.

The very first sensor report after program start is only logged ("Door state at startup") - it's not a real door movement.

---

## Modules

### main.py
Flow control + wiring between hardware and GUI.
- One rule only (see Process Flow); no status display - what happened is visible in the History, the "Last Capture" column and the red error banner
- The door capture (photos → QR → save/discard) runs in a background thread; the result is always passed back to the Tk main thread, even if the thread crashes
- Starts the ribbon cam stream at startup; the Camera Setup live preview releases it and restarts it afterwards
- Every door signal is logged with milliseconds (`===== DOOR OPENED =====`), plus how long after the signal the photos were taken
- Manual capture: allowed any time except while another capture is running
- Startup checks: door sensor, ribbon cam and USB cameras - problems are shown in the red error banner and the History; a warning is logged if the saved camera order doesn't match the connected cameras
- Logging: rotating log file (5 MB, 3 backups), timestamps with milliseconds

### config.py
All constants, platform-aware: paths (captures and logs on the external SSD), GPIO pin and direction of the door sensor (`DOOR_SENSOR_INVERTED`), camera resolution, default picture mode (`PANORAMA_MODE`) and stitching settings, QR scan window, tray limits (1-50), magnifier size/zoom

### qr_code_scanner.py
Ribbon camera via picamera2 + pyzbar. Runs permanently (`start_stream()` at startup); `scan_now()` only reads the newest frames until a QR code is found or `QR_SCAN_WINDOW_S` is over. `stop_stream()` releases the camera for the live preview and at program end.

### camera_streams.py
- Every USB camera stays open permanently: one background thread per camera continuously grabs frames (`grab()`, cheap - no decoding)
- A capture only decodes the newest frame (`retrieve()`) - a few milliseconds instead of seconds for opening + warming up, and the exposure is always settled
- Frames older than `USB_CAMERA_MAX_FRAME_AGE_S` are never used; a camera that stops delivering is reopened automatically every `USB_CAMERA_RECONNECT_S`

### camera_stitching.py
- Two steps: `grab_frames()` takes the newest frame of every camera from the streams, all at the same moment; `combine_and_save()` combines and saves them once the tray number is known. `capture_and_stitch()` = both at once (manual capture)
- The file name is the moment the photos were taken, not when saving finished
- Picture mode: OpenCV stitcher (panorama) or images side by side in camera order - chosen in the Camera Setup window, saved in `settings.json`
- Result saved as `OUTPUT_DIR/<tray>/finalFrame_<timestamp>.jpg`; save failures are detected; max. `MAX_IMAGES_PER_TRAY` images per tray (oldest deleted)

### camera_setup.py
- Finds cameras via `/dev/v4l/by-path` (by-id collides for identical models like two C920s), duplicates removed
- `get_camera_devices()`: saved order from `camera_order.json`, fallback: all connected cameras
- `start_camera_streams()` / `stop_camera_streams()`: called at program start / end
- `discover_cameras()`: starts streams for newly plugged-in cameras, stops the ones of unplugged cameras, and returns one frame per camera as preview - no camera is opened or closed for it
- `check_saved_order()`: startup check whether the saved order still matches

### door_sensor.py
Door sensor via GPIO (`pull_up=True`). Which pin level means "door open" depends on the sensor - set with `DOOR_SENSOR_INVERTED` in `config.py` and check it in the History (`===== DOOR OPENED =====` must appear when the door really opens). The test sensor (reed contact) and the sensor at the lift (3-wire module) can behave differently. Reports its initial state on startup. If gpiozero or the GPIO pin isn't available, the program still starts and `error_message` is set.

### inventory.py
Reads/writes `inventory.txt`. Writes are crash-safe (temp file + `os.replace`). `normalize_tray_number()` accepts only plain integers within the tray limits (`"01"` → `"1"`).

### gui.py
- Red error banner for problems (sensor, cameras, failed scan/capture) - no status display
- Searchable tray table; right-click → rename description
- Image preview of the selected tray's latest capture, scaled to the size of the preview area; hold the left mouse button on the image for a magnifier
- After a capture, only the affected table row (and its preview) is refreshed
- Camera Setup (always available): live camera pictures (updated every `CAMERA_SETUP_PREVIEW_REFRESH_MS`, taken from the running streams), reorder via arrows, newly plugged-in cameras are found every time the window is opened, picture mode stitch / side by side, live ribbon-cam preview (separate window; the program releases the ribbon cam for it and restarts it when the preview is closed - no automatic photos meanwhile)

### Mock modules (Windows)
`door_sensor_mock` (Enter toggles the door), `qr_code_scanner_mock` (always tray 1), `camera_stitching_mock` (only replaces grabbing the frames - webcams or placeholder images; combining and saving is the real code).

---

## Known Limitations

- A disconnected sensor cable can't be detected by software (reads like a door state)
- The QR code must be readable right when the door opens (within `QR_SCAN_WINDOW_S`) - focus and light of the ribbon cam matter
- While the ribbon cam live preview is open, no automatic photos are taken (red banner)
- The Windows QR mock always returns tray 1, so "tray gone" can't be tested on Windows
- Temporary Buttons and functions
- All USB cameras stream permanently - with many cameras on one USB controller the bandwidth can run out (camera fails to open). Then lower `USB_CAMERA_FPS` or spread the cameras over different USB ports