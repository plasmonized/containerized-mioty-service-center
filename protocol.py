from typing import Any

import msgpack

IDENTIFIER = bytes("MIOTYB01", "utf-8")


def decode_messages(data: bytes) -> list[dict[str, Any]]:
    messages = []
    while len(data) > 12:
        try:
            unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
            length = int.from_bytes(data[8 : 8 + 4], byteorder="little")
            if length + 8 > len(data):
                break
            unpacker.feed(data[12 : 12 + length])
            data = data[12 + length :]
            for msg in unpacker:
                messages.append(msg)
        except Exception as e:
            print(f"[ERROR] Fehler beim Dekodieren der Nachricht: {e}")
    return messages


def decode_message(data: bytes) -> dict[str, Any]:
    """Decode a single message from bytes"""
    try:
        unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
        unpacker.feed(data)
        for msg in unpacker:
            return msg
        return {}
    except Exception as e:
        print(f"[ERROR] Error decoding message: {e}")
        return {}


def encode_message(data: dict[str, Any]) -> bytes:
    encoded_message = bytes(msgpack.packb(data))
    return encoded_message
