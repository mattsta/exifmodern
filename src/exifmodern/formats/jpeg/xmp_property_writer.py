"""JPEG XMP property rewrite boundary."""

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
    encode_xmp_app1_segment,
    extended_xmp_app1_segments,
    first_standard_xmp_app1_segment,
    xmp_app1_insertion_offset,
)
from exifmodern.formats.xmp.copy_from_file_plan import XmpDestinationAssignment
from exifmodern.formats.xmp.mutation import (
    apply_xmp_property_write_plan,
    remove_extended_xmp_reference,
)
from exifmodern.formats.xmp.packet import empty_xmp_packet
from exifmodern.formats.xmp.property_write import XmpPropertyWritePlan
from exifmodern.formats.xmp.sidecar_copy_writer import (
    xmp_property_write_plan_from_copy_assignments,
)


@dataclass(frozen=True)
class JpegXmpPropertyRewriteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    changed_xmp_properties: int
    deleted_xmp_properties: int
    transaction: FileWriteTransactionResult | None = None


def rewrite_jpeg_xmp_properties(
    jpeg_data: bytes,
    plan: XmpPropertyWritePlan,
) -> JpegXmpPropertyRewriteResult:
    segment = first_standard_xmp_app1_segment(jpeg_data)
    if segment is None:
        if not plan.steps:
            return JpegXmpPropertyRewriteResult(
                data=jpeg_data,
                original_app1_payload_length=0,
                rewritten_app1_payload_length=0,
                changed_xmp_properties=0,
                deleted_xmp_properties=0,
            )
        raise ValueError("No JPEG XMP APP1 segment found for XMP property write.")

    payload = segment_payload(jpeg_data, segment)
    mutation_result = apply_xmp_property_write_plan(payload[len(XMP_APP1_PREFIX) :], plan)
    if mutation_result.changed_properties == 0 and mutation_result.deleted_properties == 0:
        return JpegXmpPropertyRewriteResult(
            data=jpeg_data,
            original_app1_payload_length=segment.payload_length,
            rewritten_app1_payload_length=segment.payload_length,
            changed_xmp_properties=0,
            deleted_xmp_properties=0,
        )

    cleanup_result = remove_extended_xmp_reference(mutation_result.packet)
    rewritten_payload = XMP_APP1_PREFIX + cleanup_result.packet
    rewritten_segment = encode_xmp_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    rewritten_data = jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:]
    rewritten_data = delete_extended_xmp_segments(rewritten_data)
    return JpegXmpPropertyRewriteResult(
        data=rewritten_data,
        original_app1_payload_length=segment.payload_length,
        rewritten_app1_payload_length=len(rewritten_payload),
        changed_xmp_properties=mutation_result.changed_properties,
        deleted_xmp_properties=(
            mutation_result.deleted_properties + cleanup_result.deleted_properties
        ),
    )


def rewrite_jpeg_xmp_properties_creating_if_needed(
    jpeg_data: bytes,
    plan: XmpPropertyWritePlan,
) -> JpegXmpPropertyRewriteResult:
    segment = first_standard_xmp_app1_segment(jpeg_data)
    if segment is not None:
        return rewrite_jpeg_xmp_properties(jpeg_data, plan)
    if not plan.steps:
        return JpegXmpPropertyRewriteResult(
            data=jpeg_data,
            original_app1_payload_length=0,
            rewritten_app1_payload_length=0,
            changed_xmp_properties=0,
            deleted_xmp_properties=0,
        )
    mutation_result = apply_xmp_property_write_plan(empty_xmp_packet(), plan)
    rewritten_payload = XMP_APP1_PREFIX + mutation_result.packet
    rewritten_segment = encode_xmp_app1_segment(rewritten_payload)
    insertion_offset = xmp_app1_insertion_offset(jpeg_data)
    return JpegXmpPropertyRewriteResult(
        data=jpeg_data[:insertion_offset] + rewritten_segment + jpeg_data[insertion_offset:],
        original_app1_payload_length=0,
        rewritten_app1_payload_length=len(rewritten_payload),
        changed_xmp_properties=mutation_result.changed_properties,
        deleted_xmp_properties=mutation_result.deleted_properties,
    )


def rewrite_jpeg_xmp_copy_assignments_creating_if_needed(
    jpeg_data: bytes,
    assignments: tuple[XmpDestinationAssignment, ...],
) -> JpegXmpPropertyRewriteResult:
    plan = xmp_property_write_plan_from_copy_assignments(assignments)
    return rewrite_jpeg_xmp_properties_creating_if_needed(jpeg_data, plan)


def delete_extended_xmp_segments(jpeg_data: bytes) -> bytes:
    rewritten = jpeg_data
    deleted_so_far = 0
    for segment in extended_xmp_app1_segments(jpeg_data):
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
    return rewritten


def rewrite_jpeg_file_xmp_properties_creating_if_needed(
    input_path: Path,
    output_path: Path,
    plan: XmpPropertyWritePlan,
) -> JpegXmpPropertyRewriteResult:
    result = rewrite_jpeg_xmp_properties_creating_if_needed(
        read_exact_jpeg_rewrite_source(input_path),
        plan,
    )
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegXmpPropertyRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        changed_xmp_properties=result.changed_xmp_properties,
        deleted_xmp_properties=result.deleted_xmp_properties,
        transaction=transaction,
    )


def rewrite_jpeg_file_xmp_properties(
    input_path: Path,
    output_path: Path,
    plan: XmpPropertyWritePlan,
) -> JpegXmpPropertyRewriteResult:
    result = rewrite_jpeg_xmp_properties(read_exact_jpeg_rewrite_source(input_path), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegXmpPropertyRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        changed_xmp_properties=result.changed_xmp_properties,
        deleted_xmp_properties=result.deleted_xmp_properties,
        transaction=transaction,
    )


def rewrite_jpeg_file_xmp_properties_in_place(
    target_path: Path,
    plan: XmpPropertyWritePlan,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> JpegXmpPropertyRewriteResult:
    result = rewrite_jpeg_xmp_properties(read_exact_jpeg_rewrite_source(target_path), plan)
    transaction = write_bytes_in_place_transactionally(
        target_path,
        result.data,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return JpegXmpPropertyRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        changed_xmp_properties=result.changed_xmp_properties,
        deleted_xmp_properties=result.deleted_xmp_properties,
        transaction=transaction,
    )
