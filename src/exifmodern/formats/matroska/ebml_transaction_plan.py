"""Source-backed, non-mutating Matroska EBML transaction plans.

ExifTool's Matroska reader validates the EBML header, decodes variable-length
element IDs and sizes with marker bits removed, walks Segment subdirectories,
skips large/unknown payloads safely, and resolves Matroska ``SimpleTag``
structures through the standardized tag table.  This module models those
responsibilities for future write transactions without implementing a full EBML
writer.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonObject, JsonValue

type MatroskaElementAction = Literal[
    "preserve",
    "preserve_unknown",
    "preserve_void",
    "descend",
    "skip_cluster_payload",
]
type MatroskaRouteAction = Literal[
    "upsert_standard_simple_tag",
    "upsert_generated_simple_tag",
    "delete_simple_tag",
    "delete_all_tags",
]
type MatroskaEmissionGateCode = Literal[
    "invalid_ebml_header_signature",
    "invalid_ebml_header_size",
    "truncated_ebml_element",
    "invalid_ebml_vint",
    "missing_segment",
    "unknown_size_element_blocks_rewrite",
    "size_growth_requires_void_or_rebuild",
    "planner_is_non_mutating",
    "full_ebml_writer_not_implemented",
]
type MatroskaTraversalConcern = Literal[
    "ebml_header_validation",
    "vint_element_id_and_size",
    "scalar_value_extraction",
    "segment_info_tags_traversal",
    "tag_metadata_routing",
    "unknown_element_preservation",
    "void_size_growth_blocker",
    "output_emission_gate",
]

EBML_HEADER_ID = 0x0A45DFA3
SEGMENT_ID = 0x08538067
SEEK_HEAD_ID = 0x014D9B74
INFO_ID = 0x0549A966
CHAPTER_TRANSLATE_ID = 0x2924
TRACKS_ID = 0x0654AE6B
TRACK_ENTRY_ID = 0x2E
TRACK_TRANSLATE_ID = 0x2624
VIDEO_ID = 0x60
AUDIO_ID = 0x61
CONTENT_ENCODINGS_ID = 0x2D80
CONTENT_ENCODING_ID = 0x2240
CONTENT_COMPRESSION_ID = 0x1034
CONTENT_ENCRYPTION_ID = 0x1035
TAGS_ID = 0x0254C367
TAG_ID = 0x3373
TARGETS_ID = 0x23C0
SIMPLE_TAG_ID = 0x27C8
ATTACHMENTS_ID = 0x0941A469
ATTACHED_FILE_ID = 0x21A7
CHAPTERS_ID = 0x43A770
EDITION_ENTRY_ID = 0x5B9
CHAPTER_ATOM_ID = 0x36
CHAPTER_PROCESS_ID = 0x2944
CHAPTER_PROCESS_COMMAND_ID = 0x2911
CLUSTER_ID = 0x0F43B675
VOID_ID = 0x006C
CRC32_ID = 0x003F
TAG_NAME_ID = 0x05A3
TAG_LANGUAGE_ID = 0x047A
TAG_DEFAULT_ID = 0x0484
TAG_STRING_ID = 0x0487
TAG_BINARY_ID = 0x0485

MATROSKA_HEADER_SOURCE = "matroska.header"
MATROSKA_VINT_SOURCE = "matroska.vint"
MATROSKA_TRAVERSAL_SOURCE = "matroska.traversal"
MATROSKA_TAG_TABLE_SOURCE = "matroska.tag.table"
MATROSKA_SIMPLE_TAG_SOURCE = "matroska.simple.tag"
MATROSKA_STD_TAG_SOURCE = "matroska.std.tag"
MATROSKA_STATISTICS_TAG_SOURCE = "matroska.statistics.tag"
MATROSKA_INFO_SCALAR_SOURCE = "matroska.info.scalar"
MATROSKA_SKIP_SOURCE = "matroska.skip"
MATROSKA_OUTPUT_BOUNDARY_SOURCE = "matroska.output.boundary"

MASTER_ELEMENT_IDS = frozenset(
    {
        EBML_HEADER_ID,
        SEGMENT_ID,
        SEEK_HEAD_ID,
        INFO_ID,
        CHAPTER_TRANSLATE_ID,
        TRACKS_ID,
        TRACK_ENTRY_ID,
        TRACK_TRANSLATE_ID,
        VIDEO_ID,
        AUDIO_ID,
        CONTENT_ENCODINGS_ID,
        CONTENT_ENCODING_ID,
        CONTENT_COMPRESSION_ID,
        CONTENT_ENCRYPTION_ID,
        TAGS_ID,
        TAG_ID,
        TARGETS_ID,
        SIMPLE_TAG_ID,
        ATTACHMENTS_ID,
        ATTACHED_FILE_ID,
        CHAPTERS_ID,
        EDITION_ENTRY_ID,
        CHAPTER_ATOM_ID,
        CHAPTER_PROCESS_ID,
        CHAPTER_PROCESS_COMMAND_ID,
        CLUSTER_ID,
    }
)
ELEMENT_NAMES: dict[int, str] = {
    EBML_HEADER_ID: "EBMLHeader",
    0x0286: "EBMLVersion",
    0x02F7: "EBMLReadVersion",
    0x02F2: "EBMLMaxIDLength",
    0x02F3: "EBMLMaxSizeLength",
    0x0282: "DocType",
    0x0287: "DocTypeVersion",
    0x0285: "DocTypeReadVersion",
    CRC32_ID: "CRC-32",
    VOID_ID: "Void",
    SEGMENT_ID: "Segment",
    SEEK_HEAD_ID: "SeekHead",
    0x0DBB: "Seek",
    0x13AB: "SeekID",
    0x13AC: "SeekPosition",
    INFO_ID: "Info",
    CHAPTER_TRANSLATE_ID: "ChapterTranslate",
    0x29FC: "ChapterTranslateEditionUID",
    0x29BF: "ChapterTranslateCodec",
    0x29A5: "ChapterTranslateID",
    0x03BA9: "Title",
    0x0D80: "MuxingApp",
    0x1741: "WritingApp",
    0x0AD7B1: "TimecodeScale",
    0x0489: "Duration",
    0x0461: "DateTimeOriginal",
    CLUSTER_ID: "Cluster",
    TRACKS_ID: "Tracks",
    TRACK_ENTRY_ID: "TrackEntry",
    0x57: "TrackNumber",
    0x33C5: "TrackUID",
    0x03: "TrackType",
    0x23A2: "CodecPrivate",
    0x137F: "TrackOffset",
    TRACK_TRANSLATE_ID: "TrackTranslate",
    0x26FC: "TrackTranslateEditionUID",
    0x26BF: "TrackTranslateCodec",
    0x26A5: "TrackTranslateTrackID",
    VIDEO_ID: "Video",
    0xEB524: "ColorSpace",
    AUDIO_ID: "Audio",
    0x3D7B: "ChannelPositions",
    CONTENT_ENCODINGS_ID: "ContentEncodings",
    CONTENT_ENCODING_ID: "ContentEncoding",
    0x1031: "ContentEncodingOrder",
    0x1032: "ContentEncodingScope",
    0x1033: "ContentEncodingType",
    CONTENT_COMPRESSION_ID: "ContentCompression",
    0x254: "ContentCompressionAlgorithm",
    0x255: "ContentCompressionSettings",
    CONTENT_ENCRYPTION_ID: "ContentEncryption",
    0x7E1: "ContentEncryptionAlgorithm",
    0x7E2: "ContentEncryptionKeyID",
    0x7E3: "ContentSignature",
    0x7E4: "ContentSignatureKeyID",
    0x7E5: "ContentSignatureAlgorithm",
    0x7E6: "ContentSignatureHashAlgorithm",
    ATTACHMENTS_ID: "Attachments",
    ATTACHED_FILE_ID: "AttachedFile",
    0x67E: "AttachedFileDescription",
    0x66E: "AttachedFileName",
    0x660: "AttachedFileMIMEType",
    0x65C: "AttachedFileData",
    0x6AE: "AttachedFileUID",
    0x675: "AttachedFileReferral",
    CHAPTERS_ID: "Chapters",
    EDITION_ENTRY_ID: "EditionEntry",
    CHAPTER_ATOM_ID: "ChapterAtom",
    CHAPTER_PROCESS_ID: "ChapterProcess",
    0x50D: "ChapterProcessPrivate",
    CHAPTER_PROCESS_COMMAND_ID: "ChapterProcessCommand",
    0x2933: "ChapterProcessData",
    TAGS_ID: "Tags",
    TAG_ID: "Tag",
    TARGETS_ID: "Targets",
    0x28CA: "TargetTypeValue",
    0x23CA: "TargetType",
    0x23C5: "TagTrackUID",
    0x23C9: "TagEditionUID",
    0x23C4: "TagChapterUID",
    0x23C6: "TagAttachmentUID",
    SIMPLE_TAG_ID: "SimpleTag",
    TAG_NAME_ID: "TagName",
    TAG_LANGUAGE_ID: "TagLanguage",
    TAG_DEFAULT_ID: "TagDefault",
    TAG_STRING_ID: "TagString",
    TAG_BINARY_ID: "TagBinary",
}
SCALAR_FORMATS: dict[int, str] = {
    0x0286: "unsigned",
    0x02F7: "unsigned",
    0x02F2: "unsigned",
    0x02F3: "unsigned",
    0x0282: "string",
    0x0287: "unsigned",
    0x0285: "unsigned",
    0x0AD7B1: "unsigned",
    0x0489: "float",
    0x0461: "date",
    0x03BA9: "utf8",
    0x0D80: "utf8",
    0x1741: "utf8",
    0x29FC: "string",
    0x29BF: "unsigned",
    0x57: "unsigned",
    0x33C5: "string",
    0x03: "unsigned",
    0x137F: "signed",
    0x26FC: "string",
    0x26BF: "unsigned",
    0x1031: "unsigned",
    0x1032: "unsigned",
    0x1033: "unsigned",
    0x254: "unsigned",
    0x7E1: "unsigned",
    0x7E5: "unsigned",
    0x7E6: "unsigned",
    0x67E: "utf8",
    0x66E: "utf8",
    0x660: "string",
}
STANDARD_SIMPLE_TAG_OUTPUT_NAMES = {
    "TITLE": "Title",
    "SUBTITLE": "Subtitle",
    "ARTIST": "Artist",
    "LEAD_PERFORMER": "LeadPerformer",
    "COMPOSER": "Composer",
    "DIRECTOR": "Director",
    "PRODUCER": "Producer",
    "GENRE": "Genre",
    "MOOD": "Mood",
    "SUBJECT": "Subject",
    "DESCRIPTION": "Description",
    "KEYWORDS": "Keywords",
    "SUMMARY": "Summary",
    "SYNOPSIS": "Synopsis",
    "DATE_RELEASED": "DateReleased",
    "DATE_RECORDED": "DateTimeOriginal",
    "DATE_ENCODED": "DateEncoded",
    "DATE_TAGGED": "DateTagged",
    "DATE_DIGITIZED": "CreateDate",
    "DATE_WRITTEN": "DateWritten",
    "COMMENT": "Comment",
    "COPYRIGHT": "Copyright",
    "LICENSE": "License",
    "BPS": "BPS",
    "_STATISTICS_WRITING_DATE_UTC": "StatisticsWritingDateUTC",
    "_STATISTICS_WRITING_APP": "StatisticsWritingApp",
    "_STATISTICS_TAGS": "StatisticsTags",
    "DURATION": "Duration",
    "NUMBER_OF_FRAMES": "NumberOfFrames",
    "NUMBER_OF_BYTES": "NumberOfBytes",
}
STANDARD_SIMPLE_TAGS = frozenset(STANDARD_SIMPLE_TAG_OUTPUT_NAMES)


@dataclass(frozen=True)
class EbmlVInt:
    value: int
    offset: int
    length: int
    raw: bytes
    is_unknown_size: bool
    evidence_ids: tuple[str, ...] = (MATROSKA_VINT_SOURCE,)

    @property
    def next_offset(self) -> int:
        return self.offset + self.length

    def to_json(self) -> JsonObject:
        return {
            "is_unknown_size": self.is_unknown_size,
            "length": self.length,
            "offset": self.offset,
            "raw_hex": self.raw.hex(),
            "value": self.value,
        }


@dataclass(frozen=True)
class MatroskaEbmlElementPlan:
    element_id: int
    name: str
    path: tuple[str, ...]
    offset: int
    id_length: int
    size_length: int
    payload_offset: int
    payload_size: int | None
    end_offset: int | None
    action: MatroskaElementAction
    is_master: bool
    is_unknown: bool
    is_unknown_size: bool
    payload_preview: bytes
    evidence_ids: tuple[str, ...]

    @property
    def full_path(self) -> str:
        return "/".join(self.path)

    @property
    def header_size(self) -> int:
        return self.id_length + self.size_length

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "element_id": f"0x{self.element_id:x}",
            "end_offset": self.end_offset,
            "full_path": self.full_path,
            "header_size": self.header_size,
            "is_master": self.is_master,
            "is_unknown": self.is_unknown,
            "is_unknown_size": self.is_unknown_size,
            "name": self.name,
            "offset": self.offset,
            "payload_offset": self.payload_offset,
            "payload_preview_hex": self.payload_preview.hex(),
            "payload_size": self.payload_size,
        }


@dataclass(frozen=True)
class MatroskaSimpleTagPlan:
    tag_name: str
    routed_name: str
    path: str
    value: str | bytes | None
    language: str | None
    language_code: str | None
    tag_default: bool | None
    is_standardized: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "is_standardized": self.is_standardized,
            "language": self.language,
            "language_code": self.language_code,
            "path": self.path,
            "routed_name": self.routed_name,
            "tag_default": self.tag_default,
            "tag_name": self.tag_name,
            "value": self.value.hex() if isinstance(self.value, bytes) else self.value,
            "value_kind": "binary" if isinstance(self.value, bytes) else "string",
        }


@dataclass(frozen=True)
class MatroskaSimpleTagContext:
    tag_id: str
    routed_name: str
    language: str | None
    country: str | None


@dataclass(frozen=True)
class MatroskaScalarPlan:
    element_id: int
    name: str
    path: str
    format_name: str
    raw_value: JsonValue
    rendered_value: JsonValue
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "element_id": f"0x{self.element_id:x}",
            "format_name": self.format_name,
            "name": self.name,
            "path": self.path,
            "raw_value": self.raw_value,
            "rendered_value": self.rendered_value,
        }


@dataclass(frozen=True)
class MatroskaTagWriteRequest:
    tag_name: str
    value: str | bytes | None
    language: str | None = None
    target_scope: str = "Segment"


@dataclass(frozen=True)
class MatroskaMetadataRoute:
    action: MatroskaRouteAction
    tag_name: str
    routed_name: str
    full_ebml_path: str
    existing_value: str | bytes | None
    requested_value: str | bytes | None
    estimated_size_delta: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "estimated_size_delta": self.estimated_size_delta,
            "existing_value": value_to_json(self.existing_value),
            "full_ebml_path": self.full_ebml_path,
            "requested_value": value_to_json(self.requested_value),
            "routed_name": self.routed_name,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class MatroskaTraversalResponsibility:
    order: int
    concern: MatroskaTraversalConcern
    description: str
    records: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "description": self.description,
            "order": self.order,
            "records": list(self.records),
        }


@dataclass(frozen=True)
class MatroskaEmissionGate:
    code: MatroskaEmissionGateCode
    reason: str
    blocks_emission: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocks_emission": self.blocks_emission,
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MatroskaEbmlHeaderPlan:
    is_valid: bool
    header_size: int | None
    payload_offset: int | None
    payload_end_offset: int | None
    reason: MatroskaEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "header_size": self.header_size,
            "is_valid": self.is_valid,
            "payload_end_offset": self.payload_end_offset,
            "payload_offset": self.payload_offset,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MatroskaEbmlTransactionPlan:
    header: MatroskaEbmlHeaderPlan
    elements: tuple[MatroskaEbmlElementPlan, ...]
    scalars: tuple[MatroskaScalarPlan, ...]
    simple_tags: tuple[MatroskaSimpleTagPlan, ...]
    routes: tuple[MatroskaMetadataRoute, ...]
    responsibilities: tuple[MatroskaTraversalResponsibility, ...]
    output_emission_gates: tuple[MatroskaEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def full_paths(self) -> tuple[str, ...]:
        return tuple(element.full_path for element in self.elements)

    @property
    def unknown_element_count(self) -> int:
        return sum(element.is_unknown for element in self.elements)

    @property
    def preserved_void_bytes(self) -> int:
        return sum(
            element.payload_size or 0
            for element in self.elements
            if element.action == "preserve_void"
        )

    @property
    def estimated_size_delta(self) -> int:
        return sum(route.estimated_size_delta for route in self.routes)

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"Matroska EBML transaction output is gated: {gate_codes}")

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "elements": [element.to_json() for element in self.elements],
            "estimated_size_delta": self.estimated_size_delta,
            "full_paths": list(self.full_paths),
            "header": self.header.to_json(),
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "preserved_void_bytes": self.preserved_void_bytes,
            "responsibilities": [item.to_json() for item in self.responsibilities],
            "routes": [route.to_json() for route in self.routes],
            "scalars": [scalar.to_json() for scalar in self.scalars],
            "simple_tags": [tag.to_json() for tag in self.simple_tags],
            "unknown_element_count": self.unknown_element_count,
        }


def build_matroska_ebml_transaction_plan(
    data: bytes,
    tag_writes: tuple[MatroskaTagWriteRequest, ...] = (),
    *,
    delete_all_tags: bool = False,
    allow_size_growth: bool = False,
) -> MatroskaEbmlTransactionPlan:
    """Build a non-mutating EBML transaction plan for Matroska metadata writes."""

    header, elements, parse_gates = inspect_matroska_ebml(data)
    scalars = extract_scalar_values(elements, data)
    simple_tags = extract_simple_tags(elements, data)
    routes = route_tag_writes(simple_tags, tag_writes, delete_all_tags=delete_all_tags)
    gates = [*parse_gates]

    if not any(element.element_id == SEGMENT_ID for element in elements):
        gates.append(
            MatroskaEmissionGate(
                "missing_segment",
                "A writable Matroska metadata transaction requires a Segment element.",
                True,
                (MATROSKA_TRAVERSAL_SOURCE,),
            )
        )

    unknown_size_rewrite = any(element.is_unknown_size for element in elements) and (
        bool(routes) or delete_all_tags
    )
    if unknown_size_rewrite:
        gates.append(
            MatroskaEmissionGate(
                "unknown_size_element_blocks_rewrite",
                "Unknown-size EBML elements require a full writer before metadata rewrite.",
                True,
                (MATROSKA_VINT_SOURCE, MATROSKA_OUTPUT_BOUNDARY_SOURCE),
            )
        )

    estimated_growth = sum(max(0, route.estimated_size_delta) for route in routes)
    preserved_void = sum(
        element.payload_size or 0 for element in elements if element.action == "preserve_void"
    )
    if estimated_growth > preserved_void and not allow_size_growth:
        gates.append(
            MatroskaEmissionGate(
                "size_growth_requires_void_or_rebuild",
                (
                    f"Planned tag edits need about {estimated_growth} bytes, but only "
                    f"{preserved_void} Void bytes are available for in-place growth."
                ),
                True,
                (MATROSKA_SKIP_SOURCE, MATROSKA_OUTPUT_BOUNDARY_SOURCE),
            )
        )

    gates.extend(
        (
            MatroskaEmissionGate(
                "planner_is_non_mutating",
                "Matroska EBML transaction plans record decisions but do not mutate bytes.",
                True,
                (MATROSKA_OUTPUT_BOUNDARY_SOURCE,),
            ),
            MatroskaEmissionGate(
                "full_ebml_writer_not_implemented",
                "Safe emission requires a complete EBML writer with size and offset repair.",
                True,
                (MATROSKA_OUTPUT_BOUNDARY_SOURCE,),
            ),
        )
    )
    responsibilities = default_responsibilities()
    sources = unique_sources(
        (
            *(
                source
                for responsibility in responsibilities
                for source in responsibility.evidence_ids
            ),
            *(source for element in elements for source in element.evidence_ids),
            *(source for scalar in scalars for source in scalar.evidence_ids),
            *(source for route in routes for source in route.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return MatroskaEbmlTransactionPlan(
        header=header,
        elements=elements,
        scalars=scalars,
        simple_tags=simple_tags,
        routes=routes,
        responsibilities=responsibilities,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
    )


def inspect_matroska_ebml(
    data: bytes,
) -> tuple[
    MatroskaEbmlHeaderPlan,
    tuple[MatroskaEbmlElementPlan, ...],
    tuple[MatroskaEmissionGate, ...],
]:
    gates: list[MatroskaEmissionGate] = []
    if not data.startswith(b"\x1a\x45\xdf\xa3"):
        header = MatroskaEbmlHeaderPlan(
            is_valid=False,
            header_size=None,
            payload_offset=None,
            payload_end_offset=None,
            reason="invalid_ebml_header_signature",
            evidence_ids=(MATROSKA_HEADER_SOURCE,),
        )
        return (
            header,
            (),
            (
                MatroskaEmissionGate(
                    "invalid_ebml_header_signature",
                    "Input does not start with the Matroska EBML header ID.",
                    True,
                    (MATROSKA_HEADER_SOURCE,),
                ),
            ),
        )

    try:
        header_id = read_ebml_vint(data, 0)
        header_size = read_ebml_vint(data, header_id.next_offset)
    except ValueError as exc:
        header = MatroskaEbmlHeaderPlan(
            is_valid=False,
            header_size=None,
            payload_offset=None,
            payload_end_offset=None,
            reason="invalid_ebml_vint",
            evidence_ids=(MATROSKA_HEADER_SOURCE, MATROSKA_VINT_SOURCE),
        )
        return (
            header,
            (),
            (MatroskaEmissionGate("invalid_ebml_vint", str(exc), True, (MATROSKA_VINT_SOURCE,)),),
        )

    payload_offset = header_size.next_offset
    payload_end = payload_offset + header_size.value
    if header_size.value <= 0 or header_size.is_unknown_size or payload_end > len(data):
        header = MatroskaEbmlHeaderPlan(
            is_valid=False,
            header_size=header_size.value,
            payload_offset=payload_offset,
            payload_end_offset=payload_end,
            reason="invalid_ebml_header_size",
            evidence_ids=(MATROSKA_HEADER_SOURCE, MATROSKA_VINT_SOURCE),
        )
        return (
            header,
            (),
            (
                MatroskaEmissionGate(
                    "invalid_ebml_header_size",
                    "EBML header size is zero, unknown, or extends beyond the input.",
                    True,
                    (MATROSKA_HEADER_SOURCE, MATROSKA_VINT_SOURCE),
                ),
            ),
        )

    elements, element_gates = parse_elements(data, 0, len(data), ())
    gates.extend(element_gates)
    header = MatroskaEbmlHeaderPlan(
        is_valid=True,
        header_size=header_size.value,
        payload_offset=payload_offset,
        payload_end_offset=payload_end,
        reason=None,
        evidence_ids=(MATROSKA_HEADER_SOURCE, MATROSKA_VINT_SOURCE),
    )
    return header, tuple(elements), tuple(gates)


def parse_elements(
    data: bytes,
    start: int,
    end: int,
    parent_path: tuple[str, ...],
) -> tuple[list[MatroskaEbmlElementPlan], list[MatroskaEmissionGate]]:
    elements: list[MatroskaEbmlElementPlan] = []
    gates: list[MatroskaEmissionGate] = []
    offset = start
    while offset < end:
        try:
            element_id = read_ebml_vint(data, offset)
            size = read_ebml_vint(data, element_id.next_offset)
        except ValueError as exc:
            gates.append(
                MatroskaEmissionGate(
                    "invalid_ebml_vint",
                    str(exc),
                    True,
                    (MATROSKA_VINT_SOURCE,),
                )
            )
            break

        payload_offset = size.next_offset
        payload_size = None if size.is_unknown_size else size.value
        payload_end = end if payload_size is None else payload_offset + payload_size
        if payload_end > len(data) or payload_end > end:
            gates.append(
                MatroskaEmissionGate(
                    "truncated_ebml_element",
                    f"Element 0x{element_id.value:x} extends beyond its parent payload.",
                    True,
                    (MATROSKA_TRAVERSAL_SOURCE, MATROSKA_VINT_SOURCE),
                )
            )
            break

        name = ELEMENT_NAMES.get(element_id.value, f"Unknown_0x{element_id.value:x}")
        is_master = element_id.value in MASTER_ELEMENT_IDS
        is_unknown = element_id.value not in ELEMENT_NAMES
        path = (*parent_path, name)
        action = element_action(element_id.value, is_master, is_unknown)
        element = MatroskaEbmlElementPlan(
            element_id=element_id.value,
            name=name,
            path=path,
            offset=offset,
            id_length=element_id.length,
            size_length=size.length,
            payload_offset=payload_offset,
            payload_size=payload_size,
            end_offset=payload_end if payload_size is not None else None,
            action=action,
            is_master=is_master,
            is_unknown=is_unknown,
            is_unknown_size=size.is_unknown_size,
            payload_preview=data[payload_offset : min(payload_end, payload_offset + 32)],
            evidence_ids=element_sources(element_id.value, is_unknown),
        )
        elements.append(element)

        if is_master and element_id.value != CLUSTER_ID:
            child_end = payload_end
            child_elements, child_gates = parse_elements(data, payload_offset, child_end, path)
            elements.extend(child_elements)
            gates.extend(child_gates)

        if payload_size is None:
            break
        offset = payload_end
    return elements, gates


def read_ebml_vint(data: bytes, offset: int) -> EbmlVInt:
    """Read a Matroska variable-length integer with EBML marker bits removed."""

    if offset >= len(data):
        raise ValueError(f"Missing EBML VInt at offset {offset}.")
    first = data[offset]
    if first == 0:
        raise ValueError(f"Invalid EBML VInt marker byte 0x00 at offset {offset}.")
    marker = 0x80
    length = 1
    while length <= 8 and not (first & marker):
        marker >>= 1
        length += 1
    if length > 8 or marker == 0:
        raise ValueError(f"Invalid EBML VInt marker at offset {offset}.")
    if offset + length > len(data):
        raise ValueError(f"Truncated EBML VInt at offset {offset}.")

    value = first & (marker - 1)
    all_ones_value = marker - 1
    for item in data[offset + 1 : offset + length]:
        value = value * 256 + item
        all_ones_value = all_ones_value * 256 + 0xFF
    is_unknown = value == all_ones_value
    return EbmlVInt(
        value=-1 if is_unknown else value,
        offset=offset,
        length=length,
        raw=data[offset : offset + length],
        is_unknown_size=is_unknown,
    )


def encode_ebml_vint(value: int, *, length: int | None = None, unknown_size: bool = False) -> bytes:
    """Encode an EBML VInt value for synthetic fixtures."""

    if length is None:
        length = minimal_vint_length(value)
    if length < 1 or length > 8:
        raise ValueError("EBML VInt length must be between 1 and 8 bytes.")
    marker = 1 << (8 - length)
    max_value = marker
    for _ in range(length - 1):
        max_value *= 256
    max_value -= 1
    if unknown_size:
        value = max_value
    elif value < 0 or value >= max_value:
        raise ValueError(f"Value {value} does not fit in a {length}-byte EBML VInt.")
    raw_value = value | (marker << (8 * (length - 1)))
    return raw_value.to_bytes(length, "big")


def encode_ebml_element(
    element_id: int,
    payload: bytes,
    *,
    id_length: int | None = None,
    size_length: int | None = None,
    unknown_size: bool = False,
) -> bytes:
    """Encode a stripped Matroska element ID and payload for tests."""

    if id_length is None:
        id_length = minimal_vint_length(element_id)
    return (
        encode_ebml_vint(element_id, length=id_length)
        + encode_ebml_vint(len(payload), length=size_length, unknown_size=unknown_size)
        + payload
    )


def route_tag_writes(
    existing_tags: tuple[MatroskaSimpleTagPlan, ...],
    requests: tuple[MatroskaTagWriteRequest, ...],
    *,
    delete_all_tags: bool,
) -> tuple[MatroskaMetadataRoute, ...]:
    routes: list[MatroskaMetadataRoute] = []
    existing_by_name = {tag.tag_name.upper(): tag for tag in existing_tags}
    if delete_all_tags:
        for tag in existing_tags:
            routes.append(
                MatroskaMetadataRoute(
                    action="delete_all_tags",
                    tag_name=tag.tag_name,
                    routed_name=tag.routed_name,
                    full_ebml_path=tag.path,
                    existing_value=tag.value,
                    requested_value=None,
                    estimated_size_delta=-(value_length(tag.value) + len(tag.tag_name)),
                    evidence_ids=(MATROSKA_TAG_TABLE_SOURCE, MATROSKA_SIMPLE_TAG_SOURCE),
                )
            )
    for request in requests:
        normalized = request.tag_name.upper()
        existing = existing_by_name.get(normalized)
        is_standard = normalized in STANDARD_SIMPLE_TAGS
        routed_name = (
            standardized_output_name(normalized)
            if is_standard
            else generated_output_name(normalized)
        )
        action: MatroskaRouteAction
        if request.value is None:
            action = "delete_simple_tag"
        elif is_standard:
            action = "upsert_standard_simple_tag"
        else:
            action = "upsert_generated_simple_tag"
        old_len = value_length(existing.value) if existing else 0
        new_len = value_length(request.value)
        structure_overhead = (
            18 + len(normalized) if existing is None and request.value is not None else 0
        )
        routes.append(
            MatroskaMetadataRoute(
                action=action,
                tag_name=normalized,
                routed_name=routed_name,
                full_ebml_path=f"Segment/Tags/Tag/SimpleTag[TagName={normalized}]",
                existing_value=existing.value if existing else None,
                requested_value=request.value,
                estimated_size_delta=new_len - old_len + structure_overhead,
                evidence_ids=(
                    MATROSKA_TAG_TABLE_SOURCE,
                    MATROSKA_SIMPLE_TAG_SOURCE,
                    MATROSKA_STD_TAG_SOURCE,
                ),
            )
        )
    return tuple(routes)


def extract_simple_tags(
    elements: tuple[MatroskaEbmlElementPlan, ...],
    data: bytes,
) -> tuple[MatroskaSimpleTagPlan, ...]:
    tags: list[MatroskaSimpleTagPlan] = []
    simple_tag_elements = [element for element in elements if element.element_id == SIMPLE_TAG_ID]
    for simple_tag in simple_tag_elements:
        children = simple_tag_direct_children(elements, simple_tag)
        tag_name: str | None = None
        tag_value: str | bytes | None = None
        language: str | None = None
        tag_default: bool | None = None
        for child in children:
            payload = data[child.payload_offset : child.payload_offset + (child.payload_size or 0)]
            if child.element_id == TAG_NAME_ID:
                tag_name = decode_ebml_text(payload)
            elif child.element_id == TAG_STRING_ID:
                tag_value = decode_ebml_text(payload)
            elif child.element_id == TAG_BINARY_ID:
                tag_value = payload
            elif child.element_id == TAG_LANGUAGE_ID:
                language = decode_ebml_text(payload)
            elif child.element_id == TAG_DEFAULT_ID:
                tag_default = int.from_bytes(payload, "big") != 0
        if tag_name:
            normalized = tag_name.upper()
            parent = simple_tag_context(elements, data, simple_tag)
            is_standard = normalized in STANDARD_SIMPLE_TAGS
            local_name = (
                standardized_output_name(normalized)
                if is_standard
                else generated_output_name(normalized)
            )
            parent_name = None if parent is None else parent.routed_name
            parent_tag_id = None if parent is None else parent.tag_id
            if parent_tag_id == "COUNTRY":
                parent_name = None
                parent_tag_id = None
            routed_base = f"{parent_name}/{local_name}" if parent_name else local_name
            tag_id_base = f"{parent_tag_id}/{normalized}" if parent_tag_id else normalized
            inherited_language = None if parent is None else parent.language
            inherited_country = None if parent is None else parent.country
            rendered_language = language if language is not None else inherited_language
            language_code = simple_tag_language_code(rendered_language, inherited_country)
            tags.append(
                MatroskaSimpleTagPlan(
                    tag_name=localized_simple_tag_name(tag_id_base, language_code),
                    routed_name=localized_simple_tag_name(routed_base, language_code),
                    path=simple_tag.full_path,
                    value=tag_value,
                    language=rendered_language,
                    language_code=language_code,
                    tag_default=tag_default,
                    is_standardized=is_standard,
                    evidence_ids=simple_tag_evidence_ids(normalized),
                )
            )
    return tuple(tags)


def simple_tag_evidence_ids(tag_name: str) -> tuple[str, ...]:
    if tag_name in {
        "BPS",
        "_STATISTICS_WRITING_DATE_UTC",
        "_STATISTICS_WRITING_APP",
        "_STATISTICS_TAGS",
        "DURATION",
        "NUMBER_OF_FRAMES",
        "NUMBER_OF_BYTES",
    }:
        return (
            MATROSKA_SIMPLE_TAG_SOURCE,
            MATROSKA_STD_TAG_SOURCE,
            MATROSKA_STATISTICS_TAG_SOURCE,
        )
    return (MATROSKA_SIMPLE_TAG_SOURCE, MATROSKA_STD_TAG_SOURCE)


def simple_tag_context(
    elements: tuple[MatroskaEbmlElementPlan, ...],
    data: bytes,
    simple_tag: MatroskaEbmlElementPlan,
) -> MatroskaSimpleTagContext | None:
    if simple_tag.end_offset is None:
        return None
    parents = [
        element
        for element in elements
        if element.element_id == SIMPLE_TAG_ID
        and element.end_offset is not None
        and element.payload_offset < simple_tag.payload_offset
        and element.end_offset >= simple_tag.end_offset
    ]
    if not parents:
        return None
    nearest = max(parents, key=lambda element: element.payload_offset)
    parent = simple_tag_context(elements, data, nearest)
    children = simple_tag_direct_children(elements, nearest)
    tag_name = simple_tag_text_child(elements, data, children, TAG_NAME_ID)
    if tag_name is None:
        return parent
    normalized = tag_name.upper()
    local_name = (
        standardized_output_name(normalized)
        if normalized in STANDARD_SIMPLE_TAGS
        else generated_output_name(normalized)
    )
    if parent is not None and parent.tag_id == "COUNTRY":
        tag_id = normalized
        routed_name = local_name
    else:
        tag_id = f"{parent.tag_id}/{normalized}" if parent is not None else normalized
        routed_name = f"{parent.routed_name}/{local_name}" if parent is not None else local_name
    language = simple_tag_text_child(elements, data, children, TAG_LANGUAGE_ID)
    if language is None and parent is not None:
        language = parent.language
    country = None if parent is None else parent.country
    value = simple_tag_text_child(elements, data, children, TAG_STRING_ID)
    if normalized == "COUNTRY" and value is not None:
        country = value
        tag_id = "" if parent is None else parent.tag_id
        routed_name = "" if parent is None else parent.routed_name
    return MatroskaSimpleTagContext(tag_id, routed_name, language, country)


def simple_tag_direct_children(
    elements: tuple[MatroskaEbmlElementPlan, ...],
    simple_tag: MatroskaEbmlElementPlan,
) -> list[MatroskaEbmlElementPlan]:
    if simple_tag.end_offset is None:
        return []
    direct_children: list[MatroskaEbmlElementPlan] = []
    for element in elements:
        if element.payload_size is None:
            continue
        if element.offset <= simple_tag.offset or element.end_offset is None:
            continue
        if element.end_offset > simple_tag.end_offset:
            continue
        if has_containing_nested_simple_tag(elements, simple_tag, element):
            continue
        direct_children.append(element)
    return direct_children


def has_containing_nested_simple_tag(
    elements: tuple[MatroskaEbmlElementPlan, ...],
    simple_tag: MatroskaEbmlElementPlan,
    child: MatroskaEbmlElementPlan,
) -> bool:
    if child.end_offset is None:
        return False
    for candidate in elements:
        if candidate.element_id != SIMPLE_TAG_ID or candidate.end_offset is None:
            continue
        if candidate.offset <= simple_tag.offset:
            continue
        if candidate.offset >= child.offset:
            continue
        if candidate.end_offset >= child.end_offset:
            return True
    return False


def simple_tag_text_child(
    elements: tuple[MatroskaEbmlElementPlan, ...],
    data: bytes,
    children: list[MatroskaEbmlElementPlan],
    element_id: int,
) -> str | None:
    for child in children:
        if child.element_id != element_id:
            continue
        payload = data[child.payload_offset : child.payload_offset + (child.payload_size or 0)]
        return decode_ebml_text(payload)
    return None


def simple_tag_language_code(language: str | None, country: str | None) -> str | None:
    if country is not None:
        if language:
            return f"{language}-{country}"
        return f"eng-{country}"
    return language


def localized_simple_tag_name(name: str, language_code: str | None) -> str:
    if language_code:
        return f"{name}-{language_code}"
    return name


def extract_scalar_values(
    elements: tuple[MatroskaEbmlElementPlan, ...],
    data: bytes,
) -> tuple[MatroskaScalarPlan, ...]:
    scalars: list[MatroskaScalarPlan] = []
    timecode_scale = 0
    for element in elements:
        if element.payload_size is None or element.element_id not in SCALAR_FORMATS:
            continue
        payload = data[element.payload_offset : element.payload_offset + element.payload_size]
        format_name = SCALAR_FORMATS[element.element_id]
        raw_value = decode_scalar_value(payload, format_name)
        if element.element_id == 0x0AD7B1 and isinstance(raw_value, int):
            timecode_scale = raw_value
        rendered_value = render_scalar_value(element.element_id, raw_value, timecode_scale)
        scalars.append(
            MatroskaScalarPlan(
                element_id=element.element_id,
                name=element.name,
                path=element.full_path,
                format_name=format_name,
                raw_value=raw_value,
                rendered_value=rendered_value,
                evidence_ids=scalar_sources(element.element_id),
            )
        )
    return tuple(scalars)


def element_action(
    element_id: int,
    is_master: bool,
    is_unknown: bool,
) -> MatroskaElementAction:
    if element_id == CLUSTER_ID:
        return "skip_cluster_payload"
    if element_id == VOID_ID:
        return "preserve_void"
    if is_unknown:
        return "preserve_unknown"
    if is_master:
        return "descend"
    return "preserve"


def element_sources(element_id: int, is_unknown: bool) -> tuple[str, ...]:
    if element_id == EBML_HEADER_ID:
        return (MATROSKA_HEADER_SOURCE, MATROSKA_VINT_SOURCE)
    if element_id in {
        SEGMENT_ID,
        INFO_ID,
        CHAPTER_TRANSLATE_ID,
        TRACKS_ID,
        TRACK_ENTRY_ID,
        TRACK_TRANSLATE_ID,
        VIDEO_ID,
        AUDIO_ID,
        CONTENT_ENCODINGS_ID,
        CONTENT_ENCODING_ID,
        CONTENT_COMPRESSION_ID,
        CONTENT_ENCRYPTION_ID,
        ATTACHMENTS_ID,
        ATTACHED_FILE_ID,
        CHAPTERS_ID,
        EDITION_ENTRY_ID,
        CHAPTER_ATOM_ID,
        CHAPTER_PROCESS_ID,
        CHAPTER_PROCESS_COMMAND_ID,
        TAGS_ID,
        TAG_ID,
        TARGETS_ID,
        SIMPLE_TAG_ID,
        CLUSTER_ID,
    }:
        return (MATROSKA_TRAVERSAL_SOURCE, MATROSKA_TAG_TABLE_SOURCE)
    if element_id in {TAG_NAME_ID, TAG_LANGUAGE_ID, TAG_DEFAULT_ID, TAG_STRING_ID, TAG_BINARY_ID}:
        return (MATROSKA_TAG_TABLE_SOURCE, MATROSKA_SIMPLE_TAG_SOURCE)
    if is_unknown:
        return (MATROSKA_SKIP_SOURCE,)
    return (MATROSKA_TRAVERSAL_SOURCE,)


def scalar_sources(element_id: int) -> tuple[str, ...]:
    if element_id in {0x0AD7B1, 0x0489, 0x0461, 0x03BA9, 0x0D80, 0x1741}:
        return (MATROSKA_TAG_TABLE_SOURCE, MATROSKA_INFO_SCALAR_SOURCE)
    return (MATROSKA_TAG_TABLE_SOURCE,)


def default_responsibilities() -> tuple[MatroskaTraversalResponsibility, ...]:
    return (
        MatroskaTraversalResponsibility(
            1,
            "ebml_header_validation",
            "Require the EBML header ID and a finite positive EBML header payload.",
            ("header.is_valid", "header.payload_end_offset"),
            (MATROSKA_HEADER_SOURCE,),
        ),
        MatroskaTraversalResponsibility(
            2,
            "vint_element_id_and_size",
            "Decode element IDs and sizes as EBML VInts with marker bits stripped.",
            ("elements[].element_id", "elements[].payload_size"),
            (MATROSKA_VINT_SOURCE,),
        ),
        MatroskaTraversalResponsibility(
            3,
            "scalar_value_extraction",
            (
                "Decode deterministic EBML scalar values from source-defined "
                "unsigned, string, utf8, float, and date formats."
            ),
            ("scalars",),
            (MATROSKA_TAG_TABLE_SOURCE, MATROSKA_INFO_SCALAR_SOURCE),
        ),
        MatroskaTraversalResponsibility(
            4,
            "segment_info_tags_traversal",
            "Walk Segment, Info, and Tags masters while skipping Cluster media payloads.",
            ("full_paths", "skip_cluster_payload"),
            (MATROSKA_TRAVERSAL_SOURCE,),
        ),
        MatroskaTraversalResponsibility(
            5,
            "tag_metadata_routing",
            "Route Matroska SimpleTag writes through standardized or generated tag names.",
            ("simple_tags", "routes"),
            (MATROSKA_TAG_TABLE_SOURCE, MATROSKA_SIMPLE_TAG_SOURCE, MATROSKA_STD_TAG_SOURCE),
        ),
        MatroskaTraversalResponsibility(
            6,
            "unknown_element_preservation",
            "Preserve unknown EBML elements and unsupported payloads instead of decoding them.",
            ("preserve_unknown",),
            (MATROSKA_SKIP_SOURCE,),
        ),
        MatroskaTraversalResponsibility(
            7,
            "void_size_growth_blocker",
            "Require available Void space or a future full rebuild before growing metadata.",
            ("preserved_void_bytes", "estimated_size_delta"),
            (MATROSKA_SKIP_SOURCE, MATROSKA_OUTPUT_BOUNDARY_SOURCE),
        ),
        MatroskaTraversalResponsibility(
            8,
            "output_emission_gate",
            "Keep byte emission blocked until a complete EBML writer exists.",
            ("output_emission_gates",),
            (MATROSKA_OUTPUT_BOUNDARY_SOURCE,),
        ),
    )


def minimal_vint_length(value: int) -> int:
    if value < 0:
        raise ValueError("EBML VInt values must be non-negative.")
    for length in range(1, 9):
        max_value = 1 << (7 * length)
        if value < max_value - 1:
            return length
    raise ValueError(f"Value {value} is too large for an EBML VInt.")


def decode_ebml_text(payload: bytes) -> str:
    return payload.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def decode_scalar_value(payload: bytes, format_name: str) -> JsonValue:
    if format_name == "unsigned":
        return int.from_bytes(payload, "big")
    if format_name == "signed":
        return int.from_bytes(payload, "big", signed=True)
    if format_name in {"string", "utf8"}:
        return decode_ebml_text(payload)
    if format_name == "float":
        if len(payload) == 4:
            return float(struct.unpack(">f", payload)[0])
        if len(payload) == 8:
            return float(struct.unpack(">d", payload)[0])
        return payload.hex()
    if format_name == "date":
        return int.from_bytes(payload, "big", signed=True)
    return payload.hex()


def render_scalar_value(element_id: int, raw_value: JsonValue, timecode_scale: int) -> JsonValue:
    if element_id == 0x0AD7B1 and isinstance(raw_value, int):
        return raw_value / 1_000_000
    if element_id == 0x0489 and isinstance(raw_value, (int, float)):
        if timecode_scale:
            return raw_value * timecode_scale / 1_000_000_000
        return raw_value / 1000
    return raw_value


def value_length(value: str | bytes | None) -> int:
    if value is None:
        return 0
    if isinstance(value, bytes):
        return len(value)
    return len(value.encode("utf-8"))


def standardized_output_name(tag_name: str) -> str:
    return STANDARD_SIMPLE_TAG_OUTPUT_NAMES.get(
        tag_name,
        "".join(part.capitalize() for part in tag_name.lower().split("_")),
    )


def generated_output_name(tag_name: str) -> str:
    cleaned = "".join(
        char for char in tag_name.lower().capitalize() if char.isalnum() or char == "_"
    )
    generated = "".join(part.capitalize() for part in cleaned.split("_"))
    return generated if len(generated) >= 2 else f"Tag_{generated}"


def value_to_json(value: str | bytes | None) -> str | None:
    if isinstance(value, bytes):
        return value.hex()
    return value


def unique_gates(gates: tuple[MatroskaEmissionGate, ...]) -> tuple[MatroskaEmissionGate, ...]:
    seen: set[MatroskaEmissionGateCode] = set()
    unique: list[MatroskaEmissionGate] = []
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
