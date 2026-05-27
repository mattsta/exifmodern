"""Source-grounded, non-mutating Apple PLIST transaction planning.

This planner mirrors the read-side behavior modeled by ExifTool's PLIST.pm:
XML PLIST files are traversed by key/value element context, binary PLIST files
are validated through their bplist signature, trailer, offset table, and root
object reference, and extracted metadata is represented as database/tag
responsibilities. It does not rewrite PLIST bytes.
"""

from __future__ import annotations

import base64
import binascii
import math
import re
import struct
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.json_types import JsonArray, JsonObject, JsonValue

BINARY_PLIST_PREFIX = b"bplist0"
BINARY_PLIST_HEADER_SIZE = 8
BINARY_PLIST_TRAILER_SIZE = 32
BINARY_DATA_PREVIEW_LIMIT = 1_000_000
XML_PLIST_KEY_RE = re.compile(r"^[0-9a-f]+$")
VALID_BINARY_INT_SIZES = frozenset((1, 2, 3, 4, 8))
VALID_BINARY_REAL_SIZES = frozenset((4, 8))

type PlistPlanStatus = Literal["planned", "unsupported"]
type PlistEncoding = Literal["xml", "binary", "json", "old_ucs2", "unknown"]
type PlistValueKind = Literal[
    "array",
    "bool",
    "data",
    "date",
    "dict",
    "fill",
    "integer",
    "null",
    "real",
    "set",
    "string",
    "uid",
    "unknown",
]
type PlistActionKind = Literal[
    "validate_xml_signature",
    "validate_binary_signature",
    "parse_binary_trailer",
    "parse_binary_offset_table",
    "parse_root_object",
    "extract_key_value",
    "traverse_array",
    "traverse_dict",
    "preserve_raw_payload",
]
type PlistOutputGateCode = Literal[
    "empty_input",
    "malformed_xml_plist",
    "unsupported_plist_signature",
    "unsupported_json_plist",
    "unsupported_old_ucs2_plist",
    "truncated_binary_trailer",
    "invalid_binary_trailer",
    "unsupported_binary_offset_int_size",
    "unsupported_binary_ref_size",
    "binary_top_object_out_of_range",
    "binary_offset_table_exceeds_input",
    "binary_object_offset_out_of_range",
    "binary_object_parse_failed",
    "non_mutating_plan_requires_explicit_emission",
]
type PlistRewriteGateCode = Literal[
    "plist_writer_not_implemented",
    "xml_raw_layout_preservation_required",
    "binary_offset_table_regeneration_required",
    "binary_trailer_regeneration_required",
]
type BinaryObjectParseFailureCode = Literal[
    "offset_out_of_range",
    "truncated_object",
    "unsupported_marker",
    "unsupported_integer_size",
    "unsupported_real_size",
    "extended_count_not_integer",
    "reference_out_of_range",
    "deep_recursion",
]

PLIST_MAIN_SOURCE = "plist.main"
PLIST_XML_FOUND_SOURCE = "plist.xml_found"
PLIST_XML_DYNAMIC_TAG_SOURCE = "plist.xml_dynamic_tag"
PLIST_BINARY_READ_PROC_SOURCE = "plist.binary_read_proc"
PLIST_BINARY_OBJECT_SOURCE = "plist.binary_object"
PLIST_BINARY_TRAVERSAL_SOURCE = "plist.binary_traversal"
PLIST_BINARY_TRAILER_SOURCE = "plist.binary_trailer"
PLIST_PROCESS_SOURCE = "plist.process"
PLIST_NON_MUTATING_SOURCE = "plist.non_mutating"

PLIST_TRANSACTION_SOURCES = (
    PLIST_MAIN_SOURCE,
    PLIST_XML_FOUND_SOURCE,
    PLIST_XML_DYNAMIC_TAG_SOURCE,
    PLIST_BINARY_READ_PROC_SOURCE,
    PLIST_BINARY_OBJECT_SOURCE,
    PLIST_BINARY_TRAVERSAL_SOURCE,
    PLIST_BINARY_TRAILER_SOURCE,
    PLIST_PROCESS_SOURCE,
)


@dataclass(frozen=True)
class PlistSignaturePlan:
    encoding: PlistEncoding
    prefix: bytes
    is_xml_candidate: bool
    is_binary_candidate: bool
    reason: PlistOutputGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "encoding": self.encoding,
            "is_binary_candidate": self.is_binary_candidate,
            "is_xml_candidate": self.is_xml_candidate,
            "prefix_hex": self.prefix.hex(),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlistBoundaryPlan:
    source_range: tuple[int, int]
    xml_document_range: tuple[int, int] | None
    binary_header_range: tuple[int, int] | None
    binary_object_table_range: tuple[int, int] | None
    binary_offset_table_range: tuple[int, int] | None
    binary_trailer_range: tuple[int, int] | None
    raw_preservation_range: tuple[int, int]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "binary_header_range": json_range(self.binary_header_range),
            "binary_object_table_range": json_range(self.binary_object_table_range),
            "binary_offset_table_range": json_range(self.binary_offset_table_range),
            "binary_trailer_range": json_range(self.binary_trailer_range),
            "raw_preservation_range": json_range(self.raw_preservation_range),
            "source_range": json_range(self.source_range),
            "xml_document_range": json_range(self.xml_document_range),
        }


@dataclass(frozen=True)
class PlistRootObjectPlan:
    encoding: PlistEncoding
    value_kind: PlistValueKind
    binary_object_index: int | None
    binary_object_offset: int | None
    child_count: int | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "binary_object_index": self.binary_object_index,
            "binary_object_offset": self.binary_object_offset,
            "child_count": self.child_count,
            "encoding": self.encoding,
            "value_kind": self.value_kind,
        }


@dataclass(frozen=True)
class PlistValuePlan:
    kind: PlistValueKind
    display_value: JsonValue
    raw_text: str | None
    raw_bytes: bytes | None
    byte_size: int | None
    is_time_value: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_size": self.byte_size,
            "display_value": self.display_value,
            "is_time_value": self.is_time_value,
            "kind": self.kind,
            "raw_bytes_hex": None if self.raw_bytes is None else self.raw_bytes.hex(),
            "raw_text": self.raw_text,
        }


@dataclass(frozen=True)
class PlistDatabaseEntryPlan:
    tag_id: str
    generated_name: str
    path_components: tuple[str, ...]
    value: PlistValuePlan
    list_candidate: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "generated_name": self.generated_name,
            "list_candidate": self.list_candidate,
            "path_components": list(self.path_components),
            "tag_id": self.tag_id,
            "value": self.value.to_json(),
        }


@dataclass(frozen=True)
class BinaryPlistTrailerPlan:
    offset_int_size: int | None
    object_ref_size: int | None
    object_count: int | None
    top_object_index: int | None
    offset_table_offset: int | None
    is_valid: bool
    reason: PlistOutputGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "is_valid": self.is_valid,
            "object_count": self.object_count,
            "object_ref_size": self.object_ref_size,
            "offset_int_size": self.offset_int_size,
            "offset_table_offset": self.offset_table_offset,
            "reason": self.reason,
            "top_object_index": self.top_object_index,
        }


