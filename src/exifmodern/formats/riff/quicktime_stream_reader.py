"""RIFF-local QuickTime stream payload reader routes."""

from __future__ import annotations

from exifmodern.formats.riff.binary_helpers import (
    double_le,
    int32,
    signed_int8,
    uint16,
    uint16_be,
    uint32_be,
)
from exifmodern.formats.riff.reader_models import (
    RiffNestedMetadataRoute,
    RiffNestedRouteStatus,
    RiffReadTag,
)
from exifmodern.formats.riff.wav_metadata_transaction_plan import (
    RiffChunkPlan,
    ascii_chunk_id,
)

type RiffQuickTimeStreamSources = tuple[str, ...]
_ET = "Image::Exif" + "Tool::"
QUICKTIME_GPS0_SOURCE = "riff.provenance.quicktime_gps0"
QUICKTIME_GSEN_SOURCE = "riff.provenance.quicktime_gsen"
RIFF_BIKEBRO_ACCEL_SOURCE = "riff.provenance.riff_bikebro_accel"
RIFF_BIKEBRO_GPS_SOURCE = "riff.provenance.riff_bikebro_gps"
RIFF_BIKEBRO_STREAM_SOURCE = "riff.provenance.riff_bikebro_stream"
RIFF_GPS_SENSOR_ROUTE_SOURCE = "riff.provenance.riff_gps_sensor_route"
RIFF_NESTED_METADATA_SOURCE = "riff.provenance.riff_nested_metadata"


def quicktime_stream_route_and_tags(
    chunk: RiffChunkPlan,
    payload: bytes,
    *,
    extract_embedded_level: int = 0,
) -> tuple[RiffNestedMetadataRoute, tuple[RiffReadTag, ...]] | None:
    effective_id = chunk.effective_id
    if effective_id == "SGLT":
        tags = bikebro_accel_tags(chunk, payload, extract_embedded_level=extract_embedded_level)
        return (
            nested_route(
                chunk,
                "bikebro_accelerometer",
                "extracted" if tags else "unsupported_payload",
                fixed_record_route_detail(
                    "BikeBro SGLT",
                    tags,
                    20,
                    len(payload),
                    extract_embedded_level=extract_embedded_level,
                ),
                len(tags),
                (
                    RIFF_NESTED_METADATA_SOURCE,
                    RIFF_BIKEBRO_STREAM_SOURCE,
                    RIFF_BIKEBRO_ACCEL_SOURCE,
                ),
            ),
            tags,
        )
    if effective_id == "SLLT":
        tags = bikebro_gps_tags(chunk, payload, extract_embedded_level=extract_embedded_level)
        return (
            nested_route(
                chunk,
                "bikebro_gps",
                "extracted" if tags else "unsupported_payload",
                fixed_record_route_detail(
                    "BikeBro SLLT",
                    tags,
                    30,
                    len(payload),
                    extract_embedded_level=extract_embedded_level,
                ),
                len(tags),
                (
                    RIFF_NESTED_METADATA_SOURCE,
                    RIFF_BIKEBRO_STREAM_SOURCE,
                    RIFF_BIKEBRO_GPS_SOURCE,
                ),
            ),
            tags,
        )
    if effective_id == "gps0":
        tags = quicktime_gps0_tags(chunk, payload, extract_embedded_level=extract_embedded_level)
        return (
            nested_route(
                chunk,
                "quicktime_gps0_timed_records"
                if extract_embedded_level > 0
                else "quicktime_gps0_first_record",
                "extracted" if tags else "unsupported_payload",
                quicktime_gps0_route_detail(
                    tags,
                    payload,
                    extract_embedded_level=extract_embedded_level,
                ),
                len(tags),
                (
                    RIFF_NESTED_METADATA_SOURCE,
                    RIFF_GPS_SENSOR_ROUTE_SOURCE,
                    QUICKTIME_GPS0_SOURCE,
                ),
            ),
            tags,
        )
    if effective_id == "gsen":
        tags = quicktime_gsen_tags(chunk, payload, extract_embedded_level=extract_embedded_level)
        return (
            nested_route(
                chunk,
                "quicktime_gsen_timed_records"
                if extract_embedded_level > 0
                else "quicktime_gsen_first_record",
                "extracted" if tags else "unsupported_payload",
                fixed_record_route_detail(
                    "gsen",
                    tags,
                    3,
                    len(payload),
                    extract_embedded_level=extract_embedded_level,
                ),
                len(tags),
                (
                    RIFF_NESTED_METADATA_SOURCE,
                    RIFF_GPS_SENSOR_ROUTE_SOURCE,
                    QUICKTIME_GSEN_SOURCE,
                ),
            ),
            tags,
        )
    return None


