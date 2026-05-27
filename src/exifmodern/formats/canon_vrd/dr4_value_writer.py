"""Standalone CanonDR4 in-place value writer.

This implements the narrow DR4 byte behavior needed by the generated CanonVRD
test-14 request: existing DR4 entries only, same-size scalar or subdirectory
writes only, and no trailer/container rewriting.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.canon_vrd.dr4_value_plan import (
    CanonVrdDr4RequestedValue,
    CanonVrdDr4RewriteStepPlan,
)
from exifmodern.formats.canon_vrd.external_write_plan import CanonVrdExternalWriteStep

DR4_HEADER_SIZE = 32
DR4_ENTRY_TABLE_OFFSET = 36
DR4_ENTRY_SIZE = 28
type Dr4ByteOrder = Literal["little", "big"]


@dataclass(frozen=True)
class CanonVrdDr4ValueWriteResult:
    data: bytes
    changed_tags: tuple[str, ...]
    written_bytes: int


class CanonVrdDr4ValueWriteUnsupportedError(ValueError):
    """Raised when a DR4 value write would cross the safe byte boundary."""


def materialize_supported_standalone_dr4_value_write(
    source_data: bytes,
    step: CanonVrdExternalWriteStep | CanonVrdDr4RewriteStepPlan,
) -> CanonVrdDr4ValueWriteResult:
    if step.action != "rewrite_standalone_dr4_values" or step.blocker_codes:
        blockers = ", ".join(step.blocker_codes) or step.action
        raise CanonVrdDr4ValueWriteUnsupportedError(
            f"CanonDR4 value step is not standalone byte-writable: {blockers}"
        )
    requested_values = requested_values_for_step(step)
    if not requested_values:
        raise CanonVrdDr4ValueWriteUnsupportedError("CanonDR4 value step has no writable values")
    return rewrite_standalone_dr4_values(source_data, requested_values)


def rewrite_standalone_dr4_values(
    source_data: bytes,
    requested_values: tuple[CanonVrdDr4RequestedValue, ...],
) -> CanonVrdDr4ValueWriteResult:
    output = bytearray(source_data)
    byte_order = dr4_byte_order(output)
    directory = dr4_directory_entries(output, byte_order)
    changed_tags: list[str] = []
    written_bytes = 0
    for requested_value in requested_values:
        entry = directory.get(int(require_text(requested_value.dr4_entry_tag_id), 16))
        if entry is None:
            raise CanonVrdDr4ValueWriteUnsupportedError(
                f"CanonDR4 entry is missing for {requested_value.tag_name}"
            )
        written_bytes += write_requested_value(output, byte_order, entry, requested_value)
        changed_tags.append(requested_value.tag_name)
    return CanonVrdDr4ValueWriteResult(
        data=bytes(output),
        changed_tags=tuple(changed_tags),
        written_bytes=written_bytes,
    )


@dataclass(frozen=True)
class Dr4DirectoryEntry:
    tag_id: int
    format_code: int
    entry_offset: int
    value_offset: int
    value_length: int


def dr4_byte_order(data: bytearray) -> Dr4ByteOrder:
    if len(data) < DR4_HEADER_SIZE or data[:8] != b"IIII\x04\0\x04\0":
        raise CanonVrdDr4ValueWriteUnsupportedError("Invalid CanonDR4 header")
    return "little"


def dr4_directory_entries(
    data: bytearray,
    byte_order: Dr4ByteOrder,
) -> dict[int, Dr4DirectoryEntry]:
    entry_count = read_u32(data, 28, byte_order)
    table_end = DR4_ENTRY_TABLE_OFFSET + DR4_ENTRY_SIZE * entry_count
    if table_end > len(data):
        raise CanonVrdDr4ValueWriteUnsupportedError("CanonDR4 entry table is truncated")
    entries: dict[int, Dr4DirectoryEntry] = {}
    for index in range(entry_count):
        entry_offset = DR4_ENTRY_TABLE_OFFSET + DR4_ENTRY_SIZE * index
        tag_id = read_u32(data, entry_offset, byte_order)
        value_offset = read_u32(data, entry_offset + 20, byte_order)
        value_length = read_u32(data, entry_offset + 24, byte_order)
        if value_offset + value_length >= len(data):
            continue
        entries[tag_id] = Dr4DirectoryEntry(
            tag_id=tag_id,
            format_code=read_u32(data, entry_offset + 4, byte_order),
            entry_offset=entry_offset,
            value_offset=value_offset,
            value_length=value_length,
        )
    return entries


def write_requested_value(
    data: bytearray,
    byte_order: Dr4ByteOrder,
    entry: Dr4DirectoryEntry,
    requested_value: CanonVrdDr4RequestedValue,
) -> int:
    if requested_value.location == "directory_entry_flag":
        flag_index = requested_value.flag_index
        if flag_index is None or flag_index not in {0, 1, 2}:
            raise CanonVrdDr4ValueWriteUnsupportedError(
                f"Unsupported CanonDR4 flag for {requested_value.tag_name}"
            )
        write_u32(
            data,
            entry.entry_offset + 8 + 4 * flag_index,
            parse_int(requested_value),
            byte_order,
        )
        return 4
    if requested_value.location == "directory_value":
        encoded = encode_directory_value(requested_value, entry.value_length, byte_order)
        data[entry.value_offset : entry.value_offset + entry.value_length] = encoded
        return len(encoded)
    if requested_value.location == "nested_subdirectory_value":
        encoded = encode_nested_value(requested_value, byte_order)
        value_offset = nested_value_offset(entry, requested_value)
        data[value_offset : value_offset + len(encoded)] = encoded
        return len(encoded)
    raise CanonVrdDr4ValueWriteUnsupportedError(
        f"Unsupported CanonDR4 value location for {requested_value.tag_name}"
    )


def encode_directory_value(
    requested_value: CanonVrdDr4RequestedValue,
    value_length: int,
    byte_order: Dr4ByteOrder,
) -> bytes:
    if requested_value.tag_name == "RedHSL":
        values = tuple(float(part) for part in requested_value.raw_value.split())
        if len(values) * 8 != value_length:
            raise CanonVrdDr4ValueWriteUnsupportedError("RedHSL encoded length changed")
        return struct.pack(endian_prefix(byte_order) + f"{len(values)}d", *values)
    raise CanonVrdDr4ValueWriteUnsupportedError(
        f"Unsupported CanonDR4 directory value: {requested_value.tag_name}"
    )


def encode_nested_value(
    requested_value: CanonVrdDr4RequestedValue,
    byte_order: Dr4ByteOrder,
) -> bytes:
    if requested_value.tag_name == "CropX":
        return parse_int(requested_value).to_bytes(4, byte_order, signed=True)
    if requested_value.tag_name == "GammaBlackPoint":
        raw_value = float(requested_value.raw_value)
        encoded = math.exp((raw_value - 1) * math.log(2)) * 4.6876 if raw_value else 0.0
        return struct.pack(endian_prefix(byte_order) + "d", encoded)
    raise CanonVrdDr4ValueWriteUnsupportedError(
        f"Unsupported CanonDR4 nested value: {requested_value.tag_name}"
    )


def nested_value_offset(
    entry: Dr4DirectoryEntry,
    requested_value: CanonVrdDr4RequestedValue,
) -> int:
    subdirectory_tag_id = int(require_text(requested_value.subdirectory_tag_id), 16)
    if requested_value.subdirectory == "CropInfo":
        return entry.value_offset + subdirectory_tag_id * 4
    if requested_value.subdirectory == "GammaInfo":
        return entry.value_offset + subdirectory_tag_id * 8
    raise CanonVrdDr4ValueWriteUnsupportedError(
        f"Unsupported CanonDR4 subdirectory: {requested_value.subdirectory}"
    )


def requested_values_for_step(
    step: CanonVrdExternalWriteStep | CanonVrdDr4RewriteStepPlan,
) -> tuple[CanonVrdDr4RequestedValue, ...]:
    if isinstance(step, CanonVrdDr4RewriteStepPlan):
        return step.requested_values
    values: list[CanonVrdDr4RequestedValue] = []
    for argument in step.write_args:
        if not argument.startswith("-") or "=" not in argument:
            continue
        tag, _separator, raw_value = argument[1:].partition("=")
        requested_value = requested_value_from_arg(argument, tag, raw_value)
        if requested_value is not None:
            values.append(requested_value)
    return tuple(values)


def requested_value_from_arg(
    argument: str,
    raw_tag: str,
    raw_value: str,
) -> CanonVrdDr4RequestedValue | None:
    group, _separator, tag_name = raw_tag.rpartition(":")
    if not tag_name:
        tag_name = raw_tag
        group = ""
    if tag_name == "CropX":
        return CanonVrdDr4RequestedValue(
            argument=argument,
            group=group or None,
            tag_name=tag_name,
            raw_value=raw_value,
            location="nested_subdirectory_value",
            dr4_entry_tag_id="0x0f0100",
            flag_index=None,
            subdirectory="CropInfo",
            subdirectory_tag_id="0x03",
            value_format="int32s",
        )
    if tag_name == "SharpnessAdjOn":
        return CanonVrdDr4RequestedValue(
            argument=argument,
            group=group or None,
            tag_name=tag_name,
            raw_value=raw_value,
            location="directory_entry_flag",
            dr4_entry_tag_id="0x020310",
            flag_index=0,
            subdirectory=None,
            subdirectory_tag_id=None,
            value_format="int32u",
        )
    if tag_name == "RedHSL":
        return CanonVrdDr4RequestedValue(
            argument=argument,
            group=group or None,
            tag_name=tag_name,
            raw_value=raw_value,
            location="directory_value",
            dr4_entry_tag_id="0x020910",
            flag_index=None,
            subdirectory=None,
            subdirectory_tag_id=None,
            value_format="double[3]",
        )
    if tag_name == "GammaBlackPoint":
        return CanonVrdDr4RequestedValue(
            argument=argument,
            group=group or None,
            tag_name=tag_name,
            raw_value=raw_value,
            location="nested_subdirectory_value",
            dr4_entry_tag_id="0x020a00",
            flag_index=None,
            subdirectory="GammaInfo",
            subdirectory_tag_id="0x0c",
            value_format="double",
        )
    return None


def read_u32(data: bytearray, offset: int, byte_order: Dr4ByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order)


def write_u32(data: bytearray, offset: int, value: int, byte_order: Dr4ByteOrder) -> None:
    data[offset : offset + 4] = value.to_bytes(4, byte_order, signed=False)


def parse_int(requested_value: CanonVrdDr4RequestedValue) -> int:
    return int(requested_value.raw_value, 10)


def endian_prefix(byte_order: Dr4ByteOrder) -> str:
    return "<" if byte_order == "little" else ">"


def require_text(value: str | None) -> str:
    if value is None:
        raise CanonVrdDr4ValueWriteUnsupportedError("Missing CanonDR4 layout value")
    return value
