"""Canon RAW final-emission seam.

The CR2 and CR3 mutation plans expose typed state for the container output
boundary.  This module keeps the planning surface explicit, and also contains
bounded byte emitters that consume already-rebuilt metadata payloads without
creating those payloads themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from exifmodern.formats.canon_raw.container_transaction import (
    CanonRawContainerTransactionPlan,
    plan_canon_raw_container_transaction,
)
from exifmodern.formats.canon_raw.cr2_ifd_staging import stage_cr2_tiff_ifd_mutation
from exifmodern.formats.canon_raw.cr2_mutation_plan import (
    Cr2ImageDataCopySegment,
    plan_cr2_rebuilt_header,
)
from exifmodern.formats.canon_raw.cr3_mutation_plan import (
    CR3_MDAT_BOUNDARY_SOURCE,
    CR3_MDAT_EDIT_SOURCE,
    CR3_UUID_WRITE_SOURCE,
    CR3_WRITE_LAST_SOURCE,
    QUICKTIME_XMP_UUID_SOURCE,
    XMP_UUID_IDENTIFIER,
    Cr3AtomRecord,
    Cr3AtomTreeRecord,
    Cr3CtboOffsetRegistration,
    Cr3UuidAtomBoundary,
    apply_cr3_ctbo_patches_to_rebuilt_stream,
    inspect_cr3_ctbo_atom,
    inspect_cr3_ftyp_brand,
    inspect_cr3_uuid_atom_boundary,
    plan_cr3_ctbo_patches,
    scan_cr3_atom_tree,
    scan_cr3_top_level_atoms,
    unique_sources,
)
from exifmodern.formats.canon_raw.cr3_transaction_ledger import (
    CR3_ATOM_SIZE_UPDATE_SOURCE,
    CR3_CMT_TIFF_PAYLOAD_SOURCE,
    CR3_FINAL_EMIT_SOURCE,
)
from exifmodern.formats.canon_raw.write_plan import (
    CR3_CANON_UUID_SOURCE,
    CR3_CTBO_FIXUP_SOURCE,
    CR3_QUICKTIME_MAP_SOURCE,
    EXIF_EXPOSURE_COMPENSATION_SOURCE,
    WRITE_CR2_SOURCE,
    XMP_DC_SUBJECT_SOURCE,
    XMP_EXIF_EXPOSURE_COMPENSATION_SOURCE,
    CanonRawWriteRequestClassification,
)
from exifmodern.formats.tiff.directory_transaction_plan import (
    THUMBNAIL_LENGTH_TAG,
    THUMBNAIL_OFFSET_TAG,
    TiffDirectoryInput,
    TiffDirectoryRebuildPlan,
    TiffDirectoryTransactionPlan,
    build_tiff_directory_rebuild_plan,
    build_tiff_directory_transaction_plan,
)
from exifmodern.formats.tiff.directory_transaction_plan import (
    unique_sources as unique_tiff_evidence_ids,
)
from exifmodern.formats.tiff.mutation import (
    RawTiffDirectory,
    RawTiffEntry,
    parsed_ifd_data_end,
    raw_directory,
    upsert_raw_entry,
)
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_BYTE,
    TIFF_TYPE_LONG,
    TIFF_TYPE_SHORT,
    TIFF_TYPE_SRATIONAL,
    Endian,
    parse_ifd,
    parse_tiff_header,
)
from exifmodern.formats.tiff.write_exif_value_buffer import (
    WRITE_EXIF_INLINE_IMAGE_DATA_APPEND_SOURCE,
    TiffWriteExifImageDataPlacement,
    TiffWriteExifRebuiltDirectoryPayload,
    build_tiff_write_exif_rebuilt_directory_payload,
)
from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
from exifmodern.formats.xmp.property_write import (
    GENERATED_PROPERTY_SOURCE,
    XMP_PROPERTY_WRITE_SOURCE,
    XmpPropertySpec,
    XmpPropertyWritePlan,
    XmpPropertyWriteStep,
    XmpTextListPropertyWrite,
    XmpTextPropertyWrite,
)
from exifmodern.json_types import JsonObject

type EvidenceId = str
XMP_PROPERTY_WRITE_EVIDENCE_ID = "xmp.property_write_loop"

type CanonRawFinalEmissionStatus = Literal[
    "cr2_final_emission_blocked",
    "cr3_final_emission_blocked",
    "unsupported_container",
]
type CanonRawFinalEmissionKind = Literal["cr2_tiff", "cr3_quicktime", "unknown"]
type CanonRawFinalEmissionStepCode = Literal[
    "validate_container_route",
    "emit_rebuilt_cr2_header",
    "emit_rewritten_tiff_directories",
    "copy_recorded_cr2_image_data_segments",
    "append_preserved_cr2_suffix",
    "walk_and_rebuild_cr3_atoms",
    "replace_cr3_xmp_uuid_payload",
    "rewrite_cr3_canon_cmt_tiff_payloads",
    "update_cr3_atom_sizes_and_uuid_offsets",
    "copy_or_edit_cr3_mdat_payloads",
    "patch_cr3_ctbo_item_offsets",
    "emit_cr3_write_last_atoms",
]
type CanonRawFinalEmissionBlockerCode = Literal[
    "shared_tiff_directory_emitter_required",
    "cr2_embedded_iptc_entry_relayout_required",
    "canon_makernote_binary_codec_required",
    "cr2_image_data_and_suffix_copy_required",
    "cr2_header_last_ifd_fixup_required",
    "quicktime_atom_rewrite_engine_required",
    "cr3_xmp_uuid_packet_writer_required",
    "cr3_canon_uuid_tiff_writer_required",
    "cr3_ctbo_mdat_offset_repair_required",
    "cr3_write_last_emission_required",
    "recognized_container_required",
]
type Cr3BoundedEmissionStatus = Literal[
    "ready",
    "non_cr3_container",
    "atom_scan_failed",
    "replacement_not_atom",
    "replacement_target_missing",
    "duplicate_replacement_target",
    "unsupported_mdat_replacement",
    "missing_mdat",
    "missing_ctbo",
    "ctbo_patch_failed",
]
type Cr3XmpUuidPayloadHandoffStatus = Literal[
    "ready",
    "non_cr3_container",
    "atom_scan_failed",
    "missing_xmp_uuid_atom",
    "no_supported_xmp_tags",
    "bounded_final_emission_blocked",
]
type Cr3CanonCmtTiffPayloadHandoffStatus = Literal[
    "ready",
    "non_cr3_container",
    "atom_scan_failed",
    "missing_cmt2_atom",
    "no_supported_cmt_tags",
    "unsupported_cmt_tiff_shape",
    "bounded_final_emission_blocked",
]
type Cr3CanonCmtAtomName = Literal["CMT1", "CMT2", "CMT3", "CMT4"]
type Cr3CanonCmtDirectoryName = Literal["IFD0", "ExifIFD", "MakerNotes", "GPS"]
type Cr2RebuiltContainerEmissionStatus = Literal[
    "ready",
    "non_cr2_container",
    "empty_rebuilt_tiff_payload",
    "header_fixup_blocked",
    "payload_copy_blocked",
]
type Cr2SharedTiffRebuiltPayloadSeamStatus = Literal[
    "ready",
    "ifd_stage_blocked",
    "missing_transaction_plan",
    "shared_tiff_payload_blocked",
]

EXIF_INTEROP_IFD_POINTER_TAG = 0xA005

WRITE_EXIF_CR2_EXIF_POINTER_TARGET_SOURCE = "canon_raw.write_exif_cr2_exif_pointer_target"

CR3_CMT3_MAKERNOTE_SAFETY_SOURCE = "canon_raw.cr3_cmt3_makernote_safety"
CR3_EXIF_MAKERNOTE_PARENT_WARNING_SOURCE = "canon_raw.cr3_exif_makernote_parent_warning"
CR3_CMT1_ORIENTATION_SOURCE = "canon_raw.cr3_cmt1_orientation"
CR3_CMT4_GPS_VERSION_ID_SOURCE = "canon_raw.cr3_cmt4_gps_version_id"


@dataclass(frozen=True)
class CanonRawFinalEmissionStep:
    order: int
    code: CanonRawFinalEmissionStepCode
    description: str
    ready: bool
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "description": self.description,
            "order": self.order,
            "ready": self.ready,
        }


@dataclass(frozen=True)
class CanonRawFinalEmissionBlocker:
    code: CanonRawFinalEmissionBlockerCode
    reason: str
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def blocks_emission(self) -> bool:
        return True

    def to_json(self) -> JsonObject:
        return {
            "blocks_emission": self.blocks_emission,
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CanonRawFinalEmissionPlan:
    status: CanonRawFinalEmissionStatus
    container_kind: CanonRawFinalEmissionKind
    requested_tags: tuple[str, ...]
    steps: tuple[CanonRawFinalEmissionStep, ...]
    blockers: tuple[CanonRawFinalEmissionBlocker, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_emit_bytes(self) -> bool:
        return False

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def ready_step_count(self) -> int:
        return sum(step.ready for step in self.steps)

    @property
    def blocked_step_count(self) -> int:
        return self.step_count - self.ready_step_count

    @property
    def blocker_count(self) -> int:
        return len(self.blockers)

    def blocker_codes(self) -> tuple[CanonRawFinalEmissionBlockerCode, ...]:
        return tuple(blocker.code for blocker in self.blockers)

    def to_json(self) -> JsonObject:
        return {
            "blocked_step_count": self.blocked_step_count,
            "blocker_count": self.blocker_count,
            "blockers": [blocker.to_json() for blocker in self.blockers],
            "can_emit_bytes": self.can_emit_bytes,
            "container_kind": self.container_kind,
            "ready_step_count": self.ready_step_count,
            "requested_tags": list(self.requested_tags),
            "status": self.status,
            "step_count": self.step_count,
            "steps": [step.to_json() for step in self.steps],
        }


@dataclass(frozen=True)
class Cr3AtomReplacement:
    """Already-encoded top-level CR3 atom replacement.

    The payload writer remains outside this seam.  This object only tells the
    bounded emitter where to place bytes that a source-backed payload writer has
    already materialized.
    """

    new_atom: bytes
    old_atom_offset: int | None
    write_last: bool = False


@dataclass(frozen=True)
class Cr3BoundedEmissionResult:
    status: Cr3BoundedEmissionStatus
    data: bytes | None
    replaced_atom_offsets: tuple[int, ...]
    write_last_atom_count: int
    ctbo_atom_offset: int | None
    mdat_atom_offset: int | None
    uuid_registrations: tuple[Cr3CtboOffsetRegistration, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_emit_bytes(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class Cr3XmpUuidPayloadHandoff:
    status: Cr3XmpUuidPayloadHandoffStatus
    replacement: Cr3AtomReplacement | None
    final_emission: Cr3BoundedEmissionResult | None
    xmp_uuid_atom_offset: int | None
    original_xmp_packet_byte_count: int
    rewritten_xmp_packet_byte_count: int
    changed_xmp_properties: int
    deleted_xmp_properties: int
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_feed_final_emission(self) -> bool:
        return self.replacement is not None

    @property
    def can_emit_bytes(self) -> bool:
        return self.status == "ready" and self.final_emission is not None


@dataclass(frozen=True)
class Cr3CanonCmtTiffPayloadHandoff:
    status: Cr3CanonCmtTiffPayloadHandoffStatus
    replacement: Cr3AtomReplacement | None
    final_emission: Cr3BoundedEmissionResult | None
    cmt_atom_offset: int | None
    original_cmt_payload_byte_count: int
    rewritten_cmt_payload_byte_count: int
    changed_tiff_properties: int
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_feed_final_emission(self) -> bool:
        return self.replacement is not None

    @property
    def can_emit_bytes(self) -> bool:
        return self.status == "ready" and self.final_emission is not None


@dataclass(frozen=True)
class Cr3CanonCmtAtomInventoryRecord:
    atom_name: Cr3CanonCmtAtomName
    directory_name: Cr3CanonCmtDirectoryName
    atom: Cr3AtomRecord
    can_rebuild_with_shared_tiff: bool
    makernote_safety_blocked: bool
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class Cr2RebuiltContainerEmissionResult:
    status: Cr2RebuiltContainerEmissionStatus
    data: bytes | None
    header_byte_count: int
    rebuilt_tiff_payload_byte_count: int
    copied_image_data_byte_count: int
    preserved_suffix_byte_count: int
    copied_image_data_segment_count: int
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_emit_bytes(self) -> bool:
        return self.status == "ready"

    @property
    def emitted_byte_count(self) -> int | None:
        if self.data is None:
            return None
        return len(self.data)

    def to_json(self) -> JsonObject:
        return {
            "can_emit_bytes": self.can_emit_bytes,
            "copied_image_data_byte_count": self.copied_image_data_byte_count,
            "copied_image_data_segment_count": self.copied_image_data_segment_count,
            "emitted_byte_count": self.emitted_byte_count,
            "header_byte_count": self.header_byte_count,
            "preserved_suffix_byte_count": self.preserved_suffix_byte_count,
            "rebuilt_tiff_payload_byte_count": self.rebuilt_tiff_payload_byte_count,
            "status": self.status,
        }


@dataclass(frozen=True)
class Cr2SharedTiffRebuiltPayloadSeam:
    status: Cr2SharedTiffRebuiltPayloadSeamStatus
    ifd_stage_status: str
    payload: TiffWriteExifRebuiltDirectoryPayload | None
    remaining_blocker: str | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_feed_final_emission(self) -> bool:
        return self.status == "ready" and self.payload is not None

    @property
    def rebuilt_tiff_payload(self) -> bytes | None:
        if self.payload is None:
            return None
        return self.payload.rebuilt_tiff_payload

    @property
    def last_ifd_offset(self) -> int | None:
        if self.payload is None:
            return None
        return self.payload.last_ifd_offset

    def to_json(self) -> JsonObject:
        return {
            "can_feed_final_emission": self.can_feed_final_emission,
            "ifd_stage_status": self.ifd_stage_status,
            "last_ifd_offset": self.last_ifd_offset,
            "payload": self.payload.to_json() if self.payload is not None else None,
            "rebuilt_tiff_payload_byte_count": (
                len(self.rebuilt_tiff_payload) if self.rebuilt_tiff_payload is not None else None
            ),
            "remaining_blocker": self.remaining_blocker,
            "status": self.status,
        }


def build_cr2_shared_tiff_rebuilt_payload_seam(
    data: bytes,
    classification: CanonRawWriteRequestClassification,
) -> Cr2SharedTiffRebuiltPayloadSeam:
    """Adapt CR2 IFD staging into the reusable TIFF rebuilt-payload seam."""

    ifd_stage = stage_cr2_tiff_ifd_mutation(data, classification)
    if ifd_stage.status != "ready":
        return Cr2SharedTiffRebuiltPayloadSeam(
            status="ifd_stage_blocked",
            ifd_stage_status=ifd_stage.status,
            payload=None,
            remaining_blocker=ifd_stage.status,
            evidence_ids=ifd_stage.evidence_ids,
        )
    if ifd_stage.transaction_plan is None or ifd_stage.endian is None:
        return Cr2SharedTiffRebuiltPayloadSeam(
            status="missing_transaction_plan",
            ifd_stage_status=ifd_stage.status,
            payload=None,
            remaining_blocker="missing_transaction_plan",
            evidence_ids=ifd_stage.evidence_ids,
        )

    staged_transaction_plan = cr2_transaction_plan_with_staged_exif_ifd_pointer_targets(
        data,
        ifd_stage.transaction_plan,
        ifd_stage.endian,
    )
    staged_transaction_plan = cr2_transaction_plan_with_staged_linked_ifd_chain(
        data,
        staged_transaction_plan,
        ifd_stage.endian,
    )

    payload_ledger = plan_canon_raw_container_transaction(
        data, classification
    ).cr2_payload_copy_ledger
    inline_image_data_placements = cr2_tiff_inline_image_data_placements(
        data,
        staged_transaction_plan,
        ifd_stage.endian,
        tiff_rewrite_base_offset=16,
    )
    copied_image_data_placements: tuple[TiffWriteExifImageDataPlacement, ...] = ()
    if payload_ledger is not None and payload_ledger.can_copy_payload_segments:
        copied_image_data_placements = cr2_tiff_image_data_placements(
            payload_ledger.image_data_segments,
            staged_transaction_plan.container_kind,
            first_image_data_offset=(
                16
                + projected_tiff_rebuilt_payload_byte_count(
                    staged_transaction_plan,
                    inline_image_data_placements,
                )
            ),
            evidence_ids=payload_ledger.evidence_ids,
        )
    payload = build_tiff_write_exif_rebuilt_directory_payload(
        staged_transaction_plan,
        endian=ifd_stage.endian,
        tiff_rewrite_base_offset=16,
        image_data_placements=(
            *inline_image_data_placements,
            *copied_image_data_placements,
        ),
    )
    if not payload.can_feed_container_emitter:
        return Cr2SharedTiffRebuiltPayloadSeam(
            status="shared_tiff_payload_blocked",
            ifd_stage_status=ifd_stage.status,
            payload=payload,
            remaining_blocker=payload.status,
            evidence_ids=unique_sources(
                (
                    *ifd_stage.evidence_ids,
                    WRITE_EXIF_CR2_EXIF_POINTER_TARGET_SOURCE,
                    *payload.evidence_ids,
                )
            ),
        )
    return Cr2SharedTiffRebuiltPayloadSeam(
        status="ready",
        ifd_stage_status=ifd_stage.status,
        payload=payload,
        remaining_blocker=None,
        evidence_ids=unique_sources(
            (
                *ifd_stage.evidence_ids,
                WRITE_EXIF_CR2_EXIF_POINTER_TARGET_SOURCE,
                *payload.evidence_ids,
            )
        ),
    )


def cr2_transaction_plan_with_staged_exif_ifd_pointer_targets(
    data: bytes,
    transaction_plan: TiffDirectoryTransactionPlan,
    endian: Endian,
) -> TiffDirectoryTransactionPlan:
    """Stage CR2 ExifIFD pointer targets required by bounded WriteExif fixups."""

    if any(plan.directory_name == "InteropIFD" for plan in transaction_plan.directory_plans):
        return transaction_plan
    exif_plan = next(
        (plan for plan in transaction_plan.directory_plans if plan.directory_name == "ExifIFD"),
        None,
    )
    if exif_plan is None:
        return transaction_plan
    interop_pointer_entry = next(
        (
            entry
            for entry in exif_plan.planned_directory.entries
            if entry.tag_id == EXIF_INTEROP_IFD_POINTER_TAG
        ),
        None,
    )
    if (
        interop_pointer_entry is None
        or interop_pointer_entry.field_type != TIFF_TYPE_LONG
        or interop_pointer_entry.count != 1
        or len(interop_pointer_entry.raw_value) != 4
    ):
        return transaction_plan
    interop_offset = int.from_bytes(interop_pointer_entry.raw_value, endian)
    if interop_offset == 0:
        return transaction_plan

    try:
        parsed_interop_ifd = parse_ifd(data, interop_offset, endian)
    except ValueError:
        return transaction_plan
    interop_plan = build_tiff_directory_rebuild_plan(
        raw_directory(data, parsed_interop_ifd, endian),
        directory_name="InteropIFD",
        endian=endian,
        container_kind=transaction_plan.container_kind,
        directory_start=parsed_interop_ifd.offset,
    )
    return TiffDirectoryTransactionPlan(
        status=transaction_plan.status,
        container_kind=transaction_plan.container_kind,
        directory_order=transaction_plan.directory_order,
        directory_plans=insert_directory_plan_after(
            transaction_plan.directory_plans,
            parent_directory_name="ExifIFD",
            inserted_plan=interop_plan,
        ),
        image_data_copy_gates=(
            *transaction_plan.image_data_copy_gates,
            *interop_plan.image_data_copy_gates,
        ),
        evidence_ids=unique_tiff_evidence_ids(
            (*transaction_plan.evidence_ids, *interop_plan.evidence_ids)
        ),
    )


def insert_directory_plan_after(
    directory_plans: tuple[TiffDirectoryRebuildPlan, ...],
    parent_directory_name: str,
    inserted_plan: TiffDirectoryRebuildPlan,
) -> tuple[TiffDirectoryRebuildPlan, ...]:
    rebuilt_plans: list[TiffDirectoryRebuildPlan] = []
    inserted = False
    for directory_plan in directory_plans:
        rebuilt_plans.append(directory_plan)
        if not inserted and directory_plan.directory_name == parent_directory_name:
            rebuilt_plans.append(inserted_plan)
            inserted = True
    if not inserted:
        rebuilt_plans.append(inserted_plan)
    return tuple(rebuilt_plans)


def cr2_transaction_plan_with_staged_linked_ifd_chain(
    data: bytes,
    transaction_plan: TiffDirectoryTransactionPlan,
    endian: Endian,
) -> TiffDirectoryTransactionPlan:
    """Stage the remaining CR2 linked IFD1+ chain for exact NextIFD fixups."""

    existing_offsets = {plan.directory_start for plan in transaction_plan.directory_plans}
    ifd1_plan = next(
        (plan for plan in transaction_plan.directory_plans if plan.directory_name == "IFD1"),
        None,
    )
    if ifd1_plan is None:
        return transaction_plan

    next_ifd_offset = ifd1_plan.next_ifd_pointer.original_next_ifd_offset
    ifd_index = 2
    appended_plans: list[TiffDirectoryRebuildPlan] = []
    while next_ifd_offset:
        if next_ifd_offset in existing_offsets:
            break
        try:
            parsed_ifd = parse_ifd(data, next_ifd_offset, endian)
        except ValueError:
            break
        directory_plan = build_tiff_directory_rebuild_plan(
            raw_directory(data, parsed_ifd, endian),
            directory_name=f"IFD{ifd_index}",
            endian=endian,
            container_kind=transaction_plan.container_kind,
            directory_start=parsed_ifd.offset,
            ifd_index=ifd_index,
        )
        appended_plans.append(directory_plan)
        existing_offsets.add(parsed_ifd.offset)
        next_ifd_offset = parsed_ifd.next_ifd_offset
        ifd_index += 1

    if not appended_plans:
        return transaction_plan
    return TiffDirectoryTransactionPlan(
        status=transaction_plan.status,
        container_kind=transaction_plan.container_kind,
        directory_order=transaction_plan.directory_order,
        directory_plans=(*transaction_plan.directory_plans, *appended_plans),
        image_data_copy_gates=(
            *transaction_plan.image_data_copy_gates,
            *(gate for plan in appended_plans for gate in plan.image_data_copy_gates),
        ),
        evidence_ids=unique_tiff_evidence_ids(
            (
                *transaction_plan.evidence_ids,
                *(reference for plan in appended_plans for reference in plan.evidence_ids),
            )
        ),
    )


def cr2_tiff_inline_image_data_placements(
    data: bytes,
    transaction_plan: TiffDirectoryTransactionPlan,
    endian: Endian,
    tiff_rewrite_base_offset: int,
) -> tuple[TiffWriteExifImageDataPlacement, ...]:
    """Create WriteExif inline payload placements, currently bounded to thumbnails."""

    placements: list[TiffWriteExifImageDataPlacement] = []
    current_offset = tiff_rewrite_base_offset
    for directory_plan in transaction_plan.directory_plans:
        directory_payload_byte_count = projected_cr2_tiff_directory_payload_byte_count(
            directory_plan
        )
        appended_byte_count = 0
        for offset_pair in directory_plan.offset_pairs:
            if (
                offset_pair.offset_tag_id != THUMBNAIL_OFFSET_TAG
                or offset_pair.byte_count_tag_id != THUMBNAIL_LENGTH_TAG
                or offset_pair.offset_count != 1
                or offset_pair.byte_count_count != 1
                or not offset_pair.counts_match
            ):
                continue
            offset_entry = raw_tiff_entry_by_tag_id(
                directory_plan,
                offset_pair.offset_tag_id,
            )
            byte_count_entry = raw_tiff_entry_by_tag_id(
                directory_plan,
                offset_pair.byte_count_tag_id,
            )
            if (
                offset_entry is None
                or byte_count_entry is None
                or offset_entry.field_type != TIFF_TYPE_LONG
                or byte_count_entry.field_type != TIFF_TYPE_LONG
                or offset_entry.count != 1
                or byte_count_entry.count != 1
                or len(offset_entry.raw_value) != 4
                or len(byte_count_entry.raw_value) != 4
            ):
                continue
            original_offset = int.from_bytes(offset_entry.raw_value, endian)
            byte_count = int.from_bytes(byte_count_entry.raw_value, endian)
            original_end_offset = original_offset + byte_count
            if original_offset < 0 or byte_count < 0 or original_end_offset > len(data):
                continue
            padding_byte_count = byte_count & 0x01
            payload = data[original_offset:original_end_offset]
            placements.append(
                TiffWriteExifImageDataPlacement(
                    directory_name=directory_plan.directory_name,
                    ifd_offset=directory_plan.directory_start,
                    offset_tag_id=offset_pair.offset_tag_id,
                    byte_count_tag_id=offset_pair.byte_count_tag_id,
                    original_offset=original_offset,
                    byte_count=byte_count,
                    output_offset=(
                        current_offset + directory_payload_byte_count + appended_byte_count
                    ),
                    padding_byte_count=padding_byte_count,
                    evidence_ids=(WRITE_EXIF_INLINE_IMAGE_DATA_APPEND_SOURCE,),
                    appended_payload=payload,
                )
            )
            appended_byte_count += byte_count + padding_byte_count
        current_offset += directory_payload_byte_count + appended_byte_count
    return tuple(placements)


def projected_cr2_tiff_directory_payload_byte_count(
    directory_plan: TiffDirectoryRebuildPlan,
) -> int:
    return (
        2
        + len(directory_plan.ordered_entries) * 12
        + 4
        + sum(
            len(entry_layout.source_entry.raw_value)
            for entry_layout in directory_plan.ordered_entries
            if len(entry_layout.source_entry.raw_value) > 4
        )
    )


def raw_tiff_entry_by_tag_id(
    directory_plan: TiffDirectoryRebuildPlan,
    tag_id: int,
) -> RawTiffEntry | None:
    for entry in directory_plan.planned_directory.entries:
        if entry.tag_id == tag_id:
            return entry
    return None


def cr2_tiff_image_data_placements(
    image_data_segments: tuple[Cr2ImageDataCopySegment, ...],
    container_kind: str,
    first_image_data_offset: int,
    evidence_ids: tuple[EvidenceId, ...],
) -> tuple[TiffWriteExifImageDataPlacement, ...]:
    output_offset = first_image_data_offset
    placements: list[TiffWriteExifImageDataPlacement] = []
    for segment in image_data_segments:
        placements.append(
            TiffWriteExifImageDataPlacement(
                directory_name="IFD0" if segment.ifd_offset == 16 else "SubIFD",
                ifd_offset=segment.ifd_offset,
                offset_tag_id=segment.offset_tag_id,
                byte_count_tag_id=segment.byte_count_tag_id,
                original_offset=segment.original_offset,
                byte_count=segment.byte_count,
                output_offset=output_offset,
                padding_byte_count=segment.padding_byte_count,
                evidence_ids=(WRITE_EXIF_INLINE_IMAGE_DATA_APPEND_SOURCE,),
            )
        )
        output_offset += segment.byte_count + segment.padding_byte_count
    if container_kind != "cr2":
        return ()
    return tuple(placements)


def projected_tiff_rebuilt_payload_byte_count(
    transaction_plan: TiffDirectoryTransactionPlan,
    image_data_placements: tuple[TiffWriteExifImageDataPlacement, ...] = (),
) -> int:
    appended_payload_byte_count_by_ifd_offset: dict[int, int] = {}
    for placement in image_data_placements:
        if placement.appended_payload is None:
            continue
        appended_payload_byte_count_by_ifd_offset[placement.ifd_offset] = (
            appended_payload_byte_count_by_ifd_offset.get(placement.ifd_offset, 0)
            + len(placement.appended_payload)
            + placement.padding_byte_count
        )
    total = 0
    for directory_plan in transaction_plan.directory_plans:
        total += 2 + len(directory_plan.ordered_entries) * 12 + 4
        total += sum(
            len(entry_layout.source_entry.raw_value)
            for entry_layout in directory_plan.ordered_entries
            if len(entry_layout.source_entry.raw_value) > 4
        )
        total += appended_payload_byte_count_by_ifd_offset.get(
            directory_plan.directory_start,
            0,
        )
    return total


def emit_cr2_rebuilt_container_stream(
    data: bytes,
    classification: CanonRawWriteRequestClassification,
    rebuilt_tiff_payload: bytes,
    last_ifd_offset: int,
) -> Cr2RebuiltContainerEmissionResult:
    """Emit WriteCR2's final container sequence around rebuilt TIFF bytes.

    The shared TIFF directory emitter is still responsible for producing
    ``rebuilt_tiff_payload`` and its LastIFD offset.  This bounded emitter owns
    the CR2-native final byte step: rebuilt 16-byte header, supplied TIFF data,
    copied image-data blocks, and preserved suffix bytes.
    """

    if classification.container_kind != "cr2_tiff":
        return cr2_rebuilt_container_blocked(
            "non_cr2_container",
            len(rebuilt_tiff_payload),
            (WRITE_CR2_SOURCE, CR3_QUICKTIME_MAP_SOURCE),
        )
    if not rebuilt_tiff_payload:
        return cr2_rebuilt_container_blocked(
            "empty_rebuilt_tiff_payload",
            0,
            (WRITE_CR2_SOURCE,),
        )

    transaction = plan_canon_raw_container_transaction(data, classification)
    payload_ledger = transaction.cr2_payload_copy_ledger
    header_plan = plan_cr2_rebuilt_header(data[:16], last_ifd_offset)
    if not header_plan.can_emit_header or header_plan.rebuilt_header is None:
        return cr2_rebuilt_container_blocked(
            "header_fixup_blocked",
            len(rebuilt_tiff_payload),
            header_plan.evidence_ids,
        )
    if payload_ledger is None or not payload_ledger.can_copy_payload_segments:
        return cr2_rebuilt_container_blocked(
            "payload_copy_blocked",
            len(rebuilt_tiff_payload),
            payload_ledger.evidence_ids if payload_ledger is not None else (WRITE_CR2_SOURCE,),
        )

    output = bytearray(header_plan.rebuilt_header)
    output.extend(rebuilt_tiff_payload)
    copied_image_data_byte_count = 0
    for segment in payload_ledger.image_data_segments:
        output.extend(data[segment.original_offset : segment.original_end_offset])
        if segment.padding_byte_count:
            output.extend(b"\x00" * segment.padding_byte_count)
        copied_image_data_byte_count += segment.byte_count + segment.padding_byte_count

    preserved_suffix_byte_count = 0
    if payload_ledger.suffix_range is not None:
        suffix = data[
            payload_ledger.suffix_range.start_offset : payload_ledger.suffix_range.end_offset
        ]
        output.extend(suffix)
        preserved_suffix_byte_count = len(suffix)

    return Cr2RebuiltContainerEmissionResult(
        status="ready",
        data=bytes(output),
        header_byte_count=len(header_plan.rebuilt_header),
        rebuilt_tiff_payload_byte_count=len(rebuilt_tiff_payload),
        copied_image_data_byte_count=copied_image_data_byte_count,
        preserved_suffix_byte_count=preserved_suffix_byte_count,
        copied_image_data_segment_count=len(payload_ledger.image_data_segments),
        evidence_ids=unique_sources(
            (
                *header_plan.evidence_ids,
                *payload_ledger.evidence_ids,
                WRITE_CR2_SOURCE,
            )
        ),
    )


def cr2_rebuilt_container_blocked(
    status: Cr2RebuiltContainerEmissionStatus,
    rebuilt_tiff_payload_byte_count: int,
    evidence_ids: tuple[EvidenceId, ...],
) -> Cr2RebuiltContainerEmissionResult:
    return Cr2RebuiltContainerEmissionResult(
        status=status,
        data=None,
        header_byte_count=0,
        rebuilt_tiff_payload_byte_count=rebuilt_tiff_payload_byte_count,
        copied_image_data_byte_count=0,
        preserved_suffix_byte_count=0,
        copied_image_data_segment_count=0,
        evidence_ids=evidence_ids,
    )


def emit_bounded_cr3_quicktime_stream(
    data: bytes,
    replacements: tuple[Cr3AtomReplacement, ...],
) -> Cr3BoundedEmissionResult:
    """Emit a bounded CR3 top-level rewrite from already-built replacement atoms.

    This implements the source-backed final container boundary from
    WriteQuickTime.pl: rebuilt metadata bytes first, copied media data next,
    WriteLast atoms last, then CTBO table patching from final uuid and mdat
    positions.  It deliberately does not create XMP packets, Canon CMT TIFF
    payloads, nested atom edits, or edited mdat payloads.
    """

    brand = inspect_cr3_ftyp_brand(data[:32])
    if not brand.recognized:
        return cr3_bounded_emission_blocked("non_cr3_container")
    scan = scan_cr3_top_level_atoms(data)
    if not scan.ready:
        return cr3_bounded_emission_blocked("atom_scan_failed")
    tree = scan_cr3_atom_tree(data)
    if not tree.ready:
        return cr3_bounded_emission_blocked("atom_scan_failed")

    replacements_by_offset: dict[int, Cr3AtomReplacement] = {}
    write_last_insertions: list[bytes] = []
    for requested_replacement in replacements:
        try:
            replacement_record = decode_single_cr3_atom(requested_replacement.new_atom)
        except ValueError:
            return cr3_bounded_emission_blocked("replacement_not_atom")
        if replacement_record.atom_type in {"mdat", "CTBO"}:
            return cr3_bounded_emission_blocked("unsupported_mdat_replacement")
        if requested_replacement.old_atom_offset is None:
            if requested_replacement.write_last:
                write_last_insertions.append(requested_replacement.new_atom)
                continue
            return cr3_bounded_emission_blocked("replacement_target_missing")
        if requested_replacement.old_atom_offset in replacements_by_offset:
            return cr3_bounded_emission_blocked("duplicate_replacement_target")
        replacements_by_offset[requested_replacement.old_atom_offset] = requested_replacement

    tree_records_by_offset = {record.atom.offset: record.atom for record in tree.records}
    source_offsets = set(tree_records_by_offset)
    if not set(replacements_by_offset).issubset(source_offsets):
        return cr3_bounded_emission_blocked("replacement_target_missing")
    for old_atom_offset in replacements_by_offset:
        target_record = tree_records_by_offset[old_atom_offset]
        if target_record.atom_type in {"mdat", "CTBO"}:
            return cr3_bounded_emission_blocked("unsupported_mdat_replacement")

    output = bytearray()
    mdat_atoms: list[bytes] = []
    write_last_atoms: list[bytes] = [*write_last_insertions]
    replaced_atom_offsets: list[int] = []
    ctbo_atom_offset: int | None = None
    mdat_atom_offset: int | None = None
    saw_mdat = False

    for record in scan.records:
        rebuild = rebuild_cr3_atom_with_nested_replacements(
            data,
            record,
            replacements_by_offset,
            replaced_atom_offsets,
            write_last_atoms,
        )
        if rebuild is None:
            return cr3_bounded_emission_blocked("atom_scan_failed")
        atom_bytes = rebuild

        if record.atom_type == "CTBO":
            ctbo_atom_offset = len(output)
        elif record.atom_type == "mdat":
            saw_mdat = True
            mdat_atoms.append(atom_bytes)
            continue
        output.extend(atom_bytes)

    if not saw_mdat or not mdat_atoms:
        return cr3_bounded_emission_blocked("missing_mdat")

    for atom_bytes in mdat_atoms:
        if mdat_atom_offset is None:
            mdat_atom_offset = len(output)
        output.extend(atom_bytes)

    if mdat_atom_offset is None:
        return cr3_bounded_emission_blocked("missing_mdat")

    for atom_bytes in write_last_atoms:
        output.extend(atom_bytes)

    unpatched_stream = bytes(output)
    rebuilt_tree = scan_cr3_atom_tree(unpatched_stream)
    if not rebuilt_tree.ready:
        return cr3_bounded_emission_blocked("atom_scan_failed")
    ctbo_record = cr3_ctbo_record(rebuilt_tree.records)
    if ctbo_record is None:
        return cr3_bounded_emission_blocked("missing_ctbo")
    ctbo_atom_offset = ctbo_record.atom.offset
    uuid_registrations = cr3_ctbo_uuid_registrations(unpatched_stream, rebuilt_tree.records)
    ctbo_atom = unpatched_stream[
        ctbo_record.atom.offset : ctbo_record.atom.offset + ctbo_record.atom.size
    ]
    if not inspect_cr3_ctbo_atom(ctbo_atom).ready:
        return cr3_bounded_emission_blocked("ctbo_patch_failed")
    patch_plan = plan_cr3_ctbo_patches(ctbo_atom, uuid_registrations, mdat_atom_offset)
    patch_result = apply_cr3_ctbo_patches_to_rebuilt_stream(
        unpatched_stream,
        ctbo_atom_offset,
        patch_plan,
    )
    if not patch_result.can_emit_stream or patch_result.rebuilt_stream is None:
        return cr3_bounded_emission_blocked("ctbo_patch_failed")

    return Cr3BoundedEmissionResult(
        status="ready",
        data=patch_result.rebuilt_stream,
        replaced_atom_offsets=tuple(replaced_atom_offsets),
        write_last_atom_count=len(write_last_atoms),
        ctbo_atom_offset=ctbo_atom_offset,
        mdat_atom_offset=mdat_atom_offset,
        uuid_registrations=uuid_registrations,
        evidence_ids=cr3_bounded_emission_sources(),
    )


def build_cr3_xmp_uuid_packet_handoff(
    data: bytes,
    classification: CanonRawWriteRequestClassification,
) -> Cr3XmpUuidPayloadHandoff:
    """Build and hand off a CR3 top-level XMP UUID atom replacement.

    oracle routes CR3 XMP to the top-level MOV map, identifies the MP4 XMP
    UUID by its fixed 16-byte prefix, starts the XMP subdirectory after that
    prefix, and records new uuid offsets for later CTBO repair.
    """

    if (
        classification.container_kind != "cr3_quicktime"
        or not inspect_cr3_ftyp_brand(data[:32]).recognized
    ):
        return cr3_xmp_uuid_payload_handoff_blocked("non_cr3_container")
    scan = scan_cr3_top_level_atoms(data)
    if not scan.ready:
        return cr3_xmp_uuid_payload_handoff_blocked("atom_scan_failed")

    xmp_boundary = cr3_top_level_xmp_uuid_boundary(data, scan.records)
    if (
        xmp_boundary is None
        or xmp_boundary.payload_offset is None
        or xmp_boundary.payload_size is None
    ):
        return cr3_xmp_uuid_payload_handoff_blocked("missing_xmp_uuid_atom")

    plan = cr3_xmp_property_write_plan(classification)
    if not plan.steps:
        return cr3_xmp_uuid_payload_handoff_blocked("no_supported_xmp_tags")

    source_packet = data[
        xmp_boundary.payload_offset : xmp_boundary.payload_offset + xmp_boundary.payload_size
    ]
    xmp_result = apply_xmp_property_write_plan(source_packet, plan)
    new_atom = encode_cr3_atom("uuid", XMP_UUID_IDENTIFIER + xmp_result.packet)
    replacement = Cr3AtomReplacement(
        new_atom=new_atom,
        old_atom_offset=xmp_boundary.atom.offset if xmp_boundary.atom is not None else None,
    )
    final_emission = emit_bounded_cr3_quicktime_stream(data, (replacement,))
    if final_emission.status != "ready":
        return Cr3XmpUuidPayloadHandoff(
            status="bounded_final_emission_blocked",
            replacement=replacement,
            final_emission=final_emission,
            xmp_uuid_atom_offset=replacement.old_atom_offset,
            original_xmp_packet_byte_count=len(source_packet),
            rewritten_xmp_packet_byte_count=len(xmp_result.packet),
            changed_xmp_properties=xmp_result.changed_properties,
            deleted_xmp_properties=xmp_result.deleted_properties,
            evidence_ids=cr3_xmp_uuid_payload_handoff_sources(final_emission.evidence_ids),
        )

    return Cr3XmpUuidPayloadHandoff(
        status="ready",
        replacement=replacement,
        final_emission=final_emission,
        xmp_uuid_atom_offset=replacement.old_atom_offset,
        original_xmp_packet_byte_count=len(source_packet),
        rewritten_xmp_packet_byte_count=len(xmp_result.packet),
        changed_xmp_properties=xmp_result.changed_properties,
        deleted_xmp_properties=xmp_result.deleted_properties,
        evidence_ids=cr3_xmp_uuid_payload_handoff_sources(final_emission.evidence_ids),
    )


def build_cr3_canon_cmt_tiff_payload_handoff(
    data: bytes,
    classification: CanonRawWriteRequestClassification,
) -> Cr3CanonCmtTiffPayloadHandoff:
    """Build and hand off a Canon UUID CMT2 TIFF atom replacement.

    oracle maps CMT2 to ExifIFD/WriteTIFF with PreservePadding, and tag
    0x9204 is a signed rational.  The bounded handoff now rebuilds the CMT2
    TIFF directory through the shared WriteExif value-buffer emitter, so the
    ExposureCompensation entry may be updated or created without fixture-local
    byte patching.
    """

    if (
        classification.container_kind != "cr3_quicktime"
        or not inspect_cr3_ftyp_brand(data[:32]).recognized
    ):
        return cr3_canon_cmt_tiff_payload_handoff_blocked("non_cr3_container")
    tree = scan_cr3_atom_tree(data)
    if not tree.ready:
        return cr3_canon_cmt_tiff_payload_handoff_blocked("atom_scan_failed")

    requested_value = cr3_requested_exposure_compensation_value(classification)
    if requested_value is None:
        return cr3_canon_cmt_tiff_payload_handoff_blocked("no_supported_cmt_tags")

    cmt2_record = cr3_canon_cmt_atom_record(tree.records, "CMT2")
    if cmt2_record is None:
        return cr3_canon_cmt_tiff_payload_handoff_blocked("missing_cmt2_atom")

    source_payload = data[cmt2_record.payload_offset : cmt2_record.offset + cmt2_record.size]
    rewritten_payload = rewrite_cmt2_exposure_compensation_tiff_payload(
        source_payload,
        requested_value,
    )
    if rewritten_payload is None:
        return cr3_canon_cmt_tiff_payload_handoff_blocked("unsupported_cmt_tiff_shape")

    replacement = Cr3AtomReplacement(
        new_atom=encode_cr3_atom("CMT2", rewritten_payload),
        old_atom_offset=cmt2_record.offset,
    )
    final_emission = emit_bounded_cr3_quicktime_stream(data, (replacement,))
    if final_emission.status != "ready":
        return Cr3CanonCmtTiffPayloadHandoff(
            status="bounded_final_emission_blocked",
            replacement=replacement,
            final_emission=final_emission,
            cmt_atom_offset=cmt2_record.offset,
            original_cmt_payload_byte_count=len(source_payload),
            rewritten_cmt_payload_byte_count=len(rewritten_payload),
            changed_tiff_properties=1,
            evidence_ids=cr3_canon_cmt_tiff_payload_handoff_sources(final_emission.evidence_ids),
        )

    return Cr3CanonCmtTiffPayloadHandoff(
        status="ready",
        replacement=replacement,
        final_emission=final_emission,
        cmt_atom_offset=cmt2_record.offset,
        original_cmt_payload_byte_count=len(source_payload),
        rewritten_cmt_payload_byte_count=len(rewritten_payload),
        changed_tiff_properties=1,
        evidence_ids=cr3_canon_cmt_tiff_payload_handoff_sources(final_emission.evidence_ids),
    )


def emit_cr3_rebuilt_container_stream(
    data: bytes,
    classification: CanonRawWriteRequestClassification,
) -> Cr3BoundedEmissionResult:
    """Emit the source-backed CanonRaw.t test 9 CR3 XMP+CMT2 mutation shape."""

    xmp_handoff = build_cr3_xmp_uuid_packet_handoff(data, classification)
    cmt_handoff = build_cr3_canon_cmt_tiff_payload_handoff(data, classification)
    if xmp_handoff.replacement is None or cmt_handoff.replacement is None:
        return Cr3BoundedEmissionResult(
            status="replacement_target_missing",
            data=None,
            replaced_atom_offsets=(),
            write_last_atom_count=0,
            ctbo_atom_offset=None,
            mdat_atom_offset=None,
            uuid_registrations=(),
            evidence_ids=unique_sources((*xmp_handoff.evidence_ids, *cmt_handoff.evidence_ids)),
        )
    emission = emit_bounded_cr3_quicktime_stream(
        data,
        (xmp_handoff.replacement, cmt_handoff.replacement),
    )
    return Cr3BoundedEmissionResult(
        status=emission.status,
        data=emission.data,
        replaced_atom_offsets=emission.replaced_atom_offsets,
        write_last_atom_count=emission.write_last_atom_count,
        ctbo_atom_offset=emission.ctbo_atom_offset,
        mdat_atom_offset=emission.mdat_atom_offset,
        uuid_registrations=emission.uuid_registrations,
        evidence_ids=unique_sources(
            (
                *xmp_handoff.evidence_ids,
                *cmt_handoff.evidence_ids,
                *emission.evidence_ids,
            )
        ),
    )


def cr3_requested_exposure_compensation_value(
    classification: CanonRawWriteRequestClassification,
) -> Fraction | None:
    for tag in classification.tags:
        if "cr3_quicktime_canon_uuid_tiff" not in tag.target_surfaces:
            continue
        if tag.requested_tag.rsplit(":", 1)[-1] != "ExposureCompensation":
            continue
        return Fraction(tag.requested_value)
    return None


def cr3_canon_cmt_atom_record(
    records: tuple[Cr3AtomTreeRecord, ...],
    atom_type: str,
) -> Cr3AtomRecord | None:
    """Return a Canon CMT child atom discovered under a Canon UUID container."""

    matches = tuple(
        record.atom
        for record in records
        if record.atom.atom_type == atom_type
        and len(record.path) >= 2
        and record.path[-2] == "uuid"
    )
    if len(matches) != 1:
        return None
    return matches[0]


def inspect_cr3_canon_cmt_atom_inventory(data: bytes) -> tuple[Cr3CanonCmtAtomInventoryRecord, ...]:
    """List source-defined Canon CR3 CMT TIFF atoms and MakerNote safety status.

    oracle maps CMT1/CMT2/CMT4 to normal WriteTIFF subdirectories, while
    CMT3 uses Canon MakerNote processing.  This inventory keeps the current
    mutation boundary explicit: CMT3 may be detected and preserved, but it is
    not a safe target for the shared TIFF directory rebuild path.
    """

    if not inspect_cr3_ftyp_brand(data[:32]).recognized:
        return ()
    tree = scan_cr3_atom_tree(data)
    if not tree.ready:
        return ()

    records: list[Cr3CanonCmtAtomInventoryRecord] = []
    for atom_name, directory_name in CR3_CANON_CMT_ATOM_DIRECTORIES:
        atom = cr3_canon_cmt_atom_record(tree.records, atom_name)
        if atom is None:
            continue
        makernote_blocked = atom_name == "CMT3"
        records.append(
            Cr3CanonCmtAtomInventoryRecord(
                atom_name=atom_name,
                directory_name=directory_name,
                atom=atom,
                can_rebuild_with_shared_tiff=not makernote_blocked,
                makernote_safety_blocked=makernote_blocked,
                evidence_ids=cr3_canon_cmt_inventory_sources(atom_name),
            )
        )
    return tuple(records)


def rewrite_cmt2_exposure_compensation_tiff_payload(
    cmt2_tiff_payload: bytes,
    value: Fraction,
) -> bytes | None:
    try:
        header = parse_tiff_header(cmt2_tiff_payload)
    except ValueError:
        return None
    payload = rebuild_cr3_cmt_tiff_directory_payload(
        cmt2_tiff_payload,
        directory_name="ExifIFD",
        updated_entry=cr3_cmt_exposure_compensation_entry(value, header.endian),
    )
    if payload is not None:
        return payload
    return rewrite_existing_cmt2_exposure_compensation(cmt2_tiff_payload, value)


def rewrite_cmt1_orientation_tiff_payload(
    cmt1_tiff_payload: bytes,
    orientation: int,
) -> bytes | None:
    if orientation < 1 or orientation > 8:
        return None
    try:
        header = parse_tiff_header(cmt1_tiff_payload)
    except ValueError:
        return None
    return rebuild_cr3_cmt_tiff_directory_payload(
        cmt1_tiff_payload,
        directory_name="IFD0",
        updated_entry=RawTiffEntry(
            tag_id=0x0112,
            field_type=TIFF_TYPE_SHORT,
            count=1,
            raw_value=orientation.to_bytes(2, header.endian),
        ),
    )


def rewrite_cmt4_gps_version_id_tiff_payload(
    cmt4_tiff_payload: bytes,
    version: tuple[int, int, int, int],
) -> bytes | None:
    if any(part < 0 or part > 255 for part in version):
        return None
    try:
        parse_tiff_header(cmt4_tiff_payload)
    except ValueError:
        return None
    return rebuild_cr3_cmt_tiff_directory_payload(
        cmt4_tiff_payload,
        directory_name="GPS",
        updated_entry=RawTiffEntry(
            tag_id=0x0000,
            field_type=TIFF_TYPE_BYTE,
            count=4,
            raw_value=bytes(version),
        ),
    )


def rebuild_cr3_cmt_tiff_directory_payload(
    cmt_tiff_payload: bytes,
    *,
    directory_name: str,
    updated_entry: RawTiffEntry,
) -> bytes | None:
    try:
        header = parse_tiff_header(cmt_tiff_payload)
        ifd = parse_ifd(cmt_tiff_payload, header.first_ifd_offset, header.endian)
        directory = raw_directory(cmt_tiff_payload, ifd, header.endian)
    except ValueError:
        return None

    if ifd.next_ifd_offset != 0:
        return None
    planned_directory = RawTiffDirectory(
        entries=upsert_raw_entry(directory.entries, updated_entry),
        next_ifd_offset=0,
    )
    transaction_plan = build_tiff_directory_transaction_plan(
        (
            TiffDirectoryInput(
                directory_name,
                planned_directory,
                directory_start=header.first_ifd_offset,
            ),
        ),
        endian=header.endian,
    )
    rebuilt_directory = build_tiff_write_exif_rebuilt_directory_payload(
        transaction_plan,
        endian=header.endian,
        tiff_rewrite_base_offset=header.first_ifd_offset,
    )
    if rebuilt_directory.rebuilt_tiff_payload is None:
        return None
    original_directory_end = parsed_ifd_data_end(ifd)
    rebuilt = (
        cmt_tiff_payload[: header.first_ifd_offset]
        + rebuilt_directory.rebuilt_tiff_payload
        + cmt_tiff_payload[original_directory_end:]
    )
    if len(rebuilt) < len(cmt_tiff_payload):
        rebuilt += b"\x00" * (len(cmt_tiff_payload) - len(rebuilt))
    return rebuilt


def cr3_cmt_exposure_compensation_entry(
    value: Fraction,
    endian: Endian,
) -> RawTiffEntry:
    return RawTiffEntry(
        tag_id=0x9204,
        field_type=TIFF_TYPE_SRATIONAL,
        count=1,
        raw_value=(
            value.numerator.to_bytes(4, endian, signed=True)
            + value.denominator.to_bytes(4, endian, signed=True)
        ),
    )


def rewrite_existing_cmt2_exposure_compensation(
    cmt2_tiff_payload: bytes,
    value: Fraction,
) -> bytes | None:
    try:
        header = parse_tiff_header(cmt2_tiff_payload)
        ifd = parse_ifd(cmt2_tiff_payload, header.first_ifd_offset, header.endian)
    except ValueError:
        return None
    entry = next((entry for entry in ifd.entries if entry.tag_id == 0x9204), None)
    if entry is None or entry.field_type != TIFF_TYPE_SRATIONAL or entry.count != 1:
        return None
    value_offset = entry.value_offset
    if value_offset + 8 > len(cmt2_tiff_payload):
        return None
    rewritten = bytearray(cmt2_tiff_payload)
    rewritten[value_offset : value_offset + 4] = value.numerator.to_bytes(
        4,
        header.endian,
        signed=True,
    )
    rewritten[value_offset + 4 : value_offset + 8] = value.denominator.to_bytes(
        4,
        header.endian,
        signed=True,
    )
    return bytes(rewritten)


CR3_CANON_CMT_ATOM_DIRECTORIES: tuple[tuple[Cr3CanonCmtAtomName, Cr3CanonCmtDirectoryName], ...] = (
    ("CMT1", "IFD0"),
    ("CMT2", "ExifIFD"),
    ("CMT3", "MakerNotes"),
    ("CMT4", "GPS"),
)


def cr3_canon_cmt_inventory_sources(
    atom_name: Cr3CanonCmtAtomName,
) -> tuple[EvidenceId, ...]:
    if atom_name == "CMT3":
        return unique_sources(
            (
                CR3_CANON_UUID_SOURCE,
                CR3_CMT_TIFF_PAYLOAD_SOURCE,
                CR3_CMT3_MAKERNOTE_SAFETY_SOURCE,
                CR3_EXIF_MAKERNOTE_PARENT_WARNING_SOURCE,
            )
        )
    return unique_sources((CR3_CANON_UUID_SOURCE, CR3_CMT_TIFF_PAYLOAD_SOURCE))


def cr3_canon_cmt_tiff_payload_handoff_blocked(
    status: Cr3CanonCmtTiffPayloadHandoffStatus,
) -> Cr3CanonCmtTiffPayloadHandoff:
    return Cr3CanonCmtTiffPayloadHandoff(
        status=status,
        replacement=None,
        final_emission=None,
        cmt_atom_offset=None,
        original_cmt_payload_byte_count=0,
        rewritten_cmt_payload_byte_count=0,
        changed_tiff_properties=0,
        evidence_ids=cr3_canon_cmt_tiff_payload_handoff_sources(()),
    )


def cr3_canon_cmt_tiff_payload_handoff_sources(
    extra_sources: tuple[EvidenceId, ...],
) -> tuple[EvidenceId, ...]:
    return unique_sources(
        (
            CR3_CANON_UUID_SOURCE,
            CR3_CMT_TIFF_PAYLOAD_SOURCE,
            CR3_ATOM_SIZE_UPDATE_SOURCE,
            EXIF_EXPOSURE_COMPENSATION_SOURCE,
            *extra_sources,
        )
    )


def cr3_top_level_xmp_uuid_boundary(
    data: bytes,
    records: tuple[Cr3AtomRecord, ...],
) -> Cr3UuidAtomBoundary | None:
    for record in records:
        if record.atom_type != "uuid":
            continue
        boundary = inspect_cr3_uuid_atom_boundary(data, record)
        if boundary.status == "ready" and boundary.kind == "xmp":
            return boundary
    return None


def cr3_xmp_property_write_plan(
    classification: CanonRawWriteRequestClassification,
) -> XmpPropertyWritePlan:
    steps: list[XmpPropertyWriteStep] = []
    generated_specs: list[XmpPropertySpec] = []
    for tag in classification.tags:
        if "cr3_quicktime_top_level_xmp" not in tag.target_surfaces:
            continue
        unqualified_tag = tag.requested_tag.rsplit(":", 1)[-1]
        if unqualified_tag in {"Subject", "Keywords"}:
            steps.append(XmpTextListPropertyWrite("XMP-dc:Subject", (tag.requested_value,)))
        elif unqualified_tag == "ExposureCompensation":
            property_name = "XMP-exif:ExposureCompensation"
            steps.append(XmpTextPropertyWrite(property_name, tag.requested_value))
            generated_specs.append(
                XmpPropertySpec(
                    property_name=property_name,
                    namespace_prefix="exif",
                    namespace_uri="http://ns.adobe.com/exif/1.0/",
                    element_name="ExposureBiasValue",
                    value_shape="numeric",
                    evidence_ids=(GENERATED_PROPERTY_SOURCE,),
                )
            )
    return XmpPropertyWritePlan(
        steps=tuple(steps),
        evidence_ids=(GENERATED_PROPERTY_SOURCE, XMP_PROPERTY_WRITE_SOURCE),
        generated_specs=tuple(generated_specs),
    )


def encode_cr3_atom(atom_type: str, payload: bytes) -> bytes:
    size = len(payload) + 8
    if size > 0xFFFFFFFF:
        return (
            (1).to_bytes(4, byteorder="big")
            + atom_type.encode("latin-1")
            + (len(payload) + 16).to_bytes(8, byteorder="big")
            + payload
        )
    return size.to_bytes(4, byteorder="big") + atom_type.encode("latin-1") + payload


def rebuild_cr3_atom_with_nested_replacements(
    data: bytes,
    record: Cr3AtomRecord,
    replacements_by_offset: dict[int, Cr3AtomReplacement],
    replaced_atom_offsets: list[int],
    write_last_atoms: list[bytes],
) -> bytes | None:
    replacement = replacements_by_offset.get(record.offset)
    if replacement is not None:
        replaced_atom_offsets.append(record.offset)
        if replacement.write_last:
            write_last_atoms.append(replacement.new_atom)
            return b""
        return replacement.new_atom

    if not cr3_atom_has_nested_replacement(record, replacements_by_offset):
        return data[record.offset : record.offset + record.size]
    if record.atom_type == "moov":
        return rebuild_cr3_container_atom_children(
            data,
            record,
            record.payload_offset,
            record.offset + record.size,
            replacements_by_offset,
            replaced_atom_offsets,
            write_last_atoms,
        )
    if record.atom_type == "uuid":
        boundary = inspect_cr3_uuid_atom_boundary(data, record)
        if boundary.status != "ready" or boundary.kind != "canon":
            return None
        child_payload = rebuild_cr3_child_atom_bytes(
            data,
            boundary.payload_offset or 0,
            record.offset + record.size,
            replacements_by_offset,
            replaced_atom_offsets,
            write_last_atoms,
        )
        if child_payload is None or boundary.uuid_identifier is None:
            return None
        return encode_cr3_atom("uuid", boundary.uuid_identifier + child_payload)
    return None


def rebuild_cr3_container_atom_children(
    data: bytes,
    record: Cr3AtomRecord,
    children_start_offset: int,
    children_end_offset: int,
    replacements_by_offset: dict[int, Cr3AtomReplacement],
    replaced_atom_offsets: list[int],
    write_last_atoms: list[bytes],
) -> bytes | None:
    child_payload = rebuild_cr3_child_atom_bytes(
        data,
        children_start_offset,
        children_end_offset,
        replacements_by_offset,
        replaced_atom_offsets,
        write_last_atoms,
    )
    if child_payload is None:
        return None
    return encode_cr3_atom(record.atom_type, child_payload)


def rebuild_cr3_child_atom_bytes(
    data: bytes,
    children_start_offset: int,
    children_end_offset: int,
    replacements_by_offset: dict[int, Cr3AtomReplacement],
    replaced_atom_offsets: list[int],
    write_last_atoms: list[bytes],
) -> bytes | None:
    child_scan = scan_cr3_atoms_in_nested_range(data, children_start_offset, children_end_offset)
    if child_scan is None:
        return None
    rebuilt = bytearray()
    for child in child_scan:
        child_bytes = rebuild_cr3_atom_with_nested_replacements(
            data,
            child,
            replacements_by_offset,
            replaced_atom_offsets,
            write_last_atoms,
        )
        if child_bytes is None:
            return None
        rebuilt.extend(child_bytes)
    return bytes(rebuilt)


def scan_cr3_atoms_in_nested_range(
    data: bytes,
    start_offset: int,
    end_offset: int,
) -> tuple[Cr3AtomRecord, ...] | None:
    scan = scan_cr3_top_level_atoms(data[start_offset:end_offset])
    if not scan.ready:
        return None
    return tuple(
        Cr3AtomRecord(
            offset=start_offset + record.offset,
            atom_type=record.atom_type,
            size=record.size,
            header_size=record.header_size,
            payload_offset=start_offset + record.payload_offset,
            payload_size=record.payload_size,
        )
        for record in scan.records
    )


def cr3_atom_has_nested_replacement(
    record: Cr3AtomRecord,
    replacements_by_offset: dict[int, Cr3AtomReplacement],
) -> bool:
    return any(
        record.offset < replacement_offset < record.offset + record.size
        for replacement_offset in replacements_by_offset
    )


def cr3_xmp_uuid_payload_handoff_blocked(
    status: Cr3XmpUuidPayloadHandoffStatus,
) -> Cr3XmpUuidPayloadHandoff:
    return Cr3XmpUuidPayloadHandoff(
        status=status,
        replacement=None,
        final_emission=None,
        xmp_uuid_atom_offset=None,
        original_xmp_packet_byte_count=0,
        rewritten_xmp_packet_byte_count=0,
        changed_xmp_properties=0,
        deleted_xmp_properties=0,
        evidence_ids=cr3_xmp_uuid_payload_handoff_sources(()),
    )


def cr3_xmp_uuid_payload_handoff_sources(
    extra_sources: tuple[EvidenceId, ...],
) -> tuple[EvidenceId, ...]:
    return unique_sources(
        (
            QUICKTIME_XMP_UUID_SOURCE,
            CR3_QUICKTIME_MAP_SOURCE,
            CR3_UUID_WRITE_SOURCE,
            XMP_DC_SUBJECT_SOURCE,
            XMP_EXIF_EXPOSURE_COMPENSATION_SOURCE,
            XMP_PROPERTY_WRITE_EVIDENCE_ID,
            *extra_sources,
        )
    )


def cr3_ctbo_uuid_registrations(
    data: bytes,
    records: tuple[Cr3AtomRecord | Cr3AtomTreeRecord, ...],
) -> tuple[Cr3CtboOffsetRegistration, ...]:
    registrations: list[Cr3CtboOffsetRegistration] = []
    for record in records:
        atom = record.atom if isinstance(record, Cr3AtomTreeRecord) else record
        if atom.atom_type != "uuid":
            continue
        boundary = inspect_cr3_uuid_atom_boundary(data, atom)
        if boundary.status != "ready" or boundary.ctbo_item_id is None:
            continue
        registrations.append(
            Cr3CtboOffsetRegistration(
                boundary.ctbo_item_id,
                atom.offset,
                atom.size,
            )
        )
    return tuple(registrations)


def cr3_ctbo_record(
    records: tuple[Cr3AtomTreeRecord, ...],
) -> Cr3AtomTreeRecord | None:
    ctbo_records = tuple(record for record in records if record.atom.atom_type == "CTBO")
    if len(ctbo_records) != 1:
        return None
    return ctbo_records[0]


def decode_single_cr3_atom(data: bytes) -> Cr3AtomRecord:
    scan = scan_cr3_top_level_atoms(data)
    if not scan.ready or len(scan.records) != 1:
        raise ValueError("Expected exactly one encoded CR3 atom")
    return scan.records[0]


def cr3_bounded_emission_blocked(status: Cr3BoundedEmissionStatus) -> Cr3BoundedEmissionResult:
    return Cr3BoundedEmissionResult(
        status=status,
        data=None,
        replaced_atom_offsets=(),
        write_last_atom_count=0,
        ctbo_atom_offset=None,
        mdat_atom_offset=None,
        uuid_registrations=(),
        evidence_ids=cr3_bounded_emission_sources(),
    )


def cr3_bounded_emission_sources() -> tuple[EvidenceId, ...]:
    return unique_sources(
        (
            CR3_QUICKTIME_MAP_SOURCE,
            QUICKTIME_XMP_UUID_SOURCE,
            CR3_UUID_WRITE_SOURCE,
            CR3_MDAT_EDIT_SOURCE,
            CR3_MDAT_BOUNDARY_SOURCE,
            CR3_CTBO_FIXUP_SOURCE,
            CR3_WRITE_LAST_SOURCE,
            CR3_FINAL_EMIT_SOURCE,
        )
    )


def plan_canon_raw_final_emission(
    data: bytes,
    classification: CanonRawWriteRequestClassification,
) -> CanonRawFinalEmissionPlan:
    transaction = plan_canon_raw_container_transaction(data, classification)
    if transaction.container_kind == "cr2_tiff":
        return plan_cr2_final_emission(transaction)
    if transaction.container_kind == "cr3_quicktime":
        return plan_cr3_final_emission(transaction)
    return CanonRawFinalEmissionPlan(
        status="unsupported_container",
        container_kind="unknown",
        requested_tags=transaction.requested_tags,
        steps=(),
        blockers=(
            CanonRawFinalEmissionBlocker(
                "recognized_container_required",
                "Final emission requires either the CR2 WriteCR2 route or CR3 map.",
                (WRITE_CR2_SOURCE, CR3_QUICKTIME_MAP_SOURCE),
            ),
        ),
        evidence_ids=(WRITE_CR2_SOURCE, CR3_QUICKTIME_MAP_SOURCE),
    )


def plan_cr2_final_emission(
    transaction: CanonRawContainerTransactionPlan,
) -> CanonRawFinalEmissionPlan:
    readiness = transaction.cr2_emission_readiness_plan
    if readiness is None:
        raise ValueError("Expected CR2 transaction with emission readiness plan")
    header_sources = (
        transaction.cr2_header_fixup_plan.evidence_ids
        if transaction.cr2_header_fixup_plan is not None
        else (WRITE_CR2_SOURCE,)
    )
    tiff_sources = (
        transaction.cr2_shared_tiff_emitter_contract.evidence_ids
        if transaction.cr2_shared_tiff_emitter_contract is not None
        else readiness.evidence_ids
    )
    payload_sources = (
        transaction.cr2_payload_copy_ledger.evidence_ids
        if transaction.cr2_payload_copy_ledger is not None
        else readiness.evidence_ids
    )
    blockers = tuple(
        CanonRawFinalEmissionBlocker(
            blocker.code,
            blocker.reason,
            blocker.evidence_ids,
        )
        for blocker in transaction.blockers
    )
    steps = (
        CanonRawFinalEmissionStep(
            1,
            "validate_container_route",
            "Require the CR2 signature and WriteCR2 route before emitting bytes.",
            True,
            (WRITE_CR2_SOURCE,),
        ),
        CanonRawFinalEmissionStep(
            2,
            "emit_rebuilt_cr2_header",
            "Emit the rebuilt 16-byte CR2 header with IFD0 at byte 16 and LastIFD set.",
            True,
            header_sources,
        ),
        CanonRawFinalEmissionStep(
            3,
            "emit_rewritten_tiff_directories",
            "Emit the shared WriteExif TIFF directory payload for IFD0, ExifIFD, and MakerNotes.",
            False,
            tiff_sources,
        ),
        CanonRawFinalEmissionStep(
            4,
            "copy_recorded_cr2_image_data_segments",
            "Copy image-data ranges recorded by the TIFF rewrite ledger after metadata bytes.",
            True,
            payload_sources,
        ),
        CanonRawFinalEmissionStep(
            5,
            "append_preserved_cr2_suffix",
            "Append non-TIFF suffix bytes preserved by the CR2 payload copy ledger.",
            True,
            payload_sources,
        ),
    )
    return CanonRawFinalEmissionPlan(
        status="cr2_final_emission_blocked",
        container_kind="cr2_tiff",
        requested_tags=transaction.requested_tags,
        steps=steps,
        blockers=blockers,
        evidence_ids=unique_sources(
            (
                *readiness.evidence_ids,
                *transaction.evidence_ids,
                *(reference for step in steps for reference in step.evidence_ids),
            )
        ),
    )


def plan_cr3_final_emission(
    transaction: CanonRawContainerTransactionPlan,
) -> CanonRawFinalEmissionPlan:
    ledger = transaction.cr3_ledger
    if ledger is None:
        raise ValueError("Expected CR3 transaction with QuickTime rewrite ledger")
    blockers = tuple(
        CanonRawFinalEmissionBlocker(
            blocker.code,
            blocker.reason,
            blocker.evidence_ids,
        )
        for blocker in transaction.blockers
    )
    steps = (
        CanonRawFinalEmissionStep(
            1,
            "validate_container_route",
            "Require the CR3 QuickTime brand map before applying Canon UUID semantics.",
            True,
            (CR3_QUICKTIME_MAP_SOURCE,),
        ),
        CanonRawFinalEmissionStep(
            2,
            "walk_and_rebuild_cr3_atoms",
            "Traverse QuickTime atoms and rebuild metadata atom bytes before media emission.",
            False,
            (CR3_QUICKTIME_MAP_SOURCE, CR3_FINAL_EMIT_SOURCE),
        ),
        CanonRawFinalEmissionStep(
            3,
            "replace_cr3_xmp_uuid_payload",
            "Replace the top-level XMP uuid packet using oracle padding rules.",
            False,
            (QUICKTIME_XMP_UUID_SOURCE, CR3_UUID_WRITE_SOURCE),
        ),
        CanonRawFinalEmissionStep(
            4,
            "rewrite_cr3_canon_cmt_tiff_payloads",
            "Rewrite Canon CMT TIFF payloads for ExifIFD values without guessing MakerNote layout.",
            False,
            (CR3_CANON_UUID_SOURCE, CR3_CMT_TIFF_PAYLOAD_SOURCE),
        ),
        CanonRawFinalEmissionStep(
            5,
            "update_cr3_atom_sizes_and_uuid_offsets",
            "Update changed atom sizes and register modified uuid offsets for CTBO repair.",
            False,
            (CR3_ATOM_SIZE_UPDATE_SOURCE, CR3_CTBO_FIXUP_SOURCE),
        ),
        CanonRawFinalEmissionStep(
            6,
            "copy_or_edit_cr3_mdat_payloads",
            "Copy or edit mdat payloads only when ItemInfo boundary gates are satisfied.",
            False,
            (CR3_MDAT_EDIT_SOURCE, CR3_MDAT_BOUNDARY_SOURCE),
        ),
        CanonRawFinalEmissionStep(
            7,
            "patch_cr3_ctbo_item_offsets",
            "Patch CTBO item offsets and sizes after new uuid and mdat positions are known.",
            False,
            (CR3_CTBO_FIXUP_SOURCE,),
        ),
        CanonRawFinalEmissionStep(
            8,
            "emit_cr3_write_last_atoms",
            "Emit Canon2 WriteLast atoms after mdat, matching WriteQuickTime's final order.",
            False,
            (CR3_WRITE_LAST_SOURCE, CR3_FINAL_EMIT_SOURCE),
        ),
    )
    return CanonRawFinalEmissionPlan(
        status="cr3_final_emission_blocked",
        container_kind="cr3_quicktime",
        requested_tags=transaction.requested_tags,
        steps=steps,
        blockers=blockers,
        evidence_ids=unique_sources(
            (
                *ledger.evidence_ids,
                *transaction.evidence_ids,
                *(reference for step in steps for reference in step.evidence_ids),
            )
        ),
    )
