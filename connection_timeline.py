import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any


class ConnectionTimeline:
    """Thread-safe in-memory timeline for connectivity events."""

    def __init__(self, max_entries: int = 1000) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self._lock = threading.RLock()

    def add_event(
        self,
        event: str,
        *,
        correlation_id: str | None = None,
        bs_eui: str | None = None,
        sensor_eui: str | None = None,
        op_id: int | None = None,
        details: str | None = None,
    ) -> None:
        entry = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "event": event,
            "correlation_id": correlation_id,
            "bs_eui": bs_eui,
            "sensor_eui": sensor_eui,
            "op_id": op_id,
            "details": details,
        }
        with self._lock:
            self._entries.append(entry)

    def get_entries(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._entries)[-limit:]
