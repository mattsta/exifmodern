"""Source-grounded PNG textual metadata database planning.

This module records ExifTool's PNG textual metadata table and the current
runtime boundaries that route those database entries through the PNG chunk
transaction planner.  It is intentionally declarative: it does not read or
mutate PNG files.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

type PngEvidenceId = str

type PngTextualStorageFamily = Literal[
    "textual_keyword",
    "standard_xmp_keyword",
    "raw_profile_keyword",
    "png_exif_chunk",
]
type PngTextualCompressionPolicy = Literal[
    "optional_for_text",
    "required_for_raw_profile_when_available",
    "never_for_standard_xmp",
    "chunk_specific",
]
type PngTextualRuntimeStatus = Literal["ready", "planned"]
type PngTextualSourceDefinitionKind = Literal["hash", "array_variant"]
type PngTextualSourceSupportStatus = Literal[
    "runtime_supported",
    "source_supported_duplicate_variant",
]
type PngTextualSourceLookupField = Literal[
    "keyword",
    "tag_name",
    "storage_family",
    "subdirectory",
]

PNG_PM_SOURCE_PATH = "png_textual_data_source"
PNG_TEXTUAL_TABLE_SOURCE: PngEvidenceId = "png.png_textual_table"
PNG_TEXTUAL_STANDARD_KEYWORDS_SOURCE: PngEvidenceId = "png.png_textual_standard_keywords"
PNG_TEXTUAL_UNREGISTERED_KEYWORDS_SOURCE: PngEvidenceId = "png.png_textual_unregistered_keywords"
PNG_TEXTUAL_XMP_KEYWORD_SOURCE: PngEvidenceId = "png.png_textual_xmp_keyword"
PNG_TEXTUAL_RAW_PROFILE_SOURCE: PngEvidenceId = "png.png_textual_raw_profile"
PNG_EXIF_CHUNK_DATABASE_SOURCE: PngEvidenceId = "png.png_exif_chunk_database"
PNG_TEXT_CHUNK_ROUTING_SOURCE: PngEvidenceId = "png.png_text_chunk_routing"
PNG_ADDCHUNKS_TEXT_SOURCE: PngEvidenceId = "png.png_addchunks_text"
PNG_ADDCHUNKS_EXIF_XMP_SOURCE: PngEvidenceId = "png.png_addchunks_exif_xmp"
PNG_PROCESSPNG_WRITE_GATES_SOURCE: PngEvidenceId = "png.png_processpng_write_gates"
PNG_PROCESSPNG_AFTER_IDAT_SOURCE: PngEvidenceId = "png.png_processpng_after_idat"
PNG_PROCESSPNG_INSERTION_SOURCE: PngEvidenceId = "png.png_processpng_insertion"
PNG_PROCESSPNG_CRC_SOURCE: PngEvidenceId = "png.png_processpng_crc"
PNG_PROCESSPNG_MOVED_TEXT_SOURCE: PngEvidenceId = "png.png_processpng_moved_text"
XMP_ITXT_KEYWORD = "XML:com.adobe.xmp"

_TEXTUAL_DATA_TABLE_RE = re.compile(r"^%Image::ExifTool::PNG::TextualData\s*=\s*\(")
_TEXTUAL_ENTRY_RE = re.compile(
    r"^\s*(?P<key>'[^']+'|[A-Za-z_][A-Za-z0-9_: -]*)\s*=>\s*(?P<rhs>.*)$"
)
_NAME_RE = re.compile(r"\bName\s*=>\s*'(?P<value>[^']+)'")
_GROUP2_RE = re.compile(r"Groups\s*=>\s*\{\s*2\s*=>\s*'(?P<value>[^']+)'")
_NON_STANDARD_RE = re.compile(r"\bNonStandard\s*=>\s*'(?P<value>[^']+)'")
_SUBDIRECTORY_RE = re.compile(r"TagTable\s*=>\s*'(?P<value>[^']+)'")


@dataclass(frozen=True)
class PngTextualDataSourceRecord:
    keyword: str
    tag_name: str
    storage_family: PngTextualStorageFamily
    writable: bool
    registered: bool
    group2: str
    allowed_chunk_types: tuple[str, ...]
    allows_language_suffix: bool
    forces_itxt: bool
    compression_policy: PngTextualCompressionPolicy
    subdirectory: str | None
    non_standard: str | None
    definition_kind: PngTextualSourceDefinitionKind
    variant_index: int
    support_status: PngTextualSourceSupportStatus
    source_line: int
    source_path: str

    @property
    def is_standard_xmp_keyword(self) -> bool:
        return self.keyword == XMP_ITXT_KEYWORD

    @property
    def is_raw_profile_keyword(self) -> bool:
        return self.storage_family == "raw_profile_keyword"

    def to_plan_entry(self) -> PngTextualTagDatabaseEntry:
        return PngTextualTagDatabaseEntry(
            keyword=self.keyword,
            tag_name=self.tag_name,
            storage_family=self.storage_family,
            writable=self.writable,
            registered=self.registered,
            group2=self.group2,
            allowed_chunk_types=self.allowed_chunk_types,
            allows_language_suffix=self.allows_language_suffix,
            forces_itxt=self.forces_itxt,
            compression_policy=self.compression_policy,
            subdirectory=self.subdirectory,
            non_standard=self.non_standard,
            evidence_id=_source_reference_for_record(self),
        )

    def to_json(self) -> JsonObject:
        return {
            "allowed_chunk_types": list(self.allowed_chunk_types),
            "allows_language_suffix": self.allows_language_suffix,
            "compression_policy": self.compression_policy,
            "definition_kind": self.definition_kind,
            "forces_itxt": self.forces_itxt,
            "group2": self.group2,
            "keyword": self.keyword,
            "non_standard": self.non_standard,
            "registered": self.registered,
            "storage_family": self.storage_family,
            "subdirectory": self.subdirectory,
            "support_status": self.support_status,
            "tag_name": self.tag_name,
            "variant_index": self.variant_index,
            "writable": self.writable,
        }


@dataclass(frozen=True)
class PngTextualDuplicateVariantExplanation:
    keyword: str
    selected_variant_index: int
    duplicate_variant_indexes: tuple[int, ...]
    selected_tag_name: str
    duplicate_tag_names: tuple[str, ...]
    selected_subdirectory: str | None
    duplicate_subdirectories: tuple[str | None, ...]
    reason: str
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "duplicate_subdirectories": list(self.duplicate_subdirectories),
            "duplicate_tag_names": list(self.duplicate_tag_names),
            "duplicate_variant_indexes": list(self.duplicate_variant_indexes),
            "keyword": self.keyword,
            "reason": self.reason,
            "selected_subdirectory": self.selected_subdirectory,
            "selected_tag_name": self.selected_tag_name,
            "selected_variant_index": self.selected_variant_index,
        }


@dataclass(frozen=True)
class PngTextualDataSourceIndex:
    by_keyword: dict[str, tuple[PngTextualDataSourceRecord, ...]]
    runtime_by_keyword: dict[str, PngTextualDataSourceRecord]
    by_tag_name: dict[str, tuple[PngTextualDataSourceRecord, ...]]
    by_storage_family: dict[PngTextualStorageFamily, tuple[PngTextualDataSourceRecord, ...]]
    by_subdirectory: dict[str, tuple[PngTextualDataSourceRecord, ...]]
    duplicate_variant_explanations: tuple[PngTextualDuplicateVariantExplanation, ...]

    def records_for_keyword(self, keyword: str) -> tuple[PngTextualDataSourceRecord, ...]:
        return self.by_keyword.get(keyword, ())

    def record_for_keyword(self, keyword: str) -> PngTextualDataSourceRecord | None:
        return self.runtime_by_keyword.get(keyword)

    def records_for_tag_name(self, tag_name: str) -> tuple[PngTextualDataSourceRecord, ...]:
        return self.by_tag_name.get(tag_name, ())

    def records_by_storage_family(
        self, storage_family: PngTextualStorageFamily
    ) -> tuple[PngTextualDataSourceRecord, ...]:
        return self.by_storage_family.get(storage_family, ())

    def records_for_subdirectory(
        self,
        subdirectory: str,
    ) -> tuple[PngTextualDataSourceRecord, ...]:
        return self.by_subdirectory.get(subdirectory, ())

    def supported_records(self) -> tuple[PngTextualDataSourceRecord, ...]:
        return tuple(self.runtime_by_keyword.values())

    def supported_plan_entries(self) -> tuple[PngTextualTagDatabaseEntry, ...]:
        return tuple(record.to_plan_entry() for record in self.supported_records())

    def duplicate_variant_explanation(
        self, keyword: str
    ) -> PngTextualDuplicateVariantExplanation | None:
        for explanation in self.duplicate_variant_explanations:
            if explanation.keyword == keyword:
                return explanation
        return None


@dataclass(frozen=True)
class PngTextualDataSourceTable:
    source_file: str
    source_module: str
    variable: str
    writable: str
    arbitrary_extraction_supported: bool
    arbitrary_write_requires_user_definition: bool
    records: tuple[PngTextualDataSourceRecord, ...]

    def index(self) -> PngTextualDataSourceIndex:
        return png_textual_data_source_index(self.records)

    def records_for_keyword(self, keyword: str) -> tuple[PngTextualDataSourceRecord, ...]:
        return self.index().records_for_keyword(keyword)

    def record_for_keyword(self, keyword: str) -> PngTextualDataSourceRecord | None:
        return self.index().record_for_keyword(keyword)

    def records_for_tag_name(self, tag_name: str) -> tuple[PngTextualDataSourceRecord, ...]:
        return self.index().records_for_tag_name(tag_name)

    def supported_plan_entries(self) -> tuple[PngTextualTagDatabaseEntry, ...]:
        return self.index().supported_plan_entries()

    def records_by_storage_family(
        self, storage_family: PngTextualStorageFamily
    ) -> tuple[PngTextualDataSourceRecord, ...]:
        return self.index().records_by_storage_family(storage_family)

    def records_for_subdirectory(self, subdirectory: str) -> tuple[PngTextualDataSourceRecord, ...]:
        return self.index().records_for_subdirectory(subdirectory)

    def duplicate_variant_explanations(
        self,
    ) -> tuple[PngTextualDuplicateVariantExplanation, ...]:
        return self.index().duplicate_variant_explanations

    def duplicate_variant_explanation(
        self, keyword: str
    ) -> PngTextualDuplicateVariantExplanation | None:
        return self.index().duplicate_variant_explanation(keyword)

    def to_json(self) -> JsonObject:
        return {
            "arbitrary_extraction_supported": self.arbitrary_extraction_supported,
            "arbitrary_write_requires_user_definition": (
                self.arbitrary_write_requires_user_definition
            ),
            "records": json_object_array(record.to_json() for record in self.records),
            "writable": self.writable,
        }


@dataclass(frozen=True)
class PngTextualTagDatabaseEntry:
    keyword: str
    tag_name: str
    storage_family: PngTextualStorageFamily
    writable: bool
    registered: bool
    group2: str
    allowed_chunk_types: tuple[str, ...]
    allows_language_suffix: bool
    forces_itxt: bool
    compression_policy: PngTextualCompressionPolicy
    subdirectory: str | None
    non_standard: str | None
    evidence_id: PngEvidenceId

    @property
    def is_standard_xmp_keyword(self) -> bool:
        return self.keyword == XMP_ITXT_KEYWORD

    @property
    def is_raw_profile_keyword(self) -> bool:
        return self.storage_family == "raw_profile_keyword"

    def to_json(self) -> JsonObject:
        return {
            "allowed_chunk_types": list(self.allowed_chunk_types),
            "allows_language_suffix": self.allows_language_suffix,
            "compression_policy": self.compression_policy,
            "forces_itxt": self.forces_itxt,
            "group2": self.group2,
            "keyword": self.keyword,
            "non_standard": self.non_standard,
            "registered": self.registered,
            "storage_family": self.storage_family,
            "subdirectory": self.subdirectory,
            "tag_name": self.tag_name,
            "writable": self.writable,
        }


@dataclass(frozen=True)
class PngTextualLanguageCompressionPlan:
    text_default_chunk_type: str
    compressed_text_chunk_type: str
    international_text_chunk_type: str
    language_suffix_separator: str
    language_standard: str
    language_requires_itxt: bool
    non_latin_requires_itxt: bool
    user_defined_itxt_flag_requires_itxt: bool
    standard_xmp_chunk_type: str
    standard_xmp_compressed: bool
    raw_profile_compression_policy: PngTextualCompressionPolicy
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "compressed_text_chunk_type": self.compressed_text_chunk_type,
            "international_text_chunk_type": self.international_text_chunk_type,
            "language_requires_itxt": self.language_requires_itxt,
            "language_standard": self.language_standard,
            "language_suffix_separator": self.language_suffix_separator,
            "non_latin_requires_itxt": self.non_latin_requires_itxt,
            "raw_profile_compression_policy": self.raw_profile_compression_policy,
            "standard_xmp_chunk_type": self.standard_xmp_chunk_type,
            "standard_xmp_compressed": self.standard_xmp_compressed,
            "text_default_chunk_type": self.text_default_chunk_type,
            "user_defined_itxt_flag_requires_itxt": self.user_defined_itxt_flag_requires_itxt,
        }


@dataclass(frozen=True)
class PngExifChunkDatabaseResponsibility:
    chunk_type: str
    tag_name: str
    standard_case: str
    non_standard: bool
    subdirectory: str
    write_responsibility: str
    compression_policy: PngTextualCompressionPolicy
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "chunk_type": self.chunk_type,
            "compression_policy": self.compression_policy,
            "non_standard": self.non_standard,
            "standard_case": self.standard_case,
            "subdirectory": self.subdirectory,
            "tag_name": self.tag_name,
            "write_responsibility": self.write_responsibility,
        }


@dataclass(frozen=True)
class PngTextualRuntimeGate:
    gate_id: str
    status: PngTextualRuntimeStatus
    surface: str
    current_planner_entrypoint: str
    current_gate_codes: tuple[str, ...]
    responsibility: str
    evidence_ids: tuple[PngEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "current_gate_codes": list(self.current_gate_codes),
            "current_planner_entrypoint": self.current_planner_entrypoint,
            "gate_id": self.gate_id,
            "responsibility": self.responsibility,
            "status": self.status,
            "surface": self.surface,
        }


@dataclass(frozen=True)
class PngTextualDataDatabasePlan:
    entries: tuple[PngTextualTagDatabaseEntry, ...]
    language_compression: PngTextualLanguageCompressionPlan
    xmp_keyword: PngTextualTagDatabaseEntry
    exif_chunk_responsibilities: tuple[PngExifChunkDatabaseResponsibility, ...]
    runtime_gates: tuple[PngTextualRuntimeGate, ...]
    evidence_ids: tuple[PngEvidenceId, ...]

    def entry(self, keyword: str) -> PngTextualTagDatabaseEntry:
        for entry in self.entries:
            if entry.keyword == keyword:
                return entry
        raise KeyError(keyword)

    def entries_by_storage_family(
        self, storage_family: PngTextualStorageFamily
    ) -> tuple[PngTextualTagDatabaseEntry, ...]:
        return tuple(entry for entry in self.entries if entry.storage_family == storage_family)

    def runtime_gate(self, gate_id: str) -> PngTextualRuntimeGate:
        for gate in self.runtime_gates:
            if gate.gate_id == gate_id:
                return gate
        raise KeyError(gate_id)

    def to_json(self) -> JsonObject:
        return {
            "entries": json_object_array(entry.to_json() for entry in self.entries),
            "exif_chunk_responsibilities": json_object_array(
                responsibility.to_json() for responsibility in self.exif_chunk_responsibilities
            ),
            "language_compression": self.language_compression.to_json(),
            "runtime_gates": json_object_array(gate.to_json() for gate in self.runtime_gates),
            "xmp_keyword": self.xmp_keyword.to_json(),
        }


def png_textual_data_database_plan() -> PngTextualDataDatabasePlan:
    entries = _database_entries()
    xmp_keyword = _entry_by_keyword(entries, XMP_ITXT_KEYWORD)
    runtime_gates = _runtime_gates()
    exif_responsibilities = _exif_chunk_responsibilities()
    evidence_ids = _unique_evidence_ids(
        (
            PNG_TEXTUAL_TABLE_SOURCE,
            PNG_TEXTUAL_STANDARD_KEYWORDS_SOURCE,
            PNG_TEXTUAL_UNREGISTERED_KEYWORDS_SOURCE,
            PNG_TEXTUAL_XMP_KEYWORD_SOURCE,
            PNG_TEXTUAL_RAW_PROFILE_SOURCE,
            PNG_EXIF_CHUNK_DATABASE_SOURCE,
            PNG_TEXT_CHUNK_ROUTING_SOURCE,
            PNG_ADDCHUNKS_TEXT_SOURCE,
            PNG_ADDCHUNKS_EXIF_XMP_SOURCE,
            PNG_PROCESSPNG_WRITE_GATES_SOURCE,
            PNG_PROCESSPNG_AFTER_IDAT_SOURCE,
            PNG_PROCESSPNG_INSERTION_SOURCE,
            PNG_PROCESSPNG_CRC_SOURCE,
            PNG_PROCESSPNG_MOVED_TEXT_SOURCE,
        )
    )
    return PngTextualDataDatabasePlan(
        entries=entries,
        language_compression=_language_compression_plan(),
        xmp_keyword=xmp_keyword,
        exif_chunk_responsibilities=exif_responsibilities,
        runtime_gates=runtime_gates,
        evidence_ids=evidence_ids,
    )


def png_textual_data_source_table_from_source_path(
    source_path: str | Path,
) -> PngTextualDataSourceTable:
    path = Path(source_path)
    return png_textual_data_source_table_from_source_text(
        path.read_text(encoding="utf-8"),
        path.as_posix(),
    )


def png_textual_data_source_table_from_source_text(
    source_text: str,
    source_path: str = PNG_PM_SOURCE_PATH,
) -> PngTextualDataSourceTable:
    entries = _extract_textual_data_source_entries(source_text)
    records: list[PngTextualDataSourceRecord] = []
    for entry in entries:
        records.extend(_source_records_from_entry(entry, source_path))
    return PngTextualDataSourceTable(
        source_file=source_path,
        source_module="Image::ExifTool::PNG",
        variable="TextualData",
        writable="string",
        arbitrary_extraction_supported=True,
        arbitrary_write_requires_user_definition=True,
        records=tuple(records),
    )


def png_textual_data_source_index(
    records: tuple[PngTextualDataSourceRecord, ...],
) -> PngTextualDataSourceIndex:
    by_keyword: dict[str, list[PngTextualDataSourceRecord]] = {}
    runtime_by_keyword: dict[str, PngTextualDataSourceRecord] = {}
    by_tag_name: dict[str, list[PngTextualDataSourceRecord]] = {}
    by_storage_family: dict[PngTextualStorageFamily, list[PngTextualDataSourceRecord]] = {}
    by_subdirectory: dict[str, list[PngTextualDataSourceRecord]] = {}
    for record in records:
        by_keyword.setdefault(record.keyword, []).append(record)
        by_tag_name.setdefault(record.tag_name, []).append(record)
        by_storage_family.setdefault(record.storage_family, []).append(record)
        if record.subdirectory is not None:
            by_subdirectory.setdefault(record.subdirectory, []).append(record)
        if record.support_status == "runtime_supported":
            runtime_by_keyword[record.keyword] = record
    frozen_by_keyword = _freeze_record_list_lookup(by_keyword)
    return PngTextualDataSourceIndex(
        by_keyword=frozen_by_keyword,
        runtime_by_keyword=runtime_by_keyword,
        by_tag_name=_freeze_record_list_lookup(by_tag_name),
        by_storage_family=_freeze_record_list_lookup(by_storage_family),
        by_subdirectory=_freeze_record_list_lookup(by_subdirectory),
        duplicate_variant_explanations=_duplicate_variant_explanations(frozen_by_keyword),
    )


def _freeze_record_list_lookup[LookupKey](
    lookup: dict[LookupKey, list[PngTextualDataSourceRecord]],
) -> dict[LookupKey, tuple[PngTextualDataSourceRecord, ...]]:
    return {key: tuple(records) for key, records in lookup.items()}


def _duplicate_variant_explanations(
    by_keyword: dict[str, tuple[PngTextualDataSourceRecord, ...]],
) -> tuple[PngTextualDuplicateVariantExplanation, ...]:
    explanations: list[PngTextualDuplicateVariantExplanation] = []
    for keyword, variants in by_keyword.items():
        if len(variants) < 2:
            continue
        selected = _selected_supported_variant(keyword, variants)
        duplicates = tuple(
            record for record in variants if record.support_status != "runtime_supported"
        )
        explanations.append(
            PngTextualDuplicateVariantExplanation(
                keyword=keyword,
                selected_variant_index=selected.variant_index,
                duplicate_variant_indexes=tuple(record.variant_index for record in duplicates),
                selected_tag_name=selected.tag_name,
                duplicate_tag_names=tuple(record.tag_name for record in duplicates),
                selected_subdirectory=selected.subdirectory,
                duplicate_subdirectories=tuple(record.subdirectory for record in duplicates),
                reason=_duplicate_variant_reason(keyword),
                evidence_ids=(PNG_TEXTUAL_RAW_PROFILE_SOURCE,),
            )
        )
    return tuple(explanations)


def _selected_supported_variant(
    keyword: str,
    variants: tuple[PngTextualDataSourceRecord, ...],
) -> PngTextualDataSourceRecord:
    for record in variants:
        if record.support_status == "runtime_supported":
            return record
    raise ValueError(f"PNG TextualData entry has no runtime-supported variant: {keyword}")


def _duplicate_variant_reason(keyword: str) -> str:
    if keyword == "Raw profile type APP1":
        return (
            "PNG.pm defines APP1_Profile as an array with the EXIF variant first "
            "because ProcessProfile keys on that ordering; the XMP variant remains "
            "source-supported but is not promoted as the runtime lookup winner."
        )
    return (
        "PNG.pm defines multiple variants for this textual keyword; the first "
        "runtime-supported variant is the lookup winner and later variants remain "
        "explicit source-backed duplicates."
    )


def _database_entries() -> tuple[PngTextualTagDatabaseEntry, ...]:
    return (
        _text_entry("Title", registered=True),
        _text_entry("Author", group2="Author", registered=True),
        _text_entry("Description", registered=True),
        _text_entry("Copyright", group2="Author", registered=True),
        _text_entry(
            "Creation Time",
            tag_name="CreationTime",
            group2="Time",
            registered=True,
            evidence_id=PNG_TEXTUAL_STANDARD_KEYWORDS_SOURCE,
        ),
        _text_entry("Software", registered=True),
        _text_entry("Disclaimer", registered=True),
        _text_entry("Warning", tag_name="PNGWarning", registered=True),
        _text_entry("Source", registered=True),
        _text_entry("Comment", registered=True),
        _text_entry("Collection", registered=True),
        _text_entry("Artist", group2="Author"),
        _text_entry("Document"),
        _text_entry("Label"),
        _text_entry("Make", group2="Camera"),
        _text_entry("Model", group2="Camera"),
        _text_entry("parameters"),
        _text_entry("aesthetic_score", tag_name="AestheticScore"),
        _text_entry("create-date", tag_name="CreateDate", group2="Time"),
        _text_entry("modify-date", tag_name="ModDate", group2="Time"),
        _text_entry("TimeStamp", group2="Time"),
        _text_entry("URL"),
        PngTextualTagDatabaseEntry(
            keyword=XMP_ITXT_KEYWORD,
            tag_name="XMP",
            storage_family="standard_xmp_keyword",
            writable=True,
            registered=False,
            group2="Image",
            allowed_chunk_types=("iTXt",),
            allows_language_suffix=False,
            forces_itxt=True,
            compression_policy="never_for_standard_xmp",
            subdirectory="Image::ExifTool::XMP::Main",
            non_standard=None,
            evidence_id=PNG_TEXTUAL_XMP_KEYWORD_SOURCE,
        ),
        _raw_profile_entry("Raw profile type APP1", "APP1_Profile", "EXIF"),
        _raw_profile_entry("Raw profile type exif", "EXIF_Profile", "EXIF"),
        _raw_profile_entry("Raw profile type icc", "ICC_Profile"),
        _raw_profile_entry("Raw profile type icm", "ICC_Profile"),
        _raw_profile_entry("Raw profile type iptc", "IPTC_Profile"),
        _raw_profile_entry("Raw profile type xmp", "XMP_Profile", "XMP"),
        _raw_profile_entry("Raw profile type 8bim", "Photoshop_Profile"),
    )


@dataclass(frozen=True)
class _PngTextualSourceEntry:
    keyword: str
    definition: str
    source_line: int


@dataclass(frozen=True)
class _PngTextualSourceVariant:
    definition: str
    source_line: int


def _extract_textual_data_source_entries(source_text: str) -> tuple[_PngTextualSourceEntry, ...]:
    lines = source_text.splitlines()
    table_start = _find_textual_data_table_start(lines)
    first_entry = _find_first_textual_data_entry(lines, table_start)
    entries: list[_PngTextualSourceEntry] = []
    current_keyword: str | None = None
    current_start = 0
    current_lines: list[str] = []
    current_depth = 0
    for line_index in range(first_entry, len(lines)):
        line = lines[line_index]
        if line.startswith(");") and current_keyword is None:
            break
        if current_keyword is None:
            match = _TEXTUAL_ENTRY_RE.match(line)
            if match is None:
                continue
            current_keyword = _perl_key(match.group("key"))
            current_start = line_index + 1
            current_lines = [line]
            current_depth = _source_definition_depth(line)
            if current_depth <= 0:
                entries.append(
                    _PngTextualSourceEntry(
                        keyword=current_keyword,
                        definition="\n".join(current_lines),
                        source_line=current_start,
                    )
                )
                current_keyword = None
            continue
        current_lines.append(line)
        current_depth += _source_definition_depth(line)
        if current_depth <= 0:
            entries.append(
                _PngTextualSourceEntry(
                    keyword=current_keyword,
                    definition="\n".join(current_lines),
                    source_line=current_start,
                )
            )
            current_keyword = None
    if current_keyword is not None:
        raise ValueError(f"Unterminated PNG TextualData entry: {current_keyword}")
    return tuple(entries)


def _find_textual_data_table_start(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if _TEXTUAL_DATA_TABLE_RE.match(line):
            return index
    raise ValueError("PNG TextualData table was not found")


def _find_first_textual_data_entry(lines: list[str], table_start: int) -> int:
    for index in range(table_start + 1, len(lines)):
        if re.match(r"^\s*Title\s*=>", lines[index]):
            return index
    raise ValueError("PNG TextualData Title entry was not found")


def _source_definition_depth(line: str) -> int:
    stripped = _strip_perl_comment(line)
    return stripped.count("{") + stripped.count("[") - stripped.count("}") - stripped.count("]")


def _strip_perl_comment(line: str) -> str:
    in_string = False
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == "'":
            in_string = not in_string
            continue
        if char == "#" and not in_string:
            return line[:index]
    return line


def _perl_key(raw_key: str) -> str:
    if raw_key.startswith("'") and raw_key.endswith("'"):
        return raw_key[1:-1]
    return raw_key.strip()


def _source_records_from_entry(
    entry: _PngTextualSourceEntry,
    source_path: str,
) -> tuple[PngTextualDataSourceRecord, ...]:
    variants = _source_entry_variants(entry)
    return tuple(
        _source_record_from_variant(
            entry=entry,
            variant=variant,
            source_path=source_path,
            variant_index=variant_index,
            variant_count=len(variants),
        )
        for variant_index, variant in enumerate(variants)
    )


def _source_entry_variants(
    entry: _PngTextualSourceEntry,
) -> tuple[_PngTextualSourceVariant, ...]:
    rhs = entry.definition.split("=>", 1)[1].lstrip()
    if not rhs.startswith("["):
        return (
            _PngTextualSourceVariant(
                definition=entry.definition,
                source_line=entry.source_line,
            ),
        )
    return _array_hash_variants(entry.definition, entry.source_line)


def _array_hash_variants(
    definition: str,
    entry_source_line: int,
) -> tuple[_PngTextualSourceVariant, ...]:
    variants: list[_PngTextualSourceVariant] = []
    current_lines: list[str] = []
    current_start = 0
    depth = 0
    in_variant = False
    for offset, line in enumerate(definition.splitlines()):
        if not in_variant and "{" in _strip_perl_comment(line):
            in_variant = True
            current_start = entry_source_line + offset
            current_lines = [line]
            depth = _source_definition_depth(line)
            if depth <= 0:
                variants.append(
                    _PngTextualSourceVariant(
                        definition="\n".join(current_lines),
                        source_line=current_start,
                    )
                )
                in_variant = False
            continue
        if not in_variant:
            continue
        current_lines.append(line)
        depth += _source_definition_depth(line)
        if depth <= 0:
            variants.append(
                _PngTextualSourceVariant(
                    definition="\n".join(current_lines),
                    source_line=current_start,
                )
            )
            in_variant = False
    if not variants:
        raise ValueError("PNG TextualData array entry contains no hash variants")
    return tuple(variants)


def _source_record_from_variant(
    *,
    entry: _PngTextualSourceEntry,
    variant: _PngTextualSourceVariant,
    source_path: str,
    variant_index: int,
    variant_count: int,
) -> PngTextualDataSourceRecord:
    storage_family = _source_storage_family(entry.keyword)
    tag_name = _source_field_value(_NAME_RE, variant.definition) or entry.keyword
    non_standard = _source_non_standard(entry.keyword, storage_family, variant.definition)
    return PngTextualDataSourceRecord(
        keyword=entry.keyword,
        tag_name=tag_name,
        storage_family=storage_family,
        writable=True,
        registered=_source_registered(entry.keyword, storage_family, variant.definition),
        group2=_source_field_value(_GROUP2_RE, variant.definition) or "Image",
        allowed_chunk_types=_source_allowed_chunk_types(storage_family),
        allows_language_suffix=storage_family == "textual_keyword",
        forces_itxt=storage_family == "standard_xmp_keyword",
        compression_policy=_source_compression_policy(storage_family),
        subdirectory=_source_field_value(_SUBDIRECTORY_RE, variant.definition),
        non_standard=non_standard,
        definition_kind="array_variant" if variant_count > 1 else "hash",
        variant_index=variant_index,
        support_status=(
            "source_supported_duplicate_variant"
            if variant_count > 1 and variant_index > 0
            else "runtime_supported"
        ),
        source_line=variant.source_line,
        source_path=source_path,
    )


def _source_field_value(pattern: re.Pattern[str], definition: str) -> str | None:
    match = pattern.search(definition)
    if match is None:
        return None
    return match.group("value")


def _source_storage_family(keyword: str) -> PngTextualStorageFamily:
    if keyword == XMP_ITXT_KEYWORD:
        return "standard_xmp_keyword"
    if keyword.startswith("Raw profile type "):
        return "raw_profile_keyword"
    return "textual_keyword"


def _source_registered(
    keyword: str,
    storage_family: PngTextualStorageFamily,
    definition: str,
) -> bool:
    return (
        storage_family == "textual_keyword"
        and "%unreg" not in definition
        and keyword != XMP_ITXT_KEYWORD
    )


def _source_non_standard(
    keyword: str,
    storage_family: PngTextualStorageFamily,
    definition: str,
) -> str | None:
    explicit = _source_field_value(_NON_STANDARD_RE, definition)
    if explicit is not None:
        return explicit
    if "%unreg" in definition or storage_family == "raw_profile_keyword":
        return "unregistered"
    if keyword == XMP_ITXT_KEYWORD:
        return "unregistered"
    return None


def _source_allowed_chunk_types(
    storage_family: PngTextualStorageFamily,
) -> tuple[str, ...]:
    if storage_family == "standard_xmp_keyword":
        return ("iTXt",)
    if storage_family == "raw_profile_keyword":
        return ("zTXt", "tEXt")
    return ("tEXt", "zTXt", "iTXt")


def _source_compression_policy(
    storage_family: PngTextualStorageFamily,
) -> PngTextualCompressionPolicy:
    if storage_family == "standard_xmp_keyword":
        return "never_for_standard_xmp"
    if storage_family == "raw_profile_keyword":
        return "required_for_raw_profile_when_available"
    return "optional_for_text"


def _source_reference_for_record(record: PngTextualDataSourceRecord) -> PngEvidenceId:
    if record.storage_family == "standard_xmp_keyword":
        return PNG_TEXTUAL_XMP_KEYWORD_SOURCE
    if record.storage_family == "raw_profile_keyword":
        return PNG_TEXTUAL_RAW_PROFILE_SOURCE
    if record.registered:
        return PNG_TEXTUAL_STANDARD_KEYWORDS_SOURCE
    return PNG_TEXTUAL_UNREGISTERED_KEYWORDS_SOURCE


def _text_entry(
    keyword: str,
    *,
    tag_name: str | None = None,
    group2: str = "Image",
    registered: bool = False,
    evidence_id: PngEvidenceId | None = None,
) -> PngTextualTagDatabaseEntry:
    if evidence_id is None:
        evidence_id = (
            PNG_TEXTUAL_STANDARD_KEYWORDS_SOURCE
            if registered
            else PNG_TEXTUAL_UNREGISTERED_KEYWORDS_SOURCE
        )
    return PngTextualTagDatabaseEntry(
        keyword=keyword,
        tag_name=tag_name or keyword,
        storage_family="textual_keyword",
        writable=True,
        registered=registered,
        group2=group2,
        allowed_chunk_types=("tEXt", "zTXt", "iTXt"),
        allows_language_suffix=True,
        forces_itxt=False,
        compression_policy="optional_for_text",
        subdirectory=None,
        non_standard=None if registered else "unregistered",
        evidence_id=evidence_id,
    )


def _raw_profile_entry(
    keyword: str,
    tag_name: str,
    non_standard: str | None = None,
) -> PngTextualTagDatabaseEntry:
    return PngTextualTagDatabaseEntry(
        keyword=keyword,
        tag_name=tag_name,
        storage_family="raw_profile_keyword",
        writable=True,
        registered=False,
        group2="Image",
        allowed_chunk_types=("zTXt", "tEXt"),
        allows_language_suffix=False,
        forces_itxt=False,
        compression_policy="required_for_raw_profile_when_available",
        subdirectory=_raw_profile_subdirectory(tag_name),
        non_standard=non_standard or "unregistered",
        evidence_id=PNG_TEXTUAL_RAW_PROFILE_SOURCE,
    )


def _raw_profile_subdirectory(tag_name: str) -> str:
    if tag_name in {"APP1_Profile", "EXIF_Profile"}:
        return "Image::ExifTool::Exif::Main"
    if tag_name == "XMP_Profile":
        return "Image::ExifTool::XMP::Main"
    if tag_name == "ICC_Profile":
        return "Image::ExifTool::ICC_Profile::Main"
    return "Image::ExifTool::Photoshop::Main"


def _language_compression_plan() -> PngTextualLanguageCompressionPlan:
    return PngTextualLanguageCompressionPlan(
        text_default_chunk_type="tEXt",
        compressed_text_chunk_type="zTXt",
        international_text_chunk_type="iTXt",
        language_suffix_separator="-",
        language_standard="RFC 3066",
        language_requires_itxt=True,
        non_latin_requires_itxt=True,
        user_defined_itxt_flag_requires_itxt=True,
        standard_xmp_chunk_type="iTXt",
        standard_xmp_compressed=False,
        raw_profile_compression_policy="required_for_raw_profile_when_available",
        evidence_ids=(PNG_TEXTUAL_TABLE_SOURCE, PNG_TEXT_CHUNK_ROUTING_SOURCE),
    )


def _exif_chunk_responsibilities() -> tuple[PngExifChunkDatabaseResponsibility, ...]:
    return (
        PngExifChunkDatabaseResponsibility(
            chunk_type="eXIf",
            tag_name="eXIf",
            standard_case="eXIf",
            non_standard=False,
            subdirectory="Image::ExifTool::Exif::Main",
            write_responsibility="Create new EXIF as a PNG eXIf chunk via IFD0.",
            compression_policy="chunk_specific",
            evidence_ids=(PNG_EXIF_CHUNK_DATABASE_SOURCE, PNG_ADDCHUNKS_EXIF_XMP_SOURCE),
        ),
        PngExifChunkDatabaseResponsibility(
            chunk_type="zXIf",
            tag_name="zXIf",
            standard_case="zXIf",
            non_standard=True,
            subdirectory="Image::ExifTool::Exif::Main",
            write_responsibility=(
                "Recognize the once-proposed compressed EXIF chunk, but do not create "
                "it for new writes."
            ),
            compression_policy="chunk_specific",
            evidence_ids=(PNG_EXIF_CHUNK_DATABASE_SOURCE, PNG_ADDCHUNKS_EXIF_XMP_SOURCE),
        ),
    )


def _runtime_gates() -> tuple[PngTextualRuntimeGate, ...]:
    entrypoint = "exifmodern.formats.png.chunk_transaction_plan.build_png_chunk_transaction_plan"
    return (
        PngTextualRuntimeGate(
            gate_id="current_textual_keyword_database_subset",
            status="ready",
            surface="database",
            current_planner_entrypoint=entrypoint,
            current_gate_codes=(),
            responsibility=(
                "Expose ExifTool's writable TextualData keywords and storage policy "
                "for planner callers."
            ),
            evidence_ids=(PNG_TEXTUAL_TABLE_SOURCE, PNG_ADDCHUNKS_TEXT_SOURCE),
        ),
        PngTextualRuntimeGate(
            gate_id="text_xmp_exif_insert_before_idat",
            status="ready",
            surface="chunk_transaction_plan",
            current_planner_entrypoint=entrypoint,
            current_gate_codes=("planned_chunk_too_large",),
            responsibility=("Route new text, standard XMP, and eXIf output before IDAT or IEND."),
            evidence_ids=(PNG_PROCESSPNG_INSERTION_SOURCE, PNG_ADDCHUNKS_EXIF_XMP_SOURCE),
        ),
        PngTextualRuntimeGate(
            gate_id="after_idat_text_move_or_block",
            status="ready",
            surface="chunk_transaction_plan",
            current_planner_entrypoint=entrypoint,
            current_gate_codes=("text_after_idat_cannot_move_across_no_leapfrog",),
            responsibility=(
                "Move text/XMP/eXIf chunks after IDAT before image data unless a "
                "no-leapfrog chunk blocks movement."
            ),
            evidence_ids=(PNG_PROCESSPNG_AFTER_IDAT_SOURCE, PNG_PROCESSPNG_MOVED_TEXT_SOURCE),
        ),
        PngTextualRuntimeGate(
            gate_id="crc_and_non_mutating_output",
            status="ready",
            surface="chunk_transaction_plan",
            current_planner_entrypoint=entrypoint,
            current_gate_codes=("bad_crc", "non_mutating_plan_requires_explicit_emission"),
            responsibility=(
                "Keep byte emission gated by CRC validation and explicit caller opt-in."
            ),
            evidence_ids=(PNG_PROCESSPNG_CRC_SOURCE,),
        ),
        PngTextualRuntimeGate(
            gate_id="full_arbitrary_user_defined_textual_tags",
            status="planned",
            surface="configuration",
            current_planner_entrypoint=entrypoint,
            current_gate_codes=(),
            responsibility=(
                "ExifTool can extract arbitrary textual keywords and write user-defined "
                "configured tags; this plan covers built-in database entries only."
            ),
            evidence_ids=(PNG_TEXTUAL_TABLE_SOURCE,),
        ),
    )


def _entry_by_keyword(
    entries: tuple[PngTextualTagDatabaseEntry, ...], keyword: str
) -> PngTextualTagDatabaseEntry:
    for entry in entries:
        if entry.keyword == keyword:
            return entry
    raise KeyError(keyword)


def _unique_evidence_ids(
    evidence_ids: tuple[PngEvidenceId, ...],
) -> tuple[PngEvidenceId, ...]:
    seen: set[PngEvidenceId] = set()
    unique: list[PngEvidenceId] = []
    for evidence_id in evidence_ids:
        if evidence_id not in seen:
            seen.add(evidence_id)
            unique.append(evidence_id)
    return tuple(unique)


def json_object_array(items: Iterable[JsonObject]) -> JsonArray:
    values: JsonArray = []
    for item in items:
        values.append(item)
    return values
