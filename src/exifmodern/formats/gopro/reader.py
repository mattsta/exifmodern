"""Package-local GoPro GPMF scalar reader surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.gopro.metadata_transaction_plan import (
    GOPRO_GPMF_TABLE_SOURCE,
    EvidenceAnchor,
    GoproDecodedValue,
    GoproMetadataEntryPlan,
    GoproMetadataTransactionPlan,
    GoproRecordPlan,
    build_gopro_metadata_transaction_plan,
)

type GoproReaderValue = GoproDecodedValue


@dataclass(frozen=True)
class GoproReadTag:
    name: str
    value: GoproReaderValue | None
    group0: str
    group2: str
    source_table: str
    tag_id: str
    path: tuple[str, ...]
    byte_range: tuple[int, int] | None
    evidence_anchors: tuple[EvidenceAnchor, ...]


@dataclass(frozen=True)
class GoproReadBlocker:
    code: str
    reason: str
    offset: int | None
    evidence_anchors: tuple[EvidenceAnchor, ...]


@dataclass(frozen=True)
class GoproReaderResult:
    plan: GoproMetadataTransactionPlan
    tags: tuple[GoproReadTag, ...]
    blockers: tuple[GoproReadBlocker, ...]


def read_gopro_gpmf_scalars(
    data: bytes,
    *,
    include_request_all_hidden: bool = False,
) -> GoproReaderResult:
    """Read deterministic GoPro GPMF scalar/list values without decoding private streams."""

    plan = build_gopro_metadata_transaction_plan(
        data,
        include_hidden_sample_fields=include_request_all_hidden,
    )
    ranges_by_path = {
        record.path: record.payload_range for record in _flatten_records(plan.records)
    }
    tags = tuple(
        GoproReadTag(
            name=entry.tag_name,
            value=entry.value,
            group0=entry.group0,
            group2=_group2_for_entry(entry),
            source_table=_source_table_for_entry(entry),
            tag_id=entry.tag_key,
            path=entry.path,
            byte_range=ranges_by_path.get(entry.path),
            evidence_anchors=entry.evidence_anchors or (GOPRO_GPMF_TABLE_SOURCE,),
        )
        for entry in plan.metadata_entries
        if entry.value is not None
    )
    blockers = tuple(
        GoproReadBlocker(gate.code, gate.reason, gate.offset, gate.evidence_anchors)
        for gate in plan.output_emission_gates
        if gate.blocks_emission and gate.code not in _READ_NON_BLOCKING_GATE_CODES
    )
    return GoproReaderResult(plan=plan, tags=tags, blockers=blockers)


def _flatten_records(records: tuple[GoproRecordPlan, ...]) -> tuple[GoproRecordPlan, ...]:
    flattened: list[GoproRecordPlan] = []
    for record in records:
        flattened.append(record)
        flattened.extend(_flatten_records(record.child_records))
    return tuple(flattened)


def _group2_for_role(role: str) -> str:
    if role == "gps_metadata":
        return "Location"
    if role == "time_metadata":
        return "Time"
    return "Camera"


def _group2_for_entry(entry: GoproMetadataEntryPlan) -> str:
    if entry.tag_key in {"GPS5", "GPS9", "GPRI", "GLPI"}:
        if entry.tag_name in {"GPSDateTime", "GPSDateTimeRaw"}:
            return "Time"
        return "Location"
    if entry.tag_key == "KBAT":
        return "Camera"
    return _group2_for_role(entry.role)


def _source_table_for_entry(entry: GoproMetadataEntryPlan) -> str:
    if entry.tag_key in {"GPS5", "GPS9", "GPRI", "GLPI", "KBAT"}:
        return f"Image::ExifTool::GoPro::{entry.tag_key}"
    return "Image::ExifTool::GoPro::GPMF"


_READ_NON_BLOCKING_GATE_CODES = frozenset(
    (
        "raw_payload_preservation_required",
        "planner_is_non_mutating",
        "gopro_writer_not_implemented",
    )
)
