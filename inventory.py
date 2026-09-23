"""
Reads and writes the plain-text inventory list (Inventory.txt).
One line per tray, in order - line 1 corresponds to tray number
config.TRAY_LOWER_LIMIT, line 2 to the next tray number, and so on.
"""
 
from __future__ import annotations

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
    tray order. Used e.g. when a description gets edited via the GUI."""
    with open(config.INVENTORY_FILE, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
 

def update_description(tray_number: int, new_description: str) -> None:
    """Updates a single tray's description and writes the whole file back."""
    lines = read_all()
    index = tray_number - config.TRAY_LOWER_LIMIT
 
    if not (0 <= index < len(lines)):
        raise ValueError(f"Tray number {tray_number} is out of valid range.")
 
    lines[index] = new_description
    write_all(lines)
