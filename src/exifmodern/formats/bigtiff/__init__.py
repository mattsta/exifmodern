"""BigTIFF metadata transaction planning."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from exifmodern.formats.bigtiff.transaction_plan import (
    BIGTIFF_DIRECTORY_COUNT_SIZE,
    BIGTIFF_DIRECTORY_ENTRY_SIZE,
    BIGTIFF_HEADER_SIZE,
    BIGTIFF_INLINE_VALUE_SIZE,
    BIGTIFF_MAX_SUPPORTED_OFFSET,
    BIGTIFF_NEXT_IFD_POINTER_SIZE,
    EXIF_IFD_POINTER_TAG,
    FORMAT_SIZES,
    GPS_IFD_POINTER_TAG,
    SUB_IFD_POINTER_TAG,
    BigTiffDirectoryPlan,
    BigTiffEndian,
    BigTiffEntryPlan,
    BigTiffExifGpsSourceMaterialization,
    BigTiffHeaderPlan,
    BigTiffMetadataTransactionPlan,
    BigTiffSourceTag,
    build_bigtiff_metadata_transaction_plan,
    endian_from_marker,
    materialize_bigtiff_exif_gps_source,
    read_u16,
    read_u64,
    subifd_offsets_from_payload,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.dispatch_helpers import EvidenceAnchors
    from exifmodern.read_graph import ReadGraph, TagProvenance

BIGTIFF_TAG_NAMES: dict[int, str] = {
    0x0100: "ImageWidth",
    0x0101: "ImageHeight",
    0x0102: "BitsPerSample",
    0x0106: "PhotometricInterpretation",
    0x0111: "StripOffsets",
    0x0115: "SamplesPerPixel",
    0x0116: "RowsPerStrip",
    0x0117: "StripByteCounts",
}
BIGTIFF_TAG_IDS: dict[int, str] = {
    0x0100: "256",
    0x0101: "257",
    0x0102: "258",
    0x0106: "262",
    0x0111: "273",
    0x0115: "277",
    0x0116: "278",
    0x0117: "279",
}

__all__ = [
    "BIGTIFF_MAX_SUPPORTED_OFFSET",
    "BigTiffDirectoryPlan",
    "BigTiffEntryPlan",
    "BigTiffExifGpsSourceMaterialization",
    "BigTiffHeaderPlan",
    "BigTiffMetadataTransactionPlan",
    "BigTiffSourceTag",
    "build_bigtiff_metadata_transaction_plan",
    "build_bigtiff_read_graph",
    "invoke_bigtiff",
    "materialize_bigtiff_exif_gps_source",
]


def build_bigtiff_read_graph(data: bytes, source_file: str) -> ReadGraph:
    # Lazy imports avoid circular-import collisions between read_graph and
    # the format-module ecosystem.
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value, _references
    from exifmodern.read_graph import ReadTag

    plan = build_bigtiff_metadata_transaction_plan(data, allow_output_emission=True)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"BigTIFF package-local reader status: {plan.status}")
    diagnostics.extend(
        f"BigTIFF package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = []
    if plan.status == "planned":
        tags.extend(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group="File",
                    table_name="Image::ExifTool::File",
                    tag_id=name,
                    references=_references(plan.header),
                ),
                schema=None,
            )
            for name, value in (
                ("FileType", "BTF"),
                ("FileTypeExtension", "btf"),
                ("MIMEType", "image/x-tiff-big"),
            )
        )
    image_width: int | None = None
    image_height: int | None = None
    for directory in plan.directories:
        for entry in directory.entries:
            name = BIGTIFF_TAG_NAMES.get(entry.tag_id)
            if name is None:
                continue
            value = bigtiff_entry_value(entry, plan.header.endian)
            if value is None:
                diagnostics.append(
                    f"BigTIFF package-local reader unsupported tag: "
                    f"0x{entry.tag_id:04x}: unsupported scalar format"
                )
                continue
            if entry.tag_id == 0x0100 and isinstance(value, int):
                image_width = value
            if entry.tag_id == 0x0101 and isinstance(value, int):
                image_height = value
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=_bigtiff_ifd0_provenance(
                        tag_id=BIGTIFF_TAG_IDS[entry.tag_id],
                        references=_references(entry),
                        duplicate_instance_ordinal=entry.index,
                    ),
                    schema=None,
                )
            )
    if image_width is not None and image_height is not None:
        megapixels = image_width * image_height / 1_000_000
        tags.extend(
            (
                ReadTag(
                    name="ImageSize",
                    value=f"{image_width}x{image_height}",
                    provenance=_provenance(
                        group="Composite",
                        table_name="Image::ExifTool::Composite",
                        tag_id="Exif-ImageSize",
                        references=_references(plan),
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="Megapixels",
                    value=round_bigtiff_megapixels(megapixels),
                    provenance=_provenance(
                        group="Composite",
                        table_name="Image::ExifTool::Composite",
                        tag_id="Exif-Megapixels",
                        references=_references(plan),
                    ),
                    schema=None,
                ),
            )
        )
    return _graph(source_file, tags, diagnostics)


def bigtiff_entry_value(entry: BigTiffEntryPlan, endian: str | None) -> str | int | None:
    if endian not in {"big", "little"}:
        return None
    endian_name: BigTiffEndian = "big" if endian == "big" else "little"
    payload = entry.payload_preview
    if entry.format_code in {3, 4, 16, 18}:
        step = {3: 2, 4: 4, 16: 8, 18: 8}[entry.format_code]
        values: list[int] = []
        for offset in range(0, min(len(payload), entry.count * step), step):
            if offset + step > len(payload):
                break
            values.append(int.from_bytes(payload[offset : offset + step], endian_name))
        if not values:
            return None
        value: str | int = values[0] if len(values) == 1 else " ".join(str(item) for item in values)
        if entry.tag_id == 0x0106 and value == 2:
            return "RGB"
        return value
    if entry.format_code == 2:
        return payload.split(b"\0", 1)[0].decode("latin-1", errors="replace")
    return None


def _bigtiff_ifd0_provenance(
    *,
    tag_id: str,
    references: EvidenceAnchors,
    duplicate_instance_ordinal: int | None,
) -> TagProvenance:
    from exifmodern.dispatch_helpers import _source_text
    from exifmodern.read_graph import TagProvenance

    return TagProvenance(
        group="EXIF",
        table_name="Image::ExifTool::Exif::Main",
        tag_id=tag_id,
        source=_source_text(references),
        family_0_group="EXIF",
        family_1_group="IFD0",
        family_2_group="Image",
        duplicate_instance_ordinal=duplicate_instance_ordinal,
    )


def round_bigtiff_megapixels(value: float) -> float:
    if value >= 1:
        return round(value, 1)
    if value >= 0.001:
        return round(value, 3)
    return round(value, 6)


def invoke_bigtiff(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return _build_bigtiff_read_graph_from_file(path, source_file)


def _build_bigtiff_read_graph_from_file(path: Path, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value, _references
    from exifmodern.read_graph import ReadTag

    diagnostics: list[str] = []
    tags: list[ReadTag] = []
    with path.open("rb") as file:
        header = file.read(BIGTIFF_HEADER_SIZE)
        header_plan = build_bigtiff_metadata_transaction_plan(
            header,
            allow_output_emission=True,
        ).header
        if len(header) < BIGTIFF_HEADER_SIZE:
            diagnostics.append("BigTIFF package-local reader status: unsupported")
            return _graph(source_file, tags, diagnostics)
        endian = endian_from_marker(header[:2])
        if endian is None:
            diagnostics.append("BigTIFF package-local reader status: unsupported")
            return _graph(source_file, tags, diagnostics)
        first_ifd_offset = read_u64(header, 8, endian)
        tags.extend(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group="File",
                    table_name="Image::ExifTool::File",
                    tag_id=name,
                    references=_references(header_plan),
                ),
                schema=None,
            )
            for name, value in (
                ("FileType", "BTF"),
                ("FileTypeExtension", "btf"),
                ("MIMEType", "image/x-tiff-big"),
            )
        )
        entries = _walk_bigtiff_entries(file, endian, first_ifd_offset)
    image_width: int | None = None
    image_height: int | None = None
    for ordinal, entry in enumerate(entries):
        tag_id, format_code, count, payload = entry
        name = BIGTIFF_TAG_NAMES.get(tag_id)
        if name is None:
            continue
        value = _bigtiff_value_from_payload(tag_id, format_code, count, payload, endian)
        if value is None:
            diagnostics.append(
                f"BigTIFF package-local reader unsupported tag: "
                f"0x{tag_id:04x}: unsupported scalar format"
            )
            continue
        if tag_id == 0x0100 and isinstance(value, int):
            image_width = value
        if tag_id == 0x0101 and isinstance(value, int):
            image_height = value
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_bigtiff_ifd0_provenance(
                    tag_id=BIGTIFF_TAG_IDS[tag_id],
                    references=("bigtiff.entry",),
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    if image_width is not None and image_height is not None:
        megapixels = image_width * image_height / 1_000_000
        tags.extend(
            (
                ReadTag(
                    name="ImageSize",
                    value=f"{image_width}x{image_height}",
                    provenance=_provenance(
                        group="Composite",
                        table_name="Image::ExifTool::Composite",
                        tag_id="Exif-ImageSize",
                        references=("bigtiff.directory",),
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="Megapixels",
                    value=round_bigtiff_megapixels(megapixels),
                    provenance=_provenance(
                        group="Composite",
                        table_name="Image::ExifTool::Composite",
                        tag_id="Exif-Megapixels",
                        references=("bigtiff.directory",),
                    ),
                    schema=None,
                ),
            )
        )
    return _graph(source_file, tags, diagnostics)


def _walk_bigtiff_entries(
    file: BinaryIO,
    endian: BigTiffEndian,
    first_ifd_offset: int,
) -> list[tuple[int, int, int, bytes]]:
    entries: list[tuple[int, int, int, bytes]] = []
    pending = [first_ifd_offset]
    seen: set[int] = set()
    while pending and len(seen) < 64:
        offset = pending.pop(0)
        if offset in seen or offset > BIGTIFF_MAX_SUPPORTED_OFFSET:
            continue
        seen.add(offset)
        count_bytes = _read_at(file, offset, BIGTIFF_DIRECTORY_COUNT_SIZE)
        if len(count_bytes) < BIGTIFF_DIRECTORY_COUNT_SIZE:
            continue
        entry_count = read_u64(count_bytes, 0, endian)
        if entry_count * BIGTIFF_DIRECTORY_ENTRY_SIZE > BIGTIFF_MAX_SUPPORTED_OFFSET:
            continue
        entries_offset = offset + BIGTIFF_DIRECTORY_COUNT_SIZE
        entries_bytes = _read_at(file, entries_offset, entry_count * BIGTIFF_DIRECTORY_ENTRY_SIZE)
        if len(entries_bytes) < entry_count * BIGTIFF_DIRECTORY_ENTRY_SIZE:
            continue
        for index in range(entry_count):
            entry = entries_bytes[
                index * BIGTIFF_DIRECTORY_ENTRY_SIZE : (index + 1) * BIGTIFF_DIRECTORY_ENTRY_SIZE
            ]
            parsed = _read_bigtiff_entry_payload(file, entry, endian)
            if parsed is None:
                continue
            tag_id, format_code, _count, payload = parsed
            entries.append(parsed)
            if tag_id in {SUB_IFD_POINTER_TAG, EXIF_IFD_POINTER_TAG, GPS_IFD_POINTER_TAG}:
                pending.extend(subifd_offsets_from_payload(tag_id, format_code, payload, endian))
                if tag_id in {EXIF_IFD_POINTER_TAG, GPS_IFD_POINTER_TAG} and payload:
                    pending.append(int.from_bytes(payload[: min(len(payload), 8)], endian))
        pointer_offset = entries_offset + len(entries_bytes)
        next_ifd = _read_at(file, pointer_offset, BIGTIFF_NEXT_IFD_POINTER_SIZE)
        if len(next_ifd) == BIGTIFF_NEXT_IFD_POINTER_SIZE:
            next_offset = read_u64(next_ifd, 0, endian)
            if next_offset:
                pending.append(next_offset)
    return entries


def _read_bigtiff_entry_payload(
    file: BinaryIO,
    entry: bytes,
    endian: BigTiffEndian,
) -> tuple[int, int, int, bytes] | None:
    tag_id = read_u16(entry, 0, endian)
    format_code = read_u16(entry, 2, endian)
    count = read_u64(entry, 4, endian)
    format_size = FORMAT_SIZES.get(format_code)
    if format_size is None:
        return tag_id, format_code, count, b""
    byte_count = count * format_size
    value_field = entry[12 : 12 + BIGTIFF_INLINE_VALUE_SIZE]
    if byte_count <= BIGTIFF_INLINE_VALUE_SIZE:
        return tag_id, format_code, count, value_field[:byte_count]
    value_offset = read_u64(value_field, 0, endian)
    if value_offset > BIGTIFF_MAX_SUPPORTED_OFFSET or byte_count > BIGTIFF_MAX_SUPPORTED_OFFSET:
        return tag_id, format_code, count, b""
    return tag_id, format_code, count, _read_at(file, value_offset, byte_count)


def _bigtiff_value_from_payload(
    tag_id: int,
    format_code: int,
    count: int,
    payload: bytes,
    endian: BigTiffEndian,
) -> str | int | None:
    entry = BigTiffEntryPlan(
        index=0,
        tag_id=tag_id,
        format_code=format_code,
        format_name=None,
        count=count,
        decoded_byte_count=len(payload),
        storage=None,
        entry_range=(0, 0),
        value_field_range=(0, 0),
        value_offset=None,
        payload_range=None,
        payload_preview=payload,
        subifd_offsets=(),
        gates=(),
        evidence_ids=("bigtiff.entry",),
    )
    return bigtiff_entry_value(entry, endian)


def _read_at(file: BinaryIO, offset: int, size: int) -> bytes:
    file.seek(offset)
    data = file.read(size)
    return bytes(data)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="bigtiff/le",
        builder_ref="exifmodern.formats.bigtiff:invoke_bigtiff",
        patterns=(Pattern(0, b"II+\x00"),),
    ),
    Signature(
        format_id="bigtiff/be",
        builder_ref="exifmodern.formats.bigtiff:invoke_bigtiff",
        patterns=(Pattern(0, b"MM\x00+"),),
    ),
)
