"""Source-grounded Adobe Camera Raw XMP struct adapter metadata."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructListKind,
    XmpSimpleStructParentSpec,
    XmpSimpleStructShape,
    XmpSimpleStructValueKind,
    simple_struct_parent_spec_for_property,
)

CRD_NAMESPACE = "http://ns.adobe.com/camera-raw-defaults/1.0/"
CRS_NAMESPACE = "http://ns.adobe.com/camera-raw-settings/1.0/"

type CameraRawNamespacePrefix = str
type CameraRawGroup = str

CAMERA_RAW_NAMESPACE_URIS: dict[CameraRawNamespacePrefix, str] = {
    "crd": CRD_NAMESPACE,
    "crs": CRS_NAMESPACE,
}
CAMERA_RAW_GROUPS: dict[CameraRawNamespacePrefix, CameraRawGroup] = {
    "crd": "XMP-crd",
    "crs": "XMP-crs",
}


def camera_raw_parent(
    namespace_prefix: CameraRawNamespacePrefix,
    parent_name: str,
    element_name: str,
    *,
    shape: XmpSimpleStructShape = "struct",
    list_kind: XmpSimpleStructListKind | None = None,
) -> XmpSimpleStructParentSpec:
    return XmpSimpleStructParentSpec(
        parent_name=parent_name,
        property_name=f"{CAMERA_RAW_GROUPS[namespace_prefix]}:{parent_name}",
        element_name=element_name,
        group=CAMERA_RAW_GROUPS[namespace_prefix],
        namespace_prefix=namespace_prefix,
        struct_namespace_prefix=namespace_prefix,
        struct_namespace_uri=CAMERA_RAW_NAMESPACE_URIS[namespace_prefix],
        shape=shape,
        list_kind=list_kind,
    )


def namespace_parent_specs(
    namespace_prefix: CameraRawNamespacePrefix,
) -> tuple[XmpSimpleStructParentSpec, ...]:
    return (
        camera_raw_parent(
            namespace_prefix,
            "CircularGradientBasedCorrections",
            "CircularGradientBasedCorrections",
            shape="struct_list",
            list_kind="Seq",
        ),
        camera_raw_parent(
            namespace_prefix,
            "DepthBasedCorrections",
            "DepthBasedCorrections",
            shape="struct_list",
            list_kind="Seq",
        ),
        camera_raw_parent(namespace_prefix, "DepthMapInfo", "DepthMapInfo"),
        camera_raw_parent(
            namespace_prefix,
            "GradientBasedCorrections",
            "GradientBasedCorrections",
            shape="struct_list",
            list_kind="Seq",
        ),
        camera_raw_parent(namespace_prefix, "LensBlur", "LensBlur"),
        camera_raw_parent(namespace_prefix, "Look", "Look"),
        camera_raw_parent(
            namespace_prefix,
            "MaskGroupBasedCorrections",
            "MaskGroupBasedCorrections",
            shape="struct_list",
            list_kind="Seq",
        ),
        camera_raw_parent(
            namespace_prefix,
            "PaintBasedCorrections",
            "PaintBasedCorrections",
            shape="struct_list",
            list_kind="Seq",
        ),
        camera_raw_parent(namespace_prefix, "RangeMask", "RangeMaskMapInfo"),
        camera_raw_parent(
            namespace_prefix,
            "RetouchAreas",
            "RetouchAreas",
            shape="struct_list",
            list_kind="Seq",
        ),
    )


XMP_CAMERA_RAW_PARENT_SPECS: tuple[XmpSimpleStructParentSpec, ...] = (
    *namespace_parent_specs("crd"),
    *namespace_parent_specs("crs"),
)


def field(
    suffix: str,
    field_name: str,
    readback_suffix: str,
    value_kind: XmpSimpleStructValueKind = "text",
    *,
    nested_field_name: str | None = None,
    nested_list_kind: XmpSimpleStructListKind | None = None,
    field_list_kind: XmpSimpleStructListKind | None = None,
) -> XmpSimpleStructFieldSpec:
    return XmpSimpleStructFieldSpec(
        suffix=suffix,
        field_name=field_name,
        readback_suffix=readback_suffix,
        value_kind=value_kind,
        nested_field_name=nested_field_name,
        nested_list_kind=nested_list_kind,
        field_list_kind=field_list_kind,
    )


def prefixed_field(
    prefix: str,
    suffix: str,
    field_name: str,
    value_kind: XmpSimpleStructValueKind = "text",
    *,
    nested_field_name: str | None = None,
    nested_list_kind: XmpSimpleStructListKind | None = None,
    field_list_kind: XmpSimpleStructListKind | None = None,
) -> XmpSimpleStructFieldSpec:
    return field(
        suffix=f"{prefix}{suffix}",
        field_name=field_name,
        readback_suffix=f"{prefix}{suffix}",
        value_kind=value_kind,
        nested_field_name=nested_field_name,
        nested_list_kind=nested_list_kind,
        field_list_kind=field_list_kind,
    )


def parent_fields(
    parent_name: str,
    specs: tuple[XmpSimpleStructFieldSpec, ...],
) -> tuple[str, tuple[XmpSimpleStructFieldSpec, ...]]:
    return (parent_name, specs)


def correction_fields(prefix: str) -> tuple[XmpSimpleStructFieldSpec, ...]:
    return (
        prefixed_field(prefix, "What", "What"),
        prefixed_field(prefix, "Amount", "CorrectionAmount", "real"),
        prefixed_field(prefix, "Active", "CorrectionActive", "boolean"),
        prefixed_field(prefix, "Exposure", "LocalExposure", "real"),
        prefixed_field(prefix, "Saturation", "LocalSaturation", "real"),
        prefixed_field(prefix, "Contrast", "LocalContrast", "real"),
        prefixed_field(prefix, "Clarity", "LocalClarity", "real"),
        prefixed_field(prefix, "Sharpness", "LocalSharpness", "real"),
        prefixed_field(prefix, "Exposure2012", "LocalExposure2012", "real"),
        prefixed_field(prefix, "Contrast2012", "LocalContrast2012", "real"),
        prefixed_field(prefix, "Highlights2012", "LocalHighlights2012", "real"),
        prefixed_field(prefix, "Shadows2012", "LocalShadows2012", "real"),
        prefixed_field(prefix, "Temperature", "LocalTemperature", "real"),
        prefixed_field(prefix, "Tint", "LocalTint", "real"),
        prefixed_field(prefix, "Dehaze", "LocalDehaze", "real"),
        prefixed_field(prefix, "Texture", "LocalTexture", "real"),
        prefixed_field(prefix, "Name", "CorrectionName"),
        prefixed_field(prefix, "SyncID", "CorrectionSyncID"),
        prefixed_field(
            prefix,
            "RangeMaskLumMin",
            "LumMin",
            "real",
            nested_field_name="CorrectionRangeMask",
        ),
        prefixed_field(
            prefix,
            "RangeMaskLumMax",
            "LumMax",
            "real",
            nested_field_name="CorrectionRangeMask",
        ),
        *mask_fields(prefix, "CorrectionMasks", "Mask"),
    )


def depth_based_correction_fields(prefix: str) -> tuple[XmpSimpleStructFieldSpec, ...]:
    return (
        prefixed_field(prefix, "What", "What"),
        prefixed_field(prefix, "CorrectionActive", "CorrectionActive", "boolean"),
        prefixed_field(prefix, "CorrectionAmount", "CorrectionAmount", "real"),
        prefixed_field(prefix, "CorrectionSyncID", "CorrectionSyncID"),
        prefixed_field(prefix, "LocalCorrectedDepth", "LocalCorrectedDepth", "real"),
        prefixed_field(
            prefix,
            "LocalCurveRefineSaturation",
            "LocalCurveRefineSaturation",
            "real",
        ),
        *mask_fields(prefix, "CorrectionMasks", "Mask"),
    )


def mask_fields(
    prefix: str,
    nested_field_name: str,
    flat_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    nested_suffix = f"{prefix}{flat_name}"
    return (
        prefixed_field(
            nested_suffix,
            "Value",
            "MaskValue",
            "real",
            nested_field_name=nested_field_name,
            nested_list_kind="Seq",
        ),
        prefixed_field(
            nested_suffix,
            "Radius",
            "Radius",
            "real",
            nested_field_name=nested_field_name,
            nested_list_kind="Seq",
        ),
        prefixed_field(
            nested_suffix,
            "Flow",
            "Flow",
            "real",
            nested_field_name=nested_field_name,
            nested_list_kind="Seq",
        ),
        prefixed_field(
            nested_suffix,
            "Top",
            "Top",
            "real",
            nested_field_name=nested_field_name,
            nested_list_kind="Seq",
        ),
        prefixed_field(
            nested_suffix,
            "Left",
            "Left",
            "real",
            nested_field_name=nested_field_name,
            nested_list_kind="Seq",
        ),
        prefixed_field(
            nested_suffix,
            "Angle",
            "Angle",
            "real",
            nested_field_name=nested_field_name,
            nested_list_kind="Seq",
        ),
        prefixed_field(
            nested_suffix,
            "Active",
            "MaskActive",
            "boolean",
            nested_field_name=nested_field_name,
            nested_list_kind="Seq",
        ),
        prefixed_field(
            nested_suffix,
            "Name",
            "MaskName",
            nested_field_name=nested_field_name,
            nested_list_kind="Seq",
        ),
        prefixed_field(
            nested_suffix,
            "Dabs",
            "Dabs",
            nested_field_name=nested_field_name,
            nested_list_kind="Seq",
            field_list_kind="Seq",
        ),
    )


def retouch_area_fields(prefix: str) -> tuple[XmpSimpleStructFieldSpec, ...]:
    return (
        prefixed_field(prefix, "SpotType", "SpotType"),
        prefixed_field(prefix, "SourceState", "SourceState"),
        prefixed_field(prefix, "Method", "Method"),
        prefixed_field(prefix, "SourceX", "SourceX", "real"),
        prefixed_field(prefix, "OffsetY", "OffsetY", "real"),
        prefixed_field(prefix, "Opacity", "Opacity", "real"),
        prefixed_field(prefix, "Feather", "Feather", "real"),
        prefixed_field(prefix, "Seed", "Seed", "integer"),
        *mask_fields(prefix, "Masks", "Mask"),
    )


def lens_blur_fields() -> tuple[XmpSimpleStructFieldSpec, ...]:
    return (
        prefixed_field("LensBlur", "Active", "Active", "boolean"),
        prefixed_field("LensBlur", "Amount", "BlurAmount", "real"),
        prefixed_field("LensBlur", "BokehAspect", "BokehAspect", "real"),
        prefixed_field("LensBlur", "BokehRotation", "BokehRotation", "real"),
        prefixed_field("LensBlur", "BokehShape", "BokehShape", "real"),
        prefixed_field("LensBlur", "FocalRange", "FocalRange"),
        prefixed_field("LensBlur", "FocalRangeSource", "FocalRangeSource", "real"),
        prefixed_field("LensBlur", "HighlightsBoost", "HighlightsBoost", "real"),
        prefixed_field("LensBlur", "SampledArea", "SampledArea"),
        prefixed_field("LensBlur", "Version", "Version"),
    )


def depth_map_info_fields() -> tuple[XmpSimpleStructFieldSpec, ...]:
    return (
        prefixed_field("DepthMapInfo", "BaseRawDepthInputDigest", "BaseRawDepthInputDigest"),
        prefixed_field("DepthMapInfo", "BaseRawDepthTable", "BaseRawDepthTable"),
        prefixed_field("DepthMapInfo", "BaseRawDepthVersion", "BaseRawDepthVersion"),
        prefixed_field("DepthMapInfo", "DepthSource", "DepthSource"),
    )


def look_fields() -> tuple[XmpSimpleStructFieldSpec, ...]:
    return (
        prefixed_field("Look", "Name", "Name"),
        prefixed_field("Look", "Amount", "Amount"),
        prefixed_field("Look", "Cluster", "Cluster"),
        prefixed_field("Look", "UUID", "UUID"),
        prefixed_field("Look", "Group", "Group", "lang_alt"),
        prefixed_field("Look", "ParametersVersion", "Version", nested_field_name="Parameters"),
        prefixed_field(
            "Look",
            "ParametersProcessVersion",
            "ProcessVersion",
            nested_field_name="Parameters",
        ),
        prefixed_field(
            "Look",
            "ParametersClarity2012",
            "Clarity2012",
            nested_field_name="Parameters",
        ),
        prefixed_field(
            "Look",
            "ParametersToneCurvePV2012",
            "ToneCurvePV2012",
            nested_field_name="Parameters",
            field_list_kind="Seq",
        ),
    )


def range_mask_fields() -> tuple[XmpSimpleStructFieldSpec, ...]:
    return (
        prefixed_field(
            "RangeMaskMapInfo", "RGBMin", "RGBMin", nested_field_name="RangeMaskMapInfo"
        ),
        prefixed_field(
            "RangeMaskMapInfo", "RGBMax", "RGBMax", nested_field_name="RangeMaskMapInfo"
        ),
        prefixed_field(
            "RangeMaskMapInfo", "LabMin", "LabMin", nested_field_name="RangeMaskMapInfo"
        ),
        prefixed_field(
            "RangeMaskMapInfo", "LabMax", "LabMax", nested_field_name="RangeMaskMapInfo"
        ),
        prefixed_field(
            "RangeMaskMapInfo",
            "LumEq",
            "LumEq",
            nested_field_name="RangeMaskMapInfo",
            field_list_kind="Seq",
        ),
    )


CAMERA_RAW_FIELD_SPECS_BY_PARENT: tuple[
    tuple[str, tuple[XmpSimpleStructFieldSpec, ...]],
    ...,
] = (
    parent_fields(
        "CircularGradientBasedCorrections",
        correction_fields("CircGradBasedCorr"),
    ),
    parent_fields(
        "DepthBasedCorrections",
        depth_based_correction_fields("DepthBasedCorr"),
    ),
    parent_fields("DepthMapInfo", depth_map_info_fields()),
    parent_fields("GradientBasedCorrections", correction_fields("GradientBasedCorr")),
    parent_fields("LensBlur", lens_blur_fields()),
    parent_fields("Look", look_fields()),
    parent_fields(
        "MaskGroupBasedCorrections",
        correction_fields("MaskGroupBasedCorr"),
    ),
    parent_fields("PaintBasedCorrections", correction_fields("PaintCorrection")),
    parent_fields("RangeMask", range_mask_fields()),
    parent_fields("RetouchAreas", retouch_area_fields("RetouchArea")),
)

XMP_CAMERA_RAW_FIELD_SPECS: tuple[XmpSimpleStructFieldSpec, ...] = tuple(
    field_spec for _, field_specs in CAMERA_RAW_FIELD_SPECS_BY_PARENT for field_spec in field_specs
)


def camera_raw_parent_spec_for_property(
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    return simple_struct_parent_spec_for_property(XMP_CAMERA_RAW_PARENT_SPECS, property_name)


def camera_raw_assignment_target(
    property_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group not in {"XMP-crd", "XMP-crs"} or separator != ":":
        return None
    for parent_spec in XMP_CAMERA_RAW_PARENT_SPECS:
        if parent_spec.group != group:
            continue
        for field_spec in camera_raw_field_specs_for_parent(parent_spec.parent_name):
            if tag_name == field_spec.readback_suffix:
                return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    return None


def camera_raw_field_specs_for_parent(
    parent_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    for candidate_parent_name, field_specs in CAMERA_RAW_FIELD_SPECS_BY_PARENT:
        if candidate_parent_name == parent_name:
            return field_specs
    return ()


def camera_raw_readback_tag_ids_for_group(group: CameraRawGroup) -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for parent_spec in XMP_CAMERA_RAW_PARENT_SPECS:
        if parent_spec.group != group:
            continue
        for field_spec in camera_raw_field_specs_for_parent(parent_spec.parent_name):
            tag_ids[field_spec.readback_suffix] = parent_spec.element_name
    return tag_ids


def camera_raw_crd_readback_tag_ids() -> dict[str, str]:
    return camera_raw_readback_tag_ids_for_group("XMP-crd")


def camera_raw_crs_readback_tag_ids() -> dict[str, str]:
    return camera_raw_readback_tag_ids_for_group("XMP-crs")
