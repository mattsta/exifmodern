"""Paint Shop Pro metadata transaction planning public API."""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from exifmodern.formats.psp.metadata_transaction_plan import (
    PspMetadataTransactionPlan,
    PspRewriteRequest,
    build_psp_metadata_transaction_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag

_PSP_PUBLIC_READ_LIMIT = 64 * 1024 * 1024

__all__ = (
    "PspMetadataTransactionPlan",
    "PspRewriteRequest",
    "build_psp_metadata_transaction_plan",
    "build_psp_read_graph",
    "invoke_psp",
)


_PSP_IMAGE_TABLE = "Image::ExifTool::PSP::Main"
_PSP_CREATOR_TABLE = "Image::ExifTool::PSP::Creator"
_PSP_EXIF_TABLE = "Image::ExifTool::Exif::Main"
_PSP_PUBLIC_OUTPUT_SOURCE = "psp.public_output_fixture"

type PspExifScalar = str | int | float
type PspByteOrder = Literal["little", "big"]


def build_psp_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate a PSP metadata transaction plan into a ReadGraph."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_psp_metadata_transaction_plan(data)
    diagnostics = [
        f"PSP package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
        if gate.code != "non_mutating_plan_requires_explicit_emission"
    ]
    if plan.status != "planned":
        diagnostics.insert(0, f"PSP package-local reader status: {plan.status}")

    tags: list[ReadTag] = [
        ReadTag(
            name="FileType",
            value="PSP",
            provenance=_provenance(
                group="File",
                table_name=_PSP_IMAGE_TABLE,
                tag_id="FileType",
                evidence_ids=plan.header_validation.evidence_ids,
            ),
            schema=None,
        ),
        ReadTag(
            name="FileTypeExtension",
            value="psp",
            provenance=_provenance(
                group="File",
                table_name=_PSP_IMAGE_TABLE,
                tag_id="FileTypeExtension",
                evidence_ids=plan.header_validation.evidence_ids,
            ),
            schema=None,
        ),
        ReadTag(
            name="MIMEType",
            value="image/x-paintshoppro",
            provenance=_provenance(
                group="File",
                table_name=_PSP_IMAGE_TABLE,
                tag_id="MIMEType",
                evidence_ids=plan.header_validation.evidence_ids,
            ),
            schema=None,
        ),
    ]
    if plan.header_validation.file_version is not None:
        tags.append(
            ReadTag(
                name="FileVersion",
                value=_read_value(plan.header_validation.file_version),
                provenance=_provenance(
                    group="PSP",
                    table_name=_PSP_IMAGE_TABLE,
                    tag_id="FileVersion",
                    evidence_ids=plan.header_validation.evidence_ids,
                ),
                schema=None,
            )
        )
    image_info = plan.image_info
    image_scalars: tuple[tuple[str, int | float | str | None], ...] = (
        ("ImageWidth", image_info.image_width),
        ("ImageHeight", image_info.image_height),
        ("ImageResolution", image_info.image_resolution),
        ("ResolutionUnit", image_info.resolution_unit_description or image_info.resolution_unit),
        ("Compression", image_info.compression_description or image_info.compression),
        ("BitsPerSample", image_info.bits_per_sample),
        ("Planes", image_info.planes),
        ("NumColors", image_info.num_colors),
    )
    for name, value in image_scalars:
        if value is None:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(_psp_public_value(value)),
                provenance=_provenance(
                    group="PSP",
                    table_name=_PSP_IMAGE_TABLE,
                    tag_id=name,
                    evidence_ids=image_info.evidence_ids,
                ),
                schema=None,
            )
        )

    creator = plan.creator_metadata
    for sub_block in creator.sub_blocks:
        value = _decode_creator_value(data, sub_block.tag_id, sub_block.payload_range)
        if value is None:
            continue
        tags.append(
            ReadTag(
                name=sub_block.name,
                value=_read_value(_psp_public_value(value)),
                provenance=_provenance(
                    group="PSP",
                    table_name=_PSP_CREATOR_TABLE,
                    tag_id=sub_block.name,
                    evidence_ids=sub_block.evidence_ids,
                    duplicate_instance_ordinal=sub_block.index,
                ),
                schema=None,
            )
        )
    tags.extend(_nested_exif_tags(data, plan))
    if image_info.image_width is not None and image_info.image_height is not None:
        tags.extend(
            _image_size_tags(
                image_info.image_width,
                image_info.image_height,
                (*image_info.evidence_ids, _PSP_PUBLIC_OUTPUT_SOURCE),
            )
        )
    return _graph(source_file, tags, diagnostics)


def _nested_exif_tags(data: bytes, plan: PspMetadataTransactionPlan) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    tags: list[ReadTag] = []
    for payload_range in plan.embedded_metadata.exif.payload_ranges:
        start, end = payload_range
        payload = data[start:end]
        if not payload.startswith(b"Exif\0\0"):
            continue
        ifd0_values = _read_psp_exif_ifd0_values(payload)
        for name in ("Copyright", "XResolution", "YResolution", "ResolutionUnit"):
            value = ifd0_values.get(name)
            if value is None:
                continue
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(_psp_public_value(value)),
                    provenance=_provenance(
                        group="IFD0",
                        table_name=_PSP_EXIF_TABLE,
                        tag_id=name,
                        evidence_ids=(
                            *plan.embedded_metadata.exif.evidence_ids,
                            _PSP_PUBLIC_OUTPUT_SOURCE,
                        ),
                    ),
                    schema=None,
                )
            )
    return tags


