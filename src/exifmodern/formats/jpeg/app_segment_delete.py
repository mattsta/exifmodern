"""JPEG APP segment delete plans and mutation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.jpeg.container import scan_jpeg_segments
from exifmodern.formats.jpeg.trailers.afcp_rewrite import adjust_afcp_offsets_after_delete

type JpegAppSegmentDeleteTarget = Literal["APP6"]

JPEG_APP6_DELETE_SOURCE_ID = "jpeg.app_segment_delete.app6_delete"

JPEG_APP_SEGMENT_MARKERS: dict[JpegAppSegmentDeleteTarget, int] = {
    "APP6": 0xE6,
}


@dataclass(frozen=True)
class JpegAppSegmentDeletePlan:
    target: JpegAppSegmentDeleteTarget
    marker: int
    source_reference_ids: tuple[str, ...]


@dataclass(frozen=True)
class JpegAppSegmentDeleteResult:
    data: bytes
    deleted_segments: int
    deleted_bytes: int


def build_jpeg_app_segment_delete_plan(
    target: JpegAppSegmentDeleteTarget,
) -> JpegAppSegmentDeletePlan:
    return JpegAppSegmentDeletePlan(
        target=target,
        marker=JPEG_APP_SEGMENT_MARKERS[target],
        source_reference_ids=(JPEG_APP6_DELETE_SOURCE_ID,),
    )


def jpeg_app_segment_delete_target(value: str) -> JpegAppSegmentDeleteTarget:
    if value == "APP6":
        return "APP6"
    raise ValueError("JPEG APP segment delete currently supports APP6.")


def delete_jpeg_app_segments(
    jpeg_data: bytes,
    plan: JpegAppSegmentDeletePlan,
) -> JpegAppSegmentDeleteResult:
    rewritten = jpeg_data
    deleted_so_far = 0
    deleted_segments = 0
    for segment in scan_jpeg_segments(jpeg_data):
        if segment.marker != plan.marker:
            continue
        original_segment_end = segment.payload_offset + segment.payload_length
        rewritten_start = segment.offset - deleted_so_far
        deleted_length = original_segment_end - segment.offset
        rewritten_end = rewritten_start + deleted_length
        rewritten = rewritten[:rewritten_start] + rewritten[rewritten_end:]
        rewritten = adjust_afcp_offsets_after_delete(
            rewritten,
            rewritten_start,
            deleted_length,
        )
        deleted_so_far += deleted_length
        deleted_segments += 1
    return JpegAppSegmentDeleteResult(
        data=rewritten,
        deleted_segments=deleted_segments,
        deleted_bytes=deleted_so_far,
    )
