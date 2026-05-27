"""FLIF adapter for the shared read graph contract."""

from __future__ import annotations

import time
from pathlib import Path
from typing import BinaryIO

from exifmodern.dispatch_helpers import EvidenceAnchors, _source_text
from exifmodern.formats.flif.image_transaction_plan import (
    FLIF_MAP_SOURCE,
    FLIF_PROCESS_LOOP_SOURCE,
    FLIF_TAG_TABLE_SOURCE,
    FlifImageTransactionPlan,
    FlifMetadataChunkPlan,
    build_flif_image_transaction_plan,
    inflate_raw_deflate,
)
from exifmodern.formats.icc.reader import parse_icc_header_tags, parse_icc_profile_tags
from exifmodern.formats.tiff.primitives import inspect_ifd0
from exifmodern.formats.xmp.reader import parse_xmp_packet
from exifmodern.json_types import JsonArray, JsonValue, json_string_array_or_none
from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance, TagValue

FLIF_MAGIC_EVIDENCE_TEXT = "lib/Image/ExifTool.pm:964:%magicNumber FLIF"


def build_flif_read_graph_from_file(path: Path, *, source_file: str) -> ReadGraph:
    return build_flif_read_graph(_read_flif_exiftool_chunks(path), source_file=source_file)


def _read_flif_exiftool_chunks(path: Path) -> bytes:
    with path.open("rb") as file:
        data = bytearray(file.read(6))
        if len(data) < 6:
            return bytes(data)
        while True:
            byte = file.read(1)
            if not byte:
                return bytes(data)
            data.extend(byte)
            if byte[0] < 0x80:
                break
        while True:
            byte = file.read(1)
            if not byte:
                return bytes(data)
            data.extend(byte)
            if byte[0] < 0x80:
                break
        if data[4] > ord("H"):
            while True:
                byte = file.read(1)
                if not byte:
                    return bytes(data)
                data.extend(byte)
                if byte[0] < 0x80:
                    break
        for _ in range(4096):
            tag = file.read(4)
            if len(tag) != 4:
                break
            data.extend(tag)
            if tag[0] < 32:
                break
            size_bytes = _read_flif_varint_bytes(file)
            size = _flif_varint_value(size_bytes)
            data.extend(size_bytes)
            if size is None:
                break
            if tag in {b"eXif", b"eXmp", b"iCCP"}:
                data.extend(file.read(size))
            else:
                file.seek(size, 1)
        return bytes(data)


def _read_flif_varint_bytes(file: BinaryIO) -> bytes:
    data = bytearray()
    while True:
        byte = file.read(1)
        if not byte:
            return bytes(data)
        data.extend(byte)
        if byte[0] < 0x80:
            return bytes(data)


def _flif_varint_value(data: bytes) -> int | None:
    value = 0
    shift = 0
    for byte in data:
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value
        shift += 7
    return None


def build_flif_read_graph(data: bytes, *, source_file: str) -> ReadGraph:
    plan = build_flif_image_transaction_plan(data, allow_output_emission=True)
    diagnostics = [
        f"FLIF package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    tags: list[ReadTag] = []
    if plan.status == "planned":
        tags.extend(_file_type_tags())
        tags.extend(_header_tags(plan))
        nested_tags = _nested_metadata_tags(plan, data, diagnostics)
        tags.extend(_file_group_nested_tags(nested_tags))
        tags.extend(_encoding_tags(plan))
        tags.extend(_non_file_group_nested_tags(nested_tags))
        tags.extend(_composite_tags(tags))
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=int(time.time()),
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )


def _file_type_tags() -> list[ReadTag]:
    return [
        _tag("FileType", "FLIF", "FileType", "File", "Image::ExifTool::File", ()),
        _tag(
            "FileTypeExtension",
            "flif",
            "FileTypeExtension",
            "File",
            "Image::ExifTool::File",
            (),
        ),
        _tag("MIMEType", "image/flif", "MIMEType", "File", "Image::ExifTool::File", ()),
    ]


def _header_tags(plan: FlifImageTransactionPlan) -> list[ReadTag]:
    header = plan.header
    values: tuple[tuple[str, TagValue, str], ...] = (
        ("ImageType", header.image_type_description, "0"),
        ("BitDepth", "Custom" if header.is_custom_bit_depth else header.bit_depth, "1"),
        ("ImageWidth", header.image_width, "2"),
        ("ImageHeight", header.image_height, "3"),
        ("AnimationFrames", header.animation_frames, "4"),
    )
    return [
        _tag(
            name,
            value,
            tag_id,
            "File",
            "Image::ExifTool::FLIF::Main",
            (FLIF_TAG_TABLE_SOURCE, FLIF_PROCESS_LOOP_SOURCE),
        )
        for name, value, tag_id in values
        if value is not None
    ]


