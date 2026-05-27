"""Source-backed JSON metadata reader plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.formats.json.metadata_transaction_plan import (
    JSON_TRANSACTION_SOURCES,
    JsonDatabaseEntryPlan,
    JsonMetadataTransactionPlan,
    build_json_metadata_transaction_plan,
)
from exifmodern.json_types import JsonObject, JsonValue

type JsonReaderStatus = Literal["planned", "unsupported"]
type JsonReaderDiagnosticCode = Literal["malformed_json_document", "unsupported_json_database"]


@dataclass(frozen=True)
class JsonReaderDiagnostic:
    code: JsonReaderDiagnosticCode
    detail: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class JsonReadTag:
    name: str
    group: str
    source_table: str
    tag_id: str
    raw_value: JsonValue
    rendered_value: JsonValue
    source_file: str
    byte_range: tuple[int, int]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": [self.byte_range[0], self.byte_range[1]],
            "group": self.group,
            "name": self.name,
            "raw_value": self.raw_value,
            "rendered_value": self.rendered_value,
            "source_file": self.source_file,
            "source_table": self.source_table,
            "tag_id": self.tag_id,
        }


@dataclass(frozen=True)
class JsonReaderPlan:
    status: JsonReaderStatus
    metadata: JsonMetadataTransactionPlan
    tags: tuple[JsonReadTag, ...]
    diagnostics: tuple[JsonReaderDiagnostic, ...]
    evidence_ids: tuple[str, ...]

    def tags_by_name(self) -> dict[str, tuple[JsonReadTag, ...]]:
        names = {tag.name for tag in self.tags}
        return {name: tuple(tag for tag in self.tags if tag.name == name) for name in names}

    def to_json(self) -> JsonObject:
        return {
            "diagnostics": [diagnostic.to_json() for diagnostic in self.diagnostics],
            "status": self.status,
            "tags": [tag.to_json() for tag in self.tags],
        }


def build_json_reader_plan(data: bytes) -> JsonReaderPlan:
    metadata = build_json_metadata_transaction_plan(data, allow_output_emission=True)
    diagnostics = tuple(
        JsonReaderDiagnostic(
            code=(
                "unsupported_json_database"
                if gate.code.startswith("top_level")
                else "malformed_json_document"
            ),
            detail=gate.code,
            evidence_ids=gate.evidence_ids,
        )
        for gate in metadata.output_emission_gates
    )
    tags = _json_read_tags_from_entries(metadata.database_entries)
    return JsonReaderPlan(
        status="unsupported" if diagnostics or metadata.status != "planned" else "planned",
        metadata=metadata,
        tags=tags,
        diagnostics=diagnostics,
        evidence_ids=JSON_TRANSACTION_SOURCES,
    )


plan_json_reader = build_json_reader_plan


def _json_read_tags_from_entries(
    entries: tuple[JsonDatabaseEntryPlan, ...],
) -> tuple[JsonReadTag, ...]:
    ordered: list[JsonReadTag] = []
    list_values: dict[str, list[JsonValue]] = {}
    list_tag_indexes: dict[str, int] = {}
    for entry in entries:
        name = entry.generated_name
        rendered_value = _json_scalar_value(entry.value.kind, entry.value.display_value)
        raw_value = _json_scalar_value(entry.value.kind, entry.value.raw_text)
        if entry.list_item:
            if name not in list_values:
                list_values[name] = []
                list_tag_indexes[name] = len(ordered)
                ordered.append(
                    JsonReadTag(
                        name=name,
                        group="JSON",
                        source_table="Image::ExifTool::JSON::Main",
                        tag_id=entry.tag_id,
                        raw_value=[],
                        rendered_value=[],
                        source_file=entry.source_file,
                        byte_range=entry.value.byte_range,
                        evidence_ids=entry.evidence_ids,
                    )
                )
            list_values[name].append(rendered_value)
            original = ordered[list_tag_indexes[name]]
            ordered[list_tag_indexes[name]] = JsonReadTag(
                name=original.name,
                group=original.group,
                source_table=original.source_table,
                tag_id=original.tag_id,
                raw_value=list(list_values[name]),
                rendered_value=list(list_values[name]),
                source_file=original.source_file,
                byte_range=(
                    min(original.byte_range[0], entry.value.byte_range[0]),
                    max(original.byte_range[1], entry.value.byte_range[1]),
                ),
                evidence_ids=original.evidence_ids,
            )
            continue
        ordered.append(
            JsonReadTag(
                name=name,
                group="JSON",
                source_table="Image::ExifTool::JSON::Main",
                tag_id=entry.tag_id,
                raw_value=raw_value,
                rendered_value=rendered_value,
                source_file=entry.source_file,
                byte_range=entry.value.byte_range,
                evidence_ids=entry.evidence_ids,
            )
        )
    return tuple(ordered)


def _json_scalar_value(kind: str, value: JsonValue) -> JsonValue:
    if kind == "number" and isinstance(value, str):
        return _json_number_value(value)
    if kind == "boolean" and isinstance(value, str):
        return value == "true"
    return value


def _json_number_value(value: str) -> int | float | str:
    try:
        if "." not in value and "e" not in value.lower():
            return int(value)
        return float(value)
    except ValueError:
        return value


install_evidence_reference_compat(globals())
