"""Source-grounded Canon CustomFunctions2 mutation primitives."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_LONG,
    TIFF_TYPE_SHORT,
    TIFF_TYPE_UNDEFINED,
    Endian,
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
)

EXIF_IFD_POINTER = 0x8769
MAKER_NOTE_TAG = 0x927C
CANON_CUSTOM_FUNCTIONS2_TAG = 0x0099
CANON_ISO_SPEED_RANGE_TAG = 0x0103
CANON_TIMER_LENGTH_TAG = 0x080C

type CanonCustomFunctionEvidenceId = str

CANON_CUSTOM_FUNCTIONS2_SOURCE = "canon.custom_functions2.route"
CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE = "canon.custom_functions2.process"
CANON_ISO_SPEED_RANGE_SOURCE = "canon.custom_functions2.iso_speed_range"
CANON_TIMER_LENGTH_SOURCE = "canon.custom_functions2.timer_length"
CANON_WRITE_TEST_SOURCE = "canon.custom_functions2.write_test"

NUMERIC_SUFFIX_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*$")


@dataclass(frozen=True)
class CanonCustomFunctionWriteStep:
    tag_name: str
    tag_id: int
    raw_values: tuple[int, ...]
    evidence_ids: tuple[CanonCustomFunctionEvidenceId, ...]


@dataclass(frozen=True)
class CanonCustomFunctionWritePlan:
    steps: tuple[CanonCustomFunctionWriteStep, ...]


@dataclass(frozen=True)
class CanonCustomFunctionRewriteResult:
    data: bytes
    changed_properties: int


@dataclass(frozen=True)
class CanonCustomFunctionContext:
    endian: Endian
    custom_functions2_offset: int
    custom_functions2_size: int


@dataclass(frozen=True)
class CanonCustomFunctionLocation:
    value_offset: int
    raw_values: tuple[int, ...]


def build_canon_custom_function_write_plan(
    *,
    iso_speed_range: str | None = None,
    timer_length: str | None = None,
) -> CanonCustomFunctionWritePlan:
    steps: list[CanonCustomFunctionWriteStep] = []
    if iso_speed_range is not None:
        steps.append(
            CanonCustomFunctionWriteStep(
                tag_name="ISOSpeedRange",
                tag_id=CANON_ISO_SPEED_RANGE_TAG,
                raw_values=canon_iso_speed_range_raw_values(iso_speed_range),
                evidence_ids=(
                    CANON_ISO_SPEED_RANGE_SOURCE,
                    CANON_CUSTOM_FUNCTIONS2_SOURCE,
                    CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE,
                    CANON_WRITE_TEST_SOURCE,
                ),
            )
        )
    if timer_length is not None:
        steps.append(
            CanonCustomFunctionWriteStep(
                tag_name="TimerLength",
                tag_id=CANON_TIMER_LENGTH_TAG,
                raw_values=canon_timer_length_raw_values(timer_length),
                evidence_ids=(
                    CANON_TIMER_LENGTH_SOURCE,
                    CANON_CUSTOM_FUNCTIONS2_SOURCE,
                    CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE,
                    CANON_WRITE_TEST_SOURCE,
                ),
            )
        )
    return CanonCustomFunctionWritePlan(tuple(steps))


def rewrite_canon_custom_functions_in_tiff(
    tiff_data: bytes,
    plan: CanonCustomFunctionWritePlan,
) -> CanonCustomFunctionRewriteResult:
    context = canon_custom_function_context(tiff_data)
    mutable = bytearray(tiff_data)
    changed_properties = 0
    for step in plan.steps:
        location = canon_custom_function_location(tiff_data, context, step)
        if location.raw_values == step.raw_values:
            continue
        mutable[location.value_offset : location.value_offset + len(step.raw_values) * 4] = (
            encode_int32_values(step.raw_values, context.endian)
        )
        changed_properties += 1
    return CanonCustomFunctionRewriteResult(bytes(mutable), changed_properties)


def read_canon_custom_function_values(
    tiff_data: bytes,
    step: CanonCustomFunctionWriteStep,
) -> tuple[int, ...]:
    context = canon_custom_function_context(tiff_data)
    return canon_custom_function_location(tiff_data, context, step).raw_values


def canon_custom_function_context(tiff_data: bytes) -> CanonCustomFunctionContext:
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    exif_ifd_pointer = required_ifd_entry(ifd0, EXIF_IFD_POINTER, "IFD0 ExifIFD pointer")
    exif_ifd = parse_ifd(tiff_data, exif_ifd_pointer.value_offset, header.endian)
    maker_note_entry = required_ifd_entry(exif_ifd, MAKER_NOTE_TAG, "ExifIFD MakerNoteCanon")
    if maker_note_entry.field_type != TIFF_TYPE_UNDEFINED:
        raise ValueError("Canon MakerNote tag is not undefined data.")
    maker_note_ifd = parse_ifd(tiff_data, maker_note_entry.value_offset, header.endian)
    custom_functions2_entry = required_ifd_entry(
        maker_note_ifd,
        CANON_CUSTOM_FUNCTIONS2_TAG,
        "Canon CustomFunctions2",
    )
    custom_functions2_offset = custom_functions2_entry.value_offset
    custom_functions2_byte_count = canon_ifd_entry_byte_count(custom_functions2_entry)
    size = read_u16(tiff_data, custom_functions2_offset, header.endian)
    if size != custom_functions2_byte_count:
        raise ValueError("Canon CustomFunctions2 size does not match MakerNote entry count.")
    if custom_functions2_offset + size > len(tiff_data):
        raise ValueError("Canon CustomFunctions2 data is truncated.")
    return CanonCustomFunctionContext(header.endian, custom_functions2_offset, size)


def canon_custom_function_location(
    tiff_data: bytes,
    context: CanonCustomFunctionContext,
    step: CanonCustomFunctionWriteStep,
) -> CanonCustomFunctionLocation:
    offset = context.custom_functions2_offset
    size = context.custom_functions2_size
    group_count = read_u32(tiff_data, offset + 4, context.endian)
    position = offset + 8
    end = offset + size
    parsed_group_count = 0
    while position < end:
        if position + 12 > end:
            break
        record_length = read_u32(tiff_data, position + 4, context.endian)
        record_count = read_u32(tiff_data, position + 8, context.endian)
        if record_length < 8:
            break
        position += 12
        record_position = position
        record_end = position + record_length - 8
        if record_end > end:
            raise ValueError("Canon CustomFunctions2 record is truncated.")
        parsed_entry_count = 0
        while record_position + 8 < record_end:
            tag_id = read_u32(tiff_data, record_position, context.endian)
            value_count = read_u32(tiff_data, record_position + 4, context.endian)
            next_record_position = record_position + 8 + value_count * 4
            if next_record_position > record_end:
                break
            value_offset = record_position + 8
            if tag_id == step.tag_id:
                if value_count != len(step.raw_values):
                    raise ValueError(f"Canon {step.tag_name} value count does not match source.")
                return CanonCustomFunctionLocation(
                    value_offset=value_offset,
                    raw_values=decode_int32_values(
                        tiff_data[value_offset:next_record_position],
                        context.endian,
                    ),
                )
            parsed_entry_count += 1
            record_position = next_record_position
        if parsed_entry_count != record_count:
            raise ValueError("Canon CustomFunctions2 record count is inconsistent.")
        parsed_group_count += 1
        position = record_end
    if parsed_group_count != group_count:
        raise ValueError("Canon CustomFunctions2 group count is inconsistent.")
    raise ValueError(f"Missing Canon {step.tag_name} CustomFunctions2 record.")


def canon_iso_speed_range_raw_values(value: str) -> tuple[int, int, int]:
    fields = canon_semicolon_fields(value, 3, "ISOSpeedRange")
    return (
        canon_disable_enable_raw_value(fields[0], "ISOSpeedRange"),
        canon_iso_limit_raw_value(fields[1], "ISOSpeedRange max"),
        canon_iso_limit_raw_value(fields[2], "ISOSpeedRange min"),
    )


def canon_timer_length_raw_values(value: str) -> tuple[int, int, int, int]:
    fields = canon_semicolon_fields(value, 4, "TimerLength")
    return (
        canon_disable_enable_raw_value(fields[0], "TimerLength"),
        numeric_suffix_int(fields[1], "TimerLength 6 s"),
        numeric_suffix_int(fields[2], "TimerLength 16 s"),
        numeric_suffix_int(fields[3], "TimerLength After release"),
    )


def canon_semicolon_fields(value: str, count: int, tag_name: str) -> tuple[str, ...]:
    fields = tuple(field.strip() for field in value.split(";"))
    if len(fields) != count:
        raise ValueError(f"Canon {tag_name} expects {count} semicolon-separated fields.")
    return fields


def canon_disable_enable_raw_value(value: str, tag_name: str) -> int:
    if value == "Disable":
        return 0
    if value == "Enable":
        return 1
    raise ValueError(f"Canon {tag_name} first field must be Disable or Enable.")


def canon_iso_limit_raw_value(value: str, tag_name: str) -> int:
    numeric_value = numeric_suffix_float(value, tag_name)
    if numeric_value < 0:
        raise ValueError(f"Canon {tag_name} must not be negative.")
    if numeric_value < 2:
        return int(numeric_value)
    raw_value = int(8 * (math.log(numeric_value / 100) / math.log(2) + 9) + 0.5)
    if raw_value < 0 or raw_value > 0xFFFFFFFF:
        raise ValueError(f"Canon {tag_name} raw value exceeds int32 storage.")
    return raw_value


def numeric_suffix_int(value: str, tag_name: str) -> int:
    numeric_value = numeric_suffix_float(value, tag_name)
    if not numeric_value.is_integer():
        raise ValueError(f"Canon {tag_name} must be an integer.")
    raw_value = int(numeric_value)
    if raw_value < 0 or raw_value > 0xFFFFFFFF:
        raise ValueError(f"Canon {tag_name} raw value exceeds int32 storage.")
    return raw_value


def numeric_suffix_float(value: str, tag_name: str) -> float:
    match = NUMERIC_SUFFIX_RE.search(value)
    if match is None:
        raise ValueError(f"Canon {tag_name} does not end with a numeric value.")
    return float(match.group(1))


def required_ifd_entry(ifd: Ifd, tag_id: int, label: str) -> IfdEntry:
    for entry in ifd.entries:
        if entry.tag_id == tag_id:
            return entry
    raise ValueError(f"Missing {label} tag 0x{tag_id:04x}.")


def canon_ifd_entry_byte_count(entry: IfdEntry) -> int:
    if entry.field_type == TIFF_TYPE_UNDEFINED:
        return entry.count
    if entry.field_type == TIFF_TYPE_SHORT:
        return entry.count * 2
    if entry.field_type == TIFF_TYPE_LONG:
        return entry.count * 4
    raise ValueError("Canon CustomFunctions2 entry uses an unsupported TIFF field type.")


def read_u16(data: bytes, offset: int, endian: Endian) -> int:
    return int.from_bytes(data[offset : offset + 2], endian)


def read_u32(data: bytes, offset: int, endian: Endian) -> int:
    return int.from_bytes(data[offset : offset + 4], endian)


def decode_int32_values(data: bytes, endian: Endian) -> tuple[int, ...]:
    return tuple(
        int.from_bytes(data[index : index + 4], endian, signed=True)
        for index in range(0, len(data), 4)
    )


def encode_int32_values(values: tuple[int, ...], endian: Endian) -> bytes:
    return b"".join(value.to_bytes(4, endian, signed=True) for value in values)
