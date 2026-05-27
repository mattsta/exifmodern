"""JPEG container boundary for EXIF IFD1 thumbnail deletion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.file_transaction import FileWriteTransactionResult, write_bytes_transactionally
from exifmodern.formats.jpeg.exact_rewrite_io import read_exact_jpeg_rewrite_source
from exifmodern.formats.jpeg.exif_app1 import (
    EXIF_APP1_PREFIX,
    encode_app1_segment,
    find_exif_app1_segment,
    segment_payload,
)
from exifmodern.formats.tiff.thumbnail_delete import (
    ExifThumbnailDeletePlan,
    delete_exif_ifd1_thumbnail_reference,
)


@dataclass(frozen=True)
class JpegExifThumbnailDeleteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    changed_thumbnail_references: int
    transaction: FileWriteTransactionResult | None = None


def delete_jpeg_exif_thumbnail(
    jpeg_data: bytes,
    plan: ExifThumbnailDeletePlan,
) -> JpegExifThumbnailDeleteResult:
    segment = find_exif_app1_segment(jpeg_data)
    payload = segment_payload(jpeg_data, segment)
    delete_result = delete_exif_ifd1_thumbnail_reference(
        payload[len(EXIF_APP1_PREFIX) :],
        plan,
    )
    if delete_result.changed_thumbnail_references == 0:
        return JpegExifThumbnailDeleteResult(
            data=jpeg_data,
            original_app1_payload_length=segment.payload_length,
            rewritten_app1_payload_length=segment.payload_length,
            changed_thumbnail_references=0,
        )
    rewritten_payload = EXIF_APP1_PREFIX + delete_result.data
    rewritten_segment = encode_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    return JpegExifThumbnailDeleteResult(
        data=jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:],
        original_app1_payload_length=segment.payload_length,
        rewritten_app1_payload_length=len(rewritten_payload),
        changed_thumbnail_references=delete_result.changed_thumbnail_references,
    )


def delete_jpeg_file_exif_thumbnail(
    input_path: Path,
    output_path: Path,
    plan: ExifThumbnailDeletePlan,
) -> JpegExifThumbnailDeleteResult:
    result = delete_jpeg_exif_thumbnail(read_exact_jpeg_rewrite_source(input_path), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegExifThumbnailDeleteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        changed_thumbnail_references=result.changed_thumbnail_references,
        transaction=transaction,
    )