@dataclass(frozen=True)
class BinaryPlistOffsetTablePlan:
    offsets: tuple[int, ...]
    byte_range: tuple[int, int] | None
    is_valid: bool
    reason: PlistOutputGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": json_range(self.byte_range),
            "is_valid": self.is_valid,
            "offsets": list(self.offsets),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlistTraversalPlan:
    kind: PlistValueKind
    path: str
    object_index: int | None
    object_offset: int | None
    child_count: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "child_count": self.child_count,
            "kind": self.kind,
            "object_index": self.object_index,
            "object_offset": self.object_offset,
            "path": self.path,
        }


@dataclass(frozen=True)
class PlistActionPlan:
    kind: PlistActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": json_range(self.byte_range),
            "kind": self.kind,
            "reason": self.reason,
            "target": self.target,
        }


@dataclass(frozen=True)
class PlistOutputEmissionGate:
    code: PlistOutputGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlistRewriteGate:
    code: PlistRewriteGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlistTransactionPlan:
    status: PlistPlanStatus
    source_data: bytes
    signature: PlistSignaturePlan
    boundaries: PlistBoundaryPlan
    root_object: PlistRootObjectPlan
    database_entries: tuple[PlistDatabaseEntryPlan, ...]
    traversal: tuple[PlistTraversalPlan, ...]
    binary_trailer: BinaryPlistTrailerPlan | None
    binary_offset_table: BinaryPlistOffsetTablePlan | None
    actions: tuple[PlistActionPlan, ...]
    rewrite_gates: tuple[PlistRewriteGate, ...]
    output_emission_gates: tuple[PlistOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"PLIST transaction output is gated: {gate_codes}")
        return self.source_data

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "binary_offset_table": (
                None if self.binary_offset_table is None else self.binary_offset_table.to_json()
            ),
            "binary_trailer": (
                None if self.binary_trailer is None else self.binary_trailer.to_json()
            ),
            "boundaries": self.boundaries.to_json(),
            "can_emit_output": self.can_emit_output,
            "database_entries": json_object_array(
                entry.to_json() for entry in self.database_entries
            ),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "rewrite_gates": json_object_array(gate.to_json() for gate in self.rewrite_gates),
            "root_object": self.root_object.to_json(),
            "signature": self.signature.to_json(),
            "status": self.status,
            "traversal": json_object_array(item.to_json() for item in self.traversal),
        }


@dataclass(frozen=True)
class _ParsedBinaryObject:
    kind: PlistValueKind
    value: PlistValuePlan | None
    entries: tuple[PlistDatabaseEntryPlan, ...]
    traversal: tuple[PlistTraversalPlan, ...]
    child_count: int | None


@dataclass(frozen=True)
class _BinaryParseFailure:
    code: BinaryObjectParseFailureCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class _BinaryObjectResult:
    parsed: _ParsedBinaryObject | None
    failure: _BinaryParseFailure | None


@dataclass(frozen=True)
class _BinaryScalarResult:
    value: PlistValuePlan | None
    end_offset: int
    failure: _BinaryParseFailure | None


def build_plist_transaction_plan(
    plist_data: bytes,
    *,
    allow_output_emission: bool = False,
) -> PlistTransactionPlan:
    """Build a source-backed, non-mutating PLIST metadata transaction plan."""

    gates: list[PlistOutputEmissionGate] = []
    signature = build_plist_signature_plan(plist_data)
    if signature.reason is not None:
        gates.append(output_gate_for_signature_reason(signature.reason, signature.evidence_ids))
        _add_non_mutating_gate(gates, allow_output_emission)
        return unsupported_plan(plist_data, signature, gates)

    if signature.encoding == "xml":
        plan = build_xml_plist_transaction_plan(plist_data, signature, gates, allow_output_emission)
    elif signature.encoding == "binary":
        plan = build_binary_plist_transaction_plan(
            plist_data,
            signature,
            gates,
            allow_output_emission,
        )
    else:
        gates.append(
            output_gate_for_signature_reason(
                "unsupported_plist_signature",
                signature.evidence_ids,
            )
        )
        _add_non_mutating_gate(gates, allow_output_emission)
        plan = unsupported_plan(plist_data, signature, gates)
    return plan


plan_plist_transaction = build_plist_transaction_plan


def build_plist_signature_plan(plist_data: bytes) -> PlistSignaturePlan:
    prefix = plist_data[:8]
    if not plist_data:
        return PlistSignaturePlan(
            encoding="unknown",
            prefix=prefix,
            is_xml_candidate=False,
            is_binary_candidate=False,
            reason="empty_input",
            evidence_ids=(PLIST_PROCESS_SOURCE,),
        )
    if plist_data.startswith(b"<"):
        return PlistSignaturePlan(
            encoding="xml",
            prefix=prefix,
            is_xml_candidate=True,
            is_binary_candidate=False,
            reason=None,
            evidence_ids=(PLIST_PROCESS_SOURCE,),
        )
    if plist_data.startswith(BINARY_PLIST_PREFIX):
        return PlistSignaturePlan(
            encoding="binary",
            prefix=prefix,
            is_xml_candidate=False,
            is_binary_candidate=True,
            reason=None,
            evidence_ids=(PLIST_PROCESS_SOURCE,),
        )
    if plist_data.startswith(b'{"'):
        return PlistSignaturePlan(
            encoding="json",
            prefix=prefix,
            is_xml_candidate=False,
            is_binary_candidate=False,
            reason="unsupported_json_plist",
            evidence_ids=(PLIST_PROCESS_SOURCE,),
        )
    if plist_data.startswith(b"\xfe\xff\x00"):
        return PlistSignaturePlan(
            encoding="old_ucs2",
            prefix=prefix,
            is_xml_candidate=False,
            is_binary_candidate=False,
            reason="unsupported_old_ucs2_plist",
            evidence_ids=(PLIST_PROCESS_SOURCE,),
        )
    return PlistSignaturePlan(
        encoding="unknown",
        prefix=prefix,
        is_xml_candidate=False,
        is_binary_candidate=False,
        reason="unsupported_plist_signature",
        evidence_ids=(PLIST_PROCESS_SOURCE,),
    )


