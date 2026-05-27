"""Minimal TIFF/EXIF parsing utilities for early JPEG APP1 read slices."""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal, Protocol

from exifmodern.json_types import JsonObject, JsonValue

type Endian = Literal["little", "big"]
type TagId = int
type TiffFieldType = int
type TiffValue = int | str | bytes | Fraction | list[int] | list[Fraction | None] | None
type NumericTiffValue = int | Fraction
type TagNameMap = dict[TagId, str]
type DecodedTags = JsonObject
type IfdContextName = Literal[
    "IFD0",
    "IFD1",
    "IFD2",
    "ExifIFD",
    "GPS",
    "SubIFD",
    "SubIFD1",
    "SubIFD2",
]
type TiffTraversalStatus = Literal["traversal_primitives_ready"]
type TiffBinaryProducerReadinessStatus = Literal["traversal_ready_extraction_deferred"]
type EmbeddedImageDataTag = Literal["ThumbnailImage", "JpgFromRaw", "OtherImage"]
type EmbeddedImageReadinessStatus = Literal[
    "pair_present_extraction_deferred",
    "missing_start",
    "missing_length",
    "missing_start_and_length",
]
type EmbeddedImageMaterializationStatus = Literal[
    "extracted",
    "missing_start",
    "missing_length",
    "missing_start_and_length",
    "zero_length",
    "negative_start",
    "negative_length",
    "negative_exif_data_pos",
    "out_of_buffer_or_file_relative",
    "out_of_file_bounds",
]
type TiffPointerKind = Literal["next_ifd", "subifd_pointer", "exif_ifd_pointer", "gps_ifd_pointer"]


class TiffFileByteSource(Protocol):
    @property
    def size(self) -> int: ...

    def read_at(self, offset: int, byte_count: int) -> bytes: ...


TIFF_TYPE_BYTE = 1
TIFF_TYPE_ASCII = 2
TIFF_TYPE_SHORT = 3
TIFF_TYPE_LONG = 4
TIFF_TYPE_RATIONAL = 5
TIFF_TYPE_UNDEFINED = 7
TIFF_TYPE_SLONG = 9
TIFF_TYPE_SRATIONAL = 10
TIFF_TYPE_DOUBLE = 12

TYPE_SIZES = {
    TIFF_TYPE_BYTE: 1,
    TIFF_TYPE_ASCII: 1,
    TIFF_TYPE_SHORT: 2,
    TIFF_TYPE_LONG: 4,
    TIFF_TYPE_RATIONAL: 8,
    TIFF_TYPE_UNDEFINED: 1,
    TIFF_TYPE_SLONG: 4,
    TIFF_TYPE_SRATIONAL: 8,
    TIFF_TYPE_DOUBLE: 8,
}

IFD0_TAGS = {
    0x010E: "ImageDescription",
    0x010F: "Make",
    0x0110: "Model",
    0x0112: "Orientation",
    0x011A: "XResolution",
    0x011B: "YResolution",
    0x0128: "ResolutionUnit",
    0x0131: "Software",
    0x0132: "ModifyDate",
    0x013B: "Artist",
    0x013C: "HostComputer",
    0x0213: "YCbCrPositioning",
    0x0214: "ReferenceBlackWhite",
    0x8769: "ExifIFDPointer",
    0x8825: "GPSInfoIFDPointer",
    0x8298: "Copyright",
}

IFD1_TAGS = {
    0x0103: "Compression",
    0x0112: "Orientation",
    0x011A: "XResolution",
    0x011B: "YResolution",
    0x0128: "ResolutionUnit",
    0x0213: "YCbCrPositioning",
    0x0201: "ThumbnailOffset",
    0x0202: "ThumbnailLength",
}

EXIF_IFD_TAGS = {
    0x829A: "ExposureTime",
    0x829D: "FNumber",
    0x8822: "ExposureProgram",
    0x8827: "ISO",
    0x8830: "SensitivityType",
    0x8831: "StandardOutputSensitivity",
    0x9000: "ExifVersion",
    0x9010: "OffsetTime",
    0x9011: "OffsetTimeOriginal",
    0x9012: "OffsetTimeDigitized",
    0x9003: "DateTimeOriginal",
    0x9004: "CreateDate",
    0x9101: "ComponentsConfiguration",
    0x9102: "CompressedBitsPerPixel",
    0x9201: "ShutterSpeedValue",
    0x9202: "ApertureValue",
    0x9203: "BrightnessValue",
    0x9204: "ExposureCompensation",
    0x9205: "MaxApertureValue",
    0x9207: "MeteringMode",
    0x9208: "LightSource",
    0x9209: "Flash",
    0x920D: "Noise",
    0x920A: "FocalLength",
    0x9214: "SubjectArea",
    0x9286: "UserComment",
    0x9290: "SubSecTime",
    0x9291: "SubSecTimeOriginal",
    0x9292: "SubSecTimeDigitized",
    0xA000: "FlashpixVersion",
    0xA001: "ColorSpace",
    0xA002: "ExifImageWidth",
    0xA003: "ExifImageHeight",
    0xA20E: "FocalPlaneXResolution",
    0xA20F: "FocalPlaneYResolution",
    0xA210: "FocalPlaneResolutionUnit",
    0xA217: "SensingMethod",
    0xA406: "SceneCaptureType",
    0xA300: "FileSource",
    0xA301: "SceneType",
    0xA401: "CustomRendered",
    0xA402: "ExposureMode",
    0xA403: "WhiteBalance",
    0xA404: "DigitalZoomRatio",
    0xA405: "FocalLengthIn35mmFormat",
    0xA432: "LensInfo",
    0xA433: "LensMake",
    0xA434: "LensModel",
    0xA407: "GainControl",
    0xA408: "Contrast",
    0xA409: "Saturation",
    0xA40A: "Sharpness",
    0xA430: "OwnerName",
    0xA431: "SerialNumber",
    0x9405: "CameraElevationAngle",
}

GPS_IFD_TAGS = {
    0x0000: "GPSVersionID",
    0x0001: "GPSLatitudeRef",
    0x0002: "GPSLatitude",
    0x0003: "GPSLongitudeRef",
    0x0004: "GPSLongitude",
    0x0005: "GPSAltitudeRef",
    0x0006: "GPSAltitude",
    0x0007: "GPSTimeStamp",
    0x000A: "GPSMeasureMode",
    0x000B: "GPSDOP",
    0x000C: "GPSSpeedRef",
    0x000D: "GPSSpeed",
    0x000E: "GPSTrackRef",
    0x000F: "GPSTrack",
    0x0010: "GPSImgDirectionRef",
    0x0011: "GPSImgDirection",
    0x0012: "GPSMapDatum",
    0x0017: "GPSDestBearingRef",
    0x0018: "GPSDestBearing",
    0x001D: "GPSDateStamp",
    0x001F: "GPSHPositioningError",
}

