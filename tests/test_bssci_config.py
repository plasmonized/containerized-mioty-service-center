"""Tests for the bssci_config module — environment-based configuration.

These tests use monkeypatch to simulate environment variables without
affecting the actual environment.
"""

from __future__ import annotations

from typing import Any

import pytest


class TestConfigDefaults:
    """Verifies that config constants fall back to correct defaults
    when no environment variables are set."""

    def test_listen_host_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LISTEN_HOST", raising=False)
        # Re-import to pick up the patched env
        import importlib
        import bssci_config as cfg
        importlib.reload(cfg)
        assert cfg.LISTEN_HOST == "0.0.0.0"

    def test_listen_port_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LISTEN_PORT", raising=False)
        import importlib
        import bssci_config as cfg
        importlib.reload(cfg)
        assert cfg.LISTEN_PORT == 16018

    def test_mqtt_broker_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MQTT_BROKER", raising=False)
        import importlib
        import bssci_config as cfg
        importlib.reload(cfg)
        assert cfg.MQTT_BROKER == "localhost"

    def test_mqtt_port_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MQTT_PORT", raising=False)
        import importlib
        import bssci_config as cfg
        importlib.reload(cfg)
        assert cfg.MQTT_PORT == 1883

    def test_base_topic_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BASE_TOPIC", raising=False)
        import importlib
        import bssci_config as cfg
        importlib.reload(cfg)
        assert cfg.BASE_TOPIC == "bssci/"

    def test_web_port_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WEB_PORT", raising=False)
        import importlib
        import bssci_config as cfg
        importlib.reload(cfg)
        assert cfg.WEB_PORT == 5000


class TestConfigOverrides:
    """Verifies that environment variables override defaults correctly."""

    def test_listen_port_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LISTEN_PORT", "17000")
        import importlib
        import bssci_config as cfg
        importlib.reload(cfg)
        assert cfg.LISTEN_PORT == 17000

    def test_mqtt_broker_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MQTT_BROKER", "10.0.0.1")
        import importlib
        import bssci_config as cfg
        importlib.reload(cfg)
        assert cfg.MQTT_BROKER == "10.0.0.1"

    def test_boolean_web_debug_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WEB_DEBUG", "true")
        import importlib
        import bssci_config as cfg
        importlib.reload(cfg)
        assert cfg.WEB_DEBUG is True

    def test_boolean_web_debug_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WEB_DEBUG", "false")
        import importlib
        import bssci_config as cfg
        importlib.reload(cfg)
        assert cfg.WEB_DEBUG is False

    def test_int_mqtt_port_invalid_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When MQTT_PORT is not a valid int, int() will raise.
        This tests that the code handles this gracefully (current code
        will crash on invalid int — this documents the current behaviour)."""
        monkeypatch.setenv("MQTT_PORT", "not-a-number")
        import importlib
        import bssci_config as cfg
        with pytest.raises(ValueError):
            importlib.reload(cfg)
