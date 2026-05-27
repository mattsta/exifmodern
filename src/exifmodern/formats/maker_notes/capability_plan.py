"""Capability planning for migrated maker-note table packages."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.services.maker_note_tables import (
    MakerNoteFeatureKind,
    MakerNoteTableRepository,
    MakerNoteTagLocation,
    load_maker_note_table_repository,
)

type MakerNoteCapabilityStrategy = Literal[
    "direct_tag_metadata",
    "declarative_print_conversion",
    "safe_expression_print_conversion",
    "domain_print_conversion_adapter",
    "safe_expression_value_conversion",
    "domain_value_conversion_adapter",
    "condition_predicate_adapter",
    "subdirectory_adapter",
    "conditional_subdirectory_adapter",
    "compound_feature_adapter",
]


@dataclass(frozen=True)
class MakerNoteCapabilityGroup:
    strategy: MakerNoteCapabilityStrategy
    count: int
    samples: tuple[MakerNoteTagLocation, ...]


@dataclass(frozen=True)
class MakerNoteCapabilityPlan:
    repository: MakerNoteTableRepository
    groups: tuple[MakerNoteCapabilityGroup, ...]
    print_conv_kind_counts: tuple[tuple[MakerNoteFeatureKind, int], ...]
    value_conv_kind_counts: tuple[tuple[MakerNoteFeatureKind, int], ...]
    condition_kind_counts: tuple[tuple[MakerNoteFeatureKind, int], ...]
    subdirectory_kind_counts: tuple[tuple[MakerNoteFeatureKind, int], ...]

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "summary": {
                "source_count": self.repository.source_count,
                "loaded_source_count": self.repository.loaded_source_count,
                "table_count": self.repository.table_count,
                "tag_entry_count": self.repository.tag_entry_count,
                "strategy_count": len(self.groups),
            },
            "groups": groups_to_json(self.groups),
            "feature_kind_counts": {
                "print_conv": feature_counts_to_json(self.print_conv_kind_counts),
                "value_conv": feature_counts_to_json(self.value_conv_kind_counts),
                "condition": feature_counts_to_json(self.condition_kind_counts),
                "subdirectory": feature_counts_to_json(self.subdirectory_kind_counts),
            },
        }


def build_maker_note_capability_plan(
    maker_note_package: Path,
) -> MakerNoteCapabilityPlan:
    repository = load_maker_note_table_repository(maker_note_package)
    locations = repository.tag_entry_locations()
    return MakerNoteCapabilityPlan(
        repository=repository,
        groups=capability_groups(locations),
        print_conv_kind_counts=feature_kind_counts(
            location.entry.print_conv_kind for location in locations
        ),
        value_conv_kind_counts=feature_kind_counts(
            location.entry.value_conv_kind for location in locations
        ),
        condition_kind_counts=feature_kind_counts(
            location.entry.condition_kind for location in locations
        ),
        subdirectory_kind_counts=feature_kind_counts(
            location.entry.subdirectory_kind for location in locations
        ),
    )


def write_maker_note_capability_plan(
    maker_note_package: Path,
    output: Path,
) -> MakerNoteCapabilityPlan:
    plan = build_maker_note_capability_plan(maker_note_package)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(plan.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return plan


def maker_note_capability_plan_summary(plan: MakerNoteCapabilityPlan) -> JsonObject:
    return {
        "source_count": plan.repository.source_count,
        "table_count": plan.repository.table_count,
        "tag_entry_count": plan.repository.tag_entry_count,
        "strategy_count": len(plan.groups),
    }


def capability_groups(
    locations: tuple[MakerNoteTagLocation, ...],
) -> tuple[MakerNoteCapabilityGroup, ...]:
    grouped: dict[MakerNoteCapabilityStrategy, list[MakerNoteTagLocation]] = {}
    for location in locations:
        strategy = capability_strategy(location)
        grouped.setdefault(strategy, []).append(location)
    return tuple(
        MakerNoteCapabilityGroup(
            strategy=strategy,
            count=len(grouped[strategy]),
            samples=tuple(grouped[strategy][:10]),
        )
        for strategy in sorted(grouped, key=lambda key: len(grouped[key]), reverse=True)
    )


def capability_strategy(
    location: MakerNoteTagLocation,
) -> MakerNoteCapabilityStrategy:
    entry = location.entry
    feature_count = sum(
        (
            entry.has_print_conv,
            entry.has_value_conv,
            entry.has_condition,
            bool(entry.subdirectory_tag_table),
        )
    )
    if feature_count == 0:
        return "direct_tag_metadata"
    if entry.has_condition and entry.subdirectory_tag_table:
        return "conditional_subdirectory_adapter"
    if feature_count > 1:
        return "compound_feature_adapter"
    if entry.subdirectory_tag_table:
        return "subdirectory_adapter"
    if entry.has_condition:
        return "condition_predicate_adapter"
    if entry.has_value_conv:
        return value_conversion_strategy(entry.value_conv_kind)
    return print_conversion_strategy(location, entry.print_conv_kind)


def value_conversion_strategy(
    kind: MakerNoteFeatureKind,
) -> MakerNoteCapabilityStrategy:
    if kind == "scalar":
        return "safe_expression_value_conversion"
    return "domain_value_conversion_adapter"


def print_conversion_strategy(
    location: MakerNoteTagLocation,
    kind: MakerNoteFeatureKind,
) -> MakerNoteCapabilityStrategy:
    if kind == "hash" and location.entry.has_complete_scalar_print_conv_map:
        return "declarative_print_conversion"
    if kind == "scalar":
        return "safe_expression_print_conversion"
    return "domain_print_conversion_adapter"


def feature_kind_counts(
    values: Iterable[MakerNoteFeatureKind],
) -> tuple[tuple[MakerNoteFeatureKind, int], ...]:
    counter = Counter(values)
    return tuple(counter.most_common())


def groups_to_json(groups: tuple[MakerNoteCapabilityGroup, ...]) -> JsonArray:
    return [
        {
            "strategy": group.strategy,
            "description": capability_strategy_description(group.strategy),
            "count": group.count,
            "samples": locations_to_json(group.samples),
        }
        for group in groups
    ]


def capability_strategy_description(strategy: MakerNoteCapabilityStrategy) -> str:
    if strategy == "direct_tag_metadata":
        return "Static tag metadata with no extracted conversion or traversal feature."
    if strategy == "declarative_print_conversion":
        return "Hash-shaped PrintConv that can become declarative lookup data."
    if strategy == "safe_expression_print_conversion":
        return "Scalar PrintConv expression candidate for the safe-expression VM."
    if strategy == "domain_print_conversion_adapter":
        return "Non-scalar PrintConv requiring a typed domain adapter."
    if strategy == "safe_expression_value_conversion":
        return "Scalar ValueConv expression candidate for the safe-expression VM."
    if strategy == "domain_value_conversion_adapter":
        return "Non-scalar ValueConv requiring a typed domain adapter."
    if strategy == "condition_predicate_adapter":
        return "Condition-only predicate that should become a typed predicate adapter."
    if strategy == "subdirectory_adapter":
        return "SubDirectory traversal that should become a table-local adapter edge."
    if strategy == "conditional_subdirectory_adapter":
        return "Conditional SubDirectory traversal requiring predicate plus adapter edge."
    return "Multiple extracted features that should be migrated as one table-local adapter."


def feature_counts_to_json(
    counts: tuple[tuple[MakerNoteFeatureKind, int], ...],
) -> JsonArray:
    return [{"kind": kind, "count": count} for kind, count in counts]


def locations_to_json(locations: tuple[MakerNoteTagLocation, ...]) -> JsonArray:
    return [
        {
            "vendor": location.module.name,
            "module": location.module.module,
            "source_path": location.module.source_path,
            "table": location.table.name,
            "tag_id": location.entry.tag_id,
            "name": location.entry.name,
            "print_conv_kind": location.entry.print_conv_kind,
            "print_conv_count": location.entry.print_conv_count,
            "print_conv_pair_count": location.entry.print_conv_pair_count,
            "value_conv_kind": location.entry.value_conv_kind,
            "condition_kind": location.entry.condition_kind,
            "subdirectory_kind": location.entry.subdirectory_kind,
            "subdirectory_tag_table": location.entry.subdirectory_tag_table,
        }
        for location in locations
    ]