ORIENTATION_PRINT = {
    1: "Horizontal (normal)",
    2: "Mirror horizontal",
    3: "Rotate 180",
    4: "Mirror vertical",
    5: "Mirror horizontal and rotate 270 CW",
    6: "Rotate 90 CW",
    7: "Mirror horizontal and rotate 90 CW",
    8: "Rotate 270 CW",
}

RESOLUTION_UNIT_PRINT = {
    1: "None",
    2: "inches",
    3: "cm",
}

COLOR_SPACE_PRINT = {
    1: "sRGB",
    0xFFFF: "Uncalibrated",
}

EXPOSURE_PROGRAM_PRINT = {
    0: "Not Defined",
    1: "Manual",
    2: "Program AE",
    3: "Aperture-priority AE",
    4: "Shutter speed priority AE",
    5: "Creative (Slow speed)",
    6: "Action (High speed)",
    7: "Portrait",
    8: "Landscape",
}

SENSITIVITY_TYPE_PRINT = {
    0: "Unknown",
    1: "Standard Output Sensitivity",
    2: "Recommended Exposure Index",
    3: "ISO Speed",
    4: "Standard Output Sensitivity and Recommended Exposure Index",
    5: "Standard Output Sensitivity and ISO Speed",
    6: "Recommended Exposure Index and ISO Speed",
    7: "Standard Output Sensitivity, Recommended Exposure Index and ISO Speed",
}

METERING_MODE_PRINT = {
    0: "Unknown",
    1: "Average",
    2: "Center-weighted average",
    3: "Spot",
    4: "Multi-spot",
    5: "Multi-segment",
    6: "Partial",
    255: "Other",
}

LIGHT_SOURCE_PRINT = {
    0: "Unknown",
    1: "Daylight",
    2: "Fluorescent",
    3: "Tungsten (Incandescent)",
    4: "Flash",
    9: "Fine Weather",
    10: "Cloudy",
    11: "Shade",
    12: "Daylight Fluorescent",
    13: "Day White Fluorescent",
    14: "Cool White Fluorescent",
    15: "White Fluorescent",
    17: "Standard Light A",
    18: "Standard Light B",
    19: "Standard Light C",
    20: "D55",
    21: "D65",
    22: "D75",
    23: "D50",
    24: "ISO Studio Tungsten",
    255: "Other",
}

GAIN_CONTROL_PRINT = {
    0: "None",
    1: "Low gain up",
    2: "High gain up",
    3: "Low gain down",
    4: "High gain down",
}

NORMAL_LOW_HIGH_PRINT = {
    0: "Normal",
    1: "Low",
    2: "High",
}

SHARPNESS_PRINT = {
    0: "Normal",
    1: "Soft",
    2: "Hard",
}

FLASH_PRINT = {
    0x0000: "No Flash",
    0x0001: "Fired",
    0x0005: "Fired, Return not detected",
    0x0007: "Fired, Return detected",
    0x0008: "On, Did not fire",
    0x0009: "On, Fired",
    0x000D: "On, Return not detected",
    0x000F: "On, Return detected",
    0x0010: "Off, Did not fire",
    0x0018: "Auto, Did not fire",
    0x0019: "Auto, Fired",
    0x001D: "Auto, Fired, Return not detected",
    0x001F: "Auto, Fired, Return detected",
    0x0020: "No flash function",
    0x0041: "Fired, Red-eye reduction",
}

COMPRESSION_PRINT = {
    1: "Uncompressed",
    6: "JPEG (old-style)",
}

YCBCR_POSITIONING_PRINT = {
    1: "Centered",
    2: "Co-sited",
}

SENSING_METHOD_PRINT = {
    1: "Not defined",
    2: "One-chip color area",
    3: "Two-chip color area",
    4: "Three-chip color area",
    5: "Color sequential area",
    7: "Trilinear",
    8: "Color sequential linear",
}

SCENE_CAPTURE_TYPE_PRINT = {
    0: "Standard",
    1: "Landscape",
    2: "Portrait",
    3: "Night",
    4: "Other",
}

FILE_SOURCE_PRINT = {
    0: "Unknown (0)",
    3: "Digital Camera",
}

SCENE_TYPE_PRINT = {
    0: "Unknown (0)",
    1: "Directly photographed",
}

CUSTOM_RENDERED_PRINT = {
    0: "Normal",
    1: "Custom",
}

EXPOSURE_MODE_PRINT = {
    0: "Auto",
    1: "Manual",
    2: "Auto bracket",
}

WHITE_BALANCE_PRINT = {
    0: "Auto",
    1: "Manual",
}

COMPONENT_CONFIGURATION_PRINT = {
    0: "-",
    1: "Y",
    2: "Cb",
    3: "Cr",
    4: "R",
    5: "G",
    6: "B",
}

GPS_ALTITUDE_REF_PRINT = {
    0: "Above Sea Level",
    1: "Below Sea Level",
    2: "Positive Sea Level (sea-level ref)",
    3: "Negative Sea Level (sea-level ref)",
}

GPS_SPEED_REF_PRINT = {
    "K": "km/h",
    "M": "mph",
    "N": "knots",
}

GPS_NORTH_REF_PRINT = {
    "M": "Magnetic North",
    "T": "True North",
}

BINARY_IMAGE_TAG_IDS = (0x0201, 0x0202)
MAX_KNOWN_IFD_CHAIN_DEPTH = 3
MAX_SUBIFD_POINTERS = 10
EMBEDDED_IMAGE_MATERIALIZER_SOURCE_ANCHORS = (
    "lib/Image/ExifTool/Exif.pm:4967-4991 ThumbnailImage Require "
    "ThumbnailOffset/ThumbnailLength and ExtractImage RawConv",
    "lib/Image/ExifTool/Exif.pm:5059-5082 JpgFromRaw Require "
    "JpgFromRawStart/JpgFromRawLength and ExtractImage RawConv",
    "lib/Image/ExifTool/Exif.pm:5084-5121 OtherImage Require/Desire "
    "start-length pairs and ExtractImage RawConv",
    "lib/Image/ExifTool/Exif.pm:6216-6244 ExtractImage in-buffer EXIF_DATA "
    "substring branch and file-level ExtractBinary fallback",
)


@dataclass(frozen=True)
class TiffHeader:
    byte_order: str
    endian: Endian
    first_ifd_offset: int


@dataclass(frozen=True)
class IfdEntry:
    tag_id: int
    field_type: int
    count: int
    value_offset: int
    entry_offset: int


@dataclass(frozen=True)
class Ifd:
    offset: int
    entries: list[IfdEntry]
    next_ifd_offset: int


@dataclass(frozen=True)
class TiffIfdContext:
    name: IfdContextName
    offset: int
    entry_count: int
    next_ifd_offset: int
    path: tuple[IfdContextName, ...]
    parent: IfdContextName | None
    pointer_kind: TiffPointerKind | None
    pointer_tag_id: int | None

    def to_json(self) -> JsonObject:
        return {
            "name": self.name,
            "offset": self.offset,
            "entry_count": self.entry_count,
            "next_ifd_offset": self.next_ifd_offset,
            "path": list(self.path),
            "parent": self.parent,
            "pointer_kind": self.pointer_kind,
            "pointer_tag_id": f"0x{self.pointer_tag_id:04X}"
            if self.pointer_tag_id is not None
            else None,
        }


