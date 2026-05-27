"""Source-grounded, non-mutating Sony IDC EXIF metadata plans."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

type SonyIDCByteOrder = Literal["little", "big"]
type SonyIDCWritableFormat = Literal["int16u", "int32u", "int32s", "string", "subifd"]
type SonyIDCRole = Literal[
    "preview_offset",
    "preview_length",
    "creative_style",
    "white_balance",
    "adjustment",
    "noise_reduction",
    "d_range_optimizer",
    "tone_curve",
    "lens_correction",
    "geometry",
    "version_stack",
    "time_metadata",
    "unknown",
]
type SonyIDCActionKind = Literal[
    "route_main_table",
    "route_preview_offset_pair",
    "preserve_protected_preview_data",
    "route_known_sony_idc_tag",
    "preserve_tone_curve_values",
    "preserve_unknown_tag",
    "route_source_backed_rewrite",
    "block_requested_rewrite",
    "no_metadata_mutation",
]
type SonyIDCConversionKind = Literal[
    "none",
    "print_conversion",
    "value_conversion",
    "date_time_print_conversion",
    "subifd_offset",
]
type SonyIDCBlockerCode = Literal[
    "truncated_ifd_entry_count",
    "truncated_ifd_entry",
    "truncated_next_ifd_offset",
    "unsupported_tiff_field_type",
    "truncated_ifd_value",
    "missing_preview_offset_pair",
    "preview_data_boundary_out_of_range",
    "malformed_count_for_fixed_tag",
]
type SonyIDCEmissionGateCode = Literal[
    "truncated_ifd_entry_count",
    "truncated_ifd_entry",
    "truncated_next_ifd_offset",
    "unsupported_tiff_field_type",
    "truncated_ifd_value",
    "missing_preview_offset_pair",
    "preview_data_boundary_out_of_range",
    "malformed_count_for_fixed_tag",
    "unsupported_sony_idc_rewrite",
    "source_backed_rewrite_requires_exif_writer",
    "raw_payload_preservation_required",
    "planner_is_non_mutating",
    "sony_idc_writer_not_implemented",
]
type SonyIDCRewriteOperation = Literal["replace_tag", "delete_tag", "insert_tag"]
type SonyIDCValue = int | float | str | bytes | tuple[int, ...]
type SonyIDCFieldValue = int | str | bytes | tuple[int, ...]

SONY_IDC_MAIN_SOURCE = "sony.idc.main.source"
SONY_IDC_PREVIEW_TAG_SOURCE = "sony.idc.preview.tag.source"
SONY_IDC_CREATIVE_SOURCE = "sony.idc.creative.source"
SONY_IDC_WHITE_BALANCE_SOURCE = "sony.idc.white.balance.source"
SONY_IDC_BRIGHTNESS_SOURCE = "sony.idc.brightness.source"
SONY_IDC_NOISE_D_RANGE_SOURCE = "sony.idc.noise.d.range.source"
SONY_IDC_TONE_CURVE_SOURCE = "sony.idc.tone.curve.source"
SONY_IDC_LENS_GEOMETRY_SOURCE = "sony.idc.lens.geometry.source"
SONY_IDC_VERSION_SOURCE = "sony.idc.version.source"
SONY_IDC_COMPOSITE_PREVIEW_SOURCE = "sony.idc.composite.preview.source"
SONY_IDC_PERMANENT_SOURCE = "sony.idc.permanent.source"

TIFF_TYPE_SIZES: dict[int, int] = {
    1: 1,
    2: 1,
    3: 2,
    4: 4,
    7: 1,
    9: 4,
}
TIFF_TYPE_NAMES: dict[int, str] = {
    1: "BYTE",
    2: "ASCII",
    3: "SHORT",
    4: "LONG",
    7: "UNDEFINED",
    9: "SLONG",
}
WRITABLE_FORMAT_TO_TIFF_TYPE: dict[SonyIDCWritableFormat, int] = {
    "int16u": 3,
    "int32u": 4,
    "int32s": 9,
    "string": 2,
    "subifd": 4,
}
CREATIVE_STYLE_PRINT: dict[int, str] = {
    1: "Camera Setting",
    2: "Standard",
    3: "Real",
    4: "Vivid",
    5: "Adobe RGB",
    6: "A100 Standard",
    7: "Neutral",
    8: "Portrait",
    9: "Landscape",
    10: "Clear",
    11: "Deep",
    12: "Light",
    13: "Sunset",
    14: "Night View",
    15: "Autumn Leaves",
    16: "B&W",
    17: "Sepia",
}
YES_NO_PRINT: dict[int, str] = {0: "No", 1: "Yes"}
WHITE_BALANCE_PRINT: dict[int, str] = {
    1: "Camera Setting",
    2: "Color Temperature",
    3: "Specify Gray Point",
    4: "Daylight",
    5: "Cloudy",
    6: "Shade",
    7: "Cool White Fluorescent",
    8: "Day Light Fluorescent",
    9: "Day White Fluorescent",
    10: "Warm White Fluorescent",
    11: "Tungsten",
    12: "Flash",
    13: "Auto",
}
D_RANGE_MODE_PRINT: dict[int, str] = {0: "Off", 1: "Auto", 2: "Manual"}
ON_OFF_PRINT: dict[int, str] = {0: "Off", 1: "On"}
ADVANCED_PRINT: dict[int, str] = {0: "Standard", 1: "Advanced"}
DISTORTION_PRINT: dict[int, str] = {-1: "n/a", 1: "On", 2: "Off"}


@dataclass(frozen=True)
class _SonyIDCTagDefinition:
    tag_name: str
    writable_format: SonyIDCWritableFormat | None
    role: SonyIDCRole
    evidence_ids: tuple[str, ...]
    group2: str = "Image"
    expected_count: int | None = 1
    variable_count: bool = False
    offset_pair_tag_id: int | None = None
    data_tag: str | None = None
    protected_level: int | None = None
    print_map: dict[int, str] | None = None
    conversion_kind: SonyIDCConversionKind = "none"
    conversion_formula: str = ""
    inverse_formula: str = ""


def _tag_definitions() -> dict[int, _SonyIDCTagDefinition]:
    adjustment = SONY_IDC_WHITE_BALANCE_SOURCE
    noise = SONY_IDC_NOISE_D_RANGE_SOURCE
    lens = SONY_IDC_LENS_GEOMETRY_SOURCE
    tags: dict[int, _SonyIDCTagDefinition] = {
        0x0201: _SonyIDCTagDefinition(
            "IDCPreviewStart",
            "int32u",
            "preview_offset",
            (SONY_IDC_PREVIEW_TAG_SOURCE, SONY_IDC_COMPOSITE_PREVIEW_SOURCE),
            offset_pair_tag_id=0x0202,
            data_tag="IDCPreview",
            protected_level=2,
        ),
        0x0202: _SonyIDCTagDefinition(
            "IDCPreviewLength",
            "int32u",
            "preview_length",
            (SONY_IDC_PREVIEW_TAG_SOURCE, SONY_IDC_COMPOSITE_PREVIEW_SOURCE),
            offset_pair_tag_id=0x0201,
            data_tag="IDCPreview",
            protected_level=2,
        ),
        0x8000: _SonyIDCTagDefinition(
            "IDCCreativeStyle",
            "int32u",
            "creative_style",
            (SONY_IDC_CREATIVE_SOURCE,),
            print_map=CREATIVE_STYLE_PRINT,
            conversion_kind="print_conversion",
        ),
        0x8001: _SonyIDCTagDefinition(
            "CreativeStyleWasChanged",
            "int32u",
            "creative_style",
            (SONY_IDC_CREATIVE_SOURCE,),
            print_map=YES_NO_PRINT,
            conversion_kind="print_conversion",
        ),
        0x8002: _SonyIDCTagDefinition(
            "PresetWhiteBalance",
            "int32u",
            "white_balance",
            (SONY_IDC_WHITE_BALANCE_SOURCE,),
            print_map=WHITE_BALANCE_PRINT,
            conversion_kind="print_conversion",
        ),
        0x8013: _SonyIDCTagDefinition(
            "ColorTemperatureAdj", "int16u", "white_balance", (SONY_IDC_WHITE_BALANCE_SOURCE,)
        ),
        0x8014: _SonyIDCTagDefinition(
            "PresetWhiteBalanceAdj", "int32s", "white_balance", (SONY_IDC_WHITE_BALANCE_SOURCE,)
        ),
        0x8015: _SonyIDCTagDefinition("ColorCorrection", "int32s", "adjustment", (adjustment,)),
        0x8016: _SonyIDCTagDefinition("SaturationAdj", "int32s", "adjustment", (adjustment,)),
        0x8017: _SonyIDCTagDefinition("ContrastAdj", "int32s", "adjustment", (adjustment,)),
        0x8018: _SonyIDCTagDefinition(
            "BrightnessAdj",
            "int32s",
            "adjustment",
            (SONY_IDC_BRIGHTNESS_SOURCE,),
            conversion_kind="print_conversion",
            conversion_formula='sprintf("%.2f", raw / 300)',
            inverse_formula="print * 300",
        ),
        0x8019: _SonyIDCTagDefinition("HueAdj", "int32s", "adjustment", (adjustment,)),
        0x801A: _SonyIDCTagDefinition("SharpnessAdj", "int32s", "adjustment", (adjustment,)),
        0x801B: _SonyIDCTagDefinition("SharpnessOvershoot", "int32s", "adjustment", (adjustment,)),
        0x801C: _SonyIDCTagDefinition("SharpnessUndershoot", "int32s", "adjustment", (adjustment,)),
        0x801D: _SonyIDCTagDefinition("SharpnessThreshold", "int32s", "adjustment", (adjustment,)),
        0x801E: _SonyIDCTagDefinition(
            "NoiseReductionMode",
            "int16u",
            "noise_reduction",
            (noise,),
            print_map=ON_OFF_PRINT,
            conversion_kind="print_conversion",
        ),
        0x8021: _SonyIDCTagDefinition(
            "GrayPoint",
            "int16u",
            "white_balance",
            (SONY_IDC_NOISE_D_RANGE_SOURCE,),
            expected_count=4,
        ),
        0x8022: _SonyIDCTagDefinition(
            "D-RangeOptimizerMode",
            "int16u",
            "d_range_optimizer",
            (noise,),
            print_map=D_RANGE_MODE_PRINT,
            conversion_kind="print_conversion",
        ),
        0x8023: _SonyIDCTagDefinition(
            "D-RangeOptimizerValue", "int32s", "d_range_optimizer", (noise,)
        ),
        0x8024: _SonyIDCTagDefinition(
            "D-RangeOptimizerHighlight", "int32s", "d_range_optimizer", (noise,)
        ),
        0x8026: _SonyIDCTagDefinition(
            "HighlightColorDistortReduct",
            "int16u",
            "d_range_optimizer",
            (noise,),
            print_map=ADVANCED_PRINT,
            conversion_kind="print_conversion",
        ),
        0x8027: noise_value_definition("NoiseReductionValue"),
        0x8028: noise_value_definition("EdgeNoiseReduction"),
        0x8029: noise_value_definition("ColorNoiseReduction"),
        0x802D: _SonyIDCTagDefinition(
            "D-RangeOptimizerShadow", "int32s", "d_range_optimizer", (noise,)
        ),
        0x8030: _SonyIDCTagDefinition(
            "PeripheralIllumCentralRadius", "int32s", "lens_correction", (lens,)
        ),
        0x8031: _SonyIDCTagDefinition(
            "PeripheralIllumCentralValue", "int32s", "lens_correction", (lens,)
        ),
        0x8032: _SonyIDCTagDefinition(
            "PeripheralIllumPeriphValue", "int32s", "lens_correction", (lens,)
        ),
        0x8040: _SonyIDCTagDefinition(
            "DistortionCompensation",
            "int32s",
            "lens_correction",
            (SONY_IDC_LENS_GEOMETRY_SOURCE,),
            print_map=DISTORTION_PRINT,
            conversion_kind="print_conversion",
        ),
        0x900D: _SonyIDCTagDefinition(
            "ChromaticAberrationCorrection",
            "int32s",
            "lens_correction",
            (lens,),
            print_map={1: "On", 2: "Off"},
            conversion_kind="print_conversion",
        ),
        0x900E: _SonyIDCTagDefinition(
            "InclinationCorrection",
            "int32u",
            "geometry",
            (lens,),
            print_map=ON_OFF_PRINT,
            conversion_kind="print_conversion",
        ),
        0x900F: _SonyIDCTagDefinition(
            "InclinationAngle",
            "int32s",
            "geometry",
            (lens,),
            conversion_kind="print_conversion",
            conversion_formula='sprintf("%.1f deg", raw / 1000)',
            inverse_formula="ToFloat(print) * 1000",
        ),
        0x9010: _SonyIDCTagDefinition(
            "Cropping",
            "int32u",
            "geometry",
            (lens,),
            print_map=ON_OFF_PRINT,
            conversion_kind="print_conversion",
        ),
        0x9011: _SonyIDCTagDefinition("CropArea", "int32u", "geometry", (lens,), expected_count=4),
        0x9012: _SonyIDCTagDefinition(
            "PreviewImageSize", "int32u", "geometry", (lens,), expected_count=2
        ),
        0x9013: _SonyIDCTagDefinition(
            "PxShiftPeriphEdgeNR",
            "int32s",
            "noise_reduction",
            (lens,),
            print_map=ON_OFF_PRINT,
            conversion_kind="print_conversion",
        ),
        0x9014: _SonyIDCTagDefinition(
            "PxShiftPeriphEdgeNRValue",
            "int32s",
            "noise_reduction",
            (lens,),
            conversion_kind="print_conversion",
            conversion_formula='sprintf("%.1f", raw / 10)',
            inverse_formula="print * 10",
        ),
        0x9017: _SonyIDCTagDefinition("WhitesAdj", "int32s", "adjustment", (lens,)),
        0x9018: _SonyIDCTagDefinition("BlacksAdj", "int32s", "adjustment", (lens,)),
        0x9019: _SonyIDCTagDefinition("HighlightsAdj", "int32s", "adjustment", (lens,)),
        0x901A: _SonyIDCTagDefinition("ShadowsAdj", "int32s", "adjustment", (lens,)),
        0xD000: _SonyIDCTagDefinition(
            "CurrentVersion", "int32u", "version_stack", (SONY_IDC_VERSION_SOURCE,)
        ),
        0xD001: _SonyIDCTagDefinition(
            "VersionIFD",
            "subifd",
            "version_stack",
            (SONY_IDC_VERSION_SOURCE,),
            conversion_kind="subifd_offset",
        ),
        0xD100: _SonyIDCTagDefinition(
            "VersionCreateDate",
            "string",
            "time_metadata",
            (SONY_IDC_VERSION_SOURCE,),
            group2="Time",
            expected_count=None,
            conversion_kind="date_time_print_conversion",
        ),
        0xD101: _SonyIDCTagDefinition(
            "VersionModifyDate",
            "string",
            "time_metadata",
            (SONY_IDC_VERSION_SOURCE,),
            group2="Time",
            expected_count=None,
            conversion_kind="date_time_print_conversion",
        ),
    }
    for tag_id, tag_name in (
        (0x9000, "ToneCurveBrightnessX"),
        (0x9001, "ToneCurveRedX"),
        (0x9002, "ToneCurveGreenX"),
        (0x9003, "ToneCurveBlueX"),
        (0x9004, "ToneCurveBrightnessY"),
        (0x9005, "ToneCurveRedY"),
        (0x9006, "ToneCurveGreenY"),
        (0x9007, "ToneCurveBlueY"),
    ):
        tags[tag_id] = _SonyIDCTagDefinition(
            tag_name,
            "int16u",
            "tone_curve",
            (SONY_IDC_TONE_CURVE_SOURCE,),
            expected_count=None,
            variable_count=True,
        )
    return tags


def noise_value_definition(tag_name: str) -> _SonyIDCTagDefinition:
    return _SonyIDCTagDefinition(
        tag_name,
        "int32s",
        "noise_reduction",
        (SONY_IDC_NOISE_D_RANGE_SOURCE,),
        conversion_kind="value_conversion",
        conversion_formula="(raw + 100) / 2",
        inverse_formula="value * 2 - 100",
    )


TAG_DEFINITIONS = _tag_definitions()


@dataclass(frozen=True)
class SonyIDCRewriteRequest:
    operation: SonyIDCRewriteOperation
    tag: int | str
    value: SonyIDCValue | None = None


@dataclass(frozen=True)
class SonyIDCConversionBoundary:
    kind: SonyIDCConversionKind
    raw_value: SonyIDCFieldValue | None
    converted_value: SonyIDCValue | None
    print_value: str | None
    formula: str
    inverse_formula: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SonyIDCTagPlan:
    index: int
    tag_id: int
    tag_name: str
    role: SonyIDCRole
    family0_group: str
    family1_group: str
    family2_group: str
    tiff_type: int
    tiff_type_name: str
    count: int
    value_or_offset: int
    entry_range: tuple[int, int]
    value_range: tuple[int, int]
    raw_payload: bytes
    raw_value: SonyIDCFieldValue | None
    converted_value: SonyIDCValue | None
    print_value: str | None
    writable_format: SonyIDCWritableFormat | None
    writable_surface: str
    is_known: bool
    is_permanent: bool
    offset_pair_tag_id: int | None
    data_tag: str | None
    protected_level: int | None
    conversion_boundary: SonyIDCConversionBoundary
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SonyIDCPreviewPlan:
    start_tag_id: int
    length_tag_id: int
    data_tag: str
    protected_level: int
    preview_range: tuple[int, int]
    preview_length: int
    raw_preview: bytes
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SonyIDCActionPlan:
    kind: SonyIDCActionKind
    tag_name: str | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SonyIDCResponsibility:
    concern: str
    detail: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SonyIDCEmissionGate:
    code: SonyIDCEmissionGateCode
    reason: str
    offset: int | None
    blocks_emission: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SonyIDCMetadataTransactionPlan:
    byte_order: SonyIDCByteOrder
    family1_group: str
    tag_count: int | None
    next_ifd_offset: int | None
    tags: tuple[SonyIDCTagPlan, ...]
    preview_plan: SonyIDCPreviewPlan | None
    actions: tuple[SonyIDCActionPlan, ...]
    responsibilities: tuple[SonyIDCResponsibility, ...]
    output_emission_gates: tuple[SonyIDCEmissionGate, ...]
    rewrite_requests: tuple[SonyIDCRewriteRequest, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def unknown_tags(self) -> tuple[SonyIDCTagPlan, ...]:
        return tuple(tag for tag in self.tags if not tag.is_known)

    @property
    def tone_curve_tags(self) -> tuple[SonyIDCTagPlan, ...]:
        return tuple(tag for tag in self.tags if tag.role == "tone_curve")

    def tag(self, tag_name: str) -> SonyIDCTagPlan:
        for planned_tag in self.tags:
            if planned_tag.tag_name == tag_name:
                return planned_tag
        raise KeyError(tag_name)

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"Sony IDC metadata transaction output is gated: {gate_codes}")


def build_sony_idc_metadata_transaction_plan(
    data: bytes,
    *,
    byte_order: SonyIDCByteOrder = "little",
    family1_group: str = "SonyIDC",
    rewrite_requests: tuple[SonyIDCRewriteRequest, ...] = (),
) -> SonyIDCMetadataTransactionPlan:
    tags, tag_count, next_ifd_offset, parse_gates = parse_ifd(data, byte_order, family1_group)
    gates = [*parse_gates]
    actions = [
        SonyIDCActionPlan(
            "route_main_table",
            None,
            "Route entries through SonyIDC::Main using EXIF IFD semantics.",
            (SONY_IDC_MAIN_SOURCE,),
        )
    ]
    actions.extend(actions_for_tags(tags))
    preview_plan, preview_gates, preview_actions = build_preview_plan(data, tags)
    gates.extend(preview_gates)
    actions.extend(preview_actions)
    actions.extend(rewrite_actions(rewrite_requests, gates))
    gates.extend(non_mutating_gates())
    actions.append(
        SonyIDCActionPlan(
            "no_metadata_mutation",
            None,
            "This slice plans SonyIDC metadata and does not rewrite bytes.",
            (SONY_IDC_MAIN_SOURCE,),
        )
    )
    responsibilities = default_responsibilities()
    sources = unique_sources(
        (
            *(source for tag in tags for source in tag.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
            *(source for item in responsibilities for source in item.evidence_ids),
            SONY_IDC_MAIN_SOURCE,
            SONY_IDC_PERMANENT_SOURCE,
        )
    )
    return SonyIDCMetadataTransactionPlan(
        byte_order=byte_order,
        family1_group=family1_group,
        tag_count=tag_count,
        next_ifd_offset=next_ifd_offset,
        tags=tags,
        preview_plan=preview_plan,
        actions=tuple(actions),
        responsibilities=responsibilities,
        output_emission_gates=unique_gates(tuple(gates)),
        rewrite_requests=rewrite_requests,
        evidence_ids=sources,
    )


def parse_ifd(
    data: bytes,
    byte_order: SonyIDCByteOrder,
    family1_group: str,
) -> tuple[
    tuple[SonyIDCTagPlan, ...],
    int | None,
    int | None,
    tuple[SonyIDCEmissionGate, ...],
]:
    if len(data) < 2:
        return (
            (),
            None,
            None,
            (
                SonyIDCEmissionGate(
                    "truncated_ifd_entry_count",
                    "SonyIDC IFD data is shorter than the two-byte EXIF entry count.",
                    0,
                    True,
                    (SONY_IDC_MAIN_SOURCE,),
                ),
            ),
        )
    endian = endian_name(byte_order)
    tag_count = int.from_bytes(data[0:2], endian)
    entries_start = 2
    entries_end = entries_start + tag_count * 12
    tags: list[SonyIDCTagPlan] = []
    gates: list[SonyIDCEmissionGate] = []
    for index in range(tag_count):
        entry_start = entries_start + index * 12
        entry_end = entry_start + 12
        if entry_end > len(data):
            gates.append(
                SonyIDCEmissionGate(
                    "truncated_ifd_entry",
                    f"SonyIDC IFD entry {index} at offset {entry_start} exceeds input length.",
                    entry_start,
                    True,
                    (SONY_IDC_MAIN_SOURCE,),
                )
            )
            return tuple(tags), tag_count, None, tuple(gates)
        tag_plan, tag_gates = parse_ifd_entry(data, index, entry_start, byte_order, family1_group)
        tags.append(tag_plan)
        gates.extend(tag_gates)
    next_ifd_offset: int | None = None
    if entries_end + 4 > len(data):
        gates.append(
            SonyIDCEmissionGate(
                "truncated_next_ifd_offset",
                "SonyIDC IFD is missing the four-byte next-IFD offset after entries.",
                entries_end,
                True,
                (SONY_IDC_MAIN_SOURCE,),
            )
        )
    else:
        next_ifd_offset = int.from_bytes(data[entries_end : entries_end + 4], endian)
    return tuple(tags), tag_count, next_ifd_offset, tuple(gates)


def parse_ifd_entry(
    data: bytes,
    index: int,
    entry_start: int,
    byte_order: SonyIDCByteOrder,
    family1_group: str,
) -> tuple[SonyIDCTagPlan, tuple[SonyIDCEmissionGate, ...]]:
    endian = endian_name(byte_order)
    entry = data[entry_start : entry_start + 12]
    tag_id = int.from_bytes(entry[0:2], endian)
    tiff_type = int.from_bytes(entry[2:4], endian)
    count = int.from_bytes(entry[4:8], endian)
    value_or_offset = int.from_bytes(entry[8:12], endian)
    definition = TAG_DEFINITIONS.get(tag_id)
    type_size = TIFF_TYPE_SIZES.get(tiff_type)
    raw_payload = b""
    value_range = (entry_start + 8, entry_start + 12)
    gates: list[SonyIDCEmissionGate] = []
    if type_size is None:
        gates.append(
            SonyIDCEmissionGate(
                "unsupported_tiff_field_type",
                f"SonyIDC tag 0x{tag_id:04x} uses unsupported TIFF type {tiff_type}.",
                entry_start + 2,
                True,
                (SONY_IDC_MAIN_SOURCE,),
            )
        )
    else:
        payload_size = count * type_size
        if payload_size <= 4:
            raw_payload = entry[8 : 8 + payload_size]
            value_range = (entry_start + 8, entry_start + 8 + payload_size)
        else:
            payload_start = value_or_offset
            payload_end = payload_start + payload_size
            value_range = (payload_start, payload_end)
            if payload_end > len(data):
                gates.append(
                    SonyIDCEmissionGate(
                        "truncated_ifd_value",
                        (
                            f"SonyIDC tag 0x{tag_id:04x} value range {payload_start}:"
                            f"{payload_end} exceeds input length {len(data)}."
                        ),
                        payload_start,
                        True,
                        sources_for_tag(definition),
                    )
                )
            else:
                raw_payload = data[payload_start:payload_end]
    fixed_count_gate = fixed_count_gate_for_tag(definition, count, entry_start)
    if fixed_count_gate is not None:
        gates.append(fixed_count_gate)

    raw_value = decode_value(raw_payload, tiff_type, count, byte_order)
    converted_value, print_value = convert_value(definition, raw_value)
    conversion_boundary = conversion_boundary_for_definition(
        definition, raw_value, converted_value, print_value
    )
    tag_name = definition.tag_name if definition is not None else f"Unknown_0x{tag_id:04x}"
    role = definition.role if definition is not None else "unknown"
    writable_format = definition.writable_format if definition is not None else None
    return (
        SonyIDCTagPlan(
            index=index,
            tag_id=tag_id,
            tag_name=tag_name,
            role=role,
            family0_group="MakerNotes",
            family1_group=family1_group,
            family2_group=definition.group2 if definition is not None else "Image",
            tiff_type=tiff_type,
            tiff_type_name=TIFF_TYPE_NAMES.get(tiff_type, f"UNKNOWN({tiff_type})"),
            count=count,
            value_or_offset=value_or_offset,
            entry_range=(entry_start, entry_start + 12),
            value_range=value_range,
            raw_payload=raw_payload,
            raw_value=raw_value,
            converted_value=converted_value,
            print_value=print_value,
            writable_format=writable_format,
            writable_surface=writable_surface(definition),
            is_known=definition is not None,
            is_permanent=definition is not None,
            offset_pair_tag_id=definition.offset_pair_tag_id if definition is not None else None,
            data_tag=definition.data_tag if definition is not None else None,
            protected_level=definition.protected_level if definition is not None else None,
            conversion_boundary=conversion_boundary,
            evidence_ids=sources_for_tag(definition),
        ),
        tuple(gates),
    )


def fixed_count_gate_for_tag(
    definition: _SonyIDCTagDefinition | None,
    count: int,
    offset: int,
) -> SonyIDCEmissionGate | None:
    if definition is None or definition.variable_count or definition.expected_count is None:
        return None
    if count == definition.expected_count:
        return None
    return SonyIDCEmissionGate(
        "malformed_count_for_fixed_tag",
        (
            f"{definition.tag_name} declares count {definition.expected_count} in SonyIDC.pm "
            f"but the IFD entry stores count {count}."
        ),
        offset,
        True,
        definition.evidence_ids,
    )


def build_preview_plan(
    data: bytes,
    tags: tuple[SonyIDCTagPlan, ...],
) -> tuple[
    SonyIDCPreviewPlan | None,
    tuple[SonyIDCEmissionGate, ...],
    tuple[SonyIDCActionPlan, ...],
]:
    start_tags = [tag for tag in tags if tag.tag_id == 0x0201]
    length_tags = [tag for tag in tags if tag.tag_id == 0x0202]
    if not start_tags and not length_tags:
        return None, (), ()
    actions = (
        SonyIDCActionPlan(
            "route_preview_offset_pair",
            "IDCPreview",
            "Route IDCPreviewStart and IDCPreviewLength as a protected OffsetPair.",
            (SONY_IDC_PREVIEW_TAG_SOURCE, SONY_IDC_COMPOSITE_PREVIEW_SOURCE),
        ),
    )
    if not start_tags or not length_tags:
        return (
            None,
            (
                SonyIDCEmissionGate(
                    "missing_preview_offset_pair",
                    "IDC preview extraction requires both IDCPreviewStart and IDCPreviewLength.",
                    None,
                    True,
                    (SONY_IDC_PREVIEW_TAG_SOURCE, SONY_IDC_COMPOSITE_PREVIEW_SOURCE),
                ),
            ),
            actions,
        )
    start_value = numeric_value(start_tags[0].raw_value)
    length_value = numeric_value(length_tags[0].raw_value)
    preview_end = start_value + length_value
    if start_value < 0 or length_value < 0 or preview_end > len(data):
        return (
            None,
            (
                SonyIDCEmissionGate(
                    "preview_data_boundary_out_of_range",
                    (
                        f"IDCPreview protected range {start_value}:{preview_end} exceeds "
                        f"input length {len(data)}."
                    ),
                    start_value,
                    True,
                    (SONY_IDC_PREVIEW_TAG_SOURCE, SONY_IDC_COMPOSITE_PREVIEW_SOURCE),
                ),
            ),
            actions,
        )
    preview_plan = SonyIDCPreviewPlan(
        start_tag_id=0x0201,
        length_tag_id=0x0202,
        data_tag="IDCPreview",
        protected_level=2,
        preview_range=(start_value, preview_end),
        preview_length=length_value,
        raw_preview=data[start_value:preview_end],
        evidence_ids=(SONY_IDC_PREVIEW_TAG_SOURCE, SONY_IDC_COMPOSITE_PREVIEW_SOURCE),
    )
    return (
        preview_plan,
        (),
        (
            *actions,
            SonyIDCActionPlan(
                "preserve_protected_preview_data",
                "IDCPreview",
                "Preserve bytes referenced by the Protected level 2 preview boundary.",
                (SONY_IDC_PREVIEW_TAG_SOURCE, SONY_IDC_COMPOSITE_PREVIEW_SOURCE),
            ),
        ),
    )


def rewrite_actions(
    rewrite_requests: tuple[SonyIDCRewriteRequest, ...],
    gates: list[SonyIDCEmissionGate],
) -> tuple[SonyIDCActionPlan, ...]:
    actions: list[SonyIDCActionPlan] = []
    for request in rewrite_requests:
        definition = definition_for_rewrite_target(request.tag)
        if definition is None:
            gates.append(
                SonyIDCEmissionGate(
                    "unsupported_sony_idc_rewrite",
                    (
                        f"Rewrite request {request.operation} for {request.tag!r} has "
                        "no SonyIDC.pm tag."
                    ),
                    None,
                    True,
                    (SONY_IDC_MAIN_SOURCE,),
                )
            )
            actions.append(
                SonyIDCActionPlan(
                    "block_requested_rewrite",
                    str(request.tag),
                    "Requested rewrite target is not defined by SonyIDC.pm.",
                    (SONY_IDC_MAIN_SOURCE,),
                )
            )
        else:
            gates.append(
                SonyIDCEmissionGate(
                    "source_backed_rewrite_requires_exif_writer",
                    (
                        f"Rewrite request {request.operation} for {definition.tag_name} is "
                        "source-backed but requires the downstream EXIF writer."
                    ),
                    None,
                    True,
                    definition.evidence_ids,
                )
            )
            actions.append(
                SonyIDCActionPlan(
                    "route_source_backed_rewrite",
                    definition.tag_name,
                    (
                        "Requested rewrite target is defined by SonyIDC.pm and deferred "
                        "to EXIF writing."
                    ),
                    definition.evidence_ids,
                )
            )
    return tuple(actions)


def actions_for_tags(tags: tuple[SonyIDCTagPlan, ...]) -> tuple[SonyIDCActionPlan, ...]:
    actions: list[SonyIDCActionPlan] = []
    for tag in tags:
        if tag.is_known:
            kind: SonyIDCActionKind = "route_known_sony_idc_tag"
            reason = f"Route {tag.tag_name} through SonyIDC::Main."
            if tag.role == "tone_curve":
                kind = "preserve_tone_curve_values"
                reason = "Preserve variable-count tone-curve values."
            actions.append(SonyIDCActionPlan(kind, tag.tag_name, reason, tag.evidence_ids))
        else:
            actions.append(
                SonyIDCActionPlan(
                    "preserve_unknown_tag",
                    tag.tag_name,
                    "Unknown SonyIDC tag is retained as raw EXIF entry payload.",
                    (SONY_IDC_MAIN_SOURCE,),
                )
            )
    return tuple(actions)


def non_mutating_gates() -> tuple[SonyIDCEmissionGate, ...]:
    return (
        SonyIDCEmissionGate(
            "raw_payload_preservation_required",
            "SonyIDC raw IFD and protected payload bytes must be preserved by a real writer.",
            None,
            True,
            (SONY_IDC_MAIN_SOURCE, SONY_IDC_PREVIEW_TAG_SOURCE),
        ),
        SonyIDCEmissionGate(
            "planner_is_non_mutating",
            "The SonyIDC transaction planner does not mutate bytes.",
            None,
            True,
            (SONY_IDC_MAIN_SOURCE,),
        ),
        SonyIDCEmissionGate(
            "sony_idc_writer_not_implemented",
            "SonyIDC.pm delegates writing to Exif::WriteExif; this slice records the plan only.",
            None,
            True,
            (SONY_IDC_MAIN_SOURCE,),
        ),
    )


def default_responsibilities() -> tuple[SonyIDCResponsibility, ...]:
    return (
        SonyIDCResponsibility(
            "main_table_routing",
            "Use SonyIDC::Main as the tag table routed through EXIF read/write helpers.",
            (SONY_IDC_MAIN_SOURCE,),
        ),
        SonyIDCResponsibility(
            "preview_offset_pair_and_protected_boundary",
            (
                "Pair IDCPreviewStart and IDCPreviewLength and preserve Protected "
                "level 2 preview bytes."
            ),
            (SONY_IDC_PREVIEW_TAG_SOURCE, SONY_IDC_COMPOSITE_PREVIEW_SOURCE),
        ),
        SonyIDCResponsibility(
            "creative_style_white_balance_noise_d_range_and_tone_curve_tags",
            "Classify the Sony IDC edit controls declared by the Main table.",
            (
                SONY_IDC_CREATIVE_SOURCE,
                SONY_IDC_WHITE_BALANCE_SOURCE,
                SONY_IDC_NOISE_D_RANGE_SOURCE,
                SONY_IDC_TONE_CURVE_SOURCE,
            ),
        ),
        SonyIDCResponsibility(
            "writable_exif_backed_classification",
            (
                "Known writable SonyIDC tags are EXIF-backed entries and source-backed "
                "rewrites are deferred."
            ),
            (SONY_IDC_MAIN_SOURCE,),
        ),
        SonyIDCResponsibility(
            "conversion_boundaries",
            "Expose print and value conversion boundaries without collapsing raw storage values.",
            (SONY_IDC_BRIGHTNESS_SOURCE, SONY_IDC_NOISE_D_RANGE_SOURCE),
        ),
        SonyIDCResponsibility(
            "unknown_tag_preservation",
            "Preserve unknown SonyIDC tag payloads without interpretation.",
            (SONY_IDC_MAIN_SOURCE,),
        ),
        SonyIDCResponsibility(
            "malformed_and_truncation_blockers",
            (
                "Block emission when IFD structure, value ranges, counts, or preview "
                "boundaries are invalid."
            ),
            (SONY_IDC_MAIN_SOURCE, SONY_IDC_PREVIEW_TAG_SOURCE),
        ),
        SonyIDCResponsibility(
            "non_mutating_defaults",
            "Default plans are analysis-only and never emit rewritten bytes.",
            (SONY_IDC_MAIN_SOURCE,),
        ),
    )


def decode_value(
    raw_payload: bytes,
    tiff_type: int,
    count: int,
    byte_order: SonyIDCByteOrder,
) -> SonyIDCFieldValue | None:
    if not raw_payload:
        return None
    endian = endian_name(byte_order)
    if tiff_type == 2:
        return raw_payload.rstrip(b"\x00").decode("latin-1")
    if tiff_type in {1, 7}:
        return raw_payload
    unit_size = TIFF_TYPE_SIZES.get(tiff_type)
    if unit_size is None:
        return raw_payload
    values: list[int] = []
    signed = tiff_type == 9
    for start in range(0, min(len(raw_payload), count * unit_size), unit_size):
        unit = raw_payload[start : start + unit_size]
        if len(unit) == unit_size:
            values.append(int.from_bytes(unit, endian, signed=signed))
    if count == 1 and values:
        return values[0]
    return tuple(values)


def convert_value(
    definition: _SonyIDCTagDefinition | None,
    raw_value: SonyIDCFieldValue | None,
) -> tuple[SonyIDCValue | None, str | None]:
    if definition is None or raw_value is None:
        return raw_value, None
    if definition.print_map is not None and isinstance(raw_value, int):
        return raw_value, definition.print_map.get(raw_value)
    if definition.tag_name == "BrightnessAdj" and isinstance(raw_value, int):
        return raw_value, f"{raw_value / 300:.2f}"
    if definition.tag_name == "InclinationAngle" and isinstance(raw_value, int):
        return raw_value, f"{raw_value / 1000:.1f} deg"
    if definition.tag_name == "PxShiftPeriphEdgeNRValue" and isinstance(raw_value, int):
        return raw_value, f"{raw_value / 10:.1f}"
    if definition.conversion_kind == "value_conversion" and isinstance(raw_value, int):
        return (raw_value + 100) / 2, None
    return raw_value, None


def conversion_boundary_for_definition(
    definition: _SonyIDCTagDefinition | None,
    raw_value: SonyIDCFieldValue | None,
    converted_value: SonyIDCValue | None,
    print_value: str | None,
) -> SonyIDCConversionBoundary:
    if definition is None:
        return SonyIDCConversionBoundary(
            "none", raw_value, converted_value, print_value, "", "", ()
        )
    return SonyIDCConversionBoundary(
        definition.conversion_kind,
        raw_value,
        converted_value,
        print_value,
        definition.conversion_formula,
        definition.inverse_formula,
        definition.evidence_ids,
    )


def definition_for_rewrite_target(tag: int | str) -> _SonyIDCTagDefinition | None:
    if isinstance(tag, int):
        return TAG_DEFINITIONS.get(tag)
    for definition in TAG_DEFINITIONS.values():
        if definition.tag_name == tag:
            return definition
    return None


def writable_surface(definition: _SonyIDCTagDefinition | None) -> str:
    if definition is None:
        return "preserve_unknown"
    if definition.writable_format == "subifd":
        return "exif_subifd_route"
    if definition.writable_format is None:
        return "read_only"
    return "exif_write_exif"


def sources_for_tag(
    definition: _SonyIDCTagDefinition | None,
) -> tuple[str, ...]:
    if definition is None:
        return (SONY_IDC_MAIN_SOURCE, SONY_IDC_PERMANENT_SOURCE)
    return unique_sources((*definition.evidence_ids, SONY_IDC_PERMANENT_SOURCE))


def numeric_value(value: SonyIDCFieldValue | None) -> int:
    if isinstance(value, int):
        return value
    return -1


def endian_name(byte_order: SonyIDCByteOrder) -> Literal["little", "big"]:
    if byte_order == "big":
        return "big"
    return "little"


def unique_sources(sources: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for source in sources:
        key = source
        if key not in seen:
            seen.add(key)
            unique.append(source)
    return tuple(unique)


def unique_gates(
    gates: tuple[SonyIDCEmissionGate, ...],
) -> tuple[SonyIDCEmissionGate, ...]:
    seen: set[tuple[SonyIDCEmissionGateCode, int | None, str]] = set()
    unique: list[SonyIDCEmissionGate] = []
    for gate in gates:
        key = (gate.code, gate.offset, gate.reason)
        if key not in seen:
            seen.add(key)
            unique.append(gate)
    return tuple(unique)
