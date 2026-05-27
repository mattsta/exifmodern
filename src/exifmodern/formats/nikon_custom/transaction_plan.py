"""Source-grounded Nikon custom-settings transaction planning.

The custom settings are camera-specific binary data decoded by
``lib/Image/ExifTool/NikonCustom.pm`` after Nikon maker-note tables choose the
right subdirectory.  This planner records routing, selected setting ownership,
unknown byte preservation, and rewrite gates; it does not rewrite the binary
custom-settings payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

NIKON_CUSTOM_SOURCE_PATH = "lib/Image/ExifTool/NikonCustom.pm"
NIKON_SOURCE_PATH = "lib/Image/ExifTool/Nikon.pm"

type NikonCustomPlanStatus = Literal["planned", "blocked", "unsupported"]
type NikonCustomSettingResponsibility = Literal[
    "known_writable_setting",
    "known_unknown_flagged_setting",
    "known_conditional_setting",
    "unknown_preserved_byte",
]
type NikonCustomSettingFormat = Literal["int8u", "int8s", "int16s"]
type NikonCustomRouteCode = Literal[
    "shot_info_custom_settings",
    "shot_info_offset_custom_settings",
    "menu_info_custom_settings",
]
type NikonCustomAction = Literal[
    "route_known_setting",
    "route_conditional_setting",
    "preserve_unknown_byte",
    "block_requested_rewrite",
]
type NikonCustomGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "unsupported_nikon_custom_rewrite",
    "unknown_nikon_custom_rewrite",
]
type NikonCustomBlockerCode = Literal[
    "unsupported_nikon_custom_table_route",
    "truncated_nikon_custom_settings",
]


def _custom_source(
    line_start: int,
    line_end: int,
    symbol: str,
    evidence: str,
) -> str:
    del line_start, line_end, evidence
    return "nikon.custom." + _evidence_token(symbol)


def _nikon_source(
    line_start: int,
    line_end: int,
    symbol: str,
    evidence: str,
) -> str:
    del line_start, line_end, evidence
    return "nikon.custom.route." + _evidence_token(symbol)


def _evidence_token(symbol: str) -> str:
    return (
        symbol.removeprefix("%Image::ExifTool::")
        .replace("::", ".")
        .replace("%", "")
        .replace(" ", "-")
        .lower()
    )


NIKON_CUSTOM_POD_SOURCE = _custom_source(
    11381,
    11392,
    "NikonCustom POD description",
    "Nikon custom functions are model-specific unformatted binary ShotInfo data.",
)
NIKON_CUSTOM_D80_SOURCE = _custom_source(
    349,
    766,
    "SettingsD80",
    "SettingsD80 is a writable ProcessBinaryData table with FIRST_ENTRY zero.",
)
NIKON_CUSTOM_D3_SOURCE = _custom_source(
    1456,
    2481,
    "SettingsD3",
    "SettingsD3 covers D3, D3S, D3X, D300, and D300S custom settings.",
)
NIKON_CUSTOM_D700_SOURCE = _custom_source(
    2482,
    3169,
    "SettingsD700",
    "SettingsD700 declares D700 custom settings and data members.",
)
NIKON_CUSTOM_D5_SOURCE = _custom_source(
    3392,
    4462,
    "SettingsD5",
    "SettingsD5 declares D5 custom settings as writable binary data.",
)
NIKON_CUSTOM_D500_SOURCE = _custom_source(
    4463,
    7624,
    "SettingsD500",
    "SettingsD500 declares D500 custom settings as writable binary data.",
)
NIKON_CUSTOM_Z9_SOURCE = _custom_source(
    10545,
    10954,
    "SettingsZ9",
    "SettingsZ9 declares Z9 custom settings before the v4 table split.",
)
NIKON_CUSTOM_Z9V4_SOURCE = _custom_source(
    10955,
    11379,
    "SettingsZ9v4",
    "SettingsZ9v4 declares Z9 custom settings for firmware 4.00 and higher.",
)
NIKON_SHOTINFO_D80_SOURCE = _nikon_source(
    6195,
    6201,
    "ShotInfoD80 CustomSettingsD80",
    "ShotInfoD80 routes a 17-byte custom-settings block to SettingsD80.",
)
NIKON_SHOTINFO_D3_SOURCE = _nikon_source(
    6303,
    6519,
    "ShotInfoD3/D3X/D3S CustomSettingsD3",
    "D3-family ShotInfo entries route custom-settings blocks to SettingsD3.",
)
NIKON_SHOTINFO_D700_SOURCE = _nikon_source(
    6846,
    6851,
    "ShotInfoD700 CustomSettingsD700",
    "ShotInfoD700 routes a 48-byte custom-settings block to SettingsD700.",
)
NIKON_SHOTINFO_D500_OFFSET_SOURCE = _nikon_source(
    7257,
    7261,
    "ShotInfoD500 CustomSettingsOffset",
    "ShotInfoD500 routes a relative offset to the CustomSettingsD500 table.",
)
NIKON_CUSTOM_D500_ROUTE_SOURCE = _nikon_source(
    7591,
    7608,
    "CustomSettingsD500 table route",
    "CustomSettingsD500 routes model D5 to SettingsD5 and otherwise to SettingsD500.",
)
NIKON_MENUINFO_Z9_ROUTE_SOURCE = _nikon_source(
    9218,
    9238,
    "MenuSettingsZ9 firmware route",
    "MenuInfoZ9 chooses menu/custom settings tables by firmware version.",
)
NIKON_MENU_Z9_SOURCE = _nikon_source(
    10295,
    10298,
    "MenuSettingsZ9 CustomSettingsZ9",
    "MenuSettingsZ9 routes CustomSettingsZ9 to NikonCustom SettingsZ9.",
)
NIKON_MENU_Z9V4_SOURCE = _nikon_source(
    10683,
    10686,
    "MenuSettingsZ9v4 CustomSettingsZ9v4",
    "MenuSettingsZ9v4 routes CustomSettingsZ9v4 to NikonCustom SettingsZ9v4.",
)


@dataclass(frozen=True)
class NikonCustomByteRange:
    start_offset: int
    end_offset: int

    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset


@dataclass(frozen=True)
class NikonCustomPrintMap:
    values: tuple[tuple[int, str], ...]

    def label_for(self, raw_value: int) -> str | None:
        for value, label in self.values:
            if value == raw_value:
                return label
        return None


@dataclass(frozen=True)
class NikonCustomSettingDefinition:
    table_name: str
    tag_key: str
    byte_offset: int
    tag_name: str
    size: int
    value_format: NikonCustomSettingFormat
    mask: int | None
    print_map: NikonCustomPrintMap | None
    responsibility: NikonCustomSettingResponsibility
    condition: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCustomTableDefinition:
    table_name: str
    expected_length: int
    route_code: NikonCustomRouteCode
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCustomTableRoutePlan:
    table_name: str | None
    route_code: NikonCustomRouteCode | None
    camera_model: str
    firmware_version: str | None
    expected_length: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCustomSettingPlan:
    tag_key: str
    tag_name: str
    action: NikonCustomAction
    responsibility: NikonCustomSettingResponsibility
    byte_range: NikonCustomByteRange
    size: int
    mask: int | None
    raw_value: int
    print_value: str | None
    condition: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCustomUnknownBytePlan:
    action: NikonCustomAction
    byte_range: NikonCustomByteRange
    payload: bytes
    responsibility: NikonCustomSettingResponsibility
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCustomRewriteRequest:
    tag_name: str
    raw_value: int


@dataclass(frozen=True)
class NikonCustomEmissionGate:
    code: NikonCustomGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCustomBlocker:
    code: NikonCustomBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCustomResponsibilityPlan:
    concern: NikonCustomSettingResponsibility
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonCustomTransactionPlan:
    status: NikonCustomPlanStatus
    route: NikonCustomTableRoutePlan
    original_bytes: bytes
    settings: tuple[NikonCustomSettingPlan, ...]
    unknown_bytes: tuple[NikonCustomUnknownBytePlan, ...]
    blockers: tuple[NikonCustomBlocker, ...]
    output_emission_gates: tuple[NikonCustomEmissionGate, ...]
    rewrite_requests: tuple[NikonCustomRewriteRequest, ...]
    responsibilities: tuple[NikonCustomResponsibilityPlan, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Nikon custom-settings output is gated: {gate_codes}")
        return self.original_bytes


def build_nikon_custom_transaction_plan(
    source_bytes: bytes,
    *,
    camera_model: str,
    firmware_version: str | None = None,
    table_name: str | None = None,
    rewrite_requests: tuple[NikonCustomRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> NikonCustomTransactionPlan:
    route = _route_table(camera_model, firmware_version, table_name)
    blockers = list(_route_blockers(route))
    settings: tuple[NikonCustomSettingPlan, ...] = ()
    unknown_bytes: tuple[NikonCustomUnknownBytePlan, ...] = ()

    if route.table_name is not None:
        table = _table_definitions()[route.table_name]
        if len(source_bytes) < table.expected_length:
            blockers.append(
                NikonCustomBlocker(
                    "truncated_nikon_custom_settings",
                    (
                        f"{table.table_name} expects at least {table.expected_length} bytes; "
                        f"received {len(source_bytes)} bytes."
                    ),
                    table.evidence_ids,
                )
            )
        settings = _build_setting_plans(source_bytes, route.table_name)
        unknown_bytes = _build_unknown_byte_plans(source_bytes, route.table_name)

    gates = list(_rewrite_gates(rewrite_requests, route.table_name))
    if not allow_output_emission:
        gates.append(_non_mutating_gate())

    output_gates = _unique_gates(tuple(gates))
    blocker_tuple = tuple(blockers)
    status = _status_from_findings(blocker_tuple, output_gates)
    return NikonCustomTransactionPlan(
        status=status,
        route=route,
        original_bytes=source_bytes,
        settings=settings,
        unknown_bytes=unknown_bytes,
        blockers=blocker_tuple,
        output_emission_gates=output_gates,
        rewrite_requests=rewrite_requests,
        responsibilities=_responsibilities(),
        evidence_ids=_unique_sources(
            (
                NIKON_CUSTOM_POD_SOURCE,
                *route.evidence_ids,
                *(source for setting in settings for source in setting.evidence_ids),
                *(source for byte in unknown_bytes for source in byte.evidence_ids),
                *(source for blocker in blocker_tuple for source in blocker.evidence_ids),
                *(source for gate in output_gates for source in gate.evidence_ids),
            )
        ),
    )


plan_nikon_custom_transaction = build_nikon_custom_transaction_plan


def _route_table(
    camera_model: str,
    firmware_version: str | None,
    table_name: str | None,
) -> NikonCustomTableRoutePlan:
    tables = _table_definitions()
    if table_name is not None:
        table = tables.get(table_name)
        return NikonCustomTableRoutePlan(
            table_name=table_name if table is not None else None,
            route_code=table.route_code if table is not None else None,
            camera_model=camera_model,
            firmware_version=firmware_version,
            expected_length=table.expected_length if table is not None else None,
            evidence_ids=(table.evidence_ids if table is not None else (NIKON_CUSTOM_POD_SOURCE,)),
        )

    normalized = camera_model.upper()
    if normalized == "D80":
        return _known_route("SettingsD80", camera_model, firmware_version)
    if normalized in {"D3", "D3S", "D3X", "D300", "D300S"}:
        return _known_route("SettingsD3", camera_model, firmware_version)
    if normalized == "D700":
        return _known_route("SettingsD700", camera_model, firmware_version)
    if normalized == "D5":
        return _known_route("SettingsD5", camera_model, firmware_version)
    if normalized == "D500":
        return _known_route("SettingsD500", camera_model, firmware_version)
    if normalized == "Z9":
        if _firmware_at_least(firmware_version, "04.00"):
            return _known_route("SettingsZ9v4", camera_model, firmware_version)
        return _known_route("SettingsZ9", camera_model, firmware_version)
    return NikonCustomTableRoutePlan(
        table_name=None,
        route_code=None,
        camera_model=camera_model,
        firmware_version=firmware_version,
        expected_length=None,
        evidence_ids=(NIKON_CUSTOM_POD_SOURCE,),
    )


def _known_route(
    table_name: str,
    camera_model: str,
    firmware_version: str | None,
) -> NikonCustomTableRoutePlan:
    table = _table_definitions()[table_name]
    return NikonCustomTableRoutePlan(
        table_name=table.table_name,
        route_code=table.route_code,
        camera_model=camera_model,
        firmware_version=firmware_version,
        expected_length=table.expected_length,
        evidence_ids=table.evidence_ids,
    )


def _firmware_at_least(firmware_version: str | None, minimum: str) -> bool:
    if firmware_version is None:
        return False
    return firmware_version >= minimum


def _route_blockers(route: NikonCustomTableRoutePlan) -> tuple[NikonCustomBlocker, ...]:
    if route.table_name is not None:
        return ()
    return (
        NikonCustomBlocker(
            "unsupported_nikon_custom_table_route",
            "No source-backed Nikon custom-settings table route is known for this input.",
            route.evidence_ids,
        ),
    )


def _build_setting_plans(
    source_bytes: bytes,
    table_name: str,
) -> tuple[NikonCustomSettingPlan, ...]:
    plans: list[NikonCustomSettingPlan] = []
    for definition in _setting_definitions():
        if definition.table_name != table_name:
            continue
        if len(source_bytes) < definition.byte_offset + definition.size:
            continue
        raw_value = _read_setting_value(source_bytes, definition)
        plans.append(
            NikonCustomSettingPlan(
                tag_key=definition.tag_key,
                tag_name=definition.tag_name,
                action=(
                    "route_conditional_setting"
                    if definition.responsibility == "known_conditional_setting"
                    else "route_known_setting"
                ),
                responsibility=definition.responsibility,
                byte_range=NikonCustomByteRange(
                    definition.byte_offset,
                    definition.byte_offset + definition.size,
                ),
                size=definition.size,
                mask=definition.mask,
                raw_value=raw_value,
                print_value=(
                    definition.print_map.label_for(raw_value)
                    if definition.print_map is not None
                    else None
                ),
                condition=definition.condition,
                evidence_ids=definition.evidence_ids,
            )
        )
    return tuple(plans)


def _read_setting_value(source_bytes: bytes, definition: NikonCustomSettingDefinition) -> int:
    payload = source_bytes[definition.byte_offset : definition.byte_offset + definition.size]
    signed = definition.value_format in {"int8s", "int16s"}
    value = int.from_bytes(payload, "little", signed=signed)
    if definition.mask is None:
        return value
    return (value & definition.mask) >> _mask_shift(definition.mask)


def _mask_shift(mask: int) -> int:
    shift = 0
    shifted = mask
    while shifted and shifted & 1 == 0:
        shift += 1
        shifted >>= 1
    return shift


def _build_unknown_byte_plans(
    source_bytes: bytes,
    table_name: str,
) -> tuple[NikonCustomUnknownBytePlan, ...]:
    owned_offsets = {
        definition.byte_offset + offset
        for definition in _setting_definitions()
        if definition.table_name == table_name
        for offset in range(definition.size)
    }
    unknowns: list[NikonCustomUnknownBytePlan] = []
    for byte_offset, value in enumerate(source_bytes):
        if byte_offset in owned_offsets:
            continue
        unknowns.append(
            NikonCustomUnknownBytePlan(
                action="preserve_unknown_byte",
                byte_range=NikonCustomByteRange(byte_offset, byte_offset + 1),
                payload=bytes((value,)),
                responsibility="unknown_preserved_byte",
                evidence_ids=(NIKON_CUSTOM_POD_SOURCE,),
            )
        )
    return tuple(unknowns)


def _rewrite_gates(
    rewrite_requests: tuple[NikonCustomRewriteRequest, ...],
    table_name: str | None,
) -> tuple[NikonCustomEmissionGate, ...]:
    if not rewrite_requests:
        return ()
    known_names = {
        definition.tag_name
        for definition in _setting_definitions()
        if table_name is None or definition.table_name == table_name
    }
    gates: list[NikonCustomEmissionGate] = []
    for request in rewrite_requests:
        if request.tag_name in known_names:
            gates.append(
                NikonCustomEmissionGate(
                    "unsupported_nikon_custom_rewrite",
                    (
                        "NikonCustom.pm has WriteBinaryData tables, but this slice only "
                        "plans source-backed ownership and preservation."
                    ),
                    (NIKON_CUSTOM_POD_SOURCE,),
                )
            )
        else:
            gates.append(
                NikonCustomEmissionGate(
                    "unknown_nikon_custom_rewrite",
                    "Requested tag is not part of the source-backed Nikon custom slice.",
                    (NIKON_CUSTOM_POD_SOURCE,),
                )
            )
    return tuple(gates)


def _non_mutating_gate() -> NikonCustomEmissionGate:
    return NikonCustomEmissionGate(
        "non_mutating_plan_requires_explicit_emission",
        "Nikon custom-settings plans preserve source bytes unless emission is explicit.",
        (NIKON_CUSTOM_POD_SOURCE,),
    )


def _status_from_findings(
    blockers: tuple[NikonCustomBlocker, ...],
    gates: tuple[NikonCustomEmissionGate, ...],
) -> NikonCustomPlanStatus:
    if blockers:
        return "blocked"
    if any(
        gate.code in {"unsupported_nikon_custom_rewrite", "unknown_nikon_custom_rewrite"}
        for gate in gates
    ):
        return "unsupported"
    return "planned"


def _responsibilities() -> tuple[NikonCustomResponsibilityPlan, ...]:
    return (
        NikonCustomResponsibilityPlan(
            "known_writable_setting",
            "Decode selected settings from source-declared offsets, masks, and print maps.",
            (
                NIKON_CUSTOM_D80_SOURCE,
                NIKON_CUSTOM_D3_SOURCE,
                NIKON_CUSTOM_D5_SOURCE,
                NIKON_CUSTOM_Z9V4_SOURCE,
            ),
        ),
        NikonCustomResponsibilityPlan(
            "known_unknown_flagged_setting",
            "Classify source entries marked Unknown as known-but-not-owned for rewrite.",
            (NIKON_CUSTOM_Z9V4_SOURCE,),
        ),
        NikonCustomResponsibilityPlan(
            "known_conditional_setting",
            "Record source conditions without evaluating unrelated maker-note state.",
            (NIKON_CUSTOM_Z9V4_SOURCE,),
        ),
        NikonCustomResponsibilityPlan(
            "unknown_preserved_byte",
            "Preserve bytes not covered by this source-backed setting slice.",
            (NIKON_CUSTOM_POD_SOURCE,),
        ),
    )


def _table_definitions() -> dict[str, NikonCustomTableDefinition]:
    return {
        "SettingsD80": NikonCustomTableDefinition(
            "SettingsD80",
            17,
            "shot_info_custom_settings",
            (NIKON_SHOTINFO_D80_SOURCE, NIKON_CUSTOM_D80_SOURCE),
        ),
        "SettingsD3": NikonCustomTableDefinition(
            "SettingsD3",
            24,
            "shot_info_custom_settings",
            (NIKON_SHOTINFO_D3_SOURCE, NIKON_CUSTOM_D3_SOURCE),
        ),
        "SettingsD700": NikonCustomTableDefinition(
            "SettingsD700",
            48,
            "shot_info_custom_settings",
            (NIKON_SHOTINFO_D700_SOURCE, NIKON_CUSTOM_D700_SOURCE),
        ),
        "SettingsD5": NikonCustomTableDefinition(
            "SettingsD5",
            90,
            "shot_info_offset_custom_settings",
            (
                NIKON_SHOTINFO_D500_OFFSET_SOURCE,
                NIKON_CUSTOM_D500_ROUTE_SOURCE,
                NIKON_CUSTOM_D5_SOURCE,
            ),
        ),
        "SettingsD500": NikonCustomTableDefinition(
            "SettingsD500",
            90,
            "shot_info_offset_custom_settings",
            (
                NIKON_SHOTINFO_D500_OFFSET_SOURCE,
                NIKON_CUSTOM_D500_ROUTE_SOURCE,
                NIKON_CUSTOM_D500_SOURCE,
            ),
        ),
        "SettingsZ9": NikonCustomTableDefinition(
            "SettingsZ9",
            608,
            "menu_info_custom_settings",
            (
                NIKON_MENUINFO_Z9_ROUTE_SOURCE,
                NIKON_MENU_Z9_SOURCE,
                NIKON_CUSTOM_Z9_SOURCE,
            ),
        ),
        "SettingsZ9v4": NikonCustomTableDefinition(
            "SettingsZ9v4",
            632,
            "menu_info_custom_settings",
            (
                NIKON_MENUINFO_Z9_ROUTE_SOURCE,
                NIKON_MENU_Z9V4_SOURCE,
                NIKON_CUSTOM_Z9V4_SOURCE,
            ),
        ),
    }


def _setting_definitions() -> tuple[NikonCustomSettingDefinition, ...]:
    on_off = NikonCustomPrintMap(((0, "On"), (1, "Off")))
    banks = NikonCustomPrintMap(((0, "A"), (1, "B"), (2, "C"), (3, "D")))
    afc_priority = NikonCustomPrintMap(
        ((0, "Release"), (1, "Release + Focus"), (2, "Focus"), (3, "Focus + Release"))
    )
    afs_priority_d3 = NikonCustomPrintMap(((0, "Focus"), (1, "Release")))
    afs_priority_z9 = NikonCustomPrintMap(((0, "Release"), (1, "Focus")))
    third_half_full = NikonCustomPrintMap(((0, "1/3 EV"), (1, "1/2 EV"), (2, "1 EV")))
    return (
        _setting(
            "SettingsD80", "0.1", 0, "Beep", 1, "int8u", 0x80, on_off, None, NIKON_CUSTOM_D80_SOURCE
        ),
        _setting(
            "SettingsD80",
            "0.2",
            0,
            "AFAssist",
            1,
            "int8u",
            0x40,
            on_off,
            None,
            NIKON_CUSTOM_D80_SOURCE,
        ),
        _setting(
            "SettingsD80",
            "0.7",
            0,
            "EVStepSize",
            1,
            "int8u",
            0x01,
            NikonCustomPrintMap(((0, "1/3 EV"), (1, "1/2 EV"))),
            None,
            NIKON_CUSTOM_D80_SOURCE,
        ),
        _setting(
            "SettingsD3",
            "0.1",
            0,
            "CustomSettingsBank",
            1,
            "int8u",
            0x03,
            banks,
            None,
            NIKON_CUSTOM_D3_SOURCE,
        ),
        _setting(
            "SettingsD3",
            "1.1",
            1,
            "AF-CPrioritySelection",
            1,
            "int8u",
            0xC0,
            afc_priority,
            None,
            NIKON_CUSTOM_D3_SOURCE,
        ),
        _setting(
            "SettingsD3",
            "1.2",
            1,
            "AF-SPrioritySelection",
            1,
            "int8u",
            0x20,
            afs_priority_d3,
            None,
            NIKON_CUSTOM_D3_SOURCE,
        ),
        _setting(
            "SettingsD3",
            "1.5",
            1,
            "FocusTrackingLockOn",
            1,
            "int8u",
            0x03,
            NikonCustomPrintMap(((0, "Long"), (1, "Normal"), (2, "Short"), (3, "Off"))),
            "$$self{Model} !~ /D3S\\b/",
            NIKON_CUSTOM_D3_SOURCE,
            responsibility="known_conditional_setting",
        ),
        _setting(
            "SettingsD700",
            "0.1",
            0,
            "CustomSettingsBank",
            1,
            "int8u",
            0x03,
            banks,
            None,
            NIKON_CUSTOM_D700_SOURCE,
        ),
        _setting(
            "SettingsD700",
            "1.1",
            1,
            "AF-CPrioritySelection",
            1,
            "int8u",
            0xC0,
            NikonCustomPrintMap(((0, "Release"), (1, "Release + Focus"), (2, "Focus"))),
            None,
            NIKON_CUSTOM_D700_SOURCE,
        ),
        _setting(
            "SettingsD5",
            "0.1",
            0,
            "CustomSettingsBank",
            1,
            "int8u",
            0x03,
            banks,
            None,
            NIKON_CUSTOM_D5_SOURCE,
        ),
        _setting(
            "SettingsD5",
            "1.1",
            1,
            "AF-CPrioritySelection",
            1,
            "int8u",
            0xC0,
            afc_priority,
            None,
            NIKON_CUSTOM_D5_SOURCE,
        ),
        _setting(
            "SettingsD500",
            "0.1",
            0,
            "CustomSettingsBank",
            1,
            "int8u",
            0x03,
            banks,
            None,
            NIKON_CUSTOM_D500_SOURCE,
        ),
        _setting(
            "SettingsZ9",
            "1",
            1,
            "CustomSettingsBank",
            1,
            "int8u",
            None,
            banks,
            None,
            NIKON_CUSTOM_Z9_SOURCE,
        ),
        _setting(
            "SettingsZ9",
            "3",
            3,
            "AF-CPrioritySelection",
            1,
            "int8u",
            None,
            NikonCustomPrintMap(((0, "Release"), (1, "Release + Focus"), (3, "Focus"))),
            None,
            NIKON_CUSTOM_Z9_SOURCE,
        ),
        _setting(
            "SettingsZ9v4",
            "1",
            1,
            "CustomSettingsBank",
            1,
            "int8u",
            None,
            banks,
            None,
            NIKON_CUSTOM_Z9V4_SOURCE,
        ),
        _setting(
            "SettingsZ9v4",
            "3",
            3,
            "AF-CPrioritySelection",
            1,
            "int8u",
            None,
            NikonCustomPrintMap(((0, "Release"), (1, "Release + Focus"), (3, "Focus"))),
            None,
            NIKON_CUSTOM_Z9V4_SOURCE,
        ),
        _setting(
            "SettingsZ9v4",
            "5",
            5,
            "AF-SPrioritySelection",
            1,
            "int8u",
            None,
            afs_priority_z9,
            None,
            NIKON_CUSTOM_Z9V4_SOURCE,
        ),
        _setting(
            "SettingsZ9v4",
            "16",
            16,
            "AF-OnOutOfFocusRelease",
            1,
            "int8u",
            None,
            NikonCustomPrintMap(((0, "Disable"), (1, "Enable"))),
            None,
            NIKON_CUSTOM_Z9V4_SOURCE,
            responsibility="known_unknown_flagged_setting",
        ),
        _setting(
            "SettingsZ9v4",
            "27",
            27,
            "ExposureControlStepSize",
            1,
            "int8u",
            None,
            third_half_full,
            None,
            NIKON_CUSTOM_Z9V4_SOURCE,
        ),
        _setting(
            "SettingsZ9v4",
            "613",
            613,
            "EVFWarmDisplayBrightness",
            1,
            "int8s",
            None,
            None,
            None,
            NIKON_CUSTOM_Z9V4_SOURCE,
            responsibility="known_unknown_flagged_setting",
        ),
    )


def _setting(
    table_name: str,
    tag_key: str,
    byte_offset: int,
    tag_name: str,
    size: int,
    value_format: NikonCustomSettingFormat,
    mask: int | None,
    print_map: NikonCustomPrintMap | None,
    condition: str | None,
    evidence_id: str,
    *,
    responsibility: NikonCustomSettingResponsibility = "known_writable_setting",
) -> NikonCustomSettingDefinition:
    return NikonCustomSettingDefinition(
        table_name=table_name,
        tag_key=tag_key,
        byte_offset=byte_offset,
        tag_name=tag_name,
        size=size,
        value_format=value_format,
        mask=mask,
        print_map=print_map,
        responsibility=responsibility,
        condition=condition,
        evidence_ids=(evidence_id,),
    )


def _unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(sources))


def _unique_gates(
    gates: tuple[NikonCustomEmissionGate, ...],
) -> tuple[NikonCustomEmissionGate, ...]:
    return tuple(dict.fromkeys(gates))