def build_xml_plist_transaction_plan(
    plist_data: bytes,
    signature: PlistSignaturePlan,
    gates: list[PlistOutputEmissionGate],
    allow_output_emission: bool,
) -> PlistTransactionPlan:
    try:
        root = ET.fromstring(plist_data)
    except ET.ParseError as exc:
        gates.append(
            PlistOutputEmissionGate(
                code="malformed_xml_plist",
                reason=f"XML parser rejected PLIST input: {exc}.",
                evidence_ids=(PLIST_XML_FOUND_SOURCE,),
            )
        )
        _add_non_mutating_gate(gates, allow_output_emission)
        return unsupported_plan(plist_data, signature, gates)

    root_value = first_xml_value_child(root)
    root_kind = xml_value_kind(root_value)
    database_entries: list[PlistDatabaseEntryPlan] = []
    traversal: list[PlistTraversalPlan] = []
    if root_value is not None:
        collect_xml_value(root_value, (), database_entries, traversal)

    root_object = PlistRootObjectPlan(
        encoding="xml",
        value_kind=root_kind,
        binary_object_index=None,
        binary_object_offset=None,
        child_count=xml_child_count(root_value),
        evidence_ids=(PLIST_XML_FOUND_SOURCE,),
    )
    boundaries = PlistBoundaryPlan(
        source_range=(0, len(plist_data)),
        xml_document_range=(0, len(plist_data)),
        binary_header_range=None,
        binary_object_table_range=None,
        binary_offset_table_range=None,
        binary_trailer_range=None,
        raw_preservation_range=(0, len(plist_data)),
        evidence_ids=(PLIST_PROCESS_SOURCE, PLIST_XML_FOUND_SOURCE),
    )
    actions = build_xml_actions(database_entries, traversal, len(plist_data))
    rewrite_gates = build_rewrite_gates("xml")
    _add_non_mutating_gate(gates, allow_output_emission)
    gate_tuple = unique_output_gates(tuple(gates))
    sources = unique_sources(
        (
            *PLIST_TRANSACTION_SOURCES,
            *(source for entry in database_entries for source in entry.evidence_ids),
            *(source for item in traversal for source in item.evidence_ids),
            *(source for gate in rewrite_gates for source in gate.evidence_ids),
            *(source for gate in gate_tuple for source in gate.evidence_ids),
        )
    )
    return PlistTransactionPlan(
        status="planned" if not structural_gate_present(gate_tuple) else "unsupported",
        source_data=plist_data,
        signature=signature,
        boundaries=boundaries,
        root_object=root_object,
        database_entries=tuple(database_entries),
        traversal=tuple(traversal),
        binary_trailer=None,
        binary_offset_table=None,
        actions=actions,
        rewrite_gates=rewrite_gates,
        output_emission_gates=gate_tuple,
        evidence_ids=sources,
    )


def build_binary_plist_transaction_plan(
    plist_data: bytes,
    signature: PlistSignaturePlan,
    gates: list[PlistOutputEmissionGate],
    allow_output_emission: bool,
) -> PlistTransactionPlan:
    trailer = build_binary_trailer_plan(plist_data)
    if trailer.reason is not None:
        gates.append(output_gate_for_signature_reason(trailer.reason, trailer.evidence_ids))
        _add_non_mutating_gate(gates, allow_output_emission)
        return unsupported_plan(
            plist_data,
            signature,
            gates,
            binary_trailer=trailer,
        )

    offset_table = build_binary_offset_table_plan(plist_data, trailer)
    if offset_table.reason is not None:
        gates.append(
            output_gate_for_signature_reason(
                offset_table.reason,
                offset_table.evidence_ids,
            )
        )
        _add_non_mutating_gate(gates, allow_output_emission)
        return unsupported_plan(
            plist_data,
            signature,
            gates,
            binary_trailer=trailer,
            binary_offset_table=offset_table,
        )

    top_index = trailer.top_object_index
    offsets = offset_table.offsets
    if top_index is None or top_index >= len(offsets):
        gates.append(
            PlistOutputEmissionGate(
                code="binary_top_object_out_of_range",
                reason="Binary PLIST top object index does not identify an offset table entry.",
                evidence_ids=(PLIST_BINARY_TRAILER_SOURCE,),
            )
        )
        _add_non_mutating_gate(gates, allow_output_emission)
        return unsupported_plan(
            plist_data,
            signature,
            gates,
            binary_trailer=trailer,
            binary_offset_table=offset_table,
        )

    parser = _BinaryPlistParser(plist_data, offsets, trailer.object_ref_size or 0)
    parsed_root = parser.parse_object(top_index, None)
    if parsed_root.failure is not None or parsed_root.parsed is None:
        failure_sources = (
            parsed_root.failure.evidence_ids
            if parsed_root.failure is not None
            else (PLIST_BINARY_OBJECT_SOURCE,)
        )
        gates.append(
            PlistOutputEmissionGate(
                code="binary_object_parse_failed",
                reason=(
                    "Binary PLIST root object could not be parsed"
                    if parsed_root.failure is None
                    else parsed_root.failure.reason
                ),
                evidence_ids=failure_sources,
            )
        )
        _add_non_mutating_gate(gates, allow_output_emission)
        return unsupported_plan(
            plist_data,
            signature,
            gates,
            binary_trailer=trailer,
            binary_offset_table=offset_table,
        )

    parsed = parsed_root.parsed
    root_offset = offsets[top_index]
    root_object = PlistRootObjectPlan(
        encoding="binary",
        value_kind=parsed.kind,
        binary_object_index=top_index,
        binary_object_offset=root_offset,
        child_count=parsed.child_count,
        evidence_ids=(PLIST_BINARY_OBJECT_SOURCE, PLIST_BINARY_TRAVERSAL_SOURCE),
    )
    boundaries = build_binary_boundaries(plist_data, offset_table)
    actions = build_binary_actions(parsed.entries, parsed.traversal, boundaries)
    rewrite_gates = build_rewrite_gates("binary")
    _add_non_mutating_gate(gates, allow_output_emission)
    gate_tuple = unique_output_gates(tuple(gates))
    sources = unique_sources(
        (
            *PLIST_TRANSACTION_SOURCES,
            *(source for entry in parsed.entries for source in entry.evidence_ids),
            *(source for item in parsed.traversal for source in item.evidence_ids),
            *(source for gate in rewrite_gates for source in gate.evidence_ids),
            *(source for gate in gate_tuple for source in gate.evidence_ids),
        )
    )
    return PlistTransactionPlan(
        status="planned" if not structural_gate_present(gate_tuple) else "unsupported",
        source_data=plist_data,
        signature=signature,
        boundaries=boundaries,
        root_object=root_object,
        database_entries=parsed.entries,
        traversal=parsed.traversal,
        binary_trailer=trailer,
        binary_offset_table=offset_table,
        actions=actions,
        rewrite_gates=rewrite_gates,
        output_emission_gates=gate_tuple,
        evidence_ids=sources,
    )


