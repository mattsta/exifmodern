"""DNG write-surface planning helpers and bounded TIFF read graph emission."""

from __future__ import annotations

import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from exifmodern.formats.dng.private_data_writer import (
    DngOriginalDecisionDataByteEmissionPlan,
    DngOriginalDecisionDataOffsetPairRebuildPlan,
    DngOriginalDecisionDataTiffInstallContract,
    DngOriginalDecisionDataWriteClassification,
    DngOriginalDecisionDataWriteContract,
    DngProtectedPrivateDataBlocker,
    build_original_decision_data_byte_emission_plan,
    build_original_decision_data_tiff_install_contract,
    classify_original_decision_data_write,
    original_decision_data_write_contract,
    plan_original_decision_data_offset_pair_rebuild,
    rewrite_dng_owner_name,
)
from exifmodern.formats.dng.read_graph_adapter import build_dng_original_decision_data_read_graph
from exifmodern.formats.dng.write_plan import (
    DngProtectedWritePlan,
    DngProtectedWriteSurface,
    build_dng_protected_write_plan,
)
from exifmodern.formats.tiff.primitives import (
    Endian,
    Ifd,
    IfdEntry,
    TiffValue,
    find_entry,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance, TagValue
from exifmodern.services.system_metadata import read_system_tags

DNG_READ_LIMIT_BYTES = 1_048_576
DNG_VERSION_TAG_ID = 0xC612
DNG_SUBIFD_TAG_ID = 0x014A

DNG_IFD0_TAGS: dict[int, str] = {
    0x00FE: "SubfileType",
    0x0100: "ImageWidth",
    0x0101: "ImageHeight",
    0x0102: "BitsPerSample",
    0x0103: "Compression",
    0x0106: "PhotometricInterpretation",
    0x010F: "Make",
    0x0110: "Model",
    0x0111: "StripOffsets",
    0x0112: "Orientation",
    0x0115: "SamplesPerPixel",
    0x0116: "RowsPerStrip",
    0x0117: "StripByteCounts",
    0x011C: "PlanarConfiguration",
    0x0132: "ModifyDate",
    0x013B: "Artist",
    0x829A: "ExposureTime",
    0x829D: "FNumber",
    0x8827: "ISO",
    0x9003: "DateTimeOriginal",
    0x9211: "ImageNumber",
    DNG_VERSION_TAG_ID: "DNGVersion",
    0xC613: "DNGBackwardVersion",
    0xC614: "UniqueCameraModel",
    0xC615: "LocalizedCameraModel",
    0xC621: "ColorMatrix1",
    0xC622: "ColorMatrix2",
    0xC628: "AsShotNeutral",
    0xC62A: "BaselineExposure",
    0xC62B: "BaselineNoise",
    0xC62C: "BaselineSharpness",
    0xC62E: "LinearResponseLimit",
    0xC62F: "CameraSerialNumber",
    0xC630: "DNGLensInfo",
    0xC633: "ShadowScale",
    0xC65A: "CalibrationIlluminant1",
    0xC65B: "CalibrationIlluminant2",
    0xC65D: "RawDataUniqueID",
    0xC68B: "OriginalRawFileName",
}

DNG_SUBIFD_TAGS: dict[int, str] = {
    0x00FE: "SubfileType",
    0x0100: "ImageWidth",
    0x0101: "ImageHeight",
    0x0102: "BitsPerSample",
    0x0103: "Compression",
    0x0106: "PhotometricInterpretation",
    0x0111: "StripOffsets",
    0x0115: "SamplesPerPixel",
    0x0116: "RowsPerStrip",
    0x0117: "StripByteCounts",
    0x011C: "PlanarConfiguration",
    0x0142: "TileWidth",
    0x0143: "TileLength",
    0x0144: "TileOffsets",
    0x0145: "TileByteCounts",
    0x0146: "CFARepeatPatternDim",
    0x0147: "CFAPattern2",
    0x0211: "YCbCrCoefficients",
    0x0212: "YCbCrSubSampling",
    0x0213: "YCbCrPositioning",
    0x0214: "ReferenceBlackWhite",
    0xC616: "CFAPlaneColor",
    0xC617: "CFALayout",
    0xC619: "BlackLevelRepeatDim",
    0xC61A: "BlackLevel",
    0xC61D: "WhiteLevel",
    0xC61E: "DefaultScale",
    0xC61F: "DefaultCropOrigin",
    0xC620: "DefaultCropSize",
    0xC62D: "BayerGreenSplit",
    0xC632: "AntiAliasStrength",
    0xC65C: "BestQualityScale",
    0xC68D: "ActiveArea",
    0xC68E: "MaskedAreas",
}

CALIBRATION_ILLUMINANT_PRINT = {
    17: "Standard Light A",
    21: "D65",
}
CFA_PLANE_COLOR_PRINT = {
    0: "Red",
    1: "Green",
    2: "Blue",
    3: "Cyan",
    4: "Magenta",
    5: "Yellow",
    6: "White",
}
CFA_LAYOUT_PRINT = {
    1: "Rectangular",
}
COMPRESSION_PRINT = {
    1: "Uncompressed",
    7: "JPEG",
}
ORIENTATION_PRINT = {
    1: "Horizontal (normal)",
}
PHOTOMETRIC_PRINT = {
    2: "RGB",
    6: "YCbCr",
    32803: "Color Filter Array",
}
PLANAR_CONFIGURATION_PRINT = {
    1: "Chunky",
    2: "Separate",
}
SUBFILE_TYPE_PRINT = {
    0: "Full-resolution image",
    1: "Reduced-resolution image",
}
YCBCR_POSITIONING_PRINT = {
    1: "Centered",
    2: "Co-sited",
}


@dataclass(frozen=True)
class DngDirectoryField:
    name: str
    value: TagValue
    group: str
    tag_id: int


@dataclass(frozen=True)
class DngEmbeddedImageField:
    name: str
    value: BinaryTagValue
    group: str
    tag_id: int


__all__ = [
    "DNG_READ_LIMIT_BYTES",
    "DngOriginalDecisionDataByteEmissionPlan",
    "DngOriginalDecisionDataOffsetPairRebuildPlan",
    "DngOriginalDecisionDataTiffInstallContract",
    "DngOriginalDecisionDataWriteClassification",
    "DngOriginalDecisionDataWriteContract",
    "DngProtectedPrivateDataBlocker",
    "DngProtectedWritePlan",
    "DngProtectedWriteSurface",
    "build_dng_protected_write_plan",
    "build_dng_read_graph",
    "build_dng_read_graph_from_file",
    "build_original_decision_data_byte_emission_plan",
    "build_original_decision_data_tiff_install_contract",
    "classify_original_decision_data_write",
    "invoke_dng",
    "original_decision_data_write_contract",
    "plan_original_decision_data_offset_pair_rebuild",
    "rewrite_dng_owner_name",
]


def build_dng_read_graph_from_file(path: Path, *, source_file: str) -> ReadGraph:
    with path.open("rb") as file:
        data = file.read(DNG_READ_LIMIT_BYTES + 1)
    return build_dng_read_graph(data, source_file=source_file)


def build_dng_read_graph(data: bytes, *, source_file: str) -> ReadGraph:
    diagnostics: list[str] = []
    tags: list[ReadTag] = []
    path = Path(source_file)
    try:
        tags.extend(_system_tags(path, source_file))
    except OSError as error:
        diagnostics.append(str(error))

    if len(data) > DNG_READ_LIMIT_BYTES:
        diagnostics.append(
            "DNG read graph bounded to the first 1048576 bytes; deep IFD values were skipped."
        )
        data = data[:DNG_READ_LIMIT_BYTES]

    try:
        header = parse_tiff_header(data)
        ifd0 = parse_ifd(data, header.first_ifd_offset, header.endian)
    except ValueError as error:
        diagnostics.append(str(error))
        return _graph(source_file, tags, diagnostics)

    if find_entry(ifd0, DNG_VERSION_TAG_ID) is None:
        diagnostics.append("TIFF header did not expose DNGVersion in IFD0.")
        return _graph(source_file, tags, diagnostics)

    fields: list[DngDirectoryField] = [
        DngDirectoryField("FileType", "DNG", "File", 0),
        DngDirectoryField("FileTypeExtension", "dng", "File", 0),
        DngDirectoryField("MIMEType", "image/x-adobe-dng", "File", 0),
        DngDirectoryField("ExifByteOrder", header.byte_order, "File", 0),
    ]
    fields.extend(_directory_fields(data, ifd0.entries, header.endian, "IFD0", DNG_IFD0_TAGS))
    fields.extend(_subifd_fields(data, ifd0, header.endian, diagnostics))
    tags.extend(_dng_tags(fields))
    tags.extend(_embedded_image_tags(data, ifd0, header.endian, diagnostics))
    odd_result = build_dng_original_decision_data_read_graph(
        data,
        source_file=source_file,
        generated_at_epoch=int(time.time()),
    )
    tags.extend(odd_result.graph.tags)
    diagnostics.extend(odd_result.graph.diagnostics)
    return _graph(source_file, tags, diagnostics)


def invoke_dng(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention for fallback dispatch tests and future trie use."""

    return build_dng_read_graph_from_file(path, source_file=source_file)


def _subifd_fields(
    data: bytes,
    ifd0: Ifd,
    endian: Endian,
    diagnostics: list[str],
) -> list[DngDirectoryField]:
    subifd_offsets = _entry_offsets(data, find_entry(ifd0, DNG_SUBIFD_TAG_ID), endian)
    fields: list[DngDirectoryField] = []
    if not subifd_offsets:
        return fields
    for index, subifd_offset in enumerate(subifd_offsets[:3]):
        group = _subifd_group(index)
        try:
            subifd = parse_ifd(data, subifd_offset, endian)
        except ValueError as error:
            diagnostics.append(str(error))
            continue
        tag_names = _subifd_tag_names_for_group(group)
        fields.extend(_directory_fields(data, subifd.entries, endian, group, tag_names))
    return fields


def _subifd_tag_names_for_group(group: str) -> dict[int, str]:
    if group == "SubIFD1":
        return {**DNG_SUBIFD_TAGS, 0x0111: "PreviewImageStart", 0x0117: "PreviewImageLength"}
    if group == "SubIFD2":
        return {**DNG_SUBIFD_TAGS, 0x0111: "JpgFromRawStart", 0x0117: "JpgFromRawLength"}
    return DNG_SUBIFD_TAGS


def _embedded_image_tags(
    data: bytes,
    ifd0: Ifd,
    endian: Endian,
    diagnostics: list[str],
) -> list[ReadTag]:
    tags: list[ReadTag] = []
    subifd_offsets = _entry_offsets(data, find_entry(ifd0, DNG_SUBIFD_TAG_ID), endian)
    for index, subifd_offset in enumerate(subifd_offsets[:3]):
        group = _subifd_group(index)
        try:
            subifd = parse_ifd(data, subifd_offset, endian)
        except ValueError as error:
            diagnostics.append(str(error))
            continue
        image_field = _embedded_image_field(data, subifd, endian, group)
        if image_field is not None:
            tags.append(
                ReadTag(
                    name=image_field.name,
                    value=image_field.value,
                    provenance=_dng_provenance(image_field),
                    schema=None,
                )
            )
    return tags


def _embedded_image_field(
    data: bytes,
    ifd: Ifd,
    endian: Endian,
    group: str,
) -> DngEmbeddedImageField | None:
    if _read_int_entry(data, ifd, endian, 0x0103) != 7:
        return None
    start = _read_int_entry(data, ifd, endian, 0x0111)
    length = _read_int_entry(data, ifd, endian, 0x0117)
    if start is None or length is None or length <= 0:
        return None
    end = start + length
    if start < 0 or start > len(data) or end > len(data):
        return None
    if group == "SubIFD1":
        return DngEmbeddedImageField(
            name="PreviewImage",
            value=BinaryTagValue(data[start:end], media_type="image/jpeg", file_extension="jpg"),
            group=group,
            tag_id=0x0111,
        )
    if group == "SubIFD2":
        return DngEmbeddedImageField(
            name="JpgFromRaw",
            value=BinaryTagValue(data[start:end], media_type="image/jpeg", file_extension="jpg"),
            group=group,
            tag_id=0x0111,
        )
    return None


def _read_int_entry(data: bytes, ifd: Ifd, endian: Endian, tag_id: int) -> int | None:
    entry = find_entry(ifd, tag_id)
    if entry is None:
        return None
    value = read_entry_value(data, entry, endian)
    return value if isinstance(value, int) else None


def _subifd_group(index: int) -> str:
    if index == 0:
        return "SubIFD"
    if index == 1:
        return "SubIFD1"
    return "SubIFD2"


def _entry_offsets(data: bytes, entry: IfdEntry | None, endian: Endian) -> tuple[int, ...]:
    if entry is None:
        return ()
    value = read_entry_value(data, entry, endian)
    if isinstance(value, int):
        return (value,)
    if isinstance(value, list):
        offsets: list[int] = []
        for item in value:
            if not isinstance(item, int):
                return ()
            offsets.append(item)
        return tuple(offsets)
    return ()


def _directory_fields(
    data: bytes,
    entries: list[IfdEntry],
    endian: Endian,
    group: str,
    tag_names: dict[int, str],
) -> list[DngDirectoryField]:
    fields: list[DngDirectoryField] = []
    for entry in entries:
        name = tag_names.get(entry.tag_id)
        if name is None:
            continue
        value = _print_dng_value(name, read_entry_value(data, entry, endian))
        if value is not None:
            fields.append(DngDirectoryField(name, value, group, entry.tag_id))
    return fields


def _print_dng_value(name: str, value: TiffValue) -> TagValue:
    if name in {"DNGVersion", "DNGBackwardVersion"} and isinstance(value, list):
        return ".".join(str(item) for item in value)
    if name in {
        "ColorMatrix1",
        "ColorMatrix2",
        "CameraCalibration1",
        "CameraCalibration2",
        "AnalogBalance",
        "AsShotNeutral",
        "DNGLensInfo",
        "DefaultScale",
        "YCbCrCoefficients",
        "ReferenceBlackWhite",
    } and isinstance(value, list):
        return _space_join_values(value)
    if name in {
        "AntiAliasStrength",
        "BaselineExposure",
        "BaselineNoise",
        "BaselineSharpness",
        "BestQualityScale",
        "LinearResponseLimit",
        "ShadowScale",
    } and isinstance(value, Fraction):
        return _number(value)
    if name in {"CalibrationIlluminant1", "CalibrationIlluminant2"} and isinstance(value, int):
        return CALIBRATION_ILLUMINANT_PRINT.get(value, value)
    if name == "RawDataUniqueID" and isinstance(value, list):
        return _byte_list_hex(value)
    if name == "CFAPlaneColor" and isinstance(value, list):
        color_names: list[str] = []
        for item in value:
            if not isinstance(item, int):
                return None
            color_names.append(CFA_PLANE_COLOR_PRINT.get(item, f"Unknown ({item})"))
        return ",".join(color_names)
    if name == "CFALayout" and isinstance(value, int):
        return CFA_LAYOUT_PRINT.get(value, value)
    if name == "Compression" and isinstance(value, int):
        return COMPRESSION_PRINT.get(value, value)
    if name == "Orientation" and isinstance(value, int):
        return ORIENTATION_PRINT.get(value, value)
    if name == "PhotometricInterpretation" and isinstance(value, int):
        return PHOTOMETRIC_PRINT.get(value, value)
    if name == "PlanarConfiguration" and isinstance(value, int):
        return PLANAR_CONFIGURATION_PRINT.get(value, value)
    if name == "SubfileType" and isinstance(value, int):
        return SUBFILE_TYPE_PRINT.get(value, value)
    if name == "YCbCrPositioning" and isinstance(value, int):
        return YCBCR_POSITIONING_PRINT.get(value, value)
    if name == "YCbCrSubSampling" and isinstance(value, list):
        rendered = _space_join_values(value)
        return f"YCbCr4:2:0 ({rendered})" if rendered == "2 2" else f"YCbCr4:4:4 ({rendered})"
    if name == "RawDataUniqueID" and isinstance(value, bytes):
        return value.hex().upper()
    if isinstance(value, Fraction):
        return _number(value)
    if isinstance(value, list):
        return _space_join_values(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").rstrip("\x00")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def _space_join_values(values: list[int] | list[Fraction | None]) -> str:
    return " ".join(_string_value(value) for value in values)


def _byte_list_hex(values: list[int] | list[Fraction | None]) -> str | None:
    bytes_values: list[int] = []
    for value in values:
        if not isinstance(value, int):
            return None
        bytes_values.append(value)
    return bytes(bytes_values).hex().upper()


def _string_value(value: int | Fraction | None) -> str:
    if value is None:
        return "undef"
    if isinstance(value, Fraction):
        number = _number(value)
        return str(number)
    return str(value)


def _number(value: Fraction) -> int | float:
    if value.denominator == 1:
        return value.numerator
    return round(float(value), 6)


def _system_tags(path: Path, source_file: str) -> list[ReadTag]:
    return [
        ReadTag(
            name=name,
            value=value,
            provenance=TagProvenance(
                "System",
                "Image::ExifTool::Extra",
                name,
                "filesystem",
                family_0_group="File",
                family_1_group="System",
                family_2_group="Other",
            ),
            schema=None,
        )
        for name, value in read_system_tags(path, source_file).items()
        if isinstance(value, (str, int, float, bool)) or value is None
    ]


def _dng_tags(fields: list[DngDirectoryField]) -> list[ReadTag]:
    return [
        ReadTag(
            name=field.name,
            value=field.value,
            provenance=_dng_provenance(field),
            schema=None,
        )
        for field in fields
    ]


def _dng_provenance(field: DngDirectoryField | DngEmbeddedImageField) -> TagProvenance:
    table = "Image::ExifTool::File" if field.group == "File" else "Image::ExifTool::Exif::Main"
    return TagProvenance(
        field.group,
        table,
        f"0x{field.tag_id:04x}" if field.tag_id else field.name,
        "dng-tiff-ifd",
        family_0_group="File" if field.group == "File" else "EXIF",
        family_1_group=field.group,
        family_2_group="Other" if field.group == "File" else "Image",
    )


def _graph(source_file: str, tags: list[ReadTag], diagnostics: list[str]) -> ReadGraph:
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=int(time.time()),
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )
