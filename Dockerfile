
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create necessary directories and make entrypoint executable
RUN mkdir -p certs logs config data \
    && chmod +x docker-entrypoint.sh

# Expose ports
EXPOSE 16018 5000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "web_main.py"]
