"""JPEG APP13 Photoshop IPTC ApplicationRecord mutation boundary."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.iptc.dataset_writer import (
    IPTC_DATASET_MARKER as IPTC_DATASET_MARKER,
)
from exifmodern.formats.iptc.dataset_writer import (
    IptcApplicationDataset,
    apply_iptc_application_write_plan,
    encode_iptc_dataset,
    parse_iptc_datasets,
)
from exifmodern.formats.iptc.write_plan import IptcApplicationWritePlan
from exifmodern.formats.jpeg.container import JpegSegment, scan_jpeg_segments
from exifmodern.formats.jpeg.exif_app1 import EXIF_APP1_PREFIX, segment_payload
from exifmodern.formats.photoshop.reader import (
    PHOTOSHOP_APP13_PREFIX,
    PhotoshopResourceBlock,
    parse_photoshop_resources,
)

PHOTOSHOP_IPTC_RESOURCE_ID = 0x0404
PHOTOSHOP_RESOURCE_SIGNATURE = b"8BIM"
JPEG_APP13_MARKER = 0xED

__all__ = [
    "IPTC_DATASET_MARKER",
    "IptcApplicationDataset",
    "JpegIptcApplicationRewriteResult",
    "apply_iptc_application_write_plan",
    "encode_iptc_dataset",
    "parse_iptc_datasets",
    "rewrite_jpeg_iptc_application_block_creating_if_needed",
    "rewrite_jpeg_iptc_application_creating_if_needed",
]


@dataclass(frozen=True)
class JpegIptcApplicationRewriteResult:
    data: bytes
    original_app13_payload_length: int
    rewritten_app13_payload_length: int
    changed_iptc_datasets: int


def rewrite_jpeg_iptc_application_creating_if_needed(
    jpeg_data: bytes,
    plan: IptcApplicationWritePlan,
) -> JpegIptcApplicationRewriteResult:
    resources = None
    segment = first_photoshop_app13_segment(jpeg_data)
    if segment is None:
        if plan.is_delete_only:
            return JpegIptcApplicationRewriteResult(
                data=jpeg_data,
                original_app13_payload_length=0,
                rewritten_app13_payload_length=0,
                changed_iptc_datasets=0,
            )
        existing_iptc = b""
    else:
        payload = segment_payload(jpeg_data, segment)
        resources = parse_photoshop_resources(payload)
        existing_iptc = existing_iptc_resource_data(resources)

    rewritten_iptc = apply_iptc_application_write_plan(
        existing_iptc,
        plan,
    )
    return rewrite_jpeg_iptc_application_resource(
        jpeg_data,
        rewritten_iptc,
        segment=segment,
        resources=resources,
        changed_iptc_datasets=len(plan.steps),
    )


def rewrite_jpeg_iptc_application_block_creating_if_needed(
    jpeg_data: bytes,
    iptc_data: bytes,
) -> JpegIptcApplicationRewriteResult:
    return rewrite_jpeg_iptc_application_resource(
        jpeg_data,
        iptc_data,
        changed_iptc_datasets=len(parse_iptc_datasets(iptc_data)),
    )


def rewrite_jpeg_iptc_application_resource(
    jpeg_data: bytes,
    iptc_data: bytes,
    *,
    segment: JpegSegment | None = None,
    resources: list[PhotoshopResourceBlock] | None = None,
    changed_iptc_datasets: int,
) -> JpegIptcApplicationRewriteResult:
    if segment is None:
        segment = first_photoshop_app13_segment(jpeg_data)
    if segment is None:
        if not iptc_data:
            return JpegIptcApplicationRewriteResult(
                data=jpeg_data,
                original_app13_payload_length=0,
                rewritten_app13_payload_length=0,
                changed_iptc_datasets=0,
            )
        rewritten_payload = PHOTOSHOP_APP13_PREFIX + encode_photoshop_resource(
            PhotoshopResourceBlock(
                resource_id=PHOTOSHOP_IPTC_RESOURCE_ID,
                name="",
                data=iptc_data,
            )
        )
        rewritten_segment = encode_app13_segment(rewritten_payload)
        insertion_offset = photoshop_app13_insertion_offset(jpeg_data)
        return JpegIptcApplicationRewriteResult(
            data=jpeg_data[:insertion_offset] + rewritten_segment + jpeg_data[insertion_offset:],
            original_app13_payload_length=0,
            rewritten_app13_payload_length=len(rewritten_payload),
            changed_iptc_datasets=changed_iptc_datasets,
        )

    payload = segment_payload(jpeg_data, segment)
    if resources is None:
        resources = parse_photoshop_resources(payload)
    rewritten_resources = upsert_photoshop_resource(
        resources,
        PhotoshopResourceBlock(resource_id=PHOTOSHOP_IPTC_RESOURCE_ID, name="", data=iptc_data),
    )
    segment_end = segment.payload_offset + segment.payload_length
    if not rewritten_resources:
        return JpegIptcApplicationRewriteResult(
            data=jpeg_data[: segment.offset] + jpeg_data[segment_end:],
            original_app13_payload_length=segment.payload_length,
            rewritten_app13_payload_length=0,
            changed_iptc_datasets=changed_iptc_datasets,
        )
    rewritten_payload = PHOTOSHOP_APP13_PREFIX + b"".join(
        encode_photoshop_resource(resource) for resource in rewritten_resources
    )
    rewritten_segment = encode_app13_segment(rewritten_payload)
    return JpegIptcApplicationRewriteResult(
        data=jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:],
        original_app13_payload_length=segment.payload_length,
        rewritten_app13_payload_length=len(rewritten_payload),
        changed_iptc_datasets=changed_iptc_datasets,
    )


def first_photoshop_app13_segment(jpeg_data: bytes) -> JpegSegment | None:
    for segment in scan_jpeg_segments(jpeg_data):
        if segment.marker != JPEG_APP13_MARKER:
            continue
        if segment_payload(jpeg_data, segment).startswith(PHOTOSHOP_APP13_PREFIX):
            return segment
    return None


def photoshop_app13_insertion_offset(jpeg_data: bytes) -> int:
    insertion_offset = 2
    for segment in scan_jpeg_segments(jpeg_data):
        payload = segment_payload(jpeg_data, segment)
        if segment.marker == 0xE0:
            insertion_offset = segment.payload_offset + segment.payload_length
            continue
        if segment.marker == 0xE1 and payload.startswith(EXIF_APP1_PREFIX):
            insertion_offset = segment.payload_offset + segment.payload_length
            continue
        if segment.marker == JPEG_APP13_MARKER and payload.startswith(PHOTOSHOP_APP13_PREFIX):
            insertion_offset = segment.payload_offset + segment.payload_length
            continue
        break
    return insertion_offset


def existing_iptc_resource_data(resources: list[PhotoshopResourceBlock]) -> bytes:
    for resource in resources:
        if resource.resource_id == PHOTOSHOP_IPTC_RESOURCE_ID:
            return resource.data
    return b""


def upsert_photoshop_resource(
    resources: list[PhotoshopResourceBlock],
    replacement: PhotoshopResourceBlock,
) -> tuple[PhotoshopResourceBlock, ...]:
    updated: list[PhotoshopResourceBlock] = []
    replaced = False
    for resource in resources:
        if resource.resource_id == replacement.resource_id:
            if not replaced and replacement.data:
                updated.append(replacement)
                replaced = True
            continue
        updated.append(resource)
    if not replaced and replacement.data:
        updated.append(replacement)
    return tuple(updated)


def encode_photoshop_resource(resource: PhotoshopResourceBlock) -> bytes:
    data_padding = b"\x00" if len(resource.data) % 2 else b""
    return (
        PHOTOSHOP_RESOURCE_SIGNATURE
        + resource.resource_id.to_bytes(2, "big")
        + encode_pascal_name(resource.name)
        + len(resource.data).to_bytes(4, "big")
        + resource.data
        + data_padding
    )


def encode_pascal_name(name: str) -> bytes:
    encoded = name.encode("latin-1")
    if len(encoded) > 255:
        raise ValueError("Photoshop resource names must fit in one Pascal byte.")
    raw = bytes((len(encoded),)) + encoded
    return raw + (b"\x00" if len(raw) % 2 else b"")


def encode_app13_segment(payload: bytes) -> bytes:
    segment_length = len(payload) + 2
    if segment_length > 0xFFFF:
        raise ValueError("Rewritten Photoshop APP13 segment exceeds JPEG segment size limit.")
    return b"\xff\xed" + segment_length.to_bytes(2, "big") + payload