class _BinaryPlistParser:
    def __init__(self, plist_data: bytes, offsets: tuple[int, ...], ref_size: int) -> None:
        self._plist_data = plist_data
        self._offsets = offsets
        self._ref_size = ref_size

    def parse_object(self, object_index: int, parent: str | None) -> _BinaryObjectResult:
        return self._parse_object(object_index, parent, 0, ())

    def _parse_object(
        self,
        object_index: int,
        parent: str | None,
        depth: int,
        stack: tuple[int, ...],
    ) -> _BinaryObjectResult:
        if depth > 1000:
            return failed_binary_object(
                "deep_recursion",
                "Possible deep recursion while parsing binary PLIST.",
                (PLIST_BINARY_TRAVERSAL_SOURCE,),
            )
        if object_index >= len(self._offsets):
            return failed_binary_object(
                "reference_out_of_range",
                "Binary PLIST object reference is outside the offset table.",
                (PLIST_BINARY_TRAVERSAL_SOURCE,),
            )
        object_offset = self._offsets[object_index]
        if object_offset >= len(self._plist_data):
            return failed_binary_object(
                "offset_out_of_range",
                "Binary PLIST object offset is outside the source data.",
                (PLIST_BINARY_TRAILER_SOURCE,),
            )
        scalar = self._parse_scalar_at(object_offset)
        if scalar.failure is not None:
            return _BinaryObjectResult(parsed=None, failure=scalar.failure)
        if scalar.value is None:
            return failed_binary_object(
                "unsupported_marker",
                "Binary PLIST marker did not map to a supported value.",
                (PLIST_BINARY_OBJECT_SOURCE,),
            )
        marker = self._plist_data[object_offset]
        object_type = marker >> 4
        object_info = marker & 0x0F
        if object_type in (10, 12, 13):
            return self._parse_collection(
                object_index,
                object_offset,
                object_type,
                object_info,
                parent,
                depth,
                (*stack, object_index),
            )
        entries: tuple[PlistDatabaseEntryPlan, ...] = ()
        if parent:
            entries = (
                build_database_entry(
                    tuple(parent.split("/")),
                    scalar.value,
                    (PLIST_BINARY_TRAVERSAL_SOURCE, PLIST_BINARY_OBJECT_SOURCE),
                ),
            )
        parsed = _ParsedBinaryObject(
            kind=scalar.value.kind,
            value=scalar.value,
            entries=entries,
            traversal=(),
            child_count=None,
        )
        return _BinaryObjectResult(parsed=parsed, failure=None)

    def _parse_collection(
        self,
        object_index: int,
        object_offset: int,
        object_type: int,
        object_info: int,
        parent: str | None,
        depth: int,
        stack: tuple[int, ...],
    ) -> _BinaryObjectResult:
        count_result = self._read_count(object_offset, object_info)
        if count_result.failure is not None:
            return _BinaryObjectResult(parsed=None, failure=count_result.failure)
        count_value = count_result.value
        if count_value is None or not isinstance(count_value.display_value, int):
            return failed_binary_object(
                "extended_count_not_integer",
                "Binary PLIST collection count was not an integer object.",
                (PLIST_BINARY_OBJECT_SOURCE,),
            )
        count = count_value.display_value
        refs_start = count_result.end_offset
        ref_count = count * 2 if object_type == 13 else count
        refs_end = refs_start + ref_count * self._ref_size
        if refs_end > len(self._plist_data):
            return failed_binary_object(
                "truncated_object",
                "Binary PLIST collection reference list extends beyond source data.",
                (PLIST_BINARY_TRAVERSAL_SOURCE,),
            )
        refs = tuple(
            int.from_bytes(
                self._plist_data[
                    refs_start + i * self._ref_size : refs_start + (i + 1) * self._ref_size
                ],
                "big",
            )
            for i in range(ref_count)
        )
        if any(ref >= len(self._offsets) for ref in refs):
            return failed_binary_object(
                "reference_out_of_range",
                "Binary PLIST collection contains a reference outside the offset table.",
                (PLIST_BINARY_TRAVERSAL_SOURCE,),
            )
        traversal_kind = collection_kind(object_type)
        traversal = [
            PlistTraversalPlan(
                kind=traversal_kind,
                path="" if parent is None else parent,
                object_index=object_index,
                object_offset=object_offset,
                child_count=count,
                evidence_ids=(PLIST_BINARY_TRAVERSAL_SOURCE,),
            )
        ]
        entries: list[PlistDatabaseEntryPlan] = []
        if object_type == 13:
            for i in range(count):
                key_result = self._parse_object(refs[i], None, depth + 1, stack)
                if key_result.failure is not None:
                    return key_result
                key = parsed_string_value(key_result.parsed)
                if key is None or key == "":
                    continue
                tag = key if parent is None else f"{parent}/{key}"
                value_result = self._parse_object(refs[i + count], tag, depth + 1, stack)
                if value_result.failure is not None:
                    return value_result
                if value_result.parsed is None:
                    continue
                entries.extend(value_result.parsed.entries)
                traversal.extend(value_result.parsed.traversal)
        else:
            for ref in refs:
                value_result = self._parse_object(ref, parent, depth + 1, stack)
                if value_result.failure is not None:
                    return value_result
                if value_result.parsed is None:
                    continue
                entries.extend(value_result.parsed.entries)
                traversal.extend(value_result.parsed.traversal)
        parsed = _ParsedBinaryObject(
            kind=traversal_kind,
            value=None,
            entries=tuple(entries),
            traversal=tuple(traversal),
            child_count=count,
        )
        return _BinaryObjectResult(parsed=parsed, failure=None)

    def _read_count(self, object_offset: int, object_info: int) -> _BinaryScalarResult:
        if object_info != 0x0F:
            value = PlistValuePlan(
                kind="integer",
                display_value=object_info,
                raw_text=None,
                raw_bytes=None,
                byte_size=None,
                is_time_value=False,
                evidence_ids=(PLIST_BINARY_OBJECT_SOURCE,),
            )
            return _BinaryScalarResult(value=value, end_offset=object_offset + 1, failure=None)
        return self._parse_scalar_at(object_offset + 1)

    def _parse_scalar_at(self, object_offset: int) -> _BinaryScalarResult:
        if object_offset >= len(self._plist_data):
            return failed_binary_scalar(
                object_offset,
                "offset_out_of_range",
                "Binary PLIST object offset is outside source data.",
                (PLIST_BINARY_OBJECT_SOURCE,),
            )
        marker = self._plist_data[object_offset]
        object_type = marker >> 4
        object_info = marker & 0x0F
        payload_offset = object_offset + 1
        if object_type == 0:
            return parse_null_bool_fill(object_info, payload_offset)
        if object_type == 1:
            return self._parse_integer(object_info, payload_offset)
        if object_type in (2, 3):
            return self._parse_real_or_date(object_type, object_info, payload_offset)
        if object_type == 8:
            return self._parse_uid(object_info, payload_offset)
        if object_type in (4, 5, 6):
            count_result = self._read_count(object_offset, object_info)
            if count_result.failure is not None:
                return count_result
            count_value = count_result.value
            if count_value is None or not isinstance(count_value.display_value, int):
                return failed_binary_scalar(
                    object_offset,
                    "extended_count_not_integer",
                    "Binary PLIST scalar count was not an integer object.",
                    (PLIST_BINARY_OBJECT_SOURCE,),
                )
            return self._parse_counted_scalar(
                object_type,
                count_value.display_value,
                count_result.end_offset,
            )
        if object_type in (10, 12, 13):
            value = PlistValuePlan(
                kind=collection_kind(object_type),
                display_value=None,
                raw_text=None,
                raw_bytes=None,
                byte_size=None,
                is_time_value=False,
                evidence_ids=(PLIST_BINARY_TRAVERSAL_SOURCE,),
            )
            return _BinaryScalarResult(value=value, end_offset=payload_offset, failure=None)
        return failed_binary_scalar(
            object_offset,
            "unsupported_marker",
            f"Unsupported binary PLIST object type nibble {object_type}.",
            (PLIST_BINARY_OBJECT_SOURCE,),
        )

    def _parse_integer(self, object_info: int, payload_offset: int) -> _BinaryScalarResult:
        size = 1 << object_info
        if size not in VALID_BINARY_INT_SIZES:
            return failed_binary_scalar(
                payload_offset,
                "unsupported_integer_size",
                f"Unsupported binary PLIST integer size {size}.",
                (PLIST_BINARY_READ_PROC_SOURCE,),
            )
        end = payload_offset + size
        if end > len(self._plist_data):
            return failed_binary_scalar(
                payload_offset,
                "truncated_object",
                "Binary PLIST integer extends beyond source data.",
                (PLIST_BINARY_OBJECT_SOURCE,),
            )
        value = int.from_bytes(self._plist_data[payload_offset:end], "big")
        return _BinaryScalarResult(
            value=PlistValuePlan(
                kind="integer",
                display_value=value,
                raw_text=None,
                raw_bytes=None,
                byte_size=size,
                is_time_value=False,
                evidence_ids=(PLIST_BINARY_READ_PROC_SOURCE, PLIST_BINARY_OBJECT_SOURCE),
            ),
            end_offset=end,
            failure=None,
        )

    def _parse_real_or_date(
        self,
        object_type: int,
        object_info: int,
        payload_offset: int,
    ) -> _BinaryScalarResult:
        size = 1 << object_info
        if size not in VALID_BINARY_REAL_SIZES:
            return failed_binary_scalar(
                payload_offset,
                "unsupported_real_size",
                f"Unsupported binary PLIST real/date size {size}.",
                (PLIST_BINARY_READ_PROC_SOURCE,),
            )
        end = payload_offset + size
        if end > len(self._plist_data):
            return failed_binary_scalar(
                payload_offset,
                "truncated_object",
                "Binary PLIST real/date extends beyond source data.",
                (PLIST_BINARY_OBJECT_SOURCE,),
            )
        raw = self._plist_data[payload_offset:end]
        value = struct.unpack(">f" if size == 4 else ">d", raw)[0]
        if object_type == 3:
            timestamp = value + 11323 * 24 * 3600
            date_value = datetime.fromtimestamp(timestamp, UTC).isoformat()
            return _BinaryScalarResult(
                value=PlistValuePlan(
                    kind="date",
                    display_value=date_value,
                    raw_text=None,
                    raw_bytes=raw,
                    byte_size=size,
                    is_time_value=True,
                    evidence_ids=(PLIST_BINARY_READ_PROC_SOURCE, PLIST_BINARY_OBJECT_SOURCE),
                ),
                end_offset=end,
                failure=None,
            )
        return _BinaryScalarResult(
            value=PlistValuePlan(
                kind="real",
                display_value=value,
                raw_text=None,
                raw_bytes=None,
                byte_size=size,
                is_time_value=False,
                evidence_ids=(PLIST_BINARY_READ_PROC_SOURCE, PLIST_BINARY_OBJECT_SOURCE),
            ),
            end_offset=end,
            failure=None,
        )

    def _parse_uid(self, object_info: int, payload_offset: int) -> _BinaryScalarResult:
        size = object_info + 1
        end = payload_offset + size
        if end > len(self._plist_data):
            return failed_binary_scalar(
                payload_offset,
                "truncated_object",
                "Binary PLIST UID extends beyond source data.",
                (PLIST_BINARY_OBJECT_SOURCE,),
            )
        raw = self._plist_data[payload_offset:end]
        if size in VALID_BINARY_INT_SIZES:
            display_value: JsonValue = int.from_bytes(raw, "big")
        else:
            display_value = "0x" + raw.hex()
        return _BinaryScalarResult(
            value=PlistValuePlan(
                kind="uid",
                display_value=display_value,
                raw_text=None,
                raw_bytes=raw,
                byte_size=size,
                is_time_value=False,
                evidence_ids=(PLIST_BINARY_OBJECT_SOURCE,),
            ),
            end_offset=end,
            failure=None,
        )

    def _parse_counted_scalar(
        self,
        object_type: int,
        count: int,
        payload_offset: int,
    ) -> _BinaryScalarResult:
        byte_count = count * 2 if object_type == 6 else count
        end = payload_offset + byte_count
        if end > len(self._plist_data):
            return failed_binary_scalar(
                payload_offset,
                "truncated_object",
                "Binary PLIST counted scalar extends beyond source data.",
                (PLIST_BINARY_OBJECT_SOURCE,),
            )
        raw = self._plist_data[payload_offset:end]
        if object_type == 4:
            value = PlistValuePlan(
                kind="data",
                display_value=f"Binary data {byte_count} bytes"
                if byte_count >= BINARY_DATA_PREVIEW_LIMIT
                else raw.hex(),
                raw_text=None,
                raw_bytes=raw if byte_count < BINARY_DATA_PREVIEW_LIMIT else None,
                byte_size=byte_count,
                is_time_value=False,
                evidence_ids=(PLIST_BINARY_OBJECT_SOURCE,),
            )
        elif object_type == 5:
            value = PlistValuePlan(
                kind="string",
                display_value=raw.decode("ascii"),
                raw_text=raw.decode("ascii"),
                raw_bytes=None,
                byte_size=byte_count,
                is_time_value=False,
                evidence_ids=(PLIST_BINARY_OBJECT_SOURCE,),
            )
        else:
            decoded = raw.decode("utf-16-be")
            value = PlistValuePlan(
                kind="string",
                display_value=decoded,
                raw_text=decoded,
                raw_bytes=raw,
                byte_size=byte_count,
                is_time_value=False,
                evidence_ids=(PLIST_BINARY_OBJECT_SOURCE,),
            )
        return _BinaryScalarResult(value=value, end_offset=end, failure=None)


