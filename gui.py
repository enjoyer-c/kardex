"""
GUI. Layout:

Section 1: Search (left) - Status (center) - History-Button (right)

Section 2: Table listing all shelves 1-50, scrollable

*functions:
    -History open seperate popup-Window
    -Right-clicking on a row allows to rename descriptions
"""

from __future__ import annotations
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from datetime import datetime
from typing import Optional

import config
import inventory


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Kardex Shuffle Logisticssystem- Test")
        self.root.geometry("1920x1080")

        self._log_entries: list[str] = []
        self._history_window: Optional[tk.Toplevel] = None
        self._history_listbox: Optional[tk.Listbox] = None

        self._build_top_section()
        self._build_tray_table()

    # --- Section 1: Search / Status / History ----------------------------

    def _build_top_section(self) -> None:
        top_frame = ttk.Frame(self.root)
        top_frame.pack(padx=20, pady=20, fill="x")
        top_frame.grid_columnconfigure(0, weight=1)
        top_frame.grid_columnconfigure(1, weight=1)
        top_frame.grid_columnconfigure(2, weight=1)

        search_frame = ttk.Frame(top_frame)
        search_frame.grid(row=0, column=0, sticky="w")

        ttk.Label(search_frame, text="search:").pack(side="left", padx=(0, 5))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=25, font=("Arial", 11))
        search_entry.pack(side="left")
        search_entry.bind("<KeyRelease>", self._handle_search_change)

        self.status_text = tk.StringVar(value="IDLE - waiting for door to open")
        status_label = ttk.Label(top_frame, textvariable=self.status_text, font=("Arial", 16, "bold"))
        status_label.grid(row=0, column=1)

        history_button = ttk.Button(top_frame, text="History", command=self._open_history_window)
        history_button.grid(row=0, column=2, sticky="e")

    def set_status(self, text: str) -> None:
        self.status_text.set(text)

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

        columns = ("tray", "description")
        self.tray_table = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.tray_table.heading("tray", text="Tray Nr.")
        self.tray_table.heading("description", text="Description")
        self.tray_table.column("tray", width=100, stretch=False, anchor="center")
        self.tray_table.column("description", width=1000, anchor="w")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tray_table.yview)
        self.tray_table.configure(yscrollcommand=scrollbar.set)

        self.tray_table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Right-clicking opens the context menu
        self.tray_table.bind("<Button-3>", self._handle_right_click)

        self._populate_tray_table()

    def _populate_tray_table(self, filter_query: str = "") -> None:
        self.tray_table.delete(*self.tray_table.get_children())

        if filter_query.strip():
            rows = inventory.search(filter_query)
        else:
            rows = list(enumerate(inventory.read_all(), start=config.SHELF_LOWER_LIMIT))

        for shelf_number, description in rows:
            self.tray_table.insert("", "end", values=(shelf_number, description))

    def _handle_search_change(self, event=None) -> None:
        query = self.search_var.get()
        self._populate_tray_table(query)

        children = self.tray_table.get_children()
        if children:
            self.tray_table.see(children[0])
            self.tray_table.selection_set(children[0])

    # --- Rename with right mouse button ----------------------------------------

    def _handle_right_click(self, event) -> None:
        row_id = self.tray_table.identify_row(event.y)
        if not row_id:
            return 

        self.tray_table.selection_set(row_id)

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Rename", command=lambda: self._rename_row(row_id))
        menu.post(event.x_root, event.y_root)

    def _rename_row(self, row_id: str) -> None:
        shelf_number_str, current_description = self.tray_table.item(row_id, "values")

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
        self.tray_table.item(row_id, values=(shelf_number, new_description))
        self.log_event(f"Tray {shelf_number} renamed: {new_description}")


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    app.log_event("GUI gestartet (Testmodus)")
    root.mainloop()