"""Photoshop PSD image resource block parsing and encoding.

The writer rebuilds the Photoshop image resource directory from Image Resource
Blocks (IRBs): a 4-byte signature, 2-byte resource ID, even-padded Pascal name,
4-byte data size, data bytes, and an even data pad.
"""

from __future__ import annotations

from dataclasses import dataclass

type PhotoshopResourceId = int
type PhotoshopResourceName = bytes
type PhotoshopResourceSignature = bytes

PHOTOSHOP_IRB_SIGNATURES: tuple[PhotoshopResourceSignature, ...] = (
    b"8BIM",
    b"PHUT",
    b"DCSR",
    b"AgHg",
    b"MeSa",
)
PHOTOSHOP_WRITABLE_IRB_SIGNATURE = b"8BIM"


class PhotoshopImageResourceError(ValueError):
    """Raised when a Photoshop image resource section is malformed."""


@dataclass(frozen=True)
class PhotoshopImageResourceEntry:
    signature: PhotoshopResourceSignature
    resource_id: PhotoshopResourceId
    name: PhotoshopResourceName
    data: bytes


@dataclass(frozen=True)
class PhotoshopImageResourceBlock:
    signature: PhotoshopResourceSignature
    resource_id: PhotoshopResourceId
    name: PhotoshopResourceName
    data: bytes
    entry_start: int
    name_offset: int
    name_field_length: int
    data_offset: int
    data_end: int
    entry_end: int

    @property
    def data_size(self) -> int:
        return len(self.data)

    @property
    def data_padding_size(self) -> int:
        return self.entry_end - self.data_end

    @property
    def entry_length(self) -> int:
        return self.entry_end - self.entry_start

    @property
    def decoded_name(self) -> str:
        return self.name.decode("latin-1", errors="replace")

    def to_entry(self) -> PhotoshopImageResourceEntry:
        return PhotoshopImageResourceEntry(
            signature=self.signature,
            resource_id=self.resource_id,
            name=self.name,
            data=self.data,
        )


def parse_image_resource_blocks(
    resource_section: bytes,
    *,
    section_start: int = 0,
) -> tuple[PhotoshopImageResourceBlock, ...]:
    if section_start < 0:
        raise PhotoshopImageResourceError("Photoshop image resource section start is negative.")

    blocks: list[PhotoshopImageResourceBlock] = []
    position = 0
    section_end = len(resource_section)
    while position + 8 < section_end:
        if (position ^ section_start) & 0x01:
            position += 1
            if position + 8 >= section_end:
                break

        entry_start = position
        signature = resource_section[position : position + 4]
        validate_resource_signature(signature)
        resource_id = int.from_bytes(resource_section[position + 4 : position + 6], "big")
        name_offset = position + 6
        name, after_name, name_field_length = read_pascal_resource_name(
            resource_section,
            name_offset,
        )
        if after_name + 4 > section_end:
            raise PhotoshopImageResourceError("Bad Photoshop resource block.")

        data_size = int.from_bytes(resource_section[after_name : after_name + 4], "big")
        data_offset = after_name + 4
        data_end = data_offset + data_size
        if data_end > section_end:
            raise PhotoshopImageResourceError(f"Bad Photoshop resource data size {data_size}.")
        data_padding_size = 1 if data_size & 0x01 and data_end < section_end else 0
        entry_end = data_end + data_padding_size

        blocks.append(
            PhotoshopImageResourceBlock(
                signature=signature,
                resource_id=resource_id,
                name=name,
                data=resource_section[data_offset:data_end],
                entry_start=entry_start,
                name_offset=name_offset,
                name_field_length=name_field_length,
                data_offset=data_offset,
                data_end=data_end,
                entry_end=entry_end,
            )
        )
        position = entry_end
    return tuple(blocks)


def read_pascal_resource_name(payload: bytes, offset: int) -> tuple[bytes, int, int]:
    if offset >= len(payload):
        raise PhotoshopImageResourceError("Bad Photoshop resource block.")
    name_length = payload[offset]
    name_field_length = padded_pascal_resource_name_length(name_length)
    name_start = offset + 1
    name_end = name_start + name_length
    field_end = offset + name_field_length
    if field_end > len(payload):
        raise PhotoshopImageResourceError("Bad Photoshop resource block.")
    return payload[name_start:name_end], field_end, name_field_length


def encode_image_resource_entry(entry: PhotoshopImageResourceEntry) -> bytes:
    validate_resource_signature(entry.signature)
    validate_resource_id(entry.resource_id)
    if len(entry.data) > 0xFFFFFFFF:
        raise PhotoshopImageResourceError("Photoshop image resource data is too large.")
    data_padding = b"\x00" if len(entry.data) & 0x01 else b""
    return (
        entry.signature
        + entry.resource_id.to_bytes(2, "big")
        + encode_pascal_resource_name(entry.name)
        + len(entry.data).to_bytes(4, "big")
        + entry.data
        + data_padding
    )


def encode_image_resource_section(
    entries: tuple[PhotoshopImageResourceEntry, ...],
) -> bytes:
    return b"".join(encode_image_resource_entry(entry) for entry in entries)


def encode_pascal_resource_name(name: bytes) -> bytes:
    if len(name) > 255:
        raise PhotoshopImageResourceError("Photoshop resource names must fit in one Pascal byte.")
    raw = bytes((len(name),)) + name
    return raw + (b"\x00" if len(raw) & 0x01 else b"")


def encoded_image_resource_entry_length(entry: PhotoshopImageResourceEntry) -> int:
    return (
        10
        + padded_pascal_resource_name_length(len(entry.name))
        + len(entry.data)
        + (len(entry.data) & 0x01)
    )


def padded_pascal_resource_name_length(name_length: int) -> int:
    if name_length < 0 or name_length > 255:
        raise PhotoshopImageResourceError("Photoshop resource names must fit in one Pascal byte.")
    raw_length = 1 + name_length
    return raw_length + (raw_length & 0x01)


def validate_resource_signature(signature: bytes) -> None:
    if signature not in PHOTOSHOP_IRB_SIGNATURES:
        escaped = signature.decode("latin-1", errors="backslashreplace")
        raise PhotoshopImageResourceError(f'Bad Photoshop IRB resource "{escaped}".')


def validate_resource_id(resource_id: int) -> None:
    if resource_id < 0 or resource_id > 0xFFFF:
        raise PhotoshopImageResourceError("Photoshop image resource ID must fit in uint16.")
