"""JPEG XMP group deletion boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.file_transaction import (
    BackupPolicy,
    FileWriteTransactionResult,
    write_bytes_in_place_transactionally,
    write_bytes_transactionally,
)
from exifmodern.formats.jpeg.app_segments.xmp import XMP_APP1_PREFIX
from exifmodern.formats.jpeg.exact_rewrite_io import read_exact_jpeg_rewrite_source
from exifmodern.formats.jpeg.exif_app1 import segment_payload
from exifmodern.formats.jpeg.trailers.afcp_rewrite import adjust_afcp_offsets_after_delete
from exifmodern.formats.jpeg.xmp_app1 import (
    encode_xmp_app1_segment as encode_xmp_app1_segment,
)
from exifmodern.formats.jpeg.xmp_app1 import (
    first_standard_xmp_app1_segment as first_standard_xmp_app1_segment,
)
from exifmodern.formats.jpeg.xmp_app1 import (
    xmp_app1_segments as xmp_app1_segments,
)
from exifmodern.formats.xmp.group_delete import XmpGroupDeletePlan, XmpNamespaceDeletePlan
from exifmodern.formats.xmp.mutation import delete_xmp_namespace


@dataclass(frozen=True)
class JpegXmpGroupDeleteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    deleted_xmp_segments: int
    transaction: FileWriteTransactionResult | None = None


@dataclass(frozen=True)
class JpegXmpNamespaceDeleteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    deleted_xmp_properties: int
    transaction: FileWriteTransactionResult | None = None


@dataclass(frozen=True)
class DeletedJpegRange:
    rewritten_start: int
    length: int


def delete_jpeg_xmp_group(
    jpeg_data: bytes,
    plan: XmpGroupDeletePlan,
) -> JpegXmpGroupDeleteResult:
    if plan.target != "XMP":
        raise ValueError("XMP group delete writer only supports the XMP target.")
    segments = xmp_app1_segments(jpeg_data)
    if not segments:
        return JpegXmpGroupDeleteResult(
            data=jpeg_data,
            original_app1_payload_length=0,
            rewritten_app1_payload_length=0,
            deleted_xmp_segments=0,
        )

    rewritten = bytearray()
    cursor = 0
    deleted_so_far = 0
    deleted_ranges: list[DeletedJpegRange] = []
    original_payload_length = 0
    for segment in segments:
        segment_end = segment.payload_offset + segment.payload_length
        rewritten.extend(jpeg_data[cursor : segment.offset])
        deleted_length = segment_end - segment.offset
        deleted_ranges.append(
            DeletedJpegRange(
                rewritten_start=segment.offset - deleted_so_far,
                length=deleted_length,
            )
        )
        original_payload_length += segment.payload_length
        deleted_so_far += deleted_length
        cursor = segment_end
    rewritten.extend(jpeg_data[cursor:])

    rewritten_data = bytes(rewritten)
    for deleted_range in deleted_ranges:
        rewritten_data = adjust_afcp_offsets_after_delete(
            rewritten_data,
            deleted_range.rewritten_start,
            deleted_range.length,
        )

    return JpegXmpGroupDeleteResult(
        data=rewritten_data,
        original_app1_payload_length=original_payload_length,
        rewritten_app1_payload_length=0,
        deleted_xmp_segments=len(segments),
    )


def delete_jpeg_xmp_namespace(
    jpeg_data: bytes,
    plan: XmpNamespaceDeletePlan,
) -> JpegXmpNamespaceDeleteResult:
    segment = first_standard_xmp_app1_segment(jpeg_data)
    if segment is None:
        return JpegXmpNamespaceDeleteResult(
            data=jpeg_data,
            original_app1_payload_length=0,
            rewritten_app1_payload_length=0,
            deleted_xmp_properties=0,
        )
    payload = segment_payload(jpeg_data, segment)
    mutation_result = delete_xmp_namespace(payload[len(XMP_APP1_PREFIX) :], plan)
    if mutation_result.deleted_properties == 0:
        return JpegXmpNamespaceDeleteResult(
            data=jpeg_data,
            original_app1_payload_length=segment.payload_length,
            rewritten_app1_payload_length=segment.payload_length,
            deleted_xmp_properties=0,
        )
    rewritten_payload = XMP_APP1_PREFIX + mutation_result.packet
    rewritten_segment = encode_xmp_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    return JpegXmpNamespaceDeleteResult(
        data=jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:],
        original_app1_payload_length=segment.payload_length,
        rewritten_app1_payload_length=len(rewritten_payload),
        deleted_xmp_properties=mutation_result.deleted_properties,
    )


def delete_jpeg_file_xmp_group(
    input_path: Path,
    output_path: Path,
    plan: XmpGroupDeletePlan,
) -> JpegXmpGroupDeleteResult:
    result = delete_jpeg_xmp_group(read_exact_jpeg_rewrite_source(input_path), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegXmpGroupDeleteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        deleted_xmp_segments=result.deleted_xmp_segments,
        transaction=transaction,
    )


def delete_jpeg_file_xmp_namespace(
    input_path: Path,
    output_path: Path,
    plan: XmpNamespaceDeletePlan,
) -> JpegXmpNamespaceDeleteResult:
    result = delete_jpeg_xmp_namespace(read_exact_jpeg_rewrite_source(input_path), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegXmpNamespaceDeleteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        deleted_xmp_properties=result.deleted_xmp_properties,
        transaction=transaction,
    )


def delete_jpeg_file_xmp_group_in_place(
    target_path: Path,
    plan: XmpGroupDeletePlan,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> JpegXmpGroupDeleteResult:
    result = delete_jpeg_xmp_group(read_exact_jpeg_rewrite_source(target_path), plan)
    transaction = write_bytes_in_place_transactionally(
        target_path,
        result.data,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return JpegXmpGroupDeleteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        deleted_xmp_segments=result.deleted_xmp_segments,
        transaction=transaction,
    )


def delete_jpeg_file_xmp_namespace_in_place(
    target_path: Path,
    plan: XmpNamespaceDeletePlan,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> JpegXmpNamespaceDeleteResult:
    result = delete_jpeg_xmp_namespace(read_exact_jpeg_rewrite_source(target_path), plan)
    transaction = write_bytes_in_place_transactionally(
        target_path,
        result.data,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return JpegXmpNamespaceDeleteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        deleted_xmp_properties=result.deleted_xmp_properties,
        transaction=transaction,
    )
