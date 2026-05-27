"""Google JPEG APP1 XMP payload adapter for read-graph tag emission."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree

from exifmodern.formats.jpeg.app_segments.xmp import (
    XMP_APP1_PREFIX,
    XMP_EXTENDED_APP1_PREFIX,
)
from exifmodern.formats.jpeg.container import scan_jpeg_segments
from exifmodern.formats.xmp.reader import parse_xmp_packet
from exifmodern.json_types import JsonValue
from exifmodern.read_graph import (
    BinaryTagValue,
    ReadTag,
    ReadTagSchema,
    ScalarTagArray,
    ScalarTagValue,
    TagProvenance,
    TagValue,
    schema_tag_key,
)

type SchemaProvenanceMap = dict[str, ReadTagSchema]
_GOOGLE_XMP_PACKET_NEEDLES = (
    b":GCamera",
    b":GContainer",
    b":GDepth",
    b":GDevice",
    b":GFocus",
    b":GImage",
    b":GItem",
    b":GPano",
    b":GSpherical",
    b"HDRPlusMakerNote",
    b"http://ns.google.com/photos/1.0/",
)


class _RefLike(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def line_start(self) -> int: ...

    @property
    def line_end(self) -> int: ...

    @property
    def symbol(self) -> str: ...


def add_optional_google_xmp_payload_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    data: bytes,
    schema_map: SchemaProvenanceMap,
) -> None:
    packets: list[bytes] = []
    extended_chunks: dict[str, list[tuple[int, bytes]]] = {}
    for segment in scan_jpeg_segments(data):
        if segment.marker != 0xE1:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if payload.startswith(XMP_APP1_PREFIX):
            packets.append(payload[len(XMP_APP1_PREFIX) :])
            continue
        if not payload.startswith(XMP_EXTENDED_APP1_PREFIX):
            continue
        chunk = payload[len(XMP_EXTENDED_APP1_PREFIX) :]
        if len(chunk) < 40:
            diagnostics.append(f"Google extended XMP APP1 chunk is truncated: {path}")
            continue
        guid = chunk[:32].decode("ascii", errors="replace")
        full_length = int.from_bytes(chunk[32:36], "big")
        offset = int.from_bytes(chunk[36:40], "big")
        chunk_payload = chunk[40:]
        if offset + len(chunk_payload) > full_length:
            diagnostics.append(f"Google extended XMP APP1 chunk exceeds declared length: {path}")
            continue
        extended_chunks.setdefault(guid, []).append((offset, chunk_payload))
    for guid, chunks in extended_chunks.items():
        packets.append(_reassemble_google_extended_xmp(guid, chunks))
    add_google_xmp_extended_indicator_tags(tags, packets, schema_map)
    if not packets:
        remove_google_only_xmp_internal_tags(tags)
        return
    if not _packets_may_contain_google_metadata(packets):
        remove_google_only_xmp_internal_tags(tags)
        return
    from exifmodern.formats.google.reader import read_google_metadata_scalars

    for packet in packets:
        result = read_google_metadata_scalars(packet)
        for blocker in result.blockers:
            diagnostics.append(f"Google XMP payload blocker {blocker.code}: {blocker.reason}")
        for tag in result.tags:
            value = _google_tag_value(tag.name, tag.value)
            if value is None:
                continue
            group, family_1_group, tag_name = _google_xmp_output_identity(
                tag.source_table.removeprefix("Image::ExifTool::Google::"),
                tag.name,
            )
            _append_or_merge_google_xmp_tag(
                tags,
                ReadTag(
                    name=tag_name,
                    value=value,
                    provenance=_manufacturer_provenance(
                        group,
                        family_1_group,
                        tag.group2,
                        tag.source_table,
                        tag.tag_id,
                        tag.evidence_anchors,
                    ),
                    schema=schema_map.get(schema_tag_key(group, tag_name)),
                ),
            )
    remove_google_only_xmp_internal_tags(tags)


def _packets_may_contain_google_metadata(packets: list[bytes]) -> bool:
    return any(needle in packet for packet in packets for needle in _GOOGLE_XMP_PACKET_NEEDLES)


def _reassemble_google_extended_xmp(guid: str, chunks: list[tuple[int, bytes]]) -> bytes:
    total_length = max(offset + len(payload) for offset, payload in chunks)
    buffer = bytearray(total_length)
    for offset, payload in chunks:
        buffer[offset : offset + len(payload)] = payload
    return bytes(buffer)


def add_google_xmp_extended_indicator_tags(
    tags: list[ReadTag],
    packets: list[bytes],
    schema_map: SchemaProvenanceMap,
) -> None:
    insertions: list[ReadTag] = []
    for packet in packets:
        try:
            groups = parse_xmp_packet(packet)
        except ElementTree.ParseError:
            continue
        hdrgm_version = groups.get("XMP-hdrgm", {}).get("Version")
        if isinstance(hdrgm_version, str | int | float | bool) or hdrgm_version is None:
            if hdrgm_version is not None and not has_read_tag(tags, "XMP-hdrgm", "Version"):
                insertions.append(
                    ReadTag(
                        name="Version",
                        value=hdrgm_version,
                        provenance=TagProvenance(
                            group="XMP-hdrgm",
                            table_name="Image::ExifTool::XMP::hdrgm",
                            tag_id="Version",
                            source="jpeg.google-xmp.hdrgm-version",
                            family_0_group="XMP",
                            family_1_group="XMP-hdrgm",
                            family_2_group="Image",
                        ),
                        schema=schema_map.get(schema_tag_key("XMP-hdrgm", "Version")),
                    )
                )
        has_extended_xmp = groups.get("XMP-xmpNote", {}).get("HasExtendedXMP")
        if isinstance(has_extended_xmp, str) and not has_read_tag(
            tags, "XMP-xmpNote", "HasExtendedXMP"
        ):
            insertions.append(
                ReadTag(
                    name="HasExtendedXMP",
                    value=has_extended_xmp,
                    provenance=TagProvenance(
                        group="XMP-xmpNote",
                        table_name="Image::ExifTool::XMP::xmpNote",
                        tag_id="HasExtendedXMP",
                        source="jpeg.google-xmp.has-extended-xmp",
                        family_0_group="XMP",
                        family_1_group="XMP-xmpNote",
                        family_2_group="Other",
                    ),
                    schema=schema_map.get(schema_tag_key("XMP-xmpNote", "HasExtendedXMP")),
                )
            )
    if not insertions:
        return
    insert_at = first_google_xmp_payload_index(tags)
    tags[insert_at:insert_at] = insertions


def first_google_xmp_payload_index(tags: list[ReadTag]) -> int:
    for index, tag in enumerate(tags):
        if tag.provenance.family_1_group in {"XMP-GContainer", "XMP-GCamera"}:
            return index
    return len(tags)


def has_read_tag(tags: list[ReadTag], group: str, name: str) -> bool:
    return any(tag.name == name and tag.provenance.group == group for tag in tags)


def remove_google_only_xmp_internal_tags(tags: list[ReadTag]) -> None:
    tags[:] = [
        tag
        for tag in tags
        if not (
            (tag.provenance.group == "XMP-rdf" and tag.name == "About" and tag.value == "")
            or tag.provenance.family_1_group == "payload-boundary"
        )
    ]


def _manufacturer_provenance(
    group: str,
    family_1_group: str,
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
        family_1_group=family_1_group,
        family_2_group=family_2_group,
    )


def _refs_text(refs: tuple[_RefLike, ...]) -> str:
    if not refs:
        return "source-backed-manufacturer-jpeg-payload"
    return "; ".join(_ref_text(reference) for reference in refs)


def _ref_text(reference: _RefLike) -> str:
    return f"{reference.path}:{reference.line_start}-{reference.line_end}:{reference.symbol}"


def _google_tag_value(name: str, value: JsonValue | bytes | int | float | str | bool) -> TagValue:
    if isinstance(value, bytes):
        return BinaryTagValue(value)
    if name in {"HDRPlusMakerNote", "HDRPMakerNote", "ShotLogData"} and isinstance(value, str):
        return BinaryTagValue(value.encode("latin-1"))
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _google_xmp_output_identity(namespace: str, tag_name: str) -> tuple[str, str, str]:
    if namespace == "HDRPlusMakerNote":
        return "Google", "Google", tag_name
    if namespace == "GItem":
        return "XMP-GContainer", "XMP-GContainer", f"DirectoryItem{tag_name}"
    if namespace in {"GCamera", "GContainer"}:
        group = f"XMP-{namespace}"
        return group, group, tag_name
    return namespace, namespace, tag_name


def _append_or_merge_google_xmp_tag(tags: list[ReadTag], tag: ReadTag) -> None:
    if tag.name not in {"DirectoryItemMime", "DirectoryItemSemantic"}:
        tags.append(tag)
        return
    if tag.provenance.family_1_group != "XMP-GContainer":
        tags.append(tag)
        return
    for index, existing in enumerate(tags):
        if existing.name != tag.name:
            continue
        if existing.provenance.family_1_group != tag.provenance.family_1_group:
            continue
        merged_value = _merge_google_directory_item_values(existing.value, tag.value)
        if merged_value is None:
            break
        tags[index] = replace(existing, value=merged_value)
        return
    tags.append(tag)


def _merge_google_directory_item_values(left: TagValue, right: TagValue) -> ScalarTagArray | None:
    left_values = _google_directory_item_scalar_values(left)
    if left_values is None:
        return None
    right_values = _google_directory_item_scalar_values(right)
    if right_values is None:
        return None
    return [*left_values, *right_values]


def _google_directory_item_scalar_values(value: TagValue) -> list[ScalarTagValue] | None:
    if isinstance(value, str | int | float | bool) or value is None:
        return [value]
    if isinstance(value, list):
        scalars: list[ScalarTagValue] = []
        for item in value:
            if isinstance(item, str | int | float | bool) or item is None:
                scalars.append(item)
            else:
                return None
        return scalars
    return None
