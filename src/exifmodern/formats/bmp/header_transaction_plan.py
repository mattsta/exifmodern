"""Source-grounded, non-mutating BMP/DIB header transaction plans.

The planner mirrors ExifTool's ``BMP.pm`` reader: it validates the ``BM``
signature, routes DIB header sizes to the OS/2 or Windows tables, extracts the
same image-header responsibilities, preserves color-table and pixel-data
boundaries, and discovers ExifTool-modeled embedded JPEG/PNG payloads and V5
profile data.  It never rewrites BMP bytes unless output emission is explicitly
allowed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.icc.reader import (
    parse_icc_header_tags,
    parse_icc_profile_tags,
    validate_icc_profile,
)
from exifmodern.json_types import JsonArray, JsonObject, JsonValue
from exifmodern.read_graph import BinaryTagValue, ReadTag, TagProvenance

BMP_FILE_HEADER_SIZE = 14
BMP_EXIFTOOL_INITIAL_READ_SIZE = 18
BMP_MAX_EXIFTOOL_DIB_HEADER_SIZE = 1_000_000
BMP_SIGNATURE = b"BM"

type BmpPlanStatus = Literal["planned", "unsupported"]
type BmpDibFamily = Literal["os2", "windows", "unsupported"]
type BmpDibVersion = Literal[
    "os2_v1",
    "os2_v2_short",
    "os2_v2",
    "windows_v3",
    "avi_bmp_structure",
    "windows_v4",
    "windows_v5",
    "windows_extended",
    "unsupported",
]
type BmpCompressionRoute = Literal[
    "none",
    "rle8",
    "rle4",
    "bitfields",
    "jpeg",
    "png",
    "avi_codec",
    "unknown",
    "not_available",
]
type BmpMetadataKind = Literal["embedded_jpg", "embedded_png", "linked_profile_name", "icc_profile"]
type BmpEmbeddedMetadataKind = Literal["embedded_jpg", "embedded_png"]
type BmpEmbeddedSourceTag = Literal["EmbeddedJPG", "EmbeddedPNG"]
type BmpOptionalExtraStatus = Literal["not_present", "planned", "unsupported"]
type BmpScalarValue = str | int | float
type BmpReadScalarValue = str | int | float | bool
type BmpEndpointValue = tuple[int, int, int]
type BmpActionKind = Literal[
    "validate_signature",
    "route_dib_header",
    "extract_image_header_fields",
    "preserve_file_header",
    "preserve_dib_header",
    "preserve_color_table",
    "preserve_pixel_data",
    "preserve_profile_payload",
    "preserve_embedded_payload",
]
type BmpVariantGateCode = Literal[
    "os2_header_routed_preserve_only",
    "avi_bmp_header_tail_ignored",
    "unknown_windows_header_preserve_only",
]
type BmpEmissionGateCode = Literal[
    "truncated_bmp_file_header",
    "unsupported_bm_signature",
    "unsupported_dib_header_size",
    "truncated_dib_header",
    "pixel_data_offset_before_dib_header_end",
    "pixel_data_offset_exceeds_input",
    "declared_file_size_exceeds_input",
    "embedded_payload_exceeds_input",
    "profile_data_exceeds_input",
    "non_mutating_plan_requires_explicit_emission",
]
type BmpEvidenceId = str


@dataclass(frozen=True)
class BmpEvidenceAnchor:
    path: str
    line_start: int
    line_end: int
    symbol: str
    evidence: str


BMP_SIGNATURE_SOURCE: BmpEvidenceId = "bmp.process.signature_gate"
BMP_DIB_SIZE_SOURCE: BmpEvidenceId = "bmp.process.dib_header_length_gate"
BMP_MAIN_TABLE_SOURCE: BmpEvidenceId = "bmp.table.main_scalars"
BMP_WINDOWS_EXTENDED_SOURCE: BmpEvidenceId = "bmp.table.main_extended_fields"
BMP_OS2_TABLE_SOURCE: BmpEvidenceId = "bmp.table.os2"
BMP_TABLE_ROUTING_SOURCE: BmpEvidenceId = "bmp.process.dib_table_routing"
BMP_EXTRA_TABLE_SOURCE: BmpEvidenceId = "bmp.table.extra"
BMP_FILE_TYPE_SOURCE: BmpEvidenceId = "bmp.process.set_file_type"
BMP_EMBEDDED_IMAGE_SOURCE: BmpEvidenceId = "bmp.process.embedded_image_extraction"
BMP_PROFILE_SOURCE: BmpEvidenceId = "bmp.process.v5_profile_extraction"
BMP_COMPOSITE_TEST_SOURCE: BmpEvidenceId = "bmp.oracle.composite_image_geometry"

BMP_EVIDENCE_ANCHORS: dict[BmpEvidenceId, BmpEvidenceAnchor] = {
    BMP_SIGNATURE_SOURCE: BmpEvidenceAnchor(
        path="lib/Image/ExifTool/BMP.pm",
        line_start=260,
        line_end=263,
        symbol="ProcessBMP signature gate",
        evidence="ProcessBMP reads 18 bytes, requires /^BM/, and sets little-endian byte order.",
    ),
    BMP_DIB_SIZE_SOURCE: BmpEvidenceAnchor(
        path="lib/Image/ExifTool/BMP.pm",
        line_start=264,
        line_end=268,
        symbol="ProcessBMP DIB header length gate",
        evidence=(
            "ProcessBMP reads the DIB header size at file offset 14 and accepts 12, 16, "
            "or sizes >= 40 and < 1000000."
        ),
    ),
    BMP_MAIN_TABLE_SOURCE: BmpEvidenceAnchor(
        path="lib/Image/ExifTool/BMP.pm",
        line_start=43,
        line_end=120,
        symbol="%Image::ExifTool::BMP::Main scalar fields",
        evidence=(
            "The Windows table maps DIB offsets for version, width, height, planes, "
            "bit depth, compression, image length, resolution, and color counts."
        ),
    ),
    BMP_WINDOWS_EXTENDED_SOURCE: BmpEvidenceAnchor(
        path="lib/Image/ExifTool/BMP.pm",
        line_start=122,
        line_end=211,
        symbol="%Image::ExifTool::BMP::Main masks and profile fields",
        evidence=(
            "The Windows table maps color masks, color space, calibrated endpoints, "
            "rendering intent, and profile offset/size fields."
        ),
    ),
    BMP_OS2_TABLE_SOURCE: BmpEvidenceAnchor(
        path="lib/Image/ExifTool/BMP.pm",
        line_start=214,
        line_end=232,
        symbol="%Image::ExifTool::BMP::OS2",
        evidence="The OS/2 table extracts version, 16-bit width, height, planes, and bit depth.",
    ),
    BMP_TABLE_ROUTING_SOURCE: BmpEvidenceAnchor(
        path="lib/Image/ExifTool/BMP.pm",
        line_start=270,
        line_end=282,
        symbol="ProcessBMP DIB table routing",
        evidence="ProcessBMP routes DIB sizes 12, 16, and 64 to OS/2; all others use Main.",
    ),
    BMP_EXTRA_TABLE_SOURCE: BmpEvidenceAnchor(
        path="lib/Image/ExifTool/BMP.pm",
        line_start=234,
        line_end=248,
        symbol="%Image::ExifTool::BMP::Extra",
        evidence=(
            "The Extra table models LinkedProfileName, ICC_Profile, EmbeddedJPG, and EmbeddedPNG."
        ),
    ),
    BMP_FILE_TYPE_SOURCE: BmpEvidenceAnchor(
        path="lib/Image/ExifTool/BMP.pm",
        line_start=268,
        line_end=268,
        symbol="ProcessBMP SetFileType",
        evidence=(
            "ProcessBMP calls SetFileType after accepting the BM signature and supported DIB "
            "header."
        ),
    ),
    BMP_EMBEDDED_IMAGE_SOURCE: BmpEvidenceAnchor(
        path="lib/Image/ExifTool/BMP.pm",
        line_start=284,
        line_end=295,
        symbol="ProcessBMP embedded image extraction",
        evidence="ProcessBMP extracts EmbeddedJPG or EmbeddedPNG when compression is 4 or 5.",
    ),
    BMP_PROFILE_SOURCE: BmpEvidenceAnchor(
        path="lib/Image/ExifTool/BMP.pm",
        line_start=297,
        line_end=315,
        symbol="ProcessBMP V5 profile extraction",
        evidence=(
            "ProcessBMP loads V5 profile data at ProfileDataOffset + 14 and routes LINK "
            "to LinkedProfileName, otherwise ICC_Profile."
        ),
    ),
    BMP_COMPOSITE_TEST_SOURCE: BmpEvidenceAnchor(
        path="t/BMP_2.out",
        line_start=23,
        line_end=24,
        symbol="BMP test 2 Composite ImageSize and Megapixels",
        evidence=(
            "The BMP fixture oracle emits Composite ImageSize and Megapixels after BMP header "
            "scalars."
        ),
    ),
}

BMP_TRANSACTION_SOURCES = (
    BMP_SIGNATURE_SOURCE,
    BMP_DIB_SIZE_SOURCE,
    BMP_MAIN_TABLE_SOURCE,
    BMP_WINDOWS_EXTENDED_SOURCE,
    BMP_OS2_TABLE_SOURCE,
    BMP_TABLE_ROUTING_SOURCE,
    BMP_EXTRA_TABLE_SOURCE,
    BMP_FILE_TYPE_SOURCE,
    BMP_EMBEDDED_IMAGE_SOURCE,
    BMP_PROFILE_SOURCE,
    BMP_COMPOSITE_TEST_SOURCE,
)


@dataclass(frozen=True)
class BmpSignaturePlan:
    signature: bytes
    declared_file_size: int | None
    pixel_data_offset: int | None
    is_bmp: bool
    reason: BmpEmissionGateCode | None
    evidence_ids: tuple[BmpEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "declared_file_size": self.declared_file_size,
            "is_bmp": self.is_bmp,
            "pixel_data_offset": self.pixel_data_offset,
            "reason": self.reason,
            "signature": self.signature.hex(),
        }


@dataclass(frozen=True)
class BmpDibHeaderPlan:
    header_size: int | None
    family: BmpDibFamily
    version: BmpDibVersion
    header_offset: int
    header_end_offset: int | None
    is_exiftool_supported_size: bool
    evidence_ids: tuple[BmpEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "family": self.family,
            "header_end_offset": self.header_end_offset,
            "header_offset": self.header_offset,
            "header_size": self.header_size,
            "is_exiftool_supported_size": self.is_exiftool_supported_size,
            "version": self.version,
        }


@dataclass(frozen=True)
class BmpHeaderFieldPlan:
    image_width: int | None
    image_height: int | None
    raw_image_height: int | None
    top_down: bool | None
    planes: int | None
    bit_depth: int | None
    compression: int | None
    compression_route: BmpCompressionRoute
    image_length: int | None
    pixels_per_meter_x: int | None
    pixels_per_meter_y: int | None
    num_colors: int | None
    num_important_colors: int | None
    red_mask: int | None
    green_mask: int | None
    blue_mask: int | None
    alpha_mask: int | None
    color_space: str | None
    red_endpoint: BmpEndpointValue | None
    green_endpoint: BmpEndpointValue | None
    blue_endpoint: BmpEndpointValue | None
    gamma_red: int | None
    gamma_green: int | None
    gamma_blue: int | None
    rendering_intent: int | None
    profile_data_offset: int | None
    profile_size: int | None
    evidence_ids: tuple[BmpEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "bit_depth": self.bit_depth,
            "compression": self.compression,
            "compression_route": self.compression_route,
            "image_height": self.image_height,
            "image_length": self.image_length,
            "image_width": self.image_width,
            "num_colors": self.num_colors,
            "num_important_colors": self.num_important_colors,
            "pixels_per_meter_x": self.pixels_per_meter_x,
            "pixels_per_meter_y": self.pixels_per_meter_y,
            "planes": self.planes,
            "red_mask": self.red_mask,
            "green_mask": self.green_mask,
            "blue_mask": self.blue_mask,
            "alpha_mask": self.alpha_mask,
            "profile_data_offset": self.profile_data_offset,
            "profile_size": self.profile_size,
            "red_endpoint": json_int_tuple(self.red_endpoint),
            "green_endpoint": json_int_tuple(self.green_endpoint),
            "blue_endpoint": json_int_tuple(self.blue_endpoint),
            "gamma_red": self.gamma_red,
            "gamma_green": self.gamma_green,
            "gamma_blue": self.gamma_blue,
            "rendering_intent": self.rendering_intent,
            "raw_image_height": self.raw_image_height,
            "top_down": self.top_down,
        }


@dataclass(frozen=True)
class BmpBoundaryPlan:
    file_header_range: tuple[int, int]
    dib_header_range: tuple[int, int] | None
    color_table_range: tuple[int, int] | None
    color_table_entry_size: int | None
    color_table_entry_count: int | None
    expected_color_table_size: int | None
    pixel_data_range: tuple[int, int] | None
    trailing_data_range: tuple[int, int] | None
    evidence_ids: tuple[BmpEvidenceId, ...]

    @property
    def color_table_size(self) -> int:
        if self.color_table_range is None:
            return 0
        start, end = self.color_table_range
        return end - start

    @property
    def pixel_data_size(self) -> int:
        if self.pixel_data_range is None:
            return 0
        start, end = self.pixel_data_range
        return end - start

    def to_json(self) -> JsonObject:
        return {
            "color_table_entry_count": self.color_table_entry_count,
            "color_table_entry_size": self.color_table_entry_size,
            "color_table_range": json_range(self.color_table_range),
            "color_table_size": self.color_table_size,
            "dib_header_range": json_range(self.dib_header_range),
            "expected_color_table_size": self.expected_color_table_size,
            "file_header_range": json_range(self.file_header_range),
            "pixel_data_range": json_range(self.pixel_data_range),
            "pixel_data_size": self.pixel_data_size,
            "trailing_data_range": json_range(self.trailing_data_range),
        }


@dataclass(frozen=True)
class BmpProfilePlan:
    color_space: str | None
    profile_data_offset: int | None
    profile_size: int | None
    file_offset: int | None
    metadata_kind: BmpMetadataKind | None
    payload: bytes | None
    evidence_ids: tuple[BmpEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "color_space": self.color_space,
            "file_offset": self.file_offset,
            "metadata_kind": self.metadata_kind,
            "payload_size": None if self.payload is None else len(self.payload),
            "profile_data_offset": self.profile_data_offset,
            "profile_size": self.profile_size,
        }


@dataclass(frozen=True)
class BmpMetadataPayloadPlan:
    metadata_kind: BmpEmbeddedMetadataKind
    file_offset: int
    size: int
    payload: bytes
    evidence_ids: tuple[BmpEvidenceId, ...]

    @property
    def source_tag(self) -> BmpEmbeddedSourceTag:
        if self.metadata_kind == "embedded_jpg":
            return "EmbeddedJPG"
        return "EmbeddedPNG"

    @property
    def media_type(self) -> str:
        if self.metadata_kind == "embedded_jpg":
            return "image/jpeg"
        return "image/png"

    @property
    def file_extension(self) -> str:
        if self.metadata_kind == "embedded_jpg":
            return "jpg"
        return "png"

    def to_binary_tag_value(self) -> BinaryTagValue:
        return BinaryTagValue(
            self.payload,
            media_type=self.media_type,
            file_extension=self.file_extension,
        )

    def to_read_tag(self) -> ReadTag:
        return ReadTag(
            name=self.source_tag,
            value=self.to_binary_tag_value(),
            provenance=TagProvenance(
                group="File",
                table_name="Image::ExifTool::BMP::Extra",
                tag_id=self.source_tag,
                source=f"bmp-extra:{self.file_offset}:{self.size}",
                family_0_group="File",
                family_1_group="File",
                family_2_group="Preview",
            ),
            schema=None,
        )

    def to_json(self) -> JsonObject:
        return {
            "file_offset": self.file_offset,
            "file_extension": self.file_extension,
            "media_type": self.media_type,
            "metadata_kind": self.metadata_kind,
            "payload_size": len(self.payload),
            "size": self.size,
            "source_tag": self.source_tag,
        }


@dataclass(frozen=True)
class BmpOptionalExtraConclusion:
    embedded_status: BmpOptionalExtraStatus
    embedded_reason: str
    profile_status: BmpOptionalExtraStatus
    profile_reason: str
    evidence_ids: tuple[BmpEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "embedded_reason": self.embedded_reason,
            "embedded_status": self.embedded_status,
            "profile_reason": self.profile_reason,
            "profile_status": self.profile_status,
        }


@dataclass(frozen=True)
class BmpVariantGate:
    code: BmpVariantGateCode
    reason: str
    evidence_ids: tuple[BmpEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BmpOutputEmissionGate:
    code: BmpEmissionGateCode
    reason: str
    evidence_ids: tuple[BmpEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BmpActionPlan:
    kind: BmpActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[BmpEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": json_range(self.byte_range),
            "kind": self.kind,
            "reason": self.reason,
            "target": self.target,
        }


@dataclass(frozen=True)
class BmpHeaderTransactionPlan:
    status: BmpPlanStatus
    source_data: bytes
    signature: BmpSignaturePlan
    dib_header: BmpDibHeaderPlan
    header_fields: BmpHeaderFieldPlan
    boundaries: BmpBoundaryPlan
    embedded_payloads: tuple[BmpMetadataPayloadPlan, ...]
    profile: BmpProfilePlan
    optional_extra_conclusion: BmpOptionalExtraConclusion
    variant_gates: tuple[BmpVariantGate, ...]
    actions: tuple[BmpActionPlan, ...]
    output_emission_gates: tuple[BmpOutputEmissionGate, ...]
    evidence_ids: tuple[BmpEvidenceId, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"BMP header transaction output is gated: {gate_codes}")
        return self.source_data

    def embedded_binary_tags(self) -> tuple[ReadTag, ...]:
        return tuple(payload.to_read_tag() for payload in self.embedded_payloads)

    def scalar_tags(self) -> tuple[ReadTag, ...]:
        return bmp_header_scalar_tags(self)

    def profile_tags(self) -> tuple[ReadTag, ...]:
        if self.profile.payload is None:
            return ()
        if self.profile.metadata_kind == "linked_profile_name":
            value = self.profile.payload.rstrip(b"\0").decode("latin-1")
            return (
                ReadTag(
                    name="LinkedProfileName",
                    value=value,
                    provenance=TagProvenance(
                        group="File",
                        table_name="Image::ExifTool::BMP::Extra",
                        tag_id="LinkedProfileName",
                        source=f"bmp-profile:{self.profile.file_offset}:{self.profile.profile_size}",
                        family_0_group="File",
                        family_1_group="File",
                        family_2_group="Image",
                    ),
                    schema=None,
                ),
            )
        if self.profile.metadata_kind == "icc_profile":
            return bmp_icc_profile_tags(self.profile)
        return ()

    def composite_tags(self) -> tuple[ReadTag, ...]:
        return bmp_composite_tags(self)

    def read_tags(self) -> tuple[ReadTag, ...]:
        return (
            *bmp_file_type_tags(),
            *self.scalar_tags(),
            *self.composite_tags(),
            *self.profile_tags(),
            *self.embedded_binary_tags(),
        )

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "boundaries": self.boundaries.to_json(),
            "can_emit_output": self.can_emit_output,
            "dib_header": self.dib_header.to_json(),
            "embedded_payloads": json_object_array(
                payload.to_json() for payload in self.embedded_payloads
            ),
            "header_fields": self.header_fields.to_json(),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "optional_extra_conclusion": self.optional_extra_conclusion.to_json(),
            "profile": self.profile.to_json(),
            "signature": self.signature.to_json(),
            "status": self.status,
            "variant_gates": json_object_array(gate.to_json() for gate in self.variant_gates),
        }


def build_bmp_header_transaction_plan(
    bmp_data: bytes,
    *,
    allow_output_emission: bool = False,
) -> BmpHeaderTransactionPlan:
    """Build a non-mutating BMP/DIB transaction plan from in-memory BMP bytes."""

    gates: list[BmpOutputEmissionGate] = []
    signature = build_bmp_signature_plan(bmp_data)
    if signature.reason is not None:
        gates.append(
            BmpOutputEmissionGate(
                code=signature.reason,
                reason="Input does not satisfy ExifTool's BMP signature/read gate.",
                evidence_ids=signature.evidence_ids,
            )
        )
        return _unsupported_plan(bmp_data, signature, gates)

    dib_header = build_bmp_dib_header_plan(bmp_data, gates)
    if dib_header.header_size is None or not dib_header.is_exiftool_supported_size:
        _add_non_mutating_gate(gates, allow_output_emission)
        return _unsupported_plan(bmp_data, signature, gates, dib_header=dib_header)
    if dib_header.header_end_offset is None or dib_header.header_end_offset > len(bmp_data):
        gates.append(
            BmpOutputEmissionGate(
                code="truncated_dib_header",
                reason="Input ended before ExifTool could read the declared DIB header.",
                evidence_ids=(BMP_DIB_SIZE_SOURCE,),
            )
        )
        _add_non_mutating_gate(gates, allow_output_emission)
        return _unsupported_plan(bmp_data, signature, gates, dib_header=dib_header)

    header_fields = extract_bmp_header_fields(bmp_data, dib_header)
    boundaries = build_bmp_boundary_plan(bmp_data, signature, dib_header, header_fields, gates)
    embedded_payloads = discover_embedded_payloads(bmp_data, dib_header, header_fields, gates)
    profile = discover_v5_profile(bmp_data, dib_header, gates)
    optional_extra_conclusion = build_optional_extra_conclusion(
        header_fields,
        dib_header,
        embedded_payloads,
        profile,
        gates,
    )
    variant_gates = build_variant_gates(dib_header)
    actions = build_actions(dib_header, header_fields, boundaries, embedded_payloads, profile)
    _add_non_mutating_gate(gates, allow_output_emission)
    status: BmpPlanStatus = "unsupported" if structural_gate_present(gates) else "planned"
    unique_gate_tuple = unique_emission_gates(tuple(gates))
    evidence_ids = unique_evidence_ids(
        (
            *BMP_TRANSACTION_SOURCES,
            *(evidence_id for gate in unique_gate_tuple for evidence_id in gate.evidence_ids),
            *optional_extra_conclusion.evidence_ids,
            *(evidence_id for gate in variant_gates for evidence_id in gate.evidence_ids),
            *(evidence_id for action in actions for evidence_id in action.evidence_ids),
        )
    )
    return BmpHeaderTransactionPlan(
        status=status,
        source_data=bmp_data,
        signature=signature,
        dib_header=dib_header,
        header_fields=header_fields,
        boundaries=boundaries,
        embedded_payloads=embedded_payloads,
        profile=profile,
        optional_extra_conclusion=optional_extra_conclusion,
        variant_gates=variant_gates,
        actions=actions,
        output_emission_gates=unique_gate_tuple,
        evidence_ids=evidence_ids,
    )


plan_bmp_header_transaction = build_bmp_header_transaction_plan


def build_optional_extra_conclusion(
    fields: BmpHeaderFieldPlan,
    dib_header: BmpDibHeaderPlan,
    embedded_payloads: tuple[BmpMetadataPayloadPlan, ...],
    profile: BmpProfilePlan,
    gates: list[BmpOutputEmissionGate],
) -> BmpOptionalExtraConclusion:
    embedded_status = embedded_extra_status(fields, embedded_payloads, gates)
    profile_status = profile_extra_status(profile, gates)
    return BmpOptionalExtraConclusion(
        embedded_status=embedded_status,
        embedded_reason=embedded_extra_reason(fields, embedded_payloads, embedded_status),
        profile_status=profile_status,
        profile_reason=profile_extra_reason(dib_header, profile, profile_status),
        evidence_ids=(BMP_EXTRA_TABLE_SOURCE, BMP_EMBEDDED_IMAGE_SOURCE, BMP_PROFILE_SOURCE),
    )


def embedded_extra_status(
    fields: BmpHeaderFieldPlan,
    embedded_payloads: tuple[BmpMetadataPayloadPlan, ...],
    gates: list[BmpOutputEmissionGate],
) -> BmpOptionalExtraStatus:
    if embedded_payloads:
        return "planned"
    if fields.compression in {4, 5} and fields.image_length:
        if any(gate.code == "embedded_payload_exceeds_input" for gate in gates):
            return "unsupported"
    return "not_present"


def embedded_extra_reason(
    fields: BmpHeaderFieldPlan,
    embedded_payloads: tuple[BmpMetadataPayloadPlan, ...],
    status: BmpOptionalExtraStatus,
) -> str:
    if embedded_payloads:
        source_tags = ", ".join(payload.source_tag for payload in embedded_payloads)
        return (
            "BMP.pm routes compression 4/5 with non-zero BMPImageLength through "
            f"BMP::Extra; planned {source_tags}."
        )
    if status == "unsupported":
        return (
            "BMP.pm routes compression 4/5 with non-zero BMPImageLength through "
            "BMP::Extra, but the declared payload exceeds the available input."
        )
    if fields.compression in {4, 5}:
        return (
            "BMP.pm requires a non-zero BMPImageLength before emitting EmbeddedJPG or "
            "EmbeddedPNG; no embedded payload is present."
        )
    return (
        "BMP.pm emits EmbeddedJPG/EmbeddedPNG only when BMPCompression is 4 or 5; "
        f"this header has BMPCompression {fields.compression}."
    )


def profile_extra_status(
    profile: BmpProfilePlan,
    gates: list[BmpOutputEmissionGate],
) -> BmpOptionalExtraStatus:
    if profile.payload is not None:
        return "planned"
    if profile.metadata_kind is not None:
        if any(gate.code == "profile_data_exceeds_input" for gate in gates):
            return "unsupported"
    return "not_present"


def profile_extra_reason(
    dib_header: BmpDibHeaderPlan,
    profile: BmpProfilePlan,
    status: BmpOptionalExtraStatus,
) -> str:
    if profile.payload is not None:
        if profile.metadata_kind == "linked_profile_name":
            return "BMP.pm routes V5 LINK profile data to BMP::Extra LinkedProfileName."
        return "BMP.pm routes V5 MBED profile data to BMP::Extra ICC_Profile."
    if status == "unsupported":
        return "BMP.pm found V5 profile routing fields, but profile offset/size exceeds input."
    if dib_header.header_size != 124:
        return (
            "BMP.pm processes profile data only for 124-byte Windows V5 headers; "
            f"this header size is {dib_header.header_size}."
        )
    if profile.color_space not in {"LINK", "MBED"}:
        return (
            "BMP.pm routes profile data only when BMPColorSpace is LINK or MBED; "
            f"this color space is {profile.color_space}."
        )
    return "BMP.pm requires a non-zero BMPProfileOffset before emitting profile Extra tags."


def build_bmp_signature_plan(bmp_data: bytes) -> BmpSignaturePlan:
    if len(bmp_data) < BMP_EXIFTOOL_INITIAL_READ_SIZE:
        return BmpSignaturePlan(
            signature=bmp_data[:2],
            declared_file_size=None,
            pixel_data_offset=None,
            is_bmp=False,
            reason="truncated_bmp_file_header",
            evidence_ids=(BMP_SIGNATURE_SOURCE,),
        )
    signature = bmp_data[:2]
    if signature != BMP_SIGNATURE:
        return BmpSignaturePlan(
            signature=signature,
            declared_file_size=read_u32le(bmp_data, 2),
            pixel_data_offset=read_u32le(bmp_data, 10),
            is_bmp=False,
            reason="unsupported_bm_signature",
            evidence_ids=(BMP_SIGNATURE_SOURCE,),
        )
    return BmpSignaturePlan(
        signature=signature,
        declared_file_size=read_u32le(bmp_data, 2),
        pixel_data_offset=read_u32le(bmp_data, 10),
        is_bmp=True,
        reason=None,
        evidence_ids=(BMP_SIGNATURE_SOURCE,),
    )


def build_bmp_dib_header_plan(
    bmp_data: bytes,
    gates: list[BmpOutputEmissionGate],
) -> BmpDibHeaderPlan:
    header_size = read_u32le(bmp_data, BMP_FILE_HEADER_SIZE)
    is_supported = header_size in {12, 16} or (40 <= header_size < BMP_MAX_EXIFTOOL_DIB_HEADER_SIZE)
    if not is_supported:
        gates.append(
            BmpOutputEmissionGate(
                code="unsupported_dib_header_size",
                reason="DIB header size does not match ExifTool's accepted size gate.",
                evidence_ids=(BMP_DIB_SIZE_SOURCE,),
            )
        )
    family = dib_family(header_size, is_supported)
    return BmpDibHeaderPlan(
        header_size=header_size,
        family=family,
        version=dib_version(header_size, family),
        header_offset=BMP_FILE_HEADER_SIZE,
        header_end_offset=BMP_FILE_HEADER_SIZE + header_size,
        is_exiftool_supported_size=is_supported,
        evidence_ids=(BMP_DIB_SIZE_SOURCE, BMP_TABLE_ROUTING_SOURCE),
    )


def extract_bmp_header_fields(
    bmp_data: bytes,
    dib_header: BmpDibHeaderPlan,
) -> BmpHeaderFieldPlan:
    if dib_header.header_size is None:
        return empty_header_fields(())
    if dib_header.family == "os2":
        width = read_u16le(bmp_data, BMP_FILE_HEADER_SIZE + 4)
        height = read_u16le(bmp_data, BMP_FILE_HEADER_SIZE + 6)
        return BmpHeaderFieldPlan(
            image_width=width,
            image_height=height,
            raw_image_height=height,
            top_down=False,
            planes=read_u16le(bmp_data, BMP_FILE_HEADER_SIZE + 8),
            bit_depth=read_u16le(bmp_data, BMP_FILE_HEADER_SIZE + 10),
            compression=None,
            compression_route="not_available",
            image_length=None,
            pixels_per_meter_x=None,
            pixels_per_meter_y=None,
            num_colors=None,
            num_important_colors=None,
            red_mask=None,
            green_mask=None,
            blue_mask=None,
            alpha_mask=None,
            color_space=None,
            red_endpoint=None,
            green_endpoint=None,
            blue_endpoint=None,
            gamma_red=None,
            gamma_green=None,
            gamma_blue=None,
            rendering_intent=None,
            profile_data_offset=None,
            profile_size=None,
            evidence_ids=(BMP_OS2_TABLE_SOURCE,),
        )
    raw_height = read_i32le(bmp_data, BMP_FILE_HEADER_SIZE + 8)
    compression = read_u32le(bmp_data, BMP_FILE_HEADER_SIZE + 16)
    color_space = read_optional_bmp_color_space(bmp_data, dib_header, 56)
    return BmpHeaderFieldPlan(
        image_width=read_u32le(bmp_data, BMP_FILE_HEADER_SIZE + 4),
        image_height=abs(raw_height),
        raw_image_height=raw_height,
        top_down=raw_height < 0,
        planes=read_u16le(bmp_data, BMP_FILE_HEADER_SIZE + 12),
        bit_depth=read_u16le(bmp_data, BMP_FILE_HEADER_SIZE + 14),
        compression=compression,
        compression_route=compression_route(compression),
        image_length=read_u32le(bmp_data, BMP_FILE_HEADER_SIZE + 20),
        pixels_per_meter_x=read_u32le(bmp_data, BMP_FILE_HEADER_SIZE + 24),
        pixels_per_meter_y=read_u32le(bmp_data, BMP_FILE_HEADER_SIZE + 28),
        num_colors=read_u32le(bmp_data, BMP_FILE_HEADER_SIZE + 32),
        num_important_colors=read_u32le(bmp_data, BMP_FILE_HEADER_SIZE + 36),
        red_mask=read_optional_u32le(bmp_data, dib_header, 40),
        green_mask=read_optional_u32le(bmp_data, dib_header, 44),
        blue_mask=read_optional_u32le(bmp_data, dib_header, 48),
        alpha_mask=read_optional_u32le(bmp_data, dib_header, 52),
        color_space=color_space,
        red_endpoint=read_calibrated_rgb_endpoint(bmp_data, dib_header, color_space, 60),
        green_endpoint=read_calibrated_rgb_endpoint(bmp_data, dib_header, color_space, 72),
        blue_endpoint=read_calibrated_rgb_endpoint(bmp_data, dib_header, color_space, 84),
        gamma_red=read_calibrated_rgb_u32le(bmp_data, dib_header, color_space, 96),
        gamma_green=read_calibrated_rgb_u32le(bmp_data, dib_header, color_space, 100),
        gamma_blue=read_calibrated_rgb_u32le(bmp_data, dib_header, color_space, 104),
        rendering_intent=read_optional_u32le(bmp_data, dib_header, 108),
        profile_data_offset=read_optional_u32le(bmp_data, dib_header, 112),
        profile_size=read_optional_u32le(bmp_data, dib_header, 116),
        evidence_ids=(BMP_MAIN_TABLE_SOURCE, BMP_WINDOWS_EXTENDED_SOURCE),
    )


def build_bmp_boundary_plan(
    bmp_data: bytes,
    signature: BmpSignaturePlan,
    dib_header: BmpDibHeaderPlan,
    fields: BmpHeaderFieldPlan,
    gates: list[BmpOutputEmissionGate],
) -> BmpBoundaryPlan:
    dib_range: tuple[int, int] | None = None
    color_range: tuple[int, int] | None = None
    pixel_range: tuple[int, int] | None = None
    trailing_range: tuple[int, int] | None = None
    dib_end = dib_header.header_end_offset
    pixel_offset = signature.pixel_data_offset
    entry_size = color_table_entry_size(dib_header)
    entry_count = color_table_entry_count(dib_header, fields)
    expected_size = None if entry_size is None or entry_count is None else entry_size * entry_count
    if dib_end is not None:
        dib_range = (BMP_FILE_HEADER_SIZE, min(dib_end, len(bmp_data)))
    if signature.declared_file_size is not None and signature.declared_file_size > len(bmp_data):
        gates.append(
            BmpOutputEmissionGate(
                code="declared_file_size_exceeds_input",
                reason="BMP file-size field points beyond the available input.",
                evidence_ids=(BMP_SIGNATURE_SOURCE,),
            )
        )
    if dib_end is not None and pixel_offset is not None:
        if pixel_offset < dib_end:
            gates.append(
                BmpOutputEmissionGate(
                    code="pixel_data_offset_before_dib_header_end",
                    reason="BMP pixel-data offset points inside the DIB header.",
                    evidence_ids=(BMP_SIGNATURE_SOURCE, BMP_DIB_SIZE_SOURCE),
                )
            )
        elif pixel_offset > len(bmp_data):
            gates.append(
                BmpOutputEmissionGate(
                    code="pixel_data_offset_exceeds_input",
                    reason="BMP pixel-data offset points beyond the available input.",
                    evidence_ids=(BMP_SIGNATURE_SOURCE,),
                )
            )
        else:
            color_range = (dib_end, pixel_offset) if pixel_offset > dib_end else None
            pixel_end = min(signature.declared_file_size or len(bmp_data), len(bmp_data))
            pixel_range = (pixel_offset, pixel_end)
            trailing_range = (pixel_end, len(bmp_data)) if pixel_end < len(bmp_data) else None
    return BmpBoundaryPlan(
        file_header_range=(0, min(BMP_FILE_HEADER_SIZE, len(bmp_data))),
        dib_header_range=dib_range,
        color_table_range=color_range,
        color_table_entry_size=entry_size,
        color_table_entry_count=entry_count,
        expected_color_table_size=expected_size,
        pixel_data_range=pixel_range,
        trailing_data_range=trailing_range,
        evidence_ids=(BMP_SIGNATURE_SOURCE, BMP_DIB_SIZE_SOURCE),
    )


def discover_embedded_payloads(
    bmp_data: bytes,
    dib_header: BmpDibHeaderPlan,
    fields: BmpHeaderFieldPlan,
    gates: list[BmpOutputEmissionGate],
) -> tuple[BmpMetadataPayloadPlan, ...]:
    if fields.compression not in {4, 5} or fields.image_length is None:
        return ()
    if fields.image_length == 0:
        return ()
    if dib_header.header_end_offset is None:
        return ()
    file_offset = dib_header.header_end_offset
    size = fields.image_length
    end_offset = file_offset + size
    if end_offset > len(bmp_data):
        gates.append(
            BmpOutputEmissionGate(
                code="embedded_payload_exceeds_input",
                reason="Embedded JPEG/PNG payload length points beyond available input.",
                evidence_ids=(BMP_EMBEDDED_IMAGE_SOURCE,),
            )
        )
        return ()
    metadata_kind: BmpEmbeddedMetadataKind = (
        "embedded_jpg" if fields.compression == 4 else "embedded_png"
    )
    return (
        BmpMetadataPayloadPlan(
            metadata_kind=metadata_kind,
            file_offset=file_offset,
            size=size,
            payload=bmp_data[file_offset:end_offset],
            evidence_ids=(BMP_EXTRA_TABLE_SOURCE, BMP_EMBEDDED_IMAGE_SOURCE),
        ),
    )


def discover_v5_profile(
    bmp_data: bytes,
    dib_header: BmpDibHeaderPlan,
    gates: list[BmpOutputEmissionGate],
) -> BmpProfilePlan:
    if dib_header.header_size != 124:
        return empty_profile_plan()
    color_space = read_bmp_color_space(bmp_data, BMP_FILE_HEADER_SIZE + 56)
    if color_space not in {"LINK", "MBED"}:
        return BmpProfilePlan(
            color_space=color_space,
            profile_data_offset=None,
            profile_size=None,
            file_offset=None,
            metadata_kind=None,
            payload=None,
            evidence_ids=(BMP_WINDOWS_EXTENDED_SOURCE, BMP_PROFILE_SOURCE),
        )
    profile_data_offset = read_u32le(bmp_data, BMP_FILE_HEADER_SIZE + 112)
    if profile_data_offset == 0:
        return BmpProfilePlan(
            color_space=color_space,
            profile_data_offset=profile_data_offset,
            profile_size=read_u32le(bmp_data, BMP_FILE_HEADER_SIZE + 116),
            file_offset=None,
            metadata_kind=None,
            payload=None,
            evidence_ids=(
                BMP_WINDOWS_EXTENDED_SOURCE,
                BMP_EXTRA_TABLE_SOURCE,
                BMP_PROFILE_SOURCE,
            ),
        )
    profile_size = read_u32le(bmp_data, BMP_FILE_HEADER_SIZE + 116)
    file_offset = BMP_FILE_HEADER_SIZE + profile_data_offset
    end_offset = file_offset + profile_size
    if end_offset > len(bmp_data):
        gates.append(
            BmpOutputEmissionGate(
                code="profile_data_exceeds_input",
                reason="V5 profile offset/size points beyond available input.",
                evidence_ids=(BMP_PROFILE_SOURCE,),
            )
        )
        payload = None
    else:
        payload = bmp_data[file_offset:end_offset]
    metadata_kind: BmpMetadataKind = (
        "linked_profile_name" if color_space == "LINK" else "icc_profile"
    )
    return BmpProfilePlan(
        color_space=color_space,
        profile_data_offset=profile_data_offset,
        profile_size=profile_size,
        file_offset=file_offset,
        metadata_kind=metadata_kind,
        payload=payload,
        evidence_ids=(BMP_WINDOWS_EXTENDED_SOURCE, BMP_EXTRA_TABLE_SOURCE, BMP_PROFILE_SOURCE),
    )


def build_variant_gates(dib_header: BmpDibHeaderPlan) -> tuple[BmpVariantGate, ...]:
    if dib_header.family == "os2":
        return (
            BmpVariantGate(
                code="os2_header_routed_preserve_only",
                reason="ExifTool routes this DIB size to the OS/2 table; preserve-only.",
                evidence_ids=(BMP_OS2_TABLE_SOURCE, BMP_TABLE_ROUTING_SOURCE),
            ),
        )
    if dib_header.version == "avi_bmp_structure":
        return (
            BmpVariantGate(
                code="avi_bmp_header_tail_ignored",
                reason="ExifTool treats the 68-byte AVI BMP structure tail as invalid.",
                evidence_ids=(BMP_MAIN_TABLE_SOURCE,),
            ),
        )
    if dib_header.version == "windows_extended":
        return (
            BmpVariantGate(
                code="unknown_windows_header_preserve_only",
                reason="ExifTool accepts this Windows DIB size but has no named version.",
                evidence_ids=(BMP_DIB_SIZE_SOURCE, BMP_TABLE_ROUTING_SOURCE),
            ),
        )
    return ()


def build_actions(
    dib_header: BmpDibHeaderPlan,
    fields: BmpHeaderFieldPlan,
    boundaries: BmpBoundaryPlan,
    embedded_payloads: tuple[BmpMetadataPayloadPlan, ...],
    profile: BmpProfilePlan,
) -> tuple[BmpActionPlan, ...]:
    actions = [
        BmpActionPlan(
            kind="validate_signature",
            target="BM",
            byte_range=(0, 2),
            reason="Validate the BM signature before DIB parsing.",
            evidence_ids=(BMP_SIGNATURE_SOURCE,),
        ),
        BmpActionPlan(
            kind="route_dib_header",
            target=dib_header.version,
            byte_range=boundaries.dib_header_range,
            reason="Route the DIB header to the ExifTool OS/2 or Windows table.",
            evidence_ids=(BMP_TABLE_ROUTING_SOURCE,),
        ),
        BmpActionPlan(
            kind="extract_image_header_fields",
            target=fields.compression_route,
            byte_range=boundaries.dib_header_range,
            reason="Extract width, height, bit depth, compression, and related header fields.",
            evidence_ids=fields.evidence_ids,
        ),
        BmpActionPlan(
            kind="preserve_file_header",
            target="bmp_file_header",
            byte_range=boundaries.file_header_range,
            reason="Preserve the 14-byte BMP file header.",
            evidence_ids=(BMP_SIGNATURE_SOURCE,),
        ),
        BmpActionPlan(
            kind="preserve_dib_header",
            target="dib_header",
            byte_range=boundaries.dib_header_range,
            reason="Preserve the routed DIB header bytes.",
            evidence_ids=(BMP_DIB_SIZE_SOURCE, BMP_TABLE_ROUTING_SOURCE),
        ),
    ]
    if boundaries.color_table_range is not None:
        actions.append(
            BmpActionPlan(
                kind="preserve_color_table",
                target="color_table",
                byte_range=boundaries.color_table_range,
                reason="Preserve palette bytes between the DIB header and pixel data.",
                evidence_ids=(BMP_MAIN_TABLE_SOURCE, BMP_OS2_TABLE_SOURCE),
            )
        )
    if boundaries.pixel_data_range is not None:
        actions.append(
            BmpActionPlan(
                kind="preserve_pixel_data",
                target="pixel_data",
                byte_range=boundaries.pixel_data_range,
                reason="Preserve pixel data at the BMP file-header offset.",
                evidence_ids=(BMP_SIGNATURE_SOURCE,),
            )
        )
    for payload in embedded_payloads:
        actions.append(
            BmpActionPlan(
                kind="preserve_embedded_payload",
                target=payload.metadata_kind,
                byte_range=(payload.file_offset, payload.file_offset + payload.size),
                reason="Preserve ExifTool-modeled embedded JPEG/PNG payload bytes.",
                evidence_ids=payload.evidence_ids,
            )
        )
    if profile.metadata_kind is not None and profile.file_offset is not None:
        actions.append(
            BmpActionPlan(
                kind="preserve_profile_payload",
                target=profile.metadata_kind,
                byte_range=(profile.file_offset, profile.file_offset + (profile.profile_size or 0)),
                reason="Preserve ExifTool-modeled V5 profile payload bytes.",
                evidence_ids=profile.evidence_ids,
            )
        )
    return tuple(actions)


def _unsupported_plan(
    bmp_data: bytes,
    signature: BmpSignaturePlan,
    gates: list[BmpOutputEmissionGate],
    *,
    dib_header: BmpDibHeaderPlan | None = None,
) -> BmpHeaderTransactionPlan:
    header = dib_header or BmpDibHeaderPlan(
        header_size=None,
        family="unsupported",
        version="unsupported",
        header_offset=BMP_FILE_HEADER_SIZE,
        header_end_offset=None,
        is_exiftool_supported_size=False,
        evidence_ids=(BMP_DIB_SIZE_SOURCE,),
    )
    evidence_id_tuple = unique_evidence_ids(
        (*BMP_TRANSACTION_SOURCES, *(evidence_id for g in gates for evidence_id in g.evidence_ids))
    )
    return BmpHeaderTransactionPlan(
        status="unsupported",
        source_data=bmp_data,
        signature=signature,
        dib_header=header,
        header_fields=empty_header_fields(()),
        boundaries=BmpBoundaryPlan(
            file_header_range=(0, min(BMP_FILE_HEADER_SIZE, len(bmp_data))),
            dib_header_range=None,
            color_table_range=None,
            color_table_entry_size=None,
            color_table_entry_count=None,
            expected_color_table_size=None,
            pixel_data_range=None,
            trailing_data_range=None,
            evidence_ids=(BMP_SIGNATURE_SOURCE, BMP_DIB_SIZE_SOURCE),
        ),
        embedded_payloads=(),
        profile=empty_profile_plan(),
        optional_extra_conclusion=unsupported_optional_extra_conclusion(),
        variant_gates=(),
        actions=(),
        output_emission_gates=unique_emission_gates(tuple(gates)),
        evidence_ids=evidence_id_tuple,
    )


def unsupported_optional_extra_conclusion() -> BmpOptionalExtraConclusion:
    return BmpOptionalExtraConclusion(
        embedded_status="unsupported",
        embedded_reason=(
            "Input did not pass BMP.pm header gates, so BMP::Extra routing was not attempted."
        ),
        profile_status="unsupported",
        profile_reason=(
            "Input did not pass BMP.pm header gates, so V5 profile routing was not attempted."
        ),
        evidence_ids=(BMP_EXTRA_TABLE_SOURCE, BMP_EMBEDDED_IMAGE_SOURCE, BMP_PROFILE_SOURCE),
    )


def empty_header_fields(
    evidence_ids: tuple[BmpEvidenceId, ...],
) -> BmpHeaderFieldPlan:
    return BmpHeaderFieldPlan(
        image_width=None,
        image_height=None,
        raw_image_height=None,
        top_down=None,
        planes=None,
        bit_depth=None,
        compression=None,
        compression_route="not_available",
        image_length=None,
        pixels_per_meter_x=None,
        pixels_per_meter_y=None,
        num_colors=None,
        num_important_colors=None,
        red_mask=None,
        green_mask=None,
        blue_mask=None,
        alpha_mask=None,
        color_space=None,
        red_endpoint=None,
        green_endpoint=None,
        blue_endpoint=None,
        gamma_red=None,
        gamma_green=None,
        gamma_blue=None,
        rendering_intent=None,
        profile_data_offset=None,
        profile_size=None,
        evidence_ids=evidence_ids,
    )


def empty_profile_plan() -> BmpProfilePlan:
    return BmpProfilePlan(
        color_space=None,
        profile_data_offset=None,
        profile_size=None,
        file_offset=None,
        metadata_kind=None,
        payload=None,
        evidence_ids=(BMP_PROFILE_SOURCE,),
    )


def dib_family(header_size: int, is_supported: bool) -> BmpDibFamily:
    if not is_supported:
        return "unsupported"
    if header_size in {12, 16, 64}:
        return "os2"
    return "windows"


def dib_version(header_size: int, family: BmpDibFamily) -> BmpDibVersion:
    if family == "unsupported":
        return "unsupported"
    if family == "os2":
        if header_size == 12:
            return "os2_v1"
        if header_size == 16:
            return "os2_v2_short"
        return "os2_v2"
    if header_size == 40:
        return "windows_v3"
    if header_size == 68:
        return "avi_bmp_structure"
    if header_size == 108:
        return "windows_v4"
    if header_size == 124:
        return "windows_v5"
    return "windows_extended"


def compression_route(compression: int) -> BmpCompressionRoute:
    if compression == 0:
        return "none"
    if compression == 1:
        return "rle8"
    if compression == 2:
        return "rle4"
    if compression == 3:
        return "bitfields"
    if compression == 4:
        return "jpeg"
    if compression == 5:
        return "png"
    if compression > 256:
        return "avi_codec"
    return "unknown"


def bmp_header_scalar_tags(plan: BmpHeaderTransactionPlan) -> tuple[ReadTag, ...]:
    if plan.status != "planned":
        return ()
    fields = plan.header_fields
    table_name = (
        "Image::ExifTool::BMP::OS2"
        if plan.dib_header.family == "os2"
        else "Image::ExifTool::BMP::Main"
    )
    rows: list[tuple[str, str, BmpScalarValue | None]] = [
        ("BMPVersion", "0", rendered_bmp_version(plan.dib_header.header_size)),
        ("ImageWidth", "4", fields.image_width),
        ("ImageHeight", "8" if plan.dib_header.family == "windows" else "6", fields.image_height),
        ("Planes", "12" if plan.dib_header.family == "windows" else "8", fields.planes),
        ("BitDepth", "14" if plan.dib_header.family == "windows" else "10", fields.bit_depth),
    ]
    if plan.dib_header.family == "windows":
        rows.extend(
            (
                ("Compression", "16", rendered_bmp_compression(fields.compression)),
                ("ImageLength", "20", fields.image_length),
                ("PixelsPerMeterX", "24", fields.pixels_per_meter_x),
                ("PixelsPerMeterY", "28", fields.pixels_per_meter_y),
                ("NumColors", "32", rendered_num_colors(fields.num_colors)),
                (
                    "NumImportantColors",
                    "36",
                    rendered_num_important_colors(fields.num_important_colors),
                ),
            )
        )
        rows.extend(
            (
                ("RedMask", "40", rendered_bmp_mask(fields.red_mask)),
                ("GreenMask", "44", rendered_bmp_mask(fields.green_mask)),
                ("BlueMask", "48", rendered_bmp_mask(fields.blue_mask)),
                ("AlphaMask", "52", rendered_bmp_mask(fields.alpha_mask)),
            )
        )
        if fields.color_space is not None:
            rows.append(("ColorSpace", "56", rendered_bmp_color_space(fields.color_space)))
        if fields.color_space == "0":
            rows.extend(
                (
                    ("RedEndpoint", "60", rendered_bmp_endpoint(fields.red_endpoint)),
                    ("GreenEndpoint", "72", rendered_bmp_endpoint(fields.green_endpoint)),
                    ("BlueEndpoint", "84", rendered_bmp_endpoint(fields.blue_endpoint)),
                    ("GammaRed", "96", rendered_fixed_32u(fields.gamma_red)),
                    ("GammaGreen", "100", rendered_fixed_32u(fields.gamma_green)),
                    ("GammaBlue", "104", rendered_fixed_32u(fields.gamma_blue)),
                )
            )
        rows.append(
            ("RenderingIntent", "108", rendered_bmp_rendering_intent(fields.rendering_intent))
        )
        if fields.color_space in {"LINK", "MBED"}:
            rows.extend(
                (
                    ("ProfileDataOffset", "112", fields.profile_data_offset),
                    ("ProfileSize", "116", fields.profile_size),
                )
            )
    tags: list[ReadTag] = []
    for name, tag_id, value in rows:
        if value is None:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=value,
                provenance=TagProvenance(
                    group="File",
                    table_name=table_name,
                    tag_id=tag_id,
                    source=f"bmp-dib:{plan.dib_header.header_offset + int(tag_id)}",
                    family_0_group="File",
                    family_1_group="File",
                    family_2_group="Image",
                ),
                schema=None,
            )
        )
    return tuple(tags)


def bmp_file_type_tags() -> tuple[ReadTag, ...]:
    return (
        bmp_file_type_tag("FileType", "BMP"),
        bmp_file_type_tag("FileTypeExtension", "bmp"),
        bmp_file_type_tag("MIMEType", "image/bmp"),
    )


def bmp_file_type_tag(name: str, value: str) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="File",
            table_name="Image::ExifTool::File",
            tag_id=name,
            source=f"bmp-file-type:{name}",
            family_0_group="File",
            family_1_group="File",
            family_2_group="Other",
        ),
        schema=None,
    )


def bmp_composite_tags(plan: BmpHeaderTransactionPlan) -> tuple[ReadTag, ...]:
    if plan.status != "planned":
        return ()
    width = plan.header_fields.image_width
    height = plan.header_fields.image_height
    if width is None or height is None:
        return ()
    megapixels = round_bmp_megapixels(width * height / 1_000_000)
    return (
        ReadTag(
            name="ImageSize",
            value=f"{width}x{height}",
            provenance=bmp_composite_provenance("ImageSize", "Exif-ImageSize"),
            schema=None,
        ),
        ReadTag(
            name="Megapixels",
            value=megapixels,
            provenance=bmp_composite_provenance("Megapixels", "Exif-Megapixels"),
            schema=None,
        ),
    )


def bmp_composite_provenance(name: str, tag_id: str) -> TagProvenance:
    return TagProvenance(
        group="Composite",
        table_name="Image::ExifTool::Composite",
        tag_id=tag_id,
        source=f"bmp-composite:{name}:ImageWidth:ImageHeight",
        family_0_group="Composite",
        family_1_group="Composite",
        family_2_group="Image",
    )


def round_bmp_megapixels(value: float) -> float:
    if value >= 1:
        return round(value, 1)
    if value >= 0.001:
        return round(value, 3)
    return round(value, 6)


def bmp_icc_profile_tags(profile: BmpProfilePlan) -> tuple[ReadTag, ...]:
    if profile.payload is None:
        return ()
    try:
        values = {
            **parse_icc_header_tags(profile.payload, strict_declared_length=True),
            **parse_icc_profile_tags(profile.payload, strict_declared_length=True),
        }
    except ValueError:
        return ()
    tags: list[ReadTag] = []
    for name, json_value in values.items():
        value = bmp_read_scalar_value(json_value)
        if value is None:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=value,
                provenance=TagProvenance(
                    group="ICC_Profile",
                    table_name=bmp_icc_table_name(name),
                    tag_id=name,
                    source=f"bmp-profile:{profile.file_offset}:{profile.profile_size}:{name}",
                    family_0_group="ICC_Profile",
                    family_1_group="ICC_Profile",
                    family_2_group="Image",
                ),
                schema=None,
            )
        )
    return tuple(tags)


def bmp_read_scalar_value(value: JsonValue) -> BmpReadScalarValue | None:
    if isinstance(value, str | int | float | bool):
        return value
    return None


def bmp_icc_table_name(name: str) -> str:
    if name in {
        "ProfileCopyright",
        "ProfileDescription",
        "MediaWhitePoint",
        "MediaBlackPoint",
        "RedTRC",
        "GreenTRC",
        "BlueTRC",
        "RedMatrixColumn",
        "GreenMatrixColumn",
        "BlueMatrixColumn",
    }:
        return "Image::ExifTool::ICC_Profile::Main"
    return "Image::ExifTool::ICC_Profile::Header"


def rendered_bmp_version(header_size: int | None) -> str | int | None:
    if header_size is None:
        return None
    versions = {
        12: "OS/2 V1",
        40: "Windows V3",
        64: "OS/2 V2",
        68: "AVI BMP structure?",
        108: "Windows V4",
        124: "Windows V5",
    }
    return versions.get(header_size, header_size)


def rendered_bmp_compression(compression: int | None) -> str | int | None:
    if compression is None:
        return None
    conversions = {
        0: "None",
        1: "8-Bit RLE",
        2: "4-Bit RLE",
        3: "Bitfields",
        4: "JPEG",
        5: "PNG",
    }
    if compression in conversions:
        return conversions[compression]
    if compression > 256:
        return rendered_bmp_fourcc(compression)
    return compression


def rendered_bmp_fourcc(compression: int) -> str:
    raw = compression.to_bytes(4, "little").rstrip(b" \0")
    rendered = ""
    for value in raw:
        if value <= 0x1F or value >= 0x7F:
            rendered += f"\\x{value:02x}"
        else:
            rendered += chr(value)
    return rendered


def rendered_num_colors(num_colors: int | None) -> str | int | None:
    if num_colors is None:
        return None
    return num_colors or "Use BitDepth"


def rendered_num_important_colors(num_important_colors: int | None) -> str | int | None:
    if num_important_colors is None:
        return None
    return num_important_colors or "All"


def rendered_bmp_color_space(color_space: str | None) -> str | int | None:
    if color_space is None:
        return None
    conversions = {
        "0": "Calibrated RGB",
        "1": "Device RGB",
        "2": "Device CMYK",
        "LINK": "Linked Color Profile",
        "MBED": "Embedded Color Profile",
        "sRGB": "sRGB",
        "Win ": "Windows Color Space",
    }
    if color_space in conversions:
        return conversions[color_space]
    if color_space.isdecimal():
        return int(color_space)
    return color_space


def rendered_bmp_mask(mask: int | None) -> str | None:
    if mask is None:
        return None
    return f"0x{mask:08x}"


def rendered_bmp_endpoint(endpoint: BmpEndpointValue | None) -> str | None:
    if endpoint is None:
        return None
    return " ".join(rendered_fixed_2_30(value) for value in endpoint)


def rendered_fixed_2_30(value: int) -> str:
    return f"{value / 0x40000000:.6f}"


def rendered_fixed_32u(value: int | None) -> float | None:
    if value is None:
        return None
    return int((value / 0x10000) * 1e5 + 0.5) / 1e5


def rendered_bmp_rendering_intent(rendering_intent: int | None) -> str | int | None:
    if rendering_intent is None:
        return None
    conversions = {
        1: "Graphic (LCS_GM_BUSINESS)",
        2: "Proof (LCS_GM_GRAPHICS)",
        4: "Picture (LCS_GM_IMAGES)",
        8: "Absolute Colorimetric (LCS_GM_ABS_COLORIMETRIC)",
    }
    return conversions.get(rendering_intent, rendering_intent)


def color_table_entry_size(dib_header: BmpDibHeaderPlan) -> int | None:
    if dib_header.family == "os2":
        return 3
    if dib_header.family == "windows":
        return 4
    return None


def color_table_entry_count(
    dib_header: BmpDibHeaderPlan,
    fields: BmpHeaderFieldPlan,
) -> int | None:
    if fields.bit_depth is None:
        return None
    if dib_header.family == "windows" and fields.num_colors:
        return fields.num_colors
    if fields.bit_depth <= 8:
        return 1 << fields.bit_depth
    return 0


def read_bmp_color_space(data: bytes, offset: int) -> str:
    raw = data[offset : offset + 4]
    if len(raw) < 4:
        return ""
    if b"\0" in raw:
        return str(int.from_bytes(raw, "little"))
    return int.from_bytes(raw, "little").to_bytes(4, "big").decode("latin-1")


def read_optional_bmp_color_space(
    data: bytes,
    dib_header: BmpDibHeaderPlan,
    field_offset: int,
) -> str | None:
    if not bmp_extended_field_available(dib_header, field_offset, 4):
        return None
    return read_bmp_color_space(data, BMP_FILE_HEADER_SIZE + field_offset)


def read_optional_u32le(
    data: bytes,
    dib_header: BmpDibHeaderPlan,
    field_offset: int,
) -> int | None:
    if not bmp_extended_field_available(dib_header, field_offset, 4):
        return None
    return read_u32le(data, BMP_FILE_HEADER_SIZE + field_offset)


def read_calibrated_rgb_endpoint(
    data: bytes,
    dib_header: BmpDibHeaderPlan,
    color_space: str | None,
    field_offset: int,
) -> BmpEndpointValue | None:
    if color_space != "0" or not bmp_extended_field_available(dib_header, field_offset, 12):
        return None
    offset = BMP_FILE_HEADER_SIZE + field_offset
    return (
        read_u32le(data, offset),
        read_u32le(data, offset + 4),
        read_u32le(data, offset + 8),
    )


def read_calibrated_rgb_u32le(
    data: bytes,
    dib_header: BmpDibHeaderPlan,
    color_space: str | None,
    field_offset: int,
) -> int | None:
    if color_space != "0":
        return None
    return read_optional_u32le(data, dib_header, field_offset)


def bmp_extended_field_available(
    dib_header: BmpDibHeaderPlan,
    field_offset: int,
    size: int,
) -> bool:
    if dib_header.header_size is None or dib_header.version == "avi_bmp_structure":
        return False
    return dib_header.header_size >= field_offset + size


def bmp_icc_profile_diagnostic(profile: BmpProfilePlan) -> str | None:
    if profile.metadata_kind != "icc_profile" or profile.payload is None:
        return None
    return validate_icc_profile(profile.payload, strict_declared_length=True)


def _add_non_mutating_gate(
    gates: list[BmpOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        BmpOutputEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="BMP header transaction plans are non-mutating unless emission is allowed.",
            evidence_ids=(BMP_SIGNATURE_SOURCE,),
        )
    )


def structural_gate_present(gates: list[BmpOutputEmissionGate]) -> bool:
    return any(gate.code != "non_mutating_plan_requires_explicit_emission" for gate in gates)


def read_u16le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def read_u32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def read_i32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little", signed=True)


def json_range(value: tuple[int, int] | None) -> JsonArray | None:
    return None if value is None else [value[0], value[1]]


def json_int_tuple(value: BmpEndpointValue | None) -> JsonArray | None:
    return None if value is None else [value[0], value[1], value[2]]


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return list(values)


def evidence_anchors_to_json(evidence_ids: tuple[BmpEvidenceId, ...]) -> JsonArray:
    return [
        {
            "evidence": BMP_EVIDENCE_ANCHORS[evidence_id].evidence,
            "evidence_id": evidence_id,
            "line_end": BMP_EVIDENCE_ANCHORS[evidence_id].line_end,
            "line_start": BMP_EVIDENCE_ANCHORS[evidence_id].line_start,
            "path": BMP_EVIDENCE_ANCHORS[evidence_id].path,
            "symbol": BMP_EVIDENCE_ANCHORS[evidence_id].symbol,
        }
        for evidence_id in evidence_ids
    ]


def unique_evidence_ids(evidence_ids: Iterable[BmpEvidenceId]) -> tuple[BmpEvidenceId, ...]:
    unique: list[BmpEvidenceId] = []
    seen: set[BmpEvidenceId] = set()
    for evidence_id in evidence_ids:
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        unique.append(evidence_id)
    return tuple(unique)


def unique_emission_gates(
    gates: tuple[BmpOutputEmissionGate, ...],
) -> tuple[BmpOutputEmissionGate, ...]:
    unique: list[BmpOutputEmissionGate] = []
    seen: set[BmpEmissionGateCode] = set()
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
