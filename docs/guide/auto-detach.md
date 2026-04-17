---
outline: [2, 3]
---

# Auto-Detach System

The auto-detach system provides automated sensor lifecycle management based on communication activity.

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `AUTO_DETACH_ENABLED` | `true` | Enable/disable auto-detach functionality |
| `AUTO_DETACH_TIMEOUT` | `259200` | Seconds (72 hours) before auto-detach |
| `AUTO_DETACH_WARNING_TIMEOUT` | `129600` | Seconds (36 hours) before warning |
| `AUTO_DETACH_CHECK_INTERVAL` | `3600` | Seconds (1 hour) between checks |

## Auto-Detach Process

```mermaid
flowchart TD
    Start([Sensor Active]) --> Check{Check Interval}
    
    Check -->|1 hour| LastCom{Last Communication<br/>> WARNING_TIMEOUT?}
    
    LastCom -->|No| Active[Continue Monitoring]
    Active --> Check
    
    LastCom -->|Yes<br/>36+ hours| Warning[⚠️ Warning Phase]
    Warning --> PublishWarning[MQTT: ep/{EUI}/warning]
    PublishWarning --> WebWarning[Web UI: Warning Status]
    WebWarning --> ShowTime[Show hours until detach]
    ShowTime --> Check
    
    Warning --> LastCom2{Last Communication<br/>> DETACH_TIMEOUT?}
    
    LastCom2 -->|No<br/>< 72 hours| Check
    LastCom2 -->|Yes<br/>72+ hours| Detach[🔴 Auto-Detach]
    
    Detach --> Notify[MQTT: ep/{EUI}/status]
    Notify --> Remove[Remove from base stations]
    Remove --> Update[Update web UI]
    Update --> End([Sensor Detached])
    
    style Start fill:#9f9
    style Warning fill:#ff9
    style Detach fill:#f96
    style End fill:#f99
```

## Warning Information

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

## MQTT Notifications

### Warning Notification

Topic: `ep/{EUI}/warning`

```json
{
  "action": "inactivity_warning",
  "sensor_eui": "FCA84A0300001234", 
  "inactive_hours": 36.5,
  "hours_until_detach": 35.5,
  "timestamp": 1703123456.789
}
```

### Auto-Detach Notification

Topic: `ep/{EUI}/status`

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

## Disabling Auto-Detach

```python
# In bssci_config.py or via web interface
AUTO_DETACH_ENABLED = False
```
