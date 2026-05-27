"""Bounded Phase One IIQ reader.

The IIQ fixture is TIFF-shaped and stores the Phase One maker-note block
immediately after the TIFF header.  This reader stays bounded to TIFF IFD
tables plus the PhaseOne.pm directory parser; it does not load raw image
payloads or attempt mutation/rebuild.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from exifmodern.formats.phaseone.transaction_plan import (
    PHASEONE_PROCESS_SOURCE,
    PhaseOneFieldPlan,
    build_phaseone_transaction_plan,
)
from exifmodern.formats.public_payload import (
    oversized_public_payload_graph,
    read_public_document_payload,
)
from exifmodern.formats.tiff.primitives import (
    EXIF_IFD_TAGS,
    IFD0_TAGS,
    IFD1_TAGS,
    Endian,
    Ifd,
    TiffValue,
    parse_ifd,
    parse_tiff_header,
    print_value,
    read_entry_value,
    read_exif_ifd_values,
    read_ifd0_values,
    read_ifd1_values,
)
from exifmodern.json_types import JsonObject
from exifmodern.read_graph import (
    BinaryTagListValue,
    BinaryTagValue,
    ReadGraph,
    ReadTag,
    TagProvenance,
    TagValue,
    add_tags,
    normalize_tag_map,
    system_provenance,
)
from exifmodern.services.system_metadata import read_system_tags

PHASEONE_IIQ_SOURCE = "phaseone.iiq.source"
PHASEONE_FILE_SOURCE = "phaseone.file.source"

_EXIF_IFD_POINTER = 0x8769
_MAKER_NOTE_TAG = 0x927C
_SUPPORTED_MAKER_BINARY_TAGS = frozenset(
    {"RawData", "StripOffsets", "BlackLevelData", "SensorDefects"}
)
_EXPOSED_MAKER_BINARY_PAYLOAD_TAGS = frozenset({"BlackLevelData", "SensorDefects"})
_PHASEONE_SUPPLEMENTAL_IFD0_TAGS = {
    0x00FE: "SubfileType",
    0x0100: "ImageWidth",
    0x0101: "ImageHeight",
    0x0102: "BitsPerSample",
    0x0103: "Compression",
    0x0106: "PhotometricInterpretation",
    0x0111: "StripOffsets",
    0x0115: "SamplesPerPixel",
    0x0116: "RowsPerStrip",
    0x0117: "StripByteCounts",
    0x011C: "PlanarConfiguration",
}
_PHASEONE_SUPPLEMENTAL_IFD1_TAGS = {
    tag_id: name for tag_id, name in _PHASEONE_SUPPLEMENTAL_IFD0_TAGS.items() if tag_id != 0x0103
}
_PHASEONE_SUPPLEMENTAL_EXIF_IFD_TAGS = {
    0x4746: "Rating",
    0x9208: "LightSource",
}
_TIFF_SUBFILE_TYPE_PRINT = {0: "Full-resolution image", 1: "Reduced-resolution image"}
_TIFF_PHOTOMETRIC_PRINT = {2: "RGB"}
_TIFF_PLANAR_CONFIGURATION_PRINT = {1: "Chunky", 2: "Planar"}
_TIFF_LIGHT_SOURCE_PRINT = {1: "Daylight"}
_MATRIX_TAGS = frozenset({"ColorMatrix1", "ColorMatrix2"})
_LINEARIZATION_TAGS = frozenset({"LinearizationCoefficients1", "LinearizationCoefficients2"})
type PhaseOneScalarTagValue = str | int | float | bool | None
type PhaseOneRenderableTagValue = TagValue


@dataclass(frozen=True)
class PhaseOneMakerPayload:
    offset: int
    data: bytes


def is_phaseone_iiq_prefix(prefix: bytes, path: Path) -> bool:
    """Structural check for TIFF-shaped IIQ files with a Phase One maker block."""
    if path.suffix.lower() != ".iiq":
        return False
    try:
        maker_payload_from_tiff(prefix)
    except ValueError:
        return False
    return True


def build_phaseone_iiq_read_graph_from_file(path: Path, source_file: str) -> ReadGraph:
    data = read_public_document_payload(path)
    if data is None:
        return oversized_public_payload_graph(source_file, format_name="Phase One IIQ")
    return build_phaseone_iiq_read_graph(data, source_file, path=path)


def build_phaseone_iiq_read_graph(
    data: bytes,
    source_file: str,
    *,
    path: Path | None = None,
) -> ReadGraph:
    diagnostics: list[str] = []
    tags: list[ReadTag] = []

    if path is not None:
        try:
            add_tags(
                tags,
                normalize_tag_map(read_system_tags(path, source_file)),
                system_provenance(),
                {},
            )
        except OSError as exc:
            diagnostics.append(str(exc))

    tags.extend(_file_tags())
    try:
        header = parse_tiff_header(data)
        tags.append(
            _tag(
                "ExifByteOrder",
                header.byte_order,
                "File",
                "Image::ExifTool::Exif::Main",
                "ExifByteOrder",
                (PHASEONE_IIQ_SOURCE,),
            )
        )
        _add_tiff_tags(tags, data, "IFD0", read_ifd0_values(data), IFD0_TAGS)
        _add_tiff_tags(tags, data, "ExifIFD", read_exif_ifd_values(data), EXIF_IFD_TAGS)
        _add_supplemental_tiff_tags(tags, data, header.endian)
        try:
            _add_tiff_tags(tags, data, "IFD1", read_ifd1_values(data), IFD1_TAGS)
        except ValueError as exc:
            diagnostics.append(f"PhaseOne IIQ package-local reader diagnostic: {exc}")
        maker_payload = maker_payload_from_tiff(data)
    except ValueError as exc:
        diagnostics.append(f"PhaseOne IIQ package-local reader status: unsupported: {exc}")
        return _graph(source_file, tags, diagnostics)

    plan = build_phaseone_transaction_plan(maker_payload.data, allow_output_emission=True)
    diagnostics.extend(
        f"PhaseOne package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    )
    if plan.status != "planned":
        diagnostics.insert(0, f"PhaseOne package-local reader status: {plan.status}")
        return _graph(source_file, tags, diagnostics)

    skipped_unknown = 0
    for field in plan.fields:
        if field.route == "sensor_calibration_subdirectory":
            if field.sensor_calibration is not None:
                skipped_unknown += _add_phaseone_fields(tags, field.sensor_calibration.fields)
            continue
        if field.value_class == "read_only_image_data":
            diagnostics.append(
                "PhaseOne package-local reader diagnostic: raw_image_payload_skipped: "
                f"{field.tag_name} bytes are deferred like PhaseOne.pm ImageDataHash/Binary "
                "handling and are not loaded into public output."
            )
            continue
        if _field_is_hidden_or_unknown(field):
            skipped_unknown += 1
            continue
        _add_phaseone_field(tags, field)

    binary_fields = tuple(
        field
        for field in plan.fields
        if field.value_class == "binary_source_value"
        and field.tag_name in _SUPPORTED_MAKER_BINARY_TAGS
    )
    if binary_fields:
        diagnostics.append(
            "PhaseOne package-local reader diagnostic: binary_payloads_summarized: "
            + ", ".join(
                f"{field.tag_name}={_phaseone_binary_summary_size(field)} bytes"
                for field in binary_fields
            )
        )

    if skipped_unknown:
        diagnostics.append(
            "PhaseOne package-local reader diagnostic: hidden_unknown_fields_skipped: "
            f"{skipped_unknown}"
        )
    diagnostics.append(
        "PhaseOne IIQ package-local reader diagnostic: bounded_tiff_and_phaseone_ifd_slice"
    )
    return _graph(source_file, tags, diagnostics)


def maker_payload_from_tiff(data: bytes) -> PhaseOneMakerPayload:
    header = parse_tiff_header(data)
    ifd0 = parse_ifd(data, header.first_ifd_offset, header.endian)
    exif_ifd_offset = _int_entry_value(data, ifd0, _EXIF_IFD_POINTER, header.endian)
    if exif_ifd_offset is None:
        raise ValueError("IFD0 does not contain an ExifIFD pointer.")
    exif_ifd = parse_ifd(data, exif_ifd_offset, header.endian)
    maker_entry = next(
        (entry for entry in exif_ifd.entries if entry.tag_id == _MAKER_NOTE_TAG), None
    )
    if maker_entry is None:
        raise ValueError("ExifIFD does not contain a Phase One MakerNote pointer.")
    maker_offset = maker_entry.value_offset
    if maker_entry.count > len(data) or maker_offset + maker_entry.count > len(data):
        raise ValueError("Phase One MakerNote payload is truncated.")
    payload = data[maker_offset : maker_offset + maker_entry.count]
    if not _is_phaseone_maker_header(payload[:12]):
        raise ValueError("MakerNote payload does not match PhaseOne.pm header gates.")
    return PhaseOneMakerPayload(maker_offset, payload)


def _int_entry_value(data: bytes, ifd: Ifd, tag_id: int, endian: Endian) -> int | None:
    entry = next((candidate for candidate in ifd.entries if candidate.tag_id == tag_id), None)
    if entry is None:
        return None
    value = read_entry_value(data, entry, endian)
    return value if isinstance(value, int) else None


def _is_phaseone_maker_header(header: bytes) -> bool:
    return (header.startswith(b"IIII") and header[5:8] == b"waR") or (
        header.startswith(b"MMMM") and header[4:7] == b"Raw"
    )


def _add_tiff_tags(
    tags: list[ReadTag],
    data: bytes,
    group: str,
    values: JsonObject,
    tag_names: dict[int, str],
) -> None:
    names_to_ids = {name: f"{tag_id}" for tag_id, name in tag_names.items()}
    for name, value in normalize_tag_map(values).items():
        scalar_value = _phaseone_scalar_tag_value(value)
        if scalar_value is None:
            continue
        tags.append(
            _tag(
                name,
                scalar_value,
                group,
                "Image::ExifTool::Exif::Main",
                names_to_ids.get(name, name),
                (PHASEONE_IIQ_SOURCE,),
                family_2_group=_tiff_family_2_group(name),
            )
        )


def _add_supplemental_tiff_tags(tags: list[ReadTag], data: bytes, endian: Endian) -> None:
    header = parse_tiff_header(data)
    ifd0 = parse_ifd(data, header.first_ifd_offset, endian)
    _add_supplemental_ifd_entries(
        tags,
        data,
        "IFD0",
        ifd0,
        _PHASEONE_SUPPLEMENTAL_IFD0_TAGS,
        endian,
    )
    exif_ifd_offset = _int_entry_value(data, ifd0, _EXIF_IFD_POINTER, endian)
    if exif_ifd_offset is not None:
        exif_ifd = parse_ifd(data, exif_ifd_offset, endian)
        _add_supplemental_ifd_entries(
            tags,
            data,
            "ExifIFD",
            exif_ifd,
            _PHASEONE_SUPPLEMENTAL_EXIF_IFD_TAGS,
            endian,
        )
    if ifd0.next_ifd_offset:
        ifd1 = parse_ifd(data, ifd0.next_ifd_offset, endian)
        _add_supplemental_ifd_entries(
            tags,
            data,
            "IFD1",
            ifd1,
            _PHASEONE_SUPPLEMENTAL_IFD1_TAGS,
            endian,
        )


def _add_supplemental_ifd_entries(
    tags: list[ReadTag],
    data: bytes,
    group: str,
    ifd: Ifd,
    tag_names: dict[int, str],
    endian: Endian,
) -> None:
    for entry in ifd.entries:
        name = tag_names.get(entry.tag_id)
        if name is None:
            continue
        value = _print_supplemental_tiff_value(name, read_entry_value(data, entry, endian))
        scalar_value = _phaseone_scalar_tag_value(value)
        if scalar_value is None:
            continue
        tags.append(
            _tag(
                name,
                scalar_value,
                group,
                "Image::ExifTool::Exif::Main",
                f"{entry.tag_id}",
                (PHASEONE_IIQ_SOURCE,),
                family_2_group=_tiff_family_2_group(name),
            )
        )


def _print_supplemental_tiff_value(name: str, value: TiffValue) -> PhaseOneRenderableTagValue:
    if isinstance(value, list):
        return [str(item) for item in value]
    if name == "SubfileType" and isinstance(value, int):
        return _TIFF_SUBFILE_TYPE_PRINT.get(value, value)
    if name == "PhotometricInterpretation" and isinstance(value, int):
        return _TIFF_PHOTOMETRIC_PRINT.get(value, value)
    if name == "PlanarConfiguration" and isinstance(value, int):
        return _TIFF_PLANAR_CONFIGURATION_PRINT.get(value, value)
    if name == "LightSource" and isinstance(value, int):
        return _TIFF_LIGHT_SOURCE_PRINT.get(value, value)
    printed = print_value(name, value)
    if isinstance(printed, str | int | float | bool) or printed is None:
        return printed
    if isinstance(printed, list) and all(isinstance(item, str | int) for item in printed):
        return [str(item) for item in printed]
    return None


def _phaseone_scalar_tag_value(value: PhaseOneRenderableTagValue) -> PhaseOneScalarTagValue:
    if isinstance(value, BinaryTagValue | BinaryTagListValue):
        return None
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return value


def _file_tags() -> list[ReadTag]:
    return [
        _tag(
            "FileType", "IIQ", "File", "Image::ExifTool::File", "FileType", (PHASEONE_FILE_SOURCE,)
        ),
        _tag(
            "FileTypeExtension",
            "iiq",
            "File",
            "Image::ExifTool::File",
            "FileTypeExtension",
            (PHASEONE_FILE_SOURCE,),
        ),
        _tag(
            "MIMEType",
            "image/x-raw",
            "File",
            "Image::ExifTool::File",
            "MIMEType",
            (PHASEONE_FILE_SOURCE,),
        ),
    ]


def _add_phaseone_fields(tags: list[ReadTag], fields: tuple[PhaseOneFieldPlan, ...]) -> int:
    skipped_unknown = 0
    for field in fields:
        if _field_is_hidden_or_unknown(field):
            skipped_unknown += 1
            continue
        _add_phaseone_field(tags, field)
    return skipped_unknown


def _add_phaseone_field(tags: list[ReadTag], field: PhaseOneFieldPlan) -> None:
    if field.tag_name in _EXPOSED_MAKER_BINARY_PAYLOAD_TAGS:
        tags.append(_phaseone_field_tag(field, _phaseone_binary_tag_value(field)))
        return
    if field.tag_name in _SUPPORTED_MAKER_BINARY_TAGS:
        summary = _binary_summary(_phaseone_binary_summary_size(field))
        tags.append(_phaseone_field_tag(field, summary))
        return
    rendered = _render_phaseone_field(field)
    if rendered is not None:
        tags.append(_phaseone_field_tag(field, rendered))


def _field_is_hidden_or_unknown(field: PhaseOneFieldPlan) -> bool:
    return field.is_unknown or field.value_class in {
        "hidden_unknown_source_value",
        "unknown_preserved",
    }


def _phaseone_field_tag(field: PhaseOneFieldPlan, value: TagValue) -> ReadTag:
    return _tag(
        field.tag_name,
        value,
        "PhaseOne",
        "Image::ExifTool::PhaseOne::Main"
        if field.table_kind == "main"
        else "Image::ExifTool::PhaseOne::SensorCalibration",
        str(field.tag_id),
        field.evidence_ids,
        family_0_group="MakerNotes",
        family_1_group="PhaseOne",
        family_2_group=field.group_2,
        duplicate_instance_ordinal=field.index,
    )


def _phaseone_binary_tag_value(field: PhaseOneFieldPlan) -> BinaryTagValue:
    return BinaryTagValue(
        _phaseone_binary_output_data(field),
        file_extension="txt",
    )


def _phaseone_binary_output_data(field: PhaseOneFieldPlan) -> bytes:
    if field.format_name == "undef":
        return field.raw_payload
    value = field.raw_value
    if isinstance(value, tuple):
        return " ".join(_format_number(item) for item in value).encode()
    if isinstance(value, str):
        return value.encode()
    return field.raw_payload


def _binary_summary(byte_count: int) -> str:
    return f"(Binary data {byte_count} bytes)"


def _render_phaseone_field(field: PhaseOneFieldPlan) -> str | int | float | None:
    value = field.raw_value
    if isinstance(value, bytes):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, float | int):
        scalar: int | float = value
    elif isinstance(value, tuple) and len(value) == 1:
        scalar = value[0]
    elif isinstance(value, tuple):
        if field.tag_name in _MATRIX_TAGS:
            return " ".join(f"{float(item):.3f}" for item in value)
        if field.tag_name in _LINEARIZATION_TAGS:
            return " ".join(f"{float(item):.5g}" for item in value)
        return " ".join(_format_number(item) for item in value)
    else:
        return None

    if field.tag_name == "CameraOrientation" and isinstance(scalar, int):
        return {
            0: "Horizontal (normal)",
            1: "Rotate 90 CW",
            2: "Rotate 270 CW",
            3: "Rotate 180",
        }.get(scalar & 0x03, scalar & 0x03)
    if field.tag_name == "RawFormat" and isinstance(scalar, int):
        return {
            0: "Uncompressed",
            1: "RAW 1",
            2: "RAW 2",
            3: "IIQ L",
            5: "IIQ S",
            6: "IIQ Sv2",
            8: "IIQ L16",
        }.get(scalar, scalar)
    if field.tag_name in {"SensorTemperature", "SensorTemperature2"}:
        return f"{float(scalar):.2f} C"
    if field.tag_name == "DateTimeOriginal" and isinstance(scalar, int):
        return datetime.fromtimestamp(scalar, tz=UTC).strftime("%Y:%m:%d %H:%M:%S")
    if field.tag_name == "ShutterSpeedValue":
        seconds = 2 ** (-float(scalar)) if abs(float(scalar)) < 100 else 0
        return _exposure_time(seconds)
    if field.tag_name in {"ApertureValue", "MaxApertureValue", "MinApertureValue"}:
        return round(2 ** (float(scalar) / 2), 1)
    if field.tag_name == "ExposureCompensation":
        return f"{float(scalar):.3f}"
    if field.tag_name == "FocalLength":
        return f"{float(scalar):.1f} mm"
    if field.tag_name == "SequenceKind" and isinstance(scalar, int):
        return {
            0: "Bracketing: Shutter Speed",
            1: "Bracketing: Aperture",
            2: "Bracketing: ISO",
            3: "Hyperfocal",
            4: "Time Lapse",
            5: "HDR",
            6: "Focus Stacking",
        }.get(scalar, scalar)
    return scalar


def _phaseone_binary_summary_size(field: PhaseOneFieldPlan) -> int:
    if field.format_name == "undef":
        return len(field.raw_payload)
    value = field.raw_value
    if isinstance(value, tuple):
        return len(" ".join(_format_number(item) for item in value).encode())
    if isinstance(value, str):
        return len(value.encode())
    return len(field.raw_payload)


def _format_number(value: int | float) -> str:
    if isinstance(value, float):
        return f"{value:.3f}" if not value.is_integer() else str(int(value))
    return str(value)


def _exposure_time(seconds: float) -> str | int:
    if seconds <= 0:
        return 0
    if seconds < 1:
        denominator = round(1 / seconds)
        if math.isclose(seconds, 1 / denominator, rel_tol=0.02):
            return f"1/{denominator}"
    return f"{seconds:.6g}"


def _tiff_family_2_group(name: str) -> str:
    if name in {"Make", "Model", "LightSource", "FocalLength", "WhiteBalance", "LensModel"}:
        return "Camera"
    if name in {"DateTimeOriginal", "CreateDate", "ModifyDate"}:
        return "Time"
    return "Image"


def _tag(
    name: str,
    value: TagValue,
    group: str,
    table_name: str,
    tag_id: str | None,
    evidence_ids: tuple[str, ...],
    *,
    family_0_group: str | None = None,
    family_1_group: str | None = None,
    family_2_group: str | None = None,
    duplicate_instance_ordinal: int | None = None,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group=group,
            table_name=table_name,
            tag_id=tag_id,
            source=_evidence_anchor_text(evidence_ids),
            family_0_group=family_0_group or group,
            family_1_group=family_1_group or group,
            family_2_group=family_2_group or _default_family_2_group(group),
            duplicate_instance_ordinal=duplicate_instance_ordinal,
        ),
        schema=None,
    )


def _graph(source_file: str, tags: list[ReadTag], diagnostics: list[str]) -> ReadGraph:
    import time

    return ReadGraph(
        schema_version=1,
        generated_at_epoch=int(time.time()),
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )


def _evidence_anchor_text(evidence_ids: tuple[str, ...]) -> str:
    reference = evidence_ids[0] if evidence_ids else PHASEONE_PROCESS_SOURCE
    return reference


def _default_family_2_group(group: str) -> str:
    if group in {"File", "System"}:
        return "Other"
    return group
