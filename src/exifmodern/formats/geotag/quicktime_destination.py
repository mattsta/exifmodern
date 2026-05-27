"""QuickTime destination adapter for public Geotag writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.file_transaction import (
    BackupPolicy,
    FileWriteTransactionResult,
    write_bytes_in_place_transactionally,
)
from exifmodern.formats.geotag.write_effects import GeotagWriteEffects
from exifmodern.formats.quicktime.atoms import (
    QT_ATOM_HEADER_SIZE,
    QT_EXTENDED_ATOM_HEADER_SIZE,
    read_quicktime_atoms,
)
from exifmodern.formats.quicktime.fanout_write_plan import plan_quicktime_fanout_write_args
from exifmodern.formats.quicktime.fanout_writer import rewrite_quicktime_fanout

type GeotagQuickTimeDestinationGroup = Literal["QuickTime", "ItemList", "UserData", "Keys"]


@dataclass(frozen=True)
class GeotagQuickTimeRewriteResult:
    data: bytes
    changed_atoms: int
    applied_metadata: bool
    executed_surfaces: tuple[str, ...]
    blocked_surfaces: tuple[str, ...]
    deferred: tuple[str, ...]
    transaction: FileWriteTransactionResult | None = None


def geotag_quicktime_coordinates_value(effects: GeotagWriteEffects) -> str | None:
    selected_fix = effects.application_result.selected_fix
    if selected_fix is None or selected_fix.latitude is None or selected_fix.longitude is None:
        return None
    coords = f"{selected_fix.latitude} {selected_fix.longitude}"
    if selected_fix.altitude is not None:
        coords = f"{coords} {selected_fix.altitude}"
    return coords


def geotag_quicktime_destination_assignment(
    destination_group: GeotagQuickTimeDestinationGroup,
    coordinates: str,
) -> str:
    preferred_group = "ItemList" if destination_group == "QuickTime" else destination_group
    return f"-{preferred_group}:GPSCoordinates={coordinates}"


def geotag_quicktime_destination_delete_assignments(
    destination_group: GeotagQuickTimeDestinationGroup,
) -> tuple[str, ...]:
    if destination_group == "QuickTime":
        return (
            "-ItemList:GPSCoordinates=",
            "-UserData:GPSCoordinates=",
            "-Keys:GPSCoordinates=",
        )
    return (f"-{destination_group}:GPSCoordinates=",)


def is_quicktime_container(data: bytes) -> bool:
    try:
        atoms = read_quicktime_atoms(data)
    except ValueError:
        return False
    return any(atom.atom_type == "ftyp" for atom in atoms) and any(
        atom.atom_type == "moov" for atom in atoms
    )


def is_quicktime_container_path(path: Path) -> bool:
    """Check QuickTime/BMFF structure from top-level atom headers only."""

    try:
        atom_types = _quicktime_top_level_atom_types(path)
    except OSError, ValueError:
        return False
    return "ftyp" in atom_types and "moov" in atom_types


def _quicktime_top_level_atom_types(path: Path) -> frozenset[str]:
    atom_types: set[str] = set()
    file_size = path.stat().st_size
    with path.open("rb") as file:
        offset = 0
        while offset + QT_ATOM_HEADER_SIZE <= file_size:
            file.seek(offset)
            header = file.read(QT_ATOM_HEADER_SIZE)
            if len(header) != QT_ATOM_HEADER_SIZE:
                raise ValueError("Truncated QuickTime atom header.")
            atom_size = int.from_bytes(header[:4], "big")
            atom_type = header[4:8].decode("latin-1", errors="replace")
            header_size = QT_ATOM_HEADER_SIZE
            if atom_size == 0:
                total_size = file_size - offset
            elif atom_size == 1:
                extended_header = file.read(QT_ATOM_HEADER_SIZE)
                if len(extended_header) != QT_ATOM_HEADER_SIZE:
                    raise ValueError("Truncated QuickTime extended atom header.")
                total_size = int.from_bytes(extended_header, "big")
                header_size = QT_EXTENDED_ATOM_HEADER_SIZE
            else:
                total_size = atom_size
            if total_size < header_size or offset + total_size > file_size:
                raise ValueError(f"Invalid QuickTime atom length for {atom_type!r}.")
            atom_types.add(atom_type)
            if {"ftyp", "moov"}.issubset(atom_types):
                return frozenset(atom_types)
            if total_size == 0:
                break
            offset += total_size
    return frozenset(atom_types)


def rewrite_quicktime_file_geotag_in_place(
    target_path: Path,
    effects: GeotagWriteEffects,
    destination_group: GeotagQuickTimeDestinationGroup,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> GeotagQuickTimeRewriteResult:
    coordinates = geotag_quicktime_coordinates_value(effects)
    if coordinates is None:
        raise ValueError("QuickTime geotag requires latitude and longitude.")
    plan = plan_quicktime_fanout_write_args(
        (geotag_quicktime_destination_assignment(destination_group, coordinates),)
    )
    result = rewrite_quicktime_fanout(target_path.read_bytes(), plan)
    transaction = write_bytes_in_place_transactionally(
        target_path,
        result.data,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return GeotagQuickTimeRewriteResult(
        data=result.data,
        changed_atoms=result.changed_atoms,
        applied_metadata=result.applied_metadata,
        executed_surfaces=tuple(result.executed_surfaces),
        blocked_surfaces=tuple(result.blocked_surfaces),
        deferred=result.deferred,
        transaction=transaction,
    )


def delete_quicktime_file_geotag_in_place(
    target_path: Path,
    destination_group: GeotagQuickTimeDestinationGroup,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> GeotagQuickTimeRewriteResult:
    plan = plan_quicktime_fanout_write_args(
        geotag_quicktime_destination_delete_assignments(destination_group)
    )
    result = rewrite_quicktime_fanout(target_path.read_bytes(), plan)
    transaction = write_bytes_in_place_transactionally(
        target_path,
        result.data,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return GeotagQuickTimeRewriteResult(
        data=result.data,
        changed_atoms=result.changed_atoms,
        applied_metadata=result.applied_metadata,
        executed_surfaces=tuple(result.executed_surfaces),
        blocked_surfaces=tuple(result.blocked_surfaces),
        deferred=result.deferred,
        transaction=transaction,
    )
