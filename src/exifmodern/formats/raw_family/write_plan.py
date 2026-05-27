"""Source-grounded RAW-family write routing report.

RAF, NEF, MRW, and IIQ writes require container-specific ExifTool rewrites.
This module maps requested tags to those write surfaces and records blockers
instead of attempting unsafe RAW byte mutation.
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

type RawFamilyContainer = Literal[
    "raf_fuji_embedded_jpeg",
    "nef_tiff_nikon",
    "mrw_minolta_raw",
    "iiq_phaseone",
    "unknown_jpeg_exif",
    "unknown",
]
type RawFamilyStatus = Literal[
    "source_mapped_deferred",
    "routed_outside_raw_family",
    "unsupported",
]
type RawFamilyWriteSurface = Literal[
    "raf_embedded_jpeg_exif",
    "raf_header_offsets",
    "nef_tiff_iptc_naa",
    "nef_nikon_capture_iptc",
    "nef_nikon_capture_scalar",
    "mrw_minolta_ttw_tiff",
    "mrw_minolta_makernote_binary",
    "iiq_phaseone_main_ifd",
    "iiq_phaseone_sensor_calibration_ifd",
    "jpeg_exif",
    "unknown",
]
type RawFamilyBlockerCode = Literal[
    "requires_raf_embedded_jpeg_rewrite",
    "requires_raf_header_offset_rebuild",
    "requires_nef_tiff_directory_rebuild",
    "requires_nikon_capture_block_rewrite",
    "requires_nikon_makernote_key_prescan",
    "requires_mrw_segment_rebuild",
    "requires_mrw_embedded_tiff_rewrite",
    "requires_minolta_makernote_binary_update",
    "requires_phaseone_ifd_rebuild",
    "requires_phaseone_value_offset_fixups",
    "route_to_jpeg_exif_writer_not_raw_family",
    "unsupported_requested_tag",
    "unsupported_container",
]


@dataclass(frozen=True)
class RawFamilyRequestedTagSpec:
    requested_tag: str
    surfaces_by_container: dict[RawFamilyContainer, tuple[RawFamilyWriteSurface, ...]]
    blockers_by_container: dict[RawFamilyContainer, tuple[RawFamilyBlockerCode, ...]]
    evidence_ids_by_container: dict[RawFamilyContainer, tuple[str, ...]]


@dataclass(frozen=True)
class RawFamilyWriteArgumentClassification:
    raw_argument: str
    requested_tag: str
    requested_value: str
    target_surfaces: tuple[RawFamilyWriteSurface, ...]
    blocker_codes: tuple[RawFamilyBlockerCode, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocker_codes": list(self.blocker_codes),
            "raw_argument": self.raw_argument,
            "requested_tag": self.requested_tag,
            "requested_value": self.requested_value,
            "target_surfaces": list(self.target_surfaces),
        }


@dataclass(frozen=True)
class RawFamilyWriteRequestClassification:
    request_id: str
    fixture: str
    container: RawFamilyContainer
    status: RawFamilyStatus
    can_rewrite: bool
    arguments: tuple[RawFamilyWriteArgumentClassification, ...]
    blockers: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "arguments": [argument.to_json() for argument in self.arguments],
            "blockers": list(self.blockers),
            "can_rewrite": self.can_rewrite,
            "container": self.container,
            "fixture": self.fixture,
            "request_id": self.request_id,
            "status": self.status,
        }


@dataclass(frozen=True)
class RawFamilyWriteRoutingReport:
    requests: tuple[RawFamilyWriteRequestClassification, ...]

    @property
    def request_count(self) -> int:
        return len(self.requests)

    @property
    def deferred_count(self) -> int:
        return sum(1 for request in self.requests if request.status == "source_mapped_deferred")

    @property
    def routed_outside_raw_family_count(self) -> int:
        return sum(1 for request in self.requests if request.status == "routed_outside_raw_family")

    def to_json(self) -> JsonObject:
        return {
            "deferred_count": self.deferred_count,
            "request_count": self.request_count,
            "requests": [request.to_json() for request in self.requests],
            "routed_outside_raw_family_count": self.routed_outside_raw_family_count,
            "status": "raw_family_write_routing_report",
        }


def single_container_surfaces(
    container: RawFamilyContainer,
    surfaces: tuple[RawFamilyWriteSurface, ...],
) -> dict[RawFamilyContainer, tuple[RawFamilyWriteSurface, ...]]:
    base: dict[RawFamilyContainer, tuple[RawFamilyWriteSurface, ...]] = {
        "raf_fuji_embedded_jpeg": ("unknown",),
        "nef_tiff_nikon": ("unknown",),
        "mrw_minolta_raw": ("unknown",),
        "iiq_phaseone": ("unknown",),
        "unknown_jpeg_exif": ("unknown",),
        "unknown": ("unknown",),
    }
    base[container] = surfaces
    return base


def single_container_blockers(
    container: RawFamilyContainer,
    blockers: tuple[RawFamilyBlockerCode, ...],
) -> dict[RawFamilyContainer, tuple[RawFamilyBlockerCode, ...]]:
    base: dict[RawFamilyContainer, tuple[RawFamilyBlockerCode, ...]] = {
        "raf_fuji_embedded_jpeg": ("unsupported_requested_tag",),
        "nef_tiff_nikon": ("unsupported_requested_tag",),
        "mrw_minolta_raw": ("unsupported_requested_tag",),
        "iiq_phaseone": ("unsupported_requested_tag",),
        "unknown_jpeg_exif": ("unsupported_requested_tag",),
        "unknown": ("unsupported_container",),
    }
    base[container] = blockers
    return base


def single_container_references(
    container: RawFamilyContainer,
    references: tuple[str, ...],
) -> dict[RawFamilyContainer, tuple[str, ...]]:
    base: dict[RawFamilyContainer, tuple[str, ...]] = {
        "raf_fuji_embedded_jpeg": (),
        "nef_tiff_nikon": (),
        "mrw_minolta_raw": (),
        "iiq_phaseone": (),
        "unknown_jpeg_exif": (),
        "unknown": (),
    }
    base[container] = references
    return base


def surfaces_for_only_nef(
    surfaces: tuple[RawFamilyWriteSurface, ...],
) -> dict[RawFamilyContainer, tuple[RawFamilyWriteSurface, ...]]:
    return single_container_surfaces("nef_tiff_nikon", surfaces)


def blockers_for_only_nef(
    blockers: tuple[RawFamilyBlockerCode, ...],
) -> dict[RawFamilyContainer, tuple[RawFamilyBlockerCode, ...]]:
    return single_container_blockers("nef_tiff_nikon", blockers)


def references_for_only_nef(
    references: tuple[str, ...],
) -> dict[RawFamilyContainer, tuple[str, ...]]:
    return single_container_references("nef_tiff_nikon", references)


def surfaces_for_only_mrw(
    surfaces: tuple[RawFamilyWriteSurface, ...],
) -> dict[RawFamilyContainer, tuple[RawFamilyWriteSurface, ...]]:
    return single_container_surfaces("mrw_minolta_raw", surfaces)


def blockers_for_only_mrw(
    blockers: tuple[RawFamilyBlockerCode, ...],
) -> dict[RawFamilyContainer, tuple[RawFamilyBlockerCode, ...]]:
    return single_container_blockers("mrw_minolta_raw", blockers)


def references_for_only_mrw(
    references: tuple[str, ...],
) -> dict[RawFamilyContainer, tuple[str, ...]]:
    return single_container_references("mrw_minolta_raw", references)


def surfaces_for_only_iiq(
    surfaces: tuple[RawFamilyWriteSurface, ...],
) -> dict[RawFamilyContainer, tuple[RawFamilyWriteSurface, ...]]:
    return single_container_surfaces("iiq_phaseone", surfaces)


def blockers_for_only_iiq(
    blockers: tuple[RawFamilyBlockerCode, ...],
) -> dict[RawFamilyContainer, tuple[RawFamilyBlockerCode, ...]]:
    return single_container_blockers("iiq_phaseone", blockers)


def references_for_only_iiq(
    references: tuple[str, ...],
) -> dict[RawFamilyContainer, tuple[str, ...]]:
    return single_container_references("iiq_phaseone", references)


def nikon_capture_scalar_spec(tag_name: str) -> RawFamilyRequestedTagSpec:
    return RawFamilyRequestedTagSpec(
        requested_tag=tag_name,
        surfaces_by_container=surfaces_for_only_nef(("nef_nikon_capture_scalar",)),
        blockers_by_container=blockers_for_only_nef(
            (
                "requires_nef_tiff_directory_rebuild",
                "requires_nikon_capture_block_rewrite",
                "requires_nikon_makernote_key_prescan",
            )
        ),
        evidence_ids_by_container=references_for_only_nef(
            (
                NIKON_TYPE2_SOURCE,
                NIKON_PREVIEW_IFD_SOURCE,
                NIKON_PROCESS_SOURCE,
                WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
                NIKON_CAPTURE_MAIN_SOURCE,
                NIKON_CAPTURE_TAGS_SOURCE,
                NIKON_CAPTURE_WRITE_SOURCE,
            )
        ),
    )


FUJIFILM_MAIN_SOURCE = "fujifilm.main.source"
FUJIFILM_RAF_HEADER_SOURCE = "fujifilm.raf.header.source"
FUJIFILM_WRITE_RAF_SOURCE = "fujifilm.write.raf.source"
EXIF_USER_COMMENT_SOURCE = "exif.user.comment.source"
NIKON_TYPE2_SOURCE = "nikon.type2.source"
NIKON_PREVIEW_IFD_SOURCE = "nikon.preview.ifd.source"
NIKON_PROCESS_SOURCE = "nikon.process.source"
NIKON_CAPTURE_MAIN_SOURCE = "nikon.capture.main.source"
NIKON_CAPTURE_TAGS_SOURCE = "nikon.capture.tags.source"
NIKON_CAPTURE_WRITE_SOURCE = "nikon.capture.write.source"
IPTC_CAPTION_ABSTRACT_SOURCE = "iptc.caption.abstract.source"
MINOLTA_RAW_MAIN_SOURCE = "minolta.raw.main.source"
MINOLTA_RAW_BINARY_SOURCE = "minolta.raw.binary.source"
MINOLTA_RAW_RIF_SOURCE = "minolta.raw.rif.source"
MINOLTA_RAW_WRITE_SOURCE = "minolta.raw.write.source"
WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE = "write.exif.makernote.rewrite.source"
WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE = "write.exif.image.data.fixup.source"
PHASEONE_MAIN_SOURCE = "phaseone.main.source"
PHASEONE_SERIAL_SOURCE = "phaseone.serial.source"
PHASEONE_WRITE_SOURCE = "phaseone.write.source"
EXIF_FOCAL_LENGTH_SOURCE = "exif.focal.length.source"
WRITER_RAF_ROUTING_SOURCE = "writer.raf.routing.source"
UNKNOWN_SCAN_SOURCE = "unknown.scan.source"

RAW_FAMILY_REQUESTED_TAG_SPECS: dict[str, RawFamilyRequestedTagSpec] = {
    "UserComment": RawFamilyRequestedTagSpec(
        requested_tag="UserComment",
        surfaces_by_container=single_container_surfaces(
            "raf_fuji_embedded_jpeg", ("raf_embedded_jpeg_exif", "raf_header_offsets")
        )
        | {"unknown_jpeg_exif": ("jpeg_exif",)},
        blockers_by_container=single_container_blockers(
            "raf_fuji_embedded_jpeg",
            ("requires_raf_embedded_jpeg_rewrite", "requires_raf_header_offset_rebuild"),
        )
        | {"unknown_jpeg_exif": ("route_to_jpeg_exif_writer_not_raw_family",)},
        evidence_ids_by_container=single_container_references(
            "raf_fuji_embedded_jpeg",
            (
                WRITER_RAF_ROUTING_SOURCE,
                FUJIFILM_WRITE_RAF_SOURCE,
                FUJIFILM_RAF_HEADER_SOURCE,
                EXIF_USER_COMMENT_SOURCE,
            ),
        )
        | {"unknown_jpeg_exif": (EXIF_USER_COMMENT_SOURCE,)},
    ),
    "PhotoEffects": nikon_capture_scalar_spec("PhotoEffects"),
    "VignetteControlIntensity": nikon_capture_scalar_spec("VignetteControlIntensity"),
    "Caption-abstract": RawFamilyRequestedTagSpec(
        requested_tag="Caption-abstract",
        surfaces_by_container=surfaces_for_only_nef(
            ("nef_tiff_iptc_naa", "nef_nikon_capture_iptc")
        ),
        blockers_by_container=blockers_for_only_nef(
            ("requires_nef_tiff_directory_rebuild", "requires_nikon_capture_block_rewrite")
        ),
        evidence_ids_by_container=references_for_only_nef(
            (
                NIKON_CAPTURE_MAIN_SOURCE,
                NIKON_CAPTURE_TAGS_SOURCE,
                NIKON_CAPTURE_WRITE_SOURCE,
                IPTC_CAPTION_ABSTRACT_SOURCE,
            )
        ),
    ),
    "FocusMode": RawFamilyRequestedTagSpec(
        requested_tag="FocusMode",
        surfaces_by_container=surfaces_for_only_mrw(
            ("mrw_minolta_ttw_tiff", "mrw_minolta_makernote_binary")
        ),
        blockers_by_container=blockers_for_only_mrw(
            (
                "requires_mrw_segment_rebuild",
                "requires_mrw_embedded_tiff_rewrite",
                "requires_minolta_makernote_binary_update",
            )
        ),
        evidence_ids_by_container=references_for_only_mrw(
            (
                MINOLTA_RAW_MAIN_SOURCE,
                MINOLTA_RAW_BINARY_SOURCE,
                MINOLTA_RAW_RIF_SOURCE,
                MINOLTA_RAW_WRITE_SOURCE,
                WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
                WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
            )
        ),
    ),
    "LastFileNumber": RawFamilyRequestedTagSpec(
        requested_tag="LastFileNumber",
        surfaces_by_container=surfaces_for_only_mrw(
            ("mrw_minolta_ttw_tiff", "mrw_minolta_makernote_binary")
        ),
        blockers_by_container=blockers_for_only_mrw(
            (
                "requires_mrw_segment_rebuild",
                "requires_mrw_embedded_tiff_rewrite",
                "requires_minolta_makernote_binary_update",
            )
        ),
        evidence_ids_by_container=references_for_only_mrw(
            (
                MINOLTA_RAW_MAIN_SOURCE,
                MINOLTA_RAW_WRITE_SOURCE,
                WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
                WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
            )
        ),
    ),
    "SerialNumber": RawFamilyRequestedTagSpec(
        requested_tag="SerialNumber",
        surfaces_by_container=surfaces_for_only_iiq(
            ("iiq_phaseone_main_ifd", "iiq_phaseone_sensor_calibration_ifd")
        ),
        blockers_by_container=blockers_for_only_iiq(
            ("requires_phaseone_ifd_rebuild", "requires_phaseone_value_offset_fixups")
        ),
        evidence_ids_by_container=references_for_only_iiq(
            (PHASEONE_MAIN_SOURCE, PHASEONE_SERIAL_SOURCE, PHASEONE_WRITE_SOURCE)
        ),
    ),
    "FocalLength": RawFamilyRequestedTagSpec(
        requested_tag="FocalLength",
        surfaces_by_container=single_container_surfaces("unknown_jpeg_exif", ("jpeg_exif",)),
        blockers_by_container=single_container_blockers(
            "unknown_jpeg_exif", ("route_to_jpeg_exif_writer_not_raw_family",)
        ),
        evidence_ids_by_container=single_container_references(
            "unknown_jpeg_exif", (UNKNOWN_SCAN_SOURCE, EXIF_FOCAL_LENGTH_SOURCE)
        ),
    ),
}


def classify_raw_family_golden_request_file(path: Path) -> RawFamilyWriteRequestClassification:
    return classify_raw_family_golden_request_payload(load_json_object(path))


def classify_raw_family_golden_request_payload(
    payload: JsonObject,
) -> RawFamilyWriteRequestClassification:
    fixture = required_string(payload, "fixture")
    request_id = required_string(payload, "request_id")
    container = container_for_fixture(fixture)
    arguments = tuple(
        classify_write_arg(write_arg, container)
        for write_arg in json_string_array_value(payload, "write_args")
        if is_metadata_assignment_arg(write_arg)
    )
    status = status_for(container, arguments)
    return RawFamilyWriteRequestClassification(
        request_id=request_id,
        fixture=fixture,
        container=container,
        status=status,
        can_rewrite=False,
        arguments=arguments,
        blockers=report_blockers(container, arguments, status),
        evidence_ids=report_evidence_ids(container, arguments),
    )


def build_raw_family_write_routing_report(
    request_paths: tuple[Path, ...],
) -> RawFamilyWriteRoutingReport:
    return RawFamilyWriteRoutingReport(
        requests=tuple(classify_raw_family_golden_request_file(path) for path in request_paths)
    )


def write_raw_family_write_routing_report(
    request_paths: tuple[Path, ...],
    output_path: Path,
) -> RawFamilyWriteRoutingReport:
    report = build_raw_family_write_routing_report(request_paths)
    output_path.write_text(
        json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def classify_write_arg(
    write_arg: str,
    container: RawFamilyContainer,
) -> RawFamilyWriteArgumentClassification:
    requested_tag, requested_value = split_assignment_arg(write_arg)
    canonical_tag = canonical_requested_tag(requested_tag)
    spec = RAW_FAMILY_REQUESTED_TAG_SPECS.get(canonical_tag)
    if spec is None:
        return RawFamilyWriteArgumentClassification(
            raw_argument=write_arg,
            requested_tag=requested_tag,
            requested_value=requested_value,
            target_surfaces=("unknown",),
            blocker_codes=("unsupported_requested_tag",),
            evidence_ids=container_evidence_ids(container),
        )
    return RawFamilyWriteArgumentClassification(
        raw_argument=write_arg,
        requested_tag=requested_tag,
        requested_value=requested_value,
        target_surfaces=spec.surfaces_by_container[container],
        blocker_codes=spec.blockers_by_container[container],
        evidence_ids=spec.evidence_ids_by_container[container],
    )


def container_for_fixture(fixture: str) -> RawFamilyContainer:
    suffix = Path(fixture).suffix.lower()
    if suffix == ".raf":
        return "raf_fuji_embedded_jpeg"
    if suffix == ".nef":
        return "nef_tiff_nikon"
    if suffix == ".mrw":
        return "mrw_minolta_raw"
    if suffix == ".iiq":
        return "iiq_phaseone"
    if suffix in {".jpg", ".jpeg"} and "Unknown" in Path(fixture).name:
        return "unknown_jpeg_exif"
    return "unknown"


def status_for(
    container: RawFamilyContainer,
    arguments: tuple[RawFamilyWriteArgumentClassification, ...],
) -> RawFamilyStatus:
    if container == "unknown_jpeg_exif":
        return "routed_outside_raw_family"
    if container == "unknown":
        return "unsupported"
    if arguments and all("unsupported_requested_tag" not in arg.blocker_codes for arg in arguments):
        return "source_mapped_deferred"
    return "unsupported"


def report_blockers(
    container: RawFamilyContainer,
    arguments: tuple[RawFamilyWriteArgumentClassification, ...],
    status: RawFamilyStatus,
) -> tuple[str, ...]:
    if status == "routed_outside_raw_family":
        return (
            "Unknown.t write fixture is JPEG/EXIF data and should route to the JPEG EXIF writer, "
            "not the RAW-family mutator.",
        )
    if status == "unsupported":
        return (
            "At least one requested tag or fixture does not map to a sourced RAW-family "
            "write surface.",
        )
    if container == "raf_fuji_embedded_jpeg":
        return ("RAF writes require rewriting the embedded JPEG and adjusting RAF header offsets.",)
    if container == "nef_tiff_nikon":
        return (
            "NEF writes require TIFF directory rebuild plus Nikon Capture "
            "maker-note block rewrite.",
        )
    if container == "mrw_minolta_raw":
        return (
            "MRW writes require segment rebuild, embedded TTW TIFF rewrite, and raw data copy.",
        )
    if container == "iiq_phaseone":
        return ("IIQ writes require PhaseOne IFD rebuild with value offset fixups.",)
    return tuple(dict.fromkeys(code for argument in arguments for code in argument.blocker_codes))


def report_evidence_ids(
    container: RawFamilyContainer,
    arguments: tuple[RawFamilyWriteArgumentClassification, ...],
) -> tuple[str, ...]:
    references: list[str] = list(container_evidence_ids(container))
    for argument in arguments:
        for reference in argument.evidence_ids:
            if reference not in references:
                references.append(reference)
    return tuple(references)


def container_evidence_ids(container: RawFamilyContainer) -> tuple[str, ...]:
    if container == "raf_fuji_embedded_jpeg":
        return (WRITER_RAF_ROUTING_SOURCE, FUJIFILM_MAIN_SOURCE, FUJIFILM_WRITE_RAF_SOURCE)
    if container == "nef_tiff_nikon":
        return (
            NIKON_TYPE2_SOURCE,
            NIKON_PROCESS_SOURCE,
            WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
            NIKON_CAPTURE_MAIN_SOURCE,
            NIKON_CAPTURE_WRITE_SOURCE,
        )
    if container == "mrw_minolta_raw":
        return (
            MINOLTA_RAW_MAIN_SOURCE,
            MINOLTA_RAW_WRITE_SOURCE,
            WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE,
            WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE,
        )
    if container == "iiq_phaseone":
        return (PHASEONE_MAIN_SOURCE, PHASEONE_WRITE_SOURCE)
    if container == "unknown_jpeg_exif":
        return (UNKNOWN_SCAN_SOURCE, EXIF_FOCAL_LENGTH_SOURCE)
    return ()


def is_metadata_assignment_arg(write_arg: str) -> bool:
    return write_arg.startswith("-") and "=" in write_arg and not write_arg.startswith("-api")


def split_assignment_arg(write_arg: str) -> tuple[str, str]:
    trimmed = write_arg.removeprefix("-")
    tag, separator, value = trimmed.partition("=")
    if not separator:
        raise ValueError(f"Expected metadata assignment argument: {write_arg}")
    return tag, value


def canonical_requested_tag(requested_tag: str) -> str:
    return requested_tag.rsplit(":", 1)[-1]


def required_string(payload: JsonObject, key: str) -> str:
    value = json_string_value(payload, key)
    if value is None:
        raise ValueError(f"Expected string JSON field: {key}")
    return value
