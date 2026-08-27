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

APP_VERSION = "1.0.0"

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
        self._sensor_running = False
        self._email_running  = False

        self._setup_styles()
        self._build_ui()
        self._refresh_ui()
        self._start_sensor_if_enabled()
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

        # Aktuelle Werte
        display_frame = tk.Frame(frame, bg="#313244", bd=0)
        display_frame.grid(row=0, column=0, columnspan=2, sticky="ew",
                           padx=20, pady=(20, 10))
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

        # Wasser
        wl = tk.Frame(input_frame, bg="#0d2a4a", bd=0)
        wl.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)
        tk.Label(wl, text="Wassertemperatur eingeben",
                 bg="#0d2a4a", fg="#74c7ec",
                 font=("Segoe UI", 11, "bold")).pack(pady=(14, 6), padx=16, anchor="w")

        w_entry_row = tk.Frame(wl, bg="#0d2a4a")
        w_entry_row.pack(padx=16, pady=(0, 14), fill="x")

        self.wasser_var = tk.StringVar()
        wasser_entry = tk.Entry(w_entry_row, textvariable=self.wasser_var,
                                font=("Segoe UI", 28, "bold"),
                                bg="#1a3a5c", fg="#29b6f6",
                                insertbackground="#29b6f6",
                                relief="flat", width=6,
                                justify="center")
        wasser_entry.pack(side="left")
        tk.Label(w_entry_row, text="°C", bg="#0d2a4a", fg="#4a7a9b",
                 font=("Segoe UI", 22)).pack(side="left", padx=8)

        qb_w = tk.Frame(wl, bg="#0d2a4a")
        qb_w.pack(padx=16, pady=(0, 14), fill="x")
        for delta, label in [(-0.5, "−0.5"), (+0.5, "+0.5"), (+1, "+1"), (+2, "+2")]:
            tk.Button(qb_w, text=label,
                      bg="#1a3a5c", fg="#74c7ec",
                      font=("Segoe UI", 10),
                      relief="flat", padx=8, pady=4,
                      command=lambda d=delta: self._adjust_temp("wasser", d)
                      ).pack(side="left", padx=2)

        # Luft – mit Manuell/CSV-Toggle
        ll = tk.Frame(input_frame, bg="#1a2a1a", bd=0)
        ll.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)

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

        # Manuell-Bereich
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

        # CSV-Sensor-Bereich
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

        # Speichern-Button
        save_btn = tk.Button(frame,
                             text="✓   Temperaturen speichern & anzeigen",
                             bg="#89b4fa", fg="#1e1e2e",
                             font=("Segoe UI", 13, "bold"),
                             relief="flat", padx=20, pady=12,
                             cursor="hand2",
                             command=self._save_temps)
        save_btn.grid(row=2, column=0, columnspan=2,
                      sticky="ew", padx=20, pady=16)

    # ── CSV-Sensor ────────────────────────────────────────────────────────────

    def _browse_csv(self):
        path = filedialog.askopenfilename(
            title="CSV-Datei auswählen",
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
                    else:
                        self.root.after(0, lambda: self.csv_status_lbl.config(
                            text="● Kein gültiger Temperaturwert gefunden", fg="#f9e2af"))

            except Exception as e:
                self.root.after(0, lambda err=str(e): self.csv_status_lbl.config(
                    text=f"● Fehler: {err[:60]}", fg="#f38ba8"))

            time.sleep(5)

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

        if not wt and not lt:
            messagebox.showwarning("Eingabe fehlt",
                                   "Bitte mindestens eine Temperatur eingeben.")
            return

        self.data = load_data()
        if wt:
            try:
                v = float(wt)
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

        d      = load_data()
        server = d.get("email_server", "")
        port   = int(d.get("email_port", 993))
        user   = d.get("email_user", "")
        pw     = d.get("email_password", "")
        folder = d.get("email_folder", "INBOX")

        if not server or not user or not pw:
            return

        try:
            with imaplib.IMAP4_SSL(server, port) as imap:
                imap.login(user, pw)
                imap.select(folder)
                typ, msgs = imap.search(None, "UNSEEN")
                if typ != "OK" or not msgs[0]:
                    return

                for msg_id in msgs[0].split():
                    typ, data = imap.fetch(msg_id, "(RFC822)")
                    if typ != "OK":
                        continue

                    msg    = email_lib.message_from_bytes(data[0][1])
                    sender = msg.get("From", "Unbekannt")
                    found_image = False

                    for part in msg.walk():
                        ct = part.get_content_type()
                        if not ct.startswith("image/"):
                            continue

                        raw_name = part.get_filename()
                        if not raw_name:
                            ext = ct.split("/")[-1]
                            raw_name = f"email_bild.{ext}"

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

                        found_image = True
                        self.root.after(0, lambda s=sender, fn=filename, tp=tmp_path:
                            self._confirm_email_image(s, fn, tp))

                    if found_image:
                        imap.store(msg_id, "+FLAGS", "\\Seen")

        except Exception as e:
            print(f"[EMAIL] Fehler: {e}")
            self.root.after(0, lambda err=str(e): self.email_status_lbl.config(
                text=f"✕  Fehler beim Prüfen: {err[:80]}", fg="#f38ba8"))

    def _confirm_email_image(self, sender, filename, tmp_path):
        if not messagebox.askyesno(
            "Neues Bild per E-Mail",
            f"Von: {sender}\nDatei: {filename}\n\nDieses Bild zur Slideshow hinzufügen?"
        ):
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

            # GitHub Releases API format: {"tag_name": "v1.2.0", "html_url": "..."}
            remote_version = data.get("tag_name", data.get("version", "")).lstrip("v")
            download_url   = data.get("html_url", data.get("download_url", url))

            if not remote_version:
                self.root.after(0, lambda: self.update_status_lbl.config(
                    text="✕  Keine Versionsinformation gefunden.", fg="#f38ba8"))
                return

            def _vt(v):
                try:
                    return tuple(int(x) for x in v.split("."))
                except Exception:
                    return (0,)

            if _vt(remote_version) > _vt(APP_VERSION):
                msg = (f"Neue Version verfügbar: v{remote_version}\n"
                       f"(Aktuell: v{APP_VERSION})\n\n"
                       f"Download: {download_url}\n\n"
                       f"Bitte die neue EXE herunterladen und ersetzen.")
                self.root.after(0, lambda m=msg: (
                    self.update_status_lbl.config(
                        text=f"⬆  Neue Version: v{remote_version}", fg="#f9e2af"),
                    messagebox.showinfo("Update verfügbar", m)
                ))
            else:
                self.root.after(0, lambda rv=remote_version: self.update_status_lbl.config(
                    text=f"✓  Aktuell  ·  Neueste Version: v{rv}", fg="#a6e3a1"))

        except Exception as e:
            self.root.after(0, lambda err=str(e): self.update_status_lbl.config(
                text=f"✕  Fehler: {err[:80]}", fg="#f38ba8"))

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
                proc.terminate()
            except Exception:
                pass
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

        self.root.after(5000, self._refresh_ui)


def main():
    root = tk.Tk()
    app = ControlPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
