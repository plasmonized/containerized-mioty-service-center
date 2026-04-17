---
outline: [2, 3]
---

# Installation & Setup

## Prerequisites

- Python 3.12+
- SSL certificates for TLS communication
- MQTT broker access
- Network connectivity to base stations

## Quick Start

### 1. Clone and Setup

```bash
git clone <repository-url>
cd bssci-service-center
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings
```

### 3. Generate Certificates

```bash
mkdir certs
# Use web UI certificate management or manual generation
```

### 4. Start the Service

```bash
python web_main.py
```

### 5. Access Web Interface

Open `http://localhost:5000` in your browser

## Directory Structure

```
bssci-service-center/
├── main.py                  # Service entry point
├── web_main.py              # Web UI + service
├── web_ui.py                # Flask web app
├── TLSServer.py             # TLS server
├── mqtt_interface.py        # MQTT client
├── protocol.py              # msgpack encoding
├── messages.py              # BSSCI builders
├── bssci_config.py          # Configuration
├── requirements.txt         # Python dependencies
├── .env.example             # Environment template
├── docker-compose.yml       # Docker setup
├── endpoints.json           # Sensor configuration
├── users.json               # User accounts
├── base_stations.json       # Base station registry
├── certs/                   # TLS certificates (created manually)
└── logs/                    # Log files
```
