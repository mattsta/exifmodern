"""7Z archive transaction planning."""

from pathlib import Path

from exifmodern.dispatch_helpers import build_sevenzip_read_graph
from exifmodern.formats.sevenzip.archive_transaction_plan import (
    build_sevenzip_archive_transaction_plan,
    plan_sevenzip_archive_transaction,
)
from exifmodern.formats.sevenzip.reader_plan import (
    SevenZipReaderDiagnostic,
    SevenZipReaderPlan,
    SevenZipReadTag,
    build_sevenzip_reader_plan,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "SevenZipReadTag",
    "SevenZipReaderDiagnostic",
    "SevenZipReaderPlan",
    "build_sevenzip_archive_transaction_plan",
    "build_sevenzip_reader_plan",
    "invoke_sevenzip",
    "plan_sevenzip_archive_transaction",
]

_SEVENZIP_HEADER_READ_LIMIT = 8 * 1024 * 1024


def invoke_sevenzip(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_bounded_prefix(path, _SEVENZIP_HEADER_READ_LIMIT)
    return build_sevenzip_read_graph(data, source_file)


def _read_bounded_prefix(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        return file.read(byte_count)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="sevenzip",
        builder_ref="exifmodern.formats.sevenzip:invoke_sevenzip",
        patterns=(Pattern(0, b"7z\xbc\xaf'\x1c"),),
    ),
)
