"""Source-grounded Unknown maker-note metadata transaction planning.

ExifTool's Unknown.pm defines a MakerNotes/MakerUnknown/Camera table for
unknown manufacturers whose maker notes are in standard IFD format. This
planner classifies those IFD entries, preserves raw payload bytes, and records
rewrite gates without owning EXIF byte emission.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.jpeg.container import (
    read_exif_app1,
    tiff_ascii_tag_value,
    tiff_entry_raw_value_location,
)
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_BYTE,
    TIFF_TYPE_UNDEFINED,
    Endian,
    Ifd,
    parse_ifd,
    parse_tiff_header,
)
from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.write_plan import EvidenceAnchor

UNKNOWN_PM_SOURCE_PATH = "lib/Image/ExifTool/Unknown.pm"
MAKER_NOTES_PM_SOURCE_PATH = "lib/Image/ExifTool/MakerNotes.pm"
UNKNOWN_IFD_ENTRY_SIZE = 12
UNKNOWN_IFD_COUNT_SIZE = 2
UNKNOWN_IFD_NEXT_POINTER_SIZE = 4
UNKNOWN_INLINE_VALUE_SIZE = 4
UNKNOWN_MAX_IFD_ENTRY_COUNT = 4096
UNKNOWN_IFD_LOCATE_SEARCH_BYTES = 32
UNKNOWN_RENDER_PREFIX_BYTES = 36
PRINT_IM_TAG_ID = 0x0E00

type UnknownByteOrder = Literal["little", "big"]
type UnknownPlanStatus = Literal["planned", "unsupported"]
type UnknownJpegReadStatus = Literal[
    "planned",
    "missing",
    "unsupported",
]
type UnknownGroup0 = Literal["MakerNotes"]
type UnknownGroup1 = Literal["MakerUnknown"]
type UnknownGroup2 = Literal["Camera"]
type UnknownTagRoute = Literal["print_im_subdirectory", "unknown_maker_note_tag"]
type UnknownValueClass = Literal["print_im_subdirectory", "unknown_preserved"]
type UnknownActionKind = Literal[
    "route_standard_ifd",
    "route_print_im_subdirectory",
    "preserve_unknown_maker_note_tag",
    "preserve_tag_payload",
    "block_requested_rewrite",
    "no_metadata_mutation",
]
type UnknownGateCode = Literal[
    "unsupported_byte_order",
    "truncated_unknown_ifd_count",
    "invalid_unknown_ifd_entry_count",
    "truncated_unknown_ifd_entry_table",
    "truncated_unknown_ifd_next_pointer",
    "invalid_unknown_ifd_value_offset",
    "truncated_unknown_ifd_value",
    "unsupported_unknown_rewrite",
    "non_mutating_plan_requires_explicit_emission",
]
type UnknownResponsibilityConcern = Literal[
    "standard_ifd_route_classification",
    "maker_unknown_group_classification",
    "print_im_subdirectory_routing",
    "unknown_tag_payload_preservation",
    "malformed_ifd_blockers",
    "unsupported_rewrite_gates",
]
type UnknownRewriteOperation = Literal["insert", "replace", "delete"]

UNKNOWN_DESCRIPTION_ANCHOR = EvidenceAnchor(
    path=UNKNOWN_PM_SOURCE_PATH,
    line_start=46,
    line_end=52,
    symbol="Unknown.pm DESCRIPTION",
    evidence=(
        "Unknown maker notes can sometimes be extracted when unknown manufacturer "
        "maker notes are in standard IFD format."
    ),
)
UNKNOWN_MAIN_TABLE_ANCHOR = EvidenceAnchor(
    path=UNKNOWN_PM_SOURCE_PATH,
    line_start=17,
    line_end=21,
    symbol="%Image::ExifTool::Unknown::Main",
    evidence=(
        "The Unknown table declares EXIF write/check procedures and "
        "MakerNotes/MakerUnknown/Camera groups."
    ),
)
UNKNOWN_PRINT_IM_ANCHOR = EvidenceAnchor(
    path=UNKNOWN_PM_SOURCE_PATH,
    line_start=23,
    line_end=30,
    symbol="0x0e00 PrintIM",
    evidence=(
        "Unknown.pm routes common unknown maker-note tag 0x0e00 to the "
        "Image::ExifTool::PrintIM::Main subdirectory."
    ),
)
UNKNOWN_EXIF_WRITE_ANCHOR = EvidenceAnchor(
    path=UNKNOWN_PM_SOURCE_PATH,
    line_start=18,
    line_end=20,
    symbol="WRITE_PROC/CHECK_PROC",
    evidence=(
        "Unknown.pm delegates writing and validation to Exif::WriteExif and "
        "Exif::CheckExif; this transaction slice does not implement that writer."
    ),
)
UNKNOWN_MAKER_NOTE_FALLBACK_ANCHOR = EvidenceAnchor(
    path=MAKER_NOTES_PM_SOURCE_PATH,
    line_start=1110,
    line_end=1127,
    symbol="MakerNoteUnknown fallback",
    evidence=(
        "MakerNotes.pm routes unmatched maker-note payloads to "
        "Image::ExifTool::Unknown::Main through ProcessUnknownOrPreview."
    ),
)
UNKNOWN_LOCATE_IFD_ANCHOR = EvidenceAnchor(
    path=MAKER_NOTES_PM_SOURCE_PATH,
    line_start=1494,
    line_end=1668,
    symbol="LocateIFD",
    evidence=(
        "LocateIFD scans the first 32 maker-note bytes for a standard IFD and "
        "then ProcessUnknown calls Exif::ProcessExif on that directory."
    ),
)
UNKNOWN_T_ANCHOR = EvidenceAnchor(
    path="t/Unknown.t",
    line_start=20,
    line_end=32,
    symbol="Unknown.t tests 2-3",
    evidence=(
        "Unknown.t extracts Unknown.jpg with Unknown=>1 and writes FocalLength=200 for test 3."
    ),
)

UNKNOWN_TRANSACTION_ANCHORS = (
    UNKNOWN_DESCRIPTION_ANCHOR,
    UNKNOWN_MAIN_TABLE_ANCHOR,
    UNKNOWN_PRINT_IM_ANCHOR,
    UNKNOWN_EXIF_WRITE_ANCHOR,
)
UNKNOWN_JPEG_READ_ANCHORS = (
    UNKNOWN_T_ANCHOR,
    UNKNOWN_MAIN_TABLE_ANCHOR,
    UNKNOWN_MAKER_NOTE_FALLBACK_ANCHOR,
    UNKNOWN_LOCATE_IFD_ANCHOR,
)
UNKNOWN_TAG_ROUTES: tuple[UnknownTagRoute, ...] = (
    "print_im_subdirectory",
    "unknown_maker_note_tag",
)


@dataclass(frozen=True)
class UnknownMetadataRewriteRequest:
    tag_id: int
    operation: UnknownRewriteOperation
    raw_payload: bytes | None = None


@dataclass(frozen=True)
class UnknownByteRange:
    start: int
    end: int
    reason: str

    def to_json(self) -> JsonObject:
        return {"end": self.end, "reason": self.reason, "start": self.start}


@dataclass(frozen=True)
class UnknownIfdEntryPlan:
    index: int
    tag_id: int
    tag_name: str
    group0: UnknownGroup0
    group1: UnknownGroup1
    group2: UnknownGroup2
    field_type: int
    value_count: int
    value_size: int
    entry_range: UnknownByteRange
    value_range: UnknownByteRange
    raw_payload: bytes
    payload_is_inline: bool
    route: UnknownTagRoute
    value_class: UnknownValueClass
    preserved: bool
    evidence_anchors: tuple[EvidenceAnchor, ...]

    @property
    def is_unknown(self) -> bool:
        return self.route == "unknown_maker_note_tag"

    def to_json(self) -> JsonObject:
        return {
            "entry_range": self.entry_range.to_json(),
            "field_type": self.field_type,
            "group0": self.group0,
            "group1": self.group1,
            "group2": self.group2,
            "index": self.index,
            "is_unknown": self.is_unknown,
            "payload_is_inline": self.payload_is_inline,
            "preserved": self.preserved,
            "raw_payload_hex": self.raw_payload.hex(),
            "route": self.route,
            "tag_id": self.tag_id,
            "tag_name": self.tag_name,
            "value_class": self.value_class,
            "value_count": self.value_count,
            "value_range": self.value_range.to_json(),
            "value_size": self.value_size,
        }


@dataclass(frozen=True)
class UnknownIfdRoutingPlan:
    table: str
    byte_order: UnknownByteOrder
    ifd_start: int
    entry_count: int
    next_ifd_offset: int
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_order": self.byte_order,
            "entry_count": self.entry_count,
            "ifd_start": self.ifd_start,
            "next_ifd_offset": self.next_ifd_offset,
            "table": self.table,
        }


@dataclass(frozen=True)
class UnknownPayloadPreservationPlan:
    tag_id: int
    tag_name: str
    value_range: UnknownByteRange
    raw_payload: bytes
    reason: str
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "raw_payload_hex": self.raw_payload.hex(),
            "reason": self.reason,
            "tag_id": self.tag_id,
            "tag_name": self.tag_name,
            "value_range": self.value_range.to_json(),
        }


@dataclass(frozen=True)
class UnknownResponsibilityPlan:
    concern: UnknownResponsibilityConcern
    reason: str
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class UnknownActionPlan:
    kind: UnknownActionKind
    target: str
    byte_range: UnknownByteRange | None
    reason: str
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": self.byte_range.to_json() if self.byte_range is not None else None,
            "kind": self.kind,
            "reason": self.reason,
            "target": self.target,
        }


@dataclass(frozen=True)
class UnknownOutputEmissionGate:
    code: UnknownGateCode
    reason: str
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class UnknownReadTag:
    tag_id: int
    tag_name: str
    group0: UnknownGroup0
    group1: UnknownGroup1
    group2: UnknownGroup2
    value: str
    raw_payload: bytes
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "group0": self.group0,
            "group1": self.group1,
            "group2": self.group2,
            "raw_payload_hex": self.raw_payload.hex(),
            "tag_id": self.tag_id,
            "tag_name": self.tag_name,
            "value": self.value,
        }


@dataclass(frozen=True)
class UnknownJpegReadReport:
    status: UnknownJpegReadStatus
    path: str
    maker_note_ifd_offset: int | None
    tags: tuple[UnknownReadTag, ...]
    diagnostics: tuple[str, ...]
    evidence_anchors: tuple[EvidenceAnchor, ...]

    @property
    def tag_names(self) -> tuple[str, ...]:
        return tuple(tag.tag_name for tag in self.tags)

    def to_json(self) -> JsonObject:
        tags: JsonArray = []
        for tag in self.tags:
            tags.append(tag.to_json())
        return {
            "diagnostics": list(self.diagnostics),
            "maker_note_ifd_offset": self.maker_note_ifd_offset,
            "path": self.path,
            "status": self.status,
            "tag_names": list(self.tag_names),
            "tags": tags,
        }


@dataclass(frozen=True)
class UnknownMetadataTransactionPlan:
    status: UnknownPlanStatus
    source_data: bytes
    routing: UnknownIfdRoutingPlan | None
    entries: tuple[UnknownIfdEntryPlan, ...]
    payload_preservations: tuple[UnknownPayloadPreservationPlan, ...]
    responsibilities: tuple[UnknownResponsibilityPlan, ...]
    actions: tuple[UnknownActionPlan, ...]
    output_emission_gates: tuple[UnknownOutputEmissionGate, ...]
    evidence_anchors: tuple[EvidenceAnchor, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def unknown_tag_ids(self) -> tuple[int, ...]:
        return tuple(entry.tag_id for entry in self.entries if entry.is_unknown)

    def entry(self, tag_id: int) -> UnknownIfdEntryPlan:
        for item in self.entries:
            if item.tag_id == tag_id:
                return item
        raise KeyError(hex(tag_id))

    def entries_by_route(self) -> dict[UnknownTagRoute, tuple[UnknownIfdEntryPlan, ...]]:
        return {
            route: tuple(entry for entry in self.entries if entry.route == route)
            for route in UNKNOWN_TAG_ROUTES
        }

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Unknown metadata transaction output is gated: {gate_codes}")
        return self.source_data

    def to_json(self) -> JsonObject:
        actions: JsonArray = []
        for action in self.actions:
            actions.append(action.to_json())
        entries: JsonArray = []
        for entry in self.entries:
            entries.append(entry.to_json())
        gates: JsonArray = []
        for gate in self.output_emission_gates:
            gates.append(gate.to_json())
        preservations: JsonArray = []
        for preservation in self.payload_preservations:
            preservations.append(preservation.to_json())
        responsibilities: JsonArray = []
        for responsibility in self.responsibilities:
            responsibilities.append(responsibility.to_json())
        return {
            "actions": actions,
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "entries": entries,
            "output_emission_gates": gates,
            "payload_preservations": preservations,
            "responsibilities": responsibilities,
            "routing": self.routing.to_json() if self.routing is not None else None,
            "status": self.status,
            "unknown_tag_ids": list(self.unknown_tag_ids),
        }


@dataclass(frozen=True)
class UnknownIfdParse:
    status: UnknownPlanStatus
    routing: UnknownIfdRoutingPlan | None
    entries: tuple[UnknownIfdEntryPlan, ...]
    gates: tuple[UnknownOutputEmissionGate, ...]


def build_unknown_metadata_transaction_plan(
    source_data: bytes,
    *,
    byte_order: UnknownByteOrder = "little",
    rewrite_requests: tuple[UnknownMetadataRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> UnknownMetadataTransactionPlan:
    """Build a non-mutating plan for an Unknown.pm standard-IFD maker note."""

    parse = parse_unknown_ifd(source_data, byte_order)
    gates = [*parse.gates, *rewrite_gates(rewrite_requests)]
    if not allow_output_emission:
        gates.append(
            UnknownOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="Unknown maker-note planning records routes and preservation only.",
                evidence_anchors=(UNKNOWN_EXIF_WRITE_ANCHOR,),
            )
        )
    actions = build_actions(parse.routing, parse.entries, rewrite_requests)
    payload_preservations = tuple(
        UnknownPayloadPreservationPlan(
            tag_id=entry.tag_id,
            tag_name=entry.tag_name,
            value_range=entry.value_range,
            raw_payload=entry.raw_payload,
            reason="Preserve raw maker-note payload bytes while classifying Unknown.pm routes.",
            evidence_anchors=entry.evidence_anchors,
        )
        for entry in parse.entries
    )

    return UnknownMetadataTransactionPlan(
        status=parse.status,
        source_data=source_data,
        routing=parse.routing,
        entries=parse.entries,
        payload_preservations=payload_preservations,
        responsibilities=build_responsibilities(),
        actions=actions,
        output_emission_gates=tuple(gates),
        evidence_anchors=UNKNOWN_TRANSACTION_ANCHORS,
    )


def build_unknown_jpeg_read_report(path: Path) -> UnknownJpegReadReport:
    """Classify bounded Unknown.pm maker-note tags from a JPEG EXIF APP1 payload."""

    try:
        exif = read_exif_app1(path)
        header = parse_tiff_header(exif.tiff_data)
        ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    except ValueError as exc:
        return unknown_jpeg_report(
            "missing",
            path,
            None,
            (),
            (f"Unknown maker-note read blocked before MakerNote discovery: {exc}",),
        )
    try:
        return build_unknown_jpeg_read_report_from_parsed_tiff(
            path,
            exif.tiff_data,
            ifd0,
            parse_unknown_exif_ifd(exif.tiff_data, ifd0, header.endian),
            header.endian,
        )
    except ValueError as exc:
        return unknown_jpeg_report(
            "unsupported",
            path,
            None,
            (),
            (f"ExifIFD parsing blocked unknown maker-note fallback discovery: {exc}",),
        )


def parse_unknown_exif_ifd(tiff_data: bytes, ifd0: Ifd, endian: Endian) -> Ifd:
    exif_ifd_pointer = next((entry for entry in ifd0.entries if entry.tag_id == 0x8769), None)
    if exif_ifd_pointer is None:
        raise ValueError("IFD0 does not contain an ExifIFD pointer for MakerNote discovery.")
    return parse_ifd(tiff_data, exif_ifd_pointer.value_offset, endian)


def build_unknown_jpeg_read_report_from_parsed_tiff(
    path: Path,
    tiff_data: bytes,
    ifd0: Ifd,
    exif_ifd: Ifd,
    endian: Endian,
) -> UnknownJpegReadReport:
    make = tiff_ascii_tag_value(tiff_data, ifd0.entries, 0x010F, endian) or ""
    if _known_vendor_maker_note_make(make):
        return unknown_jpeg_report(
            "missing",
            path,
            None,
            (),
            (
                "MakerNoteUnknown fallback is not selected because IFD0 Make matches a "
                f"bounded vendor maker-note reader: {make.strip()}",
            ),
        )
    maker_note_entry = next((entry for entry in exif_ifd.entries if entry.tag_id == 0x927C), None)
    if maker_note_entry is None:
        return unknown_jpeg_report(
            "missing",
            path,
            None,
            (),
            ("ExifIFD does not contain MakerNote tag 0x927c.",),
        )
    if maker_note_entry.field_type not in {TIFF_TYPE_UNDEFINED, TIFF_TYPE_BYTE}:
        return unknown_jpeg_report(
            "unsupported",
            path,
            None,
            (),
            (
                f"MakerNote tag 0x927c uses unsupported TIFF field type "
                f"{maker_note_entry.field_type}.",
            ),
        )
    raw_location = tiff_entry_raw_value_location(tiff_data, maker_note_entry, endian)
    if raw_location is None:
        return unknown_jpeg_report(
            "unsupported",
            path,
            None,
            (),
            ("MakerNote tag 0x927c value points outside the TIFF APP1 payload.",),
        )
    _, raw_maker_note = raw_location
    locate = locate_unknown_ifd(raw_maker_note, endian)
    if locate is None:
        return unknown_jpeg_report(
            "unsupported",
            path,
            None,
            (),
            (
                "MakerNoteUnknown fallback reached a maker-note payload, but did not find "
                "a standard IFD in the first 32 maker-note bytes.",
            ),
        )
    ifd_offset, _ = locate
    parse = parse_unknown_ifd_at(
        raw_maker_note,
        ifd_offset,
        endian,
        value_offset_base=ifd_offset,
    )
    if parse.status != "planned":
        return unknown_jpeg_report(
            "unsupported",
            path,
            ifd_offset,
            (),
            tuple(gate.reason for gate in parse.gates),
        )
    tags = tuple(unknown_read_tag_from_entry(entry) for entry in parse.entries if entry.is_unknown)
    return unknown_jpeg_report(
        "planned",
        path,
        ifd_offset,
        tags,
        (
            "MakerNoteUnknown fallback located "
            f"a standard IFD at maker-note offset {ifd_offset} and exposed "
            f"{len(tags)} MakerUnknown tags for public/API promotion.",
        ),
    )


def locate_unknown_ifd(
    raw_maker_note: bytes,
    byte_order: UnknownByteOrder,
) -> tuple[int, bytes] | None:
    last_offset = min(UNKNOWN_IFD_LOCATE_SEARCH_BYTES, max(len(raw_maker_note) - 14, 0))
    for offset in range(0, last_offset + 1, 2):
        if looks_like_unknown_ifd(raw_maker_note[offset:], byte_order):
            return offset, raw_maker_note[offset:]
    return None


def looks_like_unknown_ifd(source_data: bytes, byte_order: UnknownByteOrder) -> bool:
    if len(source_data) < UNKNOWN_IFD_COUNT_SIZE + UNKNOWN_IFD_ENTRY_SIZE:
        return False
    entry_count = int.from_bytes(source_data[:UNKNOWN_IFD_COUNT_SIZE], byte_order)
    if entry_count < 1 or entry_count > 255:
        return False
    table_end = UNKNOWN_IFD_COUNT_SIZE + entry_count * UNKNOWN_IFD_ENTRY_SIZE
    if len(source_data) < table_end:
        return False
    bytes_from_end = len(source_data) - table_end
    if bytes_from_end < UNKNOWN_IFD_NEXT_POINTER_SIZE and bytes_from_end not in {0, 2}:
        return False
    for index in range(entry_count):
        entry_start = UNKNOWN_IFD_COUNT_SIZE + index * UNKNOWN_IFD_ENTRY_SIZE
        field_type = int.from_bytes(source_data[entry_start + 2 : entry_start + 4], byte_order)
        value_count = int.from_bytes(source_data[entry_start + 4 : entry_start + 8], byte_order)
        if field_type < 1 or field_type > 13:
            return False
        if value_count & 0xFF000000:
            return False
        value_size = unknown_ifd_value_size(field_type, value_count)
        if value_size > 4:
            value_offset = int.from_bytes(
                source_data[entry_start + 8 : entry_start + 12],
                byte_order,
            )
            if value_offset > 0x10000 or value_offset + value_size > len(source_data):
                return False
    return True


def unknown_read_tag_from_entry(entry: UnknownIfdEntryPlan) -> UnknownReadTag:
    return UnknownReadTag(
        tag_id=entry.tag_id,
        tag_name=entry.tag_name,
        group0=entry.group0,
        group1=entry.group1,
        group2=entry.group2,
        value=render_unknown_payload(entry.raw_payload),
        raw_payload=entry.raw_payload,
        evidence_anchors=entry.evidence_anchors,
    )


def render_unknown_payload(raw_payload: bytes) -> str:
    if not raw_payload:
        return ""
    clipped = len(raw_payload) > UNKNOWN_RENDER_PREFIX_BYTES
    prefix = raw_payload[:UNKNOWN_RENDER_PREFIX_BYTES] if clipped else raw_payload
    rendered = "".join(render_unknown_byte(byte) for byte in prefix).rstrip("\x00")
    if clipped:
        return f"{rendered}[...]"
    return rendered


def render_unknown_byte(byte: int) -> str:
    if byte == 0:
        return ""
    if 32 <= byte <= 126:
        return chr(byte)
    return "."


def unknown_jpeg_report(
    status: UnknownJpegReadStatus,
    path: Path,
    maker_note_ifd_offset: int | None,
    tags: tuple[UnknownReadTag, ...],
    diagnostics: tuple[str, ...],
) -> UnknownJpegReadReport:
    return UnknownJpegReadReport(
        status=status,
        path=path.as_posix(),
        maker_note_ifd_offset=maker_note_ifd_offset,
        tags=tags,
        diagnostics=diagnostics,
        evidence_anchors=UNKNOWN_JPEG_READ_ANCHORS,
    )


def _known_vendor_maker_note_make(make: str) -> bool:
    normalized = make.upper()
    return normalized.startswith(
        (
            "APPLE",
            "CANON",
            "FUJI",
            "MINOLTA",
            "NIKON",
            "OLYMPUS",
            "EPSON",
            "PANASONIC",
            "PENTAX",
            "SONY",
        )
    )


def parse_unknown_ifd(source_data: bytes, byte_order: UnknownByteOrder) -> UnknownIfdParse:
    return parse_unknown_ifd_at(source_data, 0, byte_order)


def parse_unknown_ifd_at(
    source_data: bytes,
    ifd_start: int,
    byte_order: UnknownByteOrder,
    value_offset_base: int = 0,
) -> UnknownIfdParse:
    if byte_order not in ("little", "big"):
        return unsupported_parse("unsupported_byte_order", "Unknown byte order is not supported.")
    if ifd_start < 0 or ifd_start + UNKNOWN_IFD_COUNT_SIZE > len(source_data):
        return unsupported_parse(
            "truncated_unknown_ifd_count",
            "Standard IFD entry count is truncated.",
        )

    entry_count = int.from_bytes(
        source_data[ifd_start : ifd_start + UNKNOWN_IFD_COUNT_SIZE],
        byte_order,
    )
    if entry_count > UNKNOWN_MAX_IFD_ENTRY_COUNT:
        return unsupported_parse(
            "invalid_unknown_ifd_entry_count",
            "Standard IFD entry count exceeds the planner safety limit.",
        )

    entries_start = ifd_start + UNKNOWN_IFD_COUNT_SIZE
    entries_end = entries_start + entry_count * UNKNOWN_IFD_ENTRY_SIZE
    next_ifd_end = entries_end + UNKNOWN_IFD_NEXT_POINTER_SIZE
    if len(source_data) < entries_end:
        return unsupported_parse(
            "truncated_unknown_ifd_entry_table",
            "Standard IFD entry table is truncated.",
        )
    if len(source_data) < next_ifd_end:
        return unsupported_parse(
            "truncated_unknown_ifd_next_pointer",
            "Standard IFD next-pointer field is truncated.",
        )

    next_ifd_offset = int.from_bytes(source_data[entries_end:next_ifd_end], byte_order)
    entries: list[UnknownIfdEntryPlan] = []
    for index in range(entry_count):
        entry_start = entries_start + index * UNKNOWN_IFD_ENTRY_SIZE
        entry_end = entry_start + UNKNOWN_IFD_ENTRY_SIZE
        parsed_entry = parse_unknown_ifd_entry(
            source_data,
            byte_order,
            index,
            entry_start,
            entry_end,
            value_offset_base,
        )
        if isinstance(parsed_entry, UnknownOutputEmissionGate):
            return UnknownIfdParse(
                status="unsupported",
                routing=None,
                entries=tuple(entries),
                gates=(parsed_entry,),
            )
        entries.append(parsed_entry)

    routing = UnknownIfdRoutingPlan(
        table="Image::ExifTool::Unknown::Main",
        byte_order=byte_order,
        ifd_start=ifd_start,
        entry_count=entry_count,
        next_ifd_offset=next_ifd_offset,
        evidence_anchors=(UNKNOWN_DESCRIPTION_ANCHOR, UNKNOWN_MAIN_TABLE_ANCHOR),
    )
    return UnknownIfdParse(status="planned", routing=routing, entries=tuple(entries), gates=())


def parse_unknown_ifd_entry(
    source_data: bytes,
    byte_order: UnknownByteOrder,
    index: int,
    entry_start: int,
    entry_end: int,
    value_offset_base: int = 0,
) -> UnknownIfdEntryPlan | UnknownOutputEmissionGate:
    entry_data = source_data[entry_start:entry_end]
    tag_id = int.from_bytes(entry_data[:2], byte_order)
    field_type = int.from_bytes(entry_data[2:4], byte_order)
    value_count = int.from_bytes(entry_data[4:8], byte_order)
    value_size = unknown_ifd_value_size(field_type, value_count)
    value_field = entry_data[8:12]

    if value_size <= UNKNOWN_INLINE_VALUE_SIZE:
        payload_is_inline = True
        value_start = entry_start + 8
        value_end = value_start + value_size
    else:
        payload_is_inline = False
        value_offset = int.from_bytes(value_field, byte_order) + value_offset_base
        if value_offset < 0 or value_offset > len(source_data):
            return UnknownOutputEmissionGate(
                code="invalid_unknown_ifd_value_offset",
                reason=f"Tag 0x{tag_id:04x} value offset is outside the source payload.",
                evidence_anchors=(UNKNOWN_DESCRIPTION_ANCHOR, UNKNOWN_MAIN_TABLE_ANCHOR),
            )
        value_start = value_offset
        value_end = value_offset + value_size
        if value_end > len(source_data):
            return UnknownOutputEmissionGate(
                code="truncated_unknown_ifd_value",
                reason=f"Tag 0x{tag_id:04x} external value extends beyond source payload.",
                evidence_anchors=(UNKNOWN_DESCRIPTION_ANCHOR, UNKNOWN_MAIN_TABLE_ANCHOR),
            )

    route, tag_name, value_class, references = classify_unknown_entry(tag_id)
    value_range = UnknownByteRange(value_start, value_end, "raw IFD value payload")
    return UnknownIfdEntryPlan(
        index=index,
        tag_id=tag_id,
        tag_name=tag_name,
        group0="MakerNotes",
        group1="MakerUnknown",
        group2="Camera",
        field_type=field_type,
        value_count=value_count,
        value_size=value_size,
        entry_range=UnknownByteRange(entry_start, entry_end, "standard IFD entry"),
        value_range=value_range,
        raw_payload=source_data[value_start:value_end],
        payload_is_inline=payload_is_inline,
        route=route,
        value_class=value_class,
        preserved=True,
        evidence_anchors=references,
    )


def classify_unknown_entry(
    tag_id: int,
) -> tuple[UnknownTagRoute, str, UnknownValueClass, tuple[EvidenceAnchor, ...]]:
    if tag_id == PRINT_IM_TAG_ID:
        return (
            "print_im_subdirectory",
            "PrintIM",
            "print_im_subdirectory",
            (UNKNOWN_MAIN_TABLE_ANCHOR, UNKNOWN_PRINT_IM_ANCHOR),
        )
    return (
        "unknown_maker_note_tag",
        f"Unknown_0x{tag_id:04x}",
        "unknown_preserved",
        (UNKNOWN_MAIN_TABLE_ANCHOR, UNKNOWN_DESCRIPTION_ANCHOR),
    )


def unknown_ifd_value_size(field_type: int, value_count: int) -> int:
    unit_size = {
        1: 1,
        2: 1,
        3: 2,
        4: 4,
        5: 8,
        6: 1,
        7: 1,
        8: 2,
        9: 4,
        10: 8,
        11: 4,
        12: 8,
    }.get(field_type, 1)
    return unit_size * value_count


def build_actions(
    routing: UnknownIfdRoutingPlan | None,
    entries: tuple[UnknownIfdEntryPlan, ...],
    rewrite_requests: tuple[UnknownMetadataRewriteRequest, ...],
) -> tuple[UnknownActionPlan, ...]:
    actions: list[UnknownActionPlan] = []
    if routing is not None:
        actions.append(
            UnknownActionPlan(
                kind="route_standard_ifd",
                target=routing.table,
                byte_range=UnknownByteRange(
                    0,
                    len(entries) * UNKNOWN_IFD_ENTRY_SIZE,
                    "IFD entries",
                ),
                reason="Unknown.pm reads unknown manufacturer maker notes in standard IFD format.",
                evidence_anchors=(UNKNOWN_DESCRIPTION_ANCHOR, UNKNOWN_MAIN_TABLE_ANCHOR),
            )
        )
    for entry in entries:
        if entry.route == "print_im_subdirectory":
            actions.append(
                UnknownActionPlan(
                    kind="route_print_im_subdirectory",
                    target=entry.tag_name,
                    byte_range=entry.value_range,
                    reason="Unknown.pm routes tag 0x0e00 to the PrintIM subdirectory.",
                    evidence_anchors=(UNKNOWN_PRINT_IM_ANCHOR,),
                )
            )
        else:
            actions.append(
                UnknownActionPlan(
                    kind="preserve_unknown_maker_note_tag",
                    target=entry.tag_name,
                    byte_range=entry.value_range,
                    reason="Unknown.pm has no tag definition for this maker-note entry.",
                    evidence_anchors=(UNKNOWN_DESCRIPTION_ANCHOR, UNKNOWN_MAIN_TABLE_ANCHOR),
                )
            )
        actions.append(
            UnknownActionPlan(
                kind="preserve_tag_payload",
                target=entry.tag_name,
                byte_range=entry.value_range,
                reason="Raw payload bytes remain owned by the surrounding EXIF transaction.",
                evidence_anchors=entry.evidence_anchors,
            )
        )
    for request in rewrite_requests:
        actions.append(
            UnknownActionPlan(
                kind="block_requested_rewrite",
                target=f"{request.operation}:0x{request.tag_id:04x}",
                byte_range=None,
                reason="This slice does not implement Unknown.pm's delegated EXIF writer.",
                evidence_anchors=(UNKNOWN_EXIF_WRITE_ANCHOR,),
            )
        )
    if not rewrite_requests:
        actions.append(
            UnknownActionPlan(
                kind="no_metadata_mutation",
                target="Unknown maker-note payload",
                byte_range=UnknownByteRange(0, 0, "no requested mutation"),
                reason="Default transaction plans preserve input bytes.",
                evidence_anchors=(UNKNOWN_EXIF_WRITE_ANCHOR,),
            )
        )
    return tuple(actions)


def build_responsibilities() -> tuple[UnknownResponsibilityPlan, ...]:
    return (
        UnknownResponsibilityPlan(
            concern="standard_ifd_route_classification",
            reason="Classify only the standard IFD surface described by Unknown.pm.",
            evidence_anchors=(UNKNOWN_DESCRIPTION_ANCHOR,),
        ),
        UnknownResponsibilityPlan(
            concern="maker_unknown_group_classification",
            reason="Unknown.pm assigns MakerNotes, MakerUnknown, and Camera groups.",
            evidence_anchors=(UNKNOWN_MAIN_TABLE_ANCHOR,),
        ),
        UnknownResponsibilityPlan(
            concern="print_im_subdirectory_routing",
            reason="Tag 0x0e00 routes to Image::ExifTool::PrintIM::Main.",
            evidence_anchors=(UNKNOWN_PRINT_IM_ANCHOR,),
        ),
        UnknownResponsibilityPlan(
            concern="unknown_tag_payload_preservation",
            reason="Unrecognized unknown manufacturer tags must keep their raw bytes.",
            evidence_anchors=(UNKNOWN_DESCRIPTION_ANCHOR, UNKNOWN_MAIN_TABLE_ANCHOR),
        ),
        UnknownResponsibilityPlan(
            concern="malformed_ifd_blockers",
            reason="Malformed standard IFD boundaries block byte emission.",
            evidence_anchors=(UNKNOWN_DESCRIPTION_ANCHOR, UNKNOWN_MAIN_TABLE_ANCHOR),
        ),
        UnknownResponsibilityPlan(
            concern="unsupported_rewrite_gates",
            reason="Unknown.pm delegates writing to EXIF writer code outside this slice.",
            evidence_anchors=(UNKNOWN_EXIF_WRITE_ANCHOR,),
        ),
    )


def rewrite_gates(
    rewrite_requests: tuple[UnknownMetadataRewriteRequest, ...],
) -> tuple[UnknownOutputEmissionGate, ...]:
    if not rewrite_requests:
        return ()
    return (
        UnknownOutputEmissionGate(
            code="unsupported_unknown_rewrite",
            reason=(
                "Unknown.pm delegates writing to Exif::WriteExif; this planner classifies "
                "and preserves Unknown maker-note payloads only."
            ),
            evidence_anchors=(UNKNOWN_EXIF_WRITE_ANCHOR,),
        ),
    )


def unsupported_parse(code: UnknownGateCode, reason: str) -> UnknownIfdParse:
    return UnknownIfdParse(
        status="unsupported",
        routing=None,
        entries=(),
        gates=(
            UnknownOutputEmissionGate(
                code=code,
                reason=reason,
                evidence_anchors=(UNKNOWN_DESCRIPTION_ANCHOR, UNKNOWN_MAIN_TABLE_ANCHOR),
            ),
        ),
    )


def evidence_anchors_to_json(references: tuple[EvidenceAnchor, ...]) -> JsonArray:
    items: JsonArray = []
    for reference in references:
        items.append(
            {
                "evidence": reference.evidence,
                "line_end": reference.line_end,
                "line_start": reference.line_start,
                "path": reference.path,
                "symbol": reference.symbol,
            }
        )
    return items


plan_unknown_metadata_transaction = build_unknown_metadata_transaction_plan
