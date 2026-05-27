"""Typed FotoStation trailer write plans."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.write_plan import EvidenceAnchor

FOTOSTATION_ROTATION_ANCHOR = EvidenceAnchor(
    path="lib/Image/ExifTool/FotoStation.pm",
    line_start=80,
    line_end=92,
    symbol="Image::ExifTool::FotoStation::SoftEdit Rotation",
    evidence="Rotation is SoftEdit entry 4 and stores degrees counter-clockwise times 100.",
)


@dataclass(frozen=True)
class FotoStationRotationWritePlan:
    degrees_clockwise: int
    raw_counter_clockwise_centidegrees: int
    evidence_anchors: tuple[EvidenceAnchor, ...]


def build_fotostation_rotation_write_plan(value: str) -> FotoStationRotationWritePlan:
    degrees = int(value)
    if degrees not in {0, 90, 180, 270}:
        raise ValueError("FotoStation Rotation must be 0, 90, 180, or 270 degrees.")
    raw_value = 0 if degrees == 0 else (360 - degrees) * 100
    return FotoStationRotationWritePlan(
        degrees_clockwise=degrees,
        raw_counter_clockwise_centidegrees=raw_value,
        evidence_anchors=(FOTOSTATION_ROTATION_ANCHOR,),
    )
