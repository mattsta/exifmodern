"""JPEG CanonVRD trailer mutation boundary."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.canon_vrd.reader import find_canon_vrd_trailer
from exifmodern.formats.canon_vrd.write_plan import CanonVrdDeletePlan
from exifmodern.formats.jpeg.trailers.afcp_rewrite import adjust_afcp_offsets_after_delete


@dataclass(frozen=True)
class JpegCanonVrdDeleteResult:
    data: bytes
    deleted: bool
    deleted_bytes: int


def delete_jpeg_canon_vrd_trailer(
    jpeg_data: bytes,
    plan: CanonVrdDeletePlan,
) -> JpegCanonVrdDeleteResult:
    trailer = find_canon_vrd_trailer(jpeg_data)
    if trailer is None:
        return JpegCanonVrdDeleteResult(data=jpeg_data, deleted=False, deleted_bytes=0)
    trailer_end = trailer.start + len(trailer.payload)
    deleted_length = trailer_end - trailer.start
    rewritten = jpeg_data[: trailer.start] + jpeg_data[trailer_end:]
    rewritten = adjust_afcp_offsets_after_delete(rewritten, trailer.start, deleted_length)
    _ = plan.source_reference_ids
    return JpegCanonVrdDeleteResult(
        data=rewritten,
        deleted=True,
        deleted_bytes=deleted_length,
    )
