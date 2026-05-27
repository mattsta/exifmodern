"""Composed Photoshop PSD metadata transaction planning.

ExifTool rewrites PSD metadata by rebuilding the Photoshop image resource
section, delegating nested resources to their format writers, then processing
trailers.  This module composes the package-local nested primitives and keeps
the final byte-emission gate closed when embedded EXIFInfo TIFF staging is still
required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.photoshop.embedded_exif import (
    PhotoshopEmbeddedExifInfoStagingPlan,
    plan_embedded_exif_info_staging,
)
from exifmodern.formats.photoshop.image_resources import PhotoshopImageResourceBlock
from exifmodern.formats.photoshop.iptc import (
    PhotoshopIPTCRewritePlan,
    iptc_dataset_mutations,
    iptc_resource_blockers,
    plan_iptc_dataset_rewrite,
)
from exifmodern.formats.photoshop.nested_metadata_plan import (
    PHOTOSHOP_RESOURCE_ID_IPTC_DATA,
    PHOTOSHOP_RESOURCE_ID_IPTC_DIGEST,
    PHOTOSHOP_RESOURCE_ID_RESOLUTION_INFO,
    PHOTOSHOP_RESOURCE_ID_XMP,
)
from exifmodern.formats.photoshop.photomechanic import (
    PhotoMechanicTrailerRewritePlan,
    plan_photomechanic_tagged_trailer_rewrite,
)
from exifmodern.formats.photoshop.resolution_info import (
    PhotoshopResolutionInfoRewritePlan,
    plan_resolution_info_rewrite,
    resolution_info_mutation,
    resolution_resource_blockers,
)
from exifmodern.formats.photoshop.resource_writer import PhotoshopImageResourceMutation
from exifmodern.formats.photoshop.section_boundary_plan import (
    PhotoshopPSDSectionBoundaryPlan,
    plan_photoshop_psd_section_boundaries,
    rewrite_photoshop_psd_image_resources,
)
from exifmodern.formats.photoshop.write_plan import (
    WRITE_PHOTOSHOP_SOURCE_ID,
    PhotoshopEvidenceCompat,
    PhotoshopPSDRequestedAssignment,
    PhotoshopPSDWriteClassification,
    parse_write_arg,
)
from exifmodern.formats.photoshop.xmp import (
    PhotoshopXMPRewritePlan,
    plan_xmp_resource_rewrite,
    xmp_resource_blockers,
    xmp_resource_mutation,
)
from exifmodern.formats.xmp.property_write import (
    XmpLocalizedTextPropertyWrite,
    XmpLocalizedTextValue,
    XmpPropertyWritePlan,
    XmpPropertyWriteStep,
    XmpTextListPropertyWrite,
    XmpTextPropertyWrite,
    normalize_xmp_date_value,
    xmp_property_spec,
)


class PhotoshopPSDUnsupportedWriteError(RuntimeError):
    """Raised when a PSD request is source-backed but not safely writable."""


@dataclass(frozen=True)
class PhotoshopPSDMetadataTransactionPlan(PhotoshopEvidenceCompat):
    source_length: int
    write_args: tuple[str, ...]
    resource_mutations: tuple[PhotoshopImageResourceMutation, ...]
    section_plan: PhotoshopPSDSectionBoundaryPlan
    resource_transaction_plan: PhotoshopPSDSectionBoundaryPlan
    resolution_plan: PhotoshopResolutionInfoRewritePlan | None
    iptc_plan: PhotoshopIPTCRewritePlan | None
    xmp_plan: PhotoshopXMPRewritePlan | None
    embedded_exif_plan: PhotoshopEmbeddedExifInfoStagingPlan
    photomechanic_plan: PhotoMechanicTrailerRewritePlan | None
    source_reference_ids: tuple[str, ...]

    @property
    def can_write_bytes(self) -> bool:
        return (
            not self.blocker_codes
            and self.resource_transaction_plan.can_rewrite_real_psd
            and (self.photomechanic_plan is None or self.photomechanic_plan.can_write_bytes)
        )

    @property
    def blocker_codes(self) -> tuple[str, ...]:
        blockers: list[str] = []
        blockers.extend(self.embedded_exif_plan.blocker_codes)
        if self.resolution_plan is not None:
            blockers.extend(self.resolution_plan.blocker_codes)
        if self.iptc_plan is not None:
            blockers.extend(self.iptc_plan.blocker_codes)
        if self.xmp_plan is not None:
            blockers.extend(self.xmp_plan.blocker_codes)
        if self.photomechanic_plan is not None:
            blockers.extend(self.photomechanic_plan.blocker_codes)
        blockers.extend(self.resource_transaction_plan.blocker_codes)
        return tuple(dict.fromkeys(blockers))


@dataclass(frozen=True)
class PhotoshopPSDRewriteReadiness:
    supported: bool
    reason: str
    blocker_codes: tuple[str, ...]


def require_supported_photoshop_psd_rewrite(
    classification: PhotoshopPSDWriteClassification,
) -> PhotoshopPSDRewriteReadiness:
    if classification.supported_for_modern_mutation:
        return PhotoshopPSDRewriteReadiness(
            supported=True,
            reason="Photoshop PSD request is supported by the modern writer.",
            blocker_codes=(),
        )
    blocker_codes = tuple(str(blocker) for blocker in classification.blocker_codes)
    raise PhotoshopPSDUnsupportedWriteError(
        "Photoshop PSD rewrite is deferred until source-backed image resource, IPTC, "
        "XMP, embedded EXIF, and trailer mutation is implemented: " + ", ".join(blocker_codes)
    )


def plan_photoshop_psd_metadata_transaction(
    psd_data: bytes,
    write_args: tuple[str, ...],
    *,
    source_backed: bool = True,
    compact_photomechanic_no_padding: bool = False,
) -> PhotoshopPSDMetadataTransactionPlan:
    assignments = tuple(parse_write_arg(write_arg) for write_arg in write_args)
    section_plan = plan_photoshop_psd_section_boundaries(
        psd_data,
        source_backed=source_backed,
    )
    mutations: list[PhotoshopImageResourceMutation] = []
    source_reference_ids: list[str] = [
        WRITE_PHOTOSHOP_SOURCE_ID,
        *section_plan.source_reference_ids,
    ]

    resolution_plan, resolution_mutation = staged_resolution_mutation(
        section_plan,
        assignments,
        source_backed=source_backed,
    )
    if resolution_mutation is not None:
        mutations.append(resolution_mutation)

    iptc_plan, iptc_mutations = staged_iptc_mutations(
        section_plan,
        assignments,
        source_backed=source_backed,
    )
    mutations.extend(iptc_mutations)
    if iptc_plan is not None:
        source_reference_ids.extend(iptc_plan.source_reference_ids)

    xmp_plan, xmp_mutation = staged_xmp_mutation(
        section_plan,
        assignments,
        source_backed=source_backed,
    )
    if xmp_mutation is not None:
        mutations.append(xmp_mutation)
    if xmp_plan is not None:
        source_reference_ids.extend(photoshop_xmp_rewrite_source_reference_ids(xmp_plan))

    embedded_exif_plan = plan_embedded_exif_info_staging(
        section_plan,
        assignments,
        source_backed=source_backed,
    )
    if (
        embedded_exif_plan.resource_mutation_adapter is not None
        and embedded_exif_plan.resource_mutation_adapter.mutation is not None
    ):
        mutations.append(embedded_exif_plan.resource_mutation_adapter.mutation)
    source_reference_ids.extend(embedded_exif_plan.source_reference_ids)

    photomechanic_plan = staged_photomechanic_plan(
        psd_data,
        section_plan,
        assignments,
        source_backed=source_backed,
        compact_no_padding=compact_photomechanic_no_padding,
    )
    if photomechanic_plan is not None:
        source_reference_ids.extend(photomechanic_rewrite_source_reference_ids(photomechanic_plan))

    resource_transaction_plan = plan_photoshop_psd_section_boundaries(
        psd_data,
        mutations=tuple(mutations),
        source_backed=source_backed,
        enable_real_psd_rewrite=True,
    )
    source_reference_ids.extend(resource_transaction_plan.source_reference_ids)

    return PhotoshopPSDMetadataTransactionPlan(
        source_length=len(psd_data),
        write_args=write_args,
        resource_mutations=tuple(mutations),
        section_plan=section_plan,
        resource_transaction_plan=resource_transaction_plan,
        resolution_plan=resolution_plan,
        iptc_plan=iptc_plan,
        xmp_plan=xmp_plan,
        embedded_exif_plan=embedded_exif_plan,
        photomechanic_plan=photomechanic_plan,
        source_reference_ids=tuple(dict.fromkeys(source_reference_ids)),
    )


def photoshop_xmp_rewrite_source_reference_ids(
    xmp_plan: PhotoshopXMPRewritePlan,
) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*xmp_plan.evidence_ids,)))


def photomechanic_rewrite_source_reference_ids(
    photomechanic_plan: PhotoMechanicTrailerRewritePlan,
) -> tuple[str, ...]:
    return photomechanic_plan.evidence_ids


def _photoshop_metadata_source_reference(source_id: str) -> str:
    return source_id


def apply_photoshop_psd_metadata_transaction(
    psd_data: bytes,
    write_args: tuple[str, ...],
    *,
    source_backed: bool = True,
    compact_photomechanic_no_padding: bool = False,
) -> bytes:
    plan = plan_photoshop_psd_metadata_transaction(
        psd_data,
        write_args,
        source_backed=source_backed,
        compact_photomechanic_no_padding=compact_photomechanic_no_padding,
    )
    if not plan.can_write_bytes:
        raise PhotoshopPSDUnsupportedWriteError(
            "Photoshop PSD metadata transaction is blocked: " + ", ".join(plan.blocker_codes)
        )
    rewritten = rewrite_photoshop_psd_image_resources(
        psd_data,
        plan.resource_mutations,
        source_backed=source_backed,
    )
    if plan.photomechanic_plan is None or plan.photomechanic_plan.output_trailer is None:
        return rewritten
    rewritten_section_plan = plan_photoshop_psd_section_boundaries(
        rewritten,
        source_backed=source_backed,
    )
    trailer = rewritten_section_plan.trailer_section
    if trailer is None:
        return rewritten
    return rewritten[: trailer.total_start] + plan.photomechanic_plan.output_trailer


def staged_resolution_mutation(
    section_plan: PhotoshopPSDSectionBoundaryPlan,
    assignments: tuple[PhotoshopPSDRequestedAssignment, ...],
    *,
    source_backed: bool,
) -> tuple[PhotoshopResolutionInfoRewritePlan | None, PhotoshopImageResourceMutation | None]:
    x_resolution = requested_value(assignments, "XResolution")
    y_resolution = requested_value(assignments, "YResolution")
    if x_resolution is None and y_resolution is None:
        return None, None
    blocks = blocks_for_resource(section_plan, PHOTOSHOP_RESOURCE_ID_RESOLUTION_INFO)
    if resolution_resource_blockers(blocks, source_backed=source_backed):
        return None, None
    block = blocks[0]
    plan = plan_resolution_info_rewrite(
        block.data,
        x_resolution=x_resolution,
        y_resolution=y_resolution,
        source_backed=source_backed,
    )
    if not plan.can_write_bytes:
        return plan, None
    return plan, resolution_info_mutation(
        block.data,
        x_resolution=x_resolution,
        y_resolution=y_resolution,
        resource_name=block.name,
        source_backed=source_backed,
    )


def staged_iptc_mutations(
    section_plan: PhotoshopPSDSectionBoundaryPlan,
    assignments: tuple[PhotoshopPSDRequestedAssignment, ...],
    *,
    source_backed: bool,
) -> tuple[PhotoshopIPTCRewritePlan | None, tuple[PhotoshopImageResourceMutation, ...]]:
    object_name = requested_value(assignments, "ObjectName", "Title")
    urgency = requested_value(assignments, "Urgency")
    category = requested_value(assignments, "Category")
    supplemental_categories = requested_values(assignments, "SupplementalCategories")
    date_created = requested_value(assignments, "DateCreated", group="IPTC")
    if date_created is None:
        date_created = requested_value(assignments, "DateCreated")
    time_created = requested_value(assignments, "TimeCreated", group="IPTC")
    if time_created is None:
        time_created = requested_value(assignments, "TimeCreated")
    by_line = requested_value(assignments, "By-Line")
    keywords = requested_values(assignments, "Keywords", "Subject")
    city = requested_value(assignments, "City")
    province_state = requested_value(assignments, "Province-State", "State")
    country = requested_value(assignments, "Country-PrimaryLocationName", "Country")
    headline = requested_value(assignments, "Headline")
    credit = requested_value(assignments, "Credit")
    source = requested_value(assignments, "Source")
    copyright_notice = requested_value(assignments, "CopyrightNotice", "Rights")
    caption_abstract = requested_value(assignments, "Caption-Abstract", "Description")
    if (
        object_name is None
        and urgency is None
        and category is None
        and not supplemental_categories
        and date_created is None
        and time_created is None
        and by_line is None
        and not keywords
        and city is None
        and province_state is None
        and country is None
        and headline is None
        and credit is None
        and source is None
        and copyright_notice is None
        and caption_abstract is None
    ):
        return None, ()
    iptc_blocks = blocks_for_resource(section_plan, PHOTOSHOP_RESOURCE_ID_IPTC_DATA)
    digest_blocks = blocks_for_resource(section_plan, PHOTOSHOP_RESOURCE_ID_IPTC_DIGEST)
    if iptc_resource_blockers(iptc_blocks, digest_blocks, source_backed=source_backed):
        return None, ()
    iptc_block = iptc_blocks[0]
    digest_block = digest_blocks[0] if digest_blocks else None
    plan = plan_iptc_dataset_rewrite(
        iptc_block.data,
        object_name=object_name,
        urgency=urgency,
        category=category,
        supplemental_categories=supplemental_categories or None,
        date_created=date_created,
        time_created=time_created,
        by_line=by_line,
        keywords=keywords or None,
        city=city,
        province_state=province_state,
        country_primary_location_name=country,
        headline=headline,
        credit=credit,
        source=source,
        copyright_notice=copyright_notice,
        caption_abstract=caption_abstract,
        source_backed=source_backed,
    )
    if not plan.can_write_bytes:
        return plan, ()
    return plan, iptc_dataset_mutations(
        iptc_block.data,
        object_name=object_name,
        urgency=urgency,
        category=category,
        supplemental_categories=supplemental_categories or None,
        date_created=date_created,
        time_created=time_created,
        by_line=by_line,
        keywords=keywords or None,
        city=city,
        province_state=province_state,
        country_primary_location_name=country,
        headline=headline,
        credit=credit,
        source=source,
        copyright_notice=copyright_notice,
        caption_abstract=caption_abstract,
        iptc_resource_name=iptc_block.name,
        digest_resource_name=None if digest_block is None else digest_block.name,
        digest_resource_present=digest_block is not None,
        source_backed=source_backed,
    )


def staged_xmp_mutation(
    section_plan: PhotoshopPSDSectionBoundaryPlan,
    assignments: tuple[PhotoshopPSDRequestedAssignment, ...],
    *,
    source_backed: bool,
) -> tuple[PhotoshopXMPRewritePlan | None, PhotoshopImageResourceMutation | None]:
    xmp_plan = photoshop_psd_xmp_plan(assignments)
    if not xmp_plan.steps:
        return None, None
    xmp_blocks = blocks_for_resource(section_plan, PHOTOSHOP_RESOURCE_ID_XMP)
    if xmp_resource_blockers(xmp_blocks, source_backed=source_backed):
        return None, None
    block = xmp_blocks[0] if xmp_blocks else None
    plan = plan_xmp_resource_rewrite(
        None if block is None else block.data,
        xmp_plan,
        source_backed=source_backed,
    )
    if not plan.can_write_bytes:
        return plan, None
    return plan, xmp_resource_mutation(
        None if block is None else block.data,
        xmp_plan,
        resource_name=None if block is None else block.name,
        resource_present=block is not None,
        source_backed=source_backed,
    )


def staged_photomechanic_plan(
    psd_data: bytes,
    section_plan: PhotoshopPSDSectionBoundaryPlan,
    assignments: tuple[PhotoshopPSDRequestedAssignment, ...],
    *,
    source_backed: bool,
    compact_no_padding: bool,
) -> PhotoMechanicTrailerRewritePlan | None:
    tagged = requested_value(assignments, "Tagged", group="PhotoMechanic")
    if tagged is None:
        return None
    tagged_value = photomechanic_tagged_value(tagged)
    if tagged_value is None:
        return None
    trailer = section_plan.trailer_section
    if trailer is None:
        return None
    return plan_photomechanic_tagged_trailer_rewrite(
        psd_data[trailer.data_start : trailer.data_end],
        tagged_value,
        source_backed=source_backed,
        compact_no_padding=compact_no_padding,
    )


def photomechanic_tagged_value(value: str) -> bool | Literal["Yes", "No"] | None:
    if value == "Yes":
        return "Yes"
    if value == "No":
        return "No"
    normalized = value.casefold()
    if normalized in {"1", "true"}:
        return True
    if normalized in {"0", "false"}:
        return False
    return None


def dc_creator_xmp_plan(creator: str) -> XmpPropertyWritePlan:
    return photoshop_psd_xmp_plan((PhotoshopPSDRequestedAssignment(None, "Creator", creator),))


def photoshop_psd_xmp_plan(
    assignments: tuple[PhotoshopPSDRequestedAssignment, ...],
) -> XmpPropertyWritePlan:
    steps: list[XmpPropertyWriteStep] = []
    property_names: list[str] = []
    object_name = requested_value(assignments, "ObjectName", "Title")
    if object_name is not None:
        steps.append(
            XmpLocalizedTextPropertyWrite(
                "XMP-dc:Title",
                (XmpLocalizedTextValue("x-default", object_name),),
            )
        )
        property_names.append("XMP-dc:Title")
    creator = requested_value(assignments, "Creator")
    if creator is not None:
        steps.append(XmpTextListPropertyWrite("XMP-dc:Creator", (creator,)))
        property_names.append("XMP-dc:Creator")
    keywords = requested_values(assignments, "Keywords", "Subject")
    if keywords:
        steps.append(XmpTextListPropertyWrite("XMP-dc:Subject", keywords))
        property_names.append("XMP-dc:Subject")
    headline = requested_value(assignments, "Headline")
    if headline is not None:
        steps.append(XmpTextPropertyWrite("XMP-photoshop:Headline", headline))
        property_names.append("XMP-photoshop:Headline")
    credit = requested_value(assignments, "Credit")
    if credit is not None:
        steps.append(XmpTextPropertyWrite("XMP-photoshop:Credit", credit))
        property_names.append("XMP-photoshop:Credit")
    source = requested_value(assignments, "Source")
    if source is not None:
        steps.append(XmpTextPropertyWrite("XMP-photoshop:Source", source))
        property_names.append("XMP-photoshop:Source")
    city = requested_value(assignments, "City")
    if city is not None:
        steps.append(XmpTextPropertyWrite("XMP-photoshop:City", city))
        property_names.append("XMP-photoshop:City")
    state = requested_value(assignments, "Province-State", "State")
    if state is not None:
        steps.append(XmpTextPropertyWrite("XMP-photoshop:State", state))
        property_names.append("XMP-photoshop:State")
    country = requested_value(assignments, "Country-PrimaryLocationName", "Country")
    if country is not None:
        steps.append(XmpTextPropertyWrite("XMP-photoshop:Country", country))
        property_names.append("XMP-photoshop:Country")
    copyright_notice = requested_value(assignments, "CopyrightNotice", "Rights")
    if copyright_notice is not None:
        steps.append(
            XmpLocalizedTextPropertyWrite(
                "XMP-dc:Rights",
                (XmpLocalizedTextValue("x-default", copyright_notice),),
            )
        )
        property_names.append("XMP-dc:Rights")
    category = requested_value(assignments, "Category")
    if category is not None:
        steps.append(XmpTextPropertyWrite("XMP-photoshop:Category", category))
        property_names.append("XMP-photoshop:Category")
    supplemental_categories = requested_values(assignments, "SupplementalCategories")
    if supplemental_categories:
        steps.append(
            XmpTextListPropertyWrite(
                "XMP-photoshop:SupplementalCategories",
                supplemental_categories,
            )
        )
        property_names.append("XMP-photoshop:SupplementalCategories")
    photoshop_date_created = requested_photoshop_xmp_date_created(assignments)
    if photoshop_date_created is not None:
        steps.append(XmpTextPropertyWrite("XMP-photoshop:DateCreated", photoshop_date_created))
        property_names.append("XMP-photoshop:DateCreated")
    description = requested_value(assignments, "Caption-Abstract", "Description")
    if description is not None:
        steps.append(
            XmpLocalizedTextPropertyWrite(
                "XMP-dc:Description",
                (XmpLocalizedTextValue("x-default", description),),
            )
        )
        property_names.append("XMP-dc:Description")
    return XmpPropertyWritePlan(
        steps=tuple(steps),
        evidence_ids=(),
        generated_specs=tuple(
            dict.fromkeys(xmp_property_spec(property_name) for property_name in property_names)
        ),
    )


def requested_photoshop_xmp_date_created(
    assignments: tuple[PhotoshopPSDRequestedAssignment, ...],
) -> str | None:
    direct_date_created = requested_value(assignments, "DateCreated", group="XMP-photoshop")
    if direct_date_created is not None:
        return direct_date_created
    date_created = requested_value(assignments, "DateCreated")
    if date_created is None:
        return None
    time_created = requested_value(assignments, "TimeCreated")
    if time_created is None:
        return date_created
    date_time = f"{date_created} {time_created}"
    if normalize_xmp_date_value(date_time) is None:
        return date_created
    return date_time


def requested_value(
    assignments: tuple[PhotoshopPSDRequestedAssignment, ...],
    tag_name: str,
    *tag_aliases: str,
    group: str | None = None,
) -> str | None:
    normalized_tags = {normalized_requested_tag(tag_name)} | {
        normalized_requested_tag(alias) for alias in tag_aliases
    }
    for assignment in assignments:
        if group is None and assignment.group is not None:
            continue
        if group is not None and assignment.group != group:
            continue
        if normalized_assignment_tag(assignment) in normalized_tags:
            return assignment.value
    return None


def requested_values(
    assignments: tuple[PhotoshopPSDRequestedAssignment, ...],
    tag_name: str,
    *tag_aliases: str,
    group: str | None = None,
) -> tuple[str, ...]:
    normalized_tags = {normalized_requested_tag(tag_name)} | {
        normalized_requested_tag(alias) for alias in tag_aliases
    }
    values: list[str] = []
    for assignment in assignments:
        if group is None and assignment.group is not None:
            continue
        if group is not None and assignment.group != group:
            continue
        if (
            normalized_assignment_tag(assignment) in normalized_tags
            and assignment.value is not None
        ):
            values.append(assignment.value)
    return tuple(values)


def normalized_assignment_tag(assignment: PhotoshopPSDRequestedAssignment) -> str:
    return normalized_requested_tag(assignment.tag)


def normalized_requested_tag(tag_name: str) -> str:
    return tag_name.casefold().replace("_", "-")


def blocks_for_resource(
    section_plan: PhotoshopPSDSectionBoundaryPlan,
    resource_id: int,
) -> tuple[PhotoshopImageResourceBlock, ...]:
    return tuple(
        block for block in section_plan.image_resource_blocks if block.resource_id == resource_id
    )
