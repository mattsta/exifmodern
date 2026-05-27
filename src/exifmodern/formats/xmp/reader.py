"""Small XMP packet reader for currently proven parity slices."""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree

from exifmodern.formats.xmp.structs.acdsee_regions import (
    ACDSEE_REGION_NAMESPACE,
)
from exifmodern.formats.xmp.structs.creator_atom import (
    CREATOR_ATOM_NAMESPACE,
)
from exifmodern.formats.xmp.structs.exif_extended import (
    EXIF_EXTENDED_NAMESPACE,
)
from exifmodern.formats.xmp.structs.ics import (
    ICS_NAMESPACE,
)
from exifmodern.formats.xmp.structs.iptc import (
    IPTC_CORE_NAMESPACE,
    IPTC_EXT_NAMESPACE,
)
from exifmodern.formats.xmp.structs.job_ref import (
    job_ref_field_spec_for_field_name,
    job_ref_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.manifest_item import (
    manifest_item_parent_spec_for_property,
    manifest_item_reference_field_spec_for_field_name,
    manifest_item_simple_field_spec_for_field_name,
)
from exifmodern.formats.xmp.structs.pantry_item import (
    pantry_item_field_spec_for_field_name,
    pantry_item_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.photoshop import (
    PHOTOSHOP_NAMESPACE,
)
from exifmodern.formats.xmp.structs.prism import PRISM_NAMESPACE
from exifmodern.formats.xmp.structs.registry import (
    xmp_struct_field_specs_for_parent,
    xmp_struct_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.resource_event import (
    resource_event_field_spec_for_field_name,
    resource_event_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.resource_ref import (
    resource_ref_field_spec_for_field_name,
    resource_ref_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructFieldSpec,
    XmpSimpleStructListKind,
    XmpSimpleStructParentSpec,
    XmpSimpleStructPathStep,
    simple_struct_nested_path_steps,
)
from exifmodern.json_types import JsonArray, JsonObject, JsonValue

type XmpGroup = str
type XmpTagName = str
type XmpNamespaceUri = str
type XmpTagValue = str | int | bool | list[str]
type XmpSourceStructScalarValue = str | int | float | bool | None
type XmpSourceStructArrayValue = (
    list[XmpSourceStructScalarValue] | list[str] | list[int] | list[float] | list[bool] | list[None]
)
type XmpSourceStructValue = XmpSourceStructScalarValue | XmpSourceStructArrayValue

RDF_NAMESPACE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XMP_META_NAMESPACE = "adobe:ns:meta/"
XMP_BOOLEAN_TAG_NAMES = (
    "BaseRenditionIsHDR",
    "DistortionCorrectionAlreadyApplied",
    "EnhanceDenoiseAlreadyApplied",
    "EnhanceDetailsAlreadyApplied",
    "EnhanceSuperResolutionAlreadyApplied",
    "FujiRatingAlreadyApplied",
    "HasVisibleOverprint",
    "HasVisibleTransparency",
    "IsMergedHDR",
    "IsMergedPanorama",
    "LateralChromaticAberrationCorrectionAlreadyApplied",
    "Marked",
    "SceneReferred",
    "VignetteCorrectionAlreadyApplied",
)
XMP_DATE_TAG_NAMES = (
    "CreateDate",
    "CreationDate",
    "DateCreated",
    "DateTime",
    "DateTimeDigitized",
    "DateTimeOriginal",
    "GPSTimeStamp",
    "AudioModDate",
    "MetadataDate",
    "MetadataModDate",
    "ModDate",
    "ModifyDate",
    "VideoModDate",
)


@dataclass(frozen=True)
class XmpNamespaceSpec:
    group: XmpGroup
    uri: XmpNamespaceUri
    tag_renames: dict[XmpTagName, XmpTagName]


@dataclass(frozen=True)
class XmpSourceStructField:
    group: XmpGroup
    tag: XmpTagName
    value: XmpSourceStructValue
    uri_path: str
    struct_fields: tuple[XmpSourceStructField, ...] = ()


@dataclass(frozen=True)
class XmpSourceStructListItem:
    fields: tuple[XmpSourceStructField, ...]
    source_index: int
    source_path: str


@dataclass(frozen=True)
class XmpSourceStructElement:
    group: XmpGroup
    tag: XmpTagName
    value: XmpSourceStructValue
    uri_path: str
    list_container: XmpSimpleStructListKind | None = None
    struct_list_items: tuple[XmpSourceStructListItem, ...] = ()


XMP_EXIFTOOL_MAIN_GROUP_ORDER: tuple[XmpGroup, ...] = (
    # The upstream XMP main table declares the
    # source order used by companion nested XMP renderers.
    "XMP-x",
    "XMP-rdf",
    "XMP-dc",
    "XMP-xmp",
    "XMP-xmpDM",
    "XMP-xmpRights",
    "XMP-xmpNote",
    "XMP-xmpMM",
    "XMP-xmpBJ",
    "XMP-xmpTPg",
    "XMP-pdf",
    "XMP-photoshop",
    "XMP-crd",
    "XMP-crs",
    "XMP-aux",
    "XMP-tiff",
    "XMP-exif",
    "XMP-exifEX",
    "XMP-iptcCore",
    "XMP-iptcExt",
)

XMP_NAMESPACE_SPECS = (
    XmpNamespaceSpec("XMP-x", XMP_META_NAMESPACE, {"xmptk": "XMPToolkit"}),
    XmpNamespaceSpec(
        "XMP-microsoft",
        "http://ns.microsoft.com/photo/1.0/",
        {
            "CreatorAppId": "CreatorAppID",
        },
    ),
    XmpNamespaceSpec("XMP-MP1", "http://ns.microsoft.com/photo/1.1/", {}),
    XmpNamespaceSpec("XMP-MP", "http://ns.microsoft.com/photo/1.2/", {}),
    XmpNamespaceSpec(
        "XMP-dc",
        "http://purl.org/dc/elements/1.1/",
        {
            "creator": "Creator",
            "description": "Description",
            "rights": "Rights",
            "subject": "Subject",
            "title": "Title",
        },
    ),
    XmpNamespaceSpec("XMP-xmp", "http://ns.adobe.com/xap/1.0/", {}),
    XmpNamespaceSpec(
        "XMP-xmpDM",
        "http://ns.adobe.com/xmp/1.0/DynamicMedia/",
        {
            "audioModDate": "AudioModDate",
            "metadataModDate": "MetadataModDate",
            "videoModDate": "VideoModDate",
        },
    ),
    XmpNamespaceSpec("XMP-xmpRights", "http://ns.adobe.com/xap/1.0/rights/", {}),
    XmpNamespaceSpec("XMP-xmpNote", "http://ns.adobe.com/xmp/note/", {}),
    XmpNamespaceSpec("XMP-xmpMM", "http://ns.adobe.com/xap/1.0/mm/", {}),
    XmpNamespaceSpec("XMP-xmpBJ", "http://ns.adobe.com/xap/1.0/bj/", {"JobRef": "JobRefName"}),
    XmpNamespaceSpec("XMP-xmpTPg", "http://ns.adobe.com/xap/1.0/t/pg/", {}),
    XmpNamespaceSpec("XMP-pdf", "http://ns.adobe.com/pdf/1.3/", {}),
    XmpNamespaceSpec("XMP-photoshop", PHOTOSHOP_NAMESPACE, {}),
    XmpNamespaceSpec(
        "XMP-crd",
        "http://ns.adobe.com/camera-raw-defaults/1.0/",
        {"RangeMaskMapInfo": "RangeMask"},
    ),
    XmpNamespaceSpec(
        "XMP-crs",
        "http://ns.adobe.com/camera-raw-settings/1.0/",
        {"RangeMaskMapInfo": "RangeMask"},
    ),
    XmpNamespaceSpec("XMP-aux", "http://ns.adobe.com/exif/1.0/aux/", {}),
    XmpNamespaceSpec("XMP-tiff", "http://ns.adobe.com/tiff/1.0/", {}),
    XmpNamespaceSpec("XMP-exif", "http://ns.adobe.com/exif/1.0/", {}),
    XmpNamespaceSpec("XMP-exifEX", EXIF_EXTENDED_NAMESPACE, {}),
    XmpNamespaceSpec("XMP-iptcCore", IPTC_CORE_NAMESPACE, {}),
    XmpNamespaceSpec(
        "XMP-iptcExt",
        IPTC_EXT_NAMESPACE,
        {
            "EventExt": "ShownEvent",
            "RegistryId": "RegistryID",
            "SnapshotLink": "Snapshot",
            "metadataAuthority": "MetadataAuthority",
            "metadataLastEditor": "MetadataLastEditor",
        },
    ),
    XmpNamespaceSpec(
        "XMP-apple-fi",
        "http://ns.apple.com/faceinfo/1.0/",
        {"Timestamp": "TimeStamp"},
    ),
    XmpNamespaceSpec(
        "XMP-acdsee-rs",
        ACDSEE_REGION_NAMESPACE,
        {"Regions": "RegionInfoACDSee"},
    ),
    XmpNamespaceSpec(
        "XMP-hdr",
        "http://ns.adobe.com/hdr-metadata/1.0/",
        {
            "ccv_avg_luminance_nits": "CCVAvgLuminanceNits",
            "ccv_max_luminance_nits": "CCVMaxLuminanceNits",
            "ccv_min_luminance_nits": "CCVMinLuminanceNits",
            "ccv_primaries_xy": "CCVPrimariesXY",
            "ccv_white_xy": "CCVWhiteXY",
            "scene_referred": "SceneReferred",
        },
    ),
    XmpNamespaceSpec("XMP-hdrgm", "http://ns.adobe.com/hdr-gain-map/1.0/", {}),
    XmpNamespaceSpec("XMP-plus", "http://ns.useplus.org/ldf/xmp/1.0/", {}),
    XmpNamespaceSpec(
        "XMP-lr",
        "http://ns.adobe.com/lightroom/1.0/",
        {
            "hierarchicalSubject": "HierarchicalSubject",
            "privateRTKInfo": "PrivateRTKInfo",
            "weightedFlatSubject": "WeightedFlatSubject",
        },
    ),
    XmpNamespaceSpec("XMP-ics", ICS_NAMESPACE, {}),
    XmpNamespaceSpec(
        "XMP-prism",
        PRISM_NAMESPACE,
        {
            "alternateTitle": "AlternateTitle",
            "channel": "Channel",
            "hasCorrection": "HasCorrection",
            "killDate": "KillDate",
            "offSaleDate": "OffSaleDate",
            "onSaleDate": "OnSaleDate",
            "onSaleDay": "OnSaleDay",
            "publicationDate": "PublicationDate",
            "publicationDisplayDate": "PublicationDisplayDate",
            "url": "URL",
        },
    ),
    XmpNamespaceSpec(
        "XMP-creatorAtom",
        CREATOR_ATOM_NAMESPACE,
        {
            "aeProjectLink": "AeProjectLink",
            "macAtom": "MacAtom",
            "windowsAtom": "WindowsAtom",
        },
    ),
)


def parse_xmp_packet(packet: bytes) -> dict[XmpGroup, JsonObject]:
    root = ElementTree.fromstring(decode_xmp_packet(packet))
    parent_by_child: dict[ElementTree.Element[str], ElementTree.Element[str]] = {}
    for parent in root.iter():
        for child in tuple(parent):
            parent_by_child[child] = parent
    values_by_group = empty_xmp_values_by_group()
    collect_xmp_wrapper_attributes(values_by_group, root)
    for element in root.iter():
        collect_rdf_attributes(values_by_group["XMP-rdf"], element)
        collect_xmp_description_attributes(values_by_group, element)
        collect_xmp_element_values(values_by_group, element, parent_by_child.get(element))
    return values_by_group


def source_struct_elements_from_xmp_packet(packet: bytes) -> tuple[XmpSourceStructElement, ...]:
    root = ElementTree.fromstring(decode_xmp_packet(packet))
    elements: list[XmpSourceStructElement] = []
    for element in root.iter():
        source_element = source_struct_element_from_xmp_element(element)
        if source_element is not None:
            elements.append(source_element)
    return tuple(elements)


def source_struct_element_from_xmp_element(
    element: ElementTree.Element[str],
) -> XmpSourceStructElement | None:
    namespace, local_name = expanded_name_parts(element.tag)
    if namespace is None:
        return None
    spec = namespace_spec_for_uri(namespace)
    if spec is None:
        return None
    tag_name = spec.tag_renames.get(local_name, local_name)
    parent_spec = xmp_simple_struct_parent_spec_for_group_and_tag(spec.group, tag_name)
    if parent_spec is None or parent_spec.shape != "struct_list":
        return None
    field_specs = xmp_simple_struct_field_specs_for_parent(parent_spec)
    container = source_xmp_rdf_container(element)
    if container is None:
        return None
    list_items: list[XmpSourceStructListItem] = []
    for source_index, item in enumerate(tuple(container)):
        if expanded_name_parts(item.tag) != (RDF_NAMESPACE, "li"):
            continue
        fields = source_struct_fields_for_item(item, parent_spec.group, field_specs)
        if not fields:
            continue
        list_items.append(
            XmpSourceStructListItem(
                fields=fields,
                source_index=source_index,
                source_path=f"{parent_spec.group}:{parent_spec.parent_name}/rdf:li[{source_index}]",
            )
        )
    if not list_items:
        return None
    return XmpSourceStructElement(
        group=parent_spec.group,
        tag=parent_spec.parent_name,
        value=None,
        uri_path=xmp_group_uri_path(parent_spec.group),
        list_container=parent_spec.list_kind,
        struct_list_items=tuple(list_items),
    )


def source_struct_fields_for_item(
    item: ElementTree.Element[str],
    parent_group: XmpGroup,
    field_specs: tuple[XmpSimpleStructFieldSpec, ...],
) -> tuple[XmpSourceStructField, ...]:
    fields: list[XmpSourceStructField] = []
    nested_specs: dict[XmpSimpleStructPathStep, list[XmpSimpleStructFieldSpec]] = {}
    nested_order: list[XmpSimpleStructPathStep] = []
    for field_spec in field_specs:
        path_steps = simple_struct_nested_path_steps(field_spec)
        if len(path_steps) == 1:
            path_step = path_steps[0]
            if path_step not in nested_specs:
                nested_specs[path_step] = []
                nested_order.append(path_step)
            nested_specs[path_step].append(field_spec)
            continue
        field_element = xmp_simple_struct_field_element(item, field_spec)
        if field_element is None:
            continue
        value = source_struct_field_value(field_element, field_spec)
        if value is None:
            continue
        namespace, _ = expanded_name_parts(field_element.tag)
        field_group = xmp_source_struct_group_for_namespace(namespace, parent_group)
        fields.append(
            XmpSourceStructField(
                group=field_group,
                tag=field_spec.field_name,
                value=value,
                uri_path=xmp_group_uri_path(field_group),
            )
        )
    for path_step in nested_order:
        nested_field = source_struct_nested_field_for_path_step(
            item,
            parent_group,
            path_step,
            tuple(nested_specs[path_step]),
        )
        if nested_field is not None:
            fields.append(nested_field)
    return tuple(fields)


def source_struct_nested_field_for_path_step(
    item: ElementTree.Element[str],
    parent_group: XmpGroup,
    path_step: XmpSimpleStructPathStep,
    field_specs: tuple[XmpSimpleStructFieldSpec, ...],
) -> XmpSourceStructField | None:
    payloads = source_struct_nested_payload_elements(item, path_step)
    if not payloads:
        return None
    fields: list[XmpSourceStructField] = []
    for payload in payloads:
        for field_spec in field_specs:
            field_element = direct_child_by_local_name(payload, field_spec.field_name)
            if field_element is None:
                continue
            value = source_struct_field_value(field_element, field_spec)
            if value is None:
                continue
            namespace, _ = expanded_name_parts(field_element.tag)
            field_group = xmp_source_struct_group_for_namespace(namespace, parent_group)
            fields.append(
                XmpSourceStructField(
                    group=field_group,
                    tag=field_spec.field_name,
                    value=value,
                    uri_path=xmp_group_uri_path(field_group),
                )
            )
    if not fields:
        return None
    nested_group = xmp_source_struct_group_for_namespace(path_step.namespace_uri, parent_group)
    return XmpSourceStructField(
        group=nested_group,
        tag=path_step.field_name,
        value=None,
        uri_path=xmp_group_uri_path(nested_group),
        struct_fields=tuple(fields),
    )


def source_struct_nested_payload_elements(
    item: ElementTree.Element[str],
    path_step: XmpSimpleStructPathStep,
) -> tuple[ElementTree.Element[str], ...]:
    nested_element = direct_child_by_local_name(item, path_step.field_name)
    if nested_element is None:
        return ()
    if path_step.list_kind is not None:
        return xmp_simple_struct_payload_elements(nested_element)
    return (nested_element,)


def xmp_source_struct_group_for_namespace(
    namespace: str | None,
    fallback_group: XmpGroup,
) -> XmpGroup:
    if namespace is None:
        return fallback_group
    field_namespace_spec = namespace_spec_for_uri(namespace)
    if field_namespace_spec is None:
        return fallback_group
    return field_namespace_spec.group


def source_struct_field_value(
    element: ElementTree.Element[str],
    field_spec: XmpSimpleStructFieldSpec,
) -> XmpSourceStructValue:
    if field_spec.field_list_kind is not None:
        list_values = rdf_container_items(element)
        if list_values:
            return list_values
        return None
    value = xmp_element_value(element, field_spec.field_name)
    if value is None:
        return None
    if field_spec.value_kind == "boolean" and isinstance(value, str):
        return value == "True"
    if field_spec.value_kind == "date" and isinstance(value, str):
        return xmp_date_text(value)
    return xmp_source_tag_value(value)


def xmp_source_tag_value(value: XmpTagValue) -> XmpSourceStructValue:
    if isinstance(value, list):
        return [item for item in value]
    return value


def source_xmp_rdf_container(
    element: ElementTree.Element[str],
) -> ElementTree.Element[str] | None:
    for child in tuple(element):
        namespace, local_name = expanded_name_parts(child.tag)
        if namespace == RDF_NAMESPACE and local_name in {"Bag", "Seq", "Alt"}:
            return child
    return None


def xmp_group_uri_path(group: XmpGroup) -> str:
    return f"XMP/{group}"


def empty_xmp_values_by_group() -> dict[XmpGroup, JsonObject]:
    values_by_group: dict[XmpGroup, JsonObject] = {}
    for group in XMP_EXIFTOOL_MAIN_GROUP_ORDER:
        values_by_group[group] = {}
    for spec in XMP_NAMESPACE_SPECS:
        values_by_group.setdefault(spec.group, {})
    return values_by_group


def decode_xmp_packet(packet: bytes) -> str:
    stripped = packet.rstrip(b"\x00")
    if stripped.startswith(b"\xfe\xff") or stripped.startswith(b"\x00<"):
        return stripped.decode("utf-16-be", errors="replace")
    if stripped.startswith(b"\xff\xfe") or stripped.startswith(b"<\x00"):
        return stripped.decode("utf-16-le", errors="replace")
    return stripped.decode("utf-8", errors="replace")


def collect_xmp_wrapper_attributes(
    values_by_group: dict[XmpGroup, JsonObject],
    root: ElementTree.Element[str],
) -> None:
    toolkit = root.attrib.get(f"{{{XMP_META_NAMESPACE}}}xmptk")
    if toolkit is not None:
        values_by_group["XMP-x"]["XMPToolkit"] = toolkit


def collect_rdf_attributes(values: JsonObject, element: ElementTree.Element[str]) -> None:
    about = element.attrib.get(f"{{{RDF_NAMESPACE}}}about")
    if about is None:
        about = element.attrib.get("about")
    if about is None:
        about = first_attribute_by_local_name(element, "about")
    if about is not None:
        values["About"] = about


def collect_xmp_description_attributes(
    values_by_group: dict[XmpGroup, JsonObject],
    element: ElementTree.Element[str],
) -> None:
    namespace, local_name = expanded_name_parts(element.tag)
    if namespace != RDF_NAMESPACE or local_name != "Description":
        return
    for attribute_name, attribute_value in element.attrib.items():
        attribute_namespace, attribute_local_name = expanded_name_parts(attribute_name)
        if attribute_namespace is None or attribute_namespace == RDF_NAMESPACE:
            continue
        spec = namespace_spec_for_uri(attribute_namespace)
        if spec is None:
            continue
        tag_name = spec.tag_renames.get(attribute_local_name, attribute_local_name)
        values_by_group[spec.group][tag_name] = xmp_tag_value_to_json(
            xmp_attribute_value(attribute_value, tag_name)
        )


def collect_xmp_element_values(
    values_by_group: dict[XmpGroup, JsonObject],
    element: ElementTree.Element[str],
    parent: ElementTree.Element[str] | None,
) -> None:
    namespace, local_name = expanded_name_parts(element.tag)
    if namespace is None:
        return
    spec = namespace_spec_for_uri(namespace)
    if spec is None:
        return
    top_level_property = is_top_level_xmp_property(parent)
    if top_level_property:
        job_ref_values = xmp_job_ref_values(element, spec.group, local_name)
        if job_ref_values:
            values_by_group[spec.group].update(job_ref_values)
            return
    tag_name = spec.tag_renames.get(local_name, local_name)
    if top_level_property:
        if spec.group == "XMP-plus":
            plus_values = xmp_plus_values(element, tag_name)
            if plus_values:
                values_by_group[spec.group].update(plus_values)
                return
        resource_ref_values = xmp_resource_ref_values(element, tag_name)
        if resource_ref_values:
            values_by_group[spec.group].update(resource_ref_values)
            return
        manifest_item_values = xmp_manifest_item_values(element, tag_name)
        if manifest_item_values:
            values_by_group[spec.group].update(manifest_item_values)
            return
        pantry_item_values = xmp_pantry_item_values(element, tag_name)
        if pantry_item_values:
            values_by_group[spec.group].update(pantry_item_values)
            return
        simple_struct_values = xmp_simple_struct_values(element, spec.group, tag_name)
        if simple_struct_values:
            values_by_group[spec.group].update(simple_struct_values)
            return
        resource_event_values = xmp_resource_event_values(element, tag_name)
        if resource_event_values:
            values_by_group[spec.group].update(resource_event_values)
            return
    if not top_level_property:
        return
    value = xmp_element_value(element, tag_name)
    if value is not None:
        values_by_group[spec.group][tag_name] = xmp_tag_value_to_json(value)


def is_top_level_xmp_property(parent: ElementTree.Element[str] | None) -> bool:
    if parent is None:
        return False
    namespace, local_name = expanded_name_parts(parent.tag)
    return namespace == RDF_NAMESPACE and local_name == "Description"


def xmp_tag_value_to_json(value: XmpTagValue) -> JsonValue:
    if isinstance(value, list):
        array: JsonArray = []
        for item in value:
            array.append(item)
        return array
    return value


def expanded_name_parts(name: str) -> tuple[str | None, str]:
    if not name.startswith("{") or "}" not in name:
        return None, name
    namespace, local_name = name[1:].split("}", 1)
    return namespace, local_name


def namespace_spec_for_uri(uri: XmpNamespaceUri) -> XmpNamespaceSpec | None:
    for spec in XMP_NAMESPACE_SPECS:
        if spec.uri == uri:
            return spec
    return None


def xmp_element_value(
    element: ElementTree.Element[str],
    tag_name: str,
) -> XmpTagValue | None:
    if tag_name == "JobRefName":
        return first_descendant_text(element, "name") or first_descendant_attribute(element, "name")
    list_items = rdf_container_items(element)
    if list_items:
        return list_items[0] if len(list_items) == 1 and tag_name != "Subject" else list_items
    text = normalized_text(element)
    if text is None:
        return None
    if tag_name == "Urgency" and text == "8":
        return "8 (least urgent)"
    if tag_name == "Category":
        return int(text) if text.isdecimal() else text
    if tag_name in XMP_DATE_TAG_NAMES:
        return xmp_date_text(text)
    if tag_name in XMP_BOOLEAN_TAG_NAMES:
        return text == "True"
    return text


def xmp_plus_values(element: ElementTree.Element[str], tag_name: str) -> JsonObject:
    values: JsonObject = {}
    for descendant in element.iter():
        namespace, descendant_name = expanded_name_parts(descendant.tag)
        if namespace != "http://ns.useplus.org/ldf/xmp/1.0/" or descendant_name == tag_name:
            continue
        text = normalized_text(descendant)
        if text is None:
            continue
        values[f"{tag_name}{descendant_name}"] = xmp_plus_display_value(descendant_name, text)
    if values:
        return values
    list_items = rdf_container_items(element)
    if list_items:
        translated: JsonArray = [xmp_plus_display_value(tag_name, item) for item in list_items]
        values[tag_name] = translated
        return values
    text = normalized_text(element)
    if text is not None:
        values[tag_name] = xmp_plus_display_value(tag_name, text)
    return values


def xmp_plus_display_value(tag_name: str, value: str) -> str:
    from exifmodern.formats.plus.transaction_plan import PLUS_VOCAB_PREFIX, VOCABULARY_LOOKUP

    code = value.removeprefix(PLUS_VOCAB_PREFIX)
    vocabulary = VOCABULARY_LOOKUP.get(tag_name)
    if vocabulary is None:
        return code if code != value else value
    return vocabulary.values.get(code, code)


def xmp_attribute_value(value: str, tag_name: str) -> XmpTagValue:
    if tag_name in XMP_DATE_TAG_NAMES:
        return xmp_date_text(value)
    if tag_name in XMP_BOOLEAN_TAG_NAMES:
        return value == "True"
    return value


def xmp_date_text(text: str) -> str:
    if "T" in text:
        date_text, time_text = text.split("T", 1)
        date_parts = date_text.split("-")
        if len(date_parts) == 3 and all(part.isdecimal() for part in date_parts):
            return f"{date_parts[0]}:{date_parts[1]}:{date_parts[2]} {time_text}"
    parts = text.split("-")
    if len(parts) in {1, 2, 3} and all(part.isdecimal() for part in parts):
        return ":".join(parts)
    return text


def xmp_job_ref_values(
    element: ElementTree.Element[str],
    group: str,
    tag_name: str,
) -> JsonObject:
    parent_spec = job_ref_parent_spec_for_property(f"{group}:{tag_name}")
    if parent_spec is None:
        return {}
    values: JsonObject = {}
    for descendant in element.iter():
        _, descendant_name = expanded_name_parts(descendant.tag)
        field_spec = job_ref_field_spec_for_field_name(descendant_name)
        if field_spec is None:
            continue
        text = normalized_text(descendant)
        if text is None:
            text = first_attribute_by_local_name(descendant, field_spec.field_name)
        if text is None:
            continue
        values[f"{parent_spec.parent_name}{field_spec.readback_suffix}"] = text
    return values


def xmp_resource_ref_values(
    element: ElementTree.Element[str],
    tag_name: str,
) -> JsonObject:
    parent_spec = resource_ref_parent_spec_for_property(f"XMP-xmpMM:{tag_name}")
    if parent_spec is None:
        return {}
    values: JsonObject = {}
    for descendant in element.iter():
        for attribute_name, attribute_value in descendant.attrib.items():
            _, attribute_local_name = expanded_name_parts(attribute_name)
            field_spec = resource_ref_field_spec_for_field_name(attribute_local_name)
            if field_spec is None:
                continue
            tag_key = f"{parent_spec.parent_name}{field_spec.readback_suffix}"
            if field_spec.date_value:
                values[tag_key] = xmp_date_text(attribute_value)
            else:
                values[tag_key] = attribute_value
        _, descendant_name = expanded_name_parts(descendant.tag)
        field_spec = resource_ref_field_spec_for_field_name(descendant_name)
        if field_spec is None:
            continue
        text = normalized_text(descendant)
        if text is None:
            continue
        tag_key = f"{parent_spec.parent_name}{field_spec.readback_suffix}"
        if field_spec.date_value:
            values[tag_key] = xmp_date_text(text)
        else:
            values[tag_key] = text
    return values


def xmp_manifest_item_values(
    element: ElementTree.Element[str],
    tag_name: str,
) -> JsonObject:
    parent_spec = manifest_item_parent_spec_for_property(f"XMP-xmpMM:{tag_name}")
    if parent_spec is None:
        return {}
    values: JsonObject = {}
    for descendant in element.iter():
        _, descendant_name = expanded_name_parts(descendant.tag)
        simple_field_spec = manifest_item_simple_field_spec_for_field_name(descendant_name)
        if simple_field_spec is not None:
            text = normalized_text(descendant)
            if text is None:
                continue
            values[f"{parent_spec.parent_name}{simple_field_spec.readback_suffix}"] = text
            continue
        if descendant_name != "reference":
            continue
        for reference_descendant in descendant.iter():
            _, reference_descendant_name = expanded_name_parts(reference_descendant.tag)
            reference_field_spec = manifest_item_reference_field_spec_for_field_name(
                reference_descendant_name
            )
            if reference_field_spec is None:
                continue
            text = normalized_text(reference_descendant)
            if text is None:
                continue
            tag_key = f"{parent_spec.parent_name}Reference{reference_field_spec.readback_suffix}"
            if reference_field_spec.date_value:
                values[tag_key] = xmp_date_text(text)
            else:
                values[tag_key] = text
    return values


def xmp_pantry_item_values(
    element: ElementTree.Element[str],
    tag_name: str,
) -> JsonObject:
    parent_spec = pantry_item_parent_spec_for_property(f"XMP-xmpMM:{tag_name}")
    if parent_spec is None:
        return {}
    values: JsonObject = {}
    for descendant in element.iter():
        _, descendant_name = expanded_name_parts(descendant.tag)
        field_spec = pantry_item_field_spec_for_field_name(descendant_name)
        if field_spec is None:
            continue
        text = normalized_text(descendant)
        if text is None:
            continue
        values[f"{parent_spec.parent_name}{field_spec.readback_suffix}"] = text
    return values


def xmp_resource_event_values(
    element: ElementTree.Element[str],
    tag_name: str,
) -> JsonObject:
    parent_spec = resource_event_parent_spec_for_property(f"XMP-xmpMM:{tag_name}")
    if parent_spec is None:
        return {}
    values: JsonObject = {}
    for descendant in element.iter():
        _, descendant_name = expanded_name_parts(descendant.tag)
        field_spec = resource_event_field_spec_for_field_name(descendant_name)
        if field_spec is None:
            continue
        text = normalized_text(descendant)
        if text is None:
            continue
        tag_key = f"{parent_spec.parent_name}{field_spec.readback_suffix}"
        if field_spec.date_value:
            values[tag_key] = xmp_date_text(text)
        else:
            values[tag_key] = text
    return values


def xmp_simple_struct_values(
    element: ElementTree.Element[str],
    group: str,
    tag_name: str,
) -> JsonObject:
    parent_spec = xmp_simple_struct_parent_spec_for_group_and_tag(group, tag_name)
    if parent_spec is None:
        return {}
    field_specs = xmp_simple_struct_field_specs_for_parent(parent_spec)
    values: JsonObject = {}
    for payload_element in xmp_simple_struct_payload_elements(element):
        for field_spec in field_specs:
            field_element = xmp_simple_struct_field_element(payload_element, field_spec)
            if field_element is None:
                continue
            if parent_spec.group in {"XMP-exif", "XMP-xmpDM"} or parent_spec.parent_name in {
                "MaxPageSize",
                "Versions",
            }:
                tag_key = f"{parent_spec.parent_name}{field_spec.readback_suffix}"
            else:
                tag_key = field_spec.readback_suffix
            if field_spec.field_list_kind is not None:
                list_values = rdf_container_items(field_element)
                if list_values:
                    merge_xmp_struct_value(values, tag_key, list_values)
                continue
            if field_spec.value_kind == "lang_alt":
                value = xmp_element_value(field_element, tag_key)
                if value is not None:
                    merge_xmp_struct_value(values, tag_key, value)
                continue
            text = normalized_text(field_element)
            if text is None:
                continue
            if field_spec.value_kind == "boolean":
                merge_xmp_struct_value(values, tag_key, text == "True")
            elif field_spec.value_kind == "date":
                merge_xmp_struct_value(values, tag_key, xmp_date_text(text))
            else:
                merge_xmp_struct_value(values, tag_key, text)
    return values


def merge_xmp_struct_value(
    values: JsonObject,
    tag_key: str,
    value: XmpTagValue,
) -> None:
    new_value = xmp_tag_value_to_json(value)
    existing_value = values.get(tag_key)
    if existing_value is None:
        values[tag_key] = new_value
        return
    if isinstance(existing_value, list):
        append_xmp_struct_json_value(existing_value, new_value)
        return
    merged_values: JsonArray = [existing_value]
    append_xmp_struct_json_value(merged_values, new_value)
    values[tag_key] = merged_values


def append_xmp_struct_json_value(values: JsonArray, value: JsonValue) -> None:
    if isinstance(value, list):
        values.extend(value)
        return
    values.append(value)


def xmp_simple_struct_payload_elements(
    element: ElementTree.Element[str],
) -> tuple[ElementTree.Element[str], ...]:
    for container_name in ("Bag", "Seq", "Alt"):
        container = element.find(f"{{{RDF_NAMESPACE}}}{container_name}")
        if container is None:
            continue
        payload_elements = tuple(container.findall(f"{{{RDF_NAMESPACE}}}li"))
        if payload_elements:
            return payload_elements
    return (element,)


def xmp_simple_struct_field_element(
    payload_element: ElementTree.Element[str],
    field_spec: XmpSimpleStructFieldSpec,
) -> ElementTree.Element[str] | None:
    payload_elements: tuple[ElementTree.Element[str], ...] = (payload_element,)
    for path_step in simple_struct_nested_path_steps(field_spec):
        nested_payload_elements: list[ElementTree.Element[str]] = []
        for current_payload_element in payload_elements:
            nested_element = direct_child_by_local_name(
                current_payload_element,
                path_step.field_name,
            )
            if nested_element is None:
                continue
            nested_payload_elements.extend(xmp_simple_struct_payload_elements(nested_element))
        if not nested_payload_elements:
            return None
        payload_elements = tuple(nested_payload_elements)
    for current_payload_element in payload_elements:
        field_element = direct_child_by_local_name(
            current_payload_element,
            field_spec.field_name,
        )
        if field_element is not None:
            return field_element
    return None


def direct_child_by_local_name(
    element: ElementTree.Element[str],
    local_name: str,
) -> ElementTree.Element[str] | None:
    for child in tuple(element):
        _, child_name = expanded_name_parts(child.tag)
        if child_name == local_name:
            return child
    return None


def xmp_simple_struct_parent_spec_for_group_and_tag(
    group: str,
    tag_name: str,
) -> XmpSimpleStructParentSpec | None:
    for property_name in xmp_simple_struct_property_name_candidates(group, tag_name):
        parent_spec = xmp_simple_struct_parent_spec_for_property(property_name)
        if parent_spec is not None:
            return parent_spec
    return None


def xmp_simple_struct_property_name_candidates(group: str, tag_name: str) -> tuple[str, ...]:
    property_name = f"{group}:{tag_name}"
    if group == "XMP-x":
        return (property_name, f"XMP-xmp:{tag_name}")
    if tag_name and tag_name[0].islower():
        return (property_name, f"{group}:{tag_name[0].upper()}{tag_name[1:]}")
    return (property_name,)


def xmp_simple_struct_parent_spec_for_property(
    property_name: str,
) -> XmpSimpleStructParentSpec | None:
    return xmp_struct_parent_spec_for_property(property_name)


def xmp_simple_struct_field_specs_for_parent(
    parent_spec: XmpSimpleStructParentSpec,
) -> tuple[XmpSimpleStructFieldSpec, ...]:
    return xmp_struct_field_specs_for_parent(parent_spec)


def xmp_simple_struct_field_spec_for_field_name(
    field_specs: tuple[XmpSimpleStructFieldSpec, ...],
    field_name: str,
) -> XmpSimpleStructFieldSpec | None:
    for field_spec in field_specs:
        if field_spec.field_name == field_name:
            return field_spec
    return None


def rdf_container_items(element: ElementTree.Element[str]) -> list[str]:
    values: list[str] = []
    for container_name in ("Bag", "Seq", "Alt"):
        container = element.find(f"{{{RDF_NAMESPACE}}}{container_name}")
        if container is None:
            continue
        for item in container.findall(f"{{{RDF_NAMESPACE}}}li"):
            text = normalized_text(item)
            if text is not None:
                values.append(text)
            elif not tuple(item):
                values.append("")
    return values


def normalized_text(element: ElementTree.Element[str]) -> str | None:
    if element.text is None:
        return None
    text = element.text.strip()
    return text or None


def first_descendant_text(element: ElementTree.Element[str], local_name: str) -> str | None:
    for descendant in element.iter():
        _, descendant_name = expanded_name_parts(descendant.tag)
        if descendant_name != local_name:
            continue
        text = normalized_text(descendant)
        if text is not None:
            return text
    return None


def first_descendant_attribute(
    element: ElementTree.Element[str],
    local_name: str,
) -> str | None:
    for descendant in element.iter():
        for attribute_name, attribute_value in descendant.attrib.items():
            _, descendant_name = expanded_name_parts(attribute_name)
            if descendant_name == local_name:
                return attribute_value
    return None


def first_attribute_by_local_name(
    element: ElementTree.Element[str],
    local_name: str,
) -> str | None:
    for attribute_name, attribute_value in element.attrib.items():
        _, attribute_local_name = expanded_name_parts(attribute_name)
        if attribute_local_name == local_name:
            return attribute_value
    return None
