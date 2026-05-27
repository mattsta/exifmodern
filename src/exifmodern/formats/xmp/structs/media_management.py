"""Source-grounded XMP media-management struct adapter metadata."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructParentSpec,
    simple_struct_field_spec_for_field_name,
    simple_struct_parent_spec_for_property,
)

ST_EVT_NAMESPACE = "http://ns.adobe.com/xap/1.0/sType/ResourceEvent#"
ST_VER_NAMESPACE = "http://ns.adobe.com/xap/1.0/sType/Version#"

XMP_MEDIA_MANAGEMENT_PARENT_SPECS: tuple[XmpSimpleStructParentSpec, ...] = (
    XmpSimpleStructParentSpec(
        parent_name="Versions",
        property_name="XMP-xmpMM:Versions",
        element_name="Versions",
        group="XMP-xmpMM",
        namespace_prefix="xmpMM",
        struct_namespace_prefix="stVer",
        struct_namespace_uri=ST_VER_NAMESPACE,
        shape="struct_list",
        list_kind="Seq",
    ),
)

XMP_MEDIA_MANAGEMENT_FIELD_SPECS: tuple[XmpSimpleStructFieldSpec, ...] = (
    XmpSimpleStructFieldSpec("Comments", "comments", "Comments", "text"),
    XmpSimpleStructFieldSpec("Modifier", "modifier", "Modifier", "text"),
    XmpSimpleStructFieldSpec("ModifyDate", "modifyDate", "ModifyDate", "date"),
    XmpSimpleStructFieldSpec("Version", "version", "Version", "text"),
    XmpSimpleStructFieldSpec(
        "EventAction",
        "action",
        "EventAction",
        "text",
        namespace_uri=ST_EVT_NAMESPACE,
        nested_field_name="event",
        nested_namespace_uri=ST_VER_NAMESPACE,
    ),
    XmpSimpleStructFieldSpec(
        "EventChanged",
        "changed",
        "EventChanged",
        "text",
        namespace_uri=ST_EVT_NAMESPACE,
        nested_field_name="event",
        nested_namespace_uri=ST_VER_NAMESPACE,
    ),
    XmpSimpleStructFieldSpec(
        "EventInstanceID",
        "instanceID",
        "EventInstanceID",
        "text",
        namespace_uri=ST_EVT_NAMESPACE,
        nested_field_name="event",
        nested_namespace_uri=ST_VER_NAMESPACE,
    ),
    XmpSimpleStructFieldSpec(
        "EventParameters",
        "parameters",
        "EventParameters",
        "text",
        namespace_uri=ST_EVT_NAMESPACE,
        nested_field_name="event",
        nested_namespace_uri=ST_VER_NAMESPACE,
    ),
    XmpSimpleStructFieldSpec(
        "EventSoftwareAgent",
        "softwareAgent",
        "EventSoftwareAgent",
        "text",
        namespace_uri=ST_EVT_NAMESPACE,
        nested_field_name="event",
        nested_namespace_uri=ST_VER_NAMESPACE,
    ),
    XmpSimpleStructFieldSpec(
        "EventWhen",
        "when",
        "EventWhen",
        "date",
        namespace_uri=ST_EVT_NAMESPACE,
        nested_field_name="event",
        nested_namespace_uri=ST_VER_NAMESPACE,
    ),
)


def media_management_parent_spec_for_property(
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    return simple_struct_parent_spec_for_property(
        XMP_MEDIA_MANAGEMENT_PARENT_SPECS,
        property_name,
    )


def media_management_assignment_target(
    property_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-xmpMM" or separator != ":":
        return None
    for parent_spec in XMP_MEDIA_MANAGEMENT_PARENT_SPECS:
        if not tag_name.startswith(parent_spec.parent_name):
            continue
        field_suffix = tag_name.removeprefix(parent_spec.parent_name)
        field_spec = media_management_field_spec_for_suffix(field_suffix)
        if field_spec is None:
            continue
        return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    return None


def media_management_field_spec_for_suffix(suffix: str) -> XmpSimpleStructFieldSpec | None:
    for field_spec in XMP_MEDIA_MANAGEMENT_FIELD_SPECS:
        if field_spec.suffix == suffix:
            return field_spec
    return None


def media_management_field_specs_for_parent(
    parent_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    if parent_name == "Versions":
        return XMP_MEDIA_MANAGEMENT_FIELD_SPECS
    return ()


def media_management_field_spec_for_field_name(
    field_name: str,
) -> XmpSimpleStructFieldSpec | None:
    return simple_struct_field_spec_for_field_name(
        XMP_MEDIA_MANAGEMENT_FIELD_SPECS,
        field_name,
    )


def media_management_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for field_spec in XMP_MEDIA_MANAGEMENT_FIELD_SPECS:
        tag_ids[f"Versions{field_spec.readback_suffix}"] = "Versions"
    return tag_ids
