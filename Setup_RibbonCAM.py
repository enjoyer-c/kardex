"""
Live preview for the HQ ribbon camera (QR scanner) - for positioning
the camera and checking QR placement/focus during physical setup.
Shows the live feed with a green outline drawn around any QR code
currently detected, plus its decoded content - so you can see in real
time whether the QR is actually readable from the current position/
angle/distance, not just guess from the raw image.
"""

import cv2
from pyzbar.pyzbar import decode
from picamera2 import Picamera2

import config


def main() -> None:
    picam = Picamera2()
    preview_config = picam.create_preview_configuration(
        main={"size": config.QR_CAPTURE_SIZE, "format": "RGB888"}
    )
    picam.configure(preview_config)
    picam.start()

    try:
        while True:
            frame = picam.capture_array()
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

            for obj in decode(gray):
                if obj.type != "QRCODE":
                    continue

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

            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            cv2.imshow("Ribbon Cam - QR Setup (q = quit)", bgr)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        picam.stop()
        picam.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()