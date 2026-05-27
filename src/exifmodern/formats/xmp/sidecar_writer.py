"""XMP sidecar mutation boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.file_transaction import (
    BackupPolicy,
    FileWriteTransactionResult,
    write_bytes_in_place_transactionally,
    write_bytes_transactionally,
)
from exifmodern.formats.xmp.family2_delete import XmpFamily2DeletePlan
from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan, delete_xmp_family2_groups
from exifmodern.formats.xmp.property_write import XmpPropertyWritePlan


@dataclass(frozen=True)
class XmpSidecarPropertyRewriteResult:
    data: bytes
    changed_xmp_properties: int
    deleted_xmp_properties: int
    transaction: FileWriteTransactionResult | None = None


def rewrite_xmp_sidecar_properties(
    packet: bytes,
    plan: XmpPropertyWritePlan,
) -> XmpSidecarPropertyRewriteResult:
    mutation_result = apply_xmp_property_write_plan(packet, plan)
    return XmpSidecarPropertyRewriteResult(
        data=mutation_result.packet,
        changed_xmp_properties=mutation_result.changed_properties,
        deleted_xmp_properties=mutation_result.deleted_properties,
    )


def rewrite_xmp_sidecar_file_properties(
    input_path: Path,
    output_path: Path,
    plan: XmpPropertyWritePlan,
) -> XmpSidecarPropertyRewriteResult:
    result = rewrite_xmp_sidecar_properties(input_path.read_bytes(), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return XmpSidecarPropertyRewriteResult(
        data=result.data,
        changed_xmp_properties=result.changed_xmp_properties,
        deleted_xmp_properties=result.deleted_xmp_properties,
        transaction=transaction,
    )


def delete_xmp_sidecar_family2_groups(
    packet: bytes,
    plan: XmpFamily2DeletePlan,
) -> XmpSidecarPropertyRewriteResult:
    mutation_result = delete_xmp_family2_groups(packet, plan)
    return XmpSidecarPropertyRewriteResult(
        data=mutation_result.packet,
        changed_xmp_properties=0,
        deleted_xmp_properties=mutation_result.deleted_properties,
    )


def delete_xmp_sidecar_file_family2_groups(
    input_path: Path,
    output_path: Path,
    plan: XmpFamily2DeletePlan,
) -> XmpSidecarPropertyRewriteResult:
    result = delete_xmp_sidecar_family2_groups(input_path.read_bytes(), plan)
    transaction = write_bytes_transactionally(output_path, result.data)
    return XmpSidecarPropertyRewriteResult(
        data=result.data,
        changed_xmp_properties=0,
        deleted_xmp_properties=result.deleted_xmp_properties,
        transaction=transaction,
    )


def rewrite_xmp_sidecar_file_properties_in_place(
    target_path: Path,
    plan: XmpPropertyWritePlan,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> XmpSidecarPropertyRewriteResult:
    result = rewrite_xmp_sidecar_properties(target_path.read_bytes(), plan)
    transaction = write_bytes_in_place_transactionally(
        target_path,
        result.data,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return XmpSidecarPropertyRewriteResult(
        data=result.data,
        changed_xmp_properties=result.changed_xmp_properties,
        deleted_xmp_properties=result.deleted_xmp_properties,
        transaction=transaction,
    )


def delete_xmp_sidecar_file_family2_groups_in_place(
    target_path: Path,
    plan: XmpFamily2DeletePlan,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> XmpSidecarPropertyRewriteResult:
    result = delete_xmp_sidecar_family2_groups(target_path.read_bytes(), plan)
    transaction = write_bytes_in_place_transactionally(
        target_path,
        result.data,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return XmpSidecarPropertyRewriteResult(
        data=result.data,
        changed_xmp_properties=0,
        deleted_xmp_properties=result.deleted_xmp_properties,
        transaction=transaction,
    )
