"""Source-grounded XMP paged-text struct adapter metadata."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructParentSpec,
    simple_struct_field_spec_for_field_name,
    simple_struct_parent_spec_for_property,
)

XMPG_NAMESPACE = "http://ns.adobe.com/xap/1.0/g/"
ST_DIM_NAMESPACE = "http://ns.adobe.com/xap/1.0/sType/Dimensions#"
ST_FNT_NAMESPACE = "http://ns.adobe.com/xap/1.0/sType/Font#"

XMP_PAGED_TEXT_PARENT_SPECS: tuple[XmpSimpleStructParentSpec, ...] = (
    XmpSimpleStructParentSpec(
        parent_name="MaxPageSize",
        property_name="XMP-xmpTPg:MaxPageSize",
        element_name="MaxPageSize",
        group="XMP-xmpTPg",
        namespace_prefix="xmpTPg",
        struct_namespace_prefix="stDim",
        struct_namespace_uri=ST_DIM_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="Fonts",
        property_name="XMP-xmpTPg:Fonts",
        element_name="Fonts",
        group="XMP-xmpTPg",
        namespace_prefix="xmpTPg",
        struct_namespace_prefix="stFnt",
        struct_namespace_uri=ST_FNT_NAMESPACE,
        shape="struct_list",
        list_kind="Bag",
    ),
    XmpSimpleStructParentSpec(
        parent_name="Colorants",
        property_name="XMP-xmpTPg:Colorants",
        element_name="Colorants",
        group="XMP-xmpTPg",
        namespace_prefix="xmpTPg",
        struct_namespace_prefix="xmpG",
        struct_namespace_uri=XMPG_NAMESPACE,
        shape="struct_list",
        list_kind="Seq",
    ),
    XmpSimpleStructParentSpec(
        parent_name="SwatchGroups",
        property_name="XMP-xmpTPg:SwatchGroups",
        element_name="SwatchGroups",
        group="XMP-xmpTPg",
        namespace_prefix="xmpTPg",
        struct_namespace_prefix="xmpG",
        struct_namespace_uri=XMPG_NAMESPACE,
        shape="struct_list",
        list_kind="Seq",
    ),
)

XMP_PAGED_TEXT_FIELD_SPECS: tuple[XmpSimpleStructFieldSpec, ...] = (
    XmpSimpleStructFieldSpec("W", "w", "W", "real"),
    XmpSimpleStructFieldSpec("H", "h", "H", "real"),
    XmpSimpleStructFieldSpec("Unit", "unit", "Unit", "text"),
    XmpSimpleStructFieldSpec("FontName", "fontName", "FontName", "text"),
    XmpSimpleStructFieldSpec("FontFamily", "fontFamily", "FontFamily", "text"),
    XmpSimpleStructFieldSpec("FontFace", "fontFace", "FontFace", "text"),
    XmpSimpleStructFieldSpec("FontType", "fontType", "FontType", "text"),
    XmpSimpleStructFieldSpec("FontVersion", "versionString", "FontVersion", "text"),
    XmpSimpleStructFieldSpec("FontComposite", "composite", "FontComposite", "boolean"),
    XmpSimpleStructFieldSpec("FontFileName", "fontFileName", "FontFileName", "text"),
    XmpSimpleStructFieldSpec("ColorantSwatchName", "swatchName", "ColorantSwatchName", "text"),
    XmpSimpleStructFieldSpec("ColorantMode", "mode", "ColorantMode", "text"),
    XmpSimpleStructFieldSpec("ColorantType", "type", "ColorantType", "text"),
    XmpSimpleStructFieldSpec("ColorantCyan", "cyan", "ColorantCyan", "real"),
    XmpSimpleStructFieldSpec("ColorantMagenta", "magenta", "ColorantMagenta", "real"),
    XmpSimpleStructFieldSpec("ColorantYellow", "yellow", "ColorantYellow", "real"),
    XmpSimpleStructFieldSpec("ColorantBlack", "black", "ColorantBlack", "real"),
    XmpSimpleStructFieldSpec("ColorantRed", "red", "ColorantRed", "integer"),
    XmpSimpleStructFieldSpec("ColorantGreen", "green", "ColorantGreen", "integer"),
    XmpSimpleStructFieldSpec("ColorantBlue", "blue", "ColorantBlue", "integer"),
    XmpSimpleStructFieldSpec("ColorantGray", "gray", "ColorantGray", "integer"),
    XmpSimpleStructFieldSpec("ColorantL", "L", "ColorantL", "real"),
    XmpSimpleStructFieldSpec("ColorantA", "A", "ColorantA", "integer"),
    XmpSimpleStructFieldSpec("ColorantB", "B", "ColorantB", "integer"),
    XmpSimpleStructFieldSpec("ColorantTint", "tint", "ColorantTint", "integer"),
    XmpSimpleStructFieldSpec("SwatchGroupName", "groupName", "SwatchGroupName", "text"),
    XmpSimpleStructFieldSpec("SwatchGroupType", "groupType", "SwatchGroupType", "integer"),
    XmpSimpleStructFieldSpec(
        "SwatchColorantSwatchName",
        "swatchName",
        "SwatchColorantSwatchName",
        "text",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantMode",
        "mode",
        "SwatchColorantMode",
        "text",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantType",
        "type",
        "SwatchColorantType",
        "text",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantCyan",
        "cyan",
        "SwatchColorantCyan",
        "real",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantMagenta",
        "magenta",
        "SwatchColorantMagenta",
        "real",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantYellow",
        "yellow",
        "SwatchColorantYellow",
        "real",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantBlack",
        "black",
        "SwatchColorantBlack",
        "real",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantRed",
        "red",
        "SwatchColorantRed",
        "integer",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantGreen",
        "green",
        "SwatchColorantGreen",
        "integer",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantBlue",
        "blue",
        "SwatchColorantBlue",
        "integer",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantGray",
        "gray",
        "SwatchColorantGray",
        "integer",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantL",
        "L",
        "SwatchColorantL",
        "real",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantA",
        "A",
        "SwatchColorantA",
        "integer",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantB",
        "B",
        "SwatchColorantB",
        "integer",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
    XmpSimpleStructFieldSpec(
        "SwatchColorantTint",
        "tint",
        "SwatchColorantTint",
        "integer",
        nested_field_name="Colorants",
        nested_namespace_uri=XMPG_NAMESPACE,
        nested_list_kind="Seq",
    ),
)


def paged_text_parent_spec_for_property(property_name: str) -> XmpSimpleStructParentSpec | None:
    return simple_struct_parent_spec_for_property(XMP_PAGED_TEXT_PARENT_SPECS, property_name)


def paged_text_assignment_target(property_name: str) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-xmpTPg" or separator != ":":
        return None
    font_target = paged_text_unprefixed_assignment_target("Fonts", tag_name)
    if font_target is not None:
        return font_target
    colorant_target = paged_text_unprefixed_assignment_target("Colorants", tag_name)
    if colorant_target is not None:
        return colorant_target
    swatch_group_target = paged_text_swatch_group_assignment_target(tag_name)
    if swatch_group_target is not None:
        return swatch_group_target
    for parent_spec in XMP_PAGED_TEXT_PARENT_SPECS:
        if not tag_name.startswith(parent_spec.parent_name):
            continue
        field_suffix = tag_name.removeprefix(parent_spec.parent_name)
        field_spec = paged_text_field_spec_for_suffix(field_suffix)
        if field_spec is not None:
            return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
        if parent_spec.parent_name == "Fonts":
            return paged_text_font_alias_assignment_target(parent_spec, field_suffix)
        if parent_spec.parent_name == "Colorants":
            return paged_text_colorant_alias_assignment_target(parent_spec, field_suffix)
    return None


def paged_text_unprefixed_assignment_target(
    parent_name: str,
    tag_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    parent_spec = paged_text_parent_spec_by_name(parent_name)
    if parent_spec is None:
        return None
    field_spec = paged_text_field_spec_for_suffix(tag_name)
    if field_spec is None:
        return None
    if field_spec not in paged_text_field_specs_for_parent(parent_name):
        return None
    return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)


def paged_text_parent_spec_by_name(parent_name: str) -> XmpSimpleStructParentSpec | None:
    for parent_spec in XMP_PAGED_TEXT_PARENT_SPECS:
        if parent_spec.parent_name == parent_name:
            return parent_spec
    return None


def paged_text_font_alias_assignment_target(
    parent_spec: XmpSimpleStructParentSpec,
    field_suffix: str,
) -> XmpSimpleStructAssignmentTarget | None:
    field_spec = paged_text_field_spec_for_suffix(f"Font{field_suffix}")
    if field_spec is None:
        return None
    return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)


def paged_text_colorant_alias_assignment_target(
    parent_spec: XmpSimpleStructParentSpec,
    field_suffix: str,
) -> XmpSimpleStructAssignmentTarget | None:
    field_spec = paged_text_field_spec_for_suffix(f"Colorant{field_suffix}")
    if field_spec is None:
        return None
    return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)


def paged_text_swatch_group_assignment_target(
    tag_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    parent_spec = paged_text_parent_spec_by_name("SwatchGroups")
    if parent_spec is None:
        return None
    field_spec = paged_text_field_spec_for_suffix(tag_name)
    if field_spec is not None and field_spec in paged_text_field_specs_for_parent("SwatchGroups"):
        return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    if tag_name.startswith("SwatchGroupsColorants"):
        suffix = tag_name.removeprefix("SwatchGroupsColorants")
        field_spec = paged_text_field_spec_for_suffix(f"SwatchColorant{suffix}")
        if field_spec is not None:
            return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    if tag_name.startswith("SwatchGroups"):
        suffix = tag_name.removeprefix("SwatchGroups")
        field_spec = paged_text_field_spec_for_suffix(f"SwatchGroup{suffix}")
        if field_spec is not None:
            return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    return None


def paged_text_field_specs_for_parent(
    parent_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    if parent_name == "MaxPageSize":
        return tuple(
            field_spec
            for field_spec in XMP_PAGED_TEXT_FIELD_SPECS
            if field_spec.suffix in {"W", "H", "Unit"}
        )
    if parent_name == "Fonts":
        return tuple(
            field_spec
            for field_spec in XMP_PAGED_TEXT_FIELD_SPECS
            if field_spec.suffix.startswith("Font")
        )
    if parent_name == "Colorants":
        return tuple(
            field_spec
            for field_spec in XMP_PAGED_TEXT_FIELD_SPECS
            if field_spec.suffix.startswith("Colorant")
        )
    if parent_name == "SwatchGroups":
        return tuple(
            field_spec
            for field_spec in XMP_PAGED_TEXT_FIELD_SPECS
            if field_spec.suffix.startswith("Swatch")
        )
    return ()


def paged_text_field_spec_for_suffix(suffix: str) -> XmpSimpleStructFieldSpec | None:
    for field_spec in XMP_PAGED_TEXT_FIELD_SPECS:
        if field_spec.suffix == suffix:
            return field_spec
    return None


def paged_text_field_spec_for_field_name(field_name: str) -> XmpSimpleStructFieldSpec | None:
    return simple_struct_field_spec_for_field_name(XMP_PAGED_TEXT_FIELD_SPECS, field_name)


def paged_text_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for parent_spec in XMP_PAGED_TEXT_PARENT_SPECS:
        for field_spec in paged_text_field_specs_for_parent(parent_spec.parent_name):
            if parent_spec.parent_name == "MaxPageSize":
                tag_ids[f"{parent_spec.parent_name}{field_spec.readback_suffix}"] = (
                    parent_spec.element_name
                )
            else:
                tag_ids[field_spec.readback_suffix] = parent_spec.element_name
    return tag_ids
