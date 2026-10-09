"""
GUI Layout:
Section 1: Hints (left) - Search bar (center) - error banner (only if
    there's a problem) - Manual Capture / History / Camera Setup buttons

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
      set their left-to-right capture order - needed because a device
      path alone doesn't say which physical camera is which, and the
      order isn't stable if cameras get unplugged/swapped. Also has a
      button to launch a live ribbon-cam preview (separate process,
      for QR focus/positioning)
"""

from __future__ import annotations
from collections import deque
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageTk
import cv2
import subprocess
import sys
import threading

import config
import inventory
import logging
import camera_setup


class _RenameDialog(simpledialog.Dialog):
    """Like simpledialog.askstring, but with a much wider entry field -
    the standard dialog's field is too short for longer descriptions."""

    def __init__(self, parent, title: str, prompt: str, initial_value: str):
        # Must be set BEFORE super().__init__ - that already builds and shows the dialog
        self._prompt = prompt
        self._initial_value = initial_value
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text=self._prompt, font=("Arial", 11)).pack(anchor="w", padx=5, pady=(5, 3))
        self._entry = ttk.Entry(master, width=80, font=("Arial", 12))
        self._entry.pack(fill="x", padx=5, pady=(0, 5))
        self._entry.insert(0, self._initial_value)
        self._entry.select_range(0, "end")   # text selected -> typing replaces it, arrow keys keep it
        return self._entry                   # this widget gets the focus

    def apply(self):
        # Only called on OK / Enter - on Cancel / Escape, self.result stays None
        self.result = self._entry.get()


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Kardex Content Tracker")
        self.root.geometry("1920x1080")

        self._log_entries: list[str] = []
        self._errors: dict[str, str] = {}   # persistent problems shown in the red banner (key -> short text)
        self._history_window: Optional[tk.Toplevel] = None
        self._history_listbox: Optional[tk.Listbox] = None
        self._manual_capture_window: Optional[tk.Toplevel] = None
        self._manual_tray_var: Optional[tk.StringVar] = None
        self._search_after_id: Optional[str] = None
        self._preview_after_id: Optional[str] = None
        self._preview_photo = None

        # Image preview: the full-resolution image stays in memory - the preview is scaled from it
        # to fit the pane, and the magnifier cuts its details out of it
        self._preview_full: Optional[Image.Image] = None
        self._preview_scale = 1.0                       # displayed size / original size
        self._preview_origin: tuple[int, int] = (0, 0)  # top-left corner of the image on the canvas
        self._preview_size: tuple[int, int] = (0, 0)    # displayed width/height
        self._preview_resize_after_id: Optional[str] = None

        # Magnifier (hold left mouse button on the preview)
        self._lens_photo = None
        self._lens_pos: Optional[tuple[int, int]] = None
        self._lens_after_id: Optional[str] = None

        # Camera Setup popup state
        self._camera_setup_window: Optional[tk.Toplevel] = None
        self._camera_setup_order: list[str] = []
        self._camera_setup_photos: dict[str, ImageTk.PhotoImage] = {}
        self._camera_setup_slots_frame: Optional[ttk.Frame] = None
        self._camera_setup_status_var: Optional[tk.StringVar] = None
        self._panorama_mode_var: Optional[tk.StringVar] = None
        self._camera_setup_save_button: Optional[ttk.Button] = None
        self._camera_discovery_running = False
        self._camera_setup_image_labels: dict[str, ttk.Label] = {}
        self._camera_preview_after_id: Optional[str] = None
        self._camera_preview_fetch_running = False
        self._ribbon_cam_process: Optional[subprocess.Popen] = None

        # set from main.py - called when the user triggers a manual capture
        self.on_manual_capture: Optional[Callable[[str], None]] = None

        # TEMP door test: set from main.py - simulates a door open/close
        self.on_simulate_door: Optional[Callable[[], None]] = None

        self._button_icons: dict[str, ImageTk.PhotoImage] = {}
        self._load_button_icons()

        self._window_icon: Optional[tk.PhotoImage] = None
        self._load_window_icon()

        self._build_top_section()
        self._build_main_section()

        self.root.bind_all("<Up>", self._handle_global_arrow_key)
        self.root.bind_all("<Down>", self._handle_global_arrow_key)

    def _load_window_icon(self) -> None:
        icon_path = Path(__file__).resolve().parent / "icons" / "app_icon.png"
        if icon_path.exists():
            self._window_icon = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, self._window_icon)

    def _build_top_section(self) -> None:
        top_frame = ttk.Frame(self.root)
        top_frame.pack(padx=20, pady=(20, 15), fill="x")
        top_frame.grid_columnconfigure(0, weight=1)  # left spacer
        top_frame.grid_columnconfigure(1, weight=0)  # search
        top_frame.grid_columnconfigure(2, weight=1)  # right spacer
        top_frame.grid_columnconfigure(3, weight=0)  # manual capture button
        top_frame.grid_columnconfigure(4, weight=0)  # history / camera setup button

        hint_frame = tk.Frame(top_frame, bg="white", padx=10, pady=6)
        hint_frame.grid(row=0, column=0, rowspan=2, sticky="w")

        tk.Label(
            hint_frame, text="• Click / Arrows: Preview image",
            font=("Arial", 11), fg="black", bg="white",
        ).pack(anchor="w")
        tk.Label(
            hint_frame, text="• Right-click: Rename description",
            font=("Arial", 11), fg="black", bg="white",
        ).pack(anchor="w")
        tk.Label(
            hint_frame, text="• Hold left-click on image: Magnify", 
            font=("Arial", 11), fg="black", bg="white",
        ).pack(anchor="w")


        # Red error banner between the search and the buttons (column 2, over both rows).
        # Hidden (grid_remove) as long as there's no persistent problem - see set_error / clear_error.
        self.error_label = tk.Label(
            top_frame, text="", font=("Arial", 13, "bold"),
            bg="#c62828", fg="white", padx=15, pady=8, justify="left", wraplength=380,
        )
        self.error_label.grid(row=0, column=2, rowspan=2)
        self.error_label.grid_remove()

        style = ttk.Style()
        style.configure("Big.TButton", font=("Arial", 13), padding=(12, 8))

        manual_button = ttk.Button(
            top_frame, text="Manual Capture", image=self._button_icons.get("manual_capture"),
            compound="left", command=self._open_manual_capture_window, style="Big.TButton"
        )
        manual_button.grid(row=0, column=3, padx=(0, 10), sticky="e")

        # --- TEMP door test (remove together with config.DOOR_TEST_BUTTON) ---
        if config.DOOR_TEST_BUTTON:
            ttk.Button(
                top_frame, text="TEST: Toggle Door", command=self._handle_simulate_door,
                style="Big.TButton",
            ).grid(row=1, column=3, padx=(0, 10), pady=(12, 0), sticky="e")

        stacked_button_width = 14
        
        history_button = ttk.Button(
            top_frame, text="History", image=self._button_icons.get("history"),
            compound="left", command=self._open_history_window, style="Big.TButton",
            width=stacked_button_width,
        )
        history_button.grid(row=0, column=4, sticky="e")


        camera_setup_button = ttk.Button(
            top_frame, text="Camera Setup", image=self._button_icons.get("camera_setup"),
            compound="left", command=self._open_camera_setup_window, style="Big.TButton",
            width=stacked_button_width,
        )
        camera_setup_button.grid(row=1, column=4, pady=(12, 0), sticky="e")

        search_frame = ttk.Frame(top_frame)
        search_frame.grid(row=0, column=1, rowspan=2)

        ttk.Label(search_frame, text="search:", font=("Arial", 13)).pack(side="left", padx=(0, 8))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=50, font=("Arial", 13))
        search_entry.pack(side="left")
        search_entry.bind("<KeyRelease>", self._handle_search_change)

        # Invisible mirror of the "search:" label on the right - without
        # this, the entry box visually drifts right (the label only adds
        # width on the left), so it looks off-center even though this
        # whole frame is centered in the grid cell
        bg_color = style.lookup("TFrame", "background") or self.root.cget("bg")
        tk.Label(
            search_frame, text="search:", font=("Arial", 13), fg=bg_color, bg=bg_color
        ).pack(side="left", padx=(8, 0))


    # --- Error banner -----------------------------------------------------------

    def set_error(self, key: str, text: str) -> None:
        """Shows a persistent problem in the red banner (e.g. door sensor missing). The key identifies the problem,
        so it can be removed again with clear_error(key) once it's solved. Several problems are shown line by line.
        Only for problems the user must notice - details belong in the History."""
        self._errors[key] = text
        self._refresh_error_banner()

    def clear_error(self, key: str) -> None:
        if self._errors.pop(key, None) is not None:
            self._refresh_error_banner()

    def _refresh_error_banner(self) -> None:
        if self._errors:
            self.error_label.configure(text="\n".join(f"\u26a0 {text}" for text in self._errors.values()))
            self.error_label.grid()   # grid() without options restores the position from above
        else:
            self.error_label.grid_remove()

    def _handle_search_change(self, event=None) -> None:
        # Debounce: don't rebuild the table on every single keystroke, only 300ms after the user last typed
        if self._search_after_id is not None:
            self.root.after_cancel(self._search_after_id)

        self._search_after_id = self.root.after(config.SEARCH_DEBOUNCE_MS, self._apply_search)

    def _apply_search(self) -> None:
        self._search_after_id = None
        query = self.search_var.get()
        self._populate_tray_table(query)

        children = self.tray_table.get_children()
        if children:
            self.tray_table.see(children[0])
            self.tray_table.selection_set(children[0])

    # --- TEMP door test (remove together with config.DOOR_TEST_BUTTON) ---
    def _handle_simulate_door(self) -> None:
        if self.on_simulate_door:
            self.on_simulate_door()

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

        # Bound to the whole window - focus_set() on a freshly created Toplevel isn't always reliable before the window is fully mapped, so binding only to the entry can miss the first Enter press
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

        # Only plain numbers within the tray limits - "01" becomes "1",
        # letters/decimals/out-of-range get rejected. The popup stays
        # open so the user can correct the input.
        normalized = inventory.normalize_tray_number(tray_number)
        if normalized is None:
            messagebox.showwarning(
                "Invalid tray number",
                f"Please enter a number from {config.TRAY_LOWER_LIMIT} to {config.TRAY_UPPER_LIMIT}.",
                parent=self._manual_capture_window,
            )
            return
        tray_number = normalized

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

        # Always allowed, in every state - a setup is usually done WITH the
        # tray out, to check that the whole tray is in the picture. Collisions
        # with a running capture are prevented by the camera lock instead.

        # Start from the saved order - discovery results get merged into it
        # (cameras still connected keep their position, new ones are appended)
        self._camera_setup_order = camera_setup.load_camera_order()
        self._camera_setup_photos = {}

        # The window opens IMMEDIATELY - the camera search runs in the
        # background and fills in the slots once it's done
        self._camera_setup_window = tk.Toplevel(self.root)
        self._camera_setup_window.title("Camera Setup")
        self._camera_setup_window.resizable(False, False)

        # Layout: everything static (text, buttons, status) sits ABOVE the
        # camera slots and is left-aligned (anchor="w"). When the cameras
        # show up, the window only grows downwards/to the right - so none of
        # these widgets ever has to move. (On the Pi, widgets that got moved
        # by a window resize sometimes weren't redrawn until hovered.)
        ttk.Label(
            self._camera_setup_window,
            text="Identify each camera by its picture, then use the arrows to set left-to-right order.",
            font=("Arial", 11),
        ).pack(anchor="w", padx=15, pady=(15, 10))

        button_frame = ttk.Frame(self._camera_setup_window)
        button_frame.pack(anchor="w", padx=15, pady=(0, 10))
        self._camera_setup_save_button = ttk.Button(
            button_frame, text="Save Order", command=self._save_camera_setup_order
        )
        self._camera_setup_save_button.pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Cancel", command=self._close_camera_setup_window).pack(side="left", padx=5)

        # Ribbon cam (QR scanner) needs a real live view for fine focus/position adjustment. Opens as a separate process.
        ttk.Button(
            button_frame, text="Live: Ribbon Cam (QR Focus)",
            command=self._launch_ribbon_cam_preview,
        ).pack(side="left", padx=(25, 0))

        # Picture mode: how the camera images are combined. Applies from the next capture on, saved immediately (no "Save Order" needed).
        mode_frame = ttk.Frame(self._camera_setup_window)
        mode_frame.pack(anchor="w", padx=15, pady=(0, 10))
        ttk.Label(mode_frame, text="Picture mode:", font=("Arial", 10, "bold")).pack(side="left", padx=(0, 10))
        self._panorama_mode_var = tk.StringVar(value=camera_setup.get_panorama_mode())
        ttk.Radiobutton(
            mode_frame, text="Stitch (panorama)", value="stitch",
            variable=self._panorama_mode_var, command=self._on_panorama_mode_changed,
        ).pack(side="left", padx=(0, 10))
        ttk.Radiobutton(
            mode_frame, text="Side by side", value="side_by_side",
            variable=self._panorama_mode_var, command=self._on_panorama_mode_changed,
        ).pack(side="left")

        self._camera_setup_status_var = tk.StringVar(value="")
        ttk.Label(
            self._camera_setup_window, textvariable=self._camera_setup_status_var, font=("Arial", 10, "italic")
        ).pack(anchor="w", padx=15, pady=(0, 10))

        self._camera_setup_slots_frame = ttk.Frame(self._camera_setup_window)
        self._camera_setup_slots_frame.pack(anchor="w", padx=15, pady=(0, 15))

        self._camera_setup_window.protocol("WM_DELETE_WINDOW", self._close_camera_setup_window)

        if self._camera_discovery_running:
            # A search started from a previously closed window is still
            # running - its result will simply show up in this window
            self._camera_setup_status_var.set("Searching for cameras ...")
            self._update_camera_setup_buttons()
        else:
            self._start_camera_discovery()

    def _on_panorama_mode_changed(self) -> None:
        """Radio button clicked -> save the new picture mode right away."""
        mode = self._panorama_mode_var.get()
        try:
            camera_setup.set_panorama_mode(mode)
        except (ValueError, OSError) as exc:
            # Not saved -> show the mode that's actually active again
            self._panorama_mode_var.set(camera_setup.get_panorama_mode())
            self.log_event(f"Picture mode could not be changed: {exc}", level=logging.ERROR)
            messagebox.showerror("Camera Setup", f"Picture mode could not be saved:\n\n{exc}", parent=self._camera_setup_window)
            return

        mode_text = "stitch (panorama)" if mode == "stitch" else "side by side"
        self.log_event(f"Picture mode changed to: {mode_text}")

    def _close_camera_setup_window(self) -> None:
        if self._camera_preview_after_id is not None:
            self.root.after_cancel(self._camera_preview_after_id)
            self._camera_preview_after_id = None
        self._camera_setup_image_labels = {}
        if self._camera_setup_window is not None and self._camera_setup_window.winfo_exists():
            self._camera_setup_window.destroy()
        self._camera_setup_window = None
        self._camera_setup_slots_frame = None
        self._camera_setup_status_var = None
        self._panorama_mode_var = None
        self._camera_setup_save_button = None
        self.tray_table.focus_set()

    def _update_camera_setup_buttons(self) -> None:
        """Save is disabled while the search is running and while there's
        nothing to save (no cameras found)."""
        if self._camera_setup_save_button is not None:
            can_save = not self._camera_discovery_running and bool(self._camera_setup_order)
            self._camera_setup_save_button.state(["!disabled" if can_save else "disabled"])

    def _start_camera_discovery(self) -> None:
        """Searches for cameras and takes one preview frame from each of the permanently running
        streams. In a background thread, since a newly plugged-in camera needs a moment for its
        first frame. Runs every time the window is opened, so newly plugged-in cameras show up
        by simply reopening Camera Setup. Doesn't touch a running capture (the cameras stay open the whole time)."""
        if self._camera_discovery_running:
            return

        self._camera_discovery_running = True
        self._camera_setup_status_var.set("Searching for cameras ...")
        self._update_camera_setup_buttons()

        threading.Thread(target=self._camera_discovery_worker, daemon=True).start()

    def _camera_discovery_worker(self) -> None:
        """Runs in a background thread. ALWAYS reports back to the Tk
        main thread - otherwise _camera_discovery_running would stay True
        and the Save button disabled forever."""
        found: dict = {}
        error_message = None
        try:
            found = camera_setup.discover_cameras()
        except camera_setup.CamerasBusyError as exc:
            error_message = str(exc)
        except Exception as exc:
            logging.exception("Camera discovery crashed")
            error_message = f"Camera search failed: {exc}"

        self.root.after(0, self._on_camera_discovery_done, found, error_message)

    def _on_camera_discovery_done(self, found: dict, error_message: Optional[str]) -> None:
        self._camera_discovery_running = False

        # Window may have been closed while searching - just drop the result
        if self._camera_setup_window is None or not self._camera_setup_window.winfo_exists():
            return

        if error_message is not None:
            self._camera_setup_status_var.set(error_message)
            self._update_camera_setup_buttons()
            return

        kept = [device for device in self._camera_setup_order if device in found]
        new = [device for device in found if device not in kept]
        self._camera_setup_order = kept + new

        # The frames from the discovery's functional test ARE the previews -
        # no second capture round needed
        self._camera_setup_photos = {device: self._frame_to_photo(frame) for device, frame in found.items()}
        self._render_camera_setup_slots()

        if found:
            self._camera_setup_status_var.set(f"{len(found)} camera(s) found - pictures update live.")
            self.clear_error("usb_cameras")   # e.g. camera plugged in after startup
            self._schedule_camera_preview_refresh(config.CAMERA_SETUP_PREVIEW_REFRESH_MS)
        else:
            self._camera_setup_status_var.set("No cameras found.")
            if sys.platform.startswith("linux"):   # on Windows the search can't find cameras anyway
                self.set_error("usb_cameras", "No USB cameras found")
        self._update_camera_setup_buttons()

    # --- Camera Setup: live pictures ---------------------------------------------

    def _schedule_camera_preview_refresh(self, delay_ms: int) -> None:
        if self._camera_preview_after_id is not None:
            self.root.after_cancel(self._camera_preview_after_id)
        self._camera_preview_after_id = self.root.after(delay_ms, self._refresh_camera_setup_previews)

    def _refresh_camera_setup_previews(self) -> None:
        """Fetches the newest frame of every camera in a background thread (decoding takes a
        moment per camera), then updates the pictures in the Tk main thread."""
        self._camera_preview_after_id = None
        if self._camera_setup_window is None or not self._camera_setup_window.winfo_exists():
            return
        if self._camera_discovery_running or self._camera_preview_fetch_running:
            return  # the running search / fetch schedules the next refresh itself

        self._camera_preview_fetch_running = True
        devices = list(self._camera_setup_order)
        threading.Thread(target=self._camera_preview_worker, args=(devices,), daemon=True).start()

    def _camera_preview_worker(self, devices: list[str]) -> None:
        frames: dict = {}
        try:
            frames = camera_setup.get_preview_frames(devices)
        except Exception:
            logging.exception("Camera Setup live preview failed")
        self.root.after(0, self._on_camera_previews_fetched, frames)

    def _on_camera_previews_fetched(self, frames: dict) -> None:
        self._camera_preview_fetch_running = False
        if self._camera_setup_window is None or not self._camera_setup_window.winfo_exists():
            return

        for device, frame in frames.items():
            label = self._camera_setup_image_labels.get(device)
            if label is None or not label.winfo_exists():
                continue
            photo = self._frame_to_photo(frame)
            label.configure(image=photo, text="")
            self._camera_setup_photos[device] = photo   # keep a reference, otherwise Tk shows nothing

        if not self._camera_discovery_running:
            self._schedule_camera_preview_refresh(config.CAMERA_SETUP_PREVIEW_REFRESH_MS)

    @staticmethod
    def _frame_to_photo(frame) -> ImageTk.PhotoImage:
        """cv2 frame (BGR) -> thumbnail for the setup slots. Must run in
        the Tk main thread (PhotoImage isn't thread-safe)."""
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb)
        pil_image.thumbnail((280, 210))
        return ImageTk.PhotoImage(pil_image)

    def _render_camera_setup_slots(self) -> None:
        """Rebuilds the row of camera slots from self._camera_setup_order -
        called after any reorder, so the on-screen layout matches."""
        for child in self._camera_setup_slots_frame.winfo_children():
            child.destroy()
        self._camera_setup_image_labels = {}

        for index, device in enumerate(self._camera_setup_order):
            slot = ttk.Frame(self._camera_setup_slots_frame, relief="groove", borderwidth=1, padding=10)
            slot.grid(row=0, column=index, padx=5)

            ttk.Label(slot, text=f"Position {index + 1}", font=("Arial", 11, "bold")).pack()
            ttk.Label(slot, text=camera_setup.short_name(device), font=("Arial", 8), wraplength=200).pack(pady=(0, 5))

            image_label = ttk.Label(slot)
            image_label.pack()
            self._camera_setup_image_labels[device] = image_label
            photo = self._camera_setup_photos.get(device)
            if photo is not None:
                image_label.configure(image=photo)
            else:
                image_label.configure(text="(no preview yet)")

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

    def _move_camera_setup_slot(self, index: int, direction: int) -> None:
        new_index = index + direction
        if not (0 <= new_index < len(self._camera_setup_order)):
            return
        order = self._camera_setup_order
        order[index], order[new_index] = order[new_index], order[index]
        self._render_camera_setup_slots()

    def _save_camera_setup_order(self) -> None:
        # No need to update anything else - captures read the saved
        # order fresh via camera_setup.get_camera_devices()
        camera_setup.save_camera_order(self._camera_setup_order)
        self.log_event("Camera order updated via Camera Setup")
        self._close_camera_setup_window()

    def _launch_ribbon_cam_preview(self) -> None:
        """Starts setup_ribbon_cam.py as a separate process"""
        # Only one preview at a time - poll() is None means "still running"
        if self._ribbon_cam_process is not None and self._ribbon_cam_process.poll() is None:
            messagebox.showinfo(
                "Camera Setup", "The ribbon cam preview is already open.", parent=self._camera_setup_window
            )
            return

        script_path = Path(__file__).resolve().parent / "setup_ribbon_cam.py"
        if not script_path.exists():
            messagebox.showwarning(
                "Camera Setup", f"Script not found:\n{script_path}", parent=self._camera_setup_window
            )
            return

        messagebox.showinfo(
            "Camera Setup",
            "Opens in a separate window. Close it with 'q' or the X.\n\n"
            "While the preview is open, the ribbon cam can't scan QR codes - "
            "it is closed automatically as soon as the next QR scan starts (door closes).",
            parent=self._camera_setup_window,
        )
        self._ribbon_cam_process = subprocess.Popen([sys.executable, str(script_path)])

    def close_ribbon_cam_preview(self) -> Optional[subprocess.Popen]:
        """Called from main.py before every QR scan: the preview and the scan need the same camera.
        Only SENDS the stop signal (doesn't wait, so the GUI never freezes) and returns the process,
        so the scan thread can wait for it to really end. Returns None if no preview is running."""
        process = self._ribbon_cam_process
        if process is None or process.poll() is not None:
            return None
        process.terminate()
        self._ribbon_cam_process = None
        return process

    # --- History (separate pop-up window) --------------------------------

    def _open_history_window(self) -> None:
        if self._history_window is not None and self._history_window.winfo_exists():
            self._history_window.lift()
            self._history_window.focus_force()
            return

        self._history_window = tk.Toplevel(self.root)
        self._history_window.title("History")
        self._history_window.geometry("700x400")
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
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]   # with milliseconds, like the log file
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
                # deque with maxlen only ever keeps the last max_lines
                # lines while reading line by line - the rest of the
                # (up to 5 MB) log file is never held in memory at once
                last_lines = deque(f, maxlen=max_lines)
        except OSError:
            return

        for line in last_lines:
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
        self.tray_table.bind("<<TreeviewSelect>>", self._handle_tray_selected)
        # One context menu for the whole program, reused for every right-click
        # (creating a new one each time left old menus behind)
        self._row_menu = tk.Menu(self.root, tearoff=0)
        self._row_menu.add_command(label="Rename", command=self._rename_menu_row)
        self._menu_row_id: Optional[str] = None

        self._populate_tray_table()
        self.tray_table.focus_set()

    @staticmethod
    def _latest_capture(tray_number: int) -> Optional[Path]:
        """Path of the newest captured image of a tray, or None if the
        tray has no image yet. Filenames contain the timestamp in a
        sortable format, so sorting by name = sorting by time."""
        folder = config.OUTPUT_DIR / str(tray_number)
        images = sorted(folder.glob("finalFrame_*.jpg")) if folder.exists() else []
        return images[-1] if images else None

    @staticmethod
    def _capture_timestamp(image_path: Path) -> Optional[datetime]:
        """Reads the capture time from an image's filename
        ("finalFrame_<timestamp>.jpg"), or None if it can't be parsed."""
        timestamp_str = image_path.stem.replace("finalFrame_", "")
        try:
            return datetime.strptime(timestamp_str, config.TIMESTAMP_FORMAT)
        except ValueError:
            return None

    def _get_last_capture_date(self, tray_number: int) -> str:
        image_path = self._latest_capture(tray_number)
        if image_path is None:
            return "-"
        timestamp = self._capture_timestamp(image_path)
        return timestamp.strftime("%d.%m.%Y") if timestamp else "-"

    def _populate_tray_table(self, filter_query: str = "") -> None:
        self.tray_table.delete(*self.tray_table.get_children())

        if filter_query.strip():
            rows = inventory.search(filter_query)
        else:
            rows = list(enumerate(inventory.read_all(), start=config.TRAY_LOWER_LIMIT))

        for tray_number, description in rows:
            last_opened = self._get_last_capture_date(tray_number)
            self.tray_table.insert("", "end", values=(tray_number, description, last_opened))

        self._clear_preview()

    def update_tray_row(self, tray_number: int) -> None:
        """Refreshes just ONE tray after a new capture: its "Last Capture"
        cell, plus the preview if exactly this tray is selected right now.
        Much cheaper than _populate_tray_table (no re-reading inventory.txt,
        no scanning all 50 folders), and the user's selection, preview and
        scroll position stay as they are. Called from main.py."""
        for row_id in self.tray_table.get_children():
            tray_str, description, _last_capture = self.tray_table.item(row_id, "values")
            if int(tray_str) != tray_number:
                continue

            self.tray_table.item(
                row_id, values=(tray_str, description, self._get_last_capture_date(tray_number))
            )
            if row_id in self.tray_table.selection():
                self._load_preview_image(tray_number)
            return
        # Tray not in the table right now (filtered out by the search) -
        # nothing to do, it shows the new date once the search changes

    # --- Rename with right mouse button ----------------------------------------

    def _handle_right_click(self, event) -> None:
        """Shows the context menu with a Rename option for the row under
        the cursor. A click anywhere else closes it again."""
        row_id = self.tray_table.identify_row(event.y)
        if not row_id:
            return

        self.tray_table.selection_set(row_id)
        self._menu_row_id = row_id

        self._row_menu.unpost()   # close a menu that might still be open
        try:
            self._row_menu.tk_popup(event.x_root, event.y_root)
        finally:
            # Only on Windows: there tk_popup works differently and the grab must be released.
            # On Linux the grab is what closes the menu on a click elsewhere - releasing it
            # would keep the menu open.
            if sys.platform.startswith("win32"):
                self._row_menu.grab_release()

    def _rename_menu_row(self) -> None:
        """Called by the context menu's "Rename" entry."""
        row_id = self._menu_row_id
        self._menu_row_id = None
        # The table may have been rebuilt in the meantime (e.g. by the search) - then the row is gone
        if row_id is not None and self.tray_table.exists(row_id):
            self._rename_row(row_id)


    def _rename_row(self, row_id: str) -> None:
        """Prompts for a new description, confirms with the user, then
        writes it to Inventory.txt and updates the table in place."""

        tray_number_str, current_description, last_opened = self.tray_table.item(row_id, "values")

        dialog = _RenameDialog(
            self.root, "Rename",
            f"New description for tray {tray_number_str}:",
            current_description,
        )
        new_description = dialog.result

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
        try:
            inventory.update_description(tray_number, new_description)
        except (ValueError, OSError) as exc:
            # ValueError: tray not in inventory.txt (file too short)
            # OSError: file couldn't be written (no permission, disk
            # full, file locked, ...). Table stays unchanged, so it still
            # shows what's actually saved in the file.
            self.log_event(f"Rename of tray {tray_number} failed: {exc}", level=logging.ERROR)
            messagebox.showerror(
                "Rename failed",
                f"Tray {tray_number} could not be renamed:\n\n{exc}",
                parent=self.root,
            )
            self.tray_table.focus_set()
            return

        # Update the table directly instead of reloading it entirely
        self.tray_table.item(row_id, values=(tray_number, new_description, last_opened))
        self.log_event(f"Tray {tray_number} renamed: {new_description}")
        self.tray_table.focus_set()

    # --- Live image preview (selection-driven) -----------------------------

    def _build_preview_pane(self, preview_frame: ttk.Frame) -> None:
        self._preview_info_var = tk.StringVar(value="Select a tray to preview its last captured image.")
        info_bar = ttk.Label(preview_frame, textvariable=self._preview_info_var, font=("Arial", 16, "bold"))
        info_bar.pack(pady=(10, 10))

        # Canvas instead of a Label: the image is scaled to the real size of the pane,
        # and the magnifier can be drawn on top of it
        bg_color = ttk.Style().lookup("TFrame", "background") or self.root.cget("bg")
        self._preview_canvas = tk.Canvas(preview_frame, highlightthickness=0, bd=0, bg=bg_color)
        self._preview_canvas.pack(fill="both", expand=True)
        self._preview_canvas.bind("<Configure>", self._handle_preview_resize)
        self._preview_canvas.bind("<ButtonPress-1>", self._handle_lens_press)
        self._preview_canvas.bind("<B1-Motion>", self._handle_lens_motion)
        self._preview_canvas.bind("<ButtonRelease-1>", self._handle_lens_release)

        # Circle mask for the magnifier - built once, reused for every redraw
        self._lens_mask = Image.new("L", (config.LENS_SIZE, config.LENS_SIZE), 0)
        ImageDraw.Draw(self._lens_mask).ellipse((0, 0, config.LENS_SIZE - 1, config.LENS_SIZE - 1), fill=255)

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
            return None  # a popup is focused
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
        # Debounce: while scrolling fast through the table with the arrow keys held down, don't decode/load a JPEG for every single intermediate row
        if self._preview_after_id is not None:
            self.root.after_cancel(self._preview_after_id)

        self._preview_after_id = self.root.after(config.PREVIEW_DEBOUNCE_MS, self._apply_preview_selection)

    def _apply_preview_selection(self) -> None:
        self._preview_after_id = None

        selection = self.tray_table.selection()
        if not selection:
            self._clear_preview()
            return

        tray_number_str, _, _ = self.tray_table.item(selection[0], "values")
        self._load_preview_image(int(tray_number_str))

    def _clear_preview(self) -> None:
        self._set_preview_image(None)
        self._preview_info_var.set("Select a tray to preview its last captured image.")

    def _load_preview_image(self, tray_number: int) -> None:
        image_path = self._latest_capture(tray_number)

        if image_path is None:
            self._set_preview_image(None)
            self._preview_info_var.set(f"Tray {tray_number} - no captured image yet.")
            return

        try:
            # "with" closes the file again afterwards - convert() creates a fully loaded copy.
            # The FULL resolution is kept (no draft/thumbnail anymore): the preview is scaled
            # from it to fit the pane, and the magnifier needs the original details.
            with Image.open(image_path) as pil_image:
                full_image = pil_image.convert("RGB")
        except Exception as exc:
            self._set_preview_image(None)
            self._preview_info_var.set(f"Tray {tray_number} - could not load image ({exc}).")
            return

        self._set_preview_image(full_image)
        self._preview_info_var.set(self._format_capture_info(tray_number, image_path))

    def _set_preview_image(self, full_image: Optional[Image.Image]) -> None:
        """Shows a new image in the preview (None = empty preview)."""
        self._hide_lens()
        self._preview_full = full_image
        self._render_preview()

    def _handle_preview_resize(self, event=None) -> None:
        # Debounce: while the window or the divider is being dragged, <Configure> fires constantly -
        # only rescale once it has stopped for a moment
        if self._preview_resize_after_id is not None:
            self.root.after_cancel(self._preview_resize_after_id)
        self._preview_resize_after_id = self.root.after(config.PREVIEW_DEBOUNCE_MS, self._render_preview)

    def _render_preview(self) -> None:
        """Scales the full image to the current size of the preview canvas (keeping the aspect
        ratio, never larger than the original) and draws it centered."""
        self._preview_resize_after_id = None
        canvas = self._preview_canvas
        canvas.delete("preview")
        self._preview_photo = None

        if self._preview_full is None:
            return

        canvas_w, canvas_h = canvas.winfo_width(), canvas.winfo_height()
        if canvas_w < 10 or canvas_h < 10:
            return  # canvas not laid out yet - <Configure> calls this again once it is

        img_w, img_h = self._preview_full.size
        scale = min(canvas_w / img_w, canvas_h / img_h, 1.0)
        shown_w, shown_h = max(1, int(img_w * scale)), max(1, int(img_h * scale))

        # reducing_gap: shrinks in a fast first step, then does the fine LANCZOS scaling
        shown = self._preview_full.resize((shown_w, shown_h), Image.Resampling.LANCZOS, reducing_gap=3.0)
        self._preview_photo = ImageTk.PhotoImage(shown)

        x0, y0 = (canvas_w - shown_w) // 2, (canvas_h - shown_h) // 2
        canvas.create_image(x0, y0, image=self._preview_photo, anchor="nw", tags="preview")
        canvas.tag_raise("lens")

        self._preview_scale = scale
        self._preview_origin = (x0, y0)
        self._preview_size = (shown_w, shown_h)

    # --- Magnifier (hold left mouse button on the preview) -----------------------

    def _handle_lens_press(self, event) -> None:
        if self._preview_full is None:
            return
        self._preview_canvas.configure(cursor="none")  # the lens itself shows where the mouse is
        self._lens_pos = (event.x, event.y)
        self._draw_lens()

    def _handle_lens_motion(self, event) -> None:
        if self._lens_pos is None:
            return
        self._lens_pos = (event.x, event.y)
        # Throttle: only schedule a redraw if none is pending
        if self._lens_after_id is None:
            self._lens_after_id = self.root.after(config.LENS_UPDATE_MS, self._draw_lens)

    def _handle_lens_release(self, event=None) -> None:
        self._hide_lens()

    def _hide_lens(self) -> None:
        if self._lens_after_id is not None:
            self.root.after_cancel(self._lens_after_id)
            self._lens_after_id = None
        self._lens_pos = None
        self._lens_photo = None
        self._preview_canvas.delete("lens")
        self._preview_canvas.configure(cursor="")

    def _draw_lens(self) -> None:
        """Draws the magnifier circle at the mouse position: cuts the matching area out of the
        FULL-resolution image and enlarges it to LENS_SIZE."""
        self._lens_after_id = None
        canvas = self._preview_canvas
        if self._lens_pos is None or self._preview_full is None or self._preview_photo is None:
            return

        x, y = self._lens_pos
        x0, y0 = self._preview_origin
        shown_w, shown_h = self._preview_size
        canvas.delete("lens")
        self._lens_photo = None

        # Only over the image itself
        if not (x0 <= x < x0 + shown_w and y0 <= y < y0 + shown_h):
            return

        size = config.LENS_SIZE
        # Mouse position converted to the ORIGINAL image
        orig_x = (x - x0) / self._preview_scale
        orig_y = (y - y0) / self._preview_scale
        # Half the width of the original area that fits into the lens at LENS_ZOOM x the preview size
        half = size / (2 * config.LENS_ZOOM * self._preview_scale)

        region = self._preview_full.crop(
            (int(orig_x - half), int(orig_y - half), int(orig_x + half), int(orig_y + half))
        )
        region = region.resize((size, size), Image.Resampling.BILINEAR)
        region.putalpha(self._lens_mask)  # everything outside the circle becomes transparent
        self._lens_photo = ImageTk.PhotoImage(region)

        radius = size // 2
        canvas.create_image(x, y, image=self._lens_photo, tags="lens")
        canvas.create_oval(x - radius, y - radius, x + radius, y + radius,
                           outline="#333333", width=2, tags="lens")

    def _format_capture_info(self, tray_number: int, image_path: Path) -> str:
        """Builds a human-readable "Tray N - taken on DD-MM-YYYY at
        HH:MM:SS" string from the timestamp encoded in the filename."""
        timestamp = self._capture_timestamp(image_path)
        if timestamp is not None:
            formatted = timestamp.strftime("%d-%m-%Y at %H:%M:%S")
        else:
            formatted = image_path.stem.replace("finalFrame_", "")

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