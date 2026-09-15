"""
GUI Layout:

Section 1 - Row 1: (spacer) - Status (center) - (spacer) - Manual Capture button - History button
Section 1 - Row 2: Search bar, wider, centered

Section 2: Table listing all tray's (1-50), scrollable

*functions:
    - History open seperate popup-Window
    - Right-clicking on a row allows to rename descriptions
    - search inventory
    - double click on a row opens the latest captured image for that tray
    - manual capture: opens a small popup to enter a tray number and
      trigger a capture without waiting for the automatic door-sensor
      flow (meant as a fallback, e.g. if the door magnet/sensor fails)
"""

from __future__ import annotations
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageTk

import config
import inventory


STATUS_COLORS = {
    "IDLE": ("#e8f5e9", "#2e7d32"),
    "OUTBOUND": ("#fff3e0", "#e65100"),
    "AT_DELIVERY_POSITION": ("#e3f2fd", "#1565c0"),
    "CAPTURING_AND_STITCHING": ("#e3f2fd", "#1565c0"),
    "RETURNING": ("#fff3e0", "#e65100"),
}


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Kardex Shuttle Logistics System - Test")
        self.root.geometry("1920x1080")

        self._log_entries: list[str] = []
        self._history_window: Optional[tk.Toplevel] = None
        self._history_listbox: Optional[tk.Listbox] = None
        self._image_window: Optional[tk.Toplevel] = None
        self._image_label: Optional[ttk.Label] = None
        self._image_photo = None
        self._image_info_var: Optional[tk.StringVar] = None
        self._manual_capture_window: Optional[tk.Toplevel] = None
        self._manual_tray_var: Optional[tk.StringVar] = None

        # set from main.py - called when the user triggers a manual capture
        self.on_manual_capture: Optional[Callable[[str], None]] = None

        self._build_top_section()
        self._build_tray_table()

    # --- Section 1: Status / Manual Capture / History (row 0),
    #     Search (row 1) - shared grid so both rows center on the same
    #     point regardless of the buttons' width on the right ----------

    def _build_top_section(self) -> None:
        top_frame = ttk.Frame(self.root)
        top_frame.pack(padx=20, pady=(20, 15), fill="x")
        top_frame.grid_columnconfigure(0, weight=1)  # left spacer
        top_frame.grid_columnconfigure(1, weight=0)  # status / search
        top_frame.grid_columnconfigure(2, weight=1)  # right spacer
        top_frame.grid_columnconfigure(3, weight=0)  # manual capture button
        top_frame.grid_columnconfigure(4, weight=0)  # history button

        self.status_text = tk.StringVar(value="IDLE - waiting for door to open")
        # tk.Label statt ttk.Label, weil ttk dynamische bg/fg-Farben nicht
        # sauber unterstuetzt (Styles waeren noetig)
        self.status_label = tk.Label(
            top_frame,
            textvariable=self.status_text,
            font=("Arial", 24, "bold"),
            padx=20,
            pady=8,
        )
        self.status_label.grid(row=0, column=1)
        bg, fg = STATUS_COLORS["IDLE"]
        self.status_label.configure(bg=bg, fg=fg)

        manual_button = ttk.Button(top_frame, text="Manual Capture", command=self._open_manual_capture_window)
        manual_button.grid(row=0, column=3, padx=(0, 10), sticky="e")

        history_button = ttk.Button(top_frame, text="History", command=self._open_history_window)
        history_button.grid(row=0, column=4, sticky="e")

        # Search - placed in the same column (1) as the status label, so
        # it's centered on exactly the same point, unaffected by the
        # manual/history buttons sitting further right
        search_frame = ttk.Frame(top_frame)
        search_frame.grid(row=1, column=1, pady=(12, 0))

        ttk.Label(search_frame, text="search:", font=("Arial", 13)).pack(side="left", padx=(0, 8))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=50, font=("Arial", 13))
        search_entry.pack(side="left")
        search_entry.bind("<KeyRelease>", self._handle_search_change)

        # Invisible mirror of the "search:" label on the right - without
        # this, the entry box visually drifts right (the label only adds
        # width on the left), so it looks off-center under the status
        # box even though this whole frame is centered in the grid cell
        style = ttk.Style()
        bg_color = style.lookup("TFrame", "background") or self.root.cget("bg")
        tk.Label(
            search_frame, text="search:", font=("Arial", 13), fg=bg_color, bg=bg_color
        ).pack(side="left", padx=(8, 0))

    def set_status(self, text: str, state_name: str = "IDLE") -> None:
        self.status_text.set(text)
        bg, fg = STATUS_COLORS.get(state_name, ("#eeeeee", "#333333"))
        self.status_label.configure(bg=bg, fg=fg)

    def refresh(self) -> None:
        """Forces pending GUI redraws immediately - needed because a
        status set right before a blocking call (QR scan, camera capture)
        wouldn't otherwise repaint until the blocking call returns.
        """
        self.root.update_idletasks()

    def _handle_search_change(self, event=None) -> None:
        query = self.search_var.get()
        self._populate_tray_table(query)

        children = self.tray_table.get_children()
        if children:
            self.tray_table.see(children[0])
            self.tray_table.selection_set(children[0])

    # --- Manual capture (popup window) ------------------------------------

    def _open_manual_capture_window(self) -> None:
        """Opens a small popup to enter a tray number and trigger a
        capture manually - kept out of the main view since this is a
        fallback path, not something used in normal operation."""

        if self._manual_capture_window is not None and self._manual_capture_window.winfo_exists():
            self._manual_capture_window.lift()
            self._manual_capture_window.focus_force()
            return

        self._manual_capture_window = tk.Toplevel(self.root)
        self._manual_capture_window.title("Manual Capture")
        self._manual_capture_window.geometry("360x150")
        self._manual_capture_window.resizable(False, False)

        ttk.Label(
            self._manual_capture_window,
            text="Fallback only - use if the automatic\ndoor sensor didn't trigger correctly.",
            font=("Arial", 10),
            justify="center",
        ).pack(pady=(15, 10))

        entry_frame = ttk.Frame(self._manual_capture_window)
        entry_frame.pack()
        ttk.Label(entry_frame, text="Tray Nr.:").pack(side="left", padx=(0, 5))
        self._manual_tray_var = tk.StringVar()
        entry = ttk.Entry(entry_frame, textvariable=self._manual_tray_var, width=10)
        entry.pack(side="left")
        entry.focus_set()

        ttk.Button(
            self._manual_capture_window, text="Take a Picture", command=self._handle_manual_capture
        ).pack(pady=15)

        def _on_close() -> None:
            self._manual_capture_window.destroy()
            self._manual_capture_window = None
            self._manual_tray_var = None

        self._manual_capture_window.protocol("WM_DELETE_WINDOW", _on_close)

    def _handle_manual_capture(self) -> None:
        tray_number = self._manual_tray_var.get().strip() if self._manual_tray_var else ""
        if not tray_number:
            messagebox.showwarning("Input missing", "Please enter the tray number.", parent=self._manual_capture_window)
            return

        if self.on_manual_capture:
            self.on_manual_capture(tray_number)

        if self._manual_capture_window is not None and self._manual_capture_window.winfo_exists():
            self._manual_capture_window.destroy()
            self._manual_capture_window = None
            self._manual_tray_var = None

    # --- History (separate pop-up window) --------------------------------

    def _open_history_window(self) -> None:
        if self._history_window is not None and self._history_window.winfo_exists():
            self._history_window.lift()
            self._history_window.focus_force()
            return

        self._history_window = tk.Toplevel(self.root)
        self._history_window.title("History")
        self._history_window.geometry("500x400")

        self._history_listbox = tk.Listbox(self._history_window, font=("Consolas", 10))
        self._history_listbox.pack(padx=10, pady=10, fill="both", expand=True)

        for entry in self._log_entries:
            self._history_listbox.insert(tk.END, entry)
        self._history_listbox.see(tk.END)

        def _on_close() -> None:
            self._history_window.destroy()
            self._history_window = None
            self._history_listbox = None

        self._history_window.protocol("WM_DELETE_WINDOW", _on_close)

    def log_event(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {text}"
        self._log_entries.append(entry)

        if self._history_listbox is not None and self._history_window is not None and self._history_window.winfo_exists():
            self._history_listbox.insert(tk.END, entry)
            self._history_listbox.see(tk.END)

    # --- Section 2: Tray-table ----------------------------------------

    def _build_tray_table(self) -> None:
        table_frame = ttk.Frame(self.root)
        table_frame.pack(padx=20, pady=(0, 20), fill="both", expand=True)

        style = ttk.Style()
        style.configure("Treeview", font=("Arial", 14), rowheight=32)
        style.configure("Treeview.Heading", font=("Arial", 14, "bold"))

        columns = ("tray", "description", "last_opened")
        self.tray_table = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.tray_table.heading("tray", text="Tray Nr.")
        self.tray_table.heading("description", text="Description")
        self.tray_table.heading("last_opened", text="Last opened")
        self.tray_table.column("tray", width=100, stretch=False, anchor="center")
        self.tray_table.column("description", width=900, anchor="w")
        self.tray_table.column("last_opened", width=140, stretch=False, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tray_table.yview)
        self.tray_table.configure(yscrollcommand=scrollbar.set)

        self.tray_table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Right-clicking opens the context menu
        self.tray_table.bind("<Button-3>", self._handle_right_click)
        # Double-clicking shows the latest captured image for that tray
        self.tray_table.bind("<Double-1>", self._handle_double_click)

        self._populate_tray_table()

    def _get_last_capture_date(self, shelf_number: int) -> str:
        folder = config.OUTPUT_DIR / str(shelf_number)
        images = sorted(folder.glob("finalFrame_*.jpg")) if folder.exists() else []
        if not images:
            return "-"
        timestamp_str = images[-1].stem.replace("finalFrame_", "")
        try:
            timestamp = datetime.strptime(timestamp_str, config.TIMESTAMP_FORMAT)
            return timestamp.strftime("%d.%m.%Y")
        except ValueError:
            return "-"

    def _populate_tray_table(self, filter_query: str = "") -> None:
        self.tray_table.delete(*self.tray_table.get_children())

        if filter_query.strip():
            rows = inventory.search(filter_query)
        else:
            rows = list(enumerate(inventory.read_all(), start=config.SHELF_LOWER_LIMIT))

        for shelf_number, description in rows:
            last_opened = self._get_last_capture_date(shelf_number)
            self.tray_table.insert("", "end", values=(shelf_number, description, last_opened))

    # --- Rename with right mouse button ----------------------------------------

    def _handle_right_click(self, event) -> None:
        """Shows a context menu with a Rename option for the row under
        the cursor."""

        row_id = self.tray_table.identify_row(event.y)
        if not row_id:
            return

        self.tray_table.selection_set(row_id)

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Rename", command=lambda: self._rename_row(row_id))
        menu.post(event.x_root, event.y_root)

    def _rename_row(self, row_id: str) -> None:
        """Prompts for a new description, confirms with the user, then
        writes it to Inventory.txt and updates the table in place."""

        shelf_number_str, current_description, last_opened = self.tray_table.item(row_id, "values")

        new_description = simpledialog.askstring(
            "Rename",
            f"New description for tray {shelf_number_str}:",
            initialvalue=current_description,
            parent=self.root,
        )

        if new_description is None:  # Dialog was canceled
            return
        new_description = new_description.strip()
        if not new_description:
            return

        confirmed = messagebox.askyesno(
            "Confirm Rename",
            f"Tray {shelf_number_str} rename?\n\n"
            f"Old: {current_description}\n"
            f"New: {new_description}",
            parent=self.root,
        )
        if not confirmed:
            return

        shelf_number = int(shelf_number_str)
        inventory.update_description(shelf_number, new_description)

        # Update the table directly instead of reloading it entirely
        self.tray_table.item(row_id, values=(shelf_number, new_description, last_opened))
        self.log_event(f"Tray {shelf_number} renamed: {new_description}")

    # --- Double-click: show last captured image ---------------------------

    def _handle_double_click(self, event) -> None:
        row_id = self.tray_table.identify_row(event.y)
        if not row_id:
            return

        shelf_number_str, _, _ = self.tray_table.item(row_id, "values")
        self._show_last_capture(int(shelf_number_str))

    def _show_last_capture(self, shelf_number: int) -> None:
        """Finds the most recently saved picture for a tray and opens
        it in an image window. Shows a message instead if none exist yet."""

        folder = config.OUTPUT_DIR / str(shelf_number)
        images = sorted(folder.glob("finalFrame_*.jpg")) if folder.exists() else []

        if not images:
            messagebox.showinfo(
                "No image",
                f"No captured image found for tray {shelf_number}.",
                parent=self.root,
            )
            return

        self._open_image_window(shelf_number, images[-1])

    def _format_capture_info(self, shelf_number: int, image_path: Path) -> str:
        """Builds a human-readable "Tray N - taken on DD-MM-YYYY at
        HH:MM:SS" string from the timestamp encoded in the filename."""
        timestamp_str = image_path.stem.replace("finalFrame_", "")
        try:
            timestamp = datetime.strptime(timestamp_str, config.TIMESTAMP_FORMAT)
            formatted = timestamp.strftime("%d-%m-%Y at %H:%M:%S")
        except ValueError:
            formatted = timestamp_str  # fallback, falls das Format mal nicht passt

        return f"Tray {shelf_number} - taken on {formatted}"

    def _open_image_window(self, shelf_number: int, image_path: Path) -> None:
        """Opens (or reuses, if already open) a window showing the given
        image, with tray number and capture time shown below it."""

        pil_image = Image.open(image_path)
        pil_image.thumbnail((1200, 900))  # fit window, keep aspect ratio
        self._image_photo = ImageTk.PhotoImage(pil_image)

        info_text = self._format_capture_info(shelf_number, image_path)

        if self._image_window is not None and self._image_window.winfo_exists():
            self._image_window.title(f"Tray {shelf_number}")
            self._image_label.configure(image=self._image_photo)
            self._image_info_var.set(info_text)
            self._image_window.lift()
            self._image_window.focus_force()
            return

        self._image_window = tk.Toplevel(self.root)
        self._image_window.title(f"Tray {shelf_number}")

        self._image_label = ttk.Label(self._image_window, image=self._image_photo)
        self._image_label.pack(padx=10, pady=(10, 0))

        self._image_info_var = tk.StringVar(value=info_text)
        info_bar = ttk.Label(self._image_window, textvariable=self._image_info_var, font=("Arial", 12))
        info_bar.pack(padx=10, pady=10)

        def _on_close() -> None:
            self._image_window.destroy()
            self._image_window = None
            self._image_label = None

        self._image_window.protocol("WM_DELETE_WINDOW", _on_close)


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    app.log_event("GUI started (test mode)")
    root.mainloop()