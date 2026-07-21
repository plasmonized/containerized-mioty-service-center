"""Shared test fixtures for BSSCI Service Center."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest


# ── Config Helpers ──────────────────────────────────────────────────────────


@pytest.fixture
def sample_sensor() -> dict[str, Any]:
    """A minimal but valid sensor configuration."""
    return {
        "eui": "A1B2C3D4E5F6",
        "bidi": False,
        "nwKey": "0011223344556677",
        "shortAddr": "0001",
    }


# ── Async Queue Helpers ─────────────────────────────────────────────────────


@pytest.fixture
def mqtt_out_queue() -> asyncio.Queue[dict[str, str]]:
    """A fresh outbound asyncio.Queue for each test."""
    return asyncio.Queue()


@pytest.fixture
def mqtt_in_queue() -> asyncio.Queue[dict[str, str]]:
    """A fresh inbound asyncio.Queue for each test."""
    return asyncio.Queue()


# ── Logging Helpers ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_logger(mocker):
    """Suppress log output from the queue_logger module.

    Use this fixture in tests that instantiate QueueLogger to avoid
    log noise during test execution.
    """
    return mocker.patch("queue_logger.logger")


@pytest.fixture
def log_capture(caplog) -> Callable[[], list[dict[str, Any]]]:
    """Capture log records for assertion.

    Returns a function ``capture()`` that returns all log records
    emitted since the last call.

    Usage::

        def test_logs_something(log_capture) -> None:
            emit_log("hello")
            records = log_capture()
            assert any("hello" in r.msg for r in records)
    """
    records: list[Any] = []

    def _capture() -> list[Any]:
        nonlocal records
        new_records = list(caplog.records[len(records) :])
        records.extend(new_records)
        return new_records

    return _capture