@dataclass(frozen=True)
class TiffIfdPointer:
    pointer_kind: TiffPointerKind
    source_context: IfdContextName
    target_context: IfdContextName
    tag_id: int | None
    offset: int
    path: tuple[IfdContextName, ...]

    def to_json(self) -> JsonObject:
        return {
            "pointer_kind": self.pointer_kind,
            "source_context": self.source_context,
            "target_context": self.target_context,
            "tag_id": f"0x{self.tag_id:04X}" if self.tag_id is not None else None,
            "offset": self.offset,
            "path": list(self.path),
        }


@dataclass(frozen=True)
class TiffEmbeddedImageReadiness:
    context: IfdContextName
    data_tag: EmbeddedImageDataTag
    status: EmbeddedImageReadinessStatus
    start_tag_id: int
    length_tag_id: int
    start: int | None
    length: int | None
    path: tuple[IfdContextName, ...]

    def to_json(self) -> JsonObject:
        return {
            "context": self.context,
            "data_tag": self.data_tag,
            "status": self.status,
            "start_tag_id": f"0x{self.start_tag_id:04X}",
            "length_tag_id": f"0x{self.length_tag_id:04X}",
            "start": self.start,
            "length": self.length,
            "path": list(self.path),
        }


@dataclass(frozen=True)
class TiffTraversalReadinessReport:
    status: TiffTraversalStatus
    contexts: tuple[TiffIfdContext, ...]
    pointers: tuple[TiffIfdPointer, ...]
    embedded_image_readiness: tuple[TiffEmbeddedImageReadiness, ...]
    source_anchors: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "status": self.status,
            "contexts": [context.to_json() for context in self.contexts],
            "pointers": [pointer.to_json() for pointer in self.pointers],
            "embedded_image_readiness": [
                readiness.to_json() for readiness in self.embedded_image_readiness
            ],
            "source_anchors": list(self.source_anchors),
        }


@dataclass(frozen=True)
class TiffBinaryProducerReadiness:
    status: TiffBinaryProducerReadinessStatus
    traversal: TiffTraversalReadinessReport
    source_anchors: tuple[str, ...]
    deferred_binary_tags: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "status": self.status,
            "traversal": self.traversal.to_json(),
            "exposed_ifd_contexts": [context.name for context in self.traversal.contexts],
            "embedded_image_readiness": [
                readiness.to_json() for readiness in self.traversal.embedded_image_readiness
            ],
            "source_anchors": list(self.source_anchors),
            "deferred_binary_tags": list(self.deferred_binary_tags),
        }


@dataclass(frozen=True)
class TiffEmbeddedImageMaterialization:
    context: IfdContextName
    data_tag: EmbeddedImageDataTag
    status: EmbeddedImageMaterializationStatus
    start: int | None
    length: int | None
    image: bytes | None
    path: tuple[IfdContextName, ...]
    source_anchors: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "context": self.context,
            "data_tag": self.data_tag,
            "status": self.status,
            "start": self.start,
            "length": self.length,
            "extracted_length": len(self.image) if self.image is not None else None,
            "path": list(self.path),
            "source_anchors": list(self.source_anchors),
        }


@dataclass(frozen=True)
class TiffEmbeddedImageMaterializationReport:
    images: tuple[TiffEmbeddedImageMaterialization, ...]
    source_anchors: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "images": [image.to_json() for image in self.images],
            "source_anchors": list(self.source_anchors),
        }


@dataclass(frozen=True)
class TiffExtractImageByteSource:
    """Caller-owned bytes required for ExifTool ExtractImage file fallback."""

    full_file_bytes: bytes | None
    exif_data: bytes
    exif_data_pos: int
    file_source: TiffFileByteSource | None = None


def parse_tiff_header(data: bytes) -> TiffHeader:
    if len(data) < 8:
        raise ValueError("Truncated TIFF header")
    marker = data[:2]
    if marker == b"II":
        endian: Endian = "little"
        byte_order = "Little-endian (Intel, II)"
    elif marker == b"MM":
        endian = "big"
        byte_order = "Big-endian (Motorola, MM)"
    else:
        raise ValueError("Invalid TIFF byte-order marker")
    magic = read_u16(data, 2, endian)
    if magic != 42:
        raise ValueError(f"Invalid TIFF magic: {magic}")
    first_ifd_offset = read_u32(data, 4, endian)
    return TiffHeader(
        byte_order=byte_order,
        endian=endian,
        first_ifd_offset=first_ifd_offset,
    )


def parse_ifd(data: bytes, offset: int, endian: Endian) -> Ifd:
    if offset + 2 > len(data):
        raise ValueError(f"Truncated IFD entry count at offset {offset}")
    entry_count = read_u16(data, offset, endian)
    entries_start = offset + 2
    entries_end = entries_start + entry_count * 12
    next_offset_position = entries_end
    if next_offset_position + 4 > len(data):
        raise ValueError(f"Truncated IFD entries at offset {offset}")

    entries = []
    for index in range(entry_count):
        entry_offset = entries_start + index * 12
        entries.append(
            IfdEntry(
                tag_id=read_u16(data, entry_offset, endian),
                field_type=read_u16(data, entry_offset + 2, endian),
                count=read_u32(data, entry_offset + 4, endian),
                value_offset=read_u32(data, entry_offset + 8, endian),
                entry_offset=entry_offset,
            )
        )
    return Ifd(
        offset=offset,
        entries=entries,
        next_ifd_offset=read_u32(data, next_offset_position, endian),
    )


def read_ifd0_values(data: bytes) -> DecodedTags:
    header = parse_tiff_header(data)
    ifd0 = parse_ifd(data, header.first_ifd_offset, header.endian)
    return read_named_ifd_values(data, ifd0, header.endian, IFD0_TAGS)


def read_exif_ifd_values(data: bytes) -> DecodedTags:
    header = parse_tiff_header(data)
    ifd0 = parse_ifd(data, header.first_ifd_offset, header.endian)
    ifd0_values = read_named_ifd_values(data, ifd0, header.endian, IFD0_TAGS)
    exif_offset = ifd0_values.get("ExifIFDPointer")
    if not isinstance(exif_offset, int):
        raise ValueError("IFD0 does not contain an ExifIFD pointer")
    exif_ifd = parse_ifd(data, exif_offset, header.endian)
    return read_named_ifd_values(data, exif_ifd, header.endian, EXIF_IFD_TAGS)


def read_ifd1_values(data: bytes) -> DecodedTags:
    header = parse_tiff_header(data)
    ifd0 = parse_ifd(data, header.first_ifd_offset, header.endian)
    if ifd0.next_ifd_offset == 0:
        raise ValueError("TIFF data does not contain IFD1")
    ifd1 = parse_ifd(data, ifd0.next_ifd_offset, header.endian)
    return read_named_ifd_values(data, ifd1, header.endian, IFD1_TAGS)


