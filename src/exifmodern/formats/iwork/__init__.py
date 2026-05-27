"""Apple iWork package metadata transaction planning."""

from exifmodern.formats.iwork.package_transaction_plan import (
    IworkPackageTransactionPlan,
    IworkRewriteRequest,
    build_iwork_package_transaction_plan,
)

__all__ = [
    "IworkPackageTransactionPlan",
    "IworkRewriteRequest",
    "build_iwork_package_transaction_plan",
]

# No SIGNATURES export: iWork files are ZIP containers; dispatch via zip.
