"""OpenEXR header transaction planning primitives translated from ExifTool OpenEXR.pm."""

from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
from exifmodern.formats.openexr.header_transaction_plan import (
    OPENEXR_CHUNK_OFFSET_SIZE,
    OPENEXR_HEADER_SIZE,
    OpenExrHeaderTransactionPlan,
    OpenExrReadTagRecord,
    build_openexr_header_transaction_plan,
    plan_openexr_header_transaction,
)
from exifmodern.media_source import FileMediaSource
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "OpenExrHeaderTransactionPlan",
    "OpenExrReadTagRecord",
    "build_openexr_header_transaction_plan",
    "build_openexr_read_graph",
    "invoke_openexr",
    "plan_openexr_header_transaction",
    "read_openexr_header_payload",
]


def build_openexr_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_openexr_header_transaction_plan(data, allow_output_emission=True)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"OpenEXR package-local reader status: {plan.status}")
    diagnostics.extend(
        f"OpenEXR package-local reader gate: {gate.code}" for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = [
        ReadTag(
            name="FileType",
            value="EXR",
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::OpenEXR::Main",
                tag_id="FileType",
                evidence_ids=plan.magic.evidence_ids,
            ),
            schema=None,
        ),
        ReadTag(
            name="FileTypeExtension",
            value="exr",
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::OpenEXR::Main",
                tag_id="FileTypeExtension",
                evidence_ids=plan.magic.evidence_ids,
            ),
            schema=None,
        ),
        ReadTag(
            name="MIMEType",
            value="image/x-exr",
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::OpenEXR::Main",
                tag_id="MIMEType",
                evidence_ids=plan.magic.evidence_ids,
            ),
            schema=None,
        ),
    ]
    for ordinal, record in enumerate(plan.read_tags):
        tags.append(
            ReadTag(
                name=record.name,
                value=_read_value(_openexr_public_value(record)),
                provenance=_provenance(
                    group=_openexr_public_group(record),
                    table_name="Image::ExifTool::OpenEXR::Main",
                    tag_id=record.name,
                    evidence_ids=record.evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def _openexr_public_group(record: OpenExrReadTagRecord) -> str:
    if record.name in {"ImageWidth", "ImageHeight"}:
        return "File"
    return record.group


def _openexr_public_value(record: OpenExrReadTagRecord) -> str | int | float | list[str]:
    if record.name == "Channels":
        return record.rendered_value.split(", ")
    if record.name in {"EXRVersion", "ImageWidth", "ImageHeight", "PixelAspectRatio"}:
        return record.raw_value
    if record.name in {"ScreenWindowWidth", "Megapixels"}:
        return record.raw_value
    return record.rendered_value


def invoke_openexr(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_openexr_read_graph(read_openexr_header_payload(path, prefix), source_file)


def read_openexr_header_payload(path: Path, prefix: bytes) -> bytes:
    """Read OpenEXR header bytes and chunk offset table, not pixel chunks."""
    source = FileMediaSource(path)
    data = bytearray(prefix)
    if len(data) < OPENEXR_HEADER_SIZE:
        data = bytearray(source.prefix(OPENEXR_HEADER_SIZE))
    if len(data) < OPENEXR_HEADER_SIZE:
        return bytes(data)
    flags = int.from_bytes(data[4:8], "little")
    max_length = 255 if flags & 0x400 else 31
    offset = OPENEXR_HEADER_SIZE
    chunk_count: int | None = None
    while True:
        data = _openexr_ensure_prefix(source, data, offset + 1)
        if offset >= len(data):
            return bytes(data)
        if data[offset] == 0:
            header_end = offset + 1
            if chunk_count is None:
                return bytes(data[:header_end])
            table_end = header_end + chunk_count * OPENEXR_CHUNK_OFFSET_SIZE
            return source.prefix(table_end)
        name_end = _bounded_null_in_source(source, data, offset, max_length)
        if name_end is None or name_end == offset:
            return bytes(data)
        type_start = name_end + 1
        type_end = _bounded_null_in_source(source, data, type_start, max_length)
        if type_end is None or type_end == type_start:
            return bytes(data)
        size_offset = type_end + 1
        size_end = size_offset + 4
        data = _openexr_ensure_prefix(source, data, size_end)
        if size_end > len(data):
            return bytes(data)
        size = int.from_bytes(data[size_offset:size_end], "little")
        value_start = size_end
        value_end = value_start + size
        data = _openexr_ensure_prefix(source, data, value_end)
        if value_end > len(data):
            return bytes(data)
        name = bytes(data[offset:name_end]).decode("latin-1", errors="replace")
        type_name = bytes(data[type_start:type_end]).decode("latin-1", errors="replace")
        if name == "chunkCount" and type_name == "int" and size >= 4:
            chunk_count = int.from_bytes(data[value_start : value_start + 4], "little")
        offset = value_end


def _openexr_ensure_prefix(
    source: FileMediaSource,
    data: bytearray,
    size: int,
) -> bytearray:
    if len(data) >= size:
        return data
    return bytearray(source.prefix(size))


def _bounded_null_in_source(
    source: FileMediaSource,
    data: bytearray,
    offset: int,
    max_length: int,
) -> int | None:
    end = offset + max_length + 1
    data[:] = _openexr_ensure_prefix(source, data, end)
    search_end = min(len(data), end)
    try:
        return bytes(data[offset:search_end]).index(b"\0") + offset
    except ValueError:
        return None


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="openexr",
        builder_ref="exifmodern.formats.openexr:invoke_openexr",
        patterns=(Pattern(0, b"\x76\x2f\x31\x01"),),
    ),
)
