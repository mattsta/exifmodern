"""JPEG APP-segment adapters for shared read-graph unknown tag synthesis."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.app_segments.adobe import (
    ADOBE_CM_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
    ADOBE_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
    collect_adobe_cm_process_binary_unknown_read_tags,
    collect_adobe_process_binary_unknown_read_tags,
)
from exifmodern.formats.jpeg.app_segments.avi1 import (
    AVI1_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
    collect_avi1_process_binary_unknown_read_tags,
)
from exifmodern.read_graph import ReadTag, append_process_binarydata_unknown_tags


def add_optional_jpeg_app_process_binarydata_unknown_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    group: str,
) -> None:
    if group == "AVI1":
        add_optional_avi1_process_binarydata_unknown_tags(tags, diagnostics, path)
        return
    if group == "AdobeCM":
        add_optional_adobe_cm_process_binarydata_unknown_tags(tags, diagnostics, path)
        return
    if group == "Adobe":
        add_optional_adobe_process_binarydata_unknown_tags(tags, diagnostics, path)


def add_optional_avi1_process_binarydata_unknown_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
) -> None:
    result = collect_avi1_process_binary_unknown_read_tags(path)
    append_process_binarydata_unknown_tags(
        tags,
        diagnostics,
        result,
        group="AVI1",
        table_name="Image::ExifTool::JPEG::AVI1",
        provenance_source=AVI1_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
        family_0_group="APP0",
        family_1_group="AVI1",
        family_2_group="Image",
    )


def add_optional_adobe_cm_process_binarydata_unknown_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
) -> None:
    result = collect_adobe_cm_process_binary_unknown_read_tags(path)
    append_process_binarydata_unknown_tags(
        tags,
        diagnostics,
        result,
        group="AdobeCM",
        table_name="Image::ExifTool::JPEG::AdobeCM",
        provenance_source=ADOBE_CM_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
        family_0_group="APP13",
        family_1_group="AdobeCM",
        family_2_group="Image",
    )


def add_optional_adobe_process_binarydata_unknown_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
) -> None:
    result = collect_adobe_process_binary_unknown_read_tags(path)
    append_process_binarydata_unknown_tags(
        tags,
        diagnostics,
        result,
        group="Adobe",
        table_name="Image::ExifTool::JPEG::Adobe",
        provenance_source=ADOBE_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
        family_0_group="APP14",
        family_1_group="Adobe",
        family_2_group="Image",
    )
