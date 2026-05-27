"""Source-backed Photoshop nested metadata routing plans.

ExifTool routes PSD writes through the Photoshop image resource directory and
delegates nested payloads to IPTC, XMP, TIFF/EXIF, or Photoshop-specific binary
writers.  This module records that routing only; it does not enable PSD byte
mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.photoshop.image_resources import (
    PHOTOSHOP_WRITABLE_IRB_SIGNATURE,
    PhotoshopImageResourceBlock,
    parse_image_resource_blocks,
)
from exifmodern.formats.photoshop.resource_writer import (
    PhotoshopImageResourceReplacementBlockerCode,
    image_resource_replacement_blockers,
)
from exifmodern.formats.photoshop.write_plan import (
    EXIF_ARTIST_SOURCE_ID,
    EXIF_RESOLUTION_SOURCE_ID,
    IPTC_BY_LINE_SOURCE_ID,
    IPTC_CAPTION_ABSTRACT_SOURCE_ID,
    IPTC_HEADLINE_SOURCE_ID,
    IPTC_KEYWORDS_SOURCE_ID,
    PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE_ID,
    PHOTOSHOP_MAIN_RESOURCE_SOURCE_ID,
    PHOTOSHOP_PSD_MAP_SOURCE_ID,
    PHOTOSHOP_PSD_WRITE_SOURCE_ID,
    PHOTOSHOP_RESOLUTION_SOURCE_ID,
    WRITE_PHOTOSHOP_SOURCE_ID,
    XMP_DC_SOURCE_ID,
    XMP_PHOTOSHOP_HEADLINE_SOURCE_ID,
    XMP_TIFF_RESOLUTION_SOURCE_ID,
    PhotoshopEvidenceCompat,
)

type PhotoshopNestedMetadataPayloadKind = Literal[
    "photoshop_resolution_info",
    "iptc_dataset_stream",
    "xmp_packet",
    "embedded_tiff_exif",
    "iptc_digest",
    "photomechanic_trailer",
]
type PhotoshopNestedMetadataResponsibility = Literal[
    "rewrite_resolution_info_resource",
    "rewrite_iptc_resource",
    "rewrite_xmp_resource",
    "rewrite_embedded_exif_resource",
    "reconcile_iptc_digest_resource",
    "rewrite_photomechanic_trailer",
]
type PhotoshopNestedMetadataSurface = Literal[
    "psd_image_resource_section_length",
    "photoshop_irb_0x03ed_resolution_info",
    "photoshop_irb_0x0404_iptc_data",
    "photoshop_irb_0x0422_exif_info_tiff",
    "photoshop_irb_0x0424_xmp_packet",
    "photoshop_irb_0x0425_iptc_digest",
    "iptc_application_record_by_line",
    "iptc_application_record_keywords",
    "iptc_application_record_headline",
    "iptc_application_record_caption_abstract",
    "xmp_dc_creator_sequence",
    "xmp_dc_subject_bag",
    "xmp_dc_description_lang_alt",
    "xmp_photoshop_headline",
    "xmp_tiff_x_resolution",
    "xmp_tiff_y_resolution",
    "exif_ifd0_x_resolution",
    "exif_ifd0_y_resolution",
    "exif_ifd0_artist",
    "photomechanic_tagged_trailer",
]
type PhotoshopNestedMetadataBlockerCode = Literal[
    "requires_psd_image_resource_section_rebuild",
    "requires_photoshop_irb_entry_size_and_padding_rewrite",
    "requires_nested_resolution_binary_data_rewrite",
    "requires_iptc_dataset_rewrite_and_digest_reconciliation",
    "requires_xmp_packet_rewrite_in_photoshop_resource",
    "requires_embedded_tiff_exif_writer_in_psd_resource",
    "requires_photomechanic_trailer_writer",
    "real_psd_mutation_not_enabled",
]

PHOTOSHOP_RESOURCE_ID_RESOLUTION_INFO = 0x03ED
PHOTOSHOP_RESOURCE_ID_IPTC_DATA = 0x0404
PHOTOSHOP_RESOURCE_ID_ICC_PROFILE = 0x040F
PHOTOSHOP_RESOURCE_ID_EXIF_INFO = 0x0422
PHOTOSHOP_RESOURCE_ID_XMP = 0x0424
PHOTOSHOP_RESOURCE_ID_IPTC_DIGEST = 0x0425

PHOTOSHOP_IPTC_RESOURCE_SOURCE_ID = "photoshop.nested_metadata.iptc_resource"
PHOTOSHOP_IPTC_DIGEST_RESOURCE_SOURCE_ID = "photoshop.nested_metadata.iptc_digest_resource"
IPTC_WRITE_DIGEST_SOURCE_ID = "photoshop.nested_metadata.iptc_write_digest"
XMP_PSD_STANDARD_PATH_SOURCE_ID = "photoshop.nested_metadata.xmp_psd_standard_path"
XMP_WRITE_SOURCE_ID = "photoshop.nested_metadata.xmp_write"
EXIF_WRITE_SOURCE_ID = "photoshop.nested_metadata.exif_write"
PHOTOSHOP_PSD_TRAILER_WRITE_SOURCE_ID = "photoshop.nested_metadata.psd_trailer_write"
PHOTOMECHANIC_TRAILER_SOURCE_ID = "photoshop.nested_metadata.photomechanic_trailer"


@dataclass(frozen=True)
class PhotoshopImageResourceState:
    resource_id: int
    block_count: int
    signatures: tuple[bytes, ...]
    data_sizes: tuple[int, ...]

    @property
    def resource_id_hex(self) -> str:
        return f"0x{self.resource_id:04x}"

    @property
    def present(self) -> bool:
        return self.block_count > 0

    @property
    def writable_8bim_only(self) -> bool:
        return bool(self.signatures) and all(
            signature == PHOTOSHOP_WRITABLE_IRB_SIGNATURE for signature in self.signatures
        )


@dataclass(frozen=True)
class PhotoshopNestedMetadataRoute(PhotoshopEvidenceCompat):
    responsibility: PhotoshopNestedMetadataResponsibility
    payload_kind: PhotoshopNestedMetadataPayloadKind
    resource_id: int | None
    resource_name: str
    target_surfaces: tuple[PhotoshopNestedMetadataSurface, ...]
    blocker_codes: tuple[PhotoshopNestedMetadataBlockerCode, ...]
    resource_state: PhotoshopImageResourceState | None
    replacement_probe_blocker_codes: tuple[PhotoshopImageResourceReplacementBlockerCode, ...]
    source_reference_ids: tuple[str, ...]

    @property
    def resource_id_hex(self) -> str | None:
        if self.resource_id is None:
            return None
        return f"0x{self.resource_id:04x}"

    @property
    def can_mutate_real_psd(self) -> bool:
        return False


@dataclass(frozen=True)
class PhotoshopNestedMetadataRoutingPlan(PhotoshopEvidenceCompat):
    source_length: int | None
    routes: tuple[PhotoshopNestedMetadataRoute, ...]
    source_reference_ids: tuple[str, ...]

    @property
    def can_mutate_real_psd(self) -> bool:
        return False

    @property
    def resource_ids(self) -> tuple[int, ...]:
        return tuple(route.resource_id for route in self.routes if route.resource_id is not None)

    @property
    def blocker_codes(self) -> tuple[PhotoshopNestedMetadataBlockerCode, ...]:
        return tuple(
            dict.fromkeys(blocker for route in self.routes for blocker in route.blocker_codes)
        )

    def route_for_resource_id(self, resource_id: int) -> PhotoshopNestedMetadataRoute:
        for route in self.routes:
            if route.resource_id == resource_id:
                return route
        raise KeyError(
            f"Photoshop nested metadata route not found for resource {resource_id:#06x}."
        )

    def route_for_responsibility(
        self,
        responsibility: PhotoshopNestedMetadataResponsibility,
    ) -> PhotoshopNestedMetadataRoute:
        for route in self.routes:
            if route.responsibility == responsibility:
                return route
        raise KeyError(f"Photoshop nested metadata responsibility not found: {responsibility}.")


def plan_photoshop_nested_metadata_routes(
    resource_section: bytes | None = None,
    *,
    source_backed: bool = True,
    synthetic_resource_section: bool = False,
    include_photomechanic_trailer: bool = True,
) -> PhotoshopNestedMetadataRoutingPlan:
    blocks = parse_image_resource_blocks(resource_section) if resource_section is not None else ()
    probe_replacements = resource_section is not None
    routes = tuple(
        route
        for route in (
            resolution_info_route(
                blocks,
                source_backed,
                synthetic_resource_section,
                probe_replacements,
            ),
            iptc_route(blocks, source_backed, synthetic_resource_section, probe_replacements),
            embedded_exif_route(
                blocks,
                source_backed,
                synthetic_resource_section,
                probe_replacements,
            ),
            xmp_route(blocks, source_backed, synthetic_resource_section, probe_replacements),
            iptc_digest_route(
                blocks,
                source_backed,
                synthetic_resource_section,
                probe_replacements,
            ),
            photomechanic_trailer_route() if include_photomechanic_trailer else None,
        )
        if route is not None
    )
    return PhotoshopNestedMetadataRoutingPlan(
        source_length=None if resource_section is None else len(resource_section),
        routes=routes,
        source_reference_ids=tuple(
            dict.fromkeys(reference for route in routes for reference in route.source_reference_ids)
        ),
    )


def resolution_info_route(
    blocks: tuple[PhotoshopImageResourceBlock, ...],
    source_backed: bool,
    synthetic_resource_section: bool,
    probe_replacements: bool,
) -> PhotoshopNestedMetadataRoute:
    resource_id = PHOTOSHOP_RESOURCE_ID_RESOLUTION_INFO
    return PhotoshopNestedMetadataRoute(
        responsibility="rewrite_resolution_info_resource",
        payload_kind="photoshop_resolution_info",
        resource_id=resource_id,
        resource_name="ResolutionInfo",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x03ed_resolution_info",
            "exif_ifd0_x_resolution",
            "exif_ifd0_y_resolution",
            "xmp_tiff_x_resolution",
            "xmp_tiff_y_resolution",
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_nested_resolution_binary_data_rewrite",
            "requires_embedded_tiff_exif_writer_in_psd_resource",
            "real_psd_mutation_not_enabled",
        ),
        resource_state=resource_state(blocks, resource_id),
        replacement_probe_blocker_codes=replacement_probe_blockers(
            blocks,
            resource_id,
            source_backed,
            synthetic_resource_section,
            probe_replacements,
        ),
        source_reference_ids=(
            PHOTOSHOP_PSD_MAP_SOURCE_ID,
            PHOTOSHOP_MAIN_RESOURCE_SOURCE_ID,
            PHOTOSHOP_RESOLUTION_SOURCE_ID,
            PHOTOSHOP_PSD_WRITE_SOURCE_ID,
            WRITE_PHOTOSHOP_SOURCE_ID,
            EXIF_RESOLUTION_SOURCE_ID,
            XMP_TIFF_RESOLUTION_SOURCE_ID,
        ),
    )


def iptc_route(
    blocks: tuple[PhotoshopImageResourceBlock, ...],
    source_backed: bool,
    synthetic_resource_section: bool,
    probe_replacements: bool,
) -> PhotoshopNestedMetadataRoute:
    resource_id = PHOTOSHOP_RESOURCE_ID_IPTC_DATA
    return PhotoshopNestedMetadataRoute(
        responsibility="rewrite_iptc_resource",
        payload_kind="iptc_dataset_stream",
        resource_id=resource_id,
        resource_name="IPTCData",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x0404_iptc_data",
            "iptc_application_record_by_line",
            "iptc_application_record_keywords",
            "iptc_application_record_headline",
            "iptc_application_record_caption_abstract",
            "photoshop_irb_0x0425_iptc_digest",
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_iptc_dataset_rewrite_and_digest_reconciliation",
            "real_psd_mutation_not_enabled",
        ),
        resource_state=resource_state(blocks, resource_id),
        replacement_probe_blocker_codes=replacement_probe_blockers(
            blocks,
            resource_id,
            source_backed,
            synthetic_resource_section,
            probe_replacements,
        ),
        source_reference_ids=(
            PHOTOSHOP_PSD_MAP_SOURCE_ID,
            PHOTOSHOP_IPTC_RESOURCE_SOURCE_ID,
            PHOTOSHOP_IPTC_DIGEST_RESOURCE_SOURCE_ID,
            PHOTOSHOP_PSD_WRITE_SOURCE_ID,
            WRITE_PHOTOSHOP_SOURCE_ID,
            IPTC_WRITE_DIGEST_SOURCE_ID,
            IPTC_BY_LINE_SOURCE_ID,
            IPTC_KEYWORDS_SOURCE_ID,
            IPTC_HEADLINE_SOURCE_ID,
            IPTC_CAPTION_ABSTRACT_SOURCE_ID,
        ),
    )


def xmp_route(
    blocks: tuple[PhotoshopImageResourceBlock, ...],
    source_backed: bool,
    synthetic_resource_section: bool,
    probe_replacements: bool,
) -> PhotoshopNestedMetadataRoute:
    resource_id = PHOTOSHOP_RESOURCE_ID_XMP
    return PhotoshopNestedMetadataRoute(
        responsibility="rewrite_xmp_resource",
        payload_kind="xmp_packet",
        resource_id=resource_id,
        resource_name="XMP",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x0424_xmp_packet",
            "xmp_dc_creator_sequence",
            "xmp_dc_subject_bag",
            "xmp_dc_description_lang_alt",
            "xmp_photoshop_headline",
            "xmp_tiff_x_resolution",
            "xmp_tiff_y_resolution",
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_xmp_packet_rewrite_in_photoshop_resource",
            "real_psd_mutation_not_enabled",
        ),
        resource_state=resource_state(blocks, resource_id),
        replacement_probe_blocker_codes=replacement_probe_blockers(
            blocks,
            resource_id,
            source_backed,
            synthetic_resource_section,
            probe_replacements,
        ),
        source_reference_ids=(
            PHOTOSHOP_PSD_MAP_SOURCE_ID,
            PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE_ID,
            XMP_PSD_STANDARD_PATH_SOURCE_ID,
            PHOTOSHOP_PSD_WRITE_SOURCE_ID,
            WRITE_PHOTOSHOP_SOURCE_ID,
            XMP_WRITE_SOURCE_ID,
            XMP_DC_SOURCE_ID,
            XMP_PHOTOSHOP_HEADLINE_SOURCE_ID,
            XMP_TIFF_RESOLUTION_SOURCE_ID,
        ),
    )


def embedded_exif_route(
    blocks: tuple[PhotoshopImageResourceBlock, ...],
    source_backed: bool,
    synthetic_resource_section: bool,
    probe_replacements: bool,
) -> PhotoshopNestedMetadataRoute:
    resource_id = PHOTOSHOP_RESOURCE_ID_EXIF_INFO
    return PhotoshopNestedMetadataRoute(
        responsibility="rewrite_embedded_exif_resource",
        payload_kind="embedded_tiff_exif",
        resource_id=resource_id,
        resource_name="EXIFInfo",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x0422_exif_info_tiff",
            "exif_ifd0_x_resolution",
            "exif_ifd0_y_resolution",
            "exif_ifd0_artist",
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_embedded_tiff_exif_writer_in_psd_resource",
            "real_psd_mutation_not_enabled",
        ),
        resource_state=resource_state(blocks, resource_id),
        replacement_probe_blocker_codes=replacement_probe_blockers(
            blocks,
            resource_id,
            source_backed,
            synthetic_resource_section,
            probe_replacements,
        ),
        source_reference_ids=(
            PHOTOSHOP_PSD_MAP_SOURCE_ID,
            PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE_ID,
            PHOTOSHOP_PSD_WRITE_SOURCE_ID,
            WRITE_PHOTOSHOP_SOURCE_ID,
            EXIF_WRITE_SOURCE_ID,
            EXIF_RESOLUTION_SOURCE_ID,
            EXIF_ARTIST_SOURCE_ID,
        ),
    )


def iptc_digest_route(
    blocks: tuple[PhotoshopImageResourceBlock, ...],
    source_backed: bool,
    synthetic_resource_section: bool,
    probe_replacements: bool,
) -> PhotoshopNestedMetadataRoute:
    resource_id = PHOTOSHOP_RESOURCE_ID_IPTC_DIGEST
    return PhotoshopNestedMetadataRoute(
        responsibility="reconcile_iptc_digest_resource",
        payload_kind="iptc_digest",
        resource_id=resource_id,
        resource_name="IPTCDigest",
        target_surfaces=(
            "psd_image_resource_section_length",
            "photoshop_irb_0x0425_iptc_digest",
            "photoshop_irb_0x0404_iptc_data",
        ),
        blocker_codes=(
            "requires_psd_image_resource_section_rebuild",
            "requires_photoshop_irb_entry_size_and_padding_rewrite",
            "requires_iptc_dataset_rewrite_and_digest_reconciliation",
            "real_psd_mutation_not_enabled",
        ),
        resource_state=resource_state(blocks, resource_id),
        replacement_probe_blocker_codes=replacement_probe_blockers(
            blocks,
            resource_id,
            source_backed,
            synthetic_resource_section,
            probe_replacements,
        ),
        source_reference_ids=(
            PHOTOSHOP_IPTC_DIGEST_RESOURCE_SOURCE_ID,
            PHOTOSHOP_PSD_WRITE_SOURCE_ID,
            WRITE_PHOTOSHOP_SOURCE_ID,
            IPTC_WRITE_DIGEST_SOURCE_ID,
        ),
    )


def photomechanic_trailer_route() -> PhotoshopNestedMetadataRoute:
    return PhotoshopNestedMetadataRoute(
        responsibility="rewrite_photomechanic_trailer",
        payload_kind="photomechanic_trailer",
        resource_id=None,
        resource_name="PhotoMechanic",
        target_surfaces=("photomechanic_tagged_trailer",),
        blocker_codes=(
            "requires_photomechanic_trailer_writer",
            "real_psd_mutation_not_enabled",
        ),
        resource_state=None,
        replacement_probe_blocker_codes=(),
        source_reference_ids=(
            PHOTOSHOP_PSD_TRAILER_WRITE_SOURCE_ID,
            PHOTOMECHANIC_TRAILER_SOURCE_ID,
        ),
    )


def resource_state(
    blocks: tuple[PhotoshopImageResourceBlock, ...],
    resource_id: int,
) -> PhotoshopImageResourceState:
    matches = tuple(block for block in blocks if block.resource_id == resource_id)
    return PhotoshopImageResourceState(
        resource_id=resource_id,
        block_count=len(matches),
        signatures=tuple(block.signature for block in matches),
        data_sizes=tuple(block.data_size for block in matches),
    )


def replacement_probe_blockers(
    blocks: tuple[PhotoshopImageResourceBlock, ...],
    resource_id: int,
    source_backed: bool,
    synthetic_resource_section: bool,
    probe_replacements: bool,
) -> tuple[PhotoshopImageResourceReplacementBlockerCode, ...]:
    if not probe_replacements:
        return ()
    return image_resource_replacement_blockers(
        blocks=tuple((block.resource_id, block.signature) for block in blocks),
        replacement_ids=(resource_id,),
        duplicate_replacement_ids=(),
        source_backed=source_backed,
        resource_mutation_enabled=synthetic_resource_section,
    )
