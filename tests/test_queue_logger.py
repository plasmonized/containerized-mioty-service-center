"""Tests for the queue_logger module — async queue monitoring.

These tests use pytest-asyncio (with ``asyncio_mode = "auto"``)
and pytest-mock to verify behaviour without real queue traffic.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import pytest

from queue_logger import QueueLogger, setup_queue_logging


class TestQueueLogger:
    """Tests for ``QueueLogger`` — individual queue monitoring."""

    async def test_initial_stats_are_zero(self, mqtt_out_queue: asyncio.Queue, mock_logger) -> None:
        """After construction, all counters should start at zero."""
        ql = QueueLogger("test", mqtt_out_queue)
        assert ql.stats["put_count"] == 0
        assert ql.stats["get_count"] == 0
        assert ql.stats["current_size"] == 0

    async def test_tracks_put_count(self, mqtt_out_queue: asyncio.Queue, mock_logger) -> None:
        """Each put() should increment the put counter."""
        ql = QueueLogger("test", mqtt_out_queue)
        await mqtt_out_queue.put("item1")
        await mqtt_out_queue.put("item2")
        assert ql.stats["put_count"] == 2

    async def test_tracks_get_count(self, mqtt_out_queue: asyncio.Queue, mock_logger) -> None:
        """Each get() should increment the get counter."""
        ql = QueueLogger("test", mqtt_out_queue)
        await mqtt_out_queue.put("item1")
        await mqtt_out_queue.put("item2")
        await mqtt_out_queue.get()
        await mqtt_out_queue.get()
        assert ql.stats["get_count"] == 2

    async def test_put_get_round_trip_preserves_item(
        self, mqtt_out_queue: asyncio.Queue, mock_logger
    ) -> None:
        """Items should survive a put/get pair correctly."""
        QueueLogger("test", mqtt_out_queue)
        await mqtt_out_queue.put({"key": "value"})
        result = await mqtt_out_queue.get()
        assert result == {"key": "value"}

    async def test_max_size_seen_tracks_peak(
        self, mqtt_out_queue: asyncio.Queue, mock_logger
    ) -> None:
        """max_size_seen should reflect the highest queue depth."""
        ql = QueueLogger("test", mqtt_out_queue)
        await mqtt_out_queue.put("a")
        await mqtt_out_queue.put("b")
        await mqtt_out_queue.put("c")
        await mqtt_out_queue.get()  # size goes 3→2
        assert ql.stats["max_size_seen"] == 3

    async def test_daily_counter_starts_at_one(
        self, mqtt_out_queue: asyncio.Queue, mock_logger
    ) -> None:
        ql = QueueLogger("test", mqtt_out_queue)
        assert ql.daily_counter == 1

    async def test_get_stats_returns_expected_keys(
        self, mqtt_out_queue: asyncio.Queue, mock_logger
    ) -> None:
        ql = QueueLogger("test", mqtt_out_queue)
        stats = ql.get_stats()
        assert "queue_name" in stats
        assert "daily_counter" in stats
        assert "put_count" in stats
        assert "get_count" in stats
        assert "current_size" in stats

    async def test_queue_name_is_stored(self, mqtt_out_queue: asyncio.Queue, mock_logger) -> None:
        ql = QueueLogger("my-queue", mqtt_out_queue)
        assert ql.queue_name == "my-queue"

    async def test_put_tracks_item_type_for_dict(
        self, mqtt_out_queue: asyncio.Queue, mock_logger
    ) -> None:
        """Putting a dict should not raise."""
        QueueLogger("test", mqtt_out_queue)
        await mqtt_out_queue.put({"a": 1})  # should not raise


class TestSetupQueueLogging:
    """Tests for ``setup_queue_logging`` helper."""

    async def test_returns_logger_for_each_queue(self) -> None:
        q1: asyncio.Queue = asyncio.Queue()
        q2: asyncio.Queue = asyncio.Queue()
        queues = {"q1": q1, "q2": q2}
        loggers = setup_queue_logging(queues)
        assert "q1" in loggers
        assert "q2" in loggers
        assert isinstance(loggers["q1"], QueueLogger)
        assert isinstance(loggers["q2"], QueueLogger)

    async def test_empty_dict_returns_empty(self) -> None:
        assert setup_queue_logging({}) == {}
