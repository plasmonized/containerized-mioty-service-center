"""Regression tests for MQTTClient._handle_incoming message-loop continuity.

v1.681: /register and /cmd branches previously used `return`, which
terminated the incoming handler after the first such message. All
subsequent MQTT messages were silently dropped until a reconnect.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mqtt_interface import MQTTClient


class FakeMessage:
    def __init__(self, topic: str, payload: dict[str, Any]) -> None:
        self.topic = topic
        self.payload = json.dumps(payload).encode("utf-8")


class FakeClient:
    """Minimal aiomqtt-like client yielding a fixed message sequence."""

    def __init__(self, messages: list[FakeMessage]) -> None:
        self._messages = messages
        self.subscribe = AsyncMock()

    @property
    def messages(self):
        async def _gen():
            for m in self._messages:
                yield m

        return _gen()


@pytest.fixture
def mqtt_client(
    mqtt_out_queue: asyncio.Queue,
    mqtt_in_queue: asyncio.Queue,
) -> MQTTClient:
    return MQTTClient(mqtt_out_queue, mqtt_in_queue)


def register_payload(short_addr: str) -> dict[str, Any]:
    return {
        "nwKey": "00112233445566778899AABBCCDDEEFF",
        "shortAddr": short_addr,
        "bidi": False,
    }


@pytest.mark.asyncio
async def test_two_register_messages_are_both_processed(mqtt_client: MQTTClient) -> None:
    base = mqtt_client.base_topic
    client = FakeClient(
        [
            FakeMessage(f"{base}/ep/74731D000000138B/register", register_payload("138B")),
            FakeMessage(f"{base}/ep/74731D000000139B/register", register_payload("139B")),
        ]
    )

    await mqtt_client._handle_incoming(client)  # type: ignore[arg-type]

    euis = []
    while not mqtt_client.mqtt_in_queue.empty():
        msg = mqtt_client.mqtt_in_queue.get_nowait()
        euis.append(msg["eui"])

    assert euis == ["74731D000000138B", "74731D000000139B"]


@pytest.mark.asyncio
async def test_mixed_register_cmd_config_sequence(mqtt_client: MQTTClient) -> None:
    base = mqtt_client.base_topic
    client = FakeClient(
        [
            FakeMessage(f"{base}/ep/AAAAAAAAAAAAAAAA/register", register_payload("0001")),
            FakeMessage(f"{base}/ep/BBBBBBBBBBBBBBBB/cmd", {"command": "detach"}),
            FakeMessage(f"{base}/ep/CCCCCCCCCCCCCCCC/config", register_payload("0002")),
        ]
    )

    await mqtt_client._handle_incoming(client)  # type: ignore[arg-type]

    processed = []
    while not mqtt_client.mqtt_in_queue.empty():
        processed.append(mqtt_client.mqtt_in_queue.get_nowait())

    assert len(processed) == 3
    assert processed[0]["message_type"] == "config"
    assert processed[0]["source"] == "legacy_register"
    assert processed[1]["message_type"] == "command"
    assert processed[1]["action"] == "detach"
    assert processed[2]["message_type"] == "config"
    assert processed[2]["eui"] == "CCCCCCCCCCCCCCCC"
