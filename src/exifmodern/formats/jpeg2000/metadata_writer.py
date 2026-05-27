"""Source-grounded JPEG 2000 JP2 metadata box writer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.exif_scalar_write_plan import ExifScalarWritePlan
from exifmodern.file_transaction import FileWriteTransactionResult, write_bytes_transactionally
from exifmodern.formats.iptc.dataset_writer import apply_iptc_application_write_plan
from exifmodern.formats.iptc.write_plan import IptcApplicationWritePlan
from exifmodern.formats.jpeg2000.boxes import Jp2Box, encode_jp2_boxes, read_jp2_boxes
from exifmodern.formats.tiff.exif_scalar_rewriter import (
    create_minimal_exif_scalar_tiff,
    rewrite_exif_scalars_creating_if_needed,
)
from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
from exifmodern.formats.xmp.packet import empty_xmp_packet
from exifmodern.formats.xmp.property_write import XmpPropertyWritePlan

type Jp2ColorSpaceName = Literal["Bi-level", "Grayscale", "sRGB"]
type Jp2MetadataKind = Literal["exif", "iptc", "xmp", "xml"]

JP2_IMAGE_DATA_BOX_TYPES = {"jp2c"}
JP2_HEADER_BOX_TYPE = "jp2h"
JP2_IMAGE_HEADER_BOX_TYPE = "ihdr"
JP2_COLOR_SPEC_BOX_TYPE = "colr"
JP2_SIGNATURE_BOX_TYPE = "jP  "
JP2_SIGNATURE_PAYLOAD = b"\x0d\x0a\x87\x0a"
JP2_FILE_TYPE_BOX_TYPE = "ftyp"
JP2_FILE_TYPE_PAYLOAD = b"jp2 \x00\x00\x00\x00jp2 "
JP2_CODESTREAM_BOX_TYPE = "jp2c"
JP2_XML_BOX_TYPE = "xml "
JP2_UUID_BOX_TYPE = "uuid"
JP2_UUID_EXIF = b"JpgTiffExif->JP2"
JP2_UUID_EXIF2 = bytes.fromhex("0537cdab9d0c4431a72afa561f2a113e")
JP2_UUID_IPTC = bytes.fromhex("33c7a4d2b81d4723a0baf1a3e097ad38")
JP2_UUID_IPTC2 = bytes.fromhex("09a14e97c0b442e0bebf36df6f0ce36f")
JP2_UUID_XMP = bytes.fromhex("be7acfcb97a942e89c71999491e3afac")
JP2_UUID_GEOJP2 = bytes.fromhex("b14bf8bd083d4b43a5ae8cd7d5a6ce03")
JP2_UUID_PHOTOSHOP = bytes.fromhex("2c4c0100850440b9a03e562148d6dfeb")
JP2_ENUMERATED_COLOR_SPACES: dict[Jp2ColorSpaceName, int] = {
    "Bi-level": 0,
    "Grayscale": 17,
    "sRGB": 16,
}


@dataclass(frozen=True)
class Jp2ColorSpecPlan:
    color_space: Jp2ColorSpaceName
    precedence: int = 0
    approximation: int = 0


@dataclass(frozen=True)
class Jp2MetadataRewriteResult:
    data: bytes
    changed_exif_properties: int
    changed_iptc_properties: int
    changed_xmp_properties: int
    changed_xml_boxes: int
    changed_color_spec_boxes: int
    deleted_metadata_boxes: int
    transaction: FileWriteTransactionResult | None = None


def rewrite_jp2_metadata(
    data: bytes,
    exif_plan: ExifScalarWritePlan | None,
    iptc_plan: IptcApplicationWritePlan | None,
    xmp_plan: XmpPropertyWritePlan | None,
    xml_payload: bytes | None,
    color_spec_plan: Jp2ColorSpecPlan | None,
) -> Jp2MetadataRewriteResult:
    original_boxes = read_jp2_boxes(data)
    boxes, deleted_metadata_boxes = retained_without_replaced_metadata(
        original_boxes,
        requested_metadata_kinds(exif_plan, iptc_plan, xmp_plan, xml_payload),
    )

    changed_color_spec_boxes = 0
    if color_spec_plan is not None:
        boxes = rewrite_jp2_header_color_spec(boxes, color_spec_plan)
        changed_color_spec_boxes = 1

    if exif_plan is not None:
        boxes = append_metadata_box(
            boxes,
            Jp2Box(
                JP2_UUID_BOX_TYPE,
                JP2_UUID_EXIF + jp2_exif_payload(original_boxes, exif_plan),
            ),
        )

    if iptc_plan is not None:
        boxes = append_metadata_box(
            boxes,
            Jp2Box(
                JP2_UUID_BOX_TYPE,
                JP2_UUID_IPTC + jp2_iptc_payload(original_boxes, iptc_plan),
            ),
        )

    if xmp_plan is not None:
        xmp_result = apply_xmp_property_write_plan(jp2_xmp_payload(original_boxes), xmp_plan)
        boxes = append_metadata_box(
            boxes,
            Jp2Box(JP2_UUID_BOX_TYPE, JP2_UUID_XMP + xmp_result.packet),
        )
        changed_xmp_properties = xmp_result.changed_properties
    else:
        changed_xmp_properties = 0

    changed_xml_boxes = 0
    if xml_payload is not None:
        boxes = append_metadata_box(boxes, Jp2Box(JP2_XML_BOX_TYPE, xml_payload))
        changed_xml_boxes = 1

    return Jp2MetadataRewriteResult(
        data=encode_jp2_boxes(boxes),
        changed_exif_properties=0 if exif_plan is None else len(exif_plan.steps),
        changed_iptc_properties=0 if iptc_plan is None else len(iptc_plan.steps),
        changed_xmp_properties=changed_xmp_properties,
        changed_xml_boxes=changed_xml_boxes,
        changed_color_spec_boxes=changed_color_spec_boxes,
        deleted_metadata_boxes=deleted_metadata_boxes,
    )


def rewrite_jp2_file_metadata(
    input_path: Path,
    output_path: Path,
    exif_plan: ExifScalarWritePlan | None,
    iptc_plan: IptcApplicationWritePlan | None,
    xmp_plan: XmpPropertyWritePlan | None,
    xml_payload: bytes | None,
    color_spec_plan: Jp2ColorSpecPlan | None,
) -> Jp2MetadataRewriteResult:
    result = rewrite_jp2_metadata(
        input_path.read_bytes(),
        exif_plan,
        iptc_plan,
        xmp_plan,
        xml_payload,
        color_spec_plan,
    )
    transaction = write_bytes_transactionally(output_path, result.data)
    return Jp2MetadataRewriteResult(
        data=result.data,
        changed_exif_properties=result.changed_exif_properties,
        changed_iptc_properties=result.changed_iptc_properties,
        changed_xmp_properties=result.changed_xmp_properties,
        changed_xml_boxes=result.changed_xml_boxes,
        changed_color_spec_boxes=result.changed_color_spec_boxes,
        deleted_metadata_boxes=result.deleted_metadata_boxes,
        transaction=transaction,
    )


def retained_without_replaced_metadata(
    boxes: tuple[Jp2Box, ...],
    requested_metadata: tuple[Jp2MetadataKind, ...],
) -> tuple[tuple[Jp2Box, ...], int]:
    requested = set(requested_metadata)
    retained: list[Jp2Box] = []
    deleted = 0
    for box in boxes:
        if jp2_metadata_kind(box) in requested:
            deleted += 1
            continue
        retained.append(box)
    return tuple(retained), deleted


def is_jp2_metadata_box(box: Jp2Box) -> bool:
    return jp2_metadata_kind(box) is not None


def jp2_metadata_kind(box: Jp2Box) -> Jp2MetadataKind | None:
    if box.box_type == JP2_XML_BOX_TYPE:
        return "xml"
    if box.box_type != JP2_UUID_BOX_TYPE:
        return None
    if box.payload.startswith(JP2_UUID_EXIF):
        return "exif"
    if box.payload.startswith(JP2_UUID_IPTC):
        return "iptc"
    if box.payload.startswith(JP2_UUID_XMP):
        return "xmp"
    return None


def requested_metadata_kinds(
    exif_plan: ExifScalarWritePlan | None,
    iptc_plan: IptcApplicationWritePlan | None,
    xmp_plan: XmpPropertyWritePlan | None,
    xml_payload: bytes | None,
) -> tuple[Jp2MetadataKind, ...]:
    requested: list[Jp2MetadataKind] = []
    if exif_plan is not None:
        requested.append("exif")
    if iptc_plan is not None:
        requested.append("iptc")
    if xmp_plan is not None:
        requested.append("xmp")
    if xml_payload is not None:
        requested.append("xml")
    return tuple(requested)


def append_metadata_box(boxes: tuple[Jp2Box, ...], metadata_box: Jp2Box) -> tuple[Jp2Box, ...]:
    return (*boxes, metadata_box)


def rewrite_jp2_header_color_spec(
    boxes: tuple[Jp2Box, ...],
    plan: Jp2ColorSpecPlan,
) -> tuple[Jp2Box, ...]:
    rewritten: list[Jp2Box] = []
    replaced = False
    for box in boxes:
        if box.box_type == JP2_HEADER_BOX_TYPE:
            rewritten.append(Jp2Box(box.box_type, rewrite_jp2_header_payload(box.payload, plan)))
            replaced = True
        else:
            rewritten.append(box)
    if not replaced:
        raise ValueError("JP2 ColorSpec write requires an existing jp2h header box.")
    return tuple(rewritten)


def rewrite_jp2_header_payload(payload: bytes, plan: Jp2ColorSpecPlan) -> bytes:
    boxes = read_jp2_boxes(payload)
    rewritten: list[Jp2Box] = []
    inserted = False
    for box in boxes:
        if box.box_type == JP2_COLOR_SPEC_BOX_TYPE:
            continue
        rewritten.append(box)
        if box.box_type == JP2_IMAGE_HEADER_BOX_TYPE and not inserted:
            rewritten.append(color_spec_box(plan))
            inserted = True
    if not inserted:
        raise ValueError("JP2 ColorSpec write requires an existing ihdr box inside jp2h.")
    return encode_jp2_boxes(tuple(rewritten))


def color_spec_box(plan: Jp2ColorSpecPlan) -> Jp2Box:
    if plan.precedence < 0 or plan.precedence > 255:
        raise ValueError("ColorSpecPrecedence must fit in one byte.")
    if plan.approximation < 0 or plan.approximation > 255:
        raise ValueError("ColorSpecApproximation must fit in one byte.")
    color_space_value = JP2_ENUMERATED_COLOR_SPACES[plan.color_space]
    payload = bytes((1, plan.precedence, plan.approximation)) + color_space_value.to_bytes(4, "big")
    return Jp2Box(JP2_COLOR_SPEC_BOX_TYPE, payload)


def jp2_exif_payload(boxes: tuple[Jp2Box, ...], plan: ExifScalarWritePlan) -> bytes:
    existing_payload = first_uuid_payload(boxes, JP2_UUID_EXIF)
    if existing_payload is None:
        return create_minimal_exif_scalar_tiff(plan)
    return rewrite_exif_scalars_creating_if_needed(existing_payload, plan)


def jp2_iptc_payload(boxes: tuple[Jp2Box, ...], plan: IptcApplicationWritePlan) -> bytes:
    return apply_iptc_application_write_plan(first_uuid_payload(boxes, JP2_UUID_IPTC) or b"", plan)


def jp2_xmp_payload(boxes: tuple[Jp2Box, ...]) -> bytes:
    return first_uuid_payload(boxes, JP2_UUID_XMP) or empty_xmp_packet()


def first_uuid_payload(boxes: tuple[Jp2Box, ...], uuid: bytes) -> bytes | None:
    for box in boxes:
        if box.box_type == JP2_UUID_BOX_TYPE and box.payload.startswith(uuid):
            return box.payload[len(uuid) :]
    return None
