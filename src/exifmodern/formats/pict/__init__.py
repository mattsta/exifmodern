"""PICT transaction planning public API."""

from pathlib import Path

from exifmodern.formats.pict.image_transaction_plan import (
    PictImageTransactionPlan,
    PictRewriteRequest,
    build_pict_image_transaction_plan,
)
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = (
    "PictImageTransactionPlan",
    "PictRewriteRequest",
    "build_pict_image_transaction_plan",
    "build_pict_read_graph",
    "invoke_pict",
    "is_pict_prefix",
)


def is_pict_prefix(prefix: bytes) -> bool:
    """ExifTool-compatible PICT resource/file structural gate."""
    return build_pict_image_transaction_plan(prefix).header.reason is None


def invoke_pict(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    with path.open("rb") as file:
        data = file.read(552)
    return build_pict_read_graph(data, source_file)


def build_pict_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph

    plan = build_pict_image_transaction_plan(data)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"PICT package-local reader status: {plan.status}")
    diagnostics.extend(
        f"PICT package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    )
    header = plan.header
    tags: list[ReadTag] = [
        _pict_tag("FileType", "FileType", "PICT", header.evidence_ids, group="File"),
        _pict_tag(
            "FileTypeExtension",
            "FileTypeExtension",
            "pict",
            header.evidence_ids,
            group="File",
        ),
        _pict_tag("MIMEType", "MIMEType", "image/pict", header.evidence_ids, group="File"),
    ]
    bounds = header.bounds
    for name, tag_id, dimension_value in (
        ("ImageWidth", "ImageWidth", bounds.image_width),
        ("ImageHeight", "ImageHeight", bounds.image_height),
    ):
        if dimension_value is not None:
            tags.append(_pict_tag(name, tag_id, dimension_value, bounds.evidence_ids))
    resolution = header.resolution
    for name, tag_id, resolution_value in (
        ("XResolution", "XResolution", resolution.x_resolution),
        ("YResolution", "YResolution", resolution.y_resolution),
    ):
        if resolution_value is not None:
            tags.append(
                _pict_tag(
                    name,
                    tag_id,
                    _pict_public_number(resolution_value),
                    resolution.evidence_ids,
                )
            )
    if bounds.image_width is not None and bounds.image_height is not None:
        tags.extend(
            _pict_composite_tags(
                bounds.image_width,
                bounds.image_height,
                (*bounds.evidence_ids, *resolution.evidence_ids),
            )
        )
    return _graph(source_file, tags, diagnostics)


def _pict_public_number(value: int | float) -> int | float:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _pict_tag(
    name: str,
    tag_id: str,
    value: str | int | float,
    evidence_ids: tuple[str, ...],
    *,
    group: str = "File",
) -> ReadTag:
    from exifmodern.dispatch_helpers import _provenance, _read_value

    return ReadTag(
        name=name,
        value=_read_value(value),
        provenance=_provenance(
            group=group,
            table_name="Image::ExifTool::PICT::Main",
            tag_id=tag_id,
            references=evidence_ids,
        ),
        schema=None,
    )


def _pict_composite_tags(
    width: int,
    height: int,
    evidence_ids: tuple[str, ...],
) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _provenance, _read_value

    megapixels = round(width * height / 1_000_000, 1 if width * height >= 1_000_000 else 6)
    return [
        ReadTag(
            name="ImageSize",
            value=_read_value(f"{width}x{height}"),
            provenance=_provenance(
                group="Composite",
                table_name="Image::ExifTool::Exif::Composite",
                tag_id="Exif-ImageSize",
                references=evidence_ids,
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
                references=evidence_ids,
            ),
            schema=None,
        ),
    ]


_PICT_BUILDER = "exifmodern.formats.pict:invoke_pict"
_PICT_STRUCTURAL_CHECK = "exifmodern.formats.pict:is_pict_prefix"

SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="pict/resource-v1",
        builder_ref=_PICT_BUILDER,
        patterns=(Pattern(10, b"\x11\x01"),),
        structural_check=_PICT_STRUCTURAL_CHECK,
        notes=(
            "PICT.pm ProcessPICT unpacks x2n5 and accepts version-1 opcode "
            "0x1101 at byte 10 for PICT resources.",
        ),
    ),
    Signature(
        format_id="pict/resource-v2-standard",
        builder_ref=_PICT_BUILDER,
        patterns=(Pattern(10, b"\x00\x11"), Pattern(12, b"\x02\xff\x0c\x00\xff\xff")),
        structural_check=_PICT_STRUCTURAL_CHECK,
        notes=(
            "PICT.pm ProcessPICT accepts version-2 opcode 0x0011 at byte 10 "
            "followed by the standard v2 marker.",
        ),
    ),
    Signature(
        format_id="pict/resource-v2-extended",
        builder_ref=_PICT_BUILDER,
        patterns=(Pattern(10, b"\x00\x11"), Pattern(12, b"\x02\xff\x0c\x00\xff\xfe")),
        structural_check=_PICT_STRUCTURAL_CHECK,
        notes=(
            "PICT.pm ProcessPICT accepts version-2 opcode 0x0011 at byte 10 "
            "followed by the extended v2 marker.",
        ),
    ),
    Signature(
        format_id="pict/file-v1",
        builder_ref=_PICT_BUILDER,
        patterns=(Pattern(522, b"\x11\x01"),),
        structural_check=_PICT_STRUCTURAL_CHECK,
        notes=(
            "PICT.pm retries ProcessPICT at offset 512 for files with a "
            "512-byte PICT file header; opcode then lands at byte 522.",
        ),
    ),
    Signature(
        format_id="pict/file-v2-standard",
        builder_ref=_PICT_BUILDER,
        patterns=(Pattern(522, b"\x00\x11"), Pattern(524, b"\x02\xff\x0c\x00\xff\xff")),
        structural_check=_PICT_STRUCTURAL_CHECK,
        notes=(
            "PICT.pm retries at offset 512 and accepts the standard v2 marker "
            "after the file-header-prefixed opcode.",
        ),
    ),
    Signature(
        format_id="pict/file-v2-extended",
        builder_ref=_PICT_BUILDER,
        patterns=(Pattern(522, b"\x00\x11"), Pattern(524, b"\x02\xff\x0c\x00\xff\xfe")),
        structural_check=_PICT_STRUCTURAL_CHECK,
        notes=(
            "PICT.pm retries at offset 512 and accepts the extended v2 marker "
            "after the file-header-prefixed opcode.",
        ),
    ),
)
