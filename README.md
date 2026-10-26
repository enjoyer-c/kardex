# Kardex Shuttle Logistics System

Automated high-bay warehouse add-on: a door sensor detects door movement, a ribbon camera identifies the tray via QR code, USB cameras capture the tray contents (cropped at the overlaps and put side by side), and a GUI provides a searchable inventory with image preview.

Runs on a Raspberry Pi 4. On Windows, mock modules replace the hardware for development.


## Process Flow

One rule, triggered by the door opening. Nothing is remembered between two door events: every opening is complete on its own.

| Door event | Action |
|---|---|
| **opens** | 1. USB cameras: newest frame of every camera, right away (~0.1 s after the signal)<br>2. At the same time, ribbon cam (scanned permanently): QR code seen from `QR_RECENT_S` before to `QR_SCAN_WINDOW_S` after the signal<br>3. QR code with a valid tray number → photos saved under it. No QR code → photos discarded |
| **closes** | nothing |

Typical cycle:

1. Tray is ordered → door opens → nothing in front of the ribbon cam → photos discarded → tray moves out → door closes
2. Tray is sent back → door opens → photos + QR code of the standing tray → saved → tray moves in (a few seconds after the door opened) → door closes

All cameras (ribbon cam and USB cameras) run permanently, so nothing has to be started when the door opens. In practice the QR code is usually already read before the door signal arrives. The tray number and the photos come from the same moment, so a photo can never end up under the wrong tray.

The very first sensor report after program start is only logged ("Door state at startup"), it's not a real door movement.

---

## Running

Start via the desktop icon, or from a terminal to see error messages directly:

```
cd /home/pi/kardex/LinuxRuntimeSpeedy_new
/home/pi/.venv/bin/python3 main.py
```

The program runs only once: a second start (e.g. double-click on the icon) shows a message and quits.

### Files on the Pi

| File / folder | Content |
|---|---|
| `settings.json` (program folder) | Camera order and seam overlaps, written by Camera Setup |
| `inventory.txt` (program folder) | One description per tray, one line per tray |
| `/mnt/kardex_ssd/captures/<tray>/` | Saved pictures `finalFrame_<timestamp>.jpg` |
| `/mnt/kardex_ssd/logs/kardex.log` | Log file (rotating, 5 MB × 3) |

---

## Modules

### main.py
Flow control and wiring between hardware and GUI.
- One rule only (see Process Flow). There is no status display: what happened is visible in the History, the "Last Capture" column and the red error banner
- The door capture runs in a background thread: QR check and photos in parallel, then save or discard. The result is always passed back to the Tk main thread, even if the thread crashes
- Starts the ribbon cam stream at startup. The ribbon cam live preview releases it and restarts it afterwards
- Every door signal is logged with milliseconds (`===== DOOR OPENED =====`), plus how long after the signal the photos were taken and when the QR code was seen
- Manual capture: allowed any time except while another capture is running
- Startup checks: door sensor, ribbon cam, USB cameras and saved camera order. Problems are shown in the red error banner and the History
- Logging: rotating log file (5 MB, 3 backups), timestamps with milliseconds
- Single instance lock (`LOCK_FILE`)

### config.py
All constants, platform-aware: paths (captures and logs on the external SSD), GPIO pin and direction of the door sensor (`DOOR_SENSOR_INVERTED`), USB camera resolution and fixed camera settings (`USB_CAMERA_CONTROLS`: autofocus and auto white balance off), picture rotation (`ROTATE_IMAGE_180`), default seam overlaps (`SEAM_OVERLAP_PX`), QR scan window and watchdog times, tray limits (1 to 50), magnifier size and zoom.

### qr_code_scanner.py
Ribbon camera (Raspberry Pi HQ Camera) via picamera2.
- Runs AND is scanned permanently: a background thread scans every newest frame and logs when a code comes into view or leaves (`QR code in view` / `out of view`)
- `scan_now(signal_time)` only looks at what was seen around the door signal, so usually the answer is already there
- Two readers one after another: OpenCV's Aruco QR reader (OpenCV >= 4.7, reads the labels on metal best), then zbar as fallback. The active readers are logged at startup
- Still configuration (like the old v0.2 scanner): with the video configuration some QR codes were unreadable
- Picks the ribbon cam explicitly, never one of the USB webcams that libcamera also lists
- Robust for long-term operation: a frame that takes longer than `QR_FRAME_TIMEOUT_S` counts as an error, after `QR_CAMERA_RESTART_AFTER` errors the camera is restarted. Without fresh frames, a door opening reports an error (red banner) instead of "no QR code"
- `stop_stream()` releases the camera for the live preview and at program end

### setup_ribbon_cam.py
Live preview of the ribbon cam for positioning and focusing, started from Camera Setup. Uses exactly the same readers as the program: green = read by Aruco, yellow = only read by zbar, red = not readable. Also shows how long one scan takes. Close with `q` or the X.

