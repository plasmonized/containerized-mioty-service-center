# BSSCI Service Center

## Overview

The BSSCI Service Center is a comprehensive IoT device management system that provides secure communication between mioty sensors, base stations, and MQTT brokers. It implements the BSSCI (Base Station Service Center Interface) protocol for managing sensor attachments, data collection, and system monitoring. The system serves as a central hub that enables secure TLS communication with base stations while providing bidirectional MQTT integration for external systems.

## User Preferences

Preferred communication style: Simple, everyday language.

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

- **v1.679 - nwkSnKey as msgpack bin (Miromico attach error 22, 2nd fix)**: The session-UUID fix (v1.677) alone did not resolve error 22 "attach propagate message malformed" on Miromico EdgeCard FW 5.1.0 (BSSCI 1.1.0). attPrp now encodes nwkSnKey as raw 16 bytes (msgpack bin type) instead of an array of 16 ints. BSSCI spec v1.0.0 documents Numeric[16], but the strict Miromico parser expects bin for the network session key.
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
