"""Typed PhotoMechanic trailer write plans."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.write_plan import EvidenceAnchor

PHOTO_MECHANIC_ROTATION_ANCHOR = EvidenceAnchor(
    path="lib/Image/ExifTool/PhotoMechanic.pm",
    line_start=74,
    line_end=83,
    symbol="Image::ExifTool::PhotoMechanic::SoftEdit Rotation",
    evidence="Rotation is SoftEdit dataset 216 and stores quarter-turn indexes.",
)

PHOTO_MECHANIC_ROTATION_RAW_VALUES = {
    0: 0,
    90: 1,
    180: 2,
    270: 3,
}


@dataclass(frozen=True)
class PhotoMechanicRotationWritePlan:
    degrees_clockwise: int
    raw_rotation_index: int
    evidence_anchors: tuple[EvidenceAnchor, ...]


def build_photo_mechanic_rotation_write_plan(value: str) -> PhotoMechanicRotationWritePlan:
    degrees = int(value)
    raw_value = PHOTO_MECHANIC_ROTATION_RAW_VALUES.get(degrees)
    if raw_value is None:
        raise ValueError("PhotoMechanic Rotation must be 0, 90, 180, or 270 degrees.")
    return PhotoMechanicRotationWritePlan(
        degrees_clockwise=degrees,
        raw_rotation_index=raw_value,
        evidence_anchors=(PHOTO_MECHANIC_ROTATION_ANCHOR,),
    )
