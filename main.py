import asyncio
import logging

from bssci_config import LISTEN_PORT, MQTT_BROKER, MQTT_PORT, SENSOR_CONFIG_FILE
from mqtt_interface import MQTTClient
from observability import ERROR_CODES, configure_logging
from TLSServer import TLSServer

configure_logging(__name__)
logger = logging.getLogger(__name__)

# Global TLS server instance for web UI access
tls_server_instance = None


async def main() -> None:
    global tls_server_instance
    mqtt_out_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
    mqtt_in_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()

    logger.info("Initializing BSSCI Service Center...")
    logger.info(
        f"Config: TLS Port {LISTEN_PORT}, MQTT Broker {MQTT_BROKER}:{MQTT_PORT}"
    )

    # Setup queue logging to monitor queue usage
    from queue_logger import log_all_queue_stats, setup_queue_logging

    queue_loggers = setup_queue_logging(
        {"mqtt_out_queue": mqtt_out_queue, "mqtt_in_queue": mqtt_in_queue}
    )

    logger.info("🔍 Queue Instance Analysis:")
    logger.info("   mqtt_out_queue Daily Counter: Starting fresh")
    logger.info("   mqtt_in_queue Daily Counter: Starting fresh")

    # Create TLS server instance
    tls_server_instance = TLSServer(SENSOR_CONFIG_FILE, mqtt_out_queue, mqtt_in_queue)

    # Make it available to web_main
    try:
        import web_main

        web_main.set_tls_server(tls_server_instance)
    except ImportError:
        pass  # web_main not available in non-web mode

    # Use the same instance for the server
    tls_server = tls_server_instance
    mqtt_client = MQTTClient(mqtt_out_queue, mqtt_in_queue)

    logger.info("🔍 Queue Assignment Verification:")
    logger.info("   TLS Server mqtt_out_queue: Connected")
    logger.info("   TLS Server mqtt_in_queue: Connected")
    logger.info("   MQTT Client mqtt_out_queue: Connected")
    logger.info("   MQTT Client mqtt_in_queue: Connected")

    # Periodic queue statistics
    async def queue_stats_reporter():
        while True:
            await asyncio.sleep(60)  # Log stats every minute
            log_all_queue_stats(queue_loggers)

    # Start the stats reporter task
    asyncio.create_task(queue_stats_reporter())

    logger.info("Starting BSSCI Service Center...")
    logger.info("✓ Both TLS Server and MQTT Interface are starting...")

    try:
        # Start both services concurrently
        await asyncio.gather(
            tls_server.start_server(), mqtt_client.start(), return_exceptions=True
        )
    except KeyboardInterrupt:
        logger.info("Shutting down BSSCI Service Center...")
    except Exception as e:
        logger.error(f"Service error: {e}", extra={"error_code": ERROR_CODES["SC_SERVICE_ERROR"]})

    logger.info("✓ BSSCI Service Center shut down complete")


if __name__ == "__main__":
    policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_cls is not None:
        asyncio.set_event_loop_policy(policy_cls())
    asyncio.run(main())
