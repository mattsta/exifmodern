"""FujiFilm EXIF maker-note transaction planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type FujiFilmByteOrder = Literal["little", "big"]
type FujiFilmEvidenceId = str
type FujiFilmPlanStatus = Literal["planned", "unsupported"]
type FujiFilmExifTypeName = Literal[
    "byte",
    "ascii",
    "short",
    "long",
    "rational",
    "undefined",
    "slong",
    "srational",
]
type FujiFilmWritableFormat = Literal[
    "undef",
    "string",
    "int16u",
    "int32u",
    "int32s",
    "rational64s",
]
type FujiFilmRoute = Literal["main", "writable_binary_subdirectory", "read_only_subdirectory"]
type FujiFilmValueClass = Literal[
    "writable_exif_scalar",
    "writable_exif_string",
    "writable_exif_undef",
    "writable_binary_subdirectory",
    "read_only_subdirectory",
    "unknown_preserved",
]
type FujiFilmConversionBoundary = Literal[
    "none",
    "print_conversion",
    "raw_conversion",
    "value_conversion",
    "string_value_boundary",
    "binary_subdirectory_boundary",
    "face_recognition_boundary",
]
type FujiFilmActionKind = Literal[
    "route_main_table",
    "extract_known_tag",
    "route_binary_subdirectory",
    "preserve_read_only_subdirectory",
    "preserve_unknown_tag",
    "block_requested_rewrite",
]
type FujiFilmOutputGateCode = Literal[
    "truncated_ifd_header",
    "truncated_ifd_entry",
    "truncated_tag_value",
    "malformed_entry_type",
    "unknown_rewrite_tag",
    "missing_source_tag_for_rewrite",
    "read_only_rewrite_tag",
    "duplicate_rewrite_tag",
    "maker_note_rewrite_not_supported",
    "non_mutating_plan_requires_explicit_emission",
]
type FujiFilmRawValue = int | str | tuple[int, ...] | bytes | None
type FujiFilmInterpretedValue = int | float | str | tuple[int, ...] | bytes | None

FUJIFILM_MAIN_SOURCE = "fujifilm.makernote.main"
FUJIFILM_EXIF_WRITE_SOURCE = "fujifilm.makernote.exif-write"
FUJIFILM_VERSION_SOURCE = "fujifilm.makernote.version"
FUJIFILM_INTERNAL_SERIAL_SOURCE = "fujifilm.makernote.internal-serial-number"
FUJIFILM_QUALITY_SOURCE = "fujifilm.makernote.quality"
FUJIFILM_SHARPNESS_SOURCE = "fujifilm.makernote.sharpness"
FUJIFILM_WHITE_BALANCE_SOURCE = "fujifilm.makernote.white-balance"
FUJIFILM_NOISE_REDUCTION_SOURCE = "fujifilm.makernote.noise-reduction"
FUJIFILM_DIGITAL_ZOOM_SOURCE = "fujifilm.makernote.digital-zoom"
FUJIFILM_IMAGE_COUNT_SOURCE = "fujifilm.makernote.image-count"
FUJIFILM_PRIORITY_SETTINGS_SOURCE = "fujifilm.makernote.priority-settings"
FUJIFILM_PRIORITY_TABLE_SOURCE = "fujifilm.makernote.priority-table"
FUJIFILM_FOCUS_SETTINGS_SOURCE = "fujifilm.makernote.focus-settings"
FUJIFILM_FOCUS_TABLE_SOURCE = "fujifilm.makernote.focus-table"
FUJIFILM_AFC_SETTINGS_SOURCE = "fujifilm.makernote.afc-settings"
FUJIFILM_AFC_TABLE_SOURCE = "fujifilm.makernote.afc-table"
FUJIFILM_DRIVE_SETTINGS_SOURCE = "fujifilm.makernote.drive-settings"
FUJIFILM_DRIVE_TABLE_SOURCE = "fujifilm.makernote.drive-table"
FUJIFILM_FACE_REC_SOURCE = "fujifilm.makernote.face-rec"
FUJIFILM_FACE_REC_TABLE_SOURCE = "fujifilm.makernote.face-rec-table"


@dataclass(frozen=True)
class FujiFilmRewriteRequest:
    tag_name: str
    raw_payload: bytes


@dataclass(frozen=True)
class FujiFilmTagSpec:
    tag_id: int
    name: str
    route: FujiFilmRoute
    writable_format: FujiFilmWritableFormat | None
    expected_count: int | None
    subdirectory_table: str | None
    child_tag_names: tuple[str, ...]
    evidence_ids: tuple[FujiFilmEvidenceId, ...]

    @property
    def value_class(self) -> FujiFilmValueClass:
        if self.route == "writable_binary_subdirectory":
            return "writable_binary_subdirectory"
        if self.route == "read_only_subdirectory":
            return "read_only_subdirectory"
        if self.writable_format == "string":
            return "writable_exif_string"
        if self.writable_format == "undef":
            return "writable_exif_undef"
        return "writable_exif_scalar"


@dataclass(frozen=True)
class FujiFilmIfdEntryPlan:
    tag_id: int
    exif_type: FujiFilmExifTypeName
    count: int
    entry_range: tuple[int, int]
    value_range: tuple[int, int]
    raw_payload: bytes
    payload_is_inline: bool


@dataclass(frozen=True)
class FujiFilmFieldPlan:
    tag_name: str
    tag_id: int
    exif_type: FujiFilmExifTypeName
    count: int
    byte_range: tuple[int, int]
    raw_payload: bytes
    raw_value: FujiFilmRawValue
    interpreted_value: FujiFilmInterpretedValue
    value_class: FujiFilmValueClass
    writable_format: FujiFilmWritableFormat | None
    route: FujiFilmRoute
    conversion_boundary: FujiFilmConversionBoundary
    is_unknown: bool
    subdirectory_table: str | None
    child_tag_names: tuple[str, ...]
    evidence_ids: tuple[FujiFilmEvidenceId, ...]

    @property
    def is_writable_main_tag(self) -> bool:
        return self.value_class in {
            "writable_exif_scalar",
            "writable_exif_string",
            "writable_exif_undef",
        }


@dataclass(frozen=True)
class FujiFilmRoutingPlan:
    table: str
    byte_order: FujiFilmByteOrder
    entry_count: int
    evidence_ids: tuple[FujiFilmEvidenceId, ...]


@dataclass(frozen=True)
class FujiFilmPreservationPlan:
    payload_range: tuple[int, int]
    unknown_tag_ids: tuple[int, ...]
    read_only_subdirectory_tag_ids: tuple[int, ...]
    evidence_ids: tuple[FujiFilmEvidenceId, ...]


@dataclass(frozen=True)
class FujiFilmActionPlan:
    kind: FujiFilmActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[FujiFilmEvidenceId, ...]


@dataclass(frozen=True)
class FujiFilmOutputEmissionGate:
    code: FujiFilmOutputGateCode
    reason: str
    evidence_ids: tuple[FujiFilmEvidenceId, ...]


@dataclass(frozen=True)
class FujiFilmMakerNoteTransactionPlan:
    status: FujiFilmPlanStatus
    source_data: bytes
    routing: FujiFilmRoutingPlan
    fields: tuple[FujiFilmFieldPlan, ...]
    preservation: FujiFilmPreservationPlan
    actions: tuple[FujiFilmActionPlan, ...]
    output_emission_gates: tuple[FujiFilmOutputEmissionGate, ...]
    evidence_ids: tuple[FujiFilmEvidenceId, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def writable_main_tags(self) -> tuple[str, ...]:
        return tuple(field.tag_name for field in self.fields if field.is_writable_main_tag)

    def field(self, tag_name: str) -> FujiFilmFieldPlan:
        for field in self.fields:
            if field.tag_name == tag_name:
                return field
        raise KeyError(tag_name)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"FujiFilm maker-note transaction output is gated: {gate_codes}")
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
EXIF_TYPE_NAMES: dict[int, FujiFilmExifTypeName] = {
    1: "byte",
    2: "ascii",
    3: "short",
    4: "long",
    5: "rational",
    7: "undefined",
    9: "slong",
    10: "srational",
}
SHARPNESS_LABELS = {
    0x00: "-4 (softest)",
    0x01: "-3 (very soft)",
    0x02: "-2 (soft)",
    0x03: "0 (normal)",
    0x04: "+2 (hard)",
    0x05: "+3 (very hard)",
    0x06: "+4 (hardest)",
    0x82: "-1 (medium soft)",
    0x84: "+1 (medium hard)",
    0x8000: "Film Simulation",
    0xFFFF: "n/a",
}
WHITE_BALANCE_LABELS = {
    0x0: "Auto",
    0x1: "Auto (white priority)",
    0x2: "Auto (ambiance priority)",
    0x100: "Daylight",
    0x200: "Cloudy",
    0x300: "Daylight Fluorescent",
    0x301: "Day White Fluorescent",
    0x302: "White Fluorescent",
    0x303: "Warm White Fluorescent",
    0x304: "Living Room Warm White Fluorescent",
    0x400: "Incandescent",
    0x500: "Flash",
    0x600: "Underwater",
    0xF00: "Custom",
    0xF01: "Custom2",
    0xF02: "Custom3",
    0xF03: "Custom4",
    0xF04: "Custom5",
    0xFF0: "Kelvin",
}
NOISE_REDUCTION_LABELS = {
    0x40: "Low",
    0x80: "Normal",
}

FUJIFILM_TAG_SPECS: tuple[FujiFilmTagSpec, ...] = (
    FujiFilmTagSpec(0x0000, "Version", "main", "undef", None, None, (), (FUJIFILM_VERSION_SOURCE,)),
    FujiFilmTagSpec(
        0x0010,
        "InternalSerialNumber",
        "main",
        "string",
        None,
        None,
        (),
        (FUJIFILM_INTERNAL_SERIAL_SOURCE,),
    ),
    FujiFilmTagSpec(
        0x1000,
        "Quality",
        "main",
        "string",
        None,
        None,
        (),
        (FUJIFILM_QUALITY_SOURCE,),
    ),
    FujiFilmTagSpec(
        0x1001,
        "Sharpness",
        "main",
        "int16u",
        None,
        None,
        (),
        (FUJIFILM_SHARPNESS_SOURCE,),
    ),
    FujiFilmTagSpec(
        0x1002,
        "WhiteBalance",
        "main",
        "int16u",
        None,
        None,
        (),
        (FUJIFILM_WHITE_BALANCE_SOURCE,),
    ),
    FujiFilmTagSpec(
        0x100B,
        "NoiseReduction",
        "main",
        "int16u",
        None,
        None,
        (),
        (FUJIFILM_NOISE_REDUCTION_SOURCE,),
    ),
    FujiFilmTagSpec(
        0x102B,
        "PrioritySettings",
        "writable_binary_subdirectory",
        None,
        None,
        "Image::ExifTool::FujiFilm::PrioritySettings",
        ("AF-SPriority", "AF-CPriority"),
        (FUJIFILM_PRIORITY_SETTINGS_SOURCE, FUJIFILM_PRIORITY_TABLE_SOURCE),
    ),
    FujiFilmTagSpec(
        0x102D,
        "FocusSettings",
        "writable_binary_subdirectory",
        None,
        None,
        "Image::ExifTool::FujiFilm::FocusSettings",
        ("FocusMode2", "PreAF", "AFAreaMode", "AFAreaPointSize", "AFAreaZoneSize"),
        (FUJIFILM_FOCUS_SETTINGS_SOURCE, FUJIFILM_FOCUS_TABLE_SOURCE),
    ),
    FujiFilmTagSpec(
        0x102E,
        "AFCSettings",
        "writable_binary_subdirectory",
        None,
        None,
        "Image::ExifTool::FujiFilm::AFCSettings",
        (
            "AF-CSetting",
            "AF-CTrackingSensitivity",
            "AF-CSpeedTrackingSensitivity",
            "AF-CZoneAreaSwitching",
        ),
        (FUJIFILM_AFC_SETTINGS_SOURCE, FUJIFILM_AFC_TABLE_SOURCE),
    ),
    FujiFilmTagSpec(
        0x1044,
        "DigitalZoom",
        "main",
        "int32u",
        None,
        None,
        (),
        (FUJIFILM_DIGITAL_ZOOM_SOURCE,),
    ),
    FujiFilmTagSpec(
        0x1103,
        "DriveSettings",
        "writable_binary_subdirectory",
        None,
        None,
        "Image::ExifTool::FujiFilm::DriveSettings",
        ("DriveMode", "DriveSpeed"),
        (FUJIFILM_DRIVE_SETTINGS_SOURCE, FUJIFILM_DRIVE_TABLE_SOURCE),
    ),
    FujiFilmTagSpec(
        0x1438,
        "ImageCount",
        "main",
        "int16u",
        None,
        None,
        (),
        (FUJIFILM_IMAGE_COUNT_SOURCE,),
    ),
    FujiFilmTagSpec(
        0x4282,
        "FaceRecInfo",
        "read_only_subdirectory",
        None,
        None,
        "Image::ExifTool::FujiFilm::FaceRecInfo",
        ("Face1Name", "Face1Category", "Face1Birthday"),
        (FUJIFILM_FACE_REC_SOURCE, FUJIFILM_FACE_REC_TABLE_SOURCE),
    ),
)
FUJIFILM_TAGS_BY_ID = {spec.tag_id: spec for spec in FUJIFILM_TAG_SPECS}
FUJIFILM_TAGS_BY_NAME = {spec.name: spec for spec in FUJIFILM_TAG_SPECS}


def build_fujifilm_makernote_transaction_plan(
    source_data: bytes,
    *,
    byte_order: FujiFilmByteOrder = "little",
    rewrite_requests: tuple[FujiFilmRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> FujiFilmMakerNoteTransactionPlan:
    routing = FujiFilmRoutingPlan(
        "Image::ExifTool::FujiFilm::Main",
        byte_order,
        0,
        (FUJIFILM_MAIN_SOURCE, FUJIFILM_EXIF_WRITE_SOURCE),
    )
    if len(source_data) < 2:
        gate = FujiFilmOutputEmissionGate(
            "truncated_ifd_header",
            "FujiFilm maker-note IFD header must contain a two-byte entry count.",
            (FUJIFILM_MAIN_SOURCE,),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entry_count = read_u16(source_data, 0, byte_order)
    routing = FujiFilmRoutingPlan(
        "Image::ExifTool::FujiFilm::Main",
        byte_order,
        entry_count,
        (FUJIFILM_MAIN_SOURCE, FUJIFILM_EXIF_WRITE_SOURCE),
    )
    entry_region_end = 2 + (entry_count * 12) + 4
    if len(source_data) < entry_region_end:
        gate = FujiFilmOutputEmissionGate(
            "truncated_ifd_entry",
            "FujiFilm maker-note IFD entries and next-directory pointer are incomplete.",
            (FUJIFILM_MAIN_SOURCE,),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entries: list[FujiFilmIfdEntryPlan] = []
    parse_gates: list[FujiFilmOutputEmissionGate] = []
    for index in range(entry_count):
        entry_offset = 2 + (index * 12)
        parsed_entry = parse_ifd_entry(source_data, entry_offset, byte_order)
        if isinstance(parsed_entry, FujiFilmOutputEmissionGate):
            parse_gates.append(parsed_entry)
        else:
            entries.append(parsed_entry)

    if parse_gates:
        return unsupported_plan(source_data, routing, tuple(parse_gates))

    fields, field_actions = build_fields(tuple(entries), byte_order)
    rewrite_gates, rewrite_actions = plan_rewrites(fields, rewrite_requests)
    output_gates = list(rewrite_gates)
    if not rewrite_requests and not allow_output_emission:
        output_gates.append(
            FujiFilmOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "The default FujiFilm maker-note plan is read-only and does not emit bytes.",
                (FUJIFILM_EXIF_WRITE_SOURCE,),
            )
        )

    actions = (
        FujiFilmActionPlan(
            "route_main_table",
            "Image::ExifTool::FujiFilm::Main",
            (0, len(source_data)),
            "Use the FujiFilm Main EXIF maker-note table.",
            (FUJIFILM_MAIN_SOURCE,),
        ),
        *field_actions,
        *rewrite_actions,
    )
    gates = tuple(output_gates)
    preservation = FujiFilmPreservationPlan(
        (0, len(source_data)),
        tuple(field.tag_id for field in fields if field.value_class == "unknown_preserved"),
        tuple(field.tag_id for field in fields if field.value_class == "read_only_subdirectory"),
        (FUJIFILM_MAIN_SOURCE, FUJIFILM_FACE_REC_TABLE_SOURCE),
    )
    return FujiFilmMakerNoteTransactionPlan(
        "planned",
        source_data,
        routing,
        fields,
        preservation,
        actions,
        gates,
        collect_evidence_ids(fields, actions, gates),
    )


def unsupported_plan(
    source_data: bytes,
    routing: FujiFilmRoutingPlan,
    gates: tuple[FujiFilmOutputEmissionGate, ...],
) -> FujiFilmMakerNoteTransactionPlan:
    actions = (
        FujiFilmActionPlan(
            "route_main_table",
            "Image::ExifTool::FujiFilm::Main",
            (0, len(source_data)),
            "FujiFilm maker-note routing could not be completed.",
            routing.evidence_ids,
        ),
    )
    return FujiFilmMakerNoteTransactionPlan(
        "unsupported",
        source_data,
        routing,
        (),
        FujiFilmPreservationPlan((0, len(source_data)), (), (), (FUJIFILM_MAIN_SOURCE,)),
        actions,
        gates,
        collect_evidence_ids((), actions, gates),
    )


def parse_ifd_entry(
    source_data: bytes,
    entry_offset: int,
    byte_order: FujiFilmByteOrder,
) -> FujiFilmIfdEntryPlan | FujiFilmOutputEmissionGate:
    tag_id = read_u16(source_data, entry_offset, byte_order)
    type_id = read_u16(source_data, entry_offset + 2, byte_order)
    if type_id not in EXIF_TYPE_SIZES:
        return FujiFilmOutputEmissionGate(
            "malformed_entry_type",
            f"FujiFilm maker-note tag 0x{tag_id:04x} uses unsupported EXIF type {type_id}.",
            (FUJIFILM_MAIN_SOURCE,),
        )
    count = read_u32(source_data, entry_offset + 4, byte_order)
    byte_count = EXIF_TYPE_SIZES[type_id] * count
    value_slot = source_data[entry_offset + 8 : entry_offset + 12]
    if byte_count <= 4:
        value_range = (entry_offset + 8, entry_offset + 8 + byte_count)
        raw_payload = source_data[value_range[0] : value_range[1]]
        payload_is_inline = True
    else:
        value_offset = int.from_bytes(value_slot, byte_order)
        value_end = value_offset + byte_count
        if value_offset > len(source_data) or value_end > len(source_data):
            return FujiFilmOutputEmissionGate(
                "truncated_tag_value",
                f"FujiFilm maker-note tag 0x{tag_id:04x} points outside the source bytes.",
                (FUJIFILM_MAIN_SOURCE,),
            )
        value_range = (value_offset, value_end)
        raw_payload = source_data[value_offset:value_end]
        payload_is_inline = False
    return FujiFilmIfdEntryPlan(
        tag_id,
        EXIF_TYPE_NAMES[type_id],
        count,
        (entry_offset, entry_offset + 12),
        value_range,
        raw_payload,
        payload_is_inline,
    )


def build_fields(
    entries: tuple[FujiFilmIfdEntryPlan, ...],
    byte_order: FujiFilmByteOrder,
) -> tuple[tuple[FujiFilmFieldPlan, ...], tuple[FujiFilmActionPlan, ...]]:
    fields: list[FujiFilmFieldPlan] = []
    actions: list[FujiFilmActionPlan] = []
    for entry in entries:
        spec = FUJIFILM_TAGS_BY_ID.get(entry.tag_id)
        if spec is None:
            field = unknown_field(entry)
            actions.append(
                FujiFilmActionPlan(
                    "preserve_unknown_tag",
                    field.tag_name,
                    field.byte_range,
                    "Preserve source bytes for a FujiFilm maker-note tag not named in this slice.",
                    field.evidence_ids,
                )
            )
        else:
            field = known_field(entry, spec, byte_order)
            actions.append(action_for_known_field(field))
        fields.append(field)
    return tuple(fields), tuple(actions)


def unknown_field(entry: FujiFilmIfdEntryPlan) -> FujiFilmFieldPlan:
    return FujiFilmFieldPlan(
        f"FujiFilm_0x{entry.tag_id:04x}",
        entry.tag_id,
        entry.exif_type,
        entry.count,
        entry.value_range,
        entry.raw_payload,
        entry.raw_payload,
        entry.raw_payload,
        "unknown_preserved",
        None,
        "main",
        "none",
        True,
        None,
        (),
        (FUJIFILM_MAIN_SOURCE,),
    )


def known_field(
    entry: FujiFilmIfdEntryPlan,
    spec: FujiFilmTagSpec,
    byte_order: FujiFilmByteOrder,
) -> FujiFilmFieldPlan:
    raw_value = interpret_value(entry, spec, byte_order)
    return FujiFilmFieldPlan(
        spec.name,
        entry.tag_id,
        entry.exif_type,
        entry.count,
        entry.value_range,
        entry.raw_payload,
        raw_value,
        interpret_value_for_read(raw_value, spec),
        spec.value_class,
        spec.writable_format,
        spec.route,
        conversion_boundary(spec),
        False,
        spec.subdirectory_table,
        spec.child_tag_names,
        spec.evidence_ids,
    )


def action_for_known_field(field: FujiFilmFieldPlan) -> FujiFilmActionPlan:
    if field.value_class == "writable_binary_subdirectory":
        return FujiFilmActionPlan(
            "route_binary_subdirectory",
            field.tag_name,
            field.byte_range,
            "Route source bytes to the FujiFilm writable binary subdirectory table.",
            field.evidence_ids,
        )
    if field.value_class == "read_only_subdirectory":
        return FujiFilmActionPlan(
            "preserve_read_only_subdirectory",
            field.tag_name,
            field.byte_range,
            "Preserve source bytes for the FujiFilm read-only subdirectory boundary.",
            field.evidence_ids,
        )
    return FujiFilmActionPlan(
        "extract_known_tag",
        field.tag_name,
        field.byte_range,
        "Extract source-backed FujiFilm Main maker-note tag.",
        field.evidence_ids,
    )


def interpret_value(
    entry: FujiFilmIfdEntryPlan,
    spec: FujiFilmTagSpec,
    byte_order: FujiFilmByteOrder,
) -> FujiFilmRawValue:
    if spec.route != "main":
        return entry.raw_payload
    if spec.writable_format == "string":
        return decode_string(entry.raw_payload)
    if spec.writable_format == "undef":
        return entry.raw_payload
    if spec.writable_format == "int16u" and entry.exif_type == "short":
        return first_unsigned_integer(entry.raw_payload, 2, byte_order)
    if spec.writable_format == "int32u" and entry.exif_type == "long":
        return first_unsigned_integer(entry.raw_payload, 4, byte_order)
    if spec.writable_format == "int32s" and entry.exif_type == "slong":
        return int.from_bytes(entry.raw_payload[:4], byte_order, signed=True)
    return entry.raw_payload


def interpret_value_for_read(
    raw_value: FujiFilmRawValue,
    spec: FujiFilmTagSpec,
) -> FujiFilmInterpretedValue:
    if not isinstance(raw_value, int):
        return raw_value
    if spec.name == "Sharpness":
        return SHARPNESS_LABELS.get(raw_value, raw_value)
    if spec.name == "WhiteBalance":
        return WHITE_BALANCE_LABELS.get(raw_value, raw_value)
    if spec.name == "NoiseReduction":
        if raw_value == 0x100:
            return None
        return NOISE_REDUCTION_LABELS.get(raw_value, raw_value)
    if spec.name == "DigitalZoom":
        return raw_value // 8 if raw_value % 8 == 0 else raw_value / 8
    if spec.name == "ImageCount":
        return raw_value & 0x7FFF
    return raw_value


def conversion_boundary(spec: FujiFilmTagSpec) -> FujiFilmConversionBoundary:
    if spec.route == "writable_binary_subdirectory":
        return "binary_subdirectory_boundary"
    if spec.route == "read_only_subdirectory":
        return "face_recognition_boundary"
    if spec.writable_format == "string":
        return "string_value_boundary"
    if spec.name in {"Sharpness", "WhiteBalance"}:
        return "print_conversion"
    if spec.name == "NoiseReduction":
        return "raw_conversion"
    if spec.name in {"DigitalZoom", "ImageCount"}:
        return "value_conversion"
    return "none"


def plan_rewrites(
    fields: tuple[FujiFilmFieldPlan, ...],
    rewrite_requests: tuple[FujiFilmRewriteRequest, ...],
) -> tuple[tuple[FujiFilmOutputEmissionGate, ...], tuple[FujiFilmActionPlan, ...]]:
    fields_by_name = {field.tag_name: field for field in fields}
    seen_names: set[str] = set()
    gates: list[FujiFilmOutputEmissionGate] = []
    actions: list[FujiFilmActionPlan] = []
    for request in rewrite_requests:
        field = fields_by_name.get(request.tag_name)
        gate = rewrite_gate_for_request(request, field, seen_names)
        seen_names.add(request.tag_name)
        gates.append(gate)
        actions.append(
            FujiFilmActionPlan(
                "block_requested_rewrite",
                request.tag_name,
                field.byte_range if field is not None else None,
                gate.reason,
                gate.evidence_ids,
            )
        )
    return tuple(gates), tuple(actions)


def rewrite_gate_for_request(
    request: FujiFilmRewriteRequest,
    field: FujiFilmFieldPlan | None,
    seen_names: set[str],
) -> FujiFilmOutputEmissionGate:
    spec = FUJIFILM_TAGS_BY_NAME.get(request.tag_name)
    if request.tag_name in seen_names:
        return FujiFilmOutputEmissionGate(
            "duplicate_rewrite_tag",
            f"FujiFilm maker-note rewrite for {request.tag_name} was requested more than once.",
            (FUJIFILM_EXIF_WRITE_SOURCE,),
        )
    if spec is None:
        return FujiFilmOutputEmissionGate(
            "unknown_rewrite_tag",
            f"FujiFilm.pm does not define this slice tag: {request.tag_name}.",
            (FUJIFILM_MAIN_SOURCE,),
        )
    if spec.route == "read_only_subdirectory":
        return FujiFilmOutputEmissionGate(
            "read_only_rewrite_tag",
            f"FujiFilm tag {request.tag_name} routes to a read-only subdirectory boundary.",
            spec.evidence_ids,
        )
    if field is None:
        return FujiFilmOutputEmissionGate(
            "missing_source_tag_for_rewrite",
            f"FujiFilm maker-note tag {request.tag_name} is not present in the source payload.",
            spec.evidence_ids,
        )
    return FujiFilmOutputEmissionGate(
        "maker_note_rewrite_not_supported",
        (
            "This FujiFilm modernization slice classifies writable EXIF-backed tags "
            "but does not rewrite maker notes."
        ),
        (FUJIFILM_EXIF_WRITE_SOURCE, *field.evidence_ids),
    )


def first_unsigned_integer(raw_payload: bytes, size: int, byte_order: FujiFilmByteOrder) -> int:
    return int.from_bytes(raw_payload[:size], byte_order)


def decode_string(raw_payload: bytes) -> str:
    return raw_payload.split(b"\x00", 1)[0].decode("latin-1")


def read_u16(source_data: bytes, offset: int, byte_order: FujiFilmByteOrder) -> int:
    return int.from_bytes(source_data[offset : offset + 2], byte_order)


def read_u32(source_data: bytes, offset: int, byte_order: FujiFilmByteOrder) -> int:
    return int.from_bytes(source_data[offset : offset + 4], byte_order)


def collect_evidence_ids(
    fields: tuple[FujiFilmFieldPlan, ...],
    actions: tuple[FujiFilmActionPlan, ...],
    gates: tuple[FujiFilmOutputEmissionGate, ...],
) -> tuple[FujiFilmEvidenceId, ...]:
    collected: list[FujiFilmEvidenceId] = [FUJIFILM_MAIN_SOURCE, FUJIFILM_EXIF_WRITE_SOURCE]
    for field in fields:
        for reference in field.evidence_ids:
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