def read_gps_ifd_values(data: bytes) -> DecodedTags:
    header = parse_tiff_header(data)
    ifd0 = parse_ifd(data, header.first_ifd_offset, header.endian)
    ifd0_values = read_named_ifd_values(data, ifd0, header.endian, IFD0_TAGS)
    gps_offset = ifd0_values.get("GPSInfoIFDPointer")
    if not isinstance(gps_offset, int):
        raise ValueError("IFD0 does not contain a GPSInfo IFD pointer")
    gps_ifd = parse_ifd(data, gps_offset, header.endian)
    return read_named_ifd_values(data, gps_ifd, header.endian, GPS_IFD_TAGS)


def report_tiff_traversal_readiness(data: bytes) -> TiffTraversalReadinessReport:
    header = parse_tiff_header(data)
    contexts: list[TiffIfdContext] = []
    pointers: list[TiffIfdPointer] = []
    embedded_image_readiness: list[TiffEmbeddedImageReadiness] = []
    visited_offsets: set[int] = set()

    discover_ifd_context(
        data=data,
        endian=header.endian,
        name="IFD0",
        offset=header.first_ifd_offset,
        parent=None,
        path=("IFD0",),
        pointer_kind=None,
        pointer_tag_id=None,
        contexts=contexts,
        pointers=pointers,
        embedded_image_readiness=embedded_image_readiness,
        visited_offsets=visited_offsets,
        chain_depth=0,
    )

    return TiffTraversalReadinessReport(
        status="traversal_primitives_ready",
        contexts=tuple(contexts),
        pointers=tuple(pointers),
        embedded_image_readiness=tuple(embedded_image_readiness),
        source_anchors=(
            "lib/Image/ExifTool/Exif.pm:1008-1023 tag 0x14a SubIFD "
            "SubDirectory Start=$val MaxSubdirs=10",
            "lib/Image/ExifTool/Exif.pm:2008-2015 tag 0x8769 ExifIFD SubDirectory Start=$val",
            "lib/Image/ExifTool/Exif.pm:2131-2138 tag 0x8825 GPSInfo "
            "SubDirectory Start=$val MaxSubdirs=1",
            "lib/Image/ExifTool/Exif.pm:7213-7233 ProcessExif trailing IFD "
            "link traversal and SubIFD linked-IFD validation",
            "lib/Image/ExifTool/Exif.pm:1154-1408 tag 0x0201/0x0202 "
            "context-sensitive embedded-image start/length routing",
        ),
    )


def report_tiff_binary_producer_readiness(data: bytes) -> TiffBinaryProducerReadiness:
    traversal = report_tiff_traversal_readiness(data)
    return TiffBinaryProducerReadiness(
        status="traversal_ready_extraction_deferred",
        traversal=traversal,
        source_anchors=(
            "lib/Image/ExifTool/Exif.pm:5059-5082 JpgFromRaw Require "
            "JpgFromRawStart/JpgFromRawLength and ExtractImage RawConv",
            "lib/Image/ExifTool/Exif.pm:5084-5121 OtherImage Require/Desire "
            "start-length pairs and ExtractImage RawConv",
            "lib/Image/ExifTool/Exif.pm:1154-1408 0x0201/0x0202 DataTag routing by "
            "DIR_NAME/PATH before composite extraction",
        ),
        deferred_binary_tags=("JpgFromRaw", "OtherImage"),
    )


def materialize_tiff_embedded_images(data: bytes) -> TiffEmbeddedImageMaterializationReport:
    traversal = report_tiff_traversal_readiness(data)
    images = tuple(
        materialize_tiff_embedded_image(data, readiness)
        for readiness in traversal.embedded_image_readiness
    )
    return TiffEmbeddedImageMaterializationReport(
        images=images,
        source_anchors=EMBEDDED_IMAGE_MATERIALIZER_SOURCE_ANCHORS,
    )


def materialize_tiff_embedded_images_from_file(
    byte_source: TiffExtractImageByteSource,
) -> TiffEmbeddedImageMaterializationReport:
    traversal = report_tiff_traversal_readiness(byte_source.exif_data)
    images = tuple(
        materialize_tiff_embedded_image_from_file(byte_source, readiness)
        for readiness in traversal.embedded_image_readiness
    )
    return TiffEmbeddedImageMaterializationReport(
        images=images,
        source_anchors=EMBEDDED_IMAGE_MATERIALIZER_SOURCE_ANCHORS,
    )


def materialize_tiff_embedded_image(
    data: bytes,
    readiness: TiffEmbeddedImageReadiness,
) -> TiffEmbeddedImageMaterialization:
    status = classify_embedded_image_materialization_status(data, readiness.start, readiness.length)
    image = (
        data[readiness.start : readiness.start + readiness.length]
        if status == "extracted" and readiness.start is not None and readiness.length is not None
        else None
    )
    return TiffEmbeddedImageMaterialization(
        context=readiness.context,
        data_tag=readiness.data_tag,
        status=status,
        start=readiness.start,
        length=readiness.length,
        image=image,
        path=readiness.path,
        source_anchors=EMBEDDED_IMAGE_MATERIALIZER_SOURCE_ANCHORS,
    )


def materialize_tiff_embedded_image_from_file(
    byte_source: TiffExtractImageByteSource,
    readiness: TiffEmbeddedImageReadiness,
) -> TiffEmbeddedImageMaterialization:
    status = classify_file_relative_embedded_image_materialization_status(
        byte_source,
        readiness.start,
        readiness.length,
    )
    image = extract_file_relative_embedded_image(byte_source, readiness.start, readiness.length)
    return TiffEmbeddedImageMaterialization(
        context=readiness.context,
        data_tag=readiness.data_tag,
        status=status,
        start=readiness.start,
        length=readiness.length,
        image=image if status == "extracted" else None,
        path=readiness.path,
        source_anchors=EMBEDDED_IMAGE_MATERIALIZER_SOURCE_ANCHORS,
    )


def classify_embedded_image_materialization_status(
    data: bytes,
    start: int | None,
    length: int | None,
) -> EmbeddedImageMaterializationStatus:
    if start is None and length is None:
        return "missing_start_and_length"
    if start is None:
        return "missing_start"
    if length is None:
        return "missing_length"
    if start < 0:
        return "negative_start"
    if length < 0:
        return "negative_length"
    if length == 0:
        return "zero_length"
    if start > len(data) or length > len(data) - start:
        return "out_of_buffer_or_file_relative"
    return "extracted"


