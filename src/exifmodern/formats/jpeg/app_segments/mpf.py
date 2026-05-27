"""JPEG APP2 MPF adapter."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_data, read_jpeg_file
from exifmodern.formats.mpf.reader import (
    MPF_PREFIX,
    MpfGroups,
    parse_mpf_groups,
    read_mpf_image,
    read_mpf_preview_image,
)
from exifmodern.json_types import JsonObject


def read_mpf0_tags(path: Path) -> JsonObject:
    return read_mpf_groups(path)["MPF0"]


def read_mpimage1_tags(path: Path) -> JsonObject:
    return read_mpf_groups(path)["MPImage1"]


def read_mpimage2_tags(path: Path) -> JsonObject:
    return read_mpf_groups(path)["MPImage2"]


def read_mpimage2_preview_image(path: Path) -> bytes:
    return read_mpf_preview_image(read_jpeg_data(path), read_mpf_groups(path)["MPImage2"])


def read_mpimage_image(path: Path, entry_number: int) -> bytes:
    group_name = f"MPImage{entry_number}"
    return read_mpf_image(read_jpeg_data(path), read_mpf_groups(path)[group_name], group_name)


def read_mpimage1_image(path: Path) -> bytes:
    return read_mpimage_image(path, 1)


def read_mpf_groups(path: Path) -> MpfGroups:
    stat = path.stat()
    groups = _read_mpf_groups_cached(str(path), stat.st_size, stat.st_mtime_ns)
    return {group: dict(values) for group, values in groups.items()}


@lru_cache(maxsize=32)
def _read_mpf_groups_cached(path_text: str, size: int, mtime_ns: int) -> MpfGroups:
    _ = (size, mtime_ns)
    path = Path(path_text)
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xE2:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(MPF_PREFIX):
            continue
        tiff_file_offset = segment.payload_offset + len(MPF_PREFIX)
        return parse_mpf_groups(payload, tiff_file_offset)
    raise ValueError(f"No JPEG MPF APP2 segment found: {path}")