def _encoding_tags(plan: FlifImageTransactionPlan) -> list[ReadTag]:
    if plan.image_stream.encoding_name is None:
        return []
    return [
        _tag(
            "Encoding",
            plan.image_stream.encoding_name,
            "5",
            "File",
            "Image::ExifTool::FLIF::Main",
            (FLIF_TAG_TABLE_SOURCE, FLIF_PROCESS_LOOP_SOURCE),
        )
    ]


def _file_group_nested_tags(tags: list[ReadTag]) -> list[ReadTag]:
    return [tag for tag in tags if tag.provenance.group == "File"]


def _non_file_group_nested_tags(tags: list[ReadTag]) -> list[ReadTag]:
    return [tag for tag in tags if tag.provenance.group != "File"]


def _nested_metadata_tags(
    plan: FlifImageTransactionPlan,
    data: bytes,
    diagnostics: list[str],
) -> list[ReadTag]:
    tags: list[ReadTag] = []
    for chunk in plan.metadata_chunks:
        if chunk.metadata_kind is None:
            continue
        inflated = _inflated_payload(data, chunk)
        if inflated is None:
            diagnostics.append(
                "FLIF package-local reader diagnostic: nested_metadata_unsupported_payload: "
                f"{chunk.metadata_kind}; chunk_index={chunk.index}; reason=raw_inflate_failed"
            )
            continue
        nested_tags = _extract_nested_metadata_tags(chunk, inflated)
        tags.extend(nested_tags)
        diagnostics.append(
            "FLIF package-local reader diagnostic: nested_metadata_extracted: "
            f"{chunk.metadata_kind}; chunk_index={chunk.index}; tag_count={len(nested_tags)}"
        )
    return tags


def _inflated_payload(data: bytes, chunk: FlifMetadataChunkPlan) -> bytes | None:
    if chunk.payload_offset is None or chunk.compressed_size is None:
        return None
    payload = data[chunk.payload_offset : chunk.payload_offset + chunk.compressed_size]
    return inflate_raw_deflate(payload)


def _extract_nested_metadata_tags(
    chunk: FlifMetadataChunkPlan,
    payload: bytes,
) -> list[ReadTag]:
    if chunk.metadata_kind == "EXIF":
        return _exif_tags(chunk, payload)
    if chunk.metadata_kind == "XMP":
        return _xmp_tags(chunk, payload)
    if chunk.metadata_kind == "ICC_Profile":
        return _icc_tags(chunk, payload)
    return []


def _exif_tags(chunk: FlifMetadataChunkPlan, payload: bytes) -> list[ReadTag]:
    tiff_payload = payload[6:] if payload.startswith(b"Exif\x00\x00") else payload
    try:
        inspection = inspect_ifd0(tiff_payload)
    except ValueError:
        return []
    tags = [
        _nested_tag(
            "ExifByteOrder",
            _string_value(inspection.get("byte_order")),
            "File",
            "Image::ExifTool::Exif::Main",
            "ExifByteOrder",
            chunk,
        )
    ]
    for group, values_key in (
        ("IFD0", "ifd0_values"),
        ("ExifIFD", "exif_ifd_values"),
        ("GPS", "gps_ifd_values"),
        ("IFD1", "ifd1_values"),
    ):
        values = inspection.get(values_key)
        if not isinstance(values, dict):
            continue
        for name, value in values.items():
            if name in {"ExifIFDPointer", "GPSInfoIFDPointer"}:
                continue
            tag_value = _json_tag_value(value)
            if tag_value is None:
                continue
            tags.append(
                _nested_tag(
                    name,
                    tag_value,
                    group,
                    _exif_table_name(group),
                    name,
                    chunk,
                )
            )
    return tags


def _xmp_tags(chunk: FlifMetadataChunkPlan, payload: bytes) -> list[ReadTag]:
    try:
        values_by_group = parse_xmp_packet(payload)
    except ValueError, SyntaxError:
        return []
    tags: list[ReadTag] = []
    for group, values in values_by_group.items():
        for name, value in values.items():
            if group == "XMP-rdf" and name == "About":
                continue
            tag_value = _json_tag_value(value)
            if tag_value is None:
                continue
            tags.append(
                _nested_tag(
                    name,
                    tag_value,
                    group,
                    _xmp_table_name(group),
                    name,
                    chunk,
                )
            )
    return tags


def _icc_tags(chunk: FlifMetadataChunkPlan, payload: bytes) -> list[ReadTag]:
    try:
        values = {**parse_icc_header_tags(payload), **parse_icc_profile_tags(payload)}
    except ValueError:
        return []
    tags: list[ReadTag] = []
    for name, value in values.items():
        tag_value = _json_tag_value(value)
        if tag_value is None:
            continue
        tags.append(
            _nested_tag(
                name,
                tag_value,
                _icc_group_name(name),
                _icc_table_name(name),
                name,
                chunk,
            )
        )
    return tags


