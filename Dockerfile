
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    openssl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create necessary directories
RUN mkdir -p certs logs

# Set proper permissions for configuration files and entrypoint
RUN chmod 644 bssci_config.py endpoints.json && \
    chown root:root bssci_config.py endpoints.json && \
    touch .env && chmod 666 .env && \
    chmod +x docker-entrypoint.sh

# Expose ports
EXPOSE 16018 5000

# Run the entrypoint script which generates certificates and then launches the app
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "web_main.py"]
