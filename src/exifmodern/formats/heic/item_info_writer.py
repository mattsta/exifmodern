"""Constrained HEIC ItemInfo/XMP byte writer for synthetic atom trees."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.heic.exif_item_info import (
    HEIC_EXIF_ITEM_TYPE,
    HeicExifItemOperation,
    HeicExifTiffHandoffPlan,
    plan_heic_exif_tiff_handoff,
)
from exifmodern.formats.heic.item_info_atoms import (
    HeicAtom,
    HeicAtomSpan,
    HeicIlocItemEntry,
    HeicMdatRewritePlan,
    HeicScheduledMdatEdits,
    apply_heic_recorded_iloc_offset_rewrites,
    apply_scheduled_mdat_edits_to_payload,
    discover_iloc_offset_pointer_sites,
    encode_full_box_payload,
    encode_heic_atom,
    encode_heic_atoms,
    encode_rebuilt_item_info_meta_payload,
    mdat_box_plan_from_atom_span,
    parse_iinf_payload,
    parse_iloc_payload,
    parse_iref_payload,
    plan_item_info_extent_replacement,
    plan_mdat_rewrite,
    plan_xmp_item_info_creation_rebuild,
    read_heic_atom_spans,
    schedule_mdat_prepend,
)
from exifmodern.formats.heic.offset_repair_plan import (
    MDAT_BOUNDARY_EVIDENCE_ID,
    QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID,
    RECORDED_OFFSET_FIXUP_EVIDENCE_ID,
)
from exifmodern.json_types import JsonObject

SYNTHETIC_HEIC_TEST_BRAND = "e2ts"

REAL_FIXTURE_TRANSACTIONAL_EMISSION_EVIDENCE_ID = (
    "heic.item_info_writer.real_fixture_transactional_emission"
)

type HeicItemInfoEmissionBlockerCode = Literal[
    "not_heic_item_info_container",
    "missing_top_level_meta",
    "missing_iinf_or_iloc_box",
    "missing_primary_item_reference",
    "missing_mdat_box",
    "unsupported_offset_bearing_atom",
    "malformed_iloc_offset_pointers",
    "requires_extended_mdat_header_preservation",
]


class HeicItemInfoSyntheticMutationRequiredError(RuntimeError):
    """Raised when a HEIC tree is outside the deliberately narrow synthetic writer."""


@dataclass(frozen=True)
class HeicItemInfoEmissionBlocker:
    code: HeicItemInfoEmissionBlockerCode
    detail: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class HeicItemInfoEmissionGate:
    can_emit_transactionally: bool
    brands: tuple[str, ...]
    mdat_count: int
    offset_bearing_atoms: tuple[str, ...]
    blockers: tuple[HeicItemInfoEmissionBlocker, ...]

    @property
    def blocker_codes(self) -> tuple[HeicItemInfoEmissionBlockerCode, ...]:
        return tuple(blocker.code for blocker in self.blockers)

    def to_json(self) -> JsonObject:
        return {
            "blockers": [blocker.to_json() for blocker in self.blockers],
            "brands": list(self.brands),
            "can_emit_transactionally": self.can_emit_transactionally,
            "mdat_count": self.mdat_count,
            "offset_bearing_atoms": list(self.offset_bearing_atoms),
        }


@dataclass(frozen=True)
class HeicSyntheticItemInfoRewriteResult:
    data: bytes
    item_id: int
    changed_atoms: int
    scheduled_mdat_edits: HeicScheduledMdatEdits


@dataclass(frozen=True)
class HeicItemInfoRewriteResult:
    data: bytes
    item_id: int
    changed_atoms: int
    scheduled_mdat_edits: HeicScheduledMdatEdits
    emission_gate: HeicItemInfoEmissionGate


@dataclass(frozen=True)
class HeicExistingXmpItem:
    item_id: int
    iloc_item: HeicIlocItemEntry


@dataclass(frozen=True)
class HeicExistingExifItem:
    item_id: int
    iloc_item: HeicIlocItemEntry


@dataclass(frozen=True)
class HeicExistingExifTiffHandoff:
    item_id: int
    exif_payload: bytes
    handoff: HeicExifTiffHandoffPlan
    emission_gate: HeicItemInfoEmissionGate


def rewrite_synthetic_heic_xmp_item(
    data: bytes,
    xmp_payload: bytes,
) -> HeicSyntheticItemInfoRewriteResult:
    """Create a primary-referenced XMP ItemInfo item in a synthetic HEIC tree.

    This is intentionally gated to files whose ``ftyp`` contains the private
    ``e2ts`` test brand.  It does not attempt global offset repair, so real HEIC
    fixtures remain blocked until the full ExifTool-style fixup phase exists.
    """

    top_atoms = read_heic_atom_spans(data)
    gate = assess_heic_item_info_emission_gate(data)
    require_synthetic_test_brand(top_atoms, gate)
    meta_atom = only_atom(top_atoms, "meta")
    mdat_atom = only_atom(top_atoms, "mdat")
    if meta_atom.offset > mdat_atom.offset:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "Synthetic HEIC ItemInfo writer requires meta before mdat."
        )
    if len(meta_atom.payload) < 4:
        raise HeicItemInfoSyntheticMutationRequiredError("Synthetic meta atom is truncated.")

    meta_full_header = meta_atom.payload[:4]
    meta_children = read_heic_atom_spans(meta_atom.payload, 4, len(meta_atom.payload))
    iinf_atom = required_child_atom(meta_children, "iinf")
    iloc_atom = required_child_atom(meta_children, "iloc")
    pitm_atom = required_child_atom(meta_children, "pitm")
    primary_item_id = parse_pitm_item_id(pitm_atom.payload)
    new_item_id = next_item_id(primary_item_id, iinf_atom.payload, iloc_atom.payload)
    schedule = schedule_mdat_prepend(new_item_id, xmp_payload)
    rebuild_plan = plan_xmp_item_info_creation_rebuild(
        meta_children,
        meta_payload_file_offset=meta_atom.offset + meta_atom.header_size,
        primary_item_id=primary_item_id,
        new_item_id=new_item_id,
        xmp_payload_length=len(xmp_payload),
    )
    rewritten_meta_payload = encode_rebuilt_item_info_meta_payload(
        meta_full_header,
        meta_children,
        rebuild_plan,
    )
    rewritten_non_mdat_size = sum(
        len(
            encode_heic_atom(
                atom.atom_type,
                rewritten_payload_for_non_mdat_atom(atom, rewritten_meta_payload),
            )
        )
        for atom in top_atoms
        if atom.atom_type != "mdat"
    )
    mdat_rewrite_plan = plan_mdat_rewrite(
        (mdat_box_plan_from_atom_span(mdat_atom, mdat_index=0),),
        schedule,
        rewritten_non_mdat_size=rewritten_non_mdat_size,
    )
    emitted = encode_heic_atoms(
        (
            *(
                HeicAtom(
                    atom.atom_type,
                    rewritten_payload_for_top_atom(atom, rewritten_meta_payload, schedule),
                )
                for atom in top_atoms
                if atom.atom_type != "mdat"
            ),
            HeicAtom(
                "mdat",
                apply_scheduled_mdat_edits_to_payload(mdat_atom.payload, schedule),
            ),
        )
    )
    offset_rewrite = apply_heic_recorded_iloc_offset_rewrites(
        emitted,
        (
            *rebuild_plan.shifted_existing_iloc_offset_sites,
            rebuild_plan.new_item_offset_site,
        ),
        mdat_rewrite_plan,
    )
    return HeicSyntheticItemInfoRewriteResult(
        data=offset_rewrite.data,
        item_id=new_item_id,
        changed_atoms=4,
        scheduled_mdat_edits=schedule,
    )


def rewrite_heic_xmp_item_transactionally(
    data: bytes,
    xmp_payload: bytes,
) -> HeicItemInfoRewriteResult:
    """Create a primary-referenced XMP ItemInfo item with transactional mdat output.

    This follows ExifTool's top-level write shape for HEIC ItemInfo creation:
    rewrite the top-level ``meta`` payload in memory, prepend the new item as an
    ``mdat`` edit to the first media-data box, compute final media positions, and
    patch recorded ``iloc`` offsets only after those positions are known.
    """

    gate = assess_heic_item_info_emission_gate(data)
    if not gate.can_emit_transactionally:
        blocker_text = ", ".join(gate.blocker_codes)
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo byte mutation is blocked by emission gate: " + blocker_text
        )
    top_atoms = read_heic_atom_spans(data)
    meta_atom = only_atom(top_atoms, "meta")
    if len(meta_atom.payload) < 4:
        raise HeicItemInfoSyntheticMutationRequiredError("HEIC meta atom is truncated.")

    meta_full_header = meta_atom.payload[:4]
    meta_children = read_heic_atom_spans(meta_atom.payload, 4, len(meta_atom.payload))
    iinf_atom = required_child_atom(meta_children, "iinf")
    iloc_atom = required_child_atom(meta_children, "iloc")
    pitm_atom = required_child_atom(meta_children, "pitm")
    primary_item_id = parse_pitm_item_id(pitm_atom.payload)
    new_item_id = next_item_id(primary_item_id, iinf_atom.payload, iloc_atom.payload)
    schedule = schedule_mdat_prepend(new_item_id, xmp_payload)
    rebuild_plan = plan_xmp_item_info_creation_rebuild(
        meta_children,
        meta_payload_file_offset=meta_atom.offset + meta_atom.header_size,
        primary_item_id=primary_item_id,
        new_item_id=new_item_id,
        xmp_payload_length=len(xmp_payload),
    )
    rewritten_meta_payload = encode_rebuilt_item_info_meta_payload(
        meta_full_header,
        meta_children,
        rebuild_plan,
    )
    rewritten_non_mdat_size = rewritten_top_level_non_mdat_size(top_atoms, rewritten_meta_payload)
    mdat_atoms = tuple(atom for atom in top_atoms if atom.atom_type == "mdat")
    mdat_rewrite_plan = plan_mdat_rewrite(
        tuple(
            mdat_box_plan_from_atom_span(atom, mdat_index=index)
            for index, atom in enumerate(mdat_atoms)
        ),
        schedule,
        rewritten_non_mdat_size=rewritten_non_mdat_size,
    )
    emitted = emit_transactional_heic_top_level_atoms(
        top_atoms,
        rewritten_meta_payload,
        schedule,
        mdat_rewrite_plan,
    )
    offset_rewrite = apply_heic_recorded_iloc_offset_rewrites(
        emitted,
        (
            *rebuild_plan.shifted_existing_iloc_offset_sites,
            rebuild_plan.new_item_offset_site,
        ),
        mdat_rewrite_plan,
    )
    return HeicItemInfoRewriteResult(
        data=offset_rewrite.data,
        item_id=new_item_id,
        changed_atoms=3 + len(mdat_rewrite_plan.boxes),
        scheduled_mdat_edits=schedule,
        emission_gate=gate,
    )


def replace_existing_heic_xmp_item_transactionally(
    data: bytes,
    xmp_payload: bytes,
) -> HeicItemInfoRewriteResult:
    """Replace or delete an existing primary-referenced HEIC XMP item.

    This models the existing-item branch of ExifTool's ``WriteItemInfo``:
    schedule replacement of the first old extent, deletion of any remaining old
    extents, rewrite the corresponding ``iloc`` extent lengths, then relocate
    recorded ``iloc`` offsets after final ``mdat`` positions are known.
    """

    gate = assess_heic_item_info_emission_gate(data)
    if not gate.can_emit_transactionally:
        blocker_text = ", ".join(gate.blocker_codes)
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo byte mutation is blocked by emission gate: " + blocker_text
        )
    top_atoms = read_heic_atom_spans(data)
    meta_atom = only_atom(top_atoms, "meta")
    if len(meta_atom.payload) < 4:
        raise HeicItemInfoSyntheticMutationRequiredError("HEIC meta atom is truncated.")

    meta_full_header = meta_atom.payload[:4]
    meta_children = read_heic_atom_spans(meta_atom.payload, 4, len(meta_atom.payload))
    iinf_atom = required_child_atom(meta_children, "iinf")
    iref_atom = required_child_atom(meta_children, "iref")
    iloc_atom = required_child_atom(meta_children, "iloc")
    pitm_atom = required_child_atom(meta_children, "pitm")
    primary_item_id = parse_pitm_item_id(pitm_atom.payload)
    existing_xmp = primary_xmp_item(
        iinf_atom.payload,
        iref_atom.payload,
        iloc_atom.payload,
        primary_item_id=primary_item_id,
    )
    mdat_atoms = tuple(atom for atom in top_atoms if atom.atom_type == "mdat")
    extent_plan = plan_item_info_extent_replacement(
        iloc_atom.payload,
        item=existing_xmp.iloc_item,
        replacement=xmp_payload,
        mdat_boxes=tuple(
            mdat_box_plan_from_atom_span(atom, mdat_index=index)
            for index, atom in enumerate(mdat_atoms)
        ),
    )
    rewritten_meta_payload = replace_meta_child_payload(
        meta_full_header,
        meta_children,
        atom_type="iloc",
        replacement_payload=extent_plan.iloc_payload,
    )
    rewritten_non_mdat_size = rewritten_top_level_non_mdat_size(top_atoms, rewritten_meta_payload)
    mdat_rewrite_plan = plan_mdat_rewrite(
        tuple(
            mdat_box_plan_from_atom_span(atom, mdat_index=index)
            for index, atom in enumerate(mdat_atoms)
        ),
        extent_plan.scheduled_mdat_edits,
        rewritten_non_mdat_size=rewritten_non_mdat_size,
    )
    emitted = emit_transactional_heic_top_level_atoms(
        top_atoms,
        rewritten_meta_payload,
        extent_plan.scheduled_mdat_edits,
        mdat_rewrite_plan,
    )
    offset_rewrite = apply_heic_recorded_iloc_offset_rewrites(
        emitted,
        discover_iloc_offset_pointer_sites(
            extent_plan.iloc_payload,
            iloc_box_file_offset=meta_atom.offset + meta_atom.header_size + iloc_atom.offset,
        ),
        mdat_rewrite_plan,
    )
    return HeicItemInfoRewriteResult(
        data=offset_rewrite.data,
        item_id=existing_xmp.item_id,
        changed_atoms=1 + len(mdat_rewrite_plan.boxes),
        scheduled_mdat_edits=extent_plan.scheduled_mdat_edits,
        emission_gate=gate,
    )


def plan_existing_heic_exif_item_tiff_handoff(data: bytes) -> HeicExistingExifTiffHandoff:
    """Return the source-backed EXIF ItemInfo payload boundary for TIFF rewriting."""

    gate = assess_heic_item_info_emission_gate(data)
    if not gate.can_emit_transactionally:
        blocker_text = ", ".join(gate.blocker_codes)
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo byte mutation is blocked by emission gate: " + blocker_text
        )
    top_atoms = read_heic_atom_spans(data)
    meta_atom = only_atom(top_atoms, "meta")
    meta_children = read_heic_atom_spans(meta_atom.payload, 4, len(meta_atom.payload))
    iinf_atom = required_child_atom(meta_children, "iinf")
    iref_atom = required_child_atom(meta_children, "iref")
    iloc_atom = required_child_atom(meta_children, "iloc")
    pitm_atom = required_child_atom(meta_children, "pitm")
    existing_exif = primary_exif_item(
        iinf_atom.payload,
        iref_atom.payload,
        iloc_atom.payload,
        primary_item_id=parse_pitm_item_id(pitm_atom.payload),
    )
    exif_payload = item_info_payload(data, existing_exif.iloc_item)
    operation: HeicExifItemOperation = (
        "delete_existing_exif_item" if not exif_payload else "rewrite_existing_exif_item"
    )
    return HeicExistingExifTiffHandoff(
        item_id=existing_exif.item_id,
        exif_payload=exif_payload,
        handoff=plan_heic_exif_tiff_handoff(exif_payload, operation=operation),
        emission_gate=gate,
    )


def replace_existing_heic_exif_item_payload_transactionally(
    data: bytes,
    exif_payload: bytes,
) -> HeicItemInfoRewriteResult:
    """Replace/delete an existing HEIC EXIF item with already rewritten EXIF bytes."""

    handoff = plan_existing_heic_exif_item_tiff_handoff(data)
    if not handoff.handoff.can_handoff_to_tiff:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC EXIF ItemInfo replacement requires a valid EXIF item header."
        )
    top_atoms = read_heic_atom_spans(data)
    meta_atom = only_atom(top_atoms, "meta")
    meta_full_header = meta_atom.payload[:4]
    meta_children = read_heic_atom_spans(meta_atom.payload, 4, len(meta_atom.payload))
    iinf_atom = required_child_atom(meta_children, "iinf")
    iref_atom = required_child_atom(meta_children, "iref")
    iloc_atom = required_child_atom(meta_children, "iloc")
    pitm_atom = required_child_atom(meta_children, "pitm")
    existing_exif = primary_exif_item(
        iinf_atom.payload,
        iref_atom.payload,
        iloc_atom.payload,
        primary_item_id=parse_pitm_item_id(pitm_atom.payload),
    )
    mdat_atoms = tuple(atom for atom in top_atoms if atom.atom_type == "mdat")
    extent_plan = plan_item_info_extent_replacement(
        iloc_atom.payload,
        item=existing_exif.iloc_item,
        replacement=exif_payload,
        mdat_boxes=tuple(
            mdat_box_plan_from_atom_span(atom, mdat_index=index)
            for index, atom in enumerate(mdat_atoms)
        ),
    )
    rewritten_meta_payload = replace_meta_child_payload(
        meta_full_header,
        meta_children,
        atom_type="iloc",
        replacement_payload=extent_plan.iloc_payload,
    )
    rewritten_non_mdat_size = rewritten_top_level_non_mdat_size(top_atoms, rewritten_meta_payload)
    mdat_rewrite_plan = plan_mdat_rewrite(
        tuple(
            mdat_box_plan_from_atom_span(atom, mdat_index=index)
            for index, atom in enumerate(mdat_atoms)
        ),
        extent_plan.scheduled_mdat_edits,
        rewritten_non_mdat_size=rewritten_non_mdat_size,
    )
    emitted = emit_transactional_heic_top_level_atoms(
        top_atoms,
        rewritten_meta_payload,
        extent_plan.scheduled_mdat_edits,
        mdat_rewrite_plan,
    )
    offset_rewrite = apply_heic_recorded_iloc_offset_rewrites(
        emitted,
        discover_iloc_offset_pointer_sites(
            extent_plan.iloc_payload,
            iloc_box_file_offset=meta_atom.offset + meta_atom.header_size + iloc_atom.offset,
        ),
        mdat_rewrite_plan,
    )
    return HeicItemInfoRewriteResult(
        data=offset_rewrite.data,
        item_id=existing_exif.item_id,
        changed_atoms=1 + len(mdat_rewrite_plan.boxes),
        scheduled_mdat_edits=extent_plan.scheduled_mdat_edits,
        emission_gate=handoff.emission_gate,
    )


def has_primary_xmp_item(data: bytes) -> bool:
    top_atoms = read_heic_atom_spans(data)
    meta_atom = child_atom(top_atoms, "meta")
    if meta_atom is None or len(meta_atom.payload) < 4:
        return False
    meta_children = read_heic_atom_spans(meta_atom.payload, 4, len(meta_atom.payload))
    iinf_atom = child_atom(meta_children, "iinf")
    iref_atom = child_atom(meta_children, "iref")
    iloc_atom = child_atom(meta_children, "iloc")
    pitm_atom = child_atom(meta_children, "pitm")
    if iinf_atom is None or iref_atom is None or iloc_atom is None or pitm_atom is None:
        return False
    return bool(
        primary_xmp_item_ids(
            iinf_atom.payload,
            iref_atom.payload,
            primary_item_id=parse_pitm_item_id(pitm_atom.payload),
        )
    )


def has_primary_exif_item(data: bytes) -> bool:
    top_atoms = read_heic_atom_spans(data)
    meta_atom = child_atom(top_atoms, "meta")
    if meta_atom is None or len(meta_atom.payload) < 4:
        return False
    meta_children = read_heic_atom_spans(meta_atom.payload, 4, len(meta_atom.payload))
    iinf_atom = child_atom(meta_children, "iinf")
    iref_atom = child_atom(meta_children, "iref")
    pitm_atom = child_atom(meta_children, "pitm")
    if iinf_atom is None or iref_atom is None or pitm_atom is None:
        return False
    return bool(
        primary_exif_item_ids(
            iinf_atom.payload,
            iref_atom.payload,
            primary_item_id=parse_pitm_item_id(pitm_atom.payload),
        )
    )


def rewritten_top_level_non_mdat_size(
    top_atoms: tuple[HeicAtomSpan, ...],
    rewritten_meta_payload: bytes,
) -> int:
    return sum(
        len(
            encode_heic_atom(
                atom.atom_type,
                rewritten_payload_for_non_mdat_atom(atom, rewritten_meta_payload),
            )
        )
        for atom in top_atoms
        if atom.atom_type != "mdat"
    )


def emit_transactional_heic_top_level_atoms(
    top_atoms: tuple[HeicAtomSpan, ...],
    rewritten_meta_payload: bytes,
    schedule: HeicScheduledMdatEdits,
    mdat_rewrite_plan: HeicMdatRewritePlan,
) -> bytes:
    """Emit ExifTool-style top-level output: metadata first, media data last."""

    non_mdat = b"".join(
        encode_heic_atom(
            atom.atom_type,
            rewritten_payload_for_non_mdat_atom(atom, rewritten_meta_payload),
        )
        for atom in top_atoms
        if atom.atom_type != "mdat"
    )
    mdat_atoms = tuple(atom for atom in top_atoms if atom.atom_type == "mdat")
    emitted_mdat = b"".join(
        encode_mdat_atom_with_preserved_header(
            atom,
            apply_scheduled_mdat_edits_to_payload(atom.payload, schedule, mdat_index=index),
        )
        for index, atom in enumerate(mdat_atoms)
    )
    if len(non_mdat) + len(emitted_mdat) != expected_transactional_output_size(mdat_rewrite_plan):
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC transactional emission size did not match the mdat rewrite plan."
        )
    return non_mdat + emitted_mdat


def encode_mdat_atom_with_preserved_header(atom: HeicAtomSpan, payload: bytes) -> bytes:
    if atom.atom_type != "mdat":
        raise ValueError("Only mdat atoms may be emitted with preserved media headers.")
    if atom.header_size == 8:
        return encode_heic_atom("mdat", payload)
    raise HeicItemInfoSyntheticMutationRequiredError(
        "Extended-size mdat headers require a dedicated HEIC emission primitive."
    )


def expected_transactional_output_size(mdat_rewrite_plan: HeicMdatRewritePlan) -> int:
    if not mdat_rewrite_plan.boxes:
        return 0
    last_box = mdat_rewrite_plan.boxes[-1]
    return last_box.new_atom_offset + last_box.header_size + last_box.new_payload_length


def rewritten_payload_for_top_atom(
    atom: HeicAtomSpan,
    rewritten_meta_payload: bytes,
    schedule: HeicScheduledMdatEdits,
) -> bytes:
    if atom.atom_type == "meta":
        return rewritten_meta_payload
    if atom.atom_type == "mdat":
        return apply_scheduled_mdat_edits_to_payload(atom.payload, schedule)
    return atom.payload


def rewritten_payload_for_non_mdat_atom(
    atom: HeicAtomSpan,
    rewritten_meta_payload: bytes,
) -> bytes:
    if atom.atom_type == "meta":
        return rewritten_meta_payload
    return atom.payload


def replace_meta_child_payload(
    meta_full_header: bytes,
    meta_children: tuple[HeicAtomSpan, ...],
    *,
    atom_type: str,
    replacement_payload: bytes,
) -> bytes:
    replaced = False
    rewritten_children: list[HeicAtom] = []
    for child in meta_children:
        if child.atom_type == atom_type:
            rewritten_children.append(HeicAtom(child.atom_type, replacement_payload))
            replaced = True
        else:
            rewritten_children.append(HeicAtom(child.atom_type, child.payload))
    if not replaced:
        raise HeicItemInfoSyntheticMutationRequiredError(
            f"HEIC ItemInfo replacement requires a {atom_type} atom."
        )
    return meta_full_header + encode_heic_atoms(tuple(rewritten_children))


def primary_xmp_item(
    iinf_payload: bytes,
    iref_payload: bytes,
    iloc_payload: bytes,
    *,
    primary_item_id: int,
) -> HeicExistingXmpItem:
    xmp_entries = {
        entry.item_id: entry
        for entry in parse_iinf_payload(iinf_payload).entries
        if entry.content_type == "application/rdf+xml"
    }
    iloc_items = {item.item_id: item for item in parse_iloc_payload(iloc_payload).items}
    matches = primary_xmp_item_ids(
        iinf_payload,
        iref_payload,
        primary_item_id=primary_item_id,
    )
    if len(matches) != 1:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo replacement requires exactly one primary-referenced XMP item."
        )
    entry = xmp_entries[matches[0]]
    if entry.protection_index:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo replacement requires unprotected XMP metadata."
        )
    if entry.content_encoding is not None:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo replacement requires uncompressed XMP metadata."
        )
    item = iloc_items.get(matches[0])
    if item is None:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo replacement requires a matching iloc item."
        )
    if item.construction_method != 0:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo replacement requires construction method 0."
        )
    if item.data_reference_index != 0:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo replacement requires metadata stored in this file."
        )
    return HeicExistingXmpItem(item_id=matches[0], iloc_item=item)


def primary_exif_item(
    iinf_payload: bytes,
    iref_payload: bytes,
    iloc_payload: bytes,
    *,
    primary_item_id: int,
) -> HeicExistingExifItem:
    exif_entries = {
        entry.item_id: entry
        for entry in parse_iinf_payload(iinf_payload).entries
        if (entry.content_type or entry.item_type) == HEIC_EXIF_ITEM_TYPE
    }
    iloc_items = {item.item_id: item for item in parse_iloc_payload(iloc_payload).items}
    matches = primary_exif_item_ids(
        iinf_payload,
        iref_payload,
        primary_item_id=primary_item_id,
    )
    if len(matches) != 1:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo replacement requires exactly one primary-referenced EXIF item."
        )
    entry = exif_entries[matches[0]]
    if entry.protection_index:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo replacement requires unprotected EXIF metadata."
        )
    if entry.content_encoding is not None:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo replacement requires uncompressed EXIF metadata."
        )
    item = iloc_items.get(matches[0])
    if item is None:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo replacement requires a matching iloc item."
        )
    if item.construction_method != 0:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo replacement requires construction method 0."
        )
    if item.data_reference_index != 0:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo replacement requires metadata stored in this file."
        )
    return HeicExistingExifItem(item_id=matches[0], iloc_item=item)


def primary_xmp_item_ids(
    iinf_payload: bytes,
    iref_payload: bytes,
    *,
    primary_item_id: int,
) -> tuple[int, ...]:
    xmp_item_ids = tuple(
        entry.item_id
        for entry in parse_iinf_payload(iinf_payload).entries
        if entry.content_type == "application/rdf+xml"
    )
    referred_item_ids = {
        reference.from_item_id
        for reference in parse_iref_payload(iref_payload).cdsc_references
        if primary_item_id in reference.to_item_ids
    }
    return tuple(item_id for item_id in xmp_item_ids if item_id in referred_item_ids)


def primary_exif_item_ids(
    iinf_payload: bytes,
    iref_payload: bytes,
    *,
    primary_item_id: int,
) -> tuple[int, ...]:
    exif_item_ids = tuple(
        entry.item_id
        for entry in parse_iinf_payload(iinf_payload).entries
        if (entry.content_type or entry.item_type) == HEIC_EXIF_ITEM_TYPE
    )
    referred_item_ids = {
        reference.from_item_id
        for reference in parse_iref_payload(iref_payload).cdsc_references
        if primary_item_id in reference.to_item_ids
    }
    return tuple(item_id for item_id in exif_item_ids if item_id in referred_item_ids)


def item_info_payload(data: bytes, item: HeicIlocItemEntry) -> bytes:
    return b"".join(
        data[
            item.base_offset + extent.extent_offset : item.base_offset
            + extent.extent_offset
            + extent.extent_length
        ]
        for extent in item.extents
    )


def parse_pitm_item_id(payload: bytes) -> int:
    if len(payload) < 6:
        raise HeicItemInfoSyntheticMutationRequiredError("Synthetic pitm atom is truncated.")
    version = payload[0]
    if version == 0:
        return int.from_bytes(payload[4:6], "big")
    if len(payload) < 8:
        raise HeicItemInfoSyntheticMutationRequiredError(
            "Synthetic pitm version 1 atom is truncated."
        )
    return int.from_bytes(payload[4:8], "big")


def next_item_id(primary_item_id: int, iinf_payload: bytes, iloc_payload: bytes) -> int:
    iinf_ids = tuple(entry.item_id for entry in parse_iinf_payload(iinf_payload).entries)
    iloc_ids = tuple(item.item_id for item in parse_iloc_payload(iloc_payload).items)
    return max((primary_item_id, *iinf_ids, *iloc_ids)) + 1


def assess_heic_item_info_emission_gate(data: bytes) -> HeicItemInfoEmissionGate:
    """Classify whether the package-local ItemInfo emitter may write this tree.

    This gate is intentionally narrower than ExifTool.  It identifies real
    fixture shapes whose ItemInfo mutation still needs top-level transactional
    emission before byte writes can be enabled.
    """

    top_atoms = read_heic_atom_spans(data)
    ftyp_atom = child_atom(top_atoms, "ftyp")
    brands = ftyp_brands(ftyp_atom.payload) if ftyp_atom is not None else ()
    meta_atoms = tuple(atom for atom in top_atoms if atom.atom_type == "meta")
    mdat_atoms = tuple(atom for atom in top_atoms if atom.atom_type == "mdat")
    blockers: list[HeicItemInfoEmissionBlocker] = []
    if not is_heic_item_info_brand(brands):
        blockers.append(
            HeicItemInfoEmissionBlocker(
                code="not_heic_item_info_container",
                detail="HEIC ItemInfo writes require a HEIC/HEIF/AVIF-compatible brand.",
                evidence_ids=(QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID,),
            )
        )
    if len(meta_atoms) != 1:
        blockers.append(
            HeicItemInfoEmissionBlocker(
                code="missing_top_level_meta",
                detail="WriteItemInfo is dispatched from exactly one top-level meta box.",
                evidence_ids=(REAL_FIXTURE_TRANSACTIONAL_EMISSION_EVIDENCE_ID,),
            )
        )
    if not mdat_atoms:
        blockers.append(
            HeicItemInfoEmissionBlocker(
                code="missing_mdat_box",
                detail="Scheduled ItemInfo payload edits must be applied to media data.",
                evidence_ids=(MDAT_BOUNDARY_EVIDENCE_ID,),
            )
        )
    if any(atom.header_size == 16 for atom in mdat_atoms):
        blockers.append(
            HeicItemInfoEmissionBlocker(
                code="requires_extended_mdat_header_preservation",
                detail="Extended-size mdat headers must be preserved and resized explicitly.",
                evidence_ids=(MDAT_BOUNDARY_EVIDENCE_ID,),
            )
        )

    offset_atoms: list[str] = []
    if len(meta_atoms) == 1 and len(meta_atoms[0].payload) >= 4:
        meta_children = read_heic_atom_spans(meta_atoms[0].payload, 4, len(meta_atoms[0].payload))
        if child_atom(meta_children, "iinf") is None or child_atom(meta_children, "iloc") is None:
            blockers.append(
                HeicItemInfoEmissionBlocker(
                    code="missing_iinf_or_iloc_box",
                    detail="Creating ItemInfo metadata requires existing iinf and iloc boxes.",
                    evidence_ids=(MDAT_BOUNDARY_EVIDENCE_ID,),
                )
            )
        if child_atom(meta_children, "pitm") is None:
            blockers.append(
                HeicItemInfoEmissionBlocker(
                    code="missing_primary_item_reference",
                    detail=(
                        "The current emitter requires an existing pitm primary item reference "
                        "before creating a cdsc reference."
                    ),
                    evidence_ids=(MDAT_BOUNDARY_EVIDENCE_ID,),
                )
            )
        for atom_path, atom in flatten_heic_atoms(meta_children, prefix=("meta",)):
            if atom.atom_type not in offset_bearing_atom_types():
                continue
            offset_atoms.append("/".join((*atom_path, atom.atom_type)))
            if atom.atom_type == "iloc":
                try:
                    discover_iloc_offset_pointer_sites(
                        atom.payload,
                        iloc_box_file_offset=meta_atoms[0].offset
                        + meta_atoms[0].header_size
                        + atom.offset,
                    )
                except ValueError as exc:
                    blockers.append(
                        HeicItemInfoEmissionBlocker(
                            code="malformed_iloc_offset_pointers",
                            detail=str(exc),
                            evidence_ids=(QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID,),
                        )
                    )
                continue
            blockers.append(
                HeicItemInfoEmissionBlocker(
                    code="unsupported_offset_bearing_atom",
                    detail=f"Offset-bearing atom {atom.atom_type!r} requires a repair primitive.",
                    evidence_ids=(
                        QUICKTIME_OFFSET_DISCOVERY_EVIDENCE_ID,
                        RECORDED_OFFSET_FIXUP_EVIDENCE_ID,
                    ),
                )
            )

    return HeicItemInfoEmissionGate(
        can_emit_transactionally=not blockers,
        brands=brands,
        mdat_count=len(mdat_atoms),
        offset_bearing_atoms=tuple(dict.fromkeys(offset_atoms)),
        blockers=tuple(blockers),
    )


def require_synthetic_test_brand(
    top_atoms: tuple[HeicAtomSpan, ...],
    gate: HeicItemInfoEmissionGate,
) -> None:
    ftyp_atom = child_atom(top_atoms, "ftyp")
    if ftyp_atom is None or SYNTHETIC_HEIC_TEST_BRAND not in ftyp_brands(ftyp_atom.payload):
        if gate.blockers:
            blocker_text = ", ".join(gate.blocker_codes)
            raise HeicItemInfoSyntheticMutationRequiredError(
                "HEIC ItemInfo byte mutation is currently enabled only for synthetic e2ts "
                f"trees; real-fixture blockers: {blocker_text}."
            )
        raise HeicItemInfoSyntheticMutationRequiredError(
            "HEIC ItemInfo byte mutation is currently enabled only for synthetic e2ts trees."
        )


def is_heic_item_info_brand(brands: tuple[str, ...]) -> bool:
    return bool({"heic", "mif1", "msf1", "heix", "hevc", "hevx", "avif"}.intersection(brands))


def offset_bearing_atom_types() -> set[str]:
    return {"stco", "co64", "iloc", "mfra", "moof", "sidx", "saio", "gps ", "CTBO", "uuid"}


def flatten_heic_atoms(
    atoms: tuple[HeicAtomSpan, ...],
    *,
    prefix: tuple[str, ...] = (),
) -> tuple[tuple[tuple[str, ...], HeicAtomSpan], ...]:
    flattened: list[tuple[tuple[str, ...], HeicAtomSpan]] = []
    for atom in atoms:
        flattened.append((prefix, atom))
        child_start = 4 if atom.atom_type in {"meta", "iref"} else 0
        if atom.atom_type in {"meta", "iref", "iprp", "ipco"} and len(atom.payload) >= child_start:
            flattened.extend(
                flatten_heic_atoms(
                    read_heic_atom_spans(atom.payload, child_start, len(atom.payload)),
                    prefix=(*prefix, atom.atom_type),
                )
            )
    return tuple(flattened)


def ftyp_brands(payload: bytes) -> tuple[str, ...]:
    if len(payload) < 8:
        return ()
    brands = [payload[:4].decode("latin-1")]
    pos = 8
    while pos + 4 <= len(payload):
        brands.append(payload[pos : pos + 4].decode("latin-1"))
        pos += 4
    return tuple(brands)


def child_atom(atoms: tuple[HeicAtomSpan, ...], atom_type: str) -> HeicAtomSpan | None:
    for atom in atoms:
        if atom.atom_type == atom_type:
            return atom
    return None


def required_child_atom(atoms: tuple[HeicAtomSpan, ...], atom_type: str) -> HeicAtomSpan:
    atom = child_atom(atoms, atom_type)
    if atom is None:
        raise HeicItemInfoSyntheticMutationRequiredError(
            f"Synthetic HEIC ItemInfo writer requires a {atom_type} atom."
        )
    return atom


def only_atom(atoms: tuple[HeicAtomSpan, ...], atom_type: str) -> HeicAtomSpan:
    matches = tuple(atom for atom in atoms if atom.atom_type == atom_type)
    if len(matches) != 1:
        raise HeicItemInfoSyntheticMutationRequiredError(
            f"Synthetic HEIC ItemInfo writer requires exactly one {atom_type} atom."
        )
    return matches[0]


def pitm_payload(item_id: int) -> bytes:
    if item_id <= 0xFFFF:
        return encode_full_box_payload(0, 0, item_id.to_bytes(2, "big"))
    return encode_full_box_payload(1, 0, item_id.to_bytes(4, "big"))


def encode_synthetic_meta(children: tuple[HeicAtom, ...]) -> bytes:
    return encode_heic_atom(
        "meta",
        encode_full_box_payload(0, 0, encode_heic_atoms(children)),
    )
