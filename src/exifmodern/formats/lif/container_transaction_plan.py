"""Source-grounded, non-mutating LIF container transaction planning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from xml.etree import ElementTree

type LifPlanStatus = Literal["planned", "blocked"]
type LifSegmentKind = Literal[
    "lif_header",
    "xml_metadata",
    "xml_chunk_padding",
    "preserved_payload",
]
type LifResponsibilityKind = Literal[
    "lif_signature_validation",
    "little_endian_header_fields",
    "xml_header_metadata_block",
    "utf16le_xml_decode",
    "xmp_directory_processing",
    "ignored_wrapper_tag_suppression",
    "shortened_tag_names",
    "timestamp_list_conversion",
    "image_dimensions",
    "thumbnail_reference",
    "preview_reference",
    "embedded_payload_preservation",
    "non_mutating_emission",
]
type LifEmissionGateCode = Literal[
    "invalid_lif_signature",
    "corrupted_lif_xml_block",
    "lif_xml_block_too_large",
    "truncated_lif_xml_block",
    "declared_lif_xml_chunk_extends_past_source",
    "malformed_lif_utf16_xml",
    "output_emission_requires_explicit_opt_in",
]
type LifRewriteBlockerCode = Literal[
    "mutating_lif_writer_not_ported",
    "xml_metadata_rewrite_not_modeled_by_lif_pm",
    "raw_payload_preservation_required",
    "embedded_payload_rewrite_not_delegated_by_lif_pm",
]
type LifEmbeddedPayloadKind = Literal["jpeg", "exif", "xmp"]
type LifEmbeddedPayloadRoute = Literal["preserve_without_lif_pm_delegation"]

LIF_HEADER_SIZE = 13
LIF_SIGNATURE_READ_SIZE = 15
LIF_XML_SIZE_LIMIT = 100_000_000
LIF_IGNORED_XMP_PROPS = (
    "LMSDataContainerHeader",
    "Element",
    "Children",
    "Data",
    "Image",
    "Attachment",
)

LIF_MAIN_SOURCE = "lif.main_table.xml_xmp_timestamp_list"
LIF_SHORTEN_SOURCE = "lif.shorten_tag_names"
LIF_SIGNATURE_SOURCE = "lif.process.signature_validation"
LIF_HEADER_SOURCE = "lif.process.little_endian_header_fields"
LIF_BLOCKER_SOURCE = "lif.process.xml_block_guards"
LIF_DECODE_SOURCE = "lif.process.utf16_decode_xmp_directory"

LIF_TRANSACTION_SOURCES = (
    LIF_MAIN_SOURCE,
    LIF_SHORTEN_SOURCE,
    LIF_SIGNATURE_SOURCE,
    LIF_HEADER_SOURCE,
    LIF_BLOCKER_SOURCE,
    LIF_DECODE_SOURCE,
)


@dataclass(frozen=True)
class LifEmissionGate:
    code: LifEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LifRewriteBlocker:
    code: LifRewriteBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LifResponsibility:
    concern: LifResponsibilityKind
    detail: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LifHeaderPlan:
    accepted: bool
    sniffed_length: int
    signature_range: tuple[int, int]
    xml_size_field_range: tuple[int, int]
    xml_length_field_range: tuple[int, int]
    declared_xml_chunk_size: int | None
    declared_xml_byte_length: int | None
    xml_payload_range: tuple[int, int] | None
    declared_xml_chunk_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LifSegmentPlan:
    index: int
    kind: LifSegmentKind
    start_offset: int
    end_offset: int
    declared_size: int
    preserved: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LifXmlMetadataPlan:
    decoded_text: str
    encoded_range: tuple[int, int]
    encoded_length: int
    ignored_wrapper_tags: tuple[str, ...]
    root_tag: str | None
    parse_error: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LifMetadataEntry:
    tag_path: str
    tag_name: str
    value: str
    raw_tag_name: str
    value_source: str
    converted_timestamp_values: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LifImageResponsibility:
    concern: LifResponsibilityKind
    tag_name: str
    value: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LifEmbeddedPayloadPlan:
    kind: LifEmbeddedPayloadKind
    offset: int
    marker_range: tuple[int, int]
    route: LifEmbeddedPayloadRoute
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LifContainerTransactionPlan:
    status: LifPlanStatus
    header: LifHeaderPlan
    segments: tuple[LifSegmentPlan, ...]
    xml_metadata: LifXmlMetadataPlan | None
    metadata_entries: tuple[LifMetadataEntry, ...]
    image_responsibilities: tuple[LifImageResponsibility, ...]
    embedded_payloads: tuple[LifEmbeddedPayloadPlan, ...]
    responsibilities: tuple[LifResponsibility, ...]
    rewrite_blockers: tuple[LifRewriteBlocker, ...]
    output_emission_gates: tuple[LifEmissionGate, ...]
    output_bytes: bytes | None
    evidence_ids: tuple[str, ...] = LIF_TRANSACTION_SOURCES

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return self.output_bytes is not None and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output or self.output_bytes is None:
            codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"LIF container transaction output is gated: {codes}")
        return self.output_bytes


def build_lif_container_transaction_plan(
    source_bytes: bytes,
    *,
    allow_output_emission: bool = False,
) -> LifContainerTransactionPlan:
    gates: list[LifEmissionGate] = []
    header = _build_header(source_bytes)
    if not header.accepted:
        gates.append(
            LifEmissionGate(
                code="invalid_lif_signature",
                reason="The first 15 bytes do not match the LIF signature accepted by LIF.pm.",
                evidence_ids=(LIF_SIGNATURE_SOURCE,),
            )
        )

    if header.declared_xml_chunk_size is not None and header.declared_xml_byte_length is not None:
        if header.declared_xml_chunk_size < header.declared_xml_byte_length:
            gates.append(
                LifEmissionGate(
                    code="corrupted_lif_xml_block",
                    reason="The declared XML chunk size is smaller than the XML byte length.",
                    evidence_ids=(LIF_BLOCKER_SOURCE,),
                )
            )
        if header.declared_xml_chunk_size > LIF_XML_SIZE_LIMIT:
            gates.append(
                LifEmissionGate(
                    code="lif_xml_block_too_large",
                    reason="The declared XML chunk size exceeds the LIF.pm 100000000 byte limit.",
                    evidence_ids=(LIF_BLOCKER_SOURCE,),
                )
            )
        xml_end = LIF_HEADER_SIZE + header.declared_xml_byte_length
        if len(source_bytes) < xml_end:
            gates.append(
                LifEmissionGate(
                    code="truncated_lif_xml_block",
                    reason="The source ends before the UTF-16LE XML byte length can be read.",
                    evidence_ids=(LIF_BLOCKER_SOURCE,),
                )
            )
        chunk_end = LIF_HEADER_SIZE + header.declared_xml_chunk_size
        if len(source_bytes) < chunk_end:
            gates.append(
                LifEmissionGate(
                    code="declared_lif_xml_chunk_extends_past_source",
                    reason="The declared XML chunk extent runs past the available source bytes.",
                    evidence_ids=(LIF_HEADER_SOURCE, LIF_BLOCKER_SOURCE),
                )
            )

    xml_metadata, metadata_entries, image_responsibilities, decode_gate = _build_xml_plans(
        source_bytes,
        header,
    )
    if decode_gate is not None:
        gates.append(decode_gate)

    segments = _build_segments(source_bytes, header)
    embedded_payloads = _find_embedded_payloads(source_bytes, header)
    if not allow_output_emission:
        gates.append(
            LifEmissionGate(
                code="output_emission_requires_explicit_opt_in",
                reason="The planner is non-mutating and only returns original bytes with opt-in.",
                evidence_ids=(LIF_DECODE_SOURCE,),
            )
        )

    rewrite_blockers = _build_rewrite_blockers(embedded_payloads)
    status: LifPlanStatus = "blocked" if gates else "planned"
    output_bytes = source_bytes if allow_output_emission and not gates else None
    return LifContainerTransactionPlan(
        status=status,
        header=header,
        segments=segments,
        xml_metadata=xml_metadata,
        metadata_entries=metadata_entries,
        image_responsibilities=image_responsibilities,
        embedded_payloads=embedded_payloads,
        responsibilities=_build_responsibilities(
            metadata_entries,
            image_responsibilities,
            embedded_payloads,
        ),
        rewrite_blockers=rewrite_blockers,
        output_emission_gates=tuple(gates),
        output_bytes=output_bytes,
    )


def _build_header(source_bytes: bytes) -> LifHeaderPlan:
    sniffed_length = min(len(source_bytes), LIF_SIGNATURE_READ_SIZE)
    accepted = (
        len(source_bytes) >= LIF_SIGNATURE_READ_SIZE
        and source_bytes[0:4] == b"\x70\x00\x00\x00"
        and source_bytes[8] == 0x2A
        and source_bytes[13:15] == b"<\x00"
    )
    declared_xml_chunk_size: int | None = None
    declared_xml_byte_length: int | None = None
    xml_payload_range: tuple[int, int] | None = None
    declared_xml_chunk_range: tuple[int, int] | None = None
    if len(source_bytes) >= LIF_HEADER_SIZE:
        declared_xml_chunk_size = int.from_bytes(source_bytes[4:8], "little")
        xml_units = int.from_bytes(source_bytes[9:13], "little")
        declared_xml_byte_length = xml_units * 2
        xml_payload_range = (LIF_HEADER_SIZE, LIF_HEADER_SIZE + declared_xml_byte_length)
        declared_xml_chunk_range = (LIF_HEADER_SIZE, LIF_HEADER_SIZE + declared_xml_chunk_size)
    return LifHeaderPlan(
        accepted=accepted,
        sniffed_length=sniffed_length,
        signature_range=(0, sniffed_length),
        xml_size_field_range=(4, 8),
        xml_length_field_range=(9, 13),
        declared_xml_chunk_size=declared_xml_chunk_size,
        declared_xml_byte_length=declared_xml_byte_length,
        xml_payload_range=xml_payload_range,
        declared_xml_chunk_range=declared_xml_chunk_range,
        evidence_ids=(LIF_SIGNATURE_SOURCE, LIF_HEADER_SOURCE),
    )


def _build_xml_plans(
    source_bytes: bytes,
    header: LifHeaderPlan,
) -> tuple[
    LifXmlMetadataPlan | None,
    tuple[LifMetadataEntry, ...],
    tuple[LifImageResponsibility, ...],
    LifEmissionGate | None,
]:
    if header.declared_xml_byte_length is None:
        return None, (), (), None
    start = LIF_HEADER_SIZE
    end = start + header.declared_xml_byte_length
    if len(source_bytes) < end:
        return None, (), (), None
    xml_bytes = source_bytes[start:end]
    try:
        decoded_text = xml_bytes.decode("utf-16-le")
    except UnicodeDecodeError as exc:
        return (
            None,
            (),
            (),
            LifEmissionGate(
                code="malformed_lif_utf16_xml",
                reason=f"The LIF XML block is not valid UTF-16LE: {exc.reason}.",
                evidence_ids=(LIF_DECODE_SOURCE,),
            ),
        )

    root_tag: str | None = None
    parse_error: str | None = None
    entries: tuple[LifMetadataEntry, ...] = ()
    image_responsibilities: tuple[LifImageResponsibility, ...] = ()
    try:
        root = ElementTree.fromstring(decoded_text)
        root_tag = _local_name(root.tag)
        collected: list[LifMetadataEntry] = []
        image_markers: list[LifImageResponsibility] = []
        _collect_xml_entries(root, (), collected, image_markers)
        entries = tuple(collected)
        image_responsibilities = tuple(image_markers)
    except ElementTree.ParseError as exc:
        parse_error = str(exc)

    return (
        LifXmlMetadataPlan(
            decoded_text=decoded_text,
            encoded_range=(start, end),
            encoded_length=len(xml_bytes),
            ignored_wrapper_tags=LIF_IGNORED_XMP_PROPS,
            root_tag=root_tag,
            parse_error=parse_error,
            evidence_ids=(LIF_MAIN_SOURCE, LIF_DECODE_SOURCE),
        ),
        entries,
        image_responsibilities,
        None,
    )


def _collect_xml_entries(
    element: ElementTree.Element[str],
    parent_path: tuple[str, ...],
    entries: list[LifMetadataEntry],
    image_markers: list[LifImageResponsibility],
) -> None:
    local_tag = _local_name(element.tag)
    next_path = parent_path if local_tag in LIF_IGNORED_XMP_PROPS else (*parent_path, local_tag)
    for attr_name, attr_value in element.attrib.items():
        local_attr = _local_name(attr_name)
        raw_tag_name = "".join((*next_path, local_attr))
        tag_name = _shorten_lif_tag_name(raw_tag_name)
        entries.append(
            LifMetadataEntry(
                tag_path="/".join((*next_path, local_attr)),
                tag_name=tag_name,
                value=attr_value,
                raw_tag_name=raw_tag_name,
                value_source="attribute",
                converted_timestamp_values=_convert_timestamp_list(tag_name, attr_value),
                evidence_ids=_entry_sources(tag_name),
            )
        )
        _record_image_marker(tag_name, attr_value, image_markers)

    text_value = (element.text or "").strip()
    if text_value:
        raw_tag_name = "".join(next_path)
        tag_name = _shorten_lif_tag_name(raw_tag_name)
        entries.append(
            LifMetadataEntry(
                tag_path="/".join(next_path),
                tag_name=tag_name,
                value=text_value,
                raw_tag_name=raw_tag_name,
                value_source="text",
                converted_timestamp_values=_convert_timestamp_list(tag_name, text_value),
                evidence_ids=_entry_sources(tag_name),
            )
        )
        _record_image_marker(tag_name, text_value, image_markers)

    for child in element:
        _collect_xml_entries(child, next_path, entries, image_markers)


def _entry_sources(tag_name: str) -> tuple[str, ...]:
    sources = [LIF_DECODE_SOURCE]
    if tag_name == "TimeStampList":
        sources.append(LIF_MAIN_SOURCE)
    sources.append(LIF_SHORTEN_SOURCE)
    return tuple(sources)


def _build_segments(source_bytes: bytes, header: LifHeaderPlan) -> tuple[LifSegmentPlan, ...]:
    segments = [
        LifSegmentPlan(
            index=0,
            kind="lif_header",
            start_offset=0,
            end_offset=min(len(source_bytes), LIF_HEADER_SIZE),
            declared_size=LIF_HEADER_SIZE,
            preserved=True,
            evidence_ids=(LIF_SIGNATURE_SOURCE, LIF_HEADER_SOURCE),
        )
    ]
    if header.declared_xml_byte_length is None or header.declared_xml_chunk_size is None:
        return tuple(segments)

    xml_end = min(len(source_bytes), LIF_HEADER_SIZE + header.declared_xml_byte_length)
    segments.append(
        LifSegmentPlan(
            index=len(segments),
            kind="xml_metadata",
            start_offset=LIF_HEADER_SIZE,
            end_offset=xml_end,
            declared_size=header.declared_xml_byte_length,
            preserved=True,
            evidence_ids=(LIF_BLOCKER_SOURCE, LIF_DECODE_SOURCE),
        )
    )
    chunk_end = LIF_HEADER_SIZE + header.declared_xml_chunk_size
    if header.declared_xml_chunk_size > header.declared_xml_byte_length:
        padding_start = LIF_HEADER_SIZE + header.declared_xml_byte_length
        segments.append(
            LifSegmentPlan(
                index=len(segments),
                kind="xml_chunk_padding",
                start_offset=min(len(source_bytes), padding_start),
                end_offset=min(len(source_bytes), chunk_end),
                declared_size=header.declared_xml_chunk_size - header.declared_xml_byte_length,
                preserved=True,
                evidence_ids=(LIF_HEADER_SOURCE,),
            )
        )
    if len(source_bytes) > chunk_end:
        segments.append(
            LifSegmentPlan(
                index=len(segments),
                kind="preserved_payload",
                start_offset=chunk_end,
                end_offset=len(source_bytes),
                declared_size=len(source_bytes) - chunk_end,
                preserved=True,
                evidence_ids=(LIF_DECODE_SOURCE,),
            )
        )
    return tuple(segments)


def _find_embedded_payloads(
    source_bytes: bytes,
    header: LifHeaderPlan,
) -> tuple[LifEmbeddedPayloadPlan, ...]:
    if header.declared_xml_chunk_size is None:
        return ()
    payload_start = LIF_HEADER_SIZE + header.declared_xml_chunk_size
    if payload_start >= len(source_bytes):
        return ()
    payload = source_bytes[payload_start:]
    markers: list[LifEmbeddedPayloadPlan] = []
    marker_specs: tuple[tuple[LifEmbeddedPayloadKind, bytes], ...] = (
        ("jpeg", b"\xff\xd8\xff"),
        ("exif", b"Exif\x00\x00"),
        ("xmp", b"<?xpacket"),
        ("xmp", b"<x:xmpmeta"),
    )
    for kind, marker in marker_specs:
        offset = payload.find(marker)
        if offset >= 0:
            absolute = payload_start + offset
            markers.append(
                LifEmbeddedPayloadPlan(
                    kind=kind,
                    offset=absolute,
                    marker_range=(absolute, absolute + len(marker)),
                    route="preserve_without_lif_pm_delegation",
                    evidence_ids=(LIF_DECODE_SOURCE,),
                )
            )
    return tuple(markers)


def _build_responsibilities(
    entries: tuple[LifMetadataEntry, ...],
    image_responsibilities: tuple[LifImageResponsibility, ...],
    embedded_payloads: tuple[LifEmbeddedPayloadPlan, ...],
) -> tuple[LifResponsibility, ...]:
    concerns: list[LifResponsibility] = [
        LifResponsibility(
            concern="lif_signature_validation",
            detail="Validate the 15-byte LIF prefix before planning metadata extraction.",
            evidence_ids=(LIF_SIGNATURE_SOURCE,),
        ),
        LifResponsibility(
            concern="little_endian_header_fields",
            detail="Read XML chunk size and UTF-16 code unit count as little-endian fields.",
            evidence_ids=(LIF_HEADER_SOURCE,),
        ),
        LifResponsibility(
            concern="xml_header_metadata_block",
            detail="Treat the UTF-16LE XML block as the metadata directory processed by LIF.pm.",
            evidence_ids=(LIF_MAIN_SOURCE, LIF_DECODE_SOURCE),
        ),
        LifResponsibility(
            concern="utf16le_xml_decode",
            detail="Decode the LIF XML metadata block from UTF-16LE.",
            evidence_ids=(LIF_DECODE_SOURCE,),
        ),
        LifResponsibility(
            concern="xmp_directory_processing",
            detail="Plan XML metadata extraction through the XMP directory route used by LIF.pm.",
            evidence_ids=(LIF_MAIN_SOURCE, LIF_DECODE_SOURCE),
        ),
        LifResponsibility(
            concern="ignored_wrapper_tag_suppression",
            detail="Suppress Leica wrapper tag names listed in XmpIgnoreProps.",
            evidence_ids=(LIF_DECODE_SOURCE,),
        ),
        LifResponsibility(
            concern="shortened_tag_names",
            detail="Apply the LIF.pm tag shortening table to planned metadata names.",
            evidence_ids=(LIF_SHORTEN_SOURCE,),
        ),
        LifResponsibility(
            concern="non_mutating_emission",
            detail=(
                "Preserve bytes and require explicit opt-in before returning the original source."
            ),
            evidence_ids=(LIF_DECODE_SOURCE,),
        ),
    ]
    if any(entry.converted_timestamp_values for entry in entries):
        concerns.append(
            LifResponsibility(
                concern="timestamp_list_conversion",
                detail="Convert TimeStampList hex values with the LIF.pm epoch adjustment.",
                evidence_ids=(LIF_MAIN_SOURCE,),
            )
        )
    for image_marker in image_responsibilities:
        concerns.append(
            LifResponsibility(
                concern=image_marker.concern,
                detail=f"Record {image_marker.tag_name} from the XML metadata block.",
                evidence_ids=image_marker.evidence_ids,
            )
        )
    if embedded_payloads:
        concerns.append(
            LifResponsibility(
                concern="embedded_payload_preservation",
                detail="Preserve embedded payload markers without routing them to another parser.",
                evidence_ids=(LIF_DECODE_SOURCE,),
            )
        )
    return tuple(concerns)


def _build_rewrite_blockers(
    embedded_payloads: tuple[LifEmbeddedPayloadPlan, ...],
) -> tuple[LifRewriteBlocker, ...]:
    blockers = [
        LifRewriteBlocker(
            code="mutating_lif_writer_not_ported",
            reason="LIF.pm is a read implementation and does not provide container write logic.",
            evidence_ids=(LIF_MAIN_SOURCE, LIF_DECODE_SOURCE),
        ),
        LifRewriteBlocker(
            code="xml_metadata_rewrite_not_modeled_by_lif_pm",
            reason="The oracle decodes and processes XML but does not describe XML rewrite rules.",
            evidence_ids=(LIF_DECODE_SOURCE,),
        ),
        LifRewriteBlocker(
            code="raw_payload_preservation_required",
            reason="Bytes outside the XML metadata block are preserved by the transaction plan.",
            evidence_ids=(LIF_DECODE_SOURCE,),
        ),
    ]
    if embedded_payloads:
        blockers.append(
            LifRewriteBlocker(
                code="embedded_payload_rewrite_not_delegated_by_lif_pm",
                reason="LIF.pm does not delegate preserved JPEG, EXIF, or XMP payload bytes.",
                evidence_ids=(LIF_DECODE_SOURCE,),
            )
        )
    return tuple(blockers)


def _record_image_marker(
    tag_name: str,
    value: str,
    image_markers: list[LifImageResponsibility],
) -> None:
    normalized = tag_name.lower()
    concern: LifResponsibilityKind | None = None
    if any(part in normalized for part in ("dimension", "dimensions", "width", "height")):
        concern = "image_dimensions"
    elif "thumbnail" in normalized:
        concern = "thumbnail_reference"
    elif "preview" in normalized:
        concern = "preview_reference"
    if concern is None:
        return
    image_markers.append(
        LifImageResponsibility(
            concern=concern,
            tag_name=tag_name,
            value=value,
            evidence_ids=(LIF_MAIN_SOURCE, LIF_DECODE_SOURCE),
        )
    )


def _local_name(name: str) -> str:
    if "}" in name:
        return name.rsplit("}", 1)[1]
    if ":" in name:
        return name.rsplit(":", 1)[1]
    return name


def _shorten_lif_tag_name(tag_name: str) -> str:
    replacements: tuple[tuple[str, str], ...] = (
        ("DescriptionDimensionsDimensionDescription", "Dimensions"),
        ("DescriptionChannelsChannelDescription", "Channel"),
        ("ShutterListShutter", "Shutter"),
        ("SettingDefinition", "Setting"),
        ("AdditionalZPositionListAdditionalZPosition", "AdditionalZPosition"),
        ("LMSDataContainerHeader", ""),
        ("FilterWheelWheel", "FilterWheel"),
        ("FilterWheelFilter", "FilterWheel"),
        ("DetectorListDetector", "Detector"),
        ("OnlineDyeSeparationOnlineDyeSeparation", "OnlineDyeSeparation"),
        ("AotfListAotf", "Aotf"),
        ("SettingAotfLaserLineSetting", "SettingAotfLaser"),
        ("DataROISetROISet", "DataROISet"),
        ("AdditionalZPosition", "AddZPos"),
        ("LDM_Block_SequentialLDM_Block_Sequential_", "LDM_"),
        ("ATLConfocalSetting", "ATLConfocal"),
        ("LaserArrayLaser", "Laser"),
        ("LDM_Master", "LDM_"),
        ("Separation", "Sep"),
        ("BleachPointsElement", "BleachPoint"),
        ("BeamPositionBeamPosition", "BeamPosition"),
        ("InfoLaserLineSettingArrayLaserLineSetting", "LastLineSetting"),
        ("FilterWheelWheelNameFilterName", "FilterWheelFilterName"),
        ("LUT_ListLut", "Lut"),
        ("ROI_ListRoiRoidata", "ROI_"),
        ("LaserLineSettingArrayLaserLineSetting", "LaserLineSetting"),
    )
    shortened = tag_name
    for old, new in replacements:
        shortened = shortened.replace(old, new)
    regex_replacements: tuple[tuple[str, str], ...] = (
        (r"FRAPplusBlock_FRAPBlock_FRAP_(Master)?", "FRAP_"),
        (r"(List)?ATLConfocal", "ATL_"),
        (r"DataROISetPossible(ROI)?", "DataROISet"),
        (r"RoiElementChildrenElementDataROISingle(Roi)?", "Roi"),
    )
    for pattern, replacement in regex_replacements:
        shortened = re.sub(pattern, replacement, shortened)
    return shortened


def _convert_timestamp_list(tag_name: str, value: str) -> tuple[str, ...]:
    if tag_name != "TimeStampList":
        return ()
    converted: list[str] = []
    epoch_shift = 134_774 * 24 * 3600
    for item in value.split():
        if re.search(r"[^0-9a-fA-F]", item):
            converted.append("0000:00:00 00:00:00")
            continue
        ticks = int(item, 16)
        unix_seconds = ticks * 1e-7 - epoch_shift
        converted.append(_format_unix_time(unix_seconds))
    return tuple(converted)


def _format_unix_time(unix_seconds: float) -> str:
    try:
        value = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=unix_seconds)
    except OverflowError:
        return "0000:00:00 00:00:00"
    return value.strftime("%Y:%m:%d %H:%M:%S")
