"""Combined maker-note feature evaluation for native reader integration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.maker_notes.binary_tiff_output import (
    MakerNoteBinaryTiffRequest,
    MakerNoteBinaryTiffResult,
    maker_note_binary_tiff_result_to_json,
    maker_note_binary_tiff_spec_for_location,
    render_maker_note_binary_tiff_output,
)
from exifmodern.formats.maker_notes.condition_predicate import (
    MakerNoteConditionMatch,
    MakerNoteConditionRequest,
    MakerNoteSelfContextValue,
    evaluate_maker_note_condition_match,
    maker_note_condition_inputs,
    maker_note_condition_matches_to_json,
    maker_note_self_context_values_to_json,
)
from exifmodern.formats.maker_notes.context import (
    EMPTY_MAKER_NOTE_RUNTIME_CONTEXT,
    MakerNoteRuntimeContext,
    maker_note_runtime_context_to_json,
    maker_note_self_context,
)
from exifmodern.formats.maker_notes.print_conversion import (
    MakerNotePrintConversionMatch,
    MakerNotePrintConversionRequest,
    maker_note_print_conversion_matches_to_json,
    render_maker_note_print_conversion_match,
)
from exifmodern.formats.maker_notes.value_conversion import (
    MakerNoteValueConversionMatch,
    maker_note_value_conversion_matches_to_json,
    render_maker_note_value_conversion_match,
)
from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.services.maker_note_tables import (
    MakerNoteTableRepository,
    MakerNoteTagLocation,
    load_maker_note_table_repository,
)

type MakerNoteFeatureEvaluationStatus = Literal[
    "evaluated",
    "condition_false",
    "condition_blocked",
]


@dataclass(frozen=True)
class MakerNoteFeatureEvaluationRequest:
    raw_value: str
    binary_payload: bytes = b""
    binary_option: bool = False
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
    complete_only: bool = False
    limit: int | None = None


@dataclass(frozen=True)
class MakerNoteFeatureEvaluationMatch:
    location: MakerNoteTagLocation
    status: MakerNoteFeatureEvaluationStatus
    condition: MakerNoteConditionMatch
    value_conversion: MakerNoteValueConversionMatch | None
    print_conversion: MakerNotePrintConversionMatch | None
    binary_tiff_output: MakerNoteBinaryTiffResult | None = None

    @property
    def condition_passed(self) -> bool:
        return self.status == "evaluated"

    @property
    def value_converted(self) -> bool:
        return self.value_conversion is not None and self.value_conversion.converted

    @property
    def print_converted(self) -> bool:
        return self.print_conversion is not None and self.print_conversion.converted

    @property
    def binary_output_produced(self) -> bool:
        return self.binary_tiff_output is not None and self.binary_tiff_output.produced_binary


@dataclass(frozen=True)
class MakerNoteFeatureEvaluationResult:
    request: MakerNoteFeatureEvaluationRequest
    repository: MakerNoteTableRepository
    candidate_count: int
    matches: tuple[MakerNoteFeatureEvaluationMatch, ...]

    @property
    def condition_passed_count(self) -> int:
        return sum(1 for match in self.matches if match.condition_passed)

    @property
    def value_converted_count(self) -> int:
        return sum(1 for match in self.matches if match.value_converted)

    @property
    def print_converted_count(self) -> int:
        return sum(1 for match in self.matches if match.print_converted)

    @property
    def binary_output_count(self) -> int:
        return sum(1 for match in self.matches if match.binary_output_produced)

    @property
    def binary_tiff_terminal_surface_count(self) -> int:
        return sum(
            1
            for match in self.matches
            if match.binary_tiff_output is not None and match.binary_tiff_output.terminal_surface
        )

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "request": maker_note_feature_evaluation_request_to_json(self.request),
            "source_count": self.repository.source_count,
            "table_count": self.repository.table_count,
            "tag_entry_count": self.repository.tag_entry_count,
            "candidate_count": self.candidate_count,
            "match_count": len(self.matches),
            "condition_passed_count": self.condition_passed_count,
            "value_converted_count": self.value_converted_count,
            "print_converted_count": self.print_converted_count,
            "binary_output_count": self.binary_output_count,
            "binary_tiff_terminal_surface_count": self.binary_tiff_terminal_surface_count,
            "matches": maker_note_feature_evaluation_matches_to_json(self.matches),
        }


def run_maker_note_feature_evaluation(
    maker_note_package: Path,
    request: MakerNoteFeatureEvaluationRequest,
) -> MakerNoteFeatureEvaluationResult:
    repository = load_maker_note_table_repository(maker_note_package)
    return evaluate_maker_note_features(repository, request)


def evaluate_maker_note_features(
    repository: MakerNoteTableRepository,
    request: MakerNoteFeatureEvaluationRequest,
) -> MakerNoteFeatureEvaluationResult:
    candidates = repository.tag_entry_locations_for(
        vendor=request.vendor,
        module=request.module,
        table=request.table,
        tag_name=request.tag_name,
        tag_id=request.tag_id,
    )
    matches = tuple(evaluate_maker_note_feature_match(location, request) for location in candidates)
    limited_matches = matches if request.limit is None else matches[: request.limit]
    return MakerNoteFeatureEvaluationResult(
        request=request,
        repository=repository,
        candidate_count=len(candidates),
        matches=limited_matches,
    )


def evaluate_maker_note_feature_match(
    location: MakerNoteTagLocation,
    request: MakerNoteFeatureEvaluationRequest,
) -> MakerNoteFeatureEvaluationMatch:
    condition = evaluate_maker_note_condition_match(
        location,
        maker_note_condition_inputs(feature_evaluation_condition_request(request)),
    )
    status = maker_note_feature_evaluation_status(condition)
    if status != "evaluated":
        return MakerNoteFeatureEvaluationMatch(
            location=location,
            status=status,
            condition=condition,
            value_conversion=None,
            print_conversion=None,
            binary_tiff_output=None,
        )
    runtime_context = maker_note_feature_runtime_context(request)
    value_conversion = render_maker_note_value_conversion_match(
        location,
        request.raw_value,
        runtime_context,
    )
    print_conversion = render_maker_note_feature_print_conversion(
        location,
        request,
        value_conversion,
        runtime_context,
    )
    binary_tiff_output = render_maker_note_feature_binary_tiff_output(location, request)
    return MakerNoteFeatureEvaluationMatch(
        location=location,
        status=status,
        condition=condition,
        value_conversion=value_conversion,
        print_conversion=print_conversion,
        binary_tiff_output=binary_tiff_output,
    )


def render_maker_note_feature_print_conversion(
    location: MakerNoteTagLocation,
    request: MakerNoteFeatureEvaluationRequest,
    value_conversion: MakerNoteValueConversionMatch,
    runtime_context: MakerNoteRuntimeContext,
) -> MakerNotePrintConversionMatch:
    converted_input = maker_note_print_conversion_input(value_conversion, request.raw_value)
    converted_match = render_maker_note_print_conversion_match(
        location,
        MakerNotePrintConversionRequest(
            raw_value=converted_input,
            runtime_context=runtime_context,
            complete_only=request.complete_only,
        ),
    )
    if converted_match.converted or converted_input == request.raw_value:
        return converted_match
    return render_maker_note_print_conversion_match(
        location,
        MakerNotePrintConversionRequest(
            raw_value=request.raw_value,
            runtime_context=runtime_context,
            complete_only=request.complete_only,
        ),
    )


def render_maker_note_feature_binary_tiff_output(
    location: MakerNoteTagLocation,
    request: MakerNoteFeatureEvaluationRequest,
) -> MakerNoteBinaryTiffResult | None:
    if maker_note_binary_tiff_spec_for_location(location) is None:
        return None
    if not request.binary_payload and not request.binary_option:
        return None
    return render_maker_note_binary_tiff_output(
        MakerNoteBinaryTiffRequest(
            location=location,
            payload=request.binary_payload,
            binary_option=request.binary_option,
        )
    )


def maker_note_print_conversion_input(
    value_conversion: MakerNoteValueConversionMatch,
    raw_value: str,
) -> str:
    if not value_conversion.converted:
        return raw_value
    converted = value_conversion.converted_value
    if isinstance(converted, bool) or converted is None:
        return str(converted)
    if isinstance(converted, int | str):
        return str(converted)
    if isinstance(converted, float):
        if converted.is_integer():
            return str(int(converted))
        return str(converted)
    return raw_value


def write_maker_note_feature_evaluation_result(
    maker_note_package: Path,
    request: MakerNoteFeatureEvaluationRequest,
    output: Path,
) -> MakerNoteFeatureEvaluationResult:
    result = run_maker_note_feature_evaluation(maker_note_package, request)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def maker_note_feature_evaluation_status(
    condition: MakerNoteConditionMatch,
) -> MakerNoteFeatureEvaluationStatus:
    if condition.status == "not_scalar_condition":
        return "evaluated"
    if condition.status == "evaluated" and condition.matched is True:
        return "evaluated"
    if condition.status == "evaluated":
        return "condition_false"
    return "condition_blocked"


def feature_evaluation_condition_request(
    request: MakerNoteFeatureEvaluationRequest,
) -> MakerNoteConditionRequest:
    return MakerNoteConditionRequest(
        raw_value=request.raw_value,
        value_pointer=request.value_pointer,
        value_format=request.value_format,
        count=request.count,
        runtime_context=maker_note_feature_runtime_context(request),
        self_context=request.self_context,
    )


def maker_note_feature_runtime_context(
    request: MakerNoteFeatureEvaluationRequest,
) -> MakerNoteRuntimeContext:
    legacy_self_values = tuple(
        maker_note_self_context(value.path, value.value) for value in request.self_context
    )
    return request.runtime_context.with_values(legacy_self_values)


def maker_note_feature_evaluation_summary(
    result: MakerNoteFeatureEvaluationResult,
) -> JsonObject:
    return {
        "candidate_count": result.candidate_count,
        "match_count": len(result.matches),
        "condition_passed_count": result.condition_passed_count,
        "value_converted_count": result.value_converted_count,
        "print_converted_count": result.print_converted_count,
        "binary_output_count": result.binary_output_count,
        "binary_tiff_terminal_surface_count": result.binary_tiff_terminal_surface_count,
        "source_count": result.repository.source_count,
        "table_count": result.repository.table_count,
        "tag_entry_count": result.repository.tag_entry_count,
    }


def maker_note_feature_evaluation_request_to_json(
    request: MakerNoteFeatureEvaluationRequest,
) -> JsonObject:
    return {
        "raw_value": request.raw_value,
        "binary_payload_bytes": len(request.binary_payload),
        "binary_option": request.binary_option,
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
        "complete_only": request.complete_only,
        "limit": request.limit,
    }


def maker_note_feature_evaluation_matches_to_json(
    matches: tuple[MakerNoteFeatureEvaluationMatch, ...],
) -> JsonArray:
    return [
        {
            "status": match.status,
            "condition_passed": match.condition_passed,
            "value_converted": match.value_converted,
            "print_converted": match.print_converted,
            "binary_output_produced": match.binary_output_produced,
            "condition": maker_note_condition_matches_to_json((match.condition,))[0],
            "value_conversion": (
                maker_note_value_conversion_matches_to_json((match.value_conversion,))[0]
                if match.value_conversion is not None
                else None
            ),
            "print_conversion": (
                maker_note_print_conversion_matches_to_json((match.print_conversion,))[0]
                if match.print_conversion is not None
                else None
            ),
            "binary_tiff_output": (
                maker_note_binary_tiff_result_to_json(match.binary_tiff_output)
                if match.binary_tiff_output is not None
                else None
            ),
        }
        for match in matches
    ]
