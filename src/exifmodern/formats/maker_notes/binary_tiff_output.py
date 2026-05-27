"""Typed Binary-option TIFF output boundary for maker-note metering images."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonObject
from exifmodern.services.maker_note_tables import MakerNoteTagLocation

type MakerNoteBinaryTiffStatus = Literal[
    "binary_output",
    "binary_option_required",
    "payload_too_short",
    "unsupported_location",
]
type MakerNoteBinaryTiffRuntimeStatus = Literal[
    "callable_binary_output",
    "callable_binary_option_gate",
    "source_backed_short_payload",
    "unsupported_location",
]
type MakerNoteBinaryTiffTransform = Literal[
    "log13_big_endian_rbg_to_rgb",
    "shift10_little_endian_rgb",
    "log13_little_endian_intensity_to_rgb",
]
type MakerNoteBinaryTiffByteOrder = Literal["big", "little"]


@dataclass(frozen=True)
class MakerNoteBinaryTiffSpec:
    module: str
    table: str
    tag_name: str
    min_payload_bytes: int
    non_binary_summary_bytes: int
    width: int
    height: int
    samples_per_pixel: int
    bits_per_sample: int
    resolution_dpi: int
    input_byte_order: MakerNoteBinaryTiffByteOrder
    input_word_count: int
    output_strip_bytes: int
    transform: MakerNoteBinaryTiffTransform
    evidence_ids: tuple[str, ...]

    @property
    def output_tiff_bytes(self) -> int:
        return EXIFTOOL_TIFF_HEADER_BYTES + self.output_strip_bytes


@dataclass(frozen=True)
class MakerNoteBinaryTiffRequest:
    location: MakerNoteTagLocation
    payload: bytes
    binary_option: bool


@dataclass(frozen=True)
class MakerNoteBinaryTiffResult:
    status: MakerNoteBinaryTiffStatus
    spec: MakerNoteBinaryTiffSpec | None
    binary_option: bool
    summary_text: str
    tiff_data: bytes
    blocker_reason: str

    @property
    def produced_binary(self) -> bool:
        return self.status == "binary_output"

    @property
    def terminal_surface(self) -> bool:
        return self.status != "unsupported_location"

    @property
    def runtime_status(self) -> MakerNoteBinaryTiffRuntimeStatus:
        if self.status == "binary_output":
            return "callable_binary_output"
        if self.status == "binary_option_required":
            return "callable_binary_option_gate"
        if self.status == "payload_too_short":
            return "source_backed_short_payload"
        return "unsupported_location"


EXIFTOOL_TIFF_HEADER_BYTES = 204
_MINOLTA_SOURCE = "maker_notes.binary_tiff.minolta_wbinfo_a100"
_SONY_FOCUS_SOURCE = "maker_notes.binary_tiff.sony_focus_info"
_SONY_MORE_SOURCE = "maker_notes.binary_tiff.sony_more_info"
_SONY_TAG940E_SOURCE = "maker_notes.binary_tiff.sony_tag940e"
_TIFF_HEADER_SOURCE = "maker_notes.binary_tiff.writer_tiff_header"
_BINARY_OPTION_BLOCKER = (
    "normal scalar read remains blocked because ExifTool returns a Binary-option-gated "
    "TIFF payload reference rather than a JSON scalar ValueConv value"
)

MINOLTA_WB_INFO_A100_TIFF_METERING_IMAGE_SPEC = MakerNoteBinaryTiffSpec(
    module="Image::ExifTool::Minolta",
    table="WBInfoA100",
    tag_name="TiffMeteringImage",
    min_payload_bytes=9600,
    non_binary_summary_bytes=7404,
    width=40,
    height=30,
    samples_per_pixel=3,
    bits_per_sample=16,
    resolution_dpi=10,
    input_byte_order="big",
    input_word_count=4800,
    output_strip_bytes=7200,
    transform="log13_big_endian_rbg_to_rgb",
    evidence_ids=(_MINOLTA_SOURCE, _TIFF_HEADER_SOURCE),
)
SONY_FOCUS_INFO_TIFF_METERING_IMAGE_SPEC = MakerNoteBinaryTiffSpec(
    module="Image::ExifTool::Sony",
    table="FocusInfo",
    tag_name="TiffMeteringImage",
    min_payload_bytes=9600,
    non_binary_summary_bytes=7404,
    width=40,
    height=30,
    samples_per_pixel=3,
    bits_per_sample=16,
    resolution_dpi=10,
    input_byte_order="big",
    input_word_count=4800,
    output_strip_bytes=7200,
    transform="log13_big_endian_rbg_to_rgb",
    evidence_ids=(_SONY_FOCUS_SOURCE, _TIFF_HEADER_SOURCE),
)
SONY_MORE_INFO_TIFF_METERING_IMAGE_SPEC = MakerNoteBinaryTiffSpec(
    module="Image::ExifTool::Sony",
    table="MoreInfo",
    tag_name="TiffMeteringImage",
    min_payload_bytes=7200,
    non_binary_summary_bytes=7404,
    width=40,
    height=30,
    samples_per_pixel=3,
    bits_per_sample=16,
    resolution_dpi=10,
    input_byte_order="little",
    input_word_count=3600,
    output_strip_bytes=7200,
    transform="shift10_little_endian_rgb",
    evidence_ids=(_SONY_MORE_SOURCE, _TIFF_HEADER_SOURCE),
)
SONY_TAG940E_TIFF_METERING_IMAGE_SPEC = MakerNoteBinaryTiffSpec(
    module="Image::ExifTool::Sony",
    table="Tag940e",
    tag_name="TiffMeteringImage",
    min_payload_bytes=2640,
    non_binary_summary_bytes=2640,
    width=44,
    height=30,
    samples_per_pixel=3,
    bits_per_sample=16,
    resolution_dpi=10,
    input_byte_order="little",
    input_word_count=1320,
    output_strip_bytes=7920,
    transform="log13_little_endian_intensity_to_rgb",
    evidence_ids=(_SONY_TAG940E_SOURCE, _TIFF_HEADER_SOURCE),
)

_TIFF_METERING_IMAGE_SPECS = (
    MINOLTA_WB_INFO_A100_TIFF_METERING_IMAGE_SPEC,
    SONY_FOCUS_INFO_TIFF_METERING_IMAGE_SPEC,
    SONY_MORE_INFO_TIFF_METERING_IMAGE_SPEC,
    SONY_TAG940E_TIFF_METERING_IMAGE_SPEC,
)


def maker_note_binary_tiff_spec_for_location(
    location: MakerNoteTagLocation,
) -> MakerNoteBinaryTiffSpec | None:
    for spec in _TIFF_METERING_IMAGE_SPECS:
        if (
            location.module.module == spec.module
            and location.table.name == spec.table
            and location.entry.name == spec.tag_name
        ):
            return spec
    return None


def render_maker_note_binary_tiff_output(
    request: MakerNoteBinaryTiffRequest,
) -> MakerNoteBinaryTiffResult:
    spec = maker_note_binary_tiff_spec_for_location(request.location)
    if spec is None:
        return MakerNoteBinaryTiffResult(
            status="unsupported_location",
            spec=None,
            binary_option=request.binary_option,
            summary_text="",
            tiff_data=b"",
            blocker_reason="location is not a source-backed maker-note TIFF metering image",
        )
    if len(request.payload) < spec.min_payload_bytes:
        return MakerNoteBinaryTiffResult(
            status="payload_too_short",
            spec=spec,
            binary_option=request.binary_option,
            summary_text="",
            tiff_data=b"",
            blocker_reason=(
                f"ExifTool returns undef unless payload length is at least "
                f"{spec.min_payload_bytes} bytes"
            ),
        )
    if not request.binary_option:
        return MakerNoteBinaryTiffResult(
            status="binary_option_required",
            spec=spec,
            binary_option=False,
            summary_text=exiftool_binary_reference_summary(spec),
            tiff_data=b"",
            blocker_reason=_BINARY_OPTION_BLOCKER,
        )
    return MakerNoteBinaryTiffResult(
        status="binary_output",
        spec=spec,
        binary_option=True,
        summary_text="",
        tiff_data=make_maker_note_binary_tiff(spec, request.payload),
        blocker_reason="",
    )


def maker_note_binary_tiff_result_to_json(result: MakerNoteBinaryTiffResult) -> JsonObject:
    spec = result.spec
    return {
        "status": result.status,
        "runtime_status": result.runtime_status,
        "produced_binary": result.produced_binary,
        "terminal_surface": result.terminal_surface,
        "runtime_boundary": "binary_tiff_output" if spec is not None else "none",
        "scalar_reader_ready": False,
        "binary_option": result.binary_option,
        "summary_text": result.summary_text,
        "tiff_data_bytes": len(result.tiff_data),
        "blocker_reason": result.blocker_reason,
        "spec": (
            {
                "module": spec.module,
                "table": spec.table,
                "tag_name": spec.tag_name,
                "min_payload_bytes": spec.min_payload_bytes,
                "non_binary_summary_bytes": spec.non_binary_summary_bytes,
                "width": spec.width,
                "height": spec.height,
                "samples_per_pixel": spec.samples_per_pixel,
                "bits_per_sample": spec.bits_per_sample,
                "resolution_dpi": spec.resolution_dpi,
                "input_byte_order": spec.input_byte_order,
                "input_word_count": spec.input_word_count,
                "output_strip_bytes": spec.output_strip_bytes,
                "output_tiff_bytes": spec.output_tiff_bytes,
                "transform": spec.transform,
            }
            if spec is not None
            else None
        ),
    }


def exiftool_binary_reference_summary(spec: MakerNoteBinaryTiffSpec) -> str:
    return f"Binary data {spec.non_binary_summary_bytes} bytes"


def make_maker_note_binary_tiff(spec: MakerNoteBinaryTiffSpec, payload: bytes) -> bytes:
    words = unpack_tiff_metering_words(payload, spec)
    return make_exiftool_tiff_header(
        width=spec.width,
        height=spec.height,
        samples_per_pixel=spec.samples_per_pixel,
        bits_per_sample=spec.bits_per_sample,
        resolution_dpi=spec.resolution_dpi,
    ) + transform_tiff_metering_words(spec, words)


def unpack_tiff_metering_words(
    payload: bytes,
    spec: MakerNoteBinaryTiffSpec,
) -> tuple[int, ...]:
    return tuple(
        int.from_bytes(
            payload[index : index + 2],
            spec.input_byte_order,
        )
        for index in range(0, spec.input_word_count * 2, 2)
    )


def transform_tiff_metering_words(
    spec: MakerNoteBinaryTiffSpec,
    words: tuple[int, ...],
) -> bytes:
    if spec.transform == "log13_big_endian_rbg_to_rgb":
        return pack_little_endian_words(
            tuple(
                channel
                for index in range(spec.width * spec.height)
                for channel in (
                    log13_to_uint16(words[index]),
                    log13_to_uint16(words[index + 2400]),
                    log13_to_uint16(words[index + 1200]),
                )
            )
        )
    if spec.transform == "shift10_little_endian_rgb":
        return pack_little_endian_words(
            tuple(
                channel
                for index in range(spec.width * spec.height)
                for channel in (
                    words[index] << 6,
                    words[index + 1200] << 6,
                    words[index + 2400] << 6,
                )
            )
        )
    if spec.transform == "log13_little_endian_intensity_to_rgb":
        return pack_little_endian_words(
            tuple(
                channel
                for index in range(spec.width * spec.height)
                for channel in (log13_to_uint16(words[index]),) * 3
            )
        )
    raise ValueError(f"Unsupported TIFF metering transform: {spec.transform}")


def log13_to_uint16(value: int) -> int:
    return int(5041.1 * math.log(value + 1) / math.log(2))


def pack_little_endian_words(values: tuple[int, ...]) -> bytes:
    return b"".join((value & 0xFFFF).to_bytes(2, "little") for value in values)


def make_exiftool_tiff_header(
    *,
    width: int,
    height: int,
    samples_per_pixel: int,
    bits_per_sample: int,
    resolution_dpi: int,
) -> bytes:
    strip_offset = EXIFTOOL_TIFF_HEADER_BYTES
    bits_per_sample_offset = 0xB6
    x_resolution_offset = 0xBC
    y_resolution_offset = 0xC4
    strip_byte_count = width * height * samples_per_pixel * ((bits_per_sample + 7) // 8)
    return (
        b"\x49\x49\x2a\0\x08\0\0\0\x0e\0"
        + b"\xfe\x00\x04\0\x01\0\0\0\x00\0\0\0"
        + b"\x00\x01\x04\0\x01\0\0\0"
        + tiff_u32(width)
        + b"\x01\x01\x04\0\x01\0\0\0"
        + tiff_u32(height)
        + b"\x02\x01\x03\0"
        + tiff_u32(samples_per_pixel)
        + tiff_u32(bits_per_sample_offset)
        + b"\x03\x01\x03\0\x01\0\0\0\x01\0\0\0"
        + b"\x06\x01\x03\0\x01\0\0\0"
        + tiff_u32(2)
        + b"\x11\x01\x04\0\x01\0\0\0"
        + tiff_u32(strip_offset)
        + b"\x15\x01\x03\0\x01\0\0\0"
        + tiff_u32(samples_per_pixel)
        + b"\x16\x01\x04\0\x01\0\0\0"
        + tiff_u32(height)
        + b"\x17\x01\x04\0\x01\0\0\0"
        + tiff_u32(strip_byte_count)
        + b"\x1a\x01\x05\0\x01\0\0\0"
        + tiff_u32(x_resolution_offset)
        + b"\x1b\x01\x05\0\x01\0\0\0"
        + tiff_u32(y_resolution_offset)
        + b"\x1c\x01\x03\0\x01\0\0\0\x01\0\0\0"
        + b"\x28\x01\x03\0\x01\0\0\0\x02\0\0\0"
        + b"\0\0\0\0"
        + (tiff_u16(bits_per_sample) * 3)
        + tiff_u32(resolution_dpi)
        + b"\x01\0\0\0"
        + tiff_u32(resolution_dpi)
        + b"\x01\0\0\0"
    )


def tiff_u16(value: int) -> bytes:
    return value.to_bytes(2, "little")


def tiff_u32(value: int) -> bytes:
    return value.to_bytes(4, "little")
