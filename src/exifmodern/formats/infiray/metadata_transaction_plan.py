"""Source-grounded, preserve-only InfiRay IJPEG metadata transaction plans.

ExifTool's InfiRay module defines fixed binary tables for IJPEG APP2 and
APP4-APP7 sections. This planner mirrors those table-routing and boundary
responsibilities for JPEG bytes without adding a writer.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject, JsonValue

INFIRAY_PM_SOURCE_PATH = "lib/Image/ExifTool/InfiRay.pm"
JPEG_SOI = b"\xff\xd8"
JPEG_MARKER_PREFIX = 0xFF
JPEG_EOI = 0xD9
JPEG_SOS = 0xDA
APP2_MARKER = 0xE2
APP4_MARKER = 0xE4
APP5_MARKER = 0xE5
APP6_MARKER = 0xE6
APP7_MARKER = 0xE7
APP_MIN_MARKER = 0xE0
APP_MAX_MARKER = 0xEF
IJPEG_SIGNATURE_OFFSET = 0x04
IJPEG_SIGNATURE = b"IJPEG\0"

APP2_VERSION_MIN_LENGTH = 0x4F
APP4_FACTORY_MIN_LENGTH = 0x68
APP5_PICTURE_MIN_LENGTH = 0x26
APP6_MIX_MODE_MIN_LENGTH = 0x81
APP7_OP_MODE_MIN_LENGTH = 0x0F

type InfiRayPlanStatus = Literal["planned", "unsupported"]
type InfiRaySectionTable = Literal[
    "Version",
    "Factory",
    "Picture",
    "MixMode",
    "OpMode",
    "Unknown",
]
type InfiRaySectionRole = Literal[
    "version_header",
    "factory_temperature_defaults",
    "picture_temperature_metadata",
    "visual_infrared_mix_mode",
    "camera_operation_mode",
    "unknown_section",
]
type InfiRayRewriteOperation = Literal["insert", "replace", "delete"]
type InfiRayRewriteTarget = Literal[
    "app2_version",
    "app4_factory",
    "app5_picture",
    "app6_mix_mode",
    "app7_op_mode",
    "unknown_section",
    "jpeg_payload",
]
type InfiRayActionKind = Literal[
    "validate_jpeg_container",
    "route_app2_version_header",
    "route_app4_factory_table",
    "route_app5_picture_table",
    "route_app6_mix_mode_table",
    "route_app7_op_mode_table",
    "preserve_unknown_app_section",
    "preserve_jpeg_payload",
    "block_requested_rewrite",
    "no_metadata_mutation",
]
type InfiRayEmissionGateCode = Literal[
    "missing_jpeg_soi",
    "truncated_jpeg_marker",
    "invalid_jpeg_segment_length",
    "truncated_jpeg_segment",
    "unsupported_app2_version_header",
    "truncated_infiray_app2_version_header",
    "truncated_infiray_app4_factory",
    "truncated_infiray_app5_picture",
    "truncated_infiray_app6_mix_mode",
    "truncated_infiray_app7_op_mode",
    "rewrite_requested_requires_infiray_writer",
    "non_mutating_plan_requires_explicit_emission",
]
type InfiRayResponsibilityConcern = Literal[
    "app2_version_header_routing",
    "app4_factory_table_routing",
    "app5_picture_temperature_distance_emissivity_humidity",
    "app6_mix_mode_routing",
    "app7_operation_mode_routing",
    "thermal_visible_temp_image_size_boundaries",
    "payload_preservation",
    "unknown_section_preservation",
    "malformed_truncation_blockers",
    "unsupported_rewrite_gates",
]
type InfiRayImageKind = Literal["thermal", "temperature", "visible"]

INFIRAY_DESCRIPTION_SOURCE = "infiray.description"
INFIRAY_VERSION_SOURCE = "infiray.version"
INFIRAY_FACTORY_SOURCE = "infiray.factory"
INFIRAY_PICTURE_SOURCE = "infiray.picture"
INFIRAY_MIX_MODE_SOURCE = "infiray.mix.mode"
INFIRAY_OP_MODE_SOURCE = "infiray.op.mode"
INFIRAY_UNSCOPED_APP_SOURCE = "infiray.unscoped.app"
INFIRAY_ISOTHERMAL_SOURCE = "infiray.isothermal"
INFIRAY_SENSOR_SOURCE = "infiray.sensor"
INFIRAY_READ_ONLY_SOURCE = "infiray.read.only"

INFIRAY_TRANSACTION_SOURCES = (
    INFIRAY_DESCRIPTION_SOURCE,
    INFIRAY_VERSION_SOURCE,
    INFIRAY_FACTORY_SOURCE,
    INFIRAY_PICTURE_SOURCE,
    INFIRAY_MIX_MODE_SOURCE,
    INFIRAY_OP_MODE_SOURCE,
    INFIRAY_UNSCOPED_APP_SOURCE,
    INFIRAY_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class InfiRayMetadataRewriteRequest:
    target: InfiRayRewriteTarget
    operation: InfiRayRewriteOperation
    payload: bytes | None = None


@dataclass(frozen=True)
class InfiRayByteRange:
    start: int
    end: int
    reason: str

    def to_json(self) -> JsonObject:
        return {"end": self.end, "reason": self.reason, "start": self.start}


@dataclass(frozen=True)
class InfiRayImageBoundaryPlan:
    image_kind: InfiRayImageKind
    data_size: int
    data_format: int
    width: int
    height: int
    bits_per_pixel: int
    evidence_ids: tuple[str, ...]

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    def to_json(self) -> JsonObject:
        return {
            "bits_per_pixel": self.bits_per_pixel,
            "data_format": self.data_format,
            "data_size": self.data_size,
            "height": self.height,
            "image_kind": self.image_kind,
            "pixel_count": self.pixel_count,
            "width": self.width,
        }


@dataclass(frozen=True)
class InfiRayImageBoundariesPlan:
    thermal: InfiRayImageBoundaryPlan | None
    temperature: InfiRayImageBoundaryPlan | None
    visible: InfiRayImageBoundaryPlan | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "temperature": self.temperature.to_json() if self.temperature is not None else None,
            "thermal": self.thermal.to_json() if self.thermal is not None else None,
            "visible": self.visible.to_json() if self.visible is not None else None,
        }


@dataclass(frozen=True)
class InfiRaySectionPlan:
    section_index: int
    marker: int
    marker_name: str
    table: InfiRaySectionTable
    role: InfiRaySectionRole
    segment_range: InfiRayByteRange
    payload_range: InfiRayByteRange
    payload: bytes
    preserved: bool
    parsed_tags: JsonObject
    image_boundaries: InfiRayImageBoundariesPlan | None
    evidence_ids: tuple[str, ...]

    @property
    def payload_length(self) -> int:
        return self.payload_range.end - self.payload_range.start

    def to_json(self) -> JsonObject:
        image_boundaries = (
            self.image_boundaries.to_json() if self.image_boundaries is not None else None
        )
        return {
            "image_boundaries": image_boundaries,
            "marker": self.marker,
            "marker_name": self.marker_name,
            "parsed_tags": self.parsed_tags,
            "payload_length": self.payload_length,
            "payload_range": self.payload_range.to_json(),
            "payload_sample_hex": self.payload[:32].hex(),
            "preserved": self.preserved,
            "role": self.role,
            "section_index": self.section_index,
            "segment_range": self.segment_range.to_json(),
            "table": self.table,
        }


@dataclass(frozen=True)
class InfiRayResponsibilityPlan:
    concern: InfiRayResponsibilityConcern
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class InfiRayActionPlan:
    kind: InfiRayActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": json_tuple(self.byte_range),
            "kind": self.kind,
            "reason": self.reason,
            "target": self.target,
        }


@dataclass(frozen=True)
class InfiRayOutputEmissionGate:
    code: InfiRayEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class InfiRayMetadataTransactionPlan:
    status: InfiRayPlanStatus
    original_bytes: bytes
    sections: tuple[InfiRaySectionPlan, ...]
    image_boundaries: InfiRayImageBoundariesPlan
    responsibilities: tuple[InfiRayResponsibilityPlan, ...]
    actions: tuple[InfiRayActionPlan, ...]
    output_emission_gates: tuple[InfiRayOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def sections_by_table(self) -> dict[InfiRaySectionTable, InfiRaySectionPlan]:
        return {section.table: section for section in self.sections}

    def sections_by_marker(self) -> dict[int, InfiRaySectionPlan]:
        return {section.marker: section for section in self.sections}

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"InfiRay metadata transaction output is gated: {gate_codes}")
        return self.original_bytes

    def to_json(self) -> JsonObject:
        return {
            "actions": json_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "image_boundaries": self.image_boundaries.to_json(),
            "output_emission_gates": json_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "responsibilities": json_array(item.to_json() for item in self.responsibilities),
            "sections": json_array(section.to_json() for section in self.sections),
            "status": self.status,
        }


@dataclass(frozen=True)
class InfiRayParseResult:
    sections: tuple[InfiRaySectionPlan, ...]
    gates: tuple[InfiRayOutputEmissionGate, ...]
    payload_range: tuple[int, int] | None


@dataclass(frozen=True)
class InfiRaySectionDefinition:
    table: InfiRaySectionTable
    role: InfiRaySectionRole
    min_payload_length: int
    truncation_gate: InfiRayEmissionGateCode
    evidence_ids: tuple[str, ...]


def build_infiray_metadata_transaction_plan(
    jpeg_data: bytes,
    *,
    rewrite_requests: tuple[InfiRayMetadataRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> InfiRayMetadataTransactionPlan:
    """Build a preserve-only InfiRay IJPEG metadata plan from in-memory JPEG bytes."""

    parse = parse_jpeg_sections(jpeg_data)
    image_boundaries = build_combined_image_boundaries(parse.sections)
    responsibilities = build_responsibilities()
    gates = [*parse.gates, *rewrite_gates(rewrite_requests)]
    if not allow_output_emission:
        gates.append(
            InfiRayOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="InfiRay transaction plans are preserve-only unless emission is explicit.",
                evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
            )
        )
    unique_gates = unique_emission_gates(tuple(gates))
    actions = build_actions(parse.sections, parse.payload_range, rewrite_requests)
    status: InfiRayPlanStatus = (
        "unsupported" if structural_gate_present(unique_gates) else "planned"
    )
    sources = unique_sources(
        (
            *INFIRAY_TRANSACTION_SOURCES,
            *image_boundaries.evidence_ids,
            *(source for section in parse.sections for source in section.evidence_ids),
            *(source for item in responsibilities for source in item.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in unique_gates for source in gate.evidence_ids),
        )
    )
    return InfiRayMetadataTransactionPlan(
        status=status,
        original_bytes=jpeg_data,
        sections=parse.sections,
        image_boundaries=image_boundaries,
        responsibilities=responsibilities,
        actions=actions,
        output_emission_gates=unique_gates,
        evidence_ids=sources,
    )


def parse_jpeg_sections(data: bytes) -> InfiRayParseResult:
    if not data.startswith(JPEG_SOI):
        return InfiRayParseResult(
            sections=(),
            gates=(
                InfiRayOutputEmissionGate(
                    code="missing_jpeg_soi",
                    reason="InfiRay IJPEG metadata must be planned from a JPEG byte stream.",
                    evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
                ),
            ),
            payload_range=None,
        )
    sections: list[InfiRaySectionPlan] = []
    gates: list[InfiRayOutputEmissionGate] = []
    offset = 2
    section_index = 0
    payload_range: tuple[int, int] | None = None
    while offset < len(data):
        if data[offset] != JPEG_MARKER_PREFIX:
            payload_range = (offset, len(data))
            break
        marker_start = offset
        offset += 1
        while offset < len(data) and data[offset] == JPEG_MARKER_PREFIX:
            offset += 1
        if offset >= len(data):
            gates.append(
                InfiRayOutputEmissionGate(
                    code="truncated_jpeg_marker",
                    reason="JPEG marker prefix is not followed by a marker byte.",
                    evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
                )
            )
            break
        marker = data[offset]
        offset += 1
        if marker == JPEG_EOI:
            payload_range = (marker_start, len(data))
            break
        if offset + 2 > len(data):
            gates.append(
                InfiRayOutputEmissionGate(
                    code="truncated_jpeg_marker",
                    reason="JPEG segment marker is missing its two-byte length.",
                    evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
                )
            )
            break
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2:
            gates.append(
                InfiRayOutputEmissionGate(
                    code="invalid_jpeg_segment_length",
                    reason="JPEG segment length must include the length bytes.",
                    evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
                )
            )
            break
        payload_start = offset + 2
        segment_end = offset + segment_length
        if segment_end > len(data):
            gates.append(
                InfiRayOutputEmissionGate(
                    code="truncated_jpeg_segment",
                    reason="JPEG segment extends beyond available bytes.",
                    evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
                )
            )
            break
        if APP_MIN_MARKER <= marker <= APP_MAX_MARKER:
            payload = data[payload_start:segment_end]
            section, section_gates = build_section_plan(
                section_index=section_index,
                marker=marker,
                segment_start=marker_start,
                segment_end=segment_end,
                payload_start=payload_start,
                payload=payload,
            )
            section_index += 1
            sections.append(section)
            gates.extend(section_gates)
        offset = segment_end
        if marker == JPEG_SOS:
            payload_range = (offset, len(data))
            break
    if payload_range is None and offset <= len(data):
        payload_range = (offset, len(data))
    return InfiRayParseResult(
        sections=tuple(sections),
        gates=tuple(gates),
        payload_range=payload_range,
    )


def build_section_plan(
    *,
    section_index: int,
    marker: int,
    segment_start: int,
    segment_end: int,
    payload_start: int,
    payload: bytes,
) -> tuple[InfiRaySectionPlan, tuple[InfiRayOutputEmissionGate, ...]]:
    definition = section_definition(marker)
    segment_range = InfiRayByteRange(
        start=segment_start,
        end=segment_end,
        reason="JPEG APP segment including marker and length bytes.",
    )
    payload_range = InfiRayByteRange(
        start=payload_start,
        end=payload_start + len(payload),
        reason="JPEG APP segment payload.",
    )
    gates: list[InfiRayOutputEmissionGate] = []
    parsed_tags: JsonObject = {}
    image_boundaries: InfiRayImageBoundariesPlan | None = None
    sources = definition.evidence_ids
    if definition.table != "Unknown" and len(payload) < definition.min_payload_length:
        gates.append(
            InfiRayOutputEmissionGate(
                code=definition.truncation_gate,
                reason=f"{marker_name(marker)} payload is shorter than the InfiRay table.",
                evidence_ids=sources,
            )
        )
    elif definition.table == "Version":
        if payload[IJPEG_SIGNATURE_OFFSET : IJPEG_SIGNATURE_OFFSET + len(IJPEG_SIGNATURE)] != (
            IJPEG_SIGNATURE
        ):
            gates.append(
                InfiRayOutputEmissionGate(
                    code="unsupported_app2_version_header",
                    reason="APP2 does not contain the IJPEG signature bytes at offset 0x04.",
                    evidence_ids=(INFIRAY_VERSION_SOURCE,),
                )
            )
        parsed_tags = parse_version_tags(payload)
        image_boundaries = parse_version_image_boundaries(payload)
    elif definition.table == "Factory":
        parsed_tags = parse_factory_tags(payload)
    elif definition.table == "Picture":
        parsed_tags = parse_picture_tags(payload)
    elif definition.table == "MixMode":
        parsed_tags = parse_mix_mode_tags(payload)
    elif definition.table == "OpMode":
        parsed_tags = parse_op_mode_tags(payload)
    section = InfiRaySectionPlan(
        section_index=section_index,
        marker=marker,
        marker_name=marker_name(marker),
        table=definition.table,
        role=definition.role,
        segment_range=segment_range,
        payload_range=payload_range,
        payload=payload,
        preserved=True,
        parsed_tags=parsed_tags,
        image_boundaries=image_boundaries,
        evidence_ids=sources,
    )
    return section, tuple(gates)


def parse_version_tags(payload: bytes) -> JsonObject:
    return {
        "IJPEGVersion": json_array(payload[0x00:0x04]),
        "IJPEGSignature": read_c_string(payload[0x04:0x0A]),
        "IJPEGOrgType": payload[0x0C],
        "IJPEGDispType": payload[0x0D],
        "IJPEGRotate": payload[0x0E],
        "IJPEGMirrorFlip": payload[0x0F],
        "ImageColorSwitchable": payload[0x10],
        "ThermalColorPalette": read_u16le(payload, 0x11),
        "IRDataSize": read_u64le(payload, 0x20),
        "IRDataFormat": read_u16le(payload, 0x28),
        "IRImageWidth": read_u16le(payload, 0x2A),
        "IRImageHeight": read_u16le(payload, 0x2C),
        "IRImageBpp": payload[0x2E],
        "TempDataSize": read_u64le(payload, 0x30),
        "TempDataFormat": read_u16le(payload, 0x38),
        "TempImageWidth": read_u16le(payload, 0x3A),
        "TempImageHeight": read_u16le(payload, 0x3C),
        "TempImageBpp": payload[0x3E],
        "VisibleDataSize": read_u64le(payload, 0x40),
        "VisibleDataFormat": read_u16le(payload, 0x48),
        "VisibleImageWidth": read_u16le(payload, 0x4A),
        "VisibleImageHeight": read_u16le(payload, 0x4C),
        "VisibleImageBpp": payload[0x4E],
    }


def parse_version_image_boundaries(payload: bytes) -> InfiRayImageBoundariesPlan:
    return InfiRayImageBoundariesPlan(
        thermal=InfiRayImageBoundaryPlan(
            image_kind="thermal",
            data_size=read_u64le(payload, 0x20),
            data_format=read_u16le(payload, 0x28),
            width=read_u16le(payload, 0x2A),
            height=read_u16le(payload, 0x2C),
            bits_per_pixel=payload[0x2E],
            evidence_ids=(INFIRAY_VERSION_SOURCE,),
        ),
        temperature=InfiRayImageBoundaryPlan(
            image_kind="temperature",
            data_size=read_u64le(payload, 0x30),
            data_format=read_u16le(payload, 0x38),
            width=read_u16le(payload, 0x3A),
            height=read_u16le(payload, 0x3C),
            bits_per_pixel=payload[0x3E],
            evidence_ids=(INFIRAY_VERSION_SOURCE,),
        ),
        visible=InfiRayImageBoundaryPlan(
            image_kind="visible",
            data_size=read_u64le(payload, 0x40),
            data_format=read_u16le(payload, 0x48),
            width=read_u16le(payload, 0x4A),
            height=read_u16le(payload, 0x4C),
            bits_per_pixel=payload[0x4E],
            evidence_ids=(INFIRAY_VERSION_SOURCE,),
        ),
        evidence_ids=(INFIRAY_VERSION_SOURCE,),
    )


def parse_factory_tags(payload: bytes) -> JsonObject:
    return {
        "IJPEGTempVersion": json_array(payload[0x00:0x04]),
        "FactDefEmissivity": read_s8(payload, 0x04),
        "FactDefTau": read_s8(payload, 0x05),
        "FactDefTa": read_s16le(payload, 0x06),
        "FactDefTu": read_s16le(payload, 0x08),
        "FactDefDist": read_s16le(payload, 0x0A),
        "FactDefA0": read_s32le(payload, 0x0C),
        "FactDefB0": read_s32le(payload, 0x10),
        "FactDefA1": read_s32le(payload, 0x14),
        "FactDefB1": read_s32le(payload, 0x18),
        "FactDefP0": read_s32le(payload, 0x1C),
        "FactDefP1": read_s32le(payload, 0x20),
        "FactDefP2": read_s32le(payload, 0x24),
        "FactRelSensorTemp": read_s16le(payload, 0x44),
        "FactRelShutterTemp": read_s16le(payload, 0x46),
        "FactRelLensTemp": read_s16le(payload, 0x48),
        "FactStatusGain": read_s8(payload, 0x64),
        "FactStatusEnvOK": read_s8(payload, 0x65),
        "FactStatusDistOK": read_s8(payload, 0x66),
        "FactStatusTempMap": read_s8(payload, 0x67),
    }


def parse_picture_tags(payload: bytes) -> JsonObject:
    return {
        "EnvironmentTemp": read_floatle(payload, 0x00),
        "Distance": read_floatle(payload, 0x04),
        "Emissivity": read_floatle(payload, 0x08),
        "Humidity": read_floatle(payload, 0x0C),
        "ReferenceTemp": read_floatle(payload, 0x10),
        "TempUnit": payload[0x20],
        "ShowCenterTemp": payload[0x21],
        "ShowMaxTemp": payload[0x22],
        "ShowMinTemp": payload[0x23],
        "TempMeasureCount": read_u16le(payload, 0x24),
    }


def parse_mix_mode_tags(payload: bytes) -> JsonObject:
    return {
        "MixMode": payload[0x00],
        "FusionIntensity": read_floatle(payload, 0x01),
        "OffsetAdjustment": read_floatle(payload, 0x05),
        "CorrectionAsix": json_array(
            read_floatle(payload, 0x09 + index * 4) for index in range(30)
        ),
    }


def parse_op_mode_tags(payload: bytes) -> JsonObject:
    return {
        "WorkingMode": payload[0x00],
        "IntegralTime": read_u32le(payload, 0x01),
        "IntegratTimeHdr": read_u32le(payload, 0x05),
        "GainStable": payload[0x09],
        "TempControlEnable": payload[0x0A],
        "DeviceTemp": read_floatle(payload, 0x0B),
    }


def build_combined_image_boundaries(
    sections: tuple[InfiRaySectionPlan, ...],
) -> InfiRayImageBoundariesPlan:
    for section in sections:
        if section.image_boundaries is not None:
            return section.image_boundaries
    return InfiRayImageBoundariesPlan(
        thermal=None,
        temperature=None,
        visible=None,
        evidence_ids=(INFIRAY_VERSION_SOURCE,),
    )


def build_responsibilities() -> tuple[InfiRayResponsibilityPlan, ...]:
    return (
        InfiRayResponsibilityPlan(
            concern="app2_version_header_routing",
            reason="Route APP2 bytes to the IJPEG Version binary table.",
            evidence_ids=(INFIRAY_VERSION_SOURCE,),
        ),
        InfiRayResponsibilityPlan(
            concern="app4_factory_table_routing",
            reason="Route APP4 bytes to the Factory temperature defaults table.",
            evidence_ids=(INFIRAY_FACTORY_SOURCE,),
        ),
        InfiRayResponsibilityPlan(
            concern="app5_picture_temperature_distance_emissivity_humidity",
            reason="Keep picture temperature, distance, emissivity, and humidity in APP5.",
            evidence_ids=(INFIRAY_PICTURE_SOURCE,),
        ),
        InfiRayResponsibilityPlan(
            concern="app6_mix_mode_routing",
            reason="Keep visual-infrared mix mode and fusion intensity in APP6.",
            evidence_ids=(INFIRAY_MIX_MODE_SOURCE,),
        ),
        InfiRayResponsibilityPlan(
            concern="app7_operation_mode_routing",
            reason="Route APP7 bytes to the operation mode table.",
            evidence_ids=(INFIRAY_OP_MODE_SOURCE,),
        ),
        InfiRayResponsibilityPlan(
            concern="thermal_visible_temp_image_size_boundaries",
            reason="Represent APP2 thermal, temperature, and visible image dimensions separately.",
            evidence_ids=(INFIRAY_VERSION_SOURCE,),
        ),
        InfiRayResponsibilityPlan(
            concern="payload_preservation",
            reason="Preserve all routed APP payloads and image bytes unchanged.",
            evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
        ),
        InfiRayResponsibilityPlan(
            concern="unknown_section_preservation",
            reason="Preserve APP sections outside APP2 and APP4-APP7 as opaque bytes.",
            evidence_ids=(INFIRAY_UNSCOPED_APP_SOURCE,),
        ),
        InfiRayResponsibilityPlan(
            concern="malformed_truncation_blockers",
            reason="Block emission for malformed JPEG framing and truncated InfiRay tables.",
            evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
        ),
        InfiRayResponsibilityPlan(
            concern="unsupported_rewrite_gates",
            reason=(
                "Requested mutations require a writer that this preserve-only slice does not add."
            ),
            evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
        ),
    )


def build_actions(
    sections: tuple[InfiRaySectionPlan, ...],
    payload_range: tuple[int, int] | None,
    rewrite_requests: tuple[InfiRayMetadataRewriteRequest, ...],
) -> tuple[InfiRayActionPlan, ...]:
    actions: list[InfiRayActionPlan] = [
        InfiRayActionPlan(
            kind="validate_jpeg_container",
            target="jpeg_stream",
            byte_range=(0, 2),
            reason="Validate the JPEG SOI gate before routing APP sections.",
            evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
        )
    ]
    for section in sections:
        actions.append(section_action(section))
    if payload_range is not None and payload_range[0] < payload_range[1]:
        actions.append(
            InfiRayActionPlan(
                kind="preserve_jpeg_payload",
                target="jpeg_payload",
                byte_range=payload_range,
                reason="Keep image or trailing JPEG bytes unchanged.",
                evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
            )
        )
    for request in rewrite_requests:
        actions.append(
            InfiRayActionPlan(
                kind="block_requested_rewrite",
                target=f"{request.operation}:{request.target}",
                byte_range=None,
                reason="InfiRay.pm does not define a writer for this requested mutation.",
                evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
            )
        )
    if not rewrite_requests:
        actions.append(
            InfiRayActionPlan(
                kind="no_metadata_mutation",
                target="infiray_sections",
                byte_range=None,
                reason="Default transaction plans preserve input bytes.",
                evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
            )
        )
    return tuple(actions)


def section_action(section: InfiRaySectionPlan) -> InfiRayActionPlan:
    if section.table == "Version":
        return InfiRayActionPlan(
            kind="route_app2_version_header",
            target=section.marker_name,
            byte_range=(section.payload_range.start, section.payload_range.end),
            reason="Route APP2 payload to the IJPEG Version table.",
            evidence_ids=(INFIRAY_VERSION_SOURCE,),
        )
    if section.table == "Factory":
        return InfiRayActionPlan(
            kind="route_app4_factory_table",
            target=section.marker_name,
            byte_range=(section.payload_range.start, section.payload_range.end),
            reason="Route APP4 payload to the Factory table.",
            evidence_ids=(INFIRAY_FACTORY_SOURCE,),
        )
    if section.table == "Picture":
        return InfiRayActionPlan(
            kind="route_app5_picture_table",
            target=section.marker_name,
            byte_range=(section.payload_range.start, section.payload_range.end),
            reason="Route APP5 payload to the Picture table.",
            evidence_ids=(INFIRAY_PICTURE_SOURCE,),
        )
    if section.table == "MixMode":
        return InfiRayActionPlan(
            kind="route_app6_mix_mode_table",
            target=section.marker_name,
            byte_range=(section.payload_range.start, section.payload_range.end),
            reason="Route APP6 payload to the MixMode table.",
            evidence_ids=(INFIRAY_MIX_MODE_SOURCE,),
        )
    if section.table == "OpMode":
        return InfiRayActionPlan(
            kind="route_app7_op_mode_table",
            target=section.marker_name,
            byte_range=(section.payload_range.start, section.payload_range.end),
            reason="Route APP7 payload to the OpMode table.",
            evidence_ids=(INFIRAY_OP_MODE_SOURCE,),
        )
    return InfiRayActionPlan(
        kind="preserve_unknown_app_section",
        target=section.marker_name,
        byte_range=(section.payload_range.start, section.payload_range.end),
        reason="Preserve unsupported APP payload bytes unchanged.",
        evidence_ids=section.evidence_ids,
    )


def rewrite_gates(
    rewrite_requests: tuple[InfiRayMetadataRewriteRequest, ...],
) -> tuple[InfiRayOutputEmissionGate, ...]:
    if not rewrite_requests:
        return ()
    return (
        InfiRayOutputEmissionGate(
            code="rewrite_requested_requires_infiray_writer",
            reason="InfiRay.pm provides read behavior only, so requested rewrites are blocked.",
            evidence_ids=(INFIRAY_READ_ONLY_SOURCE,),
        ),
    )


def structural_gate_present(gates: tuple[InfiRayOutputEmissionGate, ...]) -> bool:
    non_structural_codes = {
        "rewrite_requested_requires_infiray_writer",
        "non_mutating_plan_requires_explicit_emission",
    }
    return any(gate.code not in non_structural_codes for gate in gates)


def unique_emission_gates(
    gates: tuple[InfiRayOutputEmissionGate, ...],
) -> tuple[InfiRayOutputEmissionGate, ...]:
    seen: set[InfiRayEmissionGateCode] = set()
    unique: list[InfiRayOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


def section_definition(marker: int) -> InfiRaySectionDefinition:
    definitions: dict[int, InfiRaySectionDefinition] = {
        APP2_MARKER: InfiRaySectionDefinition(
            table="Version",
            role="version_header",
            min_payload_length=APP2_VERSION_MIN_LENGTH,
            truncation_gate="truncated_infiray_app2_version_header",
            evidence_ids=(INFIRAY_VERSION_SOURCE,),
        ),
        APP4_MARKER: InfiRaySectionDefinition(
            table="Factory",
            role="factory_temperature_defaults",
            min_payload_length=APP4_FACTORY_MIN_LENGTH,
            truncation_gate="truncated_infiray_app4_factory",
            evidence_ids=(INFIRAY_FACTORY_SOURCE,),
        ),
        APP5_MARKER: InfiRaySectionDefinition(
            table="Picture",
            role="picture_temperature_metadata",
            min_payload_length=APP5_PICTURE_MIN_LENGTH,
            truncation_gate="truncated_infiray_app5_picture",
            evidence_ids=(INFIRAY_PICTURE_SOURCE,),
        ),
        APP6_MARKER: InfiRaySectionDefinition(
            table="MixMode",
            role="visual_infrared_mix_mode",
            min_payload_length=APP6_MIX_MODE_MIN_LENGTH,
            truncation_gate="truncated_infiray_app6_mix_mode",
            evidence_ids=(INFIRAY_MIX_MODE_SOURCE,),
        ),
        APP7_MARKER: InfiRaySectionDefinition(
            table="OpMode",
            role="camera_operation_mode",
            min_payload_length=APP7_OP_MODE_MIN_LENGTH,
            truncation_gate="truncated_infiray_app7_op_mode",
            evidence_ids=(INFIRAY_OP_MODE_SOURCE,),
        ),
    }
    unknown_source = (
        INFIRAY_UNSCOPED_APP_SOURCE if marker in {0xE8, 0xE9} else INFIRAY_READ_ONLY_SOURCE
    )
    return definitions.get(
        marker,
        InfiRaySectionDefinition(
            table="Unknown",
            role="unknown_section",
            min_payload_length=0,
            truncation_gate="truncated_jpeg_segment",
            evidence_ids=(unknown_source,),
        ),
    )


def marker_name(marker: int) -> str:
    if APP_MIN_MARKER <= marker <= APP_MAX_MARKER:
        return f"APP{marker - APP_MIN_MARKER}"
    return f"0x{marker:02X}"


def read_c_string(payload: bytes) -> str:
    prefix = payload.split(b"\0", 1)[0]
    return prefix.decode("latin-1", errors="replace")


def read_s8(data: bytes, offset: int) -> int:
    value = data[offset]
    return value - 0x100 if value >= 0x80 else value


def read_u16le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def read_s16le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little", signed=True)


def read_u32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def read_s32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little", signed=True)


def read_u64le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 8], "little")


def read_floatle(data: bytes, offset: int) -> float:
    return float(struct.unpack_from("<f", data, offset)[0])


def json_array(values: Iterable[JsonValue] | bytes) -> JsonArray:
    return list(values)


def json_tuple(value: tuple[int, int] | None) -> JsonArray | None:
    if value is None:
        return None
    return [value[0], value[1]]


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


plan_infiray_metadata_transaction = build_infiray_metadata_transaction_plan
