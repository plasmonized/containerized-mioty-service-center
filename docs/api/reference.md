---
outline: [2, 3]
---

# API Reference

## Sensor Operations

### Get All Sensors

```http
GET /api/sensors
```

Returns complete sensor status including registration, activity, and warning information.

### Add/Update Sensor

```http
POST /api/sensors
Content-Type: application/json

{
  "eui": "FCA84A0300001234",
  "nwKey": "0011223344556677889AABBCCDDEEFF00", 
  "shortAddr": "1234",
  "bidi": false
}
```

### Delete Sensor

```http
DELETE /api/sensors/{eui}
```

### Detach Single Sensor

```http
POST /api/sensors/{eui}/detach
```

Detaches the sensor from all connected base stations.

### Clear All Sensors

```http
POST /api/sensors/clear
```

Performs bulk detachment and clears all sensor configurations.

### Export Sensors to CSV

```http
GET /api/sensors/export
```

Downloads all sensor configurations as CSV file.

### Import Sensors from CSV/TXT

```http
POST /api/sensors/import
Content-Type: multipart/form-data

file: <csv or txt file>
```

## Variable MAC (VM) Operations

### Activate VM Sub-Channel

```http
POST /api/vm/activate
Content-Type: application/json

{
  "eui": "FCA84A0300001234"
}
```

### Deactivate VM Sub-Channel

```http
POST /api/vm/deactivate
Content-Type: application/json

{
  "eui": "FCA84A0300001234"
}
```

### Get VM Status

```http
GET /api/vm/status
```

### Send VM Downlink Data

```http
POST /api/vm/dlData
Content-Type: application/json

{
  "eui": "FCA84A0300001234",
  "payload": "48656C6C6F"
}
```

## Traffic Monitoring

### Get Traffic Metrics

```http
GET /api/traffic/metrics
```

Returns real-time traffic statistics including:
- Messages in/out counts
- Dropped messages (deduplication)
- Bytes transferred
- VM message counts
- 60-minute history for charting

### Reset Traffic Metrics

```http
POST /api/traffic/reset
```

## System Status

### Service Status

```http
GET /api/bssci/status
```

Returns comprehensive system status:
- Service running state
- Base station connections
- Sensor registration statistics
- MQTT connectivity
- TLS server status

### Base Station Status

```http
GET /api/base_stations
```

## Configuration Management

### Get Configuration

```http
GET /config
```

### Update Configuration

```http
POST /api/config
Content-Type: application/json

{
  "MQTT_BROKER": "your-broker.com",
  "AUTO_DETACH_ENABLED": true,
  "AUTO_DETACH_TIMEOUT": 259200,
  "AUTO_DETACH_WARNING_TIMEOUT": 129600
}
```
