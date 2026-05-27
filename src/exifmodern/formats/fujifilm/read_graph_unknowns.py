"""FujiFilm MakerNote read-graph adapters."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.fujifilm.read_makernote import (
    FUJIFILM_AFCSETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
    FUJIFILM_DRIVESETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
    FUJIFILM_FOCUSSETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
    FUJIFILM_PRIORITYSETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
    FUJIFILM_SOURCE_TABLE,
    FUJIFILM_TABLE_LOCAL_BLOCKERS,
    collect_fujifilm_afcsettings_process_binary_unknown_read_tags,
    collect_fujifilm_drivesettings_process_binary_unknown_read_tags,
    collect_fujifilm_focussettings_process_binary_unknown_read_tags,
    collect_fujifilm_prioritysettings_process_binary_unknown_read_tags,
    read_fujifilm_maker_note_from_jpeg,
)

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraphRuntimeOptions, ReadTag, ReadTagSchema


def add_optional_fujifilm_maker_note_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    schema_map: dict[str, ReadTagSchema],
    runtime_options: ReadGraphRuntimeOptions,
) -> None:
    from exifmodern.read_graph import (
        ReadTag,
        schema_tag_key,
        vendor_maker_note_field_provenance,
    )

    try:
        result = read_fujifilm_maker_note_from_jpeg(path)
    except ValueError as exc:
        diagnostics.append(str(exc))
        return

    if runtime_options.requests_process_binarydata_unknowns:
        add_optional_fujifilm_process_binarydata_unknown_tags(tags, diagnostics, path)

    if not result.fields:
        diagnostics.extend(result.diagnostics)
        return
    for field in result.fields:
        tags.append(
            ReadTag(
                field.name,
                field.value,
                vendor_maker_note_field_provenance(
                    "FujiFilm",
                    FUJIFILM_SOURCE_TABLE,
                    field.tag_id,
                    field.family_2_group,
                ),
                schema_map.get(schema_tag_key("MakerNotes", field.name)),
            )
        )
    diagnostics.extend(result.diagnostics)


def add_optional_fujifilm_process_binarydata_unknown_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
) -> None:
    from exifmodern.read_graph import (
        append_process_binarydata_unknown_tags,
        append_unknown_table_local_blockers,
    )

    for fujifilm_unknown_result, table_name, provenance_source in (
        (
            collect_fujifilm_focussettings_process_binary_unknown_read_tags(path),
            "Image::ExifTool::FujiFilm::FocusSettings",
            FUJIFILM_FOCUSSETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
        ),
        (
            collect_fujifilm_prioritysettings_process_binary_unknown_read_tags(path),
            "Image::ExifTool::FujiFilm::PrioritySettings",
            FUJIFILM_PRIORITYSETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
        ),
        (
            collect_fujifilm_afcsettings_process_binary_unknown_read_tags(path),
            "Image::ExifTool::FujiFilm::AFCSettings",
            FUJIFILM_AFCSETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
        ),
        (
            collect_fujifilm_drivesettings_process_binary_unknown_read_tags(path),
            "Image::ExifTool::FujiFilm::DriveSettings",
            FUJIFILM_DRIVESETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
        ),
    ):
        append_process_binarydata_unknown_tags(
            tags,
            diagnostics,
            fujifilm_unknown_result,
            group="MakerNotes",
            table_name=table_name,
            provenance_source=provenance_source,
            family_0_group="MakerNotes",
            family_1_group="FujiFilm",
            family_2_group="Camera",
        )
    append_unknown_table_local_blockers(
        diagnostics,
        "FujiFilm ProcessBinaryData Unknown=2",
        tuple(blocker.message for blocker in FUJIFILM_TABLE_LOCAL_BLOCKERS),
    )
