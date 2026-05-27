"""Source-backed Unknown.pm static write request classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.exif.existing_scalar import (
    ExistingExifRationalWritePlan,
    focal_length_existing_rational_step,
)
from exifmodern.formats.unknown.metadata_transaction_plan import (
    UNKNOWN_EXIF_WRITE_ANCHOR,
    UNKNOWN_MAIN_TABLE_ANCHOR,
    UNKNOWN_T_ANCHOR,
)
from exifmodern.json_types import (
    JsonObject,
    json_string_array_value,
    json_string_value,
    load_json_object,
)
from exifmodern.write_plan import EvidenceAnchor

type UnknownWritePlanStatus = Literal[
    "runnable_with_existing_exif_scalar_writer",
    "source_mapped_deferred",
    "unsupported",
]
type UnknownWriteStepKind = Literal["exif_scalar_companion", "unknown_makernote_requested"]
type UnknownWriteBlockerCode = Literal[
    "unsupported_tag",
    "invalid_value",
    "missing_unknown_step",
    "unknown_maker_note_rewrite_deferred",
]

UNKNOWN_PUBLIC_RUNTIME_ANCHOR = EvidenceAnchor(
    path="tests/public/test_unknown_t_public_api.py",
    line_start=63,
    line_end=93,
    symbol="Unknown.t public FocalLength write",
    evidence=(
        "Public write_metadata already executes Unknown.t FocalLength=200 through "
        "the existing EXIF scalar writer while preserving Unknown maker-note tags."
    ),
)

EXIF_FOCAL_LENGTH_ANCHOR = EvidenceAnchor(
    "lib/Image/ExifTool/Exif.pm",
    2900,
    2908,
    "ExifIFD FocalLength",
    "ExifIFD tag 0x920a defines FocalLength as a writable rational scalar.",
)


@dataclass(frozen=True)
class UnknownWriteStepPlan:
    kind: UnknownWriteStepKind
    tag_name: str
    raw_value: str
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "raw_value": self.raw_value,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class UnknownWriteBlocker:
    code: UnknownWriteBlockerCode
    tag_name: str
    reason: str
    evidence_anchors: tuple[EvidenceAnchor, ...] = ()

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class UnknownWritePlan:
    request_id: str
    fixture: str
    status: UnknownWritePlanStatus
    exif_scalar_plan: ExistingExifRationalWritePlan
    steps: tuple[UnknownWriteStepPlan, ...]
    blockers: tuple[UnknownWriteBlocker, ...]
    evidence_anchors: tuple[EvidenceAnchor, ...]

    @property
    def can_run_public_writer(self) -> bool:
        return self.status == "runnable_with_existing_exif_scalar_writer"

    @property
    def mutates_unknown_maker_note(self) -> bool:
        return False

    def to_json(self) -> JsonObject:
        return {
            "blockers": [blocker.to_json() for blocker in self.blockers],
            "can_run_public_writer": self.can_run_public_writer,
            "fixture": self.fixture,
            "mutates_unknown_maker_note": self.mutates_unknown_maker_note,
            "request_id": self.request_id,
            "status": self.status,
            "steps": [step.to_json() for step in self.steps],
        }


def classify_unknown_write_request_file(request_path: Path) -> UnknownWritePlan:
    return classify_unknown_write_request_payload(load_json_object(request_path))


def classify_unknown_write_request_payload(payload: JsonObject) -> UnknownWritePlan:
    request_id = json_string_value(payload, "request_id") or ""
    fixture = json_string_value(payload, "fixture") or ""
    focal_length: str | None = None
    steps: list[UnknownWriteStepPlan] = []
    blockers: list[UnknownWriteBlocker] = []

    for argument in json_string_array_value(payload, "write_args"):
        if not argument.startswith("-") or "=" not in argument:
            continue
        tag_token, raw_value = argument[1:].split("=", 1)
        tag_name = normalized_write_tag(tag_token)
        if tag_name == "FocalLength":
            focal_length = raw_value
            steps.append(
                UnknownWriteStepPlan(
                    kind="exif_scalar_companion",
                    tag_name=tag_name,
                    raw_value=raw_value,
                    evidence_anchors=(EXIF_FOCAL_LENGTH_ANCHOR, UNKNOWN_T_ANCHOR),
                )
            )
        elif tag_name.startswith("Unknown_0x"):
            steps.append(
                UnknownWriteStepPlan(
                    kind="unknown_makernote_requested",
                    tag_name=tag_name,
                    raw_value=raw_value,
                    evidence_anchors=(UNKNOWN_MAIN_TABLE_ANCHOR,),
                )
            )
            blockers.append(
                UnknownWriteBlocker(
                    code="unknown_maker_note_rewrite_deferred",
                    tag_name=tag_name,
                    reason=(
                        "Unknown.pm delegates writes to the EXIF writer; this package-local "
                        "slice only classifies and preserves Unknown maker-note payloads."
                    ),
                    evidence_anchors=(UNKNOWN_EXIF_WRITE_ANCHOR,),
                )
            )
        else:
            blockers.append(
                UnknownWriteBlocker(
                    code="unsupported_tag",
                    tag_name=tag_name,
                    reason="Unknown static request classifier has no source-backed writer route.",
                )
            )

    scalar_steps = []
    if focal_length is None:
        blockers.append(
            UnknownWriteBlocker(
                code="missing_unknown_step",
                tag_name="Unknown",
                reason="Unknown.t static write request has no supported EXIF scalar step.",
            )
        )
    else:
        try:
            scalar_steps.append(focal_length_existing_rational_step(focal_length))
        except ValueError as error:
            blockers.append(
                UnknownWriteBlocker(
                    code="invalid_value",
                    tag_name="FocalLength",
                    reason=str(error),
                )
            )

    status: UnknownWritePlanStatus
    if blockers:
        status = "unsupported" if not steps else "source_mapped_deferred"
    else:
        status = "runnable_with_existing_exif_scalar_writer"
    return UnknownWritePlan(
        request_id=request_id,
        fixture=fixture,
        status=status,
        exif_scalar_plan=ExistingExifRationalWritePlan(tuple(scalar_steps)),
        steps=tuple(steps),
        blockers=tuple(blockers),
        evidence_anchors=(
            UNKNOWN_T_ANCHOR,
            UNKNOWN_MAIN_TABLE_ANCHOR,
            UNKNOWN_EXIF_WRITE_ANCHOR,
            UNKNOWN_PUBLIC_RUNTIME_ANCHOR,
        ),
    )


def normalized_write_tag(tag_token: str) -> str:
    tag = tag_token.removesuffix("-").removesuffix("#")
    _group, separator, leaf = tag.partition(":")
    return leaf if separator else tag


def evidence_anchor_to_json(reference: EvidenceAnchor) -> JsonObject:
    return {
        "evidence": reference.evidence,
        "line_end": reference.line_end,
        "line_start": reference.line_start,
        "path": reference.path,
        "symbol": reference.symbol,
    }
