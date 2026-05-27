"""Source-grounded XMP JobRef struct adapter metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type XmpJobRefParentName = Literal["JobRef"]
type XmpJobRefFieldName = Literal["id", "name", "url"]
type XmpJobRefShape = Literal["struct_list"]
type XmpJobRefListKind = Literal["Bag"]


@dataclass(frozen=True)
class XmpJobRefParentSpec:
    parent_name: XmpJobRefParentName
    property_name: str
    element_name: str
    shape: XmpJobRefShape
    list_kind: XmpJobRefListKind


@dataclass(frozen=True)
class XmpJobRefFieldSpec:
    suffix: str
    field_name: XmpJobRefFieldName
    readback_suffix: str


@dataclass(frozen=True)
class XmpJobRefAssignmentTarget:
    parent_spec: XmpJobRefParentSpec
    field_spec: XmpJobRefFieldSpec


XMP_JOB_REF_PARENT_SPECS: tuple[XmpJobRefParentSpec, ...] = (
    XmpJobRefParentSpec(
        parent_name="JobRef",
        property_name="XMP-xmpBJ:JobRef",
        element_name="JobRef",
        shape="struct_list",
        list_kind="Bag",
    ),
)
XMP_JOB_REF_FIELD_SPECS: tuple[XmpJobRefFieldSpec, ...] = (
    XmpJobRefFieldSpec("Id", "id", "Id"),
    XmpJobRefFieldSpec("Name", "name", "Name"),
    XmpJobRefFieldSpec("Url", "url", "Url"),
)


def job_ref_parent_spec_for_property(property_name: str) -> XmpJobRefParentSpec | None:
    for parent_spec in XMP_JOB_REF_PARENT_SPECS:
        if parent_spec.property_name == property_name:
            return parent_spec
    return None


def job_ref_assignment_target(property_name: str) -> XmpJobRefAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-xmpBJ" or separator != ":":
        return None
    for parent_spec in XMP_JOB_REF_PARENT_SPECS:
        if not tag_name.startswith(parent_spec.parent_name):
            continue
        field_suffix = tag_name.removeprefix(parent_spec.parent_name)
        field_spec = job_ref_field_spec_for_suffix(field_suffix)
        if field_spec is None:
            continue
        return XmpJobRefAssignmentTarget(parent_spec, field_spec)
    return None


def job_ref_field_spec_for_suffix(suffix: str) -> XmpJobRefFieldSpec | None:
    for field_spec in XMP_JOB_REF_FIELD_SPECS:
        if field_spec.suffix == suffix:
            return field_spec
    return None


def job_ref_field_spec_for_field_name(field_name: str) -> XmpJobRefFieldSpec | None:
    for field_spec in XMP_JOB_REF_FIELD_SPECS:
        if field_spec.field_name == field_name:
            return field_spec
    return None


def job_ref_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for parent_spec in XMP_JOB_REF_PARENT_SPECS:
        for field_spec in XMP_JOB_REF_FIELD_SPECS:
            tag_ids[f"{parent_spec.parent_name}{field_spec.readback_suffix}"] = (
                parent_spec.element_name
            )
    return tag_ids
