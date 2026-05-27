"""Source-grounded EXIF-in-XMP struct adapter metadata."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructParentSpec,
    simple_struct_field_spec_for_field_name,
    simple_struct_field_spec_for_suffix,
    simple_struct_parent_spec_for_property,
    simple_struct_readback_tag_ids,
)

EXIF_NAMESPACE = "http://ns.adobe.com/exif/1.0/"

XMP_EXIF_STRUCT_PARENT_SPECS: tuple[XmpSimpleStructParentSpec, ...] = (
    XmpSimpleStructParentSpec(
        parent_name="CFAPattern",
        property_name="XMP-exif:CFAPattern",
        element_name="CFAPattern",
        group="XMP-exif",
        namespace_prefix="exif",
        struct_namespace_prefix="exif",
        struct_namespace_uri=EXIF_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="DeviceSettingDescription",
        property_name="XMP-exif:DeviceSettingDescription",
        element_name="DeviceSettingDescription",
        group="XMP-exif",
        namespace_prefix="exif",
        struct_namespace_prefix="exif",
        struct_namespace_uri=EXIF_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="Flash",
        property_name="XMP-exif:Flash",
        element_name="Flash",
        group="XMP-exif",
        namespace_prefix="exif",
        struct_namespace_prefix="exif",
        struct_namespace_uri=EXIF_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="OECF",
        property_name="XMP-exif:Opto-ElectricConvFactor",
        element_name="OECF",
        group="XMP-exif",
        namespace_prefix="exif",
        struct_namespace_prefix="exif",
        struct_namespace_uri=EXIF_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="SpatialFrequencyResponse",
        property_name="XMP-exif:SpatialFrequencyResponse",
        element_name="SpatialFrequencyResponse",
        group="XMP-exif",
        namespace_prefix="exif",
        struct_namespace_prefix="exif",
        struct_namespace_uri=EXIF_NAMESPACE,
        shape="struct",
    ),
)

XMP_EXIF_STRUCT_FIELD_SPECS: tuple[XmpSimpleStructFieldSpec, ...] = (
    XmpSimpleStructFieldSpec("Columns", "Columns", "Columns", "integer"),
    XmpSimpleStructFieldSpec("Rows", "Rows", "Rows", "integer"),
    XmpSimpleStructFieldSpec(
        "Names",
        "Names",
        "Names",
        "text",
        field_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "ValuesInteger",
        "Values",
        "Values",
        "integer",
        field_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "ValuesRational",
        "Values",
        "Values",
        "rational",
        field_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "Settings",
        "Settings",
        "Settings",
        "text",
        field_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec("Fired", "Fired", "Fired", "boolean"),
    XmpSimpleStructFieldSpec("Return", "Return", "Return", "integer"),
    XmpSimpleStructFieldSpec("Mode", "Mode", "Mode", "integer"),
    XmpSimpleStructFieldSpec("Function", "Function", "Function", "boolean"),
    XmpSimpleStructFieldSpec("RedEyeMode", "RedEyeMode", "RedEyeMode", "boolean"),
)


def exif_struct_parent_spec_for_property(
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    parent_spec = simple_struct_parent_spec_for_property(
        XMP_EXIF_STRUCT_PARENT_SPECS,
        property_name,
    )
    if parent_spec is not None:
        return parent_spec
    for candidate in XMP_EXIF_STRUCT_PARENT_SPECS:
        if property_name == f"{candidate.group}:{candidate.element_name}":
            return candidate
    return None


def exif_struct_assignment_target(
    property_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-exif" or separator != ":":
        return None
    for parent_spec in sorted(
        XMP_EXIF_STRUCT_PARENT_SPECS,
        key=lambda item: len(item.parent_name),
        reverse=True,
    ):
        if not tag_name.startswith(parent_spec.parent_name):
            continue
        field_suffix = tag_name.removeprefix(parent_spec.parent_name)
        field_spec = exif_struct_field_spec_for_parent_and_suffix(
            parent_spec.parent_name,
            field_suffix,
        )
        if field_spec is not None:
            return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    return None


def exif_struct_field_specs_for_parent(
    parent_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    if parent_name == "CFAPattern":
        return exif_struct_field_specs_for_suffixes(("Columns", "Rows", "ValuesInteger"))
    if parent_name == "DeviceSettingDescription":
        return exif_struct_field_specs_for_suffixes(("Columns", "Rows", "Settings"))
    if parent_name == "Flash":
        return exif_struct_field_specs_for_suffixes(
            ("Fired", "Return", "Mode", "Function", "RedEyeMode"),
        )
    if parent_name in {"OECF", "SpatialFrequencyResponse"}:
        return exif_struct_field_specs_for_suffixes(
            ("Columns", "Rows", "Names", "ValuesRational"),
        )
    return ()


def exif_struct_field_specs_for_suffixes(
    suffixes: tuple[str, ...],
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    specs: list[XmpSimpleStructFieldSpec] = []
    for suffix in suffixes:
        field_spec = exif_struct_field_spec_for_suffix(suffix)
        if field_spec is not None:
            specs.append(field_spec)
    return tuple(specs)


def exif_struct_field_spec_for_parent_and_suffix(
    parent_name: str,
    suffix: str,
) -> XmpSimpleStructFieldSpec | None:
    for field_spec in exif_struct_field_specs_for_parent(parent_name):
        if field_spec.suffix == suffix or field_spec.readback_suffix == suffix:
            return field_spec
    return None


def exif_struct_field_spec_for_suffix(suffix: str) -> XmpSimpleStructFieldSpec | None:
    return simple_struct_field_spec_for_suffix(XMP_EXIF_STRUCT_FIELD_SPECS, suffix)


def exif_struct_field_spec_for_field_name(field_name: str) -> XmpSimpleStructFieldSpec | None:
    return simple_struct_field_spec_for_field_name(XMP_EXIF_STRUCT_FIELD_SPECS, field_name)


def exif_struct_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for parent_spec in XMP_EXIF_STRUCT_PARENT_SPECS:
        field_specs = exif_struct_field_specs_for_parent(parent_spec.parent_name)
        tag_ids.update(simple_struct_readback_tag_ids((parent_spec,), field_specs))
    return tag_ids
