"""Pentax MOV user-data reader backed by QuickTime.pm's TAGS route."""

from __future__ import annotations

from dataclasses import dataclass

type QuickTimePentaxMovValue = str | int | float


@dataclass(frozen=True)
class QuickTimePentaxMovField:
    tag_id: str
    name: str
    value: QuickTimePentaxMovValue
    family_2_group: str


PENTAX_MOV_PREFIX = b"PENTAX DIGITAL CAMERA\x00"
PENTAX_MOV_WHITE_BALANCE = {
    0: "Auto",
    1: "Daylight",
    2: "Shade",
    3: "Fluorescent",
    4: "Tungsten",
    5: "Manual",
}


def parse_pentax_mov_user_data(payload: bytes) -> tuple[QuickTimePentaxMovField, ...]:
    """Parse Pentax MOV BinaryData from QuickTime UserData."""
    if not payload.startswith(PENTAX_MOV_PREFIX) or len(payload) < 0xB1:
        return ()
    fields: list[QuickTimePentaxMovField] = []
    make = _fixed_string(payload, 0x00, 24)
    if make:
        fields.append(QuickTimePentaxMovField("0x00", "Make", make, "Camera"))
    exposure_raw = _uint32_le(payload, 0x26)
    if exposure_raw is not None:
        fields.append(
            QuickTimePentaxMovField(
                "0x26",
                "ExposureTime",
                _exposure_time_text(exposure_raw),
                "Camera",
            )
        )
    f_number = _rational64u_le(payload, 0x2A)
    if f_number is not None:
        fields.append(QuickTimePentaxMovField("0x2a", "FNumber", round(f_number, 1), "Camera"))
    exposure_compensation = _rational64s_le(payload, 0x32)
    if exposure_compensation is not None:
        fields.append(
            QuickTimePentaxMovField(
                "0x32",
                "ExposureCompensation",
                0 if exposure_compensation == 0 else f"{exposure_compensation:+.1f}",
                "Camera",
            )
        )
    white_balance = _uint16_le(payload, 0x44)
    if white_balance is not None:
        fields.append(
            QuickTimePentaxMovField(
                "0x44",
                "WhiteBalance",
                PENTAX_MOV_WHITE_BALANCE.get(white_balance, white_balance),
                "Camera",
            )
        )
    focal_length = _rational64u_le(payload, 0x48)
    if focal_length is not None:
        fields.append(
            QuickTimePentaxMovField(
                "0x48",
                "FocalLength",
                f"{focal_length:.1f} mm",
                "Camera",
            )
        )
    iso = _uint16_le(payload, 0xAF)
    if iso is not None:
        fields.append(QuickTimePentaxMovField("0xaf", "ISO", iso, "Camera"))
    return tuple(fields)


def _fixed_string(payload: bytes, offset: int, size: int) -> str | None:
    if offset + size > len(payload):
        return None
    value = (
        payload[offset : offset + size]
        .split(b"\0", 1)[0]
        .decode(
            "latin-1",
            errors="replace",
        )
    )
    value = value.rstrip()
    return value or None


def _uint16_le(payload: bytes, offset: int) -> int | None:
    if offset + 2 > len(payload):
        return None
    return int.from_bytes(payload[offset : offset + 2], "little")


def _uint32_le(payload: bytes, offset: int) -> int | None:
    if offset + 4 > len(payload):
        return None
    return int.from_bytes(payload[offset : offset + 4], "little")


def _int32_le(payload: bytes, offset: int) -> int | None:
    if offset + 4 > len(payload):
        return None
    return int.from_bytes(payload[offset : offset + 4], "little", signed=True)


def _rational64u_le(payload: bytes, offset: int) -> float | None:
    numerator = _uint32_le(payload, offset)
    denominator = _uint32_le(payload, offset + 4)
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _rational64s_le(payload: bytes, offset: int) -> float | None:
    numerator = _int32_le(payload, offset)
    denominator = _int32_le(payload, offset + 4)
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _exposure_time_text(raw_value: int) -> str:
    if raw_value == 0:
        return "0"
    seconds = 10 / raw_value
    if 0 < seconds < 0.25001:
        denominator = int(0.5 + 1 / seconds)
        return f"1/{denominator}"
    return _compact_decimal(round(seconds, 1))


def _compact_decimal(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")
