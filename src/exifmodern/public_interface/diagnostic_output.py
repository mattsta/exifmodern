"""Public CLI diagnostic and status output helpers."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from exifmodern.json_types import JsonArray, JsonObject, JsonValue
from exifmodern.provenance.public_interface import (
    HTML_DUMP_RENDERER_SOURCES,
    PUBLIC_EVIDENCE_JSON_KEY,
    SVG_PLOT_RENDERER_SOURCES,
    public_evidence_requested,
    public_evidence_values,
)
from exifmodern.public_api.models import Diagnostic, PublicOperationStatus
from exifmodern.public_interface.unknown_options import (
    PublicRequestAllDeepDiscoveryBlocker,
    PublicUnknownBinaryBlockBlocker,
)


@dataclass(frozen=True)
class HtmlDumpRendererContract:
    required_state: tuple[str, ...]
    currently_available_state: tuple[str, ...]
    evidence_sources: tuple[str, ...]

    def to_json_value(
        self,
        *,
        include_evidence: bool = False,
        **options: JsonValue,
    ) -> JsonObject:
        value: JsonObject = {
            "required_state": list(self.required_state),
            "currently_available_state": list(self.currently_available_state),
            "missing_state": [
                state
                for state in self.required_state
                if state not in self.currently_available_state
            ],
        }
        if public_evidence_requested(include_evidence, options):
            value[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(self.evidence_sources))
        return value


@dataclass(frozen=True)
class SvgPlotRendererContract:
    required_state: tuple[str, ...]
    currently_available_state: tuple[str, ...]
    evidence_sources: tuple[str, ...]

    def to_json_value(
        self,
        *,
        include_evidence: bool = False,
        **options: JsonValue,
    ) -> JsonObject:
        value: JsonObject = {
            "required_state": list(self.required_state),
            "currently_available_state": list(self.currently_available_state),
            "missing_state": [
                state
                for state in self.required_state
                if state not in self.currently_available_state
            ],
        }
        if public_evidence_requested(include_evidence, options):
            value[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(self.evidence_sources))
        return value


def print_diagnostics(
    diagnostics: tuple[Diagnostic, ...],
    *,
    quiet_count: int = 0,
    ignore_minor_errors: bool = False,
) -> None:
    for diagnostic in diagnostics:
        if ignore_minor_errors and diagnostic_is_minor(diagnostic):
            continue
        if quiet_count >= 2 and not diagnostic_is_error(diagnostic):
            continue
        print(f"{diagnostic.code}: {diagnostic.message}", file=sys.stderr)


def diagnostic_is_error(diagnostic: Diagnostic) -> bool:
    return diagnostic.code.startswith("error") or diagnostic.message.startswith("Error")


def diagnostic_is_minor(diagnostic: Diagnostic) -> bool:
    return diagnostic.message.startswith(("[minor]", "[Minor]"))


def exit_code_for_status(status: PublicOperationStatus) -> int:
    if status == "ok":
        return 0
    return 2


def verbose_diagnostic_dump_not_connected_diagnostic(
    verbose_level: int,
    *,
    include_evidence: bool = False,
    **options: JsonValue,
) -> Diagnostic:
    hexdump_limit = None
    if verbose_level == 3:
        hexdump_limit = 96
    elif verbose_level == 4:
        hexdump_limit = 2048
    details: JsonObject = {
        "verbose_level": verbose_level,
        "current_renderer_state_available": [
            "public read records",
            "tag provenance labels",
            "normalized tag values",
        ],
        "missing_low_level_state": [
            "reader indentation stack",
            "directory traversal events",
            "random-access byte offsets",
            "bounded raw data windows for hex dumps",
        ],
        "verbose_hexdump_max_len": hexdump_limit,
    }
    if public_evidence_requested(include_evidence, options):
        details[PUBLIC_EVIDENCE_JSON_KEY] = list(
            public_evidence_values(
                (
                    "public.verbose.level-parse",
                    "public.verbose.reader-traces",
                    "public.verbose.hex-dump-limits",
                )
            )
        )
    return Diagnostic(
        code="verbose_diagnostic_dump_not_connected",
        message=(
            "ExifTool-style -v verbose structure dumps are recognized, but "
            "public read execution does not expose low-level verbose dumps yet."
        ),
        details=details,
    )


def html_dump_renderer_deferred_diagnostic_details(
    *,
    include_evidence: bool = False,
    **options: JsonValue,
) -> JsonObject:
    contract = html_dump_renderer_contract()
    missing_state = _string_array(contract.to_json_value()["missing_state"])
    value: JsonObject = {
        "renderer_contract": contract.to_json_value(),
        "missing_renderer_state": missing_state,
    }
    if public_evidence_requested(include_evidence, options):
        value["renderer_contract"] = contract.to_json_value(include_evidence=True)
        value[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(contract.evidence_sources))
    return value


def html_dump_renderer_contract(
    *,
    currently_available_state: tuple[str, ...] = (),
) -> HtmlDumpRendererContract:
    return HtmlDumpRendererContract(
        required_state=(
            "HtmlDumpBase byte offset",
            "per-segment byte ranges",
            "low-level EXIF/TIFF/JPEG dump blocks",
            "HTML_DUMP span/class tooltip annotations",
        ),
        currently_available_state=currently_available_state,
        evidence_sources=HTML_DUMP_RENDERER_SOURCES,
    )


def plot_renderer_deferred_diagnostic_details(
    *,
    include_evidence: bool = False,
    **options: JsonValue,
) -> JsonObject:
    contract = svg_plot_renderer_contract()
    missing_state = _string_array(contract.to_json_value()["missing_state"])
    value: JsonObject = {
        "renderer_contract": contract.to_json_value(),
        "missing_renderer_state": missing_state,
    }
    if public_evidence_requested(include_evidence, options):
        value["renderer_contract"] = contract.to_json_value(include_evidence=True)
        value[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(contract.evidence_sources))
    return value


def svg_plot_renderer_contract(
    *,
    currently_available_state: tuple[str, ...] = (),
) -> SvgPlotRendererContract:
    return SvgPlotRendererContract(
        required_state=(
            "TAG_EXTRA family-3 document metadata",
            "per-file plotted point accumulation",
            "Image::ExifTool::Plot settings and SVG draw result",
        ),
        currently_available_state=currently_available_state,
        evidence_sources=SVG_PLOT_RENDERER_SOURCES,
    )


def _string_array(value: JsonValue) -> JsonArray:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def extract_embedded_not_connected_diagnostic(
    extract_embedded_level: int,
    *,
    include_evidence: bool = False,
    **options: JsonValue,
) -> Diagnostic:
    details: JsonObject = {"extract_embedded_level": extract_embedded_level}
    if public_evidence_requested(include_evidence, options):
        details[PUBLIC_EVIDENCE_JSON_KEY] = list(
            public_evidence_values(
                (
                    "public.extract-embedded.option-parse",
                    "public.extract-embedded.processing-gate",
                )
            )
        )
    return Diagnostic(
        code="extract_embedded_not_connected",
        message=(
            "ExifTool-style -ee embedded extraction is recognized, but public "
            "read execution has no bounded embedded-document traversal contract yet."
        ),
        details=details,
    )


def unknown_binary_block_discovery_diagnostic(
    blocker: PublicUnknownBinaryBlockBlocker,
    *,
    include_evidence: bool = False,
    **options: JsonValue,
) -> Diagnostic:
    details: JsonObject = {}
    if public_evidence_requested(include_evidence, options):
        details[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(blocker.evidence_sources))
    return Diagnostic(
        code=blocker.code,
        message=blocker.message,
        details=details,
    )


def request_all_deep_discovery_diagnostic(
    blocker: PublicRequestAllDeepDiscoveryBlocker,
    *,
    include_evidence: bool = False,
    **options: JsonValue,
) -> Diagnostic:
    details: JsonObject = {}
    if public_evidence_requested(include_evidence, options):
        details[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(blocker.evidence_sources))
    return Diagnostic(
        code=blocker.code,
        message=blocker.message,
        details=details,
    )
