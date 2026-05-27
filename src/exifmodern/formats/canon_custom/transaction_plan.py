"""Source-grounded Canon custom-functions transaction planning.

ExifTool decodes Canon custom functions with two payload shapes in
``lib/Image/ExifTool/CanonCustom.pm``.  Legacy tables use packed int8 values
inside 16-bit entries, while ``Functions2`` uses grouped int32 records selected
from Canon maker-note tag ``0x99``.  This module plans routing, selected setting
ownership, unknown preservation, and rewrite gates without mutating payloads.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from exifmodern.write_plan import EvidenceAnchor

CANON_CUSTOM_SOURCE_PATH = "lib/Image/ExifTool/CanonCustom.pm"
CANON_SOURCE_PATH = "lib/Image/ExifTool/Canon.pm"

type CanonCustomByteOrder = Literal["little", "big"]
type CanonCustomPayloadKind = Literal["canon_custom", "canon_custom2"]
type CanonCustomPlanStatus = Literal["planned", "blocked", "unsupported"]
type CanonCustomTableName = Literal["Functions1D", "Functions5D", "Functions20D", "Functions2"]
type CanonCustomRouteCode = Literal[
    "legacy_model_table",
    "makernote_custom_functions2",
    "explicit_table",
]
type CanonCustomAction = Literal[
    "route_known_setting",
    "route_conditional_setting",
    "preserve_unknown_tag",
    "preserve_unknown_byte",
]
type CanonCustomResponsibility = Literal[
    "known_writable_setting",
    "known_conditional_setting",
    "unknown_preserved_tag",
    "unknown_preserved_byte",
]
type CanonCustomGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "unsupported_canon_custom_rewrite",
    "unknown_canon_custom_rewrite",
]
type CanonCustomBlockerCode = Literal[
    "unsupported_canon_custom_table_route",
    "invalid_canon_custom_data",
    "truncated_canon_custom_group",
    "corrupted_canon_custom_data",
]
type CanonCustomPrintKind = Literal[
    "raw_values",
    "disable_enable",
    "off_on",
    "iso_speed_range",
    "timer_length3",
    "timer_length4",
    "functions2_focusing_screen",
    "functions5d_focusing_screen",
    "functions5d_long_exposure_noise_reduction",
    "functions20d_long_exposure_noise_reduction",
]


def _custom_source(
    line_start: int,
    line_end: int,
    symbol: str,
    evidence: str,
) -> EvidenceAnchor:
    return EvidenceAnchor(CANON_CUSTOM_SOURCE_PATH, line_start, line_end, symbol, evidence)


def _canon_source(
    line_start: int,
    line_end: int,
    symbol: str,
    evidence: str,
) -> EvidenceAnchor:
    return EvidenceAnchor(CANON_SOURCE_PATH, line_start, line_end, symbol, evidence)


CANON_CUSTOM_FUNCTIONS2_ROUTE_SOURCE = _canon_source(
    1883,
    1888,
    "Canon MakerNotes CustomFunctions2",
    "Canon.pm routes maker-note tag 0x99 to CanonCustom::Functions2.",
)
CANON_CUSTOM_TABLE_SOURCE = _custom_source(
    35,
    49,
    "Functions1D",
    "Functions1D is a legacy int8u custom-functions table for 1D models before Mark III.",
)
CANON_CUSTOM_5D_SOURCE = _custom_source(
    225,
    263,
    "Functions5D",
    "Functions5D is a legacy int8u custom-functions table with 5D-specific values.",
)
CANON_CUSTOM_20D_SOURCE = _custom_source(
    532,
    566,
    "Functions20D",
    "Functions20D is a legacy int8u custom-functions table with 20D-specific values.",
)
CANON_CUSTOM_FUNCTIONS2_TABLE_SOURCE = _custom_source(
    1198,
    1222,
    "Functions2",
    "Functions2 is the int32s custom-functions table used by EOS 1D Mark III and later models.",
)
CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE = _custom_source(
    2642,
    2769,
    "ProcessCanonCustom2 and WriteCanonCustom2",
    (
        "ProcessCanonCustom2 validates the size word, walks grouped int32 records, "
        "and preserves unwritten records."
    ),
)
CANON_CUSTOM_LEGACY_PROCESS_SOURCE = _custom_source(
    2772,
    2888,
    "ProcessCanonCustom and WriteCanonCustom",
    (
        "ProcessCanonCustom reads packed tag/value int8u entries; WriteCanonCustom "
        "edits a copied block."
    ),
)
CANON_ISO_SPEED_RANGE_SOURCE = _custom_source(
    1245,
    1268,
    "ISOSpeedRange",
    "Tag 0x0103 is ISOSpeedRange for 1D models with Count 3 and ISO ValueConv fields.",
)
CANON_FOCUSING_SCREEN_FUNCTIONS2_SOURCE = _custom_source(
    2469,
    2526,
    "Functions2 FocusingScreen",
    "Tag 0x080b has model-specific FocusingScreen print maps in Functions2.",
)
CANON_TIMER_LENGTH_SOURCE = _custom_source(
    2528,
    2550,
    "TimerLength",
    "Tag 0x080c has Count 3 and Count 4 TimerLength variants in Functions2.",
)
CANON_5D_SELECTED_SETTINGS_SOURCE = _custom_source(
    235,
    258,
    "Functions5D selected settings",
    (
        "Functions5D declares FocusingScreen and LongExposureNoiseReduction as "
        "writable int8u settings."
    ),
)
CANON_20D_SELECTED_SETTINGS_SOURCE = _custom_source(
    540,
    553,
    "Functions20D selected settings",
    "Functions20D declares LongExposureNoiseReduction with the Off/On print map.",
)


@dataclass(frozen=True)
class CanonCustomByteRange:
    start_offset: int
    end_offset: int

    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset


@dataclass(frozen=True)
class CanonCustomPrintMap:
    values: tuple[tuple[int, str], ...]

    def label_for(self, raw_value: int) -> str | None:
        for value, label in self.values:
            if value == raw_value:
                return label
        return None


@dataclass(frozen=True)
class CanonCustomSettingDefinition:
    table_name: CanonCustomTableName
    tag_id: int
    tag_name: str
    value_count: int | None
    responsibility: CanonCustomResponsibility
    print_kind: CanonCustomPrintKind
    condition: str | None
    evidence_anchors: tuple[EvidenceAnchor, ...]


@dataclass(frozen=True)
class CanonCustomTableDefinition:
    table_name: CanonCustomTableName
    payload_kind: CanonCustomPayloadKind
    route_code: CanonCustomRouteCode
    evidence_anchors: tuple[EvidenceAnchor, ...]


@dataclass(frozen=True)
class CanonCustomRoutePlan:
    table_name: CanonCustomTableName | None
    payload_kind: CanonCustomPayloadKind
    route_code: CanonCustomRouteCode | None
    camera_model: str
    evidence_anchors: tuple[EvidenceAnchor, ...]


@dataclass(frozen=True)
class CanonCustomGroupPlan:
    group_number: int
    declared_record_length: int
    declared_entry_count: int
    byte_range: CanonCustomByteRange
    evidence_anchors: tuple[EvidenceAnchor, ...]


@dataclass(frozen=True)
class CanonCustomFunctionEntryPlan:
    tag_id: int
    tag_name: str | None
    action: CanonCustomAction
    responsibility: CanonCustomResponsibility
    group_number: int | None
    index: int
    value_count: int
    raw_values: tuple[int, ...]
    print_values: tuple[str | None, ...]
    byte_range: CanonCustomByteRange
    value_byte_range: CanonCustomByteRange
    condition: str | None
    evidence_anchors: tuple[EvidenceAnchor, ...]


@dataclass(frozen=True)
class CanonCustomUnknownBytePlan:
    action: CanonCustomAction
    byte_range: CanonCustomByteRange
    payload: bytes
    responsibility: CanonCustomResponsibility
    reason: str
    evidence_anchors: tuple[EvidenceAnchor, ...]


@dataclass(frozen=True)
class CanonCustomRewriteRequest:
    tag_name: str
    raw_values: tuple[int, ...]


@dataclass(frozen=True)
class CanonCustomEmissionGate:
    code: CanonCustomGateCode
    reason: str
    evidence_anchors: tuple[EvidenceAnchor, ...]


@dataclass(frozen=True)
class CanonCustomBlocker:
    code: CanonCustomBlockerCode
    reason: str
    evidence_anchors: tuple[EvidenceAnchor, ...]


@dataclass(frozen=True)
class CanonCustomTransactionPlan:
    status: CanonCustomPlanStatus
    route: CanonCustomRoutePlan
    original_bytes: bytes
    groups: tuple[CanonCustomGroupPlan, ...]
    entries: tuple[CanonCustomFunctionEntryPlan, ...]
    unknown_bytes: tuple[CanonCustomUnknownBytePlan, ...]
    blockers: tuple[CanonCustomBlocker, ...]
    output_emission_gates: tuple[CanonCustomEmissionGate, ...]
    rewrite_requests: tuple[CanonCustomRewriteRequest, ...]
    evidence_anchors: tuple[EvidenceAnchor, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Canon custom-functions output is gated: {gate_codes}")
        return self.original_bytes


def build_canon_custom_transaction_plan(
    source_bytes: bytes,
    *,
    camera_model: str,
    payload_kind: CanonCustomPayloadKind = "canon_custom2",
    byte_order: CanonCustomByteOrder = "little",
    table_name: CanonCustomTableName | None = None,
    rewrite_requests: tuple[CanonCustomRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> CanonCustomTransactionPlan:
    route = _route_table(camera_model, payload_kind, table_name)
    groups: tuple[CanonCustomGroupPlan, ...] = ()
    entries: tuple[CanonCustomFunctionEntryPlan, ...] = ()
    unknown_bytes: tuple[CanonCustomUnknownBytePlan, ...] = ()
    blockers = list(_route_blockers(route))

    if route.table_name is not None:
        if route.payload_kind == "canon_custom2":
            parsed = _parse_functions2(source_bytes, byte_order, route.table_name)
        else:
            parsed = _parse_legacy_functions(
                source_bytes,
                byte_order,
                camera_model,
                route.table_name,
            )
        groups = parsed.groups
        entries = parsed.entries
        unknown_bytes = parsed.unknown_bytes
        blockers.extend(parsed.blockers)

    gates = list(_rewrite_gates(rewrite_requests, route.table_name))
    if not allow_output_emission:
        gates.append(_non_mutating_gate())

    output_gates = _unique_gates(tuple(gates))
    blocker_tuple = tuple(blockers)
    return CanonCustomTransactionPlan(
        status=_status_from_findings(blocker_tuple, output_gates),
        route=route,
        original_bytes=source_bytes,
        groups=groups,
        entries=entries,
        unknown_bytes=unknown_bytes,
        blockers=blocker_tuple,
        output_emission_gates=output_gates,
        rewrite_requests=rewrite_requests,
        evidence_anchors=_unique_anchors(
            (
                *route.evidence_anchors,
                *(source for group in groups for source in group.evidence_anchors),
                *(source for entry in entries for source in entry.evidence_anchors),
                *(source for byte in unknown_bytes for source in byte.evidence_anchors),
                *(source for blocker in blocker_tuple for source in blocker.evidence_anchors),
                *(source for gate in output_gates for source in gate.evidence_anchors),
            )
        ),
    )


plan_canon_custom_transaction = build_canon_custom_transaction_plan


@dataclass(frozen=True)
class _ParsedCanonCustom:
    groups: tuple[CanonCustomGroupPlan, ...]
    entries: tuple[CanonCustomFunctionEntryPlan, ...]
    unknown_bytes: tuple[CanonCustomUnknownBytePlan, ...]
    blockers: tuple[CanonCustomBlocker, ...]


def _route_table(
    camera_model: str,
    payload_kind: CanonCustomPayloadKind,
    table_name: CanonCustomTableName | None,
) -> CanonCustomRoutePlan:
    tables = _table_definitions()
    if table_name is not None:
        table = tables.get(table_name)
        if table is None or table.payload_kind != payload_kind:
            return CanonCustomRoutePlan(
                None,
                payload_kind,
                None,
                camera_model,
                (CANON_CUSTOM_FUNCTIONS2_TABLE_SOURCE, CANON_CUSTOM_LEGACY_PROCESS_SOURCE),
            )
        return CanonCustomRoutePlan(
            table.table_name,
            table.payload_kind,
            "explicit_table",
            camera_model,
            table.evidence_anchors,
        )

    if payload_kind == "canon_custom2":
        table = tables["Functions2"]
        return CanonCustomRoutePlan(
            table.table_name,
            table.payload_kind,
            table.route_code,
            camera_model,
            table.evidence_anchors,
        )

    normalized = camera_model.upper()
    if "20D" in normalized:
        return _known_legacy_route("Functions20D", camera_model)
    if "5D" in normalized and "MARK II" not in normalized:
        return _known_legacy_route("Functions5D", camera_model)
    if "1D" in normalized and "MARK III" not in normalized:
        return _known_legacy_route("Functions1D", camera_model)
    return CanonCustomRoutePlan(
        None,
        payload_kind,
        None,
        camera_model,
        (CANON_CUSTOM_LEGACY_PROCESS_SOURCE,),
    )


def _known_legacy_route(
    table_name: CanonCustomTableName,
    camera_model: str,
) -> CanonCustomRoutePlan:
    table = _table_definitions()[table_name]
    return CanonCustomRoutePlan(
        table.table_name,
        table.payload_kind,
        table.route_code,
        camera_model,
        table.evidence_anchors,
    )


def _route_blockers(route: CanonCustomRoutePlan) -> tuple[CanonCustomBlocker, ...]:
    if route.table_name is not None:
        return ()
    return (
        CanonCustomBlocker(
            "unsupported_canon_custom_table_route",
            "No source-backed Canon custom-functions table route is known for this input.",
            route.evidence_anchors,
        ),
    )


def _parse_functions2(
    source_bytes: bytes,
    byte_order: CanonCustomByteOrder,
    table_name: CanonCustomTableName,
) -> _ParsedCanonCustom:
    blockers: list[CanonCustomBlocker] = []
    groups: list[CanonCustomGroupPlan] = []
    entries: list[CanonCustomFunctionEntryPlan] = []
    unknown_bytes = _functions2_fixed_unknown_bytes(source_bytes)
    size = len(source_bytes)
    if size < 2:
        return _blocked_parse(
            "invalid_canon_custom_data",
            "Canon CustomFunctions2 data must contain the leading size word.",
            (CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE,),
            unknown_bytes,
        )

    declared_size = _read_u16(source_bytes, 0, byte_order)
    if declared_size != size or declared_size < 8:
        return _blocked_parse(
            "invalid_canon_custom_data",
            "Canon CustomFunctions2 first uint16 must equal the payload length and be at least 8.",
            (CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE,),
            unknown_bytes,
        )

    position = 8
    end = declared_size
    while position < end:
        if position + 12 > end:
            blockers.append(
                CanonCustomBlocker(
                    "corrupted_canon_custom_data",
                    "Canon CustomFunctions2 group header ends before the declared payload length.",
                    (CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE,),
                )
            )
            break
        group_number = _read_u32(source_bytes, position, byte_order)
        record_length = _read_u32(source_bytes, position + 4, byte_order)
        entry_count = _read_u32(source_bytes, position + 8, byte_order)
        if record_length < 8:
            blockers.append(
                CanonCustomBlocker(
                    "corrupted_canon_custom_data",
                    "Canon CustomFunctions2 group record length must be at least 8.",
                    (CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE,),
                )
            )
            break
        group_start = position
        position += 12
        record_end = position + record_length - 8
        if record_end > end:
            blockers.append(
                CanonCustomBlocker(
                    "truncated_canon_custom_group",
                    f"Canon CustomFunctions2 group {group_number} extends beyond the payload.",
                    (CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE,),
                )
            )
            break
        groups.append(
            CanonCustomGroupPlan(
                group_number=group_number,
                declared_record_length=record_length,
                declared_entry_count=entry_count,
                byte_range=CanonCustomByteRange(group_start, record_end),
                evidence_anchors=(CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE,),
            )
        )
        entries.extend(
            _parse_functions2_entries(
                source_bytes,
                byte_order,
                table_name,
                group_number,
                position,
                record_end,
            )
        )
        position = record_end

    if position != end and not blockers:
        blockers.append(
            CanonCustomBlocker(
                "corrupted_canon_custom_data",
                "Canon CustomFunctions2 parser did not finish at the declared payload end.",
                (CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE,),
            )
        )

    return _ParsedCanonCustom(tuple(groups), tuple(entries), unknown_bytes, tuple(blockers))


def _parse_functions2_entries(
    source_bytes: bytes,
    byte_order: CanonCustomByteOrder,
    table_name: CanonCustomTableName,
    group_number: int,
    record_start: int,
    record_end: int,
) -> tuple[CanonCustomFunctionEntryPlan, ...]:
    plans: list[CanonCustomFunctionEntryPlan] = []
    record_position = record_start
    index = 0
    while record_position + 8 < record_end:
        entry_start = record_position
        tag_id = _read_u32(source_bytes, record_position, byte_order)
        value_count = _read_u32(source_bytes, record_position + 4, byte_order)
        next_record = record_position + 8 + value_count * 4
        if next_record > record_end:
            break
        if tag_id == 0x070C and value_count == 0x66 and next_record + 8 < record_end:
            possible_next_tag = _read_u32(source_bytes, next_record + 4, byte_order)
            if possible_next_tag == 0x070F:
                value_count += 1
                next_record += 4
        value_start = record_position + 8
        raw_values = _read_i32_values(source_bytes[value_start:next_record], byte_order)
        definition = _definition_for(table_name, tag_id, value_count)
        plans.append(
            _entry_plan(
                definition,
                tag_id,
                group_number,
                index,
                value_count,
                raw_values,
                CanonCustomByteRange(entry_start, next_record),
                CanonCustomByteRange(value_start, next_record),
                (CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE,),
            )
        )
        index += 1
        record_position = next_record
    return tuple(plans)


def _parse_legacy_functions(
    source_bytes: bytes,
    byte_order: CanonCustomByteOrder,
    camera_model: str,
    table_name: CanonCustomTableName,
) -> _ParsedCanonCustom:
    if len(source_bytes) < 2:
        return _blocked_parse(
            "invalid_canon_custom_data",
            "Canon custom data must contain the leading size word.",
            (CANON_CUSTOM_LEGACY_PROCESS_SOURCE,),
            (),
        )
    declared_size = _read_u16(source_bytes, 0, byte_order)
    d60_size_match = "D60" in camera_model.upper() and declared_size + 2 == len(source_bytes)
    if declared_size != len(source_bytes) and not d60_size_match:
        return _blocked_parse(
            "invalid_canon_custom_data",
            (
                "Canon custom data first uint16 must equal the payload length, "
                "except the D60 len+2 case."
            ),
            (CANON_CUSTOM_LEGACY_PROCESS_SOURCE,),
            (),
        )

    entries: list[CanonCustomFunctionEntryPlan] = []
    for index, position in enumerate(range(2, len(source_bytes), 2)):
        if position + 2 > len(source_bytes):
            break
        packed = _read_u16(source_bytes, position, byte_order)
        tag_id = packed >> 8
        raw_value = packed & 0xFF
        definition = _definition_for(table_name, tag_id, 1)
        value_offset = position if byte_order == "little" else position + 1
        entries.append(
            _entry_plan(
                definition,
                tag_id,
                None,
                index,
                1,
                (raw_value,),
                CanonCustomByteRange(position, position + 2),
                CanonCustomByteRange(value_offset, value_offset + 1),
                (CANON_CUSTOM_LEGACY_PROCESS_SOURCE,),
            )
        )
    return _ParsedCanonCustom((), tuple(entries), (), ())


def _blocked_parse(
    code: CanonCustomBlockerCode,
    reason: str,
    sources: tuple[EvidenceAnchor, ...],
    unknown_bytes: tuple[CanonCustomUnknownBytePlan, ...],
) -> _ParsedCanonCustom:
    return _ParsedCanonCustom(
        (),
        (),
        unknown_bytes,
        (CanonCustomBlocker(code, reason, sources),),
    )


def _entry_plan(
    definition: CanonCustomSettingDefinition | None,
    tag_id: int,
    group_number: int | None,
    index: int,
    value_count: int,
    raw_values: tuple[int, ...],
    byte_range: CanonCustomByteRange,
    value_byte_range: CanonCustomByteRange,
    parser_sources: tuple[EvidenceAnchor, ...],
) -> CanonCustomFunctionEntryPlan:
    if definition is None:
        return CanonCustomFunctionEntryPlan(
            tag_id=tag_id,
            tag_name=None,
            action="preserve_unknown_tag",
            responsibility="unknown_preserved_tag",
            group_number=group_number,
            index=index,
            value_count=value_count,
            raw_values=raw_values,
            print_values=tuple(None for _ in raw_values),
            byte_range=byte_range,
            value_byte_range=value_byte_range,
            condition=None,
            evidence_anchors=parser_sources,
        )
    return CanonCustomFunctionEntryPlan(
        tag_id=tag_id,
        tag_name=definition.tag_name,
        action=(
            "route_conditional_setting"
            if definition.responsibility == "known_conditional_setting"
            else "route_known_setting"
        ),
        responsibility=definition.responsibility,
        group_number=group_number,
        index=index,
        value_count=value_count,
        raw_values=raw_values,
        print_values=_print_values(definition.print_kind, raw_values),
        byte_range=byte_range,
        value_byte_range=value_byte_range,
        condition=definition.condition,
        evidence_anchors=_unique_anchors((*parser_sources, *definition.evidence_anchors)),
    )


def _functions2_fixed_unknown_bytes(
    source_bytes: bytes,
) -> tuple[CanonCustomUnknownBytePlan, ...]:
    if len(source_bytes) < 4:
        return ()
    return (
        CanonCustomUnknownBytePlan(
            action="preserve_unknown_byte",
            byte_range=CanonCustomByteRange(2, 4),
            payload=source_bytes[2:4],
            responsibility="unknown_preserved_byte",
            reason="ProcessCanonCustom2 reads the size at offset 0 and group count at offset 4.",
            evidence_anchors=(CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE,),
        ),
    )


def _definition_for(
    table_name: CanonCustomTableName,
    tag_id: int,
    value_count: int,
) -> CanonCustomSettingDefinition | None:
    for definition in _setting_definitions():
        if definition.table_name != table_name or definition.tag_id != tag_id:
            continue
        if definition.value_count is None or definition.value_count == value_count:
            return definition
    return None


def _rewrite_gates(
    rewrite_requests: tuple[CanonCustomRewriteRequest, ...],
    table_name: CanonCustomTableName | None,
) -> tuple[CanonCustomEmissionGate, ...]:
    if not rewrite_requests:
        return ()
    known_names = {
        definition.tag_name
        for definition in _setting_definitions()
        if table_name is None or definition.table_name == table_name
    }
    gates: list[CanonCustomEmissionGate] = []
    for request in rewrite_requests:
        if request.tag_name in known_names:
            gates.append(
                CanonCustomEmissionGate(
                    "unsupported_canon_custom_rewrite",
                    "This slice plans Canon custom-functions responsibility and preservation only.",
                    (CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE, CANON_CUSTOM_LEGACY_PROCESS_SOURCE),
                )
            )
        else:
            gates.append(
                CanonCustomEmissionGate(
                    "unknown_canon_custom_rewrite",
                    "Requested tag is not part of the source-backed Canon custom-functions slice.",
                    (CANON_CUSTOM_FUNCTIONS2_TABLE_SOURCE, CANON_CUSTOM_LEGACY_PROCESS_SOURCE),
                )
            )
    return tuple(gates)


def _non_mutating_gate() -> CanonCustomEmissionGate:
    return CanonCustomEmissionGate(
        "non_mutating_plan_requires_explicit_emission",
        "Canon custom-functions plans preserve source bytes unless emission is explicit.",
        (CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE, CANON_CUSTOM_LEGACY_PROCESS_SOURCE),
    )


def _status_from_findings(
    blockers: tuple[CanonCustomBlocker, ...],
    gates: tuple[CanonCustomEmissionGate, ...],
) -> CanonCustomPlanStatus:
    if blockers:
        return "blocked"
    if any(
        gate.code in {"unsupported_canon_custom_rewrite", "unknown_canon_custom_rewrite"}
        for gate in gates
    ):
        return "unsupported"
    return "planned"


def _table_definitions() -> dict[CanonCustomTableName, CanonCustomTableDefinition]:
    return {
        "Functions1D": CanonCustomTableDefinition(
            "Functions1D",
            "canon_custom",
            "legacy_model_table",
            (CANON_CUSTOM_TABLE_SOURCE, CANON_CUSTOM_LEGACY_PROCESS_SOURCE),
        ),
        "Functions5D": CanonCustomTableDefinition(
            "Functions5D",
            "canon_custom",
            "legacy_model_table",
            (CANON_CUSTOM_5D_SOURCE, CANON_CUSTOM_LEGACY_PROCESS_SOURCE),
        ),
        "Functions20D": CanonCustomTableDefinition(
            "Functions20D",
            "canon_custom",
            "legacy_model_table",
            (CANON_CUSTOM_20D_SOURCE, CANON_CUSTOM_LEGACY_PROCESS_SOURCE),
        ),
        "Functions2": CanonCustomTableDefinition(
            "Functions2",
            "canon_custom2",
            "makernote_custom_functions2",
            (
                CANON_CUSTOM_FUNCTIONS2_ROUTE_SOURCE,
                CANON_CUSTOM_FUNCTIONS2_TABLE_SOURCE,
                CANON_CUSTOM_FUNCTIONS2_PROCESS_SOURCE,
            ),
        ),
    }


def _setting_definitions() -> tuple[CanonCustomSettingDefinition, ...]:
    return (
        CanonCustomSettingDefinition(
            "Functions2",
            0x0103,
            "ISOSpeedRange",
            3,
            "known_conditional_setting",
            "iso_speed_range",
            "$$self{Model} =~ /\\b1D/",
            (CANON_ISO_SPEED_RANGE_SOURCE,),
        ),
        CanonCustomSettingDefinition(
            "Functions2",
            0x080B,
            "FocusingScreen",
            1,
            "known_conditional_setting",
            "functions2_focusing_screen",
            "model-specific Functions2 FocusingScreen entry",
            (CANON_FOCUSING_SCREEN_FUNCTIONS2_SOURCE,),
        ),
        CanonCustomSettingDefinition(
            "Functions2",
            0x080C,
            "TimerLength",
            3,
            "known_writable_setting",
            "timer_length3",
            "$count == 3",
            (CANON_TIMER_LENGTH_SOURCE,),
        ),
        CanonCustomSettingDefinition(
            "Functions2",
            0x080C,
            "TimerLength",
            4,
            "known_writable_setting",
            "timer_length4",
            None,
            (CANON_TIMER_LENGTH_SOURCE,),
        ),
        CanonCustomSettingDefinition(
            "Functions5D",
            0,
            "FocusingScreen",
            1,
            "known_writable_setting",
            "functions5d_focusing_screen",
            None,
            (CANON_5D_SELECTED_SETTINGS_SOURCE,),
        ),
        CanonCustomSettingDefinition(
            "Functions5D",
            2,
            "LongExposureNoiseReduction",
            1,
            "known_writable_setting",
            "functions5d_long_exposure_noise_reduction",
            None,
            (CANON_5D_SELECTED_SETTINGS_SOURCE,),
        ),
        CanonCustomSettingDefinition(
            "Functions20D",
            1,
            "LongExposureNoiseReduction",
            1,
            "known_writable_setting",
            "functions20d_long_exposure_noise_reduction",
            None,
            (CANON_20D_SELECTED_SETTINGS_SOURCE,),
        ),
    )


def _print_values(
    kind: CanonCustomPrintKind,
    raw_values: tuple[int, ...],
) -> tuple[str | None, ...]:
    if kind == "iso_speed_range" and len(raw_values) == 3:
        return (
            _disable_enable_map().label_for(raw_values[0]),
            f"Max {_iso_display(raw_values[1]):.0f}",
            f"Min {_iso_display(raw_values[2]):.0f}",
        )
    if kind == "timer_length3" and len(raw_values) == 3:
        return (
            f"6 s: {raw_values[0]}",
            f"16 s: {raw_values[1]}",
            f"After release: {raw_values[2]}",
        )
    if kind == "timer_length4" and len(raw_values) == 4:
        return (
            _disable_enable_map().label_for(raw_values[0]),
            f"6 s: {raw_values[1]}",
            f"16 s: {raw_values[2]}",
            f"After release: {raw_values[3]}",
        )
    if kind == "disable_enable":
        value_map = _disable_enable_map()
        return tuple(value_map.label_for(value) for value in raw_values)
    if kind == "off_on":
        value_map = CanonCustomPrintMap(((0, "Off"), (1, "On")))
        return tuple(value_map.label_for(value) for value in raw_values)
    if kind == "functions2_focusing_screen":
        value_map = CanonCustomPrintMap(
            (
                (0, "Ec-CIV"),
                (1, "Ec-A,B,C,CII,CIII,D,H,I,L"),
                (2, "Ec-S"),
                (3, "Ec-N,R"),
            )
        )
        return tuple(value_map.label_for(value) for value in raw_values)
    if kind == "functions5d_focusing_screen":
        value_map = CanonCustomPrintMap(((0, "Ee-A"), (1, "Ee-D"), (2, "Ee-S")))
        return tuple(value_map.label_for(value) for value in raw_values)
    if kind == "functions5d_long_exposure_noise_reduction":
        value_map = CanonCustomPrintMap(((0, "Off"), (1, "Auto"), (2, "On")))
        return tuple(value_map.label_for(value) for value in raw_values)
    if kind == "functions20d_long_exposure_noise_reduction":
        value_map = CanonCustomPrintMap(((0, "Off"), (1, "On")))
        return tuple(value_map.label_for(value) for value in raw_values)
    return tuple(None for _ in raw_values)


def _disable_enable_map() -> CanonCustomPrintMap:
    return CanonCustomPrintMap(((0, "Disable"), (1, "Enable")))


def _iso_display(raw_value: int) -> float:
    if raw_value < 2:
        return float(raw_value)
    if raw_value < 1000:
        return math.exp((raw_value / 8 - 9) * math.log(2)) * 100
    return 0.0


def _read_u16(data: bytes, offset: int, byte_order: CanonCustomByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 2], byte_order)


def _read_u32(data: bytes, offset: int, byte_order: CanonCustomByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order)


def _read_i32_values(data: bytes, byte_order: CanonCustomByteOrder) -> tuple[int, ...]:
    return tuple(
        int.from_bytes(data[index : index + 4], byte_order, signed=True)
        for index in range(0, len(data), 4)
    )


def _unique_anchors(sources: tuple[EvidenceAnchor, ...]) -> tuple[EvidenceAnchor, ...]:
    return tuple(dict.fromkeys(sources))


def _unique_gates(
    gates: tuple[CanonCustomEmissionGate, ...],
) -> tuple[CanonCustomEmissionGate, ...]:
    return tuple(dict.fromkeys(gates))
