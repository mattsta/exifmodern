"""JPEG APP3 Kodak MetaIFD mutation boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace

from exifmodern.formats.jpeg.container import scan_jpeg_segments
from exifmodern.formats.jpeg.exif_app1 import segment_payload
from exifmodern.formats.jpeg.segment_writer import replace_jpeg_segment
from exifmodern.formats.kodak.meta_write_plan import KodakMetaWritePlan, KodakMetaWriteStep
from exifmodern.formats.kodak.reader import KODAK_META_PREFIX
from exifmodern.formats.tiff.mutation import (
    RawTiffDirectory,
    RawTiffEntry,
    encode_tiff_mutation_model,
    parse_tiff_mutation_model,
    upsert_raw_entry,
)
from exifmodern.formats.tiff.primitives import TIFF_TYPE_UNDEFINED

JPEG_APP3_MARKER = 0xE3


@dataclass(frozen=True)
class JpegKodakMetaRewriteResult:
    data: bytes
    changed_tags: int


def rewrite_jpeg_kodak_meta(
    jpeg_data: bytes,
    plan: KodakMetaWritePlan,
) -> JpegKodakMetaRewriteResult:
    for segment in scan_jpeg_segments(jpeg_data):
        if segment.marker != JPEG_APP3_MARKER:
            continue
        payload = segment_payload(jpeg_data, segment)
        if not payload.startswith(KODAK_META_PREFIX):
            continue
        rewritten_payload = KODAK_META_PREFIX + rewrite_kodak_meta_tiff(
            payload[len(KODAK_META_PREFIX) :],
            plan,
        )
        return JpegKodakMetaRewriteResult(
            data=replace_jpeg_segment(jpeg_data, segment, rewritten_payload),
            changed_tags=len(plan.steps),
        )
    raise ValueError("JPEG does not contain a Kodak APP3 Meta segment.")


def rewrite_kodak_meta_tiff(tiff_data: bytes, plan: KodakMetaWritePlan) -> bytes:
    parsed = parse_tiff_mutation_model(tiff_data)
    updated_entries = parsed.ifd0.entries
    for step in plan.steps:
        updated_entries = upsert_raw_entry(updated_entries, kodak_meta_step_entry(step))
    return encode_tiff_mutation_model(
        replace(
            parsed,
            ifd0=RawTiffDirectory(
                entries=tuple(sorted(updated_entries, key=lambda entry: entry.tag_id)),
                next_ifd_offset=parsed.ifd0.next_ifd_offset,
            ),
        )
    )


def kodak_meta_step_entry(step: KodakMetaWriteStep) -> RawTiffEntry:
    raw_value = step.value.encode("ascii")
    return RawTiffEntry(
        tag_id=step.tag_id,
        field_type=TIFF_TYPE_UNDEFINED,
        count=len(raw_value),
        raw_value=raw_value,
    )
