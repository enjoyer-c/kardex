config.py:
- System & Paths: Cross-platform base directories (BASE_DIR), output folders (OUTPUT_DIR), and the inventory file (INVENTORY_FILE).
- Hardware: Defines GPIO pins (e.g., Hall sensor on pin 24) and USB camera indices/resolutions.
- Processing: Configures image stitching modes, confidence thresholds, and shelf limits (1 to 50).

camera_stiching.py


gui.py


hall_sensor.py


iventory.py





Ablauf:
# =============================================================================
# ABLAUF-LOGIK
# =============================================================================
#
# 1. IDLE
#    Tuer ist zu, System wartet. Nichts passiert.
#
# 2. Tuer oeffnet 
#    -> Zustand: TABLAR_DELIVERY
#    Tablar faehrt aus dem Regal in die Bedienposition.
#
# 3. Tuer schliesst wieder 
#    -> Zustand: BEDIENUNG 
#
# 4. QR_PRUEFEN
#    Sobald das Tablar den Trigger aus
#    Schritt 3 ausgeloest hat: QR-Code lesen -> liefert Tablar-Nummer.
#    Kein QR gefunden -> loggen (logging.error) -> erneut prüfen
#
# 5. Tür öffnet wieder
#
# 6. AUFNAHME
#    QR gefunden -> alle 4 USB-Kameras nehmen je ein Bild auf,
#    Bilder werden gestitcht, Ergebnis wird mit Zeitstempel gespeichert.
#    Pro Tablar-Nummer max. 3 gespeicherte Bilder - aeltestes wird beim
#    Ueberschreiten geloescht.
#
# 7. Tablar faehrt zurueck ins Regal
#    -> Zustand: TABLAR_FAEHRT_REIN
#    HIER erst soll das Foto gemacht werden - kurz bevor das Tablar
#    wieder im Regal verschwindet
#
# 8. zurueck zu IDLE
#
# =============================================================================


