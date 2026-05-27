"""Source-grounded Photoshop XMP struct adapter metadata."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructParentSpec,
    XmpSimpleStructValueKind,
    simple_struct_parent_spec_for_property,
)

PHOTOSHOP_NAMESPACE = "http://ns.adobe.com/photoshop/1.0/"
ST_CAMERA_NAMESPACE = "http://ns.adobe.com/photoshop/1.0/camera-profile"
CRLCP_NAMESPACE = "http://ns.adobe.com/camera-raw-embedded-lens-profile/1.0/"

XMP_PHOTOSHOP_PARENT_SPECS: tuple[XmpSimpleStructParentSpec, ...] = (
    XmpSimpleStructParentSpec(
        parent_name="CameraProfiles",
        property_name="XMP-photoshop:CameraProfiles",
        element_name="CameraProfiles",
        group="XMP-photoshop",
        namespace_prefix="photoshop",
        struct_namespace_prefix="stCamera",
        struct_namespace_uri=ST_CAMERA_NAMESPACE,
        shape="struct_list",
        list_kind="Seq",
    ),
    XmpSimpleStructParentSpec(
        parent_name="TextLayers",
        property_name="XMP-photoshop:TextLayers",
        element_name="TextLayers",
        group="XMP-photoshop",
        namespace_prefix="photoshop",
        struct_namespace_prefix="photoshop",
        struct_namespace_uri=PHOTOSHOP_NAMESPACE,
        shape="struct_list",
        list_kind="Seq",
    ),
)


def camera_profile_field(
    suffix: str,
    field_name: str,
    value_kind: XmpSimpleStructValueKind,
) -> XmpSimpleStructFieldSpec:
    return XmpSimpleStructFieldSpec(
        suffix,
        field_name,
        f"CameraProfiles{suffix}",
        value_kind,
    )


def camera_profile_perspective_field(
    suffix: str,
    field_name: str,
    value_kind: XmpSimpleStructValueKind,
) -> XmpSimpleStructFieldSpec:
    return XmpSimpleStructFieldSpec(
        f"PerspectiveModel{suffix}",
        field_name,
        f"CameraProfilesPerspectiveModel{suffix}",
        value_kind,
        nested_field_name="PerspectiveModel",
        nested_namespace_uri=CRLCP_NAMESPACE,
    )


XMP_PHOTOSHOP_FIELD_SPECS_BY_PARENT: tuple[
    tuple[str, tuple[XmpSimpleStructFieldSpec, ...]],
    ...,
] = (
    (
        "CameraProfiles",
        (
            camera_profile_field("Author", "Author", "text"),
            camera_profile_field("Make", "Make", "text"),
            camera_profile_field("Model", "Model", "text"),
            camera_profile_field("UniqueCameraModel", "UniqueCameraModel", "text"),
            camera_profile_field("CameraRawProfile", "CameraRawProfile", "boolean"),
            camera_profile_field("AutoScale", "AutoScale", "boolean"),
            camera_profile_field("Lens", "Lens", "text"),
            camera_profile_field("CameraPrettyName", "CameraPrettyName", "text"),
            camera_profile_field("LensPrettyName", "LensPrettyName", "text"),
            camera_profile_field("ProfileName", "ProfileName", "text"),
            camera_profile_field("SensorFormatFactor", "SensorFormatFactor", "real"),
            camera_profile_field("FocalLength", "FocalLength", "real"),
            camera_profile_field("FocusDistance", "FocusDistance", "real"),
            camera_profile_field("ApertureValue", "ApertureValue", "real"),
            camera_profile_perspective_field("Version", "Version", "text"),
            camera_profile_perspective_field("ImageXCenter", "ImageXCenter", "real"),
            camera_profile_perspective_field("ImageYCenter", "ImageYCenter", "real"),
            camera_profile_perspective_field("ScaleFactor", "ScaleFactor", "real"),
            camera_profile_perspective_field(
                "RadialDistortParam1",
                "RadialDistortParam1",
                "real",
            ),
            camera_profile_perspective_field(
                "RadialDistortParam2",
                "RadialDistortParam2",
                "real",
            ),
            camera_profile_perspective_field(
                "RadialDistortParam3",
                "RadialDistortParam3",
                "real",
            ),
        ),
    ),
    (
        "TextLayers",
        (
            XmpSimpleStructFieldSpec(
                "LayerName",
                "LayerName",
                "TextLayerName",
                "text",
            ),
            XmpSimpleStructFieldSpec(
                "LayerText",
                "LayerText",
                "TextLayerText",
                "text",
            ),
        ),
    ),
)

XMP_PHOTOSHOP_FIELD_SPECS: tuple[XmpSimpleStructFieldSpec, ...] = tuple(
    field_spec
    for _, field_specs in XMP_PHOTOSHOP_FIELD_SPECS_BY_PARENT
    for field_spec in field_specs
)


def photoshop_parent_spec_for_property(
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    return simple_struct_parent_spec_for_property(XMP_PHOTOSHOP_PARENT_SPECS, property_name)


def photoshop_assignment_target(
    property_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-photoshop" or separator != ":":
        return None
    for parent_spec in XMP_PHOTOSHOP_PARENT_SPECS:
        for field_spec in photoshop_field_specs_for_parent(parent_spec.parent_name):
            if tag_name == field_spec.readback_suffix:
                return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    return None


def photoshop_field_specs_for_parent(
    parent_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    for candidate_parent_name, field_specs in XMP_PHOTOSHOP_FIELD_SPECS_BY_PARENT:
        if candidate_parent_name == parent_name:
            return field_specs
    return ()


def photoshop_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for parent_spec in XMP_PHOTOSHOP_PARENT_SPECS:
        for field_spec in photoshop_field_specs_for_parent(parent_spec.parent_name):
            tag_ids[field_spec.readback_suffix] = parent_spec.element_name
    return tag_ids
