"""Typed repositories for migrated generated ExifTool indexes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.json_types import (
    JsonObject,
    JsonValue,
    json_array_value,
    json_int_value,
    json_object_items,
    json_string_array_value,
    json_string_value,
    load_json_object,
)
from exifmodern.package_resources import generated_index_shard_path


@dataclass(frozen=True)
class TagLookupTableEntry:
    table_number: int
    tag_ids: tuple[str, ...]
    flattened_root_tag_id: str | None


@dataclass(frozen=True)
class TagLookupEntry:
    tag_name: str
    tables: tuple[TagLookupTableEntry, ...]


@dataclass(frozen=True)
class TagLookupRepository:
    table_list: tuple[str, ...]
    lookup: dict[str, TagLookupEntry]
    tag_exists: frozenset[str]
    composite_modules: dict[str, str]

    @property
    def has_data(self) -> bool:
        return bool(self.table_list or self.lookup or self.tag_exists or self.composite_modules)

    def exists(self, tag_name: str) -> bool:
        key = tag_name.lower()
        return key in self.tag_exists or key in self.lookup

    def entry_for(self, tag_name: str) -> TagLookupEntry | None:
        return self.lookup.get(tag_name.lower())

    def table_name(self, table_number: int) -> str | None:
        if table_number < 0 or table_number >= len(self.table_list):
            return None
        return self.table_list[table_number]


def load_tag_lookup_repository(package_path: Path) -> TagLookupRepository:
    shard_path = (
        generated_index_shard_path("tag_lookup")
        if _is_generated_index_manifest_path(package_path)
        else None
    )
    if shard_path is not None:
        return tag_lookup_repository_from_json(load_json_object(shard_path))
    package = load_json_object(package_path)
    if "lookup" in package and "table_list" in package:
        return tag_lookup_repository_from_json(package)
    for index_value in json_array_value(package, "indexes"):
        if not isinstance(index_value, dict):
            continue
        if json_string_value(index_value, "kind") != "tag_lookup":
            continue
        data = json_object_items(index_value, "data")
        return tag_lookup_repository_from_json(data)
    return TagLookupRepository(
        table_list=(),
        lookup={},
        tag_exists=frozenset(),
        composite_modules={},
    )


def _is_generated_index_manifest_path(path: Path) -> bool:
    return path.name == "manifest.json" and path.parent.name == "generated-index"


def tag_lookup_repository_from_json(value: JsonObject) -> TagLookupRepository:
    table_list = tuple(json_string_array_value(value, "table_list"))
    lookup: dict[str, TagLookupEntry] = {}
    for entry_value in json_array_value(value, "lookup"):
        entry = tag_lookup_entry_from_json(entry_value)
        if entry is not None:
            lookup[entry.tag_name] = entry
    return TagLookupRepository(
        table_list=table_list,
        lookup=lookup,
        tag_exists=frozenset(json_string_array_value(value, "tag_exists")),
        composite_modules=string_map(json_object_items(value, "composite_modules")),
    )


def tag_lookup_entry_from_json(value: JsonValue) -> TagLookupEntry | None:
    if not isinstance(value, dict):
        return None
    tag_name = json_string_value(value, "tag_name")
    if tag_name is None:
        return None
    tables: list[TagLookupTableEntry] = []
    for table_value in json_array_value(value, "tables"):
        table = tag_lookup_table_entry_from_json(table_value)
        if table is not None:
            tables.append(table)
    return TagLookupEntry(tag_name=tag_name, tables=tuple(tables))


def tag_lookup_table_entry_from_json(value: JsonValue) -> TagLookupTableEntry | None:
    if not isinstance(value, dict):
        return None
    table_number = json_int_value(value, "table_number")
    if table_number is None:
        return None
    return TagLookupTableEntry(
        table_number=table_number,
        tag_ids=tuple(json_string_array_value(value, "tag_ids")),
        flattened_root_tag_id=json_string_value(value, "flattened_root_tag_id"),
    )


def string_map(value: JsonObject) -> dict[str, str]:
    strings: dict[str, str] = {}
    for key, item in value.items():
        if isinstance(item, str):
            strings[key] = item
    return strings
