"""JPEG writer for composed Geotag effects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.file_transaction import (
    BackupPolicy,
    FileWriteTransactionResult,
    write_bytes_in_place_transactionally,
    write_bytes_transactionally,
)
from exifmodern.formats.geotag.write_effects import GeotagWriteEffects
from exifmodern.formats.jpeg.exact_rewrite_io import read_exact_jpeg_rewrite_source
from exifmodern.formats.jpeg.exif_gps_writer import rewrite_jpeg_exif_gps_creating_if_needed
from exifmodern.formats.jpeg.exif_scalar_writer import rewrite_jpeg_exif_scalars_creating_if_needed


@dataclass(frozen=True)
class JpegGeotagRewriteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    gps_applied: bool
    exif_scalar_applied: bool
    transaction: FileWriteTransactionResult | None = None


def rewrite_jpeg_geotag_effects(
    jpeg_data: bytes,
    effects: GeotagWriteEffects,
) -> JpegGeotagRewriteResult:
    data = jpeg_data
    original_app1_payload_length = 0
    rewritten_app1_payload_length = 0
    gps_applied = False
    exif_scalar_applied = False
    if effects.gps_write_plan is not None:
        gps_result = rewrite_jpeg_exif_gps_creating_if_needed(data, effects.gps_write_plan)
        data = gps_result.data
        original_app1_payload_length = gps_result.original_app1_payload_length
        rewritten_app1_payload_length = gps_result.rewritten_app1_payload_length
        gps_applied = True
    if effects.exif_scalar_write_plan is not None:
        scalar_result = rewrite_jpeg_exif_scalars_creating_if_needed(
            data,
            effects.exif_scalar_write_plan,
        )
        data = scalar_result.data
        if not gps_applied:
            original_app1_payload_length = scalar_result.original_app1_payload_length
        rewritten_app1_payload_length = scalar_result.rewritten_app1_payload_length
        exif_scalar_applied = True
    return JpegGeotagRewriteResult(
        data=data,
        original_app1_payload_length=original_app1_payload_length,
        rewritten_app1_payload_length=rewritten_app1_payload_length,
        gps_applied=gps_applied,
        exif_scalar_applied=exif_scalar_applied,
    )


def rewrite_jpeg_file_geotag_effects(
    input_path: Path,
    output_path: Path,
    effects: GeotagWriteEffects,
) -> JpegGeotagRewriteResult:
    result = rewrite_jpeg_geotag_effects(read_exact_jpeg_rewrite_source(input_path), effects)
    transaction = write_bytes_transactionally(output_path, result.data)
    return JpegGeotagRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        gps_applied=result.gps_applied,
        exif_scalar_applied=result.exif_scalar_applied,
        transaction=transaction,
    )


def rewrite_jpeg_file_geotag_effects_in_place(
    target_path: Path,
    effects: GeotagWriteEffects,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> JpegGeotagRewriteResult:
    result = rewrite_jpeg_geotag_effects(read_exact_jpeg_rewrite_source(target_path), effects)
    transaction = write_bytes_in_place_transactionally(
        target_path,
        result.data,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return JpegGeotagRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        gps_applied=result.gps_applied,
        exif_scalar_applied=result.exif_scalar_applied,
        transaction=transaction,
    )
