"""Source-grounded, non-mutating FLIF image metadata transaction plans.

ExifTool's FLIF module validates the FLIF signature/header, decodes FLIF
variable-length dimensions, walks compressed metadata chunks until the first
image-stream marker byte, and preserves the remaining image data.  This module
models those responsibilities without mutating bytes.
"""

from __future__ import annotations

import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

FLIF_SIGNATURE = b"FLIF"
FLIF_FIXED_HEADER_SIZE = 6
FLIF_CHUNK_TAG_SIZE = 4

type FlifPlanStatus = Literal["planned", "unsupported"]
type FlifColorModel = Literal["grayscale", "rgb", "rgba", "unknown"]
type FlifMetadataKind = Literal["EXIF", "XMP", "ICC_Profile"]
type FlifActionKind = Literal[
    "validate_header",
    "extract_image_header_fields",
    "enumerate_metadata_chunk",
    "inflate_metadata_chunk",
    "preserve_metadata_chunk",
    "preserve_unknown_chunk",
    "preserve_image_stream",
]
type FlifEmissionGateCode = Literal[
    "truncated_flif_header",
    "unsupported_flif_signature",
    "unsupported_flif_header_type",
    "unsupported_flif_bit_depth",
    "truncated_flif_header_varint",
    "truncated_flif_chunk_header",
    "truncated_flif_chunk_size",
    "truncated_flif_chunk_payload",
    "missing_flif_image_stream",
    "non_mutating_plan_requires_explicit_emission",
]
type FlifRewriteBlockerCode = Literal[
    "flif_metadata_rewrite_not_implemented",
    "compressed_metadata_requires_raw_inflate_deflate",
    "metadata_inflate_failed",
    "malformed_or_truncated_input",
]


FLIF_MAP_EVIDENCE_ID = "flif.map"
FLIF_MAP_SOURCE = FLIF_MAP_EVIDENCE_ID
FLIF_TAG_TABLE_EVIDENCE_ID = "flif.tag_table"
FLIF_TAG_TABLE_SOURCE = FLIF_TAG_TABLE_EVIDENCE_ID
FLIF_VARINT_EVIDENCE_ID = "flif.varint"
FLIF_VARINT_SOURCE = FLIF_VARINT_EVIDENCE_ID
FLIF_HEADER_EVIDENCE_ID = "flif.header"
FLIF_HEADER_SOURCE = FLIF_HEADER_EVIDENCE_ID
FLIF_WRITE_LOOP_EVIDENCE_ID = "flif.write_loop"
FLIF_WRITE_LOOP_SOURCE = FLIF_WRITE_LOOP_EVIDENCE_ID
FLIF_PROCESS_LOOP_EVIDENCE_ID = "flif.process_loop"
FLIF_PROCESS_LOOP_SOURCE = FLIF_PROCESS_LOOP_EVIDENCE_ID

FLIF_TRANSACTION_EVIDENCE_IDS = (
    FLIF_MAP_EVIDENCE_ID,
    FLIF_TAG_TABLE_EVIDENCE_ID,
    FLIF_VARINT_EVIDENCE_ID,
    FLIF_HEADER_EVIDENCE_ID,
    FLIF_WRITE_LOOP_EVIDENCE_ID,
    FLIF_PROCESS_LOOP_EVIDENCE_ID,
)

IMAGE_TYPE_DESCRIPTIONS: dict[str, str] = {
    "1": "Grayscale (non-interlaced)",
    "3": "RGB (non-interlaced)",
    "4": "RGBA (non-interlaced)",
    "A": "Grayscale (interlaced)",
    "C": "RGB (interlaced)",
    "D": "RGBA (interlaced)",
    "Q": "Grayscale Animation (non-interlaced)",
    "S": "RGB Animation (non-interlaced)",
    "T": "RGBA Animation (non-interlaced)",
    "a": "Grayscale Animation (interlaced)",
    "c": "RGB Animation (interlaced)",
    "d": "RGBA Animation (interlaced)",
}
BIT_DEPTHS: dict[str, int | None] = {"0": None, "1": 8, "2": 16}
METADATA_KINDS: dict[bytes, FlifMetadataKind] = {
    b"eXif": "EXIF",
    b"eXmp": "XMP",
    b"iCCP": "ICC_Profile",
}
METADATA_TAG_TABLES: dict[FlifMetadataKind, str] = {
    "EXIF": "Image::ExifTool::Exif::Main",
    "XMP": "Image::ExifTool::XMP::Main",
    "ICC_Profile": "Image::ExifTool::ICC_Profile::Main",
}


