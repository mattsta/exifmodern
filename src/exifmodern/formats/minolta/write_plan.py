"""Minolta static write request classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.makernote.binary_data import MakerNoteBinaryDataWritePlan
from exifmodern.formats.minolta.maker_note import (
    MINOLTA_CAMERA_SETTINGS_SOURCE_ID,
    MINOLTA_MAIN_SOURCE_ID,
    MINOLTA_WRITE_TEST_SOURCE_ID,
    build_minolta_date_write_plan,
)
from exifmodern.json_types import (
    JsonObject,
    json_string_array_value,
    json_string_value,
    load_json_object,
)

type MinoltaWritePlanStatus = Literal[
    "runnable_with_composed_jpeg_writer",
    "source_mapped_deferred",
    "unsupported",
]
type MinoltaWriteStepKind = Literal[
    "minolta_binary_makernote_in_place",
    "iptc_scalar_companion",
    "minolta_mrw_ttw_requested",
]
type MinoltaWriteBlockerCode = Literal[
    "unsupported_tag",
    "invalid_value",
    "missing_minolta_step",
    "mrw_ttw_output_deferred",
]

MINOLTA_IPTC_CAPTION_ABSTRACT_SOURCE_ID = "minolta.write.iptc_caption_abstract"
MINOLTA_RAW_MAIN_SOURCE_ID = "minolta.write.mrw_main"
MINOLTA_RAW_WRITE_SOURCE_ID = "minolta.write.mrw_write"
MINOLTA_RAW_WRITE_TEST_SOURCE_ID = "minolta.write.mrw_test_4"
MINOLTA_COMPOSED_RUNTIME_SOURCE_ID = "minolta.write.composed_runtime"


@dataclass(frozen=True)
class MinoltaWriteStepPlan:
    kind: MinoltaWriteStepKind
    tag_name: str
    raw_value: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "raw_value": self.raw_value,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class MinoltaWriteBlocker:
    code: MinoltaWriteBlockerCode
    tag_name: str
    reason: str
    evidence_ids: tuple[str, ...] = ()

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class MinoltaWritePlan:
    request_id: str
    fixture: str
    status: MinoltaWritePlanStatus
    maker_note_plan: MakerNoteBinaryDataWritePlan | None
    steps: tuple[MinoltaWriteStepPlan, ...]
    blockers: tuple[MinoltaWriteBlocker, ...]
    evidence_ids: tuple[str, ...]

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


def classify_minolta_write_request_file(request_path: Path) -> MinoltaWritePlan:
    return classify_minolta_write_request_payload(load_json_object(request_path))


def classify_minolta_write_request_payload(payload: JsonObject) -> MinoltaWritePlan:
    request_id = json_string_value(payload, "request_id") or ""
    fixture = json_string_value(payload, "fixture") or ""
    minolta_date: str | None = None
    steps: list[MinoltaWriteStepPlan] = []
    blockers: list[MinoltaWriteBlocker] = []

    for argument in json_string_array_value(payload, "write_args"):
        if not argument.startswith("-") or "=" not in argument:
            continue
        tag_token, raw_value = argument[1:].split("=", 1)
        tag_name = normalized_write_tag(tag_token)
        if tag_name == "MinoltaDate" and not fixture.endswith(".mrw"):
            minolta_date = raw_value
            steps.append(
                MinoltaWriteStepPlan(
                    kind="minolta_binary_makernote_in_place",
                    tag_name=tag_name,
                    raw_value=raw_value,
                    evidence_ids=(MINOLTA_WRITE_TEST_SOURCE_ID,),
                )
            )
        elif tag_name == "Caption-Abstract":
            steps.append(
                MinoltaWriteStepPlan(
                    kind="iptc_scalar_companion",
                    tag_name=tag_name,
                    raw_value=raw_value,
                    evidence_ids=(MINOLTA_IPTC_CAPTION_ABSTRACT_SOURCE_ID,),
                )
            )
        elif fixture.endswith(".mrw") and tag_name in {"FocusMode", "LastFileNumber"}:
            steps.append(
                MinoltaWriteStepPlan(
                    kind="minolta_mrw_ttw_requested",
                    tag_name=tag_name,
                    raw_value=raw_value,
                    evidence_ids=(MINOLTA_RAW_WRITE_TEST_SOURCE_ID,),
                )
            )
            blockers.append(
                MinoltaWriteBlocker(
                    code="mrw_ttw_output_deferred",
                    tag_name=tag_name,
                    reason=(
                        "Minolta MRW TTW scalar mutation is source-mapped, but whole MRW "
                        "TTW payload rebuild/output remains gated."
                    ),
                    evidence_ids=(
                        MINOLTA_RAW_MAIN_SOURCE_ID,
                        MINOLTA_RAW_WRITE_SOURCE_ID,
                        MINOLTA_RAW_WRITE_TEST_SOURCE_ID,
                    ),
                )
            )
        else:
            blockers.append(
                MinoltaWriteBlocker(
                    code="unsupported_tag",
                    tag_name=tag_name,
                    reason="Minolta static request classifier has no source-backed writer route.",
                )
            )

    maker_note_plan: MakerNoteBinaryDataWritePlan | None = None
    if minolta_date is None and not fixture.endswith(".mrw"):
        blockers.append(
            MinoltaWriteBlocker(
                code="missing_minolta_step",
                tag_name="Minolta",
                reason="Minolta JPEG request has no package-local maker-note write step.",
            )
        )
    elif minolta_date is not None:
        try:
            maker_note_plan = build_minolta_date_write_plan(minolta_date)
        except ValueError as error:
            blockers.append(
                MinoltaWriteBlocker(
                    code="invalid_value",
                    tag_name="MinoltaDate",
                    reason=str(error),
                )
            )

    status: MinoltaWritePlanStatus
    if blockers:
        status = "unsupported" if not steps else "source_mapped_deferred"
    else:
        status = "runnable_with_composed_jpeg_writer"
    return MinoltaWritePlan(
        request_id=request_id,
        fixture=fixture,
        status=status,
        maker_note_plan=maker_note_plan,
        steps=tuple(steps),
        blockers=tuple(blockers),
        evidence_ids=(
            MINOLTA_MAIN_SOURCE_ID,
            MINOLTA_CAMERA_SETTINGS_SOURCE_ID,
            MINOLTA_WRITE_TEST_SOURCE_ID,
            MINOLTA_COMPOSED_RUNTIME_SOURCE_ID,
        ),
    )


def normalized_write_tag(tag_token: str) -> str:
    tag = tag_token.removesuffix("-").removesuffix("#")
    _group, separator, leaf = tag.partition(":")
    return leaf if separator else tag
