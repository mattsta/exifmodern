"""QuickTime fan-out runtime for source-backed metadata atom mutations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.file_transaction import FileWriteTransactionResult, write_bytes_transactionally
from exifmodern.formats.quicktime.atoms import (
    QuickTimeAtom,
    encode_quicktime_atoms,
    read_quicktime_atoms,
)
from exifmodern.formats.quicktime.del_group_delete import (
    QuickTimeDelGroupDeleteBlocker,
    QuickTimeDelGroupDeleteResult,
    delete_source_backed_broad_del_group_atoms,
)
from exifmodern.formats.quicktime.fanout_write_plan import (
    QUICKTIME_ITEMLIST_BINARY_FORMAT_SOURCE,
    QUICKTIME_OFFSET_REPAIR_SOURCE,
    QuickTimeFanoutBlocker,
    QuickTimeFanoutEvidenceAnchor,
    QuickTimeFanoutWritePlan,
    QuickTimeItemListBinaryAssignment,
    QuickTimeThreeGpAssignment,
    QuickTimeXmpAssignment,
    plan_quicktime_fanout_write_args,
)
from exifmodern.formats.quicktime.metadata_atoms import (
    QT_MOVIE_ATOM,
    QT_USER_DATA_ATOM,
    pack_quicktime_language_country,
)
from exifmodern.formats.quicktime.metadata_writer import (
    QuickTimeItemListBinaryValue,
    QuickTimeMetadataRewriteResult,
    child_atoms_or_empty,
    rewrite_quicktime_item_list_binary_values,
    rewrite_quicktime_metadata,
    upsert_child_atoms,
)
from exifmodern.formats.quicktime.microsoft_metadata import MicrosoftXtraAssignment
from exifmodern.formats.quicktime.rotation_writer import rewrite_quicktime_rotation
from exifmodern.formats.quicktime.sample_chunk_offsets import (
    QuickTimeSampleChunkOffsetBlocker,
    is_supported_sample_chunk_offset_path,
    repair_sample_chunk_offsets_after_rewrite,
)
from exifmodern.formats.quicktime.track_header_dates import (
    rewrite_quicktime_track_header_dates,
)
from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
from exifmodern.formats.xmp.packet import empty_xmp_packet
from exifmodern.formats.xmp.property_write import (
    XMP_PROPERTY_TABLE_SOURCE,
    XMP_PROPERTY_WRITE_SOURCE,
    XmpLocalizedTextPropertyWrite,
    XmpLocalizedTextValue,
    XmpPropertySpec,
    XmpPropertyValueShape,
    XmpPropertyWritePlan,
    XmpRdfContainer,
    XmpTextListPropertyWrite,
)

QT_FILE_TYPE_ATOM = "ftyp"
QT_MOV_XMP_ATOM = "XMP_"
QT_UUID_ATOM = "uuid"
QT_XMP_UUID = bytes.fromhex("be7acfcb97a942e89c71999491e3afac")
QUICKTIME_ITEM_LIST_BINARY_PROBE_SIZE = 18
QT_OFFSET_BLOCKER_BY_ATOM: dict[str, str] = {
    "stco": "requires_sample_chunk_offset_repair",
    "co64": "requires_sample_chunk_offset_repair",
    "iloc": "requires_item_location_offset_repair",
    "mfra": "unsupported_movie_fragment_offset_model",
    "moof": "unsupported_movie_fragment_offset_model",
    "sidx": "unsupported_segment_index_offset_model",
    "saio": "unsupported_sample_aux_offset_model",
    "gps ": "requires_gps_offset_repair",
    "CTBO": "requires_cr3_ctbo_offset_repair",
}
QT_OFFSET_SCAN_CONTAINER_ATOMS = frozenset(
    {
        "moov",
        "trak",
        "mdia",
        "minf",
        "stbl",
        "edts",
        "dinf",
        "udta",
        "meta",
        "ilst",
        "moof",
        "traf",
        "mfra",
        "iprp",
        "ipco",
    }
)


@dataclass(frozen=True)
class QuickTimeFanoutOffsetBlocker:
    atom_type: str
    full_path: str
    blocker_code: str
    source: QuickTimeFanoutEvidenceAnchor


@dataclass(frozen=True)
class QuickTimeFanoutRewriteResult:
    data: bytes
    changed_atoms: int
    applied_metadata: bool
    executed_surfaces: tuple[str, ...]
    blocked_surfaces: tuple[str, ...]
    deferred: tuple[str, ...]
    blockers: tuple[QuickTimeFanoutBlocker, ...]
    changed_track_headers: int = 0
    offset_blocker_codes: tuple[str, ...] = ()
    offset_blockers: tuple[QuickTimeFanoutOffsetBlocker, ...] = ()
    del_group_deleted_paths: tuple[str, ...] = ()
    del_group_blockers: tuple[QuickTimeDelGroupDeleteBlocker, ...] = ()
    transaction: FileWriteTransactionResult | None = None


@dataclass(frozen=True)
class QuickTimeResolvedItemListBinaryAssignments:
    values: tuple[QuickTimeItemListBinaryValue, ...]
    blockers: tuple[QuickTimeFanoutBlocker, ...]


@dataclass(frozen=True)
class MicrosoftXtraRecord:
    xtra_id: str
    payload: bytes
    raw_record: bytes


@dataclass(frozen=True)
class MicrosoftXtraRewrite:
    payload: bytes
    changed: bool
    malformed: bool = False


def rewrite_quicktime_fanout(
    data: bytes,
    plan: QuickTimeFanoutWritePlan,
) -> QuickTimeFanoutRewriteResult:
    binary_assignments = resolve_item_list_binary_assignments(plan.item_list_binary_assignments)
    if binary_assignments.blockers:
        return QuickTimeFanoutRewriteResult(
            data=data,
            changed_atoms=0,
            applied_metadata=False,
            executed_surfaces=(),
            blocked_surfaces=(*plan.blocked_surfaces, "ItemList-Binary"),
            deferred=(
                *tuple(blocker.message for blocker in plan.blockers),
                *tuple(blocker.message for blocker in binary_assignments.blockers),
            ),
            blockers=(*plan.blockers, *binary_assignments.blockers),
        )
    offset_blockers = broad_delete_offset_blockers(data, plan)
    unsupported_offset_blockers = unsupported_broad_delete_offset_blockers(offset_blockers)
    if unsupported_offset_blockers:
        offset_blocker_codes = dedupe_offset_blocker_codes(unsupported_offset_blockers)
        return QuickTimeFanoutRewriteResult(
            data=data,
            changed_atoms=0,
            applied_metadata=False,
            executed_surfaces=(),
            blocked_surfaces=plan.blocked_surfaces,
            deferred=(
                *tuple(blocker.message for blocker in plan.blockers),
                broad_delete_offset_repair_message(unsupported_offset_blockers),
            ),
            blockers=plan.blockers,
            offset_blocker_codes=offset_blocker_codes,
            offset_blockers=unsupported_offset_blockers,
        )
    del_group_result = rewrite_source_backed_broad_del_group_subset(data, plan)
    data_after_del_group = encode_quicktime_atoms(del_group_result.atoms)
    metadata_result = rewrite_safe_metadata_subset(data_after_del_group, plan)
    data_after_fanout = metadata_result.data
    changed_atoms = del_group_result.changed_atoms + metadata_result.changed_atoms
    changed_track_headers = 0
    if binary_assignments.values:
        binary_result = rewrite_quicktime_item_list_binary_values(
            data_after_fanout,
            binary_assignments.values,
            plan.metadata_plan.write_mode,
        )
        data_after_fanout = binary_result.data
        changed_atoms += binary_result.changed_atoms
    if plan.delete_xmp_atoms or plan.xmp_assignments:
        xmp_result = rewrite_quicktime_xmp_atoms(
            data_after_fanout,
            plan.xmp_assignments,
            delete_existing=plan.delete_xmp_atoms,
        )
        data_after_fanout = xmp_result.data
        changed_atoms += xmp_result.changed_atoms
    if plan.microsoft_assignments:
        microsoft_result = rewrite_microsoft_xtra(
            data_after_fanout,
            plan.microsoft_assignments,
            plan.metadata_plan.write_mode,
        )
        if microsoft_result.deferred:
            return QuickTimeFanoutRewriteResult(
                data=data,
                changed_atoms=0,
                applied_metadata=False,
                executed_surfaces=(),
                blocked_surfaces=(*plan.blocked_surfaces, "Microsoft"),
                deferred=(
                    *tuple(blocker.message for blocker in plan.blockers),
                    *microsoft_result.deferred,
                ),
                blockers=plan.blockers,
            )
        data_after_fanout = microsoft_result.data
        changed_atoms += microsoft_result.changed_atoms
    if plan.three_gp_assignments:
        three_gp_result = rewrite_three_gp_userdata(data_after_fanout, plan.three_gp_assignments)
        data_after_fanout = three_gp_result.data
        changed_atoms += three_gp_result.changed_atoms
    if plan.rotation_plan is not None:
        try:
            rotation_result = rewrite_quicktime_rotation(data_after_fanout, plan.rotation_plan)
        except ValueError as error:
            rotation_blocker = rotation_layout_blocker(str(error))
            return QuickTimeFanoutRewriteResult(
                data=data,
                changed_atoms=0,
                applied_metadata=False,
                executed_surfaces=(),
                blocked_surfaces=(*plan.blocked_surfaces, "Rotation"),
                deferred=(
                    *tuple(blocker.message for blocker in plan.blockers),
                    rotation_blocker.message,
                ),
                blockers=(*plan.blockers, rotation_blocker),
            )
        data_after_fanout = rotation_result.data
        changed_atoms += rotation_result.changed_track_headers
        changed_track_headers += rotation_result.changed_track_headers
    if plan.track_header_date_assignments:
        track_header_date_result = rewrite_quicktime_track_header_dates(
            data_after_fanout,
            plan.track_header_date_assignments,
        )
        if track_header_date_result.blockers:
            return QuickTimeFanoutRewriteResult(
                data=data,
                changed_atoms=0,
                applied_metadata=False,
                executed_surfaces=(),
                blocked_surfaces=plan.blocked_surfaces,
                deferred=(
                    *tuple(blocker.message for blocker in plan.blockers),
                    *tuple(blocker.message for blocker in track_header_date_result.blockers),
                ),
                blockers=plan.blockers,
            )
        data_after_fanout = track_header_date_result.data
        changed_atoms += track_header_date_result.changed_headers
        changed_track_headers += track_header_date_result.changed_track_headers
    if offset_blockers:
        repair_result = repair_sample_chunk_offsets_after_rewrite(data, data_after_fanout)
        if repair_result.plan.blockers:
            repair_blockers = offset_repair_blockers(repair_result.plan.blockers)
            return QuickTimeFanoutRewriteResult(
                data=data,
                changed_atoms=0,
                applied_metadata=False,
                executed_surfaces=(),
                blocked_surfaces=plan.blocked_surfaces,
                deferred=(
                    *tuple(blocker.message for blocker in plan.blockers),
                    broad_delete_offset_repair_message(repair_blockers),
                ),
                blockers=plan.blockers,
                offset_blocker_codes=dedupe_offset_blocker_codes(repair_blockers),
                offset_blockers=repair_blockers,
            )
        data_after_fanout = repair_result.data
        if repair_result.repaired_entry_count:
            changed_atoms += len(repair_result.plan.tables)
    return QuickTimeFanoutRewriteResult(
        data=data_after_fanout,
        changed_atoms=changed_atoms,
        applied_metadata=bool(
            plan.has_safe_metadata_mutations
            or plan.delete_xmp_atoms
            or plan.xmp_assignments
            or binary_assignments.values
            or plan.microsoft_assignments
            or plan.three_gp_assignments
            or plan.rotation_plan is not None
            or plan.track_header_date_assignments
            or del_group_result.deleted_paths
        ),
        executed_surfaces=plan.executable_surfaces,
        blocked_surfaces=plan.blocked_surfaces,
        deferred=(
            *metadata_result.deferred,
            *tuple(blocker.message for blocker in plan.blockers),
            *tuple(blocker.message for blocker in binary_assignments.blockers),
            *tuple(blocker.message for blocker in del_group_result.blockers),
        ),
        blockers=(*plan.blockers, *binary_assignments.blockers),
        changed_track_headers=changed_track_headers,
        offset_blocker_codes=(),
        del_group_deleted_paths=del_group_result.deleted_paths,
        del_group_blockers=del_group_result.blockers,
    )


def resolve_item_list_binary_assignments(
    assignments: tuple[QuickTimeItemListBinaryAssignment, ...],
) -> QuickTimeResolvedItemListBinaryAssignments:
    values: list[QuickTimeItemListBinaryValue] = []
    blockers: list[QuickTimeFanoutBlocker] = []
    for assignment in assignments:
        try:
            source_path = Path(assignment.path)
            with source_path.open("rb") as source_file:
                payload_probe = source_file.read(QUICKTIME_ITEM_LIST_BINARY_PROBE_SIZE)
                data_flags = quicktime_binary_item_list_data_flags(payload_probe)
                if data_flags is None:
                    blockers.append(item_list_binary_payload_blocker(assignment))
                    continue
                source_file.seek(0)
                payload = source_file.read()
        except OSError:
            blockers.append(item_list_binary_file_blocker(assignment))
            continue
        values.append(
            QuickTimeItemListBinaryValue(
                atom_type=assignment.atom_id,
                data_flags=data_flags,
                payload=payload,
            )
        )
    return QuickTimeResolvedItemListBinaryAssignments(
        values=tuple(values),
        blockers=tuple(blockers),
    )


def quicktime_binary_item_list_data_flags(payload: bytes) -> int | None:
    if payload.startswith(b"\xff\xd8\xff"):
        return 0x0D
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return 0x0E
    if payload.startswith(b"\x8aMNG\r\n\x1a\n"):
        return 0x0E
    if payload.startswith(b"\x8bJNG\r\n\x1a\n"):
        return 0x0E
    if len(payload) >= 17 and payload.startswith(b"BM") and payload[17:18] == b"\x00":
        return 0x1B
    return None


def item_list_binary_file_blocker(
    assignment: QuickTimeItemListBinaryAssignment,
) -> QuickTimeFanoutBlocker:
    return QuickTimeFanoutBlocker(
        code="unsupported_quicktime_write_argument",
        argument=f"ItemList:{assignment.name}<={assignment.path}",
        surface="ItemList-Binary",
        message=f"QuickTime ItemList binary payload file is unreadable: {assignment.path}",
        source=assignment.source,
    )


def item_list_binary_payload_blocker(
    assignment: QuickTimeItemListBinaryAssignment,
) -> QuickTimeFanoutBlocker:
    return QuickTimeFanoutBlocker(
        code="unsupported_quicktime_write_argument",
        argument=f"ItemList:{assignment.name}<={assignment.path}",
        surface="ItemList-Binary",
        message=(
            "QuickTime ItemList binary payload is not JPEG, PNG/MNG/JNG, or BMP, "
            "so this runtime will not guess ExifTool's UTF-8 fallback for a Binary tag."
        ),
        source=QUICKTIME_ITEMLIST_BINARY_FORMAT_SOURCE,
    )


def rotation_layout_blocker(message: str) -> QuickTimeFanoutBlocker:
    return QuickTimeFanoutBlocker(
        code="unsupported_quicktime_rotation_layout",
        argument="-Rotation",
        surface="Rotation",
        message=f"QuickTime Rotation was not emitted: {message}",
        source=QuickTimeFanoutEvidenceAnchor(
            path="lib/Image/ExifTool/QuickTime.pm",
            line_start=8821,
            line_end=8845,
            symbol="GetMatrixStructure",
            evidence=(
                "ExifTool only materializes Rotation through MatrixStructure when "
                "track matrix and image-size fields can be interpreted safely."
            ),
        ),
    )


def rewrite_quicktime_fanout_args(
    data: bytes,
    args: tuple[str, ...],
) -> QuickTimeFanoutRewriteResult:
    return rewrite_quicktime_fanout(data, plan_quicktime_fanout_write_args(args))


def rewrite_quicktime_file_fanout(
    input_path: Path,
    output_path: Path,
    plan: QuickTimeFanoutWritePlan,
) -> QuickTimeFanoutRewriteResult:
    result = rewrite_quicktime_fanout(input_path.read_bytes(), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return QuickTimeFanoutRewriteResult(
        data=result.data,
        changed_atoms=result.changed_atoms,
        applied_metadata=result.applied_metadata,
        executed_surfaces=result.executed_surfaces,
        blocked_surfaces=result.blocked_surfaces,
        deferred=result.deferred,
        blockers=result.blockers,
        changed_track_headers=result.changed_track_headers,
        offset_blocker_codes=result.offset_blocker_codes,
        offset_blockers=result.offset_blockers,
        del_group_deleted_paths=result.del_group_deleted_paths,
        del_group_blockers=result.del_group_blockers,
        transaction=transaction,
    )


def rewrite_source_backed_broad_del_group_subset(
    data: bytes,
    plan: QuickTimeFanoutWritePlan,
) -> QuickTimeDelGroupDeleteResult:
    if not has_broad_delete_blocker(plan):
        return QuickTimeDelGroupDeleteResult(
            atoms=read_quicktime_atoms(data),
            changed_atoms=0,
            deleted_paths=(),
            blockers=(),
        )
    return delete_source_backed_broad_del_group_atoms(read_quicktime_atoms(data))


def broad_delete_offset_blockers(
    data: bytes,
    plan: QuickTimeFanoutWritePlan,
) -> tuple[QuickTimeFanoutOffsetBlocker, ...]:
    if not has_broad_delete_blocker(plan):
        return ()
    return collect_fanout_offset_blockers(read_quicktime_atoms(data), ())


def has_broad_delete_blocker(plan: QuickTimeFanoutWritePlan) -> bool:
    return any(
        blocker.code == "broad_all_delete_requires_full_atom_tree_writer"
        for blocker in plan.blockers
    )


def broad_delete_offset_repair_message(
    offset_blockers: tuple[QuickTimeFanoutOffsetBlocker, ...],
) -> str:
    joined = ", ".join(f"{blocker.full_path}:{blocker.blocker_code}" for blocker in offset_blockers)
    return (
        "Broad QuickTime -all= was not emitted because this file contains offset-sensitive "
        "atoms requiring ExifTool-style offset repair before metadata size changes: "
        f"{joined}."
    )


def unsupported_broad_delete_offset_blockers(
    offset_blockers: tuple[QuickTimeFanoutOffsetBlocker, ...],
) -> tuple[QuickTimeFanoutOffsetBlocker, ...]:
    return tuple(
        blocker
        for blocker in offset_blockers
        if blocker.blocker_code != "requires_sample_chunk_offset_repair"
        or not is_supported_sample_chunk_offset_path(blocker.full_path)
    )


def offset_repair_blockers(
    blockers: tuple[QuickTimeSampleChunkOffsetBlocker, ...],
) -> tuple[QuickTimeFanoutOffsetBlocker, ...]:
    return tuple(
        QuickTimeFanoutOffsetBlocker(
            atom_type=blocker.full_path.rsplit("/", 1)[-1],
            full_path=blocker.full_path,
            blocker_code=blocker.code,
            source=QUICKTIME_OFFSET_REPAIR_SOURCE,
        )
        for blocker in blockers
    )


def dedupe_offset_blocker_codes(
    offset_blockers: tuple[QuickTimeFanoutOffsetBlocker, ...],
) -> tuple[str, ...]:
    codes: list[str] = []
    for blocker in offset_blockers:
        codes.append(blocker.blocker_code)
    return tuple(dict.fromkeys(codes))


def collect_fanout_offset_blockers(
    atoms: tuple[QuickTimeAtom, ...],
    parent_path: tuple[str, ...],
) -> tuple[QuickTimeFanoutOffsetBlocker, ...]:
    blockers: list[QuickTimeFanoutOffsetBlocker] = []
    for atom in atoms:
        path = (*parent_path, atom.atom_type)
        blocker_code = QT_OFFSET_BLOCKER_BY_ATOM.get(atom.atom_type)
        if blocker_code is not None:
            blockers.append(
                QuickTimeFanoutOffsetBlocker(
                    atom_type=atom.atom_type,
                    full_path="/".join(path),
                    blocker_code=blocker_code,
                    source=QUICKTIME_OFFSET_REPAIR_SOURCE,
                )
            )
        if atom.atom_type in QT_OFFSET_SCAN_CONTAINER_ATOMS:
            blockers.extend(collect_fanout_offset_blockers(child_atoms_for_offset_scan(atom), path))
    return tuple(blockers)


def child_atoms_for_offset_scan(atom: QuickTimeAtom) -> tuple[QuickTimeAtom, ...]:
    if not atom.payload:
        return ()
    if atom.atom_type == "meta" and len(atom.payload) >= 4:
        try:
            return read_quicktime_atoms(atom.payload[4:])
        except ValueError:
            pass
    try:
        return read_quicktime_atoms(atom.payload)
    except ValueError:
        return ()


def rewrite_safe_metadata_subset(
    data: bytes,
    plan: QuickTimeFanoutWritePlan,
) -> QuickTimeMetadataRewriteResult:
    if not plan.has_safe_metadata_mutations:
        return QuickTimeMetadataRewriteResult(data=data, changed_atoms=0)
    return rewrite_quicktime_metadata(data, plan.metadata_plan)


def rewrite_microsoft_xtra(
    data: bytes,
    assignments: tuple[MicrosoftXtraAssignment, ...],
    write_mode: str = "overwrite",
) -> QuickTimeMetadataRewriteResult:
    return rewrite_movie_user_data_xtra_payload(data, assignments, write_mode)


def rewrite_movie_user_data_xtra_payload(
    data: bytes,
    assignments: tuple[MicrosoftXtraAssignment, ...],
    write_mode: str,
) -> QuickTimeMetadataRewriteResult:
    atoms = read_quicktime_atoms(data)
    rewritten_atoms: list[QuickTimeAtom] = []
    changed_atoms = 0
    deferred: list[str] = []
    for atom in atoms:
        if atom.atom_type != QT_MOVIE_ATOM:
            rewritten_atoms.append(atom)
            continue
        movie_atoms = read_quicktime_atoms(atom.payload)
        udta_atoms = child_atoms_or_empty(movie_atoms, QT_USER_DATA_ATOM)
        rewrite = rewrite_xtra_user_data_atoms(udta_atoms, assignments, write_mode)
        if rewrite.malformed:
            deferred.append(
                "Microsoft Xtra atom was not written: existing Xtra payload is malformed."
            )
            rewritten_atoms.append(atom)
            continue
        rewritten_movie_atoms = upsert_child_atoms(
            movie_atoms,
            QT_USER_DATA_ATOM,
            encode_quicktime_atoms(rewrite.payload_atoms),
        )
        rewritten_atoms.append(
            QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(rewritten_movie_atoms))
        )
        changed_atoms += 1 if rewrite.changed and rewritten_movie_atoms != movie_atoms else 0
    return QuickTimeMetadataRewriteResult(
        data=encode_quicktime_atoms(tuple(rewritten_atoms)),
        changed_atoms=changed_atoms,
        deferred=tuple(deferred),
    )


@dataclass(frozen=True)
class MicrosoftXtraUserDataRewrite:
    payload_atoms: tuple[QuickTimeAtom, ...]
    changed: bool
    malformed: bool = False


def rewrite_xtra_user_data_atoms(
    udta_atoms: tuple[QuickTimeAtom, ...],
    assignments: tuple[MicrosoftXtraAssignment, ...],
    write_mode: str,
) -> MicrosoftXtraUserDataRewrite:
    xtra_atom = first_child_atom(udta_atoms, "Xtra")
    source_payload = xtra_atom.payload if xtra_atom is not None else b""
    rewrite = rewrite_xtra_payload(source_payload, assignments, write_mode)
    if rewrite.malformed:
        return MicrosoftXtraUserDataRewrite(udta_atoms, changed=False, malformed=True)
    rewritten_udta_atoms = upsert_child_atoms(udta_atoms, "Xtra", rewrite.payload)
    return MicrosoftXtraUserDataRewrite(
        payload_atoms=rewritten_udta_atoms,
        changed=rewrite.changed or xtra_atom is None,
    )


def first_child_atom(atoms: tuple[QuickTimeAtom, ...], atom_type: str) -> QuickTimeAtom | None:
    for atom in atoms:
        if atom.atom_type == atom_type:
            return atom
    return None


def rewrite_xtra_payload(
    payload: bytes,
    assignments: tuple[MicrosoftXtraAssignment, ...],
    write_mode: str,
) -> MicrosoftXtraRewrite:
    parsed = parse_xtra_records(payload)
    if parsed is None:
        return MicrosoftXtraRewrite(payload=payload, changed=False, malformed=True)
    records = list(parsed)
    existing_ids = {record.xtra_id for record in records}
    assignment_by_id = {assignment.xtra_id: assignment for assignment in assignments}
    rewritten_records: list[bytes] = []
    changed = False
    for record in records:
        assignment = assignment_by_id.get(record.xtra_id)
        if assignment is None or write_mode == "create":
            rewritten_records.append(record.raw_record)
            continue
        rewritten = encode_xtra_record(assignment)
        rewritten_records.append(rewritten)
        changed = changed or rewritten != record.raw_record
    for assignment in sorted(assignments, key=lambda item: item.xtra_id):
        if assignment.xtra_id in existing_ids:
            continue
        rewritten_records.append(encode_xtra_record(assignment))
        changed = True
    new_payload = b"".join(rewritten_records)
    return MicrosoftXtraRewrite(payload=new_payload, changed=changed)


def parse_xtra_records(payload: bytes) -> tuple[MicrosoftXtraRecord, ...] | None:
    records: list[MicrosoftXtraRecord] = []
    pos = 0
    while pos < len(payload):
        if pos + 8 > len(payload):
            return None
        size = int.from_bytes(payload[pos : pos + 4], "big")
        if size < 8 or pos + size > len(payload):
            return None
        tag_len = int.from_bytes(payload[pos + 4 : pos + 8], "big")
        if tag_len + 18 > size:
            return None
        tag_start = pos + 8
        tag_end = tag_start + tag_len
        try:
            xtra_id = payload[tag_start:tag_end].decode("utf-8")
        except UnicodeDecodeError:
            return None
        value_payload = payload[tag_end : pos + size]
        if not xtra_value_payload_is_well_formed(value_payload):
            return None
        records.append(
            MicrosoftXtraRecord(
                xtra_id=xtra_id,
                payload=value_payload,
                raw_record=payload[pos : pos + size],
            )
        )
        pos += size
    return tuple(records)


def xtra_value_payload_is_well_formed(payload: bytes) -> bool:
    if len(payload) < 4:
        return False
    count = int.from_bytes(payload[0:4], "big")
    pos = 4
    for _ in range(count):
        if pos + 6 > len(payload):
            return False
        value_size = int.from_bytes(payload[pos : pos + 4], "big")
        if value_size < 6 or pos + value_size > len(payload):
            return False
        pos += value_size
    return pos == len(payload)


def rewrite_quicktime_xmp_atoms(
    data: bytes,
    assignments: tuple[QuickTimeXmpAssignment, ...],
    *,
    delete_existing: bool,
) -> QuickTimeMetadataRewriteResult:
    atoms = read_quicktime_atoms(data)
    if quicktime_xmp_storage(atoms) == "mp4_uuid":
        rewritten_atoms = rewrite_top_level_xmp_uuid_atoms(atoms, assignments, delete_existing)
    else:
        rewritten_atoms = rewrite_mov_xmp_atoms(atoms, assignments, delete_existing)
    return QuickTimeMetadataRewriteResult(
        data=encode_quicktime_atoms(rewritten_atoms),
        changed_atoms=1 if rewritten_atoms != atoms else 0,
    )


def rewrite_quicktime_xmp_properties(
    data: bytes,
    xmp_plan: XmpPropertyWritePlan,
) -> QuickTimeMetadataRewriteResult:
    atoms = read_quicktime_atoms(data)
    if quicktime_xmp_storage(atoms) == "mp4_uuid":
        rewritten_atoms = rewrite_top_level_xmp_uuid_properties(atoms, xmp_plan)
    else:
        rewritten_atoms = rewrite_mov_xmp_properties(atoms, xmp_plan)
    return QuickTimeMetadataRewriteResult(
        data=encode_quicktime_atoms(rewritten_atoms),
        changed_atoms=1 if rewritten_atoms != atoms else 0,
    )


def rewrite_top_level_xmp_uuid_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    assignments: tuple[QuickTimeXmpAssignment, ...],
    delete_existing: bool,
) -> tuple[QuickTimeAtom, ...]:
    source_packet = first_top_level_xmp_packet(atoms)
    rewritten = (
        tuple(atom for atom in atoms if not is_xmp_uuid_atom(atom))
        if delete_existing or assignments
        else atoms
    )
    if not assignments:
        return rewritten
    packet = mutate_xmp_packet(source_packet or empty_xmp_packet(), assignments)
    return (*rewritten, QuickTimeAtom(QT_UUID_ATOM, QT_XMP_UUID + packet))


def rewrite_top_level_xmp_uuid_properties(
    atoms: tuple[QuickTimeAtom, ...],
    xmp_plan: XmpPropertyWritePlan,
) -> tuple[QuickTimeAtom, ...]:
    source_packet = first_top_level_xmp_packet(atoms) or empty_xmp_packet()
    packet = apply_xmp_property_write_plan(source_packet, xmp_plan).packet
    retained = tuple(atom for atom in atoms if not is_xmp_uuid_atom(atom))
    return (*retained, QuickTimeAtom(QT_UUID_ATOM, QT_XMP_UUID + packet))


def rewrite_mov_xmp_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    assignments: tuple[QuickTimeXmpAssignment, ...],
    delete_existing: bool,
) -> tuple[QuickTimeAtom, ...]:
    rewritten_atoms: list[QuickTimeAtom] = []
    for atom in atoms:
        if atom.atom_type != QT_MOVIE_ATOM:
            rewritten_atoms.append(atom)
            continue
        movie_atoms = read_quicktime_atoms(atom.payload)
        udta_atoms = child_atoms_or_empty(movie_atoms, QT_USER_DATA_ATOM)
        source_packet = first_mov_xmp_packet(udta_atoms)
        rewritten_udta_atoms = (
            tuple(child for child in udta_atoms if child.atom_type != QT_MOV_XMP_ATOM)
            if delete_existing
            else udta_atoms
        )
        if assignments:
            packet = mutate_xmp_packet(source_packet or empty_xmp_packet(), assignments)
            rewritten_udta_atoms = upsert_child_atoms(
                rewritten_udta_atoms,
                QT_MOV_XMP_ATOM,
                packet,
            )
        rewritten_movie_atoms = upsert_child_atoms(
            movie_atoms,
            QT_USER_DATA_ATOM,
            encode_quicktime_atoms(rewritten_udta_atoms),
        )
        rewritten_atoms.append(
            QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(rewritten_movie_atoms))
        )
    return tuple(rewritten_atoms)


def rewrite_mov_xmp_properties(
    atoms: tuple[QuickTimeAtom, ...],
    xmp_plan: XmpPropertyWritePlan,
) -> tuple[QuickTimeAtom, ...]:
    rewritten_atoms: list[QuickTimeAtom] = []
    handled_movie = False
    for atom in atoms:
        if atom.atom_type != QT_MOVIE_ATOM:
            rewritten_atoms.append(atom)
            continue
        handled_movie = True
        movie_atoms = read_quicktime_atoms(atom.payload)
        udta_atoms = child_atoms_or_empty(movie_atoms, QT_USER_DATA_ATOM)
        source_packet = first_mov_xmp_packet(udta_atoms) or empty_xmp_packet()
        packet = apply_xmp_property_write_plan(source_packet, xmp_plan).packet
        rewritten_udta_atoms = upsert_child_atoms(udta_atoms, QT_MOV_XMP_ATOM, packet)
        rewritten_movie_atoms = upsert_child_atoms(
            movie_atoms,
            QT_USER_DATA_ATOM,
            encode_quicktime_atoms(rewritten_udta_atoms),
        )
        rewritten_atoms.append(
            QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(rewritten_movie_atoms))
        )
    if not handled_movie:
        raise ValueError("No moov atom found for MOV QuickTime XMP writes.")
    return tuple(rewritten_atoms)


def quicktime_xmp_storage(atoms: tuple[QuickTimeAtom, ...]) -> str:
    for atom in atoms:
        if atom.atom_type != QT_FILE_TYPE_ATOM:
            continue
        if len(atom.payload) < 8:
            return "mov_userdata"
        major_brand = atom.payload[0:4]
        compatible_brands = atom.payload[8:]
        if major_brand == b"qt  " or b"qt  " in brand_chunks(compatible_brands):
            return "mov_userdata"
        return "mp4_uuid"
    return "mov_userdata"


def brand_chunks(payload: bytes) -> tuple[bytes, ...]:
    return tuple(payload[index : index + 4] for index in range(0, len(payload) - 3, 4))


def first_top_level_xmp_packet(atoms: tuple[QuickTimeAtom, ...]) -> bytes | None:
    for atom in atoms:
        if is_xmp_uuid_atom(atom):
            return atom.payload[len(QT_XMP_UUID) :]
    return None


def first_mov_xmp_packet(udta_atoms: tuple[QuickTimeAtom, ...]) -> bytes | None:
    for atom in udta_atoms:
        if atom.atom_type == QT_MOV_XMP_ATOM:
            return atom.payload
    return None


def is_xmp_uuid_atom(atom: QuickTimeAtom) -> bool:
    return atom.atom_type == QT_UUID_ATOM and atom.payload.startswith(QT_XMP_UUID)


def mutate_xmp_packet(
    packet: bytes,
    assignments: tuple[QuickTimeXmpAssignment, ...],
) -> bytes:
    plan = xmp_plan_for_quicktime_assignments(assignments)
    return apply_xmp_property_write_plan(packet, plan).packet


def xmp_plan_for_quicktime_assignments(
    assignments: tuple[QuickTimeXmpAssignment, ...],
) -> XmpPropertyWritePlan:
    creator_values = tuple(
        assignment.value
        for assignment in assignments
        if assignment.property_name == "XMP-dc:Creator"
    )
    publisher_values = tuple(
        assignment.value
        for assignment in assignments
        if assignment.property_name == "XMP-dc:Publisher"
    )
    title_values = tuple(
        XmpLocalizedTextValue("x-default", assignment.value)
        for assignment in assignments
        if assignment.property_name == "XMP-dc:Title"
    )
    steps: list[XmpTextListPropertyWrite | XmpLocalizedTextPropertyWrite] = []
    specs: list[XmpPropertySpec] = []
    if creator_values:
        steps.append(XmpTextListPropertyWrite("XMP-dc:Creator", creator_values))
        specs.append(dc_xmp_spec("XMP-dc:Creator", "creator", "seq_text", "Seq"))
    if publisher_values:
        steps.append(XmpTextListPropertyWrite("XMP-dc:Publisher", publisher_values))
        specs.append(dc_xmp_spec("XMP-dc:Publisher", "publisher", "bag_text", "Bag"))
    if title_values:
        steps.append(XmpLocalizedTextPropertyWrite("XMP-dc:Title", title_values))
        specs.append(dc_xmp_spec("XMP-dc:Title", "title", "alt_text", "Alt"))
    return XmpPropertyWritePlan(
        steps=tuple(steps),
        evidence_ids=(XMP_PROPERTY_TABLE_SOURCE, XMP_PROPERTY_WRITE_SOURCE),
        generated_specs=tuple(specs),
    )


def dc_xmp_spec(
    property_name: str,
    element_name: str,
    value_shape: XmpPropertyValueShape,
    rdf_container: XmpRdfContainer,
) -> XmpPropertySpec:
    return XmpPropertySpec(
        property_name=property_name,
        namespace_prefix="dc",
        namespace_uri="http://purl.org/dc/elements/1.1/",
        element_name=element_name,
        value_shape=value_shape,
        evidence_ids=(XMP_PROPERTY_TABLE_SOURCE,),
        rdf_container=rdf_container,
    )


def rewrite_three_gp_userdata(
    data: bytes,
    assignments: tuple[QuickTimeThreeGpAssignment, ...],
) -> QuickTimeMetadataRewriteResult:
    result = QuickTimeMetadataRewriteResult(data=data, changed_atoms=0)
    for assignment in assignments:
        result = rewrite_movie_user_data_payload(
            result.data,
            assignment.atom_id,
            encode_three_gp_payload(assignment),
        )
    return result


def rewrite_movie_user_data_payload(
    data: bytes,
    atom_type: str,
    payload: bytes,
) -> QuickTimeMetadataRewriteResult:
    atoms = read_quicktime_atoms(data)
    rewritten_atoms: list[QuickTimeAtom] = []
    changed_atoms = 0
    for atom in atoms:
        if atom.atom_type != QT_MOVIE_ATOM:
            rewritten_atoms.append(atom)
            continue
        movie_atoms = read_quicktime_atoms(atom.payload)
        udta_atoms = child_atoms_or_empty(movie_atoms, QT_USER_DATA_ATOM)
        rewritten_udta_atoms = upsert_child_atoms(udta_atoms, atom_type, payload)
        rewritten_movie_atoms = upsert_child_atoms(
            movie_atoms,
            QT_USER_DATA_ATOM,
            encode_quicktime_atoms(rewritten_udta_atoms),
        )
        rewritten_atoms.append(
            QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(rewritten_movie_atoms))
        )
        changed_atoms += 1 if rewritten_movie_atoms != movie_atoms else 0
    return QuickTimeMetadataRewriteResult(
        data=encode_quicktime_atoms(tuple(rewritten_atoms)),
        changed_atoms=changed_atoms,
    )


def encode_xtra_payload(assignments: tuple[MicrosoftXtraAssignment, ...]) -> bytes:
    return b"".join(
        encode_xtra_record(assignment)
        for assignment in sorted(assignments, key=lambda item: item.xtra_id)
    )


def encode_xtra_record(assignment: MicrosoftXtraAssignment) -> bytes:
    tag = assignment.xtra_id.encode("utf-8")
    value_payload = encode_xtra_values(assignment)
    size = 8 + len(tag) + len(value_payload)
    return size.to_bytes(4, "big") + len(tag).to_bytes(4, "big") + tag + value_payload


def encode_xtra_values(assignment: MicrosoftXtraAssignment) -> bytes:
    values = b"".join(encode_xtra_value(assignment, value) for value in assignment.values)
    return len(assignment.values).to_bytes(4, "big") + values


def encode_xtra_value(assignment: MicrosoftXtraAssignment, value: str) -> bytes:
    if assignment.writable_format == "Unicode":
        encoded_value = value.encode("utf-16le") + b"\x00\x00"
        value_type = 8
    else:
        encoded_value = int(value).to_bytes(8, "little")
        value_type = 19
    return (
        (len(encoded_value) + 6).to_bytes(4, "big") + value_type.to_bytes(2, "big") + encoded_value
    )


def encode_three_gp_payload(assignment: QuickTimeThreeGpAssignment) -> bytes:
    if assignment.atom_id in {"albm", "auth", "coll", "cprt", "dscp", "gnre", "perf", "titl"}:
        return encode_three_gp_language_text(assignment.value, assignment.language_code)
    if assignment.atom_id == "rtng":
        return encode_three_gp_rating(assignment.value, assignment.language_code)
    if assignment.atom_id == "clsf":
        return encode_three_gp_classification(assignment.value, assignment.language_code)
    if assignment.atom_id == "loci":
        return encode_three_gp_location(assignment.value, assignment.language_code)
    if assignment.atom_id == "yrrc":
        return b"\x00\x00\x00\x00" + int(assignment.value).to_bytes(2, "big")
    if assignment.atom_id == "urat":
        return b"\x00\x00\x00\x00" + int(assignment.value).to_bytes(4, "big")
    raise ValueError(f"Unsupported 3GP UserData atom: {assignment.atom_id!r}.")


def encode_three_gp_language_text(value: str, language_code: str | None) -> bytes:
    country, language = pack_quicktime_language_country(language_code)
    if country:
        raise ValueError("3GP UserData international text atoms do not support country codes.")
    return b"\x00\x00\x00\x00" + language.to_bytes(2, "big") + value.encode("utf-8") + b"\x00"


def encode_three_gp_rating(value: str, language_code: str | None) -> bytes:
    converted = value
    lower = converted.lower()
    if lower.startswith("entity="):
        parts = converted.split(" ", 2)
        if len(parts) >= 2 and parts[1].lower().startswith("criteria="):
            entity = parts[0].split("=", 1)[1]
            criteria = parts[1].split("=", 1)[1]
            rest = parts[2] if len(parts) == 3 else ""
            converted = entity + criteria + rest
    prefix_length = 8
    if len(converted) < prefix_length:
        raise ValueError(f"Expected 3GP Rating entity and criteria in {value!r}.")
    prefix = converted[:prefix_length]
    text = converted[prefix_length:].lstrip()
    return encode_three_gp_language_text_with_prefix(prefix.encode("utf-8"), text, language_code)


def encode_three_gp_classification(value: str, language_code: str | None) -> bytes:
    converted = value
    lower = converted.lower()
    if lower.startswith("entity="):
        parts = converted.split(" ", 2)
        if len(parts) >= 2 and parts[1].lower().startswith("index="):
            entity = parts[0].split("=", 1)[1]
            index = int(parts[1].split("=", 1)[1])
            rest = parts[2] if len(parts) == 3 else ""
            converted = entity + index.to_bytes(2, "big").decode("latin-1") + rest
    prefix_length = 6
    if len(converted) < prefix_length:
        raise ValueError(f"Expected 3GP Classification entity and index in {value!r}.")
    prefix = converted[:prefix_length].encode("latin-1")
    text = converted[prefix_length:].lstrip()
    return encode_three_gp_language_text_with_prefix(prefix, text, language_code)


def encode_three_gp_language_text_with_prefix(
    prefix: bytes,
    text: str,
    language_code: str | None,
) -> bytes:
    country, language = pack_quicktime_language_country(language_code)
    if country:
        raise ValueError("3GP UserData international text atoms do not support country codes.")
    return (
        b"\x00\x00\x00\x00" + prefix + language.to_bytes(2, "big") + text.encode("utf-8") + b"\x00"
    )


def encode_three_gp_location(value: str, language_code: str | None) -> bytes:
    remaining = value
    lat, remaining = pop_named_float(remaining, "Lat")
    lon, remaining = pop_named_float(remaining, "Lon")
    alt, remaining = pop_named_float(remaining, "Alt")
    notes, remaining = pop_named_text(remaining, "Notes")
    body, remaining = pop_named_text(remaining, "Body")
    role_text, remaining = pop_named_text(remaining, "Role")
    location_name = "" if remaining == "(none)" else remaining.strip()
    role = {"shooting": 0, "real": 1, "fictional": 2}.get(role_text.lower(), 0)
    location_payload = (
        location_name.encode("utf-8")
        + b"\x00"
        + role.to_bytes(1, "big")
        + encode_fixed32(lon if lon is not None else 999)
        + encode_fixed32(lat if lat is not None else 999)
        + encode_fixed32(alt if alt is not None else 0)
        + body.encode("utf-8")
        + b"\x00"
        + notes.encode("utf-8")
        + b"\x00"
    )
    return encode_three_gp_language_text_with_raw_payload(location_payload, language_code)


def encode_three_gp_language_text_with_raw_payload(
    payload: bytes,
    language_code: str | None,
) -> bytes:
    country, language = pack_quicktime_language_country(language_code)
    if country:
        raise ValueError("3GP UserData international text atoms do not support country codes.")
    return b"\x00\x00\x00\x00" + language.to_bytes(2, "big") + payload + b"\x00"


def pop_named_float(value: str, name: str) -> tuple[float | None, str]:
    marker = f" {name}="
    lower_value = value.lower()
    start = lower_value.find(marker.lower())
    if start < 0:
        return None, value
    value_start = start + len(marker)
    value_end = value.find(" ", value_start)
    if value_end < 0:
        value_end = len(value)
    return float(value[value_start:value_end]), value[:start] + value[value_end:]


def pop_named_text(value: str, name: str) -> tuple[str, str]:
    marker = f" {name}="
    lower_value = value.lower()
    start = lower_value.find(marker.lower())
    if start < 0:
        return "", value
    value_start = start + len(marker)
    next_start = len(value)
    for candidate in (" Role=", " Lat=", " Lon=", " Alt=", " Body=", " Notes="):
        found = lower_value.find(candidate.lower(), value_start)
        if found >= 0:
            next_start = min(next_start, found)
    return value[value_start:next_start], value[:start] + value[next_start:]


def encode_fixed32(value: float) -> bytes:
    scaled = int(value * 65536)
    return scaled.to_bytes(4, "big", signed=True)
