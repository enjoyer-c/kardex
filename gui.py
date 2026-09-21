"""
GUI Layout:

Section 1 - Row 1: (spacer) - Status (center) - (spacer) - Camera Setup /
    Manual Capture / History buttons
Section 1 - Row 2: Search bar, wider, centered

Section 2: Resizable split (ttk.Panedwindow, vertical) between:
    - Top pane: Table listing all tray's (1-50), scrollable
    - Bottom pane: Live image preview of the selected tray's last
      capture - updates automatically on click OR arrow-key
      navigation (Treeview's <<TreeviewSelect>> event covers both)

*functions:
    - History open seperate popup-Window
    - Right-clicking on a row allows to rename descriptions
    - search inventory
    - selecting a row (click or arrow keys) live-loads its last
      captured image in the preview pane below the table
    - manual capture: opens a small popup to enter a tray number and
      trigger a capture without waiting for the automatic door-sensor
      flow (meant as a fallback, e.g. if the door magnet/sensor fails)
    - camera setup: opens a popup showing a snapshot from each
      connected USB camera so the user can visually identify them and
      set their left-to-right capture order - needed because by-id
      device paths alone don't say which physical camera is which,
      and the order isn't stable if cameras get unplugged/swapped
"""

from __future__ import annotations
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageTk
import cv2
import subprocess
import sys

import config
import inventory
import logging
import camera_setup


STATUS_COLORS = {
    "IDLE": ("#e8f5e9", "#2e7d32"),
    "OUTBOUND": ("#fff3e0", "#e65100"),
    "AT_DELIVERY_POSITION": ("#e3f2fd", "#1565c0"),
    "CAPTURING_AND_STITCHING": ("#e3f2fd", "#1565c0"),
    "RETURNING": ("#fff3e0", "#e65100"),
}

