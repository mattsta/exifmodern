"""HTML metadata transaction planning."""

from pathlib import Path

from exifmodern.dispatch_helpers import build_html_read_graph
from exifmodern.formats.html.metadata_transaction_plan import (
    HtmlMetadataTransactionPlan,
    build_html_metadata_transaction_plan,
)
from exifmodern.formats.html.reader_plan import (
    HtmlReaderDiagnostic,
    HtmlReaderPlan,
    HtmlReadTag,
    build_html_reader_plan,
)
from exifmodern.formats.public_payload import (
    oversized_public_payload_graph,
    read_public_document_payload,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, PreprocessKind, Signature

__all__ = [
    "HtmlMetadataTransactionPlan",
    "HtmlReadTag",
    "HtmlReaderDiagnostic",
    "HtmlReaderPlan",
    "build_html_metadata_transaction_plan",
    "build_html_reader_plan",
    "invoke_html",
    "is_html_payload",
]


_HTML_EXTENSIONS = (".htm", ".html", ".xhtml")


def is_html_payload(prefix: bytes, path: Path) -> bool:
    """Structural validator the dispatcher runs after a tentative match.

    Mirrors the legacy `_is_html` content sniffer: a file is HTML if
    its extension is one of the canonical HTML suffixes, OR its
    first 512 bytes (after lstrip + BOM) begin with `<!doctype html`,
    `<html`, or `<?xml` AND contain a `<html` tag. Case-insensitive.

    Used as a `structural_check` on both the magic-byte signature
    (which has a loose `<` pattern that would otherwise match XML/
    plist/SVG) and the extension-only signature.
    """

    if path.suffix.lower() in _HTML_EXTENSIONS:
        return True
    head = prefix[:512].lstrip()
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:].lstrip()
    head_lower = head.lower()
    return head_lower.startswith((b"<!doctype html", b"<html", b"<?xml")) and b"<html" in head_lower


def invoke_html(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = read_public_document_payload(path)
    if data is None:
        return oversized_public_payload_graph(source_file, format_name="HTML")
    return build_html_read_graph(data, source_file)


SIGNATURES: tuple[Signature, ...] = (
    # Magic-byte signature: matches anything starting with `<` after
    # whitespace/BOM stripping. The structural check then confirms it's
    # actually HTML (rejects XML, plist, SVG, etc.).
    Signature(
        format_id="html",
        builder_ref="exifmodern.formats.html:invoke_html",
        patterns=(Pattern(0, b"<"),),
        preprocess=PreprocessKind.LSTRIP_WHITESPACE_AND_BOM,
        structural_check="exifmodern.formats.html:is_html_payload",
    ),
    # Extension-fallback signature: catches `.html`/`.htm`/`.xhtml`
    # files whose content doesn't start with `<` (rare but legal).
    Signature(
        format_id="html/by-ext",
        builder_ref="exifmodern.formats.html:invoke_html",
        patterns=(),
        extensions=_HTML_EXTENSIONS,
        structural_check="exifmodern.formats.html:is_html_payload",
    ),
)
