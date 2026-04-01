
# BSSCI Service Center - Docker Deployment

This guide explains how to deploy the BSSCI Service Center using Docker and Docker Compose.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+

## Quick Start

### Development Deployment

```bash
# Build and start the service
docker-compose up --build

# Run in background
docker-compose up -d --build
```

The service will be available at:
- Web UI: http://localhost:5056
- TLS Server: localhost:16019

### Production Deployment

```bash
# Use production configuration
docker-compose -f docker-compose.prod.yml up -d --build
```

The service will be available at:
- Web UI: http://localhost:5000
- TLS Server: localhost:16018

## Configuration

### Environment Variables

Set these in your environment or `docker-compose.yml`:

```bash
UID=1000          # User ID for file permissions
GID=1000          # Group ID for file permissions
```

The application configuration lives in `config/.env`. On first run this file is
auto-generated from the bundled `.env.example`. Edit it afterwards to set your
MQTT broker, credentials, and other settings.

### Volumes

The following directories are mounted as volumes:

| Host directory | Container path | Mode | Contents |
|----------------|----------------|------|----------|
| `./certs`  | `/app/certs`  | read-write | SSL certificates (writable so the container can auto-generate them) |
| `./config` | `/app/config` | read-write | `.env`, `endpoints.json`, `users.json`, and other config files |
| `./data`   | `/app/data`   | read-write | `base_stations.json` and other runtime data |
| `./logs`   | `/app/logs`   | read-write | Application logs |

On first run, any missing file in `config/` or `data/` is automatically bootstrapped from the bundled image defaults.

### Certificates

The container will automatically generate self-signed SSL certificates if none are provided in the `./certs` directory.

For production, provide your own certificates:

```
certs/
├── ca_cert.pem
├── ca_key.pem
├── service_center_cert.pem
└── service_center_key.pem
```

#### Base Station Certificates

Each base station requires its own client certificate signed by the shared CA. The Service Center manages these automatically:

- **Auto-generation on add**: When a base station is added via the Web UI or `POST /api/base-stations`, a certificate is generated automatically (default: `generate_cert=true`).
- **Manual generation**: Trigger certificate generation at any time via the Web UI (Base Stations page) or the API:
  ```http
  POST /api/base-stations/<eui>/certificate/generate
  ```
- **Download**: Retrieve the certificate bundle (key + cert) as a ZIP file:
  ```http
  GET /api/base-stations/<eui>/certificate/download
  ```

Each base station gets its own subdirectory under `./certs`, so multiple base stations are fully supported without conflicts:

```
certs/
├── ca_cert.pem                       # shared CA
├── ca_key.pem
├── service_center_cert.pem
├── service_center_key.pem
├── bs_aabbccddeeff0011/              # Base Station 1
│   ├── aabbccddeeff0011_cert.pem
│   └── aabbccddeeff0011_key.pem
└── bs_1122334455667788/              # Base Station 2
    ├── 1122334455667788_cert.pem
    └── 1122334455667788_key.pem
```

Because `./certs` is mounted as a writable volume (`:rw`), all generated certificates are persisted on the host and survive container restarts.

## Management Commands

```bash
# View logs
docker-compose logs -f

# Stop service
docker-compose down

# Restart service
docker-compose restart

# Update and restart
docker-compose pull && docker-compose up -d

# Remove everything (including volumes)
docker-compose down -v
```

## Health Check

The container includes a health check that verifies both the TLS server (port 16018) and Web UI (port 5000) are responding.

Check health status:
```bash
docker-compose ps
```

## Troubleshooting

### Permission Issues

If you encounter permission issues with logs or certificates:

```bash
# Set correct ownership
sudo chown -R $USER:$USER certs/ config/ data/ logs/

# Or run with specific user
UID=$(id -u) GID=$(id -g) docker-compose up
```

### Certificate Issues

Regenerate certificates:

```bash
# Remove old certificates
rm -rf certs/*

# Restart container (will auto-generate)
docker-compose restart
```

### Port Conflicts

If ports are already in use, modify the port mappings in `docker-compose.yml`:

```yaml
ports:
  - "16020:16018"  # Change external port
  - "5057:5000"    # Change external port
```

### Security Notes

- Change default MQTT credentials via the web UI (Settings → Configuration) or in `config/.env`
- Use proper SSL certificates for production
- Restrict network access to required ports only
- Regular security updates of base images
