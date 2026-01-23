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

- **User Authentication & Role-Based Access Control**: Three user roles implemented - Admin (full access), User (can manage sensors/base stations), Viewer (read-only dashboards). Login required for all pages, API endpoints protected with permission decorators. Users managed via users.json file.
- **Persistent Coverage Map Storage**: Floorplan images, device positions, and zoom levels are now stored server-side for access from any device. Files: coverage_positions.json and coverage_floorplan.txt (mounted as Docker volumes for persistence).
- **Sensor Detail Dashboard**: Click on any sensor EUI to view detailed statistics including Device Health (energy efficiency, signal strength), Transmission Details (data rate, spreading factor, frequency, frame counter, airtime, duty cycle), SNR/RSSI statistics (min/avg/max), and gateway coverage. Tracks first seen, last seen timestamps, and detects missed frames.
- **GitHub API-based Update System**: Update checking and installation now works in Docker containers without requiring a mounted .git directory. Uses GitHub API to fetch latest commits and downloads updates as ZIP archives.
- **Network Topology Visualization**: New interactive network page showing base stations (large orange nodes) and sensors (small blue nodes) with Cytoscape.js. Displays primary routes (green thick lines) and secondary reception paths (gray thin lines). Click nodes for details, auto-refreshes every 30 seconds.
- **Signal Score Distribution Chart**: Horizontal bar chart showing device breakdown by SNR quality (Excellent/Good/Fair/Poor/Critical) with summary counters and reference tables.
- **24-Hour SNR/RSSI History**: Extended history from 1 hour to 24 hours with 5-minute intervals (288 data points).
- **Health Dashboard**: New system health monitoring page with packet loss detection, base station health charts (CPU/Memory/Duty Cycle), and per-sensor statistics including average SNR/RSSI
- **Packet Loss Tracking**: 16-bit counter wrap-around handling for accurate packet loss rate calculation per sensor
- **Base Station Management Page**: New dedicated page for managing base stations with name, tags, IP address, CPU/memory health data, and connected sensor counts
- **Active Sensors Tracking**: Hourly tracking of sensors that sent data, displayed in traffic dashboard
- **12-Hour Traffic History**: Extended sensor and base station history graph to 12 hours
- **Bulk Import/Export**: Added CSV/TXT sensor import/export functionality with flexible delimiter detection
- **Variable MAC (VM)**: Full ETSI TS 103357 compliant VM sub-channel support for metering devices
- **Traffic Dashboard**: Real-time traffic visualization with Chart.js showing messages, dropped packets, and connections
- **Base Station Deduplication**: Fixed duplicate base station connections using EUI-based identification

## External Dependencies

**MQTT Broker**: External MQTT broker for data publishing and configuration management. Supports standard MQTT authentication and configurable topic structures.

**MessagePack**: Binary serialization format for efficient BSSCI protocol communication.

**Flask Web Framework**: Python web framework for the management interface with Bootstrap UI components.

**SSL/TLS Certificates**: CA-signed certificates for secure base station communication.

**Docker Support**: Containerized deployment with Docker Compose for both development and production environments.

**Environment Configuration**: dotenv support for configuration management with fallback defaults.

**Logging Infrastructure**: Structured logging with timezone support and multiple output targets.