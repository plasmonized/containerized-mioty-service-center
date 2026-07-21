import asyncio
import json
import logging
from typing import Any

from aiomqtt import Client

from bssci_config import (
    BASE_TOPIC,
    MQTT_BROKER,
    MQTT_PASSWORD,
    MQTT_PORT,
    MQTT_USERNAME,
)
from observability import ERROR_CODES

logger = logging.getLogger(__name__)


class MQTTClient:
    def __init__(
        self,
        mqtt_out_queue: asyncio.Queue[dict[str, str]],
        mqtt_in_queue: asyncio.Queue[dict[str, str]],
    ):
        self.broker_host = MQTT_BROKER
        if BASE_TOPIC.endswith("/"):
            self.base_topic = BASE_TOPIC[:-1]
        else:
            self.base_topic = BASE_TOPIC
        self.config_topic = self.base_topic + "/ep/+/config"  # Legacy support, wird durch register ersetzt
        self.register_topic = self.base_topic + "/ep/+/register"
        self.command_topic = self.base_topic + "/ep/+/cmd"
        self.mqtt_out_queue = mqtt_out_queue
        self.mqtt_in_queue = mqtt_in_queue

        # Add queue logging
        logger.info("🔍 MQTT Client Queue Assignment:")
        logger.info(f"   mqtt_out_queue ID: {id(self.mqtt_out_queue)}")
        logger.info(f"   mqtt_in_queue ID: {id(self.mqtt_in_queue)}")

    def log_queue_info(self) -> None:
        """Log queue information for debugging"""
        logger.info("🔍 MQTT Client Queue Information:")
        logger.info(f"   mqtt_out_queue ID: {id(self.mqtt_out_queue)}, size: {self.mqtt_out_queue.qsize()}")
        logger.info(f"   mqtt_in_queue ID: {id(self.mqtt_in_queue)}, size: {self.mqtt_in_queue.qsize()}")

    async def start(self) -> None:
        """Start MQTT client with simple connection pattern"""
        retry_delay = 5.0
        max_delay = 60.0

        while True:
            try:
                logger.info("=" * 60)
                logger.info("🔄 MQTT CONNECTION ATTEMPT")
                logger.info("=" * 60)
                logger.info(f"📡 Broker: {self.broker_host}:{MQTT_PORT}")
                logger.info(f"👤 Username: {MQTT_USERNAME}")
                logger.info(f"🔐 Password: {'*' * len(MQTT_PASSWORD) if MQTT_PASSWORD else 'NOT SET'}")
                logger.info(f"🎯 Config Topic: {self.config_topic}")
                logger.info(f"🏠 Base Topic: {self.base_topic}")

                # Use the working simple pattern with authentication
                logger.info("🔧 Creating MQTT client...")

                async with Client(
                    hostname=self.broker_host,
                    port=MQTT_PORT,
                    username=MQTT_USERNAME,
                    password=MQTT_PASSWORD,
                    keepalive=60,  # Send keepalive every 60 seconds
                    timeout=30,  # Connection timeout after 30 seconds
                ) as client:
                    logger.info("✅ MQTT CLIENT CONNECTION SUCCESSFUL!")
                    logger.info("✅ Authentication completed successfully")

                    # Reset retry delay on successful connection
                    retry_delay = 5.0

                    # Test connection
                    logger.info("🏓 Testing MQTT connection with ping...")
                    test_topic = f"{self.base_topic}/connection_test"
                    test_payload = f'{{"status": "connected", "timestamp": "{asyncio.get_event_loop().time()}"}}'
                    await client.publish(test_topic, test_payload)
                    logger.info("✅ MQTT ping successful - connection is stable")

                    # Run both handlers with health monitoring
                    logger.info("🎭 Starting concurrent MQTT handlers with health monitoring...")
                    self.log_queue_info()

                    await asyncio.gather(
                        self._handle_incoming(client),
                        self._handle_outgoing(client),
                        self._connection_health_monitor(client),
                        return_exceptions=True,
                    )

            except Exception as e:
                logger.error("=" * 60)
                logger.error("❌ MQTT CONNECTION FAILED")
                logger.error("=" * 60)
                logger.error(f"🚨 Error: {e}", extra={"error_code": ERROR_CODES["MQTT_CONNECTION_FAILED"]})
                logger.error(f"🔍 Error Type: {type(e).__name__}")

                logger.error("⏰ RETRY INFORMATION:")
                logger.error(f"   Next attempt in: {retry_delay} seconds")
                logger.error("=" * 60)

                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, max_delay)

    async def _handle_incoming(self, client: Client) -> None:
        logger.info("🔔 MQTT INCOMING HANDLER STARTING")
        logger.info("=" * 50)
        logger.info(f"📌 Subscription Topic: {self.config_topic}")

        try:
            # Subscribe to topics with retained messages handling
            topics = [
                (f"{self.base_topic}/ep/+/dl", 0),  # Downlink messages
                (f"{self.base_topic}/ep/+/cmd", 0),  # Command messages (vereinheitlicht)
                (f"{self.base_topic}/ep/+/register", 0),  # Legacy sensor registration
                (f"{self.base_topic}/ep/+/config", 0),  # Alternative config (still supported)
                (f"{self.base_topic}/config/+", 0),  # System configuration messages
            ]
            await client.subscribe(topics)
            logger.info("✅ MQTT SUBSCRIPTION SUCCESSFUL")
            logger.info(f"👂 MQTT listening on config topic: {self.config_topic}")
            logger.info(f"👂 MQTT listening on register topic: {self.register_topic}")
            logger.info(f"👂 MQTT listening on command topic: {self.command_topic}")
            logger.info("👂 MQTT incoming message handler is now ACTIVE and listening...")
            logger.info("   ✅ Legacy /register topic support enabled")
            logger.info("   ✅ Unified /cmd topic for all commands")
            logger.info("👂 MQTT incoming message handler is now ACTIVE and listening...")
        except Exception as sub_error:
            logger.error(
                f"❌ MQTT subscription failed: {sub_error}",
                extra={"error_code": ERROR_CODES["MQTT_SUBSCRIPTION_FAILED"]},
            )
            raise

        message_count = 0
        try:
            async for message in client.messages:
                message_count += 1
                logger.debug(f"🎉 MQTT INCOMING MESSAGE #{message_count} RECEIVED!")
                logger.debug(f"📍 Topic: {message.topic}")

                try:
                    # Extract EUI like the working version
                    topic_parts = str(message.topic).split("/")
                    base_parts = self.base_topic.split("/")

                    if len(topic_parts) > len(base_parts) + 1:
                        eui = topic_parts[len(base_parts) + 1].upper()
                        logger.info(f"🔑 Extracted EUI: {eui}")

                        if hasattr(message.payload, "decode"):
                            payload_str = message.payload.decode("utf-8")
                        else:
                            payload_str = str(message.payload)
                        logger.debug(f"📄 Payload: {payload_str}")

                        payload_dict = json.loads(payload_str)

                        # Check if this is a command message
                        if "/cmd" in str(message.topic):
                            await self.handle_command_message(str(message.topic), payload_dict, eui)
                            return

                        # Check if this is a register message (Legacy support)
                        if "/register" in str(message.topic):
                            await self.handle_register_message(str(message.topic), payload_dict, eui)
                            return

                        # This is a config message (alternative method)
                        config = payload_dict
                        config["eui"] = eui.upper()
                        config["message_type"] = "config"

                        logger.info(f"✅ Configuration received for EUI {eui}")
                        logger.info(f"   Queue size before put: {self.mqtt_in_queue.qsize()}")
                        await self.mqtt_in_queue.put(config)
                        logger.info("✅ Configuration queued successfully")
                        logger.info(f"   Queue size after put: {self.mqtt_in_queue.qsize()}")
                        logger.info(f"📋 Config: {json.dumps(config, indent=2)}")

                    else:
                        logger.warning(f"⚠️  Invalid topic format: {message.topic}")

                except Exception as e:
                    logger.error(
                        f"❌ Message processing failed: {e}",
                        extra={"error_code": ERROR_CODES["MQTT_MESSAGE_PROCESSING_FAILED"]},
                    )

        except Exception as handler_error:
            logger.error(f"❌ MQTT INCOMING HANDLER FAILED: {handler_error}")
            raise

    async def _connection_health_monitor(self, client: Client) -> None:
        """Monitor connection health and force reconnection if needed"""
        logger.info("💓 MQTT CONNECTION HEALTH MONITOR STARTED")

        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes

                # Send a test message to verify connection
                test_topic = f"{self.base_topic}/health_check"
                test_payload = f'{{"timestamp": "{asyncio.get_event_loop().time()}", "status": "alive"}}'

                logger.debug("💓 Performing MQTT health check...")
                await client.publish(test_topic, test_payload)
                logger.debug("✅ MQTT health check successful")

            except Exception as e:
                logger.error(f"💀 MQTT HEALTH CHECK FAILED: {e}")
                logger.error("🔄 Triggering connection reset...")
                raise  # This will cause reconnection

    async def _handle_outgoing(self, client: Client) -> None:
        logger.info("🚀 MQTT OUTGOING HANDLER INITIALIZED")
        logger.info("📤 Ready to publish messages")
        message_count = 0

        try:
            while True:
                msg = None
                try:
                    logger.debug(f"⏳ WAITING FOR MQTT MESSAGE in queue (size: {self.mqtt_out_queue.qsize()})")
                    msg = await self.mqtt_out_queue.get()
                    message_count += 1
                    topic = f"{self.base_topic}/{msg['topic']}"

                    logger.debug(f"🎉 MESSAGE #{message_count} RECEIVED FOR PUBLISHING!")
                    logger.debug(f"   Topic: {topic}")
                    logger.debug(f"   Payload Size: {len(msg['payload'])} bytes")

                    # Use the working simple publish pattern
                    print(f"{topic}:\n\t{msg['payload']}")  # Keep the original print
                    await client.publish(topic, msg["payload"])

                    logger.info("✅ MQTT MESSAGE PUBLISHED SUCCESSFULLY!")

                except Exception as e:
                    logger.error(f"❌ MQTT PUBLISH ERROR: {e}")
                    # For connection errors, re-raise to trigger reconnection
                    if (
                        isinstance(e, (ConnectionError, OSError))
                        or "connection" in str(e).lower()
                        or "not currently connected" in str(e).lower()
                    ):
                        logger.error("   CONNECTION ERROR - TRIGGERING RECONNECTION")
                        await self.mqtt_out_queue.put(msg)  # type: ignore[arg-type]
                        raise
                    # For other errors, continue
                    logger.error("   NON-CONNECTION ERROR - Continuing...")

        except Exception as e:
            logger.error(f"❌ MQTT OUTGOING HANDLER FATAL ERROR: {e}")
            raise

    async def handle_command_message(self, topic: str, payload: dict[str, Any], eui: str) -> None:
        """Handle unified command messages from MQTT (/bssci/ep/eui/cmd)"""
        logger.info(f"🎯 Processing unified command message from topic: {topic}")
        logger.info(f"🔑 EUI: {eui}")

        try:
            # Handle different command types - support both string and dict payloads
            if isinstance(payload, str):
                command = payload.lower().strip()
                logger.info(f"📄 String Command: {command}")
            else:
                command = payload.get("command", payload.get("action", "")).lower().strip()
                logger.info(f"📄 Dict Command: {command}")

            # Validate command
            valid_commands = ["detach", "attach", "status"]
            if command not in valid_commands:
                logger.warning(f"⚠️  Invalid command: {command}. Valid commands: {valid_commands}")
                return

            logger.info(f"✅ Valid command for sensor {eui}: {command}")

            # Create command message for TLS server processing
            command_msg = {
                "message_type": "command",
                "eui": eui,
                "action": command,
                "source": "unified_cmd",
                "timestamp": payload.get("timestamp", asyncio.get_event_loop().time())
                if isinstance(payload, dict)
                else asyncio.get_event_loop().time(),
            }

            # Add to in_queue for TLS server processing
            await self.mqtt_in_queue.put(command_msg)
            logger.info("✅ Unified command queued for TLS server processing")

            # Send acknowledgment
            ack_topic = f"ep/{eui.upper()}/response"
            ack_payload = {"command": command, "status": "received", "timestamp": asyncio.get_event_loop().time()}

            await self.mqtt_out_queue.put({"topic": ack_topic, "payload": json.dumps(ack_payload)})

            logger.info(f"📤 Command acknowledgment sent to {self.base_topic}/{ack_topic}")

        except Exception as e:
            logger.error(f"❌ Error handling unified command message: {e}")
            logger.error(f"   Topic: {topic}")
            logger.error(f"   Payload: {payload}")
            logger.error(f"   EUI: {eui}")

    async def handle_register_message(self, topic: str, payload: dict[str, Any], eui: str) -> None:
        """Handle legacy sensor registration messages from MQTT (/bssci/ep/eui/register)"""
        logger.info(f"🔐 Processing LEGACY registration message from topic: {topic}")
        logger.info(f"🔑 EUI: {eui}")
        logger.info("⚡ Legacy /register topic support - converting to config format")

        try:
            # Legacy register should contain sensor configuration
            # Convert to standard config format
            config = payload.copy()
            config["eui"] = eui.upper()
            config["message_type"] = "config"
            config["source"] = "legacy_register"

            # Validate required fields for registration
            required_fields = ["nwKey", "shortAddr"]
            missing_fields = [field for field in required_fields if field not in config]

            if missing_fields:
                logger.error(f"❌ Legacy registration missing required fields: {missing_fields}")
                logger.error(f"   Required: {required_fields}")
                logger.error(f"   Received: {list(config.keys())}")
                return

            # Set default bidirectional if not specified
            if "bidi" not in config:
                config["bidi"] = False
                logger.info("🔧 Setting default bidi=false for legacy registration")

            logger.info(f"✅ Legacy registration received for EUI {eui}")
            logger.info(f"📋 nwKey: {config.get('nwKey', 'N/A')}")
            logger.info(f"📋 shortAddr: {config.get('shortAddr', 'N/A')}")
            logger.info(f"📋 bidi: {config.get('bidi', 'N/A')}")

            # Queue for TLS server processing
            logger.info(f"   Queue size before put: {self.mqtt_in_queue.qsize()}")
            await self.mqtt_in_queue.put(config)
            logger.info("✅ Legacy registration queued successfully")
            logger.info(f"   Queue size after put: {self.mqtt_in_queue.qsize()}")

            # Send confirmation that legacy registration was processed
            ack_topic = f"ep/{eui.upper()}/response"
            ack_payload = {
                "action": "legacy_register",
                "status": "received",
                "eui": eui,
                "timestamp": asyncio.get_event_loop().time(),
            }

            await self.mqtt_out_queue.put({"topic": ack_topic, "payload": json.dumps(ack_payload)})

            logger.info(f"📤 Legacy registration acknowledgment sent to {self.base_topic}/{ack_topic}")

        except Exception as e:
            logger.error(f"❌ Error handling legacy registration message: {e}")
            logger.error(f"   Topic: {topic}")
            logger.error(f"   Payload: {payload}")
            logger.error(f"   EUI: {eui}")


if __name__ == "__main__":
    import sys

    async def send_mqtt(mqtt_out_queue: asyncio.Queue[dict[str, str]]) -> None:
        eui = "0123456789abcdef"
        data_dict = {
            "rxTime": 1751819907443066821,
            "snr": 23.673797607421875,
            "rssi": -72.2540283203125,
            "cnt": 3749,
            "data": [
                2,
                193,
                1,
                125,
                1,
                225,
                2,
                236,
                1,
                48,
                3,
                121,
                3,
                65,
                7,
                218,
                2,
                120,
                5,
                93,
                5,
            ],
        }
        while True:
            await mqtt_out_queue.put({"topic": f"ep/{eui.upper()}/ul", "payload": json.dumps(data_dict)})
            await asyncio.sleep(5)

    async def main() -> None:
        mqtt_out_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        mqtt_in_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        mqtt_server = MQTTClient(mqtt_out_queue, mqtt_in_queue)
        await asyncio.gather(mqtt_server.start(), send_mqtt(mqtt_out_queue))

    if sys.platform.startswith("win"):
        policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
        if policy_cls is not None:
            asyncio.set_event_loop_policy(policy_cls())
    asyncio.run(main())
    while 1:
        pass
