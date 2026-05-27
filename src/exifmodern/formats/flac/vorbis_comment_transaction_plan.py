"""Typed, source-backed FLAC Vorbis-comment transaction planning.

The planner mirrors the container and comment parsing behavior in ExifTool's
FLAC and Vorbis readers without mutating files.  It validates the native FLAC
stream marker, enumerates metadata blocks up to the last-metadata-block flag,
routes Vorbis comment blocks, preserves opaque application/picture blocks, and
records the padding changes needed to absorb comment-size deltas.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

FLAC_STREAM_MARKER = b"fLaC"
FLAC_METADATA_BLOCK_HEADER_SIZE = 4
FLAC_METADATA_BLOCK_LENGTH_MAX = 0xFF_FFFF

FLAC_BLOCK_STREAMINFO = 0
FLAC_BLOCK_PADDING = 1
FLAC_BLOCK_APPLICATION = 2
FLAC_BLOCK_VORBIS_COMMENT = 4
FLAC_BLOCK_PICTURE = 6
FLAC_BLOCK_INVALID = 127

type FlacBlockActionKind = Literal[
    "preserve",
    "replace_vorbis_comment",
    "insert_vorbis_comment",
    "shrink_padding",
    "grow_padding",
    "insert_padding",
]
type FlacPaddingActionKind = Literal[
    "preserve",
    "shrink",
    "grow",
    "insert",
    "unabsorbed_growth",
    "unabsorbed_shrink",
]
type FlacVorbisRouteKind = Literal["absent", "preserve", "replace", "insert", "delete"]
type FlacVorbisParseStatus = Literal["absent", "valid", "malformed"]
type FlacTerminalStatus = Literal["parsed", "malformed", "unsupported"]
type FlacPictureCommentStatus = Literal[
    "absent",
    "decoded",
    "malformed_base64",
    "malformed_picture",
]
type FlacStreamInfoKind = Literal[
    "block_size_min",
    "block_size_max",
    "frame_size_min",
    "frame_size_max",
    "sample_rate",
    "channels",
    "bits_per_sample",
    "total_samples",
    "md5_signature",
    "duration",
]
type FlacPictureKind = Literal[
    "picture_type",
    "picture_mime_type",
    "picture_description",
    "picture_width",
    "picture_height",
    "picture_bits_per_pixel",
    "picture_indexed_colors",
    "picture_length",
    "picture",
]

FLAC_MARKER_SOURCE = "flac.marker"
FLAC_BLOCK_ENUMERATION_SOURCE = "flac.block_enumeration"
FLAC_BLOCK_ROUTING_SOURCE = "flac.block_routing"
VORBIS_COMMENT_PARSE_SOURCE = "vorbis.comment_parse"
VORBIS_PICTURE_COMMENT_SOURCE = "vorbis.picture_comment"
XMP_BASE64_DECODE_SOURCE = "flac.xmp_base64_decode"
FLAC_STREAMINFO_SOURCE = "flac.streaminfo"
FLAC_PICTURE_SOURCE = "flac.picture"

FLAC_VORBIS_TRANSACTION_ORACLE_REFERENCES = (
    FLAC_MARKER_SOURCE,
    FLAC_BLOCK_ENUMERATION_SOURCE,
    FLAC_BLOCK_ROUTING_SOURCE,
    FLAC_STREAMINFO_SOURCE,
    FLAC_PICTURE_SOURCE,
    VORBIS_COMMENT_PARSE_SOURCE,
    VORBIS_PICTURE_COMMENT_SOURCE,
    XMP_BASE64_DECODE_SOURCE,
)

FLAC_PICTURE_TYPES: dict[int, str] = {
    0: "Other",
    1: "32x32 PNG Icon",
    2: "Other Icon",
    3: "Front Cover",
    4: "Back Cover",
    5: "Leaflet",
    6: "Media",
    7: "Lead Artist",
    8: "Artist",
    9: "Conductor",
    10: "Band",
    11: "Composer",
    12: "Lyricist",
    13: "Recording Studio or Location",
    14: "Recording Session",
    15: "Performance",
    16: "Capture from Movie or Video",
    17: "Bright(ly) Colored Fish",
    18: "Illustration",
    19: "Band Logo",
    20: "Publisher Logo",
}


@dataclass(frozen=True)
class FlacPlanIssue:
    code: str
    message: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FlacEmissionGate:
    code: str
    passed: bool
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FlacMetadataBlockPlan:
    index: int
    block_type: int
    block_name: str
    header_offset: int
    payload_offset: int
    payload_length: int
    is_last: bool
    payload: bytes
    evidence_ids: tuple[str, ...]

    @property
    def encoded_length(self) -> int:
        return FLAC_METADATA_BLOCK_HEADER_SIZE + self.payload_length

    @property
    def end_offset(self) -> int:
        return self.payload_offset + self.payload_length


@dataclass(frozen=True)
class FlacVorbisCommentEntryPlan:
    index: int
    tag: str
    value: str
    raw_length: int
    routes_to_flac_picture: bool
    picture_comment: FlacPictureCommentPlan | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FlacStreamInfoTagPlan:
    kind: FlacStreamInfoKind
    tag_name: str
    status: FlacTerminalStatus
    raw_value: int | str | None
    rendered_value: int | float | str | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FlacPictureTagPlan:
    kind: FlacPictureKind
    tag_name: str
    status: FlacTerminalStatus
    raw_value: int | str | bytes | None
    rendered_value: int | str | bytes | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FlacPictureCommentPlan:
    status: FlacPictureCommentStatus
    decoded_length: int | None
    picture_tags: tuple[FlacPictureTagPlan, ...]
    issue: FlacPlanIssue | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FlacTerminalBlockPlan:
    source_index: int
    block_type: int
    block_name: str
    status: FlacTerminalStatus
    stream_info_tags: tuple[FlacStreamInfoTagPlan, ...]
    picture_tags: tuple[FlacPictureTagPlan, ...]
    issue: FlacPlanIssue | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FlacVorbisCommentParsePlan:
    status: FlacVorbisParseStatus
    vendor: str | None
    declared_comment_count: int | None
    parsed_comment_count: int
    entries: tuple[FlacVorbisCommentEntryPlan, ...]
    issue: FlacPlanIssue | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FlacVorbisCommentRoutePlan:
    kind: FlacVorbisRouteKind
    target_source_index: int | None
    duplicate_source_indices: tuple[int, ...]
    original_parse: FlacVorbisCommentParsePlan
    replacement_parse: FlacVorbisCommentParsePlan
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FlacPaddingActionPlan:
    kind: FlacPaddingActionKind
    source_index: int | None
    output_index: int | None
    original_payload_length: int
    output_payload_length: int
    absorbed_size_delta: int
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FlacPaddingStrategyPlan:
    requested_size_delta: int
    absorbed_size_delta: int
    residual_size_delta: int
    input_padding_payload_bytes: int
    output_padding_payload_bytes: int
    actions: tuple[FlacPaddingActionPlan, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FlacOutputMetadataBlockPlan:
    output_index: int
    block_type: int
    block_name: str
    action: FlacBlockActionKind
    source_index: int | None
    payload_length: int
    is_last: bool
    header_byte: int
    payload: bytes
    evidence_ids: tuple[str, ...]

    @property
    def encoded_length(self) -> int:
        return FLAC_METADATA_BLOCK_HEADER_SIZE + self.payload_length


@dataclass(frozen=True)
class FlacVorbisCommentTransactionPlan:
    input_size: int
    metadata_audio_offset: int | None
    audio_tail_length: int
    source_blocks: tuple[FlacMetadataBlockPlan, ...]
    terminal_blocks: tuple[FlacTerminalBlockPlan, ...]
    vorbis_route: FlacVorbisCommentRoutePlan
    padding_strategy: FlacPaddingStrategyPlan
    output_blocks: tuple[FlacOutputMetadataBlockPlan, ...]
    emission_gates: tuple[FlacEmissionGate, ...]
    output_data: bytes | None
    oracle_evidence_ids: tuple[str, ...] = FLAC_VORBIS_TRANSACTION_ORACLE_REFERENCES

    @property
    def can_emit(self) -> bool:
        return all(gate.passed for gate in self.emission_gates)

    @property
    def issues(self) -> tuple[FlacPlanIssue, ...]:
        return tuple(
            FlacPlanIssue(gate.code, gate.reason, gate.evidence_ids)
            for gate in self.emission_gates
            if not gate.passed
        )

    @property
    def output_block_types(self) -> tuple[int, ...]:
        return tuple(block.block_type for block in self.output_blocks)

    def emit(self) -> bytes:
        if self.output_data is None or not self.can_emit:
            failed = ", ".join(gate.code for gate in self.emission_gates if not gate.passed)
            raise FlacVorbisCommentTransactionBlocked(
                f"FLAC Vorbis comment transaction cannot be emitted: {failed}"
            )
        return self.output_data


class FlacVorbisCommentTransactionBlocked(ValueError):
    """Raised when a planned FLAC Vorbis comment transaction is not emit-able."""


def plan_flac_vorbis_comment_transaction(
    data: bytes,
    vorbis_comment_payload: bytes | None = None,
    *,
    delete_vorbis_comment: bool = False,
) -> FlacVorbisCommentTransactionPlan:
    """Build a non-mutating FLAC metadata transaction plan.

    ``vorbis_comment_payload`` is a complete FLAC Vorbis-comment block payload:
    little-endian vendor string, comment count, then length-prefixed comments.
    """
    if vorbis_comment_payload is not None and delete_vorbis_comment:
        raise ValueError(
            "Specify either a replacement Vorbis comment payload or deletion, not both."
        )

    source_blocks, audio_offset, scan_issues = scan_flac_metadata_blocks(data)
    terminal_blocks = tuple(
        terminal_block
        for block in source_blocks
        if (terminal_block := parse_flac_terminal_block(block))
    )
    marker_ok = data.startswith(FLAC_STREAM_MARKER)
    existing_vorbis_blocks = tuple(
        block for block in source_blocks if block.block_type == FLAC_BLOCK_VORBIS_COMMENT
    )
    original_parse = (
        parse_vorbis_comment_payload(existing_vorbis_blocks[0].payload)
        if existing_vorbis_blocks
        else absent_vorbis_comment_parse()
    )
    replacement_parse = (
        parse_vorbis_comment_payload(vorbis_comment_payload)
        if vorbis_comment_payload is not None
        else absent_vorbis_comment_parse()
    )
    route = _build_vorbis_route(
        existing_vorbis_blocks=existing_vorbis_blocks,
        replacement_payload=vorbis_comment_payload,
        delete_vorbis_comment=delete_vorbis_comment,
        original_parse=original_parse,
        replacement_parse=replacement_parse,
    )

    logical_blocks = _logical_output_blocks(
        source_blocks=source_blocks,
        replacement_payload=vorbis_comment_payload,
        delete_vorbis_comment=delete_vorbis_comment,
    )
    adjusted_blocks, padding_strategy = _apply_padding_strategy(source_blocks, logical_blocks)
    output_blocks = _finalize_output_blocks(adjusted_blocks)
    gates = _build_emission_gates(
        marker_ok=marker_ok,
        scan_issues=scan_issues,
        replacement_payload=vorbis_comment_payload,
        replacement_parse=replacement_parse,
        output_blocks=output_blocks,
    )

    output_data: bytes | None = None
    if all(gate.passed for gate in gates) and audio_offset is not None:
        output_data = _encode_flac(output_blocks, data[audio_offset:])

    return FlacVorbisCommentTransactionPlan(
        input_size=len(data),
        metadata_audio_offset=audio_offset,
        audio_tail_length=0 if audio_offset is None else len(data) - audio_offset,
        source_blocks=source_blocks,
        terminal_blocks=terminal_blocks,
        vorbis_route=route,
        padding_strategy=padding_strategy,
        output_blocks=output_blocks,
        emission_gates=gates,
        output_data=output_data,
    )


build_flac_vorbis_comment_transaction_plan = plan_flac_vorbis_comment_transaction


def encode_vorbis_comment_payload(
    vendor: str | bytes,
    comments: Mapping[str, str | Sequence[str]] | Iterable[tuple[str, str]],
) -> bytes:
    """Encode a small Vorbis-comment payload for tests and higher-level planners."""
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


def scan_flac_metadata_blocks(
    data: bytes,
) -> tuple[tuple[FlacMetadataBlockPlan, ...], int | None, tuple[FlacPlanIssue, ...]]:
    if not data.startswith(FLAC_STREAM_MARKER):
        return (
            (),
            None,
            (
                FlacPlanIssue(
                    "unsupported_flac_stream_marker",
                    "Expected native FLAC stream marker b'fLaC'.",
                    (FLAC_MARKER_SOURCE,),
                ),
            ),
        )

    blocks: list[FlacMetadataBlockPlan] = []
    issues: list[FlacPlanIssue] = []
    offset = len(FLAC_STREAM_MARKER)
    while True:
        if offset + FLAC_METADATA_BLOCK_HEADER_SIZE > len(data):
            issues.append(
                FlacPlanIssue(
                    "missing_last_metadata_block",
                    "No complete metadata block with the last-metadata-block flag was found.",
                    (FLAC_BLOCK_ENUMERATION_SOURCE,),
                )
            )
            return tuple(blocks), None, tuple(issues)

        header = data[offset : offset + FLAC_METADATA_BLOCK_HEADER_SIZE]
        flag = header[0]
        block_type = flag & 0x7F
        payload_length = int.from_bytes(header[1:4], "big")
        payload_offset = offset + FLAC_METADATA_BLOCK_HEADER_SIZE
        end_offset = payload_offset + payload_length
        if end_offset > len(data):
            issues.append(
                FlacPlanIssue(
                    "truncated_metadata_block",
                    (
                        f"Metadata block {len(blocks)} declares {payload_length} bytes "
                        f"but only {max(0, len(data) - payload_offset)} remain."
                    ),
                    (FLAC_BLOCK_ENUMERATION_SOURCE,),
                )
            )
            return tuple(blocks), None, tuple(issues)

        is_last = bool(flag & 0x80)
        blocks.append(
            FlacMetadataBlockPlan(
                index=len(blocks),
                block_type=block_type,
                block_name=flac_block_name(block_type),
                header_offset=offset,
                payload_offset=payload_offset,
                payload_length=payload_length,
                is_last=is_last,
                payload=data[payload_offset:end_offset],
                evidence_ids=(FLAC_BLOCK_ENUMERATION_SOURCE, FLAC_BLOCK_ROUTING_SOURCE),
            )
        )
        offset = end_offset
        if is_last:
            return tuple(blocks), offset, tuple(issues)


def parse_vorbis_comment_payload(payload: bytes) -> FlacVorbisCommentParsePlan:
    pos = 0
    end = len(payload)
    if pos + 4 > end:
        return _malformed_vorbis_parse("Missing Vorbis vendor length.")

    vendor_length = int.from_bytes(payload[pos : pos + 4], "little")
    pos += 4
    if pos + vendor_length > end:
        return _malformed_vorbis_parse("Vorbis vendor string extends beyond the block payload.")

    vendor = payload[pos : pos + vendor_length].decode("utf-8", "replace")
    pos += vendor_length
    if pos + 4 > end:
        return FlacVorbisCommentParsePlan(
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
    entries: list[FlacVorbisCommentEntryPlan] = []
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
                f"Vorbis comment entry {index} extends beyond the block payload.",
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
            FlacVorbisCommentEntryPlan(
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

    return FlacVorbisCommentParsePlan(
        status="valid",
        vendor=vendor,
        declared_comment_count=declared_count,
        parsed_comment_count=len(entries),
        entries=tuple(entries),
        issue=None,
        evidence_ids=(VORBIS_COMMENT_PARSE_SOURCE,),
    )


def parse_flac_terminal_block(block: FlacMetadataBlockPlan) -> FlacTerminalBlockPlan | None:
    if block.block_type == FLAC_BLOCK_STREAMINFO:
        return _parse_streaminfo_block(block)
    if block.block_type == FLAC_BLOCK_PICTURE:
        return _parse_picture_block(block)
    return None


def parse_flac_picture_payload(payload: bytes, *, source_index: int = 0) -> FlacTerminalBlockPlan:
    """Parse a FLAC Picture payload using the source-backed Picture table shape."""
    return _parse_picture_block(
        FlacMetadataBlockPlan(
            index=source_index,
            block_type=FLAC_BLOCK_PICTURE,
            block_name="Picture",
            header_offset=0,
            payload_offset=0,
            payload_length=len(payload),
            is_last=False,
            payload=payload,
            evidence_ids=(FLAC_PICTURE_SOURCE,),
        )
    )


def parse_metadata_block_picture_comment(value: str) -> FlacPictureCommentPlan:
    """Decode and route a Vorbis METADATA_BLOCK_PICTURE comment."""
    decoded = decode_exiftool_base64(value)
    if decoded is None:
        issue = FlacPlanIssue(
            code="malformed_metadata_block_picture_base64",
            message="METADATA_BLOCK_PICTURE did not decode as base64.",
            evidence_ids=(VORBIS_PICTURE_COMMENT_SOURCE, XMP_BASE64_DECODE_SOURCE),
        )
        return FlacPictureCommentPlan(
            status="malformed_base64",
            decoded_length=None,
            picture_tags=(),
            issue=issue,
            evidence_ids=(VORBIS_PICTURE_COMMENT_SOURCE, XMP_BASE64_DECODE_SOURCE),
        )

    picture_block = parse_flac_picture_payload(decoded)
    if picture_block.status != "parsed":
        issue = picture_block.issue or FlacPlanIssue(
            code="malformed_metadata_block_picture",
            message="METADATA_BLOCK_PICTURE did not parse as a FLAC Picture block.",
            evidence_ids=(VORBIS_PICTURE_COMMENT_SOURCE, FLAC_PICTURE_SOURCE),
        )
        return FlacPictureCommentPlan(
            status="malformed_picture",
            decoded_length=len(decoded),
            picture_tags=picture_block.picture_tags,
            issue=issue,
            evidence_ids=(
                VORBIS_PICTURE_COMMENT_SOURCE,
                XMP_BASE64_DECODE_SOURCE,
                FLAC_PICTURE_SOURCE,
            ),
        )

    return FlacPictureCommentPlan(
        status="decoded",
        decoded_length=len(decoded),
        picture_tags=picture_block.picture_tags,
        issue=None,
        evidence_ids=(
            VORBIS_PICTURE_COMMENT_SOURCE,
            XMP_BASE64_DECODE_SOURCE,
            FLAC_PICTURE_SOURCE,
        ),
    )


def _parse_streaminfo_block(block: FlacMetadataBlockPlan) -> FlacTerminalBlockPlan:
    if block.payload_length < 34:
        issue = FlacPlanIssue(
            "malformed_streaminfo_block",
            "STREAMINFO payload ended before the 34-byte FLAC StreamInfo table.",
            (FLAC_STREAMINFO_SOURCE,),
        )
        return FlacTerminalBlockPlan(
            source_index=block.index,
            block_type=block.block_type,
            block_name=block.block_name,
            status="malformed",
            stream_info_tags=(
                FlacStreamInfoTagPlan(
                    kind="block_size_min",
                    tag_name="StreamInfo",
                    status="malformed",
                    raw_value=None,
                    rendered_value=None,
                    reason=issue.message,
                    evidence_ids=(FLAC_STREAMINFO_SOURCE,),
                ),
            ),
            picture_tags=(),
            issue=issue,
            evidence_ids=(FLAC_STREAMINFO_SOURCE,),
        )
    payload = block.payload
    block_size_min = int.from_bytes(payload[0:2], "big")
    block_size_max = int.from_bytes(payload[2:4], "big")
    frame_size_min = int.from_bytes(payload[4:7], "big")
    frame_size_max = int.from_bytes(payload[7:10], "big")
    packed = int.from_bytes(payload[10:18], "big")
    sample_rate = (packed >> 44) & 0xFFFFF
    channels = ((packed >> 41) & 0x07) + 1
    bits_per_sample = ((packed >> 36) & 0x1F) + 1
    total_samples = packed & 0xFFFFFFFFF
    md5 = payload[18:34].hex()
    duration: float | None = total_samples / sample_rate if sample_rate else None
    tags = (
        _streaminfo_tag("block_size_min", "BlockSizeMin", block_size_min),
        _streaminfo_tag("block_size_max", "BlockSizeMax", block_size_max),
        _streaminfo_tag("frame_size_min", "FrameSizeMin", frame_size_min),
        _streaminfo_tag("frame_size_max", "FrameSizeMax", frame_size_max),
        _streaminfo_tag("sample_rate", "SampleRate", sample_rate),
        _streaminfo_tag("channels", "Channels", channels),
        _streaminfo_tag("bits_per_sample", "BitsPerSample", bits_per_sample),
        _streaminfo_tag("total_samples", "TotalSamples", total_samples),
        _streaminfo_tag("md5_signature", "MD5Signature", md5),
        FlacStreamInfoTagPlan(
            kind="duration",
            tag_name="Duration",
            status="parsed" if duration is not None else "unsupported",
            raw_value=total_samples,
            rendered_value=duration,
            reason="Computed Duration from StreamInfo SampleRate and TotalSamples.",
            evidence_ids=(FLAC_STREAMINFO_SOURCE,),
        ),
    )
    return FlacTerminalBlockPlan(
        source_index=block.index,
        block_type=block.block_type,
        block_name=block.block_name,
        status="parsed",
        stream_info_tags=tags,
        picture_tags=(),
        issue=None,
        evidence_ids=(FLAC_STREAMINFO_SOURCE,),
    )


def _streaminfo_tag(
    kind: FlacStreamInfoKind, tag_name: str, value: int | str
) -> FlacStreamInfoTagPlan:
    return FlacStreamInfoTagPlan(
        kind=kind,
        tag_name=tag_name,
        status="parsed",
        raw_value=value,
        rendered_value=value,
        reason=f"Parsed {tag_name} from the FLAC StreamInfo bit table.",
        evidence_ids=(FLAC_STREAMINFO_SOURCE,),
    )


def _parse_picture_block(block: FlacMetadataBlockPlan) -> FlacTerminalBlockPlan:
    tags: list[FlacPictureTagPlan] = []
    pos = 0
    payload = block.payload
    end = len(payload)

    def fail(message: str) -> FlacTerminalBlockPlan:
        issue = FlacPlanIssue("malformed_picture_block", message, (FLAC_PICTURE_SOURCE,))
        return FlacTerminalBlockPlan(
            source_index=block.index,
            block_type=block.block_type,
            block_name=block.block_name,
            status="malformed",
            stream_info_tags=(),
            picture_tags=(
                *tuple(tags),
                FlacPictureTagPlan(
                    kind="picture",
                    tag_name="Picture",
                    status="malformed",
                    raw_value=None,
                    rendered_value=None,
                    reason=message,
                    evidence_ids=(FLAC_PICTURE_SOURCE,),
                ),
            ),
            issue=issue,
            evidence_ids=(FLAC_PICTURE_SOURCE,),
        )

    if end < 4:
        return fail("Picture block ended before PictureType.")
    picture_type = int.from_bytes(payload[pos : pos + 4], "big")
    pos += 4
    tags.append(
        _picture_tag(
            "picture_type",
            "PictureType",
            picture_type,
            FLAC_PICTURE_TYPES.get(picture_type, picture_type),
        )
    )
    if pos + 4 > end:
        return fail("Picture block ended before MIME type length.")
    mime_length = int.from_bytes(payload[pos : pos + 4], "big")
    pos += 4
    if pos + mime_length > end:
        return fail("Picture MIME type extends beyond the block payload.")
    mime = payload[pos : pos + mime_length].decode("latin-1")
    pos += mime_length
    tags.append(_picture_tag("picture_mime_type", "PictureMIMEType", mime, mime))
    if pos + 4 > end:
        return fail("Picture block ended before description length.")
    description_length = int.from_bytes(payload[pos : pos + 4], "big")
    pos += 4
    if pos + description_length > end:
        return fail("Picture description extends beyond the block payload.")
    description = payload[pos : pos + description_length].decode("utf-8", "replace")
    pos += description_length
    tags.append(_picture_tag("picture_description", "PictureDescription", description, description))
    scalar_fields: tuple[tuple[FlacPictureKind, str], ...] = (
        ("picture_width", "PictureWidth"),
        ("picture_height", "PictureHeight"),
        ("picture_bits_per_pixel", "PictureBitsPerPixel"),
        ("picture_indexed_colors", "PictureIndexedColors"),
        ("picture_length", "PictureLength"),
    )
    values: list[int] = []
    for kind, tag_name in scalar_fields:
        if pos + 4 > end:
            return fail(f"Picture block ended before {tag_name}.")
        value = int.from_bytes(payload[pos : pos + 4], "big")
        pos += 4
        values.append(value)
        tags.append(_picture_tag(kind, tag_name, value, value))
    picture_length = values[-1]
    if pos + picture_length > end:
        return fail("Picture data extends beyond the declared picture block payload.")
    picture = payload[pos : pos + picture_length]
    tags.append(_picture_tag("picture", "Picture", picture, picture))
    return FlacTerminalBlockPlan(
        source_index=block.index,
        block_type=block.block_type,
        block_name=block.block_name,
        status="parsed",
        stream_info_tags=(),
        picture_tags=tuple(tags),
        issue=None,
        evidence_ids=(FLAC_PICTURE_SOURCE,),
    )


def _picture_tag(
    kind: FlacPictureKind,
    tag_name: str,
    raw_value: int | str | bytes,
    rendered_value: int | str | bytes,
) -> FlacPictureTagPlan:
    return FlacPictureTagPlan(
        kind=kind,
        tag_name=tag_name,
        status="parsed",
        raw_value=raw_value,
        rendered_value=rendered_value,
        reason=f"Parsed {tag_name} from the FLAC Picture binary table.",
        evidence_ids=(FLAC_PICTURE_SOURCE,),
    )


def absent_vorbis_comment_parse() -> FlacVorbisCommentParsePlan:
    return FlacVorbisCommentParsePlan(
        status="absent",
        vendor=None,
        declared_comment_count=None,
        parsed_comment_count=0,
        entries=(),
        issue=None,
        evidence_ids=(VORBIS_COMMENT_PARSE_SOURCE,),
    )


@dataclass(frozen=True)
class _MutableOutputBlock:
    block_type: int
    payload: bytes
    source_index: int | None
    action: FlacBlockActionKind
    evidence_ids: tuple[str, ...]

    @property
    def encoded_length(self) -> int:
        return FLAC_METADATA_BLOCK_HEADER_SIZE + len(self.payload)


def _build_vorbis_route(
    *,
    existing_vorbis_blocks: tuple[FlacMetadataBlockPlan, ...],
    replacement_payload: bytes | None,
    delete_vorbis_comment: bool,
    original_parse: FlacVorbisCommentParsePlan,
    replacement_parse: FlacVorbisCommentParsePlan,
) -> FlacVorbisCommentRoutePlan:
    if delete_vorbis_comment:
        kind: FlacVorbisRouteKind = "delete"
    elif replacement_payload is not None:
        kind = "replace" if existing_vorbis_blocks else "insert"
    elif existing_vorbis_blocks:
        kind = "preserve"
    else:
        kind = "absent"
    return FlacVorbisCommentRoutePlan(
        kind=kind,
        target_source_index=existing_vorbis_blocks[0].index if existing_vorbis_blocks else None,
        duplicate_source_indices=tuple(block.index for block in existing_vorbis_blocks[1:]),
        original_parse=original_parse,
        replacement_parse=replacement_parse,
        evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE, VORBIS_COMMENT_PARSE_SOURCE),
    )


def _logical_output_blocks(
    *,
    source_blocks: tuple[FlacMetadataBlockPlan, ...],
    replacement_payload: bytes | None,
    delete_vorbis_comment: bool,
) -> tuple[_MutableOutputBlock, ...]:
    blocks: list[_MutableOutputBlock] = []
    inserted = False
    has_vorbis_comment = any(
        block.block_type == FLAC_BLOCK_VORBIS_COMMENT for block in source_blocks
    )
    for block in source_blocks:
        if block.block_type == FLAC_BLOCK_VORBIS_COMMENT:
            if delete_vorbis_comment:
                continue
            if replacement_payload is not None and not inserted:
                blocks.append(
                    _MutableOutputBlock(
                        block_type=FLAC_BLOCK_VORBIS_COMMENT,
                        payload=replacement_payload,
                        source_index=block.index,
                        action="replace_vorbis_comment",
                        evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE, VORBIS_COMMENT_PARSE_SOURCE),
                    )
                )
                inserted = True
                continue
        blocks.append(
            _MutableOutputBlock(
                block_type=block.block_type,
                payload=block.payload,
                source_index=block.index,
                action="preserve",
                evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE,),
            )
        )
        if (
            replacement_payload is not None
            and not inserted
            and not has_vorbis_comment
            and block.block_type == FLAC_BLOCK_STREAMINFO
        ):
            blocks.append(
                _MutableOutputBlock(
                    block_type=FLAC_BLOCK_VORBIS_COMMENT,
                    payload=replacement_payload,
                    source_index=None,
                    action="insert_vorbis_comment",
                    evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE, VORBIS_COMMENT_PARSE_SOURCE),
                )
            )
            inserted = True
    if replacement_payload is not None and not inserted:
        blocks.insert(
            0,
            _MutableOutputBlock(
                block_type=FLAC_BLOCK_VORBIS_COMMENT,
                payload=replacement_payload,
                source_index=None,
                action="insert_vorbis_comment",
                evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE, VORBIS_COMMENT_PARSE_SOURCE),
            ),
        )
    return tuple(blocks)


def _apply_padding_strategy(
    source_blocks: tuple[FlacMetadataBlockPlan, ...],
    logical_blocks: tuple[_MutableOutputBlock, ...],
) -> tuple[tuple[_MutableOutputBlock, ...], FlacPaddingStrategyPlan]:
    requested_delta = _encoded_blocks_size(logical_blocks) - _source_blocks_size(source_blocks)
    blocks = list(logical_blocks)
    actions: list[FlacPaddingActionPlan] = []
    remaining = requested_delta

    if requested_delta > 0:
        for output_index, block in enumerate(blocks):
            if remaining <= 0:
                break
            if block.block_type != FLAC_BLOCK_PADDING:
                continue
            original_length = len(block.payload)
            consume = min(original_length, remaining)
            if consume == 0:
                actions.append(_preserve_padding_action(block, output_index))
                continue
            new_length = original_length - consume
            blocks[output_index] = _MutableOutputBlock(
                block_type=FLAC_BLOCK_PADDING,
                payload=b"\x00" * new_length,
                source_index=block.source_index,
                action="shrink_padding",
                evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE,),
            )
            actions.append(
                FlacPaddingActionPlan(
                    kind="shrink",
                    source_index=block.source_index,
                    output_index=output_index,
                    original_payload_length=original_length,
                    output_payload_length=new_length,
                    absorbed_size_delta=consume,
                    reason="Shrank FLAC padding payload to absorb Vorbis comment growth.",
                    evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE,),
                )
            )
            remaining -= consume
        if remaining > 0:
            actions.append(
                FlacPaddingActionPlan(
                    kind="unabsorbed_growth",
                    source_index=None,
                    output_index=None,
                    original_payload_length=0,
                    output_payload_length=0,
                    absorbed_size_delta=0,
                    reason="Vorbis comment growth exceeds available padding; output grows.",
                    evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE,),
                )
            )
    elif requested_delta < 0:
        shrink = -requested_delta
        padding_index = _first_padding_index(blocks)
        if padding_index is not None:
            block = blocks[padding_index]
            original_length = len(block.payload)
            blocks[padding_index] = _MutableOutputBlock(
                block_type=FLAC_BLOCK_PADDING,
                payload=b"\x00" * (original_length + shrink),
                source_index=block.source_index,
                action="grow_padding",
                evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE,),
            )
            actions.append(
                FlacPaddingActionPlan(
                    kind="grow",
                    source_index=block.source_index,
                    output_index=padding_index,
                    original_payload_length=original_length,
                    output_payload_length=original_length + shrink,
                    absorbed_size_delta=-shrink,
                    reason="Grew existing FLAC padding payload to absorb Vorbis comment shrinkage.",
                    evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE,),
                )
            )
            remaining = 0
        elif shrink >= FLAC_METADATA_BLOCK_HEADER_SIZE:
            padding_payload_length = shrink - FLAC_METADATA_BLOCK_HEADER_SIZE
            blocks.append(
                _MutableOutputBlock(
                    block_type=FLAC_BLOCK_PADDING,
                    payload=b"\x00" * padding_payload_length,
                    source_index=None,
                    action="insert_padding",
                    evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE,),
                )
            )
            actions.append(
                FlacPaddingActionPlan(
                    kind="insert",
                    source_index=None,
                    output_index=len(blocks) - 1,
                    original_payload_length=0,
                    output_payload_length=padding_payload_length,
                    absorbed_size_delta=-shrink,
                    reason="Inserted a FLAC padding block to keep the metadata area size stable.",
                    evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE,),
                )
            )
            remaining = 0
        else:
            actions.append(
                FlacPaddingActionPlan(
                    kind="unabsorbed_shrink",
                    source_index=None,
                    output_index=None,
                    original_payload_length=0,
                    output_payload_length=0,
                    absorbed_size_delta=0,
                    reason="Comment shrinkage is smaller than a new padding block header.",
                    evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE,),
                )
            )
    else:
        actions.extend(
            _preserve_padding_action(block, output_index)
            for output_index, block in enumerate(blocks)
            if block.block_type == FLAC_BLOCK_PADDING
        )

    absorbed = requested_delta - remaining
    output_padding_payload_bytes = sum(
        len(block.payload) for block in blocks if block.block_type == FLAC_BLOCK_PADDING
    )
    return (
        tuple(blocks),
        FlacPaddingStrategyPlan(
            requested_size_delta=requested_delta,
            absorbed_size_delta=absorbed,
            residual_size_delta=remaining,
            input_padding_payload_bytes=sum(
                block.payload_length
                for block in source_blocks
                if block.block_type == FLAC_BLOCK_PADDING
            ),
            output_padding_payload_bytes=output_padding_payload_bytes,
            actions=tuple(actions),
            evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE,),
        ),
    )


def _finalize_output_blocks(
    blocks: tuple[_MutableOutputBlock, ...],
) -> tuple[FlacOutputMetadataBlockPlan, ...]:
    last_index = len(blocks) - 1
    output: list[FlacOutputMetadataBlockPlan] = []
    for index, block in enumerate(blocks):
        is_last = index == last_index
        header_byte = block.block_type | (0x80 if is_last else 0)
        output.append(
            FlacOutputMetadataBlockPlan(
                output_index=index,
                block_type=block.block_type,
                block_name=flac_block_name(block.block_type),
                action=block.action,
                source_index=block.source_index,
                payload_length=len(block.payload),
                is_last=is_last,
                header_byte=header_byte,
                payload=block.payload,
                evidence_ids=(*block.evidence_ids, FLAC_BLOCK_ENUMERATION_SOURCE),
            )
        )
    return tuple(output)


def _build_emission_gates(
    *,
    marker_ok: bool,
    scan_issues: tuple[FlacPlanIssue, ...],
    replacement_payload: bytes | None,
    replacement_parse: FlacVorbisCommentParsePlan,
    output_blocks: tuple[FlacOutputMetadataBlockPlan, ...],
) -> tuple[FlacEmissionGate, ...]:
    gates: list[FlacEmissionGate] = [
        FlacEmissionGate(
            code="flac_stream_marker",
            passed=marker_ok,
            reason="Input starts with the native FLAC fLaC marker."
            if marker_ok
            else "Input does not start with the native FLAC fLaC marker.",
            evidence_ids=(FLAC_MARKER_SOURCE,),
        ),
        FlacEmissionGate(
            code="metadata_block_enumeration",
            passed=not scan_issues,
            reason="Metadata blocks were enumerated through a last-metadata-block flag."
            if not scan_issues
            else "; ".join(issue.message for issue in scan_issues),
            evidence_ids=(FLAC_BLOCK_ENUMERATION_SOURCE,),
        ),
        FlacEmissionGate(
            code="replacement_vorbis_comment_payload",
            passed=replacement_payload is None or replacement_parse.status == "valid",
            reason="Replacement Vorbis comment payload is valid or absent."
            if replacement_payload is None or replacement_parse.status == "valid"
            else replacement_parse.issue.message
            if replacement_parse.issue is not None
            else "Replacement Vorbis comment payload is malformed.",
            evidence_ids=(VORBIS_COMMENT_PARSE_SOURCE,),
        ),
        FlacEmissionGate(
            code="output_metadata_block_lengths",
            passed=all(
                block.payload_length <= FLAC_METADATA_BLOCK_LENGTH_MAX for block in output_blocks
            ),
            reason="All output metadata block payloads fit the FLAC 24-bit length field.",
            evidence_ids=(FLAC_BLOCK_ENUMERATION_SOURCE,),
        ),
        FlacEmissionGate(
            code="last_metadata_block_flag",
            passed=bool(output_blocks) and sum(1 for block in output_blocks if block.is_last) == 1,
            reason="Exactly the final planned metadata block carries the last flag.",
            evidence_ids=(FLAC_BLOCK_ENUMERATION_SOURCE,),
        ),
    ]
    return tuple(gates)


def _encode_flac(
    output_blocks: tuple[FlacOutputMetadataBlockPlan, ...], audio_tail: bytes
) -> bytes:
    encoded = bytearray(FLAC_STREAM_MARKER)
    for block in output_blocks:
        if block.payload_length > FLAC_METADATA_BLOCK_LENGTH_MAX:
            raise FlacVorbisCommentTransactionBlocked(
                f"FLAC metadata block {block.output_index} exceeds 24-bit length."
            )
        encoded.append(block.header_byte)
        encoded += block.payload_length.to_bytes(3, "big")
        encoded += block.payload
    encoded += audio_tail
    return bytes(encoded)


def decode_exiftool_base64(value: str) -> bytes | None:
    """Decode base64 with ExifTool's XMP::DecodeBase64 truncation rules."""
    clean_chars: list[str] = []
    for char in value:
        if char in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/= \t\n\r\f":
            clean_chars.append(char)
            continue
        break
    clean = "".join(clean_chars)
    clean = "".join(char for char in clean if char not in " \t\n\r\f")
    try:
        return base64.b64decode(clean, validate=False)
    except binascii.Error:
        return None


