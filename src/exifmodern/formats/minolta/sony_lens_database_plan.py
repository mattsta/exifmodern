"""Source-backed Minolta/Sony lens database extraction planning.

ExifTool keeps Sony A-mount lens IDs in ``Minolta.pm`` and derives Sony's
``%sonyLensTypes`` table from that Minolta table at module load time.  This
module parses those source hashes and models the derivation without wiring the
result directly into runtime lens resolution.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import JsonObject
from exifmodern.services.lens_identity import LensIdentityEntry, LensIdentityTable

type LensDatabaseTableName = Literal[
    "minoltaLensTypes",
    "sonyLensTypes",
    "sonyLensTypes2",
    "minoltaTeleconverters",
]
type LensDatabaseEntryKind = Literal[
    "primary",
    "alias_variant",
    "generated_alias",
    "runtime_adapter_base",
    "teleconverter",
]
type LensRuntimeGateCode = Literal[
    "source_hashes_extracted",
    "sony_a_mount_alias_derivation_modelled",
    "metabones_and_mc11_adapter_remaps_modelled",
    "lens_identity_service_consumes_schema_tables",
    "exact_ff00_keeps_source_lens_entry_before_adapter_remap",
]

MINOLTA_SOURCE_PATH = "lib/Image/ExifTool/Minolta.pm"
SONY_SOURCE_PATH = "lib/Image/ExifTool/Sony.pm"

MINOLTA_LENS_TABLE_SOURCE_ID = "minolta.lens.table"
MINOLTA_ADAPTER_OTHER_SOURCE_ID = "minolta.lens.adapter_other"
MINOLTA_METABONES_SOURCE_ID = "minolta.lens.metabones_id"
MINOLTA_TELECONVERTER_SOURCE_ID = "minolta.lens.teleconverters"
SONY_E_MOUNT_LENS_TABLE_SOURCE_ID = "minolta.lens.sony_e_mount_table"
SONY_A_MOUNT_DERIVATION_SOURCE_ID = "minolta.lens.sony_a_mount_derivation"

PERL_HASH_ENTRY_RE = re.compile(
    r"^\s*(?P<key>'[^']+'|0x[0-9a-fA-F]+|\d+(?:\.\d+)?|[A-Za-z_]\w*)\s*=>\s*(?P<value>.+)"
)
PERL_STRING_RE = re.compile(r"'(?P<value>(?:[^'\\]|\\.)*)'")
PERL_SCALAR_STRING_REF_RE = re.compile(r"\\\s*'(?P<value>(?:[^'\\]|\\.)*)'")


@dataclass(frozen=True)
class PerlHashValue:
    key: str
    value_text: str
    line_number: int


@dataclass(frozen=True)
class LensDatabaseEntry:
    table: LensDatabaseTableName
    key: str
    name: str
    kind: LensDatabaseEntryKind
    source_key: str
    source_line: int
    source_file: str
    derived_from_key: str | None = None

    def lens_identity_entry(self) -> LensIdentityEntry:
        return LensIdentityEntry(key=self.key, name=self.name)

    def to_json(self) -> JsonObject:
        return {
            "derived_from_key": self.derived_from_key,
            "key": self.key,
            "kind": self.kind,
            "name": self.name,
            "source_file": self.source_file,
            "source_key": self.source_key,
            "table": self.table,
        }


@dataclass(frozen=True)
class LensAliasGroup:
    table: LensDatabaseTableName
    base_key: str
    entries: tuple[LensDatabaseEntry, ...]
    evidence_ids: tuple[str, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self.entries)

    def to_json(self) -> JsonObject:
        return {
            "base_key": self.base_key,
            "entries": [entry.to_json() for entry in self.entries],
            "names": list(self.names),
            "table": self.table,
        }


@dataclass(frozen=True)
class SonyAdapterRemap:
    high_byte: int
    canonical_offset: int
    adapter_name: str
    target_owner: str
    source_line: int
    source_file: str

    @property
    def is_alias(self) -> bool:
        return self.high_byte != self.canonical_offset

    def remapped_lens_type(self, lens_type: int) -> int:
        return lens_type - self.canonical_offset

    def to_json(self) -> JsonObject:
        return {
            "adapter_name": self.adapter_name,
            "canonical_offset": self.canonical_offset,
            "high_byte": self.high_byte,
            "is_alias": self.is_alias,
            "source_file": self.source_file,
            "target_owner": self.target_owner,
        }


@dataclass(frozen=True)
class SonySigmaAdapterRule:
    offset: int
    adapter_name: str
    target_owner: str
    evidence_ids: tuple[str, ...]

    def remapped_lens_type(self, lens_type: int) -> int:
        return lens_type - self.offset

    def to_json(self) -> JsonObject:
        return {
            "adapter_name": self.adapter_name,
            "offset": self.offset,
            "target_owner": self.target_owner,
        }


@dataclass(frozen=True)
class SonyLensRuntimeGate:
    code: LensRuntimeGateCode
    passed: bool
    blocks_runtime_consumption: bool
    evidence: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocks_runtime_consumption": self.blocks_runtime_consumption,
            "code": self.code,
            "evidence": self.evidence,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class LensDatabasePortTable:
    name: LensDatabaseTableName
    owner: str
    source_module: str
    source_file: str
    variable: str
    entries: tuple[LensDatabaseEntry, ...]
    skipped_entry_count: int
    evidence_ids: tuple[str, ...]

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    def entry_for_key(self, key: str | int) -> LensDatabaseEntry | None:
        normalized_key = normalize_lens_database_key(key)
        for entry in self.entries:
            if entry.key == normalized_key:
                return entry
        return None

    def name_for_key(self, key: str | int) -> str | None:
        entry = self.entry_for_key(key)
        return None if entry is None else entry.name

    def lens_identity_table(self) -> LensIdentityTable:
        return LensIdentityTable(
            entries=tuple(entry.lens_identity_entry() for entry in self.entries)
        )

    def alias_groups(self) -> tuple[LensAliasGroup, ...]:
        by_base: dict[str, list[LensDatabaseEntry]] = {}
        for entry in self.entries:
            by_base.setdefault(base_lens_database_key(entry.key), []).append(entry)
        groups: list[LensAliasGroup] = []
        for base_key, entries in sorted(
            by_base.items(), key=lambda item: lens_key_sort_key(item[0])
        ):
            if len(entries) < 2:
                continue
            groups.append(
                LensAliasGroup(
                    table=self.name,
                    base_key=base_key,
                    entries=tuple(entries),
                    evidence_ids=self.evidence_ids,
                )
            )
        return tuple(groups)

    def to_json(self) -> JsonObject:
        return {
            "entries": [entry.to_json() for entry in self.entries],
            "entry_count": self.entry_count,
            "name": self.name,
            "owner": self.owner,
            "skipped_entry_count": self.skipped_entry_count,
            "source_file": self.source_file,
            "source_module": self.source_module,
            "variable": self.variable,
        }


@dataclass(frozen=True)
class SonyMinoltaLensDatabasePlan:
    minolta_a_mount: LensDatabasePortTable
    sony_a_mount: LensDatabasePortTable
    sony_e_mount: LensDatabasePortTable
    minolta_teleconverters: LensDatabasePortTable
    adapter_remaps: tuple[SonyAdapterRemap, ...]
    sigma_mc11_sa_e_rule: SonySigmaAdapterRule
    runtime_gates: tuple[SonyLensRuntimeGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_feed_runtime_directly(self) -> bool:
        return not any(gate.blocks_runtime_consumption for gate in self.runtime_gates)

    @property
    def blocked_runtime_gate_codes(self) -> tuple[LensRuntimeGateCode, ...]:
        return tuple(gate.code for gate in self.runtime_gates if gate.blocks_runtime_consumption)

    def adapter_remap_for_lens_type(self, lens_type: int) -> SonyAdapterRemap | None:
        high_byte = lens_type & 0xFF00
        for remap in self.adapter_remaps:
            if remap.high_byte == high_byte:
                return remap
        return None

    def to_json(self) -> JsonObject:
        return {
            "adapter_remaps": [remap.to_json() for remap in self.adapter_remaps],
            "blocked_runtime_gate_codes": list(self.blocked_runtime_gate_codes),
            "can_feed_runtime_directly": self.can_feed_runtime_directly,
            "minolta_a_mount": self.minolta_a_mount.to_json(),
            "minolta_teleconverters": self.minolta_teleconverters.to_json(),
            "runtime_gates": [gate.to_json() for gate in self.runtime_gates],
            "sigma_mc11_sa_e_rule": self.sigma_mc11_sa_e_rule.to_json(),
            "sony_a_mount": self.sony_a_mount.to_json(),
            "sony_e_mount": self.sony_e_mount.to_json(),
        }


def build_sony_minolta_lens_database_plan(
    exiftool_root: Path | None = None,
) -> SonyMinoltaLensDatabasePlan:
    root = default_exiftool_root() if exiftool_root is None else exiftool_root
    minolta_path = root / MINOLTA_SOURCE_PATH
    sony_path = root / SONY_SOURCE_PATH
    minolta_text = minolta_path.read_text(encoding="utf-8")
    sony_text = sony_path.read_text(encoding="utf-8")

    minolta_values = parse_perl_hash_values(minolta_text, "minoltaLensTypes")
    sony_e_values = parse_perl_hash_values(sony_text, "sonyLensTypes2")
    teleconverter_values = parse_perl_hash_values(minolta_text, "minoltaTeleconverters")
    metabones_values = parse_perl_hash_values(minolta_text, "metabonesID")

    minolta_entries, minolta_skipped = lens_entries_from_hash_values(
        table="minoltaLensTypes",
        values=minolta_values,
        source_file=MINOLTA_SOURCE_PATH,
        kind_for_key=minolta_entry_kind,
    )
    sony_e_entries, sony_e_skipped = lens_entries_from_hash_values(
        table="sonyLensTypes2",
        values=sony_e_values,
        source_file=SONY_SOURCE_PATH,
        kind_for_key=sony_e_mount_entry_kind,
    )
    teleconverter_entries, teleconverter_skipped = lens_entries_from_hash_values(
        table="minoltaTeleconverters",
        values=teleconverter_values,
        source_file=MINOLTA_SOURCE_PATH,
        kind_for_key=lambda _key, _name: "teleconverter",
    )
    adapter_remaps = adapter_remaps_from_hash_values(metabones_values)
    sony_a_entries = derive_sony_a_mount_entries(minolta_entries)

    minolta_table = LensDatabasePortTable(
        name="minoltaLensTypes",
        owner="minolta",
        source_module="Image::ExifTool::Minolta",
        source_file=MINOLTA_SOURCE_PATH,
        variable="minoltaLensTypes",
        entries=minolta_entries,
        skipped_entry_count=minolta_skipped,
        evidence_ids=(MINOLTA_LENS_TABLE_SOURCE_ID, MINOLTA_ADAPTER_OTHER_SOURCE_ID),
    )
    sony_a_table = LensDatabasePortTable(
        name="sonyLensTypes",
        owner="sony",
        source_module="Image::ExifTool::Sony",
        source_file=SONY_SOURCE_PATH,
        variable="sonyLensTypes",
        entries=sony_a_entries,
        skipped_entry_count=minolta_skipped,
        evidence_ids=(MINOLTA_LENS_TABLE_SOURCE_ID, SONY_A_MOUNT_DERIVATION_SOURCE_ID),
    )
    sony_e_table = LensDatabasePortTable(
        name="sonyLensTypes2",
        owner="sony",
        source_module="Image::ExifTool::Sony",
        source_file=SONY_SOURCE_PATH,
        variable="sonyLensTypes2",
        entries=sony_e_entries,
        skipped_entry_count=sony_e_skipped,
        evidence_ids=(SONY_E_MOUNT_LENS_TABLE_SOURCE_ID,),
    )
    teleconverter_table = LensDatabasePortTable(
        name="minoltaTeleconverters",
        owner="minolta",
        source_module="Image::ExifTool::Minolta",
        source_file=MINOLTA_SOURCE_PATH,
        variable="minoltaTeleconverters",
        entries=teleconverter_entries,
        skipped_entry_count=teleconverter_skipped,
        evidence_ids=(MINOLTA_TELECONVERTER_SOURCE_ID,),
    )
    evidence_ids = (
        MINOLTA_METABONES_SOURCE_ID,
        MINOLTA_ADAPTER_OTHER_SOURCE_ID,
        MINOLTA_LENS_TABLE_SOURCE_ID,
        SONY_A_MOUNT_DERIVATION_SOURCE_ID,
        SONY_E_MOUNT_LENS_TABLE_SOURCE_ID,
        MINOLTA_TELECONVERTER_SOURCE_ID,
    )
    return SonyMinoltaLensDatabasePlan(
        minolta_a_mount=minolta_table,
        sony_a_mount=sony_a_table,
        sony_e_mount=sony_e_table,
        minolta_teleconverters=teleconverter_table,
        adapter_remaps=adapter_remaps,
        sigma_mc11_sa_e_rule=SonySigmaAdapterRule(
            offset=0x4900,
            adapter_name="MC-11 SA-E",
            target_owner="sigma",
            evidence_ids=(MINOLTA_ADAPTER_OTHER_SOURCE_ID,),
        ),
        runtime_gates=runtime_gates(
            minolta_table=minolta_table,
            sony_a_table=sony_a_table,
            sony_e_table=sony_e_table,
            adapter_remaps=adapter_remaps,
        ),
        evidence_ids=evidence_ids,
    )


def minolta_a_mount_lens_identity_table_from_source_text(source_text: str) -> LensIdentityTable:
    entries, _skipped = lens_entries_from_hash_values(
        table="minoltaLensTypes",
        values=parse_perl_hash_values(source_text, "minoltaLensTypes"),
        source_file=MINOLTA_SOURCE_PATH,
        kind_for_key=minolta_entry_kind,
    )
    return lens_identity_table_from_database_entries(entries)


def minolta_a_mount_lens_identity_table_from_source_path(
    source_path: Path | str,
) -> LensIdentityTable:
    return minolta_a_mount_lens_identity_table_from_source_text(
        Path(source_path).read_text(encoding="utf-8")
    )


def sony_a_mount_lens_identity_table_from_minolta_source_text(
    source_text: str,
) -> LensIdentityTable:
    minolta_entries, _skipped = lens_entries_from_hash_values(
        table="minoltaLensTypes",
        values=parse_perl_hash_values(source_text, "minoltaLensTypes"),
        source_file=MINOLTA_SOURCE_PATH,
        kind_for_key=minolta_entry_kind,
    )
    return lens_identity_table_from_database_entries(derive_sony_a_mount_entries(minolta_entries))


def sony_a_mount_lens_identity_table_from_minolta_source_path(
    source_path: Path | str,
) -> LensIdentityTable:
    return sony_a_mount_lens_identity_table_from_minolta_source_text(
        Path(source_path).read_text(encoding="utf-8")
    )


def sony_e_mount_lens_identity_table_from_source_text(source_text: str) -> LensIdentityTable:
    entries, _skipped = lens_entries_from_hash_values(
        table="sonyLensTypes2",
        values=parse_perl_hash_values(source_text, "sonyLensTypes2"),
        source_file=SONY_SOURCE_PATH,
        kind_for_key=sony_e_mount_entry_kind,
    )
    return lens_identity_table_from_database_entries(entries)


def sony_e_mount_lens_identity_table_from_source_path(
    source_path: Path | str,
) -> LensIdentityTable:
    return sony_e_mount_lens_identity_table_from_source_text(
        Path(source_path).read_text(encoding="utf-8")
    )


def minolta_teleconverter_identity_table_from_source_text(source_text: str) -> LensIdentityTable:
    entries, _skipped = lens_entries_from_hash_values(
        table="minoltaTeleconverters",
        values=parse_perl_hash_values(source_text, "minoltaTeleconverters"),
        source_file=MINOLTA_SOURCE_PATH,
        kind_for_key=lambda _key, _name: "teleconverter",
    )
    return lens_identity_table_from_database_entries(entries)


def minolta_teleconverter_identity_table_from_source_path(
    source_path: Path | str,
) -> LensIdentityTable:
    return minolta_teleconverter_identity_table_from_source_text(
        Path(source_path).read_text(encoding="utf-8")
    )


def lens_identity_table_from_database_entries(
    entries: tuple[LensDatabaseEntry, ...],
) -> LensIdentityTable:
    return LensIdentityTable(entries=tuple(entry.lens_identity_entry() for entry in entries))


def default_exiftool_root() -> Path:
    return Path(__file__).resolve().parents[5] / "exiftool"


def parse_perl_hash_values(source_text: str, variable: str) -> tuple[PerlHashValue, ...]:
    lines = source_text.splitlines()
    start_index = None
    for index, line in enumerate(lines):
        if re.match(rf"^\s*%{re.escape(variable)}\s*=\s*\(", line):
            start_index = index
            break
    if start_index is None:
        return ()

    values: list[PerlHashValue] = []
    for index in range(start_index + 1, len(lines)):
        line = lines[index]
        if re.match(r"^\s*\);", line):
            break
        match = PERL_HASH_ENTRY_RE.match(line)
        if match is None:
            continue
        values.append(
            PerlHashValue(
                key=match.group("key"),
                value_text=match.group("value").strip(),
                line_number=index + 1,
            )
        )
    return tuple(values)


def lens_entries_from_hash_values(
    table: LensDatabaseTableName,
    values: tuple[PerlHashValue, ...],
    source_file: str,
    kind_for_key: Callable[[str, str], LensDatabaseEntryKind],
) -> tuple[tuple[LensDatabaseEntry, ...], int]:
    entries: list[LensDatabaseEntry] = []
    skipped = 0
    for value in values:
        name = perl_single_quoted_string(value.value_text)
        if name is None:
            skipped += 1
            continue
        key = normalize_lens_database_key(value.key)
        kind = call_kind_for_key(kind_for_key, key, name)
        entries.append(
            LensDatabaseEntry(
                table=table,
                key=key,
                name=name,
                kind=kind,
                source_key=value.key,
                source_line=value.line_number,
                source_file=source_file,
            )
        )
    return tuple(sorted(entries, key=lambda entry: lens_key_sort_key(entry.key))), skipped


def call_kind_for_key(
    kind_for_key: Callable[[str, str], LensDatabaseEntryKind],
    key: str,
    name: str,
) -> LensDatabaseEntryKind:
    return kind_for_key(key, name)


def derive_sony_a_mount_entries(
    minolta_entries: tuple[LensDatabaseEntry, ...],
) -> tuple[LensDatabaseEntry, ...]:
    entries_by_key: dict[str, LensDatabaseEntry] = {
        entry.key: LensDatabaseEntry(
            table="sonyLensTypes",
            key=entry.key,
            name=entry.name,
            kind=entry.kind,
            source_key=entry.source_key,
            source_line=entry.source_line,
            source_file=entry.source_file,
            derived_from_key=entry.key,
        )
        for entry in minolta_entries
    }
    for entry in sorted(minolta_entries, key=lambda value: sony_sort_key(value.key)):
        numeric_key = lens_key_numeric_value(entry.key)
        if numeric_key is None or numeric_key < 10000:
            continue
        base_key = str(int(numeric_key / 10))
        alias_name = entry.name
        if base_key in entries_by_key:
            existing = entries_by_key[base_key]
            if " or " in alias_name:
                entries_by_key[base_key] = generated_sony_alias_entry(
                    source=entry,
                    key=base_key,
                    name=alias_name,
                )
                alias_name = existing.name
            alias_key = next_available_variant_key(base_key, entries_by_key)
        else:
            alias_key = base_key
        entries_by_key[alias_key] = generated_sony_alias_entry(
            source=entry,
            key=alias_key,
            name=alias_name,
        )
    return tuple(sorted(entries_by_key.values(), key=lambda entry: lens_key_sort_key(entry.key)))


def generated_sony_alias_entry(
    source: LensDatabaseEntry,
    key: str,
    name: str,
) -> LensDatabaseEntry:
    return LensDatabaseEntry(
        table="sonyLensTypes",
        key=key,
        name=name,
        kind="generated_alias",
        source_key=source.source_key,
        source_line=source.source_line,
        source_file=source.source_file,
        derived_from_key=source.key,
    )


def next_available_variant_key(base_key: str, entries_by_key: dict[str, LensDatabaseEntry]) -> str:
    index = 1
    while f"{base_key}.{index}" in entries_by_key:
        index += 1
    return f"{base_key}.{index}"


def adapter_remaps_from_hash_values(
    values: tuple[PerlHashValue, ...],
) -> tuple[SonyAdapterRemap, ...]:
    canonical_names: dict[int, str] = {}
    numeric_links: dict[int, tuple[int, int]] = {}
    for value in values:
        high_byte = parse_int_key(value.key)
        if high_byte is None:
            continue
        scalar_ref = perl_scalar_string_ref(value.value_text)
        if scalar_ref is not None:
            canonical_names[high_byte] = scalar_ref
            continue
        target = parse_int_key(perl_value_without_comment(value.value_text))
        if target is not None:
            numeric_links[high_byte] = (target, value.line_number)

    remaps: list[SonyAdapterRemap] = []
    for value in values:
        high_byte = parse_int_key(value.key)
        if high_byte is None:
            continue
        scalar_ref = perl_scalar_string_ref(value.value_text)
        if scalar_ref is not None:
            canonical_offset = high_byte
            adapter_name = scalar_ref
        else:
            link = numeric_links.get(high_byte)
            if link is None:
                continue
            canonical_offset = link[0]
            adapter_name = canonical_names.get(canonical_offset, "Canon EF Adapter")
        remaps.append(
            SonyAdapterRemap(
                high_byte=high_byte,
                canonical_offset=canonical_offset,
                adapter_name=adapter_name,
                target_owner="canon",
                source_line=value.line_number,
                source_file=MINOLTA_SOURCE_PATH,
            )
        )
    return tuple(sorted(remaps, key=lambda remap: remap.high_byte))


def runtime_gates(
    minolta_table: LensDatabasePortTable,
    sony_a_table: LensDatabasePortTable,
    sony_e_table: LensDatabasePortTable,
    adapter_remaps: tuple[SonyAdapterRemap, ...],
) -> tuple[SonyLensRuntimeGate, ...]:
    expected_offsets = {0x7700, 0xBC00, 0xEF00}
    canonical_offsets = {remap.canonical_offset for remap in adapter_remaps}
    return (
        SonyLensRuntimeGate(
            code="source_hashes_extracted",
            passed=(
                minolta_table.entry_count > 0
                and sony_a_table.entry_count > minolta_table.entry_count
                and sony_e_table.entry_count > 0
            ),
            blocks_runtime_consumption=False,
            evidence="Minolta, derived Sony A-mount, and Sony E-mount tables were parsed.",
            evidence_ids=(
                MINOLTA_LENS_TABLE_SOURCE_ID,
                SONY_A_MOUNT_DERIVATION_SOURCE_ID,
                SONY_E_MOUNT_LENS_TABLE_SOURCE_ID,
            ),
        ),
        SonyLensRuntimeGate(
            code="sony_a_mount_alias_derivation_modelled",
            passed=sony_a_table.name_for_key("2551") is not None,
            blocks_runtime_consumption=False,
            evidence="Sony 4-digit aliases are generated from 5-digit Minolta LensType IDs.",
            evidence_ids=(SONY_A_MOUNT_DERIVATION_SOURCE_ID,),
        ),
        SonyLensRuntimeGate(
            code="metabones_and_mc11_adapter_remaps_modelled",
            passed=expected_offsets <= canonical_offsets,
            blocks_runtime_consumption=False,
            evidence="Canon adapter offsets and the Sigma MC-11 SA-E offset are represented.",
            evidence_ids=(MINOLTA_METABONES_SOURCE_ID, MINOLTA_ADAPTER_OTHER_SOURCE_ID),
        ),
        SonyLensRuntimeGate(
            code="lens_identity_service_consumes_schema_tables",
            passed=False,
            blocks_runtime_consumption=True,
            evidence=(
                "Existing service selection consumes generated lens identity schema tables; "
                "this source parser is a planning boundary until export wiring lands."
            ),
            evidence_ids=(SONY_A_MOUNT_DERIVATION_SOURCE_ID,),
        ),
        SonyLensRuntimeGate(
            code="exact_ff00_keeps_source_lens_entry_before_adapter_remap",
            passed=True,
            blocks_runtime_consumption=False,
            evidence=(
                "Minolta.pm has both a metabonesID 0xff00 alias and a concrete LensType "
                "65280 entry, so runtime selection must keep exact 0xff00 as Sony."
            ),
            evidence_ids=(MINOLTA_METABONES_SOURCE_ID, MINOLTA_LENS_TABLE_SOURCE_ID),
        ),
    )


def normalize_lens_database_key(value: str | int) -> str:
    if isinstance(value, int):
        return str(value)
    key = value.strip().rstrip(",")
    if len(key) >= 2 and key[0] == "'" and key[-1] == "'":
        return key[1:-1]
    parsed = parse_int_key(key)
    if parsed is not None:
        return str(parsed)
    return key


def base_lens_database_key(key: str) -> str:
    return key.split(".", 1)[0]


def minolta_entry_kind(key: str, _name: str) -> LensDatabaseEntryKind:
    if key in {"30464", "48128", "61184", "65280"}:
        return "runtime_adapter_base"
    if "." in key:
        return "alias_variant"
    return "primary"


def sony_e_mount_entry_kind(key: str, _name: str) -> LensDatabaseEntryKind:
    if "." in key:
        return "alias_variant"
    return "primary"


def perl_single_quoted_string(value_text: str) -> str | None:
    match = PERL_STRING_RE.search(value_text)
    if match is None:
        return None
    return match.group("value").replace("\\'", "'")


def perl_scalar_string_ref(value_text: str) -> str | None:
    match = PERL_SCALAR_STRING_REF_RE.search(value_text)
    if match is None:
        return None
    return match.group("value").replace("\\'", "'")


def parse_int_key(value: str) -> int | None:
    stripped = value.strip().rstrip(",")
    if re.fullmatch(r"0x[0-9a-fA-F]+", stripped):
        return int(stripped, 16)
    if re.fullmatch(r"\d+", stripped):
        return int(stripped, 10)
    return None


def lens_key_numeric_value(key: str) -> float | None:
    try:
        return float(key)
    except ValueError:
        return None


def sony_sort_key(key: str) -> tuple[float, int]:
    if "." not in key:
        numeric = lens_key_numeric_value(key)
        if numeric is None:
            return (0.0, 0)
        return (numeric, -1)
    _base, suffix = key.split(".", 1)
    numeric = lens_key_numeric_value(key)
    return (0.0 if numeric is None else numeric, int(suffix))


def lens_key_sort_key(key: str) -> tuple[int, int, str]:
    if "." not in key:
        numeric = lens_key_numeric_value(key)
        if numeric is None:
            return (0, -1, key)
        return (int(numeric), -1, key)
    base, suffix = key.split(".", 1)
    return (int(base), int(suffix), key)


def perl_value_without_comment(value_text: str) -> str:
    return value_text.split("#", 1)[0].strip().rstrip(",")
