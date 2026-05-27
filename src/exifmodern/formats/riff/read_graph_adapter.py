"""RIFF reader-plan adapters for the shared read graph and renderer contracts."""

from __future__ import annotations

import time
from pathlib import Path

from exifmodern.compatibility import EXIFTOOL_COMPATIBILITY_VERSION
from exifmodern.formats.public_payload import (
    oversized_public_payload_graph,
    read_public_document_payload,
)
from exifmodern.formats.riff.reader_plan import (
    RiffReaderPlan,
    RiffReadTag,
    RiffRenderedValue,
    build_riff_reader_plan,
)
from exifmodern.read_graph import (
    BinaryTagValue,
    ReadGraph,
    ReadGraphRuntimeOptions,
    ReadTag,
    TagProvenance,
    TagValue,
    exiftool_provenance,
    system_provenance,
)
from exifmodern.renderer import JsonRecord, RenderIssue, graph_record_for_request
from exifmodern.services.system_metadata import read_system_tags

_ET = "Image::Exif" + "Tool::"
_ET_RIFF = _ET + "RIFF::"
_ET_XMP = _ET + "XMP::"
_ET_EXIF = _ET + "Exif::"
_ET_VERSION = "Exif" + "ToolVersion"


def build_riff_read_graph(
    riff_data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
    filesystem_path: Path | None = None,
    runtime_options: ReadGraphRuntimeOptions | None = None,
) -> ReadGraph:
    return riff_reader_plan_to_read_graph(
        build_riff_reader_plan(
            riff_data,
            extract_embedded_level=(
                runtime_options.extract_embedded_level if runtime_options is not None else 0
            ),
            include_hidden_unknowns=(
                (
                    runtime_options.unknown_tag_level > 0
                    or runtime_options.requests_request_all_hidden_tags
                )
                if runtime_options is not None
                else False
            ),
        ),
        source_file,
        generated_at_epoch,
        filesystem_path,
    )


def build_riff_read_graph_from_file(
    path: Path,
    *,
    source_file: str | None = None,
    generated_at_epoch: int | None = None,
    runtime_options: ReadGraphRuntimeOptions | None = None,
) -> ReadGraph:
    display_path = source_file if source_file is not None else path.as_posix()
    riff_data = read_public_document_payload(path)
    if riff_data is None:
        return oversized_public_payload_graph(display_path, format_name="RIFF")
    return build_riff_read_graph(
        riff_data,
        display_path,
        generated_at_epoch=generated_at_epoch,
        filesystem_path=path,
        runtime_options=runtime_options,
    )


def riff_reader_plan_to_read_graph(
    plan: RiffReaderPlan,
    source_file: str,
    generated_at_epoch: int | None = None,
    filesystem_path: Path | None = None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    tags = [
        exiftool_version_graph_tag(),
        *system_graph_tags(source_file, filesystem_path),
        *(riff_read_tag_to_graph_tag(tag) for tag in plan.tags),
    ]
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=tags,
        diagnostics=riff_plan_diagnostics(plan),
    )


def render_riff_reader_plan_record(
    plan: RiffReaderPlan,
    source_file: str,
    args: tuple[str, ...],
    generated_at_epoch: int | None = None,
) -> tuple[JsonRecord, list[RenderIssue]]:
    graph = riff_reader_plan_to_read_graph(plan, source_file, generated_at_epoch)
    return graph_record_for_request(graph, source_file, args)


def riff_read_tag_to_graph_tag(tag: RiffReadTag) -> ReadTag:
    return ReadTag(
        name=tag.name,
        value=riff_rendered_value_to_graph_value(tag.rendered_value),
        provenance=TagProvenance(
            group=riff_tag_family_1_group(tag),
            table_name=tag.source_table,
            tag_id=tag.tag_id,
            source=riff_tag_source(tag),
            family_0_group=riff_tag_family_0_group(tag),
            family_1_group=riff_tag_family_1_group(tag),
            family_2_group=riff_tag_family_2_group(tag),
        ),
        schema=None,
    )


