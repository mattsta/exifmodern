"""AFCP trailer adapters for the shared read graph contract."""

from __future__ import annotations

import time

from exifmodern.formats.afcp.trailer_transaction_plan import (
    AFCP_EXTRACT_SOURCE,
    AFCP_TAG_TABLE_SOURCE,
    AfcpDirectoryEntryPlan,
    build_afcp_trailer_transaction_plan,
)
from exifmodern.formats.iptc.reader import parse_iptc_application_record
from exifmodern.json_types import JsonValue
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance, TagValue

AFCP_BINARY_SOURCE = "afcp.binary"

_IPTC_GROUPS: dict[str, str] = {
    "DateCreated": "Time",
    "By-line": "Author",
    "By-lineTitle": "Author",
    "Credit": "Author",
    "Source": "Author",
    "CopyrightNotice": "Author",
    "Writer-Editor": "Author",
    "City": "Location",
    "Province-State": "Location",
    "Country-PrimaryLocationName": "Location",
}


def build_afcp_read_graph(
    data: bytes,
    *,
    source_file: str,
    generated_at_epoch: int | None = None,
    scan_for_trailer: bool = False,
) -> ReadGraph:
    """Build a read graph for source-backed AFCP trailer entries."""

    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    plan = build_afcp_trailer_transaction_plan(
        data,
        allow_output_emission=True,
        scan_for_trailer=scan_for_trailer,
    )
    tags: list[ReadTag] = []
    diagnostics = [
        f"AFCP package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status == "planned":
        for entry in plan.directory_entries:
            tags.extend(_entry_tags(entry))
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )


def _entry_tags(entry: AfcpDirectoryEntryPlan) -> list[ReadTag]:
    if entry.payload is None:
        return []
    if entry.route == "text_value":
        return [_afcp_tag("Text", entry.payload.decode("latin-1", errors="replace"), "TEXT", entry)]
    if entry.route == "thumbnail_image" and entry.preview_payload is not None:
        return [
            _afcp_tag(
                "ThumbnailImage",
                BinaryTagValue(
                    entry.preview_payload,
                    media_type="image/jpeg",
                    file_extension="jpg",
                ),
                "Nail",
                entry,
                family_2_group="Preview",
                evidence_id=AFCP_BINARY_SOURCE,
            )
        ]
    if entry.route == "preview_image" and entry.preview_payload is not None:
        return [
            _afcp_tag(
                "PreviewImage",
                BinaryTagValue(
                    entry.preview_payload,
                    media_type="image/jpeg",
                    file_extension="jpg",
                ),
                "PrVw",
                entry,
                family_2_group="Preview",
                evidence_id=AFCP_BINARY_SOURCE,
            )
        ]
    if entry.route == "iptc_subdirectory":
        return _iptc_tags(entry)
    return []


def _iptc_tags(entry: AfcpDirectoryEntryPlan) -> list[ReadTag]:
    if entry.payload is None:
        return []
    values = parse_iptc_application_record(entry.payload)
    return [
        _iptc_tag(name, _tag_value(value), entry)
        for name, value in values.items()
        if _tag_value(value) is not None
    ]


def _tag_value(value: JsonValue) -> TagValue:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item for item in value if isinstance(item, str)]
    return str(value)


def _afcp_tag(
    name: str,
    value: TagValue,
    tag_id: str,
    entry: AfcpDirectoryEntryPlan,
    *,
    family_2_group: str = "Other",
    evidence_id: str = AFCP_TAG_TABLE_SOURCE,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="AFCP",
            table_name="Image::ExifTool::AFCP::Main",
            tag_id=tag_id,
            source=_entry_source(entry, evidence_id),
            family_0_group="AFCP",
            family_1_group="AFCP",
            family_2_group=family_2_group,
        ),
        schema=None,
    )


def _iptc_tag(name: str, value: TagValue, entry: AfcpDirectoryEntryPlan) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="IPTC",
            table_name="Image::ExifTool::IPTC::Main",
            tag_id=None,
            source=_entry_source(entry, AFCP_EXTRACT_SOURCE),
            family_0_group="IPTC",
            family_1_group="IPTC2",
            family_2_group=_IPTC_GROUPS.get(name, "Other"),
        ),
        schema=None,
    )


def _entry_source(entry: AfcpDirectoryEntryPlan, evidence_id: str) -> str:
    payload_range = entry.payload_range
    if payload_range is None:
        return evidence_id
    start, end = payload_range
    return f"afcp-entry:{entry.index}:{entry.tag_name}:{start}:{end}:{evidence_id}"
