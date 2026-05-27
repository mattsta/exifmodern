"""PGF transaction planning public API."""

from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
from exifmodern.formats.pgf.image_transaction_plan import (
    PGF_EMBEDDED_METADATA_SOURCE,
    PNG_SIGNATURE,
    PgfImageTransactionPlan,
    PgfRewriteRequest,
    build_pgf_image_transaction_plan,
)
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = (
    "PgfImageTransactionPlan",
    "PgfRewriteRequest",
    "build_pgf_image_transaction_plan",
    "build_pgf_read_graph",
    "invoke_pgf",
)

type PgfGraphValue = str | int | float | bool | None

PNG_IHDR_SOURCE = "png_ihdr"


def _add(
    tags: list[ReadTag],
    plan: PgfImageTransactionPlan,
    name: str,
    value: PgfGraphValue,
) -> None:
    if value is None:
        return
    tags.append(
        ReadTag(
            name=name,
            value=_read_value(value if isinstance(value, str | int | float | bool) else str(value)),
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::PGF::Main",
                tag_id=name,
                evidence_ids=plan.evidence_ids,
                duplicate_instance_ordinal=len(tags),
            ),
            schema=None,
        )
    )


def build_pgf_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_pgf_image_transaction_plan(data)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"PGF package-local reader status: {plan.status}")
    diagnostics.extend(
        f"PGF package-local reader gate: {gate.code}" for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = [
        _tag(
            "Warning",
            "[minor] Text/EXIF chunk(s) found after PGF IDAT (may be ignored by some readers)",
            "ExifTool",
            "Image::ExifTool::Extra",
            "Warning",
            (PGF_EMBEDDED_METADATA_SOURCE,),
        )
    ]
    tags.extend(
        (
            _tag(
                "FileType",
                "PGF",
                "File",
                "Image::ExifTool::PGF::Main",
                "FileType",
                plan.header_validation.evidence_ids,
            ),
            _tag(
                "FileTypeExtension",
                "pgf",
                "File",
                "Image::ExifTool::PGF::Main",
                "FileTypeExtension",
                plan.header_validation.evidence_ids,
            ),
            _tag(
                "MIMEType",
                "image/pgf",
                "File",
                "Image::ExifTool::PGF::Main",
                "MIMEType",
                plan.header_validation.evidence_ids,
            ),
        )
    )
    version = (
        f"0x{plan.header_validation.version:02x}"
        if plan.header_validation.version is not None
        else None
    )
    _add(tags, plan, "PGFVersion", version)
    _add(tags, plan, "ImageWidth", plan.image_geometry.image_width)
    _add(tags, plan, "ImageHeight", plan.image_geometry.image_height)
    _add(tags, plan, "PyramidLevels", plan.image_geometry.pyramid_levels)
    _add(tags, plan, "Quality", plan.compression.quality)
    _add(tags, plan, "BitsPerPixel", plan.sample_layout.bits_per_pixel)
    _add(tags, plan, "ColorComponents", plan.sample_layout.color_components)
    _add(tags, plan, "ColorMode", plan.sample_layout.color_mode_name)
    if plan.sample_layout.background_color is not None:
        _add(tags, plan, "BackgroundColor", _join_color(plan.sample_layout.background_color))
    tags.extend(_embedded_png_tags(plan))
    if plan.image_geometry.image_width is not None and plan.image_geometry.image_height is not None:
        width = plan.image_geometry.image_width
        height = plan.image_geometry.image_height
        tags.append(
            _tag(
                "ImageSize",
                f"{width}x{height}",
                "Composite",
                "Image::ExifTool::Composite",
                "ImageSize",
                plan.image_geometry.evidence_ids,
            )
        )
        tags.append(
            _tag(
                "Megapixels",
                width * height / 1_000_000,
                "Composite",
                "Image::ExifTool::Composite",
                "Megapixels",
                plan.image_geometry.evidence_ids,
            )
        )
    return _graph(source_file, tags, diagnostics)


def _embedded_png_tags(plan: PgfImageTransactionPlan) -> list[ReadTag]:
    metadata_range = plan.post_header.metadata_range
    if metadata_range is None or plan.post_header.metadata_kind != "embedded_png_metadata":
        return []
    start, end = metadata_range
    png_data = plan.source_data[start:end]
    if not png_data.startswith(PNG_SIGNATURE):
        return []
    tags: list[ReadTag] = []
    tags.extend(_png_header_tags(png_data))
    tags.extend(_png_chunk_tags(png_data))
    return tags


def _png_header_tags(png_data: bytes) -> list[ReadTag]:
    if len(png_data) < 33 or png_data[12:16] != b"IHDR":
        return []
    width = int.from_bytes(png_data[16:20], "big")
    height = int.from_bytes(png_data[20:24], "big")
    bit_depth = png_data[24]
    color_type = png_data[25]
    compression = png_data[26]
    filter_method = png_data[27]
    interlace = png_data[28]
    return [
        _png_tag("ImageWidth", width, "PNG"),
        _png_tag("ImageHeight", height, "PNG"),
        _png_tag("BitDepth", bit_depth, "PNG"),
        _png_tag("ColorType", _png_color_type(color_type), "PNG"),
        _png_tag("Compression", _png_compression(compression), "PNG"),
        _png_tag("Filter", _png_filter(filter_method), "PNG"),
        _png_tag("Interlace", _png_interlace(interlace), "PNG"),
    ]


def _png_chunk_tags(png_data: bytes) -> list[ReadTag]:
    srgb_tags: list[ReadTag] = []
    text_tags: list[ReadTag] = []
    phys_tags: list[ReadTag] = []
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(png_data):
        length = int.from_bytes(png_data[offset : offset + 4], "big")
        chunk_type = png_data[offset + 4 : offset + 8]
        payload_start = offset + 8
        payload_end = payload_start + length
        if payload_end + 4 > len(png_data):
            break
        payload = png_data[payload_start:payload_end]
        if chunk_type == b"sRGB" and payload:
            srgb_tags.append(_png_tag("SRGBRendering", _png_srgb_rendering(payload[0]), "PNG"))
        elif chunk_type == b"tEXt":
            text_tag = _png_text_tag(payload)
            if text_tag is not None:
                text_tags.append(text_tag)
        elif chunk_type == b"pHYs" and len(payload) == 9:
            phys_tags.extend(_png_phys_tags(payload))
        offset = payload_end + 4
    return [*srgb_tags, *text_tags, *phys_tags]


def _png_text_tag(payload: bytes) -> ReadTag | None:
    keyword, separator, text = payload.partition(b"\0")
    if not separator:
        return None
    name = keyword.decode("latin-1", errors="replace")
    value = text.decode("latin-1", errors="replace")
    return _png_tag(name, value, "PNG")


def _png_phys_tags(payload: bytes) -> list[ReadTag]:
    unit = payload[8]
    return [
        _png_tag("PixelsPerUnitX", int.from_bytes(payload[0:4], "big"), "PNG-pHYs"),
        _png_tag("PixelsPerUnitY", int.from_bytes(payload[4:8], "big"), "PNG-pHYs"),
        _png_tag("PixelUnits", "meters" if unit == 1 else "Unknown", "PNG-pHYs"),
    ]


def _png_tag(name: str, value: PgfGraphValue, group: str) -> ReadTag:
    return _tag(
        name,
        value,
        group,
        "Image::ExifTool::PNG::Main",
        name,
        (PGF_EMBEDDED_METADATA_SOURCE, PNG_IHDR_SOURCE),
    )


def _tag(
    name: str,
    value: PgfGraphValue,
    group: str,
    table_name: str,
    tag_id: str,
    evidence_ids: tuple[str, ...],
) -> ReadTag:
    return ReadTag(
        name=name,
        value=_read_value(value),
        provenance=_provenance(
            group=group,
            table_name=table_name,
            tag_id=tag_id,
            evidence_ids=evidence_ids,
        ),
        schema=None,
    )


def _join_color(color: tuple[int, int, int]) -> str:
    return " ".join(str(component) for component in color)


def _png_color_type(color_type: int) -> str | int:
    names = {0: "Grayscale", 2: "RGB", 3: "Palette", 4: "Grayscale with Alpha", 6: "RGB with Alpha"}
    return names.get(color_type, color_type)


def _png_compression(compression: int) -> str | int:
    return "Deflate/Inflate" if compression == 0 else compression


def _png_filter(filter_method: int) -> str | int:
    return "Adaptive" if filter_method == 0 else filter_method


def _png_interlace(interlace: int) -> str | int:
    names = {0: "Noninterlaced", 1: "Adam7 Interlace"}
    return names.get(interlace, interlace)


def _png_srgb_rendering(rendering: int) -> str | int:
    names = {
        0: "Perceptual",
        1: "Relative Colorimetric",
        2: "Saturation",
        3: "Absolute Colorimetric",
    }
    return names.get(rendering, rendering)


def invoke_pgf(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_pgf_read_graph(_read_pgf_exiftool_ranges(path), source_file)


def _read_pgf_exiftool_ranges(path: Path) -> bytes:
    with path.open("rb") as file:
        header = file.read(24)
        if len(header) < 24:
            return header
        post_header_length = int.from_bytes(header[4:8], "little") - 16
        if header[19] == 2 and post_header_length > 0:
            file.seek(1024, 1)
            post_header_length -= 1024
        if 0 < post_header_length < 0x1000000:
            return header + file.read(post_header_length)
        return header


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="pgf",
        builder_ref="exifmodern.formats.pgf:invoke_pgf",
        patterns=(Pattern(0, b"PGF"),),
    ),
)
