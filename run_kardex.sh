#!/bin/bash
#
# Starts the Kardex program and starts it again if it ended with an error.
# The program ends itself with exit code 75 when the ribbon cam hangs and can't be recovered
# from within the program (see qr_code_scanner.restart_program). A normal close of the window
# ends with exit code 0 and is NOT restarted.
#
# Used by the desktop icon and the autostart entry.

cd "$(dirname "$0")"

while true; do
    .venv/bin/python3 main.py
    code=$?
    if [ $code -eq 0 ]; then
        exit 0          # window closed normally
    fi
    echo "Kardex ended with exit code $code - restarting in 10 s ..."
    sleep 10
done