@dataclass(frozen=True)
class FlifHeaderPlan:
    signature: bytes
    image_type_code: str | None
    image_type_description: str | None
    bit_depth_code: str | None
    bit_depth: int | None
    is_custom_bit_depth: bool
    image_width: int | None
    image_height: int | None
    animation_frames: int | None
    animated: bool | None
    interlaced: bool | None
    color_model: FlifColorModel
    channel_count: int | None
    header_byte_length: int | None
    is_valid: bool
    reason: FlifEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "animated": self.animated,
            "animation_frames": self.animation_frames,
            "bit_depth": self.bit_depth,
            "bit_depth_code": self.bit_depth_code,
            "channel_count": self.channel_count,
            "color_model": self.color_model,
            "header_byte_length": self.header_byte_length,
            "image_height": self.image_height,
            "image_type_code": self.image_type_code,
            "image_type_description": self.image_type_description,
            "image_width": self.image_width,
            "interlaced": self.interlaced,
            "is_custom_bit_depth": self.is_custom_bit_depth,
            "is_valid": self.is_valid,
            "reason": self.reason,
            "signature": self.signature.hex(),
        }


@dataclass(frozen=True)
class FlifMetadataResponsibilityPlan:
    tag: bytes
    metadata_kind: FlifMetadataKind
    directory_name: str
    tag_table: str
    process_proc: str | None
    write_proc: str | None
    exif_header_skip: int | None
    exif_header: bytes | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "directory_name": self.directory_name,
            "exif_header": None if self.exif_header is None else self.exif_header.hex(),
            "exif_header_skip": self.exif_header_skip,
            "metadata_kind": self.metadata_kind,
            "process_proc": self.process_proc,
            "tag": ascii_bytes(self.tag),
            "tag_table": self.tag_table,
            "write_proc": self.write_proc,
        }


@dataclass(frozen=True)
class FlifMetadataChunkPlan:
    index: int
    tag: bytes
    chunk_start_offset: int
    size_offset: int
    payload_offset: int | None
    compressed_size: int | None
    chunk_end_offset: int | None
    metadata_kind: FlifMetadataKind | None
    responsibility: FlifMetadataResponsibilityPlan | None
    inflated_size: int | None
    inflate_succeeded: bool | None
    evidence_ids: tuple[str, ...]

    @property
    def is_known_metadata(self) -> bool:
        return self.metadata_kind is not None

    def to_json(self) -> JsonObject:
        return {
            "chunk_end_offset": self.chunk_end_offset,
            "chunk_start_offset": self.chunk_start_offset,
            "compressed_size": self.compressed_size,
            "index": self.index,
            "inflate_succeeded": self.inflate_succeeded,
            "inflated_size": self.inflated_size,
            "is_known_metadata": self.is_known_metadata,
            "metadata_kind": self.metadata_kind,
            "payload_offset": self.payload_offset,
            "responsibility": (
                None if self.responsibility is None else self.responsibility.to_json()
            ),
            "size_offset": self.size_offset,
            "tag": ascii_bytes(self.tag),
        }


@dataclass(frozen=True)
class FlifImageStreamPlan:
    start_offset: int | None
    sentinel: bytes | None
    encoding_byte: int | None
    encoding_name: str | None
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[str, ...]

    @property
    def preserved_size(self) -> int:
        if self.byte_range is None:
            return 0
        start, end = self.byte_range
        return end - start

    def to_json(self) -> JsonObject:
        return {
            "byte_range": json_range(self.byte_range),
            "encoding_byte": self.encoding_byte,
            "encoding_name": self.encoding_name,
            "preserved_size": self.preserved_size,
            "sentinel": None if self.sentinel is None else self.sentinel.hex(),
            "start_offset": self.start_offset,
        }


