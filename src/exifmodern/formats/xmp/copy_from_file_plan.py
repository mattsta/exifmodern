"""XMP sidecar tagsFromFile copy planning.

This module models the ExifTool ``SetNewValuesFromFile`` routing needed by the
sidecar golden-write copy cases without wiring it into the shared CLI planner.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from fractions import Fraction
from pathlib import Path
from typing import Literal

from exifmodern.compatibility import EXIFTOOL_COMPATIBILITY_VERSION_TEXT
from exifmodern.formats.jpeg.container import read_exif_app1
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_RATIONAL,
    TIFF_TYPE_SRATIONAL,
    IfdEntry,
    TiffValue,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)
from exifmodern.json_types import JsonObject, json_string_array_value, json_string_value
from exifmodern.services.tag_lookup_runtime import TagLookupExactCopyMapping

type XmpCopySourceGroup = Literal["ALL", "EXIF", "GPS", "XMP"]
type XmpCopyDestinationGroup = Literal["ALL", "XMP"]
type XmpCopyTagPattern = str
type XmpSidecarCopyStrategy = Literal[
    "copy_all_metadata_packet",
    "copy_xmp_writable_packet",
    "copy_exif_to_xmp_assignments",
    "copy_exact_exif_to_xmp_assignments",
]
type XmpPacketTransform = Literal["update_toolkit", "filter_user_defined_xmp"]


TAGS_FROM_FILE_SOURCE = "xmp.copy_from_file.tags_from_file"
XMP_TABLE_SOURCE = "xmp.copy_from_file.tables"
XMP_WRITER_SOURCE = "xmp.copy_from_file.writer"

_COPY_REDIRECT_RE = re.compile(r"(?P<src>.+?)\s*>\s*(?P<dst>.+)")
_CUSTOM_XMP_NAMESPACE_RE = re.compile(
    rb"\s+xmlns:(?P<prefix>[-A-Za-z0-9_]+)='http://ns\.exiftool\.org/t/[^']+'"
)
_XMP_TOOLKIT_RE = re.compile(rb"x:xmptk='[^']*'")
_EXIFTOOL_VERSION_TEXT = f"Image::ExifTool {EXIFTOOL_COMPATIBILITY_VERSION_TEXT}".encode("ascii")
EXIF_TIFF_HEADER_PREFIXES = (b"II\x2a\x00", b"MM\x00\x2a")
BIGTIFF_HEADER_PREFIXES = (b"II\x2b\x00\x08\x00\x00\x00", b"MM\x00\x2b\x00\x08\x00\x00")
JPEG_EXACT_COPY_SOURCE_SUFFIXES = frozenset({".jpg", ".jpeg", ".jpe"})
EXIF_TIFF_EXACT_COPY_SOURCE_SUFFIXES = frozenset({".exif", ".tif", ".tiff"})
TIFF_RAW_EXACT_COPY_SOURCE_SUFFIXES = frozenset({".arw", ".cr2", ".dng", ".nef", ".pef", ".srw"})
SUPPORTED_EXACT_COPY_SOURCE_SUFFIXES = (
    JPEG_EXACT_COPY_SOURCE_SUFFIXES
    | EXIF_TIFF_EXACT_COPY_SOURCE_SUFFIXES
    | TIFF_RAW_EXACT_COPY_SOURCE_SUFFIXES
)


@dataclass(frozen=True)
class XmpCopySourceSelector:
    group: XmpCopySourceGroup
    tag_pattern: XmpCopyTagPattern
    raw_token: str


@dataclass(frozen=True)
class XmpCopyDestinationSelector:
    group: XmpCopyDestinationGroup
    tag_pattern: XmpCopyTagPattern
    raw_token: str


@dataclass(frozen=True)
class XmpCopyRoute:
    source: XmpCopySourceSelector
    destination: XmpCopyDestinationSelector
    raw_argument: str


@dataclass(frozen=True)
class XmpCopyFromFilePlan:
    source_filename: str
    routes: tuple[XmpCopyRoute, ...]
    strategy: XmpSidecarCopyStrategy
    packet_transform: XmpPacketTransform
    evidence_ids: tuple[str, ...]
    exact_mappings: tuple[TagLookupExactCopyMapping, ...] = ()


@dataclass(frozen=True)
class XmpCopyFromFileDiagnostic:
    token: str
    reason: str
    detail: str


@dataclass(frozen=True)
class XmpDestinationAssignment:
    property_name: str
    value: str


@dataclass(frozen=True)
class XmpMaterializedCopyFromFilePlan:
    copy_plan: XmpCopyFromFilePlan
    assignments: tuple[XmpDestinationAssignment, ...]
    diagnostics: tuple[XmpCopyFromFileDiagnostic, ...]


@dataclass(frozen=True)
class ExifSourceTag:
    group: str
    name: str
    value: TiffValue
    field_type: int


@dataclass(frozen=True)
class ExifToXmpMapping:
    source_group: str
    source_name: str
    property_name: str
    conversion: Literal[
        "raw_text",
        "xmp_date",
        "components_configuration",
        "empty_user_comment",
        "aperture_value",
        "shutter_speed_value",
        "xmp_gps_latitude",
        "xmp_gps_longitude",
        "xmp_gps_dest_latitude",
        "xmp_gps_dest_longitude",
    ] = "raw_text"


EXIF_TO_XMP_MAPPINGS = (
    ExifToXmpMapping("IFD0", "Make", "XMP-tiff:Make"),
    ExifToXmpMapping("IFD0", "Model", "XMP-tiff:Model"),
    ExifToXmpMapping("IFD0", "ImageDescription", "XMP-dc:Description"),
    ExifToXmpMapping("IFD0", "Orientation", "XMP-tiff:Orientation"),
    ExifToXmpMapping("IFD0", "XResolution", "XMP-tiff:XResolution"),
    ExifToXmpMapping("IFD0", "YResolution", "XMP-tiff:YResolution"),
    ExifToXmpMapping("IFD0", "ResolutionUnit", "XMP-tiff:ResolutionUnit"),
    ExifToXmpMapping("IFD0", "YCbCrPositioning", "XMP-tiff:YCbCrPositioning"),
    ExifToXmpMapping("IFD0", "ModifyDate", "XMP-xmp:ModifyDate", "xmp_date"),
    ExifToXmpMapping("IFD0", "Artist", "XMP-dc:Creator"),
    ExifToXmpMapping("IFD0", "Copyright", "XMP-dc:Rights"),
    ExifToXmpMapping("ExifIFD", "ExposureTime", "XMP-exif:ExposureTime"),
    ExifToXmpMapping("ExifIFD", "FNumber", "XMP-exif:FNumber"),
    ExifToXmpMapping("ExifIFD", "ISO", "XMP-exif:ISO"),
    ExifToXmpMapping("ExifIFD", "ExifVersion", "XMP-exif:ExifVersion"),
    ExifToXmpMapping("ExifIFD", "DateTimeOriginal", "XMP-exif:DateTimeOriginal", "xmp_date"),
    ExifToXmpMapping("ExifIFD", "CreateDate", "XMP-xmp:CreateDate", "xmp_date"),
    ExifToXmpMapping(
        "ExifIFD",
        "ComponentsConfiguration",
        "XMP-exif:ComponentsConfiguration",
        "components_configuration",
    ),
    ExifToXmpMapping("ExifIFD", "CompressedBitsPerPixel", "XMP-exif:CompressedBitsPerPixel"),
    ExifToXmpMapping(
        "ExifIFD",
        "ShutterSpeedValue",
        "XMP-exif:ShutterSpeedValue",
        "shutter_speed_value",
    ),
    ExifToXmpMapping("ExifIFD", "ApertureValue", "XMP-exif:ApertureValue", "aperture_value"),
    ExifToXmpMapping("ExifIFD", "ExposureCompensation", "XMP-exif:ExposureCompensation"),
    ExifToXmpMapping(
        "ExifIFD",
        "MaxApertureValue",
        "XMP-exif:MaxApertureValue",
        "aperture_value",
    ),
    ExifToXmpMapping("ExifIFD", "MeteringMode", "XMP-exif:MeteringMode"),
    ExifToXmpMapping("ExifIFD", "FocalLength", "XMP-exif:FocalLength"),
    ExifToXmpMapping("ExifIFD", "UserComment", "XMP-exif:UserComment", "empty_user_comment"),
    ExifToXmpMapping("ExifIFD", "FlashpixVersion", "XMP-exif:FlashpixVersion"),
    ExifToXmpMapping("ExifIFD", "ColorSpace", "XMP-exif:ColorSpace"),
    ExifToXmpMapping("ExifIFD", "ExifImageWidth", "XMP-exif:ExifImageWidth"),
    ExifToXmpMapping("ExifIFD", "ExifImageHeight", "XMP-exif:ExifImageHeight"),
    ExifToXmpMapping("ExifIFD", "FocalPlaneXResolution", "XMP-exif:FocalPlaneXResolution"),
    ExifToXmpMapping("ExifIFD", "FocalPlaneYResolution", "XMP-exif:FocalPlaneYResolution"),
    ExifToXmpMapping("ExifIFD", "FocalPlaneResolutionUnit", "XMP-exif:FocalPlaneResolutionUnit"),
    ExifToXmpMapping("ExifIFD", "SensingMethod", "XMP-exif:SensingMethod"),
    ExifToXmpMapping("ExifIFD", "FileSource", "XMP-exif:FileSource"),
    ExifToXmpMapping("ExifIFD", "CustomRendered", "XMP-exif:CustomRendered"),
    ExifToXmpMapping("ExifIFD", "ExposureMode", "XMP-exif:ExposureMode"),
    ExifToXmpMapping("ExifIFD", "WhiteBalance", "XMP-exif:WhiteBalance"),
    ExifToXmpMapping("ExifIFD", "SceneCaptureType", "XMP-exif:SceneCaptureType"),
    ExifToXmpMapping("InteropIFD", "InteropIndex", "XMP-exifEX:InteropIndex"),
    ExifToXmpMapping("GPS", "GPSLatitude", "XMP-exif:GPSLatitude", "xmp_gps_latitude"),
    ExifToXmpMapping("GPS", "GPSLongitude", "XMP-exif:GPSLongitude", "xmp_gps_longitude"),
    ExifToXmpMapping("GPS", "GPSAltitudeRef", "XMP-exif:GPSAltitudeRef"),
    ExifToXmpMapping("GPS", "GPSAltitude", "XMP-exif:GPSAltitude"),
    ExifToXmpMapping("GPS", "GPSSatellites", "XMP-exif:GPSSatellites"),
    ExifToXmpMapping("GPS", "GPSStatus", "XMP-exif:GPSStatus"),
    ExifToXmpMapping("GPS", "GPSMeasureMode", "XMP-exif:GPSMeasureMode"),
    ExifToXmpMapping("GPS", "GPSDOP", "XMP-exif:GPSDOP"),
    ExifToXmpMapping("GPS", "GPSSpeedRef", "XMP-exif:GPSSpeedRef"),
    ExifToXmpMapping("GPS", "GPSSpeed", "XMP-exif:GPSSpeed"),
    ExifToXmpMapping("GPS", "GPSTrackRef", "XMP-exif:GPSTrackRef"),
    ExifToXmpMapping("GPS", "GPSTrack", "XMP-exif:GPSTrack"),
    ExifToXmpMapping("GPS", "GPSImgDirectionRef", "XMP-exif:GPSImgDirectionRef"),
    ExifToXmpMapping("GPS", "GPSImgDirection", "XMP-exif:GPSImgDirection"),
    ExifToXmpMapping("GPS", "GPSMapDatum", "XMP-exif:GPSMapDatum"),
    ExifToXmpMapping("GPS", "GPSDestLatitude", "XMP-exif:GPSDestLatitude", "xmp_gps_dest_latitude"),
    ExifToXmpMapping(
        "GPS",
        "GPSDestLongitude",
        "XMP-exif:GPSDestLongitude",
        "xmp_gps_dest_longitude",
    ),
    ExifToXmpMapping("GPS", "GPSDestBearingRef", "XMP-exif:GPSDestBearingRef"),
    ExifToXmpMapping("GPS", "GPSDestBearing", "XMP-exif:GPSDestBearing"),
    ExifToXmpMapping("GPS", "GPSDestDistanceRef", "XMP-exif:GPSDestDistanceRef"),
    ExifToXmpMapping("GPS", "GPSDestDistance", "XMP-exif:GPSDestDistance"),
    ExifToXmpMapping("GPS", "GPSDifferential", "XMP-exif:GPSDifferential"),
    ExifToXmpMapping("GPS", "GPSHPositioningError", "XMP-exif:GPSHPositioningError"),
)

IFD0_SOURCE_TAGS = {
    0x010E: "ImageDescription",
    0x010F: "Make",
    0x0110: "Model",
    0x0112: "Orientation",
    0x011A: "XResolution",
    0x011B: "YResolution",
    0x0128: "ResolutionUnit",
    0x0132: "ModifyDate",
    0x013B: "Artist",
    0x0213: "YCbCrPositioning",
    0x8298: "Copyright",
}
EXIF_SOURCE_TAGS = {
    0x829A: "ExposureTime",
    0x829D: "FNumber",
    0x8827: "ISO",
    0x9000: "ExifVersion",
    0x9003: "DateTimeOriginal",
    0x9004: "CreateDate",
    0x9101: "ComponentsConfiguration",
    0x9102: "CompressedBitsPerPixel",
    0x9201: "ShutterSpeedValue",
    0x9202: "ApertureValue",
    0x9204: "ExposureCompensation",
    0x9205: "MaxApertureValue",
    0x9207: "MeteringMode",
    0x920A: "FocalLength",
    0x9286: "UserComment",
    0xA000: "FlashpixVersion",
    0xA001: "ColorSpace",
    0xA002: "ExifImageWidth",
    0xA003: "ExifImageHeight",
    0xA20E: "FocalPlaneXResolution",
    0xA20F: "FocalPlaneYResolution",
    0xA210: "FocalPlaneResolutionUnit",
    0xA217: "SensingMethod",
    0xA300: "FileSource",
    0xA401: "CustomRendered",
    0xA402: "ExposureMode",
    0xA403: "WhiteBalance",
    0xA406: "SceneCaptureType",
}
INTEROP_SOURCE_TAGS = {
    0x0001: "InteropIndex",
}
GPS_SOURCE_TAGS = {
    0x0002: "GPSLatitude",
    0x0004: "GPSLongitude",
    0x0005: "GPSAltitudeRef",
    0x0006: "GPSAltitude",
    0x0008: "GPSSatellites",
    0x0009: "GPSStatus",
    0x000A: "GPSMeasureMode",
    0x000B: "GPSDOP",
    0x000C: "GPSSpeedRef",
    0x000D: "GPSSpeed",
    0x000E: "GPSTrackRef",
    0x000F: "GPSTrack",
    0x0010: "GPSImgDirectionRef",
    0x0011: "GPSImgDirection",
    0x0012: "GPSMapDatum",
    0x0014: "GPSDestLatitude",
    0x0016: "GPSDestLongitude",
    0x0017: "GPSDestBearingRef",
    0x0018: "GPSDestBearing",
    0x0019: "GPSDestDistanceRef",
    0x001A: "GPSDestDistance",
    0x001E: "GPSDifferential",
    0x001F: "GPSHPositioningError",
}


def xmp_copy_plan_from_request_payload(payload: JsonObject) -> XmpCopyFromFilePlan:
    write_args = tuple(json_string_array_value(payload, "write_args"))
    return parse_xmp_copy_from_file_args(write_args)


def xmp_copy_request_id(payload: JsonObject) -> str | None:
    return json_string_value(payload, "request_id")


def parse_xmp_copy_from_file_args(write_args: tuple[str, ...]) -> XmpCopyFromFilePlan:
    source_filename: str | None = None
    routes: list[XmpCopyRoute] = []
    index = 0
    while index < len(write_args):
        arg = write_args[index]
        if arg == "-tagsFromFile":
            if index + 1 >= len(write_args):
                raise ValueError("Missing tagsFromFile source filename")
            source_filename = write_args[index + 1]
            index += 2
            continue
        if source_filename is not None and arg.startswith("-"):
            routes.append(parse_xmp_copy_route(arg[1:]))
        index += 1
    if source_filename is None:
        raise ValueError("Request does not contain -tagsFromFile")
    if not routes:
        raise ValueError("Request does not contain supported tagsFromFile copy routes")
    copy_routes = tuple(routes)
    strategy = xmp_copy_strategy(copy_routes)
    return XmpCopyFromFilePlan(
        source_filename=source_filename,
        routes=copy_routes,
        strategy=strategy,
        packet_transform=packet_transform_for_strategy(strategy),
        evidence_ids=(TAGS_FROM_FILE_SOURCE, XMP_TABLE_SOURCE, XMP_WRITER_SOURCE),
    )


def parse_xmp_copy_route(token: str) -> XmpCopyRoute:
    redirect_match = _COPY_REDIRECT_RE.fullmatch(token)
    if redirect_match is not None:
        source_token = redirect_match.group("src").strip()
        destination_token = redirect_match.group("dst").strip()
    else:
        source_token = token.strip()
        destination_token = token.strip()
    source = parse_xmp_copy_source_selector(source_token)
    destination = parse_xmp_copy_destination_selector(destination_token)
    return XmpCopyRoute(source=source, destination=destination, raw_argument=token)


def parse_xmp_copy_source_selector(token: str) -> XmpCopySourceSelector:
    group, tag_pattern = parse_group_tag_selector(token)
    if group == "all":
        source_group: XmpCopySourceGroup = "ALL"
    elif group == "exif":
        source_group = "EXIF"
    elif group == "gps":
        source_group = "GPS"
    elif group == "xmp":
        source_group = "XMP"
    else:
        raise ValueError(f"Unsupported tagsFromFile XMP source selector: {token}")
    return XmpCopySourceSelector(source_group, tag_pattern, token)


def parse_xmp_copy_destination_selector(token: str) -> XmpCopyDestinationSelector:
    group, tag_pattern = parse_group_tag_selector(token)
    if group == "all":
        destination_group: XmpCopyDestinationGroup = "ALL"
    elif group == "xmp" or group.startswith("xmp-"):
        destination_group = "XMP"
    else:
        raise ValueError(f"Unsupported tagsFromFile XMP destination selector: {token}")
    return XmpCopyDestinationSelector(destination_group, tag_pattern, token)


def parse_group_tag_selector(token: str) -> tuple[str, XmpCopyTagPattern]:
    group, separator, tag = token.lower().partition(":")
    if separator != ":" or not tag:
        raise ValueError(f"Unsupported tagsFromFile selector: {token}")
    if not re.fullmatch(r"[-\w?*]+", tag):
        raise ValueError(f"Unsupported tagsFromFile selector: {token}")
    return group, "*" if tag == "all" else tag


def xmp_copy_strategy(routes: tuple[XmpCopyRoute, ...]) -> XmpSidecarCopyStrategy:
    if routes and all(route_is_exact_exif_gps_to_xmp(route) for route in routes):
        return "copy_exact_exif_to_xmp_assignments"
    if routes and all(
        route.source.group in {"EXIF", "GPS"} and route.destination.group == "XMP"
        for route in routes
    ):
        return "copy_exact_exif_to_xmp_assignments"
    if len(routes) != 1:
        raise ValueError("Only single-route XMP sidecar copy plans are currently supported")
    route = routes[0]
    if route.source.group == "ALL" and route.destination.group == "ALL":
        return "copy_all_metadata_packet"
    if route.source.group == "XMP" and route.destination.group == "XMP":
        return "copy_xmp_writable_packet"
    if route.source.group == "EXIF" and route.destination.group == "XMP":
        return "copy_exif_to_xmp_assignments"
    raise ValueError(f"Unsupported XMP sidecar copy route: {route.raw_argument}")


def route_is_exact_exif_gps_to_xmp(route: XmpCopyRoute) -> bool:
    if route.source.group not in {"EXIF", "GPS"} or route.destination.group != "XMP":
        return False
    return not _selector_is_pattern(route.source.tag_pattern) and not _selector_is_pattern(
        route.destination.tag_pattern
    )


def _selector_is_pattern(tag_pattern: str) -> bool:
    return tag_pattern in {"*", "all"} or "*" in tag_pattern or "?" in tag_pattern


def packet_transform_for_strategy(strategy: XmpSidecarCopyStrategy) -> XmpPacketTransform:
    if strategy == "copy_xmp_writable_packet":
        return "filter_user_defined_xmp"
    return "update_toolkit"


def materialize_xmp_copy_from_file_plan(
    copy_plan: XmpCopyFromFilePlan,
    source_path: Path,
) -> XmpMaterializedCopyFromFilePlan:
    if copy_plan.strategy not in {
        "copy_exif_to_xmp_assignments",
        "copy_exact_exif_to_xmp_assignments",
    }:
        return XmpMaterializedCopyFromFilePlan(copy_plan, (), ())
    mappings = mappings_for_copy_plan(copy_plan)
    if not mappings:
        return XmpMaterializedCopyFromFilePlan(
            copy_plan=copy_plan,
            assignments=(),
            diagnostics=(
                XmpCopyFromFileDiagnostic(
                    "exact_copy_mapping",
                    "missing_exact_copy_mapping",
                    "Exact EXIF/GPS-to-XMP copy plans require TagLookup-backed mappings.",
                ),
            ),
        )
    source_tags = exif_source_tags(source_path)
    assignments: list[XmpDestinationAssignment] = []
    diagnostics: list[XmpCopyFromFileDiagnostic] = []
    for mapping in mappings:
        source_tag = source_tags.get((mapping.source_group, mapping.source_name))
        if source_tag is None:
            continue
        values = xmp_assignment_values_for_source_tag(source_tag, mapping)
        if not values:
            diagnostics.append(
                XmpCopyFromFileDiagnostic(
                    mapping.source_name,
                    "unsupported_source_value",
                    f"Could not convert {mapping.source_group}:{mapping.source_name} to XMP.",
                )
            )
            continue
        assignments.extend(
            XmpDestinationAssignment(mapping.property_name, value) for value in values
        )
    return XmpMaterializedCopyFromFilePlan(
        copy_plan=copy_plan,
        assignments=tuple(assignments),
        diagnostics=tuple(diagnostics),
    )


def mappings_for_copy_plan(copy_plan: XmpCopyFromFilePlan) -> tuple[ExifToXmpMapping, ...]:
    if copy_plan.exact_mappings:
        mappings: list[ExifToXmpMapping] = []
        for exact_mapping in copy_plan.exact_mappings:
            mapping = exif_to_xmp_mapping_for_exact_copy(exact_mapping)
            if mapping is not None:
                mappings.append(mapping)
        return tuple(mappings)
    return tuple(
        mapping
        for mapping in EXIF_TO_XMP_MAPPINGS
        if any(mapping_matches_copy_route(mapping, route) for route in copy_plan.routes)
    )


def mapping_matches_copy_route(mapping: ExifToXmpMapping, route: XmpCopyRoute) -> bool:
    return source_mapping_matches_selector(
        mapping, route.source
    ) and destination_mapping_matches_selector(mapping, route.destination)


def source_mapping_matches_selector(
    mapping: ExifToXmpMapping,
    selector: XmpCopySourceSelector,
) -> bool:
    if selector.group == "GPS" and mapping.source_group != "GPS":
        return False
    if selector.group not in {"EXIF", "GPS"}:
        return False
    return selector_matches_name(selector.tag_pattern, mapping.source_name)


def destination_mapping_matches_selector(
    mapping: ExifToXmpMapping,
    selector: XmpCopyDestinationSelector,
) -> bool:
    destination_group, destination_tag = xmp_property_group_and_tag(mapping.property_name)
    selector_group, _, _ = selector.raw_token.partition(":")
    if selector_group.lower() not in {"xmp", "all", "*"}:
        canonical_group = canonical_copy_xmp_group(selector_group)
        if canonical_group is None or canonical_group.lower() != destination_group.lower():
            return False
    return selector_matches_name(selector.tag_pattern, destination_tag)


def xmp_property_group_and_tag(property_name: str) -> tuple[str, str]:
    group, _, tag = property_name.partition(":")
    return group, tag


def canonical_copy_xmp_group(value: str) -> str | None:
    if value.lower().startswith("xmp-"):
        return "XMP-" + value[4:]
    return None


def selector_matches_name(pattern: XmpCopyTagPattern, name: str) -> bool:
    if pattern in {"*", "all"}:
        return True
    return fnmatchcase(name.lower(), pattern.lower())


def exif_to_xmp_mapping_for_exact_copy(
    exact_mapping: TagLookupExactCopyMapping,
) -> ExifToXmpMapping | None:
    for mapping in EXIF_TO_XMP_MAPPINGS:
        if (
            mapping.source_group == exact_mapping.source_data_group
            and mapping.source_name == exact_mapping.source_data_name
            and mapping.property_name == exact_mapping.destination_property_name
        ):
            return mapping
    return None


def exif_source_tags(path: Path) -> dict[tuple[str, str], ExifSourceTag]:
    tiff_data = exif_source_tiff_data(path)
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    tags: dict[tuple[str, str], ExifSourceTag] = {}
    tags.update(
        source_tags_from_ifd(
            tiff_data,
            ifd0.entries,
            header.endian,
            "IFD0",
            IFD0_SOURCE_TAGS,
        )
    )
    gps_ifd_offset = integer_entry_value(tiff_data, ifd0.entries, header.endian, 0x8825)
    if gps_ifd_offset is not None:
        gps_ifd = parse_ifd(tiff_data, gps_ifd_offset, header.endian)
        tags.update(
            source_tags_from_ifd(
                tiff_data,
                gps_ifd.entries,
                header.endian,
                "GPS",
                GPS_SOURCE_TAGS,
            )
        )
    exif_ifd_offset = integer_entry_value(tiff_data, ifd0.entries, header.endian, 0x8769)
    if exif_ifd_offset is None:
        return tags
    exif_ifd = parse_ifd(tiff_data, exif_ifd_offset, header.endian)
    tags.update(
        source_tags_from_ifd(
            tiff_data,
            exif_ifd.entries,
            header.endian,
            "ExifIFD",
            EXIF_SOURCE_TAGS,
        )
    )
    interop_ifd_offset = integer_entry_value(tiff_data, exif_ifd.entries, header.endian, 0xA005)
    if interop_ifd_offset is None:
        return tags
    interop_ifd = parse_ifd(tiff_data, interop_ifd_offset, header.endian)
    tags.update(
        source_tags_from_ifd(
            tiff_data,
            interop_ifd.entries,
            header.endian,
            "InteropIFD",
            INTEROP_SOURCE_TAGS,
        )
    )
    return tags


def exif_source_tiff_data(path: Path) -> bytes:
    prefix = source_path_header_prefix(path)
    if bigtiff_header_data(prefix):
        raise ValueError(
            "BigTIFF exact-copy source materialization is blocked: ExifTool routes TIFF "
            "magic 0x2b through BigTIFF::ProcessBTF, and ExifModern's native BigTIFF "
            "reader currently exposes bounded public IFD0 read-graph tags, not the "
            "EXIF/GPS source tags required by TagLookup exact-copy materialization."
        )
    if exif_tiff_header_data(prefix):
        return path.read_bytes()
    return read_exif_app1(path).tiff_data


def source_path_has_exif_tiff_header(path: Path) -> bool:
    try:
        data = source_path_header_prefix(path)
    except OSError:
        return False
    return exif_tiff_header_data(data) or bigtiff_header_data(data)


def source_path_has_bigtiff_header(path: Path) -> bool:
    try:
        return bigtiff_header_data(source_path_header_prefix(path))
    except OSError:
        return False


def source_path_header_prefix(path: Path) -> bytes:
    prefix_size = max(
        len(prefix) for prefix in (*EXIF_TIFF_HEADER_PREFIXES, *BIGTIFF_HEADER_PREFIXES)
    )
    with path.open("rb") as file:
        return file.read(prefix_size)


def exif_tiff_header_data(data: bytes) -> bool:
    return any(data.startswith(prefix) for prefix in EXIF_TIFF_HEADER_PREFIXES)


def bigtiff_header_data(data: bytes) -> bool:
    return any(data.startswith(prefix) for prefix in BIGTIFF_HEADER_PREFIXES)


def source_tags_from_ifd(
    tiff_data: bytes,
    entries: list[IfdEntry],
    endian: Literal["little", "big"],
    group: str,
    tag_names: dict[int, str],
) -> dict[tuple[str, str], ExifSourceTag]:
    tags: dict[tuple[str, str], ExifSourceTag] = {}
    for entry in entries:
        name = tag_names.get(entry.tag_id)
        if name is None:
            continue
        tags[(group, name)] = ExifSourceTag(
            group=group,
            name=name,
            value=read_entry_value(tiff_data, entry, endian),
            field_type=entry.field_type,
        )
    return tags


def integer_entry_value(
    tiff_data: bytes,
    entries: list[IfdEntry],
    endian: Literal["little", "big"],
    tag_id: int,
) -> int | None:
    for entry in entries:
        if entry.tag_id != tag_id:
            continue
        value = read_entry_value(tiff_data, entry, endian)
        return value if isinstance(value, int) else None
    return None


def xmp_assignment_values_for_source_tag(
    source_tag: ExifSourceTag,
    mapping: ExifToXmpMapping,
) -> tuple[str, ...]:
    value = source_tag.value
    if mapping.conversion == "xmp_date":
        return (xmp_date_value(value),) if isinstance(value, str) else ()
    if mapping.conversion == "components_configuration":
        return tuple(str(byte) for byte in value) if isinstance(value, bytes) else ()
    if mapping.conversion == "empty_user_comment":
        return ("",)
    if mapping.conversion == "shutter_speed_value":
        return (shutter_speed_xmp_value(value),) if isinstance(value, Fraction) else ()
    if mapping.conversion == "aperture_value":
        return (aperture_xmp_value(value),) if isinstance(value, Fraction) else ()
    if mapping.conversion == "xmp_gps_latitude":
        gps_value = xmp_gps_coordinate_value(value, "N")
        return (gps_value,) if gps_value is not None else ()
    if mapping.conversion == "xmp_gps_longitude":
        gps_value = xmp_gps_coordinate_value(value, "E")
        return (gps_value,) if gps_value is not None else ()
    if mapping.conversion == "xmp_gps_dest_latitude":
        gps_value = xmp_gps_coordinate_value(value, "N")
        return (gps_value,) if gps_value is not None else ()
    if mapping.conversion == "xmp_gps_dest_longitude":
        gps_value = xmp_gps_coordinate_value(value, "E")
        return (gps_value,) if gps_value is not None else ()
    return raw_xmp_values(value, source_tag.field_type)


def raw_xmp_values(value: TiffValue, field_type: int) -> tuple[str, ...]:
    if isinstance(value, Fraction):
        return (fraction_text(value, force_denominator=field_type in RATIONAL_FIELD_TYPES),)
    if isinstance(value, int):
        return (str(value),)
    if isinstance(value, str):
        return (value.rstrip("\x00"),)
    if isinstance(value, bytes):
        if len(value) == 1:
            return (str(value[0]),)
        return (value.rstrip(b"\x00").decode("ascii", errors="replace"),)
    if isinstance(value, list):
        return tuple(raw_list_item_text(item) for item in value)
    return ()


RATIONAL_FIELD_TYPES = {TIFF_TYPE_RATIONAL, TIFF_TYPE_SRATIONAL}


def raw_list_item_text(value: Fraction | int | None) -> str:
    if isinstance(value, Fraction):
        return fraction_text(value, force_denominator=True)
    if isinstance(value, int):
        return str(value)
    return ""


def xmp_date_value(value: str) -> str:
    date, separator, time = value.partition(" ")
    if separator == " " and date.count(":") == 2:
        return f"{date.replace(':', '-')}T{time}"
    return value


def shutter_speed_xmp_value(value: Fraction) -> str:
    if value.numerator <= -2147483648:
        return "0/1"
    seconds = math.pow(2, -float(value))
    if seconds <= 0:
        return "0/1"
    apex_value = -math.log(seconds) / math.log(2)
    return rationalized_float_text(apex_value)


def aperture_xmp_value(value: Fraction) -> str:
    aperture = round(math.pow(math.sqrt(2), float(value)), 1)
    apex_value = 2 * math.log(aperture) / math.log(2)
    return rationalized_float_text(apex_value)


def fraction_text(value: Fraction, *, force_denominator: bool) -> str:
    if force_denominator:
        return f"{value.numerator}/{value.denominator}"
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def rationalized_float_text(value: float) -> str:
    numerator, denominator = rationalize(value, 0xFFFFFFFF)
    return f"{numerator}/{denominator}"


def xmp_gps_coordinate_value(
    value: TiffValue,
    positive_ref: Literal["N", "E"],
) -> str | None:
    coordinate = numeric_tiff_triplet(value)
    if coordinate is None:
        return None
    degrees, minutes, seconds = coordinate
    decimal_minutes = float(minutes) + (float(seconds) / 60.0)
    return f"{int(degrees)},{trimmed_decimal_text(decimal_minutes)}{positive_ref}"


def numeric_tiff_triplet(
    value: TiffValue,
) -> tuple[Fraction | int, Fraction | int, Fraction | int] | None:
    if not isinstance(value, list) or len(value) < 3:
        return None
    first, second, third = value[0], value[1], value[2]
    if not isinstance(first, (Fraction, int)):
        return None
    if not isinstance(second, (Fraction, int)):
        return None
    if not isinstance(third, (Fraction, int)):
        return None
    return first, second, third


def trimmed_decimal_text(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def rationalize(value: float, max_int: int) -> tuple[int, int]:
    if value == 0:
        return 0, 1
    sign = -1 if value < 0 else 1
    positive = abs(value)
    fraction = positive
    parts: list[int] = []
    best: tuple[int, int] | None = None
    while True:
        numerator, denominator = assemble_rational(int(fraction + 0.5), 1, tuple(parts))
        if numerator > max_int or denominator > max_int:
            if best is not None:
                break
            if positive < 1:
                return sign, max_int
            return sign * max_int, 1
        best = (numerator, denominator)
        error = ((numerator / denominator) - positive) / positive
        if abs(error) < 1e-8:
            break
        integer_part = int(fraction)
        parts.insert(0, integer_part)
        fraction -= integer_part
        if fraction == 0:
            break
        fraction = 1 / fraction
    if best is None:
        return 0, 1
    return best[0] * sign, best[1]


def assemble_rational(
    numerator: int,
    denominator: int,
    previous_parts: tuple[int, ...],
) -> tuple[int, int]:
    current_numerator = numerator
    current_denominator = denominator
    for part in previous_parts:
        current_numerator, current_denominator = (
            current_denominator + current_numerator * part,
            current_numerator,
        )
    return current_numerator, current_denominator


def transform_xmp_packet_for_copy(packet: bytes, transform: XmpPacketTransform) -> bytes:
    transformed = update_xmp_toolkit(packet)
    if transform == "filter_user_defined_xmp":
        transformed = remove_user_defined_xmp_namespaces(transformed)
    return transformed


def update_xmp_toolkit(packet: bytes) -> bytes:
    replacement = b"x:xmptk='" + _EXIFTOOL_VERSION_TEXT + b"'"
    if _XMP_TOOLKIT_RE.search(packet):
        return _XMP_TOOLKIT_RE.sub(replacement, packet, count=1)
    return packet


def remove_user_defined_xmp_namespaces(packet: bytes) -> bytes:
    prefixes = tuple(match.group("prefix") for match in _CUSTOM_XMP_NAMESPACE_RE.finditer(packet))
    filtered = _CUSTOM_XMP_NAMESPACE_RE.sub(b"", packet)
    for prefix in prefixes:
        filtered = remove_prefixed_elements(filtered, prefix)
    return filtered


def remove_prefixed_elements(packet: bytes, prefix: bytes) -> bytes:
    element_name = re.escape(prefix) + rb":[-A-Za-z0-9_]+"
    pattern = re.compile(
        rb"\n[ \t]*<(?P<name>" + element_name + rb")\b[^>]*>.*?</(?P=name)>",
        flags=re.DOTALL,
    )
    previous = b""
    current = packet
    while current != previous:
        previous = current
        current = pattern.sub(b"", current)
    return current
