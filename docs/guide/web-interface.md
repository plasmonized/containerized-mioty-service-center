---
outline: [2, 3]
---

# Web Interface

## Dashboard Overview

The main dashboard provides a redesigned real-time system overview with mioty branding:

- **Custom SVG Icons**: Base station tower icon and sensor with radio waves icon for visual clarity
- **Clickable Cards**: Quick navigation cards for base stations, sensors, and system status
- **Visual Health Indicators**: Color-coded status indicators for system components
- **Network Topology Mini-Preview**: At-a-glance view of the network topology
- **Orange/White Color Scheme**: Consistent mioty branding throughout the interface

## Pages

### Sensors Page

- **Status Indicators**: Visual status for each sensor (active, warning, detached)
- **Registration Info**: Shows which base stations each sensor is connected to
- **Activity Tracking**: Hours since last communication
- **Signal Quality**: Preferred downlink path with SNR information
- **Action Buttons**: Detach individual sensors or bulk operations

### Base Stations Page

- **Configuration**: Name, tags, IP address management
- **Health Monitoring**: CPU usage, memory usage, duty cycle
- **Connected Sensors**: Count of sensors per base station
- **Status Tracking**: Online/offline status with last seen timestamps

### Network Page

Interactive network visualization showing the complete mioty infrastructure:

- **Cytoscape.js Based**: Smooth, interactive graph visualization
- **Base Stations**: Large orange nodes representing gateways
- **Sensors**: Small blue nodes representing endpoints
- **Primary Routes**: Thick green lines showing best signal paths
- **Secondary Routes**: Thin gray lines showing alternative reception paths
- **Interactive**: Click nodes for details, drag to reposition

### Health Page

Comprehensive system monitoring and health metrics:

- **Packet Loss Detection**: 16-bit counter wrap-around handling
- **Base Station Health Charts**: Real-time CPU, Memory, and Duty Cycle
- **Per-Sensor Statistics**: Individual sensor health with average SNR/RSSI
- **Signal Score Distribution**: Bar chart showing device breakdown by SNR quality

### Traffic Page

Enhanced real-time traffic visualization:

- **12-Hour History**: Extended historical graphs
- **Active Sensor Tracking**: Hourly tracking of sensors that sent data
- **Message Statistics**: Real-time messages in/out, dropped packets
- **Connection Monitoring**: Base station connection status over time

### Coverage Page

Interactive floorplan-based device positioning:

- **Floorplan Upload**: Upload custom floorplan images
- **Drag-and-Drop Placement**: Position base stations and sensors
- **Position Persistence**: Device positions stored in `coverage_positions.json`

### Configuration Page

- Network configuration (host, port)
- MQTT broker settings
- SSL certificate management
- Auto-detach settings
- Real-time parameter updates

### Certificates Page

- **Generate**: Create new self-signed certificates
- **Upload**: Upload existing certificate files
- **Download**: Backup current certificates
- **Status Check**: Verify certificate validity and expiration

### Logs Page

- Detailed system logs with timezone support
- Real-time log streaming
- Log level filtering
- Search functionality

## User Authentication

The system implements a comprehensive authentication and authorization system:

- **Admin**: Full access to all features including user management, configuration, and system updates
- **User**: Can manage sensors and base stations, view dashboards and logs
- **Viewer**: Read-only access to dashboards, sensor data, and monitoring pages
