import csv
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from datetime import UTC, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

import bssci_config
from observability import ERROR_CODES, configure_logging

# Global TLS server instance reference
tls_server_instance = None
# Trusted base directory for all certificate file operations.
CERTS_BASE_DIR = Path("certs").resolve()

# Uptime tracking
bs_uptime_events: dict[str, list[dict[str, str]]] = {}
_last_known_bs_status: dict[str, dict[str, str | int]] = {}


def record_bs_event(eui, event_type):
    eui = eui.lower()
    if eui not in bs_uptime_events:
        bs_uptime_events[eui] = []
    bs_uptime_events[eui].append({"event": event_type, "timestamp": datetime.now(UTC).isoformat()})
    if len(bs_uptime_events[eui]) > 500:
        bs_uptime_events[eui] = bs_uptime_events[eui][-500:]


def _track_bs_status_changes(current_statuses):
    global _last_known_bs_status
    for eui, status in current_statuses.items():
        prev = _last_known_bs_status.get(eui)
        if prev != status:
            if status == "connected":
                record_bs_event(eui, "connected")
            elif prev == "connected" and status != "connected":
                record_bs_event(eui, "disconnected")
    _last_known_bs_status = dict(current_statuses)


def _validate_eui(eui):
    return bool(re.match(r"^[0-9a-f]{16}$", eui.lower()))


def _safe_certs_path(*parts: str) -> Path:
    for part in parts:
        part_path = Path(part)
        if not part or part_path.is_absolute() or len(part_path.parts) > 1 or ".." in part_path.parts:
            logger.warning(
                "Blocked invalid certificate path part",
                extra={"error_code": ERROR_CODES["WEB_UI_CERT_PATH_INVALID"]},
            )
            raise ValueError("Invalid certificate path")

    candidate = (CERTS_BASE_DIR / Path(*parts)).resolve()
    if not candidate.is_relative_to(CERTS_BASE_DIR):
        logger.warning(
            "Blocked certificate path traversal attempt",
            extra={"error_code": ERROR_CODES["WEB_UI_CERT_PATH_INVALID"]},
        )
        raise ValueError("Invalid certificate path")
    return candidate


def _ensure_ca_exists():
    if os.path.exists("certs/ca_cert.pem") and os.path.exists("certs/ca_key.pem"):
        return True
    os.makedirs("certs", exist_ok=True)
    result = subprocess.run(
        ["openssl", "genrsa", "-out", "certs/ca_key.pem", "2048"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return False
    result = subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-x509",
            "-key",
            "certs/ca_key.pem",
            "-out",
            "certs/ca_cert.pem",
            "-days",
            "365",
            "-subj",
            "/C=US/ST=State/L=City/O=BSSCI/CN=BSSCI-CA",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0


def _generate_bs_certificate(eui):
    eui = eui.lower()
    if not _validate_eui(eui):
        return False, "Invalid EUI format"
    if not _ensure_ca_exists():
        return False, "Failed to ensure CA exists"
    bs_cert_dir = _safe_certs_path(f"bs_{eui}")
    bs_cert_dir.mkdir(parents=True, exist_ok=True)
    key_path = _safe_certs_path(f"bs_{eui}", f"{eui}_key.pem")
    csr_path = _safe_certs_path(f"bs_{eui}", f"{eui}.csr")
    cert_path = _safe_certs_path(f"bs_{eui}", f"{eui}_cert.pem")
    result = subprocess.run(
        ["openssl", "genrsa", "-out", str(key_path), "2048"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return False, f"Key generation failed: {result.stderr}"
    result = subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-key",
            str(key_path),
            "-out",
            str(csr_path),
            "-subj",
            f"/C=US/ST=State/L=City/O=BSSCI/CN={eui}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return False, f"CSR generation failed: {result.stderr}"
    result = subprocess.run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(csr_path),
            "-CA",
            "certs/ca_cert.pem",
            "-CAkey",
            "certs/ca_key.pem",
            "-CAcreateserial",
            "-out",
            str(cert_path),
            "-days",
            "365",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return False, f"Certificate signing failed: {result.stderr}"
    if csr_path.exists():
        csr_path.unlink()
    now = datetime.now(UTC)
    expires = now + timedelta(days=365)
    config = load_base_station_config()
    if eui in config.get("base_stations", {}):
        config["base_stations"][eui]["cert_generated"] = now.strftime("%Y-%m-%dT%H:%M:%S")
        config["base_stations"][eui]["cert_expires"] = expires.strftime("%Y-%m-%dT%H:%M:%S")
        save_base_station_config(config)
    return True, "Certificate generated successfully"


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bssci-service-secret-key-change-me")
configure_logging(__name__)

# Configure logger for this module
logger = logging.getLogger(__name__)


# User management functions
def load_users():
    """Load users from users.json file"""
    try:
        with open("users.json") as f:
            return json.load(f)
    except Exception as e:
        logger.error(
            f"Failed to load users: {e}",
            extra={"error_code": ERROR_CODES["WEB_UI_USER_STORE_ERROR"]},
        )
        return {"users": {}, "role_permissions": {}}


def save_users(users_data):
    """Save users to users.json file"""
    try:
        with open("users.json", "w") as f:
            json.dump(users_data, f, indent=2)
        return True
    except Exception as e:
        logger.error(
            f"Failed to save users: {e}",
            extra={"error_code": ERROR_CODES["WEB_UI_USER_STORE_ERROR"]},
        )
        return False


def get_current_user():
    """Get current logged in user info"""
    if "username" not in session:
        return None
    users_data = load_users()
    username = session.get("username")
    if username in users_data.get("users", {}):
        user = users_data["users"][username].copy()
        user["username"] = username
        role = user.get("role", "viewer")
        user["permissions"] = users_data.get("role_permissions", {}).get(role, {})
        return user
    return None


def get_user_permissions():
    """Get permissions for current user"""
    user = get_current_user()
    if user:
        return user.get("permissions", {})
    return {}


def login_required(f):
    """Decorator to require login"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Login required"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def role_required(*roles):
    """Decorator to require specific role(s)"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Login required"}), 401
                return redirect(url_for("login"))
            if user.get("role") not in roles:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Insufficient permissions"}), 403
                return redirect(url_for("index"))
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def permission_required(permission):
    """Decorator to require specific permission"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            perms = get_user_permissions()
            if not perms.get(permission, False):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Insufficient permissions"}), 403
                return redirect(url_for("index"))
            return f(*args, **kwargs)

        return decorated_function

    return decorator


@app.errorhandler(500)
def internal_error(error):
    """Handle internal server errors and return JSON"""
    app.logger.error(f"Internal server error: {error}")
    if request.path.startswith("/api/"):
        return (
            jsonify(
                {
                    "error": "Internal server error",
                    "running": False,
                    "service_type": "web_ui",
                    "tls_server": {"active": False},
                    "mqtt_broker": {"active": False},
                    "base_stations": {
                        "total_connected": 0,
                        "total_connecting": 0,
                        "connected": [],
                        "connecting": [],
                    },
                }
            ),
            500,
        )
    return error


@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors for API endpoints"""
    if request.path.startswith("/api/"):
        return jsonify({"error": "API endpoint not found"}), 404
    return error


@app.before_request
def ensure_json_api():
    """Ensure API endpoints always return JSON, even on error"""
    if request.path.startswith("/api/"):
        # Set content type to JSON for all API requests
        if not request.is_json and request.method in ["POST", "PUT", "PATCH"]:
            # For non-JSON requests to API, try to handle gracefully
            pass


# Global variables for log storage and configuration
log_entries: list[dict[str, Any]] = []
max_log_entries = 1000


# Custom log handler to capture all logs with timezone support
class WebUILogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        # Use configured timezone
        self._update_timezone()

    def _update_timezone(self):
        """Update timezone from config"""
        try:
            import zoneinfo

            self.tz = zoneinfo.ZoneInfo(bssci_config.TIMEZONE)
            self.use_zoneinfo = True
        except Exception:
            # Fallback to UTC+1 (CET)
            self.tz = timezone(timedelta(hours=1))
            self.use_zoneinfo = False

    def emit(self, record):
        global log_entries

        # Filter out noisy web request logs to reduce clutter
        if record.name == "werkzeug" and any(
            x in record.getMessage()
            for x in [
                "GET /api/",
                "GET /logs",
                "GET /sensors",
                "GET /config",
                "GET /",
                "GET /static/",
            ]
        ):
            return  # Skip web request logs

        # Convert UTC timestamp to local timezone
        utc_time = datetime.fromtimestamp(record.created, tz=UTC)
        local_time = utc_time.astimezone(self.tz)
        current_time = local_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        message = record.getMessage()

        # Check if this exact message was logged in the last second (duplicate detection)
        if log_entries:
            last_entry = log_entries[-1]
            try:
                last_time = datetime.strptime(last_entry["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
                time_diff = abs((local_time.replace(tzinfo=None) - last_time).total_seconds())

                if (
                    time_diff < 1.0  # Within 1 second
                    and last_entry["message"] == message
                    and last_entry["logger"] == record.name
                ):
                    return  # Skip duplicate message
            except:
                pass  # If timestamp parsing fails, continue with logging

        log_entry = {
            "timestamp": current_time,
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "source": "memory",
        }
        log_entries.append(log_entry)

        # Keep only the last max_log_entries
        if len(log_entries) > max_log_entries:
            log_entries = log_entries[-max_log_entries:]


# Add our custom handler to the root logger (only once)
if not any(isinstance(h, WebUILogHandler) for h in logging.getLogger().handlers):
    web_handler = WebUILogHandler()
    logging.getLogger().addHandler(web_handler)
    configured_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.getLogger().setLevel(getattr(logging, configured_level, logging.INFO))


@app.context_processor
def inject_user():
    """Inject user info into all templates"""
    user = get_current_user()
    return {
        "current_user": user,
        "user_permissions": user.get("permissions", {}) if user else {},
        "visible_tabs": (user.get("permissions", {}).get("visible_tabs", []) if user else []),
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        users_data = load_users()
        user = users_data.get("users", {}).get(username)
        if user and user.get("password") == password:
            session["username"] = username
            logger.info(f"User '{username}' logged in")
            return redirect(url_for("index"))
        error = "Ungültiger Benutzername oder Passwort"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    username = session.get("username", "Unknown")
    session.clear()
    logger.info(f"User '{username}' logged out")
    return redirect(url_for("login"))


@app.route("/api/users", methods=["GET", "POST", "PUT", "DELETE"])
@login_required
@role_required("admin")
def api_users():
    """Manage users (admin only)"""
    users_data = load_users()

    if request.method == "GET":
        users_list = []
        for username, data in users_data.get("users", {}).items():
            users_list.append(
                {
                    "username": username,
                    "name": data.get("name", ""),
                    "role": data.get("role", "viewer"),
                }
            )
        return jsonify(
            {
                "users": users_list,
                "roles": list(users_data.get("role_permissions", {}).keys()),
            }
        )

    elif request.method == "POST":
        data = request.get_json()
        username = data.get("username", "").strip()
        if not username or username in users_data.get("users", {}):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Benutzername ungültig oder bereits vorhanden",
                    }
                ),
                400,
            )
        users_data["users"][username] = {
            "password": data.get("password", "password123"),
            "role": data.get("role", "viewer"),
            "name": data.get("name", username),
        }
        save_users(users_data)
        return jsonify({"success": True})

    elif request.method == "PUT":
        data = request.get_json()
        username = data.get("username")
        if username not in users_data.get("users", {}):
            return jsonify({"success": False, "error": "Benutzer nicht gefunden"}), 404
        if data.get("password"):
            users_data["users"][username]["password"] = data["password"]
        if "role" in data:
            users_data["users"][username]["role"] = data["role"]
        if "name" in data:
            users_data["users"][username]["name"] = data["name"]
        save_users(users_data)
        return jsonify({"success": True})

    elif request.method == "DELETE":
        data = request.get_json()
        username = data.get("username")
        if username == session.get("username"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Eigenen Benutzer kann nicht gelöscht werden",
                    }
                ),
                400,
            )
        if username in users_data.get("users", {}):
            del users_data["users"][username]
            save_users(users_data)
        return jsonify({"success": True})


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/sensors")
@login_required
def sensors():
    try:
        with open(bssci_config.SENSOR_CONFIG_FILE) as f:
            sensors = json.load(f)
    except:
        sensors = []
    return render_template("sensors.html", sensors=sensors)


