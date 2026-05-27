"""Range-backed byte access for media readers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

type ByteOffset = int
type ByteCount = int


@dataclass(frozen=True)
class MediaSourceSnapshot:
    path: Path
    size: int
    mtime_ns: int


class FileMediaSource:
    """Small reusable range reader for runtime metadata extraction."""

    def __init__(self, path: Path) -> None:
        self._path = path
        stat = path.stat()
        self._snapshot = MediaSourceSnapshot(
            path=path,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )
        self._prefix_cache: dict[ByteCount, bytes] = {}
        self._tail_cache: dict[ByteCount, bytes] = {}

    @property
    def path(self) -> Path:
        return self._path

    @property
    def snapshot(self) -> MediaSourceSnapshot:
        return self._snapshot

    @property
    def size(self) -> int:
        return self._snapshot.size

    @property
    def mtime_ns(self) -> int:
        return self._snapshot.mtime_ns

    def open(self) -> BinaryIO:
        return self._path.open("rb")

    def prefix(self, max_bytes: ByteCount) -> bytes:
        checked_size = checked_byte_count(max_bytes, "max_bytes")
        cached = self._prefix_cache.get(checked_size)
        if cached is not None:
            return cached
        data = self.read_at(0, min(self.size, checked_size))
        self._prefix_cache[checked_size] = data
        return data

    def tail(self, max_bytes: ByteCount) -> bytes:
        checked_size = checked_byte_count(max_bytes, "max_bytes")
        cached = self._tail_cache.get(checked_size)
        if cached is not None:
            return cached
        read_size = min(self.size, checked_size)
        data = self.read_at(self.size - read_size, read_size)
        self._tail_cache[checked_size] = data
        return data

    def read_at(self, offset: ByteOffset, byte_count: ByteCount) -> bytes:
        checked_offset = checked_byte_offset(offset)
        checked_count = checked_byte_count(byte_count, "byte_count")
        if checked_offset > self.size:
            return b""
        read_size = min(checked_count, self.size - checked_offset)
        with self.open() as file:
            file.seek(checked_offset)
            return file.read(read_size)

    def read_full(self) -> bytes:
        return self.read_at(0, self.size)

    def cache_state(self) -> Mapping[str, tuple[int, ...]]:
        return {
            "prefix_lengths": tuple(sorted(self._prefix_cache)),
            "tail_lengths": tuple(sorted(self._tail_cache)),
        }


def checked_byte_offset(offset: int) -> ByteOffset:
    if offset < 0:
        raise ValueError("byte offset must be non-negative")
    return offset


def checked_byte_count(byte_count: int, name: str) -> ByteCount:
    if byte_count < 0:
        raise ValueError(f"{name} must be non-negative")
    return byte_count
