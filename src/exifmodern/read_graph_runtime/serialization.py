"""JSON projection helpers for read graph values."""

from __future__ import annotations

from base64 import b64encode
from typing import TYPE_CHECKING, Protocol, TypeGuard

from exifmodern.json_types import JsonObject, JsonValue

if TYPE_CHECKING:
    from exifmodern.read_graph_runtime.graph import ReadGraph, ReadTag, TagProvenance, TagValue


class _BinaryTagValueLike(Protocol):
    data: bytes
    media_type: str | None
    file_extension: str | None

    @property
    def byte_count(self) -> int: ...


class _BinaryTagListValueLike(Protocol):
    items: tuple[_BinaryTagValueLike, ...]

    @property
    def byte_count(self) -> int: ...

    @property
    def item_count(self) -> int: ...


def read_graph_to_json_value(graph: ReadGraph) -> JsonObject:
    payload: JsonObject = {
        "schema_version": graph.schema_version,
        "generated_at_epoch": graph.generated_at_epoch,
        "source_file": graph.source_file,
        "tags": [read_tag_to_json_value(tag) for tag in graph.tags],
        "diagnostics": list(graph.diagnostics),
    }
    if graph.html_dump_state is not None:
        from exifmodern.formats.jpeg.html_dump_state import html_dump_read_state_to_json_value

        payload["html_dump_state"] = html_dump_read_state_to_json_value(graph.html_dump_state)
    return payload


def read_tag_to_json_value(tag: ReadTag) -> JsonObject:
    return {
        "name": tag.name,
        "value": tag_value_to_json_value(tag.value),
        "provenance": tag_provenance_to_json_value(tag.provenance),
        "schema": None
        if tag.schema is None
        else {
            "matched": tag.schema.matched,
            "schema_name": tag.schema.schema_name,
            "schema_tag_id": tag.schema.schema_tag_id,
            "writable": tag.schema.writable,
            "write_group": tag.schema.write_group,
            "operation_count": tag.schema.operation_count,
            "operations": list(tag.schema.operations),
            "runtime_dynamic": tag.schema.runtime_dynamic,
        },
    }


def tag_provenance_to_json_value(provenance: TagProvenance) -> JsonObject:
    payload: JsonObject = {
        "group": provenance.group,
        "table_name": provenance.table_name,
        "tag_id": provenance.tag_id,
        "source": provenance.source,
    }
    if provenance.family_0_group is not None:
        payload["family_0_group"] = provenance.family_0_group
    if provenance.family_1_group is not None:
        payload["family_1_group"] = provenance.family_1_group
    if provenance.family_2_group is not None:
        payload["family_2_group"] = provenance.family_2_group
    if provenance.family_3_group is not None:
        payload["family_3_group"] = provenance.family_3_group
    if provenance.family_4_instance_group is not None:
        payload["family_4_instance_group"] = provenance.family_4_instance_group
    if provenance.duplicate_instance_ordinal is not None:
        payload["duplicate_instance_ordinal"] = provenance.duplicate_instance_ordinal
    return payload


def tag_value_to_json_value(value: TagValue) -> JsonValue:
    if _is_binary_tag_list_value_like(value):
        return {
            "type": "binary_list",
            "byte_count": value.byte_count,
            "item_count": value.item_count,
            "items": [binary_tag_value_like_to_json_value(item) for item in value.items],
        }
    if _is_binary_tag_value_like(value):
        return {
            "type": "binary",
            "byte_count": value.byte_count,
            "base64": b64encode(value.data).decode("ascii"),
            "media_type": value.media_type,
            "file_extension": value.file_extension,
        }
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def binary_tag_value_like_to_json_value(value: _BinaryTagValueLike) -> JsonObject:
    return {
        "type": "binary",
        "byte_count": value.byte_count,
        "base64": b64encode(value.data).decode("ascii"),
        "media_type": value.media_type,
        "file_extension": value.file_extension,
    }


def _is_binary_tag_list_value_like(value: TagValue) -> TypeGuard[_BinaryTagListValueLike]:
    items = getattr(value, "items", None)
    byte_count = getattr(value, "byte_count", None)
    item_count = getattr(value, "item_count", None)
    return (
        isinstance(items, tuple)
        and all(_is_binary_tag_value_like(item) for item in items)
        and isinstance(byte_count, int)
        and isinstance(item_count, int)
    )


def _is_binary_tag_value_like(value: TagValue) -> TypeGuard[_BinaryTagValueLike]:
    data = getattr(value, "data", None)
    media_type = getattr(value, "media_type", None)
    file_extension = getattr(value, "file_extension", None)
    byte_count = getattr(value, "byte_count", None)
    return (
        isinstance(data, bytes)
        and (media_type is None or isinstance(media_type, str))
        and (file_extension is None or isinstance(file_extension, str))
        and isinstance(byte_count, int)
    )
