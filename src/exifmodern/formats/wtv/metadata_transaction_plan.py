"""Source-backed, non-mutating WTV metadata transaction plans.

The planner mirrors ExifTool's WTV reader: validate the WTV header signature,
use the constrained sector size, walk the directory sector table, decode only
``table.0.entries.legacy_attrib`` metadata, and preserve all other sections.
Byte emission is deliberately blocked until a complete WTV writer exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonValue

WTV_HEADER_SIZE = 0x60
WTV_SIGNATURE_SIZE = 16
WTV_SECTOR_SIZE_OFFSET = 0x28
WTV_DIRECTORY_SECTOR_TABLE_OFFSET = 0x38
WTV_TOTAL_SECTORS_OFFSET = 0x58
WTV_STANDARD_SECTOR_SIZE = 0x1000
WTV_TEST_SECTOR_SIZE = 0x100
WTV_DIRECTORY_ENTRY_MIN_SIZE = 0x28
WTV_DIRECTORY_ENTRY_TRAILER_SIZE = 8
WTV_METADATA_RECORD_HEADER_SIZE = 0x18
WTV_LEGACY_METADATA_TAG = "table.0.entries.legacy_attrib"
WTV_SIGNATURE = bytes.fromhex("b7d800203749da11a64e0007e95ead8d")
WTV_DIRECTORY_ENTRY_GUID = bytes.fromhex("92b774915970704488df063b82cc213d")
WTV_METADATA_RECORD_GUID = bytes.fromhex("5afed76dc81d8f4a9922fab11c381453")

type WtvDirectoryAction = Literal[
    "route_legacy_metadata",
    "preserve_stream_payload",
    "preserve_unknown_section",
    "preserve_unsupported_flag",
]
type WtvEmissionGateCode = Literal[
    "truncated_wtv_header",
    "unsupported_wtv_signature",
    "empty_directory_sector_table",
    "reserved_sector_pointer",
    "sector_read_out_of_bounds",
    "directory_entry_unexpected_location",
    "invalid_directory_entry_size",
    "truncated_directory_entry",
    "malformed_directory_entry",
    "metadata_sector_read_failed",
    "corrupt_metadata_directory",
    "truncated_metadata_value",
    "metadata_rewrite_requires_sector_reallocation",
    "directory_sector_table_rewrite_required",
    "planner_is_non_mutating",
    "full_wtv_writer_not_implemented",
]
type WtvMetadataRole = Literal[
    "title",
    "subtitle",
    "episode",
    "channel",
    "recording_time",
    "other",
]
type WtvMetadataValue = str | int | bytes
type WtvPayloadKind = Literal["metadata_payload", "stream_payload", "unknown_section"]
type WtvRouteAction = Literal["upsert_legacy_metadata", "delete_legacy_metadata"]
type WtvSectorTableKind = Literal[
    "header_directory_table",
    "directory_entry_sector",
    "directory_entry_nested_sector_table",
]
type WtvResponsibilityConcern = Literal[
    "signature_header_validation",
    "sector_table_chunk_enumeration",
    "legacy_metadata_table_routing",
    "program_metadata_roles",
    "stream_payload_preservation",
    "unknown_section_preservation",
    "offset_size_truncation_blockers",
    "rewrite_blockers",
    "output_emission_gate",
]

WTV_PM_SOURCE_PATH = "lib/Image/ExifTool/WTV.pm"

WTV_MAIN_TABLE_SOURCE = "wtv.main.table"
WTV_METADATA_TABLE_SOURCE = "wtv.metadata.table"
WTV_READ_SECTORS_SOURCE = "wtv.read.sectors"
WTV_PROCESS_METADATA_SOURCE = "wtv.process.metadata"
WTV_HEADER_SOURCE = "wtv.header"
WTV_DIRECTORY_SOURCE = "wtv.directory"
WTV_READ_ONLY_SOURCE = "wtv.read.only"

WTV_TRANSACTION_SOURCES = (
    WTV_MAIN_TABLE_SOURCE,
    WTV_METADATA_TABLE_SOURCE,
    WTV_READ_SECTORS_SOURCE,
    WTV_PROCESS_METADATA_SOURCE,
    WTV_HEADER_SOURCE,
    WTV_DIRECTORY_SOURCE,
    WTV_READ_ONLY_SOURCE,
)

WTV_TAG_NAME_MAP: dict[str, str] = {
    "Duration": "Duration",
    "Title": "Title",
    "WM/MediaOriginalBroadcastDateTime": "MediaOriginalBroadcastDateTime",
    "WM/MediaOriginalChannel": "MediaOriginalChannel",
    "WM/MediaOriginalChannelSubNumber": "MediaOriginalChannelSubNumber",
    "WM/MediaStationCallSign": "MediaStationCallSign",
    "WM/MediaStationName": "MediaStationName",
    "WM/OriginalReleaseTime": "OriginalReleaseTime",
    "WM/SubTitle": "Subtitle",
    "WM/SubTitleDescription": "SubtitleDescription",
    "WM/WMRVEncodeTime": "EncodeTime",
    "WM/WMRVEndTime": "EndTime",
    "WM/WMRVProgramID": "ProgramID",
    "WM/WMRVScheduleItemID": "ScheduleItemID",
    "WM/WMRVSeriesUID": "SeriesUID",
}
WTV_ROLE_TAGS: dict[str, WtvMetadataRole] = {
    "Title": "title",
    "WM/SubTitle": "subtitle",
    "WM/SubTitleDescription": "episode",
    "WM/WMRVProgramID": "episode",
    "WM/WMRVScheduleItemID": "episode",
    "WM/WMRVSeriesUID": "episode",
    "WM/MediaOriginalChannel": "channel",
    "WM/MediaOriginalChannelSubNumber": "channel",
    "WM/MediaStationCallSign": "channel",
    "WM/MediaStationName": "channel",
    "WM/MediaOriginalBroadcastDateTime": "recording_time",
    "WM/OriginalReleaseTime": "recording_time",
    "WM/WMRVEncodeTime": "recording_time",
    "WM/WMRVEndTime": "recording_time",
}
WTV_UNDECODED_STREAM_TAGS = {
    "timeline",
    "timeline.table.0.header.Events",
    "timeline.table.0.entries.Events",
    "table.0.header.time",
    "table.0.entries.time",
}


@dataclass(frozen=True)
class WtvSectorChunkPlan:
    sector_number: int
    logical_offset: int
    file_offset: int
    size: int
    end_offset: int
    is_complete: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "end_offset": self.end_offset,
            "file_offset": self.file_offset,
            "is_complete": self.is_complete,
            "logical_offset": self.logical_offset,
            "sector_number": self.sector_number,
            "size": self.size,
        }


@dataclass(frozen=True)
class WtvSectorReadPlan:
    kind: WtvSectorTableKind
    sector_size: int
    sector_table_offset: int | None
    sector_table_start: int
    sector_numbers: tuple[int, ...]
    chunks: tuple[WtvSectorChunkPlan, ...]
    byte_length: int
    is_complete: bool
    reason: WtvEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def file_offset_for(self, logical_offset: int) -> int | None:
        for chunk in self.chunks:
            chunk_end = chunk.logical_offset + chunk.size
            if chunk.logical_offset <= logical_offset < chunk_end:
                return chunk.file_offset + logical_offset - chunk.logical_offset
        return None

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "byte_length": self.byte_length,
            "chunks": [chunk.to_json() for chunk in self.chunks],
            "is_complete": self.is_complete,
            "kind": self.kind,
            "reason": self.reason,
            "sector_numbers": list(self.sector_numbers),
            "sector_size": self.sector_size,
            "sector_table_offset": self.sector_table_offset,
            "sector_table_start": self.sector_table_start,
        }


@dataclass(frozen=True)
class WtvHeaderValidationPlan:
    is_valid: bool
    signature: str
    declared_sector_size: int | None
    sector_size: int | None
    total_sector_count: int | None
    reason: WtvEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "declared_sector_size": self.declared_sector_size,
            "is_valid": self.is_valid,
            "reason": self.reason,
            "sector_size": self.sector_size,
            "signature": self.signature,
            "total_sector_count": self.total_sector_count,
        }


@dataclass(frozen=True)
class WtvDirectoryEntryPlan:
    tag: str
    action: WtvDirectoryAction
    directory_offset: int
    file_offset: int | None
    declared_size: int
    end_directory_offset: int
    name_length: int
    sector_number: int
    flag: int
    sector_pointer_offset: int | None
    payload_size: int | None
    payload_read: WtvSectorReadPlan | None
    evidence_ids: tuple[str, ...]

    @property
    def section_path(self) -> str:
        return self.tag

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "action": self.action,
            "declared_size": self.declared_size,
            "directory_offset": self.directory_offset,
            "end_directory_offset": self.end_directory_offset,
            "file_offset": self.file_offset,
            "flag": self.flag,
            "name_length": self.name_length,
            "payload_read": self.payload_read.to_json() if self.payload_read else None,
            "payload_size": self.payload_size,
            "section_path": self.section_path,
            "sector_number": self.sector_number,
            "sector_pointer_offset": self.sector_pointer_offset,
            "tag": self.tag,
        }


@dataclass(frozen=True)
class WtvMetadataEntryPlan:
    tag_key: str
    exiftool_name: str
    role: WtvMetadataRole
    value: WtvMetadataValue
    format_code: int
    format_name: str
    record_payload_offset: int
    record_file_offset: int | None
    value_payload_offset: int
    value_file_offset: int | None
    value_size: int
    metadata_record_size: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "exiftool_name": self.exiftool_name,
            "format_code": self.format_code,
            "format_name": self.format_name,
            "metadata_record_size": self.metadata_record_size,
            "record_file_offset": self.record_file_offset,
            "record_payload_offset": self.record_payload_offset,
            "role": self.role,
            "tag_key": self.tag_key,
            "value": metadata_value_to_json(self.value),
            "value_file_offset": self.value_file_offset,
            "value_payload_offset": self.value_payload_offset,
            "value_size": self.value_size,
        }


@dataclass(frozen=True)
class WtvPayloadPreservationPlan:
    kind: WtvPayloadKind
    tag: str
    reason: str
    sector_number: int
    flag: int
    payload_size: int | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "flag": self.flag,
            "kind": self.kind,
            "payload_size": self.payload_size,
            "reason": self.reason,
            "sector_number": self.sector_number,
            "tag": self.tag,
        }


@dataclass(frozen=True)
class WtvMetadataWriteRequest:
    tag_name: str
    value: WtvMetadataValue | None
    format_code: int = 1


@dataclass(frozen=True)
class WtvMetadataRoutePlan:
    action: WtvRouteAction
    tag_key: str
    exiftool_name: str
    role: WtvMetadataRole
    existing_value: WtvMetadataValue | None
    requested_value: WtvMetadataValue | None
    estimated_size_delta: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "action": self.action,
            "estimated_size_delta": self.estimated_size_delta,
            "existing_value": metadata_value_to_json(self.existing_value),
            "exiftool_name": self.exiftool_name,
            "requested_value": metadata_value_to_json(self.requested_value),
            "role": self.role,
            "tag_key": self.tag_key,
        }


@dataclass(frozen=True)
class WtvPlanningResponsibility:
    order: int
    concern: WtvResponsibilityConcern
    description: str
    surfaces: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "concern": self.concern,
            "description": self.description,
            "order": self.order,
            "surfaces": list(self.surfaces),
        }


@dataclass(frozen=True)
class WtvEmissionGate:
    code: WtvEmissionGateCode
    reason: str
    blocks_emission: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "blocks_emission": self.blocks_emission,
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class WtvMetadataTransactionPlan:
    header_validation: WtvHeaderValidationPlan
    directory_read: WtvSectorReadPlan | None
    directory_entries: tuple[WtvDirectoryEntryPlan, ...]
    metadata_entries: tuple[WtvMetadataEntryPlan, ...]
    preservation_plans: tuple[WtvPayloadPreservationPlan, ...]
    routes: tuple[WtvMetadataRoutePlan, ...]
    responsibilities: tuple[WtvPlanningResponsibility, ...]
    output_emission_gates: tuple[WtvEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def section_paths(self) -> tuple[str, ...]:
        return tuple(entry.section_path for entry in self.directory_entries)

    @property
    def legacy_metadata_tags(self) -> tuple[str, ...]:
        return tuple(entry.tag_key for entry in self.metadata_entries)

    @property
    def estimated_size_delta(self) -> int:
        return sum(route.estimated_size_delta for route in self.routes)

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"WTV metadata transaction output is gated: {gate_codes}")

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "directory_entries": [entry.to_json() for entry in self.directory_entries],
            "directory_read": self.directory_read.to_json() if self.directory_read else None,
            "estimated_size_delta": self.estimated_size_delta,
            "header_validation": self.header_validation.to_json(),
            "legacy_metadata_tags": list(self.legacy_metadata_tags),
            "metadata_entries": [entry.to_json() for entry in self.metadata_entries],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "preservation_plans": [plan.to_json() for plan in self.preservation_plans],
            "responsibilities": [item.to_json() for item in self.responsibilities],
            "routes": [route.to_json() for route in self.routes],
            "section_paths": list(self.section_paths),
        }


@dataclass(frozen=True)
class _DirectoryPayload:
    entry: WtvDirectoryEntryPlan
    payload: bytes
    read_plan: WtvSectorReadPlan


def build_wtv_metadata_transaction_plan(
    data: bytes,
    metadata_writes: tuple[WtvMetadataWriteRequest, ...] = (),
) -> WtvMetadataTransactionPlan:
    """Build a non-mutating WTV metadata transaction plan."""

    (
        header_validation,
        directory_read,
        directory_entries,
        directory_payloads,
        parse_gates,
    ) = inspect_wtv_directory(data)
    metadata_entries, metadata_gates = extract_metadata_entries(directory_payloads)
    preservation_plans = plan_payload_preservation(directory_entries)
    routes = route_metadata_writes(metadata_entries, metadata_writes)
    gates = [*parse_gates, *metadata_gates]
    if routes:
        gates.extend(
            (
                WtvEmissionGate(
                    "metadata_rewrite_requires_sector_reallocation",
                    (
                        "Changing WTV legacy metadata needs sector allocation and payload "
                        "replacement beyond the read-only ExifTool model."
                    ),
                    True,
                    (WTV_PROCESS_METADATA_SOURCE, WTV_READ_ONLY_SOURCE),
                ),
                WtvEmissionGate(
                    "directory_sector_table_rewrite_required",
                    (
                        "Changing WTV metadata can require directory sector-table and size "
                        "repair not implemented by this planner."
                    ),
                    True,
                    (WTV_READ_SECTORS_SOURCE, WTV_DIRECTORY_SOURCE, WTV_READ_ONLY_SOURCE),
                ),
            )
        )
    gates.extend(
        (
            WtvEmissionGate(
                "planner_is_non_mutating",
                "WTV metadata transaction plans record decisions but do not mutate bytes.",
                True,
                (WTV_READ_ONLY_SOURCE,),
            ),
            WtvEmissionGate(
                "full_wtv_writer_not_implemented",
                "Safe emission requires a complete WTV writer with sector and directory repair.",
                True,
                (WTV_READ_ONLY_SOURCE, WTV_DIRECTORY_SOURCE),
            ),
        )
    )
    responsibilities = default_responsibilities()
    sources = unique_sources(
        (
            *header_validation.evidence_ids,
            *(directory_read.evidence_ids if directory_read else ()),
            *(source for entry in directory_entries for source in entry.evidence_ids),
            *(source for entry in metadata_entries for source in entry.evidence_ids),
            *(source for plan in preservation_plans for source in plan.evidence_ids),
            *(source for route in routes for source in route.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
            *(source for item in responsibilities for source in item.evidence_ids),
        )
    )
    return WtvMetadataTransactionPlan(
        header_validation=header_validation,
        directory_read=directory_read,
        directory_entries=directory_entries,
        metadata_entries=metadata_entries,
        preservation_plans=preservation_plans,
        routes=routes,
        responsibilities=responsibilities,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
    )


def inspect_wtv_directory(
    data: bytes,
) -> tuple[
    WtvHeaderValidationPlan,
    WtvSectorReadPlan | None,
    tuple[WtvDirectoryEntryPlan, ...],
    tuple[_DirectoryPayload, ...],
    tuple[WtvEmissionGate, ...],
]:
    if len(data) < WTV_HEADER_SIZE:
        return (
            WtvHeaderValidationPlan(
                False,
                data[:WTV_SIGNATURE_SIZE].hex(),
                None,
                None,
                None,
                "truncated_wtv_header",
                (WTV_HEADER_SOURCE,),
            ),
            None,
            (),
            (),
            (
                WtvEmissionGate(
                    "truncated_wtv_header",
                    "Input ended before ExifTool's 0x60-byte WTV header read.",
                    True,
                    (WTV_HEADER_SOURCE,),
                ),
            ),
        )

    declared_sector_size = u32(data, WTV_SECTOR_SIZE_OFFSET)
    sector_size = (
        declared_sector_size
        if declared_sector_size in {WTV_STANDARD_SECTOR_SIZE, WTV_TEST_SECTOR_SIZE}
        else WTV_STANDARD_SECTOR_SIZE
    )
    total_sector_count = u32(data, WTV_TOTAL_SECTORS_OFFSET)
    signature = data[:WTV_SIGNATURE_SIZE]
    if signature != WTV_SIGNATURE:
        return (
            WtvHeaderValidationPlan(
                False,
                signature.hex(),
                declared_sector_size,
                sector_size,
                total_sector_count,
                "unsupported_wtv_signature",
                (WTV_HEADER_SOURCE,),
            ),
            None,
            (),
            (),
            (
                WtvEmissionGate(
                    "unsupported_wtv_signature",
                    "ExifTool WTV processing accepts only files beginning with the WTV signature.",
                    True,
                    (WTV_HEADER_SOURCE,),
                ),
            ),
        )

    directory_read, directory_data, directory_gates = read_sectors(
        data,
        data[:WTV_HEADER_SIZE],
        0,
        WTV_DIRECTORY_SECTOR_TABLE_OFFSET,
        sector_size,
        "header_directory_table",
    )
    header_validation = WtvHeaderValidationPlan(
        True,
        signature.hex(),
        declared_sector_size,
        sector_size,
        total_sector_count,
        None,
        (WTV_HEADER_SOURCE, WTV_READ_SECTORS_SOURCE),
    )
    if not directory_read.is_complete:
        return header_validation, directory_read, (), (), tuple(directory_gates)
    entries, payloads, entry_gates = parse_directory_entries(
        data,
        directory_data,
        directory_read,
        sector_size,
    )
    return (
        header_validation,
        directory_read,
        tuple(entries),
        tuple(payloads),
        tuple((*directory_gates, *entry_gates)),
    )


def parse_directory_entries(
    file_data: bytes,
    directory_data: bytes,
    directory_read: WtvSectorReadPlan,
    sector_size: int,
) -> tuple[list[WtvDirectoryEntryPlan], list[_DirectoryPayload], list[WtvEmissionGate]]:
    entries: list[WtvDirectoryEntryPlan] = []
    payloads: list[_DirectoryPayload] = []
    gates: list[WtvEmissionGate] = []
    pos = 0
    while pos < len(directory_data) - WTV_DIRECTORY_ENTRY_MIN_SIZE:
        if directory_data[pos : pos + 16] != WTV_DIRECTORY_ENTRY_GUID:
            if pos:
                gates.append(
                    WtvEmissionGate(
                        "directory_entry_unexpected_location",
                        f"WTV directory entry GUID was missing at directory offset {pos}.",
                        True,
                        (WTV_DIRECTORY_SOURCE,),
                    )
                )
            break
        declared_size = u32(directory_data, pos + 0x10)
        if declared_size <= WTV_DIRECTORY_ENTRY_MIN_SIZE:
            gates.append(
                WtvEmissionGate(
                    "invalid_directory_entry_size",
                    f"WTV directory entry at offset {pos} reports invalid size {declared_size}.",
                    True,
                    (WTV_DIRECTORY_SOURCE,),
                )
            )
            break
        if pos + declared_size > len(directory_data):
            gates.append(
                WtvEmissionGate(
                    "truncated_directory_entry",
                    f"WTV directory entry at offset {pos} extends beyond the directory payload.",
                    True,
                    (WTV_DIRECTORY_SOURCE,),
                )
            )
            break
        name_length = u32(directory_data, pos + 0x20)
        required_size = (
            WTV_DIRECTORY_ENTRY_MIN_SIZE + name_length * 2 + WTV_DIRECTORY_ENTRY_TRAILER_SIZE
        )
        if required_size > declared_size:
            gates.append(
                WtvEmissionGate(
                    "malformed_directory_entry",
                    f"WTV directory entry at offset {pos} has a malformed UTF-16 name area.",
                    True,
                    (WTV_DIRECTORY_SOURCE,),
                )
            )
            break
        tag_start = pos + WTV_DIRECTORY_ENTRY_MIN_SIZE
        tag_end = tag_start + name_length * 2
        pointer_offset = tag_end
        tag = decode_utf16le(directory_data[tag_start:tag_end])
        sector_number = u32(directory_data, pointer_offset)
        flag = u32(directory_data, pointer_offset + 4)
        action = directory_action(tag, flag)
        pointer_file_offset = directory_read.file_offset_for(pointer_offset)
        payload_read: WtvSectorReadPlan | None = None
        payload_size: int | None = None
        payload_data = b""
        if flag in {0, 1}:
            payload_read, payload_data, payload_gates = read_directory_payload(
                file_data,
                directory_data[pointer_offset : pointer_offset + 4],
                pointer_file_offset,
                sector_size,
                flag,
            )
            gates.extend(payload_gates)
            payload_size = payload_read.byte_length
        entry = WtvDirectoryEntryPlan(
            tag=tag,
            action=action,
            directory_offset=pos,
            file_offset=directory_read.file_offset_for(pos),
            declared_size=declared_size,
            end_directory_offset=pos + declared_size,
            name_length=name_length,
            sector_number=sector_number,
            flag=flag,
            sector_pointer_offset=pointer_file_offset,
            payload_size=payload_size,
            payload_read=payload_read,
            evidence_ids=directory_entry_sources(action),
        )
        entries.append(entry)
        if action == "route_legacy_metadata" and payload_read and payload_read.is_complete:
            payloads.append(_DirectoryPayload(entry, payload_data, payload_read))
        elif action == "route_legacy_metadata":
            gates.append(
                WtvEmissionGate(
                    "metadata_sector_read_failed",
                    f"WTV metadata section {tag} could not be read completely.",
                    True,
                    (WTV_READ_SECTORS_SOURCE, WTV_DIRECTORY_SOURCE),
                )
            )
        pos += declared_size
    return entries, payloads, gates


def read_directory_payload(
    file_data: bytes,
    sector_bytes: bytes,
    sector_pointer_offset: int | None,
    sector_size: int,
    flag: int,
) -> tuple[WtvSectorReadPlan, bytes, tuple[WtvEmissionGate, ...]]:
    first_read, first_payload, first_gates = read_sectors(
        file_data,
        sector_bytes,
        sector_pointer_offset,
        0,
        sector_size,
        "directory_entry_sector",
    )
    if flag == 0 or not first_read.is_complete:
        return first_read, first_payload, tuple(first_gates)
    nested_read, nested_payload, nested_gates = read_sectors(
        file_data,
        first_payload,
        first_read.chunks[0].file_offset if first_read.chunks else None,
        0,
        sector_size,
        "directory_entry_nested_sector_table",
    )
    return nested_read, nested_payload, tuple((*first_gates, *nested_gates))


def read_sectors(
    file_data: bytes,
    sector_table: bytes,
    sector_table_offset: int | None,
    table_pos: int,
    sector_size: int,
    kind: WtvSectorTableKind,
) -> tuple[WtvSectorReadPlan, bytes, list[WtvEmissionGate]]:
    chunks: list[WtvSectorChunkPlan] = []
    sector_numbers: list[int] = []
    payload = b""
    gates: list[WtvEmissionGate] = []
    pos = table_pos
    reason: WtvEmissionGateCode | None = None
    while pos <= len(sector_table) - 4:
        sector_number = u32(sector_table, pos)
        if sector_number == 0xFFFF:
            reason = "reserved_sector_pointer"
            gates.append(
                WtvEmissionGate(
                    "reserved_sector_pointer",
                    "ExifTool treats sector pointer 0xffff as an error guard.",
                    True,
                    (WTV_READ_SECTORS_SOURCE,),
                )
            )
            break
        if sector_number == 0:
            break
        sector_numbers.append(sector_number)
        file_offset = sector_number * sector_size
        end_offset = file_offset + sector_size
        if end_offset > len(file_data):
            reason = "sector_read_out_of_bounds"
            gates.append(
                WtvEmissionGate(
                    "sector_read_out_of_bounds",
                    f"WTV sector {sector_number} extends beyond available bytes.",
                    True,
                    (WTV_READ_SECTORS_SOURCE,),
                )
            )
            break
        chunks.append(
            WtvSectorChunkPlan(
                sector_number=sector_number,
                logical_offset=len(payload),
                file_offset=file_offset,
                size=sector_size,
                end_offset=end_offset,
                is_complete=True,
                evidence_ids=(WTV_READ_SECTORS_SOURCE,),
            )
        )
        payload += file_data[file_offset:end_offset]
        pos += 4
    if not chunks and reason is None:
        reason = "empty_directory_sector_table"
        gates.append(
            WtvEmissionGate(
                "empty_directory_sector_table",
                "WTV sector table contained no readable sector pointers.",
                True,
                (WTV_READ_SECTORS_SOURCE,),
            )
        )
    is_complete = bool(chunks) and reason is None
    read_plan = WtvSectorReadPlan(
        kind=kind,
        sector_size=sector_size,
        sector_table_offset=sector_table_offset,
        sector_table_start=table_pos,
        sector_numbers=tuple(sector_numbers),
        chunks=tuple(chunks),
        byte_length=len(payload),
        is_complete=is_complete,
        reason=reason,
        evidence_ids=(WTV_READ_SECTORS_SOURCE,),
    )
    return read_plan, payload, gates


def extract_metadata_entries(
    directory_payloads: tuple[_DirectoryPayload, ...],
) -> tuple[tuple[WtvMetadataEntryPlan, ...], tuple[WtvEmissionGate, ...]]:
    entries: list[WtvMetadataEntryPlan] = []
    gates: list[WtvEmissionGate] = []
    for payload in directory_payloads:
        payload_entries, payload_gates = parse_metadata_payload(payload.payload, payload.read_plan)
        entries.extend(payload_entries)
        gates.extend(payload_gates)
    return tuple(entries), tuple(gates)


def parse_metadata_payload(
    payload: bytes,
    read_plan: WtvSectorReadPlan,
) -> tuple[list[WtvMetadataEntryPlan], list[WtvEmissionGate]]:
    entries: list[WtvMetadataEntryPlan] = []
    gates: list[WtvEmissionGate] = []
    pos = 0
    end = len(payload)
    while pos + WTV_METADATA_RECORD_HEADER_SIZE < end:
        record_start = pos
        if payload[pos : pos + 16] != WTV_METADATA_RECORD_GUID:
            break
        format_code = u32(payload, pos + 0x10)
        value_size = u32(payload, pos + 0x14)
        pos += WTV_METADATA_RECORD_HEADER_SIZE
        tag_name_start = pos
        tag_bytes = b""
        while True:
            if pos + 2 > end:
                gates.append(
                    WtvEmissionGate(
                        "corrupt_metadata_directory",
                        "WTV metadata tag name was not terminated inside the payload.",
                        True,
                        (WTV_PROCESS_METADATA_SOURCE,),
                    )
                )
                return entries, gates
            char = payload[pos : pos + 2]
            pos += 2
            if char == b"\0\0":
                break
            tag_bytes += char
        if pos + value_size > end:
            gates.append(
                WtvEmissionGate(
                    "truncated_metadata_value",
                    f"WTV metadata tag at payload offset {tag_name_start} exceeds its payload.",
                    True,
                    (WTV_PROCESS_METADATA_SOURCE,),
                )
            )
            break
        tag_key = decode_utf16le(tag_bytes)
        value_bytes = payload[pos : pos + value_size]
        value = decode_metadata_value(value_bytes, format_code)
        if value is None:
            gates.append(
                WtvEmissionGate(
                    "truncated_metadata_value",
                    f"WTV metadata tag {tag_key} is shorter than its declared scalar format.",
                    True,
                    (WTV_PROCESS_METADATA_SOURCE,),
                )
            )
            break
        record_size = pos + value_size - record_start
        entries.append(
            WtvMetadataEntryPlan(
                tag_key=tag_key,
                exiftool_name=exiftool_metadata_name(tag_key),
                role=metadata_role(tag_key),
                value=value,
                format_code=format_code,
                format_name=metadata_format_name(format_code),
                record_payload_offset=record_start,
                record_file_offset=read_plan.file_offset_for(record_start),
                value_payload_offset=pos,
                value_file_offset=read_plan.file_offset_for(pos),
                value_size=value_size,
                metadata_record_size=record_size,
                evidence_ids=(WTV_METADATA_TABLE_SOURCE, WTV_PROCESS_METADATA_SOURCE),
            )
        )
        pos += value_size
    return entries, gates


def plan_payload_preservation(
    entries: tuple[WtvDirectoryEntryPlan, ...],
) -> tuple[WtvPayloadPreservationPlan, ...]:
    plans: list[WtvPayloadPreservationPlan] = []
    for entry in entries:
        if entry.action == "route_legacy_metadata":
            plans.append(
                WtvPayloadPreservationPlan(
                    "metadata_payload",
                    entry.tag,
                    "Legacy attribute metadata is read for planning and otherwise preserved.",
                    entry.sector_number,
                    entry.flag,
                    entry.payload_size,
                    (WTV_MAIN_TABLE_SOURCE, WTV_PROCESS_METADATA_SOURCE),
                )
            )
        elif entry.action == "preserve_stream_payload":
            plans.append(
                WtvPayloadPreservationPlan(
                    "stream_payload",
                    entry.tag,
                    "ExifTool lists this WTV stream/table area but does not decode it.",
                    entry.sector_number,
                    entry.flag,
                    entry.payload_size,
                    (WTV_MAIN_TABLE_SOURCE,),
                )
            )
        elif entry.action == "preserve_unknown_section":
            plans.append(
                WtvPayloadPreservationPlan(
                    "unknown_section",
                    entry.tag,
                    (
                        "Unknown WTV directory sections are not decoded by ExifTool "
                        "and remain preserved."
                    ),
                    entry.sector_number,
                    entry.flag,
                    entry.payload_size,
                    (WTV_DIRECTORY_SOURCE,),
                )
            )
    return tuple(plans)


def route_metadata_writes(
    existing_entries: tuple[WtvMetadataEntryPlan, ...],
    requests: tuple[WtvMetadataWriteRequest, ...],
) -> tuple[WtvMetadataRoutePlan, ...]:
    existing_by_key = {entry.tag_key: entry for entry in existing_entries}
    routes: list[WtvMetadataRoutePlan] = []
    for request in requests:
        tag_key = normalized_metadata_key(request.tag_name)
        existing = existing_by_key.get(tag_key)
        is_delete = request.value is None
        routes.append(
            WtvMetadataRoutePlan(
                action="delete_legacy_metadata" if is_delete else "upsert_legacy_metadata",
                tag_key=tag_key,
                exiftool_name=exiftool_metadata_name(tag_key),
                role=metadata_role(tag_key),
                existing_value=existing.value if existing else None,
                requested_value=request.value,
                estimated_size_delta=estimated_route_delta(existing, request),
                evidence_ids=(WTV_METADATA_TABLE_SOURCE, WTV_PROCESS_METADATA_SOURCE),
            )
        )
    return tuple(routes)


def estimated_route_delta(
    existing: WtvMetadataEntryPlan | None,
    request: WtvMetadataWriteRequest,
) -> int:
    old_size = existing.metadata_record_size if existing else 0
    if request.value is None:
        return -old_size
    tag_key = normalized_metadata_key(request.tag_name)
    tag_bytes = len(tag_key.encode("utf-16le"))
    new_size = (
        WTV_METADATA_RECORD_HEADER_SIZE
        + tag_bytes
        + 2
        + encoded_metadata_value_size(request.value, request.format_code)
    )
    return new_size - old_size


def decode_metadata_value(value: bytes, format_code: int) -> WtvMetadataValue | None:
    if format_code in {0, 3}:
        if len(value) < 4:
            return None
        return int.from_bytes(value[:4], "little", signed=True)
    if format_code == 1:
        return decode_utf16le(value)
    if format_code == 4:
        if len(value) < 8:
            return None
        return int.from_bytes(value[:8], "little")
    if format_code == 6:
        return value.hex()
    return value


def encoded_metadata_value_size(value: WtvMetadataValue, format_code: int) -> int:
    if isinstance(value, bytes):
        return len(value)
    if format_code in {0, 3}:
        return 4
    if format_code == 4:
        return 8
    if isinstance(value, int):
        return 8
    return len(value.encode("utf-16le"))


def directory_action(tag: str, flag: int) -> WtvDirectoryAction:
    if flag not in {0, 1}:
        return "preserve_unsupported_flag"
    if tag == WTV_LEGACY_METADATA_TAG:
        return "route_legacy_metadata"
    if tag in WTV_UNDECODED_STREAM_TAGS or tag.startswith("timeline"):
        return "preserve_stream_payload"
    return "preserve_unknown_section"


def directory_entry_sources(action: WtvDirectoryAction) -> tuple[str, ...]:
    if action == "route_legacy_metadata":
        return (WTV_MAIN_TABLE_SOURCE, WTV_DIRECTORY_SOURCE, WTV_READ_SECTORS_SOURCE)
    if action == "preserve_stream_payload":
        return (WTV_MAIN_TABLE_SOURCE, WTV_DIRECTORY_SOURCE)
    return (WTV_DIRECTORY_SOURCE,)


def metadata_format_name(format_code: int) -> str:
    if format_code == 0:
        return "int32"
    if format_code == 1:
        return "string"
    if format_code == 3:
        return "boolean32"
    if format_code == 4:
        return "int64"
    if format_code == 6:
        return "guid"
    return f"Unknown({format_code})"


def metadata_role(tag_key: str) -> WtvMetadataRole:
    return WTV_ROLE_TAGS.get(tag_key, "other")


def exiftool_metadata_name(tag_key: str) -> str:
    mapped = WTV_TAG_NAME_MAP.get(tag_key)
    if mapped:
        return mapped
    name = tag_key
    if name.startswith("WTV_Metadata_WM/WMRV"):
        return name.removeprefix("WTV_Metadata_WM/WMRV")
    if name.startswith("WTV_Metadata_WM/"):
        return name.removeprefix("WTV_Metadata_WM/")
    if name.startswith("WM/WMRV"):
        return name.removeprefix("WM/WMRV")
    if name.startswith("WM/"):
        return name.removeprefix("WM/")
    return name


def normalized_metadata_key(tag_name: str) -> str:
    if tag_name in WTV_TAG_NAME_MAP:
        return tag_name
    for key, name in WTV_TAG_NAME_MAP.items():
        if tag_name == name:
            return key
    return tag_name


def default_responsibilities() -> tuple[WtvPlanningResponsibility, ...]:
    return (
        WtvPlanningResponsibility(
            1,
            "signature_header_validation",
            "Require ExifTool's WTV signature and constrained sector-size interpretation.",
            ("header_validation",),
            (WTV_HEADER_SOURCE,),
        ),
        WtvPlanningResponsibility(
            2,
            "sector_table_chunk_enumeration",
            "Read WTV directory and payload sectors through ExifTool-style sector tables.",
            ("directory_read", "directory_entries[].payload_read"),
            (WTV_READ_SECTORS_SOURCE, WTV_DIRECTORY_SOURCE),
        ),
        WtvPlanningResponsibility(
            3,
            "legacy_metadata_table_routing",
            "Route only table.0.entries.legacy_attrib to WTV metadata decoding.",
            ("directory_entries", "metadata_entries"),
            (WTV_MAIN_TABLE_SOURCE, WTV_PROCESS_METADATA_SOURCE),
        ),
        WtvPlanningResponsibility(
            4,
            "program_metadata_roles",
            "Classify title, subtitle, episode, channel, and recording time tags when present.",
            ("metadata_entries[].role",),
            (WTV_METADATA_TABLE_SOURCE,),
        ),
        WtvPlanningResponsibility(
            5,
            "stream_payload_preservation",
            "Preserve timeline and stream-like payloads that ExifTool does not decode.",
            ("preservation_plans",),
            (WTV_MAIN_TABLE_SOURCE, WTV_DIRECTORY_SOURCE),
        ),
        WtvPlanningResponsibility(
            6,
            "unknown_section_preservation",
            "Preserve unknown directory sections without assigning metadata semantics.",
            ("preservation_plans",),
            (WTV_DIRECTORY_SOURCE,),
        ),
        WtvPlanningResponsibility(
            7,
            "offset_size_truncation_blockers",
            "Expose sector, entry, metadata size, and truncation failures as blocking gates.",
            ("output_emission_gates",),
            (WTV_READ_SECTORS_SOURCE, WTV_DIRECTORY_SOURCE, WTV_PROCESS_METADATA_SOURCE),
        ),
        WtvPlanningResponsibility(
            8,
            "rewrite_blockers",
            "Block metadata rewrites that would require WTV sector allocation and repair.",
            ("routes", "output_emission_gates"),
            (WTV_READ_ONLY_SOURCE, WTV_READ_SECTORS_SOURCE),
        ),
        WtvPlanningResponsibility(
            9,
            "output_emission_gate",
            "Keep WTV byte emission disabled until a full writer owns safe output.",
            ("can_mutate_bytes", "output_emission_gates"),
            (WTV_READ_ONLY_SOURCE,),
        ),
    )


def u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def decode_utf16le(value: bytes) -> str:
    return value.decode("utf-16le", errors="replace").rstrip("\x00")


def metadata_value_to_json(value: WtvMetadataValue | None) -> JsonValue:
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    return value


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for source in sources:
        if source not in unique:
            unique.append(source)
    return tuple(unique)


def unique_gates(gates: tuple[WtvEmissionGate, ...]) -> tuple[WtvEmissionGate, ...]:
    unique: list[WtvEmissionGate] = []
    seen_codes: set[WtvEmissionGateCode] = set()
    for gate in gates:
        if gate.code not in seen_codes:
            unique.append(gate)
            seen_codes.add(gate.code)
    return tuple(unique)
