"""Source-grounded, non-mutating Kyocera RAW metadata transaction plans.

ExifTool's KyoceraRaw module reads a 156-byte Contax N Digital RAW header,
validates the reversed KYOCERA make bytes at offset 0x19, switches binary data
parsing to big-endian, and exposes a fixed MakerNotes tag table. This planner
mirrors those boundaries while preserving unknown header bytes and trailing RAW
payload bytes unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject, JsonValue

KYOCERA_RAW_HEADER_SIZE = 156
KYOCERA_RAW_MAKE_OFFSET = 0x19
KYOCERA_RAW_MAKE_BYTES = b"ARECOYK"
KYOCERA_RAW_PM_SOURCE_PATH = "lib/Image/ExifTool/KyoceraRaw.pm"

type KyoceraRawPlanStatus = Literal["planned", "unsupported"]
type KyoceraRawByteOrder = Literal["MM"]
type KyoceraRawGroup0 = Literal["MakerNotes"]
type KyoceraRawGroup2 = Literal["Camera", "Image", "Time", "Unknown"]
type KyoceraRawValueFormat = Literal[
    "string[7]",
    "string[10]",
    "string[12]",
    "string[20]",
    "string[32]",
    "int32u",
    "int32u[4]",
]
type KyoceraRawFieldRole = Literal[
    "reversed_string_metadata",
    "string_metadata",
    "big_endian_scalar_metadata",
    "big_endian_array_metadata",
]
type KyoceraRawPreservationRole = Literal["unknown_header_bytes", "tail_payload"]
type KyoceraRawActionKind = Literal[
    "read_fixed_header",
    "validate_reversed_make",
    "set_file_type",
    "set_big_endian_byte_order",
    "process_binary_data_table",
    "preserve_unknown_header_bytes",
    "preserve_tail_payload",
    "block_requested_rewrite",
    "no_metadata_mutation",
]
type KyoceraRawEmissionGateCode = Literal[
    "truncated_kyocera_raw_header",
    "unsupported_kyocera_raw_make",
    "kyocera_raw_header_rewrite_required",
    "kyocera_raw_field_rewrite_required",
    "kyocera_raw_tail_payload_rewrite_required",
    "kyocera_raw_metadata_delete_required",
    "planner_is_non_mutating",
    "full_kyocera_raw_writer_not_implemented",
]
type KyoceraRawResponsibilityConcern = Literal[
    "fixed_156_byte_header",
    "reversed_make_signature_validation",
    "big_endian_binary_data_routing",
    "main_table_metadata_fields",
    "reversed_string_value_conversion",
    "unknown_header_byte_preservation",
    "tail_payload_preservation",
    "malformed_truncation_blockers",
    "unsupported_rewrite_gates",
]

KYOCERA_RAW_DESCRIPTION_SOURCE = "kyocera-raw.pm.read-only-description"
KYOCERA_RAW_REVERSE_SOURCE = "kyocera-raw.pm.reverse-string"
KYOCERA_RAW_MAIN_TABLE_SOURCE = "kyocera-raw.pm.main-table"
KYOCERA_RAW_PROCESS_SOURCE = "kyocera-raw.pm.process-raw"
KYOCERA_RAW_VALIDATION_SOURCE = "kyocera-raw.pm.process-raw.header-validation"

KYOCERA_RAW_TRANSACTION_SOURCES = (
    KYOCERA_RAW_DESCRIPTION_SOURCE,
    KYOCERA_RAW_REVERSE_SOURCE,
    KYOCERA_RAW_MAIN_TABLE_SOURCE,
    KYOCERA_RAW_PROCESS_SOURCE,
    KYOCERA_RAW_VALIDATION_SOURCE,
)

ISO_PRINT_VALUES: dict[int, int] = {
    7: 25,
    8: 32,
    9: 40,
    10: 50,
    11: 64,
    12: 80,
    13: 100,
    14: 125,
    15: 160,
    16: 200,
    17: 250,
    18: 320,
    19: 400,
}


@dataclass(frozen=True)
class KyoceraRawFieldRewrite:
    tag_name: str
    replacement_payload: bytes


@dataclass(frozen=True)
class KyoceraRawMetadataRewriteRequest:
    replacement_header: bytes | None = None
    field_rewrites: tuple[KyoceraRawFieldRewrite, ...] = ()
    replacement_tail_payload: bytes | None = None
    delete_metadata: bool = False


@dataclass(frozen=True)
class KyoceraRawTagDefinition:
    offset: int
    name: str
    format_name: KyoceraRawValueFormat
    byte_count: int
    group0: KyoceraRawGroup0
    group2: KyoceraRawGroup2
    role: KyoceraRawFieldRole
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class KyoceraRawByteRange:
    start: int
    end: int
    reason: str

    def to_json(self) -> JsonObject:
        return {"end": self.end, "reason": self.reason, "start": self.start}


@dataclass(frozen=True)
class KyoceraRawHeaderValidation:
    header_size: int
    actual_size: int
    header_available: bool
    make_offset: int
    make_signature: bytes
    make_signature_valid: bool
    byte_order: KyoceraRawByteOrder | None
    file_type_set: bool
    reason: KyoceraRawEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "actual_size": self.actual_size,
            "byte_order": self.byte_order,
            "file_type_set": self.file_type_set,
            "header_available": self.header_available,
            "header_size": self.header_size,
            "make_offset": self.make_offset,
            "make_signature": self.make_signature.hex(),
            "make_signature_valid": self.make_signature_valid,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class KyoceraRawMetadataFieldPlan:
    offset: int
    tag_name: str
    format_name: KyoceraRawValueFormat
    group0: KyoceraRawGroup0
    group2: KyoceraRawGroup2
    role: KyoceraRawFieldRole
    byte_range: KyoceraRawByteRange
    payload: bytes
    payload_preserved: bool
    parsed_value: JsonValue
    display_value: JsonValue
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": self.byte_range.to_json(),
            "display_value": self.display_value,
            "format_name": self.format_name,
            "group0": self.group0,
            "group2": self.group2,
            "offset": self.offset,
            "parsed_value": self.parsed_value,
            "payload": self.payload.hex(),
            "payload_preserved": self.payload_preserved,
            "role": self.role,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class KyoceraRawPreservationPlan:
    role: KyoceraRawPreservationRole
    byte_range: KyoceraRawByteRange
    payload: bytes
    payload_preserved: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": self.byte_range.to_json(),
            "payload": self.payload.hex(),
            "payload_preserved": self.payload_preserved,
            "role": self.role,
        }


@dataclass(frozen=True)
class KyoceraRawActionPlan:
    kind: KyoceraRawActionKind
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
class KyoceraRawResponsibilityPlan:
    concern: KyoceraRawResponsibilityConcern
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class KyoceraRawOutputEmissionGate:
    code: KyoceraRawEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class KyoceraRawMetadataTransactionPlan:
    status: KyoceraRawPlanStatus
    header_validation: KyoceraRawHeaderValidation
    metadata_fields: tuple[KyoceraRawMetadataFieldPlan, ...]
    preserved_unknown_header_ranges: tuple[KyoceraRawPreservationPlan, ...]
    preserved_tail_payload: KyoceraRawPreservationPlan
    actions: tuple[KyoceraRawActionPlan, ...]
    responsibilities: tuple[KyoceraRawResponsibilityPlan, ...]
    output_emission_gates: tuple[KyoceraRawOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Kyocera RAW metadata transaction output is gated: {gate_codes}")
        return self.original_bytes

    def fields_by_name(self) -> dict[str, KyoceraRawMetadataFieldPlan]:
        return {field.tag_name: field for field in self.metadata_fields}

    def to_json(self) -> JsonObject:
        return {
            "actions": json_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "header_validation": self.header_validation.to_json(),
            "metadata_fields": json_array(field.to_json() for field in self.metadata_fields),
            "output_emission_gates": json_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "preserved_tail_payload": self.preserved_tail_payload.to_json(),
            "preserved_unknown_header_ranges": json_array(
                item.to_json() for item in self.preserved_unknown_header_ranges
            ),
            "responsibilities": json_array(
                responsibility.to_json() for responsibility in self.responsibilities
            ),
            "status": self.status,
        }


KYOCERA_RAW_TAGS: tuple[KyoceraRawTagDefinition, ...] = (
    KyoceraRawTagDefinition(
        0x01,
        "FirmwareVersion",
        "string[10]",
        10,
        "MakerNotes",
        "Camera",
        "reversed_string_metadata",
        (KYOCERA_RAW_MAIN_TABLE_SOURCE, KYOCERA_RAW_REVERSE_SOURCE),
    ),
    KyoceraRawTagDefinition(
        0x0C,
        "Model",
        "string[12]",
        12,
        "MakerNotes",
        "Camera",
        "reversed_string_metadata",
        (KYOCERA_RAW_MAIN_TABLE_SOURCE, KYOCERA_RAW_REVERSE_SOURCE),
    ),
    KyoceraRawTagDefinition(
        0x19,
        "Make",
        "string[7]",
        7,
        "MakerNotes",
        "Camera",
        "reversed_string_metadata",
        (KYOCERA_RAW_MAIN_TABLE_SOURCE, KYOCERA_RAW_REVERSE_SOURCE),
    ),
    KyoceraRawTagDefinition(
        0x21,
        "DateTimeOriginal",
        "string[20]",
        20,
        "MakerNotes",
        "Time",
        "reversed_string_metadata",
        (KYOCERA_RAW_MAIN_TABLE_SOURCE, KYOCERA_RAW_REVERSE_SOURCE),
    ),
    KyoceraRawTagDefinition(
        0x34,
        "ISO",
        "int32u",
        4,
        "MakerNotes",
        "Image",
        "big_endian_scalar_metadata",
        (KYOCERA_RAW_MAIN_TABLE_SOURCE, KYOCERA_RAW_PROCESS_SOURCE),
    ),
    KyoceraRawTagDefinition(
        0x38,
        "ExposureTime",
        "int32u",
        4,
        "MakerNotes",
        "Image",
        "big_endian_scalar_metadata",
        (KYOCERA_RAW_MAIN_TABLE_SOURCE, KYOCERA_RAW_PROCESS_SOURCE),
    ),
    KyoceraRawTagDefinition(
        0x3C,
        "WB_RGGBLevels",
        "int32u[4]",
        16,
        "MakerNotes",
        "Image",
        "big_endian_array_metadata",
        (KYOCERA_RAW_MAIN_TABLE_SOURCE, KYOCERA_RAW_PROCESS_SOURCE),
    ),
    KyoceraRawTagDefinition(
        0x58,
        "FNumber",
        "int32u",
        4,
        "MakerNotes",
        "Image",
        "big_endian_scalar_metadata",
        (KYOCERA_RAW_MAIN_TABLE_SOURCE, KYOCERA_RAW_PROCESS_SOURCE),
    ),
    KyoceraRawTagDefinition(
        0x68,
        "MaxAperture",
        "int32u",
        4,
        "MakerNotes",
        "Camera",
        "big_endian_scalar_metadata",
        (KYOCERA_RAW_MAIN_TABLE_SOURCE, KYOCERA_RAW_PROCESS_SOURCE),
    ),
    KyoceraRawTagDefinition(
        0x70,
        "FocalLength",
        "int32u",
        4,
        "MakerNotes",
        "Camera",
        "big_endian_scalar_metadata",
        (KYOCERA_RAW_MAIN_TABLE_SOURCE, KYOCERA_RAW_PROCESS_SOURCE),
    ),
    KyoceraRawTagDefinition(
        0x7C,
        "Lens",
        "string[32]",
        32,
        "MakerNotes",
        "Camera",
        "string_metadata",
        (KYOCERA_RAW_MAIN_TABLE_SOURCE,),
    ),
)


def build_kyocera_raw_metadata_transaction_plan(
    raw_data: bytes,
    rewrite_request: KyoceraRawMetadataRewriteRequest | None = None,
    *,
    allow_output_emission: bool = False,
) -> KyoceraRawMetadataTransactionPlan:
    header_validation = build_header_validation(raw_data)
    metadata_fields = build_metadata_fields(raw_data, header_validation)
    unknown_header_ranges = build_unknown_header_preservation(raw_data, header_validation)
    tail_payload = build_tail_payload_preservation(raw_data)
    gates = validation_gates(header_validation)
    if rewrite_request is not None and rewrite_requested(rewrite_request):
        gates.extend(rewrite_gates(rewrite_request))
    if not allow_output_emission:
        gates.extend(non_mutating_default_gates())
    actions = build_actions(
        raw_data,
        header_validation,
        metadata_fields,
        unknown_header_ranges,
        tail_payload,
        rewrite_request,
    )
    status: KyoceraRawPlanStatus = "unsupported" if has_validation_gate(gates) else "planned"
    sources = unique_evidence_ids(
        (
            *KYOCERA_RAW_TRANSACTION_SOURCES,
            *header_validation.evidence_ids,
            *(source for field in metadata_fields for source in field.evidence_ids),
            *(source for item in unknown_header_ranges for source in item.evidence_ids),
            *tail_payload.evidence_ids,
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return KyoceraRawMetadataTransactionPlan(
        status=status,
        header_validation=header_validation,
        metadata_fields=metadata_fields,
        preserved_unknown_header_ranges=unknown_header_ranges,
        preserved_tail_payload=tail_payload,
        actions=actions,
        responsibilities=build_responsibilities(),
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
        original_bytes=raw_data,
    )


def build_header_validation(raw_data: bytes) -> KyoceraRawHeaderValidation:
    header_available = len(raw_data) >= KYOCERA_RAW_HEADER_SIZE
    make_signature = raw_data[
        KYOCERA_RAW_MAKE_OFFSET : KYOCERA_RAW_MAKE_OFFSET + len(KYOCERA_RAW_MAKE_BYTES)
    ]
    reason: KyoceraRawEmissionGateCode | None = None
    if not header_available:
        reason = "truncated_kyocera_raw_header"
    elif make_signature != KYOCERA_RAW_MAKE_BYTES:
        reason = "unsupported_kyocera_raw_make"
    return KyoceraRawHeaderValidation(
        header_size=KYOCERA_RAW_HEADER_SIZE,
        actual_size=len(raw_data),
        header_available=header_available,
        make_offset=KYOCERA_RAW_MAKE_OFFSET,
        make_signature=make_signature,
        make_signature_valid=header_available and make_signature == KYOCERA_RAW_MAKE_BYTES,
        byte_order="MM" if reason is None else None,
        file_type_set=reason is None,
        reason=reason,
        evidence_ids=(KYOCERA_RAW_PROCESS_SOURCE, KYOCERA_RAW_VALIDATION_SOURCE),
    )


def build_metadata_fields(
    raw_data: bytes, header_validation: KyoceraRawHeaderValidation
) -> tuple[KyoceraRawMetadataFieldPlan, ...]:
    if header_validation.reason is not None:
        return ()
    fields: list[KyoceraRawMetadataFieldPlan] = []
    for definition in KYOCERA_RAW_TAGS:
        start = definition.offset
        end = start + definition.byte_count
        payload = raw_data[start:end]
        parsed_value = parse_field_value(definition, payload)
        display_value = display_field_value(definition, parsed_value)
        fields.append(
            KyoceraRawMetadataFieldPlan(
                offset=definition.offset,
                tag_name=definition.name,
                format_name=definition.format_name,
                group0=definition.group0,
                group2=definition.group2,
                role=definition.role,
                byte_range=KyoceraRawByteRange(
                    start=start,
                    end=end,
                    reason=f"{definition.name} fixed binary data field.",
                ),
                payload=payload,
                payload_preserved=True,
                parsed_value=parsed_value,
                display_value=display_value,
                evidence_ids=definition.evidence_ids,
            )
        )
    return tuple(fields)


def build_unknown_header_preservation(
    raw_data: bytes, header_validation: KyoceraRawHeaderValidation
) -> tuple[KyoceraRawPreservationPlan, ...]:
    if header_validation.reason is not None:
        return ()
    covered = bytearray(KYOCERA_RAW_HEADER_SIZE)
    for definition in KYOCERA_RAW_TAGS:
        start = definition.offset
        end = min(start + definition.byte_count, KYOCERA_RAW_HEADER_SIZE)
        covered[start:end] = b"\x01" * (end - start)
    ranges: list[KyoceraRawPreservationPlan] = []
    range_start: int | None = None
    for offset, is_covered in enumerate(covered):
        if not is_covered and range_start is None:
            range_start = offset
        elif is_covered and range_start is not None:
            ranges.append(unknown_header_range(raw_data, range_start, offset))
            range_start = None
    if range_start is not None:
        ranges.append(unknown_header_range(raw_data, range_start, KYOCERA_RAW_HEADER_SIZE))
    return tuple(ranges)


def unknown_header_range(raw_data: bytes, start: int, end: int) -> KyoceraRawPreservationPlan:
    return KyoceraRawPreservationPlan(
        role="unknown_header_bytes",
        byte_range=KyoceraRawByteRange(
            start=start,
            end=end,
            reason="Header bytes not claimed by KyoceraRaw.pm Main table fields.",
        ),
        payload=raw_data[start:end],
        payload_preserved=True,
        evidence_ids=(KYOCERA_RAW_MAIN_TABLE_SOURCE, KYOCERA_RAW_PROCESS_SOURCE),
    )


def build_tail_payload_preservation(raw_data: bytes) -> KyoceraRawPreservationPlan:
    start = min(KYOCERA_RAW_HEADER_SIZE, len(raw_data))
    return KyoceraRawPreservationPlan(
        role="tail_payload",
        byte_range=KyoceraRawByteRange(
            start=start,
            end=len(raw_data),
            reason="ProcessRAW only reads and parses the 156-byte header.",
        ),
        payload=raw_data[start:],
        payload_preserved=True,
        evidence_ids=(KYOCERA_RAW_PROCESS_SOURCE,),
    )


def parse_field_value(definition: KyoceraRawTagDefinition, payload: bytes) -> JsonValue:
    if definition.role == "reversed_string_metadata":
        return decode_latin1(payload[::-1])
    if definition.role == "string_metadata":
        return decode_latin1(payload)
    if definition.format_name == "int32u[4]":
        values: JsonArray = []
        for offset in range(0, len(payload), 4):
            values.append(read_u32be(payload[offset : offset + 4]))
        return values
    return read_u32be(payload)


def display_field_value(definition: KyoceraRawTagDefinition, parsed_value: JsonValue) -> JsonValue:
    if definition.name == "ISO" and isinstance(parsed_value, int):
        return ISO_PRINT_VALUES.get(parsed_value, parsed_value)
    if definition.name == "ExposureTime" and isinstance(parsed_value, int):
        return (2 ** (parsed_value / 8)) / 16000
    if definition.name in {"FNumber", "MaxAperture"} and isinstance(parsed_value, int):
        return 2 ** (parsed_value / 16)
    if definition.name == "FocalLength" and isinstance(parsed_value, int):
        return f"{parsed_value} mm"
    return parsed_value


def decode_latin1(payload: bytes) -> str:
    return payload.decode("latin-1", errors="replace").strip("\0 ")


def read_u32be(payload: bytes) -> int:
    return int.from_bytes(payload, "big")


def validation_gates(
    header_validation: KyoceraRawHeaderValidation,
) -> list[KyoceraRawOutputEmissionGate]:
    if header_validation.reason is None:
        return []
    return [
        KyoceraRawOutputEmissionGate(
            code=header_validation.reason,
            reason=(
                "Kyocera RAW planning requires the exact 156-byte header and reversed "
                "KYOCERA make bytes used by ProcessRAW."
            ),
            evidence_ids=header_validation.evidence_ids,
        )
    ]


def rewrite_gates(
    rewrite_request: KyoceraRawMetadataRewriteRequest,
) -> list[KyoceraRawOutputEmissionGate]:
    gates: list[KyoceraRawOutputEmissionGate] = []
    if rewrite_request.replacement_header is not None:
        gates.append(
            KyoceraRawOutputEmissionGate(
                code="kyocera_raw_header_rewrite_required",
                reason="KyoceraRaw.pm provides a reader and no full 156-byte header writer.",
                evidence_ids=(KYOCERA_RAW_DESCRIPTION_SOURCE, KYOCERA_RAW_PROCESS_SOURCE),
            )
        )
    if rewrite_request.field_rewrites:
        gates.append(
            KyoceraRawOutputEmissionGate(
                code="kyocera_raw_field_rewrite_required",
                reason="Fixed binary data fields need a source-backed Kyocera RAW writer.",
                evidence_ids=(KYOCERA_RAW_MAIN_TABLE_SOURCE,),
            )
        )
    if rewrite_request.replacement_tail_payload is not None:
        gates.append(
            KyoceraRawOutputEmissionGate(
                code="kyocera_raw_tail_payload_rewrite_required",
                reason="RAW payload bytes after the parsed header are outside this reader slice.",
                evidence_ids=(KYOCERA_RAW_PROCESS_SOURCE,),
            )
        )
    if rewrite_request.delete_metadata:
        gates.append(
            KyoceraRawOutputEmissionGate(
                code="kyocera_raw_metadata_delete_required",
                reason=(
                    "Deleting the fixed header would invalidate the Kyocera RAW reader contract."
                ),
                evidence_ids=(KYOCERA_RAW_PROCESS_SOURCE,),
            )
        )
    return gates


def non_mutating_default_gates() -> list[KyoceraRawOutputEmissionGate]:
    return [
        KyoceraRawOutputEmissionGate(
            code="planner_is_non_mutating",
            reason="The default planner records preservation work but does not emit bytes.",
            evidence_ids=(KYOCERA_RAW_DESCRIPTION_SOURCE,),
        ),
        KyoceraRawOutputEmissionGate(
            code="full_kyocera_raw_writer_not_implemented",
            reason="A full Kyocera RAW writer is required before default output emission.",
            evidence_ids=(KYOCERA_RAW_DESCRIPTION_SOURCE,),
        ),
    ]


def build_actions(
    raw_data: bytes,
    header_validation: KyoceraRawHeaderValidation,
    metadata_fields: Sequence[KyoceraRawMetadataFieldPlan],
    unknown_header_ranges: Sequence[KyoceraRawPreservationPlan],
    tail_payload: KyoceraRawPreservationPlan,
    rewrite_request: KyoceraRawMetadataRewriteRequest | None,
) -> tuple[KyoceraRawActionPlan, ...]:
    actions = [
        KyoceraRawActionPlan(
            kind="read_fixed_header",
            byte_range_start=0,
            byte_range_end=min(KYOCERA_RAW_HEADER_SIZE, len(raw_data)),
            input_payload_length=len(raw_data),
            planned_payload_length=KYOCERA_RAW_HEADER_SIZE,
            reason="Read the fixed header size used by ProcessRAW.",
            evidence_ids=(KYOCERA_RAW_PROCESS_SOURCE,),
        ),
        KyoceraRawActionPlan(
            kind="validate_reversed_make",
            byte_range_start=KYOCERA_RAW_MAKE_OFFSET,
            byte_range_end=KYOCERA_RAW_MAKE_OFFSET + len(KYOCERA_RAW_MAKE_BYTES),
            input_payload_length=len(header_validation.make_signature),
            planned_payload_length=len(KYOCERA_RAW_MAKE_BYTES),
            reason="Validate the reversed KYOCERA bytes required by ProcessRAW.",
            evidence_ids=(KYOCERA_RAW_VALIDATION_SOURCE,),
        ),
    ]
    if header_validation.reason is None:
        actions.extend(valid_header_actions(metadata_fields, unknown_header_ranges, tail_payload))
    if rewrite_request is not None and rewrite_requested(rewrite_request):
        actions.append(
            KyoceraRawActionPlan(
                kind="block_requested_rewrite",
                byte_range_start=0,
                byte_range_end=len(raw_data),
                input_payload_length=len(raw_data),
                planned_payload_length=None,
                reason="Requested Kyocera RAW mutation is gated until a full writer exists.",
                evidence_ids=(KYOCERA_RAW_DESCRIPTION_SOURCE, KYOCERA_RAW_PROCESS_SOURCE),
            )
        )
    actions.append(
        KyoceraRawActionPlan(
            kind="no_metadata_mutation",
            byte_range_start=0,
            byte_range_end=len(raw_data),
            input_payload_length=len(raw_data),
            planned_payload_length=len(raw_data),
            reason="The planner preserves source bytes without applying metadata mutation.",
            evidence_ids=(KYOCERA_RAW_DESCRIPTION_SOURCE,),
        )
    )
    return tuple(actions)


def valid_header_actions(
    metadata_fields: Sequence[KyoceraRawMetadataFieldPlan],
    unknown_header_ranges: Sequence[KyoceraRawPreservationPlan],
    tail_payload: KyoceraRawPreservationPlan,
) -> list[KyoceraRawActionPlan]:
    actions = [
        KyoceraRawActionPlan(
            kind="set_file_type",
            byte_range_start=None,
            byte_range_end=None,
            input_payload_length=None,
            planned_payload_length=None,
            reason="ProcessRAW marks the validated input as the Kyocera RAW file type.",
            evidence_ids=(KYOCERA_RAW_PROCESS_SOURCE,),
        ),
        KyoceraRawActionPlan(
            kind="set_big_endian_byte_order",
            byte_range_start=None,
            byte_range_end=None,
            input_payload_length=None,
            planned_payload_length=None,
            reason="ProcessRAW calls SetByteOrder('MM') before binary data parsing.",
            evidence_ids=(KYOCERA_RAW_PROCESS_SOURCE,),
        ),
        KyoceraRawActionPlan(
            kind="process_binary_data_table",
            byte_range_start=0,
            byte_range_end=KYOCERA_RAW_HEADER_SIZE,
            input_payload_length=KYOCERA_RAW_HEADER_SIZE,
            planned_payload_length=KYOCERA_RAW_HEADER_SIZE,
            reason=f"Plan {len(metadata_fields)} fixed fields from the Main table.",
            evidence_ids=(KYOCERA_RAW_MAIN_TABLE_SOURCE, KYOCERA_RAW_PROCESS_SOURCE),
        ),
    ]
    actions.extend(
        KyoceraRawActionPlan(
            kind="preserve_unknown_header_bytes",
            byte_range_start=item.byte_range.start,
            byte_range_end=item.byte_range.end,
            input_payload_length=len(item.payload),
            planned_payload_length=len(item.payload),
            reason="Preserve header bytes outside known KyoceraRaw.pm tag ranges.",
            evidence_ids=item.evidence_ids,
        )
        for item in unknown_header_ranges
    )
    actions.append(
        KyoceraRawActionPlan(
            kind="preserve_tail_payload",
            byte_range_start=tail_payload.byte_range.start,
            byte_range_end=tail_payload.byte_range.end,
            input_payload_length=len(tail_payload.payload),
            planned_payload_length=len(tail_payload.payload),
            reason="Preserve bytes after the fixed parsed header.",
            evidence_ids=tail_payload.evidence_ids,
        )
    )
    return actions


def build_responsibilities() -> tuple[KyoceraRawResponsibilityPlan, ...]:
    return (
        KyoceraRawResponsibilityPlan(
            concern="fixed_156_byte_header",
            reason="Mirror the exact header length read by ProcessRAW.",
            evidence_ids=(KYOCERA_RAW_PROCESS_SOURCE,),
        ),
        KyoceraRawResponsibilityPlan(
            concern="reversed_make_signature_validation",
            reason="Require ARECOYK at offset 0x19 before routing as Kyocera RAW.",
            evidence_ids=(KYOCERA_RAW_VALIDATION_SOURCE,),
        ),
        KyoceraRawResponsibilityPlan(
            concern="big_endian_binary_data_routing",
            reason="Read integer fields as big-endian after SetByteOrder('MM').",
            evidence_ids=(KYOCERA_RAW_PROCESS_SOURCE,),
        ),
        KyoceraRawResponsibilityPlan(
            concern="main_table_metadata_fields",
            reason="Classify fixed offsets and groups from the Main tag table.",
            evidence_ids=(KYOCERA_RAW_MAIN_TABLE_SOURCE,),
        ),
        KyoceraRawResponsibilityPlan(
            concern="reversed_string_value_conversion",
            reason="Reverse only fields whose source tag definitions use ReverseString.",
            evidence_ids=(KYOCERA_RAW_REVERSE_SOURCE, KYOCERA_RAW_MAIN_TABLE_SOURCE),
        ),
        KyoceraRawResponsibilityPlan(
            concern="unknown_header_byte_preservation",
            reason="Keep unclaimed header byte ranges unchanged.",
            evidence_ids=(KYOCERA_RAW_MAIN_TABLE_SOURCE, KYOCERA_RAW_PROCESS_SOURCE),
        ),
        KyoceraRawResponsibilityPlan(
            concern="tail_payload_preservation",
            reason="Keep bytes after the parsed 156-byte header unchanged.",
            evidence_ids=(KYOCERA_RAW_PROCESS_SOURCE,),
        ),
        KyoceraRawResponsibilityPlan(
            concern="malformed_truncation_blockers",
            reason="Block planning when ProcessRAW would return false.",
            evidence_ids=(KYOCERA_RAW_VALIDATION_SOURCE,),
        ),
        KyoceraRawResponsibilityPlan(
            concern="unsupported_rewrite_gates",
            reason="Gate writes because KyoceraRaw.pm is a reader slice.",
            evidence_ids=(KYOCERA_RAW_DESCRIPTION_SOURCE,),
        ),
    )


def rewrite_requested(rewrite_request: KyoceraRawMetadataRewriteRequest) -> bool:
    return (
        rewrite_request.replacement_header is not None
        or bool(rewrite_request.field_rewrites)
        or rewrite_request.replacement_tail_payload is not None
        or rewrite_request.delete_metadata
    )


def has_validation_gate(gates: Sequence[KyoceraRawOutputEmissionGate]) -> bool:
    validation_codes = {
        "truncated_kyocera_raw_header",
        "unsupported_kyocera_raw_make",
    }
    return any(gate.code in validation_codes for gate in gates)


def unique_gates(
    gates: Sequence[KyoceraRawOutputEmissionGate],
) -> tuple[KyoceraRawOutputEmissionGate, ...]:
    seen: set[KyoceraRawEmissionGateCode] = set()
    unique: list[KyoceraRawOutputEmissionGate] = []
    for gate in gates:
        if gate.code not in seen:
            unique.append(gate)
            seen.add(gate.code)
    return tuple(unique)


def unique_evidence_ids(sources: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for source in sources:
        if source not in seen:
            unique.append(source)
            seen.add(source)
    return tuple(unique)


def json_array(values: Iterable[JsonObject]) -> JsonArray:
    items: JsonArray = []
    for value in values:
        items.append(value)
    return items
