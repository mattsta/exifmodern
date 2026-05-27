"""Canon RAW write-surface classification.

The package owns CR2/CR3 request classification, source-backed planning, and
bounded final-emission seams for proven golden-write shapes.  Broader RAW
surfaces stay behind typed blockers rather than treating RAW bytes as generic
metadata blobs.
"""

from __future__ import annotations

from exifmodern.formats.canon_raw.final_emission import (
    CanonRawFinalEmissionPlan,
    plan_canon_raw_final_emission,
)
from exifmodern.formats.canon_raw.metadata_writer import (
    CanonRawUnsupportedWriteError,
    require_supported_canon_raw_rewrite,
)
from exifmodern.formats.canon_raw.write_plan import (
    CanonRawWriteRequestClassification,
    CanonRawWriteRequestReport,
    CanonRawWriteTagClassification,
    build_canon_raw_write_request_report,
    classify_canon_raw_golden_request_file,
    classify_canon_raw_golden_request_payload,
    write_canon_raw_write_request_report,
)

__all__ = [
    "CanonRawFinalEmissionPlan",
    "CanonRawUnsupportedWriteError",
    "CanonRawWriteRequestClassification",
    "CanonRawWriteRequestReport",
    "CanonRawWriteTagClassification",
    "build_canon_raw_write_request_report",
    "classify_canon_raw_golden_request_file",
    "classify_canon_raw_golden_request_payload",
    "plan_canon_raw_final_emission",
    "require_supported_canon_raw_rewrite",
    "write_canon_raw_write_request_report",
]
