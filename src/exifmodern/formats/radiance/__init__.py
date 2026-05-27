"""Radiance RGBE/HDR image transaction planning public API."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.radiance.image_transaction_plan import (
    RadianceImageTransactionPlan,
    RadianceRewriteRequest,
    build_radiance_image_transaction_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = (
    "RadianceImageTransactionPlan",
    "RadianceRewriteRequest",
    "build_radiance_image_transaction_plan",
    "build_radiance_read_graph",
    "invoke_radiance",
    "read_radiance_metadata_prefix",
)


_RADIANCE_TABLE = "Image::ExifTool::Radiance::Main"
_FILE_TABLE = "Image::ExifTool::File"
_RADIANCE_READLINE_LIMIT = 4096


def build_radiance_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate a Radiance HDR transaction plan into a ReadGraph."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_radiance_image_transaction_plan(data)
    diagnostics = [
        f"Radiance package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status != "planned":
        diagnostics.insert(0, f"Radiance package-local reader status: {plan.status}")

    tags: list[ReadTag] = []
    file_sources = plan.signature.evidence_ids
    if plan.status == "planned":
        for name, file_value in (
            ("FileType", "HDR"),
            ("FileTypeExtension", "hdr"),
            ("MIMEType", "image/vnd.radiance"),
        ):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(file_value),
                    provenance=_provenance(
                        group="File",
                        table_name=_FILE_TABLE,
                        tag_id=name,
                        evidence_ids=file_sources,
                    ),
                    schema=None,
                )
            )
    for index, entry in enumerate(plan.header.entries):
        if not entry.value:
            continue
        entry_value: str | int | float = entry.value
        if entry.tag_name == "Exposure":
            try:
                entry_value = float(entry.value)
            except ValueError:
                entry_value = entry.value
        tags.append(
            ReadTag(
                name=entry.tag_name,
                value=_read_value(entry_value),
                provenance=_provenance(
                    group="Radiance",
                    table_name=_RADIANCE_TABLE,
                    tag_id=entry.tag_key,
                    evidence_ids=entry.evidence_ids,
                    duplicate_instance_ordinal=index,
                ),
                schema=None,
            )
        )
    resolution = plan.resolution
    if resolution.image_width is not None:
        tags.append(
            ReadTag(
                name="ImageWidth",
                value=_read_value(resolution.image_width),
                provenance=_provenance(
                    group="File",
                    table_name=_RADIANCE_TABLE,
                    tag_id="ImageWidth",
                    evidence_ids=resolution.evidence_ids,
                ),
                schema=None,
            )
        )
    if resolution.image_height is not None:
        tags.append(
            ReadTag(
                name="ImageHeight",
                value=_read_value(resolution.image_height),
                provenance=_provenance(
                    group="File",
                    table_name=_RADIANCE_TABLE,
                    tag_id="ImageHeight",
                    evidence_ids=resolution.evidence_ids,
                ),
                schema=None,
            )
        )
    if resolution.orientation_description is not None:
        tags.append(
            ReadTag(
                name="Orientation",
                value=_read_value(resolution.orientation_description),
                provenance=_provenance(
                    group="Radiance",
                    table_name=_RADIANCE_TABLE,
                    tag_id="Orientation",
                    evidence_ids=resolution.evidence_ids,
                ),
                schema=None,
            )
        )
    if resolution.image_width is not None and resolution.image_height is not None:
        tags.extend(
            (
                ReadTag(
                    name="ImageSize",
                    value=_read_value(f"{resolution.image_width}x{resolution.image_height}"),
                    provenance=_provenance(
                        group="Composite",
                        table_name="Image::ExifTool::Composite",
                        tag_id="ImageSize",
                        evidence_ids=resolution.evidence_ids,
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="Megapixels",
                    value=_read_value(
                        round(resolution.image_width * resolution.image_height / 1e6, 6)
                    ),
                    provenance=_provenance(
                        group="Composite",
                        table_name="Image::ExifTool::Composite",
                        tag_id="Megapixels",
                        evidence_ids=resolution.evidence_ids,
                    ),
                    schema=None,
                ),
            )
        )
    return _graph(source_file, tags, diagnostics)


def invoke_radiance(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_radiance_read_graph(read_radiance_metadata_prefix(path, prefix), source_file)


def read_radiance_metadata_prefix(path: Path, prefix: bytes) -> bytes:
    """Read Radiance metadata lines and the resolution line without pixel data."""
    del prefix
    lines: list[bytes] = []
    with path.open("rb") as file:
        signature = file.readline(_RADIANCE_READLINE_LIMIT + 1)
        if signature:
            lines.append(signature)
        while True:
            line = file.readline(_RADIANCE_READLINE_LIMIT + 1)
            if not line:
                break
            lines.append(line)
            stripped = line.rstrip(b"\n")
            if not stripped or len(stripped) >= _RADIANCE_READLINE_LIMIT:
                break
        resolution = file.readline(_RADIANCE_READLINE_LIMIT + 1)
        if resolution:
            lines.append(resolution)
    return b"".join(lines)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="radiance/radiance",
        builder_ref="exifmodern.formats.radiance:invoke_radiance",
        patterns=(Pattern(0, b"#?RADIANCE"),),
    ),
    Signature(
        format_id="radiance/rgbe",
        builder_ref="exifmodern.formats.radiance:invoke_radiance",
        patterns=(Pattern(0, b"#?RGBE"),),
    ),
)