@dataclass(frozen=True)
class FlifActionPlan:
    kind: FlifActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": json_range(self.byte_range),
            "kind": self.kind,
            "reason": self.reason,
            "target": self.target,
        }


@dataclass(frozen=True)
class FlifRewriteBlocker:
    code: FlifRewriteBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FlifOutputEmissionGate:
    code: FlifEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FlifImageTransactionPlan:
    status: FlifPlanStatus
    source_data: bytes
    header: FlifHeaderPlan
    metadata_chunks: tuple[FlifMetadataChunkPlan, ...]
    metadata_responsibilities: tuple[FlifMetadataResponsibilityPlan, ...]
    image_stream: FlifImageStreamPlan
    actions: tuple[FlifActionPlan, ...]
    rewrite_blockers: tuple[FlifRewriteBlocker, ...]
    output_emission_gates: tuple[FlifOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def can_rewrite_metadata(self) -> bool:
        return self.status == "planned" and not self.rewrite_blockers

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"FLIF image transaction output is gated: {gate_codes}")
        return self.source_data

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "can_rewrite_metadata": self.can_rewrite_metadata,
            "header": self.header.to_json(),
            "image_stream": self.image_stream.to_json(),
            "metadata_chunks": json_object_array(chunk.to_json() for chunk in self.metadata_chunks),
            "metadata_responsibilities": json_object_array(
                responsibility.to_json() for responsibility in self.metadata_responsibilities
            ),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "rewrite_blockers": json_object_array(
                blocker.to_json() for blocker in self.rewrite_blockers
            ),
            "status": self.status,
        }


@dataclass(frozen=True)
class _VarIntResult:
    value: int | None
    start_offset: int
    end_offset: int
    reason: FlifEmissionGateCode | None


@dataclass(frozen=True)
class _EnumerationResult:
    chunks: tuple[FlifMetadataChunkPlan, ...]
    image_stream: FlifImageStreamPlan
    gates: tuple[FlifOutputEmissionGate, ...]
    blockers: tuple[FlifRewriteBlocker, ...]


def build_flif_image_transaction_plan(
    flif_data: bytes,
    *,
    allow_output_emission: bool = False,
) -> FlifImageTransactionPlan:
    """Build a non-mutating FLIF metadata transaction plan from in-memory bytes."""

    gates: list[FlifOutputEmissionGate] = []
    header = build_flif_header_plan(flif_data)
    validation_end = header.header_byte_length or min(len(flif_data), FLIF_FIXED_HEADER_SIZE)
    actions = [
        FlifActionPlan(
            kind="validate_header",
            target="FLIF header",
            byte_range=(0, validation_end),
            reason="Validate ExifTool's FLIF signature, type, depth, and variable fields.",
            evidence_ids=(FLIF_HEADER_EVIDENCE_ID, FLIF_VARINT_EVIDENCE_ID),
        )
    ]
    if header.reason is not None:
        gates.append(
            FlifOutputEmissionGate(
                code=header.reason,
                reason="Input does not satisfy ExifTool's FLIF header gate.",
                evidence_ids=header.evidence_ids,
            )
        )
        _add_non_mutating_gate(gates, allow_output_emission)
        return _build_plan(
            flif_data,
            "unsupported",
            header,
            (),
            FlifImageStreamPlan(None, None, None, None, None, (FLIF_PROCESS_LOOP_EVIDENCE_ID,)),
            tuple(actions),
            (malformed_blocker(),),
            tuple(gates),
        )

    actions.append(
        FlifActionPlan(
            kind="extract_image_header_fields",
            target="ImageType/BitDepth/ImageWidth/ImageHeight/AnimationFrames",
            byte_range=(0, header.header_byte_length or FLIF_FIXED_HEADER_SIZE),
            reason="Expose FLIF header fields with the same tag responsibilities as ExifTool.",
            evidence_ids=(FLIF_TAG_TABLE_EVIDENCE_ID, FLIF_HEADER_EVIDENCE_ID),
        )
    )
    enumeration = enumerate_flif_chunks(flif_data, header.header_byte_length or 0)
    gates.extend(enumeration.gates)
    _add_non_mutating_gate(gates, allow_output_emission)
    actions.extend(actions_for_chunks(enumeration.chunks, enumeration.image_stream))
    status: FlifPlanStatus = "unsupported" if structural_gate_present(gates) else "planned"
    malformed_blockers = (malformed_blocker(),) if status == "unsupported" else ()
    blockers = unique_blockers((*enumeration.blockers, *malformed_blockers))
    return _build_plan(
        flif_data,
        status,
        header,
        enumeration.chunks,
        enumeration.image_stream,
        tuple(actions),
        blockers,
        tuple(gates),
    )


