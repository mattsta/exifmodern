"""Source-grounded Canon RAW write-surface classification.

CR2 and CR3 writes are routed through different oracle mechanisms.  This
module records that surface without rewriting bytes until the corresponding
TIFF/QuickTime/Canon maker-note mutation engines are available.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import (
    JsonObject,
    json_string_array_value,
    json_string_value,
    load_json_object,
)

type EvidenceId = str

type CanonRawContainerKind = Literal["cr2_tiff", "cr3_quicktime", "unknown"]
type CanonRawWriteRequestStatus = Literal["deferred_container_rewrite"]
type CanonRawWriteSurface = Literal[
    "cr2_tiff_iptc",
    "cr2_tiff_exif",
    "cr2_canon_makernote",
    "cr3_quicktime_canon_uuid_tiff",
    "cr3_quicktime_top_level_xmp",
    "cr3_quicktime_ctbo_mdat_offsets",
]
type CanonRawBlockerCode = Literal[
    "requires_cr2_header_and_ifd_rebuild",
    "requires_tiff_embedded_iptc_rebuild",
    "requires_canon_makernote_binary_update",
    "requires_cr3_quicktime_atom_rebuild",
    "requires_cr3_ctbo_mdat_offset_fixups",
    "requires_xmp_packet_in_cr3_top_level_uuid",
    "unsupported_requested_tag",
]

CANON_RAW_MAIN_SOURCE = "canon_raw.canon_raw_main"
CANON_RAW_CR2_NOTE_SOURCE = "canon_raw.canon_raw_cr2_note"
WRITE_CR2_SOURCE = "canon_raw.write_cr2"
CANON_RAW_CRW_WRITE_SOURCE = "canon_raw.canon_raw_crw_write"
CR2_IPTC_DIRECTORY_SOURCE = "canon_raw.cr2_iptc_directory"
IPTC_KEYWORDS_SOURCE = "canon_raw.iptc_keywords"
EXIF_EXPOSURE_COMPENSATION_SOURCE = "canon_raw.exif_exposure_compensation"
EXIF_OWNER_NAME_SOURCE = "canon_raw.exif_owner_name"
CANON_OWNER_NAME_SOURCE = "canon_raw.canon_owner_name"
CANON_FOCAL_PLANE_X_SIZE_SOURCE = "canon_raw.canon_focal_plane_x_size"
CR3_QUICKTIME_MAP_SOURCE = "canon_raw.cr3_quicktime_map"
CR3_CANON_UUID_SOURCE = "canon_raw.cr3_canon_uuid"
CR3_QUICKTIME_CANON2_SOURCE = "canon_raw.cr3_quicktime_canon2"
CR3_CTBO_FIXUP_SOURCE = "canon_raw.cr3_ctbo_fixup"
XMP_DC_SUBJECT_SOURCE = "canon_raw.xmp_dc_subject"
XMP_EXIF_EXPOSURE_COMPENSATION_SOURCE = "canon_raw.xmp_exif_exposure_compensation"


@dataclass(frozen=True)
class CanonRawRequestedTagSpec:
    requested_tag: str
    surfaces_by_container: dict[CanonRawContainerKind, tuple[CanonRawWriteSurface, ...]]
    blockers_by_container: dict[CanonRawContainerKind, tuple[CanonRawBlockerCode, ...]]
    evidence_ids_by_container: dict[CanonRawContainerKind, tuple[EvidenceId, ...]]


@dataclass(frozen=True)
class CanonRawWriteTagClassification:
    requested_tag: str
    requested_value: str
    target_surfaces: tuple[CanonRawWriteSurface, ...]
    blocker_codes: tuple[CanonRawBlockerCode, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocker_codes": list(self.blocker_codes),
            "requested_tag": self.requested_tag,
            "requested_value": self.requested_value,
            "target_surfaces": list(self.target_surfaces),
        }


@dataclass(frozen=True)
class CanonRawWriteRequestClassification:
    request_id: str
    fixture: str
    container_kind: CanonRawContainerKind
    status: CanonRawWriteRequestStatus
    supported_for_modern_mutation: bool
    tags: tuple[CanonRawWriteTagClassification, ...]
    evidence_ids: tuple[EvidenceId, ...]

    def to_json(self) -> JsonObject:
        return {
            "container_kind": self.container_kind,
            "fixture": self.fixture,
            "request_id": self.request_id,
            "status": self.status,
            "supported_for_modern_mutation": self.supported_for_modern_mutation,
            "tags": [tag.to_json() for tag in self.tags],
        }


@dataclass(frozen=True)
class CanonRawWriteRequestReport:
    requests: tuple[CanonRawWriteRequestClassification, ...]

    @property
    def request_count(self) -> int:
        return len(self.requests)

    @property
    def deferred_count(self) -> int:
        return sum(1 for request in self.requests if not request.supported_for_modern_mutation)

    def to_json(self) -> JsonObject:
        return {
            "deferred_count": self.deferred_count,
            "request_count": self.request_count,
            "requests": [request.to_json() for request in self.requests],
            "status": "deferred_container_rewrite",
        }


CANON_RAW_REQUESTED_TAG_SPECS: dict[str, CanonRawRequestedTagSpec] = {
    "Keywords": CanonRawRequestedTagSpec(
        requested_tag="Keywords",
        surfaces_by_container={
            "cr2_tiff": ("cr2_tiff_iptc",),
            "cr3_quicktime": ("cr3_quicktime_top_level_xmp",),
            "unknown": (),
        },
        blockers_by_container={
            "cr2_tiff": (
                "requires_cr2_header_and_ifd_rebuild",
                "requires_tiff_embedded_iptc_rebuild",
            ),
            "cr3_quicktime": (
                "requires_cr3_quicktime_atom_rebuild",
                "requires_cr3_ctbo_mdat_offset_fixups",
                "requires_xmp_packet_in_cr3_top_level_uuid",
            ),
            "unknown": ("unsupported_requested_tag",),
        },
        evidence_ids_by_container={
            "cr2_tiff": (
                WRITE_CR2_SOURCE,
                CR2_IPTC_DIRECTORY_SOURCE,
                IPTC_KEYWORDS_SOURCE,
            ),
            "cr3_quicktime": (
                CR3_QUICKTIME_MAP_SOURCE,
                CR3_CTBO_FIXUP_SOURCE,
                XMP_DC_SUBJECT_SOURCE,
            ),
            "unknown": (),
        },
    ),
    "OwnerName": CanonRawRequestedTagSpec(
        requested_tag="OwnerName",
        surfaces_by_container={
            "cr2_tiff": ("cr2_tiff_exif", "cr2_canon_makernote"),
            "cr3_quicktime": ("cr3_quicktime_canon_uuid_tiff",),
            "unknown": (),
        },
        blockers_by_container={
            "cr2_tiff": (
                "requires_cr2_header_and_ifd_rebuild",
                "requires_canon_makernote_binary_update",
            ),
            "cr3_quicktime": (
                "requires_cr3_quicktime_atom_rebuild",
                "requires_cr3_ctbo_mdat_offset_fixups",
            ),
            "unknown": ("unsupported_requested_tag",),
        },
        evidence_ids_by_container={
            "cr2_tiff": (
                WRITE_CR2_SOURCE,
                EXIF_OWNER_NAME_SOURCE,
                CANON_OWNER_NAME_SOURCE,
            ),
            "cr3_quicktime": (
                CR3_QUICKTIME_MAP_SOURCE,
                CR3_CANON_UUID_SOURCE,
                EXIF_OWNER_NAME_SOURCE,
            ),
            "unknown": (),
        },
    ),
    "FocalPlaneXSize": CanonRawRequestedTagSpec(
        requested_tag="FocalPlaneXSize",
        surfaces_by_container={
            "cr2_tiff": ("cr2_canon_makernote",),
            "cr3_quicktime": ("cr3_quicktime_canon_uuid_tiff",),
            "unknown": (),
        },
        blockers_by_container={
            "cr2_tiff": (
                "requires_cr2_header_and_ifd_rebuild",
                "requires_canon_makernote_binary_update",
            ),
            "cr3_quicktime": (
                "requires_cr3_quicktime_atom_rebuild",
                "requires_cr3_ctbo_mdat_offset_fixups",
                "requires_canon_makernote_binary_update",
            ),
            "unknown": ("unsupported_requested_tag",),
        },
        evidence_ids_by_container={
            "cr2_tiff": (
                WRITE_CR2_SOURCE,
                CANON_FOCAL_PLANE_X_SIZE_SOURCE,
            ),
            "cr3_quicktime": (
                CR3_QUICKTIME_MAP_SOURCE,
                CR3_CANON_UUID_SOURCE,
                CANON_FOCAL_PLANE_X_SIZE_SOURCE,
            ),
            "unknown": (),
        },
    ),
    "Subject": CanonRawRequestedTagSpec(
        requested_tag="Subject",
        surfaces_by_container={
            "cr2_tiff": ("cr2_tiff_iptc",),
            "cr3_quicktime": ("cr3_quicktime_top_level_xmp",),
            "unknown": (),
        },
        blockers_by_container={
            "cr2_tiff": (
                "requires_cr2_header_and_ifd_rebuild",
                "requires_tiff_embedded_iptc_rebuild",
            ),
            "cr3_quicktime": (
                "requires_cr3_quicktime_atom_rebuild",
                "requires_cr3_ctbo_mdat_offset_fixups",
                "requires_xmp_packet_in_cr3_top_level_uuid",
            ),
            "unknown": ("unsupported_requested_tag",),
        },
        evidence_ids_by_container={
            "cr2_tiff": (
                WRITE_CR2_SOURCE,
                CR2_IPTC_DIRECTORY_SOURCE,
                IPTC_KEYWORDS_SOURCE,
            ),
            "cr3_quicktime": (
                CR3_QUICKTIME_MAP_SOURCE,
                CR3_CTBO_FIXUP_SOURCE,
                XMP_DC_SUBJECT_SOURCE,
            ),
            "unknown": (),
        },
    ),
    "ExposureCompensation": CanonRawRequestedTagSpec(
        requested_tag="ExposureCompensation",
        surfaces_by_container={
            "cr2_tiff": ("cr2_tiff_exif", "cr2_canon_makernote"),
            "cr3_quicktime": (
                "cr3_quicktime_canon_uuid_tiff",
                "cr3_quicktime_top_level_xmp",
            ),
            "unknown": (),
        },
        blockers_by_container={
            "cr2_tiff": (
                "requires_cr2_header_and_ifd_rebuild",
                "requires_canon_makernote_binary_update",
            ),
            "cr3_quicktime": (
                "requires_cr3_quicktime_atom_rebuild",
                "requires_cr3_ctbo_mdat_offset_fixups",
                "requires_xmp_packet_in_cr3_top_level_uuid",
            ),
            "unknown": ("unsupported_requested_tag",),
        },
        evidence_ids_by_container={
            "cr2_tiff": (
                WRITE_CR2_SOURCE,
                EXIF_EXPOSURE_COMPENSATION_SOURCE,
            ),
            "cr3_quicktime": (
                CR3_QUICKTIME_MAP_SOURCE,
                CR3_CANON_UUID_SOURCE,
                CR3_CTBO_FIXUP_SOURCE,
                EXIF_EXPOSURE_COMPENSATION_SOURCE,
                XMP_EXIF_EXPOSURE_COMPENSATION_SOURCE,
            ),
            "unknown": (),
        },
    ),
}


def classify_canon_raw_golden_request_file(path: Path) -> CanonRawWriteRequestClassification:
    return classify_canon_raw_golden_request_payload(load_json_object(path))


def classify_canon_raw_golden_request_payload(
    payload: JsonObject,
) -> CanonRawWriteRequestClassification:
    fixture = required_string(payload, "fixture")
    request_id = required_string(payload, "request_id")
    container_kind = container_kind_for_fixture(fixture)
    tags = tuple(
        classify_write_arg(write_arg, container_kind)
        for write_arg in json_string_array_value(payload, "write_args")
        if is_metadata_assignment_arg(write_arg)
    )
    return CanonRawWriteRequestClassification(
        request_id=request_id,
        fixture=fixture,
        container_kind=container_kind,
        status="deferred_container_rewrite",
        supported_for_modern_mutation=False,
        tags=tags,
        evidence_ids=container_evidence_ids(container_kind),
    )


def build_canon_raw_write_request_report(
    request_paths: tuple[Path, ...],
) -> CanonRawWriteRequestReport:
    return CanonRawWriteRequestReport(
        requests=tuple(classify_canon_raw_golden_request_file(path) for path in request_paths)
    )


def write_canon_raw_write_request_report(
    request_paths: tuple[Path, ...],
    output_path: Path,
) -> CanonRawWriteRequestReport:
    report = build_canon_raw_write_request_report(request_paths)
    output_path.write_text(
        json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def classify_write_arg(
    write_arg: str,
    container_kind: CanonRawContainerKind,
) -> CanonRawWriteTagClassification:
    requested_tag, requested_value = split_assignment_arg(write_arg)
    unqualified_tag = requested_tag.rsplit(":", 1)[-1]
    spec = CANON_RAW_REQUESTED_TAG_SPECS.get(unqualified_tag)
    if spec is None:
        return CanonRawWriteTagClassification(
            requested_tag=requested_tag,
            requested_value=requested_value,
            target_surfaces=(),
            blocker_codes=("unsupported_requested_tag",),
            evidence_ids=container_evidence_ids(container_kind),
        )
    return CanonRawWriteTagClassification(
        requested_tag=requested_tag,
        requested_value=requested_value,
        target_surfaces=spec.surfaces_by_container[container_kind],
        blocker_codes=spec.blockers_by_container[container_kind],
        evidence_ids=spec.evidence_ids_by_container[container_kind],
    )


def container_kind_for_fixture(fixture: str) -> CanonRawContainerKind:
    suffix = Path(fixture).suffix.lower()
    if suffix == ".cr2":
        return "cr2_tiff"
    if suffix == ".cr3":
        return "cr3_quicktime"
    return "unknown"


def container_evidence_ids(
    container_kind: CanonRawContainerKind,
) -> tuple[EvidenceId, ...]:
    if container_kind == "cr2_tiff":
        return (CANON_RAW_CR2_NOTE_SOURCE, WRITE_CR2_SOURCE)
    if container_kind == "cr3_quicktime":
        return (
            CR3_QUICKTIME_MAP_SOURCE,
            CR3_CANON_UUID_SOURCE,
            CR3_QUICKTIME_CANON2_SOURCE,
            CR3_CTBO_FIXUP_SOURCE,
        )
    return (CANON_RAW_MAIN_SOURCE,)


def is_metadata_assignment_arg(write_arg: str) -> bool:
    return write_arg.startswith("-") and "=" in write_arg and not write_arg.startswith("-api")


def split_assignment_arg(write_arg: str) -> tuple[str, str]:
    trimmed = write_arg.removeprefix("-")
    tag, separator, value = trimmed.partition("=")
    if not separator:
        raise ValueError(f"Expected metadata assignment argument: {write_arg}")
    return tag, value


def required_string(payload: JsonObject, key: str) -> str:
    value = json_string_value(payload, key)
    if value is None:
        raise ValueError(f"Expected string JSON field: {key}")
    return value


def evidence_id_to_json(reference: EvidenceId) -> JsonObject:
    return {"id": reference}
