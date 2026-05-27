"""Source-grounded PLUS XMP metadata transaction plans.

ExifTool's PLUS.pm defines the XMP-plus namespace, structured party fields,
controlled vocabularies, lang-alt/list boundaries, Media Summary validation,
and no package-local byte writer. This planner classifies routes and preserves
unknown fields without mutating packet bytes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, TypeGuard

from exifmodern.json_types import JsonArray, JsonValue

PLUS_SOURCE_PATH = "lib/Image/ExifTool/PLUS.pm"
PLUS_NAMESPACE = "plus"
PLUS_XMP_GROUP = "XMP-plus"
PLUS_VOCAB_PREFIX = "http://ns.useplus.org/ldf/vocab/"

type PlusValueKind = Literal[
    "string",
    "date",
    "lang_alt",
    "seq_struct",
    "bag_string",
    "bag_lang_alt",
    "vocabulary",
    "bag_vocabulary",
    "media_summary_code",
]
type PlusVocabularyResponsibility = Literal[
    "constraint_vocabulary",
    "release_vocabulary",
    "image_delivery_vocabulary",
    "rights_vocabulary",
    "reuse_vocabulary",
    "data_mining_vocabulary",
    "contact_vocabulary",
]
type PlusRouteAction = Literal["upsert_plus_tag", "preserve_existing", "block"]
type PlusRouteBlockerCode = Literal[
    "unsupported_namespace",
    "unknown_plus_tag",
    "invalid_plus_value_kind",
    "invalid_plus_vocabulary_value",
    "malformed_media_summary_code",
]
type PlusRewriteBlockerCode = Literal[
    "xmp_packet_writer_not_in_scope",
    "plus_struct_rewrite_not_in_scope",
    "raw_xmp_packet_layout_must_be_preserved",
]
type PlusEmissionGateCode = Literal[
    "unsupported_plus_rewrite",
    "blocked_route",
    "unknown_field_preservation_required",
    "raw_xmp_packet_preservation_required",
    "planner_is_non_mutating",
]
type PlusPlanConcern = Literal[
    "plus_namespace_routing",
    "controlled_vocabulary_conversion",
    "structured_party_boundaries",
    "media_summary_validation",
    "unknown_field_preservation",
    "unsupported_rewrite_gates",
]
type PlusStringTuple = tuple[str, ...]
type PlusLangAlt = dict[str, str]
type PlusLangAltTuple = tuple[PlusLangAlt, ...]
type PlusStructSequence = tuple[dict[str, str], ...]
type PlusMetadataValue = str | tuple[str, ...] | dict[str, str] | tuple[dict[str, str], ...]

PLUS_VOCAB_SOURCE = "plus.vocab"
PLUS_STRUCT_SOURCE = "plus.struct"
PLUS_MEDIA_MATRIX_SOURCE = "plus.media.matrix"
PLUS_MAIN_TABLE_SOURCE = "plus.main.table"
PLUS_MEDIA_VALIDATE_SOURCE = "plus.media.validate"
PLUS_POD_SOURCE = "plus.pod"
PLUS_TRANSACTION_SOURCES = (
    PLUS_VOCAB_SOURCE,
    PLUS_STRUCT_SOURCE,
    PLUS_MEDIA_MATRIX_SOURCE,
    PLUS_MAIN_TABLE_SOURCE,
    PLUS_MEDIA_VALIDATE_SOURCE,
    PLUS_POD_SOURCE,
)


@dataclass(frozen=True)
class PlusVocabularyDefinition:
    tag_name: str
    responsibility: PlusVocabularyResponsibility
    list_kind: Literal["single", "bag"]
    values: dict[str, str]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "list_kind": self.list_kind,
            "responsibility": self.responsibility,
            "tag_name": self.tag_name,
            "values": {key: value for key, value in self.values.items()},
            "vocab_prefix": PLUS_VOCAB_PREFIX,
        }


@dataclass(frozen=True)
class PlusTagDefinition:
    tag_name: str
    namespace: str
    xmp_group: str
    value_kind: PlusValueKind
    raw_name: str
    list_kind: Literal["none", "bag", "seq"]
    vocabulary: PlusVocabularyDefinition | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "list_kind": self.list_kind,
            "namespace": self.namespace,
            "raw_name": self.raw_name,
            "tag_name": self.tag_name,
            "value_kind": self.value_kind,
            "vocabulary": self.vocabulary.to_json() if self.vocabulary else None,
            "xmp_group": self.xmp_group,
        }


@dataclass(frozen=True)
class PlusExistingField:
    namespace: str
    tag_name: str
    value: PlusMetadataValue


@dataclass(frozen=True)
class PlusWriteRequest:
    namespace: str
    tag_name: str
    value: PlusMetadataValue


@dataclass(frozen=True)
class PlusMetadataEntry:
    namespace: str
    tag_name: str
    value: PlusMetadataValue
    known: bool
    preserved: bool
    value_kind: PlusValueKind | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "known": self.known,
            "namespace": self.namespace,
            "preserved": self.preserved,
            "tag_name": self.tag_name,
            "value": metadata_value_to_json(self.value),
            "value_kind": self.value_kind,
        }


@dataclass(frozen=True)
class PlusRoutePlan:
    action: PlusRouteAction
    namespace: str
    tag_name: str
    requested_value: PlusMetadataValue | None
    normalized_vocab_values: tuple[str, ...]
    blocker_code: PlusRouteBlockerCode | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "action": self.action,
            "blocker_code": self.blocker_code,
            "namespace": self.namespace,
            "normalized_vocab_values": list(self.normalized_vocab_values),
            "reason": self.reason,
            "requested_value": metadata_value_to_json(self.requested_value),
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class PlusBoundaryPlan:
    structured_seq_tags: tuple[str, ...]
    lang_alt_tags: tuple[str, ...]
    bag_tags: tuple[str, ...]
    controlled_vocabulary_tags: tuple[str, ...]
    date_tags: tuple[str, ...]
    media_summary_tags: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "bag_tags": list(self.bag_tags),
            "controlled_vocabulary_tags": list(self.controlled_vocabulary_tags),
            "date_tags": list(self.date_tags),
            "lang_alt_tags": list(self.lang_alt_tags),
            "media_summary_tags": list(self.media_summary_tags),
            "structured_seq_tags": list(self.structured_seq_tags),
        }


@dataclass(frozen=True)
class PlusPreservationBoundary:
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
class PlusRewriteBlocker:
    code: PlusRewriteBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlusEmissionGate:
    code: PlusEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlusResponsibilityPlan:
    concern: PlusPlanConcern
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "concern": self.concern,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlusMetadataTransactionPlan:
    namespace: str
    xmp_group: str
    tag_definitions: tuple[PlusTagDefinition, ...]
    vocabulary_definitions: tuple[PlusVocabularyDefinition, ...]
    boundaries: PlusBoundaryPlan
    metadata_entries: tuple[PlusMetadataEntry, ...]
    routes: tuple[PlusRoutePlan, ...]
    preservation_boundaries: tuple[PlusPreservationBoundary, ...]
    rewrite_blockers: tuple[PlusRewriteBlocker, ...]
    output_emission_gates: tuple[PlusEmissionGate, ...]
    responsibilities: tuple[PlusResponsibilityPlan, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return False

    def emit(self) -> bytes:
        raise ValueError("PLUS metadata transaction output is gated")

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "boundaries": self.boundaries.to_json(),
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "metadata_entries": [entry.to_json() for entry in self.metadata_entries],
            "namespace": self.namespace,
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "preservation_boundaries": [
                boundary.to_json() for boundary in self.preservation_boundaries
            ],
            "responsibilities": [item.to_json() for item in self.responsibilities],
            "rewrite_blockers": [blocker.to_json() for blocker in self.rewrite_blockers],
            "routes": [route.to_json() for route in self.routes],
            "tag_definitions": [definition.to_json() for definition in self.tag_definitions],
            "vocabulary_definitions": [
                definition.to_json() for definition in self.vocabulary_definitions
            ],
            "xmp_group": self.xmp_group,
        }


VOCABULARY_DEFINITIONS = (
    PlusVocabularyDefinition(
        "ImageFileConstraints",
        "constraint_vocabulary",
        "bag",
        {
            "IF-MFN": "Maintain File Name",
            "IF-MID": "Maintain ID in File Name",
            "IF-MMD": "Maintain Metadata",
            "IF-MFT": "Maintain File Type",
        },
        (PLUS_MAIN_TABLE_SOURCE, PLUS_VOCAB_SOURCE),
    ),
    PlusVocabularyDefinition(
        "ImageAlterationConstraints",
        "constraint_vocabulary",
        "bag",
        {
            "AL-CRP": "No Cropping",
            "AL-FLP": "No Flipping",
            "AL-RET": "No Retouching",
            "AL-CLR": "No Colorization",
            "AL-DCL": "No De-Colorization",
            "AL-MRG": "No Merging",
        },
        (PLUS_MAIN_TABLE_SOURCE, PLUS_VOCAB_SOURCE),
    ),
    PlusVocabularyDefinition(
        "ImageDuplicationConstraints",
        "constraint_vocabulary",
        "single",
        {
            "DP-NDC": "No Duplication Constraints",
            "DP-LIC": "Duplication Only as Necessary Under License",
            "DP-NOD": "No Duplication",
        },
        (PLUS_MAIN_TABLE_SOURCE, PLUS_VOCAB_SOURCE),
    ),
    PlusVocabularyDefinition(
        "ModelReleaseStatus",
        "release_vocabulary",
        "single",
        {
            "MR-NON": "None",
            "MR-NAP": "Not Applicable",
            "MR-UMR": "Unlimited Model Releases",
            "MR-LMR": "Limited or Incomplete Model Releases",
        },
        (PLUS_MAIN_TABLE_SOURCE, PLUS_VOCAB_SOURCE),
    ),
    PlusVocabularyDefinition(
        "PropertyReleaseStatus",
        "release_vocabulary",
        "single",
        {
            "PR-NON": "None",
            "PR-NAP": "Not Applicable",
            "PR-UPR": "Unlimited Property Releases",
            "PR-LPR": "Limited or Incomplete Property Releases",
        },
        (PLUS_MAIN_TABLE_SOURCE, PLUS_VOCAB_SOURCE),
    ),
    PlusVocabularyDefinition(
        "CreditLineRequired",
        "rights_vocabulary",
        "single",
        {
            "CR-NRQ": "Not Required",
            "CR-COI": "Credit on Image",
            "CR-CAI": "Credit Adjacent To Image",
            "CR-CCA": "Credit in Credits Area",
        },
        (PLUS_MAIN_TABLE_SOURCE, PLUS_VOCAB_SOURCE),
    ),
    PlusVocabularyDefinition(
        "AdultContentWarning",
        "rights_vocabulary",
        "single",
        {
            "CW-NRQ": "Not Required",
            "CW-AWR": "Adult Content Warning Required",
            "CW-UNK": "Unknown",
        },
        (PLUS_MAIN_TABLE_SOURCE, PLUS_VOCAB_SOURCE),
    ),
    PlusVocabularyDefinition(
        "ImageType",
        "image_delivery_vocabulary",
        "single",
        {
            "TY-PHO": "Photographic Image",
            "TY-ILL": "Illustrated Image",
            "TY-MCI": "Multimedia or Composited Image",
            "TY-VID": "Video",
            "TY-OTR": "Other",
        },
        (PLUS_MAIN_TABLE_SOURCE, PLUS_VOCAB_SOURCE),
    ),
    PlusVocabularyDefinition(
        "ImageFileFormatAsDelivered",
        "image_delivery_vocabulary",
        "single",
        {
            "FF-JPG": "JPEG Interchange Formats (JPG, JIF, JFIF)",
            "FF-TIF": "Tagged Image File Format (TIFF)",
            "FF-GIF": "Graphics Interchange Format (GIF)",
            "FF-RAW": "Proprietary RAW Image Format",
            "FF-DNG": "Digital Negative (DNG)",
            "FF-EPS": "Encapsulated PostScript (EPS)",
            "FF-BMP": "Windows Bitmap (BMP)",
            "FF-PSD": "Photoshop Document (PSD)",
            "FF-PIC": "Macintosh Picture (PICT)",
            "FF-PNG": "Portable Network Graphics (PNG)",
            "FF-WMP": "Windows Media Photo (HD Photo)",
            "FF-OTR": "Other",
        },
        (PLUS_MAIN_TABLE_SOURCE, PLUS_VOCAB_SOURCE),
    ),
    PlusVocabularyDefinition(
        "CopyrightStatus",
        "rights_vocabulary",
        "single",
        {
            "CS-PRO": "Protected",
            "CS-PUB": "Public Domain",
            "CS-UNK": "Unknown",
        },
        (PLUS_MAIN_TABLE_SOURCE, PLUS_VOCAB_SOURCE),
    ),
    PlusVocabularyDefinition(
        "Reuse",
        "reuse_vocabulary",
        "single",
        {
            "RE-REU": "Repeat Use",
            "RE-NAP": "Not Applicable",
        },
        (PLUS_MAIN_TABLE_SOURCE, PLUS_VOCAB_SOURCE),
    ),
    PlusVocabularyDefinition(
        "DataMining",
        "data_mining_vocabulary",
        "single",
        {
            "DMI-UNSPECIFIED": "Unspecified - no prohibition defined",
            "DMI-ALLOWED": "Allowed",
            "DMI-PROHIBITED-AIMLTRAINING": "Prohibited for AI/ML training",
            "DMI-PROHIBITED-GENAIMLTRAINING": "Prohibited for Generative AI/ML training",
            "DMI-PROHIBITED-EXCEPTSEARCHENGINEINDEXING": (
                "Prohibited except for search engine indexing"
            ),
            "DMI-PROHIBITED": "Prohibited",
            "DMI-PROHIBITED-SEECONSTRAINT": "Prohibited, see plus:OtherConstraints",
            "DMI-PROHIBITED-SEEEMBEDDEDRIGHTSEXPR": ("Prohibited, see iptcExt:EmbdEncRightsExpr"),
            "DMI-PROHIBITED-SEELINKEDRIGHTSEXPR": ("Prohibited, see iptcExt:LinkedEncRightsExpr"),
        },
        (PLUS_MAIN_TABLE_SOURCE, PLUS_VOCAB_SOURCE),
    ),
    PlusVocabularyDefinition(
        "LicensorTelephoneType1",
        "contact_vocabulary",
        "single",
        {
            "work": "Work",
            "cell": "Cell",
            "fax": "FAX",
            "home": "Home",
            "pager": "Pager",
        },
        (PLUS_STRUCT_SOURCE, PLUS_VOCAB_SOURCE),
    ),
    PlusVocabularyDefinition(
        "LicensorTelephoneType2",
        "contact_vocabulary",
        "single",
        {
            "work": "Work",
            "cell": "Cell",
            "fax": "FAX",
            "home": "Home",
            "pager": "Pager",
        },
        (PLUS_STRUCT_SOURCE, PLUS_VOCAB_SOURCE),
    ),
)

VOCABULARY_LOOKUP: dict[str, PlusVocabularyDefinition] = {
    definition.tag_name: definition for definition in VOCABULARY_DEFINITIONS
}

TAG_SPECS: tuple[tuple[str, PlusValueKind, str, Literal["none", "bag", "seq"]], ...] = (
    ("Version", "string", "PLUSVersion", "none"),
    ("Licensee", "seq_struct", "Licensee", "seq"),
    ("EndUser", "seq_struct", "EndUser", "seq"),
    ("Licensor", "seq_struct", "Licensor", "seq"),
    ("LicensorNotes", "lang_alt", "LicensorNotes", "none"),
    ("MediaSummaryCode", "media_summary_code", "MediaSummaryCode", "none"),
    ("LicenseStartDate", "date", "LicenseStartDate", "none"),
    ("LicenseEndDate", "date", "LicenseEndDate", "none"),
    ("MediaConstraints", "lang_alt", "MediaConstraints", "none"),
    ("RegionConstraints", "lang_alt", "RegionConstraints", "none"),
    ("ProductOrServiceConstraints", "lang_alt", "ProductOrServiceConstraints", "none"),
    ("ImageFileConstraints", "bag_vocabulary", "ImageFileConstraints", "bag"),
    ("ImageAlterationConstraints", "bag_vocabulary", "ImageAlterationConstraints", "bag"),
    ("ImageDuplicationConstraints", "vocabulary", "ImageDuplicationConstraints", "none"),
    ("ModelReleaseStatus", "vocabulary", "ModelReleaseStatus", "none"),
    ("ModelReleaseID", "bag_string", "ModelReleaseID", "bag"),
    ("PropertyReleaseStatus", "vocabulary", "PropertyReleaseStatus", "none"),
    ("PropertyReleaseID", "bag_string", "PropertyReleaseID", "bag"),
    ("OtherConstraints", "lang_alt", "OtherConstraints", "none"),
    ("CreditLineRequired", "vocabulary", "CreditLineRequired", "none"),
    ("AdultContentWarning", "vocabulary", "AdultContentWarning", "none"),
    ("OtherLicenseRequirements", "lang_alt", "OtherLicenseRequirements", "none"),
    ("TermsAndConditionsText", "lang_alt", "TermsAndConditionsText", "none"),
    ("TermsAndConditionsURL", "string", "TermsAndConditionsURL", "none"),
    ("OtherConditions", "lang_alt", "OtherConditions", "none"),
    ("ImageType", "vocabulary", "ImageType", "none"),
    ("LicensorImageID", "string", "LicensorImageID", "none"),
    ("FileNameAsDelivered", "string", "FileNameAsDelivered", "none"),
    ("ImageFileFormatAsDelivered", "vocabulary", "ImageFileFormatAsDelivered", "none"),
    ("CopyrightStatus", "vocabulary", "CopyrightStatus", "none"),
    ("CopyrightRegistrationNumber", "string", "CopyrightRegistrationNumber", "none"),
    ("FirstPublicationDate", "date", "FirstPublicationDate", "none"),
    ("CopyrightOwner", "seq_struct", "CopyrightOwner", "seq"),
    ("ImageCreator", "seq_struct", "ImageCreator", "seq"),
    ("ImageSupplier", "seq_struct", "ImageSupplier", "seq"),
    ("LicenseeImageID", "string", "LicenseeImageID", "none"),
    ("LicenseeImageNotes", "lang_alt", "LicenseeImageNotes", "none"),
    ("OtherImageInfo", "lang_alt", "OtherImageInfo", "none"),
    ("LicenseID", "string", "LicenseID", "none"),
    ("LicensorTransactionID", "bag_string", "LicensorTransactionID", "bag"),
    ("LicenseeTransactionID", "bag_string", "LicenseeTransactionID", "bag"),
    ("LicenseeProjectReference", "bag_string", "LicenseeProjectReference", "bag"),
    ("LicenseTransactionDate", "date", "LicenseTransactionDate", "none"),
    ("Reuse", "vocabulary", "Reuse", "none"),
    ("OtherLicenseDocuments", "bag_string", "OtherLicenseDocuments", "bag"),
    ("OtherLicenseInfo", "lang_alt", "OtherLicenseInfo", "none"),
    ("Custom1", "bag_lang_alt", "Custom1", "bag"),
    ("DataMining", "vocabulary", "DataMining", "none"),
)


def build_plus_metadata_transaction_plan(
    existing_fields: tuple[PlusExistingField, ...] = (),
    write_requests: tuple[PlusWriteRequest, ...] = (),
) -> PlusMetadataTransactionPlan:
    tag_definitions = build_tag_definitions()
    definition_lookup = {
        (definition.namespace, normalize_key(definition.tag_name)): definition
        for definition in tag_definitions
    }
    metadata_entries = tuple(
        build_metadata_entry(field, definition_lookup) for field in existing_fields
    )
    routes = tuple(build_route(request, definition_lookup) for request in write_requests)
    unknown_entries = tuple(entry for entry in metadata_entries if not entry.known)
    return PlusMetadataTransactionPlan(
        namespace=PLUS_NAMESPACE,
        xmp_group=PLUS_XMP_GROUP,
        tag_definitions=tag_definitions,
        vocabulary_definitions=VOCABULARY_DEFINITIONS,
        boundaries=build_boundaries(tag_definitions),
        metadata_entries=metadata_entries,
        routes=routes,
        preservation_boundaries=build_preservation_boundaries(),
        rewrite_blockers=build_rewrite_blockers(),
        output_emission_gates=build_output_emission_gates(routes, unknown_entries),
        responsibilities=build_responsibilities(),
        evidence_ids=unique_evidence_ids(
            PLUS_TRANSACTION_SOURCES
            + tuple(source for definition in tag_definitions for source in definition.evidence_ids)
        ),
    )


def build_tag_definitions() -> tuple[PlusTagDefinition, ...]:
    return tuple(
        PlusTagDefinition(
            tag_name=tag_name,
            namespace=PLUS_NAMESPACE,
            xmp_group=PLUS_XMP_GROUP,
            value_kind=value_kind,
            raw_name=raw_name,
            list_kind=list_kind,
            vocabulary=VOCABULARY_LOOKUP.get(tag_name),
            evidence_ids=tag_evidence_ids(tag_name),
        )
        for tag_name, value_kind, raw_name, list_kind in TAG_SPECS
    )


def tag_evidence_ids(tag_name: str) -> tuple[str, ...]:
    references: tuple[str, ...] = (PLUS_MAIN_TABLE_SOURCE,)
    if tag_name in VOCABULARY_LOOKUP:
        references = (*references, PLUS_VOCAB_SOURCE)
    if tag_name in {
        "Licensee",
        "EndUser",
        "Licensor",
        "CopyrightOwner",
        "ImageCreator",
        "ImageSupplier",
    }:
        references = (*references, PLUS_STRUCT_SOURCE)
    if tag_name == "MediaSummaryCode":
        references = (*references, PLUS_MEDIA_MATRIX_SOURCE, PLUS_MEDIA_VALIDATE_SOURCE)
    return references


def build_boundaries(tag_definitions: tuple[PlusTagDefinition, ...]) -> PlusBoundaryPlan:
    return PlusBoundaryPlan(
        structured_seq_tags=tuple(
            definition.tag_name
            for definition in tag_definitions
            if definition.value_kind == "seq_struct"
        ),
        lang_alt_tags=tuple(
            definition.tag_name
            for definition in tag_definitions
            if definition.value_kind in {"lang_alt", "bag_lang_alt"}
        ),
        bag_tags=tuple(
            definition.tag_name for definition in tag_definitions if definition.list_kind == "bag"
        ),
        controlled_vocabulary_tags=tuple(
            definition.tag_name
            for definition in tag_definitions
            if definition.vocabulary is not None
        ),
        date_tags=tuple(
            definition.tag_name for definition in tag_definitions if definition.value_kind == "date"
        ),
        media_summary_tags=("MediaSummaryCode",),
        evidence_ids=(PLUS_MAIN_TABLE_SOURCE, PLUS_STRUCT_SOURCE, PLUS_VOCAB_SOURCE),
    )


def build_metadata_entry(
    field: PlusExistingField,
    definition_lookup: dict[tuple[str, str], PlusTagDefinition],
) -> PlusMetadataEntry:
    definition = definition_lookup.get((field.namespace, normalize_key(field.tag_name)))
    if definition is None:
        return PlusMetadataEntry(
            namespace=field.namespace,
            tag_name=field.tag_name,
            value=field.value,
            known=False,
            preserved=True,
            value_kind=None,
            evidence_ids=(PLUS_MAIN_TABLE_SOURCE, PLUS_POD_SOURCE),
        )
    return PlusMetadataEntry(
        namespace=definition.namespace,
        tag_name=definition.tag_name,
        value=field.value,
        known=True,
        preserved=True,
        value_kind=definition.value_kind,
        evidence_ids=definition.evidence_ids,
    )


def build_route(
    request: PlusWriteRequest,
    definition_lookup: dict[tuple[str, str], PlusTagDefinition],
) -> PlusRoutePlan:
    if request.namespace != PLUS_NAMESPACE:
        return PlusRoutePlan(
            action="block",
            namespace=request.namespace,
            tag_name=request.tag_name,
            requested_value=request.value,
            normalized_vocab_values=(),
            blocker_code="unsupported_namespace",
            reason="PLUS.pm owns only the plus namespace in the XMP-plus group.",
            evidence_ids=(PLUS_MAIN_TABLE_SOURCE,),
        )
    definition = definition_lookup.get((request.namespace, normalize_key(request.tag_name)))
    if definition is None:
        return PlusRoutePlan(
            action="block",
            namespace=request.namespace,
            tag_name=request.tag_name,
            requested_value=request.value,
            normalized_vocab_values=(),
            blocker_code="unknown_plus_tag",
            reason="No PLUS.pm XMP tag definition matched this request.",
            evidence_ids=(PLUS_MAIN_TABLE_SOURCE,),
        )
    if not value_matches_kind(request.value, definition.value_kind):
        return PlusRoutePlan(
            action="block",
            namespace=definition.namespace,
            tag_name=definition.tag_name,
            requested_value=request.value,
            normalized_vocab_values=(),
            blocker_code="invalid_plus_value_kind",
            reason="Requested value does not match the PLUS.pm writable/list boundary.",
            evidence_ids=definition.evidence_ids,
        )
    if definition.value_kind == "media_summary_code" and not validate_media_summary_code(
        request.value
    ):
        return PlusRoutePlan(
            action="block",
            namespace=definition.namespace,
            tag_name=definition.tag_name,
            requested_value=request.value,
            normalized_vocab_values=(),
            blocker_code="malformed_media_summary_code",
            reason="MediaSummaryCode failed the severe-error checks in ValidateMediaSummary.",
            evidence_ids=definition.evidence_ids,
        )
    normalized_vocab_values = normalized_vocabulary_values(request.value, definition)
    if definition.vocabulary is not None and not vocabulary_values_known(
        normalized_vocab_values, definition.vocabulary
    ):
        return PlusRoutePlan(
            action="block",
            namespace=definition.namespace,
            tag_name=definition.tag_name,
            requested_value=request.value,
            normalized_vocab_values=normalized_vocab_values,
            blocker_code="invalid_plus_vocabulary_value",
            reason="Requested controlled vocabulary value is not listed in PLUS.pm.",
            evidence_ids=definition.evidence_ids,
        )
    return PlusRoutePlan(
        action="upsert_plus_tag",
        namespace=definition.namespace,
        tag_name=definition.tag_name,
        requested_value=request.value,
        normalized_vocab_values=normalized_vocab_values,
        blocker_code=None,
        reason="Tag is routed to the PLUS XMP table but byte emission remains gated.",
        evidence_ids=definition.evidence_ids,
    )


def build_preservation_boundaries() -> tuple[PlusPreservationBoundary, ...]:
    return (
        PlusPreservationBoundary(
            "xmp_packet",
            ("raw packet layout", "non-PLUS namespaces", "unknown plus fields"),
            "PLUS.pm defines the tag table; packet rewrite must preserve unrelated XMP.",
            (PLUS_MAIN_TABLE_SOURCE, PLUS_POD_SOURCE),
        ),
        PlusPreservationBoundary(
            "plus_structures",
            ("Seq party structures", "nested bag lang-alt custom tags", "lang alternatives"),
            "Structured/list values require parent XMP transaction ownership before bytes change.",
            (PLUS_STRUCT_SOURCE, PLUS_MAIN_TABLE_SOURCE),
        ),
    )


def build_rewrite_blockers() -> tuple[PlusRewriteBlocker, ...]:
    return (
        PlusRewriteBlocker(
            "xmp_packet_writer_not_in_scope",
            "PLUS planning does not include a full XMP packet writer.",
            (PLUS_MAIN_TABLE_SOURCE,),
        ),
        PlusRewriteBlocker(
            "plus_struct_rewrite_not_in_scope",
            (
                "PLUS Seq structures and nested bag lang-alt tags are classified but not "
                "rewritten here."
            ),
            (PLUS_STRUCT_SOURCE, PLUS_MAIN_TABLE_SOURCE),
        ),
        PlusRewriteBlocker(
            "raw_xmp_packet_layout_must_be_preserved",
            "Planning must preserve packet layout and unrelated namespaces.",
            (PLUS_MAIN_TABLE_SOURCE, PLUS_POD_SOURCE),
        ),
    )


def build_output_emission_gates(
    routes: tuple[PlusRoutePlan, ...],
    unknown_entries: tuple[PlusMetadataEntry, ...],
) -> tuple[PlusEmissionGate, ...]:
    gates: list[PlusEmissionGate] = []
    if any(route.action == "upsert_plus_tag" for route in routes):
        gates.append(
            PlusEmissionGate(
                "unsupported_plus_rewrite",
                "Writable PLUS route planning is present, but byte rewrite is unsupported here.",
                (PLUS_MAIN_TABLE_SOURCE,),
            )
        )
    for route in routes:
        if route.action == "block":
            gates.append(
                PlusEmissionGate(
                    "blocked_route",
                    route.reason,
                    route.evidence_ids,
                )
            )
    if unknown_entries:
        gates.append(
            PlusEmissionGate(
                "unknown_field_preservation_required",
                "Existing unknown fields must be preserved by a parent XMP transaction.",
                (PLUS_MAIN_TABLE_SOURCE, PLUS_POD_SOURCE),
            )
        )
    gates.extend(
        (
            PlusEmissionGate(
                "raw_xmp_packet_preservation_required",
                "PLUS planning cannot emit bytes without preserving the surrounding XMP packet.",
                (PLUS_MAIN_TABLE_SOURCE, PLUS_POD_SOURCE),
            ),
            PlusEmissionGate(
                "planner_is_non_mutating",
                "This planner records routes and blockers only.",
                (PLUS_MAIN_TABLE_SOURCE,),
            ),
        )
    )
    return tuple(gates)


def build_responsibilities() -> tuple[PlusResponsibilityPlan, ...]:
    return (
        PlusResponsibilityPlan(
            "plus_namespace_routing",
            "Route source-backed PLUS tags only inside the plus namespace and XMP-plus group.",
            (PLUS_MAIN_TABLE_SOURCE,),
        ),
        PlusResponsibilityPlan(
            "controlled_vocabulary_conversion",
            "Classify PLUS controlled vocabularies and normalize the raw vocabulary prefix.",
            (PLUS_VOCAB_SOURCE, PLUS_MAIN_TABLE_SOURCE),
        ),
        PlusResponsibilityPlan(
            "structured_party_boundaries",
            "Track Seq party structures without flattening or rewriting them here.",
            (PLUS_STRUCT_SOURCE, PLUS_MAIN_TABLE_SOURCE),
        ),
        PlusResponsibilityPlan(
            "media_summary_validation",
            "Apply severe MediaSummaryCode shape checks from ValidateMediaSummary.",
            (PLUS_MEDIA_VALIDATE_SOURCE, PLUS_MEDIA_MATRIX_SOURCE),
        ),
        PlusResponsibilityPlan(
            "unknown_field_preservation",
            "Preserve unknown existing fields because PLUS.pm does not own packet rewrite.",
            (PLUS_MAIN_TABLE_SOURCE, PLUS_POD_SOURCE),
        ),
        PlusResponsibilityPlan(
            "unsupported_rewrite_gates",
            "Keep output gated until a parent XMP transaction writer owns byte emission.",
            (PLUS_MAIN_TABLE_SOURCE,),
        ),
    )


def value_matches_kind(value: PlusMetadataValue, value_kind: PlusValueKind) -> bool:
    if value_kind in {"string", "date", "vocabulary", "media_summary_code"}:
        return isinstance(value, str)
    if value_kind == "lang_alt":
        return is_lang_alt(value)
    if value_kind in {"bag_string", "bag_vocabulary"}:
        return is_string_tuple(value)
    if value_kind == "bag_lang_alt":
        return is_lang_alt_tuple(value)
    return is_struct_sequence(value)


def normalized_vocabulary_values(
    value: PlusMetadataValue,
    definition: PlusTagDefinition,
) -> tuple[str, ...]:
    if definition.vocabulary is None:
        return ()
    if definition.value_kind == "vocabulary" and isinstance(value, str):
        return (strip_vocab_prefix(value),)
    if definition.value_kind == "bag_vocabulary" and is_string_tuple(value):
        return tuple(strip_vocab_prefix(item) for item in value)
    return ()


def vocabulary_values_known(
    values: tuple[str, ...],
    vocabulary: PlusVocabularyDefinition,
) -> bool:
    return bool(values) and all(value in vocabulary.values for value in values)


def validate_media_summary_code(value: PlusMetadataValue) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split("|")
    if len(parts) < 5 or parts[0] != "" or parts[1] != "PLUS":
        return False
    if not re.fullmatch(r"V\d+", parts[2]):
        return False
    usage_count_match = re.fullmatch(r"U(\d+)", parts[3])
    if usage_count_match is None:
        return False
    usage_count = int(usage_count_match.group(1))
    usages = parts[4:-1] if parts[-1] == "" else parts[4:]
    if usage_count != len(usages):
        return False
    for usage in usages:
        if not validate_media_usage(usage):
            return False
    return True


def validate_media_usage(usage: str) -> bool:
    if len(usage) % 4 != 0:
        return False
    item_count_match = re.fullmatch(r"1I([A-Z])([A-Z])", usage[:4])
    if item_count_match is None:
        return False
    expected_items = (
        (ord(item_count_match.group(1)) - 65) * 26 + ord(item_count_match.group(2)) - 65 + 1
    )
    if len(usage) != 4 * (expected_items + 1):
        return False
    return all(
        re.fullmatch(r"\d[A-Z]{3}", usage[index : index + 4]) for index in range(4, len(usage), 4)
    )


def strip_vocab_prefix(value: str) -> str:
    if value.startswith(PLUS_VOCAB_PREFIX):
        return value.removeprefix(PLUS_VOCAB_PREFIX)
    return value


def is_string_tuple(value: PlusMetadataValue) -> TypeGuard[PlusStringTuple]:
    return isinstance(value, tuple) and all(isinstance(item, str) for item in value)


def is_lang_alt(value: PlusMetadataValue) -> TypeGuard[PlusLangAlt]:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    )


def is_lang_alt_tuple(value: PlusMetadataValue) -> TypeGuard[PlusLangAltTuple]:
    return isinstance(value, tuple) and all(is_lang_alt(item) for item in value)


def is_struct_sequence(value: PlusMetadataValue) -> TypeGuard[PlusStructSequence]:
    return isinstance(value, tuple) and all(
        isinstance(item, dict)
        and item != {}
        and all(isinstance(key, str) and isinstance(child, str) for key, child in item.items())
        for item in value
    )


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def metadata_value_to_json(value: PlusMetadataValue | None) -> JsonValue:
    if value is None:
        return None
    if isinstance(value, dict):
        return {key: item for key, item in value.items()}
    if isinstance(value, tuple):
        return [metadata_value_to_json(item) for item in value]
    return value


def evidence_id_to_json(reference: str) -> JsonValue:
    return reference


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


def unique_evidence_ids(
    references: tuple[str, ...],
) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for reference in references:
        key = reference
        if key in seen:
            continue
        seen.add(key)
        unique.append(reference)
    return tuple(unique)
