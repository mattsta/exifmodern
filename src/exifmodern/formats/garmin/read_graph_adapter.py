"""Garmin FIT adapter for the shared read graph contract."""

from __future__ import annotations

import time
from pathlib import Path

from exifmodern.dispatch_helpers import EvidenceAnchors, _references, _source_text
from exifmodern.formats.garmin.metadata_transaction_plan import (
    GarminDecodedFieldPlan,
    build_garmin_metadata_transaction_plan,
)
from exifmodern.formats.public_payload import (
    oversized_public_payload_graph,
    read_public_document_payload,
)
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance, TagValue

GARMIN_HEADER_EVIDENCE_ID = "garmin.fit.header"


def is_fit_prefix(data: bytes, path: Path | None = None) -> bool:
    return len(data) >= 12 and data[8:12] == b".FIT"


def build_garmin_read_graph_from_file(path: Path, *, source_file: str) -> ReadGraph:
    data = read_public_document_payload(path)
    if data is None:
        return oversized_public_payload_graph(source_file, format_name="Garmin FIT")
    return build_garmin_read_graph(data, source_file=source_file)


def build_garmin_read_graph(data: bytes, *, source_file: str) -> ReadGraph:
    plan = build_garmin_metadata_transaction_plan(data)
    diagnostics = [
        f"Garmin FIT package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
        if gate.code != "planner_is_non_mutating"
    ]
    diagnostics.extend(
        f"Garmin FIT package-local reader blocker: {blocker.code}: {blocker.reason}"
        for blocker in plan.blockers
    )
    tags: list[ReadTag] = []
    if not any(blocker.code.startswith("truncated_fit_header") for blocker in plan.blockers):
        tags.extend(_exiftool_warning_tags())
        tags.extend(_file_type_tags())
        if plan.header.protocol_version is not None:
            tags.append(
                _tag(
                    "ProtocolVersion",
                    plan.header.protocol_version,
                    "vers",
                    "File",
                    "Image::ExifTool::Garmin::FIT",
                    _references(plan.header),
                )
            )
    tags.extend(_field_tag(field, ordinal) for ordinal, field in enumerate(plan.decoded_fields))
    composite_position = _composite_gps_position_tag(plan.decoded_fields)
    if composite_position is not None:
        tags.append(composite_position)
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=int(time.time()),
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )


def _file_type_tags() -> list[ReadTag]:
    return [
        _tag("FileType", "FIT", "FileType", "File", "Image::ExifTool::File", ()),
        _tag(
            "FileTypeExtension",
            "fit",
            "FileTypeExtension",
            "File",
            "Image::ExifTool::File",
            (),
        ),
        _tag(
            "MIMEType",
            "application/fit",
            "MIMEType",
            "File",
            "Image::ExifTool::File",
            (),
        ),
    ]


def _exiftool_warning_tags() -> list[ReadTag]:
    return [
        _tag(
            "Warning",
            "[minor] Use ExtractEmbedded option to extract all timed metadata",
            "Warning",
            "ExifTool",
            "Image::ExifTool",
            (GARMIN_HEADER_EVIDENCE_ID,),
        )
    ]


def _field_tag(field: GarminDecodedFieldPlan, ordinal: int) -> ReadTag:
    return ReadTag(
        name=field.field_name,
        value=_field_value(field),
        provenance=TagProvenance(
            group="Garmin",
            table_name=f"Image::ExifTool::Garmin::{field.message_name}",
            tag_id=str(field.field_number),
            source=_source_text(_references(field)),
            family_0_group="Garmin",
            family_1_group=field.message_name,
            family_2_group="Location" if field.group in {"gps", "track"} else "Other",
            duplicate_instance_ordinal=ordinal,
        ),
        schema=None,
    )


def _field_value(field: GarminDecodedFieldPlan) -> TagValue:
    value = field.print_value if field.print_value is not None else field.value
    if isinstance(value, bytes):
        return BinaryTagValue(value)
    return value


def _composite_gps_position_tag(
    fields: tuple[GarminDecodedFieldPlan, ...],
) -> ReadTag | None:
    latitude = next(
        (
            field
            for field in fields
            if field.field_name == "GPSLatitude" and isinstance(field.print_value, str)
        ),
        None,
    )
    longitude = next(
        (
            field
            for field in fields
            if field.field_name == "GPSLongitude" and isinstance(field.print_value, str)
        ),
        None,
    )
    if latitude is None or longitude is None:
        return None
    return _tag(
        "GPSPosition",
        f"{latitude.print_value}, {longitude.print_value}",
        "GPSPosition",
        "Composite",
        "Image::ExifTool::Composite",
        (*_references(latitude), *_references(longitude)),
    )


def _tag(
    name: str,
    value: TagValue,
    tag_id: str,
    group: str,
    table_name: str,
    references: EvidenceAnchors,
) -> ReadTag:
    anchors = references or (GARMIN_HEADER_EVIDENCE_ID,)
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group=group,
            table_name=table_name,
            tag_id=tag_id,
            source=_source_text(anchors),
            family_0_group=group,
            family_1_group=group,
            family_2_group="Other",
        ),
        schema=None,
    )
