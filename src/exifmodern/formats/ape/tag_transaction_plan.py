"""Source-backed APE tag transaction and database planning.

The planner mirrors ExifTool's APE read-time behavior without mutating files.
It validates leading APE headers and trailing footers, accounts for ID3
coexistence when locating footers, enumerates APE items, routes values by the
ExifTool flag test, preserves duplicate and unknown items, and exposes explicit
gates before identity-only byte emission.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

APE_DESCRIPTOR_SIZE = 32
APE_SIGNATURE = b"APETAGEX"
ID3V1_TRAILER_SIZE = 128
ID3V1_MARKER = b"TAG"
ID3V2_MARKER = b"ID3"
APE_ITEM_VALUE_KIND_MASK = 0x06

type ApeDescriptorKind = Literal["header", "footer", "absent"]
type ApeValueKind = Literal["utf8_text", "binary", "external_locator", "reserved"]
type ApeValueRouteKind = Literal[
    "utf8_text",
    "malformed_utf8_text",
    "binary",
    "cover_art_binary_with_description",
    "external_locator_preserve",
    "reserved_preserve",
]
type ApeItemAction = Literal["parse", "preserve_duplicate", "preserve_unknown"]
type ApeEmissionGateCode = Literal[
    "ape_descriptor_missing",
    "ape_descriptor_size_too_small",
    "ape_descriptor_size_overflow",
    "ape_payload_out_of_bounds",
    "ape_item_header_truncated",
    "ape_item_key_missing_terminator",
    "ape_item_payload_truncated",
    "ape_identity_emission_not_requested",
    "ape_planner_is_non_mutating",
    "ape_rewrite_not_implemented",
]

APE_PM_SOURCE_PATH = "lib/Image/ExifTool/APE.pm"

APE_MAIN_TABLE_SOURCE = "ape.main_table"
APE_DYNAMIC_TAG_SOURCE = "ape.dynamic_tag"
APE_ID3_PRECHECK_SOURCE = "ape.id3_precheck"
APE_DESCRIPTOR_SOURCE = "ape.descriptor"
APE_ID3V1_FOOTER_SOURCE = "ape.id3v1_footer"
APE_ITEM_ENUMERATION_SOURCE = "ape.item_enumeration"
APE_VALUE_ROUTING_SOURCE = "ape.value_routing"
APE_BAD_TRAILER_SOURCE = "ape.bad_trailer"

APE_TAG_TRANSACTION_SOURCES = (
    APE_MAIN_TABLE_SOURCE,
    APE_DYNAMIC_TAG_SOURCE,
    APE_ID3_PRECHECK_SOURCE,
    APE_DESCRIPTOR_SOURCE,
    APE_ID3V1_FOOTER_SOURCE,
    APE_ITEM_ENUMERATION_SOURCE,
    APE_VALUE_ROUTING_SOURCE,
    APE_BAD_TRAILER_SOURCE,
)

_KNOWN_APE_TAGS: dict[str, str] = {
    "Album": "Album",
    "Artist": "Artist",
    "Genre": "Genre",
    "Title": "Title",
    "Track": "Track",
    "Year": "Year",
    "DURATION": "Duration",
    "Tool Version": "ToolVersion",
    "Tool Name": "ToolName",
}


@dataclass(frozen=True)
class ApePlanIssue:
    code: ApeEmissionGateCode
    message: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ApeEmissionGate:
    code: ApeEmissionGateCode
    passed: bool
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ApeId3CoexistencePlan:
    leading_id3v2_present: bool
    trailing_id3v1_present: bool
    footer_search_end_offset: int
    footer_search_skips_trailing_id3v1: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ApeDescriptorValidationPlan:
    kind: ApeDescriptorKind
    offset: int | None
    signature_valid: bool
    version_raw: int | None
    version: float | None
    declared_tag_size: int | None
    declared_item_count: int | None
    flags: int | None
    payload_offset: int | None
    payload_size: int | None
    payload_end_offset: int | None
    issue: ApePlanIssue | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ApeItemDefinitionPlan:
    item_key: str
    tag_name: str
    known: bool
    preview_group: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ApeItemDatabasePlan:
    definitions: tuple[ApeItemDefinitionPlan, ...]
    unknown_items_preserved: bool
    duplicate_items_preserved: bool
    evidence_ids: tuple[str, ...]

    def definition_for(self, item_key: str) -> ApeItemDefinitionPlan | None:
        for definition in self.definitions:
            if definition.item_key == item_key:
                return definition
        return None


@dataclass(frozen=True)
class ApeItemValuePlan:
    kind: ApeValueKind
    route_kind: ApeValueRouteKind
    raw_value: bytes
    utf8_value: str | None
    utf8_valid: bool
    cover_art_description: str | None
    binary_payload_offset: int
    binary_payload_size: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ApeItemPlan:
    index: int
    key: str
    tag_name: str
    header_offset: int
    key_offset: int
    value_offset: int
    value_length: int
    item_end_offset: int
    flags: int
    value_kind: ApeValueKind
    value: ApeItemValuePlan
    known: bool
    duplicate_occurrence: int
    action: ApeItemAction
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ApeRewritePlan:
    requested_item_count: int
    original_payload_size: int | None
    planned_payload_size: int | None
    size_delta: int | None
    blockers: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ApeTagTransactionPlan:
    input_size: int
    id3_coexistence: ApeId3CoexistencePlan
    descriptor: ApeDescriptorValidationPlan
    database: ApeItemDatabasePlan
    items: tuple[ApeItemPlan, ...]
    rewrite_plan: ApeRewritePlan
    output_emission_gates: tuple[ApeEmissionGate, ...]
    output_data: bytes | None
    evidence_ids: tuple[str, ...] = APE_TAG_TRANSACTION_SOURCES

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return self.output_data is not None and all(
            gate.passed for gate in self.output_emission_gates
        )

    @property
    def failed_gates(self) -> tuple[ApeEmissionGate, ...]:
        return tuple(gate for gate in self.output_emission_gates if not gate.passed)

    @property
    def item_keys(self) -> tuple[str, ...]:
        return tuple(item.key for item in self.items)

    @property
    def value_routes(self) -> tuple[ApeValueRouteKind, ...]:
        return tuple(item.value.route_kind for item in self.items)

    def emit(self) -> bytes:
        if self.output_data is None or not self.can_emit_output:
            failed = ", ".join(gate.code for gate in self.failed_gates)
            raise ApeTagTransactionBlocked(f"APE tag transaction output is gated: {failed}")
        return self.output_data


class ApeTagTransactionBlocked(ValueError):
    """Raised when a planned APE tag transaction is not emit-able."""


def build_ape_tag_database_plan(item_keys: tuple[str, ...] = ()) -> ApeItemDatabasePlan:
    definitions: list[ApeItemDefinitionPlan] = [
        ApeItemDefinitionPlan(
            item_key=item_key,
            tag_name=tag_name,
            known=True,
            preview_group=False,
            evidence_ids=(APE_MAIN_TABLE_SOURCE,),
        )
        for item_key, tag_name in _KNOWN_APE_TAGS.items()
    ]
    known_keys = set(_KNOWN_APE_TAGS)
    for item_key in item_keys:
        if item_key in known_keys:
            continue
        known_keys.add(item_key)
        definitions.append(make_dynamic_definition(item_key))
    return ApeItemDatabasePlan(
        definitions=tuple(definitions),
        unknown_items_preserved=True,
        duplicate_items_preserved=True,
        evidence_ids=(APE_MAIN_TABLE_SOURCE, APE_DYNAMIC_TAG_SOURCE),
    )


def build_ape_tag_transaction_plan(
    data: bytes,
    *,
    requested_payload_size: int | None = None,
    requested_item_count: int = 0,
    allow_output_emission: bool = False,
) -> ApeTagTransactionPlan:
    id3 = inspect_id3_coexistence(data)
    descriptor = inspect_ape_descriptor(data, id3)
    items, item_gates = enumerate_ape_items(data, descriptor)
    database = build_ape_tag_database_plan(tuple(item.key for item in items))
    rewrite_plan = plan_ape_rewrite(descriptor, requested_payload_size, requested_item_count)
    gates: list[ApeEmissionGate] = []

    if descriptor.issue is not None:
        gates.append(
            ApeEmissionGate(
                code=descriptor.issue.code,
                passed=False,
                reason=descriptor.issue.message,
                evidence_ids=descriptor.issue.evidence_ids,
            )
        )
    gates.extend(item_gates)
    for blocker in rewrite_plan.blockers:
        gates.append(
            ApeEmissionGate(
                code="ape_rewrite_not_implemented",
                passed=False,
                reason=blocker,
                evidence_ids=rewrite_plan.evidence_ids,
            )
        )
    if not allow_output_emission:
        gates.append(
            ApeEmissionGate(
                code="ape_identity_emission_not_requested",
                passed=False,
                reason="APE planner is non-mutating; opt in to identity-only emission explicitly",
                evidence_ids=(APE_DESCRIPTOR_SOURCE, APE_ITEM_ENUMERATION_SOURCE),
            )
        )
        output_data = None
    elif gates:
        output_data = None
    else:
        gates.append(
            ApeEmissionGate(
                code="ape_planner_is_non_mutating",
                passed=True,
                reason="explicit identity emission returns the original byte sequence only",
                evidence_ids=(APE_DESCRIPTOR_SOURCE, APE_ITEM_ENUMERATION_SOURCE),
            )
        )
        output_data = data

    return ApeTagTransactionPlan(
        input_size=len(data),
        id3_coexistence=id3,
        descriptor=descriptor,
        database=database,
        items=items,
        rewrite_plan=rewrite_plan,
        output_emission_gates=tuple(gates),
        output_data=output_data,
    )


def inspect_id3_coexistence(data: bytes) -> ApeId3CoexistencePlan:
    trailing_id3v1 = len(data) >= ID3V1_TRAILER_SIZE and data[-ID3V1_TRAILER_SIZE:].startswith(
        ID3V1_MARKER
    )
    footer_search_end = len(data) - ID3V1_TRAILER_SIZE if trailing_id3v1 else len(data)
    return ApeId3CoexistencePlan(
        leading_id3v2_present=data.startswith(ID3V2_MARKER),
        trailing_id3v1_present=trailing_id3v1,
        footer_search_end_offset=footer_search_end,
        footer_search_skips_trailing_id3v1=trailing_id3v1,
        evidence_ids=(APE_ID3_PRECHECK_SOURCE, APE_ID3V1_FOOTER_SOURCE),
    )


def inspect_ape_descriptor(
    data: bytes, id3_coexistence: ApeId3CoexistencePlan
) -> ApeDescriptorValidationPlan:
    if len(data) >= APE_DESCRIPTOR_SIZE and data.startswith(APE_SIGNATURE):
        return parse_descriptor(data, 0, "header")

    footer_offset = id3_coexistence.footer_search_end_offset - APE_DESCRIPTOR_SIZE
    if footer_offset >= 0 and data[footer_offset : footer_offset + 8] == APE_SIGNATURE:
        return parse_descriptor(data, footer_offset, "footer")

    return ApeDescriptorValidationPlan(
        kind="absent",
        offset=None,
        signature_valid=False,
        version_raw=None,
        version=None,
        declared_tag_size=None,
        declared_item_count=None,
        flags=None,
        payload_offset=None,
        payload_size=None,
        payload_end_offset=None,
        issue=ApePlanIssue(
            code="ape_descriptor_missing",
            message="source bytes contain neither a leading nor trailing APETAGEX descriptor",
            evidence_ids=(APE_DESCRIPTOR_SOURCE,),
        ),
        evidence_ids=(APE_DESCRIPTOR_SOURCE,),
    )


def parse_descriptor(
    data: bytes, offset: int, kind: ApeDescriptorKind
) -> ApeDescriptorValidationPlan:
    descriptor = data[offset : offset + APE_DESCRIPTOR_SIZE]
    version_raw = int.from_bytes(descriptor[8:12], "little")
    declared_tag_size = int.from_bytes(descriptor[12:16], "little")
    declared_item_count = int.from_bytes(descriptor[16:20], "little")
    flags = int.from_bytes(descriptor[20:24], "little")
    payload_size = declared_tag_size - APE_DESCRIPTOR_SIZE
    payload_offset = offset + APE_DESCRIPTOR_SIZE if kind == "header" else offset - payload_size
    payload_end_offset = payload_offset + payload_size
    issue: ApePlanIssue | None = None

    if declared_tag_size < APE_DESCRIPTOR_SIZE:
        issue = ApePlanIssue(
            code="ape_descriptor_size_too_small",
            message="APE descriptor size is smaller than the 32-byte descriptor",
            evidence_ids=(APE_DESCRIPTOR_SOURCE,),
        )
    elif payload_size & 0x80000000:
        issue = ApePlanIssue(
            code="ape_descriptor_size_overflow",
            message="APE payload size has the high bit set after descriptor subtraction",
            evidence_ids=(APE_DESCRIPTOR_SOURCE,),
        )
    elif payload_offset < 0 or payload_end_offset > len(data):
        issue = ApePlanIssue(
            code="ape_payload_out_of_bounds",
            message="APE payload extent falls outside the source byte sequence",
            evidence_ids=(APE_DESCRIPTOR_SOURCE,),
        )

    return ApeDescriptorValidationPlan(
        kind=kind,
        offset=offset,
        signature_valid=True,
        version_raw=version_raw,
        version=version_raw / 1000,
        declared_tag_size=declared_tag_size,
        declared_item_count=declared_item_count,
        flags=flags,
        payload_offset=payload_offset,
        payload_size=payload_size,
        payload_end_offset=payload_end_offset,
        issue=issue,
        evidence_ids=(APE_DESCRIPTOR_SOURCE,),
    )


def enumerate_ape_items(
    data: bytes, descriptor: ApeDescriptorValidationPlan
) -> tuple[tuple[ApeItemPlan, ...], tuple[ApeEmissionGate, ...]]:
    if (
        descriptor.issue is not None
        or descriptor.payload_offset is None
        or descriptor.payload_size is None
        or descriptor.declared_item_count is None
    ):
        return (), ()

    payload = data[descriptor.payload_offset : descriptor.payload_offset + descriptor.payload_size]
    items: list[ApeItemPlan] = []
    gates: list[ApeEmissionGate] = []
    position = 0
    occurrences: dict[str, int] = {}
    for index in range(descriptor.declared_item_count):
        if position + 8 > len(payload):
            gates.append(item_gate("ape_item_header_truncated", index))
            break
        value_length = int.from_bytes(payload[position : position + 4], "little")
        flags = int.from_bytes(payload[position + 4 : position + 8], "little")
        key_start = position + 8
        key_end = payload.find(b"\x00", key_start)
        if key_end < 0:
            gates.append(item_gate("ape_item_key_missing_terminator", index))
            break
        key_bytes = payload[key_start:key_end]
        key = key_bytes.decode("latin-1")
        value_offset_in_payload = key_end + 1
        value_end = value_offset_in_payload + value_length
        if value_end > len(payload):
            gates.append(item_gate("ape_item_payload_truncated", index))
            break
        raw_value = payload[value_offset_in_payload:value_end]
        occurrence = occurrences.get(key, 0)
        occurrences[key] = occurrence + 1
        definition = known_or_dynamic_definition(key)
        value_kind = value_kind_from_flags(flags)
        value_plan = route_item_value(key, value_kind, raw_value)
        items.append(
            ApeItemPlan(
                index=index,
                key=key,
                tag_name=definition.tag_name,
                header_offset=descriptor.payload_offset + position,
                key_offset=descriptor.payload_offset + key_start,
                value_offset=descriptor.payload_offset + value_offset_in_payload,
                value_length=value_length,
                item_end_offset=descriptor.payload_offset + value_end,
                flags=flags,
                value_kind=value_kind,
                value=value_plan,
                known=definition.known,
                duplicate_occurrence=occurrence,
                action=item_action(definition.known, occurrence),
                evidence_ids=(
                    APE_ITEM_ENUMERATION_SOURCE,
                    APE_VALUE_ROUTING_SOURCE,
                    *definition.evidence_ids,
                ),
            )
        )
        position = value_end
    if len(items) != descriptor.declared_item_count and not gates:
        gates.append(item_gate("ape_item_payload_truncated", len(items)))
    return tuple(items), tuple(gates)


def plan_ape_rewrite(
    descriptor: ApeDescriptorValidationPlan,
    requested_payload_size: int | None,
    requested_item_count: int,
) -> ApeRewritePlan:
    blockers: list[str] = []
    original_payload_size = descriptor.payload_size if descriptor.issue is None else None
    planned_payload_size = requested_payload_size
    size_delta = (
        planned_payload_size - original_payload_size
        if planned_payload_size is not None and original_payload_size is not None
        else None
    )
    if requested_item_count or requested_payload_size is not None:
        blockers.append(
            "APE write requests require a future writer; this planner only records "
            "database and transaction decisions."
        )
        if size_delta is not None and size_delta != 0:
            blockers.append(
                "APE tag size changes require container-aware footer/header relocation and "
                "ID3 coexistence handling before bytes can be rewritten."
            )
    return ApeRewritePlan(
        requested_item_count=requested_item_count,
        original_payload_size=original_payload_size,
        planned_payload_size=planned_payload_size,
        size_delta=size_delta,
        blockers=tuple(blockers),
        evidence_ids=(
            APE_DESCRIPTOR_SOURCE,
            APE_ID3V1_FOOTER_SOURCE,
            APE_ITEM_ENUMERATION_SOURCE,
        ),
    )


def item_gate(code: ApeEmissionGateCode, index: int) -> ApeEmissionGate:
    messages: dict[ApeEmissionGateCode, str] = {
        "ape_item_header_truncated": f"APE item {index} is missing its length/flags header",
        "ape_item_key_missing_terminator": f"APE item {index} key is not NUL-terminated",
        "ape_item_payload_truncated": f"APE item {index} value extends beyond the APE payload",
        "ape_descriptor_missing": "APE descriptor is missing",
        "ape_descriptor_size_too_small": "APE descriptor size is too small",
        "ape_descriptor_size_overflow": "APE descriptor size overflows",
        "ape_payload_out_of_bounds": "APE payload is out of bounds",
        "ape_identity_emission_not_requested": "identity emission was not requested",
        "ape_planner_is_non_mutating": "planner is non-mutating",
        "ape_rewrite_not_implemented": "APE rewrite is not implemented",
    }
    return ApeEmissionGate(
        code=code,
        passed=False,
        reason=messages[code],
        evidence_ids=(APE_ITEM_ENUMERATION_SOURCE, APE_BAD_TRAILER_SOURCE),
    )


def value_kind_from_flags(flags: int) -> ApeValueKind:
    masked = flags & APE_ITEM_VALUE_KIND_MASK
    if masked == 0x02:
        return "binary"
    if masked == 0x04:
        return "external_locator"
    if masked == 0x06:
        return "reserved"
    return "utf8_text"


def route_item_value(key: str, value_kind: ApeValueKind, raw_value: bytes) -> ApeItemValuePlan:
    if value_kind == "binary":
        description, payload_offset = cover_art_description(key, raw_value)
        route_kind: ApeValueRouteKind = (
            "cover_art_binary_with_description" if description is not None else "binary"
        )
        return ApeItemValuePlan(
            kind=value_kind,
            route_kind=route_kind,
            raw_value=raw_value,
            utf8_value=None,
            utf8_valid=False,
            cover_art_description=description,
            binary_payload_offset=payload_offset,
            binary_payload_size=len(raw_value) - payload_offset,
            evidence_ids=(APE_VALUE_ROUTING_SOURCE,),
        )
    if value_kind == "external_locator":
        return non_text_value_plan(value_kind, "external_locator_preserve", raw_value)
    if value_kind == "reserved":
        return non_text_value_plan(value_kind, "reserved_preserve", raw_value)
    try:
        text = raw_value.decode("utf-8")
    except UnicodeDecodeError:
        return ApeItemValuePlan(
            kind=value_kind,
            route_kind="malformed_utf8_text",
            raw_value=raw_value,
            utf8_value=None,
            utf8_valid=False,
            cover_art_description=None,
            binary_payload_offset=0,
            binary_payload_size=0,
            evidence_ids=(APE_VALUE_ROUTING_SOURCE,),
        )
    return ApeItemValuePlan(
        kind=value_kind,
        route_kind="utf8_text",
        raw_value=raw_value,
        utf8_value=text,
        utf8_valid=True,
        cover_art_description=None,
        binary_payload_offset=0,
        binary_payload_size=0,
        evidence_ids=(APE_VALUE_ROUTING_SOURCE,),
    )


def non_text_value_plan(
    value_kind: ApeValueKind, route_kind: ApeValueRouteKind, raw_value: bytes
) -> ApeItemValuePlan:
    return ApeItemValuePlan(
        kind=value_kind,
        route_kind=route_kind,
        raw_value=raw_value,
        utf8_value=None,
        utf8_valid=False,
        cover_art_description=None,
        binary_payload_offset=0,
        binary_payload_size=len(raw_value),
        evidence_ids=(APE_VALUE_ROUTING_SOURCE,),
    )


def cover_art_description(key: str, raw_value: bytes) -> tuple[str | None, int]:
    if not key.startswith("Cover Art"):
        return None, 0
    terminator = raw_value.find(b"\x00")
    if terminator <= 0:
        return None, 0
    description_bytes = raw_value[:terminator]
    if all(0x20 <= byte <= 0x7E for byte in description_bytes):
        return description_bytes.decode("ascii"), terminator + 1
    return None, 0


def item_action(known: bool, duplicate_occurrence: int) -> ApeItemAction:
    if duplicate_occurrence:
        return "preserve_duplicate"
    if not known:
        return "preserve_unknown"
    return "parse"


def known_or_dynamic_definition(item_key: str) -> ApeItemDefinitionPlan:
    tag_name = _KNOWN_APE_TAGS.get(item_key)
    if tag_name is not None:
        return ApeItemDefinitionPlan(
            item_key=item_key,
            tag_name=tag_name,
            known=True,
            preview_group=False,
            evidence_ids=(APE_MAIN_TABLE_SOURCE,),
        )
    return make_dynamic_definition(item_key)


def make_dynamic_definition(item_key: str) -> ApeItemDefinitionPlan:
    return ApeItemDefinitionPlan(
        item_key=item_key,
        tag_name=normalize_dynamic_tag_name(item_key),
        known=False,
        preview_group=item_key.startswith("Cover Art") and not item_key.endswith("Desc"),
        evidence_ids=(APE_DYNAMIC_TAG_SOURCE,),
    )


def normalize_dynamic_tag_name(item_key: str) -> str:
    lowered = item_key.lower()
    output = []
    capitalize_next = True
    previous_alnum = False
    for character in lowered:
        if character.isalnum() or character in ("_", "-"):
            if capitalize_next:
                output.append(character.upper())
            else:
                output.append(character)
            capitalize_next = False
            previous_alnum = character.isalnum()
        else:
            capitalize_next = True
            previous_alnum = False
    normalized = "".join(output)
    while "_" in normalized:
        before, separator, after = normalized.partition("_")
        if not after:
            break
        if (before and before[-1].islower()) or (before and before[-1].isdigit()):
            normalized = before + after[:1].upper() + after[1:]
        else:
            normalized = before + separator + after
            break
    if previous_alnum or normalized:
        return normalized
    return "ApeItem"