def _malformed_vorbis_parse(
    message: str,
    *,
    vendor: str | None = None,
    declared_count: int | None = None,
    entries: tuple[FlacVorbisCommentEntryPlan, ...] = (),
) -> FlacVorbisCommentParsePlan:
    issue = FlacPlanIssue(
        code="malformed_vorbis_comment",
        message=message,
        evidence_ids=(VORBIS_COMMENT_PARSE_SOURCE,),
    )
    return FlacVorbisCommentParsePlan(
        status="malformed",
        vendor=vendor,
        declared_comment_count=declared_count,
        parsed_comment_count=len(entries),
        entries=entries,
        issue=issue,
        evidence_ids=(VORBIS_COMMENT_PARSE_SOURCE,),
    )


def _encoded_blocks_size(blocks: Sequence[_MutableOutputBlock]) -> int:
    return sum(block.encoded_length for block in blocks)


def _source_blocks_size(blocks: Sequence[FlacMetadataBlockPlan]) -> int:
    return sum(block.encoded_length for block in blocks)


def _first_padding_index(blocks: Sequence[_MutableOutputBlock]) -> int | None:
    for index, block in enumerate(blocks):
        if block.block_type == FLAC_BLOCK_PADDING:
            return index
    return None


def _preserve_padding_action(
    block: _MutableOutputBlock, output_index: int
) -> FlacPaddingActionPlan:
    return FlacPaddingActionPlan(
        kind="preserve",
        source_index=block.source_index,
        output_index=output_index,
        original_payload_length=len(block.payload),
        output_payload_length=len(block.payload),
        absorbed_size_delta=0,
        reason="Preserved existing FLAC padding payload.",
        evidence_ids=(FLAC_BLOCK_ROUTING_SOURCE,),
    )


def flac_block_name(block_type: int) -> str:
    names = {
        FLAC_BLOCK_STREAMINFO: "StreamInfo",
        FLAC_BLOCK_PADDING: "Padding",
        FLAC_BLOCK_APPLICATION: "Application",
        3: "SeekTable",
        FLAC_BLOCK_VORBIS_COMMENT: "VorbisComment",
        5: "CueSheet",
        FLAC_BLOCK_PICTURE: "Picture",
        FLAC_BLOCK_INVALID: "Invalid",
    }
    if block_type in names:
        return names[block_type]
    if 7 <= block_type <= 126:
        return "Reserved"
    return "Unknown"
