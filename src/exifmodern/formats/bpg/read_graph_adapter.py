"""BPG adapters for the shared read graph contract."""

from __future__ import annotations

import math
import time

from exifmodern.formats.bpg.image_transaction_plan import (
    BPG_EXTENSION_TABLE_SOURCE,
    BPG_MAIN_TABLE_SOURCE,
    BpgEvidenceId,
    BpgExtensionPlan,
    BpgImageTransactionPlan,
    build_bpg_image_transaction_plan,
)
from exifmodern.formats.bpg.nested_read import (
    BpgNestedPayloadExtraction,
    BpgNestedTag,
    extract_bpg_nested_payloads,
)
from exifmodern.read_graph import (
    BinaryTagValue,
    ReadGraph,
    ReadTag,
    TagProvenance,
    TagValue,
)

BPG_FILE_TYPE_SOURCE = "bpg.file_type"


def is_bpg_prefix(data: bytes) -> bool:
    """Return whether bytes satisfy ExifTool's BPG magic gate."""

    return len(data) >= 4 and data.startswith(b"BPG\xfb")


def build_bpg_read_graph(
    data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    plan = build_bpg_image_transaction_plan(data, allow_output_emission=True)
    return bpg_image_transaction_plan_to_read_graph(plan, data, source_file, generated_at_epoch)


def bpg_image_transaction_plan_to_read_graph(
    plan: BpgImageTransactionPlan,
    data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    tags: list[ReadTag] = []
    nested_records: tuple[BpgNestedPayloadExtraction, ...] = ()
    if plan.status == "planned":
        nested_records = extract_bpg_nested_payloads(plan, data)
        tags.extend(_file_type_tags())
        tags.extend(_header_tags(plan))
        tags.extend(_exiftool_warning_tags(plan.extensions))
        tags.extend(_binary_extension_tags(plan.extensions, data))
        tags.extend(_nested_payload_tags(nested_records))
        tags.extend(_composite_tags(tags))
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=tags,
        diagnostics=_diagnostics(plan, nested_records),
    )


def _file_type_tags() -> tuple[ReadTag, ...]:
    return (
        _file_tag("FileType", "BPG", "FileType"),
        _file_tag("FileTypeExtension", "bpg", "FileTypeExtension"),
        _file_tag("MIMEType", "image/bpg", "MIMEType"),
    )


def _header_tags(plan: BpgImageTransactionPlan) -> tuple[ReadTag, ...]:
    header = plan.header
    if header.descriptor is None:
        return ()
    return (
        _bpg_tag("PixelFormat", header.pixel_format_description, "4", BPG_MAIN_TABLE_SOURCE),
        _bpg_tag("Alpha", header.alpha_description, "4.1", BPG_MAIN_TABLE_SOURCE),
        _bpg_tag("BitDepth", header.bit_depth, "4.2", BPG_MAIN_TABLE_SOURCE),
        _bpg_tag("ColorSpace", header.color_space_description, "4.3", BPG_MAIN_TABLE_SOURCE),
        _bpg_tag("Flags", ", ".join(header.flag_descriptions), "4.4", BPG_MAIN_TABLE_SOURCE),
        _bpg_tag("ImageWidth", header.image_width, "6", BPG_MAIN_TABLE_SOURCE),
        _bpg_tag("ImageHeight", header.image_height, "7", BPG_MAIN_TABLE_SOURCE),
        _bpg_tag("ImageLength", header.image_length, "8", BPG_MAIN_TABLE_SOURCE),
    )


def _binary_extension_tags(extensions: tuple[BpgExtensionPlan, ...], data: bytes) -> list[ReadTag]:
    tags: list[ReadTag] = []
    for extension in extensions:
        if extension.kind not in {"thumbnail_bpg", "animation_control"}:
            continue
        payload = data[extension.logical_payload_offset : extension.logical_payload_range[1]]
        tags.append(
            _bpg_tag(
                extension.name,
                BinaryTagValue(payload),
                str(extension.type_code),
                BPG_EXTENSION_TABLE_SOURCE,
            )
        )
    return tags


def _exiftool_warning_tags(extensions: tuple[BpgExtensionPlan, ...]) -> list[ReadTag]:
    tags: list[ReadTag] = []
    for extension in extensions:
        if not extension.ignored_exif_padding:
            continue
        tags.append(
            ReadTag(
                name="Warning",
                value="[minor] Ignored extra byte at start of EXIF extension",
                provenance=TagProvenance(
                    group="ExifTool",
                    table_name="Image::ExifTool",
                    tag_id="Warning",
                    source="lib/Image/ExifTool/BPG.pm:200:ProcessBPG EXIF padding warning",
                    family_0_group="ExifTool",
                    family_1_group="ExifTool",
                    family_2_group="Other",
                ),
                schema=None,
            )
        )
    return tags


def _nested_payload_tags(records: tuple[BpgNestedPayloadExtraction, ...]) -> list[ReadTag]:
    return [
        _nested_tag_to_read_tag(tag)
        for record in records
        if record.status == "extracted"
        for tag in record.tags
    ]


def _composite_tags(tags: list[ReadTag]) -> list[ReadTag]:
    values: dict[str, TagValue] = {}
    width = _numeric_tag_value(tags, "File", "ImageWidth")
    height = _numeric_tag_value(tags, "File", "ImageHeight")
    if width is not None and height is not None:
        values["ImageSize"] = f"{int(width)}x{int(height)}"
        pixels = width * height / 1_000_000
        values["Megapixels"] = round(pixels, 1 if pixels >= 1 else 6)
    aperture = _numeric_tag_value(tags, "ExifIFD", "FNumber")
    if aperture is not None:
        values["Aperture"] = aperture
    shutter_speed = _string_tag_value(tags, "ExifIFD", "ExposureTime")
    if shutter_speed is not None:
        values["ShutterSpeed"] = shutter_speed
    iso = _numeric_tag_value(tags, "ExifIFD", "ISO")
    shutter_seconds = _exposure_seconds(shutter_speed)
    if aperture is not None and iso is not None and shutter_seconds is not None:
        light_value = (2 * math.log2(aperture)) - math.log2(shutter_seconds)
        light_value -= math.log2(iso / 100)
        values["LightValue"] = round(light_value, 1)
    values.update(_lens_composite_values(tags, aperture))
    return [_composite_tag(name, value) for name, value in values.items()]


def _lens_composite_values(tags: list[ReadTag], aperture: float | None) -> dict[str, TagValue]:
    focal_length = _length_mm(_string_tag_value(tags, "ExifIFD", "FocalLength"))
    if focal_length is None:
        return {}
    values: dict[str, TagValue] = {"FocalLength35efl": f"{focal_length:.1f} mm"}
    scale_factor = _scale_factor_35efl(tags)
    if scale_factor is None:
        return values
    equivalent = focal_length * scale_factor
    circle = math.hypot(36, 24) / (scale_factor * 1440)
    fov = math.degrees(2 * math.atan(36 / (2 * equivalent)))
    values.update(
        {
            "ScaleFactor35efl": round(scale_factor, 1),
            "CircleOfConfusion": f"{circle:.3f} mm",
            "FOV": f"{fov:.1f} deg",
            "FocalLength35efl": (f"{focal_length:.1f} mm (35 mm equivalent: {equivalent:.1f} mm)"),
        }
    )
    if aperture is not None and aperture > 0:
        hyperfocal = (focal_length * focal_length) / (aperture * circle * 1000)
        values["HyperfocalDistance"] = f"{hyperfocal:.2f} m"
    return values


def _scale_factor_35efl(tags: list[ReadTag]) -> float | None:
    focal_plane_x_resolution = _numeric_tag_value(tags, "ExifIFD", "FocalPlaneXResolution")
    focal_plane_y_resolution = _numeric_tag_value(tags, "ExifIFD", "FocalPlaneYResolution")
    exif_width = _numeric_tag_value(tags, "ExifIFD", "ExifImageWidth")
    exif_height = _numeric_tag_value(tags, "ExifIFD", "ExifImageHeight")
    unit = _string_tag_value(tags, "ExifIFD", "FocalPlaneResolutionUnit")
    if (
        focal_plane_x_resolution is None
        or focal_plane_y_resolution is None
        or exif_width is None
        or exif_height is None
        or focal_plane_x_resolution <= 0
        or focal_plane_y_resolution <= 0
    ):
        return None
    unit_mm = 10.0 if unit == "cm" else 25.4
    focal_plane_width = exif_width * unit_mm / focal_plane_x_resolution
    focal_plane_height = exif_height * unit_mm / focal_plane_y_resolution
    diagonal = math.hypot(focal_plane_width, focal_plane_height)
    if diagonal <= 1 or diagonal >= 100:
        return None
    return math.hypot(36, 24) / diagonal


def _numeric_tag_value(tags: list[ReadTag], group: str, name: str) -> float | None:
    value = _tag_value(tags, group, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _string_tag_value(tags: list[ReadTag], group: str, name: str) -> str | None:
    value = _tag_value(tags, group, name)
    return value if isinstance(value, str) else None


def _tag_value(tags: list[ReadTag], group: str, name: str) -> TagValue | None:
    for tag in tags:
        if tag.provenance.group == group and tag.name == name:
            return tag.value
    return None


def _length_mm(value: str | None) -> float | None:
    if value is None or not value.endswith(" mm"):
        return None
    try:
        return float(value.removesuffix(" mm"))
    except ValueError:
        return None


def _exposure_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        if numerator.isdecimal() and denominator.isdecimal() and int(denominator) != 0:
            return int(numerator) / int(denominator)
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _nested_tag_to_read_tag(tag: BpgNestedTag) -> ReadTag:
    return ReadTag(
        name=tag.name,
        value=tag.value,
        provenance=TagProvenance(
            group=tag.group,
            table_name=tag.table_name,
            tag_id=tag.name,
            source=tag.source,
            family_0_group=_nested_family_0_group(tag),
            family_1_group=tag.group,
            family_2_group=_nested_family_2_group(tag),
        ),
        schema=None,
    )


def _file_tag(name: str, value: TagValue, tag_id: str) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="File",
            table_name="Image::ExifTool::File",
            tag_id=tag_id,
            source=BPG_FILE_TYPE_SOURCE,
            family_0_group="File",
            family_1_group="File",
            family_2_group="Other",
        ),
        schema=None,
    )


