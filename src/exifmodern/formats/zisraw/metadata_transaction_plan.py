"""Source-grounded ZISRAW/CZI metadata transaction plans.

ExifTool's ZISRAW module is a reader. It validates the 100-byte CZI file
header, reads fixed little-endian version/GUID fields, follows the top-level
metadata pointer to a ZISRAWMETADATA segment, extracts the declared XML payload,
and applies CZI-specific XML tag-name shortening. This planner mirrors those
read boundaries and remains preserve-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from xml.etree import ElementTree

ZISRAW_FILE_SIGNATURE = b"ZISRAWFILE" + (b"\0" * 6)
ZISRAW_METADATA_SIGNATURE = b"ZISRAWMETADATA\0\0"
ZISRAW_HEADER_SIZE = 100
ZISRAW_METADATA_HEADER_SIZE = 288
ZISRAW_VERSION_OFFSET = 0x20
ZISRAW_PRIMARY_GUID_OFFSET = 0x30
ZISRAW_FILE_GUID_OFFSET = 0x40
ZISRAW_METADATA_OFFSET_OFFSET = 92
ZISRAW_METADATA_XML_LENGTH_OFFSET = 32
ZISRAW_MAX_XML_LENGTH = 200_000_000
ZISRAW_PM_SOURCE_PATH = "lib/Image/ExifTool/ZISRAW.pm"

type ZisrawPlanStatus = Literal["planned", "unsupported"]
type ZisrawRewriteOperation = Literal["insert", "replace", "delete"]
type ZisrawRewriteTarget = Literal["file_header", "metadata_header", "xml_metadata", "payload"]
type ZisrawActionKind = Literal[
    "validate_file_header",
    "decode_header_fields",
    "locate_metadata_segment",
    "validate_metadata_header",
    "extract_xml_metadata",
    "parse_xml_metadata",
    "shorten_xml_tag_name",
    "preserve_file_header",
    "preserve_segment_payloads",
    "preserve_metadata_header",
    "preserve_xml_metadata",
    "block_requested_rewrite",
]
type ZisrawEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_zisraw_file_header",
    "unsupported_zisraw_signature",
    "truncated_zisraw_metadata_header",
    "invalid_zisraw_metadata_header",
    "metadata_section_too_large",
    "truncated_zisraw_xml_metadata",
    "malformed_zisraw_xml_metadata",
    "rewrite_requested_requires_zisraw_writer",
]

ZISRAW_DESCRIPTION_SOURCE = "zisraw.description"
ZISRAW_MAIN_TABLE_SOURCE = "zisraw.main.table"
ZISRAW_SHORTEN_SOURCE = "zisraw.shorten"
ZISRAW_HEADER_GATE_SOURCE = "zisraw.header.gate"
ZISRAW_METADATA_GATE_SOURCE = "zisraw.metadata.gate"
ZISRAW_XML_PROCESS_SOURCE = "zisraw.xml.process"
ZISRAW_READ_ONLY_SOURCE = "zisraw.read.only"
ZISRAW_TRANSACTION_SOURCES = (
    ZISRAW_DESCRIPTION_SOURCE,
    ZISRAW_MAIN_TABLE_SOURCE,
    ZISRAW_SHORTEN_SOURCE,
    ZISRAW_HEADER_GATE_SOURCE,
    ZISRAW_METADATA_GATE_SOURCE,
    ZISRAW_XML_PROCESS_SOURCE,
    ZISRAW_READ_ONLY_SOURCE,
)
IGNORED_XML_PREFIX_PARTS = ("ImageDocument", "Metadata", "Information")


@dataclass(frozen=True)
class ZisrawRewriteRequest:
    target: ZisrawRewriteTarget
    operation: ZisrawRewriteOperation
    payload: bytes | None = None
    tag_name: str | None = None


@dataclass(frozen=True)
class ZisrawOutputEmissionGate:
    code: ZisrawEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ZisrawHeaderValidationPlan:
    signature: bytes
    header_bytes_read: int
    byte_order: Literal["little"] | None
    reason: ZisrawEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class ZisrawHeaderFieldsPlan:
    version_components: tuple[int, int] | None
    version_print: str | None
    primary_file_guid_hex: str | None
    file_guid_hex: str | None
    metadata_offset: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ZisrawMetadataSegmentPlan:
    metadata_offset: int | None
    header_range: tuple[int, int] | None
    declared_xml_length: int | None
    xml_range: tuple[int, int] | None
    xml_bytes: bytes
    root_name: str | None
    reason: ZisrawEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ZisrawXmlTagPlan:
    source_path: str
    original_name: str
    exiftool_input_name: str
    shortened_name: str
    text: str | None
    attributes: tuple[tuple[str, str], ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ZisrawPayloadPreservationPlan:
    file_header_range: tuple[int, int] | None
    preserved_ranges: tuple[tuple[int, int], ...]
    metadata_header_range: tuple[int, int] | None
    xml_range: tuple[int, int] | None
    trailing_payload_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ZisrawActionPlan:
    kind: ZisrawActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ZisrawMetadataTransactionPlan:
    status: ZisrawPlanStatus
    source_data: bytes
    header_validation: ZisrawHeaderValidationPlan
    header_fields: ZisrawHeaderFieldsPlan
    metadata_segment: ZisrawMetadataSegmentPlan
    xml_tags: tuple[ZisrawXmlTagPlan, ...]
    preservation: ZisrawPayloadPreservationPlan
    actions: tuple[ZisrawActionPlan, ...]
    output_emission_gates: tuple[ZisrawOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"ZISRAW metadata transaction output is gated: {gate_codes}")
        return self.source_data


def build_zisraw_metadata_transaction_plan(
    zisraw_data: bytes,
    *,
    rewrite_requests: tuple[ZisrawRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> ZisrawMetadataTransactionPlan:
    """Build a preserve-only ZISRAW/CZI metadata transaction plan from bytes."""

    gates: list[ZisrawOutputEmissionGate] = []
    header_validation = build_zisraw_header_validation_plan(zisraw_data)
    if header_validation.reason is not None:
        gates.append(
            ZisrawOutputEmissionGate(
                code=header_validation.reason,
                reason="Input does not satisfy ExifTool's ZISRAW file header gate.",
                evidence_ids=header_validation.evidence_ids,
            )
        )

    header_fields = build_zisraw_header_fields_plan(zisraw_data, header_validation)
    metadata_segment = build_zisraw_metadata_segment_plan(zisraw_data, header_fields)
    if metadata_segment.reason is not None:
        gates.append(
            ZisrawOutputEmissionGate(
                code=metadata_segment.reason,
                reason="ZISRAW metadata segment cannot be read with ExifTool-equivalent bounds.",
                evidence_ids=metadata_segment.evidence_ids,
            )
        )

    xml_tags = build_zisraw_xml_tag_plans(metadata_segment)
    preservation = build_zisraw_payload_preservation_plan(
        zisraw_data,
        header_validation,
        metadata_segment,
    )
    actions = build_zisraw_actions(
        header_validation,
        header_fields,
        metadata_segment,
        xml_tags,
        preservation,
        rewrite_requests,
    )
    if rewrite_requests:
        gates.append(
            ZisrawOutputEmissionGate(
                code="rewrite_requested_requires_zisraw_writer",
                reason="ZISRAW.pm provides read behavior only, so requested rewrites are blocked.",
                evidence_ids=(ZISRAW_READ_ONLY_SOURCE,),
            )
        )
    add_non_mutating_gate(gates, allow_output_emission)
    unique_gates = unique_emission_gates(tuple(gates))
    status: ZisrawPlanStatus = "unsupported" if structural_gate_present(unique_gates) else "planned"
    sources = unique_sources(
        (
            *ZISRAW_TRANSACTION_SOURCES,
            *header_validation.evidence_ids,
            *header_fields.evidence_ids,
            *metadata_segment.evidence_ids,
            *(source for tag in xml_tags for source in tag.evidence_ids),
            *preservation.evidence_ids,
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in unique_gates for source in gate.evidence_ids),
        )
    )
    return ZisrawMetadataTransactionPlan(
        status=status,
        source_data=zisraw_data,
        header_validation=header_validation,
        header_fields=header_fields,
        metadata_segment=metadata_segment,
        xml_tags=xml_tags,
        preservation=preservation,
        actions=actions,
        output_emission_gates=unique_gates,
        evidence_ids=sources,
    )


def build_zisraw_header_validation_plan(zisraw_data: bytes) -> ZisrawHeaderValidationPlan:
    header_bytes_read = min(len(zisraw_data), ZISRAW_HEADER_SIZE)
    signature = zisraw_data[: len(ZISRAW_FILE_SIGNATURE)]
    if len(zisraw_data) < ZISRAW_HEADER_SIZE:
        return ZisrawHeaderValidationPlan(
            signature=signature,
            header_bytes_read=header_bytes_read,
            byte_order=None,
            reason="truncated_zisraw_file_header",
            evidence_ids=(ZISRAW_HEADER_GATE_SOURCE,),
        )
    if not zisraw_data.startswith(ZISRAW_FILE_SIGNATURE):
        return ZisrawHeaderValidationPlan(
            signature=signature,
            header_bytes_read=header_bytes_read,
            byte_order=None,
            reason="unsupported_zisraw_signature",
            evidence_ids=(ZISRAW_HEADER_GATE_SOURCE,),
        )
    return ZisrawHeaderValidationPlan(
        signature=signature,
        header_bytes_read=header_bytes_read,
        byte_order="little",
        reason=None,
        evidence_ids=(ZISRAW_HEADER_GATE_SOURCE,),
    )


def build_zisraw_header_fields_plan(
    zisraw_data: bytes,
    validation: ZisrawHeaderValidationPlan,
) -> ZisrawHeaderFieldsPlan:
    if not validation.is_exiftool_accepted:
        return ZisrawHeaderFieldsPlan(
            version_components=None,
            version_print=None,
            primary_file_guid_hex=None,
            file_guid_hex=None,
            metadata_offset=None,
            evidence_ids=(ZISRAW_MAIN_TABLE_SOURCE,),
        )

    version_components = (
        read_u32le(zisraw_data, ZISRAW_VERSION_OFFSET),
        read_u32le(zisraw_data, ZISRAW_VERSION_OFFSET + 4),
    )
    metadata_offset = read_u64le(zisraw_data, ZISRAW_METADATA_OFFSET_OFFSET)
    return ZisrawHeaderFieldsPlan(
        version_components=version_components,
        version_print=f"{version_components[0]}.{version_components[1]}",
        primary_file_guid_hex=zisraw_data[
            ZISRAW_PRIMARY_GUID_OFFSET : ZISRAW_PRIMARY_GUID_OFFSET + 16
        ].hex(),
        file_guid_hex=zisraw_data[ZISRAW_FILE_GUID_OFFSET : ZISRAW_FILE_GUID_OFFSET + 16].hex(),
        metadata_offset=metadata_offset,
        evidence_ids=(ZISRAW_MAIN_TABLE_SOURCE, ZISRAW_METADATA_GATE_SOURCE),
    )


def build_zisraw_metadata_segment_plan(
    zisraw_data: bytes,
    fields: ZisrawHeaderFieldsPlan,
) -> ZisrawMetadataSegmentPlan:
    if fields.metadata_offset is None:
        return ZisrawMetadataSegmentPlan(
            metadata_offset=None,
            header_range=None,
            declared_xml_length=None,
            xml_range=None,
            xml_bytes=b"",
            root_name=None,
            reason=None,
            evidence_ids=(ZISRAW_METADATA_GATE_SOURCE,),
        )
    if fields.metadata_offset == 0:
        return ZisrawMetadataSegmentPlan(
            metadata_offset=0,
            header_range=None,
            declared_xml_length=None,
            xml_range=None,
            xml_bytes=b"",
            root_name=None,
            reason=None,
            evidence_ids=(ZISRAW_METADATA_GATE_SOURCE,),
        )

    header_start = fields.metadata_offset
    header_end = header_start + ZISRAW_METADATA_HEADER_SIZE
    if len(zisraw_data) < header_end:
        return ZisrawMetadataSegmentPlan(
            metadata_offset=fields.metadata_offset,
            header_range=(header_start, len(zisraw_data)),
            declared_xml_length=None,
            xml_range=None,
            xml_bytes=b"",
            root_name=None,
            reason="truncated_zisraw_metadata_header",
            evidence_ids=(ZISRAW_METADATA_GATE_SOURCE,),
        )

    metadata_header = zisraw_data[header_start:header_end]
    if not metadata_header.startswith(ZISRAW_METADATA_SIGNATURE):
        return ZisrawMetadataSegmentPlan(
            metadata_offset=fields.metadata_offset,
            header_range=(header_start, header_end),
            declared_xml_length=None,
            xml_range=None,
            xml_bytes=b"",
            root_name=None,
            reason="invalid_zisraw_metadata_header",
            evidence_ids=(ZISRAW_METADATA_GATE_SOURCE,),
        )

    declared_xml_length = read_u32le(metadata_header, ZISRAW_METADATA_XML_LENGTH_OFFSET)
    if declared_xml_length >= ZISRAW_MAX_XML_LENGTH:
        return ZisrawMetadataSegmentPlan(
            metadata_offset=fields.metadata_offset,
            header_range=(header_start, header_end),
            declared_xml_length=declared_xml_length,
            xml_range=None,
            xml_bytes=b"",
            root_name=None,
            reason="metadata_section_too_large",
            evidence_ids=(ZISRAW_METADATA_GATE_SOURCE,),
        )

    xml_start = header_end
    xml_end = xml_start + declared_xml_length
    xml_bytes = zisraw_data[xml_start : min(len(zisraw_data), xml_end)]
    if len(zisraw_data) < xml_end:
        return ZisrawMetadataSegmentPlan(
            metadata_offset=fields.metadata_offset,
            header_range=(header_start, header_end),
            declared_xml_length=declared_xml_length,
            xml_range=(xml_start, len(zisraw_data)),
            xml_bytes=xml_bytes,
            root_name=None,
            reason="truncated_zisraw_xml_metadata",
            evidence_ids=(ZISRAW_METADATA_GATE_SOURCE,),
        )

    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return ZisrawMetadataSegmentPlan(
            metadata_offset=fields.metadata_offset,
            header_range=(header_start, header_end),
            declared_xml_length=declared_xml_length,
            xml_range=(xml_start, xml_end),
            xml_bytes=xml_bytes,
            root_name=None,
            reason="malformed_zisraw_xml_metadata",
            evidence_ids=(ZISRAW_XML_PROCESS_SOURCE,),
        )

    return ZisrawMetadataSegmentPlan(
        metadata_offset=fields.metadata_offset,
        header_range=(header_start, header_end),
        declared_xml_length=declared_xml_length,
        xml_range=(xml_start, xml_end),
        xml_bytes=xml_bytes,
        root_name=local_name(root.tag),
        reason=None,
        evidence_ids=(ZISRAW_METADATA_GATE_SOURCE, ZISRAW_XML_PROCESS_SOURCE),
    )


def build_zisraw_xml_tag_plans(
    metadata_segment: ZisrawMetadataSegmentPlan,
) -> tuple[ZisrawXmlTagPlan, ...]:
    if metadata_segment.reason is not None or not metadata_segment.xml_bytes:
        return ()

    root = ElementTree.fromstring(metadata_segment.xml_bytes)
    tags: list[ZisrawXmlTagPlan] = []
    walk_xml_tags(root, (), tags)
    return tuple(tags)


def walk_xml_tags(
    element: ElementTree.Element[str],
    parent_path: tuple[str, ...],
    tags: list[ZisrawXmlTagPlan],
) -> None:
    name = local_name(element.tag)
    source_path = (*parent_path, name)
    exiftool_input_name = exiftool_tag_input_name(source_path)
    tags.append(
        ZisrawXmlTagPlan(
            source_path="/".join(source_path),
            original_name=name,
            exiftool_input_name=exiftool_input_name,
            shortened_name=shorten_zisraw_tag_name(exiftool_input_name),
            text=clean_text(element.text),
            attributes=tuple((local_name(key), value) for key, value in element.attrib.items()),
            evidence_ids=(ZISRAW_XML_PROCESS_SOURCE, ZISRAW_SHORTEN_SOURCE),
        )
    )
    for child in element:
        walk_xml_tags(child, source_path, tags)


def build_zisraw_payload_preservation_plan(
    zisraw_data: bytes,
    validation: ZisrawHeaderValidationPlan,
    metadata_segment: ZisrawMetadataSegmentPlan,
) -> ZisrawPayloadPreservationPlan:
    file_header_range: tuple[int, int] | None = None
    preserved_ranges: tuple[tuple[int, int], ...] = ()
    metadata_header_range: tuple[int, int] | None = None
    xml_range: tuple[int, int] | None = None
    trailing_payload_range: tuple[int, int] | None = None

    if validation.is_exiftool_accepted:
        file_header_range = (0, ZISRAW_HEADER_SIZE)

    if metadata_segment.metadata_offset is not None and metadata_segment.metadata_offset > 0:
        before_metadata_end = min(metadata_segment.metadata_offset, len(zisraw_data))
        if before_metadata_end > ZISRAW_HEADER_SIZE:
            preserved_ranges = ((ZISRAW_HEADER_SIZE, before_metadata_end),)
    if metadata_segment.reason is None:
        metadata_header_range = metadata_segment.header_range
        xml_range = metadata_segment.xml_range
        if xml_range is not None:
            _xml_start, xml_end = xml_range
            trailing_payload_range = (xml_end, len(zisraw_data))
    return ZisrawPayloadPreservationPlan(
        file_header_range=file_header_range,
        preserved_ranges=preserved_ranges,
        metadata_header_range=metadata_header_range,
        xml_range=xml_range,
        trailing_payload_range=trailing_payload_range,
        evidence_ids=(ZISRAW_READ_ONLY_SOURCE,),
    )


def build_zisraw_actions(
    validation: ZisrawHeaderValidationPlan,
    fields: ZisrawHeaderFieldsPlan,
    metadata_segment: ZisrawMetadataSegmentPlan,
    xml_tags: tuple[ZisrawXmlTagPlan, ...],
    preservation: ZisrawPayloadPreservationPlan,
    rewrite_requests: tuple[ZisrawRewriteRequest, ...],
) -> tuple[ZisrawActionPlan, ...]:
    actions: list[ZisrawActionPlan] = [
        ZisrawActionPlan(
            kind="validate_file_header",
            target="zisraw_file_header",
            byte_range=(0, validation.header_bytes_read),
            reason="Validate the 100-byte CZI header and ZISRAWFILE signature.",
            evidence_ids=validation.evidence_ids,
        )
    ]
    if fields.version_components is not None:
        actions.append(
            ZisrawActionPlan(
                kind="decode_header_fields",
                target="ZISRAWVersion/PrimaryFileGUID/FileGUID",
                byte_range=(0, ZISRAW_HEADER_SIZE),
                reason="Decode fixed little-endian header fields from the ZISRAW main table.",
                evidence_ids=fields.evidence_ids,
            )
        )
    if fields.metadata_offset is not None:
        actions.append(
            ZisrawActionPlan(
                kind="locate_metadata_segment",
                target=f"metadata@{fields.metadata_offset}",
                byte_range=(ZISRAW_METADATA_OFFSET_OFFSET, ZISRAW_HEADER_SIZE),
                reason="Read the u64 metadata segment pointer at byte 92.",
                evidence_ids=(ZISRAW_METADATA_GATE_SOURCE,),
            )
        )
    if metadata_segment.header_range is not None:
        actions.append(
            ZisrawActionPlan(
                kind="validate_metadata_header",
                target="ZISRAWMETADATA",
                byte_range=metadata_segment.header_range,
                reason="Validate the metadata segment header and XML length field.",
                evidence_ids=metadata_segment.evidence_ids,
            )
        )
    if metadata_segment.xml_range is not None:
        actions.append(
            ZisrawActionPlan(
                kind="extract_xml_metadata",
                target="XML",
                byte_range=metadata_segment.xml_range,
                reason="Extract the top-level XML metadata block using the declared length.",
                evidence_ids=(ZISRAW_METADATA_GATE_SOURCE, ZISRAW_XML_PROCESS_SOURCE),
            )
        )
    if metadata_segment.reason is None and metadata_segment.xml_range is not None:
        actions.append(
            ZisrawActionPlan(
                kind="parse_xml_metadata",
                target=metadata_segment.root_name or "xml_metadata",
                byte_range=metadata_segment.xml_range,
                reason="Route XML metadata through ExifTool's XML table with CZI shortening.",
                evidence_ids=(ZISRAW_XML_PROCESS_SOURCE,),
            )
        )
    for tag in xml_tags:
        if tag.exiftool_input_name == tag.shortened_name:
            continue
        actions.append(
            ZisrawActionPlan(
                kind="shorten_xml_tag_name",
                target=f"{tag.exiftool_input_name}->{tag.shortened_name}",
                byte_range=metadata_segment.xml_range,
                reason="Apply the ZISRAW.pm ShortenTagNames substitution sequence.",
                evidence_ids=tag.evidence_ids,
            )
        )
    if preservation.file_header_range is not None:
        actions.append(
            ZisrawActionPlan(
                kind="preserve_file_header",
                target="zisraw_file_header",
                byte_range=preservation.file_header_range,
                reason="Keep the validated CZI header bytes unchanged.",
                evidence_ids=preservation.evidence_ids,
            )
        )
    for preserved_range in preservation.preserved_ranges:
        actions.append(
            ZisrawActionPlan(
                kind="preserve_segment_payloads",
                target="payload_before_metadata",
                byte_range=preserved_range,
                reason="Keep non-metadata bytes before the metadata segment unchanged.",
                evidence_ids=preservation.evidence_ids,
            )
        )
    if preservation.metadata_header_range is not None:
        actions.append(
            ZisrawActionPlan(
                kind="preserve_metadata_header",
                target="metadata_header",
                byte_range=preservation.metadata_header_range,
                reason="Keep the metadata segment header unchanged.",
                evidence_ids=preservation.evidence_ids,
            )
        )
    if preservation.xml_range is not None:
        actions.append(
            ZisrawActionPlan(
                kind="preserve_xml_metadata",
                target="xml_metadata",
                byte_range=preservation.xml_range,
                reason="Keep the top-level XML metadata bytes unchanged.",
                evidence_ids=preservation.evidence_ids,
            )
        )
    if preservation.trailing_payload_range is not None:
        actions.append(
            ZisrawActionPlan(
                kind="preserve_segment_payloads",
                target="payload_after_metadata",
                byte_range=preservation.trailing_payload_range,
                reason="Keep non-metadata bytes after the metadata XML unchanged.",
                evidence_ids=preservation.evidence_ids,
            )
        )
    for request in rewrite_requests:
        target_detail: str = request.target
        if request.tag_name is not None:
            target_detail = f"{target_detail}:{request.tag_name}"
        actions.append(
            ZisrawActionPlan(
                kind="block_requested_rewrite",
                target=f"{request.operation}:{target_detail}",
                byte_range=None,
                reason="ZISRAW.pm does not define write behavior for this requested mutation.",
                evidence_ids=(ZISRAW_READ_ONLY_SOURCE,),
            )
        )
    return tuple(actions)


def shorten_zisraw_tag_name(tag_name: str) -> str:
    shortened = tag_name
    for pattern, replacement, replace_all in SHORTEN_RULES:
        count = 0 if replace_all else 1
        shortened = re.sub(pattern, replacement, shortened, count=count)
    return shortened


def exiftool_tag_input_name(source_path: tuple[str, ...]) -> str:
    return "".join(part for part in source_path if part not in IGNORED_XML_PREFIX_PARTS)


def local_name(name: str) -> str:
    if name.startswith("{"):
        _namespace, _, local = name.partition("}")
        return local
    return name


def clean_text(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    return cleaned


def read_u32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def read_u64le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 8], "little")


def add_non_mutating_gate(
    gates: list[ZisrawOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        ZisrawOutputEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="The ZISRAW plan is preserve-only; callers must opt in before emitting bytes.",
            evidence_ids=(ZISRAW_READ_ONLY_SOURCE,),
        )
    )


def structural_gate_present(gates: tuple[ZisrawOutputEmissionGate, ...]) -> bool:
    return any(
        gate.code
        in {
            "truncated_zisraw_file_header",
            "unsupported_zisraw_signature",
            "truncated_zisraw_metadata_header",
            "invalid_zisraw_metadata_header",
            "metadata_section_too_large",
            "truncated_zisraw_xml_metadata",
            "malformed_zisraw_xml_metadata",
        }
        for gate in gates
    )


def unique_emission_gates(
    gates: tuple[ZisrawOutputEmissionGate, ...],
) -> tuple[ZisrawOutputEmissionGate, ...]:
    seen: set[ZisrawEmissionGateCode] = set()
    unique: list[ZisrawOutputEmissionGate] = []
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


SHORTEN_RULES: tuple[tuple[str, str, bool], ...] = (
    (r"^HardwareSetting", "", False),
    (r"^DevicesDevice", "Device", False),
    (r"LightPathNode", "", True),
    (r"Successors", "", True),
    (r"ExperimentExperiment", "Experiment", True),
    (r"ObjectivesObjective", "Objective", False),
    (r"ChannelsChannel", "Channel", False),
    (r"TubeLensesTubeLens", "TubeLens", False),
    (r"^ExperimentHardwareSettingsPoolHardwareSetting", "HardwareSetting", False),
    (r"SharpnessMeasureSetSharpnessMeasure", "Sharpness", False),
    (r"FocusSetupAutofocusSetup", "Autofocus", False),
    (r"TracksTrack", "Track", False),
    (r"ChannelRefsChannelRef", "ChannelRef", False),
    (r"ChangerChanger", "Changer", False),
    (r"ElementsChangerElement", "Changer", False),
    (r"ChangerElements", "Changer", False),
    (r"ContrastChangerContrast", "Contrast", False),
    (r"KeyFunctionsKeyFunction", "KeyFunction", False),
    (r"ManagerContrastManager(Contrast)?", "ManagerContrast", False),
    (r"ObjectiveChangerObjective", "ObjectiveChanger", False),
    (r"ManagerLightManager", "ManagerLight", False),
    (r"WavelengthAreasWavelengthArea", "WavelengthArea", False),
    (r"ReflectorChangerReflector", "ReflectorChanger", False),
    (r"^StageStageAxesStageAxis", "StageAxis", False),
    (r"ShutterChangerShutter", "ShutterChanger", False),
    (r"OnOffChangerOnOff", "OnOffChanger", False),
    (r"UnsharpMaskStateUnsharpMask", "UnsharpMask", False),
    (r"Acquisition", "Acq", False),
    (r"Continuous", "Cont", False),
    (r"Resolution", "Res", False),
    (r"Experiment", "Expt", True),
    (r"Threshold", "Thresh", False),
    (r"Reference", "Ref", False),
    (r"Magnification", "Mag", False),
    (r"Original", "Orig", False),
    (r"FocusSetupFocusStrategySetup", "Focus", False),
    (r"ParametersParameter", "Parameter", False),
    (r"IntervalInfo", "Interval", False),
    (r"ExptBlocksAcqBlock", "AcqBlock", False),
    (r"MicroscopesMicroscope", "Microscope", False),
    (r"TimeSeriesInterval", "TimeSeries", False),
    (r"Interval(.*Interval)", r"\1", False),
    (r"SingleTileRegionsSingleTileRegion", "SingleTileRegion", False),
    (r"AcquisitionMode", "", False),
    (r"DetectorsDetector", "Detector", False),
    (r"Setup", "", False),
    (r"Setting", "", False),
    (r"TrackTrack", "Track", False),
    (r"AnalogOutMaximumsAnalogOutMaximum", "AnalogOutMaximum", False),
    (r"AnalogOutMinimumsAnalogOutMinimum", "AnalogOutMinimum", False),
    (r"DigitalOutLabelsDigitalOutLabelLabel", "DigitalOutLabelLabel", False),
    (
        r"(VivaTomeOpticalSectionInformation)+VivaTomeOpticalSectionInformation",
        "VivaTomeOpticalSectionInformation",
        False,
    ),
    (r"FocusDefiniteFocus", "FocusDefinite", False),
    (r"ChangerChanger", "Changer", False),
    (r"Calibration", "Cal", False),
    (r"LightSwitchChangerRLTLSwitch", "LightSwitchChangerRLTL", False),
    (r"Parameters", "", False),
    (r"Fluorescence", "Fluor", False),
    (r"CameraGeometryCameraGeometry", "CameraGeometry", False),
    (r"CameraCamera", "Camera", False),
    (r"DetectorsCamera", "Camera", False),
    (r"FilterChangerLeftChangerEmissionFilter", "LeftChangerEmissionFilter", False),
    (r"SwitchingStatesSwitchingState", "SwitchingState", False),
    (r"Information", "Info", False),
    (r"SubDimensions?", "", True),
    (r"Setups?", "", False),
    (r"Parameters?", "", False),
    (r"Calculate", "Calc", False),
    (r"Visibility", "Vis", False),
    (r"Orientation", "Orient", False),
    (r"ListItems", "Items", False),
    (r"Increment", "Incr", False),
    (r"Parameter", "Param", False),
    (r"(ParfocalParcentralValues)+ParfocalParcentralValue", "Parcentral", False),
    (r"ParcentralParcentral", "Parcentral", False),
    (r"CorrFocusCorrection", "FocusCorr", False),
    (r"(ApoTomeDepthInfo)+Element", "ApoTomeDepth", False),
    (r"(ApoTomeClickStopInfo)+Element", "ApoTomeClickStop", False),
    (r"DepthDepth", "Depth", False),
    (r"(Devices?)+Device", "Device", False),
    (r"(BeamPathNode)+", "BeamPathNode", False),
    (r"BeamPathsBeamPath", "BeamPath", True),
    (r"BeamPathBeamPath", "BeamPath", True),
    (r"Configuration", "Config", False),
    (r"StageAxesStageAxis", "StageAxis", False),
    (r"RangesRange", "Range", False),
    (r"DataGridDatasGridData(Grid)?", "DataGrid", False),
    (r"DataMicroscopeDatasMicroscopeData(Microscope)?", "DataMicroscope", False),
    (r"DataWegaDatasWegaData", "DataWega", False),
    (r"ClickStopPositionsClickStopPosition", "ClickStopPosition", False),
    (r"LightSourcess?LightSource(Settings)?(LightSource)?", "LightSource", False),
    (r"FilterSetsFilterSet", "FilterSet", False),
    (r"EmissionFiltersEmissionFilter", "EmissionFilter", False),
    (r"ExcitationFiltersExcitationFilter", "ExcitationFilter", False),
    (r"FiltersFilter", "Filter", False),
    (r"DichroicsDichroic", "Dichronic", False),
    (r"WavelengthsWavelength", "Wavelength", False),
    (r"MultiTrackSetup", "MultiTrack", False),
    (r"TrackTrack", "Track", False),
    (r"DataGrabberSetup", "DataGrabber", False),
    (r"CameraFrameSetup", "CameraFrame", False),
    (r"TimeSeries(TimeSeries|Setups)", "TimeSeries", False),
    (r"FocusFocus", "Focus", False),
    (r"FocusAutofocus", "Autofocus", False),
    (r"Focus(Hardware|Software)(Autofocus)+", r"Autofocus\1", False),
    (r"AutofocusAutofocus", "Autofocus", False),
)
