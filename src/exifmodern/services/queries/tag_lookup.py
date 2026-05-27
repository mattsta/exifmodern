"""User-facing query and diagnostics for generated TagLookup packages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.services.generated_indexes import (
    TagLookupEntry,
    TagLookupRepository,
    TagLookupTableEntry,
    load_tag_lookup_repository,
)


@dataclass(frozen=True)
class TagLookupResolvedTable:
    table_number: int
    table_name: str
    tag_ids: tuple[str, ...]
    flattened_root_tag_id: str | None


@dataclass(frozen=True)
class TagLookupExplanation:
    requested_name: str
    lookup_key: str
    exists: bool
    exists_only: bool
    composite_module: str
    tables: tuple[TagLookupResolvedTable, ...]


@dataclass(frozen=True)
class TagLookupQueryResult:
    repository: TagLookupRepository
    explanations: tuple[TagLookupExplanation, ...]

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "summary": tag_lookup_repository_summary(self.repository),
            "explanations": explanations_to_json(self.explanations),
        }


@dataclass(frozen=True)
class TagLookupDiagnostics:
    repository: TagLookupRepository
    sample_entries: tuple[TagLookupExplanation, ...]

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "summary": tag_lookup_repository_summary(self.repository),
            "sample_entries": explanations_to_json(self.sample_entries),
        }


def run_tag_lookup_query(
    generated_index_package: Path,
    tag_names: tuple[str, ...],
) -> TagLookupQueryResult:
    repository = load_tag_lookup_repository(generated_index_package)
    return TagLookupQueryResult(
        repository=repository,
        explanations=tuple(explain_tag_lookup(repository, tag_name) for tag_name in tag_names),
    )


def write_tag_lookup_query_result(
    generated_index_package: Path,
    tag_names: tuple[str, ...],
    output: Path,
) -> TagLookupQueryResult:
    result = run_tag_lookup_query(generated_index_package, tag_names)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def tag_lookup_query_summary(result: TagLookupQueryResult) -> JsonObject:
    return {
        "requested_tag_count": len(result.explanations),
        "existing_tag_count": sum(1 for explanation in result.explanations if explanation.exists),
        "lookup_tag_count": len(result.repository.lookup),
        "table_count": len(result.repository.table_list),
    }


def build_tag_lookup_diagnostics(
    generated_index_package: Path,
) -> TagLookupDiagnostics:
    repository = load_tag_lookup_repository(generated_index_package)
    sample_keys = tuple(sorted(repository.lookup)[:25])
    return TagLookupDiagnostics(
        repository=repository,
        sample_entries=tuple(explain_tag_lookup(repository, tag_name) for tag_name in sample_keys),
    )


def write_tag_lookup_diagnostics(
    generated_index_package: Path,
    output: Path,
) -> TagLookupDiagnostics:
    diagnostics = build_tag_lookup_diagnostics(generated_index_package)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(diagnostics.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return diagnostics


def tag_lookup_diagnostics_summary(diagnostics: TagLookupDiagnostics) -> JsonObject:
    return tag_lookup_repository_summary(diagnostics.repository)


def explain_tag_lookup(
    repository: TagLookupRepository,
    tag_name: str,
) -> TagLookupExplanation:
    key = tag_name.lower()
    entry = repository.entry_for(tag_name)
    tables = () if entry is None else resolved_tables(repository, entry)
    return TagLookupExplanation(
        requested_name=tag_name,
        lookup_key=key,
        exists=repository.exists(tag_name),
        exists_only=entry is None and key in repository.tag_exists,
        composite_module=repository.composite_modules.get(key, ""),
        tables=tables,
    )


def resolved_tables(
    repository: TagLookupRepository,
    entry: TagLookupEntry,
) -> tuple[TagLookupResolvedTable, ...]:
    return tuple(
        resolved_table
        for table_entry in entry.tables
        if (resolved_table := resolved_table_entry(repository, table_entry)) is not None
    )


def resolved_table_entry(
    repository: TagLookupRepository,
    entry: TagLookupTableEntry,
) -> TagLookupResolvedTable | None:
    table_name = repository.table_name(entry.table_number)
    if table_name is None:
        return None
    return TagLookupResolvedTable(
        table_number=entry.table_number,
        table_name=table_name,
        tag_ids=entry.tag_ids,
        flattened_root_tag_id=entry.flattened_root_tag_id,
    )


def tag_lookup_repository_summary(repository: TagLookupRepository) -> JsonObject:
    return {
        "has_data": repository.has_data,
        "table_count": len(repository.table_list),
        "lookup_tag_count": len(repository.lookup),
        "tag_exists_count": len(repository.tag_exists),
        "composite_module_count": len(repository.composite_modules),
    }


def explanations_to_json(explanations: tuple[TagLookupExplanation, ...]) -> JsonArray:
    return [
        {
            "requested_name": explanation.requested_name,
            "lookup_key": explanation.lookup_key,
            "exists": explanation.exists,
            "exists_only": explanation.exists_only,
            "composite_module": explanation.composite_module,
            "tables": resolved_tables_to_json(explanation.tables),
        }
        for explanation in explanations
    ]


def resolved_tables_to_json(tables: tuple[TagLookupResolvedTable, ...]) -> JsonArray:
    return [
        {
            "table_number": table.table_number,
            "table_name": table.table_name,
            "tag_ids": list(table.tag_ids),
            "flattened_root_tag_id": table.flattened_root_tag_id,
        }
        for table in tables
    ]
