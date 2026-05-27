"""Source-grounded PRISM XMP struct adapter metadata."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructParentSpec,
    XmpSimpleStructShape,
    XmpSimpleStructValueKind,
    simple_struct_parent_spec_for_property,
)

PRISM_NAMESPACE = "http://prismstandard.org/namespaces/basic/2.0/"


def prism_parent(
    parent_name: str,
    element_name: str,
    *,
    shape: XmpSimpleStructShape = "struct",
) -> XmpSimpleStructParentSpec:
    return XmpSimpleStructParentSpec(
        parent_name=parent_name,
        property_name=f"XMP-prism:{parent_name}",
        element_name=element_name,
        group="XMP-prism",
        namespace_prefix="prism",
        struct_namespace_prefix="prism",
        struct_namespace_uri=PRISM_NAMESPACE,
        shape=shape,
        list_kind="Bag" if shape == "struct_list" else None,
    )


XMP_PRISM_PARENT_SPECS: tuple[XmpSimpleStructParentSpec, ...] = (
    prism_parent("AlternateTitle", "alternateTitle", shape="struct_list"),
    prism_parent("Channel", "channel", shape="struct_list"),
    prism_parent("HasCorrection", "hasCorrection"),
    prism_parent("KillDate", "killDate"),
    prism_parent("OffSaleDate", "offSaleDate", shape="struct_list"),
    prism_parent("OnSaleDate", "onSaleDate", shape="struct_list"),
    prism_parent("OnSaleDay", "onSaleDay", shape="struct_list"),
    prism_parent("PublicationDate", "publicationDate", shape="struct_list"),
    prism_parent("PublicationDisplayDate", "publicationDisplayDate", shape="struct_list"),
    prism_parent("URL", "url", shape="struct_list"),
)


def field(
    suffix: str,
    field_name: str,
    readback_suffix: str,
    value_kind: XmpSimpleStructValueKind = "text",
) -> XmpSimpleStructFieldSpec:
    return XmpSimpleStructFieldSpec(
        suffix=suffix,
        field_name=field_name,
        readback_suffix=readback_suffix,
        value_kind=value_kind,
    )


def parent_fields(
    parent_name: str,
    specs: tuple[XmpSimpleStructFieldSpec, ...],
) -> tuple[str, tuple[XmpSimpleStructFieldSpec, ...]]:
    return (parent_name, specs)


def prefixed_field(
    parent_name: str,
    suffix: str,
    field_name: str,
    value_kind: XmpSimpleStructValueKind = "text",
) -> XmpSimpleStructFieldSpec:
    return field(
        suffix=f"{parent_name}{suffix}",
        field_name=field_name,
        readback_suffix=f"{parent_name}{suffix}",
        value_kind=value_kind,
    )


def text_platform_lang_fields(parent_name: str) -> tuple[XmpSimpleStructFieldSpec, ...]:
    return (
        prefixed_field(parent_name, "Text", "text"),
        prefixed_field(parent_name, "Platform", "a-platform"),
        prefixed_field(parent_name, "Lang", "a-lang"),
    )


def date_platform_fields(parent_name: str) -> tuple[XmpSimpleStructFieldSpec, ...]:
    return (
        prefixed_field(parent_name, "Date", "date", "date"),
        prefixed_field(parent_name, "Platform", "a-platform"),
    )


XMP_PRISM_FIELD_SPECS_BY_PARENT: tuple[
    tuple[str, tuple[XmpSimpleStructFieldSpec, ...]],
    ...,
] = (
    parent_fields("AlternateTitle", text_platform_lang_fields("AlternateTitle")),
    parent_fields(
        "Channel",
        (
            prefixed_field("Channel", "Channel", "channel"),
            prefixed_field("Channel", "Subchannel1", "subchannel1"),
            prefixed_field("Channel", "Subchannel2", "subchannel2"),
            prefixed_field("Channel", "Subchannel3", "subchannel3"),
            prefixed_field("Channel", "Subchannel4", "subchannel4"),
            prefixed_field("Channel", "Lang", "a-lang"),
        ),
    ),
    parent_fields("HasCorrection", text_platform_lang_fields("HasCorrection")),
    parent_fields("KillDate", date_platform_fields("KillDate")),
    parent_fields("OffSaleDate", date_platform_fields("OffSaleDate")),
    parent_fields("OnSaleDate", date_platform_fields("OnSaleDate")),
    parent_fields(
        "OnSaleDay",
        (
            prefixed_field("OnSaleDay", "Day", "day"),
            prefixed_field("OnSaleDay", "Platform", "a-platform"),
        ),
    ),
    parent_fields("PublicationDate", date_platform_fields("PublicationDate")),
    parent_fields(
        "PublicationDisplayDate",
        date_platform_fields("PublicationDisplayDate"),
    ),
    parent_fields(
        "URL",
        (
            field("URLUrl", "url", "URLUrl"),
            field("URLPlatform", "a-platform", "URLPlatform"),
        ),
    ),
)

XMP_PRISM_FIELD_SPECS: tuple[XmpSimpleStructFieldSpec, ...] = tuple(
    field_spec for _, field_specs in XMP_PRISM_FIELD_SPECS_BY_PARENT for field_spec in field_specs
)


def prism_parent_spec_for_property(
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    return simple_struct_parent_spec_for_property(XMP_PRISM_PARENT_SPECS, property_name)


def prism_assignment_target(
    property_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-prism" or separator != ":":
        return None
    for parent_spec in XMP_PRISM_PARENT_SPECS:
        for field_spec in prism_field_specs_for_parent(parent_spec.parent_name):
            if tag_name == field_spec.readback_suffix:
                return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    return None


def prism_field_specs_for_parent(
    parent_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    for candidate_parent_name, field_specs in XMP_PRISM_FIELD_SPECS_BY_PARENT:
        if candidate_parent_name == parent_name:
            return field_specs
    return ()


def prism_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for parent_spec in XMP_PRISM_PARENT_SPECS:
        for field_spec in prism_field_specs_for_parent(parent_spec.parent_name):
            tag_ids[field_spec.readback_suffix] = parent_spec.element_name
    return tag_ids
