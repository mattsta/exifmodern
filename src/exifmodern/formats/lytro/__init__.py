"""Lytro LFP metadata transaction planning public API."""

import math
from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
from exifmodern.formats.lytro.metadata_transaction_plan import (
    LFP_FILE_HEADER_SIZE,
    LFP_MAX_READ_PAYLOAD_SIZE,
    LFP_SEGMENT_HEADER_SIZE,
    LFP_SEGMENT_ID_SIZE,
    LytroMetadataTagPlan,
    LytroMetadataTransactionPlan,
    LytroRewriteRequest,
    build_lytro_metadata_transaction_plan,
)
from exifmodern.formats.lytro.reader import LytroReaderResult, read_lytro_lfp_scalars
from exifmodern.json_types import JsonValue
from exifmodern.read_graph import (
    BinaryTagListValue,
    BinaryTagValue,
    ReadGraph,
    ReadTag,
)
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = (
    "LytroMetadataTransactionPlan",
    "LytroReaderResult",
    "LytroRewriteRequest",
    "build_lytro_metadata_transaction_plan",
    "build_lytro_read_graph",
    "invoke_lytro",
    "read_lytro_lfp_scalars",
)
type LytroReadScalar = str | int | float | bool | None
type LytroReadArray = list[LytroReadScalar]
type LytroReadValue = bytes | LytroReadScalar | LytroReadArray


def build_lytro_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_lytro_metadata_transaction_plan(data)
    diagnostics: list[str] = [
        f"Lytro package-local reader gate: {gate.code}" for gate in plan.output_emission_gates
    ]
    diagnostics.extend(
        f"Lytro package-local reader blocker: {blocker.code}: {blocker.reason}"
        for blocker in plan.blockers
    )
    tags: list[ReadTag] = [
        ReadTag(
            name="FileType",
            value="LFP",
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id="FileType",
                references=(),
            ),
            schema=None,
        ),
        ReadTag(
            name="FileTypeExtension",
            value="lfp",
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id="FileTypeExtension",
                references=(),
            ),
            schema=None,
        ),
        ReadTag(
            name="MIMEType",
            value="image/x-lytro-lfp",
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id="MIMEType",
                references=(),
            ),
            schema=None,
        ),
    ]
    json_metadata_values: list[BinaryTagValue] = []
    for segment in plan.segments:
        if segment.kind == "json_metadata":
            json_metadata_values.append(
                BinaryTagValue(
                    data[segment.payload_range[0] : segment.payload_range[1]],
                    media_type="application/json",
                    file_extension="json",
                )
            )
        elif segment.kind == "embedded_image":
            tags.append(
                ReadTag(
                    name="EmbeddedImage",
                    value=BinaryTagValue(
                        data[segment.payload_range[0] : segment.payload_range[1]],
                        media_type="image/jpeg",
                        file_extension="jpg",
                    ),
                    provenance=_provenance(
                        group="Preview",
                        table_name="Image::ExifTool::Lytro::Main",
                        tag_id="EmbeddedImage",
                        references=(),
                        duplicate_instance_ordinal=segment.index,
                    ),
                    schema=None,
                )
            )
    if json_metadata_values:
        tags.append(
            ReadTag(
                name="JSONMetadata",
                value=BinaryTagListValue(tuple(json_metadata_values)),
                provenance=_provenance(
                    group="Lytro",
                    table_name="Image::ExifTool::Lytro::Main",
                    tag_id="JSONMetadata",
                    references=(),
                ),
                schema=None,
            )
        )
    emitted_paths: set[str] = set()
    for ordinal, tag in enumerate(plan.metadata_tags):
        if tag.raw_path in emitted_paths:
            continue
        same_path_tags = [
            candidate for candidate in plan.metadata_tags if candidate.raw_path == tag.raw_path
        ]
        emitted_paths.add(tag.raw_path)
        rendered: JsonValue
        if tag.is_list and len(same_path_tags) > 1:
            rendered = [
                candidate.print_value
                if candidate.print_value is not None
                else candidate.converted_value
                for candidate in same_path_tags
            ]
        else:
            selected_tag = same_path_tags[-1]
            rendered = (
                selected_tag.print_value
                if selected_tag.print_value is not None
                else selected_tag.converted_value
            )
        rendered_value = _lytro_read_value(rendered)
        tags.append(
            ReadTag(
                name=tag.tag_name,
                value=_read_value(rendered_value),
                provenance=_provenance(
                    group="Lytro",
                    table_name="Image::ExifTool::Lytro::Main",
                    tag_id=tag.raw_path,
                    references=(),
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    tags.extend(_lytro_composite_tags(tags, plan.metadata_tags))
    return _graph(source_file, tags, diagnostics)


def _lytro_read_value(value: JsonValue) -> LytroReadValue:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        values: LytroReadArray = []
        for item in value:
            if isinstance(item, str | int | float | bool) or item is None:
                values.append(item)
            else:
                values.append(str(item))
        return values
    return str(value)


def _lytro_composite_tags(
    tags: list[ReadTag],
    metadata_tags: tuple[LytroMetadataTagPlan, ...],
) -> list[ReadTag]:
    values = _lytro_tag_values(tags)
    width = _int_value(values.get("ImageWidth"))
    height = _int_value(values.get("ImageHeight"))
    aperture = _number_value(values.get("FNumber")) or _metadata_number_value(
        metadata_tags,
        "FNumber",
    )
    aperture_for_calculation = _metadata_number_value(metadata_tags, "FNumber") or aperture
    focal_length = _metadata_number_value(metadata_tags, "FocalLength") or _length_mm_value(
        values.get("FocalLength")
    )
    focal_plane_x_resolution = _metadata_number_value(
        metadata_tags,
        "FocalPlaneXResolution",
    ) or _number_value(values.get("FocalPlaneXResolution"))
    exposure_time = _exposure_seconds(values.get("ExposureTime"))
    iso = _int_value(values.get("ISO"))
    composite_values: list[tuple[str, LytroReadValue]] = []
    if aperture is not None:
        composite_values.append(("Aperture", aperture))
    if width is not None and height is not None:
        composite_values.append(("ImageSize", f"{width}x{height}"))
        composite_values.append(("Megapixels", round(width * height / 1_000_000, 1)))
    scale_factor: float | None = None
    circle_of_confusion: float | None = None
    if (
        width is not None
        and height is not None
        and focal_plane_x_resolution is not None
        and focal_plane_x_resolution > 0
    ):
        sensor_width = width * 25.4 / focal_plane_x_resolution
        sensor_height = height * 25.4 / focal_plane_x_resolution
        sensor_diagonal = math.hypot(sensor_width, sensor_height)
        if 1 < sensor_diagonal < 100:
            scale_factor = math.hypot(36, 24) / sensor_diagonal
            circle_of_confusion = math.hypot(36, 24) / (scale_factor * 1440)
            composite_values.append(("ScaleFactor35efl", round(scale_factor, 1)))
    if exposure_time is not None:
        composite_values.append(("ShutterSpeed", _print_exposure_time(exposure_time)))
    if circle_of_confusion is not None:
        composite_values.append(("CircleOfConfusion", f"{circle_of_confusion:.3f} mm"))
    if focal_length is not None and scale_factor is not None and scale_factor > 0:
        fov = math.degrees(2 * math.atan2(36, 2 * focal_length * scale_factor))
        equivalent = focal_length * scale_factor
        composite_values.append(("FOV", f"{fov:.1f} deg"))
        composite_values.append(
            (
                "FocalLength35efl",
                f"{focal_length:.1f} mm (35 mm equivalent: {equivalent:.1f} mm)",
            )
        )
    elif focal_length is not None:
        composite_values.append(("FocalLength35efl", f"{focal_length:.1f} mm"))
    if (
        focal_length is not None
        and aperture_for_calculation is not None
        and circle_of_confusion is not None
        and aperture_for_calculation > 0
    ):
        hyperfocal = (
            focal_length * focal_length / (aperture_for_calculation * circle_of_confusion * 1000)
        )
        composite_values.append(("HyperfocalDistance", f"{hyperfocal:.2f} m"))
    if (
        aperture_for_calculation is not None
        and exposure_time is not None
        and exposure_time > 0
        and iso is not None
        and iso > 0
    ):
        light_value = math.log2(
            aperture_for_calculation * aperture_for_calculation * 100 / (exposure_time * iso)
        )
        composite_values.append(("LightValue", f"{light_value:.1f}"))
    return [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_provenance(
                group="Composite",
                table_name="Image::ExifTool::Composite",
                tag_id=f"Exif-{name}",
                references=(),
            ),
            schema=None,
        )
        for name, value in composite_values
    ]


def _lytro_tag_values(tags: list[ReadTag]) -> dict[str, LytroReadValue]:
    values: dict[str, LytroReadValue] = {}
    for tag in tags:
        if isinstance(tag.value, BinaryTagValue | BinaryTagListValue):
            continue
        if isinstance(tag.value, list):
            values[tag.name] = [item for item in tag.value]
        else:
            values[tag.name] = tag.value
    return values


def _metadata_number_value(
    metadata_tags: tuple[LytroMetadataTagPlan, ...],
    tag_name: str,
) -> float | None:
    for tag in reversed(metadata_tags):
        if tag.tag_name != tag_name:
            continue
        number = _json_number_value(tag.converted_value)
        if number is not None:
            return number
    return None


def _json_number_value(value: JsonValue) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _int_value(value: LytroReadValue | None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _number_value(value: LytroReadValue | None) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.removesuffix(" mm").removesuffix(" C"))
        except ValueError:
            return None
    return None


def _length_mm_value(value: LytroReadValue | None) -> float | None:
    if isinstance(value, str) and value.endswith(" mm"):
        try:
            return float(value.removesuffix(" mm"))
        except ValueError:
            return None
    return _number_value(value)


def _exposure_seconds(value: LytroReadValue | None) -> float | None:
    if isinstance(value, str) and "/" in value:
        numerator_text, denominator_text = value.split("/", 1)
        try:
            denominator = float(denominator_text)
            if denominator == 0:
                return None
            return float(numerator_text) / denominator
        except ValueError:
            return None
    return _number_value(value)


def _print_exposure_time(value: float) -> str:
    reciprocal = round(1 / value)
    if reciprocal > 1 and abs(value - (1 / reciprocal)) < 0.00001:
        return f"1/{reciprocal}"
    if value < 1:
        return f"{value:.3g}"
    return f"{value:.1f}"


def invoke_lytro(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_lytro_read_graph(_read_lytro_exiftool_payload(path, prefix), source_file)


def _read_lytro_exiftool_payload(path: Path, prefix: bytes) -> bytes:
    # Lytro.pm reads the fixed file header, then each segment header/id. Segment
    # payloads over 20 MB are skipped; smaller JSON/JPEG payloads are read.
    data = bytearray(prefix[:LFP_FILE_HEADER_SIZE])
    with path.open("rb") as file:
        if len(data) < LFP_FILE_HEADER_SIZE:
            file.seek(len(data))
            data.extend(file.read(LFP_FILE_HEADER_SIZE - len(data)))
        offset = LFP_FILE_HEADER_SIZE
        file.seek(offset)
        while True:
            header = file.read(LFP_SEGMENT_HEADER_SIZE)
            if not header:
                break
            data.extend(header)
            if len(header) != LFP_SEGMENT_HEADER_SIZE or not header.startswith(b"\x89LF"):
                break
            size = int.from_bytes(header[12:16], "big")
            if size & 0x80000000:
                break
            identifier = file.read(LFP_SEGMENT_ID_SIZE)
            data.extend(identifier)
            if len(identifier) != LFP_SEGMENT_ID_SIZE:
                break
            if size > LFP_MAX_READ_PAYLOAD_SIZE:
                break
            payload = file.read(size)
            data.extend(payload)
            if len(payload) != size:
                break
            pad = 16 - (size % 16)
            if pad != 16:
                padding = file.read(pad)
                data.extend(padding)
                if len(padding) != pad:
                    break
    return bytes(data)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="lytro",
        builder_ref="exifmodern.formats.lytro:invoke_lytro",
        patterns=(Pattern(0, b"\x89LFP\r\n\x1a\n"),),
    ),
)
