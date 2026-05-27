"""Source-grounded XMP ResourceRef struct adapter metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type XmpResourceRefParentName = Literal["DerivedFrom", "Ingredients", "ManagedFrom", "RenditionOf"]
type XmpResourceRefFieldName = Literal[
    "documentID",
    "instanceID",
    "manager",
    "managerVariant",
    "manageTo",
    "manageUI",
    "renditionClass",
    "renditionParams",
    "versionID",
    "filePath",
    "fromPart",
    "lastModifyDate",
    "originalDocumentID",
    "lastURL",
    "linkForm",
    "linkCategory",
    "partMapping",
    "toPart",
]
type XmpResourceRefShape = Literal["struct", "struct_list"]
type XmpResourceRefListKind = Literal["Bag"]


@dataclass(frozen=True)
class XmpResourceRefParentSpec:
    parent_name: XmpResourceRefParentName
    property_name: str
    element_name: str
    shape: XmpResourceRefShape
    list_kind: XmpResourceRefListKind | None = None


@dataclass(frozen=True)
class XmpResourceRefFieldSpec:
    suffix: str
    field_name: XmpResourceRefFieldName
    readback_suffix: str
    date_value: bool = False


@dataclass(frozen=True)
class XmpResourceRefAssignmentTarget:
    parent_spec: XmpResourceRefParentSpec
    field_spec: XmpResourceRefFieldSpec


XMP_RESOURCE_REF_PARENT_SPECS: tuple[XmpResourceRefParentSpec, ...] = (
    XmpResourceRefParentSpec(
        parent_name="DerivedFrom",
        property_name="XMP-xmpMM:DerivedFrom",
        element_name="DerivedFrom",
        shape="struct",
    ),
    XmpResourceRefParentSpec(
        parent_name="Ingredients",
        property_name="XMP-xmpMM:Ingredients",
        element_name="Ingredients",
        shape="struct_list",
        list_kind="Bag",
    ),
    XmpResourceRefParentSpec(
        parent_name="ManagedFrom",
        property_name="XMP-xmpMM:ManagedFrom",
        element_name="ManagedFrom",
        shape="struct",
    ),
    XmpResourceRefParentSpec(
        parent_name="RenditionOf",
        property_name="XMP-xmpMM:RenditionOf",
        element_name="RenditionOf",
        shape="struct",
    ),
)
XMP_RESOURCE_REF_FIELD_SPECS: tuple[XmpResourceRefFieldSpec, ...] = (
    XmpResourceRefFieldSpec("DocumentID", "documentID", "DocumentID"),
    XmpResourceRefFieldSpec("InstanceID", "instanceID", "InstanceID"),
    XmpResourceRefFieldSpec("Manager", "manager", "Manager"),
    XmpResourceRefFieldSpec("ManagerVariant", "managerVariant", "ManagerVariant"),
    XmpResourceRefFieldSpec("ManageTo", "manageTo", "ManageTo"),
    XmpResourceRefFieldSpec("ManageUI", "manageUI", "ManageUI"),
    XmpResourceRefFieldSpec("RenditionClass", "renditionClass", "RenditionClass"),
    XmpResourceRefFieldSpec("RenditionParams", "renditionParams", "RenditionParams"),
    XmpResourceRefFieldSpec("VersionID", "versionID", "VersionID"),
    XmpResourceRefFieldSpec("FilePath", "filePath", "FilePath"),
    XmpResourceRefFieldSpec("FromPart", "fromPart", "FromPart"),
    XmpResourceRefFieldSpec("LastModifyDate", "lastModifyDate", "LastModifyDate", True),
    XmpResourceRefFieldSpec("OriginalDocumentID", "originalDocumentID", "OriginalDocumentID"),
    XmpResourceRefFieldSpec("LastURL", "lastURL", "LastURL"),
    XmpResourceRefFieldSpec("LinkForm", "linkForm", "LinkForm"),
    XmpResourceRefFieldSpec("LinkCategory", "linkCategory", "LinkCategory"),
    XmpResourceRefFieldSpec("PartMapping", "partMapping", "PartMapping"),
    XmpResourceRefFieldSpec("ToPart", "toPart", "ToPart"),
)


def resource_ref_parent_spec_for_property(
    property_name: str,
) -> XmpResourceRefParentSpec | None:
    for parent_spec in XMP_RESOURCE_REF_PARENT_SPECS:
        if parent_spec.property_name == property_name:
            return parent_spec
    return None


def resource_ref_assignment_target(
    property_name: str,
) -> XmpResourceRefAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-xmpMM" or separator != ":":
        return None
    for parent_spec in XMP_RESOURCE_REF_PARENT_SPECS:
        if not tag_name.startswith(parent_spec.parent_name):
            continue
        field_suffix = tag_name.removeprefix(parent_spec.parent_name)
        field_spec = resource_ref_field_spec_for_suffix(field_suffix)
        if field_spec is None:
            continue
        return XmpResourceRefAssignmentTarget(parent_spec, field_spec)
    return None


def resource_ref_field_spec_for_suffix(
    suffix: str,
) -> XmpResourceRefFieldSpec | None:
    for field_spec in XMP_RESOURCE_REF_FIELD_SPECS:
        if field_spec.suffix == suffix:
            return field_spec
    return None


def resource_ref_field_spec_for_field_name(
    field_name: str,
) -> XmpResourceRefFieldSpec | None:
    for field_spec in XMP_RESOURCE_REF_FIELD_SPECS:
        if field_spec.field_name == field_name:
            return field_spec
    return None


def resource_ref_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for parent_spec in XMP_RESOURCE_REF_PARENT_SPECS:
        for field_spec in XMP_RESOURCE_REF_FIELD_SPECS:
            tag_ids[f"{parent_spec.parent_name}{field_spec.readback_suffix}"] = (
                parent_spec.element_name
            )
    return tag_ids