def _composite_tags(tags: list[ReadTag]) -> list[ReadTag]:
    width = _numeric_tag_value(tags, "File", "ImageWidth")
    height = _numeric_tag_value(tags, "File", "ImageHeight")
    if width is None or height is None:
        return []
    pixels = width * height / 1_000_000
    return [
        _tag(
            "ImageSize",
            f"{int(width)}x{int(height)}",
            "Exif-ImageSize",
            "Composite",
            "Image::ExifTool::Exif::Composite",
            (FLIF_TAG_TABLE_SOURCE,),
        ),
        _tag(
            "Megapixels",
            round(pixels, 1 if pixels >= 1 else 6),
            "Exif-Megapixels",
            "Composite",
            "Image::ExifTool::Exif::Composite",
            (FLIF_TAG_TABLE_SOURCE,),
        ),
    ]


def _nested_tag(
    name: str,
    value: TagValue,
    group: str,
    table_name: str,
    tag_id: str,
    chunk: FlifMetadataChunkPlan,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group=group,
            table_name=table_name,
            tag_id=tag_id,
            source=_source_text((FLIF_MAP_SOURCE, FLIF_PROCESS_LOOP_SOURCE)),
            family_0_group=_nested_family_0_group(group, table_name),
            family_1_group=group,
            family_2_group=_nested_family_2_group(group, table_name, name),
            duplicate_instance_ordinal=chunk.index + 1,
        ),
        schema=None,
    )


def _json_tag_value(value: JsonValue) -> TagValue | None:
    if isinstance(value, dict):
        return None
    if isinstance(value, list):
        return _json_string_list_or_none(value)
    return value


def _json_string_list_or_none(value: JsonArray) -> list[str] | None:
    return json_string_array_or_none(value)


def _string_value(value: JsonValue | None) -> str:
    return value if isinstance(value, str) else ""


def _exif_table_name(group: str) -> str:
    if group == "ExifIFD":
        return "Image::ExifTool::Exif::ExifIFD"
    if group == "GPS":
        return "Image::ExifTool::GPS::Main"
    return "Image::ExifTool::Exif::Main"


def _xmp_table_name(group: str) -> str:
    if group.startswith("XMP-"):
        return f"Image::ExifTool::XMP::{group[4:]}"
    return "Image::ExifTool::XMP::Main"


def _icc_table_name(name: str) -> str:
    if name in {
        "ProfileCopyright",
        "ProfileDescription",
        "MediaWhitePoint",
        "MediaBlackPoint",
        "RedTRC",
        "GreenTRC",
        "BlueTRC",
        "RedMatrixColumn",
        "GreenMatrixColumn",
        "BlueMatrixColumn",
    }:
        return "Image::ExifTool::ICC_Profile::Main"
    return "Image::ExifTool::ICC_Profile::Header"


def _icc_group_name(name: str) -> str:
    if _icc_table_name(name) == "Image::ExifTool::ICC_Profile::Header":
        return "ICC-header"
    return "ICC_Profile"


def _nested_family_0_group(group: str, table_name: str) -> str:
    if table_name.startswith("Image::ExifTool::XMP::"):
        return "XMP"
    if table_name.startswith("Image::ExifTool::Exif::") or table_name.startswith(
        "Image::ExifTool::GPS::"
    ):
        return "File" if group == "File" else "EXIF"
    return group


def _nested_family_2_group(group: str, table_name: str, name: str) -> str:
    if table_name.startswith("Image::ExifTool::XMP::"):
        if group == "XMP-x":
            return "Document"
        if group == "XMP-dc" and name in {"Creator", "Rights"}:
            return "Author"
        return "Image"
    if table_name.startswith("Image::ExifTool::Exif::") or table_name.startswith(
        "Image::ExifTool::GPS::"
    ):
        if name in {"Artist", "Copyright"}:
            return "Author"
        if name in {"CreateDate", "DateTimeOriginal", "ModifyDate", "GPSDateTime"}:
            return "Time"
        if name in {"GPSAltitude", "GPSLatitude", "GPSLongitude"}:
            return "Location"
    if group == "Composite":
        return "Image"
    return "Image" if group != "File" else "Other"


def _numeric_tag_value(tags: list[ReadTag], group: str, name: str) -> float | None:
    for tag in tags:
        if tag.provenance.group != group or tag.name != name:
            continue
        value = tag.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)
    return None


def _tag(
    name: str,
    value: TagValue,
    tag_id: str,
    group: str,
    table_name: str,
    references: EvidenceAnchors,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group=group,
            table_name=table_name,
            tag_id=tag_id,
            source=_source_text(references) if references else FLIF_MAGIC_EVIDENCE_TEXT,
            family_0_group=group,
            family_1_group=group,
            family_2_group="Image" if table_name == "Image::ExifTool::FLIF::Main" else "Other",
        ),
        schema=None,
    )
