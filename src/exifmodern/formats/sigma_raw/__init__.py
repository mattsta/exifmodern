"""Sigma/Foveon X3F transaction planning."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.sigma_raw.metadata_transaction_plan import (
    SigmaRawMetadataRewriteRequest,
    SigmaRawMetadataTransactionPlan,
    build_sigma_raw_metadata_transaction_plan,
    plan_sigma_raw_metadata_transaction,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = [
    "SigmaRawMetadataRewriteRequest",
    "SigmaRawMetadataTransactionPlan",
    "build_sigma_raw_metadata_transaction_plan",
    "build_sigma_raw_read_graph",
    "invoke_sigma_raw",
    "plan_sigma_raw_metadata_transaction",
]


_SIGMA_HEADER_TABLE = "Image::ExifTool::SigmaRaw::Header"
_SIGMA_HEADER_EXT_TABLE = "Image::ExifTool::SigmaRaw::HeaderExt"
_SIGMA_PROPERTIES_TABLE = "Image::ExifTool::SigmaRaw::Properties"
_SIGMA_MAX_SPARSE_MATERIALIZATION = 16 * 1024 * 1024


def build_sigma_raw_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate a Sigma/Foveon X3F transaction plan into a ReadGraph."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_sigma_raw_metadata_transaction_plan(data)
    diagnostics = [
        f"SigmaRaw package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status != "planned":
        diagnostics.insert(0, f"SigmaRaw package-local reader status: {plan.status}")

    tags: list[ReadTag] = []
    header = plan.header
    header_scalars: tuple[tuple[str, int | float | str | None], ...] = (
        ("FileVersion", header.file_version),
        ("ImageUniqueID", header.image_unique_id),
        ("MarkBits", header.mark_bits),
        ("ImageWidth", header.image_width),
        ("ImageHeight", header.image_height),
        ("Rotation", header.rotation),
        ("WhiteBalance", header.white_balance),
        ("SceneCaptureType", header.scene_capture_type),
    )
    for name, value in header_scalars:
        if value is None:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group="Camera",
                    table_name=_SIGMA_HEADER_TABLE,
                    tag_id=name,
                    evidence_ids=header.evidence_ids,
                ),
                schema=None,
            )
        )
    for ext in header.extended_tags:
        if ext.value is None:
            continue
        tags.append(
            ReadTag(
                name=ext.routed_tag,
                value=_read_value(ext.value),
                provenance=_provenance(
                    group="Camera",
                    table_name=_SIGMA_HEADER_EXT_TABLE,
                    tag_id=ext.routed_tag,
                    evidence_ids=ext.evidence_ids,
                    duplicate_instance_ordinal=ext.selector_index,
                ),
                schema=None,
            )
        )
    for section in plan.directory.sections:
        if section.properties is None:
            continue
        for prop in section.properties.properties:
            tags.append(
                ReadTag(
                    name=prop.routed_tag,
                    value=_read_value(prop.value),
                    provenance=_provenance(
                        group="Camera",
                        table_name=_SIGMA_PROPERTIES_TABLE,
                        tag_id=prop.routed_tag,
                        evidence_ids=prop.evidence_ids,
                        duplicate_instance_ordinal=prop.index,
                    ),
                    schema=None,
                )
            )
    return _graph(source_file, tags, diagnostics)


def invoke_sigma_raw(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_sigma_raw_read_graph(_read_sigma_raw_metadata_bytes(path), source_file)


def _read_sigma_raw_metadata_bytes(path: Path) -> bytes:
    from exifmodern.formats.sigma_raw.metadata_transaction_plan import (
        X3F_DIRECTORY_ENTRY_SIZE,
        X3F_DIRECTORY_HEADER_SIZE,
        X3F_IMAGE_SUBHEADER_SIZE,
        X3F_INITIAL_HEADER_SIZE,
        x3f_header_lengths,
    )

    file_size = path.stat().st_size
    chunks: list[tuple[int, bytes]] = []
    with path.open("rb") as file:
        header = file.read(X3F_INITIAL_HEADER_SIZE)
        chunks.append((0, header))
        if len(header) < X3F_INITIAL_HEADER_SIZE:
            return _join_sparse_chunks(chunks)
        version_raw = int.from_bytes(header[4:8], "little")
        static_header_length, extended_length = x3f_header_lengths(
            version_raw >> 16,
            version_raw & 0xFFFF,
        )
        required_header = static_header_length + extended_length
        if required_header > len(header):
            file.seek(len(header))
            chunks.append((len(header), file.read(required_header - len(header))))
        if file_size < 4:
            return _join_sparse_chunks(chunks)
        file.seek(file_size - 4)
        directory_offset = int.from_bytes(file.read(4), "little")
        chunks.append((file_size - 4, directory_offset.to_bytes(4, "little")))
        file.seek(directory_offset)
        directory_header = file.read(X3F_DIRECTORY_HEADER_SIZE)
        chunks.append((directory_offset, directory_header))
        if len(directory_header) < X3F_DIRECTORY_HEADER_SIZE or not directory_header.startswith(
            b"SECd"
        ):
            return _join_sparse_chunks(chunks)
        entry_count = int.from_bytes(directory_header[8:12], "little")
        entries_offset = directory_offset + X3F_DIRECTORY_HEADER_SIZE
        entries_size = entry_count * X3F_DIRECTORY_ENTRY_SIZE
        file.seek(entries_offset)
        entries = file.read(entries_size)
        chunks.append((entries_offset, entries))
        for index in range(entry_count):
            entry_offset = index * X3F_DIRECTORY_ENTRY_SIZE
            if entry_offset + X3F_DIRECTORY_ENTRY_SIZE > len(entries):
                break
            section_offset = int.from_bytes(entries[entry_offset : entry_offset + 4], "little")
            section_length = int.from_bytes(entries[entry_offset + 4 : entry_offset + 8], "little")
            raw_tag = entries[entry_offset + 8 : entry_offset + 12]
            if raw_tag == b"PROP":
                read_length = section_length
            elif raw_tag == b"IMA2":
                read_length = min(section_length, X3F_IMAGE_SUBHEADER_SIZE + 10)
            else:
                continue
            file.seek(section_offset)
            chunks.append((section_offset, file.read(read_length)))
    return _join_sparse_chunks(chunks)


def _join_sparse_chunks(chunks: list[tuple[int, bytes]]) -> bytes:
    size = max((offset + len(chunk) for offset, chunk in chunks), default=0)
    if size > _SIGMA_MAX_SPARSE_MATERIALIZATION:
        return chunks[0][1] if chunks else b""
    result = bytearray(b"\0" * size)
    for offset, chunk in chunks:
        result[offset : offset + len(chunk)] = chunk
    return bytes(result)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="sigma_raw",
        builder_ref="exifmodern.formats.sigma_raw:invoke_sigma_raw",
        patterns=(Pattern(0, b"FOVb"),),
    ),
)
