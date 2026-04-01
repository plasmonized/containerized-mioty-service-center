
# BSSCI Service Center - Complete Documentation

## Overview

The BSSCI Service Center is a comprehensive IoT device management system that provides secure communication between mioty sensors, base stations, and MQTT brokers. It implements the BSSCI (Base Station Service Center Interface) protocol with advanced features for sensor lifecycle management, automatic detachment, and real-time monitoring.

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Core Features](#core-features)
3. [Installation & Setup](#installation--setup)
4. [Configuration](#configuration)
5. [Sensor Management](#sensor-management)
6. [Auto-Detach System](#auto-detach-system)
7. [MQTT Integration](#mqtt-integration)
8. [Web Interface](#web-interface)
9. [API Reference](#api-reference)
10. [Troubleshooting](#troubleshooting)
11. [Advanced Features](#advanced-features)
12. [OMS/Wireless M-Bus Support](#omswireless-m-bus-wmbus-meter-support)
13. [User Authentication & Access Control](#user-authentication--role-based-access-control)

## System Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Base Station  │◄──►│  Service Center  │◄──►│  MQTT Broker    │
│                 │TLS │                  │    │                 │
│  - Sensor Mgmt  │    │ - TLS Server     │    │ - Data Topics   │
│  - Data Collect │    │ - MQTT Client    │    │ - Config Topics │
│  - Status Rep.  │    │ - Web Interface  │    │ - Status Topics │
│                 │    │ - Auto-Detach    │    │ - Commands      │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                         ┌──────▼──────┐
                         │ Web Browser │
                         │ Management  │
                         └─────────────┘
```

### Key Components

- **TLS Server**: Secure communication with base stations using BSSCI protocol
- **MQTT Interface**: Bidirectional communication with external systems
- **Web UI**: Real-time management and monitoring dashboard
- **Auto-Detach System**: Automated sensor lifecycle management
- **Certificate Management**: SSL/TLS security infrastructure

## Core Features

### Sensor Lifecycle Management

- **Automatic Registration**: Sensors are automatically registered when base stations connect
- **Manual Detachment**: Individual sensor detachment via web UI
- **Bulk Operations**: Clear all sensors with automatic detachment
- **Bulk Import/Export**: CSV/TXT file support for mass sensor configuration
- **Remote Commands**: MQTT-based sensor control (attach, detach, status)
- **Auto-Detach**: Automatic removal of inactive sensors after configurable timeout
- **Automatic Offline Detection**: Based on send_interval - shows Online/Warning/Offline status

### Sensor Detail Dashboard

Click on any sensor EUI to view comprehensive statistics:
- **Device Health**: Energy efficiency, signal strength indicators
- **Transmission Details**: Data rate, spreading factor, frequency, frame counter, airtime, duty cycle
- **SNR/RSSI Statistics**: Min/Avg/Max values with historical trends
- **Base Station Coverage**: All base stations receiving this sensor with individual signal quality
- **Telegram Tracking**: First seen, last seen timestamps, missed telegram detection
- **Activity Status**: Real-time online/warning/offline indicator based on send interval

### Network Topology Visualization

Interactive network visualization showing the complete mioty infrastructure:
- **Cytoscape.js Based**: Smooth, interactive graph visualization
- **Base Stations**: Large orange nodes representing gateways
- **Sensors**: Small blue nodes representing endpoints
- **Primary Routes**: Thick green lines showing best signal paths
- **Secondary Routes**: Thin gray lines showing alternative reception paths
- **Interactive**: Click nodes for details, drag to reposition
- **Position Saving**: Save and restore custom layout positions
- **Auto-Refresh**: Updates every 30 seconds

### System Health Dashboard

Comprehensive system monitoring and health metrics:
- **Packet Loss Detection**: 16-bit counter wrap-around handling for accurate loss calculation
- **Base Station Health Charts**: Real-time CPU, Memory, and Duty Cycle monitoring
- **Per-Sensor Statistics**: Individual sensor health with average SNR/RSSI
- **Signal Score Distribution**: Horizontal bar chart showing device breakdown by SNR quality (Excellent/Good/Fair/Poor/Critical)
- **24-Hour History**: Extended SNR/RSSI history with 5-minute intervals (288 data points)

### Base Station Management

Dedicated management interface for base stations:
- **Configuration**: Name, tags, IP address management
- **Health Monitoring**: CPU usage, memory usage, duty cycle
- **Connected Sensors**: Count of sensors per base station
- **Status Tracking**: Online/offline status with last seen timestamps

### Traffic Dashboard

Enhanced real-time traffic visualization:
- **12-Hour History**: Extended historical graphs for sensors and base stations
- **Active Sensor Tracking**: Hourly tracking of sensors that sent data
- **Message Statistics**: Real-time messages in/out, dropped packets
- **Connection Monitoring**: Base station connection status over time

### Variable MAC (VM) Sub-Channel Support

Full ETSI TS 103357 compliant Variable MAC implementation for metering devices:
- **vm.activate**: Activate VM sub-channel for sensor
- **vm.deactivate**: Deactivate VM sub-channel
- **vm.status**: Query VM sub-channel status
- **vm.ulData**: Receive uplink data via VM channel
- **vm.dlData**: Send downlink data via VM channel

### OMS/Wireless M-Bus (wMBUS) Meter Support

Full EN 13757 compliant wireless M-Bus frame parsing for OMS-compatible metering devices received via VM sub-channel:
- **Automatic Frame Detection**: Scans for valid wMBUS C-field values (0x44/0x46/0x48) to find frame start, handling BSSCI/VM wrapper bytes
- **120+ Manufacturer Database**: Built-in manufacturer lookup table from the m-bus.de standard with automatic 3-letter IEC code decoding
- **Manufacturer Decoding**: 2 bytes little-endian → 3-letter IEC code via bitshift formula
- **Device Type Mapping**: Automatic identification of meter types (Water, Gas, Electricity, Heat, etc.)
- **Serial Number Extraction**: 4-byte little-endian serial number from the A-field
- **Dedicated OMS Page**: Web UI management page showing all detected wMBUS meters
- **Per-Meter Tracking**: Serial number, manufacturer, device type, version, SNR, RSSI, base station, and message count

### Coverage Map

Interactive floorplan-based device positioning for network coverage visualization:
- **Floorplan Upload**: Upload custom floorplan images for your deployment environment
- **Drag-and-Drop Placement**: Position base stations and sensors on the floorplan
- **Server-Side Persistence**: Device positions stored in `coverage_positions.json`, floorplan in `coverage_floorplan.txt`
- **Zoom Level Persistence**: Zoom and pan state preserved across sessions

### Real-Time Monitoring

- **Live Dashboard**: Real-time sensor status and base station monitoring
- **Traffic Visualization**: Real-time charts showing messages in/out, dropped packets, and connections
- **Activity Tracking**: Monitor sensor communication and detect inactivity
- **Warning System**: Proactive alerts before auto-detachment
- **Signal Quality**: Track preferred downlink paths based on SNR
- **Comprehensive Logging**: Detailed system logs with timezone support

### Data Processing

- **Message Deduplication**: Intelligent filtering of duplicate messages from multiple base stations
- **Base Station Deduplication**: Prevents duplicate base station connections using EUI-based identification
- **Signal Optimization**: Automatic selection of best signal path
- **Queue Management**: Asynchronous message processing with monitoring
- **Performance Metrics**: Real-time statistics and monitoring

### Update System

Seamless software updates for both standalone and Docker installations:
- **GitHub API Integration**: Check for updates without requiring git repository
- **Version Management**: Semantic versioning via VERSION file
- **Docker Live-Updates**: Optional live-update mode for Docker containers
- **Automatic Backup**: Creates backup before applying updates
- **Branch Support**: Supports both main and master branches

## Tested Base Stations

The BSSCI Service Center has been tested and verified with the following base station hardware:

| Manufacturer | Device |
|---|---|
| Diehl Metering | Premium Gateway |
| Weptech | AVA1 |
| Miromico | Edge |
| Diehl Metering | Compact Gateway |
| RAK | WisGate Connect for mioty |

## Installation & Setup

### Prerequisites

- Python 3.12+
- SSL certificates for TLS communication
- MQTT broker access
- Network connectivity to base stations

### Quick Start

1. **Clone and Setup**:
   ```bash
   git clone <repository-url>
   cd bssci-service-center
   pip install -r requirements.txt
   ```

2. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

3. **Generate Certificates** (if needed):
   ```bash
   mkdir certs
   # Use web UI certificate management or manual generation
   ```

4. **Start the Service**:
   ```bash
   python web_main.py
   ```

5. **Access Web Interface**:
   Open http://localhost:5000 in your browser

## Configuration

### Environment Variables (.env)

```bash
# TLS Server Configuration
LISTEN_HOST=0.0.0.0
LISTEN_PORT=8000
CERT_FILE=certs/service_center_cert.pem
KEY_FILE=certs/service_center_key.pem
CA_FILE=certs/ca_cert.pem

# MQTT Configuration
MQTT_BROKER=your-mqtt-broker.com
MQTT_PORT=1883
MQTT_USERNAME=your-username
MQTT_PASSWORD=your-password
BASE_TOPIC=mioty

# Auto-detach Configuration
AUTO_DETACH_ENABLED=true
AUTO_DETACH_TIMEOUT=259200          # 72 hours in seconds
AUTO_DETACH_WARNING_TIMEOUT=129600  # 36 hours in seconds
AUTO_DETACH_CHECK_INTERVAL=3600     # Check every hour

# Application Configuration
SENSOR_CONFIG_FILE=endpoints.json
STATUS_INTERVAL=300
DEDUPLICATION_DELAY=2.0
```

### Main Configuration (bssci_config.py)

The system uses a Python configuration file for core settings:

```python
# Network Configuration
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 16018

# SSL/TLS Certificates
CERT_FILE = "certs/service_center_cert.pem"
KEY_FILE = "certs/service_center_key.pem" 
CA_FILE = "certs/ca_cert.pem"

# Auto-detach Settings (configurable via web UI)
AUTO_DETACH_ENABLED = True
AUTO_DETACH_TIMEOUT = 72 * 3600      # 72 hours
AUTO_DETACH_WARNING_TIMEOUT = 36 * 3600  # 36 hours
AUTO_DETACH_CHECK_INTERVAL = 3600    # 1 hour
```

## Sensor Management

### Adding Sensors

#### Via Web Interface
1. Navigate to "Manage Sensors" in the web UI
2. Click "Add New Sensor"
3. Fill in required fields:
   - **EUI**: 16-character hexadecimal identifier
   - **Network Key**: 32-character hexadecimal key
   - **Short Address**: 4-character hexadecimal address
   - **Bidirectional**: Enable/disable bidirectional communication

#### Via MQTT Registration (Recommended)

**Primary Method**: Legacy sensor registration via topic: `{BASE_TOPIC}/ep/{EUI}/register`

**Required JSON Payload:**
```json
{
  "nwKey": "0011223344556677889AABBCCDDEEFF00",
  "shortAddr": "1234",
  "bidi": false
}
```

**Practical Example:**
```bash
# Register sensor with EUI FCA84A0300001234 (Legacy method - RECOMMENDED)
mosquitto_pub -h your-broker.com -u username -p password \
  -t "mioty/ep/FCA84A0300001234/register" \
  -m '{"nwKey": "0011223344556677889AABBCCDDEEFF00", "shortAddr": "1234", "bidi": false}'
```

**Alternative Configuration Method**: Use config topic: `{BASE_TOPIC}/ep/{EUI}/config`
```bash
# Alternative configuration method (still supported)
mosquitto_pub -h your-broker.com -u username -p password \
  -t "mioty/ep/FCA84A0300001234/config" \
  -m '{"nwKey": "0011223344556677889AABBCCDDEEFF00", "shortAddr": "1234", "bidi": false}'
```

**Sensor Control Commands**: Use unified command topic: `{BASE_TOPIC}/ep/{EUI}/cmd`

**Available Commands:**
- `attach` - Attach sensor to base stations
- `detach` - Detach sensor from base stations  
- `status` - Query current registration status

**Command Examples:**
```bash
# Attach sensor
mosquitto_pub -h broker -t "mioty/ep/FCA84A0300001234/cmd" -m "attach"

# Detach sensor
mosquitto_pub -h broker -t "mioty/ep/FCA84A0300001234/cmd" -m "detach"

# Request status
mosquitto_pub -h broker -t "mioty/ep/FCA84A0300001234/cmd" -m "status"
```

**Important Notes:**
- ✅ Legacy `/bssci/ep/eui/register` topic is **fully supported** for backward compatibility
- ✅ Unified `/bssci/ep/eui/cmd` topic for all sensor commands
- ✅ All commands receive responses on `{BASE_TOPIC}/ep/{EUI}/response` topic

### Sensor Status Indicators

The web interface displays comprehensive sensor status:

- **🟢 Active**: Sensor recently communicated (within warning threshold)
- **🟡 Warning**: Sensor inactive for 36+ hours (configurable)
- **🔴 Auto-Detach Pending**: Sensor inactive for 72+ hours (configurable)
- **⚫ Auto-Detached**: Sensor automatically detached due to inactivity
- **🔗 Registered**: Sensor successfully registered to base station(s)

### Manual Detachment

#### Single Sensor Detachment
- Click the "Detach" button next to any sensor in the web interface
- Sensor is detached from all connected base stations
- Status is updated immediately

#### Bulk Detachment
- Click "Clear All" in the sensors management page
- All sensors are detached from all base stations
- Configuration is cleared
- Operation is logged and confirmed

## Auto-Detach System

The auto-detach system provides automated sensor lifecycle management based on communication activity.

### Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `AUTO_DETACH_ENABLED` | `true` | Enable/disable auto-detach functionality |
| `AUTO_DETACH_TIMEOUT` | `259200` | Seconds (72 hours) before auto-detach |
| `AUTO_DETACH_WARNING_TIMEOUT` | `129600` | Seconds (36 hours) before warning |
| `AUTO_DETACH_CHECK_INTERVAL` | `3600` | Seconds (1 hour) between checks |

### Auto-Detach Process

1. **Activity Monitoring**: System tracks last communication from each sensor
2. **Warning Phase** (after 36 hours):
   - Warning status displayed in web interface
   - MQTT warning notification sent to `ep/{EUI}/warning`
   - Sensor status shows hours until detachment
3. **Auto-Detach Phase** (after 72 hours):
   - Sensor automatically detached from all base stations
   - MQTT notification sent to `ep/{EUI}/status`
   - Sensor removed from registration tracking
   - Status updated in web interface

### Warning Information

When sensors enter warning state, the following information is available:

```json
{
  "action": "inactivity_warning",
  "sensor_eui": "FCA84A0300001234",
  "inactive_hours": 36.5,
  "hours_until_detach": 35.5,
  "warning_threshold_hours": 36,
  "detach_threshold_hours": 72,
  "timestamp": 1703123456.789
}
```

## MQTT Integration

### Unified Topic Structure

The system uses a simplified, unified MQTT topic structure under `{BASE_TOPIC}/ep/{EUI}/`:

```
{BASE_TOPIC}/
├── ep/{EUI}/
│   ├── register        # 🎯 SENSOR REGISTRATION (Legacy - RECOMMENDED)
│   ├── config          # Alternative sensor configuration
│   ├── cmd             # 🎯 UNIFIED SENSOR COMMANDS (attach, detach, status)
│   ├── ul              # Uplink data from sensors
│   ├── dl              # Downlink data to sensors  
│   ├── status          # Sensor status updates
│   ├── warning         # Inactivity warnings
│   ├── response        # Command responses
│   ├── error           # Error notifications
│   └── vm/             # Variable MAC sub-channel
│       ├── activate    # VM activation commands
│       ├── deactivate  # VM deactivation commands
│       ├── status      # VM status updates
│       ├── ulData      # VM uplink data
│       └── dlData      # VM downlink data
├── ep/oms_{MFR}_{SERIAL}/
│   └── ul              # OMS meter uplink data
├── bs/{EUI}/           # Base station status
├── config/             # System configuration
└── health_check        # Connection health monitoring
```

**Subscription Topics** (what the system listens to):
- `{BASE_TOPIC}/ep/+/register` - 🎯 **Legacy sensor registration (RECOMMENDED)**
- `{BASE_TOPIC}/ep/+/config` - Alternative sensor configuration
- `{BASE_TOPIC}/ep/+/cmd` - 🎯 **Unified sensor commands**
- `{BASE_TOPIC}/ep/+/dl` - Downlink messages
- `{BASE_TOPIC}/config/+` - System configuration

**Publication Topics** (what the system sends):
- `{BASE_TOPIC}/ep/{EUI}/ul` - Sensor uplink data
- `{BASE_TOPIC}/ep/{EUI}/status` - Registration status
- `{BASE_TOPIC}/ep/{EUI}/response` - Command responses
- `{BASE_TOPIC}/ep/{EUI}/warning` - Inactivity warnings
- `{BASE_TOPIC}/ep/oms_{MFR}_{SERIAL}/ul` - OMS meter uplink data (e.g., `mioty/ep/oms_DME_269898905/ul`)
- `{BASE_TOPIC}/bs/{EUI}` - Base station status

**Key Simplifications:**
- ✅ **Single command pattern**: Only `{BASE_TOPIC}/ep/{EUI}/cmd`
- ✅ **Legacy support**: `/register` topic fully supported
- ✅ **Unified**: All sensor operations under `/bssci/ep/eui/` namespace

### Unified Command System

The system now uses a **single, unified command pattern** for all sensor operations:

**One Command Topic**: `{BASE_TOPIC}/ep/{EUI}/cmd`

#### Complete Sensor Workflow

**Step 1: Register Sensor (Legacy Method - RECOMMENDED)**
```bash
# Register sensor using legacy topic (recommended for compatibility)
mosquitto_pub -h broker -u user -p pass \
  -t "mioty/ep/FCA84A0300001234/register" \
  -m '{"nwKey": "0011223344556677889AABBCCDDEEFF00", "shortAddr": "1234", "bidi": false}'
```

**Step 2: Control Sensor (Unified Commands)**
```bash
# All sensor commands use the same unified topic pattern

# Attach sensor to base stations
mosquitto_pub -h broker -t "mioty/ep/FCA84A0300001234/cmd" -m "attach"

# Detach sensor from base stations
mosquitto_pub -h broker -t "mioty/ep/FCA84A0300001234/cmd" -m "detach"

# Request sensor status
mosquitto_pub -h broker -t "mioty/ep/FCA84A0300001234/cmd" -m "status"
```

#### Legacy Support

✅ **Legacy Registration**: The `/bssci/ep/eui/register` topic is **fully supported** for backward compatibility with existing systems.

```bash
# Legacy registration (RECOMMENDED for stability)
mosquitto_pub -h broker -t "mioty/ep/FCA84A0300001234/register" \
  -m '{"nwKey": "0011223344556677889AABBCCDDEEFF00", "shortAddr": "1234", "bidi": false}'
```

#### Simplified Architecture


- ✅ `{BASE_TOPIC}/ep/{EUI}/register` (for registration)
- ✅ `{BASE_TOPIC}/ep/{EUI}/cmd` (for all commands)


#### Command Responses

All commands receive acknowledgments on: `{BASE_TOPIC}/ep/{EUI}/response`

```json
{
  "command": "attach",
  "status": "received",
  "timestamp": 1703123456.789
}
```

### Command Responses

Commands receive responses on topic `EP/{EUI}/response`:

```json
{
  "command": "detach",
  "status": "received",
  "timestamp": 1703123456.789
}
```

### Auto-Detach Notifications

#### Warning Notification (`ep/{EUI}/warning`)
```json
{
  "action": "inactivity_warning",
  "sensor_eui": "FCA84A0300001234", 
  "inactive_hours": 36.5,
  "hours_until_detach": 35.5,
  "timestamp": 1703123456.789
}
```

#### Auto-Detach Notification (`ep/{EUI}/status`)
```json
{
  "action": "auto_detached",
  "sensor_eui": "FCA84A0300001234",
  "reason": "inactivity", 
  "inactive_hours": 72.3,
  "threshold_hours": 72,
  "timestamp": 1703123456.789
}
```

### OMS Meter MQTT Publishing

OMS/wMBUS meters detected via the VM sub-channel are automatically published to MQTT using a unified payload format. Each meter publishes under a dedicated topic based on its manufacturer and serial number.

**Topic Format**: `{BASE_TOPIC}/ep/oms_{manufacturer}_{serial}/ul`

**Example Topic**: `mioty/ep/oms_DME_269898905/ul`

**Payload Format**:
```json
{
  "bs_eui": "00073200007E21C5",
  "snr": 3.96,
  "rssi": -122.13,
  "data": "5544a511995416107607...",
  "mac_type": 0,
  "timestamp": 1739012345.67,
  "oms": {
    "serial": "269898905",
    "serial_hex": "10165499",
    "manufacturer": "DME",
    "manufacturer_name": "DIEHL Metering",
    "version": 118,
    "device_type": 7,
    "device_type_name": "Water",
    "meter_id": "A51110165499"
  }
}
```

The payload follows the same structure as standard mioty sensor uplinks (`bs_eui`, `snr`, `rssi`, `data`, `mac_type`, `timestamp`) with an additional `oms` block containing the decoded wMBUS meter information.

## Web Interface

### Dashboard Overview

The main dashboard provides a redesigned real-time system overview with mioty branding:

- **Custom SVG Icons**: Base station tower icon and sensor with radio waves icon for visual clarity
- **Clickable Cards**: Quick navigation cards for base stations, sensors, and system status
- **Visual Health Indicators**: Color-coded status indicators for system components
- **Network Topology Mini-Preview**: At-a-glance view of the network topology
- **Orange/White Color Scheme**: Consistent mioty branding throughout the interface
- **Service Status**: Overall system health and connectivity
- **Base Station Monitor**: Connected and connecting base stations
- **Sensor Summary**: Total sensors, registrations, and activity status
- **Quick Actions**: Direct access to management functions

### Sensor Management Interface

#### Sensor List View
- **Status Indicators**: Visual status for each sensor (active, warning, detached)
- **Registration Info**: Shows which base stations each sensor is connected to
- **Activity Tracking**: Hours since last communication
- **Signal Quality**: Preferred downlink path with SNR information
- **Action Buttons**: Detach individual sensors or bulk operations

#### Sensor Details
- **Configuration**: EUI, network key, short address, bidirectional setting
- **Registration History**: Timeline of registrations and detachments  
- **Communication Stats**: Message counts, signal quality metrics
- **Warning Status**: Current warning state and time until auto-detach

### Configuration Management

#### General Settings
- Network configuration (host, port)
- MQTT broker settings
- SSL certificate management
- System intervals and timeouts

#### Auto-Detach Settings
- Enable/disable auto-detach functionality
- Configure warning and detach timeouts
- Set monitoring check intervals
- Real-time parameter updates

### Certificate Management

#### SSL Certificate Operations
- **Generate**: Create new self-signed certificates
- **Upload**: Upload existing certificate files
- **Download**: Backup current certificates
- **Status Check**: Verify certificate validity and expiration

#### Certificate Files Required
- `ca_cert.pem`: Certificate Authority certificate
- `service_center_cert.pem`: Service center certificate
- `service_center_key.pem`: Service center private key
