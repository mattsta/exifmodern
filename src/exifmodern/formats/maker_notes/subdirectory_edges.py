"""SubDirectory edge graph diagnostics for maker-note packages."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.services.maker_note_tables import (
    MakerNoteTableRepository,
    MakerNoteTagLocation,
    load_maker_note_table_repository,
)
from exifmodern.services.queries.maker_note import locations_to_json


@dataclass(frozen=True)
class MakerNoteSubdirectoryTarget:
    module: str
    table: str


@dataclass(frozen=True)
class MakerNoteSubdirectoryEdge:
    source: MakerNoteTagLocation
    target: MakerNoteSubdirectoryTarget
    target_exists: bool

    @property
    def conditional(self) -> bool:
        return self.source.entry.has_condition


@dataclass(frozen=True)
class MakerNoteSubdirectoryEdgeReport:
    repository: MakerNoteTableRepository
    edges: tuple[MakerNoteSubdirectoryEdge, ...]
    top_targets: tuple[tuple[str, int], ...]
    top_vendors: tuple[tuple[str, int], ...]

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def conditional_edge_count(self) -> int:
        return sum(1 for edge in self.edges if edge.conditional)

    @property
    def missing_target_count(self) -> int:
        return sum(1 for edge in self.edges if not edge.target_exists)

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "summary": {
                "source_count": self.repository.source_count,
                "table_count": self.repository.table_count,
                "tag_entry_count": self.repository.tag_entry_count,
                "edge_count": self.edge_count,
                "conditional_edge_count": self.conditional_edge_count,
                "missing_target_count": self.missing_target_count,
            },
            "top_targets": count_pairs_to_json(self.top_targets[:50]),
            "top_vendors": count_pairs_to_json(self.top_vendors[:50]),
            "sample_edges": maker_note_subdirectory_edges_to_json(self.edges[:100]),
        }


def build_maker_note_subdirectory_edge_report(
    maker_note_package: Path,
) -> MakerNoteSubdirectoryEdgeReport:
    repository = load_maker_note_table_repository(maker_note_package)
    edges = tuple(
        maker_note_subdirectory_edge(repository, location)
        for location in repository.subdirectory_locations()
    )
    return MakerNoteSubdirectoryEdgeReport(
        repository=repository,
        edges=edges,
        top_targets=top_counts(edge.target.module + "::" + edge.target.table for edge in edges),
        top_vendors=top_counts(edge.source.module.name for edge in edges),
    )


def maker_note_subdirectory_edge(
    repository: MakerNoteTableRepository,
    location: MakerNoteTagLocation,
) -> MakerNoteSubdirectoryEdge:
    target = maker_note_subdirectory_target(location.entry.subdirectory_tag_table)
    target_module = repository.module(target.module)
    target_exists = target_module is not None and target_module.table(target.table) is not None
    return MakerNoteSubdirectoryEdge(
        source=location,
        target=target,
        target_exists=target_exists,
    )


def maker_note_subdirectory_target(tag_table: str) -> MakerNoteSubdirectoryTarget:
    module, separator, table = tag_table.rpartition("::")
    if not separator:
        return MakerNoteSubdirectoryTarget(module="", table=tag_table)
    return MakerNoteSubdirectoryTarget(module=module, table=table)


def write_maker_note_subdirectory_edge_report(
    maker_note_package: Path,
    output: Path,
) -> MakerNoteSubdirectoryEdgeReport:
    report = build_maker_note_subdirectory_edge_report(maker_note_package)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def maker_note_subdirectory_edge_summary(
    report: MakerNoteSubdirectoryEdgeReport,
) -> JsonObject:
    return {
        "edge_count": report.edge_count,
        "conditional_edge_count": report.conditional_edge_count,
        "missing_target_count": report.missing_target_count,
        "source_count": report.repository.source_count,
        "table_count": report.repository.table_count,
        "tag_entry_count": report.repository.tag_entry_count,
    }


def maker_note_subdirectory_edges_to_json(
    edges: tuple[MakerNoteSubdirectoryEdge, ...],
) -> JsonArray:
    return [
        {
            "source": locations_to_json((edge.source,))[0],
            "target_module": edge.target.module,
            "target_table": edge.target.table,
            "target_exists": edge.target_exists,
            "conditional": edge.conditional,
        }
        for edge in edges
    ]


def top_counts(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    counter = Counter(value for value in values if value)
    return tuple(counter.most_common())


def count_pairs_to_json(values: tuple[tuple[str, int], ...]) -> JsonArray:
    return [{"value": value, "count": count} for value, count in values]
