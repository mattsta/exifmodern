"""Source-grounded XMP basic image struct adapter metadata."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructParentSpec,
    simple_struct_field_spec_for_field_name,
    simple_struct_parent_spec_for_property,
)

XMPG_IMG_NAMESPACE = "http://ns.adobe.com/xap/1.0/g/img/"
XMPTPG_NAMESPACE = "http://ns.adobe.com/xap/1.0/t/pg/"
XMP_NAMESPACE = "http://ns.adobe.com/xap/1.0/"

XMP_BASIC_IMAGE_PARENT_SPECS: tuple[XmpSimpleStructParentSpec, ...] = (
    XmpSimpleStructParentSpec(
        parent_name="PageInfo",
        property_name="XMP-xmp:PageInfo",
        element_name="PageInfo",
        group="XMP-xmp",
        namespace_prefix="xmp",
        struct_namespace_prefix="xmpGImg",
        struct_namespace_uri=XMPG_IMG_NAMESPACE,
        shape="struct_list",
        list_kind="Seq",
    ),
    XmpSimpleStructParentSpec(
        parent_name="Thumbnails",
        property_name="XMP-xmp:Thumbnails",
        element_name="Thumbnails",
        group="XMP-xmp",
        namespace_prefix="xmp",
        struct_namespace_prefix="xmpGImg",
        struct_namespace_uri=XMPG_IMG_NAMESPACE,
        shape="struct_list",
        list_kind="Alt",
    ),
)

XMP_BASIC_IMAGE_FIELD_SPECS: tuple[XmpSimpleStructFieldSpec, ...] = (
    XmpSimpleStructFieldSpec(
        "PageNumber",
        "PageNumber",
        "PageImagePageNumber",
        "integer",
        namespace_uri=XMPTPG_NAMESPACE,
    ),
    XmpSimpleStructFieldSpec("Format", "format", "PageImageFormat", "text"),
    XmpSimpleStructFieldSpec("Height", "height", "PageImageHeight", "integer"),
    XmpSimpleStructFieldSpec("Image", "image", "PageImage", "text"),
    XmpSimpleStructFieldSpec("Width", "width", "PageImageWidth", "integer"),
    XmpSimpleStructFieldSpec("ThumbnailFormat", "format", "ThumbnailFormat", "text"),
    XmpSimpleStructFieldSpec("ThumbnailHeight", "height", "ThumbnailHeight", "integer"),
    XmpSimpleStructFieldSpec("ThumbnailImage", "image", "ThumbnailImage", "text"),
    XmpSimpleStructFieldSpec("ThumbnailWidth", "width", "ThumbnailWidth", "integer"),
)


def basic_image_parent_spec_for_property(property_name: str) -> XmpSimpleStructParentSpec | None:
    return simple_struct_parent_spec_for_property(XMP_BASIC_IMAGE_PARENT_SPECS, property_name)


def basic_image_assignment_target(property_name: str) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-xmp" or separator != ":":
        return None
    page_target = basic_image_page_info_assignment_target(tag_name)
    if page_target is not None:
        return page_target
    thumbnail_target = basic_image_thumbnail_assignment_target(tag_name)
    if thumbnail_target is not None:
        return thumbnail_target
    return None


def basic_image_page_info_assignment_target(
    tag_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    parent_spec = basic_image_parent_spec_by_name("PageInfo")
    if parent_spec is None:
        return None
    if not tag_name.startswith("PageImage"):
        return None
    suffix = tag_name.removeprefix("PageImage")
    field_suffix = "Image" if suffix == "" else suffix
    field_spec = basic_image_field_spec_for_suffix(field_suffix)
    if field_spec is None:
        return None
    return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)


def basic_image_thumbnail_assignment_target(
    tag_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    parent_spec = basic_image_parent_spec_by_name("Thumbnails")
    if parent_spec is None or not tag_name.startswith("Thumbnail"):
        return None
    field_spec = basic_image_field_spec_for_suffix(tag_name)
    if field_spec is None:
        return None
    return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)


def basic_image_parent_spec_by_name(parent_name: str) -> XmpSimpleStructParentSpec | None:
    for parent_spec in XMP_BASIC_IMAGE_PARENT_SPECS:
        if parent_spec.parent_name == parent_name:
            return parent_spec
    return None


def basic_image_field_specs_for_parent(
    parent_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    if parent_name == "PageInfo":
        return tuple(
            field_spec
            for field_spec in XMP_BASIC_IMAGE_FIELD_SPECS
            if field_spec.suffix in {"PageNumber", "Format", "Height", "Image", "Width"}
        )
    if parent_name == "Thumbnails":
        return tuple(
            field_spec
            for field_spec in XMP_BASIC_IMAGE_FIELD_SPECS
            if field_spec.suffix.startswith("Thumbnail")
        )
    return ()


def basic_image_field_spec_for_suffix(suffix: str) -> XmpSimpleStructFieldSpec | None:
    for field_spec in XMP_BASIC_IMAGE_FIELD_SPECS:
        if field_spec.suffix == suffix:
            return field_spec
    return None


def basic_image_field_spec_for_field_name(field_name: str) -> XmpSimpleStructFieldSpec | None:
    return simple_struct_field_spec_for_field_name(XMP_BASIC_IMAGE_FIELD_SPECS, field_name)


def basic_image_readback_tag_ids() -> dict[str, str]:
    return {
        "PageImageFormat": "PageInfo",
        "PageImageHeight": "PageInfo",
        "PageImage": "PageInfo",
        "PageImagePageNumber": "PageInfo",
        "PageImageWidth": "PageInfo",
        "ThumbnailFormat": "Thumbnails",
        "ThumbnailHeight": "Thumbnails",
        "ThumbnailImage": "Thumbnails",
        "ThumbnailWidth": "Thumbnails",
    }
