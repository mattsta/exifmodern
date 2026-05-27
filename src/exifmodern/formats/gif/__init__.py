"""GIF container planning helpers."""

from pathlib import Path
from typing import BinaryIO

from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
from exifmodern.formats.gif.extension_transaction_plan import (
    GIF_APPLICATION_SOURCE,
    GIF_APPLICATION_TABLE_SOURCE,
    GIF_EXTENSION_TRANSACTION_SOURCES,
    GIF_ICC_APPLICATION_IDENTIFIER,
    GIF_XMP_APPLICATION_IDENTIFIER,
    GIF_XMP_LANDING_ZONE,
    GifApplicationExtensionRequest,
    GifExtensionBlockPlan,
    GifExtensionTransactionPlan,
    GifReadTagRecord,
    build_gif_extension_transaction_plan,
    encode_gif_application_extension,
    encode_gif_comment_extension,
    encode_gif_xmp_application_extension,
    plan_gif_extension_transaction,
    resolve_gif_evidence,
)
from exifmodern.formats.icc.reader import parse_icc_header_tags, parse_icc_profile_tags
from exifmodern.formats.xmp.reader import parse_xmp_packet
from exifmodern.json_types import JsonArray, JsonValue
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "GIF_EXTENSION_TRANSACTION_SOURCES",
    "GIF_ICC_APPLICATION_IDENTIFIER",
    "GIF_XMP_APPLICATION_IDENTIFIER",
    "GifApplicationExtensionRequest",
    "GifExtensionTransactionPlan",
    "GifReadTagRecord",
    "build_gif_extension_transaction_plan",
    "build_gif_read_graph",
    "encode_gif_application_extension",
    "encode_gif_comment_extension",
    "encode_gif_xmp_application_extension",
    "invoke_gif",
    "plan_gif_extension_transaction",
]


type GifNestedTagValue = str | int | float | bool | None | list[str]


