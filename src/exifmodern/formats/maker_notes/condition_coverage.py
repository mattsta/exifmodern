"""Coverage diagnostics for package-backed maker-note Condition expressions."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.safe_expression.compat_compiler import compile_safe_expression
from exifmodern.safe_expression.vm import (
    DynamicContextPathSegment,
    LazyTernary,
    LazyTruthyAnd,
    LazyTruthyOr,
    LoadContextPath,
    LoadInput,
    LoadSelfContext,
    MapList,
    SafeExpressionProgram,
    StaticContextPathSegment,
    VmInstruction,
    WhileLoop,
    context_path_input_name,
    self_context_input_name,
)
from exifmodern.services.maker_note_tables import (
    MakerNoteTableRepository,
    MakerNoteTagLocation,
    load_maker_note_table_repository,
)
from exifmodern.services.queries.maker_note import locations_to_json

type MakerNoteConditionCoverageStatus = Literal[
    "compiled",
    "not_scalar_condition",
    "unsupported_expression",
]


@dataclass(frozen=True)
class MakerNoteConditionCoverageEntry:
    location: MakerNoteTagLocation
    status: MakerNoteConditionCoverageStatus
    required_inputs: tuple[str, ...]


@dataclass(frozen=True)
class MakerNoteConditionCoverageReport:
    repository: MakerNoteTableRepository
    entries: tuple[MakerNoteConditionCoverageEntry, ...]
    status_counts: tuple[tuple[MakerNoteConditionCoverageStatus, int], ...]
    required_input_counts: tuple[tuple[str, int], ...]
    top_modules: tuple[tuple[str, int], ...]
    top_tables: tuple[tuple[str, int], ...]

    @property
    def condition_count(self) -> int:
        return len(self.entries)

    @property
    def compiled_count(self) -> int:
        return count_status(self.entries, "compiled")

    @property
    def unsupported_count(self) -> int:
        return count_status(self.entries, "unsupported_expression")

    @property
    def not_scalar_count(self) -> int:
        return count_status(self.entries, "not_scalar_condition")

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "summary": {
                "source_count": self.repository.source_count,
                "table_count": self.repository.table_count,
                "tag_entry_count": self.repository.tag_entry_count,
                "condition_count": self.condition_count,
                "compiled_count": self.compiled_count,
                "unsupported_count": self.unsupported_count,
                "not_scalar_count": self.not_scalar_count,
            },
            "status_counts": count_pairs_to_json(self.status_counts),
            "required_input_counts": count_pairs_to_json(self.required_input_counts[:50]),
            "top_modules": count_pairs_to_json(self.top_modules[:50]),
            "top_tables": count_pairs_to_json(self.top_tables[:50]),
            "unsupported_samples": coverage_entries_to_json(
                entries_with_status(self.entries, "unsupported_expression")[:100],
            ),
            "compiled_samples": coverage_entries_to_json(
                entries_with_status(self.entries, "compiled")[:100],
            ),
        }


def build_maker_note_condition_coverage_report(
    maker_note_package: Path,
) -> MakerNoteConditionCoverageReport:
    repository = load_maker_note_table_repository(maker_note_package)
    entries = tuple(
        maker_note_condition_coverage_entry(location)
        for location in repository.condition_locations()
    )
    return MakerNoteConditionCoverageReport(
        repository=repository,
        entries=entries,
        status_counts=top_status_counts(entry.status for entry in entries),
        required_input_counts=top_counts(
            required_input for entry in entries for required_input in entry.required_inputs
        ),
        top_modules=top_counts(
            entry.location.module.module
            for entry in entries
            if entry.status == "unsupported_expression"
        ),
        top_tables=top_counts(
            entry.location.module.module + "::" + entry.location.table.name
            for entry in entries
            if entry.status == "unsupported_expression"
        ),
    )


def maker_note_condition_coverage_entry(
    location: MakerNoteTagLocation,
) -> MakerNoteConditionCoverageEntry:
    entry = location.entry
    if entry.condition_kind != "scalar" or not entry.condition_text:
        return MakerNoteConditionCoverageEntry(
            location=location,
            status="not_scalar_condition",
            required_inputs=(),
        )
    program = compile_safe_expression(entry.condition_text)
    if program is None:
        return MakerNoteConditionCoverageEntry(
            location=location,
            status="unsupported_expression",
            required_inputs=(),
        )
    return MakerNoteConditionCoverageEntry(
        location=location,
        status="compiled",
        required_inputs=program_required_inputs(program),
    )


def write_maker_note_condition_coverage_report(
    maker_note_package: Path,
    output: Path,
) -> MakerNoteConditionCoverageReport:
    report = build_maker_note_condition_coverage_report(maker_note_package)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def maker_note_condition_coverage_summary(
    report: MakerNoteConditionCoverageReport,
) -> JsonObject:
    return {
        "condition_count": report.condition_count,
        "compiled_count": report.compiled_count,
        "unsupported_count": report.unsupported_count,
        "not_scalar_count": report.not_scalar_count,
        "source_count": report.repository.source_count,
        "table_count": report.repository.table_count,
        "tag_entry_count": report.repository.tag_entry_count,
    }


def program_required_inputs(program: SafeExpressionProgram) -> tuple[str, ...]:
    return tuple(sorted(set(instructions_required_inputs(program.instructions))))


def instructions_required_inputs(instructions: list[VmInstruction]) -> tuple[str, ...]:
    input_names: list[str] = []
    for instruction in instructions:
        input_names.extend(instruction_required_inputs(instruction))
    return tuple(input_names)


def instruction_required_inputs(instruction: VmInstruction) -> tuple[str, ...]:
    if isinstance(instruction, LoadInput):
        return (instruction.name,)
    if isinstance(instruction, LoadSelfContext):
        return (self_context_input_name(instruction.key),)
    if isinstance(instruction, LoadContextPath):
        return (context_path_input_name(instruction.namespace, segment_names(instruction)),)
    if isinstance(instruction, LazyTruthyAnd | LazyTruthyOr):
        return instructions_required_inputs(instruction.right_instructions)
    if isinstance(instruction, LazyTernary):
        return instructions_required_inputs(
            instruction.true_instructions + instruction.false_instructions,
        )
    if isinstance(instruction, WhileLoop):
        return instructions_required_inputs(
            instruction.condition_instructions + instruction.body_instructions,
        )
    if isinstance(instruction, MapList):
        return instructions_required_inputs(instruction.item_instructions)
    return ()


def segment_names(instruction: LoadContextPath) -> list[str]:
    values: list[str] = []
    for segment in instruction.segments:
        if isinstance(segment, StaticContextPathSegment):
            values.append(segment.value)
        elif isinstance(segment, DynamicContextPathSegment):
            values.append("<dynamic>")
    return values


def count_status(
    entries: tuple[MakerNoteConditionCoverageEntry, ...],
    status: MakerNoteConditionCoverageStatus,
) -> int:
    return sum(1 for entry in entries if entry.status == status)


def entries_with_status(
    entries: tuple[MakerNoteConditionCoverageEntry, ...],
    status: MakerNoteConditionCoverageStatus,
) -> tuple[MakerNoteConditionCoverageEntry, ...]:
    return tuple(entry for entry in entries if entry.status == status)


def top_counts(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    counter = Counter(value for value in values if value)
    return tuple(counter.most_common())


def top_status_counts(
    values: Iterable[MakerNoteConditionCoverageStatus],
) -> tuple[tuple[MakerNoteConditionCoverageStatus, int], ...]:
    counter = Counter(values)
    return tuple(counter.most_common())


def count_pairs_to_json(
    values: tuple[tuple[str, int], ...] | tuple[tuple[MakerNoteConditionCoverageStatus, int], ...],
) -> JsonArray:
    return [{"value": value, "count": count} for value, count in values]


def coverage_entries_to_json(
    entries: tuple[MakerNoteConditionCoverageEntry, ...],
) -> JsonArray:
    return [
        {
            "status": entry.status,
            "required_inputs": list(entry.required_inputs),
            "location": locations_to_json((entry.location,))[0],
        }
        for entry in entries
    ]
