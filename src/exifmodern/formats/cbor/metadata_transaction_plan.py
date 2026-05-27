"""Source-grounded, non-mutating CBOR metadata transaction planning.

The planner mirrors the read-side responsibilities in ExifTool's ``CBOR.pm``:
CBOR major-type decoding is bounded, values are recursively decoded, top-level
maps and arrays are routed through JSON-style database flattening, and raw value
byte ranges are preserved.  It records blockers and rewrite gates, but it does
not emit modified CBOR bytes.
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonObject, JsonValue

type CborMajorTypeName = Literal[
    "unsigned_integer",
    "negative_integer",
    "byte_string",
    "text_string",
    "array",
    "map",
    "tag",
    "simple_or_float",
]
type CborValueKind = Literal[
    "unsigned_integer",
    "negative_integer",
    "byte_string",
    "text_string",
    "array",
    "map",
    "tag",
    "simple",
    "float",
    "break",
]
type CborScalarValue = int | float | str | bytes
type CborMetadataValue = int | float | str | bytes
type CborDecodeConcern = Literal[
    "major_type_decoding_boundaries",
    "unsigned_and_negative_integer_decoding",
    "byte_and_text_string_decoding",
    "array_and_map_recursion",
    "tag_conversion",
    "simple_and_float_decoding",
    "json_database_flattening",
    "indefinite_length_handling",
    "raw_value_preservation",
    "malformed_and_truncation_blockers",
    "non_mutating_emission_gates",
]
type CborEmissionGateCode = Literal[
    "truncated_cbor_data",
    "invalid_cbor_integer_type",
    "truncated_cbor_integer_value",
    "truncated_cbor_string_value",
    "malformed_cbor_text_value",
    "unexpected_list_terminator",
    "missing_indefinite_terminator",
    "invalid_cbor_type7_variant",
    "malformed_cbor_map_key",
    "indefinite_length_rewrite_not_implemented",
    "raw_value_preservation_required",
    "planner_is_non_mutating",
    "cbor_writer_not_implemented",
]

CBOR_EXTENDED_ARGUMENT_SIZES: dict[int, int] = {
    24: 1,
    25: 2,
    26: 4,
    27: 8,
}
CBOR_MAJOR_TYPE_NAMES: dict[int, CborMajorTypeName] = {
    0: "unsigned_integer",
    1: "negative_integer",
    2: "byte_string",
    3: "text_string",
    4: "array",
    5: "map",
    6: "tag",
    7: "simple_or_float",
}
CBOR_TYPE6_NAMES: dict[int, str] = {
    0: "date/time string",
    1: "epoch-based date/time",
    2: "positive bignum",
    3: "negative bignum",
    4: "decimal fraction",
    5: "bigfloat",
    16: "COSE Encrypt0",
    17: "COSE Mac0",
    18: "COSE Sign1",
    19: "COSE Countersignature",
    21: "expected base64url encoding",
    22: "expected base64 encoding",
    23: "expected base16 encoding",
    24: "encoded CBOR data",
    25: "string number",
    26: "serialized Perl",
    27: "serialized code",
    28: "shared value",
    29: "shared value number",
    30: "rational",
    31: "missing array value",
    32: "URI",
    33: "base64url",
    34: "base64",
    35: "regular expression",
    36: "MIME message",
    55799: "CBOR magic number",
}
CBOR_TYPE7_NAMES: dict[int, str] = {
    20: "False",
    21: "True",
    22: "null",
    23: "undef",
}
CBOR_KNOWN_TAG_NAMES: dict[str, str] = {
    "dc:title": "Title",
    "dc:format": "Format",
    "authorName": "AuthorName",
    "authorIdentifier": "AuthorIdentifier",
    "documentID": "DocumentID",
    "instanceID": "InstanceID",
    "thumbnailHash": "ThumbnailHash",
    "thumbnailUrl": "ThumbnailURL",
    "relationship": "Relationship",
}

CBOR_TYPE_TABLE_SOURCE = "cbor.type.table"
CBOR_MAIN_SOURCE = "cbor.main"
CBOR_READ_HEADER_SOURCE = "cbor.read.header"
CBOR_INTEGER_SOURCE = "cbor.integer"
CBOR_STRING_SOURCE = "cbor.string"
CBOR_ARRAY_MAP_SOURCE = "cbor.array.map"
CBOR_TAG_SOURCE = "cbor.tag"
CBOR_SIMPLE_FLOAT_SOURCE = "cbor.simple.float"
CBOR_PROCESS_SOURCE = "cbor.process"
JSON_PROCESS_TAG_SOURCE = "json.process.tag"
JSON_FOUND_TAG_SOURCE = "json.found.tag"


@dataclass(frozen=True)
class CborMajorTypeBoundary:
    major_type: int
    major_type_name: CborMajorTypeName
    additional_info: int
    argument: int
    initial_byte_range: tuple[int, int]
    argument_range: tuple[int, int]
    payload_range: tuple[int, int]
    raw_value_range: tuple[int, int]
    is_indefinite: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "additional_info": self.additional_info,
            "argument": self.argument,
            "argument_range": json_range(self.argument_range),
            "initial_byte_range": json_range(self.initial_byte_range),
            "is_indefinite": self.is_indefinite,
            "major_type": self.major_type,
            "major_type_name": self.major_type_name,
            "payload_range": json_range(self.payload_range),
            "raw_value_range": json_range(self.raw_value_range),
        }


@dataclass(frozen=True)
class CborMapPairPlan:
    index: int
    key: CborValuePlan
    value: CborValuePlan
    key_text: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "index": self.index,
            "key": self.key.to_json(),
            "key_text": self.key_text,
            "value": self.value.to_json(),
        }


@dataclass(frozen=True)
class CborValuePlan:
    kind: CborValueKind
    path: tuple[str, ...]
    boundary: CborMajorTypeBoundary
    scalar_value: CborScalarValue | None
    raw_value: bytes
    raw_payload: bytes
    children: tuple[CborValuePlan, ...]
    map_pairs: tuple[CborMapPairPlan, ...]
    tag_number: int | None
    tag_name: str | None
    evidence_ids: tuple[str, ...]

    @property
    def evidence_id_range(self) -> tuple[int, int]:
        return self.boundary.raw_value_range

    @property
    def payload_range(self) -> tuple[int, int]:
        return self.boundary.payload_range

    def to_json(self) -> JsonObject:
        return {
            "boundary": self.boundary.to_json(),
            "children": [child.to_json() for child in self.children],
            "kind": self.kind,
            "map_pairs": [pair.to_json() for pair in self.map_pairs],
            "path": list(self.path),
            "raw_payload_hex": self.raw_payload.hex(),
            "raw_value_hex": self.raw_value.hex(),
            "scalar_value": scalar_to_json(self.scalar_value),
            "tag_name": self.tag_name,
            "tag_number": self.tag_number,
        }


@dataclass(frozen=True)
class CborMetadataEntryPlan:
    tag_id: str
    tag_name: str
    value: CborMetadataValue
    value_kind: CborValueKind
    key_path: tuple[str, ...]
    evidence_id_range: tuple[int, int]
    raw_value_range: tuple[int, int]
    raw_value: bytes
    is_list_value: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "is_list_value": self.is_list_value,
            "key_path": list(self.key_path),
            "raw_value_hex": self.raw_value.hex(),
            "raw_value_range": json_range(self.raw_value_range),
            "evidence_id_range": json_range(self.evidence_id_range),
            "tag_id": self.tag_id,
            "tag_name": self.tag_name,
            "value": metadata_value_to_json(self.value),
            "value_kind": self.value_kind,
        }


@dataclass(frozen=True)
class CborDecodeResponsibility:
    order: int
    concern: CborDecodeConcern
    description: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "description": self.description,
            "order": self.order,
        }


@dataclass(frozen=True)
class CborEmissionGate:
    code: CborEmissionGateCode
    reason: str
    offset: int | None
    blocks_emission: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocks_emission": self.blocks_emission,
            "code": self.code,
            "offset": self.offset,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CborMetadataTransactionPlan:
    root_values: tuple[CborValuePlan, ...]
    metadata_entries: tuple[CborMetadataEntryPlan, ...]
    responsibilities: tuple[CborDecodeResponsibility, ...]
    output_emission_gates: tuple[CborEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def full_paths(self) -> tuple[str, ...]:
        return tuple(entry.tag_id for entry in self.metadata_entries)

    @property
    def has_indefinite_length_values(self) -> bool:
        return any(value_contains_indefinite(root) for root in self.root_values)

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"CBOR metadata transaction output is gated: {gate_codes}")

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "full_paths": list(self.full_paths),
            "has_indefinite_length_values": self.has_indefinite_length_values,
            "metadata_entries": [entry.to_json() for entry in self.metadata_entries],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "responsibilities": [item.to_json() for item in self.responsibilities],
            "root_values": [value.to_json() for value in self.root_values],
        }


def build_cbor_metadata_transaction_plan(data: bytes) -> CborMetadataTransactionPlan:
    """Build a source-backed, non-mutating CBOR metadata/database plan."""

    root_values, parse_gates = parse_cbor_document(data)
    metadata_entries, flatten_gates = flatten_root_metadata(root_values)
    gates = [*parse_gates, *flatten_gates]
    if any(value_contains_indefinite(root) for root in root_values):
        gates.append(
            CborEmissionGate(
                "indefinite_length_rewrite_not_implemented",
                "Indefinite-length CBOR was decoded, but safe rewrite requires re-chunking policy.",
                None,
                True,
                (CBOR_STRING_SOURCE, CBOR_ARRAY_MAP_SOURCE),
            )
        )
    gates.extend(
        (
            CborEmissionGate(
                "raw_value_preservation_required",
                (
                    "CBOR transaction planning preserves raw value byte ranges before any writer "
                    "can emit."
                ),
                None,
                True,
                (CBOR_READ_HEADER_SOURCE, CBOR_PROCESS_SOURCE),
            ),
            CborEmissionGate(
                "planner_is_non_mutating",
                "CBOR metadata transaction plans record extraction and routing decisions only.",
                None,
                True,
                (CBOR_PROCESS_SOURCE,),
            ),
            CborEmissionGate(
                "cbor_writer_not_implemented",
                (
                    "ExifTool CBOR.pm is a reader; this package has no "
                    "evidence_id-grounded CBOR writer."
                ),
                None,
                True,
                (CBOR_MAIN_SOURCE, CBOR_PROCESS_SOURCE),
            ),
        )
    )
    responsibilities = default_responsibilities()
    evidence_ids = unique_evidence_ids(
        (
            *(
                evidence_id
                for value in root_values
                for evidence_id in collect_value_evidence_ids(value)
            ),
            *(evidence_id for entry in metadata_entries for evidence_id in entry.evidence_ids),
            *(evidence_id for gate in gates for evidence_id in gate.evidence_ids),
            *(evidence_id for item in responsibilities for evidence_id in item.evidence_ids),
        )
    )
    return CborMetadataTransactionPlan(
        root_values=root_values,
        metadata_entries=metadata_entries,
        responsibilities=responsibilities,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=evidence_ids,
    )


def parse_cbor_document(
    data: bytes,
) -> tuple[tuple[CborValuePlan, ...], tuple[CborEmissionGate, ...]]:
    values: list[CborValuePlan] = []
    gates: list[CborEmissionGate] = []
    offset = 0
    index = 0
    while offset < len(data):
        value, next_offset, value_gates = read_cbor_value(data, offset, len(data), (f"Top{index}",))
        gates.extend(value_gates)
        if value is None:
            break
        values.append(value)
        offset = next_offset
        index += 1
        if value.scalar_value == 0 or value.scalar_value == "0":
            break
    return tuple(values), tuple(gates)


def read_cbor_value(
    data: bytes,
    offset: int,
    end: int,
    path: tuple[str, ...],
) -> tuple[CborValuePlan | None, int, tuple[CborEmissionGate, ...]]:
    if offset >= end:
        return (
            None,
            offset,
            (
                CborEmissionGate(
                    "truncated_cbor_data",
                    f"Missing CBOR initial byte at offset {offset}.",
                    offset,
                    True,
                    (CBOR_READ_HEADER_SOURCE,),
                ),
            ),
        )

    initial = data[offset]
    major_type = initial >> 5
    additional_info = initial & 0x1F
    argument_offset = offset + 1
    argument = additional_info
    gates: list[CborEmissionGate] = []

    if additional_info < 24:
        payload_offset = argument_offset
    elif additional_info == 31:
        argument = -1
        payload_offset = argument_offset
    else:
        argument_size = CBOR_EXTENDED_ARGUMENT_SIZES.get(additional_info)
        if argument_size is None:
            boundary = empty_boundary(
                major_type,
                additional_info,
                argument,
                offset,
                argument_offset,
                argument_offset,
            )
            value = make_error_value("simple", path, boundary, data[offset:argument_offset])
            return (
                value,
                argument_offset,
                (
                    CborEmissionGate(
                        "invalid_cbor_integer_type",
                        f"Invalid CBOR integer type {additional_info} at offset {offset}.",
                        offset,
                        True,
                        (CBOR_READ_HEADER_SOURCE,),
                    ),
                ),
            )
        if argument_offset + argument_size > end:
            boundary = empty_boundary(
                major_type,
                additional_info,
                argument,
                offset,
                argument_offset,
                argument_offset,
            )
            value = make_error_value("simple", path, boundary, data[offset:end])
            return (
                value,
                end,
                (
                    CborEmissionGate(
                        "truncated_cbor_integer_value",
                        f"CBOR argument at offset {argument_offset} exceeds input end {end}.",
                        argument_offset,
                        True,
                        (CBOR_READ_HEADER_SOURCE,),
                    ),
                ),
            )
        argument = int.from_bytes(
            data[argument_offset : argument_offset + argument_size],
            "big",
        )
        payload_offset = argument_offset + argument_size

    if major_type == 0:
        return make_scalar_value(
            "unsigned_integer",
            data,
            path,
            offset,
            payload_offset,
            payload_offset,
            major_type,
            additional_info,
            argument,
            argument,
            (CBOR_READ_HEADER_SOURCE, CBOR_INTEGER_SOURCE),
        )
    if major_type == 1:
        return make_scalar_value(
            "negative_integer",
            data,
            path,
            offset,
            payload_offset,
            payload_offset,
            major_type,
            additional_info,
            argument,
            -1 * argument,
            (CBOR_READ_HEADER_SOURCE, CBOR_INTEGER_SOURCE),
        )
    if major_type in (2, 3):
        return read_cbor_string(
            data,
            path,
            offset,
            payload_offset,
            end,
            major_type,
            additional_info,
            argument,
        )
    if major_type in (4, 5):
        return read_cbor_array_or_map(
            data,
            path,
            offset,
            payload_offset,
            end,
            major_type,
            additional_info,
            argument,
        )
    if major_type == 6:
        child, next_offset, child_gates = read_cbor_value(
            data,
            payload_offset,
            end,
            (*path, f"Tag{argument}"),
        )
        gates.extend(child_gates)
        if child is None:
            raw_end = next_offset
            boundary = make_boundary(
                major_type,
                additional_info,
                argument,
                offset,
                payload_offset,
                payload_offset,
                raw_end,
            )
            return (
                CborValuePlan(
                    "tag",
                    path,
                    boundary,
                    None,
                    data[offset:raw_end],
                    data[payload_offset:raw_end],
                    (),
                    (),
                    argument,
                    CBOR_TYPE6_NAMES.get(argument, "unknown"),
                    (CBOR_READ_HEADER_SOURCE, CBOR_TAG_SOURCE),
                ),
                raw_end,
                tuple(gates),
            )
        scalar = converted_tag_scalar(argument, child)
        boundary = make_boundary(
            major_type,
            additional_info,
            argument,
            offset,
            payload_offset,
            payload_offset,
            next_offset,
        )
        return (
            CborValuePlan(
                "tag",
                path,
                boundary,
                scalar,
                data[offset:next_offset],
                data[payload_offset:next_offset],
                (child,),
                (),
                argument,
                CBOR_TYPE6_NAMES.get(argument, "unknown"),
                (CBOR_READ_HEADER_SOURCE, CBOR_TAG_SOURCE, *child.evidence_ids),
            ),
            next_offset,
            tuple(gates),
        )
    if major_type == 7:
        return read_cbor_simple_or_float(
            data,
            path,
            offset,
            payload_offset,
            major_type,
            additional_info,
            argument,
        )

    boundary = empty_boundary(major_type, additional_info, argument, offset, payload_offset, end)
    return (
        make_error_value("simple", path, boundary, data[offset:end]),
        end,
        (
            CborEmissionGate(
                "invalid_cbor_integer_type",
                f"Unknown CBOR major type {major_type} at offset {offset}.",
                offset,
                True,
                (CBOR_READ_HEADER_SOURCE,),
            ),
        ),
    )


def read_cbor_string(
    data: bytes,
    path: tuple[str, ...],
    offset: int,
    payload_offset: int,
    end: int,
    major_type: int,
    additional_info: int,
    argument: int,
) -> tuple[CborValuePlan, int, tuple[CborEmissionGate, ...]]:
    kind: CborValueKind = "byte_string" if major_type == 2 else "text_string"
    if argument < 0:
        chunks: list[CborValuePlan] = []
        gates: list[CborEmissionGate] = []
        cursor = payload_offset
        terminated = False
        while cursor < end:
            child, next_cursor, child_gates = read_cbor_value(
                data,
                cursor,
                end,
                (*path, f"Chunk{len(chunks)}"),
            )
            gates.extend(child_gates)
            if child is None:
                cursor = next_cursor
                break
            cursor = next_cursor
            if child.kind == "break":
                terminated = True
                break
            chunks.append(child)
        if not terminated:
            gates.append(
                CborEmissionGate(
                    "missing_indefinite_terminator",
                    f"Indefinite CBOR {kind} at offset {offset} did not terminate with break.",
                    offset,
                    True,
                    (CBOR_STRING_SOURCE,),
                )
            )
        scalar, scalar_gates = concatenate_indefinite_string(kind, chunks, offset)
        gates.extend(scalar_gates)
        boundary = make_boundary(
            major_type,
            additional_info,
            argument,
            offset,
            payload_offset,
            payload_offset,
            cursor,
        )
        return (
            CborValuePlan(
                kind,
                path,
                boundary,
                scalar,
                data[offset:cursor],
                data[payload_offset:cursor],
                tuple(chunks),
                (),
                None,
                None,
                (CBOR_READ_HEADER_SOURCE, CBOR_STRING_SOURCE),
            ),
            cursor,
            tuple(gates),
        )

    payload_end = payload_offset + argument
    if payload_end > end:
        boundary = make_boundary(
            major_type,
            additional_info,
            argument,
            offset,
            payload_offset,
            payload_offset,
            end,
        )
        return (
            CborValuePlan(
                kind,
                path,
                boundary,
                None,
                data[offset:end],
                data[payload_offset:end],
                (),
                (),
                None,
                None,
                (CBOR_READ_HEADER_SOURCE, CBOR_STRING_SOURCE),
            ),
            end,
            (
                CborEmissionGate(
                    "truncated_cbor_string_value",
                    f"CBOR {kind} at offset {offset} declares {argument} bytes past input end.",
                    payload_offset,
                    True,
                    (CBOR_STRING_SOURCE,),
                ),
            ),
        )

    raw_payload = data[payload_offset:payload_end]
    if major_type == 2:
        definite_scalar: CborScalarValue | None = raw_payload
        definite_gates: tuple[CborEmissionGate, ...] = ()
    else:
        try:
            definite_scalar = raw_payload.decode("utf-8")
            definite_gates = ()
        except UnicodeDecodeError as exc:
            definite_scalar = None
            definite_gates = (
                CborEmissionGate(
                    "malformed_cbor_text_value",
                    f"CBOR text string at offset {offset} is not valid UTF-8: {exc.reason}.",
                    payload_offset,
                    True,
                    (CBOR_STRING_SOURCE,),
                ),
            )
    boundary = make_boundary(
        major_type,
        additional_info,
        argument,
        offset,
        payload_offset,
        payload_offset,
        payload_end,
    )
    return (
        CborValuePlan(
            kind,
            path,
            boundary,
            definite_scalar,
            data[offset:payload_end],
            raw_payload,
            (),
            (),
            None,
            None,
            (CBOR_READ_HEADER_SOURCE, CBOR_STRING_SOURCE),
        ),
        payload_end,
        definite_gates,
    )


def read_cbor_array_or_map(
    data: bytes,
    path: tuple[str, ...],
    offset: int,
    payload_offset: int,
    end: int,
    major_type: int,
    additional_info: int,
    argument: int,
) -> tuple[CborValuePlan, int, tuple[CborEmissionGate, ...]]:
    children: list[CborValuePlan] = []
    gates: list[CborEmissionGate] = []
    cursor = payload_offset
    expected_values = argument if major_type == 4 else argument * 2
    is_indefinite = argument < 0
    terminated = not is_indefinite
    index = 0
    while is_indefinite or expected_values > 0:
        child, next_cursor, child_gates = read_cbor_value(
            data,
            cursor,
            end,
            (*path, str(index)),
        )
        gates.extend(child_gates)
        if child is None:
            cursor = next_cursor
            break
        cursor = next_cursor
        if child.kind == "break":
            if is_indefinite:
                terminated = True
                break
            gates.append(
                CborEmissionGate(
                    "unexpected_list_terminator",
                    f"Definite CBOR array/map at offset {offset} encountered break.",
                    child.evidence_id_range[0],
                    True,
                    (CBOR_ARRAY_MAP_SOURCE, CBOR_SIMPLE_FLOAT_SOURCE),
                )
            )
            break
        children.append(child)
        index += 1
        if not is_indefinite:
            expected_values -= 1
    if not terminated:
        gates.append(
            CborEmissionGate(
                "missing_indefinite_terminator",
                f"Indefinite CBOR array/map at offset {offset} did not terminate with break.",
                offset,
                True,
                (CBOR_ARRAY_MAP_SOURCE,),
            )
        )
    map_pairs: tuple[CborMapPairPlan, ...] = ()
    kind: CborValueKind = "array" if major_type == 4 else "map"
    if major_type == 5:
        pair_list: list[CborMapPairPlan] = []
        for pair_index in range(0, len(children) - 1, 2):
            key = children[pair_index]
            value = children[pair_index + 1]
            key_text, key_gate = cbor_key_text(key)
            if key_gate is not None:
                gates.append(key_gate)
            pair_list.append(
                CborMapPairPlan(
                    pair_index // 2,
                    key,
                    value,
                    key_text,
                    (CBOR_ARRAY_MAP_SOURCE,),
                )
            )
        map_pairs = tuple(pair_list)
    boundary = make_boundary(
        major_type,
        additional_info,
        argument,
        offset,
        payload_offset,
        payload_offset,
        cursor,
    )
    return (
        CborValuePlan(
            kind,
            path,
            boundary,
            None,
            data[offset:cursor],
            data[payload_offset:cursor],
            tuple(children),
            map_pairs,
            None,
            None,
            (CBOR_READ_HEADER_SOURCE, CBOR_ARRAY_MAP_SOURCE),
        ),
        cursor,
        tuple(gates),
    )


def read_cbor_simple_or_float(
    data: bytes,
    path: tuple[str, ...],
    offset: int,
    payload_offset: int,
    major_type: int,
    additional_info: int,
    argument: int,
) -> tuple[CborValuePlan, int, tuple[CborEmissionGate, ...]]:
    boundary = make_boundary(
        major_type,
        additional_info,
        argument,
        offset,
        payload_offset,
        payload_offset,
        payload_offset,
    )
    if additional_info == 31:
        return (
            CborValuePlan(
                "break",
                path,
                boundary,
                None,
                data[offset:payload_offset],
                b"",
                (),
                (),
                None,
                None,
                (CBOR_READ_HEADER_SOURCE, CBOR_SIMPLE_FLOAT_SOURCE),
            ),
            payload_offset,
            (),
        )
    if additional_info < 24:
        return (
            CborValuePlan(
                "simple",
                path,
                boundary,
                CBOR_TYPE7_NAMES.get(argument, "Unknown ()"),
                data[offset:payload_offset],
                b"",
                (),
                (),
                None,
                None,
                (CBOR_READ_HEADER_SOURCE, CBOR_TYPE_TABLE_SOURCE, CBOR_SIMPLE_FLOAT_SOURCE),
            ),
            payload_offset,
            (),
        )
    if additional_info == 25:
        scalar = decode_exiftool_half_float(argument)
        return make_scalar_value(
            "float",
            data,
            path,
            offset,
            payload_offset,
            payload_offset,
            major_type,
            additional_info,
            argument,
            scalar,
            (CBOR_READ_HEADER_SOURCE, CBOR_SIMPLE_FLOAT_SOURCE),
        )
    if additional_info == 26:
        return make_scalar_value(
            "float",
            data,
            path,
            offset,
            payload_offset,
            payload_offset,
            major_type,
            additional_info,
            argument,
            float(struct.unpack(">f", data[payload_offset - 4 : payload_offset])[0]),
            (CBOR_READ_HEADER_SOURCE, CBOR_SIMPLE_FLOAT_SOURCE),
        )
    if additional_info == 27:
        return make_scalar_value(
            "float",
            data,
            path,
            offset,
            payload_offset,
            payload_offset,
            major_type,
            additional_info,
            argument,
            float(struct.unpack(">d", data[payload_offset - 8 : payload_offset])[0]),
            (CBOR_READ_HEADER_SOURCE, CBOR_SIMPLE_FLOAT_SOURCE),
        )
    return (
        CborValuePlan(
            "simple",
            path,
            boundary,
            None,
            data[offset:payload_offset],
            b"",
            (),
            (),
            None,
            None,
            (CBOR_READ_HEADER_SOURCE, CBOR_SIMPLE_FLOAT_SOURCE),
        ),
        payload_offset,
        (
            CborEmissionGate(
                "invalid_cbor_type7_variant",
                f"Invalid CBOR type 7 variant {argument} at offset {offset}.",
                offset,
                True,
                (CBOR_SIMPLE_FLOAT_SOURCE,),
            ),
        ),
    )


def make_scalar_value(
    kind: CborValueKind,
    data: bytes,
    path: tuple[str, ...],
    offset: int,
    payload_offset: int,
    next_offset: int,
    major_type: int,
    additional_info: int,
    argument: int,
    scalar_value: CborScalarValue,
    evidence_ids: tuple[str, ...],
) -> tuple[CborValuePlan, int, tuple[CborEmissionGate, ...]]:
    boundary = make_boundary(
        major_type,
        additional_info,
        argument,
        offset,
        payload_offset,
        payload_offset,
        next_offset,
    )
    return (
        CborValuePlan(
            kind,
            path,
            boundary,
            scalar_value,
            data[offset:next_offset],
            b"",
            (),
            (),
            None,
            None,
            evidence_ids,
        ),
        next_offset,
        (),
    )


def make_boundary(
    major_type: int,
    additional_info: int,
    argument: int,
    offset: int,
    payload_offset: int,
    payload_start: int,
    raw_end: int,
) -> CborMajorTypeBoundary:
    return CborMajorTypeBoundary(
        major_type=major_type,
        major_type_name=CBOR_MAJOR_TYPE_NAMES[major_type],
        additional_info=additional_info,
        argument=argument,
        initial_byte_range=(offset, offset + 1),
        argument_range=(offset + 1, payload_offset),
        payload_range=(payload_start, raw_end),
        raw_value_range=(offset, raw_end),
        is_indefinite=additional_info == 31,
        evidence_ids=(CBOR_READ_HEADER_SOURCE,),
    )


def empty_boundary(
    major_type: int,
    additional_info: int,
    argument: int,
    offset: int,
    payload_offset: int,
    raw_end: int,
) -> CborMajorTypeBoundary:
    name = CBOR_MAJOR_TYPE_NAMES.get(major_type, "simple_or_float")
    return CborMajorTypeBoundary(
        major_type=major_type,
        major_type_name=name,
        additional_info=additional_info,
        argument=argument,
        initial_byte_range=(offset, min(offset + 1, raw_end)),
        argument_range=(min(offset + 1, raw_end), payload_offset),
        payload_range=(payload_offset, raw_end),
        raw_value_range=(offset, raw_end),
        is_indefinite=additional_info == 31,
        evidence_ids=(CBOR_READ_HEADER_SOURCE,),
    )


def make_error_value(
    kind: CborValueKind,
    path: tuple[str, ...],
    boundary: CborMajorTypeBoundary,
    raw_value: bytes,
) -> CborValuePlan:
    return CborValuePlan(
        kind,
        path,
        boundary,
        None,
        raw_value,
        b"",
        (),
        (),
        None,
        None,
        (CBOR_READ_HEADER_SOURCE,),
    )


def converted_tag_scalar(tag_number: int, child: CborValuePlan) -> CborScalarValue | None:
    if tag_number in (2, 3) and isinstance(child.scalar_value, bytes):
        big = 0
        for item in child.scalar_value:
            big = 256 * big + item
        return big if tag_number == 2 else -big
    if tag_number in (4, 5) and len(child.children) == 2:
        exponent = child.children[0].scalar_value
        mantissa = child.children[1].scalar_value
        if isinstance(exponent, int) and isinstance(mantissa, int):
            base = 10 if tag_number == 4 else 2
            factor = integer_power(base, abs(exponent))
            if exponent >= 0:
                return mantissa * factor
            return float(mantissa) / float(factor)
    if child.scalar_value is not None:
        return child.scalar_value
    return None


def integer_power(base: int, exponent: int) -> int:
    value = 1
    for _ in range(exponent):
        value *= base
    return value


def decode_exiftool_half_float(argument: int) -> float | str:
    exponent = (argument >> 10) & 0x1F
    mantissa = argument & 0x3FF
    if exponent == 0:
        value = math.inf if mantissa == 0 else float(mantissa ** (-24))
        return -value if argument & 0x8000 else value
    if exponent != 31:
        value = float((mantissa + 1024) ** (exponent - 25))
        return -value if argument & 0x8000 else value
    return "<inf>" if mantissa == 0 else "<nan>"


def concatenate_indefinite_string(
    kind: CborValueKind,
    chunks: list[CborValuePlan],
    offset: int,
) -> tuple[CborScalarValue | None, tuple[CborEmissionGate, ...]]:
    gates: list[CborEmissionGate] = []
    if kind == "byte_string":
        parts: list[bytes] = []
        for chunk in chunks:
            if isinstance(chunk.scalar_value, bytes):
                parts.append(chunk.scalar_value)
            else:
                gates.append(indefinite_chunk_gate(kind, offset, chunk))
        return b"".join(parts), tuple(gates)
    parts_text: list[str] = []
    for chunk in chunks:
        if isinstance(chunk.scalar_value, str):
            parts_text.append(chunk.scalar_value)
        else:
            gates.append(indefinite_chunk_gate(kind, offset, chunk))
    return "".join(parts_text), tuple(gates)


def indefinite_chunk_gate(
    kind: CborValueKind,
    offset: int,
    chunk: CborValuePlan,
) -> CborEmissionGate:
    return CborEmissionGate(
        "malformed_cbor_text_value",
        f"Indefinite CBOR {kind} at offset {offset} contains non-string chunk {chunk.kind}.",
        chunk.evidence_id_range[0],
        True,
        (CBOR_STRING_SOURCE,),
    )


def flatten_root_metadata(
    roots: tuple[CborValuePlan, ...],
) -> tuple[tuple[CborMetadataEntryPlan, ...], tuple[CborEmissionGate, ...]]:
    entries: list[CborMetadataEntryPlan] = []
    gates: list[CborEmissionGate] = []
    for root in roots:
        if root.kind == "map":
            for pair in root.map_pairs:
                entries.extend(
                    flatten_process_tag(pair.key_text, pair.value, (pair.key_text,), False)
                )
        elif root.kind == "array":
            for index, child in enumerate(root.children):
                if child.kind == "break":
                    continue
                entries.extend(flatten_process_tag(f"Item{index}", child, (f"Item{index}",), False))
    return tuple(entries), tuple(gates)


def flatten_process_tag(
    tag: str,
    value: CborValuePlan,
    key_path: tuple[str, ...],
    is_list_value: bool,
) -> tuple[CborMetadataEntryPlan, ...]:
    if value.kind == "tag" and value.scalar_value is None and value.children:
        return flatten_process_tag(tag, value.children[0], key_path, is_list_value)
    if value.kind == "map":
        entries: list[CborMetadataEntryPlan] = []
        for pair in value.map_pairs:
            nested_tag = exiftool_nested_tag(tag, pair.key_text)
            entries.extend(
                flatten_process_tag(
                    nested_tag,
                    pair.value,
                    (*key_path, pair.key_text),
                    is_list_value,
                )
            )
        return tuple(entries)
    if value.kind == "array":
        entries = []
        for child in value.children:
            if child.kind == "break":
                continue
            entries.extend(flatten_process_tag(tag, child, key_path, True))
        return tuple(entries)
    if value.scalar_value is None:
        return ()
    return (
        CborMetadataEntryPlan(
            tag_id=tag,
            tag_name=database_tag_name(tag),
            value=value.scalar_value,
            value_kind=value.kind,
            key_path=key_path,
            evidence_id_range=value.evidence_id_range,
            raw_value_range=value.evidence_id_range,
            raw_value=value.raw_value,
            is_list_value=is_list_value,
            evidence_ids=(
                CBOR_PROCESS_SOURCE,
                JSON_PROCESS_TAG_SOURCE,
                JSON_FOUND_TAG_SOURCE,
                *value.evidence_ids,
            ),
        ),
    )


def cbor_key_text(value: CborValuePlan) -> tuple[str, CborEmissionGate | None]:
    if isinstance(value.scalar_value, str):
        return value.scalar_value, None
    if isinstance(value.scalar_value, int):
        return str(value.scalar_value), None
    if isinstance(value.scalar_value, float):
        return str(value.scalar_value), None
    if isinstance(value.scalar_value, bytes):
        return value.scalar_value.hex(), None
    return (
        f"<{value.kind}>",
        CborEmissionGate(
            "malformed_cbor_map_key",
            f"CBOR map key at offset {value.evidence_id_range[0]} is not a scalar key.",
            value.evidence_id_range[0],
            True,
            (CBOR_ARRAY_MAP_SOURCE, JSON_PROCESS_TAG_SOURCE),
        ),
    )


def exiftool_nested_tag(parent: str, child: str) -> str:
    suffix = child[:1].upper() + child[1:]
    separator = "_" if parent[-1:].isdigit() and child[:1].isdigit() else ""
    tag = f"{parent}{separator}{suffix}"
    return re.sub(
        r"([^a-zA-Z])([a-z])",
        lambda match: f"{match.group(1)}{match.group(2).upper()}",
        tag,
    )


def database_tag_name(tag: str) -> str:
    known = CBOR_KNOWN_TAG_NAMES.get(tag)
    if known is not None:
        return known
    normalized = tag.replace(":", "_")
    if normalized.lower().startswith("c2pa"):
        normalized = "C2PA" + normalized[4:]
    words = re.split(r"[^0-9A-Za-z]+", normalized)
    name = "".join(word[:1].upper() + word[1:] for word in words if word)
    return name or "CBORValue"


def value_contains_indefinite(value: CborValuePlan) -> bool:
    return (
        value.boundary.is_indefinite
        or any(value_contains_indefinite(child) for child in value.children)
        or any(
            value_contains_indefinite(pair.key) or value_contains_indefinite(pair.value)
            for pair in value.map_pairs
        )
    )


def collect_value_evidence_ids(value: CborValuePlan) -> tuple[str, ...]:
    return unique_evidence_ids(
        (
            *value.evidence_ids,
            *value.boundary.evidence_ids,
            *(
                evidence_id
                for child in value.children
                for evidence_id in collect_value_evidence_ids(child)
            ),
            *(evidence_id for pair in value.map_pairs for evidence_id in pair.evidence_ids),
            *(
                evidence_id
                for pair in value.map_pairs
                for evidence_id in collect_value_evidence_ids(pair.key)
            ),
            *(
                evidence_id
                for pair in value.map_pairs
                for evidence_id in collect_value_evidence_ids(pair.value)
            ),
        )
    )


def default_responsibilities() -> tuple[CborDecodeResponsibility, ...]:
    return (
        CborDecodeResponsibility(
            1,
            "major_type_decoding_boundaries",
            "Split the CBOR initial byte into major type and additional info, then bound args.",
            (CBOR_READ_HEADER_SOURCE,),
        ),
        CborDecodeResponsibility(
            2,
            "unsigned_and_negative_integer_decoding",
            "Plan integers as CBOR.pm does, including negative values as -1 * argument.",
            (CBOR_INTEGER_SOURCE,),
        ),
        CborDecodeResponsibility(
            3,
            "byte_and_text_string_decoding",
            "Preserve byte strings raw and decode text strings at the CBOR UTF-8 boundary.",
            (CBOR_STRING_SOURCE,),
        ),
        CborDecodeResponsibility(
            4,
            "array_and_map_recursion",
            "Recurse arrays and maps, preserving ordered map key/value pairs.",
            (CBOR_ARRAY_MAP_SOURCE,),
        ),
        CborDecodeResponsibility(
            5,
            "tag_conversion",
            "Record optional tag responsibilities and selected ExifTool conversions.",
            (CBOR_TYPE_TABLE_SOURCE, CBOR_TAG_SOURCE),
        ),
        CborDecodeResponsibility(
            6,
            "simple_and_float_decoding",
            "Decode break, simple constants, float, and double type-7 values.",
            (CBOR_TYPE_TABLE_SOURCE, CBOR_SIMPLE_FLOAT_SOURCE),
        ),
        CborDecodeResponsibility(
            7,
            "json_database_flattening",
            "Flatten top-level CBOR map/array values through JSON ProcessTag semantics.",
            (CBOR_PROCESS_SOURCE, JSON_PROCESS_TAG_SOURCE, JSON_FOUND_TAG_SOURCE),
        ),
        CborDecodeResponsibility(
            8,
            "indefinite_length_handling",
            "Decode indefinite strings, arrays, and maps through break terminators; gate rewrite.",
            (CBOR_STRING_SOURCE, CBOR_ARRAY_MAP_SOURCE, CBOR_SIMPLE_FLOAT_SOURCE),
        ),
        CborDecodeResponsibility(
            9,
            "raw_value_preservation",
            (
                "Expose raw evidence_id ranges for every decoded value before any byte "
                "emission is allowed."
            ),
            (CBOR_READ_HEADER_SOURCE, CBOR_PROCESS_SOURCE),
        ),
        CborDecodeResponsibility(
            10,
            "malformed_and_truncation_blockers",
            "Record truncated arguments, strings, missing breaks, bad keys, and invalid variants.",
            (CBOR_READ_HEADER_SOURCE, CBOR_STRING_SOURCE, CBOR_SIMPLE_FLOAT_SOURCE),
        ),
        CborDecodeResponsibility(
            11,
            "non_mutating_emission_gates",
            "Keep output emission blocked because the evidence_id oracle only reads CBOR metadata.",
            (CBOR_MAIN_SOURCE, CBOR_PROCESS_SOURCE),
        ),
    )


def evidence_ids_to_json(evidence_ids: tuple[str, ...]) -> list[JsonValue]:
    return list(evidence_ids)


def json_range(value: tuple[int, int]) -> list[JsonValue]:
    return [value[0], value[1]]


def scalar_to_json(value: CborScalarValue | None) -> JsonValue:
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex(), "byte_length": len(value)}
    return value


def metadata_value_to_json(value: CborMetadataValue) -> JsonValue:
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex(), "byte_length": len(value)}
    return value


def unique_evidence_ids(evidence_ids: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for evidence_id in evidence_ids:
        if evidence_id not in seen:
            seen.add(evidence_id)
            unique.append(evidence_id)
    return tuple(unique)


def unique_gates(gates: tuple[CborEmissionGate, ...]) -> tuple[CborEmissionGate, ...]:
    seen: set[tuple[CborEmissionGateCode, int | None, str]] = set()
    unique: list[CborEmissionGate] = []
    for gate in gates:
        key = (gate.code, gate.offset, gate.reason)
        if key not in seen:
            seen.add(key)
            unique.append(gate)
    return tuple(unique)
