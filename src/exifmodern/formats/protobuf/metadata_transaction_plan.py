"""Source-backed, non-mutating Protobuf metadata transaction plans.

ExifTool's Protobuf module is a reader. It decodes varint tags into field
numbers and wire types, classifies length-delimited payloads with lightweight
heuristics, optionally descends into unknown nested messages, and reports
format errors for malformed records. This planner mirrors those responsibilities
without rewriting bytes.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

PROTOBUF_PM_SOURCE_PATH = "lib/Image/ExifTool/Protobuf.pm"
PROTOBUF_INT64S_MIN = 18_446_744_069_414_584_320
PROTOBUF_INT_MAX = (1 << 64) - 1

type ProtobufPlanStatus = Literal["planned", "unsupported"]
type ProtobufWireType = Literal[0, 1, 2, 3, 4, 5]
type ProtobufLengthDelimitedKind = Literal[
    "empty",
    "protocol_name",
    "nested_message",
    "ascii_string",
    "bytes_hex",
    "bytes_hex_4byte_groups",
]
type ProtobufDatabaseRouteKind = Literal["known_field", "unknown_field"]
type ProtobufActionKind = Literal[
    "decode_tag_varint",
    "decode_value_varint",
    "decode_fixed64",
    "decode_length_delimited",
    "decode_start_group",
    "decode_end_group",
    "decode_fixed32",
    "classify_protocol_name",
    "classify_length_delimited",
    "descend_nested_message",
    "preserve_known_field",
    "preserve_unknown_field",
    "preserve_repeated_field",
    "block_requested_rewrite",
]
type ProtobufRewriteOperation = Literal["replace", "delete", "insert"]
type ProtobufEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_tag_varint",
    "malformed_tag_varint",
    "unsupported_wire_type",
    "truncated_value_varint",
    "malformed_value_varint",
    "truncated_length_varint",
    "malformed_length_varint",
    "truncated_length_delimited_payload",
    "truncated_fixed64_payload",
    "truncated_fixed32_payload",
    "rewrite_requested_requires_protobuf_writer",
]
type ProtobufFormatName = Literal[
    "signed",
    "unsigned",
    "int64s",
    "int64u",
    "rational64u",
    "rational64s",
    "double",
    "undef",
    "string",
    "rational",
    "int32u",
    "int32s",
    "rational32u",
    "rational32s",
    "fixed32u",
    "fixed32s",
    "float",
]

PROTOBUF_NOTES_SOURCE = "protobuf.notes"
PROTOBUF_GET_BYTES_SOURCE = "protobuf.get.bytes"
PROTOBUF_VARINT_SOURCE = "protobuf.varint"
PROTOBUF_READ_RECORD_SOURCE = "protobuf.read.record"
PROTOBUF_IS_PROTOBUF_SOURCE = "protobuf.is.protobuf"
PROTOBUF_PROCESS_LOOP_SOURCE = "protobuf.process.loop"
PROTOBUF_NESTED_SOURCE = "protobuf.nested"
PROTOBUF_VALUE_FORMAT_SOURCE = "protobuf.value.format"
PROTOBUF_HANDLE_TAG_SOURCE = "protobuf.handle.tag"
PROTOBUF_TRUNCATED_SOURCE = "protobuf.truncated"
PROTOBUF_READ_ONLY_SOURCE = "protobuf.read.only"

PROTOBUF_TRANSACTION_SOURCES = (
    PROTOBUF_NOTES_SOURCE,
    PROTOBUF_GET_BYTES_SOURCE,
    PROTOBUF_VARINT_SOURCE,
    PROTOBUF_READ_RECORD_SOURCE,
    PROTOBUF_IS_PROTOBUF_SOURCE,
    PROTOBUF_PROCESS_LOOP_SOURCE,
    PROTOBUF_NESTED_SOURCE,
    PROTOBUF_VALUE_FORMAT_SOURCE,
    PROTOBUF_HANDLE_TAG_SOURCE,
    PROTOBUF_TRUNCATED_SOURCE,
    PROTOBUF_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class ProtobufFieldDefinition:
    tag: str
    name: str
    expected_wire_type: ProtobufWireType | None = None
    format_name: ProtobufFormatName | None = None
    is_protobuf: bool | None = None
    has_subdirectory: bool = False
    is_unknown: bool = False


@dataclass(frozen=True)
class ProtobufFieldDatabase:
    definitions: tuple[ProtobufFieldDefinition, ...] = ()
    tag_prefix: str | None = None

    def definition_map(self) -> Mapping[str, ProtobufFieldDefinition]:
        return {definition.tag: definition for definition in self.definitions}


@dataclass(frozen=True)
class ProtobufRewriteRequest:
    field_path: str
    operation: ProtobufRewriteOperation
    replacement_payload: bytes | None = None


@dataclass(frozen=True)
class ProtobufVarintPlan:
    start_offset: int
    end_offset: int
    encoded: bytes
    value: int | None
    bit0: int | None
    reason: ProtobufEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return self.reason is None and self.value is not None

    def to_json(self) -> JsonObject:
        return {
            "bit0": self.bit0,
            "encoded_hex": self.encoded.hex(),
            "end_offset": self.end_offset,
            "reason": self.reason,
            "start_offset": self.start_offset,
            "value": self.value,
        }


@dataclass(frozen=True)
class ProtobufTagPlan:
    varint: ProtobufVarintPlan
    field_number: int | None
    wire_type: int | None
    wire_type_supported: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "field_number": self.field_number,
            "varint": self.varint.to_json(),
            "wire_type": self.wire_type,
            "wire_type_supported": self.wire_type_supported,
        }


@dataclass(frozen=True)
class ProtobufLengthDelimitedPlan:
    kind: ProtobufLengthDelimitedKind
    length_varint: ProtobufVarintPlan | None
    declared_length: int | None
    payload_start_offset: int | None
    payload_end_offset: int | None
    ascii_text: str | None
    hex_value: str | None
    rational_numerator: int | None
    rational_denominator: int | None
    protocol_prefix: str | None
    evidence_ids: tuple[str, ...]

    @property
    def has_rational_pair(self) -> bool:
        return self.rational_numerator is not None and self.rational_denominator is not None

    def to_json(self) -> JsonObject:
        return {
            "ascii_text": self.ascii_text,
            "declared_length": self.declared_length,
            "has_rational_pair": self.has_rational_pair,
            "hex_value": self.hex_value,
            "kind": self.kind,
            "length_varint": self.length_varint.to_json()
            if self.length_varint is not None
            else None,
            "payload_end_offset": self.payload_end_offset,
            "payload_start_offset": self.payload_start_offset,
            "protocol_prefix": self.protocol_prefix,
            "rational_denominator": self.rational_denominator,
            "rational_numerator": self.rational_numerator,
        }


@dataclass(frozen=True)
class ProtobufDatabaseRoutePlan:
    tag: str
    route_kind: ProtobufDatabaseRouteKind
    field_name: str
    expected_wire_type: ProtobufWireType | None
    actual_wire_type: int | None
    format_name: ProtobufFormatName | None
    is_protobuf: bool | None
    preserves_unknown: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "actual_wire_type": self.actual_wire_type,
            "expected_wire_type": self.expected_wire_type,
            "field_name": self.field_name,
            "format_name": self.format_name,
            "is_protobuf": self.is_protobuf,
            "preserves_unknown": self.preserves_unknown,
            "route_kind": self.route_kind,
            "tag": self.tag,
        }


@dataclass(frozen=True)
class ProtobufValuePlan:
    payload_start_offset: int
    payload_end_offset: int
    value_varint: ProtobufVarintPlan | None
    raw_payload: bytes
    display_value: str
    length_delimited: ProtobufLengthDelimitedPlan | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "display_value": self.display_value,
            "length_delimited": self.length_delimited.to_json()
            if self.length_delimited is not None
            else None,
            "payload_end_offset": self.payload_end_offset,
            "payload_hex": self.raw_payload.hex(),
            "payload_start_offset": self.payload_start_offset,
            "value_varint": self.value_varint.to_json() if self.value_varint is not None else None,
        }


@dataclass(frozen=True)
class ProtobufActionPlan:
    kind: ProtobufActionKind
    field_path: str
    byte_range_start: int | None
    byte_range_end: int | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range_end": self.byte_range_end,
            "byte_range_start": self.byte_range_start,
            "field_path": self.field_path,
            "kind": self.kind,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ProtobufRecordPlan:
    index: int
    record_start_offset: int
    record_end_offset: int
    field_path: str
    repeated_index: int
    tag: ProtobufTagPlan
    database_route: ProtobufDatabaseRoutePlan
    value: ProtobufValuePlan
    nested_records: tuple[ProtobufRecordPlan, ...]
    actions: tuple[ProtobufActionPlan, ...]
    evidence_ids: tuple[str, ...]

    @property
    def field_number(self) -> int | None:
        return self.tag.field_number

    @property
    def wire_type(self) -> int | None:
        return self.tag.wire_type

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "database_route": self.database_route.to_json(),
            "field_number": self.field_number,
            "field_path": self.field_path,
            "index": self.index,
            "nested_records": json_object_array(record.to_json() for record in self.nested_records),
            "record_end_offset": self.record_end_offset,
            "record_start_offset": self.record_start_offset,
            "repeated_index": self.repeated_index,
            "tag": self.tag.to_json(),
            "value": self.value.to_json(),
            "wire_type": self.wire_type,
        }


@dataclass(frozen=True)
class ProtobufOutputEmissionGate:
    code: ProtobufEmissionGateCode
    field_path: str | None
    byte_offset: int | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_offset": self.byte_offset,
            "code": self.code,
            "field_path": self.field_path,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ProtobufMetadataTransactionPlan:
    status: ProtobufPlanStatus
    records: tuple[ProtobufRecordPlan, ...]
    actions: tuple[ProtobufActionPlan, ...]
    output_emission_gates: tuple[ProtobufOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Protobuf metadata transaction output is gated: {gate_codes}")
        return self.original_bytes

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "records": json_object_array(record.to_json() for record in self.records),
            "status": self.status,
        }


@dataclass(frozen=True)
class ParsedMessage:
    records: tuple[ProtobufRecordPlan, ...]
    actions: tuple[ProtobufActionPlan, ...]
    gates: tuple[ProtobufOutputEmissionGate, ...]
    end_offset: int


def build_protobuf_metadata_transaction_plan(
    protobuf_data: bytes,
    *,
    field_database: ProtobufFieldDatabase | None = None,
    rewrite_requests: Iterable[ProtobufRewriteRequest] = (),
    allow_output_emission: bool = False,
) -> ProtobufMetadataTransactionPlan:
    database = field_database or ProtobufFieldDatabase()
    parsed = parse_message(
        protobuf_data,
        absolute_start=0,
        absolute_end=len(protobuf_data),
        prefix="",
        protocol_prefix="",
        database=database.definition_map(),
    )
    gates = list(parsed.gates)
    actions = list(parsed.actions)
    rewrite_request_tuple = tuple(rewrite_requests)
    for request in rewrite_request_tuple:
        actions.append(
            ProtobufActionPlan(
                kind="block_requested_rewrite",
                field_path=request.field_path,
                byte_range_start=None,
                byte_range_end=None,
                reason=(
                    "ExifTool's Protobuf module decodes records but does not provide "
                    f"a protobuf writer for {request.operation} requests."
                ),
                evidence_ids=(PROTOBUF_READ_ONLY_SOURCE,),
            )
        )
    if rewrite_request_tuple:
        gates.append(
            ProtobufOutputEmissionGate(
                code="rewrite_requested_requires_protobuf_writer",
                field_path=None,
                byte_offset=None,
                reason=(
                    "Requested Protobuf metadata changes require writer behavior absent upstream."
                ),
                evidence_ids=(PROTOBUF_READ_ONLY_SOURCE,),
            )
        )
    if not allow_output_emission:
        gates.append(
            ProtobufOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                field_path=None,
                byte_offset=None,
                reason="Protobuf transaction plans are non-mutating unless emission is explicit.",
                evidence_ids=(PROTOBUF_READ_ONLY_SOURCE,),
            )
        )
    status: ProtobufPlanStatus = "unsupported" if any_validation_gate(gates) else "planned"
    sources = unique_sources(
        (
            *PROTOBUF_TRANSACTION_SOURCES,
            *(source for record in parsed.records for source in record.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return ProtobufMetadataTransactionPlan(
        status=status,
        records=parsed.records,
        actions=tuple(actions),
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
        original_bytes=protobuf_data,
    )


def parse_message(
    data: bytes,
    *,
    absolute_start: int,
    absolute_end: int,
    prefix: str,
    protocol_prefix: str,
    database: Mapping[str, ProtobufFieldDefinition],
) -> ParsedMessage:
    pos = absolute_start
    records: list[ProtobufRecordPlan] = []
    actions: list[ProtobufActionPlan] = []
    gates: list[ProtobufOutputEmissionGate] = []
    field_counts: dict[str, int] = {}
    active_protocol_prefix = protocol_prefix
    while pos < absolute_end:
        record_index = len(records)
        record, record_gates, active_protocol_prefix = parse_record(
            data,
            record_index=record_index,
            record_start=pos,
            absolute_end=absolute_end,
            prefix=prefix,
            protocol_prefix=active_protocol_prefix,
            database=database,
            field_counts=field_counts,
        )
        gates.extend(record_gates)
        if record is None:
            break
        records.append(record)
        actions.extend(record.actions)
        pos = record.record_end_offset
    return ParsedMessage(
        records=tuple(records),
        actions=tuple(actions),
        gates=tuple(gates),
        end_offset=pos,
    )


def parse_record(
    data: bytes,
    *,
    record_index: int,
    record_start: int,
    absolute_end: int,
    prefix: str,
    protocol_prefix: str,
    database: Mapping[str, ProtobufFieldDefinition],
    field_counts: dict[str, int],
) -> tuple[ProtobufRecordPlan | None, tuple[ProtobufOutputEmissionGate, ...], str]:
    tag_varint = read_varint(data, record_start, absolute_end, "tag")
    if tag_varint.reason is not None or tag_varint.value is None:
        return (
            None,
            (
                ProtobufOutputEmissionGate(
                    code=tag_varint.reason or "truncated_tag_varint",
                    field_path=None,
                    byte_offset=record_start,
                    reason="Protobuf tag varint could not be decoded.",
                    evidence_ids=tag_varint.evidence_ids,
                ),
            ),
            protocol_prefix,
        )
    raw_wire_type = tag_varint.value & 0x07
    field_number = tag_varint.value >> 3
    if raw_wire_type not in (0, 1, 2, 3, 4, 5):
        tag = ProtobufTagPlan(
            varint=tag_varint,
            field_number=field_number,
            wire_type=raw_wire_type,
            wire_type_supported=False,
            evidence_ids=(PROTOBUF_READ_RECORD_SOURCE,),
        )
        return (
            None,
            (
                ProtobufOutputEmissionGate(
                    code="unsupported_wire_type",
                    field_path=str(field_number),
                    byte_offset=record_start,
                    reason=f"Wire type {raw_wire_type} is not handled by ExifTool ReadRecord.",
                    evidence_ids=(PROTOBUF_READ_RECORD_SOURCE,),
                ),
            ),
            protocol_prefix,
        )
    wire_type = supported_wire_type(raw_wire_type)
    tag_path = f"{prefix}{field_number}"
    tag_name = f"{protocol_prefix}{tag_path}"
    repeated_index = field_counts.get(tag_name, 0)
    field_counts[tag_name] = repeated_index + 1
    tag = ProtobufTagPlan(
        varint=tag_varint,
        field_number=field_number,
        wire_type=wire_type,
        wire_type_supported=True,
        evidence_ids=(PROTOBUF_VARINT_SOURCE, PROTOBUF_READ_RECORD_SOURCE),
    )
    route = build_database_route(tag_name, wire_type, database)
    value, value_gates, nested_records, protocol_prefix_after_value = parse_value(
        data,
        record_start=record_start,
        payload_start=tag_varint.end_offset,
        absolute_end=absolute_end,
        tag_path=tag_path,
        field_number=field_number,
        wire_type=wire_type,
        database_route=route,
        prefix=prefix,
        protocol_prefix=protocol_prefix,
        database=database,
    )
    if value is None:
        return None, value_gates, protocol_prefix
    record_end = value.payload_end_offset
    final_tag_name = tag_name
    final_route = route
    if (
        value.length_delimited is not None
        and value.length_delimited.kind == "protocol_name"
        and protocol_prefix_after_value != protocol_prefix
    ):
        final_tag_name = f"{protocol_prefix_after_value}{tag_path}"
        final_route = build_database_route(final_tag_name, wire_type, database)
    record_actions = build_record_actions(
        tag_path=final_tag_name,
        record_start=record_start,
        record_end=record_end,
        wire_type=wire_type,
        route=final_route,
        value=value,
        repeated_index=repeated_index,
    )
    sources = unique_sources(
        (
            *tag.evidence_ids,
            *final_route.evidence_ids,
            *value.evidence_ids,
            *(source for action in record_actions for source in action.evidence_ids),
        )
    )
    return (
        ProtobufRecordPlan(
            index=record_index,
            record_start_offset=record_start,
            record_end_offset=record_end,
            field_path=final_tag_name,
            repeated_index=repeated_index,
            tag=tag,
            database_route=final_route,
            value=value,
            nested_records=nested_records,
            actions=record_actions,
            evidence_ids=sources,
        ),
        value_gates,
        protocol_prefix_after_value,
    )


def parse_value(
    data: bytes,
    *,
    record_start: int,
    payload_start: int,
    absolute_end: int,
    tag_path: str,
    field_number: int,
    wire_type: ProtobufWireType,
    database_route: ProtobufDatabaseRoutePlan,
    prefix: str,
    protocol_prefix: str,
    database: Mapping[str, ProtobufFieldDefinition],
) -> tuple[
    ProtobufValuePlan | None,
    tuple[ProtobufOutputEmissionGate, ...],
    tuple[ProtobufRecordPlan, ...],
    str,
]:
    if wire_type == 0:
        value_varint = read_varint(data, payload_start, absolute_end, "value")
        if value_varint.reason is not None or value_varint.value is None:
            return None, (varint_gate(value_varint, tag_path, payload_start),), (), protocol_prefix
        value = value_varint.value
        raw_payload = data[payload_start : value_varint.end_offset]
        return (
            ProtobufValuePlan(
                payload_start_offset=payload_start,
                payload_end_offset=value_varint.end_offset,
                value_varint=value_varint,
                raw_payload=raw_payload,
                display_value=display_varint_value(value, value_varint.bit0, database_route),
                length_delimited=None,
                evidence_ids=(PROTOBUF_VARINT_SOURCE, PROTOBUF_VALUE_FORMAT_SOURCE),
            ),
            (),
            (),
            protocol_prefix,
        )
    if wire_type == 1:
        end_offset = payload_start + 8
        if end_offset > absolute_end:
            return (
                None,
                (
                    ProtobufOutputEmissionGate(
                        code="truncated_fixed64_payload",
                        field_path=tag_path,
                        byte_offset=payload_start,
                        reason="Fixed64 payload extends beyond the available Protobuf bytes.",
                        evidence_ids=(PROTOBUF_GET_BYTES_SOURCE, PROTOBUF_READ_RECORD_SOURCE),
                    ),
                ),
                (),
                protocol_prefix,
            )
        payload = data[payload_start:end_offset]
        return (
            ProtobufValuePlan(
                payload_start_offset=payload_start,
                payload_end_offset=end_offset,
                value_varint=None,
                raw_payload=payload,
                display_value=display_fixed64_value(payload),
                length_delimited=None,
                evidence_ids=(PROTOBUF_READ_RECORD_SOURCE, PROTOBUF_VALUE_FORMAT_SOURCE),
            ),
            (),
            (),
            protocol_prefix,
        )
    if wire_type == 2:
        return parse_length_delimited_value(
            data,
            record_start=record_start,
            payload_start=payload_start,
            absolute_end=absolute_end,
            tag_path=tag_path,
            field_number=field_number,
            database_route=database_route,
            prefix=prefix,
            protocol_prefix=protocol_prefix,
            database=database,
        )
    if wire_type in (3, 4):
        return (
            ProtobufValuePlan(
                payload_start_offset=payload_start,
                payload_end_offset=payload_start,
                value_varint=None,
                raw_payload=b"",
                display_value="",
                length_delimited=None,
                evidence_ids=(PROTOBUF_READ_RECORD_SOURCE,),
            ),
            (),
            (),
            protocol_prefix,
        )
    end_offset = payload_start + 4
    if end_offset > absolute_end:
        return (
            None,
            (
                ProtobufOutputEmissionGate(
                    code="truncated_fixed32_payload",
                    field_path=tag_path,
                    byte_offset=payload_start,
                    reason="Fixed32 payload extends beyond the available Protobuf bytes.",
                    evidence_ids=(PROTOBUF_GET_BYTES_SOURCE, PROTOBUF_READ_RECORD_SOURCE),
                ),
            ),
            (),
            protocol_prefix,
        )
    payload = data[payload_start:end_offset]
    return (
        ProtobufValuePlan(
            payload_start_offset=payload_start,
            payload_end_offset=end_offset,
            value_varint=None,
            raw_payload=payload,
            display_value=display_fixed32_value(payload),
            length_delimited=None,
            evidence_ids=(PROTOBUF_READ_RECORD_SOURCE, PROTOBUF_VALUE_FORMAT_SOURCE),
        ),
        (),
        (),
        protocol_prefix,
    )


def parse_length_delimited_value(
    data: bytes,
    *,
    record_start: int,
    payload_start: int,
    absolute_end: int,
    tag_path: str,
    field_number: int,
    database_route: ProtobufDatabaseRoutePlan,
    prefix: str,
    protocol_prefix: str,
    database: Mapping[str, ProtobufFieldDefinition],
) -> tuple[
    ProtobufValuePlan | None,
    tuple[ProtobufOutputEmissionGate, ...],
    tuple[ProtobufRecordPlan, ...],
    str,
]:
    length_varint = read_varint(data, payload_start, absolute_end, "length")
    if length_varint.reason is not None or length_varint.value is None:
        return None, (varint_gate(length_varint, tag_path, payload_start),), (), protocol_prefix
    payload_start_offset = length_varint.end_offset
    payload_end_offset = payload_start_offset + length_varint.value
    if payload_end_offset > absolute_end:
        return (
            None,
            (
                ProtobufOutputEmissionGate(
                    code="truncated_length_delimited_payload",
                    field_path=tag_path,
                    byte_offset=payload_start_offset,
                    reason="Length-delimited payload extends beyond the available Protobuf bytes.",
                    evidence_ids=(
                        PROTOBUF_GET_BYTES_SOURCE,
                        PROTOBUF_READ_RECORD_SOURCE,
                        PROTOBUF_TRUNCATED_SOURCE,
                    ),
                ),
            ),
            (),
            protocol_prefix,
        )
    payload = data[payload_start_offset:payload_end_offset]
    classification = classify_length_delimited_payload(
        payload,
        absolute_payload_start=payload_start_offset,
        length_varint=length_varint,
        database_route=database_route,
    )
    nested_records: tuple[ProtobufRecordPlan, ...] = ()
    if classification.kind == "nested_message":
        nested = parse_message(
            data,
            absolute_start=payload_start_offset,
            absolute_end=payload_end_offset,
            prefix=f"{prefix}{field_number}-",
            protocol_prefix=protocol_prefix,
            database=database,
        )
        nested_records = nested.records
    protocol_prefix_after = protocol_prefix
    if classification.kind == "protocol_name" and classification.protocol_prefix is not None:
        protocol_prefix_after = classification.protocol_prefix
    return (
        ProtobufValuePlan(
            payload_start_offset=payload_start_offset,
            payload_end_offset=payload_end_offset,
            value_varint=None,
            raw_payload=payload,
            display_value=display_length_value(classification, payload),
            length_delimited=classification,
            evidence_ids=(
                PROTOBUF_READ_RECORD_SOURCE,
                PROTOBUF_NESTED_SOURCE,
                PROTOBUF_VALUE_FORMAT_SOURCE,
            ),
        ),
        (),
        nested_records,
        protocol_prefix_after,
    )


def classify_length_delimited_payload(
    payload: bytes,
    *,
    absolute_payload_start: int,
    length_varint: ProtobufVarintPlan,
    database_route: ProtobufDatabaseRoutePlan,
) -> ProtobufLengthDelimitedPlan:
    if not payload:
        return length_plan(
            kind="empty",
            payload=payload,
            absolute_payload_start=absolute_payload_start,
            length_varint=length_varint,
            ascii_text="",
            hex_value=None,
            rational_pair=(None, None),
            protocol_prefix=None,
            evidence_ids=(PROTOBUF_READ_RECORD_SOURCE, PROTOBUF_VALUE_FORMAT_SOURCE),
        )
    if payload.endswith(b".proto"):
        protocol_name = payload[:-6].decode("ascii", errors="replace")
        return length_plan(
            kind="protocol_name",
            payload=payload,
            absolute_payload_start=absolute_payload_start,
            length_varint=length_varint,
            ascii_text=payload.decode("ascii", errors="replace"),
            hex_value=None,
            rational_pair=rational_pair(payload),
            protocol_prefix=f"{protocol_name}_",
            evidence_ids=(PROTOBUF_PROCESS_LOOP_SOURCE,),
        )
    if should_descend_as_nested_protobuf(payload, database_route):
        return length_plan(
            kind="nested_message",
            payload=payload,
            absolute_payload_start=absolute_payload_start,
            length_varint=length_varint,
            ascii_text=None,
            hex_value=payload.hex(),
            rational_pair=rational_pair(payload),
            protocol_prefix=None,
            evidence_ids=(PROTOBUF_NESTED_SOURCE, PROTOBUF_IS_PROTOBUF_SOURCE),
        )
    numerator, denominator = rational_pair(payload)
    if is_exiftool_ascii(payload):
        return length_plan(
            kind="ascii_string",
            payload=payload,
            absolute_payload_start=absolute_payload_start,
            length_varint=length_varint,
            ascii_text=payload.decode("ascii", errors="replace"),
            hex_value=None,
            rational_pair=(numerator, denominator),
            protocol_prefix=None,
            evidence_ids=(PROTOBUF_VALUE_FORMAT_SOURCE,),
        )
    if len(payload) % 4:
        return length_plan(
            kind="bytes_hex",
            payload=payload,
            absolute_payload_start=absolute_payload_start,
            length_varint=length_varint,
            ascii_text=None,
            hex_value=payload.hex(),
            rational_pair=(numerator, denominator),
            protocol_prefix=None,
            evidence_ids=(PROTOBUF_VALUE_FORMAT_SOURCE,),
        )
    return length_plan(
        kind="bytes_hex_4byte_groups",
        payload=payload,
        absolute_payload_start=absolute_payload_start,
        length_varint=length_varint,
        ascii_text=None,
        hex_value=" ".join(payload[index : index + 4].hex() for index in range(0, len(payload), 4)),
        rational_pair=(numerator, denominator),
        protocol_prefix=None,
        evidence_ids=(PROTOBUF_VALUE_FORMAT_SOURCE,),
    )


def length_plan(
    *,
    kind: ProtobufLengthDelimitedKind,
    payload: bytes,
    absolute_payload_start: int,
    length_varint: ProtobufVarintPlan,
    ascii_text: str | None,
    hex_value: str | None,
    rational_pair: tuple[int | None, int | None],
    protocol_prefix: str | None,
    evidence_ids: tuple[str, ...],
) -> ProtobufLengthDelimitedPlan:
    numerator, denominator = rational_pair
    return ProtobufLengthDelimitedPlan(
        kind=kind,
        length_varint=length_varint,
        declared_length=len(payload),
        payload_start_offset=absolute_payload_start,
        payload_end_offset=absolute_payload_start + len(payload),
        ascii_text=ascii_text,
        hex_value=hex_value,
        rational_numerator=numerator,
        rational_denominator=denominator,
        protocol_prefix=protocol_prefix,
        evidence_ids=evidence_ids,
    )


def read_varint(
    data: bytes,
    start_offset: int,
    absolute_end: int,
    purpose: Literal["tag", "value", "length"],
) -> ProtobufVarintPlan:
    if start_offset >= absolute_end:
        return ProtobufVarintPlan(
            start_offset=start_offset,
            end_offset=start_offset,
            encoded=b"",
            value=None,
            bit0=None,
            reason=varint_reason(purpose, truncated=True),
            evidence_ids=(PROTOBUF_GET_BYTES_SOURCE, PROTOBUF_VARINT_SOURCE),
        )
    pos = start_offset
    first = data[pos]
    value = first & 0x7F
    bit0 = value & 0x01
    mult = 128
    continuation_groups = 0
    while first & 0x80:
        pos += 1
        if pos >= absolute_end:
            return ProtobufVarintPlan(
                start_offset=start_offset,
                end_offset=pos,
                encoded=data[start_offset:pos],
                value=None,
                bit0=bit0,
                reason=varint_reason(purpose, truncated=True),
                evidence_ids=(PROTOBUF_GET_BYTES_SOURCE, PROTOBUF_VARINT_SOURCE),
            )
        first = data[pos]
        value += (first & 0x7F) * mult
        if not first & 0x80:
            break
        continuation_groups += 1
        if continuation_groups > 32:
            return ProtobufVarintPlan(
                start_offset=start_offset,
                end_offset=pos + 1,
                encoded=data[start_offset : pos + 1],
                value=None,
                bit0=bit0,
                reason=varint_reason(purpose, truncated=False),
                evidence_ids=(PROTOBUF_VARINT_SOURCE,),
            )
        mult *= 128
    return ProtobufVarintPlan(
        start_offset=start_offset,
        end_offset=pos + 1,
        encoded=data[start_offset : pos + 1],
        value=value,
        bit0=bit0,
        reason=None,
        evidence_ids=(PROTOBUF_VARINT_SOURCE,),
    )


def varint_reason(
    purpose: Literal["tag", "value", "length"],
    *,
    truncated: bool,
) -> ProtobufEmissionGateCode:
    if purpose == "tag":
        return "truncated_tag_varint" if truncated else "malformed_tag_varint"
    if purpose == "value":
        return "truncated_value_varint" if truncated else "malformed_value_varint"
    return "truncated_length_varint" if truncated else "malformed_length_varint"


def varint_gate(
    varint: ProtobufVarintPlan,
    field_path: str,
    byte_offset: int,
) -> ProtobufOutputEmissionGate:
    return ProtobufOutputEmissionGate(
        code=varint.reason or "truncated_value_varint",
        field_path=field_path,
        byte_offset=byte_offset,
        reason="Protobuf varint could not be decoded.",
        evidence_ids=varint.evidence_ids,
    )


def build_database_route(
    tag: str,
    wire_type: ProtobufWireType,
    database: Mapping[str, ProtobufFieldDefinition],
) -> ProtobufDatabaseRoutePlan:
    definition = database.get(tag)
    if definition is None:
        return ProtobufDatabaseRoutePlan(
            tag=tag,
            route_kind="unknown_field",
            field_name=tag,
            expected_wire_type=None,
            actual_wire_type=wire_type,
            format_name=None,
            is_protobuf=None,
            preserves_unknown=True,
            evidence_ids=(PROTOBUF_PROCESS_LOOP_SOURCE,),
        )
    return ProtobufDatabaseRoutePlan(
        tag=tag,
        route_kind="known_field",
        field_name=definition.name,
        expected_wire_type=definition.expected_wire_type,
        actual_wire_type=wire_type,
        format_name=definition.format_name,
        is_protobuf=definition.is_protobuf,
        preserves_unknown=definition.is_unknown,
        evidence_ids=(PROTOBUF_PROCESS_LOOP_SOURCE, PROTOBUF_NOTES_SOURCE),
    )


def build_record_actions(
    *,
    tag_path: str,
    record_start: int,
    record_end: int,
    wire_type: ProtobufWireType,
    route: ProtobufDatabaseRoutePlan,
    value: ProtobufValuePlan,
    repeated_index: int,
) -> tuple[ProtobufActionPlan, ...]:
    actions: list[ProtobufActionPlan] = [
        ProtobufActionPlan(
            kind="decode_tag_varint",
            field_path=tag_path,
            byte_range_start=record_start,
            byte_range_end=value.payload_start_offset,
            reason="Decode the protobuf key varint into field number and wire type.",
            evidence_ids=(PROTOBUF_VARINT_SOURCE, PROTOBUF_READ_RECORD_SOURCE),
        )
    ]
    actions.append(wire_action(tag_path, value, wire_type))
    if value.length_delimited is not None:
        length_kind = value.length_delimited.kind
        if length_kind == "protocol_name":
            actions.append(
                ProtobufActionPlan(
                    kind="classify_protocol_name",
                    field_path=tag_path,
                    byte_range_start=value.payload_start_offset,
                    byte_range_end=value.payload_end_offset,
                    reason="Length-delimited payload ending in .proto updates the protocol prefix.",
                    evidence_ids=(PROTOBUF_PROCESS_LOOP_SOURCE,),
                )
            )
        elif length_kind == "nested_message":
            actions.append(
                ProtobufActionPlan(
                    kind="descend_nested_message",
                    field_path=tag_path,
                    byte_range_start=value.payload_start_offset,
                    byte_range_end=value.payload_end_offset,
                    reason="Unknown binary length-delimited payload passes IsProtobuf.",
                    evidence_ids=(PROTOBUF_NESTED_SOURCE, PROTOBUF_IS_PROTOBUF_SOURCE),
                )
            )
        else:
            actions.append(
                ProtobufActionPlan(
                    kind="classify_length_delimited",
                    field_path=tag_path,
                    byte_range_start=value.payload_start_offset,
                    byte_range_end=value.payload_end_offset,
                    reason="Classify length-delimited payload as string or byte data.",
                    evidence_ids=(PROTOBUF_VALUE_FORMAT_SOURCE,),
                )
            )
    preserve_kind: ProtobufActionKind = (
        "preserve_unknown_field" if route.route_kind == "unknown_field" else "preserve_known_field"
    )
    actions.append(
        ProtobufActionPlan(
            kind=preserve_kind,
            field_path=tag_path,
            byte_range_start=record_start,
            byte_range_end=record_end,
            reason="Preserve decoded field bytes because this planner is non-mutating.",
            evidence_ids=(PROTOBUF_PROCESS_LOOP_SOURCE, PROTOBUF_READ_ONLY_SOURCE),
        )
    )
    if repeated_index:
        actions.append(
            ProtobufActionPlan(
                kind="preserve_repeated_field",
                field_path=tag_path,
                byte_range_start=record_start,
                byte_range_end=record_end,
                reason="Repeated Protobuf fields are kept in source order.",
                evidence_ids=(PROTOBUF_PROCESS_LOOP_SOURCE, PROTOBUF_HANDLE_TAG_SOURCE),
            )
        )
    return tuple(actions)


def wire_action(
    tag_path: str,
    value: ProtobufValuePlan,
    wire_type: ProtobufWireType,
) -> ProtobufActionPlan:
    action_by_wire: dict[ProtobufWireType, ProtobufActionKind] = {
        0: "decode_value_varint",
        1: "decode_fixed64",
        2: "decode_length_delimited",
        3: "decode_start_group",
        4: "decode_end_group",
        5: "decode_fixed32",
    }
    return ProtobufActionPlan(
        kind=action_by_wire[wire_type],
        field_path=tag_path,
        byte_range_start=value.payload_start_offset,
        byte_range_end=value.payload_end_offset,
        reason=f"Decode protobuf wire type {wire_type} payload according to ReadRecord.",
        evidence_ids=(PROTOBUF_READ_RECORD_SOURCE,),
    )


def should_descend_as_nested_protobuf(
    payload: bytes,
    database_route: ProtobufDatabaseRoutePlan,
) -> bool:
    if database_route.is_protobuf is True:
        return is_complete_protobuf_message(payload)
    if database_route.route_kind == "unknown_field" and has_non_printable_for_nested_check(payload):
        return is_complete_protobuf_message(payload)
    return False


def is_complete_protobuf_message(payload: bytes) -> bool:
    if not payload:
        return False
    pos = 0
    while pos < len(payload):
        tag = read_varint(payload, pos, len(payload), "tag")
        if tag.value is None or tag.reason is not None:
            return False
        wire_type = tag.value & 0x07
        pos = tag.end_offset
        if wire_type == 0:
            value = read_varint(payload, pos, len(payload), "value")
            if value.value is None or value.reason is not None:
                return False
            pos = value.end_offset
        elif wire_type == 1:
            pos += 8
        elif wire_type == 2:
            length = read_varint(payload, pos, len(payload), "length")
            if length.value is None or length.reason is not None:
                return False
            pos = length.end_offset + length.value
        elif wire_type in (3, 4):
            continue
        elif wire_type == 5:
            pos += 4
        else:
            return False
        if pos > len(payload):
            return False
    return pos == len(payload)


def rational_pair(payload: bytes) -> tuple[int | None, int | None]:
    first = read_varint(payload, 0, len(payload), "value")
    if first.value is None or first.reason is not None:
        return None, None
    second = read_varint(payload, first.end_offset, len(payload), "value")
    if second.value is None or second.reason is not None or second.value == 0:
        return None, None
    if second.end_offset != len(payload):
        return None, None
    return first.value, second.value


def display_varint_value(
    value: int,
    bit0: int | None,
    database_route: ProtobufDatabaseRoutePlan,
) -> str:
    if database_route.format_name == "signed":
        return str(signed_varint(value, bit0))
    if database_route.format_name == "int64s" and value >= PROTOBUF_INT64S_MIN:
        return str(value - PROTOBUF_INT64S_MIN - 4_294_967_296)
    hex_value = f"{value:x}"
    if value >= PROTOBUF_INT64S_MIN:
        signed64 = value - PROTOBUF_INT64S_MIN - 4_294_967_296
        return f"{value} (0x{hex_value}, int64s {signed64})"
    return f"{value} (0x{hex_value}, signed {signed_varint(value, bit0)})"


def signed_varint(value: int, bit0: int | None) -> int:
    if value > PROTOBUF_INT_MAX:
        return -int(value / 2) - 1 if bit0 else int(value / 2)
    return -((value >> 1) + 1) if value & 1 else value >> 1


def display_fixed64_value(payload: bytes) -> str:
    double_value = struct.unpack("<d", payload)[0]
    return f"0x{payload.hex()} (double {double_value})"


def display_fixed32_value(payload: bytes) -> str:
    unsigned_value = int.from_bytes(payload, "little", signed=False)
    signed_suffix = ""
    if payload[3] & 0x80:
        signed_value = int.from_bytes(payload, "little", signed=True)
        signed_suffix = f", int32s {signed_value}"
    float_value = struct.unpack("<f", payload)[0]
    return f"0x{payload.hex()} (int32u {unsigned_value}{signed_suffix}, float {float_value})"


def display_length_value(classification: ProtobufLengthDelimitedPlan, payload: bytes) -> str:
    if classification.ascii_text is not None:
        value = classification.ascii_text
    elif classification.hex_value is not None:
        value = f"0x{classification.hex_value}"
    else:
        value = payload.hex()
    if classification.has_rational_pair:
        value += (
            f" (rational {classification.rational_numerator}/{classification.rational_denominator})"
        )
    return value


def supported_wire_type(wire_type: int) -> ProtobufWireType:
    if wire_type == 0:
        return 0
    if wire_type == 1:
        return 1
    if wire_type == 2:
        return 2
    if wire_type == 3:
        return 3
    if wire_type == 4:
        return 4
    return 5


def has_non_printable_for_nested_check(payload: bytes) -> bool:
    return any(byte < 0x20 or byte > 0x7E for byte in payload)


def is_exiftool_ascii(payload: bytes) -> bool:
    return all(byte in (0x09, 0x0A, 0x0D) or 0x20 <= byte <= 0x7E for byte in payload)


def any_validation_gate(gates: list[ProtobufOutputEmissionGate]) -> bool:
    validation_codes = {
        "truncated_tag_varint",
        "malformed_tag_varint",
        "unsupported_wire_type",
        "truncated_value_varint",
        "malformed_value_varint",
        "truncated_length_varint",
        "malformed_length_varint",
        "truncated_length_delimited_payload",
        "truncated_fixed64_payload",
        "truncated_fixed32_payload",
    }
    return any(gate.code in validation_codes for gate in gates)


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
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
    gates: tuple[ProtobufOutputEmissionGate, ...],
) -> tuple[ProtobufOutputEmissionGate, ...]:
    seen: set[tuple[ProtobufEmissionGateCode, str | None, int | None]] = set()
    unique: list[ProtobufOutputEmissionGate] = []
    for gate in gates:
        key = (gate.code, gate.field_path, gate.byte_offset)
        if key in seen:
            continue
        seen.add(key)
        unique.append(gate)
    return tuple(unique)
