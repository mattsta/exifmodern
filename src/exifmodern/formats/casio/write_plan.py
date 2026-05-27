"""Source-backed Casio static write request classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.casio.maker_note import (
    CASIO_TYPE1_FIRMWARE_DATE_SOURCE,
    CASIO_TYPE2_FIRMWARE_DATE_SOURCE,
    CASIO_WRITE_TEST_SOURCE,
    CasioMakerNoteFamily,
    CasioMakerNoteWritePlan,
    build_casio_maker_note_write_plan,
)
from exifmodern.json_types import (
    JsonObject,
    json_string_array_value,
    json_string_value,
    load_json_object,
)

type CasioWritePlanStatus = Literal[
    "runnable_with_composed_jpeg_writer",
    "source_mapped_deferred",
    "unsupported",
]
type CasioWriteStepKind = Literal["casio_makernote_in_place", "exif_scalar_companion"]
type CasioWriteBlockerCode = Literal[
    "unsupported_tag",
    "invalid_value",
    "missing_casio_step",
    "maker_note_byte_mutation_deferred",
    "composed_runtime_route_deferred",
    "protected_data_deferred",
]

CASIO_EXIF_RESOLUTION_SOURCE = "format.casio.writer.exif.resolution"
CASIO_EXIF_MAX_APERTURE_SOURCE = "format.casio.writer.exif.max_aperture"
CASIO_COMPOSED_RUNTIME_SOURCE = "format.casio.writer.composed_runtime_route"
CASIO_TYPE1_WRITABLE_SCALAR_SOURCE = "format.casio.writer.type1.deferred_scalars"
CASIO_TYPE2_PROTECTED_PREVIEW_SOURCE = "format.casio.writer.type2.protected_preview"
CASIO_TYPE2_WRITABLE_SCALAR_SOURCE = "format.casio.writer.type2.deferred_scalars"

SOURCE_BACKED_DEFERRED_CASIO_TAGS = {
    "Quality": (
        CASIO_TYPE1_WRITABLE_SCALAR_SOURCE,
        "source-declared Type1 scalar is not in the executable Casio.t write slice.",
    ),
    "RecordingMode": (
        CASIO_TYPE1_WRITABLE_SCALAR_SOURCE,
        "source-declared Type1 scalar is not in the executable Casio.t write slice.",
    ),
    "WhiteBalance": (
        CASIO_TYPE2_WRITABLE_SCALAR_SOURCE,
        "ambiguous Casio tag name spans multiple maker-note tables; "
        "no safe family-specific route is implemented.",
    ),
    "QualityMode": (
        CASIO_TYPE2_WRITABLE_SCALAR_SOURCE,
        "source-declared Type2 scalar is not in the executable Casio.t write slice.",
    ),
    "PreviewImageLength": (
        CASIO_TYPE2_PROTECTED_PREVIEW_SOURCE,
        "protected Type2 preview-image offset-pair mutation is not implemented.",
    ),
    "PreviewImageStart": (
        CASIO_TYPE2_PROTECTED_PREVIEW_SOURCE,
        "protected Type2 preview-image offset-pair mutation is not implemented.",
    ),
}


@dataclass(frozen=True)
class CasioWriteStepPlan:
    kind: CasioWriteStepKind
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
class CasioWriteBlocker:
    code: CasioWriteBlockerCode
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
class CasioWritePlan:
    request_id: str
    fixture: str
    status: CasioWritePlanStatus
    maker_note_plan: CasioMakerNoteWritePlan | None
    steps: tuple[CasioWriteStepPlan, ...]
    blockers: tuple[CasioWriteBlocker, ...]
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


def classify_casio_write_request_file(request_path: Path) -> CasioWritePlan:
    return classify_casio_write_request_payload(load_json_object(request_path))


def classify_casio_write_request_payload(payload: JsonObject) -> CasioWritePlan:
    request_id = json_string_value(payload, "request_id") or ""
    fixture = json_string_value(payload, "fixture") or ""
    focus_mode: str | None = None
    object_distance: str | None = None
    firmware_date: str | None = None
    steps: list[CasioWriteStepPlan] = []
    blockers: list[CasioWriteBlocker] = []

    for argument in json_string_array_value(payload, "write_args"):
        if not argument.startswith("-") or "=" not in argument:
            continue
        tag_token, raw_value = argument[1:].split("=", 1)
        tag_name = normalized_write_tag(tag_token)
        if tag_name == "FocusMode":
            focus_mode = raw_value
            steps.append(
                CasioWriteStepPlan(
                    kind="casio_makernote_in_place",
                    tag_name=tag_name,
                    raw_value=raw_value,
                    evidence_ids=(CASIO_WRITE_TEST_SOURCE,),
                )
            )
        elif tag_name == "ObjectDistance":
            object_distance = raw_value
            steps.append(
                CasioWriteStepPlan(
                    kind="casio_makernote_in_place",
                    tag_name=tag_name,
                    raw_value=raw_value,
                    evidence_ids=(CASIO_WRITE_TEST_SOURCE,),
                )
            )
        elif tag_name == "FirmwareDate":
            firmware_date = raw_value
        elif tag_name in {"XResolution", "YResolution"}:
            steps.append(
                CasioWriteStepPlan(
                    kind="exif_scalar_companion",
                    tag_name=tag_name,
                    raw_value=raw_value,
                    evidence_ids=(CASIO_EXIF_RESOLUTION_SOURCE,),
                )
            )
        elif tag_name == "MaxApertureValue":
            steps.append(
                CasioWriteStepPlan(
                    kind="exif_scalar_companion",
                    tag_name=tag_name,
                    raw_value=raw_value,
                    evidence_ids=(CASIO_EXIF_MAX_APERTURE_SOURCE,),
                )
            )
        elif tag_name in SOURCE_BACKED_DEFERRED_CASIO_TAGS:
            evidence_id, reason = SOURCE_BACKED_DEFERRED_CASIO_TAGS[tag_name]
            blocker_code: CasioWriteBlockerCode = "maker_note_byte_mutation_deferred"
            if tag_name in {"PreviewImageLength", "PreviewImageStart"}:
                blocker_code = "protected_data_deferred"
            blockers.append(
                CasioWriteBlocker(
                    code=blocker_code,
                    tag_name=tag_name,
                    reason=reason,
                    evidence_ids=(evidence_id,),
                )
            )
        else:
            blockers.append(
                CasioWriteBlocker(
                    code="unsupported_tag",
                    tag_name=tag_name,
                    reason="Casio static request classifier has no source-backed writer route.",
                )
            )

    firmware_date_family = infer_casio_firmware_date_family(fixture, focus_mode, object_distance)
    if firmware_date is not None:
        steps.append(
            CasioWriteStepPlan(
                kind="casio_makernote_in_place",
                tag_name="FirmwareDate",
                raw_value=firmware_date,
                evidence_ids=firmware_date_evidence_ids(firmware_date_family),
            )
        )
        blockers.append(
            CasioWriteBlocker(
                code="composed_runtime_route_deferred",
                tag_name="FirmwareDate",
                reason=(
                    "Casio FirmwareDate fixed-count undef-byte mutation is implemented "
                    "package-locally, but this lane does not edit the generated composed "
                    "JPEG routing parser."
                ),
                evidence_ids=firmware_date_evidence_ids(firmware_date_family),
            )
        )

    maker_note_plan: CasioMakerNoteWritePlan | None = None
    if focus_mode is None and object_distance is None and firmware_date is None:
        blockers.append(
            CasioWriteBlocker(
                code="missing_casio_step",
                tag_name="Casio",
                reason="Casio request has no package-local maker-note write step.",
            )
        )
    else:
        try:
            maker_note_plan = build_casio_maker_note_write_plan(
                focus_mode,
                object_distance,
                firmware_date,
                firmware_date_family,
            )
        except ValueError as error:
            blockers.append(
                CasioWriteBlocker(
                    code="invalid_value",
                    tag_name="Casio",
                    reason=str(error),
                )
            )

    status: CasioWritePlanStatus
    if blockers:
        status = "unsupported" if not steps else "source_mapped_deferred"
    else:
        status = "runnable_with_composed_jpeg_writer"
    return CasioWritePlan(
        request_id=request_id,
        fixture=fixture,
        status=status,
        maker_note_plan=maker_note_plan,
        steps=tuple(steps),
        blockers=tuple(blockers),
        evidence_ids=(CASIO_WRITE_TEST_SOURCE, CASIO_COMPOSED_RUNTIME_SOURCE),
    )


def normalized_write_tag(tag_token: str) -> str:
    tag = tag_token.removesuffix("-").removesuffix("#")
    _group, separator, leaf = tag.partition(":")
    return leaf if separator else tag


def infer_casio_firmware_date_family(
    fixture: str,
    focus_mode: str | None,
    object_distance: str | None,
) -> CasioMakerNoteFamily | None:
    if object_distance is not None:
        return "type2"
    if focus_mode is not None:
        return "type1"
    if fixture.endswith("Casio2.jpg"):
        return "type2"
    if fixture.endswith("Casio.jpg"):
        return "type1"
    return None


def firmware_date_evidence_ids(
    family: CasioMakerNoteFamily | None,
) -> tuple[str, ...]:
    if family == "type1":
        return (CASIO_TYPE1_FIRMWARE_DATE_SOURCE,)
    if family == "type2":
        return (CASIO_TYPE2_FIRMWARE_DATE_SOURCE,)
    return (CASIO_TYPE1_FIRMWARE_DATE_SOURCE, CASIO_TYPE2_FIRMWARE_DATE_SOURCE)
