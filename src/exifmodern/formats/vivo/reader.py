"""Vivo JPEG trailer reader."""

from __future__ import annotations

from exifmodern.json_types import JsonObject

VIVO_TRAILER_FOOTER = b"\xff\xff\xff\xff\x1b\x2a\x39\x48\x57\x66\x75\x84\x93\xa2\xb1"
VIVO_JSON_PREFIX = b"vivo{"


def parse_vivo_trailer_tags(data: bytes) -> JsonObject:
    if not data.endswith(VIVO_TRAILER_FOOTER):
        raise ValueError("No Vivo trailer footer found")
    prefix_offset = data.find(VIVO_JSON_PREFIX)
    if prefix_offset < 0:
        raise ValueError("No Vivo JSON payload found")
    json_offset = prefix_offset + len(b"vivo")
    json_end = data.find(b"}\x00", json_offset)
    if json_end < 0:
        raise ValueError("Unterminated Vivo JSON payload")
    return {
        "JSONInfo": data[json_offset : json_end + 1].decode("utf-8", errors="replace"),
    }
