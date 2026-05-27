"""JPEG APP0 Canon CIFF mutation boundary."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.canon.ciff import (
    CIFF_SIGNATURE,
    CiffEntry,
    CiffLocatedEntry,
    find_ciff_entry,
    parse_ciff_header,
)
from exifmodern.formats.canon.ciff_write_plan import CiffWritePlan, CiffWriteStep
from exifmodern.formats.jpeg.container import scan_jpeg_segments
from exifmodern.formats.jpeg.exif_app1 import segment_payload
from exifmodern.formats.jpeg.segment_writer import replace_jpeg_segment

JPEG_APP0_MARKER = 0xE0


@dataclass(frozen=True)
class JpegCiffRewriteResult:
    data: bytes
    changed_tags: int


def rewrite_jpeg_ciff(jpeg_data: bytes, plan: CiffWritePlan) -> JpegCiffRewriteResult:
    for segment in scan_jpeg_segments(jpeg_data):
        if segment.marker != JPEG_APP0_MARKER:
            continue
        payload = segment_payload(jpeg_data, segment)
        if len(payload) < 14 or payload[:2] not in {b"II", b"MM"}:
            continue
        if payload[6:14] != CIFF_SIGNATURE:
            continue
        rewritten_payload = rewrite_ciff_payload(payload, plan)
        return JpegCiffRewriteResult(
            data=replace_jpeg_segment(jpeg_data, segment, rewritten_payload),
            changed_tags=len(plan.steps),
        )
    raise ValueError("JPEG does not contain a Canon CIFF APP0 segment.")


def rewrite_ciff_payload(payload: bytes, plan: CiffWritePlan) -> bytes:
    context, block_start, block_size = parse_ciff_header(payload)
    mutable = bytearray(payload)
    for step in plan.steps:
        located_entry = find_ciff_entry(context, block_start, block_size, step.tag_id)
        if located_entry is None:
            raise ValueError(f"Canon CIFF tag is not present for in-place write: {step.tag_name}")
        rewrite_ciff_string(mutable, located_entry, step)
    return bytes(mutable)


def rewrite_ciff_string(
    mutable: bytearray,
    located_entry: CiffLocatedEntry,
    step: CiffWriteStep,
) -> None:
    entry: CiffEntry = located_entry.entry
    if entry.value_in_directory:
        raise ValueError(f"Canon CIFF {step.tag_name} in-directory writes are not supported.")
    if entry.tag_type != 0x08:
        raise ValueError(f"Canon CIFF {step.tag_name} is not a string tag.")
    encoded = step.value.encode("utf-8")
    if len(encoded) >= step.max_byte_count or len(encoded) >= entry.size:
        raise ValueError(f"Canon CIFF {step.tag_name} value exceeds the existing field size.")
    value_start = located_entry.block_start + entry.value_pointer
    value_end = value_start + entry.size
    if value_start < 0 or value_end > len(mutable):
        raise ValueError(f"Canon CIFF {step.tag_name} has an invalid value offset.")
    mutable[value_start:value_end] = encoded + bytes(entry.size - len(encoded))
