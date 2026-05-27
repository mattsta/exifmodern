"""AIFF adapters for the shared read graph contract."""

from __future__ import annotations

import io
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from exifmodern.formats.aiff.chunk_transaction_plan import (
    AIFF_CHUNK_ENUMERATION_SOURCE,
    AIFF_CHUNK_HEADER_SIZE,
    AIFF_COMMENT_SOURCE,
    AIFF_COMMON_SOURCE,
    AIFF_FILE_TYPES,
    AIFF_FORM_HEADER_SIZE,
    AIFF_FORM_SIGNATURE,
    AIFF_FORMAT_VERSION_SOURCE,
    AIFF_MAIN_TABLE_SOURCE,
    AIFF_TEXT_METADATA_SOURCE,
    ANNOTATION_CHUNK_ID,
    APPLICATION_DATA_CHUNK_ID,
    AUTHOR_CHUNK_ID,
    COPYRIGHT_CHUNK_ID,
    ID3_CHUNK_ID,
    NAME_CHUNK_ID,
    SOUND_DATA_CHUNK_ID,
    AiffChunkPlan,
    AiffFileType,
    AiffTerminalTagPlan,
    ascii_chunk_id,
    terminal_tags_for_aiff_chunk,
)
from exifmodern.formats.id3.frame_transaction_plan import build_id3_frame_transaction_plan
from exifmodern.formats.id3.read_graph_adapter import (
    id3_frame_transaction_plan_diagnostics,
    id3_graph_tags,
)
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance, TagValue

AIFF_MAX_MODELED_PAYLOAD_BYTES = 100_000_000

AIFF_FILE_TYPE_SOURCE = "aiff.file_type"
AIFF_FILE_TYPE_DATABASE_SOURCE = "aiff.file_type_database"
AIFF_MIME_SOURCE = "aiff.mime"
AIFF_ID3_SIZE_SOURCE = "aiff.id3_size"


class AiffReadable(Protocol):
    def read(self, size: int = -1) -> bytes: ...

    def seek(self, offset: int, whence: int = 0) -> int: ...


def is_aiff_prefix(data: bytes) -> bool:
    """Return whether bytes satisfy ExifTool's FORM/AIFF/AIFC gate."""

    return len(data) >= AIFF_FORM_HEADER_SIZE and _file_type(data) is not None


