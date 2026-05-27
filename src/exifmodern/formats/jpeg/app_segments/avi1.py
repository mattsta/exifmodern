"""AVI1 APP0 reader."""

from __future__ import annotations

from pathlib import Path

from exifmodern.formats.jpeg.container import read_jpeg_segment_probes_from_source
from exifmodern.json_types import JsonObject
from exifmodern.media_source import FileMediaSource
from exifmodern.public_interface.unknown import (
    ProcessBinaryDataKnownSpan,
    ProcessBinaryDataUnknownReadResult,
    ProcessBinaryDataUnknownReadTag,
    ProcessBinaryDataUnknownTablePolicy,
    process_binarydata_unknown_tags_from_payload,
)

AVI1_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "jpeg.avi1.main-route",
    "jpeg.avi1.binary-table",
    "jpeg.process-binarydata.unknown-scan",
    "jpeg.process-binarydata.default-tag-prefix",
)
AVI1_PROCESS_BINARYDATA_UNKNOWN_SOURCE = "jpeg-app0-avi1-process-binarydata-unknown"
_AVI1_SIGNATURE_SIZE = 4
_AVI1_FIRST_UNKNOWN_INDEX = 1
AVI1_PROCESS_BINARYDATA_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    "JPEG_AVI1",
    0,
    1,
    (ProcessBinaryDataKnownSpan(start_index=0, entry_count=1),),
    AVI1_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)

type Avi1ProcessBinaryUnknownReadTag = ProcessBinaryDataUnknownReadTag
type Avi1ProcessBinaryUnknownReadResult = ProcessBinaryDataUnknownReadResult


def _result_ids(result: ProcessBinaryDataUnknownReadResult) -> tuple[str, ...]:
    return result.evidence_ids


def read_avi1_tags(path: Path) -> JsonObject:
    source = FileMediaSource(path)
    for payload in iter_avi1_payloads(source):
        return parse_avi1_payload(payload)
    raise ValueError(f"No JPEG AVI1 APP0 segment found: {path}")


def iter_avi1_payloads(source: FileMediaSource) -> tuple[bytes, ...]:
    payloads: list[bytes] = []
    for probe in read_jpeg_segment_probes_from_source(source, prefix_length=4):
        if probe.marker != 0xE0 or probe.payload_prefix != b"AVI1":
            continue
        payloads.append(source.read_at(probe.payload_offset, probe.payload_length))
    return tuple(payloads)


def parse_avi1_payload(payload: bytes) -> JsonObject:
    if len(payload) < 5:
        raise ValueError("Truncated JPEG AVI1 APP0 segment")
    return {"InterleavedField": avi1_interleaved_field(payload[4])}


def avi1_interleaved_field(value: int) -> str | int:
    return {
        0: "Not Interleaved",
        1: "Odd",
        2: "Even",
    }.get(value, value)


def collect_avi1_process_binary_unknown_read_tags(
    path: Path,
) -> Avi1ProcessBinaryUnknownReadResult:
    source = FileMediaSource(path)
    try:
        payloads = iter_avi1_payloads(source)
    except ValueError as exc:
        return ProcessBinaryDataUnknownReadResult(
            (),
            (f"JPEG AVI1 ProcessBinaryData unknown discovery blocked: {exc}",),
            AVI1_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    tags: list[Avi1ProcessBinaryUnknownReadTag] = []
    diagnostics: list[str] = []
    for payload in payloads:
        result = avi1_process_binary_unknown_tags_from_payload(payload)
        tags.extend(result.tags)
        diagnostics.extend(result.diagnostics)
    return ProcessBinaryDataUnknownReadResult(
        tuple(tags),
        tuple(diagnostics),
        AVI1_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
    )


def avi1_process_binary_unknown_tags_from_payload(
    payload: bytes,
) -> Avi1ProcessBinaryUnknownReadResult:
    if len(payload) <= _AVI1_SIGNATURE_SIZE + _AVI1_FIRST_UNKNOWN_INDEX:
        return ProcessBinaryDataUnknownReadResult(
            (),
            (),
            AVI1_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    table_data = payload[_AVI1_SIGNATURE_SIZE:]
    result = process_binarydata_unknown_tags_from_payload(
        table_data,
        AVI1_PROCESS_BINARYDATA_UNKNOWN_POLICY,
    )
    return ProcessBinaryDataUnknownReadResult(
        result.tags,
        tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                "JPEG AVI1 ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        _result_ids(result),
    )
