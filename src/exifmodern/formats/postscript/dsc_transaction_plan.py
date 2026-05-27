"""Source-backed, non-mutating PostScript/EPS DSC transaction plans."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.json_types import JsonArray, JsonObject

POSTSCRIPT_PM_SOURCE_PATH = "lib/Image/ExifTool/PostScript.pm"
WRITE_POSTSCRIPT_SOURCE_PATH = "lib/Image/ExifTool/WritePostScript.pl"

DOS_BINARY_MAGIC = b"\xc5\xd0\xd3\xc6"
HEADER_PROBE_SIZE = 256
WINDOWS_LONG_LINE_LIMIT = 500_000
ENCODED_COMMENT_CONTINUATION_LIMIT = 254
MODELED_DSC_TAGS = frozenset(
    {
        "Author",
        "BoundingBox",
        "Copyright",
        "CreationDate",
        "Creator",
        "For",
        "ImageData",
        "Keywords",
        "ModDate",
        "Pages",
        "Routing",
        "Subject",
        "Title",
        "Version",
    }
)
WRITABLE_DSC_TAGS = frozenset(
    {
        "Author",
        "Copyright",
        "CreationDate",
        "Creator",
        "For",
        "Keywords",
        "ModDate",
        "Routing",
        "Subject",
        "Title",
        "Version",
    }
)

type PostScriptDocumentKind = Literal["ps", "eps", "ai", "dos_binary_ps", "unknown"]
type PostScriptPlanStatus = Literal["planned", "unsupported"]
type PostScriptNewlineKind = Literal["lf", "cr", "crlf", "lfcr", "unknown"]
type PostScriptDscActionKind = Literal[
    "validate_header",
    "parse_dsc_comment",
    "preserve_bounding_box",
    "plan_comment_write",
    "plan_comment_delete",
    "preserve_xmp_packet",
    "plan_xmp_create",
    "plan_xmp_replace",
    "plan_xmp_delete_as_blank_packet",
    "preserve_photoshop_resource",
    "preserve_icc_profile",
    "preserve_dos_preview_or_metafile",
    "preserve_embedded_document",
    "preserve_binary_block",
    "preserve_drawing_stream",
]
type PostScriptGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_header",
    "unsupported_postscript_signature",
    "truncated_dos_binary_header",
    "invalid_dos_binary_postscript_header",
    "invalid_postscript_newline",
    "dsc_header_line_missing",
    "dsc_version_unsupported",
    "unterminated_begin_end_block",
    "unterminated_xmp_packet",
    "long_mixed_newline_line_requires_streaming_split",
    "comment_write_requires_dsc_rewrite",
    "comment_delete_requires_dsc_rewrite",
    "bounding_box_write_not_writable",
    "xmp_create_requires_pdfmark_scaffolding",
    "xmp_replace_requires_packet_size_rewrite",
    "xmp_delete_writes_blank_packet",
    "photoshop_resource_rewrite_not_planned",
    "icc_profile_rewrite_not_planned",
    "dos_binary_header_rewrite_requires_seekable_output",
    "dcs_plate_file_offsets_block_directory_writes",
    "illustrator_creator_rewrite_blocked",
    "illustrator_xmp_write_blocked",
    "multiple_postscript_directories",
    "missing_requested_postscript_information",
]
type PostScriptRewriteBlockerCode = Literal[
    "dsc_rewrite_engine_not_emitting",
    "dsc_version_warning_required",
    "dcs_plate_file_offsets_block_directory_writes",
    "illustrator_creator_rewrite_blocked",
    "illustrator_xmp_write_blocked",
    "multiple_xmp_directories",
    "multiple_photoshop_directories",
    "multiple_icc_profile_directories",
    "unterminated_begin_end_block",
    "unterminated_xmp_packet",
    "dos_binary_header_rewrite_requires_seekable_output",
    "line_split_requires_alternate_newline_streaming",
]
type PostScriptDirectoryKind = Literal[
    "xmp",
    "photoshop",
    "icc_profile",
    "embedded_document",
    "binary",
    "unknown",
]

POSTSCRIPT_TAG_TABLE_SOURCE = "postscript.tag_table"
POSTSCRIPT_IMAGE_SIZE_SOURCE = "postscript.image_size"
POSTSCRIPT_HEADER_SOURCE = "postscript.header"
POSTSCRIPT_NEWLINE_SOURCE = "postscript.newline"
POSTSCRIPT_COMMENT_DECODE_SOURCE = "postscript.comment_decode"
POSTSCRIPT_PARSE_SOURCE = "postscript.parse"
POSTSCRIPT_NESTED_DISPATCH_SOURCE = "postscript.nested_dispatch"
POSTSCRIPT_PHOTOSHOP_SOURCE = "postscript.photoshop"
POSTSCRIPT_IPTC_SOURCE = "postscript.iptc"
POSTSCRIPT_XMP_SOURCE = "postscript.xmp"
POSTSCRIPT_ICC_SOURCE = "postscript.icc"
POSTSCRIPT_DOS_PREVIEW_SOURCE = "postscript.dos_preview"
WRITE_STRUCTURE_SOURCE = "postscript.write_structure"
WRITE_XMP_SOURCE = "postscript.write_xmp"
WRITE_RESOURCE_SOURCE = "postscript.write_resource"
WRITE_ENCODE_TAG_SOURCE = "postscript.write_encode_tag"
WRITE_HEADER_SOURCE = "postscript.write_header"
WRITE_LOOP_SOURCE = "postscript.write_loop"
WRITE_BLOCKER_SOURCE = "postscript.write_blocker"
WRITE_NOTES_SOURCE = "postscript.write_notes"

POSTSCRIPT_TRANSACTION_SOURCES = (
    POSTSCRIPT_TAG_TABLE_SOURCE,
    POSTSCRIPT_HEADER_SOURCE,
    POSTSCRIPT_NEWLINE_SOURCE,
    POSTSCRIPT_COMMENT_DECODE_SOURCE,
    POSTSCRIPT_PARSE_SOURCE,
    WRITE_STRUCTURE_SOURCE,
    WRITE_HEADER_SOURCE,
    WRITE_LOOP_SOURCE,
    WRITE_NOTES_SOURCE,
)


@dataclass(frozen=True)
class PostScriptDscHeaderPlan:
    document_kind: PostScriptDocumentKind
    signature: bytes
    ps_data_start: int
    ps_data_end: int | None
    dsc_header_line: str | None
    dsc_revision: int | None
    conforms_to_write_dsc_gate: bool
    newline_kind: PostScriptNewlineKind
    is_valid_postscript: bool
    reason: PostScriptGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "conforms_to_write_dsc_gate": self.conforms_to_write_dsc_gate,
            "document_kind": self.document_kind,
            "dsc_header_line": self.dsc_header_line,
            "dsc_revision": self.dsc_revision,
            "is_valid_postscript": self.is_valid_postscript,
            "newline_kind": self.newline_kind,
            "ps_data_end": self.ps_data_end,
            "ps_data_start": self.ps_data_start,
            "reason": self.reason,
            "signature_hex": self.signature.hex(),
        }


@dataclass(frozen=True)
class PostScriptDscCommentPlan:
    tag: str
    value: str
    decoded_value: str
    line_index: int
    byte_range_start: int
    byte_range_end: int
    writable_by_exiftool: bool
    priority_zero_first_wins: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range_end": self.byte_range_end,
            "byte_range_start": self.byte_range_start,
            "decoded_value": self.decoded_value,
            "line_index": self.line_index,
            "priority_zero_first_wins": self.priority_zero_first_wins,
            "tag": self.tag,
            "value": self.value,
            "writable_by_exiftool": self.writable_by_exiftool,
        }


@dataclass(frozen=True)
class PostScriptBoundingBoxPlan:
    raw_value: str | None
    coordinates: tuple[int, int, int, int] | None
    derived_width: int | None
    derived_height: int | None
    writable_by_exiftool: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        coordinates: JsonArray | None = (
            [value for value in self.coordinates] if self.coordinates is not None else None
        )
        return {
            "coordinates": coordinates,
            "derived_height": self.derived_height,
            "derived_width": self.derived_width,
            "raw_value": self.raw_value,
            "writable_by_exiftool": self.writable_by_exiftool,
        }


@dataclass(frozen=True)
class PostScriptDirectoryPlan:
    kind: PostScriptDirectoryKind
    begin_token: str
    end_token: str | None
    byte_range_start: int
    byte_range_end: int | None
    payload_length: int | None
    preserved: bool
    reason: PostScriptGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "begin_token": self.begin_token,
            "byte_range_end": self.byte_range_end,
            "byte_range_start": self.byte_range_start,
            "end_token": self.end_token,
            "kind": self.kind,
            "payload_length": self.payload_length,
            "preserved": self.preserved,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PostScriptXmpResponsibilityPlan:
    packet_count: int
    has_ado_contains_xmp_hint: bool
    can_rewrite_reported_packet_size: bool
    creation_requires_pdfmark_scaffolding: bool
    deletion_strategy: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_rewrite_reported_packet_size": self.can_rewrite_reported_packet_size,
            "creation_requires_pdfmark_scaffolding": self.creation_requires_pdfmark_scaffolding,
            "deletion_strategy": self.deletion_strategy,
            "has_ado_contains_xmp_hint": self.has_ado_contains_xmp_hint,
            "packet_count": self.packet_count,
        }


@dataclass(frozen=True)
class PostScriptPreservationPlan:
    has_dos_preview_or_metafile: bool
    photoshop_resource_count: int
    icc_profile_count: int
    embedded_document_count: int
    binary_block_count: int
    drawing_stream_start: int | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "binary_block_count": self.binary_block_count,
            "drawing_stream_start": self.drawing_stream_start,
            "embedded_document_count": self.embedded_document_count,
            "has_dos_preview_or_metafile": self.has_dos_preview_or_metafile,
            "icc_profile_count": self.icc_profile_count,
            "photoshop_resource_count": self.photoshop_resource_count,
        }


@dataclass(frozen=True)
class PostScriptDscActionPlan:
    kind: PostScriptDscActionKind
    target: str
    byte_range_start: int | None
    byte_range_end: int | None
    planned_payload_length: int | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range_end": self.byte_range_end,
            "byte_range_start": self.byte_range_start,
            "kind": self.kind,
            "planned_payload_length": self.planned_payload_length,
            "reason": self.reason,
            "target": self.target,
        }


@dataclass(frozen=True)
class PostScriptRewriteBlocker:
    code: PostScriptRewriteBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PostScriptOutputEmissionGate:
    code: PostScriptGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PostScriptDscTransactionPlan:
    status: PostScriptPlanStatus
    header: PostScriptDscHeaderPlan
    comments: tuple[PostScriptDscCommentPlan, ...]
    bounding_box: PostScriptBoundingBoxPlan
    directories: tuple[PostScriptDirectoryPlan, ...]
    xmp: PostScriptXmpResponsibilityPlan
    preservation: PostScriptPreservationPlan
    actions: tuple[PostScriptDscActionPlan, ...]
    rewrite_blockers: tuple[PostScriptRewriteBlocker, ...]
    output_emission_gates: tuple[PostScriptOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def can_rewrite_metadata(self) -> bool:
        return not self.rewrite_blockers

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"PostScript DSC transaction output is gated: {gate_codes}")
        return self.original_bytes

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "bounding_box": self.bounding_box.to_json(),
            "can_emit_output": self.can_emit_output,
            "can_rewrite_metadata": self.can_rewrite_metadata,
            "comments": json_object_array(comment.to_json() for comment in self.comments),
            "directories": json_object_array(directory.to_json() for directory in self.directories),
            "header": self.header.to_json(),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "preservation": self.preservation.to_json(),
            "rewrite_blockers": json_object_array(
                blocker.to_json() for blocker in self.rewrite_blockers
            ),
            "status": self.status,
            "xmp": self.xmp.to_json(),
        }


def build_postscript_dsc_transaction_plan(
    postscript_data: bytes,
    *,
    requested_comment_writes: Mapping[str, str] | None = None,
    requested_comment_deletes: Iterable[str] = (),
    xmp_packet: bytes | None = None,
    delete_xmp: bool = False,
    photoshop_resource_payload: bytes | None = None,
    icc_profile_payload: bytes | None = None,
    allow_output_emission: bool = False,
) -> PostScriptDscTransactionPlan:
    """Build a non-mutating PostScript/EPS DSC metadata transaction plan."""

    comment_writes = dict(requested_comment_writes or {})
    comment_deletes = tuple(requested_comment_deletes)
    header = build_header_plan(postscript_data)
    lines = split_physical_lines(postscript_data, header.ps_data_start, header.ps_data_end)
    comments = parse_comments(lines)
    directories = parse_directories(lines)
    bounding_box = build_bounding_box_plan(comments)
    xmp = build_xmp_plan(postscript_data, comments, directories)
    preservation = build_preservation_plan(header, lines, directories)
    actions = build_actions(
        header,
        comments,
        directories,
        preservation,
        comment_writes,
        comment_deletes,
        xmp_packet,
        delete_xmp,
        photoshop_resource_payload,
        icc_profile_payload,
    )
    rewrite_blockers = build_rewrite_blockers(
        header,
        lines,
        comments,
        directories,
        preservation,
        comment_writes,
        comment_deletes,
        xmp_packet,
        delete_xmp,
        photoshop_resource_payload,
        icc_profile_payload,
    )
    gates = build_emission_gates(
        header,
        lines,
        directories,
        rewrite_blockers,
        comment_writes,
        comment_deletes,
        xmp_packet,
        delete_xmp,
        photoshop_resource_payload,
        icc_profile_payload,
        allow_output_emission,
    )
    status: PostScriptPlanStatus = (
        "unsupported" if any_validation_gate(gates, allow_output_emission) else "planned"
    )
    sources = unique_sources(
        (
            *POSTSCRIPT_TRANSACTION_SOURCES,
            *header.evidence_ids,
            *(source for comment in comments for source in comment.evidence_ids),
            *bounding_box.evidence_ids,
            *(source for directory in directories for source in directory.evidence_ids),
            *xmp.evidence_ids,
            *preservation.evidence_ids,
            *(source for action in actions for source in action.evidence_ids),
            *(source for blocker in rewrite_blockers for source in blocker.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return PostScriptDscTransactionPlan(
        status=status,
        header=header,
        comments=comments,
        bounding_box=bounding_box,
        directories=directories,
        xmp=xmp,
        preservation=preservation,
        actions=actions,
        rewrite_blockers=unique_rewrite_blockers(tuple(rewrite_blockers)),
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
        original_bytes=postscript_data,
    )


@dataclass(frozen=True)
class PhysicalLine:
    text: str
    raw: bytes
    byte_range_start: int
    byte_range_end: int
    line_index: int
    has_mixed_newline: bool


def build_header_plan(postscript_data: bytes) -> PostScriptDscHeaderPlan:
    signature = postscript_data[:4]
    reason: PostScriptGateCode | None = None
    ps_start = 0
    ps_end: int | None = len(postscript_data)
    if len(postscript_data) < 4:
        reason = "truncated_header"
    elif signature == DOS_BINARY_MAGIC:
        if len(postscript_data) < 30:
            reason = "truncated_dos_binary_header"
        else:
            ps_start = int.from_bytes(postscript_data[4:8], "little")
            ps_length = int.from_bytes(postscript_data[8:12], "little")
            ps_end = ps_start + ps_length
            if (
                ps_start + 4 > len(postscript_data)
                or ps_end > len(postscript_data)
                or postscript_data[ps_start : ps_start + 4] != b"%!PS"
            ):
                reason = "invalid_dos_binary_postscript_header"
    elif postscript_data.startswith(b"%!Adobe-PS"):
        ps_start = 0
    elif not (
        postscript_data.startswith(b"%!PS")
        or postscript_data.startswith(b"%!Fo")
        or postscript_data.startswith(b"%!PS-AdobeFont-")
        or postscript_data.startswith(b"%!FontType1-")
    ):
        reason = "unsupported_postscript_signature"

    newline_kind = detect_newline_kind(postscript_data[ps_start:ps_end])
    if reason is None and newline_kind == "unknown":
        reason = "invalid_postscript_newline"
    first_line = read_first_line(postscript_data, ps_start, ps_end)
    if reason is None and first_line is None:
        reason = "dsc_header_line_missing"
    dsc_revision = parse_dsc_revision(first_line)
    conforms_to_write_gate = dsc_revision is not None and dsc_revision < 2
    document_kind = classify_document(postscript_data, ps_start, ps_end, first_line, signature)
    return PostScriptDscHeaderPlan(
        document_kind=document_kind,
        signature=signature,
        ps_data_start=ps_start,
        ps_data_end=ps_end,
        dsc_header_line=first_line,
        dsc_revision=dsc_revision,
        conforms_to_write_dsc_gate=conforms_to_write_gate,
        newline_kind=newline_kind,
        is_valid_postscript=reason is None,
        reason=reason,
        evidence_ids=(POSTSCRIPT_HEADER_SOURCE, WRITE_HEADER_SOURCE),
    )


def detect_newline_kind(data: bytes) -> PostScriptNewlineKind:
    probe = data[:HEADER_PROBE_SIZE]
    lf = probe.find(b"\x0a")
    cr = probe.find(b"\x0d")
    if lf < 0 and cr < 0:
        return "unknown"
    if lf >= 0 and cr >= 0:
        diff = lf - cr
        if diff == 1:
            return "crlf"
        if diff == -1:
            return "lfcr"
        return "cr" if diff > 0 else "lf"
    return "lf" if lf >= 0 else "cr"


def read_first_line(data: bytes, start: int, end: int | None) -> str | None:
    lines = split_physical_lines(data, start, end)
    return lines[0].text if lines else None


def parse_dsc_revision(first_line: str | None) -> int | None:
    if first_line is None:
        return None
    match = re.match(r"^%!PS-Adobe-3\.(\d+)\b", first_line)
    return int(match.group(1)) if match else None


def classify_document(
    data: bytes,
    start: int,
    end: int | None,
    first_line: str | None,
    signature: bytes,
) -> PostScriptDocumentKind:
    if signature == DOS_BINARY_MAGIC:
        return "dos_binary_ps"
    if first_line is not None and "EPSF" in first_line:
        return "eps"
    lines = split_physical_lines(data, start, end)
    if len(lines) > 1 and lines[1].text.startswith("%%Creator: Adobe Illustrator"):
        return "ai"
    if data[start : start + 4] in (b"%!PS", b"%!Ad"):
        return "ps"
    return "unknown"


def split_physical_lines(
    data: bytes,
    start: int = 0,
    end: int | None = None,
) -> tuple[PhysicalLine, ...]:
    bounded_end = len(data) if end is None else min(end, len(data))
    lines: list[PhysicalLine] = []
    pos = start
    line_index = 0
    while pos < bounded_end:
        newline_start, newline_end = find_next_newline(data, pos, bounded_end)
        if newline_start < 0:
            raw = data[pos:bounded_end]
            next_pos = bounded_end
        else:
            raw = data[pos:newline_end]
            next_pos = newline_end
        text = raw.rstrip(b"\r\n").decode("latin-1")
        has_mixed_newline = b"\r" in raw.rstrip(b"\r\n") or b"\n" in raw.rstrip(b"\r\n")
        lines.append(
            PhysicalLine(
                text=text,
                raw=raw,
                byte_range_start=pos,
                byte_range_end=next_pos,
                line_index=line_index,
                has_mixed_newline=has_mixed_newline,
            )
        )
        line_index += 1
        pos = next_pos
    return tuple(lines)


def find_next_newline(data: bytes, start: int, end: int) -> tuple[int, int]:
    lf = data.find(b"\n", start, end)
    cr = data.find(b"\r", start, end)
    candidates = [position for position in (lf, cr) if position >= 0]
    if not candidates:
        return -1, -1
    newline_start = min(candidates)
    newline_end = newline_start + 1
    if newline_start + 1 < end:
        pair = data[newline_start : newline_start + 2]
        if pair in (b"\r\n", b"\n\r"):
            newline_end = newline_start + 2
    return newline_start, newline_end


def parse_comments(lines: tuple[PhysicalLine, ...]) -> tuple[PostScriptDscCommentPlan, ...]:
    comments: list[PostScriptDscCommentPlan] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^%%?(\w+): ?(.*)", line.text, flags=re.DOTALL)
        if match and (line.text.startswith("%%") or match.group(1) == "ImageData"):
            tag = match.group(1)
            value = match.group(2)
            if tag in MODELED_DSC_TAGS:
                continuation_index = index + 1
                while continuation_index < len(lines) and lines[continuation_index].text.startswith(
                    "%%+"
                ):
                    value += lines[continuation_index].text[3:]
                    continuation_index += 1
                comments.append(
                    PostScriptDscCommentPlan(
                        tag=tag,
                        value=match.group(2),
                        decoded_value=decode_comment_value(value),
                        line_index=line.line_index,
                        byte_range_start=line.byte_range_start,
                        byte_range_end=lines[continuation_index - 1].byte_range_end,
                        writable_by_exiftool=tag in WRITABLE_DSC_TAGS,
                        priority_zero_first_wins=True,
                        evidence_ids=(
                            POSTSCRIPT_TAG_TABLE_SOURCE,
                            POSTSCRIPT_COMMENT_DECODE_SOURCE,
                            POSTSCRIPT_PARSE_SOURCE,
                        ),
                    )
                )
                index = continuation_index
                continue
        index += 1
    return tuple(comments)


def decode_comment_value(value: str) -> str:
    stripped = value.rstrip("\r\n")
    if len(stripped) >= 2 and stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1]
    return decode_postscript_escapes(stripped)


def decode_postscript_escapes(value: str) -> str:
    decoded: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\" or index + 1 >= len(value):
            decoded.append(char)
            index += 1
            continue
        next_char = value[index + 1]
        if next_char in "01234567":
            octal = next_char
            cursor = index + 2
            while cursor < len(value) and len(octal) < 3 and value[cursor] in "01234567":
                octal += value[cursor]
                cursor += 1
            decoded.append(chr(int(octal, 8) & 0xFF))
            index = cursor
            continue
        escape_map = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
        decoded.append(escape_map.get(next_char, next_char))
        index += 2
    return "".join(decoded)


def build_bounding_box_plan(
    comments: tuple[PostScriptDscCommentPlan, ...],
) -> PostScriptBoundingBoxPlan:
    bounding = next((comment for comment in comments if comment.tag == "BoundingBox"), None)
    coordinates = parse_bounding_box(bounding.decoded_value) if bounding is not None else None
    width = coordinates[2] - coordinates[0] if coordinates is not None else None
    height = coordinates[3] - coordinates[1] if coordinates is not None else None
    return PostScriptBoundingBoxPlan(
        raw_value=bounding.decoded_value if bounding is not None else None,
        coordinates=coordinates,
        derived_width=width,
        derived_height=height,
        writable_by_exiftool=False,
        evidence_ids=(POSTSCRIPT_TAG_TABLE_SOURCE, POSTSCRIPT_IMAGE_SIZE_SOURCE),
    )


def parse_bounding_box(value: str) -> tuple[int, int, int, int] | None:
    parts = value.split()
    if len(parts) < 4:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    except ValueError:
        return None


def parse_directories(lines: tuple[PhysicalLine, ...]) -> tuple[PostScriptDirectoryPlan, ...]:
    directories: list[PostScriptDirectoryPlan] = []
    stack: list[tuple[PostScriptDirectoryKind, str, str | None, PhysicalLine, int]] = []
    for line in lines:
        begin = re.match(r"^(%{1,2})(Begin|begin)(?!Object:)(.*?)(?::|\r|\n|$)", line.text)
        if begin:
            suffix = begin.group(3)
            kind = directory_kind(suffix)
            end_token = begin.group(1) + ("end" if begin.group(2) == "begin" else "End") + suffix
            if kind == "xmp" and stack and stack[-1][0] == "xmp":
                continue
            if kind == "binary":
                directories.append(
                    PostScriptDirectoryPlan(
                        kind=kind,
                        begin_token=begin.group(0).rstrip(":"),
                        end_token=None,
                        byte_range_start=line.byte_range_start,
                        byte_range_end=line.byte_range_end,
                        payload_length=binary_payload_length(line.text),
                        preserved=True,
                        reason=None,
                        evidence_ids=(POSTSCRIPT_PARSE_SOURCE,),
                    )
                )
            else:
                stack.append((kind, begin.group(0).rstrip(":"), end_token, line, line.line_index))
            continue
        if (
            stack
            and stack[-1][2] is not None
            and re.match(rf"^{re.escape(stack[-1][2])}\s*$", line.text, flags=re.IGNORECASE)
        ):
            kind, begin_token, end_token, begin_line, begin_index = stack.pop()
            directories.append(
                PostScriptDirectoryPlan(
                    kind=kind,
                    begin_token=begin_token,
                    end_token=end_token,
                    byte_range_start=begin_line.byte_range_start,
                    byte_range_end=line.byte_range_end,
                    payload_length=max(0, line.byte_range_start - begin_line.byte_range_end),
                    preserved=True,
                    reason=None,
                    evidence_ids=directory_sources(kind),
                )
            )
            _ = begin_index
    for kind, begin_token, end_token, begin_line, begin_index in stack:
        reason: PostScriptGateCode = (
            "unterminated_xmp_packet" if kind == "xmp" else "unterminated_begin_end_block"
        )
        directories.append(
            PostScriptDirectoryPlan(
                kind=kind,
                begin_token=begin_token,
                end_token=end_token,
                byte_range_start=begin_line.byte_range_start,
                byte_range_end=None,
                payload_length=None,
                preserved=False,
                reason=reason,
                evidence_ids=directory_sources(kind),
            )
        )
        _ = begin_index
    return tuple(sorted(directories, key=lambda item: item.byte_range_start))


def directory_kind(suffix: str) -> PostScriptDirectoryKind:
    normalized = suffix.lower().lstrip("_")
    if normalized in ("xml_code", "xml_packet"):
        return "xmp"
    if normalized == "photoshop":
        return "photoshop"
    if normalized == "iccprofile":
        return "icc_profile"
    if normalized == "document":
        return "embedded_document"
    if normalized == "binary":
        return "binary"
    return "unknown"


def directory_sources(kind: PostScriptDirectoryKind) -> tuple[str, ...]:
    if kind == "xmp":
        return (POSTSCRIPT_PARSE_SOURCE, WRITE_XMP_SOURCE)
    if kind in ("photoshop", "icc_profile"):
        return (POSTSCRIPT_PARSE_SOURCE, WRITE_RESOURCE_SOURCE)
    if kind == "embedded_document":
        return (POSTSCRIPT_PARSE_SOURCE, WRITE_NOTES_SOURCE)
    return (POSTSCRIPT_PARSE_SOURCE,)


def binary_payload_length(line: str) -> int | None:
    match = re.match(r"^%{1,2}BeginBinary:\s*(\d+)", line, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def build_xmp_plan(
    data: bytes,
    comments: tuple[PostScriptDscCommentPlan, ...],
    directories: tuple[PostScriptDirectoryPlan, ...],
) -> PostScriptXmpResponsibilityPlan:
    packet_markers = len(re.findall(rb"<\?xpacket begin=.{7,13}W5M0MpCehiHzreSzNTczkc9d", data))
    xmp_count = packet_markers or sum(1 for directory in directories if directory.kind == "xmp")
    return PostScriptXmpResponsibilityPlan(
        packet_count=xmp_count,
        has_ado_contains_xmp_hint=any(comment.tag == "ADO_ContainsXMP" for comment in comments)
        or b"%ADO_ContainsXMP" in data,
        can_rewrite_reported_packet_size=can_rewrite_xmp_size(data),
        creation_requires_pdfmark_scaffolding=True,
        deletion_strategy="write_blank_xmp_record",
        evidence_ids=(POSTSCRIPT_TAG_TABLE_SOURCE, WRITE_XMP_SOURCE, WRITE_LOOP_SOURCE),
    )


def can_rewrite_xmp_size(data: bytes) -> bool:
    match = re.search(rb"%begin_xml_packet: (\d+)", data)
    if match is None:
        return False
    reported_len = match.group(1)
    return len(re.findall(rb"\b" + re.escape(reported_len) + rb"\b", data)) == 2


def build_preservation_plan(
    header: PostScriptDscHeaderPlan,
    lines: tuple[PhysicalLine, ...],
    directories: tuple[PostScriptDirectoryPlan, ...],
) -> PostScriptPreservationPlan:
    return PostScriptPreservationPlan(
        has_dos_preview_or_metafile=header.document_kind == "dos_binary_ps",
        photoshop_resource_count=sum(
            1 for directory in directories if directory.kind == "photoshop"
        ),
        icc_profile_count=sum(1 for directory in directories if directory.kind == "icc_profile"),
        embedded_document_count=sum(
            1 for directory in directories if directory.kind == "embedded_document"
        ),
        binary_block_count=sum(1 for directory in directories if directory.kind == "binary"),
        drawing_stream_start=find_drawing_stream_start(lines),
        evidence_ids=(
            POSTSCRIPT_DOS_PREVIEW_SOURCE,
            POSTSCRIPT_PARSE_SOURCE,
            WRITE_LOOP_SOURCE,
        ),
    )


def find_drawing_stream_start(lines: tuple[PhysicalLine, ...]) -> int | None:
    for line in lines:
        if re.match(
            r"^%(%Page:|%PlateFile:|%BeginObject:|.*BeginLayer)", line.text
        ) or not re.match(r"^(%.*|\s*)$", line.text, flags=re.DOTALL):
            return line.byte_range_start
    return None


def build_actions(
    header: PostScriptDscHeaderPlan,
    comments: tuple[PostScriptDscCommentPlan, ...],
    directories: tuple[PostScriptDirectoryPlan, ...],
    preservation: PostScriptPreservationPlan,
    comment_writes: dict[str, str],
    comment_deletes: tuple[str, ...],
    xmp_packet: bytes | None,
    delete_xmp: bool,
    photoshop_resource_payload: bytes | None,
    icc_profile_payload: bytes | None,
) -> tuple[PostScriptDscActionPlan, ...]:
    actions: list[PostScriptDscActionPlan] = [
        PostScriptDscActionPlan(
            kind="validate_header",
            target=header.document_kind,
            byte_range_start=header.ps_data_start,
            byte_range_end=header.ps_data_end,
            planned_payload_length=None,
            reason="Validate the PostScript/EPS header and DSC rewrite preconditions.",
            evidence_ids=header.evidence_ids,
        )
    ]
    actions.extend(comment_actions(comments, comment_writes, comment_deletes))
    actions.extend(directory_preservation_actions(directories))
    if preservation.has_dos_preview_or_metafile:
        actions.append(
            PostScriptDscActionPlan(
                kind="preserve_dos_preview_or_metafile",
                target="dos_binary_header_resource",
                byte_range_start=0,
                byte_range_end=header.ps_data_start,
                planned_payload_length=header.ps_data_start,
                reason="Preserve DOS binary EPS preview/metafile resource bytes in planning.",
                evidence_ids=(POSTSCRIPT_DOS_PREVIEW_SOURCE, WRITE_HEADER_SOURCE),
            )
        )
    if preservation.drawing_stream_start is not None:
        actions.append(
            PostScriptDscActionPlan(
                kind="preserve_drawing_stream",
                target="postscript_program",
                byte_range_start=preservation.drawing_stream_start,
                byte_range_end=header.ps_data_end,
                planned_payload_length=None,
                reason="Preserve graphics commands after the DSC comments and metadata blocks.",
                evidence_ids=(WRITE_LOOP_SOURCE,),
            )
        )
    actions.extend(
        requested_payload_actions(
            comment_writes,
            comment_deletes,
            xmp_packet,
            delete_xmp,
            photoshop_resource_payload,
            icc_profile_payload,
        )
    )
    return tuple(actions)


def comment_actions(
    comments: tuple[PostScriptDscCommentPlan, ...],
    comment_writes: dict[str, str],
    comment_deletes: tuple[str, ...],
) -> tuple[PostScriptDscActionPlan, ...]:
    actions: list[PostScriptDscActionPlan] = []
    for comment in comments:
        actions.append(
            PostScriptDscActionPlan(
                kind=(
                    "preserve_bounding_box" if comment.tag == "BoundingBox" else "parse_dsc_comment"
                ),
                target=comment.tag,
                byte_range_start=comment.byte_range_start,
                byte_range_end=comment.byte_range_end,
                planned_payload_length=len(comment.decoded_value),
                reason="Parse and preserve the first-priority DSC comment value.",
                evidence_ids=comment.evidence_ids,
            )
        )
    for tag, value in comment_writes.items():
        actions.append(
            PostScriptDscActionPlan(
                kind="plan_comment_write",
                target=tag,
                byte_range_start=None,
                byte_range_end=None,
                planned_payload_length=len(encode_tag_preview(tag, value)),
                reason="Plan a DSC comment write using ExifTool EncodeTag escaping rules.",
                evidence_ids=(WRITE_ENCODE_TAG_SOURCE, WRITE_LOOP_SOURCE),
            )
        )
    for tag in comment_deletes:
        actions.append(
            PostScriptDscActionPlan(
                kind="plan_comment_delete",
                target=tag,
                byte_range_start=None,
                byte_range_end=None,
                planned_payload_length=0,
                reason="Plan a DSC comment deletion while preserving surrounding comments.",
                evidence_ids=(WRITE_LOOP_SOURCE,),
            )
        )
    return tuple(actions)


def directory_preservation_actions(
    directories: tuple[PostScriptDirectoryPlan, ...],
) -> tuple[PostScriptDscActionPlan, ...]:
    actions: list[PostScriptDscActionPlan] = []
    for directory in directories:
        action_kind = directory_action_kind(directory.kind)
        if action_kind is None:
            continue
        actions.append(
            PostScriptDscActionPlan(
                kind=action_kind,
                target=directory.kind,
                byte_range_start=directory.byte_range_start,
                byte_range_end=directory.byte_range_end,
                planned_payload_length=directory.payload_length,
                reason="Preserve ExifTool-modeled PostScript begin/end block bytes.",
                evidence_ids=directory.evidence_ids,
            )
        )
    return tuple(actions)


def directory_action_kind(kind: PostScriptDirectoryKind) -> PostScriptDscActionKind | None:
    if kind == "xmp":
        return "preserve_xmp_packet"
    if kind == "photoshop":
        return "preserve_photoshop_resource"
    if kind == "icc_profile":
        return "preserve_icc_profile"
    if kind == "embedded_document":
        return "preserve_embedded_document"
    if kind == "binary":
        return "preserve_binary_block"
    return None


def requested_payload_actions(
    comment_writes: dict[str, str],
    comment_deletes: tuple[str, ...],
    xmp_packet: bytes | None,
    delete_xmp: bool,
    photoshop_resource_payload: bytes | None,
    icc_profile_payload: bytes | None,
) -> tuple[PostScriptDscActionPlan, ...]:
    _ = comment_writes, comment_deletes
    actions: list[PostScriptDscActionPlan] = []
    if xmp_packet is not None:
        actions.append(
            PostScriptDscActionPlan(
                kind="plan_xmp_replace",
                target="XMP",
                byte_range_start=None,
                byte_range_end=None,
                planned_payload_length=len(xmp_packet),
                reason="Plan XMP packet replacement through WritePSDirectory boundaries.",
                evidence_ids=(WRITE_XMP_SOURCE,),
            )
        )
    if delete_xmp:
        actions.append(
            PostScriptDscActionPlan(
                kind="plan_xmp_delete_as_blank_packet",
                target="XMP",
                byte_range_start=None,
                byte_range_end=None,
                planned_payload_length=0,
                reason="Plan ExifTool's blank XMP packet deletion strategy.",
                evidence_ids=(WRITE_XMP_SOURCE,),
            )
        )
    _ = photoshop_resource_payload, icc_profile_payload
    return tuple(actions)


def build_rewrite_blockers(
    header: PostScriptDscHeaderPlan,
    lines: tuple[PhysicalLine, ...],
    comments: tuple[PostScriptDscCommentPlan, ...],
    directories: tuple[PostScriptDirectoryPlan, ...],
    preservation: PostScriptPreservationPlan,
    comment_writes: dict[str, str],
    comment_deletes: tuple[str, ...],
    xmp_packet: bytes | None,
    delete_xmp: bool,
    photoshop_resource_payload: bytes | None,
    icc_profile_payload: bytes | None,
) -> tuple[PostScriptRewriteBlocker, ...]:
    blockers: list[PostScriptRewriteBlocker] = []
    metadata_requested = any(
        (
            bool(comment_writes),
            bool(comment_deletes),
            xmp_packet is not None,
            delete_xmp,
            photoshop_resource_payload is not None,
            icc_profile_payload is not None,
        )
    )
    if metadata_requested:
        blockers.append(
            PostScriptRewriteBlocker(
                code="dsc_rewrite_engine_not_emitting",
                reason=(
                    "This surface plans ExifTool DSC rewrite responsibilities but does not "
                    "emit mutations."
                ),
                evidence_ids=(WRITE_LOOP_SOURCE, WRITE_NOTES_SOURCE),
            )
        )
    if header.reason is None and not header.conforms_to_write_dsc_gate:
        blockers.append(
            PostScriptRewriteBlocker(
                code="dsc_version_warning_required",
                reason=(
                    "WritePS warns when a document does not conform to the supported "
                    "DSC 3.0/3.1 gate."
                ),
                evidence_ids=(WRITE_HEADER_SOURCE,),
            )
        )
    if preservation.drawing_stream_start is not None and any(
        line.text.startswith("%%PlateFile:") for line in lines
    ):
        blockers.append(
            PostScriptRewriteBlocker(
                code="dcs_plate_file_offsets_block_directory_writes",
                reason=(
                    "DCS PlateFile comments may contain offsets, so directory writes are blocked."
                ),
                evidence_ids=(WRITE_BLOCKER_SOURCE,),
            )
        )
    if is_illustrator(comments):
        if "Creator" in comment_writes or "Creator" in comment_deletes:
            blockers.append(
                PostScriptRewriteBlocker(
                    code="illustrator_creator_rewrite_blocked",
                    reason=(
                        "WritePS does not allow changing PostScript:Creator for Illustrator files."
                    ),
                    evidence_ids=(WRITE_BLOCKER_SOURCE,),
                )
            )
        if xmp_packet is not None or delete_xmp:
            blockers.append(
                PostScriptRewriteBlocker(
                    code="illustrator_xmp_write_blocked",
                    reason="WritePS disables XMP writes for PostScript-format Illustrator files.",
                    evidence_ids=(WRITE_BLOCKER_SOURCE,),
                )
            )
    blockers.extend(multiple_directory_blockers(directories))
    blockers.extend(unterminated_blockers(directories))
    if header.document_kind == "dos_binary_ps" and metadata_requested:
        blockers.append(
            PostScriptRewriteBlocker(
                code="dos_binary_header_rewrite_requires_seekable_output",
                reason="WritePS must seek back to update the DOS binary PS length field.",
                evidence_ids=(WRITE_HEADER_SOURCE,),
            )
        )
    if any(line.has_mixed_newline and len(line.raw) > WINDOWS_LONG_LINE_LIMIT for line in lines):
        blockers.append(
            PostScriptRewriteBlocker(
                code="line_split_requires_alternate_newline_streaming",
                reason=(
                    "ExifTool switches record separators for very long mixed-newline lines "
                    "on Windows."
                ),
                evidence_ids=(POSTSCRIPT_PARSE_SOURCE,),
            )
        )
    return tuple(blockers)


def multiple_directory_blockers(
    directories: tuple[PostScriptDirectoryPlan, ...],
) -> tuple[PostScriptRewriteBlocker, ...]:
    blockers: list[PostScriptRewriteBlocker] = []
    blocker_specs: tuple[
        tuple[PostScriptDirectoryKind, PostScriptRewriteBlockerCode],
        ...,
    ] = (
        ("xmp", "multiple_xmp_directories"),
        ("photoshop", "multiple_photoshop_directories"),
        ("icc_profile", "multiple_icc_profile_directories"),
    )
    for kind, code in blocker_specs:
        if sum(1 for directory in directories if directory.kind == kind) > 1:
            blockers.append(
                PostScriptRewriteBlocker(
                    code=code,
                    reason=f"WritePS warns on multiple {kind} directories in one outer document.",
                    evidence_ids=(WRITE_LOOP_SOURCE,),
                )
            )
    return tuple(blockers)


def unterminated_blockers(
    directories: tuple[PostScriptDirectoryPlan, ...],
) -> tuple[PostScriptRewriteBlocker, ...]:
    blockers: list[PostScriptRewriteBlocker] = []
    for directory in directories:
        if directory.reason == "unterminated_xmp_packet":
            blockers.append(
                PostScriptRewriteBlocker(
                    code="unterminated_xmp_packet",
                    reason="XMP packet begin marker has no matching packet end.",
                    evidence_ids=directory.evidence_ids,
                )
            )
        elif directory.reason == "unterminated_begin_end_block":
            blockers.append(
                PostScriptRewriteBlocker(
                    code="unterminated_begin_end_block",
                    reason="Begin block has no matching ExifTool end token.",
                    evidence_ids=directory.evidence_ids,
                )
            )
    return tuple(blockers)


def build_emission_gates(
    header: PostScriptDscHeaderPlan,
    lines: tuple[PhysicalLine, ...],
    directories: tuple[PostScriptDirectoryPlan, ...],
    rewrite_blockers: tuple[PostScriptRewriteBlocker, ...],
    comment_writes: dict[str, str],
    comment_deletes: tuple[str, ...],
    xmp_packet: bytes | None,
    delete_xmp: bool,
    photoshop_resource_payload: bytes | None,
    icc_profile_payload: bytes | None,
    allow_output_emission: bool,
) -> tuple[PostScriptOutputEmissionGate, ...]:
    gates: list[PostScriptOutputEmissionGate] = []
    append_reason_gate(
        gates,
        header.reason,
        "PostScript header validation failed.",
        header.evidence_ids,
    )
    for directory in directories:
        append_reason_gate(
            gates,
            directory.reason,
            "PostScript begin/end metadata block is incomplete.",
            directory.evidence_ids,
        )
    if header.reason is None and not header.conforms_to_write_dsc_gate:
        gates.append(
            PostScriptOutputEmissionGate(
                code="dsc_version_unsupported",
                reason="ExifTool WritePS warns or errors for non-DSC 3.0/3.1 headers.",
                evidence_ids=(WRITE_HEADER_SOURCE,),
            )
        )
    for tag in comment_writes:
        code: PostScriptGateCode = (
            "bounding_box_write_not_writable"
            if tag == "BoundingBox"
            else "comment_write_requires_dsc_rewrite"
        )
        gates.append(
            PostScriptOutputEmissionGate(
                code=code,
                reason=f"Writing PostScript:{tag} requires DSC comment rewrite emission.",
                evidence_ids=(POSTSCRIPT_TAG_TABLE_SOURCE, WRITE_ENCODE_TAG_SOURCE),
            )
        )
    for tag in comment_deletes:
        gates.append(
            PostScriptOutputEmissionGate(
                code="comment_delete_requires_dsc_rewrite",
                reason=f"Deleting PostScript:{tag} requires DSC comment rewrite emission.",
                evidence_ids=(WRITE_LOOP_SOURCE,),
            )
        )
    if xmp_packet is not None:
        gates.append(
            PostScriptOutputEmissionGate(
                code="xmp_replace_requires_packet_size_rewrite",
                reason="XMP replacement may require packet-size and pdfmark wrapper rewrites.",
                evidence_ids=(WRITE_XMP_SOURCE,),
            )
        )
    if delete_xmp:
        gates.append(
            PostScriptOutputEmissionGate(
                code="xmp_delete_writes_blank_packet",
                reason="ExifTool deletes PostScript XMP by writing a blank XMP packet.",
                evidence_ids=(WRITE_XMP_SOURCE,),
            )
        )
    if xmp_packet is not None and not any(directory.kind == "xmp" for directory in directories):
        gates.append(
            PostScriptOutputEmissionGate(
                code="xmp_create_requires_pdfmark_scaffolding",
                reason="Creating PostScript XMP requires ExifTool's pdfmark support code.",
                evidence_ids=(WRITE_XMP_SOURCE,),
            )
        )
    if photoshop_resource_payload is not None:
        gates.append(
            PostScriptOutputEmissionGate(
                code="photoshop_resource_rewrite_not_planned",
                reason="Photoshop resource mutation requires ASCII-hex block emission.",
                evidence_ids=(WRITE_RESOURCE_SOURCE,),
            )
        )
    if icc_profile_payload is not None:
        gates.append(
            PostScriptOutputEmissionGate(
                code="icc_profile_rewrite_not_planned",
                reason="ICC_Profile mutation requires ASCII-hex block emission.",
                evidence_ids=(WRITE_RESOURCE_SOURCE,),
            )
        )
    if any(line.has_mixed_newline and len(line.raw) > WINDOWS_LONG_LINE_LIMIT for line in lines):
        gates.append(
            PostScriptOutputEmissionGate(
                code="long_mixed_newline_line_requires_streaming_split",
                reason=(
                    "Very long mixed-newline records require ExifTool's alternate separator path."
                ),
                evidence_ids=(POSTSCRIPT_PARSE_SOURCE,),
            )
        )
    gates.extend(gate_from_blocker(blocker) for blocker in rewrite_blockers)
    if not allow_output_emission:
        gates.append(
            PostScriptOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason=(
                    "PostScript DSC transaction plans are non-mutating unless emission is "
                    "explicitly allowed."
                ),
                evidence_ids=(WRITE_NOTES_SOURCE,),
            )
        )
    return tuple(gates)


def gate_from_blocker(blocker: PostScriptRewriteBlocker) -> PostScriptOutputEmissionGate:
    blocker_gate_codes: dict[PostScriptRewriteBlockerCode, PostScriptGateCode] = {
        "dsc_rewrite_engine_not_emitting": "missing_requested_postscript_information",
        "dsc_version_warning_required": "dsc_version_unsupported",
        "dcs_plate_file_offsets_block_directory_writes": (
            "dcs_plate_file_offsets_block_directory_writes"
        ),
        "illustrator_creator_rewrite_blocked": "illustrator_creator_rewrite_blocked",
        "illustrator_xmp_write_blocked": "illustrator_xmp_write_blocked",
        "multiple_xmp_directories": "multiple_postscript_directories",
        "multiple_photoshop_directories": "multiple_postscript_directories",
        "multiple_icc_profile_directories": "multiple_postscript_directories",
        "unterminated_begin_end_block": "unterminated_begin_end_block",
        "unterminated_xmp_packet": "unterminated_xmp_packet",
        "dos_binary_header_rewrite_requires_seekable_output": (
            "dos_binary_header_rewrite_requires_seekable_output"
        ),
        "line_split_requires_alternate_newline_streaming": (
            "long_mixed_newline_line_requires_streaming_split"
        ),
    }
    return PostScriptOutputEmissionGate(
        code=blocker_gate_codes[blocker.code],
        reason=blocker.reason,
        evidence_ids=blocker.evidence_ids,
    )


def append_reason_gate(
    gates: list[PostScriptOutputEmissionGate],
    reason_code: PostScriptGateCode | None,
    reason: str,
    evidence_ids: tuple[str, ...],
) -> None:
    if reason_code is None:
        return
    gates.append(
        PostScriptOutputEmissionGate(
            code=reason_code,
            reason=reason,
            evidence_ids=evidence_ids,
        )
    )


def is_illustrator(comments: tuple[PostScriptDscCommentPlan, ...]) -> bool:
    return any(
        comment.tag == "Creator" and comment.decoded_value.startswith("Adobe Illustrator")
        for comment in comments
    )


def encode_tag_preview(tag: str, value: str) -> str:
    if not value.isdigit():
        escaped = (
            value.replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        escaped = "".join(
            f"\\{ord(char):03o}" if ord(char) < 32 or ord(char) in (127, 255) else char
            for char in escaped
        )
        value = f"({escaped})"
    line = f"%%{tag}: {value}"
    if len(line) <= ENCODED_COMMENT_CONTINUATION_LIMIT:
        return line
    chunks = [
        line[index : index + ENCODED_COMMENT_CONTINUATION_LIMIT]
        for index in range(0, len(line), ENCODED_COMMENT_CONTINUATION_LIMIT)
    ]
    return "\n%%+".join(chunks)


def any_validation_gate(
    gates: tuple[PostScriptOutputEmissionGate, ...],
    allow_output_emission: bool,
) -> bool:
    non_validation_codes = {"non_mutating_plan_requires_explicit_emission"}
    if not allow_output_emission:
        return any(gate.code not in non_validation_codes for gate in gates)
    return bool(gates)


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source not in seen:
            unique.append(source)
            seen.add(source)
    return tuple(unique)


def unique_rewrite_blockers(
    blockers: tuple[PostScriptRewriteBlocker, ...],
) -> tuple[PostScriptRewriteBlocker, ...]:
    unique: list[PostScriptRewriteBlocker] = []
    seen: set[PostScriptRewriteBlockerCode] = set()
    for blocker in blockers:
        if blocker.code not in seen:
            unique.append(blocker)
            seen.add(blocker.code)
    return tuple(unique)


def unique_gates(
    gates: tuple[PostScriptOutputEmissionGate, ...],
) -> tuple[PostScriptOutputEmissionGate, ...]:
    unique: list[PostScriptOutputEmissionGate] = []
    seen: set[PostScriptGateCode] = set()
    for gate in gates:
        if gate.code not in seen:
            unique.append(gate)
            seen.add(gate.code)
    return tuple(unique)


def source_reference_to_json(reference: str) -> JsonObject:
    return {"evidence_id": reference}


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return [source_reference_to_json(reference) for reference in references]


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return [value for value in values]


install_evidence_reference_compat(globals())
