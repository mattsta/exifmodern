"""Reusable JPEG EXIF APP1 segment helpers."""

from __future__ import annotations

from exifmodern.formats.jpeg.container import JpegSegment, scan_jpeg_segments

EXIF_APP1_PREFIX = b"Exif\x00\x00"
JPEG_APP1_MARKER = 0xE1
JPEG_SEGMENT_SIZE_BYTES = 2


def find_exif_app1_segment(jpeg_data: bytes) -> JpegSegment:
    segment = find_exif_app1_segment_or_none(jpeg_data)
    if segment is None:
        raise ValueError("JPEG does not contain an EXIF APP1 segment.")
    return segment


def find_exif_app1_segment_or_none(jpeg_data: bytes) -> JpegSegment | None:
    for segment in scan_jpeg_segments(jpeg_data):
        if segment.marker != JPEG_APP1_MARKER:
            continue
        if segment_payload(jpeg_data, segment).startswith(EXIF_APP1_PREFIX):
            return segment
    return None


def exif_app1_insertion_offset(jpeg_data: bytes) -> int:
    segments = scan_jpeg_segments(jpeg_data)
    if not segments:
        return 2
    first_segment = segments[0]
    if first_segment.marker == 0xE0:
        return first_segment.payload_offset + first_segment.payload_length
    return 2


def segment_payload(jpeg_data: bytes, segment: JpegSegment) -> bytes:
    return jpeg_data[segment.payload_offset : segment.payload_offset + segment.payload_length]


def encode_app1_segment(payload: bytes) -> bytes:
    segment_length = len(payload) + JPEG_SEGMENT_SIZE_BYTES
    if segment_length > 0xFFFF:
        raise ValueError("Rewritten EXIF APP1 segment exceeds JPEG segment size limit.")
    return b"\xff\xe1" + segment_length.to_bytes(2, "big") + payload
