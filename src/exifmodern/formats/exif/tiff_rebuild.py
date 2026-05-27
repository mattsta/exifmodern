"""EXIF reduced-resolution TIFF rebuild service.

Callers provide source bytes plus typed strip metadata, and the service returns
thumbnail/preview TIFF effects without mutating runtime state.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_LONG,
    TIFF_TYPE_RATIONAL,
    TIFF_TYPE_SHORT,
    Endian,
    IfdContextName,
    IfdEntry,
    TiffFieldType,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
    report_tiff_traversal_readiness,
)
from exifmodern.formats.tiff.writer_primitives import TiffIfdWriteEntry

type RebuiltTiffTagName = Literal["ThumbnailTIFF", "PreviewTIFF"]
type TiffRebuildSourceFieldName = Literal[
    "SubfileType",
    "Compression",
    "ImageWidth",
    "ImageHeight",
    "BitsPerSample",
    "PhotometricInterpretation",
    "StripOffsets",
    "SamplesPerPixel",
    "RowsPerStrip",
    "StripByteCounts",
    "PlanarConfiguration",
    "Orientation",
]
type TiffRebuildSourceFieldValue = int | str | tuple[int, ...]
type TiffScalarEntryValue = int | Fraction
type TiffEntryValue = TiffScalarEntryValue | tuple[int, ...]
type TiffRebuildDiagnosticCode = Literal[
    "invalid_required_field",
    "invalid_strip_payload",
    "missing_required_field",
    "strip_count_mismatch",
    "unsupported_compression",
    "unsupported_file_type",
]

TIFF_REBUILD_SOURCE_TAGS: dict[int, TiffRebuildSourceFieldName] = {
    0x00FE: "SubfileType",
    0x0100: "ImageWidth",
    0x0101: "ImageHeight",
    0x0102: "BitsPerSample",
    0x0103: "Compression",
    0x0106: "PhotometricInterpretation",
    0x0111: "StripOffsets",
    0x0112: "Orientation",
    0x0115: "SamplesPerPixel",
    0x0116: "RowsPerStrip",
    0x0117: "StripByteCounts",
    0x011C: "PlanarConfiguration",
}

REBUILD_TIFF_COMPOSITE_SOURCE_ID = "format.exif.tiff_rebuild.thumbnail_composite"
REBUILD_TIFF_SOURCE_ID = "format.exif.tiff_rebuild.rebuild_tiff"


@dataclass(frozen=True)
class TiffStrip:
    offset: int
    byte_count: int


@dataclass(frozen=True)
class ReducedResolutionTiffCandidate:
    subfile_type: int
    compression: int
    image_width: int
    image_height: int
    bits_per_sample: tuple[int, ...]
    photometric_interpretation: int
    strips: tuple[TiffStrip, ...]
    samples_per_pixel: int
    rows_per_strip: int
    planar_configuration: int = 1
    orientation: int = 1
    group0: str | None = None
    group1: str | None = None


@dataclass(frozen=True)
class TiffRebuildSourceField:
    name: TiffRebuildSourceFieldName
    value: TiffRebuildSourceFieldValue
    group0: str | None = None
    group1: str | None = None
    occurrence: int = 0


@dataclass(frozen=True)
class TiffRebuildCandidateCollection:
    candidates: tuple[ReducedResolutionTiffCandidate, ...]
    warnings: tuple[str, ...]
    diagnostics: tuple[TiffRebuildDiagnostic, ...] = ()
    evidence_ids: tuple[str, ...] = (REBUILD_TIFF_COMPOSITE_SOURCE_ID, REBUILD_TIFF_SOURCE_ID)


@dataclass(frozen=True)
class RebuiltTiffImage:
    tag_name: RebuiltTiffTagName
    data: bytes
    group0: str | None
    group1: str | None


@dataclass(frozen=True)
class ExifTiffRebuildResult:
    thumbnail: RebuiltTiffImage | None
    previews: tuple[RebuiltTiffImage, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class TiffRebuildDiagnostic:
    code: TiffRebuildDiagnosticCode
    message: str
    group0: str | None
    group1: str | None
    occurrence: int
    source_field: TiffRebuildSourceFieldName | None = None


@dataclass(frozen=True)
class TiffRebuildReadGraphEmission:
    tag_name: RebuiltTiffTagName
    data: bytes
    family_0_group: str | None
    family_1_group: str | None
    family_2_group: Literal["Preview"] = "Preview"
    group: Literal["Composite"] = "Composite"
    table_name: Literal["Image::ExifTool::Exif::Composite"] = "Image::ExifTool::Exif::Composite"
    source: Literal["exif-tiff-rebuild"] = "exif-tiff-rebuild"
    media_type: Literal["image/tiff"] = "image/tiff"
    file_extension: Literal["tif"] = "tif"


@dataclass(frozen=True)
class ExifTiffRebuildHandoff:
    candidates: tuple[ReducedResolutionTiffCandidate, ...]
    result: ExifTiffRebuildResult
    emissions: tuple[TiffRebuildReadGraphEmission, ...]
    diagnostics: tuple[TiffRebuildDiagnostic, ...]
    evidence_ids: tuple[str, ...] = (REBUILD_TIFF_COMPOSITE_SOURCE_ID, REBUILD_TIFF_SOURCE_ID)


def collect_rebuild_tiff_source_fields_from_tiff(
    tiff_data: bytes,
    group0: str = "EXIF",
) -> tuple[TiffRebuildSourceField, ...]:
    """Collect RebuildTIFF source fields from parsed TIFF IFD contexts."""

    header = parse_tiff_header(tiff_data)
    traversal = report_tiff_traversal_readiness(tiff_data)
    fields: list[TiffRebuildSourceField] = []
    occurrence_by_name: dict[TiffRebuildSourceFieldName, int] = {}
    for context in traversal.contexts:
        ifd = parse_ifd(tiff_data, context.offset, header.endian)
        for entry in ifd.entries:
            name = TIFF_REBUILD_SOURCE_TAGS.get(entry.tag_id)
            if name is None:
                continue
            value = rebuild_source_field_value(tiff_data, entry, header.endian)
            if value is None:
                continue
            occurrence = occurrence_by_name.get(name, 0)
            occurrence_by_name[name] = occurrence + 1
            fields.append(
                TiffRebuildSourceField(
                    name=name,
                    value=value,
                    group0=group0,
                    group1=rebuild_group_name(context.name),
                    occurrence=occurrence,
                )
            )
    return tuple(fields)


def rebuild_source_field_value(
    tiff_data: bytes,
    entry: IfdEntry,
    endian: Endian,
) -> TiffRebuildSourceFieldValue | None:
    value = read_entry_value(tiff_data, entry, endian)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        items: list[int] = []
        for item in value:
            if not isinstance(item, int):
                return None
            items.append(item)
        return tuple(items)
    return None


def rebuild_group_name(context_name: IfdContextName) -> str:
    return context_name


def collect_rebuild_tiff_candidates(
    fields: tuple[TiffRebuildSourceField, ...],
) -> TiffRebuildCandidateCollection:
    candidates: list[ReducedResolutionTiffCandidate] = []
    warnings: list[str] = []
    diagnostics: list[TiffRebuildDiagnostic] = []
    for subfile_field in fields:
        if subfile_field.name != "SubfileType":
            continue
        if source_int(subfile_field.value) != 1:
            continue
        candidate = source_fields_to_candidate(fields, subfile_field)
        if candidate is None:
            warnings.append(missing_tiff_source_fields_warning(subfile_field))
            diagnostics.extend(diagnose_candidate_source_fields(fields, subfile_field))
            continue
        candidates.append(candidate)
    return TiffRebuildCandidateCollection(
        candidates=tuple(candidates),
        warnings=tuple(warnings),
        diagnostics=tuple(diagnostics),
    )


def rebuild_tiff_from_source_fields(
    source_data: bytes,
    fields: tuple[TiffRebuildSourceField, ...],
    endian: Endian = "little",
    file_type: str | None = None,
) -> ExifTiffRebuildHandoff:
    if file_type == "RWZ":
        diagnostics = (
            TiffRebuildDiagnostic(
                code="unsupported_file_type",
                message="RebuildTIFF is disabled for RWZ files.",
                group0=None,
                group1=None,
                occurrence=0,
                source_field=None,
            ),
        )
        return ExifTiffRebuildHandoff(
            candidates=(),
            result=ExifTiffRebuildResult(thumbnail=None, previews=(), warnings=()),
            emissions=(),
            diagnostics=diagnostics,
        )
    collection = collect_rebuild_tiff_candidates(fields)
    result = rebuild_tiff_candidates(source_data, collection.candidates, endian)
    result_diagnostics = tuple(
        TiffRebuildDiagnostic(
            code="invalid_strip_payload",
            message=warning,
            group0=None,
            group1=None,
            occurrence=0,
            source_field=None,
        )
        for warning in result.warnings
    )
    return ExifTiffRebuildHandoff(
        candidates=collection.candidates,
        result=result,
        emissions=read_graph_emissions_from_result(result),
        diagnostics=collection.diagnostics + result_diagnostics,
    )


def source_fields_to_candidate(
    fields: tuple[TiffRebuildSourceField, ...],
    subfile_field: TiffRebuildSourceField,
) -> ReducedResolutionTiffCandidate | None:
    compression = source_int(required_source_value(fields, subfile_field, "Compression"))
    if compression != 1:
        return None
    image_width = source_int(required_source_value(fields, subfile_field, "ImageWidth"))
    image_height = source_int(required_source_value(fields, subfile_field, "ImageHeight"))
    bits_per_sample = source_int_tuple(
        required_source_value(fields, subfile_field, "BitsPerSample")
    )
    photometric_interpretation = source_int(
        required_source_value(fields, subfile_field, "PhotometricInterpretation")
    )
    strip_offsets = source_int_tuple(required_source_value(fields, subfile_field, "StripOffsets"))
    samples_per_pixel = source_int(required_source_value(fields, subfile_field, "SamplesPerPixel"))
    rows_per_strip = source_int(required_source_value(fields, subfile_field, "RowsPerStrip"))
    strip_byte_counts = source_int_tuple(
        required_source_value(fields, subfile_field, "StripByteCounts")
    )
    if (
        image_width is None
        or image_height is None
        or bits_per_sample is None
        or photometric_interpretation is None
        or strip_offsets is None
        or samples_per_pixel is None
        or rows_per_strip is None
        or strip_byte_counts is None
        or len(strip_offsets) != len(strip_byte_counts)
    ):
        return None
    planar_configuration = source_int(
        optional_source_value(fields, subfile_field, "PlanarConfiguration")
    )
    orientation = source_int(optional_source_value(fields, subfile_field, "Orientation"))
    return ReducedResolutionTiffCandidate(
        subfile_type=1,
        compression=1,
        image_width=image_width,
        image_height=image_height,
        bits_per_sample=bits_per_sample,
        photometric_interpretation=photometric_interpretation,
        strips=tuple(
            TiffStrip(offset=offset, byte_count=byte_count)
            for offset, byte_count in zip(strip_offsets, strip_byte_counts, strict=True)
        ),
        samples_per_pixel=samples_per_pixel,
        rows_per_strip=rows_per_strip,
        planar_configuration=1 if planar_configuration is None else planar_configuration,
        orientation=1 if orientation is None else orientation,
        group0=subfile_field.group0,
        group1=subfile_field.group1,
    )


def diagnose_candidate_source_fields(
    fields: tuple[TiffRebuildSourceField, ...],
    subfile_field: TiffRebuildSourceField,
) -> tuple[TiffRebuildDiagnostic, ...]:
    compression = source_int(required_source_value(fields, subfile_field, "Compression"))
    if compression is not None and compression != 1:
        return (
            TiffRebuildDiagnostic(
                code="unsupported_compression",
                message="RebuildTIFF only emits uncompressed reduced-resolution TIFF data.",
                group0=subfile_field.group0,
                group1=subfile_field.group1,
                occurrence=subfile_field.occurrence,
                source_field="Compression",
            ),
        )
    diagnostics: list[TiffRebuildDiagnostic] = []
    for name in (
        "Compression",
        "ImageWidth",
        "ImageHeight",
        "BitsPerSample",
        "PhotometricInterpretation",
        "StripOffsets",
        "SamplesPerPixel",
        "RowsPerStrip",
        "StripByteCounts",
    ):
        value = required_source_value(fields, subfile_field, name)
        if value is None:
            diagnostics.append(
                TiffRebuildDiagnostic(
                    code="missing_required_field",
                    message=f"Missing required RebuildTIFF source field {name}.",
                    group0=subfile_field.group0,
                    group1=subfile_field.group1,
                    occurrence=subfile_field.occurrence,
                    source_field=name,
                )
            )
        elif not valid_required_source_value(name, value):
            diagnostics.append(
                TiffRebuildDiagnostic(
                    code="invalid_required_field",
                    message=f"Invalid RebuildTIFF source field {name}.",
                    group0=subfile_field.group0,
                    group1=subfile_field.group1,
                    occurrence=subfile_field.occurrence,
                    source_field=name,
                )
            )
    strip_offsets = source_int_tuple(required_source_value(fields, subfile_field, "StripOffsets"))
    strip_byte_counts = source_int_tuple(
        required_source_value(fields, subfile_field, "StripByteCounts")
    )
    if (
        strip_offsets is not None
        and strip_byte_counts is not None
        and len(strip_offsets) != len(strip_byte_counts)
    ):
        diagnostics.append(
            TiffRebuildDiagnostic(
                code="strip_count_mismatch",
                message="RebuildTIFF StripOffsets and StripByteCounts have different counts.",
                group0=subfile_field.group0,
                group1=subfile_field.group1,
                occurrence=subfile_field.occurrence,
                source_field="StripByteCounts",
            )
        )
    return tuple(diagnostics)


def valid_required_source_value(
    name: TiffRebuildSourceFieldName,
    value: TiffRebuildSourceFieldValue,
) -> bool:
    if name in {"BitsPerSample", "StripOffsets", "StripByteCounts"}:
        return source_int_tuple(value) is not None
    return source_int(value) is not None


def required_source_value(
    fields: tuple[TiffRebuildSourceField, ...],
    subfile_field: TiffRebuildSourceField,
    name: TiffRebuildSourceFieldName,
) -> TiffRebuildSourceFieldValue | None:
    return source_value(fields, subfile_field, name)


def optional_source_value(
    fields: tuple[TiffRebuildSourceField, ...],
    subfile_field: TiffRebuildSourceField,
    name: TiffRebuildSourceFieldName,
) -> TiffRebuildSourceFieldValue | None:
    return source_value(fields, subfile_field, name)


def source_value(
    fields: tuple[TiffRebuildSourceField, ...],
    subfile_field: TiffRebuildSourceField,
    name: TiffRebuildSourceFieldName,
) -> TiffRebuildSourceFieldValue | None:
    same_group = tuple(
        field
        for field in fields
        if field.name == name and field.group1 is not None and field.group1 == subfile_field.group1
    )
    if same_group:
        return same_group[0].value
    for field in fields:
        if field.name == name and field.occurrence == subfile_field.occurrence:
            return field.value
    return None


def source_int(value: TiffRebuildSourceFieldValue | None) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip(), 0)
        except ValueError:
            return None
    return None


def source_int_tuple(
    value: TiffRebuildSourceFieldValue | None,
) -> tuple[int, ...] | None:
    if isinstance(value, tuple):
        return value
    if isinstance(value, int):
        return (value,)
    if value is None:
        return None
    items: list[int] = []
    for item in value.split():
        try:
            items.append(int(item, 0))
        except ValueError:
            return None
    return tuple(items)


def missing_tiff_source_fields_warning(field: TiffRebuildSourceField) -> str:
    suffix = f" ({field.occurrence})" if field.occurrence else ""
    return f"Missing or invalid ThumbnailTIFF source fields for SubfileType{suffix}"


def rebuild_tiff_candidates(
    source_data: bytes,
    candidates: tuple[ReducedResolutionTiffCandidate, ...],
    endian: Endian = "little",
) -> ExifTiffRebuildResult:
    thumbnail: RebuiltTiffImage | None = None
    previews: list[RebuiltTiffImage] = []
    warnings: list[str] = []
    for candidate in candidates:
        rebuilt = rebuild_single_tiff_candidate(source_data, candidate, endian)
        if rebuilt is None:
            warnings.append(invalid_tiff_warning(candidate.image_width))
            continue
        if thumbnail is None and candidate.image_width <= 256:
            thumbnail = RebuiltTiffImage(
                tag_name="ThumbnailTIFF",
                data=rebuilt,
                group0=candidate.group0,
                group1=candidate.group1,
            )
        else:
            previews.append(
                RebuiltTiffImage(
                    tag_name="PreviewTIFF",
                    data=rebuilt,
                    group0=candidate.group0,
                    group1=candidate.group1,
                )
            )
    return ExifTiffRebuildResult(
        thumbnail=thumbnail,
        previews=tuple(previews),
        warnings=tuple(warnings),
    )


def read_graph_emissions_from_result(
    result: ExifTiffRebuildResult,
) -> tuple[TiffRebuildReadGraphEmission, ...]:
    images = (() if result.thumbnail is None else (result.thumbnail,)) + result.previews
    return tuple(
        TiffRebuildReadGraphEmission(
            tag_name=image.tag_name,
            data=image.data,
            family_0_group=image.group0,
            family_1_group=image.group1,
        )
        for image in images
    )


def rebuild_single_tiff_candidate(
    source_data: bytes,
    candidate: ReducedResolutionTiffCandidate,
    endian: Endian = "little",
) -> bytes | None:
    if candidate.subfile_type != 1 or candidate.compression != 1:
        return None
    row_bytes = row_byte_count(candidate.image_width, candidate.bits_per_sample)
    image_data = extract_rebuild_image_data(source_data, candidate, row_bytes)
    if image_data is None:
        return None
    entries = rebuild_tiff_entries(candidate, row_bytes)
    return generate_tiff(entries, image_data, endian)


def row_byte_count(image_width: int, bits_per_sample: tuple[int, ...]) -> int:
    total = 0
    for bits in bits_per_sample:
        total += image_width * ((bits + 7) // 8)
    return total


def extract_rebuild_image_data(
    source_data: bytes,
    candidate: ReducedResolutionTiffCandidate,
    row_bytes: int,
) -> bytes | None:
    expected_strip_length = row_bytes * candidate.rows_per_strip
    output = bytearray()
    for strip in candidate.strips:
        if strip.byte_count != expected_strip_length:
            return None
        end = strip.offset + strip.byte_count
        if strip.offset < 0 or end > len(source_data):
            return None
        output.extend(source_data[strip.offset : end])
    return bytes(output)


def rebuild_tiff_entries(
    candidate: ReducedResolutionTiffCandidate,
    row_bytes: int,
) -> dict[int, TiffEntryValue]:
    return {
        0x0FE: 0,
        0x100: candidate.image_width,
        0x101: candidate.image_height,
        0x102: candidate.bits_per_sample,
        0x103: candidate.compression,
        0x106: candidate.photometric_interpretation,
        0x111: 0,
        0x112: candidate.orientation,
        0x115: candidate.samples_per_pixel,
        0x116: candidate.image_height,
        0x117: candidate.image_height * row_bytes,
        0x11A: Fraction(72, 1),
        0x11B: Fraction(72, 1),
        0x11C: candidate.planar_configuration,
        0x128: 2,
    }


def generate_tiff(
    entries: dict[int, TiffEntryValue],
    image_data: bytes,
    endian: Endian,
) -> bytes | None:
    if 0x111 not in entries:
        return None
    encoded_entries = tuple(
        TiffIfdWriteEntry(
            tag_id=tag_id,
            field_type=tiff_entry_field_type(tag_id),
            count=tiff_entry_count(value),
            raw_value=tiff_entry_raw_value(tag_id, value, endian),
        )
        for tag_id, value in entries.items()
    )
    ifd = encode_full_tiff_ifd_with_zero_strip_offset(encoded_entries, endian)
    image_offset = 8 + len(ifd)
    patched_ifd = patch_strip_offset(ifd, image_offset, endian)
    byte_order = b"II" if endian == "little" else b"MM"
    return (
        byte_order + (42).to_bytes(2, endian) + (8).to_bytes(4, endian) + patched_ifd + image_data
    )


def encode_full_tiff_ifd_with_zero_strip_offset(
    entries: tuple[TiffIfdWriteEntry, ...],
    endian: Endian,
) -> bytes:
    sorted_entries = tuple(sorted(entries, key=lambda entry: entry.tag_id))
    external_start = 8 + 2 + len(sorted_entries) * 12 + 4
    encoded_entries: list[bytes] = []
    external_values: list[bytes] = []
    external_offset = external_start
    for entry in sorted_entries:
        if len(entry.raw_value) <= 4:
            value_offset = int.from_bytes(entry.raw_value.ljust(4, b"\x00"), endian)
        else:
            value_offset = external_offset
            external_values.append(entry.raw_value)
            external_offset += len(entry.raw_value)
        encoded_entries.append(
            entry.tag_id.to_bytes(2, endian)
            + entry.field_type.to_bytes(2, endian)
            + entry.count.to_bytes(4, endian)
            + value_offset.to_bytes(4, endian)
        )
    return (
        len(sorted_entries).to_bytes(2, endian)
        + b"".join(encoded_entries)
        + (0).to_bytes(4, endian)
        + b"".join(external_values)
    )


def patch_strip_offset(ifd_data: bytes, image_offset: int, endian: Endian) -> bytes:
    entry_count = int.from_bytes(ifd_data[:2], endian)
    mutable = bytearray(ifd_data)
    for index in range(entry_count):
        entry_offset = 2 + index * 12
        tag_id = int.from_bytes(ifd_data[entry_offset : entry_offset + 2], endian)
        if tag_id == 0x111:
            mutable[entry_offset + 8 : entry_offset + 12] = image_offset.to_bytes(4, endian)
            return bytes(mutable)
    raise ValueError("Generated TIFF IFD does not contain StripOffsets")


def tiff_entry_field_type(tag_id: int) -> TiffFieldType:
    if tag_id in {0x102, 0x103, 0x106, 0x112, 0x115, 0x11C, 0x128}:
        return TIFF_TYPE_SHORT
    if tag_id in {0x11A, 0x11B}:
        return TIFF_TYPE_RATIONAL
    return TIFF_TYPE_LONG


def tiff_entry_count(value: TiffEntryValue) -> int:
    if isinstance(value, tuple):
        return len(value)
    return 1


def tiff_entry_raw_value(tag_id: int, value: TiffEntryValue, endian: Endian) -> bytes:
    if isinstance(value, tuple):
        return b"".join(item.to_bytes(2, endian) for item in value)
    if isinstance(value, Fraction):
        return value.numerator.to_bytes(4, endian) + value.denominator.to_bytes(4, endian)
    if tiff_entry_field_type(tag_id) == TIFF_TYPE_SHORT:
        return value.to_bytes(2, endian)
    return value.to_bytes(4, endian)


def invalid_tiff_warning(image_width: int) -> str:
    image_kind = "Preview" if image_width > 256 else "Thumbnail"
    return f"Invalid {image_kind}TIFF data"