plan_flif_image_transaction = build_flif_image_transaction_plan


def build_flif_header_plan(flif_data: bytes) -> FlifHeaderPlan:
    signature = flif_data[:4]
    if len(flif_data) < FLIF_FIXED_HEADER_SIZE:
        return invalid_header(
            signature=signature,
            reason="truncated_flif_header",
            evidence_ids=(FLIF_HEADER_EVIDENCE_ID,),
        )
    if signature != FLIF_SIGNATURE:
        return invalid_header(
            signature=signature,
            reason="unsupported_flif_signature",
            evidence_ids=(FLIF_HEADER_EVIDENCE_ID,),
        )

    image_type_byte = flif_data[4]
    bit_depth_byte = flif_data[5]
    if not 0x30 <= image_type_byte <= 0x6F:
        return invalid_header(
            signature=signature,
            image_type_code=chr(image_type_byte),
            bit_depth_code=chr(bit_depth_byte),
            reason="unsupported_flif_header_type",
            evidence_ids=(FLIF_HEADER_EVIDENCE_ID, FLIF_TAG_TABLE_EVIDENCE_ID),
        )
    if bit_depth_byte not in {0x30, 0x31, 0x32}:
        return invalid_header(
            signature=signature,
            image_type_code=chr(image_type_byte),
            bit_depth_code=chr(bit_depth_byte),
            reason="unsupported_flif_bit_depth",
            evidence_ids=(FLIF_HEADER_EVIDENCE_ID, FLIF_TAG_TABLE_EVIDENCE_ID),
        )

    offset = FLIF_FIXED_HEADER_SIZE
    width = read_flif_varint(flif_data, offset, add=1)
    if width.value is None:
        return invalid_header_with_codes(
            signature,
            chr(image_type_byte),
            chr(bit_depth_byte),
            "truncated_flif_header_varint",
            width.end_offset,
        )
    height = read_flif_varint(flif_data, width.end_offset, add=1)
    if height.value is None:
        return invalid_header_with_codes(
            signature,
            chr(image_type_byte),
            chr(bit_depth_byte),
            "truncated_flif_header_varint",
            height.end_offset,
        )
    animated = image_type_byte > ord("H")
    frames: int | None = None
    end_offset = height.end_offset
    if animated:
        frame_result = read_flif_varint(flif_data, height.end_offset, add=2)
        if frame_result.value is None:
            return invalid_header_with_codes(
                signature,
                chr(image_type_byte),
                chr(bit_depth_byte),
                "truncated_flif_header_varint",
                frame_result.end_offset,
            )
        frames = frame_result.value
        end_offset = frame_result.end_offset

    image_type = chr(image_type_byte)
    bit_depth_code = chr(bit_depth_byte)
    color_model = color_model_for_image_type(image_type)
    return FlifHeaderPlan(
        signature=signature,
        image_type_code=image_type,
        image_type_description=IMAGE_TYPE_DESCRIPTIONS.get(image_type),
        bit_depth_code=bit_depth_code,
        bit_depth=BIT_DEPTHS[bit_depth_code],
        is_custom_bit_depth=bit_depth_code == "0",
        image_width=width.value,
        image_height=height.value,
        animation_frames=frames,
        animated=animated,
        interlaced=image_type in {"A", "C", "D", "a", "c", "d"},
        color_model=color_model,
        channel_count=channel_count_for_color_model(color_model),
        header_byte_length=end_offset,
        is_valid=True,
        reason=None,
        evidence_ids=(FLIF_HEADER_EVIDENCE_ID, FLIF_VARINT_EVIDENCE_ID, FLIF_TAG_TABLE_EVIDENCE_ID),
    )


