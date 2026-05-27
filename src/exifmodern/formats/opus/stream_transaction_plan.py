"""Source-backed, non-mutating Ogg Opus stream transaction planning.

The planner mirrors ExifTool's Opus read surface: route OpusHead to the Opus
header table, route OpusTags to Vorbis comments after the eight-byte packet
signature, preserve stream bytes, and gate unsupported rewrites.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.ogg.page_comment_transaction_plan import (
    OGG_CAPTURE_PATTERN,
    OGG_PACKET_BOUNDARY_SOURCE,
    OGG_PACKET_LIMIT_SOURCE,
    OGG_PAGE_TRAVERSAL_SOURCE,
    OGG_SEQUENCE_SOURCE,
    OggPagePlan,
    OggPlanIssue,
    OggVorbisCommentParsePlan,
    absent_vorbis_comment_parse,
    parse_vorbis_comment_payload,
    scan_ogg_pages,
)

OPUS_HEAD_SIGNATURE = b"OpusHead"
OPUS_TAGS_SIGNATURE = b"OpusTags"
OPUS_PACKET_SIGNATURE_SIZE = 8
OPUS_HEAD_PACKET_SIZE = 19

type OpusPlanStatus = Literal["planned", "unsupported"]
type OpusPacketTerminalKind = Literal["complete_segment", "eos_forced", "open_at_eof"]
type OpusPacketSignature = Literal["OpusHead", "OpusTags", "other"]
type OpusPacketRouteKind = Literal[
    "opus_header",
    "opus_comments",
    "stream_payload_preserved",
]
type OpusHeadStatus = Literal["absent", "valid", "truncated"]
type OpusPreservationKind = Literal["preserve_opus_page", "preserve_stream_page"]
type OpusResponsibilityKind = Literal[
    "opus_version",
    "audio_channels",
    "sample_rate",
    "output_gain",
    "vorbis_comments",
    "payload_preservation",
]
type OpusEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "ogg_capture_pattern",
    "ogg_page_traversal",
    "ogg_page_sequence",
    "ogg_packet_boundaries",
    "missing_opus_head_packet",
    "missing_opus_tags_packet",
    "truncated_opus_head_packet",
    "malformed_opus_tags_comment",
    "requested_vorbis_comment_payload",
    "opus_metadata_rewrite_not_supported",
    "opus_stream_rewrite_not_implemented",
]

OPUS_PM_SOURCE_PATH = "lib/Image/ExifTool/Opus.pm"

OPUS_MAIN_SOURCE = "opus.main.2"
OPUS_HEADER_SOURCE = "opus.header"
OPUS_OUTPUT_GAIN_SOURCE = "opus.output_gain"
OPUS_PACKET_ROUTE_SOURCE = "opus.packet_route"
OPUS_STREAM_TRAVERSAL_SOURCE = "opus.stream_traversal"
OPUS_VORBIS_BOUNDARY_SOURCE = "opus.vorbis_boundary"
OPUS_NON_MUTATING_SOURCE = "opus.non_mutating"

OPUS_TRANSACTION_SOURCES = (
    OPUS_MAIN_SOURCE,
    OPUS_HEADER_SOURCE,
    OPUS_OUTPUT_GAIN_SOURCE,
    OPUS_PACKET_ROUTE_SOURCE,
    OPUS_STREAM_TRAVERSAL_SOURCE,
    OPUS_VORBIS_BOUNDARY_SOURCE,
    OPUS_NON_MUTATING_SOURCE,
)


@dataclass(frozen=True)
class OpusRewriteRequest:
    vorbis_comment_payload: bytes | None = None
    sample_rate: int | None = None
    output_gain: int | None = None

    @property
    def requested(self) -> bool:
        return (
            self.vorbis_comment_payload is not None
            or self.sample_rate is not None
            or self.output_gain is not None
        )


@dataclass(frozen=True)
class OpusHeadPlan:
    status: OpusHeadStatus
    packet_index: int | None
    version: int | None
    audio_channels: int | None
    pre_skip: int | None
    sample_rate: int | None
    output_gain_raw: int | None
    output_gain_linear: float | None
    channel_mapping_family: int | None
    raw_payload: bytes
    blocker_code: OpusEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OpusPacketPlan:
    packet_index: int
    stream_serial: int
    stream_packet_number: int
    start_page_index: int
    end_page_index: int
    terminal_kind: OpusPacketTerminalKind
    signature: OpusPacketSignature
    route_kind: OpusPacketRouteKind
    comment_dir_start: int | None
    payload_length: int
    payload: bytes
    head: OpusHeadPlan
    comment_parse: OggVorbisCommentParsePlan
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OpusPagePreservationPlan:
    page_index: int
    stream_serial: int
    kind: OpusPreservationKind
    offset: int
    end_offset: int
    payload: bytes
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OpusResponsibilityPlan:
    kind: OpusResponsibilityKind
    available: bool
    value: int | float | str | None
    packet_index: int | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OpusOutputEmissionGate:
    code: OpusEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OpusStreamTransactionPlan:
    status: OpusPlanStatus
    input_size: int
    pages: tuple[OggPagePlan, ...]
    issues: tuple[OggPlanIssue, ...]
    packets: tuple[OpusPacketPlan, ...]
    opus_head: OpusHeadPlan
    opus_tags: tuple[OpusPacketPlan, ...]
    requested_comment_parse: OggVorbisCommentParsePlan
    preservation_actions: tuple[OpusPagePreservationPlan, ...]
    responsibilities: tuple[OpusResponsibilityPlan, ...]
    output_emission_gates: tuple[OpusOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Opus stream transaction output is gated: {gate_codes}")
        return self.original_bytes


@dataclass(frozen=True)
class _OpenPacket:
    stream_serial: int
    stream_packet_number: int
    start_page_index: int
    payload: bytes


def build_opus_stream_transaction_plan(
    opus_data: bytes,
    *,
    requested_rewrite: OpusRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> OpusStreamTransactionPlan:
    pages, scan_issues = scan_ogg_pages(opus_data)
    packets, packet_issues = _route_opus_packets(opus_data, pages)
    issues = (*scan_issues, *packet_issues)
    head = _first_head_packet(packets)
    tags = tuple(packet for packet in packets if packet.route_kind == "opus_comments")
    requested_parse = _requested_comment_parse(requested_rewrite)
    preservation_actions = _preservation_actions(opus_data, pages, packets)
    responsibilities = _responsibility_plans(head, tags)
    gates = _output_gates(
        opus_data=opus_data,
        pages=pages,
        issues=issues,
        head=head,
        tags=tags,
        requested_rewrite=requested_rewrite,
        requested_parse=requested_parse,
        allow_output_emission=allow_output_emission,
    )
    unique_output_gates = _unique_gates(gates)
    status: OpusPlanStatus = (
        "unsupported" if _has_structural_gate(unique_output_gates) else "planned"
    )
    return OpusStreamTransactionPlan(
        status=status,
        input_size=len(opus_data),
        pages=pages,
        issues=issues,
        packets=packets,
        opus_head=head,
        opus_tags=tags,
        requested_comment_parse=requested_parse,
        preservation_actions=preservation_actions,
        responsibilities=responsibilities,
        output_emission_gates=unique_output_gates,
        evidence_ids=_unique_evidence_ids(
            (
                *OPUS_TRANSACTION_SOURCES,
                *(source for issue in issues for source in issue.evidence_ids),
                *(source for packet in packets for source in packet.evidence_ids),
                *(source for action in preservation_actions for source in action.evidence_ids),
                *(source for gate in unique_output_gates for source in gate.evidence_ids),
            )
        ),
        original_bytes=opus_data,
    )


plan_opus_stream_transaction = build_opus_stream_transaction_plan


def _route_opus_packets(
    data: bytes, pages: tuple[OggPagePlan, ...]
) -> tuple[tuple[OpusPacketPlan, ...], tuple[OggPlanIssue, ...]]:
    packets: list[OpusPacketPlan] = []
    issues: list[OggPlanIssue] = []
    open_packets: dict[int, _OpenPacket] = {}
    packet_counts: dict[int, int] = {}
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
                    evidence_ids=(OGG_PACKET_BOUNDARY_SOURCE, OPUS_STREAM_TRAVERSAL_SOURCE),
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
                next_packet_number = packet_counts.get(page.bitstream_serial, 0) + 1
                packet_counts[page.bitstream_serial] = next_packet_number
                open_packet = _OpenPacket(
                    stream_serial=page.bitstream_serial,
                    stream_packet_number=next_packet_number,
                    start_page_index=page.index,
                    payload=b"",
                )
            payload = open_packet.payload + chunk
            if segment.completes_packet:
                packets.append(
                    _classify_opus_packet(
                        packet_index=len(packets),
                        stream_serial=page.bitstream_serial,
                        stream_packet_number=open_packet.stream_packet_number,
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
                    stream_packet_number=open_packet.stream_packet_number,
                    start_page_index=open_packet.start_page_index,
                    payload=payload,
                )

        if page.is_end_of_stream and page.bitstream_serial in open_packets:
            open_packet = open_packets.pop(page.bitstream_serial)
            packets.append(
                _classify_opus_packet(
                    packet_index=len(packets),
                    stream_serial=page.bitstream_serial,
                    stream_packet_number=open_packet.stream_packet_number,
                    start_page_index=open_packet.start_page_index,
                    end_page_index=page.index,
                    terminal_kind="eos_forced",
                    payload=open_packet.payload,
                )
            )

    for stream_serial, open_packet in sorted(open_packets.items()):
        packets.append(
            _classify_opus_packet(
                packet_index=len(packets),
                stream_serial=stream_serial,
                stream_packet_number=open_packet.stream_packet_number,
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
                evidence_ids=(OGG_PACKET_BOUNDARY_SOURCE, OPUS_STREAM_TRAVERSAL_SOURCE),
            )
        )

    return tuple(packets), tuple(issues)


def _classify_opus_packet(
    *,
    packet_index: int,
    stream_serial: int,
    stream_packet_number: int,
    start_page_index: int,
    end_page_index: int,
    terminal_kind: OpusPacketTerminalKind,
    payload: bytes,
) -> OpusPacketPlan:
    signature: OpusPacketSignature = "other"
    route_kind: OpusPacketRouteKind = "stream_payload_preserved"
    comment_dir_start: int | None = None
    head = _absent_head()
    comment_parse = absent_vorbis_comment_parse()
    sources: tuple[str, ...] = (OPUS_STREAM_TRAVERSAL_SOURCE,)
    within_exiftool_opus_scan = stream_packet_number <= 2

    if payload.startswith(OPUS_HEAD_SIGNATURE) and within_exiftool_opus_scan:
        signature = "OpusHead"
        route_kind = "opus_header"
        comment_dir_start = OPUS_PACKET_SIGNATURE_SIZE
        head = _parse_opus_head(packet_index, payload)
        sources = (
            OPUS_PACKET_ROUTE_SOURCE,
            OPUS_MAIN_SOURCE,
            OPUS_HEADER_SOURCE,
            *head.evidence_ids,
        )
    elif payload.startswith(OPUS_TAGS_SIGNATURE) and within_exiftool_opus_scan:
        signature = "OpusTags"
        route_kind = "opus_comments"
        comment_dir_start = OPUS_PACKET_SIGNATURE_SIZE
        comment_parse = parse_vorbis_comment_payload(payload[OPUS_PACKET_SIGNATURE_SIZE:])
        sources = (
            OPUS_PACKET_ROUTE_SOURCE,
            OPUS_MAIN_SOURCE,
            OPUS_VORBIS_BOUNDARY_SOURCE,
            *comment_parse.evidence_ids,
        )
    elif payload.startswith(OPUS_HEAD_SIGNATURE):
        signature = "OpusHead"
        sources = (OPUS_PACKET_ROUTE_SOURCE, OGG_PACKET_LIMIT_SOURCE)
    elif payload.startswith(OPUS_TAGS_SIGNATURE):
        signature = "OpusTags"
        sources = (OPUS_PACKET_ROUTE_SOURCE, OGG_PACKET_LIMIT_SOURCE)

    return OpusPacketPlan(
        packet_index=packet_index,
        stream_serial=stream_serial,
        stream_packet_number=stream_packet_number,
        start_page_index=start_page_index,
        end_page_index=end_page_index,
        terminal_kind=terminal_kind,
        signature=signature,
        route_kind=route_kind,
        comment_dir_start=comment_dir_start,
        payload_length=len(payload),
        payload=payload,
        head=head,
        comment_parse=comment_parse,
        evidence_ids=_unique_evidence_ids(sources),
    )


def _parse_opus_head(packet_index: int, payload: bytes) -> OpusHeadPlan:
    if len(payload) < OPUS_HEAD_PACKET_SIZE:
        return OpusHeadPlan(
            status="truncated",
            packet_index=packet_index,
            version=None,
            audio_channels=None,
            pre_skip=None,
            sample_rate=None,
            output_gain_raw=None,
            output_gain_linear=None,
            channel_mapping_family=None,
            raw_payload=payload,
            blocker_code="truncated_opus_head_packet",
            evidence_ids=(OPUS_HEADER_SOURCE, OPUS_PACKET_ROUTE_SOURCE),
        )

    header = payload[OPUS_PACKET_SIGNATURE_SIZE:OPUS_HEAD_PACKET_SIZE]
    output_gain_raw = int.from_bytes(header[8:10], "little")
    return OpusHeadPlan(
        status="valid",
        packet_index=packet_index,
        version=header[0],
        audio_channels=header[1],
        pre_skip=int.from_bytes(header[2:4], "little"),
        sample_rate=int.from_bytes(header[4:8], "little"),
        output_gain_raw=output_gain_raw,
        output_gain_linear=10 ** (output_gain_raw / 5120),
        channel_mapping_family=header[10],
        raw_payload=payload,
        blocker_code=None,
        evidence_ids=(OPUS_HEADER_SOURCE, OPUS_OUTPUT_GAIN_SOURCE),
    )


def _absent_head() -> OpusHeadPlan:
    return OpusHeadPlan(
        status="absent",
        packet_index=None,
        version=None,
        audio_channels=None,
        pre_skip=None,
        sample_rate=None,
        output_gain_raw=None,
        output_gain_linear=None,
        channel_mapping_family=None,
        raw_payload=b"",
        blocker_code="missing_opus_head_packet",
        evidence_ids=(OPUS_MAIN_SOURCE, OPUS_HEADER_SOURCE),
    )


def _first_head_packet(packets: tuple[OpusPacketPlan, ...]) -> OpusHeadPlan:
    for packet in packets:
        if packet.route_kind == "opus_header":
            return packet.head
    return _absent_head()


def _requested_comment_parse(
    requested_rewrite: OpusRewriteRequest | None,
) -> OggVorbisCommentParsePlan:
    if requested_rewrite is None or requested_rewrite.vorbis_comment_payload is None:
        return absent_vorbis_comment_parse()
    return parse_vorbis_comment_payload(requested_rewrite.vorbis_comment_payload)


def _preservation_actions(
    data: bytes,
    pages: tuple[OggPagePlan, ...],
    packets: tuple[OpusPacketPlan, ...],
) -> tuple[OpusPagePreservationPlan, ...]:
    opus_page_indices: set[int] = set()
    for packet in packets:
        if packet.route_kind in {"opus_header", "opus_comments"}:
            opus_page_indices.update(range(packet.start_page_index, packet.end_page_index + 1))

    actions: list[OpusPagePreservationPlan] = []
    for page in pages:
        references: tuple[str, ...]
        if page.index in opus_page_indices:
            kind: OpusPreservationKind = "preserve_opus_page"
            reason = "Page participates in an OpusHead or OpusTags packet."
            references = (OPUS_PACKET_ROUTE_SOURCE, OPUS_MAIN_SOURCE)
        else:
            kind = "preserve_stream_page"
            reason = "Page is outside the routed Opus metadata packets and is preserved."
            references = (OPUS_STREAM_TRAVERSAL_SOURCE,)
        actions.append(
            OpusPagePreservationPlan(
                page_index=page.index,
                stream_serial=page.bitstream_serial,
                kind=kind,
                offset=page.offset,
                end_offset=page.end_offset,
                payload=data[page.offset : page.end_offset],
                reason=reason,
                evidence_ids=references,
            )
        )
    return tuple(actions)


def _responsibility_plans(
    head: OpusHeadPlan, tags: tuple[OpusPacketPlan, ...]
) -> tuple[OpusResponsibilityPlan, ...]:
    tag_packet = tags[0] if tags else None
    tag_value = "OpusTags" if tag_packet is not None else None
    tag_reason = (
        "OpusTags is routed to Vorbis comments at byte offset 8."
        if tag_packet is not None
        else "No OpusTags packet was routed."
    )
    return (
        _header_responsibility("opus_version", head.version, head),
        _header_responsibility("audio_channels", head.audio_channels, head),
        _header_responsibility("sample_rate", head.sample_rate, head),
        _header_responsibility("output_gain", head.output_gain_linear, head),
        OpusResponsibilityPlan(
            kind="vorbis_comments",
            available=tag_packet is not None and tag_packet.comment_parse.status == "valid",
            value=tag_value,
            packet_index=None if tag_packet is None else tag_packet.packet_index,
            reason=tag_reason,
            evidence_ids=(OPUS_MAIN_SOURCE, OPUS_VORBIS_BOUNDARY_SOURCE),
        ),
        OpusResponsibilityPlan(
            kind="payload_preservation",
            available=True,
            value="original_stream_bytes",
            packet_index=None,
            reason="The transaction plan preserves every Ogg page byte range.",
            evidence_ids=(OPUS_STREAM_TRAVERSAL_SOURCE, OPUS_NON_MUTATING_SOURCE),
        ),
    )


def _header_responsibility(
    kind: Literal["opus_version", "audio_channels", "sample_rate", "output_gain"],
    value: int | float | None,
    head: OpusHeadPlan,
) -> OpusResponsibilityPlan:
    return OpusResponsibilityPlan(
        kind=kind,
        available=head.status == "valid",
        value=value if head.status == "valid" else None,
        packet_index=head.packet_index,
        reason=(
            f"{kind} is exposed by the Opus header table."
            if head.status == "valid"
            else "No complete OpusHead packet was available."
        ),
        evidence_ids=(OPUS_HEADER_SOURCE,),
    )


def _output_gates(
    *,
    opus_data: bytes,
    pages: tuple[OggPagePlan, ...],
    issues: tuple[OggPlanIssue, ...],
    head: OpusHeadPlan,
    tags: tuple[OpusPacketPlan, ...],
    requested_rewrite: OpusRewriteRequest | None,
    requested_parse: OggVorbisCommentParsePlan,
    allow_output_emission: bool,
) -> tuple[OpusOutputEmissionGate, ...]:
    gates: list[OpusOutputEmissionGate] = []
    if not opus_data.startswith(OGG_CAPTURE_PATTERN):
        gates.append(
            OpusOutputEmissionGate(
                "ogg_capture_pattern",
                "Input does not begin with an OggS capture pattern.",
                (OGG_PAGE_TRAVERSAL_SOURCE, OPUS_STREAM_TRAVERSAL_SOURCE),
            )
        )
    if not pages or any(
        issue.code
        in {
            "empty_ogg_input",
            "truncated_page_header",
            "ogg_capture_pattern",
            "truncated_segment_table",
            "truncated_page_payload",
        }
        for issue in issues
    ):
        gates.append(
            OpusOutputEmissionGate(
                "ogg_page_traversal",
                "Ogg page traversal did not cover complete headers, lacing tables, and payloads.",
                (OGG_PAGE_TRAVERSAL_SOURCE, OPUS_STREAM_TRAVERSAL_SOURCE),
            )
        )
    if any(issue.code == "missing_ogg_page_sequence" for issue in issues):
        gates.append(
            OpusOutputEmissionGate(
                "ogg_page_sequence",
                "At least one stream has missing Ogg page sequence numbers.",
                (OGG_SEQUENCE_SOURCE, OPUS_STREAM_TRAVERSAL_SOURCE),
            )
        )
    if any(
        issue.code in {"dangling_continuation_page", "unterminated_ogg_packet"} for issue in issues
    ):
        gates.append(
            OpusOutputEmissionGate(
                "ogg_packet_boundaries",
                "At least one Opus packet boundary is dangling or unterminated.",
                (OGG_PACKET_BOUNDARY_SOURCE, OPUS_STREAM_TRAVERSAL_SOURCE),
            )
        )
    if head.status == "absent":
        gates.append(
            OpusOutputEmissionGate(
                "missing_opus_head_packet",
                "No OpusHead packet was routed from the first two packets of an Ogg stream.",
                (OPUS_PACKET_ROUTE_SOURCE, OPUS_MAIN_SOURCE),
            )
        )
    elif head.status == "truncated":
        gates.append(
            OpusOutputEmissionGate(
                "truncated_opus_head_packet",
                "OpusHead ended before all Opus.pm header fields could be read.",
                (OPUS_PACKET_ROUTE_SOURCE, OPUS_HEADER_SOURCE),
            )
        )
    if not tags:
        gates.append(
            OpusOutputEmissionGate(
                "missing_opus_tags_packet",
                "No OpusTags packet was routed from the first two packets of an Ogg stream.",
                (OPUS_PACKET_ROUTE_SOURCE, OPUS_MAIN_SOURCE, OPUS_VORBIS_BOUNDARY_SOURCE),
            )
        )
    if any(tag.comment_parse.status == "malformed" for tag in tags):
        gates.append(
            OpusOutputEmissionGate(
                "malformed_opus_tags_comment",
                "The routed OpusTags packet did not parse as Vorbis comments.",
                (OPUS_MAIN_SOURCE, OPUS_VORBIS_BOUNDARY_SOURCE),
            )
        )
    if requested_parse.status == "malformed":
        gates.append(
            OpusOutputEmissionGate(
                "requested_vorbis_comment_payload",
                "Requested replacement comment payload is malformed.",
                (OPUS_VORBIS_BOUNDARY_SOURCE,),
            )
        )
    if requested_rewrite is not None and requested_rewrite.requested:
        gates.extend(
            (
                OpusOutputEmissionGate(
                    "opus_metadata_rewrite_not_supported",
                    "Opus.pm exposes read tables only; requested Opus metadata rewrites are gated.",
                    (OPUS_MAIN_SOURCE, OPUS_HEADER_SOURCE),
                ),
                OpusOutputEmissionGate(
                    "opus_stream_rewrite_not_implemented",
                    "This planner preserves Ogg Opus pages and does not rebuild stream bytes.",
                    (OPUS_STREAM_TRAVERSAL_SOURCE, OPUS_NON_MUTATING_SOURCE),
                ),
            )
        )
    if not allow_output_emission:
        gates.append(
            OpusOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "Opus stream transaction plans are non-mutating unless emission is explicit.",
                (OPUS_NON_MUTATING_SOURCE,),
            )
        )
    return tuple(gates)


def _has_structural_gate(gates: tuple[OpusOutputEmissionGate, ...]) -> bool:
    structural_codes: set[OpusEmissionGateCode] = {
        "ogg_capture_pattern",
        "ogg_page_traversal",
        "ogg_page_sequence",
        "ogg_packet_boundaries",
        "missing_opus_head_packet",
        "missing_opus_tags_packet",
        "truncated_opus_head_packet",
        "malformed_opus_tags_comment",
        "requested_vorbis_comment_payload",
    }
    return any(gate.code in structural_codes for gate in gates)


def _unique_gates(gates: tuple[OpusOutputEmissionGate, ...]) -> tuple[OpusOutputEmissionGate, ...]:
    seen: set[OpusEmissionGateCode] = set()
    unique: list[OpusOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def _unique_evidence_ids(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for source in sources:
        if source not in unique:
            unique.append(source)
    return tuple(unique)
