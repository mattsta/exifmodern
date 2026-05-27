"""Source-backed CR3 QuickTime/Canon UUID transaction ledger.

This ledger decomposes oracle's CR3 write behavior into typed transaction
entries.  It is intentionally non-mutating: it records traversal, UUID
selection, XMP/CMT payload replacement, CTBO/mdat fixups, atom-size updates, and
emission gates that a future QuickTime rewrite engine must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.canon_raw.cr3_mutation_plan import (
    CR3_CTBO_ID_SOURCE,
    CR3_MDAT_BOUNDARY_SOURCE,
    CR3_MDAT_EDIT_SOURCE,
    CR3_OFFSET_COLLECTION_SOURCE,
    CR3_UUID_WRITE_SOURCE,
    CR3_WRITE_LAST_SOURCE,
    QUICKTIME_XMP_UUID_SOURCE,
    build_cr3_canon_uuid_xmp_ctbo_mutation_plan,
    unique_sources,
)
from exifmodern.formats.canon_raw.write_plan import (
    CR3_CANON_UUID_SOURCE,
    CR3_CTBO_FIXUP_SOURCE,
    CR3_QUICKTIME_CANON2_SOURCE,
    CR3_QUICKTIME_MAP_SOURCE,
    EXIF_EXPOSURE_COMPENSATION_SOURCE,
    XMP_DC_SUBJECT_SOURCE,
    XMP_EXIF_EXPOSURE_COMPENSATION_SOURCE,
    CanonRawWriteRequestClassification,
    CanonRawWriteSurface,
)
from exifmodern.json_types import JsonObject

type EvidenceId = str

type Cr3TransactionLedgerStatus = Literal["plan_only_deferred"]
type Cr3TransactionConcern = Literal[
    "quicktime_atom_traversal",
    "canon_uuid_selection",
    "xmp_payload_replacement",
    "ctbo_offset_fixup",
    "mdat_edit_planning",
    "atom_size_update",
    "output_emission_gate",
]
type Cr3TransactionPhase = Literal[
    "input_gate",
    "atom_traversal",
    "payload_rewrite",
    "atom_size_rewrite",
    "mdat_edit",
    "offset_fixup",
    "transaction_emit",
]
type Cr3TransactionEntryCode = Literal[
    "require_cr3_ftyp_and_quicktime_context",
    "walk_quicktime_atoms_and_collect_offsets",
    "route_cr3_groups_through_write_map",
    "select_top_level_xmp_uuid_atom",
    "select_canon_uuid_cmt_tiff_atoms",
    "replace_xmp_uuid_payload_preserving_padding",
    "rewrite_canon_cmt_tiff_payloads_preserving_padding",
    "stage_write_last_canon_uuid2_atoms",
    "update_modified_atom_sizes_and_uuid_offsets",
    "plan_mdat_edits_and_header_growth",
    "assign_new_mdat_positions",
    "patch_ctbo_item_offsets_and_sizes",
    "emit_rebuilt_atoms_mdat_and_write_last",
]
type Cr3EmissionGateCode = Literal[
    "no_byte_mutation_from_ledger",
    "quicktime_cr3_brand_required",
    "offset_sensitive_atoms_must_be_supported",
    "xmp_uuid_prefix_and_padding_required",
    "canon_uuid_cmt_padding_required",
    "modified_uuid_offsets_registered",
    "mdat_required_for_ctbo_fixup",
    "iteminfo_mdat_edits_must_not_cross_boundary",
    "ctbo_entries_resolve_known_item_ids",
    "canon2_write_last_after_mdat",
    "atom_size_growth_supported",
]

QUICKTIME_UUID_SELECTOR_SOURCE = "canon_raw.quicktime_uuid_selector"
QUICKTIME_CANON_UUID_SELECTOR_SOURCE = "canon_raw.quicktime_canon_uuid_selector"
CR3_CMT_TIFF_PAYLOAD_SOURCE = "canon_raw.cr3_cmt_tiff_payload"
CR3_ATOM_SIZE_UPDATE_SOURCE = "canon_raw.cr3_atom_size_update"
CR3_FINAL_EMIT_SOURCE = "canon_raw.cr3_final_emit"


@dataclass(frozen=True)
class Cr3TransactionLedgerEntry:
    order: int
    code: Cr3TransactionEntryCode
    concern: Cr3TransactionConcern
    phase: Cr3TransactionPhase
    description: str
    depends_on: tuple[Cr3TransactionEntryCode, ...]
    consumes: tuple[str, ...]
    records: tuple[str, ...]
    gates: tuple[Cr3EmissionGateCode, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "concern": self.concern,
            "consumes": list(self.consumes),
            "depends_on": list(self.depends_on),
            "description": self.description,
            "gates": list(self.gates),
            "order": self.order,
            "phase": self.phase,
            "records": list(self.records),
        }


@dataclass(frozen=True)
class Cr3OutputEmissionGate:
    code: Cr3EmissionGateCode
    required_entries: tuple[Cr3TransactionEntryCode, ...]
    invariant: str
    failure_response: str
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def blocks_mutation(self) -> bool:
        return True

    def to_json(self) -> JsonObject:
        return {
            "blocks_mutation": self.blocks_mutation,
            "code": self.code,
            "failure_response": self.failure_response,
            "invariant": self.invariant,
            "required_entries": list(self.required_entries),
        }


@dataclass(frozen=True)
class Cr3QuickTimeRewriteTransactionLedger:
    status: Cr3TransactionLedgerStatus
    requested_tags: tuple[str, ...]
    target_surfaces: tuple[CanonRawWriteSurface, ...]
    linked_plan_operation_codes: tuple[str, ...]
    entries: tuple[Cr3TransactionLedgerEntry, ...]
    output_emission_gates: tuple[Cr3OutputEmissionGate, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def blocked_gate_count(self) -> int:
        return sum(gate.blocks_mutation for gate in self.output_emission_gates)

    def entries_for_concern(
        self, concern: Cr3TransactionConcern
    ) -> tuple[Cr3TransactionLedgerEntry, ...]:
        return tuple(entry for entry in self.entries if entry.concern == concern)

    def to_json(self) -> JsonObject:
        return {
            "blocked_gate_count": self.blocked_gate_count,
            "can_mutate_bytes": self.can_mutate_bytes,
            "entries": [entry.to_json() for entry in self.entries],
            "entry_count": self.entry_count,
            "linked_plan_operation_codes": list(self.linked_plan_operation_codes),
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "requested_tags": list(self.requested_tags),
            "status": self.status,
            "target_surfaces": list(self.target_surfaces),
        }


def build_cr3_quicktime_rewrite_transaction_ledger(
    classification: CanonRawWriteRequestClassification | None = None,
) -> Cr3QuickTimeRewriteTransactionLedger:
    plan = build_cr3_canon_uuid_xmp_ctbo_mutation_plan(classification)
    linked_plan_operation_codes = tuple(operation.code for operation in plan.operations)
    evidence_ids = unique_sources(
        (
            *plan.evidence_ids,
            QUICKTIME_UUID_SELECTOR_SOURCE,
            QUICKTIME_CANON_UUID_SELECTOR_SOURCE,
            CR3_CMT_TIFF_PAYLOAD_SOURCE,
            CR3_ATOM_SIZE_UPDATE_SOURCE,
            CR3_MDAT_BOUNDARY_SOURCE,
            CR3_FINAL_EMIT_SOURCE,
        )
    )
    return Cr3QuickTimeRewriteTransactionLedger(
        status="plan_only_deferred",
        requested_tags=plan.requested_tags,
        target_surfaces=plan.target_surfaces,
        linked_plan_operation_codes=linked_plan_operation_codes,
        entries=CR3_TRANSACTION_ENTRIES,
        output_emission_gates=CR3_OUTPUT_EMISSION_GATES,
        evidence_ids=evidence_ids,
    )


CR3_TRANSACTION_ENTRIES: tuple[Cr3TransactionLedgerEntry, ...] = (
    Cr3TransactionLedgerEntry(
        1,
        "require_cr3_ftyp_and_quicktime_context",
        "output_emission_gate",
        "input_gate",
        "Require a CR3 QuickTime ftyp route before UUID and CTBO rewrite planning.",
        (),
        ("ftyp_atom", "quicktime_file_type", "output_sink"),
        ("validated_cr3_quicktime_context",),
        ("quicktime_cr3_brand_required",),
        (CR3_QUICKTIME_MAP_SOURCE,),
    ),
    Cr3TransactionLedgerEntry(
        2,
        "walk_quicktime_atoms_and_collect_offsets",
        "quicktime_atom_traversal",
        "atom_traversal",
        (
            "Traverse QuickTime atoms and register offset-sensitive stco/co64/iloc/"
            "CTBO/uuid locations while rejecting unsupported fragmented or external media."
        ),
        ("require_cr3_ftyp_and_quicktime_context",),
        ("validated_cr3_quicktime_context", "source_atom_graph"),
        ("chunk_offset_records", "ctbo_atom_records", "uuid_atom_records"),
        ("offset_sensitive_atoms_must_be_supported",),
        (CR3_OFFSET_COLLECTION_SOURCE,),
    ),
    Cr3TransactionLedgerEntry(
        3,
        "route_cr3_groups_through_write_map",
        "quicktime_atom_traversal",
        "atom_traversal",
        "Route XMP to MOV, UUID-Canon to Movie, and CMT TIFF groups to UUID-Canon.",
        ("walk_quicktime_atoms_and_collect_offsets",),
        ("chunk_offset_records", "requested_tag_groups"),
        ("cr3_write_directory_routes",),
        (),
        (CR3_QUICKTIME_MAP_SOURCE,),
    ),
    Cr3TransactionLedgerEntry(
        4,
        "select_top_level_xmp_uuid_atom",
        "canon_uuid_selection",
        "atom_traversal",
        "Select the top-level XMP uuid by its oracle XMP UUID prefix and payload start.",
        ("route_cr3_groups_through_write_map",),
        ("cr3_write_directory_routes", "uuid_atom_records"),
        ("selected_xmp_uuid_atom",),
        ("xmp_uuid_prefix_and_padding_required",),
        (QUICKTIME_XMP_UUID_SOURCE, QUICKTIME_UUID_SELECTOR_SOURCE),
    ),
    Cr3TransactionLedgerEntry(
        5,
        "select_canon_uuid_cmt_tiff_atoms",
        "canon_uuid_selection",
        "atom_traversal",
        (
            "Select UUID-Canon CMT1/CMT2/CMT3/CMT4 TIFF payloads for IFD0, ExifIFD, "
            "MakerNoteCanon, and GPS writes."
        ),
        ("route_cr3_groups_through_write_map",),
        ("cr3_write_directory_routes", "uuid_atom_records"),
        ("selected_canon_cmt_tiff_atoms",),
        ("canon_uuid_cmt_padding_required",),
        (QUICKTIME_CANON_UUID_SELECTOR_SOURCE, CR3_CMT_TIFF_PAYLOAD_SOURCE),
    ),
    Cr3TransactionLedgerEntry(
        6,
        "replace_xmp_uuid_payload_preserving_padding",
        "xmp_payload_replacement",
        "payload_rewrite",
        "Replace the XMP uuid payload for Subject and XMP-exif values while preserving padding.",
        ("select_top_level_xmp_uuid_atom",),
        ("selected_xmp_uuid_atom", "xmp_packet_payloads"),
        ("rewritten_xmp_uuid_payload",),
        ("xmp_uuid_prefix_and_padding_required",),
        (
            QUICKTIME_XMP_UUID_SOURCE,
            XMP_DC_SUBJECT_SOURCE,
            XMP_EXIF_EXPOSURE_COMPENSATION_SOURCE,
        ),
    ),
    Cr3TransactionLedgerEntry(
        7,
        "rewrite_canon_cmt_tiff_payloads_preserving_padding",
        "canon_uuid_selection",
        "payload_rewrite",
        "Rewrite Canon CMT TIFF payloads through TIFF writers without dropping padding.",
        ("select_canon_uuid_cmt_tiff_atoms",),
        ("selected_canon_cmt_tiff_atoms", "exif_scalar_payloads", "canon_makernote_payloads"),
        ("rewritten_canon_cmt_tiff_payloads",),
        ("canon_uuid_cmt_padding_required",),
        (
            CR3_CANON_UUID_SOURCE,
            CR3_CMT_TIFF_PAYLOAD_SOURCE,
            EXIF_EXPOSURE_COMPENSATION_SOURCE,
        ),
    ),
    Cr3TransactionLedgerEntry(
        8,
        "stage_write_last_canon_uuid2_atoms",
        "output_emission_gate",
        "payload_rewrite",
        "Stage UUID-Canon2 updates so they are emitted after mdat.",
        ("route_cr3_groups_through_write_map",),
        ("cr3_write_directory_routes", "canon_vrd_payloads"),
        ("write_last_canon_uuid2_atoms",),
        ("canon2_write_last_after_mdat",),
        (CR3_QUICKTIME_CANON2_SOURCE, CR3_WRITE_LAST_SOURCE),
    ),
    Cr3TransactionLedgerEntry(
        9,
        "update_modified_atom_sizes_and_uuid_offsets",
        "atom_size_update",
        "atom_size_rewrite",
        (
            "Recalculate modified atom sizes, update modified uuid ChunkOffset sizes, "
            "and register new uuid offsets."
        ),
        (
            "replace_xmp_uuid_payload_preserving_padding",
            "rewrite_canon_cmt_tiff_payloads_preserving_padding",
        ),
        ("rewritten_xmp_uuid_payload", "rewritten_canon_cmt_tiff_payloads"),
        ("modified_atom_size_records", "new_uuid_offset_records"),
        ("modified_uuid_offsets_registered", "atom_size_growth_supported"),
        (CR3_ATOM_SIZE_UPDATE_SOURCE, CR3_UUID_WRITE_SOURCE),
    ),
    Cr3TransactionLedgerEntry(
        10,
        "plan_mdat_edits_and_header_growth",
        "mdat_edit_planning",
        "mdat_edit",
        "Plan ItemInfo-derived media data edits and validate mdat header growth limits.",
        ("walk_quicktime_atoms_and_collect_offsets",),
        ("source_mdat_chunks", "item_info_mdat_edits"),
        ("mdat_edit_list", "validated_mdat_header_growth"),
        (
            "mdat_required_for_ctbo_fixup",
            "iteminfo_mdat_edits_must_not_cross_boundary",
            "atom_size_growth_supported",
        ),
        (CR3_MDAT_EDIT_SOURCE, CR3_MDAT_BOUNDARY_SOURCE),
    ),
    Cr3TransactionLedgerEntry(
        11,
        "assign_new_mdat_positions",
        "mdat_edit_planning",
        "mdat_edit",
        "Assign each copied or edited mdat chunk its final output position.",
        ("plan_mdat_edits_and_header_growth",),
        ("mdat_edit_list", "rebuilt_metadata_length"),
        ("new_mdat_positions",),
        ("mdat_required_for_ctbo_fixup",),
        (CR3_MDAT_EDIT_SOURCE,),
    ),
    Cr3TransactionLedgerEntry(
        12,
        "patch_ctbo_item_offsets_and_sizes",
        "ctbo_offset_fixup",
        "offset_fixup",
        (
            "Patch CTBO item offsets and sizes for XMP, PreviewImage, first mdat, "
            "and known Canon UUID IDs."
        ),
        ("update_modified_atom_sizes_and_uuid_offsets", "assign_new_mdat_positions"),
        ("ctbo_atom_records", "new_uuid_offset_records", "new_mdat_positions"),
        ("patched_ctbo_table",),
        (
            "ctbo_entries_resolve_known_item_ids",
            "modified_uuid_offsets_registered",
            "mdat_required_for_ctbo_fixup",
        ),
        (CR3_CTBO_ID_SOURCE, CR3_CTBO_FIXUP_SOURCE),
    ),
    Cr3TransactionLedgerEntry(
        13,
        "emit_rebuilt_atoms_mdat_and_write_last",
        "output_emission_gate",
        "transaction_emit",
        "Emit rebuilt metadata atoms, copied or edited mdat chunks, and final WriteLast atoms.",
        (
            "patch_ctbo_item_offsets_and_sizes",
            "stage_write_last_canon_uuid2_atoms",
        ),
        ("patched_ctbo_table", "new_mdat_positions", "write_last_canon_uuid2_atoms"),
        ("deferred_cr3_emit_transaction",),
        (
            "no_byte_mutation_from_ledger",
            "canon2_write_last_after_mdat",
            "ctbo_entries_resolve_known_item_ids",
        ),
        (CR3_FINAL_EMIT_SOURCE, CR3_WRITE_LAST_SOURCE),
    ),
)

CR3_OUTPUT_EMISSION_GATES: tuple[Cr3OutputEmissionGate, ...] = (
    Cr3OutputEmissionGate(
        "no_byte_mutation_from_ledger",
        ("emit_rebuilt_atoms_mdat_and_write_last",),
        "The ledger may describe a CR3 emit transaction but must not write CR3 bytes.",
        (
            "Keep the request in plan-only deferred state until a byte-level "
            "QuickTime rewrite engine exists."
        ),
        (CR3_FINAL_EMIT_SOURCE,),
    ),
    Cr3OutputEmissionGate(
        "quicktime_cr3_brand_required",
        ("require_cr3_ftyp_and_quicktime_context",),
        "The QuickTime ftyp major or compatible brand must route through CR3 rules.",
        "Abort before UUID selection if the file is not a CR3 QuickTime container.",
        (CR3_QUICKTIME_MAP_SOURCE,),
    ),
    Cr3OutputEmissionGate(
        "offset_sensitive_atoms_must_be_supported",
        ("walk_quicktime_atoms_and_collect_offsets",),
        (
            "Offset-bearing atoms must be collectable and fragmented, sidx, saio, "
            "or mixed internal/external media layouts must be rejected."
        ),
        "Abort before any atom rewrite because final offsets could not be repaired safely.",
        (CR3_OFFSET_COLLECTION_SOURCE,),
    ),
    Cr3OutputEmissionGate(
        "xmp_uuid_prefix_and_padding_required",
        ("select_top_level_xmp_uuid_atom", "replace_xmp_uuid_payload_preserving_padding"),
        "The XMP uuid must match oracle's UUID prefix and preserve existing padding.",
        "Do not synthesize or replace an ambiguous UUID atom.",
        (QUICKTIME_XMP_UUID_SOURCE, QUICKTIME_UUID_SELECTOR_SOURCE),
    ),
    Cr3OutputEmissionGate(
        "canon_uuid_cmt_padding_required",
        (
            "select_canon_uuid_cmt_tiff_atoms",
            "rewrite_canon_cmt_tiff_payloads_preserving_padding",
        ),
        "Canon CMT TIFF payloads must keep PreservePadding and MakerNote identity intact.",
        "Defer Canon UUID TIFF mutation until CMT padding and MakerNote gates are enforced.",
        (CR3_CMT_TIFF_PAYLOAD_SOURCE,),
    ),
    Cr3OutputEmissionGate(
        "modified_uuid_offsets_registered",
        ("update_modified_atom_sizes_and_uuid_offsets", "patch_ctbo_item_offsets_and_sizes"),
        "Every modified or newly created uuid needed by CTBO must have its output offset recorded.",
        "Abort CTBO patching rather than leave Canon item entries pointing at stale offsets.",
        (CR3_UUID_WRITE_SOURCE, CR3_ATOM_SIZE_UPDATE_SOURCE),
    ),
    Cr3OutputEmissionGate(
        "mdat_required_for_ctbo_fixup",
        ("assign_new_mdat_positions", "patch_ctbo_item_offsets_and_sizes"),
        "CR3 CTBO patching requires at least one mdat chunk with a final output position.",
        "Abort when media data is missing while CTBO entries reference item ID 3.",
        (CR3_MDAT_EDIT_SOURCE, CR3_CTBO_FIXUP_SOURCE),
    ),
    Cr3OutputEmissionGate(
        "iteminfo_mdat_edits_must_not_cross_boundary",
        ("plan_mdat_edits_and_header_growth",),
        "ItemInfo-derived media edits must be fully contained by a single mdat chunk.",
        "Abort before mdat rewrite instead of emitting a media edit that crosses chunk bounds.",
        (CR3_MDAT_BOUNDARY_SOURCE,),
    ),
    Cr3OutputEmissionGate(
        "ctbo_entries_resolve_known_item_ids",
        ("patch_ctbo_item_offsets_and_sizes",),
        "Non-empty CTBO entries must resolve to XMP, PreviewImage, mdat, or known Canon UUID IDs.",
        "Abort instead of guessing unknown Canon-private CTBO item semantics.",
        (CR3_CTBO_ID_SOURCE, CR3_CTBO_FIXUP_SOURCE),
    ),
    Cr3OutputEmissionGate(
        "canon2_write_last_after_mdat",
        ("stage_write_last_canon_uuid2_atoms", "emit_rebuilt_atoms_mdat_and_write_last"),
        "UUID-Canon2 must be emitted after media data.",
        "Abort rather than produce a CR3 that Canon DPP may rewrite by dropping image data.",
        (CR3_QUICKTIME_CANON2_SOURCE, CR3_WRITE_LAST_SOURCE, CR3_FINAL_EMIT_SOURCE),
    ),
    Cr3OutputEmissionGate(
        "atom_size_growth_supported",
        ("update_modified_atom_sizes_and_uuid_offsets", "plan_mdat_edits_and_header_growth"),
        "Modified atom and mdat sizes must remain representable by their existing headers.",
        "Abort before output when 32-bit atom or mdat sizes cannot represent growth safely.",
        (CR3_ATOM_SIZE_UPDATE_SOURCE, CR3_MDAT_EDIT_SOURCE),
    ),
)
