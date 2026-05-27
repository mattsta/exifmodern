"""Source-grounded Sony maker-note transaction planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type SonyByteOrder = Literal["little", "big"]
type SonyPlanStatus = Literal["planned", "unsupported"]
type SonyExifTypeName = Literal[
    "byte",
    "ascii",
    "short",
    "long",
    "rational",
    "undefined",
    "slong",
    "srational",
]
type SonyWritableFormat = Literal[
    "int8u",
    "int16u",
    "int16s",
    "int32u",
    "int32s",
    "rational64s",
    "string",
    "undef",
]
type SonyValueClass = Literal[
    "writable_exif_scalar",
    "read_only_subdirectory",
    "read_only_data_block",
    "unknown_cipher_preserved",
    "unknown_preserved",
]
type SonyConversionBoundary = Literal[
    "none",
    "binary_tiff_output",
    "print_conversion",
    "signed_print_conversion",
    "count_based_subdirectory",
    "model_based_subdirectory",
    "payload_header_subdirectory",
    "preview_header_boundary",
    "hidden_offset_pair",
    "shot_face_info_boundary",
    "lens_database_boundary",
    "pixel_shift_boundary",
    "unknown_cipher_boundary",
]
type SonyActionKind = Literal[
    "route_main_table",
    "extract_known_tag",
    "route_subdirectory",
    "preserve_data_block",
    "preserve_unknown_cipher_tag",
    "preserve_unknown_tag",
    "block_requested_rewrite",
]
type SonyOutputGateCode = Literal[
    "truncated_ifd_header",
    "truncated_ifd_entry",
    "truncated_tag_value",
    "malformed_entry_type",
    "unknown_rewrite_tag",
    "missing_source_tag_for_rewrite",
    "duplicate_rewrite_tag",
    "read_only_subdirectory_rewrite",
    "sony_makernote_rewrite_not_supported",
    "non_mutating_plan_requires_explicit_emission",
]
type SonyResponsibilityConcern = Literal[
    "main_table_routing",
    "binary_subtable_routing",
    "terminal_binary_tiff_output",
    "encrypted_subtable_preservation",
    "preview_payload_preservation",
    "hidden_data_offset_pair",
    "shot_face_info_subdirectories",
    "unknown_tag_preservation",
    "rewrite_gating",
]
type SonyRawValue = int | str | tuple[int, ...] | tuple[int, int] | bytes | None
type SonyInterpretedValue = int | str | tuple[int, ...] | bytes | None

SONY_MAIN_SOURCE = "sony.makernote.main"
SONY_EXIF_WRITE_SOURCE = "sony.makernote.exif_write_surface"
SONY_CAMERA_INFO_SOURCE = "sony.makernote.camera_info_route"
SONY_FOCUS_MORE_SOURCE = "sony.makernote.focus_more_route"
SONY_FOCUS_TIFF_SOURCE = "sony.makernote.focus_tiff_metering_image"
SONY_QUALITY_SOURCE = "sony.makernote.quality"
SONY_CAMERA_SETTINGS_SOURCE = "sony.makernote.camera_settings_route"
SONY_EXTRA_INFO_SOURCE = "sony.makernote.extra_info_route"
SONY_PREVIEW_SOURCE = "sony.makernote.preview_image"
SONY_TAG2010_SOURCE = "sony.makernote.tag2010_route"
SONY_AF_SOURCE = "sony.makernote.focus_af_route"
SONY_TAG202A_SOURCE = "sony.makernote.tag202a"
SONY_PIXEL_SHIFT_SOURCE = "sony.makernote.pixel_shift_info"
SONY_HIDDEN_INFO_SOURCE = "sony.makernote.hidden_info_route"
SONY_SHOT_INFO_SOURCE = "sony.makernote.shot_info_route"
SONY_ENCRYPTED_SOURCE = "sony.makernote.encrypted_block_note"
SONY_TAG9050_SOURCE = "sony.makernote.tag9050_route"
SONY_TAG9400_SOURCE = "sony.makernote.tag9400_route"
SONY_TAG940E_ROUTE_SOURCE = "sony.makernote.tag940e_route"
SONY_MODEL_ID_SOURCE = "sony.makernote.model_id"
SONY_CREATIVE_SOURCE = "sony.makernote.creative_style"
SONY_LENS_SOURCE = "sony.makernote.lens"
SONY_DSC_SOURCE = "sony.makernote.dsc_settings"
SONY_HIDDEN_TABLE_SOURCE = "sony.makernote.hidden_info_table"
SONY_SHOT_TABLE_SOURCE = "sony.makernote.shot_info_table"
SONY_TAG2010_TABLE_SOURCE = "sony.makernote.tag2010_table"
SONY_METER_INFO_SOURCE = "sony.makernote.meter_info"
SONY_MORE_INFO_PROCESS_SOURCE = "sony.makernote.process_more_info"
SONY_MORE_INFO_TIFF_SOURCE = "sony.makernote.more_info_tiff_metering_image"
SONY_TAG940E_TIFF_SOURCE = "sony.makernote.tag940e_tiff_metering_image"
SONY_PANORAMA_SOURCE = "sony.makernote.panorama"


@dataclass(frozen=True)
class SonyRewriteRequest:
    tag_name: str
    raw_payload: bytes


@dataclass(frozen=True)
class SonyTagSpec:
    tag_id: int
    name: str
    writable_format: SonyWritableFormat | None
    conversion_boundary: SonyConversionBoundary
    evidence_ids: tuple[str, ...]

    @property
    def value_class(self) -> SonyValueClass:
        if self.writable_format is None:
            return "read_only_subdirectory"
        if self.name == "PreviewImage":
            return "read_only_data_block"
        return "writable_exif_scalar"


@dataclass(frozen=True)
class SonyIfdEntryPlan:
    tag_id: int
    exif_type: SonyExifTypeName
    count: int
    entry_range: tuple[int, int]
    value_range: tuple[int, int]
    raw_payload: bytes
    payload_is_inline: bool


@dataclass(frozen=True)
class SonyTerminalSurfacePlan:
    tag_name: str
    boundary: SonyConversionBoundary
    runtime_status: str
    scalar_reader_ready: bool
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SonySubdirectoryPlan:
    tag_name: str
    table: str
    byte_order: SonyByteOrder | None
    reason: str
    evidence_ids: tuple[str, ...]
    terminal_surfaces: tuple[SonyTerminalSurfacePlan, ...] = ()


@dataclass(frozen=True)
class SonyFieldPlan:
    tag_name: str
    tag_id: int
    exif_type: SonyExifTypeName
    count: int
    byte_range: tuple[int, int]
    raw_payload: bytes
    raw_value: SonyRawValue
    interpreted_value: SonyInterpretedValue
    value_class: SonyValueClass
    writable_format: SonyWritableFormat | None
    conversion_boundary: SonyConversionBoundary
    is_unknown: bool
    subdirectory: SonySubdirectoryPlan | None
    evidence_ids: tuple[str, ...]

    @property
    def is_writable_exif_backed(self) -> bool:
        return self.value_class == "writable_exif_scalar"


@dataclass(frozen=True)
class SonyRoutingPlan:
    table: str
    byte_order: SonyByteOrder
    entry_count: int
    model: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SonyPreservationPlan:
    payload_range: tuple[int, int]
    unknown_tag_ids: tuple[int, ...]
    unknown_cipher_tag_ids: tuple[int, ...]
    data_block_tag_names: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SonyResponsibilityPlan:
    concern: SonyResponsibilityConcern
    summary: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SonyActionPlan:
    kind: SonyActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SonyOutputEmissionGate:
    code: SonyOutputGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SonyMakerNoteTransactionPlan:
    status: SonyPlanStatus
    source_data: bytes
    routing: SonyRoutingPlan
    fields: tuple[SonyFieldPlan, ...]
    preservation: SonyPreservationPlan
    responsibilities: tuple[SonyResponsibilityPlan, ...]
    actions: tuple[SonyActionPlan, ...]
    output_emission_gates: tuple[SonyOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def writable_exif_backed_tags(self) -> tuple[str, ...]:
        return tuple(field.tag_name for field in self.fields if field.is_writable_exif_backed)

    def field(self, tag_name: str) -> SonyFieldPlan:
        for field in self.fields:
            if field.tag_name == tag_name:
                return field
        raise KeyError(tag_name)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Sony maker-note transaction output is gated: {gate_codes}")
        return self.source_data


EXIF_TYPE_SIZES = {
    1: 1,
    2: 1,
    3: 2,
    4: 4,
    5: 8,
    7: 1,
    9: 4,
    10: 8,
}
EXIF_TYPE_NAMES: dict[int, SonyExifTypeName] = {
    1: "byte",
    2: "ascii",
    3: "short",
    4: "long",
    5: "rational",
    7: "undefined",
    9: "slong",
    10: "srational",
}
QUALITY_LABELS = {
    0: "RAW",
    1: "Super Fine",
    2: "Fine",
    3: "Standard",
    4: "Economy",
    5: "Extra Fine",
    6: "RAW + JPEG/HEIF",
    7: "Compressed RAW",
    8: "Compressed RAW + JPEG",
    9: "Light",
    0xFFFFFFFF: "n/a",
}
WHITE_BALANCE_LABELS = {
    0x00: "Auto",
    0x01: "Color Temperature/Color Filter",
    0x10: "Daylight",
    0x20: "Cloudy",
    0x30: "Shade",
    0x40: "Tungsten",
    0x50: "Flash",
    0x60: "Fluorescent",
    0x70: "Custom",
    0x80: "Underwater",
}
FOCUS_MODE_LABELS = {0: "Manual", 2: "AF-S", 3: "AF-C", 4: "AF-A", 6: "DMF", 7: "AF-D"}
AF_AREA_ILCE_LABELS = {
    0: "Wide",
    1: "Center",
    3: "Flexible Spot",
    4: "Flexible Spot (LA-EA4)",
    9: "Center (LA-EA4)",
    11: "Zone",
    12: "Expanded Flexible Spot",
    13: "Custom AF Area",
}
PRIORITY_AWB_LABELS = {0: "Standard", 1: "Ambience", 2: "White"}
METERING_MODE2_LABELS = {
    0x100: "Multi-segment",
    0x200: "Center-weighted average",
    0x301: "Spot (Standard)",
    0x302: "Spot (Large)",
    0x400: "Average",
    0x500: "Highlight",
}
QUALITY_202E_LABELS = {
    (0, 0): "n/a",
    (0, 1): "Standard",
    (0, 2): "Fine",
    (0, 3): "Extra Fine",
    (0, 4): "Light",
    (1, 0): "RAW",
    (1, 1): "RAW + Standard",
    (1, 2): "RAW + Fine",
    (1, 3): "RAW + Extra Fine",
    (1, 4): "RAW + Light",
    (4, 0): "Compressed RAW",
    (4, 1): "Compressed RAW + Standard",
    (5, 0): "Compressed (HQ) RAW",
}
SONY_MODEL_LABELS = {
    256: "DSLR-A100",
    297: "DSC-RX100",
    357: "ILCE-6300",
    363: "ILCE-7M3",
    379: "ILCE-6100",
    388: "ILCE-7M4",
    394: "ILCE-6700",
    407: "ILCE-7M5",
}
CREATIVE_STYLE_LABELS = {
    "AdobeRGB": "Adobe RGB",
    "BW": "B&W",
    "Nightview": "Night View/Portrait",
    "VV2": "Vivid 2",
}

SCALAR_TAG_SPECS: tuple[SonyTagSpec, ...] = (
    SonyTagSpec(0x0102, "Quality", "int32u", "print_conversion", (SONY_QUALITY_SOURCE,)),
    SonyTagSpec(0x0104, "FlashExposureComp", "rational64s", "none", (SONY_MAIN_SOURCE,)),
    SonyTagSpec(0x0115, "WhiteBalance", "int32u", "print_conversion", (SONY_MAIN_SOURCE,)),
    SonyTagSpec(0x2001, "PreviewImage", "undef", "preview_header_boundary", (SONY_PREVIEW_SOURCE,)),
    SonyTagSpec(0x2002, "Rating", "int32u", "none", (SONY_MAIN_SOURCE,)),
    SonyTagSpec(0x2004, "Contrast", "int32s", "signed_print_conversion", (SONY_MAIN_SOURCE,)),
    SonyTagSpec(0x2005, "Saturation", "int32s", "signed_print_conversion", (SONY_MAIN_SOURCE,)),
    SonyTagSpec(0x2006, "Sharpness", "int32s", "signed_print_conversion", (SONY_MAIN_SOURCE,)),
    SonyTagSpec(0x2007, "Brightness", "int32s", "signed_print_conversion", (SONY_MAIN_SOURCE,)),
    SonyTagSpec(0x201B, "FocusMode", "int8u", "print_conversion", (SONY_AF_SOURCE,)),
    SonyTagSpec(0x201C, "AFAreaModeSetting", "int8u", "print_conversion", (SONY_AF_SOURCE,)),
    SonyTagSpec(0x202B, "PrioritySetInAWB", "int8u", "print_conversion", (SONY_MAIN_SOURCE,)),
    SonyTagSpec(0x202C, "MeteringMode2", "int16u", "print_conversion", (SONY_MAIN_SOURCE,)),
    SonyTagSpec(
        0x202D,
        "ExposureStandardAdjustment",
        "rational64s",
        "signed_print_conversion",
        (SONY_MAIN_SOURCE,),
    ),
    SonyTagSpec(0x202E, "Quality2", "int16u", "print_conversion", (SONY_MAIN_SOURCE,)),
    SonyTagSpec(
        0x202F, "PixelShiftInfo", "undef", "pixel_shift_boundary", (SONY_PIXEL_SHIFT_SOURCE,)
    ),
    SonyTagSpec(0x2031, "SerialNumber", "string", "print_conversion", (SONY_MAIN_SOURCE,)),
    SonyTagSpec(0xB000, "SonyModelID", "int16u", "print_conversion", (SONY_MODEL_ID_SOURCE,)),
    SonyTagSpec(0xB020, "CreativeStyle", "string", "print_conversion", (SONY_CREATIVE_SOURCE,)),
    SonyTagSpec(0xB021, "ColorTemperature", "int32u", "print_conversion", (SONY_CREATIVE_SOURCE,)),
    SonyTagSpec(0xB027, "LensType", "int32u", "lens_database_boundary", (SONY_LENS_SOURCE,)),
    SonyTagSpec(0xB02A, "LensSpec", "int8u", "lens_database_boundary", (SONY_LENS_SOURCE,)),
    SonyTagSpec(0xB040, "Macro", "int16u", "print_conversion", (SONY_DSC_SOURCE,)),
    SonyTagSpec(0xB047, "JPEGQuality", "int16u", "print_conversion", (SONY_DSC_SOURCE,)),
)
SCALAR_TAGS_BY_ID = {spec.tag_id: spec for spec in SCALAR_TAG_SPECS}
SCALAR_TAGS_BY_NAME = {spec.name: spec for spec in SCALAR_TAG_SPECS}


def build_sony_makernote_transaction_plan(
    source_data: bytes,
    *,
    byte_order: SonyByteOrder = "little",
    model: str | None = None,
    rewrite_requests: tuple[SonyRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> SonyMakerNoteTransactionPlan:
    routing = SonyRoutingPlan(
        "Image::ExifTool::Sony::Main",
        byte_order,
        0,
        model,
        (SONY_MAIN_SOURCE, SONY_EXIF_WRITE_SOURCE),
    )
    if len(source_data) < 2:
        gate = SonyOutputEmissionGate(
            "truncated_ifd_header",
            "Sony maker-note IFD header must contain a two-byte entry count.",
            (SONY_MAIN_SOURCE,),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entry_count = read_u16(source_data, 0, byte_order)
    routing = SonyRoutingPlan(
        "Image::ExifTool::Sony::Main",
        byte_order,
        entry_count,
        model,
        (SONY_MAIN_SOURCE, SONY_EXIF_WRITE_SOURCE),
    )
    entry_region_end = 2 + (entry_count * 12) + 4
    if len(source_data) < entry_region_end:
        gate = SonyOutputEmissionGate(
            "truncated_ifd_entry",
            "Sony maker-note IFD entries and next-directory pointer are incomplete.",
            (SONY_MAIN_SOURCE,),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entries: list[SonyIfdEntryPlan] = []
    parse_gates: list[SonyOutputEmissionGate] = []
    for index in range(entry_count):
        entry_offset = 2 + (index * 12)
        parsed_entry = parse_ifd_entry(source_data, entry_offset, byte_order)
        if isinstance(parsed_entry, SonyOutputEmissionGate):
            parse_gates.append(parsed_entry)
        else:
            entries.append(parsed_entry)

    if parse_gates:
        return unsupported_plan(source_data, routing, tuple(parse_gates))

    fields, field_actions = build_fields(tuple(entries), byte_order, model)
    rewrite_gates, rewrite_actions = plan_rewrites(fields, rewrite_requests)
    output_gates = list(rewrite_gates)
    if not rewrite_requests and not allow_output_emission:
        output_gates.append(
            SonyOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "The default Sony maker-note plan records decisions without emitting bytes.",
                (SONY_EXIF_WRITE_SOURCE,),
            )
        )

    actions = (
        SonyActionPlan(
            "route_main_table",
            "Image::ExifTool::Sony::Main",
            (0, len(source_data)),
            "Use the Sony Main EXIF maker-note table.",
            (SONY_MAIN_SOURCE, SONY_EXIF_WRITE_SOURCE),
        ),
        *field_actions,
        *rewrite_actions,
    )
    preservation = preservation_plan(source_data, fields)
    responsibilities = responsibility_plans(fields)
    gates = tuple(output_gates)
    return SonyMakerNoteTransactionPlan(
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


def unsupported_plan(
    source_data: bytes,
    routing: SonyRoutingPlan,
    gates: tuple[SonyOutputEmissionGate, ...],
) -> SonyMakerNoteTransactionPlan:
    actions = (
        SonyActionPlan(
            "route_main_table",
            "Image::ExifTool::Sony::Main",
            (0, len(source_data)),
            "Sony maker-note routing could not be completed.",
            routing.evidence_ids,
        ),
    )
    responsibilities = (
        SonyResponsibilityPlan(
            "main_table_routing",
            "Validate and route the Sony Main maker-note IFD before any field planning.",
            (SONY_MAIN_SOURCE, SONY_EXIF_WRITE_SOURCE),
        ),
    )
    return SonyMakerNoteTransactionPlan(
        "unsupported",
        source_data,
        routing,
        (),
        SonyPreservationPlan((0, len(source_data)), (), (), (), (SONY_MAIN_SOURCE,)),
        responsibilities,
        actions,
        gates,
        collect_evidence_ids((), responsibilities, actions, gates),
    )


def parse_ifd_entry(
    source_data: bytes,
    entry_offset: int,
    byte_order: SonyByteOrder,
) -> SonyIfdEntryPlan | SonyOutputEmissionGate:
    tag_id = read_u16(source_data, entry_offset, byte_order)
    type_id = read_u16(source_data, entry_offset + 2, byte_order)
    if type_id not in EXIF_TYPE_SIZES:
        return SonyOutputEmissionGate(
            "malformed_entry_type",
            f"Sony maker-note tag 0x{tag_id:04x} uses unsupported EXIF type {type_id}.",
            (SONY_MAIN_SOURCE,),
        )
    count = read_u32(source_data, entry_offset + 4, byte_order)
    byte_count = EXIF_TYPE_SIZES[type_id] * count
    value_slot = source_data[entry_offset + 8 : entry_offset + 12]
    if byte_count <= 4:
        value_range = (entry_offset + 8, entry_offset + 8 + byte_count)
        raw_payload = value_slot[:byte_count]
        payload_is_inline = True
    else:
        value_offset = int.from_bytes(value_slot, byte_order)
        value_end = value_offset + byte_count
        if value_offset > len(source_data) or value_end > len(source_data):
            return SonyOutputEmissionGate(
                "truncated_tag_value",
                f"Sony maker-note tag 0x{tag_id:04x} points outside the source bytes.",
                (SONY_MAIN_SOURCE,),
            )
        value_range = (value_offset, value_end)
        raw_payload = source_data[value_offset:value_end]
        payload_is_inline = False
    return SonyIfdEntryPlan(
        tag_id,
        EXIF_TYPE_NAMES[type_id],
        count,
        (entry_offset, entry_offset + 12),
        value_range,
        raw_payload,
        payload_is_inline,
    )


def build_fields(
    entries: tuple[SonyIfdEntryPlan, ...],
    byte_order: SonyByteOrder,
    model: str | None,
) -> tuple[tuple[SonyFieldPlan, ...], tuple[SonyActionPlan, ...]]:
    fields: list[SonyFieldPlan] = []
    actions: list[SonyActionPlan] = []
    for entry in entries:
        subdirectory = subdirectory_for_entry(entry, model)
        if subdirectory is not None:
            field = subdirectory_field(entry, subdirectory)
            actions.append(
                SonyActionPlan(
                    "route_subdirectory",
                    field.tag_name,
                    field.byte_range,
                    subdirectory.reason,
                    field.evidence_ids,
                )
            )
        elif entry.tag_id in {0x2010, 0x9050, 0x9400}:
            field = unknown_cipher_field(entry)
            actions.append(
                SonyActionPlan(
                    "preserve_unknown_cipher_tag",
                    field.tag_name,
                    field.byte_range,
                    "Preserve encrypted Sony maker-note data that did not match a routed table.",
                    field.evidence_ids,
                )
            )
        else:
            scalar_field = scalar_or_unknown_field(entry, byte_order)
            field = scalar_field
            action_kind: SonyActionKind = (
                "preserve_data_block"
                if field.value_class == "read_only_data_block"
                else "extract_known_tag"
                if not field.is_unknown
                else "preserve_unknown_tag"
            )
            reason = action_reason(field)
            actions.append(
                SonyActionPlan(
                    action_kind, field.tag_name, field.byte_range, reason, field.evidence_ids
                )
            )
        fields.append(field)
    return tuple(fields), tuple(actions)


def subdirectory_for_entry(
    entry: SonyIfdEntryPlan,
    model: str | None,
) -> SonySubdirectoryPlan | None:
    tag_id = entry.tag_id
    if tag_id == 0x0010:
        return camera_info_subdirectory(entry)
    if tag_id == 0x0020:
        return focus_more_subdirectory(entry)
    if tag_id == 0x0114:
        return camera_settings_subdirectory(entry)
    if tag_id == 0x0116:
        return extra_info_subdirectory(model)
    if tag_id == 0x0E00:
        return subdir(
            "PrintIM",
            "Image::ExifTool::PrintIM::Main",
            None,
            "Route PrintIM data.",
            (SONY_MAIN_SOURCE,),
        )
    if tag_id == 0x1003 and is_panorama_payload(entry.raw_payload):
        return subdir(
            "Panorama",
            "Image::ExifTool::Sony::Panorama",
            None,
            "Route panorama data when the payload header indicates panorama.",
            (SONY_PANORAMA_SOURCE,),
        )
    if tag_id == 0x2010:
        return tag2010_subdirectory(model)
    if tag_id == 0x202A and entry.raw_payload.startswith(b"\x01"):
        return subdir(
            "Tag202a",
            "Image::ExifTool::Sony::Tag202a",
            None,
            "Route Tag202a when the first byte is 1.",
            (SONY_TAG202A_SOURCE,),
        )
    if tag_id == 0x2044:
        return subdir(
            "HiddenInfo",
            "Image::ExifTool::Sony::HiddenInfo",
            None,
            "Route HiddenInfo offset-pair data.",
            (SONY_HIDDEN_INFO_SOURCE, SONY_HIDDEN_TABLE_SOURCE),
        )
    if tag_id == 0x3000:
        return subdir(
            "ShotInfo",
            "Image::ExifTool::Sony::ShotInfo",
            None,
            "Route ShotInfo and its face-info subdirectories.",
            (SONY_SHOT_INFO_SOURCE, SONY_SHOT_TABLE_SOURCE),
        )
    if tag_id == 0x900B and entry.raw_payload.startswith(b"\xae"):
        return subdir(
            "Tag900b",
            "Image::ExifTool::Sony::Tag900b",
            None,
            "Route Tag900b when the first byte is 0xae.",
            (SONY_ENCRYPTED_SOURCE,),
        )
    if tag_id == 0x9050:
        return tag9050_subdirectory(entry, model)
    if tag_id == 0x9400:
        return tag9400_subdirectory(entry)
    if tag_id == 0x9401:
        return subdir(
            "Tag9401",
            "Image::ExifTool::Sony::Tag9401",
            None,
            "Route Tag9401 binary data.",
            (SONY_TAG9400_SOURCE,),
        )
    if tag_id == 0x940E:
        return tag940e_subdirectory(model)
    if tag_id == 0xB028 and entry.raw_payload != b"\x00\x00\x00\x00":
        return subdir(
            "MinoltaMakerNote",
            "Image::ExifTool::Minolta::Main",
            None,
            "Route the inherited Minolta maker-note SubIFD when non-zero.",
            (SONY_LENS_SOURCE,),
        )
    return None


def camera_info_subdirectory(entry: SonyIfdEntryPlan) -> SonySubdirectoryPlan:
    if entry.count in {368, 5478}:
        return subdir(
            "CameraInfo",
            "Image::ExifTool::Sony::CameraInfo",
            "big",
            "Route count 368 or 5478 to CameraInfo.",
            (SONY_CAMERA_INFO_SOURCE,),
        )
    if entry.count in {5506, 6118}:
        return subdir(
            "CameraInfo2",
            "Image::ExifTool::Sony::CameraInfo2",
            "little",
            "Route count 5506 or 6118 to CameraInfo2.",
            (SONY_CAMERA_INFO_SOURCE,),
        )
    if entry.count == 15360:
        return subdir(
            "CameraInfo3",
            "Image::ExifTool::Sony::CameraInfo3",
            "little",
            "Route count 15360 to CameraInfo3.",
            (SONY_CAMERA_INFO_SOURCE,),
        )
    return subdir(
        "CameraInfoUnknown",
        "Image::ExifTool::Sony::CameraInfoUnknown",
        None,
        "Route unmatched CameraInfo payloads to CameraInfoUnknown.",
        (SONY_CAMERA_INFO_SOURCE,),
    )


def focus_more_subdirectory(entry: SonyIfdEntryPlan) -> SonySubdirectoryPlan:
    if entry.count in {19154, 19148}:
        return subdir(
            "FocusInfo",
            "Image::ExifTool::Sony::FocusInfo",
            "little",
            "Route count 19154 or 19148 to FocusInfo.",
            (SONY_FOCUS_MORE_SOURCE, SONY_FOCUS_TIFF_SOURCE),
            (binary_tiff_terminal_surface("FocusInfo", SONY_FOCUS_TIFF_SOURCE),),
        )
    return subdir(
        "MoreInfo",
        "Image::ExifTool::Sony::MoreInfo",
        "little",
        "Route other 0x0020 payloads to MoreInfo through its custom block index processor.",
        (SONY_FOCUS_MORE_SOURCE, SONY_MORE_INFO_PROCESS_SOURCE, SONY_MORE_INFO_TIFF_SOURCE),
        (binary_tiff_terminal_surface("MoreInfo", SONY_MORE_INFO_TIFF_SOURCE),),
    )


def camera_settings_subdirectory(entry: SonyIfdEntryPlan) -> SonySubdirectoryPlan:
    if entry.count in {280, 364}:
        return subdir(
            "CameraSettings",
            "Image::ExifTool::Sony::CameraSettings",
            "big",
            "Route count 280 or 364 to CameraSettings.",
            (SONY_CAMERA_SETTINGS_SOURCE,),
        )
    if entry.count == 332:
        return subdir(
            "CameraSettings2",
            "Image::ExifTool::Sony::CameraSettings2",
            "big",
            "Route count 332 to CameraSettings2.",
            (SONY_CAMERA_SETTINGS_SOURCE,),
        )
    if entry.count in {1536, 2048}:
        return subdir(
            "CameraSettings3",
            "Image::ExifTool::Sony::CameraSettings3",
            "little",
            "Route count 1536 or 2048 to CameraSettings3.",
            (SONY_CAMERA_SETTINGS_SOURCE,),
        )
    return subdir(
        "CameraSettingsUnknown",
        "Image::ExifTool::Sony::CameraSettingsUnknown",
        "big",
        "Route unmatched CameraSettings payloads to CameraSettingsUnknown.",
        (SONY_CAMERA_SETTINGS_SOURCE,),
    )


def extra_info_subdirectory(model: str | None) -> SonySubdirectoryPlan:
    model_value = model or ""
    if model_value.startswith(("DSLR-A850", "DSLR-A900")):
        return subdir(
            "ExtraInfo",
            "Image::ExifTool::Sony::ExtraInfo",
            "big",
            "Route DSLR-A850/A900 models to ExtraInfo.",
            (SONY_EXTRA_INFO_SOURCE,),
        )
    if model_value.startswith(("DSLR-A230", "DSLR-A290", "DSLR-A330", "DSLR-A380", "DSLR-A390")):
        return subdir(
            "ExtraInfo2",
            "Image::ExifTool::Sony::ExtraInfo2",
            None,
            "Route DSLR-A230/A290/A330/A380/A390 models to ExtraInfo2.",
            (SONY_EXTRA_INFO_SOURCE,),
        )
    return subdir(
        "ExtraInfo3",
        "Image::ExifTool::Sony::ExtraInfo3",
        None,
        "Route remaining ExtraInfo payloads to ExtraInfo3.",
        (SONY_EXTRA_INFO_SOURCE,),
    )


def tag2010_subdirectory(model: str | None) -> SonySubdirectoryPlan | None:
    model_value = model or ""
    if model_value == "NEX-5N":
        return tag2010_subdir("Tag2010a")
    if model_value.startswith(("SLT-A65", "SLT-A77", "NEX-7", "NEX-VG20E", "Lunar")):
        return tag2010_subdir("Tag2010b")
    if model_value.startswith(("SLT-A37", "SLT-A57", "NEX-F3")):
        return tag2010_subdir("Tag2010c")
    if model_value.startswith(("DSC-RX100M2", "DSC-QX10", "DSC-QX100")):
        return tag2010_subdir("Tag2010f")
    if model_value in {"ILCE-7", "ILCE-7R", "ILCE-7S", "ILCE-7M2"} or model_value.startswith(
        (
            "ILCE-5000",
            "ILCE-5100",
            "ILCE-6000",
            "ILCE-QX1",
            "ILCA-68",
            "ILCA-77M2",
            "DSC-RX10",
            "DSC-RX100M3",
        )
    ):
        return tag2010_subdir("Tag2010g")
    if model_value.startswith(
        (
            "ILCE-6300",
            "ILCE-6500",
            "ILCE-7RM2",
            "ILCE-7SM2",
            "ILCA-99M2",
            "DSC-RX0",
            "DSC-RX100M4",
            "DSC-RX100M5",
        )
    ):
        return tag2010_subdir("Tag2010h")
    if model_value.startswith(
        (
            "ILCE-6100",
            "ILCE-6400",
            "ILCE-6600",
            "ILCE-7C",
            "ILCE-7M3",
            "ILCE-7RM3",
            "ILCE-7RM4",
            "ILCE-9",
            "DSC-RX10M4",
            "DSC-RX100M6",
            "DSC-RX100M7",
            "DSC-HX95",
            "DSC-HX99",
            "ZV-",
        )
    ):
        return tag2010_subdir("Tag2010i")
    return None


def tag2010_subdir(name: str) -> SonySubdirectoryPlan:
    return subdir(
        name,
        f"Image::ExifTool::Sony::{name}",
        None,
        f"Route model-dependent encrypted {name} payload.",
        (
            SONY_TAG2010_SOURCE,
            SONY_ENCRYPTED_SOURCE,
            SONY_TAG2010_TABLE_SOURCE,
            SONY_METER_INFO_SOURCE,
        ),
    )


def tag9050_subdirectory(entry: SonyIfdEntryPlan, model: str | None) -> SonySubdirectoryPlan | None:
    model_value = model or ""
    if model_value.startswith(
        (
            "ILCE-6100",
            "ILCE-6300",
            "ILCE-6400",
            "ILCE-6500",
            "ILCE-6600",
            "ILCE-7C",
            "ILCE-7M3",
            "ILCE-7RM2",
            "ILCE-7RM3",
            "ILCE-7RM4",
            "ILCE-7SM2",
            "ILCE-9",
            "ILCA-99M2",
            "ZV-E10",
        )
    ):
        return subdir(
            "Tag9050b",
            "Image::ExifTool::Sony::Tag9050b",
            "little",
            "Route newer ILCE/ILCA/ZV models to Tag9050b.",
            (SONY_TAG9050_SOURCE, SONY_ENCRYPTED_SOURCE),
        )
    if model_value.startswith(("ILCE-1", "ILCE-7M4", "ILCE-7RM5", "ILCE-7SM3", "ILME-FX3")):
        return subdir(
            "Tag9050c",
            "Image::ExifTool::Sony::Tag9050c",
            "little",
            "Route ILCE-1/7M4/7RM5/7SM3 and ILME-FX3 models to Tag9050c.",
            (SONY_TAG9050_SOURCE, SONY_ENCRYPTED_SOURCE),
        )
    if model_value.startswith(
        ("ILCE-6700", "ILCE-7CM2", "ILCE-7CR", "ILME-FX2", "ZV-E1", "ZV-E10M2")
    ) or (
        model_value.startswith(("ILCE-1M2", "ILCE-7M5"))
        and entry.raw_payload.startswith(b"\x00\x00\x00\x00\x00")
    ):
        return subdir(
            "Tag9050d",
            "Image::ExifTool::Sony::Tag9050d",
            "little",
            "Route late ILCE/ILME/ZV models to Tag9050d.",
            (SONY_TAG9050_SOURCE, SONY_ENCRYPTED_SOURCE),
        )
    if not model_value.startswith(
        (
            "DSC-",
            "Stellar",
            "ILCE-1",
            "ILCE-6100",
            "ILCE-6300",
            "ILCE-6400",
            "ILCE-6500",
            "ILCE-6600",
            "ILCE-6700",
            "ILCE-7C",
            "ILCE-7M3",
            "ILCE-7M4",
            "ILCE-7M5",
            "ILCE-7RM2",
            "ILCE-7RM3",
            "ILCE-7RM4",
            "ILCE-7RM5",
            "ILCE-7SM2",
            "ILCE-7SM3",
            "ILCE-9",
            "ILCA-99M2",
            "ILME-",
            "ZV-",
        )
    ):
        return subdir(
            "Tag9050a",
            "Image::ExifTool::Sony::Tag9050a",
            "little",
            "Route pre-mid-2015 non-DSC models to Tag9050a.",
            (SONY_TAG9050_SOURCE, SONY_ENCRYPTED_SOURCE),
        )
    return None


def tag9400_subdirectory(entry: SonyIfdEntryPlan) -> SonySubdirectoryPlan | None:
    if entry.raw_payload[:1] in {b"\x07", b"\x09", b"\x0a", b"\x5e", b"\xe7", b"\x04"}:
        return subdir(
            "Tag9400a",
            "Image::ExifTool::Sony::Tag9400a",
            None,
            "Route Tag9400a for first-byte family 0x07/0x09/0x0a or double-cipher markers.",
            (SONY_TAG9400_SOURCE, SONY_ENCRYPTED_SOURCE),
        )
    if entry.raw_payload.startswith(b"\x0c"):
        return subdir(
            "Tag9400b",
            "Image::ExifTool::Sony::Tag9400b",
            None,
            "Route Tag9400b for first byte 0x0c.",
            (SONY_TAG9400_SOURCE, SONY_ENCRYPTED_SOURCE),
        )
    if entry.raw_payload[:1] in {
        b"\x23",
        b"\x24",
        b"\x26",
        b"\x28",
        b"\x31",
        b"\x32",
        b"\x33",
        b"\x41",
    }:
        return subdir(
            "Tag9400c",
            "Image::ExifTool::Sony::Tag9400c",
            None,
            "Route Tag9400c for modern first-byte families.",
            (SONY_TAG9400_SOURCE, SONY_ENCRYPTED_SOURCE),
        )
    return None


def tag940e_subdirectory(model: str | None) -> SonySubdirectoryPlan | None:
    model_value = model or ""
    if model_value.startswith(("NEX-", "ILCE-", "Lunar")):
        return subdir(
            "Tag940e",
            "Image::ExifTool::Sony::Tag940e",
            None,
            "Route NEX/ILCE/Lunar 0x940e payloads to Tag940e.",
            (SONY_TAG940E_ROUTE_SOURCE, SONY_TAG940E_TIFF_SOURCE, SONY_ENCRYPTED_SOURCE),
            (binary_tiff_terminal_surface("Tag940e", SONY_TAG940E_TIFF_SOURCE),),
        )
    return None


def subdir(
    tag_name: str,
    table: str,
    byte_order: SonyByteOrder | None,
    reason: str,
    references: tuple[str, ...],
    terminal_surfaces: tuple[SonyTerminalSurfacePlan, ...] = (),
) -> SonySubdirectoryPlan:
    return SonySubdirectoryPlan(tag_name, table, byte_order, reason, references, terminal_surfaces)


def binary_tiff_terminal_surface(table_name: str, reference: str) -> SonyTerminalSurfacePlan:
    return SonyTerminalSurfacePlan(
        "TiffMeteringImage",
        "binary_tiff_output",
        "callable_binary_option_gate",
        False,
        (
            f"Sony {table_name} TiffMeteringImage is terminal Binary/TIFF output; "
            "normal scalar reads require ExifTool Binary/output-mode state."
        ),
        (reference,),
    )


def subdirectory_field(
    entry: SonyIfdEntryPlan, subdirectory: SonySubdirectoryPlan
) -> SonyFieldPlan:
    return SonyFieldPlan(
        subdirectory.tag_name,
        entry.tag_id,
        entry.exif_type,
        entry.count,
        entry.value_range,
        entry.raw_payload,
        entry.raw_payload,
        entry.raw_payload,
        "read_only_subdirectory",
        None,
        subdirectory_boundary(subdirectory),
        False,
        subdirectory,
        subdirectory.evidence_ids,
    )


def subdirectory_boundary(subdirectory: SonySubdirectoryPlan) -> SonyConversionBoundary:
    if subdirectory.tag_name in {
        "CameraInfo",
        "CameraInfo2",
        "CameraInfo3",
        "CameraInfoUnknown",
        "FocusInfo",
        "MoreInfo",
        "CameraSettings",
        "CameraSettings2",
        "CameraSettings3",
        "CameraSettingsUnknown",
    }:
        return "count_based_subdirectory"
    if subdirectory.tag_name.startswith(("Tag2010", "Tag9050", "Tag940e")):
        return "model_based_subdirectory"
    if subdirectory.tag_name.startswith(("Tag900b", "Tag9400", "Tag202a")):
        return "payload_header_subdirectory"
    if subdirectory.tag_name == "HiddenInfo":
        return "hidden_offset_pair"
    if subdirectory.tag_name == "ShotInfo":
        return "shot_face_info_boundary"
    return "none"


def unknown_cipher_field(entry: SonyIfdEntryPlan) -> SonyFieldPlan:
    tag_name = f"Sony_0x{entry.tag_id:04x}"
    refs = (SONY_MAIN_SOURCE, SONY_ENCRYPTED_SOURCE)
    if entry.tag_id == 0x2010:
        refs = (SONY_TAG2010_SOURCE, SONY_ENCRYPTED_SOURCE)
        tag_name = "Tag_0x2010"
    elif entry.tag_id == 0x9050:
        refs = (SONY_TAG9050_SOURCE, SONY_ENCRYPTED_SOURCE)
    elif entry.tag_id == 0x9400:
        refs = (SONY_TAG9400_SOURCE, SONY_ENCRYPTED_SOURCE)
    return SonyFieldPlan(
        tag_name,
        entry.tag_id,
        entry.exif_type,
        entry.count,
        entry.value_range,
        entry.raw_payload,
        entry.raw_payload,
        entry.raw_payload,
        "unknown_cipher_preserved",
        None,
        "unknown_cipher_boundary",
        True,
        None,
        refs,
    )


def scalar_or_unknown_field(entry: SonyIfdEntryPlan, byte_order: SonyByteOrder) -> SonyFieldPlan:
    spec = SCALAR_TAGS_BY_ID.get(entry.tag_id)
    if spec is None:
        return SonyFieldPlan(
            f"Sony_0x{entry.tag_id:04x}",
            entry.tag_id,
            entry.exif_type,
            entry.count,
            entry.value_range,
            entry.raw_payload,
            entry.raw_payload,
            entry.raw_payload,
            "unknown_preserved",
            None,
            "none",
            True,
            None,
            (SONY_MAIN_SOURCE,),
        )
    raw_value = interpret_value(entry, spec, byte_order)
    return SonyFieldPlan(
        spec.name,
        entry.tag_id,
        entry.exif_type,
        entry.count,
        entry.value_range,
        entry.raw_payload,
        raw_value,
        interpreted_value(spec, raw_value),
        spec.value_class,
        spec.writable_format,
        spec.conversion_boundary,
        False,
        None,
        spec.evidence_ids,
    )


def interpret_value(
    entry: SonyIfdEntryPlan,
    spec: SonyTagSpec,
    byte_order: SonyByteOrder,
) -> SonyRawValue:
    if spec.writable_format == "string":
        return decode_string(entry.raw_payload)
    if spec.writable_format == "rational64s" and len(entry.raw_payload) >= 8:
        return (
            int.from_bytes(entry.raw_payload[:4], byte_order, signed=True),
            int.from_bytes(entry.raw_payload[4:8], byte_order, signed=True),
        )
    if spec.writable_format in {"int8u", "int16u", "int32u", "int16s", "int32s"}:
        signed = spec.writable_format in {"int16s", "int32s"}
        width = width_for_format(spec.writable_format)
        values = tuple(
            int.from_bytes(entry.raw_payload[offset : offset + width], byte_order, signed=signed)
            for offset in range(0, min(len(entry.raw_payload), width * entry.count), width)
            if len(entry.raw_payload[offset : offset + width]) == width
        )
        if entry.count == 1 and values:
            return values[0]
        return values
    return entry.raw_payload


def interpreted_value(spec: SonyTagSpec, raw_value: SonyRawValue) -> SonyInterpretedValue:
    if spec.name == "Quality" and isinstance(raw_value, int):
        return QUALITY_LABELS.get(raw_value, raw_value)
    if spec.name == "WhiteBalance" and isinstance(raw_value, int):
        return WHITE_BALANCE_LABELS.get(raw_value, raw_value)
    if spec.name == "FocusMode" and isinstance(raw_value, int):
        return FOCUS_MODE_LABELS.get(raw_value, raw_value)
    if spec.name == "AFAreaModeSetting" and isinstance(raw_value, int):
        return AF_AREA_ILCE_LABELS.get(raw_value, raw_value)
    if spec.name == "PrioritySetInAWB" and isinstance(raw_value, int):
        return PRIORITY_AWB_LABELS.get(raw_value, raw_value)
    if spec.name == "MeteringMode2" and isinstance(raw_value, int):
        return METERING_MODE2_LABELS.get(raw_value, raw_value)
    if spec.name == "Quality2" and isinstance(raw_value, tuple):
        if len(raw_value) == 2:
            pair = (raw_value[0], raw_value[1])
            return QUALITY_202E_LABELS.get(pair, raw_value)
        return raw_value
    if spec.name == "SonyModelID" and isinstance(raw_value, int):
        return SONY_MODEL_LABELS.get(raw_value, raw_value)
    if spec.name == "CreativeStyle" and isinstance(raw_value, str):
        return CREATIVE_STYLE_LABELS.get(raw_value, raw_value)
    if spec.name == "ColorTemperature" and isinstance(raw_value, int):
        if raw_value == 0:
            return "Auto"
        if raw_value == 0xFFFFFFFF:
            return "n/a"
    if spec.name in {"Contrast", "Saturation", "Sharpness", "Brightness"} and isinstance(
        raw_value, int
    ):
        if raw_value > 0:
            return f"+{raw_value}"
    if spec.name == "Macro" and isinstance(raw_value, int):
        return {0: "Off", 1: "On", 2: "Close Focus", 65535: "n/a"}.get(raw_value, raw_value)
    if spec.name == "JPEGQuality" and isinstance(raw_value, int):
        return {0: "Standard", 1: "Fine", 2: "Extra Fine", 65535: "n/a"}.get(raw_value, raw_value)
    return raw_value


def action_reason(field: SonyFieldPlan) -> str:
    if field.value_class == "read_only_data_block":
        return "Preserve the Sony data block and its proprietary payload boundary."
    if field.is_unknown:
        return (
            "Preserve source bytes for a Sony maker-note tag not named in this source-backed slice."
        )
    return "Extract a source-backed Sony Main maker-note tag."


def is_panorama_payload(payload: bytes) -> bool:
    return payload.startswith(b"\x01\x01") or payload.startswith(b"\x00\x00\x01\x01")


def plan_rewrites(
    fields: tuple[SonyFieldPlan, ...],
    rewrite_requests: tuple[SonyRewriteRequest, ...],
) -> tuple[tuple[SonyOutputEmissionGate, ...], tuple[SonyActionPlan, ...]]:
    fields_by_name = {field.tag_name: field for field in fields}
    seen_names: set[str] = set()
    gates: list[SonyOutputEmissionGate] = []
    actions: list[SonyActionPlan] = []
    for request in rewrite_requests:
        field = fields_by_name.get(request.tag_name)
        gate = rewrite_gate_for_request(request, field, seen_names)
        seen_names.add(request.tag_name)
        gates.append(gate)
        actions.append(
            SonyActionPlan(
                "block_requested_rewrite",
                request.tag_name,
                field.byte_range if field is not None else None,
                gate.reason,
                gate.evidence_ids,
            )
        )
    return tuple(gates), tuple(actions)


def rewrite_gate_for_request(
    request: SonyRewriteRequest,
    field: SonyFieldPlan | None,
    seen_names: set[str],
) -> SonyOutputEmissionGate:
    if request.tag_name in seen_names:
        return SonyOutputEmissionGate(
            "duplicate_rewrite_tag",
            f"Sony maker-note rewrite for {request.tag_name} was requested more than once.",
            (SONY_EXIF_WRITE_SOURCE,),
        )
    if request.tag_name not in SCALAR_TAGS_BY_NAME and field is None:
        return SonyOutputEmissionGate(
            "unknown_rewrite_tag",
            (
                "Sony.pm does not define a writable scalar tag named "
                f"{request.tag_name} in this slice."
            ),
            (SONY_MAIN_SOURCE,),
        )
    if field is None:
        spec = SCALAR_TAGS_BY_NAME[request.tag_name]
        return SonyOutputEmissionGate(
            "missing_source_tag_for_rewrite",
            f"Sony maker-note tag {request.tag_name} is not present in the source payload.",
            spec.evidence_ids,
        )
    if field.value_class != "writable_exif_scalar":
        return SonyOutputEmissionGate(
            "read_only_subdirectory_rewrite",
            (
                f"Sony maker-note tag {request.tag_name} is routed or preserved "
                "read-only by this planner."
            ),
            field.evidence_ids,
        )
    return SonyOutputEmissionGate(
        "sony_makernote_rewrite_not_supported",
        "This Sony modernization slice classifies writable tags but does not rewrite maker notes.",
        (SONY_EXIF_WRITE_SOURCE, *field.evidence_ids),
    )


def preservation_plan(
    source_data: bytes, fields: tuple[SonyFieldPlan, ...]
) -> SonyPreservationPlan:
    return SonyPreservationPlan(
        (0, len(source_data)),
        tuple(field.tag_id for field in fields if field.value_class == "unknown_preserved"),
        tuple(field.tag_id for field in fields if field.value_class == "unknown_cipher_preserved"),
        tuple(field.tag_name for field in fields if field.value_class == "read_only_data_block"),
        (SONY_MAIN_SOURCE, SONY_ENCRYPTED_SOURCE, SONY_PREVIEW_SOURCE),
    )


def responsibility_plans(fields: tuple[SonyFieldPlan, ...]) -> tuple[SonyResponsibilityPlan, ...]:
    plans = [
        SonyResponsibilityPlan(
            "main_table_routing",
            "Parse the Sony Main EXIF-style maker-note IFD and preserve its payload range.",
            (SONY_MAIN_SOURCE, SONY_EXIF_WRITE_SOURCE),
        ),
        SonyResponsibilityPlan(
            "unknown_tag_preservation",
            "Preserve tags not covered by this source-backed Sony slice.",
            (SONY_MAIN_SOURCE,),
        ),
        SonyResponsibilityPlan(
            "rewrite_gating",
            "Classify rewrite requests but block byte mutation in this planning slice.",
            (SONY_EXIF_WRITE_SOURCE,),
        ),
    ]
    if any(field.subdirectory is not None for field in fields):
        plans.append(
            SonyResponsibilityPlan(
                "binary_subtable_routing",
                "Route selected Sony binary subtables by count, model, and payload header.",
                (SONY_CAMERA_INFO_SOURCE, SONY_CAMERA_SETTINGS_SOURCE, SONY_TAG2010_SOURCE),
            )
        )
    if any(
        field.subdirectory is not None and field.subdirectory.terminal_surfaces for field in fields
    ):
        plans.append(
            SonyResponsibilityPlan(
                "terminal_binary_tiff_output",
                (
                    "Classify Sony TiffMeteringImage child tables as terminal Binary/TIFF "
                    "output surfaces instead of scalar reader conversions."
                ),
                (SONY_FOCUS_TIFF_SOURCE, SONY_MORE_INFO_TIFF_SOURCE, SONY_TAG940E_TIFF_SOURCE),
            )
        )
    if any(field.value_class == "unknown_cipher_preserved" for field in fields):
        plans.append(
            SonyResponsibilityPlan(
                "encrypted_subtable_preservation",
                "Preserve encrypted Sony maker-note payloads that do not match a routed table.",
                (SONY_ENCRYPTED_SOURCE,),
            )
        )
    if any(field.tag_name == "PreviewImage" for field in fields):
        plans.append(
            SonyResponsibilityPlan(
                "preview_payload_preservation",
                "Preserve PreviewImage including its proprietary 32-byte header boundary.",
                (SONY_PREVIEW_SOURCE,),
            )
        )
    if any(field.tag_name == "HiddenInfo" for field in fields):
        plans.append(
            SonyResponsibilityPlan(
                "hidden_data_offset_pair",
                "Record HiddenInfo offset and length pair responsibility without relocating data.",
                (SONY_HIDDEN_INFO_SOURCE, SONY_HIDDEN_TABLE_SOURCE),
            )
        )
    if any(field.tag_name == "ShotInfo" for field in fields):
        plans.append(
            SonyResponsibilityPlan(
                "shot_face_info_subdirectories",
                (
                    "Record ShotInfo face-info subdirectory responsibility without "
                    "expanding nested tables."
                ),
                (SONY_SHOT_INFO_SOURCE, SONY_SHOT_TABLE_SOURCE),
            )
        )
    return tuple(plans)


def read_u16(source_data: bytes, offset: int, byte_order: SonyByteOrder) -> int:
    return int.from_bytes(source_data[offset : offset + 2], byte_order)


def read_u32(source_data: bytes, offset: int, byte_order: SonyByteOrder) -> int:
    return int.from_bytes(source_data[offset : offset + 4], byte_order)


def width_for_format(writable_format: SonyWritableFormat) -> int:
    if writable_format == "int8u":
        return 1
    if writable_format in {"int16u", "int16s"}:
        return 2
    return 4


def decode_string(raw_payload: bytes) -> str:
    return raw_payload.split(b"\x00", 1)[0].decode("latin-1")


def collect_evidence_ids(
    fields: tuple[SonyFieldPlan, ...],
    responsibilities: tuple[SonyResponsibilityPlan, ...],
    actions: tuple[SonyActionPlan, ...],
    gates: tuple[SonyOutputEmissionGate, ...],
) -> tuple[str, ...]:
    collected: list[str] = [SONY_MAIN_SOURCE, SONY_EXIF_WRITE_SOURCE]
    for field in fields:
        for reference in field.evidence_ids:
            if reference not in collected:
                collected.append(reference)
    for responsibility in responsibilities:
        for reference in responsibility.evidence_ids:
            if reference not in collected:
                collected.append(reference)
    for action in actions:
        for reference in action.evidence_ids:
            if reference not in collected:
                collected.append(reference)
    for gate in gates:
        for reference in gate.evidence_ids:
            if reference not in collected:
                collected.append(reference)
    return tuple(collected)
