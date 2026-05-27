"""Source-grounded XMP ManifestItem struct adapter metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.xmp.structs.resource_ref import (
    XMP_RESOURCE_REF_FIELD_SPECS,
    XmpResourceRefFieldSpec,
    resource_ref_field_spec_for_field_name,
    resource_ref_field_spec_for_suffix,
)

type XmpManifestItemParentName = Literal["Manifest"]
type XmpManifestItemSimpleFieldName = Literal[
    "linkForm",
    "placedXResolution",
    "placedYResolution",
    "placedResolutionUnit",
]
type XmpManifestItemShape = Literal["struct_list"]
type XmpManifestItemListKind = Literal["Bag"]
type XmpManifestItemFieldKind = Literal["simple", "reference"]


@dataclass(frozen=True)
class XmpManifestItemParentSpec:
    parent_name: XmpManifestItemParentName
    property_name: str
    element_name: str
    shape: XmpManifestItemShape
    list_kind: XmpManifestItemListKind


@dataclass(frozen=True)
class XmpManifestItemSimpleFieldSpec:
    suffix: str
    field_name: XmpManifestItemSimpleFieldName
    readback_suffix: str
    namespace_prefix: Literal["stMfs", "xmpMM"]
    numeric_value: bool = False


@dataclass(frozen=True)
class XmpManifestItemAssignmentTarget:
    parent_spec: XmpManifestItemParentSpec
    field_kind: XmpManifestItemFieldKind
    simple_field_spec: XmpManifestItemSimpleFieldSpec | None
    reference_field_spec: XmpResourceRefFieldSpec | None


XMP_MANIFEST_ITEM_PARENT_SPECS: tuple[XmpManifestItemParentSpec, ...] = (
    XmpManifestItemParentSpec(
        parent_name="Manifest",
        property_name="XMP-xmpMM:Manifest",
        element_name="Manifest",
        shape="struct_list",
        list_kind="Bag",
    ),
)
XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS: tuple[XmpManifestItemSimpleFieldSpec, ...] = (
    XmpManifestItemSimpleFieldSpec("LinkForm", "linkForm", "LinkForm", "stMfs"),
    XmpManifestItemSimpleFieldSpec(
        "PlacedXResolution",
        "placedXResolution",
        "PlacedXResolution",
        "xmpMM",
        True,
    ),
    XmpManifestItemSimpleFieldSpec(
        "PlacedYResolution",
        "placedYResolution",
        "PlacedYResolution",
        "xmpMM",
        True,
    ),
    XmpManifestItemSimpleFieldSpec(
        "PlacedResolutionUnit",
        "placedResolutionUnit",
        "PlacedResolutionUnit",
        "xmpMM",
    ),
)


def manifest_item_parent_spec_for_property(
    property_name: str,
) -> XmpManifestItemParentSpec | None:
    for parent_spec in XMP_MANIFEST_ITEM_PARENT_SPECS:
        if parent_spec.property_name == property_name:
            return parent_spec
    return None


def manifest_item_assignment_target(
    property_name: str,
) -> XmpManifestItemAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-xmpMM" or separator != ":":
        return None
    parent_spec = XMP_MANIFEST_ITEM_PARENT_SPECS[0]
    if not tag_name.startswith(parent_spec.parent_name):
        return None
    field_suffix = tag_name.removeprefix(parent_spec.parent_name)
    simple_field_spec = manifest_item_simple_field_spec_for_suffix(field_suffix)
    if simple_field_spec is not None:
        return XmpManifestItemAssignmentTarget(
            parent_spec,
            "simple",
            simple_field_spec,
            None,
        )
    if not field_suffix.startswith("Reference"):
        return None
    reference_suffix = field_suffix.removeprefix("Reference")
    reference_field_spec = resource_ref_field_spec_for_suffix(reference_suffix)
    if reference_field_spec is None:
        return None
    return XmpManifestItemAssignmentTarget(
        parent_spec,
        "reference",
        None,
        reference_field_spec,
    )


def manifest_item_simple_field_spec_for_suffix(
    suffix: str,
) -> XmpManifestItemSimpleFieldSpec | None:
    for field_spec in XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS:
        if field_spec.suffix == suffix:
            return field_spec
    return None


def manifest_item_simple_field_spec_for_field_name(
    field_name: str,
) -> XmpManifestItemSimpleFieldSpec | None:
    for field_spec in XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS:
        if field_spec.field_name == field_name:
            return field_spec
    return None


def manifest_item_reference_field_spec_for_field_name(
    field_name: str,
) -> XmpResourceRefFieldSpec | None:
    return resource_ref_field_spec_for_field_name(field_name)


def manifest_item_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    parent_spec = XMP_MANIFEST_ITEM_PARENT_SPECS[0]
    for field_spec in XMP_MANIFEST_ITEM_SIMPLE_FIELD_SPECS:
        tag_ids[f"{parent_spec.parent_name}{field_spec.readback_suffix}"] = parent_spec.element_name
    for reference_field_spec in XMP_RESOURCE_REF_FIELD_SPECS:
        tag_ids[f"{parent_spec.parent_name}Reference{reference_field_spec.readback_suffix}"] = (
            parent_spec.element_name
        )
    return tag_ids


def manifest_item_supported_readback_names() -> tuple[str, ...]:
    return tuple(sorted(manifest_item_readback_tag_ids()))
