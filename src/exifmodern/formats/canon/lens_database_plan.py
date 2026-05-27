"""Canon lens identity database extraction plan.

This module intentionally models a source-backed extraction contract instead of
parsing Canon.pm. The source table is a large hand-maintained Perl hash with
quoted decimal keys, comments, and alias entries; the modern port needs stable
typed metadata plus a small sourced sample that exercises the existing lens
identity service behavior.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.services.lens_identity import LensIdentityEntry, LensIdentityTable

type CanonLensKeyKind = Literal[
    "integer_lens_type",
    "decimal_variant",
    "rf_master_alias",
    "sentinel",
]
type CanonLensKeyValue = str | int | float
type CanonLensSourceRole = Literal["primary_table", "companion_table", "runtime_resolver"]
type CanonLensRuntimeGateStatus = Literal["ready", "planned", "blocked"]
type CanonLensEvidenceId = str

CANON_PM_SOURCE_PATH = "lib/Image/ExifTool/Canon.pm"

CANON_LENS_TYPES_SOURCE = "canon.lens.types"
CANON_LENS_TYPE_TAG_SOURCE = "canon.lens.type_tag"
CANON_RF_LENS_TYPE_SOURCE = "canon.lens.rf_lens_type"
CANON_LENS_WITH_TC_SOURCE = "canon.lens.with_tc"
CANON_PRINT_LENS_ID_SOURCE = "canon.lens.print_lens_id"

CANON_LENS_SOURCE_SPANS: dict[CanonLensEvidenceId, tuple[int, int]] = {
    CANON_LENS_TYPES_SOURCE: (97, 653),
    CANON_LENS_TYPE_TAG_SOURCE: (2499, 2508),
    CANON_RF_LENS_TYPE_SOURCE: (7059, 7139),
    CANON_LENS_WITH_TC_SOURCE: (10118, 10132),
    CANON_PRINT_LENS_ID_SOURCE: (10181, 10302),
}

_CANON_LENS_KEY_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_CANON_HASH_STRING_ENTRY_RE = re.compile(
    r"^\s*(?P<key>'-?\d+(?:\.\d+)?'|-?\d+(?:\.\d+)?)\s*=>\s*'(?P<name>(?:\\'|[^'])*)'\s*,"
)
_CANON_RF_LENS_TYPE_ENTRY_RE = re.compile(r"^\s*(?P<key>\d+)\s*=>\s*'(?P<name>(?:\\'|[^'])*)'\s*,")


@dataclass(frozen=True)
class CanonLensSourceTablePlan:
    role: CanonLensSourceRole
    owner: str
    source_module: str
    source_file: str
    variable: str
    key_format: str
    value_format: str
    source: CanonLensEvidenceId
    extraction_notes: tuple[str, ...]


@dataclass(frozen=True)
class CanonLensEntryPlan:
    key: str
    name: str
    key_kind: CanonLensKeyKind
    source_line: int
    source: CanonLensEvidenceId
    aliases_base_key: str | None = None


@dataclass(frozen=True)
class CanonRfLensTypeEntry:
    key: int
    name: str
    source_line: int
    source: CanonLensEvidenceId
    is_sentinel: bool = False


@dataclass(frozen=True)
class CanonLensConflictGroupPlan:
    base_key: str
    primary_key: str
    variant_keys: tuple[str, ...]
    primary_raw_name: str
    primary_candidate_name: str
    policy: str
    source: CanonLensEvidenceId


@dataclass(frozen=True)
class CanonLensDuplicatePolicy:
    alias_key_pattern: str
    primary_candidate_rule: str
    duplicate_name_rule: str
    conflict_resolution_order: tuple[str, ...]
    evidence_ids: tuple[CanonLensEvidenceId, ...]


@dataclass(frozen=True)
class CanonLensRuntimeGate:
    gate_id: str
    status: CanonLensRuntimeGateStatus
    service: str
    requirement: str
    evidence_ids: tuple[CanonLensEvidenceId, ...]


@dataclass(frozen=True)
class CanonLensDatabaseExtractionPlan:
    source_tables: tuple[CanonLensSourceTablePlan, ...]
    sample_entries: tuple[CanonLensEntryPlan, ...]
    conflict_groups: tuple[CanonLensConflictGroupPlan, ...]
    duplicate_policy: CanonLensDuplicatePolicy
    runtime_gates: tuple[CanonLensRuntimeGate, ...]

    def source_table(self, variable: str) -> CanonLensSourceTablePlan:
        for table in self.source_tables:
            if table.variable == variable:
                return table
        raise KeyError(variable)

    def sample_entry(self, key: str) -> CanonLensEntryPlan | None:
        normalized_key = normalize_canon_lens_key(key)
        for entry in self.sample_entries:
            if entry.key == normalized_key:
                return entry
        return None

    def conflict_group(self, base_key: str) -> CanonLensConflictGroupPlan | None:
        normalized_key = normalize_canon_lens_key(base_key)
        for group in self.conflict_groups:
            if group.base_key == normalized_key:
                return group
        return None

    def service_table(self) -> LensIdentityTable:
        return canon_lens_identity_table_from_entries(self.sample_entries)


def canon_lens_database_extraction_plan() -> CanonLensDatabaseExtractionPlan:
    """Return the typed Canon.pm lens table extraction plan."""

    return CanonLensDatabaseExtractionPlan(
        source_tables=canon_lens_source_tables(),
        sample_entries=canon_lens_sample_entries(),
        conflict_groups=canon_lens_conflict_groups(),
        duplicate_policy=canon_lens_duplicate_policy(),
        runtime_gates=canon_lens_runtime_gates(),
    )


def canon_lens_source_tables() -> tuple[CanonLensSourceTablePlan, ...]:
    return (
        CanonLensSourceTablePlan(
            role="primary_table",
            owner="canon",
            source_module="Image::ExifTool::Canon",
            source_file=CANON_PM_SOURCE_PATH,
            variable="canonLensTypes",
            key_format=(
                "Perl hash keys normalized as strings; integer LensType IDs, quoted "
                "decimal variant IDs like '33.10', and sentinel keys -1/65535."
            ),
            value_format="literal Perl string lens display names",
            source=CANON_LENS_TYPES_SOURCE,
            extraction_notes=(
                "Extract only literal key => 'name' entries inside %canonLensTypes.",
                "Preserve quoted decimal keys exactly because Perl numeric keys "
                "would collapse trailing zeros.",
                "Keep .$i variant entries as aliases of the integer base key for "
                "PrintLensID disambiguation.",
                "Do not collapse names shared by different integer LensType IDs.",
            ),
        ),
        CanonLensSourceTablePlan(
            role="companion_table",
            owner="canon",
            source_module="Image::ExifTool::Canon",
            source_file=CANON_PM_SOURCE_PATH,
            variable="RFLensType.PrintConv",
            key_format="int16u RF lens type IDs stored in Canon CameraInfo",
            value_format="literal Perl string lens display names",
            source=CANON_RF_LENS_TYPE_SOURCE,
            extraction_notes=(
                "Model as a companion source table, not as a replacement for %canonLensTypes.",
                "Use it to validate and extend the 61182.* RF aliases in %canonLensTypes.",
                "Keep a source-backed gate before using RFLensType as a runtime override.",
            ),
        ),
    )


def canon_lens_sample_entries() -> tuple[CanonLensEntryPlan, ...]:
    return (
        canon_lens_entry("-1", "n/a", "sentinel", 98),
        canon_lens_entry("1", "Canon EF 50mm f/1.8", "integer_lens_type", 99),
        canon_lens_entry(
            "2",
            "Canon EF 28mm f/2.8 or Sigma Lens",
            "integer_lens_type",
            100,
        ),
        canon_lens_entry(
            "2.1",
            "Sigma 24mm f/2.8 Super Wide II",
            "decimal_variant",
            101,
            aliases_base_key="2",
        ),
        canon_lens_entry(
            "33.10",
            "Carl Zeiss Distagon T* 35mm f/1.4 ZE",
            "decimal_variant",
            173,
            aliases_base_key="33",
        ),
        canon_lens_entry(
            "137",
            "Canon EF 85mm f/1.2L USM or Sigma or Tamron Lens",
            "integer_lens_type",
            246,
        ),
        canon_lens_entry(
            "137.15",
            "Sigma 18-35mm f/1.8 DC HSM",
            "decimal_variant",
            261,
            aliases_base_key="137",
        ),
        canon_lens_entry(
            "61182",
            "Canon RF 50mm F1.2L USM or other Canon RF Lens",
            "rf_master_alias",
            583,
        ),
        canon_lens_entry(
            "61182.1",
            "Canon RF 24-105mm F4L IS USM",
            "rf_master_alias",
            584,
            aliases_base_key="61182",
        ),
        canon_lens_entry("65535", "n/a", "sentinel", 652),
    )


def canon_lens_entry(
    key: str,
    name: str,
    key_kind: CanonLensKeyKind,
    source_line: int,
    aliases_base_key: str | None = None,
) -> CanonLensEntryPlan:
    return CanonLensEntryPlan(
        key=normalize_canon_lens_key(key),
        name=name,
        key_kind=key_kind,
        source_line=source_line,
        source=CANON_LENS_TYPES_SOURCE,
        aliases_base_key=aliases_base_key,
    )


def canon_lens_conflict_groups() -> tuple[CanonLensConflictGroupPlan, ...]:
    return (
        CanonLensConflictGroupPlan(
            base_key="2",
            primary_key="2",
            variant_keys=("2.1",),
            primary_raw_name="Canon EF 28mm f/2.8 or Sigma Lens",
            primary_candidate_name="Canon EF 28mm f/2.8",
            policy=(
                "The base key remains the printed fallback, but the resolver should "
                "use the name before ' or ' as the primary candidate when .$i aliases exist."
            ),
            source=CANON_LENS_TYPES_SOURCE,
        ),
        CanonLensConflictGroupPlan(
            base_key="137",
            primary_key="137",
            variant_keys=("137.1", "137.2", "137.15", "137.17"),
            primary_raw_name="Canon EF 85mm f/1.2L USM or Sigma or Tamron Lens",
            primary_candidate_name="Canon EF 85mm f/1.2L USM",
            policy=(
                "Keep all numbered aliases under the base LensType and let "
                "PrintLensID-compatible optics and LensModel filtering choose among them."
            ),
            source=CANON_LENS_TYPES_SOURCE,
        ),
        CanonLensConflictGroupPlan(
            base_key="61182",
            primary_key="61182",
            variant_keys=("61182.1", "61182.2", "61182.68"),
            primary_raw_name="Canon RF 50mm F1.2L USM or other Canon RF Lens",
            primary_candidate_name="Canon RF 50mm F1.2L USM",
            policy=(
                "Treat 61182 as the RF master LensType family; validate new members "
                "against the RFLensType companion table before runtime use."
            ),
            source=CANON_LENS_TYPES_SOURCE,
        ),
    )


def canon_lens_duplicate_policy() -> CanonLensDuplicatePolicy:
    return CanonLensDuplicatePolicy(
        alias_key_pattern=r"^(?P<base>-?\d+)\.(?P<variant>\d+)$",
        primary_candidate_rule=(
            "For a base key with variants, split the base display name at the first "
            "' or ' before using it as a candidate."
        ),
        duplicate_name_rule=(
            "Do not deduplicate equal names across different base keys; Canon.pm "
            "intentionally repeats some lens names for distinct LensType values."
        ),
        conflict_resolution_order=(
            "user_defined_lens",
            "teleconverter_and_focal_range",
            "max_aperture",
            "sigma_art_contemporary_sports_marker",
            "lens_model_match",
            "join_remaining_candidates",
        ),
        evidence_ids=(
            CANON_LENS_TYPES_SOURCE,
            CANON_LENS_WITH_TC_SOURCE,
            CANON_PRINT_LENS_ID_SOURCE,
        ),
    )


def canon_lens_runtime_gates() -> tuple[CanonLensRuntimeGate, ...]:
    return (
        CanonLensRuntimeGate(
            gate_id="canon_lens_type_table_to_lens_identity_service",
            status="ready",
            service="exifmodern.services.lens_identity.resolve_exif_lens_identity",
            requirement=(
                "Provide LensIdentityTable entries with Canon.pm keys normalized as "
                "strings so LensIdentityTable.candidates_for_key can discover .$i aliases."
            ),
            evidence_ids=(CANON_LENS_TYPE_TAG_SOURCE, CANON_PRINT_LENS_ID_SOURCE),
        ),
        CanonLensRuntimeGate(
            gate_id="canon_rf_lens_type_runtime_override",
            status="planned",
            service="Canon RFLensType companion lookup",
            requirement=(
                "Use RFLensType only after a request path carries that tag alongside "
                "LensType 61182; until then, the 61182.* entries remain table aliases."
            ),
            evidence_ids=(CANON_RF_LENS_TYPE_SOURCE, CANON_LENS_TYPES_SOURCE),
        ),
        CanonLensRuntimeGate(
            gate_id="full_canon_pm_parser",
            status="blocked",
            service="generated lens identity table build",
            requirement=(
                "Avoid a broad Perl parser. Use a constrained extractor for the "
                "known literal hash spans and fail closed if a non-literal entry appears."
            ),
            evidence_ids=(CANON_LENS_TYPES_SOURCE, CANON_RF_LENS_TYPE_SOURCE),
        ),
    )


def canon_lens_identity_sample_table(
    entries: tuple[CanonLensEntryPlan, ...] | None = None,
) -> LensIdentityTable:
    source_entries = canon_lens_sample_entries() if entries is None else entries
    return canon_lens_identity_table_from_entries(source_entries)


def canon_lens_identity_table_from_entries(
    entries: tuple[CanonLensEntryPlan, ...],
) -> LensIdentityTable:
    return LensIdentityTable(
        entries=tuple(
            LensIdentityEntry(key=entry.key, name=entry.name)
            for entry in entries
            if entry.key_kind != "sentinel"
        )
    )


def parse_canon_lens_types_source_text(source_text: str) -> tuple[CanonLensEntryPlan, ...]:
    """Extract literal ``%canonLensTypes`` rows from Canon.pm source text."""

    entries: list[CanonLensEntryPlan] = []
    for line_number, line in source_lines_for_reference(source_text, CANON_LENS_TYPES_SOURCE):
        match = _CANON_HASH_STRING_ENTRY_RE.match(line)
        if match is None:
            reject_unparsed_hash_entry(line, CANON_LENS_TYPES_SOURCE, line_number)
            continue
        key = normalize_canon_lens_key(match.group("key"))
        entries.append(
            CanonLensEntryPlan(
                key=key,
                name=decode_perl_single_quoted_string(match.group("name")),
                key_kind=canon_lens_key_kind(key),
                source_line=line_number,
                source=CANON_LENS_TYPES_SOURCE,
                aliases_base_key=canon_lens_alias_base_key(key),
            )
        )
    return tuple(entries)


def parse_canon_rf_lens_type_print_conv_source_text(
    source_text: str,
) -> tuple[CanonRfLensTypeEntry, ...]:
    """Extract literal ``RFLensType`` PrintConv rows from Canon.pm source text."""

    entries: list[CanonRfLensTypeEntry] = []
    for line_number, line in source_lines_for_reference(source_text, CANON_RF_LENS_TYPE_SOURCE):
        match = _CANON_RF_LENS_TYPE_ENTRY_RE.match(line)
        if match is None:
            reject_unparsed_hash_entry(line, CANON_RF_LENS_TYPE_SOURCE, line_number)
            continue
        key = int(match.group("key"))
        entries.append(
            CanonRfLensTypeEntry(
                key=key,
                name=decode_perl_single_quoted_string(match.group("name")),
                source_line=line_number,
                source=CANON_RF_LENS_TYPE_SOURCE,
                is_sentinel=key == 0,
            )
        )
    return tuple(entries)


def canon_rf_lens_type_identity_table_from_entries(
    entries: tuple[CanonRfLensTypeEntry, ...],
) -> LensIdentityTable:
    return LensIdentityTable(
        entries=tuple(
            LensIdentityEntry(key=str(entry.key), name=entry.name)
            for entry in entries
            if not entry.is_sentinel
        )
    )


def canon_lens_identity_table_from_source_text(source_text: str) -> LensIdentityTable:
    return canon_lens_identity_table_from_entries(parse_canon_lens_types_source_text(source_text))


def canon_lens_identity_table_from_source_path(source_path: Path | str) -> LensIdentityTable:
    return canon_lens_identity_table_from_source_text(Path(source_path).read_text(encoding="utf-8"))


def canon_rf_lens_type_identity_table_from_source_text(source_text: str) -> LensIdentityTable:
    return canon_rf_lens_type_identity_table_from_entries(
        parse_canon_rf_lens_type_print_conv_source_text(source_text)
    )


def canon_rf_lens_type_identity_table_from_source_path(
    source_path: Path | str,
) -> LensIdentityTable:
    return canon_rf_lens_type_identity_table_from_source_text(
        Path(source_path).read_text(encoding="utf-8")
    )


def source_lines_for_reference(
    source_text: str,
    source: CanonLensEvidenceId,
) -> tuple[tuple[int, str], ...]:
    lines = source_text.splitlines()
    line_start, line_end = CANON_LENS_SOURCE_SPANS[source]
    start = line_start - 1
    end = line_end
    return tuple((index + 1, line) for index, line in enumerate(lines[start:end], start=start))


def reject_unparsed_hash_entry(line: str, source: CanonLensEvidenceId, line_number: int) -> None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=>" not in stripped:
        return
    if re.match(r"^(?:'-?\d|-?(?!0x)\d)", stripped) is None:
        return
    raise ValueError(
        f"Unsupported non-literal Canon lens table entry in {source} at line {line_number}: "
        f"{stripped!r}"
    )


def decode_perl_single_quoted_string(value: str) -> str:
    return value.replace("\\'", "'").replace("\\\\", "\\")


def canon_lens_alias_base_key(key: CanonLensKeyValue) -> str | None:
    normalized_key = normalize_canon_lens_key(key)
    if "." not in normalized_key:
        return None
    return normalized_key.split(".", 1)[0]


def normalize_canon_lens_key(value: CanonLensKeyValue) -> str:
    """Normalize a Canon.pm lens hash key for LensIdentityTable lookup."""

    if isinstance(value, bool):
        raise TypeError("Canon lens keys do not accept boolean values.")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Canon lens keys must be finite.")
        return str(int(value)) if value.is_integer() else format(value, "g")
    if isinstance(value, str):
        key = value.strip()
        if len(key) >= 2 and key[0] == key[-1] and key[0] in {"'", '"'}:
            key = key[1:-1].strip()
        if _CANON_LENS_KEY_RE.fullmatch(key):
            return key
        raise ValueError(f"Invalid Canon lens key: {value!r}")
    raise TypeError(f"Unsupported Canon lens key type: {type(value).__name__}")


def canon_lens_key_kind(key: CanonLensKeyValue) -> CanonLensKeyKind:
    normalized_key = normalize_canon_lens_key(key)
    if normalized_key in {"-1", "65535"}:
        return "sentinel"
    if normalized_key == "61182" or normalized_key.startswith("61182."):
        return "rf_master_alias"
    if "." in normalized_key:
        return "decimal_variant"
    return "integer_lens_type"