@app.route("/api/sensors", methods=["GET"])
@login_required
def get_sensors():
    try:
        global tls_server_instance
        tls_server = tls_server_instance

        # Load sensors from config file first
        sensor_status = {}
        try:
            sensor_file = getattr(bssci_config, "SENSOR_CONFIG_FILE", "endpoints.json")
            print(f"Loading sensors from file: {sensor_file}")
            with open(sensor_file) as f:
                sensors = json.load(f)
                print(f"Loaded {len(sensors)} sensors from file")

                # Initialize sensor status from config file
                for sensor in sensors:
                    eui = sensor["eui"].upper()
                    sensor_status[eui] = {
                        "eui": sensor["eui"].upper(),
                        "nwKey": sensor["nwKey"],
                        "shortAddr": sensor["shortAddr"],
                        "bidi": sensor["bidi"],
                        "registered": False,
                        "registration_info": {},
                        "base_stations": [],
                        "missing_registrations": [],
                        "total_registrations": 0,
                        "total_available_bases": 0,
                        "preferredDownlinkPath": sensor.get("preferredDownlinkPath", None),
                        "activity_status": "no_data",
                        "hours_since_last_seen": 0,
                    }

                # Get connected base stations list for missing registration tracking
                connected_bases = []
                if tls_server and hasattr(tls_server, "connected_base_stations"):
                    connected_bases = list(tls_server.connected_base_stations.values())
                    # Update total available bases for all sensors
                    for sensor_eui in sensor_status:
                        sensor_status[sensor_eui]["total_available_bases"] = len(connected_bases)

                # Now safely get real registration data from TLS server
                if tls_server and hasattr(tls_server, "registered_sensors"):
                    try:
                        # Thread-safe access to registered sensors data
                        registered_dict = getattr(tls_server, "registered_sensors", {})
                        print(f"Accessing registration data for {len(registered_dict)} registered sensors")

                        for sensor_eui, reg_data in list(registered_dict.items()):
                            if sensor_eui in sensor_status:
                                try:
                                    # Get base stations list safely
                                    base_stations_list = reg_data.get("base_stations", [])
                                    registrations_list = reg_data.get("registrations", [])

                                    # Calculate missing registrations
                                    missing_bases = [bs for bs in connected_bases if bs not in base_stations_list]

                                    sensor_status[sensor_eui].update(
                                        {
                                            "registered": reg_data.get("status") == "registered",
                                            "base_stations": base_stations_list,
                                            "missing_registrations": missing_bases,
                                            "total_registrations": len(base_stations_list),
                                            "registration_info": {
                                                "status": reg_data.get("status", "unknown"),
                                                "last_update": reg_data.get("registration_time", "Unknown"),
                                                "registrations": registrations_list,
                                            },
                                        }
                                    )

                                    print(
                                        f"Sensor {sensor_eui}: {len(base_stations_list)} base stations - {base_stations_list}"
                                    )

                                except Exception as e:
                                    print(f"Error processing registration data for sensor {sensor_eui}: {e}")

                    except Exception as e:
                        print(f"Error accessing TLS server registration data: {e}")

                # For sensors without registration data, mark all connected bases as missing
                for sensor_eui in sensor_status:
                    if not sensor_status[sensor_eui]["base_stations"]:
                        sensor_status[sensor_eui]["missing_registrations"] = connected_bases.copy()

                print(f"Processed sensor status for {len(sensor_status)} sensors with registration data")
                return jsonify(sensor_status)
        except FileNotFoundError:
            sensor_file = getattr(bssci_config, "SENSOR_CONFIG_FILE", "endpoints.json")
            print(f"Sensor config file not found: {sensor_file}")
            return jsonify({})
        except json.JSONDecodeError as e:
            sensor_file = getattr(bssci_config, "SENSOR_CONFIG_FILE", "endpoints.json")
            print(f"Invalid JSON in sensor config file {sensor_file}: {e}")
            return jsonify({})

    except Exception as e:
        print(f"Error in get_sensors: {e}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/sensors", methods=["POST"])
@login_required
@permission_required("can_edit_sensors")
def add_sensor():
    data = request.json

    try:
        # Ensure EUI is uppercase
        data["eui"] = data["eui"].upper()

        # Step 1: Save directly to endpoints.json
        try:
            with open(bssci_config.SENSOR_CONFIG_FILE) as f:
                sensors = json.load(f)
        except:
            sensors = []

        # Check if sensor already exists
        sensor_updated = False
        for sensor in sensors:
            if sensor["eui"].upper() == data["eui"].upper():
                # Update existing sensor
                sensor.update(data)
                sensor_updated = True
                break

        if not sensor_updated:
            # Add new sensor
            sensors.append(data)

        # Save to file
        with open(bssci_config.SENSOR_CONFIG_FILE, "w") as f:
            json.dump(sensors, f, indent=4)

        # Step 2: Notify TLS server to reload config and send attach requests
        global tls_server_instance
        tls_server = tls_server_instance

        if tls_server and hasattr(tls_server, "reload_sensor_config"):
            try:
                # Reload the sensor configuration in TLS server
                tls_server.reload_sensor_config()

                # Force attach to connected base stations if any
                if hasattr(tls_server, "connected_base_stations") and tls_server.connected_base_stations:
                    print(
                        f"Triggering attach for new sensor {data['eui']} to {len(tls_server.connected_base_stations)} base stations"
                    )

                    # Use simple synchronous method to send attach requests
                    if hasattr(tls_server, "attach_sensor_sync"):
                        attached_count = tls_server.attach_sensor_sync(data["eui"])
                        if attached_count > 0:
                            print(
                                f"Successfully sent attach requests for {data['eui']} to {attached_count} base stations"
                            )
                            return jsonify(
                                {
                                    "success": True,
                                    "message": f"Sensor saved and attach requests sent to {attached_count} base stations",
                                }
                            )
                        else:
                            print(f"Failed to send attach requests for {data['eui']}")
                            return jsonify(
                                {
                                    "success": True,
                                    "message": "Sensor saved but failed to send attach requests",
                                }
                            )
                    else:
                        return jsonify(
                            {
                                "success": True,
                                "message": "Sensor saved but attach function not available",
                            }
                        )
                else:
                    return jsonify(
                        {
                            "success": True,
                            "message": "Sensor saved (no base stations connected for attach)",
                        }
                    )

                return jsonify({"success": True, "message": "Sensor saved and processed"})
            except Exception as e:
                print(f"Error notifying TLS server: {e}")
                return jsonify(
                    {
                        "success": True,
                        "message": "Sensor saved but failed to notify TLS server",
                    }
                )
        else:
            return jsonify(
                {
                    "success": True,
                    "message": "Sensor saved (TLS server not available for attach)",
                }
            )

    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {e!s}"})