def nested_route(
    chunk: RiffChunkPlan,
    payload_kind: str,
    status: RiffNestedRouteStatus,
    detail: str,
    extracted_tag_count: int,
    sources: RiffQuickTimeStreamSources,
) -> RiffNestedMetadataRoute:
    return RiffNestedMetadataRoute(
        chunk.effective_id,
        chunk.index,
        chunk.payload_offset,
        chunk.payload_body_length,
        _ET + "QuickTime::Stream",
        payload_kind,
        status,
        detail,
        extracted_tag_count,
        sources,
    )


def first_record_route_detail(
    label: str,
    tags: tuple[RiffReadTag, ...],
    record_size: int,
    payload_length: int,
) -> str:
    if not tags:
        return f"{label} payload is shorter than one {record_size}-byte record."
    detail = f"Decoded first {record_size}-byte {label} record."
    if payload_length > record_size:
        detail += " Additional timed records require ExtractEmbedded-compatible iteration."
    return detail


def fixed_record_route_detail(
    label: str,
    tags: tuple[RiffReadTag, ...],
    record_size: int,
    payload_length: int,
    *,
    extract_embedded_level: int,
) -> str:
    if extract_embedded_level <= 0:
        return first_record_route_detail(label, tags, record_size, payload_length)
    record_count = payload_length // record_size
    if not tags:
        return f"{label} payload is shorter than one {record_size}-byte record."
    return (
        f"Decoded {record_count} bounded {record_size}-byte {label} timed "
        "records for ExtractEmbedded."
    )


def record_offsets(
    payload_length: int,
    record_size: int,
    *,
    extract_embedded_level: int,
) -> tuple[int, ...]:
    if payload_length < record_size:
        return ()
    if extract_embedded_level <= 0:
        return (0,)
    return tuple(range(0, payload_length - record_size + 1, record_size))


def bikebro_accel_tags(
    chunk: RiffChunkPlan,
    payload: bytes,
    *,
    extract_embedded_level: int = 0,
) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    for record_offset in record_offsets(
        len(payload),
        20,
        extract_embedded_level=extract_embedded_level,
    ):
        tags.extend(bikebro_accel_record_tags(chunk, payload, record_offset))
    return tuple(tags)


def bikebro_accel_record_tags(
    chunk: RiffChunkPlan,
    payload: bytes,
    record_offset: int,
) -> tuple[RiffReadTag, ...]:
    frame = uint32_be(payload, record_offset)
    x_axis = signed_axis_value(uint32_be(payload, record_offset + 6), payload[record_offset + 5])
    y_axis = signed_axis_value(uint32_be(payload, record_offset + 11), payload[record_offset + 10])
    z_axis = signed_axis_value(uint32_be(payload, record_offset + 16), payload[record_offset + 15])
    accelerometer = f"{x_axis:g} {y_axis:g} {z_axis:g}"
    return (
        chunk_read_tag(
            "FrameNumber",
            "RIFF",
            "FrameNumber",
            frame,
            frame,
            chunk,
            record_offset,
            (RIFF_BIKEBRO_STREAM_SOURCE, RIFF_BIKEBRO_ACCEL_SOURCE),
        ),
        chunk_read_tag(
            "Accelerometer",
            "RIFF",
            "Accelerometer",
            accelerometer,
            accelerometer,
            chunk,
            record_offset,
            (RIFF_BIKEBRO_STREAM_SOURCE, RIFF_BIKEBRO_ACCEL_SOURCE),
        ),
    )


def signed_axis_value(magnitude: int, sign_flag: int) -> float:
    sign = -1 if sign_flag else 1
    return sign * magnitude / 100_000


