"""Source-backed, non-mutating Ogg Theora stream transaction planning.

The planner mirrors the Theora responsibilities exposed by ExifTool's
Theora.pm: route Theora header packets, parse the identification header fields,
delegate comment payloads to Vorbis comments, preserve setup and media payloads,
and keep all byte emission behind explicit gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.ogg.page_comment_transaction_plan import (
    OGG_PACKET_BOUNDARY_SOURCE,
    OGG_PACKET_ROUTING_SOURCE,
    OGG_SEQUENCE_SOURCE,
    OggPagePlan,
    OggPlanIssue,
    OggVorbisCommentParsePlan,
    absent_vorbis_comment_parse,
    parse_vorbis_comment_payload,
    scan_ogg_pages,
)

THEORA_PACKET_PREFIX = b"theora"
THEORA_PACKET_HEADER_SIZE = 7
THEORA_IDENTIFICATION_BODY_SIZE = 35

type TheoraPlanStatus = Literal["planned", "unsupported"]
type TheoraPacketTerminalKind = Literal["complete_segment", "eos_forced", "open_at_eof"]
type TheoraPacketRouteKind = Literal[
    "identification",
    "comments",
    "setup",
    "payload",
    "non_theora_preserved",
]
type TheoraIdentificationStatus = Literal["absent", "valid", "truncated", "malformed"]
type TheoraPreservationKind = Literal[
    "theora_header_packet",
    "theora_comment_packet",
    "theora_setup_packet",
    "theora_payload_packet",
    "non_theora_packet",
]
type TheoraResponsibilityKind = Literal[
    "theora_packet_routing",
    "identification_header",
    "image_dimensions",
    "frame_rate",
    "pixel_aspect_ratio",
    "color_space",
    "pixel_format",
    "comment_boundary",
    "setup_preservation",
    "stream_payload_preservation",
    "rewrite_boundary",
]
type TheoraResponsibilityValue = int | float | str | bool | tuple[int, int] | None
type TheoraEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_ogg_page_header",
    "ogg_capture_pattern",
    "truncated_segment_table",
    "truncated_page_payload",
    "empty_ogg_input",
    "missing_ogg_page_sequence",
    "dangling_continuation_page",
    "unterminated_ogg_packet",
    "missing_theora_identification",
    "truncated_theora_packet_header",
    "truncated_theora_identification",
    "malformed_theora_identification",
    "malformed_theora_comments",
    "theora_metadata_rewrite_not_supported",
    "ogg_theora_stream_rewrite_not_implemented",
]

THEORA_PM_SOURCE_PATH = "lib/Image/ExifTool/Theora.pm"

THEORA_MAIN_SOURCE = "theora.main"
THEORA_IDENTIFICATION_SOURCE = "theora.identification"
THEORA_PACKET_ROUTING_SOURCE = "theora.packet.routing"
THEORA_PACKET_BOUNDARY_SOURCE = "theora.packet.boundary"
VORBIS_COMMENT_SOURCE = "vorbis.comment"
THEORA_NON_MUTATING_SOURCE = "theora.non.mutating"

THEORA_TRANSACTION_SOURCES = (
    THEORA_MAIN_SOURCE,
    THEORA_IDENTIFICATION_SOURCE,
    THEORA_PACKET_ROUTING_SOURCE,
    THEORA_PACKET_BOUNDARY_SOURCE,
    VORBIS_COMMENT_SOURCE,
    THEORA_NON_MUTATING_SOURCE,
)

THEORA_COLOR_SPACES: dict[int, str] = {
    0: "Undefined",
    1: "Rec. 470M",
    2: "Rec. 470BG",
}
THEORA_PIXEL_FORMATS: dict[int, str] = {
    0: "4:2:0",
    2: "4:2:2",
    3: "4:4:4",
}


@dataclass(frozen=True)
class TheoraMetadataRewriteRequest:
    image_width: int | None = None
    image_height: int | None = None
    comment_payload: bytes | None = None


@dataclass(frozen=True)
class TheoraPacketPlan:
    packet_index: int
    stream_serial: int
    start_page_index: int
    end_page_index: int
    terminal_kind: TheoraPacketTerminalKind
    route_kind: TheoraPacketRouteKind
    header_type: int | None
    payload: bytes
    payload_length: int
    first_payload_offset: int | None
    last_payload_end_offset: int | None
    page_indices: tuple[int, ...]
    blocker_code: TheoraEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TheoraIdentificationPlan:
    status: TheoraIdentificationStatus
    packet_index: int | None
    body_offset: int | None
    version: str | None
    image_width: int | None
    image_height: int | None
    x_offset: int | None
    y_offset: int | None
    frame_rate_numerator: int | None
    frame_rate_denominator: int | None
    frame_rate: float | None
    pixel_aspect_numerator: int | None
    pixel_aspect_denominator: int | None
    pixel_aspect_ratio: float | None
    color_space_code: int | None
    color_space: str | None
    nominal_video_bitrate: int | None
    quality: int | None
    pixel_format_code: int | None
    pixel_format: str | None
    blocker_code: TheoraEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TheoraCommentPlan:
    packet_index: int
    comment_payload_offset: int | None
    comment_payload_length: int
    parse: OggVorbisCommentParsePlan
    blocker_code: TheoraEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TheoraPreservationPlan:
    packet_index: int
    kind: TheoraPreservationKind
    stream_serial: int
    page_indices: tuple[int, ...]
    payload: bytes
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TheoraResponsibilityPlan:
    kind: TheoraResponsibilityKind
    available: bool
    value: TheoraResponsibilityValue
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TheoraOutputEmissionGate:
    code: TheoraEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TheoraStreamTransactionPlan:
    status: TheoraPlanStatus
    input_size: int
    pages: tuple[OggPagePlan, ...]
    packets: tuple[TheoraPacketPlan, ...]
    identification: TheoraIdentificationPlan
    comments: tuple[TheoraCommentPlan, ...]
    preservation_actions: tuple[TheoraPreservationPlan, ...]
    responsibilities: tuple[TheoraResponsibilityPlan, ...]
    output_emission_gates: tuple[TheoraOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Theora stream transaction output is gated: {gate_codes}")
        return self.original_bytes


@dataclass(frozen=True)
class _OpenTheoraPacket:
    stream_serial: int
    start_page_index: int
    chunks: tuple[bytes, ...]
    first_payload_offset: int | None
    last_payload_end_offset: int | None
    page_indices: tuple[int, ...]


def build_theora_stream_transaction_plan(
    theora_data: bytes,
    *,
    requested_metadata: TheoraMetadataRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> TheoraStreamTransactionPlan:
    pages, scan_issues = scan_ogg_pages(theora_data)
    packets, packet_issues = _assemble_packets(theora_data, pages)
    identification = _build_identification_plan(packets)
    comments = tuple(
        _build_comment_plan(packet) for packet in packets if packet.route_kind == "comments"
    )
    preservation_actions = tuple(_preservation_action(packet) for packet in packets)

    gates = [
        *(_gate_for_ogg_issue(issue) for issue in (*scan_issues, *packet_issues)),
        *(_gate_for_packet(packet) for packet in packets if packet.blocker_code is not None),
    ]
    if identification.blocker_code is not None:
        gates.append(_gate_for_identification(identification))
    malformed_comments = tuple(comment for comment in comments if comment.blocker_code is not None)
    gates.extend(_gate_for_comment(comment) for comment in malformed_comments)
    if _has_rewrite_request(requested_metadata):
        gates.extend(
            (
                TheoraOutputEmissionGate(
                    "theora_metadata_rewrite_not_supported",
                    (
                        "Theora.pm defines read extraction and Vorbis comment delegation; "
                        "it does not define writable Theora tags."
                    ),
                    (THEORA_MAIN_SOURCE, THEORA_IDENTIFICATION_SOURCE, VORBIS_COMMENT_SOURCE),
                ),
                TheoraOutputEmissionGate(
                    "ogg_theora_stream_rewrite_not_implemented",
                    "This planner preserves packet payloads and does not rebuild Ogg pages.",
                    (THEORA_PACKET_BOUNDARY_SOURCE, THEORA_NON_MUTATING_SOURCE),
                ),
            )
        )
    if not allow_output_emission:
        gates.append(
            TheoraOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "Theora stream transaction plans are non-mutating unless emission is explicit.",
                (THEORA_NON_MUTATING_SOURCE,),
            )
        )

    output_gates = _unique_gates(tuple(gates))
    status: TheoraPlanStatus = "unsupported" if _has_structural_gate(output_gates) else "planned"
    return TheoraStreamTransactionPlan(
        status=status,
        input_size=len(theora_data),
        pages=pages,
        packets=packets,
        identification=identification,
        comments=comments,
        preservation_actions=preservation_actions,
        responsibilities=_responsibility_plans(
            packets=packets,
            identification=identification,
            comments=comments,
            preservation_actions=preservation_actions,
        ),
        output_emission_gates=output_gates,
        evidence_ids=THEORA_TRANSACTION_SOURCES,
        original_bytes=theora_data,
    )


def _assemble_packets(
    data: bytes, pages: tuple[OggPagePlan, ...]
) -> tuple[tuple[TheoraPacketPlan, ...], tuple[OggPlanIssue, ...]]:
    packets: list[TheoraPacketPlan] = []
    issues: list[OggPlanIssue] = []
    open_packets: dict[int, _OpenTheoraPacket] = {}
    ignoring_continuation: set[int] = set()

    for page in pages:
        if page.is_continuation and page.bitstream_serial not in open_packets:
            ignoring_continuation.add(page.bitstream_serial)
            issues.append(
                OggPlanIssue(
                    code="dangling_continuation_page",
                    message="Theora packet continuation appeared without a buffered start.",
                    offset=page.offset,
                    page_index=page.index,
                    evidence_ids=(THEORA_PACKET_BOUNDARY_SOURCE,),
                )
            )

        for segment in page.segments:
            chunk = data[segment.payload_offset : segment.payload_end_offset]
            open_packet = open_packets.get(page.bitstream_serial)
            if open_packet is None:
                if page.bitstream_serial in ignoring_continuation:
                    if segment.completes_packet:
                        ignoring_continuation.remove(page.bitstream_serial)
                    continue
                open_packet = _OpenTheoraPacket(
                    stream_serial=page.bitstream_serial,
                    start_page_index=page.index,
                    chunks=(),
                    first_payload_offset=segment.payload_offset,
                    last_payload_end_offset=None,
                    page_indices=(page.index,),
                )

            page_indices = open_packet.page_indices
            if not page_indices or page_indices[-1] != page.index:
                page_indices = (*page_indices, page.index)
            chunks = (*open_packet.chunks, chunk)
            if segment.completes_packet:
                payload = b"".join(chunks)
                packets.append(
                    _classify_packet(
                        packet_index=len(packets),
                        stream_serial=page.bitstream_serial,
                        start_page_index=open_packet.start_page_index,
                        end_page_index=page.index,
                        terminal_kind="complete_segment",
                        payload=payload,
                        first_payload_offset=open_packet.first_payload_offset,
                        last_payload_end_offset=segment.payload_end_offset,
                        page_indices=page_indices,
                    )
                )
                open_packets.pop(page.bitstream_serial, None)
            else:
                open_packets[page.bitstream_serial] = _OpenTheoraPacket(
                    stream_serial=page.bitstream_serial,
                    start_page_index=open_packet.start_page_index,
                    chunks=chunks,
                    first_payload_offset=open_packet.first_payload_offset,
                    last_payload_end_offset=segment.payload_end_offset,
                    page_indices=page_indices,
                )

        if page.is_end_of_stream and page.bitstream_serial in open_packets:
            open_packet = open_packets.pop(page.bitstream_serial)
            payload = b"".join(open_packet.chunks)
            packets.append(
                _classify_packet(
                    packet_index=len(packets),
                    stream_serial=page.bitstream_serial,
                    start_page_index=open_packet.start_page_index,
                    end_page_index=page.index,
                    terminal_kind="eos_forced",
                    payload=payload,
                    first_payload_offset=open_packet.first_payload_offset,
                    last_payload_end_offset=open_packet.last_payload_end_offset,
                    page_indices=open_packet.page_indices,
                )
            )

    for stream_serial, open_packet in sorted(open_packets.items()):
        packets.append(
            _classify_packet(
                packet_index=len(packets),
                stream_serial=stream_serial,
                start_page_index=open_packet.start_page_index,
                end_page_index=pages[-1].index if pages else open_packet.start_page_index,
                terminal_kind="open_at_eof",
                payload=b"".join(open_packet.chunks),
                first_payload_offset=open_packet.first_payload_offset,
                last_payload_end_offset=open_packet.last_payload_end_offset,
                page_indices=open_packet.page_indices,
            )
        )
        issues.append(
            OggPlanIssue(
                code="unterminated_ogg_packet",
                message=f"Stream {stream_serial} ended with an unterminated Theora packet.",
                offset=None,
                page_index=open_packet.start_page_index,
                evidence_ids=(THEORA_PACKET_BOUNDARY_SOURCE,),
            )
        )

    return tuple(packets), tuple(issues)


def _classify_packet(
    *,
    packet_index: int,
    stream_serial: int,
    start_page_index: int,
    end_page_index: int,
    terminal_kind: TheoraPacketTerminalKind,
    payload: bytes,
    first_payload_offset: int | None,
    last_payload_end_offset: int | None,
    page_indices: tuple[int, ...],
) -> TheoraPacketPlan:
    blocker_code: TheoraEmissionGateCode | None = None
    header_type: int | None = None
    route_kind: TheoraPacketRouteKind = "non_theora_preserved"
    references: tuple[str, ...] = (THEORA_PACKET_BOUNDARY_SOURCE,)

    if len(payload) < THEORA_PACKET_HEADER_SIZE:
        if payload.startswith(THEORA_PACKET_PREFIX[: max(0, len(payload) - 1)], 1):
            blocker_code = "truncated_theora_packet_header"
            references = (THEORA_PACKET_ROUTING_SOURCE, THEORA_MAIN_SOURCE)
    elif payload[1:THEORA_PACKET_HEADER_SIZE] == THEORA_PACKET_PREFIX:
        header_type = payload[0]
        references = (THEORA_PACKET_ROUTING_SOURCE, THEORA_MAIN_SOURCE)
        if header_type == 0x80:
            route_kind = "identification"
        elif header_type == 0x81:
            route_kind = "comments"
        elif header_type == 0x82:
            route_kind = "setup"
        else:
            route_kind = "payload"

    return TheoraPacketPlan(
        packet_index=packet_index,
        stream_serial=stream_serial,
        start_page_index=start_page_index,
        end_page_index=end_page_index,
        terminal_kind=terminal_kind,
        route_kind=route_kind,
        header_type=header_type,
        payload=payload,
        payload_length=len(payload),
        first_payload_offset=first_payload_offset,
        last_payload_end_offset=last_payload_end_offset,
        page_indices=page_indices,
        blocker_code=blocker_code,
        evidence_ids=references,
    )


def _build_identification_plan(packets: tuple[TheoraPacketPlan, ...]) -> TheoraIdentificationPlan:
    for packet in packets:
        if packet.route_kind == "identification":
            return _parse_identification_packet(packet)
    return TheoraIdentificationPlan(
        status="absent",
        packet_index=None,
        body_offset=None,
        version=None,
        image_width=None,
        image_height=None,
        x_offset=None,
        y_offset=None,
        frame_rate_numerator=None,
        frame_rate_denominator=None,
        frame_rate=None,
        pixel_aspect_numerator=None,
        pixel_aspect_denominator=None,
        pixel_aspect_ratio=None,
        color_space_code=None,
        color_space=None,
        nominal_video_bitrate=None,
        quality=None,
        pixel_format_code=None,
        pixel_format=None,
        blocker_code="missing_theora_identification",
        evidence_ids=(THEORA_MAIN_SOURCE, THEORA_IDENTIFICATION_SOURCE),
    )


def _parse_identification_packet(packet: TheoraPacketPlan) -> TheoraIdentificationPlan:
    body = packet.payload[THEORA_PACKET_HEADER_SIZE:]
    body_offset = (
        packet.first_payload_offset + THEORA_PACKET_HEADER_SIZE
        if packet.first_payload_offset is not None
        else None
    )
    if len(body) < THEORA_IDENTIFICATION_BODY_SIZE:
        return _identification_failure(
            status="truncated",
            packet_index=packet.packet_index,
            body_offset=body_offset,
            blocker_code="truncated_theora_identification",
        )

    frame_rate_numerator = int.from_bytes(body[15:19], "big")
    frame_rate_denominator = int.from_bytes(body[19:23], "big")
    pixel_aspect_numerator = int.from_bytes(body[23:26], "big")
    pixel_aspect_denominator = int.from_bytes(body[26:29], "big")
    if frame_rate_denominator == 0 or pixel_aspect_denominator == 0:
        return _identification_failure(
            status="malformed",
            packet_index=packet.packet_index,
            body_offset=body_offset,
            blocker_code="malformed_theora_identification",
        )

    color_space_code = body[29]
    pixel_format_code = (body[34] >> 3) & 0x03
    nominal_video_bitrate = int.from_bytes(body[30:34], "big") >> 8
    return TheoraIdentificationPlan(
        status="valid",
        packet_index=packet.packet_index,
        body_offset=body_offset,
        version=f"{body[0]}.{body[1]}.{body[2]}",
        image_width=int.from_bytes(body[7:11], "big") >> 8,
        image_height=int.from_bytes(body[10:14], "big") >> 8,
        x_offset=body[13],
        y_offset=body[14],
        frame_rate_numerator=frame_rate_numerator,
        frame_rate_denominator=frame_rate_denominator,
        frame_rate=round(frame_rate_numerator / frame_rate_denominator, 3),
        pixel_aspect_numerator=pixel_aspect_numerator,
        pixel_aspect_denominator=pixel_aspect_denominator,
        pixel_aspect_ratio=round(pixel_aspect_numerator / pixel_aspect_denominator, 3),
        color_space_code=color_space_code,
        color_space=THEORA_COLOR_SPACES.get(color_space_code),
        nominal_video_bitrate=nominal_video_bitrate,
        quality=body[33] >> 2,
        pixel_format_code=pixel_format_code,
        pixel_format=THEORA_PIXEL_FORMATS.get(pixel_format_code),
        blocker_code=None,
        evidence_ids=(THEORA_IDENTIFICATION_SOURCE,),
    )


def _identification_failure(
    *,
    status: Literal["truncated", "malformed"],
    packet_index: int,
    body_offset: int | None,
    blocker_code: TheoraEmissionGateCode,
) -> TheoraIdentificationPlan:
    return TheoraIdentificationPlan(
        status=status,
        packet_index=packet_index,
        body_offset=body_offset,
        version=None,
        image_width=None,
        image_height=None,
        x_offset=None,
        y_offset=None,
        frame_rate_numerator=None,
        frame_rate_denominator=None,
        frame_rate=None,
        pixel_aspect_numerator=None,
        pixel_aspect_denominator=None,
        pixel_aspect_ratio=None,
        color_space_code=None,
        color_space=None,
        nominal_video_bitrate=None,
        quality=None,
        pixel_format_code=None,
        pixel_format=None,
        blocker_code=blocker_code,
        evidence_ids=(THEORA_IDENTIFICATION_SOURCE,),
    )


def _build_comment_plan(packet: TheoraPacketPlan) -> TheoraCommentPlan:
    payload = packet.payload[THEORA_PACKET_HEADER_SIZE:]
    parse = parse_vorbis_comment_payload(payload)
    blocker_code: TheoraEmissionGateCode | None = (
        "malformed_theora_comments" if parse.status == "malformed" else None
    )
    return TheoraCommentPlan(
        packet_index=packet.packet_index,
        comment_payload_offset=(
            packet.first_payload_offset + THEORA_PACKET_HEADER_SIZE
            if packet.first_payload_offset is not None
            else None
        ),
        comment_payload_length=len(payload),
        parse=parse,
        blocker_code=blocker_code,
        evidence_ids=(THEORA_MAIN_SOURCE, VORBIS_COMMENT_SOURCE),
    )


def _preservation_action(packet: TheoraPacketPlan) -> TheoraPreservationPlan:
    if packet.route_kind == "identification":
        kind: TheoraPreservationKind = "theora_header_packet"
        reason = "Theora identification bytes are parsed for metadata and preserved."
    elif packet.route_kind == "comments":
        kind = "theora_comment_packet"
        reason = "Theora comment packet boundary is recorded and preserved."
    elif packet.route_kind == "setup":
        kind = "theora_setup_packet"
        reason = "Theora setup packets are documented but not parsed by Theora.pm."
    elif packet.route_kind == "payload":
        kind = "theora_payload_packet"
        reason = "Unrecognized Theora packet types are outside Theora.pm read tables."
    else:
        kind = "non_theora_packet"
        reason = "Non-Theora packets are outside this planner and are preserved."
    return TheoraPreservationPlan(
        packet_index=packet.packet_index,
        kind=kind,
        stream_serial=packet.stream_serial,
        page_indices=packet.page_indices,
        payload=packet.payload,
        reason=reason,
        evidence_ids=packet.evidence_ids,
    )


def _responsibility_plans(
    *,
    packets: tuple[TheoraPacketPlan, ...],
    identification: TheoraIdentificationPlan,
    comments: tuple[TheoraCommentPlan, ...],
    preservation_actions: tuple[TheoraPreservationPlan, ...],
) -> tuple[TheoraResponsibilityPlan, ...]:
    parsed = identification.status == "valid"
    setup_count = sum(1 for packet in packets if packet.route_kind == "setup")
    payload_count = sum(1 for packet in packets if packet.route_kind == "payload")
    return (
        TheoraResponsibilityPlan(
            "theora_packet_routing",
            True,
            sum(1 for packet in packets if packet.header_type is not None),
            "Theora.pm receives Ogg packets routed by one-byte Theora header type.",
            (THEORA_MAIN_SOURCE, THEORA_PACKET_ROUTING_SOURCE),
        ),
        TheoraResponsibilityPlan(
            "identification_header",
            parsed,
            identification.version,
            "Packet type 0x80 is the Theora identification subdirectory.",
            (THEORA_MAIN_SOURCE, THEORA_IDENTIFICATION_SOURCE),
        ),
        TheoraResponsibilityPlan(
            "image_dimensions",
            parsed,
            (
                (identification.image_width, identification.image_height)
                if identification.image_width is not None
                and identification.image_height is not None
                else None
            ),
            "ImageWidth and ImageHeight are 24-bit values read through int32u shifts.",
            (THEORA_IDENTIFICATION_SOURCE,),
        ),
        TheoraResponsibilityPlan(
            "frame_rate",
            parsed and identification.frame_rate is not None,
            identification.frame_rate,
            "FrameRate is a big-endian rational64u at identification offset 15.",
            (THEORA_IDENTIFICATION_SOURCE,),
        ),
        TheoraResponsibilityPlan(
            "pixel_aspect_ratio",
            parsed and identification.pixel_aspect_ratio is not None,
            identification.pixel_aspect_ratio,
            "PixelAspectRatio is derived from two 24-bit values at offset 23.",
            (THEORA_IDENTIFICATION_SOURCE,),
        ),
        TheoraResponsibilityPlan(
            "color_space",
            parsed and identification.color_space is not None,
            identification.color_space,
            "ColorSpace maps codes 0, 1, and 2 to Theora.pm labels.",
            (THEORA_IDENTIFICATION_SOURCE,),
        ),
        TheoraResponsibilityPlan(
            "pixel_format",
            parsed and identification.pixel_format is not None,
            identification.pixel_format,
            "PixelFormat maps identification byte 34 bits 3-4 to chroma labels.",
            (THEORA_IDENTIFICATION_SOURCE,),
        ),
        TheoraResponsibilityPlan(
            "comment_boundary",
            bool(comments),
            len(comments),
            "Packet type 0x81 starts a Vorbis comment payload at byte 7.",
            (THEORA_MAIN_SOURCE, VORBIS_COMMENT_SOURCE),
        ),
        TheoraResponsibilityPlan(
            "setup_preservation",
            setup_count > 0,
            setup_count,
            "Packet type 0x82 is setup and is preserved without a Theora.pm parser.",
            (THEORA_MAIN_SOURCE,),
        ),
        TheoraResponsibilityPlan(
            "stream_payload_preservation",
            bool(preservation_actions),
            len(preservation_actions) + payload_count,
            "All planned packet payloads remain byte-preserved by default.",
            (THEORA_PACKET_BOUNDARY_SOURCE, THEORA_NON_MUTATING_SOURCE),
        ),
        TheoraResponsibilityPlan(
            "rewrite_boundary",
            False,
            None,
            "Theora.pm defines read tables only; this planner has no Ogg page rebuild path.",
            (THEORA_MAIN_SOURCE, THEORA_NON_MUTATING_SOURCE),
        ),
    )


def _gate_for_ogg_issue(issue: OggPlanIssue) -> TheoraOutputEmissionGate:
    code: TheoraEmissionGateCode
    if issue.code == "truncated_page_header":
        code = "truncated_ogg_page_header"
    elif issue.code == "ogg_capture_pattern":
        code = "ogg_capture_pattern"
    elif issue.code == "truncated_segment_table":
        code = "truncated_segment_table"
    elif issue.code == "truncated_page_payload":
        code = "truncated_page_payload"
    elif issue.code == "empty_ogg_input":
        code = "empty_ogg_input"
    elif issue.code == "missing_ogg_page_sequence":
        code = "missing_ogg_page_sequence"
    elif issue.code == "dangling_continuation_page":
        code = "dangling_continuation_page"
    else:
        code = "unterminated_ogg_packet"
    return TheoraOutputEmissionGate(
        code=code,
        reason=issue.message,
        evidence_ids=_evidence_ids_for_issue(issue),
    )


def _evidence_ids_for_issue(issue: OggPlanIssue) -> tuple[str, ...]:
    reference_ids = tuple(
        reference_id
        for reference_id in issue.evidence_ids
        if reference_id
        not in {
            OGG_PACKET_BOUNDARY_SOURCE,
            OGG_PACKET_ROUTING_SOURCE,
            OGG_SEQUENCE_SOURCE,
        }
    )
    references = tuple(
        reference
        for reference_id in reference_ids
        for reference in THEORA_TRANSACTION_SOURCES
        if reference == reference_id
    )
    if references:
        return references
    return (THEORA_PACKET_BOUNDARY_SOURCE,)


def _gate_for_packet(packet: TheoraPacketPlan) -> TheoraOutputEmissionGate:
    return TheoraOutputEmissionGate(
        code=packet.blocker_code or "truncated_theora_packet_header",
        reason=(
            "Theora packet header is shorter than the routed one-byte tag plus theora signature."
        ),
        evidence_ids=packet.evidence_ids,
    )


def _gate_for_identification(
    identification: TheoraIdentificationPlan,
) -> TheoraOutputEmissionGate:
    if identification.blocker_code == "missing_theora_identification":
        reason = "No packet type 0x80 Theora identification header was found."
    elif identification.blocker_code == "truncated_theora_identification":
        reason = "Theora identification payload is shorter than fields defined by Theora.pm."
    else:
        reason = "Theora identification contains a zero rational denominator."
    return TheoraOutputEmissionGate(
        code=identification.blocker_code or "malformed_theora_identification",
        reason=reason,
        evidence_ids=identification.evidence_ids,
    )


def _gate_for_comment(comment: TheoraCommentPlan) -> TheoraOutputEmissionGate:
    reason = "Theora comment packet did not contain a valid Vorbis comment payload."
    if comment.parse.issue is not None:
        reason = comment.parse.issue.message
    return TheoraOutputEmissionGate(
        code=comment.blocker_code or "malformed_theora_comments",
        reason=reason,
        evidence_ids=comment.evidence_ids,
    )


def _has_rewrite_request(requested_metadata: TheoraMetadataRewriteRequest | None) -> bool:
    return requested_metadata is not None and (
        requested_metadata.image_width is not None
        or requested_metadata.image_height is not None
        or requested_metadata.comment_payload is not None
    )


def _unique_gates(
    gates: tuple[TheoraOutputEmissionGate, ...],
) -> tuple[TheoraOutputEmissionGate, ...]:
    unique: list[TheoraOutputEmissionGate] = []
    seen: set[TheoraEmissionGateCode] = set()
    for gate in gates:
        if gate.code in seen:
            continue
        unique.append(gate)
        seen.add(gate.code)
    return tuple(unique)


def _has_structural_gate(gates: tuple[TheoraOutputEmissionGate, ...]) -> bool:
    return any(
        gate.code
        not in {
            "non_mutating_plan_requires_explicit_emission",
            "theora_metadata_rewrite_not_supported",
            "ogg_theora_stream_rewrite_not_implemented",
        }
        for gate in gates
    )


def absent_theora_comment_parse() -> OggVorbisCommentParsePlan:
    return absent_vorbis_comment_parse()
