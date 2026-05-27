"""JPEG APP1 helpers for standard and extended XMP metadata segments."""

from __future__ import annotations

from exifmodern.formats.jpeg.app_segments.xmp import (
    XMP_APP1_PREFIX,
    XMP_EXTENDED_APP1_PREFIX,
)
from exifmodern.formats.jpeg.container import JpegSegment, scan_jpeg_segments
from exifmodern.formats.jpeg.exif_app1 import EXIF_APP1_PREFIX, segment_payload


def xmp_app1_segments(jpeg_data: bytes) -> tuple[JpegSegment, ...]:
    segments: list[JpegSegment] = []
    for segment in scan_jpeg_segments(jpeg_data):
        if segment.marker != 0xE1:
            continue
        payload = segment_payload(jpeg_data, segment)
        if payload.startswith(XMP_APP1_PREFIX) or payload.startswith(XMP_EXTENDED_APP1_PREFIX):
            segments.append(segment)
    return tuple(segments)


def first_standard_xmp_app1_segment(jpeg_data: bytes) -> JpegSegment | None:
    for segment in scan_jpeg_segments(jpeg_data):
        if segment.marker != 0xE1:
            continue
        if segment_payload(jpeg_data, segment).startswith(XMP_APP1_PREFIX):
            return segment
    return None


def extended_xmp_app1_segments(jpeg_data: bytes) -> tuple[JpegSegment, ...]:
    segments: list[JpegSegment] = []
    for segment in scan_jpeg_segments(jpeg_data):
        if segment.marker != 0xE1:
            continue
        if segment_payload(jpeg_data, segment).startswith(XMP_EXTENDED_APP1_PREFIX):
            segments.append(segment)
    return tuple(segments)


def xmp_app1_insertion_offset(jpeg_data: bytes) -> int:
    insertion_offset = 2
    for segment in scan_jpeg_segments(jpeg_data):
        if segment.marker == 0xE0:
            insertion_offset = segment.payload_offset + segment.payload_length
            continue
        if segment.marker == 0xE1 and segment_payload(jpeg_data, segment).startswith(
            EXIF_APP1_PREFIX
        ):
            insertion_offset = segment.payload_offset + segment.payload_length
            continue
        if segment.marker == 0xED:
            insertion_offset = segment.payload_offset + segment.payload_length
            continue
        break
    return insertion_offset


def encode_xmp_app1_segment(payload: bytes) -> bytes:
    segment_length = len(payload) + 2
    if segment_length > 0xFFFF:
        raise ValueError("Rewritten XMP APP1 segment exceeds JPEG segment size limit.")
    return b"\xff\xe1" + segment_length.to_bytes(2, "big") + payload
