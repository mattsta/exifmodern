"""Source-grounded XMP property write plan primitives."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.xmp.structs.acdsee_regions import (
    ACDSEE_REGION_NAMESPACE,
)
from exifmodern.formats.xmp.structs.creator_atom import CREATOR_ATOM_NAMESPACE
from exifmodern.formats.xmp.structs.exif_extended import (
    EXIF_EXTENDED_NAMESPACE,
)
from exifmodern.formats.xmp.structs.ics import ICS_NAMESPACE
from exifmodern.formats.xmp.structs.iptc import (
    IPTC_CORE_NAMESPACE,
    IPTC_EXT_NAMESPACE,
)
from exifmodern.formats.xmp.structs.job_ref import (
    XmpJobRefFieldName,
    job_ref_assignment_target,
    job_ref_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.manifest_item import (
    XmpManifestItemAssignmentTarget,
    XmpManifestItemSimpleFieldName,
    manifest_item_assignment_target,
    manifest_item_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.pantry_item import (
    XmpPantryItemFieldName,
    pantry_item_assignment_target,
    pantry_item_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.prism import (
    PRISM_NAMESPACE,
)
from exifmodern.formats.xmp.structs.registry import (
    xmp_struct_assignment_target,
    xmp_struct_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.resource_event import (
    XmpResourceEventFieldName,
    resource_event_assignment_target,
    resource_event_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.resource_ref import (
    XmpResourceRefFieldName,
    resource_ref_assignment_target,
    resource_ref_parent_spec_for_property,
)
from exifmodern.formats.xmp.structs.simple_struct import (
    XmpSimpleStructAssignmentTarget,
    XmpSimpleStructFieldSpec,
    XmpSimpleStructParentSpec,
)
from exifmodern.json_types import JsonObject, json_array_value, json_string_value, load_json_object
from exifmodern.services.generated_indexes import TagLookupRepository

type XmpWritableProperty = str
type XmpLanguageCode = str
type XmpPropertyValueShape = Literal[
    "simple_text",
    "bag_text",
    "seq_text",
    "alt_text",
    "job_ref",
    "job_ref_name",
    "manifest_item",
    "pantry_item",
    "simple_struct",
    "resource_event",
    "resource_ref",
    "boolean",
    "date",
    "numeric",
]
type XmpRdfContainer = Literal["Bag", "Seq", "Alt"]
type XmpGeneratedPlanDiagnosticReason = Literal[
    "unknown_property",
    "unsupported_strategy",
    "unsupported_namespace",
    "missing_value",
    "scalar_repeated",
    "invalid_value",
    "duplicate_language",
    "unsupported_language",
    "duplicate_struct_field",
    "not_in_tag_lookup",
]
type XmpNumericWritable = Literal["integer", "real", "rational"]

XMP_PROPERTY_TABLE_SOURCE = "xmp.property_tables"
XMP_PROPERTY_WRITE_SOURCE = "xmp.property_write_loop"


@dataclass(frozen=True)
class XmpPropertySpec:
    property_name: XmpWritableProperty
    namespace_prefix: str
    namespace_uri: str
    element_name: str
    value_shape: XmpPropertyValueShape
    evidence_ids: tuple[str, ...]
    rdf_container: XmpRdfContainer | None = None


@dataclass(frozen=True)
class XmpNamespaceRegistration:
    prefix: str
    namespace_uri: str


@dataclass(frozen=True)
class XmpUserDefinedPropertyDefinition:
    property_name: XmpWritableProperty
    namespace_prefix: str
    namespace_uri: str
    element_name: str
    value_shape: XmpPropertyValueShape
    rdf_container: XmpRdfContainer | None = None
    struct_type_resource: str | None = None
    struct_fields: tuple[XmpUserDefinedStructFieldDefinition, ...] = ()


@dataclass(frozen=True)
class XmpUserDefinedStructFieldDefinition:
    flattened_property_name: XmpWritableProperty
    field_name: str
    value_shape: XmpPropertyValueShape
    rdf_container: XmpRdfContainer | None = None
    namespace_uri: str | None = None
    resource: bool = False
    struct_fields: tuple[XmpUserDefinedStructFieldDefinition, ...] = ()


@dataclass(frozen=True)
class XmpTextPropertyWrite:
    property_name: XmpWritableProperty
    value: str


@dataclass(frozen=True)
class XmpBooleanPropertyWrite:
    property_name: XmpWritableProperty
    value: bool


@dataclass(frozen=True)
class XmpTextListPropertyWrite:
    property_name: XmpWritableProperty
    values: tuple[str, ...]


@dataclass(frozen=True)
class XmpLocalizedTextValue:
    language_code: XmpLanguageCode
    value: str


@dataclass(frozen=True)
class XmpLocalizedTextPropertyWrite:
    property_name: XmpWritableProperty
    values: tuple[XmpLocalizedTextValue, ...]


@dataclass(frozen=True)
class XmpLocalizedTextPropertyPatch:
    property_name: XmpWritableProperty
    writes: tuple[XmpLocalizedTextValue, ...] = ()
    deletes: tuple[XmpLanguageCode, ...] = ()


@dataclass(frozen=True)
class XmpJobRefFieldValue:
    field_name: XmpJobRefFieldName
    value: str


@dataclass(frozen=True)
class XmpJobRefPropertyWrite:
    property_name: XmpWritableProperty
    values: tuple[XmpJobRefFieldValue, ...]


@dataclass(frozen=True)
class XmpResourceRefFieldValue:
    field_name: XmpResourceRefFieldName
    value: str


@dataclass(frozen=True)
class XmpResourceRefPropertyWrite:
    property_name: XmpWritableProperty
    values: tuple[XmpResourceRefFieldValue, ...]


@dataclass(frozen=True)
class XmpManifestItemSimpleFieldValue:
    field_name: XmpManifestItemSimpleFieldName
    value: str


@dataclass(frozen=True)
class XmpManifestItemReferenceFieldValue:
    field_name: XmpResourceRefFieldName
    value: str


type XmpManifestItemFieldValue = (
    XmpManifestItemSimpleFieldValue | XmpManifestItemReferenceFieldValue
)


@dataclass(frozen=True)
class XmpManifestItemPropertyWrite:
    property_name: XmpWritableProperty
    values: tuple[XmpManifestItemFieldValue, ...]


@dataclass(frozen=True)
class XmpPantryItemFieldValue:
    field_name: XmpPantryItemFieldName
    value: str


@dataclass(frozen=True)
class XmpPantryItemPropertyWrite:
    property_name: XmpWritableProperty
    values: tuple[XmpPantryItemFieldValue, ...]


@dataclass(frozen=True)
class XmpResourceEventFieldValue:
    field_name: XmpResourceEventFieldName
    value: str


@dataclass(frozen=True)
class XmpResourceEventPropertyWrite:
    property_name: XmpWritableProperty
    values: tuple[XmpResourceEventFieldValue, ...]


@dataclass(frozen=True)
class XmpSimpleStructFieldValue:
    field_spec: XmpSimpleStructFieldSpec
    value: str


@dataclass(frozen=True)
class XmpSimpleStructPropertyWrite:
    property_name: XmpWritableProperty
    parent_spec: XmpSimpleStructParentSpec
    values: tuple[XmpSimpleStructFieldValue, ...]


type XmpSimpleStructFieldValueGroup = tuple[XmpSimpleStructFieldValue, ...]


@dataclass(frozen=True)
class XmpSimpleStructListPropertyWrite:
    property_name: XmpWritableProperty
    parent_spec: XmpSimpleStructParentSpec
    item_groups: tuple[XmpSimpleStructFieldValueGroup, ...]


@dataclass(frozen=True)
class XmpUserDefinedStructLangAltListFieldWrite:
    field_name: str
    item_groups: tuple[tuple[XmpLocalizedTextValue, ...], ...]
    namespace_uri: str | None = None


@dataclass(frozen=True)
class XmpUserDefinedStructLangAltFieldWrite:
    field_name: str
    values: tuple[XmpLocalizedTextValue, ...]
    namespace_uri: str | None = None


@dataclass(frozen=True)
class XmpUserDefinedStructScalarFieldWrite:
    field_name: str
    value: str
    namespace_uri: str | None = None
    resource: bool = False


@dataclass(frozen=True)
class XmpUserDefinedStructListFieldWrite:
    field_name: str
    container_name: XmpRdfContainer
    values: tuple[str, ...]
    namespace_uri: str | None = None


@dataclass(frozen=True)
class XmpUserDefinedStructNestedFieldWrite:
    field_name: str
    fields: tuple[XmpUserDefinedStructFieldWrite, ...]
    namespace_uri: str | None = None


type XmpUserDefinedStructFieldWrite = (
    XmpUserDefinedStructLangAltListFieldWrite
    | XmpUserDefinedStructLangAltFieldWrite
    | XmpUserDefinedStructScalarFieldWrite
    | XmpUserDefinedStructListFieldWrite
    | XmpUserDefinedStructNestedFieldWrite
)


@dataclass(frozen=True)
class XmpUserDefinedStructPropertyWrite:
    property_name: XmpWritableProperty
    namespace_uri: str
    element_name: str
    struct_type_resource: str | None
    lang_alt_bag_fields: tuple[XmpUserDefinedStructLangAltListFieldWrite, ...]
    fields: tuple[XmpUserDefinedStructFieldWrite, ...] = ()


@dataclass(frozen=True)
class XmpPropertyDelete:
    property_name: XmpWritableProperty


@dataclass(frozen=True)
class XmpGeneratedPropertyAssignment:
    property_name: XmpWritableProperty
    value: str
    language_code: XmpLanguageCode | None = None


@dataclass(frozen=True)
class XmpGeneratedPropertyDelete:
    property_name: XmpWritableProperty


@dataclass(frozen=True)
class XmpPublicSidecarPropertyAssignment:
    property_name: XmpWritableProperty
    value: str


@dataclass(frozen=True)
class XmpPublicSidecarPropertyDelete:
    property_name: XmpWritableProperty


@dataclass(frozen=True)
class XmpGeneratedPropertyCapability:
    property_name: XmpWritableProperty
    group: str
    namespace_prefix: str
    tag_id: str
    tag_name: str
    shape: str
    modernization_strategy: str
    list_kind: str | None
    effective_writable: str


@dataclass(frozen=True)
class XmpGeneratedPlanDiagnostic:
    property_name: XmpWritableProperty
    reason: XmpGeneratedPlanDiagnosticReason
    detail: str


@dataclass(frozen=True)
class XmpInflatedStructField:
    name: str
    value: XmpInflatedValue


@dataclass(frozen=True)
class XmpInflatedStruct:
    fields: tuple[XmpInflatedStructField, ...]


@dataclass(frozen=True)
class XmpInflatedList:
    values: tuple[XmpInflatedValue, ...]


type XmpInflatedValue = str | XmpInflatedStruct | XmpInflatedList
type XmpUserDefinedStructFieldPath = tuple[XmpUserDefinedStructFieldDefinition, ...]


@dataclass(frozen=True)
class XmpGeneratedValueValidation:
    values: tuple[str, ...]
    diagnostics: tuple[XmpGeneratedPlanDiagnostic, ...] = ()


@dataclass(frozen=True)
class XmpGeneratedLangAltValidation:
    values: tuple[XmpLocalizedTextValue, ...]
    diagnostics: tuple[XmpGeneratedPlanDiagnostic, ...] = ()


@dataclass(frozen=True)
class XmpGeneratedJobRefValidation:
    values: tuple[XmpJobRefFieldValue, ...]
    diagnostics: tuple[XmpGeneratedPlanDiagnostic, ...] = ()


@dataclass(frozen=True)
class XmpGeneratedResourceRefValidation:
    values: tuple[XmpResourceRefFieldValue, ...]
    diagnostics: tuple[XmpGeneratedPlanDiagnostic, ...] = ()


@dataclass(frozen=True)
class XmpGeneratedManifestItemValidation:
    values: tuple[XmpManifestItemFieldValue, ...]
    diagnostics: tuple[XmpGeneratedPlanDiagnostic, ...] = ()


@dataclass(frozen=True)
class XmpGeneratedPantryItemValidation:
    values: tuple[XmpPantryItemFieldValue, ...]
    diagnostics: tuple[XmpGeneratedPlanDiagnostic, ...] = ()


@dataclass(frozen=True)
class XmpGeneratedResourceEventValidation:
    values: tuple[XmpResourceEventFieldValue, ...]
    diagnostics: tuple[XmpGeneratedPlanDiagnostic, ...] = ()


@dataclass(frozen=True)
class XmpGeneratedSimpleStructValidation:
    parent_spec: XmpSimpleStructParentSpec
    values: tuple[XmpSimpleStructFieldValue, ...]
    item_groups: tuple[XmpSimpleStructFieldValueGroup, ...] = ()
    diagnostics: tuple[XmpGeneratedPlanDiagnostic, ...] = ()


type XmpPropertyWriteStep = (
    XmpTextPropertyWrite
    | XmpBooleanPropertyWrite
    | XmpTextListPropertyWrite
    | XmpLocalizedTextPropertyWrite
    | XmpLocalizedTextPropertyPatch
    | XmpJobRefPropertyWrite
    | XmpManifestItemPropertyWrite
    | XmpPantryItemPropertyWrite
    | XmpResourceEventPropertyWrite
    | XmpResourceRefPropertyWrite
    | XmpSimpleStructPropertyWrite
    | XmpSimpleStructListPropertyWrite
    | XmpUserDefinedStructPropertyWrite
    | XmpPropertyDelete
)


@dataclass(frozen=True)
class XmpPropertyWritePlan:
    steps: tuple[XmpPropertyWriteStep, ...]
    evidence_ids: tuple[str, ...]
    generated_diagnostics: tuple[XmpGeneratedPlanDiagnostic, ...] = ()
    generated_specs: tuple[XmpPropertySpec, ...] = ()
    namespace_registry: tuple[XmpNamespaceRegistration, ...] = ()


GENERATED_PROPERTY_SOURCE = "xmp.generated_property_capability"
XMP_NAMESPACE_URIS = {
    "ACDSeeRegions": ACDSEE_REGION_NAMESPACE,
    "Lightroom": "http://ns.adobe.com/lightroom/1.0/",
    "MicrosoftPhoto": "http://ns.microsoft.com/photo/1.0/",
    "MP": "http://ns.microsoft.com/photo/1.2/",
    "MP1": "http://ns.microsoft.com/photo/1.1/",
    "aux": "http://ns.adobe.com/exif/1.0/aux/",
    "apple_fi": "http://ns.apple.com/faceinfo/1.0/",
    "crd": "http://ns.adobe.com/camera-raw-defaults/1.0/",
    "crs": "http://ns.adobe.com/camera-raw-settings/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "exif": "http://ns.adobe.com/exif/1.0/",
    "exifEX": EXIF_EXTENDED_NAMESPACE,
    "hdr": "http://ns.adobe.com/hdr-metadata/1.0/",
    "hdrgm": "http://ns.adobe.com/hdr-gain-map/1.0/",
    "iptcCore": IPTC_CORE_NAMESPACE,
    "iptcExt": IPTC_EXT_NAMESPACE,
    "ics": ICS_NAMESPACE,
    "pdf": "http://ns.adobe.com/pdf/1.3/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
    "prism": PRISM_NAMESPACE,
    "tiff": "http://ns.adobe.com/tiff/1.0/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "xmpBJ": "http://ns.adobe.com/xap/1.0/bj/",
    "creatorAtom": CREATOR_ATOM_NAMESPACE,
    "xmpDM": "http://ns.adobe.com/xmp/1.0/DynamicMedia/",
    "xmpMM": "http://ns.adobe.com/xap/1.0/mm/",
    "xmpRights": "http://ns.adobe.com/xap/1.0/rights/",
    "xmpTPg": "http://ns.adobe.com/xap/1.0/t/pg/",
}
USER_DEFINED_XMP_NAMESPACE_SOURCE = "xmp.user_defined_namespace_registration"
USER_DEFINED_XMP_WRITER_SOURCE = "xmp.user_defined_writer_checks"
USER_DEFINED_XMP_TEST_SOURCE = "xmp.user_defined_fixture_shape"


@dataclass(frozen=True)
class XmpSimpleFieldSpec:
    property_name: XmpWritableProperty
    namespace_prefix: str
    element_name: str
    value_shape: XmpPropertyValueShape
    rdf_container: XmpRdfContainer | None = None


def xmp_simple_property_spec(field: XmpSimpleFieldSpec) -> XmpPropertySpec:
    return XmpPropertySpec(
        property_name=field.property_name,
        namespace_prefix=field.namespace_prefix,
        namespace_uri=XMP_NAMESPACE_URIS[field.namespace_prefix],
        element_name=field.element_name,
        value_shape=field.value_shape,
        evidence_ids=(XMP_PROPERTY_TABLE_SOURCE,),
        rdf_container=field.rdf_container,
    )


XMP_PUBLIC_SIDECAR_SIMPLE_FIELDS: tuple[XmpSimpleFieldSpec, ...] = (
    XmpSimpleFieldSpec("XMP-aux:Lens", "aux", "Lens", "simple_text"),
    XmpSimpleFieldSpec("XMP-dc:Contributor", "dc", "contributor", "bag_text", "Bag"),
    XmpSimpleFieldSpec("XMP-dc:Coverage", "dc", "coverage", "simple_text"),
    XmpSimpleFieldSpec("XMP-dc:Creator", "dc", "creator", "seq_text", "Seq"),
    XmpSimpleFieldSpec("XMP-dc:Description", "dc", "description", "alt_text", "Alt"),
    XmpSimpleFieldSpec("XMP-dc:Format", "dc", "format", "simple_text"),
    XmpSimpleFieldSpec("XMP-dc:Identifier", "dc", "identifier", "simple_text"),
    XmpSimpleFieldSpec("XMP-dc:Language", "dc", "language", "bag_text", "Bag"),
    XmpSimpleFieldSpec("XMP-dc:Publisher", "dc", "publisher", "bag_text", "Bag"),
    XmpSimpleFieldSpec("XMP-dc:Relation", "dc", "relation", "bag_text", "Bag"),
    XmpSimpleFieldSpec("XMP-dc:Rights", "dc", "rights", "alt_text", "Alt"),
    XmpSimpleFieldSpec("XMP-dc:Source", "dc", "source", "simple_text"),
    XmpSimpleFieldSpec("XMP-dc:Subject", "dc", "subject", "bag_text", "Bag"),
    XmpSimpleFieldSpec("XMP-dc:Title", "dc", "title", "alt_text", "Alt"),
    XmpSimpleFieldSpec("XMP-dc:Type", "dc", "type", "bag_text", "Bag"),
    XmpSimpleFieldSpec(
        "XMP-photoshop:AuthorsPosition",
        "photoshop",
        "AuthorsPosition",
        "simple_text",
    ),
    XmpSimpleFieldSpec("XMP-photoshop:CaptionWriter", "photoshop", "CaptionWriter", "simple_text"),
    XmpSimpleFieldSpec("XMP-photoshop:Category", "photoshop", "Category", "simple_text"),
    XmpSimpleFieldSpec("XMP-photoshop:City", "photoshop", "City", "simple_text"),
    XmpSimpleFieldSpec("XMP-photoshop:Country", "photoshop", "Country", "simple_text"),
    XmpSimpleFieldSpec("XMP-photoshop:Credit", "photoshop", "Credit", "simple_text"),
    XmpSimpleFieldSpec("XMP-photoshop:DateCreated", "photoshop", "DateCreated", "date"),
    XmpSimpleFieldSpec("XMP-photoshop:Headline", "photoshop", "Headline", "simple_text"),
    XmpSimpleFieldSpec("XMP-photoshop:Instructions", "photoshop", "Instructions", "simple_text"),
    XmpSimpleFieldSpec("XMP-photoshop:Source", "photoshop", "Source", "simple_text"),
    XmpSimpleFieldSpec("XMP-photoshop:State", "photoshop", "State", "simple_text"),
    XmpSimpleFieldSpec(
        "XMP-photoshop:SupplementalCategories",
        "photoshop",
        "SupplementalCategories",
        "bag_text",
        "Bag",
    ),
    XmpSimpleFieldSpec(
        "XMP-photoshop:TransmissionReference",
        "photoshop",
        "TransmissionReference",
        "simple_text",
    ),
    XmpSimpleFieldSpec("XMP-xmpMM:DocumentID", "xmpMM", "DocumentID", "simple_text"),
    XmpSimpleFieldSpec("XMP-xmpRights:Marked", "xmpRights", "Marked", "boolean"),
    XmpSimpleFieldSpec("XMP-xmpRights:UsageTerms", "xmpRights", "UsageTerms", "alt_text", "Alt"),
    XmpSimpleFieldSpec(
        "XMP-microsoft:CameraSerialNumber",
        "MicrosoftPhoto",
        "CameraSerialNumber",
        "simple_text",
    ),
    XmpSimpleFieldSpec(
        "XMP-microsoft:CreatorAppID",
        "MicrosoftPhoto",
        "CreatorAppId",
        "simple_text",
    ),
    XmpSimpleFieldSpec(
        "XMP-microsoft:DateAcquired",
        "MicrosoftPhoto",
        "DateAcquired",
        "date",
    ),
    XmpSimpleFieldSpec(
        "XMP-microsoft:LastKeywordXMP",
        "MicrosoftPhoto",
        "LastKeywordXMP",
        "bag_text",
        "Bag",
    ),
    XmpSimpleFieldSpec(
        "XMP-MP1:PanoramicStitchTheta0",
        "MP1",
        "PanoramicStitchTheta0",
        "numeric",
    ),
    XmpSimpleFieldSpec(
        "XMP-MP1:WhiteBalance0",
        "MP1",
        "WhiteBalance0",
        "numeric",
    ),
    XmpSimpleFieldSpec(
        "XMP-MP:RegionInfoDateRegionsValid",
        "MP",
        "RegionInfoDateRegionsValid",
        "date",
    ),
)
XMP_PUBLIC_SIDECAR_PROPERTY_SPECS: dict[XmpWritableProperty, XmpPropertySpec] = {
    field.property_name: xmp_simple_property_spec(field)
    for field in XMP_PUBLIC_SIDECAR_SIMPLE_FIELDS
}
XMP_PUBLIC_SIDECAR_PROPERTY_NAMES = frozenset(XMP_PUBLIC_SIDECAR_PROPERTY_SPECS)


def build_xmp_property_write_plan(
    *,
    photoshop_city: str | None = None,
    dc_subject: tuple[str, ...] = (),
    xmpbj_job_ref_name: str | None = None,
    xmprights_marked: bool | None = None,
    photoshop_date_created: str | None = None,
    xmpmm_document_id: str | None = None,
) -> XmpPropertyWritePlan:
    steps: list[XmpPropertyWriteStep] = []
    if photoshop_city is not None:
        steps.append(XmpTextPropertyWrite("XMP-photoshop:City", photoshop_city))
    if dc_subject:
        steps.append(XmpTextListPropertyWrite("XMP-dc:Subject", dc_subject))
    if xmpbj_job_ref_name is not None:
        steps.append(XmpTextPropertyWrite("XMP-xmpBJ:JobRefName", xmpbj_job_ref_name))
    if xmprights_marked is not None:
        steps.append(XmpBooleanPropertyWrite("XMP-xmpRights:Marked", xmprights_marked))
    if photoshop_date_created is not None:
        steps.append(XmpTextPropertyWrite("XMP-photoshop:DateCreated", photoshop_date_created))
    if xmpmm_document_id is not None:
        steps.append(XmpTextPropertyWrite("XMP-xmpMM:DocumentID", xmpmm_document_id))
    return XmpPropertyWritePlan(
        steps=tuple(steps),
        evidence_ids=(XMP_PROPERTY_TABLE_SOURCE, XMP_PROPERTY_WRITE_SOURCE),
    )


def build_xmp_property_delete_plan(
    *,
    delete_photoshop_city: bool = False,
    delete_dc_subject: bool = False,
    delete_xmpbj_job_ref_name: bool = False,
    delete_xmprights_marked: bool = False,
    delete_photoshop_date_created: bool = False,
    delete_xmpmm_document_id: bool = False,
) -> XmpPropertyWritePlan:
    steps: list[XmpPropertyWriteStep] = []
    if delete_photoshop_city:
        steps.append(XmpPropertyDelete("XMP-photoshop:City"))
    if delete_dc_subject:
        steps.append(XmpPropertyDelete("XMP-dc:Subject"))
    if delete_xmpbj_job_ref_name:
        steps.append(XmpPropertyDelete("XMP-xmpBJ:JobRefName"))
    if delete_xmprights_marked:
        steps.append(XmpPropertyDelete("XMP-xmpRights:Marked"))
    if delete_photoshop_date_created:
        steps.append(XmpPropertyDelete("XMP-photoshop:DateCreated"))
    if delete_xmpmm_document_id:
        steps.append(XmpPropertyDelete("XMP-xmpMM:DocumentID"))
    return XmpPropertyWritePlan(
        steps=tuple(steps),
        evidence_ids=(XMP_PROPERTY_TABLE_SOURCE, XMP_PROPERTY_WRITE_SOURCE),
    )


def xmp_property_spec(property_name: XmpWritableProperty) -> XmpPropertySpec:
    public_spec = XMP_PUBLIC_SIDECAR_PROPERTY_SPECS.get(property_name)
    if public_spec is not None:
        return public_spec
    if property_name == "XMP-photoshop:City":
        return XmpPropertySpec(
            property_name=property_name,
            namespace_prefix="photoshop",
            namespace_uri="http://ns.adobe.com/photoshop/1.0/",
            element_name="City",
            value_shape="simple_text",
            evidence_ids=(XMP_PROPERTY_TABLE_SOURCE,),
        )
    if property_name == "XMP-dc:Subject":
        return XmpPropertySpec(
            property_name=property_name,
            namespace_prefix="dc",
            namespace_uri="http://purl.org/dc/elements/1.1/",
            element_name="subject",
            value_shape="bag_text",
            evidence_ids=(XMP_PROPERTY_TABLE_SOURCE,),
            rdf_container="Bag",
        )
    if property_name == "XMP-xmpBJ:JobRefName":
        return XmpPropertySpec(
            property_name=property_name,
            namespace_prefix="xmpBJ",
            namespace_uri="http://ns.adobe.com/xap/1.0/bj/",
            element_name="JobRef",
            value_shape="job_ref_name",
            evidence_ids=(XMP_PROPERTY_TABLE_SOURCE,),
        )
    if property_name == "XMP-xmpRights:Marked":
        return XmpPropertySpec(
            property_name=property_name,
            namespace_prefix="xmpRights",
            namespace_uri="http://ns.adobe.com/xap/1.0/rights/",
            element_name="Marked",
            value_shape="boolean",
            evidence_ids=(XMP_PROPERTY_TABLE_SOURCE,),
        )
    if property_name == "XMP-photoshop:DateCreated":
        return XmpPropertySpec(
            property_name=property_name,
            namespace_prefix="photoshop",
            namespace_uri="http://ns.adobe.com/photoshop/1.0/",
            element_name="DateCreated",
            value_shape="date",
            evidence_ids=(XMP_PROPERTY_TABLE_SOURCE,),
        )
    if property_name == "XMP-xmpMM:DocumentID":
        return XmpPropertySpec(
            property_name=property_name,
            namespace_prefix="xmpMM",
            namespace_uri="http://ns.adobe.com/xap/1.0/mm/",
            element_name="DocumentID",
            value_shape="simple_text",
            evidence_ids=(XMP_PROPERTY_TABLE_SOURCE,),
        )
    raise ValueError(f"Unsupported XMP property: {property_name}")


def build_user_defined_xmp_property_write_plan(
    assignments: tuple[XmpGeneratedPropertyAssignment, ...],
    property_definitions: tuple[XmpUserDefinedPropertyDefinition, ...],
) -> XmpPropertyWritePlan:
    definitions_by_property = {
        definition.property_name: definition for definition in property_definitions
    }
    struct_field_definitions_by_property: dict[
        XmpWritableProperty,
        tuple[XmpUserDefinedPropertyDefinition, XmpUserDefinedStructFieldPath],
    ] = {}
    for definition in property_definitions:
        for property_name, field_path in user_defined_struct_field_paths(
            definition.struct_fields
        ).items():
            struct_field_definitions_by_property[property_name] = (definition, field_path)
    assignments_by_property: dict[XmpWritableProperty, list[XmpGeneratedPropertyAssignment]] = {}
    struct_assignments_by_property: dict[
        XmpWritableProperty,
        list[tuple[XmpUserDefinedStructFieldPath, XmpGeneratedPropertyAssignment]],
    ] = {}
    direct_struct_steps: list[XmpUserDefinedStructPropertyWrite] = []
    direct_struct_definitions: list[XmpUserDefinedPropertyDefinition] = []
    for assignment in assignments:
        struct_field_definition = struct_field_definitions_by_property.get(assignment.property_name)
        if struct_field_definition is not None:
            parent_definition, field_path = struct_field_definition
            struct_assignments_by_property.setdefault(parent_definition.property_name, []).append(
                (field_path, assignment)
            )
            continue
        direct_definition = definitions_by_property.get(assignment.property_name)
        if direct_definition is not None and direct_definition.value_shape == "simple_struct":
            inflated_struct = inflate_xmp_struct_or_none(assignment.value)
            if inflated_struct is not None:
                direct_struct_step = user_defined_inflated_struct_write_step(
                    direct_definition,
                    inflated_struct,
                )
                if direct_struct_step is not None:
                    direct_struct_steps.append(direct_struct_step)
                    direct_struct_definitions.append(direct_definition)
                continue
        assignments_by_property.setdefault(assignment.property_name, []).append(assignment)

    steps: list[XmpPropertyWriteStep] = []
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    specs: list[XmpPropertySpec] = []
    namespace_registry: list[XmpNamespaceRegistration] = []
    seen_namespaces: set[tuple[str, str]] = set()
    for direct_definition, direct_struct_step in zip(
        direct_struct_definitions,
        direct_struct_steps,
        strict=True,
    ):
        namespace_diagnostic = user_defined_namespace_diagnostic(direct_definition)
        if namespace_diagnostic is not None:
            diagnostics.append(namespace_diagnostic)
            continue
        if not user_defined_xmp_struct_shape_supported(direct_definition):
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    direct_definition.property_name,
                    "unsupported_strategy",
                    "Only explicit user-defined XMP structures are currently supported.",
                )
            )
            continue
        specs.append(
            XmpPropertySpec(
                property_name=direct_definition.property_name,
                namespace_prefix=direct_definition.namespace_prefix,
                namespace_uri=direct_definition.namespace_uri,
                element_name=direct_definition.element_name,
                value_shape=direct_definition.value_shape,
                evidence_ids=(
                    USER_DEFINED_XMP_NAMESPACE_SOURCE,
                    USER_DEFINED_XMP_WRITER_SOURCE,
                    USER_DEFINED_XMP_TEST_SOURCE,
                ),
            )
        )
        namespace_key = (direct_definition.namespace_prefix, direct_definition.namespace_uri)
        if namespace_key not in seen_namespaces:
            namespace_registry.append(
                XmpNamespaceRegistration(
                    direct_definition.namespace_prefix,
                    direct_definition.namespace_uri,
                )
            )
            seen_namespaces.add(namespace_key)
        append_user_defined_struct_namespace_registrations(
            namespace_registry,
            seen_namespaces,
            direct_definition.struct_fields,
        )
        steps.append(direct_struct_step)

    for property_name, property_assignments in assignments_by_property.items():
        property_definition = definitions_by_property.get(property_name)
        if property_definition is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "unknown_property",
                    "User-defined XMP writes require an explicit request-scoped definition.",
                )
            )
            continue
        namespace_diagnostic = user_defined_namespace_diagnostic(property_definition)
        if namespace_diagnostic is not None:
            diagnostics.append(namespace_diagnostic)
            continue
        if not user_defined_xmp_shape_supported(property_definition):
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "unsupported_strategy",
                    (
                        "Only source-backed scalar text, RDF text list, and lang-alt "
                        "user-defined XMP writes are currently supported."
                    ),
                )
            )
            continue
        values = tuple(assignment.value for assignment in property_assignments)
        if not values:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "missing_value",
                    "User-defined XMP writes require at least one value.",
                )
            )
            continue
        spec = XmpPropertySpec(
            property_name=property_definition.property_name,
            namespace_prefix=property_definition.namespace_prefix,
            namespace_uri=property_definition.namespace_uri,
            element_name=property_definition.element_name,
            value_shape=property_definition.value_shape,
            evidence_ids=(
                USER_DEFINED_XMP_NAMESPACE_SOURCE,
                USER_DEFINED_XMP_WRITER_SOURCE,
                USER_DEFINED_XMP_TEST_SOURCE,
            ),
            rdf_container=property_definition.rdf_container,
        )
        specs.append(spec)
        namespace_key = (property_definition.namespace_prefix, property_definition.namespace_uri)
        if namespace_key not in seen_namespaces:
            namespace_registry.append(
                XmpNamespaceRegistration(
                    property_definition.namespace_prefix,
                    property_definition.namespace_uri,
                )
            )
            seen_namespaces.add(namespace_key)
        steps.append(user_defined_xmp_write_step(spec, tuple(property_assignments)))

    for property_name, struct_assignments in struct_assignments_by_property.items():
        definition = definitions_by_property[property_name]
        namespace_diagnostic = user_defined_namespace_diagnostic(definition)
        if namespace_diagnostic is not None:
            diagnostics.append(namespace_diagnostic)
            continue
        if not user_defined_xmp_struct_shape_supported(definition):
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "unsupported_strategy",
                    (
                        "Only explicit user-defined XMP structures with scalar, RDF text-list, "
                        "resource, nested, and lang-alt Bag fields are currently supported."
                    ),
                )
            )
            continue
        struct_step = user_defined_xmp_struct_write_step(definition, tuple(struct_assignments))
        if struct_step is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "missing_value",
                    "User-defined XMP structure writes require at least one field value.",
                )
            )
            continue
        spec = XmpPropertySpec(
            property_name=definition.property_name,
            namespace_prefix=definition.namespace_prefix,
            namespace_uri=definition.namespace_uri,
            element_name=definition.element_name,
            value_shape=definition.value_shape,
            evidence_ids=(
                USER_DEFINED_XMP_NAMESPACE_SOURCE,
                USER_DEFINED_XMP_WRITER_SOURCE,
                USER_DEFINED_XMP_TEST_SOURCE,
            ),
        )
        specs.append(spec)
        namespace_key = (definition.namespace_prefix, definition.namespace_uri)
        if namespace_key not in seen_namespaces:
            namespace_registry.append(
                XmpNamespaceRegistration(definition.namespace_prefix, definition.namespace_uri)
            )
            seen_namespaces.add(namespace_key)
        append_user_defined_struct_namespace_registrations(
            namespace_registry,
            seen_namespaces,
            definition.struct_fields,
        )
        steps.append(struct_step)

    return XmpPropertyWritePlan(
        steps=tuple(steps),
        evidence_ids=(
            USER_DEFINED_XMP_NAMESPACE_SOURCE,
            USER_DEFINED_XMP_WRITER_SOURCE,
            USER_DEFINED_XMP_TEST_SOURCE,
        ),
        generated_diagnostics=tuple(diagnostics),
        generated_specs=tuple(specs),
        namespace_registry=tuple(namespace_registry),
    )


def user_defined_namespace_diagnostic(
    definition: XmpUserDefinedPropertyDefinition,
) -> XmpGeneratedPlanDiagnostic | None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", definition.namespace_prefix):
        return XmpGeneratedPlanDiagnostic(
            definition.property_name,
            "unsupported_namespace",
            "User-defined XMP namespace prefixes must be valid XML namespace prefixes.",
        )
    if not definition.namespace_uri:
        return XmpGeneratedPlanDiagnostic(
            definition.property_name,
            "unsupported_namespace",
            "User-defined XMP namespace registrations require a non-empty URI.",
        )
    if not definition.property_name.startswith(f"XMP-{definition.namespace_prefix}:"):
        return XmpGeneratedPlanDiagnostic(
            definition.property_name,
            "unsupported_namespace",
            "User-defined XMP property names must use the registered family-1 prefix.",
        )
    return None


def user_defined_xmp_shape_supported(definition: XmpUserDefinedPropertyDefinition) -> bool:
    if definition.value_shape == "simple_text" and definition.rdf_container is None:
        return True
    if definition.value_shape in {"bag_text", "seq_text", "alt_text"}:
        return definition.rdf_container in {"Bag", "Seq", "Alt"}
    return False


def user_defined_xmp_struct_shape_supported(
    definition: XmpUserDefinedPropertyDefinition,
) -> bool:
    if definition.value_shape != "simple_struct" or definition.rdf_container is not None:
        return False
    if not definition.struct_fields:
        return False
    for field_definition in definition.struct_fields:
        if not user_defined_struct_field_shape_supported(
            definition.namespace_prefix,
            field_definition,
        ):
            return False
    return True


def user_defined_struct_field_shape_supported(
    namespace_prefix: str,
    field_definition: XmpUserDefinedStructFieldDefinition,
) -> bool:
    if not user_defined_struct_field_property_name_supported(namespace_prefix, field_definition):
        return False
    if field_definition.value_shape == "simple_struct":
        return bool(field_definition.struct_fields) and all(
            user_defined_struct_field_shape_supported(namespace_prefix, nested_field)
            for nested_field in field_definition.struct_fields
        )
    if field_definition.value_shape == "alt_text":
        return field_definition.rdf_container in {None, "Bag", "Alt"}
    if field_definition.value_shape in {"bag_text", "seq_text", "alt_text"}:
        return field_definition.rdf_container in {"Bag", "Seq", "Alt"}
    return field_definition.value_shape == "simple_text" and field_definition.rdf_container is None


def user_defined_struct_field_property_name_supported(
    namespace_prefix: str,
    field_definition: XmpUserDefinedStructFieldDefinition,
) -> bool:
    if field_definition.namespace_uri is None:
        return field_definition.flattened_property_name.startswith(f"XMP-{namespace_prefix}:")
    return user_defined_struct_field_namespace_prefix(field_definition) is not None


def user_defined_struct_field_namespace_prefix(
    field_definition: XmpUserDefinedStructFieldDefinition,
) -> str | None:
    prefix_match = re.fullmatch(r"XMP-([^:]+):.+", field_definition.flattened_property_name)
    if prefix_match is None:
        return None
    prefix = prefix_match.group(1)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", prefix) is None:
        return None
    return prefix


def append_user_defined_struct_namespace_registrations(
    namespace_registry: list[XmpNamespaceRegistration],
    seen_namespaces: set[tuple[str, str]],
    field_definitions: tuple[XmpUserDefinedStructFieldDefinition, ...],
) -> None:
    for field_definition in field_definitions:
        if field_definition.namespace_uri is not None:
            prefix = user_defined_struct_field_namespace_prefix(field_definition)
            namespace_key = (prefix or "", field_definition.namespace_uri)
            if prefix is not None and namespace_key not in seen_namespaces:
                namespace_registry.append(
                    XmpNamespaceRegistration(prefix, field_definition.namespace_uri)
                )
                seen_namespaces.add(namespace_key)
        append_user_defined_struct_namespace_registrations(
            namespace_registry,
            seen_namespaces,
            field_definition.struct_fields,
        )


def user_defined_xmp_write_step(
    spec: XmpPropertySpec,
    assignments: tuple[XmpGeneratedPropertyAssignment, ...],
) -> XmpPropertyWriteStep:
    if spec.value_shape == "alt_text":
        values = tuple(
            XmpLocalizedTextValue(assignment.language_code or "x-default", assignment.value)
            for assignment in assignments
        )
        return XmpLocalizedTextPropertyWrite(spec.property_name, values)
    if spec.rdf_container is not None:
        return XmpTextListPropertyWrite(
            spec.property_name,
            tuple(assignment.value for assignment in assignments),
        )
    return XmpTextPropertyWrite(spec.property_name, assignments[-1].value)


def user_defined_xmp_struct_write_step(
    definition: XmpUserDefinedPropertyDefinition,
    assignments: tuple[tuple[XmpUserDefinedStructFieldPath, XmpGeneratedPropertyAssignment], ...],
) -> XmpUserDefinedStructPropertyWrite | None:
    fields = list(user_defined_struct_fields_from_path_assignments(assignments))
    if not fields:
        return None
    return XmpUserDefinedStructPropertyWrite(
        property_name=definition.property_name,
        namespace_uri=definition.namespace_uri,
        element_name=definition.element_name,
        struct_type_resource=definition.struct_type_resource,
        lang_alt_bag_fields=tuple(
            field
            for field in fields
            if isinstance(field, XmpUserDefinedStructLangAltListFieldWrite)
        ),
        fields=tuple(fields),
    )


def user_defined_struct_fields_from_path_assignments(
    assignments: tuple[tuple[XmpUserDefinedStructFieldPath, XmpGeneratedPropertyAssignment], ...],
) -> tuple[XmpUserDefinedStructFieldWrite, ...]:
    field_assignments: dict[
        str,
        tuple[
            XmpUserDefinedStructFieldDefinition,
            list[XmpGeneratedPropertyAssignment],
        ],
    ] = {}
    nested_assignments: dict[
        str,
        tuple[
            XmpUserDefinedStructFieldDefinition,
            list[tuple[XmpUserDefinedStructFieldPath, XmpGeneratedPropertyAssignment]],
        ],
    ] = {}
    for field_path, assignment in assignments:
        if not field_path:
            continue
        field_definition = field_path[0]
        if len(field_path) == 1:
            existing = field_assignments.get(field_definition.flattened_property_name)
            if existing is None:
                field_assignments[field_definition.flattened_property_name] = (
                    field_definition,
                    [assignment],
                )
            else:
                existing[1].append(assignment)
            continue
        nested_existing = nested_assignments.get(field_definition.flattened_property_name)
        nested_path = field_path[1:]
        if nested_existing is None:
            nested_assignments[field_definition.flattened_property_name] = (
                field_definition,
                [(nested_path, assignment)],
            )
        else:
            nested_existing[1].append((nested_path, assignment))

    fields: list[XmpUserDefinedStructFieldWrite] = []
    for field_definition, field_values in field_assignments.values():
        field = user_defined_struct_field_write(field_definition, field_values)
        if field is not None:
            fields.append(field)
    for field_definition, nested_values in nested_assignments.values():
        nested_fields = user_defined_struct_fields_from_path_assignments(tuple(nested_values))
        if nested_fields:
            fields.append(
                XmpUserDefinedStructNestedFieldWrite(
                    field_definition.field_name,
                    nested_fields,
                    field_definition.namespace_uri,
                )
            )
    return tuple(fields)


def user_defined_struct_field_write(
    field_definition: XmpUserDefinedStructFieldDefinition,
    assignments: list[XmpGeneratedPropertyAssignment],
) -> XmpUserDefinedStructFieldWrite | None:
    if field_definition.value_shape == "alt_text" and field_definition.rdf_container == "Bag":
        return user_defined_lang_alt_bag_field_write(field_definition, assignments)
    if field_definition.value_shape == "alt_text" and field_definition.rdf_container in {
        None,
        "Alt",
    }:
        return XmpUserDefinedStructLangAltFieldWrite(
            field_definition.field_name,
            tuple(
                XmpLocalizedTextValue(
                    normalized_xmp_language_code(assignment.language_code or "x-default")
                    or "x-default",
                    assignment.value,
                )
                for assignment in assignments
            ),
            field_definition.namespace_uri,
        )
    if field_definition.value_shape in {"bag_text", "seq_text", "alt_text"}:
        if field_definition.rdf_container is None:
            return None
        return XmpUserDefinedStructListFieldWrite(
            field_definition.field_name,
            field_definition.rdf_container,
            tuple(assignment.value for assignment in assignments),
            field_definition.namespace_uri,
        )
    if field_definition.value_shape == "simple_text" and field_definition.rdf_container is None:
        return XmpUserDefinedStructScalarFieldWrite(
            field_definition.field_name,
            assignments[-1].value,
            field_definition.namespace_uri,
            field_definition.resource,
        )
    return None


def user_defined_lang_alt_bag_field_write(
    field_definition: XmpUserDefinedStructFieldDefinition,
    assignments: list[XmpGeneratedPropertyAssignment],
) -> XmpUserDefinedStructLangAltListFieldWrite | None:
    values_by_language: dict[XmpLanguageCode, list[str]] = {}
    language_order: list[XmpLanguageCode] = []
    for assignment in assignments:
        language_code = assignment.language_code or "x-default"
        if language_code not in values_by_language:
            values_by_language[language_code] = []
            language_order.append(language_code)
        values_by_language[language_code].append(assignment.value)
    max_item_count = max((len(values) for values in values_by_language.values()), default=0)
    item_groups: list[tuple[XmpLocalizedTextValue, ...]] = []
    for index in range(max_item_count):
        item_values: list[XmpLocalizedTextValue] = []
        for language_code in language_order:
            language_values = values_by_language[language_code]
            if index >= len(language_values):
                continue
            value = language_values[index]
            if not value:
                continue
            item_values.append(XmpLocalizedTextValue(language_code, value))
        if item_values:
            item_groups.append(tuple(item_values))
    if not item_groups:
        return None
    return XmpUserDefinedStructLangAltListFieldWrite(
        field_definition.field_name,
        tuple(item_groups),
        field_definition.namespace_uri,
    )


def user_defined_inflated_struct_assignments(
    definition: XmpUserDefinedPropertyDefinition,
    inflated_struct: XmpInflatedStruct,
) -> tuple[tuple[XmpUserDefinedStructFieldDefinition, XmpGeneratedPropertyAssignment], ...]:
    assignments: list[
        tuple[XmpUserDefinedStructFieldDefinition, XmpGeneratedPropertyAssignment]
    ] = []
    definitions_by_field = {field.field_name.lower(): field for field in definition.struct_fields}
    definitions_by_flat = {
        field.flattened_property_name.rsplit(":", 1)[-1].lower(): field
        for field in definition.struct_fields
    }
    for inflated_field in inflated_struct.fields:
        field_definition = definitions_by_field.get(
            inflated_field.name.lower()
        ) or definitions_by_flat.get(inflated_field.name.lower())
        if field_definition is None:
            continue
        assignments.extend(
            user_defined_inflated_field_assignments(field_definition, inflated_field.value)
        )
    return tuple(assignments)


def user_defined_struct_field_paths(
    field_definitions: tuple[XmpUserDefinedStructFieldDefinition, ...],
) -> dict[XmpWritableProperty, XmpUserDefinedStructFieldPath]:
    paths: dict[XmpWritableProperty, XmpUserDefinedStructFieldPath] = {}
    for field_definition in field_definitions:
        user_defined_collect_struct_field_paths(field_definition, (field_definition,), paths)
    return paths


def user_defined_collect_struct_field_paths(
    field_definition: XmpUserDefinedStructFieldDefinition,
    path: XmpUserDefinedStructFieldPath,
    paths: dict[XmpWritableProperty, XmpUserDefinedStructFieldPath],
) -> None:
    paths[field_definition.flattened_property_name] = path
    for nested_field in field_definition.struct_fields:
        user_defined_collect_struct_field_paths(nested_field, (*path, nested_field), paths)


def user_defined_inflated_struct_write_step(
    definition: XmpUserDefinedPropertyDefinition,
    inflated_struct: XmpInflatedStruct,
) -> XmpUserDefinedStructPropertyWrite | None:
    fields = user_defined_inflated_struct_fields(definition.struct_fields, inflated_struct)
    if not fields:
        return None
    return XmpUserDefinedStructPropertyWrite(
        property_name=definition.property_name,
        namespace_uri=definition.namespace_uri,
        element_name=definition.element_name,
        struct_type_resource=definition.struct_type_resource,
        lang_alt_bag_fields=tuple(
            field
            for field in fields
            if isinstance(field, XmpUserDefinedStructLangAltListFieldWrite)
        ),
        fields=fields,
    )


def user_defined_inflated_struct_fields(
    field_definitions: tuple[XmpUserDefinedStructFieldDefinition, ...],
    inflated_struct: XmpInflatedStruct,
) -> tuple[XmpUserDefinedStructFieldWrite, ...]:
    fields: list[XmpUserDefinedStructFieldWrite] = []
    definitions_by_field = {field.field_name.lower(): field for field in field_definitions}
    definitions_by_flat = {
        field.flattened_property_name.rsplit(":", 1)[-1].lower(): field
        for field in field_definitions
    }
    for inflated_field in inflated_struct.fields:
        field_definition = definitions_by_field.get(
            inflated_field.name.lower()
        ) or definitions_by_flat.get(inflated_field.name.lower())
        if field_definition is None:
            continue
        field = user_defined_inflated_field_write(field_definition, inflated_field.value)
        if field is not None:
            fields.append(field)
    return tuple(fields)


def user_defined_inflated_field_write(
    field_definition: XmpUserDefinedStructFieldDefinition,
    value: XmpInflatedValue,
) -> XmpUserDefinedStructFieldWrite | None:
    if field_definition.value_shape == "simple_struct":
        if not isinstance(value, XmpInflatedStruct):
            return None
        nested_fields = user_defined_inflated_struct_fields(
            field_definition.struct_fields,
            value,
        )
        if not nested_fields:
            return None
        return XmpUserDefinedStructNestedFieldWrite(
            field_definition.field_name,
            nested_fields,
            field_definition.namespace_uri,
        )
    if field_definition.value_shape == "alt_text" and field_definition.rdf_container == "Bag":
        assignments = inflated_lang_alt_assignments(field_definition, value)
        if not assignments:
            return None
        return user_defined_lang_alt_bag_field_write(field_definition, list(assignments))
    if field_definition.value_shape == "alt_text" and field_definition.rdf_container in {
        None,
        "Alt",
    }:
        values = inflated_text_values(value)
        if not values:
            return None
        return XmpUserDefinedStructLangAltFieldWrite(
            field_definition.field_name,
            tuple(XmpLocalizedTextValue("x-default", inflated_value) for inflated_value in values),
            field_definition.namespace_uri,
        )
    if field_definition.value_shape in {"bag_text", "seq_text", "alt_text"}:
        if field_definition.rdf_container is None:
            return None
        values = inflated_text_values(value)
        if not values:
            return None
        return XmpUserDefinedStructListFieldWrite(
            field_definition.field_name,
            field_definition.rdf_container,
            values,
            field_definition.namespace_uri,
        )
    if field_definition.value_shape == "simple_text" and isinstance(value, str):
        return XmpUserDefinedStructScalarFieldWrite(
            field_definition.field_name,
            value,
            field_definition.namespace_uri,
            field_definition.resource,
        )
    return None


def inflated_text_values(value: XmpInflatedValue) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, XmpInflatedList):
        return tuple(item for item in value.values if isinstance(item, str))
    return ()


def inflated_lang_alt_assignments(
    field_definition: XmpUserDefinedStructFieldDefinition,
    value: XmpInflatedValue,
) -> tuple[XmpGeneratedPropertyAssignment, ...]:
    if isinstance(value, XmpInflatedList):
        return tuple(
            XmpGeneratedPropertyAssignment(field_definition.flattened_property_name, item)
            for item in value.values
            if isinstance(item, str)
        )
    if isinstance(value, str):
        return (XmpGeneratedPropertyAssignment(field_definition.flattened_property_name, value),)
    return ()


def user_defined_inflated_field_assignments(
    field_definition: XmpUserDefinedStructFieldDefinition,
    value: XmpInflatedValue,
) -> tuple[tuple[XmpUserDefinedStructFieldDefinition, XmpGeneratedPropertyAssignment], ...]:
    if isinstance(value, XmpInflatedStruct):
        return user_defined_inflated_nested_assignments(field_definition, value)
    if isinstance(value, XmpInflatedList):
        assignments: list[
            tuple[XmpUserDefinedStructFieldDefinition, XmpGeneratedPropertyAssignment]
        ] = []
        for item in value.values:
            if isinstance(item, str):
                assignments.append(
                    (
                        field_definition,
                        XmpGeneratedPropertyAssignment(
                            field_definition.flattened_property_name,
                            item,
                        ),
                    )
                )
        return tuple(assignments)
    return (
        (
            field_definition,
            XmpGeneratedPropertyAssignment(field_definition.flattened_property_name, value),
        ),
    )


def user_defined_inflated_nested_assignments(
    field_definition: XmpUserDefinedStructFieldDefinition,
    value: XmpInflatedStruct,
) -> tuple[tuple[XmpUserDefinedStructFieldDefinition, XmpGeneratedPropertyAssignment], ...]:
    if field_definition.value_shape != "simple_struct":
        return ()
    nested_definitions_by_field = {
        nested_field.field_name.lower(): nested_field
        for nested_field in field_definition.struct_fields
    }
    assignments: list[
        tuple[XmpUserDefinedStructFieldDefinition, XmpGeneratedPropertyAssignment]
    ] = []
    for inflated_field in value.fields:
        nested_definition = nested_definitions_by_field.get(inflated_field.name.lower())
        if nested_definition is None:
            continue
        assignments.extend(
            user_defined_inflated_field_assignments(nested_definition, inflated_field.value)
        )
    return tuple(assignments)


def inflate_xmp_struct_or_none(value: str) -> XmpInflatedStruct | None:
    parser = XmpInflateStructParser(value)
    inflated = parser.parse_value()
    parser.skip_space()
    if not isinstance(inflated, XmpInflatedStruct) or not parser.at_end:
        return None
    return inflated


class XmpInflateStructParser:
    def __init__(self, text: str) -> None:
        self._text = text
        self._index = 0

    @property
    def at_end(self) -> bool:
        return self._index >= len(self._text)

    def parse_value(self) -> XmpInflatedValue | None:
        self.skip_space()
        if self.consume("{"):
            return self.parse_struct()
        if self.consume("["):
            return self.parse_list()
        return self.parse_scalar()

    def parse_struct(self) -> XmpInflatedStruct | None:
        fields: list[XmpInflatedStructField] = []
        self.skip_space()
        if self.consume("}"):
            return XmpInflatedStruct(())
        while not self.at_end:
            name = self.parse_name()
            if name is None or not self.consume("="):
                return None
            value = self.parse_value()
            if value is None:
                return None
            fields.append(XmpInflatedStructField(name, value))
            self.skip_space()
            if self.consume("}"):
                return XmpInflatedStruct(tuple(fields))
            if not self.consume(","):
                return None
        return None

    def parse_list(self) -> XmpInflatedList | None:
        values: list[XmpInflatedValue] = []
        self.skip_space()
        if self.consume("]"):
            return XmpInflatedList(())
        while not self.at_end:
            value = self.parse_value()
            if value is None:
                return None
            values.append(value)
            self.skip_space()
            if self.consume("]"):
                return XmpInflatedList(tuple(values))
            if not self.consume(","):
                return None
        return None

    def parse_name(self) -> str | None:
        self.skip_space()
        start = self._index
        while not self.at_end and re.fullmatch(r"[-\w:.#]", self._text[self._index]):
            self._index += 1
        if self._index == start:
            return None
        return self._text[start : self._index]

    def parse_scalar(self) -> str:
        start = self._index
        while not self.at_end and self._text[self._index] not in ",]}":
            self._index += 1
        return self._text[start : self._index].strip()

    def skip_space(self) -> None:
        while not self.at_end and self._text[self._index].isspace():
            self._index += 1

    def consume(self, token: str) -> bool:
        self.skip_space()
        if self._text.startswith(token, self._index):
            self._index += len(token)
            return True
        return False


def build_public_xmp_sidecar_property_write_plan(
    assignments: tuple[XmpPublicSidecarPropertyAssignment, ...],
    list_separator: str | None = None,
) -> XmpPropertyWritePlan:
    steps: list[XmpPropertyWriteStep] = []
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    specs: list[XmpPropertySpec] = []
    assignments_by_property: dict[
        XmpWritableProperty, list[XmpPublicSidecarPropertyAssignment]
    ] = {}
    for assignment in assignments:
        assignments_by_property.setdefault(assignment.property_name, []).append(assignment)

    for property_name, property_assignments in assignments_by_property.items():
        if property_name not in XMP_PUBLIC_SIDECAR_PROPERTY_NAMES:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "unknown_property",
                    "Property is outside the source-backed public XMP sidecar write subset.",
                )
            )
            continue
        spec = xmp_property_spec(property_name)
        specs.append(spec)
        values = public_sidecar_assignment_values(property_assignments, list_separator)
        if not values:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "missing_value",
                    "Public XMP sidecar writes require at least one value.",
                )
            )
            continue
        if spec.value_shape == "boolean":
            bool_value = xmp_bool_or_none(values[-1])
            if bool_value is None:
                diagnostics.append(
                    XmpGeneratedPlanDiagnostic(
                        property_name,
                        "invalid_value",
                        "Boolean public XMP sidecar writes require true/false, 1/0, or yes/no.",
                    )
                )
                continue
            steps.append(XmpBooleanPropertyWrite(property_name, bool_value))
            continue
        if spec.rdf_container is not None:
            steps.append(XmpTextListPropertyWrite(property_name, values))
            continue
        steps.append(XmpTextPropertyWrite(property_name, values[-1]))

    return XmpPropertyWritePlan(
        steps=tuple(steps),
        evidence_ids=(XMP_PROPERTY_TABLE_SOURCE, XMP_PROPERTY_WRITE_SOURCE),
        generated_diagnostics=tuple(diagnostics),
        generated_specs=tuple(specs),
    )


def build_public_xmp_sidecar_property_delete_plan(
    deletes: tuple[XmpPublicSidecarPropertyDelete, ...],
) -> XmpPropertyWritePlan:
    steps: list[XmpPropertyWriteStep] = []
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    specs: list[XmpPropertySpec] = []
    for delete in deletes:
        if delete.property_name not in XMP_PUBLIC_SIDECAR_PROPERTY_NAMES:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    delete.property_name,
                    "unknown_property",
                    "Property is outside the source-backed public XMP sidecar delete subset.",
                )
            )
            continue
        spec = xmp_property_spec(delete.property_name)
        specs.append(spec)
        steps.append(XmpPropertyDelete(delete.property_name))
    return XmpPropertyWritePlan(
        steps=tuple(steps),
        evidence_ids=(XMP_PROPERTY_TABLE_SOURCE, XMP_PROPERTY_WRITE_SOURCE),
        generated_diagnostics=tuple(diagnostics),
        generated_specs=tuple(specs),
    )


def public_sidecar_assignment_values(
    assignments: list[XmpPublicSidecarPropertyAssignment],
    list_separator: str | None,
) -> tuple[str, ...]:
    values: list[str] = []
    for assignment in assignments:
        if list_separator is None:
            values.append(assignment.value)
        else:
            values.extend(split_xmp_public_list_value(assignment.value, list_separator))
    return tuple(values)


def split_xmp_public_list_value(value: str, separator: str) -> tuple[str, ...]:
    if separator == "":
        return tuple(value)
    pattern = re.escape(separator).replace(r"\ ", r"\s*")
    if pattern == r"\s*":
        pattern = r"\s+"
    return tuple(re.split(pattern, value))


def build_generated_xmp_property_write_plan(
    capabilities_path: Path,
    assignments: tuple[XmpGeneratedPropertyAssignment, ...],
    tag_lookup: TagLookupRepository | None = None,
) -> XmpPropertyWritePlan:
    capabilities = generated_capabilities_by_property(capabilities_path)
    steps: list[XmpPropertyWriteStep] = []
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    specs: list[XmpPropertySpec] = []
    resource_ref_assignments_by_parent: dict[
        XmpWritableProperty, list[XmpGeneratedPropertyAssignment]
    ] = {}
    resource_event_assignments_by_parent: dict[
        XmpWritableProperty, list[XmpGeneratedPropertyAssignment]
    ] = {}
    job_ref_assignments_by_parent: dict[
        XmpWritableProperty, list[XmpGeneratedPropertyAssignment]
    ] = {}
    manifest_item_assignments_by_parent: dict[
        XmpWritableProperty, list[XmpGeneratedPropertyAssignment]
    ] = {}
    pantry_item_assignments_by_parent: dict[
        XmpWritableProperty, list[XmpGeneratedPropertyAssignment]
    ] = {}
    simple_struct_assignments_by_parent: dict[
        XmpWritableProperty, list[XmpGeneratedPropertyAssignment]
    ] = {}
    assignments_by_property: dict[XmpWritableProperty, list[XmpGeneratedPropertyAssignment]] = {}
    for assignment in assignments:
        job_ref_target = job_ref_assignment_target(assignment.property_name)
        if job_ref_target is not None:
            job_ref_assignments_by_parent.setdefault(
                job_ref_target.parent_spec.property_name,
                [],
            ).append(assignment)
            continue
        manifest_item_target = manifest_item_assignment_target(assignment.property_name)
        if manifest_item_target is not None:
            manifest_item_assignments_by_parent.setdefault(
                manifest_item_target.parent_spec.property_name,
                [],
            ).append(assignment)
            continue
        pantry_item_target = pantry_item_assignment_target(assignment.property_name)
        if pantry_item_target is not None:
            pantry_item_assignments_by_parent.setdefault(
                pantry_item_target.parent_spec.property_name,
                [],
            ).append(assignment)
            continue
        simple_struct_target = simple_struct_assignment_target(assignment.property_name)
        if simple_struct_target is not None:
            simple_struct_assignments_by_parent.setdefault(
                simple_struct_target.parent_spec.property_name,
                [],
            ).append(assignment)
            continue
        target = resource_ref_assignment_target(assignment.property_name)
        if target is not None:
            resource_ref_assignments_by_parent.setdefault(
                target.parent_spec.property_name,
                [],
            ).append(assignment)
            continue
        event_target = resource_event_assignment_target(assignment.property_name)
        if event_target is not None:
            resource_event_assignments_by_parent.setdefault(
                event_target.parent_spec.property_name,
                [],
            ).append(assignment)
            continue
        assignments_by_property.setdefault(assignment.property_name, []).append(assignment)
    for parent_property, parent_assignments in job_ref_assignments_by_parent.items():
        capability = capabilities.get(parent_property)
        if capability is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    parent_property,
                    "unknown_property",
                    "JobRef parent property is not present in the generated XMP audit.",
                )
            )
            continue
        tag_lookup_diagnostic = tag_lookup_diagnostic_for_capability(capability, tag_lookup)
        if tag_lookup_diagnostic is not None:
            diagnostics.append(tag_lookup_diagnostic)
            continue
        spec = generated_job_ref_property_spec(capability)
        if spec is None:
            diagnostics.append(unsupported_capability_diagnostic(capability))
            continue
        specs.append(spec)
        job_ref_validation = validate_job_ref_property_values(parent_property, parent_assignments)
        if job_ref_validation.diagnostics:
            diagnostics.extend(job_ref_validation.diagnostics)
            continue
        steps.append(XmpJobRefPropertyWrite(parent_property, job_ref_validation.values))
    for parent_property, parent_assignments in manifest_item_assignments_by_parent.items():
        capability = capabilities.get(parent_property)
        if capability is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    parent_property,
                    "unknown_property",
                    "ManifestItem parent property is not present in the generated XMP audit.",
                )
            )
            continue
        tag_lookup_diagnostic = tag_lookup_diagnostic_for_capability(capability, tag_lookup)
        if tag_lookup_diagnostic is not None:
            diagnostics.append(tag_lookup_diagnostic)
            continue
        spec = generated_manifest_item_property_spec(capability)
        if spec is None:
            diagnostics.append(unsupported_capability_diagnostic(capability))
            continue
        specs.append(spec)
        manifest_item_validation = validate_manifest_item_property_values(
            parent_property,
            parent_assignments,
        )
        if manifest_item_validation.diagnostics:
            diagnostics.extend(manifest_item_validation.diagnostics)
            continue
        steps.append(XmpManifestItemPropertyWrite(parent_property, manifest_item_validation.values))
    for parent_property, parent_assignments in pantry_item_assignments_by_parent.items():
        capability = capabilities.get(parent_property)
        if capability is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    parent_property,
                    "unknown_property",
                    "PantryItem parent property is not present in the generated XMP audit.",
                )
            )
            continue
        tag_lookup_diagnostic = tag_lookup_diagnostic_for_capability(capability, tag_lookup)
        if tag_lookup_diagnostic is not None:
            diagnostics.append(tag_lookup_diagnostic)
            continue
        spec = generated_pantry_item_property_spec(capability)
        if spec is None:
            diagnostics.append(unsupported_capability_diagnostic(capability))
            continue
        specs.append(spec)
        pantry_item_validation = validate_pantry_item_property_values(
            parent_property,
            parent_assignments,
        )
        if pantry_item_validation.diagnostics:
            diagnostics.extend(pantry_item_validation.diagnostics)
            continue
        steps.append(XmpPantryItemPropertyWrite(parent_property, pantry_item_validation.values))
    for parent_property, parent_assignments in resource_ref_assignments_by_parent.items():
        capability = capabilities.get(parent_property)
        if capability is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    parent_property,
                    "unknown_property",
                    "ResourceRef parent property is not present in the generated XMP audit.",
                )
            )
            continue
        tag_lookup_diagnostic = tag_lookup_diagnostic_for_capability(capability, tag_lookup)
        if tag_lookup_diagnostic is not None:
            diagnostics.append(tag_lookup_diagnostic)
            continue
        spec = generated_resource_ref_property_spec(capability)
        if spec is None:
            diagnostics.append(unsupported_capability_diagnostic(capability))
            continue
        specs.append(spec)
        validation = validate_resource_ref_property_values(parent_property, parent_assignments)
        if validation.diagnostics:
            diagnostics.extend(validation.diagnostics)
            continue
        steps.append(XmpResourceRefPropertyWrite(parent_property, validation.values))
    for parent_property, parent_assignments in resource_event_assignments_by_parent.items():
        capability = capabilities.get(parent_property)
        if capability is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    parent_property,
                    "unknown_property",
                    "ResourceEvent parent property is not present in the generated XMP audit.",
                )
            )
            continue
        tag_lookup_diagnostic = tag_lookup_diagnostic_for_capability(capability, tag_lookup)
        if tag_lookup_diagnostic is not None:
            diagnostics.append(tag_lookup_diagnostic)
            continue
        spec = generated_resource_event_property_spec(capability)
        if spec is None:
            diagnostics.append(unsupported_capability_diagnostic(capability))
            continue
        specs.append(spec)
        event_validation = validate_resource_event_property_values(
            parent_property, parent_assignments
        )
        if event_validation.diagnostics:
            diagnostics.extend(event_validation.diagnostics)
            continue
        steps.append(XmpResourceEventPropertyWrite(parent_property, event_validation.values))
    for parent_property, parent_assignments in simple_struct_assignments_by_parent.items():
        capability = capabilities.get(parent_property)
        if capability is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    parent_property,
                    "unknown_property",
                    "Simple struct parent property is not present in the generated XMP audit.",
                )
            )
            continue
        tag_lookup_diagnostic = tag_lookup_diagnostic_for_capability(capability, tag_lookup)
        if tag_lookup_diagnostic is not None:
            diagnostics.append(tag_lookup_diagnostic)
            continue
        spec = generated_simple_struct_property_spec(capability)
        if spec is None:
            diagnostics.append(unsupported_capability_diagnostic(capability))
            continue
        specs.append(spec)
        simple_struct_validation = validate_simple_struct_property_values(
            parent_property,
            parent_assignments,
        )
        if simple_struct_validation.diagnostics:
            diagnostics.extend(simple_struct_validation.diagnostics)
            continue
        if simple_struct_validation.parent_spec.shape == "struct_list":
            steps.append(
                XmpSimpleStructListPropertyWrite(
                    parent_property,
                    simple_struct_validation.parent_spec,
                    simple_struct_validation.item_groups,
                )
            )
        else:
            steps.append(
                XmpSimpleStructPropertyWrite(
                    parent_property,
                    simple_struct_validation.parent_spec,
                    simple_struct_validation.values,
                )
            )
    for property_name, property_assignments in assignments_by_property.items():
        capability = capabilities.get(property_name)
        if capability is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "unknown_property",
                    "Property is not present in the generated XMP write capability audit.",
                )
            )
            continue
        tag_lookup_diagnostic = tag_lookup_diagnostic_for_capability(capability, tag_lookup)
        if tag_lookup_diagnostic is not None:
            diagnostics.append(tag_lookup_diagnostic)
            continue
        spec = generated_property_spec(capability)
        if spec is None:
            diagnostics.append(unsupported_capability_diagnostic(capability))
            continue
        specs.append(spec)
        if not property_assignments:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "missing_value",
                    "Generated XMP property writes require at least one value.",
                )
            )
            continue
        if spec.value_shape == "alt_text":
            lang_alt_validation = validate_lang_alt_property_values(
                property_name,
                property_assignments,
            )
            if lang_alt_validation.diagnostics:
                diagnostics.extend(lang_alt_validation.diagnostics)
                continue
            if any(assignment.language_code is not None for assignment in property_assignments):
                steps.append(
                    XmpLocalizedTextPropertyPatch(
                        property_name,
                        writes=lang_alt_validation.values,
                    )
                )
                continue
            steps.append(XmpLocalizedTextPropertyWrite(property_name, lang_alt_validation.values))
            continue
        language_diagnostics = unsupported_language_diagnostics(property_name, property_assignments)
        if language_diagnostics:
            diagnostics.extend(language_diagnostics)
            continue
        values = [assignment.value for assignment in property_assignments]
        value_validation = validate_generated_property_values(
            property_name, spec, capability, values
        )
        if value_validation.diagnostics:
            diagnostics.extend(value_validation.diagnostics)
            continue
        if spec.rdf_container is not None:
            steps.append(XmpTextListPropertyWrite(property_name, value_validation.values))
            continue
        scalar_value = value_validation.values[-1]
        if spec.value_shape == "boolean":
            bool_value = xmp_bool_or_none(scalar_value)
            if bool_value is None:
                diagnostics.append(
                    XmpGeneratedPlanDiagnostic(
                        property_name,
                        "invalid_value",
                        "Boolean generated XMP writes require true/false, 1/0, or yes/no.",
                    )
                )
                continue
            steps.append(XmpBooleanPropertyWrite(property_name, bool_value))
        else:
            steps.append(XmpTextPropertyWrite(property_name, scalar_value))
    return XmpPropertyWritePlan(
        steps=tuple(steps),
        evidence_ids=(GENERATED_PROPERTY_SOURCE, XMP_PROPERTY_WRITE_SOURCE),
        generated_diagnostics=tuple(diagnostics),
        generated_specs=tuple(specs),
    )


def build_generated_xmp_property_delete_plan(
    capabilities_path: Path,
    deletes: tuple[XmpGeneratedPropertyDelete, ...],
    tag_lookup: TagLookupRepository | None = None,
) -> XmpPropertyWritePlan:
    capabilities = generated_capabilities_by_property(capabilities_path)
    steps: list[XmpPropertyWriteStep] = []
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    specs: list[XmpPropertySpec] = []
    job_ref_parent_deletes: dict[XmpWritableProperty, XmpGeneratedPropertyDelete] = {}
    manifest_item_parent_deletes: dict[XmpWritableProperty, XmpGeneratedPropertyDelete] = {}
    pantry_item_parent_deletes: dict[XmpWritableProperty, XmpGeneratedPropertyDelete] = {}
    resource_ref_parent_deletes: dict[XmpWritableProperty, XmpGeneratedPropertyDelete] = {}
    resource_event_parent_deletes: dict[XmpWritableProperty, XmpGeneratedPropertyDelete] = {}
    simple_struct_parent_deletes: dict[XmpWritableProperty, XmpGeneratedPropertyDelete] = {}
    regular_deletes: list[XmpGeneratedPropertyDelete] = []
    for delete in deletes:
        job_ref_target = job_ref_assignment_target(delete.property_name)
        if job_ref_target is not None:
            job_ref_parent_deletes[job_ref_target.parent_spec.property_name] = (
                XmpGeneratedPropertyDelete(job_ref_target.parent_spec.property_name)
            )
            continue
        manifest_item_target = manifest_item_assignment_target(delete.property_name)
        if manifest_item_target is not None:
            manifest_item_parent_deletes[manifest_item_target.parent_spec.property_name] = (
                XmpGeneratedPropertyDelete(manifest_item_target.parent_spec.property_name)
            )
            continue
        pantry_item_target = pantry_item_assignment_target(delete.property_name)
        if pantry_item_target is not None:
            pantry_item_parent_deletes[pantry_item_target.parent_spec.property_name] = (
                XmpGeneratedPropertyDelete(pantry_item_target.parent_spec.property_name)
            )
            continue
        simple_struct_target = simple_struct_assignment_target(delete.property_name)
        if simple_struct_target is not None:
            simple_struct_parent_deletes[simple_struct_target.parent_spec.property_name] = (
                XmpGeneratedPropertyDelete(simple_struct_target.parent_spec.property_name)
            )
            continue
        target = resource_ref_assignment_target(delete.property_name)
        if target is not None:
            resource_ref_parent_deletes[target.parent_spec.property_name] = (
                XmpGeneratedPropertyDelete(target.parent_spec.property_name)
            )
            continue
        event_target = resource_event_assignment_target(delete.property_name)
        if event_target is not None:
            resource_event_parent_deletes[event_target.parent_spec.property_name] = (
                XmpGeneratedPropertyDelete(event_target.parent_spec.property_name)
            )
            continue
        regular_deletes.append(delete)
    grouped_deletes = (
        tuple(job_ref_parent_deletes.values())
        + tuple(manifest_item_parent_deletes.values())
        + tuple(pantry_item_parent_deletes.values())
        + tuple(resource_ref_parent_deletes.values())
        + tuple(resource_event_parent_deletes.values())
        + tuple(simple_struct_parent_deletes.values())
        + tuple(regular_deletes)
    )
    for delete in grouped_deletes:
        capability = capabilities.get(delete.property_name)
        if capability is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    delete.property_name,
                    "unknown_property",
                    "Property is not present in the generated XMP write capability audit.",
                )
            )
            continue
        tag_lookup_diagnostic = tag_lookup_diagnostic_for_capability(capability, tag_lookup)
        if tag_lookup_diagnostic is not None:
            diagnostics.append(tag_lookup_diagnostic)
            continue
        spec = generated_property_spec(capability)
        if spec is None:
            diagnostics.append(unsupported_capability_diagnostic(capability))
            continue
        specs.append(spec)
        steps.append(XmpPropertyDelete(delete.property_name))
    return XmpPropertyWritePlan(
        steps=tuple(steps),
        evidence_ids=(GENERATED_PROPERTY_SOURCE, XMP_PROPERTY_WRITE_SOURCE),
        generated_diagnostics=tuple(diagnostics),
        generated_specs=tuple(specs),
    )


def generated_capabilities_by_property(
    capabilities_path: Path,
) -> dict[XmpWritableProperty, XmpGeneratedPropertyCapability]:
    payload = load_json_object(capabilities_path)
    capabilities: dict[XmpWritableProperty, XmpGeneratedPropertyCapability] = {}
    for item in json_array_value(payload, "capabilities"):
        if not isinstance(item, dict):
            continue
        capability = generated_capability_from_json(item)
        if capability is not None:
            capabilities[capability.property_name] = capability
    return capabilities


def generated_capability_from_json(item: JsonObject) -> XmpGeneratedPropertyCapability | None:
    property_name = json_string_value(item, "property_name")
    group = json_string_value(item, "group")
    namespace_prefix = json_string_value(item, "namespace")
    tag_id = json_string_value(item, "tag_id")
    tag_name = json_string_value(item, "tag_name")
    shape = json_string_value(item, "shape")
    modernization_strategy = json_string_value(item, "modernization_strategy")
    effective_writable = json_string_value(item, "effective_writable")
    if (
        property_name is None
        or group is None
        or namespace_prefix is None
        or tag_id is None
        or tag_name is None
        or shape is None
        or modernization_strategy is None
        or effective_writable is None
    ):
        return None
    list_kind = json_string_value(item, "list_kind")
    return XmpGeneratedPropertyCapability(
        property_name=property_name,
        group=group,
        namespace_prefix=namespace_prefix,
        tag_id=tag_id,
        tag_name=tag_name,
        shape=shape,
        modernization_strategy=modernization_strategy,
        list_kind=list_kind,
        effective_writable=effective_writable,
    )


def tag_lookup_diagnostic_for_capability(
    capability: XmpGeneratedPropertyCapability,
    tag_lookup: TagLookupRepository | None,
) -> XmpGeneratedPlanDiagnostic | None:
    if tag_lookup is None or not tag_lookup.has_data:
        return None
    for tag_name in tag_lookup_candidate_names(capability):
        if tag_lookup.exists(tag_name):
            return None
    return XmpGeneratedPlanDiagnostic(
        capability.property_name,
        "not_in_tag_lookup",
        "Property is in the XMP capability audit but not in the generated TagLookup index.",
    )


def tag_lookup_candidate_names(capability: XmpGeneratedPropertyCapability) -> tuple[str, ...]:
    property_leaf = capability.property_name.rsplit(":", 1)[-1]
    return (capability.tag_name, capability.tag_id, property_leaf)


def generated_property_spec(capability: XmpGeneratedPropertyCapability) -> XmpPropertySpec | None:
    job_ref_spec = generated_job_ref_property_spec(capability)
    if job_ref_spec is not None:
        return job_ref_spec
    resource_ref_spec = generated_resource_ref_property_spec(capability)
    if resource_ref_spec is not None:
        return resource_ref_spec
    manifest_item_spec = generated_manifest_item_property_spec(capability)
    if manifest_item_spec is not None:
        return manifest_item_spec
    pantry_item_spec = generated_pantry_item_property_spec(capability)
    if pantry_item_spec is not None:
        return pantry_item_spec
    resource_event_spec = generated_resource_event_property_spec(capability)
    if resource_event_spec is not None:
        return resource_event_spec
    simple_struct_spec = generated_simple_struct_property_spec(capability)
    if simple_struct_spec is not None:
        return simple_struct_spec
    if not generated_strategy_enabled(capability):
        return None
    namespace_uri = XMP_NAMESPACE_URIS.get(capability.namespace_prefix)
    if namespace_uri is None:
        return None
    value_shape = generated_value_shape(capability)
    if value_shape is None:
        return None
    return XmpPropertySpec(
        property_name=capability.property_name,
        namespace_prefix=capability.namespace_prefix,
        namespace_uri=namespace_uri,
        element_name=capability.tag_id,
        value_shape=value_shape,
        evidence_ids=(GENERATED_PROPERTY_SOURCE,),
        rdf_container=generated_rdf_container(capability),
    )


def generated_strategy_enabled(capability: XmpGeneratedPropertyCapability) -> bool:
    if capability.modernization_strategy in {
        "current_property_spec",
        "generated_simple_property_spec",
        "generated_list_property_spec",
        "generated_lang_alt_property_spec",
    }:
        return True
    return (
        capability.modernization_strategy == "custom_operation_adapter"
        and capability.shape == "scalar_date"
        and capability.effective_writable == "date"
    )


def generated_job_ref_property_spec(
    capability: XmpGeneratedPropertyCapability,
) -> XmpPropertySpec | None:
    parent_spec = job_ref_parent_spec_for_property(capability.property_name)
    if parent_spec is None:
        return None
    if capability.modernization_strategy not in {
        "current_property_spec",
        "generated_struct_adapter",
    }:
        return None
    if capability.shape != parent_spec.shape or capability.list_kind != parent_spec.list_kind:
        return None
    if capability.namespace_prefix != "xmpBJ":
        return None
    namespace_uri = XMP_NAMESPACE_URIS.get(capability.namespace_prefix)
    if namespace_uri is None:
        return None
    return XmpPropertySpec(
        property_name=capability.property_name,
        namespace_prefix=capability.namespace_prefix,
        namespace_uri=namespace_uri,
        element_name=capability.tag_id,
        value_shape="job_ref",
        evidence_ids=(GENERATED_PROPERTY_SOURCE,),
        rdf_container=parent_spec.list_kind,
    )


def generated_resource_ref_property_spec(
    capability: XmpGeneratedPropertyCapability,
) -> XmpPropertySpec | None:
    parent_spec = resource_ref_parent_spec_for_property(capability.property_name)
    if parent_spec is None:
        return None
    if capability.modernization_strategy != "generated_struct_adapter":
        return None
    if parent_spec.shape == "struct_list":
        if capability.shape != parent_spec.shape or capability.list_kind != parent_spec.list_kind:
            return None
    elif capability.shape != "struct":
        return None
    if capability.namespace_prefix != "xmpMM":
        return None
    namespace_uri = XMP_NAMESPACE_URIS.get(capability.namespace_prefix)
    if namespace_uri is None:
        return None
    return XmpPropertySpec(
        property_name=capability.property_name,
        namespace_prefix=capability.namespace_prefix,
        namespace_uri=namespace_uri,
        element_name=capability.tag_id,
        value_shape="resource_ref",
        evidence_ids=(GENERATED_PROPERTY_SOURCE,),
        rdf_container=parent_spec.list_kind,
    )


def generated_manifest_item_property_spec(
    capability: XmpGeneratedPropertyCapability,
) -> XmpPropertySpec | None:
    parent_spec = manifest_item_parent_spec_for_property(capability.property_name)
    if parent_spec is None:
        return None
    if capability.modernization_strategy != "generated_struct_adapter":
        return None
    if capability.shape != parent_spec.shape or capability.list_kind != parent_spec.list_kind:
        return None
    if capability.namespace_prefix != "xmpMM":
        return None
    namespace_uri = XMP_NAMESPACE_URIS.get(capability.namespace_prefix)
    if namespace_uri is None:
        return None
    return XmpPropertySpec(
        property_name=capability.property_name,
        namespace_prefix=capability.namespace_prefix,
        namespace_uri=namespace_uri,
        element_name=capability.tag_id,
        value_shape="manifest_item",
        evidence_ids=(GENERATED_PROPERTY_SOURCE,),
        rdf_container=parent_spec.list_kind,
    )


def generated_pantry_item_property_spec(
    capability: XmpGeneratedPropertyCapability,
) -> XmpPropertySpec | None:
    parent_spec = pantry_item_parent_spec_for_property(capability.property_name)
    if parent_spec is None:
        return None
    if capability.modernization_strategy != "generated_struct_adapter":
        return None
    if capability.shape != parent_spec.shape or capability.list_kind != parent_spec.list_kind:
        return None
    if capability.namespace_prefix != "xmpMM":
        return None
    namespace_uri = XMP_NAMESPACE_URIS.get(capability.namespace_prefix)
    if namespace_uri is None:
        return None
    return XmpPropertySpec(
        property_name=capability.property_name,
        namespace_prefix=capability.namespace_prefix,
        namespace_uri=namespace_uri,
        element_name=capability.tag_id,
        value_shape="pantry_item",
        evidence_ids=(GENERATED_PROPERTY_SOURCE,),
        rdf_container=parent_spec.list_kind,
    )


def generated_resource_event_property_spec(
    capability: XmpGeneratedPropertyCapability,
) -> XmpPropertySpec | None:
    parent_spec = resource_event_parent_spec_for_property(capability.property_name)
    if parent_spec is None:
        return None
    if capability.modernization_strategy != "generated_struct_adapter":
        return None
    if capability.shape != parent_spec.shape or capability.list_kind != parent_spec.list_kind:
        return None
    if capability.namespace_prefix != "xmpMM":
        return None
    namespace_uri = XMP_NAMESPACE_URIS.get(capability.namespace_prefix)
    if namespace_uri is None:
        return None
    return XmpPropertySpec(
        property_name=capability.property_name,
        namespace_prefix=capability.namespace_prefix,
        namespace_uri=namespace_uri,
        element_name=capability.tag_id,
        value_shape="resource_event",
        evidence_ids=(GENERATED_PROPERTY_SOURCE,),
        rdf_container=parent_spec.list_kind,
    )


def generated_simple_struct_property_spec(
    capability: XmpGeneratedPropertyCapability,
) -> XmpPropertySpec | None:
    parent_spec = simple_struct_parent_spec_for_property(capability.property_name)
    if parent_spec is None:
        return None
    if capability.modernization_strategy != "generated_struct_adapter":
        return None
    if parent_spec.shape == "struct_list":
        if capability.shape != parent_spec.shape or capability.list_kind != parent_spec.list_kind:
            return None
    elif capability.shape != "struct":
        return None
    if capability.namespace_prefix != parent_spec.namespace_prefix:
        return None
    namespace_uri = XMP_NAMESPACE_URIS.get(capability.namespace_prefix)
    if namespace_uri is None:
        return None
    return XmpPropertySpec(
        property_name=capability.property_name,
        namespace_prefix=capability.namespace_prefix,
        namespace_uri=namespace_uri,
        element_name=capability.tag_id,
        value_shape="simple_struct",
        evidence_ids=(GENERATED_PROPERTY_SOURCE,),
        rdf_container=parent_spec.list_kind,
    )


def generated_value_shape(
    capability: XmpGeneratedPropertyCapability,
) -> XmpPropertyValueShape | None:
    if capability.shape == "scalar_boolean":
        return "boolean"
    if capability.shape == "scalar_date":
        return "date"
    if capability.shape == "scalar_numeric":
        return "numeric"
    if capability.shape == "scalar_text":
        return "simple_text"
    if capability.shape == "list_text":
        container = generated_rdf_container(capability)
        if container == "Bag":
            return "bag_text"
        if container == "Seq":
            return "seq_text"
        if container == "Alt":
            return "alt_text"
    if capability.shape == "list_typed":
        if generated_numeric_writable(capability.effective_writable) is not None:
            return "numeric"
    if capability.shape == "lang_alt":
        return "alt_text"
    return None


def generated_rdf_container(
    capability: XmpGeneratedPropertyCapability,
) -> XmpRdfContainer | None:
    if capability.list_kind == "Bag":
        return "Bag"
    if capability.list_kind == "Seq":
        return "Seq"
    if capability.list_kind == "Alt":
        return "Alt"
    if capability.shape == "lang_alt":
        return "Alt"
    return None


def unsupported_capability_diagnostic(
    capability: XmpGeneratedPropertyCapability,
) -> XmpGeneratedPlanDiagnostic:
    if capability.namespace_prefix not in XMP_NAMESPACE_URIS:
        return XmpGeneratedPlanDiagnostic(
            capability.property_name,
            "unsupported_namespace",
            f"Namespace prefix {capability.namespace_prefix} is not mapped to an XMP URI yet.",
        )
    return XmpGeneratedPlanDiagnostic(
        capability.property_name,
        "unsupported_strategy",
        f"Strategy {capability.modernization_strategy} is not enabled for generated writes.",
    )


def validate_generated_property_values(
    property_name: XmpWritableProperty,
    spec: XmpPropertySpec,
    capability: XmpGeneratedPropertyCapability,
    values: list[str],
) -> XmpGeneratedValueValidation:
    if spec.value_shape == "date":
        return validate_generated_date_values(property_name, values)
    if spec.value_shape != "numeric":
        return XmpGeneratedValueValidation(tuple(values))
    writable = generated_numeric_writable(capability.effective_writable)
    if writable is None:
        return XmpGeneratedValueValidation(
            (),
            (
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "invalid_value",
                    f"Writable type {capability.effective_writable} is not a numeric XMP type.",
                ),
            ),
        )
    normalized_values: list[str] = []
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    for value in values:
        normalized_value = normalize_xmp_numeric_value(value, writable)
        if normalized_value is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "invalid_value",
                    f"Value {value!r} is not valid for XMP {writable} writes.",
                )
            )
            continue
        normalized_values.append(normalized_value)
    return XmpGeneratedValueValidation(tuple(normalized_values), tuple(diagnostics))


def validate_generated_date_values(
    property_name: XmpWritableProperty,
    values: list[str],
) -> XmpGeneratedValueValidation:
    normalized_values: list[str] = []
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    for value in values:
        normalized_value = normalize_xmp_date_value(value)
        if normalized_value is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "invalid_value",
                    (
                        f"Value {value!r} is not valid for XMP date writes. "
                        "Use YYYY:mm:dd HH:MM:SS[.ss][+/-HH:MM|Z]."
                    ),
                )
            )
            continue
        normalized_values.append(normalized_value)
    return XmpGeneratedValueValidation(tuple(normalized_values), tuple(diagnostics))


def validate_job_ref_property_values(
    parent_property: XmpWritableProperty,
    assignments: list[XmpGeneratedPropertyAssignment],
) -> XmpGeneratedJobRefValidation:
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    values: list[XmpJobRefFieldValue] = []
    seen_fields: set[XmpJobRefFieldName] = set()
    for assignment in assignments:
        if assignment.language_code is not None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "unsupported_language",
                    "Language-specific assignments are not valid for JobRef fields.",
                )
            )
            continue
        target = job_ref_assignment_target(assignment.property_name)
        if target is None or target.parent_spec.property_name != parent_property:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "unknown_property",
                    "Assignment is not a supported generated JobRef field.",
                )
            )
            continue
        if target.field_spec.field_name in seen_fields:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "duplicate_struct_field",
                    f"JobRef field {target.field_spec.field_name} is assigned more than once.",
                )
            )
            continue
        seen_fields.add(target.field_spec.field_name)
        values.append(XmpJobRefFieldValue(target.field_spec.field_name, assignment.value))
    return XmpGeneratedJobRefValidation(tuple(values), tuple(diagnostics))


def validate_resource_ref_property_values(
    parent_property: XmpWritableProperty,
    assignments: list[XmpGeneratedPropertyAssignment],
) -> XmpGeneratedResourceRefValidation:
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    values: list[XmpResourceRefFieldValue] = []
    seen_fields: set[XmpResourceRefFieldName] = set()
    for assignment in assignments:
        if assignment.language_code is not None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "unsupported_language",
                    "Language-specific assignments are not valid for ResourceRef fields.",
                )
            )
            continue
        target = resource_ref_assignment_target(assignment.property_name)
        if target is None or target.parent_spec.property_name != parent_property:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "unknown_property",
                    "Assignment is not a supported generated ResourceRef field.",
                )
            )
            continue
        if target.field_spec.field_name in seen_fields:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "duplicate_struct_field",
                    f"ResourceRef field {target.field_spec.field_name} is assigned more than once.",
                )
            )
            continue
        normalized_value = assignment.value
        if target.field_spec.date_value:
            maybe_date = normalize_xmp_date_value(assignment.value)
            if maybe_date is None:
                diagnostics.append(
                    XmpGeneratedPlanDiagnostic(
                        assignment.property_name,
                        "invalid_value",
                        "ResourceRef lastModifyDate requires a valid XMP date value.",
                    )
                )
                continue
            normalized_value = maybe_date
        seen_fields.add(target.field_spec.field_name)
        values.append(XmpResourceRefFieldValue(target.field_spec.field_name, normalized_value))
    return XmpGeneratedResourceRefValidation(tuple(values), tuple(diagnostics))


def validate_manifest_item_property_values(
    parent_property: XmpWritableProperty,
    assignments: list[XmpGeneratedPropertyAssignment],
) -> XmpGeneratedManifestItemValidation:
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    values: list[XmpManifestItemFieldValue] = []
    seen_fields: set[str] = set()
    for assignment in assignments:
        if assignment.language_code is not None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "unsupported_language",
                    "Language-specific assignments are not valid for ManifestItem fields.",
                )
            )
            continue
        target = manifest_item_assignment_target(assignment.property_name)
        if target is None or target.parent_spec.property_name != parent_property:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "unknown_property",
                    "Assignment is not a supported generated ManifestItem field.",
                )
            )
            continue
        field_key = manifest_item_field_key(target)
        if field_key in seen_fields:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "duplicate_struct_field",
                    f"ManifestItem field {field_key} is assigned more than once.",
                )
            )
            continue
        normalized_value = assignment.value
        if target.simple_field_spec is not None:
            if target.simple_field_spec.numeric_value:
                maybe_number = normalize_xmp_numeric_value(assignment.value, "real")
                if maybe_number is None:
                    diagnostics.append(
                        XmpGeneratedPlanDiagnostic(
                            assignment.property_name,
                            "invalid_value",
                            "ManifestItem placed resolution requires a valid XMP real value.",
                        )
                    )
                    continue
                normalized_value = maybe_number
            seen_fields.add(field_key)
            values.append(
                XmpManifestItemSimpleFieldValue(
                    target.simple_field_spec.field_name,
                    normalized_value,
                )
            )
            continue
        if target.reference_field_spec is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "unknown_property",
                    "Assignment did not resolve to a ManifestItem field.",
                )
            )
            continue
        if target.reference_field_spec.date_value:
            maybe_date = normalize_xmp_date_value(assignment.value)
            if maybe_date is None:
                diagnostics.append(
                    XmpGeneratedPlanDiagnostic(
                        assignment.property_name,
                        "invalid_value",
                        "ManifestItem reference lastModifyDate requires a valid XMP date value.",
                    )
                )
                continue
            normalized_value = maybe_date
        seen_fields.add(field_key)
        values.append(
            XmpManifestItemReferenceFieldValue(
                target.reference_field_spec.field_name,
                normalized_value,
            )
        )
    return XmpGeneratedManifestItemValidation(tuple(values), tuple(diagnostics))


def manifest_item_field_key(target: XmpManifestItemAssignmentTarget) -> str:
    if target.simple_field_spec is not None:
        return target.simple_field_spec.field_name
    if target.reference_field_spec is not None:
        return f"reference.{target.reference_field_spec.field_name}"
    return "unknown"


def validate_pantry_item_property_values(
    parent_property: XmpWritableProperty,
    assignments: list[XmpGeneratedPropertyAssignment],
) -> XmpGeneratedPantryItemValidation:
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    values: list[XmpPantryItemFieldValue] = []
    seen_fields: set[XmpPantryItemFieldName] = set()
    for assignment in assignments:
        if assignment.language_code is not None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "unsupported_language",
                    "Language-specific assignments are not valid for PantryItem fields.",
                )
            )
            continue
        target = pantry_item_assignment_target(assignment.property_name)
        if target is None or target.parent_spec.property_name != parent_property:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "unknown_property",
                    "Assignment is not a supported generated PantryItem field.",
                )
            )
            continue
        if target.field_spec.field_name in seen_fields:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "duplicate_struct_field",
                    f"PantryItem field {target.field_spec.field_name} is assigned more than once.",
                )
            )
            continue
        seen_fields.add(target.field_spec.field_name)
        values.append(XmpPantryItemFieldValue(target.field_spec.field_name, assignment.value))
    return XmpGeneratedPantryItemValidation(tuple(values), tuple(diagnostics))


def validate_resource_event_property_values(
    parent_property: XmpWritableProperty,
    assignments: list[XmpGeneratedPropertyAssignment],
) -> XmpGeneratedResourceEventValidation:
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    values: list[XmpResourceEventFieldValue] = []
    seen_fields: set[XmpResourceEventFieldName] = set()
    for assignment in assignments:
        if assignment.language_code is not None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "unsupported_language",
                    "Language-specific assignments are not valid for ResourceEvent fields.",
                )
            )
            continue
        target = resource_event_assignment_target(assignment.property_name)
        if target is None or target.parent_spec.property_name != parent_property:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "unknown_property",
                    "Assignment is not a supported generated ResourceEvent field.",
                )
            )
            continue
        if target.field_spec.field_name in seen_fields:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "duplicate_struct_field",
                    (
                        f"ResourceEvent field {target.field_spec.field_name} is assigned "
                        "more than once."
                    ),
                )
            )
            continue
        normalized_value = assignment.value
        if target.field_spec.date_value:
            maybe_date = normalize_xmp_date_value(assignment.value)
            if maybe_date is None:
                diagnostics.append(
                    XmpGeneratedPlanDiagnostic(
                        assignment.property_name,
                        "invalid_value",
                        "ResourceEvent when requires a valid XMP date value.",
                    )
                )
                continue
            normalized_value = maybe_date
        seen_fields.add(target.field_spec.field_name)
        values.append(XmpResourceEventFieldValue(target.field_spec.field_name, normalized_value))
    return XmpGeneratedResourceEventValidation(tuple(values), tuple(diagnostics))


def validate_simple_struct_property_values(
    parent_property: XmpWritableProperty,
    assignments: list[XmpGeneratedPropertyAssignment],
) -> XmpGeneratedSimpleStructValidation:
    parent_spec = simple_struct_parent_spec_for_property(parent_property)
    if parent_spec is None:
        return XmpGeneratedSimpleStructValidation(
            XmpSimpleStructParentSpec(
                parent_name="",
                property_name=parent_property,
                element_name="",
                group="",
                namespace_prefix="",
                struct_namespace_prefix="",
                struct_namespace_uri="",
                shape="struct",
            ),
            (),
            (),
            (
                XmpGeneratedPlanDiagnostic(
                    parent_property,
                    "unknown_property",
                    "Simple struct parent property is not supported.",
                ),
            ),
        )
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    values: list[XmpSimpleStructFieldValue] = []
    item_groups: list[list[XmpSimpleStructFieldValue]] = []
    seen_fields: set[tuple[str | None, str]] = set()
    struct_list_field_counts: dict[tuple[str | None, str], int] = {}
    for assignment in assignments:
        if assignment.language_code is not None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "unsupported_language",
                    "Language-specific assignments are not valid for simple struct fields.",
                )
            )
            continue
        target = simple_struct_assignment_target(assignment.property_name)
        if target is None or target.parent_spec.property_name != parent_property:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "unknown_property",
                    "Assignment is not a supported generated simple struct field.",
                )
            )
            continue
        field_key = (target.field_spec.nested_field_name, target.field_spec.field_name)
        if parent_spec.shape != "struct_list" and field_key in seen_fields:
            if target.field_spec.field_list_kind is None:
                diagnostics.append(
                    XmpGeneratedPlanDiagnostic(
                        assignment.property_name,
                        "duplicate_struct_field",
                        (
                            f"Simple struct field {target.field_spec.field_name} is assigned "
                            "more than once."
                        ),
                    )
                )
                continue
        normalized_value = simple_struct_field_value_or_none(
            target.field_spec,
            assignment.value,
        )
        if normalized_value is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    assignment.property_name,
                    "invalid_value",
                    (
                        f"Value {assignment.value!r} is not valid for XMP "
                        f"{target.field_spec.value_kind} struct field writes."
                    ),
                )
            )
            continue
        if target.field_spec.field_list_kind is None:
            seen_fields.add(field_key)
        field_value = XmpSimpleStructFieldValue(target.field_spec, normalized_value)
        values.append(field_value)
        if parent_spec.shape != "struct_list":
            continue
        item_index = simple_struct_list_item_index(
            struct_list_field_counts,
            field_key,
            target.field_spec,
        )
        while len(item_groups) <= item_index:
            item_groups.append([])
        item_groups[item_index].append(field_value)
    return XmpGeneratedSimpleStructValidation(
        parent_spec,
        tuple(values),
        tuple(tuple(item_group) for item_group in item_groups),
        tuple(diagnostics),
    )


def simple_struct_list_item_index(
    field_counts: dict[tuple[str | None, str], int],
    field_key: tuple[str | None, str],
    field_spec: XmpSimpleStructFieldSpec,
) -> int:
    if field_spec.field_list_kind is not None:
        return 0
    item_index = field_counts.get(field_key, 0)
    field_counts[field_key] = item_index + 1
    return item_index


def simple_struct_field_value_or_none(
    field_spec: XmpSimpleStructFieldSpec,
    value: str,
) -> str | None:
    if field_spec.value_kind in {"text", "lang_alt"}:
        return value
    if field_spec.value_kind == "date":
        return normalize_xmp_date_value(value)
    if field_spec.value_kind == "boolean":
        bool_value = xmp_bool_or_none(value)
        if bool_value is None:
            return None
        return "True" if bool_value else "False"
    if field_spec.value_kind == "integer":
        return normalize_xmp_numeric_value(value, "integer")
    if field_spec.value_kind == "rational":
        return normalize_xmp_numeric_value(value, "rational")
    if field_spec.value_kind == "real":
        return normalize_xmp_numeric_value(value, "real")
    return None


def simple_struct_parent_spec_for_property(
    property_name: XmpWritableProperty,
) -> XmpSimpleStructParentSpec | None:
    return xmp_struct_parent_spec_for_property(property_name)


def simple_struct_assignment_target(
    property_name: XmpWritableProperty,
) -> XmpSimpleStructAssignmentTarget | None:
    return xmp_struct_assignment_target(property_name)


def unsupported_language_diagnostics(
    property_name: XmpWritableProperty,
    assignments: list[XmpGeneratedPropertyAssignment],
) -> tuple[XmpGeneratedPlanDiagnostic, ...]:
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    for assignment in assignments:
        if assignment.language_code is None:
            continue
        diagnostics.append(
            XmpGeneratedPlanDiagnostic(
                property_name,
                "unsupported_language",
                "Language-specific assignments are only valid for generated lang-alt properties.",
            )
        )
    return tuple(diagnostics)


def validate_lang_alt_property_values(
    property_name: XmpWritableProperty,
    assignments: list[XmpGeneratedPropertyAssignment],
) -> XmpGeneratedLangAltValidation:
    diagnostics: list[XmpGeneratedPlanDiagnostic] = []
    values: list[XmpLocalizedTextValue] = []
    seen_language_keys: set[str] = set()
    for assignment in assignments:
        language_code = normalized_xmp_language_code(assignment.language_code or "x-default")
        if language_code is None:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "invalid_value",
                    f"Language code {assignment.language_code!r} is not valid for XMP lang-alt.",
                )
            )
            continue
        language_key = language_code.lower()
        if language_key in seen_language_keys:
            diagnostics.append(
                XmpGeneratedPlanDiagnostic(
                    property_name,
                    "duplicate_language",
                    f"Language {language_code} is assigned more than once.",
                )
            )
            continue
        seen_language_keys.add(language_key)
        values.append(XmpLocalizedTextValue(language_code, assignment.value))
    return XmpGeneratedLangAltValidation(order_lang_alt_values(tuple(values)), tuple(diagnostics))


def normalized_xmp_language_code(value: str) -> XmpLanguageCode | None:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.lower() == "x-default":
        return "x-default"
    parts = stripped.split("-")
    if not valid_language_subtags(parts):
        return None
    normalized_parts: list[str] = []
    for index, part in enumerate(parts):
        if index == 0:
            normalized_parts.append(part.lower())
        elif len(part) == 2 and part.isalpha():
            normalized_parts.append(part.upper())
        elif len(part) == 4 and part.isalpha():
            normalized_parts.append(part.title())
        else:
            normalized_parts.append(part.lower())
    return "-".join(normalized_parts)


def valid_language_subtags(parts: list[str]) -> bool:
    if not parts:
        return False
    for index, part in enumerate(parts):
        if not part or len(part) > 8 or not part.isalnum():
            return False
        if index == 0 and not part.isalpha():
            return False
    return True


def order_lang_alt_values(
    values: tuple[XmpLocalizedTextValue, ...],
) -> tuple[XmpLocalizedTextValue, ...]:
    default_values: list[XmpLocalizedTextValue] = []
    localized_values: list[XmpLocalizedTextValue] = []
    for value in values:
        if value.language_code == "x-default":
            default_values.append(value)
        else:
            localized_values.append(value)
    return tuple(default_values + localized_values)


def generated_numeric_writable(effective_writable: str) -> XmpNumericWritable | None:
    if effective_writable == "integer":
        return "integer"
    if effective_writable == "real":
        return "real"
    if effective_writable == "rational":
        return "rational"
    return None


def normalize_xmp_numeric_value(value: str, writable: XmpNumericWritable) -> str | None:
    stripped = value.strip()
    if not stripped:
        return None
    if writable == "integer":
        return normalize_decimal_integer(stripped)
    if writable == "real":
        return stripped if finite_float_text(stripped) else None
    if "/" in stripped:
        return stripped if valid_rational_text(stripped) else None
    return stripped if finite_float_text(stripped) else None


def normalize_xmp_date_value(value: str) -> str | None:
    stripped = value.strip()
    if not stripped:
        return None
    date_time_value = normalize_xmp_date_time_value(stripped)
    if date_time_value is not None:
        return date_time_value
    date_value = normalize_xmp_date_only_value(stripped)
    if date_value is not None:
        return date_value
    return normalize_xmp_time_only_value(stripped)


def normalize_xmp_date_time_value(value: str) -> str | None:
    if "T" in value:
        date_text, time_text = value.split("T", 1)
    elif " " in value:
        date_text, time_text = value.split(" ", 1)
    else:
        return None
    normalized_date = normalize_xmp_date_only_value(date_text)
    normalized_time = normalize_xmp_time_only_value(time_text)
    if normalized_date is None or normalized_time is None:
        return None
    return f"{normalized_date}T{normalized_time}"


def normalize_xmp_date_only_value(value: str) -> str | None:
    separator = ":" if ":" in value else "-"
    parts = value.split(separator)
    if len(parts) > 3:
        return None
    if len(parts[0]) != 4 or not parts[0].isdecimal():
        return None
    normalized_parts = [parts[0]]
    for part in parts[1:]:
        if len(part) != 2 or not part.isdecimal():
            return None
        normalized_parts.append(part)
    return "-".join(normalized_parts)


def normalize_xmp_time_only_value(value: str) -> str | None:
    time_text, timezone_text = split_xmp_timezone(value)
    if timezone_text is None:
        return None
    time_parts = time_text.split(":")
    if len(time_parts) not in {2, 3}:
        return None
    if not all(len(part) == 2 and part.isdecimal() for part in time_parts[:2]):
        return None
    if len(time_parts) == 3 and not valid_xmp_second_text(time_parts[2]):
        return None
    return f"{time_text}{timezone_text}"


def split_xmp_timezone(value: str) -> tuple[str, str | None]:
    if value.endswith("Z"):
        return value[:-1], "Z"
    if len(value) >= 6 and value[-6] in {"+", "-"}:
        timezone_text = value[-6:]
        if valid_xmp_timezone_offset(timezone_text):
            return value[:-6], timezone_text
        return value, None
    return value, ""


def valid_xmp_timezone_offset(value: str) -> bool:
    return (
        len(value) == 6
        and value[0] in {"+", "-"}
        and value[1:3].isdecimal()
        and value[3] == ":"
        and value[4:6].isdecimal()
    )


def valid_xmp_second_text(value: str) -> bool:
    seconds, separator, fraction = value.partition(".")
    if len(seconds) != 2 or not seconds.isdecimal():
        return False
    if not separator:
        return True
    return fraction.isdecimal()


def normalize_decimal_integer(value: str) -> str | None:
    unsigned = value[1:] if value.startswith(("+", "-")) else value
    if not unsigned.isdecimal():
        return None
    return str(int(value))


def finite_float_text(value: str) -> bool:
    try:
        numeric = float(value)
    except ValueError:
        return False
    return math.isfinite(numeric)


def valid_rational_text(value: str) -> bool:
    numerator, separator, denominator = value.partition("/")
    if separator != "/":
        return False
    normalized_numerator = normalize_decimal_integer(numerator.strip())
    normalized_denominator = normalize_decimal_integer(denominator.strip())
    if normalized_numerator is None or normalized_denominator is None:
        return False
    return int(normalized_denominator) != 0


def xmp_marked_bool(value: str) -> bool:
    bool_value = xmp_bool_or_none(value)
    if bool_value is not None:
        return bool_value
    raise ValueError("--xmprights-marked must be true or false.")


def xmp_bool_or_none(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None
