"""Reusable JPEG 2000-family box parsing and encoding primitives."""

from __future__ import annotations

from dataclasses import dataclass

JP2_BOX_HEADER_SIZE = 8
JP2_EXTENDED_BOX_HEADER_SIZE = 16


@dataclass(frozen=True)
class Jp2Box:
    box_type: str
    payload: bytes


def read_jp2_boxes(data: bytes) -> tuple[Jp2Box, ...]:
    boxes: list[Jp2Box] = []
    offset = 0
    while offset < len(data):
        box, next_offset = read_jp2_box(data, offset)
        boxes.append(box)
        offset = next_offset
    return tuple(boxes)


def read_jp2_box(data: bytes, offset: int) -> tuple[Jp2Box, int]:
    if offset + JP2_BOX_HEADER_SIZE > len(data):
        raise ValueError("Truncated JPEG 2000 box header.")
    box_size = int.from_bytes(data[offset : offset + 4], "big")
    box_type = data[offset + 4 : offset + 8].decode("latin-1")
    if box_size == 0:
        box_end = len(data)
        payload_offset = offset + JP2_BOX_HEADER_SIZE
    elif box_size == 1:
        if offset + JP2_EXTENDED_BOX_HEADER_SIZE > len(data):
            raise ValueError("Truncated JPEG 2000 extended box header.")
        extended_size = int.from_bytes(data[offset + 8 : offset + 16], "big")
        if extended_size > 0xFFFFFFFF:
            raise ValueError("JPEG 2000 boxes larger than 4 GB are not supported.")
        box_end = offset + extended_size
        payload_offset = offset + JP2_EXTENDED_BOX_HEADER_SIZE
    else:
        box_end = offset + box_size
        payload_offset = offset + JP2_BOX_HEADER_SIZE
    if box_end < payload_offset or box_end > len(data):
        raise ValueError(f"Invalid JPEG 2000 box length for {box_type!r}.")
    return Jp2Box(box_type=box_type, payload=data[payload_offset:box_end]), box_end


def encode_jp2_box(box_type: str, payload: bytes) -> bytes:
    if len(box_type) != 4:
        raise ValueError("JPEG 2000 box types must be four characters.")
    box_size = len(payload) + JP2_BOX_HEADER_SIZE
    if box_size > 0xFFFFFFFF:
        raise ValueError("JPEG 2000 boxes larger than 4 GB are not supported.")
    return box_size.to_bytes(4, "big") + box_type.encode("latin-1") + payload


def encode_jp2_boxes(boxes: tuple[Jp2Box, ...]) -> bytes:
    return b"".join(encode_jp2_box(box.box_type, box.payload) for box in boxes)
