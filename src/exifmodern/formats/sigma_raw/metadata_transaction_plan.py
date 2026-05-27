"""Source-grounded Sigma/Foveon X3F metadata transaction plans.

ExifTool's SigmaRaw module validates the FOVb header, reads a footer directory
of SECd subsections, routes PROP payloads to the X3F properties table, detects
embedded JpgFromRaw data from IMA2 preview sections, and only supports writes
through that embedded JPEG path. This planner mirrors those read boundaries and
records why direct X3F rewrites are gated.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Literal

X3F_SIGNATURE = b"FOVb"
X3F_INITIAL_HEADER_SIZE = 40
X3F_HEADER4_SIZE = 0x300
X3F_DIRECTORY_HEADER_SIZE = 12
X3F_DIRECTORY_ENTRY_SIZE = 12
X3F_PROPERTY_HEADER_SIZE = 24
X3F_PROPERTY_ENTRY_SIZE = 8
X3F_IMAGE_SUBHEADER_SIZE = 28
X3F_JPEG_PREVIEW_SIGNATURE = b"SECi\0\0\x02\0\x02\0\0\0\x12\0\0\0"
type SigmaRawPlanStatus = Literal["planned", "unsupported"]
type SigmaRawHeaderKind = Literal["Header", "Header4"]
type SigmaRawSectionRoute = Literal[
    "properties",
    "preview_image",
    "jpg_from_raw",
    "ignored_preview_image",
    "unknown_preserved",
]
type SigmaRawRewriteTarget = Literal["property", "section", "jpg_from_raw"]
type SigmaRawRewriteOperation = Literal["insert", "replace", "delete"]
type SigmaRawActionKind = Literal[
    "validate_x3f_header",
    "route_header",
    "read_footer_directory_pointer",
    "parse_footer_directory",
    "route_section",
    "parse_properties",
    "route_property",
    "preserve_section_payload",
    "preserve_unknown_property",
    "identify_jpg_from_raw",
    "block_requested_rewrite",
]
type SigmaRawEmissionGateCode = Literal[
    "truncated_x3f_header",
    "unsupported_x3f_signature",
    "truncated_extended_x3f_header",
    "truncated_directory_pointer",
    "directory_pointer_out_of_bounds",
    "truncated_x3f_directory",
    "bad_section_header",
    "truncated_x3f_section_payload",
    "truncated_preview_image_header",
    "bad_properties_header",
    "truncated_property_directory",
    "unsupported_property_character_format",
    "bad_property_pointer",
    "x3f_property_rewrite_not_supported",
    "x3f_section_rewrite_requires_directory_rebuild",
    "jpg_from_raw_rewrite_requires_jpeg_writer",
    "planner_is_non_mutating",
]
type SigmaRawResponsibilityConcern = Literal[
    "signature_version_header_validation",
    "versioned_header_routing",
    "extended_header_tags",
    "footer_directory_routing",
    "property_directory_decoding",
    "known_property_classification",
    "unknown_property_preservation",
    "preview_and_jpg_from_raw_detection",
    "payload_preservation",
    "malformed_truncation_blockers",
    "unsupported_rewrite_gates",
]
type SigmaRawPropertyGroup = Literal["Camera", "Image", "Time", "Unknown"]

SIGMA_RAW_MAIN_SOURCE = "sigma.raw.main.source"
SIGMA_RAW_HEADER_SOURCE = "sigma.raw.header.source"
SIGMA_RAW_HEADER_EXT_SOURCE = "sigma.raw.header.ext.source"
SIGMA_RAW_PROPERTIES_SOURCE = "sigma.raw.properties.source"
SIGMA_RAW_HEADER_PROCESS_SOURCE = "sigma.raw.header.process.source"
SIGMA_RAW_PROPERTIES_PROCESS_SOURCE = "sigma.raw.properties.process.source"
SIGMA_RAW_WRITE_SOURCE = "sigma.raw.write.source"
SIGMA_RAW_DIRECTORY_PROCESS_SOURCE = "sigma.raw.directory.process.source"
SIGMA_RAW_PROCESS_SOURCE = "sigma.raw.process.source"

SIGMA_RAW_TRANSACTION_SOURCES = (
    SIGMA_RAW_MAIN_SOURCE,
    SIGMA_RAW_HEADER_SOURCE,
    SIGMA_RAW_HEADER_EXT_SOURCE,
    SIGMA_RAW_PROPERTIES_SOURCE,
    SIGMA_RAW_HEADER_PROCESS_SOURCE,
    SIGMA_RAW_PROPERTIES_PROCESS_SOURCE,
    SIGMA_RAW_WRITE_SOURCE,
    SIGMA_RAW_DIRECTORY_PROCESS_SOURCE,
    SIGMA_RAW_PROCESS_SOURCE,
)

PROPERTY_TAGS: dict[str, tuple[str, SigmaRawPropertyGroup]] = {
    "AEMODE": ("MeteringMode", "Camera"),
    "AFAREA": ("AFArea", "Camera"),
    "AFINFOCUS": ("AFInFocus", "Camera"),
    "AFMODE": ("FocusMode", "Camera"),
    "AP_DESC": ("ApertureDisplayed", "Camera"),
    "APERTURE": ("FNumber", "Image"),
    "BRACKET": ("BracketShot", "Camera"),
    "BURST": ("BurstShot", "Camera"),
    "CAMMANUF": ("Make", "Camera"),
    "CAMMODEL": ("Model", "Camera"),
    "CAMNAME": ("CameraName", "Camera"),
    "CAMSERIAL": ("SerialNumber", "Camera"),
    "CM_DESC": ("SceneCaptureType", "Camera"),
    "COLORSPACE": ("ColorSpace", "Camera"),
    "DRIVE": ("DriveMode", "Camera"),
    "EVAL_STATE": ("EvalState", "Camera"),
    "EXPCOMP": ("ExposureCompensation", "Image"),
    "EXPNET": ("NetExposureCompensation", "Image"),
    "EXPTIME": ("IntegrationTime", "Image"),
    "FIRMVERS": ("FirmwareVersion", "Camera"),
    "FLASH": ("FlashMode", "Camera"),
    "FLASHEXPCOMP": ("FlashExpComp", "Camera"),
    "FLASHPOWER": ("FlashPower", "Camera"),
    "FLASHTTLMODE": ("FlashTTLMode", "Camera"),
    "FLASHTYPE": ("FlashType", "Camera"),
    "FLENGTH": ("FocalLength", "Camera"),
    "FLEQ35MM": ("FocalLengthIn35mmFormat", "Camera"),
    "FOCUS": ("Focus", "Camera"),
    "IMAGERBOARDID": ("ImagerBoardID", "Camera"),
    "IMAGERTEMP": ("SensorTemperature", "Camera"),
    "IMAGEBOARDID": ("ImageBoardID", "Camera"),
    "ISO": ("ISO", "Camera"),
    "LENSARANGE": ("LensApertureRange", "Camera"),
    "LENSFRANGE": ("LensFocalRange", "Camera"),
    "LENSMODEL": ("LensType", "Camera"),
    "PMODE": ("ExposureProgram", "Camera"),
    "RESOLUTION": ("Quality", "Camera"),
    "SENSORID": ("SensorID", "Camera"),
    "SH_DESC": ("ShutterSpeedDisplayed", "Camera"),
    "SHUTTER": ("ExposureTime", "Image"),
    "TIME": ("DateTimeOriginal", "Time"),
    "WB_DESC": ("WhiteBalance", "Camera"),
    "VERSION_BF": ("VersionBF", "Camera"),
}
HEADER_EXT_TAGS: dict[int, str] = {
    0: "Unused",
    1: "ExposureAdjust",
    2: "Contrast",
    3: "Shadow",
    4: "Highlight",
    5: "Saturation",
    6: "Sharpness",
    7: "RedAdjust",
    8: "GreenAdjust",
    9: "BlueAdjust",
    10: "X3FillLight",
}
WORD_PROPERTY_RE = re.compile(r"^\w+$", re.ASCII)


@dataclass(frozen=True)
class SigmaRawMetadataRewriteRequest:
    target: SigmaRawRewriteTarget
    operation: SigmaRawRewriteOperation
    name: str
    payload: bytes | None = None


@dataclass(frozen=True)
class SigmaRawOutputEmissionGate:
    code: SigmaRawEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SigmaRawResponsibilityPlan:
    concern: SigmaRawResponsibilityConcern
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SigmaRawHeaderExtTagPlan:
    selector_index: int
    tag_id: int
    routed_tag: str
    value_offset: int
    value: float | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SigmaRawHeaderPlan:
    signature: bytes
    file_version_raw: int | None
    file_version: str | None
    header_kind: SigmaRawHeaderKind | None
    header_range: tuple[int, int] | None
    extended_header_range: tuple[int, int] | None
    image_unique_id: str | None
    mark_bits: int | None
    image_width: int | None
    image_height: int | None
    rotation: int | None
    white_balance: str | None
    scene_capture_type: str | None
    extended_tags: tuple[SigmaRawHeaderExtTagPlan, ...]
    reason: SigmaRawEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class SigmaRawPropertyPlan:
    index: int
    raw_tag: str
    routed_tag: str
    value: str
    group: SigmaRawPropertyGroup
    known_to_exiftool: bool
    unknown_preserved: bool
    writable: bool
    value_range: tuple[int, int]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SigmaRawPropertiesPlan:
    was_read: bool
    entry_count: int | None
    character_format: int | None
    character_count: int | None
    properties: tuple[SigmaRawPropertyPlan, ...]
    reason: SigmaRawEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SigmaRawSectionPlan:
    index: int
    raw_tag: str
    route: SigmaRawSectionRoute
    offset: int
    length: int
    byte_range: tuple[int, int]
    payload: bytes
    payload_preserved: bool
    preview_header: bytes | None
    image_payload_range: tuple[int, int] | None
    properties: SigmaRawPropertiesPlan | None
    reason: SigmaRawEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SigmaRawDirectoryPlan:
    directory_offset: int | None
    directory_version: int | None
    entry_count: int | None
    directory_range: tuple[int, int] | None
    sections: tuple[SigmaRawSectionPlan, ...]
    reason: SigmaRawEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SigmaRawActionPlan:
    kind: SigmaRawActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SigmaRawMetadataTransactionPlan:
    status: SigmaRawPlanStatus
    source_data: bytes
    header: SigmaRawHeaderPlan
    directory: SigmaRawDirectoryPlan
    responsibilities: tuple[SigmaRawResponsibilityPlan, ...]
    actions: tuple[SigmaRawActionPlan, ...]
    output_emission_gates: tuple[SigmaRawOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Sigma RAW metadata transaction output is gated: {gate_codes}")
        return self.source_data


def build_sigma_raw_metadata_transaction_plan(
    x3f_data: bytes,
    *,
    rewrite_requests: tuple[SigmaRawMetadataRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> SigmaRawMetadataTransactionPlan:
    """Build a preserve-only Sigma/Foveon X3F transaction plan from in-memory bytes."""

    gates: list[SigmaRawOutputEmissionGate] = []
    header = build_sigma_raw_header_plan(x3f_data)
    if header.reason is not None:
        gates.append(gate_from_reason(header.reason, header.evidence_ids))

    directory = build_sigma_raw_directory_plan(x3f_data, header)
    if directory.reason is not None:
        gates.append(gate_from_reason(directory.reason, directory.evidence_ids))
    for section in directory.sections:
        if section.reason is not None:
            gates.append(gate_from_reason(section.reason, section.evidence_ids))
        if section.properties is not None and section.properties.reason is not None:
            gates.append(
                gate_from_reason(section.properties.reason, section.properties.evidence_ids)
            )

    actions = build_sigma_raw_actions(header, directory, rewrite_requests)
    gates.extend(rewrite_gates(rewrite_requests))
    add_non_mutating_gate(gates, allow_output_emission)
    unique_gates = unique_emission_gates(tuple(gates))
    status: SigmaRawPlanStatus = (
        "unsupported" if structural_gate_present(unique_gates) else "planned"
    )
    responsibilities = build_sigma_raw_responsibilities()
    sources = unique_sources(
        (
            *SIGMA_RAW_TRANSACTION_SOURCES,
            *header.evidence_ids,
            *directory.evidence_ids,
            *(source for section in directory.sections for source in section.evidence_ids),
            *(
                source
                for section in directory.sections
                if section.properties is not None
                for source in section.properties.evidence_ids
            ),
            *(
                source
                for section in directory.sections
                if section.properties is not None
                for property_plan in section.properties.properties
                for source in property_plan.evidence_ids
            ),
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in unique_gates for source in gate.evidence_ids),
        )
    )
    return SigmaRawMetadataTransactionPlan(
        status=status,
        source_data=x3f_data,
        header=header,
        directory=directory,
        responsibilities=responsibilities,
        actions=actions,
        output_emission_gates=unique_gates,
        evidence_ids=sources,
    )


def build_sigma_raw_header_plan(x3f_data: bytes) -> SigmaRawHeaderPlan:
    signature = x3f_data[:4]
    if len(x3f_data) < X3F_INITIAL_HEADER_SIZE:
        return empty_header_plan(
            signature=signature,
            reason="truncated_x3f_header",
            sources=(SIGMA_RAW_PROCESS_SOURCE,),
        )
    file_version_raw = read_u32le(x3f_data, 4)
    version_major = file_version_raw >> 16
    version_minor = file_version_raw & 0xFFFF
    file_version = f"{version_major}.{version_minor}"
    if signature != X3F_SIGNATURE:
        return empty_header_plan(
            signature=signature,
            file_version_raw=file_version_raw,
            file_version=file_version,
            reason="unsupported_x3f_signature",
            sources=(SIGMA_RAW_PROCESS_SOURCE,),
        )

    header_kind: SigmaRawHeaderKind = "Header4" if version_major >= 4 else "Header"
    static_header_length, extended_length = x3f_header_lengths(version_major, version_minor)
    required_length = static_header_length + extended_length
    if len(x3f_data) < required_length:
        return empty_header_plan(
            signature=signature,
            file_version_raw=file_version_raw,
            file_version=file_version,
            header_kind=header_kind,
            header_range=(0, min(len(x3f_data), static_header_length)),
            reason="truncated_extended_x3f_header",
            sources=(SIGMA_RAW_PROCESS_SOURCE, SIGMA_RAW_HEADER_PROCESS_SOURCE),
        )

    if header_kind == "Header4":
        image_unique_id = None
        mark_bits = None
        image_width = read_u32le(x3f_data, 40)
        image_height = read_u32le(x3f_data, 44)
        rotation = read_u32le(x3f_data, 48)
        white_balance = None
        scene_capture_type = None
    else:
        image_unique_id = x3f_data[8:24].hex()
        mark_bits = read_u32le(x3f_data, 24)
        image_width = read_u32le(x3f_data, 28)
        image_height = read_u32le(x3f_data, 32)
        rotation = read_u32le(x3f_data, 36)
        white_balance = read_c_string(x3f_data[40:72]) if static_header_length >= 72 else None
        scene_capture_type = (
            read_c_string(x3f_data[72:104]) if static_header_length >= 104 else None
        )

    extended_range = (static_header_length, required_length) if extended_length >= 160 else None
    extended_tags = (
        parse_header_ext_tags(x3f_data, static_header_length) if extended_range is not None else ()
    )
    return SigmaRawHeaderPlan(
        signature=signature,
        file_version_raw=file_version_raw,
        file_version=file_version,
        header_kind=header_kind,
        header_range=(0, static_header_length),
        extended_header_range=extended_range,
        image_unique_id=image_unique_id,
        mark_bits=mark_bits,
        image_width=image_width,
        image_height=image_height,
        rotation=rotation,
        white_balance=white_balance,
        scene_capture_type=scene_capture_type,
        extended_tags=extended_tags,
        reason=None,
        evidence_ids=(
            SIGMA_RAW_PROCESS_SOURCE,
            SIGMA_RAW_HEADER_SOURCE,
            SIGMA_RAW_HEADER_PROCESS_SOURCE,
            SIGMA_RAW_HEADER_EXT_SOURCE,
        ),
    )


def build_sigma_raw_directory_plan(
    x3f_data: bytes,
    header: SigmaRawHeaderPlan,
) -> SigmaRawDirectoryPlan:
    if not header.is_exiftool_accepted:
        return SigmaRawDirectoryPlan(
            directory_offset=None,
            directory_version=None,
            entry_count=None,
            directory_range=None,
            sections=(),
            reason=None,
            evidence_ids=(SIGMA_RAW_DIRECTORY_PROCESS_SOURCE,),
        )
    if len(x3f_data) < 4:
        return empty_directory_plan("truncated_directory_pointer")
    directory_offset = read_u32le(x3f_data, len(x3f_data) - 4)
    if directory_offset + X3F_DIRECTORY_HEADER_SIZE > len(x3f_data):
        return SigmaRawDirectoryPlan(
            directory_offset=directory_offset,
            directory_version=None,
            entry_count=None,
            directory_range=None,
            sections=(),
            reason="directory_pointer_out_of_bounds",
            evidence_ids=(SIGMA_RAW_PROCESS_SOURCE, SIGMA_RAW_DIRECTORY_PROCESS_SOURCE),
        )
    directory_header = x3f_data[directory_offset : directory_offset + X3F_DIRECTORY_HEADER_SIZE]
    if not directory_header.startswith(b"SECd"):
        return SigmaRawDirectoryPlan(
            directory_offset=directory_offset,
            directory_version=None,
            entry_count=None,
            directory_range=(directory_offset, directory_offset + X3F_DIRECTORY_HEADER_SIZE),
            sections=(),
            reason="bad_section_header",
            evidence_ids=(SIGMA_RAW_DIRECTORY_PROCESS_SOURCE,),
        )
    directory_version = read_u32le(directory_header, 4)
    entry_count = read_u32le(directory_header, 8)
    directory_end = (
        directory_offset + X3F_DIRECTORY_HEADER_SIZE + entry_count * X3F_DIRECTORY_ENTRY_SIZE
    )
    if directory_end > len(x3f_data):
        return SigmaRawDirectoryPlan(
            directory_offset=directory_offset,
            directory_version=directory_version,
            entry_count=entry_count,
            directory_range=(directory_offset, len(x3f_data)),
            sections=(),
            reason="truncated_x3f_directory",
            evidence_ids=(SIGMA_RAW_DIRECTORY_PROCESS_SOURCE,),
        )
    sections = tuple(
        build_sigma_raw_section_plan(x3f_data, directory_offset, index)
        for index in range(entry_count)
    )
    return SigmaRawDirectoryPlan(
        directory_offset=directory_offset,
        directory_version=directory_version,
        entry_count=entry_count,
        directory_range=(directory_offset, directory_end),
        sections=sections,
        reason=None,
        evidence_ids=(SIGMA_RAW_PROCESS_SOURCE, SIGMA_RAW_DIRECTORY_PROCESS_SOURCE),
    )


def build_sigma_raw_section_plan(
    x3f_data: bytes,
    directory_offset: int,
    index: int,
) -> SigmaRawSectionPlan:
    entry_offset = directory_offset + X3F_DIRECTORY_HEADER_SIZE + index * X3F_DIRECTORY_ENTRY_SIZE
    offset = read_u32le(x3f_data, entry_offset)
    length = read_u32le(x3f_data, entry_offset + 4)
    raw_tag = x3f_data[entry_offset + 8 : entry_offset + 12].decode("latin-1")
    if offset + length > len(x3f_data):
        return SigmaRawSectionPlan(
            index=index,
            raw_tag=raw_tag,
            route=section_route_for_tag(raw_tag),
            offset=offset,
            length=length,
            byte_range=(offset, min(len(x3f_data), offset + length)),
            payload=x3f_data[offset:],
            payload_preserved=True,
            preview_header=None,
            image_payload_range=None,
            properties=None,
            reason="truncated_x3f_section_payload",
            evidence_ids=(SIGMA_RAW_DIRECTORY_PROCESS_SOURCE,),
        )
    payload = x3f_data[offset : offset + length]
    route = section_route_for_tag(raw_tag)
    preview_header: bytes | None = None
    image_payload_range: tuple[int, int] | None = None
    properties: SigmaRawPropertiesPlan | None = None
    reason: SigmaRawEmissionGateCode | None = None
    sources: tuple[str, ...] = (
        SIGMA_RAW_MAIN_SOURCE,
        SIGMA_RAW_DIRECTORY_PROCESS_SOURCE,
    )
    if route == "properties":
        properties = build_sigma_raw_properties_plan(payload)
        sources = (*sources, *properties.evidence_ids)
        reason = properties.reason
    elif route == "preview_image":
        if length < X3F_IMAGE_SUBHEADER_SIZE:
            reason = "truncated_preview_image_header"
        else:
            preview_header = payload[:X3F_IMAGE_SUBHEADER_SIZE]
            image_payload_range = (offset + X3F_IMAGE_SUBHEADER_SIZE, offset + length)
            if preview_header.startswith(X3F_JPEG_PREVIEW_SIGNATURE):
                image_payload = payload[X3F_IMAGE_SUBHEADER_SIZE:]
                route = "jpg_from_raw" if image_payload.startswith(b"\xff\xd8\xff\xe1") else route
            else:
                route = "ignored_preview_image"
    return SigmaRawSectionPlan(
        index=index,
        raw_tag=raw_tag,
        route=route,
        offset=offset,
        length=length,
        byte_range=(offset, offset + length),
        payload=payload,
        payload_preserved=True,
        preview_header=preview_header,
        image_payload_range=image_payload_range,
        properties=properties,
        reason=reason,
        evidence_ids=sources,
    )


def build_sigma_raw_properties_plan(payload: bytes) -> SigmaRawPropertiesPlan:
    if len(payload) < X3F_PROPERTY_HEADER_SIZE or not payload.startswith(b"SECp"):
        return SigmaRawPropertiesPlan(
            was_read=False,
            entry_count=None,
            character_format=None,
            character_count=None,
            properties=(),
            reason="bad_properties_header",
            evidence_ids=(SIGMA_RAW_PROPERTIES_PROCESS_SOURCE,),
        )
    entry_count = read_u32le(payload, 8)
    character_format = read_u32le(payload, 12)
    character_count = read_u32le(payload, 20)
    char_table_offset = X3F_PROPERTY_HEADER_SIZE + entry_count * X3F_PROPERTY_ENTRY_SIZE
    char_table_end = char_table_offset + character_count * 2
    if char_table_end > len(payload):
        return SigmaRawPropertiesPlan(
            was_read=True,
            entry_count=entry_count,
            character_format=character_format,
            character_count=character_count,
            properties=(),
            reason="truncated_property_directory",
            evidence_ids=(SIGMA_RAW_PROPERTIES_PROCESS_SOURCE,),
        )
    if character_format != 0:
        return SigmaRawPropertiesPlan(
            was_read=True,
            entry_count=entry_count,
            character_format=character_format,
            character_count=character_count,
            properties=(),
            reason="unsupported_property_character_format",
            evidence_ids=(SIGMA_RAW_PROPERTIES_PROCESS_SOURCE,),
        )
    char_values = tuple(
        read_u16le(payload, char_table_offset + char_index * 2)
        for char_index in range(character_count)
    )
    property_plans: list[SigmaRawPropertyPlan] = []
    for index in range(entry_count):
        entry_offset = X3F_PROPERTY_HEADER_SIZE + index * X3F_PROPERTY_ENTRY_SIZE
        name_pos = read_u32le(payload, entry_offset)
        value_pos = read_u32le(payload, entry_offset + 4)
        if name_pos >= len(char_values) or value_pos >= len(char_values):
            return SigmaRawPropertiesPlan(
                was_read=True,
                entry_count=entry_count,
                character_format=character_format,
                character_count=character_count,
                properties=tuple(property_plans),
                reason="bad_property_pointer",
                evidence_ids=(SIGMA_RAW_PROPERTIES_PROCESS_SOURCE,),
            )
        raw_tag = extract_utf16le_string(char_values, name_pos)
        value = extract_utf16le_string(char_values, value_pos)
        routed_tag, group, known = classify_property(raw_tag)
        value_start = char_table_offset + value_pos * 2
        value_end = value_start + (len(value) + 1) * 2
        property_plans.append(
            SigmaRawPropertyPlan(
                index=index,
                raw_tag=raw_tag,
                routed_tag=routed_tag,
                value=value,
                group=group,
                known_to_exiftool=known,
                unknown_preserved=not known,
                writable=False,
                value_range=(value_start, value_end),
                evidence_ids=(
                    SIGMA_RAW_PROPERTIES_SOURCE,
                    SIGMA_RAW_PROPERTIES_PROCESS_SOURCE,
                ),
            )
        )
    return SigmaRawPropertiesPlan(
        was_read=True,
        entry_count=entry_count,
        character_format=character_format,
        character_count=character_count,
        properties=tuple(property_plans),
        reason=None,
        evidence_ids=(SIGMA_RAW_PROPERTIES_SOURCE, SIGMA_RAW_PROPERTIES_PROCESS_SOURCE),
    )


def build_sigma_raw_actions(
    header: SigmaRawHeaderPlan,
    directory: SigmaRawDirectoryPlan,
    rewrite_requests: tuple[SigmaRawMetadataRewriteRequest, ...],
) -> tuple[SigmaRawActionPlan, ...]:
    actions: list[SigmaRawActionPlan] = [
        SigmaRawActionPlan(
            kind="validate_x3f_header",
            target="x3f_header",
            byte_range=(0, min(X3F_INITIAL_HEADER_SIZE, len(header.signature))),
            reason="Validate the FOVb signature and version word read by ProcessX3F.",
            evidence_ids=(SIGMA_RAW_PROCESS_SOURCE,),
        )
    ]
    if header.header_range is not None:
        actions.append(
            SigmaRawActionPlan(
                kind="route_header",
                target=header.header_kind or "Header",
                byte_range=header.header_range,
                reason="Route header bytes through Header or Header4 according to X3F version.",
                evidence_ids=(SIGMA_RAW_PROCESS_SOURCE, SIGMA_RAW_HEADER_SOURCE),
            )
        )
    actions.append(
        SigmaRawActionPlan(
            kind="read_footer_directory_pointer",
            target="x3f_directory_pointer",
            byte_range=None,
            reason="Read the final little-endian directory pointer.",
            evidence_ids=(SIGMA_RAW_PROCESS_SOURCE,),
        )
    )
    if directory.directory_range is not None:
        actions.append(
            SigmaRawActionPlan(
                kind="parse_footer_directory",
                target="SECd",
                byte_range=directory.directory_range,
                reason="Parse the SECd footer directory and its subsection entries.",
                evidence_ids=(SIGMA_RAW_DIRECTORY_PROCESS_SOURCE,),
            )
        )
    for section in directory.sections:
        actions.extend(section_actions(section))
    for request in rewrite_requests:
        actions.append(
            SigmaRawActionPlan(
                kind="block_requested_rewrite",
                target=f"{request.operation}:{request.target}:{request.name}",
                byte_range=None,
                reason="Requested Sigma RAW mutation is recorded but not emitted by this planner.",
                evidence_ids=(SIGMA_RAW_WRITE_SOURCE,),
            )
        )
    return tuple(actions)


def section_actions(section: SigmaRawSectionPlan) -> tuple[SigmaRawActionPlan, ...]:
    actions: list[SigmaRawActionPlan] = [
        SigmaRawActionPlan(
            kind="route_section",
            target=f"{section.index}:{section.raw_tag}:{section.route}",
            byte_range=section.byte_range,
            reason="Route the footer subsection by the SigmaRaw main table.",
            evidence_ids=section.evidence_ids,
        ),
        SigmaRawActionPlan(
            kind="preserve_section_payload",
            target=f"{section.index}:{section.raw_tag}",
            byte_range=section.byte_range,
            reason="Preserve the original subsection bytes without rewriting the X3F directory.",
            evidence_ids=(SIGMA_RAW_WRITE_SOURCE, SIGMA_RAW_DIRECTORY_PROCESS_SOURCE),
        ),
    ]
    if section.route == "jpg_from_raw":
        actions.append(
            SigmaRawActionPlan(
                kind="identify_jpg_from_raw",
                target=f"{section.index}:{section.raw_tag}",
                byte_range=section.image_payload_range,
                reason="Classify IMA2 JPEG preview data with EXIF APP1 as JpgFromRaw.",
                evidence_ids=(SIGMA_RAW_DIRECTORY_PROCESS_SOURCE,),
            )
        )
    if section.properties is not None:
        actions.append(
            SigmaRawActionPlan(
                kind="parse_properties",
                target=f"{section.index}:PROP",
                byte_range=section.byte_range,
                reason="Parse the SECp property directory and UTF-16LE string table.",
                evidence_ids=section.properties.evidence_ids,
            )
        )
        for property_plan in section.properties.properties:
            actions.append(
                SigmaRawActionPlan(
                    kind="route_property",
                    target=f"{property_plan.raw_tag}:{property_plan.routed_tag}",
                    byte_range=property_plan.value_range,
                    reason="Route X3F property metadata through the SigmaRaw Properties table.",
                    evidence_ids=property_plan.evidence_ids,
                )
            )
            if property_plan.unknown_preserved:
                actions.append(
                    SigmaRawActionPlan(
                        kind="preserve_unknown_property",
                        target=property_plan.raw_tag,
                        byte_range=property_plan.value_range,
                        reason="Preserve unknown read-only X3F property data.",
                        evidence_ids=(SIGMA_RAW_PROPERTIES_PROCESS_SOURCE,),
                    )
                )
    return tuple(actions)


def build_sigma_raw_responsibilities() -> tuple[SigmaRawResponsibilityPlan, ...]:
    return (
        SigmaRawResponsibilityPlan(
            "signature_version_header_validation",
            "Require the FOVb signature and derive the numeric X3F version word.",
            (SIGMA_RAW_PROCESS_SOURCE,),
        ),
        SigmaRawResponsibilityPlan(
            "versioned_header_routing",
            "Select Header or Header4 and expose source-declared dimension fields.",
            (SIGMA_RAW_HEADER_SOURCE, SIGMA_RAW_PROCESS_SOURCE),
        ),
        SigmaRawResponsibilityPlan(
            "extended_header_tags",
            "Route non-zero extended header selector bytes to camera adjustment tags.",
            (SIGMA_RAW_HEADER_EXT_SOURCE, SIGMA_RAW_HEADER_PROCESS_SOURCE),
        ),
        SigmaRawResponsibilityPlan(
            "footer_directory_routing",
            "Read SECd footer entries and route known subsection tags.",
            (SIGMA_RAW_MAIN_SOURCE, SIGMA_RAW_DIRECTORY_PROCESS_SOURCE),
        ),
        SigmaRawResponsibilityPlan(
            "property_directory_decoding",
            "Decode SECp property entries through the UTF-16LE string table.",
            (SIGMA_RAW_PROPERTIES_PROCESS_SOURCE,),
        ),
        SigmaRawResponsibilityPlan(
            "known_property_classification",
            "Classify known SigmaRaw property keys through the Perl Properties table.",
            (SIGMA_RAW_PROPERTIES_SOURCE,),
        ),
        SigmaRawResponsibilityPlan(
            "unknown_property_preservation",
            "Keep unknown property payloads read-only instead of inventing write behavior.",
            (SIGMA_RAW_PROPERTIES_PROCESS_SOURCE,),
        ),
        SigmaRawResponsibilityPlan(
            "preview_and_jpg_from_raw_detection",
            "Classify IMA2 preview payloads and detect embedded JpgFromRaw JPEG data.",
            (SIGMA_RAW_MAIN_SOURCE, SIGMA_RAW_DIRECTORY_PROCESS_SOURCE),
        ),
        SigmaRawResponsibilityPlan(
            "payload_preservation",
            "Preserve subsection bytes and directory ordering unless a future writer is used.",
            (SIGMA_RAW_WRITE_SOURCE,),
        ),
        SigmaRawResponsibilityPlan(
            "malformed_truncation_blockers",
            "Block emission when header, directory, subsection, or property bounds are malformed.",
            (
                SIGMA_RAW_PROCESS_SOURCE,
                SIGMA_RAW_DIRECTORY_PROCESS_SOURCE,
                SIGMA_RAW_PROPERTIES_PROCESS_SOURCE,
            ),
        ),
        SigmaRawResponsibilityPlan(
            "unsupported_rewrite_gates",
            "Gate direct X3F property and section rewrites; only embedded JPEG writes "
            "are source-backed.",
            (SIGMA_RAW_MAIN_SOURCE, SIGMA_RAW_WRITE_SOURCE),
        ),
    )


def x3f_header_lengths(version_major: int, version_minor: int) -> tuple[int, int]:
    if version_major >= 4:
        return X3F_HEADER4_SIZE, 0
    if version_major > 2 or (version_major == 2 and version_minor > 0):
        return (104 if version_major > 2 or version_minor > 2 else 72), 160
    return X3F_INITIAL_HEADER_SIZE, 0


def parse_header_ext_tags(
    x3f_data: bytes,
    static_header_length: int,
) -> tuple[SigmaRawHeaderExtTagPlan, ...]:
    tags: list[SigmaRawHeaderExtTagPlan] = []
    selector_start = static_header_length
    value_start = static_header_length + 32
    for index in range(32):
        tag_id = x3f_data[selector_start + index]
        if tag_id == 0:
            continue
        value_offset = value_start + index * 4
        value = read_f32le(x3f_data, value_offset)
        tags.append(
            SigmaRawHeaderExtTagPlan(
                selector_index=index,
                tag_id=tag_id,
                routed_tag=HEADER_EXT_TAGS.get(tag_id, f"HeaderExt_{tag_id}"),
                value_offset=value_offset,
                value=value,
                evidence_ids=(SIGMA_RAW_HEADER_EXT_SOURCE, SIGMA_RAW_HEADER_PROCESS_SOURCE),
            )
        )
    return tuple(tags)


def section_route_for_tag(raw_tag: str) -> SigmaRawSectionRoute:
    if raw_tag == "PROP":
        return "properties"
    if raw_tag in {"IMAG", "IMA2"}:
        return "preview_image"
    return "unknown_preserved"


def classify_property(raw_tag: str) -> tuple[str, SigmaRawPropertyGroup, bool]:
    known = PROPERTY_TAGS.get(raw_tag)
    if known is not None:
        routed_tag, group = known
        return routed_tag, group, True
    if WORD_PROPERTY_RE.fullmatch(raw_tag) is not None:
        return f"SigmaRaw_{raw_tag}", "Unknown", False
    return raw_tag, "Unknown", False


def rewrite_gates(
    rewrite_requests: tuple[SigmaRawMetadataRewriteRequest, ...],
) -> tuple[SigmaRawOutputEmissionGate, ...]:
    gates: list[SigmaRawOutputEmissionGate] = []
    for request in rewrite_requests:
        if request.target == "property":
            gates.append(
                SigmaRawOutputEmissionGate(
                    code="x3f_property_rewrite_not_supported",
                    reason="SigmaRaw properties are read-only in the Perl source.",
                    evidence_ids=(SIGMA_RAW_PROPERTIES_SOURCE, SIGMA_RAW_WRITE_SOURCE),
                )
            )
        elif request.target == "jpg_from_raw":
            gates.append(
                SigmaRawOutputEmissionGate(
                    code="jpg_from_raw_rewrite_requires_jpeg_writer",
                    reason=(
                        "The only source-backed X3F write path delegates to JPEG metadata writing."
                    ),
                    evidence_ids=(SIGMA_RAW_MAIN_SOURCE, SIGMA_RAW_WRITE_SOURCE),
                )
            )
        else:
            gates.append(
                SigmaRawOutputEmissionGate(
                    code="x3f_section_rewrite_requires_directory_rebuild",
                    reason=(
                        "Changing X3F sections requires directory offset, size, order, "
                        "and padding updates."
                    ),
                    evidence_ids=(SIGMA_RAW_WRITE_SOURCE,),
                )
            )
    return tuple(gates)


def add_non_mutating_gate(
    gates: list[SigmaRawOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission or gates:
        return
    gates.append(
        SigmaRawOutputEmissionGate(
            code="planner_is_non_mutating",
            reason="Sigma RAW transaction plans preserve source bytes unless emission is explicit.",
            evidence_ids=(SIGMA_RAW_WRITE_SOURCE,),
        )
    )


def gate_from_reason(
    reason: SigmaRawEmissionGateCode,
    sources: tuple[str, ...],
) -> SigmaRawOutputEmissionGate:
    return SigmaRawOutputEmissionGate(
        code=reason,
        reason=gate_reason(reason),
        evidence_ids=sources,
    )


def gate_reason(reason: SigmaRawEmissionGateCode) -> str:
    reasons: dict[SigmaRawEmissionGateCode, str] = {
        "truncated_x3f_header": "Input is shorter than the 40-byte X3F header gate.",
        "unsupported_x3f_signature": "Input does not start with the FOVb X3F signature.",
        "truncated_extended_x3f_header": "Versioned X3F header bytes are incomplete.",
        "truncated_directory_pointer": "The final directory pointer cannot be read.",
        "directory_pointer_out_of_bounds": (
            "The final directory pointer does not reference a SECd header."
        ),
        "truncated_x3f_directory": "The SECd footer directory entries are incomplete.",
        "bad_section_header": "The footer directory does not start with SECd.",
        "truncated_x3f_section_payload": "A footer subsection points beyond the available bytes.",
        "truncated_preview_image_header": (
            "A preview subsection is shorter than the 28-byte image header."
        ),
        "bad_properties_header": "The PROP payload does not start with a complete SECp header.",
        "truncated_property_directory": (
            "The SECp entry table or UTF-16LE string table is incomplete."
        ),
        "unsupported_property_character_format": (
            "The SECp character format is not the supported format 0."
        ),
        "bad_property_pointer": (
            "A SECp property name or value pointer is outside the string table."
        ),
        "x3f_property_rewrite_not_supported": "Direct X3F property rewriting is not source-backed.",
        "x3f_section_rewrite_requires_directory_rebuild": (
            "X3F section rewriting requires footer rebuild work."
        ),
        "jpg_from_raw_rewrite_requires_jpeg_writer": (
            "Embedded JpgFromRaw changes require JPEG writer delegation."
        ),
        "planner_is_non_mutating": "The planner is preserve-only by default.",
    }
    return reasons[reason]


def structural_gate_present(gates: tuple[SigmaRawOutputEmissionGate, ...]) -> bool:
    rewrite_gate_codes = {
        "x3f_property_rewrite_not_supported",
        "x3f_section_rewrite_requires_directory_rebuild",
        "jpg_from_raw_rewrite_requires_jpeg_writer",
        "planner_is_non_mutating",
    }
    return any(gate.code not in rewrite_gate_codes for gate in gates)


def unique_emission_gates(
    gates: tuple[SigmaRawOutputEmissionGate, ...],
) -> tuple[SigmaRawOutputEmissionGate, ...]:
    seen: set[SigmaRawEmissionGateCode] = set()
    unique: list[SigmaRawOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for source in sources:
        key = source
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return tuple(unique)


def empty_header_plan(
    *,
    signature: bytes,
    reason: SigmaRawEmissionGateCode,
    sources: tuple[str, ...],
    file_version_raw: int | None = None,
    file_version: str | None = None,
    header_kind: SigmaRawHeaderKind | None = None,
    header_range: tuple[int, int] | None = None,
) -> SigmaRawHeaderPlan:
    return SigmaRawHeaderPlan(
        signature=signature,
        file_version_raw=file_version_raw,
        file_version=file_version,
        header_kind=header_kind,
        header_range=header_range,
        extended_header_range=None,
        image_unique_id=None,
        mark_bits=None,
        image_width=None,
        image_height=None,
        rotation=None,
        white_balance=None,
        scene_capture_type=None,
        extended_tags=(),
        reason=reason,
        evidence_ids=sources,
    )


def empty_directory_plan(reason: SigmaRawEmissionGateCode) -> SigmaRawDirectoryPlan:
    return SigmaRawDirectoryPlan(
        directory_offset=None,
        directory_version=None,
        entry_count=None,
        directory_range=None,
        sections=(),
        reason=reason,
        evidence_ids=(SIGMA_RAW_PROCESS_SOURCE, SIGMA_RAW_DIRECTORY_PROCESS_SOURCE),
    )


def read_u16le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def read_u32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def read_f32le(data: bytes, offset: int) -> float:
    return float(struct.unpack_from("<f", data, offset)[0])


def read_c_string(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("latin-1")


def extract_utf16le_string(char_values: tuple[int, ...], start: int) -> str:
    end = start
    while end < len(char_values) and char_values[end] != 0:
        end += 1
    return bytes(
        byte_value
        for char_value in char_values[start:end]
        for byte_value in (char_value & 0xFF, char_value >> 8)
    ).decode("utf-16le")


plan_sigma_raw_metadata_transaction = build_sigma_raw_metadata_transaction_plan
