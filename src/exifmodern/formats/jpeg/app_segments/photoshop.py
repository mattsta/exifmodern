"""JPEG APP13 Photoshop Image Resource Block adapter."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.formats.photoshop.reader import (
    PHOTOSHOP_APP13_PREFIX,
    PhotoshopRenderedTag,
    parse_current_iptc_digest_tags,
    parse_photoshop_app13_rendered_tag_sequence,
    parse_photoshop_iptc_tags,
    parse_photoshop_print_scale_tags,
    parse_photoshop_quality_tags,
    parse_photoshop_resolution_tags,
    parse_photoshop_slice_tags,
    parse_photoshop_tags,
    parse_photoshop_version_tags,
)
from exifmodern.json_types import JsonObject


def read_photoshop_core_tags(path: Path) -> JsonObject:
    return parse_photoshop_tags(read_photoshop_app13_payload(path))


def read_photoshop_resolution_tags(path: Path) -> JsonObject:
    return parse_photoshop_resolution_tags(read_photoshop_app13_payload(path))


def read_photoshop_print_scale_tags(path: Path) -> JsonObject:
    return parse_photoshop_print_scale_tags(read_photoshop_app13_payload(path))


def read_photoshop_slice_tags(path: Path) -> JsonObject:
    return parse_photoshop_slice_tags(read_photoshop_app13_payload(path))


def read_photoshop_version_tags(path: Path) -> JsonObject:
    return parse_photoshop_version_tags(read_photoshop_app13_payload(path))


def read_photoshop_quality_tags(path: Path) -> JsonObject:
    return parse_photoshop_quality_tags(read_photoshop_app13_payload(path))


def read_iptc_tags(path: Path) -> JsonObject:
    return parse_photoshop_iptc_tags(read_photoshop_app13_payload(path))


def read_current_iptc_digest_tags(path: Path) -> JsonObject:
    return parse_current_iptc_digest_tags(read_photoshop_app13_payload(path))


def read_photoshop_app13_rendered_tag_sequence(path: Path) -> tuple[PhotoshopRenderedTag, ...]:
    return parse_photoshop_app13_rendered_tag_sequence(read_photoshop_app13_payload(path))


def read_photoshop_app13_payload(path: Path) -> bytes:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xED:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if payload.startswith(PHOTOSHOP_APP13_PREFIX):
            return payload
    raise ValueError(f"No JPEG Photoshop APP13 segment found: {path}")
