"""Panasonic/Leica QuickTime PANA user-data reader."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PanasonicPanaField:
    name: str
    value: str | int
    tag_id: str
    family_2_group: str


@dataclass(frozen=True)
class PanasonicPanaEmbeddedExif:
    tiff_data: bytes
    tag_id: str


PANASONIC_PANA_EMBEDDED_EXIF_OFFSETS = (0x10, 0x4068, 0x4080, 0x200080)
PANASONIC_PANA_EMBEDDED_EXIF_SOURCE_EVIDENCE = (
    "../exiftool/lib/Image/ExifTool/Panasonic.pm Panasonic::PANA tags 0x10, "
    "0x4068, 0x4080, and 0x200080 route JPEG-like payloads matching "
    "FFD8 FFE1 .. Exif\\0\\0 to Exif::Main with ProcessTIFF Start => 12.",
)


def parse_panasonic_pana_user_data(
    payload: bytes,
    *,
    leica_atom: bool = False,
) -> tuple[PanasonicPanaField, ...]:
    """Extract ExifTool-defined fixed PANA/LEIC binary fields."""

    fields: list[PanasonicPanaField] = []
    leica = leica_atom
    make = _fixed_string(payload, 0x00, 22)
    if make.startswith(("LEICA", "Panasonic")):
        fields.append(PanasonicPanaField("Make", make, "0x00", "Camera"))
        leica = True
    if leica:
        model = _fixed_string(payload, 0x16, 30)
        if model:
            fields.append(PanasonicPanaField("Model", model, "0x16", "Camera"))
        version1 = _fixed_string(payload, 0x34, 14)
        if version1:
            fields.append(PanasonicPanaField("Version1", version1, "0x34", "Image"))
        version2 = _fixed_string(payload, 0x3E, 14)
        if version2:
            fields.append(PanasonicPanaField("Version2", version2, "0x3e", "Image"))
    else:
        model_field = _first_panasonic_model(payload)
        if model_field is not None:
            model, tag_id = model_field
            fields.append(PanasonicPanaField("Model", model, tag_id, "Camera"))
    thumb_type = _thumbnail_type(payload)
    if thumb_type == 1 and len(payload) >= 0x5C:
        fields.append(
            PanasonicPanaField("ThumbnailWidth", _uint16be(payload, 0x58), "0x58", "Preview")
        )
        fields.append(
            PanasonicPanaField("ThumbnailHeight", _uint16be(payload, 0x5A), "0x5a", "Preview")
        )
    elif thumb_type == 2 and len(payload) >= 0x542:
        fields.append(
            PanasonicPanaField("ThumbnailWidth", _uint32le(payload, 0x536), "0x536", "Preview")
        )
        fields.append(
            PanasonicPanaField("ThumbnailHeight", _uint32le(payload, 0x53A), "0x53a", "Preview")
        )
        fields.append(
            PanasonicPanaField("ThumbnailLength", _uint32le(payload, 0x53E), "0x53e", "Preview")
        )
    elif thumb_type == 3 and len(payload) >= 0x55A:
        fields.append(
            PanasonicPanaField("ThumbnailWidth", _uint32le(payload, 0x54E), "0x54e", "Preview")
        )
        fields.append(
            PanasonicPanaField("ThumbnailHeight", _uint32le(payload, 0x552), "0x552", "Preview")
        )
        fields.append(
            PanasonicPanaField("ThumbnailLength", _uint32le(payload, 0x556), "0x556", "Preview")
        )
    return tuple(fields)


def embedded_exif_from_panasonic_pana_user_data(
    payload: bytes,
) -> tuple[PanasonicPanaEmbeddedExif, ...]:
    embedded: list[PanasonicPanaEmbeddedExif] = []
    for offset in PANASONIC_PANA_EMBEDDED_EXIF_OFFSETS:
        tiff_data = _embedded_jpeg_exif_tiff_data(payload, offset)
        if tiff_data is not None:
            embedded.append(PanasonicPanaEmbeddedExif(tiff_data, f"0x{offset:x}"))
    return tuple(embedded)


def _first_panasonic_model(payload: bytes) -> tuple[str, str] | None:
    for offset, tag_id in ((0x04, "0x04"), (0x0C, "0x0c")):
        value = _fixed_string(payload, offset, 16)
        if len(value) >= 6:
            return value, tag_id
    return None


def _thumbnail_type(payload: bytes) -> int:
    if payload[0x5C:0x5F] == b"\xff\xd8\xff":
        return 1
    if payload[0x546:0x549] == b"\xff\xd8\xff":
        return 2
    if payload[0x55E:0x561] == b"\xff\xd8\xff":
        return 3
    return 0


def _fixed_string(payload: bytes, offset: int, size: int) -> str:
    if len(payload) < offset + size:
        return ""
    return (
        payload[offset : offset + size]
        .split(b"\0", 1)[0]
        .decode("latin-1", errors="replace")
        .strip()
    )


def _uint16be(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset : offset + 2], "big")


def _uint32le(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset : offset + 4], "little")


def _embedded_jpeg_exif_tiff_data(payload: bytes, offset: int) -> bytes | None:
    if len(payload) < offset + 12:
        return None
    marker = payload[offset : offset + 4]
    if marker != b"\xff\xd8\xff\xe1":
        return None
    segment_length = int.from_bytes(payload[offset + 4 : offset + 6], "big")
    segment_end = offset + 4 + segment_length
    tiff_start = offset + 12
    if segment_length < 8 or segment_end > len(payload):
        return None
    if payload[offset + 6 : offset + 12] != b"Exif\0\0":
        return None
    return payload[tiff_start:segment_end]
