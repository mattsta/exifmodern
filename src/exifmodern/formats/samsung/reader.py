"""Samsung SEFT trailer reader for proven Sound & Shot metadata."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.jpeg.container import exiftool_binary_summary
from exifmodern.json_types import JsonObject

SAMSUNG_SEFT_TRAILER_MARKER = b"SEFT"
SAMSUNG_SEFH_HEADER = b"SEFH"
SAMSUNG_AUDIO_TAG = 0x0100


@dataclass(frozen=True)
class SamsungSeftEntry:
    tag_type: int
    negative_offset: int
    size: int


def parse_samsung_seft_trailer_tags(data: bytes) -> JsonObject:
    directory = samsung_seft_directory(data)
    if directory is None:
        raise ValueError("No Samsung SEFT trailer found")
    directory_offset, directory_data = directory
    entries = samsung_seft_entries(directory_data)
    values: JsonObject = {}
    for entry in entries:
        if entry.tag_type != SAMSUNG_AUDIO_TAG:
            continue
        block_start = directory_offset - entry.negative_offset
        block_end = block_start + entry.size
        if block_start < 0 or block_end > len(data):
            continue
        name, payload = samsung_seft_block(data[block_start:block_end])
        values["EmbeddedAudioFileName"] = name
        values["EmbeddedAudioFile"] = exiftool_binary_summary(len(payload))
        return values
    return values


def samsung_seft_directory(data: bytes) -> tuple[int, bytes] | None:
    position = data.find(SAMSUNG_SEFT_TRAILER_MARKER)
    while position >= 0:
        length_offset = position - 4
        if length_offset >= 0:
            length = int.from_bytes(data[length_offset:position], "little")
            directory_offset = length_offset - length
            directory_end = directory_offset + length
            if (
                directory_offset >= 0
                and directory_end <= len(data)
                and data[directory_offset : directory_offset + 4] == SAMSUNG_SEFH_HEADER
            ):
                return directory_offset, data[directory_offset:directory_end]
        position = data.find(SAMSUNG_SEFT_TRAILER_MARKER, position + 1)
    return None


def samsung_seft_entries(directory_data: bytes) -> list[SamsungSeftEntry]:
    if len(directory_data) < 12:
        return []
    entry_count = int.from_bytes(directory_data[8:12], "little")
    entries: list[SamsungSeftEntry] = []
    for index in range(entry_count):
        entry_offset = 12 + index * 12
        if entry_offset + 12 > len(directory_data):
            break
        entries.append(
            SamsungSeftEntry(
                tag_type=int.from_bytes(
                    directory_data[entry_offset + 2 : entry_offset + 4], "little"
                ),
                negative_offset=int.from_bytes(
                    directory_data[entry_offset + 4 : entry_offset + 8],
                    "little",
                ),
                size=int.from_bytes(directory_data[entry_offset + 8 : entry_offset + 12], "little"),
            )
        )
    return entries


def samsung_seft_block(data: bytes) -> tuple[str, bytes]:
    if len(data) < 8:
        raise ValueError("Truncated Samsung SEFT block")
    name_length = int.from_bytes(data[4:8], "little")
    name_offset = 8
    name_end = name_offset + name_length
    if name_end > len(data):
        raise ValueError("Truncated Samsung SEFT block name")
    return data[name_offset:name_end].decode("utf-8", errors="replace"), data[name_end:]
