"""
Reads and writes the plain-text inventory list (Inventory.txt).
One line per tray, in order - line 1 corresponds to tray number
config.TRAY_LOWER_LIMIT, line 2 to the next tray number, and so on.
"""
 
from __future__ import annotations

import os

import config


def read_all() -> list[str]:
    """Reads all inventory lines, in tray order"""
    try:
        with open(config.INVENTORY_FILE, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]
    except FileNotFoundError:
        print(f"[inventory] {config.INVENTORY_FILE} not found.")
        return []
 
 
def search(query: str) -> list[tuple[int, str]]:
    """Returns (tray_number, description) pairs whose description
    contains the query (case-insensitive substring match).
    Returns an empty list for a blank query, rather than matching
    everything."""
    query = query.strip().lower()
    if not query:
        return []
 
    results = []
    for tray_number, description in enumerate(read_all(), start=config.TRAY_LOWER_LIMIT):
        if query in description.lower():
            results.append((tray_number, description))
    return results
 
 
def write_all(lines: list[str]) -> None:
    """Overwrites the whole inventory file with the given lines, in
    tray order. Used e.g. when a description gets edited via the GUI.

    Crash-safe: writes into a temporary file first and only then swaps
    it in place of the real file with os.replace(). os.replace is atomic
    - at any moment, inventory.txt is either the complete old or the
    complete new version, never half-written (e.g. on power loss).
    The temp file sits in the SAME folder on purpose: os.replace is only
    atomic within one filesystem.
    """
    target = config.INVENTORY_FILE
    temp = target.with_name(target.name + ".tmp")

    try:
        with open(temp, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
            # push the data from Python/OS buffers onto the SD card BEFORE
            # the swap - otherwise the swap could survive a power loss
            # while the new content itself didn't
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp, target)
    except BaseException:
        # something went wrong - the original file is untouched, just
        # clean up the leftover temp file and pass the error on
        temp.unlink(missing_ok=True)
        raise
 

def update_description(tray_number: int, new_description: str) -> None:
    """Updates a single tray's description and writes the whole file back."""
    lines = read_all()
    index = tray_number - config.TRAY_LOWER_LIMIT
 
    if not (0 <= index < len(lines)):
        raise ValueError(f"Tray number {tray_number} is out of valid range.")
 
    lines[index] = new_description
    write_all(lines)


def normalize_tray_number(raw: str) -> str | None:
    """Checks a tray number coming from outside (QR code, manual input)
    and returns it in normalized form, or None if it's invalid.

    Accepted: plain digits only (surrounding whitespace is ignored),
    within TRAY_LOWER_LIMIT..TRAY_UPPER_LIMIT.
    Normalized: leading zeros are removed ("01" -> "1"), so the same
    tray always ends up in the same folder (OUTPUT_DIR/1, never /01).
    Rejected: letters, signs ("+5", "-3"), decimals ("1.0"), empty
    input, and anything out of range.
    """
    text = raw.strip()

    # isascii() on top of isdigit(): isdigit() alone would also accept
    # other Unicode digits like superscripts, which int() can't parse
    if not (text.isascii() and text.isdigit()):
        return None

    number = int(text)
    if not (config.TRAY_LOWER_LIMIT <= number <= config.TRAY_UPPER_LIMIT):
        return None

    return str(number)