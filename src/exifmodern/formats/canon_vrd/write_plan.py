"""CanonVRD block delete plans."""

from __future__ import annotations

from dataclasses import dataclass

CANON_VRD_DELETE_SOURCE_ID = "canon_vrd.delete.trailer_block"


@dataclass(frozen=True)
class CanonVrdDeletePlan:
    source_reference_ids: tuple[str, ...]


def build_canon_vrd_delete_plan() -> CanonVrdDeletePlan:
    return CanonVrdDeletePlan(source_reference_ids=(CANON_VRD_DELETE_SOURCE_ID,))
