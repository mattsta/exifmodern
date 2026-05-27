"""Source-grounded ACDSee region XMP struct adapter metadata."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructParentSpec,
    XmpSimpleStructPathStep,
    XmpSimpleStructValueKind,
    simple_struct_parent_spec_for_property,
)

ACDSEE_REGION_NAMESPACE = "http://ns.acdsee.com/regions/"
ACDSEE_DIMENSIONS_NAMESPACE = "http://ns.acdsee.com/sType/Dimensions#"
ACDSEE_AREA_NAMESPACE = "http://ns.acdsee.com/sType/Area#"

XMP_ACDSEE_REGION_PARENT_SPECS: tuple[XmpSimpleStructParentSpec, ...] = (
    XmpSimpleStructParentSpec(
        parent_name="RegionInfoACDSee",
        property_name="XMP-acdsee-rs:RegionInfoACDSee",
        element_name="Regions",
        group="XMP-acdsee-rs",
        namespace_prefix="ACDSeeRegions",
        struct_namespace_prefix="acdsee-rs",
        struct_namespace_uri=ACDSEE_REGION_NAMESPACE,
        shape="struct",
    ),
)


def acdsee_region_field(
    suffix: str,
    field_name: str,
    readback_suffix: str,
    *,
    namespace_uri: str | None = None,
    nested_path: tuple[XmpSimpleStructPathStep, ...] = (),
    value_kind: XmpSimpleStructValueKind = "text",
) -> XmpSimpleStructFieldSpec:
    return XmpSimpleStructFieldSpec(
        suffix,
        field_name,
        readback_suffix,
        value_kind,
        namespace_uri=namespace_uri,
        nested_path=nested_path,
    )


REGION_LIST_PATH = (
    XmpSimpleStructPathStep(
        "RegionList",
        namespace_uri=ACDSEE_REGION_NAMESPACE,
        list_kind="Bag",
    ),
)
APPLIED_DIMENSIONS_PATH = (
    XmpSimpleStructPathStep(
        "AppliedToDimensions",
        namespace_uri=ACDSEE_REGION_NAMESPACE,
    ),
)
ALG_AREA_PATH = (
    *REGION_LIST_PATH,
    XmpSimpleStructPathStep("ALGArea", namespace_uri=ACDSEE_REGION_NAMESPACE),
)
DLY_AREA_PATH = (
    *REGION_LIST_PATH,
    XmpSimpleStructPathStep("DLYArea", namespace_uri=ACDSEE_REGION_NAMESPACE),
)

XMP_ACDSEE_REGION_FIELD_SPECS: tuple[XmpSimpleStructFieldSpec, ...] = (
    acdsee_region_field(
        "RegionAppliedToDimensionsW",
        "w",
        "RegionAppliedToDimensionsW",
        namespace_uri=ACDSEE_DIMENSIONS_NAMESPACE,
        nested_path=APPLIED_DIMENSIONS_PATH,
        value_kind="real",
    ),
    acdsee_region_field(
        "RegionAppliedToDimensionsH",
        "h",
        "RegionAppliedToDimensionsH",
        namespace_uri=ACDSEE_DIMENSIONS_NAMESPACE,
        nested_path=APPLIED_DIMENSIONS_PATH,
        value_kind="real",
    ),
    acdsee_region_field(
        "RegionAppliedToDimensionsUnit",
        "unit",
        "RegionAppliedToDimensionsUnit",
        namespace_uri=ACDSEE_DIMENSIONS_NAMESPACE,
        nested_path=APPLIED_DIMENSIONS_PATH,
    ),
    acdsee_region_field("RegionName", "Name", "RegionName", nested_path=REGION_LIST_PATH),
    acdsee_region_field(
        "RegionNameAssignType",
        "NameAssignType",
        "RegionNameAssignType",
        nested_path=REGION_LIST_PATH,
    ),
    acdsee_region_field("RegionType", "Type", "RegionType", nested_path=REGION_LIST_PATH),
    acdsee_region_field(
        "RegionALGAreaX",
        "x",
        "RegionALGAreaX",
        namespace_uri=ACDSEE_AREA_NAMESPACE,
        nested_path=ALG_AREA_PATH,
        value_kind="real",
    ),
    acdsee_region_field(
        "RegionALGAreaY",
        "y",
        "RegionALGAreaY",
        namespace_uri=ACDSEE_AREA_NAMESPACE,
        nested_path=ALG_AREA_PATH,
        value_kind="real",
    ),
    acdsee_region_field(
        "RegionALGAreaW",
        "w",
        "RegionALGAreaW",
        namespace_uri=ACDSEE_AREA_NAMESPACE,
        nested_path=ALG_AREA_PATH,
        value_kind="real",
    ),
    acdsee_region_field(
        "RegionALGAreaH",
        "h",
        "RegionALGAreaH",
        namespace_uri=ACDSEE_AREA_NAMESPACE,
        nested_path=ALG_AREA_PATH,
        value_kind="real",
    ),
    acdsee_region_field(
        "RegionDLYAreaX",
        "x",
        "RegionDLYAreaX",
        namespace_uri=ACDSEE_AREA_NAMESPACE,
        nested_path=DLY_AREA_PATH,
        value_kind="real",
    ),
    acdsee_region_field(
        "RegionDLYAreaY",
        "y",
        "RegionDLYAreaY",
        namespace_uri=ACDSEE_AREA_NAMESPACE,
        nested_path=DLY_AREA_PATH,
        value_kind="real",
    ),
    acdsee_region_field(
        "RegionDLYAreaW",
        "w",
        "RegionDLYAreaW",
        namespace_uri=ACDSEE_AREA_NAMESPACE,
        nested_path=DLY_AREA_PATH,
        value_kind="real",
    ),
    acdsee_region_field(
        "RegionDLYAreaH",
        "h",
        "RegionDLYAreaH",
        namespace_uri=ACDSEE_AREA_NAMESPACE,
        nested_path=DLY_AREA_PATH,
        value_kind="real",
    ),
)


def acdsee_regions_parent_spec_for_property(
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    return simple_struct_parent_spec_for_property(
        XMP_ACDSEE_REGION_PARENT_SPECS,
        property_name,
    )


def acdsee_regions_assignment_target(
    property_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-acdsee-rs" or separator != ":":
        return None
    parent_spec = XMP_ACDSEE_REGION_PARENT_SPECS[0]
    if not tag_name.startswith("Region"):
        return None
    for field_spec in XMP_ACDSEE_REGION_FIELD_SPECS:
        if tag_name == field_spec.readback_suffix:
            return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    return None


def acdsee_regions_field_specs_for_parent(
    parent_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    if parent_name == "RegionInfoACDSee":
        return XMP_ACDSEE_REGION_FIELD_SPECS
    return ()


def acdsee_regions_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for field_spec in XMP_ACDSEE_REGION_FIELD_SPECS:
        tag_ids[field_spec.readback_suffix] = "Regions"
    return tag_ids
