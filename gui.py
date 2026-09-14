
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from datetime import datetime

import inventory


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Hochregallager - Testbetrieb (Pi)")

        self.status_text = tk.StringVar(value="IDLE - warte auf Tuer")
        status_label = ttk.Label(root, textvariable=self.status_text, font=("Arial", 16, "bold"))
        status_label.pack(padx=20, pady=(20, 5))

        self.next_step_text = tk.StringVar(value="")
        next_step_label = ttk.Label(root, textvariable=self.next_step_text, font=("Arial", 10, "italic"))
        next_step_label.pack(padx=20, pady=(0, 10))

        self._build_log_section()
        self._build_search_section()

    # --- History ---------------------------------------------------------

    def _build_log_section(self) -> None:
        log_frame = ttk.LabelFrame(self.root, text="Verlauf")
        log_frame.pack(padx=20, pady=10, fill="both", expand=True)

        self.log_listbox = tk.Listbox(log_frame, height=10, font=("Consolas", 10))
        self.log_listbox.pack(padx=10, pady=5, fill="both", expand=True)

    def log_event(self, text: str) -> None:
        """Adds a line with a timestamp to the history and
        automatically scrolls to it so that the most recent entry is always
        visible."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_listbox.insert(tk.END, f"[{timestamp}] {text}")
        self.log_listbox.see(tk.END)

    # --- Tray-Search --------------------------------------------------

    def _build_search_section(self) -> None:
        search_frame = ttk.LabelFrame(self.root, text="Tablar suchen")
        search_frame.pack(padx=20, pady=10, fill="both", expand=True)

        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, font=("Arial", 12))
        search_entry.pack(padx=10, pady=5, fill="x")
        search_entry.bind("<KeyRelease>", self._handle_search_change)

        self.results_listbox = tk.Listbox(search_frame, height=8, font=("Arial", 11))
        self.results_listbox.pack(padx=10, pady=5, fill="both", expand=True)

    def _handle_search_change(self, event=None) -> None:
        query = self.search_var.get()
        self.results_listbox.delete(0, tk.END)

        for shelf_number, description in inventory.search(query):
            self.results_listbox.insert(tk.END, f"Tablar {shelf_number}: {description}")

    # --- Status ------------------------------------------------------------

    def set_status(self, text: str) -> None:
        self.status_text.set(text)

    def set_next_step(self, text: str) -> None:
        self.next_step_text.set(text)


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    app.log_event("GUI gestartet (Testmodus)")
    app.set_next_step("Naechster Schritt: Tuer oeffnet")
    root.mainloop()