"""Tests for the SCACI protocol codec and message builders."""

from __future__ import annotations

from typing import Any, ClassVar

import msgpack
import pytest

from scaci_messages import (
    build_con_complete,
    build_con_response,
    build_ep_stat,
    build_ping_response,
    build_reg_complete,
    build_reg_response,
    build_ul_data,
)
from scaci_protocol import (
    IDENTIFIER,
    decode_frames,
    encode_frame,
    eui_to_int,
    int_to_eui,
    ns_now,
)

# ── encode_frame / decode_frames round-trip ──────────────────────────────────


class TestEncodeDecodeRoundTrip:
    def test_single_message_roundtrip(self) -> None:
        msg = {"command": "ping", "opId": 1}
        result = decode_frames(encode_frame(msg))
        assert result == [msg]

    def test_multiple_messages_roundtrip(self) -> None:
        msgs = [
            {"command": "con", "opId": 0},
            {"command": "conRsp", "opId": 0},
        ]
        data = b"".join(encode_frame(m) for m in msgs)
        assert decode_frames(data) == msgs

    def test_empty_buffer_returns_empty_list(self) -> None:
        assert decode_frames(b"") == []

    def test_incomplete_frame_returns_empty(self) -> None:
        # Only header, no payload
        data = IDENTIFIER + (10).to_bytes(4, "little") + b"\x01\x02"
        assert decode_frames(data) == []

    def test_identifier_is_miotya01(self) -> None:
        assert IDENTIFIER == b"MIOTYA01"

    def test_frame_starts_with_identifier(self) -> None:
        frame = encode_frame({"command": "ping"})
        assert frame[:8] == b"MIOTYA01"

    def test_length_field_is_little_endian(self) -> None:
        payload = msgpack.packb({"command": "ping"})
        frame = encode_frame({"command": "ping"})
        length_in_frame = int.from_bytes(frame[8:12], byteorder="little")
        assert length_in_frame == len(payload)

    def test_garbage_before_identifier_is_skipped(self) -> None:
        msg = {"command": "ping", "opId": 5}
        data = b"\xde\xad\xbe\xef" + encode_frame(msg)
        result = decode_frames(data)
        assert msg in result

    def test_unicode_payload(self) -> None:
        msg = {"command": "status", "info": "üñîçødé"}
        assert decode_frames(encode_frame(msg)) == [msg]


# ── EUI helpers ──────────────────────────────────────────────────────────────


class TestEuiHelpers:
    EUI_HEX: ClassVar[str] = "74731D000000138B"
    EUI_INT: ClassVar[int] = 0x74731D000000138B

    def test_eui_to_int(self) -> None:
        assert eui_to_int(self.EUI_HEX) == self.EUI_INT

    def test_int_to_eui_uppercase(self) -> None:
        result = int_to_eui(self.EUI_INT)
        assert result == self.EUI_HEX

    def test_round_trip(self) -> None:
        assert int_to_eui(eui_to_int(self.EUI_HEX)) == self.EUI_HEX

    def test_zero_eui(self) -> None:
        assert eui_to_int("0000000000000000") == 0
        assert int_to_eui(0) == "0000000000000000"


# ── ns_now ───────────────────────────────────────────────────────────────────


class TestNsNow:
    def test_returns_int(self) -> None:
        assert isinstance(ns_now(), int)

    def test_monotonically_increasing(self) -> None:
        t1 = ns_now()
        t2 = ns_now()
        assert t2 >= t1

    def test_reasonable_magnitude(self) -> None:
        # Should be somewhere around 2024-2030 in nanoseconds
        ns = ns_now()
        assert ns > 1_700_000_000_000_000_000  # after 2023-11-14
        assert ns < 2_000_000_000_000_000_000  # before ~2033


# ── message builders ─────────────────────────────────────────────────────────


class TestConResponse:
    def test_command_field(self) -> None:
        assert build_con_response(0)["command"] == "conRsp"

    def test_fresh_session(self) -> None:
        r = build_con_response(0)
        assert r["snResume"] is False
        assert isinstance(r["snScUuid"], list)
        assert len(r["snScUuid"]) == 16

    def test_unique_session_uuids(self) -> None:
        r1 = build_con_response(0)
        r2 = build_con_response(0)
        assert r1["snScUuid"] != r2["snScUuid"]

    def test_op_id_echoed(self) -> None:
        assert build_con_response(42)["opId"] == 42


class TestPingResponse:
    def test_command(self) -> None:
        assert build_ping_response(7)["command"] == "pingRsp"

    def test_op_id(self) -> None:
        assert build_ping_response(7)["opId"] == 7


class TestRegMessages:
    def test_reg_response_rc_zero(self) -> None:
        r = build_reg_response(1)
        assert r["command"] == "regRsp"
        assert r["rc"] == 0

    def test_reg_complete(self) -> None:
        assert build_reg_complete(1)["command"] == "regCmp"


class TestUlData:
    def test_required_fields(self) -> None:
        msg = build_ul_data(op_id=-1, ep_eui=0xDEAD, rx_time=12345678, data=[1, 2, 3])
        assert msg["command"] == "ulData"
        assert msg["epEui"] == 0xDEAD
        assert msg["rxTime"] == 12345678
        assert msg["data"] == [1, 2, 3]

    def test_negative_op_id(self) -> None:
        msg = build_ul_data(op_id=-5, ep_eui=1, rx_time=0, data=[])
        assert msg["opId"] == -5


class TestEpStat:
    def test_online(self) -> None:
        msg = build_ep_stat(op_id=-1, ep_eui=0xABCD, online=True)
        assert msg["command"] == "epStat"
        assert msg["online"] is True

    def test_offline_with_last_seen(self) -> None:
        ts = ns_now()
        msg = build_ep_stat(op_id=-2, ep_eui=0xABCD, online=False, last_seen_ns=ts)
        assert msg["online"] is False
        assert msg["lastSeen"] == ts

    def test_no_last_seen_when_none(self) -> None:
        msg = build_ep_stat(op_id=-1, ep_eui=1, online=True, last_seen_ns=None)
        assert "lastSeen" not in msg
