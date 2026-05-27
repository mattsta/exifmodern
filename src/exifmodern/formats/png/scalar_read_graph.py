"""PNG scalar runtime adapters for the shared read graph contracts."""

from __future__ import annotations

import time

from exifmodern.formats.png.scalar_runtime import (
    PngScalarRuntimeIssue,
    PngScalarRuntimePlan,
    PngScalarTag,
    extract_png_scalar_runtime,
)
from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance


def build_png_scalar_read_graph(
    png_data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    return png_scalar_runtime_plan_to_read_graph(
        extract_png_scalar_runtime(png_data),
        source_file,
        generated_at_epoch,
    )


def png_scalar_runtime_plan_to_read_graph(
    plan: PngScalarRuntimePlan,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=[png_scalar_tag_to_read_tag(tag) for tag in plan.tags],
        diagnostics=[png_scalar_issue_diagnostic(issue) for issue in plan.issues],
    )


def png_scalar_tag_to_read_tag(tag: PngScalarTag) -> ReadTag:
    return ReadTag(
        name=tag.name,
        value=tag.value,
        provenance=TagProvenance(
            group=tag.group,
            table_name=tag.table_name,
            tag_id=tag.tag_id,
            source=f"png-scalar:{tag.chunk_type.decode('ascii')}:{tag.chunk_index}:{tag.payload_offset}",
            family_0_group=tag.family_0_group,
            family_1_group=tag.family_1_group,
            family_2_group=tag.family_2_group,
        ),
        schema=None,
    )


def png_scalar_issue_diagnostic(issue: PngScalarRuntimeIssue) -> str:
    return (
        "png_scalar_issue: "
        f"chunk_index={issue.chunk_index}; "
        f"chunk_type={issue.chunk_type.decode('latin-1', errors='replace')}; "
        f"code={issue.code}; "
        f"reason={issue.reason}"
    )
