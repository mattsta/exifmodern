"""Ogg Opus stream transaction planner public API."""

from exifmodern.formats.opus.stream_transaction_plan import (
    OpusRewriteRequest,
    OpusStreamTransactionPlan,
    build_opus_stream_transaction_plan,
)

__all__ = (
    "OpusRewriteRequest",
    "OpusStreamTransactionPlan",
    "build_opus_stream_transaction_plan",
)

# No SIGNATURES export: Opus is a codec inside Ogg containers; dispatch via ogg.
