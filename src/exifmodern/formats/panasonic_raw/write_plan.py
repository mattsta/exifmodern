"""Panasonic RAW/RW2/RWL write-surface classification.

This module intentionally does not mutate RAW containers.  ExifTool's
PanasonicRaw writer is a TIFF rewrite path with Panasonic-specific raw-data
offset patching, so this package exposes a reusable typed report until that
container rewrite can be implemented without corrupting image data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import json_string_array_value, json_string_value, load_json_object

type PanasonicRawEvidenceId = str
type PanasonicRawWriteGroup = Literal["EXIF", "IFD0", "IPTC", "XMP", "unknown"]
type PanasonicRawWriteTarget = Literal[
    "ifd0_exif_scalar",
    "ifd0_iptc_naa",
    "ifd0_application_notes",
    "unknown",
]
type PanasonicRawWriteStatus = Literal[
    "source_mapped_executable",
    "source_mapped_deferred",
    "unsupported",
]

PANASONIC_RAW_MAIN_SOURCE: PanasonicRawEvidenceId = "panasonic_raw.main"
PANASONIC_RAW_JPG_FROM_RAW_SOURCE: PanasonicRawEvidenceId = "panasonic_raw.jpg_from_raw"
PANASONIC_RAW_APPLICATION_NOTES_SOURCE: PanasonicRawEvidenceId = "panasonic_raw.application_notes"
PANASONIC_RAW_IPTC_SOURCE: PanasonicRawEvidenceId = "panasonic_raw.iptc_naa"
PANASONIC_RAW_MODIFY_DATE_SOURCE: PanasonicRawEvidenceId = "panasonic_raw.modify_date"
PANASONIC_RAW_OFFSET_PATCH_SOURCE: PanasonicRawEvidenceId = "panasonic_raw.patch_raw_data_offset"
WRITE_EXIF_PANASONIC_PATCH_SOURCE: PanasonicRawEvidenceId = "panasonic_raw.writeexif_patch"
WRITE_EXIF_PANASONIC_STRIP_SOURCE: PanasonicRawEvidenceId = "panasonic_raw.writeexif_strip"
WRITE_EXIF_RAW_DATA_COPY_SOURCE: PanasonicRawEvidenceId = "panasonic_raw.writeexif_raw_copy"
PANASONIC_RAW_GOLDEN_REQUEST_SOURCE: PanasonicRawEvidenceId = "panasonic_raw.golden_request"
PANASONIC_RAW_GOLDEN_STRUCTURE_SOURCE: PanasonicRawEvidenceId = "panasonic_raw.golden_structure"
PANASONIC_RAW_GOLDEN_RESULT_SOURCE: PanasonicRawEvidenceId = "panasonic_raw.golden_result"

SOURCE_MAPPED_GROUPS = {"EXIF", "IFD0", "IPTC", "XMP"}
DEFERRED_BLOCKERS = (
    "RW2 mutation must rebuild the TIFF container through PanasonicRaw::Main rather than "
    "append standalone XMP/IPTC payloads.",
    "Raw image data offsets require PanasonicRaw::PatchRawDataOffset variant checks and "
    "RawDataOffset/StripOffsets/StripByteCounts fixups.",
    "The oracle changes the RW2 file size and places XMP/IPTC in IFD0 directories, so a "
    "safe implementation needs source-backed TIFF directory rebuilding before writing bytes.",
)
EXECUTABLE_SUMMARY = (
    "Panasonic RW2 write is source-backed and executable for the bounded "
    "IFD0 ApplicationNotes/IPTC-NAA plus JpgFromRaw ModifyDate oracle shape."
)


@dataclass(frozen=True)
class PanasonicRawWriteArgument:
    raw_argument: str
    group: PanasonicRawWriteGroup
    tag_name: str
    value: str
    target: PanasonicRawWriteTarget
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]


@dataclass(frozen=True)
class PanasonicRawWriteClassificationReport:
    request_id: str
    fixture: str | None
    status: PanasonicRawWriteStatus
    can_rewrite: bool
    arguments: tuple[PanasonicRawWriteArgument, ...]
    blockers: tuple[str, ...]
    evidence_ids: tuple[PanasonicRawEvidenceId, ...]

    @property
    def deferred_summary(self) -> str:
        if self.status == "source_mapped_executable":
            return EXECUTABLE_SUMMARY
        return "Panasonic RW2 write is source-mapped but deferred pending safe RAW TIFF rewrite."


def load_panasonic_raw_golden_write_report(
    request_path: Path,
) -> PanasonicRawWriteClassificationReport:
    request = load_json_object(request_path)
    request_id = json_string_value(request, "request_id") or request_path.stem
    fixture = json_string_value(request, "fixture")
    write_args = tuple(json_string_array_value(request, "write_args"))
    return classify_panasonic_raw_write_args(
        write_args,
        request_id=request_id,
        fixture=fixture,
        include_golden_sources=True,
    )


def classify_panasonic_raw_write_args(
    write_args: tuple[str, ...],
    request_id: str = "ad-hoc-panasonic-raw-write",
    fixture: str | None = None,
    include_golden_sources: bool = False,
) -> PanasonicRawWriteClassificationReport:
    arguments = tuple(
        argument
        for raw_argument in write_args
        if (argument := parse_write_argument(raw_argument)) is not None
    )
    evidence_ids = report_evidence_ids(arguments, include_golden_sources)
    if arguments and panasonic_rw2_executable_argument_shape(arguments):
        status: PanasonicRawWriteStatus = "source_mapped_executable"
        blockers: tuple[str, ...] = ()
    elif arguments and all(argument.group in SOURCE_MAPPED_GROUPS for argument in arguments):
        status = "source_mapped_deferred"
        blockers = DEFERRED_BLOCKERS
    else:
        status = "unsupported"
        blockers = (
            "At least one write argument does not map to the sourced Panasonic RAW write surface.",
        )
    return PanasonicRawWriteClassificationReport(
        request_id=request_id,
        fixture=fixture,
        status=status,
        can_rewrite=status == "source_mapped_executable",
        arguments=arguments,
        blockers=blockers,
        evidence_ids=evidence_ids,
    )


def panasonic_rw2_executable_argument_shape(
    arguments: tuple[PanasonicRawWriteArgument, ...],
) -> bool:
    """Bound the promoted writer to the source-backed Panasonic.t RW2 shape."""

    return tuple(argument.target for argument in arguments) == (
        "ifd0_application_notes",
        "ifd0_iptc_naa",
        "ifd0_exif_scalar",
    ) and tuple((argument.group, argument.tag_name) for argument in arguments) == (
        ("XMP", "Title"),
        ("IPTC", "Keywords"),
        ("EXIF", "ModifyDate"),
    )


def parse_write_argument(raw_argument: str) -> PanasonicRawWriteArgument | None:
    if not raw_argument.startswith("-") or "=" not in raw_argument:
        return None
    assignment = raw_argument[1:]
    left, value = assignment.split("=", 1)
    group, tag_name = split_group_and_tag(left)
    target = target_for_group_and_tag(group, tag_name)
    return PanasonicRawWriteArgument(
        raw_argument=raw_argument,
        group=group,
        tag_name=tag_name,
        value=value,
        target=target,
        evidence_ids=evidence_ids_for_target(target, tag_name),
    )


def split_group_and_tag(text: str) -> tuple[PanasonicRawWriteGroup, str]:
    if ":" not in text:
        return "EXIF", text
    group_text, tag_name = text.split(":", 1)
    if group_text == "XMP":
        return "XMP", tag_name
    if group_text == "IPTC":
        return "IPTC", tag_name
    if group_text == "EXIF":
        return "EXIF", tag_name
    if group_text == "IFD0":
        return "IFD0", tag_name
    return "unknown", tag_name


def target_for_group_and_tag(
    group: PanasonicRawWriteGroup,
    tag_name: str,
) -> PanasonicRawWriteTarget:
    if group == "XMP":
        return "ifd0_application_notes"
    if group == "IPTC":
        return "ifd0_iptc_naa"
    if group in {"EXIF", "IFD0"} and tag_name == "ModifyDate":
        return "ifd0_exif_scalar"
    return "unknown"


def evidence_ids_for_target(
    target: PanasonicRawWriteTarget,
    tag_name: str,
) -> tuple[PanasonicRawEvidenceId, ...]:
    if target == "ifd0_application_notes":
        return (PANASONIC_RAW_MAIN_SOURCE, PANASONIC_RAW_APPLICATION_NOTES_SOURCE)
    if target == "ifd0_iptc_naa":
        return (PANASONIC_RAW_MAIN_SOURCE, PANASONIC_RAW_IPTC_SOURCE)
    if target == "ifd0_exif_scalar" and tag_name == "ModifyDate":
        return (PANASONIC_RAW_MAIN_SOURCE, PANASONIC_RAW_MODIFY_DATE_SOURCE)
    return (PANASONIC_RAW_MAIN_SOURCE,)


def report_evidence_ids(
    arguments: tuple[PanasonicRawWriteArgument, ...],
    include_golden_sources: bool,
) -> tuple[PanasonicRawEvidenceId, ...]:
    references: list[PanasonicRawEvidenceId] = [
        PANASONIC_RAW_MAIN_SOURCE,
        PANASONIC_RAW_JPG_FROM_RAW_SOURCE,
        PANASONIC_RAW_OFFSET_PATCH_SOURCE,
        WRITE_EXIF_PANASONIC_PATCH_SOURCE,
        WRITE_EXIF_PANASONIC_STRIP_SOURCE,
    ]
    for argument in arguments:
        for evidence_id in argument.evidence_ids:
            if evidence_id not in references:
                references.append(evidence_id)
    if include_golden_sources:
        references.extend(
            (
                PANASONIC_RAW_GOLDEN_REQUEST_SOURCE,
                PANASONIC_RAW_GOLDEN_STRUCTURE_SOURCE,
                PANASONIC_RAW_GOLDEN_RESULT_SOURCE,
            )
        )
    return tuple(references)
