"""Ducky APP12 reader."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.json_types import JsonObject


def read_ducky_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xEC:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(b"Ducky"):
            continue
        return parse_ducky_payload(payload)
    raise ValueError(f"No JPEG Ducky APP12 segment found: {path}")


def parse_ducky_payload(payload: bytes) -> JsonObject:
    values: JsonObject = {}
    offset = 5
    while offset + 4 <= len(payload):
        tag = int.from_bytes(payload[offset : offset + 2], "big")
        length = int.from_bytes(payload[offset + 2 : offset + 4], "big")
        offset += 4
        if tag == 0:
            break
        if offset + length > len(payload):
            raise ValueError("Invalid JPEG Ducky APP12 block length")
        block = payload[offset : offset + length]
        add_ducky_block(values, tag, block)
        offset += length
    return values


def add_ducky_block(values: JsonObject, tag: int, block: bytes) -> None:
    if tag == 1:
        if len(block) != 4:
            raise ValueError("Invalid JPEG Ducky quality block length")
        values["Quality"] = f"{int.from_bytes(block, 'big')}%"
        return
    if tag == 3:
        values["Copyright"] = parse_ducky_utf16_text(block)


def parse_ducky_utf16_text(block: bytes) -> str:
    if len(block) < 4:
        raise ValueError("Invalid JPEG Ducky text block length")
    character_count = int.from_bytes(block[:4], "big")
    text_bytes = block[4 : 4 + character_count * 2]
    return text_bytes.decode("utf-16-be", errors="replace")
