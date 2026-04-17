---
outline: [2, 3]
---

# Configuration

## Environment Variables (.env)

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

## Main Configuration (bssci_config.py)

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

## Configuration via Web Interface

The web interface provides a configuration page for:

- Network configuration (host, port)
- MQTT broker settings
- SSL certificate management
- System intervals and timeouts
- Auto-detach settings
