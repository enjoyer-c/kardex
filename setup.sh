#!/bin/bash
#
# One-time setup script for a fresh Raspberry Pi to run the Kardex
# project. Installs system packages (apt) and Python packages (pip,
# inside a venv with --system-site-packages, since picamera2 needs
# access to the system-wide libcamera libraries).
#
# Run once after flashing a new Pi / setting up a replacement board:
#   chmod +x setup_pi.sh
#   ./setup_pi.sh
#
# Safe to re-run - apt/pip skip already-installed packages.

set -e  # stop immediately on any error, instead of continuing half-broken

echo "=== Updating package lists ==="
sudo apt update

echo "=== Installing system packages ==="
sudo apt install -y \
    python3-pip \
    python3-venv \
    python3-tk \
    python3-pil \
    python3-pil.imagetk \
    libzbar0 \
    python3-picamera2 \
    python3-libcamera \
    --no-install-recommends

echo "=== Creating virtual environment (.venv) ==="
if [ ! -d ".venv" ]; then
    # --system-site-packages: lets the venv see picamera2/libcamera,
    # which are only installed system-wide via apt, not pip-installable
    python3 -m venv --system-site-packages .venv
    echo "Created .venv"
else
    echo ".venv already exists - skipping"
fi

echo "=== Installing Python packages into .venv ==="
source .venv/bin/activate
pip install --upgrade pip
pip install opencv-python pillow pyzbar gpiozero numpy

echo "=== Verifying imports ==="
python3 -c "import cv2, PIL, pyzbar, gpiozero, picamera2; print('All imports OK')"

echo ""
echo "=== Setup complete ==="
echo "Start the program with:"
echo "  source .venv/bin/activate"
echo "  python3 main.py"