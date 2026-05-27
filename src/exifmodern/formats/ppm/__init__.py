"""PPM/PGM/PBM transaction planning public API."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.ppm.image_transaction_plan import (
    PpmImageTransactionPlan,
    PpmRewriteRequest,
    build_ppm_image_transaction_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag

__all__ = (
    "PpmImageTransactionPlan",
    "PpmRewriteRequest",
    "build_ppm_image_transaction_plan",
    "build_ppm_read_graph",
    "invoke_ppm",
)


_PPM_TABLE_NAME = "Image::ExifTool::PPM::Main"
_PPM_MIME_TYPES = {
    "PBM": "image/x-portable-bitmap",
    "PGM": "image/x-portable-graymap",
    "PPM": "image/x-portable-pixmap",
}


def build_ppm_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate a PPM transaction plan into a ReadGraph."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_ppm_image_transaction_plan(data)
    diagnostics = [
        f"PPM package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status != "planned":
        diagnostics.insert(0, f"PPM package-local reader status: {plan.status}")

    tags: list[ReadTag] = []
    if plan.magic.family in _PPM_MIME_TYPES:
        family = plan.magic.family
        tags.extend(
            [
                ReadTag(
                    name="FileType",
                    value=_read_value(family),
                    provenance=_provenance(
                        group="File",
                        table_name=_PPM_TABLE_NAME,
                        tag_id="FileType",
                        evidence_ids=plan.magic.evidence_ids,
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="FileTypeExtension",
                    value=_read_value(family.lower()),
                    provenance=_provenance(
                        group="File",
                        table_name=_PPM_TABLE_NAME,
                        tag_id="FileTypeExtension",
                        evidence_ids=plan.magic.evidence_ids,
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="MIMEType",
                    value=_read_value(_PPM_MIME_TYPES[family]),
                    provenance=_provenance(
                        group="File",
                        table_name=_PPM_TABLE_NAME,
                        tag_id="MIMEType",
                        evidence_ids=plan.magic.evidence_ids,
                    ),
                    schema=None,
                ),
            ]
        )
    if plan.comment.cleaned_value is not None and plan.comment.tag_emitted_as_comment:
        tags.append(
            ReadTag(
                name="Comment",
                value=_read_value(plan.comment.cleaned_value),
                provenance=_provenance(
                    group="File",
                    table_name=_PPM_TABLE_NAME,
                    tag_id="Comment",
                    evidence_ids=plan.comment.evidence_ids,
                ),
                schema=None,
            )
        )
    for header_field in (plan.image_width, plan.image_height, plan.maxval):
        if header_field.value is None:
            continue
        tags.append(
            ReadTag(
                name=header_field.name,
                value=_read_value(header_field.value),
                provenance=_provenance(
                    group="File",
                    table_name=_PPM_TABLE_NAME,
                    tag_id=header_field.name,
                    evidence_ids=header_field.evidence_ids,
                ),
                schema=None,
            )
        )
    if plan.image_width.value is not None and plan.image_height.value is not None:
        tags.extend(
            _ppm_composite_tags(
                plan.image_width.value,
                plan.image_height.value,
                (*plan.image_width.evidence_ids, *plan.image_height.evidence_ids),
            )
        )
    return _graph(source_file, tags, diagnostics)


def _ppm_composite_tags(
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


def invoke_ppm(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_ppm_read_graph(_read_ppm_exiftool_header(path), source_file)


def _read_ppm_exiftool_header(path: Path) -> bytes:
    """Read 1024-byte header chunks until PPM.pm-style scalar parsing completes."""

    data = bytearray()
    with path.open("rb") as file:
        while True:
            chunk = file.read(1024)
            if not chunk:
                break
            data.extend(chunk)
            if _ppm_header_complete(bytes(data)):
                break
    return bytes(data)


def _ppm_header_complete(data: bytes) -> bool:
    if len(data) < 3 or not data.startswith(b"P") or data[1:2] not in b"123456":
        return False
    required = 2 if data[1:2] in {b"1", b"4"} else 3
    offset = 2
    tokens = 0
    while offset < len(data):
        while offset < len(data) and data[offset] in b" \t\n\r\f\v":
            offset += 1
        if offset >= len(data):
            return False
        if data[offset] == 35:
            newline = data.find(b"\n", offset)
            carriage = data.find(b"\r", offset)
            ends = [pos for pos in (newline, carriage) if pos >= 0]
            if not ends:
                return False
            offset = min(ends) + 1
            continue
        end = offset
        while end < len(data) and data[end] not in b" \t\n\r\f\v#":
            end += 1
        if end == len(data):
            return False
        tokens += 1
        offset = end
        if tokens >= required:
            return True
    return False


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="ppm/p1",
        builder_ref="exifmodern.formats.ppm:invoke_ppm",
        patterns=(Pattern(0, b"P1"),),
    ),
    Signature(
        format_id="ppm/p2",
        builder_ref="exifmodern.formats.ppm:invoke_ppm",
        patterns=(Pattern(0, b"P2"),),
    ),
    Signature(
        format_id="ppm/p3",
        builder_ref="exifmodern.formats.ppm:invoke_ppm",
        patterns=(Pattern(0, b"P3"),),
    ),
    Signature(
        format_id="ppm/p4",
        builder_ref="exifmodern.formats.ppm:invoke_ppm",
        patterns=(Pattern(0, b"P4"),),
    ),
    Signature(
        format_id="ppm/p5",
        builder_ref="exifmodern.formats.ppm:invoke_ppm",
        patterns=(Pattern(0, b"P5"),),
    ),
    Signature(
        format_id="ppm/p6",
        builder_ref="exifmodern.formats.ppm:invoke_ppm",
        patterns=(Pattern(0, b"P6"),),
    ),
)
