"""Package-local RED/R3D scalar reader surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.red.metadata_transaction_plan import (
    RedEvidenceId,
    RedMetadataTransactionPlan,
    build_red_metadata_transaction_plan,
)

type RedReadValue = str | int | float


@dataclass(frozen=True)
class RedReadTag:
    name: str
    value: RedReadValue
    group0: str
    group2: str
    source_table: str
    tag_id: str
    byte_range: tuple[int, int]
    evidence_ids: tuple[RedEvidenceId, ...]


@dataclass(frozen=True)
class RedReadBlocker:
    code: str
    reason: str
    evidence_ids: tuple[RedEvidenceId, ...]


@dataclass(frozen=True)
class RedReaderResult:
    plan: RedMetadataTransactionPlan
    tags: tuple[RedReadTag, ...]
    blockers: tuple[RedReadBlocker, ...]


def read_red_r3d_scalars(data: bytes) -> RedReaderResult:
    plan = build_red_metadata_transaction_plan(data, allow_output_emission=True)
    tags: list[RedReadTag] = []
    for field in plan.header_fields:
        value: RedReadValue | None
        if isinstance(field.numeric_value, float) and field.value_text is not None:
            value = _float_text_value(field.value_text)
        else:
            value = field.numeric_value if field.numeric_value is not None else field.value_text
        if value is not None:
            tags.append(
                RedReadTag(
                    name=field.name,
                    value=value,
                    group0="Red",
                    group2=_group2_for_responsibility(field.responsibility),
                    source_table=f"Image::ExifTool::Red::RED{plan.version or ''}",
                    tag_id=field.name,
                    byte_range=(field.byte_range_start, field.byte_range_end),
                    evidence_ids=field.evidence_ids,
                )
            )
    for entry in plan.directory.entries:
        value = entry.value_text
        if value is not None:
            tags.append(
                RedReadTag(
                    name=entry.tag_name,
                    value=value,
                    group0="Red",
                    group2=_group2_for_responsibility(entry.responsibility),
                    source_table="Image::ExifTool::Red::Main",
                    tag_id=f"0x{entry.tag_id:04x}",
                    byte_range=(entry.payload_range_start, entry.payload_range_end),
                    evidence_ids=entry.evidence_ids,
                )
            )
    blockers = tuple(
        RedReadBlocker(gate.code, gate.reason, gate.evidence_ids)
        for gate in plan.output_emission_gates
    )
    return RedReaderResult(plan=plan, tags=tuple(tags), blockers=blockers)


def _group2_for_responsibility(responsibility: str) -> str:
    if responsibility == "timecode_metadata":
        return "Time"
    if responsibility in {"clip_metadata", "video_metadata"}:
        return "Video"
    if responsibility == "audio_metadata":
        return "Audio"
    return "Camera"


def _float_text_value(value: str) -> float | str:
    try:
        return float(value)
    except ValueError:
        return value
