"""JPEG APP1 EXIF GPS mutation boundary.

This module handles JPEG EXIF APP1 GPS writes. GPS IFD creation inside existing
EXIF and minimal EXIF APP1 creation for no-EXIF JPEGs are both backed by
checked-in source-oracle probes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.file_transaction import (
    BackupPolicy,
    FileWriteTransactionResult,
    write_bytes_in_place_transactionally,
    write_bytes_transactionally,
)
from exifmodern.formats.jpeg.exact_rewrite_io import read_exact_jpeg_rewrite_source
from exifmodern.formats.jpeg.exif_app1 import (
    EXIF_APP1_PREFIX,
    encode_app1_segment,
    exif_app1_insertion_offset,
    find_exif_app1_segment,
    find_exif_app1_segment_or_none,
    segment_payload,
)
from exifmodern.formats.tiff.gps_rewriter import (
    create_minimal_gps_tiff,
    delete_gps_ifd,
    rewrite_existing_gps_ifd,
    rewrite_gps_ifd_creating_if_needed,
)
from exifmodern.write_plan import ExifGpsWritePlan


@dataclass(frozen=True)
class JpegExifGpsRewriteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    transaction: FileWriteTransactionResult | None = None


def rewrite_jpeg_existing_exif_gps(
    jpeg_data: bytes,
    plan: ExifGpsWritePlan,
) -> JpegExifGpsRewriteResult:
    segment = find_exif_app1_segment(jpeg_data)
    payload = segment_payload(jpeg_data, segment)
    rewritten_tiff = rewrite_existing_gps_ifd(payload[len(EXIF_APP1_PREFIX) :], plan)
    rewritten_payload = EXIF_APP1_PREFIX + rewritten_tiff
    rewritten_segment = encode_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    return JpegExifGpsRewriteResult(
        data=jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:],
        original_app1_payload_length=segment.payload_length,
        rewritten_app1_payload_length=len(rewritten_payload),
    )


def rewrite_jpeg_exif_gps_creating_if_needed(
    jpeg_data: bytes,
    plan: ExifGpsWritePlan,
) -> JpegExifGpsRewriteResult:
    segment = find_exif_app1_segment_or_none(jpeg_data)
    if segment is None:
        rewritten_tiff = create_minimal_gps_tiff(plan)
        rewritten_payload = EXIF_APP1_PREFIX + rewritten_tiff
        rewritten_segment = encode_app1_segment(rewritten_payload)
        insertion_offset = exif_app1_insertion_offset(jpeg_data)
        return JpegExifGpsRewriteResult(
            data=jpeg_data[:insertion_offset] + rewritten_segment + jpeg_data[insertion_offset:],
            original_app1_payload_length=0,
            rewritten_app1_payload_length=len(rewritten_payload),
        )
    payload = segment_payload(jpeg_data, segment)
    rewritten_tiff = rewrite_gps_ifd_creating_if_needed(payload[len(EXIF_APP1_PREFIX) :], plan)
    rewritten_payload = EXIF_APP1_PREFIX + rewritten_tiff
    rewritten_segment = encode_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    return JpegExifGpsRewriteResult(
        data=jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:],
        original_app1_payload_length=segment.payload_length,
        rewritten_app1_payload_length=len(rewritten_payload),
    )


def delete_jpeg_exif_gps(jpeg_data: bytes) -> JpegExifGpsRewriteResult:
    segment = find_exif_app1_segment(jpeg_data)
    payload = segment_payload(jpeg_data, segment)
    rewritten_tiff = delete_gps_ifd(payload[len(EXIF_APP1_PREFIX) :])
    rewritten_payload = EXIF_APP1_PREFIX + rewritten_tiff
    rewritten_segment = encode_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    return JpegExifGpsRewriteResult(
        data=jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:],
        original_app1_payload_length=segment.payload_length,
        rewritten_app1_payload_length=len(rewritten_payload),
    )


def rewrite_jpeg_file_existing_exif_gps(
    input_path: Path,
    output_path: Path,
    plan: ExifGpsWritePlan,
) -> JpegExifGpsRewriteResult:
    result = rewrite_jpeg_existing_exif_gps(read_exact_jpeg_rewrite_source(input_path), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegExifGpsRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        transaction=transaction,
    )


def rewrite_jpeg_file_exif_gps_creating_if_needed(
    input_path: Path,
    output_path: Path,
    plan: ExifGpsWritePlan,
) -> JpegExifGpsRewriteResult:
    result = rewrite_jpeg_exif_gps_creating_if_needed(
        read_exact_jpeg_rewrite_source(input_path),
        plan,
    )
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegExifGpsRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        transaction=transaction,
    )


def delete_jpeg_file_exif_gps(
    input_path: Path,
    output_path: Path,
) -> JpegExifGpsRewriteResult:
    result = delete_jpeg_exif_gps(read_exact_jpeg_rewrite_source(input_path))
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegExifGpsRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        transaction=transaction,
    )


def rewrite_jpeg_file_exif_gps_in_place(
    target_path: Path,
    plan: ExifGpsWritePlan,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> JpegExifGpsRewriteResult:
    result = rewrite_jpeg_exif_gps_creating_if_needed(
        read_exact_jpeg_rewrite_source(target_path),
        plan,
    )
    transaction = write_bytes_in_place_transactionally(
        target_path,
        result.data,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return JpegExifGpsRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        transaction=transaction,
    )


def delete_jpeg_file_exif_gps_in_place(
    target_path: Path,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> JpegExifGpsRewriteResult:
    result = delete_jpeg_exif_gps(read_exact_jpeg_rewrite_source(target_path))
    transaction = write_bytes_in_place_transactionally(
        target_path,
        result.data,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return JpegExifGpsRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        transaction=transaction,
    )
