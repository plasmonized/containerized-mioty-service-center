# BSSCI Service Center

## Overview

The BSSCI Service Center is a comprehensive IoT device management system that provides secure communication between mioty sensors, base stations, and MQTT brokers. It implements the BSSCI (Base Station Service Center Interface) protocol for managing sensor attachments, data collection, and system monitoring. The system serves as a central hub that enables secure TLS communication with base stations while providing bidirectional MQTT integration for external systems.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Core Components

The system follows a multi-layered architecture with clear separation of concerns:

**TLS Server Layer**: Implements the BSSCI protocol for secure communication with mioty base stations using TLS encryption. Handles base station connections, sensor attachment/detachment requests, and real-time data collection.

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

SSL/TLS infrastructure using CA-signed certificates for secure base station authentication. The system supports certificate generation, validation, and management through the web interface.

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

## Recent Changes

- **v1.665 - OpID 0-Index & Attach Abort Fix**: Fixed opId starting value from 1 to 0 (BSSCI protocol uses 0-indexed operation IDs). Added connection validity check in batch attach loop - now aborts immediately on connection loss instead of cascading errors for every remaining sensor. Connection-related exceptions (ConnectionResetError, BrokenPipeError) break the loop cleanly.
- **v1.664 - Per-BS Operation ID Fix**: Replaced global opID counter with per-BS sequential counters. Each BS connection gets its own opID sequence, properly initialized on connect and cleaned up on disconnect. Fixed inconsistent opID direction (attach decremented, status incremented) - all now increment consistently.
- **v1.663 - Unified Base Station & Certificate Management**: Merged Base Stations and Certificates pages into single tabbed interface. Per-BS certificate generation (stored in `certs/bs_{eui}/`), auto-cert onboarding flow with ZIP download, Certificate overview tab with CA management, uptime tracking with horizontal bar chart (Chart.js). Removed standalone Certificates nav tab. 3-failure threshold for BS status requests, skip-attach for already-registered sensors on BS reconnect.
- **v1.660 - Robust wMBUS Frame Parser**: Automatic wMBUS frame-start detection by scanning for valid C-field (0x44/0x46/0x48). Handles BSSCI/VM wrapper bytes that some base stations prepend. Fixes incorrect manufacturer/device type parsing for certain meter telegrams.
- **OMS/Wireless M-Bus Meter Support**: Full EN 13757 compliant wMBUS frame parsing with 120+ manufacturer database, automatic 3-letter IEC code decoding, device type mapping, and dedicated OMS management page. Meters publish to MQTT under `ep/oms_{manufacturer}_{serial}/ul` with unified payload format including decoded OMS metadata block.
- **Dashboard Redesign**: Custom SVG icons (base station tower, sensor with radio waves), clickable cards, visual health indicators, network topology mini-preview. Orange/white color scheme matching mioty branding.
- **User Authentication & Role-Based Access Control**: Three user roles - Admin (full access), User (sensor/BS management), Viewer (read-only dashboards). Login required for all pages, API endpoints protected with permission decorators. Users managed via users.json file.
- **Persistent Coverage Map Storage**: Floorplan images, device positions, and zoom levels stored server-side. Files: coverage_positions.json and coverage_floorplan.txt.
- **Sensor Detail Dashboard**: Click any sensor EUI for detailed statistics including Device Health, Transmission Details, SNR/RSSI statistics (min/avg/max), and gateway coverage.
- **Network Topology Visualization**: Interactive Cytoscape.js graph showing base stations and sensors with primary/secondary routes.
- **System Health Dashboard**: Packet loss detection, base station health charts (CPU/Memory/Duty Cycle), per-sensor statistics, signal score distribution.
- **Base Station Management Page**: Dedicated page with name, tags, IP, health data, and connected sensor counts.
- **Variable MAC (VM)**: Full ETSI TS 103357 compliant VM sub-channel support for metering devices.
- **Traffic Dashboard**: Real-time visualization with 12-hour history, active sensor tracking, message statistics.
- **Bulk Import/Export**: CSV/TXT sensor import/export with flexible delimiter detection.
- **Update System**: GitHub API-based update checking, Docker live-updates, automatic backups.

## External Dependencies

**MQTT Broker**: External MQTT broker for data publishing and configuration management. Supports standard MQTT authentication and configurable topic structures.

**MessagePack**: Binary serialization format for efficient BSSCI protocol communication.

**Flask Web Framework**: Python web framework for the management interface with Bootstrap UI components.

**SSL/TLS Certificates**: CA-signed certificates for secure base station communication.

**Docker Support**: Containerized deployment with Docker Compose for both development and production environments.

**Environment Configuration**: dotenv support for configuration management with fallback defaults.

**Logging Infrastructure**: Structured logging with timezone support and multiple output targets.