def classify_file_relative_embedded_image_materialization_status(
    byte_source: TiffExtractImageByteSource,
    start: int | None,
    length: int | None,
) -> EmbeddedImageMaterializationStatus:
    if start is None and length is None:
        return "missing_start_and_length"
    if start is None:
        return "missing_start"
    if length is None:
        return "missing_length"
    if start < 0:
        return "negative_start"
    if length < 0:
        return "negative_length"
    if byte_source.exif_data_pos < 0:
        return "negative_exif_data_pos"
    if length == 0:
        return "zero_length"
    file_start = byte_source.exif_data_pos + start
    file_size = tiff_file_byte_source_size(byte_source)
    if file_size is None:
        return "out_of_file_bounds"
    if file_start > file_size:
        return "out_of_file_bounds"
    if length > file_size - file_start:
        return "out_of_file_bounds"
    return "extracted"


def extract_file_relative_embedded_image(
    byte_source: TiffExtractImageByteSource,
    start: int | None,
    length: int | None,
) -> bytes | None:
    if (
        classify_file_relative_embedded_image_materialization_status(byte_source, start, length)
        != "extracted"
        or start is None
        or length is None
    ):
        return None
    file_start = byte_source.exif_data_pos + start
    file_end = file_start + length
    exif_end = byte_source.exif_data_pos + len(byte_source.exif_data)
    if byte_source.exif_data_pos <= file_start and file_end <= exif_end:
        exif_start = file_start - byte_source.exif_data_pos
        return byte_source.exif_data[exif_start : exif_start + length]
    if byte_source.file_source is not None:
        return byte_source.file_source.read_at(file_start, length)
    if byte_source.full_file_bytes is None:
        return None
    return byte_source.full_file_bytes[file_start:file_end]


def tiff_file_byte_source_size(byte_source: TiffExtractImageByteSource) -> int | None:
    if byte_source.file_source is not None:
        return byte_source.file_source.size
    if byte_source.full_file_bytes is not None:
        return len(byte_source.full_file_bytes)
    return None


def discover_ifd_context(
    *,
    data: bytes,
    endian: Endian,
    name: IfdContextName,
    offset: int,
    parent: IfdContextName | None,
    path: tuple[IfdContextName, ...],
    pointer_kind: TiffPointerKind | None,
    pointer_tag_id: int | None,
    contexts: list[TiffIfdContext],
    pointers: list[TiffIfdPointer],
    embedded_image_readiness: list[TiffEmbeddedImageReadiness],
    visited_offsets: set[int],
    chain_depth: int,
) -> None:
    if offset in visited_offsets:
        return
    visited_offsets.add(offset)
    ifd = parse_ifd(data, offset, endian)
    context = TiffIfdContext(
        name=name,
        offset=ifd.offset,
        entry_count=len(ifd.entries),
        next_ifd_offset=ifd.next_ifd_offset,
        path=path,
        parent=parent,
        pointer_kind=pointer_kind,
        pointer_tag_id=pointer_tag_id,
    )
    contexts.append(context)
    readiness = classify_embedded_image_readiness(data, ifd, endian, context)
    if readiness is not None:
        embedded_image_readiness.append(readiness)

    for subifd_index, subifd_offset in enumerate(read_subifd_offsets(data, ifd, endian)):
        target_name = subifd_context_name(subifd_index)
        target_path = (*path, target_name)
        pointers.append(
            TiffIfdPointer(
                pointer_kind="subifd_pointer",
                source_context=name,
                target_context=target_name,
                tag_id=0x014A,
                offset=subifd_offset,
                path=target_path,
            )
        )
        discover_ifd_context(
            data=data,
            endian=endian,
            name=target_name,
            offset=subifd_offset,
            parent=name,
            path=target_path,
            pointer_kind="subifd_pointer",
            pointer_tag_id=0x014A,
            contexts=contexts,
            pointers=pointers,
            embedded_image_readiness=embedded_image_readiness,
            visited_offsets=visited_offsets,
            chain_depth=0,
        )

    if name == "IFD0":
        discover_single_pointer_context(
            data=data,
            endian=endian,
            ifd=ifd,
            source_context=name,
            source_path=path,
            tag_id=0x8769,
            target_context="ExifIFD",
            pointer_kind="exif_ifd_pointer",
            contexts=contexts,
            pointers=pointers,
            embedded_image_readiness=embedded_image_readiness,
            visited_offsets=visited_offsets,
        )
        discover_single_pointer_context(
            data=data,
            endian=endian,
            ifd=ifd,
            source_context=name,
            source_path=path,
            tag_id=0x8825,
            target_context="GPS",
            pointer_kind="gps_ifd_pointer",
            contexts=contexts,
            pointers=pointers,
            embedded_image_readiness=embedded_image_readiness,
            visited_offsets=visited_offsets,
        )

    next_name = next_ifd_context_name(name, chain_depth)
    if ifd.next_ifd_offset and next_name is not None:
        target_path = (*path[:-1], next_name)
        pointers.append(
            TiffIfdPointer(
                pointer_kind="next_ifd",
                source_context=name,
                target_context=next_name,
                tag_id=None,
                offset=ifd.next_ifd_offset,
                path=target_path,
            )
        )
        discover_ifd_context(
            data=data,
            endian=endian,
            name=next_name,
            offset=ifd.next_ifd_offset,
            parent=parent,
            path=target_path,
            pointer_kind="next_ifd",
            pointer_tag_id=None,
            contexts=contexts,
            pointers=pointers,
            embedded_image_readiness=embedded_image_readiness,
            visited_offsets=visited_offsets,
            chain_depth=chain_depth + 1,
        )


def discover_single_pointer_context(
    *,
    data: bytes,
    endian: Endian,
    ifd: Ifd,
    source_context: IfdContextName,
    source_path: tuple[IfdContextName, ...],
    tag_id: int,
    target_context: IfdContextName,
    pointer_kind: TiffPointerKind,
    contexts: list[TiffIfdContext],
    pointers: list[TiffIfdPointer],
    embedded_image_readiness: list[TiffEmbeddedImageReadiness],
    visited_offsets: set[int],
) -> None:
    offset = read_entry_int(data, find_entry(ifd, tag_id), endian)
    if offset is None:
        return
    target_path = (*source_path, target_context)
    pointers.append(
        TiffIfdPointer(
            pointer_kind=pointer_kind,
            source_context=source_context,
            target_context=target_context,
            tag_id=tag_id,
            offset=offset,
            path=target_path,
        )
    )
    discover_ifd_context(
        data=data,
        endian=endian,
        name=target_context,
        offset=offset,
        parent=source_context,
        path=target_path,
        pointer_kind=pointer_kind,
        pointer_tag_id=tag_id,
        contexts=contexts,
        pointers=pointers,
        embedded_image_readiness=embedded_image_readiness,
        visited_offsets=visited_offsets,
        chain_depth=0,
    )


def read_subifd_offsets(data: bytes, ifd: Ifd, endian: Endian) -> tuple[int, ...]:
    value = read_entry_value(data, entry, endian) if (entry := find_entry(ifd, 0x014A)) else None
    if isinstance(value, int):
        return (value,)
    if isinstance(value, list):
        offsets: list[int] = []
        for item in value:
            if isinstance(item, int):
                offsets.append(item)
        return tuple(offsets[:MAX_SUBIFD_POINTERS])
    return ()


