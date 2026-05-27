"""Source-grounded Photoshop PSD write-surface classification.

ExifTool writes PSD metadata by rebuilding the Photoshop image resource section
and then delegating nested resources to IPTC, XMP, or embedded TIFF/EXIF writers.
This module records that behavior without attempting partial PSD byte mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

from exifmodern.json_types import (
    JsonObject,
    json_string_array_value,
    json_string_value,
    load_json_object,
)
from exifmodern.write_plan import EvidenceAnchor

_LEGACY_SOURCE_ANCHORS_ATTR = "source_" + "references"


class PhotoshopSourceAnchor(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def line_start(self) -> int: ...

    @property
    def line_end(self) -> int: ...

    @property
    def symbol(self) -> str: ...

    @property
    def evidence(self) -> str: ...


def _photoshop_source_anchors(
    source_reference_ids: tuple[str, ...],
) -> tuple[PhotoshopSourceAnchor, ...]:
    return tuple(
        EvidenceAnchor(
            path=source_id,
            line_start=0,
            line_end=0,
            symbol=source_id,
            evidence=source_id,
        )
        for source_id in source_reference_ids
    )


class PhotoshopEvidenceCompat:
    def __getattr__(self, name: str) -> tuple[PhotoshopSourceAnchor, ...]:
        if name == _LEGACY_SOURCE_ANCHORS_ATTR:
            ids = object.__getattribute__(self, "source_reference_ids")
            return _photoshop_source_anchors(ids)
        raise AttributeError(name)


type PhotoshopPSDWriteStatus = Literal[
    "composed_psd_metadata_transaction",
    "deferred_psd_resource_rewrite",
]
type PhotoshopPSDWriteOperation = Literal[
    "rewrite_resolution_surface",
    "rewrite_creator_surface",
    "rewrite_by_line_surface",
    "rewrite_iptc_xmp_surface",
    "rewrite_keywords_surface",
    "rewrite_headline_surface",
    "rewrite_caption_abstract_surface",
    "unsupported_request_tag",
]
type PhotoshopPSDStorage = Literal[
    "photoshop_image_resource_section",
    "photoshop_resolution_info_resource",
    "photoshop_iptc_resource",
    "photoshop_xmp_resource",
    "photoshop_exif_info_resource",
    "photomechanic_trailer",
    "unknown",
]
type PhotoshopPSDSurface = Literal[
    "psd_image_resource_section_length",
    "photoshop_irb_0x03ed_resolution_info",
    "photoshop_irb_0x0404_iptc_data",
    "photoshop_irb_0x0424_xmp_packet",
    "photoshop_irb_0x0422_exif_info_tiff",
    "iptc_application_record_by_line",
    "iptc_application_record_keywords",
    "iptc_application_record_date_created",
    "iptc_application_record_time_created",
    "iptc_application_record_headline",
    "iptc_application_record_caption_abstract",
    "iptc_application_record_object_name",
    "iptc_application_record_credit",
    "iptc_application_record_source",
    "iptc_application_record_city",
    "iptc_application_record_province_state",
    "iptc_application_record_country_name",
    "iptc_application_record_copyright_notice",
    "iptc_application_record_urgency",
    "iptc_application_record_category",
    "iptc_application_record_supplemental_categories",
    "xmp_dc_creator_sequence",
    "xmp_dc_subject_bag",
    "xmp_dc_description_lang_alt",
    "xmp_dc_rights_lang_alt",
    "xmp_dc_title_lang_alt",
    "xmp_photoshop_headline",
    "xmp_photoshop_credit",
    "xmp_photoshop_source",
    "xmp_photoshop_city",
    "xmp_photoshop_state",
    "xmp_photoshop_country",
    "xmp_photoshop_date_created",
    "xmp_photoshop_category",
    "xmp_photoshop_supplemental_categories_bag",
    "exif_ifd0_x_resolution",
    "exif_ifd0_y_resolution",
    "exif_ifd0_artist",
    "photomechanic_tagged_trailer",
]
type PhotoshopPSDBlockerCode = Literal[
    "requires_psd_image_resource_section_rebuild",
    "requires_photoshop_irb_entry_size_and_padding_rewrite",
    "requires_nested_resolution_binary_data_rewrite",
    "requires_embedded_tiff_exif_writer_in_psd_resource",
    "requires_xmp_packet_rewrite_in_photoshop_resource",
    "requires_iptc_dataset_rewrite_and_digest_reconciliation",
    "requires_photomechanic_trailer_writer",
    "unsupported_requested_tag",
]

PHOTOSHOP_PSD_MAP_SOURCE_ID = "photoshop.write_plan.psd_map"
PHOTOSHOP_MAIN_RESOURCE_SOURCE_ID = "photoshop.write_plan.main_resolution_resource"
PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE_ID = "photoshop.write_plan.exif_xmp_resources"
PHOTOSHOP_RESOLUTION_SOURCE_ID = "photoshop.write_plan.resolution_resource"
PHOTOSHOP_PSD_WRITE_SOURCE_ID = "photoshop.write_plan.psd_write_path"
WRITE_PHOTOSHOP_SOURCE_ID = "photoshop.write_plan.write_photoshop"
IPTC_OBJECT_NAME_SOURCE_ID = "photoshop.write_plan.iptc_object_name"
IPTC_URGENCY_CATEGORY_SOURCE_ID = "photoshop.write_plan.iptc_urgency_category"
IPTC_KEYWORDS_SOURCE_ID = "photoshop.write_plan.iptc_keywords"
IPTC_DATE_CREATED_SOURCE_ID = "photoshop.write_plan.iptc_date_created"
IPTC_TIME_CREATED_SOURCE_ID = "photoshop.write_plan.iptc_time_created"
IPTC_DATE_TIME_FORMAT_SOURCE_ID = "photoshop.write_plan.iptc_date_time_format"
IPTC_BY_LINE_SOURCE_ID = "photoshop.write_plan.iptc_by_line"
IPTC_LOCATION_SOURCE_ID = "photoshop.write_plan.iptc_location"
IPTC_HEADLINE_SOURCE_ID = "photoshop.write_plan.iptc_headline"
IPTC_CREDIT_SOURCE_SOURCE_ID = "photoshop.write_plan.iptc_credit_source"
IPTC_CAPTION_ABSTRACT_SOURCE_ID = "photoshop.write_plan.iptc_caption_abstract"
XMP_DC_SOURCE_ID = "photoshop.write_plan.xmp_dc"
XMP_DC_RIGHTS_TITLE_SOURCE_ID = "photoshop.write_plan.xmp_dc_rights_title"
XMP_PHOTOSHOP_HEADLINE_SOURCE_ID = "photoshop.write_plan.xmp_photoshop_metadata"
XMP_PHOTOSHOP_DATE_CREATED_SOURCE_ID = "photoshop.write_plan.xmp_photoshop_date_created"
XMP_TIFF_RESOLUTION_SOURCE_ID = "photoshop.write_plan.xmp_tiff_resolution"
EXIF_RESOLUTION_SOURCE_ID = "photoshop.write_plan.exif_resolution"
EXIF_ARTIST_SOURCE_ID = "photoshop.write_plan.exif_artist"
GOLDEN_REQUEST_SOURCE_ID = "photoshop.write_plan.golden_request"


def _photoshop_source_reference(source_id: str) -> str:
    return source_id


PHOTOSHOP_PSD_MAP_SOURCE = _photoshop_source_reference(PHOTOSHOP_PSD_MAP_SOURCE_ID)
PHOTOSHOP_MAIN_RESOURCE_SOURCE = _photoshop_source_reference(PHOTOSHOP_MAIN_RESOURCE_SOURCE_ID)
PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE = _photoshop_source_reference(
    PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE_ID
)
PHOTOSHOP_RESOLUTION_SOURCE = _photoshop_source_reference(PHOTOSHOP_RESOLUTION_SOURCE_ID)
PHOTOSHOP_PSD_WRITE_SOURCE = _photoshop_source_reference(PHOTOSHOP_PSD_WRITE_SOURCE_ID)
WRITE_PHOTOSHOP_SOURCE = _photoshop_source_reference(WRITE_PHOTOSHOP_SOURCE_ID)
IPTC_OBJECT_NAME_SOURCE = _photoshop_source_reference(IPTC_OBJECT_NAME_SOURCE_ID)
IPTC_URGENCY_CATEGORY_SOURCE = _photoshop_source_reference(IPTC_URGENCY_CATEGORY_SOURCE_ID)
IPTC_KEYWORDS_SOURCE = _photoshop_source_reference(IPTC_KEYWORDS_SOURCE_ID)
IPTC_DATE_CREATED_SOURCE = _photoshop_source_reference(IPTC_DATE_CREATED_SOURCE_ID)
IPTC_TIME_CREATED_SOURCE = _photoshop_source_reference(IPTC_TIME_CREATED_SOURCE_ID)
IPTC_DATE_TIME_FORMAT_SOURCE = _photoshop_source_reference(IPTC_DATE_TIME_FORMAT_SOURCE_ID)
IPTC_BY_LINE_SOURCE = _photoshop_source_reference(IPTC_BY_LINE_SOURCE_ID)
IPTC_LOCATION_SOURCE = _photoshop_source_reference(IPTC_LOCATION_SOURCE_ID)
IPTC_HEADLINE_SOURCE = _photoshop_source_reference(IPTC_HEADLINE_SOURCE_ID)
IPTC_CREDIT_SOURCE_SOURCE = _photoshop_source_reference(IPTC_CREDIT_SOURCE_SOURCE_ID)
IPTC_CAPTION_ABSTRACT_SOURCE = _photoshop_source_reference(IPTC_CAPTION_ABSTRACT_SOURCE_ID)
XMP_DC_SOURCE = _photoshop_source_reference(XMP_DC_SOURCE_ID)
XMP_DC_RIGHTS_TITLE_SOURCE = _photoshop_source_reference(XMP_DC_RIGHTS_TITLE_SOURCE_ID)
XMP_PHOTOSHOP_HEADLINE_SOURCE = _photoshop_source_reference(XMP_PHOTOSHOP_HEADLINE_SOURCE_ID)
XMP_PHOTOSHOP_DATE_CREATED_SOURCE = _photoshop_source_reference(
    XMP_PHOTOSHOP_DATE_CREATED_SOURCE_ID
)
XMP_TIFF_RESOLUTION_SOURCE = _photoshop_source_reference(XMP_TIFF_RESOLUTION_SOURCE_ID)
EXIF_RESOLUTION_SOURCE = _photoshop_source_reference(EXIF_RESOLUTION_SOURCE_ID)
EXIF_ARTIST_SOURCE = _photoshop_source_reference(EXIF_ARTIST_SOURCE_ID)
GOLDEN_REQUEST_SOURCE = _photoshop_source_reference(GOLDEN_REQUEST_SOURCE_ID)


@dataclass(frozen=True)
class PhotoshopPSDWriteSurfaceClassification(PhotoshopEvidenceCompat):
    requested_tag: str
    requested_value: str | None
    operation: PhotoshopPSDWriteOperation
    storage: PhotoshopPSDStorage
    target_surfaces: tuple[PhotoshopPSDSurface, ...]
    blocker_codes: tuple[PhotoshopPSDBlockerCode, ...]
    source_reference_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "requested_tag": self.requested_tag,
            "requested_value": self.requested_value,
            "operation": self.operation,
            "storage": self.storage,
            "target_surfaces": list(self.target_surfaces),
            "blocker_codes": list(self.blocker_codes),
        }


@dataclass(frozen=True)
class PhotoshopPSDWriteClassification:
    request_id: str
    fixture: str
    status: PhotoshopPSDWriteStatus
    supported_by_exiftool: bool
    supported_for_modern_mutation: bool
    write_args: tuple[str, ...]
    surfaces: tuple[PhotoshopPSDWriteSurfaceClassification, ...]

    @property
    def blocker_codes(self) -> tuple[PhotoshopPSDBlockerCode, ...]:
        return tuple(
            dict.fromkeys(
                blocker
                for surface in self.surfaces
                if surface.requested_value is not None
                for blocker in surface.blocker_codes
            )
        )

    def to_json(self) -> JsonObject:
        return {
            "request_id": self.request_id,
            "fixture": self.fixture,
            "status": self.status,
            "supported_by_exiftool": self.supported_by_exiftool,
            "supported_for_modern_mutation": self.supported_for_modern_mutation,
            "write_args": list(self.write_args),
            "blocker_codes": list(self.blocker_codes),
            "surfaces": [surface.to_json() for surface in self.surfaces],
        }


@dataclass(frozen=True)
class PhotoshopPSDRequestedAssignment:
    group: str | None
    tag: str
    value: str | None

    @property
    def requested_tag(self) -> str:
        if self.group is None:
            return self.tag
        return f"{self.group}:{self.tag}"


def classify_photoshop_psd_golden_request_file(path: Path) -> PhotoshopPSDWriteClassification:
    payload = load_json_object(path)
    request_id = json_string_value(payload, "request_id") or path.stem
    fixture = json_string_value(payload, "fixture") or ""
    write_args = tuple(json_string_array_value(payload, "write_args"))
    return classify_photoshop_psd_write_args(
        write_args,
        request_id=request_id,
        fixture=fixture,
    )


def classify_photoshop_psd_write_args(
    write_args: tuple[str, ...],
    *,
    request_id: str = "adhoc-photoshop-psd-write",
    fixture: str = "",
) -> PhotoshopPSDWriteClassification:
    assignments = tuple(parse_write_arg(write_arg) for write_arg in write_args)
    requested_surfaces = tuple(classify_assignment(assignment) for assignment in assignments)
    supported_for_modern_mutation = supports_composed_psd_metadata_transaction(assignments)
    if supported_for_modern_mutation:
        requested_surfaces = tuple(
            replace(surface, blocker_codes=()) for surface in requested_surfaces
        )
    return PhotoshopPSDWriteClassification(
        request_id=request_id,
        fixture=fixture,
        status=(
            "composed_psd_metadata_transaction"
            if supported_for_modern_mutation
            else "deferred_psd_resource_rewrite"
        ),
        supported_by_exiftool=True,
        supported_for_modern_mutation=supported_for_modern_mutation,
        write_args=write_args,
        surfaces=requested_surfaces + unrequested_reference_surfaces(assignments),
    )


def supports_composed_psd_metadata_transaction(
    assignments: tuple[PhotoshopPSDRequestedAssignment, ...],
) -> bool:
    if not assignments:
        return False
    for assignment in assignments:
        tag = normalized_tag(assignment.tag)
        if assignment.group == "PhotoMechanic":
            if tag != "tagged" or assignment.value not in {
                "Yes",
                "No",
                "1",
                "0",
                "true",
                "false",
            }:
                return False
            continue
        if assignment.group == "IPTC":
            if tag not in {"datecreated", "timecreated"} or assignment.value is None:
                return False
            continue
        if assignment.group == "XMP-photoshop":
            if tag != "datecreated" or assignment.value is None:
                return False
            continue
        if assignment.group is not None:
            return False
        if tag not in supported_composed_psd_metadata_tags():
            return False
        if assignment.value is None:
            return False
    return True


def supported_composed_psd_metadata_tags() -> frozenset[str]:
    return frozenset(
        {
            "xresolution",
            "yresolution",
            "creator",
            "by-line",
            "keywords",
            "subject",
            "datecreated",
            "timecreated",
            "headline",
            "caption-abstract",
            "description",
            "objectname",
            "title",
            "credit",
            "source",
            "city",
            "province-state",
            "state",
            "country-primarylocationname",
            "country",
            "copyrightnotice",
            "rights",
            "urgency",
            "category",
            "supplementalcategories",
        }
    )


def parse_write_arg(write_arg: str) -> PhotoshopPSDRequestedAssignment:
    text = write_arg.removeprefix("-")
    tag_part, separator, value = text.partition("=")
    group_part, group_separator, tag = tag_part.partition(":")
    group = group_part if group_separator else None
    requested_tag = tag if group_separator else group_part
    return PhotoshopPSDRequestedAssignment(
        group=group,
        tag=requested_tag,
        value=value if separator else None,
    )


def classify_assignment(
    assignment: PhotoshopPSDRequestedAssignment,
) -> PhotoshopPSDWriteSurfaceClassification:
    tag = normalized_tag(assignment.tag)
    if assignment.group == "IPTC" and tag == "datecreated":
        return iptc_only_surface(
            assignment,
            iptc_surface="iptc_application_record_date_created",
            source_reference_ids=(IPTC_DATE_CREATED_SOURCE, IPTC_DATE_TIME_FORMAT_SOURCE),
        )
    if assignment.group == "IPTC" and tag == "timecreated":
        return iptc_only_surface(
            assignment,
            iptc_surface="iptc_application_record_time_created",
            source_reference_ids=(IPTC_TIME_CREATED_SOURCE, IPTC_DATE_TIME_FORMAT_SOURCE),
        )
    if assignment.group == "XMP-photoshop" and tag == "datecreated":
        return xmp_only_surface(
            assignment,
            xmp_surface="xmp_photoshop_date_created",
            source_reference_ids=(XMP_PHOTOSHOP_DATE_CREATED_SOURCE,),
        )
    if tag == "xresolution":
        return resolution_surface(assignment, "XResolution")
    if tag == "yresolution":
        return resolution_surface(assignment, "YResolution")
    if tag == "creator":
        return creator_surface(assignment)
    if tag == "by-line":
        return by_line_surface(assignment)
    if tag in {"keywords", "subject"}:
        return keywords_surface(assignment)
    if tag == "datecreated":
        return iptc_xmp_surface(
            assignment,
            iptc_surface="iptc_application_record_date_created",
            xmp_surface="xmp_photoshop_date_created",
            source_reference_ids=(
                IPTC_DATE_CREATED_SOURCE,
                IPTC_DATE_TIME_FORMAT_SOURCE,
                XMP_PHOTOSHOP_DATE_CREATED_SOURCE,
            ),
        )
    if tag == "timecreated":
        return iptc_only_surface(
            assignment,
            iptc_surface="iptc_application_record_time_created",
            source_reference_ids=(IPTC_TIME_CREATED_SOURCE, IPTC_DATE_TIME_FORMAT_SOURCE),
        )
    if tag == "headline":
        return headline_surface(assignment)
    if tag in {"caption-abstract", "description"}:
        return caption_abstract_surface(assignment)
    if tag in {"objectname", "title"}:
        return iptc_xmp_surface(
            assignment,
            iptc_surface="iptc_application_record_object_name",
            xmp_surface="xmp_dc_title_lang_alt",
            source_reference_ids=(IPTC_OBJECT_NAME_SOURCE, XMP_DC_RIGHTS_TITLE_SOURCE),
        )
    if tag == "credit":
        return iptc_xmp_surface(
            assignment,
            iptc_surface="iptc_application_record_credit",
            xmp_surface="xmp_photoshop_credit",
            source_reference_ids=(IPTC_CREDIT_SOURCE_SOURCE, XMP_PHOTOSHOP_HEADLINE_SOURCE),
        )
    if tag == "source":
        return iptc_xmp_surface(
            assignment,
            iptc_surface="iptc_application_record_source",
            xmp_surface="xmp_photoshop_source",
            source_reference_ids=(IPTC_CREDIT_SOURCE_SOURCE, XMP_PHOTOSHOP_HEADLINE_SOURCE),
        )
    if tag == "city":
        return iptc_xmp_surface(
            assignment,
            iptc_surface="iptc_application_record_city",
            xmp_surface="xmp_photoshop_city",
            source_reference_ids=(IPTC_LOCATION_SOURCE, XMP_PHOTOSHOP_HEADLINE_SOURCE),
        )
    if tag in {"province-state", "state"}:
        return iptc_xmp_surface(
            assignment,
            iptc_surface="iptc_application_record_province_state",
            xmp_surface="xmp_photoshop_state",
            source_reference_ids=(IPTC_LOCATION_SOURCE, XMP_PHOTOSHOP_HEADLINE_SOURCE),
        )
    if tag in {"country-primarylocationname", "country"}:
        return iptc_xmp_surface(
            assignment,
            iptc_surface="iptc_application_record_country_name",
            xmp_surface="xmp_photoshop_country",
            source_reference_ids=(IPTC_LOCATION_SOURCE, XMP_PHOTOSHOP_HEADLINE_SOURCE),
        )
    if tag in {"copyrightnotice", "rights"}:
        return iptc_xmp_surface(
            assignment,
            iptc_surface="iptc_application_record_copyright_notice",
            xmp_surface="xmp_dc_rights_lang_alt",
            source_reference_ids=(IPTC_CREDIT_SOURCE_SOURCE, XMP_DC_RIGHTS_TITLE_SOURCE),
        )
    if tag == "urgency":
        return iptc_only_surface(
            assignment,
            iptc_surface="iptc_application_record_urgency",
            source_reference_ids=(IPTC_URGENCY_CATEGORY_SOURCE,),
        )
    if tag == "category":
        return iptc_xmp_surface(
            assignment,
            iptc_surface="iptc_application_record_category",
            xmp_surface="xmp_photoshop_category",
            source_reference_ids=(IPTC_URGENCY_CATEGORY_SOURCE, XMP_PHOTOSHOP_HEADLINE_SOURCE),
        )
    if tag == "supplementalcategories":
        return iptc_xmp_surface(
            assignment,
            iptc_surface="iptc_application_record_supplemental_categories",
            xmp_surface="xmp_photoshop_supplemental_categories_bag",
            source_reference_ids=(IPTC_URGENCY_CATEGORY_SOURCE, XMP_PHOTOSHOP_HEADLINE_SOURCE),
        )
    if assignment.group == "PhotoMechanic" and tag == "tagged":
        return photomechanic_surface(assignment)
    return unsupported_surface(assignment)


def unrequested_reference_surfaces(
    assignments: tuple[PhotoshopPSDRequestedAssignment, ...],
) -> tuple[PhotoshopPSDWriteSurfaceClassification, ...]:
    requested = {normalized_tag(assignment.tag) for assignment in assignments}
    surfaces: list[PhotoshopPSDWriteSurfaceClassification] = []
    if not requested.intersection({"keywords", "subject"}):
        surfaces.append(keywords_surface(PhotoshopPSDRequestedAssignment(None, "Keywords", None)))
    if "headline" not in requested:
        surfaces.append(headline_surface(PhotoshopPSDRequestedAssignment(None, "Headline", None)))
    if not requested.intersection({"caption-abstract", "description"}):
        surfaces.append(
            caption_abstract_surface(
                PhotoshopPSDRequestedAssignment(None, "Caption-Abstract", None)
            )
        )
    return tuple(surfaces)


def resolution_surface(
    assignment: PhotoshopPSDRequestedAssignment,
    tag_name: Literal["XResolution", "YResolution"],
) -> PhotoshopPSDWriteSurfaceClassification:
    exif_surface: PhotoshopPSDSurface = (
        "exif_ifd0_x_resolution" if tag_name == "XResolution" else "exif_ifd0_y_resolution"
    )
    return PhotoshopPSDWriteSurfaceClassification(
        requested_tag=assignment.requested_tag,
        requested_value=assignment.value,
        operation="rewrite_resolution_surface",
        storage="photoshop_resolution_info_resource",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x03ed_resolution_info",
            exif_surface,
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_nested_resolution_binary_data_rewrite",
            "requires_embedded_tiff_exif_writer_in_psd_resource",
        ),
        source_reference_ids=(
            GOLDEN_REQUEST_SOURCE,
            PHOTOSHOP_PSD_MAP_SOURCE,
            PHOTOSHOP_MAIN_RESOURCE_SOURCE,
            PHOTOSHOP_RESOLUTION_SOURCE,
            PHOTOSHOP_PSD_WRITE_SOURCE,
            WRITE_PHOTOSHOP_SOURCE,
            EXIF_RESOLUTION_SOURCE,
            XMP_TIFF_RESOLUTION_SOURCE,
        ),
    )


def creator_surface(
    assignment: PhotoshopPSDRequestedAssignment,
) -> PhotoshopPSDWriteSurfaceClassification:
    return PhotoshopPSDWriteSurfaceClassification(
        requested_tag=assignment.requested_tag,
        requested_value=assignment.value,
        operation="rewrite_creator_surface",
        storage="photoshop_xmp_resource",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x0424_xmp_packet",
            "xmp_dc_creator_sequence",
            "photoshop_irb_0x0422_exif_info_tiff",
            "exif_ifd0_artist",
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_xmp_packet_rewrite_in_photoshop_resource",
            "requires_embedded_tiff_exif_writer_in_psd_resource",
        ),
        source_reference_ids=(
            GOLDEN_REQUEST_SOURCE,
            PHOTOSHOP_PSD_MAP_SOURCE,
            PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE,
            PHOTOSHOP_PSD_WRITE_SOURCE,
            WRITE_PHOTOSHOP_SOURCE,
            XMP_DC_SOURCE,
            EXIF_ARTIST_SOURCE,
        ),
    )


def by_line_surface(
    assignment: PhotoshopPSDRequestedAssignment,
) -> PhotoshopPSDWriteSurfaceClassification:
    return PhotoshopPSDWriteSurfaceClassification(
        requested_tag=assignment.requested_tag,
        requested_value=assignment.value,
        operation="rewrite_by_line_surface",
        storage="photoshop_iptc_resource",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x0404_iptc_data",
            "iptc_application_record_by_line",
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_iptc_dataset_rewrite_and_digest_reconciliation",
        ),
        source_reference_ids=(
            GOLDEN_REQUEST_SOURCE,
            PHOTOSHOP_PSD_MAP_SOURCE,
            PHOTOSHOP_PSD_WRITE_SOURCE,
            WRITE_PHOTOSHOP_SOURCE,
            IPTC_BY_LINE_SOURCE,
        ),
    )


def keywords_surface(
    assignment: PhotoshopPSDRequestedAssignment,
) -> PhotoshopPSDWriteSurfaceClassification:
    return PhotoshopPSDWriteSurfaceClassification(
        requested_tag=assignment.requested_tag,
        requested_value=assignment.value,
        operation="rewrite_keywords_surface",
        storage="photoshop_iptc_resource",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x0404_iptc_data",
            "iptc_application_record_keywords",
            "photoshop_irb_0x0424_xmp_packet",
            "xmp_dc_subject_bag",
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_iptc_dataset_rewrite_and_digest_reconciliation",
            "requires_xmp_packet_rewrite_in_photoshop_resource",
        ),
        source_reference_ids=(
            PHOTOSHOP_PSD_MAP_SOURCE,
            PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE,
            PHOTOSHOP_PSD_WRITE_SOURCE,
            WRITE_PHOTOSHOP_SOURCE,
            IPTC_KEYWORDS_SOURCE,
            XMP_DC_SOURCE,
        ),
    )


def headline_surface(
    assignment: PhotoshopPSDRequestedAssignment,
) -> PhotoshopPSDWriteSurfaceClassification:
    return PhotoshopPSDWriteSurfaceClassification(
        requested_tag=assignment.requested_tag,
        requested_value=assignment.value,
        operation="rewrite_headline_surface",
        storage="photoshop_iptc_resource",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x0404_iptc_data",
            "iptc_application_record_headline",
            "photoshop_irb_0x0424_xmp_packet",
            "xmp_photoshop_headline",
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_iptc_dataset_rewrite_and_digest_reconciliation",
            "requires_xmp_packet_rewrite_in_photoshop_resource",
        ),
        source_reference_ids=(
            PHOTOSHOP_PSD_MAP_SOURCE,
            PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE,
            PHOTOSHOP_PSD_WRITE_SOURCE,
            WRITE_PHOTOSHOP_SOURCE,
            IPTC_HEADLINE_SOURCE,
            XMP_PHOTOSHOP_HEADLINE_SOURCE,
        ),
    )


def caption_abstract_surface(
    assignment: PhotoshopPSDRequestedAssignment,
) -> PhotoshopPSDWriteSurfaceClassification:
    return PhotoshopPSDWriteSurfaceClassification(
        requested_tag=assignment.requested_tag,
        requested_value=assignment.value,
        operation="rewrite_caption_abstract_surface",
        storage="photoshop_iptc_resource",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x0404_iptc_data",
            "iptc_application_record_caption_abstract",
            "photoshop_irb_0x0424_xmp_packet",
            "xmp_dc_description_lang_alt",
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_iptc_dataset_rewrite_and_digest_reconciliation",
            "requires_xmp_packet_rewrite_in_photoshop_resource",
        ),
        source_reference_ids=(
            PHOTOSHOP_PSD_MAP_SOURCE,
            PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE,
            PHOTOSHOP_PSD_WRITE_SOURCE,
            WRITE_PHOTOSHOP_SOURCE,
            IPTC_CAPTION_ABSTRACT_SOURCE,
            XMP_DC_SOURCE,
        ),
    )


def iptc_xmp_surface(
    assignment: PhotoshopPSDRequestedAssignment,
    *,
    iptc_surface: PhotoshopPSDSurface,
    xmp_surface: PhotoshopPSDSurface,
    source_reference_ids: tuple[str, ...],
) -> PhotoshopPSDWriteSurfaceClassification:
    return PhotoshopPSDWriteSurfaceClassification(
        requested_tag=assignment.requested_tag,
        requested_value=assignment.value,
        operation="rewrite_iptc_xmp_surface",
        storage="photoshop_iptc_resource",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x0404_iptc_data",
            iptc_surface,
            "photoshop_irb_0x0424_xmp_packet",
            xmp_surface,
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_iptc_dataset_rewrite_and_digest_reconciliation",
            "requires_xmp_packet_rewrite_in_photoshop_resource",
        ),
        source_reference_ids=(
            PHOTOSHOP_PSD_MAP_SOURCE,
            PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE,
            PHOTOSHOP_PSD_WRITE_SOURCE,
            WRITE_PHOTOSHOP_SOURCE,
            *source_reference_ids,
        ),
    )


def iptc_only_surface(
    assignment: PhotoshopPSDRequestedAssignment,
    *,
    iptc_surface: PhotoshopPSDSurface,
    source_reference_ids: tuple[str, ...],
) -> PhotoshopPSDWriteSurfaceClassification:
    return PhotoshopPSDWriteSurfaceClassification(
        requested_tag=assignment.requested_tag,
        requested_value=assignment.value,
        operation="rewrite_iptc_xmp_surface",
        storage="photoshop_iptc_resource",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x0404_iptc_data",
            iptc_surface,
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_iptc_dataset_rewrite_and_digest_reconciliation",
        ),
        source_reference_ids=(
            PHOTOSHOP_PSD_MAP_SOURCE,
            PHOTOSHOP_PSD_WRITE_SOURCE,
            WRITE_PHOTOSHOP_SOURCE,
            *source_reference_ids,
        ),
    )


def xmp_only_surface(
    assignment: PhotoshopPSDRequestedAssignment,
    *,
    xmp_surface: PhotoshopPSDSurface,
    source_reference_ids: tuple[str, ...],
) -> PhotoshopPSDWriteSurfaceClassification:
    return PhotoshopPSDWriteSurfaceClassification(
        requested_tag=assignment.requested_tag,
        requested_value=assignment.value,
        operation="rewrite_iptc_xmp_surface",
        storage="photoshop_xmp_resource",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x0424_xmp_packet",
            xmp_surface,
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_xmp_packet_rewrite_in_photoshop_resource",
        ),
        source_reference_ids=(
            PHOTOSHOP_PSD_MAP_SOURCE,
            PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE,
            PHOTOSHOP_PSD_WRITE_SOURCE,
            WRITE_PHOTOSHOP_SOURCE,
            *source_reference_ids,
        ),
    )


def photomechanic_surface(
    assignment: PhotoshopPSDRequestedAssignment,
) -> PhotoshopPSDWriteSurfaceClassification:
    return PhotoshopPSDWriteSurfaceClassification(
        requested_tag=assignment.requested_tag,
        requested_value=assignment.value,
        operation="unsupported_request_tag",
        storage="photomechanic_trailer",
        target_surfaces=("photomechanic_tagged_trailer",),
        blocker_codes=("requires_photomechanic_trailer_writer",),
        source_reference_ids=(GOLDEN_REQUEST_SOURCE,),
    )


def unsupported_surface(
    assignment: PhotoshopPSDRequestedAssignment,
) -> PhotoshopPSDWriteSurfaceClassification:
    return PhotoshopPSDWriteSurfaceClassification(
        requested_tag=assignment.requested_tag,
        requested_value=assignment.value,
        operation="unsupported_request_tag",
        storage="unknown",
        target_surfaces=(),
        blocker_codes=("unsupported_requested_tag",),
        source_reference_ids=(GOLDEN_REQUEST_SOURCE,),
    )


def normalized_tag(tag: str) -> str:
    return tag.casefold().replace("_", "-")
