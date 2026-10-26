"""
Live preview for the QR scanner for positioning the camera and checking QR placement/focus during physical setup.
Uses EXACTLY the same readers as the main program (qr_code_scanner.scan_frame) - what is green here is also read
when the door opens. A green outline is drawn around the code (if the reader reports its corners), plus the
reader name and the time one scan took.

Status line:
    green   read by the main reader (aruco)
    yellow  only readable by the fallback reader (zbar) - works, but better improve position/light
    red     not readable

Started from Camera Setup in main.py, which releases its own ribbon cam stream for it and restarts it when this window closes.
"""

import time

import cv2
from picamera2 import Picamera2

import config
import qr_code_scanner

WINDOW_NAME = "Ribbon Cam - QR Setup (q or X = quit)"

# picamera2 "RGB888" frames are B, G, R - so the colors here are BGR too
GREEN = (0, 255, 0)
YELLOW = (0, 255, 255)
RED = (0, 0, 255)


def _put_status(frame, text: str, color) -> None:
    cv2.putText(frame, text, (15, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5)   # dark outline - readable on any background
    cv2.putText(frame, text, (15, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)


def main() -> None:
    picam = Picamera2(qr_code_scanner.ribbon_camera_num())
    # Same configuration as qr_code_scanner._open_camera - the preview must show exactly what the scanner sees
    preview_config = picam.create_still_configuration(
        main={"size": config.QR_CAPTURE_SIZE, "format": "RGB888"}
    )
    picam.configure(preview_config)
    picam.start()
    print(f"QR readers: {qr_code_scanner.reader_names()}")

    try:
        while True:
            frame = picam.capture_array()

            # Scan BEFORE drawing - the readers must see the untouched picture
            t0 = time.monotonic()
            result = qr_code_scanner.scan_frame(frame)
            scan_ms = (time.monotonic() - t0) * 1000

            if result is None:
                _put_status(frame, f"QR: not readable  ({scan_ms:.0f} ms)", RED)
            else:
                color = GREEN if result.reader == qr_code_scanner.MAIN_READER else YELLOW
                _put_status(frame, f"QR: '{result.data}' read by {result.reader}  ({scan_ms:.0f} ms)", color)
                if result.points:
                    pts = result.points
                    for i in range(len(pts)):
                        cv2.line(frame, pts[i], pts[(i + 1) % len(pts)], color, 3)

            cv2.imshow(WINDOW_NAME, frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            # X button: closing the window only hides it - the loop would keep running and block the camera.
            # getWindowProperty reports < 1 once the window was closed.
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        picam.stop()
        picam.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()