"""Typed registry for optional JPEG APP-segment extension readers."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from exifmodern.json_types import JsonObject

type JpegAppSegmentTagIds = Mapping[str, str]
type JpegAppSegmentRead = Callable[[Path], JsonObject]
type LazyTagIdFunction = tuple[str, str]


@dataclass(frozen=True)
class JpegAppSegmentReader:
    inspection_key: str
    group: str
    table_name: str
    source: str
    missing_message_prefix: str
    tag_ids: JpegAppSegmentTagIds
    read: JpegAppSegmentRead
    runtime_dynamic_tag_names: tuple[str, ...] = ()


def _lazy_reader(module_path: str, function_name: str) -> JpegAppSegmentRead:
    def read(path: Path) -> JsonObject:
        function = getattr(import_module(module_path), function_name)
        result = function(path)
        if not isinstance(result, dict):
            raise TypeError(f"{module_path}:{function_name} returned {type(result).__name__}")
        return result

    return read


class LazyJpegAppSegmentTagIds(Mapping[str, str]):
    def __init__(
        self,
        static_items: tuple[tuple[str, str], ...] = (),
        lazy_functions: tuple[LazyTagIdFunction, ...] = (),
    ) -> None:
        self._static_items = static_items
        self._lazy_functions = lazy_functions
        self._cache: dict[str, str] | None = None

    def __getitem__(self, key: str) -> str:
        return self._materialized()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._materialized())

    def __len__(self) -> int:
        return len(self._materialized())

    def _materialized(self) -> dict[str, str]:
        if self._cache is None:
            tag_ids = dict(self._static_items)
            for module_path, function_name in self._lazy_functions:
                function = getattr(import_module(module_path), function_name)
                tag_ids.update(function())
            self._cache = tag_ids
        return self._cache


def _tag_ids(
    *static_items: tuple[str, str],
    lazy_functions: tuple[LazyTagIdFunction, ...] = (),
) -> JpegAppSegmentTagIds:
    if not lazy_functions:
        return dict(static_items)
    return LazyJpegAppSegmentTagIds(static_items, lazy_functions)


read_adobe_cm_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.adobe",
    "read_adobe_cm_tags",
)
read_adobe_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.adobe", "read_adobe_tags")
read_app10_comment_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.app10",
    "read_app10_comment_tags",
)
read_avi1_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.avi1", "read_avi1_tags")
read_ducky_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.ducky", "read_ducky_tags")
read_eppim_printim_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.printim",
    "read_eppim_printim_tags",
)
read_flashpix_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.flashpix",
    "read_flashpix_tags",
)
read_graphconv_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.graphconv",
    "read_graphconv_tags",
)
read_icc_header_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.icc",
    "read_icc_header_tags",
)
read_icc_profile_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.icc",
    "read_icc_profile_tags",
)
read_jfif_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.jfif", "read_jfif_tags")
read_jfxx_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.jfif", "read_jfxx_tags")
read_jpeg_hdr_gain_info_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.hdr",
    "read_jpeg_hdr_gain_info_tags",
)
read_jpeg_hdr_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.hdr",
    "read_jpeg_hdr_tags",
)
read_jumbf_json_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.jumbf",
    "read_jumbf_json_tags",
)
read_jumbf_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.jumbf", "read_jumbf_tags")
read_kodak_meta_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.kodak",
    "read_kodak_meta_tags",
)
read_media_jukebox_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.media_jukebox",
    "read_media_jukebox_tags",
)
read_mpf0_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.mpf", "read_mpf0_tags")
read_mpimage1_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.mpf",
    "read_mpimage1_tags",
)
read_mpimage2_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.mpf",
    "read_mpimage2_tags",
)
read_nitf_app6_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.nitf",
    "read_nitf_app6_tags",
)
read_picture_info_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.picture_info",
    "read_picture_info_tags",
)
read_qualcomm_app7_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.qualcomm",
    "read_qualcomm_app7_tags",
)
read_ricoh_rmeta_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.ricoh",
    "read_ricoh_rmeta_tags",
)
read_spiff_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.spiff", "read_spiff_tags")
read_afcp_iptc_tags = _lazy_reader(
    "exifmodern.formats.jpeg.trailers.afcp",
    "read_afcp_iptc_tags",
)
read_canon_vrd_tags = _lazy_reader(
    "exifmodern.formats.jpeg.trailers.canon_vrd",
    "read_canon_vrd_tags",
)
read_fotostation_tags = _lazy_reader(
    "exifmodern.formats.jpeg.trailers.fotostation",
    "read_fotostation_tags",
)
read_mie_doc_tags = _lazy_reader("exifmodern.formats.jpeg.trailers.mie", "read_mie_doc_tags")
read_mie_main_tags = _lazy_reader("exifmodern.formats.jpeg.trailers.mie", "read_mie_main_tags")
read_photo_mechanic_tags = _lazy_reader(
    "exifmodern.formats.jpeg.trailers.photomechanic",
    "read_photo_mechanic_tags",
)
read_samsung_trailer_tags = _lazy_reader(
    "exifmodern.formats.jpeg.trailers.samsung",
    "read_samsung_trailer_tags",
)
read_trailing_iptc_tags = _lazy_reader(
    "exifmodern.formats.jpeg.trailers.afcp",
    "read_trailing_iptc_tags",
)
read_vivo_tags = _lazy_reader("exifmodern.formats.jpeg.trailers.vivo", "read_vivo_tags")
read_xmp_acdsee_region_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.xmp",
    "read_xmp_acdsee_region_tags",
)
read_xmp_aux_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.xmp", "read_xmp_aux_tags")
read_xmp_bj_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.xmp", "read_xmp_bj_tags")
read_xmp_crd_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.xmp", "read_xmp_crd_tags")
read_xmp_creator_atom_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.xmp",
    "read_xmp_creator_atom_tags",
)
read_xmp_crs_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.xmp", "read_xmp_crs_tags")
read_xmp_dc_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.xmp", "read_xmp_dc_tags")
read_xmp_dm_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.xmp", "read_xmp_dm_tags")
read_xmp_exif_ex_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.xmp",
    "read_xmp_exif_ex_tags",
)
read_xmp_exif_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.xmp",
    "read_xmp_exif_tags",
)
read_xmp_hdrgm_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.xmp",
    "read_xmp_hdrgm_tags",
)
read_xmp_ics_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.xmp", "read_xmp_ics_tags")
read_xmp_iptc_core_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.xmp",
    "read_xmp_iptc_core_tags",
)
read_xmp_iptc_ext_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.xmp",
    "read_xmp_iptc_ext_tags",
)
read_xmp_mm_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.xmp", "read_xmp_mm_tags")
read_xmp_pdf_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.xmp", "read_xmp_pdf_tags")
read_xmp_photoshop_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.xmp",
    "read_xmp_photoshop_tags",
)
read_xmp_prism_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.xmp",
    "read_xmp_prism_tags",
)
read_xmp_rdf_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.xmp", "read_xmp_rdf_tags")
read_xmp_rights_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.xmp",
    "read_xmp_rights_tags",
)
read_xmp_tiff_tags = _lazy_reader(
    "exifmodern.formats.jpeg.app_segments.xmp",
    "read_xmp_tiff_tags",
)
read_xmp_tpg_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.xmp", "read_xmp_tpg_tags")
read_xmp_x_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.xmp", "read_xmp_x_tags")
read_xmp_xmp_tags = _lazy_reader("exifmodern.formats.jpeg.app_segments.xmp", "read_xmp_xmp_tags")


def read_ciff_tags(path: Path) -> JsonObject:
    from exifmodern.formats.jpeg.app_segments.ciff import read_ciff_tags as read

    return read(path)


def read_current_iptc_digest_tags(path: Path) -> JsonObject:
    from exifmodern.formats.jpeg.app_segments.photoshop import read_current_iptc_digest_tags as read

    return read(path)


def read_iptc_tags(path: Path) -> JsonObject:
    from exifmodern.formats.jpeg.app_segments.photoshop import read_iptc_tags as read

    return read(path)


def read_photoshop_core_tags(path: Path) -> JsonObject:
    from exifmodern.formats.jpeg.app_segments.photoshop import read_photoshop_core_tags as read

    return read(path)


def read_photoshop_print_scale_tags(path: Path) -> JsonObject:
    from exifmodern.formats.jpeg.app_segments.photoshop import (
        read_photoshop_print_scale_tags as read,
    )

    return read(path)


def read_photoshop_quality_tags(path: Path) -> JsonObject:
    from exifmodern.formats.jpeg.app_segments.photoshop import read_photoshop_quality_tags as read

    return read(path)


def read_photoshop_resolution_tags(path: Path) -> JsonObject:
    from exifmodern.formats.jpeg.app_segments.photoshop import (
        read_photoshop_resolution_tags as read,
    )

    return read(path)


def read_photoshop_slice_tags(path: Path) -> JsonObject:
    from exifmodern.formats.jpeg.app_segments.photoshop import read_photoshop_slice_tags as read

    return read(path)


def read_photoshop_version_tags(path: Path) -> JsonObject:
    from exifmodern.formats.jpeg.app_segments.photoshop import read_photoshop_version_tags as read

    return read(path)


MPIMAGE_TAG_IDS: JpegAppSegmentTagIds = {
    "MPImageFlags": "0.1",
    "MPImageFormat": "0.2",
    "MPImageType": "0.3",
    "MPImageLength": "4",
    "MPImageStart": "8",
    "DependentImage1EntryNumber": "12",
    "DependentImage2EntryNumber": "14",
}


def mpimage_tag_ids_with_preview() -> JpegAppSegmentTagIds:
    return {**MPIMAGE_TAG_IDS, "PreviewImage": "PreviewImage"}


JPEG_APP_SEGMENT_READERS = (
    JpegAppSegmentReader(
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
    ),
    JpegAppSegmentReader(
        inspection_key="jfxx",
        group="JFXX",
        table_name="Image::ExifTool::JFIF::Extension",
        source="jpeg-app0-jfxx",
        missing_message_prefix="No JPEG JFXX APP0 thumbnail segment found:",
        tag_ids={
            "ThumbnailImage": "0x0010",
        },
        read=read_jfxx_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="ciff_main",
        group="CIFF",
        table_name="Image::ExifTool::CanonRaw::Main",
        source="jpeg-app0-ciff",
        missing_message_prefix="No JPEG Canon CIFF APP0 segment found:",
        tag_ids={
            "TargetImageType": "0x100A",
            "RecordID": "0x1804",
            "FileNumber": "0x1817",
            "OriginalFileName": "0x0816",
            "ThumbnailFileName": "0x0817",
            "ShutterReleaseMethod": "0x1010",
            "ShutterReleaseTiming": "0x1011",
            "TargetDistanceSetting": "0x1807",
            "MeasuredEV": "0x1814",
            "CanonFileDescription": "0x0805",
            "CanonImageType": "0x0815",
            "OwnerName": "0x0810",
            "BaseISO": "0x101C",
            "ROMOperationMode": "0x080D",
            "CanonFirmwareVersion": "0x080B",
            "FreeBytes": "0x0001",
        },
        read=read_ciff_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="ciff_image_format",
        group="CIFF",
        table_name="Image::ExifTool::CanonRaw::ImageFormat",
        source="jpeg-app0-ciff",
        missing_message_prefix="No JPEG Canon CIFF APP0 segment found:",
        tag_ids={
            "FileFormat": "0",
            "TargetCompressionRatio": "1",
        },
        read=read_ciff_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="ciff_image_info",
        group="CIFF",
        table_name="Image::ExifTool::CanonRaw::ImageInfo",
        source="jpeg-app0-ciff",
        missing_message_prefix="No JPEG Canon CIFF APP0 segment found:",
        tag_ids={
            "ImageWidth": "0",
            "ImageHeight": "1",
            "PixelAspectRatio": "2",
            "Rotation": "3",
            "ComponentBitDepth": "4",
            "ColorBitDepth": "5",
            "ColorBW": "6",
        },
        read=read_ciff_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="ciff_timestamp",
        group="CIFF",
        table_name="Image::ExifTool::CanonRaw::TimeStamp",
        source="jpeg-app0-ciff",
        missing_message_prefix="No JPEG Canon CIFF APP0 segment found:",
        tag_ids={
            "DateTimeOriginal": "0",
            "TimeZoneCode": "1",
            "TimeZoneInfo": "2",
        },
        read=read_ciff_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="ciff_flash_info",
        group="CIFF",
        table_name="Image::ExifTool::CanonRaw::FlashInfo",
        source="jpeg-app0-ciff",
        missing_message_prefix="No JPEG Canon CIFF APP0 segment found:",
        tag_ids={
            "FlashGuideNumber": "0",
            "FlashThreshold": "1",
        },
        read=read_ciff_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="ciff_exposure_info",
        group="CIFF",
        table_name="Image::ExifTool::CanonRaw::ExposureInfo",
        source="jpeg-app0-ciff",
        missing_message_prefix="No JPEG Canon CIFF APP0 segment found:",
        tag_ids={
            "ExposureCompensation": "0",
            "ShutterSpeedValue": "1",
            "ApertureValue": "2",
        },
        read=read_ciff_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="ciff_make_model",
        group="CIFF",
        table_name="Image::ExifTool::CanonRaw::MakeModel",
        source="jpeg-app0-ciff",
        missing_message_prefix="No JPEG Canon CIFF APP0 segment found:",
        tag_ids={
            "Make": "0",
            "Model": "6",
        },
        read=read_ciff_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="ciff_focal_length",
        group="CIFF",
        table_name="Image::ExifTool::Canon::FocalLength",
        source="jpeg-app0-ciff",
        missing_message_prefix="No JPEG Canon CIFF APP0 segment found:",
        tag_ids={
            "FocalType": "0",
            "FocalLength": "1",
            "FocalPlaneXSize": "2",
            "FocalPlaneYSize": "3",
        },
        read=read_ciff_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="flashpix_summary",
        group="FlashPix",
        table_name="Image::ExifTool::FlashPix::SummaryInfo",
        source="jpeg-app2-fpxr",
        missing_message_prefix="No JPEG FlashPix FPXR APP2 segment found:",
        tag_ids={
            "CodePage": "0x0001",
        },
        read=read_flashpix_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="flashpix_extensions",
        group="FlashPix",
        table_name="Image::ExifTool::FlashPix::Extensions",
        source="jpeg-app2-fpxr",
        missing_message_prefix="No JPEG FlashPix FPXR APP2 segment found:",
        tag_ids={
            "UsedExtensionNumbers": "0x10000000",
            "ExtensionName": "0x0001",
            "ExtensionClassID": "0x0002",
            "ExtensionPersistence": "0x0003",
            "ExtensionCreateDate": "0x0004",
            "ExtensionModifyDate": "0x0005",
            "CreatingApplication": "0x0006",
            "ExtensionDescription": "0x0007",
            "Storage-StreamPathname": "0x1000",
        },
        read=read_flashpix_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="flashpix_main",
        group="FlashPix",
        table_name="Image::ExifTool::FlashPix::Main",
        source="jpeg-app2-fpxr",
        missing_message_prefix="No JPEG FlashPix FPXR APP2 segment found:",
        tag_ids={
            "ScreenNail": "\x05Screen Nail",
            "PreviewImage": "Preview",
        },
        read=read_flashpix_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_x",
        group="XMP-x",
        table_name="Image::ExifTool::XMP::x",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            ("CreateDate", "CreateDate"),
            ("MetadataDate", "MetadataDate"),
            ("ModifyDate", "ModifyDate"),
            ("Rating", "Rating"),
            ("XMPToolkit", "xmptk"),
            lazy_functions=(
                ("exifmodern.formats.xmp.structs.basic_image", "basic_image_readback_tag_ids"),
            ),
        ),
        read=read_xmp_x_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_xmp",
        group="XMP-xmp",
        table_name="Image::ExifTool::XMP::xmp",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids={
            "CreateDate": "CreateDate",
            "CreatorTool": "CreatorTool",
            "MetadataDate": "MetadataDate",
            "ModifyDate": "ModifyDate",
            "Rating": "Rating",
        },
        read=read_xmp_xmp_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_rdf",
        group="XMP-rdf",
        table_name="Image::ExifTool::XMP::rdf",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids={
            "About": "about",
        },
        read=read_xmp_rdf_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_crd",
        group="XMP-crd",
        table_name="Image::ExifTool::XMP::crd",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            ("ColorNoiseReduction", "ColorNoiseReduction"),
            ("ColorVariance", "ColorVariance"),
            ("Exposure", "Exposure"),
            lazy_functions=(
                ("exifmodern.formats.xmp.structs.camera_raw", "camera_raw_crd_readback_tag_ids"),
            ),
        ),
        read=read_xmp_crd_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_crs",
        group="XMP-crs",
        table_name="Image::ExifTool::XMP::crs",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            ("ColorNoiseReduction", "ColorNoiseReduction"),
            ("ColorVariance", "ColorVariance"),
            ("Exposure", "Exposure"),
            lazy_functions=(
                ("exifmodern.formats.xmp.structs.camera_raw", "camera_raw_crs_readback_tag_ids"),
            ),
        ),
        read=read_xmp_crs_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_aux",
        group="XMP-aux",
        table_name="Image::ExifTool::XMP::aux",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids={
            "Firmware": "Firmware",
            "FlashCompensation": "FlashCompensation",
            "IsMergedHDR": "IsMergedHDR",
            "Lens": "Lens",
            "LensID": "LensID",
            "LensSerialNumber": "LensSerialNumber",
            "SerialNumber": "SerialNumber",
        },
        read=read_xmp_aux_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_acdsee_regions",
        group="XMP-acdsee-rs",
        table_name="Image::ExifTool::XMP::ACDSeeRegions",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            lazy_functions=(
                (
                    "exifmodern.formats.xmp.structs.acdsee_regions",
                    "acdsee_regions_readback_tag_ids",
                ),
            )
        ),
        read=read_xmp_acdsee_region_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_dc",
        group="XMP-dc",
        table_name="Image::ExifTool::XMP::dc",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids={
            "Creator": "creator",
            "Description": "description",
            "Rights": "rights",
            "Subject": "subject",
            "Title": "title",
        },
        read=read_xmp_dc_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_exif",
        group="XMP-exif",
        table_name="Image::ExifTool::XMP::exif",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            ("BrightnessValue", "BrightnessValue"),
            ("CompressedBitsPerPixel", "CompressedBitsPerPixel"),
            ("DateTimeDigitized", "DateTimeDigitized"),
            ("DateTimeOriginal", "DateTimeOriginal"),
            ("ExifImageWidth", "PixelXDimension"),
            lazy_functions=(
                ("exifmodern.formats.xmp.structs.exif_struct", "exif_struct_readback_tag_ids"),
            ),
        ),
        read=read_xmp_exif_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_exif_ex",
        group="XMP-exifEX",
        table_name="Image::ExifTool::XMP::exifEX",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            lazy_functions=(
                (
                    "exifmodern.formats.xmp.structs.exif_extended",
                    "exif_extended_readback_tag_ids",
                ),
            )
        ),
        read=read_xmp_exif_ex_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_hdrgm",
        group="XMP-hdrgm",
        table_name="Image::ExifTool::XMP::hdrgm",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids={
            "GainMapMax": "GainMapMax",
            "GainMapMin": "GainMapMin",
        },
        read=read_xmp_hdrgm_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_ics",
        group="XMP-ics",
        table_name="Image::ExifTool::XMP::ics",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            lazy_functions=(("exifmodern.formats.xmp.structs.ics", "ics_readback_tag_ids"),)
        ),
        read=read_xmp_ics_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_iptc_core",
        group="XMP-iptcCore",
        table_name="Image::ExifTool::XMP::iptcCore",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            lazy_functions=(("exifmodern.formats.xmp.structs.iptc", "iptc_core_readback_tag_ids"),)
        ),
        read=read_xmp_iptc_core_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_iptc_ext",
        group="XMP-iptcExt",
        table_name="Image::ExifTool::XMP::iptcExt",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            lazy_functions=(("exifmodern.formats.xmp.structs.iptc", "iptc_ext_readback_tag_ids"),)
        ),
        read=read_xmp_iptc_ext_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_pdf",
        group="XMP-pdf",
        table_name="Image::ExifTool::XMP::pdf",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids={
            "Author": "Author",
            "CreationDate": "CreationDate",
            "Keywords": "Keywords",
            "Marked": "Marked",
            "ModDate": "ModDate",
            "PDFVersion": "PDFVersion",
        },
        read=read_xmp_pdf_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_photoshop",
        group="XMP-photoshop",
        table_name="Image::ExifTool::XMP::photoshop",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            ("AuthorsPosition", "AuthorsPosition"),
            ("CaptionWriter", "CaptionWriter"),
            ("Category", "Category"),
            ("City", "City"),
            ("Country", "Country"),
            ("Credit", "Credit"),
            ("DateCreated", "DateCreated"),
            ("Headline", "Headline"),
            ("Instructions", "Instructions"),
            ("Source", "Source"),
            ("State", "State"),
            ("SupplementalCategories", "SupplementalCategories"),
            ("TransmissionReference", "TransmissionReference"),
            ("Urgency", "Urgency"),
            lazy_functions=(
                ("exifmodern.formats.xmp.structs.photoshop", "photoshop_readback_tag_ids"),
            ),
        ),
        read=read_xmp_photoshop_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_prism",
        group="XMP-prism",
        table_name="Image::ExifTool::XMP::prism",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            lazy_functions=(("exifmodern.formats.xmp.structs.prism", "prism_readback_tag_ids"),)
        ),
        read=read_xmp_prism_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_tiff",
        group="XMP-tiff",
        table_name="Image::ExifTool::XMP::tiff",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids={
            "Artist": "Artist",
            "BitsPerSample": "BitsPerSample",
            "DateTime": "DateTime",
            "ImageDescription": "ImageDescription",
            "ImageWidth": "ImageWidth",
            "XResolution": "XResolution",
        },
        read=read_xmp_tiff_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_bj",
        group="XMP-xmpBJ",
        table_name="Image::ExifTool::XMP::xmpBJ",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            lazy_functions=(("exifmodern.formats.xmp.structs.job_ref", "job_ref_readback_tag_ids"),)
        ),
        read=read_xmp_bj_tags,
        runtime_dynamic_tag_names=("JobRefId", "JobRefName", "JobRefUrl"),
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_creator_atom",
        group="XMP-creatorAtom",
        table_name="Image::ExifTool::XMP::creatorAtom",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            lazy_functions=(
                (
                    "exifmodern.formats.xmp.structs.creator_atom",
                    "creator_atom_readback_tag_ids",
                ),
            )
        ),
        read=read_xmp_creator_atom_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_dm",
        group="XMP-xmpDM",
        table_name="Image::ExifTool::XMP::xmpDM",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            ("Album", "album"),
            ("AudioModDate", "audioModDate"),
            ("AudioSampleRate", "audioSampleRate"),
            ("FileDataRate", "fileDataRate"),
            ("MetadataModDate", "metadataModDate"),
            ("VideoModDate", "videoModDate"),
            lazy_functions=(
                ("exifmodern.formats.xmp.structs.dynamic_media", "dynamic_media_readback_tag_ids"),
            ),
        ),
        read=read_xmp_dm_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_mm",
        group="XMP-xmpMM",
        table_name="Image::ExifTool::XMP::xmpMM",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            ("DocumentID", "DocumentID"),
            ("SaveID", "SaveID"),
            lazy_functions=(
                ("exifmodern.formats.xmp.structs.manifest_item", "manifest_item_readback_tag_ids"),
                (
                    "exifmodern.formats.xmp.structs.media_management",
                    "media_management_readback_tag_ids",
                ),
                ("exifmodern.formats.xmp.structs.pantry_item", "pantry_item_readback_tag_ids"),
                (
                    "exifmodern.formats.xmp.structs.resource_event",
                    "resource_event_readback_tag_ids",
                ),
                ("exifmodern.formats.xmp.structs.resource_ref", "resource_ref_readback_tag_ids"),
            ),
        ),
        read=read_xmp_mm_tags,
        runtime_dynamic_tag_names=(
            "ManifestLinkForm",
            "ManifestPlacedResolutionUnit",
            "ManifestPlacedXResolution",
            "ManifestPlacedYResolution",
            "ManifestReferenceAlternatePaths",
            "ManifestReferenceDocumentID",
            "ManifestReferenceFilePath",
            "ManifestReferenceFromPart",
            "ManifestReferenceInstanceID",
            "ManifestReferenceLastModifyDate",
            "ManifestReferenceManager",
            "ManifestReferenceManagerVariant",
            "ManifestReferenceManageTo",
            "ManifestReferenceManageUI",
            "ManifestReferenceMaskMarkers",
            "ManifestReferencePartMapping",
            "ManifestReferenceRenditionClass",
            "ManifestReferenceRenditionParams",
            "ManifestReferenceToPart",
            "ManifestReferenceVersionID",
            "PantryInstanceID",
        ),
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_rights",
        group="XMP-xmpRights",
        table_name="Image::ExifTool::XMP::xmpRights",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids={
            "Marked": "Marked",
            "UsageTerms": "UsageTerms",
            "WebStatement": "WebStatement",
        },
        read=read_xmp_rights_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="xmp_tpg",
        group="XMP-xmpTPg",
        table_name="Image::ExifTool::XMP::xmpTPg",
        source="jpeg-app1-xmp",
        missing_message_prefix="No JPEG XMP APP1 segment found:",
        tag_ids=_tag_ids(
            ("HasVisibleTransparency", "HasVisibleTransparency"),
            ("NPages", "NPages"),
            ("PlateNames", "PlateNames"),
            lazy_functions=(
                ("exifmodern.formats.xmp.structs.paged_text", "paged_text_readback_tag_ids"),
            ),
        ),
        read=read_xmp_tpg_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="icc_header",
        group="ICC-header",
        table_name="Image::ExifTool::ICC_Profile::Header",
        source="jpeg-app2-icc-profile",
        missing_message_prefix="No JPEG ICC APP2 segment found:",
        tag_ids={
            "ProfileCMMType": "4",
            "ProfileVersion": "8",
            "ProfileClass": "12",
            "ColorSpaceData": "16",
            "ProfileConnectionSpace": "20",
            "ProfileDateTime": "24",
            "ProfileFileSignature": "36",
            "PrimaryPlatform": "40",
            "CMMFlags": "44",
            "DeviceManufacturer": "48",
            "DeviceModel": "52",
            "DeviceAttributes": "56",
            "RenderingIntent": "64",
            "ConnectionSpaceIlluminant": "68",
            "ProfileCreator": "80",
            "ProfileID": "84",
        },
        read=read_icc_header_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="icc_profile",
        group="ICC_Profile",
        table_name="Image::ExifTool::ICC_Profile::Main",
        source="jpeg-app2-icc-profile",
        missing_message_prefix="No JPEG ICC APP2 segment found:",
        tag_ids={
            "ProfileCopyright": "cprt",
            "ProfileDescription": "desc",
            "MediaWhitePoint": "wtpt",
            "MediaBlackPoint": "bkpt",
            "RedTRC": "rTRC",
            "GreenTRC": "gTRC",
            "BlueTRC": "bTRC",
            "RedMatrixColumn": "rXYZ",
            "GreenMatrixColumn": "gXYZ",
            "BlueMatrixColumn": "bXYZ",
            "DeviceMfgDesc": "dmnd",
            "DeviceModelDesc": "dmdd",
            "ViewingCondDesc": "vued",
            "Luminance": "lumi",
            "Technology": "tech",
            "ViewingCondIlluminant": "8",
            "ViewingCondSurround": "20",
            "ViewingCondIlluminantType": "32",
            "MeasurementObserver": "8",
            "MeasurementBacking": "12",
            "MeasurementGeometry": "24",
            "MeasurementFlare": "28",
            "MeasurementIlluminant": "32",
        },
        read=read_icc_profile_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="mpf0",
        group="MPF0",
        table_name="Image::ExifTool::MPF::Main",
        source="jpeg-app2-mpf",
        missing_message_prefix="No JPEG MPF APP2 segment found:",
        tag_ids={
            "MPFVersion": "0xB000",
            "NumberOfImages": "0xB001",
        },
        read=read_mpf0_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="mpimage1",
        group="MPImage1",
        table_name="Image::ExifTool::MPF::MPImage",
        source="jpeg-app2-mpf",
        missing_message_prefix="No JPEG MPF APP2 segment found:",
        tag_ids=MPIMAGE_TAG_IDS,
        read=read_mpimage1_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="mpimage2",
        group="MPImage2",
        table_name="Image::ExifTool::MPF::MPImage",
        source="jpeg-app2-mpf",
        missing_message_prefix="No JPEG MPF APP2 segment found:",
        tag_ids=mpimage_tag_ids_with_preview(),
        read=read_mpimage2_tags,
        runtime_dynamic_tag_names=("PreviewImage",),
    ),
    JpegAppSegmentReader(
        inspection_key="avi1",
        group="AVI1",
        table_name="Image::ExifTool::JPEG::AVI1",
        source="jpeg-app0-avi1",
        missing_message_prefix="No JPEG AVI1 APP0 segment found:",
        tag_ids={
            "InterleavedField": "0x0000",
        },
        read=read_avi1_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="spiff",
        group="SPIFF",
        table_name="Image::ExifTool::JPEG::SPIFF",
        source="jpeg-app8-spiff",
        missing_message_prefix="No JPEG SPIFF APP8 segment found:",
        tag_ids={
            "SPIFFVersion": "0x0000",
            "ProfileID": "0x0002",
            "ColorComponents": "0x0003",
            "ImageHeight": "0x0006",
            "ImageWidth": "0x000A",
            "ColorSpace": "0x000E",
            "BitsPerSample": "0x000F",
            "Compression": "0x0010",
            "ResolutionUnit": "0x0011",
            "YResolution": "0x0012",
            "XResolution": "0x0016",
        },
        read=read_spiff_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="printim",
        group="PrintIM",
        table_name="Image::ExifTool::PrintIM::Main",
        source="jpeg-app6-eppim-printim",
        missing_message_prefix="No JPEG EPPIM APP6 segment found:",
        tag_ids={
            "PrintIMVersion": "PrintIMVersion",
        },
        read=read_eppim_printim_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="nitf_app6",
        group="NITF",
        table_name="Image::ExifTool::JPEG::NITF",
        source="jpeg-app6-nitf",
        missing_message_prefix="No NITF APP6 segment found:",
        tag_ids={
            "NITFVersion": "0",
            "ImageFormat": "2",
            "BlocksPerRow": "3",
            "BlocksPerColumn": "5",
            "ImageColor": "7",
            "BitDepth": "8",
            "ImageClass": "9",
            "JPEGProcess": "10",
            "Quality": "11",
            "StreamColor": "12",
            "StreamBitDepth": "13",
            "Flags": "14",
        },
        read=read_nitf_app6_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="ricoh_rmeta",
        group="RMETA",
        table_name="Image::ExifTool::Ricoh::RMETA",
        source="jpeg-app5-ricoh-rmeta",
        missing_message_prefix="No Ricoh RMETA APP5 segment found:",
        tag_ids={
            "SignType": "Sign type",
            "Location": "Location",
            "Lit": "Lit",
            "Condition": "Condition",
            "Azimuth": "Azimuth",
        },
        read=read_ricoh_rmeta_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="qualcomm_app7",
        group="Qualcomm",
        table_name="Image::ExifTool::Qualcomm::Main",
        source="jpeg-app7-qualcomm",
        missing_message_prefix="No Qualcomm APP7 Camera Attributes segment found:",
        tag_ids={
            "AECCurrentSensorLuma": "aec_current_sensor_luma",
            "AFPosition": "af_position",
            "AECCurrentExpIndex": "aec_current_exp_index",
            "AWBSampleDecision": "awb_sample_decision",
            "ASF5Enable": "asf5_enable",
            "ASF5FilterMode": "asf5_filter_mode",
            "ASF5ExposureIndex1": "asf5_exposure_index_1",
            "ASF5ExposureIndex2": "asf5_exposure_index_2",
            "ASF5MaxExposureIndex": "asf5_max_exposure_index",
        },
        read=read_qualcomm_app7_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="app10_comment",
        group="File",
        table_name="Image::ExifTool::JPEG::Main",
        source="jpeg-app10-comment",
        missing_message_prefix="No JPEG APP10 Unicode comment segment found:",
        tag_ids={
            "Comment": "APP10.Comment",
        },
        read=read_app10_comment_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="hdr_gain_info",
        group="APP10",
        table_name="Image::ExifTool::JPEG::HDRGainInfo",
        source="jpeg-app10-hdr-gain-info",
        missing_message_prefix="No JPEG HDRGainInfo APP10 segment found:",
        tag_ids={
            "HDRGainCurveSize": "6",
            "HDRGainCurve": "10",
        },
        read=read_jpeg_hdr_gain_info_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="ducky",
        group="Ducky",
        table_name="Image::ExifTool::APP12::Ducky",
        source="jpeg-app12-ducky",
        missing_message_prefix="No JPEG Ducky APP12 segment found:",
        tag_ids={
            "Quality": "0x0001",
            "Copyright": "0x0003",
        },
        read=read_ducky_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="picture_info",
        group="PictureInfo",
        table_name="Image::ExifTool::APP12::PictureInfo",
        source="jpeg-app12-picture-info",
        missing_message_prefix="No JPEG PictureInfo APP12 segment found:",
        tag_ids={
            "DateTimeOriginal": "TimeDate",
            "ExposureTime": "Shutter",
            "Flash": "Flash",
            "Resolution": "Resolution",
            "Protect": "Protect",
            "ContTake": "ContTake",
            "ImageSize": "ImageSize",
            "ColorMode": "ColorMode",
            "FNumber": "FNumber",
            "Zoom": "Zoom",
            "Macro": "Macro",
            "LightS": "LightS",
            "ExposureCompensation": "ExpBias",
            "CameraType": "Type",
            "SerialNumber": "Serial#",
            "Version": "Version",
            "ID": "ID",
            "PicLen": "PicLen",
            "ThmLen": "ThmLen",
            "TagQ": "Q",
            "TagR": "R",
            "TagB": "B",
            "S0": "s0",
            "T0": "T0",
        },
        read=read_picture_info_tags,
        runtime_dynamic_tag_names=("PicLen", "ThmLen", "TagQ", "TagR", "TagB", "S0", "T0"),
    ),
    JpegAppSegmentReader(
        inspection_key="adobe_cm",
        group="AdobeCM",
        table_name="Image::ExifTool::JPEG::AdobeCM",
        source="jpeg-app13-adobe-cm",
        missing_message_prefix="No JPEG AdobeCM APP13 segment found:",
        tag_ids={
            "AdobeCMType": "0x0000",
        },
        read=read_adobe_cm_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="kodak_metaifd",
        group="MetaIFD",
        table_name="Image::ExifTool::Kodak::Meta",
        source="jpeg-app3-kodak-meta",
        missing_message_prefix="No Kodak APP3 Meta segment found:",
        tag_ids={
            "FilmProductCode": "0xC350",
            "ImageSourceEK": "0xC351",
            "CaptureConditionsPAR": "0xC352",
            "CameraOwner": "0xC353",
            "SerialNumber": "0xC354",
            "FrameNumber": "0xC359",
            "FilmCategory": "0xC35A",
            "FilmGencode": "0xC35B",
            "ModelAndVersion": "0xC35C",
            "FilmSize": "0xC35D",
            "SBA_RGBShifts": "0xC35E",
            "SBAInputImageColorspace": "0xC35F",
            "SBAInputImageBitDepth": "0xC360",
            "SBAExposureRecord": "0xC361",
            "UserAdjSBA_RGBShifts": "0xC362",
            "ImageRotationStatus": "0xC363",
            "RollGuidElements": "0xC364",
            "MetadataNumber": "0xC365",
        },
        read=read_kodak_meta_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="iptc_app13",
        group="IPTC",
        table_name="Image::ExifTool::IPTC::ApplicationRecord",
        source="jpeg-app13-photoshop-iptc",
        missing_message_prefix="No JPEG Photoshop APP13 segment found:",
        tag_ids={
            "ApplicationRecordVersion": "0x0000",
            "Caption-Abstract": "0x0078",
            "Writer-Editor": "0x007A",
            "Headline": "0x0069",
            "SpecialInstructions": "0x0028",
            "By-line": "0x0050",
            "By-lineTitle": "0x0055",
            "Credit": "0x006E",
            "ObjectName": "0x0005",
            "DateCreated": "0x0037",
            "City": "0x005A",
            "Province-State": "0x005F",
            "Country-PrimaryLocationName": "0x0065",
            "OriginalTransmissionReference": "0x0067",
            "Category": "0x000F",
            "SupplementalCategories": "0x0014",
            "CopyrightNotice": "0x0074",
            "Urgency": "0x000A",
            "Source": "0x0073",
            "Keywords": "0x0019",
        },
        read=read_iptc_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="current_iptc_digest",
        group="File",
        table_name="Image::ExifTool::Extra",
        source="jpeg-app13-photoshop-iptc",
        missing_message_prefix="No JPEG Photoshop APP13 segment found:",
        tag_ids={
            "CurrentIPTCDigest": "CurrentIPTCDigest",
        },
        read=read_current_iptc_digest_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="iptc_trailing",
        group="IPTC2",
        table_name="Image::ExifTool::IPTC::ApplicationRecord",
        source="jpeg-trailer-iptc",
        missing_message_prefix="No JPEG trailing IPTC data found:",
        tag_ids={
            "ApplicationRecordVersion": "0x0000",
            "EditStatus": "0x0007",
            "Urgency": "0x000A",
            "Category": "0x000F",
            "SpecialInstructions": "0x0028",
            "ObjectCycle": "0x004B",
            "OriginalTransmissionReference": "0x0067",
            "Caption-Abstract": "0x0078",
            "ObjectPreviewFileFormat": "0x00C8",
            "ObjectPreviewFileVersion": "0x00C9",
            "ObjectPreviewData": "0x00CA",
            "DocumentNotes": "0x00E6",
        },
        read=read_trailing_iptc_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="iptc_afcp",
        group="IPTC2",
        table_name="Image::ExifTool::IPTC::ApplicationRecord",
        source="jpeg-trailer-afcp-iptc",
        missing_message_prefix="No JPEG AFCP IPTC trailer found:",
        tag_ids={
            "ApplicationRecordVersion": "0x0000",
            "Caption-Abstract": "0x0078",
            "Writer-Editor": "0x007A",
            "Headline": "0x0069",
            "SpecialInstructions": "0x0028",
            "By-line": "0x0050",
            "By-lineTitle": "0x0055",
            "Credit": "0x006E",
            "ObjectName": "0x0005",
            "DateCreated": "0x0037",
            "City": "0x005A",
            "Province-State": "0x005F",
            "Country-PrimaryLocationName": "0x0065",
            "OriginalTransmissionReference": "0x0067",
            "Category": "0x000F",
            "SupplementalCategories": "0x0014",
            "CopyrightNotice": "0x0074",
            "Urgency": "0x000A",
            "Source": "0x0073",
            "Keywords": "0x0019",
        },
        read=read_afcp_iptc_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="photo_mechanic",
        group="PhotoMechanic",
        table_name="Image::ExifTool::PhotoMechanic::SoftEdit",
        source="jpeg-trailer-photomechanic",
        missing_message_prefix="No JPEG PhotoMechanic trailer found:",
        tag_ids={
            "Rotation": "216",
            "CropLeft": "217",
            "CropTop": "218",
            "CropRight": "219",
            "CropBottom": "220",
            "Tagged": "221",
            "ColorClass": "222",
        },
        read=read_photo_mechanic_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="canon_vrd",
        group="CanonVRD",
        table_name="Image::ExifTool::CanonVRD::Ver1",
        source="jpeg-trailer-canon-vrd",
        missing_message_prefix="No CanonVRD trailer found",
        tag_ids={
            "VRDVersion": "0x002",
            "WBAdjRGGBLevels": "0x006",
            "WhiteBalanceAdj": "0x018",
            "WBAdjColorTemp": "0x01a",
            "WBFineTuneActive": "0x024",
            "WBFineTuneSaturation": "0x028",
            "WBFineTuneTone": "0x02c",
            "RawColorAdj": "0x02e",
            "RawCustomSaturation": "0x030",
            "RawCustomTone": "0x034",
            "RawBrightnessAdj": "0x038",
            "ToneCurveProperty": "0x03c",
            "DynamicRangeMin": "0x07a",
            "DynamicRangeMax": "0x07c",
            "ToneCurveActive": "0x110",
            "ToneCurveMode": "0x113",
            "BrightnessAdj": "0x114",
            "ContrastAdj": "0x115",
            "SaturationAdj": "0x116",
            "ColorToneAdj": "0x11e",
            "LuminanceCurvePoints": "0x126",
            "LuminanceCurveLimits": "0x150",
            "ToneCurveInterpolation": "0x159",
            "RedCurvePoints": "0x160",
            "RedCurveLimits": "0x18a",
            "GreenCurvePoints": "0x19a",
            "GreenCurveLimits": "0x1c4",
            "BlueCurvePoints": "0x1d4",
            "BlueCurveLimits": "0x1fe",
            "RGBCurvePoints": "0x20e",
            "RGBCurveLimits": "0x238",
            "CropActive": "0x244",
            "CropLeft": "0x246",
            "CropTop": "0x248",
            "CropWidth": "0x24a",
            "CropHeight": "0x24c",
            "SharpnessAdj": "0x25a",
            "CropAspectRatio": "0x260",
            "ConstrainedCropWidth": "0x262",
            "ConstrainedCropHeight": "0x266",
            "CheckMark": "0x26a",
            "Rotation": "0x26e",
            "WorkColorSpace": "0x270",
        },
        read=read_canon_vrd_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="fotostation",
        group="FotoStation",
        table_name="Image::ExifTool::FotoStation::SoftEdit",
        source="jpeg-trailer-fotostation",
        missing_message_prefix="No JPEG FotoStation trailer found:",
        tag_ids={
            "OriginalImageWidth": "0",
            "OriginalImageHeight": "1",
            "ColorPlanes": "2",
            "XYResolution": "3",
            "Rotation": "4",
            "CropLeft": "6",
            "CropTop": "7",
            "CropRight": "8",
            "CropBottom": "9",
            "CropRotation": "11",
        },
        read=read_fotostation_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="mie_doc",
        group="MIE-Doc",
        table_name="Image::ExifTool::MIE::Doc",
        source="jpeg-trailer-mie",
        missing_message_prefix="No MIE trailer found",
        tag_ids={
            "Copyright": "Copyright",
        },
        read=read_mie_doc_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="mie_main",
        group="MIE-Main",
        table_name="Image::ExifTool::MIE::Main",
        source="jpeg-trailer-mie",
        missing_message_prefix="No MIE trailer found",
        tag_ids={
            "TrailerSignature": "zmie",
        },
        read=read_mie_main_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="vivo",
        group="Vivo",
        table_name="Image::ExifTool::Trailer::Vivo",
        source="jpeg-trailer-vivo",
        missing_message_prefix="No Vivo trailer",
        tag_ids={
            "JSONInfo": "JSONInfo",
        },
        read=read_vivo_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="samsung_trailer",
        group="Samsung",
        table_name="Image::ExifTool::Samsung::Trailer",
        source="jpeg-trailer-samsung-seft",
        missing_message_prefix="No Samsung SEFT trailer found",
        tag_ids={
            "EmbeddedAudioFileName": "0x0100-name",
            "EmbeddedAudioFile": "0x0100",
        },
        read=read_samsung_trailer_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="photoshop_core",
        group="Photoshop",
        table_name="Image::ExifTool::Photoshop::Main",
        source="jpeg-app13-photoshop-irb",
        missing_message_prefix="No JPEG Photoshop APP13 segment found:",
        tag_ids={
            "IPTCDigest": "0x0425",
            "GlobalAngle": "0x040D",
            "GlobalAltitude": "0x0419",
            "CopyrightFlag": "0x040A",
            "URL": "0x040B",
            "URL_List": "0x041E",
        },
        read=read_photoshop_core_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="photoshop_resolution",
        group="Photoshop",
        table_name="Image::ExifTool::Photoshop::Resolution",
        source="jpeg-app13-photoshop-irb",
        missing_message_prefix="No JPEG Photoshop APP13 segment found:",
        tag_ids={
            "XResolution": "0x0000",
            "DisplayedUnitsX": "0x0002",
            "YResolution": "0x0004",
            "DisplayedUnitsY": "0x0006",
        },
        read=read_photoshop_resolution_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="photoshop_print_scale",
        group="Photoshop",
        table_name="Image::ExifTool::Photoshop::PrintScaleInfo",
        source="jpeg-app13-photoshop-irb",
        missing_message_prefix="No JPEG Photoshop APP13 segment found:",
        tag_ids={
            "PrintStyle": "0x0000",
            "PrintPosition": "0x0002",
            "PrintScale": "0x000A",
        },
        read=read_photoshop_print_scale_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="photoshop_slice",
        group="Photoshop",
        table_name="Image::ExifTool::Photoshop::SliceInfo",
        source="jpeg-app13-photoshop-irb",
        missing_message_prefix="No JPEG Photoshop APP13 segment found:",
        tag_ids={
            "SlicesGroupName": "0x0014",
            "NumSlices": "0x0018",
        },
        read=read_photoshop_slice_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="photoshop_version",
        group="Photoshop",
        table_name="Image::ExifTool::Photoshop::VersionInfo",
        source="jpeg-app13-photoshop-irb",
        missing_message_prefix="No JPEG Photoshop APP13 segment found:",
        tag_ids={
            "HasRealMergedData": "0x0004",
            "WriterName": "0x0005",
            "ReaderName": "0x0009",
        },
        read=read_photoshop_version_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="photoshop_quality",
        group="Photoshop",
        table_name="Image::ExifTool::Photoshop::JPEG_Quality",
        source="jpeg-app13-photoshop-irb",
        missing_message_prefix="No JPEG Photoshop APP13 segment found:",
        tag_ids={
            "PhotoshopQuality": "0x0000",
            "PhotoshopFormat": "0x0001",
        },
        read=read_photoshop_quality_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="adobe",
        group="Adobe",
        table_name="Image::ExifTool::JPEG::Adobe",
        source="jpeg-app14-adobe",
        missing_message_prefix="No JPEG Adobe APP14 segment found:",
        tag_ids={
            "DCTEncodeVersion": "0x0000",
            "APP14Flags0": "0x0001",
            "APP14Flags1": "0x0002",
            "ColorTransform": "0x0003",
        },
        read=read_adobe_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="graphconv",
        group="GraphConv",
        table_name="Image::ExifTool::JPEG::GraphConv",
        source="jpeg-app15-graphconv",
        missing_message_prefix="No JPEG GraphicConverter APP15 segment found:",
        tag_ids={
            "Quality": "Q",
        },
        read=read_graphconv_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="jpeg_hdr",
        group="JPEG-HDR",
        table_name="Image::ExifTool::JPEG::HDR",
        source="jpeg-app11-hdr",
        missing_message_prefix="No JPEG-HDR APP11 segment found:",
        tag_ids={
            "JPEG-HDRVersion": "ver",
            "Ln0": "ln0",
            "Ln1": "ln1",
            "S2n": "s2n",
            "Alpha": "alp",
            "Beta": "bet",
            "CorrectionMethod": "cor",
            "RatioImage": "RatioImage",
        },
        read=read_jpeg_hdr_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="jumbf",
        group="JUMBF",
        table_name="Image::ExifTool::Jpeg2000::JUMD",
        source="jpeg-app11-jumbf",
        missing_message_prefix="No JPEG JUMBF APP11 segment found:",
        tag_ids={
            "JUMDType": "type",
            "JUMDLabel": "label",
        },
        read=read_jumbf_tags,
    ),
    JpegAppSegmentReader(
        inspection_key="jumbf_json",
        group="JSON",
        table_name="Image::ExifTool::JSON::Main",
        source="jpeg-app11-jumbf-json",
        missing_message_prefix="No JPEG JUMBF APP11 segment found:",
        tag_ids={
            "Title": "Title",
            "Location": "Location",
            "Copyright": "Copyright",
        },
        read=read_jumbf_json_tags,
        runtime_dynamic_tag_names=("Title", "Location", "Copyright"),
    ),
    JpegAppSegmentReader(
        inspection_key="media_jukebox",
        group="MediaJukebox",
        table_name="Image::ExifTool::JPEG::MediaJukebox",
        source="jpeg-app9-media-jukebox",
        missing_message_prefix="No Media Jukebox APP9 segment found:",
        tag_ids={
            "Tool_Name": "Tool_Name",
            "Tool_Version": "Tool_Version",
            "People": "People",
            "Places": "Places",
            "Date": "Date",
            "Album": "Album",
            "Name": "Name",
        },
        read=read_media_jukebox_tags,
    ),
)
