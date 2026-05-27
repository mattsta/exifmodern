"""Source-grounded JPEG XL EXIF/XMP box writer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.exif_scalar_write_plan import ExifScalarWritePlan
from exifmodern.file_transaction import FileWriteTransactionResult, write_bytes_transactionally
from exifmodern.formats.jpeg2000.boxes import Jp2Box, encode_jp2_boxes, read_jp2_boxes
from exifmodern.formats.tiff.exif_scalar_rewriter import (
    create_minimal_exif_scalar_tiff,
    rewrite_exif_scalars_creating_if_needed,
)
from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
from exifmodern.formats.xmp.packet import empty_xmp_packet
from exifmodern.formats.xmp.property_write import XmpPropertyWritePlan

JXL_CONTAINER_SIGNATURE = b"\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a"
JXL_CODESTREAM_MAGIC = b"\xff\x0a"
JXL_FILE_TYPE_BOX = Jp2Box("ftyp", b"jxl \x00\x00\x00\x00jxl ")
JXL_IMAGE_DATA_BOX_TYPES = {"jbrd", "jxlc", "jxlp"}
JXL_METADATA_BOX_TYPES = {"Exif", "xml ", "brob"}
JXL_EXIF_PREFIX = b"\x00\x00\x00\x00"


@dataclass(frozen=True)
class JxlContainer:
    boxes: tuple[Jp2Box, ...]
    wrapped_codestream: bool


@dataclass(frozen=True)
class JxlMetadataRewriteResult:
    data: bytes
    changed_exif_properties: int
    changed_xmp_properties: int
    deleted_metadata_boxes: int
    wrapped_codestream: bool
    transaction: FileWriteTransactionResult | None = None


def rewrite_jxl_metadata(
    data: bytes,
    exif_plan: ExifScalarWritePlan | None,
    xmp_plan: XmpPropertyWritePlan | None,
    delete_all_metadata: bool = False,
) -> JxlMetadataRewriteResult:
    container = parse_jxl_container(data)
    boxes = container.boxes
    deleted_metadata_boxes = 0
    if delete_all_metadata:
        retained_boxes = tuple(box for box in boxes if box.box_type not in JXL_METADATA_BOX_TYPES)
        deleted_metadata_boxes = len(boxes) - len(retained_boxes)
        boxes = retained_boxes

    changed_exif_properties = 0
    if exif_plan is not None:
        boxes = upsert_metadata_box(
            boxes, Jp2Box("Exif", JXL_EXIF_PREFIX + jxl_exif_payload(boxes, exif_plan))
        )
        changed_exif_properties = len(exif_plan.steps)

    changed_xmp_properties = 0
    if xmp_plan is not None:
        xmp_result = apply_xmp_property_write_plan(jxl_xmp_payload(boxes), xmp_plan)
        boxes = upsert_metadata_box(boxes, Jp2Box("xml ", xmp_result.packet))
        changed_xmp_properties = xmp_result.changed_properties

    return JxlMetadataRewriteResult(
        data=JXL_CONTAINER_SIGNATURE + encode_jp2_boxes(boxes),
        changed_exif_properties=changed_exif_properties,
        changed_xmp_properties=changed_xmp_properties,
        deleted_metadata_boxes=deleted_metadata_boxes,
        wrapped_codestream=container.wrapped_codestream,
    )


def rewrite_jxl_file_metadata(
    input_path: Path,
    output_path: Path,
    exif_plan: ExifScalarWritePlan | None,
    xmp_plan: XmpPropertyWritePlan | None,
    delete_all_metadata: bool = False,
) -> JxlMetadataRewriteResult:
    result = rewrite_jxl_metadata(input_path.read_bytes(), exif_plan, xmp_plan, delete_all_metadata)
    transaction = write_bytes_transactionally(output_path, result.data)
    return JxlMetadataRewriteResult(
        data=result.data,
        changed_exif_properties=result.changed_exif_properties,
        changed_xmp_properties=result.changed_xmp_properties,
        deleted_metadata_boxes=result.deleted_metadata_boxes,
        wrapped_codestream=result.wrapped_codestream,
        transaction=transaction,
    )


def parse_jxl_container(data: bytes) -> JxlContainer:
    if data.startswith(JXL_CONTAINER_SIGNATURE):
        return JxlContainer(
            boxes=read_jp2_boxes(data[len(JXL_CONTAINER_SIGNATURE) :]),
            wrapped_codestream=False,
        )
    if data.startswith(JXL_CODESTREAM_MAGIC):
        return JxlContainer(
            boxes=(JXL_FILE_TYPE_BOX, Jp2Box("jxlc", data)),
            wrapped_codestream=True,
        )
    raise ValueError("Unsupported JPEG XL file: expected ISO BMFF JXL container or codestream.")


def jxl_exif_payload(boxes: tuple[Jp2Box, ...], plan: ExifScalarWritePlan) -> bytes:
    existing_payload = first_box_payload(boxes, "Exif")
    if existing_payload is None:
        return create_minimal_exif_scalar_tiff(plan)
    return rewrite_exif_scalars_creating_if_needed(strip_jxl_exif_prefix(existing_payload), plan)


def strip_jxl_exif_prefix(payload: bytes) -> bytes:
    if payload.startswith(JXL_EXIF_PREFIX):
        return payload[len(JXL_EXIF_PREFIX) :]
    return payload


def jxl_xmp_payload(boxes: tuple[Jp2Box, ...]) -> bytes:
    existing_payload = first_box_payload(boxes, "xml ")
    return empty_xmp_packet() if existing_payload is None else existing_payload


def first_box_payload(boxes: tuple[Jp2Box, ...], box_type: str) -> bytes | None:
    for box in boxes:
        if box.box_type == box_type:
            return box.payload
    return None


def upsert_metadata_box(boxes: tuple[Jp2Box, ...], metadata_box: Jp2Box) -> tuple[Jp2Box, ...]:
    retained = tuple(box for box in boxes if box.box_type != metadata_box.box_type)
    insertion_index = metadata_insertion_index(retained)
    return (*retained[:insertion_index], metadata_box, *retained[insertion_index:])


def metadata_insertion_index(boxes: tuple[Jp2Box, ...]) -> int:
    for index, box in enumerate(boxes):
        if box.box_type in JXL_IMAGE_DATA_BOX_TYPES:
            return index
    return len(boxes)
