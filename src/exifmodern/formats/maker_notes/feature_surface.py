"""Package-wide maker-note feature readiness diagnostics."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.maker_notes.binary_tiff_output import (
    maker_note_binary_tiff_spec_for_location,
)
from exifmodern.formats.maker_notes.print_conversion import (
    maker_note_domain_print_conversion_adapter_supported,
    maker_note_scalar_print_conversion_adapter_supported,
)
from exifmodern.formats.maker_notes.value_conversion import (
    maker_note_domain_value_conversion_adapter_supported,
    maker_note_scalar_value_conversion_adapter_supported,
)
from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.safe_expression.compat_compiler import compile_safe_expression
from exifmodern.services.maker_note_tables import (
    MakerNoteTableRepository,
    MakerNoteTagLocation,
    load_maker_note_table_repository,
)
from exifmodern.services.queries.maker_note import locations_to_json

type MakerNoteConditionReadiness = Literal[
    "none",
    "compiled",
    "not_scalar",
    "unsupported",
]
type MakerNoteValueConversionReadiness = Literal[
    "none",
    "scalar_compiled",
    "scalar_runtime_adapter",
    "binary_runtime_adapter",
    "scalar_unsupported",
    "domain_adapter_required",
]
type MakerNotePrintConversionReadiness = Literal[
    "none",
    "declarative_complete",
    "declarative_partial",
    "scalar_compiled",
    "scalar_runtime_adapter",
    "scalar_unsupported",
    "domain_adapter_required",
]
type MakerNoteTraversalReadiness = Literal[
    "none",
    "subdirectory_edge",
]
type MakerNoteReaderReadiness = Literal[
    "static_metadata",
    "read_pipeline_ready",
    "traversal_pipeline_ready",
    "domain_adapter_required",
]
type MakerNoteFeatureSignature = str


@dataclass(frozen=True)
class MakerNoteFeatureSurfaceEntry:
    location: MakerNoteTagLocation
    condition: MakerNoteConditionReadiness
    value_conversion: MakerNoteValueConversionReadiness
    print_conversion: MakerNotePrintConversionReadiness
    traversal: MakerNoteTraversalReadiness
    reader_readiness: MakerNoteReaderReadiness
    feature_signature: MakerNoteFeatureSignature


@dataclass(frozen=True)
class MakerNoteFeatureSurfaceReport:
    repository: MakerNoteTableRepository
    entries: tuple[MakerNoteFeatureSurfaceEntry, ...]
    reader_readiness_counts: tuple[tuple[MakerNoteReaderReadiness, int], ...]
    condition_counts: tuple[tuple[MakerNoteConditionReadiness, int], ...]
    value_conversion_counts: tuple[tuple[MakerNoteValueConversionReadiness, int], ...]
    print_conversion_counts: tuple[tuple[MakerNotePrintConversionReadiness, int], ...]
    traversal_counts: tuple[tuple[MakerNoteTraversalReadiness, int], ...]
    feature_signature_counts: tuple[tuple[MakerNoteFeatureSignature, int], ...]
    blocked_modules: tuple[tuple[str, int], ...]
    blocked_tables: tuple[tuple[str, int], ...]

    @property
    def reader_ready_count(self) -> int:
        return sum(
            count
            for readiness, count in self.reader_readiness_counts
            if readiness in ("static_metadata", "read_pipeline_ready", "traversal_pipeline_ready")
        )

    @property
    def domain_adapter_required_count(self) -> int:
        return count_reader_readiness(self.entries, "domain_adapter_required")

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "summary": {
                "source_count": self.repository.source_count,
                "loaded_source_count": self.repository.loaded_source_count,
                "table_count": self.repository.table_count,
                "tag_entry_count": self.repository.tag_entry_count,
                "reader_ready_count": self.reader_ready_count,
                "domain_adapter_required_count": self.domain_adapter_required_count,
            },
            "reader_readiness_counts": count_pairs_to_json(self.reader_readiness_counts),
            "condition_counts": count_pairs_to_json(self.condition_counts),
            "value_conversion_counts": count_pairs_to_json(self.value_conversion_counts),
            "print_conversion_counts": count_pairs_to_json(self.print_conversion_counts),
            "traversal_counts": count_pairs_to_json(self.traversal_counts),
            "feature_signature_counts": count_pairs_to_json(
                self.feature_signature_counts[:100],
            ),
            "blocked_modules": count_pairs_to_json(self.blocked_modules[:50]),
            "blocked_tables": count_pairs_to_json(self.blocked_tables[:50]),
            "reader_ready_samples": feature_surface_entries_to_json(
                entries_without_domain_adapter(self.entries)[:50],
            ),
            "domain_adapter_required_samples": feature_surface_entries_to_json(
                entries_with_reader_readiness(self.entries, "domain_adapter_required")[:100],
            ),
        }


def build_maker_note_feature_surface_report(
    maker_note_package: Path,
) -> MakerNoteFeatureSurfaceReport:
    repository = load_maker_note_table_repository(maker_note_package)
    entries = tuple(
        maker_note_feature_surface_entry(location) for location in repository.tag_entry_locations()
    )
    blocked_entries = entries_with_reader_readiness(entries, "domain_adapter_required")
    return MakerNoteFeatureSurfaceReport(
        repository=repository,
        entries=entries,
        reader_readiness_counts=top_typed_counts(entry.reader_readiness for entry in entries),
        condition_counts=top_typed_counts(entry.condition for entry in entries),
        value_conversion_counts=top_typed_counts(entry.value_conversion for entry in entries),
        print_conversion_counts=top_typed_counts(entry.print_conversion for entry in entries),
        traversal_counts=top_typed_counts(entry.traversal for entry in entries),
        feature_signature_counts=top_counts(entry.feature_signature for entry in entries),
        blocked_modules=top_counts(entry.location.module.module for entry in blocked_entries),
        blocked_tables=top_counts(
            entry.location.module.module + "::" + entry.location.table.name
            for entry in blocked_entries
        ),
    )


def write_maker_note_feature_surface_report(
    maker_note_package: Path,
    output: Path,
) -> MakerNoteFeatureSurfaceReport:
    report = build_maker_note_feature_surface_report(maker_note_package)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def maker_note_feature_surface_entry(
    location: MakerNoteTagLocation,
) -> MakerNoteFeatureSurfaceEntry:
    condition = condition_readiness(location)
    value_conversion = value_conversion_readiness(location)
    print_conversion = print_conversion_readiness(location)
    traversal = traversal_readiness(location)
    reader_readiness = maker_note_reader_readiness(
        condition=condition,
        value_conversion=value_conversion,
        print_conversion=print_conversion,
        traversal=traversal,
    )
    return MakerNoteFeatureSurfaceEntry(
        location=location,
        condition=condition,
        value_conversion=value_conversion,
        print_conversion=print_conversion,
        traversal=traversal,
        reader_readiness=reader_readiness,
        feature_signature=feature_signature(
            condition=condition,
            value_conversion=value_conversion,
            print_conversion=print_conversion,
            traversal=traversal,
        ),
    )


def condition_readiness(
    location: MakerNoteTagLocation,
) -> MakerNoteConditionReadiness:
    entry = location.entry
    if not entry.has_condition:
        return "none"
    if entry.condition_kind != "scalar" or not entry.condition_text:
        return "not_scalar"
    if compile_safe_expression(entry.condition_text) is None:
        return "unsupported"
    return "compiled"


def value_conversion_readiness(
    location: MakerNoteTagLocation,
) -> MakerNoteValueConversionReadiness:
    entry = location.entry
    if not entry.has_value_conv:
        return "none"
    if maker_note_binary_tiff_spec_for_location(location) is not None:
        return "binary_runtime_adapter"
    if maker_note_domain_value_conversion_adapter_supported(location):
        return "scalar_runtime_adapter"
    if entry.value_conv_kind != "scalar" or not entry.value_conv_text:
        return "domain_adapter_required"
    if maker_note_scalar_value_conversion_adapter_supported(entry.value_conv_text):
        return "scalar_runtime_adapter"
    if compile_safe_expression(entry.value_conv_text) is None:
        return "scalar_unsupported"
    return "scalar_compiled"


def print_conversion_readiness(
    location: MakerNoteTagLocation,
) -> MakerNotePrintConversionReadiness:
    entry = location.entry
    if not entry.has_print_conv:
        return "none"
    if entry.print_conv_kind == "hash":
        if entry.has_complete_scalar_print_conv_map:
            return "declarative_complete"
        return "declarative_partial"
    if maker_note_domain_print_conversion_adapter_supported(location):
        return "scalar_runtime_adapter"
    if entry.print_conv_kind == "scalar" and entry.print_conv_text:
        if maker_note_scalar_print_conversion_adapter_supported(entry.print_conv_text):
            return "scalar_runtime_adapter"
        if compile_safe_expression(entry.print_conv_text) is not None:
            return "scalar_compiled"
        return "scalar_unsupported"
    return "domain_adapter_required"


def traversal_readiness(
    location: MakerNoteTagLocation,
) -> MakerNoteTraversalReadiness:
    return "subdirectory_edge" if location.entry.subdirectory_tag_table else "none"


def maker_note_reader_readiness(
    *,
    condition: MakerNoteConditionReadiness,
    value_conversion: MakerNoteValueConversionReadiness,
    print_conversion: MakerNotePrintConversionReadiness,
    traversal: MakerNoteTraversalReadiness,
) -> MakerNoteReaderReadiness:
    if (
        condition in ("not_scalar", "unsupported")
        or value_conversion in ("scalar_unsupported", "domain_adapter_required")
        or print_conversion in ("scalar_unsupported", "domain_adapter_required")
    ):
        return "domain_adapter_required"
    if (
        condition == "none"
        and value_conversion == "none"
        and print_conversion == "none"
        and traversal == "none"
    ):
        return "static_metadata"
    if traversal == "subdirectory_edge":
        return "traversal_pipeline_ready"
    return "read_pipeline_ready"


def feature_signature(
    *,
    condition: MakerNoteConditionReadiness,
    value_conversion: MakerNoteValueConversionReadiness,
    print_conversion: MakerNotePrintConversionReadiness,
    traversal: MakerNoteTraversalReadiness,
) -> MakerNoteFeatureSignature:
    return (
        "condition="
        + condition
        + "|value="
        + value_conversion
        + "|print="
        + print_conversion
        + "|traversal="
        + traversal
    )


def maker_note_feature_surface_summary(
    report: MakerNoteFeatureSurfaceReport,
) -> JsonObject:
    return {
        "source_count": report.repository.source_count,
        "table_count": report.repository.table_count,
        "tag_entry_count": report.repository.tag_entry_count,
        "reader_ready_count": report.reader_ready_count,
        "domain_adapter_required_count": report.domain_adapter_required_count,
    }


def entries_with_reader_readiness(
    entries: tuple[MakerNoteFeatureSurfaceEntry, ...],
    readiness: MakerNoteReaderReadiness,
) -> tuple[MakerNoteFeatureSurfaceEntry, ...]:
    return tuple(entry for entry in entries if entry.reader_readiness == readiness)


def entries_without_domain_adapter(
    entries: tuple[MakerNoteFeatureSurfaceEntry, ...],
) -> tuple[MakerNoteFeatureSurfaceEntry, ...]:
    return tuple(entry for entry in entries if entry.reader_readiness != "domain_adapter_required")


def count_reader_readiness(
    entries: tuple[MakerNoteFeatureSurfaceEntry, ...],
    readiness: MakerNoteReaderReadiness,
) -> int:
    return sum(1 for entry in entries if entry.reader_readiness == readiness)


def top_counts(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    counter = Counter(value for value in values if value)
    return tuple(counter.most_common())


def top_typed_counts[T: str](values: Iterable[T]) -> tuple[tuple[T, int], ...]:
    counter = Counter(values)
    return tuple(counter.most_common())


def count_pairs_to_json[T: str](values: tuple[tuple[T, int], ...]) -> JsonArray:
    return [{"value": value, "count": count} for value, count in values]


def feature_surface_entries_to_json(
    entries: tuple[MakerNoteFeatureSurfaceEntry, ...],
) -> JsonArray:
    return [
        {
            "reader_readiness": entry.reader_readiness,
            "feature_signature": entry.feature_signature,
            "condition": entry.condition,
            "value_conversion": entry.value_conversion,
            "print_conversion": entry.print_conversion,
            "traversal": entry.traversal,
            "location": locations_to_json((entry.location,))[0],
        }
        for entry in entries
    ]
