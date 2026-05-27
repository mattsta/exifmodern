"""Source-backed JPEG.pm APP-segment route planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type JpegSourceSegment = Literal[
    "APP0",
    "APP1",
    "APP2",
    "APP3",
    "APP4",
    "APP5",
    "APP6",
    "APP7",
    "APP8",
    "APP9",
    "APP10",
    "APP11",
    "APP12",
    "APP13",
    "APP14",
    "APP15",
]
type JpegSourceRoute = Literal[
    "adobe",
    "adobe_cm",
    "avi1",
    "ducky",
    "eppim",
    "exif",
    "gopro",
    "graphconv",
    "hdr_gain_info",
    "icc_profile",
    "jfif",
    "jps",
    "jpeg_hdr",
    "jumbf",
    "media_jukebox",
    "mpf",
    "nitf",
    "pentax",
    "picture_info",
    "photoshop",
    "qualcomm",
    "ricoh",
    "scalado",
    "spiff",
    "unknown",
    "xmp",
]
type JpegSourceBlockerCode = Literal["rewrite_not_supported", "unsupported_segment"]


@dataclass(frozen=True)
class JpegSourceSegmentRequest:
    marker: JpegSourceSegment
    payload_prefix: bytes


@dataclass(frozen=True)
class JpegSourceBlocker:
    code: JpegSourceBlockerCode
    detail: str
    source_symbol: str


@dataclass(frozen=True)
class JpegSourceSegmentPlan:
    request: JpegSourceSegmentRequest
    route: JpegSourceRoute
    table_name: str | None
    source_symbol: str


@dataclass(frozen=True)
class JpegSourceSegmentTransactionPlan:
    segments: tuple[JpegSourceSegmentPlan, ...]
    blockers: tuple[JpegSourceBlocker, ...]
    source_symbols: tuple[str, ...]
    can_mutate_metadata: bool
    can_emit_metadata: bool


_SOURCE_SYMBOLS = (
    "Image::ExifTool::JPEG::Main",
    "Image::ExifTool::JPEG::HDRGainInfo",
    "Image::ExifTool::JPEG::SPIFF",
    "Image::ExifTool::JPEG::Adobe",
)


def build_jpeg_source_segment_plan(
    segments: tuple[JpegSourceSegmentRequest, ...],
    *,
    rewrite: bool = False,
) -> JpegSourceSegmentTransactionPlan:
    planned = tuple(_plan_segment(segment) for segment in segments)
    blockers: tuple[JpegSourceBlocker, ...] = ()
    if rewrite:
        blockers = (
            JpegSourceBlocker(
                code="rewrite_not_supported",
                detail=(
                    "JPEG.pm defines uncommon segment extraction tables; writers live elsewhere."
                ),
                source_symbol="Image::ExifTool::JPEG::Main",
            ),
        )
    return JpegSourceSegmentTransactionPlan(
        segments=planned,
        blockers=blockers,
        source_symbols=_SOURCE_SYMBOLS,
        can_mutate_metadata=False,
        can_emit_metadata=not blockers,
    )


def _plan_segment(segment: JpegSourceSegmentRequest) -> JpegSourceSegmentPlan:
    payload = segment.payload_prefix
    if segment.marker == "APP0" and payload.startswith(b"JFIF\x00"):
        return _segment_plan(segment, "jfif", "Image::ExifTool::JFIF::Main")
    if segment.marker == "APP0" and payload.startswith(b"AVI1"):
        return _segment_plan(segment, "avi1", "Image::ExifTool::JPEG::AVI1")
    if segment.marker == "APP1" and payload.startswith(b"Exif\x00"):
        return _segment_plan(segment, "exif", "Image::ExifTool::Exif::Main")
    if segment.marker == "APP1" and (payload.startswith(b"http") or b"<exif:" in payload):
        return _segment_plan(segment, "xmp", "Image::ExifTool::XMP::Main")
    if segment.marker == "APP2" and payload.startswith(b"ICC_PROFILE\x00"):
        return _segment_plan(segment, "icc_profile", "Image::ExifTool::ICC_Profile::Main")
    if segment.marker == "APP2" and payload.startswith(b"MPF\x00"):
        return _segment_plan(segment, "mpf", "Image::ExifTool::MPF::Main")
    if segment.marker == "APP4" and payload.startswith(b"SCALADO\x00"):
        return _segment_plan(segment, "scalado", "Image::ExifTool::Scalado::Main")
    if segment.marker == "APP6" and payload.startswith(b"EPPIM\x00"):
        return _segment_plan(segment, "eppim", "Image::ExifTool::JPEG::EPPIM")
    if segment.marker == "APP6" and payload.startswith(b"NTIF\x00"):
        return _segment_plan(segment, "nitf", "Image::ExifTool::JPEG::NITF")
    if segment.marker == "APP6" and payload.startswith(b"GoPro\x00"):
        return _segment_plan(segment, "gopro", "Image::ExifTool::GoPro::GPMF")
    if segment.marker == "APP7" and payload.startswith(b"PENTAX \x00"):
        return _segment_plan(segment, "pentax", "Image::ExifTool::Pentax::Main")
    if segment.marker == "APP7" and payload.startswith(b"RICOH\x00"):
        return _segment_plan(segment, "ricoh", "Image::ExifTool::Pentax::Main")
    if segment.marker == "APP7" and payload.startswith(b"\x1aQualcomm Camera Attributes"):
        return _segment_plan(segment, "qualcomm", "Image::ExifTool::Qualcomm::Main")
    if segment.marker == "APP8" and payload.startswith(b"SPIFF\x00"):
        return _segment_plan(segment, "spiff", "Image::ExifTool::JPEG::SPIFF")
    if segment.marker == "APP9" and payload.startswith(b"Media Jukebox\x00"):
        return _segment_plan(segment, "media_jukebox", "Image::ExifTool::JPEG::MediaJukebox")
    if segment.marker == "APP10" and payload.startswith(b"UNICODE\x00"):
        return _segment_plan(segment, "unknown", None)
    if segment.marker == "APP10" and payload.startswith(b"AROT\x00\x00"):
        return _segment_plan(segment, "hdr_gain_info", "Image::ExifTool::JPEG::HDRGainInfo")
    if segment.marker == "APP11" and payload.startswith(b"JPEG-HDR"):
        return _segment_plan(segment, "jpeg_hdr", "Image::ExifTool::JPEG::HDR")
    if segment.marker == "APP11" and payload.startswith(b"HDR_RI "):
        return _segment_plan(segment, "jpeg_hdr", "Image::ExifTool::JPEG::HDR")
    if segment.marker == "APP11" and payload.startswith(b"JP"):
        return _segment_plan(segment, "jumbf", "Image::ExifTool::Jpeg2000::Main")
    if segment.marker == "APP12" and (b"[picture info]" in payload or b"Type=" in payload):
        return _segment_plan(segment, "picture_info", "Image::ExifTool::APP12::PictureInfo")
    if segment.marker == "APP12" and payload.startswith(b"Ducky"):
        return _segment_plan(segment, "ducky", "Image::ExifTool::APP12::Ducky")
    if segment.marker == "APP13" and payload.startswith(b"Photoshop 3.0\x00"):
        return _segment_plan(segment, "photoshop", "Image::ExifTool::Photoshop::Main")
    if segment.marker == "APP13" and payload.startswith(b"Adobe_Photoshop2.5"):
        return _segment_plan(segment, "photoshop", "Image::ExifTool::Photoshop::Main")
    if segment.marker == "APP13" and payload.startswith(b"Adobe_CM"):
        return _segment_plan(segment, "adobe_cm", "Image::ExifTool::JPEG::AdobeCM")
    if segment.marker == "APP14" and payload.startswith(b"Adobe"):
        return _segment_plan(segment, "adobe", "Image::ExifTool::JPEG::Adobe")
    if segment.marker == "APP15" and payload.startswith(b"Q"):
        return _segment_plan(segment, "graphconv", "Image::ExifTool::JPEG::GraphConv")
    return _segment_plan(segment, "unknown", None)


def _segment_plan(
    segment: JpegSourceSegmentRequest,
    route: JpegSourceRoute,
    table_name: str | None,
) -> JpegSourceSegmentPlan:
    return JpegSourceSegmentPlan(
        request=segment,
        route=route,
        table_name=table_name,
        source_symbol="Image::ExifTool::JPEG::Main",
    )