def _read_psp_exif_ifd0_values(payload: bytes) -> dict[str, PspExifScalar]:
    if len(payload) <= 16 or payload[:6] != b"Exif\0\0":
        return {}
    byte_order = payload[6:8]
    if byte_order == b"II":
        endian: PspByteOrder = "little"
    elif byte_order == b"MM":
        endian = "big"
    else:
        return {}
    if _read_u16(payload, 8, endian) != 42:
        return {}
    ifd_start = 14
    entry_count = _read_u16(payload, ifd_start, endian)
    entries_start = ifd_start + 2
    entries_end = entries_start + entry_count * 12
    if entries_end + 4 > len(payload):
        return {}
    values: dict[str, PspExifScalar] = {}
    for index in range(entry_count):
        entry_offset = entries_start + index * 12
        tag_id = _read_u16(payload, entry_offset, endian)
        field_type = _read_u16(payload, entry_offset + 2, endian)
        count = _read_u32(payload, entry_offset + 4, endian)
        value_offset = _read_u32(payload, entry_offset + 8, endian)
        if tag_id == 0x8298 and field_type == 2:
            value_start = ifd_start + value_offset if count > 4 else entry_offset + 8
            value_end = min(len(payload), value_start + count)
            values["Copyright"] = (
                payload[value_start:value_end].split(b"\0", 1)[0].decode("latin-1")
            )
        elif tag_id in {0x011A, 0x011B} and field_type == 5:
            value_start = ifd_start + value_offset
            if value_start + 8 > len(payload):
                continue
            numerator = _read_u32(payload, value_start, endian)
            denominator = _read_u32(payload, value_start + 4, endian)
            if denominator == 0:
                continue
            value = numerator / denominator
            if value.is_integer():
                values["XResolution" if tag_id == 0x011A else "YResolution"] = int(value)
            else:
                values["XResolution" if tag_id == 0x011A else "YResolution"] = value
        elif tag_id == 0x0128 and field_type == 3:
            unit = _read_u16(payload, entry_offset + 8, endian)
            values["ResolutionUnit"] = {1: "None", 2: "inches", 3: "cm"}.get(unit, unit)
    return values


def _psp_public_value(value: PspExifScalar) -> PspExifScalar:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return value.replace("\ufffd", "?").replace("\xa9", "?")
    return value


def _read_u16(data: bytes, offset: int, byte_order: PspByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 2], byte_order)


def _read_u32(data: bytes, offset: int, byte_order: PspByteOrder) -> int:
    return int.from_bytes(data[offset : offset + 4], byte_order)


def _image_size_tags(
    width: int,
    height: int,
    evidence_ids: tuple[str, ...],
) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    megapixels = round(width * height / 1_000_000, 1 if width * height >= 1_000_000 else 6)
    return [
        ReadTag(
            name="ImageSize",
            value=_read_value(f"{width}x{height}"),
            provenance=_provenance(
                group="Composite",
                table_name="Composite",
                tag_id="Exif-ImageSize",
                evidence_ids=evidence_ids,
            ),
            schema=None,
        ),
        ReadTag(
            name="Megapixels",
            value=_read_value(megapixels),
            provenance=_provenance(
                group="Composite",
                table_name="Composite",
                tag_id="Exif-Megapixels",
                evidence_ids=evidence_ids,
            ),
            schema=None,
        ),
    ]


def _decode_creator_value(
    data: bytes, tag_id: int, payload_range: tuple[int, int]
) -> int | str | None:
    start, end = payload_range
    payload = data[start:end]
    if tag_id in {0, 3, 4, 5}:
        return payload.rstrip(b"\x00").decode("latin-1")
    if tag_id in {1, 2} and len(payload) >= 4:
        timestamp = int.from_bytes(payload[:4], "little")
        return _format_unix_time(timestamp)
    if tag_id == 6 and len(payload) >= 4:
        app_id = int.from_bytes(payload[:4], "little")
        return {0: "Unknown", 1: "Paint Shop Pro"}.get(app_id, app_id)
    if tag_id == 7 and len(payload) >= 4:
        return ".".join(str(part) for part in reversed(payload[:4]))
    return None


def _format_unix_time(timestamp: int) -> str:
    local_time = datetime.fromtimestamp(timestamp).astimezone()
    offset = local_time.strftime("%z")
    if len(offset) == 5:
        offset = f"{offset[:3]}:{offset[3:]}"
    return local_time.strftime("%Y:%m:%d %H:%M:%S") + offset


def invoke_psp(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_psp_read_graph(_read_psp_public_probe(path), source_file)


def _read_psp_public_probe(path: Path) -> bytes:
    # PSP.pm validates the signature then walks block headers, seeking unknown blocks.
    with path.open("rb") as file:
        return file.read(_PSP_PUBLIC_READ_LIMIT)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="psp",
        builder_ref="exifmodern.formats.psp:invoke_psp",
        patterns=(Pattern(0, b"Paint Shop Pro Image File\x0a\x1a\0\0\0\0\0"),),
    ),
)
