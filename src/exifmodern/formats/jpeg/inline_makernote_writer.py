"""JPEG container boundary for inline maker-note scalar writes."""

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
from exifmodern.formats.makernote.inline_ifd import (
    InlineMakerNoteScalarWritePlan,
    InlineMakerNoteStringWritePlan,
    rewrite_inline_maker_note_scalars_in_tiff,
    rewrite_inline_maker_note_strings_in_tiff,
)


@dataclass(frozen=True)
class JpegInlineMakerNoteScalarRewriteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    changed_inline_maker_note_properties: int
    transaction: FileWriteTransactionResult | None = None


@dataclass(frozen=True)
class JpegInlineMakerNoteStringRewriteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    changed_inline_maker_note_properties: int
    transaction: FileWriteTransactionResult | None = None


def rewrite_jpeg_inline_maker_note_scalars(
    jpeg_data: bytes,
    plan: InlineMakerNoteScalarWritePlan,
) -> JpegInlineMakerNoteScalarRewriteResult:
    segment = find_exif_app1_segment(jpeg_data)
    payload = segment_payload(jpeg_data, segment)
    mutation_result = rewrite_inline_maker_note_scalars_in_tiff(
        payload[len(EXIF_APP1_PREFIX) :],
        plan,
    )
    if mutation_result.changed_properties == 0:
        return JpegInlineMakerNoteScalarRewriteResult(
            data=jpeg_data,
            original_app1_payload_length=segment.payload_length,
            rewritten_app1_payload_length=segment.payload_length,
            changed_inline_maker_note_properties=0,
        )
    rewritten_payload = EXIF_APP1_PREFIX + mutation_result.data
    rewritten_segment = encode_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    return JpegInlineMakerNoteScalarRewriteResult(
        data=jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:],
        original_app1_payload_length=segment.payload_length,
        rewritten_app1_payload_length=len(rewritten_payload),
        changed_inline_maker_note_properties=mutation_result.changed_properties,
    )


def rewrite_jpeg_inline_maker_note_strings(
    jpeg_data: bytes,
    plan: InlineMakerNoteStringWritePlan,
) -> JpegInlineMakerNoteStringRewriteResult:
    segment = find_exif_app1_segment(jpeg_data)
    payload = segment_payload(jpeg_data, segment)
    mutation_result = rewrite_inline_maker_note_strings_in_tiff(
        payload[len(EXIF_APP1_PREFIX) :],
        plan,
    )
    if mutation_result.changed_properties == 0:
        return JpegInlineMakerNoteStringRewriteResult(
            data=jpeg_data,
            original_app1_payload_length=segment.payload_length,
            rewritten_app1_payload_length=segment.payload_length,
            changed_inline_maker_note_properties=0,
        )
    rewritten_payload = EXIF_APP1_PREFIX + mutation_result.data
    rewritten_segment = encode_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    return JpegInlineMakerNoteStringRewriteResult(
        data=jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:],
        original_app1_payload_length=segment.payload_length,
        rewritten_app1_payload_length=len(rewritten_payload),
        changed_inline_maker_note_properties=mutation_result.changed_properties,
    )


def rewrite_jpeg_file_inline_maker_note_scalars(
    input_path: Path,
    output_path: Path,
    plan: InlineMakerNoteScalarWritePlan,
) -> JpegInlineMakerNoteScalarRewriteResult:
    result = rewrite_jpeg_inline_maker_note_scalars(
        read_exact_jpeg_rewrite_source(input_path),
        plan,
    )
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegInlineMakerNoteScalarRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        changed_inline_maker_note_properties=result.changed_inline_maker_note_properties,
        transaction=transaction,
    )


def rewrite_jpeg_file_inline_maker_note_strings(
    input_path: Path,
    output_path: Path,
    plan: InlineMakerNoteStringWritePlan,
) -> JpegInlineMakerNoteStringRewriteResult:
    result = rewrite_jpeg_inline_maker_note_strings(
        read_exact_jpeg_rewrite_source(input_path),
        plan,
    )
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegInlineMakerNoteStringRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        changed_inline_maker_note_properties=result.changed_inline_maker_note_properties,
        transaction=transaction,
    )
