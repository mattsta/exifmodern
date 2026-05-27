"""JPEG container boundary for Casio maker-note writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.file_transaction import FileWriteTransactionResult, write_bytes_transactionally
from exifmodern.formats.casio.maker_note import (
    CasioMakerNoteWritePlan,
    rewrite_casio_maker_notes_in_tiff,
)
from exifmodern.formats.jpeg.exact_rewrite_io import read_exact_jpeg_rewrite_source
from exifmodern.formats.jpeg.exif_app1 import (
    EXIF_APP1_PREFIX,
    encode_app1_segment,
    find_exif_app1_segment,
    segment_payload,
)


@dataclass(frozen=True)
class JpegCasioMakerNoteRewriteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    changed_casio_properties: int
    transaction: FileWriteTransactionResult | None = None


def rewrite_jpeg_casio_maker_notes(
    jpeg_data: bytes,
    plan: CasioMakerNoteWritePlan,
) -> JpegCasioMakerNoteRewriteResult:
    segment = find_exif_app1_segment(jpeg_data)
    payload = segment_payload(jpeg_data, segment)
    mutation_result = rewrite_casio_maker_notes_in_tiff(payload[len(EXIF_APP1_PREFIX) :], plan)
    if mutation_result.changed_properties == 0:
        return JpegCasioMakerNoteRewriteResult(
            data=jpeg_data,
            original_app1_payload_length=segment.payload_length,
            rewritten_app1_payload_length=segment.payload_length,
            changed_casio_properties=0,
        )
    rewritten_payload = EXIF_APP1_PREFIX + mutation_result.data
    rewritten_segment = encode_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    return JpegCasioMakerNoteRewriteResult(
        data=jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:],
        original_app1_payload_length=segment.payload_length,
        rewritten_app1_payload_length=len(rewritten_payload),
        changed_casio_properties=mutation_result.changed_properties,
    )


def rewrite_jpeg_file_casio_maker_notes(
    input_path: Path,
    output_path: Path,
    plan: CasioMakerNoteWritePlan,
) -> JpegCasioMakerNoteRewriteResult:
    result = rewrite_jpeg_casio_maker_notes(read_exact_jpeg_rewrite_source(input_path), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegCasioMakerNoteRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        changed_casio_properties=result.changed_casio_properties,
        transaction=transaction,
    )
