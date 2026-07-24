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
AUTO_DETACH_WARNING_TIMEOUT = int(
    os.getenv("AUTO_DETACH_WARNING_TIMEOUT", "129600")
)  # 36 hours in seconds
AUTO_DETACH_CHECK_INTERVAL = int(
    os.getenv("AUTO_DETACH_CHECK_INTERVAL", "3600")
)  # Check every hour

# Timezone Configuration
TIMEZONE = os.getenv("TIMEZONE", "Europe/Berlin")  # Default to Europe/Berlin (CET/CEST)

# Update Channel Configuration
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "stable")

# TLS Compatibility Configuration
# TLS_REQUIRE_CLIENT_CERT: require base stations to present a CA-signed client certificate (mutual TLS)
# TLS_COMPAT_MODE: lower OpenSSL security level for embedded TLS stacks (older ciphers/smaller keys)
TLS_REQUIRE_CLIENT_CERT = os.getenv("TLS_REQUIRE_CLIENT_CERT", "true").lower() == "true"
TLS_COMPAT_MODE = os.getenv("TLS_COMPAT_MODE", "false").lower() == "true"

# Connector toggles
# MQTT_ENABLED: set false to disable MQTT publishing (web UI still works)
MQTT_ENABLED = os.getenv("MQTT_ENABLED", "true").lower() == "true"
# SCACI_ENABLED: set true to start the SC↔AC SCACI interface listener
SCACI_ENABLED = os.getenv("SCACI_ENABLED", "false").lower() == "true"

# SCACI (SC ↔ Application Center Interface) Configuration
SCACI_HOST = os.getenv("SCACI_HOST", "0.0.0.0")
SCACI_PORT = int(os.getenv("SCACI_PORT", "16019"))
# By default reuse the same TLS certs as BSSCI; override with SCACI_CERT_FILE etc.
SCACI_CERT_FILE = os.getenv("SCACI_CERT_FILE", CERT_FILE)
SCACI_KEY_FILE = os.getenv("SCACI_KEY_FILE", KEY_FILE)
SCACI_CA_FILE = os.getenv("SCACI_CA_FILE", CA_FILE)
SCACI_REQUIRE_CLIENT_CERT = os.getenv("SCACI_REQUIRE_CLIENT_CERT", "true").lower() == "true"
