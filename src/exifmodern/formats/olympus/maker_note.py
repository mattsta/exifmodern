"""Source-grounded Olympus maker-note mutation primitives."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Literal

from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_ASCII,
    TIFF_TYPE_LONG,
    TIFF_TYPE_RATIONAL,
    TIFF_TYPE_SHORT,
    TIFF_TYPE_UNDEFINED,
    Endian,
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)

type OlympusMacroValue = Literal["Off", "On", "Super Macro"]
type OlympusMakerNoteValueKind = Literal["ascii_fixed", "rational64u", "short"]
type OlympusMakerNoteOffsetBase = Literal["auto", "maker_note_relative", "tiff_absolute"]

EXIF_IFD_POINTER = 0x8769
MAKER_NOTE_TAG = 0x927C
OLYMPUS_MAKER_NOTE_HEADERS = (
    b"OLYMP\x00\x01\x00",
    b"OLYMP\x00\x02\x00",
    b"OLYMPUS\x00II\x03\x00",
)
OLYMPUS_MACRO_TAG = 0x0202
OLYMPUS_CORING_FILTER_TAG = 0x102D
OLYMPUS_EQUIPMENT_IFD_TAG = 0x2010
OLYMPUS_IMAGE_PROCESSING_IFD_TAG = 0x2040
OLYMPUS_FOCUS_INFO_IFD_TAG = 0x2050
OLYMPUS_EQUIPMENT_LENS_SERIAL_NUMBER_TAG = 0x0202
OLYMPUS_IMAGE_PROCESSING_CORING_FILTER_TAG = 0x0310
OLYMPUS_FOCUS_DISTANCE_TAG = 0x0305

OLYMPUS_MACRO_SOURCE = "olympus.makernote.macro"
OLYMPUS_CORING_FILTER_SOURCE = "olympus.makernote.coring_filter"
OLYMPUS_IMAGE_PROCESSING_CORING_FILTER_SOURCE = "olympus.makernote.image_processing_coring_filter"
OLYMPUS_EQUIPMENT_SOURCE = "olympus.makernote.equipment_lens_serial_number"
OLYMPUS_FOCUS_DISTANCE_SOURCE = "olympus.makernote.focus_distance"
OLYMPUS_WRITE_TEST_SOURCE = "olympus.makernote.write_test_3"
OLYMPUS_WRITE_TEST_EXTENDED_SOURCE = "olympus.makernote.write_tests_5_7"


@dataclass(frozen=True)
class OlympusMakerNoteHeaderSpec:
    header: bytes
    ifd_offset: int


@dataclass(frozen=True)
class OlympusSubIfdReference:
    tag_id: int
    tag_name: str
    offset_base: OlympusMakerNoteOffsetBase


@dataclass(frozen=True)
class OlympusMakerNoteWriteStep:
    tag_name: str
    tag_id: int
    sub_ifd_path: tuple[OlympusSubIfdReference, ...]
    value_kind: OlympusMakerNoteValueKind
    raw_values: tuple[int, ...]
    raw_bytes: bytes | None
    required: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OlympusMakerNoteWritePlan:
    steps: tuple[OlympusMakerNoteWriteStep, ...]


@dataclass(frozen=True)
class OlympusMacroWritePlan:
    value: OlympusMacroValue
    raw_value: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OlympusMacroRewriteResult:
    data: bytes
    changed: bool
    original_raw_value: int
    rewritten_raw_value: int


@dataclass(frozen=True)
class OlympusMakerNoteRewriteResult:
    data: bytes
    changed_step_count: int


@dataclass(frozen=True)
class OlympusMakerNoteContext:
    endian: Endian
    maker_note_offset: int
    maker_note_ifd: Ifd


@dataclass(frozen=True)
class OlympusMakerNoteStepLocation:
    value_offset: int
    value_byte_count: int
    endian: Endian
    raw_values: tuple[int, ...]
    raw_bytes: bytes | None


def build_olympus_macro_write_plan(value: str) -> OlympusMacroWritePlan:
    normalized = normalize_olympus_macro_value(value)
    return OlympusMacroWritePlan(
        value=normalized,
        raw_value=olympus_macro_raw_value(normalized),
        evidence_ids=(OLYMPUS_MACRO_SOURCE, OLYMPUS_WRITE_TEST_SOURCE),
    )


def build_olympus_maker_note_write_plan(
    *,
    macro: str | None = None,
    focus_distance: str | None = None,
    lens_serial_number: str | None = None,
    coring_filter: str | None = None,
) -> OlympusMakerNoteWritePlan:
    steps: list[OlympusMakerNoteWriteStep] = []
    if macro is not None:
        macro_value = normalize_olympus_macro_value(macro)
        steps.append(
            OlympusMakerNoteWriteStep(
                tag_name="Macro",
                tag_id=OLYMPUS_MACRO_TAG,
                sub_ifd_path=(),
                value_kind="short",
                raw_values=(olympus_macro_raw_value(macro_value),),
                raw_bytes=None,
                required=True,
                evidence_ids=(OLYMPUS_MACRO_SOURCE, OLYMPUS_WRITE_TEST_SOURCE),
            )
        )
    if focus_distance is not None:
        steps.append(
            OlympusMakerNoteWriteStep(
                tag_name="FocusDistance",
                tag_id=OLYMPUS_FOCUS_DISTANCE_TAG,
                sub_ifd_path=(
                    OlympusSubIfdReference(
                        OLYMPUS_FOCUS_INFO_IFD_TAG,
                        "FocusInfo",
                        "maker_note_relative",
                    ),
                ),
                value_kind="rational64u",
                raw_values=olympus_focus_distance_raw_values(focus_distance),
                raw_bytes=None,
                required=True,
                evidence_ids=(
                    OLYMPUS_FOCUS_DISTANCE_SOURCE,
                    OLYMPUS_WRITE_TEST_EXTENDED_SOURCE,
                ),
            )
        )
    if lens_serial_number is not None:
        steps.append(
            OlympusMakerNoteWriteStep(
                tag_name="LensSerialNumber",
                tag_id=OLYMPUS_EQUIPMENT_LENS_SERIAL_NUMBER_TAG,
                sub_ifd_path=(
                    OlympusSubIfdReference(
                        OLYMPUS_EQUIPMENT_IFD_TAG,
                        "Equipment",
                        "auto",
                    ),
                ),
                value_kind="ascii_fixed",
                raw_values=(),
                raw_bytes=olympus_lens_serial_number_raw_bytes(lens_serial_number),
                required=True,
                evidence_ids=(OLYMPUS_EQUIPMENT_SOURCE, OLYMPUS_WRITE_TEST_EXTENDED_SOURCE),
            )
        )
    if coring_filter is not None:
        raw_coring_filter = olympus_int16u_value("CoringFilter", coring_filter)
        steps.extend(
            (
                OlympusMakerNoteWriteStep(
                    tag_name="CoringFilter",
                    tag_id=OLYMPUS_CORING_FILTER_TAG,
                    sub_ifd_path=(),
                    value_kind="short",
                    raw_values=(raw_coring_filter,),
                    raw_bytes=None,
                    required=False,
                    evidence_ids=(
                        OLYMPUS_CORING_FILTER_SOURCE,
                        OLYMPUS_WRITE_TEST_EXTENDED_SOURCE,
                    ),
                ),
                OlympusMakerNoteWriteStep(
                    tag_name="CoringFilter",
                    tag_id=OLYMPUS_IMAGE_PROCESSING_CORING_FILTER_TAG,
                    sub_ifd_path=(
                        OlympusSubIfdReference(
                            OLYMPUS_IMAGE_PROCESSING_IFD_TAG,
                            "ImageProcessing",
                            "auto",
                        ),
                    ),
                    value_kind="short",
                    raw_values=(raw_coring_filter,),
                    raw_bytes=None,
                    required=False,
                    evidence_ids=(
                        OLYMPUS_IMAGE_PROCESSING_CORING_FILTER_SOURCE,
                        OLYMPUS_WRITE_TEST_EXTENDED_SOURCE,
                    ),
                ),
            )
        )
    return OlympusMakerNoteWritePlan(tuple(steps))


def rewrite_olympus_macro_in_tiff(
    tiff_data: bytes,
    plan: OlympusMacroWritePlan,
) -> OlympusMacroRewriteResult:
    location = olympus_macro_value_location(tiff_data)
    maker_note_plan = build_olympus_maker_note_write_plan(macro=plan.value)
    result = rewrite_olympus_maker_notes_in_tiff(tiff_data, maker_note_plan)
    return OlympusMacroRewriteResult(
        data=result.data,
        changed=result.changed_step_count > 0,
        original_raw_value=location.raw_value,
        rewritten_raw_value=plan.raw_value,
    )


def rewrite_olympus_maker_notes_in_tiff(
    tiff_data: bytes,
    plan: OlympusMakerNoteWritePlan,
) -> OlympusMakerNoteRewriteResult:
    context = olympus_maker_note_context(tiff_data)
    mutable = bytearray(tiff_data)
    changed_step_count = 0
    for step in plan.steps:
        location = optional_olympus_maker_note_step_location(tiff_data, context, step)
        if location is None:
            if step.required:
                raise ValueError(f"Missing required Olympus {step.tag_name} tag.")
            continue
        if write_olympus_step_value(mutable, location, step):
            changed_step_count += 1
    return OlympusMakerNoteRewriteResult(bytes(mutable), changed_step_count)


def read_olympus_macro_from_tiff(tiff_data: bytes) -> OlympusMacroValue:
    location = olympus_macro_value_location(tiff_data)
    return olympus_macro_print_value(location.raw_value)


def read_olympus_maker_note_step_values(
    tiff_data: bytes,
    step: OlympusMakerNoteWriteStep,
) -> tuple[int, ...] | bytes:
    context = olympus_maker_note_context(tiff_data)
    location = olympus_maker_note_step_location(tiff_data, context, step)
    if step.value_kind == "ascii_fixed":
        if location.raw_bytes is None:
            raise ValueError(f"Olympus {step.tag_name} did not read as bytes.")
        return location.raw_bytes
    return location.raw_values


@dataclass(frozen=True)
class OlympusMacroValueLocation:
    value_offset: int
    endian: Literal["little", "big"]
    raw_value: int


def olympus_macro_value_location(tiff_data: bytes) -> OlympusMacroValueLocation:
    context = olympus_maker_note_context(tiff_data)
    step = build_olympus_maker_note_write_plan(macro="Off").steps[0]
    location = olympus_maker_note_step_location(tiff_data, context, step)
    if len(location.raw_values) != 1:
        raise ValueError("Olympus Macro value is not a scalar integer.")
    return OlympusMacroValueLocation(
        value_offset=location.value_offset,
        endian=location.endian,
        raw_value=location.raw_values[0],
    )


def olympus_maker_note_context(tiff_data: bytes) -> OlympusMakerNoteContext:
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    exif_ifd_pointer = required_ifd_entry(ifd0, EXIF_IFD_POINTER, "IFD0 ExifIFD pointer")
    exif_ifd = parse_ifd(tiff_data, inline_u32(exif_ifd_pointer, header.endian), header.endian)
    maker_note_entry = required_ifd_entry(exif_ifd, MAKER_NOTE_TAG, "ExifIFD MakerNoteOlympus")
    validate_maker_note_entry(maker_note_entry)
    maker_note_offset = maker_note_entry.value_offset
    header_spec = olympus_maker_note_header_spec(tiff_data, maker_note_offset)
    maker_note_ifd = parse_ifd(tiff_data, maker_note_offset + header_spec.ifd_offset, header.endian)
    return OlympusMakerNoteContext(header.endian, maker_note_offset, maker_note_ifd)


def olympus_maker_note_step_location(
    tiff_data: bytes,
    context: OlympusMakerNoteContext,
    step: OlympusMakerNoteWriteStep,
) -> OlympusMakerNoteStepLocation:
    location = optional_olympus_maker_note_step_location(tiff_data, context, step)
    if location is None:
        raise ValueError(f"Missing Olympus {step.tag_name} tag.")
    return location


def optional_olympus_maker_note_step_location(
    tiff_data: bytes,
    context: OlympusMakerNoteContext,
    step: OlympusMakerNoteWriteStep,
) -> OlympusMakerNoteStepLocation | None:
    target_ifd = context.maker_note_ifd
    for sub_ifd_reference in step.sub_ifd_path:
        sub_ifd_entry = optional_ifd_entry(target_ifd, sub_ifd_reference.tag_id)
        if sub_ifd_entry is None:
            return None
        sub_ifd_offset = olympus_sub_ifd_offset(context, sub_ifd_entry, sub_ifd_reference)
        target_ifd = parse_ifd(tiff_data, sub_ifd_offset, context.endian)
    target_entry = optional_ifd_entry(target_ifd, step.tag_id)
    if target_entry is None:
        return None
    return olympus_step_value_location(tiff_data, context.endian, target_entry, step)


def olympus_step_value_location(
    tiff_data: bytes,
    endian: Endian,
    entry: IfdEntry,
    step: OlympusMakerNoteWriteStep,
) -> OlympusMakerNoteStepLocation:
    if step.value_kind == "short":
        validate_short_entry(entry, step.tag_name)
        value = read_entry_value(tiff_data, entry, endian)
        if not isinstance(value, int):
            raise ValueError(f"Olympus {step.tag_name} value is not a scalar integer.")
        return OlympusMakerNoteStepLocation(entry.entry_offset + 8, 2, endian, (value,), None)
    if step.value_kind == "rational64u":
        validate_rational64u_entry(entry, step.tag_name)
        value_offset = entry.value_offset
        end = value_offset + 8
        if end > len(tiff_data):
            raise ValueError(f"Olympus {step.tag_name} value is truncated.")
        return OlympusMakerNoteStepLocation(
            value_offset,
            8,
            endian,
            (
                int.from_bytes(tiff_data[value_offset : value_offset + 4], endian),
                int.from_bytes(tiff_data[value_offset + 4 : end], endian),
            ),
            None,
        )
    validate_ascii_fixed_entry(entry, step.tag_name)
    value_offset = entry.value_offset
    end = value_offset + entry.count
    if end > len(tiff_data):
        raise ValueError(f"Olympus {step.tag_name} value is truncated.")
    return OlympusMakerNoteStepLocation(
        value_offset,
        entry.count,
        endian,
        (),
        tiff_data[value_offset:end],
    )


def write_olympus_step_value(
    mutable_tiff_data: bytearray,
    location: OlympusMakerNoteStepLocation,
    step: OlympusMakerNoteWriteStep,
) -> bool:
    if step.value_kind == "ascii_fixed":
        if step.raw_bytes is None:
            raise ValueError(f"Olympus {step.tag_name} has no string payload.")
        if len(step.raw_bytes) != location.value_byte_count:
            raise ValueError(f"Olympus {step.tag_name} payload length does not match tag count.")
        original = bytes(
            mutable_tiff_data[location.value_offset : location.value_offset + len(step.raw_bytes)]
        )
        mutable_tiff_data[location.value_offset : location.value_offset + len(step.raw_bytes)] = (
            step.raw_bytes
        )
        return original != step.raw_bytes
    payload = b"".join(
        raw_value.to_bytes(location.value_byte_count // len(step.raw_values), location.endian)
        for raw_value in step.raw_values
    )
    original = bytes(
        mutable_tiff_data[location.value_offset : location.value_offset + len(payload)]
    )
    mutable_tiff_data[location.value_offset : location.value_offset + len(payload)] = payload
    return original != payload


def required_ifd_entry(ifd: Ifd, tag_id: int, label: str) -> IfdEntry:
    for entry in ifd.entries:
        if entry.tag_id == tag_id:
            return entry
    raise ValueError(f"Missing {label} tag 0x{tag_id:04x}.")


def optional_ifd_entry(ifd: Ifd, tag_id: int) -> IfdEntry | None:
    for entry in ifd.entries:
        if entry.tag_id == tag_id:
            return entry
    return None


def validate_maker_note_entry(entry: IfdEntry) -> None:
    if entry.field_type != TIFF_TYPE_UNDEFINED:
        raise ValueError("Olympus MakerNote tag is not undefined data.")
    if entry.count < min(len(header) for header in OLYMPUS_MAKER_NOTE_HEADERS):
        raise ValueError("Olympus MakerNote payload is too short.")


def olympus_maker_note_header_spec(tiff_data: bytes, offset: int) -> OlympusMakerNoteHeaderSpec:
    for maker_note_header in OLYMPUS_MAKER_NOTE_HEADERS:
        end = offset + len(maker_note_header)
        if end > len(tiff_data):
            continue
        if tiff_data[offset:end] == maker_note_header:
            return OlympusMakerNoteHeaderSpec(maker_note_header, len(maker_note_header))
    raise ValueError("Unsupported Olympus MakerNote header.")


def validate_olympus_macro_entry(entry: IfdEntry) -> None:
    validate_short_entry(entry, "Macro")


def validate_short_entry(entry: IfdEntry, tag_name: str) -> None:
    if entry.field_type != TIFF_TYPE_SHORT or entry.count != 1:
        raise ValueError(f"Olympus {tag_name} is not a scalar int16u tag.")


def validate_rational64u_entry(entry: IfdEntry, tag_name: str) -> None:
    if entry.field_type == TIFF_TYPE_LONG and entry.count == 2:
        return
    if entry.field_type == TIFF_TYPE_RATIONAL and entry.count == 1:
        return
    raise ValueError(f"Olympus {tag_name} is not stored as a rational64u value.")


def validate_ascii_fixed_entry(entry: IfdEntry, tag_name: str) -> None:
    if entry.field_type != TIFF_TYPE_ASCII or entry.count <= 4:
        raise ValueError(f"Olympus {tag_name} is not an out-of-line ASCII string tag.")


def inline_u32(entry: IfdEntry, endian: Literal["little", "big"]) -> int:
    return entry.value_offset


def normalize_olympus_macro_value(value: str) -> OlympusMacroValue:
    if value == "Off":
        return "Off"
    if value == "On":
        return "On"
    if value == "Super Macro":
        return "Super Macro"
    raise ValueError("Olympus Macro must be Off, On, or Super Macro.")


def olympus_macro_raw_value(value: OlympusMacroValue) -> int:
    if value == "Off":
        return 0
    if value == "On":
        return 1
    return 2


def olympus_macro_print_value(raw_value: int) -> OlympusMacroValue:
    if raw_value == 0:
        return "Off"
    if raw_value == 1:
        return "On"
    if raw_value == 2:
        return "Super Macro"
    raise ValueError(f"Unknown Olympus Macro raw value: {raw_value}")


def olympus_sub_ifd_offset(
    context: OlympusMakerNoteContext,
    entry: IfdEntry,
    reference: OlympusSubIfdReference,
) -> int:
    if reference.offset_base == "tiff_absolute":
        return entry.value_offset
    if reference.offset_base == "maker_note_relative":
        return context.maker_note_offset + entry.value_offset
    if entry.field_type == TIFF_TYPE_UNDEFINED and entry.count > 4:
        return entry.value_offset
    return context.maker_note_offset + entry.value_offset


def olympus_lens_serial_number_raw_bytes(value: str) -> bytes:
    encoded = value.encode("ascii")
    if len(encoded) > 31:
        encoded = encoded[:31]
    return encoded.ljust(31, b" ") + b"\x00"


def olympus_focus_distance_raw_values(value: str) -> tuple[int, int]:
    try:
        decimal_value = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("Olympus FocusDistance must be numeric meters.") from error
    if decimal_value == 0:
        return (0xFFFFFFFF, 1)
    if decimal_value < 0:
        raise ValueError("Olympus FocusDistance must not be negative.")
    millimeters = int(
        (decimal_value * Decimal(1000) + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR)
    )
    if millimeters > 0xFFFFFFFF:
        raise ValueError("Olympus FocusDistance exceeds uint32 storage.")
    return (millimeters, 1)


def olympus_int16u_value(tag_name: str, value: str) -> int:
    try:
        raw_value = int(value, 10)
    except ValueError as error:
        raise ValueError(f"Olympus {tag_name} must be an integer.") from error
    if raw_value < 0 or raw_value > 0xFFFF:
        raise ValueError(f"Olympus {tag_name} must fit int16u storage.")
    return raw_value
