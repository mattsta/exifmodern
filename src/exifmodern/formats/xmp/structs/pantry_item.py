"""Source-grounded XMP PantryItem struct adapter metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type XmpPantryItemParentName = Literal["Pantry"]
type XmpPantryItemFieldName = Literal["InstanceID"]
type XmpPantryItemShape = Literal["struct_list"]
type XmpPantryItemListKind = Literal["Bag"]


@dataclass(frozen=True)
class XmpPantryItemParentSpec:
    parent_name: XmpPantryItemParentName
    property_name: str
    element_name: str
    shape: XmpPantryItemShape
    list_kind: XmpPantryItemListKind


@dataclass(frozen=True)
class XmpPantryItemFieldSpec:
    suffix: str
    field_name: XmpPantryItemFieldName
    readback_suffix: str


@dataclass(frozen=True)
class XmpPantryItemAssignmentTarget:
    parent_spec: XmpPantryItemParentSpec
    field_spec: XmpPantryItemFieldSpec


XMP_PANTRY_ITEM_PARENT_SPECS: tuple[XmpPantryItemParentSpec, ...] = (
    XmpPantryItemParentSpec(
        parent_name="Pantry",
        property_name="XMP-xmpMM:Pantry",
        element_name="Pantry",
        shape="struct_list",
        list_kind="Bag",
    ),
)
XMP_PANTRY_ITEM_FIELD_SPECS: tuple[XmpPantryItemFieldSpec, ...] = (
    XmpPantryItemFieldSpec("InstanceID", "InstanceID", "InstanceID"),
)


def pantry_item_parent_spec_for_property(
    property_name: str,
) -> XmpPantryItemParentSpec | None:
    for parent_spec in XMP_PANTRY_ITEM_PARENT_SPECS:
        if parent_spec.property_name == property_name:
            return parent_spec
    return None


def pantry_item_assignment_target(
    property_name: str,
) -> XmpPantryItemAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-xmpMM" or separator != ":":
        return None
    parent_spec = XMP_PANTRY_ITEM_PARENT_SPECS[0]
    if not tag_name.startswith(parent_spec.parent_name):
        return None
    field_suffix = tag_name.removeprefix(parent_spec.parent_name)
    field_spec = pantry_item_field_spec_for_suffix(field_suffix)
    if field_spec is None:
        return None
    return XmpPantryItemAssignmentTarget(parent_spec, field_spec)


def pantry_item_field_spec_for_suffix(suffix: str) -> XmpPantryItemFieldSpec | None:
    for field_spec in XMP_PANTRY_ITEM_FIELD_SPECS:
        if field_spec.suffix == suffix:
            return field_spec
    return None


def pantry_item_field_spec_for_field_name(field_name: str) -> XmpPantryItemFieldSpec | None:
    for field_spec in XMP_PANTRY_ITEM_FIELD_SPECS:
        if field_spec.field_name == field_name:
            return field_spec
    return None


def pantry_item_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    parent_spec = XMP_PANTRY_ITEM_PARENT_SPECS[0]
    for field_spec in XMP_PANTRY_ITEM_FIELD_SPECS:
        tag_ids[f"{parent_spec.parent_name}{field_spec.readback_suffix}"] = parent_spec.element_name
    return tag_ids
