import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "16018"))

CERT_FILE = os.getenv("CERT_FILE", "certs/service_center_cert.pem")
KEY_FILE = os.getenv("KEY_FILE", "certs/service_center_key.pem")
CA_FILE = os.getenv("CA_FILE", "certs/ca_cert.pem")

# MQTT Configuration - read from .env
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
BASE_TOPIC = os.getenv("BASE_TOPIC", "bssci/")

SENSOR_CONFIG_FILE = os.getenv("SENSOR_CONFIG_FILE", "endpoints.json")
BASE_STATION_CONFIG_FILE = os.getenv("BASE_STATION_CONFIG_FILE", "base_stations.json")
STATUS_INTERVAL = int(os.getenv("STATUS_INTERVAL", "30"))
DEDUPLICATION_DELAY = float(os.getenv("DEDUPLICATION_DELAY", "2.0"))

# Auto-detach Configuration
AUTO_DETACH_ENABLED = os.getenv("AUTO_DETACH_ENABLED", "true").lower() == "true"
AUTO_DETACH_TIMEOUT = int(os.getenv("AUTO_DETACH_TIMEOUT", "259200"))  # 72 hours in seconds
AUTO_DETACH_WARNING_TIMEOUT = int(os.getenv("AUTO_DETACH_WARNING_TIMEOUT", "129600"))  # 36 hours in seconds
AUTO_DETACH_CHECK_INTERVAL = int(os.getenv("AUTO_DETACH_CHECK_INTERVAL", "3600"))  # Check every hour

# Timezone Configuration
TIMEZONE = os.getenv("TIMEZONE", "Europe/Berlin")  # Default to Europe/Berlin (CET/CEST)

# Update Channel Configuration
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "stable")