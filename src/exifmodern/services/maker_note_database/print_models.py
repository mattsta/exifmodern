"""Data models and JSON rendering for maker-note PrintConv service results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from exifmodern.formats.maker_notes.context import (
    EMPTY_MAKER_NOTE_RUNTIME_CONTEXT,
    MakerNoteRuntimeContext,
    maker_note_runtime_context_to_json,
)
from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.services.maker_note_tables import MakerNoteTableRepository, MakerNoteTagLocation
from exifmodern.services.queries.maker_note import locations_to_json

if TYPE_CHECKING:
    from exifmodern.safe_expression.bytecode import VmValue
else:
    type VmValue = str | int | float | bool | None | list[VmValue]

type MakerNotePrintConversionStatus = Literal[
    "converted",
    "missing_entry",
    "not_declarative",
    "partial_map_blocked",
    "unknown_value",
    "unsupported_expression",
    "evaluation_error",
]


@dataclass(frozen=True)
class MakerNotePrintConversionRequest:
    raw_value: str
    vendor: str = ""
    module: str = ""
    table: str = ""
    tag_name: str = ""
    tag_id: str = ""
    runtime_context: MakerNoteRuntimeContext = EMPTY_MAKER_NOTE_RUNTIME_CONTEXT
    complete_only: bool = False
    limit: int | None = None


@dataclass(frozen=True)
class MakerNotePrintConversionMatch:
    location: MakerNoteTagLocation
    status: MakerNotePrintConversionStatus
    printed_value: str | None

    @property
    def converted(self) -> bool:
        return self.status == "converted"


@dataclass(frozen=True)
class MakerNotePrintConversionResult:
    request: MakerNotePrintConversionRequest
    repository: MakerNoteTableRepository
    candidate_count: int
    matches: tuple[MakerNotePrintConversionMatch, ...]

    @property
    def converted_count(self) -> int:
        return sum(1 for match in self.matches if match.converted)

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "request": maker_note_print_conversion_request_to_json(self.request),
            "source_count": self.repository.source_count,
            "table_count": self.repository.table_count,
            "tag_entry_count": self.repository.tag_entry_count,
            "candidate_count": self.candidate_count,
            "match_count": len(self.matches),
            "converted_count": self.converted_count,
            "matches": maker_note_print_conversion_matches_to_json(self.matches),
        }


def vm_value_to_print_string(value: VmValue) -> str:
    if isinstance(value, list):
        return " ".join(vm_value_to_print_string(item) for item in value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def maker_note_print_conversion_summary(
    result: MakerNotePrintConversionResult,
) -> JsonObject:
    return {
        "candidate_count": result.candidate_count,
        "match_count": len(result.matches),
        "converted_count": result.converted_count,
        "source_count": result.repository.source_count,
        "table_count": result.repository.table_count,
        "tag_entry_count": result.repository.tag_entry_count,
    }


def maker_note_print_conversion_request_to_json(
    request: MakerNotePrintConversionRequest,
) -> JsonObject:
    return {
        "raw_value": request.raw_value,
        "vendor": request.vendor,
        "module": request.module,
        "table": request.table,
        "tag_name": request.tag_name,
        "tag_id": request.tag_id,
        "runtime_context": maker_note_runtime_context_to_json(request.runtime_context),
        "complete_only": request.complete_only,
        "limit": request.limit,
    }


def maker_note_print_conversion_matches_to_json(
    matches: tuple[MakerNotePrintConversionMatch, ...],
) -> JsonArray:
    return [
        {
            "status": match.status,
            "converted": match.converted,
            "printed_value": match.printed_value,
            "location": locations_to_json((match.location,))[0],
        }
        for match in matches
    ]
