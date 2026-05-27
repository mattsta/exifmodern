"""Declarative PrintConv index and lookup over migrated maker-note packages."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.services.maker_note_tables import (
    MakerNotePrintConvLocation,
    MakerNoteTableRepository,
    MakerNoteTagLocation,
    load_maker_note_table_repository,
)


@dataclass(frozen=True)
class MakerNotePrintConvIndex:
    repository: MakerNoteTableRepository
    complete_locations: tuple[MakerNoteTagLocation, ...]
    partial_locations: tuple[MakerNoteTagLocation, ...]
    top_modules_by_pair_count: tuple[tuple[str, int], ...]
    top_tables_by_pair_count: tuple[tuple[str, int], ...]
    top_tag_names_by_pair_count: tuple[tuple[str, int], ...]

    @property
    def complete_pair_count(self) -> int:
        return sum(location.entry.print_conv_pair_count for location in self.complete_locations)

    @property
    def partial_pair_count(self) -> int:
        return sum(location.entry.print_conv_pair_count for location in self.partial_locations)

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "summary": {
                "source_count": self.repository.source_count,
                "table_count": self.repository.table_count,
                "tag_entry_count": self.repository.tag_entry_count,
                "complete_map_count": len(self.complete_locations),
                "complete_pair_count": self.complete_pair_count,
                "partial_map_count": len(self.partial_locations),
                "partial_pair_count": self.partial_pair_count,
            },
            "top_modules_by_pair_count": count_pairs_to_json(self.top_modules_by_pair_count[:50]),
            "top_tables_by_pair_count": count_pairs_to_json(self.top_tables_by_pair_count[:50]),
            "top_tag_names_by_pair_count": count_pairs_to_json(
                self.top_tag_names_by_pair_count[:50]
            ),
            "sample_complete_maps": locations_to_json(self.complete_locations[:25]),
            "sample_partial_maps": locations_to_json(self.partial_locations[:25]),
        }


@dataclass(frozen=True)
class MakerNotePrintConvLookupRequest:
    value: str
    vendor: str = ""
    module: str = ""
    table: str = ""
    tag_name: str = ""
    complete_only: bool = True
    limit: int | None = None


@dataclass(frozen=True)
class MakerNotePrintConvLookupResult:
    request: MakerNotePrintConvLookupRequest
    repository: MakerNoteTableRepository
    matches: tuple[MakerNotePrintConvLocation, ...]

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "request": lookup_request_to_json(self.request),
            "match_count": len(self.matches),
            "matches": print_conv_matches_to_json(self.matches),
        }


def build_maker_note_print_conv_index(
    maker_note_package: Path,
) -> MakerNotePrintConvIndex:
    repository = load_maker_note_table_repository(maker_note_package)
    complete_locations = repository.print_conv_locations(complete_only=True)
    all_locations = repository.print_conv_locations(complete_only=False)
    partial_locations = tuple(
        location
        for location in all_locations
        if not location.entry.has_complete_scalar_print_conv_map
    )
    return MakerNotePrintConvIndex(
        repository=repository,
        complete_locations=complete_locations,
        partial_locations=partial_locations,
        top_modules_by_pair_count=top_pair_counts(
            f"{location.module.name} ({location.module.module})"
            for location in all_locations
            for _pair in location.entry.print_conv_pairs
        ),
        top_tables_by_pair_count=top_pair_counts(
            f"{location.module.name}:{location.table.name}"
            for location in all_locations
            for _pair in location.entry.print_conv_pairs
        ),
        top_tag_names_by_pair_count=top_pair_counts(
            location.entry.name
            for location in all_locations
            for _pair in location.entry.print_conv_pairs
        ),
    )


def write_maker_note_print_conv_index(
    maker_note_package: Path,
    output: Path,
) -> MakerNotePrintConvIndex:
    index = build_maker_note_print_conv_index(maker_note_package)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(index.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return index


def maker_note_print_conv_index_summary(index: MakerNotePrintConvIndex) -> JsonObject:
    return {
        "complete_map_count": len(index.complete_locations),
        "complete_pair_count": index.complete_pair_count,
        "partial_map_count": len(index.partial_locations),
        "partial_pair_count": index.partial_pair_count,
    }


def run_maker_note_print_conv_lookup(
    maker_note_package: Path,
    request: MakerNotePrintConvLookupRequest,
) -> MakerNotePrintConvLookupResult:
    repository = load_maker_note_table_repository(maker_note_package)
    matches = tuple(
        match
        for match in repository.print_conversion_locations(
            value=request.value,
            complete_only=request.complete_only,
        )
        if print_conv_match_satisfies_request(match, request)
    )
    limited_matches = matches if request.limit is None else matches[: request.limit]
    return MakerNotePrintConvLookupResult(
        request=request,
        repository=repository,
        matches=limited_matches,
    )


def write_maker_note_print_conv_lookup_result(
    maker_note_package: Path,
    request: MakerNotePrintConvLookupRequest,
    output: Path,
) -> MakerNotePrintConvLookupResult:
    result = run_maker_note_print_conv_lookup(maker_note_package, request)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def maker_note_print_conv_lookup_summary(
    result: MakerNotePrintConvLookupResult,
) -> JsonObject:
    return {
        "match_count": len(result.matches),
        "source_count": result.repository.source_count,
        "table_count": result.repository.table_count,
        "tag_entry_count": result.repository.tag_entry_count,
    }


def print_conv_match_satisfies_request(
    match: MakerNotePrintConvLocation,
    request: MakerNotePrintConvLookupRequest,
) -> bool:
    location = match.location
    if request.vendor and location.module.name.casefold() != request.vendor.casefold():
        return False
    if request.module and location.module.module != request.module:
        return False
    if request.table and location.table.name.casefold() != request.table.casefold():
        return False
    return not request.tag_name or location.entry.name.casefold() == request.tag_name.casefold()


def top_pair_counts(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    counter = Counter(value for value in values if value)
    return tuple(counter.most_common())


def count_pairs_to_json(values: tuple[tuple[str, int], ...]) -> JsonArray:
    return [{"value": value, "count": count} for value, count in values]


def lookup_request_to_json(request: MakerNotePrintConvLookupRequest) -> JsonObject:
    return {
        "value": request.value,
        "vendor": request.vendor,
        "module": request.module,
        "table": request.table,
        "tag_name": request.tag_name,
        "complete_only": request.complete_only,
        "limit": request.limit,
    }


def locations_to_json(locations: tuple[MakerNoteTagLocation, ...]) -> JsonArray:
    return [
        {
            "vendor": location.module.name,
            "module": location.module.module,
            "source_path": location.module.source_path,
            "table": location.table.name,
            "tag_id": location.entry.tag_id,
            "name": location.entry.name,
            "print_conv_count": location.entry.print_conv_count,
            "print_conv_text": location.entry.print_conv_text,
            "print_conv_pair_count": location.entry.print_conv_pair_count,
            "complete": location.entry.has_complete_scalar_print_conv_map,
        }
        for location in locations
    ]


def print_conv_matches_to_json(
    matches: tuple[MakerNotePrintConvLocation, ...],
) -> JsonArray:
    return [
        {
            "vendor": match.location.module.name,
            "module": match.location.module.module,
            "source_path": match.location.module.source_path,
            "table": match.location.table.name,
            "tag_id": match.location.entry.tag_id,
            "name": match.location.entry.name,
            "key": match.pair.key,
            "value": match.pair.value,
            "complete": match.location.entry.has_complete_scalar_print_conv_map,
        }
        for match in matches
    ]