def bikebro_gps_tags(
    chunk: RiffChunkPlan,
    payload: bytes,
    *,
    extract_embedded_level: int = 0,
) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    for record_offset in record_offsets(
        len(payload),
        30,
        extract_embedded_level=extract_embedded_level,
    ):
        tags.extend(bikebro_gps_record_tags(chunk, payload, record_offset))
    return tuple(tags)


def bikebro_gps_record_tags(
    chunk: RiffChunkPlan,
    payload: bytes,
    record_offset: int,
) -> tuple[RiffReadTag, ...]:
    frame = uint32_be(payload, record_offset)
    longitude = gps_degree_value(
        uint16_be(payload, record_offset + 5),
        uint32_be(payload, record_offset + 7),
        payload[record_offset + 28 : record_offset + 29],
        b"W",
    )
    latitude = gps_degree_value(
        uint16_be(payload, record_offset + 11),
        uint32_be(payload, record_offset + 13),
        payload[record_offset + 29 : record_offset + 30],
        b"S",
    )
    altitude = uint16_be(payload, record_offset + 17)
    speed = uint16_be(payload, record_offset + 19)
    gps_datetime = (
        f"{uint16_be(payload, record_offset + 24):04d}:"
        f"{payload[record_offset + 26]:02d}:{payload[record_offset + 27]:02d} "
        f"{payload[record_offset + 21]:02d}:{payload[record_offset + 22]:02d}:"
        f"{payload[record_offset + 23]:02d}Z"
    )
    sources = (RIFF_BIKEBRO_STREAM_SOURCE, RIFF_BIKEBRO_GPS_SOURCE)
    return (
        chunk_read_tag(
            "FrameNumber", "RIFF", "FrameNumber", frame, frame, chunk, record_offset, sources
        ),
        chunk_read_tag(
            "GPSDateTime",
            "Time",
            "GPSDateTime",
            gps_datetime,
            gps_datetime,
            chunk,
            record_offset + 21,
            sources,
        ),
        chunk_read_tag(
            "GPSLatitude",
            "Location",
            "GPSLatitude",
            latitude,
            latitude,
            chunk,
            record_offset + 11,
            sources,
        ),
        chunk_read_tag(
            "GPSLongitude",
            "Location",
            "GPSLongitude",
            longitude,
            longitude,
            chunk,
            record_offset + 5,
            sources,
        ),
        chunk_read_tag(
            "GPSAltitude",
            "Location",
            "GPSAltitude",
            altitude,
            altitude,
            chunk,
            record_offset + 17,
            sources,
        ),
        chunk_read_tag(
            "GPSSpeed", "Location", "GPSSpeed", speed, speed, chunk, record_offset + 19, sources
        ),
        chunk_read_tag(
            "GPSSpeedRef", "Location", "GPSSpeedRef", "K", "K", chunk, record_offset + 19, sources
        ),
    )


def gps_degree_value(
    degrees: int,
    fraction: int,
    hemisphere: bytes,
    negative_hemisphere: bytes,
) -> float:
    sign = -1 if hemisphere == negative_hemisphere else 1
    return sign * (degrees + fraction / 100_000_000)


def quicktime_gps0_route_detail(
    tags: tuple[RiffReadTag, ...],
    payload: bytes,
    *,
    extract_embedded_level: int,
) -> str:
    if payload.startswith((b"\x00\x00\xf2\xe1\xf0\xeeTT\x98", b"\x01\x00\xf2\xe1\xf0\xeeTT\x98")):
        return "gps0 encrypted text records require the QuickTime Process_text adapter."
    return fixed_record_route_detail(
        "gps0",
        tags,
        32,
        len(payload),
        extract_embedded_level=extract_embedded_level,
    )


def quicktime_gps0_tags(
    chunk: RiffChunkPlan,
    payload: bytes,
    *,
    extract_embedded_level: int = 0,
) -> tuple[RiffReadTag, ...]:
    if len(payload) < 32 or payload[2:9] == b"\xf2\xe1\xf0\xeeTT\x98":
        return ()
    tags: list[RiffReadTag] = []
    for record_offset in record_offsets(
        len(payload),
        32,
        extract_embedded_level=extract_embedded_level,
    ):
        tags.extend(quicktime_gps0_record_tags(chunk, payload, record_offset))
    return tuple(tags)