def classify_embedded_image_readiness(
    data: bytes,
    ifd: Ifd,
    endian: Endian,
    context: TiffIfdContext,
) -> TiffEmbeddedImageReadiness | None:
    start = read_entry_int(data, find_entry(ifd, 0x0201), endian)
    length = read_entry_int(data, find_entry(ifd, 0x0202), endian)
    if start is None and length is None:
        return None
    if start is None:
        status: EmbeddedImageReadinessStatus = "missing_start"
    elif length is None:
        status = "missing_length"
    else:
        status = "pair_present_extraction_deferred"
    return TiffEmbeddedImageReadiness(
        context=context.name,
        data_tag=embedded_image_data_tag(context.name),
        status=status,
        start_tag_id=0x0201,
        length_tag_id=0x0202,
        start=start,
        length=length,
        path=context.path,
    )


def embedded_image_data_tag(context: IfdContextName) -> EmbeddedImageDataTag:
    if context in {"SubIFD", "IFD2"}:
        return "JpgFromRaw"
    if context == "IFD1":
        return "ThumbnailImage"
    return "OtherImage"


def subifd_context_name(index: int) -> IfdContextName:
    if index == 0:
        return "SubIFD"
    if index == 1:
        return "SubIFD1"
    return "SubIFD2"


def next_ifd_context_name(
    context: IfdContextName,
    chain_depth: int,
) -> IfdContextName | None:
    if chain_depth >= MAX_KNOWN_IFD_CHAIN_DEPTH:
        return None
    if context == "IFD0":
        return "IFD1"
    if context == "IFD1":
        return "IFD2"
    if context == "SubIFD":
        return "SubIFD1"
    if context == "SubIFD1":
        return "SubIFD2"
    return None


def find_entry(ifd: Ifd, tag_id: int) -> IfdEntry | None:
    for entry in ifd.entries:
        if entry.tag_id == tag_id:
            return entry
    return None


def read_entry_int(data: bytes, entry: IfdEntry | None, endian: Endian) -> int | None:
    if entry is None:
        return None
    value = read_entry_value(data, entry, endian)
    return value if isinstance(value, int) else None


def read_named_ifd_values(
    data: bytes,
    ifd: Ifd,
    endian: Endian,
    tag_names: TagNameMap,
) -> DecodedTags:
    values: DecodedTags = {}
    for entry in ifd.entries:
        name = tag_names.get(entry.tag_id)
        if not name:
            continue
        raw_value = read_entry_value(data, entry, endian)
        values[name] = print_value(name, raw_value)
    return values


def inspect_ifd0(data: bytes) -> JsonObject:
    header = parse_tiff_header(data)
    ifd0 = parse_ifd(data, header.first_ifd_offset, header.endian)
    exif_ifd = None
    ifd1 = None
    gps_ifd = None
    exif_ifd_values: DecodedTags = {}
    ifd1_values: DecodedTags = {}
    gps_ifd_values: DecodedTags = {}
    ifd0_values = read_named_ifd_values(data, ifd0, header.endian, IFD0_TAGS)
    if ifd0.next_ifd_offset:
        ifd1 = parse_ifd(data, ifd0.next_ifd_offset, header.endian)
        ifd1_values = read_named_ifd_values(data, ifd1, header.endian, IFD1_TAGS)
    exif_offset = ifd0_values.get("ExifIFDPointer")
    if isinstance(exif_offset, int):
        exif_ifd = parse_ifd(data, exif_offset, header.endian)
        exif_ifd_values = read_named_ifd_values(
            data,
            exif_ifd,
            header.endian,
            EXIF_IFD_TAGS,
        )
    gps_offset = ifd0_values.get("GPSInfoIFDPointer")
    if isinstance(gps_offset, int):
        gps_ifd = parse_ifd(data, gps_offset, header.endian)
        gps_ifd_values = read_named_ifd_values(
            data,
            gps_ifd,
            header.endian,
            GPS_IFD_TAGS,
        )
    return {
        "byte_order": header.byte_order,
        "first_ifd_offset": header.first_ifd_offset,
        "ifd0_offset": ifd0.offset,
        "ifd0_entry_count": len(ifd0.entries),
        "next_ifd_offset": ifd0.next_ifd_offset,
        "ifd0_values": ifd0_values,
        "ifd0_entries": [
            {
                "tag_id": f"0x{entry.tag_id:04X}",
                "tag_name": IFD0_TAGS.get(entry.tag_id),
                "field_type": entry.field_type,
                "count": entry.count,
                "value_offset": entry.value_offset,
                "entry_offset": entry.entry_offset,
            }
            for entry in ifd0.entries
        ],
        "ifd1_offset": ifd1.offset if ifd1 else None,
        "ifd1_entry_count": len(ifd1.entries) if ifd1 else 0,
        "ifd1_values": ifd1_values,
        "ifd1_entries": [
            {
                "tag_id": f"0x{entry.tag_id:04X}",
                "tag_name": IFD1_TAGS.get(entry.tag_id),
                "field_type": entry.field_type,
                "count": entry.count,
                "value_offset": entry.value_offset,
                "entry_offset": entry.entry_offset,
            }
            for entry in ifd1.entries
        ]
        if ifd1
        else [],
        "exif_ifd_offset": exif_ifd.offset if exif_ifd else None,
        "exif_ifd_entry_count": len(exif_ifd.entries) if exif_ifd else 0,
        "exif_ifd_values": exif_ifd_values,
        "exif_ifd_entries": [
            {
                "tag_id": f"0x{entry.tag_id:04X}",
                "tag_name": EXIF_IFD_TAGS.get(entry.tag_id),
                "field_type": entry.field_type,
                "count": entry.count,
                "value_offset": entry.value_offset,
                "entry_offset": entry.entry_offset,
            }
            for entry in exif_ifd.entries
        ]
        if exif_ifd
        else [],
        "gps_ifd_offset": gps_ifd.offset if gps_ifd else None,
        "gps_ifd_entry_count": len(gps_ifd.entries) if gps_ifd else 0,
        "gps_ifd_values": gps_ifd_values,
        "gps_ifd_entries": [
            {
                "tag_id": f"0x{entry.tag_id:04X}",
                "tag_name": GPS_IFD_TAGS.get(entry.tag_id),
                "field_type": entry.field_type,
                "count": entry.count,
                "value_offset": entry.value_offset,
                "entry_offset": entry.entry_offset,
            }
            for entry in gps_ifd.entries
        ]
        if gps_ifd
        else [],
    }


