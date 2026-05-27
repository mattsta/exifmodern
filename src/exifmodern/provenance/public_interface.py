"""Public-interface provenance IDs for explicit debug/dev opt-ins."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from exifmodern.json_types import JsonObject

PUBLIC_EVIDENCE_JSON_KEY = "evidence_ids"
type PublicEvidenceId = str
type PublicEvidenceResolver = Callable[[Iterable[PublicEvidenceId]], tuple[str, ...]]

_public_evidence_resolver: PublicEvidenceResolver | None = None


PLOT_SOURCES: tuple[PublicEvidenceId, ...] = (
    "public.plot.entrypoint",
    "public.plot.list-output-settings",
    "public.plot.tag-extra-points",
    "public.plot.accumulate-points",
    "public.plot.draw-svg",
    "public.plot.finalize-diagnostics",
)

HTML_DUMP_RENDERER_SOURCES: tuple[PublicEvidenceId, ...] = (
    "public.html-dump.option-parse",
    "public.html-dump.renderer-document",
    "public.html-dump.jpeg-byte-ranges",
)

SVG_PLOT_RENDERER_SOURCES: tuple[PublicEvidenceId, ...] = (
    "public.svg-plot.entrypoint",
    "public.svg-plot.final-draw",
    "public.svg-plot.tag-extra-points",
)


def public_evidence_requested(
    include_evidence: bool,
    options: JsonObject,
) -> bool:
    current_option = f"include_{PUBLIC_EVIDENCE_JSON_KEY}"
    return include_evidence or bool(options.pop(current_option, False))


def set_public_evidence_resolver(resolver: PublicEvidenceResolver | None) -> None:
    """Install a dev/debug resolver without importing dev-only modules in production."""

    global _public_evidence_resolver
    _public_evidence_resolver = resolver


def public_evidence_values(evidence_ids: Iterable[PublicEvidenceId]) -> tuple[str, ...]:
    ids = tuple(evidence_ids)
    if _public_evidence_resolver is None:
        return ids
    return _public_evidence_resolver(ids)
