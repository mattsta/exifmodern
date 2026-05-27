"""TXT/CSV metadata transaction planning and bounded read graph emission."""

from __future__ import annotations

import time
from pathlib import Path

from exifmodern.formats.text.metadata_transaction_plan import (
    TextFileType,
    TextMetadataTransactionPlan,
    TextRewriteRequest,
    TextStatisticsPlan,
    build_text_metadata_transaction_plan,
)
from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance, TagValue
from exifmodern.services.system_metadata import read_system_tags

TEXT_READ_LIMIT_BYTES = 20_000_001

__all__ = [
    "TEXT_READ_LIMIT_BYTES",
    "TextMetadataTransactionPlan",
    "TextRewriteRequest",
    "build_text_metadata_transaction_plan",
    "build_text_read_graph",
    "build_text_read_graph_from_file",
    "invoke_text",
]


def build_text_read_graph_from_file(path: Path, *, source_file: str) -> ReadGraph:
    file_type = "CSV" if path.suffix.lower() == ".csv" else "TXT"
    with path.open("rb") as file:
        data = file.read(TEXT_READ_LIMIT_BYTES)
    return build_text_read_graph(
        data,
        source_file=source_file,
        file_type=file_type,
        filesystem_path=path,
    )


def build_text_read_graph(
    data: bytes,
    *,
    source_file: str,
    file_type: str = "TXT",
    filesystem_path: Path | None = None,
) -> ReadGraph:
    text_file_type: TextFileType = "CSV" if file_type == "CSV" else "TXT"
    plan = build_text_metadata_transaction_plan(data, file_type=text_file_type)
    diagnostics: list[str] = []
    tags: list[ReadTag] = []
    path = filesystem_path if filesystem_path is not None else Path(source_file)
    try:
        tags.extend(_system_tags(path, source_file))
    except OSError as error:
        diagnostics.append(str(error))

    if plan.status == "blocked":
        diagnostics.extend(gate.reason for gate in plan.output_emission_gates)
        return _graph(source_file, tags, diagnostics)

    file_values: dict[str, TagValue] = {
        "FileType": text_file_type,
        "FileTypeExtension": "csv" if text_file_type == "CSV" else "txt",
        "MIMEType": "text/csv" if text_file_type == "CSV" else "text/plain",
    }
    if plan.encoding.encoding is not None:
        file_values["MIMEEncoding"] = plan.encoding.encoding
    if plan.encoding.has_byte_order_mark is not None:
        file_values["ByteOrderMark"] = "Yes" if plan.encoding.has_byte_order_mark else "No"
    file_values["Newlines"] = plan.newlines.label

    if text_file_type == "CSV" and plan.csv_statistics is not None:
        file_values["Delimiter"] = plan.csv_statistics.delimiter_label
        file_values["Quoting"] = plan.csv_statistics.quoting_label
        file_values["ColumnCount"] = plan.csv_statistics.column_count
        if plan.csv_statistics.row_count is not None:
            file_values["RowCount"] = plan.csv_statistics.row_count
    elif plan.text_statistics is not None:
        file_values.update(_text_statistics_values(plan.text_statistics))

    tags.extend(_file_tags(file_values))
    return _graph(source_file, tags, diagnostics)


def invoke_text(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention for fallback dispatch tests and future trie use."""

    return build_text_read_graph_from_file(path, source_file=source_file)


def _text_statistics_values(statistics: TextStatisticsPlan) -> dict[str, TagValue]:
    values: dict[str, TagValue] = {}
    if statistics.line_count is not None:
        values["LineCount"] = statistics.line_count
    if statistics.word_count is not None:
        values["WordCount"] = statistics.word_count
    return values


def _system_tags(path: Path, source_file: str) -> list[ReadTag]:
    return [
        ReadTag(
            name=name,
            value=value,
            provenance=TagProvenance(
                "System",
                "Image::ExifTool::Extra",
                name,
                "filesystem",
                family_0_group="File",
                family_1_group="System",
                family_2_group="Other",
            ),
            schema=None,
        )
        for name, value in read_system_tags(path, source_file).items()
        if isinstance(value, (str, int, float, bool)) or value is None
    ]


def _file_tags(values: dict[str, TagValue]) -> list[ReadTag]:
    return [
        ReadTag(
            name=name,
            value=value,
            provenance=_text_provenance(name),
            schema=None,
        )
        for name, value in values.items()
    ]


def _text_provenance(name: str) -> TagProvenance:
    file_other_tags = {"FileType", "FileTypeExtension", "MIMEType", "MIMEEncoding"}
    family_2_group = "Other" if name in file_other_tags else "Document"
    table_name = (
        "Image::ExifTool::File"
        if name in {"FileType", "FileTypeExtension", "MIMEType"}
        else "Image::ExifTool::Text::Main"
    )
    return TagProvenance(
        "File",
        table_name,
        name,
        "text-pm-process-txt",
        family_0_group="File",
        family_1_group="File",
        family_2_group=family_2_group,
    )


def _graph(source_file: str, tags: list[ReadTag], diagnostics: list[str]) -> ReadGraph:
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=int(time.time()),
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )
