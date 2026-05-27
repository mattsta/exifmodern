"""Audible AA adapters for the shared read graph contract."""

from __future__ import annotations

import time

from exifmodern.formats.audible.metadata_transaction_plan import (
    AUDIBLE_AA_CHAPTER_SOURCE,
    AUDIBLE_AA_COVER_SOURCE,
    AUDIBLE_MAIN_TABLE_SOURCE,
    AudibleCoverArtPlan,
    AudibleEmissionGate,
    AudibleMetadataEntryPlan,
    AudibleMetadataTransactionPlan,
    build_audible_metadata_transaction_plan,
)
from exifmodern.read_graph import (
    BinaryTagValue,
    ReadGraph,
    ReadTag,
    TagProvenance,
    TagValue,
)

AUDIBLE_FILE_TYPE_SOURCE = "audible.file_type"


def is_audible_aa_prefix(data: bytes) -> bool:
    """Return whether bytes satisfy ExifTool's AA magic gate."""

    return len(data) >= 8 and data[4:8] == b"\x57\x90\x75\x36"


def build_audible_read_graph(
    data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
    actual_file_size: int | None = None,
) -> ReadGraph:
    plan = build_audible_metadata_transaction_plan(data, actual_file_size=actual_file_size)
    return audible_transaction_plan_to_read_graph(plan, data, source_file, generated_at_epoch)


def audible_transaction_plan_to_read_graph(
    plan: AudibleMetadataTransactionPlan,
    data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    tags: list[ReadTag] = []
    if plan.header_validation.is_valid:
        tags.extend(_file_type_tags())
    tags.extend(_metadata_tags(plan.metadata_entries))
    tags.extend(_chapter_tags(plan))
    tags.extend(_cover_art_tags(plan.cover_art, data))
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=tags,
        diagnostics=_diagnostics(plan),
    )


def _file_type_tags() -> tuple[ReadTag, ...]:
    return (
        _file_tag("FileType", "AA", "FileType"),
        _file_tag("FileTypeExtension", "aa", "FileTypeExtension"),
        _file_tag("MIMEType", "audio/audible", "MIMEType"),
    )


def _metadata_tags(entries: tuple[AudibleMetadataEntryPlan, ...]) -> list[ReadTag]:
    return [
        _audible_tag(
            entry.name,
            _metadata_value(entry),
            entry.tag_id,
            _metadata_group2(entry.role),
            AUDIBLE_MAIN_TABLE_SOURCE,
        )
        for entry in entries
    ]


def _metadata_value(entry: AudibleMetadataEntryPlan) -> TagValue:
    tag_id = entry.tag_id.casefold()
    if tag_id == "price":
        return _float_value(entry.value)
    if tag_id in {
        "headerseed",
        "header_seed",
        "encryptedblocks",
        "encrypted_blocks",
        "license_list",
        "cputype",
        "cpu_type",
        "license_count",
    }:
        return _integer_value(entry.value)
    return entry.value


def _float_value(value: str) -> float | str:
    try:
        return float(value)
    except ValueError:
        return value


def _integer_value(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def _chapter_tags(plan: AudibleMetadataTransactionPlan) -> list[ReadTag]:
    return [
        _audible_tag(
            "ChapterCount",
            chapter.chapter_count,
            "_chapter_count",
            "Audio",
            AUDIBLE_AA_CHAPTER_SOURCE,
        )
        for chapter in plan.chapter_counts
    ]


def _cover_art_tags(cover_art: tuple[AudibleCoverArtPlan, ...], data: bytes) -> list[ReadTag]:
    tags: list[ReadTag] = []
    for cover in cover_art:
        payload = data[cover.payload_offset : cover.payload_offset + cover.payload_size]
        tags.append(
            _audible_tag(
                "CoverArt",
                BinaryTagValue(payload),
                "_cover_art",
                "Preview",
                AUDIBLE_AA_COVER_SOURCE,
            )
        )
    return tags


def _file_tag(name: str, value: TagValue, tag_id: str) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="File",
            table_name="Image::ExifTool::File",
            tag_id=tag_id,
            source=_evidence_id_text(AUDIBLE_FILE_TYPE_SOURCE),
            family_0_group="File",
            family_1_group="File",
            family_2_group="Other",
        ),
        schema=None,
    )


def _audible_tag(
    name: str,
    value: TagValue,
    tag_id: str,
    group2: str,
    evidence_id: str,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="Audible",
            table_name="Image::ExifTool::Audible::Main",
            tag_id=tag_id,
            source=_evidence_id_text(evidence_id),
            family_0_group="Audible",
            family_1_group="Audible",
            family_2_group=group2,
        ),
        schema=None,
    )


def _metadata_group2(role: str) -> str:
    if role in {"author", "copyright"}:
        return "Author"
    if role == "publish_date":
        return "Time"
    return "Audio"


def _diagnostics(plan: AudibleMetadataTransactionPlan) -> list[str]:
    diagnostics = [
        f"Audible package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
        if _is_read_gate(gate)
    ]
    if plan.header_validation.reason is not None:
        diagnostics.insert(
            0,
            f"Audible package-local reader status: {plan.header_validation.reason}",
        )
    if plan.header_validation.is_valid:
        diagnostics.append(
            "Audible package-local reader diagnostic: m4b_atoms_not_dispatched: "
            "Audible.pm also defines QuickTime tags/meta/cvrx/tseg tables; this "
            "AA reader only promotes ProcessAA chunk metadata."
        )
    return diagnostics


def _is_read_gate(gate: AudibleEmissionGate) -> bool:
    return gate.code not in {
        "planner_is_non_mutating",
        "full_audible_writer_not_implemented",
    }


def _evidence_id_text(evidence_id: str) -> str:
    return evidence_id
