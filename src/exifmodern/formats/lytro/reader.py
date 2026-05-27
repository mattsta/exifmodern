"""Package-local Lytro LFP scalar reader surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.lytro.metadata_transaction_plan import (
    LytroEvidenceId,
    LytroMetadataTransactionPlan,
    build_lytro_metadata_transaction_plan,
)
from exifmodern.json_types import JsonValue


@dataclass(frozen=True)
class LytroReadTag:
    name: str
    value: JsonValue
    rendered_value: str | None
    group0: str
    group2: str
    source_table: str
    tag_id: str
    segment_index: int
    payload_range: tuple[int, int]
    evidence_ids: tuple[LytroEvidenceId, ...]


@dataclass(frozen=True)
class LytroReadBlocker:
    code: str
    reason: str
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[LytroEvidenceId, ...]


@dataclass(frozen=True)
class LytroReaderResult:
    plan: LytroMetadataTransactionPlan
    tags: tuple[LytroReadTag, ...]
    blockers: tuple[LytroReadBlocker, ...]


def read_lytro_lfp_scalars(data: bytes) -> LytroReaderResult:
    plan = build_lytro_metadata_transaction_plan(data, allow_output_emission=True)
    tags: list[LytroReadTag] = []
    for segment in plan.segments:
        for tag in segment.metadata_tags:
            tags.append(
                LytroReadTag(
                    name=tag.tag_name,
                    value=tag.converted_value,
                    rendered_value=tag.print_value,
                    group0="Lytro",
                    group2=tag.group2,
                    source_table="Image::ExifTool::Lytro::Main",
                    tag_id=tag.raw_path,
                    segment_index=segment.index,
                    payload_range=segment.payload_range,
                    evidence_ids=tag.evidence_ids,
                )
            )
    blockers = tuple(
        LytroReadBlocker(
            blocker.code,
            blocker.reason,
            blocker.byte_range,
            blocker.evidence_ids,
        )
        for blocker in plan.blockers
    )
    return LytroReaderResult(plan=plan, tags=tuple(tags), blockers=blockers)
