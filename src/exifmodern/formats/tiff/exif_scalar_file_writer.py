"""TIFF-file EXIF scalar mutation boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.exif_scalar_write_plan import ExifScalarWritePlan
from exifmodern.file_transaction import FileWriteTransactionResult, write_bytes_transactionally
from exifmodern.formats.tiff.exif_scalar_rewriter import rewrite_exif_scalars_creating_if_needed


@dataclass(frozen=True)
class TiffExifScalarRewriteResult:
    data: bytes
    original_size: int
    rewritten_size: int
    transaction: FileWriteTransactionResult | None = None


def rewrite_tiff_exif_scalars_creating_if_needed(
    tiff_data: bytes,
    plan: ExifScalarWritePlan,
) -> TiffExifScalarRewriteResult:
    rewritten = rewrite_exif_scalars_creating_if_needed(tiff_data, plan)
    return TiffExifScalarRewriteResult(
        data=rewritten,
        original_size=len(tiff_data),
        rewritten_size=len(rewritten),
    )


def rewrite_tiff_file_exif_scalars_creating_if_needed(
    input_path: Path,
    output_path: Path,
    plan: ExifScalarWritePlan,
) -> TiffExifScalarRewriteResult:
    result = rewrite_tiff_exif_scalars_creating_if_needed(input_path.read_bytes(), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return TiffExifScalarRewriteResult(
        data=result.data,
        original_size=result.original_size,
        rewritten_size=result.rewritten_size,
        transaction=transaction,
    )
