"""Package-local EXIF sidecar tagsFromFile copy writer."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from exifmodern.file_transaction import (
    BackupPolicy,
    FileWriteTransactionResult,
    write_bytes_in_place_transactionally,
    write_bytes_transactionally,
)
from exifmodern.formats.exif_sidecar.copy_from_file_plan import (
    ExifSidecarCopyDiagnostic,
    ExifSidecarCopyFromFilePlan,
    materialize_exif_sidecar_copy_from_file_plan,
)


@dataclass(frozen=True)
class ExifSidecarCopyRewriteResult:
    data: bytes
    changed: bool
    copied_exif_bytes: int
    diagnostic_count: int
    diagnostics: tuple[ExifSidecarCopyDiagnostic, ...]
    transaction: FileWriteTransactionResult | None = None


@dataclass(frozen=True)
class ExifSidecarCopyFromFileExecutionRequest:
    source_path: Path
    output_path: Path
    copy_plan: ExifSidecarCopyFromFilePlan
    backup_policy: BackupPolicy = "overwrite_original"
    backup_suffix: str = "_original"


@dataclass(frozen=True)
class GoldenWriteModernExifSidecarCopyRunResult:
    request_id: str
    status: str
    copied_exif_bytes: int


def rewrite_exif_sidecar_copy_from_file(
    source_path: Path,
    copy_plan: ExifSidecarCopyFromFilePlan,
) -> ExifSidecarCopyRewriteResult:
    materialized = materialize_exif_sidecar_copy_from_file_plan(copy_plan, source_path)
    diagnostics = materialized.diagnostics
    if diagnostics:
        return ExifSidecarCopyRewriteResult(
            data=b"",
            changed=False,
            copied_exif_bytes=0,
            diagnostic_count=len(diagnostics),
            diagnostics=diagnostics,
        )
    return ExifSidecarCopyRewriteResult(
        data=materialized.data,
        changed=True,
        copied_exif_bytes=len(materialized.data),
        diagnostic_count=0,
        diagnostics=(),
    )


def rewrite_exif_sidecar_copy_from_file_to_path(
    source_path: Path,
    output_path: Path,
    copy_plan: ExifSidecarCopyFromFilePlan,
    backup_policy: BackupPolicy = "overwrite_original",
    backup_suffix: str = "_original",
) -> ExifSidecarCopyRewriteResult:
    result = rewrite_exif_sidecar_copy_from_file(source_path, copy_plan)
    if result.diagnostics:
        return result
    if backup_policy == "create_backup" and output_path.exists():
        transaction = write_bytes_in_place_transactionally(
            output_path,
            result.data,
            backup_policy,
            backup_suffix,
        )
    else:
        transaction = write_bytes_transactionally(output_path, result.data)
    return ExifSidecarCopyRewriteResult(
        data=result.data,
        changed=result.changed,
        copied_exif_bytes=result.copied_exif_bytes,
        diagnostic_count=result.diagnostic_count,
        diagnostics=result.diagnostics,
        transaction=transaction,
    )


def execute_exif_sidecar_copy_from_file_request(
    request: ExifSidecarCopyFromFileExecutionRequest,
) -> ExifSidecarCopyRewriteResult:
    return rewrite_exif_sidecar_copy_from_file_to_path(
        request.source_path,
        request.output_path,
        request.copy_plan,
        request.backup_policy,
        request.backup_suffix,
    )


def run_golden_write_modern_exif_sidecar_copy_from_file_request(
    exiftool_root: Path,
    request_path: Path,
    output_dir: Path,
) -> GoldenWriteModernExifSidecarCopyRunResult:
    module = import_module(
        "exifmodern.oracle_parity.golden_write_modern.exif_sidecar",
    )
    run_request = module.run_golden_write_modern_exif_sidecar_copy_from_file_request
    result: GoldenWriteModernExifSidecarCopyRunResult = run_request(
        exiftool_root,
        request_path,
        output_dir,
    )

    return GoldenWriteModernExifSidecarCopyRunResult(
        request_id=result.request_id,
        status=result.status,
        copied_exif_bytes=result.copied_exif_bytes,
    )
