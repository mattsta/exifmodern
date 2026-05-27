"""Phase One compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.binary import (
    binary_text_bytes,
    float32_big_endian,
    float32_little_endian,
    uint16_big_endian,
    uint16_little_endian,
)
from exifmodern.exiftool_compat.types import (
    ExifToolScalar,
    ExifToolValue,
    perl_numeric_text,
    scalar_value,
    string_value,
)


def sensor_calibration(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 1:
        return None
    payload = string_value(scalar_value(values[0], "Phase One SensorCalibration payload"))
    if len(payload) < 8:
        return payload
    byte_order = payload[:2]
    if byte_order not in {"II", "MM"}:
        return payload
    data = binary_text_bytes(payload)
    int16_reader = uint16_little_endian if byte_order == "II" else uint16_big_endian
    float_reader = float32_little_endian if byte_order == "II" else float32_big_endian
    fields = [str(int16_reader(data, 2))]
    cursor = 4
    while cursor + 4 <= len(data):
        fields.append(perl_numeric_text(float_reader(data, cursor)))
        cursor += 4
    return " ".join(fields)
