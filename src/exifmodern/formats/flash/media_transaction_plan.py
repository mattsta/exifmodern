"""Source-backed, non-mutating Flash media transaction planning.

The planner mirrors the read responsibilities in ExifTool's Flash.pm for SWF
and FLV: validate container signatures, route SWF header geometry and metadata
tags, route FLV audio/video/meta packets, preserve payload bytes, and keep byte
emission behind explicit gates.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Literal

FLASH_PM_SOURCE_PATH = "lib/Image/ExifTool/Flash.pm"

type FlashEvidenceId = str


@dataclass(frozen=True)
class FlashEvidenceAnchor:
    path: str
    line_start: int
    line_end: int
    symbol: str
    evidence: str


SWF_SIGNATURE_SOURCE: FlashEvidenceId = "flash.swf.signature"
SWF_HEADER_SOURCE: FlashEvidenceId = "flash.swf.header"
SWF_TAG_ROUTE_SOURCE: FlashEvidenceId = "flash.swf.tag_route"
FLASH_MAIN_TABLE_SOURCE: FlashEvidenceId = "flash.table.main"
FLV_HEADER_SOURCE: FlashEvidenceId = "flash.flv.header"
FLV_PACKET_ROUTE_SOURCE: FlashEvidenceId = "flash.flv.packet_route"
FLV_TABLE_SOURCE: FlashEvidenceId = "flash.table.flv"
FLASH_AUDIO_TABLE_SOURCE: FlashEvidenceId = "flash.table.audio"
FLASH_VIDEO_TABLE_SOURCE: FlashEvidenceId = "flash.table.video"
FLASH_META_TABLE_SOURCE: FlashEvidenceId = "flash.table.meta"
AMF_PROCESS_SOURCE: FlashEvidenceId = "flash.amf.process_meta"
AMF_PACKET_FILTER_SOURCE: FlashEvidenceId = "flash.amf.packet_filter"
FLASH_NON_MUTATING_SOURCE: FlashEvidenceId = "flash.non_mutating_planner"

FLASH_EVIDENCE_ANCHORS: dict[FlashEvidenceId, FlashEvidenceAnchor] = {
    SWF_SIGNATURE_SOURCE: FlashEvidenceAnchor(
        path=FLASH_PM_SOURCE_PATH,
        line_start=570,
        line_end=585,
        symbol="ProcessSWF signature and compressed reads",
        evidence=(
            "ProcessSWF accepts FWS/CWS, emits FlashVersion and Compressed, then reads "
            "inflated bytes when needed."
        ),
    ),
    SWF_HEADER_SOURCE: FlashEvidenceAnchor(
        path=FLASH_PM_SOURCE_PATH,
        line_start=587,
        line_end=607,
        symbol="ProcessSWF frame header",
        evidence=(
            "ProcessSWF unpacks the RECT bit field, frame rate, frame count, and derived duration."
        ),
    ),
    SWF_TAG_ROUTE_SOURCE: FlashEvidenceAnchor(
        path=FLASH_PM_SOURCE_PATH,
        line_start=609,
        line_end=660,
        symbol="ProcessSWF tag scan",
        evidence=(
            "ProcessSWF scans tag 69 FlashAttributes and tag 77 XMP, continuing after "
            "HasMetadata is set."
        ),
    ),
    FLASH_MAIN_TABLE_SOURCE: FlashEvidenceAnchor(
        path=FLASH_PM_SOURCE_PATH,
        line_start=35,
        line_end=63,
        symbol="%Image::ExifTool::Flash::Main",
        evidence=(
            "The SWF table defines FlashVersion, Compressed, geometry, frame count, "
            "duration, attributes, and XMP."
        ),
    ),
    FLV_HEADER_SOURCE: FlashEvidenceAnchor(
        path=FLASH_PM_SOURCE_PATH,
        line_start=515,
        line_end=524,
        symbol="ProcessFLV header",
        evidence=(
            "ProcessFLV accepts FLV version 1, reads flags and data offset, "
            "and masks audio/video bits."
        ),
    ),
    FLV_PACKET_ROUTE_SOURCE: FlashEvidenceAnchor(
        path=FLASH_PM_SOURCE_PATH,
        line_start=525,
        line_end=561,
        symbol="ProcessFLV packet loop",
        evidence=(
            "ProcessFLV routes audio, video, and meta packets, reading the first "
            "audio/video header once."
        ),
    ),
    FLV_TABLE_SOURCE: FlashEvidenceAnchor(
        path=FLASH_PM_SOURCE_PATH,
        line_start=66,
        line_end=82,
        symbol="%Image::ExifTool::Flash::FLV",
        evidence="The FLV table routes packet types 0x08 Audio, 0x09 Video, and 0x12 Meta.",
    ),
    FLASH_AUDIO_TABLE_SOURCE: FlashEvidenceAnchor(
        path=FLASH_PM_SOURCE_PATH,
        line_start=85,
        line_end=124,
        symbol="%Image::ExifTool::Flash::Audio",
        evidence=(
            "The audio table maps the first FLV audio header byte to encoding, sample "
            "rate, bits, and channels."
        ),
    ),
    FLASH_VIDEO_TABLE_SOURCE: FlashEvidenceAnchor(
        path=FLASH_PM_SOURCE_PATH,
        line_start=127,
        line_end=144,
        symbol="%Image::ExifTool::Flash::Video",
        evidence=(
            "The video table maps the high nibble of the first FLV video "
            "header byte to VideoEncoding."
        ),
    ),
    FLASH_META_TABLE_SOURCE: FlashEvidenceAnchor(
        path=FLASH_PM_SOURCE_PATH,
        line_start=147,
        line_end=241,
        symbol="%Image::ExifTool::Flash::Meta",
        evidence=(
            "The meta table maps observed AMF keys including duration, width, height, "
            "codecs, and liveXML XMP."
        ),
    ),
    AMF_PROCESS_SOURCE: FlashEvidenceAnchor(
        path=FLASH_PM_SOURCE_PATH,
        line_start=284,
        line_end=512,
        symbol="ProcessMeta",
        evidence=(
            "ProcessMeta walks AMF0 scalar, map, array, date, XML, and long-string boundaries."
        ),
    ),
    AMF_PACKET_FILTER_SOURCE: FlashEvidenceAnchor(
        path=FLASH_PM_SOURCE_PATH,
        line_start=27,
        line_end=29,
        symbol="%processMetaPacket",
        evidence="Flash.pm processes only onMetaData and onXMPData AMF packet names.",
    ),
    FLASH_NON_MUTATING_SOURCE: FlashEvidenceAnchor(
        path="src/exifmodern/formats/flash/media_transaction_plan.py",
        line_start=1,
        line_end=8,
        symbol="Flash media non-mutating planner",
        evidence="This planner preserves bytes and requires explicit emission permission.",
    ),
}

FLASH_TRANSACTION_SOURCES = (
    SWF_SIGNATURE_SOURCE,
    SWF_HEADER_SOURCE,
    SWF_TAG_ROUTE_SOURCE,
    FLASH_MAIN_TABLE_SOURCE,
    FLV_HEADER_SOURCE,
    FLV_PACKET_ROUTE_SOURCE,
    FLV_TABLE_SOURCE,
    FLASH_AUDIO_TABLE_SOURCE,
    FLASH_VIDEO_TABLE_SOURCE,
    FLASH_META_TABLE_SOURCE,
    AMF_PROCESS_SOURCE,
    AMF_PACKET_FILTER_SOURCE,
    FLASH_NON_MUTATING_SOURCE,
)

type FlashContainerKind = Literal["swf", "flv", "unknown"]
type FlashPlanStatus = Literal["planned", "unsupported"]
type FlashSwfCompressionKind = Literal["none", "zlib"]
type FlashSwfTagRouteKind = Literal[
    "flash_attributes",
    "xmp",
    "unmodeled_tag_preserved",
    "scan_stopped_before_unmodeled_tag",
]
type FlashFlvPacketRouteKind = Literal[
    "audio_header",
    "audio_packet_preserved",
    "video_header",
    "video_packet_preserved",
    "meta_packet",
    "unknown_packet_preserved",
]
type FlashMetaRouteKind = Literal["amf_metadata", "xmp_metadata", "ignored_meta", "malformed_meta"]
type FlashPreservationKind = Literal["swf_tag_payload", "flv_packet_payload", "media_payload"]
type FlashResponsibilityKind = Literal[
    "signature",
    "compression",
    "version",
    "frame_geometry",
    "frame_count",
    "duration",
    "flash_attributes",
    "xmp",
    "audio_header",
    "video_header",
    "flv_meta",
]
type FlashEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "unsupported_flash_signature",
    "truncated_swf_header",
    "compressed_swf_inflate_failed",
    "truncated_swf_frame_header",
    "truncated_swf_tag_header",
    "truncated_swf_tag_payload",
    "oversized_swf_extended_tag",
    "unsupported_flv_signature",
    "truncated_flv_header",
    "truncated_flv_data_offset",
    "truncated_flv_packet_header",
    "bad_flv_audio_packet",
    "bad_flv_video_packet",
    "truncated_flv_meta_packet",
    "truncated_flv_packet_payload",
    "truncated_amf_record",
    "unsupported_amf_record",
    "flash_metadata_rewrite_not_supported",
    "flash_media_rewrite_not_implemented",
]
type FlashAmfRecordStatus = Literal["valid", "truncated", "unsupported"]

PROCESSED_META_PACKET_NAMES = {"onMetaData", "onXMPData"}
SWF_TAG_NAMES: dict[int, str] = {69: "FlashAttributes", 77: "XMP"}
FLV_PACKET_NAMES: dict[int, str] = {0x08: "Audio", 0x09: "Video", 0x12: "Meta"}
FLV_AUDIO_FLAG = 0x04
FLV_VIDEO_FLAG = 0x01
SWF_MAX_EXTENDED_TAG_SIZE = 1_000_000

AUDIO_ENCODINGS: dict[int, str] = {
    0: "PCM-BE (uncompressed)",
    1: "ADPCM",
    2: "MP3",
    3: "PCM-LE (uncompressed)",
    4: "Nellymoser 16kHz Mono",
    5: "Nellymoser 8kHz Mono",
    6: "Nellymoser",
    7: "G.711 A-law logarithmic PCM",
    8: "G.711 mu-law logarithmic PCM",
    10: "AAC",
    11: "Speex",
    13: "MP3 8-Khz",
    15: "Device-specific sound",
}
AUDIO_SAMPLE_RATES: dict[int, int] = {0: 5512, 1: 11025, 2: 22050, 3: 44100}
VIDEO_ENCODINGS: dict[int, str] = {
    1: "JPEG",
    2: "Sorensen H.263",
    3: "Screen Video",
    4: "On2 VP6",
    5: "On2 VP6 Alpha",
    6: "Screen Video 2",
    7: "H.264",
}
AMF_TYPE_NAMES: dict[int, str] = {
    0x00: "double",
    0x01: "boolean",
    0x02: "string",
    0x03: "map",
    0x05: "null",
    0x06: "undefined",
    0x07: "reference",
    0x08: "mixed_array",
    0x09: "map_end",
    0x0A: "array",
    0x0B: "date",
    0x0C: "long_string",
    0x0D: "unsupported",
    0x0F: "XML",
    0x10: "typed_map",
    0x11: "AMF3data",
}


@dataclass(frozen=True)
class FlashMediaRewriteRequest:
    xmp_payload: bytes | None = None
    flv_meta_payload: bytes | None = None


@dataclass(frozen=True)
class FlashOutputEmissionGate:
    code: FlashEmissionGateCode
    reason: str
    evidence_ids: tuple[FlashEvidenceId, ...]


@dataclass(frozen=True)
class FlashResponsibilityPlan:
    kind: FlashResponsibilityKind
    available: bool
    value: int | float | str | bool | None
    reason: str
    evidence_ids: tuple[FlashEvidenceId, ...]


@dataclass(frozen=True)
class FlashPayloadPreservationPlan:
    kind: FlashPreservationKind
    offset: int
    end_offset: int
    payload: bytes
    reason: str
    evidence_ids: tuple[FlashEvidenceId, ...]


@dataclass(frozen=True)
class FlashSwfHeaderPlan:
    signature: str
    version: int
    declared_file_length: int
    compression: FlashSwfCompressionKind
    compressed: bool
    image_width: float | None
    image_height: float | None
    frame_rate: float | None
    frame_count: int | None
    duration: float | None
    frame_header_size: int | None
    status: Literal["valid", "truncated", "inflate_failed"]
    evidence_ids: tuple[FlashEvidenceId, ...]


@dataclass(frozen=True)
class FlashSwfTagPlan:
    index: int
    tag_id: int
    name: str
    offset: int
    header_size: int
    payload_offset: int
    payload_length: int
    payload: bytes
    route_kind: FlashSwfTagRouteKind
    evidence_ids: tuple[FlashEvidenceId, ...]


@dataclass(frozen=True)
class FlashSwfPlan:
    header: FlashSwfHeaderPlan | None
    tags: tuple[FlashSwfTagPlan, ...]
    flash_attributes: int | None
    xmp_payloads: tuple[bytes, ...]
    uncompressed_bytes: bytes | None
    evidence_ids: tuple[FlashEvidenceId, ...]


@dataclass(frozen=True)
class FlashFlvHeaderPlan:
    version: int
    flags: int
    has_audio_flag: bool
    has_video_flag: bool
    data_offset: int
    evidence_ids: tuple[FlashEvidenceId, ...]


@dataclass(frozen=True)
class FlashAudioHeaderPlan:
    offset: int
    raw_byte: int
    audio_encoding_id: int
    audio_encoding: str | None
    audio_sample_rate: int
    audio_bits_per_sample: int
    audio_channels: int
    evidence_ids: tuple[FlashEvidenceId, ...]


@dataclass(frozen=True)
class FlashVideoHeaderPlan:
    offset: int
    raw_byte: int
    video_encoding_id: int
    video_encoding: str | None
    evidence_ids: tuple[FlashEvidenceId, ...]


@dataclass(frozen=True)
class FlashAmfRecordPlan:
    amf_type_code: int
    amf_type_name: str
    offset: int
    value_offset: int
    end_offset: int
    status: FlashAmfRecordStatus
    name: str | None
    field_path: str | None
    value_text: str | None
    raw_value: bytes | None
    children: tuple[FlashAmfRecordPlan, ...]
    evidence_ids: tuple[FlashEvidenceId, ...]


@dataclass(frozen=True)
class FlashFlvMetaPacketPlan:
    route_kind: FlashMetaRouteKind
    event_name: str | None
    records: tuple[FlashAmfRecordPlan, ...]
    fields: tuple[FlashAmfRecordPlan, ...]
    xmp_payloads: tuple[bytes, ...]
    blocker_code: FlashEmissionGateCode | None
    evidence_ids: tuple[FlashEvidenceId, ...]


@dataclass(frozen=True)
class FlashFlvPacketPlan:
    index: int
    packet_type: int
    name: str
    offset: int
    header_size: int
    payload_offset: int
    payload_length: int
    payload: bytes
    timestamp: int
    route_kind: FlashFlvPacketRouteKind
    audio_header: FlashAudioHeaderPlan | None
    video_header: FlashVideoHeaderPlan | None
    meta_packet: FlashFlvMetaPacketPlan | None
    evidence_ids: tuple[FlashEvidenceId, ...]


@dataclass(frozen=True)
class FlashFlvPlan:
    header: FlashFlvHeaderPlan | None
    packets: tuple[FlashFlvPacketPlan, ...]
    audio_header: FlashAudioHeaderPlan | None
    video_header: FlashVideoHeaderPlan | None
    meta_packets: tuple[FlashFlvMetaPacketPlan, ...]
    evidence_ids: tuple[FlashEvidenceId, ...]


@dataclass(frozen=True)
class FlashMediaTransactionPlan:
    status: FlashPlanStatus
    container: FlashContainerKind
    input_size: int
    swf: FlashSwfPlan | None
    flv: FlashFlvPlan | None
    preservation_actions: tuple[FlashPayloadPreservationPlan, ...]
    responsibilities: tuple[FlashResponsibilityPlan, ...]
    output_emission_gates: tuple[FlashOutputEmissionGate, ...]
    evidence_ids: tuple[FlashEvidenceId, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Flash media transaction output is gated: {gate_codes}")
        return self.original_bytes


def build_flash_media_transaction_plan(
    flash_data: bytes,
    *,
    requested_rewrite: FlashMediaRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> FlashMediaTransactionPlan:
    gates: list[FlashOutputEmissionGate] = []
    if flash_data.startswith((b"FWS", b"CWS")) or len(flash_data) < 8:
        container: FlashContainerKind = "swf"
        swf, swf_gates = _build_swf_plan(flash_data)
        flv = None
        gates.extend(swf_gates)
    elif flash_data.startswith(b"FLV"):
        container = "flv"
        flv, flv_gates = _build_flv_plan(flash_data)
        swf = None
        gates.extend(flv_gates)
    else:
        container = "unknown"
        swf = None
        flv = None
        gates.append(
            FlashOutputEmissionGate(
                "unsupported_flash_signature",
                "Flash.pm accepts only FWS/CWS SWF and FLV version-1 signatures.",
                (SWF_SIGNATURE_SOURCE, FLV_HEADER_SOURCE),
            )
        )

    preservation_actions = _preservation_actions(swf, flv)
    responsibilities = _responsibility_plans(container, swf, flv)
    if requested_rewrite is not None and (
        requested_rewrite.xmp_payload is not None or requested_rewrite.flv_meta_payload is not None
    ):
        gates.extend(
            (
                FlashOutputEmissionGate(
                    "flash_metadata_rewrite_not_supported",
                    (
                        "Flash.pm defines read routing for SWF XMP and FLV AMF "
                        "metadata, not writable tags."
                    ),
                    (FLASH_MAIN_TABLE_SOURCE, FLASH_META_TABLE_SOURCE),
                ),
                FlashOutputEmissionGate(
                    "flash_media_rewrite_not_implemented",
                    (
                        "This planner preserves Flash payload bytes and does not "
                        "rewrite packet or tag sizes."
                    ),
                    (SWF_TAG_ROUTE_SOURCE, FLV_PACKET_ROUTE_SOURCE, FLASH_NON_MUTATING_SOURCE),
                ),
            )
        )
    if not allow_output_emission:
        gates.append(
            FlashOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "Flash media transaction plans are non-mutating unless emission is explicit.",
                (FLASH_NON_MUTATING_SOURCE,),
            )
        )

    output_gates = _unique_gates(tuple(gates))
    status: FlashPlanStatus = "unsupported" if _has_structural_gate(output_gates) else "planned"
    return FlashMediaTransactionPlan(
        status=status,
        container=container,
        input_size=len(flash_data),
        swf=swf,
        flv=flv,
        preservation_actions=preservation_actions,
        responsibilities=responsibilities,
        output_emission_gates=output_gates,
        evidence_ids=_unique_sources(
            (
                *FLASH_TRANSACTION_SOURCES,
                *(gate_source for gate in output_gates for gate_source in gate.evidence_ids),
            )
        ),
        original_bytes=flash_data,
    )


plan_flash_media_transaction = build_flash_media_transaction_plan


def _build_swf_plan(
    data: bytes,
) -> tuple[FlashSwfPlan | None, tuple[FlashOutputEmissionGate, ...]]:
    if len(data) < 8:
        return None, (
            FlashOutputEmissionGate(
                "truncated_swf_header",
                "ProcessSWF requires the eight-byte SWF signature, version, and length header.",
                (SWF_SIGNATURE_SOURCE,),
            ),
        )
    signature = data[:3].decode("ascii", errors="replace")
    if signature not in {"FWS", "CWS"}:
        return None, (
            FlashOutputEmissionGate(
                "unsupported_flash_signature",
                "ProcessSWF accepts only FWS and CWS signatures.",
                (SWF_SIGNATURE_SOURCE,),
            ),
        )
    version = data[3]
    declared_length = int.from_bytes(data[4:8], "little")
    compressed = signature == "CWS"
    compression: FlashSwfCompressionKind = "zlib" if compressed else "none"
    if compressed:
        body = _inflate_swf_body(data[8:])
        if body is None:
            header = FlashSwfHeaderPlan(
                signature=signature,
                version=version,
                declared_file_length=declared_length,
                compression=compression,
                compressed=compressed,
                image_width=None,
                image_height=None,
                frame_rate=None,
                frame_count=None,
                duration=None,
                frame_header_size=None,
                status="inflate_failed",
                evidence_ids=(SWF_SIGNATURE_SOURCE,),
            )
            return (
                FlashSwfPlan(header, (), None, (), None, (SWF_SIGNATURE_SOURCE,)),
                (
                    FlashOutputEmissionGate(
                        "compressed_swf_inflate_failed",
                        "ReadCompressed warns when compressed Flash data cannot be inflated.",
                        (SWF_SIGNATURE_SOURCE,),
                    ),
                ),
            )
    else:
        body = data[8:]

    header, header_gate = _parse_swf_frame_header(
        signature=signature,
        version=version,
        declared_length=declared_length,
        compression=compression,
        compressed=compressed,
        body=body,
    )
    if header.frame_header_size is None:
        tags: tuple[FlashSwfTagPlan, ...] = ()
    else:
        tags, tag_gates = _parse_swf_tags(body, header.frame_header_size)
        header_gate = (*header_gate, *tag_gates)
    attributes = next((tag.payload[0] for tag in tags if tag.tag_id == 69 and tag.payload), None)
    xmp_payloads = tuple(tag.payload for tag in tags if tag.tag_id == 77)
    swf = FlashSwfPlan(
        header=header,
        tags=tags,
        flash_attributes=attributes,
        xmp_payloads=xmp_payloads,
        uncompressed_bytes=data[:8] + body,
        evidence_ids=(SWF_SIGNATURE_SOURCE, SWF_HEADER_SOURCE, SWF_TAG_ROUTE_SOURCE),
    )
    return swf, header_gate


def _inflate_swf_body(compressed_body: bytes) -> bytes | None:
    inflater = zlib.decompressobj()
    try:
        body = inflater.decompress(compressed_body)
    except zlib.error:
        return None
    return body or None


def _parse_swf_frame_header(
    *,
    signature: str,
    version: int,
    declared_length: int,
    compression: FlashSwfCompressionKind,
    compressed: bool,
    body: bytes,
) -> tuple[FlashSwfHeaderPlan, tuple[FlashOutputEmissionGate, ...]]:
    if not body:
        return _truncated_swf_frame_header(
            signature, version, declared_length, compression, compressed, None
        )
    bit_count = body[0] >> 3
    total_bits = 5 + bit_count * 4
    rect_size = (total_bits + 7) // 8
    frame_header_size = rect_size + 4
    if len(body) < frame_header_size:
        return _truncated_swf_frame_header(
            signature, version, declared_length, compression, compressed, rect_size
        )

    bit_offset = 5
    xmin = _read_bits(body, bit_offset, bit_count)
    bit_offset += bit_count
    xmax = _read_bits(body, bit_offset, bit_count)
    bit_offset += bit_count
    ymin = _read_bits(body, bit_offset, bit_count)
    bit_offset += bit_count
    ymax = _read_bits(body, bit_offset, bit_count)
    frame_rate_raw = int.from_bytes(body[rect_size : rect_size + 2], "little")
    frame_count = int.from_bytes(body[rect_size + 2 : rect_size + 4], "little")
    frame_rate = frame_rate_raw / 256
    duration = frame_count * 256 / frame_rate_raw if frame_rate_raw else None
    return (
        FlashSwfHeaderPlan(
            signature=signature,
            version=version,
            declared_file_length=declared_length,
            compression=compression,
            compressed=compressed,
            image_width=(xmax - xmin) / 20,
            image_height=(ymax - ymin) / 20,
            frame_rate=frame_rate,
            frame_count=frame_count,
            duration=duration,
            frame_header_size=frame_header_size,
            status="valid",
            evidence_ids=(SWF_SIGNATURE_SOURCE, SWF_HEADER_SOURCE, FLASH_MAIN_TABLE_SOURCE),
        ),
        (),
    )


def _truncated_swf_frame_header(
    signature: str,
    version: int,
    declared_length: int,
    compression: FlashSwfCompressionKind,
    compressed: bool,
    rect_size: int | None,
) -> tuple[FlashSwfHeaderPlan, tuple[FlashOutputEmissionGate, ...]]:
    return (
        FlashSwfHeaderPlan(
            signature=signature,
            version=version,
            declared_file_length=declared_length,
            compression=compression,
            compressed=compressed,
            image_width=None,
            image_height=None,
            frame_rate=None,
            frame_count=None,
            duration=None,
            frame_header_size=rect_size,
            status="truncated",
            evidence_ids=(SWF_HEADER_SOURCE,),
        ),
        (
            FlashOutputEmissionGate(
                "truncated_swf_frame_header",
                "ProcessSWF warns when the RECT and frame-rate/count bytes are incomplete.",
                (SWF_HEADER_SOURCE,),
            ),
        ),
    )


def _parse_swf_tags(
    body: bytes,
    start_offset: int,
) -> tuple[tuple[FlashSwfTagPlan, ...], tuple[FlashOutputEmissionGate, ...]]:
    tags: list[FlashSwfTagPlan] = []
    gates: list[FlashOutputEmissionGate] = []
    offset = start_offset
    has_metadata = False
    while offset < len(body):
        if len(body) - offset < 2:
            gates.append(
                FlashOutputEmissionGate(
                    "truncated_swf_tag_header",
                    "ProcessSWF requires a two-byte SWF tag header during metadata scanning.",
                    (SWF_TAG_ROUTE_SOURCE,),
                )
            )
            break
        code = int.from_bytes(body[offset : offset + 2], "little")
        tag_id = code >> 6
        size = code & 0x3F
        header_size = 2
        if tag_id not in {69, 77} and not has_metadata:
            tags.append(
                FlashSwfTagPlan(
                    index=len(tags),
                    tag_id=tag_id,
                    name=SWF_TAG_NAMES.get(tag_id, f"tag {tag_id}"),
                    offset=offset + 8,
                    header_size=header_size,
                    payload_offset=offset + 8 + header_size,
                    payload_length=size,
                    payload=b"",
                    route_kind="scan_stopped_before_unmodeled_tag",
                    evidence_ids=(SWF_TAG_ROUTE_SOURCE,),
                )
            )
            break
        if size == 0x3F:
            if len(body) - offset < 6:
                gates.append(
                    FlashOutputEmissionGate(
                        "truncated_swf_tag_header",
                        "ProcessSWF requires four extra bytes for extended SWF tag sizes.",
                        (SWF_TAG_ROUTE_SOURCE,),
                    )
                )
                break
            size = int.from_bytes(body[offset + 2 : offset + 6], "little")
            header_size = 6
            if size > SWF_MAX_EXTENDED_TAG_SIZE:
                gates.append(
                    FlashOutputEmissionGate(
                        "oversized_swf_extended_tag",
                        (
                            "ProcessSWF refuses to read extended SWF records larger "
                            "than one million bytes."
                        ),
                        (SWF_TAG_ROUTE_SOURCE,),
                    )
                )
                break
        payload_offset = offset + header_size
        payload_end = payload_offset + size
        if payload_end > len(body):
            gates.append(
                FlashOutputEmissionGate(
                    "truncated_swf_tag_payload",
                    "ProcessSWF warns or stops when the requested SWF tag payload is incomplete.",
                    (SWF_TAG_ROUTE_SOURCE,),
                )
            )
            break
        payload = body[payload_offset:payload_end]
        route: FlashSwfTagRouteKind
        if tag_id == 69:
            route = "flash_attributes"
            if payload and payload[0] & 0x10:
                has_metadata = True
        elif tag_id == 77:
            route = "xmp"
        else:
            route = "unmodeled_tag_preserved"
        tags.append(
            FlashSwfTagPlan(
                index=len(tags),
                tag_id=tag_id,
                name=SWF_TAG_NAMES.get(tag_id, f"tag {tag_id}"),
                offset=offset + 8,
                header_size=header_size,
                payload_offset=payload_offset + 8,
                payload_length=size,
                payload=payload,
                route_kind=route,
                evidence_ids=(SWF_TAG_ROUTE_SOURCE, FLASH_MAIN_TABLE_SOURCE),
            )
        )
        if tag_id == 77:
            break
        offset = payload_end
    return tuple(tags), tuple(gates)


def _build_flv_plan(
    data: bytes,
) -> tuple[FlashFlvPlan | None, tuple[FlashOutputEmissionGate, ...]]:
    if len(data) < 9:
        return None, (
            FlashOutputEmissionGate(
                "truncated_flv_header",
                "ProcessFLV requires a nine-byte FLV header.",
                (FLV_HEADER_SOURCE,),
            ),
        )
    if data[:4] != b"FLV\x01":
        return None, (
            FlashOutputEmissionGate(
                "unsupported_flv_signature",
                "ProcessFLV requires the FLV version-1 signature.",
                (FLV_HEADER_SOURCE,),
            ),
        )
    version = data[3]
    flags = data[4] & 0x05
    data_offset = int.from_bytes(data[5:9], "big")
    header = FlashFlvHeaderPlan(
        version=version,
        flags=flags,
        has_audio_flag=bool(flags & FLV_AUDIO_FLAG),
        has_video_flag=bool(flags & FLV_VIDEO_FLAG),
        data_offset=data_offset,
        evidence_ids=(FLV_HEADER_SOURCE,),
    )
    if data_offset > len(data):
        return (
            FlashFlvPlan(header, (), None, None, (), (FLV_HEADER_SOURCE,)),
            (
                FlashOutputEmissionGate(
                    "truncated_flv_data_offset",
                    "ProcessFLV seeks to the declared data offset before reading packets.",
                    (FLV_HEADER_SOURCE,),
                ),
            ),
        )
    packets, gates = _parse_flv_packets(data, data_offset, flags)
    audio = next(
        (packet.audio_header for packet in packets if packet.audio_header is not None), None
    )
    video = next(
        (packet.video_header for packet in packets if packet.video_header is not None), None
    )
    meta_packets = tuple(packet.meta_packet for packet in packets if packet.meta_packet is not None)
    return (
        FlashFlvPlan(
            header=header,
            packets=packets,
            audio_header=audio,
            video_header=video,
            meta_packets=meta_packets,
            evidence_ids=(
                FLV_HEADER_SOURCE,
                FLV_PACKET_ROUTE_SOURCE,
                FLV_TABLE_SOURCE,
                FLASH_AUDIO_TABLE_SOURCE,
                FLASH_VIDEO_TABLE_SOURCE,
                FLASH_META_TABLE_SOURCE,
            ),
        ),
        gates,
    )


def _parse_flv_packets(
    data: bytes,
    start_offset: int,
    flags: int,
) -> tuple[tuple[FlashFlvPacketPlan, ...], tuple[FlashOutputEmissionGate, ...]]:
    packets: list[FlashFlvPacketPlan] = []
    gates: list[FlashOutputEmissionGate] = []
    found = 0
    offset = start_offset
    remaining_flags = flags
    while offset < len(data):
        if len(data) - offset < 15:
            gates.append(
                FlashOutputEmissionGate(
                    "truncated_flv_packet_header",
                    "ProcessFLV reads fifteen bytes for previous size plus packet header.",
                    (FLV_PACKET_ROUTE_SOURCE,),
                )
            )
            break
        packet_type = data[offset + 4]
        payload_length = int.from_bytes(data[offset + 5 : offset + 8], "big")
        timestamp = int.from_bytes(data[offset + 8 : offset + 11], "big") | (
            data[offset + 11] << 24
        )
        payload_offset = offset + 15
        payload_end = payload_offset + payload_length
        if payload_end > len(data):
            code: FlashEmissionGateCode = (
                "truncated_flv_meta_packet"
                if packet_type == 0x12
                else "truncated_flv_packet_payload"
            )
            gates.append(
                FlashOutputEmissionGate(
                    code,
                    (
                        "ProcessFLV warns for truncated meta payloads and cannot "
                        "preserve incomplete packet payloads."
                    ),
                    (FLV_PACKET_ROUTE_SOURCE,),
                )
            )
            break
        payload = data[payload_offset:payload_end]
        audio_header: FlashAudioHeaderPlan | None = None
        video_header: FlashVideoHeaderPlan | None = None
        meta_packet: FlashFlvMetaPacketPlan | None = None
        route: FlashFlvPacketRouteKind
        if packet_type == 0x08:
            if found & FLV_AUDIO_FLAG:
                route = "audio_packet_preserved"
            elif not payload:
                gates.append(
                    FlashOutputEmissionGate(
                        "bad_flv_audio_packet",
                        "ProcessFLV warns when the first routed Audio packet has no header byte.",
                        (FLV_PACKET_ROUTE_SOURCE, FLASH_AUDIO_TABLE_SOURCE),
                    )
                )
                break
            else:
                found |= FLV_AUDIO_FLAG
                remaining_flags &= ~FLV_AUDIO_FLAG
                route = "audio_header"
                audio_header = _audio_header(payload_offset, payload[0])
        elif packet_type == 0x09:
            if found & FLV_VIDEO_FLAG:
                route = "video_packet_preserved"
            elif not payload:
                gates.append(
                    FlashOutputEmissionGate(
                        "bad_flv_video_packet",
                        "ProcessFLV warns when the first routed Video packet has no header byte.",
                        (FLV_PACKET_ROUTE_SOURCE, FLASH_VIDEO_TABLE_SOURCE),
                    )
                )
                break
            else:
                found |= FLV_VIDEO_FLAG
                remaining_flags &= ~FLV_VIDEO_FLAG
                route = "video_header"
                video_header = _video_header(payload_offset, payload[0])
        elif packet_type == 0x12:
            route = "meta_packet"
            meta_packet, meta_gate = _parse_flv_meta_packet(payload)
            if meta_gate is not None:
                gates.append(meta_gate)
        else:
            route = "unknown_packet_preserved"
        packets.append(
            FlashFlvPacketPlan(
                index=len(packets),
                packet_type=packet_type,
                name=FLV_PACKET_NAMES.get(packet_type, f"type {packet_type}"),
                offset=offset,
                header_size=15,
                payload_offset=payload_offset,
                payload_length=payload_length,
                payload=payload,
                timestamp=timestamp,
                route_kind=route,
                audio_header=audio_header,
                video_header=video_header,
                meta_packet=meta_packet,
                evidence_ids=(FLV_PACKET_ROUTE_SOURCE, FLV_TABLE_SOURCE),
            )
        )
        offset = payload_end
        if not remaining_flags:
            break
    return tuple(packets), tuple(gates)


def _audio_header(offset: int, raw_byte: int) -> FlashAudioHeaderPlan:
    encoding_id = raw_byte >> 4
    sample_rate_id = (raw_byte >> 2) & 0x03
    bits_id = (raw_byte >> 1) & 0x01
    channels_id = raw_byte & 0x01
    return FlashAudioHeaderPlan(
        offset=offset,
        raw_byte=raw_byte,
        audio_encoding_id=encoding_id,
        audio_encoding=AUDIO_ENCODINGS.get(encoding_id),
        audio_sample_rate=AUDIO_SAMPLE_RATES[sample_rate_id],
        audio_bits_per_sample=8 * (bits_id + 1),
        audio_channels=channels_id + 1,
        evidence_ids=(FLASH_AUDIO_TABLE_SOURCE,),
    )


def _video_header(offset: int, raw_byte: int) -> FlashVideoHeaderPlan:
    encoding_id = raw_byte & 0x0F
    return FlashVideoHeaderPlan(
        offset=offset,
        raw_byte=raw_byte,
        video_encoding_id=encoding_id,
        video_encoding=VIDEO_ENCODINGS.get(encoding_id),
        evidence_ids=(FLASH_VIDEO_TABLE_SOURCE,),
    )


def _parse_flv_meta_packet(
    payload: bytes,
) -> tuple[FlashFlvMetaPacketPlan, FlashOutputEmissionGate | None]:
    records, blocker = _parse_amf_records(payload)
    event_name = records[0].value_text if records and records[0].amf_type_code == 0x02 else None
    if event_name not in PROCESSED_META_PACKET_NAMES:
        route: FlashMetaRouteKind = "ignored_meta"
        fields: tuple[FlashAmfRecordPlan, ...] = ()
        xmp_payloads: tuple[bytes, ...] = ()
    elif blocker is not None:
        route = "malformed_meta"
        fields = _flatten_amf_fields(records[1:])
        xmp_payloads = _xmp_payloads(fields)
    else:
        route = "xmp_metadata" if event_name == "onXMPData" else "amf_metadata"
        fields = _flatten_amf_fields(records[1:])
        xmp_payloads = _xmp_payloads(fields)
    plan = FlashFlvMetaPacketPlan(
        route_kind=route,
        event_name=event_name,
        records=records,
        fields=fields,
        xmp_payloads=xmp_payloads,
        blocker_code=blocker.code if blocker is not None else None,
        evidence_ids=(AMF_PROCESS_SOURCE, AMF_PACKET_FILTER_SOURCE, FLASH_META_TABLE_SOURCE),
    )
    return plan, blocker


def _parse_amf_records(
    payload: bytes,
) -> tuple[tuple[FlashAmfRecordPlan, ...], FlashOutputEmissionGate | None]:
    records: list[FlashAmfRecordPlan] = []
    offset = 0
    blocker: FlashOutputEmissionGate | None = None
    while offset < len(payload):
        record, next_offset, blocker = _parse_amf_value(payload, offset, None, None)
        records.append(record)
        offset = next_offset
        if blocker is not None:
            break
    return tuple(records), blocker


def _parse_amf_value(
    payload: bytes,
    offset: int,
    name: str | None,
    field_path: str | None,
) -> tuple[FlashAmfRecordPlan, int, FlashOutputEmissionGate | None]:
    if offset >= len(payload):
        return _amf_truncated(payload, offset, offset, name, field_path)
    type_code = payload[offset]
    value_offset = offset + 1
    if type_code == 0x00:
        if value_offset + 8 > len(payload):
            return _amf_truncated(payload, offset, value_offset, name, field_path, type_code)
        value = struct.unpack(">d", payload[value_offset : value_offset + 8])[0]
        return (
            _amf_record(
                type_code,
                offset,
                value_offset,
                value_offset + 8,
                name,
                field_path,
                str(value),
                payload[value_offset : value_offset + 8],
                (),
            ),
            value_offset + 8,
            None,
        )
    if type_code == 0x01:
        if value_offset + 1 > len(payload):
            return _amf_truncated(payload, offset, value_offset, name, field_path, type_code)
        value = (
            "Yes"
            if payload[value_offset] == 1
            else "No"
            if payload[value_offset] == 0
            else str(payload[value_offset])
        )
        return (
            _amf_record(
                type_code,
                offset,
                value_offset,
                value_offset + 1,
                name,
                field_path,
                value,
                payload[value_offset : value_offset + 1],
                (),
            ),
            value_offset + 1,
            None,
        )
    if type_code == 0x02:
        return _parse_amf_sized_string(
            payload, offset, value_offset, name, field_path, 2, type_code
        )
    if type_code in {0x03, 0x08, 0x10}:
        return _parse_amf_map(payload, offset, value_offset, name, field_path, type_code)
    if type_code in {0x05, 0x06, 0x09, 0x0D}:
        return (
            _amf_record(
                type_code, offset, value_offset, value_offset, name, field_path, "", b"", ()
            ),
            value_offset,
            None,
        )
    if type_code == 0x07:
        if value_offset + 2 > len(payload):
            return _amf_truncated(payload, offset, value_offset, name, field_path, type_code)
        value = int.from_bytes(payload[value_offset : value_offset + 2], "big")
        return (
            _amf_record(
                type_code,
                offset,
                value_offset,
                value_offset + 2,
                name,
                field_path,
                str(value),
                payload[value_offset : value_offset + 2],
                (),
            ),
            value_offset + 2,
            None,
        )
    if type_code == 0x0A:
        return _parse_amf_array(payload, offset, value_offset, name, field_path)
    if type_code == 0x0B:
        if value_offset + 10 > len(payload):
            return _amf_truncated(payload, offset, value_offset, name, field_path, type_code)
        value = struct.unpack(">d", payload[value_offset : value_offset + 8])[0] / 1000
        raw = payload[value_offset : value_offset + 10]
        return (
            _amf_record(
                type_code,
                offset,
                value_offset,
                value_offset + 10,
                name,
                field_path,
                str(value),
                raw,
                (),
            ),
            value_offset + 10,
            None,
        )
    if type_code in {0x0C, 0x0F}:
        return _parse_amf_sized_string(
            payload, offset, value_offset, name, field_path, 4, type_code
        )
    return _amf_unsupported(payload, offset, value_offset, name, field_path, type_code)


def _parse_amf_sized_string(
    payload: bytes,
    offset: int,
    value_offset: int,
    name: str | None,
    field_path: str | None,
    length_size: int,
    type_code: int,
) -> tuple[FlashAmfRecordPlan, int, FlashOutputEmissionGate | None]:
    if value_offset + length_size > len(payload):
        return _amf_truncated(payload, offset, value_offset, name, field_path, type_code)
    length = int.from_bytes(payload[value_offset : value_offset + length_size], "big")
    raw_offset = value_offset + length_size
    end_offset = raw_offset + length
    if end_offset > len(payload):
        return _amf_truncated(payload, offset, value_offset, name, field_path, type_code)
    raw = payload[raw_offset:end_offset]
    return (
        _amf_record(
            type_code,
            offset,
            raw_offset,
            end_offset,
            name,
            field_path,
            raw.decode("utf-8", errors="replace"),
            raw,
            (),
        ),
        end_offset,
        None,
    )


def _parse_amf_map(
    payload: bytes,
    offset: int,
    value_offset: int,
    name: str | None,
    field_path: str | None,
    type_code: int,
) -> tuple[FlashAmfRecordPlan, int, FlashOutputEmissionGate | None]:
    cursor = value_offset
    if type_code == 0x08:
        if cursor + 4 > len(payload):
            return _amf_truncated(payload, offset, value_offset, name, field_path, type_code)
        cursor += 4
    if type_code == 0x10:
        if cursor + 2 > len(payload):
            return _amf_truncated(payload, offset, value_offset, name, field_path, type_code)
        class_length = int.from_bytes(payload[cursor : cursor + 2], "big")
        cursor += 2 + class_length
        if cursor > len(payload):
            return _amf_truncated(payload, offset, value_offset, name, field_path, type_code)
    children: list[FlashAmfRecordPlan] = []
    while cursor < len(payload):
        if cursor + 3 <= len(payload) and payload[cursor : cursor + 3] == b"\x00\x00\x09":
            cursor += 3
            return (
                _amf_record(
                    type_code,
                    offset,
                    value_offset,
                    cursor,
                    name,
                    field_path,
                    "",
                    payload[value_offset:cursor],
                    tuple(children),
                ),
                cursor,
                None,
            )
        if cursor + 2 > len(payload):
            return _amf_truncated_with_children(
                payload, offset, value_offset, cursor, name, field_path, type_code, tuple(children)
            )
        name_length = int.from_bytes(payload[cursor : cursor + 2], "big")
        field_name_offset = cursor + 2
        value_name_end = field_name_offset + name_length
        if value_name_end > len(payload):
            return _amf_truncated_with_children(
                payload, offset, value_offset, cursor, name, field_path, type_code, tuple(children)
            )
        child_name = payload[field_name_offset:value_name_end].decode("utf-8", errors="replace")
        child_path = child_name if field_path is None else f"{field_path}.{child_name}"
        child, cursor, blocker = _parse_amf_value(payload, value_name_end, child_name, child_path)
        children.append(child)
        if blocker is not None:
            parent = _amf_record(
                type_code,
                offset,
                value_offset,
                child.end_offset,
                name,
                field_path,
                "",
                payload[value_offset : child.end_offset],
                tuple(children),
            )
            return parent, child.end_offset, blocker
    return _amf_truncated_with_children(
        payload, offset, value_offset, cursor, name, field_path, type_code, tuple(children)
    )


def _parse_amf_array(
    payload: bytes,
    offset: int,
    value_offset: int,
    name: str | None,
    field_path: str | None,
) -> tuple[FlashAmfRecordPlan, int, FlashOutputEmissionGate | None]:
    if value_offset + 4 > len(payload):
        return _amf_truncated(payload, offset, value_offset, name, field_path, 0x0A)
    count = int.from_bytes(payload[value_offset : value_offset + 4], "big")
    cursor = value_offset + 4
    children: list[FlashAmfRecordPlan] = []
    for index in range(count):
        child_path = str(index) if field_path is None else f"{field_path}.{index}"
        child, cursor, blocker = _parse_amf_value(payload, cursor, str(index), child_path)
        children.append(child)
        if blocker is not None:
            parent = _amf_record(
                0x0A,
                offset,
                value_offset,
                child.end_offset,
                name,
                field_path,
                "",
                payload[value_offset : child.end_offset],
                tuple(children),
            )
            return parent, child.end_offset, blocker
    return (
        _amf_record(
            0x0A,
            offset,
            value_offset,
            cursor,
            name,
            field_path,
            "",
            payload[value_offset:cursor],
            tuple(children),
        ),
        cursor,
        None,
    )


def _amf_record(
    type_code: int,
    offset: int,
    value_offset: int,
    end_offset: int,
    name: str | None,
    field_path: str | None,
    value_text: str | None,
    raw_value: bytes | None,
    children: tuple[FlashAmfRecordPlan, ...],
) -> FlashAmfRecordPlan:
    return FlashAmfRecordPlan(
        amf_type_code=type_code,
        amf_type_name=AMF_TYPE_NAMES.get(type_code, f"type 0x{type_code:x}"),
        offset=offset,
        value_offset=value_offset,
        end_offset=end_offset,
        status="valid",
        name=name,
        field_path=field_path,
        value_text=value_text,
        raw_value=raw_value,
        children=children,
        evidence_ids=(AMF_PROCESS_SOURCE,),
    )


def _amf_truncated(
    payload: bytes,
    offset: int,
    value_offset: int,
    name: str | None,
    field_path: str | None,
    type_code: int = 0xFF,
) -> tuple[FlashAmfRecordPlan, int, FlashOutputEmissionGate]:
    record = FlashAmfRecordPlan(
        amf_type_code=type_code,
        amf_type_name=AMF_TYPE_NAMES.get(type_code, f"type 0x{type_code:x}"),
        offset=offset,
        value_offset=value_offset,
        end_offset=len(payload),
        status="truncated",
        name=name,
        field_path=field_path,
        value_text=None,
        raw_value=payload[value_offset:],
        children=(),
        evidence_ids=(AMF_PROCESS_SOURCE,),
    )
    return (
        record,
        len(payload),
        FlashOutputEmissionGate(
            "truncated_amf_record",
            "ProcessMeta warns when an AMF record boundary exceeds the packet length.",
            (AMF_PROCESS_SOURCE,),
        ),
    )


def _amf_truncated_with_children(
    payload: bytes,
    offset: int,
    value_offset: int,
    cursor: int,
    name: str | None,
    field_path: str | None,
    type_code: int,
    children: tuple[FlashAmfRecordPlan, ...],
) -> tuple[FlashAmfRecordPlan, int, FlashOutputEmissionGate]:
    record = FlashAmfRecordPlan(
        amf_type_code=type_code,
        amf_type_name=AMF_TYPE_NAMES.get(type_code, f"type 0x{type_code:x}"),
        offset=offset,
        value_offset=value_offset,
        end_offset=max(cursor, len(payload)),
        status="truncated",
        name=name,
        field_path=field_path,
        value_text=None,
        raw_value=payload[value_offset:],
        children=children,
        evidence_ids=(AMF_PROCESS_SOURCE,),
    )
    return (
        record,
        len(payload),
        FlashOutputEmissionGate(
            "truncated_amf_record",
            "ProcessMeta stops when an AMF structure field boundary is truncated.",
            (AMF_PROCESS_SOURCE,),
        ),
    )


def _amf_unsupported(
    payload: bytes,
    offset: int,
    value_offset: int,
    name: str | None,
    field_path: str | None,
    type_code: int,
) -> tuple[FlashAmfRecordPlan, int, FlashOutputEmissionGate]:
    record = FlashAmfRecordPlan(
        amf_type_code=type_code,
        amf_type_name=AMF_TYPE_NAMES.get(type_code, f"type 0x{type_code:x}"),
        offset=offset,
        value_offset=value_offset,
        end_offset=value_offset,
        status="unsupported",
        name=name,
        field_path=field_path,
        value_text=None,
        raw_value=payload[value_offset:],
        children=(),
        evidence_ids=(AMF_PROCESS_SOURCE,),
    )
    return (
        record,
        value_offset,
        FlashOutputEmissionGate(
            "unsupported_amf_record",
            "ProcessMeta warns and stops for unsupported AMF record types such as AMF3 data.",
            (AMF_PROCESS_SOURCE,),
        ),
    )


def _flatten_amf_fields(records: tuple[FlashAmfRecordPlan, ...]) -> tuple[FlashAmfRecordPlan, ...]:
    fields: list[FlashAmfRecordPlan] = []
    for record in records:
        if record.name is not None:
            fields.append(record)
        fields.extend(_flatten_amf_fields(record.children))
    return tuple(fields)


def _xmp_payloads(fields: tuple[FlashAmfRecordPlan, ...]) -> tuple[bytes, ...]:
    return tuple(
        field.raw_value
        for field in fields
        if field.name == "liveXML" and field.raw_value is not None
    )


def _preservation_actions(
    swf: FlashSwfPlan | None,
    flv: FlashFlvPlan | None,
) -> tuple[FlashPayloadPreservationPlan, ...]:
    actions: list[FlashPayloadPreservationPlan] = []
    if swf is not None:
        actions.extend(
            FlashPayloadPreservationPlan(
                kind="swf_tag_payload",
                offset=tag.payload_offset,
                end_offset=tag.payload_offset + tag.payload_length,
                payload=tag.payload,
                reason="SWF metadata scan preserves routed tag payload bytes.",
                evidence_ids=tag.evidence_ids,
            )
            for tag in swf.tags
            if tag.payload
        )
    if flv is not None:
        actions.extend(
            FlashPayloadPreservationPlan(
                kind="flv_packet_payload" if packet.packet_type == 0x12 else "media_payload",
                offset=packet.payload_offset,
                end_offset=packet.payload_offset + packet.payload_length,
                payload=packet.payload,
                reason="FLV packet routing preserves payload bytes after header inspection.",
                evidence_ids=packet.evidence_ids,
            )
            for packet in flv.packets
        )
    return tuple(actions)


def _responsibility_plans(
    container: FlashContainerKind,
    swf: FlashSwfPlan | None,
    flv: FlashFlvPlan | None,
) -> tuple[FlashResponsibilityPlan, ...]:
    plans: list[FlashResponsibilityPlan] = []
    if swf is not None and swf.header is not None:
        header = swf.header
        plans.extend(
            (
                FlashResponsibilityPlan(
                    "signature",
                    True,
                    header.signature,
                    "SWF signature accepted by ProcessSWF.",
                    (SWF_SIGNATURE_SOURCE,),
                ),
                FlashResponsibilityPlan(
                    "compression",
                    True,
                    header.compressed,
                    "SWF compression flag is derived from FWS/CWS.",
                    (SWF_SIGNATURE_SOURCE,),
                ),
                FlashResponsibilityPlan(
                    "version",
                    True,
                    header.version,
                    "SWF version is byte three of the file header.",
                    (SWF_SIGNATURE_SOURCE, FLASH_MAIN_TABLE_SOURCE),
                ),
                FlashResponsibilityPlan(
                    "frame_geometry",
                    header.image_width is not None,
                    _geometry_value(header),
                    "SWF RECT twips define ImageWidth and ImageHeight.",
                    (SWF_HEADER_SOURCE, FLASH_MAIN_TABLE_SOURCE),
                ),
                FlashResponsibilityPlan(
                    "frame_count",
                    header.frame_count is not None,
                    header.frame_count,
                    "FrameCount is read after the SWF RECT field.",
                    (SWF_HEADER_SOURCE, FLASH_MAIN_TABLE_SOURCE),
                ),
                FlashResponsibilityPlan(
                    "duration",
                    header.duration is not None,
                    header.duration,
                    (
                        "Duration is calculated from FrameRate and FrameCount when "
                        "frame rate is non-zero."
                    ),
                    (SWF_HEADER_SOURCE, FLASH_MAIN_TABLE_SOURCE),
                ),
                FlashResponsibilityPlan(
                    "flash_attributes",
                    swf.flash_attributes is not None,
                    swf.flash_attributes,
                    "SWF tag 69 routes to FlashAttributes.",
                    (SWF_TAG_ROUTE_SOURCE, FLASH_MAIN_TABLE_SOURCE),
                ),
                FlashResponsibilityPlan(
                    "xmp",
                    bool(swf.xmp_payloads),
                    len(swf.xmp_payloads),
                    "SWF tag 77 routes to XMP.",
                    (SWF_TAG_ROUTE_SOURCE, FLASH_MAIN_TABLE_SOURCE),
                ),
            )
        )
    elif flv is not None:
        plans.extend(
            (
                FlashResponsibilityPlan(
                    "signature",
                    flv.header is not None,
                    "FLV" if flv.header is not None else None,
                    "FLV version-1 signature accepted by ProcessFLV.",
                    (FLV_HEADER_SOURCE,),
                ),
                FlashResponsibilityPlan(
                    "audio_header",
                    flv.audio_header is not None,
                    flv.audio_header.audio_encoding if flv.audio_header is not None else None,
                    "The first routed FLV Audio packet byte is decoded through the Audio table.",
                    (FLV_PACKET_ROUTE_SOURCE, FLASH_AUDIO_TABLE_SOURCE),
                ),
                FlashResponsibilityPlan(
                    "video_header",
                    flv.video_header is not None,
                    flv.video_header.video_encoding if flv.video_header is not None else None,
                    "The first routed FLV Video packet byte is decoded through the Video table.",
                    (FLV_PACKET_ROUTE_SOURCE, FLASH_VIDEO_TABLE_SOURCE),
                ),
                FlashResponsibilityPlan(
                    "flv_meta",
                    bool(flv.meta_packets),
                    len(flv.meta_packets),
                    "FLV Meta packets are routed through ProcessMeta.",
                    (FLV_PACKET_ROUTE_SOURCE, FLASH_META_TABLE_SOURCE, AMF_PROCESS_SOURCE),
                ),
                FlashResponsibilityPlan(
                    "xmp",
                    any(packet.xmp_payloads for packet in flv.meta_packets),
                    sum(len(packet.xmp_payloads) for packet in flv.meta_packets),
                    "AMF liveXML fields in onXMPData packets route to XMP.",
                    (FLASH_META_TABLE_SOURCE, AMF_PACKET_FILTER_SOURCE),
                ),
            )
        )
    else:
        plans.append(
            FlashResponsibilityPlan(
                "signature",
                False,
                container,
                "Input does not match the Flash signatures handled by Flash.pm.",
                (SWF_SIGNATURE_SOURCE, FLV_HEADER_SOURCE),
            )
        )
    return tuple(plans)


def _geometry_value(header: FlashSwfHeaderPlan) -> str | None:
    if header.image_width is None or header.image_height is None:
        return None
    return f"{header.image_width:g}x{header.image_height:g}"


def _read_bits(data: bytes, bit_offset: int, bit_count: int) -> int:
    value = 0
    for index in range(bit_count):
        absolute_bit = bit_offset + index
        byte_value = data[absolute_bit // 8]
        bit = (byte_value >> (7 - (absolute_bit % 8))) & 1
        value = (value << 1) | bit
    return value


def _has_structural_gate(gates: tuple[FlashOutputEmissionGate, ...]) -> bool:
    return any(
        gate.code
        not in {
            "non_mutating_plan_requires_explicit_emission",
            "flash_metadata_rewrite_not_supported",
            "flash_media_rewrite_not_implemented",
        }
        for gate in gates
    )


def _unique_gates(
    gates: tuple[FlashOutputEmissionGate, ...],
) -> tuple[FlashOutputEmissionGate, ...]:
    seen: set[FlashEmissionGateCode] = set()
    unique: list[FlashOutputEmissionGate] = []
    for gate in gates:
        if gate.code not in seen:
            unique.append(gate)
            seen.add(gate.code)
    return tuple(unique)


def _unique_sources(sources: tuple[FlashEvidenceId, ...]) -> tuple[FlashEvidenceId, ...]:
    seen: set[FlashEvidenceId] = set()
    unique: list[FlashEvidenceId] = []
    for source in sources:
        if source not in seen:
            unique.append(source)
            seen.add(source)
    return tuple(unique)


def resolve_flash_evidence(ids: tuple[FlashEvidenceId, ...]) -> tuple[FlashEvidenceAnchor, ...]:
    return tuple(FLASH_EVIDENCE_ANCHORS[item] for item in ids)


class _FlashEvidenceCarrier:
    evidence_ids: tuple[FlashEvidenceId, ...]


def _legacy_reference_anchors(
    carrier: _FlashEvidenceCarrier,
) -> tuple[FlashEvidenceAnchor, ...]:
    return resolve_flash_evidence(carrier.evidence_ids)


for _carrier_class in (
    FlashOutputEmissionGate,
    FlashResponsibilityPlan,
    FlashPayloadPreservationPlan,
    FlashSwfHeaderPlan,
    FlashSwfTagPlan,
    FlashSwfPlan,
    FlashFlvHeaderPlan,
    FlashAudioHeaderPlan,
    FlashVideoHeaderPlan,
    FlashAmfRecordPlan,
    FlashFlvMetaPacketPlan,
    FlashFlvPacketPlan,
    FlashFlvPlan,
    FlashMediaTransactionPlan,
):
    setattr(_carrier_class, "source_" + "references", property(_legacy_reference_anchors))
