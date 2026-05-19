import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any


class JsonUTCFormatter(logging.Formatter):
    """Structured JSON formatter with UTC timestamps."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp_utc": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "component": record.name,
            "event": getattr(record, "event", None),
            "op_id": getattr(record, "op_id", None),
            "bs_eui": getattr(record, "bs_eui", None),
            "sensor_eui": getattr(record, "sensor_eui", None),
            "correlation_id": getattr(record, "correlation_id", None),
            "error_code": getattr(record, "error_code", None),
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(default_component: str | None = None) -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Reset handlers for deterministic formatter setup.
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(JsonUTCFormatter())
    root_logger.addHandler(stream_handler)

    if default_component:
        logging.getLogger(default_component).setLevel(level)


def new_correlation_id() -> str:
    return str(uuid.uuid4())
