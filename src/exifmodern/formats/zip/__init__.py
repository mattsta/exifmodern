"""ZIP archive metadata transaction planning."""

import time
from pathlib import Path
from typing import Literal

from exifmodern.dispatch_helpers import build_zip_read_graph
from exifmodern.formats.zip.archive_member_detail_plan import (
    GzipOptionalFieldsPlan,
    Rar4BlockStreamPlan,
    build_gzip_optional_fields_plan,
    build_rar4_block_stream_plan,
)
from exifmodern.formats.zip.archive_transaction_plan import (
    ZipArchiveTransactionPlan,
    ZipCentralDirectoryEntryPlan,
    ZipEndOfCentralDirectoryPlan,
    ZipEntryActionPlan,
    ZipLocalFileHeaderPlan,
    ZipMetadataRoutePlan,
    ZipOutputEmissionGate,
    ZipOutputEntry,
    build_zip_archive_transaction_plan,
    encode_zip_entries,
    plan_zip_archive_transaction,
    zip_plan_sources,
    zip_tag_provenance,
)
from exifmodern.formats.zip.gzip_value_plan import (
    GzipValuePlan,
    build_gzip_value_plan,
)
from exifmodern.formats.zip.member_attribute_plan import (
    ZipMemberAttributeInput,
    ZipMemberAttributesPlan,
    build_zip_member_attributes_plan,
    render_zip_dos_datetime,
)
from exifmodern.formats.zip.member_family_plan import (
    GZIP_PROCESS_SOURCE,
    ZipMemberFamilyPlan,
    build_zip_member_family_plan,
)
from exifmodern.formats.zip.rar5_detail_plan import (
    Rar5DetailPlan,
    build_rar5_detail_plan,
    render_rar5_operating_system,
)
from exifmodern.formats.zip.reader_plan import (
    ZipReaderDiagnostic,
    ZipReaderPlan,
    ZipReadTag,
    build_zip_reader_plan,
)
from exifmodern.read_graph import ReadGraph
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "GzipOptionalFieldsPlan",
    "GzipValuePlan",
    "Rar4BlockStreamPlan",
    "Rar5DetailPlan",
    "ZipArchiveTransactionPlan",
    "ZipCentralDirectoryEntryPlan",
    "ZipEndOfCentralDirectoryPlan",
    "ZipEntryActionPlan",
    "ZipLocalFileHeaderPlan",
    "ZipMemberAttributeInput",
    "ZipMemberAttributesPlan",
    "ZipMemberFamilyPlan",
    "ZipMetadataRoutePlan",
    "ZipOutputEmissionGate",
    "ZipOutputEntry",
    "ZipReadTag",
    "ZipReaderDiagnostic",
    "ZipReaderPlan",
    "build_gzip_optional_fields_plan",
    "build_gzip_value_plan",
    "build_rar4_block_stream_plan",
    "build_rar5_detail_plan",
    "build_zip_archive_transaction_plan",
    "build_zip_member_attributes_plan",
    "build_zip_member_family_plan",
    "build_zip_reader_plan",
    "encode_zip_entries",
    "invoke_gzip",
    "invoke_rar",
    "invoke_zip",
    "plan_zip_archive_transaction",
    "render_rar5_operating_system",
    "render_zip_dos_datetime",
]

_ZIP_EOCD_SEARCH_WINDOW = 65_557
_ZIP_METADATA_READ_LIMIT = 8 * 1024 * 1024
_GZIP_HEADER_READ_LIMIT = 65_536
_RAR_HEADER_READ_LIMIT = 8 * 1024 * 1024