def _bpg_tag(
    name: str,
    value: TagValue,
    tag_id: str,
    evidence_id: BpgEvidenceId,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="File",
            table_name="Image::ExifTool::BPG::Main",
            tag_id=tag_id,
            source=evidence_id,
            family_0_group="File",
            family_1_group="File",
            family_2_group="Image",
        ),
        schema=None,
    )


def _composite_tag(name: str, value: TagValue) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="Composite",
            table_name="Image::ExifTool::Exif::Composite",
            tag_id=f"Exif-{name}",
            source="lib/Image/ExifTool/Exif.pm:4747-4865:Exif::Composite",
            family_0_group="Composite",
            family_1_group="Composite",
            family_2_group="Image" if name in {"ImageSize", "Megapixels"} else "Camera",
        ),
        schema=None,
    )


def _diagnostics(
    plan: BpgImageTransactionPlan,
    nested_records: tuple[BpgNestedPayloadExtraction, ...],
) -> list[str]:
    diagnostics = [
        f"BPG package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
        if gate.code != "non_mutating_plan_requires_explicit_emission"
    ]
    for extension in plan.extensions:
        if extension.ignored_exif_padding:
            diagnostics.append(
                "BPG package-local reader warning: ignored_extra_exif_padding: "
                "ProcessBPG skips one leading byte before II/MM in EXIF extensions."
            )
        if extension.kind in {"exif", "icc_profile", "xmp"}:
            record = _nested_record_for_extension(nested_records, extension.index)
            if record is None:
                continue
            if record.status == "extracted":
                diagnostics.append(
                    "BPG package-local reader diagnostic: nested_metadata_extracted: "
                    f"{extension.name}; "
                    f"type={extension.type_code}; "
                    f"payload_offset={extension.payload_offset}; "
                    f"payload_length={extension.payload_length}; "
                    f"logical_payload_offset={extension.logical_payload_offset}; "
                    f"logical_payload_length={extension.logical_payload_length}; "
                    f"target_table={record.target_table}; "
                    f"tag_count={len(record.tags)}"
                )
                continue
            diagnostics.append(
                "BPG package-local reader diagnostic: nested_metadata_unsupported_payload: "
                f"{extension.name}; "
                f"type={extension.type_code}; "
                f"payload_offset={extension.payload_offset}; "
                f"payload_length={extension.payload_length}; "
                f"logical_payload_offset={extension.logical_payload_offset}; "
                f"logical_payload_length={extension.logical_payload_length}; "
                f"target_table={record.target_table}; "
                f"reason={record.reason}"
            )
    if plan.status != "planned":
        diagnostics.insert(0, f"BPG package-local reader status: {plan.status}")
    if not plan.extensions:
        diagnostics.append(
            "BPG package-local reader diagnostic: hevc_payload_preserved: "
            "BPG.pm reads metadata only; HEVC image payload decoding is outside "
            "the metadata reader surface."
        )
    return diagnostics