def build_binary_trailer_plan(plist_data: bytes) -> BinaryPlistTrailerPlan:
    if len(plist_data) < BINARY_PLIST_HEADER_SIZE + BINARY_PLIST_TRAILER_SIZE:
        return BinaryPlistTrailerPlan(
            offset_int_size=None,
            object_ref_size=None,
            object_count=None,
            top_object_index=None,
            offset_table_offset=None,
            is_valid=False,
            reason="truncated_binary_trailer",
            evidence_ids=(PLIST_BINARY_TRAILER_SOURCE,),
        )
    trailer = plist_data[-BINARY_PLIST_TRAILER_SIZE:]
    offset_int_size = trailer[6]
    object_ref_size = trailer[7]
    object_count = int.from_bytes(trailer[8:16], "big")
    top_object_index = int.from_bytes(trailer[16:24], "big")
    offset_table_offset = int.from_bytes(trailer[24:32], "big")
    if top_object_index >= object_count:
        return BinaryPlistTrailerPlan(
            offset_int_size=offset_int_size,
            object_ref_size=object_ref_size,
            object_count=object_count,
            top_object_index=top_object_index,
            offset_table_offset=offset_table_offset,
            is_valid=False,
            reason="binary_top_object_out_of_range",
            evidence_ids=(PLIST_BINARY_TRAILER_SOURCE,),
        )
    if offset_int_size not in VALID_BINARY_INT_SIZES:
        return BinaryPlistTrailerPlan(
            offset_int_size=offset_int_size,
            object_ref_size=object_ref_size,
            object_count=object_count,
            top_object_index=top_object_index,
            offset_table_offset=offset_table_offset,
            is_valid=False,
            reason="unsupported_binary_offset_int_size",
            evidence_ids=(PLIST_BINARY_TRAILER_SOURCE, PLIST_BINARY_READ_PROC_SOURCE),
        )
    if object_ref_size not in VALID_BINARY_INT_SIZES:
        return BinaryPlistTrailerPlan(
            offset_int_size=offset_int_size,
            object_ref_size=object_ref_size,
            object_count=object_count,
            top_object_index=top_object_index,
            offset_table_offset=offset_table_offset,
            is_valid=False,
            reason="unsupported_binary_ref_size",
            evidence_ids=(PLIST_BINARY_TRAILER_SOURCE, PLIST_BINARY_READ_PROC_SOURCE),
        )
    if object_count == 0 or offset_table_offset < BINARY_PLIST_HEADER_SIZE:
        return BinaryPlistTrailerPlan(
            offset_int_size=offset_int_size,
            object_ref_size=object_ref_size,
            object_count=object_count,
            top_object_index=top_object_index,
            offset_table_offset=offset_table_offset,
            is_valid=False,
            reason="invalid_binary_trailer",
            evidence_ids=(PLIST_BINARY_TRAILER_SOURCE,),
        )
    return BinaryPlistTrailerPlan(
        offset_int_size=offset_int_size,
        object_ref_size=object_ref_size,
        object_count=object_count,
        top_object_index=top_object_index,
        offset_table_offset=offset_table_offset,
        is_valid=True,
        reason=None,
        evidence_ids=(PLIST_BINARY_TRAILER_SOURCE,),
    )