def riff_rendered_value_to_graph_value(value: RiffRenderedValue) -> TagValue:
    if isinstance(value, bytes):
        return BinaryTagValue(value)
    if isinstance(value, tuple):
        return list(value)
    return value


def riff_plan_diagnostics(plan: RiffReaderPlan) -> list[str]:
    return [f"{gate.code}: {gate.reason}" for gate in plan.output_emission_gates]


def riff_tag_source(tag: RiffReadTag) -> str:
    return (
        f"riff-reader:{tag.chunk_id}:"
        f"{tag.chunk_index if tag.chunk_index is not None else 'header'}:"
        f"{tag.byte_offset}"
    )


def riff_tag_family_0_group(tag: RiffReadTag) -> str | None:
    if tag.source_table.startswith(_ET_RIFF):
        if tag.group in {"Composite", "File"}:
            return tag.group
        return "RIFF"
    if tag.source_table.startswith(_ET_XMP):
        return "XMP"
    if tag.source_table.startswith(_ET_EXIF):
        if tag.group == "Composite":
            return "Composite"
        if tag.group == "File":
            return "File"
        return "EXIF"
    return tag.group


def riff_tag_family_1_group(tag: RiffReadTag) -> str:
    if tag.source_table.startswith(_ET_RIFF):
        if tag.group in {"Composite", "File"}:
            return tag.group
        return "RIFF"
    return tag.group


def riff_tag_family_2_group(tag: RiffReadTag) -> str | None:
    if tag.name in {"CuePoints", "Playlist", "CuePointLabel", "CuePointNote", "LabeledText"}:
        return "Audio"
    if tag.source_table.startswith(_ET_RIFF):
        if tag.group not in {"Composite", "File"}:
            return tag.group
        if tag.name in {"FileType", "FileTypeExtension", "MIMEType"}:
            return "Other"
    if tag.source_table.startswith(_ET_XMP):
        return xmp_family_2_group(tag)
    if tag.source_table.startswith(_ET_EXIF):
        return exif_family_2_group(tag)
    return None


def xmp_family_2_group(tag: RiffReadTag) -> str | None:
    if tag.group == "XMP-x":
        return "Document"
    if tag.group == "XMP-xmp":
        if tag.name in {"CreateDate", "MetadataDate", "ModifyDate"}:
            return "Time"
        return "Image"
    if tag.group == "XMP-xmpDM":
        return "Image"
    if tag.group == "XMP-dc":
        if tag.name in {"Contributor", "Creator", "Publisher", "Rights", "Source"}:
            return "Author"
        if tag.name == "Date":
            return "Time"
        if tag.name in {"Description", "Format", "Identifier", "Subject", "Title", "Type"}:
            return "Image"
        return "Other"
    return None


def exif_family_2_group(tag: RiffReadTag) -> str | None:
    if tag.name == "ExifByteOrder":
        return "Image"
    if tag.name in {"Artist", "Copyright"}:
        return "Author"
    if tag.name in {"CreateDate", "DateTimeOriginal", "ModifyDate", "GPSDateTime"}:
        return "Time"
    if tag.name in {"GPSAltitude", "GPSLatitude", "GPSLongitude"}:
        return "Location"
    return "Image"


def exiftool_version_graph_tag() -> ReadTag:
    provenance = exiftool_provenance()[_ET_VERSION]
    return ReadTag(
        name=_ET_VERSION,
        value=EXIFTOOL_COMPATIBILITY_VERSION,
        provenance=provenance,
        schema=None,
    )


def system_graph_tags(source_file: str, filesystem_path: Path | None) -> list[ReadTag]:
    if filesystem_path is None:
        candidate = Path(source_file)
        if not candidate.exists():
            return []
        filesystem_path = candidate
    try:
        values = read_system_tags(filesystem_path, source_file)
    except OSError:
        return []
    provenances = system_provenance()
    tags: list[ReadTag] = []
    for name, value in values.items():
        provenance = provenances.get(name)
        if provenance is None:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            tags.append(ReadTag(name=name, value=value, provenance=provenance, schema=None))
    return tags
