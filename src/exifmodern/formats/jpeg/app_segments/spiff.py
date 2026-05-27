"""SPIFF APP8 reader."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.app_segments.common import jfif_resolution_unit
from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.json_types import JsonObject


def read_spiff_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    spiff_segment_seen = False
    for segment in jpeg_file.segments:
        if segment.marker != 0xE8:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(b"SPIFF\x00"):
            continue
        spiff_segment_seen = True
        return parse_spiff_payload(payload)
    if spiff_segment_seen:
        raise ValueError(f"No readable JPEG SPIFF APP8 segment found: {path}")
    raise ValueError(f"No JPEG SPIFF APP8 segment found: {path}")


def parse_spiff_payload(payload: bytes) -> JsonObject:
    if len(payload) < 32:
        raise ValueError("Truncated JPEG SPIFF APP8 segment")
    return {
        "SPIFFVersion": spiff_version(payload[6], payload[7]),
        "ProfileID": spiff_profile_id(payload[8]),
        "ColorComponents": payload[9],
        "ImageHeight": int.from_bytes(payload[12:16], "big"),
        "ImageWidth": int.from_bytes(payload[16:20], "big"),
        "ColorSpace": spiff_color_space(payload[20]),
        "BitsPerSample": payload[21],
        "Compression": spiff_compression(payload[22]),
        "ResolutionUnit": jfif_resolution_unit(payload[23]),
        "YResolution": int.from_bytes(payload[24:28], "big"),
        "XResolution": int.from_bytes(payload[28:32], "big"),
    }


def spiff_version(major: int, minor: int) -> float:
    return major + minor / 10


def spiff_profile_id(value: int) -> str | int:
    return {
        0: "Not Specified",
        1: "Continuous-tone Base",
        2: "Continuous-tone Progressive",
        3: "Bi-level Facsimile",
        4: "Continuous-tone Facsimile",
    }.get(value, value)


def spiff_color_space(value: int) -> str | int:
    return {
        0: "Bi-level",
        1: "YCbCr, ITU-R BT 709, video",
        2: "No color space specified",
        3: "YCbCr, ITU-R BT 601-1, RGB",
        4: "YCbCr, ITU-R BT 601-1, video",
        8: "Gray-scale",
        9: "PhotoYCC",
        10: "RGB",
        11: "CMY",
        12: "CMYK",
        13: "YCCK",
        14: "CIELab",
    }.get(value, value)


def spiff_compression(value: int) -> str | int:
    return {
        0: "Uncompressed, interleaved, 8 bits per sample",
        1: "Modified Huffman",
        2: "Modified READ",
        3: "Modified Modified READ",
        4: "JBIG",
        5: "JPEG",
    }.get(value, value)
