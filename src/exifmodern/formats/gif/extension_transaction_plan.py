"""Typed, source-backed GIF extension-block transaction plans.

The behavior modeled here is grounded in ExifTool's GIF implementation:
``/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/GIF.pm``.  Plans are
non-mutating: they parse source bytes, describe preservation/rewrite decisions,
and can optionally emit planned bytes without touching files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

GIF_HEADER_SIZE = 6
GIF_LOGICAL_SCREEN_SIZE = 7
GIF_FIXED_PREFIX_SIZE = GIF_HEADER_SIZE + GIF_LOGICAL_SCREEN_SIZE
GIF_TRAILER = 0x3B
GIF_EXTENSION_INTRODUCER = 0x21
GIF_IMAGE_SEPARATOR = 0x2C
GIF_COMMENT_LABEL = 0xFE
GIF_APPLICATION_LABEL = 0xFF
GIF_GRAPHIC_CONTROL_LABEL = 0xF9
GIF_PLAIN_TEXT_LABEL = 0x01
GIF_APPLICATION_HEADER_SIZE = 11
GIF_MAX_SUB_BLOCK_SIZE = 255
GIF_XMP_APPLICATION_IDENTIFIER = b"XMP DataXMP"
GIF_ICC_APPLICATION_IDENTIFIER = b"ICCRGBG1012"
GIF_XMP_LANDING_ZONE = bytes((1, *reversed(range(256))))

type GifPlanStatus = Literal["planned", "blocked"]
type GifExtensionKind = Literal[
    "comment",
    "application",
    "graphic_control",
    "plain_text",
    "generic",
]
type GifBlockAction = Literal[
    "preserve",
    "insert_comment",
    "replace_comment",
    "delete_comment",
    "insert_application",
    "replace_application",
    "delete_application",
]
type GifReadValue = str | int | float
type GifReadDiagnosticCode = Literal[
    "gif_application_subdirectory_adapter_missing",
    "gif_application_binary_payload_deferred",
]
type GifEmissionGateCode = Literal[
    "truncated_header",
    "unsupported_signature",
    "truncated_logical_screen",
    "truncated_global_color_table",
    "truncated_extension_header",
    "truncated_sub_block_payload",
    "missing_sub_block_terminator",
    "truncated_application_identifier",
    "truncated_image_descriptor",
    "truncated_local_color_table",
    "truncated_lzw_min_code_size",
    "missing_trailer_or_non_extension_terminator",
    "application_identifier_must_be_11_bytes",
    "xmp_packet_exceeds_single_sub_block",
]

type GifEvidenceId = str


@dataclass(frozen=True)
class GifEvidenceAnchor:
    path: str
    line_start: int
    line_end: int
    symbol: str
    evidence: str


GIF_HEADER_SOURCE: GifEvidenceId = "gif.header"
GIF_SCREEN_SOURCE: GifEvidenceId = "gif.screen"
GIF_EXTENSION_INSERTION_SOURCE: GifEvidenceId = "gif.extension_insertion"
GIF_COMMENT_SOURCE: GifEvidenceId = "gif.comment"
GIF_APPLICATION_TABLE_SOURCE: GifEvidenceId = "gif.table.application_extensions"
GIF_APPLICATION_SOURCE: GifEvidenceId = "gif.application_extension"
GIF_MIDI_CONTROL_SOURCE: GifEvidenceId = "gif.midi_control"
GIF_IMAGE_SOURCE: GifEvidenceId = "gif.image_data"
GIF_TRAILER_SOURCE: GifEvidenceId = "gif.trailer"
GIF_OTHER_EXTENSION_SOURCE: GifEvidenceId = "gif.other_extension"

GIF_EVIDENCE_ANCHORS: dict[GifEvidenceId, GifEvidenceAnchor] = {
    GIF_HEADER_SOURCE: GifEvidenceAnchor(
        path="lib/Image/ExifTool/GIF.pm",
        line_start=191,
        line_end=200,
        symbol="ProcessGIF GIF signature and byte order",
        evidence=(
            "ProcessGIF accepts only GIF87a/GIF89a headers, reads the seven-byte "
            "logical screen descriptor, and sets little-endian byte order."
        ),
    ),
    GIF_SCREEN_SOURCE: GifEvidenceAnchor(
        path="lib/Image/ExifTool/GIF.pm",
        line_start=223,
        line_end=232,
        symbol="ProcessGIF screen descriptor and global color table",
        evidence=(
            "ProcessGIF records GIFVersion and ScreenDescriptor, then skips or copies "
            "a global color table sized as 3 * (2 << packed low bits)."
        ),
    ),
    GIF_EXTENSION_INSERTION_SOURCE: GifEvidenceAnchor(
        path="lib/Image/ExifTool/GIF.pm",
        line_start=240,
        line_end=307,
        symbol="ProcessGIF pre-image metadata insertion",
        evidence=(
            "When writing, ExifTool emits new comments first and application extensions "
            "next when the next block is not an extension block."
        ),
    ),
    GIF_COMMENT_SOURCE: GifEvidenceAnchor(
        path="lib/Image/ExifTool/GIF.pm",
        line_start=355,
        line_end=411,
        symbol="ProcessGIF comment extension",
        evidence=(
            "Comment extensions concatenate sub-block payloads until a zero terminator "
            "and are rewritten as 255-byte chunks plus an empty terminator."
        ),
    ),
    GIF_APPLICATION_TABLE_SOURCE: GifEvidenceAnchor(
        path="lib/Image/ExifTool/GIF.pm",
        line_start=63,
        line_end=88,
        symbol="%Image::ExifTool::GIF::Extensions",
        evidence=(
            "The extension table declares writable XMP Data/XMP and ICCRGBG1/012 "
            "application extensions; XMP uses IncludeLengthBytes => 2."
        ),
    ),
    GIF_APPLICATION_SOURCE: GifEvidenceAnchor(
        path="lib/Image/ExifTool/GIF.pm",
        line_start=413,
        line_end=524,
        symbol="ProcessGIF application extension",
        evidence=(
            "Application extensions require an 11-byte identifier, read data sub-blocks, "
            "copy unknown/non-writable extensions, and write either length-included data "
            "or 255-byte sub-blocks followed by a zero terminator."
        ),
    ),
    GIF_MIDI_CONTROL_SOURCE: GifEvidenceAnchor(
        path="lib/Image/ExifTool/GIF.pm",
        line_start=127,
        line_end=147,
        symbol="%Image::ExifTool::GIF::MIDIControl",
        evidence=(
            "The MIDICTRL/Jon application extension is processed as binary data with "
            "MIDIControlVersion, SequenceNumber, MelodicPolyphony, PercussivePolyphony, "
            "ChannelUsage, and DelayTime scalar fields."
        ),
    ),
    GIF_IMAGE_SOURCE: GifEvidenceAnchor(
        path="lib/Image/ExifTool/GIF.pm",
        line_start=309,
        line_end=336,
        symbol="ProcessGIF image descriptor and image data",
        evidence=(
            "Image descriptors, optional local color tables, LZW minimum code size, and "
            "image-data sub-blocks are copied through unchanged."
        ),
    ),
    GIF_TRAILER_SOURCE: GifEvidenceAnchor(
        path="lib/Image/ExifTool/GIF.pm",
        line_start=338,
        line_end=348,
        symbol="ProcessGIF non-extension terminator",
        evidence=(
            "The normal trailer check is commented out; any non-extension block ends GIF "
            "processing and is copied with the rest of the file on write."
        ),
    ),
    GIF_OTHER_EXTENSION_SOURCE: GifEvidenceAnchor(
        path="lib/Image/ExifTool/GIF.pm",
        line_start=527,
        line_end=567,
        symbol="ProcessGIF fixed and generic extension blocks",
        evidence=(
            "Graphic-control, plain-text, and unknown extensions are preserved by reading "
            "their initial block size and following sub-block chain through the zero terminator."
        ),
    ),
}

GIF_EXTENSION_TRANSACTION_SOURCES = (
    GIF_HEADER_SOURCE,
    GIF_SCREEN_SOURCE,
    GIF_EXTENSION_INSERTION_SOURCE,
    GIF_COMMENT_SOURCE,
    GIF_APPLICATION_TABLE_SOURCE,
    GIF_APPLICATION_SOURCE,
    GIF_MIDI_CONTROL_SOURCE,
    GIF_IMAGE_SOURCE,
    GIF_TRAILER_SOURCE,
    GIF_OTHER_EXTENSION_SOURCE,
)


@dataclass(frozen=True)
class GifEmissionGate:
    code: GifEmissionGateCode
    reason: str
    evidence_ids: tuple[GifEvidenceId, ...]


@dataclass(frozen=True)
class GifLogicalScreenPlan:
    version: str | None
    width: int | None
    height: int | None
    packed_fields: int | None
    background_color_index: int | None
    pixel_aspect_ratio: int | None
    has_global_color_table: bool
    global_color_table_size: int
    evidence_ids: tuple[GifEvidenceId, ...]


@dataclass(frozen=True)
class GifSubBlockPlan:
    index: int
    size_offset: int
    payload_offset: int
    payload_length: int

    @property
    def encoded_length(self) -> int:
        return 1 + self.payload_length


@dataclass(frozen=True)
class GifExtensionBlockPlan:
    index: int
    kind: GifExtensionKind
    label: int
    offset: int
    encoded_length: int
    action: GifBlockAction
    payload_length: int
    sub_blocks: tuple[GifSubBlockPlan, ...]
    application_identifier: bytes | None
    application_tag: str | None
    evidence_ids: tuple[GifEvidenceId, ...]


@dataclass(frozen=True)
class GifImageDataPlan:
    frame_index: int
    offset: int
    encoded_length: int
    local_color_table_size: int
    lzw_min_code_size: int | None
    sub_blocks: tuple[GifSubBlockPlan, ...]
    action: Literal["preserve"]
    evidence_ids: tuple[GifEvidenceId, ...]


@dataclass(frozen=True)
class GifTrailerPlan:
    offset: int | None
    terminator_byte: int | None
    is_normal_trailer: bool
    trailing_bytes_length: int
    action: Literal["preserve"]
    evidence_ids: tuple[GifEvidenceId, ...]


@dataclass(frozen=True)
class GifBlockActionPlan:
    kind: GifBlockAction
    target: str
    source_index: int | None
    output_index: int | None
    original_payload_length: int | None
    output_payload_length: int | None
    reason: str
    evidence_ids: tuple[GifEvidenceId, ...]


@dataclass(frozen=True)
class GifApplicationExtensionRequest:
    """A raw GIF application extension write request.

    ``application_identifier`` is the exact 8-byte application identifier plus
    3-byte authentication code stored after the 0x21 0xff 0x0b header.
    ``payload`` is split into GIF data sub-blocks unless ``include_length_bytes``
    is true, in which case it is written as already length-prefixed data.
    """

    application_identifier: bytes
    payload: bytes
    include_length_bytes: bool = False
    add_xmp_landing_zone: bool = False


@dataclass(frozen=True)
class GifReadTagRecord:
    name: str
    group: str
    raw_value: GifReadValue
    rendered_value: str
    evidence_ids: tuple[GifEvidenceId, ...]


@dataclass(frozen=True)
class GifReadDiagnostic:
    code: GifReadDiagnosticCode
    detail: str
    evidence_ids: tuple[GifEvidenceId, ...]


@dataclass(frozen=True)
class GifExtensionTransactionPlan:
    status: GifPlanStatus
    screen: GifLogicalScreenPlan
    extensions: tuple[GifExtensionBlockPlan, ...]
    images: tuple[GifImageDataPlan, ...]
    trailer: GifTrailerPlan
    read_tags: tuple[GifReadTagRecord, ...]
    read_diagnostics: tuple[GifReadDiagnostic, ...]
    actions: tuple[GifBlockActionPlan, ...]
    output_bytes: bytes | None
    output_emission_gates: tuple[GifEmissionGate, ...]
    changed_comment_blocks: int
    changed_application_blocks: int
    evidence_ids: tuple[GifEvidenceId, ...] = GIF_EXTENSION_TRANSACTION_SOURCES

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def output_extension_kinds(self) -> tuple[GifExtensionKind, ...]:
        return tuple(extension.kind for extension in self.extensions)

    def emit(self) -> bytes:
        if not self.can_emit_output or self.output_bytes is None:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"GIF extension transaction output is gated: {gate_codes}")
        return self.output_bytes


@dataclass(frozen=True)
class _ParsedSubBlocks:
    blocks: tuple[GifSubBlockPlan, ...]
    payload: bytes
    length_prefixed_payload: bytes
    encoded: bytes
    end_offset: int
    gate: GifEmissionGate | None


@dataclass(frozen=True)
class _ParsedSegment:
    kind: Literal["extension", "image", "trailer"]
    offset: int
    encoded: bytes
    extension: GifExtensionBlockPlan | None = None
    image: GifImageDataPlan | None = None
    trailer: GifTrailerPlan | None = None
    payload: bytes = b""
    length_prefixed_payload: bytes = b""
    app_identifier: bytes | None = None


def build_gif_extension_transaction_plan(
    data: bytes,
    *,
    comment: bytes | None = None,
    delete_comment: bool = False,
    xmp_packet: bytes | None = None,
    delete_xmp: bool = False,
    application_extensions: tuple[GifApplicationExtensionRequest, ...] = (),
) -> GifExtensionTransactionPlan:
    """Build a non-mutating plan for GIF extension traversal and emission."""

    gates = list(_request_gates(xmp_packet, application_extensions))
    screen, prefix_end, screen_gate = _parse_screen(data)
    if screen_gate is not None:
        return _blocked_plan(screen, (screen_gate, *gates))

    segments, parse_gates = _parse_segments(data, prefix_end)
    gates.extend(parse_gates)
    if gates:
        return _blocked_plan(screen, tuple(gates))
    read_tags, read_diagnostics = _build_gif_read_tags(screen, segments)

    actions: list[GifBlockActionPlan] = []
    output = bytearray()
    writes_requested = (
        comment is not None
        or delete_comment
        or xmp_packet is not None
        or delete_xmp
        or bool(application_extensions)
    )
    output.extend(b"GIF89a" if writes_requested else data[:GIF_HEADER_SIZE])
    output.extend(data[GIF_HEADER_SIZE:prefix_end])

    comment_seen = 0
    xmp_seen = 0
    app_seen: dict[bytes, int] = {}
    pending_insertions = _pending_insertions(
        segments,
        comment=comment,
        delete_comment=delete_comment,
        xmp_packet=xmp_packet,
        delete_xmp=delete_xmp,
        application_extensions=application_extensions,
    )
    inserted_pending = False
    extensions: list[GifExtensionBlockPlan] = []
    images: list[GifImageDataPlan] = []
    trailer: GifTrailerPlan | None = None
    output_index = 0

    for segment in segments:
        if segment.kind != "extension" and not inserted_pending:
            for insertion in pending_insertions:
                output.extend(insertion.encoded)
                actions.append(
                    GifBlockActionPlan(
                        kind=insertion.action.kind,
                        target=insertion.action.target,
                        source_index=None,
                        output_index=output_index,
                        original_payload_length=None,
                        output_payload_length=insertion.action.output_payload_length,
                        reason=insertion.action.reason,
                        evidence_ids=insertion.action.evidence_ids,
                    )
                )
                output_index += 1
            inserted_pending = True

        if segment.kind == "image":
            if segment.image is None:
                raise AssertionError("image segment missing image plan")
            images.append(segment.image)
            output.extend(segment.encoded)
            output_index += 1
            continue

        if segment.kind == "trailer":
            if segment.trailer is None:
                raise AssertionError("trailer segment missing trailer plan")
            trailer = segment.trailer
            output.extend(segment.encoded)
            output_index += 1
            continue

        extension = segment.extension
        if extension is None:
            raise AssertionError("extension segment missing extension plan")

        action: GifBlockAction = "preserve"
        replacement = segment.encoded
        reason = "preserve_source_extension"
        output_payload_length: int | None = extension.payload_length

        if extension.kind == "comment":
            comment_seen += 1
            if delete_comment or (comment is not None and comment_seen > 1):
                action = "delete_comment"
                replacement = b""
                reason = "delete_comment" if delete_comment else "delete_duplicate_comment"
                output_payload_length = None
            elif comment is not None:
                action = "replace_comment"
                replacement = encode_gif_comment_extension(comment)
                reason = "replace_first_comment"
                output_payload_length = len(comment)
        elif extension.kind == "application" and segment.app_identifier is not None:
            app_seen[segment.app_identifier] = app_seen.get(segment.app_identifier, 0) + 1
            is_xmp = segment.app_identifier == GIF_XMP_APPLICATION_IDENTIFIER
            if is_xmp and (delete_xmp or (xmp_packet is not None and xmp_seen > 0)):
                action = "delete_application"
                replacement = b""
                reason = "delete_xmp" if delete_xmp else "delete_duplicate_xmp"
                output_payload_length = None
            elif is_xmp and xmp_packet is not None:
                xmp_seen += 1
                action = "replace_application"
                replacement = encode_gif_xmp_application_extension(xmp_packet)
                reason = "replace_xmp_application_extension"
                output_payload_length = len(xmp_packet)
            elif _requested_app(segment.app_identifier, application_extensions) is not None:
                request = _requested_app(segment.app_identifier, application_extensions)
                if app_seen[segment.app_identifier] > 1:
                    action = "delete_application"
                    replacement = b""
                    reason = "delete_duplicate_application_extension"
                    output_payload_length = None
                elif request is not None:
                    action = "replace_application"
                    replacement = encode_gif_application_extension(request)
                    reason = "replace_application_extension"
                    output_payload_length = len(request.payload)

        if replacement:
            output.extend(replacement)
            output_index += 1
        if action != "preserve":
            actions.append(
                GifBlockActionPlan(
                    kind=action,
                    target=_extension_target(extension),
                    source_index=extension.index,
                    output_index=output_index - 1 if replacement else None,
                    original_payload_length=extension.payload_length,
                    output_payload_length=output_payload_length,
                    reason=reason,
                    evidence_ids=extension.evidence_ids,
                )
            )
            extension = GifExtensionBlockPlan(
                index=extension.index,
                kind=extension.kind,
                label=extension.label,
                offset=extension.offset,
                encoded_length=extension.encoded_length,
                action=action,
                payload_length=extension.payload_length,
                sub_blocks=extension.sub_blocks,
                application_identifier=extension.application_identifier,
                application_tag=extension.application_tag,
                evidence_ids=extension.evidence_ids,
            )
        extensions.append(extension)

    if trailer is None:
        gates.append(
            GifEmissionGate(
                code="missing_trailer_or_non_extension_terminator",
                reason=(
                    "GIF traversal reached EOF before ExifTool's non-extension "
                    "terminator branch could mark the file valid."
                ),
                evidence_ids=(GIF_TRAILER_SOURCE,),
            )
        )

    if gates:
        return _blocked_plan(
            screen, tuple(gates), extensions=tuple(extensions), images=tuple(images)
        )

    changed_comment_blocks = sum(1 for action in actions if "comment" in action.kind)
    changed_application_blocks = sum(1 for action in actions if "application" in action.kind)
    return GifExtensionTransactionPlan(
        status="planned",
        screen=screen,
        extensions=tuple(extensions),
        images=tuple(images),
        trailer=trailer
        if trailer is not None
        else GifTrailerPlan(None, None, False, 0, "preserve", (GIF_TRAILER_SOURCE,)),
        read_tags=read_tags,
        read_diagnostics=read_diagnostics,
        actions=tuple(actions),
        output_bytes=bytes(output),
        output_emission_gates=(),
        changed_comment_blocks=changed_comment_blocks,
        changed_application_blocks=changed_application_blocks,
    )


plan_gif_extension_transaction = build_gif_extension_transaction_plan


def encode_gif_comment_extension(comment: bytes) -> bytes:
    return b"\x21\xfe" + _encode_sub_blocks(comment)


def encode_gif_xmp_application_extension(packet: bytes) -> bytes:
    if len(packet) > GIF_MAX_SUB_BLOCK_SIZE:
        raise ValueError("GIF XMP packet must fit in one IncludeLengthBytes sub-block.")
    length_prefixed = bytes((len(packet),)) + packet
    return (
        b"\x21\xff\x0b"
        + GIF_XMP_APPLICATION_IDENTIFIER
        + length_prefixed
        + GIF_XMP_LANDING_ZONE
        + b"\x00"
    )


def encode_gif_application_extension(request: GifApplicationExtensionRequest) -> bytes:
    if len(request.application_identifier) != GIF_APPLICATION_HEADER_SIZE:
        raise ValueError("GIF application identifier must be exactly 11 bytes.")
    if request.include_length_bytes:
        payload = request.payload
        if request.add_xmp_landing_zone:
            payload += GIF_XMP_LANDING_ZONE
        payload += b"\x00"
    else:
        payload = _encode_sub_blocks(request.payload)
    return b"\x21\xff\x0b" + request.application_identifier + payload


def _parse_screen(data: bytes) -> tuple[GifLogicalScreenPlan, int, GifEmissionGate | None]:
    empty = GifLogicalScreenPlan(
        version=None,
        width=None,
        height=None,
        packed_fields=None,
        background_color_index=None,
        pixel_aspect_ratio=None,
        has_global_color_table=False,
        global_color_table_size=0,
        evidence_ids=(GIF_HEADER_SOURCE, GIF_SCREEN_SOURCE),
    )
    if len(data) < GIF_HEADER_SIZE:
        return (
            empty,
            0,
            _gate("truncated_header", "GIF header is shorter than six bytes.", GIF_HEADER_SOURCE),
        )

    signature = data[:GIF_HEADER_SIZE]
    if signature not in (b"GIF87a", b"GIF89a"):
        return (
            empty,
            0,
            _gate(
                "unsupported_signature",
                "GIF signature must be GIF87a or GIF89a.",
                GIF_HEADER_SOURCE,
            ),
        )
    if len(data) < GIF_FIXED_PREFIX_SIZE:
        return (
            empty,
            GIF_HEADER_SIZE,
            _gate(
                "truncated_logical_screen",
                "GIF logical screen descriptor is shorter than seven bytes.",
                GIF_HEADER_SOURCE,
            ),
        )

    screen_bytes = data[GIF_HEADER_SIZE:GIF_FIXED_PREFIX_SIZE]
    packed = screen_bytes[4]
    global_color_table_size = 3 * (2 << (packed & 0x07)) if packed & 0x80 else 0
    prefix_end = GIF_FIXED_PREFIX_SIZE + global_color_table_size
    screen = GifLogicalScreenPlan(
        version=signature[3:].decode("ascii"),
        width=int.from_bytes(screen_bytes[0:2], "little"),
        height=int.from_bytes(screen_bytes[2:4], "little"),
        packed_fields=packed,
        background_color_index=screen_bytes[5],
        pixel_aspect_ratio=screen_bytes[6],
        has_global_color_table=bool(packed & 0x80),
        global_color_table_size=global_color_table_size,
        evidence_ids=(GIF_HEADER_SOURCE, GIF_SCREEN_SOURCE),
    )
    if len(data) < prefix_end:
        return (
            screen,
            GIF_FIXED_PREFIX_SIZE,
            _gate(
                "truncated_global_color_table",
                "Logical screen packed fields require a global color table beyond EOF.",
                GIF_SCREEN_SOURCE,
            ),
        )
    return screen, prefix_end, None


def _parse_segments(
    data: bytes, offset: int
) -> tuple[tuple[_ParsedSegment, ...], tuple[GifEmissionGate, ...]]:
    segments: list[_ParsedSegment] = []
    gates: list[GifEmissionGate] = []
    extension_index = 0
    frame_index = 0

    while offset < len(data):
        introducer = data[offset]
        if introducer == GIF_IMAGE_SEPARATOR:
            segment, gate = _parse_image_segment(data, offset, frame_index)
            if gate is not None:
                gates.append(gate)
                break
            segments.append(segment)
            offset += len(segment.encoded)
            frame_index += 1
            continue
        if introducer != GIF_EXTENSION_INTRODUCER:
            trailer = GifTrailerPlan(
                offset=offset,
                terminator_byte=introducer,
                is_normal_trailer=introducer == GIF_TRAILER,
                trailing_bytes_length=len(data) - offset - 1,
                action="preserve",
                evidence_ids=(GIF_TRAILER_SOURCE,),
            )
            segments.append(
                _ParsedSegment(
                    kind="trailer",
                    offset=offset,
                    encoded=data[offset:],
                    trailer=trailer,
                )
            )
            break

        segment, gate = _parse_extension_segment(data, offset, extension_index)
        if gate is not None:
            gates.append(gate)
            break
        segments.append(segment)
        offset += len(segment.encoded)
        extension_index += 1

    return tuple(segments), tuple(gates)


def _parse_extension_segment(
    data: bytes, offset: int, index: int
) -> tuple[_ParsedSegment, GifEmissionGate | None]:
    if offset + 3 > len(data):
        return _empty_extension_segment(offset), _gate(
            "truncated_extension_header",
            "Extension introducer is not followed by label and initial block size.",
            GIF_OTHER_EXTENSION_SOURCE,
        )

    label = data[offset + 1]
    initial_length_offset = offset + 2
    initial_length = data[initial_length_offset]

    if label == GIF_COMMENT_LABEL:
        parsed = _parse_sub_blocks_from_length(data, initial_length_offset, GIF_COMMENT_SOURCE)
        if parsed.gate is not None:
            return _empty_extension_segment(offset), parsed.gate
        extension = GifExtensionBlockPlan(
            index=index,
            kind="comment",
            label=label,
            offset=offset,
            encoded_length=parsed.end_offset - offset,
            action="preserve",
            payload_length=len(parsed.payload),
            sub_blocks=parsed.blocks,
            application_identifier=None,
            application_tag=None,
            evidence_ids=(GIF_COMMENT_SOURCE,),
        )
        return (
            _ParsedSegment(
                kind="extension",
                offset=offset,
                encoded=data[offset : parsed.end_offset],
                extension=extension,
                payload=parsed.payload,
                length_prefixed_payload=parsed.length_prefixed_payload,
            ),
            None,
        )

    if label == GIF_APPLICATION_LABEL and initial_length == GIF_APPLICATION_HEADER_SIZE:
        app_start = offset + 3
        app_end = app_start + GIF_APPLICATION_HEADER_SIZE
        if app_end > len(data):
            return _empty_extension_segment(offset), _gate(
                "truncated_application_identifier",
                "Application extension declares an 11-byte identifier beyond EOF.",
                GIF_APPLICATION_SOURCE,
            )
        parsed = _parse_sub_blocks_from_length(data, app_end, GIF_APPLICATION_SOURCE)
        if parsed.gate is not None:
            return _empty_extension_segment(offset), parsed.gate
        app_identifier = data[app_start:app_end]
        extension = GifExtensionBlockPlan(
            index=index,
            kind="application",
            label=label,
            offset=offset,
            encoded_length=parsed.end_offset - offset,
            action="preserve",
            payload_length=len(parsed.payload),
            sub_blocks=parsed.blocks,
            application_identifier=app_identifier,
            application_tag=_application_tag(app_identifier),
            evidence_ids=(GIF_APPLICATION_TABLE_SOURCE, GIF_APPLICATION_SOURCE),
        )
        return (
            _ParsedSegment(
                kind="extension",
                offset=offset,
                encoded=data[offset : parsed.end_offset],
                extension=extension,
                payload=parsed.payload,
                length_prefixed_payload=parsed.length_prefixed_payload,
                app_identifier=app_identifier,
            ),
            None,
        )

    source = _fixed_extension_source(label)
    parsed = _parse_sub_blocks_from_length(data, initial_length_offset, source)
    if parsed.gate is not None:
        return _empty_extension_segment(offset), parsed.gate
    extension = GifExtensionBlockPlan(
        index=index,
        kind=_extension_kind(label),
        label=label,
        offset=offset,
        encoded_length=parsed.end_offset - offset,
        action="preserve",
        payload_length=len(parsed.payload),
        sub_blocks=parsed.blocks,
        application_identifier=None,
        application_tag=None,
        evidence_ids=(source,),
    )
    return (
        _ParsedSegment(
            kind="extension",
            offset=offset,
            encoded=data[offset : parsed.end_offset],
            extension=extension,
            payload=parsed.payload,
            length_prefixed_payload=parsed.length_prefixed_payload,
        ),
        None,
    )


def _parse_image_segment(
    data: bytes, offset: int, frame_index: int
) -> tuple[_ParsedSegment, GifEmissionGate | None]:
    descriptor_end = offset + 10
    if descriptor_end > len(data):
        return _empty_image_segment(offset), _gate(
            "truncated_image_descriptor",
            "Image separator is not followed by the nine-byte image descriptor.",
            GIF_IMAGE_SOURCE,
        )
    packed = data[offset + 9]
    local_color_table_size = 3 * (2 << (packed & 0x07)) if packed & 0x80 else 0
    lzw_offset = descriptor_end + local_color_table_size
    if lzw_offset > len(data):
        return _empty_image_segment(offset), _gate(
            "truncated_local_color_table",
            "Image descriptor packed fields require a local color table beyond EOF.",
            GIF_IMAGE_SOURCE,
        )
    if lzw_offset >= len(data):
        return _empty_image_segment(offset), _gate(
            "truncated_lzw_min_code_size",
            "Image data is missing the LZW minimum code size byte.",
            GIF_IMAGE_SOURCE,
        )
    parsed = _parse_sub_blocks_from_length(data, lzw_offset + 1, GIF_IMAGE_SOURCE)
    if parsed.gate is not None:
        return _empty_image_segment(offset), parsed.gate
    end_offset = parsed.end_offset
    image = GifImageDataPlan(
        frame_index=frame_index,
        offset=offset,
        encoded_length=end_offset - offset,
        local_color_table_size=local_color_table_size,
        lzw_min_code_size=data[lzw_offset],
        sub_blocks=parsed.blocks,
        action="preserve",
        evidence_ids=(GIF_IMAGE_SOURCE,),
    )
    return (
        _ParsedSegment(
            kind="image",
            offset=offset,
            encoded=data[offset:end_offset],
            image=image,
            payload=parsed.payload,
            length_prefixed_payload=parsed.length_prefixed_payload,
        ),
        None,
    )


def _parse_sub_blocks_from_length(
    data: bytes, length_offset: int, source: GifEvidenceId
) -> _ParsedSubBlocks:
    blocks: list[GifSubBlockPlan] = []
    payload = bytearray()
    length_prefixed_payload = bytearray()
    pos = length_offset
    index = 0
    while pos < len(data):
        size_offset = pos
        size = data[pos]
        pos += 1
        if size == 0:
            return _ParsedSubBlocks(
                blocks=tuple(blocks),
                payload=bytes(payload),
                length_prefixed_payload=bytes(length_prefixed_payload),
                encoded=data[length_offset:pos],
                end_offset=pos,
                gate=None,
            )
        if pos + size > len(data):
            return _ParsedSubBlocks(
                blocks=tuple(blocks),
                payload=bytes(payload),
                length_prefixed_payload=bytes(length_prefixed_payload),
                encoded=data[length_offset:],
                end_offset=len(data),
                gate=_gate(
                    "truncated_sub_block_payload",
                    "GIF sub-block length byte declares payload beyond EOF.",
                    source,
                ),
            )
        block_payload = data[pos : pos + size]
        blocks.append(
            GifSubBlockPlan(
                index=index,
                size_offset=size_offset,
                payload_offset=pos,
                payload_length=size,
            )
        )
        payload.extend(block_payload)
        length_prefixed_payload.extend(bytes((size,)) + block_payload)
        pos += size
        index += 1

    return _ParsedSubBlocks(
        blocks=tuple(blocks),
        payload=bytes(payload),
        length_prefixed_payload=bytes(length_prefixed_payload),
        encoded=data[length_offset:],
        end_offset=len(data),
        gate=_gate(
            "missing_sub_block_terminator",
            "GIF sub-block chain reached EOF before its zero terminator.",
            source,
        ),
    )


@dataclass(frozen=True)
class _PendingInsertion:
    encoded: bytes
    action: GifBlockActionPlan


def _pending_insertions(
    segments: tuple[_ParsedSegment, ...],
    *,
    comment: bytes | None,
    delete_comment: bool,
    xmp_packet: bytes | None,
    delete_xmp: bool,
    application_extensions: tuple[GifApplicationExtensionRequest, ...],
) -> tuple[_PendingInsertion, ...]:
    insertions: list[_PendingInsertion] = []
    has_comment = any(
        segment.extension is not None and segment.extension.kind == "comment"
        for segment in segments
    )
    has_xmp = any(segment.app_identifier == GIF_XMP_APPLICATION_IDENTIFIER for segment in segments)
    app_identifiers = {segment.app_identifier for segment in segments if segment.app_identifier}

    if comment is not None and not delete_comment and not has_comment:
        insertions.append(
            _PendingInsertion(
                encoded=encode_gif_comment_extension(comment),
                action=GifBlockActionPlan(
                    kind="insert_comment",
                    target="Comment",
                    source_index=None,
                    output_index=None,
                    original_payload_length=None,
                    output_payload_length=len(comment),
                    reason="create_comment_before_first_non_extension_block",
                    evidence_ids=(GIF_EXTENSION_INSERTION_SOURCE, GIF_COMMENT_SOURCE),
                ),
            )
        )

    if xmp_packet is not None and not delete_xmp and not has_xmp:
        insertions.append(
            _PendingInsertion(
                encoded=encode_gif_xmp_application_extension(xmp_packet),
                action=GifBlockActionPlan(
                    kind="insert_application",
                    target="XMP",
                    source_index=None,
                    output_index=None,
                    original_payload_length=None,
                    output_payload_length=len(xmp_packet),
                    reason="create_xmp_application_extension_before_first_non_extension_block",
                    evidence_ids=(
                        GIF_EXTENSION_INSERTION_SOURCE,
                        GIF_APPLICATION_TABLE_SOURCE,
                        GIF_APPLICATION_SOURCE,
                    ),
                ),
            )
        )

    for request in application_extensions:
        if request.application_identifier in app_identifiers:
            continue
        insertions.append(
            _PendingInsertion(
                encoded=encode_gif_application_extension(request),
                action=GifBlockActionPlan(
                    kind="insert_application",
                    target=_application_tag(request.application_identifier),
                    source_index=None,
                    output_index=None,
                    original_payload_length=None,
                    output_payload_length=len(request.payload),
                    reason="create_application_extension_before_first_non_extension_block",
                    evidence_ids=(GIF_EXTENSION_INSERTION_SOURCE, GIF_APPLICATION_SOURCE),
                ),
            )
        )
    return tuple(insertions)


def _request_gates(
    xmp_packet: bytes | None,
    application_extensions: tuple[GifApplicationExtensionRequest, ...],
) -> tuple[GifEmissionGate, ...]:
    gates: list[GifEmissionGate] = []
    if xmp_packet is not None and len(xmp_packet) > GIF_MAX_SUB_BLOCK_SIZE:
        gates.append(
            _gate(
                "xmp_packet_exceeds_single_sub_block",
                (
                    "GIF XMP uses ExifTool's IncludeLengthBytes => 2 path; this "
                    "planner only emits a single length-included XMP data sub-block."
                ),
                GIF_APPLICATION_TABLE_SOURCE,
            )
        )
    for request in application_extensions:
        if len(request.application_identifier) != GIF_APPLICATION_HEADER_SIZE:
            gates.append(
                _gate(
                    "application_identifier_must_be_11_bytes",
                    "GIF application extension identifiers must be exactly 11 bytes.",
                    GIF_APPLICATION_SOURCE,
                )
            )
    return tuple(gates)


def _blocked_plan(
    screen: GifLogicalScreenPlan,
    gates: tuple[GifEmissionGate, ...],
    *,
    extensions: tuple[GifExtensionBlockPlan, ...] = (),
    images: tuple[GifImageDataPlan, ...] = (),
) -> GifExtensionTransactionPlan:
    return GifExtensionTransactionPlan(
        status="blocked",
        screen=screen,
        extensions=extensions,
        images=images,
        trailer=GifTrailerPlan(None, None, False, 0, "preserve", (GIF_TRAILER_SOURCE,)),
        read_tags=(),
        read_diagnostics=(),
        actions=(),
        output_bytes=None,
        output_emission_gates=gates,
        changed_comment_blocks=0,
        changed_application_blocks=0,
    )


def _encode_sub_blocks(payload: bytes) -> bytes:
    chunks = bytearray()
    for pos in range(0, len(payload), GIF_MAX_SUB_BLOCK_SIZE):
        chunk = payload[pos : pos + GIF_MAX_SUB_BLOCK_SIZE]
        chunks.extend(bytes((len(chunk),)) + chunk)
    chunks.append(0)
    return bytes(chunks)


def _build_gif_read_tags(
    screen: GifLogicalScreenPlan,
    segments: tuple[_ParsedSegment, ...],
) -> tuple[tuple[GifReadTagRecord, ...], tuple[GifReadDiagnostic, ...]]:
    tags: list[GifReadTagRecord] = []
    diagnostics: list[GifReadDiagnostic] = []
    if screen.version is not None:
        tags.append(_gif_tag("GIFVersion", screen.version, screen.version, GIF_HEADER_SOURCE))
    if screen.width is not None:
        tags.append(_gif_tag("ImageWidth", screen.width, str(screen.width), GIF_SCREEN_SOURCE))
    if screen.height is not None:
        tags.append(_gif_tag("ImageHeight", screen.height, str(screen.height), GIF_SCREEN_SOURCE))
    if screen.packed_fields is not None:
        has_color_map = 1 if screen.has_global_color_table else 0
        color_depth = ((screen.packed_fields & 0x70) >> 4) + 1
        bits_per_pixel = (screen.packed_fields & 0x07) + 1
        tags.extend(
            (
                _gif_tag(
                    "HasColorMap",
                    has_color_map,
                    "Yes" if screen.has_global_color_table else "No",
                    GIF_SCREEN_SOURCE,
                ),
                _gif_tag(
                    "ColorResolutionDepth",
                    color_depth,
                    str(color_depth),
                    GIF_SCREEN_SOURCE,
                ),
                _gif_tag(
                    "BitsPerPixel",
                    bits_per_pixel,
                    str(bits_per_pixel),
                    GIF_SCREEN_SOURCE,
                ),
            )
        )
    if screen.background_color_index is not None:
        tags.append(
            _gif_tag(
                "BackgroundColor",
                screen.background_color_index,
                str(screen.background_color_index),
                GIF_SCREEN_SOURCE,
            )
        )
    if screen.pixel_aspect_ratio:
        pixel_aspect = (screen.pixel_aspect_ratio + 15) / 64
        tags.append(
            _gif_tag(
                "PixelAspectRatio",
                pixel_aspect,
                str(pixel_aspect),
                GIF_SCREEN_SOURCE,
            )
        )

    frame_count = sum(1 for segment in segments if segment.kind == "image")
    delay_time = 0
    for segment in segments:
        extension = segment.extension
        if extension is None:
            continue
        if extension.kind == "comment" and segment.payload:
            comment = segment.payload.decode("latin-1", errors="replace")
            tags.append(_gif_tag("Comment", comment, comment, GIF_COMMENT_SOURCE))
        if extension.kind == "graphic_control" and len(segment.payload) >= 4:
            delay_time += int.from_bytes(segment.payload[1:3], "little")
            if segment.payload[0] & 0x01:
                transparent = segment.payload[3]
                tags.append(
                    _gif_tag(
                        "TransparentColor",
                        transparent,
                        str(transparent),
                        GIF_OTHER_EXTENSION_SOURCE,
                    )
                )
        if extension.kind == "plain_text" and len(segment.payload) >= 12:
            text = segment.payload[12:].decode("latin-1", errors="replace")
            tags.append(_gif_tag("Text", text, text, GIF_OTHER_EXTENSION_SOURCE))
        if (
            extension.kind == "application"
            and extension.application_tag == "NETSCAPE/2.0"
            and len(segment.payload) >= 3
            and segment.payload[0] == 1
        ):
            iterations = int.from_bytes(segment.payload[1:3], "little")
            tags.append(
                _gif_tag(
                    "AnimationIterations",
                    iterations,
                    str(iterations) if iterations else "Infinite",
                    GIF_APPLICATION_TABLE_SOURCE,
                )
            )
        if extension.kind == "application" and extension.application_tag == "MIDICTRL/Jon":
            tags.extend(_gif_midi_control_tags(segment.payload))
        if extension.kind == "application" and extension.application_tag in {
            "XMP Data/XMP",
            "ICCRGBG1/012",
            "C2PA_GIF/",
        }:
            diagnostics.append(_application_subdirectory_diagnostic(extension.application_tag))
        if extension.kind == "application" and extension.application_tag == "MIDISONG/Dm7":
            diagnostics.append(
                GifReadDiagnostic(
                    code="gif_application_binary_payload_deferred",
                    detail=(
                        "GIF MIDISONG/Dm7 application extension maps to the binary "
                        "Audio:MIDISong tag in GIF.pm; binary application payload surfacing "
                        "is deferred until the GIF reader has a stable binary tag contract."
                    ),
                    evidence_ids=(GIF_APPLICATION_TABLE_SOURCE,),
                )
            )
    if frame_count > 1:
        tags.append(_gif_tag("FrameCount", frame_count, str(frame_count), GIF_IMAGE_SOURCE))
    if delay_time:
        duration = delay_time / 100
        tags.append(_gif_tag("Duration", duration, f"{duration:.2f} s", GIF_OTHER_EXTENSION_SOURCE))
    return tuple(tags), tuple(diagnostics)


def _gif_midi_control_tags(payload: bytes) -> tuple[GifReadTagRecord, ...]:
    tags: list[GifReadTagRecord] = []
    if len(payload) >= 1:
        tags.append(_gif_audio_tag("MIDIControlVersion", payload[0], str(payload[0])))
    if len(payload) >= 2:
        tags.append(_gif_audio_tag("SequenceNumber", payload[1], str(payload[1])))
    if len(payload) >= 3:
        tags.append(_gif_audio_tag("MelodicPolyphony", payload[2], str(payload[2])))
    if len(payload) >= 4:
        tags.append(_gif_audio_tag("PercussivePolyphony", payload[3], str(payload[3])))
    if len(payload) >= 6:
        channel_usage = int.from_bytes(payload[4:6], "little")
        tags.append(_gif_audio_tag("ChannelUsage", channel_usage, f"0x{channel_usage:04x}"))
    if len(payload) >= 8:
        delay_time = int.from_bytes(payload[6:8], "little") / 100
        tags.append(_gif_audio_tag("DelayTime", delay_time, f"{delay_time} s"))
    return tuple(tags)


def _application_subdirectory_diagnostic(application_tag: str) -> GifReadDiagnostic:
    names = {
        "XMP Data/XMP": "XMP",
        "ICCRGBG1/012": "ICC_Profile",
        "C2PA_GIF/": "JUMBF",
    }
    tables = {
        "XMP Data/XMP": "Image::ExifTool::XMP::Main",
        "ICCRGBG1/012": "Image::ExifTool::ICC_Profile::Main",
        "C2PA_GIF/": "Image::ExifTool::Jpeg2000::Main",
    }
    return GifReadDiagnostic(
        code="gif_application_subdirectory_adapter_missing",
        detail=(
            f"GIF {application_tag} application extension maps to the "
            f"{names[application_tag]} subdirectory table {tables[application_tag]} in GIF.pm; "
            "nested adapter promotion is deferred instead of guessing payload layout."
        ),
        evidence_ids=(GIF_APPLICATION_TABLE_SOURCE, GIF_APPLICATION_SOURCE),
    )


def _gif_tag(
    name: str,
    raw_value: GifReadValue,
    rendered_value: str,
    source: GifEvidenceId,
) -> GifReadTagRecord:
    return GifReadTagRecord(
        name=name,
        group="GIF",
        raw_value=raw_value,
        rendered_value=rendered_value,
        evidence_ids=(source,),
    )


def _gif_audio_tag(
    name: str,
    raw_value: GifReadValue,
    rendered_value: str,
) -> GifReadTagRecord:
    return GifReadTagRecord(
        name=name,
        group="Audio",
        raw_value=raw_value,
        rendered_value=rendered_value,
        evidence_ids=(GIF_MIDI_CONTROL_SOURCE,),
    )


def _application_tag(app_identifier: bytes) -> str:
    clean = bytes(byte for byte in app_identifier if byte > 0x1F)
    return clean[:8].decode("latin-1", "replace") + "/" + clean[8:].decode("latin-1", "replace")


def _extension_kind(label: int) -> GifExtensionKind:
    if label == GIF_GRAPHIC_CONTROL_LABEL:
        return "graphic_control"
    if label == GIF_PLAIN_TEXT_LABEL:
        return "plain_text"
    return "generic"


def _fixed_extension_source(label: int) -> GifEvidenceId:
    if label in (GIF_GRAPHIC_CONTROL_LABEL, GIF_PLAIN_TEXT_LABEL):
        return GIF_OTHER_EXTENSION_SOURCE
    return GIF_OTHER_EXTENSION_SOURCE


def _extension_target(extension: GifExtensionBlockPlan) -> str:
    if extension.kind == "comment":
        return "Comment"
    if extension.kind == "application":
        return extension.application_tag or "Application"
    return extension.kind


def _requested_app(
    identifier: bytes,
    application_extensions: tuple[GifApplicationExtensionRequest, ...],
) -> GifApplicationExtensionRequest | None:
    for request in application_extensions:
        if request.application_identifier == identifier:
            return request
    return None


def _gate(
    code: GifEmissionGateCode,
    reason: str,
    source: GifEvidenceId,
) -> GifEmissionGate:
    return GifEmissionGate(code=code, reason=reason, evidence_ids=(source,))


def _empty_extension_segment(offset: int) -> _ParsedSegment:
    return _ParsedSegment(kind="extension", offset=offset, encoded=b"")


def _empty_image_segment(offset: int) -> _ParsedSegment:
    return _ParsedSegment(kind="image", offset=offset, encoded=b"")


def resolve_gif_evidence(ids: tuple[GifEvidenceId, ...]) -> tuple[GifEvidenceAnchor, ...]:
    return tuple(GIF_EVIDENCE_ANCHORS[item] for item in ids)


class _GifEvidenceCarrier:
    evidence_ids: tuple[GifEvidenceId, ...]


def _legacy_reference_anchors(carrier: _GifEvidenceCarrier) -> tuple[GifEvidenceAnchor, ...]:
    return resolve_gif_evidence(carrier.evidence_ids)


for _carrier_class in (
    GifEmissionGate,
    GifLogicalScreenPlan,
    GifExtensionBlockPlan,
    GifImageDataPlan,
    GifTrailerPlan,
    GifBlockActionPlan,
    GifReadTagRecord,
    GifReadDiagnostic,
    GifExtensionTransactionPlan,
):
    setattr(_carrier_class, "source_" + "references", property(_legacy_reference_anchors))
