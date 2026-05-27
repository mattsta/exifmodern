"""Generated ExifTool lens table adapters for the lens identity service."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import JsonObject, JsonValue, load_json_object
from exifmodern.package_resources import generated_index_shard_path
from exifmodern.services.lens_identity import LensIdentityEntry, LensIdentityTable
from exifmodern.services.lens_identity_repository import (
    SourceLensIdentityFamily,
    SourceLensIdentityFamilyName,
    SourceLensIdentityRepository,
    SourceLensIdentityTableRecord,
)

type LensIdentityOwner = Literal[
    "canon",
    "minolta",
    "nikon",
    "olympus_micro_four_thirds",
    "pentax",
    "panasonic_leica",
    "sony",
    "sigma",
    "samsung",
    "leica",
]


@dataclass(frozen=True)
class LensIdentitySourceTable:
    owner: LensIdentityOwner
    source_module: str
    source_file: str | None
    variable: str
    source_entry_count: int
    normalized_entry_count: int
    skipped_entry_count: int
    table: LensIdentityTable


@dataclass(frozen=True)
class LensIdentityTableExport:
    owner: LensIdentityOwner
    source_module: str
    source_file: str | None
    variable: str
    source_entry_count: int
    normalized_entry_count: int
    skipped_entry_count: int
    entries: tuple[LensIdentityEntry, ...]


@dataclass(frozen=True)
class LensIdentityTableIndex:
    schema_version: int
    generated_at_epoch: int
    source_schema: str
    table_count: int
    tables: tuple[LensIdentityTableExport, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


type LensIdentityPackageTableKey = tuple[LensIdentityOwner, str]

PACKAGE_FAMILY_BY_TABLE: dict[LensIdentityPackageTableKey, SourceLensIdentityFamilyName] = {
    ("canon", "RFLensType.PrintConv"): "canon_rf_lens_type",
    ("canon", "canonLensTypes"): "canon_lens_types",
    ("minolta", "minoltaLensTypes"): "minolta_a_mount",
    ("minolta", "minoltaTeleconverters"): "minolta_teleconverters",
    ("nikon", "nikonLensIDs"): "nikon_lens_ids",
    ("nikon", "nikonLensIDs+LensData0800.LensID.PrintConv"): "nikon_lens_ids",
    ("olympus_micro_four_thirds", "olympusLensTypes"): "olympus_micro_four_thirds",
    ("panasonic_leica", "leicaLensTypes"): "panasonic_leica",
    ("pentax", "pentaxLensTypes"): "pentax_lens_types",
    ("sigma", "sigmaLensTypes"): "sigma_lens_types",
    ("sony", "sonyLensTypes"): "sony_a_mount",
    ("sony", "sonyLensTypes2"): "sony_e_mount",
    ("leica", "leicaLensTypes"): "panasonic_leica",
}


@dataclass(frozen=True)
class LensIdentityPackageRepository:
    schema_version: int
    source_schema: str
    tables: tuple[LensIdentitySourceTable, ...]

    @property
    def table_count(self) -> int:
        return len(self.tables)

    @property
    def total_entry_count(self) -> int:
        return sum(table.normalized_entry_count for table in self.tables)

    def tables_for_owner(self, owner: LensIdentityOwner) -> tuple[LensIdentitySourceTable, ...]:
        return tuple(table for table in self.tables if table.owner == owner)

    def table_for_variable(
        self,
        owner: LensIdentityOwner,
        variable: str,
    ) -> LensIdentitySourceTable | None:
        for table in self.tables:
            if table.owner == owner and table.variable == variable:
                return table
        return None

    def source_lens_identity_repository(self) -> SourceLensIdentityRepository:
        families: list[SourceLensIdentityFamily] = []
        for table in self.tables:
            family = PACKAGE_FAMILY_BY_TABLE.get((table.owner, table.variable))
            if family is None:
                continue
            families.append(
                SourceLensIdentityTableRecord(
                    family=family,
                    status="loaded",
                    owner=table.owner,
                    source_module=table.source_module,
                    source_paths=source_paths_for_package_table(table),
                    variable=table.variable,
                    table=table.table,
                )
            )
        return SourceLensIdentityRepository(
            exiftool_root=Path(self.source_schema).parent,
            families=tuple(families),
        )


def load_lens_identity_package_repository(package_path: Path) -> LensIdentityPackageRepository:
    shard_path = (
        generated_index_shard_path("lens_identity")
        if package_path.name == "manifest.json" and package_path.parent.name == "generated-index"
        else None
    )
    package = load_json_object(shard_path or package_path)
    return lens_identity_package_repository_from_json(package)


def source_lens_identity_repository_from_lens_package(
    package_path: Path,
) -> SourceLensIdentityRepository:
    return load_lens_identity_package_repository(package_path).source_lens_identity_repository()


def lens_identity_package_repository_from_json(
    package: JsonObject,
) -> LensIdentityPackageRepository:
    return LensIdentityPackageRepository(
        schema_version=json_int(package.get("schema_version")) or 0,
        source_schema=json_string(package.get("source_schema")) or "",
        tables=load_lens_identity_source_tables_from_package(package),
    )


def load_lens_identity_source_tables(schema_path: Path) -> tuple[LensIdentitySourceTable, ...]:
    schema = load_json_object(schema_path)
    package_tables = load_lens_identity_source_tables_from_package(schema)
    if package_tables:
        return package_tables
    tables_value = schema.get("lens_identity_tables")
    if not isinstance(tables_value, list):
        return ()
    tables: list[LensIdentitySourceTable] = []
    for table_value in tables_value:
        if not isinstance(table_value, dict):
            continue
        table = lens_identity_source_table(table_value)
        if table is not None:
            tables.append(table)
    return tuple(tables)


def lens_identity_table_for_owner(
    schema_path: Path,
    owner: LensIdentityOwner,
) -> LensIdentityTable:
    for source_table in load_lens_identity_source_tables(schema_path):
        if source_table.owner == owner:
            return source_table.table
    return LensIdentityTable(entries=())


def load_lens_identity_source_tables_from_package(
    package: JsonObject,
) -> tuple[LensIdentitySourceTable, ...]:
    tables: list[LensIdentitySourceTable] = []
    tables_value = package.get("tables")
    if not isinstance(tables_value, list):
        return ()
    for table_value in tables_value:
        if not isinstance(table_value, dict):
            continue
        table = lens_identity_source_table_from_package(table_value)
        if table is not None:
            tables.append(table)
    return tuple(tables)


def build_lens_identity_table_index(schema_path: Path) -> LensIdentityTableIndex:
    source_tables = load_lens_identity_source_tables(schema_path)
    exports = tuple(lens_identity_table_export(table) for table in source_tables)
    return LensIdentityTableIndex(
        schema_version=1,
        generated_at_epoch=int(time.time()),
        source_schema=schema_path.as_posix(),
        table_count=len(exports),
        tables=exports,
    )


def write_lens_identity_table_index(schema_path: Path, output: Path | None) -> None:
    payload = build_lens_identity_table_index(schema_path).to_json()
    if output is None:
        print(payload, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")


def lens_identity_source_table(value: JsonObject) -> LensIdentitySourceTable | None:
    owner = lens_identity_owner(value.get("owner"))
    source_module = json_string(value.get("source_module"))
    variable = json_string(value.get("variable"))
    entries_value = value.get("entries")
    if owner is None or source_module is None or variable is None:
        return None
    if not isinstance(entries_value, dict):
        return None

    entries: list[LensIdentityEntry] = []
    skipped_entry_count = 0
    for key, entry_value in sorted(entries_value.items(), key=lambda item: item[0]):
        name = lens_identity_entry_name(entry_value)
        if name is None:
            skipped_entry_count += 1
            continue
        entries.append(LensIdentityEntry(key=key, name=name))

    source_entry_count = json_int(value.get("entry_count")) or len(entries_value)
    table = LensIdentityTable(entries=tuple(entries))
    return LensIdentitySourceTable(
        owner=owner,
        source_module=source_module,
        source_file=json_string(value.get("source_file")),
        variable=variable,
        source_entry_count=source_entry_count,
        normalized_entry_count=len(entries),
        skipped_entry_count=skipped_entry_count,
        table=table,
    )


def lens_identity_source_table_from_package(value: JsonObject) -> LensIdentitySourceTable | None:
    owner = lens_identity_owner(value.get("owner"))
    source_module = json_string(value.get("source_module"))
    variable = json_string(value.get("variable"))
    entries_value = value.get("entries")
    if owner is None or source_module is None or variable is None:
        return None
    if not isinstance(entries_value, list):
        return None

    entries: list[LensIdentityEntry] = []
    skipped_entry_count = 0
    for entry_value in entries_value:
        entry = lens_identity_entry_from_package(entry_value)
        if entry is None:
            skipped_entry_count += 1
        else:
            entries.append(entry)

    normalized_entry_count = json_int(value.get("normalized_entry_count")) or len(entries)
    source_entry_count = json_int(value.get("source_entry_count")) or len(entries_value)
    skipped_source_entry_count = json_int(value.get("skipped_entry_count")) or skipped_entry_count
    return LensIdentitySourceTable(
        owner=owner,
        source_module=source_module,
        source_file=relative_source_file(json_string(value.get("source_file"))),
        variable=variable,
        source_entry_count=source_entry_count,
        normalized_entry_count=normalized_entry_count,
        skipped_entry_count=skipped_source_entry_count,
        table=LensIdentityTable(entries=tuple(entries)),
    )


def lens_identity_table_export(table: LensIdentitySourceTable) -> LensIdentityTableExport:
    return LensIdentityTableExport(
        owner=table.owner,
        source_module=table.source_module,
        source_file=table.source_file,
        variable=table.variable,
        source_entry_count=table.source_entry_count,
        normalized_entry_count=table.normalized_entry_count,
        skipped_entry_count=table.skipped_entry_count,
        entries=table.table.entries,
    )


def lens_identity_entry_from_package(value: JsonValue) -> LensIdentityEntry | None:
    if not isinstance(value, dict):
        return None
    key = json_string(value.get("key"))
    name = json_string(value.get("name"))
    if key is None or name is None:
        return None
    return LensIdentityEntry(
        key=key,
        name=name,
        user_defined=json_bool(value.get("user_defined")),
    )


def lens_identity_entry_name(value: JsonValue | None) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict) and value.get("__kind") == "scalar_ref":
        return lens_identity_entry_name(value.get("value"))
    return None


def lens_identity_owner(value: JsonValue | None) -> LensIdentityOwner | None:
    if value == "canon":
        return "canon"
    if value == "minolta":
        return "minolta"
    if value == "nikon":
        return "nikon"
    if value == "olympus_micro_four_thirds":
        return "olympus_micro_four_thirds"
    if value == "panasonic_leica":
        return "panasonic_leica"
    if value == "pentax":
        return "pentax"
    if value == "sony":
        return "sony"
    if value == "sigma":
        return "sigma"
    if value == "samsung":
        return "samsung"
    if value == "leica":
        return "leica"
    return None


def source_paths_for_package_table(table: LensIdentitySourceTable) -> tuple[str, ...]:
    if table.source_file is None:
        return ()
    return (table.source_file,)


def relative_source_file(source_file: str | None) -> str | None:
    if source_file is None:
        return None
    marker = "/lib/Image/ExifTool/"
    marker_index = source_file.find(marker)
    if marker_index >= 0:
        return f"lib/Image/ExifTool/{source_file[marker_index + len(marker) :]}"
    return source_file


def json_string(value: JsonValue | None) -> str | None:
    return value if isinstance(value, str) else None


def json_int(value: JsonValue | None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def json_bool(value: JsonValue | None) -> bool:
    return value if isinstance(value, bool) else False
