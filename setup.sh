#!/bin/bash
#
# One-time setup script for a fresh Raspberry Pi (Raspberry Pi OS based on Debian 13 "Trixie")
# to run the Kardex project.
#
# - System packages (Tk, camera, GPIO, zbar library) via apt
# - OpenCV and pyzbar via pip into the project's .venv, in the exact versions the program was tested with:
#     opencv-python: the apt version is older, and the Aruco QR reader needs OpenCV >= 4.7
#     pyzbar:        not available via apt on Trixie
#
# Run once after flashing a new Pi / setting up a replacement board
# (as the normal user, NOT with sudo):
#   chmod +x setup.sh
#   ./setup.sh
#
# Safe to re-run - apt and pip skip what is already installed.
# The system time must be correct, otherwise apt rejects the package lists ("Not live until ...").

set -e  # stop immediately on any error, instead of continuing half-broken

# Run without sudo - otherwise the .venv would belong to root
if [ "$EUID" -eq 0 ]; then
    echo "Please run this script as the normal user, without sudo."
    exit 1
fi

# Always work in the folder this script lives in (= project folder),
# no matter where it was started from
cd "$(dirname "$0")"

echo "=== Updating package lists ==="
sudo apt update

echo "=== Installing system packages ==="
sudo apt install -y \
    python3-venv \
    python3-pip \
    python3-tk \
    python3-pil \
    python3-pil.imagetk \
    python3-numpy \
    python3-gpiozero \
    python3-picamera2 \
    python3-libcamera \
    libzbar0t64 \
    v4l-utils \
    --no-install-recommends

echo "=== Creating virtual environment (.venv) ==="
if [ ! -d ".venv" ]; then
    # --system-site-packages: the venv also sees the apt packages above (picamera2, gpiozero, Tk, ...)
    python3 -m venv --system-site-packages .venv
    echo "Created .venv"
else
    echo ".venv already exists - skipping"
fi

echo "=== Installing OpenCV and pyzbar into the venv (tested versions) ==="
.venv/bin/pip install opencv-python==5.0.0.93 pyzbar==0.1.9

echo "=== Verifying imports ==="
.venv/bin/python3 -c "import tkinter, cv2, numpy, PIL.ImageTk, pyzbar.pyzbar, gpiozero, picamera2; print('All imports OK')"
.venv/bin/python3 -c "import cv2, sys; ok = hasattr(cv2, 'QRCodeDetectorAruco'); print('OpenCV', cv2.__version__, '- Aruco QR reader:', 'OK' if ok else 'MISSING (needs OpenCV >= 4.7)'); sys.exit(0 if ok else 1)"

echo ""
echo "=== Setup complete ==="
echo "Start the program with:"
echo "  .venv/bin/python3 main.py"
