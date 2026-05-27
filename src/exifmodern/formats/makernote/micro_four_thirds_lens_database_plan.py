"""Source-backed Olympus/Panasonic lens identity database extraction plan."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from exifmodern.services.lens_identity import LensIdentityEntry, LensIdentityTable

type LensDatabaseOwner = Literal["olympus_micro_four_thirds", "panasonic_leica"]
type LensSourceVariable = Literal["olympusLensTypes", "leicaLensTypes"]
type LensKeyFormat = Literal[
    "olympus_make_model_submodel_hex",
    "panasonic_leica_lens_id_selector",
]
type RuntimeGateStatus = Literal["ready", "required", "blocked"]
type RuntimeGateCode = Literal[
    "source_backed_runtime_helpers_ready",
    "lens_identity_owner_literal_missing_olympus",
    "lens_identity_owner_literal_missing_panasonic_leica",
    "schema_export_missing_olympus_lens_types",
    "schema_export_panasonic_leica_owner_is_legacy_leica",
    "exif_owner_adapter_missing_olympus_panasonic",
    "xmp_make_adapter_missing_olympus_panasonic_aliases",
    "panasonic_raw_mft_requires_olympus_shared_key",
    "panasonic_leica_other_fallback_requires_service_support",
    "duplicate_names_must_not_be_collapsed",
]

OLYMPUS_PM_SOURCE_PATH = "lib/Image/ExifTool/Olympus.pm"
PANASONIC_PM_SOURCE_PATH = "lib/Image/ExifTool/Panasonic.pm"


@dataclass(frozen=True)
class LensEvidenceAnchor:
    source_file: str
    source_module: str
    variable: LensSourceVariable
    line: int
    comment: str | None = None


@dataclass(frozen=True)
class LensDatabaseRecord:
    owner: LensDatabaseOwner
    key: str
    name: str
    source: LensEvidenceAnchor

    def lens_identity_entry(self) -> LensIdentityEntry:
        return LensIdentityEntry(key=self.key, name=self.name)


@dataclass(frozen=True)
class LensMakeAlias:
    make: str
    owner: LensDatabaseOwner
    reason: str


@dataclass(frozen=True)
class DuplicateLensNameGroup:
    owner: LensDatabaseOwner
    name: str
    keys: tuple[str, ...]
    source_lines: tuple[int, ...]


@dataclass(frozen=True)
class SharedEcosystemKeyRule:
    name: str
    output_owner: LensDatabaseOwner
    source_module: str
    source_tags: tuple[str, ...]
    key_format: LensKeyFormat
    expression: str
    source_lines: tuple[int, ...]


@dataclass(frozen=True)
class RuntimeConsumptionGate:
    code: RuntimeGateCode
    status: RuntimeGateStatus
    consumer: str
    reason: str
    required_change: str


@dataclass(frozen=True)
class LensDatabasePort:
    owner: LensDatabaseOwner
    source_module: str
    source_file: str
    variable: LensSourceVariable
    key_format: LensKeyFormat
    records: tuple[LensDatabaseRecord, ...]
    dynamic_fallback: str | None = None

    def to_lens_identity_table(self) -> LensIdentityTable:
        return LensIdentityTable(
            entries=tuple(record.lens_identity_entry() for record in self.records)
        )

    def record_for_key(self, key: str) -> LensDatabaseRecord | None:
        for record in self.records:
            if record.key == key:
                return record
        return None

    def name_for_key(self, key: str) -> str | None:
        record = self.record_for_key(key)
        return None if record is None else record.name

    def runtime_lookup_key_candidates(self, key: str) -> tuple[str, ...]:
        if self.dynamic_fallback == "panasonic_leica_strip_selector" and " " in key:
            base_key = key.split(" ", 1)[0]
            if base_key != key:
                return (key, base_key)
        return (key,)

    def runtime_name_for_key(self, key: str) -> str | None:
        for candidate in self.runtime_lookup_key_candidates(key):
            name = self.name_for_key(candidate)
            if name is not None:
                return name
        return None


@dataclass(frozen=True)
class MicroFourThirdsLensIdentityTables:
    olympus_micro_four_thirds: LensIdentityTable
    panasonic_leica: LensIdentityTable


@dataclass(frozen=True)
class MicroFourThirdsLensDatabasePlan:
    schema_version: int
    databases: tuple[LensDatabasePort, ...]
    make_aliases: tuple[LensMakeAlias, ...]
    shared_key_rules: tuple[SharedEcosystemKeyRule, ...]
    duplicate_name_groups: tuple[DuplicateLensNameGroup, ...]
    runtime_consumption_gates: tuple[RuntimeConsumptionGate, ...]

    def database(self, owner: LensDatabaseOwner) -> LensDatabasePort:
        for database in self.databases:
            if database.owner == owner:
                return database
        raise KeyError(owner)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


_PERL_LENS_ENTRY_RE = re.compile(
    r"^\s*(?P<key>'[^']+'|\d+)\s*=>\s*'(?P<name>[^']+)'\s*,?(?:\s*#(?P<comment>.*))?$"
)
_HASH_START_RE = re.compile(r"^(?:my\s+)?%(?P<variable>\w+)\s*=\s*\(")


def build_micro_four_thirds_lens_database_plan(
    olympus_source: Path,
    panasonic_source: Path,
) -> MicroFourThirdsLensDatabasePlan:
    olympus_database = extract_olympus_lens_database(olympus_source)
    panasonic_database = extract_panasonic_leica_lens_database(panasonic_source)
    databases = (olympus_database, panasonic_database)
    return MicroFourThirdsLensDatabasePlan(
        schema_version=1,
        databases=databases,
        make_aliases=MICRO_FOUR_THIRDS_MAKE_ALIASES,
        shared_key_rules=shared_ecosystem_key_rules(olympus_source, panasonic_source),
        duplicate_name_groups=duplicate_name_groups(databases),
        runtime_consumption_gates=RUNTIME_CONSUMPTION_GATES,
    )


def extract_olympus_lens_database(source_path: Path) -> LensDatabasePort:
    return parse_olympus_lens_database_source_text(
        source_path.read_text(encoding="utf-8"),
        source_path.as_posix(),
    )


def parse_olympus_lens_database_source_text(
    source_text: str,
    source_path: str = OLYMPUS_PM_SOURCE_PATH,
) -> LensDatabasePort:
    return _extract_database_from_source_text(
        source_text=source_text,
        source_path=source_path,
        source_module="Image::ExifTool::Olympus",
        variable="olympusLensTypes",
        owner="olympus_micro_four_thirds",
        key_format="olympus_make_model_submodel_hex",
    )


def extract_panasonic_leica_lens_database(source_path: Path) -> LensDatabasePort:
    return parse_panasonic_leica_lens_database_source_text(
        source_path.read_text(encoding="utf-8"),
        source_path.as_posix(),
    )


def parse_panasonic_leica_lens_database_source_text(
    source_text: str,
    source_path: str = PANASONIC_PM_SOURCE_PATH,
) -> LensDatabasePort:
    database = _extract_database_from_source_text(
        source_text=source_text,
        source_path=source_path,
        source_module="Image::ExifTool::Panasonic",
        variable="leicaLensTypes",
        owner="panasonic_leica",
        key_format="panasonic_leica_lens_id_selector",
    )
    return LensDatabasePort(
        owner=database.owner,
        source_module=database.source_module,
        source_file=database.source_file,
        variable=database.variable,
        key_format=database.key_format,
        records=database.records,
        dynamic_fallback="panasonic_leica_strip_selector",
    )


def olympus_micro_four_thirds_lens_identity_table_from_source_text(
    source_text: str,
    source_path: str = OLYMPUS_PM_SOURCE_PATH,
) -> LensIdentityTable:
    return parse_olympus_lens_database_source_text(
        source_text,
        source_path,
    ).to_lens_identity_table()


def olympus_micro_four_thirds_lens_identity_table_from_source_path(
    source_path: str | Path,
) -> LensIdentityTable:
    path = Path(source_path)
    return olympus_micro_four_thirds_lens_identity_table_from_source_text(
        path.read_text(encoding="utf-8"),
        path.as_posix(),
    )


def panasonic_leica_lens_identity_table_from_source_text(
    source_text: str,
    source_path: str = PANASONIC_PM_SOURCE_PATH,
) -> LensIdentityTable:
    return parse_panasonic_leica_lens_database_source_text(
        source_text,
        source_path,
    ).to_lens_identity_table()


def panasonic_leica_lens_identity_table_from_source_path(
    source_path: str | Path,
) -> LensIdentityTable:
    path = Path(source_path)
    return panasonic_leica_lens_identity_table_from_source_text(
        path.read_text(encoding="utf-8"),
        path.as_posix(),
    )


def micro_four_thirds_lens_identity_tables_from_source_paths(
    olympus_source_path: str | Path,
    panasonic_source_path: str | Path,
) -> MicroFourThirdsLensIdentityTables:
    return MicroFourThirdsLensIdentityTables(
        olympus_micro_four_thirds=olympus_micro_four_thirds_lens_identity_table_from_source_path(
            olympus_source_path
        ),
        panasonic_leica=panasonic_leica_lens_identity_table_from_source_path(panasonic_source_path),
    )


def olympus_lens_type_key_from_makernote_values(values: tuple[int, int, int, int, int, int]) -> str:
    """Port Olympus.pm 0x201 LensType ValueConv key selection."""
    lens_make, _, lens_model, lens_submodel, _, _ = values
    return f"{lens_make:x} {lens_model:02x} {lens_submodel:02x}"


def panasonic_raw_micro_four_thirds_lens_type_key(
    lens_type_make: int,
    lens_type_model: int,
) -> str:
    """Port Panasonic.pm LensTypeMake/LensTypeModel composite key behavior."""
    lens_model = f"{lens_type_model:04x}"
    return f"{lens_type_make:x} {lens_model[2:4]} {lens_model[0:2]}"


def panasonic_leica_lens_type_value(raw_value: int) -> str:
    """Port Panasonic.pm Leica LensType ValueConv for int32u values."""
    return f"{raw_value >> 2} {raw_value & 0x3}"


def panasonic_leica_lens_type_value_data1(raw_value: int) -> str:
    """Port Panasonic.pm Data1 LensType ValueConv with the 16-bit lens id mask."""
    return f"{(raw_value >> 2) & 0xFFFF} {raw_value & 0x3}"


def _extract_database_from_source_text(
    *,
    source_text: str,
    source_path: str,
    source_module: str,
    variable: LensSourceVariable,
    owner: LensDatabaseOwner,
    key_format: LensKeyFormat,
) -> LensDatabasePort:
    lines = source_text.splitlines()
    hash_lines = _extract_hash_lines(lines, variable)
    records: list[LensDatabaseRecord] = []
    for line_number, line in hash_lines:
        entry = _perl_lens_entry(line)
        if entry is None:
            continue
        key, name, comment = entry
        records.append(
            LensDatabaseRecord(
                owner=owner,
                key=key,
                name=name,
                source=LensEvidenceAnchor(
                    source_file=source_path,
                    source_module=source_module,
                    variable=variable,
                    line=line_number,
                    comment=comment,
                ),
            )
        )
    return LensDatabasePort(
        owner=owner,
        source_module=source_module,
        source_file=source_path,
        variable=variable,
        key_format=key_format,
        records=tuple(records),
    )


def _extract_hash_lines(
    lines: list[str],
    variable: LensSourceVariable,
) -> tuple[tuple[int, str], ...]:
    in_hash = False
    hash_lines: list[tuple[int, str]] = []
    for line_index, line in enumerate(lines, start=1):
        if not in_hash:
            match = _HASH_START_RE.match(line)
            if match is not None and match.group("variable") == variable:
                in_hash = True
            continue
        if line == ");":
            return tuple(hash_lines)
        hash_lines.append((line_index, line))
    raise ValueError(f"Could not find Perl hash %{variable}")


def _perl_lens_entry(line: str) -> tuple[str, str, str | None] | None:
    if line.lstrip().startswith("#"):
        return None
    match = _PERL_LENS_ENTRY_RE.match(line)
    if match is None:
        return None
    raw_key = match.group("key")
    key = raw_key[1:-1] if raw_key.startswith("'") else raw_key
    comment = match.group("comment")
    return (key, match.group("name"), None if comment is None else comment.strip())


def duplicate_name_groups(
    databases: tuple[LensDatabasePort, ...],
) -> tuple[DuplicateLensNameGroup, ...]:
    groups: list[DuplicateLensNameGroup] = []
    for database in databases:
        by_name: dict[str, list[LensDatabaseRecord]] = {}
        for record in database.records:
            by_name.setdefault(record.name, []).append(record)
        for name, records in sorted(by_name.items()):
            if len(records) < 2:
                continue
            groups.append(
                DuplicateLensNameGroup(
                    owner=database.owner,
                    name=name,
                    keys=tuple(record.key for record in records),
                    source_lines=tuple(record.source.line for record in records),
                )
            )
    return tuple(groups)


def shared_ecosystem_key_rules(
    olympus_source: Path,
    panasonic_source: Path,
) -> tuple[SharedEcosystemKeyRule, ...]:
    return (
        SharedEcosystemKeyRule(
            name="olympus_makernote_lens_type_0x201",
            output_owner="olympus_micro_four_thirds",
            source_module="Image::ExifTool::Olympus",
            source_tags=("Olympus:LensType",),
            key_format="olympus_make_model_submodel_hex",
            expression="sprintf('%x %.2x %.2x', make, model, submodel)",
            source_lines=_line_numbers_containing(
                olympus_source,
                ("0x201 => { #6", "ValueConv => 'my @a=split"),
            ),
        ),
        SharedEcosystemKeyRule(
            name="panasonic_raw_lens_type_make_model_to_olympus_lens_type",
            output_owner="olympus_micro_four_thirds",
            source_module="Image::ExifTool::Panasonic",
            source_tags=("Panasonic:LensTypeMake", "Panasonic:LensTypeModel"),
            key_format="olympus_make_model_submodel_hex",
            expression="make_hex + ' ' + swapped_model_low_high_bytes",
            source_lines=_line_numbers_containing(
                panasonic_source,
                ("LensTypeMake", "LensTypeModel", "ValueConv => '$_=sprintf"),
            ),
        ),
        SharedEcosystemKeyRule(
            name="panasonic_leica_lens_type_int32_to_lens_id_selector",
            output_owner="panasonic_leica",
            source_module="Image::ExifTool::Panasonic",
            source_tags=("Panasonic:LensType", "Leica:LensType"),
            key_format="panasonic_leica_lens_id_selector",
            expression="(raw >> 2) + ' ' + (raw & 0x3)",
            source_lines=_line_numbers_containing(
                panasonic_source,
                ("ValueConv => '($val >> 2) . \" \" . ($val & 0x3)'",),
            ),
        ),
    )


def _line_numbers_containing(source_path: Path, needles: tuple[str, ...]) -> tuple[int, ...]:
    lines = source_path.read_text(encoding="utf-8").splitlines()
    found: list[int] = []
    for needle in needles:
        for line_index, line in enumerate(lines, start=1):
            if needle in line:
                found.append(line_index)
                break
    return tuple(found)


MICRO_FOUR_THIRDS_MAKE_ALIASES: tuple[LensMakeAlias, ...] = (
    LensMakeAlias(
        make="Olympus",
        owner="olympus_micro_four_thirds",
        reason="Olympus maker-note LensType uses %olympusLensTypes.",
    ),
    LensMakeAlias(
        make="OM System",
        owner="olympus_micro_four_thirds",
        reason="OM System lenses continue in the Olympus LensType table.",
    ),
    LensMakeAlias(
        make="OM Digital Solutions",
        owner="olympus_micro_four_thirds",
        reason="OM Digital Solutions is the successor branding for Olympus MFT lenses.",
    ),
    LensMakeAlias(
        make="Panasonic",
        owner="olympus_micro_four_thirds",
        reason="Panasonic RW2 LensTypeMake/LensTypeModel composes into Olympus LensType.",
    ),
    LensMakeAlias(
        make="Lumix",
        owner="olympus_micro_four_thirds",
        reason="Lumix Micro Four Thirds lens ids are entries in %olympusLensTypes.",
    ),
    LensMakeAlias(
        make="Leica",
        owner="panasonic_leica",
        reason="Panasonic.pm %leicaLensTypes stores Leica LensType code identities.",
    ),
)

RUNTIME_CONSUMPTION_GATES: tuple[RuntimeConsumptionGate, ...] = (
    RuntimeConsumptionGate(
        code="source_backed_runtime_helpers_ready",
        status="ready",
        consumer="exifmodern.formats.makernote.micro_four_thirds_lens_database_plan",
        reason=(
            "Package-local helpers can now build Olympus MFT and Panasonic Leica "
            "LensIdentityTable instances directly from ExifTool source text or paths."
        ),
        required_change="No schema export or public owner literal is required for this local path.",
    ),
    RuntimeConsumptionGate(
        code="lens_identity_owner_literal_missing_olympus",
        status="required",
        consumer="exifmodern.services.lens_identity_tables.LensIdentityOwner",
        reason=(
            "The public schema owner literal does not include an Olympus/Micro Four "
            "Thirds table owner, but source-backed helpers can already build the table locally."
        ),
        required_change="Add an Olympus owner only when wiring the generated schema loader.",
    ),
    RuntimeConsumptionGate(
        code="lens_identity_owner_literal_missing_panasonic_leica",
        status="required",
        consumer="exifmodern.services.lens_identity_tables.LensIdentityOwner",
        reason="The current service exposes Panasonic.pm leicaLensTypes as legacy owner 'leica'.",
        required_change="Either keep a documented 'leica' alias or add a Panasonic/Leica owner.",
    ),
    RuntimeConsumptionGate(
        code="schema_export_missing_olympus_lens_types",
        status="required",
        consumer="exifmodern.perl.export_schema.pl",
        reason=(
            "The generated schema export still omits %olympusLensTypes; local runtime "
            "consumption can use olympus_micro_four_thirds_lens_identity_table_from_source_path."
        ),
        required_change=(
            "Export Image::ExifTool::Olympus %olympusLensTypes for public schema packages."
        ),
    ),
    RuntimeConsumptionGate(
        code="schema_export_panasonic_leica_owner_is_legacy_leica",
        status="required",
        consumer="exifmodern.perl.export_schema.pl",
        reason="Panasonic.pm %leicaLensTypes is exported under owner 'leica', not Panasonic.",
        required_change="Preserve compatibility while documenting Panasonic.pm as the source.",
    ),
    RuntimeConsumptionGate(
        code="exif_owner_adapter_missing_olympus_panasonic",
        status="blocked",
        consumer="exifmodern.formats.exif.lens_tables",
        reason="EXIF adapter owner typing cannot request the new Olympus/MFT owner.",
        required_change="Extend owner routing after the source-backed table is exported.",
    ),
    RuntimeConsumptionGate(
        code="xmp_make_adapter_missing_olympus_panasonic_aliases",
        status="blocked",
        consumer="exifmodern.formats.xmp.lens_tables",
        reason="XMP make aliases do not route Olympus, OM System, Panasonic, or Lumix.",
        required_change="Add make aliases without collapsing Panasonic Leica M and MFT behavior.",
    ),
    RuntimeConsumptionGate(
        code="panasonic_raw_mft_requires_olympus_shared_key",
        status="required",
        consumer="exifmodern.services.lens_identity",
        reason="Panasonic RW2 MFT identity can use the package-local shared-key adapter.",
        required_change=(
            "Call panasonic_raw_micro_four_thirds_lens_type_key before invoking "
            "resolve_exif_lens_identity."
        ),
    ),
    RuntimeConsumptionGate(
        code="panasonic_leica_other_fallback_requires_service_support",
        status="required",
        consumer="exifmodern.services.lens_identity.LensIdentityTable",
        reason=(
            "ExifTool's %leicaLensTypes OTHER code falls back from 'id selector' to "
            "'id'; LensDatabasePort.runtime_name_for_key now provides the table-specific path."
        ),
        required_change=(
            "Use the Panasonic Leica port for selector fallback; the generic table remains "
            "exact-key only."
        ),
    ),
    RuntimeConsumptionGate(
        code="duplicate_names_must_not_be_collapsed",
        status="required",
        consumer="exifmodern.services.lens_identity_tables",
        reason="Source tables contain distinct keys with identical lens names.",
        required_change="Normalize by key, not by display name, and keep duplicate-name groups.",
    ),
)
