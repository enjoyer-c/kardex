"""
Reads and writes the plain-text inventory list (Inventory.txt).
 
One line per shelf, in order - line 1 corresponds to shelf number
config.SHELF_LOWER_LIMIT, line 2 to the next shelf number, and so on.
"""
 
from __future__ import annotations
from typing import Optional
 
import config


def read_all() -> list[str]:
    """Reads all inventory lines, in shelf order
    """
    try:
        with open(config.INVENTORY_FILE, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]
    except FileNotFoundError:
        print(f"[inventory] {config.INVENTORY_FILE} not found.")
        return []
 
 
def get_description(shelf_number: int) -> Optional[str]:
    """Returns the description for a given shelf number, or None if
    the shelf number is out of range."""
    lines = read_all()
    index = shelf_number - config.SHELF_LOWER_LIMIT
    if 0 <= index < len(lines):
        return lines[index]
    return None
 
 
def search(query: str) -> list[tuple[int, str]]:
    """Returns (shelf_number, description) pairs whose description
    contains the query (case-insensitive substring match).
    Returns an empty list for a blank query, rather than matching
    everything
    """
    query = query.strip().lower()
    if not query:
        return []
 
    results = []
    for shelf_number, description in enumerate(read_all(), start=config.SHELF_LOWER_LIMIT):
        if query in description.lower():
            results.append((shelf_number, description))
    return results
 
 
def write_all(lines: list[str]) -> None:
    """Overwrites the whole inventory file with the given lines, in
    shelf order. Used e.g. when a description gets edited via the GUI."""
    with open(config.INVENTORY_FILE, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
 
 

