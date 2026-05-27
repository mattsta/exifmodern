"""XMP packet mutation primitives."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from xml.etree import ElementTree

from exifmodern.compatibility import EXIFTOOL_COMPATIBILITY_VERSION_TEXT
from exifmodern.formats.xmp.family2_delete import (
    XmpFamily2DeletePlan,
    XmpQualifiedProperty,
)
from exifmodern.formats.xmp.group_delete import XmpNamespaceDeletePlan
from exifmodern.formats.xmp.property_write import (
    XmpBooleanPropertyWrite,
    XmpJobRefFieldValue,
    XmpJobRefPropertyWrite,
    XmpLanguageCode,
    XmpLocalizedTextPropertyPatch,
    XmpLocalizedTextPropertyWrite,
    XmpLocalizedTextValue,
    XmpManifestItemFieldValue,
    XmpManifestItemPropertyWrite,
    XmpManifestItemReferenceFieldValue,
    XmpManifestItemSimpleFieldValue,
    XmpNamespaceRegistration,
    XmpPantryItemFieldValue,
    XmpPantryItemPropertyWrite,
    XmpPropertyDelete,
    XmpPropertySpec,
    XmpPropertyValueShape,
    XmpPropertyWritePlan,
    XmpRdfContainer,
    XmpResourceEventFieldValue,
    XmpResourceEventPropertyWrite,
    XmpResourceRefFieldValue,
    XmpResourceRefPropertyWrite,
    XmpSimpleStructFieldValue,
    XmpSimpleStructListPropertyWrite,
    XmpSimpleStructPropertyWrite,
    XmpTextListPropertyWrite,
    XmpTextPropertyWrite,
    XmpUserDefinedStructFieldWrite,
    XmpUserDefinedStructLangAltFieldWrite,
    XmpUserDefinedStructLangAltListFieldWrite,
    XmpUserDefinedStructListFieldWrite,
    XmpUserDefinedStructNestedFieldWrite,
    XmpUserDefinedStructPropertyWrite,
    XmpUserDefinedStructScalarFieldWrite,
    normalize_xmp_date_value,
    xmp_property_spec,
)
from exifmodern.formats.xmp.reader import RDF_NAMESPACE, XMP_META_NAMESPACE, decode_xmp_packet
from exifmodern.formats.xmp.structs.iptc import IPTC_CORE_NAMESPACE, IPTC_EXT_NAMESPACE
from exifmodern.formats.xmp.structs.prism import PRISM_NAMESPACE
from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructPathStep,
    simple_struct_nested_path_steps,
)

type XmlElement = ElementTree.Element[str]
type SimpleStructNestedElementKey = tuple[tuple[str, str, str], ...]

STJOB_NAMESPACE = "http://ns.adobe.com/xap/1.0/sType/Job#"
STMFS_NAMESPACE = "http://ns.adobe.com/xap/1.0/sType/ManifestItem#"
ST_DIM_NAMESPACE = "http://ns.adobe.com/xap/1.0/sType/Dimensions#"
ST_FNT_NAMESPACE = "http://ns.adobe.com/xap/1.0/sType/Font#"
ST_VER_NAMESPACE = "http://ns.adobe.com/xap/1.0/sType/Version#"
STEVT_NAMESPACE = "http://ns.adobe.com/xap/1.0/sType/ResourceEvent#"
STREF_NAMESPACE = "http://ns.adobe.com/xap/1.0/sType/ResourceRef#"
XMPG_NAMESPACE = "http://ns.adobe.com/xap/1.0/g/"
XMPG_IMG_NAMESPACE = "http://ns.adobe.com/xap/1.0/g/img/"
XMP_NOTE_NAMESPACE = "http://ns.adobe.com/xmp/note/"
XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
ACDSEE_REGION_NAMESPACE = "http://ns.acdsee.com/regions/"
ACDSEE_DIMENSIONS_NAMESPACE = "http://ns.acdsee.com/sType/Dimensions#"
ACDSEE_AREA_NAMESPACE = "http://ns.acdsee.com/sType/Area#"


@dataclass(frozen=True)
class XmpNamespaceMutationResult:
    packet: bytes
    deleted_properties: int


@dataclass(frozen=True)
class XmpFamily2MutationResult:
    packet: bytes
    deleted_properties: int


@dataclass(frozen=True)
class XmpPropertyMutationResult:
    packet: bytes
    changed_properties: int
    deleted_properties: int


XMP_NAMESPACE_PREFIXES = (
    ("x", XMP_META_NAMESPACE),
    ("rdf", RDF_NAMESPACE),
    ("MicrosoftPhoto", "http://ns.microsoft.com/photo/1.0/"),
    ("MP", "http://ns.microsoft.com/photo/1.2/"),
    ("MP1", "http://ns.microsoft.com/photo/1.1/"),
    ("apple-fi", "http://ns.apple.com/faceinfo/1.0/"),
    ("aux", "http://ns.adobe.com/exif/1.0/aux/"),
    ("acdsee-rs", ACDSEE_REGION_NAMESPACE),
    ("acdsee-stArea", ACDSEE_AREA_NAMESPACE),
    ("acdsee-stDim", ACDSEE_DIMENSIONS_NAMESPACE),
    ("crd", "http://ns.adobe.com/camera-raw-defaults/1.0/"),
    ("crs", "http://ns.adobe.com/camera-raw-settings/1.0/"),
    ("dc", "http://purl.org/dc/elements/1.1/"),
    ("exif", "http://ns.adobe.com/exif/1.0/"),
    ("hdr_metadata", "http://ns.adobe.com/hdr-metadata/1.0/"),
    ("hdrgm", "http://ns.adobe.com/hdr-gain-map/1.0/"),
    ("Iptc4xmpCore", IPTC_CORE_NAMESPACE),
    ("Iptc4xmpExt", IPTC_EXT_NAMESPACE),
    ("iptcCore", IPTC_CORE_NAMESPACE),
    ("iptcExt", IPTC_EXT_NAMESPACE),
    ("lr", "http://ns.adobe.com/lightroom/1.0/"),
    ("pdf", "http://ns.adobe.com/pdf/1.3/"),
    ("photoshop", "http://ns.adobe.com/photoshop/1.0/"),
    ("prism", PRISM_NAMESPACE),
    ("tiff", "http://ns.adobe.com/tiff/1.0/"),
    ("xmp", "http://ns.adobe.com/xap/1.0/"),
    ("xmpBJ", "http://ns.adobe.com/xap/1.0/bj/"),
    ("xmpDM", "http://ns.adobe.com/xmp/1.0/DynamicMedia/"),
    ("stEvt", STEVT_NAMESPACE),
    ("stDim", ST_DIM_NAMESPACE),
    ("stFnt", ST_FNT_NAMESPACE),
    ("stVer", ST_VER_NAMESPACE),
    ("stRef", STREF_NAMESPACE),
    ("stJob", STJOB_NAMESPACE),
    ("stMfs", STMFS_NAMESPACE),
    ("xmpG", XMPG_NAMESPACE),
    ("xmpGImg", XMPG_IMG_NAMESPACE),
    ("xmpMM", "http://ns.adobe.com/xap/1.0/mm/"),
    ("xmpNote", XMP_NOTE_NAMESPACE),
    ("xmpRights", "http://ns.adobe.com/xap/1.0/rights/"),
    ("xmpTPg", "http://ns.adobe.com/xap/1.0/t/pg/"),
)


def delete_xmp_namespace(packet: bytes, plan: XmpNamespaceDeletePlan) -> XmpNamespaceMutationResult:
    root = ElementTree.fromstring(decode_xmp_packet(packet))
    deleted_properties = remove_namespace_elements(root, plan.namespace_uri)
    if deleted_properties == 0:
        return XmpNamespaceMutationResult(packet=packet, deleted_properties=0)
    update_xmp_toolkit(root)
    rewritten = serialize_xmp_root(root)
    return XmpNamespaceMutationResult(packet=rewritten, deleted_properties=deleted_properties)


def delete_xmp_family2_groups(
    packet: bytes,
    plan: XmpFamily2DeletePlan,
) -> XmpFamily2MutationResult:
    if not plan.properties:
        return XmpFamily2MutationResult(packet=packet, deleted_properties=0)

    root = ElementTree.fromstring(decode_xmp_packet(packet))
    deleted_properties = remove_qualified_properties(root, plan.properties)
    if deleted_properties == 0:
        return XmpFamily2MutationResult(packet=packet, deleted_properties=0)
    update_xmp_toolkit(root)
    rewritten = serialize_xmp_root(root)
    return XmpFamily2MutationResult(packet=rewritten, deleted_properties=deleted_properties)


def apply_xmp_property_write_plan(
    packet: bytes,
    plan: XmpPropertyWritePlan,
) -> XmpPropertyMutationResult:
    if not plan.steps:
        return XmpPropertyMutationResult(packet=packet, changed_properties=0, deleted_properties=0)

    root = ElementTree.fromstring(decode_xmp_packet(packet))
    changed_properties = 0
    deleted_properties = 0
    for step in plan.steps:
        spec = xmp_property_spec_for_plan(plan, step.property_name)
        if isinstance(step, XmpLocalizedTextPropertyPatch):
            description = first_rdf_description(root)
            changed, deleted = patch_lang_alt_text_property(
                description,
                spec.namespace_uri,
                spec.element_name,
                step.writes,
                step.deletes,
            )
            changed_properties += changed
            deleted_properties += deleted
            continue
        deleted = delete_xmp_property_elements(root, spec.namespace_uri, spec.element_name)
        deleted_properties += deleted
        if isinstance(step, XmpPropertyDelete):
            changed_properties += 1 if deleted else 0
            continue
        description = first_rdf_description(root)
        if isinstance(step, XmpLocalizedTextPropertyWrite):
            write_lang_alt_text_property(
                description,
                spec.namespace_uri,
                spec.element_name,
                step.values,
            )
        elif isinstance(step, XmpJobRefPropertyWrite):
            write_job_ref_list_property(
                description,
                spec.namespace_uri,
                spec.element_name,
                spec.rdf_container or "Bag",
                step.values,
            )
        elif isinstance(step, XmpManifestItemPropertyWrite):
            write_manifest_item_list_property(
                description,
                spec.namespace_uri,
                spec.element_name,
                spec.rdf_container or "Bag",
                step.values,
            )
        elif isinstance(step, XmpPantryItemPropertyWrite):
            write_pantry_item_list_property(
                description,
                spec.namespace_uri,
                spec.element_name,
                spec.rdf_container or "Bag",
                step.values,
            )
        elif isinstance(step, XmpResourceRefPropertyWrite):
            if spec.rdf_container is None:
                write_resource_ref_property(
                    description,
                    spec.namespace_uri,
                    spec.element_name,
                    step.values,
                )
            else:
                write_resource_ref_list_property(
                    description,
                    spec.namespace_uri,
                    spec.element_name,
                    spec.rdf_container,
                    step.values,
                )
        elif isinstance(step, XmpResourceEventPropertyWrite):
            write_resource_event_list_property(
                description,
                spec.namespace_uri,
                spec.element_name,
                spec.rdf_container or "Seq",
                step.values,
            )
        elif isinstance(step, XmpSimpleStructListPropertyWrite):
            write_simple_struct_list_property_items(
                description,
                spec.namespace_uri,
                spec.element_name,
                spec.rdf_container or "Bag",
                step.parent_spec.struct_namespace_uri,
                step.item_groups,
            )
        elif isinstance(step, XmpSimpleStructPropertyWrite):
            if spec.rdf_container is None:
                write_simple_struct_property(
                    description,
                    spec.namespace_uri,
                    spec.element_name,
                    step.parent_spec.struct_namespace_uri,
                    step.values,
                )
            else:
                write_simple_struct_list_property(
                    description,
                    spec.namespace_uri,
                    spec.element_name,
                    spec.rdf_container,
                    step.parent_spec.struct_namespace_uri,
                    step.values,
                )
        elif isinstance(step, XmpUserDefinedStructPropertyWrite):
            write_user_defined_struct_property(description, step)
        elif isinstance(step, XmpTextListPropertyWrite):
            if spec.value_shape == "alt_text":
                write_default_lang_alt_text_property(
                    description,
                    spec.namespace_uri,
                    spec.element_name,
                    step.values,
                )
            else:
                write_container_text_property(
                    description,
                    spec.namespace_uri,
                    spec.element_name,
                    spec.rdf_container or "Bag",
                    step.values,
                )
        elif isinstance(step, XmpBooleanPropertyWrite):
            write_text_property(
                description,
                spec.namespace_uri,
                spec.element_name,
                "True" if step.value else "False",
            )
        elif isinstance(step, XmpTextPropertyWrite):
            if spec.value_shape == "job_ref_name":
                write_job_ref_name(description, step.value)
            else:
                write_text_property(
                    description,
                    spec.namespace_uri,
                    spec.element_name,
                    xmp_text_for_shape(step.value, spec.value_shape),
                )
        changed_properties += 1

    if changed_properties == 0 and deleted_properties == 0:
        return XmpPropertyMutationResult(packet=packet, changed_properties=0, deleted_properties=0)

    update_xmp_toolkit(root)
    rewritten = serialize_xmp_root(root, plan.namespace_registry)
    return XmpPropertyMutationResult(
        packet=rewritten,
        changed_properties=changed_properties,
        deleted_properties=deleted_properties,
    )


def remove_extended_xmp_reference(packet: bytes) -> XmpPropertyMutationResult:
    root = ElementTree.fromstring(decode_xmp_packet(packet))
    deleted_properties = delete_xmp_property_elements(
        root,
        XMP_NOTE_NAMESPACE,
        "HasExtendedXMP",
    )
    if deleted_properties == 0:
        return XmpPropertyMutationResult(
            packet=packet,
            changed_properties=0,
            deleted_properties=0,
        )
    update_xmp_toolkit(root)
    rewritten = serialize_xmp_root(root)
    return XmpPropertyMutationResult(
        packet=rewritten,
        changed_properties=0,
        deleted_properties=deleted_properties,
    )


def xmp_property_spec_for_plan(
    plan: XmpPropertyWritePlan,
    property_name: str,
) -> XmpPropertySpec:
    for spec in plan.generated_specs:
        if spec.property_name == property_name:
            return spec
    return xmp_property_spec(property_name)


def xmp_text_for_shape(value: str, value_shape: XmpPropertyValueShape) -> str:
    if value_shape == "date":
        return normalize_xmp_date_value(value) or value
    return value


def delete_xmp_property_elements(root: XmlElement, namespace_uri: str, element_name: str) -> int:
    deleted = 0
    for parent in root.iter():
        for child in tuple(parent):
            namespace, local_name = expanded_name_parts(child.tag)
            if namespace == namespace_uri and local_name == element_name:
                parent.remove(child)
                deleted += 1
    return deleted


def remove_qualified_properties(
    root: XmlElement,
    properties: frozenset[XmpQualifiedProperty],
) -> int:
    deleted = 0
    for element in root.iter():
        deleted += delete_matching_attributes(element, properties)
        for child in tuple(element):
            namespace, local_name = expanded_name_parts(child.tag)
            if namespace is None:
                continue
            if XmpQualifiedProperty(namespace, local_name) in properties:
                element.remove(child)
                deleted += 1
    return deleted


def delete_matching_attributes(
    element: XmlElement,
    properties: frozenset[XmpQualifiedProperty],
) -> int:
    deleted = 0
    for attribute_name in tuple(element.attrib):
        namespace, local_name = expanded_name_parts(attribute_name)
        if namespace is None:
            continue
        if XmpQualifiedProperty(namespace, local_name) in properties:
            del element.attrib[attribute_name]
            deleted += 1
    return deleted


def first_rdf_description(root: XmlElement) -> XmlElement:
    for element in root.iter(f"{{{RDF_NAMESPACE}}}Description"):
        return element
    rdf = root.find(f".//{{{RDF_NAMESPACE}}}RDF")
    if rdf is None:
        rdf = ElementTree.SubElement(root, f"{{{RDF_NAMESPACE}}}RDF")
    return ElementTree.SubElement(rdf, f"{{{RDF_NAMESPACE}}}Description")


def write_text_property(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    value: str,
) -> None:
    element = ElementTree.SubElement(description, f"{{{namespace_uri}}}{element_name}")
    element.text = value


def write_container_text_property(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    container_name: XmpRdfContainer,
    values: tuple[str, ...],
) -> None:
    element = ElementTree.SubElement(description, f"{{{namespace_uri}}}{element_name}")
    container = ElementTree.SubElement(element, f"{{{RDF_NAMESPACE}}}{container_name}")
    for value in values:
        item = ElementTree.SubElement(container, f"{{{RDF_NAMESPACE}}}li")
        item.text = value


def write_lang_alt_text_property(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    values: tuple[XmpLocalizedTextValue, ...],
) -> None:
    element = ElementTree.SubElement(description, f"{{{namespace_uri}}}{element_name}")
    container = ElementTree.SubElement(element, f"{{{RDF_NAMESPACE}}}Alt")
    for value in values:
        item = ElementTree.SubElement(
            container,
            f"{{{RDF_NAMESPACE}}}li",
            {f"{{{XML_NAMESPACE}}}lang": value.language_code},
        )
        item.text = value.value


def patch_lang_alt_text_property(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    writes: tuple[XmpLocalizedTextValue, ...],
    deletes: tuple[XmpLanguageCode, ...],
) -> tuple[int, int]:
    element = direct_child(description, namespace_uri, element_name)
    if element is None:
        if not writes:
            return (0, 0)
        write_lang_alt_text_property(description, namespace_uri, element_name, writes)
        return (1, 0)

    container = direct_child(element, RDF_NAMESPACE, "Alt")
    if container is None:
        if not writes:
            return (0, 0)
        container = ElementTree.SubElement(element, f"{{{RDF_NAMESPACE}}}Alt")

    write_languages = frozenset(value.language_code.lower() for value in writes)
    delete_languages = frozenset(language.lower() for language in deletes)
    removed = 0
    for item in tuple(container):
        namespace, local_name = expanded_name_parts(item.tag)
        if namespace != RDF_NAMESPACE or local_name != "li":
            continue
        language = item.attrib.get(f"{{{XML_NAMESPACE}}}lang", "x-default").lower()
        if language not in write_languages and language not in delete_languages:
            continue
        container.remove(item)
        removed += 1

    for value in writes:
        item = ElementTree.Element(
            f"{{{RDF_NAMESPACE}}}li",
            {f"{{{XML_NAMESPACE}}}lang": value.language_code},
        )
        item.text = value.value
        if value.language_code == "x-default":
            container.insert(0, item)
        else:
            container.append(item)

    if not tuple(container):
        description.remove(element)
        return (1 if removed else 0, removed)
    return (1 if removed or writes else 0, removed)


def direct_child(parent: XmlElement, namespace_uri: str, element_name: str) -> XmlElement | None:
    for child in tuple(parent):
        namespace, local_name = expanded_name_parts(child.tag)
        if namespace == namespace_uri and local_name == element_name:
            return child
    return None


def write_default_lang_alt_text_property(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    values: tuple[str, ...],
) -> None:
    localized_values: list[XmpLocalizedTextValue] = []
    for value in values:
        localized_values.append(XmpLocalizedTextValue("x-default", value))
    write_lang_alt_text_property(description, namespace_uri, element_name, tuple(localized_values))


def write_resource_ref_property(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    values: tuple[XmpResourceRefFieldValue, ...],
) -> None:
    element = ElementTree.SubElement(
        description,
        f"{{{namespace_uri}}}{element_name}",
        {f"{{{RDF_NAMESPACE}}}parseType": "Resource"},
    )
    for value in values:
        item = ElementTree.SubElement(element, f"{{{STREF_NAMESPACE}}}{value.field_name}")
        item.text = value.value


def write_job_ref_list_property(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    container_name: XmpRdfContainer,
    values: tuple[XmpJobRefFieldValue, ...],
) -> None:
    element = ElementTree.SubElement(description, f"{{{namespace_uri}}}{element_name}")
    container = ElementTree.SubElement(element, f"{{{RDF_NAMESPACE}}}{container_name}")
    list_item = ElementTree.SubElement(container, f"{{{RDF_NAMESPACE}}}li")
    for value in values:
        item = ElementTree.SubElement(list_item, f"{{{STJOB_NAMESPACE}}}{value.field_name}")
        item.text = value.value


def write_resource_ref_list_property(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    container_name: XmpRdfContainer,
    values: tuple[XmpResourceRefFieldValue, ...],
) -> None:
    element = ElementTree.SubElement(description, f"{{{namespace_uri}}}{element_name}")
    container = ElementTree.SubElement(element, f"{{{RDF_NAMESPACE}}}{container_name}")
    list_item = ElementTree.SubElement(
        container,
        f"{{{RDF_NAMESPACE}}}li",
        {f"{{{RDF_NAMESPACE}}}parseType": "Resource"},
    )
    for value in values:
        item = ElementTree.SubElement(list_item, f"{{{STREF_NAMESPACE}}}{value.field_name}")
        item.text = value.value


def write_manifest_item_list_property(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    container_name: XmpRdfContainer,
    values: tuple[XmpManifestItemFieldValue, ...],
) -> None:
    element = ElementTree.SubElement(description, f"{{{namespace_uri}}}{element_name}")
    container = ElementTree.SubElement(element, f"{{{RDF_NAMESPACE}}}{container_name}")
    list_item = ElementTree.SubElement(
        container,
        f"{{{RDF_NAMESPACE}}}li",
        {f"{{{RDF_NAMESPACE}}}parseType": "Resource"},
    )
    reference_values: list[XmpManifestItemReferenceFieldValue] = []
    for value in values:
        if isinstance(value, XmpManifestItemSimpleFieldValue):
            item = ElementTree.SubElement(
                list_item,
                f"{{{manifest_item_simple_field_namespace(value)}}}{value.field_name}",
            )
            item.text = value.value
        elif isinstance(value, XmpManifestItemReferenceFieldValue):
            reference_values.append(value)
    if reference_values:
        reference = ElementTree.SubElement(
            list_item,
            f"{{{STMFS_NAMESPACE}}}reference",
            {f"{{{RDF_NAMESPACE}}}parseType": "Resource"},
        )
        for value in reference_values:
            item = ElementTree.SubElement(reference, f"{{{STREF_NAMESPACE}}}{value.field_name}")
            item.text = value.value


def manifest_item_simple_field_namespace(value: XmpManifestItemSimpleFieldValue) -> str:
    if value.field_name in {"placedXResolution", "placedYResolution", "placedResolutionUnit"}:
        return "http://ns.adobe.com/xap/1.0/mm/"
    return STMFS_NAMESPACE


def write_pantry_item_list_property(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    container_name: XmpRdfContainer,
    values: tuple[XmpPantryItemFieldValue, ...],
) -> None:
    element = ElementTree.SubElement(description, f"{{{namespace_uri}}}{element_name}")
    container = ElementTree.SubElement(element, f"{{{RDF_NAMESPACE}}}{container_name}")
    list_item = ElementTree.SubElement(
        container,
        f"{{{RDF_NAMESPACE}}}li",
        {f"{{{RDF_NAMESPACE}}}parseType": "Resource"},
    )
    for value in values:
        item = ElementTree.SubElement(list_item, f"{{{namespace_uri}}}{value.field_name}")
        item.text = value.value


def write_resource_event_list_property(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    container_name: XmpRdfContainer,
    values: tuple[XmpResourceEventFieldValue, ...],
) -> None:
    element = ElementTree.SubElement(description, f"{{{namespace_uri}}}{element_name}")
    container = ElementTree.SubElement(element, f"{{{RDF_NAMESPACE}}}{container_name}")
    list_item = ElementTree.SubElement(
        container,
        f"{{{RDF_NAMESPACE}}}li",
        {f"{{{RDF_NAMESPACE}}}parseType": "Resource"},
    )
    for value in values:
        item = ElementTree.SubElement(list_item, f"{{{STEVT_NAMESPACE}}}{value.field_name}")
        item.text = value.value


def write_simple_struct_property(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    struct_namespace_uri: str,
    values: tuple[XmpSimpleStructFieldValue, ...],
) -> None:
    element = ElementTree.SubElement(
        description,
        f"{{{namespace_uri}}}{element_name}",
        {f"{{{RDF_NAMESPACE}}}parseType": "Resource"},
    )
    write_simple_struct_fields(element, struct_namespace_uri, values)


def write_simple_struct_list_property(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    container_name: XmpRdfContainer,
    struct_namespace_uri: str,
    values: tuple[XmpSimpleStructFieldValue, ...],
) -> None:
    write_simple_struct_list_property_items(
        description,
        namespace_uri,
        element_name,
        container_name,
        struct_namespace_uri,
        (values,),
    )


def write_simple_struct_list_property_items(
    description: XmlElement,
    namespace_uri: str,
    element_name: str,
    container_name: XmpRdfContainer,
    struct_namespace_uri: str,
    item_groups: tuple[tuple[XmpSimpleStructFieldValue, ...], ...],
) -> None:
    element = ElementTree.SubElement(description, f"{{{namespace_uri}}}{element_name}")
    container = ElementTree.SubElement(element, f"{{{RDF_NAMESPACE}}}{container_name}")
    for item_group in item_groups:
        list_item = ElementTree.SubElement(
            container,
            f"{{{RDF_NAMESPACE}}}li",
            {f"{{{RDF_NAMESPACE}}}parseType": "Resource"},
        )
        write_simple_struct_fields(list_item, struct_namespace_uri, item_group)


def write_simple_struct_fields(
    element: XmlElement,
    struct_namespace_uri: str,
    values: tuple[XmpSimpleStructFieldValue, ...],
) -> None:
    nested_elements: dict[SimpleStructNestedElementKey, XmlElement] = {}
    list_field_elements: dict[tuple[int, str, str, str], XmlElement] = {}
    for value in values:
        target_element = simple_struct_nested_write_target(
            element,
            nested_elements,
            struct_namespace_uri,
            value,
        )
        write_simple_struct_field(
            target_element,
            struct_namespace_uri,
            list_field_elements,
            value,
        )


def simple_struct_nested_write_target(
    element: XmlElement,
    nested_elements: dict[SimpleStructNestedElementKey, XmlElement],
    struct_namespace_uri: str,
    value: XmpSimpleStructFieldValue,
) -> XmlElement:
    target_element = element
    key_parts: list[tuple[str, str, str]] = []
    for path_step in simple_struct_nested_path_steps(value.field_spec):
        target_element = simple_struct_path_step_write_target(
            target_element,
            nested_elements,
            struct_namespace_uri,
            key_parts,
            path_step,
        )
    return target_element


def simple_struct_path_step_write_target(
    element: XmlElement,
    nested_elements: dict[SimpleStructNestedElementKey, XmlElement],
    struct_namespace_uri: str,
    key_parts: list[tuple[str, str, str]],
    path_step: XmpSimpleStructPathStep,
) -> XmlElement:
    namespace_uri = path_step.namespace_uri or struct_namespace_uri
    path_kind = path_step.list_kind or "Resource"
    key_parts.append((namespace_uri, path_step.field_name, path_kind))
    path_key = tuple(key_parts)
    existing_element = nested_elements.get(path_key)
    if existing_element is not None:
        return existing_element
    if path_step.list_kind is None:
        nested_element = ElementTree.SubElement(
            element,
            f"{{{namespace_uri}}}{path_step.field_name}",
            {f"{{{RDF_NAMESPACE}}}parseType": "Resource"},
        )
        nested_elements[path_key] = nested_element
        return nested_element
    nested_element = ElementTree.SubElement(
        element,
        f"{{{namespace_uri}}}{path_step.field_name}",
    )
    container = ElementTree.SubElement(
        nested_element,
        f"{{{RDF_NAMESPACE}}}{path_step.list_kind}",
    )
    list_item = ElementTree.SubElement(
        container,
        f"{{{RDF_NAMESPACE}}}li",
        {f"{{{RDF_NAMESPACE}}}parseType": "Resource"},
    )
    nested_elements[path_key] = list_item
    return list_item


def write_simple_struct_field(
    element: XmlElement,
    struct_namespace_uri: str,
    list_field_elements: dict[tuple[int, str, str, str], XmlElement],
    value: XmpSimpleStructFieldValue,
) -> None:
    field_namespace_uri = value.field_spec.namespace_uri or struct_namespace_uri
    if value.field_spec.field_list_kind is not None:
        list_key = (
            id(element),
            field_namespace_uri,
            value.field_spec.field_name,
            value.field_spec.field_list_kind,
        )
        container = list_field_elements.get(list_key)
        if container is None:
            item = ElementTree.SubElement(
                element,
                f"{{{field_namespace_uri}}}{value.field_spec.field_name}",
            )
            container = ElementTree.SubElement(
                item,
                f"{{{RDF_NAMESPACE}}}{value.field_spec.field_list_kind}",
            )
            list_field_elements[list_key] = container
        list_item = ElementTree.SubElement(container, f"{{{RDF_NAMESPACE}}}li")
        list_item.text = value.value
        return
    item = ElementTree.SubElement(
        element,
        f"{{{field_namespace_uri}}}{value.field_spec.field_name}",
    )
    if value.field_spec.value_kind == "lang_alt":
        container = ElementTree.SubElement(item, f"{{{RDF_NAMESPACE}}}Alt")
        list_item = ElementTree.SubElement(
            container,
            f"{{{RDF_NAMESPACE}}}li",
            {f"{{{XML_NAMESPACE}}}lang": "x-default"},
        )
        list_item.text = value.value
        return
    item.text = value.value


def write_user_defined_struct_property(
    description: XmlElement,
    write: XmpUserDefinedStructPropertyWrite,
) -> None:
    element = ElementTree.SubElement(
        description,
        f"{{{write.namespace_uri}}}{write.element_name}",
        {f"{{{RDF_NAMESPACE}}}parseType": "Resource"},
    )
    if write.struct_type_resource is not None:
        ElementTree.SubElement(
            element,
            f"{{{RDF_NAMESPACE}}}type",
            {f"{{{RDF_NAMESPACE}}}resource": write.struct_type_resource},
        )
    for field in write.fields or write.lang_alt_bag_fields:
        write_user_defined_struct_field(element, write.namespace_uri, field)


def write_user_defined_struct_field(
    element: XmlElement,
    struct_namespace_uri: str,
    field: XmpUserDefinedStructFieldWrite,
) -> None:
    field_namespace_uri = user_defined_field_namespace_uri(struct_namespace_uri, field)
    if isinstance(field, XmpUserDefinedStructLangAltListFieldWrite):
        field_element = ElementTree.SubElement(
            element,
            f"{{{field_namespace_uri}}}{field.field_name}",
        )
        bag = ElementTree.SubElement(field_element, f"{{{RDF_NAMESPACE}}}Bag")
        for item_group in field.item_groups:
            bag_item = ElementTree.SubElement(bag, f"{{{RDF_NAMESPACE}}}li")
            alt = ElementTree.SubElement(bag_item, f"{{{RDF_NAMESPACE}}}Alt")
            for localized_value in item_group:
                alt_item = ElementTree.SubElement(
                    alt,
                    f"{{{RDF_NAMESPACE}}}li",
                    {f"{{{XML_NAMESPACE}}}lang": localized_value.language_code},
                )
                alt_item.text = localized_value.value
        return
    if isinstance(field, XmpUserDefinedStructLangAltFieldWrite):
        field_element = ElementTree.SubElement(
            element,
            f"{{{field_namespace_uri}}}{field.field_name}",
        )
        alt = ElementTree.SubElement(field_element, f"{{{RDF_NAMESPACE}}}Alt")
        for localized_value in field.values:
            alt_item = ElementTree.SubElement(
                alt,
                f"{{{RDF_NAMESPACE}}}li",
                {f"{{{XML_NAMESPACE}}}lang": localized_value.language_code},
            )
            alt_item.text = localized_value.value
        return
    if isinstance(field, XmpUserDefinedStructScalarFieldWrite):
        if field.resource:
            ElementTree.SubElement(
                element,
                f"{{{field_namespace_uri}}}{field.field_name}",
                {f"{{{RDF_NAMESPACE}}}resource": field.value},
            )
            return
        ElementTree.SubElement(
            element, f"{{{field_namespace_uri}}}{field.field_name}"
        ).text = field.value
        return
    if isinstance(field, XmpUserDefinedStructListFieldWrite):
        field_element = ElementTree.SubElement(
            element,
            f"{{{field_namespace_uri}}}{field.field_name}",
        )
        container = ElementTree.SubElement(
            field_element,
            f"{{{RDF_NAMESPACE}}}{field.container_name}",
        )
        for value in field.values:
            ElementTree.SubElement(container, f"{{{RDF_NAMESPACE}}}li").text = value
        return
    if isinstance(field, XmpUserDefinedStructNestedFieldWrite):
        nested_element = ElementTree.SubElement(
            element,
            f"{{{field_namespace_uri}}}{field.field_name}",
            {f"{{{RDF_NAMESPACE}}}parseType": "Resource"},
        )
        for nested_field in field.fields:
            write_user_defined_struct_field(nested_element, struct_namespace_uri, nested_field)


def user_defined_field_namespace_uri(
    struct_namespace_uri: str,
    field: XmpUserDefinedStructFieldWrite,
) -> str:
    if isinstance(field, XmpUserDefinedStructLangAltListFieldWrite):
        return field.namespace_uri or struct_namespace_uri
    if isinstance(field, XmpUserDefinedStructLangAltFieldWrite):
        return field.namespace_uri or struct_namespace_uri
    if isinstance(field, XmpUserDefinedStructScalarFieldWrite):
        return field.namespace_uri or struct_namespace_uri
    if isinstance(field, XmpUserDefinedStructListFieldWrite):
        return field.namespace_uri or struct_namespace_uri
    if isinstance(field, XmpUserDefinedStructNestedFieldWrite):
        return field.namespace_uri or struct_namespace_uri
    return struct_namespace_uri


def write_job_ref_name(description: XmlElement, value: str) -> None:
    element = ElementTree.SubElement(
        description,
        "{http://ns.adobe.com/xap/1.0/bj/}JobRef",
    )
    bag = ElementTree.SubElement(element, f"{{{RDF_NAMESPACE}}}Bag")
    item = ElementTree.SubElement(bag, f"{{{RDF_NAMESPACE}}}li")
    ElementTree.SubElement(item, f"{{{STJOB_NAMESPACE}}}name").text = value


def remove_namespace_elements(root: XmlElement, namespace_uri: str) -> int:
    deleted_properties = 0
    for parent in root.iter():
        deleted_properties += remove_direct_namespace_children(parent, namespace_uri)
    return deleted_properties


def remove_direct_namespace_children(parent: XmlElement, namespace_uri: str) -> int:
    deleted = 0
    for child in tuple(parent):
        if element_namespace(child) != namespace_uri:
            continue
        parent.remove(child)
        deleted += 1
    return deleted


def element_namespace(element: XmlElement) -> str | None:
    namespace, _ = expanded_name_parts(element.tag)
    return namespace


def expanded_name_parts(name: str) -> tuple[str | None, str]:
    if not name.startswith("{") or "}" not in name:
        return None, name
    namespace, local_name = name[1:].split("}", 1)
    return namespace, local_name


def update_xmp_toolkit(root: XmlElement) -> None:
    root.set(
        f"{{{XMP_META_NAMESPACE}}}xmptk",
        f"Image::ExifTool {EXIFTOOL_COMPATIBILITY_VERSION_TEXT}",
    )


def serialize_xmp_root(
    root: XmlElement,
    namespace_registry: tuple[XmpNamespaceRegistration, ...] = (),
) -> bytes:
    with scoped_xmp_namespace_registration(namespace_registry):
        return bytes(ElementTree.tostring(root, encoding="utf-8", short_empty_elements=True))


@contextmanager
def scoped_xmp_namespace_registration(
    namespace_registry: tuple[XmpNamespaceRegistration, ...] = (),
) -> Iterator[None]:
    namespace_map: dict[str, str] = ElementTree._namespace_map  # type: ignore[attr-defined]
    original_namespace_map = dict(namespace_map)
    try:
        register_xmp_namespaces(namespace_registry)
        yield
    finally:
        namespace_map.clear()
        namespace_map.update(original_namespace_map)


def register_xmp_namespaces(
    namespace_registry: tuple[XmpNamespaceRegistration, ...] = (),
) -> None:
    for prefix, namespace_uri in XMP_NAMESPACE_PREFIXES:
        ElementTree.register_namespace(prefix, namespace_uri)
    for registration in namespace_registry:
        ElementTree.register_namespace(registration.prefix, registration.namespace_uri)
