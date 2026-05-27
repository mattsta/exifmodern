"""Nikon Capture block rebuild planning and local block emission.

ExifTool rewrites NikonCaptureData as a protected MakerNote subdirectory.  This
module models the byte choreography from NikonCapture.pm and the MakerNote
reinsertion gates from WriteExif.pl.  It can emit the rebuilt NikonCaptureData
block, but never reinserts that block into NEF/TIFF image bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.nikon_raw.mutation_plan import (
    NikonNefMakerNoteDirectoryLocation,
    NikonNefMakerNotePreviewOffsetPair,
    NikonNefNikonCaptureDiscoveryPlan,
    build_nikon_nef_nikon_capture_discovery_plan,
)
from exifmodern.formats.nikon_raw.sources import (
    IPTC_CAPTION_ABSTRACT_SOURCE,
    NIKON_CAPTURE_TAGS_SOURCE,
    NIKON_CAPTURE_WRITE_SOURCE,
    NIKON_PREVIEW_IFD_POINTER_SOURCE,
    NIKON_PREVIEW_IFD_SOURCE,
    WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
    WRITE_EXIF_MAKERNOTE_PADDING_SOURCE,
    WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
    WRITE_EXIF_REBUILD_MAKERNOTES_SOURCE,
    WRITE_EXIF_VALUE_FIXUP_SOURCE,
    WRITE_IPTC_SOURCE,
    EvidenceId,
    unique_evidence_ids,
)
from exifmodern.formats.nikon_raw.tiff_routing import (
    TIFF_IFD_ENTRY_SIZE,
    read_ifd_entry_count,
    read_uint,
)
from exifmodern.json_types import JsonObject

type NikonCaptureRebuildPlanStatus = Literal[
    "source_mapped_non_mutating",
    "unsupported",
]
type NikonCaptureBlockEmissionStatus = Literal[
    "emitted_nikon_capture_block",
    "unsupported",
]
type NikonCaptureIptcPayloadEmissionStatus = Literal[
    "emitted_iptc_payload",
    "unsupported",
]
type NikonNefCaptureIptcRewriteEmissionStatus = Literal[
    "emitted_nef_nikon_capture_block",
    "unsupported",
]
type NikonCapturePreviewOffsetPairProtectionStatus = Literal[
    "source_mapped_absent",
    "source_mapped_protected",
    "unsupported",
]
type NikonCaptureEntryAction = Literal[
    "copy_existing_entry",
    "rewrite_scalar_entry",
    "rewrite_iptc_subdirectory",
    "drop_empty_subdirectory",
    "copy_unknown_entry",
]
type NikonCaptureIptcEntryAction = Literal[
    "copy_existing_dataset",
    "replace_caption_abstract",
    "drop_caption_abstract",
    "insert_caption_abstract",
]
type NikonCaptureReplacementWriter = Literal[
    "scalar_value",
    "iptc_subdirectory",
]
type NikonCaptureReinsertionGateKind = Literal[
    "requires_existing_nikon_type2_makernote",
    "requires_writeexif_makernote_subdirectory_handoff",
    "requires_nikon_capture_write_directory_result",
    "requires_makernote_fixup_collection",
    "requires_preview_offset_pair_protection",
]

NIKON_CAPTURE_HEADER_SIZE = 22
NIKON_CAPTURE_FIXED_HEADER_SIZE = 18
NIKON_CAPTURE_ENTRY_PREFIX_SIZE = 18
NIKON_CAPTURE_ENTRY_SIZE_FIELD_SIZE = 4
NIKON_CAPTURE_ENTRY_HEADER_SIZE = (
    NIKON_CAPTURE_ENTRY_PREFIX_SIZE + NIKON_CAPTURE_ENTRY_SIZE_FIELD_SIZE
)
NIKON_CAPTURE_MAGIC = 0x7A86A940
NIKON_CAPTURE_ENTRY_SIZE_BIAS = 4

NIKON_CAPTURE_IPTC_TAG_ID = 0x9EF5F6E0
NIKON_CAPTURE_PHOTO_EFFECTS_TAG_ID = 0xAB5ECA5E
NIKON_CAPTURE_VIGNETTE_CONTROL_INTENSITY_TAG_ID = 0xAC6BD5C0
NIKON_PREVIEW_IFD_TAG_ID = 0x0011
NIKON_PREVIEW_IMAGE_START_TAG_ID = 0x0201
NIKON_PREVIEW_IMAGE_LENGTH_TAG_ID = 0x0202
IPTC_MARKER = 0x1C
IPTC_APPLICATION_RECORD = 2
IPTC_CAPTION_ABSTRACT_DATASET = 120
IPTC_SHORT_HEADER_SIZE = 5
IPTC_CAPTION_ABSTRACT_MAX_LENGTH = 2000


@dataclass(frozen=True)
class NikonCaptureTagSpec:
    tag_name: str
    writer: NikonCaptureReplacementWriter


NIKON_CAPTURE_TAG_SPECS = {
    NIKON_CAPTURE_IPTC_TAG_ID: NikonCaptureTagSpec("IPTCData", "iptc_subdirectory"),
    NIKON_CAPTURE_PHOTO_EFFECTS_TAG_ID: NikonCaptureTagSpec("PhotoEffects", "scalar_value"),
    NIKON_CAPTURE_VIGNETTE_CONTROL_INTENSITY_TAG_ID: NikonCaptureTagSpec(
        "VignetteControlIntensity",
        "scalar_value",
    ),
}
NIKON_CAPTURE_TAG_IDS_BY_NAME = {
    spec.tag_name: tag_id for tag_id, spec in NIKON_CAPTURE_TAG_SPECS.items()
}


@dataclass(frozen=True)
class NikonCaptureByteRange:
    start_offset: int
    end_offset: int

    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset

    def to_json(self) -> JsonObject:
        return {
            "end_offset": self.end_offset,
            "length": self.length,
            "start_offset": self.start_offset,
        }


@dataclass(frozen=True)
class NikonCaptureEntryReplacement:
    tag_name: str
    writer: NikonCaptureReplacementWriter
    payload: bytes


@dataclass(frozen=True)
class NikonCaptureHeaderValidation:
    block_range: NikonCaptureByteRange
    fixed_header_range: NikonCaptureByteRange
    size_field_range: NikonCaptureByteRange
    tag_id: int
    declared_size: int
    effective_directory_length: int
    trailing_padding_range: NikonCaptureByteRange | None
    trailing_padding_length: int
    legacy_size_includes_header: bool
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "block_range": self.block_range.to_json(),
            "declared_size": self.declared_size,
            "effective_directory_length": self.effective_directory_length,
            "fixed_header_range": self.fixed_header_range.to_json(),
            "legacy_size_includes_header": self.legacy_size_includes_header,
            "size_field_range": self.size_field_range.to_json(),
            "tag_id": self.tag_id,
            "tag_id_hex": f"0x{self.tag_id:08x}",
            "trailing_padding_length": self.trailing_padding_length,
            "trailing_padding_range": (
                self.trailing_padding_range.to_json()
                if self.trailing_padding_range is not None
                else None
            ),
        }


@dataclass(frozen=True)
class NikonCapturePaddingDecision:
    entry_value_padding_length: int
    trailing_padding_length: int
    preserves_original_trailing_padding: bool
    policy: str

    def to_json(self) -> JsonObject:
        return {
            "entry_value_padding_length": self.entry_value_padding_length,
            "policy": self.policy,
            "preserves_original_trailing_padding": self.preserves_original_trailing_padding,
            "trailing_padding_length": self.trailing_padding_length,
        }


@dataclass(frozen=True)
class NikonCaptureRebuildOperation:
    index: int
    tag_id: int
    tag_name: str | None
    action: NikonCaptureEntryAction
    original_entry_range: NikonCaptureByteRange
    original_value_range: NikonCaptureByteRange
    planned_output_range: NikonCaptureByteRange
    original_value_length: int
    replacement_value_length: int | None
    planned_value_length: int
    size_word_value: int
    padding: NikonCapturePaddingDecision
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "index": self.index,
            "original_entry_range": self.original_entry_range.to_json(),
            "original_value_length": self.original_value_length,
            "original_value_range": self.original_value_range.to_json(),
            "padding": self.padding.to_json(),
            "planned_output_range": self.planned_output_range.to_json(),
            "planned_value_length": self.planned_value_length,
            "replacement_value_length": self.replacement_value_length,
            "size_word_value": self.size_word_value,
            "tag_id": self.tag_id,
            "tag_id_hex": f"0x{self.tag_id:08x}",
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class NikonCaptureBlockSizeRewrite:
    size_field_range: NikonCaptureByteRange
    old_declared_size: int
    planned_declared_size: int
    rewrite_required: bool
    legacy_size_normalized: bool
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "legacy_size_normalized": self.legacy_size_normalized,
            "old_declared_size": self.old_declared_size,
            "planned_declared_size": self.planned_declared_size,
            "rewrite_required": self.rewrite_required,
            "size_field_range": self.size_field_range.to_json(),
        }


@dataclass(frozen=True)
class NikonCaptureMakerNoteReinsertionGate:
    kind: NikonCaptureReinsertionGateKind
    satisfied: bool
    description: str
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "description": self.description,
            "kind": self.kind,
            "satisfied": self.satisfied,
        }


@dataclass(frozen=True)
class NikonCaptureMakerNoteReinsertionPlan:
    can_reinsert: bool
    parent_directory: str
    source_tag: str
    source_tag_id: int
    write_proc: str
    gates: tuple[NikonCaptureMakerNoteReinsertionGate, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_reinsert": self.can_reinsert,
            "gates": [gate.to_json() for gate in self.gates],
            "parent_directory": self.parent_directory,
            "source_tag": self.source_tag,
            "source_tag_id": self.source_tag_id,
            "source_tag_id_hex": f"0x{self.source_tag_id:04x}",
            "write_proc": self.write_proc,
        }


@dataclass(frozen=True)
class NikonCaptureRebuildPlan:
    status: NikonCaptureRebuildPlanStatus
    can_mutate: bool
    header: NikonCaptureHeaderValidation | None
    operations: tuple[NikonCaptureRebuildOperation, ...]
    block_size_rewrite: NikonCaptureBlockSizeRewrite | None
    maker_note_reinsertion: NikonCaptureMakerNoteReinsertionPlan
    unsupported_reason: str | None
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "block_size_rewrite": (
                self.block_size_rewrite.to_json() if self.block_size_rewrite is not None else None
            ),
            "can_mutate": self.can_mutate,
            "header": self.header.to_json() if self.header is not None else None,
            "maker_note_reinsertion": self.maker_note_reinsertion.to_json(),
            "operations": [operation.to_json() for operation in self.operations],
            "status": self.status,
            "unsupported_reason": self.unsupported_reason,
        }


@dataclass(frozen=True)
class NikonCaptureBlockEmission:
    status: NikonCaptureBlockEmissionStatus
    plan: NikonCaptureRebuildPlan
    rebuilt_block: bytes | None
    deferred_container_blockers: tuple[NikonCaptureReinsertionGateKind, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "deferred_container_blockers": list(self.deferred_container_blockers),
            "emitted_size": len(self.rebuilt_block) if self.rebuilt_block is not None else None,
            "plan": self.plan.to_json(),
            "status": self.status,
        }


@dataclass(frozen=True)
class NikonCapturePreviewOffsetPairProtectionPlan:
    status: NikonCapturePreviewOffsetPairProtectionStatus
    can_satisfy_reinsertion_gate: bool
    preview_ifd_pointer_value: int | None
    preview_ifd_offset: int | None
    preview_offset_pairs: tuple[NikonNefMakerNotePreviewOffsetPair, ...]
    blockers: tuple[str, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "blockers": list(self.blockers),
            "can_satisfy_reinsertion_gate": self.can_satisfy_reinsertion_gate,
            "preview_ifd_offset": self.preview_ifd_offset,
            "preview_ifd_pointer_value": self.preview_ifd_pointer_value,
            "preview_offset_pairs": [pair.to_json() for pair in self.preview_offset_pairs],
            "status": self.status,
        }


@dataclass(frozen=True)
class NikonCaptureIptcDataset:
    record: int
    dataset: int
    entry_range: NikonCaptureByteRange
    value_range: NikonCaptureByteRange
    value_length: int
    uses_extended_length: bool

    def to_json(self) -> JsonObject:
        return {
            "dataset": self.dataset,
            "entry_range": self.entry_range.to_json(),
            "record": self.record,
            "uses_extended_length": self.uses_extended_length,
            "value_length": self.value_length,
            "value_range": self.value_range.to_json(),
        }


@dataclass(frozen=True)
class NikonCaptureIptcRewriteOperation:
    action: NikonCaptureIptcEntryAction
    record: int
    dataset: int
    original_entry_range: NikonCaptureByteRange | None
    planned_output_range: NikonCaptureByteRange
    original_value_length: int | None
    replacement_value_length: int | None
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "dataset": self.dataset,
            "original_entry_range": (
                self.original_entry_range.to_json()
                if self.original_entry_range is not None
                else None
            ),
            "original_value_length": self.original_value_length,
            "planned_output_range": self.planned_output_range.to_json(),
            "record": self.record,
            "replacement_value_length": self.replacement_value_length,
        }


@dataclass(frozen=True)
class NikonCaptureIptcPayloadEmission:
    status: NikonCaptureIptcPayloadEmissionStatus
    rebuilt_payload: bytes | None
    operations: tuple[NikonCaptureIptcRewriteOperation, ...]
    unsupported_reason: str | None
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "emitted_size": len(self.rebuilt_payload) if self.rebuilt_payload is not None else None,
            "operations": [operation.to_json() for operation in self.operations],
            "rebuilt_payload_available": self.rebuilt_payload is not None,
            "status": self.status,
            "unsupported_reason": self.unsupported_reason,
        }


@dataclass(frozen=True)
class NikonNefCaptureIptcRewriteEmission:
    status: NikonNefCaptureIptcRewriteEmissionStatus
    discovery: NikonNefNikonCaptureDiscoveryPlan
    iptc_payload_emission: NikonCaptureIptcPayloadEmission | None
    capture_block_emission: NikonCaptureBlockEmission | None
    unsupported_reason: str | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def rebuilt_capture_block(self) -> bytes | None:
        if self.capture_block_emission is None:
            return None
        return self.capture_block_emission.rebuilt_block

    def to_json(self) -> JsonObject:
        return {
            "capture_block_emission": (
                self.capture_block_emission.to_json()
                if self.capture_block_emission is not None
                else None
            ),
            "discovery": self.discovery.to_json(),
            "emitted_size": (
                len(self.rebuilt_capture_block) if self.rebuilt_capture_block is not None else None
            ),
            "iptc_payload_emission": (
                self.iptc_payload_emission.to_json()
                if self.iptc_payload_emission is not None
                else None
            ),
            "rebuilt_capture_block_available": self.rebuilt_capture_block is not None,
            "status": self.status,
            "unsupported_reason": self.unsupported_reason,
        }


def build_nikon_capture_rebuild_plan(
    data: bytes,
    replacements: tuple[NikonCaptureEntryReplacement, ...] = (),
    *,
    dir_start: int = 0,
    dir_len: int | None = None,
) -> NikonCaptureRebuildPlan:
    """Build a dry-run plan for ExifTool-style NikonCaptureData rebuilding."""

    effective_dir_len = len(data) - dir_start if dir_len is None else dir_len
    reinsertion = build_maker_note_reinsertion_plan()
    evidence_ids = nikon_capture_rebuild_evidence_ids()
    header = validate_nikon_capture_header(data, dir_start, effective_dir_len)
    if header is None:
        return unsupported_capture_plan(
            reinsertion=reinsertion,
            evidence_ids=evidence_ids,
            reason="invalid_nikon_capture_header",
        )

    replacement_by_tag_id = map_replacements_by_tag_id(replacements)
    if replacement_by_tag_id is None:
        return unsupported_capture_plan(
            reinsertion=reinsertion,
            evidence_ids=evidence_ids,
            reason="unsupported_replacement_tag_or_writer",
        )

    enumerated = enumerate_nikon_capture_rebuild_operations(
        data=data,
        dir_start=dir_start,
        header=header,
        replacements=replacement_by_tag_id,
    )
    if enumerated is None:
        return unsupported_capture_plan(
            reinsertion=reinsertion,
            evidence_ids=evidence_ids,
            reason="malformed_nikon_capture_entries",
        )

    operations, planned_outbuff_length = enumerated
    if not replacement_targets_are_present(replacement_by_tag_id, operations):
        return unsupported_capture_plan(
            reinsertion=reinsertion,
            evidence_ids=evidence_ids,
            reason="replacement_target_not_present",
        )

    planned_declared_size = planned_outbuff_length + NIKON_CAPTURE_ENTRY_SIZE_BIAS
    block_size_rewrite = NikonCaptureBlockSizeRewrite(
        size_field_range=header.size_field_range,
        old_declared_size=header.declared_size,
        planned_declared_size=planned_declared_size,
        rewrite_required=planned_declared_size != header.declared_size,
        legacy_size_normalized=header.legacy_size_includes_header,
        evidence_ids=(NIKON_CAPTURE_WRITE_SOURCE,),
    )
    return NikonCaptureRebuildPlan(
        status="source_mapped_non_mutating",
        can_mutate=False,
        header=header,
        operations=operations,
        block_size_rewrite=block_size_rewrite,
        maker_note_reinsertion=reinsertion,
        unsupported_reason=None,
        evidence_ids=evidence_ids,
    )


def emit_nikon_capture_rebuilt_block(
    data: bytes,
    replacements: tuple[NikonCaptureEntryReplacement, ...] = (),
    *,
    dir_start: int = 0,
    dir_len: int | None = None,
) -> NikonCaptureBlockEmission:
    """Emit a rebuilt NikonCaptureData block without reinserting it into NEF bytes."""

    plan = build_nikon_capture_rebuild_plan(
        data,
        replacements,
        dir_start=dir_start,
        dir_len=dir_len,
    )
    if (
        plan.status != "source_mapped_non_mutating"
        or plan.header is None
        or plan.block_size_rewrite is None
    ):
        return NikonCaptureBlockEmission(
            status="unsupported",
            plan=plan,
            rebuilt_block=None,
            deferred_container_blockers=(),
            evidence_ids=plan.evidence_ids,
        )

    replacement_by_tag_id = map_replacements_by_tag_id(replacements)
    if replacement_by_tag_id is None:
        return NikonCaptureBlockEmission(
            status="unsupported",
            plan=plan,
            rebuilt_block=None,
            deferred_container_blockers=(),
            evidence_ids=plan.evidence_ids,
        )

    outbuff = build_nikon_capture_outbuff(
        data=data,
        header=plan.header,
        operations=plan.operations,
        replacements=replacement_by_tag_id,
    )
    rebuilt_block = (
        data[
            plan.header.fixed_header_range.start_offset : plan.header.fixed_header_range.end_offset
        ]
        + plan.block_size_rewrite.planned_declared_size.to_bytes(4, "little")
        + outbuff
        + nikon_capture_trailing_padding(data, plan.header)
    )
    return NikonCaptureBlockEmission(
        status="emitted_nikon_capture_block",
        plan=plan,
        rebuilt_block=rebuilt_block,
        deferred_container_blockers=tuple(
            gate.kind for gate in plan.maker_note_reinsertion.gates if not gate.satisfied
        ),
        evidence_ids=unique_evidence_ids(
            (
                NIKON_CAPTURE_WRITE_SOURCE,
                WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
                WRITE_EXIF_REBUILD_MAKERNOTES_SOURCE,
                WRITE_EXIF_VALUE_FIXUP_SOURCE,
                NIKON_PREVIEW_IFD_SOURCE,
            )
        ),
    )


def resolve_nikon_capture_reinsertion_gates(
    emission: NikonCaptureBlockEmission,
    satisfied_gates: tuple[NikonCaptureReinsertionGateKind, ...],
) -> NikonCaptureBlockEmission:
    """Mark source-backed outer MakerNote reinsertion gates satisfied.

    NikonCapture block emission is intentionally separate from NEF/TIFF
    reinsertion.  The raw writer calls this only after the corresponding
    Type2 MakerNote and WriteExif-style handoff evidence has been emitted by
    package-local Nikon NEF primitives.
    """

    if not satisfied_gates:
        return emission

    satisfied_gate_set = set(satisfied_gates)
    existing_plan = emission.plan.maker_note_reinsertion
    gates = tuple(
        NikonCaptureMakerNoteReinsertionGate(
            kind=gate.kind,
            satisfied=gate.satisfied or gate.kind in satisfied_gate_set,
            description=gate.description,
            evidence_ids=gate.evidence_ids,
        )
        for gate in existing_plan.gates
    )
    reinsertion = NikonCaptureMakerNoteReinsertionPlan(
        can_reinsert=all(gate.satisfied for gate in gates),
        parent_directory=existing_plan.parent_directory,
        source_tag=existing_plan.source_tag,
        source_tag_id=existing_plan.source_tag_id,
        write_proc=existing_plan.write_proc,
        gates=gates,
        evidence_ids=unique_evidence_ids(
            tuple(reference for gate in gates for reference in gate.evidence_ids)
        ),
    )
    plan = NikonCaptureRebuildPlan(
        status=emission.plan.status,
        can_mutate=emission.plan.can_mutate,
        header=emission.plan.header,
        operations=emission.plan.operations,
        block_size_rewrite=emission.plan.block_size_rewrite,
        maker_note_reinsertion=reinsertion,
        unsupported_reason=emission.plan.unsupported_reason,
        evidence_ids=unique_evidence_ids((*emission.plan.evidence_ids, *reinsertion.evidence_ids)),
    )
    return NikonCaptureBlockEmission(
        status=emission.status,
        plan=plan,
        rebuilt_block=emission.rebuilt_block,
        deferred_container_blockers=tuple(gate.kind for gate in gates if not gate.satisfied),
        evidence_ids=unique_evidence_ids((*emission.evidence_ids, *reinsertion.evidence_ids)),
    )


def build_nikon_capture_preview_offset_pair_protection_plan(
    data: bytes,
    maker_note_directory: NikonNefMakerNoteDirectoryLocation | None,
    *,
    offset_fixups_applied: bool,
) -> NikonCapturePreviewOffsetPairProtectionPlan:
    """Prove the Nikon PreviewIFD offset pair is either absent or protected.

    ExifTool routes Nikon MakerNote tag 0x0011 to PreviewIFD, where
    PreviewImageStart and PreviewImageLength are a protected offset/data pair.
    This proof only satisfies the capture reinsertion gate after the existing
    WriteExif-style offset fixup seam has materialized final offsets.
    """

    evidence_ids = unique_evidence_ids(
        (
            NIKON_PREVIEW_IFD_POINTER_SOURCE,
            NIKON_PREVIEW_IFD_SOURCE,
            WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
        )
    )
    if maker_note_directory is None:
        return unsupported_preview_offset_pair_protection_plan(
            "requires_nikon_type2_makernote_ifd",
            evidence_ids,
        )

    pointer = find_nikon_preview_ifd_pointer(data, maker_note_directory)
    if pointer is None:
        return NikonCapturePreviewOffsetPairProtectionPlan(
            status="source_mapped_absent",
            can_satisfy_reinsertion_gate=True,
            preview_ifd_pointer_value=None,
            preview_ifd_offset=None,
            preview_offset_pairs=(),
            blockers=(),
            evidence_ids=evidence_ids,
        )

    preview_ifd_pointer_value, preview_ifd_offset = pointer
    pair = find_nikon_preview_offset_pair(data, maker_note_directory, preview_ifd_offset)
    if pair is None:
        return unsupported_preview_offset_pair_protection_plan(
            "requires_complete_preview_ifd_offset_pair",
            evidence_ids,
            preview_ifd_pointer_value=preview_ifd_pointer_value,
            preview_ifd_offset=preview_ifd_offset,
        )
    if not offset_fixups_applied:
        return NikonCapturePreviewOffsetPairProtectionPlan(
            status="unsupported",
            can_satisfy_reinsertion_gate=False,
            preview_ifd_pointer_value=preview_ifd_pointer_value,
            preview_ifd_offset=preview_ifd_offset,
            preview_offset_pairs=(pair,),
            blockers=("requires_writeexif_offset_fixup_application",),
            evidence_ids=evidence_ids,
        )
    return NikonCapturePreviewOffsetPairProtectionPlan(
        status="source_mapped_protected",
        can_satisfy_reinsertion_gate=True,
        preview_ifd_pointer_value=preview_ifd_pointer_value,
        preview_ifd_offset=preview_ifd_offset,
        preview_offset_pairs=(pair,),
        blockers=(),
        evidence_ids=evidence_ids,
    )


def find_nikon_preview_ifd_pointer(
    data: bytes,
    maker_note_directory: NikonNefMakerNoteDirectoryLocation,
) -> tuple[int, int] | None:
    entries_start = maker_note_directory.ifd_offset + 2
    for index in range(maker_note_directory.ifd_entry_count):
        entry_offset = entries_start + index * TIFF_IFD_ENTRY_SIZE
        if entry_offset + TIFF_IFD_ENTRY_SIZE > len(data):
            return None
        tag_id = read_uint(data, entry_offset, maker_note_directory.byte_order, 2)
        if tag_id != NIKON_PREVIEW_IFD_TAG_ID:
            continue
        pointer_value = read_uint(data, entry_offset + 8, maker_note_directory.byte_order, 4)
        preview_ifd_offset = maker_note_directory.tiff_base_offset + pointer_value
        return (pointer_value, preview_ifd_offset)
    return None


def find_nikon_preview_offset_pair(
    data: bytes,
    maker_note_directory: NikonNefMakerNoteDirectoryLocation,
    preview_ifd_offset: int,
) -> NikonNefMakerNotePreviewOffsetPair | None:
    entry_count = read_ifd_entry_count(data, preview_ifd_offset, maker_note_directory.byte_order)
    if entry_count is None:
        return None
    entries_start = preview_ifd_offset + 2
    entries_end = entries_start + entry_count * TIFF_IFD_ENTRY_SIZE
    if entries_end + 4 > len(data):
        return None

    start_value_field_offset: int | None = None
    length_value_field_offset: int | None = None
    start_value: int | None = None
    length_value: int | None = None
    for index in range(entry_count):
        entry_offset = entries_start + index * TIFF_IFD_ENTRY_SIZE
        tag_id = read_uint(data, entry_offset, maker_note_directory.byte_order, 2)
        value_field_offset = entry_offset + 8
        value = read_uint(data, value_field_offset, maker_note_directory.byte_order, 4)
        if tag_id == NIKON_PREVIEW_IMAGE_START_TAG_ID:
            start_value_field_offset = value_field_offset
            start_value = value
        elif tag_id == NIKON_PREVIEW_IMAGE_LENGTH_TAG_ID:
            length_value_field_offset = value_field_offset
            length_value = value

    if (
        start_value_field_offset is None
        or length_value_field_offset is None
        or start_value is None
        or length_value is None
    ):
        return None
    return NikonNefMakerNotePreviewOffsetPair(
        data_tag="PreviewImage",
        start_tag=NIKON_PREVIEW_IMAGE_START_TAG_ID,
        length_tag=NIKON_PREVIEW_IMAGE_LENGTH_TAG_ID,
        start_pointer_offset=(
            start_value_field_offset - maker_note_directory.tiff_header_range.start_offset
        ),
        length_pointer_offset=(
            length_value_field_offset - maker_note_directory.tiff_header_range.start_offset
        ),
        start_value=start_value,
        length_value=length_value,
        marker_carried_forward=True,
        protected_by_preview_ifd=True,
        evidence_ids=unique_evidence_ids(
            (NIKON_PREVIEW_IFD_POINTER_SOURCE, NIKON_PREVIEW_IFD_SOURCE)
        ),
    )


def unsupported_preview_offset_pair_protection_plan(
    blocker: str,
    evidence_ids: tuple[EvidenceId, ...],
    *,
    preview_ifd_pointer_value: int | None = None,
    preview_ifd_offset: int | None = None,
) -> NikonCapturePreviewOffsetPairProtectionPlan:
    return NikonCapturePreviewOffsetPairProtectionPlan(
        status="unsupported",
        can_satisfy_reinsertion_gate=False,
        preview_ifd_pointer_value=preview_ifd_pointer_value,
        preview_ifd_offset=preview_ifd_offset,
        preview_offset_pairs=(),
        blockers=(blocker,),
        evidence_ids=evidence_ids,
    )


def emit_nikon_capture_iptc_caption_payload(
    data: bytes,
    caption_abstract_payload: bytes,
    *,
    dir_start: int = 0,
    dir_len: int | None = None,
) -> NikonCaptureIptcPayloadEmission:
    """Emit an IPTC payload for NikonCapture IPTCData Caption-Abstract rewrites."""

    evidence_ids = (IPTC_CAPTION_ABSTRACT_SOURCE, WRITE_IPTC_SOURCE)
    effective_dir_len = len(data) - dir_start if dir_len is None else dir_len
    if dir_start < 0 or effective_dir_len < 0 or dir_start + effective_dir_len > len(data):
        return unsupported_iptc_payload_emission(
            "invalid_iptc_directory_bounds",
            evidence_ids,
        )
    if len(caption_abstract_payload) > IPTC_CAPTION_ABSTRACT_MAX_LENGTH:
        return unsupported_iptc_payload_emission(
            "caption_abstract_exceeds_iptc_string_limit",
            evidence_ids,
        )

    datasets = parse_iptc_datasets(data, dir_start, effective_dir_len)
    if datasets is None:
        return unsupported_iptc_payload_emission(
            "malformed_iptc_payload",
            evidence_ids,
        )

    rebuilt_payload, operations = rebuild_iptc_caption_payload(
        data,
        datasets,
        caption_abstract_payload,
        dir_start,
    )
    return NikonCaptureIptcPayloadEmission(
        status="emitted_iptc_payload",
        rebuilt_payload=rebuilt_payload,
        operations=operations,
        unsupported_reason=None,
        evidence_ids=evidence_ids,
    )


def emit_nef_nikon_capture_caption_abstract_rebuilt_block(
    data: bytes,
    caption_abstract_payload: bytes,
) -> NikonNefCaptureIptcRewriteEmission:
    """Discover NEF NikonCapture/IPTC entries and emit the rebuilt Capture block.

    The returned bytes are only the replacement NikonCaptureData value. Full NEF
    reinsertion still depends on MakerNote and TIFF value-position fixups.
    """

    discovery = build_nikon_nef_nikon_capture_discovery_plan(data)
    evidence_ids = unique_evidence_ids(
        (
            *discovery.evidence_ids,
            IPTC_CAPTION_ABSTRACT_SOURCE,
            WRITE_IPTC_SOURCE,
            NIKON_CAPTURE_WRITE_SOURCE,
            WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
        )
    )
    if discovery.capture_entry is None:
        return NikonNefCaptureIptcRewriteEmission(
            status="unsupported",
            discovery=discovery,
            iptc_payload_emission=None,
            capture_block_emission=None,
            unsupported_reason="missing_nikon_capture_data_entry",
            evidence_ids=evidence_ids,
        )
    if discovery.iptc_entry is None:
        return NikonNefCaptureIptcRewriteEmission(
            status="unsupported",
            discovery=discovery,
            iptc_payload_emission=None,
            capture_block_emission=None,
            unsupported_reason="missing_nikon_capture_iptc_entry",
            evidence_ids=evidence_ids,
        )

    iptc_payload_emission = emit_nikon_capture_iptc_caption_payload(
        data,
        caption_abstract_payload,
        dir_start=discovery.iptc_entry.value_range.start_offset,
        dir_len=discovery.iptc_entry.value_range.length,
    )
    if iptc_payload_emission.rebuilt_payload is None:
        return NikonNefCaptureIptcRewriteEmission(
            status="unsupported",
            discovery=discovery,
            iptc_payload_emission=iptc_payload_emission,
            capture_block_emission=None,
            unsupported_reason=iptc_payload_emission.unsupported_reason,
            evidence_ids=evidence_ids,
        )

    capture_block_emission = emit_nikon_capture_rebuilt_block(
        data,
        (
            NikonCaptureEntryReplacement(
                tag_name="IPTCData",
                writer="iptc_subdirectory",
                payload=iptc_payload_emission.rebuilt_payload,
            ),
        ),
        dir_start=discovery.capture_entry.value_range.start_offset,
        dir_len=discovery.capture_entry.value_range.length,
    )
    if capture_block_emission.rebuilt_block is None:
        return NikonNefCaptureIptcRewriteEmission(
            status="unsupported",
            discovery=discovery,
            iptc_payload_emission=iptc_payload_emission,
            capture_block_emission=capture_block_emission,
            unsupported_reason=capture_block_emission.plan.unsupported_reason,
            evidence_ids=evidence_ids,
        )

    return NikonNefCaptureIptcRewriteEmission(
        status="emitted_nef_nikon_capture_block",
        discovery=discovery,
        iptc_payload_emission=iptc_payload_emission,
        capture_block_emission=capture_block_emission,
        unsupported_reason=None,
        evidence_ids=evidence_ids,
    )


def validate_nikon_capture_header(
    data: bytes,
    dir_start: int,
    dir_len: int,
) -> NikonCaptureHeaderValidation | None:
    if dir_start < 0 or dir_len < NIKON_CAPTURE_HEADER_SIZE:
        return None
    dir_end = dir_start + dir_len
    if dir_end > len(data):
        return None

    tag_id = read_uint32_le(data, dir_start)
    declared_size = read_uint32_le(data, dir_start + NIKON_CAPTURE_FIXED_HEADER_SIZE)
    pad_length = dir_len - declared_size - NIKON_CAPTURE_FIXED_HEADER_SIZE
    if tag_id != NIKON_CAPTURE_MAGIC or not (pad_length >= 0 or pad_length == -18):
        return None

    if pad_length > 0:
        effective_directory_length = declared_size + NIKON_CAPTURE_FIXED_HEADER_SIZE
        padding_start = dir_start + effective_directory_length
        trailing_padding_range = NikonCaptureByteRange(padding_start, dir_end)
    else:
        effective_directory_length = dir_len
        trailing_padding_range = None
        pad_length = 0

    return NikonCaptureHeaderValidation(
        block_range=NikonCaptureByteRange(dir_start, dir_end),
        fixed_header_range=NikonCaptureByteRange(
            dir_start,
            dir_start + NIKON_CAPTURE_FIXED_HEADER_SIZE,
        ),
        size_field_range=NikonCaptureByteRange(
            dir_start + NIKON_CAPTURE_FIXED_HEADER_SIZE,
            dir_start + NIKON_CAPTURE_HEADER_SIZE,
        ),
        tag_id=tag_id,
        declared_size=declared_size,
        effective_directory_length=effective_directory_length,
        trailing_padding_range=trailing_padding_range,
        trailing_padding_length=pad_length,
        legacy_size_includes_header=dir_len - declared_size - NIKON_CAPTURE_FIXED_HEADER_SIZE
        == -18,
        evidence_ids=(NIKON_CAPTURE_WRITE_SOURCE,),
    )


def enumerate_nikon_capture_rebuild_operations(
    data: bytes,
    dir_start: int,
    header: NikonCaptureHeaderValidation,
    replacements: dict[int, NikonCaptureEntryReplacement],
) -> tuple[tuple[NikonCaptureRebuildOperation, ...], int] | None:
    operations: list[NikonCaptureRebuildOperation] = []
    dir_end = dir_start + header.effective_directory_length
    input_position = dir_start + NIKON_CAPTURE_HEADER_SIZE
    output_position = dir_start + NIKON_CAPTURE_HEADER_SIZE
    index = 0

    while input_position + NIKON_CAPTURE_ENTRY_HEADER_SIZE < dir_end:
        size_word_offset = input_position + NIKON_CAPTURE_ENTRY_PREFIX_SIZE
        tag_id = read_uint32_le(data, input_position)
        size_word_value = read_uint32_le(data, size_word_offset)
        original_value_length = size_word_value - NIKON_CAPTURE_ENTRY_SIZE_BIAS
        if size_word_value < NIKON_CAPTURE_ENTRY_SIZE_BIAS:
            return None
        original_value_start = input_position + NIKON_CAPTURE_ENTRY_HEADER_SIZE
        original_value_end = original_value_start + original_value_length
        if original_value_end > dir_end:
            return None

        operation = build_nikon_capture_rebuild_operation(
            index=index,
            tag_id=tag_id,
            original_entry_range=NikonCaptureByteRange(input_position, original_value_end),
            original_value_range=NikonCaptureByteRange(original_value_start, original_value_end),
            original_value_length=original_value_length,
            planned_output_offset=output_position,
            replacement=replacements.get(tag_id),
            trailing_padding_length=header.trailing_padding_length,
        )
        operations.append(operation)
        input_position = original_value_end
        output_position = operation.planned_output_range.end_offset
        index += 1

    if input_position == dir_end:
        return tuple(operations), output_position - dir_start - NIKON_CAPTURE_HEADER_SIZE
    if input_position == dir_end - NIKON_CAPTURE_ENTRY_SIZE_FIELD_SIZE:
        # NikonCapture.pm copies this four-byte NX2 terminator into the rebuilt outBuff.
        return (
            tuple(operations),
            output_position - dir_start - NIKON_CAPTURE_HEADER_SIZE + 4,
        )
    return None


def build_nikon_capture_outbuff(
    data: bytes,
    header: NikonCaptureHeaderValidation,
    operations: tuple[NikonCaptureRebuildOperation, ...],
    replacements: dict[int, NikonCaptureEntryReplacement],
) -> bytes:
    chunks: list[bytes] = []
    for operation in operations:
        if operation.action == "drop_empty_subdirectory":
            continue
        replacement = replacements.get(operation.tag_id)
        if replacement is None:
            chunks.append(
                data[
                    operation.original_entry_range.start_offset : (
                        operation.original_entry_range.end_offset
                    )
                ]
            )
            continue
        chunks.append(
            data[
                operation.original_entry_range.start_offset : (
                    operation.original_entry_range.start_offset + NIKON_CAPTURE_ENTRY_PREFIX_SIZE
                )
            ]
        )
        chunks.append(operation.size_word_value.to_bytes(4, "little"))
        chunks.append(replacement.payload)

    terminator = nikon_capture_nx2_terminator(data, header, operations)
    if terminator is not None:
        chunks.append(terminator)
    return b"".join(chunks)


def nikon_capture_nx2_terminator(
    data: bytes,
    header: NikonCaptureHeaderValidation,
    operations: tuple[NikonCaptureRebuildOperation, ...],
) -> bytes | None:
    dir_end = header.block_range.start_offset + header.effective_directory_length
    last_input_position = (
        operations[-1].original_entry_range.end_offset
        if operations
        else header.block_range.start_offset + NIKON_CAPTURE_HEADER_SIZE
    )
    if last_input_position != dir_end - NIKON_CAPTURE_ENTRY_SIZE_FIELD_SIZE:
        return None
    return data[last_input_position:dir_end]


def nikon_capture_trailing_padding(
    data: bytes,
    header: NikonCaptureHeaderValidation,
) -> bytes:
    if header.trailing_padding_range is None:
        return b""
    return data[
        header.trailing_padding_range.start_offset : header.trailing_padding_range.end_offset
    ]


def build_nikon_capture_rebuild_operation(
    index: int,
    tag_id: int,
    original_entry_range: NikonCaptureByteRange,
    original_value_range: NikonCaptureByteRange,
    original_value_length: int,
    planned_output_offset: int,
    replacement: NikonCaptureEntryReplacement | None,
    trailing_padding_length: int,
) -> NikonCaptureRebuildOperation:
    tag_spec = NIKON_CAPTURE_TAG_SPECS.get(tag_id)
    tag_name = tag_spec.tag_name if tag_spec is not None else None
    action = nikon_capture_entry_action(tag_id, replacement)
    replacement_value_length = len(replacement.payload) if replacement is not None else None
    if replacement is None:
        planned_value_length = original_value_length
    elif action == "drop_empty_subdirectory":
        planned_value_length = 0
    else:
        planned_value_length = len(replacement.payload)

    planned_entry_length = (
        0
        if action == "drop_empty_subdirectory"
        else NIKON_CAPTURE_ENTRY_HEADER_SIZE + planned_value_length
    )
    planned_output_range = NikonCaptureByteRange(
        planned_output_offset,
        planned_output_offset + planned_entry_length,
    )
    return NikonCaptureRebuildOperation(
        index=index,
        tag_id=tag_id,
        tag_name=tag_name,
        action=action,
        original_entry_range=original_entry_range,
        original_value_range=original_value_range,
        planned_output_range=planned_output_range,
        original_value_length=original_value_length,
        replacement_value_length=replacement_value_length,
        planned_value_length=planned_value_length,
        size_word_value=planned_value_length + NIKON_CAPTURE_ENTRY_SIZE_BIAS,
        padding=NikonCapturePaddingDecision(
            entry_value_padding_length=0,
            trailing_padding_length=trailing_padding_length,
            preserves_original_trailing_padding=True,
            policy=(
                "NikonCapture values are copied at exact length; only block trailing pad "
                "is preserved."
            ),
        ),
        evidence_ids=operation_evidence_ids(tag_id, replacement),
    )


def nikon_capture_entry_action(
    tag_id: int,
    replacement: NikonCaptureEntryReplacement | None,
) -> NikonCaptureEntryAction:
    if replacement is None:
        return "copy_existing_entry" if tag_id in NIKON_CAPTURE_TAG_SPECS else "copy_unknown_entry"
    if replacement.writer == "iptc_subdirectory" and not replacement.payload:
        return "drop_empty_subdirectory"
    if replacement.writer == "iptc_subdirectory":
        return "rewrite_iptc_subdirectory"
    return "rewrite_scalar_entry"


def map_replacements_by_tag_id(
    replacements: tuple[NikonCaptureEntryReplacement, ...],
) -> dict[int, NikonCaptureEntryReplacement] | None:
    mapped: dict[int, NikonCaptureEntryReplacement] = {}
    for replacement in replacements:
        tag_id = NIKON_CAPTURE_TAG_IDS_BY_NAME.get(replacement.tag_name)
        if tag_id is None:
            return None
        expected_writer = NIKON_CAPTURE_TAG_SPECS[tag_id].writer
        if replacement.writer != expected_writer or tag_id in mapped:
            return None
        if replacement.writer == "scalar_value" and not replacement.payload:
            return None
        mapped[tag_id] = replacement
    return mapped


def replacement_targets_are_present(
    replacements: dict[int, NikonCaptureEntryReplacement],
    operations: tuple[NikonCaptureRebuildOperation, ...],
) -> bool:
    found_tag_ids = {operation.tag_id for operation in operations}
    return all(tag_id in found_tag_ids for tag_id in replacements)


def build_maker_note_reinsertion_plan() -> NikonCaptureMakerNoteReinsertionPlan:
    gates = (
        NikonCaptureMakerNoteReinsertionGate(
            kind="requires_existing_nikon_type2_makernote",
            satisfied=False,
            description=(
                "NikonCaptureData must be rewritten inside an existing Nikon Type2 MakerNote."
            ),
            evidence_ids=(WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,),
        ),
        NikonCaptureMakerNoteReinsertionGate(
            kind="requires_writeexif_makernote_subdirectory_handoff",
            satisfied=False,
            description="WriteExif must delegate tag 0x0e01 through WriteDirectory.",
            evidence_ids=(WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,),
        ),
        NikonCaptureMakerNoteReinsertionGate(
            kind="requires_nikon_capture_write_directory_result",
            satisfied=False,
            description="WriteNikonCapture must return a non-empty rebuilt subdirectory.",
            evidence_ids=(NIKON_CAPTURE_WRITE_SOURCE,),
        ),
        NikonCaptureMakerNoteReinsertionGate(
            kind="requires_makernote_fixup_collection",
            satisfied=False,
            description=(
                "MakerNote value fixups must be collected before TIFF value data is emitted."
            ),
            evidence_ids=(WRITE_EXIF_VALUE_FIXUP_SOURCE, WRITE_EXIF_REBUILD_MAKERNOTES_SOURCE),
        ),
        NikonCaptureMakerNoteReinsertionGate(
            kind="requires_preview_offset_pair_protection",
            satisfied=False,
            description=(
                "PreviewImageStart and PreviewImageLength must remain paired during reinsertion."
            ),
            evidence_ids=(NIKON_PREVIEW_IFD_SOURCE,),
        ),
    )
    sources = unique_evidence_ids(
        tuple(reference for gate in gates for reference in gate.evidence_ids)
    )
    return NikonCaptureMakerNoteReinsertionPlan(
        can_reinsert=False,
        parent_directory="MakerNotes",
        source_tag="NikonCaptureData",
        source_tag_id=0x0E01,
        write_proc="Image::ExifTool::Exif::WriteExif",
        gates=gates,
        evidence_ids=sources,
    )


def operation_evidence_ids(
    tag_id: int,
    replacement: NikonCaptureEntryReplacement | None,
) -> tuple[EvidenceId, ...]:
    references: list[EvidenceId] = [NIKON_CAPTURE_WRITE_SOURCE]
    if tag_id in NIKON_CAPTURE_TAG_SPECS:
        references.append(NIKON_CAPTURE_TAGS_SOURCE)
    if replacement is not None:
        references.append(NIKON_CAPTURE_TAGS_SOURCE)
        if replacement.writer == "iptc_subdirectory":
            references.append(IPTC_CAPTION_ABSTRACT_SOURCE)
    return unique_evidence_ids(tuple(references))


def unsupported_capture_plan(
    reinsertion: NikonCaptureMakerNoteReinsertionPlan,
    evidence_ids: tuple[EvidenceId, ...],
    reason: str,
) -> NikonCaptureRebuildPlan:
    return NikonCaptureRebuildPlan(
        status="unsupported",
        can_mutate=False,
        header=None,
        operations=(),
        block_size_rewrite=None,
        maker_note_reinsertion=reinsertion,
        unsupported_reason=reason,
        evidence_ids=evidence_ids,
    )


def nikon_capture_rebuild_evidence_ids() -> tuple[EvidenceId, ...]:
    return unique_evidence_ids(
        (
            NIKON_CAPTURE_TAGS_SOURCE,
            NIKON_CAPTURE_WRITE_SOURCE,
            IPTC_CAPTION_ABSTRACT_SOURCE,
            WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
            WRITE_EXIF_REBUILD_MAKERNOTES_SOURCE,
            WRITE_EXIF_VALUE_FIXUP_SOURCE,
            WRITE_EXIF_MAKERNOTE_PADDING_SOURCE,
            NIKON_PREVIEW_IFD_SOURCE,
        )
    )


def read_uint32_le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def parse_iptc_datasets(
    data: bytes,
    dir_start: int,
    dir_len: int,
) -> tuple[NikonCaptureIptcDataset, ...] | None:
    datasets: list[NikonCaptureIptcDataset] = []
    pos = dir_start
    dir_end = dir_start + dir_len
    last_record = -1
    while pos + IPTC_SHORT_HEADER_SIZE <= dir_end:
        marker = data[pos]
        if marker != IPTC_MARKER:
            return tuple(datasets) if not data[pos:dir_end].strip(b"\0") else None
        record = data[pos + 1]
        dataset = data[pos + 2]
        if record < last_record:
            return None
        last_record = record
        length_word = int.from_bytes(data[pos + 3 : pos + 5], "big")
        value_start = pos + IPTC_SHORT_HEADER_SIZE
        uses_extended_length = bool(length_word & 0x8000)
        if uses_extended_length:
            length_byte_count = length_word & 0x7FFF
            if length_byte_count > 8 or value_start + length_byte_count > dir_end:
                return None
            value_length = int.from_bytes(
                data[value_start : value_start + length_byte_count],
                "big",
            )
            value_start += length_byte_count
        else:
            value_length = length_word
        value_end = value_start + value_length
        if value_end > dir_end:
            return None
        datasets.append(
            NikonCaptureIptcDataset(
                record=record,
                dataset=dataset,
                entry_range=NikonCaptureByteRange(pos, value_end),
                value_range=NikonCaptureByteRange(value_start, value_end),
                value_length=value_length,
                uses_extended_length=uses_extended_length,
            )
        )
        pos = value_end
    if data[pos:dir_end].strip(b"\0"):
        return None
    return tuple(datasets)


def rebuild_iptc_caption_payload(
    data: bytes,
    datasets: tuple[NikonCaptureIptcDataset, ...],
    caption_abstract_payload: bytes,
    dir_start: int,
) -> tuple[bytes, tuple[NikonCaptureIptcRewriteOperation, ...]]:
    output = bytearray()
    operations: list[NikonCaptureIptcRewriteOperation] = []
    caption_written = False
    caption_dropped = False
    insert_before_index = iptc_caption_insert_before_index(datasets)

    for index, dataset in enumerate(datasets):
        if index == insert_before_index and not caption_written and caption_abstract_payload:
            operations.append(
                append_iptc_caption_entry(output, caption_abstract_payload, dir_start)
            )
            caption_written = True
        if is_caption_abstract_dataset(dataset):
            if caption_abstract_payload and not caption_written:
                start = len(output) + dir_start
                output.extend(iptc_caption_entry(caption_abstract_payload))
                end = len(output) + dir_start
                operations.append(
                    NikonCaptureIptcRewriteOperation(
                        action="replace_caption_abstract",
                        record=dataset.record,
                        dataset=dataset.dataset,
                        original_entry_range=dataset.entry_range,
                        planned_output_range=NikonCaptureByteRange(start, end),
                        original_value_length=dataset.value_length,
                        replacement_value_length=len(caption_abstract_payload),
                        evidence_ids=(IPTC_CAPTION_ABSTRACT_SOURCE, WRITE_IPTC_SOURCE),
                    )
                )
                caption_written = True
            else:
                operations.append(
                    NikonCaptureIptcRewriteOperation(
                        action="drop_caption_abstract",
                        record=dataset.record,
                        dataset=dataset.dataset,
                        original_entry_range=dataset.entry_range,
                        planned_output_range=NikonCaptureByteRange(
                            len(output) + dir_start,
                            len(output) + dir_start,
                        ),
                        original_value_length=dataset.value_length,
                        replacement_value_length=(
                            len(caption_abstract_payload) if not caption_dropped else None
                        ),
                        evidence_ids=(IPTC_CAPTION_ABSTRACT_SOURCE, WRITE_IPTC_SOURCE),
                    )
                )
                caption_dropped = True
            continue

        start = len(output) + dir_start
        output.extend(data[dataset.entry_range.start_offset : dataset.entry_range.end_offset])
        end = len(output) + dir_start
        operations.append(
            NikonCaptureIptcRewriteOperation(
                action="copy_existing_dataset",
                record=dataset.record,
                dataset=dataset.dataset,
                original_entry_range=dataset.entry_range,
                planned_output_range=NikonCaptureByteRange(start, end),
                original_value_length=dataset.value_length,
                replacement_value_length=None,
                evidence_ids=(WRITE_IPTC_SOURCE,),
            )
        )

    if not caption_written and caption_abstract_payload:
        operations.append(append_iptc_caption_entry(output, caption_abstract_payload, dir_start))
    return bytes(output), tuple(operations)


def append_iptc_caption_entry(
    output: bytearray,
    caption_abstract_payload: bytes,
    dir_start: int,
) -> NikonCaptureIptcRewriteOperation:
    start = len(output) + dir_start
    output.extend(iptc_caption_entry(caption_abstract_payload))
    end = len(output) + dir_start
    return NikonCaptureIptcRewriteOperation(
        action="insert_caption_abstract",
        record=IPTC_APPLICATION_RECORD,
        dataset=IPTC_CAPTION_ABSTRACT_DATASET,
        original_entry_range=None,
        planned_output_range=NikonCaptureByteRange(start, end),
        original_value_length=None,
        replacement_value_length=len(caption_abstract_payload),
        evidence_ids=(IPTC_CAPTION_ABSTRACT_SOURCE, WRITE_IPTC_SOURCE),
    )


def iptc_caption_entry(caption_abstract_payload: bytes) -> bytes:
    return (
        bytes((IPTC_MARKER, IPTC_APPLICATION_RECORD, IPTC_CAPTION_ABSTRACT_DATASET))
        + len(caption_abstract_payload).to_bytes(2, "big")
        + caption_abstract_payload
    )


def iptc_caption_insert_before_index(
    datasets: tuple[NikonCaptureIptcDataset, ...],
) -> int | None:
    for index, dataset in enumerate(datasets):
        if dataset.record > IPTC_APPLICATION_RECORD:
            return index
    return None


def is_caption_abstract_dataset(dataset: NikonCaptureIptcDataset) -> bool:
    return (
        dataset.record == IPTC_APPLICATION_RECORD
        and dataset.dataset == IPTC_CAPTION_ABSTRACT_DATASET
    )


def unsupported_iptc_payload_emission(
    reason: str,
    evidence_ids: tuple[EvidenceId, ...],
) -> NikonCaptureIptcPayloadEmission:
    return NikonCaptureIptcPayloadEmission(
        status="unsupported",
        rebuilt_payload=None,
        operations=(),
        unsupported_reason=reason,
        evidence_ids=evidence_ids,
    )
