"""Adobe DNGPrivateData protected block parsing and rewrap helpers."""

from __future__ import annotations

from exifmodern.formats.tiff.primitives import Endian


def find_adobe_private_data_record(
    file_data: bytes,
    adobe_offset: int,
    adobe_size: int,
    record_tag: bytes,
) -> tuple[int, int, int] | None:
    end = adobe_offset + adobe_size
    pos = adobe_offset + 6
    while pos + 8 <= end:
        tag = file_data[pos : pos + 4]
        size = int.from_bytes(file_data[pos + 4 : pos + 8], "big")
        data_offset = pos + 8
        if data_offset + size > end:
            return None
        if tag == record_tag:
            return (pos, data_offset, size)
        pos = data_offset + size + (size & 1)
    return None


def adobe_makn_endian(file_data: bytes, makn_data_offset: int) -> Endian | None:
    marker = file_data[makn_data_offset : makn_data_offset + 2]
    if marker == b"II":
        return "little"
    if marker == b"MM":
        return "big"
    return None


def adobe_makn_header_length(file_data: bytes, makn_data_offset: int, makn_size: int) -> int:
    if makn_size >= 18 and file_data[makn_data_offset + 6 : makn_data_offset + 10] == (
        b"\x00\x00\x00\x01"
    ):
        return 18
    return 6


def rewrap_adobe_private_data_record(
    private_data: bytes,
    record_tag: bytes,
    replacement_value: bytes,
) -> bytes | None:
    if not private_data.startswith(b"Adobe\x00"):
        return None
    pos = 6
    records = bytearray(b"Adobe\x00")
    while pos + 8 <= len(private_data):
        tag = private_data[pos : pos + 4]
        size = int.from_bytes(private_data[pos + 4 : pos + 8], "big")
        value_offset = pos + 8
        value_end = value_offset + size
        if value_end > len(private_data):
            return None
        value = replacement_value if tag == record_tag else private_data[value_offset:value_end]
        records.extend(tag)
        records.extend(len(value).to_bytes(4, "big"))
        records.extend(value)
        if len(value) & 1:
            records.extend(b"\x00")
        pos = value_end + (size & 1)
    if pos != len(private_data):
        return None
    return bytes(records)
