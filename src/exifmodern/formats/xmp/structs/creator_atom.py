"""Source-grounded Adobe creatorAtom XMP struct adapter metadata."""

from __future__ import annotations

from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructParentSpec,
    simple_struct_parent_spec_for_property,
)

CREATOR_ATOM_NAMESPACE = "http://ns.adobe.com/creatorAtom/1.0/"

XMP_CREATOR_ATOM_PARENT_SPECS: tuple[XmpSimpleStructParentSpec, ...] = (
    XmpSimpleStructParentSpec(
        parent_name="AeProjectLink",
        property_name="XMP-creatorAtom:AeProjectLink",
        element_name="aeProjectLink",
        group="XMP-creatorAtom",
        namespace_prefix="creatorAtom",
        struct_namespace_prefix="creatorAtom",
        struct_namespace_uri=CREATOR_ATOM_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="MacAtom",
        property_name="XMP-creatorAtom:MacAtom",
        element_name="macAtom",
        group="XMP-creatorAtom",
        namespace_prefix="creatorAtom",
        struct_namespace_prefix="creatorAtom",
        struct_namespace_uri=CREATOR_ATOM_NAMESPACE,
        shape="struct",
    ),
    XmpSimpleStructParentSpec(
        parent_name="WindowsAtom",
        property_name="XMP-creatorAtom:WindowsAtom",
        element_name="windowsAtom",
        group="XMP-creatorAtom",
        namespace_prefix="creatorAtom",
        struct_namespace_prefix="creatorAtom",
        struct_namespace_uri=CREATOR_ATOM_NAMESPACE,
        shape="struct",
    ),
)

XMP_CREATOR_ATOM_FIELD_SPECS_BY_PARENT: tuple[
    tuple[str, tuple[XmpSimpleStructFieldSpec, ...]],
    ...,
] = (
    (
        "AeProjectLink",
        (
            XmpSimpleStructFieldSpec(
                "RenderTimeStamp",
                "renderTimeStamp",
                "AeProjectLinkRenderTimeStamp",
                "integer",
            ),
            XmpSimpleStructFieldSpec(
                "CompositionID",
                "compositionID",
                "AeProjectLinkCompositionID",
                "text",
            ),
            XmpSimpleStructFieldSpec(
                "RenderQueueItemID",
                "renderQueueItemID",
                "AeProjectLinkRenderQueueItemID",
                "text",
            ),
            XmpSimpleStructFieldSpec(
                "RenderOutputModuleIndex",
                "renderOutputModuleIndex",
                "AeProjectLinkRenderOutputModuleIndex",
                "text",
            ),
            XmpSimpleStructFieldSpec(
                "FullPath",
                "fullPath",
                "AeProjectLinkFullPath",
                "text",
            ),
        ),
    ),
    (
        "MacAtom",
        (
            XmpSimpleStructFieldSpec(
                "ApplicationCode",
                "applicationCode",
                "MacAtomApplicationCode",
                "text",
            ),
            XmpSimpleStructFieldSpec(
                "InvocationAppleEvent",
                "invocationAppleEvent",
                "MacAtomInvocationAppleEvent",
                "text",
            ),
            XmpSimpleStructFieldSpec(
                "PosixProjectPath",
                "posixProjectPath",
                "MacAtomPosixProjectPath",
                "text",
            ),
        ),
    ),
    (
        "WindowsAtom",
        (
            XmpSimpleStructFieldSpec(
                "Extension",
                "extension",
                "WindowsAtomExtension",
                "text",
            ),
            XmpSimpleStructFieldSpec(
                "InvocationFlags",
                "invocationFlags",
                "WindowsAtomInvocationFlags",
                "text",
            ),
            XmpSimpleStructFieldSpec(
                "UncProjectPath",
                "uncProjectPath",
                "WindowsAtomUncProjectPath",
                "text",
            ),
        ),
    ),
)

XMP_CREATOR_ATOM_FIELD_SPECS: tuple[XmpSimpleStructFieldSpec, ...] = tuple(
    field_spec
    for _, field_specs in XMP_CREATOR_ATOM_FIELD_SPECS_BY_PARENT
    for field_spec in field_specs
)


def creator_atom_parent_spec_for_property(
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    return simple_struct_parent_spec_for_property(XMP_CREATOR_ATOM_PARENT_SPECS, property_name)


def creator_atom_assignment_target(
    property_name: str,
) -> XmpSimpleStructAssignmentTarget | None:
    group, separator, tag_name = property_name.partition(":")
    if group != "XMP-creatorAtom" or separator != ":":
        return None
    for parent_spec in XMP_CREATOR_ATOM_PARENT_SPECS:
        for field_spec in creator_atom_field_specs_for_parent(parent_spec.parent_name):
            if tag_name == field_spec.readback_suffix:
                return XmpSimpleStructAssignmentTarget(parent_spec, field_spec)
    return None


def creator_atom_field_specs_for_parent(
    parent_name: str,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    for candidate_parent_name, field_specs in XMP_CREATOR_ATOM_FIELD_SPECS_BY_PARENT:
        if candidate_parent_name == parent_name:
            return field_specs
    return ()


def creator_atom_readback_tag_ids() -> dict[str, str]:
    tag_ids: dict[str, str] = {}
    for parent_spec in XMP_CREATOR_ATOM_PARENT_SPECS:
        for field_spec in creator_atom_field_specs_for_parent(parent_spec.parent_name):
            tag_ids[field_spec.readback_suffix] = parent_spec.element_name
    return tag_ids
