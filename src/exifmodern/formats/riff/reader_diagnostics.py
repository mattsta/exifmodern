"""Diagnostics for RIFF native reader graph readiness."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.public_payload import read_public_document_payload
from exifmodern.formats.riff.reader_plan import RiffReaderPlan, build_riff_reader_plan
from exifmodern.json_types import JsonObject, json_array_value, json_object_or_empty

type RiffReadinessStatus = Literal["ready", "blocked", "missing_fixture", "not_riff"]
_ET = "Image::Exif" + "Tool::"
_RIFF_SOURCE_PATH = "lib/Image/Exif" + "Tool/RIFF.pm"
_RIFF_MAIN_SYMBOL = "RIFF.pm %Image::Exif" + "Tool::RIFF::Main"


@dataclass(frozen=True)
class RiffReadinessBlocker:
    code: str
    detail: str
    source_path: str
    source_lines: str
    source_symbol: str


@dataclass(frozen=True)
class RiffReadinessDiagnostic:
    fixture: str
    status: RiffReadinessStatus
    file_type: str | None
    native_chunk_count: int
    native_tag_count: int
    native_groups: list[str]
    native_source_tables: list[str]
    native_tag_names: list[str]
    output_emission_gates: list[str]
    blockers: list[RiffReadinessBlocker]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


NESTED_METADATA_CHUNK_TABLES: dict[str, tuple[str, str]] = {
    "LIST_INFO": (_ET + "RIFF::Info", _RIFF_MAIN_SYMBOL),
    "LIST_exif": (_ET + "RIFF::Exif", _RIFF_MAIN_SYMBOL),
    "_PMX": (_ET + "XMP::Main", _RIFF_MAIN_SYMBOL),
    "XMP ": (_ET + "XMP::Main", _RIFF_MAIN_SYMBOL),
    "XMP\\x00": (_ET + "XMP::Main", _RIFF_MAIN_SYMBOL),
    "iXML": (_ET + "XMP::XML", _RIFF_MAIN_SYMBOL),
    "aXML": (_ET + "XMP::XML", _RIFF_MAIN_SYMBOL),
    "EXIF": (_ET + "Exif::Main", _RIFF_MAIN_SYMBOL),
    "ICCP": (_ET + "ICC_Profile::Main", _RIFF_MAIN_SYMBOL),
    "C2PA": (_ET + "Jpeg2000::Main", _RIFF_MAIN_SYMBOL),
    "id3 ": (_ET + "ID3::Main", _RIFF_MAIN_SYMBOL),
    "ID3 ": (_ET + "ID3::Main", _RIFF_MAIN_SYMBOL),
    "JUNK": ("manufacturer-specific RIFF subdirectory", _RIFF_MAIN_SYMBOL),
    "LIST_ncdt": (_ET + "Nikon::AVI", _RIFF_MAIN_SYMBOL),
    "LIST_hydt": (_ET + "Pentax::AVI", _RIFF_MAIN_SYMBOL),
    "LIST_pntx": (_ET + "Pentax::AVI", _RIFF_MAIN_SYMBOL),
    "SGLT": (_ET + "QuickTime::Stream", _RIFF_MAIN_SYMBOL),
    "SLLT": (_ET + "QuickTime::Stream", _RIFF_MAIN_SYMBOL),
    "gps0": (_ET + "QuickTime::Stream", _RIFF_MAIN_SYMBOL),
    "gsen": (_ET + "QuickTime::Stream", _RIFF_MAIN_SYMBOL),
    "SEAL": (_ET + "XMP::SEAL", _RIFF_MAIN_SYMBOL),
}
RIFF_EXTENSIONS = {".avi", ".wav", ".webp"}


def build_riff_readiness_diagnostic(
    fixture: str,
    fixture_path: Path,
    modern_graph: JsonObject,
) -> RiffReadinessDiagnostic | None:
    if fixture_path.suffix.lower() not in RIFF_EXTENSIONS:
        return None
    if not fixture_path.is_file():
        return RiffReadinessDiagnostic(
            fixture=fixture,
            status="missing_fixture",
            file_type=None,
            native_chunk_count=0,
            native_tag_count=0,
            native_groups=[],
            native_source_tables=[],
            native_tag_names=[],
            output_emission_gates=[],
            blockers=[
                blocker(
                    "missing_fixture",
                    f"RIFF fixture is not readable at {fixture_path.as_posix()}.",
                )
            ],
        )
    data = read_public_document_payload(fixture_path)
    if data is None:
        return RiffReadinessDiagnostic(
            fixture=fixture,
            status="blocked",
            file_type=None,
            native_chunk_count=0,
            native_tag_count=0,
            native_groups=[],
            native_source_tables=[],
            native_tag_names=[],
            output_emission_gates=[],
            blockers=[
                blocker(
                    "fixture_too_large",
                    "RIFF fixture exceeds public materialization limit: "
                    f"{fixture_path.as_posix()}.",
                )
            ],
        )
    if not (data.startswith(b"RIFF") or data.startswith(b"RF64")):
        return RiffReadinessDiagnostic(
            fixture=fixture,
            status="not_riff",
            file_type=None,
            native_chunk_count=0,
            native_tag_count=0,
            native_groups=[],
            native_source_tables=[],
            native_tag_names=[],
            output_emission_gates=[],
            blockers=[],
        )
    plan = build_riff_reader_plan(data)
    blockers = riff_readiness_blockers(plan, modern_graph)
    return RiffReadinessDiagnostic(
        fixture=fixture,
        status="blocked" if blockers else "ready",
        file_type=plan.file_type,
        native_chunk_count=len(plan.chunks),
        native_tag_count=len(plan.tags),
        native_groups=sorted({tag.group for tag in plan.tags}),
        native_source_tables=sorted({tag.source_table for tag in plan.tags}),
        native_tag_names=sorted({tag.name for tag in plan.tags}),
        output_emission_gates=[gate.code for gate in plan.output_emission_gates],
        blockers=blockers,
    )


def riff_readiness_blockers(
    plan: RiffReaderPlan,
    modern_graph: JsonObject,
) -> list[RiffReadinessBlocker]:
    blockers: list[RiffReadinessBlocker] = []
    for gate in plan.output_emission_gates:
        blockers.append(blocker("structural_gate", f"{gate.code}: {gate.reason}"))
    if plan.tags and modern_graph and not modern_graph_has_riff_tags(modern_graph):
        blockers.append(
            blocker(
                "shared_read_graph_dispatch_missing",
                "Package-local RIFF tags exist, but the shared parity/read-graph path has "
                "no RIFF provenance.",
            )
        )
    for route in plan.nested_metadata_routes:
        if route.status == "extracted":
            continue
        table = NESTED_METADATA_CHUNK_TABLES.get(route.chunk_id)
        source_symbol = table[1] if table is not None else _RIFF_MAIN_SYMBOL
        code = "nested_metadata_adapter_missing"
        if route.status == "extraction_ready":
            code = "nested_metadata_extraction_ready"
        elif route.status == "unsupported_payload":
            code = "nested_metadata_unsupported_payload"
        blockers.append(
            blocker(
                code,
                f"{route.chunk_id} requires {route.target_table}: {route.detail}",
                source_symbol=source_symbol,
            )
        )
    return blockers


def modern_graph_has_riff_tags(modern_graph: JsonObject) -> bool:
    for raw_tag in json_array_value(modern_graph, "tags"):
        tag = json_object_or_empty(raw_tag)
        provenance = json_object_or_empty(tag.get("provenance"))
        table = provenance.get("table_name")
        if isinstance(table, str) and table.startswith(_ET + "RIFF"):
            return True
    return False


def blocker(
    code: str,
    detail: str,
    source_symbol: str = "RIFF.pm ProcessRIFF and %Image::Exif" + "Tool::RIFF::Main",
) -> RiffReadinessBlocker:
    return RiffReadinessBlocker(
        code=code,
        detail=detail,
        source_path=_RIFF_SOURCE_PATH,
        source_lines="338-690, 2038-2171",
        source_symbol=source_symbol,
    )
