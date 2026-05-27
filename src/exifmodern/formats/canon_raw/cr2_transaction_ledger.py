"""Source-backed CR2 TIFF rewrite transaction ledger.

This ledger decomposes oracle's CR2 writer into typed transaction entries.
It is intentionally non-mutating: it records the ordering, offset, trailer, and
emission gates that a future TIFF rewrite engine must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.canon_raw.cr2_mutation_plan import (
    CANON_RAW_CR2_SUFFIX_TEST_SOURCE,
    WRITE_EXIF_IFD_ORDER_SOURCE,
    WRITE_EXIF_IMAGE_DATA_SOURCE,
    WRITE_EXIF_LAST_IFD_SOURCE,
    build_cr2_tiff_ifd_mutation_plan,
    unique_sources,
)
from exifmodern.formats.canon_raw.write_plan import (
    CANON_FOCAL_PLANE_X_SIZE_SOURCE,
    CANON_OWNER_NAME_SOURCE,
    CANON_RAW_CR2_NOTE_SOURCE,
    WRITE_CR2_SOURCE,
    CanonRawWriteRequestClassification,
    CanonRawWriteSurface,
)
from exifmodern.json_types import JsonObject

type EvidenceId = str

type Cr2TransactionLedgerStatus = Literal["plan_only_deferred"]
type Cr2TransactionConcern = Literal[
    "tiff_ifd_ordering",
    "makernote_subifd_boundary",
    "image_data_offset_tracking",
    "file_suffix_preservation",
    "trailer_preservation",
    "output_emission_gate",
]
type Cr2TransactionPhase = Literal[
    "input_gate",
    "rewrite_layout",
    "nested_directory_rewrite",
    "offset_fixup",
    "trailer_fixup",
    "transaction_emit",
]
type Cr2TransactionEntryCode = Literal[
    "require_cr2_signature_and_raf",
    "establish_16_byte_tiff_rewrite_base",
    "schedule_writeexif_ifd_order",
    "rewrite_subifd_boundaries",
    "rewrite_makernote_boundaries",
    "track_offset_pairs_and_image_data",
    "apply_top_level_offset_fixups",
    "capture_last_ifd_for_header",
    "preserve_non_tiff_suffix_bytes",
    "preserve_trailer_fixup_markers",
    "emit_header_tiff_data_then_image_data",
]
type Cr2EmissionGateCode = Literal[
    "no_byte_mutation_from_ledger",
    "cr2_signature_and_random_access_required",
    "ifd0_pointer_rebased_to_16",
    "last_ifd_required_before_emit",
    "image_data_copy_requires_tracked_offsets",
    "non_tiff_suffix_requires_copy_contract",
    "trailer_offsets_require_fixup_markers",
]

WRITE_EXIF_SUBIFD_BOUNDARY_SOURCE = "canon_raw.write_exif_subifd_boundary"
WRITE_EXIF_MAKERNOTE_BOUNDARY_SOURCE = "canon_raw.write_exif_makernote_boundary"
WRITE_EXIF_OFFSET_PAIR_SOURCE = "canon_raw.write_exif_offset_pair"
WRITE_EXIF_IMAGE_DATA_VALIDATE_SOURCE = "canon_raw.write_exif_image_data_validate"
WRITE_EXIF_SUBIFD_IMAGE_DATA_FIXUP_SOURCE = "canon_raw.write_exif_subifd_image_data_fixup"
WRITE_EXIF_TRAILER_FIXUP_SOURCE = "canon_raw.write_exif_trailer_fixup"
WRITE_EXIF_TOP_LEVEL_FIXUP_SOURCE = "canon_raw.write_exif_top_level_fixup"


@dataclass(frozen=True)
class Cr2TransactionLedgerEntry:
    order: int
    code: Cr2TransactionEntryCode
    concern: Cr2TransactionConcern
    phase: Cr2TransactionPhase
    description: str
    depends_on: tuple[Cr2TransactionEntryCode, ...]
    consumes: tuple[str, ...]
    records: tuple[str, ...]
    gates: tuple[Cr2EmissionGateCode, ...]
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
class Cr2OutputEmissionGate:
    code: Cr2EmissionGateCode
    required_entries: tuple[Cr2TransactionEntryCode, ...]
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
class Cr2TiffRewriteTransactionLedger:
    status: Cr2TransactionLedgerStatus
    requested_tags: tuple[str, ...]
    target_surfaces: tuple[CanonRawWriteSurface, ...]
    linked_plan_operation_codes: tuple[str, ...]
    entries: tuple[Cr2TransactionLedgerEntry, ...]
    output_emission_gates: tuple[Cr2OutputEmissionGate, ...]
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
        self, concern: Cr2TransactionConcern
    ) -> tuple[Cr2TransactionLedgerEntry, ...]:
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


def build_cr2_tiff_rewrite_transaction_ledger(
    classification: CanonRawWriteRequestClassification | None = None,
) -> Cr2TiffRewriteTransactionLedger:
    plan = build_cr2_tiff_ifd_mutation_plan(classification)
    linked_plan_operation_codes = tuple(operation.code for operation in plan.operations)
    evidence_ids = unique_sources(
        (
            CANON_RAW_CR2_NOTE_SOURCE,
            *plan.evidence_ids,
            WRITE_EXIF_SUBIFD_BOUNDARY_SOURCE,
            WRITE_EXIF_MAKERNOTE_BOUNDARY_SOURCE,
            WRITE_EXIF_OFFSET_PAIR_SOURCE,
            WRITE_EXIF_IMAGE_DATA_VALIDATE_SOURCE,
            WRITE_EXIF_SUBIFD_IMAGE_DATA_FIXUP_SOURCE,
            CANON_RAW_CR2_SUFFIX_TEST_SOURCE,
            WRITE_EXIF_TRAILER_FIXUP_SOURCE,
            WRITE_EXIF_TOP_LEVEL_FIXUP_SOURCE,
        )
    )
    return Cr2TiffRewriteTransactionLedger(
        status="plan_only_deferred",
        requested_tags=plan.requested_tags,
        target_surfaces=plan.target_surfaces,
        linked_plan_operation_codes=linked_plan_operation_codes,
        entries=CR2_TRANSACTION_ENTRIES,
        output_emission_gates=CR2_OUTPUT_EMISSION_GATES,
        evidence_ids=evidence_ids,
    )


CR2_TRANSACTION_ENTRIES: tuple[Cr2TransactionLedgerEntry, ...] = (
    Cr2TransactionLedgerEntry(
        1,
        "require_cr2_signature_and_raf",
        "output_emission_gate",
        "input_gate",
        "Require a CR2 signature, output sink, and RAF-backed random access before planning emit.",
        (),
        ("first_16_header_bytes", "raf_random_access_input", "output_sink"),
        ("validated_cr2_container",),
        ("cr2_signature_and_random_access_required",),
        (WRITE_CR2_SOURCE, CANON_RAW_CR2_NOTE_SOURCE),
    ),
    Cr2TransactionLedgerEntry(
        2,
        "establish_16_byte_tiff_rewrite_base",
        "tiff_ifd_ordering",
        "rewrite_layout",
        "Start the rebuilt TIFF data at byte 16, the CR2 header boundary.",
        ("require_cr2_signature_and_raf",),
        ("validated_cr2_container",),
        ("new_data_pos_16",),
        ("ifd0_pointer_rebased_to_16",),
        (WRITE_CR2_SOURCE,),
    ),
    Cr2TransactionLedgerEntry(
        3,
        "schedule_writeexif_ifd_order",
        "tiff_ifd_ordering",
        "rewrite_layout",
        (
            "Schedule IFD0, SubIFD, global parameter, EXIF, GPS, Interop, linked "
            "IFD, thumbnail, and image data emission in WriteExif order."
        ),
        ("establish_16_byte_tiff_rewrite_base",),
        ("new_data_pos_16", "source_tiff_ifds"),
        ("writeexif_ifd_order",),
        (),
        (WRITE_EXIF_IFD_ORDER_SOURCE,),
    ),
    Cr2TransactionLedgerEntry(
        4,
        "rewrite_subifd_boundaries",
        "makernote_subifd_boundary",
        "nested_directory_rewrite",
        (
            "Recurse into SubIFDs with isolated dirInfo and propagate first-level "
            "SubIFD image-data records upward."
        ),
        ("schedule_writeexif_ifd_order",),
        ("writeexif_ifd_order", "subifd_directory_records"),
        ("subifd_rewrite_boundaries", "subifd_image_data_records"),
        ("image_data_copy_requires_tracked_offsets",),
        (WRITE_EXIF_SUBIFD_BOUNDARY_SOURCE, WRITE_EXIF_IMAGE_DATA_SOURCE),
    ),
    Cr2TransactionLedgerEntry(
        5,
        "rewrite_makernote_boundaries",
        "makernote_subifd_boundary",
        "nested_directory_rewrite",
        (
            "Rewrite Canon MakerNotes through MakerNote-specific IFD or binary-data "
            "boundaries with model-sensitive Canon conversions."
        ),
        ("schedule_writeexif_ifd_order",),
        ("canon_makernote_tag_blocks", "canon_model_context"),
        ("makernote_rewrite_boundaries", "makernote_fixups"),
        (),
        (
            WRITE_EXIF_MAKERNOTE_BOUNDARY_SOURCE,
            CANON_OWNER_NAME_SOURCE,
            CANON_FOCAL_PLANE_X_SIZE_SOURCE,
        ),
    ),
    Cr2TransactionLedgerEntry(
        6,
        "track_offset_pairs_and_image_data",
        "image_data_offset_tracking",
        "offset_fixup",
        (
            "Record offset-pair value pointers and image-data records so "
            "strip/tile/raw payloads can be copied after directory layout is final."
        ),
        ("rewrite_subifd_boundaries", "rewrite_makernote_boundaries"),
        ("offset_pair_tags", "subifd_image_data_records", "source_image_data_ranges"),
        ("offset_pair_pointer_table", "validated_image_data_copy_plan"),
        ("image_data_copy_requires_tracked_offsets",),
        (
            WRITE_EXIF_OFFSET_PAIR_SOURCE,
            WRITE_EXIF_IMAGE_DATA_VALIDATE_SOURCE,
            WRITE_EXIF_SUBIFD_IMAGE_DATA_FIXUP_SOURCE,
        ),
    ),
    Cr2TransactionLedgerEntry(
        7,
        "apply_top_level_offset_fixups",
        "image_data_offset_tracking",
        "offset_fixup",
        "Apply the byte-16 top-level shift and any contained SubIFD image-data offset shifts.",
        ("track_offset_pairs_and_image_data", "establish_16_byte_tiff_rewrite_base"),
        ("offset_pair_pointer_table", "new_data_pos_16"),
        ("rebased_tiff_offsets",),
        ("ifd0_pointer_rebased_to_16",),
        (WRITE_EXIF_TOP_LEVEL_FIXUP_SOURCE, WRITE_EXIF_SUBIFD_IMAGE_DATA_FIXUP_SOURCE),
    ),
    Cr2TransactionLedgerEntry(
        8,
        "capture_last_ifd_for_header",
        "output_emission_gate",
        "offset_fixup",
        "Capture WriteExif's final NextIFD marker for the last four bytes of the CR2 header.",
        ("apply_top_level_offset_fixups",),
        ("rebased_tiff_offsets",),
        ("last_ifd_offset",),
        ("last_ifd_required_before_emit",),
        (WRITE_EXIF_LAST_IFD_SOURCE, WRITE_EXIF_TOP_LEVEL_FIXUP_SOURCE),
    ),
    Cr2TransactionLedgerEntry(
        9,
        "preserve_non_tiff_suffix_bytes",
        "file_suffix_preservation",
        "trailer_fixup",
        (
            "Carry forward non-TIFF CR2 suffix bytes after the copied image data; "
            "CanonRaw.t verifies the dummy preview and suffix string survive the write."
        ),
        ("track_offset_pairs_and_image_data",),
        ("validated_image_data_copy_plan", "source_file_suffix_range"),
        ("preserved_non_tiff_suffix_bytes",),
        ("non_tiff_suffix_requires_copy_contract",),
        (CANON_RAW_CR2_SUFFIX_TEST_SOURCE,),
    ),
    Cr2TransactionLedgerEntry(
        10,
        "preserve_trailer_fixup_markers",
        "trailer_preservation",
        "trailer_fixup",
        (
            "Preserve trailer-related offset markers such as CanonVRD and Leica "
            "trailer fixups across the rebuilt TIFF layout."
        ),
        ("apply_top_level_offset_fixups",),
        ("trailer_offset_pairs", "rebased_tiff_offsets"),
        ("trailer_fixup_markers",),
        ("trailer_offsets_require_fixup_markers",),
        (WRITE_EXIF_TRAILER_FIXUP_SOURCE, WRITE_EXIF_TOP_LEVEL_FIXUP_SOURCE),
    ),
    Cr2TransactionLedgerEntry(
        11,
        "emit_header_tiff_data_then_image_data",
        "output_emission_gate",
        "transaction_emit",
        (
            "Emit only after the CR2 header can be rebuilt with IFD0=16 and "
            "LastIFD, then copy tracked image data after directory output."
        ),
        (
            "capture_last_ifd_for_header",
            "track_offset_pairs_and_image_data",
            "preserve_non_tiff_suffix_bytes",
            "preserve_trailer_fixup_markers",
        ),
        (
            "last_ifd_offset",
            "rebased_tiff_offsets",
            "validated_image_data_copy_plan",
            "preserved_non_tiff_suffix_bytes",
        ),
        ("deferred_cr2_emit_transaction",),
        (
            "no_byte_mutation_from_ledger",
            "last_ifd_required_before_emit",
            "image_data_copy_requires_tracked_offsets",
            "non_tiff_suffix_requires_copy_contract",
        ),
        (WRITE_CR2_SOURCE, WRITE_EXIF_TOP_LEVEL_FIXUP_SOURCE, CANON_RAW_CR2_SUFFIX_TEST_SOURCE),
    ),
)

CR2_OUTPUT_EMISSION_GATES: tuple[Cr2OutputEmissionGate, ...] = (
    Cr2OutputEmissionGate(
        "no_byte_mutation_from_ledger",
        ("emit_header_tiff_data_then_image_data",),
        "The ledger may describe an emit transaction but must not write CR2 bytes.",
        (
            "Keep the request in plan-only deferred state until a byte-level TIFF "
            "rewrite engine exists."
        ),
        (WRITE_CR2_SOURCE,),
    ),
    Cr2OutputEmissionGate(
        "cr2_signature_and_random_access_required",
        ("require_cr2_signature_and_raf",),
        "Bytes 8-11 must be CR 02 00 and the source must support RAF reads.",
        "Abort before directory rewrite planning if signature or random access is missing.",
        (WRITE_CR2_SOURCE,),
    ),
    Cr2OutputEmissionGate(
        "ifd0_pointer_rebased_to_16",
        ("establish_16_byte_tiff_rewrite_base", "apply_top_level_offset_fixups"),
        (
            "The rebuilt header must point IFD0 at byte 16 and all top-level offsets "
            "must be shifted by that base."
        ),
        "Do not emit output with stale PhotoMechanic-shifted or original IFD0 pointers.",
        (WRITE_CR2_SOURCE, WRITE_EXIF_TOP_LEVEL_FIXUP_SOURCE),
    ),
    Cr2OutputEmissionGate(
        "last_ifd_required_before_emit",
        ("capture_last_ifd_for_header",),
        "LastIFD must be produced by WriteExif when NewDataPos is 16.",
        "Abort because oracle treats missing LastIFD as deletion of the CR2 image IFD.",
        (WRITE_CR2_SOURCE, WRITE_EXIF_LAST_IFD_SOURCE),
    ),
    Cr2OutputEmissionGate(
        "image_data_copy_requires_tracked_offsets",
        ("track_offset_pairs_and_image_data", "emit_header_tiff_data_then_image_data"),
        "Image data copy must be based on validated offset-pair and SubIFD image-data records.",
        (
            "Do not copy raw image ranges when strip, tile, or SubIFD image-data "
            "offsets are untracked."
        ),
        (
            WRITE_CR2_SOURCE,
            WRITE_EXIF_IMAGE_DATA_VALIDATE_SOURCE,
            WRITE_EXIF_SUBIFD_IMAGE_DATA_FIXUP_SOURCE,
        ),
    ),
    Cr2OutputEmissionGate(
        "non_tiff_suffix_requires_copy_contract",
        ("preserve_non_tiff_suffix_bytes", "emit_header_tiff_data_then_image_data"),
        "CR2 non-TIFF suffix bytes must be preserved after image-data copy.",
        (
            "Keep CR2 writes deferred until the copy engine can prove CanonRaw.t "
            "test 6 suffix preservation."
        ),
        (CANON_RAW_CR2_SUFFIX_TEST_SOURCE,),
    ),
    Cr2OutputEmissionGate(
        "trailer_offsets_require_fixup_markers",
        ("preserve_trailer_fixup_markers",),
        (
            "Trailer-bearing offsets such as CanonVRD and Leica trailer pointers "
            "must retain fixup markers across TIFF layout shifts."
        ),
        (
            "Preserve existing trailer state and defer trailer-affecting writes "
            "until marker fixups are implemented."
        ),
        (WRITE_EXIF_TRAILER_FIXUP_SOURCE, WRITE_EXIF_TOP_LEVEL_FIXUP_SOURCE),
    ),
)
