"""JPEG container boundary for Olympus maker-note writes."""

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
from exifmodern.formats.olympus.maker_note import (
    OlympusMacroWritePlan,
    OlympusMakerNoteWritePlan,
    rewrite_olympus_macro_in_tiff,
    rewrite_olympus_maker_notes_in_tiff,
)


@dataclass(frozen=True)
class JpegOlympusMacroRewriteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    changed_olympus_properties: int
    transaction: FileWriteTransactionResult | None = None


@dataclass(frozen=True)
class JpegOlympusMakerNoteRewriteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    changed_olympus_properties: int
    transaction: FileWriteTransactionResult | None = None


def rewrite_jpeg_olympus_macro(
    jpeg_data: bytes,
    plan: OlympusMacroWritePlan,
) -> JpegOlympusMacroRewriteResult:
    segment = find_exif_app1_segment(jpeg_data)
    payload = segment_payload(jpeg_data, segment)
    mutation_result = rewrite_olympus_macro_in_tiff(payload[len(EXIF_APP1_PREFIX) :], plan)
    if not mutation_result.changed:
        return JpegOlympusMacroRewriteResult(
            data=jpeg_data,
            original_app1_payload_length=segment.payload_length,
            rewritten_app1_payload_length=segment.payload_length,
            changed_olympus_properties=0,
        )
    rewritten_payload = EXIF_APP1_PREFIX + mutation_result.data
    rewritten_segment = encode_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    return JpegOlympusMacroRewriteResult(
        data=jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:],
        original_app1_payload_length=segment.payload_length,
        rewritten_app1_payload_length=len(rewritten_payload),
        changed_olympus_properties=1,
    )


def rewrite_jpeg_file_olympus_macro(
    input_path: Path,
    output_path: Path,
    plan: OlympusMacroWritePlan,
) -> JpegOlympusMacroRewriteResult:
    result = rewrite_jpeg_olympus_macro(read_exact_jpeg_rewrite_source(input_path), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegOlympusMacroRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        changed_olympus_properties=result.changed_olympus_properties,
        transaction=transaction,
    )


def rewrite_jpeg_olympus_maker_notes(
    jpeg_data: bytes,
    plan: OlympusMakerNoteWritePlan,
) -> JpegOlympusMakerNoteRewriteResult:
    segment = find_exif_app1_segment(jpeg_data)
    payload = segment_payload(jpeg_data, segment)
    mutation_result = rewrite_olympus_maker_notes_in_tiff(
        payload[len(EXIF_APP1_PREFIX) :],
        plan,
    )
    if mutation_result.changed_step_count == 0:
        return JpegOlympusMakerNoteRewriteResult(
            data=jpeg_data,
            original_app1_payload_length=segment.payload_length,
            rewritten_app1_payload_length=segment.payload_length,
            changed_olympus_properties=0,
        )
    rewritten_payload = EXIF_APP1_PREFIX + mutation_result.data
    rewritten_segment = encode_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    return JpegOlympusMakerNoteRewriteResult(
        data=jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:],
        original_app1_payload_length=segment.payload_length,
        rewritten_app1_payload_length=len(rewritten_payload),
        changed_olympus_properties=mutation_result.changed_step_count,
    )
