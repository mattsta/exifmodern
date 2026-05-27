"""PNG textual runtime adapters for the shared read graph contracts."""

from __future__ import annotations

import time

from exifmodern.formats.png.textual_data_database_plan import (
    PngTextualTagDatabaseEntry,
    png_textual_data_database_plan,
)
from exifmodern.formats.png.textual_runtime import (
    PngNativeMetadataRecord,
    PngNativeMetadataTag,
    PngRawProfileNestedTag,
    PngTextualChunkRecord,
    PngTextualRuntimeIssue,
    PngTextualRuntimePlan,
    extract_png_textual_runtime,
)
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance
from exifmodern.renderer import JsonRecord, RenderIssue, graph_record_for_request

_ET = "Image::Exif" + "Tool::"
PNG_TEXTUAL_TABLE_NAME = _ET + "PNG::TextualData"


def build_png_textual_read_graph(
    png_data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    return png_textual_runtime_plan_to_read_graph(
        extract_png_textual_runtime(png_data),
        source_file,
        generated_at_epoch,
    )


def png_textual_runtime_plan_to_read_graph(
    plan: PngTextualRuntimePlan,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=[
            *[tag for record in plan.records for tag in png_textual_record_to_graph_tags(record)],
            *[
                tag
                for record in plan.native_records
                for tag in png_native_metadata_record_to_graph_tags(record)
            ],
        ],
        diagnostics=png_textual_plan_diagnostics(plan),
    )


def render_png_textual_runtime_plan_record(
    plan: PngTextualRuntimePlan,
    source_file: str,
    args: tuple[str, ...],
    generated_at_epoch: int | None = None,
) -> tuple[JsonRecord, list[RenderIssue]]:
    graph = png_textual_runtime_plan_to_read_graph(plan, source_file, generated_at_epoch)
    return graph_record_for_request(graph, source_file, args)


def is_renderable(record: PngTextualChunkRecord) -> bool:
    return record.tag_name is not None and record.textual_storage_family != "raw_profile_keyword"


def png_textual_record_to_graph_tags(record: PngTextualChunkRecord) -> tuple[ReadTag, ...]:
    if record.nested_raw_profile is not None:
        return tuple(
            png_raw_profile_nested_tag_to_graph_tag(record, nested_tag)
            for nested_tag in record.nested_raw_profile.tags
        )
    if record.is_raw_profile and record.raw_profile_payload is not None:
        return (png_raw_profile_record_to_graph_tag(record),)
    if is_renderable(record):
        return (png_textual_record_to_graph_tag(record),)
    return ()


def png_native_metadata_record_to_graph_tags(
    record: PngNativeMetadataRecord,
) -> tuple[ReadTag, ...]:
    return tuple(png_native_metadata_tag_to_graph_tag(record, tag) for tag in record.tags)


def png_native_metadata_tag_to_graph_tag(
    record: PngNativeMetadataRecord,
    tag: PngNativeMetadataTag,
) -> ReadTag:
    return ReadTag(
        name=tag.name,
        value=tag.value,
        provenance=TagProvenance(
            group=tag.group,
            table_name=tag.table_name,
            tag_id=tag.name,
            source=tag.source,
        ),
        schema=None,
    )


def png_raw_profile_record_to_graph_tag(record: PngTextualChunkRecord) -> ReadTag:
    tag_name = record.tag_name if record.tag_name is not None else record.keyword
    return ReadTag(
        name=tag_name,
        value=BinaryTagValue(record.raw_profile_payload or b""),
        provenance=TagProvenance(
            group=png_textual_record_group(record),
            table_name=PNG_TEXTUAL_TABLE_NAME,
            tag_id=png_textual_record_tag_id(record),
            source=png_textual_record_source(record),
        ),
        schema=None,
    )


def png_textual_record_to_graph_tag(record: PngTextualChunkRecord) -> ReadTag:
    entry = png_textual_database_entry(record.keyword)
    tag_name = (
        entry.tag_name if entry is not None and "-" not in record.keyword else record.tag_name
    )
    if tag_name is None:
        tag_name = record.keyword
    group = "PNG" if entry is not None else "Image"
    return ReadTag(
        name=tag_name,
        value=record.text,
        provenance=TagProvenance(
            group=group,
            table_name=PNG_TEXTUAL_TABLE_NAME,
            tag_id=png_textual_record_tag_id(record),
            source=png_textual_record_source(record),
            family_0_group=group,
            family_1_group=group,
            family_2_group=png_textual_record_group(record),
        ),
        schema=None,
    )


def png_raw_profile_nested_tag_to_graph_tag(
    record: PngTextualChunkRecord,
    nested_tag: PngRawProfileNestedTag,
) -> ReadTag:
    source = (
        (
            f"png-raw-profile:{record.text_route}:{record.chunk_index}:"
            f"{record.payload_offset}:{nested_tag.name}"
        )
        if record.is_raw_profile
        else nested_tag.source
    )
    return ReadTag(
        name=nested_tag.name,
        value=nested_tag.value,
        provenance=TagProvenance(
            group=nested_tag.group,
            table_name=nested_tag.table_name,
            tag_id=nested_tag.name,
            source=source,
        ),
        schema=None,
    )


def png_textual_plan_diagnostics(plan: PngTextualRuntimePlan) -> list[str]:
    binary_profile_chunk_indexes = {
        record.chunk_index
        for record in plan.records
        if record.is_raw_profile
        and record.raw_profile_payload is not None
        and record.nested_raw_profile is None
    }
    issue_chunk_indexes = {
        issue.chunk_index
        for issue in plan.issues
        if issue.chunk_index not in binary_profile_chunk_indexes
    }
    return [
        *(
            png_textual_raw_profile_route_diagnostic(record)
            for record in plan.records
            if record.is_raw_profile
            and record.nested_raw_profile is None
            and record.chunk_index not in binary_profile_chunk_indexes
            and record.chunk_index not in issue_chunk_indexes
        ),
        *(
            png_textual_issue_diagnostic(issue)
            for issue in plan.issues
            if issue.chunk_index not in binary_profile_chunk_indexes
        ),
    ]


def png_textual_record_group(record: PngTextualChunkRecord) -> str:
    entry = png_textual_database_entry(record.keyword)
    if entry is not None:
        return entry.group2
    return "Image"


def png_textual_database_entry(keyword: str) -> PngTextualTagDatabaseEntry | None:
    database = png_textual_data_database_plan()
    try:
        return database.entry(keyword)
    except KeyError:
        lowered = keyword.lower()
        for entry in database.entries:
            if entry.keyword.lower() == lowered or entry.tag_name.lower() == lowered:
                return entry
        if "-" in keyword:
            return png_textual_database_entry(keyword.split("-", 1)[0])
    return None


def png_textual_record_tag_id(record: PngTextualChunkRecord) -> str:
    if record.language_code:
        return f"{record.keyword}-{record.language_code}"
    return record.keyword


def png_textual_record_source(record: PngTextualChunkRecord) -> str:
    return f"png-textual:{record.text_route}:{record.chunk_index}:{record.payload_offset}"


def png_textual_raw_profile_route_diagnostic(record: PngTextualChunkRecord) -> str:
    target = record.textual_subdirectory if record.textual_subdirectory is not None else "unknown"
    tag_name = record.tag_name if record.tag_name is not None else record.keyword
    return (
        "png_textual_route_handoff: "
        f"chunk_index={record.chunk_index}; "
        f"chunk_type={record.text_route}; "
        f"keyword={record.keyword}; "
        f"tag_name={tag_name}; "
        f"target_table={target}; "
        f"payload_bytes={len(record.value)}; "
        "nested_profile_decoding=deferred"
    )


def png_textual_issue_diagnostic(issue: PngTextualRuntimeIssue) -> str:
    return (
        "png_textual_issue: "
        f"chunk_index={issue.chunk_index}; "
        f"chunk_type={issue.chunk_type.decode('latin-1', errors='replace')}; "
        f"code={issue.code}; "
        f"reason={issue.reason}"
    )
