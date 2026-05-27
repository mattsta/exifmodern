"""Reusable file transaction helpers for metadata writes."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type BackupPolicy = Literal["create_backup", "overwrite_original"]


@dataclass(frozen=True)
class FileWriteTransactionResult:
    output_path: str
    bytes_written: int
    replaced_existing: bool
    backup_path: str | None = None
    backup_created: bool = False
    preserve_file_times: bool = False


def write_bytes_transactionally(output_path: Path, data: bytes) -> FileWriteTransactionResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    replaced_existing = output_path.exists()
    temp_path = output_path.with_name(f".{output_path.name}.tmp-{os.getpid()}")
    try:
        write_transaction_temp_file(temp_path, data)
        temp_path.replace(output_path)
        fsync_directory(output_path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return FileWriteTransactionResult(
        output_path=output_path.as_posix(),
        bytes_written=len(data),
        replaced_existing=replaced_existing,
    )


def write_bytes_in_place_transactionally(
    target_path: Path,
    data: bytes,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> FileWriteTransactionResult:
    if not target_path.is_file():
        raise FileNotFoundError(f"Missing in-place write target: {target_path}")
    if not backup_suffix:
        raise ValueError("Backup suffix must not be empty.")

    original_stat = target_path.stat()
    backup_path = Path(f"{target_path}{backup_suffix}")
    temp_path = target_path.with_name(f".{target_path.name}.tmp-{os.getpid()}")
    backup_created = False
    try:
        write_transaction_temp_file(temp_path, data)
        if backup_policy == "create_backup":
            if backup_path.exists():
                raise FileExistsError(f"Backup path already exists: {backup_path}")
            target_path.replace(backup_path)
            backup_created = True
            try:
                temp_path.replace(target_path)
            except OSError:
                backup_path.replace(target_path)
                backup_created = False
                raise
        elif backup_policy == "overwrite_original":
            temp_path.replace(target_path)
        else:
            raise ValueError(f"Unsupported backup policy: {backup_policy}")
        if preserve_file_times:
            os.utime(target_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        fsync_directory(target_path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return FileWriteTransactionResult(
        output_path=target_path.as_posix(),
        bytes_written=len(data),
        replaced_existing=True,
        backup_path=backup_path.as_posix() if backup_policy == "create_backup" else None,
        backup_created=backup_created,
        preserve_file_times=preserve_file_times,
    )


def copy_back_bytes_in_place_transactionally(
    target_path: Path,
    data: bytes,
    *,
    preserve_file_times: bool = False,
) -> FileWriteTransactionResult:
    """Replace file contents through the existing path instead of rename replacement."""
    if not target_path.is_file():
        raise FileNotFoundError(f"Missing in-place write target: {target_path}")

    original_stat = target_path.stat()
    temp_path = target_path.with_name(f".{target_path.name}.tmp-{os.getpid()}")
    rollback_path = target_path.with_name(f".{target_path.name}.rollback-{os.getpid()}")
    try:
        write_transaction_temp_file(temp_path, data)
        shutil.copy2(target_path, rollback_path)
        try:
            with target_path.open("r+b") as handle:
                handle.seek(0)
                with temp_path.open("rb") as source_handle:
                    shutil.copyfileobj(source_handle, handle, length=1024 * 1024)
                handle.truncate()
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            restore_file_from_backup(target_path, rollback_path)
            raise
        if preserve_file_times:
            os.utime(target_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        fsync_directory(target_path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink()
        if rollback_path.exists():
            rollback_path.unlink()
    return FileWriteTransactionResult(
        output_path=target_path.as_posix(),
        bytes_written=len(data),
        replaced_existing=True,
        backup_path=None,
        backup_created=False,
        preserve_file_times=preserve_file_times,
    )


def write_transaction_temp_file(temp_path: Path, data: bytes) -> None:
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with temp_path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def restore_file_from_backup(target_path: Path, backup_path: Path) -> None:
    shutil.copy2(backup_path, target_path)
    fsync_directory(target_path.parent)


def fsync_directory(path: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
