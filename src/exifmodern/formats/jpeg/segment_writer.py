"""Reusable JPEG APP segment replacement helpers."""

from __future__ import annotations

from exifmodern.formats.jpeg.container import JpegSegment

JPEG_SEGMENT_SIZE_BYTES = 2


def encode_jpeg_segment(marker: int, payload: bytes) -> bytes:
    if marker < 0 or marker > 0xFF:
        raise ValueError(f"Invalid JPEG marker: 0x{marker:X}")
    segment_length = len(payload) + JPEG_SEGMENT_SIZE_BYTES
    if segment_length > 0xFFFF:
        raise ValueError("Rewritten JPEG segment exceeds JPEG segment size limit.")
    return b"\xff" + bytes((marker,)) + segment_length.to_bytes(2, "big") + payload


def replace_jpeg_segment(jpeg_data: bytes, segment: JpegSegment, payload: bytes) -> bytes:
    segment_end = segment.payload_offset + segment.payload_length
    rewritten_segment = encode_jpeg_segment(segment.marker, payload)
    return jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:]