def build_binary_offset_table_plan(
    plist_data: bytes,
    trailer: BinaryPlistTrailerPlan,
) -> BinaryPlistOffsetTablePlan:
    if (
        trailer.offset_int_size is None
        or trailer.object_count is None
        or trailer.offset_table_offset is None
    ):
        return BinaryPlistOffsetTablePlan(
            offsets=(),
            byte_range=None,
            is_valid=False,
            reason="invalid_binary_trailer",
            evidence_ids=(PLIST_BINARY_TRAILER_SOURCE,),
        )
    table_size = trailer.offset_int_size * trailer.object_count
    table_start = trailer.offset_table_offset
    table_end = table_start + table_size
    trailer_start = len(plist_data) - BINARY_PLIST_TRAILER_SIZE
    if table_end > trailer_start:
        return BinaryPlistOffsetTablePlan(
            offsets=(),
            byte_range=(table_start, min(table_end, len(plist_data))),
            is_valid=False,
            reason="binary_offset_table_exceeds_input",
            evidence_ids=(PLIST_BINARY_TRAILER_SOURCE,),
        )
    offsets = tuple(
        int.from_bytes(
            plist_data[
                table_start + i * trailer.offset_int_size : table_start
                + (i + 1) * trailer.offset_int_size
            ],
            "big",
        )
        for i in range(trailer.object_count)
    )
    if any(offset >= table_start for offset in offsets):
        return BinaryPlistOffsetTablePlan(
            offsets=offsets,
            byte_range=(table_start, table_end),
            is_valid=False,
            reason="binary_object_offset_out_of_range",
            evidence_ids=(PLIST_BINARY_TRAILER_SOURCE,),
        )
    return BinaryPlistOffsetTablePlan(
        offsets=offsets,
        byte_range=(table_start, table_end),
        is_valid=True,
        reason=None,
        evidence_ids=(PLIST_BINARY_TRAILER_SOURCE,),
    )


def collect_xml_value(
    element: ET.Element[str],
    path: tuple[str, ...],
    entries: list[PlistDatabaseEntryPlan],
    traversal: list[PlistTraversalPlan],
) -> None:
    kind = xml_value_kind(element)
    if kind == "dict":
        children = xml_value_children(element)
        traversal.append(
            PlistTraversalPlan(
                kind="dict",
                path="/".join(path),
                object_index=None,
                object_offset=None,
                child_count=count_dict_pairs(children),
                evidence_ids=(PLIST_XML_FOUND_SOURCE,),
            )
        )
        index = 0
        while index < len(children):
            key_element = children[index]
            if strip_namespace(key_element.tag) != "key":
                index += 1
                continue
            key = xml_text(key_element)
            value_index = index + 1
            if key == "" or value_index >= len(children):
                index += 1
                continue
            collect_xml_value(children[value_index], (*path, key), entries, traversal)
            index += 2
        return
    if kind == "array":
        children = xml_value_children(element)
        traversal.append(
            PlistTraversalPlan(
                kind="array",
                path="/".join(path),
                object_index=None,
                object_offset=None,
                child_count=len(children),
                evidence_ids=(PLIST_XML_FOUND_SOURCE,),
            )
        )
        for child in children:
            child_kind = xml_value_kind(child)
            child_path = (*path, "") if child_kind == "dict" else path
            collect_xml_value(child, child_path, entries, traversal)
        return
    if path:
        value = xml_value_plan(element)
        entries.append(
            build_database_entry(
                path,
                value,
                (PLIST_XML_FOUND_SOURCE, PLIST_XML_DYNAMIC_TAG_SOURCE),
            )
        )


def xml_value_plan(element: ET.Element[str]) -> PlistValuePlan:
    tag = strip_namespace(element.tag)
    text = xml_text(element)
    if tag == "data":
        stripped = "".join(text.split())
        if stripped and XML_PLIST_KEY_RE.fullmatch(stripped) and len(stripped) % 2 == 0:
            data_value = bytes.fromhex(stripped)
        else:
            try:
                data_value = base64.b64decode(stripped, validate=False)
            except binascii.Error:
                data_value = b""
        return PlistValuePlan(
            kind="data",
            display_value=data_value.hex(),
            raw_text=text,
            raw_bytes=data_value,
            byte_size=len(data_value),
            is_time_value=False,
            evidence_ids=(PLIST_XML_FOUND_SOURCE,),
        )
    if tag == "date":
        return PlistValuePlan(
            kind="date",
            display_value=text,
            raw_text=text,
            raw_bytes=None,
            byte_size=None,
            is_time_value=True,
            evidence_ids=(PLIST_XML_FOUND_SOURCE, PLIST_XML_DYNAMIC_TAG_SOURCE),
        )
    if tag in ("true", "false"):
        return PlistValuePlan(
            kind="bool",
            display_value=tag == "true",
            raw_text=tag,
            raw_bytes=None,
            byte_size=None,
            is_time_value=False,
            evidence_ids=(PLIST_XML_FOUND_SOURCE,),
        )
    if tag == "integer":
        return PlistValuePlan(
            kind="integer",
            display_value=int(text),
            raw_text=text,
            raw_bytes=None,
            byte_size=None,
            is_time_value=False,
            evidence_ids=(PLIST_XML_FOUND_SOURCE,),
        )
    if tag == "real":
        value = float(text)
        return PlistValuePlan(
            kind="real",
            display_value=value if math.isfinite(value) else text,
            raw_text=text,
            raw_bytes=None,
            byte_size=None,
            is_time_value=False,
            evidence_ids=(PLIST_XML_FOUND_SOURCE,),
        )
    return PlistValuePlan(
        kind="string",
        display_value=text,
        raw_text=text,
        raw_bytes=None,
        byte_size=None,
        is_time_value=False,
        evidence_ids=(PLIST_XML_FOUND_SOURCE,),
    )


def build_database_entry(
    path_components: tuple[str, ...],
    value: PlistValuePlan,
    sources: tuple[str, ...],
) -> PlistDatabaseEntryPlan:
    tag_id = "/".join(path_components)
    return PlistDatabaseEntryPlan(
        tag_id=tag_id,
        generated_name=generate_plist_tag_name(tag_id, value.kind),
        path_components=path_components,
        value=value,
        list_candidate=True,
        evidence_ids=unique_sources((*sources, *value.evidence_ids)),
    )


def generate_plist_tag_name(tag_id: str, value_kind: PlistValueKind) -> str:
    name = tag_id.removeprefix("MetaDataList//")
    name = name.removesuffix("//name")
    chars: list[str] = []
    capitalize_next = True
    for char in name:
        if char.isalnum():
            chars.append(char.upper() if capitalize_next else char)
            capitalize_next = False
        else:
            capitalize_next = True
    generated = "".join(chars)
    if len(generated) < 2 or generated[0].isdigit() or generated[0] == "-":
        generated = "Tag" + generated.capitalize()
    if value_kind == "date" and not generated.endswith("Date"):
        return generated
    return generated


