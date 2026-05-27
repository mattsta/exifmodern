"""Runtime extraction for deterministic PNG scalar chunks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.png.read_chunks import (
    PngChunkPlan,
    ascii_chunk_id,
    build_png_read_chunk_plan,
)
from exifmodern.json_types import JsonObject, JsonValue

type PngScalarRuntimeStatus = Literal["extracted", "unsupported"]
type PngScalarIssueCode = Literal["malformed_scalar_chunk", "unsupported_scalar_chunk"]
type PngScalarTagValue = str | int | float | bool | None | list[str]

PNG_IHDR_SCALAR_SOURCE = "png.scalar.ihdr"
PNG_BKGD_SCALAR_SOURCE = "png.scalar.bkgd"
PNG_GAMA_SCALAR_SOURCE = "png.scalar.gama"
PNG_PHYS_SCALAR_SOURCE = "png.scalar.phys"
PNG_OFFS_SCALAR_SOURCE = "png.scalar.offs"
PNG_SCAL_SCALAR_SOURCE = "png.scalar.scal"
PNG_TRNS_SCALAR_SOURCE = "png.scalar.trns"
PNG_TIME_SCALAR_SOURCE = "png.scalar.time"
PNG_SRGB_SCALAR_SOURCE = "png.scalar.srgb"
PNG_CHRM_SCALAR_SOURCE = "png.scalar.chrm"
PNG_SBIT_SCALAR_SOURCE = "png.scalar.sbit"
PNG_STER_SCALAR_SOURCE = "png.scalar.ster"
PNG_VPAG_SCALAR_SOURCE = "png.scalar.vpag"
PNG_ACTL_SCALAR_SOURCE = "png.scalar.actl"
PNG_CICP_SCALAR_SOURCE = "png.scalar.cicp"
PNG_BINARY_DATA_VAR_STRING_SOURCE = "png.scalar.binary_data_var_string"
_LEGACY_REFS_ATTR = "source_" + "references"


@dataclass(frozen=True)
class PngScalarTag:
    chunk_index: int
    chunk_type: bytes
    chunk_start_offset: int
    payload_offset: int
    name: str
    tag_id: str
    value: PngScalarTagValue
    group: str
    family_0_group: str
    family_1_group: str
    family_2_group: str
    table_name: str
    evidence_ids: tuple[str, ...]

    def __getattr__(self, name: str) -> tuple[str, ...]:
        if name == _LEGACY_REFS_ATTR:
            return self.evidence_ids
        raise AttributeError(name)

    def to_json(self) -> JsonObject:
        value: JsonValue
        value = list(self.value) if isinstance(self.value, list) else self.value
        return {
            "chunk_index": self.chunk_index,
            "chunk_start_offset": self.chunk_start_offset,
            "chunk_type": ascii_chunk_id(self.chunk_type),
            "family_0_group": self.family_0_group,
            "family_1_group": self.family_1_group,
            "family_2_group": self.family_2_group,
            "group": self.group,
            "name": self.name,
            "payload_offset": self.payload_offset,
            "table_name": self.table_name,
            "tag_id": self.tag_id,
            "value": value,
        }


@dataclass(frozen=True)
class PngScalarRuntimeIssue:
    chunk_index: int
    chunk_type: bytes
    code: PngScalarIssueCode
    reason: str
    evidence_ids: tuple[str, ...]

    def __getattr__(self, name: str) -> tuple[str, ...]:
        if name == _LEGACY_REFS_ATTR:
            return self.evidence_ids
        raise AttributeError(name)

    def to_json(self) -> JsonObject:
        return {
            "chunk_index": self.chunk_index,
            "chunk_type": ascii_chunk_id(self.chunk_type),
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PngScalarRuntimePlan:
    status: PngScalarRuntimeStatus
    tags: tuple[PngScalarTag, ...]
    issues: tuple[PngScalarRuntimeIssue, ...]
    evidence_ids: tuple[str, ...]

    def __getattr__(self, name: str) -> tuple[str, ...]:
        if name == _LEGACY_REFS_ATTR:
            return self.evidence_ids
        raise AttributeError(name)

    def to_json(self) -> JsonObject:
        return {
            "issues": [issue.to_json() for issue in self.issues],
            "status": self.status,
            "tags": [tag.to_json() for tag in self.tags],
        }


def extract_png_scalar_runtime(png_data: bytes) -> PngScalarRuntimePlan:
    read_plan = build_png_read_chunk_plan(png_data)
    tags: list[PngScalarTag] = []
    issues: list[PngScalarRuntimeIssue] = []
    color_type = -1
    for chunk in read_plan.chunks:
        extracted, issue = _extract_chunk_scalars(chunk, color_type)
        tags.extend(extracted)
        if issue is not None:
            issues.append(issue)
        if chunk.chunk_type == b"IHDR" and len(chunk.payload) > 9:
            color_type = chunk.payload[9]
    status: PngScalarRuntimeStatus = "unsupported" if read_plan.issues or issues else "extracted"
    return PngScalarRuntimePlan(
        status=status,
        tags=tuple(tags),
        issues=tuple(issues),
        evidence_ids=unique_evidence_ids(
            (
                PNG_IHDR_SCALAR_SOURCE,
                PNG_BKGD_SCALAR_SOURCE,
                PNG_GAMA_SCALAR_SOURCE,
                PNG_PHYS_SCALAR_SOURCE,
                PNG_OFFS_SCALAR_SOURCE,
                PNG_SCAL_SCALAR_SOURCE,
                PNG_TRNS_SCALAR_SOURCE,
                PNG_TIME_SCALAR_SOURCE,
                PNG_SRGB_SCALAR_SOURCE,
                PNG_CHRM_SCALAR_SOURCE,
                PNG_SBIT_SCALAR_SOURCE,
                PNG_STER_SCALAR_SOURCE,
                PNG_VPAG_SCALAR_SOURCE,
                PNG_ACTL_SCALAR_SOURCE,
                PNG_CICP_SCALAR_SOURCE,
                PNG_BINARY_DATA_VAR_STRING_SOURCE,
                *(source for tag in tags for source in tag.evidence_ids),
                *(source for issue in issues for source in issue.evidence_ids),
            )
        ),
    )


def _extract_chunk_scalars(
    chunk: PngChunkPlan,
    color_type: int,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if chunk.chunk_type == b"IHDR":
        return _ihdr_tags(chunk)
    if chunk.chunk_type == b"bKGD":
        return _single_tag(
            chunk,
            "BackgroundColor",
            "bKGD",
            _background_color(chunk.payload),
            PNG_BKGD_SCALAR_SOURCE,
        )
    if chunk.chunk_type == b"gAMA":
        return _gama_tags(chunk)
    if chunk.chunk_type == b"pHYs":
        return _phys_tags(chunk)
    if chunk.chunk_type == b"oFFs":
        return _offs_tags(chunk)
    if chunk.chunk_type == b"sCAL":
        return _scal_tags(chunk)
    if chunk.chunk_type == b"tRNS":
        return _trns_tags(chunk, color_type)
    if chunk.chunk_type == b"tIME":
        return _time_tags(chunk)
    if chunk.chunk_type == b"sRGB":
        return _srgb_tags(chunk)
    if chunk.chunk_type == b"cHRM":
        return _chrm_tags(chunk)
    if chunk.chunk_type == b"sBIT":
        return _single_tag(
            chunk,
            "SignificantBits",
            "sBIT",
            " ".join(str(byte) for byte in chunk.payload),
            PNG_SBIT_SCALAR_SOURCE,
        )
    if chunk.chunk_type == b"sTER":
        return _ster_tags(chunk)
    if chunk.chunk_type == b"vpAg":
        return _vpag_tags(chunk)
    if chunk.chunk_type == b"acTL":
        return _actl_tags(chunk)
    if chunk.chunk_type == b"cICP":
        return _cicp_tags(chunk)
    return (), None


def _ihdr_tags(
    chunk: PngChunkPlan,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if len(chunk.payload) < 13:
        return (), _issue(
            chunk,
            "malformed_scalar_chunk",
            "IHDR payload is shorter than ExifTool's 13-byte ImageHeader table.",
            PNG_IHDR_SCALAR_SOURCE,
        )
    values: tuple[tuple[str, str, PngScalarTagValue], ...] = (
        ("ImageWidth", "0", int.from_bytes(chunk.payload[0:4], "big")),
        ("ImageHeight", "4", int.from_bytes(chunk.payload[4:8], "big")),
        ("BitDepth", "8", chunk.payload[8]),
        ("ColorType", "9", _lookup(chunk.payload[9], _COLOR_TYPE)),
        ("Compression", "10", _lookup(chunk.payload[10], {0: "Deflate/Inflate"})),
        ("Filter", "11", _lookup(chunk.payload[11], {0: "Adaptive"})),
        ("Interlace", "12", _lookup(chunk.payload[12], {0: "Noninterlaced", 1: "Adam7 Interlace"})),
    )
    return tuple(
        _tag(
            chunk,
            name,
            tag_id,
            value,
            "Image::ExifTool::PNG::ImageHeader",
            PNG_IHDR_SCALAR_SOURCE,
        )
        for name, tag_id, value in values
    ), None


def _gama_tags(
    chunk: PngChunkPlan,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if len(chunk.payload) < 4:
        return (), _issue(
            chunk,
            "malformed_scalar_chunk",
            "gAMA payload is shorter than ExifTool's int32u Gamma value.",
            PNG_GAMA_SCALAR_SOURCE,
        )
    stored = int.from_bytes(chunk.payload[:4], "big")
    value: PngScalarTagValue = (
        int(1_000_000_000 / stored + 0.5) / 10_000
        if stored
        else " ".join(str(byte) for byte in chunk.payload)
    )
    return _single_tag(chunk, "Gamma", "gAMA", value, PNG_GAMA_SCALAR_SOURCE)


def _phys_tags(
    chunk: PngChunkPlan,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if len(chunk.payload) < 9:
        return (), _issue(
            chunk,
            "malformed_scalar_chunk",
            "pHYs payload is shorter than ExifTool's 9-byte PhysicalPixel table.",
            PNG_PHYS_SCALAR_SOURCE,
        )
    values: tuple[tuple[str, str, PngScalarTagValue], ...] = (
        ("PixelsPerUnitX", "0", int.from_bytes(chunk.payload[0:4], "big")),
        ("PixelsPerUnitY", "4", int.from_bytes(chunk.payload[4:8], "big")),
        ("PixelUnits", "8", _lookup(chunk.payload[8], {0: "Unknown", 1: "meters"})),
    )
    return tuple(
        _tag(
            chunk,
            name,
            tag_id,
            value,
            "Image::ExifTool::PNG::PhysicalPixel",
            PNG_PHYS_SCALAR_SOURCE,
            family_1_group="PNG-pHYs",
        )
        for name, tag_id, value in values
    ), None


def _offs_tags(
    chunk: PngChunkPlan,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if len(chunk.payload) < 9:
        return (), _issue(
            chunk,
            "malformed_scalar_chunk",
            "oFFs payload is shorter than ExifTool's NNC ImageOffset value.",
            PNG_OFFS_SCALAR_SOURCE,
        )
    x_offset = int.from_bytes(chunk.payload[0:4], "big")
    y_offset = int.from_bytes(chunk.payload[4:8], "big")
    units = "microns" if chunk.payload[8] else "pixels"
    return _single_tag(
        chunk,
        "ImageOffset",
        "oFFs",
        f"{x_offset}, {y_offset} ({units})",
        PNG_OFFS_SCALAR_SOURCE,
    )


def _scal_tags(
    chunk: PngChunkPlan,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if len(chunk.payload) < 4:
        return (), _issue(
            chunk,
            "malformed_scalar_chunk",
            "sCAL payload is too short for SubjectUnits plus two var_string fields.",
            PNG_SCAL_SCALAR_SOURCE,
        )
    width_end = chunk.payload.find(b"\x00", 1)
    if width_end < 0 or width_end + 1 >= len(chunk.payload):
        return (), _issue(
            chunk,
            "malformed_scalar_chunk",
            (
                "sCAL payload does not contain the NUL-delimited width needed "
                "to reach SubjectPixelHeight."
            ),
            PNG_BINARY_DATA_VAR_STRING_SOURCE,
        )
    values: tuple[tuple[str, str, PngScalarTagValue], ...] = (
        ("SubjectUnits", "0", _lookup(chunk.payload[0], {1: "meters", 2: "radians"})),
        ("SubjectPixelWidth", "1", _decode_null_terminated_string(chunk.payload[1:width_end])),
        ("SubjectPixelHeight", "2", _decode_null_terminated_string(chunk.payload[width_end + 1 :])),
    )
    return tuple(
        _tag(
            chunk,
            name,
            tag_id,
            value,
            "Image::ExifTool::PNG::SubjectScale",
            PNG_SCAL_SCALAR_SOURCE,
        )
        for name, tag_id, value in values
    ), None


def _trns_tags(
    chunk: PngChunkPlan,
    color_type: int,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if len(chunk.payload) > 6:
        return (), _issue(
            chunk,
            "unsupported_scalar_chunk",
            (
                "tRNS payload is longer than ExifTool's scalar Transparency "
                "path and is treated as binary."
            ),
            PNG_TRNS_SCALAR_SOURCE,
        )
    if not chunk.payload:
        return _single_tag(chunk, "Transparency", "tRNS", "", PNG_TRNS_SCALAR_SOURCE)
    if color_type == 3:
        value = " ".join(str(byte) for byte in chunk.payload)
    else:
        value = " ".join(
            str(int.from_bytes(chunk.payload[index : index + 2], "big"))
            for index in range(0, len(chunk.payload) - 1, 2)
        )
    return _single_tag(chunk, "Transparency", "tRNS", value, PNG_TRNS_SCALAR_SOURCE)


def _time_tags(
    chunk: PngChunkPlan,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if len(chunk.payload) < 7:
        return (), _issue(
            chunk,
            "malformed_scalar_chunk",
            "tIME payload is shorter than ExifTool's nC5 ModifyDate fields.",
            PNG_TIME_SCALAR_SOURCE,
        )
    year = int.from_bytes(chunk.payload[:2], "big")
    month, day, hour, minute, second = chunk.payload[2:7]
    value = f"{year:04d}:{month:02d}:{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
    return _single_tag(
        chunk,
        "ModifyDate",
        "tIME",
        value,
        PNG_TIME_SCALAR_SOURCE,
        family_2_group="Time",
    )


def _srgb_tags(
    chunk: PngChunkPlan,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if not chunk.payload:
        return (), _issue(
            chunk,
            "malformed_scalar_chunk",
            "sRGB payload is missing ExifTool's SRGBRendering byte.",
            PNG_SRGB_SCALAR_SOURCE,
        )
    return _single_tag(
        chunk,
        "SRGBRendering",
        "sRGB",
        _lookup(chunk.payload[0], _SRGB_RENDERING),
        PNG_SRGB_SCALAR_SOURCE,
    )


def _chrm_tags(
    chunk: PngChunkPlan,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if len(chunk.payload) < 32:
        return (), _issue(
            chunk,
            "malformed_scalar_chunk",
            "cHRM payload is shorter than ExifTool's eight int32u PrimaryChromaticities values.",
            PNG_CHRM_SCALAR_SOURCE,
        )
    names = (
        "WhitePointX",
        "WhitePointY",
        "RedX",
        "RedY",
        "GreenX",
        "GreenY",
        "BlueX",
        "BlueY",
    )
    tags = []
    for index, name in enumerate(names):
        offset = index * 4
        value = int.from_bytes(chunk.payload[offset : offset + 4], "big") / 100_000
        tags.append(
            _tag(
                chunk,
                name,
                str(index),
                value,
                "Image::ExifTool::PNG::PrimaryChromaticities",
                PNG_CHRM_SCALAR_SOURCE,
            )
        )
    return tuple(tags), None


def _ster_tags(
    chunk: PngChunkPlan,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if not chunk.payload:
        return (), _issue(
            chunk,
            "malformed_scalar_chunk",
            "sTER payload is missing ExifTool's StereoMode byte.",
            PNG_STER_SCALAR_SOURCE,
        )
    return _single_tag(
        chunk,
        "StereoMode",
        "0",
        _lookup(chunk.payload[0], {0: "Cross-fuse Layout", 1: "Diverging-fuse Layout"}),
        PNG_STER_SCALAR_SOURCE,
        table_name="Image::ExifTool::PNG::StereoImage",
    )


def _vpag_tags(
    chunk: PngChunkPlan,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if len(chunk.payload) < 9:
        return (), _issue(
            chunk,
            "malformed_scalar_chunk",
            "vpAg payload is shorter than ExifTool's VirtualPage table.",
            PNG_VPAG_SCALAR_SOURCE,
        )
    values: tuple[tuple[str, str, PngScalarTagValue], ...] = (
        ("VirtualImageWidth", "0", int.from_bytes(chunk.payload[0:4], "big")),
        ("VirtualImageHeight", "1", int.from_bytes(chunk.payload[4:8], "big")),
        ("VirtualPageUnits", "2", chunk.payload[8]),
    )
    return tuple(
        _tag(
            chunk,
            name,
            tag_id,
            value,
            "Image::ExifTool::PNG::VirtualPage",
            PNG_VPAG_SCALAR_SOURCE,
        )
        for name, tag_id, value in values
    ), None


def _actl_tags(
    chunk: PngChunkPlan,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if len(chunk.payload) < 8:
        return (), _issue(
            chunk,
            "malformed_scalar_chunk",
            "acTL payload is shorter than the APNG frame/play count fields routed by PNG.pm.",
            PNG_ACTL_SCALAR_SOURCE,
        )
    values: tuple[tuple[str, str, PngScalarTagValue], ...] = (
        ("AnimationFrames", "0", int.from_bytes(chunk.payload[0:4], "big")),
        ("AnimationPlays", "1", int.from_bytes(chunk.payload[4:8], "big") or "inf"),
    )
    return tuple(
        _tag(
            chunk,
            name,
            tag_id,
            value,
            "Image::ExifTool::PNG::AnimationControl",
            PNG_ACTL_SCALAR_SOURCE,
        )
        for name, tag_id, value in values
    ), None


def _cicp_tags(
    chunk: PngChunkPlan,
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    if len(chunk.payload) < 4:
        return (), _issue(
            chunk,
            "malformed_scalar_chunk",
            "cICP payload is shorter than ExifTool's four CICodePoints bytes.",
            PNG_CICP_SCALAR_SOURCE,
        )
    values: tuple[tuple[str, str, PngScalarTagValue], ...] = (
        ("ColorPrimaries", "0", _lookup(chunk.payload[0], _COLOR_PRIMARIES)),
        (
            "TransferCharacteristics",
            "1",
            _lookup(chunk.payload[1], _TRANSFER_CHARACTERISTICS),
        ),
        ("MatrixCoefficients", "2", _lookup(chunk.payload[2], _MATRIX_COEFFICIENTS)),
        ("VideoFullRangeFlag", "3", chunk.payload[3]),
    )
    return tuple(
        _tag(
            chunk,
            name,
            tag_id,
            value,
            "Image::ExifTool::PNG::CICodePoints",
            PNG_CICP_SCALAR_SOURCE,
            family_1_group="PNG-cICP",
        )
        for name, tag_id, value in values
    ), None


def _background_color(payload: bytes) -> str:
    if len(payload) < 2:
        values = tuple(payload)
    else:
        values = tuple(
            int.from_bytes(payload[index : index + 2], "big")
            for index in range(0, len(payload) - 1, 2)
        )
    return " ".join(str(value) for value in values)


def _decode_null_terminated_string(payload: bytes) -> str:
    return payload.split(b"\x00", 1)[0].decode("latin-1", errors="replace")


def _single_tag(
    chunk: PngChunkPlan,
    name: str,
    tag_id: str,
    value: PngScalarTagValue,
    source: str,
    *,
    table_name: str = "Image::ExifTool::PNG::Main",
    family_1_group: str = "PNG",
    family_2_group: str = "Image",
) -> tuple[tuple[PngScalarTag, ...], PngScalarRuntimeIssue | None]:
    return (
        _tag(
            chunk,
            name,
            tag_id,
            value,
            table_name,
            source,
            family_1_group=family_1_group,
            family_2_group=family_2_group,
        ),
    ), None


def _tag(
    chunk: PngChunkPlan,
    name: str,
    tag_id: str,
    value: PngScalarTagValue,
    table_name: str,
    source: str,
    *,
    family_1_group: str = "PNG",
    family_2_group: str = "Image",
) -> PngScalarTag:
    return PngScalarTag(
        chunk_index=chunk.index,
        chunk_type=chunk.chunk_type,
        chunk_start_offset=chunk.chunk_start_offset,
        payload_offset=chunk.payload_offset,
        name=name,
        tag_id=tag_id,
        value=value,
        group=family_1_group,
        family_0_group="PNG",
        family_1_group=family_1_group,
        family_2_group=family_2_group,
        table_name=table_name,
        evidence_ids=(source,),
    )


def _issue(
    chunk: PngChunkPlan,
    code: PngScalarIssueCode,
    reason: str,
    source: str,
) -> PngScalarRuntimeIssue:
    return PngScalarRuntimeIssue(
        chunk_index=chunk.index,
        chunk_type=chunk.chunk_type,
        code=code,
        reason=reason,
        evidence_ids=(source,),
    )


def _lookup(value: int, table: dict[int, str]) -> str | int:
    return table.get(value, value)


def unique_evidence_ids(references: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for reference in references:
        if reference in seen:
            continue
        seen.add(reference)
        unique.append(reference)
    return tuple(unique)


_COLOR_TYPE = {
    0: "Grayscale",
    2: "RGB",
    3: "Palette",
    4: "Grayscale with Alpha",
    6: "RGB with Alpha",
}
_SRGB_RENDERING = {
    0: "Perceptual",
    1: "Relative Colorimetric",
    2: "Saturation",
    3: "Absolute Colorimetric",
}
_COLOR_PRIMARIES = {
    1: "BT.709",
    2: "Unspecified",
    4: "BT.470 System M (historical)",
    5: "BT.470 System B, G (historical)",
    6: "BT.601",
    7: "SMPTE 240",
    8: "Generic film (color filters using illuminant C)",
    9: "BT.2020, BT.2100",
    10: "SMPTE 428 (CIE 1921 XYZ)",
    11: "SMPTE RP 431-2",
    12: "SMPTE EG 432-1",
    22: "EBU Tech. 3213-E",
}
_TRANSFER_CHARACTERISTICS = {
    0: "For future use (0)",
    1: "BT.709",
    2: "Unspecified",
    3: "For future use (3)",
    4: "BT.470 System M (historical)",
    5: "BT.470 System B, G (historical)",
    6: "BT.601",
    7: "SMPTE 240 M",
    8: "Linear",
    9: "Logarithmic (100 : 1 range)",
    10: "Logarithmic (100 * Sqrt(10) : 1 range)",
    11: "IEC 61966-2-4",
    12: "BT.1361",
    13: "sRGB or sYCC",
    14: "BT.2020 10-bit systems",
    15: "BT.2020 12-bit systems",
    16: "SMPTE ST 2084, ITU BT.2100 PQ",
    17: "SMPTE ST 428",
    18: "BT.2100 HLG, ARIB STD-B67",
}
_MATRIX_COEFFICIENTS = {
    0: "Identity matrix",
    1: "BT.709",
    2: "Unspecified",
    3: "For future use (3)",
    4: "US FCC 73.628",
    5: "BT.470 System B, G (historical)",
    6: "BT.601",
    7: "SMPTE 240 M",
    8: "YCgCo",
    9: "BT.2020 non-constant luminance, BT.2100 YCbCr",
    10: "BT.2020 constant luminance",
    11: "SMPTE ST 2085 YDzDx",
    12: "Chromaticity-derived non-constant luminance",
    13: "Chromaticity-derived constant luminance",
    14: "BT.2100 ICtCp",
}