# How long to wait after the selection last changed before actually
# loading the image - avoids loading/decoding a JPEG on every single
# intermediate row while scrolling quickly through the table with the
# arrow keys held down.
PREVIEW_DEBOUNCE_MS = 150


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Kardex Shuttle Logistics System - Test")
        self.root.geometry("1920x1080")

        self._log_entries: list[str] = []
        self._history_window: Optional[tk.Toplevel] = None
        self._history_listbox: Optional[tk.Listbox] = None
        self._manual_capture_window: Optional[tk.Toplevel] = None
        self._manual_tray_var: Optional[tk.StringVar] = None
        self._search_after_id: Optional[str] = None
        self._preview_after_id: Optional[str] = None
        self._preview_photo = None  # keep a reference, or Tk garbage-collects it

        # Camera Setup popup state
        self._camera_setup_window: Optional[tk.Toplevel] = None
        self._camera_setup_order: list[str] = []
        self._camera_setup_photos: dict[str, ImageTk.PhotoImage] = {}
        self._camera_setup_slots_frame: Optional[ttk.Frame] = None

        # set from main.py - called when the user triggers a manual capture
        self.on_manual_capture: Optional[Callable[[str], None]] = None

        self._button_icons: dict[str, ImageTk.PhotoImage] = {}
        self._load_button_icons()

        self._build_top_section()
        self._build_main_section()

        

        # Up/Down should move the table selection even when some other
        # widget in the main window has focus (e.g. the search box,
        # which doesn't use Up/Down for anything itself). The table's
        # own native Up/Down handling still applies when it itself has
        # focus - see _handle_global_arrow_key.
        self.root.bind_all("<Up>", self._handle_global_arrow_key)
        self.root.bind_all("<Down>", self._handle_global_arrow_key)

    # --- Section 1: Status / Camera Setup / Manual Capture / History
    #     (row 0), Search (row 1) - shared grid so both rows center on
    #     the same point. Column 2 stays a pure EMPTY spacer (mirrors
    #     column 0) - buttons live in columns 3-5, never in 0-2, so the
    #     status/search centering trick keeps working. -----------------

    def _build_top_section(self) -> None:
        top_frame = ttk.Frame(self.root)
        top_frame.pack(padx=20, pady=(20, 15), fill="x")
        top_frame.grid_columnconfigure(0, weight=1)  # left spacer
        top_frame.grid_columnconfigure(1, weight=0)  # status / search
        top_frame.grid_columnconfigure(2, weight=1)  # right spacer (kept empty!)
        top_frame.grid_columnconfigure(3, weight=0)  # manual capture button
        top_frame.grid_columnconfigure(4, weight=0)  # history button
        top_frame.grid_columnconfigure(5, weight=0)  # camera setup button

        hint_frame = tk.Frame(top_frame, bg="white", padx=10, pady=6)
        hint_frame.grid(row=0, column=0, rowspan=2, sticky="w")

        tk.Label(
            hint_frame, text="• Click or use arrow keys: preview image below",
            font=("Arial", 10), fg="black", bg="white",
        ).pack(anchor="w")
        tk.Label(
            hint_frame, text="• Right-click: rename description",
            font=("Arial", 10), fg="black", bg="white",
        ).pack(anchor="w")
        tk.Label(
            hint_frame, text="• Camera Setup takes a few seconds to load",
            font=("Arial", 10), fg="black", bg="white",
        ).pack(anchor="w")


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

        style = ttk.Style()
        style.configure("Big.TButton", font=("Arial", 13), padding=(12, 8))

        # Manual Capture and History are everyday-use buttons (bigger,
        # prominent). Camera Setup is only for the rare troubleshooting
        # case (cameras swapped/unplugged) - kept smaller, plain style,
        # and placed furthest to the right, away from Manual Capture,
        # so the two aren't easy to mix up on a quick click.
        manual_button = ttk.Button(
            top_frame, text="Manual Capture", image=self._button_icons.get("manual_capture"),
            compound="left", command=self._open_manual_capture_window, style="Big.TButton"
        )
        manual_button.grid(row=0, column=3, padx=(0, 10), sticky="e")

        stacked_button_width = 14
        
        history_button = ttk.Button(
            top_frame, text="History", image=self._button_icons.get("history"),
            compound="left", command=self._open_history_window, style="Big.TButton",
            width=stacked_button_width,
        )
        history_button.grid(row=0, column=4, sticky="e")

        # Camera Setup sits on its own row, right below History - same
        # size as the other buttons, but visually set apart by position
        # rather than by being shrunk down, since a smaller button next
        # to two big ones looked unbalanced.

        camera_setup_button = ttk.Button(
            top_frame, text="Camera Setup", image=self._button_icons.get("camera_setup"),
            compound="left", command=self._open_camera_setup_window, style="Big.TButton",
            width=stacked_button_width,
        )
        camera_setup_button.grid(row=1, column=4, pady=(12, 0), sticky="e")

        # Search - placed in the same column (1) as the status label, so
        # it's centered on exactly the same point, unaffected by the
        # buttons sitting further right
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
        # Debounce: Tabelle nicht bei jedem einzelnen Tastendruck neu
        # aufbauen, sondern erst 300ms nachdem zuletzt getippt wurde -
        # verhindert bis zu 50 Dateisystem-Zugriffe pro Tastenanschlag
        if self._search_after_id is not None:
            self.root.after_cancel(self._search_after_id)

        self._search_after_id = self.root.after(300, self._apply_search)

    def _apply_search(self) -> None:
        self._search_after_id = None
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

        ttk.Button(
            self._manual_capture_window, text="Take a Picture", command=self._handle_manual_capture
        ).pack(pady=15)

        # Bound to the whole window (not just the entry) - focus_set()
        # on a freshly created Toplevel isn't always reliable before the
        # window is fully mapped, so binding only to the entry can miss
        # the first Enter press
        self._manual_capture_window.bind("<Return>", lambda event: self._handle_manual_capture())

        def _on_close() -> None:
            self._manual_capture_window.destroy()
            self._manual_capture_window = None
            self._manual_tray_var = None
            self.tray_table.focus_set()

        self._manual_capture_window.protocol("WM_DELETE_WINDOW", _on_close)
        self._manual_capture_window.after(50, entry.focus_force)

    def _handle_manual_capture(self) -> None:
        tray_number = self._manual_tray_var.get().strip() if self._manual_tray_var else ""
        if not tray_number:
            messagebox.showwarning("Input missing", "Please enter the tray number.", parent=self._manual_capture_window)
            return

        try:
            if self.on_manual_capture:
                self.on_manual_capture(tray_number)
        except Exception as exc:
            self.log_event(f"Manual capture failed unexpectedly: {exc}", level=logging.ERROR)
        finally:
            if self._manual_capture_window is not None and self._manual_capture_window.winfo_exists():
                self._manual_capture_window.destroy()
                self._manual_capture_window = None
                self._manual_tray_var = None
            self.tray_table.focus_set()

    # --- Camera Setup (popup window) ---------------------------------------

    def _open_camera_setup_window(self) -> None:
        if self._camera_setup_window is not None and self._camera_setup_window.winfo_exists():
            self._camera_setup_window.lift()
            self._camera_setup_window.focus_force()
            return

        devices = camera_setup.discover_cameras()
        if not devices:
            messagebox.showinfo("Camera Setup", "No cameras found.", parent=self.root)
            return

        # Start from the currently saved order if it still matches what's
        # connected, otherwise just use discovery order as a starting point
        saved_order = camera_setup.load_camera_order()
        if saved_order and set(saved_order) == set(devices):
            self._camera_setup_order = list(saved_order)
        else:
            self._camera_setup_order = list(devices)

        self._camera_setup_photos = {}

        self._camera_setup_window = tk.Toplevel(self.root)
        self._camera_setup_window.title("Camera Setup")
        self._camera_setup_window.resizable(False, False)

        ttk.Label(
            self._camera_setup_window,
            text="Identify each camera by its picture, then use the arrows to set left-to-right order.",
            font=("Arial", 11),
        ).pack(padx=15, pady=(15, 10))

        self._camera_setup_slots_frame = ttk.Frame(self._camera_setup_window)
        self._camera_setup_slots_frame.pack(padx=15, pady=(0, 10))

        button_frame = ttk.Frame(self._camera_setup_window)
        button_frame.pack(pady=(0, 15))
        ttk.Button(button_frame, text="Save Order", command=self._save_camera_setup_order).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Cancel", command=self._close_camera_setup_window).pack(side="left", padx=5)

        # Ribbon cam (QR scanner) needs a real live view for fine focus/
        # position adjustment. Opens as a separate process.
        ttk.Button(
            self._camera_setup_window, text="Live: Ribbon Cam (QR Focus)",
            command=self._launch_ribbon_cam_preview,
        ).pack(pady=(0, 15))

        def _on_close() -> None:
            self._close_camera_setup_window()

        self._camera_setup_window.protocol("WM_DELETE_WINDOW", _on_close)

        self._render_camera_setup_slots()
        for device in self._camera_setup_order:
            self._refresh_camera_setup_slot(device)

    def _close_camera_setup_window(self) -> None:
        if self._camera_setup_window is not None and self._camera_setup_window.winfo_exists():
            self._camera_setup_window.destroy()
        self._camera_setup_window = None
        self._camera_setup_slots_frame = None
        self.tray_table.focus_set()

    def _render_camera_setup_slots(self) -> None:
        """Rebuilds the row of camera slots from self._camera_setup_order -
        called after any reorder, so the on-screen layout matches."""
        for child in self._camera_setup_slots_frame.winfo_children():
            child.destroy()

        for index, device in enumerate(self._camera_setup_order):
            slot = ttk.Frame(self._camera_setup_slots_frame, relief="groove", borderwidth=1, padding=10)
            slot.grid(row=0, column=index, padx=5)

            ttk.Label(slot, text=f"Position {index + 1}", font=("Arial", 11, "bold")).pack()
            ttk.Label(slot, text=camera_setup.short_name(device), font=("Arial", 8), wraplength=200).pack(pady=(0, 5))

            image_label = ttk.Label(slot)
            image_label.pack()
            photo = self._camera_setup_photos.get(device)
            if photo is not None:
                image_label.configure(image=photo)
            else:
                image_label.configure(text="(no preview yet)")

            ttk.Button(
                slot, text="Refresh", command=lambda d=device: self._refresh_camera_setup_slot(d)
            ).pack(pady=(5, 5))

            nav_frame = ttk.Frame(slot)
            nav_frame.pack()
            left_button = ttk.Button(
                nav_frame, text="\u25c0", width=3,
                command=lambda i=index: self._move_camera_setup_slot(i, -1),
            )
            left_button.pack(side="left")
            if index == 0:
                left_button.state(["disabled"])

            right_button = ttk.Button(
                nav_frame, text="\u25b6", width=3,
                command=lambda i=index: self._move_camera_setup_slot(i, 1),
            )
            right_button.pack(side="left")
            if index == len(self._camera_setup_order) - 1:
                right_button.state(["disabled"])

    def _refresh_camera_setup_slot(self, device: str) -> None:
        frame = camera_setup.capture_snapshot(device)
        if frame is None:
            messagebox.showwarning(
                "Camera Setup", f"Could not read from:\n{camera_setup.short_name(device)}",
                parent=self._camera_setup_window,
            )
            return

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb)
        pil_image.thumbnail((280, 210))
        self._camera_setup_photos[device] = ImageTk.PhotoImage(pil_image)
        self._render_camera_setup_slots()

    def _move_camera_setup_slot(self, index: int, direction: int) -> None:
        new_index = index + direction
        if not (0 <= new_index < len(self._camera_setup_order)):
            return
        order = self._camera_setup_order
        order[index], order[new_index] = order[new_index], order[index]
        self._render_camera_setup_slots()

    def _save_camera_setup_order(self) -> None:
        camera_setup.save_camera_order(self._camera_setup_order)
        config.USB_CAMERA_DEVICES = list(self._camera_setup_order)
        self.log_event("Camera order updated via Camera Setup")
        self._close_camera_setup_window()

    def _launch_ribbon_cam_preview(self) -> None:
        """Starts Setup_RibbonCAM.py as a separate process - a live
        cv2.imshow window outside of Tkinter, for fine-tuning the
        ribbon camera's focus/position while watching QR detection in
        real time."""
        script_path = Path(__file__).resolve().parent / "Setup_RibbonCAM.py"
        if not script_path.exists():
            messagebox.showwarning(
                "Camera Setup", f"Script not found:\n{script_path}", parent=self._camera_setup_window
            )
            return

        messagebox.showinfo(
            "Camera Setup",
            "Opens in a separate window. Press 'q' in that window when done.\n"
            "Don't run this while a tray is currently being captured.",
            parent=self._camera_setup_window,
        )
        subprocess.Popen([sys.executable, str(script_path)])

    # --- History (separate pop-up window) --------------------------------

    def _open_history_window(self) -> None:
        if self._history_window is not None and self._history_window.winfo_exists():
            self._history_window.lift()
            self._history_window.focus_force()
            return

        self._history_window = tk.Toplevel(self.root)
        self._history_window.title("History")
        self._history_window.geometry("600x400")
        self._history_window.lift()
        self._history_window.attributes("-topmost", True)
        self._history_window.after(200, lambda: self._history_window.attributes("-topmost", False))

        self._history_listbox = tk.Listbox(self._history_window, font=("Consolas", 10))
        self._history_listbox.pack(padx=10, pady=10, fill="both", expand=True)

        for entry in self._log_entries:
            self._history_listbox.insert(tk.END, entry)
        self._history_listbox.see(tk.END)

        def _on_close() -> None:
            self._history_window.destroy()
            self._history_window = None
            self._history_listbox = None
            self.tray_table.focus_set()

        self._history_window.protocol("WM_DELETE_WINDOW", _on_close)

    def log_event(self, text: str, level: int = logging.INFO) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level_name = logging.getLevelName(level)
        entry = f"{timestamp} [{level_name}] {text}"
        self._log_entries.append(entry)
        if len(self._log_entries) > 500:
            del self._log_entries[:-500]

        logging.log(level, text)

        if self._history_listbox is not None and self._history_window is not None and self._history_window.winfo_exists():
            self._history_listbox.insert(tk.END, entry)
            self._history_listbox.see(tk.END)

    def load_history_from_log_file(self, log_file: Path, max_lines: int = 100) -> None:
        """Pre-loads the History list with the tail of the persisted log
        file, so it isn't empty right after a restart (e.g. after a crash
        or power loss)."""
        if not log_file.exists():
            return

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return

        for line in lines[-max_lines:]:
            line = line.rstrip("\n")
            if line:
                self._log_entries.append(line)

    # --- Section 2: Resizable split - table (top) / image preview (bottom) --

    def _build_main_section(self) -> None:
        paned = ttk.Panedwindow(self.root, orient=tk.VERTICAL)
        paned.pack(padx=20, pady=(0, 20), fill="both", expand=True)

        table_frame = ttk.Frame(paned)
        preview_frame = ttk.Frame(paned)

        paned.add(table_frame, weight=1)
        paned.add(preview_frame, weight=3)

        # Preview pane must exist BEFORE the table is built - building
        # the table ends with _populate_tray_table(), which calls
        # _clear_preview(), which references the preview widgets
        self._build_preview_pane(preview_frame)
        self._build_tray_table(table_frame)

    # --- Tray table ----------------------------------------------------

    def _build_tray_table(self, table_frame: ttk.Frame) -> None:
        style = ttk.Style()
        style.configure("Treeview", font=("Arial", 14), rowheight=32)
        style.configure("Treeview.Heading", font=("Arial", 14, "bold"))

        columns = ("tray", "description", "last_capture")
        self.tray_table = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.tray_table.heading("tray", text="Tray Nr.")
        self.tray_table.heading("description", text="Description")
        self.tray_table.heading("last_capture", text="Last Capture")
        self.tray_table.column("tray", width=100, stretch=False, anchor="center")
        self.tray_table.column("description", width=900, anchor="w")
        self.tray_table.column("last_capture", width=140, stretch=False, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tray_table.yview)
        self.tray_table.configure(yscrollcommand=scrollbar.set)

        self.tray_table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Right-clicking opens the context menu
        self.tray_table.bind("<Button-3>", self._handle_right_click)
        # Selecting a row - by click OR arrow keys, <<TreeviewSelect>>
        # covers both - live-loads that tray's last image below
        self.tray_table.bind("<<TreeviewSelect>>", self._handle_tray_selected)

        self._populate_tray_table()
        self.tray_table.focus_set()

    def _get_last_capture_date(self, tray_number: int) -> str:
        folder = config.OUTPUT_DIR / str(tray_number)
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
            rows = list(enumerate(inventory.read_all(), start=config.TRAY_LOWER_LIMIT))

        for tray_number, description in rows:
            last_opened = self._get_last_capture_date(tray_number)
            self.tray_table.insert("", "end", values=(tray_number, description, last_opened))

        # Table content changed - whatever was previewed no longer
        # necessarily matches a visible/selected row
        self._clear_preview()

    # --- Rename with right mouse button ----------------------------------------

    def _handle_right_click(self, event) -> None:
        """Shows a context menu with a Rename option for the row under
        the cursor. Closes automatically on any click outside the menu."""

        row_id = self.tray_table.identify_row(event.y)
        if not row_id:
            return

        self.tray_table.selection_set(row_id)

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Rename", command=lambda: self._rename_row(row_id))

        def _close_menu(_event=None) -> None:
            menu.unpost()

        menu.bind("<FocusOut>", _close_menu)

        try:
            menu.tk_popup(event.x_root, event.y_root)
            menu.focus_set()
        finally:
            menu.grab_release()

    def _rename_row(self, row_id: str) -> None:
        """Prompts for a new description, confirms with the user, then
        writes it to Inventory.txt and updates the table in place."""

        tray_number_str, current_description, last_opened = self.tray_table.item(row_id, "values")

        new_description = simpledialog.askstring(
            "Rename",
            f"New description for tray {tray_number_str}:",
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
            f"Tray {tray_number_str} rename?\n\n"
            f"Old: {current_description}\n"
            f"New: {new_description}",
            parent=self.root,
        )
        if not confirmed:
            return

        tray_number = int(tray_number_str)
        inventory.update_description(tray_number, new_description)

        # Update the table directly instead of reloading it entirely
        self.tray_table.item(row_id, values=(tray_number, new_description, last_opened))
        self.log_event(f"Tray {tray_number} renamed: {new_description}")
        self.tray_table.focus_set()

    # --- Live image preview (selection-driven) -----------------------------

    def _build_preview_pane(self, preview_frame: ttk.Frame) -> None:
        self._preview_info_var = tk.StringVar(value="Select a tray to preview its last captured image.")
        info_bar = ttk.Label(preview_frame, textvariable=self._preview_info_var, font=("Arial", 12, "bold"))
        info_bar.pack(pady=(5, 10))

        self._preview_label = ttk.Label(preview_frame)
        self._preview_label.pack(expand=True)

    def _handle_global_arrow_key(self, event) -> Optional[str]:
        """Lets Up/Down move the table selection even when focus is
        elsewhere (e.g. the search box) - the table itself already
        handles Up/Down natively when it has focus, so this only takes
        over when some OTHER widget in the main window has focus.
        Popup windows (History, Manual Capture, Camera Setup) are
        excluded, so their own keyboard handling isn't hijacked.
        """
        focused = self.root.focus_get()
        if focused is None:
            return None
        if focused.winfo_toplevel() != self.root:
            return None  # a popup is focused - don't interfere
        if focused is self.tray_table:
            return None  # table already handles its own Up/Down natively

        children = self.tray_table.get_children()
        if not children:
            return None

        current = self.tray_table.selection()
        index = children.index(current[0]) if current else -1

        if event.keysym == "Down":
            index = min(index + 1, len(children) - 1)
        else:  # "Up"
            index = max(index - 1, 0)

        next_id = children[index]
        self.tray_table.selection_set(next_id)
        self.tray_table.see(next_id)
        return "break"

    def _handle_tray_selected(self, event=None) -> None:
        # Debounce: while scrolling fast through the table with the
        # arrow keys held down, don't decode/load a JPEG for every
        # single intermediate row - only for the one the user actually
        # settles on
        if self._preview_after_id is not None:
            self.root.after_cancel(self._preview_after_id)

        self._preview_after_id = self.root.after(PREVIEW_DEBOUNCE_MS, self._apply_preview_selection)

    def _apply_preview_selection(self) -> None:
        self._preview_after_id = None

        selection = self.tray_table.selection()
        if not selection:
            self._clear_preview()
            return

        tray_number_str, _, _ = self.tray_table.item(selection[0], "values")
        self._load_preview_image(int(tray_number_str))

    def _clear_preview(self) -> None:
        self._preview_photo = None
        self._preview_label.configure(image="")
        self._preview_info_var.set("Select a tray to preview its last captured image.")

    def _load_preview_image(self, tray_number: int) -> None:
        folder = config.OUTPUT_DIR / str(tray_number)
        images = sorted(folder.glob("finalFrame_*.jpg")) if folder.exists() else []

        if not images:
            self._preview_photo = None
            self._preview_label.configure(image="")
            self._preview_info_var.set(f"Tray {tray_number} - no captured image yet.")
            return

        image_path = images[-1]

        try:
            pil_image = Image.open(image_path)
            pil_image.thumbnail((1400, 900))  
            self._preview_photo = ImageTk.PhotoImage(pil_image)
        except Exception as exc:
            self._preview_photo = None
            self._preview_label.configure(image="")
            self._preview_info_var.set(f"Tray {tray_number} - could not load image ({exc}).")
            return

        self._preview_label.configure(image=self._preview_photo)
        self._preview_info_var.set(self._format_capture_info(tray_number, image_path))

    def _format_capture_info(self, tray_number: int, image_path: Path) -> str:
        """Builds a human-readable "Tray N - taken on DD-MM-YYYY at
        HH:MM:SS" string from the timestamp encoded in the filename."""
        timestamp_str = image_path.stem.replace("finalFrame_", "")
        try:
            timestamp = datetime.strptime(timestamp_str, config.TIMESTAMP_FORMAT)
            formatted = timestamp.strftime("%d-%m-%Y at %H:%M:%S")
        except ValueError:
            formatted = timestamp_str 

        return f"Tray {tray_number} - taken on {formatted}"

    def _load_button_icons(self) -> None:
        icons_dir = Path(__file__).resolve().parent / "icons"
        names = ["history", "camera_setup", "manual_capture"]
        for name in names:
            path = icons_dir / f"{name}.png"
            if path.exists():
                self._button_icons[name] = ImageTk.PhotoImage(Image.open(path))



if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    app.log_event("GUI started (test mode)")
    root.mainloop()