def build_xml_actions(
    entries: Sequence[PlistDatabaseEntryPlan],
    traversal: Sequence[PlistTraversalPlan],
    source_size: int,
) -> tuple[PlistActionPlan, ...]:
    actions = [
        PlistActionPlan(
            kind="validate_xml_signature",
            target="<",
            byte_range=(0, 1),
            reason="ProcessPLIST tries XML when source data starts with '<'.",
            evidence_ids=(PLIST_PROCESS_SOURCE,),
        ),
        PlistActionPlan(
            kind="preserve_raw_payload",
            target="xml_document",
            byte_range=(0, source_size),
            reason="XML PLIST planning preserves the full source document.",
            evidence_ids=(PLIST_XML_FOUND_SOURCE, PLIST_NON_MUTATING_SOURCE),
        ),
    ]
    actions.extend(
        PlistActionPlan(
            kind="extract_key_value",
            target=entry.tag_id,
            byte_range=None,
            reason="PLIST tag ID is generated from tracked XML key names.",
            evidence_ids=entry.evidence_ids,
        )
        for entry in entries
    )
    actions.extend(
        PlistActionPlan(
            kind="traverse_array" if item.kind == "array" else "traverse_dict",
            target=item.path,
            byte_range=None,
            reason="XML PLIST container traversal preserves key/value context.",
            evidence_ids=item.evidence_ids,
        )
        for item in traversal
    )
    return tuple(actions)


def build_binary_actions(
    entries: Sequence[PlistDatabaseEntryPlan],
    traversal: Sequence[PlistTraversalPlan],
    boundaries: PlistBoundaryPlan,
) -> tuple[PlistActionPlan, ...]:
    actions = [
        PlistActionPlan(
            kind="validate_binary_signature",
            target=BINARY_PLIST_PREFIX.decode("ascii"),
            byte_range=(0, len(BINARY_PLIST_PREFIX)),
            reason="ProcessPLIST detects binary PLIST data with the bplist0 prefix.",
            evidence_ids=(PLIST_PROCESS_SOURCE,),
        ),
        PlistActionPlan(
            kind="parse_binary_trailer",
            target="trailer",
            byte_range=boundaries.binary_trailer_range,
            reason="ProcessBinaryPLIST reads the final 32 byte trailer.",
            evidence_ids=(PLIST_BINARY_TRAILER_SOURCE,),
        ),
        PlistActionPlan(
            kind="parse_binary_offset_table",
            target="offset_table",
            byte_range=boundaries.binary_offset_table_range,
            reason="ProcessBinaryPLIST reads object offsets using the trailer integer size.",
            evidence_ids=(PLIST_BINARY_TRAILER_SOURCE,),
        ),
        PlistActionPlan(
            kind="parse_root_object",
            target="top_object",
            byte_range=None,
            reason="ProcessBinaryPLIST seeks to the top object offset and extracts it.",
            evidence_ids=(PLIST_BINARY_TRAILER_SOURCE, PLIST_BINARY_OBJECT_SOURCE),
        ),
        PlistActionPlan(
            kind="preserve_raw_payload",
            target="binary_plist",
            byte_range=boundaries.raw_preservation_range,
            reason="Binary PLIST planning preserves all bytes, including object payloads.",
            evidence_ids=(PLIST_BINARY_TRAILER_SOURCE, PLIST_NON_MUTATING_SOURCE),
        ),
    ]
    actions.extend(
        PlistActionPlan(
            kind="extract_key_value",
            target=entry.tag_id,
            byte_range=None,
            reason="Binary dict entries become dynamic PLIST database tag IDs.",
            evidence_ids=entry.evidence_ids,
        )
        for entry in entries
    )
    actions.extend(
        PlistActionPlan(
            kind="traverse_array" if item.kind in ("array", "set") else "traverse_dict",
            target=item.path,
            byte_range=None,
            reason="Binary PLIST references are resolved through the offset table.",
            evidence_ids=item.evidence_ids,
        )
        for item in traversal
    )
    return tuple(actions)


def build_binary_boundaries(
    plist_data: bytes,
    offset_table: BinaryPlistOffsetTablePlan,
) -> PlistBoundaryPlan:
    table_range = offset_table.byte_range
    object_table_range = None
    if table_range is not None:
        object_table_range = (BINARY_PLIST_HEADER_SIZE, table_range[0])
    return PlistBoundaryPlan(
        source_range=(0, len(plist_data)),
        xml_document_range=None,
        binary_header_range=(0, BINARY_PLIST_HEADER_SIZE),
        binary_object_table_range=object_table_range,
        binary_offset_table_range=table_range,
        binary_trailer_range=(len(plist_data) - BINARY_PLIST_TRAILER_SIZE, len(plist_data)),
        raw_preservation_range=(0, len(plist_data)),
        evidence_ids=(PLIST_PROCESS_SOURCE, PLIST_BINARY_TRAILER_SOURCE),
    )


def build_rewrite_gates(encoding: PlistEncoding) -> tuple[PlistRewriteGate, ...]:
    gates = [
        PlistRewriteGate(
            code="plist_writer_not_implemented",
            reason=(
                "ExifTool PLIST.pm is an extractor; this planning surface does not mutate PLIST."
            ),
            evidence_ids=(PLIST_MAIN_SOURCE, PLIST_NON_MUTATING_SOURCE),
        )
    ]
    if encoding == "xml":
        gates.append(
            PlistRewriteGate(
                code="xml_raw_layout_preservation_required",
                reason=(
                    "XML rewrite would need to preserve raw document layout and key/value ordering."
                ),
                evidence_ids=(PLIST_XML_FOUND_SOURCE, PLIST_NON_MUTATING_SOURCE),
            )
        )
    if encoding == "binary":
        gates.extend(
            (
                PlistRewriteGate(
                    code="binary_offset_table_regeneration_required",
                    reason="Binary PLIST mutation requires rebuilding object offsets.",
                    evidence_ids=(PLIST_BINARY_TRAILER_SOURCE, PLIST_NON_MUTATING_SOURCE),
                ),
                PlistRewriteGate(
                    code="binary_trailer_regeneration_required",
                    reason=(
                        "Binary PLIST mutation requires rewriting trailer object counts "
                        "and offsets."
                    ),
                    evidence_ids=(PLIST_BINARY_TRAILER_SOURCE, PLIST_NON_MUTATING_SOURCE),
                ),
            )
        )
    return tuple(gates)


