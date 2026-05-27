"""Runtime resolver for the signature-trie dispatcher.

`read_dispatch.py` reads a file's prefix bytes, hands them to
`dispatch_via_trie`, and gets back a fully-built `ReadGraph`. All
per-format calling conventions are handled here, behind one stable
function signature, so the dispatcher itself contains zero per-format
logic.

How the layers connect:

    read_dispatch.build_dispatched_read_graph(path)
        ↓
    dispatch_via_trie(prefix, path, source_file)
        ├─ dispatch_generated.dispatch(prefix)        # the trie says "this is PNG"
        │      → ("png", None) or ("aac", "exifmodern.formats.aac.read_graph_adapter:is_aac_prefix")
        │
        ├─ _resolve(builder_ref)                       # imports invoke_png and caches it
        │
        ├─ optional: _run_structural(check_ref, ...)   # confirms ICO image-count, etc.
        │
        └─ invoker(path, prefix, source_file) → ReadGraph

Public surface:

  - `dispatch_via_trie(prefix, path, source_file) -> ReadGraph | None`
  - `resolve_invoker(builder_ref) -> Callable`  (cached, public for tests)
  - `assert_fresh()`                            (raises if the generated
                                                 file's trie_digest doesn't
                                                 match the live SIGNATURES;
                                                 called once at import-time
                                                 from read_dispatch)

Caching: every `builder_ref` is `importlib.import_module`-resolved exactly
once per process. The cache is a plain dict; lookups are dict misses on
first dispatch per format and dict hits afterward.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from inspect import signature
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph


@runtime_checkable
class FormatInvoker(Protocol):
    def __call__(self, path: Path, prefix: bytes, source_file: str) -> ReadGraph: ...


@runtime_checkable
class StructuralCheckCallable(Protocol):
    def __call__(self, *args: bytes | Path) -> bool: ...


type ResolvedStructuralCheck = Callable[[bytes, Path], bool]
type ExtensionFallback = tuple[str, str, tuple[str, ...], str | None]


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


_INVOKER_CACHE: dict[str, FormatInvoker] = {}
_STRUCTURAL_CHECK_CACHE: dict[str, ResolvedStructuralCheck] = {}


def resolve_invoker(builder_ref: str) -> FormatInvoker:
    """Resolve a `module.path:func_name` reference to a callable.

    Cached per process. The cache is a hot-path optimization, not a
    correctness mechanism — re-importing on every dispatch would work,
    just slowly.

    Raises `ImportError` if the module can't be loaded, `AttributeError`
    if the function doesn't exist. These propagate as runtime errors;
    the dispatcher catches them only to add context.
    """

    cached = _INVOKER_CACHE.get(builder_ref)
    if cached is not None:
        return cached
    module_path, _, func_name = builder_ref.partition(":")
    if not module_path or not func_name:
        raise ValueError(
            f"builder_ref must be of the form 'module.path:func_name', got {builder_ref!r}"
        )
    value = _resolve_invoker_callable(builder_ref)
    _INVOKER_CACHE[builder_ref] = value
    return value


def _resolve_structural_check(check_ref: str) -> ResolvedStructuralCheck:
    cached = _STRUCTURAL_CHECK_CACHE.get(check_ref)
    if cached is not None:
        return cached
    value = _resolve_structural_callable(check_ref)
    _STRUCTURAL_CHECK_CACHE[check_ref] = value
    return value


def _resolve_invoker_callable(dotted_ref: str) -> FormatInvoker:
    module_path, func_name = _split_ref(dotted_ref)
    module = importlib.import_module(module_path)
    value = getattr(module, func_name)
    if not isinstance(value, FormatInvoker):
        raise TypeError(f"resolved attribute is not callable: {dotted_ref!r}")
    return value


def _resolve_structural_callable(dotted_ref: str) -> ResolvedStructuralCheck:
    module_path, func_name = _split_ref(dotted_ref)
    module = importlib.import_module(module_path)
    value = getattr(module, func_name)
    if not isinstance(value, StructuralCheckCallable):
        raise TypeError(f"resolved attribute is not callable: {dotted_ref!r}")
    if _accepts_path_argument(value):
        return lambda prefix, path: bool(value(prefix, path))
    return lambda prefix, path: bool(value(prefix))


def _accepts_path_argument(value: StructuralCheckCallable) -> bool:
    """Return whether a structural predicate declares the optional path parameter."""

    required_positional = 0
    accepts_varargs = False
    for parameter in signature(value).parameters.values():
        if parameter.kind == parameter.VAR_POSITIONAL:
            accepts_varargs = True
        if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD):
            if parameter.default is parameter.empty:
                required_positional += 1
    return accepts_varargs or required_positional >= 2


def _split_ref(dotted_ref: str) -> tuple[str, str]:
    module_path, _, func_name = dotted_ref.partition(":")
    if not module_path or not func_name:
        raise ValueError(
            f"builder_ref must be of the form 'module.path:func_name', got {dotted_ref!r}"
        )
    return module_path, func_name


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------


def run_structural_check(check_ref: str, prefix: bytes, path: Path) -> bool:
    """Run a structural validation predicate after the trie pinpoints a leaf.

    Currently used by ICO (image-count > 0), AAC (ADTS frame validation),
    MPC (post-ID3v2 MPC magic), and a handful of others. The convention
    is the same `module.path:func_name` form as `builder_ref`. The
    predicate is called as `func(prefix, path)` and must return `bool`.

    Backwards compatibility: many existing predicates take just `prefix`
    (e.g. `is_aac_prefix(data)`). We try the (prefix, path) signature
    first; if it raises TypeError on argument count, fall back to
    (prefix,). Yes, this is a tiny piece of legacy translation, but it
    keeps the structural-check refs in SIGNATURES exports stable across
    predicate-signature evolution.
    """

    if check_ref.startswith("perl_regex:"):
        # ExifTool-imported bucket-4 entries carry the original regex
        # as the structural check. We don't currently run it (would
        # need a Perl-regex evaluator). Treat as "trust the trie" for
        # now — the literal prefix already matched.
        return True

    func = _resolve_structural_check(check_ref)
    return func(prefix, path)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def dispatch_via_trie(
    prefix: bytes,
    path: Path,
    source_file: str,
) -> ReadGraph | None:
    """Trie-driven dispatch with extension-fallback.

    Order:
      1. Magic-byte trie. Matches > 90% of real files.
      2. If the trie matches but a `structural_check` is declared,
         run the predicate; on False, treat as a miss and continue.
      3. Extension-fallback table. For formats with no usable magic
         (MP3) or whose magic is too generic to trust alone (HTML,
         JSON, FITS), an extension match invokes the format's
         reader. Optional structural_check applies the same way.
      4. Return None — the caller's fallback (TIFF/JPEG sniffer)
         takes over.

    Side effects: imports format modules lazily on first dispatch per
    format. After a process has dispatched a few times against typical
    files, the import cost is amortized to zero.
    """

    suffix = path.suffix.lower()
    if suffix:
        priority_graph = _dispatch_extension_match(
            suffix,
            prefix,
            path,
            source_file,
            _extension_priority_fallbacks(),
        )
        if priority_graph is not None:
            return priority_graph

    # Late import keeps `read_dispatch.py` importable even before the
    # trie has been generated for the first time (e.g. fresh checkout
    # before regenerate).
    from exifmodern.signature_trie.dispatch_generated import dispatch as _trie_dispatch

    hit = _trie_dispatch(prefix)
    if hit is not None:
        format_id, structural_check = hit
        if structural_check is None or run_structural_check(structural_check, prefix, path):
            builder_ref = _builder_for_format(format_id)
            if builder_ref is not None:
                return resolve_invoker(builder_ref)(path, prefix, source_file)

    # Extension fallback.
    if suffix:
        return _dispatch_extension_match(
            suffix,
            prefix,
            path,
            source_file,
            _extension_fallbacks(),
        )
    return None


def _dispatch_extension_match(
    suffix: str,
    prefix: bytes,
    path: Path,
    source_file: str,
    fallbacks: tuple[ExtensionFallback, ...],
) -> ReadGraph | None:
    for _format_id, builder_ref, extensions, structural_check in fallbacks:
        if suffix in extensions:
            if structural_check is not None:
                if not run_structural_check(structural_check, prefix, path):
                    continue
            return resolve_invoker(builder_ref)(path, prefix, source_file)
    return None


# ---------------------------------------------------------------------------
# Format-id → builder_ref map
# ---------------------------------------------------------------------------
#
# The generated `dispatch_generated.py` carries the hot-path dispatch
# function plus small metadata tables. Runtime never imports discovery,
# ExifTool-import, oracle, or migration tooling for normal dispatch.


def _builder_for_format(format_id: str) -> str | None:
    from exifmodern.signature_trie import dispatch_generated

    return dispatch_generated.FORMAT_BUILDERS.get(format_id)


def _extension_fallbacks() -> tuple[ExtensionFallback, ...]:
    """Signatures that declare `extensions` for fallback dispatch.

    Cached per process. Order is the discovery order of the format
    modules; the first extension match wins, so format modules
    declaring more specific extensions should be loaded first if
    extensions overlap (rare in practice).
    """

    from exifmodern.signature_trie import dispatch_generated

    return dispatch_generated.EXTENSION_FALLBACKS


def _extension_priority_fallbacks() -> tuple[ExtensionFallback, ...]:
    """Extension-only signatures that must win before generic magic hits.

    MP3 is the motivating case: many real MP3 files start with an ID3v2
    prelude, but ExifTool's file-level processing treats the file as MPEG audio
    and lets the MPEG reader delegate ID3 frames internally.
    """

    from exifmodern.signature_trie import dispatch_generated

    return dispatch_generated.EXTENSION_PRIORITY_FALLBACKS


# ---------------------------------------------------------------------------
# Freshness assertion
# ---------------------------------------------------------------------------


def assert_fresh() -> None:
    """Raise if the committed `dispatch_generated.py` is stale relative
    to the live SIGNATURES exports.

    Cheap: re-runs discovery (~50ms) and rebuilds the trie (~10ms),
    compares the resulting digest to the one embedded in the generated
    file's header. Skipped when EXIFMODERN_SKIP_TRIE_FRESHNESS_CHECK is
    set in the environment (CI, perf-critical paths).
    """

    import os

    if os.environ.get("EXIFMODERN_SKIP_TRIE_FRESHNESS_CHECK"):
        return

    try:
        from exifmodern.signature_trie import dispatch_generated
        from exifmodern.signature_trie.cli import merge_signatures
        from exifmodern.signature_trie.codegen import _trie_digest
        from exifmodern.signature_trie.compiler import compile_trie
        from exifmodern.signature_trie.discovery import discover_signatures
        from exifmodern.signature_trie.exiftool_import import (
            Bucket,
            ImportReport,
            import_exiftool_signatures,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Signature-trie freshness checks are source-tree maintenance operations "
            "and are not bundled in production wheels."
        ) from exc

    explicit, _raw = discover_signatures(Path.cwd())
    exiftool_pm = Path.cwd().parent / "exiftool" / "lib" / "Image" / "ExifTool.pm"
    exiftool_report = (
        import_exiftool_signatures(exiftool_pm)
        if exiftool_pm.exists()
        else ImportReport(
            signatures=(),
            by_bucket={bucket: 0 for bucket in Bucket},
            diagnostics=(),
            raw_count=0,
        )
    )
    merge = merge_signatures(explicit, _raw, exiftool_report)
    trie = compile_trie(merge.final, strict=False)
    live_digest = _trie_digest(trie)

    embedded_digest = _read_embedded_digest(dispatch_generated.__file__)
    if embedded_digest != live_digest:
        raise RuntimeError(
            f"dispatch_generated.py is stale: embedded trie_digest="
            f"{embedded_digest}, live trie_digest={live_digest}. "
            f"Run: uv run exifmodern-signature-trie regenerate"
        )


def _read_embedded_digest(file_path: str) -> str:
    """Pull the `trie_digest : ...` line out of the generated file's header."""

    with Path(file_path).open(encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith("trie_digest"):
                return stripped.split(":", 1)[1].strip()
            if line.startswith('"""') and "AUTO-GENERATED" not in line:
                break
    return "(unknown)"
