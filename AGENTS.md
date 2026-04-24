# AGENTS.md - BSSCI Service Center

## Entry Points

- **With Web UI (dev)**: `python web_main.py` → serves http://localhost:5000
- **Service only (prod)**: `python main.py` → no web interface
- **Docker**: `docker-compose up -d --build`

## Key Files

- `bssci_config.py` - Main config (TLS port, MQTT, auto-detach)
- `.env` - Environment variables (broker, credentials)
- `endpoints.json` - Sensor configuration (auto-persisted)
- `TLSServer.py` - Core TLS server (port 16018)
- `mqtt_interface.py` - MQTT client
- `web_ui.py` - Flask web interface

## Important Ports

| Service | Internal | Docker |
|---------|----------|--------|
| TLS Server | 16018 | 16019 |
| Web UI | 5000 | 5056 |

## Quick Commands

```bash
# Development with web UI
python web_main.py

# Production (no web)
python main.py

# Docker
docker-compose up -d --build
docker-compose -f docker-compose.live-update.yml up -d
```

## Architecture

- Flask app runs in daemon thread, async TLS server + MQTT client in main thread
- Queues: `mqtt_out_queue` (to broker), `mqtt_in_queue` (from broker)
- Web UI accesses TLS server via global `tls_server_instance` set by `web_main.set_tls_server()`

## MQTT Topics

- Registration: `{BASE_TOPIC}/ep/{EUI}/register`
- Commands: `{BASE_TOPIC}/ep/{EUI}/cmd` (attach/detach/status)
- Uplink: `{BASE_TOPIC}/ep/{EUI}/ul`
- Legacy `/bssci/ep/eui/` also supported

## Linting

Dev dependencies in requirements.txt: flake8, black, isort

## Configuration Defaults

- TLS port: `16018` (bssci_config.py default, .env.example shows 8000 but that's overridden)
- Default BASE_TOPIC: `bssci/` (not "mioty" - important for MQTT)
- Sensor config: `endpoints.json`
- Web auth: `users.json`

## Documentation

```bash
npm run docs:dev    # Development server
npm run docs:build # Build static docs
```