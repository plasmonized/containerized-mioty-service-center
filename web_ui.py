import csv
import io
import json
import logging
import os
import subprocess
import shutil
import threading
import time
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, Response
from typing import List, Dict, Any
import bssci_config

# Global TLS server instance reference
tls_server_instance = None

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

# Configure logger for this module
logger = logging.getLogger(__name__)

@app.errorhandler(500)
def internal_error(error):
    """Handle internal server errors and return JSON"""
    app.logger.error(f"Internal server error: {error}")
    if request.path.startswith('/api/'):
        return jsonify({
            'error': 'Internal server error',
            'running': False,
            'service_type': 'web_ui',
            'tls_server': {'active': False},
            'mqtt_broker': {'active': False},
            'base_stations': {'total_connected': 0, 'total_connecting': 0, 'connected': [], 'connecting': []}
        }), 500
    return error

@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors for API endpoints"""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'API endpoint not found'}), 404
    return error

@app.before_request
def ensure_json_api():
    """Ensure API endpoints always return JSON, even on error"""
    if request.path.startswith('/api/'):
        # Set content type to JSON for all API requests
        if not request.is_json and request.method in ['POST', 'PUT', 'PATCH']:
            # For non-JSON requests to API, try to handle gracefully
            pass

# Global variables for log storage and configuration
log_entries: List[Dict[str, Any]] = []
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
        if record.name == 'werkzeug' and any(x in record.getMessage() for x in [
            'GET /api/', 'GET /logs', 'GET /sensors', 'GET /config', 'GET /', 'GET /static/'
        ]):
            return  # Skip web request logs

        # Convert UTC timestamp to local timezone
        utc_time = datetime.fromtimestamp(record.created, tz=timezone.utc)
        local_time = utc_time.astimezone(self.tz)
        current_time = local_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        message = record.getMessage()

        # Check if this exact message was logged in the last second (duplicate detection)
        if log_entries:
            last_entry = log_entries[-1]
            try:
                last_time = datetime.strptime(last_entry['timestamp'], '%Y-%m-%d %H:%M:%S.%f')
                time_diff = abs((local_time.replace(tzinfo=None) - last_time).total_seconds())

                if (time_diff < 1.0 and  # Within 1 second
                    last_entry['message'] == message and
                    last_entry['logger'] == record.name):
                    return  # Skip duplicate message
            except:
                pass  # If timestamp parsing fails, continue with logging

        log_entry = {
            'timestamp': current_time,
            'level': record.levelname,
            'logger': record.name,
            'message': message,
            'source': 'memory'
        }
        log_entries.append(log_entry)

        # Keep only the last max_log_entries
        if len(log_entries) > max_log_entries:
            log_entries = log_entries[-max_log_entries:]

# Add our custom handler to the root logger (only once)
if not any(isinstance(h, WebUILogHandler) for h in logging.getLogger().handlers):
    web_handler = WebUILogHandler()
    logging.getLogger().addHandler(web_handler)
    logging.getLogger().setLevel(logging.DEBUG)

    # Specifically capture important logs
    logging.getLogger('TLSServer').setLevel(logging.DEBUG)
    logging.getLogger('mqtt_interface').setLevel(logging.DEBUG)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sensors')
def sensors():
    try:
        with open(bssci_config.SENSOR_CONFIG_FILE, 'r') as f:
            sensors = json.load(f)
    except:
        sensors = []
    return render_template('sensors.html', sensors=sensors)

@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    try:
        global tls_server_instance
        tls_server = tls_server_instance
        
        # Load sensors from config file first
        sensor_status = {}
        try:
            sensor_file = getattr(bssci_config, 'SENSOR_CONFIG_FILE', 'endpoints.json')
            print(f"Loading sensors from file: {sensor_file}")
            with open(sensor_file, 'r') as f:
                sensors = json.load(f)
                print(f"Loaded {len(sensors)} sensors from file")
                
                # Initialize sensor status from config file
                for sensor in sensors:
                    eui = sensor['eui'].upper()
                    sensor_status[eui] = {
                        'eui': sensor['eui'].upper(),
                        'nwKey': sensor['nwKey'],
                        'shortAddr': sensor['shortAddr'],
                        'bidi': sensor['bidi'],
                        'registered': False,
                        'registration_info': {},
                        'base_stations': [],
                        'missing_registrations': [],
                        'total_registrations': 0,
                        'total_available_bases': 0,
                        'preferredDownlinkPath': sensor.get('preferredDownlinkPath', None),
                        'activity_status': 'no_data',
                        'hours_since_last_seen': 0
                    }
                    
                # Get connected base stations list for missing registration tracking
                connected_bases = []
                if tls_server and hasattr(tls_server, 'connected_base_stations'):
                    connected_bases = list(tls_server.connected_base_stations.values())
                    # Update total available bases for all sensors
                    for sensor_eui in sensor_status:
                        sensor_status[sensor_eui]['total_available_bases'] = len(connected_bases)
                
                # Now safely get real registration data from TLS server
                if tls_server and hasattr(tls_server, 'registered_sensors'):
                    try:
                        # Thread-safe access to registered sensors data
                        registered_dict = getattr(tls_server, 'registered_sensors', {})
                        print(f"Accessing registration data for {len(registered_dict)} registered sensors")
                        
                        for sensor_eui, reg_data in list(registered_dict.items()):
                            if sensor_eui in sensor_status:
                                try:
                                    # Get base stations list safely
                                    base_stations_list = reg_data.get('base_stations', [])
                                    registrations_list = reg_data.get('registrations', [])
                                    
                                    # Calculate missing registrations
                                    missing_bases = [bs for bs in connected_bases if bs not in base_stations_list]
                                    
                                    sensor_status[sensor_eui].update({
                                        'registered': reg_data.get('status') == 'registered',
                                        'base_stations': base_stations_list,
                                        'missing_registrations': missing_bases,
                                        'total_registrations': len(base_stations_list),
                                        'registration_info': {
                                            'status': reg_data.get('status', 'unknown'),
                                            'last_update': reg_data.get('registration_time', 'Unknown'),
                                            'registrations': registrations_list
                                        }
                                    })
                                    
                                    print(f"Sensor {sensor_eui}: {len(base_stations_list)} base stations - {base_stations_list}")
                                    
                                except Exception as e:
                                    print(f"Error processing registration data for sensor {sensor_eui}: {e}")
                                    
                    except Exception as e:
                        print(f"Error accessing TLS server registration data: {e}")
                
                # For sensors without registration data, mark all connected bases as missing
                for sensor_eui in sensor_status:
                    if not sensor_status[sensor_eui]['base_stations']:
                        sensor_status[sensor_eui]['missing_registrations'] = connected_bases.copy()
                        
                print(f"Processed sensor status for {len(sensor_status)} sensors with registration data")
                return jsonify(sensor_status)
        except FileNotFoundError:
            sensor_file = getattr(bssci_config, 'SENSOR_CONFIG_FILE', 'endpoints.json')
            print(f"Sensor config file not found: {sensor_file}")
            return jsonify({})
        except json.JSONDecodeError as e:
            sensor_file = getattr(bssci_config, 'SENSOR_CONFIG_FILE', 'endpoints.json')
            print(f"Invalid JSON in sensor config file {sensor_file}: {e}")
            return jsonify({})
            
    except Exception as e:
        print(f"Error in get_sensors: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/sensors', methods=['POST'])
def add_sensor():
    data = request.json
    
    try:
        # Ensure EUI is uppercase
        data['eui'] = data['eui'].upper()
        
        # Step 1: Save directly to endpoints.json
        try:
            with open(bssci_config.SENSOR_CONFIG_FILE, 'r') as f:
                sensors = json.load(f)
        except:
            sensors = []

        # Check if sensor already exists
        sensor_updated = False
        for sensor in sensors:
            if sensor['eui'].upper() == data['eui'].upper():
                # Update existing sensor
                sensor.update(data)
                sensor_updated = True
                break
        
        if not sensor_updated:
            # Add new sensor
            sensors.append(data)

        # Save to file
        with open(bssci_config.SENSOR_CONFIG_FILE, 'w') as f:
            json.dump(sensors, f, indent=4)
        
        # Step 2: Notify TLS server to reload config and send attach requests
        global tls_server_instance
        tls_server = tls_server_instance
        
        if tls_server and hasattr(tls_server, 'reload_sensor_config'):
            try:
                # Reload the sensor configuration in TLS server
                tls_server.reload_sensor_config()
                
                # Force attach to connected base stations if any
                if hasattr(tls_server, 'connected_base_stations') and tls_server.connected_base_stations:
                    print(f"Triggering attach for new sensor {data['eui']} to {len(tls_server.connected_base_stations)} base stations")
                    
                    # Use simple synchronous method to send attach requests
                    if hasattr(tls_server, 'attach_sensor_sync'):
                        attached_count = tls_server.attach_sensor_sync(data['eui'])
                        if attached_count > 0:
                            print(f"Successfully sent attach requests for {data['eui']} to {attached_count} base stations")
                            return jsonify({'success': True, 'message': f'Sensor saved and attach requests sent to {attached_count} base stations'})
                        else:
                            print(f"Failed to send attach requests for {data['eui']}")
                            return jsonify({'success': True, 'message': 'Sensor saved but failed to send attach requests'})
                    else:
                        return jsonify({'success': True, 'message': 'Sensor saved but attach function not available'})
                else:
                    return jsonify({'success': True, 'message': 'Sensor saved (no base stations connected for attach)'})
                            
                return jsonify({'success': True, 'message': 'Sensor saved and processed'})
            except Exception as e:
                print(f"Error notifying TLS server: {e}")
                return jsonify({'success': True, 'message': 'Sensor saved but failed to notify TLS server'})
        else:
            return jsonify({'success': True, 'message': 'Sensor saved (TLS server not available for attach)'})
                
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/api/sensors/<eui>', methods=['DELETE'])
def delete_sensor(eui):
    try:
        with open(bssci_config.SENSOR_CONFIG_FILE, 'r') as f:
            sensors = json.load(f)
    except:
        sensors = []

    sensors = [s for s in sensors if s['eui'].upper() != eui.upper()]

    try:
        with open(bssci_config.SENSOR_CONFIG_FILE, 'w') as f:
            json.dump(sensors, f, indent=4)
        return jsonify({'success': True, 'message': 'Sensor deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/sensors/<eui>/attach', methods=['POST'])
def attach_sensor(eui):
    """Attach a specific sensor to all base stations"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance
        
        if not tls_server:
            return jsonify({'success': False, 'message': 'TLS server not available'})
        
        if not hasattr(tls_server, 'connected_base_stations') or not tls_server.connected_base_stations:
            return jsonify({'success': False, 'message': 'No base stations connected'})
        
        if hasattr(tls_server, 'attach_sensor_sync'):
            attached_count = tls_server.attach_sensor_sync(eui)
            bs_count = len(tls_server.connected_base_stations)
            if attached_count > 0:
                return jsonify({
                    'success': True, 
                    'message': f'Sensor {eui} attached to {attached_count}/{bs_count} base stations'
                })
            else:
                return jsonify({
                    'success': False, 
                    'message': f'Failed to attach sensor {eui} to any base stations'
                })
        else:
            return jsonify({'success': False, 'message': 'Attach function not available'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/sensors/<eui>/detach', methods=['POST'])
def detach_sensor(eui):
    """Detach a specific sensor from all base stations"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance
        if tls_server and hasattr(tls_server, 'detach_sensor_sync'):
            success = tls_server.detach_sensor_sync(eui)
            return jsonify({'success': success, 'message': f'Sensor {eui} {"detached" if success else "detach failed"}'})
        else:
            return jsonify({'success': False, 'message': 'TLS server not available'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/sensors/attach-all', methods=['POST'])
def attach_all_sensors():
    """Attach all configured sensors to base stations"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance
        
        if not tls_server:
            return jsonify({'success': False, 'message': 'TLS server not available'})
        
        if not hasattr(tls_server, 'connected_base_stations') or not tls_server.connected_base_stations:
            return jsonify({'success': False, 'message': 'No base stations connected'})
        
        # Get all sensors from config file
        try:
            with open(bssci_config.SENSOR_CONFIG_FILE, 'r') as f:
                sensors = json.load(f)
        except:
            sensors = []
        
        if not sensors:
            return jsonify({'success': False, 'message': 'No sensors configured to attach'})
        
        # Force reload sensor config to ensure all sensors are loaded
        tls_server.reload_sensor_config()
        
        # Send attach requests for all sensors to all connected base stations
        if hasattr(tls_server, 'attach_all_sensors_sync'):
            attached_count = tls_server.attach_all_sensors_sync()
            bs_count = len(tls_server.connected_base_stations)
            message = f'Sent attach requests for {attached_count} sensors to {bs_count} base stations'
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': 'Attach all function not available in TLS server'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/sensors/detach-all', methods=['POST'])
def detach_all_sensors():
    """Detach all sensors from base stations"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance
        
        if not tls_server:
            return jsonify({'success': False, 'message': 'TLS server not available'})
        
        if hasattr(tls_server, 'detach_all_sensors_sync'):
            detached_count = tls_server.detach_all_sensors_sync()
            message = f'Successfully detached {detached_count} sensors from all base stations.'
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': 'Detach all function not available'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/sensors/clear', methods=['POST'])
def clear_all_sensors():
    """Clear all sensor configurations and detach all sensors"""
    try:
        detached_count = 0

        # First detach all sensors from base stations
        global tls_server_instance
        tls_server = tls_server_instance
        if tls_server and hasattr(tls_server, 'detach_all_sensors_sync'):
            detached_count = tls_server.detach_all_sensors_sync()

        # Clear the file
        with open(bssci_config.SENSOR_CONFIG_FILE, 'w') as f:
            json.dump([], f, indent=4)

        # Also clear from TLS server if available
        if tls_server and hasattr(tls_server, 'clear_all_sensors'):
            tls_server.clear_all_sensors()

        message = f'All sensors cleared successfully. Detached {detached_count} sensors from base stations.'
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/sensors/reload', methods=['POST'])
def reload_sensors():
    """Force reload sensor configuration in TLS server"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance
        if tls_server:
            tls_server.reload_sensor_config()
            return jsonify({'success': True, 'message': 'Sensor configuration reloaded successfully'})
        else:
            return jsonify({'success': False, 'message': 'TLS server not available'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/sensors/export', methods=['GET'])
def export_sensors():
    """Export all sensors as CSV file"""
    try:
        # Load sensors from config file
        try:
            with open(bssci_config.SENSOR_CONFIG_FILE, 'r') as f:
                sensors = json.load(f)
        except:
            sensors = []
        
        if not sensors:
            return jsonify({'success': False, 'message': 'No sensors to export'}), 404
        
        # Create CSV content
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['eui', 'nwKey', 'shortAddr', 'bidi'])
        
        # Write sensor data
        for sensor in sensors:
            writer.writerow([
                sensor.get('eui', ''),
                sensor.get('nwKey', ''),
                sensor.get('shortAddr', ''),
                'true' if sensor.get('bidi', False) else 'false'
            ])
        
        # Create response with CSV file
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=sensors_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'}
        )
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/sensors/import', methods=['POST'])
def import_sensors():
    """Import sensors from CSV/TXT file"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'}), 400
        
        # Read file content
        content = file.read().decode('utf-8')
        lines = content.strip().split('\n')
        
        if len(lines) < 1:
            return jsonify({'success': False, 'message': 'File is empty'}), 400
        
        # Detect delimiter (comma, semicolon, or tab)
        first_line = lines[0]
        if ';' in first_line:
            delimiter = ';'
        elif '\t' in first_line:
            delimiter = '\t'
        else:
            delimiter = ','
        
        # Parse CSV
        reader = csv.reader(io.StringIO(content), delimiter=delimiter)
        rows = list(reader)
        
        if len(rows) < 1:
            return jsonify({'success': False, 'message': 'No data in file'}), 400
        
        # Check if first row is header
        header = rows[0]
        has_header = any(h.lower() in ['eui', 'nwkey', 'shortaddr', 'bidi', 'network_key', 'short_addr'] for h in header)
        
        if has_header:
            # Map header columns
            header_lower = [h.lower().strip() for h in header]
            eui_idx = next((i for i, h in enumerate(header_lower) if h in ['eui', 'mac', 'address']), 0)
            nwkey_idx = next((i for i, h in enumerate(header_lower) if h in ['nwkey', 'network_key', 'key', 'networkkey']), 1)
            shortaddr_idx = next((i for i, h in enumerate(header_lower) if h in ['shortaddr', 'short_addr', 'shortaddress', 'addr']), 2)
            bidi_idx = next((i for i, h in enumerate(header_lower) if h in ['bidi', 'bidirectional', 'bidir']), 3)
            data_rows = rows[1:]
        else:
            # Assume order: eui, nwKey, shortAddr, bidi
            eui_idx, nwkey_idx, shortaddr_idx, bidi_idx = 0, 1, 2, 3
            data_rows = rows
        
        # Load existing sensors
        try:
            with open(bssci_config.SENSOR_CONFIG_FILE, 'r') as f:
                existing_sensors = json.load(f)
        except:
            existing_sensors = []
        
        existing_euis = {s['eui'].upper() for s in existing_sensors}
        
        imported_count = 0
        updated_count = 0
        errors = []
        
        for row_idx, row in enumerate(data_rows):
            try:
                if len(row) < 3:  # At least eui, nwKey, shortAddr required
                    errors.append(f"Row {row_idx + 1}: Not enough columns")
                    continue
                
                eui = row[eui_idx].strip().upper() if eui_idx < len(row) else ''
                nwkey = row[nwkey_idx].strip() if nwkey_idx < len(row) else ''
                shortaddr = row[shortaddr_idx].strip() if shortaddr_idx < len(row) else '0000'
                bidi_val = row[bidi_idx].strip().lower() if bidi_idx < len(row) else 'false'
                bidi = bidi_val in ['true', '1', 'yes', 'on']
                
                # Validate EUI
                if not eui or len(eui) < 8:
                    errors.append(f"Row {row_idx + 1}: Invalid EUI '{eui}'")
                    continue
                
                # Validate nwKey
                if not nwkey or len(nwkey) < 16:
                    errors.append(f"Row {row_idx + 1}: Invalid network key")
                    continue
                
                sensor_data = {
                    'eui': eui,
                    'nwKey': nwkey,
                    'shortAddr': shortaddr if shortaddr else '0000',
                    'bidi': bidi
                }
                
                if eui in existing_euis:
                    # Update existing sensor
                    for s in existing_sensors:
                        if s['eui'].upper() == eui:
                            s.update(sensor_data)
                            break
                    updated_count += 1
                else:
                    # Add new sensor
                    existing_sensors.append(sensor_data)
                    existing_euis.add(eui)
                    imported_count += 1
                    
            except Exception as e:
                errors.append(f"Row {row_idx + 1}: {str(e)}")
        
        # Save to file
        with open(bssci_config.SENSOR_CONFIG_FILE, 'w') as f:
            json.dump(existing_sensors, f, indent=4)
        
        # Reload TLS server config
        global tls_server_instance
        if tls_server_instance and hasattr(tls_server_instance, 'reload_sensor_config'):
            tls_server_instance.reload_sensor_config()
        
        message = f'Import complete: {imported_count} new sensors, {updated_count} updated'
        if errors:
            message += f', {len(errors)} errors'
        
        return jsonify({
            'success': True,
            'message': message,
            'imported': imported_count,
            'updated': updated_count,
            'errors': errors[:10] if errors else []  # Limit error messages
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/config')
def config():
    try:
        # Force reload the config module to get latest values
        import importlib
        import sys
        if 'bssci_config' in sys.modules:
            importlib.reload(sys.modules['bssci_config'])
        
        import bssci_config
        
        config_data = {
            'LISTEN_HOST': getattr(bssci_config, 'LISTEN_HOST', '0.0.0.0'),
            'LISTEN_PORT': getattr(bssci_config, 'LISTEN_PORT', 16018),
            'MQTT_BROKER': getattr(bssci_config, 'MQTT_BROKER', 'localhost'),
            'MQTT_PORT': getattr(bssci_config, 'MQTT_PORT', 1883),
            'MQTT_USERNAME': getattr(bssci_config, 'MQTT_USERNAME', ''),
            'MQTT_PASSWORD': getattr(bssci_config, 'MQTT_PASSWORD', ''),
            'BASE_TOPIC': getattr(bssci_config, 'BASE_TOPIC', 'bssci/'),
            'STATUS_INTERVAL': getattr(bssci_config, 'STATUS_INTERVAL', 30),
            'DEDUPLICATION_DELAY': getattr(bssci_config, 'DEDUPLICATION_DELAY', 2.0),
            'AUTO_DETACH_ENABLED': getattr(bssci_config, 'AUTO_DETACH_ENABLED', True),
            'AUTO_DETACH_TIMEOUT': getattr(bssci_config, 'AUTO_DETACH_TIMEOUT', 259200),
            'AUTO_DETACH_WARNING_TIMEOUT': getattr(bssci_config, 'AUTO_DETACH_WARNING_TIMEOUT', 129600),
            'AUTO_DETACH_CHECK_INTERVAL': getattr(bssci_config, 'AUTO_DETACH_CHECK_INTERVAL', 3600),
            'TIMEZONE': getattr(bssci_config, 'TIMEZONE', 'Europe/Berlin')
        }
        return render_template('config.html', config=config_data)
    except Exception as e:
        print(f"Error loading config page: {e}")
        # Return default config if there's an error
        default_config = {
            'LISTEN_HOST': '0.0.0.0',
            'LISTEN_PORT': 16018,
            'MQTT_BROKER': 'localhost',
            'MQTT_PORT': 1883,
            'MQTT_USERNAME': '',
            'MQTT_PASSWORD': '',
            'BASE_TOPIC': 'bssci/',
            'STATUS_INTERVAL': 30,
            'DEDUPLICATION_DELAY': 2.0,
            'AUTO_DETACH_ENABLED': True,
            'AUTO_DETACH_TIMEOUT': 259200,
            'AUTO_DETACH_WARNING_TIMEOUT': 129600,
            'AUTO_DETACH_CHECK_INTERVAL': 3600,
            'TIMEZONE': 'Europe/Berlin'
        }
        return render_template('config.html', config=default_config)

@app.route('/api/config', methods=['POST'])
def update_config():
    try:
        data = request.json
        
        # Type safety: Validate request data
        if data is None:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400
        
        # Values are already in seconds from HTML form (no conversion needed)
        auto_detach_timeout = int(data.get('AUTO_DETACH_TIMEOUT', 259200))
        auto_detach_warning_timeout = int(data.get('AUTO_DETACH_WARNING_TIMEOUT', 129600))
        auto_detach_check_interval = int(data.get('AUTO_DETACH_CHECK_INTERVAL', 3600))
        
        # Update the .env file - this is the primary configuration source (with type safety)
        env_content = f"""# TLS Server Configuration
LISTEN_HOST={data.get('LISTEN_HOST', '0.0.0.0')}
LISTEN_PORT={data.get('LISTEN_PORT', 16018)}

# SSL/TLS Certificate Configuration
CERT_FILE=certs/service_center_cert.pem
KEY_FILE=certs/service_center_key.pem
CA_FILE=certs/ca_cert.pem

# MQTT Configuration
MQTT_BROKER={data.get('MQTT_BROKER', 'localhost')}
MQTT_PORT={data.get('MQTT_PORT', 1883)}
MQTT_USERNAME={data.get('MQTT_USERNAME', '')}
MQTT_PASSWORD={data.get('MQTT_PASSWORD', '')}
BASE_TOPIC={data.get('BASE_TOPIC', 'bssci/')}

# Application Configuration
SENSOR_CONFIG_FILE=endpoints.json
STATUS_INTERVAL={data.get('STATUS_INTERVAL', 30)}
DEDUPLICATION_DELAY={data.get('DEDUPLICATION_DELAY', 2.0)}

# Web Interface Configuration
WEB_HOST=0.0.0.0
WEB_PORT=5000
WEB_DEBUG=false

# Auto-detach Configuration
AUTO_DETACH_ENABLED={str(data.get('AUTO_DETACH_ENABLED', True)).lower()}
AUTO_DETACH_TIMEOUT={auto_detach_timeout}
AUTO_DETACH_HOURS={auto_detach_timeout // 3600}
AUTO_DETACH_WARNING_TIMEOUT={auto_detach_warning_timeout}
AUTO_DETACH_WARNING_HOURS={auto_detach_warning_timeout // 3600}
AUTO_DETACH_CHECK_INTERVAL={auto_detach_check_interval}

# Timezone Configuration
TIMEZONE={data.get('TIMEZONE', 'Europe/Berlin')}

# Logging Configuration
LOG_LEVEL=INFO
LOG_FILE=logs/bssci_service.log

# Security
SECRET_KEY=your-secret-key-here"""
        
        # Write to .env file with error handling for Docker environments
        try:
            with open('.env', 'w') as f:
                f.write(env_content)
        except PermissionError as pe:
            # Try alternative approach for Docker/Synology environments
            try:
                import tempfile
                import shutil
                # Write to temp file first, then move
                with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
                    tmp.write(env_content)
                    tmp_name = tmp.name
                shutil.move(tmp_name, '.env')
            except Exception as fallback_error:
                raise Exception(f"Cannot write .env file. Docker volume not mounted as writable? Original error: {pe}, Fallback error: {fallback_error}")
        
        # Reload environment variables
        from dotenv import load_dotenv
        load_dotenv(override=True)
            
        # Force reload of the bssci_config module to pick up new .env values
        import importlib
        import sys
        if 'bssci_config' in sys.modules:
            importlib.reload(sys.modules['bssci_config'])
            
        return jsonify({'success': True, 'message': 'Configuration updated in .env file and reloaded successfully.'})
    except Exception as e:
        print(f"Error updating config: {e}")
        return jsonify({'success': False, 'message': f'Configuration update failed: {str(e)}'})

@app.route('/certificates')
def certificates():
    return render_template('certificates.html')

@app.route('/logs')
def logs():
    return render_template('logs.html')

@app.route('/traffic')
def traffic():
    return render_template('traffic.html')

@app.route('/base-stations')
def base_stations():
    return render_template('base_stations.html')

def load_base_station_config():
    """Load base station configuration from JSON file"""
    try:
        config_path = getattr(bssci_config, 'BASE_STATION_CONFIG_FILE', 'base_stations.json')
        with open(config_path, 'r') as f:
            return json.load(f)
    except:
        return {"base_stations": {}}

def save_base_station_config(config):
    """Save base station configuration to JSON file"""
    import os
    config_path = getattr(bssci_config, 'BASE_STATION_CONFIG_FILE', 'base_stations.json')
    try:
        dir_path = os.path.dirname(config_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
    except:
        pass
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

@app.route('/api/base-stations', methods=['GET'])
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
        
        if tls_server_instance:
            status = tls_server_instance.get_base_station_status()
            for bs in status.get("connected", []):
                eui = bs["eui"].lower()
                connected_bs[eui] = bs
            for bs in status.get("connecting", []):
                eui = bs["eui"].lower()
                connecting_bs[eui] = bs
            if hasattr(tls_server_instance, 'base_station_health'):
                bs_health = tls_server_instance.base_station_health
            if hasattr(tls_server_instance, 'registered_sensors'):
                for sensor_eui, sensor_data in tls_server_instance.registered_sensors.items():
                    if isinstance(sensor_data, dict):
                        for bs_info in sensor_data.get('base_stations', []):
                            if isinstance(bs_info, dict):
                                bs_eui = bs_info.get('base_station_eui', '').lower()
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
            
            result.append({
                "eui": eui_lower,
                "name": bs_data.get("name", ""),
                "tags": bs_data.get("tags", []),
                "status": status,
                "configured_ip": bs_data.get("ip", ""),
                "health": health,
                "connected_sensors": bs_sensors.get(eui_lower, 0)
            })
        
        result.sort(key=lambda x: (x["status"] != "connected", x["status"] != "connecting", x["eui"]))
        
        return jsonify({"success": True, "base_stations": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/base-stations/<eui>', methods=['GET'])
def get_base_station(eui):
    """Get single base station details"""
    try:
        config = load_base_station_config()
        bs_data = config.get("base_stations", {}).get(eui.lower(), {})
        return jsonify({"eui": eui.lower(), **bs_data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/base-stations', methods=['POST'])
def add_base_station():
    """Add new base station"""
    try:
        data = request.get_json()
        eui = data.get("eui", "").lower()
        
        if not eui or len(eui) != 16:
            return jsonify({"success": False, "error": "Invalid EUI"}), 400
        
        config = load_base_station_config()
        if eui in config.get("base_stations", {}):
            return jsonify({"success": False, "error": "Base station already exists"}), 400
        
        config["base_stations"][eui] = {
            "name": data.get("name", ""),
            "tags": data.get("tags", []),
            "ip": data.get("ip", "")
        }
        save_base_station_config(config)
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/base-stations/<eui>', methods=['PUT'])
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
            "ip": data.get("ip", "")
        }
        save_base_station_config(config)
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/base-stations/<eui>', methods=['DELETE'])
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

@app.route('/api/traffic/metrics')
def get_traffic_metrics():
    """Get traffic metrics for visualization"""
    try:
        global tls_server_instance
        if tls_server_instance and hasattr(tls_server_instance, 'get_traffic_metrics'):
            data = tls_server_instance.get_traffic_metrics()
            return jsonify({'success': True, **data})
        return jsonify({
            'success': True,
            'metrics': {
                'messages_in': 0,
                'messages_out': 0,
                'messages_dropped': 0,
                'bytes_in': 0,
                'bytes_out': 0,
                'vm_messages': 0,
                'attach_requests': 0,
                'detach_requests': 0,
                'status_requests': 0,
                'start_time': 0
            },
            'dedup_stats': {'total_messages': 0, 'duplicate_messages': 0, 'published_messages': 0},
            'history': [],
            'connections': 0
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/traffic/reset', methods=['POST'])
def reset_traffic_metrics():
    """Reset traffic metrics"""
    try:
        global tls_server_instance
        if tls_server_instance and hasattr(tls_server_instance, 'reset_traffic_metrics'):
            tls_server_instance.reset_traffic_metrics()
            return jsonify({'success': True, 'message': 'Traffic metrics reset successfully'})
        return jsonify({'success': False, 'message': 'TLS server not available'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/logs')
def get_logs():
    global log_entries

    # Get query parameters for filtering
    level_filter = request.args.get('level', 'all').upper()
    logger_filter = request.args.get('logger', 'all')
    limit = int(request.args.get('limit', 100))

    # Filter logs based on parameters
    filtered_logs = log_entries

    if level_filter != 'ALL':
        filtered_logs = [log for log in filtered_logs if log['level'] == level_filter]

    if logger_filter != 'all':
        filtered_logs = [log for log in filtered_logs if logger_filter.lower() in log['logger'].lower()]

    # Return the most recent logs (up to limit)
    recent_logs = filtered_logs[-limit:] if len(filtered_logs) > limit else filtered_logs

    return jsonify({
        'logs': recent_logs,
        'total_logs': len(log_entries),
        'filtered_logs': len(filtered_logs),
        'source': 'memory'
    })

# =========================
# UPDATE MANAGEMENT SYSTEM
# =========================

def get_current_version():
    """Get current version - works with or without Git"""
    try:
        # First try Git commands
        try:
            # Try to unlock git if needed
            lock_file = '.git/index.lock'
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                    print("Removed stale git lock file")
                except:
                    pass
            
            result = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                commit_hash = result.stdout.strip()
                
                # Try to get tag
                tag_result = subprocess.run(['git', 'describe', '--tags', '--exact-match', 'HEAD'], 
                                          capture_output=True, text=True, timeout=10)
                if tag_result.returncode == 0:
                    return tag_result.stdout.strip()
                else:
                    return f"commit-{commit_hash}"
        except FileNotFoundError:
            # Git not installed, use fallback
            pass
        except Exception as e:
            if "No such file or directory" in str(e):
                # Git not installed
                pass
            else:
                print(f"Git command error: {e}")
        
        # Fallback 1: try to read .git/HEAD directly
        try:
            with open('.git/HEAD', 'r') as f:
                head_ref = f.read().strip()
                if head_ref.startswith('ref: refs/heads/'):
                    # Get branch name and try to read commit
                    branch = head_ref.split('/')[-1]
                    ref_path = f'.git/refs/heads/{branch}'
                    try:
                        with open(ref_path, 'r') as ref_file:
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
            main_files = ['main.py', 'web_ui.py', 'TLSServer.py', 'mqtt_interface.py']
            latest_time = 0
            for file in main_files:
                if os.path.exists(file):
                    mtime = os.path.getmtime(file)
                    latest_time = max(latest_time, mtime)
            
            if latest_time > 0:
                date_str = time.strftime('%Y%m%d', time.localtime(latest_time))
                return f"local-{date_str}"
        except:
            pass
            
        return "local-version"
    except Exception as e:
        print(f"Error getting current version: {e}")
        return "version-unknown"

def get_remote_version():
    """Get latest remote version - works with or without Git"""
    try:
        # First try Git commands  
        try:
            # Try to unlock git if needed
            lock_file = '.git/index.lock'
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                except:
                    pass
            
            # Fetch latest from remote
            fetch_result = subprocess.run(['git', 'fetch', 'origin'], capture_output=True, text=True, timeout=30)
            if fetch_result.returncode != 0:
                print(f"Git fetch failed: {fetch_result.stderr}")
                return "fetch-failed"
            
            # Get latest commit hash from origin/main
            result = subprocess.run(['git', 'rev-parse', '--short', 'origin/main'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                commit_hash = result.stdout.strip()
                
                # Try to get latest tag
                tag_result = subprocess.run(['git', 'describe', '--tags', 'origin/main'], 
                                          capture_output=True, text=True, timeout=10)
                if tag_result.returncode == 0:
                    return tag_result.stdout.strip().split('-')[0]  # Get tag without commit info
                else:
                    return f"commit-{commit_hash}"
        except FileNotFoundError:
            # Git not installed, can't check remote
            pass
        except Exception as e:
            if "No such file or directory" in str(e):
                # Git not installed
                pass
            else:
                print(f"Git command error: {e}")
        
        # Without Git, we can't check remote versions
        return "git-required-for-remote"
    except Exception as e:
        print(f"Error getting remote version: {e}")
        return "remote-check-unavailable"

def get_commit_log(limit=5):
    """Get recent commit log - works with or without Git"""
    try:
        # First try Git commands
        try:
            # Try to unlock git if needed
            lock_file = '.git/index.lock'
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                except:
                    pass
            
            result = subprocess.run(['git', 'log', '--oneline', f'-{limit}'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                commits = []
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split(' ', 1)
                        commits.append({
                            'hash': parts[0],
                            'message': parts[1] if len(parts) > 1 else ''
                        })
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
            {'hash': 'local', 'message': 'Local installation - Git not available'},
            {'hash': 'info', 'message': 'Install Git to see commit history'},
            {'hash': 'note', 'message': 'Version checking works without Git'}
        ]
    except Exception as e:
        print(f"Error getting commit log: {e}")
        return [{'hash': 'error', 'message': f'Unable to get history: {str(e)}'}]

def check_for_updates():
    """Check if updates are available"""
    try:
        current = get_current_version()
        remote = get_remote_version()
        
        # Determine if updates are available
        updates_available = False
        status_message = None
        
        if remote in ['git-required-for-remote', 'remote-check-unavailable']:
            updates_available = False
            status_message = 'Git installation required for remote version checking'
        elif current.startswith('local-') and remote.startswith('git-required'):
            updates_available = False
            status_message = 'Local installation - remote checking requires Git'
        elif current != remote and not remote.startswith('git-required') and not remote.startswith('remote-'):
            updates_available = True
        
        result = {
            'current_version': current,
            'remote_version': remote,
            'updates_available': updates_available,
            'status': 'success'
        }
        
        if status_message:
            result['message'] = status_message
            
        return result
    except Exception as e:
        return {
            'current_version': 'unknown',
            'remote_version': 'unknown', 
            'updates_available': False,
            'status': 'error',
            'error': str(e)
        }

def create_backup():
    """Create backup before update"""
    try:
        backup_dir = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Create backup directory
        os.makedirs(backup_dir, exist_ok=True)
        
        # Backup important files
        files_to_backup = ['.env', 'endpoints.json']
        dirs_to_backup = ['logs', 'certs']
        
        for file in files_to_backup:
            if os.path.exists(file):
                shutil.copy2(file, backup_dir)
                
        for dir_name in dirs_to_backup:
            if os.path.exists(dir_name):
                shutil.copytree(dir_name, os.path.join(backup_dir, dir_name))
        
        return {'success': True, 'backup_dir': backup_dir}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def perform_update():
    """Perform git pull update"""
    try:
        # Create backup first
        backup_result = create_backup()
        if not backup_result['success']:
            return {'success': False, 'error': f"Backup failed: {backup_result['error']}"}
        
        # Perform git pull
        result = subprocess.run(['git', 'pull', 'origin', 'main'], 
                              capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            return {
                'success': True, 
                'message': 'Update completed successfully',
                'backup_dir': backup_result['backup_dir'],
                'git_output': result.stdout
            }
        else:
            return {
                'success': False, 
                'error': f"Git pull failed: {result.stderr}",
                'backup_dir': backup_result['backup_dir']
            }
    except Exception as e:
        return {'success': False, 'error': str(e)}

@app.route('/api/system/version')
def api_get_version():
    """Get current and remote version info"""
    try:
        version_info = check_for_updates()
        recent_commits = get_commit_log(5)
        
        return jsonify({
            **version_info,
            'recent_commits': recent_commits
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/system/check-updates')
def api_check_updates():
    """Check for available updates"""
    try:
        return jsonify(check_for_updates())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/system/update', methods=['POST'])
def api_perform_update():
    """Perform system update"""
    try:
        result = perform_update()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/system/restart', methods=['POST'])
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
        
        return jsonify({'success': True, 'message': 'Service restart initiated'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

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
                'running': False,
                'service_type': 'web_ui',
                'tls_server': {'active': False},
                'mqtt_broker': {'active': False},
                'base_stations': {'total_connected': 0, 'total_connecting': 0, 'connected': [], 'connecting': []},
                'total_sensors': 0,
                'registered_sensors': 0,
                'pending_requests': 0,
                'error': 'TLS server not available'
            }
            
        # Get base station status safely without asyncio operations
        bs_status = {'total_connected': 0, 'total_connecting': 0, 'connected': [], 'connecting': []}
        try:
            # Thread-safe access to base station collections
            connected_count = 0
            connecting_count = 0
            connected_stations = []
            connecting_stations = []
            
            if hasattr(tls_server, 'connected_base_stations'):
                connected_dict = getattr(tls_server, 'connected_base_stations', {})
                connected_count = len(connected_dict)
                for writer, bs_eui in list(connected_dict.items()):
                    connected_stations.append({
                        "eui": bs_eui.upper(),
                        "address": "connected",
                        "status": "connected"
                    })
            
            if hasattr(tls_server, 'connecting_base_stations'):
                connecting_dict = getattr(tls_server, 'connecting_base_stations', {})
                connecting_count = len(connecting_dict)
                for writer, bs_eui in list(connecting_dict.items()):
                    connecting_stations.append({
                        "eui": bs_eui.upper(),
                        "address": "connecting", 
                        "status": "connecting"
                    })
                
            bs_status = {
                "connected": connected_stations,
                "connecting": connecting_stations,
                "total_connected": connected_count,
                "total_connecting": connecting_count
            }
        except Exception as e:
            print(f"Error getting base station status: {e}")
            
        # Get sensor count safely
        total_sensors = 0
        registered_sensors = 0
        try:
            # Count sensors from config file instead of runtime status to avoid asyncio issues
            with open(bssci_config.SENSOR_CONFIG_FILE, 'r') as f:
                sensors = json.load(f)
                total_sensors = len(sensors)
                # For now, assume all configured sensors could be registered
                registered_sensors = total_sensors
        except Exception as e:
            print(f"Error counting sensors: {e}")

        # Build response safely
        response = {
            'running': True,
            'service_type': 'web_ui',
            'base_stations': bs_status,
            'tls_server': {
                'active': True,
                'listening_port': getattr(bssci_config, 'LISTEN_PORT', 16018),
                'connected_base_stations': bs_status.get('total_connected', 0),
                'total_sensors': total_sensors,
                'registered_sensors': registered_sensors
            },
            'mqtt_broker': {
                'active': True,
                'broker_host': getattr(bssci_config, 'MQTT_BROKER', 'localhost'),
                'broker_port': getattr(bssci_config, 'MQTT_PORT', 1883)
            },
            'total_sensors': total_sensors,
            'registered_sensors': registered_sensors,
            'pending_requests': 0  # Avoid accessing asyncio objects
        }
        
        return response
        
    except Exception as e:
        print(f"Error in get_bssci_service_status: {e}")
        import traceback
        traceback.print_exc()
        return {
            'running': False,
            'service_type': 'web_ui',
            'tls_server': {'active': False},
            'mqtt_broker': {'active': False},
            'base_stations': {'total_connected': 0, 'total_connecting': 0, 'connected': [], 'connecting': []},
            'total_sensors': 0,
            'registered_sensors': 0,
            'pending_requests': 0,
            'error': f'Status error: {str(e)}'
        }

@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    global log_entries
    log_entries = []
    return jsonify({'success': True, 'message': 'Logs cleared successfully'})

@app.route('/api/bssci/status')
@app.route('/api/service/status')  # Support both endpoints for compatibility
def bssci_status():
    try:
        status = get_bssci_service_status()
        return jsonify(status)
    except Exception as e:
        app.logger.error(f"Error in bssci_status endpoint: {e}")
        error_response = {
            'running': False,
            'error': f'Service status error: {str(e)}',
            'service_type': 'web_ui',
            'tls_server': {'active': False},
            'mqtt_broker': {'active': False},
            'base_stations': {'total_connected': 0, 'total_connecting': 0, 'connected': [], 'connecting': []},
            'total_sensors': 0,
            'registered_sensors': 0,
            'pending_requests': 0
        }
        return jsonify(error_response), 500

@app.route('/api/base_stations/status')
def get_base_stations_status():
    """Get status of connected base stations - thread-safe version (legacy endpoint)"""
    try:
        global tls_server_instance
        tls_server = tls_server_instance

        if not tls_server:
            return jsonify({
                "connected": [],
                "connecting": [],
                "total_connected": 0,
                "total_connecting": 0,
                "error": "TLS server not initialized"
            }), 503

        connected_stations = []
        connecting_stations = []
        
        try:
            if hasattr(tls_server, 'connected_base_stations'):
                connected_dict = getattr(tls_server, 'connected_base_stations', {})
                for writer, bs_eui in list(connected_dict.items()):
                    try:
                        connected_stations.append({
                            "eui": bs_eui,
                            "address": "connected",
                            "status": "connected"
                        })
                    except Exception as e:
                        print(f"Error processing connected station {bs_eui}: {e}")
            
            if hasattr(tls_server, 'connecting_base_stations'):
                connecting_dict = getattr(tls_server, 'connecting_base_stations', {})
                for writer, bs_eui in list(connecting_dict.items()):
                    try:
                        connecting_stations.append({
                            "eui": bs_eui,
                            "address": "connecting",
                            "status": "connecting"
                        })
                    except Exception as e:
                        print(f"Error processing connecting station {bs_eui}: {e}")
                        
        except Exception as e:
            print(f"Error accessing base station collections: {e}")

        return jsonify({
            "connected": connected_stations,
            "connecting": connecting_stations,
            "total_connected": len(connected_stations),
            "total_connecting": len(connecting_stations)
        })
            
    except Exception as e:
        print(f"Error in get_base_stations_status endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "connected": [],
            "connecting": [],
            "total_connected": 0,
            "total_connecting": 0,
            "error": f"Base stations error: {str(e)}"
        })

# ==================== Variable MAC (VM) Sub-Channel API ====================

@app.route('/api/vm/status')
def get_vm_status():
    """Get VM sub-channel status for all sensors"""
    try:
        global tls_server_instance
        if tls_server_instance and hasattr(tls_server_instance, 'get_vm_status'):
            status = tls_server_instance.get_vm_status()
            return jsonify({'success': True, **status})
        return jsonify({'success': False, 'message': 'TLS server not available', 'active_sensors': {}})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/vm/activate/<eui>', methods=['POST'])
def vm_activate_sensor(eui):
    """Activate VM sub-channel for a sensor"""
    try:
        global tls_server_instance
        if not tls_server_instance:
            return jsonify({'success': False, 'message': 'TLS server not available'}), 503
        
        data = request.json or {}
        vm_channel = data.get('vm_channel', 0)
        
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            success = loop.run_until_complete(tls_server_instance.vm_activate(eui, vm_channel))
        finally:
            loop.close()
        
        if success:
            return jsonify({'success': True, 'message': f'VM activate request sent for sensor {eui}'})
        else:
            return jsonify({'success': False, 'message': 'No base stations connected'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/vm/deactivate/<eui>', methods=['POST'])
def vm_deactivate_sensor(eui):
    """Deactivate VM sub-channel for a sensor"""
    try:
        global tls_server_instance
        if not tls_server_instance:
            return jsonify({'success': False, 'message': 'TLS server not available'}), 503
        
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            success = loop.run_until_complete(tls_server_instance.vm_deactivate(eui))
        finally:
            loop.close()
        
        if success:
            return jsonify({'success': True, 'message': f'VM deactivate request sent for sensor {eui}'})
        else:
            return jsonify({'success': False, 'message': 'No base stations connected'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/vm/query/<eui>', methods=['POST'])
def vm_query_sensor(eui):
    """Query VM sub-channel status for a sensor"""
    try:
        global tls_server_instance
        if not tls_server_instance:
            return jsonify({'success': False, 'message': 'TLS server not available'}), 503
        
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            success = loop.run_until_complete(tls_server_instance.vm_status(eui))
        finally:
            loop.close()
        
        if success:
            return jsonify({'success': True, 'message': f'VM status query sent for sensor {eui}'})
        else:
            return jsonify({'success': False, 'message': 'No base stations connected'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/vm/send/<eui>', methods=['POST'])
def vm_send_data_to_sensor(eui):
    """Send data to sensor via VM sub-channel (downlink)"""
    try:
        global tls_server_instance
        if not tls_server_instance:
            return jsonify({'success': False, 'message': 'TLS server not available'}), 503
        
        data = request.json
        if not data or 'data' not in data:
            return jsonify({'success': False, 'message': 'Missing data field'}), 400
        
        payload = bytes.fromhex(data['data']) if isinstance(data['data'], str) else bytes(data['data'])
        port = data.get('port', 1)
        
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            success = loop.run_until_complete(tls_server_instance.vm_send_data(eui, payload, port))
        finally:
            loop.close()
        
        if success:
            return jsonify({'success': True, 'message': f'VM downlink data sent to sensor {eui}'})
        else:
            return jsonify({'success': False, 'message': 'Failed to send VM data - VM may not be active for this sensor'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/certificates/status')
def get_certificate_status():
    """Get status of SSL certificates"""
    import os
    from datetime import datetime
    try:
        cert_files = {
            'ca': 'certs/ca_cert.pem',
            'service': 'certs/service_center_cert.pem',
            'key': 'certs/service_center_key.pem'
        }

        status = {'certificates': {}}

        for cert_type, file_path in cert_files.items():
            if os.path.exists(file_path):
                status['certificates'][cert_type] = True
                # Try to get certificate expiry date
                try:
                    if cert_type != 'key':  # Don't try to parse private key as certificate
                        import ssl
                        import socket
                        from cryptography import x509
                        from cryptography.hazmat.backends import default_backend

                        with open(file_path, 'rb') as f:
                            cert_data = f.read()
                            cert = x509.load_pem_x509_certificate(cert_data, default_backend())
                            expiry = cert.not_valid_after
                            status['certificates'][f'{cert_type}_expires'] = expiry.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    pass  # If we can't read the certificate, just mark as present
            else:
                status['certificates'][cert_type] = False

        return jsonify({'success': True, 'certificates': status['certificates']})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/certificates/download/<filename>')
def download_certificate(filename):
    """Download a certificate file"""
    import os
    from flask import send_file, abort

    # Security: only allow specific certificate files
    allowed_files = ['ca_cert.pem', 'service_center_cert.pem', 'service_center_key.pem']
    if filename not in allowed_files:
        abort(404)

    file_path = os.path.join('certs', filename)
    if not os.path.exists(file_path):
        abort(404)

    return send_file(file_path, as_attachment=True, download_name=filename)

@app.route('/api/certificates/upload/<cert_type>', methods=['POST'])
def upload_certificate(cert_type):
    """Upload a new certificate"""
    import os
    from werkzeug.utils import secure_filename

    if 'certificate' not in request.files:
        return jsonify({'success': False, 'message': 'No file provided'})

    file = request.files['certificate']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'})

    # Map cert types to filenames
    cert_mapping = {
        'ca': 'ca_cert.pem',
        'service': 'service_center_cert.pem',
        'key': 'service_center_key.pem'
    }

    if cert_type not in cert_mapping:
        return jsonify({'success': False, 'message': 'Invalid certificate type'})

    try:
        # Ensure certs directory exists
        os.makedirs('certs', exist_ok=True)

        # Backup existing file
        target_file = os.path.join('certs', cert_mapping[cert_type])
        if os.path.exists(target_file):
            backup_file = target_file + '.backup'
            os.rename(target_file, backup_file)

        # Save new file
        file.save(target_file)

        return jsonify({'success': True, 'message': f'{cert_type.upper()} certificate uploaded successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/certificates/generate', methods=['POST'])
def generate_certificates():
    """Generate new SSL certificates"""
    import os
    import subprocess

    try:
        # Ensure certs directory exists
        os.makedirs('certs', exist_ok=True)

        # Generate new certificates using OpenSSL with static, validated commands
        import shlex

        # Execute certificate generation commands with completely static strings

        # Generate CA private key
        result = subprocess.run(['openssl', 'genrsa', '-out', 'certs/ca_key.pem', '2048'],
                               capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return jsonify({'success': False, 'message': f'CA key generation failed: {result.stderr}'})

        # Generate CA certificate
        result = subprocess.run(['openssl', 'req', '-new', '-x509', '-key', 'certs/ca_key.pem', '-out', 'certs/ca_cert.pem', '-days', '365', '-subj', '/C=US/ST=State/L=City/O=BSSCI/CN=BSSCI-CA'],
                               capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return jsonify({'success': False, 'message': f'CA certificate generation failed: {result.stderr}'})

        # Generate service private key
        result = subprocess.run(['openssl', 'genrsa', '-out', 'certs/service_center_key.pem', '2048'],
                               capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return jsonify({'success': False, 'message': f'Service key generation failed: {result.stderr}'})

        # Generate service certificate request
        result = subprocess.run(['openssl', 'req', '-new', '-key', 'certs/service_center_key.pem', '-out', 'certs/service_center.csr', '-subj', '/C=US/ST=State/L=City/O=BSSCI/CN=bssci-service'],
                               capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return jsonify({'success': False, 'message': f'Service certificate request generation failed: {result.stderr}'})

        # Sign service certificate with CA
        result = subprocess.run(['openssl', 'x509', '-req', '-in', 'certs/service_center.csr', '-CA', 'certs/ca_cert.pem', '-CAkey', 'certs/ca_key.pem', '-CAcreateserial', '-out', 'certs/service_center_cert.pem', '-days', '365'],
                               capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return jsonify({'success': False, 'message': f'Service certificate signing failed: {result.stderr}'})

        # Clean up temporary files
        temp_files = ['certs/service_center.csr', 'certs/ca_cert.srl']
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                os.remove(temp_file)

        return jsonify({'success': True, 'message': 'New certificates generated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/certificates/backup')
def backup_certificates():
    """Download all certificates as ZIP"""
    import os
    import tempfile
    import zipfile
    from flask import send_file

    try:
        # Create temporary ZIP file
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')

        with zipfile.ZipFile(temp_zip.name, 'w') as zipf:
            cert_files = ['ca_cert.pem', 'service_center_cert.pem', 'service_center_key.pem']
            for cert_file in cert_files:
                file_path = os.path.join('certs', cert_file)
                if os.path.exists(file_path):
                    zipf.write(file_path, cert_file)

        return send_file(temp_zip.name, as_attachment=True, download_name='bssci_certificates_backup.zip')
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/certificates/restore', methods=['POST'])
def restore_certificates():
    """Restore certificates from ZIP backup"""
    import os
    import tempfile
    import zipfile

    if 'backup' not in request.files:
        return jsonify({'success': False, 'message': 'No backup file provided'})

    file = request.files['backup']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'})

    try:
        # Save uploaded ZIP to temporary location
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        file.save(temp_zip.name)

        # Extract certificates
        with zipfile.ZipFile(temp_zip.name, 'r') as zipf:
            # Ensure certs directory exists
            os.makedirs('certs', exist_ok=True)

            # Extract only certificate files
            cert_files = ['ca_cert.pem', 'service_center_cert.pem', 'service_center_key.pem']
            for cert_file in cert_files:
                if cert_file in zipf.namelist():
                    target_path = os.path.join('certs', cert_file)
                    # Backup existing file
                    if os.path.exists(target_path):
                        os.rename(target_path, target_path + '.backup')
                    # Extract new file
                    zipf.extract(cert_file, 'certs')

        # Clean up temporary file
        os.unlink(temp_zip.name)

        return jsonify({'success': True, 'message': 'Certificates restored successfully from backup'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/container/restart', methods=['POST'])
def restart_container():
    """Force restart the entire container"""
    import subprocess
    import threading
    import time
    import os

    def container_restart_in_background():
        """Perform container restart in a separate thread"""
        try:
            time.sleep(1)  # Small delay to allow response to be sent
            
            logger.info("Forcing container restart")
            try:
                # Send SIGTERM to PID 1 (init process) to restart the container
                subprocess.run(['kill', '-TERM', '1'], check=False, timeout=5)
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
        
        return jsonify({'success': True, 'message': 'Container restart initiated. The container will restart completely to reload all environment variables.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/service/restart', methods=['POST'])
def restart_service():
    """Restart the BSSCI service with full environment reload"""
    import subprocess
    import threading
    import time
    import os

    def restart_in_background():
        """Perform the restart operation in a separate thread"""
        try:
            time.sleep(1)  # Small delay to allow response to be sent

            # Check if we're running in Docker
            is_docker = os.path.exists('/.dockerenv') or os.getenv('CONTAINER') == '1'
            
            # Check environment type
            is_replit = os.getenv('REPLIT_ENVIRONMENT') or os.getenv('REPL_SLUG')
            
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

        return jsonify({'success': True, 'message': 'Service restart initiated. In Docker environments, the entire container will restart to reload environment variables.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)