def read_entry_value(data: bytes, entry: IfdEntry, endian: Endian) -> TiffValue:
    field_size = TYPE_SIZES.get(entry.field_type)
    if field_size is None:
        raise ValueError(f"Unsupported TIFF field type: {entry.field_type}")
    byte_count = field_size * entry.count
    if byte_count <= 4:
        raw = entry.value_offset.to_bytes(4, endian)[:byte_count]
    else:
        value_start = entry.value_offset
        value_end = value_start + byte_count
        if value_end > len(data):
            raise ValueError(f"Truncated TIFF value at offset {value_start}")
        raw = data[value_start:value_end]

    if entry.field_type == TIFF_TYPE_ASCII:
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace")
    if entry.field_type == TIFF_TYPE_SHORT:
        values = [read_u16(raw, index * 2, endian) for index in range(entry.count)]
        return values[0] if entry.count == 1 else values
    if entry.field_type == TIFF_TYPE_LONG:
        values = [read_u32(raw, index * 4, endian) for index in range(entry.count)]
        return values[0] if entry.count == 1 else values
    if entry.field_type == TIFF_TYPE_SLONG:
        values = [read_s32(raw, index * 4, endian) for index in range(entry.count)]
        return values[0] if entry.count == 1 else values
    if entry.field_type == TIFF_TYPE_RATIONAL:
        rational_values: list[Fraction | None] = []
        for index in range(entry.count):
            item_offset = index * 8
            numerator = read_u32(raw, item_offset, endian)
            denominator = read_u32(raw, item_offset + 4, endian)
            rational_values.append(Fraction(numerator, denominator) if denominator else None)
        return rational_values[0] if entry.count == 1 else rational_values
    if entry.field_type == TIFF_TYPE_SRATIONAL:
        srational_values: list[Fraction | None] = []
        for index in range(entry.count):
            item_offset = index * 8
            numerator = read_s32(raw, item_offset, endian)
            denominator = read_s32(raw, item_offset + 4, endian)
            srational_values.append(Fraction(numerator, denominator) if denominator else None)
        return srational_values[0] if entry.count == 1 else srational_values
    if entry.field_type == TIFF_TYPE_UNDEFINED:
        return raw
    if entry.field_type == TIFF_TYPE_BYTE:
        return raw[0] if entry.count == 1 else list(raw)
    if entry.field_type == TIFF_TYPE_DOUBLE:
        return raw
    raise ValueError(f"Unsupported TIFF field type: {entry.field_type}")


def print_value(name: str, value: TiffValue) -> JsonValue:
    if name == "Orientation" and isinstance(value, int):
        return ORIENTATION_PRINT.get(value, value)
    if name in {"ResolutionUnit", "FocalPlaneResolutionUnit"} and isinstance(value, int):
        return RESOLUTION_UNIT_PRINT.get(value, value)
    if name == "Compression" and isinstance(value, int):
        return COMPRESSION_PRINT.get(value, value)
    if name == "YCbCrPositioning" and isinstance(value, int):
        return YCBCR_POSITIONING_PRINT.get(value, value)
    if name == "ColorSpace" and isinstance(value, int):
        return COLOR_SPACE_PRINT.get(value, value)
    if name == "UserComment" and isinstance(value, bytes):
        return print_exif_user_comment(value)
    if name == "ExposureProgram" and isinstance(value, int):
        return EXPOSURE_PROGRAM_PRINT.get(value, value)
    if name == "SensitivityType" and isinstance(value, int):
        return SENSITIVITY_TYPE_PRINT.get(value, f"Unknown ({value})")
    if name == "MeteringMode" and isinstance(value, int):
        return METERING_MODE_PRINT.get(value, value)
    if name == "LightSource" and isinstance(value, int):
        return LIGHT_SOURCE_PRINT.get(value, f"Unknown ({value})")
    if name == "Flash" and isinstance(value, int):
        return FLASH_PRINT.get(value, value)
    if name == "SensingMethod" and isinstance(value, int):
        return SENSING_METHOD_PRINT.get(value, value)
    if name == "SceneCaptureType" and isinstance(value, int):
        return SCENE_CAPTURE_TYPE_PRINT.get(value, value)
    if name == "CustomRendered" and isinstance(value, int):
        return CUSTOM_RENDERED_PRINT.get(value, value)
    if name == "ExposureMode" and isinstance(value, int):
        return EXPOSURE_MODE_PRINT.get(value, value)
    if name == "WhiteBalance" and isinstance(value, int):
        return WHITE_BALANCE_PRINT.get(value, value)
    if name == "DigitalZoomRatio" and isinstance(value, Fraction):
        return value.numerator if value.denominator == 1 else float(value)
    if name == "GainControl" and isinstance(value, int):
        return GAIN_CONTROL_PRINT.get(value, value)
    if name in {"Contrast", "Saturation"} and isinstance(value, int):
        return NORMAL_LOW_HIGH_PRINT.get(value, value)
    if name == "Sharpness" and isinstance(value, int):
        return SHARPNESS_PRINT.get(value, value)
    if name in {"ExifVersion", "FlashpixVersion"} and isinstance(value, bytes):
        return value.decode("ascii", errors="replace")
    if name == "ComponentsConfiguration" and isinstance(value, bytes):
        return components_configuration_print(value)
    if name == "FileSource" and isinstance(value, bytes) and value:
        return FILE_SOURCE_PRINT.get(value[0], value[0])
    if name == "SceneType" and isinstance(value, bytes) and value:
        return SCENE_TYPE_PRINT.get(value[0], value[0])
    if name == "GPSVersionID" and isinstance(value, list):
        return ".".join(str(item) for item in value)
    if name in {"GPSLatitudeRef", "GPSLongitudeRef"} and isinstance(value, str):
        return gps_ref_print(value)
    if name in {"GPSLatitude", "GPSLongitude"} and isinstance(value, list):
        return gps_coordinate_print(value)
    if name == "GPSAltitudeRef" and isinstance(value, int):
        return GPS_ALTITUDE_REF_PRINT.get(value, value)
    if name == "GPSAltitude" and isinstance(value, Fraction):
        return f"{gps_altitude_number(value)} m"
    if name == "GPSHPositioningError" and isinstance(value, Fraction):
        return f"{gps_altitude_number(value)} m"
    if name in {"GPSTrack", "GPSImgDirection", "GPSDestBearing"} and isinstance(value, Fraction):
        return gps_direction_number(value)
    if name == "GPSTimeStamp" and isinstance(value, list):
        return gps_time_print(value)
    if name == "GPSMeasureMode" and isinstance(value, str):
        return value.rstrip("\x00")
    if name == "GPSSpeedRef" and isinstance(value, str):
        return GPS_SPEED_REF_PRINT.get(value.upper(), value)
    if name in {"GPSTrackRef", "GPSImgDirectionRef", "GPSDestBearingRef"} and isinstance(
        value, str
    ):
        return GPS_NORTH_REF_PRINT.get(value.upper(), value)
    if name == "ShutterSpeedValue" and isinstance(value, Fraction):
        return print_shutter_speed(value)
    if name == "ExposureTime" and isinstance(value, Fraction):
        return print_exposure_time(value)
    if name == "FNumber" and isinstance(value, Fraction):
        return print_f_number(value)
    if name in {"ApertureValue", "MaxApertureValue"} and isinstance(value, Fraction):
        return round_half_up(math.pow(2, float(value) / 2), 1)
    if name == "BrightnessValue" and isinstance(value, Fraction):
        return round_half_up(float(value), 9)
    if name == "ExposureCompensation" and isinstance(value, Fraction):
        rendered = round(float(value), 2)
        return int(rendered) if rendered.is_integer() else rendered
    if name == "FocalLength" and isinstance(value, Fraction):
        return f"{float(value):.1f} mm"
    if name == "FocalLengthIn35mmFormat" and isinstance(value, int):
        return f"{value} mm"
    if name == "LensInfo" and isinstance(value, list):
        return print_lens_info(value)
    if name == "SubjectArea" and isinstance(value, list):
        return " ".join(str(item) for item in value)
    if name in {"SubSecTime", "SubSecTimeOriginal", "SubSecTimeDigitized"} and isinstance(
        value,
        str,
    ):
        return value
    if name == "ReferenceBlackWhite" and isinstance(value, list):
        return reference_black_white_print(value)
    if isinstance(value, Fraction):
        if value.denominator == 1:
            return value.numerator
        return float(value)
    if isinstance(value, (str, int)) or value is None:
        return value
    raise ValueError(f"Unhandled TIFF value for {name}: {value!r}")


