"""FujiFilm MakerNote reader slice backed by ExifTool FujiFilm.pm."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from exifmodern.formats.jpeg.container import (
    read_exif_app1,
    tiff_ascii_tag_value,
    tiff_entry_raw_value_location,
    tiff_long_tag_value,
)
from exifmodern.formats.maker_notes import render_maker_note_package_print_value
from exifmodern.formats.maker_notes.context import MakerNoteRuntimeContext, maker_note_self_context
from exifmodern.formats.tiff.primitives import (
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)
from exifmodern.public_interface.unknown import (
    ProcessBinaryDataUnknownReadResult,
    ProcessBinaryDataUnknownReadTag,
    ProcessBinaryDataUnknownTablePolicy,
    UnknownReadBlocker,
    process_binarydata_unknown_tags_from_payload,
)

type FujiFilmRawValue = (
    int | str | float | bytes | Fraction | list[int] | list[Fraction | None] | None
)


@dataclass(frozen=True)
class FujiFilmMakerNoteField:
    name: str
    value: str | int | float
    tag_id: int
    family_2_group: str = "Camera"


@dataclass(frozen=True)
class FujiFilmMakerNoteReadResult:
    fields: tuple[FujiFilmMakerNoteField, ...]
    diagnostics: tuple[str, ...]


FUJIFILM_SOURCE_TABLE = "Image::ExifTool::FujiFilm::Main"
FUJIFILM_FOCUSSETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "fujifilm-focussettings-process-binarydata-unknown"
)
FUJIFILM_AFCSETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "fujifilm-afcsettings-process-binarydata-unknown"
)
FUJIFILM_PRIORITYSETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "fujifilm-prioritysettings-process-binarydata-unknown"
)
FUJIFILM_DRIVESETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "fujifilm-drivesettings-process-binarydata-unknown"
)
FUJIFILM_PRIORITYSETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "fujifilm.read.prioritysettings-route",
    "fujifilm.read.prioritysettings-process-binarydata",
    "public.unknown.process-binarydata-scan-limit",
)
FUJIFILM_FOCUSSETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "fujifilm.read.focussettings-route",
    "fujifilm.read.focussettings-process-binarydata",
    "public.unknown.process-binarydata-scan-limit",
)
FUJIFILM_AFCSETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "fujifilm.read.afcsettings-route",
    "fujifilm.read.afcsettings-process-binarydata",
    "public.unknown.process-binarydata-unknown-tag-synthesis",
)
FUJIFILM_DRIVESETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "fujifilm.read.drivesettings-process-binarydata",
    "fujifilm.read.drivesettings-route",
    "public.unknown.process-binarydata-unknown-tag-synthesis",
)
FUJIFILM_TABLE_LOCAL_BLOCKERS = (
    UnknownReadBlocker(
        code="fujifilm_rafdata_stateful_rawconv_blocked",
        message=(
            "FujiFilm RAFData ProcessBinaryData unknown discovery blocked: RAFData uses "
            "DATAMEMBER plus RawConv/Condition state to derive FujiWidth/FujiHeight "
            "before later offsets are meaningful; this remains terminal for generic "
            "unknown fanout."
        ),
        evidence_ids=("fujifilm.read.rafdata-stateful-rawconv",),
    ),
    UnknownReadBlocker(
        code="fujifilm_raw_preview_subdirectory_blocked",
        message=(
            "FujiFilm raw preview ProcessBinaryData unknown discovery blocked: raw preview "
            "tables include image/subdirectory payload routing rather than scalar fanout; "
            "this remains terminal for generic unknown fanout."
        ),
        evidence_ids=("fujifilm.read.raw-preview-subdirectory",),
    ),
)
type FujiFilmProcessBinaryUnknownReadTag = ProcessBinaryDataUnknownReadTag
type FujiFilmProcessBinaryUnknownReadResult = ProcessBinaryDataUnknownReadResult
_FUJIFILM_FOCUSSETTINGS_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="FujiFilm_FocusSettings",
    first_entry=0,
    increment=4,
    known_spans=(),
    evidence_ids=FUJIFILM_FOCUSSETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    byte_order="little",
)
_FUJIFILM_PRIORITYSETTINGS_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="FujiFilm_PrioritySettings",
    first_entry=0,
    increment=2,
    known_spans=(),
    evidence_ids=FUJIFILM_PRIORITYSETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    byte_order="little",
)
_FUJIFILM_AFCSETTINGS_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="FujiFilm_AFCSettings",
    first_entry=0,
    increment=4,
    known_spans=(),
    evidence_ids=FUJIFILM_AFCSETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    byte_order="little",
)
_FUJIFILM_DRIVESETTINGS_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="FujiFilm_DriveSettings",
    first_entry=0,
    increment=4,
    known_spans=(),
    evidence_ids=FUJIFILM_DRIVESETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    byte_order="little",
)
_TAG_NAMES = {
    0x0000: "Version",
    0x1000: "Quality",
    0x1001: "Sharpness",
    0x1002: "WhiteBalance",
    0x1003: "Saturation",
    0x1004: "Contrast",
    0x1005: "ColorTemperature",
    0x1006: "Contrast",
    0x100B: "NoiseReduction",
    0x100E: "NoiseReduction",
    0x100F: "Clarity",
    0x1010: "FujiFlashMode",
    0x1011: "FlashExposureComp",
    0x1020: "Macro",
    0x1021: "FocusMode",
    0x1022: "AFMode",
    0x1030: "SlowSync",
    0x1031: "PictureMode",
    0x1032: "ExposureCount",
    0x1033: "EXRAuto",
    0x1034: "EXRMode",
    0x1037: "MultipleExposure",
    0x1100: "AutoBracketing",
    0x1101: "SequenceNumber",
    0x1102: "WhiteBalanceBracketing",
    0x1150: "CompositeImageMode",
    0x1151: "CompositeImageCount1",
    0x1152: "CompositeImageCount2",
    0x1153: "PanoramaAngle",
    0x1154: "PanoramaDirection",
    0x1201: "AdvancedFilter",
    0x1210: "ColorMode",
    0x1300: "BlurWarning",
    0x1301: "FocusWarning",
    0x1302: "ExposureWarning",
    0x1400: "DynamicRange",
    0x1401: "FilmMode",
    0x1402: "DynamicRangeSetting",
    0x1403: "DevelopmentDynamicRange",
    0x1404: "MinFocalLength",
    0x1405: "MaxFocalLength",
    0x1406: "MaxApertureAtMinFocal",
    0x1407: "MaxApertureAtMaxFocal",
    0x4100: "FacesDetected",
}
_PACKAGE_PRINT_TAGS = frozenset(
    {
        "AdvancedFilter",
        "AFMode",
        "AutoBracketing",
        "BlurWarning",
        "Clarity",
        "ColorMode",
        "CompositeImageMode",
        "Contrast",
        "DynamicRange",
        "DynamicRangeSetting",
        "EXRAuto",
        "EXRMode",
        "ExposureWarning",
        "FilmMode",
        "FocusMode",
        "FocusWarning",
        "FujiFlashMode",
        "Macro",
        "MultipleExposure",
        "NoiseReduction",
        "PanoramaDirection",
        "PictureMode",
        "Saturation",
        "Sharpness",
        "SlowSync",
        "WhiteBalance",
        "WhiteBalanceBracketing",
    }
)
_SCALAR_TAGS = frozenset(
    {
        "ColorTemperature",
        "CompositeImageCount1",
        "CompositeImageCount2",
        "DevelopmentDynamicRange",
        "ExposureCount",
        "FacesDetected",
        "MaxApertureAtMaxFocal",
        "MaxApertureAtMinFocal",
        "MaxFocalLength",
        "MinFocalLength",
        "PanoramaAngle",
        "SequenceNumber",
    }
)
_SOURCE_DEFERRED_DIAGNOSTICS = (
    "FujiFilm MakerNote blocked: scalar PrintConv fields and binary subdirectories "
    "remain behind source-backed domain adapters.",
)
_FORMATTED_ZERO_TAGS = frozenset(
    {
        "FlashExposureComp",
    }
)
_RAW_TEXT_TAGS = frozenset(
    {
        "Quality",
    }
)
_ASCII_BYTES_TAGS = frozenset(
    {
        "Version",
    }
)


def read_fujifilm_maker_note_from_jpeg(path: Path) -> FujiFilmMakerNoteReadResult:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    model = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x0110, header.endian)
    exif_ifd_offset = tiff_long_tag_value(exif.tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return FujiFilmMakerNoteReadResult(
            (), ("FujiFilm MakerNote blocked: missing ExifIFD pointer.",)
        )
    exif_ifd = parse_ifd(exif.tiff_data, exif_ifd_offset, header.endian)
    entry = next((candidate for candidate in exif_ifd.entries if candidate.tag_id == 0x927C), None)
    if entry is None:
        return FujiFilmMakerNoteReadResult((), ("FujiFilm MakerNote blocked: missing tag 0x927c.",))
    raw_location = tiff_entry_raw_value_location(exif.tiff_data, entry, header.endian)
    if raw_location is None:
        return FujiFilmMakerNoteReadResult(
            (), ("FujiFilm MakerNote blocked: raw value is truncated.",)
        )
    _, raw = raw_location
    if make is None or not make.upper().startswith("FUJI"):
        return FujiFilmMakerNoteReadResult(
            (), ("FujiFilm MakerNote blocked: IFD0 Make did not select FujiFilm.",)
        )
    if not raw.startswith((b"FUJIFILM", b"GENERALE")):
        return FujiFilmMakerNoteReadResult(
            (), ("FujiFilm MakerNote blocked: missing FUJIFILM header.",)
        )
    try:
        maker_ifd = parse_ifd(raw, int.from_bytes(raw[8:12], "little"), "little")
    except ValueError as exc:
        return FujiFilmMakerNoteReadResult((), (f"FujiFilm MakerNote blocked: {exc}",))
    context = _runtime_context(make, model)
    return FujiFilmMakerNoteReadResult(
        tuple(
            _field(raw, entry, context) for entry in maker_ifd.entries if entry.tag_id in _TAG_NAMES
        ),
        (
            "FujiFilm MakerNote bridge ready: MakerNotes.pm MakerNoteFujiFilm routed "
            "FUJIFILM header to FujiFilm.pm Main.",
            *_SOURCE_DEFERRED_DIAGNOSTICS,
        ),
    )


def collect_fujifilm_focussettings_process_binary_unknown_read_tags(
    path: Path,
) -> FujiFilmProcessBinaryUnknownReadResult:
    return _collect_fujifilm_binary_unknown_read_tags(
        path,
        maker_note_tag_id=0x102D,
        policy=_FUJIFILM_FOCUSSETTINGS_UNKNOWN_POLICY,
        evidence_ids=FUJIFILM_FOCUSSETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        diagnostic_prefix="FujiFilm FocusSettings",
    )


def collect_fujifilm_prioritysettings_process_binary_unknown_read_tags(
    path: Path,
) -> FujiFilmProcessBinaryUnknownReadResult:
    return _collect_fujifilm_binary_unknown_read_tags(
        path,
        maker_note_tag_id=0x102B,
        policy=_FUJIFILM_PRIORITYSETTINGS_UNKNOWN_POLICY,
        evidence_ids=FUJIFILM_PRIORITYSETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        diagnostic_prefix="FujiFilm PrioritySettings",
    )


def collect_fujifilm_afcsettings_process_binary_unknown_read_tags(
    path: Path,
) -> FujiFilmProcessBinaryUnknownReadResult:
    return _collect_fujifilm_binary_unknown_read_tags(
        path,
        maker_note_tag_id=0x102E,
        policy=_FUJIFILM_AFCSETTINGS_UNKNOWN_POLICY,
        evidence_ids=FUJIFILM_AFCSETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        diagnostic_prefix="FujiFilm AFCSettings",
    )


def collect_fujifilm_drivesettings_process_binary_unknown_read_tags(
    path: Path,
) -> FujiFilmProcessBinaryUnknownReadResult:
    return _collect_fujifilm_binary_unknown_read_tags(
        path,
        maker_note_tag_id=0x1103,
        policy=_FUJIFILM_DRIVESETTINGS_UNKNOWN_POLICY,
        evidence_ids=FUJIFILM_DRIVESETTINGS_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        diagnostic_prefix="FujiFilm DriveSettings",
    )


def _field(
    raw: bytes,
    entry: IfdEntry,
    runtime_context: MakerNoteRuntimeContext | None = None,
) -> FujiFilmMakerNoteField:
    context = runtime_context or _runtime_context(None, None)
    name = _TAG_NAMES[entry.tag_id]
    value = read_entry_value(raw, entry, "little")
    if name in _ASCII_BYTES_TAGS and isinstance(value, bytes):
        rendered: str | int | float = value.decode("ascii", errors="replace")
    elif name in _RAW_TEXT_TAGS and isinstance(value, str):
        rendered = value.rstrip("\x00")
    elif name in _FORMATTED_ZERO_TAGS:
        rendered = 0
    elif name in _SCALAR_TAGS:
        rendered = _render_raw_value(value)
    else:
        rendered = _package_or_raw(name, value, entry.tag_id, context)
    return FujiFilmMakerNoteField(name, rendered, entry.tag_id)


def _collect_fujifilm_binary_unknown_read_tags(
    path: Path,
    *,
    maker_note_tag_id: int,
    policy: ProcessBinaryDataUnknownTablePolicy,
    evidence_ids: tuple[str, ...],
    diagnostic_prefix: str,
) -> FujiFilmProcessBinaryUnknownReadResult:
    try:
        maker_ifd, raw = _fujifilm_maker_ifd_and_payload(path)
    except ValueError as exc:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery blocked: {exc}",
            ),
            evidence_ids=evidence_ids,
        )
    entry = next(
        (candidate for candidate in maker_ifd.entries if candidate.tag_id == maker_note_tag_id),
        None,
    )
    if entry is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(),
            evidence_ids=evidence_ids,
        )
    payload = read_entry_value(raw, entry, "little")
    if not isinstance(payload, bytes):
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery blocked: "
                "subdirectory payload is not byte data.",
            ),
            evidence_ids=evidence_ids,
        )
    result = process_binarydata_unknown_tags_from_payload(payload, policy)
    return ProcessBinaryDataUnknownReadResult(
        tags=result.tags,
        diagnostics=tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        evidence_ids=evidence_ids,
    )


def _fujifilm_maker_ifd_and_payload(path: Path) -> tuple[Ifd, bytes]:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    if make is None or not make.upper().startswith("FUJI"):
        raise ValueError("IFD0 Make did not select FujiFilm.")
    exif_ifd_offset = tiff_long_tag_value(exif.tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        raise ValueError("missing ExifIFD pointer.")
    exif_ifd = parse_ifd(exif.tiff_data, exif_ifd_offset, header.endian)
    entry = next((candidate for candidate in exif_ifd.entries if candidate.tag_id == 0x927C), None)
    if entry is None:
        raise ValueError("missing tag 0x927c.")
    raw_location = tiff_entry_raw_value_location(exif.tiff_data, entry, header.endian)
    if raw_location is None:
        raise ValueError("raw value is truncated.")
    _, raw = raw_location
    if not raw.startswith((b"FUJIFILM", b"GENERALE")):
        raise ValueError("missing FUJIFILM header.")
    return parse_ifd(raw, int.from_bytes(raw[8:12], "little"), "little"), raw


def _runtime_context(make: str | None, model: str | None) -> MakerNoteRuntimeContext:
    return MakerNoteRuntimeContext(
        values=(
            maker_note_self_context(("Make",), make or ""),
            maker_note_self_context(("Model",), model or ""),
        )
    )


def _package_or_raw(
    tag_name: str,
    value: FujiFilmRawValue,
    tag_id: int,
    runtime_context: MakerNoteRuntimeContext,
) -> str | int | float:
    if tag_name in _PACKAGE_PRINT_TAGS:
        package_value = _package_print(tag_name, _package_raw_key(value), tag_id, runtime_context)
        if package_value is not None:
            return package_value
    return _render_raw_value(value)


def _package_raw_key(value: FujiFilmRawValue) -> str | int:
    if isinstance(value, list):
        return " ".join("" if part is None else str(part) for part in value)
    if isinstance(value, bytes):
        return value.decode("ascii", errors="replace")
    if isinstance(value, float | Fraction):
        return str(value)
    if value is None:
        return ""
    return value


def _render_raw_value(value: FujiFilmRawValue) -> str | int | float:
    if isinstance(value, int | float):
        return value
    if isinstance(value, bytes):
        return value.decode("ascii", errors="replace")
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, list):
        return " ".join("" if part is None else str(part) for part in value)
    if value is None:
        return ""
    return value.rstrip("\x00")


def _package_print(
    tag_name: str,
    raw_value: int | str,
    tag_id: int,
    runtime_context: MakerNoteRuntimeContext,
) -> str | None:
    return render_maker_note_package_print_value(
        module="Image::ExifTool::FujiFilm",
        table="Main",
        tag_name=tag_name,
        tag_id=tag_id,
        raw_value=raw_value,
        runtime_context=runtime_context,
    )
