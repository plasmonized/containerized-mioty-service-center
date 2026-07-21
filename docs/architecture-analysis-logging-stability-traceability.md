# Architektur-Analyse: Logging, Stabilität und Nachvollziehbarkeit

## Fokus
Bewertung des Projekts als IoT-Service-Center mit Schwerpunkt auf:
- Logging-Qualität
- Betriebsstabilität
- Nachvollziehbarkeit bei Verbindungsproblemen (TLS, MQTT, Web UI)

## Analysierte Kernmodule
- `main.py`
- `web_main.py`
- `TLSServer.py`
- `mqtt_interface.py`
- `web_ui.py`
- `queue_logger.py`
- `bssci_config.py`
- `docker-compose.yml`

## Stärken
- Umfangreiches Operational Logging in TLS- und MQTT-Pfaden.
- MQTT-Reconnect mit Backoff und Health-Checks implementiert.
- Metriken/Monitoring vorhanden (Deduplication, Traffic, Heartbeat, Auto-Detach).
- Queue-Transparenz über `queue_logger.py`.
- Deduplication und Topology-Tracking unterstützen Funk-/Empfangsdiagnosen.

## Risiken und Beobachtungen

### 1) Log-Overhead und Signal/Rauschen (hoch)
- In Hot Paths (Uplink/Queue) wird sehr viel auf `INFO` geloggt.
- Risiko: Performance-I/O, erschwerte Incident-Analyse, schnelle Log-Rotation.

### 2) Uneinheitliche Zeitbehandlung (hoch)
- Mehrere Zeitmodelle/Fallbacks (UTC, feste UTC+2, ZoneInfo/Fallback UTC+1).
- Risiko: fehlerhafte Korrelation zwischen Komponenten und externen Systemen.

### 3) Viele breite Exception-Handler (hoch)
- Häufig `except Exception`, teils ohne standardisierte Fehlerklassifikation.
- Risiko: schwache Root-Cause-Analyse und inkonsistente Recovery.

### 4) Nebenläufigkeitskomplexität (hoch)
- Flask-Webthread + Async-Core mit gemeinsamem Zustand (`tls_server_instance`).
- Mehrfach neue Event-Loops in Sync-Wrappern.
- Risiko: Race Conditions, schwer reproduzierbares Laufzeitverhalten.

### 5) Potenzielle Doppelpfade für MQTT-Inbound (mittel)
- `queue_watcher` und `process_mqtt_messages` verarbeiten denselben Kanaltyp.
- Risiko: doppelte/abweichende Verarbeitung je nach aktivem Pfad.

### 6) Monolithischer TLS-Server (mittel)
- `TLSServer.py` kombiniert viele Verantwortlichkeiten.
- Risiko: geringe Änderungsstabilität, erschwerte Testbarkeit.

### 7) End-to-End-Traceability nicht durchgängig standardisiert (mittel)
- Teilweise Korrelation über `opId`, aber keine konsistente Correlation-ID über alle Ebenen.
- Risiko: lange MTTR bei sporadischen Verbindungsstörungen.

## Empfohlene Maßnahmen (priorisiert)
1. Einheitliches strukturiertes Logging (JSON) mit festen Feldern (`timestamp_utc`, `component`, `event`, `op_id`, `bs_eui`, `sensor_eui`, `correlation_id`, `error_code`).
2. Log-Level-Policy definieren (Hot-Path-Details auf DEBUG, Zustandswechsel auf INFO).
3. Zeitmodell vereinheitlichen: intern UTC, Lokalisierung nur in UI.
4. Fehlerkatalog/Fehlercodes für TLS/MQTT/Queue/Attach-Flow einführen.
5. Thread-/Event-Loop-Grenzen klarziehen und Shared-State-Zugriff kapseln.
6. Inbound-Queue-Verarbeitung auf einen autoritativen Consumer konsolidieren.
7. `TLSServer.py` in klar getrennte Verantwortungsbereiche aufteilen.
8. Verbindungs-Timeline pro Base-Station/Sensor (connect/auth/attach/status/disconnect) mit Correlation-ID etablieren.

## Empfohlene Reihenfolge
1. Logging- und Zeitstandardisierung
2. Fehlerklassifikation + End-to-End-Traceability
3. Concurrency-/Queue-Härtung
4. Modulare Refaktorierung

## Ergebnis
Die Plattform ist funktional stark und observability-orientiert, aber aktuell zu noisig und in Teilen inkonsistent für schnelle, belastbare Ursachenanalyse bei komplexen Verbindungsproblemen. Die größte Hebelwirkung liegt in Standardisierung von Logs/Zeit/Fehlern und in der Entkopplung kritischer Laufzeitpfade.
