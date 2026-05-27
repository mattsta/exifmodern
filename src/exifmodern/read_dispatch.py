"""Read-time format dispatch — trie-driven, zero per-format if/elif.

This module reads a file's first ~64KB and hands the prefix to the
signature-trie runtime. The runtime consults the auto-generated
`signature_trie/dispatch_generated.py`, resolves the matching format's
invoker (an `invoke_<name>(path, prefix, source_file)` wrapper exported
by each format module's `__init__.py`), and returns the resulting
`ReadGraph`.

There is no per-format dispatch logic in this file by design. Adding a
new format is a three-step workflow:

  1. In `src/exifmodern/formats/<name>/__init__.py`:
       - Append a `SIGNATURES = (Signature(...),)` tuple naming the
         format's magic bytes.
       - Define `invoke_<name>(path, prefix, source_file) -> ReadGraph`
         that translates the uniform call into whatever the underlying
         reader needs.
  2. Run `uv run exifmodern-signature-trie regenerate` (the pre-commit
     hook installed via `... install` does this automatically when
     SIGNATURES files change).
  3. Commit; CI's `regenerate --check` validates the artifact is in
     sync with the live SIGNATURES exports.

Fallback: when the trie returns None for a buffer (no magic match),
this dispatcher delegates to `build_read_graph` — the JPEG/TIFF
content sniffer that discriminates camera raws by IFD0 inspection.
That fallback is structural, not magic-byte; it has no per-format
if/elif of its own.

The per-format `build_*_read_graph` helpers live in
`exifmodern.dispatch_helpers` (a peer module) so format invokers can
import them at top-level without a circular dependency. The
underscore-prefixed names below are kept as back-compat re-exports
for any external consumer that still imports them from this module.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.signature_trie.runtime import dispatch_via_trie

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadGraphRuntimeOptions

type _DispatchHelperExport = Callable[[bytes, str], ReadGraph]

# NOTE: freshness of `dispatch_generated.py` vs the live SIGNATURES
# exports is enforced at CI time by
# `tests/test_signature_trie_runtime.py::test_fresh_after_regenerate`
# and by the pre-commit hook installed via `exifmodern-signature-trie
# install`. We deliberately do NOT call `assert_fresh()` here — every
# importer would pay a ~50ms tax on every cold start, and at any
# realistic install base that's wasted millions of CPU-seconds for a
# property already guaranteed by the build.

__all__ = [  # noqa: F822 - underscore helper exports are resolved by __getattr__.
    "EXIFTOOL_MAGIC_PROBE_BYTES",
    "MEDIA_HEADER_PROBE_BYTES",
    "RIFF_SIGNATURES",
    "_build_dpx_read_graph",
    "_build_fits_read_graph",
    "_build_flac_read_graph",
    "_build_gif_read_graph",
    "_build_html_read_graph",
    "_build_json_read_graph",
    "_build_pdf_read_graph",
    "_build_sevenzip_read_graph",
    "_build_zip_read_graph",
    "build_dispatched_read_graph",
]

# Number of header bytes handed to the signature-trie. The trie itself
# only inspects the first ~64 bytes for any registered format; the
# extra capacity covers structural-check predicates that need more.
MEDIA_HEADER_PROBE_BYTES = 65536

# Legacy probe-size constant kept exported for any external consumer
# that referenced it. New code should use MEDIA_HEADER_PROBE_BYTES.
EXIFTOOL_MAGIC_PROBE_BYTES = 1024

# Back-compat re-export. The authoritative source of every format's
# magic bytes is the SIGNATURES tuple in that format's `__init__.py`;
# this constant is kept only for one external consumer
# (exifmodern.public_api.models). New code should consult the
# signature-trie registry, not these constants.
RIFF_SIGNATURES = (b"RIFF", b"RF64")

_LAZY_DISPATCH_HELPER_EXPORTS = {
    "_build_dpx_read_graph": "build_dpx_read_graph",
    "_build_fits_read_graph": "build_fits_read_graph",
    "_build_flac_read_graph": "build_flac_read_graph",
    "_build_gif_read_graph": "build_gif_read_graph",
    "_build_html_read_graph": "build_html_read_graph",
    "_build_json_read_graph": "build_json_read_graph",
    "_build_pdf_read_graph": "build_pdf_read_graph",
    "_build_sevenzip_read_graph": "build_sevenzip_read_graph",
    "_build_zip_read_graph": "build_zip_read_graph",
}


def __getattr__(name: str) -> _DispatchHelperExport:
    import exifmodern.dispatch_helpers as dispatch_helpers

    if name == "_build_dpx_read_graph":
        helper = dispatch_helpers.build_dpx_read_graph
    elif name == "_build_fits_read_graph":
        helper = dispatch_helpers.build_fits_read_graph
    elif name == "_build_flac_read_graph":
        helper = dispatch_helpers.build_flac_read_graph
    elif name == "_build_gif_read_graph":
        helper = dispatch_helpers.build_gif_read_graph
    elif name == "_build_html_read_graph":
        helper = dispatch_helpers.build_html_read_graph
    elif name == "_build_json_read_graph":
        helper = dispatch_helpers.build_json_read_graph
    elif name == "_build_pdf_read_graph":
        helper = dispatch_helpers.build_pdf_read_graph
    elif name == "_build_sevenzip_read_graph":
        helper = dispatch_helpers.build_sevenzip_read_graph
    elif name == "_build_zip_read_graph":
        helper = dispatch_helpers.build_zip_read_graph
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = helper
    return helper


def build_dispatched_read_graph(
    path: Path,
    *,
    display_path: str | None = None,
    runtime_options: ReadGraphRuntimeOptions | None = None,
) -> ReadGraph:
    """Dispatch a file to its format reader via the signature trie.

    Reads the file's first MEDIA_HEADER_PROBE_BYTES, asks the trie,
    invokes the matching format's reader. Falls through to the
    JPEG/TIFF structural sniffer when the trie has no match.
    """

    from exifmodern.read_graph import (
        ReadGraphRuntimeOptions,
        build_read_graph,
        reset_dispatch_read_graph_runtime_options,
        set_dispatch_read_graph_runtime_options,
    )

    source_file = display_path if display_path is not None else path.as_posix()
    effective_runtime_options = (
        runtime_options if runtime_options is not None else ReadGraphRuntimeOptions()
    )
    token = set_dispatch_read_graph_runtime_options(effective_runtime_options)
    try:
        prefix = _read_prefix(path, MEDIA_HEADER_PROBE_BYTES)
        result = dispatch_via_trie(prefix, path, source_file)
        if result is not None:
            return result
        fallback = _build_source_backed_fallback_read_graph(path, prefix, source_file)
        if fallback is not None:
            return fallback
        return build_read_graph(
            path,
            display_path=source_file,
            runtime_options=effective_runtime_options,
        )
    finally:
        reset_dispatch_read_graph_runtime_options(token)


def _read_prefix(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        return file.read(byte_count)


def _build_source_backed_fallback_read_graph(
    path: Path,
    prefix: bytes,
    source_file: str,
) -> ReadGraph | None:
    suffix = path.suffix.lower()
    if suffix == ".dng" and prefix[:2] in {b"II", b"MM"}:
        from exifmodern.formats.dng import build_dng_read_graph_from_file

        return build_dng_read_graph_from_file(path, source_file=source_file)
    if suffix in {".txt", ".csv"}:
        from exifmodern.formats.text import build_text_read_graph_from_file

        return build_text_read_graph_from_file(path, source_file=source_file)
    return None
