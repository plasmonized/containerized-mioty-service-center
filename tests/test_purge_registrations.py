"""Tests for TLSServer._purge_bs_registrations (v1.685 reconnect re-attach fix)."""

from typing import Any

import pytest

from TLSServer import TLSServer


@pytest.fixture()
def server() -> TLSServer:
    srv = TLSServer.__new__(TLSServer)
    srv.registered_sensors = {}
    return srv


def _reg(base_stations: list[str]) -> dict[str, Any]:
    return {"status": "registered", "base_stations": list(base_stations)}


def test_purge_removes_only_target_bs(server: TLSServer) -> None:
    server.registered_sensors = {
        "AAAA": _reg(["BS1", "BS2"]),
        "BBBB": _reg(["BS2"]),
        "CCCC": _reg(["BS1"]),
    }

    purged = server._purge_bs_registrations("BS1")

    assert purged == 2
    assert server.registered_sensors["AAAA"]["base_stations"] == ["BS2"]
    assert server.registered_sensors["BBBB"]["base_stations"] == ["BS2"]
    assert server.registered_sensors["CCCC"]["base_stations"] == []


def test_purge_is_case_insensitive(server: TLSServer) -> None:
    server.registered_sensors = {"AAAA": _reg(["bs1abc"])}

    assert server._purge_bs_registrations("BS1ABC") == 1
    assert server.registered_sensors["AAAA"]["base_stations"] == []


def test_purge_skips_failure_entries(server: TLSServer) -> None:
    server.registered_sensors = {"AAAA_failure": _reg(["BS1"])}

    assert server._purge_bs_registrations("BS1") == 0
    assert server.registered_sensors["AAAA_failure"]["base_stations"] == ["BS1"]


def test_purge_no_match_returns_zero(server: TLSServer) -> None:
    server.registered_sensors = {"AAAA": _reg(["BS2"])}

    assert server._purge_bs_registrations("BS1") == 0
    assert server.registered_sensors["AAAA"]["base_stations"] == ["BS2"]


def test_purge_enables_reattach_skip_logic(server: TLSServer) -> None:
    """After purge, the attach_file skip condition must no longer hold."""
    server.registered_sensors = {"AAAA": _reg(["BS1"])}
    server._purge_bs_registrations("BS1")

    reg_info = server.registered_sensors["AAAA"]
    skip = reg_info.get("status") == "registered" and "BS1" in reg_info.get("base_stations", [])
    assert skip is False
