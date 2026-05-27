"""PhotoCD adapter for the shared read graph contract."""

from __future__ import annotations

import time
from pathlib import Path

from exifmodern.formats.photocd.metadata_transaction_plan import (
    PHOTOCD_IMAGE_SIZE_SOURCE,
    PHOTOCD_MAIN_TABLE_SOURCE,
    PHOTOCD_PROCESS_SOURCE,
    PhotoCdMetadataTransactionPlan,
    PhotoCdRecordPlan,
    build_photocd_metadata_transaction_plan,
)
from exifmodern.formats.public_payload import (
    oversized_public_payload_graph,
    read_public_document_payload,
)
from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance, TagValue


def build_photocd_read_graph_from_file(path: Path, *, source_file: str) -> ReadGraph:
    data = read_public_document_payload(path)
    if data is None:
        return oversized_public_payload_graph(source_file, format_name="PhotoCD")
    return build_photocd_read_graph(data, source_file=source_file)


def build_photocd_read_graph(data: bytes, *, source_file: str) -> ReadGraph:
    plan = build_photocd_metadata_transaction_plan(data, allow_output_emission=True)
    diagnostics = [
        f"PhotoCD package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    tags: list[ReadTag] = []
    if plan.status == "planned":
        tags.extend(_file_type_tags())
        tags.extend(_record_tags(plan))
        tags.extend(_image_metadata_tags(plan))
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=int(time.time()),
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )


def _file_type_tags() -> list[ReadTag]:
    return [
        _tag("FileType", "PCD", "FileType", "File", "Image::ExifTool::File", ()),
        _tag(
            "FileTypeExtension",
            "pcd",
            "FileTypeExtension",
            "File",
            "Image::ExifTool::File",
            (),
        ),
        _tag("MIMEType", "image/x-photo-cd", "MIMEType", "File", "Image::ExifTool::File", ()),
    ]


def _record_tags(plan: PhotoCdMetadataTransactionPlan) -> list[ReadTag]:
    return [
        _record_tag(record)
        for record in plan.directory.records
        if record.eligible
        and not record.is_unknown
        and record.parsed_value is not None
        and record.name not in {"Signature", "HasSBA", "Orientation"}
    ]


def _record_tag(record: PhotoCdRecordPlan) -> ReadTag:
    return _tag(
        record.name,
        _render_record_value(record),
        record.name,
        "PhotoCD",
        "Image::ExifTool::PhotoCD::Main",
        record.evidence_ids,
    )


def _image_metadata_tags(plan: PhotoCdMetadataTransactionPlan) -> list[ReadTag]:
    photocd_values: tuple[tuple[str, TagValue], ...] = (
        ("Orientation", _render_orientation(plan.image_metadata.orientation_code)),
        ("ImageWidth", plan.image_metadata.image_width),
        ("ImageHeight", plan.image_metadata.image_height),
        (
            "CompressionClass",
            _render_compression_class(plan.image_metadata.compression_class),
        ),
    )
    tags = [
        _tag(
            name,
            value,
            name,
            "PhotoCD",
            "Image::ExifTool::PhotoCD::Main",
            (PHOTOCD_IMAGE_SIZE_SOURCE, PHOTOCD_PROCESS_SOURCE),
        )
        for name, value in photocd_values
        if value is not None
    ]
    composite_values: tuple[tuple[str, TagValue], ...] = (
        ("ImageSize", _render_image_size(plan)),
        ("Megapixels", _render_megapixels(plan)),
    )
    tags.extend(
        _tag(
            name,
            value,
            f"Exif-{name}",
            "Composite",
            "Image::ExifTool::Composite",
            (PHOTOCD_IMAGE_SIZE_SOURCE, PHOTOCD_PROCESS_SOURCE),
        )
        for name, value in composite_values
        if value is not None
    )
    return tags