def invoke_zip(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_zip_metadata_sections(path)
    return build_zip_read_graph(data, source_file)


def invoke_gzip(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_bounded_prefix(path, _GZIP_HEADER_READ_LIMIT)
    return build_gzip_read_graph(data, source_file)


def invoke_rar(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_bounded_prefix(path, _RAR_HEADER_READ_LIMIT)
    return build_rar_read_graph(data, source_file)


def _read_zip_metadata_sections(path: Path) -> bytes:
    """Read the ZIP metadata envelope, matching ZIP.pm's EOCD/local-header flow."""
    size = path.stat().st_size
    if size <= _ZIP_METADATA_READ_LIMIT:
        return _read_bounded_prefix(path, _ZIP_METADATA_READ_LIMIT)
    with path.open("rb") as file:
        file.seek(max(0, size - _ZIP_EOCD_SEARCH_WINDOW))
        tail = file.read(_ZIP_EOCD_SEARCH_WINDOW)
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0:
        return tail
    eocd_offset = size - len(tail) + eocd
    if eocd + 22 > len(tail):
        return tail[eocd:]
    central_size = int.from_bytes(tail[eocd + 12 : eocd + 16], "little")
    central_offset = int.from_bytes(tail[eocd + 16 : eocd + 20], "little")
    if central_offset + central_size != eocd_offset:
        return tail[eocd:]
    window_size = min(_ZIP_METADATA_READ_LIMIT, size - central_offset)
    with path.open("rb") as file:
        file.seek(central_offset)
        return file.read(window_size)


def _read_bounded_prefix(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        return file.read(byte_count)


def build_gzip_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _read_value
    from exifmodern.read_graph import ReadTag

    optional = build_gzip_optional_fields_plan(data)
    diagnostics = [
        f"GZIP package-local reader gate: {gate.code}: {gate.reason}"
        for gate in optional.output_emission_gates
    ]
    tags: list[ReadTag] = []
    if len(data) >= 10 and data.startswith(b"\x1f\x8b\x08"):
        for name, value in (
            ("FileType", "GZIP"),
            ("FileTypeExtension", "gz"),
            ("MIMEType", "application/x-gzip"),
        ):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=zip_tag_provenance(
                        group="File",
                        table_name="Image::ExifTool::File",
                        tag_id=name,
                        sources=(GZIP_PROCESS_SOURCE,),
                    ),
                    schema=None,
                )
            )
        for name, tag_id, rendered, group in (
            ("Compression", "2", "Deflated" if data[2] == 8 else data[2], "ZIP"),
            ("Flags", "3", _gzip_flags(data[3]), "ZIP"),
            ("ModifyDate", "4", _gzip_modify_date(data[4:8]), "ZIP"),
            ("ExtraFlags", "8", _gzip_value("extra_flags", data[8]), "ZIP"),
            ("OperatingSystem", "9", _gzip_value("operating_system", data[9]), "ZIP"),
        ):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(rendered),
                    provenance=zip_tag_provenance(
                        group=group,
                        table_name="Image::ExifTool::ZIP::GZIP",
                        tag_id=tag_id,
                        sources=zip_plan_sources(optional),
                    ),
                    schema=None,
                )
            )
    field_names = {"archived_file_name": ("ArchivedFileName", "10"), "comment": ("Comment", "11")}
    for field in optional.fields:
        if field.field not in field_names:
            continue
        name, tag_id = field_names[field.field]
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(field.value.decode("latin-1", errors="replace")),
                provenance=zip_tag_provenance(
                    group="ZIP",
                    table_name="Image::ExifTool::ZIP::GZIP",
                    tag_id=tag_id,
                    sources=zip_plan_sources(optional),
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def build_rar_read_graph(data: bytes, source_file: str) -> ReadGraph:
    if data.startswith(b"Rar!\x1a\x07\x00"):
        return _rar4_read_graph(data, source_file)
    return _rar5_read_graph(data, source_file)


def _rar4_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_rar4_block_stream_plan(data)
    diagnostics = [
        f"RAR4 package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    tags: list[ReadTag] = [
        ReadTag(
            name="FileVersion",
            value=_read_value("RAR v4"),
            provenance=zip_tag_provenance(
                group="Other",
                table_name="Image::ExifTool::ZIP::RAR5",
                tag_id="FileVersion",
                sources=zip_plan_sources(plan),
            ),
            schema=None,
        )
    ]
    file_index = 0
    for block in plan.blocks:
        if block.kind == "file":
            file_index += 1
            tags.append(
                ReadTag(
                    name="CompressedSize",
                    value=_read_value(block.payload_size),
                    provenance=zip_tag_provenance(
                        group="Other",
                        table_name="Image::ExifTool::ZIP::RAR",
                        tag_id="0",
                        sources=zip_plan_sources(plan),
                        duplicate_instance_ordinal=file_index,
                    ),
                    schema=None,
                )
            )
        elif block.kind == "comment" and block.comment is not None:
            tags.append(
                ReadTag(
                    name="Comment",
                    value=_read_value(block.comment.decode("latin-1", errors="replace")),
                    provenance=zip_tag_provenance(
                        group="Other",
                        table_name="Image::ExifTool::ZIP::RAR",
                        tag_id="Comment",
                        sources=zip_plan_sources(plan),
                    ),
                    schema=None,
                )
            )
    return _graph(source_file, tags, diagnostics)


def _rar5_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_rar5_detail_plan(data)
    diagnostics = [
        f"RAR5 package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    tags: list[ReadTag] = [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=zip_tag_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id=name,
                sources=zip_plan_sources(plan),
            ),
            schema=None,
        )
        for name, value in (
            ("FileType", "RAR"),
            ("FileTypeExtension", "rar"),
            ("MIMEType", "application/x-rar-compressed"),
        )
    ]
    tags.append(
        ReadTag(
            name="FileVersion",
            value=_read_value("RAR v5"),
            provenance=zip_tag_provenance(
                group="ZIP",
                table_name="Image::ExifTool::ZIP::RAR5",
                tag_id="FileVersion",
                sources=zip_plan_sources(plan),
            ),
            schema=None,
        )
    )
    file_index = 0
    for header in plan.headers:
        if header.kind != "file":
            continue
        file_index += 1
        for name, tag_id, value in (
            ("CompressedSize", "CompressedSize", header.compressed_size),
            ("UncompressedSize", "UncompressedSize", header.uncompressed_size),
            ("ModifyDate", "ModifyDate", header.modify_timestamp),
            (
                "OperatingSystem",
                "OperatingSystem",
                None
                if header.operating_system is None
                else render_rar5_operating_system(header.operating_system),
            ),
            (
                "ArchivedFileName",
                "ArchivedFileName",
                None
                if header.archived_file_name is None
                else header.archived_file_name.decode("utf-8", errors="replace"),
            ),
        ):
            if value is None:
                continue
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=zip_tag_provenance(
                        group="ZIP",
                        table_name="Image::ExifTool::ZIP::RAR5",
                        tag_id=tag_id,
                        sources=zip_plan_sources(plan),
                        duplicate_instance_ordinal=file_index,
                    ),
                    schema=None,
                )
            )
    return _graph(source_file, tags, diagnostics)


