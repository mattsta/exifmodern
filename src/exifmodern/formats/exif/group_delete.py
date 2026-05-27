"""EXIF group deletion plan primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type ExifGroupDeleteTarget = Literal["EXIF", "IFD0", "ExifIFD"]

EXIF_GROUP_DELETE_SOURCE_ID = "format.exif.group_delete.exif_ifd0_guard"
EXIF_IFD_GROUP_DELETE_SOURCE_ID = "format.exif.group_delete.exif_ifd"


@dataclass(frozen=True)
class ExifGroupDeletePlan:
    target: ExifGroupDeleteTarget
    evidence_ids: tuple[str, ...]


def build_exif_group_delete_plan(target: ExifGroupDeleteTarget) -> ExifGroupDeletePlan:
    if target == "ExifIFD":
        return ExifGroupDeletePlan(
            target=target,
            evidence_ids=(EXIF_GROUP_DELETE_SOURCE_ID, EXIF_IFD_GROUP_DELETE_SOURCE_ID),
        )
    return ExifGroupDeletePlan(
        target=target,
        evidence_ids=(EXIF_GROUP_DELETE_SOURCE_ID,),
    )


def exif_group_delete_target(value: str) -> ExifGroupDeleteTarget:
    if value == "EXIF":
        return "EXIF"
    if value == "IFD0":
        return "IFD0"
    if value == "ExifIFD":
        return "ExifIFD"
    raise ValueError("EXIF group delete target must be EXIF, IFD0, or ExifIFD.")
