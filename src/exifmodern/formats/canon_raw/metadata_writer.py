"""Non-mutating Canon RAW writer guard.

Canon RAW writes are classified in :mod:`exifmodern.formats.canon_raw.write_plan`.
This module deliberately refuses rewrites until the required CR2 TIFF and CR3
QuickTime/Canon UUID mutation engines are implemented.
"""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.canon_raw.container_transaction import (
    CanonRawContainerTransactionPlan,
    plan_canon_raw_container_transaction,
)
from exifmodern.formats.canon_raw.write_plan import CanonRawWriteRequestClassification


class CanonRawUnsupportedWriteError(RuntimeError):
    """Raised when a Canon RAW request is source-backed but not safely writable."""


@dataclass(frozen=True)
class CanonRawRewriteReadiness:
    supported: bool
    reason: str
    blocker_codes: tuple[str, ...]
    transaction_plan: CanonRawContainerTransactionPlan | None = None


def require_supported_canon_raw_rewrite(
    classification: CanonRawWriteRequestClassification,
    data: bytes | None = None,
) -> CanonRawRewriteReadiness:
    if classification.supported_for_modern_mutation:
        return CanonRawRewriteReadiness(
            supported=True,
            reason="Canon RAW request is supported by the modern writer.",
            blocker_codes=(),
        )
    if data is not None:
        transaction_plan = plan_canon_raw_container_transaction(data, classification)
        raise CanonRawUnsupportedWriteError(
            "Canon RAW metadata rewrite is deferred until source-backed container "
            f"mutation is implemented for {classification.container_kind}: "
            + ", ".join(transaction_plan.blocker_codes())
        )
    blocker_codes = tuple(blocker for tag in classification.tags for blocker in tag.blocker_codes)
    unique_blockers = tuple(dict.fromkeys(blocker_codes))
    raise CanonRawUnsupportedWriteError(
        "Canon RAW metadata rewrite is deferred until source-backed container "
        f"mutation is implemented for {classification.container_kind}: "
        + ", ".join(unique_blockers)
    )
