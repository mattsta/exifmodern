"""Reusable metadata for flat XMP struct adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type XmpSimpleStructShape = Literal["struct", "struct_list"]
type XmpSimpleStructListKind = Literal["Alt", "Bag", "Seq"]
type XmpSimpleStructValueKind = Literal[
    "boolean",
    "date",
    "integer",
    "lang_alt",
    "rational",
    "real",
    "text",
]


@dataclass(frozen=True)
class XmpSimpleStructParentSpec:
    parent_name: str
    property_name: str
    element_name: str
    group: str
    namespace_prefix: str
    struct_namespace_prefix: str
    struct_namespace_uri: str
    shape: XmpSimpleStructShape
    list_kind: XmpSimpleStructListKind | None = None


@dataclass(frozen=True)
class XmpSimpleStructPathStep:
    field_name: str
    namespace_uri: str | None = None
    list_kind: XmpSimpleStructListKind | None = None


@dataclass(frozen=True)
class XmpSimpleStructFieldSpec:
    suffix: str
    field_name: str
    readback_suffix: str
    value_kind: XmpSimpleStructValueKind
    namespace_uri: str | None = None
    nested_field_name: str | None = None
    nested_namespace_uri: str | None = None
    nested_list_kind: XmpSimpleStructListKind | None = None
    field_list_kind: XmpSimpleStructListKind | None = None
    nested_path: tuple[XmpSimpleStructPathStep, ...] = ()


@dataclass(frozen=True)
class XmpSimpleStructAssignmentTarget:
    parent_spec: XmpSimpleStructParentSpec
    field_spec: XmpSimpleStructFieldSpec


def simple_struct_parent_spec_for_property(
    parent_specs: tuple[XmpSimpleStructParentSpec, ...],
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    for parent_spec in parent_specs:
        if parent_spec.property_name == property_name:
            return parent_spec
    return None


def simple_struct_assignment_target(
    parent_specs: tuple[XmpSimpleStructParentSpec, ...],
    field_specs: tuple[XmpSimpleStructFieldSpec, ...],
    property_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if separator != ":":
        return None
    for parent_spec in parent_specs:
        if group != parent_spec.group or not tag_name.startswith(parent_spec.parent_name):
            continue
        field_suffix = tag_name.removeprefix(parent_spec.parent_name)
        field_spec = simple_struct_field_spec_for_suffix(field_specs, field_suffix)
        if field_spec is None:
            continue
        return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    return None


def simple_struct_field_spec_for_suffix(
    field_specs: tuple[XmpSimpleStructFieldSpec, ...],
    suffix: str,
) -> XmpSimpleStructFieldSpec | None:
    for field_spec in field_specs:
        if field_spec.suffix == suffix:
            return field_spec
    return None


def simple_struct_field_spec_for_field_name(
    field_specs: tuple[XmpSimpleStructFieldSpec, ...],
    field_name: str,
) -> XmpSimpleStructFieldSpec | None:
    for field_spec in field_specs:
        if field_spec.field_name == field_name:
            return field_spec
    return None


def simple_struct_readback_tag_ids(
    parent_specs: tuple[XmpSimpleStructParentSpec, ...],
    field_specs: tuple[XmpSimpleStructFieldSpec, ...],
) -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for parent_spec in parent_specs:
        for field_spec in field_specs:
            tag_ids[f"{parent_spec.parent_name}{field_spec.readback_suffix}"] = (
                parent_spec.element_name
            )
    return tag_ids


def simple_struct_nested_path_steps(
    field_spec: XmpSimpleStructFieldSpec,
) -> tuple[XmpSimpleStructPathStep, ...]:
    if field_spec.nested_path:
        return field_spec.nested_path
    if field_spec.nested_field_name is None:
        return ()
    return (
        XmpSimpleStructPathStep(
            field_name=field_spec.nested_field_name,
            namespace_uri=field_spec.nested_namespace_uri,
            list_kind=field_spec.nested_list_kind,
        ),
    )
