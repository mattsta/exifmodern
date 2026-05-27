"""Constrained QuickTime ItemList/UserData/Keys metadata writer foundation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.file_transaction import FileWriteTransactionResult, write_bytes_transactionally
from exifmodern.formats.quicktime.atoms import (
    QuickTimeAtom,
    encode_quicktime_atom,
    encode_quicktime_atoms,
    read_quicktime_atoms,
)
from exifmodern.formats.quicktime.metadata_atoms import (
    ITEM_LIST_TAGS,
    QT_DATA_ATOM,
    QT_DEFAULT_COUNTRY,
    QT_DEFAULT_LANGUAGE,
    QT_HANDLER_ATOM,
    QT_ITEM_LIST_ATOM,
    QT_KEYS_ATOM,
    QT_META_ATOM,
    QT_METADATA_HANDLER,
    QT_MOVIE_ATOM,
    QT_TRACK_ATOM,
    QT_USER_DATA_ATOM,
    USER_DATA_TAGS,
    QuickTimeDataAtom,
    QuickTimeItemListValueFormat,
    QuickTimeMetadataGroup,
    QuickTimeMetadataTag,
    QuickTimeMetadataValue,
    QuickTimeMetadataWriteMode,
    QuickTimeMetadataWritePlan,
    atom_type_from_key_index,
    data_atom_matches_language,
    encode_handler_atom,
    encode_item_list_value_atom,
    encode_item_list_value_bytes,
    encode_keys_payload,
    encode_user_data_text_value,
    key_index_from_atom_type,
    pack_quicktime_language_country,
    parse_item_list_data_atoms,
    parse_keys_payload,
    quicktime_metadata_tag,
)
from exifmodern.formats.quicktime.rotation_writer import quicktime_track_handler_type


@dataclass(frozen=True)
class QuickTimeMetadataRewriteResult:
    data: bytes
    changed_atoms: int
    deferred: tuple[str, ...] = ()
    transaction: FileWriteTransactionResult | None = None


@dataclass(frozen=True)
class QuickTimeMetadataContainerRewrite:
    atoms: tuple[QuickTimeAtom, ...]
    changed_atoms: int
    deferred: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuickTimeKeysRewrite:
    meta_atoms: tuple[QuickTimeAtom, ...]
    changed_atoms: int


@dataclass(frozen=True)
class QuickTimeItemListBinaryValue:
    atom_type: str
    data_flags: int
    payload: bytes


def rewrite_quicktime_metadata(
    data: bytes,
    plan: QuickTimeMetadataWritePlan,
) -> QuickTimeMetadataRewriteResult:
    atoms = read_quicktime_atoms(data)
    rewritten_atoms: list[QuickTimeAtom] = []
    changed_atoms = 0
    deferred: list[str] = []
    handled_movie = False
    for atom in atoms:
        if atom.atom_type != QT_MOVIE_ATOM:
            rewritten_atoms.append(atom)
            continue
        handled_movie = True
        rewrite = rewrite_movie_metadata_atoms(read_quicktime_atoms(atom.payload), plan)
        rewritten_payload = encode_quicktime_atoms(rewrite.atoms)
        rewritten_atoms.append(QuickTimeAtom(atom.atom_type, rewritten_payload))
        changed_atoms += rewrite.changed_atoms
        deferred.extend(rewrite.deferred)
    if not handled_movie:
        deferred.append("No moov atom found; QuickTime metadata locations are unavailable.")
    return QuickTimeMetadataRewriteResult(
        data=encode_quicktime_atoms(tuple(rewritten_atoms)),
        changed_atoms=changed_atoms,
        deferred=tuple(deferred),
    )


def rewrite_quicktime_item_list_binary_values(
    data: bytes,
    values: tuple[QuickTimeItemListBinaryValue, ...],
    write_mode: QuickTimeMetadataWriteMode = "overwrite",
) -> QuickTimeMetadataRewriteResult:
    atoms = read_quicktime_atoms(data)
    rewritten_atoms: list[QuickTimeAtom] = []
    changed_atoms = 0
    deferred: list[str] = []
    handled_movie = False
    for atom in atoms:
        if atom.atom_type != QT_MOVIE_ATOM:
            rewritten_atoms.append(atom)
            continue
        handled_movie = True
        rewrite = rewrite_movie_item_list_binary_atoms(
            read_quicktime_atoms(atom.payload),
            values,
            write_mode,
        )
        rewritten_atoms.append(QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(rewrite.atoms)))
        changed_atoms += rewrite.changed_atoms
    if not handled_movie:
        deferred.append("No moov atom found; QuickTime ItemList binary locations are unavailable.")
    return QuickTimeMetadataRewriteResult(
        data=encode_quicktime_atoms(tuple(rewritten_atoms)),
        changed_atoms=changed_atoms,
        deferred=tuple(deferred),
    )


def rewrite_quicktime_file_metadata(
    input_path: Path,
    output_path: Path,
    plan: QuickTimeMetadataWritePlan,
) -> QuickTimeMetadataRewriteResult:
    result = rewrite_quicktime_metadata(input_path.read_bytes(), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return QuickTimeMetadataRewriteResult(
        data=result.data,
        changed_atoms=result.changed_atoms,
        deferred=result.deferred,
        transaction=transaction,
    )


def rewrite_movie_metadata_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    plan: QuickTimeMetadataWritePlan,
) -> QuickTimeMetadataContainerRewrite:
    movie_atoms = atoms
    changed_atoms = 0
    deferred: list[str] = []
    item_list_plan = group_plan(plan, "ItemList")
    user_data_plan = group_plan(plan, "UserData")
    keys_plan = group_plan(plan, "Keys")
    audio_keys_plan = group_plan(plan, "AudioKeys")
    video_keys_plan = group_plan(plan, "VideoKeys")
    if item_list_plan.values or item_list_plan.delete_groups:
        rewrite = rewrite_movie_item_list_atoms(movie_atoms, item_list_plan)
        movie_atoms = rewrite.atoms
        changed_atoms += rewrite.changed_atoms
    if user_data_plan.values or user_data_plan.delete_groups:
        rewrite = rewrite_movie_user_data_atoms(movie_atoms, user_data_plan)
        movie_atoms = rewrite.atoms
        changed_atoms += rewrite.changed_atoms
        deferred.extend(rewrite.deferred)
    if keys_plan.values or keys_plan.delete_groups:
        rewrite = rewrite_movie_keys_atoms(movie_atoms, keys_plan)
        movie_atoms = rewrite.atoms
        changed_atoms += rewrite.changed_atoms
    if audio_keys_plan.values or audio_keys_plan.delete_groups:
        rewrite = rewrite_track_keys_atoms(movie_atoms, audio_keys_plan, "soun")
        movie_atoms = rewrite.atoms
        changed_atoms += rewrite.changed_atoms
        deferred.extend(rewrite.deferred)
    if video_keys_plan.values or video_keys_plan.delete_groups:
        rewrite = rewrite_track_keys_atoms(movie_atoms, video_keys_plan, "vide")
        movie_atoms = rewrite.atoms
        changed_atoms += rewrite.changed_atoms
        deferred.extend(rewrite.deferred)
    return QuickTimeMetadataContainerRewrite(
        atoms=movie_atoms,
        changed_atoms=changed_atoms,
        deferred=tuple(deferred),
    )


def group_plan(
    plan: QuickTimeMetadataWritePlan,
    group: QuickTimeMetadataGroup,
) -> QuickTimeMetadataWritePlan:
    return QuickTimeMetadataWritePlan(
        values=tuple(value for value in plan.values if value.group == group),
        delete_groups=tuple(delete for delete in plan.delete_groups if delete.group == group),
        write_mode=plan.write_mode,
    )


def rewrite_movie_item_list_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    plan: QuickTimeMetadataWritePlan,
) -> QuickTimeMetadataContainerRewrite:
    udta_atoms = child_atoms_or_empty(atoms, QT_USER_DATA_ATOM)
    meta_atoms = child_atoms_or_empty(udta_atoms, QT_META_ATOM)
    ilst_atoms = child_atoms_or_empty(meta_atoms, QT_ITEM_LIST_ATOM)
    if plan.delete_groups and not plan.values and not ilst_atoms:
        return changed_container_result(atoms, atoms)
    rewritten_ilst_atoms = rewrite_item_list_atoms(ilst_atoms, plan)
    if not rewritten_ilst_atoms and not meta_atoms:
        return changed_container_result(atoms, atoms)
    rewritten_meta_atoms = upsert_child_atoms(
        ensure_handler_atom(meta_atoms, "mdir"),
        QT_ITEM_LIST_ATOM,
        encode_quicktime_atoms(rewritten_ilst_atoms),
    )
    rewritten_udta_atoms = upsert_child_atoms(
        udta_atoms,
        QT_META_ATOM,
        encode_quicktime_atoms(rewritten_meta_atoms),
    )
    rewritten_atoms = upsert_child_atoms(
        atoms,
        QT_USER_DATA_ATOM,
        encode_quicktime_atoms(rewritten_udta_atoms),
    )
    return changed_container_result(atoms, rewritten_atoms)


def rewrite_movie_item_list_binary_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    values: tuple[QuickTimeItemListBinaryValue, ...],
    write_mode: QuickTimeMetadataWriteMode,
) -> QuickTimeMetadataContainerRewrite:
    udta_atoms = child_atoms_or_empty(atoms, QT_USER_DATA_ATOM)
    meta_atoms = child_atoms_or_empty(udta_atoms, QT_META_ATOM)
    ilst_atoms = child_atoms_or_empty(meta_atoms, QT_ITEM_LIST_ATOM)
    rewritten_ilst_atoms = ilst_atoms
    for value in values:
        rewritten_ilst_atoms = upsert_item_list_binary_value(
            rewritten_ilst_atoms,
            value,
            write_mode,
        )
    rewritten_meta_atoms = upsert_child_atoms(
        ensure_handler_atom(meta_atoms, "mdir"),
        QT_ITEM_LIST_ATOM,
        encode_quicktime_atoms(rewritten_ilst_atoms),
    )
    rewritten_udta_atoms = upsert_child_atoms(
        udta_atoms,
        QT_META_ATOM,
        encode_quicktime_atoms(rewritten_meta_atoms),
    )
    rewritten_atoms = upsert_child_atoms(
        atoms,
        QT_USER_DATA_ATOM,
        encode_quicktime_atoms(rewritten_udta_atoms),
    )
    return changed_container_result(atoms, rewritten_atoms)


def rewrite_movie_user_data_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    plan: QuickTimeMetadataWritePlan,
) -> QuickTimeMetadataContainerRewrite:
    deferred: list[str] = []
    for value in plan.values:
        if value.language_code is not None and "-" in value.language_code:
            deferred.append(
                f"UserData:{value.name}-{value.language_code} not written: "
                "Upstream source rejects country codes for UserData international text atoms."
            )
    writable_values = tuple(
        value
        for value in plan.values
        if value.language_code is None or "-" not in value.language_code
    )
    writable_plan = QuickTimeMetadataWritePlan(
        values=writable_values,
        delete_groups=plan.delete_groups,
        write_mode=plan.write_mode,
    )
    udta_atoms = child_atoms_or_empty(atoms, QT_USER_DATA_ATOM)
    if writable_plan.delete_groups and not writable_plan.values and not udta_atoms:
        return QuickTimeMetadataContainerRewrite(
            atoms=atoms,
            changed_atoms=0,
            deferred=tuple(deferred),
        )
    rewritten_udta_atoms = rewrite_user_data_atoms(udta_atoms, writable_plan)
    rewritten_atoms = upsert_child_atoms(
        atoms,
        QT_USER_DATA_ATOM,
        encode_quicktime_atoms(rewritten_udta_atoms),
    )
    result = changed_container_result(atoms, rewritten_atoms)
    return QuickTimeMetadataContainerRewrite(
        atoms=result.atoms,
        changed_atoms=result.changed_atoms,
        deferred=tuple(deferred),
    )


def rewrite_movie_keys_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    plan: QuickTimeMetadataWritePlan,
) -> QuickTimeMetadataContainerRewrite:
    meta_atoms = child_atoms_or_empty(atoms, QT_META_ATOM)
    if plan.delete_groups and not plan.values and not meta_atoms:
        return changed_container_result(atoms, atoms)
    rewrite = rewrite_keys_meta_atoms(meta_atoms, plan)
    if not rewrite.meta_atoms and not meta_atoms:
        return changed_container_result(atoms, atoms)
    rewritten_atoms = upsert_child_atoms(
        atoms,
        QT_META_ATOM,
        encode_quicktime_atoms(rewrite.meta_atoms),
    )
    return changed_container_result(atoms, rewritten_atoms)


def rewrite_track_keys_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    plan: QuickTimeMetadataWritePlan,
    handler_type: str,
) -> QuickTimeMetadataContainerRewrite:
    rewritten_atoms: list[QuickTimeAtom] = []
    changed_atoms = 0
    matching_tracks = 0
    for atom in atoms:
        if atom.atom_type != QT_TRACK_ATOM:
            rewritten_atoms.append(atom)
            continue
        track_atoms = read_quicktime_atoms(atom.payload)
        if quicktime_track_handler_type(track_atoms) != handler_type:
            rewritten_atoms.append(atom)
            continue
        matching_tracks += 1
        meta_atoms = child_atoms_or_empty(track_atoms, QT_META_ATOM)
        rewrite = rewrite_keys_meta_atoms(meta_atoms, plan)
        rewritten_track_atoms = upsert_child_atoms(
            track_atoms,
            QT_META_ATOM,
            encode_quicktime_atoms(rewrite.meta_atoms),
        )
        rewritten_atoms.append(
            QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(rewritten_track_atoms))
        )
        changed_atoms += 1 if rewritten_track_atoms != track_atoms else 0
    deferred: tuple[str, ...] = ()
    if matching_tracks == 0:
        deferred = (f"No {handler_type} track found for {metadata_plan_group(plan)} metadata.",)
    return QuickTimeMetadataContainerRewrite(
        atoms=tuple(rewritten_atoms),
        changed_atoms=changed_atoms,
        deferred=deferred,
    )


def rewrite_keys_meta_atoms(
    meta_atoms: tuple[QuickTimeAtom, ...],
    plan: QuickTimeMetadataWritePlan,
) -> QuickTimeKeysRewrite:
    source_key_ids = keys_from_meta_atoms(meta_atoms)
    key_ids = list(source_key_ids)
    ilst_atoms = child_atoms_or_empty(meta_atoms, QT_ITEM_LIST_ATOM)
    if plan.delete_groups:
        key_ids = []
        ilst_atoms = ()
    for value in plan.values:
        tag = required_metadata_tag(value)
        key_id = tag.key_id
        if key_id is None:
            continue
        if value.value is None:
            if value.language_code is None:
                key_delete = delete_key_item_and_remap(ilst_atoms, tuple(key_ids), key_id)
                ilst_atoms = key_delete.ilst_atoms
                key_ids = list(key_delete.key_ids)
            else:
                ilst_atoms = delete_key_item(ilst_atoms, key_ids, key_id, value.language_code)
            continue
        if key_id not in key_ids:
            key_ids.append(key_id)
        key_index = key_ids.index(key_id) + 1
        item_atom_type = atom_type_from_key_index(key_index)
        ilst_atoms = upsert_item_list_value(
            ilst_atoms,
            item_atom_type,
            value.value,
            value.language_code,
            plan.write_mode,
            tag.item_list_format,
            planned_language_codes=planned_key_language_codes(plan, key_id),
        )
    rewritten_meta_atoms = ensure_handler_atom(meta_atoms, QT_METADATA_HANDLER)
    rewritten_meta_atoms = upsert_child_atoms(
        rewritten_meta_atoms,
        QT_KEYS_ATOM,
        encode_keys_payload(tuple(key_ids)),
    )
    rewritten_meta_atoms = upsert_child_atoms(
        rewritten_meta_atoms,
        QT_ITEM_LIST_ATOM,
        encode_quicktime_atoms(ilst_atoms),
    )
    if not key_ids and not ilst_atoms:
        rewritten_meta_atoms = tuple(
            atom
            for atom in rewritten_meta_atoms
            if atom.atom_type not in {QT_KEYS_ATOM, QT_ITEM_LIST_ATOM}
        )
    return QuickTimeKeysRewrite(
        meta_atoms=rewritten_meta_atoms,
        changed_atoms=1 if rewritten_meta_atoms != meta_atoms else 0,
    )


def rewrite_item_list_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    plan: QuickTimeMetadataWritePlan,
) -> tuple[QuickTimeAtom, ...]:
    rewritten = () if plan.delete_groups else atoms
    for value in plan.values:
        tag = required_metadata_tag(value)
        atom_type = value.atom_id_override or tag.atom_id
        if value.value is None:
            rewritten = delete_item_list_value(rewritten, atom_type, value.language_code)
        else:
            rewritten = upsert_item_list_value(
                rewritten,
                atom_type,
                value.value,
                value.language_code,
                plan.write_mode,
                item_list_value_format(tag, atom_type),
                planned_language_codes=planned_item_list_language_codes(plan, atom_type),
            )
    return rewritten


def rewrite_user_data_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    plan: QuickTimeMetadataWritePlan,
) -> tuple[QuickTimeAtom, ...]:
    if plan.delete_groups:
        deletable_atom_ids = frozenset(tag.atom_id for tag in USER_DATA_TAGS.values())
        rewritten = tuple(atom for atom in atoms if atom.atom_type not in deletable_atom_ids)
    else:
        rewritten = atoms
    for value in plan.values:
        tag = required_metadata_tag(value)
        if value.value is None:
            rewritten = tuple(atom for atom in rewritten if atom.atom_type != tag.atom_id)
            continue
        if plan.write_mode == "create" and atom_exists(rewritten, tag.atom_id):
            continue
        payload = encode_user_data_metadata_value(value.value, value.language_code, tag)
        rewritten = upsert_child_atoms(rewritten, tag.atom_id, payload)
    return rewritten


def encode_user_data_metadata_value(
    value: str,
    language_code: str | None,
    tag: QuickTimeMetadataTag,
) -> bytes:
    if tag.item_list_format == "gps_iso6709":
        _flags, value_bytes = encode_item_list_value_bytes(value, tag.item_list_format)
        return encode_user_data_text_value(value_bytes.decode("utf-8"), language_code)
    return encode_user_data_text_value(value, language_code)


def upsert_item_list_value(
    atoms: tuple[QuickTimeAtom, ...],
    atom_type: str,
    value: str,
    language_code: str | None,
    write_mode: QuickTimeMetadataWriteMode,
    value_format: QuickTimeItemListValueFormat = "utf8",
    planned_language_codes: tuple[str | None, ...] = (),
) -> tuple[QuickTimeAtom, ...]:
    replacement = encode_item_list_value_atom(value, language_code, value_format)
    preserved_languages = tuple(
        pack_quicktime_language_country(planned_language_code)
        for planned_language_code in planned_language_codes
        if planned_language_code is not None
    )
    rewritten: list[QuickTimeAtom] = []
    handled = False
    for atom in atoms:
        if atom.atom_type != atom_type:
            rewritten.append(atom)
            continue
        existing_data = parse_item_list_data_atoms(atom.payload)
        if write_mode == "create" and data_atom_language_exists(existing_data, language_code):
            rewritten.append(atom)
            handled = True
            continue
        if write_mode == "create":
            rewritten.append(QuickTimeAtom(atom.atom_type, atom.payload + replacement))
        else:
            kept_payload = b"".join(
                encode_quicktime_atom_from_data_atom(data_atom)
                for data_atom in existing_data
                if keep_data_atom_during_upsert(data_atom, language_code, preserved_languages)
            )
            rewritten.append(QuickTimeAtom(atom.atom_type, kept_payload + replacement))
        handled = True
    if not handled:
        rewritten.append(QuickTimeAtom(atom_type, replacement))
    return tuple(rewritten)


def data_atom_language_exists(
    data_atoms: tuple[QuickTimeDataAtom, ...],
    language_code: str | None,
) -> bool:
    country, language = pack_quicktime_language_country(language_code)
    return any(
        (data_atom.country, data_atom.language) == (country, language) for data_atom in data_atoms
    )


def upsert_item_list_binary_value(
    atoms: tuple[QuickTimeAtom, ...],
    value: QuickTimeItemListBinaryValue,
    write_mode: QuickTimeMetadataWriteMode,
) -> tuple[QuickTimeAtom, ...]:
    replacement = encode_item_list_binary_data_atom(value)
    rewritten: list[QuickTimeAtom] = []
    handled = False
    for atom in atoms:
        if atom.atom_type != value.atom_type:
            rewritten.append(atom)
            continue
        if write_mode == "create":
            rewritten.append(atom)
        else:
            rewritten.append(QuickTimeAtom(atom.atom_type, replacement))
        handled = True
    if not handled:
        rewritten.append(QuickTimeAtom(value.atom_type, replacement))
    return tuple(rewritten)


def encode_item_list_binary_data_atom(value: QuickTimeItemListBinaryValue) -> bytes:
    payload = (
        value.data_flags.to_bytes(4, "big")
        + QT_DEFAULT_COUNTRY.to_bytes(2, "big")
        + QT_DEFAULT_LANGUAGE.to_bytes(2, "big")
        + value.payload
    )
    return encode_quicktime_atom(QT_DATA_ATOM, payload)


def keep_data_atom_during_upsert(
    data_atom: QuickTimeDataAtom,
    language_code: str | None,
    preserved_languages: tuple[tuple[int, int], ...],
) -> bool:
    if language_code is not None:
        return not data_atom_matches_language(data_atom, language_code)
    language = (data_atom.country, data_atom.language)
    return language in preserved_languages


def planned_item_list_language_codes(
    plan: QuickTimeMetadataWritePlan,
    atom_type: str,
) -> tuple[str | None, ...]:
    language_codes: list[str | None] = []
    for value in plan.values:
        if value.value is None:
            continue
        tag = required_metadata_tag(value)
        if (value.atom_id_override or tag.atom_id) == atom_type:
            language_codes.append(value.language_code)
    return tuple(language_codes)


def planned_key_language_codes(
    plan: QuickTimeMetadataWritePlan,
    key_id: str,
) -> tuple[str | None, ...]:
    language_codes: list[str | None] = []
    for value in plan.values:
        if value.value is None:
            continue
        tag = required_metadata_tag(value)
        if tag.key_id == key_id:
            language_codes.append(value.language_code)
    return tuple(language_codes)


def delete_item_list_value(
    atoms: tuple[QuickTimeAtom, ...],
    atom_type: str,
    language_code: str | None,
) -> tuple[QuickTimeAtom, ...]:
    rewritten: list[QuickTimeAtom] = []
    for atom in atoms:
        if atom.atom_type != atom_type:
            rewritten.append(atom)
            continue
        if language_code is None:
            continue
        kept_payload = b"".join(
            encode_quicktime_atom_from_data_atom(data_atom)
            for data_atom in parse_item_list_data_atoms(atom.payload)
            if not data_atom_matches_language(data_atom, language_code)
        )
        if kept_payload:
            rewritten.append(QuickTimeAtom(atom.atom_type, kept_payload))
    return tuple(rewritten)


def delete_key_item(
    atoms: tuple[QuickTimeAtom, ...],
    key_ids: list[str],
    key_id: str,
    language_code: str | None,
) -> tuple[QuickTimeAtom, ...]:
    if key_id not in key_ids:
        return atoms
    return delete_item_list_value(
        atoms, atom_type_from_key_index(key_ids.index(key_id) + 1), language_code
    )


@dataclass(frozen=True)
class QuickTimeKeyDeleteRewrite:
    ilst_atoms: tuple[QuickTimeAtom, ...]
    key_ids: tuple[str, ...]


def delete_key_item_and_remap(
    atoms: tuple[QuickTimeAtom, ...],
    key_ids: tuple[str, ...],
    key_id: str,
) -> QuickTimeKeyDeleteRewrite:
    if key_id not in key_ids:
        return QuickTimeKeyDeleteRewrite(ilst_atoms=atoms, key_ids=key_ids)
    deleted_index = key_ids.index(key_id) + 1
    rewritten_key_ids = tuple(existing for existing in key_ids if existing != key_id)
    rewritten_atoms: list[QuickTimeAtom] = []
    for atom in atoms:
        index = key_index_from_atom_type(atom.atom_type)
        if index < 1 or index > len(key_ids):
            rewritten_atoms.append(atom)
            continue
        if index == deleted_index:
            continue
        if index > deleted_index:
            rewritten_atoms.append(QuickTimeAtom(atom_type_from_key_index(index - 1), atom.payload))
            continue
        rewritten_atoms.append(atom)
    return QuickTimeKeyDeleteRewrite(
        ilst_atoms=tuple(rewritten_atoms),
        key_ids=rewritten_key_ids,
    )


def encode_quicktime_atom_from_data_atom(data_atom: QuickTimeDataAtom) -> bytes:
    payload = (
        data_atom.flags.to_bytes(4, "big")
        + data_atom.country.to_bytes(2, "big")
        + data_atom.language.to_bytes(2, "big")
        + data_atom.value
    )
    return encode_quicktime_atom(QT_DATA_ATOM, payload)


def keys_from_meta_atoms(meta_atoms: tuple[QuickTimeAtom, ...]) -> tuple[str, ...]:
    for atom in meta_atoms:
        if atom.atom_type == QT_KEYS_ATOM:
            return parse_keys_payload(atom.payload)
    return ()


def ensure_handler_atom(
    atoms: tuple[QuickTimeAtom, ...],
    handler_type: str,
) -> tuple[QuickTimeAtom, ...]:
    handler = encode_handler_atom(handler_type)
    rewritten: list[QuickTimeAtom] = []
    handled = False
    for atom in atoms:
        if atom.atom_type != QT_HANDLER_ATOM:
            rewritten.append(atom)
            continue
        rewritten.append(handler)
        handled = True
    if not handled:
        return (handler, *atoms)
    return tuple(rewritten)


def child_atoms_or_empty(
    atoms: tuple[QuickTimeAtom, ...], atom_type: str
) -> tuple[QuickTimeAtom, ...]:
    for atom in atoms:
        if atom.atom_type == atom_type:
            return read_quicktime_atoms(atom.payload)
    return ()


def upsert_child_atoms(
    atoms: tuple[QuickTimeAtom, ...],
    atom_type: str,
    payload: bytes,
) -> tuple[QuickTimeAtom, ...]:
    rewritten: list[QuickTimeAtom] = []
    handled = False
    for atom in atoms:
        if atom.atom_type != atom_type:
            rewritten.append(atom)
            continue
        if payload:
            rewritten.append(QuickTimeAtom(atom_type, payload))
        handled = True
    if not handled and payload:
        rewritten.append(QuickTimeAtom(atom_type, payload))
    return tuple(rewritten)


def atom_exists(atoms: tuple[QuickTimeAtom, ...], atom_type: str) -> bool:
    return any(atom.atom_type == atom_type for atom in atoms)


def required_metadata_tag(value: QuickTimeMetadataValue) -> QuickTimeMetadataTag:
    tag = quicktime_metadata_tag(value.group, value.name)
    if tag is None:
        raise ValueError(f"Unsupported QuickTime {value.group}:{value.name} metadata tag.")
    return tag


def item_list_tag_for_atom(atom_type: str) -> QuickTimeMetadataTag | None:
    for tag in quicktime_item_list_tags():
        if tag.atom_id == atom_type:
            return tag
    return None


def quicktime_item_list_tags() -> tuple[QuickTimeMetadataTag, ...]:
    return tuple(ITEM_LIST_TAGS.values())


def item_list_value_format(
    tag: QuickTimeMetadataTag,
    atom_type: str,
) -> QuickTimeItemListValueFormat:
    if tag.name == "Genre" and atom_type == "gnre":
        return "genre_id"
    return tag.item_list_format


def changed_container_result(
    original_atoms: tuple[QuickTimeAtom, ...],
    rewritten_atoms: tuple[QuickTimeAtom, ...],
) -> QuickTimeMetadataContainerRewrite:
    return QuickTimeMetadataContainerRewrite(
        atoms=rewritten_atoms,
        changed_atoms=1 if rewritten_atoms != original_atoms else 0,
    )


def metadata_plan_group(plan: QuickTimeMetadataWritePlan) -> QuickTimeMetadataGroup:
    if plan.values:
        return plan.values[0].group
    return plan.delete_groups[0].group
