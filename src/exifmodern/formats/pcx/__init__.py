"""PCX image transaction planning public API."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.pcx.image_transaction_plan import (
    PCX_HEADER_SIZE,
    PcxImageTransactionPlan,
    PcxRewriteRequest,
    build_pcx_image_transaction_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag

__all__ = (
    "PcxImageTransactionPlan",
    "PcxRewriteRequest",
    "build_pcx_image_transaction_plan",
    "build_pcx_read_graph",
    "invoke_pcx",
    "is_pcx_prefix",
)


def is_pcx_prefix(prefix: bytes) -> bool:
    plan = build_pcx_image_transaction_plan(prefix)
    return plan.header_validation.is_exiftool_accepted


def build_pcx_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph

    plan = build_pcx_image_transaction_plan(data)
    diagnostics = [
        f"PCX package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    header = plan.header_validation
    tags: list[ReadTag] = [
        _pcx_tag("FileType", "FileType", "PCX", header.evidence_ids, group="File"),
        _pcx_tag(
            "FileTypeExtension",
            "FileTypeExtension",
            "pcx",
            header.evidence_ids,
            group="File",
        ),
        _pcx_tag("MIMEType", "MIMEType", "image/pcx", header.evidence_ids, group="File"),
    ]
    for name, tag_id, value in (
        ("Manufacturer", "0x00", header.manufacturer_name or header.manufacturer),
        ("Software", "0x01", header.software_name or header.version),
        ("Encoding", "0x02", header.encoding_name or header.encoding),
        ("BitsPerPixel", "0x03", header.bits_per_pixel),
    ):
        if value is None:
            continue
        tags.append(_pcx_tag(name, tag_id, value, header.evidence_ids, group="File"))
    bounds = plan.image_bounds
    for name, tag_id, value in (
        ("LeftMargin", "0x04", bounds.left_margin),
        ("TopMargin", "0x06", bounds.top_margin),
        ("ImageWidth", "0x08", bounds.image_width),
        ("ImageHeight", "0x0a", bounds.image_height),
    ):
        if value is not None:
            tags.append(_pcx_tag(name, tag_id, value, bounds.evidence_ids, group="File"))
    resolution = plan.resolution
    for name, tag_id, value in (
        ("XResolution", "0x0c", resolution.x_resolution),
        ("YResolution", "0x0e", resolution.y_resolution),
        ("ScreenWidth", "0x46", resolution.screen_width),
        ("ScreenHeight", "0x48", resolution.screen_height),
    ):
        if value is not None:
            tags.append(_pcx_tag(name, tag_id, value, resolution.evidence_ids, group="File"))
    raster = plan.raster_layout
    for name, tag_id, value in (
        ("ColorPlanes", "0x41", raster.color_planes),
        ("BytesPerLine", "0x42", raster.bytes_per_line),
    ):
        if value is not None:
            tags.append(_pcx_tag(name, tag_id, value, raster.evidence_ids, group="File"))
    color_mode = header.color_mode_description or header.color_mode
    if color_mode is not None:
        tags.append(_pcx_tag("ColorMode", "0x44", color_mode, header.evidence_ids, group="File"))
    if bounds.image_width is not None and bounds.image_height is not None:
        tags.extend(
            _pcx_composite_tags(
                bounds.image_width,
                bounds.image_height,
                (*bounds.evidence_ids, *header.evidence_ids),
            )
        )
    return _graph(source_file, tags, diagnostics)


def _pcx_tag(
    name: str,
    tag_id: str,
    value: str | int,
    evidence_ids: tuple[str, ...],
    *,
    group: str = "Image",
) -> ReadTag:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    return ReadTag(
        name=name,
        value=_read_value(value),
        provenance=_provenance(
            group=group,
            table_name="Image::ExifTool::PCX::Main",
            tag_id=tag_id,
            evidence_ids=evidence_ids,
        ),
        schema=None,
    )


def _pcx_composite_tags(
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
                table_name="Image::ExifTool::Exif::Composite",
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
                table_name="Image::ExifTool::Exif::Composite",
                tag_id="Exif-Megapixels",
                evidence_ids=evidence_ids,
            ),
            schema=None,
        ),
    ]


def invoke_pcx(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    with path.open("rb") as file:
        data = file.read(PCX_HEADER_SIZE)
    return build_pcx_read_graph(data, source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="pcx",
        builder_ref="exifmodern.formats.pcx:invoke_pcx",
        patterns=(Pattern(0, b"\x0a"),),
        structural_check="exifmodern.formats.pcx:is_pcx_prefix",
        weak=True,
    ),
)
