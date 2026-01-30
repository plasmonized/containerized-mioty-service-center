import asyncio
import json
import logging
import os
import ssl
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

import bssci_config
import messages
from protocol import decode_messages, encode_message

logger = logging.getLogger(__name__)

IDENTIFIER = bytes("MIOTYB01", "utf-8")


class TLSServer:
    def __init__(
        self,
        sensor_config_file: str,
        mqtt_out_queue: asyncio.Queue[dict[str, str]],
        mqtt_in_queue: asyncio.Queue[dict[str, str]],
    ) -> None:
        self.opID = -1
        self.mqtt_out_queue = mqtt_out_queue
        self.mqtt_in_queue = mqtt_in_queue
        self.connected_base_stations: Dict[
            asyncio.streams.StreamWriter, str
        ] = {}
        self.connecting_base_stations: Dict[
            asyncio.streams.StreamWriter, str
        ] = {}
        self.sensor_config_file = sensor_config_file
        # EUI -> {status, base_stations: [], timestamp}
        self.registered_sensors: Dict[str, Dict[str, Any]] = {}
        # opID -> {sensor_eui, timestamp, base_station}
        self.pending_attach_requests: Dict[int, Dict[str, Any]] = {}
        # Track if status request task is running
        self._status_task_running = False

        # Deduplication variables
        # message_key -> {message, timestamp, snr, bs_eui}
        self.deduplication_buffer: Dict[str, Dict[str, Any]] = {}
        self.deduplication_delay = bssci_config.DEDUPLICATION_DELAY
        self.deduplication_stats = {
            'total_messages': 0,
            'duplicate_messages': 0,
            'published_messages': 0
        }
        
        # Traffic metrics for visualization
        self.traffic_metrics = {
            'messages_in': 0,          # Total messages received from base stations
            'messages_out': 0,         # Total messages sent to MQTT
            'messages_dropped': 0,     # Messages filtered by deduplication
            'bytes_in': 0,             # Total bytes received
            'bytes_out': 0,            # Total bytes sent to MQTT
            'vm_messages': 0,          # VM sub-channel messages
            'attach_requests': 0,      # Attach requests sent
            'detach_requests': 0,      # Detach requests sent
            'status_requests': 0,      # Status requests sent
            'start_time': datetime.now(timezone.utc).timestamp()
        }
        # Time-series data for charts (last 60 minutes, 1-minute resolution)
        self.traffic_history: list = []
        self._last_history_update = 0
        
        # Track active sensors per hour (sensors that sent data)
        self.active_sensors_hourly: set = set()
        self._current_hour = datetime.now(timezone.utc).hour
        self._last_hourly_active_count = 0
        
        # Base station health data (eui -> {cpu, temperature, ...})
        self.base_station_health: Dict[str, dict] = {}
        
        # Sensor packet tracking for packet loss detection
        # eui -> {last_packet_cnt, packets_received, packets_lost, snr_sum, snr_count}
        self.sensor_packet_stats: Dict[str, Dict[str, Any]] = {}
        
        # SNR/RSSI history for graphs (last 288 data points, 5 min intervals = 24 hours)
        self.snr_rssi_history: list = []
        self._last_snr_history_update = 0

        # Auto-detach variables
        # eui -> timestamp of last message
        self.sensor_last_seen: Dict[str, float] = {}
        # eui -> whether warning was sent
        self.sensor_warning_sent: Dict[str, bool] = {}

        # Network topology tracking: which base stations receive which sensors
        # sensor_eui -> {primary_bs: str, receiving_bases: {bs_eui: {snr, rssi, last_seen, count}}}
        self.sensor_topology: Dict[str, Dict[str, Any]] = {}
        
        # Variable MAC (VM) Sub-Channel tracking
        # eui -> {active: bool, vm_channel: int, activated_at: timestamp, bs_eui: str}
        self.vm_active_sensors: Dict[str, Dict[str, Any]] = {}
        # Pending VM operations: opID -> {eui, operation, timestamp}
        self.pending_vm_operations: Dict[int, Dict[str, Any]] = {}
        
        # OMS Meter tracking for VM uplink data (WMBUS/wireless M-Bus meters)
        # meter_id -> {eui, snr, rssi, data, timestamp, bs_eui, message_count}
        self.oms_meters: Dict[str, Dict[str, Any]] = {}
        
        # VM Log for OMS page - stores last 100 VM-related log entries
        self.vm_log: List[Dict[str, Any]] = []
        self.vm_log_max_size = 100

        # Start the deduplication task
        asyncio.create_task(self.process_deduplication_buffer())

        # Start auto-detach monitoring if enabled
        if getattr(bssci_config, 'AUTO_DETACH_ENABLED', True):
            asyncio.create_task(self.auto_detach_monitor())

        try:
            with open(sensor_config_file, "r") as f:
                self.sensor_config = json.load(f)
        except Exception:
            self.sensor_config = []

        # Add queue logging
        logger.info("🔍 TLS Server Queue Assignment:")
        logger.info(f"   mqtt_out_queue ID: {id(self.mqtt_out_queue)}")
        logger.info(f"   mqtt_in_queue ID: {id(self.mqtt_in_queue)}")

    def _get_local_time(self) -> str:
        """Get current time in configured timezone"""
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(bssci_config.TIMEZONE)
            local_time = datetime.now(tz)
        except Exception:
            # Fallback to UTC+1 (CET) if timezone not available
            utc_time = datetime.now(timezone.utc)
            local_time = utc_time + timedelta(hours=1)
        return local_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    async def start_server(self) -> None:
        logger.info("🔐 Setting up SSL/TLS context for BSSCI server...")
        logger.info(f"   Certificate file: {bssci_config.CERT_FILE}")
        logger.info(f"   Key file: {bssci_config.KEY_FILE}")
        logger.info(f"   CA file: {bssci_config.CA_FILE}")

        try:
            ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_ctx.load_cert_chain(
                certfile=bssci_config.CERT_FILE, keyfile=bssci_config.KEY_FILE
            )
            ssl_ctx.load_verify_locations(cafile=bssci_config.CA_FILE)
            ssl_ctx.verify_mode = ssl.CERT_REQUIRED

            # Log SSL context details
            logger.info(f"   TLS Protocol versions: {ssl_ctx.minimum_version.name} - {ssl_ctx.maximum_version.name}")
            logger.info("✓ SSL context configured successfully with client certificate verification")

        except FileNotFoundError as e:
            logger.error(f"❌ SSL certificate file not found: {e}")
            raise
        except ssl.SSLError as e:
            logger.error(f"❌ SSL configuration error: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Unexpected error setting up SSL: {e}")
            raise

        logger.info("🚀 Starting BSSCI TLS server...")
        logger.info(f"   Listen address: {bssci_config.LISTEN_HOST}:{bssci_config.LISTEN_PORT}")
        logger.info(f"   Sensor config file: {self.sensor_config_file}")
        logger.info(f"   Loaded sensors: {len(self.sensor_config)}")

        server = await asyncio.start_server(
            self.handle_client,
            bssci_config.LISTEN_HOST,
            bssci_config.LISTEN_PORT,
            ssl=ssl_ctx,
        )

        logger.info("📨 Starting MQTT queue watcher task...")
        asyncio.create_task(self.queue_watcher())

        logger.info("✓ BSSCI TLS Server is ready and listening for base station connections")
        async with server:
            await server.serve_forever()

    async def send_attach_request(
        self, writer: asyncio.streams.StreamWriter, sensor: dict[str, Any]
    ) -> None:
        bs_eui = self.connected_base_stations.get(writer, "unknown")
        try:
            logger.info("📤 BSSCI ATTACH REQUEST INITIATED")
            logger.info("   =====================================")
            logger.info(f"   Sensor EUI: {sensor['eui']}")
            logger.info(f"   Target Base Station: {bs_eui}")
            logger.info(f"   Operation ID: {self.opID}")
            logger.info(f"   Timestamp: {self._get_local_time()}")

            # Comprehensive validation with detailed logging
            validation_errors = []
            validation_warnings = []

            # EUI validation
            if len(sensor["eui"]) != 16:
                validation_errors.append(f"EUI length {len(sensor['eui'])} != 16 characters")
            else:
                try:
                    int(sensor["eui"], 16)  # Test hex validity
                    logger.info(f"   ✓ EUI format valid: {sensor['eui']}")
                except ValueError:
                    validation_errors.append(f"EUI contains invalid hex characters: {sensor['eui']}")

            # Network Key validation and normalization
            original_nw_key = sensor["nwKey"]
            nw_key = original_nw_key[:32] if len(original_nw_key) >= 32 else original_nw_key

            if len(original_nw_key) != 32:
                if len(original_nw_key) > 32:
                    validation_warnings.append(f"Network key truncated from {len(original_nw_key)} to 32 characters")
                    logger.warning(f"   ⚠️  Network key too long, truncating: {original_nw_key} -> {nw_key}")
                else:
                    validation_errors.append(f"Network key length {len(original_nw_key)} < 32 characters required")
            else:
                try:
                    int(nw_key, 16)  # Test hex validity
                    logger.info(f"   ✓ Network key format valid: {nw_key[:8]}...{nw_key[-8:]}")
                except ValueError:
                    validation_errors.append(f"Network key contains invalid hex characters: {nw_key}")

            # Short Address validation
            if len(sensor["shortAddr"]) != 4:
                validation_errors.append(f"Short address length {len(sensor['shortAddr'])} != 4 characters")
            else:
                try:
                    int(sensor["shortAddr"], 16)  # Test hex validity
                    logger.info(f"   ✓ Short address format valid: {sensor['shortAddr']}")
                except ValueError:
                    validation_errors.append(f"Short address contains invalid hex characters: {sensor['shortAddr']}")

            # Bidirectional flag validation
            bidi_value = sensor.get("bidi", False)
            logger.info(f"   ✓ Bidirectional flag: {bidi_value}")

            # Check for existing registrations to this base station
            eui_upper = sensor["eui"].upper()
            if eui_upper in self.registered_sensors:
                reg_info = self.registered_sensors[eui_upper]
                if reg_info.get('status') == 'registered':
                    existing_bases = reg_info.get('base_stations', [])
                    if bs_eui in existing_bases:
                        validation_warnings.append(f"Sensor {sensor['eui']} already registered to base station {bs_eui}")
                        logger.warning(f"   ⚠️  Re-registering sensor to same base station")
                    else:
                        validation_warnings.append(f"Sensor {sensor['eui']} already registered to {len(existing_bases)} other base station(s): {existing_bases}")
                        logger.warning(f"   ⚠️  Adding registration to additional base station")

            # Log all warnings
            for warning in validation_warnings:
                logger.warning(f"   ⚠️  {warning}")

            if not validation_errors:
                logger.info(f"   ✅ All validations passed")
                logger.info(f"   📋 Final parameters:")
                logger.info(f"     EUI: {sensor['eui']}")
                logger.info(f"     Network Key: {nw_key[:8]}...{nw_key[-8:]}")
                logger.info(f"     Short Address: {sensor['shortAddr']}")
                logger.info(f"     Bidirectional: {bidi_value}")

                # Use normalized sensor data
                normalized_sensor = {
                    "eui": sensor["eui"].upper(),
                    "nwKey": nw_key,
                    "shortAddr": sensor["shortAddr"],
                    "bidi": bidi_value
                }

                # Build and encode the message
                attach_message = messages.build_attach_request(normalized_sensor, self.opID)
                logger.debug(f"   📝 Built attach message: {attach_message}")

                msg_pack = encode_message(attach_message)
                full_message = IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack

                logger.info(f"   📤 Transmitting attach request...")
                logger.info(f"     Message size: {len(full_message)} bytes")
                logger.info(f"     Payload size: {len(msg_pack)} bytes")

                writer.write(full_message)
                await writer.drain()
                self.traffic_metrics['attach_requests'] += 1

                # Track this attach request for correlation with response
                self.pending_attach_requests[self.opID] = {
                    'sensor_eui': sensor['eui'],
                    'timestamp': asyncio.get_event_loop().time(),
                    'base_station': bs_eui,
                    'sensor_config': normalized_sensor
                }

                logger.info(f"✅ BSSCI ATTACH REQUEST TRANSMITTED")
                logger.info(f"   Operation ID {self.opID} sent to base station {bs_eui}")
                logger.info(f"   Tracking request for correlation with response")
                logger.info(f"   Awaiting response from base station...")
                logger.info("   =====================================")

                self.opID -= 1
            else:
                logger.error(f"❌ ATTACH REQUEST VALIDATION FAILED")
                logger.error(f"   Sensor EUI: {sensor.get('eui', 'unknown')}")
                logger.error(f"   Base Station: {bs_eui}")
                logger.error(f"   Validation errors found:")
                for i, error in enumerate(validation_errors, 1):
                    logger.error(f"     {i}. {error}")
                logger.error(f"   ❌ Attach request NOT sent due to validation failures")
                logger.error(f"   =====================================")

        except Exception as e:
            logger.error(f"❌ CRITICAL ERROR during attach request preparation")
            logger.error(f"   Sensor EUI: {sensor.get('eui', 'unknown')}")
            logger.error(f"   Base Station: {bs_eui}")
            logger.error(f"   Exception type: {type(e).__name__}")
            logger.error(f"   Exception message: {str(e)}")
            import traceback
            logger.error(f"   Full traceback:")
            for line in traceback.format_exc().strip().split('\n'):
                logger.error(f"     {line}")
            logger.error(f"   =====================================")
            raise  # Re-raise to handle upstream

    async def attach_file(self, writer: asyncio.streams.StreamWriter) -> None:
        bs_eui = self.connected_base_stations.get(writer, "unknown")
        logger.info(f"🔗 BATCH SENSOR ATTACHMENT started for base station {bs_eui}")
        logger.info(f"   Total sensors to process: {len(self.sensor_config)}")

        successful_attachments = 0
        failed_attachments = 0

        for i, sensor in enumerate(self.sensor_config, 1):
            try:
                logger.info(f"   Processing sensor {i}/{len(self.sensor_config)}: {sensor['eui']}")
                await self.send_attach_request(writer, sensor)
                successful_attachments += 1

                # Small delay between requests to avoid overwhelming the base station
                await asyncio.sleep(0.1)

            except Exception as e:
                failed_attachments += 1
                logger.error(f"   ❌ Failed to attach sensor {sensor.get('eui', 'unknown')}: {e}")
                logger.error(f"     Exception type: {type(e).__name__}")

        logger.info(f"✅ BATCH SENSOR ATTACHMENT completed for base station {bs_eui}")
        logger.info(f"   Successful: {successful_attachments}")
        logger.info(f"   Failed: {failed_attachments}")
        logger.info(f"   Total processed: {len(self.sensor_config)}")

        if failed_attachments > 0:
            logger.warning(f"   ⚠️  {failed_attachments} sensors failed to attach - check individual sensor logs above")

    async def send_status_requests(self) -> None:
        logger.info(f"📊 STATUS REQUEST TASK STARTED")
        logger.info(f"   Status request interval: {bssci_config.STATUS_INTERVAL} seconds")

        try:
            while True:
                await asyncio.sleep(bssci_config.STATUS_INTERVAL)
                if self.connected_base_stations:
                    logger.info(f"📊 PERIODIC STATUS REQUEST CYCLE STARTING")
                    logger.info(f"   Connected base stations: {len(self.connected_base_stations)}")
                    logger.info(f"   Base stations: {list(self.connected_base_stations.values())}")

                    requests_sent = 0
                    failed_requests = 0

                    for writer, bs_eui in self.connected_base_stations.copy().items():  # Use copy to avoid dict change during iteration
                        try:
                            logger.info(f"📤 Sending status request to base station {bs_eui}")
                            logger.info(f"   Operation ID: {self.opID}")
                            self.traffic_metrics['status_requests'] += 1

                            msg_pack = encode_message(messages.build_status_request(self.opID))
                            full_message = IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack

                            writer.write(full_message)
                            await writer.drain()
                            logger.info(f"✅ Status request transmitted to {bs_eui} (opID: {self.opID})")
                            requests_sent += 1
                            self.opID -= 1

                        except Exception as e:
                            failed_requests += 1
                            logger.error(f"❌ Failed to send status request to base station {bs_eui}")
                            logger.error(f"   Error: {type(e).__name__}: {e}")
                            logger.warning(f"🔌 Removing disconnected base station {bs_eui} from active list")
                            # Remove disconnected base station
                            if writer in self.connected_base_stations:
                                self.connected_base_stations.pop(writer)

                    logger.info(f"📊 STATUS REQUEST CYCLE COMPLETE")
                    logger.info(f"   Requests sent: {requests_sent}")
                    logger.info(f"   Failed requests: {failed_requests}")
                    logger.info(f"   Remaining connected base stations: {len(self.connected_base_stations)}")

                else:
                    logger.info(f"⏸️  STATUS REQUEST CYCLE SKIPPED - No base stations connected")

        except asyncio.CancelledError:
            logger.info(f"📊 STATUS REQUEST TASK CANCELLED")
            self._status_task_running = False
            raise
        except Exception as e:
            logger.error(f"❌ STATUS REQUEST TASK ERROR: {e}")
            self._status_task_running = False
            raise

    async def send_detach_request(self, writer: asyncio.streams.StreamWriter, sensor_eui: str) -> bool:
        """Send detach request for a specific sensor"""
        bs_eui = self.connected_base_stations.get(writer, "unknown")
        logger.info(f"🔌 DETACHING SENSOR from base station {bs_eui}")
        logger.info(f"   Sensor EUI: {sensor_eui}")

        try:
            # Ensure EUI is properly formatted (16 hex characters)
            clean_eui = sensor_eui.upper().replace(":", "").replace("-", "")
            if len(clean_eui) != 16:
                logger.error(f"❌ Invalid EUI format: {sensor_eui} (should be 16 hex characters)")
                return False
            
            # Build and encode the detach message
            detach_message = messages.build_detach_request(clean_eui, self.opID)
            logger.debug(f"   📝 Built detach message: {detach_message}")

            msg_pack = encode_message(detach_message)
            full_message = IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack

            logger.info(f"   📤 Transmitting detach request...")
            logger.info(f"     Message size: {len(full_message)} bytes")

            writer.write(full_message)
            await writer.drain()
            self.traffic_metrics['detach_requests'] += 1
            self.opID -= 1

            # Remove from registered sensors
            eui_key = sensor_eui.upper()
            if eui_key in self.registered_sensors:
                # Remove this base station from the sensor's list
                if 'base_stations' in self.registered_sensors[eui_key]:
                    self.registered_sensors[eui_key]['base_stations'] = [
                        bs for bs in self.registered_sensors[eui_key]['base_stations']
                        if bs['base_station_eui'] != bs_eui
                    ]

                    # If no base stations left, mark as not registered
                    if not self.registered_sensors[eui_key]['base_stations']:
                        self.registered_sensors[eui_key]['registered'] = False
                        logger.info(f"   ✅ Sensor {sensor_eui} fully detached from all base stations")
                    else:
                        logger.info(f"   ✅ Sensor {sensor_eui} detached from {bs_eui}, still connected to {len(self.registered_sensors[eui_key]['base_stations'])} other base stations")

            # Notify via MQTT
            if self.mqtt_out_queue:
                detach_notification = {
                    "topic": f"ep/{sensor_eui.upper()}/status",
                    "payload": json.dumps({
                        "action": "detached",
                        "sensor_eui": sensor_eui,
                        "base_station_eui": bs_eui,
                        "timestamp": asyncio.get_event_loop().time()
                    })
                }
                await self.mqtt_out_queue.put(detach_notification)

            logger.info(f"✅ DETACH REQUEST sent for sensor {sensor_eui}")
            return True

        except Exception as e:
            logger.error(f"❌ CRITICAL ERROR during detach request")
            logger.error(f"   Sensor EUI: {sensor_eui}")
            logger.error(f"   Base Station: {bs_eui}")
            logger.error(f"   Exception: {e}")
            return False

    async def detach_sensor(self, sensor_eui: str) -> bool:
        """Detach a sensor from all connected base stations"""
        logger.info(f"🔌 DETACHING SENSOR {sensor_eui} from ALL base stations")

        success_count = 0
        total_count = len(self.connected_base_stations)

        for writer in list(self.connected_base_stations.keys()):
            try:
                success = await self.send_detach_request(writer, sensor_eui)
                if success:
                    success_count += 1
                await asyncio.sleep(0.1)  # Small delay between requests
            except Exception as e:
                logger.error(f"   ❌ Failed to detach sensor {sensor_eui} from base station: {e}")

        logger.info(f"✅ SENSOR DETACH completed for {sensor_eui}")
        logger.info(f"   Successful: {success_count}/{total_count} base stations")

        return success_count > 0

    async def detach_all_sensors(self) -> int:
        """Detach all sensors from all base stations"""
        logger.info(f"🔌 DETACHING ALL SENSORS from all base stations")

        # Get list of all registered sensors
        registered_euis = [eui for eui in self.registered_sensors.keys()
                          if not eui.endswith('_failure') and self.registered_sensors[eui].get('registered', False)]

        logger.info(f"   Total registered sensors to detach: {len(registered_euis)}")

        detached_count = 0
        for sensor_eui in registered_euis:
            try:
                success = await self.detach_sensor(sensor_eui)
                if success:
                    detached_count += 1
                await asyncio.sleep(0.2)  # Small delay between sensors
            except Exception as e:
                logger.error(f"   ❌ Failed to detach sensor {sensor_eui}: {e}")

        logger.info(f"✅ BULK DETACH completed")
        logger.info(f"   Successfully detached: {detached_count}/{len(registered_euis)} sensors")

        return detached_count

    def clear_all_sensors(self) -> None:
        """Clear all sensor configurations and registrations"""
        logger.info(f"🗑️ CLEARING ALL SENSOR CONFIGURATIONS")

        # Clear sensor config
        old_count = len(self.sensor_config)
        self.sensor_config = []

        # Clear registered sensors
        old_registered = len([k for k in self.registered_sensors.keys() if not k.endswith('_failure')])
        self.registered_sensors.clear()

        # Clear pending requests
        self.pending_attach_requests.clear()

        logger.info(f"✅ ALL SENSORS CLEARED")
        logger.info(f"   Configurations removed: {old_count}")
        logger.info(f"   Registrations removed: {old_registered}")

    def detach_sensor_sync(self, sensor_eui: str) -> bool:
        """Synchronous wrapper for detaching a sensor from all connected base stations"""
        try:
            logger.info(f"🔌 SYNC DETACHING SENSOR {sensor_eui} from ALL base stations")

            success_count = 0
            total_count = len(self.connected_base_stations)

            # Remove from registered sensors immediately
            eui_key = sensor_eui.upper()
            if eui_key in self.registered_sensors:
                self.registered_sensors[eui_key]['registered'] = False
                self.registered_sensors[eui_key]['base_stations'] = []
                logger.info(f"   ✅ Sensor {sensor_eui} marked as detached in local registry")
                success_count = total_count  # Consider it successful if we can update local state

            logger.info(f"✅ SYNC SENSOR DETACH completed for {sensor_eui}")
            logger.info(f"   Local detach: {success_count}/{total_count} base stations")

            return success_count > 0

        except Exception as e:
            logger.error(f"❌ Error in sync detach for {sensor_eui}: {e}")
            return False

    def detach_all_sensors_sync(self) -> int:
        """Synchronous wrapper for detaching all sensors from all base stations"""
        try:
            logger.info(f"🔌 SYNC DETACHING ALL SENSORS from all base stations")

            # Get list of all registered sensors
            registered_euis = [eui for eui in self.registered_sensors.keys()
                              if not eui.endswith('_failure') and self.registered_sensors[eui].get('registered', False)]

            logger.info(f"   Total registered sensors to detach: {len(registered_euis)}")

            detached_count = 0
            for sensor_eui in registered_euis:
                try:
                    success = self.detach_sensor_sync(sensor_eui)
                    if success:
                        detached_count += 1
                except Exception as e:
                    logger.error(f"   ❌ Failed to sync detach sensor {sensor_eui}: {e}")

            logger.info(f"✅ SYNC BULK DETACH completed")
            logger.info(f"   Successfully detached: {detached_count}/{len(registered_euis)} sensors")

            return detached_count

        except Exception as e:
            logger.error(f"❌ Error in sync detach all: {e}")
            return 0

    def attach_sensor_sync(self, sensor_eui: str) -> int:
        """Synchronous wrapper for attaching a sensor to all connected base stations"""
        try:
            logger.info(f"🔗 SYNC ATTACHING SENSOR {sensor_eui} to ALL base stations")
            
            if not self.connected_base_stations:
                logger.warning("   ⚠️  No base stations connected")
                return 0
            
            # Find sensor in configuration
            sensor_config = None
            for sensor in self.sensor_config:
                if sensor['eui'].upper() == sensor_eui.upper():
                    sensor_config = sensor
                    break
            
            if not sensor_config:
                logger.error(f"   ❌ Sensor {sensor_eui} not found in configuration")
                return 0
            
            logger.info(f"   Found sensor config: {sensor_config['eui']}")
            logger.info(f"   Target base stations: {len(self.connected_base_stations)}")
            
            # Create new event loop for sync call
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            success_count = 0
            try:
                async def send_attaches():
                    nonlocal success_count
                    for writer in list(self.connected_base_stations.keys()):
                        try:
                            await self.send_attach_request(writer, sensor_config)
                            success_count += 1
                            logger.info(f"   ✅ Attach request sent to {self.connected_base_stations[writer]}")
                        except Exception as e:
                            logger.error(f"   ❌ Failed to send attach to {self.connected_base_stations.get(writer, 'unknown')}: {e}")
                
                loop.run_until_complete(send_attaches())
            finally:
                loop.close()
            
            logger.info(f"✅ SYNC SENSOR ATTACH completed for {sensor_eui}")
            logger.info(f"   Successful attachments: {success_count}/{len(self.connected_base_stations)} base stations")
            
            return success_count
            
        except Exception as e:
            logger.error(f"❌ Error in sync attach for {sensor_eui}: {e}")
            return 0
    
    def attach_all_sensors_sync(self) -> int:
        """Synchronous wrapper for attaching all sensors to all connected base stations"""
        try:
            logger.info(f"🔗 SYNC ATTACHING ALL SENSORS to all base stations")
            
            if not self.connected_base_stations:
                logger.warning("   ⚠️  No base stations connected")
                return 0
            
            if not self.sensor_config:
                logger.warning("   ⚠️  No sensors configured")
                return 0
            
            logger.info(f"   Total sensors to attach: {len(self.sensor_config)}")
            logger.info(f"   Target base stations: {len(self.connected_base_stations)}")
            
            # Create new event loop for sync call
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            total_attachments = 0
            try:
                async def send_all_attaches():
                    nonlocal total_attachments
                    for sensor in self.sensor_config:
                        for writer in list(self.connected_base_stations.keys()):
                            try:
                                await self.send_attach_request(writer, sensor)
                                total_attachments += 1
                                logger.info(f"   ✅ Attach request sent for {sensor['eui']} to {self.connected_base_stations[writer]}")
                                # Small delay between requests
                                await asyncio.sleep(0.1)
                            except Exception as e:
                                logger.error(f"   ❌ Failed to send attach for {sensor['eui']} to {self.connected_base_stations.get(writer, 'unknown')}: {e}")
                
                loop.run_until_complete(send_all_attaches())
            finally:
                loop.close()
            
            expected_total = len(self.sensor_config) * len(self.connected_base_stations)
            logger.info(f"✅ SYNC BULK ATTACH completed")
            logger.info(f"   Successful attachments: {total_attachments}/{expected_total} total requests")
            logger.info(f"   Sensors processed: {len(self.sensor_config)}")
            logger.info(f"   Base stations: {len(self.connected_base_stations)}")
            
            return total_attachments
            
        except Exception as e:
            logger.error(f"❌ Error in sync attach all: {e}")
            return 0

    async def send_status_requests(self) -> None:
        logger.info(f"📊 STATUS REQUEST TASK STARTED")
        logger.info(f"   Status request interval: {bssci_config.STATUS_INTERVAL} seconds")

        try:
            while True:
                await asyncio.sleep(bssci_config.STATUS_INTERVAL)
                if self.connected_base_stations:
                    logger.info(f"📊 PERIODIC STATUS REQUEST CYCLE STARTING")
                    logger.info(f"   Connected base stations: {len(self.connected_base_stations)}")
                    logger.info(f"   Base stations: {list(self.connected_base_stations.values())}")

                    for writer in list(self.connected_base_stations.keys()):
                        try:
                            bs_eui = self.connected_base_stations.get(writer, "unknown")
                            logger.info(f"   📊 Sending status request to {bs_eui}")

                            status_message = messages.build_status_request(self.opID)
                            msg_pack = encode_message(status_message)
                            full_message = IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack

                            writer.write(full_message)
                            await writer.drain()
                            self.opID -= 1
                            
                            await asyncio.sleep(0.1)
                            
                            logger.info(f"   📊 Sending VM status request to {bs_eui}")
                            op_id = self.opID
                            self.opID -= 1
                            
                            self.pending_vm_operations[op_id] = {
                                "type": "vm_status",
                                "bs_eui": bs_eui,
                                "timestamp": asyncio.get_event_loop().time()
                            }
                            
                            vm_status_msg = encode_message(messages.build_vm_status_request(op_id))
                            writer.write(IDENTIFIER + len(vm_status_msg).to_bytes(4, byteorder="little") + vm_status_msg)
                            await writer.drain()

                        except Exception as e:
                            logger.error(f"   ❌ Failed to send status to {bs_eui}: {e}")

                    logger.info(f"📊 STATUS REQUEST CYCLE COMPLETED (incl. VM status)")
                else:
                    logger.debug(f"📊 No base stations connected - skipping status requests")

        except Exception as e:
            logger.error(f"❌ STATUS REQUEST TASK FAILED: {e}")
            raise

    async def handle_client(
        self, reader: asyncio.streams.StreamReader, writer: asyncio.streams.StreamWriter
    ) -> None:
        addr = writer.get_extra_info("peername")
        ssl_obj = writer.get_extra_info("ssl_object")

        try:
            logger.info(f"🔗 New BSSCI connection attempt from {addr}")

            if ssl_obj:
                cert = ssl_obj.getpeercert()
                if cert:
                    subject = cert.get('subject', [])
                    cn = None
                    for field in subject:
                        for name, value in field:
                            if name == 'commonName':
                                cn = value
                                break
                    logger.info(f"   ✓ SSL handshake successful - Client certificate CN: {cn}")
                else:
                    logger.warning(f"   ⚠️  SSL handshake completed but no client certificate provided")
            else:
                logger.error(f"   ❌ No SSL object found - connection may not be encrypted")

        except Exception as e:
            logger.error(f"   ❌ SSL connection error from {addr}: {e}")
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass
            return

        connection_start_time = asyncio.get_event_loop().time()
        messages_processed = 0

        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                self.traffic_metrics['bytes_in'] += len(data)
                # try:
                for message in decode_messages(data):
                    msg_type = message.get("command", "")
                    messages_processed += 1

                    logger.info(f"📨 BSSCI message #{messages_processed} received from {addr}")
                    logger.info(f"   Message type: {msg_type}")
                    logger.debug(f"   Full message: {message}")

                    if msg_type == "con":
                        logger.info(f"📨 BSSCI CONNECTION REQUEST received from {addr}")
                        logger.info(f"   Operation ID: {message.get('opId', 'unknown')}")
                        logger.info(f"   Base Station UUID: {message.get('snBsUuid', 'unknown')}")

                        msg = encode_message(
                            messages.build_connection_response(
                                message.get("opId", ""), message.get("snBsUuid", "")
                            )
                        )
                        writer.write(
                            IDENTIFIER + len(msg).to_bytes(4, byteorder="little") + msg
                        )
                        await writer.drain()
                        bs_eui = int(message["bsEui"]).to_bytes(8, byteorder="big").hex().upper()
                        self.connecting_base_stations[writer] = bs_eui
                        logger.info(f"📤 BSSCI CONNECTION RESPONSE sent to base station {bs_eui}")
                        logger.info(f"   Base station {bs_eui} is now in connecting state")

                    elif msg_type == "conCmp":
                        logger.info(f"📨 BSSCI CONNECTION COMPLETE received from {addr}")
                        
                        # Always remove from connecting first (fix for duplicate display bug)
                        bs_eui = self.connecting_base_stations.pop(writer, None)
                        
                        if bs_eui and writer not in self.connected_base_stations:
                            # Deduplicate: Remove any existing connection with the same EUI
                            old_writers = [w for w, eui in list(self.connected_base_stations.items()) if eui == bs_eui]
                            for old_writer in old_writers:
                                logger.warning(f"🔄 REPLACING duplicate connection for base station {bs_eui}")
                                logger.warning(f"   Closing old connection, keeping new connection from {addr}")
                                try:
                                    old_writer.close()
                                except Exception as e:
                                    logger.debug(f"   Could not close old writer: {e}")
                                self.connected_base_stations.pop(old_writer, None)
                                # Also remove from connecting if present there
                                self.connecting_base_stations.pop(old_writer, None)
                            
                            self.connected_base_stations[writer] = bs_eui
                            connection_time = asyncio.get_event_loop().time() - connection_start_time

                            logger.info(f"✅ BSSCI CONNECTION ESTABLISHED with base station {bs_eui}")
                            logger.info("   =====================================")
                            logger.info(f"   Base Station EUI: {bs_eui}")
                            logger.info(f"   Connection established at: {self._get_local_time()}")
                            logger.info(f"   Connection setup duration: {connection_time:.2f} seconds")
                            logger.info(f"   Client address: {addr}")
                            logger.info(f"   Total connected base stations: {len(self.connected_base_stations)}")
                            logger.info(f"   All connected stations: {list(self.connected_base_stations.values())}")

                            logger.info(f"🔗 INITIATING SENSOR ATTACHMENT PROCESS")
                            logger.info(f"   Total sensors to attach: {len(self.sensor_config)}")
                            if self.sensor_config:
                                logger.info(f"   Sensors to be attached:")
                                for i, sensor in enumerate(self.sensor_config, 1):
                                    logger.info(f"     {i:2d}. EUI: {sensor['eui']}, Short Addr: {sensor['shortAddr']}")
                            else:
                                logger.warning(f"   ⚠️  No sensors configured for attachment")
                            logger.info("   =====================================")

                            # Start attachment process
                            await self.attach_file(writer)

                            # Always ensure status request task is running
                            if not hasattr(self, '_status_task_running') or not self._status_task_running:
                                logger.info(f"📊 Starting periodic status request task for all base stations")
                                self._status_task_running = True
                                asyncio.create_task(self.send_status_requests())
                            else:
                                logger.info(f"📊 Status request task already running, will include this base station")
                        else:
                            logger.warning(f"⚠️  Received connection complete from unknown or already connected base station")

                    elif msg_type == "ping":
                        logger.debug(f"Ping request received from {addr}")
                        msg_pack = encode_message(
                            messages.build_ping_response(message.get("opId", ""))
                        )
                        writer.write(
                            IDENTIFIER
                            + len(msg_pack).to_bytes(4, byteorder="little")
                            + msg_pack
                        )
                        await writer.drain()

                    elif msg_type == "pingCmp":
                        logger.debug(f"Ping complete received from {addr}")

                    elif msg_type == "statusRsp":
                        bs_eui = self.connected_base_stations[writer]
                        op_id = message.get("opId", "unknown")

                        logger.info(f"📊 BASE STATION STATUS RESPONSE received from {bs_eui}")
                        logger.info(f"   Operation ID: {op_id}")
                        logger.info(f"   Status Code: {message['code']}")
                        logger.info(f"   Memory Load: {message['memLoad']:.1%}")
                        logger.info(f"   CPU Load: {message['cpuLoad']:.1%}")
                        logger.info(f"   Duty Cycle: {message['dutyCycle']:.1%}")

                        # Parse uptime to human readable format
                        uptime_seconds = message['uptime']
                        uptime_hours = uptime_seconds // 3600
                        uptime_minutes = (uptime_seconds % 3600) // 60
                        uptime_secs = uptime_seconds % 60
                        logger.info(f"   Uptime: {uptime_hours:02d}:{uptime_minutes:02d}:{uptime_secs:02d} ({uptime_seconds}s)")

                        # Parse timestamp
                        try:
                            bs_time = datetime.fromtimestamp(message['time'] / 1_000_000_000)
                            logger.info(f"   Base Station Time: {bs_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
                        except:
                            logger.info(f"   Base Station Time: {message['time']} (raw)")

                        data_dict = {
                            "code": message["code"],
                            "memLoad": message["memLoad"],
                            "cpuLoad": message["cpuLoad"],
                            "dutyCycle": message["dutyCycle"],
                            "time": message["time"],
                            "uptime": message["uptime"],
                        }
                        
                        cpu_load = message["cpuLoad"]
                        mem_load = message["memLoad"]
                        duty_cycle = message["dutyCycle"]
                        temp = message.get("temp")
                        
                        cpu_pct = cpu_load if cpu_load > 1 else cpu_load * 100
                        mem_pct = mem_load if mem_load > 1 else mem_load * 100
                        duty_pct = duty_cycle * 100
                        
                        health_data = {
                            "cpu": cpu_pct,
                            "memory": mem_pct,
                            "duty_cycle": duty_pct,
                            "uptime": message["uptime"],
                            "last_update": datetime.now(timezone.utc).isoformat()
                        }
                        
                        if temp is not None:
                            health_data["temperature"] = temp
                            logger.info(f"   Temperature: {temp:.1f}°C")
                        
                        self.base_station_health[bs_eui.lower()] = health_data

                        mqtt_topic = f"bs/{bs_eui.upper()}"
                        payload = json.dumps(data_dict)

                        logger.info(f"📤 MQTT PUBLICATION - BASE STATION STATUS")
                        logger.info(f"   Topic: {bssci_config.BASE_TOPIC.rstrip('/')}/{mqtt_topic}")
                        logger.info(f"   Base Station EUI: {bs_eui}")
                        logger.info(f"   Payload size: {len(payload)} bytes")
                        logger.info(f"   Status data: Code={data_dict['code']}, CPU={data_dict['cpuLoad']:.1%}, Memory={data_dict['memLoad']:.1%}")
                        logger.info(f"   Queue size before add: {self.mqtt_out_queue.qsize()}")

                        try:
                            await self.mqtt_out_queue.put(
                                {
                                    "topic": mqtt_topic,
                                    "payload": payload,
                                }
                            )
                            logger.info(f"✅ Base station status queued for MQTT publication")
                            logger.info(f"   Queue size after add: {self.mqtt_out_queue.qsize()}")
                        except Exception as mqtt_err:
                            logger.error(f"❌ Failed to queue MQTT message: {mqtt_err}")
                        msg_pack = encode_message(
                            messages.build_status_complete(message.get("opId", ""))
                        )
                        writer.write(
                            IDENTIFIER
                            + len(msg_pack).to_bytes(4, byteorder="little")
                            + msg_pack
                        )
                        await writer.drain()
                        logger.debug(f"📤 STATUS COMPLETE sent for opID {op_id}")

                    elif msg_type == "attPrpRsp":
                        # Handle attach response according to BSSCI specification
                        # Per spec: attPrpRsp only contains command and opId fields
                        op_id = message.get("opId", "unknown")
                        bs_eui = self.connected_base_stations.get(writer, "unknown")

                        logger.info(f"📨 BSSCI ATTACH RESPONSE received from base station {bs_eui}")
                        logger.info("   =====================================")
                        logger.info(f"   Operation ID: {op_id}")
                        logger.info(f"   Raw message: {message}")
                        logger.info(f"   Note: Per BSSCI spec, attach response contains only command and opId")

                        # Try to correlate with pending attach request
                        pending_request = self.pending_attach_requests.get(op_id)
                        if pending_request:
                            sensor_eui = pending_request['sensor_eui']
                            sensor_config = pending_request['sensor_config']
                            request_time = pending_request['timestamp']
                            response_time = asyncio.get_event_loop().time()
                            processing_duration = response_time - request_time

                            logger.info(f"✅ ATTACH RESPONSE CORRELATED with pending request")
                            logger.info(f"   Sensor EUI: {sensor_eui}")
                            logger.info(f"   Base station: {bs_eui}")
                            logger.info(f"   Processing duration: {processing_duration:.3f} seconds")
                            logger.info(f"   Sensor Configuration:")
                            logger.info(f"     EUI: {sensor_config['eui']}")
                            logger.info(f"     Network Key: {sensor_config['nwKey'][:8]}...{sensor_config['nwKey'][-8:]}")
                            logger.info(f"     Short Address: {sensor_config['shortAddr']}")
                            logger.info(f"     Bidirectional: {sensor_config['bidi']}")

                            # According to BSSCI specification, receiving attach response indicates success
                            # Store successful registration - support multiple base stations
                            eui_key = sensor_eui.upper()
                            if eui_key not in self.registered_sensors:
                                self.registered_sensors[eui_key] = {
                                    'status': 'registered',
                                    'base_stations': [],
                                    'timestamp': response_time,
                                    'registration_time': self._get_local_time(),
                                    'registrations': []
                                }

                            # Add this base station if not already registered
                            if bs_eui not in self.registered_sensors[eui_key]['base_stations']:
                                self.registered_sensors[eui_key]['base_stations'].append(bs_eui)
                                self.registered_sensors[eui_key]['registrations'].append({
                                    'base_station': bs_eui,
                                    'op_id': op_id,
                                    'processing_duration': processing_duration,
                                    'registration_time': self._get_local_time()
                                })
                                self.registered_sensors[eui_key]['timestamp'] = response_time

                            logger.info(f"✅ SENSOR REGISTRATION SUCCESSFUL")
                            logger.info(f"   Sensor {sensor_eui} is now REGISTERED to base station {bs_eui}")
                            logger.info(f"   Registration completed at: {self._get_local_time()}")
                            logger.info(f"   Total base stations for this sensor: {len(self.registered_sensors[eui_key]['base_stations'])}")
                            logger.info(f"   All base stations for sensor: {self.registered_sensors[eui_key]['base_stations']}")
                            logger.info(f"   Total registered sensors: {len([k for k in self.registered_sensors.keys() if not k.endswith('_failure')])}")

                            # Remove from pending requests
                            del self.pending_attach_requests[op_id]

                        else:
                            logger.warning(f"⚠️  ATTACH RESPONSE for unknown operation ID")
                            logger.warning(f"   Operation ID {op_id} not found in pending requests")
                            logger.warning(f"   Available pending requests: {list(self.pending_attach_requests.keys())}")
                            logger.warning(f"   This could indicate:")
                            logger.warning(f"     - Response arrived after timeout")
                            logger.warning(f"     - Duplicate response")
                            logger.warning(f"     - Base station sent unsolicited response")

                            # Try to find a matching pending request by checking recent requests
                            # This is a fallback for when op_id correlation fails
                            recent_requests = [(k, v) for k, v in self.pending_attach_requests.items()]
                            if recent_requests:
                                # Use the most recent request as fallback
                                fallback_op_id, fallback_request = recent_requests[-1]
                                sensor_eui = fallback_request['sensor_eui']

                                logger.warning(f"   🔄 FALLBACK: Using most recent pending request")
                                logger.warning(f"   Fallback OP ID: {fallback_op_id}")
                                logger.warning(f"   Fallback Sensor EUI: {sensor_eui}")

                                # Store successful registration with fallback data
                                eui_key = sensor_eui.upper()
                                if eui_key not in self.registered_sensors:
                                    self.registered_sensors[eui_key] = {
                                        'status': 'registered',
                                        'base_stations': [],
                                        'timestamp': asyncio.get_event_loop().time(),
                                        'registration_time': self._get_local_time(),
                                        'registrations': []
                                    }

                                # Add this base station if not already registered
                                if bs_eui not in self.registered_sensors[eui_key]['base_stations']:
                                    self.registered_sensors[eui_key]['base_stations'].append(bs_eui)
                                    self.registered_sensors[eui_key]['registrations'].append({
                                        'base_station': bs_eui,
                                        'op_id': op_id,
                                        'registration_time': self._get_local_time(),
                                        'fallback_used': True
                                    })
                                    self.registered_sensors[eui_key]['timestamp'] = asyncio.get_event_loop().time()

                                logger.warning(f"   ✅ FALLBACK REGISTRATION: Sensor {sensor_eui} registered to {bs_eui}")

                                # Remove the fallback request
                                del self.pending_attach_requests[fallback_op_id]

                        logger.info(f"   Response received at: {self._get_local_time()}")
                        logger.info("   =====================================")

                        msg_pack = encode_message(
                            messages.build_attach_complete(message.get("opId", ""))
                        )
                        writer.write(
                            IDENTIFIER
                            + len(msg_pack).to_bytes(4, byteorder="little")
                            + msg_pack
                        )
                        await writer.drain()
                        logger.debug(f"📤 BSSCI ATTACH COMPLETE sent for opID {op_id}")

                    elif msg_type == "detPrpRsp":
                        # Handle detach response according to BSSCI specification
                        op_id = message.get("opId", "unknown")
                        bs_eui = self.connected_base_stations.get(writer, "unknown")

                        logger.info(f"📨 BSSCI DETACH RESPONSE received from base station {bs_eui}")
                        logger.info("   =====================================")
                        logger.info(f"   Operation ID: {op_id}")
                        logger.info(f"   Raw message: {message}")
                        logger.info(f"   Note: Per BSSCI spec, detach response contains only command and opId")

                        # Send detach complete response
                        msg_pack = encode_message(
                            messages.build_detach_complete(message.get("opId", ""))
                        )
                        writer.write(
                            IDENTIFIER
                            + len(msg_pack).to_bytes(4, byteorder="little")
                            + msg_pack
                        )
                        await writer.drain()
                        logger.info(f"📤 BSSCI DETACH COMPLETE sent for opID {op_id}")
                        logger.info(f"✅ Detach operation completed successfully")
                        logger.info("   =====================================")

                    elif msg_type == "att":
                        # Over-the-air attach initiated by base station
                        # Per BSSCI spec 5.6: Base station sends att when sensor attaches OTA
                        op_id = message.get("opId", 0)
                        ep_eui = int(message["epEui"]).to_bytes(8, byteorder="big").hex().upper()
                        bs_eui = self.connected_base_stations.get(writer, "unknown")
                        
                        logger.info(f"📡 OTA ATTACH REQUEST from base station {bs_eui}")
                        logger.info(f"   Sensor EUI: {ep_eui}")
                        logger.info(f"   Operation ID: {op_id}")
                        logger.info(f"   Attach Counter: {message.get('attachCnt', 'N/A')}")
                        logger.info(f"   SNR: {message.get('snr', 'N/A')} dB")
                        logger.info(f"   RSSI: {message.get('rssi', 'N/A')} dBm")
                        
                        # Look up sensor config to get network key
                        sensor_config = None
                        for sensor in self.sensor_config:
                            if sensor['eui'].upper() == ep_eui:
                                sensor_config = sensor
                                break
                        
                        if sensor_config:
                            # Send attach response with network key
                            nwk_key = list(bytes.fromhex(sensor_config['nwKey']))
                            sh_addr = int.from_bytes(bytes.fromhex(sensor_config['shortAddr']), "big") if sensor_config.get('shortAddr') else None
                            
                            msg_pack = encode_message(messages.build_attach_response(op_id, nwk_key, sh_addr))
                            writer.write(IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack)
                            await writer.drain()
                            logger.info(f"✅ OTA ATTACH RESPONSE sent for sensor {ep_eui}")
                        else:
                            # Unknown sensor - still need to respond
                            logger.warning(f"⚠️  Unknown sensor {ep_eui} trying to attach OTA")
                            # Send empty response to prevent timeout
                            msg_pack = encode_message(messages.build_attach_response(op_id, [0]*16, 0))
                            writer.write(IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack)
                            await writer.drain()
                    
                    elif msg_type == "attCmp":
                        # Attach complete from base station
                        op_id = message.get("opId", 0)
                        logger.info(f"✅ OTA ATTACH COMPLETE received, opId: {op_id}")
                    
                    elif msg_type == "det":
                        # Over-the-air detach initiated by base station
                        # Per BSSCI spec 5.7: Base station sends det when sensor detaches OTA
                        op_id = message.get("opId", 0)
                        ep_eui = int(message["epEui"]).to_bytes(8, byteorder="big").hex().upper()
                        bs_eui = self.connected_base_stations.get(writer, "unknown")
                        
                        logger.info(f"📡 OTA DETACH REQUEST from base station {bs_eui}")
                        logger.info(f"   Sensor EUI: {ep_eui}")
                        logger.info(f"   Operation ID: {op_id}")
                        
                        # Send detach response
                        msg_pack = encode_message(messages.build_detach_response(op_id))
                        writer.write(IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack)
                        await writer.drain()
                        logger.info(f"✅ OTA DETACH RESPONSE sent for sensor {ep_eui}")
                    
                    elif msg_type == "detCmp":
                        # Detach complete from base station
                        op_id = message.get("opId", 0)
                        logger.info(f"✅ OTA DETACH COMPLETE received, opId: {op_id}")
                    
                    elif msg_type == "dlDataRes":
                        # DL data result from base station - queued DL data was sent or discarded
                        # Per BSSCI spec 5.14
                        op_id = message.get("opId", 0)
                        ep_eui = int(message["epEui"]).to_bytes(8, byteorder="big").hex().upper()
                        result = message.get("result", "unknown")
                        que_id = message.get("queId", 0)
                        bs_eui = self.connected_base_stations.get(writer, "unknown")
                        
                        logger.info(f"📡 DL DATA RESULT from base station {bs_eui}")
                        logger.info(f"   Sensor EUI: {ep_eui}")
                        logger.info(f"   Queue ID: {que_id}")
                        logger.info(f"   Result: {result}")
                        
                        # Send DL data result response
                        msg_pack = encode_message(messages.build_dl_data_result_response(op_id))
                        writer.write(IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack)
                        await writer.drain()
                        logger.info(f"✅ DL DATA RESULT RESPONSE sent")
                    
                    elif msg_type == "dlDataResCmp":
                        op_id = message.get("opId", 0)
                        logger.info(f"✅ DL DATA RESULT COMPLETE received, opId: {op_id}")
                    
                    elif msg_type == "dlRxStat":
                        # DL RX status from base station - received after DL RX status from endpoint
                        # Per BSSCI spec 5.15
                        op_id = message.get("opId", 0)
                        ep_eui = int(message["epEui"]).to_bytes(8, byteorder="big").hex().upper()
                        dl_rx_snr = message.get("dlRxSnr", 0)
                        dl_rx_rssi = message.get("dlRxRssi", 0)
                        bs_eui = self.connected_base_stations.get(writer, "unknown")
                        
                        logger.info(f"📡 DL RX STATUS from base station {bs_eui}")
                        logger.info(f"   Sensor EUI: {ep_eui}")
                        logger.info(f"   DL RX SNR: {dl_rx_snr} dB")
                        logger.info(f"   DL RX RSSI: {dl_rx_rssi} dBm")
                        
                        # Send DL RX status response
                        msg_pack = encode_message(messages.build_dl_rx_status_response(op_id))
                        writer.write(IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack)
                        await writer.drain()
                        logger.info(f"✅ DL RX STATUS RESPONSE sent")
                    
                    elif msg_type == "dlRxStatCmp":
                        op_id = message.get("opId", 0)
                        logger.info(f"✅ DL RX STATUS COMPLETE received, opId: {op_id}")

                    elif msg_type == "ulData":
                        eui = int(message["epEui"]).to_bytes(8, byteorder="big").hex()
                        bs_eui = self.connected_base_stations[writer]
                        op_id = message.get("opId", "unknown")
                        rx_time = message["rxTime"]
                        snr = message["snr"]
                        packet_cnt = message["packetCnt"]

                        # Create a unique key for deduplication
                        message_key = f"{eui}_{packet_cnt}"

                        self.deduplication_stats['total_messages'] += 1
                        self.traffic_metrics['messages_in'] += 1
                        
                        # Track active sensor for hourly stats
                        self.active_sensors_hourly.add(eui)
                        
                        # Update network topology (track ALL receiving base stations, before dedup)
                        eui_upper = eui.upper()
                        rssi = message.get('rssi', 0)
                        current_time = asyncio.get_event_loop().time()
                        
                        if eui_upper not in self.sensor_topology:
                            self.sensor_topology[eui_upper] = {
                                'primary_bs': bs_eui,
                                'receiving_bases': {}
                            }
                        
                        # Update or add this base station as a receiver
                        if bs_eui not in self.sensor_topology[eui_upper]['receiving_bases']:
                            self.sensor_topology[eui_upper]['receiving_bases'][bs_eui] = {
                                'snr': snr,
                                'rssi': rssi,
                                'last_seen': current_time,
                                'count': 1
                            }
                        else:
                            rb = self.sensor_topology[eui_upper]['receiving_bases'][bs_eui]
                            rb['snr'] = snr  # Update with latest
                            rb['rssi'] = rssi
                            rb['last_seen'] = current_time
                            rb['count'] += 1

                        # Check if message is a duplicate and if the new one has better SNR
                        is_duplicate = message_key in self.deduplication_buffer
                        if is_duplicate:
                            existing_message = self.deduplication_buffer[message_key]
                            if snr > existing_message['snr']:
                                logger.info(f"🔄 DEDUPLICATION: Better signal found for {eui}")
                                logger.info(f"   Message counter: {packet_cnt}")
                                logger.info(f"   Previous SNR: {existing_message['snr']:.2f} dB (via {existing_message['bs_eui']})")
                                logger.info(f"   New SNR: {snr:.2f} dB (via {bs_eui})")
                                logger.info(f"   Updating preferred path: {existing_message['bs_eui']} → {bs_eui}")

                                # Update preferred downlink path in sensor config
                                self.update_preferred_downlink_path(eui, bs_eui, snr)
                                
                                # Update topology primary BS
                                if eui_upper in self.sensor_topology:
                                    self.sensor_topology[eui_upper]['primary_bs'] = bs_eui

                                self.deduplication_buffer[message_key] = {
                                    'message': message,
                                    'timestamp': asyncio.get_event_loop().time(),
                                    'snr': snr,
                                    'bs_eui': bs_eui
                                }
                            else:
                                logger.debug(f"   🔽 DEDUPLICATION: Filtered duplicate message for {eui} with lower SNR ({snr:.2f} dB <= {existing_message['snr']:.2f} dB)")
                                self.deduplication_stats['duplicate_messages'] += 1
                                self.traffic_metrics['messages_dropped'] += 1

                                # Send acknowledgment but don't queue for MQTT
                                msg_pack = encode_message(
                                    messages.build_ul_response(message.get("opId", ""))
                                )
                                writer.write(
                                    IDENTIFIER
                                    + len(msg_pack).to_bytes(4, byteorder="little")
                                    + msg_pack
                                )
                                await writer.drain()
                                continue  # Skip processing this duplicate

                        else:
                            logger.debug(f"📨 DEDUPLICATION: New message received for {eui}")
                            logger.debug(f"   Message counter: {packet_cnt}")
                            logger.debug(f"   SNR: {snr:.2f} dB (via {bs_eui})")

                            # Update preferred downlink path for new messages too
                            self.update_preferred_downlink_path(eui, bs_eui, snr)
                            
                            # Update topology primary BS for new messages
                            if eui_upper in self.sensor_topology:
                                self.sensor_topology[eui_upper]['primary_bs'] = bs_eui

                            self.deduplication_buffer[message_key] = {
                                'message': message,
                                'timestamp': asyncio.get_event_loop().time(),
                                'snr': snr,
                                'bs_eui': bs_eui
                            }
                            
                            # Track packet statistics for packet loss detection (only for new messages, not duplicates)
                            eui_upper = eui.upper()
                            current_timestamp = datetime.now(timezone.utc).timestamp()
                            
                            # Extract transmission details from message
                            airtime_ms = message.get('airtime', 0)  # in microseconds usually
                            spreading_factor = message.get('sf', message.get('spreadingFactor', 7))
                            frequency_hz = message.get('freq', message.get('frequency', 0))
                            data_rate = message.get('dataRate', f'SF{spreading_factor}BW125')
                            
                            if eui_upper not in self.sensor_packet_stats:
                                self.sensor_packet_stats[eui_upper] = {
                                    'last_packet_cnt': packet_cnt,
                                    'packets_received': 1,
                                    'packets_lost': 0,
                                    'snr_sum': snr,
                                    'snr_count': 1,
                                    'rssi_sum': message.get('rssi', 0),
                                    'rssi_count': 1,
                                    'first_seen': current_timestamp,
                                    'last_seen': current_timestamp,
                                    'last_airtime_ms': airtime_ms / 1000 if airtime_ms > 1000 else airtime_ms,
                                    'total_airtime_ms': airtime_ms / 1000 if airtime_ms > 1000 else airtime_ms,
                                    'spreading_factor': spreading_factor,
                                    'frequency_mhz': frequency_hz / 1000000 if frequency_hz > 1000000 else frequency_hz,
                                    'data_rate': data_rate,
                                    'frame_counter': packet_cnt,
                                    'min_snr': snr,
                                    'max_snr': snr,
                                    'min_rssi': message.get('rssi', 0),
                                    'max_rssi': message.get('rssi', 0),
                                    'snr_history': [],
                                    'rssi_history': []
                                }
                            else:
                                stats = self.sensor_packet_stats[eui_upper]
                                last_cnt = stats['last_packet_cnt']
                                # Packet counter wraps at 65536 (16-bit)
                                expected_next = (last_cnt + 1) % 65536
                                if packet_cnt != expected_next:
                                    # Calculate lost packets (handle wrap-around)
                                    if packet_cnt > last_cnt:
                                        lost = packet_cnt - last_cnt - 1
                                    else:
                                        lost = (65536 - last_cnt - 1) + packet_cnt
                                    if lost > 0 and lost < 1000:  # Sanity check
                                        stats['packets_lost'] += lost
                                stats['last_packet_cnt'] = packet_cnt
                                stats['packets_received'] += 1
                                stats['snr_sum'] += snr
                                stats['snr_count'] += 1
                                stats['rssi_sum'] += message.get('rssi', 0)
                                stats['rssi_count'] += 1
                                
                                # Update extended stats
                                stats['last_seen'] = current_timestamp
                                airtime_val = airtime_ms / 1000 if airtime_ms > 1000 else airtime_ms
                                stats['last_airtime_ms'] = airtime_val
                                stats['total_airtime_ms'] = stats.get('total_airtime_ms', 0) + airtime_val
                                stats['spreading_factor'] = spreading_factor
                                stats['frequency_mhz'] = frequency_hz / 1000000 if frequency_hz > 1000000 else frequency_hz
                                stats['data_rate'] = data_rate
                                stats['frame_counter'] = packet_cnt
                                
                                # Track min/max values
                                stats['min_snr'] = min(stats.get('min_snr', snr), snr)
                                stats['max_snr'] = max(stats.get('max_snr', snr), snr)
                                rssi = message.get('rssi', 0)
                                stats['min_rssi'] = min(stats.get('min_rssi', rssi), rssi)
                                stats['max_rssi'] = max(stats.get('max_rssi', rssi), rssi)
                                
                                # Keep last 100 values for history charts
                                if 'snr_history' not in stats:
                                    stats['snr_history'] = []
                                if 'rssi_history' not in stats:
                                    stats['rssi_history'] = []
                                stats['snr_history'].append({'ts': current_timestamp, 'val': snr})
                                stats['rssi_history'].append({'ts': current_timestamp, 'val': rssi})
                                if len(stats['snr_history']) > 100:
                                    stats['snr_history'] = stats['snr_history'][-100:]
                                if len(stats['rssi_history']) > 100:
                                    stats['rssi_history'] = stats['rssi_history'][-100:]
                            
                            # Update SNR/RSSI history (every 5 minutes)
                            current_time = datetime.now(timezone.utc).timestamp()
                            if current_time - self._last_snr_history_update >= 300:
                                self._update_snr_rssi_history(current_time)

                        # Parse received timestamp if available
                        try:
                            rx_datetime = datetime.fromtimestamp(rx_time / 1_000_000_000)
                            rx_time_str = rx_datetime.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                        except:
                            rx_time_str = str(rx_time)

                        logger.info(f"📡 UPLINK DATA BUFFERED FOR DEDUPLICATION")
                        logger.info(f"   =================================")
                        logger.info(f"   Endpoint EUI: {eui}")
                        logger.info(f"   Via Base Station: {bs_eui}")
                        logger.info(f"   Reception Time: {rx_time_str}")
                        logger.info(f"   Operation ID: {op_id}")
                        logger.info(f"   Signal Quality:")
                        logger.info(f"     SNR: {snr:.2f} dB")
                        logger.info(f"     RSSI: {message['rssi']:.2f} dBm")
                        logger.info(f"   Packet Counter: {packet_cnt}")
                        logger.info(f"   Payload:")
                        logger.info(f"     Length: {len(message['userData'])} bytes")
                        logger.info(f"     Data (hex): {' '.join(f'{b:02x}' for b in message['userData'])}")
                        logger.info(f"     Data (dec): {message['userData']}")

                        # Check if this sensor is registered
                        is_registered = eui.upper() in self.registered_sensors
                        if is_registered:
                            reg_info = self.registered_sensors[eui.upper()]
                            logger.info(f"   Registration Status: ✅ REGISTERED")
                            logger.info(f"     Registered to {len(reg_info.get('base_stations', []))} base station(s): {reg_info.get('base_stations', [])}")
                            logger.info(f"     Data received via: {bs_eui}")
                            logger.info(f"     Registration time: {reg_info.get('registration_time', 'unknown')}")
                        else:
                            logger.warning(f"   Registration Status: ⚠️  NOT REGISTERED")
                            logger.warning(f"     This sensor may not be configured in endpoints.json")

                        # Message will be published after deduplication delay
                        logger.info(f"⏳ Message queued for deduplication processing")
                        logger.info(f"   Will be published in {self.deduplication_delay} seconds if no better signal received")
                        logger.info(f"   Buffer size: {len(self.deduplication_buffer)} messages")
                        logger.info(f"   =================================")

                        msg_pack = encode_message(
                            messages.build_ul_response(message.get("opId", ""))
                        )
                        writer.write(
                            IDENTIFIER
                            + len(msg_pack).to_bytes(4, byteorder="little")
                            + msg_pack
                        )
                        await writer.drain()
                        # Update last seen timestamp for auto-detach functionality
                        self.sensor_last_seen[eui.upper()] = asyncio.get_event_loop().time()

                        # Reset warning flag if sensor becomes active again
                        if eui.upper() in self.sensor_warning_sent:
                            self.sensor_warning_sent[eui.upper()] = False

                        logger.info(f"✅ UPLINK DATA PROCESSING COMPLETE for {eui}")
                        logger.info(f"   =================================")

                    elif msg_type == "ulDataCmp":
                        pass

                    elif msg_type == "detachResp":
                        eui = message.get("eui", "unknown")
                        result = message.get("resultCode", -1)
                        status = "OK" if result == 0 else f"Fehler {result}"
                        logger.info(f"[DETACH] Sensor {eui} status: {status}")

                        # Notify via MQTT
                        if self.mqtt_out_queue:
                            detach_response_notification = {
                                "topic": f"ep/{eui.upper()}/status",
                                "payload": json.dumps({
                                    "action": "detach_response",
                                    "sensor_eui": eui,
                                    "result": status,
                                    "timestamp": asyncio.get_event_loop().time()
                                })
                            }
                            await self.mqtt_out_queue.put(detach_response_notification)

                    # Variable MAC (VM) Sub-Channel Message Handlers
                    elif msg_type == "vmActRsp":
                        op_id = message.get("opId", "unknown")
                        code = message.get("code", -1)
                        bs_eui = self.connected_base_stations.get(writer, "unknown")
                        
                        if op_id in self.pending_vm_operations:
                            pending = self.pending_vm_operations.pop(op_id)
                            eui = pending.get("eui", "unknown")
                            vm_channel = pending.get("vm_channel", 0)
                            
                            if code == 0:
                                logger.info(f"✅ VM ACTIVATE SUCCESS for sensor {eui}")
                                self.vm_active_sensors[eui.upper()] = {
                                    "active": True,
                                    "vm_channel": vm_channel,
                                    "activated_at": asyncio.get_event_loop().time(),
                                    "bs_eui": bs_eui
                                }
                            else:
                                logger.warning(f"❌ VM ACTIVATE FAILED for sensor {eui}, code: {code}")
                            
                            if self.mqtt_out_queue:
                                await self.mqtt_out_queue.put({
                                    "topic": f"ep/{eui.upper()}/vm/status",
                                    "payload": json.dumps({
                                        "action": "vm_activate_response",
                                        "eui": eui,
                                        "success": code == 0,
                                        "vm_channel": vm_channel,
                                        "timestamp": asyncio.get_event_loop().time()
                                    })
                                })
                    
                    elif msg_type == "vmDeactRsp":
                        op_id = message.get("opId", "unknown")
                        code = message.get("code", -1)
                        
                        if op_id in self.pending_vm_operations:
                            pending = self.pending_vm_operations.pop(op_id)
                            eui = pending.get("eui", "unknown")
                            
                            if code == 0:
                                logger.info(f"✅ VM DEACTIVATE SUCCESS for sensor {eui}")
                                if eui.upper() in self.vm_active_sensors:
                                    del self.vm_active_sensors[eui.upper()]
                            else:
                                logger.warning(f"❌ VM DEACTIVATE FAILED for sensor {eui}, code: {code}")
                            
                            if self.mqtt_out_queue:
                                await self.mqtt_out_queue.put({
                                    "topic": f"ep/{eui.upper()}/vm/status",
                                    "payload": json.dumps({
                                        "action": "vm_deactivate_response",
                                        "eui": eui,
                                        "success": code == 0,
                                        "timestamp": asyncio.get_event_loop().time()
                                    })
                                })
                    
                    elif msg_type == "vm.statusRsp":
                        op_id = message.get("opId", "unknown")
                        mac_types = message.get("macTypes", [])
                        
                        if op_id in self.pending_vm_operations:
                            pending = self.pending_vm_operations.pop(op_id)
                            bs_eui = pending.get("bs_eui", self.connected_base_stations.get(writer, "unknown"))
                            
                            logger.info(f"═══════════════════════════════════════════════════════════")
                            logger.info(f"📊 VM STATUS RESPONSE from base station {bs_eui}")
                            logger.info(f"   Operation ID: {op_id}")
                            if mac_types:
                                logger.info(f"   Active MAC Types: {mac_types}")
                                mac_str = ", ".join([str(m) for m in mac_types])
                                self.add_vm_log(f"BS {bs_eui}: Active MAC types: [{mac_str}]", "response")
                                for mac_type in mac_types:
                                    logger.info(f"      - MAC Type {mac_type}")
                            else:
                                logger.info(f"   No MAC Types active (VM reception not enabled)")
                                self.add_vm_log(f"BS {bs_eui}: No MAC types active", "response")
                            logger.info(f"═══════════════════════════════════════════════════════════")
                            
                            if self.mqtt_out_queue:
                                await self.mqtt_out_queue.put({
                                    "topic": f"bs/{bs_eui}/vm/status",
                                    "payload": json.dumps({
                                        "action": "vm_status_response",
                                        "bs_eui": bs_eui,
                                        "mac_types": mac_types,
                                        "timestamp": asyncio.get_event_loop().time()
                                    })
                                })
                    
                    elif msg_type == "vm.statusCmp":
                        op_id = message.get("opId", "unknown")
                        logger.info(f"📊 VM STATUS COMPLETE - Operation {op_id}")
                    
                    elif msg_type == "vmUlData":
                        eui = int(message["epEui"]).to_bytes(8, byteorder="big").hex()
                        bs_eui = self.connected_base_stations.get(writer, "unknown")
                        op_id = message.get("opId", 0)
                        port = message.get("port", 1)
                        data = message.get("data", [])
                        snr = message.get("snr", 0)
                        rssi = message.get("rssi", 0)
                        
                        logger.info(f"📨 VM UPLINK DATA received from sensor {eui}")
                        logger.info(f"   Port: {port}, Data length: {len(data)} bytes")
                        logger.info(f"   Via base station: {bs_eui}")
                        logger.info(f"   SNR: {snr}, RSSI: {rssi}")
                        
                        # Parse OMS meter ID from WMBUS payload (if applicable)
                        data_hex = bytes(data).hex() if isinstance(data, list) else data
                        meter_id = self._extract_oms_meter_id(data if isinstance(data, list) else bytes.fromhex(data))
                        
                        if meter_id:
                            logger.info(f"   OMS Meter ID: {meter_id}")
                            current_time = asyncio.get_event_loop().time()
                            
                            # Track OMS meter
                            if meter_id in self.oms_meters:
                                self.oms_meters[meter_id]['message_count'] += 1
                                self.oms_meters[meter_id]['last_data'] = data_hex
                                self.oms_meters[meter_id]['timestamp'] = current_time
                                self.oms_meters[meter_id]['snr'] = snr
                                self.oms_meters[meter_id]['rssi'] = rssi
                                self.oms_meters[meter_id]['bs_eui'] = bs_eui
                            else:
                                self.oms_meters[meter_id] = {
                                    'meter_id': meter_id,
                                    'eui': eui.upper(),
                                    'snr': snr,
                                    'rssi': rssi,
                                    'last_data': data_hex,
                                    'timestamp': current_time,
                                    'bs_eui': bs_eui,
                                    'message_count': 1
                                }
                        
                        # Send acknowledgment
                        msg_pack = encode_message(messages.build_vm_ul_data_response(op_id))
                        writer.write(IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack)
                        await writer.drain()
                        
                        # Update last seen
                        self.sensor_last_seen[eui.upper()] = asyncio.get_event_loop().time()
                        
                        # Increment VM message counter
                        self.traffic_metrics['vm_messages'] += 1
                        
                        # Publish to MQTT
                        if self.mqtt_out_queue:
                            await self.mqtt_out_queue.put({
                                "topic": f"ep/{eui.upper()}/vm/ul",
                                "payload": json.dumps({
                                    "bs_eui": bs_eui,
                                    "port": port,
                                    "data": data_hex,
                                    "meter_id": meter_id,
                                    "snr": snr,
                                    "rssi": rssi,
                                    "timestamp": asyncio.get_event_loop().time()
                                })
                            })
                    
                    elif msg_type == "vmDlDataRsp":
                        op_id = message.get("opId", "unknown")
                        code = message.get("code", -1)
                        
                        if op_id in self.pending_vm_operations:
                            pending = self.pending_vm_operations.pop(op_id)
                            eui = pending.get("eui", "unknown")
                            
                            if code == 0:
                                logger.info(f"✅ VM DOWNLINK DATA SENT successfully to sensor {eui}")
                            else:
                                logger.warning(f"❌ VM DOWNLINK DATA FAILED for sensor {eui}, code: {code}")
                            
                            if self.mqtt_out_queue:
                                await self.mqtt_out_queue.put({
                                    "topic": f"ep/{eui.upper()}/vm/dl/response",
                                    "payload": json.dumps({
                                        "action": "vm_dl_response",
                                        "eui": eui,
                                        "success": code == 0,
                                        "timestamp": asyncio.get_event_loop().time()
                                    })
                                })

                    elif msg_type == "error":
                        # Error response from base station - must acknowledge to prevent timeout
                        # Per BSSCI spec: Error can be sent instead of normal response
                        op_id = message.get("opId", 0)
                        code = message.get("code", -1)
                        error_msg = message.get("message", "Unknown error")
                        bs_eui = self.connected_base_stations.get(writer, "unknown")
                        
                        logger.warning(f"⚠️  ERROR RESPONSE from base station {bs_eui}")
                        logger.warning(f"   Operation ID: {op_id}")
                        logger.warning(f"   Error Code: {code}")
                        logger.warning(f"   Error Message: {error_msg}")
                        
                        # Determine what operation this error is for and send appropriate complete
                        # Negative opIds are from our requests (Service Center initiated)
                        if op_id < 0:
                            # This was our request - check pending operations
                            if op_id in self.pending_vm_operations:
                                pending = self.pending_vm_operations.pop(op_id)
                                op_type = pending.get("operation", "unknown")
                                logger.warning(f"   VM operation '{op_type}' failed")
                                self.add_vm_log(f"BS {bs_eui}: Error - {error_msg} (code {code})", "error")
                                
                                # Send appropriate complete message based on operation type
                                if op_type == "status":
                                    msg_pack = encode_message({"command": "vm.statusCmp", "opId": op_id})
                                elif op_type == "activate":
                                    msg_pack = encode_message({"command": "vm.activateCmp", "opId": op_id})
                                elif op_type == "deactivate":
                                    msg_pack = encode_message({"command": "vm.deactivateCmp", "opId": op_id})
                                else:
                                    # Generic error acknowledgment - try statusCmp as fallback
                                    msg_pack = encode_message({"command": "vm.statusCmp", "opId": op_id})
                                
                                writer.write(IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack)
                                await writer.drain()
                                logger.info(f"✅ Error acknowledged with complete message for opId {op_id}")
                            elif op_id in self.pending_attach_requests:
                                # Attach request failed
                                pending = self.pending_attach_requests.pop(op_id)
                                sensor_eui = pending.get("sensor_eui", "unknown")
                                logger.warning(f"   Attach request for sensor {sensor_eui} failed")
                                
                                msg_pack = encode_message({"command": "attPrpCmp", "opId": op_id})
                                writer.write(IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack)
                                await writer.drain()
                                logger.info(f"✅ Attach error acknowledged with complete message for opId {op_id}")
                            else:
                                # Unknown pending operation - still need to acknowledge somehow
                                # Try to send a generic statusCmp to prevent timeout
                                logger.warning(f"   Unknown pending operation for opId {op_id}, sending statusCmp")
                                msg_pack = encode_message({"command": "statusCmp", "opId": op_id})
                                writer.write(IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack)
                                await writer.drain()
                                logger.info(f"✅ Error acknowledged with statusCmp for opId {op_id}")
                        else:
                            # Positive opId - base station initiated, we should respond
                            logger.warning(f"   Base station error for its own operation {op_id}")

                    else:
                        logger.warning(f"[WARN] Unknown message type: {msg_type} - Message: {message}")

                    # except Exception as e:
                    #    print(f"[ERROR] Fehler beim Dekodieren der Nachricht: {e}")

        except asyncio.CancelledError:
            logger.info(f"🔌 Connection from {addr} was cancelled")
        except ConnectionResetError:
            logger.warning(f"🔌 Connection from {addr} was reset by peer")
        except ssl.SSLError as e:
            logger.error(f"❌ SSL/TLS error from {addr}: {e}")
        except Exception as e:
            logger.error(f"❌ Unexpected error handling connection from {addr}: {e}")
        finally:
            connection_duration = asyncio.get_event_loop().time() - connection_start_time

            try:
                with open(self.sensor_config_file, "w") as f:
                    json.dump(self.sensor_config, f, indent=4)
                logger.debug(f"Sensor configuration saved to {self.sensor_config_file}")
            except Exception as e:
                logger.error(f"Failed to save sensor configuration: {e}")

            logger.info(f"🔌 Connection to {addr} closed")
            logger.info(f"   Connection duration: {connection_duration:.2f} seconds")
            logger.info(f"   Messages processed: {messages_processed}")

            writer.close()
            await writer.wait_closed()

            if writer in self.connected_base_stations:
                bs_eui = self.connected_base_stations.pop(writer)
                logger.info(f"❌ Base station {bs_eui} disconnected")
                logger.info(f"   Remaining connected base stations: {len(self.connected_base_stations)}")
            if writer in self.connecting_base_stations:
                self.connecting_base_stations.pop(writer)

    async def process_deduplication_buffer(self) -> None:
        """Processes the deduplication buffer, forwards best messages, and cleans up old entries."""
        logger.info(f"🧠 Starting deduplication buffer processing task with delay: {self.deduplication_delay}s")
        while True:
            await asyncio.sleep(self.deduplication_delay)
            current_time = asyncio.get_event_loop().time()

            # Find messages that have been in the buffer longer than the delay
            messages_to_publish = []
            for key, value in list(self.deduplication_buffer.items()): # Use list to allow modification during iteration
                if current_time - value['timestamp'] >= self.deduplication_delay:
                    messages_to_publish.append((key, value))
                    del self.deduplication_buffer[key] # Remove from buffer

            # Sort messages to publish by SNR (highest first)
            messages_to_publish.sort(key=lambda item: item[1]['snr'], reverse=True)

            for message_key, message_data in messages_to_publish:
                message = message_data['message']
                bs_eui = message_data['bs_eui']
                eui = int(message["epEui"]).to_bytes(8, byteorder="big").hex()
                snr = message_data['snr']
                packet_cnt = message["packetCnt"]

                data_dict = {
                    "bs_eui": bs_eui,
                    "rxTime": message["rxTime"],
                    "snr": snr,
                    "rssi": message["rssi"],
                    "cnt": packet_cnt,
                    "data": message["userData"],
                }

                mqtt_topic = f"ep/{eui.upper()}/ul"
                payload_json = json.dumps(data_dict)

                logger.info(f"📤 PUBLISHING DEDUPLICATED MESSAGE")
                logger.info("   =====================================")
                logger.info(f"   Full Topic: {bssci_config.BASE_TOPIC.rstrip('/')}/{mqtt_topic}")
                logger.info(f"   Sensor EUI: {eui}")
                logger.info(f"   Base Station: {bs_eui}")
                logger.info(f"   Payload Size: {len(payload_json)} bytes")
                logger.info(f"   Data Preview: SNR={data_dict['snr']:.1f}dB, RSSI={data_dict['rssi']:.1f}dBm, Count={data_dict['cnt']}")
                logger.info(f"   Queue size before add: {self.mqtt_out_queue.qsize()}")
                logger.debug(f"   Full Payload: {payload_json}")

                try:
                    await self.mqtt_out_queue.put(
                        {"topic": mqtt_topic, "payload": payload_json}
                    )
                    logger.info(f"✅ DEDUPLICATED MQTT message queued successfully")
                    logger.info(f"   Queue size after add: {self.mqtt_out_queue.qsize()}")

                    # Update statistics
                    self.deduplication_stats['published_messages'] += 1
                    self.traffic_metrics['messages_out'] += 1
                    self.traffic_metrics['bytes_out'] += len(payload_json)
                    total_msg = self.deduplication_stats['total_messages']
                    dup_msg = self.deduplication_stats['duplicate_messages']
                    pub_msg = self.deduplication_stats['published_messages']
                    dup_rate = (dup_msg / total_msg * 100) if total_msg > 0 else 0

                    logger.info(f"📊 DEDUPLICATION STATISTICS:")
                    logger.info(f"   Total messages received: {total_msg}")
                    logger.info(f"   Duplicate messages filtered: {dup_msg}")
                    logger.info(f"   Messages published: {pub_msg}")
                    logger.info(f"   Duplication rate: {dup_rate:.1f}%")

                except Exception as mqtt_err:
                    logger.error(f"❌ FAILED to queue deduplicated MQTT message")
                    logger.error(f"   Error: {type(mqtt_err).__name__}: {mqtt_err}")
                    logger.error(f"   Topic: {mqtt_topic}")
                    logger.error(f"   Payload: {payload_json}")
                logger.info(f"   =======================================")

            # Clean up old entries from the buffer that were not published
            oldest_allowed_time = current_time - (self.deduplication_delay * 2) # Keep entries for a bit longer to ensure they are processed
            for key, value in list(self.deduplication_buffer.items()):
                 if current_time - value['timestamp'] > oldest_allowed_time:
                     logger.warning(f"   🧹 Cleaning up old unduplicated message from buffer: {key}")
                     del self.deduplication_buffer[key]

    async def auto_detach_monitor(self) -> None:
        """Monitor sensors for auto-detach based on inactivity"""
        logger.info(f"🕐 AUTO-DETACH MONITOR STARTED")
        logger.info(f"   Auto-detach timeout: {getattr(bssci_config, 'AUTO_DETACH_TIMEOUT', 259200)} seconds ({getattr(bssci_config, 'AUTO_DETACH_TIMEOUT', 259200) / 3600:.1f} hours)")
        logger.info(f"   Warning timeout: {getattr(bssci_config, 'AUTO_DETACH_WARNING_TIMEOUT', 129600)} seconds ({getattr(bssci_config, 'AUTO_DETACH_WARNING_TIMEOUT', 129600) / 3600:.1f} hours)")
        logger.info(f"   Check interval: {getattr(bssci_config, 'AUTO_DETACH_CHECK_INTERVAL', 3600)} seconds")

        try:
            while True:
                await asyncio.sleep(getattr(bssci_config, 'AUTO_DETACH_CHECK_INTERVAL', 3600))
                current_time = asyncio.get_event_loop().time()

                auto_detach_timeout = getattr(bssci_config, 'AUTO_DETACH_TIMEOUT', 259200)
                warning_timeout = getattr(bssci_config, 'AUTO_DETACH_WARNING_TIMEOUT', 129600)

                sensors_to_detach = []
                sensors_to_warn = []

                # Check all registered sensors
                for eui_key, sensor_info in list(self.registered_sensors.items()):
                    if eui_key.endswith('_failure') or not sensor_info.get('registered', False):
                        continue

                    last_seen = self.sensor_last_seen.get(eui_key, sensor_info.get('timestamp', 0))
                    time_since_last_seen = current_time - last_seen

                    # Check for auto-detach
                    if time_since_last_seen > auto_detach_timeout:
                        sensors_to_detach.append((eui_key, time_since_last_seen))

                    # Check for warning (only if not already sent and not scheduled for detach)
                    elif (time_since_last_seen > warning_timeout and
                          not self.sensor_warning_sent.get(eui_key, False) and
                          eui_key not in [s[0] for s in sensors_to_detach]):
                        sensors_to_warn.append((eui_key, time_since_last_seen))

                # Process warnings
                for eui_key, inactive_time in sensors_to_warn:
                    await self.send_inactivity_warning(eui_key, inactive_time, warning_timeout, auto_detach_timeout)
                    self.sensor_warning_sent[eui_key] = True

                # Process auto-detaches
                for eui_key, inactive_time in sensors_to_detach:
                    await self.auto_detach_inactive_sensor(eui_key, inactive_time)

                if sensors_to_detach or sensors_to_warn:
                    logger.info(f"🕐 AUTO-DETACH MONITOR CYCLE COMPLETE")
                    logger.info(f"   Warnings sent: {len(sensors_to_warn)}")
                    logger.info(f"   Sensors auto-detached: {len(sensors_to_detach)}")
                elif len(self.registered_sensors) > 0:
                    logger.debug(f"🕐 AUTO-DETACH MONITOR: All {len(self.registered_sensors)} sensors within activity thresholds")

        except asyncio.CancelledError:
            logger.info(f"🕐 AUTO-DETACH MONITOR CANCELLED")
            raise
        except Exception as e:
            logger.error(f"❌ AUTO-DETACH MONITOR ERROR: {e}")
            raise

    async def send_inactivity_warning(self, eui_key: str, inactive_time: float, warning_timeout: float, detach_timeout: float) -> None:
        """Send warning notification for inactive sensor"""
        eui = eui_key.upper()
        hours_inactive = inactive_time / 3600
        hours_until_detach = (detach_timeout - inactive_time) / 3600

        logger.warning(f"⚠️  SENSOR INACTIVITY WARNING")
        logger.warning(f"   Sensor EUI: {eui}")
        logger.warning(f"   Inactive for: {hours_inactive:.1f} hours")
        logger.warning(f"   Warning threshold: {warning_timeout / 3600:.1f} hours")
        logger.warning(f"   Auto-detach in: {hours_until_detach:.1f} hours")

        # Update sensor status with warning
        if eui_key in self.registered_sensors:
            self.registered_sensors[eui_key]['warning_status'] = {
                'active': True,
                'inactive_hours': round(hours_inactive, 1),
                'hours_until_detach': round(hours_until_detach, 1),
                'warning_sent_time': self._get_local_time()
            }

        # Send MQTT warning notification
        if self.mqtt_out_queue:
            warning_payload = {
                "action": "inactivity_warning",
                "sensor_eui": eui,
                "inactive_hours": round(hours_inactive, 1),
                "hours_until_detach": round(hours_until_detach, 1),
                "warning_threshold_hours": warning_timeout / 3600,
                "detach_threshold_hours": detach_timeout / 3600,
                "timestamp": asyncio.get_event_loop().time()
            }

            await self.mqtt_out_queue.put({
                "topic": f"ep/{eui.upper()}/warning",
                "payload": json.dumps(warning_payload)
            })

            logger.warning(f"📤 Inactivity warning notification sent via MQTT for {eui}")

    async def auto_detach_inactive_sensor(self, eui_key: str, inactive_time: float) -> None:
        """Auto-detach a sensor due to inactivity"""
        eui = eui_key.upper()
        hours_inactive = inactive_time / 3600

        logger.warning(f"🔌 AUTO-DETACH TRIGGERED")
        logger.warning(f"   Sensor EUI: {eui}")
        logger.warning(f"   Inactive for: {hours_inactive:.1f} hours")
        logger.warning(f"   Threshold: {getattr(bssci_config, 'AUTO_DETACH_TIMEOUT', 259200) / 3600:.1f} hours")

        # Perform detach
        success = await self.detach_sensor(eui)

        if success:
            # Update sensor status to indicate auto-detach
            if eui_key in self.registered_sensors:
                self.registered_sensors[eui_key]['auto_detached'] = {
                    'detached': True,
                    'reason': 'inactivity',
                    'inactive_hours': round(hours_inactive, 1),
                    'detach_time': self._get_local_time()
                }

            # Remove from last seen and warning tracking
            self.sensor_last_seen.pop(eui_key, None)
            self.sensor_warning_sent.pop(eui_key, None)

            logger.warning(f"✅ AUTO-DETACH COMPLETED for sensor {eui}")

            # Send MQTT auto-detach notification
            if self.mqtt_out_queue:
                detach_payload = {
                    "action": "auto_detached",
                    "sensor_eui": eui,
                    "reason": "inactivity",
                    "inactive_hours": round(hours_inactive, 1),
                    "threshold_hours": getattr(bssci_config, 'AUTO_DETACH_TIMEOUT', 259200) / 3600,
                    "timestamp": asyncio.get_event_loop().time()
                }

                await self.mqtt_out_queue.put({
                    "topic": f"ep/{eui.upper()}/status",
                    "payload": json.dumps(detach_payload)
                })

                logger.warning(f"📤 Auto-detach notification sent via MQTT for {eui}")
        else:
            logger.error(f"❌ AUTO-DETACH FAILED for sensor {eui}")

            # Send MQTT failure notification
            if self.mqtt_out_queue:
                failure_payload = {
                    "action": "auto_detach_failed",
                    "sensor_eui": eui,
                    "inactive_hours": round(hours_inactive, 1),
                    "timestamp": asyncio.get_event_loop().time()
                }

                await self.mqtt_out_queue.put({
                    "topic": f"ep/{eui.upper()}/error",
                    "payload": json.dumps(failure_payload)
                })

    async def queue_watcher(self) -> None:
        logger.info("📨 MQTT queue watcher started - monitoring for configuration updates")
        logger.info(f"   Watching queue ID: {id(self.mqtt_in_queue)}")
        try:
            while True:
                logger.debug(f"⏳ Queue watcher waiting for message (queue size: {self.mqtt_in_queue.qsize()})")
                msg = dict(await self.mqtt_in_queue.get())
                logger.info(f"📥 MQTT CONFIGURATION MESSAGE received")
                logger.debug(f"   Raw message: {msg}")

                if (
                    "eui" in msg.keys()
                    and "nwKey" in msg.keys()
                    and "shortAddr" in msg.keys()
                    and "bidi" in msg.keys()
                ):
                    logger.info(f"🔧 PROCESSING ENDPOINT CONFIGURATION")
                    logger.info(f"   Endpoint EUI: {msg['eui']}")
                    logger.info(f"   Short Address: {msg['shortAddr']}")
                    logger.info(f"   Network Key: {msg['nwKey'][:8]}...{msg['nwKey'][-8:]}")
                    logger.info(f"   Bidirectional: {msg['bidi']}")

                    if self.connected_base_stations:
                        logger.info(f"📤 PROPAGATING to {len(self.connected_base_stations)} connected base stations")
                        for writer, bs_eui in self.connected_base_stations.items():
                            logger.info(f"   Sending attach request to base station: {bs_eui}")
                            await self.send_attach_request(writer, msg)
                    else:
                        logger.warning("⚠️  NO BASE STATIONS CONNECTED")
                        logger.warning("   Configuration saved but attach requests will be sent when base stations connect")

                    logger.info(f"💾 UPDATING local configuration file")
                    self.update_or_add_entry(msg)
                    logger.info(f"✅ ENDPOINT CONFIGURATION processing complete for {msg['eui']}")
                else:
                    logger.error(f"❌ INVALID MQTT configuration message - missing required fields")
                    logger.error(f"   Required: eui, nwKey, shortAddr, bidi")
                    logger.error(f"   Received: {list(msg.keys())}")
        except asyncio.CancelledError:
            logger.info("📨 MQTT queue watcher stopped")
        except Exception as e:
            logger.error(f"❌ Error in MQTT queue watcher: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")

    # ==================== Variable MAC (VM) Sub-Channel Methods ====================
    
    async def vm_activate(self, mac_type: int = 0) -> bool:
        """Activate VM sub-channel reception
        
        Per BSSCI VM specification:
        - command: "vm.activate"
        - opId: Numeric ID of the operation
        - macType: Numeric MAC-Type of the intended Variable MAC
        """
        logger.info(f"📡 VM ACTIVATE request, macType {mac_type}")
        
        if not self.connected_base_stations:
            logger.warning("   No base stations connected")
            return False
        
        success = False
        for writer, bs_eui in self.connected_base_stations.items():
            try:
                op_id = self.opID
                self.opID -= 1
                
                self.pending_vm_operations[op_id] = {
                    "operation": "activate",
                    "mac_type": mac_type,
                    "timestamp": asyncio.get_event_loop().time()
                }
                
                msg_pack = encode_message(messages.build_vm_activate_request(op_id, mac_type))
                writer.write(IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack)
                await writer.drain()
                
                logger.info(f"   Sent VM activate to base station {bs_eui}")
                self.add_vm_log(f"Sent vm.activate (macType={mac_type}) to BS {bs_eui}", "command")
                success = True
            except Exception as e:
                logger.error(f"   Failed to send VM activate to {bs_eui}: {e}")
                self.add_vm_log(f"Failed vm.activate to BS {bs_eui}: {e}", "error")
        
        return success
    
    async def vm_deactivate(self) -> bool:
        """Deactivate VM sub-channel reception
        
        Per BSSCI VM specification:
        - command: "vm.deactivate"
        - opId: Numeric ID of the operation
        """
        logger.info(f"📡 VM DEACTIVATE request")
        
        if not self.connected_base_stations:
            logger.warning("   No base stations connected")
            return False
        
        success = False
        for writer, bs_eui in self.connected_base_stations.items():
            try:
                op_id = self.opID
                self.opID -= 1
                
                self.pending_vm_operations[op_id] = {
                    "operation": "deactivate",
                    "timestamp": asyncio.get_event_loop().time()
                }
                
                msg_pack = encode_message(messages.build_vm_deactivate_request(op_id))
                writer.write(IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack)
                await writer.drain()
                
                logger.info(f"   Sent VM deactivate to base station {bs_eui}")
                self.add_vm_log(f"Sent vm.deactivate to BS {bs_eui}", "command")
                success = True
            except Exception as e:
                logger.error(f"   Failed to send VM deactivate to {bs_eui}: {e}")
                self.add_vm_log(f"Failed vm.deactivate to BS {bs_eui}: {e}", "error")
        
        return success
    
    async def vm_status(self) -> bool:
        """Query VM sub-channel status - returns list of activated macTypes
        
        Per BSSCI VM specification:
        - command: "vm.status"
        - opId: Numeric ID of the operation
        
        Response will contain macTypes: Numeric[] - List of activated macTypes
        """
        logger.info(f"📊 VM STATUS request - querying active MAC types")
        
        if not self.connected_base_stations:
            logger.warning("   No base stations connected")
            return False
        
        success = False
        for writer, bs_eui in self.connected_base_stations.items():
            try:
                op_id = self.opID
                self.opID -= 1
                
                self.pending_vm_operations[op_id] = {
                    "operation": "status",
                    "bs_eui": bs_eui,
                    "timestamp": asyncio.get_event_loop().time()
                }
                
                msg_pack = encode_message(messages.build_vm_status_request(op_id))
                writer.write(IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack)
                await writer.drain()
                
                logger.info(f"   Sent VM status request to base station {bs_eui}")
                self.add_vm_log(f"Sent vm.status to BS {bs_eui}", "command")
                success = True
            except Exception as e:
                logger.error(f"   Failed to send VM status to {bs_eui}: {e}")
                self.add_vm_log(f"Failed vm.status to BS {bs_eui}: {e}", "error")
        
        return success
    
    async def vm_send_data(self, sensor_eui: str, data: bytes, port: int = 1) -> bool:
        """Send data to sensor via VM sub-channel (downlink)"""
        sensor_eui = sensor_eui.upper()
        logger.info(f"📤 VM DOWNLINK DATA for sensor {sensor_eui}")
        logger.info(f"   Port: {port}, Data length: {len(data)} bytes")
        
        # Check if sensor has VM active
        if sensor_eui not in self.vm_active_sensors:
            logger.warning(f"   Sensor {sensor_eui} does not have VM sub-channel active")
            return False
        
        vm_info = self.vm_active_sensors[sensor_eui]
        preferred_bs = vm_info.get("bs_eui")
        
        # Find the writer for the preferred base station
        target_writer = None
        for writer, bs_eui in self.connected_base_stations.items():
            if bs_eui == preferred_bs:
                target_writer = writer
                break
        
        if not target_writer:
            # Use any connected base station if preferred one not found
            if self.connected_base_stations:
                target_writer = list(self.connected_base_stations.keys())[0]
            else:
                logger.warning("   No base stations connected")
                return False
        
        try:
            op_id = self.opID
            self.opID -= 1
            
            self.pending_vm_operations[op_id] = {
                "eui": sensor_eui,
                "operation": "dl_data",
                "timestamp": asyncio.get_event_loop().time()
            }
            
            msg_pack = encode_message(messages.build_vm_dl_data(sensor_eui, op_id, data, port))
            target_writer.write(IDENTIFIER + len(msg_pack).to_bytes(4, byteorder="little") + msg_pack)
            await target_writer.drain()
            
            bs_eui = self.connected_base_stations.get(target_writer, "unknown")
            logger.info(f"   Sent VM downlink data via base station {bs_eui}")
            return True
        except Exception as e:
            logger.error(f"   Failed to send VM downlink data: {e}")
            return False
    
    def add_vm_log(self, message: str, log_type: str = "info") -> None:
        """Add entry to VM log for OMS page"""
        import time
        entry = {
            "timestamp": time.time(),
            "message": message,
            "type": log_type
        }
        self.vm_log.append(entry)
        if len(self.vm_log) > self.vm_log_max_size:
            self.vm_log = self.vm_log[-self.vm_log_max_size:]
    
    def get_vm_log(self) -> list:
        """Get VM log entries"""
        return list(self.vm_log)
    
    def get_vm_status(self) -> dict:
        """Get VM sub-channel status for all sensors"""
        return {
            "active_sensors": dict(self.vm_active_sensors),
            "pending_operations": len(self.pending_vm_operations)
        }
    
    def get_traffic_metrics(self) -> dict:
        """Get traffic metrics for visualization"""
        import time
        current_time = time.time()
        
        # Check for hour change and update hourly active count
        current_hour = datetime.now(timezone.utc).hour
        if current_hour != self._current_hour:
            self._last_hourly_active_count = len(self.active_sensors_hourly)
            self.active_sensors_hourly = set()
            self._current_hour = current_hour
        
        # Update history every minute
        if current_time - self._last_history_update >= 60:
            self.traffic_history.append({
                'timestamp': current_time,
                'messages_in': self.traffic_metrics['messages_in'],
                'messages_out': self.traffic_metrics['messages_out'],
                'messages_dropped': self.traffic_metrics['messages_dropped'],
                'sensors_registered': len(self.registered_sensors),
                'sensors_active': len(self.active_sensors_hourly),
                'base_stations': len(self.connected_base_stations)
            })
            # Keep only last 720 entries (12 hours)
            if len(self.traffic_history) > 720:
                self.traffic_history = self.traffic_history[-720:]
            self._last_history_update = current_time
        
        return {
            'metrics': dict(self.traffic_metrics),
            'dedup_stats': dict(self.deduplication_stats),
            'history': list(self.traffic_history),
            'connections': len(self.connected_base_stations),
            'sensors_registered': len(self.registered_sensors),
            'sensors_active': len(self.active_sensors_hourly)
        }
    
    def reset_traffic_metrics(self) -> None:
        """Reset traffic metrics"""
        self.traffic_metrics = {
            'messages_in': 0,
            'messages_out': 0,
            'messages_dropped': 0,
            'bytes_in': 0,
            'bytes_out': 0,
            'vm_messages': 0,
            'attach_requests': 0,
            'detach_requests': 0,
            'status_requests': 0,
            'start_time': datetime.now(timezone.utc).timestamp()
        }
        self.traffic_history = []
        self._last_history_update = 0

    def get_base_station_status(self) -> dict:
        """Get status of connected base stations"""
        connected_stations = []
        for writer, bs_eui in list(self.connected_base_stations.items()):
            try:
                if writer is None:
                    continue
                addr = writer.get_extra_info("peername")
                ssl_obj = writer.get_extra_info("ssl_object")

                station_info = {
                    "eui": bs_eui.upper(),
                    "address": f"{addr[0]}:{addr[1]}" if addr else "unknown",
                    "status": "connected"
                }

                if ssl_obj:
                    try:
                        cert = ssl_obj.getpeercert()
                        if cert:
                            subject = cert.get('subject', [])
                            for field in subject:
                                for name, value in field:
                                    if name == 'commonName':
                                        station_info['certificate_cn'] = value
                                        break
                    except:
                        pass

                connected_stations.append(station_info)
            except Exception:
                continue

        connecting_stations = []
        for writer, bs_eui in list(self.connecting_base_stations.items()):
            try:
                if writer is None:
                    continue
                addr = writer.get_extra_info("peername")
                connecting_stations.append({
                    "eui": bs_eui.upper(),
                    "address": f"{addr[0]}:{addr[1]}" if addr else "unknown",
                    "status": "connecting"
                })
            except Exception:
                continue

        return {
            "connected": connected_stations,
            "connecting": connecting_stations,
            "total_connected": len(connected_stations),
            "total_connecting": len(connecting_stations)
        }

    def reload_sensor_config(self) -> None:
        """Reload sensor configuration from file"""
        try:
            with open(self.sensor_config_file, "r") as f:
                new_config = json.load(f)

            old_count = len(self.sensor_config)
            self.sensor_config = new_config
            new_count = len(self.sensor_config)

            logger.info(f"Sensor configuration reloaded: {old_count} -> {new_count} sensors")

            # Clear registration status for removed sensors
            configured_euis = {sensor['eui'].upper() for sensor in self.sensor_config}
            removed_euis = set(self.registered_sensors.keys()) - configured_euis
            for eui in removed_euis:
                self.registered_sensors.pop(eui, None)
                logger.info(f"Removed registration status for deleted sensor: {eui}")

        except Exception as e:
            logger.error(f"Failed to reload sensor configuration: {e}")

    def _extract_oms_meter_id(self, data: list) -> str | None:
        """Extract OMS meter ID from WMBUS payload data.
        
        WMBUS format typically:
        - Byte 0: Length
        - Byte 1: C-field (control)
        - Bytes 2-3: M-field (manufacturer)
        - Bytes 4-7: A-field (meter ID, 4 bytes, little-endian)
        - Byte 8: Version
        - Byte 9: Type (device type)
        
        Returns the meter ID as a hex string, or None if data is too short.
        """
        try:
            if len(data) < 10:
                return None
            
            # Extract manufacturer (bytes 2-3, little-endian)
            manufacturer = bytes(data[2:4]).hex().upper()
            
            # Extract meter ID (bytes 4-7, little-endian, so reverse for display)
            meter_id_bytes = data[4:8]
            meter_id = bytes(meter_id_bytes[::-1]).hex().upper()
            
            # Extract version and type
            version = data[8] if len(data) > 8 else 0
            device_type = data[9] if len(data) > 9 else 0
            
            # Return combined identifier: manufacturer + meter_id
            return f"{manufacturer}{meter_id}"
        except Exception as e:
            logger.debug(f"Failed to extract OMS meter ID: {e}")
            return None

    def get_oms_meters(self) -> Dict[str, Dict[str, Any]]:
        """Return all tracked OMS meters."""
        return self.oms_meters.copy()

    def get_oms_stats(self) -> Dict[str, Any]:
        """Return OMS statistics."""
        total_meters = len(self.oms_meters)
        total_messages = sum(m.get('message_count', 0) for m in self.oms_meters.values())
        return {
            'total_meters': total_meters,
            'total_messages': total_messages
        }


    def get_sensor_registration_status(self) -> Dict[str, Dict[str, Any]]:
        """Get registration status of all sensors"""
        status = {}
        current_time = asyncio.get_event_loop().time()

        for sensor in self.sensor_config:
            eui = sensor['eui'].upper()
            reg_info = self.registered_sensors.get(eui, {})

            # Get preferred downlink path from sensor config or from instance attribute
            preferred_path = sensor.get('preferredDownlinkPath', None)
            if hasattr(self, 'preferred_downlink_paths') and eui in self.preferred_downlink_paths:
                preferred_path = self.preferred_downlink_paths[eui]

            # Calculate activity status
            last_seen = self.sensor_last_seen.get(eui, reg_info.get('timestamp', 0))
            time_since_last_seen = current_time - last_seen if last_seen > 0 else 0
            hours_since_last_seen = time_since_last_seen / 3600

            # Determine activity status
            activity_status = "active"
            warning_info = None
            auto_detach_info = None

            if getattr(bssci_config, 'AUTO_DETACH_ENABLED', True) and last_seen > 0:
                warning_timeout = getattr(bssci_config, 'AUTO_DETACH_WARNING_TIMEOUT', 129600)
                detach_timeout = getattr(bssci_config, 'AUTO_DETACH_TIMEOUT', 259200)

                if time_since_last_seen > detach_timeout:
                    activity_status = "auto_detach_pending"
                elif time_since_last_seen > warning_timeout:
                    activity_status = "warning"
                    warning_info = {
                        'hours_inactive': round(hours_since_last_seen, 1),
                        'hours_until_detach': round((detach_timeout - time_since_last_seen) / 3600, 1),
                        'warning_sent': self.sensor_warning_sent.get(eui, False)
                    }

            # Check for auto-detach info from registration
            if 'auto_detached' in reg_info:
                auto_detach_info = reg_info['auto_detached']
                activity_status = "auto_detached"

            status[eui] = {
                'eui': sensor['eui'],
                'nwKey': sensor['nwKey'],
                'shortAddr': sensor['shortAddr'],
                'bidi': sensor['bidi'],
                'registered': eui in self.registered_sensors,
                'registration_info': reg_info,
                'base_stations': reg_info.get('base_stations', []),
                'total_registrations': len(reg_info.get('base_stations', [])),
                'preferredDownlinkPath': preferred_path,
                'activity_status': activity_status,
                'last_seen_timestamp': last_seen,
                'hours_since_last_seen': round(hours_since_last_seen, 1) if last_seen > 0 else None,
                'warning_info': warning_info,
                'auto_detach_info': auto_detach_info,
                'warning_status': reg_info.get('warning_status', None)
            }
        return status

    def clear_all_sensors(self) -> None:
        """Clear all sensor configurations and registrations"""
        logger.info(f"🗑️ CLEARING ALL SENSOR CONFIGURATIONS")

        # Clear sensor config
        old_count = len(self.sensor_config)
        self.sensor_config = []

        # Clear registered sensors
        old_registered = len([k for k in self.registered_sensors.keys() if not k.endswith('_failure')])
        self.registered_sensors.clear()

        # Clear pending requests
        self.pending_attach_requests.clear()

        logger.info(f"✅ ALL SENSORS CLEARED")
        logger.info(f"   Configurations removed: {old_count}")
        logger.info(f"   Registrations removed: {old_registered}")

    def update_preferred_downlink_path(self, eui: str, bs_eui: str, snr: float) -> None:
        """Update the preferred downlink path for a sensor based on signal quality"""
        eui_upper = eui.upper()

        # Find the sensor in configuration
        for sensor in self.sensor_config:
            if sensor["eui"].upper() == eui_upper:
                # Update preferred downlink path
                if "preferredDownlinkPath" not in sensor:
                    sensor["preferredDownlinkPath"] = {}

                sensor["preferredDownlinkPath"] = {
                    "baseStation": bs_eui,
                    "snr": round(snr, 2),
                    "lastUpdated": self._get_local_time(),
                    "messageCount": sensor["preferredDownlinkPath"].get("messageCount", 0) + 1
                }

                logger.info(f"📊 PREFERRED PATH UPDATED for sensor {eui}")
                logger.info(f"   Base Station: {bs_eui}")
                logger.info(f"   SNR: {snr:.2f} dB")
                logger.info(f"   Total messages: {sensor['preferredDownlinkPath']['messageCount']}")

                # Save configuration
                try:
                    with open(self.sensor_config_file, "w") as f:
                        json.dump(self.sensor_config, f, indent=4)
                    logger.debug(f"✅ Preferred downlink path saved successfully")
                except Exception as e:
                    logger.error(f"❌ Failed to save preferred downlink path: {e}")
                break
        else:
            logger.warning(f"⚠️  Sensor {eui} not found in configuration for preferred path update")

    def update_or_add_entry(self, msg: dict[str, Any]) -> None:
        # Update existing entry or add new one
        for sensor in self.sensor_config:
            if sensor["eui"].upper() == msg["eui"].upper():
                sensor["eui"] = msg["eui"].upper()  # Ensure stored EUI is uppercase
                sensor["nwKey"] = msg["nwKey"]
                sensor["shortAddr"] = msg["shortAddr"]
                sensor["bidi"] = msg["bidi"]
                logger.info(f"Updated configuration for existing endpoint {msg['eui']}")
                break
        else:
            # No existing entry found → add new one
            new_sensor = {
                "eui": msg["eui"].upper(),
                "nwKey": msg["nwKey"],
                "shortAddr": msg["shortAddr"],
                "bidi": msg["bidi"]
            }
            self.sensor_config.append(new_sensor)
            logger.info(f"Added new endpoint configuration for {msg['eui']}")

        # Save updated configuration to file
        try:
            logger.info(f"💾 SAVING configuration to {self.sensor_config_file}")
            with open(self.sensor_config_file, "w") as f:
                json.dump(self.sensor_config, f, indent=4)
            logger.info(f"✅ Configuration saved to {self.sensor_config_file}")
        except Exception as e:
            logger.error(f"❌ Failed to save configuration: {e}")
            
            # Try emergency save
            try:
                alt_file = f"{self.sensor_config_file}.emergency"
                with open(alt_file, "w") as f:
                    json.dump(self.sensor_config, f, indent=4)
                logger.error(f"   Emergency backup saved to: {alt_file}")
            except:
                logger.error(f"   Emergency backup also failed!")
    
    def detach_sensor_sync(self, eui: str) -> bool:
        """Synchronous wrapper for detach_sensor (for Web UI)"""
        try:
            # Create new event loop for sync call
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self.detach_sensor(eui))
                return result
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Sync detach failed for {eui}: {e}")
            return False
            
    def add_sensor_via_ui(self, sensor_data: dict) -> bool:
        """Add sensor via Web UI - sends to MQTT queue for processing"""
        try:
            # Ensure EUI is uppercase
            sensor_data['eui'] = sensor_data['eui'].upper()
            
            # Add to MQTT queue using thread-safe method
            import asyncio
            import threading
            
            def queue_sensor():
                try:
                    # Get or create event loop for this thread
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    
                    # Schedule the coroutine
                    asyncio.ensure_future(self.mqtt_in_queue.put(sensor_data), loop=loop)
                    logger.info(f"✅ Sensor {sensor_data['eui']} queued for processing via UI")
                except Exception as e:
                    logger.error(f"Failed to queue sensor in thread: {e}")
            
            # Run in separate thread to avoid blocking
            thread = threading.Thread(target=queue_sensor)
            thread.start()
            
            return True
        except Exception as e:
            logger.error(f"Failed to add sensor via UI: {e}")
            return False

    async def process_mqtt_messages(self) -> None:
        """Process incoming MQTT messages for sensor configuration and commands"""
        logger.info("🔄 MQTT MESSAGE PROCESSOR STARTING")
        logger.info(f"   Monitoring queue ID: {id(self.mqtt_in_queue)}")

        message_count = 0
        try:
            while True:
                logger.debug(f"⏳ Waiting for MQTT message (queue size: {self.mqtt_in_queue.qsize()})")
                message = await self.mqtt_in_queue.get()
                message_count += 1

                logger.info(f"🎉 MQTT MESSAGE #{message_count} RECEIVED!")
                logger.info(f"   EUI: {message.get('eui', 'unknown')}")
                logger.info(f"   Message Type: {message.get('message_type', 'config')}")
                logger.info(f"   Message Keys: {list(message.keys())}")

                try:
                    message_type = message.get('message_type', 'config')

                    if message_type == 'command':
                        # Process command messages
                        await self.process_mqtt_command(message)
                    else:
                        # Process configuration messages
                        # Validate required fields
                        required_fields = ['eui', 'nwKey', 'shortAddr']
                        missing_fields = [field for field in required_fields if field not in message]

                        if missing_fields:
                            logger.error(f"❌ Invalid sensor configuration - missing fields: {missing_fields}")
                            continue

                        # Process the sensor configuration
                        await self.process_sensor_config_message(message)

                except Exception as e:
                    logger.error(f"❌ Failed to process MQTT message: {e}")
                    logger.error(f"   Message: {message}")

        except Exception as e:
            logger.error(f"❌ MQTT MESSAGE PROCESSOR FAILED: {e}")
            raise

    async def process_sensor_config_message(self, message: dict) -> None:
        """Process sensor configuration messages from MQTT"""
        logger.info(f"🔧 PROCESSING SENSOR CONFIGURATION MESSAGE")
        logger.info(f"   EUI: {message.get('eui', 'unknown')}")
        logger.info(f"   Short Address: {message.get('shortAddr', 'unknown')}")
        logger.info(f"   Network Key: {message.get('nwKey', 'unknown')[:8]}...")
        logger.info(f"   Bidirectional: {message.get('bidi', 'unknown')}")
        
        # Send attach requests to connected base stations
        if self.connected_base_stations:
            logger.info(f"📤 PROPAGATING to {len(self.connected_base_stations)} connected base stations")
            for writer, bs_eui in self.connected_base_stations.items():
                logger.info(f"   Sending attach request to base station: {bs_eui}")
                try:
                    await self.send_attach_request(writer, message)
                except Exception as e:
                    logger.error(f"Failed to send attach request to {bs_eui}: {e}")
        else:
            logger.warning("⚠️  NO BASE STATIONS CONNECTED")
            logger.warning("   Configuration saved but attach requests will be sent when base stations connect")
        
        # Update local configuration
        logger.info(f"💾 UPDATING local configuration file")
        self.update_or_add_entry(message)
        logger.info(f"✅ SENSOR CONFIGURATION processing complete for {message['eui']}")

    async def process_mqtt_command(self, command: dict) -> None:
        """Process MQTT command messages"""
        eui = command.get('eui')
        action = command.get('action', '').lower()
        
        if not eui:
            logger.error(f"❌ MQTT command missing EUI: {command}")
            return

        logger.info(f"🎯 PROCESSING MQTT COMMAND for {eui}: {action}")

        try:
            if action == 'detach':
                # Detach sensor from all base stations
                success = await self.detach_sensor(eui)

                # Send response
                response_payload = {
                    "action": "detach_response",
                    "sensor_eui": eui,
                    "success": success,
                    "timestamp": asyncio.get_event_loop().time()
                }

                await self.mqtt_out_queue.put({
                    "topic": f"ep/{eui.upper()}/response",
                    "payload": json.dumps(response_payload)
                })

                logger.info(f"✅ DETACH command processed for {eui}, success: {success}")

            elif action == 'attach':
                # Find sensor in config and attach
                sensor_config = None
                for sensor in self.sensor_config:
                    if sensor['eui'].upper() == eui.upper():
                        sensor_config = sensor
                        break

                if sensor_config:
                    # Attach to all connected base stations
                    success_count = 0
                    for writer in list(self.connected_base_stations.keys()):
                        try:
                            await self.send_attach_request(writer, sensor_config)
                            success_count += 1
                            await asyncio.sleep(0.1)
                        except Exception as e:
                            logger.error(f"Failed to attach {eui} to base station: {e}")

                    success = success_count > 0
                else:
                    logger.error(f"Sensor {eui} not found in configuration")
                    success = False

                # Send response
                response_payload = {
                    "action": "attach_response",
                    "sensor_eui": eui,
                    "success": success,
                    "attached_to": success_count if success else 0,
                    "timestamp": asyncio.get_event_loop().time()
                }

                await self.mqtt_out_queue.put({
                    "topic": f"ep/{eui.upper()}/response",
                    "payload": json.dumps(response_payload)
                })

                logger.info(f"✅ ATTACH command processed for {eui}, success: {success}")

            elif action == 'status':
                # Get sensor status
                eui_key = eui.upper()  # Use upper for consistency
                if eui_key in self.registered_sensors:
                    sensor_status = self.registered_sensors[eui_key]
                else:
                    sensor_status = {"registered": False, "base_stations": []}

                # Send status response
                response_payload = {
                    "action": "status_response",
                    "sensor_eui": eui,
                    "status": sensor_status,
                    "timestamp": asyncio.get_event_loop().time()
                }

                await self.mqtt_out_queue.put({
                    "topic": f"ep/{eui.upper()}/response",
                    "payload": json.dumps(response_payload)
                })

                logger.info(f"✅ STATUS command processed for {eui}")

            else:
                logger.warning(f"❓ Unknown command action: {action} for sensor {eui}")

                # Send error response
                response_payload = {
                    "action": "error_response",
                    "sensor_eui": eui,
                    "error": f"Unknown command: {action}",
                    "timestamp": asyncio.get_event_loop().time()
                }

                await self.mqtt_out_queue.put({
                    "topic": f"ep/{eui.upper()}/response",
                    "payload": json.dumps(response_payload)
                })

        except Exception as e:
            logger.error(f"❌ Error processing command {action} for {eui}: {e}")

            # Send error response
            try:
                response_payload = {
                    "action": "error_response",
                    "sensor_eui": eui,
                    "error": str(e),
                    "timestamp": asyncio.get_event_loop().time()
                }

                await self.mqtt_out_queue.put({
                    "topic": f"ep/{eui.upper()}/response",
                    "payload": json.dumps(response_payload)
                })
            except:
                pass  # Don't let error response fail

    def _update_snr_rssi_history(self, current_time: float) -> None:
        """Update SNR/RSSI history with current averages"""
        total_snr = 0
        total_rssi = 0
        count = 0
        
        for stats in self.sensor_packet_stats.values():
            if stats.get('snr_count', 0) > 0:
                total_snr += stats['snr_sum'] / stats['snr_count']
                total_rssi += stats['rssi_sum'] / stats['rssi_count']
                count += 1
        
        if count > 0:
            avg_snr = round(total_snr / count, 2)
            avg_rssi = round(total_rssi / count, 2)
        else:
            avg_snr = 0
            avg_rssi = 0
        
        self.snr_rssi_history.append({
            'timestamp': current_time,
            'avg_snr': avg_snr,
            'avg_rssi': avg_rssi
        })
        
        # Keep last 288 entries (24 hours of data at 5 min intervals)
        if len(self.snr_rssi_history) > 288:
            self.snr_rssi_history = self.snr_rssi_history[-288:]
        
        self._last_snr_history_update = current_time

    async def process_sensor_config(self, config: dict) -> None:
        """Process a single sensor configuration update from MQTT"""
        eui = config.get('eui')
        if not eui:
            logger.error("Sensor configuration update received without EUI.")
            return

        logger.info(f"🔧 Processing sensor configuration update for EUI: {eui}")

        # Update the sensor configuration in the local list
        self.update_or_add_entry(config)

        # If base stations are connected, trigger an attach request for this sensor
        if self.connected_base_stations:
            logger.info(f"📤 Sending attach request for updated sensor {eui} to all connected base stations")
            for writer, bs_eui in self.connected_base_stations.items():
                try:
                    await self.send_attach_request(writer, config)
                    await asyncio.sleep(0.1) # Small delay between requests
                except Exception as e:
                    logger.error(f"Failed to send attach request for {eui} to {bs_eui}: {e}")
        else:
            logger.warning(f"⚠️  No base stations connected, attach request for {eui} will be sent when they connect.")