"""Source-grounded, non-mutating Paint Shop Pro metadata transaction plans.

ExifTool's PSP module validates the PSP signature, records the file version,
enumerates top-level PSP blocks, reads image characteristics, and walks creator
or extended sub-blocks. It routes EXIF from extended sub-block tag 3 and keeps
all other PSP payload bytes unchanged because PSP.pm does not provide a writer.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

PSP_SIGNATURE = b"Paint Shop Pro Image File\x0a\x1a\0\0\0\0\0"
PSP_SIGNATURE_SIZE = 32
PSP_VERSION_SIZE = 4
PSP_INITIAL_OFFSET = PSP_SIGNATURE_SIZE + PSP_VERSION_SIZE
PSP_MODERN_BLOCK_HEADER_SIZE = 10
PSP_LEGACY_BLOCK_HEADER_SIZE = 14
PSP_SUB_BLOCK_HEADER_SIZE = 10
PSP_BLOCK_MAGIC = b"~BK\0"
PSP_SUB_BLOCK_MAGIC = b"~FL\0"
PSP_IMAGE_INFO_BLOCK = 0
PSP_CREATOR_INFO_BLOCK = 1
PSP_EXTENDED_INFO_BLOCK = 10
PSP_EXIF_SUB_BLOCK = 3
PSP_MODERN_IMAGE_INFO_START = 4
PSP_IMAGE_INFO_MIN_SIZE = 27

type PspPlanStatus = Literal["planned", "unsupported"]
type PspBlockName = Literal["ImageInfo", "CreatorInfo", "ExtendedInfo", "UnknownBlock"]
type PspSubBlockParent = Literal["CreatorInfo", "ExtendedInfo"]
type PspEmbeddedKind = Literal["exif", "iptc", "xmp", "icc_profile"]
type PspEmbeddedAction = Literal["route_to_exif", "preserve_if_present"]
type PspRewriteOperation = Literal["insert", "replace", "delete"]
type PspRewriteTarget = Literal[
    "image_info",
    "creator_info",
    "extended_info",
    "exif",
    "iptc",
    "xmp",
    "icc_profile",
    "unknown_block",
    "payload",
]
type PspActionKind = Literal[
    "validate_signature_header",
    "enumerate_main_blocks",
    "enumerate_sub_blocks",
    "extract_image_characteristics",
    "route_creator_metadata",
    "route_embedded_exif",
    "preserve_image_payload",
    "preserve_unknown_block",
    "preserve_unknown_sub_block",
    "preserve_metadata_payload",
    "block_requested_rewrite",
]
type PspEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_psp_signature",
    "invalid_psp_signature",
    "truncated_psp_file_version",
    "truncated_psp_block_header",
    "lost_psp_block_sync",
    "truncated_psp_block",
    "truncated_psp_sub_block",
    "lost_psp_sub_block_sync",
    "truncated_psp_image_info",
    "rewrite_requested_requires_psp_writer",
]

PSP_DESCRIPTION_SOURCE = "psp.description"
PSP_MAIN_TABLE_SOURCE = "psp.main_table"
PSP_IMAGE_TABLE_SOURCE = "psp.image_table"
PSP_CREATOR_TABLE_SOURCE = "psp.creator_table"
PSP_EXTENDED_TABLE_SOURCE = "psp.extended_table"
PSP_SUB_BLOCK_LOOP_SOURCE = "psp.sub_block_loop"
PSP_PROCESS_GATE_SOURCE = "psp.process_gate"
PSP_BLOCK_LOOP_SOURCE = "psp.block_loop"
PSP_READ_ONLY_SOURCE = "psp.read_only"

PSP_TRANSACTION_SOURCES = (
    PSP_DESCRIPTION_SOURCE,
    PSP_MAIN_TABLE_SOURCE,
    PSP_IMAGE_TABLE_SOURCE,
    PSP_CREATOR_TABLE_SOURCE,
    PSP_EXTENDED_TABLE_SOURCE,
    PSP_SUB_BLOCK_LOOP_SOURCE,
    PSP_PROCESS_GATE_SOURCE,
    PSP_BLOCK_LOOP_SOURCE,
    PSP_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class PspOutputEmissionGate:
    code: PspEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PspRewriteRequest:
    target: PspRewriteTarget
    operation: PspRewriteOperation
    payload: bytes | None = None


@dataclass(frozen=True)
class PspHeaderValidationPlan:
    signature_range: tuple[int, int]
    signature_valid: bool
    version_range: tuple[int, int] | None
    file_version_words: tuple[int, int] | None
    file_version: str | None
    block_header_size: int | None
    reason: PspEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class PspBlockPlan:
    index: int
    tag_id: int
    name: PspBlockName
    header_range: tuple[int, int]
    payload_range: tuple[int, int]
    declared_length: int
    known_to_exiftool: bool
    truncated: bool
    evidence_ids: tuple[str, ...]

    @property
    def payload_length(self) -> int:
        start, end = self.payload_range
        return end - start


@dataclass(frozen=True)
class PspSubBlockPlan:
    parent_block_index: int
    parent_name: PspSubBlockParent
    index: int
    tag_id: int
    name: str
    header_range: tuple[int, int]
    payload_range: tuple[int, int]
    declared_length: int
    known_to_exiftool: bool
    routed: bool
    valid_exif_header: bool | None
    truncated: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PspImageInfoPlan:
    block_index: int | None
    raw_range: tuple[int, int] | None
    table_start_offset: int | None
    image_width: int | None
    image_height: int | None
    image_resolution: float | None
    resolution_unit: int | None
    resolution_unit_description: str | None
    compression: int | None
    compression_description: str | None
    bits_per_sample: int | None
    planes: int | None
    num_colors: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PspCreatorMetadataPlan:
    sub_blocks: tuple[PspSubBlockPlan, ...]
    title_present: bool
    create_date_present: bool
    modify_date_present: bool
    artist_present: bool
    copyright_present: bool
    description_present: bool
    creator_app_id_present: bool
    creator_app_version_present: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PspEmbeddedPayloadPlan:
    kind: PspEmbeddedKind
    action: PspEmbeddedAction
    payload_ranges: tuple[tuple[int, int], ...]
    reason: str
    evidence_ids: tuple[str, ...]

    @property
    def is_present(self) -> bool:
        return bool(self.payload_ranges)


@dataclass(frozen=True)
class PspEmbeddedMetadataPlan:
    exif: PspEmbeddedPayloadPlan
    iptc: PspEmbeddedPayloadPlan
    xmp: PspEmbeddedPayloadPlan
    icc_profile: PspEmbeddedPayloadPlan
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PspPayloadPreservationPlan:
    source_range: tuple[int, int]
    image_payload_ranges: tuple[tuple[int, int], ...]
    known_metadata_ranges: tuple[tuple[int, int], ...]
    unknown_block_ranges: tuple[tuple[int, int], ...]
    unknown_sub_block_ranges: tuple[tuple[int, int], ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PspActionPlan:
    kind: PspActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PspMetadataTransactionPlan:
    status: PspPlanStatus
    source_data: bytes
    header_validation: PspHeaderValidationPlan
    blocks: tuple[PspBlockPlan, ...]
    sub_blocks: tuple[PspSubBlockPlan, ...]
    image_info: PspImageInfoPlan
    creator_metadata: PspCreatorMetadataPlan
    embedded_metadata: PspEmbeddedMetadataPlan
    preservation: PspPayloadPreservationPlan
    actions: tuple[PspActionPlan, ...]
    output_emission_gates: tuple[PspOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"PSP metadata transaction output is gated: {gate_codes}")
        return self.source_data


def build_psp_metadata_transaction_plan(
    psp_data: bytes,
    *,
    rewrite_requests: tuple[PspRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> PspMetadataTransactionPlan:
    """Build a preserve-only PSP metadata transaction plan from in-memory bytes."""

    gates: list[PspOutputEmissionGate] = []
    header = build_psp_header_validation_plan(psp_data)
    if header.reason is not None:
        gates.append(
            PspOutputEmissionGate(
                code=header.reason,
                reason="Input does not satisfy ExifTool's PSP signature/version gate.",
                evidence_ids=header.evidence_ids,
            )
        )

    blocks = build_psp_block_plans(psp_data, header, gates)
    sub_blocks = build_psp_sub_block_plans(psp_data, blocks, gates)
    image_info = build_psp_image_info_plan(psp_data, header, blocks, gates)
    creator_metadata = build_psp_creator_metadata_plan(sub_blocks)
    embedded_metadata = build_psp_embedded_metadata_plan(sub_blocks)
    preservation = build_psp_payload_preservation_plan(psp_data, blocks, sub_blocks)
    actions = build_psp_actions(blocks, sub_blocks, image_info, rewrite_requests)

    if rewrite_requests:
        gates.append(
            PspOutputEmissionGate(
                code="rewrite_requested_requires_psp_writer",
                reason="PSP.pm provides read behavior only, so requested rewrites are blocked.",
                evidence_ids=(PSP_READ_ONLY_SOURCE,),
            )
        )
    add_non_mutating_gate(gates, allow_output_emission)
    unique_gates = unique_emission_gates(tuple(gates))
    status: PspPlanStatus = "unsupported" if structural_gate_present(unique_gates) else "planned"
    sources = unique_sources(
        (
            *PSP_TRANSACTION_SOURCES,
            *header.evidence_ids,
            *(source for block in blocks for source in block.evidence_ids),
            *(source for sub_block in sub_blocks for source in sub_block.evidence_ids),
            *image_info.evidence_ids,
            *creator_metadata.evidence_ids,
            *embedded_metadata.evidence_ids,
            *preservation.evidence_ids,
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in unique_gates for source in gate.evidence_ids),
        )
    )
    return PspMetadataTransactionPlan(
        status=status,
        source_data=psp_data,
        header_validation=header,
        blocks=blocks,
        sub_blocks=sub_blocks,
        image_info=image_info,
        creator_metadata=creator_metadata,
        embedded_metadata=embedded_metadata,
        preservation=preservation,
        actions=actions,
        output_emission_gates=unique_gates,
        evidence_ids=sources,
    )


def build_psp_header_validation_plan(psp_data: bytes) -> PspHeaderValidationPlan:
    signature_range = (0, min(len(psp_data), PSP_SIGNATURE_SIZE))
    if len(psp_data) < PSP_SIGNATURE_SIZE:
        return PspHeaderValidationPlan(
            signature_range=signature_range,
            signature_valid=False,
            version_range=None,
            file_version_words=None,
            file_version=None,
            block_header_size=None,
            reason="truncated_psp_signature",
            evidence_ids=(PSP_PROCESS_GATE_SOURCE,),
        )
    signature_valid = psp_data[:PSP_SIGNATURE_SIZE] == PSP_SIGNATURE
    if not signature_valid:
        return PspHeaderValidationPlan(
            signature_range=signature_range,
            signature_valid=False,
            version_range=None,
            file_version_words=None,
            file_version=None,
            block_header_size=None,
            reason="invalid_psp_signature",
            evidence_ids=(PSP_PROCESS_GATE_SOURCE,),
        )
    if len(psp_data) < PSP_INITIAL_OFFSET:
        return PspHeaderValidationPlan(
            signature_range=signature_range,
            signature_valid=True,
            version_range=(PSP_SIGNATURE_SIZE, len(psp_data)),
            file_version_words=None,
            file_version=None,
            block_header_size=None,
            reason="truncated_psp_file_version",
            evidence_ids=(PSP_PROCESS_GATE_SOURCE,),
        )
    major = read_u16le(psp_data, PSP_SIGNATURE_SIZE)
    minor = read_u16le(psp_data, PSP_SIGNATURE_SIZE + 2)
    block_header_size = PSP_MODERN_BLOCK_HEADER_SIZE if major > 3 else PSP_LEGACY_BLOCK_HEADER_SIZE
    return PspHeaderValidationPlan(
        signature_range=signature_range,
        signature_valid=True,
        version_range=(PSP_SIGNATURE_SIZE, PSP_INITIAL_OFFSET),
        file_version_words=(major, minor),
        file_version=f"{major}.{minor}",
        block_header_size=block_header_size,
        reason=None,
        evidence_ids=(PSP_PROCESS_GATE_SOURCE, PSP_MAIN_TABLE_SOURCE),
    )


def build_psp_block_plans(
    psp_data: bytes,
    header: PspHeaderValidationPlan,
    gates: list[PspOutputEmissionGate],
) -> tuple[PspBlockPlan, ...]:
    if not header.is_exiftool_accepted or header.block_header_size is None:
        return ()
    blocks: list[PspBlockPlan] = []
    offset = PSP_INITIAL_OFFSET
    while offset < len(psp_data):
        remaining = len(psp_data) - offset
        if remaining < header.block_header_size:
            gates.append(
                PspOutputEmissionGate(
                    code="truncated_psp_block_header",
                    reason="Input ends before the next PSP main block header is complete.",
                    evidence_ids=(PSP_BLOCK_LOOP_SOURCE,),
                )
            )
            break
        header_end = offset + header.block_header_size
        if psp_data[offset : offset + 4] != PSP_BLOCK_MAGIC:
            gates.append(
                PspOutputEmissionGate(
                    code="lost_psp_block_sync",
                    reason="Main PSP block does not begin with ExifTool's ~BK marker.",
                    evidence_ids=(PSP_BLOCK_LOOP_SOURCE,),
                )
            )
            break
        tag_id = read_u16le(psp_data, offset + 4)
        declared_length = read_u32le(psp_data, offset + header.block_header_size - 4)
        payload_start = header_end
        payload_end = payload_start + declared_length
        truncated = payload_end > len(psp_data)
        actual_payload_end = min(payload_end, len(psp_data))
        blocks.append(
            PspBlockPlan(
                index=len(blocks),
                tag_id=tag_id,
                name=block_name(tag_id),
                header_range=(offset, header_end),
                payload_range=(payload_start, actual_payload_end),
                declared_length=declared_length,
                known_to_exiftool=tag_id
                in {
                    PSP_IMAGE_INFO_BLOCK,
                    PSP_CREATOR_INFO_BLOCK,
                    PSP_EXTENDED_INFO_BLOCK,
                },
                truncated=truncated,
                evidence_ids=(PSP_MAIN_TABLE_SOURCE, PSP_BLOCK_LOOP_SOURCE),
            )
        )
        if truncated:
            gates.append(
                PspOutputEmissionGate(
                    code="truncated_psp_block",
                    reason="A PSP main block declares bytes beyond the available input.",
                    evidence_ids=(PSP_BLOCK_LOOP_SOURCE,),
                )
            )
            break
        offset = payload_end
    return tuple(blocks)


def build_psp_sub_block_plans(
    psp_data: bytes,
    blocks: tuple[PspBlockPlan, ...],
    gates: list[PspOutputEmissionGate],
) -> tuple[PspSubBlockPlan, ...]:
    sub_blocks: list[PspSubBlockPlan] = []
    for block in blocks:
        if block.name not in {"CreatorInfo", "ExtendedInfo"} or block.truncated:
            continue
        parent_name: PspSubBlockParent = (
            "CreatorInfo" if block.name == "CreatorInfo" else "ExtendedInfo"
        )
        block_payload = psp_data[block.payload_range[0] : block.payload_range[1]]
        local_offset = 0
        while local_offset + PSP_SUB_BLOCK_HEADER_SIZE < len(block_payload):
            absolute_header_start = block.payload_range[0] + local_offset
            if block_payload[local_offset : local_offset + 4] != PSP_SUB_BLOCK_MAGIC:
                gates.append(
                    PspOutputEmissionGate(
                        code="lost_psp_sub_block_sync",
                        reason="Nested PSP sub-block does not begin with ExifTool's ~FL marker.",
                        evidence_ids=(PSP_SUB_BLOCK_LOOP_SOURCE,),
                    )
                )
                break
            tag_id = read_u16le(block_payload, local_offset + 4)
            declared_length = read_u32le(block_payload, local_offset + 6)
            payload_start = absolute_header_start + PSP_SUB_BLOCK_HEADER_SIZE
            payload_end = payload_start + declared_length
            block_end = block.payload_range[1]
            truncated = payload_end > block_end
            actual_payload_end = min(payload_end, block_end)
            known = is_known_sub_block(parent_name, tag_id)
            valid_exif_header = (
                is_valid_psp_exif_payload(psp_data, (payload_start, actual_payload_end))
                if parent_name == "ExtendedInfo" and tag_id == PSP_EXIF_SUB_BLOCK
                else None
            )
            sub_blocks.append(
                PspSubBlockPlan(
                    parent_block_index=block.index,
                    parent_name=parent_name,
                    index=sum(1 for item in sub_blocks if item.parent_block_index == block.index),
                    tag_id=tag_id,
                    name=sub_block_name(parent_name, tag_id),
                    header_range=(absolute_header_start, absolute_header_start + 10),
                    payload_range=(payload_start, actual_payload_end),
                    declared_length=declared_length,
                    known_to_exiftool=known,
                    routed=known
                    and (
                        parent_name == "CreatorInfo"
                        or (
                            tag_id == PSP_EXIF_SUB_BLOCK
                            and valid_exif_header is True
                            and not truncated
                        )
                    ),
                    valid_exif_header=valid_exif_header,
                    truncated=truncated,
                    evidence_ids=(
                        PSP_CREATOR_TABLE_SOURCE
                        if parent_name == "CreatorInfo"
                        else PSP_EXTENDED_TABLE_SOURCE,
                        PSP_SUB_BLOCK_LOOP_SOURCE,
                    ),
                )
            )
            if truncated:
                gates.append(
                    PspOutputEmissionGate(
                        code="truncated_psp_sub_block",
                        reason="A PSP sub-block declares bytes beyond its containing block.",
                        evidence_ids=(PSP_SUB_BLOCK_LOOP_SOURCE,),
                    )
                )
                break
            local_offset += PSP_SUB_BLOCK_HEADER_SIZE + declared_length
    return tuple(sub_blocks)


def build_psp_image_info_plan(
    psp_data: bytes,
    header: PspHeaderValidationPlan,
    blocks: tuple[PspBlockPlan, ...],
    gates: list[PspOutputEmissionGate],
) -> PspImageInfoPlan:
    image_block = next((block for block in blocks if block.tag_id == PSP_IMAGE_INFO_BLOCK), None)
    if image_block is None or image_block.truncated:
        return empty_image_info_plan()
    table_start_delta = (
        PSP_MODERN_IMAGE_INFO_START
        if header.file_version_words is not None and header.file_version_words[0] > 3
        else 0
    )
    table_start = image_block.payload_range[0] + table_start_delta
    table_end_required = table_start + PSP_IMAGE_INFO_MIN_SIZE
    if table_end_required > image_block.payload_range[1]:
        gates.append(
            PspOutputEmissionGate(
                code="truncated_psp_image_info",
                reason="ImageInfo block is too short for ExifTool's declared image fields.",
                evidence_ids=(PSP_IMAGE_TABLE_SOURCE,),
            )
        )
        return PspImageInfoPlan(
            block_index=image_block.index,
            raw_range=image_block.payload_range,
            table_start_offset=table_start,
            image_width=None,
            image_height=None,
            image_resolution=None,
            resolution_unit=None,
            resolution_unit_description=None,
            compression=None,
            compression_description=None,
            bits_per_sample=None,
            planes=None,
            num_colors=None,
            evidence_ids=(PSP_IMAGE_TABLE_SOURCE, PSP_PROCESS_GATE_SOURCE),
        )
    resolution_unit = psp_data[table_start + 16]
    compression = read_u16le(psp_data, table_start + 17)
    return PspImageInfoPlan(
        block_index=image_block.index,
        raw_range=image_block.payload_range,
        table_start_offset=table_start,
        image_width=read_u32le(psp_data, table_start),
        image_height=read_u32le(psp_data, table_start + 4),
        image_resolution=struct.unpack("<d", psp_data[table_start + 8 : table_start + 16])[0],
        resolution_unit=resolution_unit,
        resolution_unit_description=resolution_unit_description(resolution_unit),
        compression=compression,
        compression_description=compression_description(compression),
        bits_per_sample=read_u16le(psp_data, table_start + 19),
        planes=read_u16le(psp_data, table_start + 21),
        num_colors=read_u32le(psp_data, table_start + 23),
        evidence_ids=(PSP_IMAGE_TABLE_SOURCE, PSP_PROCESS_GATE_SOURCE),
    )


def build_psp_creator_metadata_plan(
    sub_blocks: tuple[PspSubBlockPlan, ...],
) -> PspCreatorMetadataPlan:
    creator_sub_blocks = tuple(item for item in sub_blocks if item.parent_name == "CreatorInfo")
    tag_ids = {item.tag_id for item in creator_sub_blocks if item.known_to_exiftool}
    return PspCreatorMetadataPlan(
        sub_blocks=creator_sub_blocks,
        title_present=0 in tag_ids,
        create_date_present=1 in tag_ids,
        modify_date_present=2 in tag_ids,
        artist_present=3 in tag_ids,
        copyright_present=4 in tag_ids,
        description_present=5 in tag_ids,
        creator_app_id_present=6 in tag_ids,
        creator_app_version_present=7 in tag_ids,
        evidence_ids=(PSP_CREATOR_TABLE_SOURCE, PSP_SUB_BLOCK_LOOP_SOURCE),
    )


def build_psp_embedded_metadata_plan(
    sub_blocks: tuple[PspSubBlockPlan, ...],
) -> PspEmbeddedMetadataPlan:
    exif_ranges = tuple(
        item.payload_range
        for item in sub_blocks
        if item.parent_name == "ExtendedInfo"
        and item.tag_id == PSP_EXIF_SUB_BLOCK
        and item.known_to_exiftool
        and item.routed
    )
    exif = PspEmbeddedPayloadPlan(
        kind="exif",
        action="route_to_exif",
        payload_ranges=exif_ranges,
        reason="ExtendedInfo tag 3 is routed as EXIFInfo when its Exif/TIFF header is valid.",
        evidence_ids=(PSP_EXTENDED_TABLE_SOURCE, PSP_SUB_BLOCK_LOOP_SOURCE),
    )
    preserve_reason = "PSP.pm does not declare this embedded metadata route; preserve bytes."
    iptc = PspEmbeddedPayloadPlan(
        kind="iptc",
        action="preserve_if_present",
        payload_ranges=(),
        reason=preserve_reason,
        evidence_ids=(PSP_EXTENDED_TABLE_SOURCE, PSP_BLOCK_LOOP_SOURCE),
    )
    xmp = PspEmbeddedPayloadPlan(
        kind="xmp",
        action="preserve_if_present",
        payload_ranges=(),
        reason=preserve_reason,
        evidence_ids=(PSP_EXTENDED_TABLE_SOURCE, PSP_BLOCK_LOOP_SOURCE),
    )
    icc_profile = PspEmbeddedPayloadPlan(
        kind="icc_profile",
        action="preserve_if_present",
        payload_ranges=(),
        reason=preserve_reason,
        evidence_ids=(PSP_EXTENDED_TABLE_SOURCE, PSP_BLOCK_LOOP_SOURCE),
    )
    return PspEmbeddedMetadataPlan(
        exif=exif,
        iptc=iptc,
        xmp=xmp,
        icc_profile=icc_profile,
        evidence_ids=(PSP_EXTENDED_TABLE_SOURCE, PSP_SUB_BLOCK_LOOP_SOURCE),
    )


def build_psp_payload_preservation_plan(
    psp_data: bytes,
    blocks: tuple[PspBlockPlan, ...],
    sub_blocks: tuple[PspSubBlockPlan, ...],
) -> PspPayloadPreservationPlan:
    image_payload_ranges = tuple(
        block.payload_range for block in blocks if block.tag_id == PSP_IMAGE_INFO_BLOCK
    )
    known_metadata_ranges = tuple(
        block.payload_range
        for block in blocks
        if block.tag_id in {PSP_CREATOR_INFO_BLOCK, PSP_EXTENDED_INFO_BLOCK}
    )
    unknown_block_ranges = tuple(
        block.payload_range for block in blocks if not block.known_to_exiftool
    )
    unknown_sub_block_ranges = tuple(
        item.payload_range for item in sub_blocks if not item.known_to_exiftool
    )
    return PspPayloadPreservationPlan(
        source_range=(0, len(psp_data)),
        image_payload_ranges=image_payload_ranges,
        known_metadata_ranges=known_metadata_ranges,
        unknown_block_ranges=unknown_block_ranges,
        unknown_sub_block_ranges=unknown_sub_block_ranges,
        evidence_ids=(PSP_BLOCK_LOOP_SOURCE, PSP_READ_ONLY_SOURCE),
    )


def build_psp_actions(
    blocks: tuple[PspBlockPlan, ...],
    sub_blocks: tuple[PspSubBlockPlan, ...],
    image_info: PspImageInfoPlan,
    rewrite_requests: tuple[PspRewriteRequest, ...],
) -> tuple[PspActionPlan, ...]:
    actions: list[PspActionPlan] = [
        PspActionPlan(
            kind="validate_signature_header",
            target="psp_signature_and_version",
            byte_range=(0, PSP_INITIAL_OFFSET),
            reason="Mirror ExifTool's PSP signature and version gate.",
            evidence_ids=(PSP_PROCESS_GATE_SOURCE,),
        )
    ]
    for block in blocks:
        actions.append(
            PspActionPlan(
                kind="enumerate_main_blocks",
                target=f"{block.name}:{block.tag_id}",
                byte_range=block.header_range,
                reason="Mirror ExifTool's sequential ~BK main block scan.",
                evidence_ids=(PSP_BLOCK_LOOP_SOURCE,),
            )
        )
        if block.tag_id == PSP_IMAGE_INFO_BLOCK:
            actions.append(
                PspActionPlan(
                    kind="preserve_image_payload",
                    target="ImageInfo",
                    byte_range=block.payload_range,
                    reason="Keep the PSP ImageInfo payload unchanged.",
                    evidence_ids=(PSP_READ_ONLY_SOURCE,),
                )
            )
        elif block.known_to_exiftool:
            actions.append(
                PspActionPlan(
                    kind="preserve_metadata_payload",
                    target=block.name,
                    byte_range=block.payload_range,
                    reason="Keep known PSP metadata block bytes unchanged.",
                    evidence_ids=(PSP_READ_ONLY_SOURCE,),
                )
            )
        else:
            actions.append(
                PspActionPlan(
                    kind="preserve_unknown_block",
                    target=f"unknown:{block.tag_id}",
                    byte_range=block.payload_range,
                    reason="ExifTool skips unknown PSP block IDs; preserve the payload.",
                    evidence_ids=(PSP_BLOCK_LOOP_SOURCE, PSP_READ_ONLY_SOURCE),
                )
            )
    if image_info.raw_range is not None:
        actions.append(
            PspActionPlan(
                kind="extract_image_characteristics",
                target="ImageInfo",
                byte_range=image_info.raw_range,
                reason="Extract ExifTool's PSP image characteristics from ImageInfo.",
                evidence_ids=(PSP_IMAGE_TABLE_SOURCE,),
            )
        )
    for sub_block in sub_blocks:
        actions.append(
            PspActionPlan(
                kind="enumerate_sub_blocks",
                target=f"{sub_block.parent_name}:{sub_block.tag_id}",
                byte_range=sub_block.header_range,
                reason="Mirror ExifTool's sequential ~FL sub-block scan.",
                evidence_ids=(PSP_SUB_BLOCK_LOOP_SOURCE,),
            )
        )
        if sub_block.parent_name == "CreatorInfo" and sub_block.known_to_exiftool:
            actions.append(
                PspActionPlan(
                    kind="route_creator_metadata",
                    target=sub_block.name,
                    byte_range=sub_block.payload_range,
                    reason="Route PSP creator metadata sub-blocks declared by PSP.pm.",
                    evidence_ids=(PSP_CREATOR_TABLE_SOURCE,),
                )
            )
        elif (
            sub_block.parent_name == "ExtendedInfo"
            and sub_block.tag_id == PSP_EXIF_SUB_BLOCK
            and sub_block.routed
        ):
            actions.append(
                PspActionPlan(
                    kind="route_embedded_exif",
                    target="EXIFInfo",
                    byte_range=sub_block.payload_range,
                    reason="Route ExtendedInfo tag 3 to EXIF when the payload header is valid.",
                    evidence_ids=(PSP_EXTENDED_TABLE_SOURCE, PSP_SUB_BLOCK_LOOP_SOURCE),
                )
            )
        elif sub_block.parent_name == "ExtendedInfo" and sub_block.tag_id == PSP_EXIF_SUB_BLOCK:
            actions.append(
                PspActionPlan(
                    kind="preserve_metadata_payload",
                    target="EXIFInfo:unrouted",
                    byte_range=sub_block.payload_range,
                    reason="Preserve EXIFInfo bytes when ExifTool's EXIF header gate fails.",
                    evidence_ids=(PSP_SUB_BLOCK_LOOP_SOURCE, PSP_READ_ONLY_SOURCE),
                )
            )
        elif not sub_block.known_to_exiftool:
            actions.append(
                PspActionPlan(
                    kind="preserve_unknown_sub_block",
                    target=f"{sub_block.parent_name}:unknown:{sub_block.tag_id}",
                    byte_range=sub_block.payload_range,
                    reason="ExifTool ignores unknown PSP sub-block tags; preserve the payload.",
                    evidence_ids=(PSP_SUB_BLOCK_LOOP_SOURCE, PSP_READ_ONLY_SOURCE),
                )
            )
    for request in rewrite_requests:
        actions.append(
            PspActionPlan(
                kind="block_requested_rewrite",
                target=f"{request.operation}:{request.target}",
                byte_range=None,
                reason="PSP.pm does not provide a writer for this requested mutation.",
                evidence_ids=(PSP_READ_ONLY_SOURCE,),
            )
        )
    return tuple(actions)


def empty_image_info_plan() -> PspImageInfoPlan:
    return PspImageInfoPlan(
        block_index=None,
        raw_range=None,
        table_start_offset=None,
        image_width=None,
        image_height=None,
        image_resolution=None,
        resolution_unit=None,
        resolution_unit_description=None,
        compression=None,
        compression_description=None,
        bits_per_sample=None,
        planes=None,
        num_colors=None,
        evidence_ids=(PSP_IMAGE_TABLE_SOURCE,),
    )


def block_name(tag_id: int) -> PspBlockName:
    if tag_id == PSP_IMAGE_INFO_BLOCK:
        return "ImageInfo"
    if tag_id == PSP_CREATOR_INFO_BLOCK:
        return "CreatorInfo"
    if tag_id == PSP_EXTENDED_INFO_BLOCK:
        return "ExtendedInfo"
    return "UnknownBlock"


def is_known_sub_block(parent_name: PspSubBlockParent, tag_id: int) -> bool:
    if parent_name == "CreatorInfo":
        return 0 <= tag_id <= 7
    return tag_id == PSP_EXIF_SUB_BLOCK


def sub_block_name(parent_name: PspSubBlockParent, tag_id: int) -> str:
    if parent_name == "CreatorInfo":
        names = {
            0: "Title",
            1: "CreateDate",
            2: "ModifyDate",
            3: "Artist",
            4: "Copyright",
            5: "Description",
            6: "CreatorAppID",
            7: "CreatorAppVersion",
        }
        return names.get(tag_id, "UnknownSubBlock")
    if tag_id == PSP_EXIF_SUB_BLOCK:
        return "EXIFInfo"
    return "UnknownSubBlock"


def resolution_unit_description(value: int) -> str | None:
    descriptions = {
        0: "None",
        1: "inches",
        2: "cm",
    }
    return descriptions.get(value)


def compression_description(value: int) -> str | None:
    descriptions = {
        0: "None",
        1: "RLE",
        2: "LZ77",
        3: "JPEG",
    }
    return descriptions.get(value)


def is_valid_psp_exif_payload(data: bytes, payload_range: tuple[int, int]) -> bool:
    start, end = payload_range
    payload_length = end - start
    return (
        payload_length > 14
        and data[start : start + 6] == b"Exif\0\0"
        and data[start + 6 : start + 8] in {b"II", b"MM"}
    )


def add_non_mutating_gate(
    gates: list[PspOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        PspOutputEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="PSP transaction plans are preserve-only unless output emission is explicit.",
            evidence_ids=(PSP_READ_ONLY_SOURCE,),
        )
    )


def structural_gate_present(gates: tuple[PspOutputEmissionGate, ...]) -> bool:
    non_structural_codes = {
        "rewrite_requested_requires_psp_writer",
        "non_mutating_plan_requires_explicit_emission",
    }
    return any(gate.code not in non_structural_codes for gate in gates)


def unique_emission_gates(
    gates: tuple[PspOutputEmissionGate, ...],
) -> tuple[PspOutputEmissionGate, ...]:
    seen: set[PspEmissionGateCode] = set()
    unique: list[PspOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


def read_u16le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def read_u32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")
