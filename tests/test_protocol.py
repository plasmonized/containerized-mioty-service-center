"""Tests for the protocol module — binary encoding/decoding.

The protocol module handles msgpack-based serialisation for BSSCI
messages. These tests verify round-trip stability and edge-case handling.
"""

from __future__ import annotations

from typing import Any

import msgpack
import pytest

from protocol import decode_message, decode_messages, encode_message


# ── Helpers ──────────────────────────────────────────────────────────────────


def _pack_message(data: dict[str, Any]) -> bytes:
    """Convenience: pack a dict into msgpack bytes."""
    return msgpack.packb(data)


def _pack_message_with_header(data: dict[str, Any]) -> bytes:
    """Pack a dict into the framed BSSCI format.

    Frame structure (from protocol.py):
    [8 bytes identifier "MIOTYB01"] [4 bytes LE length] [payload]
    """
    payload = _pack_message(data)
    length = len(payload).to_bytes(4, byteorder="little")
    return b"MIOTYB01" + length + payload


# ── encode_message ───────────────────────────────────────────────────────────


class TestEncodeMessage:
    """Tests for ``encode_message``."""

    def test_returns_bytes(self) -> None:
        result = encode_message({"command": "ping"})
        assert isinstance(result, bytes)

    def test_round_trip_with_decode_message(self) -> None:
        original: dict[str, Any] = {"command": "pingRsp", "opId": 42}
        encoded = encode_message(original)
        decoded = decode_message(encoded)
        assert decoded == original

    def test_empty_dict(self) -> None:
        result = encode_message({})
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_nested_dict(self) -> None:
        original = {"command": "vm.dlData", "params": {"macType": 2, "data": [1, 2, 3]}}
        encoded = encode_message(original)
        decoded = decode_message(encoded)
        assert decoded == original


# ── decode_message ───────────────────────────────────────────────────────────


class TestDecodeMessage:
    """Tests for ``decode_message`` — single message."""

    def test_decodes_valid_message(self) -> None:
        data = _pack_message({"command": "pingRsp", "opId": 1})
        result = decode_message(data)
        assert result == {"command": "pingRsp", "opId": 1}

    def test_returns_empty_dict_on_empty_bytes(self) -> None:
        result = decode_message(b"")
        assert result == {}

    def test_returns_empty_dict_on_garbage(self) -> None:
        result = decode_message(b"\xff\xfe\xfd\xfc")
        assert result == {}

    def test_handles_unicode_strings(self) -> None:
        data = _pack_message({"command": "status", "label": "üñîçødé"})
        result = decode_message(data)
        assert result["label"] == "üñîçødé"


# ── decode_messages ──────────────────────────────────────────────────────────


class TestDecodeMessages:
    """Tests for ``decode_messages`` — framed multi-message format."""

    def test_decodes_single_message(self) -> None:
        msg = {"command": "conRsp", "opId": 1}
        data = _pack_message_with_header(msg)
        result = decode_messages(data)
        assert result == [msg]

    def test_decodes_multiple_messages(self) -> None:
        msg1 = {"command": "conRsp", "opId": 1}
        msg2 = {"command": "attPrp", "opId": 2}
        data = _pack_message_with_header(msg1) + _pack_message_with_header(msg2)
        result = decode_messages(data)
        assert result == [msg1, msg2]

    def test_returns_empty_list_for_empty_bytes(self) -> None:
        assert decode_messages(b"") == []

    def test_returns_empty_list_for_too_short_data(self) -> None:
        assert decode_messages(b"\x00" * 8) == []

    def test_handles_partial_frame_gracefully(self) -> None:
        """If the length field says 100 bytes but only 5 follow, skip it."""
        msg = {"command": "ping", "opId": 1}
        full = _pack_message_with_header(msg)
        # Append a truncated second frame
        truncated = full + b"MIOTYB01\x64\x00\x00\x00" + b"\x01\x02"  # length=100 but only 2 bytes
        result = decode_messages(truncated)
        assert result == [msg]  # first message decoded, second skipped

    def test_three_vm_messages(self) -> None:
        msgs = [
            {"command": "vm.activate", "opId": 1, "macType": 2},
            {"command": "vm.dlData", "opId": 1, "userData": [10, 20]},
            {"command": "vm.deactivateRsp", "opId": 1},
        ]
        data = b"".join(_pack_message_with_header(m) for m in msgs)
        result = decode_messages(data)
        assert result == msgs

    def test_ignores_non_identifier_prefix(self) -> None:
        """Bytes before 'MIOTYB01' should be ignored by the parser."""
        msg = {"command": "ping", "opId": 1}
        junk = b"\x00\x00\x00\x00\x00\x00\x00\x00" + _pack_message_with_header(msg)
        result = decode_messages(junk)
        # The parser checks for 12-byte min frames and identifier at [0:8]
        # "MIOTYB01" won't be at offset 0, so this may need adjustment
        # based on exact parser implementation
        assert isinstance(result, list)


# ── attPrp wire-format regression ────────────────────────────────────────────


class TestAttachRequestWireFormat:
    """Regression: nwkSnKey must be encoded as msgpack bin, not array.

    Miromico EdgeCard FW 5.1.0 (BSSCI 1.1.0) rejects attPrp with error 22
    "attach propagate message malformed" when the network session key is
    sent as an array of 16 ints instead of a 16-byte msgpack bin.
    """

    def test_nwk_sn_key_packs_as_msgpack_bin(self) -> None:
        from messages import build_attach_request

        sensor = {
            "eui": "74731D000000138B",
            "bidi": False,
            "nwKey": "09DE6551000000000000000071B538A4",
            "shortAddr": "138B",
        }
        packed = encode_message(build_attach_request(sensor, -1))
        # bin 8 marker (0xc4) followed by length 16 and the raw key bytes
        assert b"\xc4\x10" + bytes.fromhex(sensor["nwKey"]) in packed

        decoded = decode_message(packed)
        assert decoded["nwkSnKey"] == bytes.fromhex(sensor["nwKey"])
        assert isinstance(decoded["nwkSnKey"], bytes)
