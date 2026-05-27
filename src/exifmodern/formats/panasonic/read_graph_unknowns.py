"""Panasonic MakerNote unknown-tag read-graph adapters."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.panasonic.read_makernote import (
    PANASONIC_LEICA5_FOCUSINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
    PANASONIC_LEICA_SERIALINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
    PANASONIC_TIMEINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
    collect_panasonic_leica5_focusinfo_process_binary_unknown_read_tags,
    collect_panasonic_leica5_shotinfo_process_binary_unknown_diagnostics,
    collect_panasonic_leica_serialinfo_process_binary_unknown_read_tags,
    collect_panasonic_timeinfo_process_binary_unknown_read_tags,
)

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadTag


def add_optional_panasonic_leica_process_binarydata_unknown_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
) -> None:
    from exifmodern.read_graph import append_process_binarydata_unknown_tags

    panasonic_leica_serialinfo_result = (
        collect_panasonic_leica_serialinfo_process_binary_unknown_read_tags(path)
    )
    append_process_binarydata_unknown_tags(
        tags,
        diagnostics,
        panasonic_leica_serialinfo_result,
        group="MakerNotes",
        table_name="Image::ExifTool::Panasonic::SerialInfo",
        provenance_source=PANASONIC_LEICA_SERIALINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
        family_0_group="MakerNotes",
        family_1_group="Leica",
        family_2_group="Camera",
    )
    panasonic_leica5_focusinfo_result = (
        collect_panasonic_leica5_focusinfo_process_binary_unknown_read_tags(path)
    )
    append_process_binarydata_unknown_tags(
        tags,
        diagnostics,
        panasonic_leica5_focusinfo_result,
        group="MakerNotes",
        table_name="Image::ExifTool::Panasonic::FocusInfo",
        provenance_source=PANASONIC_LEICA5_FOCUSINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
        family_0_group="MakerNotes",
        family_1_group="Leica",
        family_2_group="Camera",
    )
    diagnostics.extend(collect_panasonic_leica5_shotinfo_process_binary_unknown_diagnostics(path))


def add_optional_panasonic_timeinfo_process_binarydata_unknown_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
) -> None:
    from exifmodern.read_graph import append_process_binarydata_unknown_tags

    panasonic_timeinfo_result = collect_panasonic_timeinfo_process_binary_unknown_read_tags(path)
    append_process_binarydata_unknown_tags(
        tags,
        diagnostics,
        panasonic_timeinfo_result,
        group="MakerNotes",
        table_name="Image::ExifTool::Panasonic::TimeInfo",
        provenance_source=PANASONIC_TIMEINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
        family_0_group="MakerNotes",
        family_1_group="Panasonic",
        family_2_group="Image",
    )
