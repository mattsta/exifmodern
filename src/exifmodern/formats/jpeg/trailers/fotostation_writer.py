"""JPEG FotoStation trailer mutation boundary."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.fotostation.reader import (
    FOTOSTATION_FOOTER_SIZE,
    FOTOSTATION_SIGNATURE,
    FOTOSTATION_SOFT_EDIT_TAG,
)
from exifmodern.formats.fotostation.write_plan import FotoStationRotationWritePlan

FOTOSTATION_ROTATION_ENTRY_INDEX = 4
FOTOSTATION_ENTRY_SIZE = 4


@dataclass(frozen=True)
class FotoStationRewriteResult:
    data: bytes
    changed: bool
    patched_offset: int | None


def rewrite_jpeg_fotostation_rotation(
    jpeg_data: bytes,
    plan: FotoStationRotationWritePlan,
) -> FotoStationRewriteResult:
    soft_edit = locate_fotostation_soft_edit_payload(jpeg_data)
    if soft_edit is None:
        raise ValueError("No JPEG FotoStation SoftEdit trailer found.")
    patch_offset = (
        soft_edit.payload_offset + FOTOSTATION_ROTATION_ENTRY_INDEX * FOTOSTATION_ENTRY_SIZE
    )
    if patch_offset + FOTOSTATION_ENTRY_SIZE > soft_edit.footer_offset:
        raise ValueError("FotoStation SoftEdit payload does not contain Rotation.")
    rewritten = bytearray(jpeg_data)
    rewritten[patch_offset : patch_offset + FOTOSTATION_ENTRY_SIZE] = (
        plan.raw_counter_clockwise_centidegrees.to_bytes(4, "big", signed=True)
    )
    data = bytes(rewritten)
    return FotoStationRewriteResult(
        data=data,
        changed=data != jpeg_data,
        patched_offset=patch_offset,
    )


@dataclass(frozen=True)
class FotoStationPayloadLocation:
    payload_offset: int
    footer_offset: int


def locate_fotostation_soft_edit_payload(data: bytes) -> FotoStationPayloadLocation | None:
    signature_offset = data.find(FOTOSTATION_SIGNATURE)
    while signature_offset >= 0:
        footer_offset = signature_offset - 6
        if footer_offset >= 0:
            tag_id = int.from_bytes(data[footer_offset : footer_offset + 2], "big")
            record_size = int.from_bytes(data[footer_offset + 2 : footer_offset + 6], "big")
            payload_size = record_size - FOTOSTATION_FOOTER_SIZE
            payload_offset = footer_offset - payload_size
            if (
                tag_id == FOTOSTATION_SOFT_EDIT_TAG
                and record_size >= FOTOSTATION_FOOTER_SIZE
                and payload_offset >= 0
            ):
                return FotoStationPayloadLocation(
                    payload_offset=payload_offset,
                    footer_offset=footer_offset,
                )
        signature_offset = data.find(FOTOSTATION_SIGNATURE, signature_offset + 1)
    return None
