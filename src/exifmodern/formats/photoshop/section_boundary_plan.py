"""Source-backed Photoshop PSD section boundary planning.

ExifTool's PSD write path rewrites only the image resource section and copies
the remaining PSD bytes, with optional trailer processing.  This module parses
those section boundaries and computes replacement sizes without enabling real
PSD mutation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.photoshop.image_resources import (
    PhotoshopImageResourceBlock,
    encode_image_resource_section,
    parse_image_resource_blocks,
)
from exifmodern.formats.photoshop.nested_metadata_plan import (
    PHOTOMECHANIC_TRAILER_SOURCE_ID,
    PHOTOSHOP_PSD_TRAILER_WRITE_SOURCE_ID,
    PhotoshopNestedMetadataRoutingPlan,
    plan_photoshop_nested_metadata_routes,
)
from exifmodern.formats.photoshop.resource_writer import (
    PhotoshopImageResourceMutation,
    PhotoshopImageResourceMutationPlan,
    PhotoshopImageResourceReplacement,
    PhotoshopImageResourceReplacementPlan,
    PhotoshopPSDUnsupportedWriteError,
    encode_image_resource_section_length,
    plan_image_resource_entry_mutations,
    plan_image_resource_entry_replacements,
)
from exifmodern.formats.photoshop.write_plan import (
    PHOTOSHOP_PSD_WRITE_SOURCE_ID,
    WRITE_PHOTOSHOP_SOURCE_ID,
    PhotoshopEvidenceCompat,
)

type PhotoshopPSDSectionKind = Literal[
    "header",
    "color_mode_data",
    "image_resources",
    "layer_and_mask_info",
    "image_data",
    "photomechanic_trailer",
]
type PhotoshopPSDLengthFieldName = Literal[
    "color_mode_data_length",
    "image_resource_section_length",
    "layer_and_mask_info_length",
]
type PhotoshopPSDSizeGateName = Literal[
    "output_color_mode_data_length",
    "output_image_resource_section_length",
    "output_layer_and_mask_info_length",
]
type PhotoshopPSDSectionBoundaryBlockerCode = Literal[
    "real_psd_mutation_not_enabled",
    "image_resource_replacement_blocked",
    "image_resource_mutation_blocked",
    "output_color_mode_data_too_large",
    "output_image_resource_section_too_large",
    "output_layer_and_mask_info_too_large",
]

PSD_SIGNATURE = b"8BPS"
PSD_HEADER_LENGTH = 26
PSD_LENGTH_FIELD_SIZE = 4
PSD_UINT32_MAX = 0xFFFFFFFF
PHOTOMECHANIC_TRAILER_FOOTER_SIGNATURE = b"cbipcbbl"
PHOTOMECHANIC_TRAILER_FOOTER_LENGTH = 12

PHOTOSHOP_PSD_HEADER_SOURCE_ID = "photoshop.section_boundary.psd_header"
PHOTOSHOP_PSD_PROCESS_BOUNDARY_SOURCE_ID = "photoshop.section_boundary.process_psd"
PHOTOSHOP_PSD_LAYER_MASK_SOURCE_ID = "photoshop.section_boundary.layer_mask"
PHOTOSHOP_PSD_IMAGE_DATA_SOURCE_ID = "photoshop.section_boundary.image_data"
PHOTOSHOP_PHOTOMECHANIC_TRAILER_BOUNDARY_SOURCE_ID = (
    "photoshop.section_boundary.photomechanic_trailer"
)


def _photoshop_section_source_reference(source_id: str) -> str:
    return source_id


PHOTOSHOP_PSD_HEADER_SOURCE = _photoshop_section_source_reference(PHOTOSHOP_PSD_HEADER_SOURCE_ID)
PHOTOSHOP_PSD_PROCESS_BOUNDARY_SOURCE = _photoshop_section_source_reference(
    PHOTOSHOP_PSD_PROCESS_BOUNDARY_SOURCE_ID
)
PHOTOSHOP_PSD_LAYER_MASK_SOURCE = _photoshop_section_source_reference(
    PHOTOSHOP_PSD_LAYER_MASK_SOURCE_ID
)
PHOTOSHOP_PSD_IMAGE_DATA_SOURCE = _photoshop_section_source_reference(
    PHOTOSHOP_PSD_IMAGE_DATA_SOURCE_ID
)
PHOTOSHOP_PHOTOMECHANIC_TRAILER_BOUNDARY_SOURCE = _photoshop_section_source_reference(
    PHOTOSHOP_PHOTOMECHANIC_TRAILER_BOUNDARY_SOURCE_ID
)


class PhotoshopPSDSectionBoundaryError(ValueError):
    """Raised when a PSD file boundary cannot be planned safely."""


@dataclass(frozen=True)
class PhotoshopPSDHeader:
    signature: bytes
    version: int
    channels: int
    height: int
    width: int
    bit_depth: int
    color_mode: int

    @property
    def file_type(self) -> str:
        return "PSD" if self.version == 1 else "PSB"


@dataclass(frozen=True)
class PhotoshopPSDSectionBoundary:
    kind: PhotoshopPSDSectionKind
    total_start: int
    total_end: int
    data_start: int
    data_end: int
    length_field_name: PhotoshopPSDLengthFieldName | None = None
    length_field_start: int | None = None
    length_field_size: int = 0
    compression: int | None = None

    @property
    def total_length(self) -> int:
        return self.total_end - self.total_start

    @property
    def payload_length(self) -> int:
        return self.data_end - self.data_start

    @property
    def preserves_source_bytes(self) -> bool:
        return True


@dataclass(frozen=True)
class PhotoshopPSDOutputSectionSizeGate:
    name: PhotoshopPSDSizeGateName
    value: int
    maximum: int
    fits: bool
    blocker_code: PhotoshopPSDSectionBoundaryBlockerCode | None
    source_reference_id: str


@dataclass(frozen=True)
class PhotoshopPSDSectionBoundaryPlan(PhotoshopEvidenceCompat):
    source_length: int
    header: PhotoshopPSDHeader
    header_section: PhotoshopPSDSectionBoundary
    color_mode_data_section: PhotoshopPSDSectionBoundary
    image_resource_section: PhotoshopPSDSectionBoundary
    layer_and_mask_info_section: PhotoshopPSDSectionBoundary
    image_data_section: PhotoshopPSDSectionBoundary
    trailer_section: PhotoshopPSDSectionBoundary | None
    image_resource_section_payload: bytes
    image_resource_blocks: tuple[PhotoshopImageResourceBlock, ...]
    nested_metadata_plan: PhotoshopNestedMetadataRoutingPlan
    image_resource_replacement_plan: PhotoshopImageResourceReplacementPlan | None
    image_resource_mutation_plan: PhotoshopImageResourceMutationPlan | None
    output_section_size_gates: tuple[PhotoshopPSDOutputSectionSizeGate, ...]
    real_psd_rewrite_enabled: bool
    source_reference_ids: tuple[str, ...]

    @property
    def output_image_resource_section_length(self) -> int:
        if self.image_resource_replacement_plan is None:
            if self.image_resource_mutation_plan is None:
                return self.image_resource_section.payload_length
            return self.image_resource_mutation_plan.output_length
        if self.image_resource_mutation_plan is not None:
            raise PhotoshopPSDSectionBoundaryError(
                "Photoshop PSD section plan cannot carry both replacement and mutation plans."
            )
        return self.image_resource_replacement_plan.output_length

    @property
    def output_image_resource_section_length_field(self) -> bytes:
        return encode_image_resource_section_length(self.output_image_resource_section_length)

    @property
    def can_rewrite_synthetic_psd(self) -> bool:
        if self.can_rewrite_real_psd:
            return True
        if any(not gate.fits for gate in self.output_section_size_gates):
            return False
        if self.image_resource_replacement_plan is not None:
            return self.image_resource_replacement_plan.can_write_bytes
        if self.image_resource_mutation_plan is not None:
            return self.image_resource_mutation_plan.can_write_bytes
        return False

    @property
    def output_image_resource_section_payload(self) -> bytes:
        if self.image_resource_replacement_plan is None:
            if self.image_resource_mutation_plan is None:
                return self.image_resource_section_payload
            return encode_image_resource_section(self.image_resource_mutation_plan.entries)
        if self.image_resource_mutation_plan is not None:
            raise PhotoshopPSDSectionBoundaryError(
                "Photoshop PSD section plan cannot carry both replacement and mutation plans."
            )
        return encode_image_resource_section(self.image_resource_replacement_plan.entries)

    @property
    def has_image_resource_write_plan(self) -> bool:
        return (
            self.image_resource_replacement_plan is not None
            or self.image_resource_mutation_plan is not None
        )

    @property
    def planned_output_file_length(self) -> int:
        return (
            self.source_length
            - self.image_resource_section.payload_length
            + self.output_image_resource_section_length
        )

    @property
    def can_rewrite_real_psd(self) -> bool:
        if not self.real_psd_rewrite_enabled:
            return False
        if any(not gate.fits for gate in self.output_section_size_gates):
            return False
        if self.image_resource_replacement_plan is not None:
            return self.image_resource_replacement_plan.can_write_bytes
        if self.image_resource_mutation_plan is not None:
            return self.image_resource_mutation_plan.can_write_bytes
        return False

    @property
    def blocker_codes(self) -> tuple[PhotoshopPSDSectionBoundaryBlockerCode, ...]:
        blockers: list[PhotoshopPSDSectionBoundaryBlockerCode] = []
        if not self.can_rewrite_real_psd:
            blockers.append("real_psd_mutation_not_enabled")
        if (
            self.image_resource_replacement_plan is not None
            and self.image_resource_replacement_plan.blocker_codes
        ):
            blockers.append("image_resource_replacement_blocked")
        if (
            self.image_resource_mutation_plan is not None
            and self.image_resource_mutation_plan.blocker_codes
        ):
            blockers.append("image_resource_mutation_blocked")
        blockers.extend(
            gate.blocker_code
            for gate in self.output_section_size_gates
            if gate.blocker_code is not None
        )
        return tuple(dict.fromkeys(blockers))


def plan_photoshop_psd_section_boundaries(
    psd_data: bytes,
    replacements: Sequence[PhotoshopImageResourceReplacement] = (),
    mutations: Sequence[PhotoshopImageResourceMutation] = (),
    *,
    source_backed: bool = True,
    synthetic_psd: bool = False,
    enable_real_psd_rewrite: bool = False,
) -> PhotoshopPSDSectionBoundaryPlan:
    if replacements and mutations:
        raise PhotoshopPSDSectionBoundaryError(
            "Photoshop PSD section planning accepts replacements or mutations, not both."
        )

    header = parse_photoshop_psd_header(psd_data)
    header_section = PhotoshopPSDSectionBoundary(
        kind="header",
        total_start=0,
        total_end=PSD_HEADER_LENGTH,
        data_start=0,
        data_end=PSD_HEADER_LENGTH,
    )

    color_length = read_psd_u32(psd_data, PSD_HEADER_LENGTH, "color mode data")
    color_total_start = PSD_HEADER_LENGTH
    color_data_start = color_total_start + PSD_LENGTH_FIELD_SIZE
    color_data_end = checked_section_end(
        psd_data,
        color_data_start,
        color_length,
        "color mode data",
    )
    color_section = PhotoshopPSDSectionBoundary(
        kind="color_mode_data",
        total_start=color_total_start,
        total_end=color_data_end,
        data_start=color_data_start,
        data_end=color_data_end,
        length_field_name="color_mode_data_length",
        length_field_start=color_total_start,
        length_field_size=PSD_LENGTH_FIELD_SIZE,
    )

    resource_length_field_start = color_data_end
    resource_length = read_psd_u32(psd_data, resource_length_field_start, "image resource section")
    resource_data_start = resource_length_field_start + PSD_LENGTH_FIELD_SIZE
    resource_data_end = checked_section_end(
        psd_data,
        resource_data_start,
        resource_length,
        "image resource section",
    )
    resource_section = PhotoshopPSDSectionBoundary(
        kind="image_resources",
        total_start=resource_length_field_start,
        total_end=resource_data_end,
        data_start=resource_data_start,
        data_end=resource_data_end,
        length_field_name="image_resource_section_length",
        length_field_start=resource_length_field_start,
        length_field_size=PSD_LENGTH_FIELD_SIZE,
    )
    resource_payload = psd_data[resource_data_start:resource_data_end]
    image_resource_blocks = parse_image_resource_blocks(resource_payload)

    layer_length_field_start = resource_data_end
    layer_length = read_psd_u32(psd_data, layer_length_field_start, "layer and mask information")
    layer_data_start = layer_length_field_start + PSD_LENGTH_FIELD_SIZE
    layer_data_end = checked_section_end(
        psd_data,
        layer_data_start,
        layer_length,
        "layer and mask information",
    )
    layer_section = PhotoshopPSDSectionBoundary(
        kind="layer_and_mask_info",
        total_start=layer_length_field_start,
        total_end=layer_data_end,
        data_start=layer_data_start,
        data_end=layer_data_end,
        length_field_name="layer_and_mask_info_length",
        length_field_start=layer_length_field_start,
        length_field_size=PSD_LENGTH_FIELD_SIZE,
    )

    image_data_start = layer_data_end
    trailer_section = detect_photomechanic_trailer(psd_data, minimum_start=image_data_start)
    image_data_end = trailer_section.total_start if trailer_section is not None else len(psd_data)
    if image_data_end - image_data_start < 2:
        raise PhotoshopPSDSectionBoundaryError(
            "Truncated Photoshop PSD image data section: missing compression field."
        )
    image_data_section = PhotoshopPSDSectionBoundary(
        kind="image_data",
        total_start=image_data_start,
        total_end=image_data_end,
        data_start=image_data_start,
        data_end=image_data_end,
        compression=int.from_bytes(psd_data[image_data_start : image_data_start + 2], "big"),
    )

    replacement_plan = None
    if replacements:
        replacement_plan = plan_image_resource_entry_replacements(
            resource_payload,
            replacements,
            source_backed=source_backed,
            synthetic_resource_section=synthetic_psd,
            real_psd_resource_mutation_enabled=enable_real_psd_rewrite,
        )
    mutation_plan = None
    if mutations:
        mutation_plan = plan_image_resource_entry_mutations(
            resource_payload,
            mutations,
            source_backed=source_backed,
            synthetic_resource_section=synthetic_psd,
            real_psd_resource_mutation_enabled=enable_real_psd_rewrite,
        )

    if replacement_plan is not None:
        output_resource_length = replacement_plan.output_length
    elif mutation_plan is not None:
        output_resource_length = mutation_plan.output_length
    else:
        output_resource_length = resource_length
    output_gates = photoshop_psd_output_section_size_gates(
        color_mode_data_length=color_length,
        image_resource_section_length=output_resource_length,
        layer_and_mask_info_length=layer_length,
    )
    nested_plan = plan_photoshop_nested_metadata_routes(
        resource_payload,
        source_backed=source_backed,
        synthetic_resource_section=synthetic_psd,
        include_photomechanic_trailer=trailer_section is not None,
    )
    references = (
        PHOTOSHOP_PSD_HEADER_SOURCE,
        PHOTOSHOP_PSD_PROCESS_BOUNDARY_SOURCE,
        PHOTOSHOP_PSD_WRITE_SOURCE_ID,
        WRITE_PHOTOSHOP_SOURCE_ID,
        PHOTOSHOP_PSD_LAYER_MASK_SOURCE,
        PHOTOSHOP_PSD_IMAGE_DATA_SOURCE,
        *(nested_plan.source_reference_ids),
    )
    if trailer_section is not None:
        references = (
            *references,
            PHOTOSHOP_PSD_TRAILER_WRITE_SOURCE_ID,
            PHOTOMECHANIC_TRAILER_SOURCE_ID,
            PHOTOSHOP_PHOTOMECHANIC_TRAILER_BOUNDARY_SOURCE,
        )

    return PhotoshopPSDSectionBoundaryPlan(
        source_length=len(psd_data),
        header=header,
        header_section=header_section,
        color_mode_data_section=color_section,
        image_resource_section=resource_section,
        layer_and_mask_info_section=layer_section,
        image_data_section=image_data_section,
        trailer_section=trailer_section,
        image_resource_section_payload=resource_payload,
        image_resource_blocks=image_resource_blocks,
        nested_metadata_plan=nested_plan,
        image_resource_replacement_plan=replacement_plan,
        image_resource_mutation_plan=mutation_plan,
        output_section_size_gates=output_gates,
        real_psd_rewrite_enabled=enable_real_psd_rewrite,
        source_reference_ids=tuple(dict.fromkeys(references)),
    )


def rewrite_photoshop_psd_image_resources(
    psd_data: bytes,
    mutations: Sequence[PhotoshopImageResourceMutation],
    *,
    source_backed: bool = True,
) -> bytes:
    plan = plan_photoshop_psd_section_boundaries(
        psd_data,
        mutations=mutations,
        source_backed=source_backed,
        synthetic_psd=False,
        enable_real_psd_rewrite=True,
    )
    if not plan.can_rewrite_real_psd or plan.image_resource_mutation_plan is None:
        raise PhotoshopPSDUnsupportedWriteError(
            "Photoshop PSD image-resource transaction rewrite is blocked: "
            + ", ".join(plan.blocker_codes)
        )
    length_field_start = plan.image_resource_section.length_field_start
    if length_field_start is None:
        raise PhotoshopPSDSectionBoundaryError(
            "Photoshop PSD image-resource length field is missing."
        )
    return b"".join(
        (
            psd_data[:length_field_start],
            plan.output_image_resource_section_length_field,
            plan.output_image_resource_section_payload,
            psd_data[plan.image_resource_section.data_end :],
        )
    )


def rewrite_synthetic_photoshop_psd_image_resources(
    psd_data: bytes,
    mutations: Sequence[PhotoshopImageResourceMutation],
    *,
    source_backed: bool = True,
) -> bytes:
    plan = plan_photoshop_psd_section_boundaries(
        psd_data,
        mutations=mutations,
        source_backed=source_backed,
        synthetic_psd=True,
    )
    if not plan.can_rewrite_synthetic_psd or plan.image_resource_mutation_plan is None:
        raise PhotoshopPSDUnsupportedWriteError(
            "Photoshop synthetic PSD image-resource rewrite is blocked: "
            + ", ".join(plan.blocker_codes)
        )
    length_field_start = plan.image_resource_section.length_field_start
    if length_field_start is None:
        raise PhotoshopPSDSectionBoundaryError(
            "Photoshop PSD image-resource length field is missing."
        )
    return b"".join(
        (
            psd_data[:length_field_start],
            plan.output_image_resource_section_length_field,
            plan.output_image_resource_section_payload,
            psd_data[plan.image_resource_section.data_end :],
        )
    )


def parse_photoshop_psd_header(psd_data: bytes) -> PhotoshopPSDHeader:
    if len(psd_data) < PSD_HEADER_LENGTH + PSD_LENGTH_FIELD_SIZE:
        raise PhotoshopPSDSectionBoundaryError("Truncated Photoshop PSD header.")
    if psd_data[:4] != PSD_SIGNATURE:
        raise PhotoshopPSDSectionBoundaryError("Not a valid Photoshop PSD file.")
    version = int.from_bytes(psd_data[4:6], "big")
    if version == 2:
        raise PhotoshopPSDSectionBoundaryError(
            "Photoshop PSB boundary planning is not enabled by this PSD planner."
        )
    if version != 1:
        raise PhotoshopPSDSectionBoundaryError("Not a valid Photoshop PSD version.")

    return PhotoshopPSDHeader(
        signature=psd_data[:4],
        version=version,
        channels=int.from_bytes(psd_data[12:14], "big"),
        height=int.from_bytes(psd_data[14:18], "big"),
        width=int.from_bytes(psd_data[18:22], "big"),
        bit_depth=int.from_bytes(psd_data[22:24], "big"),
        color_mode=int.from_bytes(psd_data[24:26], "big"),
    )


def detect_photomechanic_trailer(
    psd_data: bytes,
    *,
    minimum_start: int,
) -> PhotoshopPSDSectionBoundary | None:
    if len(psd_data) < minimum_start + 2 + PHOTOMECHANIC_TRAILER_FOOTER_LENGTH:
        return None
    footer_start = len(psd_data) - PHOTOMECHANIC_TRAILER_FOOTER_LENGTH
    footer = psd_data[footer_start:]
    if footer[4:] != PHOTOMECHANIC_TRAILER_FOOTER_SIGNATURE:
        return None

    payload_length = int.from_bytes(footer[:4], "big")
    if payload_length & 0x80000000:
        return None
    trailer_start = footer_start - payload_length
    if trailer_start < minimum_start + 2:
        return None

    return PhotoshopPSDSectionBoundary(
        kind="photomechanic_trailer",
        total_start=trailer_start,
        total_end=len(psd_data),
        data_start=trailer_start,
        data_end=footer_start,
    )


def photoshop_psd_output_section_size_gates(
    *,
    color_mode_data_length: int,
    image_resource_section_length: int,
    layer_and_mask_info_length: int,
) -> tuple[PhotoshopPSDOutputSectionSizeGate, ...]:
    return (
        output_section_size_gate(
            name="output_color_mode_data_length",
            value=color_mode_data_length,
            blocker_code="output_color_mode_data_too_large",
        ),
        output_section_size_gate(
            name="output_image_resource_section_length",
            value=image_resource_section_length,
            blocker_code="output_image_resource_section_too_large",
        ),
        output_section_size_gate(
            name="output_layer_and_mask_info_length",
            value=layer_and_mask_info_length,
            blocker_code="output_layer_and_mask_info_too_large",
        ),
    )


def output_section_size_gate(
    *,
    name: PhotoshopPSDSizeGateName,
    value: int,
    blocker_code: PhotoshopPSDSectionBoundaryBlockerCode,
) -> PhotoshopPSDOutputSectionSizeGate:
    fits = 0 <= value <= PSD_UINT32_MAX
    return PhotoshopPSDOutputSectionSizeGate(
        name=name,
        value=value,
        maximum=PSD_UINT32_MAX,
        fits=fits,
        blocker_code=None if fits else blocker_code,
        source_reference_id=PHOTOSHOP_PSD_PROCESS_BOUNDARY_SOURCE,
    )


def read_psd_u32(psd_data: bytes, offset: int, field_name: str) -> int:
    if offset + PSD_LENGTH_FIELD_SIZE > len(psd_data):
        raise PhotoshopPSDSectionBoundaryError(
            f"Truncated Photoshop PSD {field_name} length field."
        )
    return int.from_bytes(psd_data[offset : offset + PSD_LENGTH_FIELD_SIZE], "big")


def checked_section_end(
    psd_data: bytes,
    data_start: int,
    payload_length: int,
    section_name: str,
) -> int:
    data_end = data_start + payload_length
    if data_end > len(psd_data):
        raise PhotoshopPSDSectionBoundaryError(f"Truncated Photoshop PSD {section_name} section.")
    return data_end
