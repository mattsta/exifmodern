"""Canon OriginalDecisionData reader translated from ExifTool ReadODD.

ExifTool stores this behind a RawConv helper because the value is not in the
normal MakerNote value stream. It is a file-offset read through the runtime RAF
cursor, so the modern boundary accepts explicit file bytes and offset instead
of reaching through global parser state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.tiff.primitives import Endian, read_u32

type OriginalDecisionDataStatus = Literal[
    "ok",
    "no_offset",
    "invalid",
    "unsupported_version",
]
type OriginalDecisionDataSliceReader = Callable[[int, int], bytes | None]


@dataclass(frozen=True)
class OriginalDecisionDataReadResult:
    status: OriginalDecisionDataStatus
    data: bytes | None
    version: int | None
    byte_order: Endian | None
    warning: str | None


def read_original_decision_data(
    file_data: bytes,
    offset: int,
    current_byte_order: Endian = "little",
) -> OriginalDecisionDataReadResult:
    """Read a Canon OriginalDecisionData block at an explicit file offset.

    This mirrors `Image::ExifTool::Canon::ReadODD`: empty offsets are silent
    no-ops, invalid reachable blocks warn, versions 1/2 use the record-count
    layout, and version 3 uses the newer three-length-field layout.
    """

    return read_original_decision_data_from_slices(
        slice_reader=lambda slice_offset, length: read_slice(file_data, slice_offset, length),
        offset=offset,
        current_byte_order=current_byte_order,
    )


def read_original_decision_data_from_slices(
    slice_reader: OriginalDecisionDataSliceReader,
    offset: int,
    current_byte_order: Endian = "little",
) -> OriginalDecisionDataReadResult:
    """Read Canon OriginalDecisionData through explicit bounded byte slices."""

    if offset <= 0:
        return OriginalDecisionDataReadResult(
            status="no_offset",
            data=None,
            version=None,
            byte_order=None,
            warning=None,
        )
    header = slice_reader(offset, 8)
    if header is None or not has_original_decision_data_signature(header):
        return invalid_original_decision_data()

    version, byte_order = read_version_with_exiftool_toggle(header, current_byte_order)
    if version in (1, 2):
        return read_version_1_or_2_data(slice_reader, offset, version, byte_order)
    if version == 3:
        return read_version_3_data(slice_reader, offset, byte_order)
    return OriginalDecisionDataReadResult(
        status="unsupported_version",
        data=None,
        version=version,
        byte_order=byte_order,
        warning=f"Unsupported original decision data version {version}",
    )


def has_original_decision_data_signature(header: bytes) -> bool:
    return len(header) == 8 and header[:4] == b"\xff\xff\xff\xff" and header[5:7] == b"\x00\x00"


def read_version_with_exiftool_toggle(
    header: bytes,
    current_byte_order: Endian,
) -> tuple[int, Endian]:
    version = read_u32(header, 4, current_byte_order)
    if version <= 20:
        return version, current_byte_order
    toggled_byte_order = toggle_byte_order(current_byte_order)
    return read_u32(header, 4, toggled_byte_order), toggled_byte_order


def toggle_byte_order(byte_order: Endian) -> Endian:
    return "big" if byte_order == "little" else "little"


def read_version_1_or_2_data(
    slice_reader: OriginalDecisionDataSliceReader,
    offset: int,
    version: int,
    byte_order: Endian,
) -> OriginalDecisionDataReadResult:
    header_and_digest = slice_reader(offset, 32)
    if header_and_digest is None:
        return invalid_original_decision_data(version, byte_order)
    count = read_u32(header_and_digest, 28, byte_order)
    if count <= 0 or count >= 20:
        return invalid_original_decision_data(version, byte_order)
    record_bytes = slice_reader(offset + 32, count * 32)
    if record_bytes is None:
        return invalid_original_decision_data(version, byte_order)
    return OriginalDecisionDataReadResult(
        status="ok",
        data=header_and_digest + record_bytes,
        version=version,
        byte_order=byte_order,
        warning=None,
    )


def read_version_3_data(
    slice_reader: OriginalDecisionDataSliceReader,
    offset: int,
    byte_order: Endian,
) -> OriginalDecisionDataReadResult:
    cursor = offset + 8
    output = bytearray(slice_reader(offset, 8) or b"")
    for index in range(3):
        length_word = slice_reader(cursor, 4)
        if length_word is None:
            return invalid_original_decision_data(3, byte_order)
        cursor += 4
        output.extend(length_word)
        chunk_length = read_u32(length_word, 0, byte_order)
        if index == 2 and chunk_length >= 4:
            chunk_length -= 4
        if chunk_length > 0x10000:
            return invalid_original_decision_data(3, byte_order)
        chunk = slice_reader(cursor, chunk_length)
        if chunk is None:
            return invalid_original_decision_data(3, byte_order)
        cursor += chunk_length
        output.extend(chunk)
    return OriginalDecisionDataReadResult(
        status="ok",
        data=bytes(output),
        version=3,
        byte_order=byte_order,
        warning=None,
    )


def read_slice(file_data: bytes, offset: int, length: int) -> bytes | None:
    if offset < 0 or length < 0:
        return None
    end = offset + length
    if end > len(file_data):
        return None
    return file_data[offset:end]


def invalid_original_decision_data(
    version: int | None = None,
    byte_order: Endian | None = None,
) -> OriginalDecisionDataReadResult:
    return OriginalDecisionDataReadResult(
        status="invalid",
        data=None,
        version=version,
        byte_order=byte_order,
        warning="Invalid original decision data",
    )
