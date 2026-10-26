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

| File | Purpose |
|---|---|
| `main.py` | Flow control: door events, capture threads, startup checks, logging, single instance lock |
| `config.py` | All constants (paths, GPIO, camera settings, QR timing, tray limits) |
| `qr_code_scanner.py` | Ribbon cam, scanned permanently (readers: Aruco, then zbar) |
| `camera_streams.py` | Keeps every USB camera open, applies fixed camera settings, turns frames by 180° |
| `camera_capture.py` | Takes the frames of all USB cameras, crops the overlaps, saves the picture |
| `camera_setup.py` | Finds the USB cameras, camera order, startup checks |
| `door_sensor.py` | Door sensor (reed contact) via GPIO |
| `inventory.py` | Reads / writes `inventory.txt`, checks tray numbers |
| `gui.py` | Tkinter GUI: tray table, preview with magnifier, History, Manual Capture, Camera Setup |
| `setup_ribbon_cam.py` | Ribbon cam live preview for focusing (green = Aruco, yellow = zbar, red = not readable) |
| `*_mock.py` | Replace the hardware on Windows |

Details and design decisions: see the project documentation.

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