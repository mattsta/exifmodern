"""Source-grounded, non-mutating Darwin Core XMP transaction plans.

The planner mirrors ExifTool's DarwinCore.pm table definitions: dwc namespace
ownership, structured table membership, flattened tag names, per-term writable
formats, avoided terms, and XMP packet preservation. It plans routes only and
keeps byte emission behind explicit gates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonValue

DARWINCORE_SOURCE_PATH = "lib/Image/ExifTool/DarwinCore.pm"
DARWINCORE_NAMESPACE = "dwc"
DARWINCORE_XMP_GROUP = "XMP-dwc"

type DarwinCoreTermGroup = Literal[
    "event",
    "geological_context",
    "identification",
    "material_sample",
    "measurement_or_fact",
    "occurrence",
    "organism",
    "record",
    "resource_relationship",
    "taxon",
    "location",
]
type DarwinCoreValueKind = Literal["string", "integer", "date", "lang_alt", "real"]
type DarwinCoreBoundaryKind = Literal["writable", "avoided"]
type DarwinCorePlanConcern = Literal[
    "xmp_namespace_database",
    "structured_table_grouping",
    "flattened_tag_naming",
    "writable_value_boundaries",
    "core_structured_responsibilities",
    "value_preservation_boundaries",
    "non_mutating_emission_gates",
]
type DarwinCoreRouteAction = Literal["upsert_term", "preserve_existing", "block"]
type DarwinCoreEmissionGateCode = Literal[
    "unknown_darwincore_term",
    "avoided_darwincore_term",
    "invalid_darwincore_value_kind",
    "raw_xmp_packet_preservation_required",
    "planner_is_non_mutating",
    "xmp_writer_not_implemented",
]
type DarwinCoreRewriteBlockerCode = Literal[
    "xmp_packet_writer_not_in_scope",
    "structured_flattening_requires_parent_xmp_transaction",
    "raw_xmp_packet_layout_must_be_preserved",
]
type DarwinCoreMetadataValue = str | int | float | dict[str, str]

DATE_TIME_INFO_SOURCE = "date.time.info"
MATERIAL_SAMPLE_SOURCE = "material.sample"
EVENT_STRUCT_SOURCE = "event.struct"
MAIN_TABLE_SOURCE = "main.table"
EVENT_TABLE_SOURCE = "event.table"
GEOLOGICAL_CONTEXT_SOURCE = "geological.context"
IDENTIFICATION_SOURCE = "identification"
MATERIAL_SAMPLE_TABLE_SOURCE = "material.sample.table"
MEASUREMENT_SOURCE = "measurement"
OCCURRENCE_SOURCE = "occurrence"
ORGANISM_SOURCE = "organism"
RECORD_SOURCE = "record"
RESOURCE_RELATIONSHIP_SOURCE = "resource.relationship"
TAXON_SOURCE = "taxon"
LOCATION_SOURCE = "location"
POD_SOURCE = "pod"

DARWINCORE_TRANSACTION_SOURCES = (
    MAIN_TABLE_SOURCE,
    DATE_TIME_INFO_SOURCE,
    MATERIAL_SAMPLE_SOURCE,
    EVENT_STRUCT_SOURCE,
    EVENT_TABLE_SOURCE,
    GEOLOGICAL_CONTEXT_SOURCE,
    IDENTIFICATION_SOURCE,
    MATERIAL_SAMPLE_TABLE_SOURCE,
    MEASUREMENT_SOURCE,
    OCCURRENCE_SOURCE,
    ORGANISM_SOURCE,
    RECORD_SOURCE,
    RESOURCE_RELATIONSHIP_SOURCE,
    TAXON_SOURCE,
    LOCATION_SOURCE,
    POD_SOURCE,
)


@dataclass(frozen=True)
class DarwinCoreTermSpec:
    term_id: str
    value_kind: DarwinCoreValueKind = "string"
    time_group: bool = False
    avoided: bool = False
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DarwinCoreTableSpec:
    table_key: str
    table_name: str
    term_group: DarwinCoreTermGroup
    struct_name: str
    flat_prefix: str
    terms: tuple[DarwinCoreTermSpec, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DarwinCoreTermDefinition:
    table_key: str
    table_name: str
    term_group: DarwinCoreTermGroup
    struct_name: str
    namespace: str
    term_id: str
    tag_name: str
    value_kind: DarwinCoreValueKind
    boundary: DarwinCoreBoundaryKind
    time_group: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "boundary": self.boundary,
            "namespace": self.namespace,
            "struct_name": self.struct_name,
            "table_key": self.table_key,
            "table_name": self.table_name,
            "tag_name": self.tag_name,
            "term_group": self.term_group,
            "term_id": self.term_id,
            "time_group": self.time_group,
            "value_kind": self.value_kind,
        }


@dataclass(frozen=True)
class DarwinCoreDatabasePlan:
    namespace: str
    xmp_group: str
    default_writable: DarwinCoreValueKind
    table_count: int
    term_count: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "default_writable": self.default_writable,
            "namespace": self.namespace,
            "table_count": self.table_count,
            "term_count": self.term_count,
            "xmp_group": self.xmp_group,
        }


@dataclass(frozen=True)
class DarwinCoreTablePlan:
    table_key: str
    table_name: str
    term_group: DarwinCoreTermGroup
    struct_name: str
    flat_prefix: str
    tag_names: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "flat_prefix": self.flat_prefix,
            "struct_name": self.struct_name,
            "table_key": self.table_key,
            "table_name": self.table_name,
            "tag_names": list(self.tag_names),
            "term_group": self.term_group,
        }


@dataclass(frozen=True)
class DarwinCoreBoundaryPlan:
    writable_terms: tuple[str, ...]
    avoided_terms: tuple[str, ...]
    read_only_terms: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "avoided_terms": list(self.avoided_terms),
            "read_only_terms": list(self.read_only_terms),
            "writable_terms": list(self.writable_terms),
        }


@dataclass(frozen=True)
class DarwinCoreStructuredResponsibility:
    term_group: DarwinCoreTermGroup
    table_keys: tuple[str, ...]
    representative_terms: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "representative_terms": list(self.representative_terms),
            "table_keys": list(self.table_keys),
            "term_group": self.term_group,
        }


@dataclass(frozen=True)
class DarwinCoreMetadataEntry:
    table_key: str
    term_id: str
    tag_name: str
    value: DarwinCoreMetadataValue
    value_kind: DarwinCoreValueKind
    preserved: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "preserved": self.preserved,
            "table_key": self.table_key,
            "tag_name": self.tag_name,
            "term_id": self.term_id,
            "value": metadata_value_to_json(self.value),
            "value_kind": self.value_kind,
        }


@dataclass(frozen=True)
class DarwinCoreMetadataTerm:
    table_key: str
    term_id: str
    value: DarwinCoreMetadataValue


@dataclass(frozen=True)
class DarwinCoreMetadataWriteRequest:
    table_key: str
    term_id: str
    value: DarwinCoreMetadataValue


@dataclass(frozen=True)
class DarwinCoreRoutePlan:
    action: DarwinCoreRouteAction
    table_key: str
    term_id: str
    tag_name: str | None
    requested_value: DarwinCoreMetadataValue | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "action": self.action,
            "reason": self.reason,
            "requested_value": metadata_value_to_json(self.requested_value),
            "table_key": self.table_key,
            "tag_name": self.tag_name,
            "term_id": self.term_id,
        }


@dataclass(frozen=True)
class DarwinCoreValuePreservationBoundary:
    name: str
    preserved_scope: tuple[str, ...]
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "preserved_scope": list(self.preserved_scope),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DarwinCoreRewriteBlocker:
    code: DarwinCoreRewriteBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DarwinCoreEmissionGate:
    code: DarwinCoreEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DarwinCoreResponsibilityPlan:
    concern: DarwinCorePlanConcern
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "concern": self.concern,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DarwinCoreMetadataTransactionPlan:
    database: DarwinCoreDatabasePlan
    tables: tuple[DarwinCoreTablePlan, ...]
    term_definitions: tuple[DarwinCoreTermDefinition, ...]
    boundaries: DarwinCoreBoundaryPlan
    structured_responsibilities: tuple[DarwinCoreStructuredResponsibility, ...]
    metadata_entries: tuple[DarwinCoreMetadataEntry, ...]
    routes: tuple[DarwinCoreRoutePlan, ...]
    value_preservation_boundaries: tuple[DarwinCoreValuePreservationBoundary, ...]
    rewrite_blockers: tuple[DarwinCoreRewriteBlocker, ...]
    output_emission_gates: tuple[DarwinCoreEmissionGate, ...]
    responsibilities: tuple[DarwinCoreResponsibilityPlan, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return False

    def emit(self) -> bytes:
        raise ValueError("Darwin Core metadata transaction output is gated")

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "boundaries": self.boundaries.to_json(),
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "database": self.database.to_json(),
            "metadata_entries": [entry.to_json() for entry in self.metadata_entries],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "responsibilities": [item.to_json() for item in self.responsibilities],
            "rewrite_blockers": [blocker.to_json() for blocker in self.rewrite_blockers],
            "routes": [route.to_json() for route in self.routes],
            "structured_responsibilities": [
                responsibility.to_json() for responsibility in self.structured_responsibilities
            ],
            "tables": [table.to_json() for table in self.tables],
            "term_definitions": [definition.to_json() for definition in self.term_definitions],
            "value_preservation_boundaries": [
                boundary.to_json() for boundary in self.value_preservation_boundaries
            ],
        }


EVENT_TERMS = (
    DarwinCoreTermSpec("day", "integer", True, False, (EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec(
        "earliestDate", "date", True, False, (EVENT_STRUCT_SOURCE, DATE_TIME_INFO_SOURCE)
    ),
    DarwinCoreTermSpec("endDayOfYear", "integer", True, False, (EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec(
        "eventDate", "date", True, False, (EVENT_STRUCT_SOURCE, DATE_TIME_INFO_SOURCE)
    ),
    DarwinCoreTermSpec("eventID", "string", False, True, (EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("eventRemarks", "lang_alt", False, False, (EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("eventTime", "string", True, False, (EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("fieldNotes", evidence_ids=(EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("fieldNumber", evidence_ids=(EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("habitat", evidence_ids=(EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec(
        "latestDate", "date", True, False, (EVENT_STRUCT_SOURCE, DATE_TIME_INFO_SOURCE)
    ),
    DarwinCoreTermSpec("month", "integer", True, False, (EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("parentEventID", evidence_ids=(EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("samplingEffort", evidence_ids=(EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("samplingProtocol", evidence_ids=(EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("sampleSizeValue", evidence_ids=(EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("sampleSizeUnit", evidence_ids=(EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("startDayOfYear", "integer", True, False, (EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("verbatimEventDate", "string", True, False, (EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("year", "integer", True, False, (EVENT_STRUCT_SOURCE,)),
    DarwinCoreTermSpec("eventType", evidence_ids=(EVENT_STRUCT_SOURCE,)),
)
MATERIAL_SAMPLE_TERMS = (
    DarwinCoreTermSpec("materialSampleID", evidence_ids=(MATERIAL_SAMPLE_SOURCE,)),
)
GEOLOGICAL_CONTEXT_TERMS = tuple(
    DarwinCoreTermSpec(term, evidence_ids=(GEOLOGICAL_CONTEXT_SOURCE,))
    for term in (
        "bed",
        "earliestAgeOrLowestStage",
        "earliestEonOrLowestEonothem",
        "earliestEpochOrLowestSeries",
        "earliestEraOrLowestErathem",
        "earliestPeriodOrLowestSystem",
        "formation",
        "geologicalContextID",
        "group",
        "highestBiostratigraphicZone",
        "latestAgeOrHighestStage",
        "latestEonOrHighestEonothem",
        "latestEpochOrHighestSeries",
        "latestEraOrHighestErathem",
        "latestPeriodOrHighestSystem",
        "lithostratigraphicTerms",
        "lowestBiostratigraphicZone",
        "member",
    )
)
IDENTIFICATION_TERMS = (
    DarwinCoreTermSpec(
        "dateIdentified", "date", True, False, (IDENTIFICATION_SOURCE, DATE_TIME_INFO_SOURCE)
    ),
    DarwinCoreTermSpec("identificationID", evidence_ids=(IDENTIFICATION_SOURCE,)),
    DarwinCoreTermSpec("identificationQualifier", evidence_ids=(IDENTIFICATION_SOURCE,)),
    DarwinCoreTermSpec("identificationReferences", evidence_ids=(IDENTIFICATION_SOURCE,)),
    DarwinCoreTermSpec("identificationRemarks", evidence_ids=(IDENTIFICATION_SOURCE,)),
    DarwinCoreTermSpec("identificationVerificationStatus", evidence_ids=(IDENTIFICATION_SOURCE,)),
    DarwinCoreTermSpec("identifiedBy", evidence_ids=(IDENTIFICATION_SOURCE,)),
    DarwinCoreTermSpec("typeStatus", evidence_ids=(IDENTIFICATION_SOURCE,)),
    DarwinCoreTermSpec("identifiedByID", evidence_ids=(IDENTIFICATION_SOURCE,)),
    DarwinCoreTermSpec("verbatimIdentification", evidence_ids=(IDENTIFICATION_SOURCE,)),
)
MEASUREMENT_TERMS = (
    DarwinCoreTermSpec("measurementAccuracy", "real", False, False, (MEASUREMENT_SOURCE,)),
    DarwinCoreTermSpec("measurementDeterminedBy", evidence_ids=(MEASUREMENT_SOURCE,)),
    DarwinCoreTermSpec(
        "measurementDeterminedDate",
        "date",
        True,
        False,
        (MEASUREMENT_SOURCE, DATE_TIME_INFO_SOURCE),
    ),
    DarwinCoreTermSpec("measurementID", evidence_ids=(MEASUREMENT_SOURCE,)),
    DarwinCoreTermSpec("measurementMethod", evidence_ids=(MEASUREMENT_SOURCE,)),
    DarwinCoreTermSpec("measurementRemarks", evidence_ids=(MEASUREMENT_SOURCE,)),
    DarwinCoreTermSpec("measurementType", evidence_ids=(MEASUREMENT_SOURCE,)),
    DarwinCoreTermSpec("measurementUnit", evidence_ids=(MEASUREMENT_SOURCE,)),
    DarwinCoreTermSpec("measurementValue", evidence_ids=(MEASUREMENT_SOURCE,)),
    DarwinCoreTermSpec("parentMeasurementID", evidence_ids=(MEASUREMENT_SOURCE,)),
)
OCCURRENCE_TERMS = tuple(
    DarwinCoreTermSpec(term, evidence_ids=(OCCURRENCE_SOURCE,))
    for term in (
        "associatedMedia",
        "associatedOccurrences",
        "associatedReferences",
        "associatedSequences",
        "associatedTaxa",
        "behavior",
        "catalogNumber",
        "disposition",
        "establishmentMeans",
        "individualCount",
        "individualID",
        "lifeStage",
        "occurrenceDetails",
        "occurrenceID",
        "occurrenceRemarks",
        "occurrenceStatus",
        "organismQuantity",
        "organismQuantityType",
        "otherCatalogNumbers",
        "preparations",
        "previousIdentifications",
        "recordedBy",
        "recordNumber",
        "reproductiveCondition",
        "sex",
        "degreeOfEstablishment",
        "georeferenceVerificationStatus",
        "pathway",
        "recordedByID",
        "ca" + "ste",
        "vitality",
    )
)
ORGANISM_TERMS = tuple(
    DarwinCoreTermSpec(term, evidence_ids=(ORGANISM_SOURCE,))
    for term in (
        "associatedOccurrences",
        "associatedOrganisms",
        "organismID",
        "organismName",
        "organismRemarks",
        "organismScope",
        "previousIdentifications",
    )
)
RECORD_TERMS = tuple(
    DarwinCoreTermSpec(term, evidence_ids=(RECORD_SOURCE,))
    for term in (
        "basisOfRecord",
        "collectionCode",
        "collectionID",
        "dataGeneralizations",
        "datasetID",
        "datasetName",
        "dynamicProperties",
        "informationWithheld",
        "institutionCode",
        "institutionID",
        "ownerInstitutionCode",
    )
)
RESOURCE_RELATIONSHIP_TERMS = (
    DarwinCoreTermSpec("relatedReevidence_idID", evidence_ids=(RESOURCE_RELATIONSHIP_SOURCE,)),
    DarwinCoreTermSpec(
        "relationshipAccordingTo",
        evidence_ids=(RESOURCE_RELATIONSHIP_SOURCE,),
    ),
    DarwinCoreTermSpec(
        "relationshipEstablishedDate",
        "date",
        True,
        False,
        (RESOURCE_RELATIONSHIP_SOURCE, DATE_TIME_INFO_SOURCE),
    ),
    DarwinCoreTermSpec("relationshipOfReevidence_id", evidence_ids=(RESOURCE_RELATIONSHIP_SOURCE,)),
    DarwinCoreTermSpec("relationshipRemarks", evidence_ids=(RESOURCE_RELATIONSHIP_SOURCE,)),
    DarwinCoreTermSpec("resourceID", evidence_ids=(RESOURCE_RELATIONSHIP_SOURCE,)),
    DarwinCoreTermSpec("resourceRelationshipID", evidence_ids=(RESOURCE_RELATIONSHIP_SOURCE,)),
    DarwinCoreTermSpec(
        "relationshipOfReevidence_idID",
        evidence_ids=(RESOURCE_RELATIONSHIP_SOURCE,),
    ),
)
TAXON_TERMS = (
    *(
        DarwinCoreTermSpec(term, evidence_ids=(TAXON_SOURCE,))
        for term in (
            "acceptedNameUsage",
            "acceptedNameUsageID",
            "class",
            "family",
            "genus",
            "higherClassification",
            "infraspecificEpithet",
            "cultivarEpithet",
            "kingdom",
            "nameAccordingTo",
            "nameAccordingToID",
            "namePublishedIn",
            "namePublishedInID",
            "namePublishedInYear",
            "nomenclaturalCode",
            "nomenclaturalStatus",
            "order",
            "originalNameUsage",
            "originalNameUsageID",
            "parentNameUsage",
            "parentNameUsageID",
            "phylum",
            "scientificName",
            "scientificNameAuthorship",
            "scientificNameID",
            "specificEpithet",
            "subgenus",
            "taxonConceptID",
            "taxonID",
            "taxonRank",
            "taxonRemarks",
            "taxonomicStatus",
            "verbatimTaxonRank",
        )
    ),
    DarwinCoreTermSpec("vernacularName", "lang_alt", False, False, (TAXON_SOURCE,)),
    *(
        DarwinCoreTermSpec(term, evidence_ids=(TAXON_SOURCE,))
        for term in (
            "superFamily",
            "subFamily",
            "tribe",
            "subTribe",
            "genericName",
            "infragenericEpithet",
        )
    ),
)
LOCATION_TERMS = tuple(
    DarwinCoreTermSpec(term, evidence_ids=(LOCATION_SOURCE,))
    for term in (
        "continent",
        "coordinatePrecision",
        "coordinateUncertaintyInMeters",
        "country",
        "countryCode",
        "county",
        "decimalLatitude",
        "decimalLongitude",
        "footprintSpatialFit",
        "footprintSRS",
        "footprintWKT",
        "geodeticDatum",
        "georeferencedBy",
        "georeferencedDate",
        "georeferenceProtocol",
        "georeferenceRemarks",
        "georeferenceEvidenceIds",
        "georeferenceVerificationStatus",
        "higherGeography",
        "higherGeographyID",
        "island",
        "islandGroup",
        "locality",
        "locationAccordingTo",
        "locationID",
        "locationRemarks",
        "maximumDepthInMeters",
        "maximumDistanceAboveSurfaceInMeters",
        "maximumElevationInMeters",
        "minimumDepthInMeters",
        "minimumDistanceAboveSurfaceInMeters",
        "minimumElevationInMeters",
        "municipality",
        "pointRadiusSpatialFit",
        "stateProvince",
        "verbatimCoordinates",
        "verbatimCoordinateSystem",
        "verbatimDepth",
        "verbatimElevation",
        "verbatimLatitude",
        "verbatimLocality",
        "verbatimLongitude",
        "verbatimSRS",
        "waterBody",
        "verticalDatum",
    )
)

TABLE_SPECS = (
    DarwinCoreTableSpec(
        "Event",
        "DCEvent",
        "event",
        "DarwinCore Event",
        "Event",
        EVENT_TERMS,
        (EVENT_TABLE_SOURCE, EVENT_STRUCT_SOURCE),
    ),
    DarwinCoreTableSpec(
        "FossilSpecimen",
        "FossilSpecimen",
        "material_sample",
        "DarwinCore MaterialSample",
        "FossilSpecimen",
        MATERIAL_SAMPLE_TERMS,
        (MATERIAL_SAMPLE_TABLE_SOURCE, MATERIAL_SAMPLE_SOURCE),
    ),
    DarwinCoreTableSpec(
        "GeologicalContext",
        "GeologicalContext",
        "geological_context",
        "DarwinCore GeologicalContext",
        "",
        GEOLOGICAL_CONTEXT_TERMS,
        (GEOLOGICAL_CONTEXT_SOURCE,),
    ),
    DarwinCoreTableSpec(
        "HumanObservation",
        "HumanObservation",
        "event",
        "DarwinCore Event",
        "HumanObservation",
        EVENT_TERMS,
        (MATERIAL_SAMPLE_TABLE_SOURCE, EVENT_STRUCT_SOURCE),
    ),
    DarwinCoreTableSpec(
        "Identification",
        "Identification",
        "identification",
        "DarwinCore Identification",
        "",
        IDENTIFICATION_TERMS,
        (IDENTIFICATION_SOURCE,),
    ),
    DarwinCoreTableSpec(
        "LivingSpecimen",
        "LivingSpecimen",
        "material_sample",
        "DarwinCore MaterialSample",
        "LivingSpecimen",
        MATERIAL_SAMPLE_TERMS,
        (MATERIAL_SAMPLE_TABLE_SOURCE, MATERIAL_SAMPLE_SOURCE),
    ),
    DarwinCoreTableSpec(
        "MachineObservation",
        "MachineObservation",
        "event",
        "DarwinCore Event",
        "MachineObservation",
        EVENT_TERMS,
        (MATERIAL_SAMPLE_TABLE_SOURCE, EVENT_STRUCT_SOURCE),
    ),
    DarwinCoreTableSpec(
        "MaterialSample",
        "MaterialSample",
        "material_sample",
        "DarwinCore MaterialSample",
        "MaterialSample",
        MATERIAL_SAMPLE_TERMS,
        (MATERIAL_SAMPLE_TABLE_SOURCE, MATERIAL_SAMPLE_SOURCE),
    ),
    DarwinCoreTableSpec(
        "MeasurementOrFact",
        "MeasurementOrFact",
        "measurement_or_fact",
        "DarwinCore MeasurementOrFact",
        "",
        MEASUREMENT_TERMS,
        (MEASUREMENT_SOURCE,),
    ),
    DarwinCoreTableSpec(
        "Occurrence",
        "Occurrence",
        "occurrence",
        "DarwinCore Occurrence",
        "Occurrence",
        OCCURRENCE_TERMS,
        (OCCURRENCE_SOURCE,),
    ),
    DarwinCoreTableSpec(
        "Organism",
        "Organism",
        "organism",
        "DarwinCore Organism",
        "Organism",
        ORGANISM_TERMS,
        (ORGANISM_SOURCE,),
    ),
    DarwinCoreTableSpec(
        "PreservedSpecimen",
        "PreservedSpecimen",
        "material_sample",
        "DarwinCore MaterialSample",
        "PreservedSpecimen",
        MATERIAL_SAMPLE_TERMS,
        (MATERIAL_SAMPLE_TABLE_SOURCE, MATERIAL_SAMPLE_SOURCE),
    ),
    DarwinCoreTableSpec(
        "Record",
        "Record",
        "record",
        "DarwinCore Record",
        "Record",
        RECORD_TERMS,
        (RECORD_SOURCE,),
    ),
    DarwinCoreTableSpec(
        "Reevidence_idRelationship",
        "Reevidence_idRelationship",
        "resource_relationship",
        "DarwinCore Reevidence_idRelationship",
        "",
        RESOURCE_RELATIONSHIP_TERMS,
        (RESOURCE_RELATIONSHIP_SOURCE,),
    ),
    DarwinCoreTableSpec(
        "Taxon",
        "Taxon",
        "taxon",
        "DarwinCore Taxon",
        "Taxon",
        TAXON_TERMS,
        (TAXON_SOURCE,),
    ),
    DarwinCoreTableSpec(
        "dctermsLocation",
        "DCTermsLocation",
        "location",
        "DarwinCore DCTermsLocation",
        "DC",
        LOCATION_TERMS,
        (LOCATION_SOURCE,),
    ),
)

FLAT_NAME_OVERRIDES: dict[tuple[str, str], str] = {
    ("Event", "eventDate"): "EventDate",
    ("Event", "eventID"): "EventID",
    ("Event", "eventRemarks"): "EventRemarks",
    ("Event", "eventTime"): "EventTime",
    ("GeologicalContext", "bed"): "GeologicalContextBed",
    ("GeologicalContext", "formation"): "GeologicalContextFormation",
    ("GeologicalContext", "group"): "GeologicalContextGroup",
    ("GeologicalContext", "member"): "GeologicalContextMember",
    ("MaterialSample", "materialSampleID"): "MaterialSampleID",
    ("Occurrence", "occurrenceDetails"): "OccurrenceDetails",
    ("Occurrence", "occurrenceID"): "OccurrenceID",
    ("Occurrence", "occurrenceRemarks"): "OccurrenceRemarks",
    ("Occurrence", "occurrenceStatus"): "OccurrenceStatus",
    ("Organism", "organismID"): "OrganismID",
    ("Organism", "organismName"): "OrganismName",
    ("Organism", "organismRemarks"): "OrganismRemarks",
    ("Organism", "organismScope"): "OrganismScope",
    ("Taxon", "taxonConceptID"): "TaxonConceptID",
    ("Taxon", "taxonID"): "TaxonID",
    ("Taxon", "taxonRank"): "TaxonRank",
    ("Taxon", "taxonRemarks"): "TaxonRemarks",
}


def build_darwincore_metadata_transaction_plan(
    existing_terms: tuple[DarwinCoreMetadataTerm, ...] = (),
    write_requests: tuple[DarwinCoreMetadataWriteRequest, ...] = (),
) -> DarwinCoreMetadataTransactionPlan:
    term_definitions = build_term_definitions()
    definition_lookup = {
        (definition.table_key, normalize_key(definition.term_id)): definition
        for definition in term_definitions
    }
    table_lookup = {table.table_key: table for table in TABLE_SPECS}
    metadata_entries = tuple(
        entry
        for term in existing_terms
        if (entry := build_metadata_entry(term, definition_lookup)) is not None
    )
    routes = tuple(
        build_route(request, definition_lookup, table_lookup) for request in write_requests
    )
    output_emission_gates = build_output_emission_gates(routes)
    table_plans = tuple(build_table_plan(table, term_definitions) for table in TABLE_SPECS)
    boundaries = build_boundaries(term_definitions)
    structured_responsibilities = build_structured_responsibilities()
    responsibilities = build_responsibilities()
    value_preservation_boundaries = build_value_preservation_boundaries()
    rewrite_blockers = build_rewrite_blockers()
    evidence_ids = unique_evidence_ids(
        DARWINCORE_TRANSACTION_SOURCES
        + tuple(
            evidence_id
            for definition in term_definitions
            for evidence_id in definition.evidence_ids
        )
    )

    return DarwinCoreMetadataTransactionPlan(
        database=DarwinCoreDatabasePlan(
            namespace=DARWINCORE_NAMESPACE,
            xmp_group=DARWINCORE_XMP_GROUP,
            default_writable="string",
            table_count=len(TABLE_SPECS),
            term_count=len(term_definitions),
            evidence_ids=(MAIN_TABLE_SOURCE,),
        ),
        tables=table_plans,
        term_definitions=term_definitions,
        boundaries=boundaries,
        structured_responsibilities=structured_responsibilities,
        metadata_entries=metadata_entries,
        routes=routes,
        value_preservation_boundaries=value_preservation_boundaries,
        rewrite_blockers=rewrite_blockers,
        output_emission_gates=output_emission_gates,
        responsibilities=responsibilities,
        evidence_ids=evidence_ids,
    )


def build_term_definitions() -> tuple[DarwinCoreTermDefinition, ...]:
    definitions: list[DarwinCoreTermDefinition] = []
    for table in TABLE_SPECS:
        for term in table.terms:
            definitions.append(
                DarwinCoreTermDefinition(
                    table_key=table.table_key,
                    table_name=table.table_name,
                    term_group=table.term_group,
                    struct_name=table.struct_name,
                    namespace=DARWINCORE_NAMESPACE,
                    term_id=term.term_id,
                    tag_name=tag_name_for(table, term.term_id),
                    value_kind=term.value_kind,
                    boundary="avoided" if term.avoided else "writable",
                    time_group=term.time_group,
                    evidence_ids=unique_evidence_ids(
                        table.evidence_ids + term.evidence_ids + (MAIN_TABLE_SOURCE,)
                    ),
                )
            )
    return tuple(definitions)


def build_table_plan(
    table: DarwinCoreTableSpec,
    term_definitions: tuple[DarwinCoreTermDefinition, ...],
) -> DarwinCoreTablePlan:
    tag_names = tuple(
        definition.tag_name
        for definition in term_definitions
        if definition.table_key == table.table_key
    )
    return DarwinCoreTablePlan(
        table_key=table.table_key,
        table_name=table.table_name,
        term_group=table.term_group,
        struct_name=table.struct_name,
        flat_prefix=table.flat_prefix,
        tag_names=tag_names,
        evidence_ids=table.evidence_ids,
    )


def build_boundaries(
    term_definitions: tuple[DarwinCoreTermDefinition, ...],
) -> DarwinCoreBoundaryPlan:
    writable_terms = tuple(
        f"{definition.table_key}.{definition.term_id}"
        for definition in term_definitions
        if definition.boundary == "writable"
    )
    avoided_terms = tuple(
        f"{definition.table_key}.{definition.term_id}"
        for definition in term_definitions
        if definition.boundary == "avoided"
    )
    return DarwinCoreBoundaryPlan(
        writable_terms=writable_terms,
        avoided_terms=avoided_terms,
        read_only_terms=(),
        evidence_ids=(MAIN_TABLE_SOURCE, EVENT_STRUCT_SOURCE),
    )


def build_structured_responsibilities() -> tuple[DarwinCoreStructuredResponsibility, ...]:
    return (
        DarwinCoreStructuredResponsibility(
            "event",
            ("Event", "HumanObservation", "MachineObservation"),
            ("eventDate", "eventTime", "fieldNumber", "eventType"),
            (EVENT_STRUCT_SOURCE, EVENT_TABLE_SOURCE, MATERIAL_SAMPLE_TABLE_SOURCE),
        ),
        DarwinCoreStructuredResponsibility(
            "occurrence",
            ("Occurrence",),
            ("occurrenceID", "catalogNumber", "recordedByID", "vitality"),
            (OCCURRENCE_SOURCE,),
        ),
        DarwinCoreStructuredResponsibility(
            "location",
            ("dctermsLocation",),
            ("decimalLatitude", "decimalLongitude", "georeferencedDate", "verticalDatum"),
            (LOCATION_SOURCE,),
        ),
        DarwinCoreStructuredResponsibility(
            "taxon",
            ("Taxon",),
            ("scientificName", "taxonID", "vernacularName", "genericName"),
            (TAXON_SOURCE,),
        ),
        DarwinCoreStructuredResponsibility(
            "geological_context",
            ("GeologicalContext",),
            ("bed", "formation", "lithostratigraphicTerms", "member"),
            (GEOLOGICAL_CONTEXT_SOURCE,),
        ),
    )


def build_responsibilities() -> tuple[DarwinCoreResponsibilityPlan, ...]:
    return (
        DarwinCoreResponsibilityPlan(
            "xmp_namespace_database",
            "Plan the Darwin Core dwc namespace inside the XMP-dwc group.",
            (MAIN_TABLE_SOURCE, POD_SOURCE),
        ),
        DarwinCoreResponsibilityPlan(
            "structured_table_grouping",
            "Keep ExifTool's structured table membership and shared structures explicit.",
            (EVENT_STRUCT_SOURCE, MATERIAL_SAMPLE_SOURCE, MAIN_TABLE_SOURCE),
        ),
        DarwinCoreResponsibilityPlan(
            "flattened_tag_naming",
            "Apply ExifTool flat prefixes and explicit flattened-name tweaks.",
            (
                EVENT_TABLE_SOURCE,
                GEOLOGICAL_CONTEXT_SOURCE,
                OCCURRENCE_SOURCE,
                ORGANISM_SOURCE,
                TAXON_SOURCE,
                LOCATION_SOURCE,
            ),
        ),
        DarwinCoreResponsibilityPlan(
            "writable_value_boundaries",
            (
                "Honor table-level string writability, specialized date/integer/lang-alt/real "
                "terms, and avoided tags."
            ),
            (MAIN_TABLE_SOURCE, DATE_TIME_INFO_SOURCE, EVENT_STRUCT_SOURCE, TAXON_SOURCE),
        ),
        DarwinCoreResponsibilityPlan(
            "core_structured_responsibilities",
            "Expose occurrence, event, location, taxon, and geological context planning groups.",
            (
                EVENT_STRUCT_SOURCE,
                OCCURRENCE_SOURCE,
                LOCATION_SOURCE,
                TAXON_SOURCE,
                GEOLOGICAL_CONTEXT_SOURCE,
            ),
        ),
        DarwinCoreResponsibilityPlan(
            "value_preservation_boundaries",
            "Preserve the surrounding XMP packet and unplanned metadata during route planning.",
            (MAIN_TABLE_SOURCE, POD_SOURCE),
        ),
        DarwinCoreResponsibilityPlan(
            "non_mutating_emission_gates",
            "Keep this planner non-mutating until an XMP transaction writer owns byte emission.",
            (MAIN_TABLE_SOURCE,),
        ),
    )


def build_value_preservation_boundaries() -> tuple[DarwinCoreValuePreservationBoundary, ...]:
    return (
        DarwinCoreValuePreservationBoundary(
            "xmp_packet",
            ("raw packet layout", "non-DarwinCore XMP namespaces", "unknown dwc payload"),
            "DarwinCore.pm defines tags only; packet rewrite must preserve unrelated XMP.",
            (MAIN_TABLE_SOURCE, POD_SOURCE),
        ),
        DarwinCoreValuePreservationBoundary(
            "structured_values",
            ("nested structures", "lang-alt alternatives", "time conversion evidence_id text"),
            (
                "Structured and converted values need parent XMP transaction context before "
                "bytes change."
            ),
            (EVENT_STRUCT_SOURCE, DATE_TIME_INFO_SOURCE, TAXON_SOURCE),
        ),
    )


def build_rewrite_blockers() -> tuple[DarwinCoreRewriteBlocker, ...]:
    return (
        DarwinCoreRewriteBlocker(
            "xmp_packet_writer_not_in_scope",
            "Darwin Core planning does not include a full XMP packet writer.",
            (MAIN_TABLE_SOURCE,),
        ),
        DarwinCoreRewriteBlocker(
            "structured_flattening_requires_parent_xmp_transaction",
            "Flattened tag aliases cannot be emitted without rebuilding their parent structures.",
            (
                EVENT_TABLE_SOURCE,
                GEOLOGICAL_CONTEXT_SOURCE,
                OCCURRENCE_SOURCE,
                ORGANISM_SOURCE,
                TAXON_SOURCE,
                LOCATION_SOURCE,
            ),
        ),
        DarwinCoreRewriteBlocker(
            "raw_xmp_packet_layout_must_be_preserved",
            "Planning must preserve packet layout and unrelated namespaces.",
            (MAIN_TABLE_SOURCE, POD_SOURCE),
        ),
    )


def build_metadata_entry(
    term: DarwinCoreMetadataTerm,
    definition_lookup: dict[tuple[str, str], DarwinCoreTermDefinition],
) -> DarwinCoreMetadataEntry | None:
    definition = definition_lookup.get((term.table_key, normalize_key(term.term_id)))
    if definition is None:
        return None
    return DarwinCoreMetadataEntry(
        table_key=definition.table_key,
        term_id=definition.term_id,
        tag_name=definition.tag_name,
        value=term.value,
        value_kind=definition.value_kind,
        preserved=True,
        evidence_ids=definition.evidence_ids,
    )


def build_route(
    request: DarwinCoreMetadataWriteRequest,
    definition_lookup: dict[tuple[str, str], DarwinCoreTermDefinition],
    table_lookup: dict[str, DarwinCoreTableSpec],
) -> DarwinCoreRoutePlan:
    definition = definition_lookup.get((request.table_key, normalize_key(request.term_id)))
    if definition is None:
        references: tuple[str, ...] = (MAIN_TABLE_SOURCE,)
        if request.table_key in table_lookup:
            references = table_lookup[request.table_key].evidence_ids
        return DarwinCoreRoutePlan(
            action="block",
            table_key=request.table_key,
            term_id=request.term_id,
            tag_name=None,
            requested_value=request.value,
            reason="No DarwinCore.pm term definition matched this request.",
            evidence_ids=references,
        )
    if definition.boundary == "avoided":
        return DarwinCoreRoutePlan(
            action="block",
            table_key=definition.table_key,
            term_id=definition.term_id,
            tag_name=definition.tag_name,
            requested_value=request.value,
            reason="ExifTool marks this term Avoid and prefers another namespace.",
            evidence_ids=definition.evidence_ids,
        )
    if not value_matches_kind(request.value, definition.value_kind):
        return DarwinCoreRoutePlan(
            action="block",
            table_key=definition.table_key,
            term_id=definition.term_id,
            tag_name=definition.tag_name,
            requested_value=request.value,
            reason="Requested value does not match the ExifTool writable format.",
            evidence_ids=definition.evidence_ids,
        )
    return DarwinCoreRoutePlan(
        action="upsert_term",
        table_key=definition.table_key,
        term_id=definition.term_id,
        tag_name=definition.tag_name,
        requested_value=request.value,
        reason="Term is writable in the Darwin Core XMP tag table.",
        evidence_ids=definition.evidence_ids,
    )


def build_output_emission_gates(
    routes: tuple[DarwinCoreRoutePlan, ...],
) -> tuple[DarwinCoreEmissionGate, ...]:
    gates: list[DarwinCoreEmissionGate] = []
    for route in routes:
        if route.action != "block":
            continue
        if route.tag_name is None:
            gates.append(
                DarwinCoreEmissionGate(
                    "unknown_darwincore_term",
                    route.reason,
                    route.evidence_ids,
                )
            )
        elif route.reason.startswith("ExifTool marks"):
            gates.append(
                DarwinCoreEmissionGate(
                    "avoided_darwincore_term",
                    route.reason,
                    route.evidence_ids,
                )
            )
        else:
            gates.append(
                DarwinCoreEmissionGate(
                    "invalid_darwincore_value_kind",
                    route.reason,
                    route.evidence_ids,
                )
            )
    gates.extend(
        (
            DarwinCoreEmissionGate(
                "raw_xmp_packet_preservation_required",
                (
                    "Darwin Core planning cannot emit bytes without preserving the surrounding "
                    "XMP packet."
                ),
                (MAIN_TABLE_SOURCE, POD_SOURCE),
            ),
            DarwinCoreEmissionGate(
                "planner_is_non_mutating",
                "This planner records routes and blockers only.",
                (MAIN_TABLE_SOURCE,),
            ),
            DarwinCoreEmissionGate(
                "xmp_writer_not_implemented",
                "No Darwin Core XMP writer is implemented here.",
                (MAIN_TABLE_SOURCE,),
            ),
        )
    )
    return tuple(gates)


def tag_name_for(table: DarwinCoreTableSpec, term_id: str) -> str:
    if (override := FLAT_NAME_OVERRIDES.get((table.table_key, term_id))) is not None:
        return override
    term_name = pascal_case(term_id)
    if table.flat_prefix == "":
        return term_name
    return f"{table.flat_prefix}{term_name}"


def pascal_case(value: str) -> str:
    return value[:1].upper() + value[1:]


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def value_matches_kind(
    value: DarwinCoreMetadataValue,
    value_kind: DarwinCoreValueKind,
) -> bool:
    if value_kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_kind == "real":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if value_kind == "lang_alt":
        return isinstance(value, dict) and all(
            isinstance(key, str) and isinstance(item, str) for key, item in value.items()
        )
    return isinstance(value, str)


def metadata_value_to_json(value: DarwinCoreMetadataValue | None) -> JsonValue:
    if value is None:
        return None
    if isinstance(value, dict):
        return {key: item for key, item in value.items()}
    return value


def evidence_id_to_json(reference: str) -> dict[str, JsonValue]:
    return {"id": reference}


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return [evidence_id_to_json(reference) for reference in references]


def unique_evidence_ids(
    references: tuple[str, ...],
) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for reference in references:
        if reference in seen:
            continue
        seen.add(reference)
        unique.append(reference)
    return tuple(unique)
