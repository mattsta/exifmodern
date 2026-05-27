"""Executable query surface for migrated maker-note table packages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from exifmodern.json_types import JsonArray, JsonObject
from exifmodern.services.maker_note_tables import (
    MakerNoteTableRepository,
    MakerNoteTagLocation,
    load_maker_note_table_repository,
)


@dataclass(frozen=True)
class MakerNoteQueryRequest:
    vendor: str = ""
    module: str = ""
    table: str = ""
    tag_name: str = ""
    has_print_conv: bool = False
    has_value_conv: bool = False
    has_condition: bool = False
    has_subdirectory: bool = False
    has_complete_print_conv_map: bool = False
    has_partial_print_conv_map: bool = False
    print_conv_key: str = ""
    limit: int | None = None


@dataclass(frozen=True)
class MakerNoteQueryResult:
    request: MakerNoteQueryRequest
    repository: MakerNoteTableRepository
    matches: tuple[MakerNoteTagLocation, ...]

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "request": request_to_json(self.request),
            "source_count": self.repository.source_count,
            "table_count": self.repository.table_count,
            "tag_entry_count": self.repository.tag_entry_count,
            "match_count": len(self.matches),
            "matches": locations_to_json(self.matches),
        }


def run_maker_note_query(
    maker_note_package: Path,
    request: MakerNoteQueryRequest,
) -> MakerNoteQueryResult:
    repository = load_maker_note_table_repository(maker_note_package)
    return MakerNoteQueryResult(
        request=request,
        repository=repository,
        matches=query_locations(repository, request),
    )


def write_maker_note_query_result(
    maker_note_package: Path,
    request: MakerNoteQueryRequest,
    output: Path,
) -> MakerNoteQueryResult:
    result = run_maker_note_query(maker_note_package, request)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def maker_note_query_summary(result: MakerNoteQueryResult) -> JsonObject:
    return {
        "match_count": len(result.matches),
        "source_count": result.repository.source_count,
        "table_count": result.repository.table_count,
        "tag_entry_count": result.repository.tag_entry_count,
    }


def query_locations(
    repository: MakerNoteTableRepository,
    request: MakerNoteQueryRequest,
) -> tuple[MakerNoteTagLocation, ...]:
    matches: list[MakerNoteTagLocation] = []
    for location in repository.tag_entry_locations():
        if not location_matches_request(location, request):
            continue
        matches.append(location)
        if request.limit is not None and len(matches) >= request.limit:
            break
    return tuple(matches)


def location_matches_request(
    location: MakerNoteTagLocation,
    request: MakerNoteQueryRequest,
) -> bool:
    if request.vendor and location.module.name.casefold() != request.vendor.casefold():
        return False
    if request.module and location.module.module != request.module:
        return False
    if request.table and location.table.name.casefold() != request.table.casefold():
        return False
    if request.tag_name and location.entry.name.casefold() != request.tag_name.casefold():
        return False
    if request.has_print_conv and not location.entry.has_print_conv:
        return False
    if request.has_value_conv and not location.entry.has_value_conv:
        return False
    if request.has_condition and not location.entry.has_condition:
        return False
    if request.has_subdirectory and not location.entry.subdirectory_tag_table:
        return False
    if (
        request.has_complete_print_conv_map
        and not location.entry.has_complete_scalar_print_conv_map
    ):
        return False
    if request.has_partial_print_conv_map and (
        not location.entry.print_conv_pair_count
        or location.entry.has_complete_scalar_print_conv_map
    ):
        return False
    return not request.print_conv_key or any(
        pair.key == request.print_conv_key for pair in location.entry.print_conv_pairs
    )


def request_to_json(request: MakerNoteQueryRequest) -> JsonObject:
    return {
        "vendor": request.vendor,
        "module": request.module,
        "table": request.table,
        "tag_name": request.tag_name,
        "has_print_conv": request.has_print_conv,
        "has_value_conv": request.has_value_conv,
        "has_condition": request.has_condition,
        "has_subdirectory": request.has_subdirectory,
        "has_complete_print_conv_map": request.has_complete_print_conv_map,
        "has_partial_print_conv_map": request.has_partial_print_conv_map,
        "print_conv_key": request.print_conv_key,
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
            "format": location.entry.format,
            "writable": location.entry.writable,
            "group0": location.entry.group0,
            "group1": location.entry.group1,
            "group2": location.entry.group2,
            "has_print_conv": location.entry.has_print_conv,
            "print_conv_kind": location.entry.print_conv_kind,
            "print_conv_count": location.entry.print_conv_count,
            "print_conv_text": location.entry.print_conv_text,
            "print_conv_pair_count": location.entry.print_conv_pair_count,
            "print_conv_pairs": [
                {"key": pair.key, "value": pair.value} for pair in location.entry.print_conv_pairs
            ],
            "has_value_conv": location.entry.has_value_conv,
            "value_conv_kind": location.entry.value_conv_kind,
            "value_conv_count": location.entry.value_conv_count,
            "value_conv_text": location.entry.value_conv_text,
            "has_condition": location.entry.has_condition,
            "condition_kind": location.entry.condition_kind,
            "condition_text": location.entry.condition_text,
            "subdirectory_kind": location.entry.subdirectory_kind,
            "subdirectory_tag_table": location.entry.subdirectory_tag_table,
        }
        for location in locations
    ]
