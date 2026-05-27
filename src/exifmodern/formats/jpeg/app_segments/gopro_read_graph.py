"""JPEG APP6 GoPro payload adapter for read-graph tag emission."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from exifmodern.formats.jpeg.container import scan_jpeg_segments
from exifmodern.json_types import JsonValue
from exifmodern.read_graph import (
    BinaryTagValue,
    ReadGraphRuntimeOptions,
    ReadTag,
    ReadTagSchema,
    ScalarTagValue,
    TagProvenance,
    TagValue,
    schema_tag_key,
)

type GoProDecodedValue = (
    JsonValue
    | bytes
    | tuple[ScalarTagValue | bytes, ...]
    | tuple[tuple[ScalarTagValue | bytes, ...], ...]
)
type SchemaProvenanceMap = dict[str, ReadTagSchema]


class _RefLike(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def line_start(self) -> int: ...

    @property
    def line_end(self) -> int: ...

    @property
    def symbol(self) -> str: ...


def add_optional_gopro_app6_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    data: bytes,
    schema_map: SchemaProvenanceMap,
    runtime_options: ReadGraphRuntimeOptions,
) -> None:
    for segment in scan_jpeg_segments(data):
        if segment.marker != 0xE6:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(b"GoPro\0"):
            continue
        from exifmodern.formats.gopro.reader import read_gopro_gpmf_scalars

        result = read_gopro_gpmf_scalars(
            payload[6:],
            include_request_all_hidden=runtime_options.requests_request_all_hidden_tags,
        )
        for blocker in result.blockers:
            diagnostics.append(f"GoPro APP6 GPMF blocker {blocker.code}: {blocker.reason}")
        for tag in result.tags:
            if tag.name in {"DeviceID", "TotalSamples"}:
                continue
            value = _gopro_tag_value(tag.name, tag.value)
            if value is None:
                continue
            tags.append(
                ReadTag(
                    name=tag.name,
                    value=value,
                    provenance=_gopro_provenance(
                        "APP6",
                        tag.group2,
                        tag.source_table,
                        tag.tag_id,
                        tag.evidence_anchors,
                    ),
                    schema=schema_map.get(schema_tag_key("APP6", tag.name)),
                )
            )


def _gopro_provenance(
    group: str,
    family_2_group: str,
    table_name: str,
    tag_id: str,
    refs: tuple[_RefLike, ...],
) -> TagProvenance:
    return TagProvenance(
        group=group,
        table_name=table_name,
        tag_id=tag_id,
        source=_refs_text(refs),
        family_0_group=group,
        family_1_group="GoPro",
        family_2_group=family_2_group,
    )


def _refs_text(refs: tuple[_RefLike, ...]) -> str:
    if not refs:
        return "source-backed-manufacturer-jpeg-payload"
    return "; ".join(_ref_text(reference) for reference in refs)


def _ref_text(reference: _RefLike) -> str:
    return f"{reference.path}:{reference.line_start}-{reference.line_end}:{reference.symbol}"


def _gopro_tag_value(name: str, value: GoProDecodedValue) -> TagValue:
    if name == "MediaUniqueID" and isinstance(value, tuple):
        parts: list[str] = []
        for item in value:
            if not isinstance(item, int):
                return _manufacturer_tag_value(value)
            parts.append(f"{item:08x}")
        return "".join(parts)
    if isinstance(value, str):
        if name == "DigitalZoomOn":
            return {"Y": "Yes", "N": "No"}.get(value, value)
        if name == "SpotMeter":
            return {"Y": "Yes", "N": "No"}.get(value, value)
        if name == "Protune":
            return {"Y": "On", "N": "Off"}.get(value, value)
        if name == "AutoRotation":
            return {"U": "Up", "D": "Down"}.get(value, value)
    return _manufacturer_tag_value(value)


def _manufacturer_tag_value(value: GoProDecodedValue) -> TagValue:
    if isinstance(value, bytes):
        return BinaryTagValue(value)
    if isinstance(value, tuple):
        if all(isinstance(item, bytes) for item in value):
            return " ".join(item.hex() for item in value if isinstance(item, bytes))
        scalar_values: list[ScalarTagValue] = []
        for item in value:
            if isinstance(item, tuple):
                return str(value)
            if isinstance(item, bytes):
                return BinaryTagValue(item)
            scalar_values.append(item)
        return scalar_values
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        list_values: list[ScalarTagValue] = []
        for list_item in value:
            if isinstance(list_item, str | int | float | bool) or list_item is None:
                list_values.append(list_item)
            else:
                return str(value)
        return list_values
    return str(value)
