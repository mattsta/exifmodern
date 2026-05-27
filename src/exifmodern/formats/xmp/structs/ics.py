"""Source-grounded IDimager iCS XMP struct adapter metadata."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructParentSpec,
    simple_struct_parent_spec_for_property,
)

ICS_NAMESPACE = "http://ns.idimager.com/ics/1.0/"

XMP_ICS_PARENT_SPECS: tuple[XmpSimpleStructParentSpec, ...] = (
    XmpSimpleStructParentSpec(
        parent_name="SubVersions",
        property_name="XMP-ics:SubVersions",
        element_name="SubVersions",
        group="XMP-ics",
        namespace_prefix="ics",
        struct_namespace_prefix="ics",
        struct_namespace_uri=ICS_NAMESPACE,
        shape="struct_list",
        list_kind="Bag",
    ),
    XmpSimpleStructParentSpec(
        parent_name="TagStructure",
        property_name="XMP-ics:TagStructure",
        element_name="TagStructure",
        group="XMP-ics",
        namespace_prefix="ics",
        struct_namespace_prefix="ics",
        struct_namespace_uri=ICS_NAMESPACE,
        shape="struct_list",
        list_kind="Bag",
    ),
)

XMP_ICS_FIELD_SPECS_BY_PARENT: tuple[
    tuple[str, tuple[XmpSimpleStructFieldSpec, ...]],
    ...,
] = (
    (
        "SubVersions",
        (
            XmpSimpleStructFieldSpec(
                "VersRef",
                "VersRef",
                "SubVersionReference",
                "text",
            ),
            XmpSimpleStructFieldSpec(
                "FileName",
                "FileName",
                "SubVersionFileName",
                "text",
            ),
        ),
    ),
    (
        "TagStructure",
        (
            XmpSimpleStructFieldSpec("LabelName", "LabelName", "LabelName1", "text"),
            XmpSimpleStructFieldSpec("Reference", "Reference", "Reference1", "text"),
            XmpSimpleStructFieldSpec(
                "ParentReference",
                "ParentReference",
                "ParentReference1",
                "text",
            ),
            XmpSimpleStructFieldSpec(
                "SubLabelsLabelName",
                "LabelName",
                "LabelName2",
                "text",
                nested_field_name="SubLabels",
                nested_list_kind="Bag",
            ),
            XmpSimpleStructFieldSpec(
                "SubLabelsReference",
                "Reference",
                "Reference2",
                "text",
                nested_field_name="SubLabels",
                nested_list_kind="Bag",
            ),
            XmpSimpleStructFieldSpec(
                "SubLabelsParentReference",
                "ParentReference",
                "ParentReference2",
                "text",
                nested_field_name="SubLabels",
                nested_list_kind="Bag",
            ),
        ),
    ),
)

XMP_ICS_FIELD_SPECS: tuple[XmpSimpleStructFieldSpec, ...] = tuple(
    field_spec for _, field_specs in XMP_ICS_FIELD_SPECS_BY_PARENT for field_spec in field_specs
)


def ics_parent_spec_for_property(
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    return simple_struct_parent_spec_for_property(XMP_ICS_PARENT_SPECS, property_name)


def ics_assignment_target(
    property_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-ics" or separator != ":":
        return None
    for parent_spec in XMP_ICS_PARENT_SPECS:
        for field_spec in ics_field_specs_for_parent(parent_spec.parent_name):
            if tag_name == field_spec.readback_suffix:
                return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    return None


def ics_field_specs_for_parent(
    parent_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    for candidate_parent_name, field_specs in XMP_ICS_FIELD_SPECS_BY_PARENT:
        if candidate_parent_name == parent_name:
            return field_specs
    return ()


def ics_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for parent_spec in XMP_ICS_PARENT_SPECS:
        for field_spec in ics_field_specs_for_parent(parent_spec.parent_name):
            tag_ids[field_spec.readback_suffix] = parent_spec.element_name
    return tag_ids
