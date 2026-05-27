"""Source-grounded, non-mutating RED/R3D metadata transaction plans.

The planner mirrors ExifTool's Red.pm read boundaries: validate the first
big-endian RED block, extract RED1/RED2 header fields, locate the first RED
directory, walk length/tag entries with the high-nibble format code, and keep
all container/media bytes behind explicit emission gates.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

RED_DIRECTORY_MIN_LENGTH = 300
RED_DIRECTORY_MAX_LENGTH = 2048
RED1_DIRECTORY_OFFSET = 0x22
RED2_DIRECTORY_BASE_OFFSET = 0x44
RED2_ALIGNMENT = 0x1000

type RedPlanStatus = Literal["planned", "unsupported"]
type RedVersion = Literal["1", "2"]
type RedEvidenceId = str
type RedBlockStatus = Literal["valid", "invalid_size", "truncated"]
type RedDirectoryStatus = Literal["found", "fallback_found", "not_found", "not_read"]
type RedMetadataResponsibility = Literal[
    "clip_metadata",
    "camera_metadata",
    "timecode_metadata",
    "lens_metadata",
    "audio_metadata",
    "video_metadata",
]
type RedActionKind = Literal[
    "validate_r3d_header",
    "detect_r3d_blocks",
    "extract_red_header",
    "locate_red_directory",
    "read_red_directory_entry",
    "preserve_payload",
    "plan_metadata_rewrite",
    "no_metadata_mutation",
]
type RedPreservationKind = Literal[
    "header_block_payload",
    "directory_payload",
    "media_payload",
    "alignment_padding",
    "trailing_payload",
]
type RedEmissionGateCode = Literal[
    "truncated_r3d_header",
    "unsupported_r3d_signature",
    "invalid_first_block_size",
    "truncated_first_block",
    "truncated_red1_directory_block",
    "truncated_red2_directory_counts",
    "red_directory_not_found",
    "malformed_red_directory_entry",
    "unknown_red_format_code",
    "red_metadata_rewrite_not_supported",
    "red_header_rewrite_required",
    "red_media_payload_rewrite_required",
    "planner_is_non_mutating",
    "full_red_writer_not_implemented",
]
type RedFormatName = Literal[
    "int8u",
    "string",
    "float",
    "int16u",
    "int8s",
    "int32s",
    "undef",
    "int32u",
]

RED_FORMATS: dict[int, RedFormatName] = {
    0: "int8u",
    1: "string",
    2: "float",
    3: "int8u",
    4: "int16u",
    5: "int8s",
    6: "int32s",
    7: "undef",
    8: "int32u",
    9: "undef",
}

RED_DIRECTORY_TAGS: dict[int, tuple[str, RedMetadataResponsibility]] = {
    0x1000: ("StartEdgeCode", "timecode_metadata"),
    0x1001: ("StartTimecode", "timecode_metadata"),
    0x1002: ("OtherDate1", "timecode_metadata"),
    0x1003: ("OtherDate2", "timecode_metadata"),
    0x1004: ("OtherDate3", "timecode_metadata"),
    0x1005: ("DateTimeOriginal", "timecode_metadata"),
    0x1006: ("SerialNumber", "camera_metadata"),
    0x1019: ("CameraType", "camera_metadata"),
    0x101A: ("ReelNumber", "clip_metadata"),
    0x101B: ("Take", "clip_metadata"),
    0x1023: ("DateCreated", "timecode_metadata"),
    0x1024: ("TimeCreated", "timecode_metadata"),
    0x1025: ("FirmwareVersion", "camera_metadata"),
    0x1029: ("ReelTimecode", "timecode_metadata"),
    0x102A: ("StorageType", "camera_metadata"),
    0x1030: ("StorageFormatDate", "timecode_metadata"),
    0x1031: ("StorageFormatTime", "timecode_metadata"),
    0x1032: ("StorageSerialNumber", "camera_metadata"),
    0x1033: ("StorageModel", "camera_metadata"),
    0x1036: ("AspectRatio", "video_metadata"),
    0x1042: ("Revision", "camera_metadata"),
    0x1056: ("OriginalFileName", "clip_metadata"),
    0x106E: ("LensMake", "lens_metadata"),
    0x106F: ("LensNumber", "lens_metadata"),
    0x1070: ("LensModel", "lens_metadata"),
    0x1071: ("Model", "camera_metadata"),
    0x107C: ("CameraOperator", "camera_metadata"),
    0x1086: ("VideoFormat", "video_metadata"),
    0x1096: ("Filter", "lens_metadata"),
    0x10A0: ("Brain", "camera_metadata"),
    0x10A1: ("Sensor", "camera_metadata"),
    0x10BE: ("Quality", "video_metadata"),
    0x200D: ("ColorTemperature", "camera_metadata"),
    0x204B: ("RGBCurves", "camera_metadata"),
    0x2066: ("OriginalFrameRate", "video_metadata"),
    0x4037: ("CropArea", "video_metadata"),
    0x403B: ("ISO", "camera_metadata"),
    0x406A: ("FNumber", "lens_metadata"),
    0x406B: ("FocalLength", "lens_metadata"),
    0x606C: ("FocusDistance", "lens_metadata"),
}

RED_HEADER_SOURCE = "red.header.validation"
RED_BLOCK_SOURCE = "red.block.structure"
RED_HEADER_TAG_SOURCE = "red.header.tags"
RED_DIRECTORY_TABLE_SOURCE = "red.directory.table"
RED_FORMAT_SOURCE = "red.directory.format"
RED_DIRECTORY_LOCATE_SOURCE = "red.directory.locate"
RED_DIRECTORY_WALK_SOURCE = "red.directory.walk"
RED_AUDIO_BOUNDARY_SOURCE = "red.audio.boundary"
RED_READ_ONLY_SOURCE = "red.read_only"

RED_TRANSACTION_SOURCES = (
    RED_HEADER_SOURCE,
    RED_BLOCK_SOURCE,
    RED_HEADER_TAG_SOURCE,
    RED_DIRECTORY_TABLE_SOURCE,
    RED_FORMAT_SOURCE,
    RED_DIRECTORY_LOCATE_SOURCE,
    RED_DIRECTORY_WALK_SOURCE,
    RED_AUDIO_BOUNDARY_SOURCE,
    RED_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class RedMetadataRewriteRequest:
    replacement_directory_payload: bytes | None = None
    replacement_header_payload: bytes | None = None
    delete_red_directory: bool = False


@dataclass(frozen=True)
class RedBlockPlan:
    index: int
    offset: int
    declared_size: int | None
    block_type: str
    status: RedBlockStatus
    byte_range_start: int
    byte_range_end: int
    payload_range_start: int
    payload_range_end: int
    payload_preserved: bool
    evidence_ids: tuple[RedEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "block_type": self.block_type,
            "byte_range_end": self.byte_range_end,
            "byte_range_start": self.byte_range_start,
            "declared_size": self.declared_size,
            "index": self.index,
            "payload_preserved": self.payload_preserved,
            "payload_range_end": self.payload_range_end,
            "payload_range_start": self.payload_range_start,
            "status": self.status,
        }


@dataclass(frozen=True)
class RedHeaderFieldPlan:
    name: str
    responsibility: RedMetadataResponsibility
    byte_range_start: int
    byte_range_end: int
    raw_payload: bytes
    value_text: str | None
    numeric_value: int | float | None
    evidence_ids: tuple[RedEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range_end": self.byte_range_end,
            "byte_range_start": self.byte_range_start,
            "name": self.name,
            "numeric_value": self.numeric_value,
            "payload_size": len(self.raw_payload),
            "responsibility": self.responsibility,
            "value_text": self.value_text,
        }


@dataclass(frozen=True)
class RedDirectoryEntryPlan:
    tag_id: int
    tag_name: str
    responsibility: RedMetadataResponsibility
    format_code: int
    format_name: RedFormatName
    entry_range_start: int
    entry_range_end: int
    payload_range_start: int
    payload_range_end: int
    raw_payload: bytes
    value_text: str | None
    numeric_values: tuple[int | float, ...]
    evidence_ids: tuple[RedEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "entry_range_end": self.entry_range_end,
            "entry_range_start": self.entry_range_start,
            "format_code": self.format_code,
            "format_name": self.format_name,
            "numeric_values": [value for value in self.numeric_values],
            "payload_range_end": self.payload_range_end,
            "payload_range_start": self.payload_range_start,
            "payload_size": len(self.raw_payload),
            "responsibility": self.responsibility,
            "tag_id": f"0x{self.tag_id:04x}",
            "tag_name": self.tag_name,
            "value_text": self.value_text,
        }


@dataclass(frozen=True)
class RedDirectoryPlan:
    status: RedDirectoryStatus
    data_position: int | None
    directory_start: int | None
    directory_end: int | None
    declared_length: int | None
    fallback_used: bool
    entries: tuple[RedDirectoryEntryPlan, ...]
    reason: RedEmissionGateCode | None
    evidence_ids: tuple[RedEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "data_position": self.data_position,
            "declared_length": self.declared_length,
            "directory_end": self.directory_end,
            "directory_start": self.directory_start,
            "entries": json_object_array(entry.to_json() for entry in self.entries),
            "fallback_used": self.fallback_used,
            "reason": self.reason,
            "status": self.status,
        }


@dataclass(frozen=True)
class RedPreservationPlan:
    kind: RedPreservationKind
    byte_range_start: int
    byte_range_end: int
    payload: bytes
    evidence_ids: tuple[RedEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range_end": self.byte_range_end,
            "byte_range_start": self.byte_range_start,
            "kind": self.kind,
            "payload_size": len(self.payload),
        }


@dataclass(frozen=True)
class RedActionPlan:
    kind: RedActionKind
    byte_range_start: int | None
    byte_range_end: int | None
    reason: str
    evidence_ids: tuple[RedEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range_end": self.byte_range_end,
            "byte_range_start": self.byte_range_start,
            "kind": self.kind,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RedResponsibilityPlan:
    concern: (
        RedMetadataResponsibility
        | Literal[
            "container_validation",
            "atom_chunk_detection",
            "payload_preservation",
            "malformed_truncation_blockers",
            "unsupported_rewrite_gates",
        ]
    )
    tag_names: tuple[str, ...]
    reason: str
    evidence_ids: tuple[RedEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "reason": self.reason,
            "tag_names": [tag_name for tag_name in self.tag_names],
        }


@dataclass(frozen=True)
class RedOutputEmissionGate:
    code: RedEmissionGateCode
    reason: str
    evidence_ids: tuple[RedEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RedMetadataTransactionPlan:
    status: RedPlanStatus
    version: RedVersion | None
    first_block_size: int | None
    blocks: tuple[RedBlockPlan, ...]
    header_fields: tuple[RedHeaderFieldPlan, ...]
    directory: RedDirectoryPlan
    preservation_actions: tuple[RedPreservationPlan, ...]
    actions: tuple[RedActionPlan, ...]
    responsibilities: tuple[RedResponsibilityPlan, ...]
    output_emission_gates: tuple[RedOutputEmissionGate, ...]
    evidence_ids: tuple[RedEvidenceId, ...]
    original_bytes: bytes
    allow_output_emission: bool = False

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return (
            self.allow_output_emission
            and self.status == "planned"
            and not self.output_emission_gates
        )

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"RED metadata transaction output is gated: {gate_codes}")
        return self.original_bytes

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "allow_output_emission": self.allow_output_emission,
            "blocks": json_object_array(block.to_json() for block in self.blocks),
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "directory": self.directory.to_json(),
            "first_block_size": self.first_block_size,
            "header_fields": json_object_array(field.to_json() for field in self.header_fields),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "preservation_actions": json_object_array(
                action.to_json() for action in self.preservation_actions
            ),
            "responsibilities": json_object_array(
                responsibility.to_json() for responsibility in self.responsibilities
            ),
            "status": self.status,
            "version": self.version,
        }


def build_red_metadata_transaction_plan(
    r3d_data: bytes,
    rewrite_request: RedMetadataRewriteRequest | None = None,
    *,
    allow_output_emission: bool = False,
) -> RedMetadataTransactionPlan:
    version, first_block_size, header_gate = validate_header(r3d_data)
    blocks = scan_blocks(r3d_data, version)
    first_block = blocks[0] if blocks else None
    header_fields = build_header_fields(r3d_data, version, first_block)
    directory = build_directory_plan(r3d_data, version, first_block_size)
    preservation_actions = build_preservation_actions(r3d_data, blocks, directory)
    gates = validation_gates(header_gate, first_block, directory)
    if rewrite_request is not None and rewrite_requested(rewrite_request):
        gates.extend(rewrite_gates(rewrite_request))
    if not allow_output_emission:
        gates.extend(non_mutating_default_gates())
    actions = build_actions(
        first_block_size,
        header_fields,
        directory,
        preservation_actions,
        rewrite_request,
    )
    status: RedPlanStatus = "unsupported" if any_validation_gate(gates) else "planned"
    evidence_ids = unique_evidence_ids(
        (
            *RED_TRANSACTION_SOURCES,
            *(source for block in blocks for source in block.evidence_ids),
            *(source for field in header_fields for source in field.evidence_ids),
            *directory.evidence_ids,
            *(source for entry in directory.entries for source in entry.evidence_ids),
            *(source for action in preservation_actions for source in action.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return RedMetadataTransactionPlan(
        status=status,
        version=version,
        first_block_size=first_block_size,
        blocks=blocks,
        header_fields=header_fields,
        directory=directory,
        preservation_actions=preservation_actions,
        actions=actions,
        responsibilities=build_responsibilities(),
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=evidence_ids,
        original_bytes=r3d_data,
        allow_output_emission=allow_output_emission,
    )


def validate_header(
    r3d_data: bytes,
) -> tuple[RedVersion | None, int | None, RedEmissionGateCode | None]:
    if len(r3d_data) < 8:
        return None, None, "truncated_r3d_header"
    if (
        r3d_data[:2] != b"\x00\x00"
        or r3d_data[4:7] != b"RED"
        or r3d_data[7:8]
        not in (
            b"1",
            b"2",
        )
    ):
        return None, int.from_bytes(r3d_data[:4], "big"), "unsupported_r3d_signature"
    version: RedVersion = "1" if r3d_data[7:8] == b"1" else "2"
    first_block_size = int.from_bytes(r3d_data[:4], "big")
    if first_block_size < 8:
        return version, first_block_size, "invalid_first_block_size"
    if first_block_size > len(r3d_data):
        return version, first_block_size, "truncated_first_block"
    return version, first_block_size, None


def scan_blocks(r3d_data: bytes, version: RedVersion | None) -> tuple[RedBlockPlan, ...]:
    blocks: list[RedBlockPlan] = []
    offset = 0
    index = 0
    while offset + 8 <= len(r3d_data):
        declared_size = int.from_bytes(r3d_data[offset : offset + 4], "big")
        block_type = decode_block_type(r3d_data[offset + 4 : offset + 8])
        if declared_size < 8:
            blocks.append(
                RedBlockPlan(
                    index=index,
                    offset=offset,
                    declared_size=declared_size,
                    block_type=block_type,
                    status="invalid_size",
                    byte_range_start=offset,
                    byte_range_end=min(offset + 8, len(r3d_data)),
                    payload_range_start=min(offset + 8, len(r3d_data)),
                    payload_range_end=min(offset + 8, len(r3d_data)),
                    payload_preserved=False,
                    evidence_ids=(RED_BLOCK_SOURCE, RED_HEADER_SOURCE),
                )
            )
            break
        block_end = offset + declared_size
        if block_end > len(r3d_data):
            blocks.append(
                RedBlockPlan(
                    index=index,
                    offset=offset,
                    declared_size=declared_size,
                    block_type=block_type,
                    status="truncated",
                    byte_range_start=offset,
                    byte_range_end=len(r3d_data),
                    payload_range_start=offset + 8,
                    payload_range_end=len(r3d_data),
                    payload_preserved=False,
                    evidence_ids=(RED_BLOCK_SOURCE, RED_HEADER_SOURCE),
                )
            )
            break
        blocks.append(
            RedBlockPlan(
                index=index,
                offset=offset,
                declared_size=declared_size,
                block_type=block_type,
                status="valid",
                byte_range_start=offset,
                byte_range_end=block_end,
                payload_range_start=offset + 8,
                payload_range_end=block_end,
                payload_preserved=True,
                evidence_ids=(RED_BLOCK_SOURCE,),
            )
        )
        index += 1
        offset = next_block_offset(r3d_data, block_end, version)
    return tuple(blocks)


def next_block_offset(r3d_data: bytes, block_end: int, version: RedVersion | None) -> int:
    if version != "2" or block_end >= len(r3d_data):
        return block_end
    aligned = align_up(block_end, RED2_ALIGNMENT)
    if aligned <= len(r3d_data) and all(byte == 0 for byte in r3d_data[block_end:aligned]):
        return aligned
    return block_end


def build_header_fields(
    r3d_data: bytes,
    version: RedVersion | None,
    first_block: RedBlockPlan | None,
) -> tuple[RedHeaderFieldPlan, ...]:
    if version is None or first_block is None or first_block.status != "valid":
        return ()
    fields: list[RedHeaderFieldPlan] = []
    block_end = first_block.byte_range_end
    add_string_header_field(
        fields,
        r3d_data,
        "RedcodeVersion",
        0x07,
        1,
        "video_metadata",
        block_end,
    )
    if version == "1":
        add_int_header_field(fields, r3d_data, "ImageWidth", 0x36, 2, "video_metadata", block_end)
        add_int_header_field(fields, r3d_data, "ImageHeight", 0x3A, 2, "video_metadata", block_end)
        if block_end >= 0x46:
            numerator = int.from_bytes(r3d_data[0x3E:0x42], "big")
            denominator = int.from_bytes(r3d_data[0x42:0x46], "big")
            value = numerator / denominator if denominator else None
            fields.append(
                RedHeaderFieldPlan(
                    name="FrameRate",
                    responsibility="video_metadata",
                    byte_range_start=0x3E,
                    byte_range_end=0x46,
                    raw_payload=r3d_data[0x3E:0x46],
                    value_text=format_number(value),
                    numeric_value=value,
                    evidence_ids=(RED_HEADER_TAG_SOURCE,),
                )
            )
        add_string_header_field(
            fields,
            r3d_data,
            "OriginalFileName",
            0x43,
            32,
            "clip_metadata",
            block_end,
        )
    else:
        add_int_header_field(fields, r3d_data, "ImageWidth", 0x4C, 4, "video_metadata", block_end)
        add_int_header_field(fields, r3d_data, "ImageHeight", 0x50, 4, "video_metadata", block_end)
        if block_end >= 0x5C:
            denominator = int.from_bytes(r3d_data[0x56:0x58], "big")
            high = int.from_bytes(r3d_data[0x58:0x5A], "big")
            low = int.from_bytes(r3d_data[0x5A:0x5C], "big")
            value = ((high * 0x10000) + low) / denominator if denominator else None
            fields.append(
                RedHeaderFieldPlan(
                    name="FrameRate",
                    responsibility="video_metadata",
                    byte_range_start=0x56,
                    byte_range_end=0x5C,
                    raw_payload=r3d_data[0x56:0x5C],
                    value_text=format_number(value),
                    numeric_value=value,
                    evidence_ids=(RED_HEADER_TAG_SOURCE,),
                )
            )
    return tuple(fields)


def add_string_header_field(
    fields: list[RedHeaderFieldPlan],
    r3d_data: bytes,
    name: str,
    offset: int,
    size: int,
    responsibility: RedMetadataResponsibility,
    block_end: int,
) -> None:
    end = offset + size
    if end > block_end:
        return
    payload = r3d_data[offset:end]
    fields.append(
        RedHeaderFieldPlan(
            name=name,
            responsibility=responsibility,
            byte_range_start=offset,
            byte_range_end=end,
            raw_payload=payload,
            value_text=decode_red_string(payload),
            numeric_value=None,
            evidence_ids=(RED_HEADER_TAG_SOURCE,),
        )
    )


def add_int_header_field(
    fields: list[RedHeaderFieldPlan],
    r3d_data: bytes,
    name: str,
    offset: int,
    size: Literal[2, 4],
    responsibility: RedMetadataResponsibility,
    block_end: int,
) -> None:
    end = offset + size
    if end > block_end:
        return
    value = int.from_bytes(r3d_data[offset:end], "big")
    fields.append(
        RedHeaderFieldPlan(
            name=name,
            responsibility=responsibility,
            byte_range_start=offset,
            byte_range_end=end,
            raw_payload=r3d_data[offset:end],
            value_text=str(value),
            numeric_value=value,
            evidence_ids=(RED_HEADER_TAG_SOURCE,),
        )
    )


def build_directory_plan(
    r3d_data: bytes,
    version: RedVersion | None,
    first_block_size: int | None,
) -> RedDirectoryPlan:
    if version is None or first_block_size is None or first_block_size > len(r3d_data):
        return empty_directory_plan(None)
    if version == "1":
        return build_red1_directory_plan(r3d_data, first_block_size)
    return build_red2_directory_plan(r3d_data, first_block_size)


def build_red1_directory_plan(r3d_data: bytes, first_block_size: int) -> RedDirectoryPlan:
    directory_buffer = r3d_data[first_block_size : min(first_block_size + 0x10000, len(r3d_data))]
    if not directory_buffer:
        return empty_directory_plan("truncated_red1_directory_block")
    return locate_directory_in_buffer(
        directory_buffer,
        data_position=first_block_size,
        initial_offset=RED1_DIRECTORY_OFFSET,
    )


def build_red2_directory_plan(r3d_data: bytes, first_block_size: int) -> RedDirectoryPlan:
    directory_buffer = r3d_data[:first_block_size]
    if len(directory_buffer) < RED2_DIRECTORY_BASE_OFFSET:
        return empty_directory_plan("truncated_red2_directory_counts")
    offset = RED2_DIRECTORY_BASE_OFFSET
    offset += directory_buffer[0x40] * 0x18
    offset += directory_buffer[0x41] * 0x14
    offset += directory_buffer[0x42] * 0x10
    return locate_directory_in_buffer(directory_buffer, data_position=0, initial_offset=offset)


def locate_directory_in_buffer(
    directory_buffer: bytes,
    *,
    data_position: int,
    initial_offset: int,
) -> RedDirectoryPlan:
    declared_length: int | None
    entries_offset = initial_offset
    if initial_offset + 8 > len(directory_buffer):
        declared_length = 0
    else:
        declared_length = int.from_bytes(
            directory_buffer[initial_offset : initial_offset + 2],
            "big",
        )
        entries_offset = initial_offset + 2
    if (
        declared_length is None
        or declared_length < RED_DIRECTORY_MIN_LENGTH
        or declared_length >= RED_DIRECTORY_MAX_LENGTH
        or entries_offset + declared_length > len(directory_buffer)
    ):
        fallback_offset = find_directory_fallback(directory_buffer)
        if fallback_offset is None:
            return RedDirectoryPlan(
                status="not_found",
                data_position=data_position,
                directory_start=None,
                directory_end=None,
                declared_length=declared_length,
                fallback_used=False,
                entries=(),
                reason="red_directory_not_found",
                evidence_ids=(RED_DIRECTORY_LOCATE_SOURCE,),
            )
        entries, reason = read_directory_entries(
            directory_buffer,
            data_position=data_position,
            entries_offset=fallback_offset,
            directory_end=len(directory_buffer),
            declared_length=None,
        )
        return RedDirectoryPlan(
            status="fallback_found",
            data_position=data_position,
            directory_start=data_position + fallback_offset,
            directory_end=data_position + len(directory_buffer),
            declared_length=None,
            fallback_used=True,
            entries=entries,
            reason=reason,
            evidence_ids=(RED_DIRECTORY_LOCATE_SOURCE, RED_DIRECTORY_WALK_SOURCE),
        )
    directory_end = entries_offset + declared_length
    entries, reason = read_directory_entries(
        directory_buffer,
        data_position=data_position,
        entries_offset=entries_offset,
        directory_end=directory_end,
        declared_length=declared_length,
    )
    return RedDirectoryPlan(
        status="found",
        data_position=data_position,
        directory_start=data_position + entries_offset,
        directory_end=data_position + directory_end,
        declared_length=declared_length,
        fallback_used=False,
        entries=entries,
        reason=reason,
        evidence_ids=(RED_DIRECTORY_LOCATE_SOURCE, RED_DIRECTORY_WALK_SOURCE),
    )


def read_directory_entries(
    directory_buffer: bytes,
    *,
    data_position: int,
    entries_offset: int,
    directory_end: int,
    declared_length: int | None,
) -> tuple[tuple[RedDirectoryEntryPlan, ...], RedEmissionGateCode | None]:
    entries: list[RedDirectoryEntryPlan] = []
    offset = entries_offset
    while offset + 4 <= directory_end:
        entry_length = int.from_bytes(directory_buffer[offset : offset + 2], "big")
        if entry_length == 0:
            break
        if entry_length < 4 or offset + entry_length > directory_end:
            return tuple(entries), "malformed_red_directory_entry"
        tag_id = int.from_bytes(directory_buffer[offset + 2 : offset + 4], "big")
        format_code = tag_id >> 12
        format_name = RED_FORMATS.get(format_code)
        if format_name is None:
            reason: RedEmissionGateCode | None = (
                "unknown_red_format_code" if declared_length is not None else None
            )
            return tuple(entries), reason
        payload_start = offset + 4
        payload_end = offset + entry_length
        payload = directory_buffer[payload_start:payload_end]
        tag_name, responsibility = RED_DIRECTORY_TAGS.get(
            tag_id,
            (f"UnknownRedTag0x{tag_id:04x}", "camera_metadata"),
        )
        value_text, numeric_values = decode_directory_value(tag_id, format_name, payload)
        entries.append(
            RedDirectoryEntryPlan(
                tag_id=tag_id,
                tag_name=tag_name,
                responsibility=responsibility,
                format_code=format_code,
                format_name=format_name,
                entry_range_start=data_position + offset,
                entry_range_end=data_position + offset + entry_length,
                payload_range_start=data_position + payload_start,
                payload_range_end=data_position + payload_end,
                raw_payload=payload,
                value_text=value_text,
                numeric_values=numeric_values,
                evidence_ids=(
                    RED_DIRECTORY_TABLE_SOURCE,
                    RED_FORMAT_SOURCE,
                    RED_DIRECTORY_WALK_SOURCE,
                ),
            )
        )
        offset += entry_length
    return tuple(entries), None


def decode_directory_value(
    tag_id: int,
    format_name: RedFormatName,
    payload: bytes,
) -> tuple[str | None, tuple[int | float, ...]]:
    if format_name == "string":
        value = convert_string_tag(tag_id, decode_red_string(payload))
        return value, ()
    if format_name == "int8u":
        values = tuple(payload)
        return join_values(values), values
    if format_name == "int8s":
        values = tuple(value - 256 if value > 127 else value for value in payload)
        return join_values(values), values
    if format_name == "int16u":
        values = tuple(
            int.from_bytes(payload[offset : offset + 2], "big")
            for offset in range(0, len(payload) - 1, 2)
        )
        converted = convert_numeric_tag(tag_id, values)
        return join_values(converted), converted
    if format_name in {"int32s", "int32u"}:
        signed = format_name == "int32s"
        values = tuple(
            int.from_bytes(payload[offset : offset + 4], "big", signed=signed)
            for offset in range(0, len(payload) - 3, 4)
        )
        converted = convert_numeric_tag(tag_id, values)
        return join_values(converted), converted
    if format_name == "float":
        float_values: tuple[float, ...] = tuple(
            float(struct.unpack(">f", payload[offset : offset + 4])[0])
            for offset in range(0, len(payload) - 3, 4)
        )
        converted = convert_numeric_tag(tag_id, float_values)
        return join_values(converted), converted
    return None, ()


def convert_string_tag(tag_id: int, value: str) -> str:
    if tag_id in {0x1002, 0x1003, 0x1004} and len(value) >= 8:
        return value[:4] + ":" + value[5:7] + ":" + value[8:].replace("_", " ")
    if tag_id == 0x1005 and len(value) >= 12:
        return (
            value[:4]
            + ":"
            + value[4:6]
            + ":"
            + value[6:8]
            + " "
            + value[8:10]
            + ":"
            + value[10:12]
            + ":"
            + value[12:]
        )
    if tag_id in {0x1023, 0x1030} and len(value) >= 6:
        return value[:4] + ":" + value[4:6] + ":" + value[6:]
    if tag_id in {0x1024, 0x1031} and len(value) >= 4:
        return value[:2] + ":" + value[2:4] + ":" + value[4:]
    return value


def convert_numeric_tag(
    tag_id: int,
    values: tuple[int | float, ...],
) -> tuple[int | float, ...]:
    if not values:
        return values
    if tag_id == 0x406A:
        return tuple(value / 10 for value in values)
    if tag_id == 0x606C:
        return tuple(value / 1000 for value in values)
    if tag_id == 0x2066:
        return tuple(round(value, 3) for value in values)
    return values


def find_directory_fallback(directory_buffer: bytes) -> int | None:
    for offset in range(0, max(len(directory_buffer) - 3, 0)):
        if directory_buffer[offset : offset + 3] == b"\x00\x0f\x10" and directory_buffer[
            offset + 3
        ] in {0x00, 0x06}:
            return offset
    return None


def build_preservation_actions(
    r3d_data: bytes,
    blocks: tuple[RedBlockPlan, ...],
    directory: RedDirectoryPlan,
) -> tuple[RedPreservationPlan, ...]:
    actions: list[RedPreservationPlan] = []
    for block in blocks:
        if block.status != "valid":
            continue
        payload = r3d_data[block.payload_range_start : block.payload_range_end]
        if block.index == 0 and block.block_type in {"RED1", "RED2"}:
            kind: RedPreservationKind = "header_block_payload"
        elif block.block_type == "R3D ":
            kind = "media_payload"
        else:
            kind = "trailing_payload"
        actions.append(
            RedPreservationPlan(
                kind=kind,
                byte_range_start=block.payload_range_start,
                byte_range_end=block.payload_range_end,
                payload=payload,
                evidence_ids=(RED_BLOCK_SOURCE, RED_READ_ONLY_SOURCE),
            )
        )
    for previous, current in pairwise(blocks):
        if previous.byte_range_end < current.byte_range_start:
            actions.append(
                RedPreservationPlan(
                    kind="alignment_padding",
                    byte_range_start=previous.byte_range_end,
                    byte_range_end=current.byte_range_start,
                    payload=r3d_data[previous.byte_range_end : current.byte_range_start],
                    evidence_ids=(RED_BLOCK_SOURCE, RED_READ_ONLY_SOURCE),
                )
            )
    if directory.directory_start is not None and directory.directory_end is not None:
        actions.append(
            RedPreservationPlan(
                kind="directory_payload",
                byte_range_start=directory.directory_start,
                byte_range_end=directory.directory_end,
                payload=r3d_data[directory.directory_start : directory.directory_end],
                evidence_ids=(RED_DIRECTORY_WALK_SOURCE, RED_READ_ONLY_SOURCE),
            )
        )
    consumed_end = blocks[-1].byte_range_end if blocks else 0
    if consumed_end < len(r3d_data):
        actions.append(
            RedPreservationPlan(
                kind="trailing_payload",
                byte_range_start=consumed_end,
                byte_range_end=len(r3d_data),
                payload=r3d_data[consumed_end:],
                evidence_ids=(RED_BLOCK_SOURCE, RED_READ_ONLY_SOURCE),
            )
        )
    return tuple(actions)


def build_actions(
    first_block_size: int | None,
    header_fields: tuple[RedHeaderFieldPlan, ...],
    directory: RedDirectoryPlan,
    preservation_actions: tuple[RedPreservationPlan, ...],
    rewrite_request: RedMetadataRewriteRequest | None,
) -> tuple[RedActionPlan, ...]:
    actions: list[RedActionPlan] = [
        RedActionPlan(
            kind="validate_r3d_header",
            byte_range_start=0,
            byte_range_end=8,
            reason="Validate the R3D first block header and accepted RED version.",
            evidence_ids=(RED_HEADER_SOURCE,),
        ),
        RedActionPlan(
            kind="detect_r3d_blocks",
            byte_range_start=0,
            byte_range_end=first_block_size,
            reason="Detect source-declared R3D block boundaries for preservation.",
            evidence_ids=(RED_BLOCK_SOURCE,),
        ),
    ]
    if header_fields:
        actions.append(
            RedActionPlan(
                kind="extract_red_header",
                byte_range_start=min(field.byte_range_start for field in header_fields),
                byte_range_end=max(field.byte_range_end for field in header_fields),
                reason="Extract RED1/RED2 header table fields without mutating the block.",
                evidence_ids=(RED_HEADER_TAG_SOURCE,),
            )
        )
    actions.append(
        RedActionPlan(
            kind="locate_red_directory",
            byte_range_start=directory.directory_start,
            byte_range_end=directory.directory_end,
            reason="Locate the first RED directory using Red.pm version-specific rules.",
            evidence_ids=(RED_DIRECTORY_LOCATE_SOURCE,),
        )
    )
    for entry in directory.entries:
        actions.append(
            RedActionPlan(
                kind="read_red_directory_entry",
                byte_range_start=entry.entry_range_start,
                byte_range_end=entry.entry_range_end,
                reason=f"Read {entry.tag_name} as {entry.format_name}.",
                evidence_ids=entry.evidence_ids,
            )
        )
    for preservation in preservation_actions:
        actions.append(
            RedActionPlan(
                kind="preserve_payload",
                byte_range_start=preservation.byte_range_start,
                byte_range_end=preservation.byte_range_end,
                reason=f"Preserve {preservation.kind} bytes exactly.",
                evidence_ids=preservation.evidence_ids,
            )
        )
    if rewrite_request is not None and rewrite_requested(rewrite_request):
        actions.append(
            RedActionPlan(
                kind="plan_metadata_rewrite",
                byte_range_start=directory.directory_start,
                byte_range_end=directory.directory_end,
                reason="Record the requested RED metadata change while keeping emission gated.",
                evidence_ids=(RED_READ_ONLY_SOURCE,),
            )
        )
    else:
        actions.append(
            RedActionPlan(
                kind="no_metadata_mutation",
                byte_range_start=None,
                byte_range_end=None,
                reason="No RED metadata mutation was requested.",
                evidence_ids=(RED_READ_ONLY_SOURCE,),
            )
        )
    return tuple(actions)


def build_responsibilities() -> tuple[RedResponsibilityPlan, ...]:
    return (
        RedResponsibilityPlan(
            concern="container_validation",
            tag_names=(),
            reason="Validate the initial RED1/RED2 block signature, size, and big-endian layout.",
            evidence_ids=(RED_HEADER_SOURCE,),
        ),
        RedResponsibilityPlan(
            concern="atom_chunk_detection",
            tag_names=(),
            reason="Track declared R3D block/chunk boundaries and RED2 alignment padding.",
            evidence_ids=(RED_BLOCK_SOURCE,),
        ),
        RedResponsibilityPlan(
            concern="clip_metadata",
            tag_names=responsibility_tags("clip_metadata"),
            reason="Route reel, take, and original file name fields to clip metadata.",
            evidence_ids=(RED_DIRECTORY_TABLE_SOURCE, RED_HEADER_TAG_SOURCE),
        ),
        RedResponsibilityPlan(
            concern="camera_metadata",
            tag_names=responsibility_tags("camera_metadata"),
            reason=(
                "Route serial, model, firmware, storage, color, and operator fields "
                "to camera metadata."
            ),
            evidence_ids=(RED_DIRECTORY_TABLE_SOURCE,),
        ),
        RedResponsibilityPlan(
            concern="timecode_metadata",
            tag_names=responsibility_tags("timecode_metadata"),
            reason="Route edge code, timecode, date, and time fields to time metadata.",
            evidence_ids=(RED_DIRECTORY_TABLE_SOURCE,),
        ),
        RedResponsibilityPlan(
            concern="lens_metadata",
            tag_names=responsibility_tags("lens_metadata"),
            reason=(
                "Route lens identity, aperture, focal length, filter, and focus distance fields."
            ),
            evidence_ids=(RED_DIRECTORY_TABLE_SOURCE,),
        ),
        RedResponsibilityPlan(
            concern="audio_metadata",
            tag_names=(),
            reason=(
                "Keep audio metadata as an explicit boundary because Red.pm has no "
                "active audio tag."
            ),
            evidence_ids=(RED_AUDIO_BOUNDARY_SOURCE,),
        ),
        RedResponsibilityPlan(
            concern="video_metadata",
            tag_names=responsibility_tags("video_metadata"),
            reason=(
                "Route image dimensions, frame rates, crop, format, quality, and "
                "aspect fields to video metadata."
            ),
            evidence_ids=(RED_HEADER_TAG_SOURCE, RED_DIRECTORY_TABLE_SOURCE),
        ),
        RedResponsibilityPlan(
            concern="payload_preservation",
            tag_names=(),
            reason="Preserve exact block, directory, padding, and media payload bytes.",
            evidence_ids=(RED_BLOCK_SOURCE, RED_DIRECTORY_WALK_SOURCE, RED_READ_ONLY_SOURCE),
        ),
        RedResponsibilityPlan(
            concern="malformed_truncation_blockers",
            tag_names=(),
            reason=(
                "Surface Red.pm truncation, missing-directory, malformed-entry, and "
                "format-code blockers."
            ),
            evidence_ids=(
                RED_HEADER_SOURCE,
                RED_DIRECTORY_LOCATE_SOURCE,
                RED_DIRECTORY_WALK_SOURCE,
            ),
        ),
        RedResponsibilityPlan(
            concern="unsupported_rewrite_gates",
            tag_names=(),
            reason="Gate RED mutation because this source-backed planner only ports read behavior.",
            evidence_ids=(RED_READ_ONLY_SOURCE,),
        ),
    )


def validation_gates(
    header_gate: RedEmissionGateCode | None,
    first_block: RedBlockPlan | None,
    directory: RedDirectoryPlan,
) -> list[RedOutputEmissionGate]:
    gates: list[RedOutputEmissionGate] = []
    append_gate(gates, header_gate, "R3D first block validation failed.", (RED_HEADER_SOURCE,))
    if first_block is not None and first_block.status == "invalid_size":
        append_gate(
            gates,
            "invalid_first_block_size",
            "An R3D block declared fewer than 8 bytes.",
            first_block.evidence_ids,
        )
    if first_block is not None and first_block.status == "truncated":
        append_gate(
            gates,
            "truncated_first_block",
            "The first R3D block is shorter than its declared size.",
            first_block.evidence_ids,
        )
    append_gate(
        gates,
        directory.reason,
        "The RED directory could not be fully planned.",
        directory.evidence_ids,
    )
    return gates


def rewrite_gates(
    rewrite_request: RedMetadataRewriteRequest,
) -> tuple[RedOutputEmissionGate, ...]:
    planned_length = planned_rewrite_length(rewrite_request)
    return (
        RedOutputEmissionGate(
            code="red_metadata_rewrite_not_supported",
            reason=(
                "Changing RED metadata is not implemented for the planned "
                f"{planned_length}-byte payload."
            ),
            evidence_ids=(RED_READ_ONLY_SOURCE,),
        ),
        RedOutputEmissionGate(
            code="red_header_rewrite_required",
            reason=(
                "RED metadata changes may require rebuilding RED1/RED2 header and "
                "directory offsets."
            ),
            evidence_ids=(RED_HEADER_TAG_SOURCE, RED_DIRECTORY_LOCATE_SOURCE),
        ),
        RedOutputEmissionGate(
            code="red_media_payload_rewrite_required",
            reason=(
                "RED byte emission must prove media payload and alignment preservation "
                "before writing."
            ),
            evidence_ids=(RED_BLOCK_SOURCE, RED_READ_ONLY_SOURCE),
        ),
    )


def non_mutating_default_gates() -> tuple[RedOutputEmissionGate, ...]:
    return (
        RedOutputEmissionGate(
            code="planner_is_non_mutating",
            reason="RED transaction plans do not mutate bytes by default.",
            evidence_ids=(RED_READ_ONLY_SOURCE,),
        ),
        RedOutputEmissionGate(
            code="full_red_writer_not_implemented",
            reason=(
                "No full RED/R3D writer is implemented for header, directory, and "
                "media-safe output."
            ),
            evidence_ids=(RED_READ_ONLY_SOURCE,),
        ),
    )


def append_gate(
    gates: list[RedOutputEmissionGate],
    code: RedEmissionGateCode | None,
    reason: str,
    evidence_ids: tuple[RedEvidenceId, ...],
) -> None:
    if code is None:
        return
    gates.append(RedOutputEmissionGate(code=code, reason=reason, evidence_ids=evidence_ids))


def any_validation_gate(gates: list[RedOutputEmissionGate]) -> bool:
    validation_codes = {
        "truncated_r3d_header",
        "unsupported_r3d_signature",
        "invalid_first_block_size",
        "truncated_first_block",
        "truncated_red1_directory_block",
        "truncated_red2_directory_counts",
        "red_directory_not_found",
        "malformed_red_directory_entry",
        "unknown_red_format_code",
    }
    return any(gate.code in validation_codes for gate in gates)


def rewrite_requested(rewrite_request: RedMetadataRewriteRequest) -> bool:
    return (
        rewrite_request.replacement_directory_payload is not None
        or rewrite_request.replacement_header_payload is not None
        or rewrite_request.delete_red_directory
    )


def planned_rewrite_length(rewrite_request: RedMetadataRewriteRequest) -> int:
    if rewrite_request.delete_red_directory:
        return 0
    directory_length = len(rewrite_request.replacement_directory_payload or b"")
    header_length = len(rewrite_request.replacement_header_payload or b"")
    return directory_length + header_length


def responsibility_tags(responsibility: RedMetadataResponsibility) -> tuple[str, ...]:
    names = [
        tag_name
        for tag_name, tag_responsibility in RED_DIRECTORY_TAGS.values()
        if tag_responsibility == responsibility
    ]
    if responsibility == "video_metadata":
        names.extend(("RedcodeVersion", "ImageWidth", "ImageHeight", "FrameRate"))
    if responsibility == "clip_metadata":
        names.append("OriginalFileName")
    return tuple(dict.fromkeys(names))


def empty_directory_plan(reason: RedEmissionGateCode | None) -> RedDirectoryPlan:
    return RedDirectoryPlan(
        status="not_read" if reason is None else "not_found",
        data_position=None,
        directory_start=None,
        directory_end=None,
        declared_length=None,
        fallback_used=False,
        entries=(),
        reason=reason,
        evidence_ids=(RED_DIRECTORY_LOCATE_SOURCE,),
    )


def decode_block_type(payload: bytes) -> str:
    return payload.decode("latin-1", errors="replace")


def decode_red_string(payload: bytes) -> str:
    return payload.split(b"\x00", 1)[0].decode("latin-1", errors="replace")


def join_values(values: tuple[int | float, ...]) -> str | None:
    if not values:
        return None
    return " ".join(format_required_number(value) for value in values)


def format_number(value: int | float | None) -> str | None:
    if value is None:
        return None
    return format_required_number(value)


def format_required_number(value: int | float) -> str:
    if isinstance(value, float):
        rounded = round(value, 3)
        return str(int(rounded)) if rounded.is_integer() else str(rounded)
    return str(value)


def align_up(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return [value for value in values]


def unique_evidence_ids(references: Iterable[RedEvidenceId]) -> tuple[RedEvidenceId, ...]:
    seen: set[RedEvidenceId] = set()
    unique: list[RedEvidenceId] = []
    for reference in references:
        if reference in seen:
            continue
        seen.add(reference)
        unique.append(reference)
    return tuple(unique)


def unique_gates(gates: tuple[RedOutputEmissionGate, ...]) -> tuple[RedOutputEmissionGate, ...]:
    seen: set[RedEmissionGateCode] = set()
    unique: list[RedOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
