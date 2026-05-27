"""Mach-O file-kind override planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type MachOOverrideStatus = Literal["planned", "not_needed"]
type MachOOverrideExtension = Literal["O", "DYLIB"]
type MachOOverrideEvidenceId = Literal["exe.mach_o.kind_override"]
type MachOOverrideProvenance = tuple[MachOOverrideEvidenceId, ...]

MACH_OVERRIDE_EVIDENCE_ID: MachOOverrideEvidenceId = "exe.mach_o.kind_override"

MACH_OVERRIDE_TABLE: dict[int, tuple[str, MachOOverrideExtension]] = {
    1: ("file", "O"),
    6: ("dynamic link library", "DYLIB"),
    8: ("dynamic bound bundle", "DYLIB"),
    9: ("dynamic link library stub", "DYLIB"),
}


@dataclass(frozen=True)
class MachOOverridePlan:
    status: MachOOverrideStatus
    file_kind_value: int
    description: str | None
    extension: MachOOverrideExtension | None
    provenance: MachOOverrideProvenance


def build_mach_o_override_plan(file_kind_value: int, fat_binary: bool = False) -> MachOOverridePlan:
    override = MACH_OVERRIDE_TABLE.get(file_kind_value)
    if override is None:
        return MachOOverridePlan(
            status="not_needed",
            file_kind_value=file_kind_value,
            description=None,
            extension=None,
            provenance=(MACH_OVERRIDE_EVIDENCE_ID,),
        )
    description, extension = override
    prefix = "Mach-O fat " if fat_binary else "Mach-O "
    return MachOOverridePlan(
        status="planned",
        file_kind_value=file_kind_value,
        description=prefix + description,
        extension=extension,
        provenance=(MACH_OVERRIDE_EVIDENCE_ID,),
    )
