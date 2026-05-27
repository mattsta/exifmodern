"""QuickTime generated-target setup materialization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.quicktime.atoms import (
    QuickTimeAtom,
    encode_quicktime_atoms,
    read_quicktime_atoms,
)
from exifmodern.formats.quicktime.del_group_delete import (
    QuickTimeDelGroupDeleteBlocker,
    delete_source_backed_broad_del_group_atoms,
)
from exifmodern.formats.quicktime.fanout_writer import (
    QuickTimeFanoutOffsetBlocker,
    broad_delete_offset_repair_message,
    collect_fanout_offset_blockers,
    dedupe_offset_blocker_codes,
    offset_repair_blockers,
    unsupported_broad_delete_offset_blockers,
)
from exifmodern.formats.quicktime.metadata_atoms import (
    QT_ITEM_LIST_ATOM,
    QT_ITEM_LIST_HANDLER,
    QT_META_ATOM,
    QT_MOVIE_ATOM,
    QT_USER_DATA_ATOM,
    encode_item_list_value_atom,
)
from exifmodern.formats.quicktime.metadata_writer import (
    child_atoms_or_empty,
    ensure_handler_atom,
    rewrite_quicktime_metadata,
    upsert_child_atoms,
)
from exifmodern.formats.quicktime.sample_chunk_offsets import (
    repair_sample_chunk_offsets_after_rewrite,
)
from exifmodern.formats.quicktime.setup_write_plan import (
    QuickTimeSetupMaterializationPlan,
    QuickTimeSetupSupplementalMetadataValue,
    QuickTimeSetupSupplementalXmpValue,
    QuickTimeSetupWriteStep,
)
from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
from exifmodern.formats.xmp.packet import empty_xmp_packet
from exifmodern.formats.xmp.property_write import (
    XMP_PROPERTY_TABLE_SOURCE,
    XMP_PROPERTY_WRITE_SOURCE,
    XmpPropertySpec,
    XmpPropertyWritePlan,
    XmpTextListPropertyWrite,
)

QT_MOV_XMP_ATOM = "XMP_"

type QuickTimeSetupMaterializationStatus = Literal["runnable", "blocked"]


@dataclass(frozen=True)
class QuickTimeSetupMaterializationResult:
    data: bytes
    changed_atoms: int
    applied_steps: tuple[str, ...]
    deferred: tuple[str, ...]
    offset_blocker_codes: tuple[str, ...] = ()
    offset_blockers: tuple[QuickTimeFanoutOffsetBlocker, ...] = ()
    del_group_deleted_paths: tuple[str, ...] = ()
    del_group_blockers: tuple[QuickTimeDelGroupDeleteBlocker, ...] = ()

    @property
    def status(self) -> QuickTimeSetupMaterializationStatus:
        if self.offset_blockers or self.del_group_blockers:
            return "blocked"
        return "runnable"

    @property
    def blocker_codes(self) -> tuple[str, ...]:
        codes = [*self.offset_blocker_codes]
        codes.extend(blocker.code for blocker in self.del_group_blockers)
        return tuple(dict.fromkeys(codes))


class QuickTimeSetupWriteUnsupportedError(ValueError):
    """Raised when a setup write step cannot be applied by the QuickTime atom writer."""


def materialize_quicktime_setup_data(
    source_data: bytes,
    plan: QuickTimeSetupMaterializationPlan,
    *,
    include_main_write: bool = True,
) -> QuickTimeSetupMaterializationResult:
    data = source_data
    changed_atoms = 0
    applied_steps: list[str] = []
    deferred: list[str] = []
    offset_blockers: list[QuickTimeFanoutOffsetBlocker] = []
    del_group_deleted_paths: list[str] = []
    del_group_blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    steps = plan.steps if include_main_write else plan.setup_steps
    for step in steps:
        require_supported_step(step)
        if not step.has_quicktime_atom_mutations:
            continue
        step_source_data = data
        broad_rewrite = apply_setup_broad_delete_primitives(data, step)
        if broad_rewrite.offset_blockers:
            deferred.extend(broad_rewrite.deferred)
            offset_blockers.extend(broad_rewrite.offset_blockers)
            return QuickTimeSetupMaterializationResult(
                data=data,
                changed_atoms=changed_atoms,
                applied_steps=tuple(applied_steps),
                deferred=tuple(deferred),
                offset_blocker_codes=dedupe_offset_blocker_codes(tuple(offset_blockers)),
                offset_blockers=tuple(offset_blockers),
                del_group_deleted_paths=tuple(del_group_deleted_paths),
                del_group_blockers=tuple(del_group_blockers),
            )
        data = broad_rewrite.data
        changed_atoms += broad_rewrite.changed_atoms
        deferred.extend(broad_rewrite.deferred)
        del_group_deleted_paths.extend(broad_rewrite.del_group_deleted_paths)
        del_group_blockers.extend(broad_rewrite.del_group_blockers)
        rewrite = rewrite_quicktime_metadata(data, step.metadata_plan)
        data = rewrite.data
        changed_atoms += rewrite.changed_atoms
        deferred.extend(rewrite.deferred)
        supplemental = rewrite_supplemental_item_list_values(data, step.supplemental_values)
        data = supplemental.data
        changed_atoms += supplemental.changed_atoms
        deferred.extend(supplemental.deferred)
        supplemental_xmp = rewrite_supplemental_mov_xmp_values(data, step.supplemental_xmp_values)
        data = supplemental_xmp.data
        changed_atoms += supplemental_xmp.changed_atoms
        deferred.extend(supplemental_xmp.deferred)
        if broad_rewrite.needs_sample_offset_repair:
            repair_result = repair_sample_chunk_offsets_after_rewrite(step_source_data, data)
            if repair_result.plan.blockers:
                repair_blockers = offset_repair_blockers(repair_result.plan.blockers)
                return QuickTimeSetupMaterializationResult(
                    data=step_source_data,
                    changed_atoms=0,
                    applied_steps=tuple(applied_steps),
                    deferred=(
                        *tuple(deferred),
                        broad_delete_offset_repair_message(repair_blockers),
                    ),
                    offset_blocker_codes=dedupe_offset_blocker_codes(repair_blockers),
                    offset_blockers=repair_blockers,
                    del_group_deleted_paths=tuple(del_group_deleted_paths),
                    del_group_blockers=tuple(del_group_blockers),
                )
            data = repair_result.data
            if repair_result.repaired_entry_count:
                changed_atoms += len(repair_result.plan.tables)
        deferred.extend(blocker.message for blocker in step.blockers)
        deferred.extend(blocker.message for blocker in broad_rewrite.del_group_blockers)
        applied_steps.append(step.action)
    return QuickTimeSetupMaterializationResult(
        data=data,
        changed_atoms=changed_atoms,
        applied_steps=tuple(applied_steps),
        deferred=tuple(deferred),
        offset_blocker_codes=dedupe_offset_blocker_codes(tuple(offset_blockers)),
        offset_blockers=tuple(offset_blockers),
        del_group_deleted_paths=tuple(del_group_deleted_paths),
        del_group_blockers=tuple(del_group_blockers),
    )


def require_supported_step(step: QuickTimeSetupWriteStep) -> None:
    if step.can_apply_quicktime_atoms:
        return
    blockers = ", ".join(blocker.code for blocker in step.blockers) or step.action
    raise QuickTimeSetupWriteUnsupportedError(
        f"QuickTime setup step is not supported by the package-local writer: {blockers}"
    )


@dataclass(frozen=True)
class QuickTimeSetupBroadDeleteRewrite:
    data: bytes
    changed_atoms: int
    deferred: tuple[str, ...]
    needs_sample_offset_repair: bool
    offset_blockers: tuple[QuickTimeFanoutOffsetBlocker, ...]
    del_group_deleted_paths: tuple[str, ...]
    del_group_blockers: tuple[QuickTimeDelGroupDeleteBlocker, ...]


def apply_setup_broad_delete_primitives(
    data: bytes,
    step: QuickTimeSetupWriteStep,
) -> QuickTimeSetupBroadDeleteRewrite:
    if not is_setup_broad_delete_step(step):
        return QuickTimeSetupBroadDeleteRewrite(
            data=data,
            changed_atoms=0,
            deferred=(),
            needs_sample_offset_repair=False,
            offset_blockers=(),
            del_group_deleted_paths=(),
            del_group_blockers=(),
        )
    offset_blockers = collect_fanout_offset_blockers(read_quicktime_atoms(data), ())
    unsupported_offset_blockers = unsupported_broad_delete_offset_blockers(offset_blockers)
    if unsupported_offset_blockers:
        return QuickTimeSetupBroadDeleteRewrite(
            data=data,
            changed_atoms=0,
            deferred=(
                *tuple(blocker.message for blocker in step.blockers),
                broad_delete_offset_repair_message(unsupported_offset_blockers),
            ),
            needs_sample_offset_repair=False,
            offset_blockers=unsupported_offset_blockers,
            del_group_deleted_paths=(),
            del_group_blockers=(),
        )
    del_group_result = delete_source_backed_broad_del_group_atoms(read_quicktime_atoms(data))
    return QuickTimeSetupBroadDeleteRewrite(
        data=encode_quicktime_atoms(del_group_result.atoms),
        changed_atoms=del_group_result.changed_atoms,
        deferred=(),
        needs_sample_offset_repair=bool(offset_blockers),
        offset_blockers=(),
        del_group_deleted_paths=del_group_result.deleted_paths,
        del_group_blockers=del_group_result.blockers,
    )


def is_setup_broad_delete_step(step: QuickTimeSetupWriteStep) -> bool:
    if step.action == "materialize_reusable_t7_setup_movie":
        return True
    return any(
        blocker.code == "broad_all_delete_requires_full_atom_tree_writer"
        for blocker in step.blockers
    )


def rewrite_supplemental_item_list_values(
    data: bytes,
    values: tuple[QuickTimeSetupSupplementalMetadataValue, ...],
) -> QuickTimeSetupMaterializationResult:
    if not values:
        return QuickTimeSetupMaterializationResult(
            data=data,
            changed_atoms=0,
            applied_steps=(),
            deferred=(),
        )
    atoms = read_quicktime_atoms(data)
    rewritten_atoms: list[QuickTimeAtom] = []
    changed_atoms = 0
    handled_movie = False
    for atom in atoms:
        if atom.atom_type != QT_MOVIE_ATOM:
            rewritten_atoms.append(atom)
            continue
        handled_movie = True
        movie_atoms = read_quicktime_atoms(atom.payload)
        rewritten_movie_atoms = rewrite_movie_supplemental_item_list_values(movie_atoms, values)
        rewritten_atoms.append(
            QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(rewritten_movie_atoms))
        )
        changed_atoms += 1 if rewritten_movie_atoms != movie_atoms else 0
    deferred = () if handled_movie else ("No moov atom found for supplemental ItemList writes.",)
    return QuickTimeSetupMaterializationResult(
        data=encode_quicktime_atoms(tuple(rewritten_atoms)),
        changed_atoms=changed_atoms,
        applied_steps=("apply_supplemental_itemlist_values",),
        deferred=deferred,
    )


def rewrite_movie_supplemental_item_list_values(
    atoms: tuple[QuickTimeAtom, ...],
    values: tuple[QuickTimeSetupSupplementalMetadataValue, ...],
) -> tuple[QuickTimeAtom, ...]:
    udta_atoms = child_atoms_or_empty(atoms, QT_USER_DATA_ATOM)
    meta_atoms = child_atoms_or_empty(udta_atoms, QT_META_ATOM)
    ilst_atoms = child_atoms_or_empty(meta_atoms, QT_ITEM_LIST_ATOM)
    rewritten_ilst_atoms = rewrite_supplemental_item_list_atoms(ilst_atoms, values)
    rewritten_meta_atoms = upsert_child_atoms(
        ensure_handler_atom(meta_atoms, QT_ITEM_LIST_HANDLER),
        QT_ITEM_LIST_ATOM,
        encode_quicktime_atoms(rewritten_ilst_atoms),
    )
    rewritten_udta_atoms = upsert_child_atoms(
        udta_atoms,
        QT_META_ATOM,
        encode_quicktime_atoms(rewritten_meta_atoms),
    )
    return upsert_child_atoms(
        atoms,
        QT_USER_DATA_ATOM,
        encode_quicktime_atoms(rewritten_udta_atoms),
    )


def rewrite_supplemental_item_list_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    values: tuple[QuickTimeSetupSupplementalMetadataValue, ...],
) -> tuple[QuickTimeAtom, ...]:
    rewritten = atoms
    for value in values:
        if value.value is None:
            rewritten = tuple(atom for atom in rewritten if atom.atom_type != value.atom_id)
            continue
        rewritten = upsert_supplemental_item_list_value(
            rewritten,
            value.atom_id,
            encode_item_list_value_atom(value.value),
        )
    return rewritten


def upsert_supplemental_item_list_value(
    atoms: tuple[QuickTimeAtom, ...],
    atom_id: str,
    payload: bytes,
) -> tuple[QuickTimeAtom, ...]:
    rewritten: list[QuickTimeAtom] = []
    handled = False
    for atom in atoms:
        if atom.atom_type != atom_id:
            rewritten.append(atom)
            continue
        rewritten.append(QuickTimeAtom(atom_id, payload))
        handled = True
    if not handled:
        rewritten.append(QuickTimeAtom(atom_id, payload))
    return tuple(rewritten)


def rewrite_supplemental_mov_xmp_values(
    data: bytes,
    values: tuple[QuickTimeSetupSupplementalXmpValue, ...],
) -> QuickTimeSetupMaterializationResult:
    if not values:
        return QuickTimeSetupMaterializationResult(
            data=data,
            changed_atoms=0,
            applied_steps=(),
            deferred=(),
        )
    atoms = read_quicktime_atoms(data)
    rewritten_atoms: list[QuickTimeAtom] = []
    changed_atoms = 0
    handled_movie = False
    for atom in atoms:
        if atom.atom_type != QT_MOVIE_ATOM:
            rewritten_atoms.append(atom)
            continue
        handled_movie = True
        movie_atoms = read_quicktime_atoms(atom.payload)
        rewritten_movie_atoms = rewrite_movie_supplemental_mov_xmp_values(movie_atoms, values)
        rewritten_atoms.append(
            QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(rewritten_movie_atoms))
        )
        changed_atoms += 1 if rewritten_movie_atoms != movie_atoms else 0
    deferred = () if handled_movie else ("No moov atom found for supplemental MOV XMP writes.",)
    return QuickTimeSetupMaterializationResult(
        data=encode_quicktime_atoms(tuple(rewritten_atoms)),
        changed_atoms=changed_atoms,
        applied_steps=("apply_supplemental_mov_xmp_values",),
        deferred=deferred,
    )


def rewrite_movie_supplemental_mov_xmp_values(
    atoms: tuple[QuickTimeAtom, ...],
    values: tuple[QuickTimeSetupSupplementalXmpValue, ...],
) -> tuple[QuickTimeAtom, ...]:
    udta_atoms = child_atoms_or_empty(atoms, QT_USER_DATA_ATOM)
    source_packet = first_mov_xmp_packet(udta_atoms) or empty_xmp_packet()
    packet = mutate_supplemental_xmp_packet(source_packet, values)
    rewritten_udta_atoms = upsert_child_atoms(udta_atoms, QT_MOV_XMP_ATOM, packet)
    return upsert_child_atoms(
        atoms,
        QT_USER_DATA_ATOM,
        encode_quicktime_atoms(rewritten_udta_atoms),
    )


def first_mov_xmp_packet(udta_atoms: tuple[QuickTimeAtom, ...]) -> bytes | None:
    for atom in udta_atoms:
        if atom.atom_type == QT_MOV_XMP_ATOM:
            return atom.payload
    return None


def mutate_supplemental_xmp_packet(
    packet: bytes,
    values: tuple[QuickTimeSetupSupplementalXmpValue, ...],
) -> bytes:
    plan = supplemental_xmp_property_write_plan(values)
    return apply_xmp_property_write_plan(packet, plan).packet


def supplemental_xmp_property_write_plan(
    values: tuple[QuickTimeSetupSupplementalXmpValue, ...],
) -> XmpPropertyWritePlan:
    publisher_values = tuple(value.value for value in values if value.value is not None)
    return XmpPropertyWritePlan(
        steps=(XmpTextListPropertyWrite("XMP-dc:Publisher", publisher_values),),
        evidence_ids=(XMP_PROPERTY_TABLE_SOURCE, XMP_PROPERTY_WRITE_SOURCE),
        generated_specs=(
            XmpPropertySpec(
                property_name="XMP-dc:Publisher",
                namespace_prefix="dc",
                namespace_uri="http://purl.org/dc/elements/1.1/",
                element_name="publisher",
                value_shape="bag_text",
                evidence_ids=(XMP_PROPERTY_TABLE_SOURCE,),
                rdf_container="Bag",
            ),
        ),
    )
