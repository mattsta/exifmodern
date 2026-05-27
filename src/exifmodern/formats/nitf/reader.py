"""NITF APP6 binary table reader."""

from __future__ import annotations

from exifmodern.json_types import JsonObject

NITF_APP6_PREFIX = b"NITF\x00"
NITF_APP6_SCALAR_PAYLOAD_SIZE = 18
NITF_APP6_READ_SIZE = len(NITF_APP6_PREFIX) + NITF_APP6_SCALAR_PAYLOAD_SIZE


def parse_nitf_app6_tags(payload: bytes) -> JsonObject:
    if not payload.startswith(NITF_APP6_PREFIX):
        raise ValueError("No NITF APP6 payload found")
    data = payload[len(NITF_APP6_PREFIX) :]
    if len(data) < NITF_APP6_SCALAR_PAYLOAD_SIZE:
        raise ValueError("Truncated NITF APP6 data")
    return {
        "NITFVersion": nitf_version(data[0], data[1]),
        "ImageFormat": nitf_image_format(data[2]),
        "BlocksPerRow": int.from_bytes(data[3:5], "big"),
        "BlocksPerColumn": int.from_bytes(data[5:7], "big"),
        "ImageColor": nitf_image_color(data[7]),
        "BitDepth": data[8],
        "ImageClass": nitf_image_class(data[9]),
        "JPEGProcess": nitf_jpeg_process(data[10]),
        "Quality": data[11],
        "StreamColor": nitf_image_color(data[12]),
        "StreamBitDepth": data[13],
        "Flags": f"0x{int.from_bytes(data[14:18], 'big'):x}",
    }


def nitf_version(major: int, minor: int) -> float:
    return major + minor / 100


def nitf_image_format(value: int) -> str | int:
    if chr(value) == "B":
        return "IMode B"
    return value


def nitf_image_color(value: int) -> str | int:
    return "Monochrome" if value == 0 else value


def nitf_image_class(value: int) -> str | int:
    return {
        0: "General Purpose",
        4: "Tactical Imagery",
    }.get(value, value)


def nitf_jpeg_process(value: int) -> str | int:
    return {
        1: "Baseline sequential DCT, Huffman coding, 8-bit samples",
        4: "Extended sequential DCT, Huffman coding, 12-bit samples",
    }.get(value, value)
