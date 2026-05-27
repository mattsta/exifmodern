"""Source-backed Ogg page and comment transaction planning.

The planner mirrors ExifTool's Ogg page traversal and packet routing decisions
without mutating files.  It validates OggS capture patterns, walks page lacing
values into packet boundaries, classifies Vorbis/Theora/Opus comment packets,
preserves unknown streams, and exposes explicit gates that block emission until
CRC, lacing, and page reconstruction are implemented.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.flac.vorbis_comment_transaction_plan import (
    FLAC_PICTURE_SOURCE,
    XMP_BASE64_DECODE_SOURCE,
    FlacPictureCommentPlan,
    parse_metadata_block_picture_comment,
)

OGG_CAPTURE_PATTERN = b"OggS"
OGG_FIXED_HEADER_SIZE = 27
OGG_CONTINUATION_FLAG = 0x01
OGG_BOS_FLAG = 0x02
OGG_EOS_FLAG = 0x04
OGG_LACING_CONTINUES = 255

type OggPageSequenceStatus = Literal["expected", "missing", "untracked"]
type OggPacketTerminalKind = Literal["complete_segment", "eos_forced", "open_at_eof"]
type OggCodecKind = Literal["vorbis", "theora", "opus", "flac", "speex", "unknown"]
type OggPacketRouteKind = Literal[
    "comment",
    "codec_header",
    "codec_setup",
    "flac_header",
    "speex_preserved_unsupported",
    "unknown_preserved",
]
type OggVorbisCommentParseStatus = Literal["absent", "valid", "malformed"]
type OggPreservationActionKind = Literal["preserve_routed_page", "preserve_unknown_page"]
type OggFlacHandoffStatus = Literal["absent", "assembled", "malformed_header", "truncated_headers"]

OGG_MAIN_SOURCE = "ogg.main"
OGG_PACKET_ROUTING_SOURCE = "ogg.packet_routing"
OGG_PAGE_TRAVERSAL_SOURCE = "ogg.page_traversal"
OGG_PACKET_BOUNDARY_SOURCE = "ogg.packet_boundary"
OGG_PACKET_LIMIT_SOURCE = "ogg.packet_limit"
OGG_SEQUENCE_SOURCE = "ogg.sequence"
VORBIS_MAIN_SOURCE = "vorbis.main"
THEORA_MAIN_SOURCE = "theora.main"
OPUS_MAIN_SOURCE = "opus.main"
VORBIS_COMMENT_PARSE_SOURCE = "vorbis.comment_parse.2"
VORBIS_PICTURE_COMMENT_SOURCE = "vorbis.picture_comment.2"
SPEEX_PRESERVATION_SOURCE = "speex.preservation"
OGG_CRC_REWRITE_BLOCKER_SOURCE = "ogg.crc_rewrite_blocker"
OGG_FLAC_HANDOFF_SOURCE = "ogg.flac_handoff"

OGG_PAGE_COMMENT_TRANSACTION_SOURCES = (
    OGG_MAIN_SOURCE,
    OGG_PACKET_ROUTING_SOURCE,
    OGG_PAGE_TRAVERSAL_SOURCE,
    OGG_PACKET_BOUNDARY_SOURCE,
    OGG_PACKET_LIMIT_SOURCE,
    OGG_SEQUENCE_SOURCE,
    VORBIS_MAIN_SOURCE,
    THEORA_MAIN_SOURCE,
    OPUS_MAIN_SOURCE,
    VORBIS_COMMENT_PARSE_SOURCE,
    VORBIS_PICTURE_COMMENT_SOURCE,
    SPEEX_PRESERVATION_SOURCE,
    OGG_CRC_REWRITE_BLOCKER_SOURCE,
    OGG_FLAC_HANDOFF_SOURCE,
)


@dataclass(frozen=True)
class OggPlanIssue:
    code: str
    message: str
    offset: int | None
    page_index: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OggEmissionGate:
    code: str
    passed: bool
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OggSegmentPlan:
    page_index: int
    segment_index: int
    length: int
    payload_offset: int
    payload_end_offset: int
    completes_packet: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OggPagePlan:
    index: int
    offset: int
    data_offset: int
    end_offset: int
    version: int
    header_type: int
    granule_position: int
    bitstream_serial: int
    page_sequence: int
    checksum: int
    segment_lengths: tuple[int, ...]
    payload_length: int
    sequence_status: OggPageSequenceStatus
    expected_page_sequence: int | None
    segments: tuple[OggSegmentPlan, ...]
    evidence_ids: tuple[str, ...]

    @property
    def is_continuation(self) -> bool:
        return bool(self.header_type & OGG_CONTINUATION_FLAG)

    @property
    def is_beginning_of_stream(self) -> bool:
        return bool(self.header_type & OGG_BOS_FLAG)

    @property
    def is_end_of_stream(self) -> bool:
        return bool(self.header_type & OGG_EOS_FLAG)


@dataclass(frozen=True)
class OggVorbisCommentEntryPlan:
    index: int
    tag: str
    value: str
    raw_length: int
    routes_to_flac_picture: bool
    picture_comment: FlacPictureCommentPlan | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OggVorbisCommentParsePlan:
    status: OggVorbisCommentParseStatus
    vendor: str | None
    declared_comment_count: int | None
    parsed_comment_count: int
    entries: tuple[OggVorbisCommentEntryPlan, ...]
    issue: OggPlanIssue | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OggPacketRoutePlan:
    packet_index: int
    stream_serial: int
    start_page_index: int
    end_page_index: int
    terminal_kind: OggPacketTerminalKind
    codec: OggCodecKind
    route_kind: OggPacketRouteKind
    comment_dir_start: int | None
    packet_tag: int | str | None
    payload_length: int
    comment_parse: OggVorbisCommentParsePlan
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OggPagePreservationPlan:
    page_index: int
    stream_serial: int
    action: OggPreservationActionKind
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OggFlacHandoffPlan:
    status: OggFlacHandoffStatus
    stream_serial: int | None
    start_packet_index: int | None
    declared_header_packets: int | None
    assembled_header_packets: int
    synthetic_flac_stream: bytes | None
    issue: OggPlanIssue | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OggPageCommentTransactionPlan:
    input_size: int
    pages: tuple[OggPagePlan, ...]
    packet_routes: tuple[OggPacketRoutePlan, ...]
    preservation_actions: tuple[OggPagePreservationPlan, ...]
    requested_comment_parse: OggVorbisCommentParsePlan
    flac_handoff: OggFlacHandoffPlan
    issues: tuple[OggPlanIssue, ...]
    emission_gates: tuple[OggEmissionGate, ...]
    oracle_evidence_ids: tuple[str, ...] = OGG_PAGE_COMMENT_TRANSACTION_SOURCES

    @property
    def can_emit(self) -> bool:
        return all(gate.passed for gate in self.emission_gates)

    @property
    def comment_routes(self) -> tuple[OggPacketRoutePlan, ...]:
        return tuple(route for route in self.packet_routes if route.route_kind == "comment")

    @property
    def unknown_preserved_page_indices(self) -> tuple[int, ...]:
        return tuple(
            action.page_index
            for action in self.preservation_actions
            if action.action == "preserve_unknown_page"
        )

    def emit(self) -> bytes:
        failed = ", ".join(gate.code for gate in self.emission_gates if not gate.passed)
        raise OggPageCommentTransactionBlocked(
            f"Ogg page/comment transaction cannot be emitted by this planner: {failed}"
        )


class OggPageCommentTransactionBlocked(ValueError):
    """Raised when a caller attempts to emit from the planning-only Ogg surface."""


def plan_ogg_page_comment_transaction(
    data: bytes,
    replacement_comment_payload: bytes | None = None,
) -> OggPageCommentTransactionPlan:
    """Build a non-mutating Ogg page/comment transaction plan.

    ``replacement_comment_payload`` is a Vorbis-comment payload without the
    codec packet signature.  It is parsed for planning evidence only; emission
    remains blocked because Ogg page CRC and lacing rebuilds are not implemented.
    """
    pages, scan_issues = scan_ogg_pages(data)
    packet_routes, packet_issues = route_ogg_packets(data, pages)
    requested_parse = (
        parse_vorbis_comment_payload(replacement_comment_payload)
        if replacement_comment_payload is not None
        else absent_vorbis_comment_parse()
    )
    issues = (*scan_issues, *packet_issues)
    preservation_actions = _build_preservation_actions(pages, packet_routes)
    flac_handoff = build_ogg_flac_handoff(data, pages, packet_routes)
    flac_issues = (flac_handoff.issue,) if flac_handoff.issue is not None else ()
    issues = (*issues, *flac_issues)
    gates = _build_emission_gates(
        data=data,
        pages=pages,
        issues=issues,
        replacement_comment_payload=replacement_comment_payload,
        requested_parse=requested_parse,
    )
    return OggPageCommentTransactionPlan(
        input_size=len(data),
        pages=pages,
        packet_routes=packet_routes,
        preservation_actions=preservation_actions,
        requested_comment_parse=requested_parse,
        flac_handoff=flac_handoff,
        issues=issues,
        emission_gates=gates,
    )


build_ogg_page_comment_transaction_plan = plan_ogg_page_comment_transaction


def encode_vorbis_comment_payload(
    vendor: str | bytes,
    comments: Mapping[str, str | Sequence[str]] | Iterable[tuple[str, str]],
) -> bytes:
    vendor_bytes = vendor if isinstance(vendor, bytes) else vendor.encode("utf-8")
    entries: list[tuple[str, str]] = []
    if isinstance(comments, Mapping):
        for tag, value in comments.items():
            if isinstance(value, str):
                entries.append((tag, value))
            else:
                entries.extend((tag, item) for item in value)
    else:
        entries.extend(comments)

    payload = bytearray()
    payload += len(vendor_bytes).to_bytes(4, "little")
    payload += vendor_bytes
    payload += len(entries).to_bytes(4, "little")
    for tag, value in entries:
        raw = f"{tag}={value}".encode()
        payload += len(raw).to_bytes(4, "little")
        payload += raw
    return bytes(payload)


def scan_ogg_pages(data: bytes) -> tuple[tuple[OggPagePlan, ...], tuple[OggPlanIssue, ...]]:
    pages: list[OggPagePlan] = []
    issues: list[OggPlanIssue] = []
    next_sequence_by_stream: dict[int, int] = {}
    offset = 0

    while offset < len(data):
        if offset + OGG_FIXED_HEADER_SIZE > len(data):
            issues.append(
                OggPlanIssue(
                    code="truncated_page_header",
                    message="Ogg page header is shorter than 27 bytes.",
                    offset=offset,
                    page_index=len(pages),
                    evidence_ids=(OGG_PAGE_TRAVERSAL_SOURCE,),
                )
            )
            break

        header = data[offset : offset + OGG_FIXED_HEADER_SIZE]
        if header[:4] != OGG_CAPTURE_PATTERN:
            issues.append(
                OggPlanIssue(
                    code="ogg_capture_pattern",
                    message="Expected OggS capture pattern at the next page boundary.",
                    offset=offset,
                    page_index=len(pages) if pages else None,
                    evidence_ids=(OGG_PAGE_TRAVERSAL_SOURCE,),
                )
            )
            break

        page_segments = header[26]
        segment_table_offset = offset + OGG_FIXED_HEADER_SIZE
        segment_table_end = segment_table_offset + page_segments
        if segment_table_end > len(data):
            issues.append(
                OggPlanIssue(
                    code="truncated_segment_table",
                    message="Ogg page segment table extends beyond the input.",
                    offset=segment_table_offset,
                    page_index=len(pages),
                    evidence_ids=(OGG_PAGE_TRAVERSAL_SOURCE,),
                )
            )
            break

        segment_lengths = tuple(data[segment_table_offset:segment_table_end])
        payload_length = sum(segment_lengths)
        data_offset = segment_table_end
        end_offset = data_offset + payload_length
        if end_offset > len(data):
            issues.append(
                OggPlanIssue(
                    code="truncated_page_payload",
                    message=(
                        f"Ogg page declares {payload_length} payload bytes but only "
                        f"{max(0, len(data) - data_offset)} remain."
                    ),
                    offset=data_offset,
                    page_index=len(pages),
                    evidence_ids=(OGG_PAGE_TRAVERSAL_SOURCE,),
                )
            )
            break

        header_type = header[5]
        stream_serial = int.from_bytes(header[14:18], "little")
        page_sequence = int.from_bytes(header[18:22], "little")
        expected_sequence = next_sequence_by_stream.get(stream_serial)
        if header_type & OGG_BOS_FLAG:
            sequence_status: OggPageSequenceStatus = "expected" if page_sequence == 0 else "missing"
            expected_for_page = 0
        elif expected_sequence is None:
            sequence_status = "untracked"
            expected_for_page = None
        elif page_sequence == expected_sequence:
            sequence_status = "expected"
            expected_for_page = expected_sequence
        else:
            sequence_status = "missing"
            expected_for_page = expected_sequence
        next_sequence_by_stream[stream_serial] = page_sequence + 1
        if sequence_status == "missing":
            issues.append(
                OggPlanIssue(
                    code="missing_ogg_page_sequence",
                    message=(
                        f"Stream {stream_serial} page sequence is {page_sequence}; "
                        f"expected {expected_for_page}."
                    ),
                    offset=offset,
                    page_index=len(pages),
                    evidence_ids=(OGG_SEQUENCE_SOURCE,),
                )
            )

        segments: list[OggSegmentPlan] = []
        payload_cursor = data_offset
        for segment_index, length in enumerate(segment_lengths):
            segments.append(
                OggSegmentPlan(
                    page_index=len(pages),
                    segment_index=segment_index,
                    length=length,
                    payload_offset=payload_cursor,
                    payload_end_offset=payload_cursor + length,
                    completes_packet=length < OGG_LACING_CONTINUES,
                    evidence_ids=(OGG_PAGE_TRAVERSAL_SOURCE, OGG_PACKET_BOUNDARY_SOURCE),
                )
            )
            payload_cursor += length

        pages.append(
            OggPagePlan(
                index=len(pages),
                offset=offset,
                data_offset=data_offset,
                end_offset=end_offset,
                version=header[4],
                header_type=header_type,
                granule_position=int.from_bytes(header[6:14], "little", signed=True),
                bitstream_serial=stream_serial,
                page_sequence=page_sequence,
                checksum=int.from_bytes(header[22:26], "little"),
                segment_lengths=segment_lengths,
                payload_length=payload_length,
                sequence_status=sequence_status,
                expected_page_sequence=expected_for_page,
                segments=tuple(segments),
                evidence_ids=(OGG_PAGE_TRAVERSAL_SOURCE, OGG_SEQUENCE_SOURCE),
            )
        )
        offset = end_offset

    if not pages and not issues:
        issues.append(
            OggPlanIssue(
                code="empty_ogg_input",
                message="No Ogg pages were present.",
                offset=0,
                page_index=None,
                evidence_ids=(OGG_PAGE_TRAVERSAL_SOURCE,),
            )
        )
    return tuple(pages), tuple(issues)


@dataclass(frozen=True)
class _OpenPacket:
    stream_serial: int
    start_page_index: int
    payload: bytes


def route_ogg_packets(
    data: bytes, pages: Sequence[OggPagePlan]
) -> tuple[tuple[OggPacketRoutePlan, ...], tuple[OggPlanIssue, ...]]:
    packet_routes: list[OggPacketRoutePlan] = []
    issues: list[OggPlanIssue] = []
    open_packets: dict[int, _OpenPacket] = {}
    ignoring_continuation: set[int] = set()

    for page in pages:
        if page.is_continuation and page.bitstream_serial not in open_packets:
            ignoring_continuation.add(page.bitstream_serial)
            issues.append(
                OggPlanIssue(
                    code="dangling_continuation_page",
                    message=(
                        f"Stream {page.bitstream_serial} has a continuation page without "
                        "a buffered packet start."
                    ),
                    offset=page.offset,
                    page_index=page.index,
                    evidence_ids=(OGG_PACKET_BOUNDARY_SOURCE,),
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
                open_packet = _OpenPacket(
                    stream_serial=page.bitstream_serial,
                    start_page_index=page.index,
                    payload=b"",
                )
            payload = open_packet.payload + chunk
            if segment.completes_packet:
                packet_routes.append(
                    _classify_packet(
                        packet_index=len(packet_routes),
                        stream_serial=page.bitstream_serial,
                        start_page_index=open_packet.start_page_index,
                        end_page_index=page.index,
                        terminal_kind="complete_segment",
                        payload=payload,
                    )
                )
                open_packets.pop(page.bitstream_serial, None)
            else:
                open_packets[page.bitstream_serial] = _OpenPacket(
                    stream_serial=page.bitstream_serial,
                    start_page_index=open_packet.start_page_index,
                    payload=payload,
                )

        if page.is_end_of_stream and page.bitstream_serial in open_packets:
            open_packet = open_packets.pop(page.bitstream_serial)
            packet_routes.append(
                _classify_packet(
                    packet_index=len(packet_routes),
                    stream_serial=page.bitstream_serial,
                    start_page_index=open_packet.start_page_index,
                    end_page_index=page.index,
                    terminal_kind="eos_forced",
                    payload=open_packet.payload,
                )
            )

    for stream_serial, open_packet in sorted(open_packets.items()):
        packet_routes.append(
            _classify_packet(
                packet_index=len(packet_routes),
                stream_serial=stream_serial,
                start_page_index=open_packet.start_page_index,
                end_page_index=pages[-1].index if pages else open_packet.start_page_index,
                terminal_kind="open_at_eof",
                payload=open_packet.payload,
            )
        )
        issues.append(
            OggPlanIssue(
                code="unterminated_ogg_packet",
                message=f"Stream {stream_serial} ended with an unterminated packet.",
                offset=None,
                page_index=open_packet.start_page_index,
                evidence_ids=(OGG_PACKET_BOUNDARY_SOURCE,),
            )
        )

    return tuple(packet_routes), tuple(issues)


def build_ogg_flac_handoff(
    data: bytes,
    pages: Sequence[OggPagePlan],
    packet_routes: Sequence[OggPacketRoutePlan],
) -> OggFlacHandoffPlan:
    """Assemble the ExifTool Ogg-FLAC synthetic native FLAC stream."""
    for route_index, route in enumerate(packet_routes):
        if route.codec != "flac" or route.route_kind != "flac_header":
            continue
        first_payload = packet_route_payload(data, pages, route)
        if len(first_payload) < 9:
            issue = OggPlanIssue(
                code="malformed_ogg_flac_header",
                message="Ogg-FLAC packet is shorter than the 9-byte FLAC mapping header.",
                offset=None,
                page_index=route.start_page_index,
                evidence_ids=(OGG_FLAC_HANDOFF_SOURCE,),
            )
            return OggFlacHandoffPlan(
                status="malformed_header",
                stream_serial=route.stream_serial,
                start_packet_index=route.packet_index,
                declared_header_packets=None,
                assembled_header_packets=0,
                synthetic_flac_stream=None,
                issue=issue,
                evidence_ids=(OGG_FLAC_HANDOFF_SOURCE,),
            )

        declared_header_packets = int.from_bytes(first_payload[7:9], "big")
        chunks = [first_payload[9:]]
        assembled_header_packets = 1
        for follow_route in packet_routes[route_index + 1 :]:
            if follow_route.stream_serial != route.stream_serial:
                continue
            if assembled_header_packets >= declared_header_packets:
                break
            chunks.append(packet_route_payload(data, pages, follow_route))
            assembled_header_packets += 1

        synthetic = b"".join(chunks)
        if assembled_header_packets < declared_header_packets:
            issue = OggPlanIssue(
                code="truncated_ogg_flac_headers",
                message=(
                    "Ogg-FLAC stream ended before all declared FLAC header packets "
                    f"were assembled ({assembled_header_packets}/{declared_header_packets})."
                ),
                offset=None,
                page_index=route.start_page_index,
                evidence_ids=(OGG_FLAC_HANDOFF_SOURCE,),
            )
            return OggFlacHandoffPlan(
                status="truncated_headers",
                stream_serial=route.stream_serial,
                start_packet_index=route.packet_index,
                declared_header_packets=declared_header_packets,
                assembled_header_packets=assembled_header_packets,
                synthetic_flac_stream=synthetic,
                issue=issue,
                evidence_ids=(OGG_FLAC_HANDOFF_SOURCE,),
            )

        return OggFlacHandoffPlan(
            status="assembled",
            stream_serial=route.stream_serial,
            start_packet_index=route.packet_index,
            declared_header_packets=declared_header_packets,
            assembled_header_packets=assembled_header_packets,
            synthetic_flac_stream=synthetic,
            issue=None,
            evidence_ids=(OGG_FLAC_HANDOFF_SOURCE,),
        )

    return OggFlacHandoffPlan(
        status="absent",
        stream_serial=None,
        start_packet_index=None,
        declared_header_packets=None,
        assembled_header_packets=0,
        synthetic_flac_stream=None,
        issue=None,
        evidence_ids=(OGG_FLAC_HANDOFF_SOURCE,),
    )


def packet_route_payload(
    data: bytes, pages: Sequence[OggPagePlan], route: OggPacketRoutePlan
) -> bytes:
    chunks: list[bytes] = []
    for page in pages[route.start_page_index : route.end_page_index + 1]:
        for segment in page.segments:
            chunks.append(data[segment.payload_offset : segment.payload_end_offset])
            if segment.completes_packet:
                return b"".join(chunks)
    return b"".join(chunks)


def parse_vorbis_comment_payload(payload: bytes) -> OggVorbisCommentParsePlan:
    pos = 0
    end = len(payload)
    if pos + 4 > end:
        return _malformed_vorbis_parse("Missing Vorbis vendor length.")

    vendor_length = int.from_bytes(payload[pos : pos + 4], "little")
    pos += 4
    if pos + vendor_length > end:
        return _malformed_vorbis_parse("Vorbis vendor string extends beyond the packet payload.")

    vendor = payload[pos : pos + vendor_length].decode("utf-8", "replace")
    pos += vendor_length
    if pos + 4 > end:
        return OggVorbisCommentParsePlan(
            status="valid",
            vendor=vendor,
            declared_comment_count=0,
            parsed_comment_count=0,
            entries=(),
            issue=None,
            evidence_ids=(VORBIS_COMMENT_PARSE_SOURCE,),
        )

    declared_count = int.from_bytes(payload[pos : pos + 4], "little")
    pos += 4
    entries: list[OggVorbisCommentEntryPlan] = []
    for index in range(declared_count):
        if pos + 4 > end:
            return _malformed_vorbis_parse(
                f"Missing length for Vorbis comment entry {index}.",
                vendor=vendor,
                declared_count=declared_count,
                entries=tuple(entries),
            )
        raw_length = int.from_bytes(payload[pos : pos + 4], "little")
        pos += 4
        if pos + raw_length > end:
            return _malformed_vorbis_parse(
                f"Vorbis comment entry {index} extends beyond the packet payload.",
                vendor=vendor,
                declared_count=declared_count,
                entries=tuple(entries),
            )
        raw = payload[pos : pos + raw_length]
        pos += raw_length
        if b"=" not in raw:
            return _malformed_vorbis_parse(
                f"Vorbis comment entry {index} is not a TAG=value pair.",
                vendor=vendor,
                declared_count=declared_count,
                entries=tuple(entries),
            )
        raw_tag, raw_value = raw.split(b"=", 1)
        tag = raw_tag.decode("utf-8", "replace").upper()
        value = raw_value.decode("utf-8", "replace")
        picture_comment = (
            parse_metadata_block_picture_comment(value) if tag == "METADATA_BLOCK_PICTURE" else None
        )
        entries.append(
            OggVorbisCommentEntryPlan(
                index=index,
                tag=tag,
                value=value,
                raw_length=raw_length,
                routes_to_flac_picture=tag == "METADATA_BLOCK_PICTURE",
                picture_comment=picture_comment,
                evidence_ids=(
                    (VORBIS_PICTURE_COMMENT_SOURCE, XMP_BASE64_DECODE_SOURCE, FLAC_PICTURE_SOURCE)
                    if tag == "METADATA_BLOCK_PICTURE"
                    else (VORBIS_COMMENT_PARSE_SOURCE,)
                ),
            )
        )

    return OggVorbisCommentParsePlan(
        status="valid",
        vendor=vendor,
        declared_comment_count=declared_count,
        parsed_comment_count=len(entries),
        entries=tuple(entries),
        issue=None,
        evidence_ids=(VORBIS_COMMENT_PARSE_SOURCE,),
    )


def absent_vorbis_comment_parse() -> OggVorbisCommentParsePlan:
    return OggVorbisCommentParsePlan(
        status="absent",
        vendor=None,
        declared_comment_count=None,
        parsed_comment_count=0,
        entries=(),
        issue=None,
        evidence_ids=(VORBIS_COMMENT_PARSE_SOURCE,),
    )


def _classify_packet(
    *,
    packet_index: int,
    stream_serial: int,
    start_page_index: int,
    end_page_index: int,
    terminal_kind: OggPacketTerminalKind,
    payload: bytes,
) -> OggPacketRoutePlan:
    codec: OggCodecKind = "unknown"
    route_kind: OggPacketRouteKind = "unknown_preserved"
    comment_dir_start: int | None = None
    packet_tag: int | str | None = None
    comment_parse = absent_vorbis_comment_parse()
    references: tuple[str, ...] = (OGG_PACKET_BOUNDARY_SOURCE,)

    if len(payload) >= 7 and payload[1:7] == b"vorbis":
        codec = "vorbis"
        packet_tag = payload[0]
        references = (OGG_PACKET_ROUTING_SOURCE, VORBIS_MAIN_SOURCE)
        if payload[0] == 3:
            route_kind = "comment"
            comment_dir_start = 7
            comment_parse = parse_vorbis_comment_payload(payload[comment_dir_start:])
            references = (*references, VORBIS_COMMENT_PARSE_SOURCE)
        elif payload[0] == 1:
            route_kind = "codec_header"
        else:
            route_kind = "codec_setup"
    elif len(payload) >= 7 and payload[1:7] == b"theora":
        codec = "theora"
        packet_tag = payload[0]
        references = (OGG_PACKET_ROUTING_SOURCE, THEORA_MAIN_SOURCE)
        if payload[0] == 0x81:
            route_kind = "comment"
            comment_dir_start = 7
            comment_parse = parse_vorbis_comment_payload(payload[comment_dir_start:])
            references = (*references, VORBIS_COMMENT_PARSE_SOURCE)
        elif payload[0] == 0x80:
            route_kind = "codec_header"
        else:
            route_kind = "codec_setup"
    elif payload.startswith(b"OpusTags"):
        codec = "opus"
        packet_tag = "OpusTags"
        route_kind = "comment"
        comment_dir_start = 8
        comment_parse = parse_vorbis_comment_payload(payload[comment_dir_start:])
        references = (OGG_PACKET_ROUTING_SOURCE, OPUS_MAIN_SOURCE, VORBIS_COMMENT_PARSE_SOURCE)
    elif payload.startswith(b"OpusHead"):
        codec = "opus"
        packet_tag = "OpusHead"
        route_kind = "codec_header"
        comment_dir_start = 8
        references = (OGG_PACKET_ROUTING_SOURCE, OPUS_MAIN_SOURCE)
    elif payload.startswith(b"\x7fFLAC"):
        codec = "flac"
        route_kind = "flac_header"
        references = (OGG_PACKET_ROUTING_SOURCE, OGG_MAIN_SOURCE)
    elif payload.startswith(b"Speex"):
        codec = "speex"
        route_kind = "speex_preserved_unsupported"
        references = (SPEEX_PRESERVATION_SOURCE,)

    return OggPacketRoutePlan(
        packet_index=packet_index,
        stream_serial=stream_serial,
        start_page_index=start_page_index,
        end_page_index=end_page_index,
        terminal_kind=terminal_kind,
        codec=codec,
        route_kind=route_kind,
        comment_dir_start=comment_dir_start,
        packet_tag=packet_tag,
        payload_length=len(payload),
        comment_parse=comment_parse,
        evidence_ids=references,
    )


def _build_preservation_actions(
    pages: Sequence[OggPagePlan], packet_routes: Sequence[OggPacketRoutePlan]
) -> tuple[OggPagePreservationPlan, ...]:
    routed_pages: set[int] = set()
    for route in packet_routes:
        if route.route_kind in {"comment", "codec_header", "codec_setup", "flac_header"}:
            routed_pages.update(range(route.start_page_index, route.end_page_index + 1))

    actions: list[OggPagePreservationPlan] = []
    for page in pages:
        if page.index in routed_pages:
            actions.append(
                OggPagePreservationPlan(
                    page_index=page.index,
                    stream_serial=page.bitstream_serial,
                    action="preserve_routed_page",
                    reason="Page participates in an ExifTool-routed Ogg packet.",
                    evidence_ids=(OGG_PACKET_ROUTING_SOURCE,),
                )
            )
        else:
            actions.append(
                OggPagePreservationPlan(
                    page_index=page.index,
                    stream_serial=page.bitstream_serial,
                    action="preserve_unknown_page",
                    reason="Page is not part of an ExifTool-routed Ogg packet and is preserved.",
                    evidence_ids=(OGG_PACKET_BOUNDARY_SOURCE, SPEEX_PRESERVATION_SOURCE),
                )
            )
    return tuple(actions)


def _build_emission_gates(
    *,
    data: bytes,
    pages: Sequence[OggPagePlan],
    issues: Sequence[OggPlanIssue],
    replacement_comment_payload: bytes | None,
    requested_parse: OggVorbisCommentParsePlan,
) -> tuple[OggEmissionGate, ...]:
    has_scan_issues = any(
        issue.code
        in {
            "empty_ogg_input",
            "truncated_page_header",
            "ogg_capture_pattern",
            "truncated_segment_table",
            "truncated_page_payload",
        }
        for issue in issues
    )
    has_sequence_issues = any(issue.code == "missing_ogg_page_sequence" for issue in issues)
    has_packet_issues = any(
        issue.code in {"dangling_continuation_page", "unterminated_ogg_packet"} for issue in issues
    )
    return (
        OggEmissionGate(
            code="ogg_capture_pattern",
            passed=data.startswith(OGG_CAPTURE_PATTERN),
            reason="Input begins with an OggS capture pattern."
            if data.startswith(OGG_CAPTURE_PATTERN)
            else "Input does not begin with an OggS capture pattern.",
            evidence_ids=(OGG_PAGE_TRAVERSAL_SOURCE,),
        ),
        OggEmissionGate(
            code="page_header_lacing_traversal",
            passed=bool(pages) and not has_scan_issues,
            reason="All pages were traversed through complete headers, lacing tables, and payloads."
            if bool(pages) and not has_scan_issues
            else "Ogg page traversal stopped before complete page/lacing coverage.",
            evidence_ids=(OGG_PAGE_TRAVERSAL_SOURCE,),
        ),
        OggEmissionGate(
            code="serial_page_sequence_responsibility",
            passed=not has_sequence_issues,
            reason="Per-stream page sequence numbers are contiguous where ExifTool tracks them."
            if not has_sequence_issues
            else "At least one stream has missing Ogg page sequence numbers.",
            evidence_ids=(OGG_SEQUENCE_SOURCE,),
        ),
        OggEmissionGate(
            code="packet_segmentation_boundaries",
            passed=not has_packet_issues,
            reason="Packet segmentation boundaries were closed or explicitly forced by EOS."
            if not has_packet_issues
            else "At least one packet boundary is dangling or unterminated.",
            evidence_ids=(OGG_PACKET_BOUNDARY_SOURCE,),
        ),
        OggEmissionGate(
            code="replacement_comment_payload",
            passed=replacement_comment_payload is None or requested_parse.status == "valid",
            reason="Replacement comment payload is absent or parses as Vorbis comments."
            if replacement_comment_payload is None or requested_parse.status == "valid"
            else "Replacement comment payload is malformed.",
            evidence_ids=(VORBIS_COMMENT_PARSE_SOURCE,),
        ),
        OggEmissionGate(
            code="ogg_crc_lacing_rewrite",
            passed=False,
            reason=(
                "Emission is blocked: Ogg rewrites require page CRC recalculation and "
                "lacing/page reconstruction."
            ),
            evidence_ids=(OGG_CRC_REWRITE_BLOCKER_SOURCE,),
        ),
        OggEmissionGate(
            code="non_mutating_planner",
            passed=False,
            reason="This module intentionally plans Ogg transactions without mutating bytes.",
            evidence_ids=OGG_PAGE_COMMENT_TRANSACTION_SOURCES,
        ),
    )


def _malformed_vorbis_parse(
    message: str,
    *,
    vendor: str | None = None,
    declared_count: int | None = None,
    entries: tuple[OggVorbisCommentEntryPlan, ...] = (),
) -> OggVorbisCommentParsePlan:
    issue = OggPlanIssue(
        code="malformed_vorbis_comment",
        message=message,
        offset=None,
        page_index=None,
        evidence_ids=(VORBIS_COMMENT_PARSE_SOURCE,),
    )
    return OggVorbisCommentParsePlan(
        status="malformed",
        vendor=vendor,
        declared_comment_count=declared_count,
        parsed_comment_count=len(entries),
        entries=entries,
        issue=issue,
        evidence_ids=(VORBIS_COMMENT_PARSE_SOURCE,),
    )
