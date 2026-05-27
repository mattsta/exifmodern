"""Print Image Matching (PrintIM) reader."""

from __future__ import annotations

from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_UNDEFINED,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)
from exifmodern.json_types import JsonObject

PRINTIM_HEADER = b"PrintIM"
EPPIM_APP6_PREFIX = b"EPPIM\x00"
EPPIM_PRINTIM_TAG_ID = 0xC4A5


def parse_printim_tags(data: bytes) -> JsonObject:
    if len(data) <= 15:
        raise ValueError("Bad PrintIM data")
    if not data.startswith(PRINTIM_HEADER):
        raise ValueError("Invalid PrintIM header")
    return {"PrintIMVersion": data[8:12].decode("latin-1", errors="replace")}


def parse_eppim_printim_tags(payload: bytes) -> JsonObject:
    if not payload.startswith(EPPIM_APP6_PREFIX):
        raise ValueError("Unrecognized EPPIM APP6 segment")
    printim_data = read_eppim_printim_data(payload[len(EPPIM_APP6_PREFIX) :])
    return parse_printim_tags(printim_data)


def read_eppim_printim_data(tiff_data: bytes) -> bytes:
    header = parse_tiff_header(tiff_data)
    ifd = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    for entry in ifd.entries:
        if entry.tag_id != EPPIM_PRINTIM_TAG_ID:
            continue
        if entry.field_type != TIFF_TYPE_UNDEFINED:
            raise ValueError("Unexpected EPPIM PrintIM TIFF field type")
        value = read_entry_value(tiff_data, entry, header.endian)
        if not isinstance(value, bytes):
            raise ValueError("Unexpected EPPIM PrintIM value")
        return value
    raise ValueError("No EPPIM PrintIM TIFF entry found")
