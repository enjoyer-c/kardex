#!/bin/bash
#
# One-time setup script for a fresh Raspberry Pi to run the Kardex project. 
# Installs ALL packages via apt
#
# Run once after flashing a new Pi / setting up a replacement board
# (as the normal user, NOT with sudo):
#   chmod +x setup.sh
#   ./setup.sh
#
# Safe to re-run - apt skips already-installed packages.

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
python3 -c "import tkinter, cv2, numpy, PIL.ImageTk, pyzbar.pyzbar, gpiozero, picamera2; print('All imports OK')"

echo ""
echo "=== Setup complete ==="
echo "Start the program with:"
echo "  source .venv/bin/activate"
echo "  python3 main.py"