"""
Live preview for the QR scanner for positioning the camera and checking QR placement/focus during physical setup.
Shows the live feed with a green outline drawn around any QR code zbar detects, plus its decoded content - so you can see in real
time whether the QR is actually readable from the current position/angle/distance, not just guess from the raw image.

If zbar finds nothing, the fallback readers of the main program are tried too (see qr_code_scanner.scan_frame) - a yellow text
then shows that the code is only readable with a fallback. Press 's' to save the current picture (for checking it afterwards).

Started from Camera Setup in main.py, which releases its own ribbon cam stream for it and restarts it when this window closes.
"""

from datetime import datetime

import cv2
from pyzbar.pyzbar import decode
from picamera2 import Picamera2

import config
import qr_code_scanner

WINDOW_NAME = "Ribbon Cam - QR Setup (q or X = quit, s = save picture)"


def _put_status(frame, text: str, color) -> None:
    cv2.putText(frame, text, (15, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5)   # dark outline - readable on any background
    cv2.putText(frame, text, (15, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)


def main() -> None:
    picam = Picamera2()
    preview_config = picam.create_preview_configuration(
        main={"size": config.QR_CAPTURE_SIZE, "format": "RGB888"}
    )
    picam.configure(preview_config)
    picam.start()

    try:
        while True:
            raw = picam.capture_array()
            frame = raw.copy()   # drawing goes onto the copy, saving ('s') uses the untouched picture
            gray = cv2.cvtColor(raw, cv2.COLOR_RGB2GRAY)

            found_by_zbar = False
            for obj in decode(gray):
                if obj.type != "QRCODE":
                    continue
                found_by_zbar = True

                points = obj.polygon
                if points:
                    pts = [(p.x, p.y) for p in points]
                    for i in range(len(pts)):
                        cv2.line(frame, pts[i], pts[(i + 1) % len(pts)], (0, 255, 0), 3)

                x, y, _w, _h = obj.rect
                cv2.putText(
                    frame, obj.data.decode("utf-8"), (x, max(y - 10, 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2,
                )

            if found_by_zbar:
                _put_status(frame, "QR: read by zbar", (0, 255, 0))
            else:
                # Same readers as the main program uses - shows whether a fallback would still find the code
                result = qr_code_scanner.scan_frame(raw)
                if result is not None:
                    _put_status(frame, f"QR: '{result.data}' - only readable with '{result.reader}'", (255, 255, 0))
                else:
                    _put_status(frame, "QR: not readable", (255, 0, 0))

            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            cv2.imshow(WINDOW_NAME, bgr)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                config.QR_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                path = config.QR_DEBUG_DIR / f"preview_{datetime.now().strftime(config.TIMESTAMP_FORMAT)}.jpg"
                cv2.imwrite(str(path), cv2.cvtColor(raw, cv2.COLOR_RGB2BGR))
                print(f"Saved: {path}")
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