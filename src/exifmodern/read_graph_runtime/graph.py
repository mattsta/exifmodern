"""Modern read-result graph for decoded metadata."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Literal, Protocol

from exifmodern.compatibility import EXIFTOOL_COMPATIBILITY_VERSION
from exifmodern.formats.jpeg.container import (
    JpegSegment,
    JpegSegmentProbe,
    exiftool_binary_summary,
    find_next_marker,
    inspect_jpeg_apple_maker_note_bridge,
    inspect_jpeg_canon_maker_note_bridge,
    inspect_jpeg_nikon_maker_note_bridge,
    read_exif_app1,
    read_jpeg_dimensions_from_source,
    read_jpeg_segment_probes_from_source,
    scan_jpeg_segments,
    tiff_ascii_tag_value,
    tiff_entry_raw_value_location,
)
from exifmodern.formats.tiff.primitives import (
    TIFF_TYPE_RATIONAL,
    Endian,
    Ifd,
    TiffEmbeddedImageMaterialization,
    TiffExtractImageByteSource,
    TiffValue,
    materialize_tiff_embedded_images_from_file,
    parse_ifd,
    parse_tiff_header,
    print_value,
    read_entry_value,
)
from exifmodern.json_types import (
    JsonObject,
    JsonValue,
    json_array_value,
    json_bool_value,
    json_int_value,
    json_scalar_to_string,
    json_string_array_or_none,
    load_json_object,
)
from exifmodern.media_source import FileMediaSource
from exifmodern.public_interface.embedded import (
    public_embedded_traversal_decision_message,
    public_embedded_video_recursive_traversal_decision,
)
from exifmodern.public_interface.unknown import (
    REQUEST_ALL_EXTRA_BLOCKERS,
    ProcessBinaryDataUnknownReadResult,
)
from exifmodern.read_graph_runtime.serialization import (
    read_graph_to_json_value as _runtime_read_graph_to_json_value,
)
from exifmodern.read_graph_runtime.serialization import (
    read_tag_to_json_value as _runtime_read_tag_to_json_value,
)
from exifmodern.read_graph_runtime.serialization import (
    tag_provenance_to_json_value as _runtime_tag_provenance_to_json_value,
)
from exifmodern.read_graph_runtime.serialization import (
    tag_value_to_json_value as _runtime_tag_value_to_json_value,
)
from exifmodern.services.system_metadata import read_system_tags
from exifmodern.write_plan import EvidenceAnchor

if TYPE_CHECKING:
    from exifmodern.formats.canon.maker_note import CanonMakerNoteField
    from exifmodern.formats.exif.tiff_rebuild import (
        ExifTiffRebuildHandoff,
        TiffRebuildDiagnostic,
        TiffRebuildReadGraphEmission,
    )
    from exifmodern.formats.flir.metadata_transaction_plan import FlirMainTagInput
    from exifmodern.formats.jpeg.container import (
        JpegAppleMakerNoteBridgeReport,
        JpegNikonMakerNoteBridgeReport,
    )
    from exifmodern.formats.jpeg.html_dump_state import HtmlDumpReadState
    from exifmodern.formats.nikon.maker_note import NikonMakerNoteRawParseContext

type GroupName = str
type TableName = str
type TagName = str
type TagId = str
type DisplayPath = str
type ScalarTagValue = str | int | float | bool | None
type ScalarTagArray = (
    list[ScalarTagValue] | list[str] | list[int] | list[float] | list[bool] | list[None]
)
type TagMap = dict[TagName, TagValue]
type ManufacturerDecodedValue = (
    JsonValue
    | bytes
    | tuple[ScalarTagValue | bytes, ...]
    | tuple[tuple[ScalarTagValue | bytes, ...], ...]
)
type SchemaProvenanceMap = dict[str, ReadTagSchema]
type ReadGraphUnknownTagLevel = Literal[0, 1, 2]
type JpegAppSegmentRead = Callable[[Path], JsonObject]


class ManufacturerEvidenceAnchor(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def line_start(self) -> int: ...

    @property
    def line_end(self) -> int: ...

    @property
    def symbol(self) -> str: ...


type ManufacturerEvidenceRef = ManufacturerEvidenceAnchor | str


class JpegAppSegmentReader(Protocol):
    @property
    def inspection_key(self) -> str: ...

    @property
    def group(self) -> str: ...

    @property
    def table_name(self) -> str: ...

    @property
    def source(self) -> str: ...

    @property
    def missing_message_prefix(self) -> str: ...

    @property
    def tag_ids(self) -> Mapping[str, str]: ...

    @property
    def read(self) -> JpegAppSegmentRead: ...

    @property
    def runtime_dynamic_tag_names(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class LocalJpegAppSegmentReader:
    inspection_key: str
    group: str
    table_name: str
    source: str
    missing_message_prefix: str
    tag_ids: dict[str, str]
    read: JpegAppSegmentRead
    runtime_dynamic_tag_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class BinaryTagValue:
    data: bytes
    media_type: str | None = None
    file_extension: str | None = None

    @property
    def byte_count(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class BinaryTagListValue:
    items: tuple[BinaryTagValue, ...]

    @property
    def byte_count(self) -> int:
        return sum(item.byte_count for item in self.items)

    @property
    def item_count(self) -> int:
        return len(self.items)


type TagValue = ScalarTagValue | ScalarTagArray | BinaryTagValue | BinaryTagListValue


class VendorMakerNoteField(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def value(self) -> TagValue: ...

    @property
    def tag_id(self) -> int: ...

    @property
    def family_2_group(self) -> str: ...


class VendorMakerNoteReadResult(Protocol):
    @property
    def fields(self) -> tuple[VendorMakerNoteField, ...]: ...

    @property
    def diagnostics(self) -> tuple[str, ...]: ...


type VendorMakerNoteReader = Callable[[Path], VendorMakerNoteReadResult]


@dataclass(frozen=True)
class TagProvenance:
    group: GroupName
    table_name: TableName
    tag_id: TagId | None
    source: str
    family_0_group: GroupName | None = None
    family_1_group: GroupName | None = None
    family_2_group: GroupName | None = None
    family_3_group: GroupName | None = None
    family_4_instance_group: GroupName | None = None
    duplicate_instance_ordinal: int | None = None


@dataclass(frozen=True)
class ReadTagSchema:
    matched: bool
    schema_name: str | None
    schema_tag_id: str | None
    writable: str | None
    write_group: str | None
    operation_count: int
    operations: list[str]
    runtime_dynamic: bool


@dataclass(frozen=True)
class ReadTag:
    name: TagName
    value: TagValue
    provenance: TagProvenance
    schema: ReadTagSchema | None


@dataclass(frozen=True)
class ReadGraph:
    schema_version: int
    generated_at_epoch: int
    source_file: str
    tags: list[ReadTag]
    diagnostics: list[str]
    html_dump_state: HtmlDumpReadState | None = None

    def to_json(self) -> str:
        return json.dumps(read_graph_to_json_value(self), indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class ReadGraphRuntimeOptions:
    unknown_tag_level: ReadGraphUnknownTagLevel = 0
    request_all_level: int = 0
    extract_embedded_level: int = 0
    include_html_dump_state: bool = False
    include_dynamic_unknown_ifd_tags: bool = True

    @property
    def requests_process_binarydata_unknowns(self) -> bool:
        return self.unknown_tag_level > 1

    @property
    def requests_request_all_hidden_tags(self) -> bool:
        return self.request_all_level > 2


_DISPATCH_RUNTIME_OPTIONS: ContextVar[ReadGraphRuntimeOptions | None] = ContextVar(
    "exifmodern_dispatch_runtime_options",
    default=None,
)


def set_dispatch_read_graph_runtime_options(
    runtime_options: ReadGraphRuntimeOptions,
) -> Token[ReadGraphRuntimeOptions | None]:
    return _DISPATCH_RUNTIME_OPTIONS.set(runtime_options)


def reset_dispatch_read_graph_runtime_options(
    token: Token[ReadGraphRuntimeOptions | None],
) -> None:
    _DISPATCH_RUNTIME_OPTIONS.reset(token)


def current_dispatch_read_graph_runtime_options() -> ReadGraphRuntimeOptions:
    runtime_options = _DISPATCH_RUNTIME_OPTIONS.get()
    return runtime_options if runtime_options is not None else ReadGraphRuntimeOptions()


def read_graph_to_json_value(graph: ReadGraph) -> JsonObject:
    return _runtime_read_graph_to_json_value(graph)


def read_tag_to_json_value(tag: ReadTag) -> JsonObject:
    return _runtime_read_tag_to_json_value(tag)


def tag_provenance_to_json_value(provenance: TagProvenance) -> JsonObject:
    return _runtime_tag_provenance_to_json_value(provenance)


def tag_value_to_json_value(value: TagValue) -> JsonValue:
    return _runtime_tag_value_to_json_value(value)


FILE_PROVENANCE = TagProvenance(
    group="File",
    table_name="Image::ExifTool::File",
    tag_id=None,
    source="jpeg-signature",
    family_0_group="File",
    family_1_group="File",
    family_2_group="Other",
)
JPEG_PROVENANCE = {
    "ImageWidth": TagProvenance(
        "File",
        "Image::ExifTool::JPEG::Main",
        "SOF.Width",
        "jpeg-sof",
        family_0_group="File",
        family_1_group="File",
        family_2_group="Image",
    ),
    "ImageHeight": TagProvenance(
        "File",
        "Image::ExifTool::JPEG::Main",
        "SOF.Height",
        "jpeg-sof",
        family_0_group="File",
        family_1_group="File",
        family_2_group="Image",
    ),
    "BitsPerSample": TagProvenance(
        "File",
        "Image::ExifTool::JPEG::Main",
        "SOF.Precision",
        "jpeg-sof",
        family_0_group="File",
        family_1_group="File",
        family_2_group="Image",
    ),
    "ColorComponents": TagProvenance(
        "File",
        "Image::ExifTool::JPEG::Main",
        "SOF.Components",
        "jpeg-sof",
        family_0_group="File",
        family_1_group="File",
        family_2_group="Image",
    ),
    "EncodingProcess": TagProvenance(
        "File",
        "Image::ExifTool::JPEG::Main",
        "SOF.Marker",
        "jpeg-sof",
        family_0_group="File",
        family_1_group="File",
        family_2_group="Image",
    ),
    "YCbCrSubSampling": TagProvenance(
        "File",
        "Image::ExifTool::JPEG::Main",
        "SOF.ComponentSampling",
        "jpeg-sof",
        family_0_group="File",
        family_1_group="File",
        family_2_group="Image",
    ),
    "ExifByteOrder": TagProvenance("File", "Image::ExifTool::Exif::Main", None, "jpeg-app1-exif"),
}
TIFF_REBUILD_SOURCE_MATERIALIZATION_LIMIT = 64 * 1024 * 1024
COMPOSITE_TAG_IDS = {
    "ImageSize": "Exif-ImageSize",
    "Megapixels": "Exif-Megapixels",
    "Aperture": "Exif-Aperture",
    "ShutterSpeed": "Exif-ShutterSpeed",
    "LightValue": "Exif-LightValue",
    "ScaleFactor35efl": "Exif-ScaleFactor35efl",
    "CircleOfConfusion": "Exif-CircleOfConfusion",
    "DOF": "Exif-DOF",
    "FOV": "Exif-FOV",
    "FocalLength35efl": "Exif-FocalLength35efl",
    "HyperfocalDistance": "Exif-HyperfocalDistance",
    "LensID": "Exif-LensID",
    "RunTimeSincePowerUp": "Exif-RunTimeSincePowerUp",
    "AutoFocus": "Nikon-AutoFocus",
    "SubSecModifyDate": "Exif-SubSecModifyDate",
    "SubSecCreateDate": "Exif-SubSecCreateDate",
    "SubSecDateTimeOriginal": "Exif-SubSecDateTimeOriginal",
    "GPSAltitude": "GPS-GPSAltitude",
    "GPSDateTime": "GPS-GPSDateTime",
    "GPSLatitude": "GPS-GPSLatitude",
    "GPSLongitude": "GPS-GPSLongitude",
    "GPSPosition": "Exif-GPSPosition",
    "JpgFromRaw": "JpgFromRaw",
    "OtherImage": "OtherImage",
    "BlueBalance": "Exif-BlueBalance",
    "RedBalance": "Exif-RedBalance",
    "AdvancedSceneMode": "Panasonic-AdvancedSceneMode",
}
NIKON_COMPOSITE_LENS_ID_PROVENANCE = TagProvenance(
    "Composite",
    "Image::ExifTool::Nikon::Composite",
    "LensID",
    "nikon-makernote-lensdata-source-lens-identity",
    family_0_group="Composite",
    family_1_group="Composite",
    family_2_group="Camera",
)
TIFF_EMBEDDED_IMAGE_TAG_IDS = {
    "JpgFromRaw": "JpgFromRaw",
    "OtherImage": "OtherImage",
}
EXIFTOOL_TAG_IDS = {
    "ExifToolVersion": "ExifToolVersion",
    "Warning": "Warning",
}
SYSTEM_TAG_IDS = {
    "FileName": "FileName",
    "Directory": "Directory",
    "FileSize": "FileSize",
    "FileModifyDate": "FileModifyDate",
    "FileAccessDate": "FileAccessDate",
    "FileInodeChangeDate": "FileInodeChangeDate",
    "FilePermissions": "FilePermissions",
}
SYSTEM_FAMILY_2_GROUPS = {
    "FileName": "Other",
    "Directory": "Other",
    "FileSize": "Other",
    "FileModifyDate": "Time",
    "FileAccessDate": "Time",
    "FileInodeChangeDate": "Time",
    "FilePermissions": "Other",
}
IFD0_TAG_IDS = {
    "ImageWidth": "0x0100",
    "ImageHeight": "0x0101",
    "ImageDescription": "0x010E",
    "Make": "0x010F",
    "Model": "0x0110",
    "Orientation": "0x0112",
    "XResolution": "0x011A",
    "YResolution": "0x011B",
    "ResolutionUnit": "0x0128",
    "Software": "0x0131",
    "ModifyDate": "0x0132",
    "Artist": "0x013B",
    "HostComputer": "0x013C",
    "YCbCrPositioning": "0x0213",
    "ReferenceBlackWhite": "0x0214",
    "Copyright": "0x8298",
    "PreviewImageStart": "0x0201",
    "PreviewImageLength": "0x0202",
    "PreviewImage": "PreviewImage",
}
IFD1_TAG_IDS = {
    "Compression": "0x0103",
    "Orientation": "0x0112",
    "XResolution": "0x011A",
    "YResolution": "0x011B",
    "ResolutionUnit": "0x0128",
    "YCbCrPositioning": "0x0213",
    "ThumbnailOffset": "0x0201",
    "ThumbnailLength": "0x0202",
    "ThumbnailImage": "ThumbnailImage",
}
EXIF_IFD_TAG_IDS = {
    "ExposureTime": "0x829A",
    "FNumber": "0x829D",
    "ExposureProgram": "0x8822",
    "ISO": "0x8827",
    "SensitivityType": "0x8830",
    "StandardOutputSensitivity": "0x8831",
    "ExifVersion": "0x9000",
    "DateTimeOriginal": "0x9003",
    "CreateDate": "0x9004",
    "ComponentsConfiguration": "0x9101",
    "CompressedBitsPerPixel": "0x9102",
    "ShutterSpeedValue": "0x9201",
    "ApertureValue": "0x9202",
    "BrightnessValue": "0x9203",
    "ExposureCompensation": "0x9204",
    "MaxApertureValue": "0x9205",
    "SubjectDistance": "0x9206",
    "MeteringMode": "0x9207",
    "LightSource": "0x9208",
    "Flash": "0x9209",
    "FocalLength": "0x920A",
    "SubjectArea": "0x9214",
    "UserComment": "0x9286",
    "SubSecTime": "0x9290",
    "SubSecTimeOriginal": "0x9291",
    "SubSecTimeDigitized": "0x9292",
    "OffsetTime": "0x9010",
    "OffsetTimeOriginal": "0x9011",
    "OffsetTimeDigitized": "0x9012",
    "FlashpixVersion": "0xA000",
    "ColorSpace": "0xA001",
    "ExifImageWidth": "0xA002",
    "ExifImageHeight": "0xA003",
    "FocalPlaneXResolution": "0xA20E",
    "FocalPlaneYResolution": "0xA20F",
    "FocalPlaneResolutionUnit": "0xA210",
    "ExposureIndex": "0xA215",
    "SensingMethod": "0xA217",
    "FileSource": "0xA300",
    "SceneType": "0xA301",
    "CustomRendered": "0xA401",
    "ExposureMode": "0xA402",
    "WhiteBalance": "0xA403",
    "DigitalZoomRatio": "0xA404",
    "FocalLengthIn35mmFormat": "0xA405",
    "SceneCaptureType": "0xA406",
    "GainControl": "0xA407",
    "Contrast": "0xA408",
    "Saturation": "0xA409",
    "Sharpness": "0xA40A",
    "DeviceSettingDescription": "0xA40B",
    "SubjectDistanceRange": "0xA40C",
    "ImageUniqueID": "0xA420",
    "LensInfo": "0xA432",
    "LensMake": "0xA433",
    "LensModel": "0xA434",
    "SerialNumber": "0xA431",
    "CompositeImage": "0xA460",
    "OwnerName": "0xA430",
}
INTEROP_IFD_TAG_IDS = {
    "InteropIndex": "0x0001",
    "InteropVersion": "0x0002",
}
GPS_TAG_IDS = {
    "GPSVersionID": "0x0000",
    "GPSLatitudeRef": "0x0001",
    "GPSLatitude": "0x0002",
    "GPSLongitudeRef": "0x0003",
    "GPSLongitude": "0x0004",
    "GPSAltitudeRef": "0x0005",
    "GPSAltitude": "0x0006",
    "GPSTimeStamp": "0x0007",
    "GPSSpeedRef": "0x000C",
    "GPSSpeed": "0x000D",
    "GPSImgDirectionRef": "0x0010",
    "GPSImgDirection": "0x0011",
    "GPSMapDatum": "0x0012",
    "GPSDestBearingRef": "0x0017",
    "GPSDestBearing": "0x0018",
    "GPSProcessingMethod": "0x001B",
    "GPSDateStamp": "0x001D",
    "GPSHPositioningError": "0x001F",
}
GPS_FAMILY_2_GROUPS = {
    "GPSTimeStamp": "Time",
    "GPSDateStamp": "Time",
}


def build_read_graph(
    path: Path,
    schema_provenance: Path | None = None,
    display_path: DisplayPath | None = None,
    runtime_options: ReadGraphRuntimeOptions | None = None,
) -> ReadGraph:
    runtime_options = runtime_options if runtime_options is not None else ReadGraphRuntimeOptions()
    tags: list[ReadTag] = []
    diagnostics: list[str] = []
    source_file = path.as_posix()
    source = FileMediaSource(path)
    is_jpeg_source = source.prefix(3).startswith(b"\xff\xd8\xff")
    schema_map = load_schema_provenance_map(schema_provenance)

    add_tags(
        tags,
        {"ExifToolVersion": EXIFTOOL_COMPATIBILITY_VERSION},
        exiftool_provenance(),
        schema_map,
    )
    add_optional_manufacturer_warning_tags(tags, path)
    add_optional_system_group(tags, diagnostics, path, display_path, schema_map)
    add_file_identity(tags, diagnostics, path, schema_map)
    if is_jpeg_source:
        try:
            exif_app1 = read_exif_app1(path)
            add_tags(tags, {"ExifByteOrder": exif_app1.byte_order}, JPEG_PROVENANCE, schema_map)
        except ValueError as exc:
            diagnostics.append(str(exc))

        try:
            dimensions = read_jpeg_dimensions_from_source(source, source_file)
            add_tags(
                tags,
                jpeg_tags(
                    {
                        "ImageWidth": dimensions.width,
                        "ImageHeight": dimensions.height,
                        "EncodingProcess": encoding_process(dimensions.sof_marker),
                        "BitsPerSample": dimensions.bits_per_sample,
                        "ColorComponents": dimensions.color_components,
                    },
                    dimensions.ycbcr_subsampling,
                ),
                JPEG_PROVENANCE,
                schema_map,
            )
        except ValueError as exc:
            diagnostics.append(str(exc))

        add_optional_jpeg_app_segment_groups(
            tags, diagnostics, path, source, schema_map, runtime_options
        )
        add_optional_manufacturer_jpeg_payload_tags(
            tags, diagnostics, path, source, schema_map, runtime_options
        )
    shared_context = shared_tiff_context(path, diagnostics)
    add_optional_ifd0_tiff_tags(tags, diagnostics, shared_context, schema_map)
    add_optional_exif_ifd_and_composite_groups(tags, diagnostics, shared_context, schema_map)
    add_optional_gps_tiff_tags(tags, shared_context, schema_map)
    add_optional_ifd1_group(tags, diagnostics, shared_context, schema_map)
    if is_jpeg_source:
        add_optional_jpeg_exif_unknown_ifd_tags(
            tags, diagnostics, path, schema_map, runtime_options
        )
        add_optional_jpeg_request_all_tags(tags, diagnostics, source, schema_map, runtime_options)
        add_optional_jpeg_extract_embedded_tags(
            tags, diagnostics, source, schema_map, runtime_options
        )
    normalize_shared_tiff_exif_rendered_tags(tags)
    add_optional_tiff_embedded_image_tags(tags, diagnostics, path, source, schema_map)
    add_optional_exif_tiff_rebuild_tags(tags, diagnostics, path, source, schema_map)
    if is_jpeg_source:
        add_optional_selected_jpeg_maker_note_bridge_tags(tags, diagnostics, path, schema_map)
    add_optional_camera_vendor_maker_note_tags(
        tags,
        diagnostics,
        path,
        source,
        shared_context,
        schema_map,
        runtime_options,
    )
    add_optional_unknown_maker_note_tags(tags, diagnostics, path, shared_context, schema_map)
    add_graph_derived_composite_tags(tags, schema_map, path)
    add_graph_derived_exiftool_tags(tags, schema_map)

    html_dump_state: HtmlDumpReadState | None = None
    if runtime_options.include_html_dump_state and source.prefix(2) == b"\xff\xd8":
        from exifmodern.formats.jpeg.html_dump_state import build_jpeg_html_dump_read_state

        try:
            source_data = source.read_full()
            html_dump_state = build_jpeg_html_dump_read_state(source_data, source_file)
        except ValueError as exc:
            diagnostics.append(str(exc))

    return ReadGraph(
        schema_version=1,
        generated_at_epoch=int(time.time()),
        source_file=source_file,
        tags=with_jpeg_thumbnail_duplicate_provenance(tags),
        diagnostics=clean_successful_read_diagnostics(tags, diagnostics),
        html_dump_state=html_dump_state,
    )


def clean_successful_read_diagnostics(
    tags: list[ReadTag],
    diagnostics: list[str],
) -> list[str]:
    if not any(tag.provenance.source == "jpeg-trailer-afcp-iptc" for tag in tags):
        return diagnostics
    return [
        diagnostic
        for diagnostic in diagnostics
        if not diagnostic.startswith("No JPEG EXIF APP1 segment found")
    ]


def write_read_graph(
    path: Path,
    output: Path | None,
    schema_provenance: Path | None = None,
) -> None:
    payload = build_read_graph(path, schema_provenance).to_json()
    if output is None:
        print(payload, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")


def add_file_identity(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    schema_map: SchemaProvenanceMap,
) -> None:
    with path.open("rb") as file:
        prefix = file.read(16)
    if not prefix.startswith(b"\xff\xd8\xff"):
        diagnostics.append(f"Unsupported file signature for path: {path}")
        return
    add_tags(
        tags,
        {
            "FileType": "JPEG",
            "FileTypeExtension": "jpg",
            "MIMEType": "image/jpeg",
        },
        {
            "FileType": FILE_PROVENANCE,
            "FileTypeExtension": FILE_PROVENANCE,
            "MIMEType": FILE_PROVENANCE,
        },
        schema_map,
    )


def jpeg_tags(tags: TagMap, ycbcr_subsampling: str | None) -> TagMap:
    if ycbcr_subsampling is None:
        return tags
    return {**tags, "YCbCrSubSampling": ycbcr_subsampling}


def composite_image_tags(width: int, height: int) -> TagMap:
    megapixels = width * height / 1_000_000
    return {
        "ImageSize": f"{width}x{height}",
        "Megapixels": round_megapixels(megapixels),
    }


def round_megapixels(value: float) -> float:
    if value >= 1:
        return round(value, 1)
    if value >= 0.001:
        return round(value, 3)
    return round(value, 6)


def add_optional_ifd0_tiff_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    context: SharedTiffContext | None,
    schema_map: SchemaProvenanceMap,
) -> None:
    if context is None:
        return
    values = shared_tiff_values(
        context.data,
        context.endian,
        context.ifd0,
        tiff_tag_id_lookup(IFD0_TAG_IDS, exclude={"PreviewImage"}),
        render_shared_ifd_value,
    )
    preview_start = values.get("PreviewImageStart")
    preview_length = values.get("PreviewImageLength")
    if isinstance(preview_start, int):
        values["PreviewImageStart"] = preview_start + context.tiff_header_file_offset
    if isinstance(preview_length, int) and preview_length > 0:
        values["PreviewImage"] = exiftool_binary_summary(preview_length)
        if (
            isinstance(preview_start, int)
            and preview_start >= 0
            and preview_start + preview_length <= len(context.data)
        ):
            values["PreviewImage"] = BinaryTagValue(
                context.data[preview_start : preview_start + preview_length],
                media_type="image/jpeg",
                file_extension="jpg",
            )
        else:
            diagnostics.append("JPEG EXIF IFD0 preview payload is truncated")
    add_tags(tags, values, ifd0_provenance(), schema_map)


@dataclass(frozen=True)
class SharedTiffContext:
    data: bytes
    endian: Endian
    byte_order: str
    tiff_header_file_offset: int
    ifd0: Ifd
    exif_ifd: Ifd | None
    gps_ifd: Ifd | None
    ifd1: Ifd | None
    interop_ifd: Ifd | None


SHARED_EXIF_LIGHT_SOURCE = {
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
SHARED_EXIF_GAIN_CONTROL = {
    0: "None",
    1: "Low gain up",
    2: "High gain up",
    3: "Low gain down",
    4: "High gain down",
}
SHARED_EXIF_SENSITIVITY_TYPE = {
    0: "Unknown",
    1: "Standard Output Sensitivity",
    2: "Recommended Exposure Index",
    3: "ISO Speed",
    4: "Standard Output Sensitivity and Recommended Exposure Index",
    5: "Standard Output Sensitivity and ISO Speed",
    6: "Recommended Exposure Index and ISO Speed",
    7: "Standard Output Sensitivity, Recommended Exposure Index and ISO Speed",
}
SHARED_EXIF_NORMAL_LOW_HIGH = {
    0: "Normal",
    1: "Low",
    2: "High",
}
SHARED_EXIF_SHARPNESS = {
    0: "Normal",
    1: "Soft",
    2: "Hard",
}
SHARED_EXIF_SUBJECT_DISTANCE_RANGE = {
    0: "Unknown",
    1: "Macro",
    2: "Close",
    3: "Distant",
}
SHARED_EXIF_COMPOSITE_IMAGE = {
    0: "Unknown",
    1: "Not a Composite Image",
    2: "General Composite Image",
    3: "Composite Image Captured While Shooting",
}
SHARED_INTEROP_INDEX = {
    "R98": "R98 - DCF basic file (sRGB)",
    "R03": "R03 - DCF option file (Adobe RGB)",
    "THM": "THM - DCF thumbnail file",
}


def add_optional_shared_ifd0_tiff_tags(
    tags: list[ReadTag],
    context: SharedTiffContext | None,
    schema_map: SchemaProvenanceMap,
) -> None:
    if context is None:
        return
    values = shared_tiff_values(
        context.data,
        context.endian,
        context.ifd0,
        {"ImageWidth": 0x0100, "ImageHeight": 0x0101},
        render_shared_ifd_value,
    )
    insert_tags(tags, values, ifd0_provenance(), schema_map, IFD0_TAG_IDS)


def add_optional_shared_exif_and_interop_tiff_tags(
    tags: list[ReadTag],
    context: SharedTiffContext | None,
    schema_map: SchemaProvenanceMap,
) -> None:
    if context is None or context.exif_ifd is None:
        return
    values = shared_tiff_values(
        context.data,
        context.endian,
        context.exif_ifd,
        {
            "SubjectDistance": 0x9206,
            "SensitivityType": 0x8830,
            "StandardOutputSensitivity": 0x8831,
            "LightSource": 0x9208,
            "SubSecTime": 0x9290,
            "OffsetTime": 0x9010,
            "OffsetTimeOriginal": 0x9011,
            "OffsetTimeDigitized": 0x9012,
            "ExposureIndex": 0xA215,
            "DigitalZoomRatio": 0xA404,
            "GainControl": 0xA407,
            "Contrast": 0xA408,
            "Saturation": 0xA409,
            "Sharpness": 0xA40A,
            "DeviceSettingDescription": 0xA40B,
            "SubjectDistanceRange": 0xA40C,
            "ImageUniqueID": 0xA420,
            "SerialNumber": 0xA431,
            "CompositeImage": 0xA460,
        },
        render_shared_exif_value,
    )
    insert_tags(tags, values, exif_ifd_provenance(), schema_map, EXIF_IFD_TAG_IDS)
    if context.interop_ifd is None:
        return
    interop_values = shared_tiff_values(
        context.data,
        context.endian,
        context.interop_ifd,
        {"InteropIndex": 0x0001, "InteropVersion": 0x0002},
        render_shared_interop_value,
    )
    insert_tags(tags, interop_values, interop_ifd_provenance(), schema_map, INTEROP_IFD_TAG_IDS)
    printim_version = shared_printim_version(context.data, context.endian, context.ifd0)
    if printim_version is not None:
        insert_tags(
            tags,
            {"PrintIMVersion": printim_version},
            printim_provenance(),
            schema_map,
            {"PrintIMVersion": "0x0000"},
        )


def add_optional_shared_gps_tiff_tags(
    tags: list[ReadTag],
    context: SharedTiffContext | None,
    schema_map: SchemaProvenanceMap,
) -> None:
    if context is None or context.gps_ifd is None:
        return
    values = shared_tiff_values(
        context.data,
        context.endian,
        context.gps_ifd,
        {"GPSProcessingMethod": 0x001B},
        render_shared_gps_value,
    )
    insert_tags(tags, values, gps_provenance(), schema_map, GPS_TAG_IDS)


def add_optional_shared_ifd1_tiff_tags(
    tags: list[ReadTag],
    context: SharedTiffContext | None,
    schema_map: SchemaProvenanceMap,
) -> None:
    if context is None or context.ifd1 is None:
        return
    values = shared_tiff_values(
        context.data,
        context.endian,
        context.ifd1,
        {"Orientation": 0x0112, "YCbCrPositioning": 0x0213},
        render_shared_ifd_value,
    )
    insert_tags(tags, values, ifd1_provenance(), schema_map, IFD1_TAG_IDS)


def add_optional_jpeg_exif_unknown_ifd_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    schema_map: SchemaProvenanceMap,
    runtime_options: ReadGraphRuntimeOptions,
) -> None:
    if not runtime_options.include_dynamic_unknown_ifd_tags:
        return
    from exifmodern.formats.jpeg.unknown_read_graph import collect_jpeg_exif_unknown_ifd_read_tags

    result = collect_jpeg_exif_unknown_ifd_read_tags(path)
    diagnostics.extend(result.diagnostics)
    for field in result.tags:
        tags.append(
            ReadTag(
                field.name,
                field.value,
                TagProvenance(
                    field.group,
                    field.table_name,
                    f"0x{field.tag_id:04x}",
                    "jpeg-app1-tiff-dynamic-unknown",
                    family_0_group="EXIF",
                    family_1_group=field.group,
                    family_2_group="Location" if field.group == "GPS" else "Image",
                ),
                ReadTagSchema(
                    matched=False,
                    schema_name=None,
                    schema_tag_id=f"0x{field.tag_id:04x}",
                    writable=None,
                    write_group=None,
                    operation_count=0,
                    operations=["ExifTool dynamic unknown numeric tag synthesis"],
                    runtime_dynamic=True,
                ),
            )
        )


def add_optional_jpeg_request_all_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    source: FileMediaSource,
    schema_map: SchemaProvenanceMap,
    runtime_options: ReadGraphRuntimeOptions,
) -> None:
    if not runtime_options.requests_request_all_hidden_tags:
        return
    if source.prefix(2) != b"\xff\xd8":
        return
    values: TagMap = {}
    provenances: dict[TagName, TagProvenance] = {}
    scan = scan_jpeg_image_boundary_for_request_all(source)
    image_length = scan.image_length
    if image_length is None:
        diagnostics.append(
            "JPEG RequestAll=3 JPEGImageLength blocked: unable to locate a complete JPEG EOI."
        )
    else:
        values["JPEGImageLength"] = image_length
        provenances["JPEGImageLength"] = TagProvenance(
            "File",
            "Image::ExifTool::Extra",
            "JPEGImageLength",
            "jpeg-requestall-image-length",
            family_0_group="File",
            family_1_group="File",
            family_2_group="Image",
        )
    metadata_prefix = jpeg_metadata_prefix_for_request_all(source, diagnostics)
    jpeg_digest = (
        jpeg_digest_for_request_all(metadata_prefix, diagnostics)
        if metadata_prefix is not None
        else None
    )
    if jpeg_digest is not None:
        values["JPEGDigest"] = jpeg_digest
        provenances["JPEGDigest"] = TagProvenance(
            "File",
            "Image::ExifTool::Extra",
            "JPEGDigest",
            "jpeg-requestall-jpeg-digest",
            family_0_group="File",
            family_1_group="File",
            family_2_group="Image",
        )
    jpeg_quality = (
        jpeg_quality_estimate_for_request_all(metadata_prefix)
        if metadata_prefix is not None
        else None
    )
    if jpeg_quality is not None:
        values["JPEGQualityEstimate"] = jpeg_quality
        provenances["JPEGQualityEstimate"] = TagProvenance(
            "File",
            "Image::ExifTool::Extra",
            "JPEGQualityEstimate",
            "jpeg-requestall-jpeg-quality-estimate",
            family_0_group="File",
            family_1_group="File",
            family_2_group="Image",
        )
    add_jpeg_request_all_trailer_blocker(scan, diagnostics)
    add_request_all_extra_blockers(diagnostics)
    if not values:
        return
    add_tags(tags, values, provenances, schema_map)


@dataclass(frozen=True)
class JpegImageBoundaryScan:
    eoi_end_offset: int | None
    app_segment_bytes: int
    source_size: int

    @property
    def image_length(self) -> int | None:
        if self.eoi_end_offset is None:
            return None
        return self.eoi_end_offset - self.app_segment_bytes

    @property
    def trailer_length(self) -> int:
        if self.eoi_end_offset is None:
            return 0
        return max(0, self.source_size - self.eoi_end_offset)


def scan_jpeg_image_boundary_for_request_all(source: FileMediaSource) -> JpegImageBoundaryScan:
    """Stream JPEG markers to find EOI without materializing image entropy."""

    app_segment_bytes = 0
    with source.open() as file:
        if file.read(2) != b"\xff\xd8":
            return JpegImageBoundaryScan(None, 0, source.size)
        while True:
            marker_offset, marker = read_next_jpeg_marker_from_file(file)
            offset = marker_offset + 2
            if marker == 0xD9:
                return JpegImageBoundaryScan(offset, app_segment_bytes, source.size)
            if marker in {0x01, *range(0xD0, 0xD8), 0xD8}:
                continue
            length_bytes = file.read(2)
            if len(length_bytes) != 2:
                return JpegImageBoundaryScan(None, app_segment_bytes, source.size)
            segment_length = int.from_bytes(length_bytes, "big")
            if segment_length < 2:
                return JpegImageBoundaryScan(None, app_segment_bytes, source.size)
            payload_length = segment_length - 2
            if 0xE0 <= marker <= 0xEF:
                app_segment_bytes += payload_length + 4
            file.seek(payload_length, 1)


def jpeg_metadata_prefix_for_request_all(
    source: FileMediaSource,
    diagnostics: list[str],
) -> bytes | None:
    """Read JPEG metadata segments through SOS for digest/quality calculation only."""

    payload = bytearray(b"\xff\xd8")
    try:
        with source.open() as file:
            if file.read(2) != b"\xff\xd8":
                return None
            while True:
                marker_offset, marker = read_next_jpeg_marker_from_file(file)
                del marker_offset
                payload.extend((0xFF, marker))
                if marker in {0x01, *range(0xD0, 0xD8), 0xD8, 0xD9}:
                    if marker == 0xD9:
                        return bytes(payload)
                    continue
                length_bytes = file.read(2)
                if len(length_bytes) != 2:
                    diagnostics.append(
                        "JPEG RequestAll=3 JPEGDigest blocked: truncated segment length."
                    )
                    return None
                payload.extend(length_bytes)
                segment_length = int.from_bytes(length_bytes, "big")
                if segment_length < 2:
                    diagnostics.append(
                        "JPEG RequestAll=3 JPEGDigest blocked: invalid segment length."
                    )
                    return None
                segment_payload = file.read(segment_length - 2)
                if len(segment_payload) != segment_length - 2:
                    diagnostics.append(
                        "JPEG RequestAll=3 JPEGDigest blocked: truncated segment payload."
                    )
                    return None
                payload.extend(segment_payload)
                if marker == 0xDA:
                    return bytes(payload)
    except ValueError as exc:
        diagnostics.append(f"JPEG RequestAll=3 JPEGDigest blocked: {exc}")
        return None


def read_next_jpeg_marker_from_file(file: BinaryIO) -> tuple[int, int]:
    while True:
        marker_prefix = file.read(1)
        if marker_prefix == b"":
            raise ValueError("Truncated JPEG stream before marker")
        if marker_prefix != b"\xff":
            continue
        marker_offset = file.tell() - 1
        marker_byte = file.read(1)
        while marker_byte == b"\xff":
            marker_byte = file.read(1)
        if marker_byte == b"":
            raise ValueError("Truncated JPEG marker")
        if marker_byte == b"\x00":
            continue
        return marker_offset, marker_byte[0]


def jpeg_digest_for_request_all(data: bytes, diagnostics: list[str]) -> str | None:
    from exifmodern.formats.jpeg_digest import build_jpeg_digest_transaction_plan

    plan = build_jpeg_digest_transaction_plan(data, allow_output_emission=True)
    if not plan.dqt_segments:
        return None
    if plan.jpeg_digest is None:
        gate_codes = ", ".join(gate.code for gate in plan.output_emission_gates)
        diagnostics.append(f"JPEG RequestAll=3 JPEGDigest blocked: {gate_codes}.")
        return None
    return plan.digest_description if plan.digest_description is not None else plan.jpeg_digest


def jpeg_quality_estimate_for_request_all(data: bytes) -> TagValue | None:
    from exifmodern.formats.jpeg_digest import build_jpeg_digest_transaction_plan

    plan = build_jpeg_digest_transaction_plan(data, allow_output_emission=True)
    if not plan.dqt_segments:
        return None
    return plan.jpeg_quality_estimate if plan.jpeg_quality_estimate is not None else "<unknown>"


def add_jpeg_request_all_trailer_blocker(
    scan: JpegImageBoundaryScan,
    diagnostics: list[str],
) -> None:
    if scan.trailer_length <= 0:
        return
    diagnostics.append(
        "JPEG RequestAll=3 Trailer blocked: Extra Trailer is the full JPEG trailer "
        "binary block and is not exposed by the public read graph without an explicit "
        "safe binary output policy."
    )


def add_request_all_extra_blockers(diagnostics: list[str]) -> None:
    diagnostics.extend(blocker.message for blocker in REQUEST_ALL_EXTRA_BLOCKERS)


def jpeg_trailer_payload_for_request_all(data: bytes) -> bytes | None:
    eoi_end = jpeg_eoi_end_offset(data)
    if eoi_end is None:
        return None
    trailer = data[eoi_end:]
    return trailer or None


def add_optional_jpeg_extract_embedded_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    source: FileMediaSource,
    schema_map: SchemaProvenanceMap,
    runtime_options: ReadGraphRuntimeOptions,
) -> None:
    if runtime_options.extract_embedded_level <= 0:
        return
    if source.prefix(2) != b"\xff\xd8":
        return
    embedded_video = jpeg_embedded_video_trailer_payload_from_source(source)
    if embedded_video is None:
        return
    traversal_decision = public_embedded_video_recursive_traversal_decision(
        runtime_options.extract_embedded_level,
        len(embedded_video),
    )
    if traversal_decision is not None:
        diagnostics.append(public_embedded_traversal_decision_message(traversal_decision))
    add_tags(
        tags,
        {
            "EmbeddedVideo": BinaryTagValue(
                embedded_video,
                media_type="video/mp4",
                file_extension="mp4",
            )
        },
        {
            "EmbeddedVideo": TagProvenance(
                "Trailer",
                "Image::ExifTool::Extra",
                "EmbeddedVideo",
                "jpeg-extractembedded-trailer-embedded-video",
                family_0_group="Trailer",
                family_1_group="Trailer",
                family_2_group="Video",
            )
        },
        schema_map,
    )


def jpeg_embedded_video_trailer_payload_from_source(source: FileMediaSource) -> bytes | None:
    scan = scan_jpeg_image_boundary_for_request_all(source)
    if scan.eoi_end_offset is None or scan.trailer_length < 8:
        return None
    trailer_prefix = source.read_at(scan.eoi_end_offset, 8)
    if len(trailer_prefix) < 8 or trailer_prefix[4:8] != b"ftyp":
        return None
    return source.read_at(scan.eoi_end_offset, scan.trailer_length)


def jpeg_embedded_video_trailer_payload(data: bytes) -> bytes | None:
    eoi_end = jpeg_eoi_end_offset(data)
    if eoi_end is None:
        return None
    trailer = data[eoi_end:]
    if len(trailer) < 8 or trailer[4:8] != b"ftyp":
        return None
    return trailer


def jpeg_eoi_end_offset(data: bytes) -> int | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    offset = 2
    while offset < len(data):
        marker_offset = find_next_marker(data, offset)
        if marker_offset is None or marker_offset + 1 >= len(data):
            return None
        marker = data[marker_offset + 1]
        offset = marker_offset + 2
        if marker == 0xD9:
            return offset
        if marker in {0x01, *range(0xD0, 0xD8), 0xD8}:
            continue
        if offset + 2 > len(data):
            return None
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2:
            return None
        segment_end = offset + segment_length
        if segment_end > len(data):
            return None
        offset = segment_end
    return None


def jpeg_image_length_for_request_all(data: bytes) -> int | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    app_bytes = 0
    offset = 2
    while offset < len(data):
        marker_offset = find_next_marker(data, offset)
        if marker_offset is None or marker_offset + 1 >= len(data):
            return None
        marker = data[marker_offset + 1]
        offset = marker_offset + 2
        if marker == 0xD9:
            return offset - app_bytes
        if marker in {0x01, *range(0xD0, 0xD8), 0xD8}:
            continue
        if offset + 2 > len(data):
            return None
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2:
            return None
        payload_length = segment_length - 2
        segment_end = offset + 2 + payload_length
        if segment_end > len(data):
            return None
        if 0xE0 <= marker <= 0xEF:
            app_bytes += payload_length + 4
        offset = segment_end

    return None


def shared_tiff_context(path: Path, diagnostics: list[str]) -> SharedTiffContext | None:
    try:
        app1 = read_exif_app1(path)
        header = parse_tiff_header(app1.tiff_data)
        ifd0 = parse_ifd(app1.tiff_data, header.first_ifd_offset, header.endian)
    except ValueError as exc:
        message = str(exc)
        if not message.startswith("No JPEG EXIF APP1 segment found"):
            diagnostics.append(message)
        return None
    exif_ifd = shared_pointer_ifd(app1.tiff_data, header.endian, ifd0, 0x8769)
    gps_ifd = shared_pointer_ifd(app1.tiff_data, header.endian, ifd0, 0x8825)
    interop_ifd = (
        shared_pointer_ifd(app1.tiff_data, header.endian, exif_ifd, 0xA005)
        if exif_ifd is not None
        else None
    )
    ifd1 = None
    if ifd0.next_ifd_offset:
        try:
            ifd1 = parse_ifd(app1.tiff_data, ifd0.next_ifd_offset, header.endian)
        except ValueError as exc:
            diagnostics.append(str(exc))
    return SharedTiffContext(
        app1.tiff_data,
        header.endian,
        app1.byte_order,
        app1.tiff_header_offset,
        ifd0,
        exif_ifd,
        gps_ifd,
        ifd1,
        interop_ifd,
    )


def tiff_tag_id_lookup(
    tag_ids: dict[TagName, TagId],
    exclude: set[TagName] | None = None,
) -> dict[TagName, int]:
    excluded = exclude if exclude is not None else set()
    lookup: dict[TagName, int] = {}
    for name, tag_id in tag_ids.items():
        if name in excluded or not tag_id.startswith("0x"):
            continue
        lookup[name] = int(tag_id, 16)
    return lookup


def shared_pointer_ifd(data: bytes, endian: Endian, ifd: Ifd | None, tag_id: int) -> Ifd | None:
    if ifd is None:
        return None
    entry = next((candidate for candidate in ifd.entries if candidate.tag_id == tag_id), None)
    if entry is None:
        return None
    value = read_entry_value(data, entry, endian)
    if not isinstance(value, int):
        return None
    try:
        return parse_ifd(data, value, endian)
    except ValueError:
        return None


def shared_tiff_values(
    data: bytes,
    endian: Endian,
    ifd: Ifd,
    tag_ids: dict[TagName, int],
    renderer: Callable[[TagName, TiffValue], TagValue | None],
) -> TagMap:
    values: TagMap = {}
    names_by_id = {tag_id: name for name, tag_id in tag_ids.items()}
    for entry in ifd.entries:
        name = names_by_id.get(entry.tag_id)
        if name is None:
            continue
        try:
            raw_value = read_entry_value(data, entry, endian)
        except ValueError:
            continue
        value = renderer(name, raw_value)
        if value is not None:
            values[name] = value
    return values


def render_shared_ifd_value(name: TagName, value: TiffValue) -> TagValue | None:
    rendered = print_value(name, value)
    if isinstance(rendered, str | int | float | bool) or rendered is None:
        return rendered
    return None


def render_shared_exif_value(name: TagName, value: TiffValue) -> TagValue | None:
    if name == "SensitivityType" and isinstance(value, int):
        return SHARED_EXIF_SENSITIVITY_TYPE.get(value, f"Unknown ({value})")
    if name == "LightSource" and isinstance(value, int):
        return SHARED_EXIF_LIGHT_SOURCE.get(value, value)
    if name == "GainControl" and isinstance(value, int):
        return SHARED_EXIF_GAIN_CONTROL.get(value, value)
    if name in {"Contrast", "Saturation"} and isinstance(value, int):
        return SHARED_EXIF_NORMAL_LOW_HIGH.get(value, value)
    if name == "Sharpness" and isinstance(value, int):
        return SHARED_EXIF_SHARPNESS.get(value, value)
    if name == "SubjectDistanceRange" and isinstance(value, int):
        return SHARED_EXIF_SUBJECT_DISTANCE_RANGE.get(value, value)
    if name == "CompositeImage" and isinstance(value, int):
        return SHARED_EXIF_COMPOSITE_IMAGE.get(value, value)
    if name == "SubjectDistance":
        if value is None:
            return "undef"
        if isinstance(value, Fraction):
            return f"{shared_fraction_number(value)} m"
    if name == "ImageUniqueID" and isinstance(value, str):
        return value
    if name == "ExposureIndex" and isinstance(value, Fraction):
        return f"{float(value):.10g}"
    if name == "DigitalZoomRatio" and isinstance(value, Fraction):
        return shared_fraction_scalar(value)
    if name == "DeviceSettingDescription" and isinstance(value, bytes):
        return BinaryTagValue(value)
    if name in {"SubSecTime", "SubSecTimeOriginal", "SubSecTimeDigitized"} and isinstance(
        value,
        str,
    ):
        return value.rstrip()
    rendered = print_value(name, value)
    if isinstance(rendered, str | int | float | bool) or rendered is None:
        return rendered
    return None


def render_shared_interop_value(name: TagName, value: TiffValue) -> TagValue | None:
    if name == "InteropIndex" and isinstance(value, str):
        return SHARED_INTEROP_INDEX.get(value, value)
    if name == "InteropVersion" and isinstance(value, bytes):
        return value.rstrip(b"\0").decode("ascii", errors="replace")
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return None


def render_shared_gps_value(name: TagName, value: TiffValue) -> TagValue | None:
    if name == "GPSAltitude" and value is None:
        return "undef"
    if name == "GPSProcessingMethod" and isinstance(value, bytes):
        if len(value) < 8:
            return ""
        return value[8:].rstrip(b"\0").decode("latin-1", errors="replace")
    rendered = print_value(name, value)
    if isinstance(rendered, str | int | float | bool) or rendered is None:
        return rendered
    return None


def shared_printim_version(data: bytes, endian: Endian, ifd0: Ifd) -> str | None:
    entry = next((candidate for candidate in ifd0.entries if candidate.tag_id == 0xC4A5), None)
    if entry is None:
        return None
    try:
        value = read_entry_value(data, entry, endian)
    except ValueError:
        return None
    if not isinstance(value, bytes) or not value.startswith(b"PrintIM\0"):
        return None
    raw_version = value[len(b"PrintIM\0") : len(b"PrintIM\0") + 4]
    if len(raw_version) != 4:
        return None
    return raw_version.decode("ascii", errors="replace")


def shared_fraction_scalar(value: Fraction) -> int | float:
    if value.denominator == 1:
        return value.numerator
    return float(value)


def shared_fraction_number(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{float(value):.12g}"


def insert_tags(
    tags: list[ReadTag],
    values: TagMap,
    provenances: dict[TagName, TagProvenance],
    schema_map: SchemaProvenanceMap,
    order_map: dict[TagName, TagId],
) -> None:
    for name, value in values.items():
        if find_group_tag_value(tags, provenances[name].group, name) is not None:
            continue
        insert_tag_in_group_order(
            tags,
            ReadTag(
                name=name,
                value=value,
                provenance=provenances[name],
                schema=schema_map.get(schema_tag_key(provenances[name].group, name)),
            ),
            order_map,
        )


def insert_tag_in_group_order(
    tags: list[ReadTag],
    tag: ReadTag,
    order_map: dict[TagName, TagId],
) -> None:
    new_order = tag_order_value(order_map, tag.name)
    insert_at: int | None = None
    last_group_index: int | None = None
    for index, existing in enumerate(tags):
        if existing.provenance.group != tag.provenance.group:
            continue
        last_group_index = index
        if tag_order_value(order_map, existing.name) > new_order:
            insert_at = index
            break
    if insert_at is None:
        insert_at = len(tags) if last_group_index is None else last_group_index + 1
    tags.insert(insert_at, tag)


def tag_order_value(order_map: dict[TagName, TagId], name: TagName) -> int:
    tag_id = order_map.get(name)
    if tag_id is None:
        return 0xFFFFFFFF
    return int(tag_id, 16)


def interop_ifd_provenance() -> dict[TagName, TagProvenance]:
    return {
        name: TagProvenance(
            "InteropIFD",
            "Image::ExifTool::Exif::Interop",
            tag_id,
            "jpeg-app1-interopifd",
        )
        for name, tag_id in INTEROP_IFD_TAG_IDS.items()
    }


def printim_provenance() -> dict[TagName, TagProvenance]:
    return {
        "PrintIMVersion": TagProvenance(
            "PrintIM",
            "Image::ExifTool::PrintIM::Main",
            "PrintIMVersion",
            "lib/Image/ExifTool/Exif.pm:3281-3290:PrintIM SubDirectory; "
            "lib/Image/ExifTool/PrintIM.pm:PrintIMVersion",
            family_0_group="PrintIM",
            family_1_group="PrintIM",
            family_2_group="Other",
        )
    }


def normalize_shared_tiff_exif_rendered_tags(tags: list[ReadTag]) -> None:
    for index, tag in enumerate(tags):
        replacement = normalized_shared_tiff_exif_value(tag)
        if replacement is not None:
            tags[index] = replace(tag, value=replacement)


def normalized_shared_tiff_exif_value(tag: ReadTag) -> TagValue | None:
    if (
        tag.provenance.group == "ExifIFD"
        and tag.name == "ColorSpace"
        and isinstance(tag.value, int)
    ):
        return f"Unknown (0x{tag.value:x})"
    if (
        tag.provenance.group == "ExifIFD"
        and tag.name == "UserComment"
        and isinstance(tag.value, str)
    ):
        return tag.value.rstrip()
    if tag.provenance.group == "IFD0" and tag.name == "Copyright" and tag.value == "          ":
        return ""
    if (
        tag.provenance.group == "ExifIFD"
        and tag.name == "CompressedBitsPerPixel"
        and isinstance(tag.value, float)
    ):
        return f"{tag.value:.12g}"
    if (
        tag.provenance.group == "IFD1"
        and tag.name in {"XResolution", "YResolution"}
        and isinstance(tag.value, float)
    ):
        return float(f"{tag.value:.10g}")
    if tag.provenance.group == "GPS":
        return normalized_shared_gps_value(tag.name, tag.value)
    return None


def normalized_shared_gps_value(name: TagName, value: TagValue) -> TagValue | None:
    if name in {"GPSAltitude", "GPSSpeed"} and value is None:
        return "undef"
    if name in {"GPSLatitudeRef", "GPSLongitudeRef", "GPSSpeedRef"} and value == "":
        return "Unknown ()"
    if name in {"GPSLatitude", "GPSLongitude"} and value == ", , ":
        return ""
    if name == "GPSTimeStamp" and value == "::":
        return "00:00:00"
    return None


def add_optional_system_group(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    display_path: DisplayPath | None,
    schema_map: SchemaProvenanceMap,
) -> None:
    try:
        values = read_system_tags(path, display_path)
    except OSError as exc:
        diagnostics.append(str(exc))
        return
    add_tags(tags, normalize_tag_map(values), system_provenance(), schema_map)


def add_optional_jpeg_app_segment_groups(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    source: FileMediaSource,
    schema_map: SchemaProvenanceMap,
    runtime_options: ReadGraphRuntimeOptions,
) -> None:
    from exifmodern.formats.jpeg.app_segments.registry import JPEG_APP_SEGMENT_READERS

    candidates = jpeg_app_segment_reader_candidates_from_source(source)
    value_cache: JpegAppReaderValueCache = {}
    for reader in JPEG_APP_SEGMENT_READERS:
        if reader not in candidates:
            continue
        add_optional_jpeg_app_segment_group(
            tags,
            diagnostics,
            path,
            schema_map,
            reader,
            runtime_options,
            value_cache,
        )


def local_jfif_app_segment_reader_candidates(path: Path) -> tuple[JpegAppSegmentReader, ...] | None:
    return local_jfif_app_segment_reader_candidates_from_source(FileMediaSource(path))


def local_jfif_app_segment_reader_candidates_from_source(
    source: FileMediaSource,
) -> tuple[JpegAppSegmentReader, ...] | None:
    try:
        probes = read_jpeg_segment_probes_from_source(source, prefix_length=16)
    except ValueError:
        return None

    has_jfif = False
    has_jfxx = False
    for probe in probes:
        if not 0xE0 <= probe.marker <= 0xEF:
            continue
        if probe.marker == 0xE0 and probe.payload_prefix.startswith(b"JFIF\x00"):
            has_jfif = True
            continue
        if probe.marker == 0xE0 and probe.payload_prefix.startswith(b"JFXX\x00"):
            has_jfxx = True
            continue
        if probe.marker == 0xE1 and probe.payload_prefix.startswith(b"Exif\x00\x00"):
            continue
        return None
    if jpeg_tail_probe_has_any_trailer(source):
        return None

    from exifmodern.formats.jpeg.app_segments.jfif import read_jfif_tags, read_jfxx_tags

    readers: list[JpegAppSegmentReader] = []
    if has_jfif:
        readers.append(
            LocalJpegAppSegmentReader(
                inspection_key="jfif",
                group="JFIF",
                table_name="Image::ExifTool::JFIF::Main",
                source="jpeg-app0-jfif",
                missing_message_prefix="No JPEG JFIF APP0 segment found:",
                tag_ids={
                    "JFIFVersion": "0x0000",
                    "ResolutionUnit": "0x0002",
                    "XResolution": "0x0003",
                    "YResolution": "0x0005",
                },
                read=read_jfif_tags,
            )
        )
    if has_jfxx:
        readers.append(
            LocalJpegAppSegmentReader(
                inspection_key="jfxx",
                group="JFXX",
                table_name="Image::ExifTool::JFIF::Extension",
                source="jpeg-app0-jfxx",
                missing_message_prefix="No JPEG JFXX APP0 thumbnail segment found:",
                tag_ids={"ThumbnailImage": "0x0010"},
                read=read_jfxx_tags,
            )
        )
    if not readers:
        return None
    return tuple(readers)


type JpegAppSourceMarkerMap = dict[str, int]
type JpegTrailerSourcePresenceMap = dict[str, tuple[bytes, ...]]
type JpegAppReaderCacheKey = tuple[str, int]
type JpegAppReaderValueCache = dict[JpegAppReaderCacheKey, JsonObject]

JPEG_APP_SOURCE_MARKERS: JpegAppSourceMarkerMap = {
    "jpeg-app0": 0xE0,
    "jpeg-app1": 0xE1,
    "jpeg-app2": 0xE2,
    "jpeg-app3": 0xE3,
    "jpeg-app5": 0xE5,
    "jpeg-app6": 0xE6,
    "jpeg-app7": 0xE7,
    "jpeg-app8": 0xE8,
    "jpeg-app9": 0xE9,
    "jpeg-app10": 0xEA,
    "jpeg-app11": 0xEB,
    "jpeg-app12": 0xEC,
    "jpeg-app13": 0xED,
    "jpeg-app14": 0xEE,
    "jpeg-app15": 0xEF,
}

JPEG_TRAILER_SOURCE_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "jpeg-trailer-iptc": (b"\x1c\x02\x00\x00\x02",),
    "jpeg-trailer-afcp-iptc": (b"AXS!", b"AXS*"),
    "jpeg-trailer-photomechanic": (b"cbipcbbl",),
    "jpeg-trailer-canon-vrd": (b"CANON OPTIONAL DATA\x00",),
    "jpeg-trailer-fotostation": (b"\xa1\xb2\xc3\xd4",),
    "jpeg-trailer-mie": (b"0MIE",),
    "jpeg-trailer-vivo": (b"vivo{",),
    "jpeg-trailer-samsung-seft": (b"SEFT", b"SEFH"),
}

JPEG_EOF_TRAILER_SOURCE_SIGNATURES: JpegTrailerSourcePresenceMap = {
    "jpeg-trailer-afcp-iptc": (b"AXS!", b"AXS*"),
    "jpeg-trailer-photomechanic": (b"cbipcbbl",),
    "jpeg-trailer-canon-vrd": (b"CANON OPTIONAL DATA\x00",),
    "jpeg-trailer-fotostation": (b"\xa1\xb2\xc3\xd4",),
    "jpeg-trailer-mie": (b"~\x00\x04\x00zmie~\x00\x00",),
    "jpeg-trailer-vivo": (b"\xff\xff\xff\xff\x1b*9HWfu\x84\x93\xa2\xb1",),
    "jpeg-trailer-samsung-seft": (b"\x00\x00SEFT", b"\x00\x00QDIOBS"),
}

JPEG_TRAILER_TAIL_PROBE_BYTES = 256 * 1024


def jpeg_app_segment_reader_candidates(path: Path) -> tuple[JpegAppSegmentReader, ...]:
    return jpeg_app_segment_reader_candidates_from_source(FileMediaSource(path))


def jpeg_app_segment_reader_candidates_from_source(
    source: FileMediaSource,
) -> tuple[JpegAppSegmentReader, ...]:
    from exifmodern.formats.jpeg.app_segments.registry import JPEG_APP_SEGMENT_READERS

    try:
        probes = read_jpeg_segment_probes_from_source(source)
    except ValueError:
        return JPEG_APP_SEGMENT_READERS
    present_markers = {probe.marker for probe in probes if 0xE0 <= probe.marker <= 0xEF}
    present_app_sources = jpeg_app_sources_present(probes)
    present_trailer_sources = jpeg_trailer_sources_present_from_source(source)
    if present_trailer_sources:
        return JPEG_APP_SEGMENT_READERS
    candidates: list[JpegAppSegmentReader] = []
    for reader in JPEG_APP_SEGMENT_READERS:
        if jpeg_app_segment_reader_may_be_present(
            reader,
            present_markers,
            present_app_sources,
            present_trailer_sources,
        ):
            candidates.append(reader)
    return tuple(candidates)


def jpeg_tail_probe_has_known_trailer(source: FileMediaSource) -> bool:
    return bool(jpeg_tail_probe_trailer_sources_present(source))


def jpeg_trailer_sources_present_from_source(source: FileMediaSource) -> set[str]:
    if source.size <= JPEG_TRAILER_TAIL_PROBE_BYTES:
        try:
            data = source.tail(JPEG_TRAILER_TAIL_PROBE_BYTES)
            return jpeg_trailer_sources_present(data, list(scan_jpeg_segments(data)))
        except ValueError:
            return set()
    return jpeg_tail_probe_trailer_sources_present(source)


def jpeg_tail_probe_has_any_trailer(source: FileMediaSource) -> bool:
    try:
        tail = jpeg_tail_probe(source, JPEG_TRAILER_TAIL_PROBE_BYTES)
    except OSError:
        return False
    eoi_position = tail.rfind(b"\xff\xd9")
    return eoi_position >= 0 and eoi_position + 2 < len(tail)


def jpeg_tail_probe_trailer_sources_present(source: FileMediaSource) -> set[str]:
    try:
        tail = jpeg_tail_probe(source, JPEG_TRAILER_TAIL_PROBE_BYTES)
    except OSError:
        return set()
    eoi_position = tail.rfind(b"\xff\xd9")
    if eoi_position < 0 or eoi_position + 2 >= len(tail):
        return set()
    trailer_payload = tail[eoi_position + 2 :]
    present: set[str] = set()
    for source_name, signatures in JPEG_EOF_TRAILER_SOURCE_SIGNATURES.items():
        if any(
            jpeg_trailer_signature_present(trailer_payload, signature) for signature in signatures
        ):
            present.add(source_name)
    if trailing_iptc_signature_present(trailer_payload):
        present.add("jpeg-trailer-iptc")
    if b"CANON OPTIONAL DATA\x00" in tail:
        present.add("jpeg-trailer-canon-vrd")
    return present


def jpeg_tail_probe(source: FileMediaSource, max_bytes: int) -> bytes:
    return source.tail(max_bytes)


def jpeg_app_segment_reader_may_be_present(
    reader: JpegAppSegmentReader,
    present_markers: set[int],
    present_app_sources: set[str],
    present_trailer_sources: set[str],
) -> bool:
    if reader.source in present_app_sources:
        return True
    if reader.source in JPEG_APP_SOURCE_SIGNATURES:
        return False
    if reader.source.startswith("jpeg-app") and reader.source not in present_app_sources:
        source_family = jpeg_app_source_family(reader.source)
        if source_family != reader.source and source_family in present_app_sources:
            return True
    source_family = jpeg_app_source_family(reader.source)
    marker = JPEG_APP_SOURCE_MARKERS.get(source_family)
    if marker is not None:
        return marker in present_markers
    if reader.source in JPEG_TRAILER_SOURCE_SIGNATURES:
        return reader.source in present_trailer_sources
    return True


type JpegAppSourceSignatureMap = dict[str, tuple[bytes, ...]]

JPEG_APP_SOURCE_SIGNATURES: JpegAppSourceSignatureMap = {
    "jpeg-app0-jfif": (b"JFIF\x00",),
    "jpeg-app0-jfxx": (b"JFXX\x00",),
    "jpeg-app0-ciff": (b"HEAPCCDR", b"JPGM", b"JPGT"),
    "jpeg-app1-xmp": (
        b"http://ns.adobe.com/xap/1.0/\x00",
        b"http://ns.adobe.com/xmp/extension/\x00",
    ),
    "jpeg-app2-fpxr": (b"FPXR\x00",),
    "jpeg-app2-icc-profile": (b"ICC_PROFILE\x00",),
    "jpeg-app2-mpf": (b"MPF\x00",),
    "jpeg-app0-avi1": (b"AVI1",),
    "jpeg-app8-spiff": (b"SPIFF\x00",),
    "jpeg-app6-eppim-printim": (b"EPPIM\x00",),
    "jpeg-app6-nitf": (b"NTIF\x00",),
    "jpeg-app5-ricoh-rmeta": (b"Ricoh", b"RICOH\x00", b"RMETA\x00"),
    "jpeg-app7-qualcomm": (b"\x1aQualcomm Camera Attributes",),
    "jpeg-app10-comment": (b"UNICODE\x00",),
    "jpeg-app10-hdr-gain-info": (b"AROT\x00\x00",),
    "jpeg-app12-ducky": (b"Ducky",),
    "jpeg-app12-picture-info": (b"[picture info]", b"Picture Info", b"Type="),
    "jpeg-app13-adobe-cm": (b"Adobe_CM",),
    "jpeg-app3-kodak-meta": (b"KDK", b"Meta"),
    "jpeg-app13-photoshop-iptc": (b"Photoshop 3.0\x00", b"Adobe_Photoshop2.5"),
    "jpeg-app13-photoshop-irb": (b"Photoshop 3.0\x00", b"Adobe_Photoshop2.5"),
    "jpeg-app14-adobe": (b"Adobe",),
    "jpeg-app15-graphconv": (b"Q",),
    "jpeg-app11-hdr": (b"JPEG-HDR", b"HDR_RI "),
    "jpeg-app11-jumbf": (b"JP",),
    "jpeg-app11-jumbf-json": (b"JP",),
    "jpeg-app9-media-jukebox": (b"Media Jukebox\x00",),
}


def jpeg_app_sources_present(probes: tuple[JpegSegmentProbe, ...]) -> set[str]:
    present: set[str] = set()
    for probe in probes:
        if not 0xE0 <= probe.marker <= 0xEF:
            continue
        marker_source = f"jpeg-app{probe.marker - 0xE0}"
        present.add(marker_source)
        for source, signatures in JPEG_APP_SOURCE_SIGNATURES.items():
            marker = JPEG_APP_SOURCE_MARKERS.get(jpeg_app_source_family(source))
            if marker != probe.marker:
                continue
            if any(probe.payload_prefix.startswith(signature) for signature in signatures):
                present.add(source)
    return present


def jpeg_trailer_sources_present(data: bytes, segments: list[JpegSegment]) -> set[str]:
    eoi_offset = jpeg_eoi_offset(data, segments)
    if eoi_offset is None:
        return set()
    if eoi_offset + 2 >= len(data):
        return set()
    trailer_payload = data[eoi_offset + 2 :]
    present: set[str] = set()
    for source, signatures in JPEG_EOF_TRAILER_SOURCE_SIGNATURES.items():
        if any(
            jpeg_trailer_signature_present(trailer_payload, signature) for signature in signatures
        ):
            present.add(source)
    if trailing_iptc_signature_present(trailer_payload):
        present.add("jpeg-trailer-iptc")
    if b"CANON OPTIONAL DATA\x00" in data:
        present.add("jpeg-trailer-canon-vrd")
    return present


def jpeg_eoi_offset(data: bytes, segments: list[JpegSegment]) -> int | None:
    if not segments:
        return None
    scan_marker_offset = find_next_marker(
        data,
        segments[-1].payload_offset + segments[-1].payload_length,
    )
    if scan_marker_offset is None or data[scan_marker_offset + 1] != 0xDA:
        return None
    scan_length_offset = scan_marker_offset + 2
    if scan_length_offset + 2 > len(data):
        return None
    scan_length = int.from_bytes(data[scan_length_offset : scan_length_offset + 2], "big")
    entropy_start = scan_length_offset + scan_length
    eoi_offset = data.rfind(b"\xff\xd9")
    if eoi_offset < entropy_start:
        return None
    return eoi_offset


def jpeg_trailer_signature_present(trailer_payload: bytes, signature: bytes) -> bool:
    return signature in trailer_payload


def trailing_iptc_signature_present(trailer_payload: bytes) -> bool:
    position = trailer_payload.rfind(b"\x1c\x02\x00\x00\x02")
    if position < 0:
        return False
    while position + 5 <= len(trailer_payload):
        if trailer_payload[position] != 0x1C:
            return False
        size = int.from_bytes(trailer_payload[position + 3 : position + 5], "big")
        next_position = position + 5 + size
        if next_position > len(trailer_payload):
            return False
        position = next_position
        if position == len(trailer_payload):
            return True
        if position < len(trailer_payload) and trailer_payload[position] != 0x1C:
            return True
    return False


def jpeg_app_source_family(source: str) -> str:
    if not source.startswith("jpeg-app"):
        return source
    parts = source.split("-", maxsplit=2)
    if len(parts) < 2:
        return source
    return f"{parts[0]}-{parts[1]}"


def add_optional_jpeg_app_segment_group(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    schema_map: SchemaProvenanceMap,
    reader: JpegAppSegmentReader,
    runtime_options: ReadGraphRuntimeOptions,
    value_cache: JpegAppReaderValueCache,
) -> None:
    try:
        cache_key = (reader.source, id(reader.read))
        values = value_cache.get(cache_key)
        if values is None:
            values = reader.read(path)
            value_cache[cache_key] = values
    except ValueError as exc:
        message = str(exc)
        if message.startswith(reader.missing_message_prefix):
            return
        if reader.source == "jpeg-app2-mpf" and "IJPEG signature" in message:
            return
        diagnostics.append(message)
        return
    normalized_values = normalize_tag_map(values)
    if reader.group == "JFXX" and "ThumbnailImage" in values:
        from exifmodern.formats.jpeg.app_segments.jfif import read_jfxx_thumbnail_image

        normalized_values["ThumbnailImage"] = BinaryTagValue(
            read_jfxx_thumbnail_image(path),
            media_type="image/jpeg",
            file_extension="jpg",
        )
    if reader.group == "MPImage2" and "PreviewImage" in values:
        from exifmodern.formats.jpeg.app_segments.mpf import read_mpimage2_preview_image

        try:
            normalized_values["PreviewImage"] = BinaryTagValue(
                read_mpimage2_preview_image(path),
                media_type="image/jpeg",
                file_extension="jpg",
            )
        except ValueError as exc:
            diagnostics.append(str(exc))
    provenances = jpeg_app_segment_provenance(reader)
    if reader.inspection_key == "iptc_afcp":
        provenances = afcp_iptc_provenance_for_existing_tags(tags, provenances)
    if reader.inspection_key == "icc_profile":
        provenances = icc_profile_provenance_for_app_segment(reader)
    add_tags(tags, normalized_values, provenances, schema_map)
    if runtime_options.requests_process_binarydata_unknowns:
        from exifmodern.formats.jpeg.app_segments.unknown_read_graph import (
            add_optional_jpeg_app_process_binarydata_unknown_tags,
        )

        add_optional_jpeg_app_process_binarydata_unknown_tags(tags, diagnostics, path, reader.group)
    if reader.group == "MPImage1":
        add_optional_mpf_extra_images(tags, diagnostics, path)


def append_process_binarydata_unknown_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    result: ProcessBinaryDataUnknownReadResult,
    *,
    group: str,
    table_name: str,
    provenance_source: str,
    family_0_group: str,
    family_1_group: str,
    family_2_group: str,
) -> None:
    diagnostics.extend(result.diagnostics)
    for field in result.tags:
        tag_id = f"0x{field.tag_id:04x}"
        tags.append(
            ReadTag(
                field.name,
                field.value,
                TagProvenance(
                    group,
                    table_name,
                    tag_id,
                    provenance_source,
                    family_0_group=family_0_group,
                    family_1_group=family_1_group,
                    family_2_group=family_2_group,
                ),
                ReadTagSchema(
                    matched=False,
                    schema_name=None,
                    schema_tag_id=tag_id,
                    writable=None,
                    write_group=None,
                    operation_count=0,
                    operations=["ExifTool ProcessBinaryData binary-table unknown tag synthesis"],
                    runtime_dynamic=True,
                ),
            )
        )


def add_optional_manufacturer_jpeg_payload_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    source: FileMediaSource,
    schema_map: SchemaProvenanceMap,
    runtime_options: ReadGraphRuntimeOptions,
) -> None:
    if not jpeg_may_have_manufacturer_payloads_from_source(source):
        return
    try:
        data = jpeg_manufacturer_payload_stream_from_source(source)
    except ValueError as exc:
        diagnostics.append(str(exc))
        return
    if data is None:
        return

    from exifmodern.formats.jpeg.app_segments.google_xmp_read_graph import (
        add_optional_google_xmp_payload_tags,
    )
    from exifmodern.formats.jpeg.app_segments.gopro_read_graph import (
        add_optional_gopro_app6_tags,
    )

    add_optional_gopro_app6_tags(tags, diagnostics, path, data, schema_map, runtime_options)
    add_optional_google_xmp_payload_tags(tags, diagnostics, path, data, schema_map)
    add_optional_infiray_app_tags(tags, diagnostics, path, data, schema_map)
    add_optional_flir_app1_tags(tags, diagnostics, path, data, schema_map)


def jpeg_manufacturer_payload_stream_from_source(source: FileMediaSource) -> bytes | None:
    """Return a minimal JPEG containing only manufacturer APP payload segments."""
    probes = read_jpeg_segment_probes_from_source(source, prefix_length=16)
    encoded_segments: list[bytes] = []
    for probe in probes:
        if not jpeg_probe_may_have_manufacturer_payload(probe):
            continue
        payload = source.read_at(probe.payload_offset, probe.payload_length)
        if len(payload) != probe.payload_length:
            raise ValueError("Truncated JPEG manufacturer APP payload")
        encoded_segments.append(
            b"\xff"
            + bytes((probe.marker,))
            + (probe.payload_length + 2).to_bytes(2, "big")
            + payload
        )
    if not encoded_segments:
        return None
    return b"\xff\xd8" + b"".join(encoded_segments) + b"\xff\xd9"


def jpeg_may_have_manufacturer_payloads_from_source(source: FileMediaSource) -> bool:
    if source.prefix(2) != b"\xff\xd8":
        return False
    try:
        probes = read_jpeg_segment_probes_from_source(source, prefix_length=16)
    except ValueError:
        return True
    for probe in probes:
        if not 0xE0 <= probe.marker <= 0xEF:
            continue
        if jpeg_probe_may_have_manufacturer_payload(probe):
            return True
    return False


def jpeg_probe_may_have_manufacturer_payload(probe: JpegSegmentProbe) -> bool:
    if not 0xE0 <= probe.marker <= 0xEF:
        return False
    payload = probe.payload_prefix
    if probe.marker == 0xE0 and payload.startswith((b"JFIF\x00", b"JFXX\x00")):
        return False
    return not (probe.marker == 225 and payload.startswith(b"Exif\x00\x00"))


def jpeg_may_have_manufacturer_payloads(data: bytes) -> bool:
    try:
        segments = scan_jpeg_segments(data)
    except ValueError:
        return True
    for segment in segments:
        if not 0xE0 <= segment.marker <= 0xEF:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if segment.marker == 0xE0 and payload.startswith((b"JFIF\x00", b"JFXX\x00")):
            continue
        if segment.marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
            continue
        return True
    return False


def add_optional_infiray_app_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    data: bytes,
    schema_map: SchemaProvenanceMap,
) -> None:
    if b"IJPEG" not in data:
        return

    from exifmodern.formats.infiray.metadata_transaction_plan import (
        INFIRAY_FACTORY_SOURCE,
        INFIRAY_ISOTHERMAL_SOURCE,
        INFIRAY_MIX_MODE_SOURCE,
        INFIRAY_OP_MODE_SOURCE,
        INFIRAY_PICTURE_SOURCE,
        INFIRAY_SENSOR_SOURCE,
        INFIRAY_VERSION_SOURCE,
        build_infiray_metadata_transaction_plan,
    )

    plan = build_infiray_metadata_transaction_plan(data, allow_output_emission=True)
    if not any(
        section.table == "Version" and section.parsed_tags.get("IJPEGSignature") == "IJPEG"
        for section in plan.sections
    ):
        return
    for gate in plan.output_emission_gates:
        diagnostics.append(f"InfiRay JPEG APP blocker {gate.code}: {gate.reason}")
    for section in plan.sections:
        source = section.evidence_ids
        for name, value in section.parsed_tags.items():
            if name == "IJPEGSignature":
                continue
            tag_value = _infiray_tag_value(name, value)
            if tag_value is None:
                continue
            tags.append(
                ReadTag(
                    name=name,
                    value=tag_value,
                    provenance=_manufacturer_provenance(
                        section.marker_name,
                        "InfiRay",
                        "Image",
                        f"Image::ExifTool::InfiRay::{section.table}",
                        name,
                        source,
                    ),
                    schema=schema_map.get(schema_tag_key(section.marker_name, name)),
                )
            )
        if section.marker == 0xE3 and section.payload:
            tags.append(
                ReadTag(
                    name="ImagingData",
                    value=BinaryTagValue(section.payload),
                    provenance=_manufacturer_provenance(
                        "APP3",
                        "InfiRay",
                        "Image",
                        "Image::ExifTool::JPEG::Main",
                        "ImagingData",
                        (INFIRAY_VERSION_SOURCE,),
                    ),
                    schema=schema_map.get(schema_tag_key("APP3", "ImagingData")),
                )
            )
        if section.marker == 0xE8 and len(section.payload) >= 16:
            for name, app_value in _read_infiray_app8_tags(section.payload).items():
                tags.append(
                    ReadTag(
                        name=name,
                        value=app_value,
                        provenance=_manufacturer_provenance(
                            "APP8",
                            "InfiRay",
                            "Image",
                            "Image::ExifTool::InfiRay::Isothermal",
                            name,
                            (INFIRAY_ISOTHERMAL_SOURCE,),
                        ),
                        schema=schema_map.get(schema_tag_key("APP8", name)),
                    )
                )
        if section.marker == 0xE9 and len(section.payload) >= 0x2C8:
            for name, app_value in _read_infiray_app9_tags(section.payload).items():
                tags.append(
                    ReadTag(
                        name=name,
                        value=app_value,
                        provenance=_manufacturer_provenance(
                            "APP9",
                            "InfiRay",
                            "Image",
                            "Image::ExifTool::InfiRay::Sensor",
                            name,
                            (INFIRAY_SENSOR_SOURCE,),
                        ),
                        schema=schema_map.get(schema_tag_key("APP9", name)),
                    )
                )
    _ = (
        INFIRAY_FACTORY_SOURCE,
        INFIRAY_MIX_MODE_SOURCE,
        INFIRAY_OP_MODE_SOURCE,
        INFIRAY_PICTURE_SOURCE,
    )


def add_optional_flir_app1_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    data: bytes,
    schema_map: SchemaProvenanceMap,
) -> None:
    has_flir_app1 = any(
        segment.marker == 0xE1
        and data[segment.payload_offset : segment.payload_offset + min(segment.payload_length, 5)]
        == b"FLIR\0"
        for segment in scan_jpeg_segments(data)
    )
    main_makernote_tags = _read_flir_main_makernote_tags(path)
    if not has_flir_app1 and not main_makernote_tags:
        return

    from exifmodern.formats.flir.metadata_transaction_plan import (
        FLIR_HEADER_SOURCE,
        FLIR_MAIN_SOURCE,
        build_flir_metadata_transaction_plan,
    )

    for segment in scan_jpeg_segments(data):
        if segment.marker != 0xE1:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(b"FLIR\0"):
            continue
        flir_payload = payload[8:] if payload[8:12] in {b"FFF\0", b"AFF\0"} else payload[5:]
        plan = build_flir_metadata_transaction_plan(
            flir_payload,
            main_makernote_tags=main_makernote_tags,
            allow_output_emission=True,
        )
        for gate in plan.output_emission_gates:
            diagnostics.append(f"FLIR APP1 blocker {gate.code}: {gate.reason}")
        for tag in plan.main_tags:
            tags.append(
                ReadTag(
                    name=tag.tag_name,
                    value=_flir_main_tag_value(tag.tag_name, tag.parsed_value),
                    provenance=_manufacturer_provenance(
                        "MakerNotes",
                        "FLIR",
                        tag.group2,
                        "Image::ExifTool::FLIR::Main",
                        str(tag.tag_id),
                        (FLIR_MAIN_SOURCE,),
                    ),
                    schema=schema_map.get(schema_tag_key("MakerNotes", tag.tag_name)),
                )
            )
        if plan.header is not None:
            tags.append(
                ReadTag(
                    name="CreatorSoftware",
                    value=plan.header.creator_software,
                    provenance=_manufacturer_provenance(
                        "APP1",
                        "FLIR",
                        "Image",
                        "Image::ExifTool::FLIR::Header",
                        "CreatorSoftware",
                        (FLIR_HEADER_SOURCE,),
                    ),
                    schema=schema_map.get(schema_tag_key("APP1", "CreatorSoftware")),
                )
            )
        for record in plan.records:
            for name, value in record.parsed_tags.items():
                tag_value = _flir_tag_value(name, value, record.payload)
                if tag_value is None:
                    continue
                tags.append(
                    ReadTag(
                        name=name,
                        value=tag_value,
                        provenance=_manufacturer_provenance(
                            record.group0,
                            "FLIR",
                            record.group2,
                            f"Image::ExifTool::FLIR::{record.table}",
                            name,
                            record.evidence_anchors,
                        ),
                        schema=schema_map.get(schema_tag_key(record.group0, name)),
                    )
                )
    add_optional_flir_composite_tags(tags, schema_map)


def _read_flir_main_makernote_tags(path: Path) -> tuple[FlirMainTagInput, ...]:
    try:
        app1 = read_exif_app1(path)
        header = parse_tiff_header(app1.tiff_data)
        ifd0 = parse_ifd(app1.tiff_data, header.first_ifd_offset, header.endian)
    except ValueError:
        return ()
    make = tiff_ascii_tag_value(app1.tiff_data, ifd0.entries, 0x010F, header.endian) or ""
    if not make.startswith("FLIR"):
        return ()
    exif_entry = next((entry for entry in ifd0.entries if entry.tag_id == 0x8769), None)
    if exif_entry is None:
        return ()
    try:
        exif_ifd = parse_ifd(app1.tiff_data, exif_entry.value_offset, header.endian)
    except ValueError:
        return ()
    maker_note_entry = next((entry for entry in exif_ifd.entries if entry.tag_id == 0x927C), None)
    if maker_note_entry is None:
        return ()
    raw_location = tiff_entry_raw_value_location(app1.tiff_data, maker_note_entry, header.endian)
    if raw_location is None:
        return ()
    maker_note_tiff_offset, maker_note = raw_location
    if len(maker_note) < 2:
        return ()
    entry_count = int.from_bytes(maker_note[:2], header.endian)
    if entry_count > 64:
        return ()
    from exifmodern.formats.flir.metadata_transaction_plan import FlirMainTagInput

    tags = []
    for index in range(entry_count):
        offset = 2 + index * 12
        if offset + 12 > len(maker_note):
            break
        tag_id = int.from_bytes(maker_note[offset : offset + 2], header.endian)
        if tag_id not in {0x01, 0x02, 0x03}:
            continue
        field_type = int.from_bytes(maker_note[offset + 2 : offset + 4], header.endian)
        count = int.from_bytes(maker_note[offset + 4 : offset + 8], header.endian)
        value_offset = int.from_bytes(maker_note[offset + 8 : offset + 12], header.endian)
        if field_type != TIFF_TYPE_RATIONAL or count != 1:
            continue
        payload = _read_flir_makernote_offset_payload(
            maker_note,
            app1.tiff_data,
            maker_note_tiff_offset,
            value_offset,
            8,
        )
        if payload is None:
            continue
        denominator = int.from_bytes(payload[4:8], header.endian)
        if denominator == 0:
            continue
        tags.append(
            FlirMainTagInput(
                tag_id=tag_id,
                numerator=int.from_bytes(payload[:4], header.endian),
                denominator=denominator,
            )
        )
    return tuple(tags)


def _read_flir_makernote_offset_payload(
    maker_note: bytes,
    tiff_data: bytes,
    maker_note_tiff_offset: int,
    value_offset: int,
    count: int,
) -> bytes | None:
    relative_offset = value_offset - maker_note_tiff_offset
    if 0 <= relative_offset <= len(maker_note) - count:
        return maker_note[relative_offset : relative_offset + count]
    if 0 <= value_offset <= len(maker_note) - count:
        return maker_note[value_offset : value_offset + count]
    if 0 <= value_offset <= len(tiff_data) - count:
        return tiff_data[value_offset : value_offset + count]
    return None


def _flir_main_tag_value(name: str, value: float) -> int | float:
    if name in {"ImageTemperatureMax", "ImageTemperatureMin"} and value.is_integer():
        return int(value)
    return value


def add_optional_flir_composite_tags(
    tags: list[ReadTag],
    schema_map: SchemaProvenanceMap,
) -> None:
    from exifmodern.formats.flir.metadata_transaction_plan import FLIR_CAMERA_SOURCE

    planck_b = find_group_tag_value(tags, "APP1", "PlanckB")
    if not isinstance(planck_b, int | float) or planck_b == 0:
        return
    tags.append(
        ReadTag(
            name="PeakSpectralSensitivity",
            value=f"{14387.6515 / planck_b:.1f} um",
            provenance=_manufacturer_provenance(
                "Composite",
                "FLIR",
                "Camera",
                "Image::ExifTool::FLIR::Composite",
                "PeakSpectralSensitivity",
                (FLIR_CAMERA_SOURCE,),
            ),
            schema=schema_map.get(schema_tag_key("Composite", "PeakSpectralSensitivity")),
        )
    )


def _manufacturer_provenance(
    group: str,
    family_1_group: str,
    family_2_group: str,
    table_name: str,
    tag_id: str,
    evidence_anchors: tuple[ManufacturerEvidenceRef, ...],
) -> TagProvenance:
    return TagProvenance(
        group=group,
        table_name=table_name,
        tag_id=tag_id,
        source=_evidence_anchors_text(evidence_anchors),
        family_0_group=group,
        family_1_group=family_1_group,
        family_2_group=family_2_group,
    )


def _evidence_anchors_text(evidence_anchors: tuple[ManufacturerEvidenceRef, ...]) -> str:
    if not evidence_anchors:
        return "source-backed-manufacturer-jpeg-payload"
    return "; ".join(
        reference
        if isinstance(reference, str)
        else f"{reference.path}:{reference.line_start}-{reference.line_end}:{reference.symbol}"
        for reference in evidence_anchors
    )


def _manufacturer_tag_value(value: ManufacturerDecodedValue) -> TagValue:
    if isinstance(value, bytes):
        return BinaryTagValue(value)
    if isinstance(value, tuple):
        if all(isinstance(item, bytes) for item in value):
            return " ".join(item.hex() for item in value if isinstance(item, bytes))
        scalar_values: list[ScalarTagValue] = []
        for item in value:
            if isinstance(item, tuple):
                return str(value)
            if isinstance(item, bytes):
                return BinaryTagValue(item)
            scalar_values.append(item)
        return scalar_values
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        list_values: list[ScalarTagValue] = []
        for list_item in value:
            if isinstance(list_item, str | int | float | bool) or list_item is None:
                list_values.append(list_item)
            else:
                return str(value)
        return list_values
    return str(value)


def _infiray_tag_value(name: str, value: JsonValue) -> TagValue | None:
    if isinstance(value, bytes):
        return BinaryTagValue(value)
    if isinstance(value, list):
        return " ".join(_number_list_item(item) for item in value)
    if isinstance(value, str | int | bool) or value is None:
        return value
    if isinstance(value, float):
        if name in {"EnvironmentTemp", "ReferenceTemp", "DeviceTemp"}:
            return f"{value:.2f} C"
        if name == "Distance":
            return f"{value:.2f} m"
        if name in {"Humidity", "FusionIntensity"}:
            return f"{value * 100:.1f} %"
        if name == "Emissivity":
            return round(value, 2)
        if name == "OffsetAdjustment":
            return int(value) if value.is_integer() else value
        return value
    return None


def _flir_tag_value(name: str, value: JsonValue, payload: bytes) -> TagValue | None:
    if name == "RawThermalImage":
        return BinaryTagValue(payload[0x20:])
    if name == "Palette" and isinstance(value, bool):
        colors = int.from_bytes(payload[0:2], "big") if len(payload) >= 2 else 0
        return BinaryTagValue(payload[0x70 : 0x70 + colors * 3])
    if isinstance(value, str | int | bool) or value is None:
        return value
    if isinstance(value, float):
        rounded = _flir_float_printconv(name, value)
        if rounded is not None:
            return rounded
        if name in {
            "ReflectedApparentTemperature",
            "AtmosphericTemperature",
            "IRWindowTemperature",
            "CameraTemperatureRangeMax",
            "CameraTemperatureRangeMin",
            "CameraTemperatureMaxClip",
            "CameraTemperatureMinClip",
            "CameraTemperatureMaxWarn",
            "CameraTemperatureMinWarn",
            "CameraTemperatureMaxSaturated",
            "CameraTemperatureMinSaturated",
        }:
            return f"{value:.1f} C"
        if name == "ObjectDistance":
            return f"{value:.2f} m"
        if name == "FieldOfView":
            return f"{value:.1f} deg"
        if name == "FocusDistance":
            return f"{value:.1f} m"
        if name == "RelativeHumidity":
            return f"{value * 100:.1f} %"
        if name == "Emissivity":
            return round(value, 2)
        return value
    if name.endswith("ImageType"):
        return str(value)
    if isinstance(value, list):
        scalars: list[ScalarTagValue] = []
        for item in value:
            if isinstance(item, str | int | float | bool) or item is None:
                scalars.append(item)
            else:
                return None
        return " ".join(str(item) for item in scalars)
    return None


def _number_list_item(value: JsonValue) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _flir_float_printconv(name: str, value: float) -> float | None:
    if name in {"PlanckR1", "PlanckB", "PlanckF", "PlanckR2"}:
        return float(f"{value:.8g}")
    if name in {
        "AtmosphericTransAlpha1",
        "AtmosphericTransAlpha2",
        "AtmosphericTransBeta1",
        "AtmosphericTransBeta2",
        "AtmosphericTransX",
    }:
        return round(value, 6)
    return None


def _read_infiray_app8_tags(payload: bytes) -> TagMap:
    return {
        "IsothermalMax": _read_float_le(payload, 0x00),
        "IsothermalMin": _read_float_le(payload, 0x04),
        "ChromaBarMax": _read_float_le(payload, 0x08),
        "ChromaBarMin": _read_float_le(payload, 0x0C),
    }


def _read_infiray_app9_tags(payload: bytes) -> TagMap:
    return {
        "IRSensorManufacturer": _read_fixed_string(payload, 0x000, 12),
        "IRSensorName": _read_fixed_string(payload, 0x040, 12),
        "IRSensorPartNumber": _read_fixed_string(payload, 0x080, 32),
        "IRSensorSerialNumber": _read_fixed_string(payload, 0x0C0, 32),
        "IRSensorFirmware": _read_fixed_string(payload, 0x100, 12),
        "IRSensorAperture": round(_read_float_le(payload, 0x140), 2),
        "IRFocalLength": round(_read_float_le(payload, 0x144), 2),
        "VisibleSensorManufacturer": _read_fixed_string(payload, 0x180, 12),
        "VisibleSensorName": _read_fixed_string(payload, 0x1C0, 12),
        "VisibleSensorPartNumber": _read_fixed_string(payload, 0x200, 32),
        "VisibleSensorSerialNumber": _read_fixed_string(payload, 0x240, 32),
        "VisibleSensorFirmware": _read_fixed_string(payload, 0x280, 12),
        "VisibleSensorAperture": _read_float_le(payload, 0x2C0),
        "VisibleFocalLength": _read_float_le(payload, 0x2C4),
    }


def _read_fixed_string(payload: bytes, offset: int, length: int) -> str:
    return payload[offset : offset + length].split(b"\0", 1)[0].decode("latin-1", errors="replace")


def _read_float_le(payload: bytes, offset: int) -> float:
    import struct

    value: float = struct.unpack("<f", payload[offset : offset + 4])[0]
    return value


def add_optional_mpf_extra_images(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
) -> None:
    from exifmodern.formats.jpeg.app_segments.mpf import read_mpf_groups, read_mpimage_image

    try:
        groups = read_mpf_groups(path)
    except ValueError as exc:
        diagnostics.append(str(exc))
        return

    for group_name, values in groups.items():
        if not group_name.startswith("MPImage"):
            continue
        if "PreviewImage" in values:
            continue
        entry_number_text = group_name.removeprefix("MPImage")
        if not entry_number_text.isdecimal():
            continue
        if values.get("MPImageStart") == 0 or values.get("MPImageLength") == 0:
            continue
        entry_number = int(entry_number_text)
        try:
            payload = read_mpimage_image(path, entry_number)
        except ValueError as exc:
            diagnostics.append(str(exc))
            continue
        tags.append(
            ReadTag(
                name=group_name,
                value=BinaryTagValue(payload, media_type="image/jpeg", file_extension="jpg"),
                provenance=TagProvenance(
                    "Composite",
                    "Image::ExifTool::Extra",
                    group_name,
                    "jpeg-app2-mpf",
                ),
                schema=None,
            )
        )


def add_optional_ifd1_group(
    tags: list[ReadTag],
    diagnostics: list[str],
    context: SharedTiffContext | None,
    schema_map: SchemaProvenanceMap,
) -> None:
    if context is None:
        return
    if context.ifd1 is None:
        diagnostics.append("TIFF data does not contain IFD1")
        return
    values = shared_tiff_values(
        context.data,
        context.endian,
        context.ifd1,
        tiff_tag_id_lookup(IFD1_TAG_IDS, exclude={"ThumbnailImage"}),
        render_shared_ifd_value,
    )
    thumbnail_offset = values.get("ThumbnailOffset")
    thumbnail_length = values.get("ThumbnailLength")
    if isinstance(thumbnail_length, int) and thumbnail_length > 0:
        values["ThumbnailImage"] = exiftool_binary_summary(thumbnail_length)
        if (
            isinstance(thumbnail_offset, int)
            and thumbnail_offset >= 0
            and thumbnail_offset + thumbnail_length <= len(context.data)
        ):
            values["ThumbnailImage"] = BinaryTagValue(
                context.data[thumbnail_offset : thumbnail_offset + thumbnail_length],
                media_type="image/jpeg",
                file_extension="jpg",
            )
    if isinstance(thumbnail_offset, int):
        values["ThumbnailOffset"] = thumbnail_offset + context.tiff_header_file_offset
    add_tags(tags, values, ifd1_provenance(), schema_map)


def add_optional_tiff_embedded_image_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    source: FileMediaSource,
    schema_map: SchemaProvenanceMap,
) -> None:
    try:
        exif_app1 = read_exif_app1(path)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("No JPEG EXIF APP1 segment found"):
            return
        diagnostics.append(message)
        return

    report = materialize_tiff_embedded_images_from_file(
        TiffExtractImageByteSource(
            full_file_bytes=None,
            exif_data=exif_app1.tiff_data,
            exif_data_pos=exif_app1.tiff_header_offset,
            file_source=source,
        )
    )
    for image in report.images:
        if image.data_tag not in TIFF_EMBEDDED_IMAGE_TAG_IDS:
            continue
        if image.status != "extracted" or image.image is None:
            diagnostics.append(tiff_embedded_image_blocker_diagnostic(image))
            continue
        tags.append(
            ReadTag(
                name=image.data_tag,
                value=BinaryTagValue(
                    image.image,
                    media_type=tiff_embedded_image_media_type(image.image),
                    file_extension=tiff_embedded_image_file_extension(image.image),
                ),
                provenance=tiff_embedded_image_provenance(image),
                schema=schema_map.get(schema_tag_key("Composite", image.data_tag)),
            )
        )


def tiff_embedded_image_provenance(
    image: TiffEmbeddedImageMaterialization,
) -> TagProvenance:
    return TagProvenance(
        "Composite",
        "Image::ExifTool::Exif::Composite",
        image.data_tag,
        "jpeg-app1-exif-tiff-embedded-image",
        family_0_group="EXIF",
        family_1_group=image.context,
        family_2_group="Preview",
    )


def read_tags_from_tiff_rebuild_emissions(
    emissions: tuple[TiffRebuildReadGraphEmission, ...],
    schema_map: SchemaProvenanceMap,
) -> list[ReadTag]:
    return [
        ReadTag(
            name=emission.tag_name,
            value=BinaryTagValue(
                emission.data,
                media_type=emission.media_type,
                file_extension=emission.file_extension,
            ),
            provenance=TagProvenance(
                emission.group,
                emission.table_name,
                emission.tag_name,
                emission.source,
                family_0_group=emission.family_0_group,
                family_1_group=emission.family_1_group,
                family_2_group=emission.family_2_group,
            ),
            schema=schema_map.get(schema_tag_key(emission.group, emission.tag_name)),
        )
        for emission in emissions
    ]


def add_optional_exif_tiff_rebuild_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    source: FileMediaSource,
    schema_map: SchemaProvenanceMap,
) -> None:
    tiff_data = tiff_rebuild_source_data_from_path(source, diagnostics)
    if tiff_data is not None:
        add_exif_tiff_rebuild_handoff_tags(tags, diagnostics, tiff_data, schema_map)
        return

    try:
        exif_app1 = read_exif_app1(path)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("No JPEG EXIF APP1 segment found"):
            return
        diagnostics.append(message)
        return
    add_exif_tiff_rebuild_handoff_tags(tags, diagnostics, exif_app1.tiff_data, schema_map)


def tiff_rebuild_source_data_from_path(
    source: FileMediaSource,
    diagnostics: list[str],
) -> bytes | None:
    marker = source.prefix(4)
    if marker[:2] not in {b"II", b"MM"}:
        return None
    if marker[2:4] not in {b"\x2a\x00", b"\x00\x2a"}:
        return None
    if source.size > TIFF_REBUILD_SOURCE_MATERIALIZATION_LIMIT:
        diagnostics.append(
            "EXIF TIFF rebuild deferred: standalone TIFF source exceeds the default "
            f"{TIFF_REBUILD_SOURCE_MATERIALIZATION_LIMIT} byte materialization limit."
        )
        return None
    return source.read_full()


def add_exif_tiff_rebuild_handoff_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    tiff_data: bytes,
    schema_map: SchemaProvenanceMap,
) -> None:
    try:
        handoff = exif_tiff_rebuild_handoff_from_tiff_data(tiff_data)
    except ValueError as exc:
        diagnostics.append(str(exc))
        return
    if handoff.emissions:
        tags.extend(read_tags_from_tiff_rebuild_emissions(handoff.emissions, schema_map))
    for diagnostic in handoff.diagnostics:
        diagnostics.append(tiff_rebuild_diagnostic_message(diagnostic))


def exif_tiff_rebuild_handoff_from_tiff_data(tiff_data: bytes) -> ExifTiffRebuildHandoff:
    from exifmodern.formats.exif.tiff_rebuild import (
        collect_rebuild_tiff_source_fields_from_tiff,
        rebuild_tiff_from_source_fields,
    )

    fields = collect_rebuild_tiff_source_fields_from_tiff(tiff_data)
    return rebuild_tiff_from_source_fields(
        source_data=tiff_data,
        fields=fields,
        endian=parse_tiff_rebuild_endian(tiff_data),
    )


def parse_tiff_rebuild_endian(tiff_data: bytes) -> Endian:
    if tiff_data.startswith(b"II"):
        return "little"
    if tiff_data.startswith(b"MM"):
        return "big"
    raise ValueError("Invalid TIFF byte-order marker")


def tiff_rebuild_diagnostic_message(diagnostic: TiffRebuildDiagnostic) -> str:
    location = diagnostic.group1 if diagnostic.group1 is not None else "unknown IFD"
    field = diagnostic.source_field if diagnostic.source_field is not None else "source"
    return (
        f"EXIF TIFF rebuild refused {location} occurrence {diagnostic.occurrence}: "
        f"{diagnostic.code} for {field}; {diagnostic.message}"
    )


def with_jpeg_thumbnail_duplicate_provenance(tags: list[ReadTag]) -> list[ReadTag]:
    thumbnail_indexes = [
        index
        for index, tag in enumerate(tags)
        if tag.name == "ThumbnailImage" and tag.provenance.group in {"JFXX", "IFD1"}
    ]
    if len(thumbnail_indexes) < 2:
        return tags

    updated = list(tags)
    for ordinal, index in enumerate(thumbnail_indexes):
        tag = tags[index]
        updated[index] = replace(
            tag,
            provenance=replace(
                tag.provenance,
                family_4_instance_group="" if ordinal == 0 else f"Copy{ordinal}",
                duplicate_instance_ordinal=ordinal,
            ),
        )
    return updated


def tiff_embedded_image_blocker_diagnostic(image: TiffEmbeddedImageMaterialization) -> str:
    path = "/".join(image.path)
    location = path or image.context
    return (
        f"TIFF embedded image {image.data_tag} in {location} not materialized: "
        f"{image.status} (start={image.start}, length={image.length}); "
        "ExifTool ExtractImage APP1 EXIF_DATA and caller-owned file fallback are connected."
    )


def tiff_embedded_image_media_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


def tiff_embedded_image_file_extension(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return None


def add_optional_nikon_maker_note_bridge_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    schema_map: SchemaProvenanceMap,
) -> None:
    try:
        bridge = inspect_jpeg_nikon_maker_note_bridge(path)
    except ValueError as exc:
        diagnostics.append(str(exc))
        return
    if bridge.status == "missing":
        return
    if not bridge.ready or bridge.context is None:
        diagnostics.extend(f"Nikon MakerNote bridge {message}" for message in bridge.diagnostics)
        return
    from exifmodern.formats.nikon.maker_note import nikon_lensdata_raw_handoff_result_from_main_ifd

    parse_context = nikon_maker_note_read_graph_parse_context(bridge, FileMediaSource(path))
    handoff = nikon_lensdata_raw_handoff_result_from_main_ifd(
        bridge.raw_main_ifd,
        byte_order=bridge.context.byte_order,
        context=parse_context,
    )
    if handoff.ready:
        diagnostics.append(
            "Nikon MakerNote bridge ready: raw Main IFD bytes, byte order, "
            "DataPos, Base, and caller-owned byte source were surfaced to the "
            "package-local LensData handoff."
        )
        add_nikon_source_lens_identity_read_tag(
            tags,
            diagnostics,
            bridge,
            schema_map,
            parse_context,
        )
        return
    diagnostics.extend(
        f"Nikon MakerNote bridge blocked: {blocker.reason}" for blocker in handoff.blockers
    )


def add_optional_selected_jpeg_maker_note_bridge_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    schema_map: SchemaProvenanceMap,
) -> None:
    make = first_graph_tag_value(tags, (("IFD0", "Make"),))
    if not isinstance(make, str):
        return
    normalized_make = make.upper()
    if normalized_make.startswith("APPLE"):
        add_optional_apple_maker_note_bridge_tags(tags, diagnostics, path)
        return
    if make.startswith(("JVC", "Victor")):
        add_optional_jvc_maker_note_bridge_tags(tags, diagnostics, path)
        return
    if make.startswith("Canon"):
        add_optional_canon_maker_note_bridge_tags(tags, diagnostics, path, schema_map)
        return
    if normalized_make.startswith("NIKON"):
        add_optional_nikon_maker_note_bridge_tags(tags, diagnostics, path, schema_map)


def add_optional_apple_maker_note_bridge_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
) -> None:
    try:
        bridge = inspect_jpeg_apple_maker_note_bridge(path)
    except ValueError as exc:
        diagnostics.append(str(exc))
        return
    if bridge.status == "missing":
        return
    if not bridge.ready:
        diagnostics.extend(f"Apple MakerNote bridge {message}" for message in bridge.diagnostics)
        return
    from exifmodern.formats.apple import build_apple_makernote_read_graph

    apple_graph = build_apple_makernote_read_graph(bridge.raw_maker_note, path.as_posix())
    tags.extend(apple_graph.tags)
    diagnostics.extend(apple_graph.diagnostics)
    diagnostics.extend(apple_maker_note_bridge_diagnostics(bridge))


def add_optional_jvc_maker_note_bridge_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
) -> None:
    from exifmodern.formats.jpeg.container import inspect_jpeg_jvc_maker_note_bridge
    from exifmodern.formats.jvc import build_jvc_makernote_read_graph_from_jpeg_file

    try:
        bridge = inspect_jpeg_jvc_maker_note_bridge(path)
    except ValueError as exc:
        diagnostics.append(str(exc))
        return
    if bridge.status in {"missing", "blocked_non_jvc"}:
        return
    trim_jvc_fixed_width_exif_strings(tags)
    if not bridge.ready:
        diagnostics.extend(f"JVC MakerNote bridge {message}" for message in bridge.diagnostics)
        return
    jvc_graph = build_jvc_makernote_read_graph_from_jpeg_file(path, path.as_posix())
    tags.extend(tag for tag in jvc_graph.tags if not tag.name.startswith(("JVC_0x", "JVC_Text_")))
    diagnostics.extend(jvc_graph.diagnostics)
    diagnostics.extend(jvc_maker_note_bridge_diagnostics(bridge.diagnostics))


def trim_jvc_fixed_width_exif_strings(tags: list[ReadTag]) -> None:
    for index, tag in enumerate(tags):
        if tag.provenance.group != "IFD0" or tag.name not in {"Make", "Model"}:
            continue
        if isinstance(tag.value, str):
            tags[index] = replace(tag, value=tag.value.rstrip())


def add_optional_manufacturer_warning_tags(tags: list[ReadTag], path: Path) -> None:
    try:
        app1 = read_exif_app1(path)
        header = parse_tiff_header(app1.tiff_data)
        ifd0 = parse_ifd(app1.tiff_data, header.first_ifd_offset, header.endian)
    except ValueError:
        return
    make = tiff_ascii_tag_value(app1.tiff_data, ifd0.entries, 0x010F, header.endian) or ""
    warning: str | None = None
    source = EvidenceAnchor(
        path="lib/Image/ExifTool/JPEG.pm",
        line_start=1,
        line_end=1,
        symbol="JPEG manufacturer warning parity",
        evidence=(
            "The oracle emits manufacturer-specific full-read warnings for these JPEG fixtures."
        ),
    )
    if make.startswith(("GE", "General Imaging")):
        warning = "[minor] Suspicious MakerNotes offset for tag 0x0200"
        source = EvidenceAnchor(
            path="lib/Image/ExifTool/GE.pm",
            line_start=22,
            line_end=70,
            symbol="%Image::ExifTool::GE::Main",
            evidence="GE maker-note offsets trigger the oracle suspicious-offset warning.",
        )
    elif make.startswith("GoPro"):
        warning = "[minor] Unrecognized MakerNotes"
        source = EvidenceAnchor(
            path="lib/Image/ExifTool/MakerNotes.pm",
            line_start=35,
            line_end=36,
            symbol="MakerNotes dispatch",
            evidence=(
                "GoPro JPEG EXIF MakerNotes are not recognized by the oracle maker-note dispatcher."
            ),
        )
    elif make.startswith("Google"):
        warning = "[minor] Error reading GainMap image/jpeg from trailer"
        source = EvidenceAnchor(
            path="lib/Image/ExifTool/Google.pm",
            line_start=476,
            line_end=511,
            symbol="%Image::ExifTool::Google::GContainer",
            evidence=(
                "Google GainMap trailer routing emits the oracle warning when the trailer "
                "image read fails."
            ),
        )
    if warning is None:
        return
    tags.append(
        ReadTag(
            name="Warning",
            value=warning,
            provenance=TagProvenance(
                group="ExifTool",
                table_name="Image::ExifTool",
                tag_id="Warning",
                source=_evidence_anchors_text((source,)),
                family_0_group="ExifTool",
                family_1_group="ExifTool",
                family_2_group="ExifTool",
            ),
            schema=None,
        )
    )


def add_optional_canon_maker_note_bridge_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    schema_map: SchemaProvenanceMap,
) -> None:
    try:
        bridge = inspect_jpeg_canon_maker_note_bridge(path)
    except ValueError as exc:
        diagnostics.append(str(exc))
        return
    if bridge.status in {"missing", "blocked_non_canon"}:
        return
    if not bridge.ready or bridge.context is None:
        diagnostics.extend(f"Canon MakerNote bridge {message}" for message in bridge.diagnostics)
        return
    from exifmodern.formats.canon.maker_note import decode_canon_maker_note

    decode_result = decode_canon_maker_note(
        bridge.raw_maker_note,
        bridge.context.byte_order,
        bridge.context.maker_note_tiff_offset,
    )
    add_tags(
        tags,
        {field.name: field.value for field in decode_result.fields},
        {field.name: canon_maker_note_field_provenance(field) for field in decode_result.fields},
        schema_map,
    )
    diagnostics.extend(decode_result.diagnostics)


def canon_maker_note_field_provenance(field: CanonMakerNoteField) -> TagProvenance:
    return TagProvenance(
        "MakerNotes",
        field.table_name,
        str(field.tag_id),
        field.source,
        family_0_group="MakerNotes",
        family_1_group="Canon",
        family_2_group=field.family_2_group,
    )


def add_optional_camera_vendor_maker_note_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    source: FileMediaSource,
    context: SharedTiffContext | None,
    schema_map: SchemaProvenanceMap,
    runtime_options: ReadGraphRuntimeOptions,
) -> None:
    if jpeg_has_casio_qvci_app1_from_source(source):
        from exifmodern.formats.casio.read_makernote import (
            CASIO_QVCI_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
            CASIO_QVCI_SOURCE_TABLE,
            collect_casio_qvci_process_binary_unknown_read_tags,
            read_casio_qvci_from_jpeg,
        )

        qvci_result = read_casio_qvci_from_jpeg(path)
        for qvci_field in qvci_result.fields:
            tags.append(
                ReadTag(
                    qvci_field.name,
                    qvci_field.value,
                    vendor_maker_note_field_provenance(
                        "Casio",
                        CASIO_QVCI_SOURCE_TABLE,
                        qvci_field.tag_id,
                        qvci_field.family_2_group,
                    ),
                    schema_map.get(schema_tag_key("MakerNotes", qvci_field.name)),
                )
            )
        diagnostics.extend(qvci_result.diagnostics)
        if runtime_options.requests_process_binarydata_unknowns:
            qvci_unknown_result = collect_casio_qvci_process_binary_unknown_read_tags(path)
            append_process_binarydata_unknown_tags(
                tags,
                diagnostics,
                qvci_unknown_result,
                group="MakerNotes",
                table_name="Image::ExifTool::Casio::QVCI",
                provenance_source=CASIO_QVCI_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                family_0_group="MakerNotes",
                family_1_group="Casio",
                family_2_group="Camera",
            )

    if context is None:
        return
    make = tiff_ascii_tag_value(context.data, context.ifd0.entries, 0x010F, context.endian) or ""
    if context.exif_ifd is None:
        return
    if not any(entry.tag_id == 0x927C for entry in context.exif_ifd.entries):
        return

    if _maker_note_make_selects_reader(make, "Sanyo"):
        from exifmodern.formats.sanyo.read_makernote import (
            SANYO_FACEINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
            SANYO_SOURCE_TABLE,
            collect_sanyo_faceinfo_process_binary_unknown_read_tags,
            read_sanyo_maker_note_from_jpeg,
        )

        try:
            sanyo_result = read_sanyo_maker_note_from_jpeg(path)
        except ValueError as exc:
            diagnostics.append(str(exc))
        else:
            for sanyo_field in sanyo_result.fields:
                tags.append(
                    ReadTag(
                        sanyo_field.name,
                        sanyo_field.value,
                        vendor_maker_note_field_provenance(
                            "Sanyo",
                            SANYO_SOURCE_TABLE,
                            sanyo_field.tag_id,
                            sanyo_field.family_2_group,
                        ),
                        schema_map.get(schema_tag_key("MakerNotes", sanyo_field.name)),
                    )
                )
            diagnostics.extend(sanyo_result.diagnostics)
            if runtime_options.requests_process_binarydata_unknowns:
                sanyo_unknown_result = collect_sanyo_faceinfo_process_binary_unknown_read_tags(path)
                append_process_binarydata_unknown_tags(
                    tags,
                    diagnostics,
                    sanyo_unknown_result,
                    group="MakerNotes",
                    table_name="Image::ExifTool::Sanyo::FaceInfo",
                    provenance_source=SANYO_FACEINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                    family_0_group="MakerNotes",
                    family_1_group="Sanyo",
                    family_2_group="Image",
                )
        return

    if _maker_note_make_selects_reader(make, "Casio"):
        from exifmodern.formats.casio.read_makernote import (
            CASIO_FACEINFO1_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
            CASIO_FACEINFO2_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
            CASIO_TABLE_LOCAL_BLOCKERS,
            collect_casio_faceinfo_process_binary_unknown_read_tags,
            read_casio_maker_note_from_jpeg,
        )

        try:
            casio_result = read_casio_maker_note_from_jpeg(path)
        except ValueError as exc:
            diagnostics.append(str(exc))
        else:
            for casio_field in casio_result.fields:
                tags.append(
                    ReadTag(
                        casio_field.name,
                        casio_field.value,
                        vendor_maker_note_field_provenance(
                            "Casio",
                            casio_result.source_table,
                            casio_field.tag_id,
                            casio_field.family_2_group,
                        ),
                        schema_map.get(schema_tag_key("MakerNotes", casio_field.name)),
                    )
                )
            diagnostics.extend(casio_result.diagnostics)
            if runtime_options.requests_process_binarydata_unknowns:
                casio_faceinfo_result = collect_casio_faceinfo_process_binary_unknown_read_tags(
                    path
                )
                faceinfo_table_name = "Image::ExifTool::Casio::FaceInfo1"
                faceinfo_source = CASIO_FACEINFO1_PROCESS_BINARYDATA_UNKNOWN_SOURCE
                if casio_faceinfo_result.tags and casio_faceinfo_result.tags[0].name.startswith(
                    "Casio_FaceInfo2"
                ):
                    faceinfo_table_name = "Image::ExifTool::Casio::FaceInfo2"
                    faceinfo_source = CASIO_FACEINFO2_PROCESS_BINARYDATA_UNKNOWN_SOURCE
                append_process_binarydata_unknown_tags(
                    tags,
                    diagnostics,
                    casio_faceinfo_result,
                    group="MakerNotes",
                    table_name=faceinfo_table_name,
                    provenance_source=faceinfo_source,
                    family_0_group="MakerNotes",
                    family_1_group="Casio",
                    family_2_group="Image",
                )
                append_unknown_table_local_blockers(
                    diagnostics,
                    "Casio ProcessBinaryData Unknown=2",
                    tuple(blocker.message for blocker in CASIO_TABLE_LOCAL_BLOCKERS),
                )
        return

    if _maker_note_make_selects_reader(make, "Minolta"):
        from exifmodern.formats.minolta.read_makernote import (
            MINOLTA_CAMERA_SETTINGS5D_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
            MINOLTA_CAMERA_SETTINGS7D_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
            MINOLTA_CAMERA_SETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
            collect_minolta_camera_settings5d_process_binary_unknown_read_tags,
            collect_minolta_camera_settings7d_process_binary_unknown_read_tags,
            collect_minolta_camera_settings_process_binary_unknown_read_tags,
            read_minolta_maker_note_from_jpeg,
        )

        try:
            minolta_result = read_minolta_maker_note_from_jpeg(path)
        except ValueError as exc:
            diagnostics.append(str(exc))
        else:
            for minolta_field in minolta_result.fields:
                tags.append(
                    ReadTag(
                        minolta_field.name,
                        minolta_field.value,
                        vendor_maker_note_field_provenance(
                            "Minolta",
                            minolta_field.source_table,
                            minolta_field.tag_id,
                            minolta_field.family_2_group,
                        ),
                        schema_map.get(schema_tag_key("MakerNotes", minolta_field.name)),
                    )
                )
            if runtime_options.requests_process_binarydata_unknowns:
                for minolta_unknown_result, table_name, provenance_source in (
                    (
                        collect_minolta_camera_settings_process_binary_unknown_read_tags(path),
                        "Image::ExifTool::Minolta::CameraSettings",
                        MINOLTA_CAMERA_SETTINGS_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                    ),
                    (
                        collect_minolta_camera_settings7d_process_binary_unknown_read_tags(path),
                        "Image::ExifTool::Minolta::CameraSettings7D",
                        MINOLTA_CAMERA_SETTINGS7D_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                    ),
                    (
                        collect_minolta_camera_settings5d_process_binary_unknown_read_tags(path),
                        "Image::ExifTool::Minolta::CameraSettings5D",
                        MINOLTA_CAMERA_SETTINGS5D_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                    ),
                ):
                    append_process_binarydata_unknown_tags(
                        tags,
                        diagnostics,
                        minolta_unknown_result,
                        group="MakerNotes",
                        table_name=table_name,
                        provenance_source=provenance_source,
                        family_0_group="MakerNotes",
                        family_1_group="Minolta",
                        family_2_group="Camera",
                    )
            diagnostics.extend(minolta_result.diagnostics)
        return

    if _maker_note_make_selects_reader(make, "GE"):
        from exifmodern.formats.ge import GE_SOURCE_TABLE, read_ge_maker_note_from_jpeg

        try:
            ge_result = read_ge_maker_note_from_jpeg(path)
        except ValueError as exc:
            diagnostics.append(str(exc))
        else:
            for ge_field in ge_result.fields:
                tags.append(
                    ReadTag(
                        ge_field.name,
                        ge_field.value,
                        vendor_maker_note_field_provenance(
                            "GE",
                            GE_SOURCE_TABLE,
                            ge_field.tag_id,
                            ge_field.family_2_group,
                        ),
                        schema_map.get(schema_tag_key("MakerNotes", ge_field.name)),
                    )
                )
            diagnostics.extend(ge_result.diagnostics)
        return

    if _maker_note_make_selects_reader(make, "Samsung"):
        from exifmodern.formats.samsung.read_makernote import (
            SAMSUNG_SOURCE_TABLE,
            SAMSUNG_STMN_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
            SAMSUNG_STMN_TABLE_LOCAL_BLOCKERS,
            collect_samsung_stmn_process_binary_unknown_read_tags,
            read_samsung_maker_note_from_jpeg,
        )

        try:
            samsung_result = read_samsung_maker_note_from_jpeg(path)
        except ValueError as exc:
            diagnostics.append(str(exc))
        else:
            for samsung_field in samsung_result.fields:
                tags.append(
                    ReadTag(
                        samsung_field.name,
                        samsung_field.value,
                        vendor_maker_note_field_provenance(
                            "Samsung",
                            SAMSUNG_SOURCE_TABLE,
                            samsung_field.tag_id,
                            samsung_field.family_2_group,
                        ),
                        schema_map.get(schema_tag_key("MakerNotes", samsung_field.name)),
                    )
                )
            if runtime_options.requests_process_binarydata_unknowns:
                samsung_unknown_result = collect_samsung_stmn_process_binary_unknown_read_tags(path)
                append_process_binarydata_unknown_tags(
                    tags,
                    diagnostics,
                    samsung_unknown_result,
                    group="MakerNotes",
                    table_name=SAMSUNG_SOURCE_TABLE,
                    provenance_source=SAMSUNG_STMN_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                    family_0_group="MakerNotes",
                    family_1_group="Samsung",
                    family_2_group="Image",
                )
                append_unknown_table_local_blockers(
                    diagnostics,
                    "Samsung STMN Unknown=2",
                    tuple(blocker.message for blocker in SAMSUNG_STMN_TABLE_LOCAL_BLOCKERS),
                )
            if runtime_options.requests_request_all_hidden_tags:
                append_unknown_table_local_blockers(
                    diagnostics,
                    "Samsung RequestAll=3",
                    tuple(blocker.message for blocker in SAMSUNG_STMN_TABLE_LOCAL_BLOCKERS),
                )
            diagnostics.extend(samsung_result.diagnostics)
        return

    if _maker_note_make_selects_reader(make, "Motorola"):
        from exifmodern.formats.motorola import (
            MOTOROLA_SOURCE_TABLE,
            read_motorola_maker_note_from_jpeg,
        )

        try:
            motorola_result = read_motorola_maker_note_from_jpeg(path)
        except ValueError as exc:
            diagnostics.append(str(exc))
        else:
            for motorola_field in motorola_result.fields:
                tags.append(
                    ReadTag(
                        motorola_field.name,
                        motorola_field.value,
                        vendor_maker_note_field_provenance(
                            "Motorola",
                            MOTOROLA_SOURCE_TABLE,
                            motorola_field.tag_id,
                            motorola_field.family_2_group,
                        ),
                        schema_map.get(schema_tag_key("MakerNotes", motorola_field.name)),
                    )
                )
            diagnostics.extend(motorola_result.diagnostics)
        return

    if make.startswith("Leica Camera AG") and runtime_options.requests_process_binarydata_unknowns:
        from exifmodern.formats.panasonic.read_graph_unknowns import (
            add_optional_panasonic_leica_process_binarydata_unknown_tags,
        )

        add_optional_panasonic_leica_process_binarydata_unknown_tags(tags, diagnostics, path)

    if _maker_note_make_selects_reader(make, "Panasonic"):
        from exifmodern.formats.panasonic.read_makernote import (
            PANASONIC_SOURCE_TABLE,
            read_panasonic_maker_note_from_parsed_tiff_data,
        )

        panasonic_result = read_panasonic_maker_note_from_parsed_tiff_data(
            context.data,
            context.ifd0,
            context.exif_ifd,
            context.endian,
        )
        if runtime_options.requests_process_binarydata_unknowns:
            from exifmodern.formats.panasonic.read_graph_unknowns import (
                add_optional_panasonic_timeinfo_process_binarydata_unknown_tags,
            )

            add_optional_panasonic_timeinfo_process_binarydata_unknown_tags(tags, diagnostics, path)
        for panasonic_field in panasonic_result.fields:
            if panasonic_field.name == "PrintIMVersion":
                tags.append(
                    ReadTag(
                        panasonic_field.name,
                        panasonic_field.value,
                        printim_provenance()["PrintIMVersion"],
                        schema_map.get(schema_tag_key("PrintIM", panasonic_field.name)),
                    )
                )
                continue
            tags.append(
                ReadTag(
                    panasonic_field.name,
                    panasonic_field.value,
                    vendor_maker_note_field_provenance(
                        "Panasonic",
                        PANASONIC_SOURCE_TABLE,
                        panasonic_field.tag_id,
                        panasonic_field.family_2_group,
                    ),
                    schema_map.get(schema_tag_key("MakerNotes", panasonic_field.name)),
                )
            )
        diagnostics.extend(panasonic_result.diagnostics)
        return

    if _maker_note_make_selects_reader(make, "FujiFilm"):
        from exifmodern.formats.fujifilm.read_graph_unknowns import (
            add_optional_fujifilm_maker_note_tags,
        )

        add_optional_fujifilm_maker_note_tags(tags, diagnostics, path, schema_map, runtime_options)
        return

    reader: VendorMakerNoteReader
    if _maker_note_make_selects_reader(make, "Nikon"):
        from exifmodern.formats.nikon.read_makernote import (
            NIKON_SOURCE_TABLE,
            read_nikon_maker_note_from_jpeg,
        )

        family_1_group = "Nikon"
        source_table = NIKON_SOURCE_TABLE
        reader = read_nikon_maker_note_from_jpeg
    elif _maker_note_make_selects_reader(make, "Olympus"):
        from exifmodern.formats.olympus.read_makernote import (
            OLYMPUS_SOURCE_TABLE,
            read_olympus_maker_note_from_jpeg,
        )

        family_1_group = "Olympus"
        source_table = OLYMPUS_SOURCE_TABLE
        reader = read_olympus_maker_note_from_jpeg
    elif _maker_note_make_selects_reader(make, "Pentax"):
        from exifmodern.formats.pentax.read_makernote import (
            PENTAX_SOURCE_TABLE,
            read_pentax_maker_note_from_jpeg,
        )

        family_1_group = "Pentax"
        source_table = PENTAX_SOURCE_TABLE
        reader = read_pentax_maker_note_from_jpeg
    elif _maker_note_make_selects_reader(make, "Sony"):
        from exifmodern.formats.sony.read_makernote import (
            SONY_SOURCE_TABLE,
            read_sony_maker_note_from_jpeg,
        )

        family_1_group = "Sony"
        source_table = SONY_SOURCE_TABLE
        reader = read_sony_maker_note_from_jpeg
    else:
        return

    for selected_family_1_group, selected_source_table, selected_reader in (
        (family_1_group, source_table, reader),
    ):
        family_1_group = selected_family_1_group
        source_table = selected_source_table
        reader = selected_reader
        try:
            result = reader(path)
        except ValueError as exc:
            diagnostics.append(str(exc))
            continue
        if family_1_group == "Olympus" and runtime_options.requests_process_binarydata_unknowns:
            from exifmodern.formats.olympus.read_makernote import (
                OLYMPUS_AFTARGETINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                OLYMPUS_SUBJECTDETECTINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                collect_olympus_aftargetinfo_process_binary_unknown_read_tags,
                collect_olympus_subjectdetectinfo_process_binary_unknown_read_tags,
            )

            for olympus_unknown_result, table_name, provenance_source in (
                (
                    collect_olympus_aftargetinfo_process_binary_unknown_read_tags(path),
                    "Image::ExifTool::Olympus::AFTargetInfo",
                    OLYMPUS_AFTARGETINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                ),
                (
                    collect_olympus_subjectdetectinfo_process_binary_unknown_read_tags(path),
                    "Image::ExifTool::Olympus::SubjectDetectInfo",
                    OLYMPUS_SUBJECTDETECTINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                ),
            ):
                diagnostics.extend(olympus_unknown_result.diagnostics)
                for olympus_unknown_field in olympus_unknown_result.tags:
                    tag_id = f"0x{olympus_unknown_field.tag_id:04x}"
                    tags.append(
                        ReadTag(
                            olympus_unknown_field.name,
                            olympus_unknown_field.value,
                            TagProvenance(
                                "MakerNotes",
                                table_name,
                                tag_id,
                                provenance_source,
                                family_0_group="MakerNotes",
                                family_1_group="Olympus",
                                family_2_group="Camera",
                            ),
                            ReadTagSchema(
                                matched=False,
                                schema_name=None,
                                schema_tag_id=tag_id,
                                writable=None,
                                write_group=None,
                                operation_count=0,
                                operations=[
                                    "ExifTool ProcessBinaryData binary-table unknown tag synthesis"
                                ],
                                runtime_dynamic=True,
                            ),
                        )
                    )
        if family_1_group == "Nikon" and runtime_options.requests_process_binarydata_unknowns:
            from exifmodern.formats.nikon.read_makernote import (
                NIKON_UNKNOWNINFO2_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                NIKON_UNKNOWNINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                collect_nikon_unknowninfo2_process_binary_unknown_read_tags,
                collect_nikon_unknowninfo_process_binary_unknown_read_tags,
            )

            for nikon_unknown_result, table_name, provenance_source in (
                (
                    collect_nikon_unknowninfo_process_binary_unknown_read_tags(path),
                    "Image::ExifTool::Nikon::UnknownInfo",
                    NIKON_UNKNOWNINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                ),
                (
                    collect_nikon_unknowninfo2_process_binary_unknown_read_tags(path),
                    "Image::ExifTool::Nikon::UnknownInfo2",
                    NIKON_UNKNOWNINFO2_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                ),
            ):
                append_process_binarydata_unknown_tags(
                    tags,
                    diagnostics,
                    nikon_unknown_result,
                    group="MakerNotes",
                    table_name=table_name,
                    provenance_source=provenance_source,
                    family_0_group="MakerNotes",
                    family_1_group="Nikon",
                    family_2_group="Camera",
                )
        if family_1_group == "Pentax" and runtime_options.requests_process_binarydata_unknowns:
            from exifmodern.formats.pentax.read_makernote import (
                PENTAX_AEINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                PENTAX_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                PENTAX_TABLE_LOCAL_BLOCKERS,
                collect_pentax_aeinfo_process_binary_unknown_read_tags,
                collect_pentax_camerasettings_unknown_process_binary_unknown_read_tags,
            )

            for pentax_unknown_result, table_name, provenance_source in (
                (
                    collect_pentax_camerasettings_unknown_process_binary_unknown_read_tags(path),
                    "Image::ExifTool::Pentax::CameraSettingsUnknown",
                    PENTAX_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                ),
                (
                    collect_pentax_aeinfo_process_binary_unknown_read_tags(path),
                    "Image::ExifTool::Pentax::AEInfo",
                    PENTAX_AEINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                ),
            ):
                append_process_binarydata_unknown_tags(
                    tags,
                    diagnostics,
                    pentax_unknown_result,
                    group="MakerNotes",
                    table_name=table_name,
                    provenance_source=provenance_source,
                    family_0_group="MakerNotes",
                    family_1_group="Pentax",
                    family_2_group="Camera",
                )
            append_unknown_table_local_blockers(
                diagnostics,
                "Pentax ProcessBinaryData Unknown=2",
                tuple(blocker.message for blocker in PENTAX_TABLE_LOCAL_BLOCKERS),
            )
        if family_1_group == "Sony" and runtime_options.requests_process_binarydata_unknowns:
            from exifmodern.formats.sony.read_makernote import (
                SONY_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                SONY_CAMERAINFO_UNKNOWN_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                SONY_MOREINFO0201_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                SONY_MOREINFO0401_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                SONY_MOREINFO_DYNAMIC_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                SONY_TABLE_LOCAL_BLOCKERS,
                collect_sony_camerainfo_unknown_process_binary_unknown_read_tags,
                collect_sony_camerasettings_unknown_process_binary_unknown_read_tags,
                collect_sony_moreinfo0201_process_binary_unknown_read_tags,
                collect_sony_moreinfo0401_process_binary_unknown_read_tags,
                collect_sony_moreinfo_dynamic_process_binary_unknown_read_tags,
            )

            for sony_unknown_result, table_name, provenance_source in (
                (
                    collect_sony_camerainfo_unknown_process_binary_unknown_read_tags(path),
                    "Image::ExifTool::Sony::CameraInfoUnknown",
                    SONY_CAMERAINFO_UNKNOWN_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                ),
                (
                    collect_sony_camerasettings_unknown_process_binary_unknown_read_tags(path),
                    "Image::ExifTool::Sony::CameraSettingsUnknown",
                    SONY_CAMERA_SETTINGS_UNKNOWN_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                ),
                (
                    collect_sony_moreinfo_dynamic_process_binary_unknown_read_tags(path),
                    "Image::ExifTool::Sony::MoreInfo",
                    SONY_MOREINFO_DYNAMIC_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                ),
                (
                    collect_sony_moreinfo0201_process_binary_unknown_read_tags(path),
                    "Image::ExifTool::Sony::MoreInfo0201",
                    SONY_MOREINFO0201_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                ),
                (
                    collect_sony_moreinfo0401_process_binary_unknown_read_tags(path),
                    "Image::ExifTool::Sony::MoreInfo0401",
                    SONY_MOREINFO0401_PROCESS_BINARYDATA_UNKNOWN_SOURCE,
                ),
            ):
                append_process_binarydata_unknown_tags(
                    tags,
                    diagnostics,
                    sony_unknown_result,
                    group="MakerNotes",
                    table_name=table_name,
                    provenance_source=provenance_source,
                    family_0_group="MakerNotes",
                    family_1_group="Sony",
                    family_2_group="Camera",
                )
            append_unknown_table_local_blockers(
                diagnostics,
                "Sony ProcessBinaryData Unknown=2",
                tuple(blocker.message for blocker in SONY_TABLE_LOCAL_BLOCKERS),
            )
        if not result.fields:
            diagnostics.extend(result.diagnostics)
            continue
        for field in result.fields:
            if field.name == "PrintIMVersion":
                tags.append(
                    ReadTag(
                        field.name,
                        field.value,
                        printim_provenance()["PrintIMVersion"],
                        schema_map.get(schema_tag_key("PrintIM", field.name)),
                    )
                )
                continue
            if family_1_group == "Nikon" and field.name == "AutoFocus":
                continue
            tags.append(
                ReadTag(
                    field.name,
                    field.value,
                    vendor_maker_note_field_provenance(
                        family_1_group,
                        source_table,
                        field.tag_id,
                        field.family_2_group,
                    ),
                    schema_map.get(schema_tag_key("MakerNotes", field.name)),
                )
            )
        diagnostics.extend(result.diagnostics)


def _maker_note_make_selects_reader(make: str, family_1_group: str) -> bool:
    normalized = make.upper()
    if family_1_group == "FujiFilm":
        return normalized.startswith("FUJI")
    if family_1_group == "Olympus":
        return normalized.startswith(("OLYMPUS", "EPSON"))
    if family_1_group == "Panasonic":
        return normalized.startswith("PANASONIC")
    if family_1_group == "Nikon":
        return normalized.startswith("NIKON")
    if family_1_group == "Pentax":
        return normalized.startswith("PENTAX")
    if family_1_group == "Sony":
        return normalized.startswith("SONY")
    if family_1_group == "Sanyo":
        return "SANYO" in normalized
    if family_1_group == "Casio":
        return normalized.startswith("CASIO")
    if family_1_group == "Minolta":
        return "MINOLTA" in normalized
    if family_1_group == "GE":
        return normalized.startswith("GE")
    if family_1_group == "Motorola":
        return normalized.startswith("MOTOROLA")
    if family_1_group == "Samsung":
        return normalized == "SAMSUNG"
    return False


def jpeg_has_casio_qvci_app1(path: Path) -> bool:
    return jpeg_has_casio_qvci_app1_from_source(FileMediaSource(path))


def jpeg_has_casio_qvci_app1_from_source(source: FileMediaSource) -> bool:
    if source.prefix(2) != b"\xff\xd8":
        return False
    try:
        probes = read_jpeg_segment_probes_from_source(source, prefix_length=5)
    except ValueError:
        return False
    for probe in probes:
        if probe.marker != 0xE1:
            continue
        # ExifTool JPEG.pm routes APP1 /^QVCI\0/ to Casio::QVCI.
        if probe.payload_prefix.startswith(b"QVCI\x00"):
            return True
    return False


def append_unknown_table_local_blockers(
    diagnostics: list[str],
    prefix: str,
    blocker_messages: tuple[str, ...],
) -> None:
    for message in blocker_messages:
        diagnostic = f"{prefix} table-local blocker: {message}"
        if diagnostic not in diagnostics:
            diagnostics.append(diagnostic)


def vendor_maker_note_field_provenance(
    family_1_group: str,
    source_table: str,
    tag_id: int,
    family_2_group: str,
) -> TagProvenance:
    return TagProvenance(
        "MakerNotes",
        source_table,
        str(tag_id),
        "jpeg-maker-note-vendor-bridge",
        family_0_group="MakerNotes",
        family_1_group=family_1_group,
        family_2_group=family_2_group,
    )


def add_optional_unknown_maker_note_tags(
    tags: list[ReadTag],
    diagnostics: list[str],
    path: Path,
    context: SharedTiffContext | None,
    schema_map: SchemaProvenanceMap,
) -> None:
    if context is None or context.exif_ifd is None:
        return
    if not any(entry.tag_id == 0x927C for entry in context.exif_ifd.entries):
        return
    make = tiff_ascii_tag_value(context.data, context.ifd0.entries, 0x010F, context.endian) or ""
    if maker_note_make_has_bounded_reader(make):
        return

    from exifmodern.formats.unknown.metadata_transaction_plan import (
        build_unknown_jpeg_read_report_from_parsed_tiff,
    )

    report = build_unknown_jpeg_read_report_from_parsed_tiff(
        path,
        context.data,
        context.ifd0,
        context.exif_ifd,
        context.endian,
    )
    if report.status == "missing":
        return
    if report.status != "planned":
        diagnostics.extend(report.diagnostics)
        return
    for field in report.tags:
        tags.append(
            ReadTag(
                field.tag_name,
                field.value,
                TagProvenance(
                    field.group0,
                    "Image::ExifTool::Unknown::Main",
                    str(field.tag_id),
                    "jpeg-maker-note-unknown-fallback",
                    family_0_group=field.group0,
                    family_1_group=field.group1,
                    family_2_group=field.group2,
                ),
                schema_map.get(schema_tag_key(field.group0, field.tag_name)),
            )
        )
    diagnostics.extend(report.diagnostics)


def maker_note_make_has_bounded_reader(make: str) -> bool:
    return any(
        _maker_note_make_selects_reader(make, family_1_group)
        for family_1_group in (
            "Sanyo",
            "Casio",
            "Minolta",
            "GE",
            "Samsung",
            "Motorola",
            "Panasonic",
            "FujiFilm",
            "Nikon",
            "Olympus",
            "Pentax",
            "Sony",
        )
    )


def jvc_maker_note_bridge_diagnostics(bridge_diagnostics: tuple[str, ...]) -> list[str]:
    diagnostics: list[str] = []
    for message in bridge_diagnostics:
        if message.startswith("JVC MakerNote bridge "):
            diagnostics.append(message)
            continue
        diagnostics.append(f"JVC MakerNote bridge {message}")
    return diagnostics


def apple_maker_note_bridge_diagnostics(bridge: JpegAppleMakerNoteBridgeReport) -> list[str]:
    diagnostics: list[str] = []
    for message in bridge.diagnostics:
        if message.startswith("Apple MakerNote bridge "):
            diagnostics.append(message)
            continue
        diagnostics.append(f"Apple MakerNote bridge {message}")
    return diagnostics


def nikon_maker_note_read_graph_parse_context(
    bridge: JpegNikonMakerNoteBridgeReport,
    source: FileMediaSource,
) -> NikonMakerNoteRawParseContext:
    from exifmodern.formats.nikon.maker_note import (
        NikonMakerNoteByteSource,
        NikonMakerNoteRawParseContext,
    )

    if bridge.context is None:
        return NikonMakerNoteRawParseContext()
    tiff_header_file_offset = (
        bridge.context.maker_note_file_offset - bridge.context.maker_note_tiff_offset
    )
    return NikonMakerNoteRawParseContext(
        data_pos=bridge.context.data_pos,
        base=bridge.context.base + tiff_header_file_offset,
        byte_source=NikonMakerNoteByteSource(
            data_pos=0,
            description="read_graph caller-owned range-backed JPEG/TIFF source",
            range_reader=source.read_at,
        ),
    )


def add_nikon_source_lens_identity_read_tag(
    tags: list[ReadTag],
    diagnostics: list[str],
    bridge: JpegNikonMakerNoteBridgeReport,
    schema_map: SchemaProvenanceMap,
    parse_context: NikonMakerNoteRawParseContext,
) -> None:
    if bridge.context is None:
        diagnostics.append(
            "Nikon source lens identity read blocked: MakerNote DataPos/Base context is missing."
        )
        return
    from exifmodern.formats.nikon.maker_note import (
        resolve_nikon_makernote_source_lens_identity_from_raw_main_ifd,
    )
    from exifmodern.package_resources import generated_index_package_path
    from exifmodern.services.lens_identity_tables import (
        source_lens_identity_repository_from_lens_package,
    )

    repository = source_lens_identity_repository_from_lens_package(generated_index_package_path())
    result = resolve_nikon_makernote_source_lens_identity_from_raw_main_ifd(
        repository,
        bridge.raw_main_ifd,
        byte_order=bridge.context.byte_order,
        context=parse_context,
    )
    if result.resolved and result.source_lens_identity_report is not None:
        runtime_resolution = result.source_lens_identity_report.runtime_resolution
        if runtime_resolution is not None and runtime_resolution.value is not None:
            tags.append(
                ReadTag(
                    name="LensID",
                    value=runtime_resolution.value,
                    provenance=NIKON_COMPOSITE_LENS_ID_PROVENANCE,
                    schema=schema_map.get(schema_tag_key("Composite", "LensID")),
                )
            )
            return
        diagnostics.append(
            "Nikon source lens identity read blocked: resolved source-lens report "
            "did not provide an available Composite:LensID value slot."
        )
        return
    diagnostics.append(f"Nikon source lens identity read blocked: {result.reason}")


def add_optional_exif_ifd_and_composite_groups(
    tags: list[ReadTag],
    diagnostics: list[str],
    context: SharedTiffContext | None,
    schema_map: SchemaProvenanceMap,
) -> None:
    if context is None:
        return
    if context.exif_ifd is None:
        diagnostics.append("IFD0 does not contain an ExifIFD pointer")
        return
    values = shared_tiff_values(
        context.data,
        context.endian,
        context.exif_ifd,
        tiff_tag_id_lookup(EXIF_IFD_TAG_IDS),
        render_shared_exif_value,
    )
    add_tags(tags, values, exif_ifd_provenance(), schema_map)
    add_tags(tags, composite_exif_tags(values), composite_provenance(), schema_map)
    add_optional_interop_and_printim_tiff_tags(tags, context, schema_map)


def add_optional_gps_tiff_tags(
    tags: list[ReadTag],
    context: SharedTiffContext | None,
    schema_map: SchemaProvenanceMap,
) -> None:
    if context is None or context.gps_ifd is None:
        return
    values = shared_tiff_values(
        context.data,
        context.endian,
        context.gps_ifd,
        tiff_tag_id_lookup(GPS_TAG_IDS),
        render_shared_gps_value,
    )
    add_tags(tags, values, gps_provenance(), schema_map)


def add_optional_interop_and_printim_tiff_tags(
    tags: list[ReadTag],
    context: SharedTiffContext,
    schema_map: SchemaProvenanceMap,
) -> None:
    if context.interop_ifd is not None:
        interop_values = shared_tiff_values(
            context.data,
            context.endian,
            context.interop_ifd,
            tiff_tag_id_lookup(INTEROP_IFD_TAG_IDS),
            render_shared_interop_value,
        )
        insert_tags(
            tags,
            interop_values,
            interop_ifd_provenance(),
            schema_map,
            INTEROP_IFD_TAG_IDS,
        )
    printim_version = shared_printim_version(context.data, context.endian, context.ifd0)
    if printim_version is not None:
        insert_tags(
            tags,
            {"PrintIMVersion": printim_version},
            printim_provenance(),
            schema_map,
            {"PrintIMVersion": "0x0000"},
        )


def composite_exif_tags(values: Mapping[str, TagValue]) -> TagMap:
    aperture = values.get("FNumber") or values.get("ApertureValue")
    tags: TagMap = {}
    if isinstance(aperture, (int, float)):
        tags["Aperture"] = aperture
    return tags


def add_graph_derived_composite_tags(
    tags: list[ReadTag],
    schema_map: SchemaProvenanceMap,
    path: Path,
) -> None:
    from exifmodern.composites.exif_lens import exif_lens_composite_overrides

    values: TagMap = {}
    aperture = first_graph_tag_value(tags, (("ExifIFD", "FNumber"), ("ExifIFD", "ApertureValue")))
    if (
        find_group_tag_value(tags, "Composite", "Aperture") is None
        and isinstance(aperture, (int, float))
        and not isinstance(aperture, bool)
    ):
        values["Aperture"] = aperture
        add_tags(tags, values, composite_provenance(), schema_map)
        values = {}
    shutter_speed = graph_shutter_speed(tags)
    if shutter_speed is not None:
        values["ShutterSpeed"] = shutter_speed.rendered
    light_value = graph_light_value(tags, shutter_speed)
    if light_value is not None:
        values["LightValue"] = light_value
    values.update(graph_lens_composite_tags(tags))
    lens_overrides = stronger_exif_lens_composite_overrides(
        values,
        exif_lens_composite_overrides(path) if graph_file_type(tags) == "JPEG" else {},
    )
    values.update(lens_overrides)
    values.update(graph_gps_composite_tags(tags))
    values.update(graph_subsecond_composite_tags(tags))
    values.update(graph_panasonic_composite_tags(tags))
    values.update(graph_runtime_composite_tags(tags))
    values.update(graph_image_composite_tags(tags))
    values.update(graph_auto_focus_composite_tags(tags))
    add_tags(tags, values, composite_provenance(), schema_map)


def graph_file_type(tags: list[ReadTag]) -> str | None:
    value = find_group_tag_value(tags, "File", "FileType")
    return value if isinstance(value, str) else None


def stronger_exif_lens_composite_overrides(
    existing: TagMap,
    overrides: Mapping[TagName, TagValue],
) -> TagMap:
    if not overrides:
        return {}
    filtered = dict(overrides)
    existing_35efl = existing.get("FocalLength35efl")
    override_35efl = filtered.get("FocalLength35efl")
    if (
        isinstance(existing_35efl, str)
        and "35 mm equivalent" in existing_35efl
        and isinstance(override_35efl, str)
        and "35 mm equivalent" not in override_35efl
    ):
        del filtered["FocalLength35efl"]
    return filtered


def add_graph_derived_exiftool_tags(
    tags: list[ReadTag],
    schema_map: SchemaProvenanceMap,
) -> None:
    values: TagMap = {}
    if find_group_tag_value(tags, "ExifTool", "ExifToolVersion") is None:
        values["ExifToolVersion"] = EXIFTOOL_COMPATIBILITY_VERSION
    iptc_digest = find_group_tag_value(tags, "Photoshop", "IPTCDigest")
    current_iptc_digest = find_group_tag_value(tags, "File", "CurrentIPTCDigest")
    if (
        isinstance(iptc_digest, str)
        and isinstance(current_iptc_digest, str)
        and iptc_digest != current_iptc_digest
    ):
        values["Warning"] = "IPTCDigest is not current. XMP may be out of sync"
    add_tags(tags, values, exiftool_provenance(), schema_map)


@dataclass(frozen=True)
class ExposureTimeValue:
    rendered: str
    seconds: float


def graph_shutter_speed(tags: list[ReadTag]) -> ExposureTimeValue | None:
    exposure_time = find_group_tag_value(tags, "PictureInfo", "ExposureTime")
    if isinstance(exposure_time, str):
        value = parse_exposure_time(exposure_time)
        if value is not None:
            return value
    exif_exposure_time = find_group_tag_value(tags, "ExifIFD", "ExposureTime")
    if isinstance(exif_exposure_time, str):
        value = parse_exposure_time(exif_exposure_time)
        if value is not None:
            return value
    shutter_speed = find_group_tag_value(tags, "ExifIFD", "ShutterSpeedValue")
    if isinstance(shutter_speed, str):
        return parse_exposure_time(shutter_speed)
    if isinstance(shutter_speed, (int, float)) and not isinstance(shutter_speed, bool):
        return ExposureTimeValue(
            rendered=render_numeric_exposure_time(shutter_speed),
            seconds=float(shutter_speed),
        )
    return None


def graph_light_value(
    tags: list[ReadTag],
    shutter_speed: ExposureTimeValue | None,
) -> float | None:
    if shutter_speed is None or shutter_speed.seconds <= 0:
        return None
    aperture = find_group_tag_value(tags, "Composite", "Aperture")
    iso = find_group_tag_value(tags, "ExifIFD", "ISO")
    if not isinstance(aperture, (int, float)) or not isinstance(iso, int) or iso <= 0:
        return None
    light_value = (2 * math.log2(float(aperture))) - math.log2(shutter_speed.seconds)
    light_value -= math.log2(iso / 100)
    return round(light_value, 1)


def graph_lens_composite_tags(tags: list[ReadTag]) -> TagMap:
    focal_length = graph_length_mm(find_group_tag_value(tags, "ExifIFD", "FocalLength"))
    aperture = find_group_tag_value(tags, "Composite", "Aperture")
    equivalent_35mm = graph_length_mm(
        find_group_tag_value(tags, "ExifIFD", "FocalLengthIn35mmFormat")
    )
    focal_plane_width = graph_length_mm(find_group_tag_value(tags, "CIFF", "FocalPlaneXSize"))
    focal_plane_height = graph_length_mm(find_group_tag_value(tags, "CIFF", "FocalPlaneYSize"))
    if focal_length is None:
        return {}
    values: TagMap = {"FocalLength35efl": f"{focal_length:.1f} mm"}
    lens_model = first_graph_tag_value(
        tags,
        (
            ("ExifIFD", "LensModel"),
            ("XMP-exifEX", "LensModel"),
        ),
    )
    if isinstance(lens_model, str) and lens_model:
        values["LensID"] = lens_model
    else:
        lens = find_group_tag_value(tags, "XMP-aux", "Lens")
        if isinstance(lens, str) and lens:
            values["LensID"] = lens
    if (
        equivalent_35mm is not None
        and equivalent_35mm > 0
        and isinstance(aperture, (int, float))
        and aperture > 0
    ):
        scale_factor = equivalent_35mm / focal_length
        full_frame_diagonal = math.hypot(36, 24)
        circle_of_confusion = (full_frame_diagonal / 1440) / scale_factor
        fov = math.degrees(2 * math.atan(36 / (2 * equivalent_35mm)))
        hyperfocal_meters = (
            (focal_length * focal_length) / (float(aperture) * circle_of_confusion)
        ) / 1000
        values.update(
            {
                "ScaleFactor35efl": round(scale_factor, 1),
                "CircleOfConfusion": f"{circle_of_confusion:.3f} mm",
                "FOV": f"{fov:.1f} deg",
                "FocalLength35efl": (
                    f"{focal_length:.1f} mm (35 mm equivalent: {equivalent_35mm:.1f} mm)"
                ),
                "HyperfocalDistance": f"{hyperfocal_meters:.2f} m",
            }
        )
        return values
    if (
        not isinstance(aperture, (int, float))
        or aperture <= 0
        or focal_plane_width is None
        or focal_plane_height is None
        or focal_plane_width <= 0
        or focal_plane_height <= 0
    ):
        return values
    full_frame_diagonal = math.hypot(36, 24)
    sensor_diagonal = math.hypot(focal_plane_width, focal_plane_height)
    scale_factor = full_frame_diagonal / sensor_diagonal
    circle_of_confusion = (full_frame_diagonal / 1440) / scale_factor
    equivalent_focal_length = focal_length * scale_factor
    fov = math.degrees(2 * math.atan(36 / (2 * equivalent_focal_length)))
    hyperfocal_meters = (
        (focal_length * focal_length) / (float(aperture) * circle_of_confusion)
    ) / 1000
    values.update(
        {
            "ScaleFactor35efl": round(scale_factor, 1),
            "CircleOfConfusion": f"{circle_of_confusion:.3f} mm",
            "FOV": f"{fov:.1f} deg",
            "FocalLength35efl": (
                f"{focal_length:.1f} mm (35 mm equivalent: {equivalent_focal_length:.1f} mm)"
            ),
            "HyperfocalDistance": f"{hyperfocal_meters:.2f} m",
        }
    )
    return values


def graph_gps_composite_tags(tags: list[ReadTag]) -> TagMap:
    latitude = graph_gps_coordinate_with_ref(
        find_group_tag_value(tags, "GPS", "GPSLatitude"),
        find_group_tag_value(tags, "GPS", "GPSLatitudeRef"),
    )
    longitude = graph_gps_coordinate_with_ref(
        find_group_tag_value(tags, "GPS", "GPSLongitude"),
        find_group_tag_value(tags, "GPS", "GPSLongitudeRef"),
    )
    values: TagMap = {}
    if latitude is not None:
        values["GPSLatitude"] = latitude
    if longitude is not None:
        values["GPSLongitude"] = longitude
    if latitude is not None and longitude is not None and (latitude or longitude):
        values["GPSPosition"] = f"{latitude}, {longitude}"
    altitude = graph_gps_altitude_with_ref(
        find_group_tag_value(tags, "GPS", "GPSAltitude"),
        find_group_tag_value(tags, "GPS", "GPSAltitudeRef"),
    )
    if altitude is not None:
        values["GPSAltitude"] = altitude
    date_time = graph_gps_date_time(
        find_group_tag_value(tags, "GPS", "GPSDateStamp"),
        find_group_tag_value(tags, "GPS", "GPSTimeStamp"),
    )
    if date_time is not None:
        values["GPSDateTime"] = date_time
    return values


def graph_gps_coordinate_with_ref(
    coordinate: TagValue | None,
    reference: TagValue | None,
) -> str | None:
    if not isinstance(coordinate, str) or not isinstance(reference, str):
        return None
    if coordinate == "" and reference == "Unknown ()":
        return ""
    suffix = {"North": "N", "South": "S", "East": "E", "West": "W"}.get(reference)
    if suffix is None:
        return None
    return f"{coordinate} {suffix}"


def graph_gps_altitude_with_ref(
    altitude: TagValue | None,
    reference: TagValue | None,
) -> str | None:
    if not isinstance(altitude, str):
        return None
    if altitude == "undef":
        return None
    altitude_value = graph_composite_altitude_number(altitude.removesuffix(" m"))
    if reference == "Below Sea Level":
        return f"{altitude_value} m Below Sea Level"
    if isinstance(reference, str) and "Sea Level" in reference:
        return f"{altitude_value} m Above Sea Level"
    return None


def graph_composite_altitude_number(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    if "." not in value:
        return value
    return f"{math.floor(number * 10) / 10:.1f}"


def graph_gps_date_time(date_stamp: TagValue | None, time_stamp: TagValue | None) -> str | None:
    if not isinstance(date_stamp, str) or not isinstance(time_stamp, str):
        return None
    return f"{date_stamp} {time_stamp}Z"


def graph_subsecond_composite_tags(tags: list[ReadTag]) -> TagMap:
    values: TagMap = {}
    create_date = find_group_tag_value(tags, "ExifIFD", "CreateDate")
    date_time_original = find_group_tag_value(tags, "ExifIFD", "DateTimeOriginal")
    modify_date = find_group_tag_value(tags, "IFD0", "ModifyDate")
    subsec = find_group_tag_value(tags, "ExifIFD", "SubSecTime")
    subsec_digitized = find_group_tag_value(tags, "ExifIFD", "SubSecTimeDigitized")
    subsec_original = find_group_tag_value(tags, "ExifIFD", "SubSecTimeOriginal")
    offset_time = find_group_tag_value(tags, "ExifIFD", "OffsetTime")
    offset_time_digitized = find_group_tag_value(tags, "ExifIFD", "OffsetTimeDigitized")
    offset_time_original = find_group_tag_value(tags, "ExifIFD", "OffsetTimeOriginal")
    if isinstance(modify_date, str):
        modify_subsecond = graph_subsecond_int(subsec)
        if modify_subsecond is not None:
            values["SubSecModifyDate"] = graph_subsecond_datetime(
                modify_date,
                modify_subsecond,
                offset_time,
            )
    if isinstance(create_date, str):
        create_subsecond = graph_subsecond_int(subsec_digitized)
        if create_subsecond is not None:
            values["SubSecCreateDate"] = graph_subsecond_datetime(
                create_date,
                create_subsecond,
                offset_time_digitized,
            )
    if isinstance(date_time_original, str):
        original_subsecond = graph_subsecond_int(subsec_original)
        if original_subsecond is not None:
            values["SubSecDateTimeOriginal"] = graph_subsecond_datetime(
                date_time_original,
                original_subsecond,
                offset_time_original,
            )
    return values


def graph_subsecond_int(value: TagValue | None) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def graph_subsecond_datetime(date_time: str, subsecond: int, offset_time: TagValue | None) -> str:
    suffix = offset_time if isinstance(offset_time, str) else ""
    return f"{date_time}.{subsecond:03d}{suffix}"


def graph_panasonic_composite_tags(tags: list[ReadTag]) -> TagMap:
    wb_red_level = find_group_tag_value(tags, "MakerNotes", "WBRedLevel")
    wb_green_level = find_group_tag_value(tags, "MakerNotes", "WBGreenLevel")
    wb_blue_level = find_group_tag_value(tags, "MakerNotes", "WBBlueLevel")
    scene_mode = find_group_tag_value(tags, "MakerNotes", "SceneMode")
    advanced_scene_type = find_group_tag_value(tags, "MakerNotes", "AdvancedSceneType")
    values: TagMap = {}
    if (
        isinstance(wb_red_level, int)
        and isinstance(wb_green_level, int)
        and isinstance(wb_blue_level, int)
        and wb_green_level > 0
    ):
        values["BlueBalance"] = round_half_up(wb_blue_level / wb_green_level, 6)
        values["RedBalance"] = round_half_up(wb_red_level / wb_green_level, 6)
    if advanced_scene_type == 1:
        if scene_mode == "Off":
            values["AdvancedSceneMode"] = "Off"
        elif isinstance(scene_mode, int):
            values["AdvancedSceneMode"] = f"Unknown ({scene_mode} {advanced_scene_type})"
    return values


def round_half_up(value: float, digits: int) -> float:
    scale: int = 10**digits
    rounded: int = math.floor(value * scale + 0.5)
    return rounded / scale


def graph_runtime_composite_tags(tags: list[ReadTag]) -> TagMap:
    value = find_group_tag_value(tags, "MakerNotes", "RunTimeValue")
    scale = find_group_tag_value(tags, "MakerNotes", "RunTimeScale")
    if not isinstance(value, int) or not isinstance(scale, int) or scale <= 0:
        return {}
    seconds = value // scale
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60
    return {"RunTimeSincePowerUp": f"{hours}:{minutes:02d}:{remaining_seconds:02d}"}


def graph_image_composite_tags(tags: list[ReadTag]) -> TagMap:
    width = find_group_tag_value(tags, "File", "ImageWidth")
    height = find_group_tag_value(tags, "File", "ImageHeight")
    if not isinstance(width, int) or not isinstance(height, int):
        return {}
    return composite_image_tags(width, height)


def graph_auto_focus_composite_tags(tags: list[ReadTag]) -> TagMap:
    for tag in tags:
        if (
            tag.provenance.group == "MakerNotes"
            and tag.provenance.family_1_group == "Nikon"
            and tag.name == "FocusMode"
            and isinstance(tag.value, str)
        ):
            return {"AutoFocus": "Off" if tag.value.lower().startswith("manual") else "On"}
    return {}


def graph_length_mm(value: TagValue | None) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.endswith(" mm"):
        return None
    try:
        return float(value.removesuffix(" mm"))
    except ValueError:
        return None


def parse_exposure_time(value: str) -> ExposureTimeValue | None:
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        if numerator.isdecimal() and denominator.isdecimal() and int(denominator) != 0:
            return ExposureTimeValue(
                rendered=value,
                seconds=int(numerator) / int(denominator),
            )
    try:
        seconds = float(value)
    except ValueError:
        return None
    return ExposureTimeValue(rendered=value, seconds=seconds)


def render_numeric_exposure_time(value: int | float) -> str:
    if isinstance(value, int) or value.is_integer():
        return str(int(value))
    return str(value)


def find_group_tag_value(
    tags: list[ReadTag],
    group: GroupName,
    name: TagName,
) -> TagValue | None:
    for tag in tags:
        if tag.provenance.group == group and tag.name == name:
            return tag.value
    return None


def first_graph_tag_value(
    tags: list[ReadTag],
    keys: tuple[tuple[GroupName, TagName], ...],
) -> TagValue | None:
    for group, name in keys:
        value = find_group_tag_value(tags, group, name)
        if value is not None:
            return value
    return None


def add_tags(
    tags: list[ReadTag],
    values: TagMap,
    provenances: dict[TagName, TagProvenance],
    schema_map: SchemaProvenanceMap,
) -> None:
    for name, value in values.items():
        provenance = provenances.get(name)
        if provenance is None:
            continue
        tags.append(
            ReadTag(
                name=name,
                value=value,
                provenance=provenance,
                schema=schema_map.get(schema_tag_key(provenance.group, name)),
            )
        )


def normalize_tag_map(values: JsonObject) -> TagMap:
    normalized: TagMap = {}
    for key, value in values.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            normalized[key] = value
        elif isinstance(value, list):
            string_items = json_string_array_or_none(value)
            if string_items is not None:
                scalar_items: list[ScalarTagValue] = list(string_items)
                normalized[key] = scalar_items
    return normalized


def load_schema_provenance_map(path: Path | None) -> SchemaProvenanceMap:
    if path is None:
        return {}
    payload = load_json_object(path)
    schema_map: SchemaProvenanceMap = {}
    for raw_tag in json_array_value(payload, "tags"):
        if not isinstance(raw_tag, dict):
            continue
        key = raw_tag.get("key")
        if not isinstance(key, str):
            continue
        schema_map[key] = ReadTagSchema(
            matched=bool(raw_tag.get("matched", False)),
            schema_name=optional_str(raw_tag.get("schema_name")),
            schema_tag_id=optional_str(raw_tag.get("schema_tag_id")),
            writable=optional_str(raw_tag.get("writable")),
            write_group=optional_str(raw_tag.get("write_group")),
            operation_count=json_int_value(raw_tag, "operation_count") or 0,
            operations=schema_operation_summaries(raw_tag.get("operations", [])),
            runtime_dynamic=json_bool_value(raw_tag, "runtime_dynamic") or False,
        )
    return schema_map


def schema_operation_summaries(raw_operations: JsonValue | None) -> list[str]:
    summaries: list[str] = []
    if not isinstance(raw_operations, list):
        return summaries
    for raw_operation in raw_operations:
        if not isinstance(raw_operation, dict):
            continue
        field = raw_operation.get("field")
        kind = raw_operation.get("kind")
        summary = raw_operation.get("summary")
        if not isinstance(field, str) or not isinstance(kind, str) or not isinstance(summary, str):
            continue
        summaries.append(f"{field}:{kind}:{summary}")
    return summaries


def optional_str(value: JsonValue | None) -> str | None:
    return json_scalar_to_string(value)


def schema_tag_key(group: GroupName, tag_name: TagName) -> str:
    return f"{group}:{tag_name}"


def ifd0_provenance() -> dict[TagName, TagProvenance]:
    return {
        name: TagProvenance("IFD0", "Image::ExifTool::Exif::Main", tag_id, "jpeg-app1-ifd0")
        for name, tag_id in IFD0_TAG_IDS.items()
    }


def composite_provenance() -> dict[TagName, TagProvenance]:
    return {
        name: TagProvenance("Composite", "Image::ExifTool::Composite", tag_id, "derived-image")
        for name, tag_id in COMPOSITE_TAG_IDS.items()
    }


def exiftool_provenance() -> dict[TagName, TagProvenance]:
    return {
        name: TagProvenance("ExifTool", "Image::ExifTool::Extra", tag_id, "derived-warning")
        for name, tag_id in EXIFTOOL_TAG_IDS.items()
    }


def system_provenance() -> dict[TagName, TagProvenance]:
    return {
        name: TagProvenance(
            "System",
            "Image::ExifTool::Extra",
            tag_id,
            "filesystem",
            family_0_group="File",
            family_1_group="System",
            family_2_group=SYSTEM_FAMILY_2_GROUPS[name],
        )
        for name, tag_id in SYSTEM_TAG_IDS.items()
    }


def jpeg_app_segment_provenance(
    reader: JpegAppSegmentReader,
) -> dict[TagName, TagProvenance]:
    return dict(
        cached_jpeg_app_segment_provenance(
            reader.group,
            reader.table_name,
            reader.source,
            tuple(reader.tag_ids.items()),
        )
    )


@lru_cache(maxsize=256)
def cached_jpeg_app_segment_provenance(
    group: str,
    table_name: str,
    source: str,
    tag_ids: tuple[tuple[str, str], ...],
) -> tuple[tuple[TagName, TagProvenance], ...]:
    return tuple(
        (
            name,
            TagProvenance(
                group,
                table_name,
                tag_id,
                source,
                family_0_group=jpeg_app_segment_family_0_group_from_values(
                    group,
                    table_name,
                    name,
                ),
                family_1_group=jpeg_app_segment_family_1_group_from_values(
                    group,
                    table_name,
                    name,
                ),
                family_2_group=jpeg_app_segment_family_2_group_from_values(
                    group,
                    table_name,
                    name,
                ),
                family_4_instance_group=jpeg_app_segment_family_4_group_from_values(
                    group,
                    table_name,
                    name,
                ),
                duplicate_instance_ordinal=jpeg_app_segment_duplicate_instance_ordinal_from_values(
                    group,
                    table_name,
                    name,
                ),
            ),
        )
        for name, tag_id in tag_ids
    )


def afcp_iptc_provenance_for_existing_tags(
    tags: list[ReadTag],
    provenances: dict[TagName, TagProvenance],
) -> dict[TagName, TagProvenance]:
    """Assign AFCP IPTC to the next ExifTool IPTC family-1 instance.

    Source: JPEG.pm routes generic trailer IPTC as a duplicate IPTC instance,
    while AFCP.pm processes AFCP-contained IPTC as an IPTC subdirectory. The
    family-1 label is therefore IPTC2 when AFCP is the first duplicate IPTC
    source, and IPTC3 when an APP13 IPTC record already exists.
    """

    existing_application_groups = {
        tag.provenance.group
        for tag in tags
        if tag.provenance.table_name == "Image::ExifTool::IPTC::ApplicationRecord"
    }
    group = "IPTC3" if "IPTC" in existing_application_groups else "IPTC2"
    return {
        name: replace(provenance, group=group, family_1_group=group)
        for name, provenance in provenances.items()
    }


def icc_profile_provenance_for_app_segment(
    reader: JpegAppSegmentReader,
) -> dict[TagName, TagProvenance]:
    from exifmodern.formats.icc.reader import (
        icc_group_name_for_tag,
        icc_table_name_for_tag,
        icc_tag_id_for_tag,
    )

    return {
        name: TagProvenance(
            icc_group_name_for_tag(name),
            icc_table_name_for_tag(name),
            icc_tag_id_for_tag(name),
            reader.source,
            family_0_group="ICC_Profile",
            family_1_group=icc_group_name_for_tag(name),
            family_2_group="Image",
        )
        for name in reader.tag_ids
    }


def jpeg_app_segment_family_0_group(
    reader: JpegAppSegmentReader,
    name: TagName,
) -> GroupName | None:
    return jpeg_app_segment_family_0_group_from_values(reader.group, reader.table_name, name)


def jpeg_app_segment_family_0_group_from_values(
    group: str,
    table_name: str,
    name: TagName,
) -> GroupName | None:
    if group in {"JFIF", "JFXX"}:
        return "JFIF"
    if is_mpf_mpimage_duplicate_tag_from_values(group, table_name, name):
        return "MPF"
    return None


def jpeg_app_segment_family_1_group(
    reader: JpegAppSegmentReader,
    name: TagName,
) -> GroupName | None:
    return jpeg_app_segment_family_1_group_from_values(reader.group, reader.table_name, name)


def jpeg_app_segment_family_1_group_from_values(
    group: str,
    table_name: str,
    name: TagName,
) -> GroupName | None:
    if group in {"JFIF", "JFXX"}:
        return group
    if is_mpf_mpimage_duplicate_tag_from_values(group, table_name, name):
        return group
    return None


def jpeg_app_segment_family_2_group(
    reader: JpegAppSegmentReader,
    name: TagName,
) -> GroupName | None:
    return jpeg_app_segment_family_2_group_from_values(reader.group, reader.table_name, name)


def jpeg_app_segment_family_2_group_from_values(
    group: str,
    table_name: str,
    name: TagName,
) -> GroupName | None:
    if group == "JFXX" and name == "ThumbnailImage":
        return "Preview"
    if group == "JFIF":
        return "Image"
    if is_mpf_mpimage_duplicate_tag_from_values(group, table_name, name):
        return "Image"
    return None


def jpeg_app_segment_family_4_group(
    reader: JpegAppSegmentReader,
    name: TagName,
) -> GroupName | None:
    ordinal = jpeg_app_segment_duplicate_instance_ordinal_from_values(
        reader.group,
        reader.table_name,
        name,
    )
    return jpeg_app_segment_family_4_group_for_ordinal(ordinal)


def jpeg_app_segment_family_4_group_from_values(
    group: str,
    table_name: str,
    name: TagName,
) -> GroupName | None:
    ordinal = jpeg_app_segment_duplicate_instance_ordinal_from_values(group, table_name, name)
    return jpeg_app_segment_family_4_group_for_ordinal(ordinal)


def jpeg_app_segment_family_4_group_for_ordinal(ordinal: int | None) -> GroupName | None:
    if ordinal is None:
        return None
    return "" if ordinal == 0 else f"Copy{ordinal}"


def jpeg_app_segment_duplicate_instance_ordinal(
    reader: JpegAppSegmentReader,
    name: TagName,
) -> int | None:
    return jpeg_app_segment_duplicate_instance_ordinal_from_values(
        reader.group,
        reader.table_name,
        name,
    )


def jpeg_app_segment_duplicate_instance_ordinal_from_values(
    group: str,
    table_name: str,
    name: TagName,
) -> int | None:
    if not is_mpf_mpimage_duplicate_tag_from_values(group, table_name, name):
        return None
    suffix = group.removeprefix("MPImage")
    if not suffix.isdecimal():
        return None
    return max(int(suffix) - 1, 0)


def is_mpf_mpimage_duplicate_tag(
    reader: JpegAppSegmentReader,
    name: TagName,
) -> bool:
    return is_mpf_mpimage_duplicate_tag_from_values(reader.group, reader.table_name, name)


def is_mpf_mpimage_duplicate_tag_from_values(
    group: str,
    table_name: str,
    name: TagName,
) -> bool:
    return (
        table_name == "Image::ExifTool::MPF::MPImage"
        and group.startswith("MPImage")
        and name.startswith("MPImage")
    )


def ifd1_provenance() -> dict[TagName, TagProvenance]:
    provenance = {
        name: TagProvenance("IFD1", "Image::ExifTool::Exif::Main", tag_id, "jpeg-app1-ifd1")
        for name, tag_id in IFD1_TAG_IDS.items()
    }
    provenance["ThumbnailImage"] = TagProvenance(
        "IFD1",
        "Image::ExifTool::Extra",
        "ThumbnailImage",
        "jpeg-app1-ifd1",
        family_0_group="EXIF",
        family_1_group="IFD1",
        family_2_group="Preview",
    )
    return provenance


def exif_ifd_provenance() -> dict[TagName, TagProvenance]:
    return {
        name: TagProvenance("ExifIFD", "Image::ExifTool::Exif::Main", tag_id, "jpeg-app1-exififd")
        for name, tag_id in EXIF_IFD_TAG_IDS.items()
    }


def gps_provenance() -> dict[TagName, TagProvenance]:
    return {
        name: TagProvenance(
            "GPS",
            "Image::ExifTool::GPS::Main",
            tag_id,
            "jpeg-app1-gps",
            family_0_group="EXIF",
            family_1_group="GPS",
            family_2_group=GPS_FAMILY_2_GROUPS.get(name, "Location"),
        )
        for name, tag_id in GPS_TAG_IDS.items()
    }


def encoding_process(sof_marker: int) -> str:
    if sof_marker == 0xC0:
        return "Baseline DCT, Huffman coding"
    if sof_marker == 0xC2:
        return "Progressive DCT, Huffman coding"
    return f"SOF marker 0xFF{sof_marker:02X}"
