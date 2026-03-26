
#!/bin/bash
set -e

echo "=== BSSCI Service Center Startup ==="

# Check for Live Update Mode
if [ "$ENABLE_LIVE_UPDATE" = "1" ]; then
    echo "Live Update Mode ENABLED"
    APP_DIR="/app-data"
    
    # Create writable app directory if it doesn't exist
    mkdir -p $APP_DIR
    
    # Copy application files on first run or if VERSION changed
    if [ ! -f "$APP_DIR/web_main.py" ]; then
        echo "First run: Copying application files to writable volume..."
        cp -r /app/* $APP_DIR/ 2>/dev/null || true
        echo "Application files copied to $APP_DIR"
    else
        # Check if image has newer version
        if [ -f "/app/VERSION" ] && [ -f "$APP_DIR/VERSION" ]; then
            IMAGE_VERSION=$(cat /app/VERSION)
            DATA_VERSION=$(cat $APP_DIR/VERSION)
            if [ "$IMAGE_VERSION" != "$DATA_VERSION" ]; then
                echo "New image version detected ($IMAGE_VERSION vs $DATA_VERSION)"
                echo "Keeping existing files (use web UI to update or remove $APP_DIR to reset)"
            fi
        fi
    fi
    
    # Ensure directories exist
    mkdir -p $APP_DIR/logs $APP_DIR/certs $APP_DIR/data
    
    # Copy certs from mounted volume if available
    if [ -d "/certs" ] && [ "$(ls -A /certs 2>/dev/null)" ]; then
        cp -r /certs/* $APP_DIR/certs/ 2>/dev/null || true
    fi
    
    # Copy config from mounted volume if available
    if [ -f "/config/endpoints.json" ]; then
        cp /config/endpoints.json $APP_DIR/endpoints.json 2>/dev/null || true
    fi
    if [ -f "/config/bssci_config.py" ]; then
        cp /config/bssci_config.py $APP_DIR/bssci_config.py 2>/dev/null || true
    fi
    if [ -f "/config/.env" ]; then
        cp /config/.env $APP_DIR/.env 2>/dev/null || true
    fi
    
    cd $APP_DIR
    echo "Working directory: $APP_DIR (writable)"
else
    echo "Standard Mode (read-only, Live Updates DISABLED)"
    echo "Set ENABLE_LIVE_UPDATE=1 to enable in-app updates"
    APP_DIR="/app"

    # Ensure required directories exist
    mkdir -p /app/config /app/data /app/logs /app/certs
    chmod 755 /app/logs

    # --- Populate /app/config with defaults on first run ---

    # .env: copy from bundled example if not present
    if [ ! -f /app/config/.env ]; then
        echo "Creating default config/.env from .env.example..."
        cp /app/.env.example /app/config/.env 2>/dev/null || touch /app/config/.env
        chmod 666 /app/config/.env
    fi

    # endpoints.json
    if [ ! -f /app/config/endpoints.json ]; then
        echo "Creating default config/endpoints.json..."
        cp /app/endpoints.json /app/config/endpoints.json 2>/dev/null || echo '[]' > /app/config/endpoints.json
        chmod 644 /app/config/endpoints.json
    fi

    # users.json
    if [ ! -f /app/config/users.json ]; then
        echo "Creating default config/users.json..."
        cp /app/users.json /app/config/users.json 2>/dev/null || echo '{"users":{}}' > /app/config/users.json
        chmod 644 /app/config/users.json
    fi

    # coverage_positions.json
    if [ ! -f /app/config/coverage_positions.json ]; then
        echo "Creating default config/coverage_positions.json..."
        echo '{}' > /app/config/coverage_positions.json
        chmod 644 /app/config/coverage_positions.json
    fi

    # coverage_floorplan.txt
    if [ ! -f /app/config/coverage_floorplan.txt ]; then
        touch /app/config/coverage_floorplan.txt
        chmod 644 /app/config/coverage_floorplan.txt
    fi

    # --- Populate /app/data with defaults on first run ---

    if [ ! -f /app/data/base_stations.json ]; then
        echo "Creating default data/base_stations.json..."
        echo '{"base_stations":{}}' > /app/data/base_stations.json
        chmod 644 /app/data/base_stations.json
    fi

fi

# Generate self-signed certificates if they don't exist
CERT_DIR="$APP_DIR/certs"
mkdir -p $CERT_DIR

if [ ! -f "$CERT_DIR/ca_cert.pem" ] || [ ! -f "$CERT_DIR/service_center_cert.pem" ] || [ ! -f "$CERT_DIR/service_center_key.pem" ]; then
    echo "Generating SSL certificates in $CERT_DIR..."
    
    openssl genrsa -out $CERT_DIR/ca_key.pem 4096
    openssl req -new -x509 -days 365 -key $CERT_DIR/ca_key.pem -out $CERT_DIR/ca_cert.pem -subj "/C=US/ST=State/L=City/O=Organization/CN=BSSCI-CA"
    openssl genrsa -out $CERT_DIR/service_center_key.pem 4096
    openssl req -new -key $CERT_DIR/service_center_key.pem -out $CERT_DIR/service_center.csr -subj "/C=US/ST=State/L=City/O=Organization/CN=BSSCI-ServiceCenter"
    openssl x509 -req -in $CERT_DIR/service_center.csr -CA $CERT_DIR/ca_cert.pem -CAkey $CERT_DIR/ca_key.pem -CAcreateserial -out $CERT_DIR/service_center_cert.pem -days 365
    rm $CERT_DIR/service_center.csr
    
    echo "SSL certificates generated successfully"
fi

echo "Starting BSSCI Service Center..."
exec "$@"