def _render_record_value(record: PhotoCdRecordPlan) -> TagValue:
    value = record.parsed_value
    if record.name == "ImageMedium" and isinstance(value, int):
        return _IMAGE_MEDIUM.get(value, value)
    if record.name == "CharacterSet" and isinstance(value, int):
        return _CHARACTER_SET.get(value, value)
    if record.name == "ScannerPixelSize" and isinstance(value, str):
        return f"{value} micrometers"
    if record.name == "SceneBalanceAlgorithmCommand" and isinstance(value, int):
        return _SBA_COMMAND.get(value, value)
    if record.name == "SceneBalanceAlgorithmFilmID" and isinstance(value, int):
        return _SBA_FILM_ID.get(value, value)
    if record.name == "CopyrightStatus" and isinstance(value, int):
        return _COPYRIGHT_STATUS.get(value, value)
    if record.name in {"CreateDate", "ModifyDate"} and isinstance(value, int):
        return _render_unix_time(value)
    return value


def _render_unix_time(value: int) -> str:
    rendered = time.strftime("%Y:%m:%d %H:%M:%S%z", time.localtime(value))
    return f"{rendered[:-2]}:{rendered[-2:]}"


def _render_orientation(code: int | None) -> str | None:
    if code is None:
        return None
    return _ORIENTATION.get(code, f"Unknown ({code})")


def _render_compression_class(code: int | None) -> str | None:
    if code is None:
        return None
    return _COMPRESSION_CLASS.get(code, f"Unknown ({code})")


def _render_image_size(plan: PhotoCdMetadataTransactionPlan) -> str | None:
    width = plan.image_metadata.image_width
    height = plan.image_metadata.image_height
    if width is None or height is None:
        return None
    return f"{width}x{height}"


def _render_megapixels(plan: PhotoCdMetadataTransactionPlan) -> float | None:
    width = plan.image_metadata.image_width
    height = plan.image_metadata.image_height
    if width is None or height is None:
        return None
    return round(width * height / 1_000_000, 1)


def _tag(
    name: str,
    value: TagValue,
    tag_id: str,
    group: str,
    table_name: str,
    evidence_ids: tuple[str, ...],
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group=group,
            table_name=table_name,
            tag_id=tag_id,
            source=_evidence_id_text(evidence_ids),
            family_0_group=group,
            family_1_group=group,
            family_2_group="Image" if group == "PhotoCD" else "Other",
        ),
        schema=None,
    )


def _evidence_id_text(evidence_ids: tuple[str, ...]) -> str:
    return (evidence_ids or (PHOTOCD_MAIN_TABLE_SOURCE,))[0]


_IMAGE_MEDIUM: dict[int, str] = {
    0: "Color negative",
    1: "Color reversal",
    2: "Color hard copy",
    3: "Thermal hard copy",
    4: "Black and white negative",
    5: "Black and white reversal",
    6: "Black and white hard copy",
    7: "Internegative",
    8: "Synthetic image",
}
_CHARACTER_SET: dict[int, str] = {
    1: "38 characters ISO 646",
    2: "65 characters ISO 646",
    3: "95 characters ISO 646",
    4: "191 characters ISO 8850-1",
    5: "ISO 2022",
    6: "Includes characters not ISO 2375 registered",
}
_SBA_COMMAND: dict[int, str] = {
    0: "Neutral SBA On, Color SBA On",
    1: "Neutral SBA Off, Color SBA Off",
    2: "Neutral SBA On, Color SBA Off",
    3: "Neutral SBA Off, Color SBA On",
}
_SBA_FILM_ID: dict[int, str] = {
    72: "Kodak Gold 100 Gen 2",
}
_COPYRIGHT_STATUS: dict[int, str] = {
    0: "Copyright restrictions apply",
    1: "Public domain",
    0xFF: "Not specified",
}
_ORIENTATION: dict[int, str] = {
    0: "Horizontal (normal)",
    1: "Rotate 270 CW",
    2: "Rotate 180",
    3: "Rotate 90 CW",
}
_COMPRESSION_CLASS: dict[int, str] = {
    0: "Class 1 - 35mm film; Pictoral hard copy",
    1: "Class 2 - Large format film",
    2: "Class 3 - Text and graphics, high resolution",
    3: "Class 4 - Text and graphics, high dynamic range",
}
