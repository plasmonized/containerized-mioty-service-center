import asyncio
import logging

import bssci_config
from bssci_config import LISTEN_PORT, MQTT_BROKER, MQTT_PORT, SENSOR_CONFIG_FILE
from mqtt_interface import MQTTClient
from observability import ERROR_CODES, configure_logging
from TLSServer import TLSServer

configure_logging(__name__)
logger = logging.getLogger(__name__)

# Global server instances for web UI access
tls_server_instance = None
sca_server_instance = None

# Keep references to background tasks so they are not garbage collected
_background_tasks: set[asyncio.Task] = set()


async def main() -> None:
    global tls_server_instance, sca_server_instance
    mqtt_out_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
    mqtt_in_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()

    logger.info("Initializing BSSCI Service Center...")
    logger.info(f"Config: TLS Port {LISTEN_PORT}, MQTT Broker {MQTT_BROKER}:{MQTT_PORT}")

    # Setup queue logging to monitor queue usage
    from queue_logger import log_all_queue_stats, setup_queue_logging

    queue_loggers = setup_queue_logging(
        {"mqtt_out_queue": mqtt_out_queue, "mqtt_in_queue": mqtt_in_queue}
    )

    logger.info("🔍 Queue Instance Analysis:")
    logger.info("   mqtt_out_queue Daily Counter: Starting fresh")
    logger.info("   mqtt_in_queue Daily Counter: Starting fresh")

    # Create TLS server instance (BSSCI BS interface)
    tls_server_instance = TLSServer(SENSOR_CONFIG_FILE, mqtt_out_queue, mqtt_in_queue)

    # Create SCACI server instance if enabled
    scaci_enabled = getattr(bssci_config, "SCACI_ENABLED", False)
    if scaci_enabled:
        from SCAServer import SCAServer

        sca_server_instance = SCAServer(mqtt_out_queue)
        # Wire up fan-out: TLSServer calls sca_server_instance.broadcast_ul_data after dedup
        tls_server_instance.sca_server = sca_server_instance  # type: ignore[attr-defined]
        logger.info("SCACI interface ENABLED — listening on port %s", bssci_config.SCACI_PORT)
    else:
        logger.info("SCACI interface disabled (set SCACI_ENABLED=true to enable)")

    # Make instances available to web_main
    try:
        import web_main

        web_main.set_tls_server(tls_server_instance)
        if sca_server_instance is not None:
            web_main.set_sca_server(sca_server_instance)
    except ImportError:
        pass  # web_main not available in non-web mode

    # Use the same instance for the server
    tls_server = tls_server_instance

    # Periodic queue statistics
    async def queue_stats_reporter():
        while True:
            await asyncio.sleep(60)  # Log stats every minute
            log_all_queue_stats(queue_loggers)

    # Start the stats reporter task (keep a reference so it is not GC'd)
    stats_task = asyncio.create_task(queue_stats_reporter())
    _background_tasks.add(stats_task)
    stats_task.add_done_callback(_background_tasks.discard)

    logger.info("Starting BSSCI Service Center...")

    # Collect coroutines to run concurrently
    coros: list = [tls_server.start_server()]

    mqtt_enabled = getattr(bssci_config, "MQTT_ENABLED", True)
    if mqtt_enabled:
        mqtt_client = MQTTClient(mqtt_out_queue, mqtt_in_queue)
        coros.append(mqtt_client.start())
        logger.info("MQTT interface ENABLED — broker %s:%s", MQTT_BROKER, MQTT_PORT)
    else:
        logger.warning("MQTT interface disabled (set MQTT_ENABLED=true to enable)")

    if scaci_enabled and sca_server_instance is not None:
        coros.append(sca_server_instance.start_server())

    if not mqtt_enabled and not scaci_enabled:
        logger.warning(
            "⚠ Both MQTT and SCACI are disabled — data will not be forwarded to any external system"
        )

    logger.info("✓ Starting %d service(s) concurrently...", len(coros))

    try:
        # Start all services concurrently
        await asyncio.gather(*coros, return_exceptions=True)
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
