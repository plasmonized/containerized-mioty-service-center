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
    
    # Ensure proper permissions on log directory
    mkdir -p /app/logs
    chmod 755 /app/logs

    # Ensure certificates directory exists
    mkdir -p /app/certs

    # Handle Synology Docker setup
    if [ "$SYNOLOGY_DOCKER" = "1" ]; then
        echo "Synology Docker mode detected - copying config files to writable locations"
        
        if [ -f "/tmp/host_bssci_config.py" ]; then
            cp /tmp/host_bssci_config.py /app/bssci_config.py
        fi
        
        if [ -f "/tmp/host_endpoints.json" ]; then
            cp /tmp/host_endpoints.json /app/endpoints.json
        fi
        
        if [ -f "/tmp/host_.env" ]; then
            cp /tmp/host_.env /app/.env
        fi
        
        touch /app/.env 2>/dev/null || true
        chmod 644 /app/bssci_config.py /app/endpoints.json 2>/dev/null || true
        chmod 666 /app/.env 2>/dev/null || true
    else
        touch /app/.env 2>/dev/null || true
        chmod 644 /app/bssci_config.py /app/endpoints.json 2>/dev/null || true
        chmod 666 /app/.env 2>/dev/null || true
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