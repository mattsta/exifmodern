"""JPEG EXIF group deletion boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.file_transaction import (
    BackupPolicy,
    FileWriteTransactionResult,
    write_bytes_in_place_transactionally,
    write_bytes_transactionally,
)
from exifmodern.formats.exif.group_delete import ExifGroupDeletePlan
from exifmodern.formats.jpeg.exact_rewrite_io import read_exact_jpeg_rewrite_source
from exifmodern.formats.jpeg.exif_app1 import (
    EXIF_APP1_PREFIX,
    encode_app1_segment,
    find_exif_app1_segment_or_none,
    segment_payload,
)
from exifmodern.formats.jpeg.trailers.afcp_rewrite import adjust_afcp_offsets_after_delete
from exifmodern.formats.tiff.exif_group_rewriter import delete_exif_ifd


@dataclass(frozen=True)
class JpegExifGroupDeleteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    transaction: FileWriteTransactionResult | None = None


def delete_jpeg_exif_group(
    jpeg_data: bytes,
    plan: ExifGroupDeletePlan,
) -> JpegExifGroupDeleteResult:
    segment = find_exif_app1_segment_or_none(jpeg_data)
    if segment is None:
        return JpegExifGroupDeleteResult(
            data=jpeg_data,
            original_app1_payload_length=0,
            rewritten_app1_payload_length=0,
        )
    if plan.target in {"EXIF", "IFD0"}:
        segment_end = segment.payload_offset + segment.payload_length
        deleted_length = segment_end - segment.offset
        rewritten = jpeg_data[: segment.offset] + jpeg_data[segment_end:]
        rewritten = adjust_afcp_offsets_after_delete(
            rewritten,
            segment.offset,
            deleted_length,
        )
        return JpegExifGroupDeleteResult(
            data=rewritten,
            original_app1_payload_length=segment.payload_length,
            rewritten_app1_payload_length=0,
        )
    payload = segment_payload(jpeg_data, segment)
    rewritten_tiff = delete_exif_ifd(payload[len(EXIF_APP1_PREFIX) :])
    rewritten_payload = EXIF_APP1_PREFIX + rewritten_tiff
    rewritten_segment = encode_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    return JpegExifGroupDeleteResult(
        data=jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:],
        original_app1_payload_length=segment.payload_length,
        rewritten_app1_payload_length=len(rewritten_payload),
    )


def delete_jpeg_file_exif_group(
    input_path: Path,
    output_path: Path,
    plan: ExifGroupDeletePlan,
) -> JpegExifGroupDeleteResult:
    result = delete_jpeg_exif_group(read_exact_jpeg_rewrite_source(input_path), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegExifGroupDeleteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        transaction=transaction,
    )


def delete_jpeg_file_exif_group_in_place(
    target_path: Path,
    plan: ExifGroupDeletePlan,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> JpegExifGroupDeleteResult:
    result = delete_jpeg_exif_group(read_exact_jpeg_rewrite_source(target_path), plan)
    transaction = write_bytes_in_place_transactionally(
        target_path,
        result.data,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return JpegExifGroupDeleteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        transaction=transaction,
    )