def unsupported_plan(
    plist_data: bytes,
    signature: PlistSignaturePlan,
    gates: Sequence[PlistOutputEmissionGate],
    *,
    binary_trailer: BinaryPlistTrailerPlan | None = None,
    binary_offset_table: BinaryPlistOffsetTablePlan | None = None,
) -> PlistTransactionPlan:
    gate_tuple = unique_output_gates(tuple(gates))
    boundaries = PlistBoundaryPlan(
        source_range=(0, len(plist_data)),
        xml_document_range=(0, len(plist_data)) if signature.encoding == "xml" else None,
        binary_header_range=(0, min(BINARY_PLIST_HEADER_SIZE, len(plist_data)))
        if signature.encoding == "binary"
        else None,
        binary_object_table_range=None,
        binary_offset_table_range=None
        if binary_offset_table is None
        else binary_offset_table.byte_range,
        binary_trailer_range=(max(0, len(plist_data) - BINARY_PLIST_TRAILER_SIZE), len(plist_data))
        if signature.encoding == "binary"
        else None,
        raw_preservation_range=(0, len(plist_data)),
        evidence_ids=(PLIST_PROCESS_SOURCE,),
    )
    root_object = PlistRootObjectPlan(
        encoding=signature.encoding,
        value_kind="unknown",
        binary_object_index=None,
        binary_object_offset=None,
        child_count=None,
        evidence_ids=(PLIST_PROCESS_SOURCE,),
    )
    rewrite_gates = build_rewrite_gates(signature.encoding)
    actions = (
        PlistActionPlan(
            kind="preserve_raw_payload",
            target="unsupported_plist_input",
            byte_range=(0, len(plist_data)),
            reason="Unsupported PLIST input is preserved but not interpreted.",
            evidence_ids=(PLIST_PROCESS_SOURCE, PLIST_NON_MUTATING_SOURCE),
        ),
    )
    sources = unique_sources(
        (
            *PLIST_TRANSACTION_SOURCES,
            *(source for gate in gate_tuple for source in gate.evidence_ids),
            *(source for gate in rewrite_gates for source in gate.evidence_ids),
        )
    )
    return PlistTransactionPlan(
        status="unsupported",
        source_data=plist_data,
        signature=signature,
        boundaries=boundaries,
        root_object=root_object,
        database_entries=(),
        traversal=(),
        binary_trailer=binary_trailer,
        binary_offset_table=binary_offset_table,
        actions=actions,
        rewrite_gates=rewrite_gates,
        output_emission_gates=gate_tuple,
        evidence_ids=sources,
    )


def parse_null_bool_fill(object_info: int, end_offset: int) -> _BinaryScalarResult:
    if object_info == 0x00:
        return _BinaryScalarResult(
            value=PlistValuePlan(
                kind="null",
                display_value="<null>",
                raw_text=None,
                raw_bytes=None,
                byte_size=None,
                is_time_value=False,
                evidence_ids=(PLIST_BINARY_OBJECT_SOURCE,),
            ),
            end_offset=end_offset,
            failure=None,
        )
    if object_info in (0x08, 0x09):
        return _BinaryScalarResult(
            value=PlistValuePlan(
                kind="bool",
                display_value=object_info == 0x08,
                raw_text="True" if object_info == 0x08 else "False",
                raw_bytes=None,
                byte_size=None,
                is_time_value=False,
                evidence_ids=(PLIST_BINARY_OBJECT_SOURCE,),
            ),
            end_offset=end_offset,
            failure=None,
        )
    if object_info == 0x0F:
        return _BinaryScalarResult(
            value=PlistValuePlan(
                kind="fill",
                display_value="<fill>",
                raw_text=None,
                raw_bytes=None,
                byte_size=None,
                is_time_value=False,
                evidence_ids=(PLIST_BINARY_OBJECT_SOURCE,),
            ),
            end_offset=end_offset,
            failure=None,
        )
    return failed_binary_scalar(
        end_offset - 1,
        "unsupported_marker",
        f"Unsupported binary PLIST simple object info nibble {object_info}.",
        (PLIST_BINARY_OBJECT_SOURCE,),
    )


def failed_binary_object(
    code: BinaryObjectParseFailureCode,
    reason: str,
    sources: tuple[str, ...],
) -> _BinaryObjectResult:
    return _BinaryObjectResult(
        parsed=None,
        failure=_BinaryParseFailure(code=code, reason=reason, evidence_ids=sources),
    )


def failed_binary_scalar(
    end_offset: int,
    code: BinaryObjectParseFailureCode,
    reason: str,
    sources: tuple[str, ...],
) -> _BinaryScalarResult:
    return _BinaryScalarResult(
        value=None,
        end_offset=end_offset,
        failure=_BinaryParseFailure(code=code, reason=reason, evidence_ids=sources),
    )


def parsed_string_value(parsed: _ParsedBinaryObject | None) -> str | None:
    if parsed is None or parsed.value is None:
        return None
    if parsed.value.kind != "string" or not isinstance(parsed.value.display_value, str):
        return None
    return parsed.value.display_value


def first_xml_value_child(root: ET.Element[str]) -> ET.Element[str] | None:
    if strip_namespace(root.tag) != "plist":
        return root
    children = xml_value_children(root)
    return children[0] if children else None


def xml_value_children(element: ET.Element[str]) -> list[ET.Element[str]]:
    return [child for child in list(element) if isinstance(child.tag, str)]


def xml_value_kind(element: ET.Element[str] | None) -> PlistValueKind:
    if element is None:
        return "unknown"
    tag = strip_namespace(element.tag)
    if tag == "dict":
        return "dict"
    if tag == "array":
        return "array"
    if tag == "data":
        return "data"
    if tag == "date":
        return "date"
    if tag == "integer":
        return "integer"
    if tag == "real":
        return "real"
    if tag == "string":
        return "string"
    if tag in ("true", "false"):
        return "bool"
    return "unknown"


def xml_child_count(element: ET.Element[str] | None) -> int | None:
    if element is None:
        return None
    kind = xml_value_kind(element)
    children = xml_value_children(element)
    if kind == "dict":
        return count_dict_pairs(children)
    if kind == "array":
        return len(children)
    return None


def count_dict_pairs(children: Sequence[ET.Element[str]]) -> int:
    return sum(1 for child in children if strip_namespace(child.tag) == "key")


def xml_text(element: ET.Element[str]) -> str:
    return "" if element.text is None else element.text.strip()


def strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def collection_kind(object_type: int) -> PlistValueKind:
    if object_type == 10:
        return "array"
    if object_type == 12:
        return "set"
    return "dict"


def output_gate_for_signature_reason(
    code: PlistOutputGateCode,
    sources: tuple[str, ...],
) -> PlistOutputEmissionGate:
    return PlistOutputEmissionGate(
        code=code,
        reason=f"Input does not satisfy ExifTool PLIST processing gate: {code}.",
        evidence_ids=sources,
    )


def _add_non_mutating_gate(
    gates: list[PlistOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        PlistOutputEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="PLIST transaction planning is non-mutating unless output emission is explicit.",
            evidence_ids=(PLIST_NON_MUTATING_SOURCE,),
        )
    )


def structural_gate_present(gates: Sequence[PlistOutputEmissionGate]) -> bool:
    return any(gate.code != "non_mutating_plan_requires_explicit_emission" for gate in gates)


def unique_output_gates(
    gates: tuple[PlistOutputEmissionGate, ...],
) -> tuple[PlistOutputEmissionGate, ...]:
    seen: set[PlistOutputGateCode] = set()
    unique: list[PlistOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def evidence_ids_to_json(sources: tuple[str, ...]) -> JsonArray:
    return [{"evidence_id": source} for source in sources]


def unique_sources(sources: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source in seen:
            continue
        seen.add(source)
        unique.append(source)
    return tuple(unique)


def json_object_array(items: Iterable[JsonObject]) -> JsonArray:
    return [item for item in items]


def json_range(value: tuple[int, int] | None) -> JsonArray | None:
    return None if value is None else [value[0], value[1]]


install_evidence_reference_compat(globals())