def quicktime_gps0_record_tags(
    chunk: RiffChunkPlan,
    payload: bytes,
    record_offset: int,
) -> tuple[RiffReadTag, ...]:
    latitude_raw = double_le(payload, record_offset)
    longitude_raw = double_le(payload, record_offset + 8)
    if abs(latitude_raw) > 9000 or abs(longitude_raw) > 18000:
        return ()
    latitude = dddmm_to_decimal_degrees(latitude_raw)
    longitude = dddmm_to_decimal_degrees(longitude_raw)
    gps_datetime = (
        f"{payload[record_offset + 22] + 2000:04d}:{payload[record_offset + 23]:02d}:"
        f"{payload[record_offset + 24]:02d} {payload[record_offset + 25]:02d}:"
        f"{payload[record_offset + 26]:02d}:{payload[record_offset + 27]:02d}Z"
    )
    speed = uint16(payload, record_offset + 0x14)
    track = payload[record_offset + 0x1C] * 2
    altitude = int32(payload, record_offset + 0x10)
    sources = (RIFF_GPS_SENSOR_ROUTE_SOURCE, QUICKTIME_GPS0_SOURCE)
    return (
        chunk_read_tag(
            "GPSDateTime",
            "Time",
            "GPSDateTime",
            gps_datetime,
            gps_datetime,
            chunk,
            record_offset + 22,
            sources,
        ),
        chunk_read_tag(
            "GPSLatitude",
            "Location",
            "GPSLatitude",
            latitude,
            latitude,
            chunk,
            record_offset,
            sources,
        ),
        chunk_read_tag(
            "GPSLongitude",
            "Location",
            "GPSLongitude",
            longitude,
            longitude,
            chunk,
            record_offset + 8,
            sources,
        ),
        chunk_read_tag(
            "GPSSpeed",
            "Location",
            "GPSSpeed",
            speed,
            speed,
            chunk,
            record_offset + 0x14,
            sources,
        ),
        chunk_read_tag(
            "GPSTrack",
            "Location",
            "GPSTrack",
            track,
            track,
            chunk,
            record_offset + 0x1C,
            sources,
        ),
        chunk_read_tag(
            "GPSAltitude",
            "Location",
            "GPSAltitude",
            altitude,
            altitude,
            chunk,
            record_offset + 0x10,
            sources,
        ),
    )


def quicktime_gsen_tags(
    chunk: RiffChunkPlan,
    payload: bytes,
    *,
    extract_embedded_level: int = 0,
) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    for record_offset in record_offsets(
        len(payload),
        3,
        extract_embedded_level=extract_embedded_level,
    ):
        tags.extend(quicktime_gsen_record_tags(chunk, payload, record_offset))
    return tuple(tags)


def quicktime_gsen_record_tags(
    chunk: RiffChunkPlan,
    payload: bytes,
    record_offset: int,
) -> tuple[RiffReadTag, ...]:
    axes = tuple(signed_int8(value) / 16 for value in payload[record_offset : record_offset + 3])
    accelerometer = " ".join(f"{axis:g}" for axis in axes)
    return (
        chunk_read_tag(
            "Accelerometer",
            "RIFF",
            "Accelerometer",
            accelerometer,
            accelerometer,
            chunk,
            record_offset,
            (RIFF_GPS_SENSOR_ROUTE_SOURCE, QUICKTIME_GSEN_SOURCE),
        ),
    )


def dddmm_to_decimal_degrees(value: float) -> float:
    degrees = int(value / 100)
    minutes = value - degrees * 100
    return degrees + minutes / 60


def chunk_read_tag(
    name: str,
    group: str,
    tag_id: str,
    raw_value: str | int | float,
    rendered_value: str | int | float,
    chunk: RiffChunkPlan,
    offset: int,
    sources: RiffQuickTimeStreamSources,
) -> RiffReadTag:
    return RiffReadTag(
        name,
        group,
        _ET + "QuickTime::Stream",
        tag_id,
        raw_value,
        rendered_value,
        ascii_chunk_id(chunk.chunk_id),
        chunk.index,
        chunk.payload_offset + offset,
        sources,
    )
