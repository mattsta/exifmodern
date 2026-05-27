"""Typed repository for migrated maker-note table package manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import (
    JsonValue,
    json_array_value,
    json_bool_value,
    json_int_value,
    json_string_array_value,
    json_string_value,
    load_json_object,
)
from exifmodern.package_resources import maker_note_shard_path
from exifmodern.runtime_data_shards import maker_note_shard_for_module

type MakerNoteFeatureKind = Literal[
    "none",
    "scalar",
    "hash",
    "array",
    "code",
    "regexp",
    "other",
]
type MakerNoteTagLocationKey = tuple[str, str, str, str]


@dataclass(frozen=True)
class MakerNotePrintConvPair:
    key: str
    value: str


@dataclass(frozen=True)
class MakerNoteTagEntry:
    tag_id: str
    name: str
    format: str
    writable: str
    group0: str
    group1: str
    group2: str
    has_print_conv: bool
    print_conv_kind: MakerNoteFeatureKind
    print_conv_count: int
    print_conv_text: str
    print_conv_pairs: tuple[MakerNotePrintConvPair, ...]
    has_value_conv: bool
    value_conv_kind: MakerNoteFeatureKind
    value_conv_count: int
    value_conv_text: str
    has_condition: bool
    condition_kind: MakerNoteFeatureKind
    condition_text: str
    subdirectory_kind: MakerNoteFeatureKind
    subdirectory_tag_table: str

    @property
    def print_conv_pair_count(self) -> int:
        return len(self.print_conv_pairs)

    @property
    def has_complete_scalar_print_conv_map(self) -> bool:
        return (
            self.print_conv_kind == "hash" and self.print_conv_pair_count == self.print_conv_count
        )

    def print_conversion_for(self, value: str) -> str | None:
        for pair in self.print_conv_pairs:
            if pair.key == value:
                return pair.value
        return None


@dataclass(frozen=True)
class MakerNoteTable:
    name: str
    key_count: int
    entry_count: int
    entries: tuple[MakerNoteTagEntry, ...]


@dataclass(frozen=True)
class MakerNoteModuleRecord:
    name: str
    source_path: str
    source_sha256: str
    module: str
    size_bytes: int
    line_count: int
    hash_count: int
    table_count: int
    tag_entry_count: int
    table_names: tuple[str, ...]
    tables: tuple[MakerNoteTable, ...]
    load_error: str

    def table(self, table_name: str) -> MakerNoteTable | None:
        requested_name = table_name.casefold()
        for table in self.tables:
            if table.name.casefold() == requested_name:
                return table
        return None


@dataclass(frozen=True)
class MakerNoteTagLocation:
    module: MakerNoteModuleRecord
    table: MakerNoteTable
    entry: MakerNoteTagEntry


@dataclass(frozen=True)
class MakerNotePrintConvLocation:
    location: MakerNoteTagLocation
    pair: MakerNotePrintConvPair


@dataclass(frozen=True)
class MakerNoteTableRepository:
    records: tuple[MakerNoteModuleRecord, ...]
    records_by_name: dict[str, MakerNoteModuleRecord]
    records_by_module: dict[str, MakerNoteModuleRecord]
    locations: tuple[MakerNoteTagLocation, ...]
    locations_by_tag_name: dict[str, tuple[MakerNoteTagLocation, ...]]
    locations_by_key: dict[MakerNoteTagLocationKey, tuple[MakerNoteTagLocation, ...]]

    @property
    def source_count(self) -> int:
        return len(self.records)

    @property
    def table_count(self) -> int:
        return sum(record.table_count for record in self.records)

    @property
    def loaded_source_count(self) -> int:
        return sum(1 for record in self.records if not record.load_error)

    @property
    def tag_entry_count(self) -> int:
        return sum(record.tag_entry_count for record in self.records)

    def module(self, module_name: str) -> MakerNoteModuleRecord | None:
        return self.records_by_module.get(module_name)

    def vendor(self, name: str) -> MakerNoteModuleRecord | None:
        return self.records_by_name.get(name.casefold())

    def modules_with_table(self, table_name: str) -> tuple[MakerNoteModuleRecord, ...]:
        requested_name = table_name.casefold()
        return tuple(
            record
            for record in self.records
            if any(name.casefold() == requested_name for name in record.table_names)
        )

    def tag_entries_named(self, tag_name: str) -> tuple[MakerNoteTagEntry, ...]:
        return tuple(location.entry for location in self.tag_entry_locations_named(tag_name))

    def tag_entry_locations_named(
        self,
        tag_name: str,
    ) -> tuple[MakerNoteTagLocation, ...]:
        return self.locations_by_tag_name.get(tag_name.casefold(), ())

    def tag_entry_locations(self) -> tuple[MakerNoteTagLocation, ...]:
        return self.locations

    def tag_entry_locations_for(
        self,
        *,
        vendor: str = "",
        module: str = "",
        table: str = "",
        tag_name: str = "",
        tag_id: str = "",
    ) -> tuple[MakerNoteTagLocation, ...]:
        if vendor and table and tag_name and tag_id:
            key = maker_note_tag_location_key(vendor, table, tag_name, tag_id)
            keyed = self.locations_by_key.get(key, ())
            if module:
                return tuple(location for location in keyed if location.module.module == module)
            return keyed
        return tuple(
            location
            for location in self.locations
            if maker_note_location_matches(
                location,
                vendor=vendor,
                module=module,
                table=table,
                tag_name=tag_name,
                tag_id=tag_id,
            )
        )

    def print_conv_locations(
        self,
        *,
        complete_only: bool,
    ) -> tuple[MakerNoteTagLocation, ...]:
        return tuple(
            location
            for location in self.locations
            if location.entry.print_conv_pair_count
            and (not complete_only or location.entry.has_complete_scalar_print_conv_map)
        )

    def print_conversion_locations(
        self,
        *,
        value: str,
        complete_only: bool,
    ) -> tuple[MakerNotePrintConvLocation, ...]:
        matches: list[MakerNotePrintConvLocation] = []
        for location in self.print_conv_locations(complete_only=complete_only):
            for pair in location.entry.print_conv_pairs:
                if pair.key == value:
                    matches.append(MakerNotePrintConvLocation(location, pair))
        return tuple(matches)

    def condition_locations(self) -> tuple[MakerNoteTagLocation, ...]:
        return tuple(location for location in self.locations if location.entry.has_condition)

    def subdirectory_locations(self) -> tuple[MakerNoteTagLocation, ...]:
        return tuple(
            location for location in self.locations if location.entry.subdirectory_tag_table
        )


def load_maker_note_table_repository(package_path: Path) -> MakerNoteTableRepository:
    package = load_json_object(package_path)
    records = tuple(
        record
        for item in json_array_value(package, "records")
        if (record := maker_note_module_record_from_json(item)) is not None
    )
    locations = maker_note_tag_locations(records)
    return MakerNoteTableRepository(
        records=records,
        records_by_name={record.name.casefold(): record for record in records},
        records_by_module={record.module: record for record in records},
        locations=locations,
        locations_by_tag_name=maker_note_tag_locations_by_name(locations),
        locations_by_key=maker_note_tag_locations_by_key(locations),
    )


def load_maker_note_table_repository_for_modules(
    package_path: Path,
    modules: tuple[str, ...],
) -> MakerNoteTableRepository:
    module_names = set(modules)
    if not module_names:
        return _maker_note_table_repository_from_records(())
    if package_path.name == "manifest.json" and package_path.parent.name == "makernote":
        shard_records = maker_note_module_records_from_shards(modules)
        if shard_records:
            return _maker_note_table_repository_from_records(shard_records)
    record_values = maker_note_module_record_json_values_for_modules(package_path, module_names)
    records = tuple(
        record
        for item in record_values
        if (record := maker_note_module_record_from_json(item)) is not None
    )
    return _maker_note_table_repository_from_records(records)


def maker_note_module_records_from_shards(
    modules: tuple[str, ...],
) -> tuple[MakerNoteModuleRecord, ...]:
    records: list[MakerNoteModuleRecord] = []
    for module_name in modules:
        shard = maker_note_shard_for_module(module_name)
        if shard is None:
            continue
        shard_path = maker_note_shard_path(shard)
        if shard_path is None:
            continue
        record = maker_note_module_record_from_json(load_json_object(shard_path))
        if record is not None:
            records.append(record)
    return tuple(records)


def _maker_note_table_repository_from_records(
    records: tuple[MakerNoteModuleRecord, ...],
) -> MakerNoteTableRepository:
    locations = maker_note_tag_locations(records)
    return MakerNoteTableRepository(
        records=records,
        records_by_name={record.name.casefold(): record for record in records},
        records_by_module={record.module: record for record in records},
        locations=locations,
        locations_by_tag_name=maker_note_tag_locations_by_name(locations),
        locations_by_key=maker_note_tag_locations_by_key(locations),
    )


def maker_note_module_record_json_values_for_modules(
    package_path: Path,
    module_names: set[str],
) -> tuple[JsonValue, ...]:
    records: list[JsonValue] = []
    package_bytes = package_path.read_bytes()
    for module_name in module_names:
        record_bytes = _maker_note_module_record_json_bytes(package_bytes, module_name)
        if record_bytes is not None:
            records.append(json.loads(record_bytes))
    return tuple(records)


def _maker_note_module_record_json_bytes(
    package_bytes: bytes,
    module_name: str,
) -> bytes | None:
    needle = f'"module": "{module_name}"'.encode()
    module_offset = package_bytes.find(needle)
    if module_offset < 0:
        return None
    record_start = package_bytes.rfind(b"\n    {", 0, module_offset)
    record_end = package_bytes.find(b"\n    }", module_offset)
    if record_start < 0 or record_end < 0:
        return None
    return package_bytes[record_start + 1 : record_end + len(b"\n    }")]


def maker_note_tag_locations(
    records: tuple[MakerNoteModuleRecord, ...],
) -> tuple[MakerNoteTagLocation, ...]:
    return tuple(
        MakerNoteTagLocation(record, table, entry)
        for record in records
        for table in record.tables
        for entry in table.entries
    )


def maker_note_tag_locations_by_name(
    locations: tuple[MakerNoteTagLocation, ...],
) -> dict[str, tuple[MakerNoteTagLocation, ...]]:
    grouped: dict[str, list[MakerNoteTagLocation]] = {}
    for location in locations:
        grouped.setdefault(location.entry.name.casefold(), []).append(location)
    return {name: tuple(name_locations) for name, name_locations in grouped.items()}


def maker_note_tag_locations_by_key(
    locations: tuple[MakerNoteTagLocation, ...],
) -> dict[MakerNoteTagLocationKey, tuple[MakerNoteTagLocation, ...]]:
    grouped: dict[MakerNoteTagLocationKey, list[MakerNoteTagLocation]] = {}
    for location in locations:
        key = maker_note_tag_location_key(
            location.module.name,
            location.table.name,
            location.entry.name,
            location.entry.tag_id,
        )
        grouped.setdefault(key, []).append(location)
    return {key: tuple(key_locations) for key, key_locations in grouped.items()}


def maker_note_tag_location_key(
    vendor: str,
    table: str,
    tag_name: str,
    tag_id: str,
) -> MakerNoteTagLocationKey:
    return (
        vendor.casefold(),
        table.casefold(),
        tag_name.casefold(),
        tag_id,
    )


def maker_note_location_matches(
    location: MakerNoteTagLocation,
    *,
    vendor: str,
    module: str,
    table: str,
    tag_name: str,
    tag_id: str,
) -> bool:
    if vendor and location.module.name.casefold() != vendor.casefold():
        return False
    if module and location.module.module != module:
        return False
    if table and location.table.name.casefold() != table.casefold():
        return False
    if tag_name and location.entry.name.casefold() != tag_name.casefold():
        return False
    return not tag_id or location.entry.tag_id == tag_id


def maker_note_module_record_from_json(value: JsonValue) -> MakerNoteModuleRecord | None:
    if not isinstance(value, dict):
        return None
    name = json_string_value(value, "name")
    source_path = json_string_value(value, "source_path")
    source_sha256 = json_string_value(value, "source_sha256")
    module = json_string_value(value, "module")
    size_bytes = json_int_value(value, "size_bytes")
    line_count = json_int_value(value, "line_count")
    hash_count = json_int_value(value, "hash_count")
    table_count = json_int_value(value, "table_count")
    tag_entry_count = json_int_value(value, "tag_entry_count")
    load_error = json_string_value(value, "load_error")
    if (
        name is None
        or source_path is None
        or source_sha256 is None
        or module is None
        or size_bytes is None
        or line_count is None
        or hash_count is None
        or table_count is None
        or tag_entry_count is None
        or load_error is None
    ):
        return None
    tables = tuple(
        table
        for item in json_array_value(value, "tables")
        if (table := maker_note_table_from_json(item)) is not None
    )
    return MakerNoteModuleRecord(
        name=name,
        source_path=source_path,
        source_sha256=source_sha256,
        module=module,
        size_bytes=size_bytes,
        line_count=line_count,
        hash_count=hash_count,
        table_count=table_count,
        tag_entry_count=tag_entry_count,
        table_names=tuple(json_string_array_value(value, "table_names")),
        tables=tables,
        load_error=load_error,
    )


def maker_note_table_from_json(value: JsonValue) -> MakerNoteTable | None:
    if not isinstance(value, dict):
        return None
    name = json_string_value(value, "name")
    key_count = json_int_value(value, "key_count")
    entry_count = json_int_value(value, "entry_count")
    if name is None or key_count is None or entry_count is None:
        return None
    entries = tuple(
        entry
        for item in json_array_value(value, "entries")
        if (entry := maker_note_tag_entry_from_json(item)) is not None
    )
    return MakerNoteTable(
        name=name,
        key_count=key_count,
        entry_count=entry_count,
        entries=entries,
    )


def maker_note_tag_entry_from_json(value: JsonValue) -> MakerNoteTagEntry | None:
    if not isinstance(value, dict):
        return None
    tag_id = json_string_value(value, "tag_id")
    name = json_string_value(value, "name")
    format_name = json_string_value(value, "format")
    writable = json_string_value(value, "writable")
    group0 = json_string_value(value, "group0")
    group1 = json_string_value(value, "group1")
    group2 = json_string_value(value, "group2")
    has_print_conv = json_bool_value(value, "has_print_conv")
    print_conv_kind = maker_note_feature_kind(json_string_value(value, "print_conv_kind"))
    print_conv_count = json_int_value(value, "print_conv_count")
    print_conv_text = json_string_value(value, "print_conv_text")
    print_conv_pairs = tuple(
        pair
        for item in json_array_value(value, "print_conv_pairs")
        if (pair := maker_note_print_conv_pair_from_json(item)) is not None
    )
    has_value_conv = json_bool_value(value, "has_value_conv")
    value_conv_kind = maker_note_feature_kind(json_string_value(value, "value_conv_kind"))
    value_conv_count = json_int_value(value, "value_conv_count")
    value_conv_text = json_string_value(value, "value_conv_text")
    has_condition = json_bool_value(value, "has_condition")
    condition_kind = maker_note_feature_kind(json_string_value(value, "condition_kind"))
    condition_text = json_string_value(value, "condition_text")
    subdirectory_kind = maker_note_feature_kind(json_string_value(value, "subdirectory_kind"))
    subdirectory_tag_table = json_string_value(value, "subdirectory_tag_table")
    if (
        tag_id is None
        or name is None
        or format_name is None
        or writable is None
        or group0 is None
        or group1 is None
        or group2 is None
        or has_print_conv is None
        or print_conv_count is None
        or print_conv_text is None
        or has_value_conv is None
        or value_conv_count is None
        or value_conv_text is None
        or has_condition is None
        or condition_text is None
        or subdirectory_tag_table is None
    ):
        return None
    return MakerNoteTagEntry(
        tag_id=tag_id,
        name=name,
        format=format_name,
        writable=writable,
        group0=group0,
        group1=group1,
        group2=group2,
        has_print_conv=has_print_conv,
        print_conv_kind=print_conv_kind,
        print_conv_count=print_conv_count,
        print_conv_text=print_conv_text,
        print_conv_pairs=print_conv_pairs,
        has_value_conv=has_value_conv,
        value_conv_kind=value_conv_kind,
        value_conv_count=value_conv_count,
        value_conv_text=value_conv_text,
        has_condition=has_condition,
        condition_kind=condition_kind,
        condition_text=condition_text,
        subdirectory_kind=subdirectory_kind,
        subdirectory_tag_table=subdirectory_tag_table,
    )


def maker_note_print_conv_pair_from_json(value: JsonValue) -> MakerNotePrintConvPair | None:
    if not isinstance(value, dict):
        return None
    key = json_string_value(value, "key")
    mapped_value = json_string_value(value, "value")
    if key is None or mapped_value is None:
        return None
    return MakerNotePrintConvPair(key=key, value=mapped_value)


def maker_note_feature_kind(value: str | None) -> MakerNoteFeatureKind:
    if value == "scalar":
        return "scalar"
    if value == "hash":
        return "hash"
    if value == "array":
        return "array"
    if value == "code":
        return "code"
    if value == "regexp":
        return "regexp"
    if value == "other":
        return "other"
    return "none"
