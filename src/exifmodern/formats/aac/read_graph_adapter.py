"""AAC/ADTS adapters for the shared read graph contract."""

from __future__ import annotations

import time

from exifmodern.formats.aac.stream_transaction_plan import (
    AAC_ENCODER_SOURCE,
    AAC_TAG_TABLE_SOURCE,
    ADTS_FIXED_HEADER_SIZE,
    AacAdtsHeaderPlan,
    AacEncoderPlan,
    AacStreamTransactionPlan,
    build_aac_stream_transaction_plan,
    parse_adts_header,
)
from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance, TagValue

AAC_MAX_FIRST_FRAME_BYTES = 8191

AAC_FILE_TYPE_SOURCE = "aac.file_type"


def is_aac_prefix(data: bytes) -> bool:
    """Return whether bytes satisfy ExifTool's bounded AAC.pm ADTS gate."""

    if len(data) < ADTS_FIXED_HEADER_SIZE:
        return False
    return parse_adts_header(data).status == "valid"


def aac_first_frame_byte_count(data: bytes) -> int | None:
    """Return the first-frame byte count AAC.pm may read for Encoder inspection."""

    if len(data) < ADTS_FIXED_HEADER_SIZE:
        return None
    header = parse_adts_header(data)
    if header.status != "valid" or header.frame_length is None:
        return None
    return min(header.frame_length, AAC_MAX_FIRST_FRAME_BYTES)


def build_aac_read_graph(
    first_frame_data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    plan = build_aac_stream_transaction_plan(first_frame_data, allow_output_emission=True)
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=_graph_tags(plan),
        diagnostics=_diagnostics(plan),
    )


def _graph_tags(plan: AacStreamTransactionPlan) -> list[ReadTag]:
    if plan.status != "planned" or plan.primary_header is None:
        return []
    tags = [
        _file_tag("FileType", "AAC", "FileType"),
        _file_tag("FileTypeExtension", "aac", "FileTypeExtension"),
        _file_tag("MIMEType", "audio/aac", "MIMEType"),
        *_header_tags(plan.primary_header),
    ]
    if plan.encoder.present and plan.encoder.value is not None:
        tags.append(_encoder_tag(plan.encoder))
    return tags


def _file_tag(name: str, value: TagValue, tag_id: str) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="File",
            table_name="Image::ExifTool::File",
            tag_id=tag_id,
            source=_evidence_id_text(AAC_FILE_TYPE_SOURCE),
            family_0_group="File",
            family_1_group="File",
            family_2_group="Other",
        ),
        schema=None,
    )


def _header_tags(header: AacAdtsHeaderPlan) -> tuple[ReadTag, ...]:
    return (
        _aac_tag("ProfileType", header.profile, "Bit016-017", AAC_TAG_TABLE_SOURCE),
        _aac_tag("SampleRate", header.sample_rate, "Bit018-021", AAC_TAG_TABLE_SOURCE),
        _aac_tag("Channels", _channel_value(header.channels), "Bit023-025", AAC_TAG_TABLE_SOURCE),
    )


def _encoder_tag(encoder: AacEncoderPlan) -> ReadTag:
    return _aac_tag("Encoder", encoder.value, "Encoder", AAC_ENCODER_SOURCE)


def _aac_tag(
    name: str,
    value: TagValue,
    tag_id: str,
    evidence_id: str,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="AAC",
            table_name="Image::ExifTool::AAC::Main",
            tag_id=tag_id,
            source=_evidence_id_text(evidence_id),
            family_0_group="AAC",
            family_1_group="AAC",
            family_2_group="Audio",
        ),
        schema=None,
    )


def _channel_value(value: str | None) -> int | str | None:
    if value is not None and value.isdecimal():
        return int(value)
    return value


def _diagnostics(plan: AacStreamTransactionPlan) -> list[str]:
    diagnostics = [
        f"AAC package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status != "planned":
        diagnostics.insert(0, f"AAC package-local reader status: {plan.status}")
    if plan.frames and plan.frames[0].declared_length is not None:
        diagnostics.append(
            "AAC package-local reader diagnostic: first_frame_only: "
            "AAC.pm ProcessAAC inspects the first frame payload for Encoder and does not "
            "scan later frames for additional AAC tags."
        )
    return diagnostics


def _evidence_id_text(evidence_id: str) -> str:
    return evidence_id
