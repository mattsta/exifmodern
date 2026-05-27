"""Source-grounded XMP ResourceEvent struct adapter metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type XmpResourceEventParentName = Literal["History"]
type XmpResourceEventFieldName = Literal[
    "action",
    "changed",
    "instanceID",
    "parameters",
    "softwareAgent",
    "when",
]
type XmpResourceEventShape = Literal["struct_list"]
type XmpResourceEventListKind = Literal["Seq"]


@dataclass(frozen=True)
class XmpResourceEventParentSpec:
    parent_name: XmpResourceEventParentName
    property_name: str
    element_name: str
    shape: XmpResourceEventShape
    list_kind: XmpResourceEventListKind


@dataclass(frozen=True)
class XmpResourceEventFieldSpec:
    suffix: str
    field_name: XmpResourceEventFieldName
    readback_suffix: str
    date_value: bool = False


@dataclass(frozen=True)
class XmpResourceEventAssignmentTarget:
    parent_spec: XmpResourceEventParentSpec
    field_spec: XmpResourceEventFieldSpec


XMP_RESOURCE_EVENT_PARENT_SPECS: tuple[XmpResourceEventParentSpec, ...] = (
    XmpResourceEventParentSpec(
        parent_name="History",
        property_name="XMP-xmpMM:History",
        element_name="History",
        shape="struct_list",
        list_kind="Seq",
    ),
)
XMP_RESOURCE_EVENT_FIELD_SPECS: tuple[XmpResourceEventFieldSpec, ...] = (
    XmpResourceEventFieldSpec("Action", "action", "Action"),
    XmpResourceEventFieldSpec("Changed", "changed", "Changed"),
    XmpResourceEventFieldSpec("InstanceID", "instanceID", "InstanceID"),
    XmpResourceEventFieldSpec("Parameters", "parameters", "Parameters"),
    XmpResourceEventFieldSpec("SoftwareAgent", "softwareAgent", "SoftwareAgent"),
    XmpResourceEventFieldSpec("When", "when", "When", True),
)


def resource_event_parent_spec_for_property(
    property_name: str,
) -> XmpResourceEventParentSpec | None:
    for parent_spec in XMP_RESOURCE_EVENT_PARENT_SPECS:
        if parent_spec.property_name == property_name:
            return parent_spec
    return None


def resource_event_assignment_target(
    property_name: str,
) -> XmpResourceEventAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-xmpMM" or separator != ":":
        return None
    for parent_spec in XMP_RESOURCE_EVENT_PARENT_SPECS:
        if not tag_name.startswith(parent_spec.parent_name):
            continue
        field_suffix = tag_name.removeprefix(parent_spec.parent_name)
        field_spec = resource_event_field_spec_for_suffix(field_suffix)
        if field_spec is None:
            continue
        return XmpResourceEventAssignmentTarget(parent_spec, field_spec)
    return None


def resource_event_field_spec_for_suffix(
    suffix: str,
) -> XmpResourceEventFieldSpec | None:
    for field_spec in XMP_RESOURCE_EVENT_FIELD_SPECS:
        if field_spec.suffix == suffix:
            return field_spec
    return None


def resource_event_field_spec_for_field_name(
    field_name: str,
) -> XmpResourceEventFieldSpec | None:
    for field_spec in XMP_RESOURCE_EVENT_FIELD_SPECS:
        if field_spec.field_name == field_name:
            return field_spec
    return None


def resource_event_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for parent_spec in XMP_RESOURCE_EVENT_PARENT_SPECS:
        for field_spec in XMP_RESOURCE_EVENT_FIELD_SPECS:
            tag_ids[f"{parent_spec.parent_name}{field_spec.readback_suffix}"] = (
                parent_spec.element_name
            )
    return tag_ids
