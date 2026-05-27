"""PhotoMechanic trailer write primitives for Photoshop PSD files.

ExifTool treats PhotoMechanic trailers as IPTC-format data with soft-edit
fields stored in record 2.  This module implements the bounded ``Tagged``
writer used by the Photoshop PSD write path while leaving broader
PhotoMechanic/IPTC mutation surfaces gated elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.photoshop.iptc import (
    PhotoshopIPTCDatasetEntry,
    encode_iptc_dataset_entry,
    parse_iptc_dataset_entries,
)
from exifmodern.formats.photoshop.nested_metadata_plan import (
    PHOTOMECHANIC_TRAILER_SOURCE_ID,
    PHOTOSHOP_PSD_TRAILER_WRITE_SOURCE_ID,
)
from exifmodern.formats.photoshop.resource_writer import PhotoshopPSDUnsupportedWriteError
from exifmodern.formats.photoshop.section_boundary_plan import (
    PHOTOMECHANIC_TRAILER_FOOTER_SIGNATURE,
    PHOTOSHOP_PHOTOMECHANIC_TRAILER_BOUNDARY_SOURCE_ID,
    plan_photoshop_psd_section_boundaries,
)

type PhotoMechanicTaggedValue = bool | Literal["Yes", "No"]
type PhotoMechanicTrailerBlockerCode = Literal[
    "not_source_backed",
    "missing_photomechanic_trailer",
    "photomechanic_trailer_malformed",
    "photomechanic_tagged_value_unsupported",
    "photomechanic_trailer_too_large",
]

PHOTOMECHANIC_SOFT_EDIT_RECORD = 2
PHOTOMECHANIC_TAGGED_DATASET = 221
PHOTOMECHANIC_COLOR_CLASS_DATASET = 222
PHOTOMECHANIC_ROTATION_DATASET = 216
PHOTOMECHANIC_CROP_LEFT_DATASET = 217
PHOTOMECHANIC_CROP_TOP_DATASET = 218
PHOTOMECHANIC_CROP_RIGHT_DATASET = 219
PHOTOMECHANIC_CROP_BOTTOM_DATASET = 220
PHOTOMECHANIC_TRAILER_PAD_LENGTH = 0x800
PHOTOMECHANIC_TRAILER_MAX_LENGTH = 0x7FFFFFFF

PHOTOMECHANIC_COLOR_CLASSES = {
    0: "0 (None)",
    1: "1 (Winner)",
    2: "2 (Winner alt)",
    3: "3 (Superior)",
    4: "4 (Superior alt)",
    5: "5 (Typical)",
    6: "6 (Typical alt)",
    7: "7 (Extras)",
    8: "8 (Trash)",
}

PHOTOMECHANIC_MAIN_SOURCE_ID = "photoshop.photomechanic.main"
PHOTOMECHANIC_SOFT_EDIT_SOURCE_ID = "photoshop.photomechanic.soft_edit"
PHOTOMECHANIC_TRAILER_REWRITE_SOURCE_ID = "photoshop.photomechanic.trailer_rewrite"


@dataclass(frozen=True)
class PhotoMechanicTaggedAssignment:
    value: int
    raw_value: bytes


@dataclass(frozen=True)
class PhotoMechanicTaggedRewriteStep:
    record: int
    dataset: int
    source_values: tuple[bytes, ...]
    output_value: bytes
    changed: bool


@dataclass(frozen=True)
class PhotoMechanicTrailerRewritePlan:
    source_payload_length: int
    output_payload_length: int
    output_trailer_length: int
    source_backed: bool
    can_write_bytes: bool
    blocker_codes: tuple[PhotoMechanicTrailerBlockerCode, ...]
    output_payload: bytes | None
    output_footer: bytes | None
    steps: tuple[PhotoMechanicTaggedRewriteStep, ...]
    evidence_ids: tuple[str, ...]

    @property
    def output_trailer(self) -> bytes | None:
        if self.output_payload is None or self.output_footer is None:
            return None
        return self.output_payload + self.output_footer


def parse_photomechanic_trailer_tags(payload: bytes) -> dict[str, str | int]:
    """Read source-backed PhotoMechanic soft-edit fields from trailer IPTC records."""

    entries_result = parse_iptc_dataset_entries(payload)
    if entries_result.blocker_code is not None:
        raise ValueError(entries_result.blocker_code)

    values: dict[str, str | int] = {}
    for entry in entries_result.entries:
        if entry.record != PHOTOMECHANIC_SOFT_EDIT_RECORD:
            continue
        value = photomechanic_int32_value(entry)
        if value is None:
            continue
        if entry.dataset == PHOTOMECHANIC_TAGGED_DATASET:
            values["Tagged"] = {0: "No", 1: "Yes"}.get(value, value)
        elif entry.dataset == PHOTOMECHANIC_COLOR_CLASS_DATASET:
            values["ColorClass"] = PHOTOMECHANIC_COLOR_CLASSES.get(value, value)
        elif entry.dataset == PHOTOMECHANIC_ROTATION_DATASET:
            values["Rotation"] = {0: "0", 1: "90", 2: "180", 3: "270"}.get(value, value)
        elif entry.dataset == PHOTOMECHANIC_CROP_LEFT_DATASET:
            values["CropLeft"] = value
        elif entry.dataset == PHOTOMECHANIC_CROP_TOP_DATASET:
            values["CropTop"] = value
        elif entry.dataset == PHOTOMECHANIC_CROP_RIGHT_DATASET:
            values["CropRight"] = value
        elif entry.dataset == PHOTOMECHANIC_CROP_BOTTOM_DATASET:
            values["CropBottom"] = value
    return values


def photomechanic_int32_value(entry: PhotoshopIPTCDatasetEntry) -> int | None:
    if len(entry.value) != 4:
        return None
    return int.from_bytes(entry.value, "big", signed=True)


def plan_photomechanic_tagged_trailer_rewrite(
    payload: bytes,
    tagged: PhotoMechanicTaggedValue,
    *,
    source_backed: bool = True,
    compact_no_padding: bool = False,
) -> PhotoMechanicTrailerRewritePlan:
    blockers: list[PhotoMechanicTrailerBlockerCode] = []
    if not source_backed:
        blockers.append("not_source_backed")

    assignment = normalize_tagged_assignment(tagged)
    if assignment is None:
        blockers.append("photomechanic_tagged_value_unsupported")

    entries_result = parse_iptc_dataset_entries(payload)
    if entries_result.blocker_code is not None:
        blockers.append("photomechanic_trailer_malformed")

    if blockers or assignment is None:
        return blocked_plan(payload, source_backed, blockers)

    output = rewrite_tagged_entries(entries_result.entries, assignment)
    if not compact_no_padding and len(output) < PHOTOMECHANIC_TRAILER_PAD_LENGTH:
        output += b"\x00" * (PHOTOMECHANIC_TRAILER_PAD_LENGTH - len(output))
    if len(output) > PHOTOMECHANIC_TRAILER_MAX_LENGTH:
        return blocked_plan(payload, source_backed, ("photomechanic_trailer_too_large",))

    footer = len(output).to_bytes(4, "big") + PHOTOMECHANIC_TRAILER_FOOTER_SIGNATURE
    return PhotoMechanicTrailerRewritePlan(
        source_payload_length=len(payload),
        output_payload_length=len(output),
        output_trailer_length=len(output) + len(footer),
        source_backed=source_backed,
        can_write_bytes=True,
        blocker_codes=(),
        output_payload=output,
        output_footer=footer,
        steps=(tagged_step(entries_result.entries, assignment),),
        evidence_ids=photomechanic_evidence_ids(),
    )


def rewrite_photomechanic_tagged_trailer(
    payload: bytes,
    tagged: PhotoMechanicTaggedValue,
    *,
    source_backed: bool = True,
    compact_no_padding: bool = False,
) -> bytes:
    plan = plan_photomechanic_tagged_trailer_rewrite(
        payload,
        tagged,
        source_backed=source_backed,
        compact_no_padding=compact_no_padding,
    )
    if not plan.can_write_bytes or plan.output_trailer is None:
        raise PhotoshopPSDUnsupportedWriteError(
            "PhotoMechanic trailer rewrite is blocked: " + ", ".join(plan.blocker_codes)
        )
    return plan.output_trailer


def rewrite_photoshop_psd_photomechanic_tagged(
    psd_data: bytes,
    tagged: PhotoMechanicTaggedValue,
    *,
    source_backed: bool = True,
    compact_no_padding: bool = False,
) -> bytes:
    section_plan = plan_photoshop_psd_section_boundaries(
        psd_data,
        source_backed=source_backed,
    )
    trailer = section_plan.trailer_section
    if trailer is None:
        raise PhotoshopPSDUnsupportedWriteError(
            "PhotoMechanic PSD trailer rewrite is blocked: missing_photomechanic_trailer"
        )

    rewritten_trailer = rewrite_photomechanic_tagged_trailer(
        psd_data[trailer.data_start : trailer.data_end],
        tagged,
        source_backed=source_backed,
        compact_no_padding=compact_no_padding,
    )
    return psd_data[: trailer.total_start] + rewritten_trailer


def normalize_tagged_assignment(
    tagged: PhotoMechanicTaggedValue,
) -> PhotoMechanicTaggedAssignment | None:
    if tagged is True or tagged == "Yes":
        value = 1
    elif tagged is False or tagged == "No":
        value = 0
    else:
        return None
    return PhotoMechanicTaggedAssignment(value=value, raw_value=value.to_bytes(4, "big"))


def rewrite_tagged_entries(
    entries: tuple[PhotoshopIPTCDatasetEntry, ...],
    assignment: PhotoMechanicTaggedAssignment,
) -> bytes:
    output = bytearray()
    emitted = False
    tagged_key = (PHOTOMECHANIC_SOFT_EDIT_RECORD, PHOTOMECHANIC_TAGGED_DATASET)
    for entry in entries:
        if not emitted and tagged_key < entry.key:
            output.extend(encode_tagged_assignment(assignment))
            emitted = True
        if entry.key == tagged_key:
            if not emitted:
                output.extend(encode_tagged_assignment(assignment))
                emitted = True
            continue
        output.extend(entry.raw_entry)
    if not emitted:
        output.extend(encode_tagged_assignment(assignment))
    return bytes(output)


def encode_tagged_assignment(assignment: PhotoMechanicTaggedAssignment) -> bytes:
    return encode_iptc_dataset_entry(
        PHOTOMECHANIC_SOFT_EDIT_RECORD,
        PHOTOMECHANIC_TAGGED_DATASET,
        assignment.raw_value,
    )


def tagged_step(
    entries: tuple[PhotoshopIPTCDatasetEntry, ...],
    assignment: PhotoMechanicTaggedAssignment,
) -> PhotoMechanicTaggedRewriteStep:
    source_values = tuple(
        entry.value
        for entry in entries
        if entry.record == PHOTOMECHANIC_SOFT_EDIT_RECORD
        and entry.dataset == PHOTOMECHANIC_TAGGED_DATASET
    )
    return PhotoMechanicTaggedRewriteStep(
        record=PHOTOMECHANIC_SOFT_EDIT_RECORD,
        dataset=PHOTOMECHANIC_TAGGED_DATASET,
        source_values=source_values,
        output_value=assignment.raw_value,
        changed=source_values != (assignment.raw_value,),
    )


def blocked_plan(
    payload: bytes,
    source_backed: bool,
    blockers: tuple[PhotoMechanicTrailerBlockerCode, ...] | list[PhotoMechanicTrailerBlockerCode],
) -> PhotoMechanicTrailerRewritePlan:
    return PhotoMechanicTrailerRewritePlan(
        source_payload_length=len(payload),
        output_payload_length=len(payload),
        output_trailer_length=len(payload) + 12,
        source_backed=source_backed,
        can_write_bytes=False,
        blocker_codes=tuple(dict.fromkeys(blockers)),
        output_payload=None,
        output_footer=None,
        steps=(),
        evidence_ids=photomechanic_evidence_ids(),
    )


def photomechanic_evidence_ids() -> tuple[str, ...]:
    return (
        PHOTOMECHANIC_MAIN_SOURCE_ID,
        PHOTOMECHANIC_SOFT_EDIT_SOURCE_ID,
        PHOTOMECHANIC_TRAILER_SOURCE_ID,
        PHOTOMECHANIC_TRAILER_REWRITE_SOURCE_ID,
        PHOTOSHOP_PHOTOMECHANIC_TRAILER_BOUNDARY_SOURCE_ID,
        PHOTOSHOP_PSD_TRAILER_WRITE_SOURCE_ID,
    )
