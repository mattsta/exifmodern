"""Photoshop EXIFInfo TIFF resource staging.

ExifTool stores PSD EXIF metadata as Photoshop image resource ``0x0422`` and
delegates its payload to the TIFF writer.  This module keeps that bridge
package-local: it builds the exact scalar write plan, emits the supported TIFF
payload subset, and adapts the result into an IRB mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.exif_scalar_write_plan import (
    ExifScalarWritePlan,
    ExifScalarWriteStep,
    artist_step,
    x_resolution_step,
    y_resolution_step,
)
from exifmodern.formats.photoshop.image_resources import (
    PHOTOSHOP_WRITABLE_IRB_SIGNATURE,
    PhotoshopImageResourceBlock,
)
from exifmodern.formats.photoshop.nested_metadata_plan import (
    EXIF_WRITE_SOURCE_ID,
    PHOTOSHOP_RESOURCE_ID_EXIF_INFO,
)
from exifmodern.formats.photoshop.resource_writer import PhotoshopImageResourceMutation
from exifmodern.formats.photoshop.section_boundary_plan import PhotoshopPSDSectionBoundaryPlan
from exifmodern.formats.photoshop.write_plan import (
    EXIF_ARTIST_SOURCE_ID,
    EXIF_RESOLUTION_SOURCE_ID,
    PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE_ID,
    PhotoshopEvidenceCompat,
    PhotoshopPSDRequestedAssignment,
)
from exifmodern.formats.tiff.exif_scalar_rewriter import (
    create_minimal_exif_scalar_tiff,
    rewrite_exif_scalars_creating_if_needed,
)

type PhotoshopEmbeddedExifInfoAction = Literal["none", "insert", "replace", "blocked"]
type PhotoshopEmbeddedExifInfoBlockerCode = Literal[
    "not_source_backed",
    "duplicate_exif_info_resource",
    "non_8bim_exif_info_resource",
    "requires_photoshop_embedded_tiff_write_tiff_bridge",
    "empty_tiff_payload_removes_exif_info_resource",
    "invalid_tiff_payload_bridge_request",
    "unsupported_tiff_payload_scalar_plan",
    "malformed_source_tiff_payload",
]

WRITE_TIFF_SOURCE_ID = "photoshop.embedded_exif.write_tiff"
WRITE_PHOTOSHOP_SUBDIRECTORY_SOURCE_ID = "photoshop.embedded_exif.write_photoshop_subdir"


def _photoshop_embedded_exif_source_reference(source_id: str) -> str:
    return source_id


WRITE_TIFF_SOURCE_ID = _photoshop_embedded_exif_source_reference(WRITE_TIFF_SOURCE_ID)
WRITE_PHOTOSHOP_SUBDIRECTORY_SOURCE_ID = _photoshop_embedded_exif_source_reference(
    WRITE_PHOTOSHOP_SUBDIRECTORY_SOURCE_ID
)


@dataclass(frozen=True)
class PhotoshopEmbeddedExifInfoTiffPayloadRequest(PhotoshopEvidenceCompat):
    resource_id: int
    resource_action: Literal["insert", "replace"]
    resource_name: bytes | None
    source_payload: bytes | None
    scalar_plan: ExifScalarWritePlan
    dir_info_parent: str
    tag_table: str
    process_proc: str
    write_proc: str
    source_reference_ids: tuple[str, ...]

    @property
    def source_payload_length(self) -> int | None:
        if self.source_payload is None:
            return None
        return len(self.source_payload)

    @property
    def requested_tags(self) -> tuple[str, ...]:
        return tuple(step.tag_name for step in self.scalar_plan.steps)


@dataclass(frozen=True)
class PhotoshopEmbeddedExifInfoTiffPayloadBridgeInput:
    request: PhotoshopEmbeddedExifInfoTiffPayloadRequest
    source_backed: bool


@dataclass(frozen=True)
class PhotoshopEmbeddedExifInfoTiffPayloadBridgeOutput(PhotoshopEvidenceCompat):
    request: PhotoshopEmbeddedExifInfoTiffPayloadRequest
    output_payload: bytes | None
    can_write_bytes: bool
    blocker_codes: tuple[PhotoshopEmbeddedExifInfoBlockerCode, ...]
    resource_mutation_adapter: PhotoshopEmbeddedExifInfoResourceMutationAdapter
    source_reference_ids: tuple[str, ...]

    @property
    def output_payload_length(self) -> int | None:
        if self.output_payload is None:
            return None
        return len(self.output_payload)


@dataclass(frozen=True)
class PhotoshopEmbeddedExifInfoResourceMutationAdapter:
    request: PhotoshopEmbeddedExifInfoTiffPayloadRequest
    output_payload: bytes | None
    can_materialize: bool
    blocker_codes: tuple[PhotoshopEmbeddedExifInfoBlockerCode, ...]

    @property
    def mutation(self) -> PhotoshopImageResourceMutation | None:
        if not self.can_materialize or self.output_payload is None:
            return None
        return PhotoshopImageResourceMutation(
            self.request.resource_action,
            self.request.resource_id,
            self.output_payload,
            self.request.resource_name,
        )

    @property
    def output_payload_length(self) -> int | None:
        if self.output_payload is None:
            return None
        return len(self.output_payload)


@dataclass(frozen=True)
class PhotoshopEmbeddedExifInfoStagingPlan(PhotoshopEvidenceCompat):
    required: bool
    resource_id: int
    resource_present: bool
    resource_action: PhotoshopEmbeddedExifInfoAction
    requested_fields: tuple[str, ...]
    scalar_plan: ExifScalarWritePlan | None
    can_stage_scalar_plan: bool
    can_write_bytes: bool
    blocker_codes: tuple[PhotoshopEmbeddedExifInfoBlockerCode, ...]
    prerequisite: str | None
    tiff_payload_request: PhotoshopEmbeddedExifInfoTiffPayloadRequest | None
    tiff_payload_bridge_output: PhotoshopEmbeddedExifInfoTiffPayloadBridgeOutput | None
    resource_mutation_adapter: PhotoshopEmbeddedExifInfoResourceMutationAdapter | None
    source_reference_ids: tuple[str, ...]

    @property
    def scalar_tags(self) -> tuple[str, ...]:
        if self.scalar_plan is None:
            return ()
        return tuple(step.tag_name for step in self.scalar_plan.steps)


def plan_embedded_exif_info_staging(
    section_plan: PhotoshopPSDSectionBoundaryPlan,
    assignments: tuple[PhotoshopPSDRequestedAssignment, ...],
    *,
    source_backed: bool,
) -> PhotoshopEmbeddedExifInfoStagingPlan:
    requested_fields = embedded_exif_requested_fields(assignments)
    required = bool(requested_fields)
    blocks = blocks_for_resource(section_plan, PHOTOSHOP_RESOURCE_ID_EXIF_INFO)
    blocker_codes = embedded_exif_resource_blockers(blocks, source_backed=source_backed)
    scalar_plan = embedded_exif_scalar_plan(assignments) if required else None
    can_stage_scalar_plan = scalar_plan is not None or not required
    if not required:
        resource_action: PhotoshopEmbeddedExifInfoAction = "none"
    elif blocker_codes:
        resource_action = "blocked"
    elif blocks:
        resource_action = "replace"
    else:
        resource_action = "insert"

    source_reference_ids = (
        (
            PHOTOSHOP_EXIF_XMP_RESOURCE_SOURCE_ID,
            WRITE_PHOTOSHOP_SUBDIRECTORY_SOURCE_ID,
            EXIF_WRITE_SOURCE_ID,
            WRITE_TIFF_SOURCE_ID,
            EXIF_RESOLUTION_SOURCE_ID,
            EXIF_ARTIST_SOURCE_ID,
        )
        if required
        else ()
    )
    tiff_payload_request = embedded_exif_tiff_payload_request(
        blocks,
        resource_action,
        scalar_plan,
        source_reference_ids=source_reference_ids,
    )
    tiff_payload_bridge_output = (
        produce_embedded_exif_info_tiff_payload_bytes(
            PhotoshopEmbeddedExifInfoTiffPayloadBridgeInput(
                request=tiff_payload_request,
                source_backed=source_backed,
            )
        )
        if tiff_payload_request is not None
        else None
    )
    bridge_blockers = (
        blocker_codes
        if tiff_payload_bridge_output is None
        else tiff_payload_bridge_output.blocker_codes
    )
    resource_mutation_adapter = (
        None
        if tiff_payload_bridge_output is None
        else tiff_payload_bridge_output.resource_mutation_adapter
    )

    return PhotoshopEmbeddedExifInfoStagingPlan(
        required=required,
        resource_id=PHOTOSHOP_RESOURCE_ID_EXIF_INFO,
        resource_present=bool(blocks),
        resource_action=resource_action,
        requested_fields=requested_fields,
        scalar_plan=scalar_plan,
        can_stage_scalar_plan=can_stage_scalar_plan,
        can_write_bytes=not bridge_blockers,
        blocker_codes=bridge_blockers,
        prerequisite=(
            "Extend the Photoshop EXIFInfo TIFF payload bridge to cover this "
            "request/resource shape before feeding bytes to the package-local "
            "IRB insert/replace primitive."
            if required and bridge_blockers
            else None
        ),
        tiff_payload_request=tiff_payload_request,
        tiff_payload_bridge_output=tiff_payload_bridge_output,
        resource_mutation_adapter=resource_mutation_adapter,
        source_reference_ids=source_reference_ids,
    )


def embedded_exif_requested_fields(
    assignments: tuple[PhotoshopPSDRequestedAssignment, ...],
) -> tuple[str, ...]:
    fields: list[str] = []
    for assignment in assignments:
        tag = normalized_assignment_tag(assignment)
        if tag == "xresolution":
            fields.append("IFD0:XResolution")
        if tag == "yresolution":
            fields.append("IFD0:YResolution")
        if tag == "creator":
            fields.append("IFD0:Artist")
    return tuple(dict.fromkeys(fields))


def embedded_exif_scalar_plan(
    assignments: tuple[PhotoshopPSDRequestedAssignment, ...],
) -> ExifScalarWritePlan | None:
    steps: list[ExifScalarWriteStep] = []
    for assignment in assignments:
        if assignment.value is None:
            continue
        tag = normalized_assignment_tag(assignment)
        if tag == "xresolution":
            steps.append(x_resolution_step(assignment.value))
        if tag == "yresolution":
            steps.append(y_resolution_step(assignment.value))
        if tag == "creator":
            steps.append(artist_step(assignment.value))
    if not steps:
        return None
    return ExifScalarWritePlan(tuple(steps))


def embedded_exif_resource_blockers(
    blocks: tuple[PhotoshopImageResourceBlock, ...],
    *,
    source_backed: bool,
) -> tuple[PhotoshopEmbeddedExifInfoBlockerCode, ...]:
    blocker_codes: list[PhotoshopEmbeddedExifInfoBlockerCode] = []
    if not source_backed:
        blocker_codes.append("not_source_backed")
    if len(blocks) > 1:
        blocker_codes.append("duplicate_exif_info_resource")
    if any(block.signature != PHOTOSHOP_WRITABLE_IRB_SIGNATURE for block in blocks):
        blocker_codes.append("non_8bim_exif_info_resource")
    return tuple(dict.fromkeys(blocker_codes))


def embedded_exif_tiff_payload_request(
    blocks: tuple[PhotoshopImageResourceBlock, ...],
    resource_action: PhotoshopEmbeddedExifInfoAction,
    scalar_plan: ExifScalarWritePlan | None,
    *,
    source_reference_ids: tuple[str, ...],
) -> PhotoshopEmbeddedExifInfoTiffPayloadRequest | None:
    if scalar_plan is None:
        return None
    if resource_action == "insert":
        tiff_resource_action: Literal["insert", "replace"] = "insert"
    elif resource_action == "replace":
        tiff_resource_action = "replace"
    else:
        return None
    block = blocks[0] if blocks else None
    return PhotoshopEmbeddedExifInfoTiffPayloadRequest(
        resource_id=PHOTOSHOP_RESOURCE_ID_EXIF_INFO,
        resource_action=tiff_resource_action,
        resource_name=None if block is None else block.name,
        source_payload=None if block is None else block.data,
        scalar_plan=scalar_plan,
        dir_info_parent="Photoshop",
        tag_table="Image::ExifTool::Exif::Main",
        process_proc="Image::ExifTool::ProcessTIFF",
        write_proc="Image::ExifTool::WriteTIFF",
        source_reference_ids=source_reference_ids,
    )


def materialize_embedded_exif_info_resource_mutation(
    request: PhotoshopEmbeddedExifInfoTiffPayloadRequest,
    tiff_payload: bytes,
    *,
    source_backed: bool,
) -> PhotoshopEmbeddedExifInfoResourceMutationAdapter:
    """Adapt an already-produced TIFF payload into Photoshop resource 0x0422.

    ExifTool's Photoshop writer uses non-empty subdirectory WriteProc output as
    the resource payload.  Empty output removes an existing subdirectory entry
    or skips a new one, so this adapter refuses empty bytes instead of silently
    turning an EXIFInfo write into deletion.
    """

    blocker_codes: list[PhotoshopEmbeddedExifInfoBlockerCode] = []
    if not source_backed:
        blocker_codes.append("not_source_backed")
    if not tiff_payload:
        blocker_codes.append("empty_tiff_payload_removes_exif_info_resource")
    return PhotoshopEmbeddedExifInfoResourceMutationAdapter(
        request=request,
        output_payload=tiff_payload,
        can_materialize=not blocker_codes,
        blocker_codes=tuple(blocker_codes),
    )


def produce_embedded_exif_info_tiff_payload_bytes(
    bridge_input: PhotoshopEmbeddedExifInfoTiffPayloadBridgeInput,
) -> PhotoshopEmbeddedExifInfoTiffPayloadBridgeOutput:
    """Produce Photoshop EXIFInfo TIFF payload bytes for the staged scalar subset."""

    request = bridge_input.request
    blocker_codes = validate_embedded_exif_info_tiff_payload_request(bridge_input)
    output_payload: bytes | None = None
    if not blocker_codes:
        try:
            if request.resource_action == "insert":
                output_payload = create_minimal_exif_scalar_tiff(request.scalar_plan)
            else:
                output_payload = rewrite_exif_scalars_creating_if_needed(
                    request.source_payload or b"",
                    request.scalar_plan,
                )
        except ValueError:
            blocker_codes = ("malformed_source_tiff_payload",)
    if blocker_codes:
        adapter = PhotoshopEmbeddedExifInfoResourceMutationAdapter(
            request=request,
            output_payload=output_payload,
            can_materialize=False,
            blocker_codes=blocker_codes,
        )
    else:
        adapter = materialize_embedded_exif_info_resource_mutation(
            request,
            output_payload or b"",
            source_backed=bridge_input.source_backed,
        )
        blocker_codes = tuple(dict.fromkeys(adapter.blocker_codes))
    return PhotoshopEmbeddedExifInfoTiffPayloadBridgeOutput(
        request=request,
        output_payload=output_payload,
        can_write_bytes=not blocker_codes,
        blocker_codes=blocker_codes,
        resource_mutation_adapter=adapter,
        source_reference_ids=request.source_reference_ids,
    )


def validate_embedded_exif_info_tiff_payload_request(
    bridge_input: PhotoshopEmbeddedExifInfoTiffPayloadBridgeInput,
) -> tuple[PhotoshopEmbeddedExifInfoBlockerCode, ...]:
    request = bridge_input.request
    blocker_codes: list[PhotoshopEmbeddedExifInfoBlockerCode] = []
    if not bridge_input.source_backed:
        blocker_codes.append("not_source_backed")
    if (
        request.resource_id != PHOTOSHOP_RESOURCE_ID_EXIF_INFO
        or request.dir_info_parent != "Photoshop"
        or request.tag_table != "Image::ExifTool::Exif::Main"
        or request.process_proc != "Image::ExifTool::ProcessTIFF"
        or request.write_proc != "Image::ExifTool::WriteTIFF"
    ):
        blocker_codes.append("invalid_tiff_payload_bridge_request")
    if request.resource_action == "insert" and request.source_payload is not None:
        blocker_codes.append("invalid_tiff_payload_bridge_request")
    if request.resource_action == "replace" and request.source_payload is None:
        blocker_codes.append("invalid_tiff_payload_bridge_request")
    if not request.scalar_plan.steps or any(
        step.directory_name != "IFD0"
        or step.operation != "upsert"
        or step.tag_name not in {"XResolution", "YResolution", "Artist"}
        for step in request.scalar_plan.steps
    ):
        blocker_codes.append("unsupported_tiff_payload_scalar_plan")
    return tuple(dict.fromkeys(blocker_codes))


def blocks_for_resource(
    section_plan: PhotoshopPSDSectionBoundaryPlan,
    resource_id: int,
) -> tuple[PhotoshopImageResourceBlock, ...]:
    return tuple(
        block for block in section_plan.image_resource_blocks if block.resource_id == resource_id
    )


def normalized_assignment_tag(assignment: PhotoshopPSDRequestedAssignment) -> str:
    return assignment.tag.casefold().replace("_", "-")
