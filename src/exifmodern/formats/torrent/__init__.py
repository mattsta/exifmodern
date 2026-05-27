"""BitTorrent bencode metadata transaction planning public API."""

import time
from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.formats.torrent.bencode_transaction_plan import (
    TorrentBencodeTransactionPlan,
    build_torrent_bencode_transaction_plan,
)
from exifmodern.json_types import JsonValue
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = (
    "TorrentBencodeTransactionPlan",
    "build_torrent_bencode_transaction_plan",
    "build_torrent_read_graph",
    "invoke_torrent",
    "is_torrent_prefix",
)

_TORRENT_TABLES = {
    "main": "Image::ExifTool::Torrent::Main",
    "info": "Image::ExifTool::Torrent::Info",
    "files": "Image::ExifTool::Torrent::Files",
    "profiles": "Image::ExifTool::Torrent::Profiles",
}
_FILE_TABLE = "Image::ExifTool::File"
_TORRENT_BENCODE_SCAN_LIMIT = 8 * 1024 * 1024


def is_torrent_prefix(prefix: bytes) -> bool:
    plan = build_torrent_bencode_transaction_plan(prefix)
    return plan.status == "planned"


def build_torrent_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_torrent_bencode_transaction_plan(data)
    diagnostics = [
        f"Torrent package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
        if gate.code != "non_mutating_plan_requires_explicit_emission"
    ]
    tags: list[ReadTag] = []
    if plan.status == "planned":
        for name, value in (
            ("FileType", "Torrent"),
            ("FileTypeExtension", "torrent"),
            ("MIMEType", "application/x-bittorrent"),
        ):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=_provenance(
                        group="File",
                        table_name=_FILE_TABLE,
                        tag_id=name,
                        evidence_ids=plan.evidence_ids,
                    ),
                    schema=None,
                )
            )
    for responsibility in plan.metadata_responsibilities:
        rendered = _render_torrent_value(
            responsibility.generated_name,
            responsibility.value.display_value,
            responsibility.value.raw_bytes,
        )
        tags.append(
            ReadTag(
                name=responsibility.generated_name,
                value=_read_value(rendered),
                provenance=_provenance(
                    group="Torrent",
                    table_name=_TORRENT_TABLES[responsibility.table],
                    tag_id=responsibility.tag_id,
                    evidence_ids=responsibility.evidence_ids,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def _render_torrent_value(
    name: str, value: JsonValue, raw_bytes: bytes | None
) -> str | int | float | bool | None:
    if raw_bytes is not None:
        return f"(Binary data {len(raw_bytes)} bytes, use -b option to extract)"
    if name == "CreateDate" and isinstance(value, int):
        return _render_local_unix_datetime(value)
    if name.startswith("File") and name.endswith("Length") and isinstance(value, int):
        return _render_file_size(value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _render_local_unix_datetime(timestamp: int) -> str:
    local_time = time.localtime(timestamp)
    offset_seconds = -time.altzone if local_time.tm_isdst and time.daylight else -time.timezone
    sign = "+" if offset_seconds >= 0 else "-"
    offset_seconds = abs(offset_seconds)
    offset = f"{sign}{offset_seconds // 3600:02d}:{offset_seconds % 3600 // 60:02d}"
    return time.strftime("%Y:%m:%d %H:%M:%S", local_time) + offset


def _render_file_size(byte_count: int) -> str:
    if byte_count < 1000:
        return f"{byte_count} bytes"
    units = ("kB", "MB", "GB", "TB")
    value = float(byte_count)
    for unit in units:
        value /= 1000.0
        if value < 1000.0:
            return f"{value:.1f} {unit}" if value < 10 else f"{value:.0f} {unit}"
    return f"{value:.0f} PB"


def invoke_torrent(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_torrent_read_graph(
        _read_bounded_prefix(path, _TORRENT_BENCODE_SCAN_LIMIT),
        source_file,
    )


def _read_bounded_prefix(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        return file.read(byte_count)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="torrent",
        builder_ref="exifmodern.formats.torrent:invoke_torrent",
        patterns=(Pattern(0, b"d"),),
        structural_check="exifmodern.formats.torrent:is_torrent_prefix",
        weak=True,
        extensions=(".torrent",),
    ),
)


install_evidence_reference_compat(globals())
