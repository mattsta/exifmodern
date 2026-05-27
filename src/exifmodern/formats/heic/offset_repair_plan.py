"""Non-mutating HEIC ItemInfo global-offset repair planning.

ExifTool's HEIC ItemInformation writer edits ``iinf``/``iref``/``iloc`` boxes
and then repairs global media offsets after any ``mdat`` changes.  This module
models that repair contract only; it deliberately does not mutate HEIC bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.heic.item_info_atoms import HeicScheduledMdatEdits
from exifmodern.formats.heic.item_info_write_plan import (
    HEIC_ITEM_INFO_MAP_EVIDENCE_ID,
    WRITE_ITEM_INFO_BOX_INSERT_EVIDENCE_ID,
    WRITE_ITEM_INFO_CREATE_EVIDENCE_ID,
    WRITE_ITEM_INFO_REWRITE_EVIDENCE_ID,
    WRITE_MDAT_EDIT_EVIDENCE_ID,
    WRITE_OFFSET_FIXUP_EVIDENCE_ID,
    HeicItemInfoOperation,
    HeicItemInfoState,
    HeicItemInfoWriteClassification,
)
from exifmodern.json_types import JsonObject

type HeicOffsetRepairPlanStatus = Literal["deferred_global_offset_repair_plan"]
type HeicOffsetRepairPrerequisiteCode = Literal[
    "heic_item_info_container",
    "top_level_meta_box",
    "iinf_and_iloc_boxes",
    "mdat_box",
    "primary_item_reference",
    "existing_xmp_item_has_single_internal_extent",
    "offset_pointer_sites_discovered_before_box_insertion",
]
type HeicOffsetRepairPhaseName = Literal[
    "discover_offset_pointer_sites",
    "rebuild_item_info_boxes",
    "schedule_mdat_item_edits",
    "split_resize_mdat_chunks",
    "compute_new_mdat_positions",
    "rewrite_recorded_offsets",
]
type HeicOffsetRepairSafetyGateCode = Literal[
    "mutation_deferred_until_all_repairs_are_modeled",
    "reject_mdat_edit_crossing_boundary",
    "reject_32_bit_mdat_growth_past_uint32",
    "reject_offset_width_promotion",
    "reject_iloc_external_or_relative_offsets",
    "reject_movie_fragments_segment_indexes_and_aux_offsets",
    "reject_mixed_internal_external_media_data",
    "require_exactly_one_new_item_offset_pointer",
    "reject_existing_multi_extent_item_rewrite",
    "reject_iloc_length_width_promotion",
]
type HeicOffsetPointerKind = Literal[
    "stco_table",
    "co64_table",
    "iloc_extent_offset",
    "iloc_base_offset",
    "gps_table",
    "cr3_ctbo",
]
type HeicOffsetRepairTarget = Literal[
    "iinf_size_and_item_count",
    "iref_size_or_insertion",
    "iloc_size_item_count_and_extent_lengths",
    "iloc_new_item_offset_pointer",
    "mdat_header_size",
    "mdat_chunk_boundaries",
    "recorded_stco_co64_offsets",
    "recorded_iloc_offsets",
    "recorded_gps_offsets",
    "cr3_ctbo_offsets",
]

HANDLE_ILOC_EVIDENCE_ID = "heic.offset_repair.handle_iloc"
QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID = "heic.offset_repair.offset_discovery"
QUICKTIME_SUBDIR_OFFSET_EVIDENCE_ID = "heic.offset_repair.subdir_offset"
WRITE_ITEM_INFO_DISPATCH_EVIDENCE_ID = "heic.offset_repair.item_info_dispatch"
MDAT_BOUNDARY_EVIDENCE_ID = "heic.offset_repair.mdat_boundary"
NEW_MDAT_POSITION_EVIDENCE_ID = "heic.offset_repair.new_mdat_position"
RECORDED_OFFSET_FIXUP_EVIDENCE_ID = "heic.offset_repair.recorded_offset_fixup"


@dataclass(frozen=True)
class HeicOffsetRepairPrerequisite:
    code: HeicOffsetRepairPrerequisiteCode
    satisfied: bool
    description: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "description": self.description,
            "satisfied": self.satisfied,
        }


@dataclass(frozen=True)
class HeicOffsetRepairSafetyGate:
    code: HeicOffsetRepairSafetyGateCode
    enforced: bool
    description: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "description": self.description,
            "enforced": self.enforced,
        }


@dataclass(frozen=True)
class HeicOffsetPointerRepair:
    kind: HeicOffsetPointerKind
    atom_type: str
    integer_size: int | None
    pointer_semantics: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "atom_type": self.atom_type,
            "integer_size": self.integer_size,
            "kind": self.kind,
            "pointer_semantics": self.pointer_semantics,
        }


@dataclass(frozen=True)
class HeicMdatEditRepairPlan:
    edit_count: int
    total_length_delta: int
    touched_item_ids: tuple[int, ...]
    requires_header_size_rewrite: bool
    requires_chunk_split: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "edit_count": self.edit_count,
            "requires_chunk_split": self.requires_chunk_split,
            "requires_header_size_rewrite": self.requires_header_size_rewrite,
            "total_length_delta": self.total_length_delta,
            "touched_item_ids": list(self.touched_item_ids),
        }


@dataclass(frozen=True)
class HeicOffsetRepairPhase:
    order: int
    name: HeicOffsetRepairPhaseName
    purpose: str
    repair_targets: tuple[HeicOffsetRepairTarget, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "name": self.name,
            "order": self.order,
            "purpose": self.purpose,
            "repair_targets": list(self.repair_targets),
        }


@dataclass(frozen=True)
class HeicItemInfoOffsetRepairPlan:
    status: HeicOffsetRepairPlanStatus
    operation: HeicItemInfoOperation
    supported_for_modern_mutation: bool
    prerequisites: tuple[HeicOffsetRepairPrerequisite, ...]
    safety_gates: tuple[HeicOffsetRepairSafetyGate, ...]
    pointer_repairs: tuple[HeicOffsetPointerRepair, ...]
    mdat_edit_repair: HeicMdatEditRepairPlan
    phases: tuple[HeicOffsetRepairPhase, ...]
    evidence_ids: tuple[str, ...]

    @property
    def prerequisite_codes(self) -> tuple[HeicOffsetRepairPrerequisiteCode, ...]:
        return tuple(prerequisite.code for prerequisite in self.prerequisites)

    @property
    def unsatisfied_prerequisite_codes(self) -> tuple[HeicOffsetRepairPrerequisiteCode, ...]:
        return tuple(
            prerequisite.code for prerequisite in self.prerequisites if not prerequisite.satisfied
        )

    @property
    def phase_names(self) -> tuple[HeicOffsetRepairPhaseName, ...]:
        return tuple(phase.name for phase in self.phases)

    @property
    def safety_gate_codes(self) -> tuple[HeicOffsetRepairSafetyGateCode, ...]:
        return tuple(gate.code for gate in self.safety_gates)

    def to_json(self) -> JsonObject:
        return {
            "mdat_edit_repair": self.mdat_edit_repair.to_json(),
            "operation": self.operation,
            "phases": [phase.to_json() for phase in self.phases],
            "pointer_repairs": [repair.to_json() for repair in self.pointer_repairs],
            "prerequisites": [prerequisite.to_json() for prerequisite in self.prerequisites],
            "safety_gates": [gate.to_json() for gate in self.safety_gates],
            "status": self.status,
            "supported_for_modern_mutation": self.supported_for_modern_mutation,
        }


def plan_heic_item_info_offset_repair(
    classification: HeicItemInfoWriteClassification,
    *,
    scheduled_mdat_edits: HeicScheduledMdatEdits | None = None,
) -> HeicItemInfoOffsetRepairPlan:
    """Build a source-backed global-offset repair plan for a classified HEIC write."""

    operation = first_operation(classification)
    state = classification.state
    return build_heic_item_info_offset_repair_plan(
        operation=operation,
        state=state,
        scheduled_mdat_edits=scheduled_mdat_edits,
    )


def build_heic_item_info_offset_repair_plan(
    *,
    operation: HeicItemInfoOperation,
    state: HeicItemInfoState | None = None,
    scheduled_mdat_edits: HeicScheduledMdatEdits | None = None,
) -> HeicItemInfoOffsetRepairPlan:
    """Build the deferred repair sequence required before HEIC mutation is safe."""

    pointer_repairs = default_pointer_repairs()
    mdat_edit_repair = build_mdat_edit_repair_plan(scheduled_mdat_edits)
    phases = offset_repair_phases(operation)
    safety_gates = offset_repair_safety_gates(operation)
    prerequisites = offset_repair_prerequisites(operation, state)
    evidence_ids = tuple(
        dict.fromkeys(
            (
                HEIC_ITEM_INFO_MAP_EVIDENCE_ID,
                HANDLE_ILOC_EVIDENCE_ID,
                QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID,
                QUICKTIME_SUBDIR_OFFSET_EVIDENCE_ID,
                WRITE_ITEM_INFO_DISPATCH_EVIDENCE_ID,
                WRITE_ITEM_INFO_CREATE_EVIDENCE_ID,
                WRITE_ITEM_INFO_REWRITE_EVIDENCE_ID,
                WRITE_ITEM_INFO_BOX_INSERT_EVIDENCE_ID,
                MDAT_BOUNDARY_EVIDENCE_ID,
                NEW_MDAT_POSITION_EVIDENCE_ID,
                RECORDED_OFFSET_FIXUP_EVIDENCE_ID,
                WRITE_MDAT_EDIT_EVIDENCE_ID,
                WRITE_OFFSET_FIXUP_EVIDENCE_ID,
            )
        )
    )
    return HeicItemInfoOffsetRepairPlan(
        status="deferred_global_offset_repair_plan",
        operation=operation,
        supported_for_modern_mutation=False,
        prerequisites=prerequisites,
        safety_gates=safety_gates,
        pointer_repairs=pointer_repairs,
        mdat_edit_repair=mdat_edit_repair,
        phases=phases,
        evidence_ids=evidence_ids,
    )


def offset_repair_prerequisites(
    operation: HeicItemInfoOperation,
    state: HeicItemInfoState | None,
) -> tuple[HeicOffsetRepairPrerequisite, ...]:
    is_known_heic = state is not None and state.container_kind == "heic_item_info"
    has_meta = state is not None and state.has_top_level_meta
    has_iinf_iloc = state is not None and state.has_iinf and state.has_iloc
    has_mdat = state is not None and state.has_mdat
    has_primary = state is not None and (state.primary_item_id is not None or bool(state.items))
    prerequisites = [
        HeicOffsetRepairPrerequisite(
            code="heic_item_info_container",
            satisfied=is_known_heic,
            description="The request must target HEIC/HEIF ItemInformation metadata.",
            evidence_ids=(HEIC_ITEM_INFO_MAP_EVIDENCE_ID,),
        ),
        HeicOffsetRepairPrerequisite(
            code="top_level_meta_box",
            satisfied=has_meta,
            description="WriteItemInfo is dispatched from the top-level Meta container.",
            evidence_ids=(WRITE_ITEM_INFO_DISPATCH_EVIDENCE_ID,),
        ),
        HeicOffsetRepairPrerequisite(
            code="iinf_and_iloc_boxes",
            satisfied=has_iinf_iloc,
            description=(
                "ExifTool can insert a missing iref, but creating ItemInfo metadata "
                "requires existing iinf and iloc boxes."
            ),
            evidence_ids=(
                WRITE_ITEM_INFO_CREATE_EVIDENCE_ID,
                WRITE_ITEM_INFO_BOX_INSERT_EVIDENCE_ID,
            ),
        ),
        HeicOffsetRepairPrerequisite(
            code="mdat_box",
            satisfied=has_mdat,
            description="ItemInfo payload edits must be applied to top-level media data.",
            evidence_ids=(MDAT_BOUNDARY_EVIDENCE_ID,),
        ),
        HeicOffsetRepairPrerequisite(
            code="primary_item_reference",
            satisfied=has_primary,
            description=(
                "New XMP/EXIF ItemInfo entries must cdsc-reference the primary item; "
                "ExifTool falls back to the lowest item only when pitm is absent."
            ),
            evidence_ids=(WRITE_ITEM_INFO_CREATE_EVIDENCE_ID,),
        ),
        HeicOffsetRepairPrerequisite(
            code="offset_pointer_sites_discovered_before_box_insertion",
            satisfied=False,
            description=(
                "The modern writer must first persist every stco/co64/iloc/gps/CTBO "
                "pointer location and then update locations shifted by inserted iinf/"
                "iref/iloc entries."
            ),
            evidence_ids=(
                QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID,
                WRITE_ITEM_INFO_BOX_INSERT_EVIDENCE_ID,
                QUICKTIME_SUBDIR_OFFSET_EVIDENCE_ID,
            ),
        ),
    ]
    if operation in {"rewrite_existing_xmp_item", "delete_existing_xmp_item"}:
        prerequisites.append(
            HeicOffsetRepairPrerequisite(
                code="existing_xmp_item_has_single_internal_extent",
                satisfied=has_single_internal_primary_xmp_extent(state),
                description=(
                    "Existing ItemInfo metadata rewrite must be modeled as a single "
                    "in-file extent; ExifTool errors after trying multi-part rewrite."
                ),
                evidence_ids=(WRITE_ITEM_INFO_REWRITE_EVIDENCE_ID, MDAT_BOUNDARY_EVIDENCE_ID),
            )
        )
    return tuple(prerequisites)


def offset_repair_safety_gates(
    operation: HeicItemInfoOperation,
) -> tuple[HeicOffsetRepairSafetyGate, ...]:
    gates = [
        HeicOffsetRepairSafetyGate(
            code="mutation_deferred_until_all_repairs_are_modeled",
            enforced=True,
            description=("This plan is descriptive only and must not enable real HEIC mutation."),
            evidence_ids=(WRITE_OFFSET_FIXUP_EVIDENCE_ID,),
        ),
        HeicOffsetRepairSafetyGate(
            code="reject_mdat_edit_crossing_boundary",
            enforced=True,
            description=(
                "Every ItemInfo mdat replacement or insertion must fit one mdat; "
                "ExifTool errors if an item edit runs across a boundary."
            ),
            evidence_ids=(MDAT_BOUNDARY_EVIDENCE_ID,),
        ),
        HeicOffsetRepairSafetyGate(
            code="reject_32_bit_mdat_growth_past_uint32",
            enforced=True,
            description=(
                "A 32-bit mdat header may be resized only while the new atom size "
                "still fits uint32."
            ),
            evidence_ids=(MDAT_BOUNDARY_EVIDENCE_ID,),
        ),
        HeicOffsetRepairSafetyGate(
            code="reject_offset_width_promotion",
            enforced=True,
            description=(
                "Recorded 32-bit stco/iloc/gps offsets must not overflow because "
                "ExifTool refuses promotion to 64-bit offsets during this pass."
            ),
            evidence_ids=(RECORDED_OFFSET_FIXUP_EVIDENCE_ID,),
        ),
        HeicOffsetRepairSafetyGate(
            code="reject_iloc_external_or_relative_offsets",
            enforced=True,
            description=(
                "Only construction-method zero and in-file data-reference iloc "
                "offsets participate in global repair; other iloc offsets are constant."
            ),
            evidence_ids=(HANDLE_ILOC_EVIDENCE_ID,),
        ),
        HeicOffsetRepairSafetyGate(
            code="reject_movie_fragments_segment_indexes_and_aux_offsets",
            enforced=True,
            description=(
                "The writer must reject offset-bearing moof, mfra, sidx, and saio "
                "boxes until those offset models are implemented."
            ),
            evidence_ids=(QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID,),
        ),
        HeicOffsetRepairSafetyGate(
            code="reject_mixed_internal_external_media_data",
            enforced=True,
            description=(
                "Files mixing internal and external media data cannot be rewritten "
                "because ExifTool cannot safely decide which offsets to repair."
            ),
            evidence_ids=(QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID,),
        ),
        HeicOffsetRepairSafetyGate(
            code="require_exactly_one_new_item_offset_pointer",
            enforced=True,
            description=(
                "A newly inserted ItemInfo mdat chunk must have exactly one recorded "
                "iloc offset pointer associated with its item ID."
            ),
            evidence_ids=(WRITE_ITEM_INFO_CREATE_EVIDENCE_ID, MDAT_BOUNDARY_EVIDENCE_ID),
        ),
        HeicOffsetRepairSafetyGate(
            code="reject_iloc_length_width_promotion",
            enforced=True,
            description=(
                "Existing extent_length updates may use the current iloc length field "
                "width only; ExifTool refuses length promotion to 64 bits."
            ),
            evidence_ids=(WRITE_ITEM_INFO_REWRITE_EVIDENCE_ID,),
        ),
    ]
    if operation in {"rewrite_existing_xmp_item", "delete_existing_xmp_item"}:
        gates.append(
            HeicOffsetRepairSafetyGate(
                code="reject_existing_multi_extent_item_rewrite",
                enforced=True,
                description=(
                    "Existing XMP/EXIF ItemInfo rewrite must not proceed for "
                    "multi-part metadata until the multi-extent mdat edit model exists."
                ),
                evidence_ids=(WRITE_ITEM_INFO_REWRITE_EVIDENCE_ID,),
            )
        )
    return tuple(gates)


def default_pointer_repairs() -> tuple[HeicOffsetPointerRepair, ...]:
    return (
        HeicOffsetPointerRepair(
            kind="stco_table",
            atom_type="stco",
            integer_size=4,
            pointer_semantics="Sample chunk offsets are absolute file offsets into media data.",
            evidence_ids=(
                QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID,
                RECORDED_OFFSET_FIXUP_EVIDENCE_ID,
            ),
        ),
        HeicOffsetPointerRepair(
            kind="co64_table",
            atom_type="co64",
            integer_size=8,
            pointer_semantics=(
                "64-bit sample chunk offsets are absolute file offsets into media data."
            ),
            evidence_ids=(
                QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID,
                RECORDED_OFFSET_FIXUP_EVIDENCE_ID,
            ),
        ),
        HeicOffsetPointerRepair(
            kind="iloc_extent_offset",
            atom_type="iloc",
            integer_size=None,
            pointer_semantics=(
                "For absolute in-file ItemLocation entries, ExifTool repairs either "
                "extent_offset or base_offset depending on which component is larger."
            ),
            evidence_ids=(HANDLE_ILOC_EVIDENCE_ID, RECORDED_OFFSET_FIXUP_EVIDENCE_ID),
        ),
        HeicOffsetPointerRepair(
            kind="iloc_base_offset",
            atom_type="iloc",
            integer_size=None,
            pointer_semantics=(
                "When iloc offset_size is zero or base_offset is the selected larger "
                "component, base_offset is recorded as the repair pointer."
            ),
            evidence_ids=(
                HANDLE_ILOC_EVIDENCE_ID,
                WRITE_ITEM_INFO_CREATE_EVIDENCE_ID,
                RECORDED_OFFSET_FIXUP_EVIDENCE_ID,
            ),
        ),
        HeicOffsetPointerRepair(
            kind="gps_table",
            atom_type="gps ",
            integer_size=4,
            pointer_semantics="QuickTime gps table entries are repaired like stco offsets.",
            evidence_ids=(
                QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID,
                RECORDED_OFFSET_FIXUP_EVIDENCE_ID,
            ),
        ),
        HeicOffsetPointerRepair(
            kind="cr3_ctbo",
            atom_type="CTBO",
            integer_size=8,
            pointer_semantics=(
                "CR3 CTBO entries are updated from uuid and first-mdat positions; "
                "this is documented as out of scope for HEIC ItemInfo mutation."
            ),
            evidence_ids=(
                QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID,
                RECORDED_OFFSET_FIXUP_EVIDENCE_ID,
            ),
        ),
    )


def build_mdat_edit_repair_plan(
    scheduled_mdat_edits: HeicScheduledMdatEdits | None,
) -> HeicMdatEditRepairPlan:
    if scheduled_mdat_edits is None:
        return HeicMdatEditRepairPlan(
            edit_count=0,
            total_length_delta=0,
            touched_item_ids=(),
            requires_header_size_rewrite=False,
            requires_chunk_split=False,
            evidence_ids=(MDAT_BOUNDARY_EVIDENCE_ID, NEW_MDAT_POSITION_EVIDENCE_ID),
        )
    edits = scheduled_mdat_edits.edits
    return HeicMdatEditRepairPlan(
        edit_count=len(edits),
        total_length_delta=scheduled_mdat_edits.length_delta,
        touched_item_ids=tuple(dict.fromkeys(edit.item_id for edit in edits)),
        requires_header_size_rewrite=any(edit.length_delta for edit in edits),
        requires_chunk_split=bool(edits),
        evidence_ids=(MDAT_BOUNDARY_EVIDENCE_ID, NEW_MDAT_POSITION_EVIDENCE_ID),
    )


def offset_repair_phases(
    operation: HeicItemInfoOperation,
) -> tuple[HeicOffsetRepairPhase, ...]:
    item_info_targets: tuple[HeicOffsetRepairTarget, ...]
    if operation == "create_xmp_item":
        item_info_targets = (
            "iinf_size_and_item_count",
            "iref_size_or_insertion",
            "iloc_size_item_count_and_extent_lengths",
            "iloc_new_item_offset_pointer",
        )
    elif operation in {"rewrite_existing_xmp_item", "delete_existing_xmp_item"}:
        item_info_targets = ("iloc_size_item_count_and_extent_lengths",)
    else:
        item_info_targets = ()
    return (
        HeicOffsetRepairPhase(
            order=1,
            name="discover_offset_pointer_sites",
            purpose=(
                "Record every offset-bearing atom and iloc pointer location before "
                "any inserted ItemInfo bytes can shift those pointers."
            ),
            repair_targets=(
                "recorded_stco_co64_offsets",
                "recorded_iloc_offsets",
                "recorded_gps_offsets",
                "cr3_ctbo_offsets",
            ),
            evidence_ids=(
                QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID,
                HANDLE_ILOC_EVIDENCE_ID,
                QUICKTIME_SUBDIR_OFFSET_EVIDENCE_ID,
            ),
        ),
        HeicOffsetRepairPhase(
            order=2,
            name="rebuild_item_info_boxes",
            purpose=(
                "Apply the ItemInformation box-level changes: update extent lengths "
                "for existing items or append new infe/cdsc/iloc entries and adjust counts."
            ),
            repair_targets=item_info_targets,
            evidence_ids=(
                WRITE_ITEM_INFO_CREATE_EVIDENCE_ID,
                WRITE_ITEM_INFO_REWRITE_EVIDENCE_ID,
                WRITE_ITEM_INFO_BOX_INSERT_EVIDENCE_ID,
            ),
        ),
        HeicOffsetRepairPhase(
            order=3,
            name="schedule_mdat_item_edits",
            purpose=(
                "Represent existing item replacement/deletion or new item insertion as "
                "ItemInfo mdat edits tagged with the affected item ID."
            ),
            repair_targets=("mdat_chunk_boundaries",),
            evidence_ids=(WRITE_ITEM_INFO_CREATE_EVIDENCE_ID, WRITE_ITEM_INFO_REWRITE_EVIDENCE_ID),
        ),
        HeicOffsetRepairPhase(
            order=4,
            name="split_resize_mdat_chunks",
            purpose=(
                "Validate each edit against one mdat, update the mdat header size, split "
                "the original media span, and initialize new item offsets when needed."
            ),
            repair_targets=(
                "mdat_header_size",
                "mdat_chunk_boundaries",
                "iloc_new_item_offset_pointer",
            ),
            evidence_ids=(MDAT_BOUNDARY_EVIDENCE_ID,),
        ),
        HeicOffsetRepairPhase(
            order=5,
            name="compute_new_mdat_positions",
            purpose=(
                "After the non-media output buffer is complete, compute every rewritten "
                "media chunk's new absolute file position."
            ),
            repair_targets=("mdat_chunk_boundaries",),
            evidence_ids=(NEW_MDAT_POSITION_EVIDENCE_ID,),
        ),
        HeicOffsetRepairPhase(
            order=6,
            name="rewrite_recorded_offsets",
            purpose=(
                "Rewrite recorded stco/co64/iloc/gps offsets by matching old offsets and "
                "optional item IDs to the new mdat chunk positions."
            ),
            repair_targets=(
                "recorded_stco_co64_offsets",
                "recorded_iloc_offsets",
                "recorded_gps_offsets",
                "cr3_ctbo_offsets",
            ),
            evidence_ids=(RECORDED_OFFSET_FIXUP_EVIDENCE_ID,),
        ),
    )


def first_operation(
    classification: HeicItemInfoWriteClassification,
) -> HeicItemInfoOperation:
    for tag in classification.tags:
        if tag.operation != "unsupported_request":
            return tag.operation
    return "unsupported_request"


def has_single_internal_primary_xmp_extent(state: HeicItemInfoState | None) -> bool:
    if state is None:
        return False
    if len(state.primary_xmp_items) != 1:
        return False
    item = state.primary_xmp_items[0]
    return (
        item.construction_method == 0 and item.data_reference_index == 0 and len(item.extents) == 1
    )
