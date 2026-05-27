"""Source-backed Minolta MRW mutation planning.

ExifTool rewrites MRW by buffering metadata segments, delegating the TTW segment
to the TIFF writer, padding rewritten segments, and then copying raw image data.
This module models that sequence without attempting unsafe byte mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.raw_family.write_plan import (
    RawFamilyBlockerCode,
    RawFamilyWriteRequestClassification,
    RawFamilyWriteSurface,
    classify_raw_family_golden_request_file,
)
from exifmodern.json_types import JsonObject
from exifmodern.read_graph import TagProvenance

type MrwByteOrder = Literal["little", "big"]
type MinoltaMrwMutationPlanStatus = Literal["source_mapped_deferred", "unsupported"]
type MinoltaMrwSegmentName = Literal[
    "MinoltaTTW",
    "MinoltaPRD",
    "MinoltaWBG",
    "MinoltaRIF",
    "Padding",
    "Unknown",
]
type MinoltaMrwMutationStepKind = Literal[
    "validate_mrw_header",
    "enumerate_mrw_segments",
    "rewrite_ttw_segment_with_tiff_writer",
    "rewrite_binary_subdirectories",
    "pad_rewritten_segments_to_four_bytes",
    "write_mrw_header_with_new_metadata_length",
    "copy_raw_image_data",
]
type MinoltaMrwPrerequisite = Literal[
    "mrw_magic",
    "mrw_metadata_length",
    "known_mrw_segment_table",
    "ttw_tiff_writer",
    "binary_subdirectory_writers",
    "writeexif_ttw_length_fixup",
]
type MinoltaMrwSafetyGate = Literal[
    "defer_without_segment_rebuilder",
    "defer_without_embedded_tiff_rewriter",
    "defer_without_binary_data_rewriter",
    "defer_without_four_byte_padding_validation",
    "defer_without_raw_image_data_copy",
    "defer_without_ttw_offset_fixups",
]

MRW_SEGMENT_HEADER_SIZE = 8
MRW_SEGMENT_NAMES: dict[bytes, MinoltaMrwSegmentName] = {
    b"\0TTW": "MinoltaTTW",
    b"\0PRD": "MinoltaPRD",
    b"\0WBG": "MinoltaWBG",
    b"\0RIF": "MinoltaRIF",
    b"\0CSA": "Padding",
}

MINOLTA_RAW_MAIN_SOURCE_ID = "minolta_raw.mutation.main_table"
MINOLTA_RAW_BINARY_SOURCE_ID = "minolta_raw.mutation.prd_binary_data"
MINOLTA_RAW_WBG_SOURCE_ID = "minolta_raw.mutation.wbg_binary_data"
MINOLTA_RAW_RIF_SOURCE_ID = "minolta_raw.mutation.rif_binary_data"
MINOLTA_RAW_WRITE_SOURCE_ID = "minolta_raw.mutation.write_mrw_process_mrw"
WRITE_EXIF_MRW_TTW_SOURCE_ID = "minolta_raw.mutation.write_exif_ttw_fixups"


def minolta_mrw_tag_provenance(
    plan: MinoltaMrwMutationPlan,
    *,
    group: str,
    table_name: str,
    tag_id: str | None,
    duplicate_instance_ordinal: int | None = None,
) -> TagProvenance:
    return TagProvenance(
        group=group,
        table_name=table_name,
        tag_id=tag_id,
        source=_minolta_raw_evidence_id_text(plan.evidence_ids),
        family_0_group=group,
        family_1_group=group,
        family_2_group=group if group in {"Audio", "Video", "Image"} else None,
        duplicate_instance_ordinal=duplicate_instance_ordinal,
    )


def _minolta_raw_evidence_id_text(evidence_ids: tuple[str, ...]) -> str:
    if not evidence_ids:
        return "package-local-reader-plan"
    return evidence_ids[0]


MINOLTA_RAW_MAIN_EVIDENCE_ID = MINOLTA_RAW_MAIN_SOURCE_ID
MINOLTA_RAW_BINARY_EVIDENCE_ID = MINOLTA_RAW_BINARY_SOURCE_ID
MINOLTA_RAW_WBG_EVIDENCE_ID = MINOLTA_RAW_WBG_SOURCE_ID
MINOLTA_RAW_RIF_EVIDENCE_ID = MINOLTA_RAW_RIF_SOURCE_ID
MINOLTA_RAW_WRITE_EVIDENCE_ID = MINOLTA_RAW_WRITE_SOURCE_ID
WRITE_EXIF_MRW_TTW_EVIDENCE_ID = WRITE_EXIF_MRW_TTW_SOURCE_ID


@dataclass(frozen=True)
class MinoltaMrwSegmentSummary:
    tag_bytes_hex: str
    segment_name: MinoltaMrwSegmentName
    data_offset: int
    length: int
    padded_length: int

    def to_json(self) -> JsonObject:
        return {
            "data_offset": self.data_offset,
            "length": self.length,
            "padded_length": self.padded_length,
            "segment_name": self.segment_name,
            "tag_bytes_hex": self.tag_bytes_hex,
        }


@dataclass(frozen=True)
class MinoltaMrwHeaderSummary:
    magic: str
    byte_order: MrwByteOrder
    metadata_length: int
    metadata_end_offset: int
    segments: tuple[MinoltaMrwSegmentSummary, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_order": self.byte_order,
            "magic": self.magic,
            "metadata_end_offset": self.metadata_end_offset,
            "metadata_length": self.metadata_length,
            "segments": [segment.to_json() for segment in self.segments],
        }


@dataclass(frozen=True)
class MinoltaMrwRequestedMutation:
    requested_tag: str
    requested_value: str
    generic_surfaces: tuple[RawFamilyWriteSurface, ...]
    generic_blockers: tuple[RawFamilyBlockerCode, ...]

    def to_json(self) -> JsonObject:
        return {
            "generic_blockers": list(self.generic_blockers),
            "generic_surfaces": list(self.generic_surfaces),
            "requested_tag": self.requested_tag,
            "requested_value": self.requested_value,
        }


@dataclass(frozen=True)
class MinoltaMrwMutationStep:
    kind: MinoltaMrwMutationStepKind
    description: str
    prerequisites: tuple[MinoltaMrwPrerequisite, ...]
    safety_gates: tuple[MinoltaMrwSafetyGate, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "description": self.description,
            "kind": self.kind,
            "prerequisites": list(self.prerequisites),
            "safety_gates": list(self.safety_gates),
        }


@dataclass(frozen=True)
class MinoltaMrwMutationPlan:
    status: MinoltaMrwMutationPlanStatus
    can_mutate: bool
    raw_family_request_id: str | None
    header: MinoltaMrwHeaderSummary | None
    requested_mutations: tuple[MinoltaMrwRequestedMutation, ...]
    steps: tuple[MinoltaMrwMutationStep, ...]
    safety_gates: tuple[MinoltaMrwSafetyGate, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_mutate": self.can_mutate,
            "header": self.header.to_json() if self.header is not None else None,
            "raw_family_request_id": self.raw_family_request_id,
            "requested_mutations": [
                requested_mutation.to_json() for requested_mutation in self.requested_mutations
            ],
            "safety_gates": list(self.safety_gates),
            "status": self.status,
            "steps": [step.to_json() for step in self.steps],
        }


def load_minolta_mrw_golden_mutation_plan(
    request_path: Path,
    data: bytes,
) -> MinoltaMrwMutationPlan:
    return build_minolta_mrw_mutation_plan(
        data,
        classify_raw_family_golden_request_file(request_path),
    )


def build_minolta_mrw_mutation_plan(
    data: bytes,
    raw_family_classification: RawFamilyWriteRequestClassification | None = None,
) -> MinoltaMrwMutationPlan:
    header = inspect_mrw_header(data)
    requested_mutations = requested_mutations_from_raw_family(raw_family_classification)
    steps = minolta_mrw_mutation_steps() if header is not None else ()
    status: MinoltaMrwMutationPlanStatus = (
        "source_mapped_deferred"
        if header is not None and raw_family_classification_is_mrw(raw_family_classification)
        else "unsupported"
    )
    return MinoltaMrwMutationPlan(
        status=status,
        can_mutate=False,
        raw_family_request_id=(
            raw_family_classification.request_id if raw_family_classification is not None else None
        ),
        header=header,
        requested_mutations=requested_mutations,
        steps=steps,
        safety_gates=unique_safety_gates(steps),
        evidence_ids=plan_evidence_ids(raw_family_classification),
    )


def inspect_mrw_header(data: bytes) -> MinoltaMrwHeaderSummary | None:
    if len(data) < 8 or data[:3] != b"\0MR":
        return None
    if data[3:4] == b"M":
        byte_order: MrwByteOrder = "big"
    elif data[3:4] == b"I":
        byte_order = "little"
    else:
        return None
    metadata_length = read_uint(data, 4, byte_order)
    metadata_end_offset = 8 + metadata_length
    if metadata_end_offset > len(data):
        return None
    return MinoltaMrwHeaderSummary(
        magic=data[:4].decode("latin-1"),
        byte_order=byte_order,
        metadata_length=metadata_length,
        metadata_end_offset=metadata_end_offset,
        segments=parse_mrw_segments(data, metadata_end_offset, byte_order),
    )


def parse_mrw_segments(
    data: bytes,
    metadata_end_offset: int,
    byte_order: MrwByteOrder,
) -> tuple[MinoltaMrwSegmentSummary, ...]:
    segments: list[MinoltaMrwSegmentSummary] = []
    position = 8
    while position + MRW_SEGMENT_HEADER_SIZE <= metadata_end_offset:
        tag_bytes = data[position : position + 4]
        length = read_uint(data, position + 4, byte_order)
        data_offset = position + MRW_SEGMENT_HEADER_SIZE
        segment_end = data_offset + length
        if segment_end > metadata_end_offset:
            break
        segments.append(
            MinoltaMrwSegmentSummary(
                tag_bytes_hex=tag_bytes.hex(),
                segment_name=MRW_SEGMENT_NAMES.get(tag_bytes, "Unknown"),
                data_offset=data_offset,
                length=length,
                padded_length=length + ((4 - (length & 0x03)) & 0x03),
            )
        )
        position = segment_end
    return tuple(segments)


def requested_mutations_from_raw_family(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> tuple[MinoltaMrwRequestedMutation, ...]:
    if raw_family_classification is None:
        return ()
    return tuple(
        MinoltaMrwRequestedMutation(
            requested_tag=argument.requested_tag,
            requested_value=argument.requested_value,
            generic_surfaces=argument.target_surfaces,
            generic_blockers=argument.blocker_codes,
        )
        for argument in raw_family_classification.arguments
    )


def raw_family_classification_is_mrw(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> bool:
    if raw_family_classification is None:
        return True
    return (
        raw_family_classification.container == "mrw_minolta_raw"
        and raw_family_classification.status == "source_mapped_deferred"
        and all(
            "mrw_minolta_ttw_tiff" in argument.target_surfaces
            or "mrw_minolta_makernote_binary" in argument.target_surfaces
            for argument in raw_family_classification.arguments
        )
    )


def minolta_mrw_mutation_steps() -> tuple[MinoltaMrwMutationStep, ...]:
    return (
        MinoltaMrwMutationStep(
            kind="validate_mrw_header",
            description="Validate MRW magic, byte order, and metadata length before rewrite.",
            prerequisites=("mrw_magic", "mrw_metadata_length"),
            safety_gates=("defer_without_segment_rebuilder",),
            evidence_ids=(MINOLTA_RAW_WRITE_EVIDENCE_ID,),
        ),
        MinoltaMrwMutationStep(
            kind="enumerate_mrw_segments",
            description="Walk MRW metadata segments up to the raw image data offset.",
            prerequisites=("known_mrw_segment_table",),
            safety_gates=("defer_without_segment_rebuilder",),
            evidence_ids=(MINOLTA_RAW_MAIN_EVIDENCE_ID, MINOLTA_RAW_WRITE_EVIDENCE_ID),
        ),
        MinoltaMrwMutationStep(
            kind="rewrite_ttw_segment_with_tiff_writer",
            description="Delegate MinoltaTTW to WriteTIFF with MRW-specific offset handling.",
            prerequisites=("ttw_tiff_writer", "writeexif_ttw_length_fixup"),
            safety_gates=(
                "defer_without_embedded_tiff_rewriter",
                "defer_without_ttw_offset_fixups",
            ),
            evidence_ids=(MINOLTA_RAW_MAIN_EVIDENCE_ID, WRITE_EXIF_MRW_TTW_EVIDENCE_ID),
        ),
        MinoltaMrwMutationStep(
            kind="rewrite_binary_subdirectories",
            description=(
                "Rewrite writable PRD/WBG/RIF binary subdirectories when requested tags land there."
            ),
            prerequisites=("binary_subdirectory_writers",),
            safety_gates=("defer_without_binary_data_rewriter",),
            evidence_ids=(
                MINOLTA_RAW_BINARY_EVIDENCE_ID,
                MINOLTA_RAW_WBG_EVIDENCE_ID,
                MINOLTA_RAW_RIF_EVIDENCE_ID,
            ),
        ),
        MinoltaMrwMutationStep(
            kind="pad_rewritten_segments_to_four_bytes",
            description=(
                "Pad rewritten MRW segment payloads to the even 4-byte length ExifTool expects."
            ),
            prerequisites=("mrw_metadata_length",),
            safety_gates=("defer_without_four_byte_padding_validation",),
            evidence_ids=(MINOLTA_RAW_WRITE_EVIDENCE_ID, WRITE_EXIF_MRW_TTW_EVIDENCE_ID),
        ),
        MinoltaMrwMutationStep(
            kind="write_mrw_header_with_new_metadata_length",
            description="Write a new MRW header whose length matches the rebuilt segment buffer.",
            prerequisites=("mrw_metadata_length",),
            safety_gates=("defer_without_segment_rebuilder",),
            evidence_ids=(MINOLTA_RAW_WRITE_EVIDENCE_ID,),
        ),
        MinoltaMrwMutationStep(
            kind="copy_raw_image_data",
            description="Stream raw image data after the rebuilt metadata segments.",
            prerequisites=("mrw_metadata_length",),
            safety_gates=("defer_without_raw_image_data_copy",),
            evidence_ids=(MINOLTA_RAW_WRITE_EVIDENCE_ID,),
        ),
    )


def plan_evidence_ids(
    raw_family_classification: RawFamilyWriteRequestClassification | None,
) -> tuple[str, ...]:
    evidence_ids = [
        MINOLTA_RAW_MAIN_EVIDENCE_ID,
        MINOLTA_RAW_BINARY_EVIDENCE_ID,
        MINOLTA_RAW_WBG_EVIDENCE_ID,
        MINOLTA_RAW_RIF_EVIDENCE_ID,
        MINOLTA_RAW_WRITE_EVIDENCE_ID,
        WRITE_EXIF_MRW_TTW_EVIDENCE_ID,
    ]
    return unique_evidence_ids(tuple(evidence_ids))


def read_uint(data: bytes, offset: int, byte_order: MrwByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order)


def unique_safety_gates(
    steps: tuple[MinoltaMrwMutationStep, ...],
) -> tuple[MinoltaMrwSafetyGate, ...]:
    safety_gates: list[MinoltaMrwSafetyGate] = []
    for step in steps:
        for safety_gate in step.safety_gates:
            if safety_gate not in safety_gates:
                safety_gates.append(safety_gate)
    return tuple(safety_gates)


def unique_evidence_ids(
    evidence_ids: tuple[str, ...],
) -> tuple[str, ...]:
    unique: list[str] = []
    for evidence_id in evidence_ids:
        if evidence_id not in unique:
            unique.append(evidence_id)
    return tuple(unique)
