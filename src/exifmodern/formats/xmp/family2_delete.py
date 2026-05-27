"""XMP family-2 group deletion plan primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type XmpFamily2DeleteTarget = Literal["Image", "Camera"]

DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
EXIF_NAMESPACE = "http://ns.adobe.com/exif/1.0/"
PHOTOSHOP_NAMESPACE = "http://ns.adobe.com/photoshop/1.0/"
TIFF_NAMESPACE = "http://ns.adobe.com/tiff/1.0/"
XMP_NAMESPACE = "http://ns.adobe.com/xap/1.0/"

XMP_FAMILY2_WRITER_TEST_SOURCE_ID = "xmp.family2_delete.writer_test_52"
XMP_FAMILY2_DELETE_SOURCE_ID = "xmp.family2_delete.del_group2"
XMP_FAMILY2_ROUTING_SOURCE_ID = "xmp.family2_delete.set_new_value_routing"
XMP_FAMILY2_XMP_TABLE_SOURCE_ID = "xmp.family2_delete.xmp_tables"


@dataclass(frozen=True)
class XmpQualifiedProperty:
    namespace_uri: str
    local_name: str


@dataclass(frozen=True)
class XmpFamily2DeletePlan:
    targets: tuple[XmpFamily2DeleteTarget, ...]
    properties: frozenset[XmpQualifiedProperty]
    source_reference_ids: tuple[str, ...]


def build_xmp_family2_delete_plan(
    targets: tuple[XmpFamily2DeleteTarget, ...],
) -> XmpFamily2DeletePlan:
    unique_targets = tuple(dict.fromkeys(targets))
    properties: set[XmpQualifiedProperty] = set()
    for target in unique_targets:
        properties.update(xmp_family2_properties(target))
    return XmpFamily2DeletePlan(
        targets=unique_targets,
        properties=frozenset(properties),
        source_reference_ids=(
            XMP_FAMILY2_WRITER_TEST_SOURCE_ID,
            XMP_FAMILY2_DELETE_SOURCE_ID,
            XMP_FAMILY2_ROUTING_SOURCE_ID,
            XMP_FAMILY2_XMP_TABLE_SOURCE_ID,
        ),
    )


def xmp_family2_delete_target(value: str) -> XmpFamily2DeleteTarget:
    if value == "Image":
        return "Image"
    if value == "Camera":
        return "Camera"
    raise ValueError("XMP family-2 delete target must be Image or Camera.")


def xmp_family2_properties(
    target: XmpFamily2DeleteTarget,
) -> frozenset[XmpQualifiedProperty]:
    if target == "Image":
        return XMP_FAMILY2_IMAGE_PROPERTIES
    return XMP_FAMILY2_CAMERA_PROPERTIES


def xmp_property(namespace_uri: str, local_name: str) -> XmpQualifiedProperty:
    return XmpQualifiedProperty(namespace_uri=namespace_uri, local_name=local_name)


XMP_FAMILY2_IMAGE_PROPERTIES = frozenset(
    (
        xmp_property(DC_NAMESPACE, "description"),
        xmp_property(DC_NAMESPACE, "format"),
        xmp_property(DC_NAMESPACE, "identifier"),
        xmp_property(DC_NAMESPACE, "subject"),
        xmp_property(DC_NAMESPACE, "title"),
        xmp_property(DC_NAMESPACE, "type"),
        xmp_property(EXIF_NAMESPACE, "ColorSpace"),
        xmp_property(EXIF_NAMESPACE, "ComponentsConfiguration"),
        xmp_property(EXIF_NAMESPACE, "CompressedBitsPerPixel"),
        xmp_property(EXIF_NAMESPACE, "ExifVersion"),
        xmp_property(EXIF_NAMESPACE, "FlashpixVersion"),
        xmp_property(EXIF_NAMESPACE, "MakerNote"),
        xmp_property(EXIF_NAMESPACE, "NativeDigest"),
        xmp_property(EXIF_NAMESPACE, "PixelXDimension"),
        xmp_property(EXIF_NAMESPACE, "PixelYDimension"),
        xmp_property(EXIF_NAMESPACE, "RelatedSoundFile"),
        xmp_property(EXIF_NAMESPACE, "UserComment"),
        xmp_property(PHOTOSHOP_NAMESPACE, "Category"),
        xmp_property(PHOTOSHOP_NAMESPACE, "ColorMode"),
        xmp_property(PHOTOSHOP_NAMESPACE, "DocumentAncestors"),
        xmp_property(PHOTOSHOP_NAMESPACE, "Headline"),
        xmp_property(PHOTOSHOP_NAMESPACE, "History"),
        xmp_property(PHOTOSHOP_NAMESPACE, "ICCProfile"),
        xmp_property(PHOTOSHOP_NAMESPACE, "Instructions"),
        xmp_property(PHOTOSHOP_NAMESPACE, "LegacyIPTCDigest"),
        xmp_property(PHOTOSHOP_NAMESPACE, "SidecarForExtension"),
        xmp_property(PHOTOSHOP_NAMESPACE, "SupplementalCategories"),
        xmp_property(PHOTOSHOP_NAMESPACE, "TextLayers"),
        xmp_property(TIFF_NAMESPACE, "BitsPerSample"),
        xmp_property(TIFF_NAMESPACE, "Compression"),
        xmp_property(TIFF_NAMESPACE, "ImageDescription"),
        xmp_property(TIFF_NAMESPACE, "ImageLength"),
        xmp_property(TIFF_NAMESPACE, "ImageWidth"),
        xmp_property(TIFF_NAMESPACE, "NativeDigest"),
        xmp_property(TIFF_NAMESPACE, "Orientation"),
        xmp_property(TIFF_NAMESPACE, "PhotometricInterpretation"),
        xmp_property(TIFF_NAMESPACE, "PlanarConfiguration"),
        xmp_property(TIFF_NAMESPACE, "PrimaryChromaticities"),
        xmp_property(TIFF_NAMESPACE, "ReferenceBlackWhite"),
        xmp_property(TIFF_NAMESPACE, "ResolutionUnit"),
        xmp_property(TIFF_NAMESPACE, "SamplesPerPixel"),
        xmp_property(TIFF_NAMESPACE, "TransferFunction"),
        xmp_property(TIFF_NAMESPACE, "WhitePoint"),
        xmp_property(TIFF_NAMESPACE, "XResolution"),
        xmp_property(TIFF_NAMESPACE, "YCbCrCoefficients"),
        xmp_property(TIFF_NAMESPACE, "YCbCrPositioning"),
        xmp_property(TIFF_NAMESPACE, "YCbCrSubSampling"),
        xmp_property(TIFF_NAMESPACE, "YResolution"),
        xmp_property(XMP_NAMESPACE, "Advisory"),
        xmp_property(XMP_NAMESPACE, "BaseURL"),
        xmp_property(XMP_NAMESPACE, "CreatorTool"),
        xmp_property(XMP_NAMESPACE, "Identifier"),
        xmp_property(XMP_NAMESPACE, "Label"),
        xmp_property(XMP_NAMESPACE, "Nickname"),
        xmp_property(XMP_NAMESPACE, "Rating"),
        xmp_property(XMP_NAMESPACE, "RatingPercent"),
        xmp_property(XMP_NAMESPACE, "Thumbnails"),
    )
)

XMP_FAMILY2_CAMERA_PROPERTIES = frozenset(
    (
        xmp_property(EXIF_NAMESPACE, "ApertureValue"),
        xmp_property(EXIF_NAMESPACE, "BrightnessValue"),
        xmp_property(EXIF_NAMESPACE, "CFAPattern"),
        xmp_property(EXIF_NAMESPACE, "Contrast"),
        xmp_property(EXIF_NAMESPACE, "CustomRendered"),
        xmp_property(EXIF_NAMESPACE, "DeviceSettingDescription"),
        xmp_property(EXIF_NAMESPACE, "DigitalZoomRatio"),
        xmp_property(EXIF_NAMESPACE, "ExposureBiasValue"),
        xmp_property(EXIF_NAMESPACE, "ExposureIndex"),
        xmp_property(EXIF_NAMESPACE, "ExposureMode"),
        xmp_property(EXIF_NAMESPACE, "ExposureProgram"),
        xmp_property(EXIF_NAMESPACE, "ExposureTime"),
        xmp_property(EXIF_NAMESPACE, "FNumber"),
        xmp_property(EXIF_NAMESPACE, "FileSource"),
        xmp_property(EXIF_NAMESPACE, "Flash"),
        xmp_property(EXIF_NAMESPACE, "FlashEnergy"),
        xmp_property(EXIF_NAMESPACE, "FocalLength"),
        xmp_property(EXIF_NAMESPACE, "FocalLengthIn35mmFilm"),
        xmp_property(EXIF_NAMESPACE, "FocalPlaneResolutionUnit"),
        xmp_property(EXIF_NAMESPACE, "FocalPlaneXResolution"),
        xmp_property(EXIF_NAMESPACE, "FocalPlaneYResolution"),
        xmp_property(EXIF_NAMESPACE, "GainControl"),
        xmp_property(EXIF_NAMESPACE, "ISOSpeedRatings"),
        xmp_property(EXIF_NAMESPACE, "LightSource"),
        xmp_property(EXIF_NAMESPACE, "MaxApertureValue"),
        xmp_property(EXIF_NAMESPACE, "MeteringMode"),
        xmp_property(EXIF_NAMESPACE, "OECF"),
        xmp_property(EXIF_NAMESPACE, "Saturation"),
        xmp_property(EXIF_NAMESPACE, "SceneCaptureType"),
        xmp_property(EXIF_NAMESPACE, "SceneType"),
        xmp_property(EXIF_NAMESPACE, "SensingMethod"),
        xmp_property(EXIF_NAMESPACE, "Sharpness"),
        xmp_property(EXIF_NAMESPACE, "ShutterSpeedValue"),
        xmp_property(EXIF_NAMESPACE, "SpatialFrequencyResponse"),
        xmp_property(EXIF_NAMESPACE, "SpectralSensitivity"),
        xmp_property(EXIF_NAMESPACE, "SubjectArea"),
        xmp_property(EXIF_NAMESPACE, "SubjectDistance"),
        xmp_property(EXIF_NAMESPACE, "SubjectDistanceRange"),
        xmp_property(EXIF_NAMESPACE, "SubjectLocation"),
        xmp_property(EXIF_NAMESPACE, "WhiteBalance"),
        xmp_property(TIFF_NAMESPACE, "Make"),
        xmp_property(TIFF_NAMESPACE, "Model"),
    )
)
