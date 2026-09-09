"""
Baggersee Anzeigetafel - Bedienoberfläche
Hier werden Temperaturen eingegeben und Bilder/QR-Codes verwaltet.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from PIL import Image, ImageTk

_BASE = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
         else os.path.dirname(os.path.abspath(__file__)))
DATA_FILE  = os.path.join(_BASE, "data.json")
ASSETS_DIR = os.path.join(_BASE, "assets")

APP_VERSION = "1.1.1"

DEFAULT_DATA = {
    "wasser_temp": "--",
    "luft_temp": "--",
    "slideshow_interval": 10,
    "show_temp_interval": 15,
    "weather_interval": 20,
    "show_weather": True,
    "orientation": "landscape",
    "luft_source": "manual",
    "csv_path": "",
    "wasser_source": "manual",
    "wasser_csv_path": "",
    "email_enabled": False,
    "email_server": "imap.gmail.com",
    "email_port": 993,
    "email_user": "",
    "email_password": "",
    "email_folder": "INBOX",
    "email_check_interval": 5,
    "update_url": "",
    "slides": [],
    "last_updated": "",
    "temp_log": [],
}

os.makedirs(ASSETS_DIR, exist_ok=True)


def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                for k, v in DEFAULT_DATA.items():
                    if k not in d:
                        d[k] = v
                # Migrate old "usb" source value to "csv"
                if d.get("luft_source") == "usb":
                    d["luft_source"] = "csv"
                # Ensure new wasser sensor fields exist
                if "wasser_source" not in d:
                    d["wasser_source"] = "manual"
                if "wasser_csv_path" not in d:
                    d["wasser_csv_path"] = ""
                if "temp_log" not in d:
                    d["temp_log"] = []
                return d
    except Exception:
        pass
    return dict(DEFAULT_DATA)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class ControlPanel:
    def __init__(self, root):
        self.root = root
        self.root.title("Badesee – Bedienoberfläche")
        self.root.geometry("820x740")
        self.root.minsize(720, 620)
        self.root.configure(bg="#1e1e2e")

        self.data = load_data()
        self.display_processes = []
        self.thumb_cache = {}
        self._sensor_running        = False
        self._wasser_sensor_running = False
        self._email_running         = False
        self.log_tree               = None
        self._log_day_offset        = 0   # 0 = heute, 1 = gestern, …

        self._setup_styles()
        self._build_ui()
        self._refresh_ui()
        self._start_sensor_if_enabled()
        self._start_wasser_sensor_if_enabled()
        self._start_email_if_enabled()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background="#1e1e2e", foreground="#cdd6f4",
                        font=("Segoe UI", 11))
        style.configure("TFrame", background="#1e1e2e")
        style.configure("TLabel", background="#1e1e2e", foreground="#cdd6f4",
                        font=("Segoe UI", 11))
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"),
                        foreground="#89b4fa")
        style.configure("Section.TLabel", font=("Segoe UI", 13, "bold"),
                        foreground="#89dceb")
        style.configure("Value.TLabel", font=("Segoe UI", 36, "bold"),
                        foreground="#a6e3a1")
        style.configure("TNotebook", background="#1e1e2e", borderwidth=0)
        style.configure("TNotebook.Tab", background="#313244", foreground="#cdd6f4",
                        padding=[14, 8], font=("Segoe UI", 11))
        style.map("TNotebook.Tab",
                  background=[("selected", "#45475a")],
                  foreground=[("selected", "#cba6f7")])
        style.configure("TEntry", fieldbackground="#313244", foreground="#cdd6f4",
                        insertcolor="#cdd6f4", borderwidth=0,
                        font=("Segoe UI", 11))
        style.configure("TSpinbox", fieldbackground="#313244", foreground="#cdd6f4",
                        insertcolor="#cdd6f4",
                        font=("Segoe UI", 11))
        style.configure("Primary.TButton", background="#89b4fa", foreground="#1e1e2e",
                        font=("Segoe UI", 11, "bold"), padding=[12, 8])
        style.map("Primary.TButton",
                  background=[("active", "#74c7ec")])
        style.configure("Danger.TButton", background="#f38ba8", foreground="#1e1e2e",
                        font=("Segoe UI", 11, "bold"), padding=[8, 6])
        style.map("Danger.TButton",
                  background=[("active", "#eba0ac")])
        style.configure("Success.TButton", background="#a6e3a1", foreground="#1e1e2e",
                        font=("Segoe UI", 11, "bold"), padding=[12, 8])
        style.map("Success.TButton",
                  background=[("active", "#94e2d5")])
        style.configure("TScrollbar", background="#45475a", troughcolor="#313244")

    def _build_ui(self):
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=20, pady=(20, 0))
        ttk.Label(header, text="🏖  Badesee Ummendorf", style="Title.TLabel").pack(side="left")

        btn_frame = ttk.Frame(header)
        btn_frame.pack(side="right")
        ttk.Button(btn_frame, text="▶  Anzeigen starten",
                   style="Success.TButton",
                   command=self._launch_displays).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="■  Anzeigen beenden",
                   style="Danger.TButton",
                   command=self._stop_displays).pack(side="left")

        sep = tk.Frame(self.root, bg="#45475a", height=1)
        sep.pack(fill="x", padx=20, pady=14)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self.tab_temp     = ttk.Frame(notebook)
        self.tab_slides   = ttk.Frame(notebook)
        self.tab_settings = ttk.Frame(notebook)
        self.tab_email    = ttk.Frame(notebook)

        notebook.add(self.tab_temp,     text="  🌡  Temperaturen  ")
        notebook.add(self.tab_slides,   text="  🖼  Bilder & QR-Codes  ")
        notebook.add(self.tab_settings, text="  ⚙  Einstellungen  ")
        notebook.add(self.tab_email,    text="  📧  E-Mail & Updates  ")

        self._build_temp_tab()
        self._build_slides_tab()
        self._build_settings_tab()
        self._build_email_tab()

    # ── Temperaturen ─────────────────────────────────────────────────────────

    def _build_temp_tab(self):
        frame = self.tab_temp
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)

        # Aktuelle Werte
        display_frame = tk.Frame(frame, bg="#313244", bd=0)
        display_frame.grid(row=0, column=0, columnspan=2, sticky="ew",
                           padx=20, pady=(20, 10))
        display_frame.columnconfigure(0, weight=1)
        display_frame.columnconfigure(1, weight=1)
        tk.Label(display_frame, text="Aktuell angezeigte Werte",
                 bg="#313244", fg="#89dceb",
                 font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=2,
                                                     pady=(14, 4), padx=20, sticky="w")
        tk.Label(display_frame, text="💧 Wasser", bg="#313244",
                 fg="#74c7ec", font=("Segoe UI", 11)).grid(row=1, column=0, padx=30, pady=4)
        tk.Label(display_frame, text="🌡 Luft", bg="#313244",
                 fg="#a6e3a1", font=("Segoe UI", 11)).grid(row=1, column=1, padx=30, pady=4)

        self.wasser_display = tk.Label(display_frame, text="--°C",
                                       bg="#313244", fg="#29b6f6",
                                       font=("Segoe UI", 48, "bold"))
        self.wasser_display.grid(row=2, column=0, padx=30, pady=(0, 4))

        self.luft_display = tk.Label(display_frame, text="--°C",
                                     bg="#313244", fg="#66bb6a",
                                     font=("Segoe UI", 48, "bold"))
        self.luft_display.grid(row=2, column=1, padx=30, pady=(0, 4))

        self.updated_display = tk.Label(display_frame, text="",
                                        bg="#313244", fg="#6c7086",
                                        font=("Segoe UI", 10))
        self.updated_display.grid(row=3, column=0, columnspan=2, pady=(0, 14))

        # Eingabefelder
        input_frame = tk.Frame(frame, bg="#1e1e2e")
        input_frame.grid(row=1, column=0, columnspan=2, sticky="ew",
                         padx=20, pady=10)
        input_frame.columnconfigure(0, weight=1)
        input_frame.columnconfigure(1, weight=1)

        # ── Wasser – mit Manuell/CSV-Toggle ──────────────────────────────────
        wl = tk.Frame(input_frame, bg="#0d2a4a", bd=0)
        wl.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=4)

        wasser_top = tk.Frame(wl, bg="#0d2a4a")
        wasser_top.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(wasser_top, text="Wassertemperatur",
                 bg="#0d2a4a", fg="#74c7ec",
                 font=("Segoe UI", 11, "bold")).pack(side="left")

        self.wasser_source_var = tk.StringVar(
            value=self.data.get("wasser_source", "manual"))
        tk.Radiobutton(wasser_top, text="Manuell",
                       variable=self.wasser_source_var, value="manual",
                       bg="#0d2a4a", fg="#cdd6f4", selectcolor="#1a3a5c",
                       activebackground="#0d2a4a",
                       font=("Segoe UI", 10),
                       command=self._on_wasser_source_change
                       ).pack(side="right", padx=(8, 0))
        tk.Radiobutton(wasser_top, text="CSV-Sensor",
                       variable=self.wasser_source_var, value="csv",
                       bg="#0d2a4a", fg="#cdd6f4", selectcolor="#1a3a5c",
                       activebackground="#0d2a4a",
                       font=("Segoe UI", 10),
                       command=self._on_wasser_source_change
                       ).pack(side="right")

        # Manuell-Bereich Wasser
        self.wasser_manual_frame = tk.Frame(wl, bg="#0d2a4a")
        self.wasser_manual_frame.pack(padx=16, fill="x")

        w_entry_row = tk.Frame(self.wasser_manual_frame, bg="#0d2a4a")
        w_entry_row.pack(pady=(0, 6), fill="x")
        self.wasser_var = tk.StringVar()
        tk.Entry(w_entry_row, textvariable=self.wasser_var,
                 font=("Segoe UI", 28, "bold"),
                 bg="#1a3a5c", fg="#29b6f6",
                 insertbackground="#29b6f6",
                 relief="flat", width=6,
                 justify="center").pack(side="left")
        tk.Label(w_entry_row, text="°C", bg="#0d2a4a", fg="#4a7a9b",
                 font=("Segoe UI", 22)).pack(side="left", padx=8)

        qb_w = tk.Frame(self.wasser_manual_frame, bg="#0d2a4a")
        qb_w.pack(pady=(0, 14), fill="x")
        for delta, label in [(-0.5, "−0.5"), (+0.5, "+0.5"), (+1, "+1"), (+2, "+2")]:
            tk.Button(qb_w, text=label,
                      bg="#1a3a5c", fg="#74c7ec",
                      font=("Segoe UI", 10),
                      relief="flat", padx=8, pady=4,
                      command=lambda d=delta: self._adjust_temp("wasser", d)
                      ).pack(side="left", padx=2)

        # CSV-Sensor-Bereich Wasser
        self.wasser_csv_frame = tk.Frame(wl, bg="#0d2a4a")
        self.wasser_csv_frame.pack(padx=16, fill="x")

        wcsv_row = tk.Frame(self.wasser_csv_frame, bg="#0d2a4a")
        wcsv_row.pack(fill="x", pady=(4, 4))
        tk.Label(wcsv_row, text="CSV-Datei:",
                 bg="#0d2a4a", fg="#bac2de",
                 font=("Segoe UI", 10)).pack(side="left")
        self.wasser_csv_path_var = tk.StringVar(
            value=self.data.get("wasser_csv_path", ""))
        tk.Entry(wcsv_row, textvariable=self.wasser_csv_path_var,
                 bg="#1a3a5c", fg="#cdd6f4",
                 insertbackground="#cdd6f4",
                 relief="flat", font=("Segoe UI", 9), width=18
                 ).pack(side="left", padx=6, fill="x", expand=True)
        tk.Button(wcsv_row, text="Browse",
                  bg="#1a3a5c", fg="#74c7ec",
                  relief="flat", font=("Segoe UI", 10),
                  padx=8, pady=2,
                  command=self._browse_wasser_csv).pack(side="left")
        self.wasser_csv_status_lbl = tk.Label(self.wasser_csv_frame,
                 text="● Keine Datei ausgewählt",
                 bg="#0d2a4a", fg="#6c7086",
                 font=("Segoe UI", 10))
        self.wasser_csv_status_lbl.pack(anchor="w", pady=(0, 14))

        self._on_wasser_source_change()

        # ── Luft – mit Manuell/CSV-Toggle ────────────────────────────────────
        ll = tk.Frame(input_frame, bg="#1a2a1a", bd=0)
        ll.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=4)

        luft_top = tk.Frame(ll, bg="#1a2a1a")
        luft_top.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(luft_top, text="Lufttemperatur",
                 bg="#1a2a1a", fg="#a6e3a1",
                 font=("Segoe UI", 11, "bold")).pack(side="left")

        self.luft_source_var = tk.StringVar(
            value=self.data.get("luft_source", "manual"))
        tk.Radiobutton(luft_top, text="Manuell",
                       variable=self.luft_source_var, value="manual",
                       bg="#1a2a1a", fg="#cdd6f4", selectcolor="#2a3a2a",
                       activebackground="#1a2a1a",
                       font=("Segoe UI", 10),
                       command=self._on_luft_source_change
                       ).pack(side="right", padx=(8, 0))
        tk.Radiobutton(luft_top, text="CSV-Sensor",
                       variable=self.luft_source_var, value="csv",
                       bg="#1a2a1a", fg="#cdd6f4", selectcolor="#2a3a2a",
                       activebackground="#1a2a1a",
                       font=("Segoe UI", 10),
                       command=self._on_luft_source_change
                       ).pack(side="right")

        # Manuell-Bereich Luft
        self.luft_manual_frame = tk.Frame(ll, bg="#1a2a1a")
        self.luft_manual_frame.pack(padx=16, fill="x")

        l_entry_row = tk.Frame(self.luft_manual_frame, bg="#1a2a1a")
        l_entry_row.pack(pady=(0, 6), fill="x")
        self.luft_var = tk.StringVar()
        tk.Entry(l_entry_row, textvariable=self.luft_var,
                 font=("Segoe UI", 28, "bold"),
                 bg="#1a2e1a", fg="#66bb6a",
                 insertbackground="#66bb6a",
                 relief="flat", width=6,
                 justify="center").pack(side="left")
        tk.Label(l_entry_row, text="°C", bg="#1a2a1a", fg="#4a7a9b",
                 font=("Segoe UI", 22)).pack(side="left", padx=8)

        qb_l = tk.Frame(self.luft_manual_frame, bg="#1a2a1a")
        qb_l.pack(pady=(0, 14), fill="x")
        for delta, label in [(-0.5, "−0.5"), (+0.5, "+0.5"), (+1, "+1"), (+2, "+2")]:
            tk.Button(qb_l, text=label,
                      bg="#1a2e1a", fg="#a6e3a1",
                      font=("Segoe UI", 10),
                      relief="flat", padx=8, pady=4,
                      command=lambda d=delta: self._adjust_temp("luft", d)
                      ).pack(side="left", padx=2)

        # CSV-Sensor-Bereich Luft
        self.luft_csv_frame = tk.Frame(ll, bg="#1a2a1a")
        self.luft_csv_frame.pack(padx=16, fill="x")

        csv_row = tk.Frame(self.luft_csv_frame, bg="#1a2a1a")
        csv_row.pack(fill="x", pady=(4, 4))
        tk.Label(csv_row, text="CSV-Datei:",
                 bg="#1a2a1a", fg="#bac2de",
                 font=("Segoe UI", 10)).pack(side="left")

        self.csv_path_var = tk.StringVar(value=self.data.get("csv_path", ""))
        csv_entry = tk.Entry(csv_row, textvariable=self.csv_path_var,
                             bg="#2a3a2a", fg="#cdd6f4",
                             insertbackground="#cdd6f4",
                             relief="flat", font=("Segoe UI", 9), width=18)
        csv_entry.pack(side="left", padx=6, fill="x", expand=True)

        tk.Button(csv_row, text="Browse",
                  bg="#2a3a2a", fg="#a6e3a1",
                  relief="flat", font=("Segoe UI", 10),
                  padx=8, pady=2,
                  command=self._browse_csv).pack(side="left")

        self.csv_status_lbl = tk.Label(self.luft_csv_frame,
                 text="● Keine Datei ausgewählt",
                 bg="#1a2a1a", fg="#6c7086",
                 font=("Segoe UI", 10))
        self.csv_status_lbl.pack(anchor="w", pady=(0, 14))

        self._on_luft_source_change()

        # Speichern-Button (nur sichtbar wenn mindestens eine Quelle auf Manuell)
        save_btn = tk.Button(frame,
                             text="✓   Temperaturen speichern & anzeigen",
                             bg="#89b4fa", fg="#1e1e2e",
                             font=("Segoe UI", 13, "bold"),
                             relief="flat", padx=20, pady=12,
                             cursor="hand2",
                             command=self._save_temps)
        save_btn.grid(row=2, column=0, columnspan=2,
                      sticky="ew", padx=20, pady=(4, 8))

        # ── Temperatur-Protokoll ──────────────────────────────────────────────
        log_frame = tk.Frame(frame, bg="#1e1e2e")
        log_frame.grid(row=3, column=0, columnspan=2, sticky="nsew",
                       padx=20, pady=(0, 16))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)

        # Navigation: ◀  Datum  ▶
        nav = tk.Frame(log_frame, bg="#1e1e2e")
        nav.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        nav.columnconfigure(1, weight=1)

        self._nav_prev_btn = tk.Button(
            nav, text="◀", bg="#45475a", fg="#cdd6f4",
            font=("Segoe UI", 12, "bold"), relief="flat",
            padx=10, pady=2,
            command=lambda: self._nav_log(+1))   # +1 = älter
        self._nav_prev_btn.grid(row=0, column=0, padx=(0, 8))

        self._log_date_lbl = tk.Label(
            nav, text="Tagesprotokoll",
            bg="#1e1e2e", fg="#89dceb",
            font=("Segoe UI", 13, "bold"), anchor="center")
        self._log_date_lbl.grid(row=0, column=1, sticky="ew")

        self._nav_next_btn = tk.Button(
            nav, text="▶", bg="#45475a", fg="#cdd6f4",
            font=("Segoe UI", 12, "bold"), relief="flat",
            padx=10, pady=2,
            command=lambda: self._nav_log(-1))   # -1 = neuer
        self._nav_next_btn.grid(row=0, column=2, padx=(8, 0))

        # Tabelle – zeigt immer nur einen Tag
        cols = ("luft_10", "luft_12", "luft_14", "luft_16", "wasser", "wasser_time")
        headings = ("Luft 10:00", "Luft 12:00", "Luft 14:00",
                    "Luft 16:00", "Wasser", "Zeit Wasser")

        style = ttk.Style()
        style.configure("Log.Treeview",
                        background="#313244", foreground="#cdd6f4",
                        fieldbackground="#313244", rowheight=30,
                        font=("Segoe UI", 11))
        style.configure("Log.Treeview.Heading",
                        background="#45475a", foreground="#89dceb",
                        font=("Segoe UI", 10, "bold"))
        style.map("Log.Treeview", background=[("selected", "#585b70")])

        tree_frame = tk.Frame(log_frame, bg="#313244")
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)

        self.log_tree = ttk.Treeview(tree_frame, columns=cols,
                                     show="headings", style="Log.Treeview",
                                     height=2)
        widths = [100, 100, 100, 100, 90, 100]
        for col, head, w in zip(cols, headings, widths):
            self.log_tree.heading(col, text=head)
            self.log_tree.column(col, width=w, anchor="center", minwidth=70)

        self.log_tree.grid(row=0, column=0, sticky="ew")

        self._refresh_log_table()

    # ── CSV-Sensor (Luft) ─────────────────────────────────────────────────────

    def _browse_csv(self):
        path = filedialog.askopenfilename(
            title="CSV-Datei für Lufttemperatur auswählen",
            filetypes=[("CSV-Dateien", "*.csv"), ("Alle Dateien", "*.*")]
        )
        if path:
            self.csv_path_var.set(path)
            self._save_sensor_settings()
            if self.luft_source_var.get() == "csv":
                self._stop_sensor_reading()
                self._start_sensor_reading()

    def _on_luft_source_change(self):
        src = self.luft_source_var.get()
        if src == "csv":
            self.luft_manual_frame.pack_forget()
            self.luft_csv_frame.pack(padx=16, fill="x")
            self._save_sensor_settings()
            self._start_sensor_reading()
        else:
            self.luft_csv_frame.pack_forget()
            self.luft_manual_frame.pack(padx=16, fill="x")
            self._stop_sensor_reading()
            self._save_sensor_settings()

    def _save_sensor_settings(self):
        self.data = load_data()
        self.data["luft_source"] = self.luft_source_var.get()
        self.data["csv_path"]    = self.csv_path_var.get()
        save_data(self.data)

    def _start_sensor_if_enabled(self):
        if self.data.get("luft_source", "manual") == "csv":
            self._start_sensor_reading()

    def _start_sensor_reading(self):
        if self._sensor_running:
            return
        self._sensor_running = True
        threading.Thread(target=self._csv_reader, daemon=True).start()

    def _stop_sensor_reading(self):
        self._sensor_running = False

    # ── CSV-Sensor (Wasser) ───────────────────────────────────────────────────

    def _browse_wasser_csv(self):
        path = filedialog.askopenfilename(
            title="CSV-Datei für Wassertemperatur auswählen",
            filetypes=[("CSV-Dateien", "*.csv"), ("Alle Dateien", "*.*")]
        )
        if path:
            self.wasser_csv_path_var.set(path)
            self._save_wasser_sensor_settings()
            if self.wasser_source_var.get() == "csv":
                self._stop_wasser_sensor_reading()
                self._start_wasser_sensor_reading()

    def _on_wasser_source_change(self):
        src = self.wasser_source_var.get()
        if src == "csv":
            self.wasser_manual_frame.pack_forget()
            self.wasser_csv_frame.pack(padx=16, fill="x")
            self._save_wasser_sensor_settings()
            self._start_wasser_sensor_reading()
        else:
            self.wasser_csv_frame.pack_forget()
            self.wasser_manual_frame.pack(padx=16, fill="x")
            self._stop_wasser_sensor_reading()
            self._save_wasser_sensor_settings()

    def _save_wasser_sensor_settings(self):
        self.data = load_data()
        self.data["wasser_source"]   = self.wasser_source_var.get()
        self.data["wasser_csv_path"] = self.wasser_csv_path_var.get()
        save_data(self.data)

    def _start_wasser_sensor_if_enabled(self):
        if self.data.get("wasser_source", "manual") == "csv":
            self._start_wasser_sensor_reading()

    def _start_wasser_sensor_reading(self):
        if self._wasser_sensor_running:
            return
        self._wasser_sensor_running = True
        threading.Thread(target=self._wasser_csv_reader, daemon=True).start()

    def _stop_wasser_sensor_reading(self):
        self._wasser_sensor_running = False

    def _wasser_csv_reader(self):
        last_mtime = None
        MAX_LINES  = 500

        while self._wasser_sensor_running:
            self.data = load_data()
            csv_path  = self.data.get("wasser_csv_path", "")

            if not csv_path:
                self.root.after(0, lambda: self.wasser_csv_status_lbl.config(
                    text="● Keine Datei ausgewählt", fg="#6c7086"))
                time.sleep(5)
                continue

            if not os.path.exists(csv_path):
                self.root.after(0, lambda p=csv_path: self.wasser_csv_status_lbl.config(
                    text=f"● Datei nicht gefunden: {os.path.basename(p)}", fg="#f38ba8"))
                time.sleep(5)
                continue

            try:
                mtime = os.path.getmtime(csv_path)
                if mtime != last_mtime:
                    last_mtime = mtime
                    with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
                        raw_lines = f.readlines()

                    non_empty = [l.rstrip("\r\n") for l in raw_lines if l.strip()]

                    if len(non_empty) > MAX_LINES:
                        kept = non_empty[-MAX_LINES:]
                        try:
                            with open(csv_path, "w", encoding="utf-8") as f:
                                f.write("\n".join(kept) + "\n")
                            non_empty = kept
                        except Exception:
                            pass

                    val = None
                    for line in reversed(non_empty):
                        parts = [p.strip() for p in line.split(",")]
                        parts = [p for p in parts if p]
                        if not parts:
                            continue
                        value_parts = (parts[1:] if len(parts) > 1 and
                                       re.match(r'\d{4}-\d{2}-\d{2}', parts[0])
                                       else parts)
                        combined = ",".join(value_parts)
                        combined = re.sub(r'(\d),(\d)', r'\1.\2', combined)
                        nums = re.findall(r'-?\d+\.?\d*', combined)
                        if nums:
                            candidate = float(nums[0])
                            if -10 <= candidate <= 50:
                                val = candidate
                                break

                    if val is not None:
                        d = load_data()
                        d["wasser_temp"]   = f"{val:.1f}".rstrip("0").rstrip(".")
                        d["last_updated"]  = datetime.now().isoformat()
                        save_data(d)
                        ts = datetime.now().strftime("%H:%M")
                        self.root.after(0, lambda v=val, t=ts, c=len(non_empty):
                            self.wasser_csv_status_lbl.config(
                                text=f"● Aktiv  |  {v:.1f}°C  ·  {t} Uhr  ({c} Einträge)",
                                fg="#74c7ec"))
                        self.root.after(0, lambda v=val: self._log_temp("wasser", v))
                    else:
                        self.root.after(0, lambda: self.wasser_csv_status_lbl.config(
                            text="● Kein gültiger Temperaturwert gefunden", fg="#f9e2af"))

            except Exception as e:
                self.root.after(0, lambda err=str(e): self.wasser_csv_status_lbl.config(
                    text=f"● Fehler: {err[:60]}", fg="#f38ba8"))

            time.sleep(5)

    def _csv_reader(self):
        last_mtime = None
        MAX_LINES  = 500  # Datei auf diese Anzahl Einträge kürzen

        while self._sensor_running:
            self.data = load_data()
            csv_path  = self.data.get("csv_path", "")

            if not csv_path:
                self.root.after(0, lambda: self.csv_status_lbl.config(
                    text="● Keine Datei ausgewählt", fg="#6c7086"))
                time.sleep(5)
                continue

            if not os.path.exists(csv_path):
                self.root.after(0, lambda p=csv_path: self.csv_status_lbl.config(
                    text=f"● Datei nicht gefunden: {os.path.basename(p)}", fg="#f38ba8"))
                time.sleep(5)
                continue

            try:
                mtime = os.path.getmtime(csv_path)
                if mtime != last_mtime:
                    last_mtime = mtime
                    with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
                        raw_lines = f.readlines()

                    non_empty = [l.rstrip("\r\n") for l in raw_lines if l.strip()]

                    # Datei kürzen wenn zu groß
                    if len(non_empty) > MAX_LINES:
                        kept = non_empty[-MAX_LINES:]
                        try:
                            with open(csv_path, "w", encoding="utf-8") as f:
                                f.write("\n".join(kept) + "\n")
                            non_empty = kept
                        except Exception:
                            pass  # Datei gesperrt – beim nächsten Mal versuchen

                    # Temperatur aus letzter gültiger Zeile lesen
                    # Format: "2026-08-27 10:21:24,21,75°C," (deutsches Dezimalkomma)
                    val = None
                    for line in reversed(non_empty):
                        parts = [p.strip() for p in line.split(",")]
                        parts = [p for p in parts if p]  # Leerfelder entfernen
                        if not parts:
                            continue

                        # Zeitstempel überspringen (beginnt mit "JJJJ-")
                        value_parts = (parts[1:] if len(parts) > 1 and
                                       re.match(r'\d{4}-\d{2}-\d{2}', parts[0])
                                       else parts)

                        # Deutsches Dezimalkomma normalisieren: "21,75" → "21.75"
                        combined = ",".join(value_parts)
                        combined = re.sub(r'(\d),(\d)', r'\1.\2', combined)

                        nums = re.findall(r'-?\d+\.?\d*', combined)
                        if nums:
                            candidate = float(nums[0])
                            if -50 <= candidate <= 80:
                                val = candidate
                                break

                    if val is not None:
                        d = load_data()
                        d["luft_temp"] = f"{val:.1f}".rstrip("0").rstrip(".")
                        d["last_updated"] = datetime.now().isoformat()
                        save_data(d)
                        count = len(non_empty)
                        ts = datetime.now().strftime("%H:%M")
                        self.root.after(0, lambda v=val, t=ts, c=count:
                            self.csv_status_lbl.config(
                                text=f"● Aktiv  |  {v:.1f}°C  ·  {t} Uhr  ({c} Einträge)",
                                fg="#a6e3a1"))
                        # Zeitslot-Protokollierung (10/12/14/16 Uhr ± 20 Min.)
                        slot = self._current_luft_slot()
                        if slot:
                            self.root.after(0, lambda v=val, s=slot:
                                self._log_temp(s, v))
                    else:
                        self.root.after(0, lambda: self.csv_status_lbl.config(
                            text="● Kein gültiger Temperaturwert gefunden", fg="#f9e2af"))

            except Exception as e:
                self.root.after(0, lambda err=str(e): self.csv_status_lbl.config(
                    text=f"● Fehler: {err[:60]}", fg="#f38ba8"))

            time.sleep(5)

    @staticmethod
    def _current_luft_slot():
        """Gibt 'luft_10', 'luft_12', 'luft_14' oder 'luft_16' zurück,
        wenn die aktuelle Uhrzeit ± 20 Minuten um eine der Messzeiten liegt."""
        now = datetime.now()
        total_min = now.hour * 60 + now.minute
        for slot_hour in [10, 12, 14, 16]:
            if abs(total_min - slot_hour * 60) <= 20:
                return f"luft_{slot_hour:02d}"
        return None

    def _log_temp(self, field, value):
        """Trägt einen Temperaturwert in das Tagesprotokoll ein.
        field: 'luft_10', 'luft_12', 'luft_14', 'luft_16' oder 'wasser'
        Luft-Slots werden nur einmal pro Tag gesetzt."""
        d = load_data()
        today = datetime.now().strftime("%Y-%m-%d")
        log   = d.get("temp_log", [])

        entry = next((e for e in log if e.get("date") == today), None)
        if entry is None:
            entry = {
                "date": today,
                "luft_10": None, "luft_12": None,
                "luft_14": None, "luft_16": None,
                "wasser": None,  "wasser_time": None,
            }
            log.insert(0, entry)

        if field.startswith("luft_") and entry.get(field) is not None:
            return  # Slot für heute bereits eingetragen

        val_str = f"{value:.1f}".rstrip("0").rstrip(".")
        if field == "wasser":
            entry["wasser"]      = val_str
            entry["wasser_time"] = datetime.now().strftime("%H:%M")
        else:
            entry[field] = val_str

        # Maximal 7 Tage aufbewahren
        log = sorted(log, key=lambda e: e.get("date", ""), reverse=True)[:7]
        d["temp_log"] = log
        save_data(d)
        self.data = d
        self._refresh_log_table()

    def _nav_log(self, direction):
        """direction: +1 = einen Tag älter, -1 = einen Tag neuer."""
        log = self.data.get("temp_log", [])
        log_sorted = sorted(log, key=lambda e: e.get("date", ""), reverse=True)
        max_offset = max(0, len(log_sorted) - 1)
        self._log_day_offset = max(0, min(max_offset, self._log_day_offset + direction))
        self._refresh_log_table()

    def _refresh_log_table(self):
        if self.log_tree is None:
            return

        self.data = load_data()
        log = self.data.get("temp_log", [])
        log_sorted = sorted(log, key=lambda e: e.get("date", ""), reverse=True)

        # Offset sicher halten
        max_offset = max(0, len(log_sorted) - 1)
        self._log_day_offset = min(self._log_day_offset, max_offset)

        # Nav-Buttons aktualisieren
        prev_state = "normal" if self._log_day_offset < max_offset else "disabled"
        next_state = "normal" if self._log_day_offset > 0 else "disabled"
        try:
            self._nav_prev_btn.config(state=prev_state)
            self._nav_next_btn.config(state=next_state)
        except Exception:
            pass

        # Datumsbeschriftung
        if log_sorted:
            entry = log_sorted[self._log_day_offset]
            raw_date = entry.get("date", "")
            try:
                dt = datetime.strptime(raw_date, "%Y-%m-%d")
                weekdays = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
                wd = weekdays[dt.weekday()]
                disp_date = dt.strftime(f"{wd}, %d.%m.%Y")
                if self._log_day_offset == 0:
                    disp_date = f"Heute  –  {disp_date}"
                elif self._log_day_offset == 1:
                    disp_date = f"Gestern  –  {disp_date}"
            except Exception:
                disp_date = raw_date
        else:
            entry     = {}
            disp_date = "Noch keine Einträge"

        try:
            self._log_date_lbl.config(text=disp_date)
        except Exception:
            pass

        # Treeview befüllen
        for row in self.log_tree.get_children():
            self.log_tree.delete(row)

        def fmt(v):
            return f"{v}°C" if v else "--"

        self.log_tree.insert("", "end", values=(
            fmt(entry.get("luft_10")),
            fmt(entry.get("luft_12")),
            fmt(entry.get("luft_14")),
            fmt(entry.get("luft_16")),
            fmt(entry.get("wasser")),
            entry.get("wasser_time") or "--",
        ))

    def _adjust_temp(self, field, delta):
        var = self.wasser_var if field == "wasser" else self.luft_var
        try:
            current = float(var.get().replace(",", "."))
            new_val = current + delta
            if new_val == int(new_val):
                var.set(str(int(new_val)))
            else:
                var.set(f"{new_val:.1f}")
        except ValueError:
            pass

    def _save_temps(self):
        wt = self.wasser_var.get().strip().replace(",", ".")
        lt = self.luft_var.get().strip().replace(",", ".")

        # Bei CSV-Quellen müssen die entsprechenden Felder nicht manuell gefüllt sein
        wasser_is_manual = self.wasser_source_var.get() == "manual"
        luft_is_manual   = self.luft_source_var.get()   == "manual"

        if wasser_is_manual and luft_is_manual and not wt and not lt:
            messagebox.showwarning("Eingabe fehlt",
                                   "Bitte mindestens eine Temperatur eingeben.")
            return

        self.data = load_data()
        wasser_val = None
        if wt:
            try:
                v = float(wt)
                wasser_val = v
                self.data["wasser_temp"] = f"{v:.1f}".rstrip("0").rstrip(".")
            except ValueError:
                messagebox.showerror("Ungültige Eingabe",
                                     "Wassertemperatur ist keine gültige Zahl.")
                return
        if lt:
            try:
                v = float(lt)
                self.data["luft_temp"] = f"{v:.1f}".rstrip("0").rstrip(".")
            except ValueError:
                messagebox.showerror("Ungültige Eingabe",
                                     "Lufttemperatur ist keine gültige Zahl.")
                return

        self.data["last_updated"] = datetime.now().isoformat()
        save_data(self.data)
        # Wassertemperatur ins Tagesprotokoll eintragen
        if wasser_val is not None:
            self._log_temp("wasser", wasser_val)
        self._refresh_ui()
        self._flash_saved()

    def _flash_saved(self):
        orig = self.updated_display.cget("text")
        self.updated_display.config(text="✓  Gespeichert!", fg="#a6e3a1")
        self.root.after(2000, lambda: self.updated_display.config(
            text=orig, fg="#6c7086"))

    # ── Slides / Bilder ───────────────────────────────────────────────────────

    def _build_slides_tab(self):
        frame = self.tab_slides
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        toolbar = tk.Frame(frame, bg="#1e1e2e")
        toolbar.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))

        tk.Button(toolbar, text="+ Bild hinzufügen",
                  bg="#89b4fa", fg="#1e1e2e",
                  font=("Segoe UI", 11, "bold"),
                  relief="flat", padx=12, pady=6,
                  cursor="hand2",
                  command=self._add_image).pack(side="left", padx=(0, 8))

        tk.Button(toolbar, text="+ QR-Code hinzufügen",
                  bg="#cba6f7", fg="#1e1e2e",
                  font=("Segoe UI", 11, "bold"),
                  relief="flat", padx=12, pady=6,
                  cursor="hand2",
                  command=self._add_qr).pack(side="left")

        tk.Label(toolbar,
                 text="Reihenfolge: ↑↓ Buttons",
                 bg="#1e1e2e", fg="#6c7086",
                 font=("Segoe UI", 10)).pack(side="right")

        list_container = tk.Frame(frame, bg="#1e1e2e")
        list_container.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 16))
        list_container.columnconfigure(0, weight=1)
        list_container.rowconfigure(0, weight=1)

        canvas = tk.Canvas(list_container, bg="#1e1e2e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical",
                                  command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.slides_inner = tk.Frame(canvas, bg="#1e1e2e")
        canvas_window = canvas.create_window((0, 0), window=self.slides_inner, anchor="nw")

        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(canvas_window, width=e.width))
        self.slides_inner.bind("<Configure>",
                               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        self._render_slides_list()

    def _render_slides_list(self):
        for widget in self.slides_inner.winfo_children():
            widget.destroy()

        slides = self.data.get("slides", [])
        if not slides:
            tk.Label(self.slides_inner,
                     text="Noch keine Bilder hinzugefügt.",
                     bg="#1e1e2e", fg="#6c7086",
                     font=("Segoe UI", 12),
                     justify="center").pack(pady=40)
            return

        for i, slide in enumerate(slides):
            self._render_slide_row(i, slide)

    def _render_slide_row(self, index, slide):
        row = tk.Frame(self.slides_inner, bg="#313244", bd=0)
        row.pack(fill="x", pady=4)

        thumb_frame = tk.Frame(row, bg="#313244", width=80, height=60)
        thumb_frame.pack(side="left", padx=12, pady=8)
        thumb_frame.pack_propagate(False)

        path = os.path.join(ASSETS_DIR, slide.get("filename", ""))
        try:
            img = Image.open(path)
            img.thumbnail((80, 60), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.thumb_cache[slide["filename"]] = photo
            tk.Label(thumb_frame, image=photo, bg="#313244").pack(expand=True)
        except Exception:
            tk.Label(thumb_frame, text="?",
                     bg="#45475a", fg="#6c7086",
                     font=("Segoe UI", 20)).pack(expand=True, fill="both")

        info = tk.Frame(row, bg="#313244")
        info.pack(side="left", fill="both", expand=True, pady=8)

        stype = slide.get("type", "image")
        type_color = "#cba6f7" if stype == "qr" else "#89b4fa"
        type_label = "QR-Code" if stype == "qr" else "Bild"

        tk.Label(info,
                 text=f"[{type_label}]  {slide.get('caption', slide.get('filename', ''))}",
                 bg="#313244", fg=type_color,
                 font=("Segoe UI", 11, "bold"),
                 anchor="w").pack(anchor="w")
        tk.Label(info,
                 text=slide.get("filename", ""),
                 bg="#313244", fg="#6c7086",
                 font=("Segoe UI", 9),
                 anchor="w").pack(anchor="w")

        btns = tk.Frame(row, bg="#313244")
        btns.pack(side="right", padx=8, pady=8)

        slides = self.data.get("slides", [])
        if index > 0:
            tk.Button(btns, text="↑",
                      bg="#45475a", fg="#cdd6f4",
                      relief="flat", font=("Segoe UI", 12),
                      padx=8, pady=4,
                      command=lambda i=index: self._move_slide(i, -1)
                      ).pack(side="left", padx=2)
        if index < len(slides) - 1:
            tk.Button(btns, text="↓",
                      bg="#45475a", fg="#cdd6f4",
                      relief="flat", font=("Segoe UI", 12),
                      padx=8, pady=4,
                      command=lambda i=index: self._move_slide(i, 1)
                      ).pack(side="left", padx=2)

        tk.Button(btns, text="✎ Bezeichnung",
                  bg="#45475a", fg="#cdd6f4",
                  relief="flat", font=("Segoe UI", 10),
                  padx=8, pady=4,
                  command=lambda i=index: self._rename_slide(i)
                  ).pack(side="left", padx=2)

        tk.Button(btns, text="✕",
                  bg="#f38ba8", fg="#1e1e2e",
                  relief="flat", font=("Segoe UI", 11, "bold"),
                  padx=8, pady=4,
                  command=lambda i=index: self._delete_slide(i)
                  ).pack(side="left", padx=2)

    def _add_image(self):
        path = filedialog.askopenfilename(
            title="Bild auswählen",
            filetypes=[("Bilder", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                       ("Alle Dateien", "*.*")]
        )
        if not path:
            return
        filename = os.path.basename(path)
        dest = os.path.join(ASSETS_DIR, filename)
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(dest):
            filename = f"{base}_{counter}{ext}"
            dest = os.path.join(ASSETS_DIR, filename)
            counter += 1
        shutil.copy2(path, dest)

        caption = self._ask_caption(f"Bezeichnung für '{filename}':")
        self.data["slides"].append({"filename": filename, "caption": caption, "type": "image"})
        save_data(self.data)
        self._render_slides_list()

    def _add_qr(self):
        path = filedialog.askopenfilename(
            title="QR-Code Bild auswählen",
            filetypes=[("Bilder", "*.png *.jpg *.jpeg *.gif *.bmp"),
                       ("Alle Dateien", "*.*")]
        )
        if not path:
            return
        filename = os.path.basename(path)
        dest = os.path.join(ASSETS_DIR, filename)
        if not os.path.exists(dest):
            shutil.copy2(path, dest)

        caption = self._ask_caption("Bezeichnung (z.B. 'Instagram @badesee_ummendorf'):")
        self.data["slides"].append({"filename": filename, "caption": caption, "type": "qr"})
        save_data(self.data)
        self._render_slides_list()

    def _ask_caption(self, prompt):
        dialog = tk.Toplevel(self.root)
        dialog.title("Bezeichnung")
        dialog.geometry("420x160")
        dialog.configure(bg="#1e1e2e")
        dialog.grab_set()
        dialog.transient(self.root)

        tk.Label(dialog, text=prompt,
                 bg="#1e1e2e", fg="#cdd6f4",
                 font=("Segoe UI", 11)).pack(pady=(20, 8), padx=20)
        var = tk.StringVar()
        entry = tk.Entry(dialog, textvariable=var,
                         bg="#313244", fg="#cdd6f4",
                         insertbackground="#cdd6f4",
                         relief="flat", font=("Segoe UI", 12))
        entry.pack(fill="x", padx=20)
        entry.focus()

        result = [""]

        def ok(event=None):
            result[0] = var.get().strip()
            dialog.destroy()

        tk.Button(dialog, text="OK",
                  bg="#89b4fa", fg="#1e1e2e",
                  relief="flat", font=("Segoe UI", 11, "bold"),
                  padx=16, pady=6,
                  command=ok).pack(pady=14)
        entry.bind("<Return>", ok)
        dialog.wait_window()
        return result[0]

    def _move_slide(self, index, direction):
        slides = self.data["slides"]
        new_index = index + direction
        if 0 <= new_index < len(slides):
            slides[index], slides[new_index] = slides[new_index], slides[index]
            save_data(self.data)
            self._render_slides_list()

    def _rename_slide(self, index):
        slide = self.data["slides"][index]
        new_caption = self._ask_caption(f"Neue Bezeichnung für '{slide['filename']}':")
        if new_caption:
            slide["caption"] = new_caption
            save_data(self.data)
            self._render_slides_list()

    def _delete_slide(self, index):
        slide = self.data["slides"][index]
        if messagebox.askyesno("Löschen",
                               f"'{slide['filename']}' aus der Slideshow entfernen?\n"
                               "(Die Datei bleibt im Assets-Ordner erhalten)"):
            self.data["slides"].pop(index)
            save_data(self.data)
            self._render_slides_list()

    # ── Einstellungen ─────────────────────────────────────────────────────────

    def _build_settings_tab(self):
        frame = self.tab_settings
        frame.columnconfigure(0, weight=1)

        content = tk.Frame(frame, bg="#1e1e2e")
        content.pack(fill="both", expand=True, padx=30, pady=20)
        content.columnconfigure(1, weight=1)

        def lbl(r, text):
            tk.Label(content, text=text,
                     bg="#1e1e2e", fg="#bac2de",
                     font=("Segoe UI", 11),
                     anchor="w").grid(row=r, column=0, sticky="w",
                                      pady=8, padx=(0, 20))

        def sep(r):
            tk.Frame(content, bg="#45475a", height=1).grid(
                row=r, column=0, columnspan=2, sticky="ew", pady=8)

        # Zeiten
        self.temp_interval_var = tk.IntVar(value=self.data.get("show_temp_interval", 15))
        lbl(0, "Temperaturen anzeigen für (Sek.):")
        tk.Spinbox(content, from_=5, to=120,
                   textvariable=self.temp_interval_var,
                   bg="#313244", fg="#cdd6f4",
                   insertbackground="#cdd6f4",
                   buttonbackground="#45475a",
                   relief="flat",
                   font=("Segoe UI", 12), width=8
                   ).grid(row=0, column=1, sticky="ew", pady=8)

        self.slide_interval_var = tk.IntVar(value=self.data.get("slideshow_interval", 10))
        lbl(1, "Bild/QR-Code anzeigen für (Sek.):")
        tk.Spinbox(content, from_=3, to=60,
                   textvariable=self.slide_interval_var,
                   bg="#313244", fg="#cdd6f4",
                   insertbackground="#cdd6f4",
                   buttonbackground="#45475a",
                   relief="flat",
                   font=("Segoe UI", 12), width=8
                   ).grid(row=1, column=1, sticky="ew", pady=8)

        self.weather_interval_var = tk.IntVar(value=self.data.get("weather_interval", 20))
        lbl(2, "Wettervorhersage anzeigen für (Sek.):")
        tk.Spinbox(content, from_=5, to=120,
                   textvariable=self.weather_interval_var,
                   bg="#313244", fg="#cdd6f4",
                   insertbackground="#cdd6f4",
                   buttonbackground="#45475a",
                   relief="flat",
                   font=("Segoe UI", 12), width=8
                   ).grid(row=2, column=1, sticky="ew", pady=8)

        sep(3)

        # Anzeige
        self.show_weather_var = tk.BooleanVar(value=self.data.get("show_weather", True))
        lbl(4, "Wettervorhersage einblenden:")
        tk.Checkbutton(content,
                       variable=self.show_weather_var,
                       text="(Ummendorf · Open-Meteo)",
                       bg="#1e1e2e", fg="#bac2de",
                       selectcolor="#313244",
                       activebackground="#1e1e2e",
                       font=("Segoe UI", 11)
                       ).grid(row=4, column=1, sticky="w", pady=8)

        # Ausrichtung
        lbl(5, "Ausrichtung der Anzeige:")
        orient_frame = tk.Frame(content, bg="#1e1e2e")
        orient_frame.grid(row=5, column=1, sticky="w", pady=8)
        self.orientation_var = tk.StringVar(value=self.data.get("orientation", "landscape"))
        tk.Radiobutton(orient_frame, text="Querformat (Standard)",
                       variable=self.orientation_var, value="landscape",
                       bg="#1e1e2e", fg="#cdd6f4", selectcolor="#313244",
                       activebackground="#1e1e2e",
                       font=("Segoe UI", 11)
                       ).pack(side="left", padx=(0, 16))
        tk.Radiobutton(orient_frame, text="Hochformat",
                       variable=self.orientation_var, value="portrait",
                       bg="#1e1e2e", fg="#cdd6f4", selectcolor="#313244",
                       activebackground="#1e1e2e",
                       font=("Segoe UI", 11)
                       ).pack(side="left")

        # Monitore
        self.monitor_count_var = tk.IntVar(value=self.data.get("monitor_count", 2))
        lbl(6, "Anzahl angeschlossener Bildschirme:")
        tk.Spinbox(content, from_=1, to=4,
                   textvariable=self.monitor_count_var,
                   bg="#313244", fg="#cdd6f4",
                   insertbackground="#cdd6f4",
                   buttonbackground="#45475a",
                   relief="flat",
                   font=("Segoe UI", 12), width=8
                   ).grid(row=6, column=1, sticky="ew", pady=8)

        sep(7)

        tk.Label(content,
                 text="Reihenfolge: Temperaturen → Bild 1 → Temperaturen → Bild 2 → ...",
                 bg="#1e1e2e", fg="#6c7086",
                 font=("Segoe UI", 10, "italic")).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # Buttons
        btn_row = tk.Frame(content, bg="#1e1e2e")
        btn_row.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        tk.Button(btn_row,
                  text="📁  Assets-Ordner öffnen",
                  bg="#45475a", fg="#cdd6f4",
                  relief="flat", font=("Segoe UI", 11),
                  padx=12, pady=6,
                  command=lambda: os.startfile(ASSETS_DIR) if sys.platform == "win32"
                  else subprocess.run(["xdg-open", ASSETS_DIR])
                  ).pack(side="left", padx=(0, 8))

        tk.Button(btn_row,
                  text="✓  Einstellungen speichern",
                  bg="#89b4fa", fg="#1e1e2e",
                  relief="flat", font=("Segoe UI", 12, "bold"),
                  padx=16, pady=8,
                  command=self._save_settings
                  ).pack(side="left")

    def _save_settings(self):
        self.data = load_data()
        self.data["show_temp_interval"] = self.temp_interval_var.get()
        self.data["slideshow_interval"] = self.slide_interval_var.get()
        self.data["weather_interval"]   = self.weather_interval_var.get()
        self.data["show_weather"]       = self.show_weather_var.get()
        self.data["orientation"]        = self.orientation_var.get()
        self.data["monitor_count"]      = self.monitor_count_var.get()
        save_data(self.data)
        messagebox.showinfo("Gespeichert",
                            "Einstellungen gespeichert.\n"
                            "Anzeigen neu starten, damit Änderungen wirksam werden.")

    # ── E-Mail & Updates ──────────────────────────────────────────────────────

    def _build_email_tab(self):
        frame = self.tab_email
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(frame, bg="#1e1e2e", highlightthickness=0)
        sb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        inner = tk.Frame(canvas, bg="#1e1e2e")
        cw = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        content = tk.Frame(inner, bg="#1e1e2e")
        content.pack(fill="both", expand=True, padx=30, pady=20)
        content.columnconfigure(1, weight=1)

        def lbl(r, text):
            tk.Label(content, text=text,
                     bg="#1e1e2e", fg="#bac2de",
                     font=("Segoe UI", 11),
                     anchor="w").grid(row=r, column=0, sticky="w", pady=6, padx=(0, 20))

        def sep(r, title=""):
            if title:
                tk.Label(content, text=title,
                         bg="#1e1e2e", fg="#89dceb",
                         font=("Segoe UI", 13, "bold")).grid(
                    row=r, column=0, columnspan=2, sticky="w", pady=(16, 4))
            else:
                tk.Frame(content, bg="#45475a", height=1).grid(
                    row=r, column=0, columnspan=2, sticky="ew", pady=10)

        # ── E-Mail-Bereich ────────────────────────────────────────────────────
        sep(0, "📧  E-Mail-Bildimport")

        self.email_enabled_var = tk.BooleanVar(value=self.data.get("email_enabled", False))
        lbl(1, "E-Mail Import aktivieren:")
        tk.Checkbutton(content,
                       variable=self.email_enabled_var,
                       text="Postfach auf neue Bilder überwachen",
                       bg="#1e1e2e", fg="#bac2de",
                       selectcolor="#313244",
                       activebackground="#1e1e2e",
                       font=("Segoe UI", 11),
                       command=self._on_email_toggle
                       ).grid(row=1, column=1, sticky="w", pady=6)

        lbl(2, "IMAP-Server:")
        self.email_server_var = tk.StringVar(value=self.data.get("email_server", "imap.gmail.com"))
        tk.Entry(content, textvariable=self.email_server_var,
                 bg="#313244", fg="#cdd6f4",
                 insertbackground="#cdd6f4",
                 relief="flat", font=("Segoe UI", 11)
                 ).grid(row=2, column=1, sticky="ew", pady=6)

        lbl(3, "Port:")
        self.email_port_var = tk.IntVar(value=self.data.get("email_port", 993))
        tk.Spinbox(content, from_=1, to=65535,
                   textvariable=self.email_port_var,
                   bg="#313244", fg="#cdd6f4",
                   insertbackground="#cdd6f4",
                   buttonbackground="#45475a",
                   relief="flat", font=("Segoe UI", 11), width=8
                   ).grid(row=3, column=1, sticky="w", pady=6)

        lbl(4, "Benutzername (E-Mail):")
        self.email_user_var = tk.StringVar(value=self.data.get("email_user", ""))
        tk.Entry(content, textvariable=self.email_user_var,
                 bg="#313244", fg="#cdd6f4",
                 insertbackground="#cdd6f4",
                 relief="flat", font=("Segoe UI", 11)
                 ).grid(row=4, column=1, sticky="ew", pady=6)

        lbl(5, "Passwort:")
        self.email_pw_var = tk.StringVar(value=self.data.get("email_password", ""))
        tk.Entry(content, textvariable=self.email_pw_var,
                 show="*",
                 bg="#313244", fg="#cdd6f4",
                 insertbackground="#cdd6f4",
                 relief="flat", font=("Segoe UI", 11)
                 ).grid(row=5, column=1, sticky="ew", pady=6)

        lbl(6, "Ordner (IMAP-Postfach):")
        self.email_folder_var = tk.StringVar(value=self.data.get("email_folder", "INBOX"))
        tk.Entry(content, textvariable=self.email_folder_var,
                 bg="#313244", fg="#cdd6f4",
                 insertbackground="#cdd6f4",
                 relief="flat", font=("Segoe UI", 11)
                 ).grid(row=6, column=1, sticky="ew", pady=6)

        lbl(7, "Prüf-Intervall (Minuten):")
        self.email_interval_var = tk.IntVar(value=self.data.get("email_check_interval", 5))
        tk.Spinbox(content, from_=1, to=60,
                   textvariable=self.email_interval_var,
                   bg="#313244", fg="#cdd6f4",
                   insertbackground="#cdd6f4",
                   buttonbackground="#45475a",
                   relief="flat", font=("Segoe UI", 11), width=8
                   ).grid(row=7, column=1, sticky="w", pady=6)

        email_btn_row = tk.Frame(content, bg="#1e1e2e")
        email_btn_row.grid(row=8, column=0, columnspan=2, sticky="w", pady=8)

        tk.Button(email_btn_row, text="🔗  Verbindung testen",
                  bg="#45475a", fg="#cdd6f4",
                  relief="flat", font=("Segoe UI", 11),
                  padx=12, pady=6,
                  command=self._test_email_connection
                  ).pack(side="left", padx=(0, 8))

        tk.Button(email_btn_row, text="📧  Jetzt prüfen",
                  bg="#45475a", fg="#cdd6f4",
                  relief="flat", font=("Segoe UI", 11),
                  padx=12, pady=6,
                  command=self._check_email_now
                  ).pack(side="left", padx=(0, 8))

        tk.Button(email_btn_row, text="✓  E-Mail-Einstellungen speichern",
                  bg="#89b4fa", fg="#1e1e2e",
                  relief="flat", font=("Segoe UI", 11, "bold"),
                  padx=12, pady=6,
                  command=self._save_email_settings
                  ).pack(side="left")

        self.email_status_lbl = tk.Label(content, text="",
                 bg="#1e1e2e", fg="#6c7086",
                 font=("Segoe UI", 10))
        self.email_status_lbl.grid(row=9, column=0, columnspan=2, sticky="w", pady=4)

        tk.Label(content,
                 text="💡 Tipp für Gmail: Unter Konto-Einstellungen → Sicherheit ein App-Passwort erstellen.",
                 bg="#1e1e2e", fg="#6c7086",
                 font=("Segoe UI", 9, "italic"),
                 wraplength=500, justify="left").grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(0, 8))

        sep(11)

        # ── Update-Bereich ────────────────────────────────────────────────────
        sep(12, "🔄  Update-Funktion")

        tk.Label(content,
                 text=f"Aktuelle Version:  {APP_VERSION}",
                 bg="#1e1e2e", fg="#a6e3a1",
                 font=("Segoe UI", 12, "bold")).grid(
            row=13, column=0, columnspan=2, sticky="w", pady=(4, 8))

        lbl(14, "Update-URL (GitHub Releases API):")
        self.update_url_var = tk.StringVar(value=self.data.get("update_url", ""))
        tk.Entry(content, textvariable=self.update_url_var,
                 bg="#313244", fg="#cdd6f4",
                 insertbackground="#cdd6f4",
                 relief="flat", font=("Segoe UI", 10)
                 ).grid(row=14, column=1, sticky="ew", pady=6)

        tk.Label(content,
                 text="Beispiel: https://api.github.com/repos/NUTZER/REPO/releases/latest",
                 bg="#1e1e2e", fg="#6c7086",
                 font=("Segoe UI", 9, "italic")).grid(
            row=15, column=0, columnspan=2, sticky="w", pady=(0, 8))

        update_btn_row = tk.Frame(content, bg="#1e1e2e")
        update_btn_row.grid(row=16, column=0, columnspan=2, sticky="w", pady=8)

        tk.Button(update_btn_row, text="💾  URL speichern",
                  bg="#45475a", fg="#cdd6f4",
                  relief="flat", font=("Segoe UI", 11),
                  padx=12, pady=6,
                  command=self._save_update_url
                  ).pack(side="left", padx=(0, 8))

        tk.Button(update_btn_row, text="🔍  Nach Updates suchen",
                  bg="#a6e3a1", fg="#1e1e2e",
                  relief="flat", font=("Segoe UI", 11, "bold"),
                  padx=12, pady=6,
                  command=self._check_for_updates
                  ).pack(side="left")

        self.update_status_lbl = tk.Label(content, text="",
                 bg="#1e1e2e", fg="#6c7086",
                 font=("Segoe UI", 10))
        self.update_status_lbl.grid(row=17, column=0, columnspan=2, sticky="w", pady=4)

    # ── E-Mail-Logik ──────────────────────────────────────────────────────────

    def _save_email_settings(self):
        self.data = load_data()
        self.data["email_enabled"]        = self.email_enabled_var.get()
        self.data["email_server"]         = self.email_server_var.get().strip()
        self.data["email_port"]           = self.email_port_var.get()
        self.data["email_user"]           = self.email_user_var.get().strip()
        self.data["email_password"]       = self.email_pw_var.get()
        self.data["email_folder"]         = self.email_folder_var.get().strip() or "INBOX"
        self.data["email_check_interval"] = self.email_interval_var.get()
        save_data(self.data)
        self.email_status_lbl.config(text="✓  Einstellungen gespeichert.", fg="#a6e3a1")
        self._restart_email_monitor()

    def _on_email_toggle(self):
        if self.email_enabled_var.get():
            self._save_email_settings()
        else:
            self._stop_email_monitor()
            self._save_email_settings()

    def _test_email_connection(self):
        self.email_status_lbl.config(text="Verbinde...", fg="#f9e2af")
        self.root.update_idletasks()
        threading.Thread(target=self._do_email_test, daemon=True).start()

    def _do_email_test(self):
        import imaplib
        server = self.email_server_var.get().strip()
        port   = self.email_port_var.get()
        user   = self.email_user_var.get().strip()
        pw     = self.email_pw_var.get()
        folder = self.email_folder_var.get().strip() or "INBOX"
        try:
            with imaplib.IMAP4_SSL(server, port) as imap:
                imap.login(user, pw)
                imap.select(folder)
                typ, msgs = imap.search(None, "UNSEEN")
                count = len(msgs[0].split()) if msgs[0] else 0
            self.root.after(0, lambda c=count: self.email_status_lbl.config(
                text=f"✓  Verbindung OK  ·  {c} ungelesene Nachricht(en) in '{folder}'",
                fg="#a6e3a1"))
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.email_status_lbl.config(
                text=f"✕  Fehler: {err}", fg="#f38ba8"))

    def _check_email_now(self):
        self.email_status_lbl.config(text="Prüfe Postfach...", fg="#f9e2af")
        self.root.update_idletasks()
        threading.Thread(target=self._do_email_check, daemon=True).start()

    def _start_email_if_enabled(self):
        if self.data.get("email_enabled", False):
            self._start_email_monitor()

    def _start_email_monitor(self):
        if self._email_running:
            return
        self._email_running = True
        threading.Thread(target=self._email_reader, daemon=True).start()

    def _stop_email_monitor(self):
        self._email_running = False

    def _restart_email_monitor(self):
        self._stop_email_monitor()
        time.sleep(0.2)
        if self.data.get("email_enabled", False):
            self._start_email_monitor()

    def _email_reader(self):
        while self._email_running:
            d = load_data()
            if not d.get("email_enabled", False):
                time.sleep(30)
                continue
            interval = max(1, int(d.get("email_check_interval", 5)))
            self._do_email_check()
            for _ in range(interval * 60):
                if not self._email_running:
                    return
                time.sleep(1)

    def _do_email_check(self):
        import imaplib
        import email as email_lib
        import email.header
        import tempfile
        import socket

        d      = load_data()
        server = d.get("email_server", "")
        port   = int(d.get("email_port", 993))
        user   = d.get("email_user", "")
        pw     = d.get("email_password", "")
        folder = d.get("email_folder", "INBOX")

        if not server or not user or not pw:
            return

        # Globalen Socket-Timeout für langsame Verbindungen erhöhen
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(60)

        pending = []  # [(sender, filename, tmp_path)] – erst sammeln, dann anzeigen

        try:
            imap = imaplib.IMAP4_SSL(server, port)
            imap.login(user, pw)
            imap.select(folder)

            # ALLE Mails prüfen, nicht nur ungelesene
            typ, msgs = imap.search(None, "ALL")
            if typ != "OK" or not msgs[0]:
                imap.logout()
                return

            to_delete = []

            for msg_id in msgs[0].split():
                typ, data = imap.fetch(msg_id, "(RFC822)")
                if typ != "OK":
                    continue

                msg    = email_lib.message_from_bytes(data[0][1])
                sender = msg.get("From", "Unbekannt")
                has_image = False

                for part in msg.walk():
                    ct = part.get_content_type()
                    is_image = ct.startswith("image/")
                    is_pdf   = ct == "application/pdf"
                    if not is_image and not is_pdf:
                        continue

                    raw_name = part.get_filename()
                    if not raw_name:
                        raw_name = "email_bild.pdf" if is_pdf else f"email_bild.{ct.split('/')[-1]}"

                    decoded = email_lib.header.decode_header(raw_name)[0]
                    if isinstance(decoded[0], bytes):
                        filename = decoded[0].decode(decoded[1] or "utf-8", errors="replace")
                    else:
                        filename = decoded[0]

                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue

                    tmp_path = os.path.join(tempfile.gettempdir(), filename)
                    with open(tmp_path, "wb") as f:
                        f.write(payload)

                    if is_pdf:
                        # Jede PDF-Seite als PNG-Bild extrahieren
                        for pg_sender, pg_name, pg_path in self._pdf_to_images(
                                tmp_path, filename, sender):
                            pending.append((pg_sender, pg_name, pg_path))
                    else:
                        pending.append((sender, filename, tmp_path))
                    has_image = True

                if has_image:
                    to_delete.append(msg_id)

            # Mails vom Server löschen
            for msg_id in to_delete:
                try:
                    imap.store(msg_id, "+FLAGS", "\\Deleted")
                except Exception:
                    pass
            if to_delete:
                imap.expunge()

            imap.logout()

        except Exception as e:
            print(f"[EMAIL] Fehler: {e}")
            self.root.after(0, lambda err=str(e): self.email_status_lbl.config(
                text=f"✕  Fehler: {err[:80]}", fg="#f38ba8"))
        finally:
            socket.setdefaulttimeout(old_timeout)

        # Bestätigungs-Popups sequenziell im Hauptthread zeigen
        if pending:
            self.root.after(0, lambda: self._next_email_confirm(pending))

    def _next_email_confirm(self, queue):
        if not queue:
            return
        sender, filename, tmp_path = queue[0]
        self._confirm_email_image(sender, filename, tmp_path)
        # Nach dem Schließen des Dialogs nächstes Bild zeigen
        self.root.after(200, lambda: self._next_email_confirm(queue[1:]))

    def _pdf_to_images(self, pdf_path, pdf_filename, sender):
        """Konvertiert jede PDF-Seite in eine PNG-Datei. Gibt Liste von (sender, name, path) zurück."""
        import tempfile
        results = []
        try:
            import fitz  # PyMuPDF
        except ImportError:
            print("[EMAIL] PyMuPDF nicht installiert – PDF wird übersprungen. "
                  "Bitte 'pip install PyMuPDF' ausführen.")
            return results

        try:
            doc  = fitz.open(pdf_path)
            base = os.path.splitext(pdf_filename)[0]
            mat  = fitz.Matrix(2.0, 2.0)  # 2× Zoom → ca. 144 dpi

            for page_num in range(len(doc)):
                page = doc[page_num]
                pix  = page.get_pixmap(matrix=mat, alpha=False)
                if len(doc) == 1:
                    out_name = f"{base}.png"
                else:
                    out_name = f"{base}_Seite{page_num + 1}.png"
                out_path = os.path.join(tempfile.gettempdir(), out_name)
                pix.save(out_path)
                results.append((sender, out_name, out_path))
            doc.close()
        except Exception as e:
            print(f"[EMAIL] PDF-Konvertierung fehlgeschlagen: {e}")
        return results

    def _confirm_email_image(self, sender, filename, tmp_path):
        dialog = tk.Toplevel(self.root)
        dialog.title("Neues Bild per E-Mail")
        dialog.configure(bg="#1e1e2e")
        dialog.grab_set()
        dialog.transient(self.root)
        dialog.resizable(True, True)

        # Bildvorschau
        try:
            img = Image.open(tmp_path)
            img.thumbnail((480, 340), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            img_lbl = tk.Label(dialog, image=photo, bg="#1e1e2e")
            img_lbl.image = photo
            img_lbl.pack(padx=20, pady=(20, 8))
            dim_text = f"{img.width}×{img.height} px  ·  {os.path.splitext(filename)[1].upper()}"
        except Exception:
            tk.Label(dialog, text="[Vorschau nicht verfügbar]",
                     bg="#313244", fg="#6c7086",
                     font=("Segoe UI", 12),
                     width=40, height=8).pack(padx=20, pady=(20, 8))
            dim_text = ""

        # Absender-Info
        info = tk.Frame(dialog, bg="#313244")
        info.pack(fill="x", padx=20, pady=4)
        tk.Label(info, text=f"Von:    {sender}",
                 bg="#313244", fg="#cdd6f4",
                 font=("Segoe UI", 11), anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(info, text=f"Datei:  {filename}",
                 bg="#313244", fg="#89b4fa",
                 font=("Segoe UI", 11), anchor="w").pack(fill="x", padx=12, pady=(2, 2))
        if dim_text:
            tk.Label(info, text=dim_text,
                     bg="#313244", fg="#6c7086",
                     font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=12, pady=(0, 8))

        tk.Label(dialog, text="Dieses Bild zur Slideshow hinzufügen?",
                 bg="#1e1e2e", fg="#cdd6f4",
                 font=("Segoe UI", 12, "bold")).pack(pady=(12, 6))

        result = [False]

        def yes():
            result[0] = True
            dialog.destroy()

        def no():
            dialog.destroy()

        btn_row = tk.Frame(dialog, bg="#1e1e2e")
        btn_row.pack(pady=(0, 20))
        tk.Button(btn_row, text="✓  Ja, hinzufügen",
                  bg="#a6e3a1", fg="#1e1e2e",
                  font=("Segoe UI", 12, "bold"),
                  relief="flat", padx=16, pady=8,
                  command=yes).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="✕  Ablehnen",
                  bg="#f38ba8", fg="#1e1e2e",
                  font=("Segoe UI", 12, "bold"),
                  relief="flat", padx=16, pady=8,
                  command=no).pack(side="left")

        dialog.wait_window()

        if not result[0]:
            return

        dest_name = filename
        dest = os.path.join(ASSETS_DIR, dest_name)
        base, ext = os.path.splitext(dest_name)
        counter = 1
        while os.path.exists(dest):
            dest_name = f"{base}_{counter}{ext}"
            dest = os.path.join(ASSETS_DIR, dest_name)
            counter += 1

        try:
            shutil.copy2(tmp_path, dest)
        except Exception as e:
            messagebox.showerror("Fehler", f"Datei konnte nicht gespeichert werden:\n{e}")
            return

        self.data = load_data()
        self.data["slides"].append({
            "filename": dest_name,
            "caption":  f"Per E-Mail von {sender}",
            "type":     "image"
        })
        save_data(self.data)
        self._render_slides_list()
        messagebox.showinfo("Hinzugefügt",
                            f"'{dest_name}' wurde zur Slideshow hinzugefügt.")

    # ── Update-Logik ──────────────────────────────────────────────────────────

    def _save_update_url(self):
        self.data = load_data()
        self.data["update_url"] = self.update_url_var.get().strip()
        save_data(self.data)
        self.update_status_lbl.config(text="✓  URL gespeichert.", fg="#a6e3a1")

    def _check_for_updates(self):
        url = self.update_url_var.get().strip()
        if not url:
            messagebox.showwarning("Keine URL",
                                   "Bitte erst eine Update-URL eingeben und speichern.")
            return
        self.update_status_lbl.config(text="Prüfe auf Updates...", fg="#f9e2af")
        self.root.update_idletasks()
        threading.Thread(target=self._do_update_check, args=(url,), daemon=True).start()

    def _do_update_check(self, url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BadeseeAnzeigetafel"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            remote_version = data.get("tag_name", data.get("version", "")).lstrip("v")
            fallback_url   = data.get("html_url", data.get("download_url", url))

            if not remote_version:
                self.root.after(0, lambda: self.update_status_lbl.config(
                    text="✕  Keine Versionsinformation gefunden.", fg="#f38ba8"))
                return

            def _vt(v):
                try:
                    return tuple(int(x) for x in v.split("."))
                except Exception:
                    return (0,)

            if _vt(remote_version) <= _vt(APP_VERSION):
                self.root.after(0, lambda rv=remote_version: self.update_status_lbl.config(
                    text=f"✓  Aktuell  ·  Neueste Version: v{rv}", fg="#a6e3a1"))
                return

            # Neue Version gefunden – EXE-Assets aus dem Release suchen
            exe_assets = [
                (a["name"], a["browser_download_url"])
                for a in data.get("assets", [])
                if a.get("name", "").lower().endswith(".exe")
            ]

            self.root.after(0, lambda rv=remote_version, fu=fallback_url, ea=exe_assets:
                self._show_update_dialog(rv, fu, ea))

        except Exception as e:
            self.root.after(0, lambda err=str(e): self.update_status_lbl.config(
                text=f"✕  Fehler: {err[:80]}", fg="#f38ba8"))

    def _show_update_dialog(self, remote_version, fallback_url, exe_assets):
        self.update_status_lbl.config(
            text=f"⬆  Neue Version: v{remote_version}", fg="#f9e2af")

        is_exe = getattr(sys, "frozen", False)
        if is_exe and exe_assets:
            names = "\n".join(f"  • {n}" for n, _ in exe_assets)
            answer = messagebox.askyesno(
                "Update verfügbar",
                f"Neue Version: v{remote_version}  (aktuell: v{APP_VERSION})\n\n"
                f"Folgende Dateien werden heruntergeladen:\n{names}\n\n"
                f"Automatisch herunterladen und installieren?"
            )
            if answer:
                self._start_auto_update(exe_assets)
        else:
            messagebox.showinfo(
                "Update verfügbar",
                f"Neue Version: v{remote_version}  (aktuell: v{APP_VERSION})\n\n"
                f"Download: {fallback_url}\n\n"
                f"EXE-Dateien manuell ersetzen und App neu starten."
            )

    def _start_auto_update(self, exe_assets):
        # Fortschritts-Dialog
        prog = tk.Toplevel(self.root)
        prog.title("Update wird heruntergeladen …")
        prog.geometry("420x160")
        prog.configure(bg="#1e1e2e")
        prog.grab_set()
        prog.transient(self.root)
        prog.resizable(False, False)

        status_lbl = tk.Label(prog, text="Vorbereitung …",
                              bg="#1e1e2e", fg="#cdd6f4",
                              font=("Segoe UI", 12, "bold"))
        status_lbl.pack(pady=(28, 6), padx=20)

        detail_lbl = tk.Label(prog, text="",
                              bg="#1e1e2e", fg="#6c7086",
                              font=("Segoe UI", 10))
        detail_lbl.pack()

        app_dir = os.path.dirname(sys.executable)

        def download_thread():
            downloaded = []
            try:
                for idx, (name, dl_url) in enumerate(exe_assets):
                    prog.after(0, lambda n=name, i=idx, t=len(exe_assets):
                        status_lbl.config(text=f"({i+1}/{t})  {n}"))

                    new_path = os.path.join(app_dir, name + ".new")

                    # Bis zu 3 Versuche bei langsamer/instabiler Verbindung
                    last_err = None
                    for attempt in range(3):
                        try:
                            if attempt > 0:
                                prog.after(0, lambda a=attempt:
                                    detail_lbl.config(text=f"Versuch {a+1}/3 …"))
                                time.sleep(5)

                            req = urllib.request.Request(
                                dl_url, headers={"User-Agent": "BadeseeAnzeigetafel"})
                            # timeout=300: 5 Minuten pro Daten-Paket – für sehr langsame Verbindungen
                            with urllib.request.urlopen(req, timeout=300) as resp:
                                total = int(resp.headers.get("Content-Length", 0))
                                done  = 0
                                with open(new_path, "wb") as f:
                                    while True:
                                        chunk = resp.read(8192)  # kleinere Chunks für langsame Leitungen
                                        if not chunk:
                                            break
                                        f.write(chunk)
                                        done += len(chunk)
                                        if total:
                                            pct = done * 100 // total
                                            mb  = done / 1_048_576
                                            prog.after(0, lambda p=pct, m=mb:
                                                detail_lbl.config(text=f"{m:.1f} MB  ({p}%)"))
                            last_err = None
                            break  # Erfolg
                        except Exception as e:
                            last_err = e

                    if last_err:
                        raise last_err

                    # Integritätsprüfung: Windows-EXE beginnt mit "MZ"
                    with open(new_path, "rb") as f:
                        header = f.read(2)
                    if header != b"MZ":
                        raise ValueError(
                            f"{name}: Heruntergeladene Datei ist keine gültige EXE "
                            f"(Header: {header!r}). Bitte Upload auf GitHub prüfen.")

                    downloaded.append((name, new_path))

                # Update-Batch schreiben
                # Wartet aktiv bis beide Prozesse wirklich beendet sind,
                # dann noch 4 Sekunden für PyInstaller _MEI-Ordner-Cleanup
                bat_path = os.path.join(app_dir, "badesee_update.bat")
                steuerung = os.path.join(app_dir, "Badesee_Steuerung.exe")
                lines = [
                    "@echo off",
                    "echo Warte auf Prozessende...",
                    # Warte bis Badesee_Steuerung.exe nicht mehr laeuft
                    ":wait_steuerung",
                    'tasklist /fi "imagename eq Badesee_Steuerung.exe" 2>nul'
                    ' | find /i "Badesee_Steuerung.exe" >nul',
                    "if not errorlevel 1 (",
                    "    timeout /t 1 /nobreak > nul",
                    "    goto wait_steuerung",
                    ")",
                    # Warte bis Badesee_Anzeige.exe nicht mehr laeuft
                    ":wait_anzeige",
                    'tasklist /fi "imagename eq Badesee_Anzeige.exe" 2>nul'
                    ' | find /i "Badesee_Anzeige.exe" >nul',
                    "if not errorlevel 1 (",
                    "    timeout /t 1 /nobreak > nul",
                    "    goto wait_anzeige",
                    ")",
                    # Extra-Puffer fuer PyInstaller _MEI-Ordner-Cleanup
                    "timeout /t 4 /nobreak > nul",
                ]
                for name, new_path in downloaded:
                    orig = os.path.join(app_dir, name)
                    lines.append(f'move /y "{new_path}" "{orig}"')
                lines.append(f'start "" "{steuerung}"')
                lines.append('del "%~f0"')
                with open(bat_path, "w", encoding="cp1252") as f:
                    f.write("\r\n".join(lines))

                prog.after(0, lambda bp=bat_path: self._finish_auto_update(prog, bp))

            except Exception as e:
                prog.after(0, lambda err=str(e): (
                    status_lbl.config(text="Fehler beim Download", fg="#f38ba8"),
                    detail_lbl.config(text=err[:80])
                ))

        threading.Thread(target=download_thread, daemon=True).start()

    def _finish_auto_update(self, prog_dialog, bat_path):
        prog_dialog.destroy()
        if messagebox.askyesno(
            "Update bereit",
            "Download abgeschlossen!\n\n"
            "Die App wird jetzt beendet, das Update installiert\n"
            "und danach automatisch neu gestartet.\n\n"
            "Jetzt installieren?"
        ):
            self._stop_displays()
            subprocess.Popen(bat_path, shell=True,
                             creationflags=subprocess.CREATE_NO_WINDOW
                             if sys.platform == "win32" else 0)
            self.root.after(600, self.root.destroy)

    # ── Display starten/stoppen ───────────────────────────────────────────────

    def _enumerate_monitors(self):
        try:
            import screeninfo
            return [(m.x, m.y, m.width, m.height) for m in screeninfo.get_monitors()]
        except ImportError:
            pass
        try:
            import ctypes
            import ctypes.wintypes
            monitors = []
            MONITORENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_ulong, ctypes.c_ulong,
                ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_double)
            def _cb(hMon, hdc, rect, data):
                r = rect.contents
                monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
                return True
            ctypes.windll.user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
            if monitors:
                return monitors
        except Exception as e:
            print(f"[DEBUG] ctypes Fehler: {e}")
        return [(0, 0, 1920, 1080)]

    def _get_display_monitor_indices(self):
        monitors = self._enumerate_monitors()
        print(f"[DEBUG] {len(monitors)} Monitor(e) gefunden:")
        for i, (mx, my, mw, mh) in enumerate(monitors):
            print(f"  Monitor {i}: x={mx}, y={my}, {mw}x{mh}")
        if len(monitors) <= 1:
            print("[DEBUG] Nur 1 Monitor – starte auf Monitor 0")
            return [0]
        self.root.update_idletasks()
        wx = self.root.winfo_rootx()
        wy = self.root.winfo_rooty()
        print(f"[DEBUG] Bedienoberfläche Position: x={wx}, y={wy}")
        control_idx = 0
        for i, (mx, my, mw, mh) in enumerate(monitors):
            if mx <= wx < mx + mw and my <= wy < my + mh:
                control_idx = i
                break
        print(f"[DEBUG] Bedienoberfläche läuft auf Monitor {control_idx}")
        result = [i for i in range(len(monitors)) if i != control_idx]
        print(f"[DEBUG] Anzeigen werden gestartet auf Monitoren: {result}")
        return result

    def _launch_displays(self):
        self._stop_displays()
        indices = self._get_display_monitor_indices()

        if getattr(sys, "frozen", False):
            anzeige_exe = os.path.join(os.path.dirname(sys.executable),
                                       "Badesee_Anzeige.exe")
            def make_cmd(i): return [anzeige_exe, str(i)]
        else:
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "display.py")
            def make_cmd(i): return [sys.executable, script, str(i)]

        for i in indices:
            try:
                proc = subprocess.Popen(
                    make_cmd(i),
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                )
                self.display_processes.append(proc)
                print(f"[DEBUG] Prozess für Monitor {i} gestartet (PID {proc.pid})")
            except Exception as e:
                messagebox.showerror("Fehler",
                                     f"Anzeige {i+1} konnte nicht gestartet werden:\n{e}")

    def _stop_displays(self):
        for proc in self.display_processes:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        capture_output=True, timeout=5
                    )
                else:
                    proc.terminate()
            except Exception as e:
                print(f"[DEBUG] Beenden Fehler: {e}")
        self.display_processes.clear()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _refresh_ui(self):
        d = load_data()
        self.data = d

        wt = d.get("wasser_temp", "--")
        lt = d.get("luft_temp", "--")
        self.wasser_display.config(text=f"{wt}°C")
        self.luft_display.config(text=f"{lt}°C")

        upd = d.get("last_updated", "")
        if upd:
            try:
                t = datetime.fromisoformat(upd)
                self.updated_display.config(
                    text=f"Zuletzt aktualisiert: {t.strftime('%d.%m.%Y %H:%M Uhr')}")
            except Exception:
                pass

        self._refresh_log_table()
        self.root.after(5000, self._refresh_ui)


def main():
    root = tk.Tk()
    app = ControlPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
