"""
Live preview for the two USB cameras (tray photo cams) - for
physically positioning and focusing them during setup.

Uses whichever devices are currently configured in config.py
(config.USB_CAMERA_DEVICES - either from a saved Camera Setup order,
or auto-discovered), so it always shows the same cameras the main
program would actually use.

Requires a display (local monitor, or VNC) since it uses cv2.imshow.
Do not run this at the same time as main.py - both would try to use
the same USB cameras at once.

Press 'q' in the window to quit, or Ctrl+C in the terminal.
"""

import cv2

import config


def main() -> None:
    devices = config.USB_CAMERA_DEVICES
    if not devices:
        print("Keine USB-Kameras konfiguriert - erst Camera Setup im Hauptprogramm ausfuehren.")
        return

    caps = []
    for device in devices:
        cam = cv2.VideoCapture(device, config.CAP_BACKEND)
        cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*config.USB_CAMERA_FOURCC))
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, config.USB_CAMERA_RESOLUTION[0])
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, config.USB_CAMERA_RESOLUTION[1])
        if not cam.isOpened():
            print(f"Konnte Kamera nicht oeffnen: {device}")
        caps.append(cam)

    print("Live-Feed laeuft - 'q' im Fenster druecken zum Beenden.")

    try:
        while True:
            frames = []
            for cam in caps:
                ret, frame = cam.read()
                if ret:
                    frames.append(frame)

            if frames and len(frames) == len(caps):
                height = min(f.shape[0] for f in frames)
                resized = [
                    cv2.resize(f, (int(f.shape[1] * height / f.shape[0]), height))
                    for f in frames
                ]
                combined = cv2.hconcat(resized)
                cv2.imshow("USB Cams - Setup (q = quit)", combined)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        for cam in caps:
            cam.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()