def build_aiff_read_graph_from_file(
    path: Path,
    *,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    with path.open("rb") as file:
        return _build_aiff_read_graph(
            file,
            source_file=source_file,
            actual_file_size=path.stat().st_size,
            generated_at_epoch=generated_at_epoch,
        )


def build_aiff_read_graph(
    data: bytes,
    *,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    return _build_aiff_read_graph(
        io.BytesIO(data),
        source_file=source_file,
        actual_file_size=len(data),
        generated_at_epoch=generated_at_epoch,
    )


def _build_aiff_read_graph(
    reader: AiffReadable,
    *,
    source_file: str,
    actual_file_size: int,
    generated_at_epoch: int | None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    header = reader.read(AIFF_FORM_HEADER_SIZE)
    file_type = _file_type(header)
    if file_type is None:
        return ReadGraph(
            schema_version=1,
            generated_at_epoch=epoch,
            source_file=source_file,
            tags=[],
            diagnostics=["AIFF package-local reader status: unsupported_header"],
        )

    declared_size = int.from_bytes(header[4:8], "big")
    declared_file_size = declared_size + 8
    readable_end = min(declared_file_size, actual_file_size)
    diagnostics = _header_diagnostics(declared_file_size, actual_file_size)
    tags = _file_type_tags(file_type)
    scalar_values: dict[str, int | float] = {}
    offset = AIFF_FORM_HEADER_SIZE
    empty_chunk_run = 0
    chunk_index = 0

    while offset < readable_end:
        reader.seek(offset)
        header_data = reader.read(AIFF_CHUNK_HEADER_SIZE)
        if len(header_data) < AIFF_CHUNK_HEADER_SIZE:
            diagnostics.append(
                "AIFF package-local reader diagnostic: truncated_aiff_chunk_header: "
                f"chunk header at offset {offset} is incomplete."
            )
            break

        chunk_id = header_data[:4]
        payload_length = int.from_bytes(header_data[4:8], "big")
        padded_length = payload_length + (payload_length & 1)
        payload_offset = offset + AIFF_CHUNK_HEADER_SIZE
        payload_end = payload_offset + payload_length
        padded_end = payload_offset + padded_length
        if payload_end > actual_file_size:
            diagnostics.append(
                "AIFF package-local reader diagnostic: truncated_aiff_chunk_payload: "
                f"chunk {ascii_chunk_id(chunk_id)} declares {payload_length} bytes."
            )
            break
        if padded_end > actual_file_size:
            diagnostics.append(
                "AIFF package-local reader diagnostic: missing_odd_chunk_padding: "
                f"chunk {ascii_chunk_id(chunk_id)} has no padding byte."
            )
            break
        if payload_length == 0:
            empty_chunk_run += 1
            if empty_chunk_run >= 100:
                diagnostics.append(
                    "AIFF package-local reader diagnostic: too_many_empty_chunks: "
                    "ExifTool aborts after 100 empty chunks."
                )
                break
        else:
            empty_chunk_run = 0

        payload = _read_modeled_payload(
            reader,
            chunk_id,
            payload_offset,
            payload_length,
            diagnostics,
        )
        if payload is not None:
            chunk = AiffChunkPlan(
                index=chunk_index,
                chunk_id=chunk_id,
                chunk_start_offset=offset,
                payload_offset=payload_offset,
                payload_length=payload_length,
                payload_end_offset=payload_end,
                padding_length=payload_length & 1,
                padding_byte=_padding_byte(reader, payload_end, payload_length),
                padded_end_offset=padded_end,
                payload=payload,
                evidence_ids=(AIFF_CHUNK_ENUMERATION_SOURCE,),
            )
            if chunk.chunk_id == ID3_CHUNK_ID:
                tags.extend(_id3_chunk_tags(chunk, diagnostics))
            tags.extend(_text_metadata_tags(chunk))
            tags.extend(_application_data_tags(chunk, diagnostics))
            chunk_terminal_tags = terminal_tags_for_aiff_chunk(chunk)
            tags.extend(_terminal_read_tags(list(chunk_terminal_tags), diagnostics))
            for terminal_tag in chunk_terminal_tags:
                if terminal_tag.status == "parsed" and isinstance(
                    terminal_tag.rendered_value, int | float
                ):
                    scalar_values[terminal_tag.tag_name] = terminal_tag.rendered_value

        offset = padded_end
        chunk_index += 1

    duration = _duration_value(scalar_values)
    if duration is not None:
        tags.append(
            _composite_tag(
                "Duration",
                _duration_text(duration),
                "AIFF-Duration",
                AIFF_MAIN_TABLE_SOURCE,
            )
        )
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=tags,
        diagnostics=diagnostics,
    )


def _file_type(data: bytes) -> AiffFileType | None:
    if len(data) < AIFF_FORM_HEADER_SIZE:
        return None
    if not data.startswith(AIFF_FORM_SIGNATURE) or data[8:12] not in AIFF_FILE_TYPES:
        return None
    if data[8:12] == b"AIFF":
        return "AIFF"
    return "AIFC"


def _header_diagnostics(declared_file_size: int, actual_file_size: int) -> list[str]:
    if declared_file_size == actual_file_size:
        return []
    return [
        "AIFF package-local reader diagnostic: form_size_mismatch: "
        f"FORM declares {declared_file_size} bytes; file has {actual_file_size} bytes."
    ]


def _read_modeled_payload(
    reader: AiffReadable,
    chunk_id: bytes,
    payload_offset: int,
    payload_length: int,
    diagnostics: list[str],
) -> bytes | None:
    if chunk_id in {
        b"FVER",
        b"COMM",
        b"COMT",
        NAME_CHUNK_ID,
        AUTHOR_CHUNK_ID,
        COPYRIGHT_CHUNK_ID,
        ANNOTATION_CHUNK_ID,
        APPLICATION_DATA_CHUNK_ID,
        ID3_CHUNK_ID,
    }:
        if payload_length > AIFF_MAX_MODELED_PAYLOAD_BYTES:
            diagnostics.append(
                "AIFF package-local reader diagnostic: skipped_large_modeled_chunk: "
                f"chunk {ascii_chunk_id(chunk_id)} declares {payload_length} bytes."
            )
            return None
        reader.seek(payload_offset)
        payload = reader.read(payload_length)
        if len(payload) != payload_length:
            diagnostics.append(
                "AIFF package-local reader diagnostic: truncated_modeled_chunk_read: "
                f"chunk {ascii_chunk_id(chunk_id)} could not be fully read."
            )
            return None
        return payload
    if chunk_id == SOUND_DATA_CHUNK_ID:
        diagnostics.append(
            "AIFF package-local reader diagnostic: sound_data_payload_skipped: "
            f"SSND media payload of {payload_length} bytes was skipped."
        )
    return None


def _padding_byte(reader: AiffReadable, payload_end: int, payload_length: int) -> bytes:
    if not payload_length & 1:
        return b""
    reader.seek(payload_end)
    return reader.read(1)


def _text_metadata_tags(chunk: AiffChunkPlan) -> list[ReadTag]:
    if chunk.chunk_id == NAME_CHUNK_ID:
        return [_aiff_tag("Name", _decode_text(chunk.payload), "NAME", AIFF_TEXT_METADATA_SOURCE)]
    if chunk.chunk_id == AUTHOR_CHUNK_ID:
        return [_aiff_tag("Author", _decode_text(chunk.payload), "AUTH", AIFF_TEXT_METADATA_SOURCE)]
    if chunk.chunk_id == COPYRIGHT_CHUNK_ID:
        return [
            _aiff_tag("Copyright", _decode_text(chunk.payload), "(c) ", AIFF_TEXT_METADATA_SOURCE)
        ]
    if chunk.chunk_id == ANNOTATION_CHUNK_ID:
        return [
            _aiff_tag("Annotation", _decode_text(chunk.payload), "ANNO", AIFF_TEXT_METADATA_SOURCE)
        ]
    return []


def _application_data_tags(chunk: AiffChunkPlan, diagnostics: list[str]) -> list[ReadTag]:
    if chunk.chunk_id != APPLICATION_DATA_CHUNK_ID:
        return []
    diagnostics.append(
        "AIFF package-local reader diagnostic: application_data_binary_preserved: "
        f"APPL ApplicationData payload of {chunk.payload_length} bytes was modeled."
    )
    return [
        _aiff_tag(
            "ApplicationData",
            BinaryTagValue(chunk.payload),
            "APPL",
            AIFF_MAIN_TABLE_SOURCE,
        )
    ]


def _id3_chunk_tags(chunk: AiffChunkPlan, diagnostics: list[str]) -> list[ReadTag]:
    plan = build_id3_frame_transaction_plan(chunk.payload)
    diagnostics.extend(
        f"AIFF package-local ID3 diagnostic: {diagnostic}"
        for diagnostic in id3_frame_transaction_plan_diagnostics(plan)
    )
    if not plan.can_emit:
        return []
    return [
        _id3_size_tag(chunk.payload_length),
        *_aiff_id3_tags(id3_graph_tags(plan)),
    ]


def _decode_text(payload: bytes) -> str:
    return payload.rstrip(b"\x00").decode("mac_roman")


def _terminal_read_tags(
    terminal_tags: list[AiffTerminalTagPlan],
    diagnostics: list[str],
) -> list[ReadTag]:
    tags: list[ReadTag] = []
    for terminal_tag in terminal_tags:
        if terminal_tag.status != "parsed":
            diagnostics.append(
                "AIFF package-local reader diagnostic: malformed_terminal_tag: "
                f"{terminal_tag.tag_name}: {terminal_tag.reason}"
            )
            continue
        if terminal_tag.rendered_value is not None:
            value = terminal_tag.rendered_value
            if terminal_tag.kind in {"comment_time", "format_version_time"} and isinstance(
                value, int
            ):
                value = _aiff_time_text(value)
            tags.append(
                _aiff_tag(
                    terminal_tag.tag_name,
                    value,
                    terminal_tag.kind,
                    terminal_tag.evidence_ids[0],
                )
            )
    return tags


def _duration_value(values: dict[str, int | float]) -> float | None:
    sample_rate = values.get("SampleRate")
    frame_count = values.get("NumSampleFrames")
    if sample_rate is None or frame_count is None or sample_rate == 0:
        return None
    return float(frame_count) / float(sample_rate)


def _duration_text(value: float) -> str:
    return f"{value:.2f} s"


def _aiff_time_text(value: int) -> str:
    return datetime.fromtimestamp(value, UTC).strftime("%Y:%m:%d %H:%M:%S")


def _aiff_id3_tags(tags: list[ReadTag]) -> list[ReadTag]:
    converted: list[ReadTag] = []
    for tag in tags:
        if tag.name in {"Track", "Year", "DateTimeOriginal"} and isinstance(tag.value, str):
            integer_value = _integer_text_value(tag.value)
            if integer_value is not None:
                converted.append(replace(tag, value=integer_value))
                continue
        converted.append(tag)
    return converted


def _integer_text_value(value: str) -> int | None:
    if value.isdecimal():
        return int(value)
    return None


def _file_type_tags(file_type: AiffFileType) -> list[ReadTag]:
    extension = "aifc" if file_type == "AIFC" else "aiff"
    return [
        _file_tag("FileType", file_type, "FileType", AIFF_FILE_TYPE_SOURCE),
        _file_tag(
            "FileTypeExtension",
            extension,
            "FileTypeExtension",
            AIFF_FILE_TYPE_DATABASE_SOURCE,
        ),
        _file_tag("MIMEType", "audio/x-aiff", "MIMEType", AIFF_MIME_SOURCE),
    ]


def _file_tag(
    name: str,
    value: TagValue,
    tag_id: str,
    evidence_id: str,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="File",
            table_name="Image::ExifTool::File",
            tag_id=tag_id,
            source=_evidence_id_text(evidence_id),
            family_0_group="File",
            family_1_group="File",
            family_2_group="Other",
        ),
        schema=None,
    )


def _id3_size_tag(value: int) -> ReadTag:
    return ReadTag(
        name="ID3Size",
        value=value,
        provenance=TagProvenance(
            group="File",
            table_name="Image::ExifTool::File",
            tag_id="ID3Size",
            source=_evidence_id_text(AIFF_ID3_SIZE_SOURCE),
            family_0_group="File",
            family_1_group="File",
            family_2_group="Image",
        ),
        schema=None,
    )


def _aiff_tag(
    name: str,
    value: TagValue,
    tag_id: str,
    evidence_id: str,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="AIFF",
            table_name=_table_name(evidence_id),
            tag_id=tag_id,
            source=_evidence_id_text(evidence_id),
            family_0_group="AIFF",
            family_1_group="AIFF",
            family_2_group="Audio",
        ),
        schema=None,
    )


def _composite_tag(
    name: str,
    value: TagValue,
    tag_id: str,
    evidence_id: str,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="Composite",
            table_name="Image::ExifTool::AIFF::Composite",
            tag_id=tag_id,
            source=_evidence_id_text(evidence_id),
            family_0_group="Composite",
            family_1_group="Composite",
            family_2_group="Other",
        ),
        schema=None,
    )


def _table_name(evidence_id: str) -> str:
    if evidence_id == AIFF_COMMON_SOURCE:
        return "Image::ExifTool::AIFF::Common"
    if evidence_id == AIFF_FORMAT_VERSION_SOURCE:
        return "Image::ExifTool::AIFF::FormatVers"
    if evidence_id == AIFF_COMMENT_SOURCE:
        return "Image::ExifTool::AIFF::Comment"
    return "Image::ExifTool::AIFF::Main"


def _evidence_id_text(evidence_id: str) -> str:
    return evidence_id
