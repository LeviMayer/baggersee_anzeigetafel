"""
Baggersee Anzeigetafel - Hauptprogramm
Startet die Bedienoberfläche. Von dort können die Anzeigebildschirme gestartet werden.
"""

import tkinter as tk
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from control import ControlPanel

if __name__ == "__main__":
    root = tk.Tk()
    app = ControlPanel(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app._stop_displays(), root.destroy()))
    root.mainloop()
