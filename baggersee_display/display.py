"""
Badesee Anzeigetafel - Display Fenster
Zeigt Wasser- und Lufttemperatur, Bilder/QR-Codes und Wetter im Vollbild an.
"""

import tkinter as tk
import json
import os
import sys
import threading
import urllib.request
from datetime import datetime
from PIL import Image, ImageTk

_BASE = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
         else os.path.dirname(os.path.abspath(__file__)))
DATA_FILE  = os.path.join(_BASE, "data.json")
ASSETS_DIR = os.path.join(_BASE, "assets")

DAYS_DE   = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]
MONTHS_DE = ["Januar","Februar","März","April","Mai","Juni",
             "Juli","August","September","Oktober","November","Dezember"]

WEATHER_CODES = {
    0:  ("Sonnig",                "☀️"),
    1:  ("Überwiegend klar",      "🌤"),
    2:  ("Teilweise bewölkt",     "⛅"),
    3:  ("Bedeckt",               "☁️"),
    45: ("Nebel",                 "🌫"),
    48: ("Nebel",                 "🌫"),
    51: ("Leichter Nieselregen",  "🌦"),
    53: ("Nieselregen",           "🌦"),
    55: ("Starker Nieselregen",   "🌧"),
    61: ("Leichter Regen",        "🌧"),
    63: ("Regen",                 "🌧"),
    65: ("Starker Regen",         "🌧"),
    71: ("Leichter Schnee",       "🌨"),
    73: ("Schnee",                "❄️"),
    75: ("Starker Schnee",        "❄️"),
    80: ("Regenschauer",          "🌦"),
    81: ("Schauer",               "🌧"),
    82: ("Starke Schauer",        "⛈"),
    95: ("Gewitter",              "⛈"),
    96: ("Gewitter mit Hagel",    "⛈"),
    99: ("Schweres Gewitter",     "⛈"),
}

DEFAULT_DATA = {
    "wasser_temp": "--",
    "luft_temp": "--",
    "slideshow_interval": 10,
    "show_temp_interval": 15,
    "weather_interval": 20,
    "show_weather": True,
    "orientation": "landscape",
    "slides": [],
    "last_updated": "",
}


def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                for k, v in DEFAULT_DATA.items():
                    if k not in d:
                        d[k] = v
                return d
    except Exception:
        pass
    return dict(DEFAULT_DATA)


def _weather_info(code):
    for c in sorted(WEATHER_CODES.keys(), reverse=True):
        if code >= c:
            return WEATHER_CODES[c]
    return ("Unbekannt", "🌡️")