def enumerate_flif_chunks(flif_data: bytes, offset: int) -> _EnumerationResult:
    chunks: list[FlifMetadataChunkPlan] = []
    gates: list[FlifOutputEmissionGate] = []
    blockers: list[FlifRewriteBlocker] = []
    while offset + FLIF_CHUNK_TAG_SIZE <= len(flif_data):
        chunk_start = offset
        tag = flif_data[offset : offset + FLIF_CHUNK_TAG_SIZE]
        if tag[0] < 32:
            image_stream = FlifImageStreamPlan(
                start_offset=chunk_start,
                sentinel=tag,
                encoding_byte=tag[0],
                encoding_name="FLIF16" if tag[0] == 0 else None,
                byte_range=(chunk_start, len(flif_data)),
                evidence_ids=(FLIF_PROCESS_LOOP_EVIDENCE_ID, FLIF_WRITE_LOOP_EVIDENCE_ID),
            )
            return _EnumerationResult(
                tuple(chunks),
                image_stream,
                tuple(gates),
                unique_blockers(tuple(blockers)),
            )

        size = read_flif_varint(flif_data, offset + FLIF_CHUNK_TAG_SIZE)
        if size.value is None:
            gates.append(
                FlifOutputEmissionGate(
                    code="truncated_flif_chunk_size",
                    reason=f"Chunk {ascii_bytes(tag)} ended before its FLIF size integer.",
                    evidence_ids=(FLIF_PROCESS_LOOP_EVIDENCE_ID, FLIF_VARINT_EVIDENCE_ID),
                )
            )
            break
        payload_offset = size.end_offset
        payload_end = payload_offset + size.value
        if payload_end > len(flif_data):
            gates.append(
                FlifOutputEmissionGate(
                    code="truncated_flif_chunk_payload",
                    reason=f"Chunk {ascii_bytes(tag)} declares {size.value} payload bytes.",
                    evidence_ids=(FLIF_PROCESS_LOOP_EVIDENCE_ID,),
                )
            )
            chunks.append(
                build_chunk_plan(
                    len(chunks),
                    tag,
                    chunk_start,
                    offset + FLIF_CHUNK_TAG_SIZE,
                    payload_offset,
                    size.value,
                    None,
                    flif_data[payload_offset:],
                    blockers,
                )
            )
            break
        chunks.append(
            build_chunk_plan(
                len(chunks),
                tag,
                chunk_start,
                offset + FLIF_CHUNK_TAG_SIZE,
                payload_offset,
                size.value,
                payload_end,
                flif_data[payload_offset:payload_end],
                blockers,
            )
        )
        offset = payload_end

    if not gates:
        if offset == len(flif_data):
            gates.append(
                FlifOutputEmissionGate(
                    code="missing_flif_image_stream",
                    reason="Metadata chunk enumeration reached EOF before an image-stream marker.",
                    evidence_ids=(FLIF_PROCESS_LOOP_EVIDENCE_ID, FLIF_WRITE_LOOP_EVIDENCE_ID),
                )
            )
        else:
            gates.append(
                FlifOutputEmissionGate(
                    code="truncated_flif_chunk_header",
                    reason="Trailing bytes are not enough for ExifTool's four-byte FLIF tag read.",
                    evidence_ids=(FLIF_PROCESS_LOOP_EVIDENCE_ID, FLIF_WRITE_LOOP_EVIDENCE_ID),
                )
            )
    return _EnumerationResult(
        tuple(chunks),
        FlifImageStreamPlan(None, None, None, None, None, (FLIF_PROCESS_LOOP_EVIDENCE_ID,)),
        tuple(gates),
        unique_blockers(tuple(blockers)),
    )