def _gzip_value(
    value_kind: Literal["extra_flags", "operating_system"], raw_value: int
) -> str | int:
    plan = build_gzip_value_plan(value_kind, raw_value)
    return plan.display_name if plan.display_name is not None else raw_value


def _gzip_modify_date(raw_value: bytes) -> str:
    timestamp = int.from_bytes(raw_value, "little")
    rendered = time.strftime("%Y:%m:%d %H:%M:%S%z", time.localtime(timestamp))
    if len(rendered) > 2:
        return f"{rendered[:-2]}:{rendered[-2:]}"
    return rendered


def _gzip_flags(flags: int) -> str | int:
    names = []
    for bit, name in (
        (0, "Text"),
        (1, "CRC16"),
        (2, "ExtraFields"),
        (3, "FileName"),
        (4, "Comment"),
    ):
        if flags & (1 << bit):
            names.append(name)
    return ", ".join(names) if names else 0


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="zip",
        builder_ref="exifmodern.formats.zip:invoke_zip",
        patterns=(Pattern(0, b"PK\x03\x04"),),
    ),
    Signature(
        format_id="gzip",
        builder_ref="exifmodern.formats.zip:invoke_gzip",
        patterns=(Pattern(0, b"\x1f\x8b\x08"),),
    ),
    Signature(
        format_id="rar/4",
        builder_ref="exifmodern.formats.zip:invoke_rar",
        patterns=(Pattern(0, b"Rar!\x1a\x07\x00"),),
    ),
    Signature(
        format_id="rar",
        builder_ref="exifmodern.formats.zip:invoke_rar",
        patterns=(Pattern(0, b"Rar!\x1a\x07\x01\x00"),),
    ),
)
