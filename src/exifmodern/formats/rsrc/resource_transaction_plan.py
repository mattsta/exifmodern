"""Source-grounded Mac RSRC resource-fork transaction planning.

The planner mirrors the read and preservation duties in ExifTool's RSRC.pm:
validate the header, bounds-check data and map sections, walk the type list and
resource references, keep resource payloads intact, record standard RSRC tag
routing, and keep byte edits behind explicit gates.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

RSRC_HEADER_READ_SIZE = 30
RSRC_MIN_SECTION_OFFSET = 0x10
RSRC_MIN_MAP_LENGTH = 30
RSRC_TYPE_ENTRY_SIZE = 8
RSRC_REFERENCE_ENTRY_SIZE = 12
RSRC_MAX_VALUE_LENGTH = 100_000_000
RSRC_PM_SOURCE_PATH = "lib/Image/ExifTool/RSRC.pm"

type RsrcPlanStatus = Literal["planned", "unsupported"]
type RsrcSectionKind = Literal["data", "map"]
type RsrcNameStatus = Literal["decoded", "absent", "empty", "offset_out_of_range", "truncated"]
type RsrcActionKind = Literal[
    "preserve_resource_payload",
    "route_photoshop_resource",
    "delegate_font_resource",
    "delegate_postscript_resource",
    "route_version_resource",
    "route_pascal_string_resource",
    "route_user_resource",
    "route_string_list_resource",
    "route_text_resource",
    "block_resource_rewrite",
]
type RsrcMetadataResponsibilityKind = Literal[
    "photoshop_info",
    "font",
    "postscript_font",
    "open_with_application",
    "application_version",
    "application_missing_message",
    "creator_application",
    "keywords",
    "description",
]
type RsrcEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_header",
    "invalid_data_offset",
    "data_section_truncated",
    "invalid_map_offset",
    "map_section_truncated",
    "truncated_map",
    "overlapping_data_map_sections",
    "invalid_type_list_offset",
    "invalid_name_list_offset",
    "type_entry_truncated",
    "reference_list_truncated",
    "resource_data_offset_out_of_range",
    "resource_length_too_large",
    "resource_length_truncated",
    "name_offset_out_of_range",
    "name_length_truncated",
    "map_offset_rewrite_blocked",
    "data_offset_rewrite_blocked",
    "resource_payload_rewrite_blocked",
    "no_rsrc_rewrite_behavior",
]

RSRC_MAIN_SOURCE = "rsrc.main"
RSRC_NOTES_SOURCE = "rsrc.notes"
RSRC_PROCESS_SOURCE = "rsrc.process"
RSRC_HEADER_SOURCE = "rsrc.header"
RSRC_MAP_SOURCE = "rsrc.map"
RSRC_REFERENCE_SOURCE = "rsrc.reference"
RSRC_DATA_SOURCE = "rsrc.data"
RSRC_NAME_SOURCE = "rsrc.name"
RSRC_TAG_SOURCE = "rsrc.tag"

RSRC_RESOURCE_TRANSACTION_SOURCES = (
    RSRC_MAIN_SOURCE,
    RSRC_NOTES_SOURCE,
    RSRC_PROCESS_SOURCE,
    RSRC_HEADER_SOURCE,
    RSRC_MAP_SOURCE,
    RSRC_REFERENCE_SOURCE,
    RSRC_DATA_SOURCE,
    RSRC_NAME_SOURCE,
    RSRC_TAG_SOURCE,
)

STANDARD_RESOURCE_KEYS: dict[str, tuple[RsrcMetadataResponsibilityKind, str]] = {
    "8BIM": ("photoshop_info", "PhotoshopInfo"),
    "sfnt": ("font", "Font"),
    "POST_0x01f5": ("postscript_font", "PostscriptFont"),
    "usro_0x0000": ("open_with_application", "OpenWithApplication"),
    "vers_0x0001": ("application_version", "ApplicationVersion"),
    "STR _0xbff3": ("application_missing_message", "ApplicationMissingMsg"),
    "STR _0xbff4": ("creator_application", "CreatorApplication"),
    "STR#_0x0080": ("keywords", "Keywords"),
    "TEXT_0x0080": ("description", "Description"),
}


@dataclass(frozen=True)
class RsrcResourceWriteRequest:
    resource_type: str
    resource_id: int
    replacement_payload: bytes
    reason: str


@dataclass(frozen=True)
class RsrcEmissionGate:
    code: RsrcEmissionGateCode
    reason: str
    blocks_emission: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RsrcHeaderPlan:
    data_offset: int | None
    map_offset: int | None
    data_length: int | None
    map_length: int | None
    file_length: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RsrcSectionBoundsPlan:
    kind: RsrcSectionKind
    offset: int
    length: int
    end_offset: int
    is_within_file: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RsrcMapPlan:
    type_list_offset: int
    name_list_offset: int
    declared_type_count: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RsrcTypeEntryPlan:
    index: int
    resource_type: str
    resource_count: int
    reference_list_offset: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RsrcResourceNamePlan:
    raw_name_offset: int
    absolute_offset: int | None
    status: RsrcNameStatus
    declared_length: int | None
    decoded_name: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RsrcResourceDataPlan:
    relative_data_offset: int
    absolute_length_offset: int
    absolute_payload_offset: int | None
    declared_length: int | None
    payload: bytes | None
    payload_preserved: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RsrcResourceReferencePlan:
    type_index: int
    reference_index: int
    resource_type: str
    resource_id: int
    tag_key: str
    standard_tag_name: str | None
    name: RsrcResourceNamePlan
    data: RsrcResourceDataPlan
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RsrcMetadataResponsibilityPlan:
    kind: RsrcMetadataResponsibilityKind
    tag_key: str
    tag_name: str
    resource_type: str
    resource_id: int
    decoded_values: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RsrcResourceActionPlan:
    kind: RsrcActionKind
    tag_key: str
    target: str
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RsrcResourceTransactionPlan:
    status: RsrcPlanStatus
    header: RsrcHeaderPlan
    sections: tuple[RsrcSectionBoundsPlan, ...]
    map_plan: RsrcMapPlan | None
    type_entries: tuple[RsrcTypeEntryPlan, ...]
    resources: tuple[RsrcResourceReferencePlan, ...]
    responsibilities: tuple[RsrcMetadataResponsibilityPlan, ...]
    actions: tuple[RsrcResourceActionPlan, ...]
    requested_resource_rewrites: tuple[RsrcResourceWriteRequest, ...]
    output_emission_gates: tuple[RsrcEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_data: bytes

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not any(
            gate.blocks_emission for gate in self.output_emission_gates
        )

    @property
    def preserved_payload_bytes(self) -> int:
        return sum(
            resource.data.declared_length
            for resource in self.resources
            if resource.data.payload_preserved and resource.data.declared_length is not None
        )

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        if gate_codes:
            raise ValueError(f"RSRC resource transaction output is gated: {gate_codes}")
        return self.original_data


def build_rsrc_resource_transaction_plan(
    rsrc_data: bytes,
    *,
    resource_rewrite_requests: Iterable[RsrcResourceWriteRequest] = (),
    allow_output_emission: bool = False,
) -> RsrcResourceTransactionPlan:
    requests = tuple(resource_rewrite_requests)
    gates: list[RsrcEmissionGate] = []
    header = _parse_header(rsrc_data, gates)
    sections = _section_bounds(header)
    map_plan: RsrcMapPlan | None = None
    type_entries: tuple[RsrcTypeEntryPlan, ...] = ()
    resources: tuple[RsrcResourceReferencePlan, ...] = ()
    if _header_allows_map(header, gates):
        if (
            header.data_offset is not None
            and header.map_offset is not None
            and header.map_length is not None
        ):
            data_offset = header.data_offset
            map_offset = header.map_offset
            map_bytes = rsrc_data[map_offset : map_offset + header.map_length]
            map_plan = _parse_map(map_bytes, gates)
            if map_plan is not None:
                type_entries = _parse_type_entries(map_bytes, map_plan, gates)
                resources = _parse_reevidence_ids(
                    rsrc_data=rsrc_data,
                    map_bytes=map_bytes,
                    data_offset=data_offset,
                    map_offset=map_offset,
                    map_plan=map_plan,
                    type_entries=type_entries,
                    gates=gates,
                )
    responsibilities = _plan_responsibilities(resources)
    actions = _plan_actions(resources, responsibilities, requests)
    gates.extend(_rewrite_blockers(requests))
    _add_explicit_emission_gate(gates, allow_output_emission)
    gates_tuple = _unique_gates(tuple(gates))
    status: RsrcPlanStatus = "unsupported" if _has_structural_blocker(gates_tuple) else "planned"
    return RsrcResourceTransactionPlan(
        status=status,
        header=header,
        sections=sections,
        map_plan=map_plan,
        type_entries=type_entries,
        resources=resources,
        responsibilities=responsibilities,
        actions=actions,
        requested_resource_rewrites=requests,
        output_emission_gates=gates_tuple,
        evidence_ids=_collect_sources(
            header=header,
            sections=sections,
            map_plan=map_plan,
            type_entries=type_entries,
            resources=resources,
            responsibilities=responsibilities,
            actions=actions,
            gates=gates_tuple,
        ),
        original_data=rsrc_data,
    )


plan_rsrc_resource_transaction = build_rsrc_resource_transaction_plan


def _parse_header(rsrc_data: bytes, gates: list[RsrcEmissionGate]) -> RsrcHeaderPlan:
    if len(rsrc_data) < RSRC_HEADER_READ_SIZE:
        gates.append(
            RsrcEmissionGate(
                code="truncated_header",
                reason="Input ended before ExifTool's 30-byte RSRC header read.",
                blocks_emission=True,
                evidence_ids=(RSRC_HEADER_SOURCE,),
            )
        )
        return RsrcHeaderPlan(
            data_offset=None,
            map_offset=None,
            data_length=None,
            map_length=None,
            file_length=len(rsrc_data),
            evidence_ids=(RSRC_HEADER_SOURCE,),
        )
    data_offset = _u32(rsrc_data, 0)
    map_offset = _u32(rsrc_data, 4)
    data_length = _u32(rsrc_data, 8)
    map_length = _u32(rsrc_data, 12)
    file_length = len(rsrc_data)
    if data_offset < RSRC_MIN_SECTION_OFFSET:
        gates.append(
            RsrcEmissionGate(
                code="invalid_data_offset",
                reason="The data section offset is before ExifTool's minimum 0x10 boundary.",
                blocks_emission=True,
                evidence_ids=(RSRC_HEADER_SOURCE,),
            )
        )
    if data_offset + data_length > file_length:
        gates.append(
            RsrcEmissionGate(
                code="data_section_truncated",
                reason="The declared data section extends past the file length.",
                blocks_emission=True,
                evidence_ids=(RSRC_HEADER_SOURCE,),
            )
        )
    if map_offset < RSRC_MIN_SECTION_OFFSET:
        gates.append(
            RsrcEmissionGate(
                code="invalid_map_offset",
                reason="The map section offset is before ExifTool's minimum 0x10 boundary.",
                blocks_emission=True,
                evidence_ids=(RSRC_HEADER_SOURCE,),
            )
        )
    if map_offset + map_length > file_length:
        gates.append(
            RsrcEmissionGate(
                code="map_section_truncated",
                reason="The declared map section extends past the file length.",
                blocks_emission=True,
                evidence_ids=(RSRC_HEADER_SOURCE,),
            )
        )
    if map_length < RSRC_MIN_MAP_LENGTH:
        gates.append(
            RsrcEmissionGate(
                code="truncated_map",
                reason="The declared map length is shorter than ExifTool's 30-byte minimum.",
                blocks_emission=True,
                evidence_ids=(RSRC_HEADER_SOURCE, RSRC_MAP_SOURCE),
            )
        )
    if data_offset < map_offset and data_offset + data_length > map_offset:
        gates.append(
            RsrcEmissionGate(
                code="overlapping_data_map_sections",
                reason="The data section overlaps the map section.",
                blocks_emission=True,
                evidence_ids=(RSRC_HEADER_SOURCE,),
            )
        )
    if map_offset < data_offset and map_offset + map_length > data_offset:
        gates.append(
            RsrcEmissionGate(
                code="overlapping_data_map_sections",
                reason="The map section overlaps the data section.",
                blocks_emission=True,
                evidence_ids=(RSRC_HEADER_SOURCE,),
            )
        )
    return RsrcHeaderPlan(
        data_offset=data_offset,
        map_offset=map_offset,
        data_length=data_length,
        map_length=map_length,
        file_length=file_length,
        evidence_ids=(RSRC_HEADER_SOURCE,),
    )


def _section_bounds(header: RsrcHeaderPlan) -> tuple[RsrcSectionBoundsPlan, ...]:
    if (
        header.data_offset is None
        or header.map_offset is None
        or header.data_length is None
        or header.map_length is None
    ):
        return ()
    return (
        RsrcSectionBoundsPlan(
            kind="data",
            offset=header.data_offset,
            length=header.data_length,
            end_offset=header.data_offset + header.data_length,
            is_within_file=header.data_offset + header.data_length <= header.file_length,
            evidence_ids=(RSRC_HEADER_SOURCE,),
        ),
        RsrcSectionBoundsPlan(
            kind="map",
            offset=header.map_offset,
            length=header.map_length,
            end_offset=header.map_offset + header.map_length,
            is_within_file=header.map_offset + header.map_length <= header.file_length,
            evidence_ids=(RSRC_HEADER_SOURCE, RSRC_MAP_SOURCE),
        ),
    )


def _header_allows_map(header: RsrcHeaderPlan, gates: list[RsrcEmissionGate]) -> bool:
    if (
        header.data_offset is None
        or header.map_offset is None
        or header.data_length is None
        or header.map_length is None
    ):
        return False
    blocking_codes = {
        gate.code
        for gate in gates
        if gate.blocks_emission
        and gate.code
        in {
            "truncated_header",
            "invalid_data_offset",
            "data_section_truncated",
            "invalid_map_offset",
            "map_section_truncated",
            "truncated_map",
            "overlapping_data_map_sections",
        }
    }
    return not blocking_codes


def _parse_map(map_bytes: bytes, gates: list[RsrcEmissionGate]) -> RsrcMapPlan | None:
    if len(map_bytes) < RSRC_MIN_MAP_LENGTH:
        gates.append(
            RsrcEmissionGate(
                code="truncated_map",
                reason="The resource map is shorter than ExifTool's map header reads.",
                blocks_emission=True,
                evidence_ids=(RSRC_MAP_SOURCE,),
            )
        )
        return None
    type_list_offset = _u16(map_bytes, 24)
    name_list_offset = _u16(map_bytes, 26)
    declared_type_count = (_u16(map_bytes, 28) + 1) & 0xFFFF
    if type_list_offset < 28:
        gates.append(
            RsrcEmissionGate(
                code="invalid_type_list_offset",
                reason="The resource type list offset is before ExifTool's accepted boundary.",
                blocks_emission=True,
                evidence_ids=(RSRC_MAP_SOURCE,),
            )
        )
    if name_list_offset < 30:
        gates.append(
            RsrcEmissionGate(
                code="invalid_name_list_offset",
                reason="The resource name list offset is before ExifTool's accepted boundary.",
                blocks_emission=True,
                evidence_ids=(RSRC_MAP_SOURCE,),
            )
        )
    if type_list_offset + 2 > len(map_bytes):
        gates.append(
            RsrcEmissionGate(
                code="type_entry_truncated",
                reason="The resource map ends before the type-list count field.",
                blocks_emission=True,
                evidence_ids=(RSRC_MAP_SOURCE, RSRC_REFERENCE_SOURCE),
            )
        )
    return RsrcMapPlan(
        type_list_offset=type_list_offset,
        name_list_offset=name_list_offset,
        declared_type_count=declared_type_count,
        evidence_ids=(RSRC_MAP_SOURCE,),
    )


def _parse_type_entries(
    map_bytes: bytes,
    map_plan: RsrcMapPlan,
    gates: list[RsrcEmissionGate],
) -> tuple[RsrcTypeEntryPlan, ...]:
    entries: list[RsrcTypeEntryPlan] = []
    for index in range(map_plan.declared_type_count):
        offset = map_plan.type_list_offset + 2 + RSRC_TYPE_ENTRY_SIZE * index
        if offset + RSRC_TYPE_ENTRY_SIZE > len(map_bytes):
            gates.append(
                RsrcEmissionGate(
                    code="type_entry_truncated",
                    reason="A declared resource type entry extends past the map section.",
                    blocks_emission=True,
                    evidence_ids=(RSRC_REFERENCE_SOURCE,),
                )
            )
            break
        raw_type = map_bytes[offset : offset + 4]
        entries.append(
            RsrcTypeEntryPlan(
                index=index,
                resource_type=raw_type.decode("latin-1"),
                resource_count=_u16(map_bytes, offset + 4) + 1,
                reference_list_offset=map_plan.type_list_offset + _u16(map_bytes, offset + 6),
                evidence_ids=(RSRC_REFERENCE_SOURCE,),
            )
        )
    return tuple(entries)


def _parse_reevidence_ids(
    *,
    rsrc_data: bytes,
    map_bytes: bytes,
    data_offset: int,
    map_offset: int,
    map_plan: RsrcMapPlan,
    type_entries: tuple[RsrcTypeEntryPlan, ...],
    gates: list[RsrcEmissionGate],
) -> tuple[RsrcResourceReferencePlan, ...]:
    resources: list[RsrcResourceReferencePlan] = []
    for type_entry in type_entries:
        for reference_index in range(type_entry.resource_count):
            reference_offset = (
                type_entry.reference_list_offset + RSRC_REFERENCE_ENTRY_SIZE * reference_index
            )
            if reference_offset + RSRC_REFERENCE_ENTRY_SIZE > len(map_bytes):
                gates.append(
                    RsrcEmissionGate(
                        code="reference_list_truncated",
                        reason="A resource reference entry extends past the map section.",
                        blocks_emission=True,
                        evidence_ids=(RSRC_REFERENCE_SOURCE,),
                    )
                )
                break
            resource_id = _u16(map_bytes, reference_offset)
            raw_name_offset = _u16(map_bytes, reference_offset + 2)
            relative_data_offset = _u32(map_bytes, reference_offset + 4) & 0x00FFFFFF
            tag_key = _tag_key(type_entry.resource_type, resource_id)
            resources.append(
                RsrcResourceReferencePlan(
                    type_index=type_entry.index,
                    reference_index=reference_index,
                    resource_type=type_entry.resource_type,
                    resource_id=resource_id,
                    tag_key=tag_key,
                    standard_tag_name=_standard_tag_name(tag_key),
                    name=_read_resource_name(
                        rsrc_data=rsrc_data,
                        map_offset=map_offset,
                        map_plan=map_plan,
                        raw_name_offset=raw_name_offset,
                        gates=gates,
                    ),
                    data=_read_resource_data(
                        rsrc_data=rsrc_data,
                        data_offset=data_offset,
                        relative_data_offset=relative_data_offset,
                        gates=gates,
                    ),
                    evidence_ids=(RSRC_REFERENCE_SOURCE,),
                )
            )
    return tuple(resources)


def _read_resource_name(
    *,
    rsrc_data: bytes,
    map_offset: int,
    map_plan: RsrcMapPlan,
    raw_name_offset: int,
    gates: list[RsrcEmissionGate],
) -> RsrcResourceNamePlan:
    if raw_name_offset == 0xFFFF:
        return RsrcResourceNamePlan(
            raw_name_offset=raw_name_offset,
            absolute_offset=None,
            status="absent",
            declared_length=None,
            decoded_name=None,
            evidence_ids=(RSRC_NAME_SOURCE,),
        )
    absolute_offset = map_offset + map_plan.name_list_offset + raw_name_offset
    if absolute_offset >= len(rsrc_data):
        gates.append(
            RsrcEmissionGate(
                code="name_offset_out_of_range",
                reason="The resource name offset points past the input bytes.",
                blocks_emission=False,
                evidence_ids=(RSRC_NAME_SOURCE,),
            )
        )
        return RsrcResourceNamePlan(
            raw_name_offset=raw_name_offset,
            absolute_offset=absolute_offset,
            status="offset_out_of_range",
            declared_length=None,
            decoded_name=None,
            evidence_ids=(RSRC_NAME_SOURCE,),
        )
    length = rsrc_data[absolute_offset]
    if length == 0:
        return RsrcResourceNamePlan(
            raw_name_offset=raw_name_offset,
            absolute_offset=absolute_offset,
            status="empty",
            declared_length=0,
            decoded_name="",
            evidence_ids=(RSRC_NAME_SOURCE,),
        )
    name_start = absolute_offset + 1
    name_end = name_start + length
    if name_end > len(rsrc_data):
        gates.append(
            RsrcEmissionGate(
                code="name_length_truncated",
                reason="The Pascal resource name length extends past the input bytes.",
                blocks_emission=False,
                evidence_ids=(RSRC_NAME_SOURCE,),
            )
        )
        return RsrcResourceNamePlan(
            raw_name_offset=raw_name_offset,
            absolute_offset=absolute_offset,
            status="truncated",
            declared_length=length,
            decoded_name=None,
            evidence_ids=(RSRC_NAME_SOURCE,),
        )
    return RsrcResourceNamePlan(
        raw_name_offset=raw_name_offset,
        absolute_offset=absolute_offset,
        status="decoded",
        declared_length=length,
        decoded_name=rsrc_data[name_start:name_end].decode("macroman", errors="replace"),
        evidence_ids=(RSRC_NAME_SOURCE,),
    )


def _read_resource_data(
    *,
    rsrc_data: bytes,
    data_offset: int,
    relative_data_offset: int,
    gates: list[RsrcEmissionGate],
) -> RsrcResourceDataPlan:
    length_offset = data_offset + relative_data_offset
    if length_offset + 4 > len(rsrc_data):
        gates.append(
            RsrcEmissionGate(
                code="resource_data_offset_out_of_range",
                reason="The 24-bit resource data offset does not reach a length field.",
                blocks_emission=True,
                evidence_ids=(RSRC_REFERENCE_SOURCE, RSRC_DATA_SOURCE),
            )
        )
        return RsrcResourceDataPlan(
            relative_data_offset=relative_data_offset,
            absolute_length_offset=length_offset,
            absolute_payload_offset=None,
            declared_length=None,
            payload=None,
            payload_preserved=False,
            evidence_ids=(RSRC_REFERENCE_SOURCE, RSRC_DATA_SOURCE),
        )
    declared_length = _u32(rsrc_data, length_offset)
    payload_offset = length_offset + 4
    if declared_length >= RSRC_MAX_VALUE_LENGTH:
        gates.append(
            RsrcEmissionGate(
                code="resource_length_too_large",
                reason="Resource length reaches ExifTool's 100MB safety cap.",
                blocks_emission=True,
                evidence_ids=(RSRC_DATA_SOURCE,),
            )
        )
        payload = None
    elif payload_offset + declared_length > len(rsrc_data):
        gates.append(
            RsrcEmissionGate(
                code="resource_length_truncated",
                reason="The declared resource payload extends past the input bytes.",
                blocks_emission=True,
                evidence_ids=(RSRC_DATA_SOURCE,),
            )
        )
        payload = None
    else:
        payload = rsrc_data[payload_offset : payload_offset + declared_length]
    return RsrcResourceDataPlan(
        relative_data_offset=relative_data_offset,
        absolute_length_offset=length_offset,
        absolute_payload_offset=payload_offset,
        declared_length=declared_length,
        payload=payload,
        payload_preserved=payload is not None,
        evidence_ids=(RSRC_REFERENCE_SOURCE, RSRC_DATA_SOURCE),
    )


def _plan_responsibilities(
    resources: tuple[RsrcResourceReferencePlan, ...],
) -> tuple[RsrcMetadataResponsibilityPlan, ...]:
    responsibilities: list[RsrcMetadataResponsibilityPlan] = []
    for resource in resources:
        standard = STANDARD_RESOURCE_KEYS.get(resource.tag_key)
        if standard is None or resource.data.payload is None:
            continue
        kind, tag_name = standard
        responsibilities.append(
            RsrcMetadataResponsibilityPlan(
                kind=kind,
                tag_key=resource.tag_key,
                tag_name=tag_name,
                resource_type=resource.resource_type,
                resource_id=resource.resource_id,
                decoded_values=_decode_standard_values(resource),
                evidence_ids=(RSRC_MAIN_SOURCE, RSRC_TAG_SOURCE),
            )
        )
    return tuple(responsibilities)


def _plan_actions(
    resources: tuple[RsrcResourceReferencePlan, ...],
    responsibilities: tuple[RsrcMetadataResponsibilityPlan, ...],
    requests: tuple[RsrcResourceWriteRequest, ...],
) -> tuple[RsrcResourceActionPlan, ...]:
    actions: list[RsrcResourceActionPlan] = []
    responsibility_by_key = {item.tag_key: item for item in responsibilities}
    for resource in resources:
        actions.append(
            RsrcResourceActionPlan(
                kind="preserve_resource_payload",
                tag_key=resource.tag_key,
                target=resource.tag_key,
                reason="Resource data is retained byte-for-byte in the plan.",
                evidence_ids=(RSRC_NOTES_SOURCE, RSRC_DATA_SOURCE),
            )
        )
        responsibility = responsibility_by_key.get(resource.tag_key)
        if responsibility is not None:
            actions.append(
                RsrcResourceActionPlan(
                    kind=_action_for_responsibility(responsibility.kind),
                    tag_key=resource.tag_key,
                    target=responsibility.tag_name,
                    reason="Standard RSRC metadata is routed the same way RSRC.pm routes it.",
                    evidence_ids=(RSRC_MAIN_SOURCE, RSRC_TAG_SOURCE),
                )
            )
    for request in requests:
        actions.append(
            RsrcResourceActionPlan(
                kind="block_resource_rewrite",
                tag_key=_tag_key(request.resource_type, request.resource_id),
                target=f"{request.resource_type}_0x{request.resource_id:04x}",
                reason=request.reason,
                evidence_ids=(RSRC_NOTES_SOURCE,),
            )
        )
    return tuple(actions)


def _decode_standard_values(resource: RsrcResourceReferencePlan) -> tuple[str, ...]:
    payload = resource.data.payload
    if payload is None:
        return ()
    if resource.resource_type == "vers" and len(payload) > 8:
        short_length = payload[6]
        position = 7 + short_length
        if position < len(payload):
            long_length = payload[position]
            value_start = position + 1
            if value_start + long_length <= len(payload):
                return (payload[value_start : value_start + long_length].decode("macroman"),)
    if resource.resource_type == "STR " and len(payload) > 1:
        length = payload[0]
        if len(payload) >= length + 1:
            return (payload[1 : length + 1].decode("macroman"),)
    if resource.resource_type == "usro" and len(payload) > 4:
        length = _u32(payload, 0)
        if len(payload) >= length + 4:
            value = payload[4 : length + 4].split(b"\0", 1)[0]
            return (value.decode("macroman"),)
    if resource.resource_type == "STR#" and len(payload) > 2:
        count = _u16(payload, 0)
        if count & 0xF000:
            return ()
        values: list[str] = []
        position = 2
        for _index in range(count):
            if position >= len(payload):
                break
            length = payload[position]
            position += 1
            if position + length > len(payload):
                break
            values.append(payload[position : position + length].decode("macroman"))
            position += length
        return tuple(values)
    if resource.resource_type == "TEXT":
        return (payload.decode("macroman"),)
    return ()


def _action_for_responsibility(kind: RsrcMetadataResponsibilityKind) -> RsrcActionKind:
    if kind == "photoshop_info":
        return "route_photoshop_resource"
    if kind == "font":
        return "delegate_font_resource"
    if kind == "postscript_font":
        return "delegate_postscript_resource"
    if kind == "application_version":
        return "route_version_resource"
    if kind in {"application_missing_message", "creator_application"}:
        return "route_pascal_string_resource"
    if kind == "open_with_application":
        return "route_user_resource"
    if kind == "keywords":
        return "route_string_list_resource"
    return "route_text_resource"


def _rewrite_blockers(
    requests: tuple[RsrcResourceWriteRequest, ...],
) -> tuple[RsrcEmissionGate, ...]:
    if not requests:
        return ()
    return (
        RsrcEmissionGate(
            code="map_offset_rewrite_blocked",
            reason="RSRC rewrites would have to preserve or adjust resource-map offsets.",
            blocks_emission=True,
            evidence_ids=(RSRC_HEADER_SOURCE, RSRC_MAP_SOURCE, RSRC_REFERENCE_SOURCE),
        ),
        RsrcEmissionGate(
            code="data_offset_rewrite_blocked",
            reason="RSRC rewrites would have to preserve or adjust resource-data offsets.",
            blocks_emission=True,
            evidence_ids=(RSRC_HEADER_SOURCE, RSRC_REFERENCE_SOURCE),
        ),
        RsrcEmissionGate(
            code="resource_payload_rewrite_blocked",
            reason="RSRC.pm reads resource payloads but does not define payload rewrite logic.",
            blocks_emission=True,
            evidence_ids=(RSRC_DATA_SOURCE, RSRC_TAG_SOURCE),
        ),
        RsrcEmissionGate(
            code="no_rsrc_rewrite_behavior",
            reason="RSRC.pm documents preservation by default and deletion, not resource edits.",
            blocks_emission=True,
            evidence_ids=(RSRC_NOTES_SOURCE,),
        ),
    )


def _add_explicit_emission_gate(
    gates: list[RsrcEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        RsrcEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="The RSRC planner emits original bytes only when explicitly allowed.",
            blocks_emission=True,
            evidence_ids=(RSRC_NOTES_SOURCE,),
        )
    )


def _unique_gates(gates: tuple[RsrcEmissionGate, ...]) -> tuple[RsrcEmissionGate, ...]:
    seen: set[RsrcEmissionGateCode] = set()
    unique: list[RsrcEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def _has_structural_blocker(gates: tuple[RsrcEmissionGate, ...]) -> bool:
    structural_codes: set[RsrcEmissionGateCode] = {
        "truncated_header",
        "invalid_data_offset",
        "data_section_truncated",
        "invalid_map_offset",
        "map_section_truncated",
        "truncated_map",
        "overlapping_data_map_sections",
        "invalid_type_list_offset",
        "invalid_name_list_offset",
        "type_entry_truncated",
        "reference_list_truncated",
        "resource_data_offset_out_of_range",
        "resource_length_too_large",
        "resource_length_truncated",
    }
    return any(gate.code in structural_codes for gate in gates)


def _collect_sources(
    *,
    header: RsrcHeaderPlan,
    sections: tuple[RsrcSectionBoundsPlan, ...],
    map_plan: RsrcMapPlan | None,
    type_entries: tuple[RsrcTypeEntryPlan, ...],
    resources: tuple[RsrcResourceReferencePlan, ...],
    responsibilities: tuple[RsrcMetadataResponsibilityPlan, ...],
    actions: tuple[RsrcResourceActionPlan, ...],
    gates: tuple[RsrcEmissionGate, ...],
) -> tuple[str, ...]:
    sources: list[str] = [RSRC_PROCESS_SOURCE, *header.evidence_ids]
    for section in sections:
        sources.extend(section.evidence_ids)
    if map_plan is not None:
        sources.extend(map_plan.evidence_ids)
    for entry in type_entries:
        sources.extend(entry.evidence_ids)
    for resource in resources:
        sources.extend(resource.evidence_ids)
        sources.extend(resource.name.evidence_ids)
        sources.extend(resource.data.evidence_ids)
    for responsibility in responsibilities:
        sources.extend(responsibility.evidence_ids)
    for action in actions:
        sources.extend(action.evidence_ids)
    for gate in gates:
        sources.extend(gate.evidence_ids)
    return _unique_sources(tuple(sources))


def _unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for source in sources:
        key = source
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return tuple(unique)


def _tag_key(resource_type: str, resource_id: int) -> str:
    if resource_type in STANDARD_RESOURCE_KEYS:
        return resource_type
    return f"{resource_type}_0x{resource_id:04x}"


def _standard_tag_name(tag_key: str) -> str | None:
    standard = STANDARD_RESOURCE_KEYS.get(tag_key)
    if standard is None:
        return None
    return standard[1]


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")
