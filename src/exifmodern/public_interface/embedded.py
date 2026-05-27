"""Public extract-embedded read-output contracts."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.json_types import JsonObject, JsonValue
from exifmodern.provenance.public_interface import (
    PUBLIC_EVIDENCE_JSON_KEY,
    public_evidence_requested,
    public_evidence_values,
)

PUBLIC_EXTRACT_EMBEDDED_BYTE_RANGE_TAGS: tuple[str, ...] = (
    "EmbeddedVideo",
    "EmbeddedJPG",
    "EmbeddedPNG",
)
PUBLIC_EXTRACT_EMBEDDED_BYTE_RANGE_SOURCES: tuple[str, ...] = (
    "jpeg-extractembedded-trailer-embedded-video",
)
PUBLIC_EXTRACT_EMBEDDED_BYTE_RANGE_SOURCE_PREFIXES: tuple[str, ...] = ("bmp-extra:",)
PUBLIC_EXTRACT_EMBEDDED_BOUNDED_TIMED_RECORD_SOURCE_PREFIXES: tuple[str, ...] = (
    "riff-reader:SGLT:",
    "riff-reader:SLLT:",
    "riff-reader:gps0:",
    "riff-reader:gsen:",
)
PUBLIC_EXTRACT_EMBEDDED_RECURSIVE_SENSITIVE_TAGS: tuple[str, ...] = ("EmbeddedVideo",)
PUBLIC_EXTRACT_EMBEDDED_QUICKTIME_RECURSIVE_BLOCKER = (
    "quicktime_embedded_video_recursive_dispatch_deferred"
)
PUBLIC_EXTRACT_EMBEDDED_BOUNDED_TIMED_RECORD_CATEGORY = "bounded_timed_metadata_records"
PUBLIC_EXTRACT_EMBEDDED_UNSAFE_MEDIA_RECURSION_CATEGORY = "unsafe_media_stream_recursion"

PUBLIC_EXTRACT_EMBEDDED_RECURSIVE_EVIDENCE_IDS: tuple[str, ...] = (
    "public.extract-embedded.ee-option",
    "public.extract-embedded.ee-docs",
    "public.extract-embedded.jpeg-trailer-tag",
    "public.extract-embedded.jpeg-trailer-read",
    "public.extract-embedded.embedded-video-extra",
    "public.extract-embedded.bmp-extra-tags",
    "public.extract-embedded.bmp-extra-emit",
)
PUBLIC_EXTRACT_EMBEDDED_QUICKTIME_EVIDENCE_IDS: tuple[str, ...] = (
    "public.extract-embedded.quicktime.saved-atoms",
    "public.extract-embedded.quicktime.stream-loader",
    "public.extract-embedded.quicktime.unknown-gate",
    "public.extract-embedded.quicktime.timed-stream",
    "public.extract-embedded.quicktime.meta-keys",
)
PUBLIC_EXTRACT_EMBEDDED_BOUNDED_TIMED_EVIDENCE_IDS: tuple[str, ...] = (
    "public.extract-embedded.riff-fixed-timed",
    "public.extract-embedded.quicktime-stream-fixed-timed",
    "public.extract-embedded.garmin-fit-records",
)


@dataclass(frozen=True)
class PublicEmbeddedTraversalDecision:
    code: str
    blocking: bool
    reason: str
    evidence_ids: tuple[str, ...]
    performance_boundary: str
    embedded_payload_byte_count: int

    def to_json_value(self, *, include_evidence: bool = False, **options: JsonValue) -> JsonObject:
        payload: JsonObject = {
            "code": self.code,
            "blocking": self.blocking,
            "reason": self.reason,
            "performance_boundary": self.performance_boundary,
            "embedded_payload_byte_count": self.embedded_payload_byte_count,
        }
        if public_evidence_requested(include_evidence, options):
            payload[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(self.evidence_ids))
        return payload


@dataclass(frozen=True)
class PublicExtractEmbeddedCategory:
    code: str
    safe_for_release: bool
    reason: str
    evidence_ids: tuple[str, ...]
    performance_boundary: str

    def to_json_value(self, *, include_evidence: bool = False, **options: JsonValue) -> JsonObject:
        payload: JsonObject = {
            "code": self.code,
            "safe_for_release": self.safe_for_release,
            "reason": self.reason,
            "performance_boundary": self.performance_boundary,
        }
        if public_evidence_requested(include_evidence, options):
            payload[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(self.evidence_ids))
        return payload


def public_extract_embedded_requires_recursive_traversal(
    extract_embedded_level: int,
) -> bool:
    return extract_embedded_level > 1


def public_embedded_byte_range_source_is_safe(tag_name: str, source: str) -> bool:
    if tag_name not in PUBLIC_EXTRACT_EMBEDDED_BYTE_RANGE_TAGS:
        return False
    if source in PUBLIC_EXTRACT_EMBEDDED_BYTE_RANGE_SOURCES:
        return True
    return any(
        source.startswith(prefix) for prefix in PUBLIC_EXTRACT_EMBEDDED_BYTE_RANGE_SOURCE_PREFIXES
    )


def public_embedded_bounded_timed_record_source_is_safe(source: str) -> bool:
    return any(
        source.startswith(prefix)
        for prefix in PUBLIC_EXTRACT_EMBEDDED_BOUNDED_TIMED_RECORD_SOURCE_PREFIXES
    )


def public_embedded_tag_requires_recursive_traversal(tag_name: str) -> bool:
    return tag_name in PUBLIC_EXTRACT_EMBEDDED_RECURSIVE_SENSITIVE_TAGS


def public_extract_embedded_bounded_timed_record_category() -> PublicExtractEmbeddedCategory:
    return PublicExtractEmbeddedCategory(
        code=PUBLIC_EXTRACT_EMBEDDED_BOUNDED_TIMED_RECORD_CATEGORY,
        safe_for_release=True,
        reason=(
            "Fixed-size timed records inside an already-bounded RIFF chunk or "
            "declared Garmin FIT data section may be iterated for ExtractEmbedded "
            "without scanning arbitrary media payload bytes."
        ),
        evidence_ids=PUBLIC_EXTRACT_EMBEDDED_BOUNDED_TIMED_EVIDENCE_IDS,
        performance_boundary=(
            "Only iterate records when the enclosing reader owns the byte range and "
            "the source defines a fixed record size or declared data-section limit."
        ),
    )


def public_extract_embedded_unsafe_media_recursion_category() -> PublicExtractEmbeddedCategory:
    return PublicExtractEmbeddedCategory(
        code=PUBLIC_EXTRACT_EMBEDDED_UNSAFE_MEDIA_RECURSION_CATEGORY,
        safe_for_release=False,
        reason=(
            "QuickTime/H264 -ee2/-ee3 recursion depends on saved sample-table atoms, "
            "avcC state, and potentially scanning media streams, so it is not a "
            "generic recursive parse of embedded media bytes."
        ),
        evidence_ids=PUBLIC_EXTRACT_EMBEDDED_QUICKTIME_EVIDENCE_IDS,
        performance_boundary=(
            "Require a random-access bounded QuickTime reader that can walk sample "
            "tables and skip mdat/media payloads before enabling this path."
        ),
    )


def public_embedded_video_recursive_traversal_decision(
    extract_embedded_level: int,
    embedded_payload_byte_count: int,
) -> PublicEmbeddedTraversalDecision | None:
    if not public_extract_embedded_requires_recursive_traversal(extract_embedded_level):
        return None
    return PublicEmbeddedTraversalDecision(
        code=PUBLIC_EXTRACT_EMBEDDED_QUICKTIME_RECURSIVE_BLOCKER,
        blocking=True,
        reason=(
            "JPEG Trailer EmbeddedVideo is a bounded binary trailer tag. ExifTool's "
            "QuickTime -ee2/-ee3 behavior is stream traversal driven by saved MP4 "
            "sample-table atoms and H264 avcC state, not a generic recursive parse "
            "of every EmbeddedVideo byte range."
        ),
        evidence_ids=PUBLIC_EXTRACT_EMBEDDED_QUICKTIME_EVIDENCE_IDS,
        performance_boundary=(
            "Do not dispatch recursive QuickTime/H264 parsing until the read graph "
            "can pass a bounded byte range to a path-independent QuickTime reader "
            "that skips media payloads such as mdat."
        ),
        embedded_payload_byte_count=embedded_payload_byte_count,
    )


def public_embedded_traversal_decision_message(
    decision: PublicEmbeddedTraversalDecision,
) -> str:
    return (
        f"{decision.code}: {decision.reason} "
        f"embedded_payload_byte_count={decision.embedded_payload_byte_count}; "
        f"performance_boundary={decision.performance_boundary}"
    )
