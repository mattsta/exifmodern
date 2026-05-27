"""HEIC ItemInformation write-surface classification."""

# No SIGNATURES export: HEIC is dispatched via QuickTime ftyp brand discrimination.

from __future__ import annotations

from exifmodern.formats.heic.item_info_write_plan import (
    HeicItemInfoState,
    HeicItemInfoWriteClassification,
    HeicItemInfoWriteRequestReport,
    HeicItemInfoWriteTagClassification,
    build_heic_item_info_write_request_report,
    classify_heic_item_info_golden_request_file,
    classify_heic_item_info_golden_request_payload,
    parse_heic_item_info_state,
    write_heic_item_info_write_request_report,
)
from exifmodern.formats.heic.metadata_writer import (
    HeicItemInfoUnsupportedWriteError,
    HeicItemInfoXmpRewriteResult,
    require_supported_heic_item_info_rewrite,
    rewrite_heic_item_info_file_xmp_properties,
    rewrite_heic_item_info_xmp_properties,
)

__all__ = [
    "HeicItemInfoState",
    "HeicItemInfoUnsupportedWriteError",
    "HeicItemInfoWriteClassification",
    "HeicItemInfoWriteRequestReport",
    "HeicItemInfoWriteTagClassification",
    "HeicItemInfoXmpRewriteResult",
    "build_heic_item_info_write_request_report",
    "classify_heic_item_info_golden_request_file",
    "classify_heic_item_info_golden_request_payload",
    "parse_heic_item_info_state",
    "require_supported_heic_item_info_rewrite",
    "rewrite_heic_item_info_file_xmp_properties",
    "rewrite_heic_item_info_xmp_properties",
    "write_heic_item_info_write_request_report",
]
