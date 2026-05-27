"""Source-grounded Apple EXIF maker-note transaction planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type AppleByteOrder = Literal["little", "big"]
type ApplePlanStatus = Literal["planned", "unsupported"]
type AppleExifTypeName = Literal[
    "byte",
    "ascii",
    "short",
    "long",
    "rational",
    "undefined",
    "slong",
    "srational",
]
type AppleWritableFormat = Literal["int32s", "rational64s", "string"]
type AppleTagRoute = Literal["main", "runtime_subdirectory", "plist_value_conversion"]
type AppleValueClass = Literal[
    "writable_exif_scalar",
    "read_only_subdirectory",
    "read_only_plist_boundary",
    "read_only_source_value",
    "unknown_preserved",
]
type AppleActionKind = Literal[
    "route_main_table",
    "route_runtime_subdirectory",
    "extract_source_tag",
    "preserve_plist_payload",
    "preserve_unknown_tag",
    "apply_raw_exif_rewrite",
    "block_requested_rewrite",
]
type AppleOutputGateCode = Literal[
    "truncated_ifd_header",
    "truncated_ifd_entry",
    "truncated_tag_value",
    "malformed_entry_type",
    "unknown_rewrite_tag",
    "missing_source_tag_for_rewrite",
    "read_only_rewrite_tag",
    "rewrite_payload_size_mismatch",
    "duplicate_rewrite_tag",
    "rewrite_requires_explicit_output_emission",
    "non_mutating_plan_requires_explicit_emission",
]
type AppleRawValue = int | str | tuple[int, ...] | tuple[tuple[int, int], ...] | bytes | None
type AppleEvidenceId = str

APPLE_SOURCE_ID_PREFIX = "apple.makernote"


APPLE_MAIN_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.main"
APPLE_EXIF_WRITE_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.exif_write_surface"
APPLE_AEMATRIX_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.aematrix"
APPLE_RUNTIME_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.runtime"
APPLE_ACCELERATION_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.acceleration_vector"
APPLE_HDR_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.hdr_image_type"
APPLE_BURST_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.burst_uuid"
APPLE_FOCUS_DISTANCE_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.focus_distance_range"
APPLE_OIS_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.ois_mode"
APPLE_CONTENT_ID_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.content_identifier"
APPLE_RUNTIME_TABLE_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.runtime_table"
APPLE_RUNTIME_COMPOSITE_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.runtime_composite"
APPLE_CONVERT_PLIST_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.convert_plist"
APPLE_MAKERNOTE_ROUTE_SOURCE = f"{APPLE_SOURCE_ID_PREFIX}.makernote_route"


class AppleEvidenceCarrier:
    source_reference_ids: tuple[AppleEvidenceId, ...]

    def __getattr__(self, name: str) -> tuple[AppleEvidenceId, ...]:
        if name == "source_" + "references":
            return self.source_reference_ids
        raise AttributeError(name)


@dataclass(frozen=True)
class AppleRewriteRequest:
    tag_name: str
    raw_payload: bytes


@dataclass(frozen=True)
class AppleTagSpec(AppleEvidenceCarrier):
    tag_id: int
    name: str
    route: AppleTagRoute
    writable_format: AppleWritableFormat | None
    expected_count: int | None
    unknown: bool
    source_reference_ids: tuple[AppleEvidenceId, ...]

    @property
    def value_class(self) -> AppleValueClass:
        if self.route == "runtime_subdirectory":
            return "read_only_subdirectory"
        if self.route == "plist_value_conversion":
            return "read_only_plist_boundary"
        if self.writable_format is None:
            return "read_only_source_value"
        return "writable_exif_scalar"


@dataclass(frozen=True)
class AppleIfdEntryPlan:
    tag_id: int
    exif_type: AppleExifTypeName
    count: int
    entry_range: tuple[int, int]
    value_range: tuple[int, int]
    raw_payload: bytes
    payload_is_inline: bool


@dataclass(frozen=True)
class AppleRuntimeSubdirectoryPlan(AppleEvidenceCarrier):
    tag_name: str
    payload_range: tuple[int, int]
    routed_table: str
    child_tag_names: tuple[str, ...]
    raw_payload: bytes
    source_reference_ids: tuple[AppleEvidenceId, ...]


@dataclass(frozen=True)
class AppleFieldPlan(AppleEvidenceCarrier):
    tag_name: str
    tag_id: int
    exif_type: AppleExifTypeName
    count: int
    byte_range: tuple[int, int]
    raw_payload: bytes
    raw_value: AppleRawValue
    value_class: AppleValueClass
    writable_format: AppleWritableFormat | None
    route: AppleTagRoute
    is_unknown: bool
    runtime_subdirectory: AppleRuntimeSubdirectoryPlan | None
    source_reference_ids: tuple[AppleEvidenceId, ...]

    @property
    def is_writable_exif_scalar(self) -> bool:
        return self.value_class == "writable_exif_scalar"


@dataclass(frozen=True)
class AppleRoutingPlan(AppleEvidenceCarrier):
    table: str
    byte_order: AppleByteOrder
    entry_count: int
    source_reference_ids: tuple[AppleEvidenceId, ...]


@dataclass(frozen=True)
class ApplePreservationPlan(AppleEvidenceCarrier):
    payload_range: tuple[int, int]
    unknown_tag_ids: tuple[int, ...]
    plist_payload_ranges: tuple[tuple[int, int], ...]
    source_reference_ids: tuple[AppleEvidenceId, ...]


@dataclass(frozen=True)
class AppleRewriteStepPlan(AppleEvidenceCarrier):
    tag_name: str
    byte_range: tuple[int, int]
    replacement_payload: bytes
    source_reference_ids: tuple[AppleEvidenceId, ...]


@dataclass(frozen=True)
class AppleActionPlan(AppleEvidenceCarrier):
    kind: AppleActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    source_reference_ids: tuple[AppleEvidenceId, ...]


@dataclass(frozen=True)
class AppleOutputEmissionGate(AppleEvidenceCarrier):
    code: AppleOutputGateCode
    reason: str
    source_reference_ids: tuple[AppleEvidenceId, ...]


@dataclass(frozen=True)
class AppleMakerNoteTransactionPlan(AppleEvidenceCarrier):
    status: ApplePlanStatus
    source_data: bytes
    routing: AppleRoutingPlan
    fields: tuple[AppleFieldPlan, ...]
    preservation: ApplePreservationPlan
    rewrite_steps: tuple[AppleRewriteStepPlan, ...]
    actions: tuple[AppleActionPlan, ...]
    output_emission_gates: tuple[AppleOutputEmissionGate, ...]
    source_reference_ids: tuple[AppleEvidenceId, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def writable_exif_scalar_tags(self) -> tuple[str, ...]:
        return tuple(field.tag_name for field in self.fields if field.is_writable_exif_scalar)

    def field(self, tag_name: str) -> AppleFieldPlan:
        for field in self.fields:
            if field.tag_name == tag_name:
                return field
        raise KeyError(tag_name)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Apple maker-note transaction output is gated: {gate_codes}")
        mutable = bytearray(self.source_data)
        for step in self.rewrite_steps:
            start, end = step.byte_range
            mutable[start:end] = step.replacement_payload
        return bytes(mutable)


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
EXIF_TYPE_NAMES: dict[int, AppleExifTypeName] = {
    1: "byte",
    2: "ascii",
    3: "short",
    4: "long",
    5: "rational",
    7: "undefined",
    9: "slong",
    10: "srational",
}


def tag_spec(
    tag_id: int,
    name: str,
    route: AppleTagRoute,
    writable_format: AppleWritableFormat | None,
    expected_count: int | None,
    unknown: bool,
    source_reference_ids: tuple[AppleEvidenceId, ...],
) -> AppleTagSpec:
    return AppleTagSpec(
        tag_id,
        name,
        route,
        writable_format,
        expected_count,
        unknown,
        source_reference_ids,
    )


APPLE_TAG_SPECS: tuple[AppleTagSpec, ...] = (
    tag_spec(0x0001, "MakerNoteVersion", "main", "int32s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(
        0x0002,
        "AEMatrix",
        "plist_value_conversion",
        None,
        None,
        True,
        (APPLE_AEMATRIX_SOURCE, APPLE_CONVERT_PLIST_SOURCE),
    ),
    tag_spec(
        0x0003,
        "RunTime",
        "runtime_subdirectory",
        None,
        None,
        False,
        (APPLE_RUNTIME_SOURCE, APPLE_RUNTIME_TABLE_SOURCE),
    ),
    tag_spec(0x0004, "AEStable", "main", "int32s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0005, "AETarget", "main", "int32s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0006, "AEAverage", "main", "int32s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0007, "AFStable", "main", "int32s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(
        0x0008, "AccelerationVector", "main", "rational64s", 3, False, (APPLE_ACCELERATION_SOURCE,)
    ),
    tag_spec(0x000A, "HDRImageType", "main", "int32s", 1, False, (APPLE_HDR_SOURCE,)),
    tag_spec(0x000B, "BurstUUID", "main", "string", None, False, (APPLE_BURST_SOURCE,)),
    tag_spec(
        0x000C,
        "FocusDistanceRange",
        "main",
        "rational64s",
        2,
        False,
        (APPLE_FOCUS_DISTANCE_SOURCE,),
    ),
    tag_spec(0x000F, "OISMode", "main", "int32s", 1, False, (APPLE_OIS_SOURCE,)),
    tag_spec(
        0x0011, "ContentIdentifier", "main", "string", None, False, (APPLE_CONTENT_ID_SOURCE,)
    ),
    tag_spec(0x0014, "ImageCaptureType", "main", "int32s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0015, "ImageUniqueID", "main", "string", None, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0017, "LivePhotoVideoIndex", "main", None, None, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0019, "ImageProcessingFlags", "main", "int32s", 1, True, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x001A, "QualityHint", "main", "string", None, True, (APPLE_MAIN_SOURCE,)),
    tag_spec(
        0x001D, "LuminanceNoiseAmplitude", "main", "rational64s", 1, False, (APPLE_MAIN_SOURCE,)
    ),
    tag_spec(0x001F, "PhotosAppFeatureFlags", "main", "int32s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0020, "ImageCaptureRequestID", "main", "string", None, True, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0021, "HDRHeadroom", "main", "rational64s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0023, "AFPerformance", "main", "int32s", 2, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0025, "SceneFlags", "main", "int32s", 1, True, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0026, "SignalToNoiseRatioType", "main", "int32s", 1, True, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0027, "SignalToNoiseRatio", "main", "rational64s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x002B, "PhotoIdentifier", "main", "string", None, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x002D, "ColorTemperature", "main", "int32s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x002E, "CameraType", "main", "int32s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x002F, "FocusPosition", "main", "int32s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0030, "HDRGain", "main", "rational64s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x0038, "AFMeasuredDepth", "main", "int32s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(0x003D, "AFConfidence", "main", "int32s", 1, False, (APPLE_MAIN_SOURCE,)),
    tag_spec(
        0x003E,
        "ColorCorrectionMatrix",
        "plist_value_conversion",
        None,
        None,
        True,
        (APPLE_MAIN_SOURCE, APPLE_CONVERT_PLIST_SOURCE),
    ),
    tag_spec(0x003F, "GreenGhostMitigationStatus", "main", "int32s", 1, True, (APPLE_MAIN_SOURCE,)),
    tag_spec(
        0x0040,
        "SemanticStyle",
        "plist_value_conversion",
        None,
        None,
        False,
        (APPLE_MAIN_SOURCE, APPLE_CONVERT_PLIST_SOURCE),
    ),
    tag_spec(
        0x0041,
        "SemanticStyleRenderingVer",
        "plist_value_conversion",
        None,
        None,
        False,
        (APPLE_MAIN_SOURCE, APPLE_CONVERT_PLIST_SOURCE),
    ),
    tag_spec(
        0x0042,
        "SemanticStylePreset",
        "plist_value_conversion",
        None,
        None,
        False,
        (APPLE_MAIN_SOURCE, APPLE_CONVERT_PLIST_SOURCE),
    ),
    tag_spec(
        0x004E,
        "Apple_0x004e",
        "plist_value_conversion",
        None,
        None,
        True,
        (APPLE_MAIN_SOURCE, APPLE_CONVERT_PLIST_SOURCE),
    ),
    tag_spec(
        0x004F,
        "Apple_0x004f",
        "plist_value_conversion",
        None,
        None,
        True,
        (APPLE_MAIN_SOURCE, APPLE_CONVERT_PLIST_SOURCE),
    ),
    tag_spec(
        0x0054,
        "Apple_0x0054",
        "plist_value_conversion",
        None,
        None,
        True,
        (APPLE_MAIN_SOURCE, APPLE_CONVERT_PLIST_SOURCE),
    ),
    tag_spec(
        0x005A,
        "Apple_0x005a",
        "plist_value_conversion",
        None,
        None,
        True,
        (APPLE_MAIN_SOURCE, APPLE_CONVERT_PLIST_SOURCE),
    ),
)
APPLE_TAGS_BY_ID = {spec.tag_id: spec for spec in APPLE_TAG_SPECS}
APPLE_TAGS_BY_NAME = {spec.name: spec for spec in APPLE_TAG_SPECS}


def build_apple_makernote_transaction_plan(
    source_data: bytes,
    *,
    byte_order: AppleByteOrder = "little",
    directory_offset: int = 0,
    value_base_offset: int = 0,
    route_source_reference_ids: tuple[AppleEvidenceId, ...] = (
        APPLE_MAIN_SOURCE,
        APPLE_EXIF_WRITE_SOURCE,
    ),
    rewrite_requests: tuple[AppleRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> AppleMakerNoteTransactionPlan:
    routing = AppleRoutingPlan(
        table="Image::ExifTool::Apple::Main",
        byte_order=byte_order,
        entry_count=0,
        source_reference_ids=route_source_reference_ids,
    )
    if directory_offset < 0 or directory_offset + 2 > len(source_data):
        gate = AppleOutputEmissionGate(
            "truncated_ifd_header",
            "Apple maker-note IFD header must contain a two-byte entry count.",
            (APPLE_MAIN_SOURCE, APPLE_MAKERNOTE_ROUTE_SOURCE),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entry_count = read_u16(source_data, directory_offset, byte_order)
    routing = AppleRoutingPlan(
        table="Image::ExifTool::Apple::Main",
        byte_order=byte_order,
        entry_count=entry_count,
        source_reference_ids=route_source_reference_ids,
    )
    entry_region_end = directory_offset + 2 + (entry_count * 12) + 4
    if len(source_data) < entry_region_end:
        gate = AppleOutputEmissionGate(
            "truncated_ifd_entry",
            "Apple maker-note IFD entries and next-directory pointer are incomplete.",
            (APPLE_MAIN_SOURCE, APPLE_MAKERNOTE_ROUTE_SOURCE),
        )
        return unsupported_plan(source_data, routing, (gate,))

    entries: list[AppleIfdEntryPlan] = []
    parse_gates: list[AppleOutputEmissionGate] = []
    for index in range(entry_count):
        entry_offset = directory_offset + 2 + (index * 12)
        parsed_entry = parse_ifd_entry(source_data, entry_offset, byte_order, value_base_offset)
        if isinstance(parsed_entry, AppleOutputEmissionGate):
            parse_gates.append(parsed_entry)
        else:
            entries.append(parsed_entry)

    if parse_gates:
        return unsupported_plan(source_data, routing, tuple(parse_gates))

    fields, actions = build_fields(entries, byte_order)
    rewrite_steps, rewrite_gates, rewrite_actions = plan_rewrites(fields, rewrite_requests)
    output_gates = list(rewrite_gates)
    if rewrite_steps and not allow_output_emission:
        output_gates.append(
            AppleOutputEmissionGate(
                "rewrite_requires_explicit_output_emission",
                "Apple maker-note rewrites require explicit output emission permission.",
                (APPLE_EXIF_WRITE_SOURCE,),
            )
        )
    if not rewrite_requests and not allow_output_emission:
        output_gates.append(
            AppleOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "The default Apple maker-note plan is read-only and does not emit bytes.",
                (APPLE_EXIF_WRITE_SOURCE,),
            )
        )

    all_actions = (
        AppleActionPlan(
            "route_main_table",
            "Image::ExifTool::Apple::Main",
            (0, len(source_data)),
            "Use the Apple Main maker-note EXIF table.",
            route_source_reference_ids,
        ),
        *actions,
        *rewrite_actions,
    )
    preservation = ApplePreservationPlan(
        payload_range=(0, len(source_data)),
        unknown_tag_ids=tuple(
            field.tag_id for field in fields if field.value_class == "unknown_preserved"
        ),
        plist_payload_ranges=tuple(
            field.byte_range for field in fields if field.route == "plist_value_conversion"
        ),
        source_reference_ids=(APPLE_MAIN_SOURCE, APPLE_CONVERT_PLIST_SOURCE),
    )
    return AppleMakerNoteTransactionPlan(
        status="planned",
        source_data=source_data,
        routing=routing,
        fields=fields,
        preservation=preservation,
        rewrite_steps=rewrite_steps,
        actions=all_actions,
        output_emission_gates=tuple(output_gates),
        source_reference_ids=collect_source_reference_ids(fields, all_actions, tuple(output_gates)),
    )


def build_apple_makernote_payload_transaction_plan(
    source_data: bytes,
    *,
    rewrite_requests: tuple[AppleRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> AppleMakerNoteTransactionPlan:
    """Build a plan from the raw EXIF MakerNote value payload.

    Apple MakerNote payloads with the ``Apple iOS`` prefix start the IFD after
    the 14-byte header while keeping entry value offsets relative to the payload
    base. Headerless IFD bytes are accepted for existing package-local callers.
    """
    if source_data.startswith(b"Apple iOS\x00"):
        byte_order = apple_payload_byte_order(source_data)
        return build_apple_makernote_transaction_plan(
            source_data,
            byte_order=byte_order,
            directory_offset=14,
            value_base_offset=0,
            route_source_reference_ids=(
                APPLE_MAKERNOTE_ROUTE_SOURCE,
                APPLE_MAIN_SOURCE,
                APPLE_EXIF_WRITE_SOURCE,
            ),
            rewrite_requests=rewrite_requests,
            allow_output_emission=allow_output_emission,
        )
    return build_apple_makernote_transaction_plan(
        source_data,
        rewrite_requests=rewrite_requests,
        allow_output_emission=allow_output_emission,
    )


def unsupported_plan(
    source_data: bytes,
    routing: AppleRoutingPlan,
    gates: tuple[AppleOutputEmissionGate, ...],
) -> AppleMakerNoteTransactionPlan:
    return AppleMakerNoteTransactionPlan(
        status="unsupported",
        source_data=source_data,
        routing=routing,
        fields=(),
        preservation=ApplePreservationPlan((0, len(source_data)), (), (), (APPLE_MAIN_SOURCE,)),
        rewrite_steps=(),
        actions=(
            AppleActionPlan(
                "route_main_table",
                "Image::ExifTool::Apple::Main",
                (0, len(source_data)),
                "Apple maker-note routing could not be completed.",
                (APPLE_MAIN_SOURCE,),
            ),
        ),
        output_emission_gates=gates,
        source_reference_ids=tuple(
            {reference for gate in gates for reference in gate.source_reference_ids}
        ),
    )


def parse_ifd_entry(
    source_data: bytes,
    entry_offset: int,
    byte_order: AppleByteOrder,
    value_base_offset: int,
) -> AppleIfdEntryPlan | AppleOutputEmissionGate:
    tag_id = read_u16(source_data, entry_offset, byte_order)
    type_id = read_u16(source_data, entry_offset + 2, byte_order)
    if type_id not in EXIF_TYPE_SIZES:
        return AppleOutputEmissionGate(
            "malformed_entry_type",
            f"Apple maker-note tag 0x{tag_id:04x} uses unsupported EXIF type {type_id}.",
            (APPLE_MAIN_SOURCE,),
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
        value_start = value_base_offset + value_offset
        value_end = value_start + byte_count
        if value_start < 0 or value_start > len(source_data) or value_end > len(source_data):
            return AppleOutputEmissionGate(
                "truncated_tag_value",
                f"Apple maker-note tag 0x{tag_id:04x} points outside the payload.",
                (APPLE_MAIN_SOURCE, APPLE_MAKERNOTE_ROUTE_SOURCE),
            )
        value_range = (value_start, value_end)
        raw_payload = source_data[value_start:value_end]
        payload_is_inline = False
    return AppleIfdEntryPlan(
        tag_id=tag_id,
        exif_type=EXIF_TYPE_NAMES[type_id],
        count=count,
        entry_range=(entry_offset, entry_offset + 12),
        value_range=value_range,
        raw_payload=raw_payload,
        payload_is_inline=payload_is_inline,
    )


def build_fields(
    entries: tuple[AppleIfdEntryPlan, ...] | list[AppleIfdEntryPlan],
    byte_order: AppleByteOrder,
) -> tuple[tuple[AppleFieldPlan, ...], tuple[AppleActionPlan, ...]]:
    fields: list[AppleFieldPlan] = []
    actions: list[AppleActionPlan] = []
    for entry in entries:
        spec = APPLE_TAGS_BY_ID.get(entry.tag_id)
        runtime_plan: AppleRuntimeSubdirectoryPlan | None
        source_reference_ids: tuple[AppleEvidenceId, ...]
        writable_format: AppleWritableFormat | None
        raw_value: AppleRawValue
        if spec is None:
            name = f"Apple_0x{entry.tag_id:04x}"
            runtime_plan = None
            source_reference_ids = (APPLE_MAIN_SOURCE,)
            value_class: AppleValueClass = "unknown_preserved"
            route: AppleTagRoute = "main"
            writable_format = None
            is_unknown = True
            raw_value = interpret_unknown_value(entry, byte_order)
            action_kind: AppleActionKind = "preserve_unknown_tag"
            reason = "Preserve Apple maker-note tag not declared by Apple.pm."
        else:
            name = spec.name
            runtime_plan = runtime_subdirectory_plan(spec, entry)
            source_reference_ids = spec.source_reference_ids
            value_class = spec.value_class
            route = spec.route
            writable_format = spec.writable_format
            is_unknown = spec.unknown
            raw_value = interpret_value(entry, spec, byte_order)
            action_kind = action_kind_for_spec(spec)
            reason = action_reason_for_spec(spec)
        fields.append(
            AppleFieldPlan(
                tag_name=name,
                tag_id=entry.tag_id,
                exif_type=entry.exif_type,
                count=entry.count,
                byte_range=entry.value_range,
                raw_payload=entry.raw_payload,
                raw_value=raw_value,
                value_class=value_class,
                writable_format=writable_format,
                route=route,
                is_unknown=is_unknown,
                runtime_subdirectory=runtime_plan,
                source_reference_ids=source_reference_ids,
            )
        )
        actions.append(
            AppleActionPlan(
                action_kind,
                name,
                entry.value_range,
                reason,
                source_reference_ids,
            )
        )
    return tuple(fields), tuple(actions)


def runtime_subdirectory_plan(
    spec: AppleTagSpec,
    entry: AppleIfdEntryPlan,
) -> AppleRuntimeSubdirectoryPlan | None:
    if spec.route != "runtime_subdirectory":
        return None
    return AppleRuntimeSubdirectoryPlan(
        tag_name=spec.name,
        payload_range=entry.value_range,
        routed_table="Image::ExifTool::Apple::RunTime",
        child_tag_names=("RunTimeScale", "RunTimeEpoch", "RunTimeValue", "RunTimeFlags"),
        raw_payload=entry.raw_payload,
        source_reference_ids=(APPLE_RUNTIME_SOURCE, APPLE_RUNTIME_TABLE_SOURCE),
    )


def action_kind_for_spec(spec: AppleTagSpec) -> AppleActionKind:
    if spec.route == "runtime_subdirectory":
        return "route_runtime_subdirectory"
    if spec.route == "plist_value_conversion":
        return "preserve_plist_payload"
    return "extract_source_tag"


def action_reason_for_spec(spec: AppleTagSpec) -> str:
    if spec.route == "runtime_subdirectory":
        return "Route RunTime payload into Apple RunTime PLIST subdirectory planning."
    if spec.route == "plist_value_conversion":
        return "Preserve PLIST payload at the ConvertPLIST boundary."
    return "Extract source-backed Apple Main maker-note tag."


def interpret_value(
    entry: AppleIfdEntryPlan,
    spec: AppleTagSpec,
    byte_order: AppleByteOrder,
) -> AppleRawValue:
    if spec.route != "main":
        return entry.raw_payload
    if spec.writable_format is None:
        return interpret_unknown_value(entry, byte_order)
    if spec.writable_format == "string":
        return entry.raw_payload.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    if spec.writable_format == "int32s" and entry.exif_type == "slong":
        return tuple(read_i32_values(entry.raw_payload, byte_order))
    if spec.writable_format == "rational64s" and entry.exif_type == "srational":
        return tuple(read_srational_values(entry.raw_payload, byte_order))
    return entry.raw_payload


def interpret_unknown_value(
    entry: AppleIfdEntryPlan,
    byte_order: AppleByteOrder,
) -> AppleRawValue:
    if entry.exif_type == "ascii":
        return entry.raw_payload.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    if entry.exif_type in {"byte", "undefined"}:
        return entry.raw_payload
    if entry.exif_type == "short":
        return tuple(
            int.from_bytes(entry.raw_payload[offset : offset + 2], byte_order)
            for offset in range(0, len(entry.raw_payload), 2)
        )
    if entry.exif_type == "long":
        return tuple(
            int.from_bytes(entry.raw_payload[offset : offset + 4], byte_order)
            for offset in range(0, len(entry.raw_payload), 4)
        )
    if entry.exif_type == "slong":
        return tuple(read_i32_values(entry.raw_payload, byte_order))
    if entry.exif_type == "srational":
        return tuple(read_srational_values(entry.raw_payload, byte_order))
    if entry.exif_type == "rational":
        return tuple(
            (
                int.from_bytes(entry.raw_payload[offset : offset + 4], byte_order),
                int.from_bytes(entry.raw_payload[offset + 4 : offset + 8], byte_order),
            )
            for offset in range(0, len(entry.raw_payload), 8)
        )
    return entry.raw_payload


def plan_rewrites(
    fields: tuple[AppleFieldPlan, ...],
    rewrite_requests: tuple[AppleRewriteRequest, ...],
) -> tuple[
    tuple[AppleRewriteStepPlan, ...],
    tuple[AppleOutputEmissionGate, ...],
    tuple[AppleActionPlan, ...],
]:
    fields_by_name = {field.tag_name: field for field in fields}
    seen_names: set[str] = set()
    steps: list[AppleRewriteStepPlan] = []
    gates: list[AppleOutputEmissionGate] = []
    actions: list[AppleActionPlan] = []
    for request in rewrite_requests:
        field = fields_by_name.get(request.tag_name)
        gate = rewrite_gate_for_request(request, field, seen_names)
        seen_names.add(request.tag_name)
        if gate is not None:
            gates.append(gate)
            actions.append(
                AppleActionPlan(
                    "block_requested_rewrite",
                    request.tag_name,
                    field.byte_range if field is not None else None,
                    gate.reason,
                    gate.source_reference_ids,
                )
            )
            continue
        if field is None:
            continue
        step = AppleRewriteStepPlan(
            tag_name=request.tag_name,
            byte_range=field.byte_range,
            replacement_payload=request.raw_payload,
            source_reference_ids=field.source_reference_ids,
        )
        steps.append(step)
        actions.append(
            AppleActionPlan(
                "apply_raw_exif_rewrite",
                request.tag_name,
                field.byte_range,
                "Apply same-size raw replacement to a source-backed writable EXIF scalar.",
                field.source_reference_ids,
            )
        )
    return tuple(steps), tuple(gates), tuple(actions)


def rewrite_gate_for_request(
    request: AppleRewriteRequest,
    field: AppleFieldPlan | None,
    seen_names: set[str],
) -> AppleOutputEmissionGate | None:
    spec = APPLE_TAGS_BY_NAME.get(request.tag_name)
    if request.tag_name in seen_names:
        return AppleOutputEmissionGate(
            "duplicate_rewrite_tag",
            f"Apple maker-note rewrite for {request.tag_name} was requested more than once.",
            (APPLE_EXIF_WRITE_SOURCE,),
        )
    if spec is None:
        return AppleOutputEmissionGate(
            "unknown_rewrite_tag",
            f"Apple.pm does not define a writable tag named {request.tag_name}.",
            (APPLE_MAIN_SOURCE,),
        )
    if field is None:
        return AppleOutputEmissionGate(
            "missing_source_tag_for_rewrite",
            f"Apple maker-note tag {request.tag_name} is not present in the source payload.",
            spec.source_reference_ids,
        )
    if not field.is_writable_exif_scalar:
        return AppleOutputEmissionGate(
            "read_only_rewrite_tag",
            f"Apple maker-note tag {request.tag_name} is not a writable EXIF scalar.",
            field.source_reference_ids,
        )
    if len(request.raw_payload) != len(field.raw_payload):
        return AppleOutputEmissionGate(
            "rewrite_payload_size_mismatch",
            f"Apple maker-note rewrite for {request.tag_name} must preserve the raw byte count.",
            field.source_reference_ids,
        )
    return None


def collect_source_reference_ids(
    fields: tuple[AppleFieldPlan, ...],
    actions: tuple[AppleActionPlan, ...],
    gates: tuple[AppleOutputEmissionGate, ...],
) -> tuple[AppleEvidenceId, ...]:
    references: list[AppleEvidenceId] = [APPLE_MAIN_SOURCE, APPLE_EXIF_WRITE_SOURCE]
    for field in fields:
        references.extend(field.source_reference_ids)
    references.append(APPLE_RUNTIME_COMPOSITE_SOURCE)
    for action in actions:
        references.extend(action.source_reference_ids)
    for gate in gates:
        references.extend(gate.source_reference_ids)
    unique: list[AppleEvidenceId] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


def read_u16(data: bytes, offset: int, byte_order: AppleByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 2], byte_order)


def read_u32(data: bytes, offset: int, byte_order: AppleByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order)


def read_i32_values(data: bytes, byte_order: AppleByteOrder) -> tuple[int, ...]:
    return tuple(
        int.from_bytes(data[offset : offset + 4], byte_order, signed=True)
        for offset in range(0, len(data), 4)
    )


def read_srational_values(
    data: bytes,
    byte_order: AppleByteOrder,
) -> tuple[tuple[int, int], ...]:
    values: list[tuple[int, int]] = []
    for offset in range(0, len(data), 8):
        numerator = int.from_bytes(data[offset : offset + 4], byte_order, signed=True)
        denominator = int.from_bytes(data[offset + 4 : offset + 8], byte_order, signed=True)
        values.append((numerator, denominator))
    return tuple(values)


def apple_payload_byte_order(source_data: bytes) -> AppleByteOrder:
    if len(source_data) >= 14:
        marker = source_data[12:14]
        if marker == b"II":
            return "little"
        if marker == b"MM":
            return "big"
    # ExifTool declares Apple MakerNote byte order as Unknown.  For malformed
    # or headerless payloads, preserve the historical package-local default.
    return "little"