def _nested_record_for_extension(
    records: tuple[BpgNestedPayloadExtraction, ...],
    extension_index: int,
) -> BpgNestedPayloadExtraction | None:
    for record in records:
        if record.extension_index == extension_index:
            return record
    return None


def _nested_family_0_group(tag: BpgNestedTag) -> str | None:
    if tag.table_name.startswith("Image::ExifTool::XMP::"):
        return "XMP"
    if tag.table_name.startswith("Image::ExifTool::Exif::"):
        if tag.group == "File":
            return "File"
        return "EXIF"
    if tag.table_name.startswith("Image::ExifTool::GPS::"):
        return "EXIF"
    return tag.group


def _nested_family_2_group(tag: BpgNestedTag) -> str | None:
    if tag.table_name.startswith("Image::ExifTool::XMP::"):
        return _xmp_family_2_group(tag)
    if tag.table_name.startswith("Image::ExifTool::Exif::") or tag.table_name.startswith(
        "Image::ExifTool::GPS::"
    ):
        return _exif_family_2_group(tag)
    return None


def _xmp_family_2_group(tag: BpgNestedTag) -> str | None:
    if tag.group == "XMP-x":
        return "Document"
    if tag.group == "XMP-xmp":
        if tag.name in {"CreateDate", "MetadataDate", "ModifyDate"}:
            return "Time"
        return "Image"
    if tag.group == "XMP-dc":
        if tag.name in {"Contributor", "Creator", "Publisher", "Rights", "Source"}:
            return "Author"
        if tag.name == "Date":
            return "Time"
        if tag.name in {"Description", "Format", "Identifier", "Subject", "Title", "Type"}:
            return "Image"
        return "Other"
    return None


def _exif_family_2_group(tag: BpgNestedTag) -> str | None:
    if tag.name == "ExifByteOrder":
        return "Image"
    if tag.name in {"Artist", "Copyright"}:
        return "Author"
    if tag.name in {"CreateDate", "DateTimeOriginal", "ModifyDate", "GPSDateTime"}:
        return "Time"
    if tag.name in {"GPSAltitude", "GPSLatitude", "GPSLongitude"}:
        return "Location"
    return "Image"
