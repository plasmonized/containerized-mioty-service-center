---
outline: [2, 3]
---

# Variable MAC (VM) Sub-Channel

Full ETSI TS 103357 compliant Variable MAC implementation for metering devices.

## Supported Operations

| Operation | Description |
|-----------|-------------|
| `vm.activate` | Activate VM sub-channel for sensor |
| `vm.deactivate` | Deactivate VM sub-channel |
| `vm.status` | Query VM sub-channel status |
| `vm.ulData` | Receive uplink data via VM channel |
| `vm.dlData` | Send downlink data via VM channel |

## API Endpoints

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

Returns status of all active VM sub-channels.

### Send VM Downlink Data

```http
POST /api/vm/dlData
Content-Type: application/json

{
  "eui": "FCA84A0300001234",
  "payload": "48656C6C6F"
}
```

## MQTT Topics

```
{BASE_TOPIC}/ep/{EUI}/vm/
├── activate    # VM activation commands
├── deactivate  # VM deactivation commands
├── status      # VM status updates
├── ulData      # VM uplink data
└── dlData      # VM downlink data
```