class DisplayApp:
    def __init__(self, root, monitor_index=0):
        self.root = root
        self.root.title("Badesee Anzeigetafel")

        screens = self._get_screens()
        print(f"[DISPLAY {monitor_index}] Screens: {screens}")
        if monitor_index < len(screens):
            x, y, w, h = screens[monitor_index]
        else:
            x, y = 0, 0
            w = self.root.winfo_screenwidth()
            h = self.root.winfo_screenheight()
            print(f"[DISPLAY {monitor_index}] Fallback")

        self.screen_w, self.screen_h = w, h

        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.update_idletasks()
        self.root.overrideredirect(True)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.update_idletasks()
        print(f"[DISPLAY {monitor_index}] bei x={self.root.winfo_rootx()}, y={self.root.winfo_rooty()}")

        self.data             = load_data()
        self.current_item_idx = 0
        self.current_mode     = "temp"
        self.slide_images     = {}
        self.after_id         = None
        self.weather_data     = {}

        self._build_ui()
        self._start_weather_fetch()
        self._start_loop()

    # ── Monitor-Erkennung ─────────────────────────────────────────────────────

    def _get_screens(self):
        try:
            import screeninfo
            return [(m.x, m.y, m.width, m.height) for m in screeninfo.get_monitors()]
        except ImportError:
            pass
        try:
            import ctypes, ctypes.wintypes
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
            print(f"[DISPLAY] ctypes Fehler: {e}")
        return [(0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())]

    # ── UI aufbauen ───────────────────────────────────────────────────────────

    def _build_ui(self):
        BG = "#000D1A"
        self.root.configure(bg=BG)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.main_frame = tk.Frame(self.root, bg=BG)
        self.main_frame.grid(row=0, column=0, sticky="nsew")
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.rowconfigure(0, weight=1)

        self._build_temp_screen()
        self._build_slide_screen()
        self._build_weather_screen()

        self.temp_frame.grid(row=0, column=0, sticky="nsew")
        self.slide_frame.grid(row=0, column=0, sticky="nsew")
        self.weather_frame.grid(row=0, column=0, sticky="nsew")
        self.temp_frame.tkraise()

    # ── Temperatur-Bildschirm ─────────────────────────────────────────────────

    def _build_temp_screen(self):
        BG      = "#000D1A"
        W_COLOR = "#00E5FF"
        L_COLOR = "#80FF40"
        DIV     = "#0A3050"
        TITLE   = "#FFFFFF"
        TIME_FG = "#7AADCC"
        FOOT_BG = "#000810"
        FOOT_FG = "#88BBCC"

        sh, sw = self.screen_h, self.screen_w
        pad = max(12, sh // 32)
        orientation = self.data.get("orientation", "landscape")

        fs_foot  = max(14, sh // 64)

        if orientation == "portrait":
            fs_title = max(20, sh // 44)
            fs_time  = max(12, sh // 72)
            fs_badge = max(14, sh // 60)
            fs_temp  = max(60, sh // 15)
            fs_unit  = max(22, sh // 36)
        else:
            fs_title = max(28, sh // 28)
            fs_time  = max(15, sh // 54)
            fs_badge = max(22, sh // 36)
            fs_temp  = max(170, sh // 4)
            fs_unit  = max(54, sh // 16)

        self.temp_frame = tk.Frame(self.main_frame, bg=BG)
        self.temp_frame.columnconfigure(0, weight=1)
        self.temp_frame.rowconfigure(0, weight=1)
        self.temp_frame.rowconfigure(1, weight=8)
        self.temp_frame.rowconfigure(2, minsize=max(32, sh // 28))

        # Header
        header = tk.Frame(self.temp_frame, bg=BG)
        header.grid(row=0, column=0, sticky="nsew")
        header.columnconfigure(0, weight=1)
        header.rowconfigure(0, weight=1)
        header.rowconfigure(1, weight=1)
        tk.Label(header, text="🏖  BADESEE  UMMENDORF",
                 bg=BG, fg=TITLE,
                 font=("Segoe UI", fs_title, "bold")).grid(row=0, column=0, sticky="s")
        self.time_label = tk.Label(header, text="",
                 bg=BG, fg=TIME_FG, font=("Segoe UI", fs_time))
        self.time_label.grid(row=1, column=0, sticky="n", pady=(4, 0))

        # Temperatur-Bereich
        temps = tk.Frame(self.temp_frame, bg=BG)
        temps.grid(row=1, column=0, sticky="nsew")

        def make_panel(icon, label_text, color):
            side = tk.Frame(temps, bg=BG)
            side.columnconfigure(0, weight=1)
            side.rowconfigure(0, weight=0)
            side.rowconfigure(1, weight=1)

            badge = tk.Frame(side, bg=BG)
            badge.grid(row=0, column=0, pady=(pad // 2, 0))
            tk.Label(badge, text=icon,
                     font=("Segoe UI", fs_badge), bg=BG, fg=color).pack(side="left")
            tk.Label(badge, text=f"  {label_text}",
                     font=("Segoe UI", fs_badge, "bold"),
                     bg=BG, fg=color).pack(side="left")

            vf = tk.Frame(side, bg=BG)
            vf.grid(row=1, column=0, sticky="nsew")
            vf.columnconfigure(0, weight=1)
            vf.rowconfigure(0, weight=1)
            num = tk.Frame(vf, bg=BG)
            num.grid(row=0, column=0)
            val = tk.Label(num, text="--", bg=BG, fg=color,
                     font=("Segoe UI", fs_temp, "bold"))
            val.pack(side="left")
            tk.Label(num, text="°C", bg=BG, fg=color,
                     font=("Segoe UI", fs_unit)).pack(
                         side="left", anchor="s", pady=(0, fs_temp // 5))
            return side, val

        if orientation == "portrait":
            temps.columnconfigure(0, weight=1)
            temps.rowconfigure(0, weight=1)
            temps.rowconfigure(1, minsize=3)
            temps.rowconfigure(2, weight=1)

            wf, self.wasser_val = make_panel("💧", "WASSERTEMPERATUR", W_COLOR)
            wf.grid(row=0, column=0, sticky="nsew", padx=pad, pady=(0, pad // 2))

            tk.Frame(temps, bg=DIV, height=3).grid(
                row=1, column=0, sticky="ew", padx=pad)

            lf, self.luft_val = make_panel("🌡️", "LUFTTEMPERATUR", L_COLOR)
            lf.grid(row=2, column=0, sticky="nsew", padx=pad, pady=(pad // 2, 0))
        else:
            temps.columnconfigure(0, weight=1)
            temps.columnconfigure(1, minsize=3)
            temps.columnconfigure(2, weight=1)
            temps.rowconfigure(0, weight=1)

            wf, self.wasser_val = make_panel("💧", "WASSERTEMPERATUR", W_COLOR)
            wf.grid(row=0, column=0, sticky="nsew", padx=(pad, pad // 2))

            tk.Frame(temps, bg=DIV, width=3).grid(
                row=0, column=1, sticky="ns", pady=pad)

            lf, self.luft_val = make_panel("🌡️", "LUFTTEMPERATUR", L_COLOR)
            lf.grid(row=0, column=2, sticky="nsew", padx=(pad // 2, pad))

        # Footer
        footer = tk.Frame(self.temp_frame, bg=FOOT_BG)
        footer.grid(row=2, column=0, sticky="nsew")
        footer.columnconfigure(0, weight=1)
        footer.rowconfigure(0, weight=1)
        self.updated_label = tk.Label(footer, text="",
                 bg=FOOT_BG, fg=FOOT_FG, font=("Segoe UI", fs_foot))
        self.updated_label.grid(row=0, column=0)

    # ── Slide-Bildschirm ──────────────────────────────────────────────────────

    def _build_slide_screen(self):
        self.slide_frame = tk.Frame(self.main_frame, bg="#000000")
        self.slide_frame.columnconfigure(0, weight=1)
        self.slide_frame.rowconfigure(0, weight=1)
        self.slide_label = tk.Label(self.slide_frame, bg="#000000")
        self.slide_label.grid(row=0, column=0, sticky="nsew")
        fs_cap = max(16, self.screen_h // 54)
        self.slide_caption = tk.Label(self.slide_frame, text="",
                 bg="#000000", fg="#ffffff", font=("Segoe UI", fs_cap))
        self.slide_caption.grid(row=1, column=0, pady=10)

    # ── Wetter-Bildschirm ─────────────────────────────────────────────────────

    def _build_weather_screen(self):
        BG      = "#000D1A"
        TITLE   = "#FFFFFF"
        TIME_FG = "#7AADCC"
        FOOT_BG = "#000810"

        sh, sw = self.screen_h, self.screen_w
        pad = max(12, sh // 30)

        fs_title  = max(22, sh // 36)
        fs_sub    = max(45, sh // 20)
        fs_icon   = max(80, sh // 10)
        fs_desc   = max(20, sh // 42)
        fs_temp   = max(55, sh // 14)
        fs_detail = max(13, sh // 70)

        self.weather_frame = tk.Frame(self.main_frame, bg=BG)
        self.weather_frame.columnconfigure(0, weight=1)
        self.weather_frame.rowconfigure(0, weight=1)
        self.weather_frame.rowconfigure(1, weight=5)
        self.weather_frame.rowconfigure(2, minsize=max(30, sh // 28))

        hdr = tk.Frame(self.weather_frame, bg=BG)
        hdr.grid(row=0, column=0, sticky="nsew")
        hdr.columnconfigure(0, weight=1)
        hdr.rowconfigure(0, weight=1)
        hdr.rowconfigure(1, weight=1)
        tk.Label(hdr, text="🏖  BADESEE  UMMENDORF",
                 bg=BG, fg=TITLE,
                 font=("Segoe UI", fs_title, "bold")).grid(row=0, column=0, sticky="s")
        tk.Label(hdr, text="Wettervorhersage für heute",
                 bg=BG, fg=TIME_FG,
                 font=("Segoe UI", fs_sub, "bold")).grid(row=1, column=0, sticky="n", pady=(4, 0))

        body = tk.Frame(self.weather_frame, bg=BG)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=2)
        body.rowconfigure(1, weight=1)
        body.rowconfigure(2, weight=1)

        self.w_icon_lbl = tk.Label(body, text="", bg=BG, fg="#FFDD00",
                 font=("Segoe UI", fs_icon))
        self.w_icon_lbl.grid(row=0, column=0)

        self.w_desc_lbl = tk.Label(body, text="", bg=BG, fg="#CCDDEE",
                 font=("Segoe UI", fs_desc, "bold"))
        self.w_desc_lbl.grid(row=1, column=0)

        temp_row = tk.Frame(body, bg=BG)
        temp_row.grid(row=2, column=0, pady=(pad // 2, 0))
        self.w_max_lbl = tk.Label(temp_row, text="",
                 bg=BG, fg="#FF7070", font=("Segoe UI", fs_temp, "bold"))
        self.w_max_lbl.pack(side="left", padx=pad * 2)
        self.w_min_lbl = tk.Label(temp_row, text="",
                 bg=BG, fg="#74B9FF", font=("Segoe UI", fs_temp, "bold"))
        self.w_min_lbl.pack(side="left", padx=pad * 2)
        self.w_rain_lbl = tk.Label(temp_row, text="",
                 bg=BG, fg="#88BBCC", font=("Segoe UI", fs_temp))
        self.w_rain_lbl.pack(side="left", padx=pad * 2)

        footer = tk.Frame(self.weather_frame, bg=FOOT_BG)
        footer.grid(row=2, column=0, sticky="nsew")
        footer.columnconfigure(0, weight=1)
        footer.rowconfigure(0, weight=1)
        self.w_updated_lbl = tk.Label(footer, text="",
                 bg=FOOT_BG, fg="#2A5A7A", font=("Segoe UI", fs_detail))
        self.w_updated_lbl.grid(row=0, column=0)

    # ── Wetter abrufen ────────────────────────────────────────────────────────

    def _start_weather_fetch(self):
        threading.Thread(target=self._fetch_weather, daemon=True).start()

    def _fetch_weather(self):
        lat, lon = 48.10, 9.93
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum"
            f"&timezone=Europe%2FBerlin&forecast_days=1"
        )
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                d = json.loads(resp.read().decode())
            daily = d["daily"]
            self.weather_data = {
                "max_temp":      daily["temperature_2m_max"][0],
                "min_temp":      daily["temperature_2m_min"][0],
                "weathercode":   daily["weathercode"][0],
                "precipitation": daily["precipitation_sum"][0],
                "fetched":       datetime.now().isoformat(),
            }
            print(f"[WEATHER] Abgerufen: {self.weather_data}")
        except Exception as e:
            print(f"[WEATHER] Fehler: {e}")
        self.root.after(30 * 60 * 1000, self._start_weather_fetch)

    # ── Anzeigelogik ──────────────────────────────────────────────────────────

    def _update_temp_display(self):
        d = self.data
        self.wasser_val.config(text=str(d.get("wasser_temp", "--")))
        self.luft_val.config(text=str(d.get("luft_temp", "--")))

        now = datetime.now()
        self.time_label.config(
            text=f"{DAYS_DE[now.weekday()]}, {now.day}. {MONTHS_DE[now.month-1]} {now.year}"
                 f"  |  {now.strftime('%H:%M')} Uhr")

        updated = d.get("last_updated", "")
        if updated:
            try:
                t = datetime.fromisoformat(updated)
                self.updated_label.config(
                    text=f"Letzte Aktualisierung: {t.strftime('%H:%M')} Uhr")
            except Exception:
                pass

    def _load_slide_image(self, path):
        if path in self.slide_images:
            return self.slide_images[path]
        try:
            img = Image.open(path)
            img.thumbnail((self.screen_w, self.screen_h - 60), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.slide_images[path] = photo
            return photo
        except Exception:
            return None

    def _show_temp(self):
        self.current_mode = "temp"
        self._update_temp_display()
        self.temp_frame.tkraise()

    def _show_slide(self, slide):
        path    = os.path.join(ASSETS_DIR, slide.get("filename", ""))
        caption = slide.get("caption", "")
        photo   = self._load_slide_image(path)
        if photo:
            self.slide_label.config(image=photo)
            self.slide_label._image = photo
        else:
            self.slide_label.config(image="", text="Bild nicht gefunden",
                                    font=("Segoe UI", 30), fg="white")
        self.slide_caption.config(text=caption)
        self.current_mode = "slide"
        self.slide_frame.tkraise()

    def _show_weather(self):
        wd   = self.weather_data
        code = int(wd.get("weathercode", 0))
        desc, icon = _weather_info(code)
        max_t = wd.get("max_temp", "--")
        min_t = wd.get("min_temp", "--")
        rain  = wd.get("precipitation", 0)

        self.w_icon_lbl.config(text=icon)
        self.w_desc_lbl.config(text=desc)
        self.w_max_lbl.config(text=f"▲ {max_t}°C")
        self.w_min_lbl.config(text=f"▼ {min_t}°C")
        self.w_rain_lbl.config(text=f"🌧 {rain} mm" if rain else "")

        fetched = wd.get("fetched", "")
        if fetched:
            try:
                t = datetime.fromisoformat(fetched)
                self.w_updated_lbl.config(
                    text=f"Stand: {t.strftime('%H:%M')} Uhr  ·  Quelle: Open-Meteo")
            except Exception:
                pass

        self.current_mode = "weather"
        self.weather_frame.tkraise()

    # ── Rotations-Loop ────────────────────────────────────────────────────────

    def _start_loop(self):
        self._tick()

    def _tick(self):
        self.data    = load_data()
        slides       = self.data.get("slides", [])
        show_weather = self.data.get("show_weather", True)
        temp_ms      = int(self.data.get("show_temp_interval", 15)) * 1000
        slide_ms     = int(self.data.get("slideshow_interval", 10)) * 1000
        weather_ms   = int(self.data.get("weather_interval", 20)) * 1000

        if self.current_mode in ("slide", "weather"):
            self._show_temp()
            self.after_id = self.root.after(temp_ms, self._tick)
            return

        items = [("slide", i) for i in range(len(slides))]
        if show_weather and self.weather_data:
            items.append(("weather", None))

        if not items:
            self._show_temp()
            self.after_id = self.root.after(temp_ms, self._tick)
            return

        if self.current_item_idx >= len(items):
            self.current_item_idx = 0

        kind, idx = items[self.current_item_idx]
        self.current_item_idx += 1

        if kind == "weather":
            self._show_weather()
            self.after_id = self.root.after(weather_ms, self._tick)
        else:
            self._show_slide(slides[idx])
            self.after_id = self.root.after(slide_ms, self._tick)

    def _cleanup(self):
        if self.after_id:
            self.root.after_cancel(self.after_id)


def main():
    monitor = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    root = tk.Tk()
    app = DisplayApp(root, monitor_index=monitor)
    root.bind("<Escape>", lambda e: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    main()
