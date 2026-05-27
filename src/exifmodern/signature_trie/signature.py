"""Signature DSL.

A `Signature` is a declarative description of "this format claims these
bytes in the file header." A list of `Signature`s compiles into a trie
that the dispatcher walks at read time.

Design rules:

- Pure data; no I/O, no side effects.
- Frozen dataclasses so signatures are hashable and trivially diff-able.
- Validation happens in `__post_init__`. A constructed Signature is
  always well-formed.
- `Pattern.bytes_` is named with a trailing underscore because `bytes` is
  a builtin; the trailing underscore is the only place that ugliness
  exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PreprocessKind(StrEnum):
    """How the input prefix is normalized before the trie walks it.

    Mirrors the only normalizations the current dispatcher does inline:
    PDF allows leading whitespace; JSON allows whitespace and an optional
    UTF-8 BOM. Both are content-sniffer escape hatches, kept narrow.
    """

    NONE = "none"
    LSTRIP_WHITESPACE = "lstrip_ws"
    LSTRIP_WHITESPACE_AND_BOM = "lstrip_ws_bom"


class SignatureSource(StrEnum):
    """Where this signature came from. Surfaced in diagnostics and the
    serialized artifact so reviewers can see which signatures are
    upstream-imported vs. discovered locally vs. hand-written.
    """

    DISCOVERY = "discovery"
    EXIFTOOL = "exiftool"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class Pattern:
    """A literal byte sequence that must appear at a fixed offset.

    Two patterns AND together inside one Signature: both must match.
    Alternatives (regex `(A|B|C)`) are expressed as multiple Signatures
    sharing a builder, not as alternatives inside one Pattern.
    """

    offset: int
    bytes_: bytes

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise ValueError(f"Pattern.offset must be >= 0, got {self.offset}")
        if not isinstance(self.bytes_, bytes):
            raise TypeError(f"Pattern.bytes_ must be bytes, got {type(self.bytes_).__name__}")
        if len(self.bytes_) == 0:
            raise ValueError("Pattern.bytes_ must not be empty")

    @property
    def end(self) -> int:
        return self.offset + len(self.bytes_)

    def matches(self, data: bytes) -> bool:
        if len(data) < self.end:
            return False
        return data[self.offset : self.end] == self.bytes_


@dataclass(frozen=True, slots=True)
class Signature:
    """A registered "this is format X" claim.

    `format_id` is opaque to the trie but must be unique across the
    registry. The convention is `family/variant` (e.g. `riff/wave`,
    `quicktime/heic`) so multiple Signatures pointing at the same
    builder can be distinguished in diagnostics.

    `builder_ref` is a string of the form `module.path:function_name`.
    The trie compiler does not import it; that is the dispatcher's job
    at runtime. Keeping it symbolic means the registry can be analyzed
    and serialized without loading every reader module.

    `weak` mirrors ExifTool's `%weakMagic`: the signature is too generic
    to trust without a corroborating extension hint.

    `structural_check` is a symbolic ref to a predicate the dispatcher
    runs *after* the trie pins down a leaf, used for formats whose
    detection is genuinely structural (ICO image-count, AAC ADTS frame
    validation). Should be rare; see DSL coverage discussion in
    docs/architecture/future-state/signature-trie-dispatch.md.
    """

    format_id: str
    builder_ref: str
    patterns: tuple[Pattern, ...]
    preprocess: PreprocessKind = PreprocessKind.NONE
    priority: int = 0
    weak: bool = False
    structural_check: str | None = None
    source: SignatureSource = SignatureSource.MANUAL
    notes: tuple[str, ...] = field(default_factory=tuple)
    extensions: tuple[str, ...] = field(default_factory=tuple)
    """File extensions (lowercase, including the dot — e.g. ".mp3") to
    use as a fallback dispatch hint when the trie has no magic-byte
    match. Used for formats with no usable magic (MP3) and as a last-
    resort for formats whose magic is too generic to trust without a
    filename hint (HTML, JSON, FITS).

    A signature may be **extension-only**: declare `extensions` and
    leave `patterns=()`. The dispatcher consults extension-only
    signatures only after the trie misses, in declaration order; the
    first extension match wins. Pair with `structural_check` to do a
    final content validation (recommended)."""

    def __post_init__(self) -> None:
        if not self.format_id:
            raise ValueError("format_id must be non-empty")
        if not self.builder_ref:
            raise ValueError("builder_ref must be non-empty")
        if ":" not in self.builder_ref:
            raise ValueError(
                f"builder_ref must be of the form 'module.path:func', got {self.builder_ref!r}"
            )
        if not self.patterns and not self.extensions:
            raise ValueError(
                f"signature {self.format_id!r} must declare at least one Pattern "
                "or one extension (extension-only signatures use empty patterns)"
            )
        # Patterns must be sorted by offset for deterministic compile output.
        offsets = [p.offset for p in self.patterns]
        if offsets != sorted(offsets):
            raise ValueError(f"signature {self.format_id!r} patterns must be sorted by offset")
        # Patterns must not overlap.
        for prev, curr in zip(self.patterns, self.patterns[1:], strict=False):
            if prev.end > curr.offset:
                raise ValueError(
                    f"signature {self.format_id!r} has overlapping patterns: {prev} and {curr}"
                )
        # Extensions must be lowercase, dotted, non-empty.
        for ext in self.extensions:
            if not ext.startswith(".") or ext != ext.lower() or len(ext) < 2:
                raise ValueError(
                    f"signature {self.format_id!r} has invalid extension {ext!r}; "
                    "use lowercase form including the dot, e.g. '.mp3'"
                )

    @property
    def total_bytes_examined(self) -> int:
        return sum(len(p.bytes_) for p in self.patterns)

    @property
    def max_offset(self) -> int:
        return max(p.end for p in self.patterns)
