"""Typed RIFF reader-plan records shared by RIFF package adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from exifmodern.formats.riff.wav_metadata_transaction_plan import (
    RiffChunkPlan,
    RiffEmissionGate,
    RiffSignatureValidationPlan,
)
from exifmodern.json_types import JsonObject, JsonValue
from exifmodern.read_graph import BinaryTagValue, tag_value_to_json_value

type RiffReaderStatus = Literal["planned", "unsupported"]
type RiffNestedRouteStatus = Literal[
    "extracted",
    "extraction_ready",
    "adapter_missing",
    "unsupported_payload",
]
type RiffReaderGateCode = Literal[
    "truncated_riff_header",
    "unsupported_riff_signature",
    "unsupported_riff_form_type",
    "truncated_riff_chunk",
    "missing_odd_chunk_padding",
    "trailing_partial_chunk_header",
]
type RiffTagValue = (
    bytes | str | int | float | bool | None | tuple[int, ...] | tuple[str, ...] | BinaryTagValue
)
type RiffRenderedValue = bytes | str | int | float | bool | None | tuple[str, ...] | BinaryTagValue
type _EvidenceTuple = tuple[str, ...]


@dataclass(frozen=True)
class RiffNestedMetadataRoute:
    chunk_id: str
    chunk_index: int
    byte_offset: int
    payload_length: int
    target_table: str
    payload_kind: str
    status: RiffNestedRouteStatus
    detail: str
    extracted_tag_count: int
    evidence_ids: _EvidenceTuple
    route_details: JsonObject = field(default_factory=dict)

    def to_json(self) -> JsonObject:
        return {
            "byte_offset": self.byte_offset,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "detail": self.detail,
            "extracted_tag_count": self.extracted_tag_count,
            "payload_kind": self.payload_kind,
            "payload_length": self.payload_length,
            "route_details": self.route_details,
            "status": self.status,
            "target_table": self.target_table,
        }


@dataclass(frozen=True)
class RiffReadTag:
    name: str
    group: str
    source_table: str
    tag_id: str
    raw_value: RiffTagValue
    rendered_value: RiffRenderedValue
    chunk_id: str
    chunk_index: int | None
    byte_offset: int
    evidence_ids: _EvidenceTuple

    def to_json(self) -> JsonObject:
        return {
            "byte_offset": self.byte_offset,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "group": self.group,
            "name": self.name,
            "raw_value": tag_value_to_json(self.raw_value),
            "rendered_value": tag_value_to_json(self.rendered_value),
            "source_table": self.source_table,
            "tag_id": self.tag_id,
        }


@dataclass(frozen=True)
class RiffReaderPlan:
    status: RiffReaderStatus
    signature_validation: RiffSignatureValidationPlan
    chunks: tuple[RiffChunkPlan, ...]
    nested_metadata_routes: tuple[RiffNestedMetadataRoute, ...]
    tags: tuple[RiffReadTag, ...]
    output_emission_gates: tuple[RiffEmissionGate, ...]
    evidence_ids: _EvidenceTuple

    @property
    def file_type(self) -> str | None:
        for tag in reversed(self.tags):
            if tag.name == "FileType":
                return str(tag.rendered_value)
        return None

    def tags_by_name(self) -> dict[str, tuple[RiffReadTag, ...]]:
        names = {tag.name for tag in self.tags}
        return {name: tuple(tag for tag in self.tags if tag.name == name) for name in names}

    def to_json(self) -> JsonObject:
        return {
            "chunks": [chunk.to_json() for chunk in self.chunks],
            "file_type": self.file_type,
            "nested_metadata_routes": [route.to_json() for route in self.nested_metadata_routes],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "signature_validation": self.signature_validation.to_json(),
            "status": self.status,
            "tags": [tag.to_json() for tag in self.tags],
        }


def riff_tag_value_from_json(value: JsonValue) -> RiffTagValue:
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            if not isinstance(item, str):
                return None
            strings.append(item)
        return tuple(strings)
    if isinstance(value, dict):
        return None
    return value


def riff_rendered_value_from_tag_value(value: RiffTagValue) -> RiffRenderedValue:
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    return value


def tag_value_to_json(value: RiffTagValue | RiffRenderedValue) -> JsonValue:
    if isinstance(value, BinaryTagValue):
        return tag_value_to_json_value(value)
    if isinstance(value, bytes):
        return {
            "type": "binary",
            "byte_count": len(value),
            "hex": value.hex(),
        }
    if isinstance(value, tuple):
        return list(value)
    return value
