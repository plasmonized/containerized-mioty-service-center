# BSSCI Service Center

## Overview

The BSSCI Service Center is a comprehensive IoT device management system that provides secure communication between mioty sensors, base stations, and MQTT brokers. It implements the BSSCI (Base Station Service Center Interface) protocol for managing sensor attachments, data collection, and system monitoring. The system serves as a central hub that enables secure TLS communication with base stations while providing bidirectional MQTT integration for external systems.

## User Preferences

Preferred communication style: Simple, everyday language.

After every bugfix/feature (version bump), automatically include a German changelog entry in the reply — suitable for GitHub release notes — without being asked.

## System Architecture

### Core Components

The system follows a multi-layered architecture with clear separation of concerns:

**TLS Server Layer**: Implements the BSSCI protocol for secure communication with mioty base stations using TLS encryption. Handles base station connections, sensor attachment/detachment requests, and real-time data collection. Per-BS operation ID management with negative opIds for SC-initiated operations per BSSCI convention.

**MQTT Interface Layer**: Provides bidirectional communication with external systems through MQTT topics. Publishes sensor data and base station status while subscribing to configuration updates and commands.

**Web Interface Layer**: Flask-based web application offering real-time management and monitoring capabilities. Provides dashboards for system status, sensor management, configuration, and log viewing.

**Message Processing**: Implements MessagePack-based protocol encoding/decoding with message deduplication capabilities to handle duplicate sensor data from multiple base stations.

### Data Flow Architecture

The system uses asynchronous queue-based communication between components:
- MQTT output queue for publishing sensor data and status updates
- MQTT input queue for receiving configuration changes and commands
- Real-time message processing with deduplication buffers
- Auto-detach system for sensor lifecycle management

### Certificate Management

SSL/TLS infrastructure using CA-signed certificates for secure base station authentication. Per-BS certificate generation (stored in `certs/bs_{eui}/`), auto-cert onboarding flow with ZIP download, CA management through web interface.

### Configuration Management

Environment-based configuration system supporting:
- TLS server settings (host, port, certificates)
- MQTT broker configuration (host, port, authentication)
- Sensor configuration file management
- Auto-detach timeouts and intervals
- Message deduplication parameters

### Sensor Management

JSON-based sensor configuration with support for:
- EUI-based sensor identification
- Network key management
- Short address allocation
- Bidirectional communication flags
- Dynamic attach/detach operations
- Bulk CSV/TXT import/export with flexible delimiter detection

### OMS / Wireless M-Bus Meter Support

Full EN 13757 compliant wMBUS frame parsing with:
- 120+ manufacturer database from m-bus.de, automatic 3-letter IEC code decoding
- Device type mapping and dedicated OMS management page
- Automatic wMBUS frame-start detection by scanning for valid C-field (0x44/0x46/0x48)
- Handles BSSCI/VM wrapper bytes that some base stations prepend
- Meters publish to MQTT under `ep/oms_{manufacturer}_{serial}/ul` with decoded OMS metadata
- OMS identifier format: `oms_{3-letter-code}_{serial_number}` (e.g., oms_DME_63874728)

### Variable MAC (VM) Sub-Channel

Full ETSI TS 103357 compliant VM sub-channel support for metering devices. VM response handlers identify base stations via writer connection (not opId lookup) to avoid key collisions with per-BS counters.

### User Authentication & Access Control

Three user roles - Admin (full access), User (sensor/BS management), Viewer (read-only dashboards). Login required for all pages, API endpoints protected with permission decorators. Users managed via users.json file.

## Dashboard

- Custom SVG icons (base station tower, sensor with radio waves), clickable cards, visual health indicators
- Orange/white color scheme matching mioty branding
- Online sensors count (heartbeat-based, persistent - no hourly reset), configured sensors total
- Network topology mini-preview (Cytoscape.js)
- System health: packet loss detection, base station health charts (CPU/Memory/Duty Cycle), signal score distribution
- Traffic visualization with 12-hour history, active sensor tracking, message statistics
- Sensor detail view: per-sensor SNR/RSSI statistics (min/avg/max), gateway coverage
- Coverage map with persistent floorplan storage (coverage_positions.json, coverage_floorplan.txt)