### camera_streams.py
- Every USB camera stays open permanently: one background thread per camera continuously grabs frames (`grab()`, cheap, no decoding)
- A capture only decodes the newest frame (`retrieve()`): a few milliseconds instead of seconds for opening and warming up, and the exposure is always settled
- On every (re)open, the fixed settings from `USB_CAMERA_CONTROLS` are set via `v4l2-ctl`, one call per setting
- Frames are turned by 180° if `ROTATE_IMAGE_180` is set (the cameras are mounted upside down), so every following step already gets the right orientation
- Frames older than `USB_CAMERA_MAX_FRAME_AGE_S` are never used. A camera that stops delivering is reopened automatically every `USB_CAMERA_RECONNECT_S`

### camera_capture.py
- Two steps: `grab_frames()` takes the newest frame of every camera from the streams, all at the same moment. `combine_and_save()` combines and saves them once the tray number is known. `capture_and_save()` does both at once (manual capture)
- Combining: one overlap value per seam. Half of it is cut off each of the two neighbouring cameras, the outer edges stay, so the picture stays centered. Values from Camera Setup (`settings.json`), defaults in `config.py`
- If the values don't fit the cameras (e.g. one is missing), the images are saved side by side uncut, with a warning in the log
- Result saved as `OUTPUT_DIR/<tray>/finalFrame_<timestamp>.jpg` (timestamp = moment the photos were taken). Max. `MAX_IMAGES_PER_TRAY` images per tray, the oldest are deleted
- Reads and writes `settings.json` (`read_settings()` / `write_settings()`)

### camera_setup.py
- Finds cameras via `/dev/v4l/by-path` (by-id collides for identical models like the C920s), duplicates removed
- `get_camera_devices()`: the order saved in `settings.json`. If none is saved or a saved camera is missing (e.g. plugged into another USB port): all connected cameras in USB port order
- `start_camera_streams()` / `stop_camera_streams()`: called at program start and end
- `discover_cameras()`: starts streams for newly plugged-in cameras, stops the ones of unplugged cameras, and returns one frame per camera as preview. No camera is opened or closed for it
- `check_saved_order()`: startup check whether the saved order still matches

### door_sensor.py
Door sensor (reed contact) via GPIO (`pull_up=True`). Which contact state means "door open" is set with `DOOR_SENSOR_INVERTED` in `config.py`. Check it in the History: `===== DOOR OPENED =====` must appear when the door really opens. Reports its initial state on startup. If gpiozero or the GPIO pin isn't available, the program still starts and `error_message` is set.

### inventory.py
Reads, searches and writes `inventory.txt`. Writes are crash-safe (temp file + `os.replace`). `normalize_tray_number()` accepts only plain integers within the tray limits (`"01"` → `"1"`), so a wrong label can never save into a wrong folder.

### gui.py
- Red error banner for problems (sensor, cameras, failed scan or capture)
- Searchable tray table, right-click → rename description
- Image preview of the selected tray's latest capture, scaled to the size of the preview area. Hold the left mouse button on the image for a magnifier
- After a capture, only the affected table row (and its preview) is refreshed
- History popup with the log entries (the last lines of the log file are loaded at startup)
- Camera Setup (always available): live camera pictures from the running streams, reorder via arrows, overlap per seam with a live preview of the combined picture (red seam lines only in the preview, not in saved photos). Newly plugged-in cameras are found every time the window is opened. Also starts the ribbon cam live preview: the program releases the ribbon cam for it and restarts it when the preview is closed, no automatic photos meanwhile

### Mock modules (Windows)
`door_sensor_mock` (Enter toggles the door, reports the initial state like the real sensor), `qr_code_scanner_mock` (always tray 1), `camera_capture_mock` (only replaces grabbing the frames with webcams or placeholder images; combining and saving is the real code).

---

## Known Limitations

- A disconnected sensor cable can't be detected by software (reads like a door state)
- The QR code must be visible around the door opening (`QR_RECENT_S` before to `QR_SCAN_WINDOW_S` after). Focus, light and a white border around the label matter. Labels with a too narrow white border on reflective metal can be unreadable
- While the ribbon cam live preview is open, no automatic photos are taken (red banner)
- The Raspberry Pi has no hardware clock: without time synchronisation (NTP) the time is wrong after a restart, and with it the file names, the "Last Capture" column and the log
- The Windows QR mock always returns tray 1, so "no tray in front" can't be tested on Windows
- The door test button (`DOOR_TEST_BUTTON` in `config.py`) is a temporary function for testing without a magnet
- The outer right USB camera vibrates slightly when the door opens or the lift moves, so its part of the picture can be a little blurred
- All USB cameras stream permanently. With many cameras on one USB controller the bandwidth can run out (camera fails to open). Then lower `USB_CAMERA_FPS` or spread the cameras over different USB ports