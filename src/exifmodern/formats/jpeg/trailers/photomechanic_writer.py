"""JPEG PhotoMechanic trailer mutation boundary."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.jpeg.iptc_app13_writer import (
    IPTC_DATASET_MARKER,
    IptcApplicationDataset,
    encode_iptc_dataset,
)
from exifmodern.formats.photomechanic.reader import PHOTO_MECHANIC_FOOTER_SIGNATURE
from exifmodern.formats.photomechanic.write_plan import PhotoMechanicRotationWritePlan

PHOTO_MECHANIC_SOFT_EDIT_RECORD = 2
PHOTO_MECHANIC_ROTATION_DATASET = 216
PHOTO_MECHANIC_FOOTER_SIZE = 12
PHOTO_MECHANIC_DEFAULT_PADDED_PAYLOAD_SIZE = 0x800


@dataclass(frozen=True)
class PhotoMechanicRewriteResult:
    data: bytes
    changed: bool
    original_payload_length: int
    rewritten_payload_length: int


def rewrite_jpeg_photo_mechanic_rotation(
    jpeg_data: bytes,
    plan: PhotoMechanicRotationWritePlan,
) -> PhotoMechanicRewriteResult:
    trailer = locate_photo_mechanic_trailer(jpeg_data)
    if trailer is None:
        raise ValueError("No JPEG PhotoMechanic trailer found.")
    replacement = plan.raw_rotation_index.to_bytes(4, "big", signed=True)
    rewritten_payload = rewrite_photo_mechanic_soft_edit_dataset(
        trailer.payload,
        PHOTO_MECHANIC_ROTATION_DATASET,
        replacement,
    )
    if len(rewritten_payload) < PHOTO_MECHANIC_DEFAULT_PADDED_PAYLOAD_SIZE:
        rewritten_payload += b"\x00" * (
            PHOTO_MECHANIC_DEFAULT_PADDED_PAYLOAD_SIZE - len(rewritten_payload)
        )
    rewritten_footer = len(rewritten_payload).to_bytes(4, "big") + PHOTO_MECHANIC_FOOTER_SIGNATURE
    data = jpeg_data[: trailer.payload_offset] + rewritten_payload + rewritten_footer
    return PhotoMechanicRewriteResult(
        data=data,
        changed=data != jpeg_data,
        original_payload_length=len(trailer.payload),
        rewritten_payload_length=len(rewritten_payload),
    )


@dataclass(frozen=True)
class PhotoMechanicTrailerLocation:
    payload_offset: int
    payload: bytes


def locate_photo_mechanic_trailer(data: bytes) -> PhotoMechanicTrailerLocation | None:
    signature_offset = data.find(PHOTO_MECHANIC_FOOTER_SIGNATURE)
    while signature_offset >= 0:
        size_offset = signature_offset - 4
        if size_offset >= 0:
            payload_size = int.from_bytes(data[size_offset:signature_offset], "big")
            payload_offset = size_offset - payload_size
            footer_end = signature_offset + len(PHOTO_MECHANIC_FOOTER_SIGNATURE)
            if payload_offset >= 0 and footer_end == len(data):
                return PhotoMechanicTrailerLocation(
                    payload_offset=payload_offset,
                    payload=data[payload_offset:size_offset],
                )
        signature_offset = data.find(PHOTO_MECHANIC_FOOTER_SIGNATURE, signature_offset + 1)
    return None


def rewrite_photo_mechanic_soft_edit_dataset(
    payload: bytes,
    dataset_id: int,
    replacement: bytes,
) -> bytes:
    rewritten = bytearray()
    position = 0
    replaced = False
    while position + 5 <= len(payload):
        if payload[position] != IPTC_DATASET_MARKER:
            rewritten.extend(payload[position:])
            break
        record_id = payload[position + 1]
        current_dataset_id = payload[position + 2]
        size = int.from_bytes(payload[position + 3 : position + 5], "big")
        value_offset = position + 5
        next_position = value_offset + size
        if next_position > len(payload):
            rewritten.extend(payload[position:])
            break
        if record_id == PHOTO_MECHANIC_SOFT_EDIT_RECORD and current_dataset_id == dataset_id:
            rewritten.extend(
                encode_iptc_dataset(
                    IptcApplicationDataset(
                        record_id=PHOTO_MECHANIC_SOFT_EDIT_RECORD,
                        dataset_id=dataset_id,
                        value=replacement,
                    )
                )
            )
            replaced = True
        else:
            rewritten.extend(payload[position:next_position])
        position = next_position
    if not replaced:
        rewritten.extend(
            encode_iptc_dataset(
                IptcApplicationDataset(
                    record_id=PHOTO_MECHANIC_SOFT_EDIT_RECORD,
                    dataset_id=dataset_id,
                    value=replacement,
                )
            )
        )
    return bytes(rewritten).rstrip(b"\x00")
