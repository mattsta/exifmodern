"""Source-backed Sanyo static write request classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.makernote.inline_ifd import InlineMakerNoteScalarWritePlan
from exifmodern.formats.sanyo.maker_note import (
    SANYO_MAIN_SOURCE,
    SANYO_MAIN_TAG_SPECS,
    SANYO_WRITE_TEST_SOURCE,
    SanyoEvidenceId,
    build_sanyo_flash_mode_write_plan,
)
from exifmodern.json_types import (
    JsonObject,
    json_string_array_value,
    json_string_value,
    load_json_object,
)

type SanyoWritePlanStatus = Literal[
    "runnable_with_composed_jpeg_writer",
    "source_mapped_deferred",
    "unsupported",
]
type SanyoWriteStepKind = Literal["sanyo_makernote_in_place", "exif_scalar_companion"]
type SanyoWriteBlockerCode = Literal[
    "unsupported_tag",
    "invalid_value",
    "missing_sanyo_step",
    "maker_note_byte_mutation_deferred",
]

SANYO_EXIF_SCENE_CAPTURE_TYPE_SOURCE = "sanyo.write.exif_scene_capture_type"
SANYO_COMPOSED_RUNTIME_SOURCE = "sanyo.write.composed_runtime"


@dataclass(frozen=True)
class SanyoWriteStepPlan:
    kind: SanyoWriteStepKind
    tag_name: str
    raw_value: str
    evidence_ids: tuple[SanyoEvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "raw_value": self.raw_value,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class SanyoWriteBlocker:
    code: SanyoWriteBlockerCode
    tag_name: str
    reason: str
    evidence_ids: tuple[SanyoEvidenceId, ...] = ()

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class SanyoWritePlan:
    request_id: str
    fixture: str
    status: SanyoWritePlanStatus
    maker_note_plan: InlineMakerNoteScalarWritePlan | None
    steps: tuple[SanyoWriteStepPlan, ...]
    blockers: tuple[SanyoWriteBlocker, ...]
    evidence_ids: tuple[SanyoEvidenceId, ...]

    @property
    def can_run_composed_writer(self) -> bool:
        return self.status == "runnable_with_composed_jpeg_writer"

    def to_json(self) -> JsonObject:
        return {
            "blockers": [blocker.to_json() for blocker in self.blockers],
            "can_run_composed_writer": self.can_run_composed_writer,
            "fixture": self.fixture,
            "request_id": self.request_id,
            "status": self.status,
            "steps": [step.to_json() for step in self.steps],
        }


def classify_sanyo_write_request_file(request_path: Path) -> SanyoWritePlan:
    return classify_sanyo_write_request_payload(load_json_object(request_path))


def classify_sanyo_write_request_payload(payload: JsonObject) -> SanyoWritePlan:
    request_id = json_string_value(payload, "request_id") or ""
    fixture = json_string_value(payload, "fixture") or ""
    flash_mode: str | None = None
    steps: list[SanyoWriteStepPlan] = []
    blockers: list[SanyoWriteBlocker] = []

    for argument in json_string_array_value(payload, "write_args"):
        if not argument.startswith("-") or "=" not in argument:
            continue
        tag_token, raw_value = argument[1:].split("=", 1)
        tag_name = normalized_write_tag(tag_token)
        if tag_name == "FlashMode":
            flash_mode = raw_value
            steps.append(
                SanyoWriteStepPlan(
                    kind="sanyo_makernote_in_place",
                    tag_name=tag_name,
                    raw_value=raw_value,
                    evidence_ids=(SANYO_WRITE_TEST_SOURCE,),
                )
            )
        elif tag_name == "SceneCaptureType":
            steps.append(
                SanyoWriteStepPlan(
                    kind="exif_scalar_companion",
                    tag_name=tag_name,
                    raw_value=raw_value,
                    evidence_ids=(SANYO_EXIF_SCENE_CAPTURE_TYPE_SOURCE,),
                )
            )
        elif tag_name in {spec.tag_name for spec in SANYO_MAIN_TAG_SPECS.values()}:
            blockers.append(
                SanyoWriteBlocker(
                    code="maker_note_byte_mutation_deferred",
                    tag_name=tag_name,
                    reason=(
                        "Sanyo.pm declares this maker-note scalar, but the executable "
                        "static write seed only promotes t/Sanyo.t FlashMode."
                    ),
                    evidence_ids=(SANYO_MAIN_SOURCE,),
                )
            )
        else:
            blockers.append(
                SanyoWriteBlocker(
                    code="unsupported_tag",
                    tag_name=tag_name,
                    reason="Sanyo static request classifier has no source-backed writer route.",
                )
            )

    maker_note_plan: InlineMakerNoteScalarWritePlan | None = None
    if flash_mode is None:
        blockers.append(
            SanyoWriteBlocker(
                code="missing_sanyo_step",
                tag_name="Sanyo",
                reason="Sanyo request has no package-local maker-note write step.",
            )
        )
    else:
        try:
            maker_note_plan = build_sanyo_flash_mode_write_plan(flash_mode)
        except ValueError as error:
            blockers.append(
                SanyoWriteBlocker(
                    code="invalid_value",
                    tag_name="FlashMode",
                    reason=str(error),
                )
            )

    status: SanyoWritePlanStatus
    if blockers:
        status = "unsupported" if not steps else "source_mapped_deferred"
    else:
        status = "runnable_with_composed_jpeg_writer"
    return SanyoWritePlan(
        request_id=request_id,
        fixture=fixture,
        status=status,
        maker_note_plan=maker_note_plan,
        steps=tuple(steps),
        blockers=tuple(blockers),
        evidence_ids=(SANYO_WRITE_TEST_SOURCE, SANYO_COMPOSED_RUNTIME_SOURCE),
    )


def normalized_write_tag(tag_token: str) -> str:
    tag = tag_token.removesuffix("-").removesuffix("#")
    _group, separator, leaf = tag.partition(":")
    return leaf if separator else tag
