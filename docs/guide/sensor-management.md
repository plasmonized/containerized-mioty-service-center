---
outline: [2, 3]
---

# Sensor Management

## Adding Sensors

### Via Web Interface

1. Navigate to "Manage Sensors" in the web UI
2. Click "Add New Sensor"
3. Fill in required fields:
   - **EUI**: 16-character hexadecimal identifier
   - **Network Key**: 32-character hexadecimal key
   - **Short Address**: 4-character hexadecimal address
   - **Bidirectional**: Enable/disable bidirectional communication

### Via MQTT Registration

**Primary Method**: Legacy sensor registration via topic: `{BASE_TOPIC}/ep/{EUI}/register`

**Required JSON Payload:**

```json
{
  "nwKey": "0011223344556677889AABBCCDDEEFF00",
  "shortAddr": "1234",
  "bidi": false
}
```

**Example:**

```bash
mosquitto_pub -h your-broker.com -u username -p password \
  -t "mioty/ep/FCA84A0300001234/register" \
  -m '{"nwKey": "0011223344556677889AABBCCDDEEFF00", "shortAddr": "1234", "bidi": false}'
```

## Sensor Status Indicators

| Status | Description |
|--------|-------------|
| 🟢 Active | Sensor recently communicated (within warning threshold) |
| 🟡 Warning | Sensor inactive for 36+ hours (configurable) |
| 🔴 Auto-Detach Pending | Sensor inactive for 72+ hours (configurable) |
| ⚫ Auto-Detached | Sensor automatically detached due to inactivity |
| 🔗 Registered | Sensor successfully registered to base station(s) |

## Sensor Commands

**One Command Topic**: `{BASE_TOPIC}/ep/{EUI}/cmd`

### Available Commands

```bash
# Attach sensor to base stations
mosquitto_pub -h broker -t "mioty/ep/FCA84A0300001234/cmd" -m "attach"

# Detach sensor from base stations
mosquitto_pub -h broker -t "mioty/ep/FCA84A0300001234/cmd" -m "detach"

# Request sensor status
mosquitto_pub -h broker -t "mioty/ep/FCA84A0300001234/cmd" -m "status"
```

## Bulk Operations

### Export Sensors to CSV

```http
GET /api/sensors/export
```

### Import Sensors from CSV/TXT

```http
POST /api/sensors/import
Content-Type: multipart/form-data

file: <csv or txt file>
```

### Clear All Sensors

```http
POST /api/sensors/clear
```
