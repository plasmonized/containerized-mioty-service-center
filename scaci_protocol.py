"""SCACI (SC ↔ Application Center Interface) protocol codec.

Frame layout (identical to BSSCI but with "MIOTYA01" identifier):
  [8 bytes "MIOTYA01"] [4 bytes LE payload length] [msgpack payload]

Timestamps are 64-bit nanoseconds UTC.  EUIs are integers at the wire boundary.
"""

from typing import Any

import msgpack

IDENTIFIER = b"MIOTYA01"


def encode_frame(data: dict[str, Any]) -> bytes:
    """Encode a dict into a SCACI framed binary message."""
    payload = msgpack.packb(data)
    length = len(payload).to_bytes(4, byteorder="little")
    return IDENTIFIER + length + payload


def decode_frames(data: bytes) -> list[dict[str, Any]]:
    """Decode zero or more SCACI frames from a raw byte buffer.

    Returns a list of decoded message dicts.  Incomplete trailing frames are
    silently dropped (caller should accumulate data across reads).
    """
    messages: list[dict[str, Any]] = []
    while len(data) >= 12:
        if data[:8] != IDENTIFIER:
            # Skip one byte and re-scan — handles spurious leading bytes.
            data = data[1:]
            continue
        length = int.from_bytes(data[8:12], byteorder="little")
        if 12 + length > len(data):
            break  # incomplete frame
        payload_bytes = data[12 : 12 + length]
        data = data[12 + length :]
        try:
            unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
            unpacker.feed(payload_bytes)
            for msg in unpacker:
                if isinstance(msg, dict):
                    messages.append(msg)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("SCACI decode error: %s", exc)
    return messages


def eui_to_int(eui_hex: str) -> int:
    """Convert a 16-hex-char EUI string to an integer for the wire."""
    return int.from_bytes(bytes.fromhex(eui_hex), "big")


def int_to_eui(value: int) -> str:
    """Convert an integer EUI from the wire to a 16-hex-char string (uppercase)."""
    return value.to_bytes(8, "big").hex().upper()


def ns_now() -> int:
    """Return current UTC time as nanosecond integer (64-bit)."""
    import time

    return time.time_ns()
