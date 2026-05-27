"""WTV metadata transaction planning."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from exifmodern.formats.wtv.metadata_transaction_plan import (
    WtvMetadataTransactionPlan,
    WtvMetadataWriteRequest,
    build_wtv_metadata_transaction_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = [
    "WtvMetadataTransactionPlan",
    "WtvMetadataWriteRequest",
    "build_wtv_metadata_transaction_plan",
    "build_wtv_read_graph",
    "invoke_wtv",
]


_WTV_TABLE = "Image::ExifTool::WTV::Main"
_FILE_TABLE = "Image::ExifTool::File"
_WTV_BOOL_TAGS = frozenset(
    (
        "ATSCContent",
        "ContentProtected",
        "DTVContent",
        "HDContent",
        "MediaIsDelay",
        "MediaIsFinale",
        "MediaIsLive",
        "MediaIsMovie",
        "MediaIsPremiere",
        "MediaIsRepeat",
        "MediaIsSAP",
        "MediaIsSport",
        "MediaIsStereo",
        "MediaIsSubtitled",
        "MediaIsTape",
        "VideoClosedCaptioning",
        "Watched",
    )
)
_WTV_STRING_INT_TAGS = frozenset(("MediaOriginalChannel", "MediaOriginalChannelSubNumber"))
_WTV_SECONDS_100NS_TAGS = frozenset(("Duration", "MediaOriginalRunTime"))
_WTV_FILETIME_TAGS = frozenset(("EncodeTime", "EndTime"))
_WTV_TEXT_DATETIME_TAGS = frozenset(("MediaOriginalBroadcastDateTime", "OriginalReleaseTime"))
_WTV_DEFAULT_UNKNOWN_TAGS = frozenset(
    ("Bitrate", "ExpirationDate", "ExpirationSpan", "MediaThumbTimeStamp")
)


def build_wtv_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate a WTV metadata transaction plan into a ReadGraph."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_wtv_metadata_transaction_plan(data)
    diagnostics = [
        f"WTV package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
        if gate.code != "planner_is_non_mutating"
    ]

    tags: list[ReadTag] = []
    if plan.header_validation.is_valid:
        for name, value in (
            ("FileType", "WTV"),
            ("FileTypeExtension", "wtv"),
            ("MIMEType", "video/x-ms-wtv"),
        ):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=_provenance(
                        group="File",
                        table_name=_FILE_TABLE,
                        tag_id=name,
                        evidence_ids=plan.header_validation.evidence_ids,
                    ),
                    schema=None,
                )
            )
    for index, entry in enumerate(plan.metadata_entries):
        if entry.exiftool_name in _WTV_DEFAULT_UNKNOWN_TAGS:
            continue
        rendered = _render_wtv_value(entry.exiftool_name, entry.value, entry.format_code)
        tags.append(
            ReadTag(
                name=entry.exiftool_name,
                value=_read_value(rendered),
                provenance=_provenance(
                    group="WTV",
                    table_name=_WTV_TABLE,
                    tag_id=entry.tag_key,
                    evidence_ids=entry.evidence_ids,
                    duplicate_instance_ordinal=index,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def _render_wtv_value(name: str, value: str | int | bytes, format_code: int) -> str | int | bytes:
    if isinstance(value, bytes):
        return value
    if name in _WTV_BOOL_TAGS and isinstance(value, int):
        return "Yes" if value else "No"
    if name in _WTV_FILETIME_TAGS and isinstance(value, int):
        return _render_windows_filetime(value)
    if name in _WTV_SECONDS_100NS_TAGS and isinstance(value, int):
        return _render_duration(value / 10_000_000)
    if name in _WTV_TEXT_DATETIME_TAGS and isinstance(value, str):
        if value == "0":
            return 0
        return value.replace("-", ":", 2).replace("T", " ")
    if name in _WTV_STRING_INT_TAGS and isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return value
    if format_code in {0, 3, 4, 6}:
        return value
    return value


def _render_windows_filetime(value: int) -> str:
    seconds = value / 10_000_000 - 719_162 * 24 * 3600
    timestamp = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=round(seconds))
    return timestamp.strftime("%Y:%m:%d %H:%M:%SZ")


def _render_duration(seconds: float) -> str:
    if seconds >= 60:
        total_seconds = int(seconds)
        hours = total_seconds // 3600
        minutes = total_seconds % 3600 // 60
        secs = total_seconds % 60
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{seconds:.2f} s"


def invoke_wtv(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_wtv_read_graph(_read_wtv_exiftool_sectors(path), source_file)


def _read_wtv_exiftool_sectors(path: Path) -> bytes:
    with path.open("rb") as file:
        header = file.read(0x60)
        data = bytearray(header)
        if len(header) < 0x60:
            return bytes(data)
        declared_sector_size = int.from_bytes(header[0x28:0x2C], "little")
        sector_size = declared_sector_size if declared_sector_size in {0x100, 0x1000} else 0x1000
        directory = _read_wtv_sector_table(file, data, header, 0x38, sector_size)
        position = 0
        for _ in range(8192):
            if position + 0x28 >= len(directory):
                break
            if directory[position : position + 16] != bytes.fromhex(
                "92b774915970704488df063b82cc213d"
            ):
                break
            entry_size = int.from_bytes(directory[position + 0x10 : position + 0x14], "little")
            if entry_size <= 0 or position + entry_size > len(directory):
                break
            name_length = int.from_bytes(directory[position + 0x20 : position + 0x24], "little")
            pointer = position + 0x28 + name_length * 2
            if pointer + 8 > position + entry_size:
                break
            flag = int.from_bytes(directory[pointer + 4 : pointer + 8], "little")
            section = _read_wtv_sector_table(
                file, data, directory[pointer : pointer + 4], 0, sector_size
            )
            if flag == 1:
                _read_wtv_sector_table(file, data, section, 0, sector_size)
            position += entry_size
        return bytes(data)


def _read_wtv_sector_table(
    file: BinaryIO,
    data: bytearray,
    sector_table: bytes,
    offset: int,
    sector_size: int,
) -> bytes:
    chunks = bytearray()
    position = offset
    for _ in range(8192):
        if position > len(sector_table) - 4:
            break
        sector_number = int.from_bytes(sector_table[position : position + 4], "little")
        if sector_number in {0, 0xFFFF}:
            break
        file_offset = sector_number * sector_size
        file.seek(file_offset)
        chunk = file.read(sector_size)
        if len(chunk) != sector_size:
            break
        end = file_offset + sector_size
        if len(data) < end:
            data.extend(b"\0" * (end - len(data)))
        data[file_offset:end] = chunk
        chunks.extend(chunk)
        position += 4
    return bytes(chunks)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="wtv",
        builder_ref="exifmodern.formats.wtv:invoke_wtv",
        patterns=(Pattern(0, b"\xb7\xd8\x00\x20\x37\x49\xda\x11\xa6\x4e\x00\x07\xe9\x5e\xad\x8d"),),
    ),
)
