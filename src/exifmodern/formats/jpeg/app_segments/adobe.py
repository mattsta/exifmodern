"""Adobe APP13/APP14 readers."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_file
from exifmodern.json_types import JsonObject
from exifmodern.public_interface.unknown import (
    ProcessBinaryDataKnownSpan,
    ProcessBinaryDataUnknownReadResult,
    ProcessBinaryDataUnknownReadTag,
    ProcessBinaryDataUnknownTablePolicy,
    process_binarydata_unknown_tags_from_payload,
)

ADOBE_CM_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "jpeg.adobe-cm.main-route",
    "jpeg.adobe-cm.binary-table",
    "jpeg.process-binarydata.unknown-scan",
    "jpeg.process-binarydata.default-tag-prefix",
)
ADOBE_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "jpeg.adobe.main-route",
    "jpeg.adobe.binary-table",
    "jpeg.process-binarydata.unknown-scan",
    "jpeg.process-binarydata.default-tag-prefix",
)
ADOBE_CM_PROCESS_BINARYDATA_UNKNOWN_SOURCE = "jpeg-app13-adobecm-process-binarydata-unknown"
ADOBE_PROCESS_BINARYDATA_UNKNOWN_SOURCE = "jpeg-app14-adobe-process-binarydata-unknown"
_ADOBE_CM_SIGNATURE_SIZE = 8
_ADOBE_SIGNATURE_SIZE = 5
_ADOBE_INT16U_FIELD_SIZE = 2
_ADOBE_CM_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    "JPEG_AdobeCM",
    0,
    _ADOBE_INT16U_FIELD_SIZE,
    (ProcessBinaryDataKnownSpan(start_index=0, entry_count=1),),
    ADOBE_CM_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)
_ADOBE_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    "JPEG_Adobe",
    0,
    _ADOBE_INT16U_FIELD_SIZE,
    (ProcessBinaryDataKnownSpan(start_index=0, entry_count=4),),
    ADOBE_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)

type AdobeProcessBinaryUnknownReadTag = ProcessBinaryDataUnknownReadTag
type AdobeProcessBinaryUnknownReadResult = ProcessBinaryDataUnknownReadResult


def _policy_ids(policy: ProcessBinaryDataUnknownTablePolicy) -> tuple[str, ...]:
    return policy.evidence_ids


def read_adobe_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xEE:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(b"Adobe"):
            continue
        return parse_adobe_payload(payload)
    raise ValueError(f"No JPEG Adobe APP14 segment found: {path}")


def read_adobe_cm_tags(path: Path) -> JsonObject:
    jpeg_file = read_jpeg_file(path)
    data = jpeg_file.data
    for segment in jpeg_file.segments:
        if segment.marker != 0xED:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(b"Adobe_CM"):
            continue
        return parse_adobe_cm_payload(payload)
    raise ValueError(f"No JPEG AdobeCM APP13 segment found: {path}")


def parse_adobe_payload(payload: bytes) -> JsonObject:
    if len(payload) < 12:
        raise ValueError("Truncated JPEG Adobe APP14 segment")
    return {
        "DCTEncodeVersion": int.from_bytes(payload[5:7], "big"),
        "APP14Flags0": adobe_flags(payload[7:9]),
        "APP14Flags1": adobe_flags(payload[9:11]),
        "ColorTransform": adobe_color_transform(payload[11]),
    }


def adobe_flags(raw: bytes) -> str | int:
    value = int.from_bytes(raw, "big")
    if value == 0:
        return "(none)"
    return value


def adobe_color_transform(value: int) -> str | int:
    return {
        0: "Unknown (RGB or CMYK)",
        1: "YCbCr",
        2: "YCCK",
    }.get(value, value)


def parse_adobe_cm_payload(payload: bytes) -> JsonObject:
    if len(payload) < 10:
        raise ValueError("Truncated JPEG AdobeCM APP13 segment")
    return {"AdobeCMType": int.from_bytes(payload[8:10], "big")}


def collect_adobe_cm_process_binary_unknown_read_tags(
    path: Path,
) -> AdobeProcessBinaryUnknownReadResult:
    return _collect_adobe_process_binary_unknown_read_tags(
        path,
        marker=0xED,
        signature=b"Adobe_CM",
        signature_size=_ADOBE_CM_SIGNATURE_SIZE,
        policy=_ADOBE_CM_UNKNOWN_POLICY,
        diagnostic_prefix="JPEG AdobeCM",
    )


def collect_adobe_process_binary_unknown_read_tags(
    path: Path,
) -> AdobeProcessBinaryUnknownReadResult:
    return _collect_adobe_process_binary_unknown_read_tags(
        path,
        marker=0xEE,
        signature=b"Adobe",
        signature_size=_ADOBE_SIGNATURE_SIZE,
        policy=_ADOBE_UNKNOWN_POLICY,
        diagnostic_prefix="JPEG Adobe",
    )


def _collect_adobe_process_binary_unknown_read_tags(
    path: Path,
    *,
    marker: int,
    signature: bytes,
    signature_size: int,
    policy: ProcessBinaryDataUnknownTablePolicy,
    diagnostic_prefix: str,
) -> AdobeProcessBinaryUnknownReadResult:
    try:
        jpeg_file = read_jpeg_file(path)
        segments = jpeg_file.segments
    except ValueError as exc:
        return ProcessBinaryDataUnknownReadResult(
            (),
            (f"{diagnostic_prefix} ProcessBinaryData unknown discovery blocked: {exc}",),
            _policy_ids(policy),
        )
    tags: list[AdobeProcessBinaryUnknownReadTag] = []
    diagnostics: list[str] = []
    data = jpeg_file.data
    for segment in segments:
        if segment.marker != marker:
            continue
        payload = data[segment.payload_offset : segment.payload_offset + segment.payload_length]
        if not payload.startswith(signature):
            continue
        result = process_binarydata_unknown_tags_from_payload(
            payload[signature_size:],
            policy,
        )
        tags.extend(result.tags)
        diagnostics.extend(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                f"{diagnostic_prefix} ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        )
    return ProcessBinaryDataUnknownReadResult(
        tuple(tags),
        tuple(diagnostics),
        _policy_ids(policy),
    )