def build_chunk_plan(
    index: int,
    tag: bytes,
    chunk_start: int,
    size_offset: int,
    payload_offset: int | None,
    compressed_size: int | None,
    chunk_end: int | None,
    payload: bytes,
    blockers: list[FlifRewriteBlocker],
) -> FlifMetadataChunkPlan:
    metadata_kind = METADATA_KINDS.get(tag)
    if metadata_kind is None:
        return FlifMetadataChunkPlan(
            index=index,
            tag=tag,
            chunk_start_offset=chunk_start,
            size_offset=size_offset,
            payload_offset=payload_offset,
            compressed_size=compressed_size,
            chunk_end_offset=chunk_end,
            metadata_kind=None,
            responsibility=None,
            inflated_size=None,
            inflate_succeeded=None,
            evidence_ids=(FLIF_PROCESS_LOOP_EVIDENCE_ID,),
        )

    responsibility = metadata_responsibility(tag, metadata_kind)
    inflated = inflate_raw_deflate(payload)
    if inflated is None:
        blockers.append(
            FlifRewriteBlocker(
                code="metadata_inflate_failed",
                reason=f"ExifTool would warn when raw-inflating FLIF {ascii_bytes(tag)} metadata.",
                evidence_ids=(FLIF_PROCESS_LOOP_EVIDENCE_ID,),
            )
        )
    blockers.append(
        FlifRewriteBlocker(
            code="flif_metadata_rewrite_not_implemented",
            reason=(
                "This planning surface identifies FLIF metadata rewrite responsibility "
                "but does not mutate compressed FLIF chunks."
            ),
            evidence_ids=(FLIF_WRITE_LOOP_EVIDENCE_ID,),
        )
    )
    blockers.append(
        FlifRewriteBlocker(
            code="compressed_metadata_requires_raw_inflate_deflate",
            reason="ExifTool rewrites FLIF metadata by raw-inflating and raw-deflating chunks.",
            evidence_ids=(FLIF_WRITE_LOOP_EVIDENCE_ID,),
        )
    )
    return FlifMetadataChunkPlan(
        index=index,
        tag=tag,
        chunk_start_offset=chunk_start,
        size_offset=size_offset,
        payload_offset=payload_offset,
        compressed_size=compressed_size,
        chunk_end_offset=chunk_end,
        metadata_kind=metadata_kind,
        responsibility=responsibility,
        inflated_size=None if inflated is None else len(inflated),
        inflate_succeeded=inflated is not None,
        evidence_ids=(FLIF_PROCESS_LOOP_EVIDENCE_ID, FLIF_TAG_TABLE_EVIDENCE_ID),
    )


def metadata_responsibility(
    tag: bytes,
    metadata_kind: FlifMetadataKind,
) -> FlifMetadataResponsibilityPlan:
    return FlifMetadataResponsibilityPlan(
        tag=tag,
        metadata_kind=metadata_kind,
        directory_name=metadata_kind,
        tag_table=METADATA_TAG_TABLES[metadata_kind],
        process_proc="Image::ExifTool::ProcessTIFF" if metadata_kind == "EXIF" else None,
        write_proc="Image::ExifTool::WriteTIFF" if metadata_kind == "EXIF" else None,
        exif_header_skip=6 if metadata_kind == "EXIF" else None,
        exif_header=b"Exif\0\0" if metadata_kind == "EXIF" else None,
        evidence_ids=(FLIF_TAG_TABLE_EVIDENCE_ID, FLIF_MAP_EVIDENCE_ID),
    )


def actions_for_chunks(
    chunks: tuple[FlifMetadataChunkPlan, ...],
    image_stream: FlifImageStreamPlan,
) -> tuple[FlifActionPlan, ...]:
    actions: list[FlifActionPlan] = []
    for chunk in chunks:
        action_kind: FlifActionKind = (
            "preserve_metadata_chunk" if chunk.is_known_metadata else "preserve_unknown_chunk"
        )
        if chunk.is_known_metadata:
            actions.append(
                FlifActionPlan(
                    kind="inflate_metadata_chunk",
                    target=ascii_bytes(chunk.tag),
                    byte_range=payload_range(chunk),
                    reason=(
                        "Known FLIF metadata chunks are raw-inflated before subdirectory handling."
                    ),
                    evidence_ids=(FLIF_PROCESS_LOOP_EVIDENCE_ID,),
                )
            )
        actions.append(
            FlifActionPlan(
                kind=action_kind,
                target=ascii_bytes(chunk.tag),
                byte_range=chunk_range(chunk),
                reason="Preserve the source FLIF chunk bytes in this non-mutating plan.",
                evidence_ids=(FLIF_PROCESS_LOOP_EVIDENCE_ID, FLIF_WRITE_LOOP_EVIDENCE_ID),
            )
        )
    if image_stream.byte_range is not None:
        actions.append(
            FlifActionPlan(
                kind="preserve_image_stream",
                target="image_stream",
                byte_range=image_stream.byte_range,
                reason="Preserve the SOI marker bytes and all remaining FLIF image data.",
                evidence_ids=(FLIF_PROCESS_LOOP_EVIDENCE_ID, FLIF_WRITE_LOOP_EVIDENCE_ID),
            )
        )
    return tuple(actions)


