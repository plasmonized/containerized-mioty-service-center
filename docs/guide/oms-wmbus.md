---
outline: [2, 3]
---

# OMS/Wireless M-Bus Support

Full EN 13757 compliant wireless M-Bus frame parsing for OMS-compatible metering devices received via VM sub-channel.

## Features

- **Automatic Frame Detection**: Scans for valid wMBUS C-field values (0x44/0x46/0x48)
- **120+ Manufacturer Database**: Built-in manufacturer lookup table with automatic 3-letter IEC code decoding
- **Device Type Mapping**: Automatic identification of meter types (Water, Gas, Electricity, Heat, etc.)
- **Dedicated OMS Page**: Web UI management page showing all detected wMBUS meters
- **Per-Meter Tracking**: Serial number, manufacturer, device type, version, SNR, RSSI, base station, and message count

## Device Types

| Type ID | Name |
|---------|------|
| 0 | Unknown |
| 1 | Other |
| 2 | Oil |
| 3 | Electricity |
| 4 | Gas |
| 5 | Heat |
| 6 | Steam |
| 7 | Water |
| 8 | Heat Cost |
| 9 | Compressed Air |
| 10 | Cooling Load Meter |
| 11 | Cooling Load Meter |
| 12 | Heat |
| 13 | Heat/Steam |
| 14 | Bayonette |
| 15 | Temperature |
| 16 | Pressure |
| 17 | Gas Mode |
| 18 | Multi Valve |
| 19 | Multi Sensor |
| 20 | Smoke Detector |
| 21 | Room Panel |
| 22 | Valve Controller |
| 23 | Monitoring Controller |
| 24 | Monitoring Device |
| 25 | Valve Actuator |

## MQTT Publishing

OMS/wMBUS meters detected via the VM sub-channel are automatically published to MQTT.

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
