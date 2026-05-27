"""Source-grounded Nikon settings transaction planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type NikonByteOrder = Literal["little", "big"]
type NikonPlanStatus = Literal["planned", "unsupported"]
type NikonCameraFamily = Literal["d_model", "z_model", "unknown"]
type NikonSettingGroup = Literal[
    "iso",
    "autofocus",
    "exposure",
    "flash",
    "display",
    "controls",
    "movie",
    "playback",
    "storage",
    "power",
    "unknown",
]
type NikonValueClass = Literal[
    "source_known_setting",
    "source_known_reduced_output_setting",
    "unknown_preserved",
]
type NikonConversionBoundary = Literal[
    "none",
    "print_conversion",
    "conditional_print_conversion",
    "raw_condition_context",
    "value_conversion",
]
type NikonActionKind = Literal[
    "route_settings_table",
    "extract_known_setting",
    "preserve_known_reduced_output_setting",
    "preserve_unknown_setting",
    "block_requested_rewrite",
]
type NikonOutputGateCode = Literal[
    "truncated_nikon_settings_header",
    "truncated_nikon_settings_entries",
    "malformed_nikon_settings_format",
    "unknown_rewrite_tag",
    "missing_source_setting_for_rewrite",
    "duplicate_rewrite_tag",
    "nikon_settings_rewrite_not_supported",
    "non_mutating_plan_requires_explicit_emission",
]
type NikonResponsibilityConcern = Literal[
    "header_validation",
    "setting_table_routing",
    "known_setting_classification",
    "conditional_setting_resolution",
    "unknown_payload_preservation",
    "rewrite_gating",
]
type NikonRawValue = int
type NikonInterpretedValue = int | str

NIKON_SETTINGS_PM_SOURCE_PATH = "lib/Image/ExifTool/NikonSettings.pm"


def evidence_id(
    line_start: int,
    line_end: int,
    symbol: str,
    evidence: str,
) -> str:
    del line_start, line_end, evidence
    return "nikon.settings." + _evidence_token(symbol)


def _evidence_token(symbol: str) -> str:
    return (
        symbol.removeprefix("%Image::ExifTool::")
        .replace("::", ".")
        .replace("%", "")
        .replace(" ", "-")
        .lower()
    )


NIKON_SETTINGS_MAIN_SOURCE = evidence_id(
    402,
    407,
    "%Image::ExifTool::NikonSettings::Main",
    "NikonSettings::Main routes newer Nikon user settings in MakerNotes/Camera groups.",
)
NIKON_SETTINGS_READER_SOURCE = evidence_id(
    2063,
    2118,
    "ProcessNikonSettings",
    "ProcessNikonSettings validates the 24-byte header and extracts 8-byte setting entries.",
)
NIKON_SETTINGS_HEADER_SOURCE = evidence_id(
    2070,
    2077,
    "NikonSettings directory header",
    (
        "The header stores two 0100 markers, camera family, model-generation code, "
        "firmware, and count."
    ),
)
NIKON_SETTINGS_FORMAT_SOURCE = evidence_id(
    2095,
    2109,
    "NikonSettings entry extraction",
    "Entries contain a tag, a format byte that must be 4, and a four-byte int32u value.",
)
NIKON_SETTINGS_UNKNOWN_SOURCE = evidence_id(
    405,
    407,
    "NikonSettings Unknown note",
    "The table marks some tags Unknown only to reduce normal output volume.",
)
NIKON_ISO_SOURCE = evidence_id(
    410,
    462,
    "ISOAutoHiLimit and ISOAutoFlashLimit",
    "NikonSettings defines D6 and Z7/Z7_2 ISO auto high-limit setting variants.",
)
NIKON_AF_SOURCE = evidence_id(
    602,
    629,
    "AF priority and activation settings",
    "NikonSettings defines AF-C, AF-S, AF point, and AF activation settings.",
)
NIKON_EXPOSURE_SOURCE = evidence_id(
    640,
    688,
    "Exposure and metering settings",
    "NikonSettings defines EV step size and fine-tune metering value conversions.",
)
NIKON_DISPLAY_SOURCE = evidence_id(
    775,
    790,
    "Release and display settings",
    "NikonSettings defines exposure delay and framing-grid display settings.",
)
NIKON_BUTTON_SOURCE = evidence_id(
    1162,
    1185,
    "Func button settings",
    "Func1Button and Func2Button route to D6, Z6/Z7, and Z-series print conversion maps.",
)
NIKON_REDUCED_OUTPUT_SOURCE = evidence_id(
    1506,
    1527,
    "Unknown-reduced limit settings",
    "Limit AF-area and selectable-image-area tags are marked Unknown to reduce output volume.",
)
NIKON_PLAYBACK_SOURCE = evidence_id(
    1598,
    1603,
    "SubDialFrameAdvanceRating settings",
    "Sub-dial frame-advance rating settings are source-known but marked Unknown.",
)
NIKON_FLICK_SOURCE = evidence_id(
    1906,
    1909,
    "Playback flick settings",
    (
        "Playback flick rating settings are meaningful only when the related flick direction "
        "is Rating."
    ),
)
NIKON_SHUTTER_SOURCE = evidence_id(
    1920,
    1927,
    "ShutterType and LensFunc2Button",
    "Z-series shutter and lens-function settings are defined in NikonSettings::Main.",
)


@dataclass(frozen=True)
class NikonSettingsRewriteRequest:
    tag_name: str
    raw_value: int


@dataclass(frozen=True)
class NikonSettingVariant:
    label_by_value: dict[int, str]
    condition: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonSettingSpec:
    tag_id: int
    name: str
    setting_group: NikonSettingGroup
    conversion_boundary: NikonConversionBoundary
    variants: tuple[NikonSettingVariant, ...]
    reduced_default_output: bool
    evidence_ids: tuple[str, ...]

    @property
    def value_class(self) -> NikonValueClass:
        if self.reduced_default_output:
            return "source_known_reduced_output_setting"
        return "source_known_setting"


@dataclass(frozen=True)
class NikonSettingsHeaderPlan:
    magic_prefix: bytes
    camera_family_code: int
    camera_family: NikonCameraFamily
    magic_middle: bytes
    model_generation_code: int
    firmware: bytes
    entry_count: int
    byte_range: tuple[int, int]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonSettingsEntryPlan:
    tag_id: int
    unknown_format_high_byte: int
    format_code: int
    raw_value: int
    entry_range: tuple[int, int]
    raw_payload: bytes


@dataclass(frozen=True)
class NikonSettingsFieldPlan:
    tag_name: str
    tag_id: int
    setting_group: NikonSettingGroup
    byte_range: tuple[int, int]
    raw_payload: bytes
    raw_value: NikonRawValue
    interpreted_value: NikonInterpretedValue
    value_class: NikonValueClass
    conversion_boundary: NikonConversionBoundary
    model_condition: str | None
    is_unknown: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonSettingsRoutingPlan:
    table: str
    byte_order: NikonByteOrder
    model: str | None
    header: NikonSettingsHeaderPlan
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonSettingsPreservationPlan:
    payload_range: tuple[int, int]
    unknown_tag_ids: tuple[int, ...]
    reduced_output_tag_names: tuple[str, ...]
    raw_payloads: tuple[bytes, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonSettingsResponsibilityPlan:
    concern: NikonResponsibilityConcern
    summary: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonSettingsActionPlan:
    kind: NikonActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonSettingsOutputEmissionGate:
    code: NikonOutputGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class NikonSettingsTransactionPlan:
    status: NikonPlanStatus
    source_data: bytes
    routing: NikonSettingsRoutingPlan
    fields: tuple[NikonSettingsFieldPlan, ...]
    preservation: NikonSettingsPreservationPlan
    responsibilities: tuple[NikonSettingsResponsibilityPlan, ...]
    actions: tuple[NikonSettingsActionPlan, ...]
    output_emission_gates: tuple[NikonSettingsOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def source_known_tags(self) -> tuple[str, ...]:
        return tuple(field.tag_name for field in self.fields if not field.is_unknown)

    def field(self, tag_name: str) -> NikonSettingsFieldPlan:
        for field in self.fields:
            if field.tag_name == tag_name:
                return field
        raise KeyError(tag_name)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Nikon settings transaction output is gated: {gate_codes}")
        return self.source_data


ENABLE_DISABLE = {1: "Enable", 2: "Disable"}
ON_OFF = {1: "On", 2: "Off"}
OFF_ON = {1: "Off", 2: "On"}
YES_NO = {1: "Yes", 2: "No"}
NO_YES = {1: "No", 2: "Yes"}
RELEASE_FOCUS = {1: "Release", 2: "Focus"}
THIRD_HALF_FULL = {1: "1/3 EV", 2: "1/2 EV", 3: "1 EV"}
LIMIT_NO_LIMIT = {1: "Limit", 2: "No Limit"}
FLICK_UP_DOWN_D6 = {
    1: "Rating",
    2: "Select To Send",
    3: "Protect",
    4: "Voice Memo",
    5: "None",
}
FLICK_RATING_D6 = {
    1: "Rating 5",
    2: "Rating 4",
    3: "Rating 3",
    4: "Rating 2",
    5: "Rating 1",
    6: "Candidate for Deletion",
}
ISO_AUTO_HIGH_LIMIT_D6 = {
    1: "ISO 200",
    13: "ISO 1600",
    37: "ISO 102400",
    41: "ISO Hi 1.0",
}
ISO_AUTO_HIGH_LIMIT_Z7 = {
    1: "ISO 100",
    17: "ISO 1600",
    33: "ISO 25600",
    41: "ISO Hi 1.0",
}
FUNC_BUTTON_Z6 = {
    1: "AF-On or Subject Tracking",
    20: "Framing Grid Display",
    30: "White Balance",
    44: "None",
}
FUNC_BUTTON_Z7M2 = {
    1: "AF-On",
    20: "Subject Tracking",
    23: "Grid Display",
    33: "White Balance",
    52: "None",
}
PREVIEW_BUTTON_D6 = {
    1: "Preset Focus Point - Press To Recall",
    23: "AF-On",
    40: "Grid Display",
    56: "None",
}
SHUTTER_TYPE = {1: "Auto", 2: "Mechanical", 3: "Electronic"}
LENS_FUNC_BUTTON_Z7M2 = {
    1: "AF-On",
    20: "Subject Tracking",
    23: "Zoom (1:1)",
    28: "None",
}


def variant(
    label_by_value: dict[int, str],
    condition: str | None,
    references: tuple[str, ...],
) -> NikonSettingVariant:
    return NikonSettingVariant(label_by_value, condition, references)


SETTING_SPECS: tuple[NikonSettingSpec, ...] = (
    NikonSettingSpec(
        0x001,
        "ISOAutoHiLimit",
        "iso",
        "conditional_print_conversion",
        (
            variant(ISO_AUTO_HIGH_LIMIT_D6, "D6", (NIKON_ISO_SOURCE,)),
            variant(ISO_AUTO_HIGH_LIMIT_Z7, "Z7 or Z7_2", (NIKON_ISO_SOURCE,)),
        ),
        False,
        (NIKON_ISO_SOURCE,),
    ),
    NikonSettingSpec(
        0x00B,
        "FlickerReductionShooting",
        "display",
        "print_conversion",
        (variant(ENABLE_DISABLE, None, (NIKON_SETTINGS_MAIN_SOURCE,)),),
        False,
        (NIKON_SETTINGS_MAIN_SOURCE,),
    ),
    NikonSettingSpec(
        0x01D,
        "AF-CPrioritySel",
        "autofocus",
        "conditional_print_conversion",
        (
            variant(
                {1: "Release", 2: "Release + Focus", 3: "Focus + Release", 4: "Focus"},
                "D6",
                (NIKON_AF_SOURCE,),
            ),
            variant(RELEASE_FOCUS, "Z Series", (NIKON_AF_SOURCE,)),
        ),
        False,
        (NIKON_AF_SOURCE,),
    ),
    NikonSettingSpec(
        0x01E,
        "AF-SPrioritySel",
        "autofocus",
        "print_conversion",
        (variant(RELEASE_FOCUS, None, (NIKON_AF_SOURCE,)),),
        False,
        (NIKON_AF_SOURCE,),
    ),
    NikonSettingSpec(
        0x022,
        "AFActivation",
        "autofocus",
        "print_conversion",
        (variant({1: "Shutter/AF-On", 2: "AF-On Only"}, None, (NIKON_AF_SOURCE,)),),
        False,
        (NIKON_AF_SOURCE,),
    ),
    NikonSettingSpec(
        0x02F,
        "FineTuneOptMatrixMetering",
        "exposure",
        "value_conversion",
        (variant({}, None, (NIKON_EXPOSURE_SOURCE,)),),
        False,
        (NIKON_EXPOSURE_SOURCE,),
    ),
    NikonSettingSpec(
        0x040,
        "ExposureDelayMode",
        "exposure",
        "print_conversion",
        (
            variant(
                {1: "3 s", 2: "2 s", 3: "1 s", 4: "0.5 s", 5: "0.2 s", 6: "Off"},
                None,
                (NIKON_DISPLAY_SOURCE,),
            ),
        ),
        False,
        (NIKON_DISPLAY_SOURCE,),
    ),
    NikonSettingSpec(
        0x043,
        "FramingGridDisplay",
        "display",
        "print_conversion",
        (variant(ON_OFF, None, (NIKON_DISPLAY_SOURCE,)),),
        False,
        (NIKON_DISPLAY_SOURCE,),
    ),
    NikonSettingSpec(
        0x0A0,
        "Func1Button",
        "controls",
        "conditional_print_conversion",
        (
            variant(PREVIEW_BUTTON_D6, "D6", (NIKON_BUTTON_SOURCE,)),
            variant(FUNC_BUTTON_Z6, "Z6 or Z7", (NIKON_BUTTON_SOURCE,)),
            variant(FUNC_BUTTON_Z7M2, "Z Series", (NIKON_BUTTON_SOURCE,)),
        ),
        False,
        (NIKON_BUTTON_SOURCE,),
    ),
    NikonSettingSpec(
        0x0B8,
        "LimitAFAreaModeSelD9",
        "autofocus",
        "print_conversion",
        (variant(LIMIT_NO_LIMIT, None, (NIKON_REDUCED_OUTPUT_SOURCE,)),),
        True,
        (NIKON_REDUCED_OUTPUT_SOURCE, NIKON_SETTINGS_UNKNOWN_SOURCE),
    ),
    NikonSettingSpec(
        0x0F2,
        "SubDialFrameAdvanceRating5",
        "playback",
        "print_conversion",
        (variant(NO_YES, None, (NIKON_PLAYBACK_SOURCE,)),),
        True,
        (NIKON_PLAYBACK_SOURCE, NIKON_SETTINGS_UNKNOWN_SOURCE),
    ),
    NikonSettingSpec(
        0x139,
        "PlaybackFlickUp",
        "playback",
        "raw_condition_context",
        (variant(FLICK_UP_DOWN_D6, "D6", (NIKON_FLICK_SOURCE,)),),
        False,
        (NIKON_FLICK_SOURCE,),
    ),
    NikonSettingSpec(
        0x13A,
        "PlaybackFlickUpRating",
        "playback",
        "conditional_print_conversion",
        (variant(FLICK_RATING_D6, "PlaybackFlickUp == Rating", (NIKON_FLICK_SOURCE,)),),
        False,
        (NIKON_FLICK_SOURCE,),
    ),
    NikonSettingSpec(
        0x150,
        "ShutterType",
        "exposure",
        "print_conversion",
        (variant(SHUTTER_TYPE, "Z7_2", (NIKON_SHUTTER_SOURCE,)),),
        False,
        (NIKON_SHUTTER_SOURCE,),
    ),
    NikonSettingSpec(
        0x151,
        "LensFunc2Button",
        "controls",
        "print_conversion",
        (variant(LENS_FUNC_BUTTON_Z7M2, "Z7_2", (NIKON_SHUTTER_SOURCE,)),),
        False,
        (NIKON_SHUTTER_SOURCE,),
    ),
)
SETTING_SPECS_BY_ID = {spec.tag_id: spec for spec in SETTING_SPECS}
SETTING_SPECS_BY_NAME = {spec.name: spec for spec in SETTING_SPECS}


def build_nikon_settings_transaction_plan(
    source_data: bytes,
    *,
    byte_order: NikonByteOrder = "little",
    model: str | None = None,
    rewrite_requests: tuple[NikonSettingsRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> NikonSettingsTransactionPlan:
    placeholder_header = NikonSettingsHeaderPlan(
        b"",
        0,
        "unknown",
        b"",
        0,
        b"",
        0,
        (0, min(len(source_data), 24)),
        (NIKON_SETTINGS_HEADER_SOURCE,),
    )
    routing = NikonSettingsRoutingPlan(
        "Image::ExifTool::NikonSettings::Main",
        byte_order,
        model,
        placeholder_header,
        (NIKON_SETTINGS_MAIN_SOURCE, NIKON_SETTINGS_READER_SOURCE),
    )
    if len(source_data) < 24:
        gate = NikonSettingsOutputEmissionGate(
            "truncated_nikon_settings_header",
            "NikonSettings directories must include the 24-byte settings header.",
            (NIKON_SETTINGS_READER_SOURCE, NIKON_SETTINGS_HEADER_SOURCE),
        )
        return unsupported_plan(source_data, routing, (gate,))

    header = parse_header(source_data, byte_order)
    routing = NikonSettingsRoutingPlan(
        "Image::ExifTool::NikonSettings::Main",
        byte_order,
        model,
        header,
        (NIKON_SETTINGS_MAIN_SOURCE, NIKON_SETTINGS_READER_SOURCE),
    )
    entries_end = 24 + (header.entry_count * 8)
    if len(source_data) < entries_end:
        gate = NikonSettingsOutputEmissionGate(
            "truncated_nikon_settings_entries",
            "NikonSettings entry count exceeds the available 8-byte entry records.",
            (NIKON_SETTINGS_READER_SOURCE, NIKON_SETTINGS_FORMAT_SOURCE),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entries: list[NikonSettingsEntryPlan] = []
    for index in range(header.entry_count):
        entry = parse_entry(source_data, 24 + (index * 8), byte_order)
        if isinstance(entry, NikonSettingsOutputEmissionGate):
            return unsupported_plan(source_data, routing, (entry,))
        entries.append(entry)

    fields, field_actions = build_fields(tuple(entries), model)
    rewrite_gates, rewrite_actions = plan_rewrites(fields, rewrite_requests)
    output_gates = list(rewrite_gates)
    if not rewrite_requests and not allow_output_emission:
        output_gates.append(
            NikonSettingsOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "The default NikonSettings plan records routing and preservation decisions only.",
                (NIKON_SETTINGS_READER_SOURCE,),
            )
        )

    actions = (
        NikonSettingsActionPlan(
            "route_settings_table",
            "Image::ExifTool::NikonSettings::Main",
            (0, len(source_data)),
            "Route the NikonSettings directory through NikonSettings::Main.",
            routing.evidence_ids,
        ),
        *field_actions,
        *rewrite_actions,
    )
    preservation = preservation_plan(source_data, fields)
    responsibilities = responsibility_plans(fields, rewrite_requests)
    gates = tuple(output_gates)
    return NikonSettingsTransactionPlan(
        "planned",
        source_data,
        routing,
        fields,
        preservation,
        responsibilities,
        actions,
        gates,
        collect_evidence_ids(fields, responsibilities, actions, gates),
    )


def parse_header(source_data: bytes, byte_order: NikonByteOrder) -> NikonSettingsHeaderPlan:
    camera_family_code = read_u32(source_data, 4, byte_order)
    camera_family: NikonCameraFamily = "unknown"
    if camera_family_code == 1:
        camera_family = "d_model"
    elif camera_family_code == 2:
        camera_family = "z_model"
    return NikonSettingsHeaderPlan(
        source_data[0:4],
        camera_family_code,
        camera_family,
        source_data[8:12],
        read_u32(source_data, 12, byte_order),
        source_data[16:20],
        read_u32(source_data, 20, byte_order),
        (0, 24),
        (NIKON_SETTINGS_HEADER_SOURCE,),
    )


def parse_entry(
    source_data: bytes,
    entry_offset: int,
    byte_order: NikonByteOrder,
) -> NikonSettingsEntryPlan | NikonSettingsOutputEmissionGate:
    tag_id = int.from_bytes(source_data[entry_offset : entry_offset + 2], "big")
    format_code = source_data[entry_offset + 3]
    if format_code != 4:
        return NikonSettingsOutputEmissionGate(
            "malformed_nikon_settings_format",
            f"NikonSettings tag 0x{tag_id:04x} uses unsupported format byte {format_code}.",
            (NIKON_SETTINGS_READER_SOURCE, NIKON_SETTINGS_FORMAT_SOURCE),
        )
    return NikonSettingsEntryPlan(
        tag_id,
        source_data[entry_offset + 2],
        format_code,
        read_u32(source_data, entry_offset + 4, byte_order),
        (entry_offset, entry_offset + 8),
        source_data[entry_offset : entry_offset + 8],
    )


def build_fields(
    entries: tuple[NikonSettingsEntryPlan, ...],
    model: str | None,
) -> tuple[tuple[NikonSettingsFieldPlan, ...], tuple[NikonSettingsActionPlan, ...]]:
    context: dict[str, int] = {}
    fields: list[NikonSettingsFieldPlan] = []
    actions: list[NikonSettingsActionPlan] = []
    for entry in entries:
        field = field_for_entry(entry, model, context)
        fields.append(field)
        if not field.is_unknown:
            context[field.tag_name] = field.raw_value
        action_kind: NikonActionKind = "extract_known_setting"
        reason = "Extract source-known NikonSettings scalar setting."
        if field.value_class == "source_known_reduced_output_setting":
            action_kind = "preserve_known_reduced_output_setting"
            reason = (
                "Preserve source-known setting that NikonSettings marks Unknown for output volume."
            )
        elif field.is_unknown:
            action_kind = "preserve_unknown_setting"
            reason = "Preserve unclaimed NikonSettings entry bytes."
        actions.append(
            NikonSettingsActionPlan(
                action_kind,
                field.tag_name,
                field.byte_range,
                reason,
                field.evidence_ids,
            )
        )
    return tuple(fields), tuple(actions)


def field_for_entry(
    entry: NikonSettingsEntryPlan,
    model: str | None,
    context: dict[str, int],
) -> NikonSettingsFieldPlan:
    spec = SETTING_SPECS_BY_ID.get(entry.tag_id)
    if spec is None:
        refs = (NIKON_SETTINGS_MAIN_SOURCE, NIKON_SETTINGS_UNKNOWN_SOURCE)
        return NikonSettingsFieldPlan(
            f"NikonSettings_0x{entry.tag_id:04x}",
            entry.tag_id,
            "unknown",
            entry.entry_range,
            entry.raw_payload,
            entry.raw_value,
            entry.raw_value,
            "unknown_preserved",
            "none",
            None,
            True,
            refs,
        )
    selected_variant = select_variant(spec, model, context)
    interpreted = interpret_value(spec, selected_variant, entry.raw_value)
    return NikonSettingsFieldPlan(
        spec.name,
        spec.tag_id,
        spec.setting_group,
        entry.entry_range,
        entry.raw_payload,
        entry.raw_value,
        interpreted,
        spec.value_class,
        spec.conversion_boundary,
        selected_variant.condition,
        False,
        merge_references((*spec.evidence_ids, *selected_variant.evidence_ids)),
    )


def select_variant(
    spec: NikonSettingSpec,
    model: str | None,
    context: dict[str, int],
) -> NikonSettingVariant:
    model_value = model or ""
    for setting_variant in spec.variants:
        condition = setting_variant.condition
        if condition is None:
            return setting_variant
        if condition == "D6" and model_value.upper().startswith("NIKON D6"):
            return setting_variant
        if condition == "Z7 or Z7_2" and model_value.upper().startswith(
            ("NIKON Z 7", "NIKON Z 7_2")
        ):
            return setting_variant
        if condition == "Z6 or Z7" and model_value.upper() in {"NIKON Z 6", "NIKON Z 7"}:
            return setting_variant
        if condition == "Z7_2" and model_value.upper().startswith("NIKON Z 7_2"):
            return setting_variant
        if condition == "Z Series" and is_z_series_model(model_value):
            return setting_variant
        if condition == "PlaybackFlickUp == Rating" and context.get("PlaybackFlickUp") == 1:
            return setting_variant
    return spec.variants[-1]


def interpret_value(
    spec: NikonSettingSpec,
    selected_variant: NikonSettingVariant,
    raw_value: int,
) -> NikonInterpretedValue:
    if spec.name.startswith("FineTuneOpt"):
        adjusted = (raw_value - 7) / 6
        return "0" if adjusted == 0 else f"{adjusted:+.2f}"
    if spec.name == "SelfTimerShotCount":
        return 10 - raw_value
    label = selected_variant.label_by_value.get(raw_value)
    if label is not None:
        return label
    return raw_value


def preservation_plan(
    source_data: bytes,
    fields: tuple[NikonSettingsFieldPlan, ...],
) -> NikonSettingsPreservationPlan:
    unknown_tag_ids = tuple(field.tag_id for field in fields if field.is_unknown)
    reduced_output_tag_names = tuple(
        field.tag_name
        for field in fields
        if field.value_class == "source_known_reduced_output_setting"
    )
    raw_payloads = tuple(field.raw_payload for field in fields)
    refs = (NIKON_SETTINGS_READER_SOURCE, NIKON_SETTINGS_UNKNOWN_SOURCE)
    return NikonSettingsPreservationPlan(
        (0, len(source_data)),
        unknown_tag_ids,
        reduced_output_tag_names,
        raw_payloads,
        refs,
    )


def responsibility_plans(
    fields: tuple[NikonSettingsFieldPlan, ...],
    rewrite_requests: tuple[NikonSettingsRewriteRequest, ...],
) -> tuple[NikonSettingsResponsibilityPlan, ...]:
    plans: list[NikonSettingsResponsibilityPlan] = [
        NikonSettingsResponsibilityPlan(
            "header_validation",
            "Validate the NikonSettings header before reading setting entries.",
            (NIKON_SETTINGS_HEADER_SOURCE, NIKON_SETTINGS_READER_SOURCE),
        ),
        NikonSettingsResponsibilityPlan(
            "setting_table_routing",
            "Route entries through Image::ExifTool::NikonSettings::Main.",
            (NIKON_SETTINGS_MAIN_SOURCE, NIKON_SETTINGS_READER_SOURCE),
        ),
        NikonSettingsResponsibilityPlan(
            "known_setting_classification",
            "Classify source-known settings by NikonSettings tag responsibility.",
            collect_field_references(fields),
        ),
    ]
    if any(field.conversion_boundary == "conditional_print_conversion" for field in fields):
        plans.append(
            NikonSettingsResponsibilityPlan(
                "conditional_setting_resolution",
                "Resolve model- and context-dependent print conversion tables without rewriting.",
                collect_field_references(fields),
            )
        )
    if any(field.is_unknown for field in fields) or any(
        field.value_class == "source_known_reduced_output_setting" for field in fields
    ):
        plans.append(
            NikonSettingsResponsibilityPlan(
                "unknown_payload_preservation",
                "Preserve unclaimed entries and source-known reduced-output entries byte-for-byte.",
                (NIKON_SETTINGS_UNKNOWN_SOURCE, NIKON_SETTINGS_READER_SOURCE),
            )
        )
    if rewrite_requests:
        plans.append(
            NikonSettingsResponsibilityPlan(
                "rewrite_gating",
                "Reject requested NikonSettings rewrites until a byte writer owns table updates.",
                (NIKON_SETTINGS_READER_SOURCE,),
            )
        )
    return tuple(plans)


def plan_rewrites(
    fields: tuple[NikonSettingsFieldPlan, ...],
    rewrite_requests: tuple[NikonSettingsRewriteRequest, ...],
) -> tuple[tuple[NikonSettingsOutputEmissionGate, ...], tuple[NikonSettingsActionPlan, ...]]:
    gates: list[NikonSettingsOutputEmissionGate] = []
    actions: list[NikonSettingsActionPlan] = []
    fields_by_name = {field.tag_name: field for field in fields}
    seen: set[str] = set()
    for request in rewrite_requests:
        refs: tuple[str, ...] = (NIKON_SETTINGS_READER_SOURCE,)
        field = fields_by_name.get(request.tag_name)
        if request.tag_name in seen:
            code: NikonOutputGateCode = "duplicate_rewrite_tag"
            reason = f"NikonSettings rewrite requested more than once for {request.tag_name}."
        elif request.tag_name not in SETTING_SPECS_BY_NAME:
            code = "unknown_rewrite_tag"
            reason = f"NikonSettings has no source-backed writable route for {request.tag_name}."
        elif field is None:
            code = "missing_source_setting_for_rewrite"
            reason = f"NikonSettings source does not contain {request.tag_name}."
        else:
            code = "nikon_settings_rewrite_not_supported"
            reason = "NikonSettings.pm reads settings, but this package slice has no byte writer."
            refs = field.evidence_ids
        seen.add(request.tag_name)
        gate = NikonSettingsOutputEmissionGate(code, reason, refs)
        gates.append(gate)
        actions.append(
            NikonSettingsActionPlan(
                "block_requested_rewrite",
                request.tag_name,
                field.byte_range if field is not None else None,
                reason,
                refs,
            )
        )
    return tuple(gates), tuple(actions)


def unsupported_plan(
    source_data: bytes,
    routing: NikonSettingsRoutingPlan,
    gates: tuple[NikonSettingsOutputEmissionGate, ...],
) -> NikonSettingsTransactionPlan:
    actions = (
        NikonSettingsActionPlan(
            "route_settings_table",
            "Image::ExifTool::NikonSettings::Main",
            (0, len(source_data)),
            "NikonSettings routing could not be completed.",
            routing.evidence_ids,
        ),
    )
    responsibilities = (
        NikonSettingsResponsibilityPlan(
            "header_validation",
            "Validate the NikonSettings header and entry table before field planning.",
            (NIKON_SETTINGS_HEADER_SOURCE, NIKON_SETTINGS_READER_SOURCE),
        ),
    )
    preservation = NikonSettingsPreservationPlan(
        (0, len(source_data)),
        (),
        (),
        (),
        (NIKON_SETTINGS_READER_SOURCE,),
    )
    return NikonSettingsTransactionPlan(
        "unsupported",
        source_data,
        routing,
        (),
        preservation,
        responsibilities,
        actions,
        gates,
        collect_evidence_ids((), responsibilities, actions, gates),
    )


def collect_evidence_ids(
    fields: tuple[NikonSettingsFieldPlan, ...],
    responsibilities: tuple[NikonSettingsResponsibilityPlan, ...],
    actions: tuple[NikonSettingsActionPlan, ...],
    gates: tuple[NikonSettingsOutputEmissionGate, ...],
) -> tuple[str, ...]:
    references: list[str] = [
        NIKON_SETTINGS_MAIN_SOURCE,
        NIKON_SETTINGS_READER_SOURCE,
        NIKON_SETTINGS_HEADER_SOURCE,
        NIKON_SETTINGS_FORMAT_SOURCE,
    ]
    for field in fields:
        references.extend(field.evidence_ids)
    for responsibility in responsibilities:
        references.extend(responsibility.evidence_ids)
    for action in actions:
        references.extend(action.evidence_ids)
    for gate in gates:
        references.extend(gate.evidence_ids)
    return merge_references(tuple(references))


def collect_field_references(
    fields: tuple[NikonSettingsFieldPlan, ...],
) -> tuple[str, ...]:
    references: list[str] = []
    for field in fields:
        references.extend(field.evidence_ids)
    return merge_references(tuple(references))


def merge_references(references: tuple[str, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for reference in references:
        if reference not in seen:
            seen.add(reference)
            merged.append(reference)
    return tuple(merged)


def read_u32(source_data: bytes, offset: int, byte_order: NikonByteOrder) -> int:
    return int.from_bytes(source_data[offset : offset + 4], byte_order)


def is_z_series_model(model: str) -> bool:
    return model.upper().startswith(
        (
            "NIKON Z 5",
            "NIKON Z 50",
            "NIKON Z 6",
            "NIKON Z 6_2",
            "NIKON Z 7",
            "NIKON Z 7_2",
            "NIKON Z FC",
        )
    )
