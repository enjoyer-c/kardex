# Kardex Shuttle Logistics System

Automated high-bay warehouse add-on: a door sensor detects tray movement, a ribbon camera identifies the tray via QR code, USB cameras photograph the tray contents (stitched into one panorama), and a GUI provides a searchable inventory with image preview.

Runs on a Raspberry Pi 4 with real hardware, and on Windows with mock modules (no hardware needed) for development.

---

## Setup (Raspberry Pi)

```bash
chmod +x setup.sh
./setup.sh
source .venv/bin/activate
python3 main.py
```

`setup.sh` installs **all** dependencies via apt and creates a `.venv` with `--system-site-packages`.

Optional: `kardex.desktop` (copy to `~/.local/share/applications/`, adjust paths) adds a start-menu entry and the app icon in the taskbar.


---

## Process Flow

The flow is **not** a fixed sequence of door events. It is bound to what the ribbon camera sees:

| Door event | Action |
|---|---|
| **closes** | Ribbon cam scans (up to `QR_SCAN_TIMEOUT_S`). QR code visible → this tray is at the front. No code → no tray. The previous tray number is always forgotten first. |
| **opens** | If a tray is at the front → USB cameras take photos immediately. Otherwise nothing happens. |

Typical cycle:

1. Tray is ordered → door opens → no tray known → no photos → tray moves out
2. Tray reaches the delivery position → door closes → QR found → tray number known
3. Tray is sent back → door opens → photos taken → tray moves in → door closes → no QR → tray number cleared


A false trigger (e.g. a hand in the light barrier) can't break the flow: without a tray at the front it leads nowhere; with a tray at the front it just produces one extra photo - the final photo is still taken when the tray really goes back.

Edge cases handled: door opens while a scan is running (photos are taken as soon as the scan finds a tray), door closes again during a scan (rescan), door opens while a capture is running (a second capture follows right after).
---

## Modules

### main.py
Flow control + wiring between hardware and GUI.
- Two rules only (see Process Flow); status bar shows `NO_TRAY`, `SCANNING`, `TRAY_PRESENT` or `CAPTURING`
- QR scan and captures run in background threads; results are always passed back to the Tk main thread, even if a thread crashes
- Manual capture: allowed any time except while another capture is running
- On startup: shows a History error if the hall sensor isn't available, and a warning if the saved camera order doesn't match the connected cameras
- Logging: rotating log file (5 MB, 3 backups) + console; unhandled GUI errors are logged too

### config.py
All constants, platform-aware (same file on Windows and Pi). Paths (captures and logs on the external SSD), GPIO pin, camera resolution, stitching settings, QR timeout/scan interval, tray limits (1-50), `DOOR_TEST_BUTTON` (temporary).

### qr_code_scanner.py
Ribbon camera (Pi HQ Camera) via picamera2 + pyzbar. Scans until a QR code is found or the timeout is reached (short pause between attempts to save CPU). Camera is always released cleanly.

### camera_stitching.py
- Each USB camera is opened, warmed up, read and released per capture; all cameras are read in parallel
- `exclusive_cameras()`: one lock for all camera access (captures and Camera Setup search)
- OpenCV stitcher → panorama saved as `OUTPUT_DIR/<tray>/finalFrame_<timestamp>.jpg`; save failures are detected; max. `MAX_IMAGES_PER_TRAY` images per tray (oldest deleted)

### camera_setup.py
- Finds cameras via `/dev/v4l/by-path` (by-id collides for identical models like two C920s), duplicates removed
- `get_camera_devices()`: saved order from `camera_order.json`, fallback: all connected cameras
- `discover_cameras()`: functional test per camera, the test frame doubles as preview
- `check_saved_order()`: startup check whether the saved order still matches

### hall_sensor.py
Door sensor via GPIO (`pull_up=True`, magnet present = door closed). Reports its initial state on startup. If gpiozero or the GPIO pin isn't available, the program still starts and `error_message` is set. Temporary: `simulate_toggle()` for the test button.

### inventory.py
Reads/writes `inventory.txt` (one description per line, line 1 = tray 1). Writes are crash-safe (temp file + `os.replace`). `normalize_tray_number()` accepts only plain integers within the tray limits (`"01"` → `"1"`).

### gui.py
- Color-coded status, searchable tray table, image preview of the selected tray's latest capture
- Right-click → rename description
- After a capture, only the affected table row (and its preview) is refreshed
- Camera Setup: camera snapshots, reorder via arrows, Refresh All re-discovers, live ribbon-cam preview; search runs in the background
- Temporary: "TEST: Toggle Door" button simulates the door sensor (Pi only; on Windows use Enter in the console)

### Mock modules (Windows)
`hall_sensor_mock` (Enter toggles the door), `qr_code_scanner_mock` (always tray 1), `camera_stitching_mock` (webcams or placeholder images).

---

## Known Limitations

- Parallel capture with more than 2 USB cameras not yet verified on real hardware (USB bandwidth)
- If the door opens again during a running capture, the follow-up capture starts only after stitching of the first one has finished
- A disconnected sensor cable can't be detected by software (reads the same as an open door)
- The Windows QR mock always returns tray 1, so "tray gone" can't be tested on Windows