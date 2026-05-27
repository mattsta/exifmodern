"""JSON metadata transaction planning public API."""

from pathlib import Path

from exifmodern.dispatch_helpers import build_json_read_graph
from exifmodern.formats.json.metadata_transaction_plan import (
    JsonMetadataTransactionPlan,
    build_json_metadata_transaction_plan,
)
from exifmodern.formats.json.reader_plan import (
    JsonReaderDiagnostic,
    JsonReaderPlan,
    JsonReadTag,
    build_json_reader_plan,
)
from exifmodern.formats.public_payload import (
    oversized_public_payload_graph,
    read_public_document_payload,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, PreprocessKind, Signature

__all__ = (
    "JsonMetadataTransactionPlan",
    "JsonReadTag",
    "JsonReaderDiagnostic",
    "JsonReaderPlan",
    "build_json_metadata_transaction_plan",
    "build_json_reader_plan",
    "invoke_json",
    "is_json_payload",
)


def is_json_payload(prefix: bytes, path: Path) -> bool:
    """Structural validator the dispatcher runs after a tentative match.

    Mirrors the legacy `_is_json` content sniffer: a `.json` extension
    is sufficient by itself, otherwise the first 512 bytes (after
    lstrip + optional UTF-8 BOM) must start with `{` or `[`.
    """

    if path.suffix.lower() == ".json":
        return True
    head = prefix[:512].lstrip()
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:].lstrip()
    return head.startswith((b"{", b"["))


def invoke_json(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = read_public_document_payload(path)
    if data is None:
        return oversized_public_payload_graph(source_file, format_name="JSON")
    return build_json_read_graph(data, source_file)


SIGNATURES: tuple[Signature, ...] = (
    # Magic-byte signatures: object or array prefix after whitespace/BOM
    # stripping. The structural check rejects bytes that happen to start
    # with `{` or `[` but aren't actually JSON.
    Signature(
        format_id="json",
        builder_ref="exifmodern.formats.json:invoke_json",
        patterns=(Pattern(0, b"{"),),
        preprocess=PreprocessKind.LSTRIP_WHITESPACE_AND_BOM,
        structural_check="exifmodern.formats.json:is_json_payload",
    ),
    Signature(
        format_id="json/array",
        builder_ref="exifmodern.formats.json:invoke_json",
        patterns=(Pattern(0, b"["),),
        preprocess=PreprocessKind.LSTRIP_WHITESPACE_AND_BOM,
        structural_check="exifmodern.formats.json:is_json_payload",
    ),
    # Extension fallback: `.json` files whose content was unusual
    # enough to miss the magic-byte path.
    Signature(
        format_id="json/by-ext",
        builder_ref="exifmodern.formats.json:invoke_json",
        patterns=(),
        extensions=(".json",),
        structural_check="exifmodern.formats.json:is_json_payload",
    ),
)
