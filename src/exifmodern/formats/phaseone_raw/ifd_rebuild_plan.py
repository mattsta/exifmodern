"""Dry-run Phase One IFD rebuild planning.

ExifTool's ``WritePhaseOne`` rebuilds Phase One maker-note directories into a
new block rather than mutating entries in place.  This module mirrors that byte
choreography as typed planning data only: it validates the directory, plans
entry rewrites, value padding, value-offset fixups, and the PhaseOneIFD pointer
patch without returning writable bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.phaseone_raw.mutation_plan import (
    PHASEONE_MAIN_ENTRY_SIZE,
    PHASEONE_MAIN_SOURCE,
    PHASEONE_SENSOR_CALIBRATION_SOURCE,
    PHASEONE_SENSOR_CALIBRATION_TAG,
    PHASEONE_SERIAL_NUMBER_TAG,
    PHASEONE_SERIAL_SOURCE,
    PHASEONE_WRITE_SOURCE,
    PhaseOneByteOrder,
    PhaseOneEvidenceId,
    PhaseOneIfdKind,
    PhaseOneRawSafetyGate,
    inspect_phaseone_ifd_header,
    phaseone_byte_order,
    phaseone_entry_size,
    read_uint,
    unique_evidence_ids,
)
from exifmodern.json_types import JsonObject

type PhaseOneIfdRebuildPlanStatus = Literal[
    "source_mapped_non_mutating",
    "unsupported",
]
type PhaseOneIfdEntryAction = Literal[
    "copy_inline_value",
    "copy_deferred_value",
    "copy_put_first_value",
    "rewrite_serial_number",
    "rewrite_sensor_calibration_subifd",
]
type PhaseOneIfdValueStorage = Literal[
    "inline_value_field",
    "header_buffer_put_first",
    "value_buffer_with_fixup",
]
type PhaseOneIfdFormatName = Literal[
    "string",
    "int16s",
    "int32s",
    "undef",
    "invalid",
]

PHASEONE_SENSOR_SERIAL_NUMBER_TAG = 0x0407
PHASEONE_RAW_DATA_TAG = 0x010F
PHASEONE_HEADER_SIZE = 12
PHASEONE_DIRECTORY_PREFIX_SIZE = 8
PHASEONE_INLINE_VALUE_SIZE = 4
PHASEONE_MAX_ENTRY_COUNT = 300
PHASEONE_MAX_VALUE_SIZE = 0x7FFFFFFF

PHASEONE_FORMAT_NAMES: dict[int, PhaseOneIfdFormatName] = {
    1: "string",
    2: "int16s",
    4: "int32s",
}


@dataclass(frozen=True)
class PhaseOneByteRange:
    start_offset: int
    end_offset: int

    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset

    def to_json(self) -> JsonObject:
        return {
            "end_offset": self.end_offset,
            "length": self.length,
            "start_offset": self.start_offset,
        }


@dataclass(frozen=True)
class PhaseOneIfdHeaderProbe:
    directory_offset: int
    byte_order: PhaseOneByteOrder
    ifd_kind: PhaseOneIfdKind
    entry_size: int
    ifd_start: int
    entry_count: int


@dataclass(frozen=True)
class PhaseOneSerialNumberEncoding:
    requested_value: str
    encoding: str
    format_name: PhaseOneIfdFormatName
    encoded_hex: str
    encoded_length: int
    count_can_change: bool
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "count_can_change": self.count_can_change,
            "encoded_hex": self.encoded_hex,
            "encoded_length": self.encoded_length,
            "encoding": self.encoding,
            "format_name": self.format_name,
            "requested_value": self.requested_value,
        }


@dataclass(frozen=True)
class PhaseOneValuePaddingPlan:
    unpadded_length: int
    padding_length: int
    padded_length: int
    pads_zero_length_to_four_bytes: bool
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "padded_length": self.padded_length,
            "padding_length": self.padding_length,
            "pads_zero_length_to_four_bytes": self.pads_zero_length_to_four_bytes,
            "unpadded_length": self.unpadded_length,
        }


@dataclass(frozen=True)
class PhaseOneValueOffsetFixupPlan:
    entry_index: int
    directory_buffer_field_offset: int
    final_value_field_offset: int
    unshifted_value_buffer_offset: int
    shift: int
    planned_value_offset: int
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "directory_buffer_field_offset": self.directory_buffer_field_offset,
            "entry_index": self.entry_index,
            "final_value_field_offset": self.final_value_field_offset,
            "planned_value_offset": self.planned_value_offset,
            "shift": self.shift,
            "unshifted_value_buffer_offset": self.unshifted_value_buffer_offset,
        }


@dataclass(frozen=True)
class PhaseOneIfdPointerPatchPlan:
    pointer_field_range: PhaseOneByteRange
    original_ifd_start: int
    planned_ifd_start: int
    rewrite_required: bool
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "original_ifd_start": self.original_ifd_start,
            "planned_ifd_start": self.planned_ifd_start,
            "pointer_field_range": self.pointer_field_range.to_json(),
            "rewrite_required": self.rewrite_required,
        }


@dataclass(frozen=True)
class PhaseOneIfdEntryRebuildOperation:
    index: int
    tag_id: int
    tag_name: str
    action: PhaseOneIfdEntryAction
    storage: PhaseOneIfdValueStorage
    entry_range: PhaseOneByteRange
    original_value_range: PhaseOneByteRange
    planned_value_range: PhaseOneByteRange
    format_size: int | None
    format_name: PhaseOneIfdFormatName
    original_size: int
    planned_size: int
    value_or_offset: int
    directory_buffer_entry_offset: int
    planned_value_field: int | None
    padding: PhaseOneValuePaddingPlan
    serial_encoding: PhaseOneSerialNumberEncoding | None
    nested_sensor_calibration_plan: PhaseOneIfdRebuildPlan | None
    fixup: PhaseOneValueOffsetFixupPlan | None
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "directory_buffer_entry_offset": self.directory_buffer_entry_offset,
            "entry_range": self.entry_range.to_json(),
            "fixup": self.fixup.to_json() if self.fixup is not None else None,
            "format_name": self.format_name,
            "format_size": self.format_size,
            "index": self.index,
            "nested_sensor_calibration_plan": (
                self.nested_sensor_calibration_plan.to_json()
                if self.nested_sensor_calibration_plan is not None
                else None
            ),
            "original_size": self.original_size,
            "original_value_range": self.original_value_range.to_json(),
            "padding": self.padding.to_json(),
            "planned_size": self.planned_size,
            "planned_value_field": self.planned_value_field,
            "planned_value_range": self.planned_value_range.to_json(),
            "serial_encoding": (
                self.serial_encoding.to_json() if self.serial_encoding is not None else None
            ),
            "storage": self.storage,
            "tag_id": f"0x{self.tag_id:04x}",
            "tag_name": self.tag_name,
            "value_or_offset": self.value_or_offset,
        }


@dataclass(frozen=True)
class PhaseOneIfdBufferLayoutPlan:
    header_buffer_length: int
    value_buffer_length: int
    directory_buffer_length: int
    planned_ifd_start: int
    final_rebuilt_length: int

    def to_json(self) -> JsonObject:
        return {
            "directory_buffer_length": self.directory_buffer_length,
            "final_rebuilt_length": self.final_rebuilt_length,
            "header_buffer_length": self.header_buffer_length,
            "planned_ifd_start": self.planned_ifd_start,
            "value_buffer_length": self.value_buffer_length,
        }


@dataclass(frozen=True)
class PhaseOneIfdRebuildPlan:
    status: PhaseOneIfdRebuildPlanStatus
    can_mutate: bool
    ifd_kind: PhaseOneIfdKind | None
    byte_order: PhaseOneByteOrder | None
    directory_offset: int | None
    ifd_start: int | None
    entry_size: int | None
    entry_count: int | None
    operations: tuple[PhaseOneIfdEntryRebuildOperation, ...]
    fixups: tuple[PhaseOneValueOffsetFixupPlan, ...]
    pointer_patch: PhaseOneIfdPointerPatchPlan | None
    buffer_layout: PhaseOneIfdBufferLayoutPlan | None
    safety_gates: tuple[PhaseOneRawSafetyGate, ...]
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "buffer_layout": (
                self.buffer_layout.to_json() if self.buffer_layout is not None else None
            ),
            "byte_order": self.byte_order,
            "can_mutate": self.can_mutate,
            "directory_offset": self.directory_offset,
            "entry_count": self.entry_count,
            "entry_size": self.entry_size,
            "fixups": [fixup.to_json() for fixup in self.fixups],
            "ifd_kind": self.ifd_kind,
            "ifd_start": self.ifd_start,
            "operations": [operation.to_json() for operation in self.operations],
            "pointer_patch": (
                self.pointer_patch.to_json() if self.pointer_patch is not None else None
            ),
            "safety_gates": list(self.safety_gates),
            "status": self.status,
        }


@dataclass(frozen=True)
class PhaseOneIfdByteEmission:
    status: Literal["rebuilt", "unsupported"]
    can_emit: bool
    rebuilt_block: bytes | None
    rebuilt_length: int
    applied_fixups: tuple[PhaseOneValueOffsetFixupPlan, ...]
    pointer_patch: PhaseOneIfdPointerPatchPlan | None
    evidence_ids: tuple[PhaseOneEvidenceId, ...]

    def emit(self) -> bytes:
        if not self.can_emit or self.rebuilt_block is None:
            raise ValueError("Phase One IFD byte emission is gated")
        return self.rebuilt_block

    def to_json(self) -> JsonObject:
        return {
            "applied_fixups": [fixup.to_json() for fixup in self.applied_fixups],
            "can_emit": self.can_emit,
            "pointer_patch": (
                self.pointer_patch.to_json() if self.pointer_patch is not None else None
            ),
            "rebuilt_hex": self.rebuilt_block.hex() if self.rebuilt_block is not None else None,
            "rebuilt_length": self.rebuilt_length,
            "status": self.status,
        }


def build_phaseone_ifd_rebuild_plan(
    data: bytes,
    serial_number: str | None = None,
    directory_offset: int | None = None,
) -> PhaseOneIfdRebuildPlan:
    """Plan an ExifTool-style PhaseOne IFD rebuild without emitting rebuilt bytes."""

    header = (
        inspect_phaseone_ifd_header(data)
        if directory_offset is None
        else inspect_phaseone_ifd_header_at(data, directory_offset)
    )
    evidence_ids = phaseone_ifd_rebuild_evidence_ids()
    safety_gates = phaseone_ifd_rebuild_safety_gates()
    if header is None:
        return unsupported_phaseone_ifd_rebuild_plan(safety_gates, evidence_ids)

    enumerated = enumerate_phaseone_ifd_rebuild_operations(
        data=data,
        directory_offset=header.directory_offset,
        ifd_kind=header.ifd_kind,
        byte_order=header.byte_order,
        ifd_start=header.ifd_start,
        entry_size=header.entry_size,
        entry_count=header.entry_count,
        serial_number=serial_number,
    )
    if enumerated is None:
        return unsupported_phaseone_ifd_rebuild_plan(safety_gates, evidence_ids)

    operations, fixups, buffer_layout, pointer_patch = enumerated
    return PhaseOneIfdRebuildPlan(
        status="source_mapped_non_mutating",
        can_mutate=False,
        ifd_kind=header.ifd_kind,
        byte_order=header.byte_order,
        directory_offset=header.directory_offset,
        ifd_start=header.ifd_start,
        entry_size=header.entry_size,
        entry_count=header.entry_count,
        operations=operations,
        fixups=fixups,
        pointer_patch=pointer_patch,
        buffer_layout=buffer_layout,
        safety_gates=safety_gates,
        evidence_ids=evidence_ids,
    )


def rebuild_phaseone_ifd_bytes(
    data: bytes,
    serial_number: str | None = None,
    directory_offset: int | None = None,
) -> PhaseOneIfdByteEmission:
    """Emit an isolated PhaseOne directory block from the source-backed rebuild plan."""

    plan = build_phaseone_ifd_rebuild_plan(
        data,
        serial_number=serial_number,
        directory_offset=directory_offset,
    )
    if (
        plan.status != "source_mapped_non_mutating"
        or plan.directory_offset is None
        or plan.ifd_start is None
        or plan.entry_size is None
        or plan.byte_order is None
        or plan.buffer_layout is None
        or plan.pointer_patch is None
    ):
        return unsupported_phaseone_ifd_byte_emission(plan)

    rebuilt = emit_phaseone_ifd_rebuild_plan(data, plan)
    if rebuilt is None:
        return unsupported_phaseone_ifd_byte_emission(plan)
    return PhaseOneIfdByteEmission(
        status="rebuilt",
        can_emit=True,
        rebuilt_block=rebuilt,
        rebuilt_length=len(rebuilt),
        applied_fixups=plan.fixups,
        pointer_patch=plan.pointer_patch,
        evidence_ids=plan.evidence_ids,
    )


def emit_phaseone_ifd_rebuild_plan(
    data: bytes,
    plan: PhaseOneIfdRebuildPlan,
) -> bytes | None:
    if (
        plan.directory_offset is None
        or plan.ifd_start is None
        or plan.entry_size is None
        or plan.byte_order is None
        or plan.buffer_layout is None
        or plan.pointer_patch is None
    ):
        return None

    directory_offset = plan.directory_offset
    header_start = directory_offset
    header_end = directory_offset + PHASEONE_HEADER_SIZE
    directory_prefix_start = directory_offset + plan.ifd_start
    directory_prefix_end = directory_prefix_start + PHASEONE_DIRECTORY_PREFIX_SIZE
    if header_end > len(data) or directory_prefix_end > len(data):
        return None

    header_buffer = bytearray(data[header_start:header_end])
    value_buffer = bytearray()
    directory_buffer = bytearray(data[directory_prefix_start:directory_prefix_end])
    for operation in plan.operations:
        value = phaseone_rebuilt_operation_value(data, operation)
        if value is None:
            return None
        directory_buffer.extend(
            data[
                operation.entry_range.start_offset : operation.entry_range.start_offset
                + plan.entry_size
                - 8
            ]
        )
        directory_buffer.extend(write_uint(operation.planned_size, plan.byte_order))
        padded_value = phaseone_padded_value(value, operation.planned_size)
        if operation.storage == "inline_value_field":
            directory_buffer.extend(padded_value)
        elif operation.storage == "header_buffer_put_first":
            directory_buffer.extend(write_uint(len(header_buffer), plan.byte_order))
            header_buffer.extend(padded_value)
        else:
            directory_buffer.extend(write_uint(len(value_buffer), plan.byte_order))
            value_buffer.extend(padded_value)

    for fixup in plan.fixups:
        write_uint_into(
            directory_buffer,
            fixup.directory_buffer_field_offset,
            fixup.planned_value_offset,
            plan.byte_order,
        )
    write_uint_into(header_buffer, 8, plan.buffer_layout.planned_ifd_start, plan.byte_order)
    return bytes(header_buffer + value_buffer + directory_buffer)


def phaseone_rebuilt_operation_value(
    data: bytes,
    operation: PhaseOneIfdEntryRebuildOperation,
) -> bytes | None:
    if operation.action == "rewrite_serial_number":
        if operation.serial_encoding is None:
            return None
        return bytes.fromhex(operation.serial_encoding.encoded_hex)
    if operation.action == "rewrite_sensor_calibration_subifd":
        value = data[
            operation.original_value_range.start_offset : operation.original_value_range.end_offset
        ]
        emission = rebuild_phaseone_ifd_bytes(
            value,
            serial_number=phaseone_nested_serial_number(operation),
            directory_offset=0,
        )
        return emission.emit() if emission.can_emit else None
    if operation.original_size > PHASEONE_INLINE_VALUE_SIZE:
        start_offset = operation.original_value_range.start_offset
        return data[start_offset : start_offset + operation.original_size]
    value_field = data[
        operation.original_value_range.start_offset : operation.original_value_range.start_offset
        + PHASEONE_INLINE_VALUE_SIZE
    ]
    if len(value_field) < PHASEONE_INLINE_VALUE_SIZE:
        return None
    if operation.original_size == PHASEONE_INLINE_VALUE_SIZE:
        return value_field
    if operation.original_size == 0:
        return b""
    return value_field[: operation.original_size]


def phaseone_nested_serial_number(operation: PhaseOneIfdEntryRebuildOperation) -> str | None:
    nested_plan = operation.nested_sensor_calibration_plan
    if nested_plan is None:
        return None
    for nested_operation in nested_plan.operations:
        if nested_operation.serial_encoding is not None:
            return nested_operation.serial_encoding.requested_value
    return None


def phaseone_padded_value(value: bytes, planned_size: int) -> bytes:
    value = value[:planned_size]
    padding_length = phaseone_value_padding_length(planned_size)
    if padding_length:
        return value + b"\0" * padding_length
    return value


def write_uint(value: int, byte_order: PhaseOneByteOrder) -> bytes:
    return value.to_bytes(4, byte_order)


def write_uint_into(
    buffer: bytearray,
    offset: int,
    value: int,
    byte_order: PhaseOneByteOrder,
) -> None:
    buffer[offset : offset + 4] = write_uint(value, byte_order)


def inspect_phaseone_ifd_header_at(
    data: bytes,
    directory_offset: int,
) -> PhaseOneIfdHeaderProbe | None:
    if directory_offset < 0 or directory_offset + PHASEONE_HEADER_SIZE > len(data):
        return None
    byte_order = phaseone_byte_order(data, directory_offset)
    if byte_order is None:
        return None
    entry_size = phaseone_entry_size(data, directory_offset)
    if entry_size is None:
        return None
    ifd_start = read_uint(data, directory_offset + 8, byte_order)
    dir_len = len(data) - directory_offset
    if ifd_start + PHASEONE_DIRECTORY_PREFIX_SIZE > dir_len:
        return None
    entry_count = read_uint(data, directory_offset + ifd_start, byte_order)
    if entry_count < 2 or entry_count > PHASEONE_MAX_ENTRY_COUNT:
        return None
    ifd_end = ifd_start + PHASEONE_DIRECTORY_PREFIX_SIZE + entry_size * entry_count
    if ifd_end > dir_len:
        return None

    ifd_kind: PhaseOneIfdKind = (
        "phaseone_main_ifd" if entry_size == PHASEONE_MAIN_ENTRY_SIZE else "sensor_calibration_ifd"
    )
    return PhaseOneIfdHeaderProbe(
        directory_offset=directory_offset,
        byte_order=byte_order,
        ifd_kind=ifd_kind,
        entry_size=entry_size,
        ifd_start=ifd_start,
        entry_count=entry_count,
    )


def enumerate_phaseone_ifd_rebuild_operations(
    data: bytes,
    directory_offset: int,
    ifd_kind: PhaseOneIfdKind,
    byte_order: PhaseOneByteOrder,
    ifd_start: int,
    entry_size: int,
    entry_count: int | None,
    serial_number: str | None,
) -> (
    tuple[
        tuple[PhaseOneIfdEntryRebuildOperation, ...],
        tuple[PhaseOneValueOffsetFixupPlan, ...],
        PhaseOneIfdBufferLayoutPlan,
        PhaseOneIfdPointerPatchPlan,
    ]
    | None
):
    if entry_count is None:
        return None
    dir_len = len(data) - directory_offset
    ifd_end = ifd_start + PHASEONE_DIRECTORY_PREFIX_SIZE + entry_size * entry_count
    if ifd_end > dir_len:
        return None

    operations: list[PhaseOneIfdEntryRebuildOperation] = []
    fixups: list[PhaseOneValueOffsetFixupPlan] = []
    header_buffer_length = PHASEONE_HEADER_SIZE
    value_buffer_length = 0
    directory_buffer_length = PHASEONE_DIRECTORY_PREFIX_SIZE
    entries_start = directory_offset + ifd_start + PHASEONE_DIRECTORY_PREFIX_SIZE

    for index in range(entry_count):
        entry_offset = entries_start + index * entry_size
        operation = build_phaseone_entry_rebuild_operation(
            data=data,
            directory_offset=directory_offset,
            dir_len=dir_len,
            ifd_kind=ifd_kind,
            byte_order=byte_order,
            entry_size=entry_size,
            entry_offset=entry_offset,
            index=index,
            directory_buffer_entry_offset=directory_buffer_length,
            header_buffer_length=header_buffer_length,
            value_buffer_length=value_buffer_length,
            serial_number=serial_number,
        )
        if operation is None:
            return None
        operations.append(operation)
        if operation.fixup is not None:
            fixups.append(operation.fixup)
        directory_buffer_length += entry_size
        if operation.storage == "header_buffer_put_first":
            header_buffer_length += operation.padding.padded_length
        elif operation.storage == "value_buffer_with_fixup":
            value_buffer_length += operation.padding.padded_length

    planned_ifd_start = header_buffer_length + value_buffer_length
    final_rebuilt_length = planned_ifd_start + directory_buffer_length
    buffer_layout = PhaseOneIfdBufferLayoutPlan(
        header_buffer_length=header_buffer_length,
        value_buffer_length=value_buffer_length,
        directory_buffer_length=directory_buffer_length,
        planned_ifd_start=planned_ifd_start,
        final_rebuilt_length=final_rebuilt_length,
    )
    shifted_fixups = tuple(
        PhaseOneValueOffsetFixupPlan(
            entry_index=fixup.entry_index,
            directory_buffer_field_offset=fixup.directory_buffer_field_offset,
            final_value_field_offset=planned_ifd_start + fixup.directory_buffer_field_offset,
            unshifted_value_buffer_offset=fixup.unshifted_value_buffer_offset,
            shift=header_buffer_length,
            planned_value_offset=header_buffer_length + fixup.unshifted_value_buffer_offset,
            evidence_ids=fixup.evidence_ids,
        )
        for fixup in fixups
    )
    operations = [
        operation_with_final_offsets(operation, shifted_fixups, planned_ifd_start)
        for operation in operations
    ]
    pointer_patch = PhaseOneIfdPointerPatchPlan(
        pointer_field_range=PhaseOneByteRange(directory_offset + 8, directory_offset + 12),
        original_ifd_start=ifd_start,
        planned_ifd_start=planned_ifd_start,
        rewrite_required=planned_ifd_start != ifd_start,
        evidence_ids=(PHASEONE_WRITE_SOURCE,),
    )
    return tuple(operations), shifted_fixups, buffer_layout, pointer_patch


def build_phaseone_entry_rebuild_operation(
    data: bytes,
    directory_offset: int,
    dir_len: int,
    ifd_kind: PhaseOneIfdKind,
    byte_order: PhaseOneByteOrder,
    entry_size: int,
    entry_offset: int,
    index: int,
    directory_buffer_entry_offset: int,
    header_buffer_length: int,
    value_buffer_length: int,
    serial_number: str | None,
) -> PhaseOneIfdEntryRebuildOperation | None:
    entry_range = PhaseOneByteRange(entry_offset, entry_offset + entry_size)
    tag_id = read_uint(data, entry_offset, byte_order)
    format_size = (
        read_uint(data, entry_offset + 4, byte_order)
        if entry_size == PHASEONE_MAIN_ENTRY_SIZE
        else None
    )
    original_size = read_uint(data, entry_offset + entry_size - 8, byte_order)
    value_or_offset = read_uint(data, entry_offset + entry_size - 4, byte_order)
    if original_size > PHASEONE_MAX_VALUE_SIZE:
        return None
    original_value_range = phaseone_original_value_range(
        directory_offset=directory_offset,
        dir_len=dir_len,
        entry_offset=entry_offset,
        entry_size=entry_size,
        original_size=original_size,
        value_or_offset=value_or_offset,
    )
    if original_value_range is None:
        return None

    tag_name = phaseone_tag_name(ifd_kind, tag_id)
    format_name = phaseone_entry_format_name(ifd_kind, tag_id, format_size)
    serial_encoding = phaseone_serial_encoding(tag_id, serial_number, format_name)
    nested_plan = phaseone_nested_sensor_calibration_plan(
        data=data,
        original_value_range=original_value_range,
        ifd_kind=ifd_kind,
        tag_id=tag_id,
        serial_number=serial_number,
    )
    if (
        tag_id == PHASEONE_SENSOR_CALIBRATION_TAG
        and nested_plan is not None
        and nested_plan.buffer_layout is not None
    ):
        planned_size = nested_plan.buffer_layout.final_rebuilt_length
        action: PhaseOneIfdEntryAction = "rewrite_sensor_calibration_subifd"
    elif serial_encoding is not None and format_name != "invalid":
        planned_size = serial_encoding.encoded_length
        action = "rewrite_serial_number"
    elif is_phaseone_put_first_tag(ifd_kind, tag_id) and original_size > PHASEONE_INLINE_VALUE_SIZE:
        planned_size = original_size
        action = "copy_put_first_value"
    elif original_size > PHASEONE_INLINE_VALUE_SIZE:
        planned_size = original_size
        action = "copy_deferred_value"
    else:
        planned_size = original_size
        action = "copy_inline_value"

    padding = phaseone_value_padding_plan(planned_size)
    storage = phaseone_value_storage(ifd_kind, tag_id, planned_size)
    planned_value_range = phaseone_planned_value_range(
        storage=storage,
        entry_size=entry_size,
        index=index,
        header_buffer_length=header_buffer_length,
        value_buffer_length=value_buffer_length,
        padded_length=padding.padded_length,
    )
    unshifted_pointer = value_buffer_length if storage == "value_buffer_with_fixup" else None
    directory_buffer_value_field_offset = (
        directory_buffer_entry_offset + entry_size - PHASEONE_INLINE_VALUE_SIZE
    )
    fixup = (
        PhaseOneValueOffsetFixupPlan(
            entry_index=index,
            directory_buffer_field_offset=directory_buffer_value_field_offset,
            final_value_field_offset=0,
            unshifted_value_buffer_offset=value_buffer_length,
            shift=0,
            planned_value_offset=0,
            evidence_ids=(PHASEONE_WRITE_SOURCE,),
        )
        if storage == "value_buffer_with_fixup"
        else None
    )
    evidence_ids = phaseone_entry_evidence_ids(
        ifd_kind=ifd_kind,
        tag_id=tag_id,
        action=action,
    )
    return PhaseOneIfdEntryRebuildOperation(
        index=index,
        tag_id=tag_id,
        tag_name=tag_name,
        action=action,
        storage=storage,
        entry_range=entry_range,
        original_value_range=original_value_range,
        planned_value_range=planned_value_range,
        format_size=format_size,
        format_name=format_name,
        original_size=original_size,
        planned_size=planned_size,
        value_or_offset=value_or_offset,
        directory_buffer_entry_offset=directory_buffer_entry_offset,
        planned_value_field=unshifted_pointer,
        padding=padding,
        serial_encoding=serial_encoding,
        nested_sensor_calibration_plan=nested_plan,
        fixup=fixup,
        evidence_ids=evidence_ids,
    )


def operation_with_final_offsets(
    operation: PhaseOneIfdEntryRebuildOperation,
    shifted_fixups: tuple[PhaseOneValueOffsetFixupPlan, ...],
    planned_ifd_start: int,
) -> PhaseOneIfdEntryRebuildOperation:
    shifted_fixup = (
        next(fixup for fixup in shifted_fixups if fixup.entry_index == operation.index)
        if operation.fixup is not None
        else None
    )
    if shifted_fixup is not None:
        planned_value_range = PhaseOneByteRange(
            shifted_fixup.planned_value_offset,
            shifted_fixup.planned_value_offset + operation.padding.padded_length,
        )
        planned_value_field = shifted_fixup.planned_value_offset
    elif operation.storage == "inline_value_field":
        planned_value_field_offset = (
            planned_ifd_start
            + operation.directory_buffer_entry_offset
            + operation.entry_range.length
            - PHASEONE_INLINE_VALUE_SIZE
        )
        planned_value_range = PhaseOneByteRange(
            planned_value_field_offset,
            planned_value_field_offset + PHASEONE_INLINE_VALUE_SIZE,
        )
        planned_value_field = None
    else:
        planned_value_range = operation.planned_value_range
        planned_value_field = operation.planned_value_field
    return PhaseOneIfdEntryRebuildOperation(
        index=operation.index,
        tag_id=operation.tag_id,
        tag_name=operation.tag_name,
        action=operation.action,
        storage=operation.storage,
        entry_range=operation.entry_range,
        original_value_range=operation.original_value_range,
        planned_value_range=planned_value_range,
        format_size=operation.format_size,
        format_name=operation.format_name,
        original_size=operation.original_size,
        planned_size=operation.planned_size,
        value_or_offset=operation.value_or_offset,
        directory_buffer_entry_offset=operation.directory_buffer_entry_offset,
        planned_value_field=planned_value_field,
        padding=operation.padding,
        serial_encoding=operation.serial_encoding,
        nested_sensor_calibration_plan=operation.nested_sensor_calibration_plan,
        fixup=shifted_fixup,
        evidence_ids=operation.evidence_ids,
    )


def phaseone_original_value_range(
    directory_offset: int,
    dir_len: int,
    entry_offset: int,
    entry_size: int,
    original_size: int,
    value_or_offset: int,
) -> PhaseOneByteRange | None:
    if original_size > PHASEONE_INLINE_VALUE_SIZE:
        if value_or_offset + original_size > dir_len:
            return None
        start_offset = directory_offset + value_or_offset
        return PhaseOneByteRange(start_offset, start_offset + original_size)
    value_field_offset = entry_offset + entry_size - PHASEONE_INLINE_VALUE_SIZE
    return PhaseOneByteRange(value_field_offset, value_field_offset + PHASEONE_INLINE_VALUE_SIZE)


def phaseone_planned_value_range(
    storage: PhaseOneIfdValueStorage,
    entry_size: int,
    index: int,
    header_buffer_length: int,
    value_buffer_length: int,
    padded_length: int,
) -> PhaseOneByteRange:
    if storage == "header_buffer_put_first":
        return PhaseOneByteRange(header_buffer_length, header_buffer_length + padded_length)
    if storage == "value_buffer_with_fixup":
        start_offset = header_buffer_length + value_buffer_length
        return PhaseOneByteRange(start_offset, start_offset + padded_length)
    value_field_offset = (
        PHASEONE_DIRECTORY_PREFIX_SIZE
        + index * entry_size
        + entry_size
        - PHASEONE_INLINE_VALUE_SIZE
    )
    return PhaseOneByteRange(value_field_offset, value_field_offset + PHASEONE_INLINE_VALUE_SIZE)


def phaseone_value_storage(
    ifd_kind: PhaseOneIfdKind,
    tag_id: int,
    planned_size: int,
) -> PhaseOneIfdValueStorage:
    if planned_size <= PHASEONE_INLINE_VALUE_SIZE:
        return "inline_value_field"
    if is_phaseone_put_first_tag(ifd_kind, tag_id):
        return "header_buffer_put_first"
    return "value_buffer_with_fixup"


def phaseone_nested_sensor_calibration_plan(
    data: bytes,
    original_value_range: PhaseOneByteRange,
    ifd_kind: PhaseOneIfdKind,
    tag_id: int,
    serial_number: str | None,
) -> PhaseOneIfdRebuildPlan | None:
    if (
        serial_number is None
        or ifd_kind != "phaseone_main_ifd"
        or tag_id != PHASEONE_SENSOR_CALIBRATION_TAG
    ):
        return None
    value = data[original_value_range.start_offset : original_value_range.end_offset]
    nested_plan = build_phaseone_ifd_rebuild_plan(
        value,
        serial_number=serial_number,
        directory_offset=0,
    )
    return nested_plan if nested_plan.status == "source_mapped_non_mutating" else None


def phaseone_serial_encoding(
    tag_id: int,
    serial_number: str | None,
    format_name: PhaseOneIfdFormatName,
) -> PhaseOneSerialNumberEncoding | None:
    if serial_number is None or tag_id not in phaseone_serial_number_tags():
        return None
    encoded = serial_number.encode("latin-1")
    return PhaseOneSerialNumberEncoding(
        requested_value=serial_number,
        encoding="latin-1",
        format_name=format_name,
        encoded_hex=encoded.hex(),
        encoded_length=len(encoded),
        count_can_change=format_name in ("string", "undef"),
        evidence_ids=(PHASEONE_SERIAL_SOURCE, PHASEONE_SENSOR_CALIBRATION_SOURCE),
    )


def phaseone_value_padding_plan(unpadded_length: int) -> PhaseOneValuePaddingPlan:
    padding_length = phaseone_value_padding_length(unpadded_length)
    return PhaseOneValuePaddingPlan(
        unpadded_length=unpadded_length,
        padding_length=padding_length,
        padded_length=unpadded_length + padding_length,
        pads_zero_length_to_four_bytes=unpadded_length == 0,
        evidence_ids=(PHASEONE_WRITE_SOURCE,),
    )


def phaseone_value_padding_length(unpadded_length: int) -> int:
    remainder = unpadded_length & 0x03
    if remainder or unpadded_length == 0:
        return 4 - remainder
    return 0


def phaseone_entry_format_name(
    ifd_kind: PhaseOneIfdKind,
    tag_id: int,
    format_size: int | None,
) -> PhaseOneIfdFormatName:
    if ifd_kind == "sensor_calibration_ifd":
        if tag_id == PHASEONE_SENSOR_SERIAL_NUMBER_TAG:
            return "string"
        return "undef"
    if format_size is None:
        return "invalid"
    base_format_name = PHASEONE_FORMAT_NAMES.get(format_size, "invalid")
    if base_format_name == "invalid":
        return "invalid"
    if tag_id == PHASEONE_SERIAL_NUMBER_TAG:
        return "string"
    return base_format_name


def phaseone_tag_name(ifd_kind: PhaseOneIfdKind, tag_id: int) -> str:
    if tag_id == PHASEONE_SERIAL_NUMBER_TAG and ifd_kind == "phaseone_main_ifd":
        return "SerialNumber"
    if tag_id == PHASEONE_SENSOR_SERIAL_NUMBER_TAG and ifd_kind == "sensor_calibration_ifd":
        return "SerialNumber"
    if tag_id == PHASEONE_SENSOR_CALIBRATION_TAG and ifd_kind == "phaseone_main_ifd":
        return "SensorCalibration"
    if tag_id == PHASEONE_RAW_DATA_TAG and ifd_kind == "phaseone_main_ifd":
        return "RawData"
    return f"PhaseOne_0x{tag_id:04x}"


def is_phaseone_put_first_tag(ifd_kind: PhaseOneIfdKind, tag_id: int) -> bool:
    return ifd_kind == "phaseone_main_ifd" and tag_id == PHASEONE_RAW_DATA_TAG


def phaseone_serial_number_tags() -> frozenset[int]:
    return frozenset((PHASEONE_SERIAL_NUMBER_TAG, PHASEONE_SENSOR_SERIAL_NUMBER_TAG))


def phaseone_entry_evidence_ids(
    ifd_kind: PhaseOneIfdKind,
    tag_id: int,
    action: PhaseOneIfdEntryAction,
) -> tuple[PhaseOneEvidenceId, ...]:
    evidence_ids: list[PhaseOneEvidenceId] = [PHASEONE_WRITE_SOURCE]
    evidence_ids.append(
        PHASEONE_MAIN_SOURCE
        if ifd_kind == "phaseone_main_ifd"
        else PHASEONE_SENSOR_CALIBRATION_SOURCE
    )
    if action == "rewrite_serial_number":
        evidence_ids.append(PHASEONE_SERIAL_SOURCE)
    if tag_id in (PHASEONE_SENSOR_CALIBRATION_TAG, PHASEONE_SENSOR_SERIAL_NUMBER_TAG):
        evidence_ids.append(PHASEONE_SENSOR_CALIBRATION_SOURCE)
    return unique_evidence_ids(tuple(evidence_ids))


def phaseone_ifd_rebuild_safety_gates() -> tuple[PhaseOneRawSafetyGate, ...]:
    return (
        "defer_without_phaseone_ifd_rebuilder",
        "defer_without_entry_size_validation",
        "defer_without_serial_value_encoder",
        "defer_without_sensor_calibration_rewriter",
        "defer_without_value_padding",
        "defer_without_value_offset_fixups",
        "defer_without_phaseone_ifd_pointer_patch",
    )


def phaseone_ifd_rebuild_evidence_ids() -> tuple[PhaseOneEvidenceId, ...]:
    return (
        PHASEONE_MAIN_SOURCE,
        PHASEONE_SERIAL_SOURCE,
        PHASEONE_SENSOR_CALIBRATION_SOURCE,
        PHASEONE_WRITE_SOURCE,
    )


def unsupported_phaseone_ifd_rebuild_plan(
    safety_gates: tuple[PhaseOneRawSafetyGate, ...],
    evidence_ids: tuple[PhaseOneEvidenceId, ...],
) -> PhaseOneIfdRebuildPlan:
    return PhaseOneIfdRebuildPlan(
        status="unsupported",
        can_mutate=False,
        ifd_kind=None,
        byte_order=None,
        directory_offset=None,
        ifd_start=None,
        entry_size=None,
        entry_count=None,
        operations=(),
        fixups=(),
        pointer_patch=None,
        buffer_layout=None,
        safety_gates=safety_gates,
        evidence_ids=evidence_ids,
    )


def unsupported_phaseone_ifd_byte_emission(
    plan: PhaseOneIfdRebuildPlan,
) -> PhaseOneIfdByteEmission:
    return PhaseOneIfdByteEmission(
        status="unsupported",
        can_emit=False,
        rebuilt_block=None,
        rebuilt_length=0,
        applied_fixups=(),
        pointer_patch=plan.pointer_patch,
        evidence_ids=plan.evidence_ids,
    )
