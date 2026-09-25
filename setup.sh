#!/bin/bash
#
# One-time setup script for a fresh Raspberry Pi to run the Kardex
# project. Installs ALL packages via apt (no pip) - apt packages are
# built to work together, so there are no version conflicts
#
# Run once after flashing a new Pi / setting up a replacement board:
#   chmod +x setup_pi.sh
#   ./setup_pi.sh
#
# Safe to re-run - apt skips already-installed packages.

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
    python3-numpy \
    python3-opencv \
    python3-pyzbar \
    python3-gpiozero \
    libzbar0 \
    python3-picamera2 \
    python3-libcamera \
    --no-install-recommends

echo "=== Creating virtual environment (.venv) ==="
if [ ! -d ".venv" ]; then
    # --system-site-packages: lets the venv see all the apt packages
    # above - nothing gets installed into the venv itself anymore
    python3 -m venv --system-site-packages .venv
    echo "Created .venv"
else
    echo ".venv already exists - skipping"
fi

echo "=== Verifying imports ==="
source .venv/bin/activate
python3 -c "import cv2, numpy, PIL, pyzbar, gpiozero, picamera2; print('All imports OK')"

echo ""
echo "=== Setup complete ==="
echo "Start the program with:"
echo "  source .venv/bin/activate"
echo "  python3 main.py"