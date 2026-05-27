"""Photoshop XMP image resource rewrite primitives.

ExifTool stores PSD XMP in Photoshop image resource ``0x0424`` and delegates
the nested packet write to the XMP writer before the Photoshop IRB section is
recomposed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from xml.etree import ElementTree

from exifmodern.formats.photoshop.image_resources import (
    PHOTOSHOP_WRITABLE_IRB_SIGNATURE,
    PhotoshopImageResourceBlock,
)
from exifmodern.formats.photoshop.nested_metadata_plan import (
    PHOTOSHOP_RESOURCE_ID_XMP,
    XMP_PSD_STANDARD_PATH_SOURCE_ID,
    XMP_WRITE_SOURCE_ID,
)
from exifmodern.formats.photoshop.resource_writer import (
    PhotoshopImageResourceMutation,
    PhotoshopPSDUnsupportedWriteError,
)
from exifmodern.formats.photoshop.section_boundary_plan import (
    plan_photoshop_psd_section_boundaries,
    rewrite_synthetic_photoshop_psd_image_resources,
)
from exifmodern.formats.photoshop.write_plan import (
    PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE_ID,
    WRITE_PHOTOSHOP_SOURCE_ID,
)
from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
from exifmodern.formats.xmp.packet import empty_xmp_packet
from exifmodern.formats.xmp.property_write import XmpPropertyWritePlan

type PhotoshopXMPRewriteBlockerCode = Literal[
    "not_source_backed",
    "empty_xmp_write_plan",
    "xmp_packet_malformed",
    "duplicate_xmp_resource",
    "non_8bim_xmp_resource",
]


@dataclass(frozen=True)
class PhotoshopXMPRewritePlan:
    source_length: int
    output_length: int
    source_backed: bool
    can_write_bytes: bool
    blocker_codes: tuple[PhotoshopXMPRewriteBlockerCode, ...]
    output_data: bytes | None
    changed_xmp_properties: int
    deleted_xmp_properties: int
    evidence_ids: tuple[str, ...]
    property_plan: XmpPropertyWritePlan | None

    @property
    def changed(self) -> bool:
        return self.changed_xmp_properties > 0 or self.deleted_xmp_properties > 0


def plan_xmp_resource_rewrite(
    payload: bytes | None,
    xmp_plan: XmpPropertyWritePlan,
    *,
    source_backed: bool = True,
) -> PhotoshopXMPRewritePlan:
    source_payload = empty_xmp_packet() if payload is None else payload
    blockers: list[PhotoshopXMPRewriteBlockerCode] = []
    if not source_backed:
        blockers.append("not_source_backed")
    if not xmp_plan.steps:
        blockers.append("empty_xmp_write_plan")
    if blockers:
        return blocked_xmp_plan(source_payload, source_backed, blockers)

    try:
        mutation_result = apply_xmp_property_write_plan(source_payload, xmp_plan)
    except ElementTree.ParseError:
        return blocked_xmp_plan(source_payload, source_backed, ["xmp_packet_malformed"])

    return PhotoshopXMPRewritePlan(
        source_length=len(source_payload),
        output_length=len(mutation_result.packet),
        source_backed=source_backed,
        can_write_bytes=True,
        blocker_codes=(),
        output_data=mutation_result.packet,
        changed_xmp_properties=mutation_result.changed_properties,
        deleted_xmp_properties=mutation_result.deleted_properties,
        evidence_ids=xmp_resource_anchor_ids(),
        property_plan=xmp_plan,
    )


def xmp_resource_mutation(
    payload: bytes | None,
    xmp_plan: XmpPropertyWritePlan,
    *,
    resource_name: bytes | None = None,
    resource_present: bool = True,
    source_backed: bool = True,
) -> PhotoshopImageResourceMutation:
    rewrite_plan = plan_xmp_resource_rewrite(
        payload,
        xmp_plan,
        source_backed=source_backed,
    )
    if not rewrite_plan.can_write_bytes or rewrite_plan.output_data is None:
        raise PhotoshopPSDUnsupportedWriteError(
            "Photoshop XMP resource rewrite is blocked: " + ", ".join(rewrite_plan.blocker_codes)
        )
    action: Literal["replace", "insert"] = "replace" if resource_present else "insert"
    return PhotoshopImageResourceMutation(
        action,
        PHOTOSHOP_RESOURCE_ID_XMP,
        rewrite_plan.output_data,
        resource_name,
    )


def rewrite_synthetic_photoshop_psd_xmp(
    psd_data: bytes,
    xmp_plan: XmpPropertyWritePlan,
    *,
    source_backed: bool = True,
) -> bytes:
    section_plan = plan_photoshop_psd_section_boundaries(
        psd_data,
        source_backed=source_backed,
        synthetic_psd=True,
    )
    xmp_blocks = tuple(
        block
        for block in section_plan.image_resource_blocks
        if block.resource_id == PHOTOSHOP_RESOURCE_ID_XMP
    )
    blocker_codes = xmp_resource_blockers(xmp_blocks, source_backed=source_backed)
    if blocker_codes:
        raise PhotoshopPSDUnsupportedWriteError(
            "Photoshop synthetic PSD XMP rewrite is blocked: " + ", ".join(blocker_codes)
        )

    xmp_block = xmp_blocks[0] if xmp_blocks else None
    mutation = xmp_resource_mutation(
        None if xmp_block is None else xmp_block.data,
        xmp_plan,
        resource_name=None if xmp_block is None else xmp_block.name,
        resource_present=xmp_block is not None,
        source_backed=source_backed,
    )
    return rewrite_synthetic_photoshop_psd_image_resources(
        psd_data,
        (mutation,),
        source_backed=source_backed,
    )


def xmp_resource_blockers(
    xmp_blocks: tuple[PhotoshopImageResourceBlock, ...],
    *,
    source_backed: bool,
) -> tuple[PhotoshopXMPRewriteBlockerCode, ...]:
    blockers: list[PhotoshopXMPRewriteBlockerCode] = []
    if not source_backed:
        blockers.append("not_source_backed")
    if len(xmp_blocks) > 1:
        blockers.append("duplicate_xmp_resource")
    if any(block.signature != PHOTOSHOP_WRITABLE_IRB_SIGNATURE for block in xmp_blocks):
        blockers.append("non_8bim_xmp_resource")
    return tuple(dict.fromkeys(blockers))


def blocked_xmp_plan(
    payload: bytes,
    source_backed: bool,
    blocker_codes: list[PhotoshopXMPRewriteBlockerCode],
) -> PhotoshopXMPRewritePlan:
    return PhotoshopXMPRewritePlan(
        source_length=len(payload),
        output_length=len(payload),
        source_backed=source_backed,
        can_write_bytes=False,
        blocker_codes=tuple(dict.fromkeys(blocker_codes)),
        output_data=None,
        changed_xmp_properties=0,
        deleted_xmp_properties=0,
        evidence_ids=xmp_resource_anchor_ids(),
        property_plan=None,
    )


def xmp_resource_anchor_ids() -> tuple[str, ...]:
    return (
        PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE_ID,
        XMP_PSD_STANDARD_PATH_SOURCE_ID,
        XMP_WRITE_SOURCE_ID,
        WRITE_PHOTOSHOP_SOURCE_ID,
    )
