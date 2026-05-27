"""JPEG APP2 ICC profile adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.formats.icc.reader import parse_icc_header_tags, parse_icc_profile_tags
from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.json_types import JsonObject

ICC_APP2_PREFIX = b"ICC_PROFILE\x00"


@dataclass(frozen=True)
class IccChunk:
    sequence_number: int
    chunk_count: int
    data: bytes


def read_icc_header_tags(path: Path) -> JsonObject:
    return parse_icc_header_tags(read_icc_profile(path))


def read_icc_profile_tags(path: Path) -> JsonObject:
    return parse_icc_profile_tags(read_icc_profile(path))


def read_icc_profile(path: Path) -> bytes:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    chunks: list[IccChunk] = []
    for segment in jpeg_file.segments:
        if segment.marker != 0xE2:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(ICC_APP2_PREFIX) or len(payload) < len(ICC_APP2_PREFIX) + 2:
            continue
        sequence_offset = len(ICC_APP2_PREFIX)
        chunks.append(
            IccChunk(
                sequence_number=payload[sequence_offset],
                chunk_count=payload[sequence_offset + 1],
                data=payload[sequence_offset + 2 :],
            )
        )
    if not chunks:
        raise ValueError(f"No JPEG ICC APP2 segment found: {path}")
    return b"".join(chunk.data for chunk in sorted(chunks, key=lambda chunk: chunk.sequence_number))
