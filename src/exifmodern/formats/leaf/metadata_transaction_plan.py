"""Source-grounded, non-mutating Leaf MOS metadata transaction plans.

ExifTool's Leaf module walks the Leaf-specific PKTS directory stored by MOS
files in EXIF tag 0x8606. The planner mirrors those read boundaries: 52-byte
PKTS headers, observed table routes, recursive Leaf profile directories,
opaque ICC/profile/preview payload preservation, dynamic unknown tag handling,
and explicit gates for malformed input or requested rewrites.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject, JsonValue

LEAF_EXIF_TAG_ID = 0x8606
LEAF_PKTS_HEADER_SIZE = 52
LEAF_PKTS_SIGNATURE = b"PKTS"
LEAF_UNKNOWN_DIRECTORY_PREFIX = b"PKTS\0\0\0\x01"
LEAF_PM_SOURCE_PATH = "lib/Image/ExifTool/Leaf.pm"

type LeafPlanStatus = Literal["planned", "unsupported"]
type LeafDirectoryTable = Literal[
    "Main",
    "CameraProfile",
    "CaptureProfile",
    "ImageProfile",
    "ShootSetup",
    "CaptureSetup",
    "Neutrals",
    "Selection",
    "ToneCurve",
    "Sharpness",
    "ColorSetup",
    "SaveSetup",
    "CameraSetup",
    "LookHeader",
    "Unknown",
]
type LeafTargetTable = LeafDirectoryTable | Literal["ICC_Profile"]
type LeafGroup2 = Literal["Camera", "Image", "Preview", "Other", "Unknown", "Profile"]
type LeafValueFormat = Literal["int16u", "int8u"]
type LeafRecordRole = Literal[
    "scalar_metadata",
    "binary_metadata",
    "icc_profile_payload",
    "jpeg_preview_payload",
    "nested_leaf_directory",
    "unknown_tag",
    "unknown_directory",
]
type LeafActionKind = Literal[
    "validate_leaf_pkts_directory",
    "enumerate_observed_leaf_tag",
    "route_nested_leaf_directory",
    "preserve_icc_profile_payload",
    "preserve_jpeg_preview_payload",
    "preserve_unknown_tag",
    "preserve_unknown_directory",
    "preserve_unparsed_leaf_tail",
    "block_requested_rewrite",
    "no_metadata_mutation",
]
type LeafEmissionGateCode = Literal[
    "bad_format_leaf_data",
    "truncated_leaf_data",
    "leaf_payload_rewrite_required",
    "leaf_directory_delete_required",
    "leaf_preview_rewrite_required",
    "leaf_icc_rewrite_required",
    "planner_is_non_mutating",
    "full_leaf_writer_not_implemented",
]
type LeafResponsibilityConcern = Literal[
    "exif_tag_0x8606_leaf_pkts_directory",
    "main_table_observed_tags",
    "nested_profile_directory_routing",
    "icc_profile_payload_boundaries",
    "jpeg_preview_payload_boundaries",
    "unknown_tag_preservation",
    "malformed_truncation_blockers",
    "unsupported_rewrite_gates",
]

LEAF_MAIN_TABLE_SOURCE = "leaf.main.table"
LEAF_CAMERA_PROFILE_SOURCE = "leaf.camera.profile"
LEAF_CAPTURE_PROFILE_SOURCE = "leaf.capture.profile"
LEAF_IMAGE_PROFILE_SOURCE = "leaf.image.profile"
LEAF_SHOOT_SETUP_SOURCE = "leaf.shoot.setup"
LEAF_CAPTURE_SETUP_SOURCE = "leaf.capture.setup"
LEAF_SETUP_TABLES_SOURCE = "leaf.setup.tables"
LEAF_UNKNOWN_SOURCE = "leaf.unknown"
LEAF_SUBIFD_SOURCE = "leaf.subifd"
LEAF_NAME_PREP_SOURCE = "leaf.name.prep"
LEAF_PROCESS_SOURCE = "leaf.process"
LEAF_READ_ONLY_SOURCE = "leaf.read.only"

LEAF_TRANSACTION_SOURCES = (
    LEAF_MAIN_TABLE_SOURCE,
    LEAF_CAMERA_PROFILE_SOURCE,
    LEAF_CAPTURE_PROFILE_SOURCE,
    LEAF_IMAGE_PROFILE_SOURCE,
    LEAF_SHOOT_SETUP_SOURCE,
    LEAF_CAPTURE_SETUP_SOURCE,
    LEAF_SETUP_TABLES_SOURCE,
    LEAF_UNKNOWN_SOURCE,
    LEAF_SUBIFD_SOURCE,
    LEAF_NAME_PREP_SOURCE,
    LEAF_PROCESS_SOURCE,
    LEAF_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class LeafMetadataRewriteRequest:
    replacement_leaf_payload: bytes | None = None
    replacement_preview_payload: bytes | None = None
    replacement_icc_profile_payloads: tuple[bytes, ...] = ()
    delete_leaf_directory: bool = False


@dataclass(frozen=True)
class LeafTagDefinition:
    tag_id: str
    name: str
    table: LeafDirectoryTable
    group2: LeafGroup2
    role: LeafRecordRole
    evidence_ids: tuple[str, ...]
    format_name: LeafValueFormat | None = None
    target_table: LeafTargetTable | None = None


@dataclass(frozen=True)
class LeafByteRange:
    start: int
    end: int
    reason: str

    def to_json(self) -> JsonObject:
        return {"end": self.end, "reason": self.reason, "start": self.start}


@dataclass(frozen=True)
class LeafProfileRoutePlan:
    source_table: LeafDirectoryTable
    tag_id: str
    tag_name: str
    target_table: LeafTargetTable
    group2: LeafGroup2
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "group2": self.group2,
            "source_table": self.source_table,
            "tag_id": self.tag_id,
            "tag_name": self.tag_name,
            "target_table": self.target_table,
        }


@dataclass(frozen=True)
class LeafRecordPlan:
    tag_id: str
    tag_name: str
    table: LeafDirectoryTable
    group2: LeafGroup2
    role: LeafRecordRole
    observed: bool
    preserved: bool
    header_range: LeafByteRange
    payload_range: LeafByteRange
    payload: bytes
    parsed_value: JsonValue
    format_name: LeafValueFormat | None
    target_table: LeafTargetTable | None
    nested_directory: LeafDirectoryPlan | None
    evidence_ids: tuple[str, ...]

    @property
    def payload_length(self) -> int:
        return self.payload_range.end - self.payload_range.start

    def to_json(self) -> JsonObject:
        nested = self.nested_directory.to_json() if self.nested_directory is not None else None
        return {
            "format_name": self.format_name,
            "group2": self.group2,
            "header_range": self.header_range.to_json(),
            "nested_directory": nested,
            "observed": self.observed,
            "parsed_value": self.parsed_value,
            "payload_length": self.payload_length,
            "payload_range": self.payload_range.to_json(),
            "payload_sample_hex": self.payload[:32].hex(),
            "preserved": self.preserved,
            "role": self.role,
            "table": self.table,
            "tag_id": self.tag_id,
            "tag_name": self.tag_name,
            "target_table": self.target_table,
        }


@dataclass(frozen=True)
class LeafDirectoryPlan:
    table: LeafDirectoryTable
    group2: LeafGroup2
    dir_name: str
    start: int
    end: int
    records: tuple[LeafRecordPlan, ...]
    trailing_unparsed_range: LeafByteRange | None
    reason: LeafEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def was_parsed(self) -> bool:
        return self.reason is None

    def records_by_tag_id(self) -> dict[str, LeafRecordPlan]:
        return {record.tag_id: record for record in self.records}

    def to_json(self) -> JsonObject:
        trailing = (
            self.trailing_unparsed_range.to_json()
            if self.trailing_unparsed_range is not None
            else None
        )
        return {
            "dir_name": self.dir_name,
            "end": self.end,
            "group2": self.group2,
            "reason": self.reason,
            "records": json_array(record.to_json() for record in self.records),
            "start": self.start,
            "table": self.table,
            "trailing_unparsed_range": trailing,
            "was_parsed": self.was_parsed,
        }


@dataclass(frozen=True)
class LeafPayloadBoundaryPlan:
    icc_profile_ranges: tuple[LeafByteRange, ...]
    jpeg_preview_ranges: tuple[LeafByteRange, ...]
    profile_directory_ranges: tuple[LeafByteRange, ...]
    unknown_ranges: tuple[LeafByteRange, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "icc_profile_ranges": json_array(item.to_json() for item in self.icc_profile_ranges),
            "jpeg_preview_ranges": json_array(item.to_json() for item in self.jpeg_preview_ranges),
            "profile_directory_ranges": json_array(
                item.to_json() for item in self.profile_directory_ranges
            ),
            "unknown_ranges": json_array(item.to_json() for item in self.unknown_ranges),
        }


@dataclass(frozen=True)
class LeafResponsibilityPlan:
    concern: LeafResponsibilityConcern
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LeafActionPlan:
    kind: LeafActionKind
    byte_range_start: int | None
    byte_range_end: int | None
    input_payload_length: int | None
    planned_payload_length: int | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range_end": self.byte_range_end,
            "byte_range_start": self.byte_range_start,
            "input_payload_length": self.input_payload_length,
            "kind": self.kind,
            "planned_payload_length": self.planned_payload_length,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LeafOutputEmissionGate:
    code: LeafEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LeafMetadataTransactionPlan:
    status: LeafPlanStatus
    exif_tag_id: int
    root_directory: LeafDirectoryPlan
    payload_boundaries: LeafPayloadBoundaryPlan
    profile_routes: tuple[LeafProfileRoutePlan, ...]
    responsibilities: tuple[LeafResponsibilityPlan, ...]
    actions: tuple[LeafActionPlan, ...]
    output_emission_gates: tuple[LeafOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def all_records(self) -> tuple[LeafRecordPlan, ...]:
        return flatten_records(self.root_directory)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Leaf metadata transaction output is gated: {gate_codes}")
        return self.original_bytes

    def to_json(self) -> JsonObject:
        return {
            "actions": json_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "exif_tag_id": self.exif_tag_id,
            "output_emission_gates": json_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "payload_boundaries": self.payload_boundaries.to_json(),
            "profile_routes": json_array(route.to_json() for route in self.profile_routes),
            "responsibilities": json_array(item.to_json() for item in self.responsibilities),
            "root_directory": self.root_directory.to_json(),
            "status": self.status,
        }


@dataclass(frozen=True)
class LeafParseResult:
    directory: LeafDirectoryPlan
    gates: tuple[LeafOutputEmissionGate, ...]


def build_leaf_metadata_transaction_plan(
    leaf_payload: bytes,
    rewrite_request: LeafMetadataRewriteRequest | None = None,
    *,
    allow_output_emission: bool = False,
) -> LeafMetadataTransactionPlan:
    request = rewrite_request if rewrite_request is not None else LeafMetadataRewriteRequest()
    parse = parse_leaf_directory(leaf_payload, 0, len(leaf_payload), "Main")
    boundaries = build_payload_boundary_plan(parse.directory)
    profile_routes = build_profile_routes(parse.directory)
    responsibilities = build_responsibilities()
    gates = [*parse.gates, *rewrite_gates(request)]
    if not allow_output_emission:
        gates.extend(non_mutating_gates())
    actions = build_actions(leaf_payload, parse.directory, request)
    status: LeafPlanStatus = "unsupported" if any_validation_gate(tuple(gates)) else "planned"
    sources = unique_sources(
        (
            *LEAF_TRANSACTION_SOURCES,
            *parse.directory.evidence_ids,
            *boundaries.evidence_ids,
            *(source for route in profile_routes for source in route.evidence_ids),
            *(source for item in responsibilities for source in item.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return LeafMetadataTransactionPlan(
        status=status,
        exif_tag_id=LEAF_EXIF_TAG_ID,
        root_directory=parse.directory,
        payload_boundaries=boundaries,
        profile_routes=profile_routes,
        responsibilities=responsibilities,
        actions=actions,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
        original_bytes=leaf_payload,
    )


def parse_leaf_directory(
    data: bytes,
    start: int,
    end: int,
    table: LeafDirectoryTable,
) -> LeafParseResult:
    records: list[LeafRecordPlan] = []
    gates: list[LeafOutputEmissionGate] = []
    pos = start
    reason: LeafEmissionGateCode | None = None
    trailing: LeafByteRange | None = None
    while True:
        if pos + LEAF_PKTS_HEADER_SIZE > end:
            if not records:
                reason = "bad_format_leaf_data"
                gates.append(format_gate(reason, table))
            elif pos < end:
                trailing = LeafByteRange(
                    start=pos,
                    end=end,
                    reason="Preserve bytes after the last complete Leaf PKTS record.",
                )
            break
        header = data[pos : pos + LEAF_PKTS_HEADER_SIZE]
        if not header.startswith(LEAF_PKTS_SIGNATURE):
            if not records:
                reason = "bad_format_leaf_data"
                gates.append(format_gate(reason, table))
            else:
                trailing = LeafByteRange(
                    start=pos,
                    end=end,
                    reason="Preserve bytes after ProcessLeaf stops at a non-PKTS marker.",
                )
            break
        payload_size = int.from_bytes(header[48:52], "big")
        payload_start = pos + LEAF_PKTS_HEADER_SIZE
        payload_end = payload_start + payload_size
        tag_id = read_leaf_tag_id(header)
        if not tag_id or payload_end > end:
            reason = "truncated_leaf_data" if payload_end > end else "bad_format_leaf_data"
            gates.append(format_gate(reason, table))
            break
        record_parse = build_record(data, pos, payload_start, payload_end, tag_id, table)
        records.append(record_parse.record)
        gates.extend(record_parse.gates)
        pos = payload_end
    directory = LeafDirectoryPlan(
        table=table,
        group2=TABLE_GROUPS[table],
        dir_name="Leaf" if table == "Main" else "Leaf PKTS",
        start=start,
        end=end,
        records=tuple(records),
        trailing_unparsed_range=trailing,
        reason=reason,
        evidence_ids=(LEAF_PROCESS_SOURCE, table_source(table)),
    )
    return LeafParseResult(directory=directory, gates=tuple(gates))


@dataclass(frozen=True)
class LeafRecordParse:
    record: LeafRecordPlan
    gates: tuple[LeafOutputEmissionGate, ...]


def build_record(
    data: bytes,
    header_start: int,
    payload_start: int,
    payload_end: int,
    tag_id: str,
    table: LeafDirectoryTable,
) -> LeafRecordParse:
    payload = data[payload_start:payload_end]
    definition = tag_definition(table, tag_id, payload)
    nested_directory: LeafDirectoryPlan | None = None
    gates: tuple[LeafOutputEmissionGate, ...] = ()
    if definition.target_table is not None and definition.target_table != "ICC_Profile":
        parse = parse_leaf_directory(data, payload_start, payload_end, definition.target_table)
        nested_directory = parse.directory
        gates = parse.gates
    record = LeafRecordPlan(
        tag_id=tag_id,
        tag_name=definition.name,
        table=table,
        group2=definition.group2,
        role=definition.role,
        observed=definition.role not in {"unknown_tag", "unknown_directory"},
        preserved=True,
        header_range=LeafByteRange(
            start=header_start,
            end=payload_start,
            reason="Leaf PKTS header read by ProcessLeaf.",
        ),
        payload_range=LeafByteRange(
            start=payload_start,
            end=payload_end,
            reason=f"Leaf PKTS payload for {definition.name}.",
        ),
        payload=payload,
        parsed_value=parse_value(definition, payload),
        format_name=definition.format_name,
        target_table=definition.target_table,
        nested_directory=nested_directory,
        evidence_ids=definition.evidence_ids,
    )
    return LeafRecordParse(record=record, gates=gates)


def tag_definition(
    table: LeafDirectoryTable,
    tag_id: str,
    payload: bytes,
) -> LeafTagDefinition:
    definitions = LEAF_TAG_DEFINITIONS.get(table, {})
    definition = definitions.get(tag_id)
    if definition is not None:
        return definition
    role: LeafRecordRole = (
        "unknown_directory" if payload.startswith(LEAF_UNKNOWN_DIRECTORY_PREFIX) else "unknown_tag"
    )
    target_table: LeafTargetTable | None = "Unknown" if role == "unknown_directory" else None
    return LeafTagDefinition(
        tag_id=tag_id,
        name=leaf_name_from_tag_id(tag_id),
        table=table,
        group2="Unknown" if role == "unknown_directory" else TABLE_GROUPS[table],
        role=role,
        target_table=target_table,
        evidence_ids=(LEAF_PROCESS_SOURCE, LEAF_UNKNOWN_SOURCE),
    )


def parse_value(definition: LeafTagDefinition, payload: bytes) -> JsonValue:
    if definition.role in {
        "binary_metadata",
        "icc_profile_payload",
        "jpeg_preview_payload",
        "nested_leaf_directory",
        "unknown_directory",
    }:
        return None
    if definition.format_name == "int16u":
        values = [
            int.from_bytes(payload[index : index + 2], "big")
            for index in range(0, len(payload) - 1, 2)
        ]
        return values[0] if len(values) == 1 else json_array(values)
    if definition.format_name == "int8u":
        values = [byte for byte in payload]
        return values[0] if len(values) == 1 else json_array(values)
    value = payload.replace(b"\n", b" ").rstrip(b"\0").decode("latin-1")
    if definition.tag_id in {"back_serial_number", "CaptProf_serial_number"}:
        return value.split(" ", 1)[0]
    return value


def build_payload_boundary_plan(directory: LeafDirectoryPlan) -> LeafPayloadBoundaryPlan:
    records = flatten_records(directory)
    icc_ranges = tuple(
        record.payload_range for record in records if record.role == "icc_profile_payload"
    )
    preview_ranges = tuple(
        record.payload_range for record in records if record.role == "jpeg_preview_payload"
    )
    profile_ranges = tuple(
        record.payload_range for record in records if record.role == "nested_leaf_directory"
    )
    unknown_ranges = tuple(
        record.payload_range
        for record in records
        if record.role in {"unknown_tag", "unknown_directory"}
    )
    return LeafPayloadBoundaryPlan(
        icc_profile_ranges=icc_ranges,
        jpeg_preview_ranges=preview_ranges,
        profile_directory_ranges=profile_ranges,
        unknown_ranges=unknown_ranges,
        evidence_ids=(LEAF_MAIN_TABLE_SOURCE, LEAF_PROCESS_SOURCE, LEAF_UNKNOWN_SOURCE),
    )


def build_profile_routes(directory: LeafDirectoryPlan) -> tuple[LeafProfileRoutePlan, ...]:
    routes: list[LeafProfileRoutePlan] = []
    for record in flatten_records(directory):
        if record.target_table is None:
            continue
        routes.append(
            LeafProfileRoutePlan(
                source_table=record.table,
                tag_id=record.tag_id,
                tag_name=record.tag_name,
                target_table=record.target_table,
                group2=record.group2,
                evidence_ids=record.evidence_ids,
            )
        )
    return tuple(routes)


def build_actions(
    leaf_payload: bytes,
    directory: LeafDirectoryPlan,
    request: LeafMetadataRewriteRequest,
) -> tuple[LeafActionPlan, ...]:
    actions: list[LeafActionPlan] = [
        LeafActionPlan(
            kind="validate_leaf_pkts_directory",
            byte_range_start=directory.start,
            byte_range_end=directory.end,
            input_payload_length=directory.end - directory.start,
            planned_payload_length=directory.end - directory.start,
            reason="Validate and preserve the Leaf EXIF tag 0x8606 PKTS payload.",
            evidence_ids=(LEAF_MAIN_TABLE_SOURCE, LEAF_PROCESS_SOURCE),
        )
    ]
    for record in flatten_records(directory):
        actions.append(record_action(record))
    for item in trailing_ranges(directory):
        actions.append(
            LeafActionPlan(
                kind="preserve_unparsed_leaf_tail",
                byte_range_start=item.start,
                byte_range_end=item.end,
                input_payload_length=item.end - item.start,
                planned_payload_length=item.end - item.start,
                reason=item.reason,
                evidence_ids=(LEAF_PROCESS_SOURCE, LEAF_READ_ONLY_SOURCE),
            )
        )
    if has_rewrite_request(request):
        actions.append(
            LeafActionPlan(
                kind="block_requested_rewrite",
                byte_range_start=0,
                byte_range_end=len(leaf_payload),
                input_payload_length=len(leaf_payload),
                planned_payload_length=None,
                reason="Requested Leaf byte changes are recorded only as blocked work.",
                evidence_ids=(LEAF_READ_ONLY_SOURCE,),
            )
        )
    actions.append(
        LeafActionPlan(
            kind="no_metadata_mutation",
            byte_range_start=0,
            byte_range_end=len(leaf_payload),
            input_payload_length=len(leaf_payload),
            planned_payload_length=len(leaf_payload),
            reason="The Leaf planner preserves source bytes and does not rewrite MOS metadata.",
            evidence_ids=(LEAF_READ_ONLY_SOURCE,),
        )
    )
    return tuple(actions)


def record_action(record: LeafRecordPlan) -> LeafActionPlan:
    kind: LeafActionKind = "enumerate_observed_leaf_tag"
    if record.role == "nested_leaf_directory":
        kind = "route_nested_leaf_directory"
    elif record.role == "icc_profile_payload":
        kind = "preserve_icc_profile_payload"
    elif record.role == "jpeg_preview_payload":
        kind = "preserve_jpeg_preview_payload"
    elif record.role == "unknown_directory":
        kind = "preserve_unknown_directory"
    elif record.role == "unknown_tag":
        kind = "preserve_unknown_tag"
    return LeafActionPlan(
        kind=kind,
        byte_range_start=record.payload_range.start,
        byte_range_end=record.payload_range.end,
        input_payload_length=record.payload_length,
        planned_payload_length=record.payload_length,
        reason=f"Preserve Leaf PKTS payload for {record.tag_name}.",
        evidence_ids=record.evidence_ids,
    )


def rewrite_gates(request: LeafMetadataRewriteRequest) -> tuple[LeafOutputEmissionGate, ...]:
    gates: list[LeafOutputEmissionGate] = []
    if request.replacement_leaf_payload is not None:
        gates.append(
            LeafOutputEmissionGate(
                code="leaf_payload_rewrite_required",
                reason="Replacing the Leaf EXIF tag 0x8606 payload requires a MOS writer.",
                evidence_ids=(LEAF_MAIN_TABLE_SOURCE, LEAF_READ_ONLY_SOURCE),
            )
        )
    if request.delete_leaf_directory:
        gates.append(
            LeafOutputEmissionGate(
                code="leaf_directory_delete_required",
                reason="Deleting the Leaf PKTS directory is outside Leaf.pm read behavior.",
                evidence_ids=(LEAF_PROCESS_SOURCE, LEAF_READ_ONLY_SOURCE),
            )
        )
    if request.replacement_preview_payload is not None:
        gates.append(
            LeafOutputEmissionGate(
                code="leaf_preview_rewrite_required",
                reason="JPEG preview replacement is not implemented for Leaf MOS metadata.",
                evidence_ids=(LEAF_MAIN_TABLE_SOURCE, LEAF_READ_ONLY_SOURCE),
            )
        )
    if request.replacement_icc_profile_payloads:
        gates.append(
            LeafOutputEmissionGate(
                code="leaf_icc_rewrite_required",
                reason="ICC profile replacement is not implemented for Leaf MOS metadata.",
                evidence_ids=(LEAF_MAIN_TABLE_SOURCE, LEAF_READ_ONLY_SOURCE),
            )
        )
    return tuple(gates)


def non_mutating_gates() -> tuple[LeafOutputEmissionGate, ...]:
    return (
        LeafOutputEmissionGate(
            code="planner_is_non_mutating",
            reason="Leaf metadata transaction plans require explicit output emission approval.",
            evidence_ids=(LEAF_READ_ONLY_SOURCE,),
        ),
        LeafOutputEmissionGate(
            code="full_leaf_writer_not_implemented",
            reason="This slice ports Leaf.pm read planning only; no MOS writer is emitted.",
            evidence_ids=(LEAF_READ_ONLY_SOURCE,),
        ),
    )


def build_responsibilities() -> tuple[LeafResponsibilityPlan, ...]:
    return (
        LeafResponsibilityPlan(
            concern="exif_tag_0x8606_leaf_pkts_directory",
            reason="Plan the Leaf EXIF tag 0x8606 PKTS directory as a contained payload.",
            evidence_ids=(LEAF_MAIN_TABLE_SOURCE, LEAF_SUBIFD_SOURCE),
        ),
        LeafResponsibilityPlan(
            concern="main_table_observed_tags",
            reason="Route observed Leaf main table tags by their ExifTool names and groups.",
            evidence_ids=(LEAF_MAIN_TABLE_SOURCE,),
        ),
        LeafResponsibilityPlan(
            concern="nested_profile_directory_routing",
            reason="Recurse through camera, capture, image, shoot, and setup PKTS directories.",
            evidence_ids=(
                LEAF_CAMERA_PROFILE_SOURCE,
                LEAF_IMAGE_PROFILE_SOURCE,
                LEAF_SHOOT_SETUP_SOURCE,
                LEAF_CAPTURE_SETUP_SOURCE,
            ),
        ),
        LeafResponsibilityPlan(
            concern="icc_profile_payload_boundaries",
            reason="Preserve ICC and RGB profile payloads without decoding in this planner.",
            evidence_ids=(LEAF_MAIN_TABLE_SOURCE,),
        ),
        LeafResponsibilityPlan(
            concern="jpeg_preview_payload_boundaries",
            reason="Preserve JPEG preview payload bytes and group them as Preview metadata.",
            evidence_ids=(LEAF_MAIN_TABLE_SOURCE,),
        ),
        LeafResponsibilityPlan(
            concern="unknown_tag_preservation",
            reason="Keep unknown Leaf PKTS payloads and recurse unknown PKTS directories.",
            evidence_ids=(LEAF_PROCESS_SOURCE, LEAF_UNKNOWN_SOURCE),
        ),
        LeafResponsibilityPlan(
            concern="malformed_truncation_blockers",
            reason="Surface ProcessLeaf bad format and truncated data warnings as gates.",
            evidence_ids=(LEAF_PROCESS_SOURCE,),
        ),
        LeafResponsibilityPlan(
            concern="unsupported_rewrite_gates",
            reason="Block rewrites because Leaf.pm contributes read behavior only.",
            evidence_ids=(LEAF_READ_ONLY_SOURCE,),
        ),
    )


def format_gate(
    code: Literal["bad_format_leaf_data", "truncated_leaf_data"],
    table: LeafDirectoryTable,
) -> LeafOutputEmissionGate:
    reason = (
        f"Leaf {table} PKTS directory is truncated."
        if code == "truncated_leaf_data"
        else f"Leaf {table} PKTS directory has bad format."
    )
    return LeafOutputEmissionGate(
        code=code,
        reason=reason,
        evidence_ids=(LEAF_PROCESS_SOURCE, table_source(table)),
    )


def any_validation_gate(gates: tuple[LeafOutputEmissionGate, ...]) -> bool:
    return any(gate.code in {"bad_format_leaf_data", "truncated_leaf_data"} for gate in gates)


def has_rewrite_request(request: LeafMetadataRewriteRequest) -> bool:
    return (
        request.replacement_leaf_payload is not None
        or request.replacement_preview_payload is not None
        or bool(request.replacement_icc_profile_payloads)
        or request.delete_leaf_directory
    )


def flatten_records(directory: LeafDirectoryPlan) -> tuple[LeafRecordPlan, ...]:
    records: list[LeafRecordPlan] = []
    for record in directory.records:
        records.append(record)
        if record.nested_directory is not None:
            records.extend(flatten_records(record.nested_directory))
    return tuple(records)


def trailing_ranges(directory: LeafDirectoryPlan) -> tuple[LeafByteRange, ...]:
    ranges: list[LeafByteRange] = []
    if directory.trailing_unparsed_range is not None:
        ranges.append(directory.trailing_unparsed_range)
    for record in directory.records:
        if record.nested_directory is not None:
            ranges.extend(trailing_ranges(record.nested_directory))
    return tuple(ranges)


def read_leaf_tag_id(header: bytes) -> str:
    raw_tag = header[8:48].split(b"\0", 1)[0]
    return raw_tag.decode("latin-1")


def leaf_name_from_tag_id(tag_id: str) -> str:
    parts = [part for part in tag_id.split("_") if part]
    if not parts:
        return ""
    return "".join(part[:1].upper() + part[1:] for part in parts)


def table_source(table: LeafDirectoryTable) -> str:
    if table == "Main":
        return LEAF_MAIN_TABLE_SOURCE
    if table == "CameraProfile":
        return LEAF_CAMERA_PROFILE_SOURCE
    if table == "CaptureProfile":
        return LEAF_CAPTURE_PROFILE_SOURCE
    if table == "ImageProfile":
        return LEAF_IMAGE_PROFILE_SOURCE
    if table == "ShootSetup":
        return LEAF_SHOOT_SETUP_SOURCE
    if table == "CaptureSetup":
        return LEAF_CAPTURE_SETUP_SOURCE
    if table == "Unknown":
        return LEAF_UNKNOWN_SOURCE
    return LEAF_SETUP_TABLES_SOURCE


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


def json_array(values: Iterable[JsonValue]) -> JsonArray:
    return [value for value in values]


def unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for reference in references:
        key = reference
        if key in seen:
            continue
        seen.add(key)
        unique.append(reference)
    return tuple(unique)


def unique_gates(
    gates: tuple[LeafOutputEmissionGate, ...],
) -> tuple[LeafOutputEmissionGate, ...]:
    seen: set[LeafEmissionGateCode] = set()
    unique: list[LeafOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


TABLE_GROUPS: dict[LeafDirectoryTable, LeafGroup2] = {
    "Main": "Camera",
    "CameraProfile": "Camera",
    "CaptureProfile": "Image",
    "ImageProfile": "Image",
    "ShootSetup": "Image",
    "CaptureSetup": "Image",
    "Neutrals": "Image",
    "Selection": "Image",
    "ToneCurve": "Image",
    "Sharpness": "Image",
    "ColorSetup": "Image",
    "SaveSetup": "Other",
    "CameraSetup": "Camera",
    "LookHeader": "Other",
    "Unknown": "Unknown",
}


def leaf_tag(
    tag_id: str,
    name: str,
    table: LeafDirectoryTable,
    role: LeafRecordRole,
    evidence_ids: tuple[str, ...],
    *,
    group2: LeafGroup2 | None = None,
    format_name: LeafValueFormat | None = None,
    target_table: LeafTargetTable | None = None,
) -> LeafTagDefinition:
    return LeafTagDefinition(
        tag_id=tag_id,
        name=name,
        table=table,
        group2=TABLE_GROUPS[table] if group2 is None else group2,
        role=role,
        evidence_ids=evidence_ids,
        format_name=format_name,
        target_table=target_table,
    )


LEAF_TAG_DEFINITIONS: dict[LeafDirectoryTable, dict[str, LeafTagDefinition]] = {
    "Main": {
        "icc_camera_profile": leaf_tag(
            "icc_camera_profile",
            "ICC_Profile",
            "Main",
            "icc_profile_payload",
            (LEAF_MAIN_TABLE_SOURCE,),
            group2="Profile",
            target_table="ICC_Profile",
        ),
        "icc_rgb_ws_profile": leaf_tag(
            "icc_rgb_ws_profile",
            "RGB_Profile",
            "Main",
            "icc_profile_payload",
            (LEAF_MAIN_TABLE_SOURCE,),
            group2="Profile",
            target_table="ICC_Profile",
        ),
        "camera_profile": leaf_tag(
            "camera_profile",
            "CameraProfile",
            "Main",
            "nested_leaf_directory",
            (LEAF_MAIN_TABLE_SOURCE, LEAF_CAMERA_PROFILE_SOURCE),
            target_table="CameraProfile",
        ),
        "JPEG_preview_data": leaf_tag(
            "JPEG_preview_data",
            "PreviewImage",
            "Main",
            "jpeg_preview_payload",
            (LEAF_MAIN_TABLE_SOURCE,),
            group2="Preview",
        ),
        "JPEG_preview_info": leaf_tag(
            "JPEG_preview_info",
            "PreviewInfo",
            "Main",
            "scalar_metadata",
            (LEAF_MAIN_TABLE_SOURCE,),
            group2="Preview",
        ),
        "icc_camera_to_tone_space_flow": leaf_tag(
            "icc_camera_to_tone_space_flow",
            "ToneSpaceFlow",
            "Main",
            "scalar_metadata",
            (LEAF_MAIN_TABLE_SOURCE,),
            format_name="int16u",
        ),
        "icc_camera_to_tone_matrix": leaf_tag(
            "icc_camera_to_tone_matrix",
            "ToneMatrix",
            "Main",
            "binary_metadata",
            (LEAF_MAIN_TABLE_SOURCE,),
            format_name="int8u",
        ),
        "PDA_histogram_data": leaf_tag(
            "PDA_histogram_data",
            "PDAHistogram",
            "Main",
            "binary_metadata",
            (LEAF_MAIN_TABLE_SOURCE,),
        ),
        "pattern_ratation_angle": leaf_tag(
            "pattern_ratation_angle",
            "PatternAngle",
            "Main",
            "scalar_metadata",
            (LEAF_MAIN_TABLE_SOURCE,),
            format_name="int16u",
        ),
        "back_serial_number": leaf_tag(
            "back_serial_number",
            "BackSerial",
            "Main",
            "scalar_metadata",
            (LEAF_MAIN_TABLE_SOURCE,),
        ),
        "image_offset": leaf_tag(
            "image_offset",
            "ImageOffset",
            "Main",
            "scalar_metadata",
            (LEAF_MAIN_TABLE_SOURCE,),
            format_name="int16u",
        ),
    },
    "CameraProfile": {
        "CamProf_version": leaf_tag(
            "CamProf_version",
            "CameraProfileVersion",
            "CameraProfile",
            "scalar_metadata",
            (LEAF_CAMERA_PROFILE_SOURCE,),
        ),
        "CamProf_name": leaf_tag(
            "CamProf_name",
            "CameraName",
            "CameraProfile",
            "scalar_metadata",
            (LEAF_CAMERA_PROFILE_SOURCE,),
        ),
        "CamProf_type": leaf_tag(
            "CamProf_type",
            "CameraType",
            "CameraProfile",
            "scalar_metadata",
            (LEAF_CAMERA_PROFILE_SOURCE,),
        ),
        "CamProf_back_type": leaf_tag(
            "CamProf_back_type",
            "CameraBackType",
            "CameraProfile",
            "scalar_metadata",
            (LEAF_CAMERA_PROFILE_SOURCE,),
        ),
        "CamProf_capture_profile": leaf_tag(
            "CamProf_capture_profile",
            "CaptureProfile",
            "CameraProfile",
            "nested_leaf_directory",
            (LEAF_CAMERA_PROFILE_SOURCE, LEAF_CAPTURE_PROFILE_SOURCE),
            target_table="CaptureProfile",
        ),
        "CamProf_image_profile": leaf_tag(
            "CamProf_image_profile",
            "ImageProfile",
            "CameraProfile",
            "nested_leaf_directory",
            (LEAF_CAMERA_PROFILE_SOURCE, LEAF_IMAGE_PROFILE_SOURCE),
            target_table="ImageProfile",
        ),
    },
    "CaptureProfile": {
        "CaptProf_version": leaf_tag(
            "CaptProf_version",
            "Version",
            "CaptureProfile",
            "scalar_metadata",
            (LEAF_CAPTURE_PROFILE_SOURCE, LEAF_NAME_PREP_SOURCE),
        ),
        "CaptProf_name": leaf_tag(
            "CaptProf_name",
            "Name",
            "CaptureProfile",
            "scalar_metadata",
            (LEAF_CAPTURE_PROFILE_SOURCE, LEAF_NAME_PREP_SOURCE),
        ),
        "CaptProf_serial_number": leaf_tag(
            "CaptProf_serial_number",
            "CaptureSerial",
            "CaptureProfile",
            "scalar_metadata",
            (LEAF_CAPTURE_PROFILE_SOURCE,),
        ),
        "CaptProf_xy_offset_info": leaf_tag(
            "CaptProf_xy_offset_info",
            "XYOffsetInfo",
            "CaptureProfile",
            "scalar_metadata",
            (LEAF_CAPTURE_PROFILE_SOURCE,),
        ),
    },
    "ImageProfile": {
        "ImgProf_version": leaf_tag(
            "ImgProf_version",
            "Version",
            "ImageProfile",
            "scalar_metadata",
            (LEAF_IMAGE_PROFILE_SOURCE, LEAF_NAME_PREP_SOURCE),
        ),
        "ImgProf_name": leaf_tag(
            "ImgProf_name",
            "Name",
            "ImageProfile",
            "scalar_metadata",
            (LEAF_IMAGE_PROFILE_SOURCE, LEAF_NAME_PREP_SOURCE),
        ),
        "ImgProf_shoot_setup": leaf_tag(
            "ImgProf_shoot_setup",
            "ShootSetup",
            "ImageProfile",
            "nested_leaf_directory",
            (LEAF_IMAGE_PROFILE_SOURCE, LEAF_SHOOT_SETUP_SOURCE),
            target_table="ShootSetup",
        ),
        "ImgProf_image_status": leaf_tag(
            "ImgProf_image_status",
            "ImageStatus",
            "ImageProfile",
            "scalar_metadata",
            (LEAF_IMAGE_PROFILE_SOURCE,),
        ),
        "ImgProf_rotation_angle": leaf_tag(
            "ImgProf_rotation_angle",
            "RotationAngle",
            "ImageProfile",
            "scalar_metadata",
            (LEAF_IMAGE_PROFILE_SOURCE,),
        ),
    },
    "ShootSetup": {
        "ShootObj_capture_setup": leaf_tag(
            "ShootObj_capture_setup",
            "CaptureSetup",
            "ShootSetup",
            "nested_leaf_directory",
            (LEAF_SHOOT_SETUP_SOURCE, LEAF_CAPTURE_SETUP_SOURCE),
            target_table="CaptureSetup",
        ),
        "ShootObj_color_setup": leaf_tag(
            "ShootObj_color_setup",
            "ColorSetup",
            "ShootSetup",
            "nested_leaf_directory",
            (LEAF_SHOOT_SETUP_SOURCE, LEAF_SETUP_TABLES_SOURCE),
            target_table="ColorSetup",
        ),
        "ShootObj_save_setup": leaf_tag(
            "ShootObj_save_setup",
            "SaveSetup",
            "ShootSetup",
            "nested_leaf_directory",
            (LEAF_SHOOT_SETUP_SOURCE, LEAF_SETUP_TABLES_SOURCE),
            group2="Other",
            target_table="SaveSetup",
        ),
        "ShootObj_camera_setup": leaf_tag(
            "ShootObj_camera_setup",
            "CameraSetup",
            "ShootSetup",
            "nested_leaf_directory",
            (LEAF_SHOOT_SETUP_SOURCE, LEAF_SETUP_TABLES_SOURCE),
            group2="Camera",
            target_table="CameraSetup",
        ),
        "ShootObj_look_header": leaf_tag(
            "ShootObj_look_header",
            "LookHeader",
            "ShootSetup",
            "nested_leaf_directory",
            (LEAF_SHOOT_SETUP_SOURCE, LEAF_SETUP_TABLES_SOURCE),
            group2="Other",
            target_table="LookHeader",
        ),
    },
    "CaptureSetup": {
        "CaptureObj_neutals": leaf_tag(
            "CaptureObj_neutals",
            "Neutals",
            "CaptureSetup",
            "nested_leaf_directory",
            (LEAF_CAPTURE_SETUP_SOURCE, LEAF_SETUP_TABLES_SOURCE),
            target_table="Neutrals",
        ),
        "CaptureObj_selection": leaf_tag(
            "CaptureObj_selection",
            "Selection",
            "CaptureSetup",
            "nested_leaf_directory",
            (LEAF_CAPTURE_SETUP_SOURCE, LEAF_SETUP_TABLES_SOURCE),
            target_table="Selection",
        ),
        "CaptureObj_tone_curve": leaf_tag(
            "CaptureObj_tone_curve",
            "ToneCurve",
            "CaptureSetup",
            "nested_leaf_directory",
            (LEAF_CAPTURE_SETUP_SOURCE, LEAF_SETUP_TABLES_SOURCE),
            target_table="ToneCurve",
        ),
        "CaptureObj_sharpness": leaf_tag(
            "CaptureObj_sharpness",
            "Sharpness",
            "CaptureSetup",
            "nested_leaf_directory",
            (LEAF_CAPTURE_SETUP_SOURCE, LEAF_SETUP_TABLES_SOURCE),
            target_table="Sharpness",
        ),
    },
    "ColorSetup": {
        "ColorObj_has_ICC": leaf_tag(
            "ColorObj_has_ICC",
            "HasICC",
            "ColorSetup",
            "scalar_metadata",
            (LEAF_SETUP_TABLES_SOURCE,),
        ),
        "ColorObj_input_profile": leaf_tag(
            "ColorObj_input_profile",
            "InputProfile",
            "ColorSetup",
            "scalar_metadata",
            (LEAF_SETUP_TABLES_SOURCE,),
        ),
        "ColorObj_output_profile": leaf_tag(
            "ColorObj_output_profile",
            "OutputProfile",
            "ColorSetup",
            "scalar_metadata",
            (LEAF_SETUP_TABLES_SOURCE,),
        ),
    },
    "CameraSetup": {
        "CameraObj_ISO_speed": leaf_tag(
            "CameraObj_ISO_speed",
            "ISOSpeed",
            "CameraSetup",
            "scalar_metadata",
            (LEAF_SETUP_TABLES_SOURCE,),
        ),
        "CameraObj_lens_ID": leaf_tag(
            "CameraObj_lens_ID",
            "LensID",
            "CameraSetup",
            "scalar_metadata",
            (LEAF_SETUP_TABLES_SOURCE,),
        ),
    },
    "SaveSetup": {},
    "LookHeader": {},
    "Neutrals": {},
    "Selection": {},
    "ToneCurve": {},
    "Sharpness": {},
    "Unknown": {},
}


def generated_leaf_tag(
    table: LeafDirectoryTable,
    tag_id: str,
    prefix: str,
    evidence_id: str,
) -> LeafTagDefinition:
    return leaf_tag(
        tag_id,
        generated_leaf_name(tag_id, prefix),
        table,
        "scalar_metadata",
        (evidence_id, LEAF_NAME_PREP_SOURCE),
    )


def generated_leaf_name(tag_id: str, prefix: str) -> str:
    name = leaf_name_from_tag_id(tag_id)
    if name.startswith(prefix):
        name = name.removeprefix(prefix)
    return f"{prefix}{name}" if name in {"Version", "Name", "Type", "BackType"} else name


def register_generated_tags(
    table: LeafDirectoryTable,
    prefix: str,
    evidence_id: str,
    tag_ids: tuple[str, ...],
) -> None:
    definitions = LEAF_TAG_DEFINITIONS[table]
    for tag_id in tag_ids:
        definitions.setdefault(tag_id, generated_leaf_tag(table, tag_id, prefix, evidence_id))


register_generated_tags(
    "CaptureProfile",
    "CaptProf",
    LEAF_CAPTURE_PROFILE_SOURCE,
    (
        "CaptProf_type",
        "CaptProf_back_type",
        "CaptProf_image_offset",
        "CaptProf_luminance_consts",
        "CaptProf_color_matrix",
        "CaptProf_reconstruction_type",
        "CaptProf_image_fields",
        "CaptProf_image_bounds",
        "CaptProf_number_of_planes",
        "CaptProf_raw_data_rotation",
        "CaptProf_color_averages",
        "CaptProf_mosaic_pattern",
        "CaptProf_dark_correction_type",
        "CaptProf_right_dark_rect",
        "CaptProf_left_dark_rect",
        "CaptProf_center_dark_rect",
        "CaptProf_CCD_rect",
        "CaptProf_CCD_valid_rect",
        "CaptProf_CCD_video_rect",
    ),
)
register_generated_tags(
    "ImageProfile",
    "ImgProf",
    LEAF_IMAGE_PROFILE_SOURCE,
    ("ImgProf_type", "ImgProf_back_type"),
)
register_generated_tags(
    "ShootSetup",
    "ShootObj",
    LEAF_SHOOT_SETUP_SOURCE,
    ("ShootObj_version", "ShootObj_name", "ShootObj_type", "ShootObj_back_type"),
)
register_generated_tags(
    "CaptureSetup",
    "CaptureObj",
    LEAF_CAPTURE_SETUP_SOURCE,
    (
        "CaptureObj_version",
        "CaptureObj_name",
        "CaptureObj_type",
        "CaptureObj_back_type",
        "CaptureObj_single_quality",
        "CaptureObj_Multi_quality",
    ),
)
register_generated_tags(
    "Neutrals",
    "NeutObj",
    LEAF_SETUP_TABLES_SOURCE,
    (
        "NeutObj_version",
        "NeutObj_name",
        "NeutObj_type",
        "NeutObj_back_type",
        "NeutObj_neutrals",
        "NeutObj_color_casts",
        "NeutObj_shadow_end_points",
        "NeutObj_highlight_end_points",
    ),
)
register_generated_tags(
    "Selection",
    "SelObj",
    LEAF_SETUP_TABLES_SOURCE,
    (
        "SelObj_version",
        "SelObj_name",
        "SelObj_type",
        "SelObj_back_type",
        "SelObj_rect",
        "SelObj_resolution",
        "SelObj_scale",
        "SelObj_locks",
        "SelObj_orientation",
    ),
)
register_generated_tags(
    "ToneCurve",
    "ToneObj",
    LEAF_SETUP_TABLES_SOURCE,
    (
        "ToneObj_version",
        "ToneObj_name",
        "ToneObj_type",
        "ToneObj_back_type",
        "ToneObj_npts",
        "ToneObj_tones",
        "ToneObj_gamma",
    ),
)
register_generated_tags(
    "Sharpness",
    "SharpObj",
    LEAF_SETUP_TABLES_SOURCE,
    (
        "SharpObj_version",
        "SharpObj_name",
        "SharpObj_type",
        "SharpObj_back_type",
        "SharpObj_sharp_method",
        "SharpObj_data_len",
        "SharpObj_sharp_info",
    ),
)
register_generated_tags(
    "ColorSetup",
    "ColorObj",
    LEAF_SETUP_TABLES_SOURCE,
    (
        "ColorObj_version",
        "ColorObj_name",
        "ColorObj_type",
        "ColorObj_back_type",
        "ColorObj_color_mode",
        "ColorObj_color_type",
    ),
)
register_generated_tags(
    "SaveSetup",
    "SaveObj",
    LEAF_SETUP_TABLES_SOURCE,
    (
        "SaveObj_version",
        "SaveObj_name",
        "SaveObj_type",
        "SaveObj_back_type",
        "SaveObj_leaf_auto_active",
        "SaveObj_leaf_hot_folder",
        "SaveObj_leaf_output_file_type",
        "SaveObj_leaf_auto_base_name",
        "SaveObj_leaf_save_selection",
        "SaveObj_leaf_open_proc_HDR",
        "SaveObj_std_auto_active",
        "SaveObj_std_hot_folder",
        "SaveObj_std_output_file_type",
        "SaveObj_std_output_color_mode",
        "SaveObj_std_output_bit_depth",
        "SaveObj_std_base_name",
        "SaveObj_std_save_selection",
        "SaveObj_std_oxygen",
        "SaveObj_std_open_in_photoshop",
        "SaveObj_std_scaled_output",
        "SaveObj_std_sharpen_output",
    ),
)
register_generated_tags(
    "CameraSetup",
    "CameraObj",
    LEAF_SETUP_TABLES_SOURCE,
    (
        "CameraObj_version",
        "CameraObj_name",
        "CameraObj_type",
        "CameraObj_back_type",
        "CameraObj_strobe",
        "CameraObj_camera_type",
        "CameraObj_lens_type",
    ),
)
register_generated_tags(
    "LookHeader",
    "LookHead",
    LEAF_SETUP_TABLES_SOURCE,
    (
        "LookHead_version",
        "LookHead_name",
        "LookHead_type",
        "LookHead_back_type",
    ),
)
