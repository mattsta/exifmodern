"""HEIC ItemInfo metadata writer guard and XMP packet routing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.exif_scalar_write_plan import ExifScalarWritePlan
from exifmodern.file_transaction import FileWriteTransactionResult, write_bytes_transactionally
from exifmodern.formats.heic.item_info_atoms import parse_iloc_payload, read_heic_atom_spans
from exifmodern.formats.heic.item_info_write_plan import HeicItemInfoWriteClassification
from exifmodern.formats.heic.item_info_writer import (
    HeicItemInfoEmissionGate,
    HeicItemInfoRewriteResult,
    has_primary_xmp_item,
    parse_pitm_item_id,
    plan_existing_heic_exif_item_tiff_handoff,
    primary_xmp_item,
    replace_existing_heic_exif_item_payload_transactionally,
    replace_existing_heic_xmp_item_transactionally,
    rewrite_heic_xmp_item_transactionally,
)
from exifmodern.formats.tiff.exif_scalar_rewriter import (
    create_minimal_exif_scalar_tiff,
    rewrite_exif_scalars_creating_if_needed,
)
from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
from exifmodern.formats.xmp.packet import empty_xmp_packet
from exifmodern.formats.xmp.property_write import XmpPropertyWritePlan


class HeicItemInfoUnsupportedWriteError(RuntimeError):
    """Raised when a HEIC ItemInfo request is source-backed but not safely writable."""


@dataclass(frozen=True)
class HeicItemInfoRewriteReadiness:
    supported: bool
    reason: str
    blocker_codes: tuple[str, ...]


@dataclass(frozen=True)
class HeicItemInfoXmpRewriteResult:
    data: bytes
    changed_xmp_properties: int
    item_id: int
    changed_atoms: int
    emission_gate: HeicItemInfoEmissionGate
    transaction: FileWriteTransactionResult | None = None


@dataclass(frozen=True)
class HeicItemInfoExifScalarRewriteResult:
    data: bytes
    item_id: int
    original_exif_payload_size: int
    rewritten_exif_payload_size: int
    changed_atoms: int
    emission_gate: HeicItemInfoEmissionGate
    transaction: FileWriteTransactionResult | None = None


def require_supported_heic_item_info_rewrite(
    classification: HeicItemInfoWriteClassification,
) -> HeicItemInfoRewriteReadiness:
    blocker_codes = tuple(blocker for tag in classification.tags for blocker in tag.blocker_codes)
    if classification.supported_for_modern_mutation:
        return HeicItemInfoRewriteReadiness(
            supported=True,
            reason="HEIC ItemInfo request is supported by the transactional modern writer.",
            blocker_codes=(),
        )
    unique_blockers = tuple(dict.fromkeys(blocker_codes))
    raise HeicItemInfoUnsupportedWriteError(
        "HEIC ItemInfo/XMP rewrite is deferred until source-backed iinf/iref/iloc/mdat "
        "mutation is implemented: " + ", ".join(unique_blockers)
    )


def rewrite_heic_item_info_exif_scalars(
    data: bytes,
    exif_plan: ExifScalarWritePlan,
) -> HeicItemInfoExifScalarRewriteResult:
    """Rewrite a primary-referenced existing HEIC EXIF ItemInfo payload.

    The upstream QuickTime writer strips the HEIC EXIF item envelope, delegates
    the embedded TIFF bytes to WriteTIFF, prefixes the saved envelope again, and
    schedules the result as an mdat replacement.  This adapter uses the existing
    ExifModern TIFF scalar mutator for that middle step.
    """

    handoff = plan_existing_heic_exif_item_tiff_handoff(data)
    if not handoff.handoff.can_handoff_to_tiff:
        raise HeicItemInfoUnsupportedWriteError(
            "HEIC EXIF scalar rewrite requires a valid EXIF item header: "
            + (handoff.handoff.warning or "invalid EXIF item")
        )
    if exif_plan.is_delete_only or handoff.handoff.tiff_payload:
        rewritten_tiff = rewrite_exif_scalars_creating_if_needed(
            handoff.handoff.tiff_payload,
            exif_plan,
        )
    else:
        rewritten_tiff = create_minimal_exif_scalar_tiff(exif_plan)
    rewritten_exif_payload = handoff.handoff.header + rewritten_tiff
    item_info_result = replace_existing_heic_exif_item_payload_transactionally(
        data,
        rewritten_exif_payload,
    )
    return HeicItemInfoExifScalarRewriteResult(
        data=item_info_result.data,
        item_id=item_info_result.item_id,
        original_exif_payload_size=len(handoff.exif_payload),
        rewritten_exif_payload_size=len(rewritten_exif_payload),
        changed_atoms=item_info_result.changed_atoms,
        emission_gate=item_info_result.emission_gate,
    )


def rewrite_heic_item_info_file_exif_scalars(
    input_path: Path,
    output_path: Path,
    exif_plan: ExifScalarWritePlan,
) -> HeicItemInfoExifScalarRewriteResult:
    result = rewrite_heic_item_info_exif_scalars(input_path.read_bytes(), exif_plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return HeicItemInfoExifScalarRewriteResult(
        data=result.data,
        item_id=result.item_id,
        original_exif_payload_size=result.original_exif_payload_size,
        rewritten_exif_payload_size=result.rewritten_exif_payload_size,
        changed_atoms=result.changed_atoms,
        emission_gate=result.emission_gate,
        transaction=transaction,
    )


def rewrite_heic_item_info_xmp_properties(
    data: bytes,
    xmp_plan: XmpPropertyWritePlan,
) -> HeicItemInfoXmpRewriteResult:
    """Create or replace a primary-referenced HEIC XMP ItemInfo item from a plan."""

    existing_packet = primary_xmp_payload(data) if has_primary_xmp_item(data) else None
    xmp_result = apply_xmp_property_write_plan(existing_packet or empty_xmp_packet(), xmp_plan)
    if existing_packet is None:
        item_info_result: HeicItemInfoRewriteResult = rewrite_heic_xmp_item_transactionally(
            data,
            xmp_result.packet,
        )
    else:
        item_info_result = replace_existing_heic_xmp_item_transactionally(
            data,
            xmp_result.packet,
        )
    return HeicItemInfoXmpRewriteResult(
        data=item_info_result.data,
        changed_xmp_properties=xmp_result.changed_properties,
        item_id=item_info_result.item_id,
        changed_atoms=item_info_result.changed_atoms,
        emission_gate=item_info_result.emission_gate,
    )


def rewrite_heic_item_info_file_xmp_properties(
    input_path: Path,
    output_path: Path,
    xmp_plan: XmpPropertyWritePlan,
) -> HeicItemInfoXmpRewriteResult:
    result = rewrite_heic_item_info_xmp_properties(input_path.read_bytes(), xmp_plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return HeicItemInfoXmpRewriteResult(
        data=result.data,
        changed_xmp_properties=result.changed_xmp_properties,
        item_id=result.item_id,
        changed_atoms=result.changed_atoms,
        emission_gate=result.emission_gate,
        transaction=transaction,
    )


def primary_xmp_payload(data: bytes) -> bytes:
    """Read the current primary XMP item for the bounded replacement path."""

    top_atoms = read_heic_atom_spans(data)
    meta_atom = next(atom for atom in top_atoms if atom.atom_type == "meta")
    meta_children = read_heic_atom_spans(meta_atom.payload, 4, len(meta_atom.payload))
    iinf_atom = next(atom for atom in meta_children if atom.atom_type == "iinf")
    iref_atom = next(atom for atom in meta_children if atom.atom_type == "iref")
    iloc_atom = next(atom for atom in meta_children if atom.atom_type == "iloc")
    pitm_atom = next(atom for atom in meta_children if atom.atom_type == "pitm")
    item = primary_xmp_item(
        iinf_atom.payload,
        iref_atom.payload,
        iloc_atom.payload,
        primary_item_id=parse_pitm_item_id(pitm_atom.payload),
    )
    iloc = parse_iloc_payload(iloc_atom.payload)
    iloc_item = next(entry for entry in iloc.items if entry.item_id == item.item_id)
    return b"".join(
        data[
            iloc_item.base_offset + extent.extent_offset : iloc_item.base_offset
            + extent.extent_offset
            + extent.extent_length
        ]
        for extent in iloc_item.extents
    )