def build_gif_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Build a GIF read graph with source-backed nested application metadata."""

    plan = build_gif_extension_transaction_plan(data)
    diagnostics = [
        *(
            f"GIF package-local reader gate: {gate.code}: {gate.reason}"
            for gate in plan.output_emission_gates
        ),
        *(
            f"GIF package-local reader diagnostic: {diagnostic.code}: {diagnostic.detail}"
            for diagnostic in plan.read_diagnostics
        ),
    ]
    tags: list[ReadTag] = []
    if plan.status == "planned":
        tags.extend(_gif_file_type_tags())

    comments = tuple(tag for tag in plan.read_tags if tag.name == "Comment")
    scalar_tags = tuple(tag for tag in plan.read_tags if tag.name != "Comment")
    tags.extend(_gif_read_tags(comments))
    tags.extend(_gif_read_tags(scalar_tags))
    nested_tags, nested_diagnostics = _gif_nested_application_tags(plan, data)
    tags.extend(nested_tags)
    diagnostics.extend(nested_diagnostics)
    tags.extend(_gif_composite_tags(tags))
    return _graph(source_file, tags, diagnostics)


def _gif_file_type_tags() -> list[ReadTag]:
    return [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id=name,
                references=(),
            ),
            schema=None,
        )
        for name, value in (
            ("FileType", "GIF"),
            ("FileTypeExtension", "gif"),
            ("MIMEType", "image/gif"),
        )
    ]


def _gif_read_tags(records: tuple[GifReadTagRecord, ...]) -> list[ReadTag]:
    return [
        ReadTag(
            name=record.name,
            value=_read_value(_gif_public_value(record)),
            provenance=_provenance(
                group="File" if record.name == "Comment" else record.group,
                table_name=_gif_table_name(record),
                tag_id=record.name,
                references=resolve_gif_evidence(record.evidence_ids),
            ),
            schema=None,
        )
        for record in records
    ]


def _gif_public_value(record: GifReadTagRecord) -> str | int | float:
    if record.name in {"HasColorMap", "ChannelUsage", "DelayTime", "Duration"}:
        return record.rendered_value
    raw_value = record.raw_value
    if isinstance(raw_value, float) and raw_value.is_integer():
        return int(raw_value)
    return raw_value


def _gif_table_name(record: GifReadTagRecord) -> str:
    for reference in resolve_gif_evidence(record.evidence_ids):
        if reference.symbol.startswith("%Image::ExifTool::GIF::MIDIControl"):
            return "Image::ExifTool::GIF::MIDIControl"
        if reference.symbol.startswith("%Image::ExifTool::GIF::Extensions"):
            return "Image::ExifTool::GIF::Extensions"
    return "Image::ExifTool::GIF::Main"


def _gif_nested_application_tags(
    plan: GifExtensionTransactionPlan,
    data: bytes,
) -> tuple[list[ReadTag], list[str]]:
    tags: list[ReadTag] = []
    diagnostics: list[str] = []
    for extension in plan.extensions:
        if extension.application_identifier == GIF_XMP_APPLICATION_IDENTIFIER:
            payload = _gif_extension_length_prefixed_payload(extension, data)
            packet = _gif_xmp_packet(payload)
            if packet is None:
                diagnostics.append(
                    "GIF package-local reader diagnostic: gif_xmp_packet_unbounded: "
                    "XMP Data/XMP application payload did not contain a bounded XMP packet."
                )
                continue
            tags.extend(_gif_nested_xmp_tags(packet, extension.index))
            continue
        if extension.application_identifier == GIF_ICC_APPLICATION_IDENTIFIER:
            payload = _gif_extension_payload(extension, data)
            tags.extend(_gif_nested_icc_tags(payload, extension.index))
    return tags, diagnostics


def _gif_extension_payload(extension: GifExtensionBlockPlan, data: bytes) -> bytes:
    chunks = bytearray()
    for sub_block in extension.sub_blocks:
        chunks.extend(
            data[sub_block.payload_offset : sub_block.payload_offset + sub_block.payload_length]
        )
    return bytes(chunks)


def _gif_extension_length_prefixed_payload(
    extension: GifExtensionBlockPlan,
    data: bytes,
) -> bytes:
    chunks = bytearray()
    for sub_block in extension.sub_blocks:
        payload = data[
            sub_block.payload_offset : sub_block.payload_offset + sub_block.payload_length
        ]
        chunks.extend(bytes((sub_block.payload_length,)) + payload)
    return bytes(chunks)


def _gif_xmp_packet(payload: bytes) -> bytes | None:
    if GIF_XMP_LANDING_ZONE in payload:
        payload = payload.split(GIF_XMP_LANDING_ZONE, 1)[0]
    start = payload.find(b"<?xpacket")
    if start < 0:
        start = payload.find(b"<x:xmpmeta")
    if start < 0:
        return None
    payload = payload[start:]
    end_marker = b"<?xpacket end="
    end_start = payload.find(end_marker)
    if end_start >= 0:
        end = payload.find(b"?>", end_start)
        if end >= 0:
            return payload[: end + 2]
    xmp_end = payload.find(b"</x:xmpmeta>")
    if xmp_end >= 0:
        return payload[: xmp_end + len(b"</x:xmpmeta>")]
    return payload.rstrip(b"\x00")


def _gif_nested_xmp_tags(packet: bytes, ordinal: int) -> list[ReadTag]:
    try:
        values_by_group = parse_xmp_packet(packet)
    except ValueError, SyntaxError:
        return []
    tags: list[ReadTag] = []
    for group, values in values_by_group.items():
        for name, value in values.items():
            if group == "XMP-rdf" and name == "About":
                continue
            tag_value = _gif_nested_json_value(value)
            if tag_value is None and value is not None:
                continue
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(tag_value),
                    provenance=_provenance(
                        group=group,
                        table_name=_gif_xmp_table_name(group),
                        tag_id=name,
                        references=resolve_gif_evidence(
                            (GIF_APPLICATION_TABLE_SOURCE, GIF_APPLICATION_SOURCE)
                        ),
                        duplicate_instance_ordinal=ordinal,
                    ),
                    schema=None,
                )
            )
    return tags


def _gif_nested_icc_tags(payload: bytes, ordinal: int) -> list[ReadTag]:
    try:
        values = {**parse_icc_header_tags(payload), **parse_icc_profile_tags(payload)}
    except ValueError:
        return []
    tags: list[ReadTag] = []
    for name, value in values.items():
        tag_value = _gif_nested_json_value(value)
        if tag_value is None and value is not None:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(tag_value),
                provenance=_provenance(
                    group=_gif_icc_group_name(name),
                    table_name=_gif_icc_table_name(name),
                    tag_id=name,
                    references=resolve_gif_evidence(
                        (GIF_APPLICATION_TABLE_SOURCE, GIF_APPLICATION_SOURCE)
                    ),
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    return tags


def _gif_nested_json_value(value: JsonValue) -> GifNestedTagValue | None:
    if isinstance(value, dict):
        return None
    if isinstance(value, list):
        return _gif_json_string_array_or_none(value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return None


def _gif_json_string_array_or_none(value: JsonArray) -> list[str] | None:
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        strings.append(item)
    return strings


def _gif_icc_table_name(name: str) -> str:
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


def _gif_icc_group_name(name: str) -> str:
    if _gif_icc_table_name(name) == "Image::ExifTool::ICC_Profile::Header":
        return "ICC-header"
    return "ICC_Profile"


def _gif_xmp_table_name(group: str) -> str:
    if group.startswith("XMP-"):
        return f"Image::ExifTool::XMP::{group[4:]}"
    return "Image::ExifTool::XMP::Main"


def _gif_composite_tags(tags: list[ReadTag]) -> list[ReadTag]:
    width = _gif_numeric_tag_value(tags, "ImageWidth")
    height = _gif_numeric_tag_value(tags, "ImageHeight")
    if width is None or height is None:
        return []
    megapixels = round(width * height / 1_000_000, 1 if width * height >= 1_000_000 else 6)
    return [
        ReadTag(
            name="ImageSize",
            value=_read_value(f"{int(width)}x{int(height)}"),
            provenance=_provenance(
                group="Composite",
                table_name="Image::ExifTool::Exif::Composite",
                tag_id="Exif-ImageSize",
                references=resolve_gif_evidence(GIF_EXTENSION_TRANSACTION_SOURCES),
            ),
            schema=None,
        ),
        ReadTag(
            name="Megapixels",
            value=_read_value(megapixels),
            provenance=_provenance(
                group="Composite",
                table_name="Image::ExifTool::Exif::Composite",
                tag_id="Exif-Megapixels",
                references=resolve_gif_evidence(GIF_EXTENSION_TRANSACTION_SOURCES),
            ),
            schema=None,
        ),
    ]


def _gif_numeric_tag_value(tags: list[ReadTag], name: str) -> float | None:
    for tag in tags:
        if tag.name != name:
            continue
        value = tag.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)
    return None


def invoke_gif(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_gif_exiftool_blocks(path)
    return build_gif_read_graph(data, source_file)


def _read_gif_exiftool_blocks(path: Path) -> bytes:
    with path.open("rb") as file:
        data = bytearray(file.read(13))
        if len(data) < 13:
            return bytes(data)
        packed = data[10]
        if packed & 0x80:
            data.extend(file.read(3 * (2 << (packed & 0x07))))
        for _ in range(8192):
            marker = file.read(1)
            if not marker:
                break
            data.extend(marker)
            if marker == b"\x3b":
                break
            if marker == b"\x21":
                label = file.read(1)
                if not label:
                    break
                data.extend(label)
                if label == b"\xff":
                    data.extend(file.read(12))
                    _append_gif_sub_blocks(file, data)
                elif label == b"\xf9":
                    block_size = file.read(1)
                    data.extend(block_size)
                    if block_size:
                        data.extend(file.read(block_size[0] + 1))
                else:
                    block_size = file.read(1)
                    data.extend(block_size)
                    if block_size:
                        data.extend(file.read(block_size[0]))
                    _append_gif_sub_blocks(file, data)
                continue
            if marker == b"\x2c":
                descriptor = file.read(9)
                data.extend(descriptor)
                if len(descriptor) == 9 and descriptor[8] & 0x80:
                    data.extend(file.read(3 * (2 << (descriptor[8] & 0x07))))
                code_size = file.read(1)
                data.extend(code_size)
                _append_gif_sub_blocks(file, data)
                continue
            break
        return bytes(data)


def _append_gif_sub_blocks(file: BinaryIO, data: bytearray) -> None:
    for _ in range(1_000_000):
        size = file.read(1)
        if not size:
            return
        data.extend(size)
        if size == b"\0":
            return
        data.extend(file.read(size[0]))


def _skip_gif_sub_blocks(file: BinaryIO) -> None:
    for _ in range(1_000_000):
        size = file.read(1)
        if not size or size == b"\0":
            return
        file.seek(size[0], 1)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="gif/87a",
        builder_ref="exifmodern.formats.gif:invoke_gif",
        patterns=(Pattern(0, b"GIF87a"),),
    ),
    Signature(
        format_id="gif/89a",
        builder_ref="exifmodern.formats.gif:invoke_gif",
        patterns=(Pattern(0, b"GIF89a"),),
    ),
)