def _build_plan(
    flif_data: bytes,
    status: FlifPlanStatus,
    header: FlifHeaderPlan,
    chunks: tuple[FlifMetadataChunkPlan, ...],
    image_stream: FlifImageStreamPlan,
    actions: tuple[FlifActionPlan, ...],
    blockers: tuple[FlifRewriteBlocker, ...],
    gates: tuple[FlifOutputEmissionGate, ...],
) -> FlifImageTransactionPlan:
    responsibilities = tuple(
        chunk.responsibility for chunk in chunks if chunk.responsibility is not None
    )
    unique_gates = unique_emission_gates(gates)
    sources = unique_sources(
        (
            *FLIF_TRANSACTION_EVIDENCE_IDS,
            *header.evidence_ids,
            *image_stream.evidence_ids,
            *(source for chunk in chunks for source in chunk.evidence_ids),
            *(
                source
                for responsibility in responsibilities
                for source in responsibility.evidence_ids
            ),
            *(source for action in actions for source in action.evidence_ids),
            *(source for blocker in blockers for source in blocker.evidence_ids),
            *(source for gate in unique_gates for source in gate.evidence_ids),
        )
    )
    return FlifImageTransactionPlan(
        status=status,
        source_data=flif_data,
        header=header,
        metadata_chunks=chunks,
        metadata_responsibilities=responsibilities,
        image_stream=image_stream,
        actions=actions,
        rewrite_blockers=unique_blockers(blockers),
        output_emission_gates=unique_gates,
        evidence_ids=sources,
    )


def invalid_header(
    *,
    signature: bytes,
    reason: FlifEmissionGateCode,
    evidence_ids: tuple[str, ...],
    image_type_code: str | None = None,
    bit_depth_code: str | None = None,
) -> FlifHeaderPlan:
    return FlifHeaderPlan(
        signature=signature,
        image_type_code=image_type_code,
        image_type_description=(
            None if image_type_code is None else IMAGE_TYPE_DESCRIPTIONS.get(image_type_code)
        ),
        bit_depth_code=bit_depth_code,
        bit_depth=None if bit_depth_code is None else BIT_DEPTHS.get(bit_depth_code),
        is_custom_bit_depth=bit_depth_code == "0",
        image_width=None,
        image_height=None,
        animation_frames=None,
        animated=None,
        interlaced=None,
        color_model="unknown",
        channel_count=None,
        header_byte_length=None,
        is_valid=False,
        reason=reason,
        evidence_ids=evidence_ids,
    )


def invalid_header_with_codes(
    signature: bytes,
    image_type_code: str,
    bit_depth_code: str,
    reason: FlifEmissionGateCode,
    header_byte_length: int,
) -> FlifHeaderPlan:
    plan = invalid_header(
        signature=signature,
        image_type_code=image_type_code,
        bit_depth_code=bit_depth_code,
        reason=reason,
        evidence_ids=(FLIF_HEADER_EVIDENCE_ID, FLIF_VARINT_EVIDENCE_ID),
    )
    return FlifHeaderPlan(
        signature=plan.signature,
        image_type_code=plan.image_type_code,
        image_type_description=plan.image_type_description,
        bit_depth_code=plan.bit_depth_code,
        bit_depth=plan.bit_depth,
        is_custom_bit_depth=plan.is_custom_bit_depth,
        image_width=None,
        image_height=None,
        animation_frames=None,
        animated=ord(image_type_code) > ord("H"),
        interlaced=image_type_code in {"A", "C", "D", "a", "c", "d"},
        color_model=color_model_for_image_type(image_type_code),
        channel_count=channel_count_for_color_model(color_model_for_image_type(image_type_code)),
        header_byte_length=header_byte_length,
        is_valid=False,
        reason=reason,
        evidence_ids=plan.evidence_ids,
    )


