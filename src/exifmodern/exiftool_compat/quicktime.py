"""QuickTime exact-helper compatibility adapters."""

from __future__ import annotations

import math

from exifmodern.exiftool_compat.binary import (
    binary_text_bytes,
    float32_little_endian,
    uint16_big_endian,
    uint16_little_endian,
    uint32_big_endian,
    uint32_little_endian,
)
from exifmodern.exiftool_compat.core import convert_unix_time
from exifmodern.exiftool_compat.types import (
    ExifToolContextUpdate,
    ExifToolEffectResult,
    ExifToolHashReference,
    ExifToolScalar,
    ExifToolScalarReference,
    ExifToolValue,
    hash_field,
    hash_reference_value,
    numeric_value,
    perl_numeric_text,
    perl_truthy,
    scalar_hash_field,
    scalar_reference_value,
    scalar_value,
    string_value,
)


def calc_rotation(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 1:
        return None
    exiftool_context = hash_reference_value(values[0], "QuickTime CalcRotation ExifTool context")
    value_record = hash_field(exiftool_context, "VALUE")
    if not isinstance(value_record, ExifToolHashReference):
        return None
    groups_record = hash_field(exiftool_context, "GROUPS")
    groups = groups_record if isinstance(groups_record, ExifToolHashReference) else None
    track = first_video_track(value_record, groups)
    if track is None:
        return None
    matrix = first_track_matrix(value_record, groups, track)
    if matrix is None:
        return None
    return rotation_angle(string_value(matrix))


def first_video_track(
    values: ExifToolHashReference,
    groups: ExifToolHashReference | None,
) -> str | None:
    index = 0
    while True:
        tag = indexed_tag_name("HandlerType", index)
        handler_type = scalar_hash_field(values, tag)
        if handler_type is None:
            return None
        if handler_type == "vide":
            return group_for_tag(groups, tag)
        index += 1


def first_track_matrix(
    values: ExifToolHashReference,
    groups: ExifToolHashReference | None,
    track: str,
) -> ExifToolScalar:
    index = 0
    while True:
        tag = indexed_tag_name("MatrixStructure", index)
        matrix = scalar_hash_field(values, tag)
        if matrix is None:
            return None
        if group_for_tag(groups, tag) == track:
            return matrix
        index += 1


def indexed_tag_name(name: str, index: int) -> str:
    return name if index == 0 else f"{name} ({index})"


def group_for_tag(groups: ExifToolHashReference | None, tag: str) -> str | None:
    if groups is None:
        return None
    group = scalar_hash_field(groups, tag)
    if group is None:
        return None
    return string_value(group)


def rotation_angle(matrix: str) -> float | None:
    values = [numeric_value(part) for part in matrix.split()]
    if len(values) < 2:
        return None
    if values[0] == 0 and values[1] == 0:
        return None
    angle = math.atan2(values[1], values[0]) * 180 / 3.14159
    if angle < 0:
        angle += 360
    return int(angle * 1000 + 0.5) / 1000


def calc_sample_rate(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 2:
        return None
    exiftool_context = hash_reference_value(values[0], "QuickTime CalcSampleRate ExifTool context")
    media_time_scale = scalar_hash_field(exiftool_context, "MediaTS")
    if not perl_truthy(media_time_scale):
        return None
    table_reference = scalar_reference_value(
        values[1],
        "QuickTime CalcSampleRate time-to-sample table",
    )
    words = big_endian_uint32_words(string_value(table_reference.value))
    sample_count = 0
    sample_duration = 0
    index = 2
    while index < len(words) - 1:
        sample_count += words[index]
        sample_duration += words[index] * words[index + 1]
        index += 2
    if sample_count == 0 or sample_duration == 0:
        return None
    return sample_count * numeric_value(media_time_scale) / sample_duration


def ar_drone_telemetry(values: list[ExifToolValue]) -> ExifToolValue:
    if len(values) != 2:
        return None
    exiftool_context = hash_reference_value(
        values[0],
        "QuickTime ARDroneTelemetry ExifTool context",
    )
    payload = string_value(scalar_value(values[1], "QuickTime ARDroneTelemetry payload"))
    if len(payload) < 12 or not quicktime_binary_option_enabled(exiftool_context):
        return ExifToolScalarReference(payload)
    data = binary_text_bytes(payload)
    record_length = uint16_big_endian(data, 2)
    if record_length <= 0:
        return ExifToolScalarReference("")
    rendered_lines: list[str] = []
    cursor = 12
    while cursor + record_length <= len(data):
        rendered_lines.append(ar_drone_telemetry_record(data, cursor, record_length))
        cursor += record_length
    return ExifToolScalarReference("".join(rendered_lines))


def free_payload_offsets(values: list[ExifToolValue]) -> ExifToolValue:
    if len(values) != 1:
        return ()
    payload = string_value(scalar_value(values[0], "QuickTime free payload"))
    data = binary_text_bytes(payload)
    if len(data) < 8:
        return None
    payload_length = uint32_big_endian(data, 4)
    if payload_length < 13 or payload_length + 4 > len(data):
        return None
    item_count = int((payload_length - 13) / 5)
    offsets: list[ExifToolScalar] = []
    cursor = 17
    for _ in range(item_count):
        if cursor + 5 > len(data):
            break
        offsets.append(uint32_little_endian(data, cursor + 1) / 1000)
        cursor += 5
    return tuple(offsets)


def camm6_timestamp(values: list[ExifToolValue]) -> ExifToolScalar:
    if len(values) != 2:
        return None
    exiftool_context = hash_reference_value(values[0], "QuickTime CAMM6 ExifTool context")
    timestamp = numeric_value(scalar_value(values[1], "QuickTime CAMM6 timestamp"))
    create_date = scalar_hash_field(exiftool_context, "CreateDate")
    create_date_value = numeric_value(create_date) if perl_truthy(create_date) else None
    if create_date_value is not None and create_date_value - timestamp > 24 * 3600 * 365 * 5:
        timestamp += 315964800
    converted = convert_unix_time([timestamp, 0, -6])
    return string_value(converted) + "Z"


def handler_type_update(values: list[ExifToolValue]) -> ExifToolEffectResult:
    if len(values) != 2:
        return ExifToolEffectResult(value=None)
    context = hash_reference_value(values[0], "QuickTime Handler ExifTool context")
    handler_type = string_value(scalar_value(values[1], "QuickTime handler type"))
    return ExifToolEffectResult(
        value=handler_type,
        context_updates=tuple(quicktime_handler_updates(context, handler_type)),
    )


def quicktime_handler_updates(
    context: ExifToolHashReference,
    handler_type: str,
) -> list[ExifToolContextUpdate]:
    updates: list[ExifToolContextUpdate] = []
    if handler_type not in {"alis", "url "}:
        updates.append(
            ExifToolContextUpdate(
                namespace="$$self",
                path=("HandlerType",),
                value=handler_type,
            )
        )
    path = hash_field(context, "PATH")
    if isinstance(path, tuple) and len(path) > 1 and path[-2] == "Media":
        updates.append(
            ExifToolContextUpdate(namespace="$$self", path=("MediaType",), value=handler_type)
        )
    updates.append(
        ExifToolContextUpdate(namespace="$$self", path=("HasHandler", handler_type), value=1)
    )
    return updates


def quicktime_binary_option_enabled(exiftool_context: ExifToolHashReference) -> bool:
    options = hash_field(exiftool_context, "OPTIONS")
    if not isinstance(options, ExifToolHashReference):
        return False
    return perl_truthy(scalar_hash_field(options, "Binary"))


def ar_drone_telemetry_record(data: list[int], cursor: int, record_length: int) -> str:
    status_1 = uint16_little_endian(data, cursor)
    status_2 = uint16_little_endian(data, cursor + 2)
    values = [f"{status_1} {status_2}"]
    value_count = int((record_length - 4) / 4)
    for index in range(value_count):
        value_cursor = cursor + 4 + index * 4
        if 0 < index < 4:
            values.append(perl_numeric_text(float32_little_endian(data, value_cursor)))
        else:
            raw_value = float(uint32_little_endian(data, value_cursor))
            if index <= 5:
                raw_value /= 1000
            values.append(perl_numeric_text(raw_value))
    return " ".join(values) + "\n"


def big_endian_uint32_words(value: str) -> list[int]:
    words: list[int] = []
    data = binary_text_bytes(value)
    index = 0
    while index + 4 <= len(value):
        words.append(uint32_big_endian(data, index))
        index += 4
    return words
