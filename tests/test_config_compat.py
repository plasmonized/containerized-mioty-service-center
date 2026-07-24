"""Tests for config_compat.get_config — .env fallback for stale bssci_config.py."""

import config_compat
from config_compat import get_config


def test_prefers_module_attribute(monkeypatch):
    monkeypatch.setattr(config_compat.bssci_config, "SCACI_ENABLED", True, raising=False)
    monkeypatch.setenv("SCACI_ENABLED", "false")
    assert get_config("SCACI_ENABLED", False) is True


def test_falls_back_to_env_bool(monkeypatch):
    monkeypatch.delattr(config_compat.bssci_config, "SCACI_ENABLED", raising=False)
    monkeypatch.setenv("SCACI_ENABLED", "true")
    assert get_config("SCACI_ENABLED", False) is True
    monkeypatch.setenv("SCACI_ENABLED", "false")
    assert get_config("SCACI_ENABLED", False) is False


def test_falls_back_to_env_int(monkeypatch):
    monkeypatch.delattr(config_compat.bssci_config, "SCACI_PORT", raising=False)
    monkeypatch.setenv("SCACI_PORT", "17000")
    assert get_config("SCACI_PORT", 16019) == 17000


def test_invalid_int_uses_default(monkeypatch):
    monkeypatch.delattr(config_compat.bssci_config, "SCACI_PORT", raising=False)
    monkeypatch.setenv("SCACI_PORT", "not-a-number")
    assert get_config("SCACI_PORT", 16019) == 16019


def test_missing_everywhere_uses_default(monkeypatch):
    monkeypatch.delattr(config_compat.bssci_config, "SCACI_HOST", raising=False)
    monkeypatch.delenv("SCACI_HOST", raising=False)
    assert get_config("SCACI_HOST", "0.0.0.0") == "0.0.0.0"


def test_string_passthrough(monkeypatch):
    monkeypatch.delattr(config_compat.bssci_config, "SCACI_HOST", raising=False)
    monkeypatch.setenv("SCACI_HOST", "127.0.0.1")
    assert get_config("SCACI_HOST", "0.0.0.0") == "127.0.0.1"