@app.route("/api/sensors/<eui>", methods=["DELETE"])
@login_required
@permission_required("can_edit_sensors")
def delete_sensor(eui):
    try:
        with open(bssci_config.SENSOR_CONFIG_FILE) as f:
            sensors = json.load(f)
    except:
        sensors = []

    sensors = [s for s in sensors if s["eui"].upper() != eui.upper()]

    try:
        with open(bssci_config.SENSOR_CONFIG_FILE, "w") as f:
            json.dump(sensors, f, indent=4)
        return jsonify({"success": True, "message": "Sensor deleted successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/sensors/<eui>/attach", methods=["POST"])
@login_required
@permission_required("can_edit_sensors")
def attach_sensor(eui):
    """Attach a specific sensor to all base stations"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance

        if not tls_server:
            return jsonify({"success": False, "message": "TLS server not available"})

        if not hasattr(tls_server, "connected_base_stations") or not tls_server.connected_base_stations:
            return jsonify({"success": False, "message": "No base stations connected"})

        if hasattr(tls_server, "attach_sensor_sync"):
            attached_count = tls_server.attach_sensor_sync(eui)
            bs_count = len(tls_server.connected_base_stations)
            if attached_count > 0:
                return jsonify(
                    {
                        "success": True,
                        "message": f"Sensor {eui} attached to {attached_count}/{bs_count} base stations",
                    }
                )
            else:
                return jsonify(
                    {
                        "success": False,
                        "message": f"Failed to attach sensor {eui} to any base stations",
                    }
                )
        else:
            return jsonify({"success": False, "message": "Attach function not available"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/sensors/<eui>/detach", methods=["POST"])
@login_required
@permission_required("can_edit_sensors")
def detach_sensor(eui):
    """Detach a specific sensor from all base stations"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance
        if tls_server and hasattr(tls_server, "detach_sensor_sync"):
            success = tls_server.detach_sensor_sync(eui)
            return jsonify(
                {
                    "success": success,
                    "message": f"Sensor {eui} {'detached' if success else 'detach failed'}",
                }
            )
        else:
            return jsonify({"success": False, "message": "TLS server not available"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


def _convert_topology_timestamps(receiving_bases, sensor_last_seen):
    """Use the sensor's real last_seen timestamp for all base stations"""
    if not receiving_bases:
        return {}
    result = {}
    for bs_eui, data in receiving_bases.items():
        result[bs_eui] = data.copy()
        if sensor_last_seen and sensor_last_seen > 0:
            result[bs_eui]["last_seen"] = sensor_last_seen
    return result


@app.route("/api/sensors/<eui>/details", methods=["GET"])
@login_required
def get_sensor_details(eui):
    """Get detailed statistics for a specific sensor"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance
        eui_upper = eui.upper()

        # Get base sensor config
        sensor_config = None
        try:
            with open(bssci_config.SENSOR_CONFIG_FILE) as f:
                sensors = json.load(f)
                for s in sensors:
                    if s.get("eui", "").upper() == eui_upper:
                        sensor_config = s
                        break
        except:
            pass

        if not sensor_config:
            return jsonify({"success": False, "message": "Sensor not found"})

        # Get packet statistics
        stats = {}
        if tls_server and hasattr(tls_server, "sensor_packet_stats"):
            stats = tls_server.sensor_packet_stats.get(eui_upper, {})

        # Get topology info
        topology = {}
        if tls_server and hasattr(tls_server, "sensor_topology"):
            topology = tls_server.sensor_topology.get(eui_upper, {})

        # Get registration info
        registration = {}
        if tls_server and hasattr(tls_server, "registered_sensors"):
            registration = tls_server.registered_sensors.get(eui_upper, {})

        # Get preferred downlink path
        downlink_path = {}
        if tls_server and hasattr(tls_server, "preferred_downlink_paths"):
            downlink_path = tls_server.preferred_downlink_paths.get(eui_upper, {})

        # Calculate derived metrics
        avg_snr = stats.get("snr_sum", 0) / stats.get("snr_count", 1) if stats.get("snr_count", 0) > 0 else 0
        avg_rssi = stats.get("rssi_sum", 0) / stats.get("rssi_count", 1) if stats.get("rssi_count", 0) > 0 else 0
        packets_received = stats.get("packets_received", 0)
        packets_lost = stats.get("packets_lost", 0)
        packet_loss_rate = (
            (packets_lost / (packets_received + packets_lost) * 100) if (packets_received + packets_lost) > 0 else 0
        )

        # Calculate send interval (based on last 10 messages if history available)
        send_interval = 0
        if "snr_history" in stats and len(stats["snr_history"]) >= 2:
            history = stats["snr_history"][-10:]
            intervals = []
            for i in range(1, len(history)):
                intervals.append(history[i]["ts"] - history[i - 1]["ts"])
            if intervals:
                send_interval = sum(intervals) / len(intervals)

        # Calculate device health scores
        signal_score = 5.0
        if avg_snr < -5:
            signal_score = 1.0
        elif avg_snr < 0:
            signal_score = 2.0
        elif avg_snr < 5:
            signal_score = 3.0
        elif avg_snr < 10:
            signal_score = 4.0

        energy_score = 3.0  # Default fair
        if stats.get("spreading_factor", 7) <= 7:
            energy_score = 5.0
        elif stats.get("spreading_factor", 7) <= 9:
            energy_score = 4.0
        elif stats.get("spreading_factor", 7) <= 10:
            energy_score = 3.0
        elif stats.get("spreading_factor", 7) <= 11:
            energy_score = 2.0
        else:
            energy_score = 1.0

        # Get gateway count from topology
        gateway_count = len(topology.get("receiving_bases", {})) if topology else 0

        # Calculate duty cycle
        total_airtime_ms = stats.get("total_airtime_ms", 0)
        first_seen = stats.get("first_seen", 0)
        last_seen = stats.get("last_seen", 0)
        observation_time_s = (last_seen - first_seen) if first_seen and last_seen else 1
        duty_cycle = (total_airtime_ms / 1000 / observation_time_s * 100) if observation_time_s > 0 else 0

        response = {
            "success": True,
            "eui": eui_upper,
            "config": sensor_config,
            "first_seen": stats.get("first_seen"),
            "last_seen": stats.get("last_seen"),
            "packets_received": packets_received,
            "packets_lost": packets_lost,
            "packet_loss_rate": round(packet_loss_rate, 2),
            "avg_snr": round(avg_snr, 2),
            "avg_rssi": round(avg_rssi, 2),
            "min_snr": stats.get("min_snr", 0),
            "max_snr": stats.get("max_snr", 0),
            "min_rssi": stats.get("min_rssi", 0),
            "max_rssi": stats.get("max_rssi", 0),
            "current_rssi": (
                stats.get("rssi_sum", 0) / stats.get("rssi_count", 1) if stats.get("rssi_count", 0) > 0 else 0
            ),
            "send_interval": round(send_interval, 1),
            "gateway_count": gateway_count,
            "primary_gateway": topology.get("primary_bs", ""),
            "receiving_gateways": (list(topology.get("receiving_bases", {}).keys()) if topology else []),
            "receiving_bases_details": (
                _convert_topology_timestamps(topology.get("receiving_bases", {}), last_seen) if topology else {}
            ),
            "signal_score": round(signal_score, 1),
            "energy_score": round(energy_score, 1),
            "spreading_factor": stats.get("spreading_factor", 7),
            "data_rate": stats.get("data_rate", "SF7BW125"),
            "frequency_mhz": round(stats.get("frequency_mhz", 0), 3),
            "frame_counter": stats.get("frame_counter", 0),
            "last_airtime_ms": round(stats.get("last_airtime_ms", 0), 2),
            "avg_airtime_ms": (round(total_airtime_ms / packets_received, 2) if packets_received > 0 else 0),
            "total_airtime_ms": round(total_airtime_ms, 2),
            "duty_cycle": round(duty_cycle, 4),
            "snr_history": stats.get("snr_history", [])[-50:],
            "rssi_history": stats.get("rssi_history", [])[-50:],
            "registration": registration,
            "downlink_path": downlink_path,
            "heartbeat": {},
        }

        if tls_server and hasattr(tls_server, "sensor_heartbeat"):
            hb = tls_server.sensor_heartbeat.get(eui_upper, {})
            if hb:
                response["heartbeat"] = {
                    "state": hb.get("state", "unknown"),
                    "avg_interval": round(hb.get("avg_interval", 0), 1),
                    "offline_since": hb.get("offline_since"),
                    "warning_active": hb.get("warning_active", False),
                    "last_seen": hb.get("last_seen"),
                }

        return jsonify(response)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/sensors/attach-all", methods=["POST"])
@login_required
@permission_required("can_edit_sensors")
def attach_all_sensors():
    """Attach all configured sensors to base stations"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance

        if not tls_server:
            return jsonify({"success": False, "message": "TLS server not available"})

        if not hasattr(tls_server, "connected_base_stations") or not tls_server.connected_base_stations:
            return jsonify({"success": False, "message": "No base stations connected"})

        # Get all sensors from config file
        try:
            with open(bssci_config.SENSOR_CONFIG_FILE) as f:
                sensors = json.load(f)
        except:
            sensors = []

        if not sensors:
            return jsonify({"success": False, "message": "No sensors configured to attach"})

        # Force reload sensor config to ensure all sensors are loaded
        tls_server.reload_sensor_config()

        # Send attach requests for all sensors to all connected base stations
        if hasattr(tls_server, "attach_all_sensors_sync"):
            attached_count = tls_server.attach_all_sensors_sync()
            bs_count = len(tls_server.connected_base_stations)
            message = f"Sent attach requests for {attached_count} sensors to {bs_count} base stations"
            return jsonify({"success": True, "message": message})
        else:
            return jsonify(
                {
                    "success": False,
                    "message": "Attach all function not available in TLS server",
                }
            )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/sensors/detach-all", methods=["POST"])
@login_required
@permission_required("can_edit_sensors")
def detach_all_sensors():
    """Detach all sensors from base stations"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance

        if not tls_server:
            return jsonify({"success": False, "message": "TLS server not available"})

        if hasattr(tls_server, "detach_all_sensors_sync"):
            detached_count = tls_server.detach_all_sensors_sync()
            message = f"Successfully detached {detached_count} sensors from all base stations."
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": "Detach all function not available"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/sensors/clear", methods=["POST"])
@login_required
@permission_required("can_edit_sensors")
def clear_all_sensors():
    """Clear all sensor configurations and detach all sensors"""
    try:
        detached_count = 0

        # First detach all sensors from base stations
        global tls_server_instance
        tls_server = tls_server_instance
        if tls_server and hasattr(tls_server, "detach_all_sensors_sync"):
            detached_count = tls_server.detach_all_sensors_sync()

        # Clear the file
        with open(bssci_config.SENSOR_CONFIG_FILE, "w") as f:
            json.dump([], f, indent=4)

        # Also clear from TLS server if available
        if tls_server and hasattr(tls_server, "clear_all_sensors"):
            tls_server.clear_all_sensors()

        message = f"All sensors cleared successfully. Detached {detached_count} sensors from base stations."
        return jsonify({"success": True, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/sensors/reload", methods=["POST"])
@login_required
@permission_required("can_edit_sensors")
def reload_sensors():
    """Force reload sensor configuration in TLS server"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance
        if tls_server:
            tls_server.reload_sensor_config()
            return jsonify(
                {
                    "success": True,
                    "message": "Sensor configuration reloaded successfully",
                }
            )
        else:
            return jsonify({"success": False, "message": "TLS server not available"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/sensors/export", methods=["GET"])
@login_required
def export_sensors():
    """Export all sensors as CSV file"""
    try:
        # Load sensors from config file
        try:
            with open(bssci_config.SENSOR_CONFIG_FILE) as f:
                sensors = json.load(f)
        except:
            sensors = []

        if not sensors:
            return jsonify({"success": False, "message": "No sensors to export"}), 404

        # Create CSV content
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow(["eui", "nwKey", "shortAddr", "bidi"])

        # Write sensor data
        for sensor in sensors:
            writer.writerow(
                [
                    sensor.get("eui", ""),
                    sensor.get("nwKey", ""),
                    sensor.get("shortAddr", ""),
                    "true" if sensor.get("bidi", False) else "false",
                ]
            )

        # Create response with CSV file
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=sensors_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            },
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/sensors/import", methods=["POST"])
@login_required
@permission_required("can_edit_sensors")
def import_sensors():
    """Import sensors from CSV/TXT file"""
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "message": "No file provided"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"success": False, "message": "No file selected"}), 400

        # Read file content
        content = file.read().decode("utf-8")
        lines = content.strip().split("\n")

        if len(lines) < 1:
            return jsonify({"success": False, "message": "File is empty"}), 400

        # Detect delimiter (comma, semicolon, or tab)
        first_line = lines[0]
        if ";" in first_line:
            delimiter = ";"
        elif "\t" in first_line:
            delimiter = "\t"
        else:
            delimiter = ","

        # Parse CSV
        reader = csv.reader(io.StringIO(content), delimiter=delimiter)
        rows = list(reader)

        if len(rows) < 1:
            return jsonify({"success": False, "message": "No data in file"}), 400

        # Check if first row is header
        header = rows[0]
        has_header = any(
            h.lower() in ["eui", "nwkey", "shortaddr", "bidi", "network_key", "short_addr"] for h in header
        )

        if has_header:
            # Map header columns
            header_lower = [h.lower().strip() for h in header]
            eui_idx = next(
                (i for i, h in enumerate(header_lower) if h in ["eui", "mac", "address"]),
                0,
            )
            nwkey_idx = next(
                (i for i, h in enumerate(header_lower) if h in ["nwkey", "network_key", "key", "networkkey"]),
                1,
            )
            shortaddr_idx = next(
                (i for i, h in enumerate(header_lower) if h in ["shortaddr", "short_addr", "shortaddress", "addr"]),
                2,
            )
            bidi_idx = next(
                (i for i, h in enumerate(header_lower) if h in ["bidi", "bidirectional", "bidir"]),
                3,
            )
            data_rows = rows[1:]
        else:
            # Assume order: eui, nwKey, shortAddr, bidi
            eui_idx, nwkey_idx, shortaddr_idx, bidi_idx = 0, 1, 2, 3
            data_rows = rows

        # Load existing sensors
        try:
            with open(bssci_config.SENSOR_CONFIG_FILE) as f:
                existing_sensors = json.load(f)
        except:
            existing_sensors = []

        existing_euis = {s["eui"].upper() for s in existing_sensors}

        imported_count = 0
        updated_count = 0
        errors = []

        for row_idx, row in enumerate(data_rows):
            try:
                if len(row) < 3:  # At least eui, nwKey, shortAddr required
                    errors.append(f"Row {row_idx + 1}: Not enough columns")
                    continue

                eui = row[eui_idx].strip().upper() if eui_idx < len(row) else ""
                nwkey = row[nwkey_idx].strip() if nwkey_idx < len(row) else ""
                shortaddr = row[shortaddr_idx].strip() if shortaddr_idx < len(row) else "0000"
                bidi_val = row[bidi_idx].strip().lower() if bidi_idx < len(row) else "false"
                bidi = bidi_val in ["true", "1", "yes", "on"]

                # Validate EUI
                if not eui or len(eui) < 8:
                    errors.append(f"Row {row_idx + 1}: Invalid EUI '{eui}'")
                    continue

                # Validate nwKey
                if not nwkey or len(nwkey) < 16:
                    errors.append(f"Row {row_idx + 1}: Invalid network key")
                    continue

                sensor_data = {
                    "eui": eui,
                    "nwKey": nwkey,
                    "shortAddr": shortaddr if shortaddr else "0000",
                    "bidi": bidi,
                }

                if eui in existing_euis:
                    # Update existing sensor
                    for s in existing_sensors:
                        if s["eui"].upper() == eui:
                            s.update(sensor_data)
                            break
                    updated_count += 1
                else:
                    # Add new sensor
                    existing_sensors.append(sensor_data)
                    existing_euis.add(eui)
                    imported_count += 1

            except Exception as e:
                errors.append(f"Row {row_idx + 1}: {e!s}")

        # Save to file
        with open(bssci_config.SENSOR_CONFIG_FILE, "w") as f:
            json.dump(existing_sensors, f, indent=4)

        # Reload TLS server config
        global tls_server_instance
        if tls_server_instance and hasattr(tls_server_instance, "reload_sensor_config"):
            tls_server_instance.reload_sensor_config()

        message = f"Import complete: {imported_count} new sensors, {updated_count} updated"
        if errors:
            message += f", {len(errors)} errors"

        return jsonify(
            {
                "success": True,
                "message": message,
                "imported": imported_count,
                "updated": updated_count,
                "errors": errors[:10] if errors else [],  # Limit error messages
            }
        )

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/config")
@login_required
@permission_required("can_edit_config")
def config():
    try:
        # Force reload the config module to get latest values
        import importlib
        import sys

        if "bssci_config" in sys.modules:
            importlib.reload(sys.modules["bssci_config"])

        import bssci_config

        config_data = {
            "LISTEN_HOST": getattr(bssci_config, "LISTEN_HOST", "0.0.0.0"),
            "LISTEN_PORT": getattr(bssci_config, "LISTEN_PORT", 16018),
            "MQTT_BROKER": getattr(bssci_config, "MQTT_BROKER", "localhost"),
            "MQTT_PORT": getattr(bssci_config, "MQTT_PORT", 1883),
            "MQTT_USERNAME": getattr(bssci_config, "MQTT_USERNAME", ""),
            "MQTT_PASSWORD": getattr(bssci_config, "MQTT_PASSWORD", ""),
            "BASE_TOPIC": getattr(bssci_config, "BASE_TOPIC", "bssci/"),
            "STATUS_INTERVAL": getattr(bssci_config, "STATUS_INTERVAL", 30),
            "DEDUPLICATION_DELAY": getattr(bssci_config, "DEDUPLICATION_DELAY", 2.0),
            "AUTO_DETACH_ENABLED": getattr(bssci_config, "AUTO_DETACH_ENABLED", True),
            "AUTO_DETACH_TIMEOUT": getattr(bssci_config, "AUTO_DETACH_TIMEOUT", 259200),
            "AUTO_DETACH_WARNING_TIMEOUT": getattr(bssci_config, "AUTO_DETACH_WARNING_TIMEOUT", 129600),
            "AUTO_DETACH_CHECK_INTERVAL": getattr(bssci_config, "AUTO_DETACH_CHECK_INTERVAL", 3600),
            "TIMEZONE": getattr(bssci_config, "TIMEZONE", "Europe/Berlin"),
            "UPDATE_CHANNEL": getattr(bssci_config, "UPDATE_CHANNEL", "stable"),
        }
        return render_template("config.html", config=config_data)
    except Exception as e:
        print(f"Error loading config page: {e}")
        # Return default config if there's an error
        default_config = {
            "LISTEN_HOST": "0.0.0.0",
            "LISTEN_PORT": 16018,
            "MQTT_BROKER": "localhost",
            "MQTT_PORT": 1883,
            "MQTT_USERNAME": "",
            "MQTT_PASSWORD": "",
            "BASE_TOPIC": "bssci/",
            "STATUS_INTERVAL": 30,
            "DEDUPLICATION_DELAY": 2.0,
            "AUTO_DETACH_ENABLED": True,
            "AUTO_DETACH_TIMEOUT": 259200,
            "AUTO_DETACH_WARNING_TIMEOUT": 129600,
            "AUTO_DETACH_CHECK_INTERVAL": 3600,
            "TIMEZONE": "Europe/Berlin",
            "UPDATE_CHANNEL": "stable",
        }
        return render_template("config.html", config=default_config)


@app.route("/api/config", methods=["POST"])
@login_required
@permission_required("can_edit_config")
def update_config():
    try:
        data = request.json

        # Type safety: Validate request data
        if data is None:
            return jsonify({"success": False, "message": "No JSON data provided"}), 400

        # Values are already in seconds from HTML form (no conversion needed)
        auto_detach_timeout = int(data.get("AUTO_DETACH_TIMEOUT", 259200))
        auto_detach_warning_timeout = int(data.get("AUTO_DETACH_WARNING_TIMEOUT", 129600))
        auto_detach_check_interval = int(data.get("AUTO_DETACH_CHECK_INTERVAL", 3600))

        # Update the .env file - this is the primary configuration source (with type safety)
        env_content = f"""# TLS Server Configuration
LISTEN_HOST={data.get("LISTEN_HOST", "0.0.0.0")}
LISTEN_PORT={data.get("LISTEN_PORT", 16018)}

# SSL/TLS Certificate Configuration
CERT_FILE=certs/service_center_cert.pem
KEY_FILE=certs/service_center_key.pem
CA_FILE=certs/ca_cert.pem

# MQTT Configuration
MQTT_BROKER={data.get("MQTT_BROKER", "localhost")}
MQTT_PORT={data.get("MQTT_PORT", 1883)}
MQTT_USERNAME={data.get("MQTT_USERNAME", "")}
MQTT_PASSWORD={data.get("MQTT_PASSWORD", "")}
BASE_TOPIC={data.get("BASE_TOPIC", "bssci/")}

# Application Configuration
SENSOR_CONFIG_FILE=endpoints.json
STATUS_INTERVAL={data.get("STATUS_INTERVAL", 30)}
DEDUPLICATION_DELAY={data.get("DEDUPLICATION_DELAY", 2.0)}

# Web Interface Configuration
WEB_HOST=0.0.0.0
WEB_PORT=5000
WEB_DEBUG=false

# Auto-detach Configuration
AUTO_DETACH_ENABLED={str(data.get("AUTO_DETACH_ENABLED", True)).lower()}
AUTO_DETACH_TIMEOUT={auto_detach_timeout}
AUTO_DETACH_HOURS={auto_detach_timeout // 3600}
AUTO_DETACH_WARNING_TIMEOUT={auto_detach_warning_timeout}
AUTO_DETACH_WARNING_HOURS={auto_detach_warning_timeout // 3600}
AUTO_DETACH_CHECK_INTERVAL={auto_detach_check_interval}

# Timezone Configuration
TIMEZONE={data.get("TIMEZONE", "Europe/Berlin")}

# Update Channel Configuration
UPDATE_CHANNEL={data.get("UPDATE_CHANNEL", "stable")}

# Logging Configuration
LOG_LEVEL=INFO
LOG_FILE=logs/bssci_service.log

# Security
SECRET_KEY=your-secret-key-here"""

        # Write to .env file with error handling for Docker environments
        try:
            with open(".env", "w") as f:
                f.write(env_content)
        except PermissionError as pe:
            # Try alternative approach for Docker/Synology environments
            try:
                import shutil
                import tempfile

                # Write to temp file first, then move
                with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
                    tmp.write(env_content)
                    tmp_name = tmp.name
                shutil.move(tmp_name, ".env")
            except Exception as fallback_error:
                raise Exception(
                    f"Cannot write .env file. Docker volume not mounted as writable? Original error: {pe}, Fallback error: {fallback_error}"
                )

        # Reload environment variables
        from dotenv import load_dotenv

        load_dotenv(override=True)

        # Force reload of the bssci_config module to pick up new .env values
        import importlib
        import sys

        if "bssci_config" in sys.modules:
            importlib.reload(sys.modules["bssci_config"])

        # Also set key config values directly on the module for immediate effect
        bssci_config.UPDATE_CHANNEL = data.get("UPDATE_CHANNEL", "stable")
        bssci_config.MQTT_BROKER = data.get("MQTT_BROKER", "localhost")
        bssci_config.MQTT_PORT = int(data.get("MQTT_PORT", 1883))
        bssci_config.MQTT_USERNAME = data.get("MQTT_USERNAME", "")
        bssci_config.MQTT_PASSWORD = data.get("MQTT_PASSWORD", "")
        bssci_config.BASE_TOPIC = data.get("BASE_TOPIC", "bssci/")
        bssci_config.STATUS_INTERVAL = int(data.get("STATUS_INTERVAL", 30))
        bssci_config.DEDUPLICATION_DELAY = float(data.get("DEDUPLICATION_DELAY", 2.0))
        bssci_config.AUTO_DETACH_ENABLED = str(data.get("AUTO_DETACH_ENABLED", True)).lower() == "true"
        bssci_config.TIMEZONE = data.get("TIMEZONE", "Europe/Berlin")

        return jsonify(
            {
                "success": True,
                "message": "Configuration updated in .env file and reloaded successfully.",
            }
        )
    except Exception as e:
        logger.error(
            f"Error updating config: {e}",
            extra={"error_code": ERROR_CODES["WEB_UI_CONFIG_UPDATE_ERROR"]},
        )
        return jsonify(
            {
                "success": False,
                "message": "Configuration update failed.",
                "error_code": ERROR_CODES["WEB_UI_CONFIG_UPDATE_ERROR"],
            }
        )


@app.route("/certificates")
@login_required
@permission_required("can_manage_certificates")
def certificates():
    return redirect(url_for("base_stations"))


@app.route("/logs")
@login_required
def logs():
    return render_template("logs.html")


@app.route("/traffic")
@login_required
def traffic():
    return redirect(url_for("health"))


@app.route("/oms")
@login_required
def oms():
    return render_template("oms.html")


@app.route("/health")
@login_required
def health():
    return render_template("health.html")


@app.route("/api/health", methods=["GET"])
@login_required
def get_health_stats():
    """Get comprehensive health statistics for the system"""
    try:
        global tls_server_instance

        result = {
            "system": {
                "uptime": 0,
                "total_sensors": 0,
                "active_sensors": 0,
                "total_base_stations": 0,
                "connected_base_stations": 0,
                "total_packets_received": 0,
                "total_packets_lost": 0,
                "overall_packet_loss_rate": 0,
                "avg_snr": 0,
                "avg_rssi": 0,
            },
            "base_stations": [],
            "sensors": [],
            "snr_rssi_history": [],
        }

        if tls_server_instance:
            # System stats
            start_time = tls_server_instance.traffic_metrics.get("start_time", 0)
            if start_time:
                from datetime import datetime

                result["system"]["uptime"] = int(datetime.now(UTC).timestamp() - start_time)

            result["system"]["total_sensors"] = len(tls_server_instance.sensor_config)
            result["system"]["active_sensors"] = tls_server_instance.get_sensor_online_count()
            result["system"]["total_base_stations"] = len(tls_server_instance.connected_base_stations) + len(
                tls_server_instance.connecting_base_stations
            )
            result["system"]["connected_base_stations"] = len(tls_server_instance.connected_base_stations)

            # Aggregate packet stats
            total_received = 0
            total_lost = 0
            for eui, stats in tls_server_instance.sensor_packet_stats.items():
                total_received += stats.get("packets_received", 0)
                total_lost += stats.get("packets_lost", 0)

            result["system"]["total_packets_received"] = total_received
            result["system"]["total_packets_lost"] = total_lost
            if total_received + total_lost > 0:
                result["system"]["overall_packet_loss_rate"] = round(
                    total_lost / (total_received + total_lost) * 100, 2
                )

            # Base station health
            bs_config = load_base_station_config().get("base_stations", {})
            for writer, bs_eui in tls_server_instance.connected_base_stations.items():
                eui_lower = bs_eui.lower()
                health = tls_server_instance.base_station_health.get(eui_lower, {})
                bs_info = bs_config.get(eui_lower, {})
                result["base_stations"].append(
                    {
                        "eui": eui_lower,
                        "name": bs_info.get("name", ""),
                        "status": "connected",
                        "cpu": health.get("cpu", 0),
                        "memory": health.get("memory", 0),
                        "duty_cycle": health.get("duty_cycle", 0),
                        "uptime": health.get("uptime", 0),
                    }
                )

            # Sensor packet stats
            for eui, stats in tls_server_instance.sensor_packet_stats.items():
                received = stats.get("packets_received", 0)
                lost = stats.get("packets_lost", 0)
                snr_avg = stats.get("snr_sum", 0) / max(stats.get("snr_count", 1), 1)
                rssi_avg = stats.get("rssi_sum", 0) / max(stats.get("rssi_count", 1), 1)
                loss_rate = 0
                if received + lost > 0:
                    loss_rate = round(lost / (received + lost) * 100, 2)

                result["sensors"].append(
                    {
                        "eui": eui.lower(),
                        "packets_received": received,
                        "packets_lost": lost,
                        "packet_loss_rate": loss_rate,
                        "avg_snr": round(snr_avg, 2),
                        "avg_rssi": round(rssi_avg, 2),
                    }
                )

            # Sort sensors by packet loss rate (worst first)
            result["sensors"].sort(key=lambda x: x["packet_loss_rate"], reverse=True)

            # Calculate overall average SNR/RSSI
            total_snr = 0
            total_rssi = 0
            sensor_count = 0
            for stats in tls_server_instance.sensor_packet_stats.values():
                if stats.get("snr_count", 0) > 0:
                    total_snr += stats["snr_sum"] / stats["snr_count"]
                    total_rssi += stats["rssi_sum"] / stats["rssi_count"]
                    sensor_count += 1

            if sensor_count > 0:
                result["system"]["avg_snr"] = round(total_snr / sensor_count, 2)
                result["system"]["avg_rssi"] = round(total_rssi / sensor_count, 2)

            # Include SNR/RSSI history
            result["snr_rssi_history"] = tls_server_instance.snr_rssi_history

            # Calculate signal score distribution based on SNR
            # Excellent: >= 10 dB, Good: 5-10 dB, Fair: 0-5 dB, Poor: -5-0 dB, Critical: < -5 dB
            distribution = {
                "excellent": 0,
                "good": 0,
                "fair": 0,
                "poor": 0,
                "critical": 0,
            }
            for stats in tls_server_instance.sensor_packet_stats.values():
                if stats.get("snr_count", 0) > 0:
                    avg_snr = stats["snr_sum"] / stats["snr_count"]
                    if avg_snr >= 10:
                        distribution["excellent"] += 1
                    elif avg_snr >= 5:
                        distribution["good"] += 1
                    elif avg_snr >= 0:
                        distribution["fair"] += 1
                    elif avg_snr >= -5:
                        distribution["poor"] += 1
                    else:
                        distribution["critical"] += 1
            result["signal_distribution"] = distribution

        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/base-stations")
@login_required
def base_stations():
    return render_template("base_stations.html")


@app.route("/network")
@login_required
def network():
    return render_template("network.html")


@app.route("/coverage")
@login_required
def coverage():
    return redirect(url_for("network"))


@app.route("/api/coverage/topology")
@login_required
def api_coverage_topology():
    """Get sensor topology with SNR/RSSI per base station for coverage heatmap"""
    try:
        global tls_server_instance
        result = {"sensors": {}, "base_stations": []}

        if tls_server_instance and hasattr(tls_server_instance, "sensor_topology"):
            for sensor_eui, topo in tls_server_instance.sensor_topology.items():
                receiving = topo.get("receiving_bases", {})
                if receiving:
                    result["sensors"][sensor_eui] = {"base_stations": {}}
                    for bs_eui, bs_data in receiving.items():
                        result["sensors"][sensor_eui]["base_stations"][bs_eui] = {
                            "snr": bs_data.get("snr", 0),
                            "rssi": bs_data.get("rssi", -100),
                            "count": bs_data.get("count", 0),
                        }

        # Get base station list
        bs_config = load_base_station_config().get("base_stations", {})
        connected_euis = set()
        if tls_server_instance and hasattr(tls_server_instance, "connected_base_stations"):
            for writer, bs_eui in tls_server_instance.connected_base_stations.items():
                connected_euis.add(bs_eui.upper())

        all_bs = set(bs_config.keys())
        all_bs.update(connected_euis)

        for bs_eui in all_bs:
            result["base_stations"].append(bs_eui.upper())

        return jsonify(result)
    except Exception as e:
        return jsonify({"sensors": {}, "base_stations": [], "error": str(e)})


@app.route("/api/coverage/positions", methods=["GET", "POST"])
@login_required
def api_coverage_positions():
    """Get or save coverage map device positions"""
    positions_file = "coverage_positions.json"

    if request.method == "POST":
        perms = get_user_permissions()
        if not perms.get("can_edit_sensors", False):
            return jsonify({"success": False, "error": "Insufficient permissions"}), 403
        try:
            positions = request.get_json()
            with open(positions_file, "w") as f:
                json.dump(positions, f, indent=2)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        try:
            if os.path.exists(positions_file):
                with open(positions_file) as f:
                    return jsonify(json.load(f))
            return jsonify({})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


@app.route("/api/coverage/floorplan", methods=["GET", "POST"])
@login_required
def api_coverage_floorplan():
    """Get or save floorplan image (base64 encoded)"""
    floorplan_file = "coverage_floorplan.txt"

    if request.method == "POST":
        perms = get_user_permissions()
        if not perms.get("can_edit_sensors", False):
            return jsonify({"success": False, "error": "Insufficient permissions"}), 403
        try:
            data = request.get_json()
            image_data = data.get("image", "")
            with open(floorplan_file, "w") as f:
                f.write(image_data)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        try:
            if os.path.exists(floorplan_file):
                with open(floorplan_file) as f:
                    return jsonify({"image": f.read()})
            return jsonify({"image": None})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


@app.route("/api/network")
@login_required
def api_network():
    """Get network topology data for visualization"""
    try:
        global tls_server_instance
        nodes = []
        edges = []

        if tls_server_instance:
            bs_config = load_base_station_config().get("base_stations", {})

            # Add base station nodes
            connected_bs = set()
            for writer, bs_eui in tls_server_instance.connected_base_stations.items():
                connected_bs.add(bs_eui.upper())

            # Get all base stations from topology and connected list
            all_bs = set(connected_bs)
            for sensor_data in tls_server_instance.sensor_topology.values():
                for bs_eui in sensor_data.get("receiving_bases", {}).keys():
                    all_bs.add(bs_eui.upper())

            for bs_eui in all_bs:
                bs_lower = bs_eui.lower()
                config = bs_config.get(bs_lower, {})
                health = tls_server_instance.base_station_health.get(bs_eui, {})

                nodes.append(
                    {
                        "id": f"bs_{bs_eui}",
                        "type": "base_station",
                        "eui": bs_eui,
                        "label": config.get("name", bs_eui[:8] + "..."),
                        "connected": bs_eui in connected_bs,
                        "cpu": health.get("cpu", 0),
                        "memory": health.get("memory", 0),
                        "duty_cycle": health.get("duty_cycle", 0),
                    }
                )

            # Add sensor nodes and edges
            for sensor_eui, topo in tls_server_instance.sensor_topology.items():
                primary_bs = topo.get("primary_bs", "").upper()
                receiving = topo.get("receiving_bases", {})

                # Get sensor name from config if available
                sensor_name = sensor_eui[:8] + "..."
                for sensor in tls_server_instance.sensor_config:
                    if sensor.get("eui", "").upper() == sensor_eui:
                        sensor_name = sensor.get("name", sensor_name)
                        break

                nodes.append(
                    {
                        "id": f"sensor_{sensor_eui}",
                        "type": "sensor",
                        "eui": sensor_eui,
                        "label": sensor_name,
                        "primary_bs": primary_bs,
                        "receiver_count": len(receiving),
                    }
                )

                # Add edges to all receiving base stations
                for bs_eui, stats in receiving.items():
                    bs_upper = bs_eui.upper()
                    edges.append(
                        {
                            "id": f"edge_{sensor_eui}_{bs_upper}",
                            "source": f"sensor_{sensor_eui}",
                            "target": f"bs_{bs_upper}",
                            "primary": bs_upper == primary_bs,
                            "snr": round(stats.get("snr", 0), 2),
                            "rssi": round(stats.get("rssi", 0), 2),
                            "last_seen": stats.get("last_seen", 0),
                            "count": stats.get("count", 0),
                        }
                    )

        return jsonify({"success": True, "nodes": nodes, "edges": edges})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def load_base_station_config():
    """Load base station configuration from JSON file"""
    try:
        config_path = getattr(bssci_config, "BASE_STATION_CONFIG_FILE", "base_stations.json")
        with open(config_path) as f:
            return json.load(f)
    except:
        return {"base_stations": {}}


def save_base_station_config(config):
    """Save base station configuration to JSON file"""
    import os

    config_path = getattr(bssci_config, "BASE_STATION_CONFIG_FILE", "base_stations.json")
    try:
        dir_path = os.path.dirname(config_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
    except:
        pass
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


@app.route("/api/base-stations", methods=["GET"])
@login_required
def get_base_stations():
    """Get all base stations with status and health data"""
    try:
        global tls_server_instance
        config = load_base_station_config()
        bs_config = config.get("base_stations", {})

        connected_bs = {}
        connecting_bs = {}
        bs_health = {}
        bs_sensors = {}
        vm_capable_set = set()

        if tls_server_instance:
            status = tls_server_instance.get_base_station_status()
            for bs in status.get("connected", []):
                eui = bs["eui"].lower()
                connected_bs[eui] = bs
            for bs in status.get("connecting", []):
                eui = bs["eui"].lower()
                connecting_bs[eui] = bs
            if hasattr(tls_server_instance, "base_station_health"):
                bs_health = tls_server_instance.base_station_health
            if hasattr(tls_server_instance, "vm_capable_base_stations"):
                vm_capable_set = {e.lower() for e in tls_server_instance.vm_capable_base_stations}
            if hasattr(tls_server_instance, "sensor_config"):
                for sensor in tls_server_instance.sensor_config:
                    preferred = sensor.get("preferredDownlinkPath", {})
                    if isinstance(preferred, dict):
                        bs_eui = preferred.get("baseStation", "").lower()
                        if bs_eui:
                            bs_sensors[bs_eui] = bs_sensors.get(bs_eui, 0) + 1

        all_euis = set(bs_config.keys()) | set(connected_bs.keys()) | set(connecting_bs.keys())

        result = []
        for eui in all_euis:
            eui_lower = eui.lower()
            bs_data = bs_config.get(eui_lower, {})

            if eui_lower in connected_bs:
                status = "connected"
            elif eui_lower in connecting_bs:
                status = "connecting"
            else:
                status = "offline"

            health = bs_health.get(eui_lower, {})

            result.append(
                {
                    "eui": eui_lower,
                    "name": bs_data.get("name", ""),
                    "tags": bs_data.get("tags", []),
                    "status": status,
                    "configured_ip": bs_data.get("ip", ""),
                    "health": health,
                    "vm_capable": eui_lower in vm_capable_set,
                    "connected_sensors": bs_sensors.get(eui_lower, 0),
                }
            )

        result.sort(
            key=lambda x: (
                x["status"] != "connected",
                x["status"] != "connecting",
                x["eui"],
            )
        )

        current_statuses = {bs["eui"]: bs["status"] for bs in result}
        _track_bs_status_changes(current_statuses)

        return jsonify({"success": True, "base_stations": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/base-stations/certificates/status")
@login_required
@permission_required("can_manage_certificates")
def get_bs_certificates_status():
    """Get cert status for ALL base stations"""
    try:
        config = load_base_station_config()
        bs_config = config.get("base_stations", {})
        result = []
        for eui_key, bs_data in bs_config.items():
            eui_lower = eui_key.lower()
            bs_cert_dir = os.path.join("certs", f"bs_{eui_lower}")
            cert_path = os.path.join(bs_cert_dir, f"{eui_lower}_cert.pem")
            cert_exists = os.path.exists(cert_path)
            cert_expires = bs_data.get("cert_expires", "")
            cert_generated = bs_data.get("cert_generated", "")
            status = "missing"
            if cert_exists and cert_expires:
                try:
                    exp_dt = datetime.strptime(cert_expires, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
                    now = datetime.now(UTC)
                    if exp_dt < now:
                        status = "expired"
                    elif (exp_dt - now).days < 30:
                        status = "expiring_soon"
                    else:
                        status = "valid"
                except:
                    status = "valid" if cert_exists else "missing"
            elif cert_exists:
                status = "valid"
            result.append(
                {
                    "eui": eui_lower,
                    "name": bs_data.get("name", ""),
                    "cert_exists": cert_exists,
                    "cert_status": status,
                    "cert_generated": cert_generated,
                    "cert_expires": cert_expires,
                }
            )
        return jsonify({"success": True, "certificates": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/base-stations/uptime")
@login_required
def get_bs_uptime():
    """Get uptime data for all base stations"""
    try:
        return jsonify({"success": True, "uptime_events": bs_uptime_events})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/base-stations/<eui>", methods=["GET"])
@login_required
def get_base_station(eui):
    """Get single base station details"""
    try:
        config = load_base_station_config()
        bs_data = config.get("base_stations", {}).get(eui.lower(), {})
        return jsonify({"eui": eui.lower(), **bs_data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/base-stations", methods=["POST"])
@login_required
@permission_required("can_edit_sensors")
def add_base_station():
    """Add new base station"""
    try:
        data = request.get_json()
        eui = data.get("eui", "").lower()

        if not eui or not _validate_eui(eui):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Invalid EUI (must be 16 hex characters)",
                    }
                ),
                400,
            )

        config = load_base_station_config()
        if eui in config.get("base_stations", {}):
            return (
                jsonify({"success": False, "error": "Base station already exists"}),
                400,
            )

        config["base_stations"][eui] = {
            "name": data.get("name", ""),
            "tags": data.get("tags", []),
            "ip": data.get("ip", ""),
        }
        save_base_station_config(config)

        generate_cert = data.get("generate_cert", True)
        cert_download_url = None
        if generate_cert:
            success, msg = _generate_bs_certificate(eui)
            if success:
                cert_download_url = f"/api/base-stations/{eui}/certificate/download"

        result = {"success": True}
        if cert_download_url:
            result["cert_download_url"] = cert_download_url
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/base-stations/<eui>", methods=["PUT"])
@login_required
@permission_required("can_edit_sensors")
def update_base_station(eui):
    """Update base station"""
    try:
        data = request.get_json()
        eui = eui.lower()

        config = load_base_station_config()
        if "base_stations" not in config:
            config["base_stations"] = {}

        config["base_stations"][eui] = {
            "name": data.get("name", ""),
            "tags": data.get("tags", []),
            "ip": data.get("ip", ""),
        }
        save_base_station_config(config)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/base-stations/<eui>", methods=["DELETE"])
@login_required
@permission_required("can_edit_sensors")
def delete_base_station(eui):
    """Delete base station from config"""
    try:
        config = load_base_station_config()
        eui = eui.lower()

        if eui in config.get("base_stations", {}):
            del config["base_stations"][eui]
            save_base_station_config(config)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/traffic/metrics")
@login_required
def get_traffic_metrics():
    """Get traffic metrics for visualization"""
    try:
        global tls_server_instance
        if tls_server_instance and hasattr(tls_server_instance, "get_traffic_metrics"):
            data = tls_server_instance.get_traffic_metrics()
            return jsonify({"success": True, **data})
        return jsonify(
            {
                "success": True,
                "metrics": {
                    "messages_in": 0,
                    "messages_out": 0,
                    "messages_dropped": 0,
                    "bytes_in": 0,
                    "bytes_out": 0,
                    "vm_messages": 0,
                    "attach_requests": 0,
                    "detach_requests": 0,
                    "status_requests": 0,
                    "start_time": 0,
                },
                "dedup_stats": {
                    "total_messages": 0,
                    "duplicate_messages": 0,
                    "published_messages": 0,
                },
                "history": [],
                "connections": 0,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/traffic/reset", methods=["POST"])
@login_required
@role_required("admin")
def reset_traffic_metrics():
    """Reset traffic metrics"""
    try:
        global tls_server_instance
        if tls_server_instance and hasattr(tls_server_instance, "reset_traffic_metrics"):
            tls_server_instance.reset_traffic_metrics()
            return jsonify({"success": True, "message": "Traffic metrics reset successfully"})
        return jsonify({"success": False, "message": "TLS server not available"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/oms/meters")
@login_required
def get_oms_meters():
    """Get all tracked OMS meters"""
    try:
        global tls_server_instance
        if tls_server_instance and hasattr(tls_server_instance, "get_oms_meters"):
            meters = tls_server_instance.get_oms_meters()
            return jsonify({"success": True, "meters": list(meters.values())})
        return jsonify({"success": True, "meters": []})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/oms/stats")
@login_required
def get_oms_stats():
    """Get OMS statistics"""
    try:
        global tls_server_instance
        if tls_server_instance and hasattr(tls_server_instance, "get_oms_stats"):
            stats = tls_server_instance.get_oms_stats()
            return jsonify({"success": True, **stats})
        return jsonify({"success": True, "total_meters": 0, "total_messages": 0})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/logs")
@login_required
def get_logs():
    global log_entries

    # Get query parameters for filtering
    level_filter = request.args.get("level", "all").upper()
    logger_filter = request.args.get("logger", "all")
    limit = int(request.args.get("limit", 100))

    # Filter logs based on parameters
    filtered_logs = log_entries

    if level_filter != "ALL":
        filtered_logs = [log for log in filtered_logs if log["level"] == level_filter]

    if logger_filter != "all":
        filtered_logs = [log for log in filtered_logs if logger_filter.lower() in log["logger"].lower()]

    # Return the most recent logs (up to limit)
    recent_logs = filtered_logs[-limit:] if len(filtered_logs) > limit else filtered_logs

    return jsonify(
        {
            "logs": recent_logs,
            "total_logs": len(log_entries),
            "filtered_logs": len(filtered_logs),
            "source": "memory",
        }
    )


# =========================
# UPDATE MANAGEMENT SYSTEM
# =========================


def get_current_version():
    """Get current version from VERSION file or fallback methods"""
    try:
        # First: Try to read VERSION file (preferred method)
        if os.path.exists("VERSION"):
            try:
                with open("VERSION") as f:
                    version = f.read().strip()
                    if version:
                        return f"v{version}" if not version.startswith("v") else version
            except:
                pass

        # Fallback: Try Git commands
        try:
            lock_file = ".git/index.lock"
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                except:
                    pass

            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                commit_hash = result.stdout.strip()

                tag_result = subprocess.run(
                    ["git", "describe", "--tags", "--exact-match", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if tag_result.returncode == 0:
                    return tag_result.stdout.strip()
                else:
                    return f"commit-{commit_hash}"
        except FileNotFoundError:
            pass
        except Exception as e:
            if "No such file or directory" not in str(e):
                print(f"Git command error: {e}")

        # Fallback 1: try to read .git/HEAD directly
        try:
            with open(".git/HEAD") as f:
                head_ref = f.read().strip()
                if head_ref.startswith("ref: refs/heads/"):
                    # Get branch name and try to read commit
                    branch = head_ref.split("/")[-1]
                    ref_path = f".git/refs/heads/{branch}"
                    try:
                        with open(ref_path) as ref_file:
                            commit = ref_file.read().strip()[:7]
                            return f"local-{commit}"
                    except:
                        return f"branch-{branch}"
                else:
                    # Direct commit hash
                    return f"local-{head_ref[:7]}"
        except:
            pass

        # Fallback 2: Use file modification timestamps
        try:
            import time

            main_files = ["main.py", "web_ui.py", "TLSServer.py", "mqtt_interface.py"]
            latest_time = 0
            for file in main_files:
                if os.path.exists(file):
                    mtime = os.path.getmtime(file)
                    latest_time = max(latest_time, mtime)

            if latest_time > 0:
                date_str = time.strftime("%Y%m%d", time.localtime(latest_time))
                return f"local-{date_str}"
        except:
            pass

        return "local-version"
    except Exception as e:
        print(f"Error getting current version: {e}")
        return "version-unknown"


def get_remote_version(channel="stable"):
    """Get latest remote version - checks releases first, then commits.
    Returns a tuple (version_string, is_prerelease)."""
    GITHUB_REPO = "plasmonized/containerized-mioty-Service-Center"

    try:
        import ssl
        import urllib.request

        ctx = ssl.create_default_context()

        if channel == "beta":
            try:
                best_version = None
                best_tag = None
                best_prerelease = False

                releases_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=30"
                req = urllib.request.Request(releases_url, headers={"User-Agent": "BSSCI-Service-Center"})
                with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                    releases = json.loads(response.read().decode())
                    for rel in releases:
                        tag = rel.get("tag_name", "")
                        if tag:
                            ver = parse_version(tag)
                            if best_version is None or ver > best_version:
                                best_version = ver
                                best_tag = tag
                                best_prerelease = rel.get("prerelease", False)

                tags_url = f"https://api.github.com/repos/{GITHUB_REPO}/tags?per_page=30"
                req = urllib.request.Request(tags_url, headers={"User-Agent": "BSSCI-Service-Center"})
                with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                    tags = json.loads(response.read().decode())
                    for tag_obj in tags:
                        tag = tag_obj.get("name", "")
                        if tag:
                            ver = parse_version(tag)
                            if best_version is None or ver > best_version:
                                best_version = ver
                                best_tag = tag
                                best_prerelease = "beta" in tag.lower() or "rc" in tag.lower() or "alpha" in tag.lower()

                if best_tag:
                    version = best_tag if best_tag.startswith("v") else f"v{best_tag}"
                    return (version, best_prerelease)
            except:
                pass
        else:
            try:
                releases_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                req = urllib.request.Request(releases_url, headers={"User-Agent": "BSSCI-Service-Center"})
                with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                    data = json.loads(response.read().decode())
                    tag_name = data.get("tag_name", "")
                    if tag_name:
                        version = tag_name if tag_name.startswith("v") else f"v{tag_name}"
                        return (version, False)
            except:
                pass

        # Fallback: Try to get latest tag
        try:
            tags_url = f"https://api.github.com/repos/{GITHUB_REPO}/tags"
            req = urllib.request.Request(tags_url, headers={"User-Agent": "BSSCI-Service-Center"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                tags = json.loads(response.read().decode())
                if tags and len(tags) > 0:
                    tag_name = tags[0].get("name", "")
                    if tag_name:
                        version = tag_name if tag_name.startswith("v") else f"v{tag_name}"
                        return (version, False)
        except:
            pass

        # Fallback: Get latest commit
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/{get_default_branch()}"
        req = urllib.request.Request(api_url, headers={"User-Agent": "BSSCI-Service-Center"})

        try:
            with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                data = json.loads(response.read().decode())
                commit_hash = data.get("sha", "")[:7]
                commit_date = data.get("commit", {}).get("committer", {}).get("date", "")[:10]
                return (f"commit-{commit_hash} ({commit_date})", False)
        except Exception as api_error:
            logger.error(f"GitHub API error: {api_error}")

        # Fallback to Git commands if API fails
        try:
            lock_file = ".git/index.lock"
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                except:
                    pass

            default_branch = get_default_branch()
            subprocess.run(
                ["git", "fetch", "--tags", "origin", default_branch], capture_output=True, text=True, timeout=30
            )

            result = subprocess.run(
                ["git", "rev-parse", "--short", f"origin/{default_branch}"], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return (f"commit-{result.stdout.strip()}", False)
        except:
            pass

        return ("remote-unavailable", False)
    except Exception as e:
        print(f"Error getting remote version: {e}")
        return ("remote-check-unavailable", False)


def get_commit_log(limit=5):
    """Get recent commit log - works with or without Git"""
    try:
        # First try Git commands
        try:
            # Try to unlock git if needed
            lock_file = ".git/index.lock"
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                except:
                    pass

            result = subprocess.run(
                ["git", "log", "--oneline", f"-{limit}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                commits = []
                for line in result.stdout.strip().split("\n"):
                    if line:
                        parts = line.split(" ", 1)
                        commits.append(
                            {
                                "hash": parts[0],
                                "message": parts[1] if len(parts) > 1 else "",
                            }
                        )
                return commits
        except FileNotFoundError:
            # Git not installed
            pass
        except Exception as e:
            if "No such file or directory" in str(e):
                # Git not installed
                pass
            else:
                print(f"Git command error: {e}")

        # Fallback: Return info about the current installation
        return [
            {"hash": "local", "message": "Local installation - Git not available"},
            {"hash": "info", "message": "Install Git to see commit history"},
            {"hash": "note", "message": "Version checking works without Git"},
        ]
    except Exception as e:
        print(f"Error getting commit log: {e}")
        return [{"hash": "error", "message": f"Unable to get history: {e!s}"}]


def parse_version(version_str):
    """Parse version string to comparable tuple.
    Stable releases sort higher than pre-releases of the same base version.
    e.g. v1.672 > v1.672-beta1 > v1.671 > v1.671-beta2 > v1.671-beta1
    Handles suffixes like v1.658a (treated as v1.658 patch) and v1.672-beta1.
    Returns tuple like (1, 672, 1000, 0) for stable or (1, 672, 0, 1) for beta1"""
    try:
        import re

        v = version_str.lstrip("v")
        parts = v.split("-", 1)
        base = parts[0]
        base_segments = base.replace(".", " ").split()
        base_nums = []
        for seg in base_segments:
            m = re.match(r"^(\d+)", seg)
            if m:
                base_nums.append(int(m.group(1)))
        base_parts = tuple(base_nums) if base_nums else (0,)
        has_letter_suffix = bool(re.search(r"[a-zA-Z]", base))
        if len(parts) > 1:
            suffix = parts[1].lower()
            m = re.search(r"(\d+)", suffix)
            suffix_num = int(m.group(1)) if m else 1
            return base_parts + (0, suffix_num)
        elif has_letter_suffix:
            letter = re.search(r"[a-zA-Z]+", base)
            letter_val = ord(letter.group(0)[0].lower()) - ord("a") + 1 if letter else 1
            return base_parts + (500, letter_val)
        else:
            return base_parts + (1000, 0)
    except:
        return (0,)


_update_cache = {"result": None, "timestamp": 0, "ttl": 300}


def check_for_updates(force=False):
    """Check if updates are available using GitHub API (cached for 5 minutes)"""
    import time as _time

    now = _time.time()
    if not force and _update_cache["result"] and (now - _update_cache["timestamp"]) < _update_cache["ttl"]:
        return _update_cache["result"]

    GITHUB_REPO = "plasmonized/containerized-mioty-Service-Center"

    try:
        try:
            channel = getattr(bssci_config, "UPDATE_CHANNEL", "stable")
        except:
            channel = "stable"

        current = get_current_version()
        remote, is_prerelease = get_remote_version(channel)

        updates_available = False
        status_message = None

        if remote in ["remote-unavailable", "remote-check-unavailable"]:
            updates_available = False
            status_message = "Cannot connect to GitHub to check for updates"
        elif current.startswith("v") and remote.startswith("v"):
            current_ver = parse_version(current)
            remote_ver = parse_version(remote)
            if remote_ver > current_ver:
                updates_available = True
                status_message = f"Update available: {current} → {remote}"
        elif "commit-" in current and "commit-" in remote:
            current_hash = current.split("commit-")[1].split()[0][:7]
            remote_hash = remote.split("commit-")[1].split()[0][:7]
            if current_hash != remote_hash:
                updates_available = True
        elif current.startswith("local-") or current.startswith("v"):
            updates_available = True
            status_message = "Update available"

        recent_commits = []
        try:
            import ssl
            import urllib.request

            ctx = ssl.create_default_context()

            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/commits?per_page=5"
            req = urllib.request.Request(api_url, headers={"User-Agent": "BSSCI-Service-Center"})

            with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                commits_data = json.loads(response.read().decode())
                for commit in commits_data:
                    recent_commits.append(
                        {
                            "hash": commit["sha"][:7],
                            "message": commit["commit"]["message"].split("\n")[0][:60],
                        }
                    )

                if commits_data and remote in [
                    "remote-unavailable",
                    "remote-check-unavailable",
                ]:
                    first_commit = commits_data[0]
                    remote_hash = first_commit["sha"][:7]
                    commit_date = first_commit["commit"]["committer"]["date"][:10]
                    remote = f"commit-{remote_hash} ({commit_date})"
                    updates_available = True
                    status_message = "Update available"
        except Exception as e:
            logger.error(f"Error fetching commits: {e}")

        result = {
            "current_version": current,
            "remote_version": remote,
            "updates_available": updates_available,
            "recent_commits": recent_commits,
            "channel": channel,
            "is_prerelease": is_prerelease,
            "status": "success",
        }

        if status_message:
            result["message"] = status_message

        import time as _time

        _update_cache["result"] = result
        _update_cache["timestamp"] = _time.time()

        return result
    except Exception as e:
        logger.error(f"Error checking for updates: {e}")
        return {"status": "error", "error": str(e)}


def create_backup():
    """Create backup before update"""
    try:
        # Use /tmp for Docker compatibility, fallback to current dir
        backup_base = "/tmp" if os.path.exists("/tmp") and os.access("/tmp", os.W_OK) else "."
        backup_dir = os.path.join(backup_base, f"bssci_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

        # Create backup directory
        os.makedirs(backup_dir, exist_ok=True)

        # Backup important files
        files_to_backup = [".env", "endpoints.json", "VERSION"]
        dirs_to_backup = ["certs"]

        for file in files_to_backup:
            if os.path.exists(file):
                shutil.copy2(file, backup_dir)

        for dir_name in dirs_to_backup:
            if os.path.exists(dir_name):
                try:
                    shutil.copytree(dir_name, os.path.join(backup_dir, dir_name))
                except Exception as e:
                    logger.warning(f"Could not backup {dir_name}: {e}")

        return {"success": True, "backup_dir": backup_dir}
    except Exception as e:
        return {"success": False, "error": str(e)}


_default_branch_cache = {"branch": None, "time": 0.0}


def get_default_branch():
    """Detect the repository's default branch on GitHub (cached 5 min).

    The repo's default branch is 'release', not 'main' - hardcoding 'main'
    caused updates to check out a stale local branch and break the install.
    """
    GITHUB_REPO = "plasmonized/containerized-mioty-Service-Center"
    now = time.time()
    if _default_branch_cache["branch"] and now - _default_branch_cache["time"] < 300:
        return _default_branch_cache["branch"]

    branch = None
    try:
        import ssl as _ssl
        import urllib.request

        ctx = _ssl.create_default_context()
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}", headers={"User-Agent": "BSSCI-Service-Center"}
        )
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            data = json.loads(response.read().decode())
            branch = data.get("default_branch")
    except Exception as e:
        logger.warning(f"Could not detect default branch via GitHub API: {e}")

    if not branch:
        try:
            result = subprocess.run(
                ["git", "ls-remote", "--symref", "origin", "HEAD"], capture_output=True, text=True, timeout=15
            )
            for line in result.stdout.splitlines():
                if line.startswith("ref:"):
                    branch = line.split()[1].replace("refs/heads/", "")
                    break
        except Exception:
            pass

    branch = branch or "release"
    _default_branch_cache["branch"] = branch
    _default_branch_cache["time"] = now
    logger.info(f"Default branch detected: {branch}")
    return branch


def perform_update():
    """Perform update by downloading from GitHub"""
    GITHUB_REPO = "plasmonized/containerized-mioty-Service-Center"

    try:
        try:
            channel = getattr(bssci_config, "UPDATE_CHANNEL", "stable")
        except:
            channel = "stable"

        backup_result = create_backup()
        if not backup_result["success"]:
            return {
                "success": False,
                "error": f"Backup failed: {backup_result['error']}",
            }

        if os.path.exists(".git"):
            try:
                subprocess.run(
                    ["git", "fetch", "--tags", "--force", "origin"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if channel == "beta":
                    remote, _ = get_remote_version("beta")
                    if remote.startswith("v") and "unavailable" not in remote:
                        subprocess.run(
                            ["git", "reset", "--hard", "HEAD"],
                            capture_output=True,
                            timeout=30,
                        )
                        subprocess.run(["git", "clean", "-fd"], capture_output=True, timeout=30)
                        result = subprocess.run(
                            ["git", "checkout", "--force", remote],
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )
                        if result.returncode == 0:
                            return {
                                "success": True,
                                "message": f"Update completed successfully via git (beta: {remote})",
                                "backup_dir": backup_result["backup_dir"],
                                "git_output": result.stdout,
                            }
                        else:
                            logger.error(f"Git checkout {remote} failed: {result.stderr}, trying ZIP fallback")
                            raise Exception(f"Git checkout {remote} failed, using ZIP fallback")
                    else:
                        logger.warning(f"Beta remote version not usable: {remote}")
                else:
                    default_branch = get_default_branch()
                    subprocess.run(["git", "reset", "--hard", "HEAD"], capture_output=True, timeout=30)
                    checkout_result = subprocess.run(
                        ["git", "checkout", default_branch], capture_output=True, text=True, timeout=30
                    )
                    if checkout_result.returncode != 0:
                        logger.error(f"Git checkout {default_branch} failed: {checkout_result.stderr}")
                        raise Exception(f"Git checkout {default_branch} failed, using ZIP fallback")
                    result = subprocess.run(
                        ["git", "pull", "origin", default_branch], capture_output=True, text=True, timeout=60
                    )
                    if result.returncode == 0:
                        return {
                            "success": True,
                            "message": f"Update completed successfully via git ({channel} channel, branch {default_branch})",
                            "backup_dir": backup_result["backup_dir"],
                            "git_output": result.stdout,
                        }
                    else:
                        logger.error(f"Git pull origin {default_branch} failed: {result.stderr}")
                        raise Exception(f"Git pull {default_branch} failed, using ZIP fallback")
            except Exception as e:
                logger.error(f"Git update failed, trying ZIP download: {e}")

        import ssl
        import urllib.request

        ctx = ssl.create_default_context()

        if channel == "beta":
            try:
                remote, _ = get_remote_version("beta")
                if remote.startswith("v") and "unavailable" not in remote:
                    zip_url = f"https://github.com/{GITHUB_REPO}/archive/refs/tags/{remote}.zip"
                    return _download_and_extract_zip(zip_url, ctx, backup_result, f"beta tag {remote}")
            except Exception as e:
                logger.error(f"Beta channel ZIP download failed: {e}")

        branch_candidates = [get_default_branch(), "main", "master"]
        seen = set()
        branch_candidates = [b for b in branch_candidates if not (b in seen or seen.add(b))]
        for branch in branch_candidates:
            zip_url = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/{branch}.zip"
            try:
                return _download_and_extract_zip(zip_url, ctx, backup_result, f"{branch} branch")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    logger.warning(f"Branch {branch} not found, trying next...")
                    continue
                raise

        return {
            "success": False,
            "error": "Could not download from GitHub (no valid branch found)",
        }

    except PermissionError as e:
        logger.error(f"Update failed - permission denied: {e}")
        return {
            "success": False,
            "error": 'Permission denied - files are read-only. For Docker: rebuild container with "docker-compose up -d --build"',
        }
    except Exception as e:
        logger.error(f"Update failed: {e}")
        if "Permission denied" in str(e):
            return {
                "success": False,
                "error": 'Permission denied - files are read-only. For Docker: rebuild container with "docker-compose up -d --build"',
            }
        return {"success": False, "error": str(e)}


def _download_and_extract_zip(zip_url, ctx, backup_result, source_label):
    """Helper to download and extract a ZIP update from a URL"""
    import tempfile
    import urllib.request

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
        tmp_path = tmp_file.name
        req = urllib.request.Request(zip_url, headers={"User-Agent": "BSSCI-Service-Center"})

        with urllib.request.urlopen(req, timeout=60, context=ctx) as response:
            tmp_file.write(response.read())

    extract_dir = tempfile.mkdtemp()
    with zipfile.ZipFile(tmp_path, "r") as zip_ref:
        zip_ref.extractall(extract_dir)

    extracted_folders = os.listdir(extract_dir)
    updated_files = []
    if extracted_folders:
        source_dir = os.path.join(extract_dir, extracted_folders[0])

        # Copy ALL Python modules from the release, plus metadata files.
        # A fixed whitelist previously caused crash loops: newly added modules
        # (e.g. observability.py) were imported by updated files but never
        # copied. Exclusions protect locally modified/user data files.
        excluded_files = {"bssci_config.py"}  # holds local settings (e.g. UPDATE_CHANNEL)
        files_to_update = sorted(
            f for f in os.listdir(source_dir) if f.endswith(".py") and f not in excluded_files
        )
        files_to_update += ["requirements.txt", "VERSION"]
        dirs_to_update = ["templates", "static"]

        for filename in files_to_update:
            src = os.path.join(source_dir, filename)
            if os.path.exists(src):
                shutil.copy2(src, filename)
                updated_files.append(filename)

        for dirname in dirs_to_update:
            src_dir = os.path.join(source_dir, dirname)
            if os.path.exists(src_dir):
                for root, subdirs, files in os.walk(src_dir):
                    rel_root = os.path.relpath(root, source_dir)
                    dest_root = os.path.join(".", rel_root)
                    os.makedirs(dest_root, exist_ok=True)
                    for item in files:
                        src_file = os.path.join(root, item)
                        dst_file = os.path.join(dest_root, item)
                        shutil.copy2(src_file, dst_file)
                        updated_files.append(os.path.join(rel_root, item))

    os.unlink(tmp_path)
    shutil.rmtree(extract_dir, ignore_errors=True)

    return {
        "success": True,
        "message": f"Update completed via GitHub ({source_label})",
        "backup_dir": backup_result["backup_dir"],
        "updated_files": updated_files,
    }


@app.route("/api/system/version")
def api_get_version():
    """Get current and remote version info"""
    try:
        version_info = check_for_updates()
        # Use remote commits from check_for_updates() - don't override with local git
        return jsonify(version_info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/system/check-updates")
def api_check_updates():
    """Check for available updates (forces fresh GitHub check)"""
    try:
        return jsonify(check_for_updates(force=True))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/system/update", methods=["POST"])
@login_required
@role_required("admin")
def api_perform_update():
    """Perform system update"""
    try:
        result = perform_update()
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/system/restart", methods=["POST"])
@login_required
@role_required("admin")
def api_restart_system():
    """Restart the service after update"""
    try:
        # Schedule restart in a separate thread to allow response to be sent
        def restart_service():
            time.sleep(2)  # Give time for response to be sent
            os._exit(0)  # Force exit - service manager should restart

        restart_thread = threading.Thread(target=restart_service)
        restart_thread.daemon = True
        restart_thread.start()

        return jsonify({"success": True, "message": "Service restart initiated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# Global variable to store TLS server instance
# tls_server_instance = None # Already defined at the top


def set_tls_server(server):
    """Set the TLS server instance"""
    global tls_server_instance
    tls_server_instance = server


def get_bssci_service_status():
    """Get the status of the BSSCI service - thread-safe version"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance

        if not tls_server:
            return {
                "running": False,
                "service_type": "web_ui",
                "tls_server": {"active": False},
                "mqtt_broker": {"active": False},
                "base_stations": {
                    "total_connected": 0,
                    "total_connecting": 0,
                    "connected": [],
                    "connecting": [],
                },
                "total_sensors": 0,
                "registered_sensors": 0,
                "pending_requests": 0,
                "error": "TLS server not available",
            }

        runtime_snapshot = tls_server.get_runtime_snapshot() if hasattr(tls_server, "get_runtime_snapshot") else {}
        connected_euis = runtime_snapshot.get("connected_euis", [])
        connecting_euis = runtime_snapshot.get("connecting_euis", [])

        connected_stations = [{"eui": eui, "address": "connected", "status": "connected"} for eui in connected_euis]
        connecting_stations = [{"eui": eui, "address": "connecting", "status": "connecting"} for eui in connecting_euis]

        total_configured_bs = len(set(connected_euis + connecting_euis))
        try:
            bs_config = load_base_station_config().get("base_stations", {})
            all_bs = set(k.upper() for k in bs_config.keys())
            all_bs.update(connected_euis)
            all_bs.update(connecting_euis)
            total_configured_bs = len(all_bs)
        except Exception:
            pass

        bs_status = {
            "connected": connected_stations,
            "connecting": connecting_stations,
            "total_connected": runtime_snapshot.get("total_connected", 0),
            "total_connecting": runtime_snapshot.get("total_connecting", 0),
            "total_configured": total_configured_bs,
        }

        total_sensors = runtime_snapshot.get("total_sensors", 0)
        registered_sensors = runtime_snapshot.get("registered_sensors", 0)

        # Build response safely
        response = {
            "running": True,
            "service_type": "web_ui",
            "base_stations": bs_status,
            "tls_server": {
                "active": True,
                "listening_port": getattr(bssci_config, "LISTEN_PORT", 16018),
                "connected_base_stations": bs_status.get("total_connected", 0),
                "total_sensors": total_sensors,
                "registered_sensors": registered_sensors,
            },
            "mqtt_broker": {
                "active": True,
                "broker_host": getattr(bssci_config, "MQTT_BROKER", "localhost"),
                "broker_port": getattr(bssci_config, "MQTT_PORT", 1883),
            },
            "total_sensors": total_sensors,
            "registered_sensors": registered_sensors,
            "pending_requests": 0,
            "sensor_status": runtime_snapshot.get("sensor_status", {"online": 0, "offline": 0, "total_tracked": 0}),
        }

        return response

    except Exception as e:
        logger.error(
            f"Error in get_bssci_service_status: {e}",
            extra={"error_code": ERROR_CODES["WEB_UI_STATUS_ERROR"]},
        )
        import traceback

        traceback.print_exc()
        return {
            "running": False,
            "service_type": "web_ui",
            "tls_server": {"active": False},
            "mqtt_broker": {"active": False},
            "base_stations": {
                "total_connected": 0,
                "total_connecting": 0,
                "connected": [],
                "connecting": [],
            },
            "total_sensors": 0,
            "registered_sensors": 0,
            "pending_requests": 0,
            "error": "Failed to retrieve service status",
            "error_code": ERROR_CODES["WEB_UI_STATUS_ERROR"],
        }


@app.route("/api/logs/clear", methods=["POST"])
@login_required
@role_required("admin")
def clear_logs():
    global log_entries
    log_entries = []
    return jsonify({"success": True, "message": "Logs cleared successfully"})


@app.route("/api/bssci/status")
@app.route("/api/service/status")  # Support both endpoints for compatibility
@login_required
def bssci_status():
    try:
        status = get_bssci_service_status()
        return jsonify(status)
    except Exception as e:
        app.logger.error(
            f"Error in bssci_status endpoint: {e}",
            extra={"error_code": ERROR_CODES["WEB_UI_STATUS_ERROR"]},
        )
        error_response = {
            "running": False,
            "error": f"Service status error: {e!s}",
            "service_type": "web_ui",
            "tls_server": {"active": False},
            "mqtt_broker": {"active": False},
            "base_stations": {
                "total_connected": 0,
                "total_connecting": 0,
                "connected": [],
                "connecting": [],
            },
            "total_sensors": 0,
            "registered_sensors": 0,
            "pending_requests": 0,
        }
        return jsonify(error_response), 500


@app.route("/api/connection-timeline")
@login_required
def api_connection_timeline():
    try:
        global tls_server_instance
        requested_limit = request.args.get("limit", 200, type=int)
        if requested_limit is None:
            requested_limit = 200
        limit = max(1, min(requested_limit, 2000))
        if tls_server_instance and hasattr(tls_server_instance, "get_connection_timeline"):
            return jsonify(
                {
                    "success": True,
                    "requested_limit": requested_limit,
                    "applied_limit": limit,
                    "entries": tls_server_instance.get_connection_timeline(limit=limit),
                }
            )
        return jsonify(
            {
                "success": True,
                "requested_limit": requested_limit,
                "applied_limit": limit,
                "entries": [],
            }
        )
    except Exception as e:
        logger.error(
            f"Failed to read connection timeline: {e}",
            extra={"error_code": ERROR_CODES["WEB_UI_TIMELINE_ERROR"]},
        )
        return (
            jsonify({"success": False, "error": "Failed to read connection timeline"}),
            500,
        )


@app.route("/api/base_stations")
def api_base_stations():
    """Get all base stations for coverage map"""
    try:
        global tls_server_instance
        base_stations = []
        bs_config = load_base_station_config().get("base_stations", {})

        # Get connected base stations
        connected_euis = set()
        if tls_server_instance and hasattr(tls_server_instance, "connected_base_stations"):
            for writer, bs_eui in tls_server_instance.connected_base_stations.items():
                connected_euis.add(bs_eui.upper())

        # Add configured base stations
        for eui, config in bs_config.items():
            base_stations.append(
                {
                    "eui": eui.upper(),
                    "EUI": eui.upper(),
                    "name": config.get("name", eui[:8]),
                    "connected": eui.upper() in connected_euis,
                }
            )

        # Add connected but not configured
        for eui in connected_euis:
            if eui.lower() not in bs_config:
                base_stations.append({"eui": eui, "EUI": eui, "name": eui[:8], "connected": True})

        return jsonify({"base_stations": base_stations})
    except Exception as e:
        return jsonify({"base_stations": [], "error": str(e)})


@app.route("/api/base_stations/status")
def get_base_stations_status():
    """Get status of connected base stations - thread-safe version (legacy endpoint)"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance

        if not tls_server:
            return (
                jsonify(
                    {
                        "connected": [],
                        "connecting": [],
                        "total_connected": 0,
                        "total_connecting": 0,
                        "error": "TLS server not initialized",
                    }
                ),
                503,
            )

        connected_stations = []
        connecting_stations = []

        try:
            if hasattr(tls_server, "connected_base_stations"):
                connected_dict = getattr(tls_server, "connected_base_stations", {})
                for writer, bs_eui in list(connected_dict.items()):
                    try:
                        connected_stations.append(
                            {
                                "eui": bs_eui,
                                "address": "connected",
                                "status": "connected",
                            }
                        )
                    except Exception as e:
                        print(f"Error processing connected station {bs_eui}: {e}")

            if hasattr(tls_server, "connecting_base_stations"):
                connecting_dict = getattr(tls_server, "connecting_base_stations", {})
                for writer, bs_eui in list(connecting_dict.items()):
                    try:
                        connecting_stations.append(
                            {
                                "eui": bs_eui,
                                "address": "connecting",
                                "status": "connecting",
                            }
                        )
                    except Exception as e:
                        print(f"Error processing connecting station {bs_eui}: {e}")

        except Exception as e:
            print(f"Error accessing base station collections: {e}")

        return jsonify(
            {
                "connected": connected_stations,
                "connecting": connecting_stations,
                "total_connected": len(connected_stations),
                "total_connecting": len(connecting_stations),
            }
        )

    except Exception as e:
        print(f"Error in get_base_stations_status endpoint: {e}")
        import traceback

        traceback.print_exc()
        return jsonify(
            {
                "connected": [],
                "connecting": [],
                "total_connected": 0,
                "total_connecting": 0,
                "error": f"Base stations error: {e!s}",
            }
        )


# ==================== Variable MAC (VM) Sub-Channel API ====================


@app.route("/api/vm/status")
@login_required
def get_vm_status():
    """Get VM sub-channel status for all sensors"""
    try:
        global tls_server_instance
        if tls_server_instance and hasattr(tls_server_instance, "get_vm_status"):
            status = tls_server_instance.get_vm_status()
            return jsonify({"success": True, **status})
        return jsonify(
            {
                "success": False,
                "message": "TLS server not available",
                "active_sensors": {},
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/vm/activate", methods=["POST"])
@login_required
@permission_required("can_edit_sensors")
def vm_activate():
    """Activate VM sub-channel reception on VM-capable base stations only

    Per BSSCI VM specification, this sends vm.activate with macType parameter.
    Only sends to base stations that have been confirmed as VM-capable.
    """
    try:
        global tls_server_instance
        if not tls_server_instance:
            return (
                jsonify({"success": False, "message": "TLS server not available"}),
                503,
            )

        data = request.get_json(silent=True) or {}
        mac_type = data.get("macType", 0)

        import asyncio

        loop = asyncio.new_event_loop()
        try:
            success = loop.run_until_complete(tls_server_instance.vm_activate(mac_type, only_vm_capable=True))
        finally:
            loop.close()

        if success:
            return jsonify(
                {
                    "success": True,
                    "message": f"VM activate sent to VM-capable base stations (macType={mac_type})",
                }
            )
        else:
            return jsonify({"success": False, "message": "No VM-capable base stations found"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/vm/deactivate", methods=["POST"])
@login_required
@permission_required("can_edit_sensors")
def vm_deactivate():
    """Deactivate VM sub-channel reception on VM-capable base stations only

    Per BSSCI VM specification, this sends vm.deactivate with macType parameter.
    Only sends to base stations that have been confirmed as VM-capable.
    """
    try:
        global tls_server_instance
        if not tls_server_instance:
            return (
                jsonify({"success": False, "message": "TLS server not available"}),
                503,
            )

        data = request.get_json(silent=True) or {}
        mac_type = data.get("macType", 0)

        import asyncio

        loop = asyncio.new_event_loop()
        try:
            success = loop.run_until_complete(tls_server_instance.vm_deactivate(mac_type, only_vm_capable=True))
        finally:
            loop.close()

        if success:
            return jsonify(
                {
                    "success": True,
                    "message": f"VM deactivate sent to VM-capable base stations (macType={mac_type})",
                }
            )
        else:
            return jsonify({"success": False, "message": "No VM-capable base stations found"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/vm/status", methods=["POST"])
@login_required
@permission_required("can_edit_sensors")
def vm_query_status():
    """Query VM sub-channel status - returns list of activated macTypes

    Per BSSCI VM specification, this sends vm.status to VM-capable base stations.
    Use discover=true to query ALL base stations (for initial VM capability detection).
    """
    try:
        global tls_server_instance
        if not tls_server_instance:
            return (
                jsonify({"success": False, "message": "TLS server not available"}),
                503,
            )

        data = request.get_json(silent=True) or {}
        discover = data.get("discover", False)  # If true, query ALL base stations

        import asyncio

        loop = asyncio.new_event_loop()
        try:
            success = loop.run_until_complete(tls_server_instance.vm_status(only_vm_capable=not discover))
        finally:
            loop.close()

        if success:
            if discover:
                return jsonify(
                    {
                        "success": True,
                        "message": "VM status query sent to ALL base stations (discovery mode)",
                    }
                )
            else:
                return jsonify(
                    {
                        "success": True,
                        "message": "VM status query sent to VM-capable base stations",
                    }
                )
        else:
            if discover:
                return jsonify({"success": False, "message": "No base stations connected"})
            else:
                return jsonify({"success": False, "message": "No VM-capable base stations found"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/vm/log")
@login_required
def get_vm_log():
    """Get VM operation log entries"""
    try:
        global tls_server_instance
        if tls_server_instance and hasattr(tls_server_instance, "vm_log"):
            return jsonify({"success": True, "log": tls_server_instance.vm_log[-50:]})
        return jsonify({"success": True, "log": []})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/vm/capable")
@login_required
def get_vm_capable_base_stations():
    """Get list of base stations that support VM (Variable MAC)"""
    try:
        global tls_server_instance
        if tls_server_instance and hasattr(tls_server_instance, "get_vm_capable_base_stations"):
            vm_capable = tls_server_instance.get_vm_capable_base_stations()
            connected = (
                list(tls_server_instance.connected_base_stations.values())
                if hasattr(tls_server_instance, "connected_base_stations")
                else []
            )
            return jsonify(
                {
                    "success": True,
                    "vm_capable": vm_capable,
                    "total_connected": len(connected),
                    "connected_base_stations": connected,
                }
            )
        return jsonify(
            {
                "success": True,
                "vm_capable": [],
                "total_connected": 0,
                "connected_base_stations": [],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/vm/send/<eui>", methods=["POST"])
@login_required
@permission_required("can_edit_sensors")
def vm_send_data_to_sensor(eui):
    """Send data to sensor via VM sub-channel (downlink)"""
    try:
        global tls_server_instance
        if not tls_server_instance:
            return (
                jsonify({"success": False, "message": "TLS server not available"}),
                503,
            )

        data = request.json
        if not data or "data" not in data:
            return jsonify({"success": False, "message": "Missing data field"}), 400

        payload = bytes.fromhex(data["data"]) if isinstance(data["data"], str) else bytes(data["data"])
        port = data.get("port", 1)

        import asyncio

        loop = asyncio.new_event_loop()
        try:
            success = loop.run_until_complete(tls_server_instance.vm_send_data(eui, payload, port))
        finally:
            loop.close()

        if success:
            return jsonify({"success": True, "message": f"VM downlink data sent to sensor {eui}"})
        else:
            return jsonify(
                {
                    "success": False,
                    "message": "Failed to send VM data - VM may not be active for this sensor",
                }
            )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/certificates/status")
@login_required
@permission_required("can_manage_certificates")
def get_certificate_status():
    """Get status of SSL certificates"""
    import os

    try:
        cert_files = {
            "ca": "certs/ca_cert.pem",
            "service": "certs/service_center_cert.pem",
            "key": "certs/service_center_key.pem",
        }

        status = {"certificates": {}}

        for cert_type, file_path in cert_files.items():
            if os.path.exists(file_path):
                status["certificates"][cert_type] = True
                # Try to get certificate expiry date
                try:
                    if cert_type != "key":  # Don't try to parse private key as certificate
                        from cryptography import x509
                        from cryptography.hazmat.backends import default_backend

                        with open(file_path, "rb") as f:
                            cert_data = f.read()
                            cert = x509.load_pem_x509_certificate(cert_data, default_backend())
                            expiry = cert.not_valid_after
                            status["certificates"][f"{cert_type}_expires"] = expiry.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    pass  # If we can't read the certificate, just mark as present
            else:
                status["certificates"][cert_type] = False

        return jsonify({"success": True, "certificates": status["certificates"]})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/certificates/download/<filename>")
@login_required
@permission_required("can_manage_certificates")
def download_certificate(filename):
    """Download a certificate file"""
    import os

    from flask import abort, send_file

    # Security: only allow specific certificate files
    allowed_files = ["ca_cert.pem", "service_center_cert.pem", "service_center_key.pem"]
    if filename not in allowed_files:
        abort(404)

    file_path = os.path.join("certs", filename)
    if not os.path.exists(file_path):
        abort(404)

    return send_file(file_path, as_attachment=True, download_name=filename)


@app.route("/api/certificates/upload/<cert_type>", methods=["POST"])
@login_required
@permission_required("can_manage_certificates")
def upload_certificate(cert_type):
    """Upload a new certificate"""
    import os

    if "certificate" not in request.files:
        return jsonify({"success": False, "message": "No file provided"})

    file = request.files["certificate"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No file selected"})

    # Map cert types to filenames
    cert_mapping = {
        "ca": "ca_cert.pem",
        "service": "service_center_cert.pem",
        "key": "service_center_key.pem",
    }

    if cert_type not in cert_mapping:
        return jsonify({"success": False, "message": "Invalid certificate type"})

    try:
        # Ensure certs directory exists
        os.makedirs("certs", exist_ok=True)

        # Backup existing file
        target_file = os.path.join("certs", cert_mapping[cert_type])
        if os.path.exists(target_file):
            backup_file = target_file + ".backup"
            os.rename(target_file, backup_file)

        # Save new file
        file.save(target_file)

        return jsonify(
            {
                "success": True,
                "message": f"{cert_type.upper()} certificate uploaded successfully",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/certificates/generate", methods=["POST"])
@login_required
@permission_required("can_manage_certificates")
def generate_certificates():
    """Generate new SSL certificates"""
    import os
    import subprocess

    try:
        # Ensure certs directory exists
        os.makedirs("certs", exist_ok=True)

        # Generate new certificates using OpenSSL with static, validated commands

        # Execute certificate generation commands with completely static strings

        # Generate CA private key
        result = subprocess.run(
            ["openssl", "genrsa", "-out", "certs/ca_key.pem", "2048"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return jsonify(
                {
                    "success": False,
                    "message": f"CA key generation failed: {result.stderr}",
                }
            )

        # Generate CA certificate
        result = subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-x509",
                "-key",
                "certs/ca_key.pem",
                "-out",
                "certs/ca_cert.pem",
                "-days",
                "365",
                "-subj",
                "/C=US/ST=State/L=City/O=BSSCI/CN=BSSCI-CA",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return jsonify(
                {
                    "success": False,
                    "message": f"CA certificate generation failed: {result.stderr}",
                }
            )

        # Generate service private key
        result = subprocess.run(
            ["openssl", "genrsa", "-out", "certs/service_center_key.pem", "2048"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return jsonify(
                {
                    "success": False,
                    "message": f"Service key generation failed: {result.stderr}",
                }
            )

        # Generate service certificate request
        result = subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-key",
                "certs/service_center_key.pem",
                "-out",
                "certs/service_center.csr",
                "-subj",
                "/C=US/ST=State/L=City/O=BSSCI/CN=bssci-service",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return jsonify(
                {
                    "success": False,
                    "message": f"Service certificate request generation failed: {result.stderr}",
                }
            )

        # Sign service certificate with CA
        result = subprocess.run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                "certs/service_center.csr",
                "-CA",
                "certs/ca_cert.pem",
                "-CAkey",
                "certs/ca_key.pem",
                "-CAcreateserial",
                "-out",
                "certs/service_center_cert.pem",
                "-days",
                "365",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return jsonify(
                {
                    "success": False,
                    "message": f"Service certificate signing failed: {result.stderr}",
                }
            )

        # Clean up temporary files
        temp_files = ["certs/service_center.csr", "certs/ca_cert.srl"]
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                os.remove(temp_file)

        return jsonify({"success": True, "message": "New certificates generated successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/certificates/backup")
@login_required
@permission_required("can_manage_certificates")
def backup_certificates():
    """Download all certificates as ZIP"""
    import os
    import tempfile
    import zipfile

    from flask import send_file

    try:
        # Create temporary ZIP file
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")

        with zipfile.ZipFile(temp_zip.name, "w") as zipf:
            cert_files = [
                "ca_cert.pem",
                "service_center_cert.pem",
                "service_center_key.pem",
            ]
            for cert_file in cert_files:
                file_path = os.path.join("certs", cert_file)
                if os.path.exists(file_path):
                    zipf.write(file_path, cert_file)

        return send_file(
            temp_zip.name,
            as_attachment=True,
            download_name="bssci_certificates_backup.zip",
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/certificates/restore", methods=["POST"])
@login_required
@permission_required("can_manage_certificates")
def restore_certificates():
    """Restore certificates from ZIP backup"""
    import os
    import tempfile
    import zipfile

    if "backup" not in request.files:
        return jsonify({"success": False, "message": "No backup file provided"})

    file = request.files["backup"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No file selected"})

    try:
        # Save uploaded ZIP to temporary location
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        file.save(temp_zip.name)

        # Extract certificates
        with zipfile.ZipFile(temp_zip.name, "r") as zipf:
            # Ensure certs directory exists
            os.makedirs("certs", exist_ok=True)

            # Extract only certificate files
            cert_files = [
                "ca_cert.pem",
                "service_center_cert.pem",
                "service_center_key.pem",
            ]
            for cert_file in cert_files:
                if cert_file in zipf.namelist():
                    target_path = os.path.join("certs", cert_file)
                    # Backup existing file
                    if os.path.exists(target_path):
                        os.rename(target_path, target_path + ".backup")
                    # Extract new file
                    zipf.extract(cert_file, "certs")

        # Clean up temporary file
        os.unlink(temp_zip.name)

        return jsonify(
            {
                "success": True,
                "message": "Certificates restored successfully from backup",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/base-stations/<eui>/certificate/generate", methods=["POST"])
@login_required
@permission_required("can_manage_certificates")
def generate_bs_certificate(eui):
    """Generate certificate pair for specific base station"""
    try:
        eui = eui.lower()
        if not _validate_eui(eui):
            return jsonify({"success": False, "message": "Invalid EUI format"}), 400
        config = load_base_station_config()
        if eui not in config.get("base_stations", {}):
            return jsonify({"success": False, "message": "Base station not found"}), 404
        success, msg = _generate_bs_certificate(eui)
        if success:
            return jsonify(
                {
                    "success": True,
                    "message": msg,
                    "download_url": f"/api/base-stations/{eui}/certificate/download",
                }
            )
        else:
            return jsonify({"success": False, "message": msg}), 500
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/base-stations/<eui>/certificate/download")
@login_required
@permission_required("can_manage_certificates")
def download_bs_certificate(eui):
    """Download ZIP with CA cert + BS cert + BS key"""
    try:
        eui = eui.lower()
        if not _validate_eui(eui):
            return jsonify({"success": False, "message": "Invalid EUI format"}), 400
        bs_cert_dir = os.path.join("certs", f"bs_{eui}")
        cert_path = os.path.join(bs_cert_dir, f"{eui}_cert.pem")
        key_path = os.path.join(bs_cert_dir, f"{eui}_key.pem")
        ca_path = "certs/ca_cert.pem"
        if not os.path.exists(cert_path) or not os.path.exists(key_path):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Certificate not found for this base station",
                    }
                ),
                404,
            )
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        with zipfile.ZipFile(temp_zip.name, "w") as zipf:
            if os.path.exists(ca_path):
                zipf.write(ca_path, "ca_cert.pem")
            zipf.write(cert_path, f"{eui}_cert.pem")
            zipf.write(key_path, f"{eui}_key.pem")
        return send_file(
            temp_zip.name,
            as_attachment=True,
            download_name=f"bs_{eui}_certificates.zip",
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/container/restart", methods=["POST"])
@login_required
@role_required("admin")
def restart_container():
    """Force restart the entire container"""
    import os
    import subprocess
    import threading
    import time

    def container_restart_in_background():
        """Perform container restart in a separate thread"""
        try:
            time.sleep(1)  # Small delay to allow response to be sent

            logger.info("Forcing container restart")
            try:
                # Send SIGTERM to PID 1 (init process) to restart the container
                subprocess.run(["kill", "-TERM", "1"], check=False, timeout=5)
            except Exception as e:
                logger.error(f"Container restart failed: {e}")
                # Fallback: exit the main process which should cause container restart
                os._exit(0)

        except Exception as e:
            logger.error(f"Error during container restart: {e}")
            os._exit(1)

    try:
        # Start restart in background thread
        restart_thread = threading.Thread(target=container_restart_in_background)
        restart_thread.daemon = True
        restart_thread.start()

        return jsonify(
            {
                "success": True,
                "message": "Container restart initiated. The container will restart completely to reload all environment variables.",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/service/restart", methods=["POST"])
@login_required
@role_required("admin")
def restart_service():
    """Restart the BSSCI service with full environment reload"""
    import os
    import threading
    import time

    def restart_in_background():
        """Perform the restart operation in a separate thread"""
        try:
            time.sleep(1)  # Small delay to allow response to be sent

            # Check if we're running in Docker
            is_docker = os.path.exists("/.dockerenv") or os.getenv("CONTAINER") == "1"

            # Check environment type
            is_replit = os.getenv("REPLIT_ENVIRONMENT") or os.getenv("REPL_SLUG")

            if is_replit:
                # In Replit, workflows auto-restart when the process exits
                logger.info("Replit environment detected - restarting via process exit")
                _restart_processes()
            elif is_docker:
                # In Docker (including Synology), use process exit with Docker restart policy
                # This avoids using kill/pkill commands that may not be available
                logger.info("Docker environment detected - restarting via process exit")
                logger.info("Docker restart policy will automatically restart the container")
                _restart_processes()
            else:
                # In regular environment without Docker
                logger.info("Regular environment detected - attempting process restart")
                _restart_processes()

        except Exception as e:
            logger.error(f"Error during restart: {e}")
            # Fallback to basic process restart
            _restart_processes()

    def _restart_processes():
        """Restart Python processes (Docker-compatible version without kill/pkill)"""
        try:
            logger.info("Initiating service restart for Docker environment...")

            # Give time for the response to be sent before restarting
            time.sleep(2)

            # In Docker with restart policy, we can simply exit and let Docker restart us
            # This works for Synology Docker and other containerized environments
            logger.info("Exiting process - Docker will restart automatically")

            # Use os._exit to bypass cleanup handlers and exit immediately
            import os

            os._exit(0)

        except Exception as e:
            logger.error(f"Error during process exit: {e}")
            # Fallback: try standard exit
            try:
                import sys

                sys.exit(0)
            except:
                # Last resort: force exit
                import os

                os._exit(1)

    try:
        # Start restart in background thread
        restart_thread = threading.Thread(target=restart_in_background)
        restart_thread.daemon = True
        restart_thread.start()

        return jsonify(
            {
                "success": True,
                "message": "Service restart initiated. In Docker environments, the entire container will restart to reload environment variables.",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
