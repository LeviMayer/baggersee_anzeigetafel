# Baggersee Anzeigetafel – Installationsanleitung

## Voraussetzungen

- Windows 10/11 (oder Linux/Mac)
- Python 3.10 oder neuer → https://www.python.org/downloads/

## Installation

1. Python installieren (beim Setup "Add to PATH" aktivieren!)

2. Abhängigkeiten installieren – Eingabeaufforderung öffnen und eingeben:

   pip install -r requirements.txt

3. Programm starten:

   python main.py


## Bedienung

### Bedienoberfläche (main.py)
- Öffnet sich beim Start auf dem Haupt-PC-Bildschirm
- Tab "Temperaturen": Wasser- und Lufttemperatur eingeben und speichern
- Tab "Bilder & QR-Codes": Bilder und QR-Codes hinzufügen, sortieren, entfernen
- Tab "Einstellungen": Anzeigedauer und Anzahl Monitore festlegen
- Button "Anzeigen starten": Öffnet die Vollbild-Anzeigen auf den konfigurierten Bildschirmen

### Anzeigefenster (display.py)
- Öffnet sich im Vollbild auf dem jeweiligen Monitor
- Zeigt automatisch Temperaturen und Bilder/QR-Codes im Wechsel
- Mit ESC schließen (nur für Wartung)

### Bilder und QR-Codes
- Alle Bilder werden im Ordner "assets/" gespeichert
- Unterstützte Formate: PNG, JPG, JPEG, GIF, BMP
- QR-Codes einfach als PNG-Bild speichern (z.B. von qr-code-generator.com) und hinzufügen

### Ablauf der Anzeige
Temperaturen (15 Sek.) → Bild 1 (10 Sek.) → Temperaturen → Bild 2 → ...
(Zeiten in den Einstellungen anpassbar)

## Als .exe kompilieren (optional)

pip install pyinstaller
pyinstaller --onefile --windowed --name "Baggersee_Anzeige" main.py


## Projektstruktur

baggersee_display/
├── main.py          ← Starte dieses Programm
├── control.py       ← Bedienoberfläche
├── display.py       ← Vollbild-Anzeige (wird automatisch gestartet)
├── data.json        ← Temperaturen und Einstellungen (wird automatisch erstellt)
├── requirements.txt ← Python-Pakete
└── assets/          ← Hier kommen Bilder und QR-Codes rein