## BSSCI Protocol Details

- BS-initiated operations use positive opIds (0, 1, 2...)
- SC-initiated operations use negative opIds (-1, -2, -3...)
- Per-BS sequential opId counters, initialized on connect, cleaned up on disconnect
- Connection validity check in batch attach loop - aborts on connection loss
- 3-failure threshold for BS status requests
- Skip-attach for already-registered sensors on BS reconnect

## Recent Changes

- **v1.692 - SCACI-Release: Komplettes SC ↔ Application Center Interface**: Konsolidiertes Release aller SCACI-Features. (1) *SCACI-Interface*: MIOTYA01-Protokoll (`scaci_protocol.py`, `scaci_messages.py`), TLS-Server `SCAServer.py`, unabhängige Connector-Toggles `MQTT_ENABLED`/`SCACI_ENABLED`, ulData-Fan-out nach Deduplizierung, Web-UI-Seite `/app-centers`. (2) *AC-Zertifikate über Web-UI*: EUI-basierte Zertifikatserzeugung mit ZIP-Download (CA-Cert + Cert + Key, `certs/ac_{eui}/`), Tabelle mit Status/Gültigkeit, neue API-Endpunkte `/api/ac-certificates/*`, Nav-Link "App Centers". (3) *AC→BS-Downlink-Pfad*: `vm_send_data` mit `ac_op_id`-Korrelation; dlDataRes wird genau EINMAL an den AC gesendet — erst nach tatsächlicher BS-Bestätigung via vm.dlDataRsp. Pending-DL-Queue als Liste pro Endpunkt (keine Überschreibung mehrerer Downlinks), Sweep-Loop mit Retry (30s) und TTL (300s, rc=110). (4) *epStat-Propagation*: Online/Offline-Wechsel automatisch an alle ACs, epStat-Burst bei AC-Verbindungsaufbau. 147+ Tests grün.

- **v1.691 - epStat-Propagation an verbundene ACs**: Online/Offline-Statuswechsel von Sensoren werden jetzt automatisch per `epStat` an alle verbundenen Application Centers propagiert. Beim Verbindungsaufbau eines neuen ACs sendet der SC sofort einen `epStat`-Burst mit dem aktuellen Status aller bekannten Sensoren (aus dem Heartbeat-Tracking). Kein Warten auf den nächsten Heartbeat-Zyklus. 8 neue Tests in `test_scaci_integration.py` (148 Tests gesamt, alle grün).

- **v1.690 - SCACI Interface (SC ↔ Application Center)**: Neues MIOTYA01-Protokollmodul (`scaci_protocol.py`, `scaci_messages.py`) und TLS-Server `SCAServer.py` für die Anbindung von Application Centers. MQTT und SCACI sind unabhängig per `MQTT_ENABLED`/`SCACI_ENABLED` in der `.env` aktivierbar. ulData-Fan-out nach Deduplizierung an alle verbundenen ACs. Neue Web-UI-Seite `/app-centers` mit Echtzeit-Status. Konfigurationsseite mit Connector-Abschnitt (MQTT/SCACI-Toggles, SCACI-Port). 29 neue Tests für Codec, EUI-Konvertierung und Message-Builder. Vollständige Operationen: con/ping/reg/dereg/dlDataQue/dlDataRev (AC→SC) und status/ulData/epStat/dlDataRes (SC→AC); ulDataTx und rc.* antworten mit ENOTSUP (rc=95).

