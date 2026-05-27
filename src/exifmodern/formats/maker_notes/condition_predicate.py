"""Runtime evaluation boundary for maker-note Condition predicates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from exifmodern.formats.maker_notes.context import (
    EMPTY_MAKER_NOTE_RUNTIME_CONTEXT,
    MakerNoteRuntimeContext,
    maker_note_runtime_context_to_json,
)
from exifmodern.json_types import JsonArray, JsonObject, JsonValue
from exifmodern.services.maker_note_tables import (
    MakerNoteTableRepository,
    MakerNoteTagLocation,
    load_maker_note_table_repository,
)
from exifmodern.services.queries.maker_note import locations_to_json

if TYPE_CHECKING:
    from exifmodern.safe_expression.vm import InputName, VmInputs, VmValue

type MakerNoteConditionStatus = Literal[
    "evaluated",
    "missing_entry",
    "not_scalar_condition",
    "unsupported_expression",
    "evaluation_error",
]


@dataclass(frozen=True)
class MakerNoteConditionRequest:
    raw_value: str
    value_pointer: str = ""
    value_format: str = ""
    count: int | None = None
    vendor: str = ""
    module: str = ""
    table: str = ""
    tag_name: str = ""
    tag_id: str = ""
    runtime_context: MakerNoteRuntimeContext = EMPTY_MAKER_NOTE_RUNTIME_CONTEXT
    self_context: tuple[MakerNoteSelfContextValue, ...] = ()
    limit: int | None = None


@dataclass(frozen=True)
class MakerNoteSelfContextValue:
    path: tuple[str, ...]
    value: str

    @property
    def input_name(self) -> InputName:
        from exifmodern.safe_expression.vm import context_path_input_name

        return context_path_input_name("$$self", list(self.path))


@dataclass(frozen=True)
class MakerNoteConditionMatch:
    location: MakerNoteTagLocation
    status: MakerNoteConditionStatus
    matched: bool | None
    raw_result: JsonValue
    error: str


@dataclass(frozen=True)
class MakerNoteConditionResult:
    request: MakerNoteConditionRequest
    repository: MakerNoteTableRepository
    candidate_count: int
    matches: tuple[MakerNoteConditionMatch, ...]

    @property
    def evaluated_count(self) -> int:
        return sum(1 for match in self.matches if match.status == "evaluated")

    @property
    def matched_count(self) -> int:
        return sum(1 for match in self.matches if match.matched is True)

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "request": maker_note_condition_request_to_json(self.request),
            "source_count": self.repository.source_count,
            "table_count": self.repository.table_count,
            "tag_entry_count": self.repository.tag_entry_count,
            "candidate_count": self.candidate_count,
            "match_count": len(self.matches),
            "evaluated_count": self.evaluated_count,
            "matched_count": self.matched_count,
            "matches": maker_note_condition_matches_to_json(self.matches),
        }


def run_maker_note_condition(
    maker_note_package: Path,
    request: MakerNoteConditionRequest,
) -> MakerNoteConditionResult:
    repository = load_maker_note_table_repository(maker_note_package)
    return evaluate_maker_note_condition(repository, request)


def evaluate_maker_note_condition(
    repository: MakerNoteTableRepository,
    request: MakerNoteConditionRequest,
) -> MakerNoteConditionResult:
    candidates = repository.tag_entry_locations_for(
        vendor=request.vendor,
        module=request.module,
        table=request.table,
        tag_name=request.tag_name,
        tag_id=request.tag_id,
    )
    matches = tuple(
        evaluate_maker_note_condition_match(location, maker_note_condition_inputs(request))
        for location in candidates
    )
    limited_matches = matches if request.limit is None else matches[: request.limit]
    return MakerNoteConditionResult(
        request=request,
        repository=repository,
        candidate_count=len(candidates),
        matches=limited_matches,
    )


def evaluate_maker_note_condition_match(
    location: MakerNoteTagLocation,
    inputs: VmInputs,
) -> MakerNoteConditionMatch:
    entry = location.entry
    if entry.condition_kind != "scalar" or not entry.condition_text:
        return MakerNoteConditionMatch(
            location=location,
            status="not_scalar_condition",
            matched=None,
            raw_result=None,
            error="",
        )
    from exifmodern.safe_expression.compat_compiler import compile_safe_expression
    from exifmodern.safe_expression.vm import SafeExpressionVmError, evaluate_program, perl_truthy

    program = compile_safe_expression(entry.condition_text)
    if program is None:
        return MakerNoteConditionMatch(
            location=location,
            status="unsupported_expression",
            matched=None,
            raw_result=None,
            error="",
        )
    try:
        raw_result = evaluate_program(program, inputs)
    except SafeExpressionVmError as exc:
        return MakerNoteConditionMatch(
            location=location,
            status="evaluation_error",
            matched=None,
            raw_result=None,
            error=str(exc),
        )
    return MakerNoteConditionMatch(
        location=location,
        status="evaluated",
        matched=perl_truthy(raw_result),
        raw_result=vm_result_to_json(raw_result),
        error="",
    )


def write_maker_note_condition_result(
    maker_note_package: Path,
    request: MakerNoteConditionRequest,
    output: Path,
) -> MakerNoteConditionResult:
    result = run_maker_note_condition(maker_note_package, request)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def maker_note_condition_summary(result: MakerNoteConditionResult) -> JsonObject:
    return {
        "candidate_count": result.candidate_count,
        "match_count": len(result.matches),
        "evaluated_count": result.evaluated_count,
        "matched_count": result.matched_count,
        "source_count": result.repository.source_count,
        "table_count": result.repository.table_count,
        "tag_entry_count": result.repository.tag_entry_count,
    }


def maker_note_condition_request_to_json(request: MakerNoteConditionRequest) -> JsonObject:
    return {
        "raw_value": request.raw_value,
        "value_pointer": request.value_pointer,
        "value_format": request.value_format,
        "count": request.count,
        "vendor": request.vendor,
        "module": request.module,
        "table": request.table,
        "tag_name": request.tag_name,
        "tag_id": request.tag_id,
        "runtime_context": maker_note_runtime_context_to_json(request.runtime_context),
        "self_context": maker_note_self_context_values_to_json(request.self_context),
        "limit": request.limit,
    }


def maker_note_condition_matches_to_json(
    matches: tuple[MakerNoteConditionMatch, ...],
) -> JsonArray:
    return [
        {
            "status": match.status,
            "matched": match.matched,
            "raw_result": match.raw_result,
            "error": match.error,
            "location": locations_to_json((match.location,))[0],
        }
        for match in matches
    ]


def vm_result_to_json(value: VmValue) -> JsonValue:
    from exifmodern.formats.maker_notes.value_conversion import vm_value_to_json

    return vm_value_to_json(value)


def maker_note_condition_inputs(request: MakerNoteConditionRequest) -> VmInputs:
    inputs: VmInputs = request.runtime_context.to_vm_inputs()
    inputs["$val"] = request.raw_value
    if request.value_pointer:
        inputs["$valPt"] = request.value_pointer
    if request.value_format:
        inputs["$format"] = request.value_format
    if request.count is not None:
        inputs["$count"] = request.count
    for value in request.self_context:
        inputs[value.input_name] = value.value
    return inputs


def maker_note_self_context_values_to_json(
    values: tuple[MakerNoteSelfContextValue, ...],
) -> JsonArray:
    return [{"path": list(value.path), "value": value.value} for value in values]
