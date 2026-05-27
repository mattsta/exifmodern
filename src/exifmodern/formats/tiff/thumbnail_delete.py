"""In-place EXIF IFD1 thumbnail reference deletion."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.tiff.primitives import parse_ifd, parse_tiff_header

THUMBNAIL_DELETE_EVIDENCE_IDS = (
    "tiff_thumbnail.delete_ifd1_reference",
    "tiff_thumbnail.pentax_write_delete",
)


@dataclass(frozen=True)
class ExifThumbnailDeletePlan:
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExifThumbnailDeleteResult:
    data: bytes
    changed_thumbnail_references: int


def build_exif_thumbnail_delete_plan() -> ExifThumbnailDeletePlan:
    return ExifThumbnailDeletePlan(THUMBNAIL_DELETE_EVIDENCE_IDS)


def delete_exif_ifd1_thumbnail_reference(
    tiff_data: bytes,
    plan: ExifThumbnailDeletePlan,
) -> ExifThumbnailDeleteResult:
    if not plan.evidence_ids:
        raise ValueError("EXIF thumbnail delete plan must include evidence IDs.")
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    if ifd0.next_ifd_offset == 0:
        return ExifThumbnailDeleteResult(tiff_data, 0)
    mutable = bytearray(tiff_data)
    next_ifd_offset_position = ifd0.offset + 2 + len(ifd0.entries) * 12
    mutable[next_ifd_offset_position : next_ifd_offset_position + 4] = (0).to_bytes(
        4,
        header.endian,
    )
    return ExifThumbnailDeleteResult(bytes(mutable), 1)
