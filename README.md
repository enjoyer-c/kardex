# Kardex Shuttle Logistics System

Automated high-bay warehouse add-on: a door sensor detects door movement, a ribbon camera identifies the tray via QR code, USB cameras capture the tray contents (stitched or side by side), and a GUI provides a searchable inventory with image preview.

Runs on a Raspberry Pi 4 and on Windows with mock modules for development.


## Process Flow

The flow is event-driven: every door event is handled on its own, and what the ribbon camera sees decides what happens.

| Door event | Action |
|---|---|
| **closes** | The previous tray number is forgotten, then the ribbon cam scans (up to `QR_SCAN_TIMEOUT_S`). QR code visible → this tray is at the front. No code → no tray. |
| **opens** | If a tray is at the front → USB cameras take photos immediately. Otherwise nothing happens. |

Typical cycle:

1. Tray is ordered → door opens → no tray known → no photos → tray moves out
2. Tray reaches the delivery position → door closes → QR found → tray number known
3. Tray is sent back → door opens → photos taken → tray moves in → door closes → no QR → tray number cleared


A false trigger (e.g. a hand in the light barrier) can't break the flow: without a tray at the front it leads nowhere; with a tray at the front it just produces one extra photo - the final photo is still taken when the tray really goes back.

---

## Modules

### main.py
Flow control + wiring between hardware and GUI.
- Two rules only (see Process Flow); status bar shows `NO_TRAY`, `SCANNING`, `TRAY_PRESENT` or `CAPTURING`
- QR scan and captures run in background threads; results are always passed back to the Tk main thread, even if a thread crashes
- Before each scan, an open ribbon-cam live preview is closed automatically
- Manual capture: allowed any time except while another capture is running
- Startup checks: door sensor, ribbon cam and USB cameras - problems are shown in the red error banner and the History; a warning is logged if the saved camera order doesn't match the connected cameras
- Logging: rotating log file (5 MB, 3 backups)

### config.py
All constants, platform-aware: paths (captures and logs on the external SSD), GPIO pin, camera resolution, default picture mode (`PANORAMA_MODE`) and stitching settings, QR timeout/scan interval, tray limits (1-50), magnifier size/zoom

### qr_code_scanner.py
Ribbon camera via picamera2 + pyzbar. Scans until a QR code is found or the timeout is reached (short pause between attempts to save CPU). Camera is always released cleanly.

### camera_streams.py
- Every USB camera stays open permanently: one background thread per camera continuously grabs frames (`grab()`, cheap - no decoding)
- A capture only decodes the newest frame (`retrieve()`) - a few milliseconds instead of seconds for opening + warming up, and the exposure is always settled
- Frames older than `USB_CAMERA_MAX_FRAME_AGE_S` are never used; a camera that stops delivering is reopened automatically every `USB_CAMERA_RECONNECT_S`

### camera_stitching.py
- Takes the newest frame of every camera from the streams, all at the same moment; the time until the frames are taken is written to the log
- `exclusive_cameras()`: only one capture at a time
- Picture mode: OpenCV stitcher (panorama) or images side by side in camera order - chosen in the Camera Setup window, saved in `settings.json`
- Result saved as `OUTPUT_DIR/<tray>/finalFrame_<timestamp>.jpg`; save failures are detected; max. `MAX_IMAGES_PER_TRAY` images per tray (oldest deleted)

### camera_setup.py
- Finds cameras via `/dev/v4l/by-path` (by-id collides for identical models like two C920s), duplicates removed
- `get_camera_devices()`: saved order from `camera_order.json`, fallback: all connected cameras
- `start_camera_streams()` / `stop_camera_streams()`: called at program start / end
- `discover_cameras()`: starts streams for newly plugged-in cameras, stops the ones of unplugged cameras, and returns one frame per camera as preview - no camera is opened or closed for it
- `check_saved_order()`: startup check whether the saved order still matches

### door_sensor.py
Door sensor (reed contact) via GPIO (`pull_up=True`, magnet present = door closed). Reports its initial state on startup. If gpiozero or the GPIO pin isn't available, the program still starts and `error_message` is set.

### inventory.py
Reads/writes `inventory.txt`. Writes are crash-safe (temp file + `os.replace`). `normalize_tray_number()` accepts only plain integers within the tray limits (`"01"` → `"1"`).

### gui.py
- Color-coded status bar and a red error banner for problems (sensor, cameras, failed scan/capture)
- Searchable tray table; right-click → rename description
- Image preview of the selected tray's latest capture, scaled to the size of the preview area; hold the left mouse button on the image for a magnifier
- After a capture, only the affected table row (and its preview) is refreshed
- Camera Setup (always available): live camera pictures (updated every `CAMERA_SETUP_PREVIEW_REFRESH_MS`, taken from the running streams), reorder via arrows, Refresh All re-discovers, picture mode stitch / side by side, live ribbon-cam preview

### Mock modules (Windows)
`door_sensor_mock` (Enter toggles the door), `qr_code_scanner_mock` (always tray 1), `camera_stitching_mock` (webcams or placeholder images).

---

## Known Limitations

- A disconnected sensor cable can't be detected by software (reads the same as an open door)
- The Windows QR mock always returns tray 1, so "tray gone" can't be tested on Windows
- Temporary Buttons and functions
- All USB cameras stream permanently - with many cameras on one USB controller the bandwidth can run out (camera fails to open). Then lower `USB_CAMERA_FPS` or spread the cameras over different USB ports