def read_flif_varint(flif_data: bytes, offset: int, add: int = 0) -> _VarIntResult:
    start = offset
    value = 0
    while True:
        if offset >= len(flif_data):
            return _VarIntResult(None, start, offset, "truncated_flif_header_varint")
        byte = flif_data[offset]
        offset += 1
        value |= byte & 0x7F
        if not byte & 0x80:
            return _VarIntResult(value + add, start, offset, None)
        value <<= 7


def color_model_for_image_type(image_type: str) -> FlifColorModel:
    if image_type in {"1", "A", "Q", "a"}:
        return "grayscale"
    if image_type in {"3", "C", "S", "c"}:
        return "rgb"
    if image_type in {"4", "D", "T", "d"}:
        return "rgba"
    return "unknown"


def channel_count_for_color_model(color_model: FlifColorModel) -> int | None:
    if color_model == "grayscale":
        return 1
    if color_model == "rgb":
        return 3
    if color_model == "rgba":
        return 4
    return None


def inflate_raw_deflate(payload: bytes) -> bytes | None:
    try:
        return zlib.decompress(payload, wbits=-15)
    except zlib.error:
        return None


def payload_range(chunk: FlifMetadataChunkPlan) -> tuple[int, int] | None:
    if chunk.payload_offset is None or chunk.compressed_size is None:
        return None
    return (chunk.payload_offset, chunk.payload_offset + chunk.compressed_size)


def chunk_range(chunk: FlifMetadataChunkPlan) -> tuple[int, int] | None:
    if chunk.chunk_end_offset is None:
        return None
    return (chunk.chunk_start_offset, chunk.chunk_end_offset)


def malformed_blocker() -> FlifRewriteBlocker:
    return FlifRewriteBlocker(
        code="malformed_or_truncated_input",
        reason="FLIF metadata rewrite is blocked until the source parses without structural gates.",
        evidence_ids=(FLIF_HEADER_EVIDENCE_ID, FLIF_PROCESS_LOOP_EVIDENCE_ID),
    )


def structural_gate_present(gates: list[FlifOutputEmissionGate]) -> bool:
    return any(gate.code != "non_mutating_plan_requires_explicit_emission" for gate in gates)


def _add_non_mutating_gate(
    gates: list[FlifOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        FlifOutputEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="FLIF transaction plans are non-mutating unless emission is explicitly allowed.",
            evidence_ids=(FLIF_WRITE_LOOP_EVIDENCE_ID,),
        )
    )


def unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


def unique_emission_gates(
    gates: tuple[FlifOutputEmissionGate, ...],
) -> tuple[FlifOutputEmissionGate, ...]:
    unique: list[FlifOutputEmissionGate] = []
    codes: set[FlifEmissionGateCode] = set()
    for gate in gates:
        if gate.code not in codes:
            codes.add(gate.code)
            unique.append(gate)
    return tuple(unique)


def unique_blockers(blockers: tuple[FlifRewriteBlocker, ...]) -> tuple[FlifRewriteBlocker, ...]:
    unique: list[FlifRewriteBlocker] = []
    codes: set[FlifRewriteBlockerCode] = set()
    for blocker in blockers:
        if blocker.code not in codes:
            codes.add(blocker.code)
            unique.append(blocker)
    return tuple(unique)


def ascii_bytes(value: bytes) -> str:
    if all(32 <= byte <= 126 for byte in value):
        return value.decode("ascii")
    return value.hex()


def json_range(byte_range: tuple[int, int] | None) -> JsonArray | None:
    if byte_range is None:
        return None
    start, end = byte_range
    return [start, end]


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return [value for value in values]


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)
