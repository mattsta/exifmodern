"""OOXML package metadata transaction planning."""

from exifmodern.formats.ooxml.package_transaction_plan import (
    OoxmlContentTypesPlan,
    OoxmlDocumentMetadataPathPlan,
    OoxmlEntryResponsibilityPlan,
    OoxmlOutputEmissionGate,
    OoxmlPackageTransactionPlan,
    OoxmlPreservationBoundaryPlan,
    OoxmlPropertyPartPlan,
    OoxmlRelationshipsPlan,
    OoxmlRewriteBlocker,
    build_ooxml_package_transaction_plan,
)

__all__ = [
    "OoxmlContentTypesPlan",
    "OoxmlDocumentMetadataPathPlan",
    "OoxmlEntryResponsibilityPlan",
    "OoxmlOutputEmissionGate",
    "OoxmlPackageTransactionPlan",
    "OoxmlPreservationBoundaryPlan",
    "OoxmlPropertyPartPlan",
    "OoxmlRelationshipsPlan",
    "OoxmlRewriteBlocker",
    "build_ooxml_package_transaction_plan",
]

# No SIGNATURES export: OOXML files are ZIP containers; dispatch via zip.