- **v1.689 - CI & Ruff: `release`-Referenzen entfernt, Markdown aus Ruff-Scope ausgeschlossen**: GitHub Actions Workflow (main.yml) referenzierte noch `release` in Branch-Filtern und docker-pr-Bedingung — auf `main` bereinigt. Ruff hat Python-Code-Blöcke in Markdown-Dateien (CONTRIBUTING.md, README.md, docs/, .agents/) geprüft und CI zum Scheitern gebracht; `.agents`, `docs`, `CONTRIBUTING.md`, `README.md` zu `extend-exclude` in pyproject.toml hinzugefügt.
- **v1.688 - Updater-Fallback branch `release` → `main`**: `get_default_branch()` in web_ui.py hat als letzten Fallback (wenn GitHub-API und git ls-remote nicht erreichbar) weiterhin `"release"` verwendet. Fallback und Docstring auf `"main"` aktualisiert.
- **v1.687 - Branch umbenannt: release → main**: Der GitHub-Hauptbranch wurde von `release` in `main` umbenannt. CONTRIBUTING.md und docs aktualisiert; Updater erkennt den Default-Branch automatisch per GitHub-API.
- **v1.686 - Local Timezone for User-Facing Timestamps**: Sensor/message timestamps in the web UI were shown 2h off (UTC instead of local). New `TLSServer._get_local_time()` uses configured TIMEZONE (bssci_config, default Europe/Berlin) for user-facing fields: registration_time, warning_sent_time, detach_time, preferredDownlinkPath.lastUpdated. sensors.html now displays the lastUpdated string directly (no `new Date()` re-parse of naive strings). `_get_utc_time()` stays UTC for internal correlation/logs.
- **v1.685 - Re-Attach on BS Reconnect (stale attach tracking fix)**: Since the SC always starts a fresh BSSCI session (snResume=False, v1.677), a reconnecting BS has forgotten all attachments — but the SC's registered_sensors records survived, so attach_file skipped sensors as "already attached" and they silently stopped working until a manual re-attach. New `_purge_bs_registrations(bs_eui)` clears the BS from all sensor records on both BS disconnect and conCmp (before attach_file), forcing a full re-attach. Note: BSSCI has no message to query a BS for its attached endpoint list, so local tracking must be invalidated instead.
- **v1.683 - CI Green (Ruff + Mypy)**: Fixed all GitHub CI failures. Ruff: background asyncio tasks now keep references (TLSServer._spawn_background_task helper + main.py task set), removed unused variables, ClassVar annotations for class-level dicts/sets, GITHUB_REPO as module constant in web_ui, ruff format applied to all files, per-file ignore for BSSCI protocol arg names (opID) in messages.py. Mypy: tests no longer reference non-existent WEB_PORT/WEB_DEBUG config attrs (repointed to STATUS_INTERVAL/AUTO_DETACH_ENABLED), typed SENSOR test fixtures, isinstance-based payload decode in mqtt_interface. Bonus: test_bssci_config now stubs load_dotenv so a local .env can't break test isolation (all 79 tests pass).
- **v1.682 - Duty Cycle Bar in Base Stations Table**: Base stations page now shows a Duty Cycle column with a 0-100% Bootstrap progress bar (green <50%, yellow <80%, red >=80%) plus numeric value. Data comes from the existing `health.duty_cycle` field (statusRsp dutyCycle * 100).
- **v1.681 - MQTT Incoming Handler Fix (register/cmd killed the listener)**: In mqtt_interface `_handle_incoming`, processing a `/register` or `/cmd` message ended with `return` instead of `continue`, terminating the incoming-message loop after the FIRST such message. Result: first sensor registered via MQTT worked, every subsequent register/cmd/config message was silently ignored until MQTT reconnected. Fixed both to `continue`. Note: the `{"registration": "received", "status": "processing"}` response seen in the broker is published by the external Home Assistant app, not by the SC (SC's ack uses `action: legacy_register`).
- **v1.680 - Version-Aware attPrp (Miromico attach error 22, real fix)**: The official BSSCI v1.1.0 spec (provided by user) revealed that attPrp changed in 1.1.0: 'bidi' was REMOVED and replaced by mandatory 'epClass' ('z'=uplink-only, 'a'=bidirectional), and 'syncBurst' became mandatory. Sending the 1.0.0 layout to a 1.1.0 BS causes error 22 "attach propagate message malformed". SC now stores each BS's protocol version from its con message and builds attPrp accordingly (1.0.0 legacy format vs 1.1.0 format). nwkSnKey stays Numeric[16] array in both versions - the v1.679 bin experiment was reverted.
- **v1.678 - ZIP Updater Copies All Python Modules**: ZIP update path previously copied only a fixed whitelist of files; newly added modules (observability.py) were imported by updated files but never copied, causing ModuleNotFoundError crash loops after update+restart. Updater now copies all *.py files from the release (except bssci_config.py which holds local settings like UPDATE_CHANNEL), plus requirements.txt, VERSION, templates/, static/.
- **v1.677 - Session Resume Fix (Miromico attach error 22)**: conRsp no longer echoes the base station's snBsUuid as snScUuid. Echoing it made strict firmwares (Miromico EdgeCard 5.1.0) treat the connection as a resumed session and expect SC opIds to continue from the previous session's snScOpId; the SC restarting at -1 caused error 22 "attach propagate message malformed" and a 5s reconnect loop. SC now sends a fresh random 16-byte session UUID with snResume=False on every connection. Added proper handling of BSSCI "error" messages (previously logged as "Unknown message type").
- **v1.672 - Heartbeat-Based Sensor Tracking**: Replaced hourly-reset active sensor count with persistent heartbeat-based online/offline tracking. Each sensor's avg send interval is calculated from last 10 messages. Sensor marked offline after 4x avg interval without data. Auto-detach warning now triggered by offline transition (not fixed 36h). Auto-detach uses offline_since + configured timeout. MQTT warning published on offline transition. Dashboard shows "Sensoren online" instead of hourly "aktiv" count. Fixed BS count deduplication (was counting writer objects, showing 5/10 instead of 5/5). Fixed beta channel config persistence (UPDATE_CHANNEL in bssci_config.py + direct module update after save). Beta version detection now scans both /releases and /tags APIs.
- **v1.671 - Base Station Connection Status**: Enhanced BS card to show "x/y connected" ratio with dynamic coloring.
- **v1.670 - Beta Channel & OMS Fixes**: Added Beta Channel toggle in config page for pre-release updates. When enabled, update checker includes GitHub pre-releases. Beta versions shown with BETA badge. Fixed OMS meter count on dashboard (was using wrong API endpoint). Added OMS meters as separate trend line (purple) in Traffic chart.
- **v1.669 - Active Sensor Count Fix**: Dashboard sensor card (blue field) now correctly shows active sensors (sent data this hour) instead of registered/configured count. Consistent with System Status percentage and Network Statistics count.
- **v1.668 - Dashboard Corrections**: Fixed 5 dashboard bugs: incorrect API endpoints, sensor count accuracy, replaced VM-capable with OMS meter count in network statistics, removed cluttered EUI list from base stations card, VM Sub-Channel shown separately in system status.
- **v1.667 - VM Detection Fix**: Fixed pending_vm_operations collision causing only 1 of 3 VM-capable BS to be detected. VM response handlers now use writer connection identification. Added VM-capable badge in base stations table.
- **v1.666 - Update System & Rate Limit Fixes**: Fixed directory handling in GitHub updates (os.walk), 5-minute cache for version checks against API rate limits, manual refresh with force=True.
- **v1.665 - OpID 0-Index & Attach Abort Fix**: opId starts at 0, SC uses negative opIds per BSSCI convention, connection loss aborts batch attach cleanly.
- **v1.664 - Per-BS Operation ID Fix**: Per-BS sequential opId counters replacing global counter, consistent increment direction.

## External Dependencies

**MQTT Broker**: External MQTT broker for data publishing and configuration management. Supports standard MQTT authentication and configurable topic structures.

**MessagePack**: Binary serialization format for efficient BSSCI protocol communication.

**Flask Web Framework**: Python web framework for the management interface with Bootstrap UI components.

**SSL/TLS Certificates**: CA-signed certificates for secure base station communication.

**Docker Support**: Containerized deployment with Docker Compose for both development and production environments.

**Environment Configuration**: dotenv support for configuration management with fallback defaults.

**Logging Infrastructure**: Structured logging with timezone support and multiple output targets.

**Update System**: GitHub API-based update checking with 5-minute cache, Docker live-updates, automatic backups.