def print_exif_user_comment(value: bytes) -> str:
    if len(value) >= 8 and value[:8] in {
        b"ASCII\x00\x00\x00",
        b"\x00\x00\x00\x00\x00\x00\x00\x00",
    }:
        return value[8:].split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    return value.decode("utf-8", errors="replace")


def gps_altitude_number(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{float(value):.10g}"


def gps_direction_number(value: Fraction) -> float | int:
    if value.denominator == 1:
        return value.numerator
    return float(f"{float(value):.10g}")


def reference_black_white_print(value: list[int] | list[Fraction | None]) -> str:
    numbers = numeric_tiff_values(value)
    if numbers is None:
        return " ".join("" if item is None else str(item) for item in value)
    rendered_values: list[str] = []
    for item in numbers:
        if isinstance(item, int):
            rendered_values.append(str(item))
        elif item.denominator == 1:
            rendered_values.append(str(item.numerator))
        else:
            rendered_values.append(str(float(item)))
    return " ".join(rendered_values)


def print_f_number(value: Fraction) -> float:
    raw_value = float(value)
    digits = 2 if raw_value < 1 else 1
    return round_half_up(raw_value, digits)


def components_configuration_print(value: bytes) -> str:
    return ", ".join(COMPONENT_CONFIGURATION_PRINT.get(item, str(item)) for item in value)


def gps_ref_print(value: str) -> str:
    return {
        "N": "North",
        "S": "South",
        "E": "East",
        "W": "West",
    }.get(value, value)


def gps_coordinate_print(value: list[int] | list[Fraction | None]) -> str:
    numbers = numeric_tiff_values(value)
    if numbers is None:
        return ", ".join("" if item is None else str(item) for item in value)
    if len(numbers) != 3:
        return ", ".join(str(item) for item in numbers)
    degrees, raw_minutes, raw_seconds = numbers
    minutes = int(raw_minutes)
    seconds = (float(raw_minutes) - minutes) * 60 + float(raw_seconds)
    return f"{int(degrees)} deg {minutes}' {seconds:.2f}\""


def gps_time_print(value: list[int] | list[Fraction | None]) -> str:
    numbers = numeric_tiff_values(value)
    if numbers is None:
        return ":".join("" if item is None else str(item) for item in value)
    if len(numbers) != 3:
        return ":".join(str(item) for item in numbers)
    hours, minutes, seconds = numbers
    return f"{int(hours):02d}:{int(minutes):02d}:{gps_seconds_print(seconds)}"


def gps_seconds_print(value: NumericTiffValue) -> str:
    if isinstance(value, int) or value.denominator == 1:
        return f"{int(value):02d}"
    rendered = f"{float(value):05.2f}".rstrip("0").rstrip(".")
    return rendered if len(rendered.split(".", 1)[0]) == 2 else f"0{rendered}"


def print_lens_info(value: list[int] | list[Fraction | None]) -> str:
    numbers = numeric_tiff_values(value)
    if numbers is None or len(numbers) != 4:
        return " ".join("" if item is None else str(item) for item in value)
    short_focal, long_focal, short_aperture, long_aperture = numbers
    focal = lens_range_print(short_focal, long_focal, "mm")
    aperture = lens_range_print(short_aperture, long_aperture, "")
    return f"{focal} f/{aperture}"


def lens_range_print(start: NumericTiffValue, end: NumericTiffValue, suffix: str) -> str:
    start_text = lens_number_print(start)
    end_text = lens_number_print(end)
    if start_text == end_text:
        return f"{start_text}{suffix}"
    return f"{start_text}-{end_text}{suffix}"


def lens_number_print(value: NumericTiffValue) -> str:
    rendered = f"{float(value):.2f}".rstrip("0").rstrip(".")
    if "." not in rendered:
        return rendered
    if len(rendered.split(".", 1)[1]) == 1:
        return f"{rendered}0".rstrip("0")
    return rendered


def numeric_tiff_values(value: list[int] | list[Fraction | None]) -> list[NumericTiffValue] | None:
    numbers: list[NumericTiffValue] = []
    for item in value:
        if item is None:
            return None
        numbers.append(item)
    return numbers


def print_shutter_speed(value: Fraction) -> str | int | float:
    if abs(float(value)) >= 100:
        return 0
    seconds = math.pow(2, -float(value))
    if seconds < 1:
        denominator = round(1 / seconds)
        return f"1/{denominator}"
    if abs(seconds - round(seconds)) < 1e-9:
        return round(seconds)
    return round_half_up(seconds, 2)


def print_exposure_time(value: Fraction) -> str | int | float:
    if value <= 0:
        return 0
    if value < 1:
        denominator = round(1 / float(value))
        return f"1/{denominator}"
    if value.denominator == 1:
        return value.numerator
    return round_half_up(float(value), 2)


def round_half_up(value: float, digits: int) -> float:
    scale = 10**digits
    return float(math.floor(value * scale + 0.5) / scale)


def read_u16(data: bytes, offset: int, endian: Endian) -> int:
    if offset + 2 > len(data):
        raise ValueError(f"Truncated 16-bit value at offset {offset}")
    return int.from_bytes(data[offset : offset + 2], endian)


def read_u32(data: bytes, offset: int, endian: Endian) -> int:
    if offset + 4 > len(data):
        raise ValueError(f"Truncated 32-bit value at offset {offset}")
    return int.from_bytes(data[offset : offset + 4], endian)


def read_s32(data: bytes, offset: int, endian: Endian) -> int:
    if offset + 4 > len(data):
        raise ValueError(f"Truncated signed 32-bit value at offset {offset}")
    return int.from_bytes(data[offset : offset + 4], endian, signed=True)
