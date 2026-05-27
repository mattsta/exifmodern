"""Typed CR3 Canon UUID/XMP/CTBO mutation-engine plan.

CR3 metadata writes are QuickTime atom rewrites plus Canon UUID TIFF payload
rewrites and CTBO/mdat fixups.  This module decomposes that engine and exposes
safe inspectors, but it does not mutate CR3 bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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

type Cr3BrandStatus = Literal["recognized_cr3", "non_cr3_ftyp", "missing_ftyp", "truncated"]
type Cr3AtomScanStatus = Literal[
    "ready",
    "truncated_atom_header",
    "invalid_atom_size",
]
type Cr3CtboInspectionStatus = Literal["ready", "invalid_atom", "truncated_atom"]
type Cr3UuidAtomBoundaryStatus = Literal["ready", "not_uuid_atom", "uuid_payload_truncated"]
type Cr3UuidAtomKind = Literal[
    "xmp",
    "canon",
    "canon2",
    "preview_image",
    "burst_roll",
    "unknown",
]
type Cr3CtboPatchPlanStatus = Literal[
    "ready",
    "invalid_ctbo",
    "missing_mdat",
    "unknown_ctbo_id",
]
type Cr3CtboPatchApplicationStatus = Literal[
    "ready",
    "patch_plan_not_ready",
    "ctbo_offset_out_of_range",
    "ctbo_atom_mismatch",
    "ctbo_atom_truncated",
]
type Cr3MutationPlanStatus = Literal["plan_only_deferred"]
type Cr3MutationPrerequisiteCode = Literal[
    "quicktime_cr3_brand_detected",
    "quicktime_atom_rewrite_engine_available",
    "top_level_xmp_uuid_writer_available",
    "canon_uuid_cmt_tiff_writer_available",
    "ctbo_uuid_offset_index_available",
    "mdat_edit_engine_available",
    "iteminfo_mdat_boundary_checks_available",
    "write_last_ordering_available",
]
type Cr3MutationOperationCode = Literal[
    "validate_cr3_ftyp_brand",
    "initialize_cr3_quicktime_write_map",
    "collect_ctbo_uuid_and_media_offsets",
    "rewrite_top_level_xmp_uuid",
    "rewrite_canon_uuid_cmt_tiff_payloads",
    "stage_write_last_canon_uuid2_atoms",
    "edit_or_copy_mdat_chunks",
    "recalculate_mdat_positions",
    "patch_ctbo_item_offsets_and_sizes",
    "write_rebuilt_atoms_and_media_data",
]
type Cr3MutationSafetyGateCode = Literal[
    "reject_non_cr3_brand",
    "reject_unsupported_fragmented_or_external_media",
    "ctbo_atom_length_and_entry_count_valid",
    "mdat_available_for_ctbo_fixup",
    "uuid_offsets_registered_for_ctbo_ids",
    "unknown_ctbo_ids_rejected",
    "canon_cmt_tiff_payloads_preserve_padding",
    "canon2_write_last_after_mdat",
    "iteminfo_edits_stay_within_single_mdat",
    "mdat_size_growth_within_32bit_header_limit",
]
type Cr3MutationArtifact = Literal[
    "validated_cr3_ftyp",
    "cr3_directory_map",
    "chunk_offset_index",
    "top_level_xmp_uuid",
    "canon_uuid_cmt_payloads",
    "write_last_uuid2_payloads",
    "mdat_edit_list",
    "new_mdat_positions",
    "patched_ctbo_table",
    "rebuilt_quicktime_stream",
]

QUICKTIME_XMP_UUID_SOURCE = "canon_raw.quicktime_xmp_uuid"
CR3_CTBO_ID_SOURCE = "canon_raw.cr3_ctbo_id"
QUICKTIME_CANON_UUID_SOURCE = "canon_raw.quicktime_canon_uuid"
QUICKTIME_CANON2_UUID_SOURCE = "canon_raw.quicktime_canon2_uuid"
QUICKTIME_PREVIEW_UUID_SOURCE = "canon_raw.quicktime_preview_uuid"
CR3_OFFSET_COLLECTION_SOURCE = "canon_raw.cr3_offset_collection"
CR3_UUID_WRITE_SOURCE = "canon_raw.cr3_uuid_write"
CR3_WRITE_LAST_SOURCE = "canon_raw.cr3_write_last"
CR3_MDAT_EDIT_SOURCE = "canon_raw.cr3_mdat_edit"
CR3_MDAT_BOUNDARY_SOURCE = "canon_raw.cr3_mdat_boundary"


@dataclass(frozen=True)
class Cr3BrandInspection:
    status: Cr3BrandStatus
    ftyp_size: int | None
    major_brand: str | None
    compatible_brands: tuple[str, ...]

    @property
    def recognized(self) -> bool:
        return self.status == "recognized_cr3"


@dataclass(frozen=True)
class Cr3AtomRecord:
    offset: int
    atom_type: str
    size: int
    header_size: int
    payload_offset: int
    payload_size: int


@dataclass(frozen=True)
class Cr3AtomScan:
    status: Cr3AtomScanStatus
    records: tuple[Cr3AtomRecord, ...]
    blocked_offset: int | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class Cr3AtomTreeRecord:
    path: tuple[str, ...]
    atom: Cr3AtomRecord

    @property
    def full_path(self) -> str:
        return "/".join(self.path)


@dataclass(frozen=True)
class Cr3AtomTreeScan:
    status: Cr3AtomScanStatus
    records: tuple[Cr3AtomTreeRecord, ...]
    blocked_offset: int | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class Cr3CtboEntry:
    item_id: int
    item_offset: int
    item_size: int


@dataclass(frozen=True)
class Cr3CtboInspection:
    status: Cr3CtboInspectionStatus
    entry_count: int | None
    entries: tuple[Cr3CtboEntry, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class Cr3CtboOffsetRegistration:
    item_id: int
    item_offset: int
    item_size: int


@dataclass(frozen=True)
class Cr3CtboPatch:
    item_id: int
    old_offset: int
    old_size: int
    new_offset: int
    new_size: int
    source: str


@dataclass(frozen=True)
class Cr3CtboPatchPlan:
    status: Cr3CtboPatchPlanStatus
    patches: tuple[Cr3CtboPatch, ...]
    blocked_item_id: int | None
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_patch_table(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class Cr3CtboPatchApplication:
    status: Cr3CtboPatchApplicationStatus
    rebuilt_stream: bytes | None
    applied_patches: tuple[Cr3CtboPatch, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_emit_stream(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class Cr3UuidAtomBoundary:
    status: Cr3UuidAtomBoundaryStatus
    atom: Cr3AtomRecord | None
    uuid_identifier: bytes | None
    kind: Cr3UuidAtomKind | None
    ctbo_item_id: int | None
    payload_offset: int | None
    payload_size: int | None
    preserve_padding: bool
    write_last: bool
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_emit_payload(self) -> bool:
        return False


@dataclass(frozen=True)
class Cr3MutationPrerequisite:
    code: Cr3MutationPrerequisiteCode
    requirement: str
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class Cr3MutationOperation:
    order: int
    code: Cr3MutationOperationCode
    description: str
    requires: tuple[Cr3MutationPrerequisiteCode, ...]
    produces: tuple[Cr3MutationArtifact, ...]
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class Cr3MutationSafetyGate:
    code: Cr3MutationSafetyGateCode
    must_pass_before: Cr3MutationOperationCode
    invariant: str
    failure_response: str
    evidence_ids: tuple[EvidenceId, ...]


@dataclass(frozen=True)
class Cr3CanonUuidXmpCtboMutationPlan:
    status: Cr3MutationPlanStatus
    requested_tags: tuple[str, ...]
    target_surfaces: tuple[CanonRawWriteSurface, ...]
    prerequisites: tuple[Cr3MutationPrerequisite, ...]
    operations: tuple[Cr3MutationOperation, ...]
    safety_gates: tuple[Cr3MutationSafetyGate, ...]
    evidence_ids: tuple[EvidenceId, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    def to_json(self) -> JsonObject:
        return {
            "can_mutate_bytes": self.can_mutate_bytes,
            "operations": [
                {
                    "code": operation.code,
                    "description": operation.description,
                    "order": operation.order,
                    "produces": list(operation.produces),
                    "requires": list(operation.requires),
                }
                for operation in self.operations
            ],
            "prerequisites": [
                {
                    "code": prerequisite.code,
                    "requirement": prerequisite.requirement,
                }
                for prerequisite in self.prerequisites
            ],
            "requested_tags": list(self.requested_tags),
            "safety_gates": [
                {
                    "code": safety_gate.code,
                    "failure_response": safety_gate.failure_response,
                    "invariant": safety_gate.invariant,
                    "must_pass_before": safety_gate.must_pass_before,
                }
                for safety_gate in self.safety_gates
            ],
            "status": self.status,
            "target_surfaces": list(self.target_surfaces),
        }


def inspect_cr3_ftyp_brand(data: bytes) -> Cr3BrandInspection:
    if len(data) < 16:
        return Cr3BrandInspection("truncated", None, None, ())
    ftyp_size = int.from_bytes(data[:4], byteorder="big")
    if data[4:8] != b"ftyp":
        return Cr3BrandInspection("missing_ftyp", ftyp_size, None, ())
    if ftyp_size < 16 or ftyp_size > len(data):
        return Cr3BrandInspection("truncated", ftyp_size, None, ())
    major_brand = ascii_brand(data[8:12])
    compatible_brands = tuple(
        ascii_brand(data[index : index + 4]) for index in range(16, ftyp_size, 4)
    )
    status: Cr3BrandStatus = (
        "recognized_cr3" if major_brand == "crx " or "crx " in compatible_brands else "non_cr3_ftyp"
    )
    return Cr3BrandInspection(status, ftyp_size, major_brand, compatible_brands)


def scan_cr3_top_level_atoms(data: bytes) -> Cr3AtomScan:
    return scan_cr3_atoms_in_range(data, 0, len(data))


def scan_cr3_atoms_in_range(data: bytes, start_offset: int, end_offset: int) -> Cr3AtomScan:
    records: list[Cr3AtomRecord] = []
    offset = start_offset
    if start_offset < 0 or end_offset < start_offset or end_offset > len(data):
        return Cr3AtomScan(
            "invalid_atom_size",
            (),
            start_offset,
            (CR3_QUICKTIME_MAP_SOURCE,),
        )
    while offset < end_offset:
        remaining = end_offset - offset
        if remaining < 8:
            return Cr3AtomScan(
                "truncated_atom_header",
                tuple(records),
                offset,
                (CR3_QUICKTIME_MAP_SOURCE,),
            )
        size32 = int.from_bytes(data[offset : offset + 4], byteorder="big")
        atom_type = ascii_brand(data[offset + 4 : offset + 8])
        if size32 == 1:
            if remaining < 16:
                return Cr3AtomScan(
                    "truncated_atom_header",
                    tuple(records),
                    offset,
                    (CR3_QUICKTIME_MAP_SOURCE,),
                )
            size = int.from_bytes(data[offset + 8 : offset + 16], byteorder="big")
            header_size = 16
        elif size32 == 0:
            size = remaining
            header_size = 8
        else:
            size = size32
            header_size = 8
        if size < header_size or size > remaining:
            return Cr3AtomScan(
                "invalid_atom_size",
                tuple(records),
                offset,
                (CR3_QUICKTIME_MAP_SOURCE,),
            )
        records.append(
            Cr3AtomRecord(
                offset=offset,
                atom_type=atom_type,
                size=size,
                header_size=header_size,
                payload_offset=offset + header_size,
                payload_size=size - header_size,
            )
        )
        offset += size
    return Cr3AtomScan("ready", tuple(records), None, (CR3_QUICKTIME_MAP_SOURCE,))


def scan_cr3_atom_tree(data: bytes) -> Cr3AtomTreeScan:
    """Scan CR3 atoms needed by the bounded CR3 rewrite seams.

    WriteQuickTime records CR3 ``CTBO`` and ``uuid`` locations wherever they
    are encountered during atom traversal.  Canon CR3 files place those records
    inside ``moov`` or Canon ``uuid`` containers, so this bounded tree scan
    exposes absolute offsets for the reusable CTBO repair seam without
    attempting a general QuickTime rewrite.
    """

    top_level = scan_cr3_top_level_atoms(data)
    if not top_level.ready:
        return Cr3AtomTreeScan(
            top_level.status,
            tuple(Cr3AtomTreeRecord((record.atom_type,), record) for record in top_level.records),
            top_level.blocked_offset,
            top_level.evidence_ids,
        )

    tree_records: list[Cr3AtomTreeRecord] = []
    for record in top_level.records:
        tree_records.append(Cr3AtomTreeRecord((record.atom_type,), record))
        child_scan = scan_cr3_record_children_for_tree(
            data,
            tree_records,
            (record.atom_type,),
            record,
        )
        if child_scan is None:
            continue
        if not child_scan.ready:
            return Cr3AtomTreeScan(
                child_scan.status,
                tuple(tree_records),
                child_scan.blocked_offset,
                child_scan.evidence_ids,
            )
    return Cr3AtomTreeScan("ready", tuple(tree_records), None, (CR3_QUICKTIME_MAP_SOURCE,))


def scan_cr3_record_children_for_tree(
    data: bytes,
    tree_records: list[Cr3AtomTreeRecord],
    parent_path: tuple[str, ...],
    record: Cr3AtomRecord,
) -> Cr3AtomScan | None:
    if record.atom_type == "moov":
        return append_cr3_child_atom_tree_records(
            data,
            tree_records,
            parent_path,
            record.payload_offset,
            record.payload_offset + record.payload_size,
        )
    if record.atom_type != "uuid":
        return None
    boundary = inspect_cr3_uuid_atom_boundary(data, record)
    if boundary.status != "ready" or boundary.kind != "canon" or boundary.payload_offset is None:
        return None
    return append_cr3_child_atom_tree_records(
        data,
        tree_records,
        parent_path,
        boundary.payload_offset,
        record.offset + record.size,
    )


def append_cr3_child_atom_tree_records(
    data: bytes,
    tree_records: list[Cr3AtomTreeRecord],
    parent_path: tuple[str, ...],
    start_offset: int,
    end_offset: int,
) -> Cr3AtomScan:
    child_scan = scan_cr3_atoms_in_range(data, start_offset, end_offset)
    tree_records.extend(
        Cr3AtomTreeRecord((*parent_path, child.atom_type), child) for child in child_scan.records
    )
    if not child_scan.ready:
        return child_scan
    for child in child_scan.records:
        nested_scan = scan_cr3_record_children_for_tree(
            data,
            tree_records,
            (*parent_path, child.atom_type),
            child,
        )
        if nested_scan is not None and not nested_scan.ready:
            return nested_scan
    return child_scan


def inspect_cr3_uuid_atom_boundary(data: bytes, atom: Cr3AtomRecord) -> Cr3UuidAtomBoundary:
    if atom.atom_type != "uuid":
        return Cr3UuidAtomBoundary(
            "not_uuid_atom",
            atom,
            None,
            None,
            None,
            None,
            None,
            False,
            False,
            (CR3_QUICKTIME_MAP_SOURCE,),
        )
    if atom.payload_size < 16 or atom.payload_offset + 16 > len(data):
        return Cr3UuidAtomBoundary(
            "uuid_payload_truncated",
            atom,
            None,
            None,
            None,
            None,
            None,
            False,
            False,
            (QUICKTIME_XMP_UUID_SOURCE, QUICKTIME_CANON_UUID_SOURCE),
        )

    uuid_identifier = data[atom.payload_offset : atom.payload_offset + 16]
    kind, ctbo_item_id, preserve_padding, write_last, evidence_ids = classify_cr3_uuid_identifier(
        uuid_identifier
    )
    return Cr3UuidAtomBoundary(
        "ready",
        atom,
        uuid_identifier,
        kind,
        ctbo_item_id,
        atom.payload_offset + 16,
        atom.payload_size - 16,
        preserve_padding,
        write_last,
        evidence_ids,
    )


def inspect_cr3_uuid_atom_boundaries(data: bytes) -> tuple[Cr3UuidAtomBoundary, ...]:
    scan = scan_cr3_top_level_atoms(data)
    if not scan.ready:
        return ()
    return tuple(
        boundary
        for boundary in (
            inspect_cr3_uuid_atom_boundary(data, atom)
            for atom in scan.records
            if atom.atom_type == "uuid"
        )
        if boundary.status == "ready"
    )


def inspect_cr3_ctbo_atom(data: bytes) -> Cr3CtboInspection:
    if len(data) <= 12 or data[4:8] != b"CTBO":
        return Cr3CtboInspection("invalid_atom", None, (), (CR3_CTBO_FIXUP_SOURCE,))
    entry_count = int.from_bytes(data[8:12], byteorder="big")
    required_length = 12 + entry_count * 20
    if len(data) < required_length:
        return Cr3CtboInspection("truncated_atom", entry_count, (), (CR3_CTBO_FIXUP_SOURCE,))
    entries = tuple(
        Cr3CtboEntry(
            int.from_bytes(data[offset : offset + 4], byteorder="big"),
            int.from_bytes(data[offset + 4 : offset + 12], byteorder="big"),
            int.from_bytes(data[offset + 12 : offset + 20], byteorder="big"),
        )
        for offset in range(12, required_length, 20)
    )
    return Cr3CtboInspection("ready", entry_count, entries, (CR3_CTBO_FIXUP_SOURCE,))


def plan_cr3_ctbo_patches(
    ctbo_atom: bytes,
    uuid_offsets: tuple[Cr3CtboOffsetRegistration, ...],
    mdat_atom_offset: int | None,
) -> Cr3CtboPatchPlan:
    inspection = inspect_cr3_ctbo_atom(ctbo_atom)
    if not inspection.ready:
        return Cr3CtboPatchPlan("invalid_ctbo", (), None, inspection.evidence_ids)
    if mdat_atom_offset is None:
        return Cr3CtboPatchPlan(
            "missing_mdat",
            (),
            3,
            (CR3_CTBO_FIXUP_SOURCE, CR3_MDAT_EDIT_SOURCE),
        )

    offsets_by_id = {registration.item_id: registration for registration in uuid_offsets}
    offsets_by_id[3] = Cr3CtboOffsetRegistration(3, mdat_atom_offset, -1)
    patches: list[Cr3CtboPatch] = []
    for entry in inspection.entries:
        if entry.item_size == 0 and entry.item_id not in {1, 2}:
            continue
        registration = offsets_by_id.get(entry.item_id)
        if registration is None:
            if entry.item_id not in {1, 2}:
                return Cr3CtboPatchPlan(
                    "unknown_ctbo_id",
                    tuple(patches),
                    entry.item_id,
                    (CR3_CTBO_FIXUP_SOURCE,),
                )
            registration = Cr3CtboOffsetRegistration(entry.item_id, 0, 0)
        new_size = entry.item_size if registration.item_size < 0 else registration.item_size
        patches.append(
            Cr3CtboPatch(
                entry.item_id,
                entry.item_offset,
                entry.item_size,
                registration.item_offset,
                new_size,
                "mdat" if entry.item_id == 3 else "uuid",
            )
        )
    return Cr3CtboPatchPlan(
        "ready",
        tuple(patches),
        None,
        (CR3_CTBO_ID_SOURCE, CR3_UUID_WRITE_SOURCE, CR3_CTBO_FIXUP_SOURCE),
    )


def apply_cr3_ctbo_patches_to_rebuilt_stream(
    rebuilt_stream: bytes,
    ctbo_atom_offset: int,
    patch_plan: Cr3CtboPatchPlan,
) -> Cr3CtboPatchApplication:
    """Patch only the CTBO table fields inside an already rebuilt CR3 stream."""

    if not patch_plan.can_patch_table:
        return Cr3CtboPatchApplication(
            "patch_plan_not_ready",
            None,
            (),
            patch_plan.evidence_ids,
        )
    if ctbo_atom_offset < 0 or ctbo_atom_offset + 12 > len(rebuilt_stream):
        return Cr3CtboPatchApplication(
            "ctbo_offset_out_of_range",
            None,
            (),
            (CR3_CTBO_FIXUP_SOURCE,),
        )
    atom_size = int.from_bytes(
        rebuilt_stream[ctbo_atom_offset : ctbo_atom_offset + 4], byteorder="big"
    )
    if rebuilt_stream[ctbo_atom_offset + 4 : ctbo_atom_offset + 8] != b"CTBO":
        return Cr3CtboPatchApplication(
            "ctbo_atom_mismatch",
            None,
            (),
            (CR3_CTBO_FIXUP_SOURCE,),
        )
    if atom_size < 12 or ctbo_atom_offset + atom_size > len(rebuilt_stream):
        return Cr3CtboPatchApplication(
            "ctbo_atom_truncated",
            None,
            (),
            (CR3_CTBO_FIXUP_SOURCE,),
        )

    table = rebuilt_stream[ctbo_atom_offset : ctbo_atom_offset + atom_size]
    inspection = inspect_cr3_ctbo_atom(table)
    if not inspection.ready:
        return Cr3CtboPatchApplication(
            "ctbo_atom_truncated",
            None,
            (),
            inspection.evidence_ids,
        )

    patches_by_item_id = {patch.item_id: patch for patch in patch_plan.patches}
    patched_stream = bytearray(rebuilt_stream)
    applied_patches: list[Cr3CtboPatch] = []
    for index, entry in enumerate(inspection.entries):
        patch = patches_by_item_id.get(entry.item_id)
        if patch is None:
            continue
        entry_offset = ctbo_atom_offset + 12 + index * 20
        patched_stream[entry_offset + 4 : entry_offset + 12] = patch.new_offset.to_bytes(
            8, byteorder="big"
        )
        patched_stream[entry_offset + 12 : entry_offset + 20] = patch.new_size.to_bytes(
            8, byteorder="big"
        )
        applied_patches.append(patch)

    return Cr3CtboPatchApplication(
        "ready",
        bytes(patched_stream),
        tuple(applied_patches),
        (CR3_CTBO_FIXUP_SOURCE,),
    )


def build_cr3_canon_uuid_xmp_ctbo_mutation_plan(
    classification: CanonRawWriteRequestClassification | None = None,
) -> Cr3CanonUuidXmpCtboMutationPlan:
    if classification is not None and classification.container_kind != "cr3_quicktime":
        raise ValueError(
            f"Expected cr3_quicktime classification, got {classification.container_kind}"
        )
    requested_tags = (
        tuple(tag.requested_tag for tag in classification.tags) if classification else ()
    )
    target_surfaces = (
        tuple(
            dict.fromkeys(
                (
                    *(
                        surface
                        for tag in classification.tags
                        for surface in tag.target_surfaces
                        if surface.startswith("cr3_")
                    ),
                    "cr3_quicktime_ctbo_mdat_offsets",
                )
            )
        )
        if classification
        else (
            "cr3_quicktime_canon_uuid_tiff",
            "cr3_quicktime_top_level_xmp",
            "cr3_quicktime_ctbo_mdat_offsets",
        )
    )
    evidence_ids = unique_sources(
        (
            CR3_QUICKTIME_MAP_SOURCE,
            QUICKTIME_XMP_UUID_SOURCE,
            CR3_CANON_UUID_SOURCE,
            CR3_QUICKTIME_CANON2_SOURCE,
            CR3_CTBO_ID_SOURCE,
            CR3_OFFSET_COLLECTION_SOURCE,
            CR3_UUID_WRITE_SOURCE,
            CR3_WRITE_LAST_SOURCE,
            CR3_MDAT_EDIT_SOURCE,
            CR3_MDAT_BOUNDARY_SOURCE,
            CR3_CTBO_FIXUP_SOURCE,
            XMP_DC_SUBJECT_SOURCE,
            XMP_EXIF_EXPOSURE_COMPENSATION_SOURCE,
            EXIF_EXPOSURE_COMPENSATION_SOURCE,
        )
    )
    return Cr3CanonUuidXmpCtboMutationPlan(
        status="plan_only_deferred",
        requested_tags=requested_tags,
        target_surfaces=target_surfaces,
        prerequisites=CR3_PREREQUISITES,
        operations=CR3_OPERATIONS,
        safety_gates=CR3_SAFETY_GATES,
        evidence_ids=evidence_ids,
    )


def ascii_brand(data: bytes) -> str:
    return data.decode("latin-1")


def classify_cr3_uuid_identifier(
    uuid_identifier: bytes,
) -> tuple[Cr3UuidAtomKind, int | None, bool, bool, tuple[EvidenceId, ...]]:
    if uuid_identifier == XMP_UUID_IDENTIFIER:
        return "xmp", 1, True, False, (QUICKTIME_XMP_UUID_SOURCE, CR3_CTBO_ID_SOURCE)
    if uuid_identifier == CANON_UUID_IDENTIFIER:
        return (
            "canon",
            None,
            False,
            False,
            (QUICKTIME_CANON_UUID_SOURCE, CR3_CANON_UUID_SOURCE),
        )
    if uuid_identifier == CANON2_UUID_IDENTIFIER:
        return (
            "canon2",
            None,
            False,
            True,
            (QUICKTIME_CANON2_UUID_SOURCE, CR3_QUICKTIME_CANON2_SOURCE),
        )
    if uuid_identifier == PREVIEW_UUID_IDENTIFIER:
        return (
            "preview_image",
            2,
            True,
            False,
            (QUICKTIME_PREVIEW_UUID_SOURCE, CR3_CTBO_ID_SOURCE),
        )
    if uuid_identifier == BURST_ROLL_UUID_IDENTIFIER:
        return "burst_roll", 5, False, False, (CR3_CTBO_ID_SOURCE,)
    return "unknown", None, False, False, (CR3_QUICKTIME_MAP_SOURCE,)


def unique_sources(references: tuple[EvidenceId, ...]) -> tuple[EvidenceId, ...]:
    unique: list[EvidenceId] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


XMP_UUID_IDENTIFIER = b"\xbe\x7a\xcf\xcb\x97\xa9\x42\xe8\x9c\x71\x99\x94\x91\xe3\xaf\xac"
CANON_UUID_IDENTIFIER = b"\x85\xc0\xb6\x87\x82\x0f\x11\xe0\x81\x11\xf4\xce\x46\x2b\x6a\x48"
CANON2_UUID_IDENTIFIER = b"\x21\x0f\x16\x87\x91\x49\x11\xe4\x81\x11\x00\x24\x21\x31\xfc\xe4"
PREVIEW_UUID_IDENTIFIER = b"\xea\xf4\x2b\x5e\x1c\x98\x4b\x88\xb9\xfb\xb7\xdc\x40\x6e\x4d\x16"
BURST_ROLL_UUID_IDENTIFIER = b"\x57\x66\xb8\x29\xbb\x6a\x47\xc5\xbc\xfb\x8b\x9f\x22\x60\xd0\x6d"


CR3_PREREQUISITES: tuple[Cr3MutationPrerequisite, ...] = (
    Cr3MutationPrerequisite(
        "quicktime_cr3_brand_detected",
        "Input must be a QuickTime ftyp container with major or compatible brand crx.",
        (CR3_QUICKTIME_MAP_SOURCE,),
    ),
    Cr3MutationPrerequisite(
        "quicktime_atom_rewrite_engine_available",
        "A QuickTime atom rewriter must preserve atom hierarchy and supported offset atoms.",
        (CR3_QUICKTIME_MAP_SOURCE, CR3_OFFSET_COLLECTION_SOURCE),
    ),
    Cr3MutationPrerequisite(
        "top_level_xmp_uuid_writer_available",
        "XMP writes must target the top-level XMP UUID atom mapped directly below MOV.",
        (CR3_QUICKTIME_MAP_SOURCE, QUICKTIME_XMP_UUID_SOURCE),
    ),
    Cr3MutationPrerequisite(
        "canon_uuid_cmt_tiff_writer_available",
        "IFD0, ExifIFD, MakerNoteCanon, and GPS writes must rebuild CMT TIFF payloads.",
        (CR3_CANON_UUID_SOURCE,),
    ),
    Cr3MutationPrerequisite(
        "ctbo_uuid_offset_index_available",
        "CTBO fixups require an index of uuid atom positions keyed by Canon CTBO IDs.",
        (CR3_CTBO_ID_SOURCE, CR3_OFFSET_COLLECTION_SOURCE),
    ),
    Cr3MutationPrerequisite(
        "mdat_edit_engine_available",
        "mdat edits must be staged, size-checked, and assigned new positions before CTBO patching.",
        (CR3_MDAT_EDIT_SOURCE, CR3_MDAT_BOUNDARY_SOURCE),
    ),
    Cr3MutationPrerequisite(
        "iteminfo_mdat_boundary_checks_available",
        "ItemInfo-derived edits must be rejected if they cross an mdat boundary.",
        (CR3_MDAT_BOUNDARY_SOURCE,),
    ),
    Cr3MutationPrerequisite(
        "write_last_ordering_available",
        "UUID-Canon2 must be staged as WriteLast so DPP keeps image data.",
        (CR3_QUICKTIME_CANON2_SOURCE, CR3_WRITE_LAST_SOURCE),
    ),
)

CR3_OPERATIONS: tuple[Cr3MutationOperation, ...] = (
    Cr3MutationOperation(
        1,
        "validate_cr3_ftyp_brand",
        "Confirm that the QuickTime brand map should use CR3 routing.",
        ("quicktime_cr3_brand_detected",),
        ("validated_cr3_ftyp",),
        (CR3_QUICKTIME_MAP_SOURCE,),
    ),
    Cr3MutationOperation(
        2,
        "initialize_cr3_quicktime_write_map",
        "Route XMP to MOV and IFD0/ExifIFD/GPS to UUID-Canon.",
        ("quicktime_atom_rewrite_engine_available",),
        ("cr3_directory_map",),
        (CR3_QUICKTIME_MAP_SOURCE,),
    ),
    Cr3MutationOperation(
        3,
        "collect_ctbo_uuid_and_media_offsets",
        "Record CTBO, uuid, and media offset atoms before mutation so fixups have stable inputs.",
        ("quicktime_atom_rewrite_engine_available", "ctbo_uuid_offset_index_available"),
        ("chunk_offset_index",),
        (CR3_OFFSET_COLLECTION_SOURCE, CR3_CTBO_ID_SOURCE),
    ),
    Cr3MutationOperation(
        4,
        "rewrite_top_level_xmp_uuid",
        "Update Subject and XMP-exif tags in the top-level XMP UUID payload.",
        ("top_level_xmp_uuid_writer_available",),
        ("top_level_xmp_uuid",),
        (
            CR3_QUICKTIME_MAP_SOURCE,
            QUICKTIME_XMP_UUID_SOURCE,
            XMP_DC_SUBJECT_SOURCE,
            XMP_EXIF_EXPOSURE_COMPENSATION_SOURCE,
        ),
    ),
    Cr3MutationOperation(
        5,
        "rewrite_canon_uuid_cmt_tiff_payloads",
        "Update Canon UUID CMT1/CMT2/CMT3/CMT4 TIFF payloads with PreservePadding.",
        ("canon_uuid_cmt_tiff_writer_available",),
        ("canon_uuid_cmt_payloads",),
        (CR3_CANON_UUID_SOURCE, EXIF_EXPOSURE_COMPENSATION_SOURCE),
    ),
    Cr3MutationOperation(
        6,
        "stage_write_last_canon_uuid2_atoms",
        "Stage UUID-Canon2 updates for final top-level emission after media data.",
        ("write_last_ordering_available",),
        ("write_last_uuid2_payloads",),
        (CR3_QUICKTIME_CANON2_SOURCE, CR3_WRITE_LAST_SOURCE),
    ),
    Cr3MutationOperation(
        7,
        "edit_or_copy_mdat_chunks",
        "Apply ItemInfo-derived edits and copy unchanged media chunks through the mdat edit list.",
        ("mdat_edit_engine_available", "iteminfo_mdat_boundary_checks_available"),
        ("mdat_edit_list",),
        (CR3_MDAT_EDIT_SOURCE, CR3_MDAT_BOUNDARY_SOURCE),
    ),
    Cr3MutationOperation(
        8,
        "recalculate_mdat_positions",
        "Assign each mdat chunk its final position before offset tables are patched.",
        ("mdat_edit_engine_available",),
        ("new_mdat_positions",),
        (CR3_MDAT_EDIT_SOURCE,),
    ),
    Cr3MutationOperation(
        9,
        "patch_ctbo_item_offsets_and_sizes",
        "Patch CTBO item offsets and sizes for XMP, preview, mdat, and known Canon UUID entries.",
        ("ctbo_uuid_offset_index_available", "mdat_edit_engine_available"),
        ("patched_ctbo_table",),
        (CR3_CTBO_FIXUP_SOURCE, CR3_CTBO_ID_SOURCE),
    ),
    Cr3MutationOperation(
        10,
        "write_rebuilt_atoms_and_media_data",
        "Emit rebuilt non-media atoms, media chunks, and final WriteLast atoms in source order.",
        (
            "quicktime_atom_rewrite_engine_available",
            "mdat_edit_engine_available",
            "write_last_ordering_available",
        ),
        ("rebuilt_quicktime_stream",),
        (CR3_MDAT_EDIT_SOURCE, CR3_WRITE_LAST_SOURCE),
    ),
)

CR3_SAFETY_GATES: tuple[Cr3MutationSafetyGate, ...] = (
    Cr3MutationSafetyGate(
        "reject_non_cr3_brand",
        "validate_cr3_ftyp_brand",
        "The ftyp major or compatible brand must be crx before CR3 routing is used.",
        "Abort rather than applying Canon CR3 UUID semantics to another QuickTime family.",
        (CR3_QUICKTIME_MAP_SOURCE,),
    ),
    Cr3MutationSafetyGate(
        "reject_unsupported_fragmented_or_external_media",
        "collect_ctbo_uuid_and_media_offsets",
        "mfra, moof, sidx, saio, and mixed internal/external media data layouts are unsupported.",
        "Abort before atom mutation because offset repair would be incomplete.",
        (CR3_OFFSET_COLLECTION_SOURCE,),
    ),
    Cr3MutationSafetyGate(
        "ctbo_atom_length_and_entry_count_valid",
        "patch_ctbo_item_offsets_and_sizes",
        "CTBO must be longer than 12 bytes and contain N complete 20-byte entries.",
        "Abort on invalid or truncated CTBO instead of patching beyond the table.",
        (CR3_CTBO_FIXUP_SOURCE,),
    ),
    Cr3MutationSafetyGate(
        "mdat_available_for_ctbo_fixup",
        "patch_ctbo_item_offsets_and_sizes",
        "CR3 CTBO patching requires at least one mdat chunk to calculate item ID 3.",
        "Abort if media data is missing while CTBO or other offsets reference it.",
        (CR3_CTBO_FIXUP_SOURCE, CR3_MDAT_EDIT_SOURCE),
    ),
    Cr3MutationSafetyGate(
        "uuid_offsets_registered_for_ctbo_ids",
        "patch_ctbo_item_offsets_and_sizes",
        "Each non-deleted CTBO entry must resolve to a known uuid offset or mdat position.",
        "Abort rather than leave CTBO pointing at stale or missing uuid data.",
        (CR3_CTBO_ID_SOURCE, CR3_UUID_WRITE_SOURCE, CR3_CTBO_FIXUP_SOURCE),
    ),
    Cr3MutationSafetyGate(
        "unknown_ctbo_ids_rejected",
        "patch_ctbo_item_offsets_and_sizes",
        "Unknown CTBO IDs are rejected unless the missing entry is XMP or PreviewImage deletion.",
        "Abort with a CTBO ID error instead of guessing Canon-private item semantics.",
        (CR3_CTBO_FIXUP_SOURCE,),
    ),
    Cr3MutationSafetyGate(
        "canon_cmt_tiff_payloads_preserve_padding",
        "rewrite_canon_uuid_cmt_tiff_payloads",
        "CMT TIFF payload rewrites must preserve padding and MakerNotes directory identity.",
        (
            "Defer Canon UUID TIFF mutation until CMT payload padding and MakerNotes gates "
            "are enforced."
        ),
        (CR3_CANON_UUID_SOURCE,),
    ),
    Cr3MutationSafetyGate(
        "canon2_write_last_after_mdat",
        "write_rebuilt_atoms_and_media_data",
        "UUID-Canon2 must be emitted as a top-level WriteLast atom after mdat.",
        "Abort rather than produce a CR3 that Canon DPP may rewrite by dropping image data.",
        (CR3_QUICKTIME_CANON2_SOURCE, CR3_WRITE_LAST_SOURCE),
    ),
    Cr3MutationSafetyGate(
        "iteminfo_edits_stay_within_single_mdat",
        "edit_or_copy_mdat_chunks",
        "ItemInfo edit ranges must not run across mdat boundaries.",
        "Abort before media rewrite because the edit cannot be mapped to one mdat chunk.",
        (CR3_MDAT_BOUNDARY_SOURCE,),
    ),
    Cr3MutationSafetyGate(
        "mdat_size_growth_within_32bit_header_limit",
        "edit_or_copy_mdat_chunks",
        "If an mdat header is 32-bit, growth must not cross the 4 GB boundary.",
        "Abort before media rewrite when the mdat atom cannot be represented safely.",
        (CR3_MDAT_EDIT_SOURCE,),
    ),
)
