"""Source-backed, non-mutating ITC metadata transaction plans.

The planner mirrors the read-side block traversal in ExifTool's ITC module.
It validates the first ``itch`` block, walks later blocks, routes known header
and item metadata from the source tables, preserves unknown and image payloads,
and keeps byte emission behind explicit gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonObject

ITC_BLOCK_HEADER_SIZE = 8
ITC_INITIAL_ITCH_MIN_SIZE = 0x1C
ITC_INITIAL_ITCH_MAX_SIZE = 0x10000
ITC_LATER_BLOCK_MAX_SIZE = 0x80000000
ITC_HEADER_DATA_TYPE_OFFSET = 0x10
ITC_ITEM_MIN_HEADER_SIZE = 0xD0
ITC_ITEM_DATA_MARKER_OFFSET = 0xB0
ITC_ITEM_DATA_MARKER_SIZE = 4

type ItcContainerKind = Literal["itc", "unknown"]
type ItcTableName = Literal["main", "header", "item"]
type ItcBlockKind = Literal["itch", "item", "unknown"]
type ItcBlockAction = Literal[
    "route_header_metadata",
    "route_item_metadata",
    "preserve_unknown_block",
    "block_malformed",
]
type ItcPayloadKind = Literal["image_data", "unknown_block"]
type ItcMetadataRole = Literal[
    "data_type",
    "library_id",
    "track_id",
    "data_location",
    "image_type",
    "image_dimensions",
]
type ItcRouteAction = Literal["upsert_metadata", "delete_metadata"]
type ItcEmissionGateCode = Literal[
    "truncated_itc_block_header",
    "unsupported_itc_signature",
    "invalid_initial_itch_size",
    "invalid_itc_block_size",
    "truncated_itc_block_payload",
    "invalid_item_block_size",
    "invalid_item_header_length",
    "missing_item_terminator",
    "item_data_boundary_missing",
    "metadata_rewrite_unsupported",
    "image_payload_rewrite_unsupported",
    "planner_is_non_mutating",
    "full_itc_writer_not_implemented",
]
type ItcResponsibilityConcern = Literal[
    "signature_header_validation",
    "block_enumeration",
    "header_metadata_routing",
    "item_metadata_routing",
    "image_payload_preservation",
    "unknown_block_preservation",
    "malformed_truncation_blockers",
    "rewrite_blockers",
    "output_emission_gate",
]

ITC_PM_SOURCE_PATH = "lib/Image/ExifTool/ITC.pm"

ITC_MAIN_TABLE_SOURCE = "itc.pm.main-table"
ITC_HEADER_TABLE_SOURCE = "itc.pm.header-table"
ITC_ITEM_TABLE_SOURCE = "itc.pm.item-table"
ITC_BLOCK_VALIDATION_SOURCE = "itc.pm.process-itc.block-validation"
ITC_HEADER_PROCESS_SOURCE = "itc.pm.process-itc.itch-processing"
ITC_ITEM_PROCESS_SOURCE = "itc.pm.process-itc.item-processing"
ITC_IMAGE_DATA_SOURCE = "itc.pm.process-itc.embedded-image-extraction"
ITC_UNKNOWN_BLOCK_SOURCE = "itc.pm.process-itc.unknown-block-preservation"
ITC_READ_ONLY_SOURCE = "itc.pm.read-only-description"


@dataclass(frozen=True)
class ItcTableEntryPlan:
    table: ItcTableName
    tag_id: str
    name: str
    role: ItcMetadataRole | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "name": self.name,
            "role": self.role,
            "table": self.table,
            "tag_id": self.tag_id,
        }


@dataclass(frozen=True)
class ItcHeaderValidation:
    container_kind: ItcContainerKind
    is_valid: bool
    first_block_tag: str | None
    first_block_size: int | None
    actual_file_size: int
    reason: ItcEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "actual_file_size": self.actual_file_size,
            "container_kind": self.container_kind,
            "first_block_size": self.first_block_size,
            "first_block_tag": self.first_block_tag,
            "is_valid": self.is_valid,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ItcBlockPlan:
    block_index: int
    tag: str
    block_kind: ItcBlockKind
    action: ItcBlockAction
    offset: int
    size: int
    payload_offset: int
    payload_size: int
    evidence_ids: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"block[{self.block_index}]/{self.tag}:{self.block_kind}"

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "block_index": self.block_index,
            "block_kind": self.block_kind,
            "label": self.label,
            "offset": self.offset,
            "payload_offset": self.payload_offset,
            "payload_size": self.payload_size,
            "size": self.size,
            "tag": self.tag,
        }


@dataclass(frozen=True)
class ItcMetadataEntryPlan:
    tag_id: str
    name: str
    role: ItcMetadataRole
    value: str | int
    raw_value_hex: str
    block_label: str
    value_offset: int
    value_size: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "block_label": self.block_label,
            "name": self.name,
            "raw_value_hex": self.raw_value_hex,
            "role": self.role,
            "tag_id": self.tag_id,
            "value": self.value,
            "value_offset": self.value_offset,
            "value_size": self.value_size,
        }


@dataclass(frozen=True)
class ItcItemBoundaryPlan:
    block_label: str
    item_header_length: int
    metadata_offset: int
    metadata_size: int
    image_payload_offset: int
    image_payload_size: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "block_label": self.block_label,
            "image_payload_offset": self.image_payload_offset,
            "image_payload_size": self.image_payload_size,
            "item_header_length": self.item_header_length,
            "metadata_offset": self.metadata_offset,
            "metadata_size": self.metadata_size,
        }


@dataclass(frozen=True)
class ItcPreservedPayloadPlan:
    payload_kind: ItcPayloadKind
    block_label: str
    offset: int
    length: int
    payload: bytes
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "block_label": self.block_label,
            "length": self.length,
            "offset": self.offset,
            "payload_hex": self.payload.hex(),
            "payload_kind": self.payload_kind,
        }


@dataclass(frozen=True)
class ItcMetadataRewriteRequest:
    tag_name: str
    value: str | int | None


@dataclass(frozen=True)
class ItcMetadataRoute:
    action: ItcRouteAction
    tag_name: str
    requested_value: str | int | None
    existing_value: str | int | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "existing_value": self.existing_value,
            "requested_value": self.requested_value,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class ItcResponsibility:
    order: int
    concern: ItcResponsibilityConcern
    description: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "description": self.description,
            "order": self.order,
        }


@dataclass(frozen=True)
class ItcEmissionGate:
    code: ItcEmissionGateCode
    reason: str
    blocks_emission: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocks_emission": self.blocks_emission,
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ItcMetadataTransactionPlan:
    header_validation: ItcHeaderValidation
    table_entries: tuple[ItcTableEntryPlan, ...]
    blocks: tuple[ItcBlockPlan, ...]
    item_boundaries: tuple[ItcItemBoundaryPlan, ...]
    metadata_entries: tuple[ItcMetadataEntryPlan, ...]
    preserved_payloads: tuple[ItcPreservedPayloadPlan, ...]
    routes: tuple[ItcMetadataRoute, ...]
    responsibilities: tuple[ItcResponsibility, ...]
    output_emission_gates: tuple[ItcEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def block_labels(self) -> tuple[str, ...]:
        return tuple(block.label for block in self.blocks)

    @property
    def preserved_image_payload_bytes(self) -> int:
        return sum(
            payload.length
            for payload in self.preserved_payloads
            if payload.payload_kind == "image_data"
        )

    @property
    def preserved_unknown_payload_bytes(self) -> int:
        return sum(
            payload.length
            for payload in self.preserved_payloads
            if payload.payload_kind == "unknown_block"
        )

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"ITC metadata transaction output is gated: {gate_codes}")

    def to_json(self) -> JsonObject:
        return {
            "block_labels": list(self.block_labels),
            "blocks": [block.to_json() for block in self.blocks],
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "header_validation": self.header_validation.to_json(),
            "item_boundaries": [boundary.to_json() for boundary in self.item_boundaries],
            "metadata_entries": [entry.to_json() for entry in self.metadata_entries],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "preserved_image_payload_bytes": self.preserved_image_payload_bytes,
            "preserved_payloads": [payload.to_json() for payload in self.preserved_payloads],
            "preserved_unknown_payload_bytes": self.preserved_unknown_payload_bytes,
            "responsibilities": [item.to_json() for item in self.responsibilities],
            "routes": [route.to_json() for route in self.routes],
            "table_entries": [entry.to_json() for entry in self.table_entries],
        }


@dataclass(frozen=True)
class _ParsedItem:
    boundary: ItcItemBoundaryPlan | None
    metadata_entries: tuple[ItcMetadataEntryPlan, ...]
    preserved_payload: ItcPreservedPayloadPlan | None
    gates: tuple[ItcEmissionGate, ...]


def build_itc_metadata_transaction_plan(
    data: bytes,
    rewrite_requests: tuple[ItcMetadataRewriteRequest, ...] = (),
) -> ItcMetadataTransactionPlan:
    """Build a non-mutating ITC metadata transaction plan."""

    (
        header,
        blocks,
        boundaries,
        metadata_entries,
        preserved_payloads,
        parse_gates,
    ) = inspect_itc(data)
    routes = route_rewrite_requests(metadata_entries, rewrite_requests)
    gates = [*parse_gates]
    if routes:
        gates.extend(rewrite_gates(routes))
    gates.extend(non_mutating_gates())
    table_entries = itc_table_entries()
    responsibilities = default_responsibilities()
    evidence_ids = unique_evidence_ids(
        (
            *header.evidence_ids,
            *(source for entry in table_entries for source in entry.evidence_ids),
            *(source for block in blocks for source in block.evidence_ids),
            *(source for boundary in boundaries for source in boundary.evidence_ids),
            *(source for entry in metadata_entries for source in entry.evidence_ids),
            *(source for payload in preserved_payloads for source in payload.evidence_ids),
            *(source for route in routes for source in route.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
            *(source for item in responsibilities for source in item.evidence_ids),
        )
    )
    return ItcMetadataTransactionPlan(
        header_validation=header,
        table_entries=table_entries,
        blocks=blocks,
        item_boundaries=boundaries,
        metadata_entries=metadata_entries,
        preserved_payloads=preserved_payloads,
        routes=routes,
        responsibilities=responsibilities,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=evidence_ids,
    )


def inspect_itc(
    data: bytes,
) -> tuple[
    ItcHeaderValidation,
    tuple[ItcBlockPlan, ...],
    tuple[ItcItemBoundaryPlan, ...],
    tuple[ItcMetadataEntryPlan, ...],
    tuple[ItcPreservedPayloadPlan, ...],
    tuple[ItcEmissionGate, ...],
]:
    actual_file_size = len(data)
    if actual_file_size < ITC_BLOCK_HEADER_SIZE:
        return (
            ItcHeaderValidation(
                container_kind="unknown",
                is_valid=False,
                first_block_tag=None,
                first_block_size=None,
                actual_file_size=actual_file_size,
                reason="truncated_itc_block_header",
                evidence_ids=(ITC_BLOCK_VALIDATION_SOURCE,),
            ),
            (),
            (),
            (),
            (),
            (
                ItcEmissionGate(
                    "truncated_itc_block_header",
                    "ProcessITC requires 8 bytes for each block header.",
                    True,
                    (ITC_BLOCK_VALIDATION_SOURCE,),
                ),
            ),
        )

    first_size = read_u32be(data, 0)
    first_tag = decode_tag(data[4:8])
    invalid_first_reason = first_block_invalid_reason(first_tag, first_size)
    if invalid_first_reason is not None:
        return (
            ItcHeaderValidation(
                container_kind="unknown",
                is_valid=False,
                first_block_tag=first_tag,
                first_block_size=first_size,
                actual_file_size=actual_file_size,
                reason=invalid_first_reason,
                evidence_ids=(ITC_BLOCK_VALIDATION_SOURCE,),
            ),
            (),
            (),
            (),
            (),
            (first_block_gate(invalid_first_reason),),
        )

    header = ItcHeaderValidation(
        container_kind="itc",
        is_valid=True,
        first_block_tag=first_tag,
        first_block_size=first_size,
        actual_file_size=actual_file_size,
        reason=None,
        evidence_ids=(ITC_BLOCK_VALIDATION_SOURCE,),
    )
    blocks: list[ItcBlockPlan] = []
    boundaries: list[ItcItemBoundaryPlan] = []
    metadata_entries: list[ItcMetadataEntryPlan] = []
    preserved_payloads: list[ItcPreservedPayloadPlan] = []
    gates: list[ItcEmissionGate] = []
    offset = 0
    block_index = 0
    while offset < actual_file_size:
        remaining = actual_file_size - offset
        if remaining < ITC_BLOCK_HEADER_SIZE:
            gates.append(
                ItcEmissionGate(
                    "truncated_itc_block_header",
                    "ProcessITC stops with a format warning on a short block header.",
                    True,
                    (ITC_BLOCK_VALIDATION_SOURCE,),
                )
            )
            break
        block_size = read_u32be(data, offset)
        tag = decode_tag(data[offset + 4 : offset + 8])
        invalid_later_block_size = (
            block_size < ITC_BLOCK_HEADER_SIZE or block_size >= ITC_LATER_BLOCK_MAX_SIZE
        )
        if block_index > 0 and invalid_later_block_size:
            gates.append(
                ItcEmissionGate(
                    "invalid_itc_block_size",
                    "ProcessITC requires later block sizes to be at least 8 and below 0x80000000.",
                    True,
                    (ITC_BLOCK_VALIDATION_SOURCE,),
                )
            )
            break
        block_end = offset + block_size
        if block_end > actual_file_size:
            gates.append(
                ItcEmissionGate(
                    "truncated_itc_block_payload",
                    "ProcessITC requires each declared block payload to be fully readable.",
                    True,
                    (ITC_BLOCK_VALIDATION_SOURCE,),
                )
            )
            break
        block = make_block(block_index, tag, offset, block_size)
        blocks.append(block)
        if tag == "itch":
            metadata_entries.extend(extract_header_metadata(data, block))
        elif tag == "item":
            parsed_item = inspect_item_block(data, block)
            if parsed_item.boundary is not None:
                boundaries.append(parsed_item.boundary)
            metadata_entries.extend(parsed_item.metadata_entries)
            if parsed_item.preserved_payload is not None:
                preserved_payloads.append(parsed_item.preserved_payload)
            gates.extend(parsed_item.gates)
        else:
            preserved_payloads.append(
                ItcPreservedPayloadPlan(
                    payload_kind="unknown_block",
                    block_label=block.label,
                    offset=block.payload_offset,
                    length=block.payload_size,
                    payload=data[block.payload_offset : block.payload_offset + block.payload_size],
                    evidence_ids=(ITC_UNKNOWN_BLOCK_SOURCE,),
                )
            )
        offset = block_end
        block_index += 1
    return (
        header,
        tuple(blocks),
        tuple(boundaries),
        tuple(metadata_entries),
        tuple(preserved_payloads),
        tuple(gates),
    )


def make_block(block_index: int, tag: str, offset: int, block_size: int) -> ItcBlockPlan:
    if tag == "itch":
        return ItcBlockPlan(
            block_index,
            tag,
            "itch",
            "route_header_metadata",
            offset,
            block_size,
            offset + ITC_BLOCK_HEADER_SIZE,
            block_size - ITC_BLOCK_HEADER_SIZE,
            (ITC_MAIN_TABLE_SOURCE, ITC_HEADER_PROCESS_SOURCE),
        )
    if tag == "item":
        return ItcBlockPlan(
            block_index,
            tag,
            "item",
            "route_item_metadata",
            offset,
            block_size,
            offset + ITC_BLOCK_HEADER_SIZE,
            block_size - ITC_BLOCK_HEADER_SIZE,
            (ITC_MAIN_TABLE_SOURCE, ITC_ITEM_PROCESS_SOURCE),
        )
    return ItcBlockPlan(
        block_index,
        tag,
        "unknown",
        "preserve_unknown_block",
        offset,
        block_size,
        offset + ITC_BLOCK_HEADER_SIZE,
        block_size - ITC_BLOCK_HEADER_SIZE,
        (ITC_UNKNOWN_BLOCK_SOURCE,),
    )


def extract_header_metadata(data: bytes, block: ItcBlockPlan) -> tuple[ItcMetadataEntryPlan, ...]:
    value_offset = block.payload_offset + ITC_HEADER_DATA_TYPE_OFFSET
    if value_offset + 4 > block.payload_offset + block.payload_size:
        return ()
    raw_value = data[value_offset : value_offset + 4]
    value = "Artwork" if raw_value == b"artw" else decode_tag(raw_value)
    return (
        ItcMetadataEntryPlan(
            tag_id="0x10",
            name="DataType",
            role="data_type",
            value=value,
            raw_value_hex=raw_value.hex(),
            block_label=block.label,
            value_offset=value_offset,
            value_size=4,
            evidence_ids=(ITC_HEADER_TABLE_SOURCE, ITC_HEADER_PROCESS_SOURCE),
        ),
    )


def inspect_item_block(data: bytes, block: ItcBlockPlan) -> _ParsedItem:
    if block.size <= 12:
        return _ParsedItem(
            None,
            (),
            None,
            (
                ItcEmissionGate(
                    "invalid_item_block_size",
                    "ProcessITC requires item block size to be greater than 12.",
                    True,
                    (ITC_ITEM_PROCESS_SOURCE,),
                ),
            ),
        )
    item_header_length = read_u32be(data, block.payload_offset)
    if item_header_length < ITC_ITEM_MIN_HEADER_SIZE or item_header_length > block.size:
        return _ParsedItem(
            None,
            (),
            None,
            (
                ItcEmissionGate(
                    "invalid_item_header_length",
                    "ProcessITC requires item header length at least 0xd0 "
                    "and no larger than the block.",
                    True,
                    (ITC_ITEM_PROCESS_SOURCE,),
                ),
            ),
        )
    remaining_header_size = item_header_length - 12
    cursor = block.payload_offset + 4
    while remaining_header_size >= 4:
        group = data[cursor : cursor + 4]
        cursor += 4
        remaining_header_size -= 4
        if group == b"\x00\x00\x00\x00":
            break
    if remaining_header_size < 4:
        return _ParsedItem(
            None,
            (),
            None,
            (
                ItcEmissionGate(
                    "missing_item_terminator",
                    "ProcessITC requires space remaining after the "
                    "null-terminated item header prefix.",
                    True,
                    (ITC_ITEM_PROCESS_SOURCE,),
                ),
            ),
        )
    metadata_offset = cursor
    metadata_size = remaining_header_size
    metadata_end = metadata_offset + metadata_size
    metadata = data[metadata_offset:metadata_end]
    marker = metadata[
        ITC_ITEM_DATA_MARKER_OFFSET : ITC_ITEM_DATA_MARKER_OFFSET + ITC_ITEM_DATA_MARKER_SIZE
    ]
    if metadata_size < 0xB4 or marker != b"data":
        return _ParsedItem(
            None,
            (),
            None,
            (
                ItcEmissionGate(
                    "item_data_boundary_missing",
                    "ProcessITC requires a data marker at item metadata offset 0xb0.",
                    True,
                    (ITC_ITEM_PROCESS_SOURCE,),
                ),
            ),
        )
    image_payload_offset = block.offset + item_header_length
    image_payload_size = block.size - item_header_length
    boundary = ItcItemBoundaryPlan(
        block_label=block.label,
        item_header_length=item_header_length,
        metadata_offset=metadata_offset,
        metadata_size=metadata_size,
        image_payload_offset=image_payload_offset,
        image_payload_size=image_payload_size,
        evidence_ids=(ITC_ITEM_PROCESS_SOURCE, ITC_IMAGE_DATA_SOURCE),
    )
    preserved_payload = None
    if image_payload_size > 0:
        preserved_payload = ItcPreservedPayloadPlan(
            payload_kind="image_data",
            block_label=block.label,
            offset=image_payload_offset,
            length=image_payload_size,
            payload=data[image_payload_offset : image_payload_offset + image_payload_size],
            evidence_ids=(ITC_MAIN_TABLE_SOURCE, ITC_IMAGE_DATA_SOURCE),
        )
    return _ParsedItem(
        boundary,
        extract_item_metadata(metadata, metadata_offset, block.label),
        preserved_payload,
        (),
    )


def extract_item_metadata(
    metadata: bytes,
    metadata_offset: int,
    block_label: str,
) -> tuple[ItcMetadataEntryPlan, ...]:
    entries: list[ItcMetadataEntryPlan] = []
    entries.append(
        ItcMetadataEntryPlan(
            tag_id="0",
            name="LibraryID",
            role="library_id",
            value=metadata[0:8].hex().upper(),
            raw_value_hex=metadata[0:8].hex(),
            block_label=block_label,
            value_offset=metadata_offset,
            value_size=8,
            evidence_ids=(ITC_ITEM_TABLE_SOURCE, ITC_ITEM_PROCESS_SOURCE),
        )
    )
    entries.append(
        ItcMetadataEntryPlan(
            tag_id="2",
            name="TrackID",
            role="track_id",
            value=metadata[8:16].hex().upper(),
            raw_value_hex=metadata[8:16].hex(),
            block_label=block_label,
            value_offset=metadata_offset + 8,
            value_size=8,
            evidence_ids=(ITC_ITEM_TABLE_SOURCE, ITC_ITEM_PROCESS_SOURCE),
        )
    )
    data_location_raw = metadata[16:20]
    entries.append(
        ItcMetadataEntryPlan(
            tag_id="4",
            name="DataLocation",
            role="data_location",
            value=print_data_location(data_location_raw),
            raw_value_hex=data_location_raw.hex(),
            block_label=block_label,
            value_offset=metadata_offset + 16,
            value_size=4,
            evidence_ids=(ITC_ITEM_TABLE_SOURCE, ITC_ITEM_PROCESS_SOURCE),
        )
    )
    image_type_raw = metadata[20:24]
    entries.append(
        ItcMetadataEntryPlan(
            tag_id="5",
            name="ImageType",
            role="image_type",
            value=print_image_type(image_type_raw),
            raw_value_hex=image_type_raw.hex(),
            block_label=block_label,
            value_offset=metadata_offset + 20,
            value_size=4,
            evidence_ids=(ITC_ITEM_TABLE_SOURCE, ITC_ITEM_PROCESS_SOURCE),
        )
    )
    entries.append(
        ItcMetadataEntryPlan(
            tag_id="7",
            name="ImageWidth",
            role="image_dimensions",
            value=read_u32be(metadata, 28),
            raw_value_hex=metadata[28:32].hex(),
            block_label=block_label,
            value_offset=metadata_offset + 28,
            value_size=4,
            evidence_ids=(ITC_ITEM_TABLE_SOURCE, ITC_ITEM_PROCESS_SOURCE),
        )
    )
    entries.append(
        ItcMetadataEntryPlan(
            tag_id="8",
            name="ImageHeight",
            role="image_dimensions",
            value=read_u32be(metadata, 32),
            raw_value_hex=metadata[32:36].hex(),
            block_label=block_label,
            value_offset=metadata_offset + 32,
            value_size=4,
            evidence_ids=(ITC_ITEM_TABLE_SOURCE, ITC_ITEM_PROCESS_SOURCE),
        )
    )
    return tuple(entries)


def route_rewrite_requests(
    metadata_entries: tuple[ItcMetadataEntryPlan, ...],
    rewrite_requests: tuple[ItcMetadataRewriteRequest, ...],
) -> tuple[ItcMetadataRoute, ...]:
    existing_by_name = {entry.name: entry.value for entry in metadata_entries}
    routes: list[ItcMetadataRoute] = []
    for request in rewrite_requests:
        action: ItcRouteAction = "delete_metadata" if request.value is None else "upsert_metadata"
        routes.append(
            ItcMetadataRoute(
                action=action,
                tag_name=request.tag_name,
                requested_value=request.value,
                existing_value=existing_by_name.get(request.tag_name),
                evidence_ids=(ITC_MAIN_TABLE_SOURCE, ITC_READ_ONLY_SOURCE),
            )
        )
    return tuple(routes)


def rewrite_gates(routes: tuple[ItcMetadataRoute, ...]) -> tuple[ItcEmissionGate, ...]:
    gates = [
        ItcEmissionGate(
            "metadata_rewrite_unsupported",
            "ITC.pm supplies read-side tables but no package-local metadata writer.",
            True,
            (ITC_READ_ONLY_SOURCE, ITC_MAIN_TABLE_SOURCE),
        )
    ]
    if any(route.tag_name == "ImageData" for route in routes):
        gates.append(
            ItcEmissionGate(
                "image_payload_rewrite_unsupported",
                "Embedded image data is extracted as a binary payload; "
                "this planner only preserves it.",
                True,
                (ITC_IMAGE_DATA_SOURCE,),
            )
        )
    return tuple(gates)


def non_mutating_gates() -> tuple[ItcEmissionGate, ...]:
    return (
        ItcEmissionGate(
            "planner_is_non_mutating",
            "This transaction planner reports source-backed actions without mutating bytes.",
            True,
            (ITC_READ_ONLY_SOURCE,),
        ),
        ItcEmissionGate(
            "full_itc_writer_not_implemented",
            "A full ITC block rewriter is outside this read-side modernization slice.",
            True,
            (ITC_READ_ONLY_SOURCE,),
        ),
    )


def itc_table_entries() -> tuple[ItcTableEntryPlan, ...]:
    return (
        ItcTableEntryPlan("main", "itch", "ITC Header", None, (ITC_MAIN_TABLE_SOURCE,)),
        ItcTableEntryPlan("main", "item", "ITC Item", None, (ITC_MAIN_TABLE_SOURCE,)),
        ItcTableEntryPlan("main", "data", "ImageData", None, (ITC_MAIN_TABLE_SOURCE,)),
        ItcTableEntryPlan("header", "0x10", "DataType", "data_type", (ITC_HEADER_TABLE_SOURCE,)),
        ItcTableEntryPlan("item", "0", "LibraryID", "library_id", (ITC_ITEM_TABLE_SOURCE,)),
        ItcTableEntryPlan("item", "2", "TrackID", "track_id", (ITC_ITEM_TABLE_SOURCE,)),
        ItcTableEntryPlan("item", "4", "DataLocation", "data_location", (ITC_ITEM_TABLE_SOURCE,)),
        ItcTableEntryPlan("item", "5", "ImageType", "image_type", (ITC_ITEM_TABLE_SOURCE,)),
        ItcTableEntryPlan("item", "7", "ImageWidth", "image_dimensions", (ITC_ITEM_TABLE_SOURCE,)),
        ItcTableEntryPlan("item", "8", "ImageHeight", "image_dimensions", (ITC_ITEM_TABLE_SOURCE,)),
    )


def default_responsibilities() -> tuple[ItcResponsibility, ...]:
    return (
        ItcResponsibility(
            1,
            "signature_header_validation",
            "Validate that the first block is itch and that size ranges match ProcessITC.",
            (ITC_BLOCK_VALIDATION_SOURCE,),
        ),
        ItcResponsibility(
            2,
            "block_enumeration",
            "Enumerate big-endian ITC blocks until clean EOF or a structural blocker.",
            (ITC_BLOCK_VALIDATION_SOURCE,),
        ),
        ItcResponsibility(
            3,
            "header_metadata_routing",
            "Route itch payloads to the Header table and DataType tag.",
            (ITC_HEADER_TABLE_SOURCE, ITC_HEADER_PROCESS_SOURCE),
        ),
        ItcResponsibility(
            4,
            "item_metadata_routing",
            "Route valid item metadata payloads to the Item table fields.",
            (ITC_ITEM_TABLE_SOURCE, ITC_ITEM_PROCESS_SOURCE),
        ),
        ItcResponsibility(
            5,
            "image_payload_preservation",
            "Preserve bytes after a valid item header as embedded ImageData.",
            (ITC_MAIN_TABLE_SOURCE, ITC_IMAGE_DATA_SOURCE),
        ),
        ItcResponsibility(
            6,
            "unknown_block_preservation",
            "Preserve unknown block payloads after size validation.",
            (ITC_UNKNOWN_BLOCK_SOURCE,),
        ),
        ItcResponsibility(
            7,
            "malformed_truncation_blockers",
            "Block emission on malformed block, item, and payload boundaries.",
            (ITC_BLOCK_VALIDATION_SOURCE, ITC_ITEM_PROCESS_SOURCE),
        ),
        ItcResponsibility(
            8,
            "rewrite_blockers",
            "Represent requested writes but do not claim unsupported ITC mutation.",
            (ITC_READ_ONLY_SOURCE,),
        ),
        ItcResponsibility(
            9,
            "output_emission_gate",
            "Keep output emission gated until a full ITC writer exists.",
            (ITC_READ_ONLY_SOURCE,),
        ),
    )


def first_block_invalid_reason(tag: str, size: int) -> ItcEmissionGateCode | None:
    if tag != "itch":
        return "unsupported_itc_signature"
    if size < ITC_INITIAL_ITCH_MIN_SIZE or size >= ITC_INITIAL_ITCH_MAX_SIZE:
        return "invalid_initial_itch_size"
    return None


def first_block_gate(code: ItcEmissionGateCode) -> ItcEmissionGate:
    if code == "unsupported_itc_signature":
        return ItcEmissionGate(
            code,
            "ProcessITC requires the first block tag to be itch.",
            True,
            (ITC_BLOCK_VALIDATION_SOURCE,),
        )
    return ItcEmissionGate(
        code,
        "ProcessITC requires the first itch size to be at least 0x1c and below 0x10000.",
        True,
        (ITC_BLOCK_VALIDATION_SOURCE,),
    )


def print_data_location(raw_value: bytes) -> str:
    if raw_value == b"down":
        return "Downloaded Separately"
    if raw_value == b"locl":
        return "Local Music File"
    return decode_tag(raw_value)


def print_image_type(raw_value: bytes) -> str:
    if raw_value == b"PNGf":
        return "PNG"
    if raw_value == b"\x00\x00\x00\x0d":
        return "JPEG"
    return raw_value.hex()


def read_u32be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def decode_tag(raw_value: bytes) -> str:
    return raw_value.decode("latin1")


def unique_evidence_ids(references: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for reference in references:
        if reference not in seen:
            seen.add(reference)
            unique.append(reference)
    return tuple(unique)


def unique_gates(gates: tuple[ItcEmissionGate, ...]) -> tuple[ItcEmissionGate, ...]:
    unique: list[ItcEmissionGate] = []
    seen: set[ItcEmissionGateCode] = set()
    for gate in gates:
        if gate.code not in seen:
            seen.add(gate.code)
            unique.append(gate)
    return tuple(unique)
