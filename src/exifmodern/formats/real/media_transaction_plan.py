"""Source-backed, non-mutating RealMedia transaction planning.

The planner mirrors the read responsibilities in ExifTool's ``Real.pm``. It
validates RealMedia, RealAudio, RAM, and RPM inputs, routes only the modeled
PROP/MDPR/CONT/RJMD and RA/RAM/RPM surfaces, preserves stream bytes, and keeps
rewrite emission behind explicit gates.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject, JsonValue

REAL_HEADER_SIZE = 8
REAL_CHUNK_HEADER_SIZE = 10
REALMEDIA_SIGNATURE = b".RMF"
REALAUDIO_SIGNATURE = b".ra\xfd"
REALMEDIA_KNOWN_CHUNKS = frozenset((b"PROP", b"MDPR", b"CONT", b"RJMD"))
REALMEDIA_STOP_CHUNK = b"DATA"
REALMEDIA_NULL_CHUNK = b"\x00\x00\x00\x00"
REAL_METADATA_FOOTER_PROBE_SIZE = 140
REAL_ID3V1_SIZE = 128
REAL_METAFILE_URL = re.compile(rb"^[a-z]{3,4}://")
REAL_METAFILE_HTTP_REAL_MEDIA = re.compile(rb"\.(ra|rm|rv|rmvb|smil)$", re.IGNORECASE)

type RealPlanStatus = Literal["planned", "unsupported"]
type RealFileKind = Literal["RM", "RA", "RAM", "RPM"]
type RealChunkRouteKind = Literal[
    "properties",
    "media_properties",
    "content_description",
    "metadata",
    "data_payload_preserved",
    "unknown_preserved",
]
type RealMetafileTag = Literal["txt", "url"]
type RealPropertyFormat = Literal["int32u", "string", "undef"]
type RealMetadataFormat = Literal["string", "int8u", "int32u", "undef"]
type RealAudioScalarFormat = Literal["int16u", "int32u", "string", "undef"]
type RealRewriteOperation = Literal["delete_metadata", "replace_metadata", "insert_metadata"]
type RealEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "unsupported_real_signature",
    "truncated_real_header",
    "invalid_realmedia_header_size",
    "truncated_realmedia_chunk_header",
    "invalid_realmedia_chunk_size",
    "truncated_realmedia_chunk_payload",
    "malformed_real_content_description",
    "malformed_real_properties",
    "malformed_real_metadata",
    "bad_metadata_footer",
    "truncated_realaudio_header",
    "unsupported_realaudio_version",
    "unsupported_metafile_url",
    "real_rewrite_not_implemented",
]

REAL_PM_SOURCE_PATH = "lib/Image/ExifTool/Real.pm"

REAL_PROPERTY_TYPE_SOURCE = "real.property.type"
REAL_METADATA_FORMAT_SOURCE = "real.metadata.format"
REAL_METADATA_FLAG_SOURCE = "real.metadata.flag"
REAL_MEDIA_TABLE_SOURCE = "real.media.table"
REAL_AUDIO_TABLE_SOURCE = "real.audio.table"
REAL_METAFILE_TABLE_SOURCE = "real.metafile.table"
REAL_PROPERTIES_TABLE_SOURCE = "real.properties.table"
REAL_MEDIA_PROPS_TABLE_SOURCE = "real.media.props.table"
REAL_CONTENT_SOURCE = "real.content"
REAL_AUDIO_V3_SOURCE = "real.audio.v3"
REAL_AUDIO_V4_SOURCE = "real.audio.v4"
REAL_AUDIO_V5_SOURCE = "real.audio.v5"
REAL_PROPERTIES_PROCESS_SOURCE = "real.properties.process"
REAL_METADATA_PROCESS_SOURCE = "real.metadata.process"
REAL_PROCESS_SOURCE = "real.process"
REAL_NON_MUTATING_SOURCE = "real.non.mutating"


@dataclass(frozen=True)
class RealRewriteRequest:
    operation: RealRewriteOperation
    tag_name: str
    payload: bytes = b""


@dataclass(frozen=True)
class RealEmissionGate:
    code: RealEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RealChunkPlan:
    index: int
    chunk_id: bytes
    version: int
    chunk_offset: int
    payload_offset: int
    declared_size: int
    payload_length: int
    payload: bytes
    route_kind: RealChunkRouteKind
    evidence_ids: tuple[str, ...]

    @property
    def encoded_bytes(self) -> bytes:
        return (
            self.chunk_id
            + self.declared_size.to_bytes(4, "big")
            + self.version.to_bytes(2, "big")
            + self.payload
        )

    def to_json(self) -> JsonObject:
        return {
            "chunk_id": ascii_bytes(self.chunk_id),
            "chunk_offset": self.chunk_offset,
            "declared_size": self.declared_size,
            "index": self.index,
            "payload_length": self.payload_length,
            "payload_offset": self.payload_offset,
            "route_kind": self.route_kind,
            "version": self.version,
        }


@dataclass(frozen=True)
class RealContentDescriptionPlan:
    chunk_index: int
    title: str | None
    author: str | None
    copyright: str | None
    comment: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RealPropFieldPlan:
    name: str
    format_name: Literal["int16u", "int32u"]
    value: int
    evidence_ids: tuple[str, ...]

    @property
    def rendered_value(self) -> int | float | tuple[str, ...]:
        if self.name in {"Duration", "Preroll"}:
            return self.value / 1000
        if self.name == "Flags":
            return real_flag_names(self.value)
        return self.value


@dataclass(frozen=True)
class RealAudioScalarPlan:
    table_name: str
    tag_name: str
    format_name: RealAudioScalarFormat
    value: JsonValue
    value_offset: int
    value_size: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RealStreamPlan:
    chunk_index: int
    stream_number: int | None
    stream_name: str | None
    mime_type: str | None
    preserved_payload: bytes
    file_info_properties: tuple[RealNameValuePropertyPlan, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RealNameValuePropertyPlan:
    tag: str
    property_type: int
    format_name: RealPropertyFormat
    value_length: int
    value_bytes: bytes
    int_values: tuple[int, ...]
    text_value: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RealMetadataValuePlan:
    tag_path: str
    type_code: int
    flags: int
    flag_names: tuple[str, ...]
    format_name: RealMetadataFormat | None
    value_length: int
    value_bytes: bytes
    int_value: int | None
    text_value: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RealMetadataSurfacePlan:
    chunk_index: int | None
    footer_offset: int | None
    values: tuple[RealMetadataValuePlan, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RealAudioPlan:
    version: int
    pseudo_tag: str
    table_name: str | None
    payload_offset: int
    payload_length: int
    preserved_payload: bytes
    scalars: tuple[RealAudioScalarPlan, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RealMetafileEntryPlan:
    index: int
    tag: RealMetafileTag
    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RealMediaTransactionPlan:
    status: RealPlanStatus
    file_kind: RealFileKind | None
    chunks: tuple[RealChunkPlan, ...]
    content_descriptions: tuple[RealContentDescriptionPlan, ...]
    prop_fields: tuple[RealPropFieldPlan, ...]
    streams: tuple[RealStreamPlan, ...]
    metadata_surfaces: tuple[RealMetadataSurfacePlan, ...]
    audio: RealAudioPlan | None
    metafile_entries: tuple[RealMetafileEntryPlan, ...]
    stream_mime_types: tuple[str, ...]
    output_emission_gates: tuple[RealEmissionGate, ...]
    source_bytes: bytes
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Real media transaction output is gated: {gate_codes}")
        return self.source_bytes

    def to_json(self) -> JsonObject:
        return {
            "audio_scalars": json_strings(audio_scalar_names(self.audio)),
            "can_emit_output": self.can_emit_output,
            "chunk_ids": [ascii_bytes(chunk.chunk_id) for chunk in self.chunks],
            "file_kind": self.file_kind,
            "metafile_tags": [entry.tag for entry in self.metafile_entries],
            "output_emission_gates": json_items(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "status": self.status,
            "stream_mime_types": json_strings(self.stream_mime_types),
        }


def build_real_media_transaction_plan(
    real_data: bytes,
    *,
    file_extension: str | None = None,
    rewrite_request: RealRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> RealMediaTransactionPlan:
    if len(real_data) < REAL_HEADER_SIZE:
        return unsupported_plan(
            real_data,
            None,
            RealEmissionGate(
                "truncated_real_header",
                "Input ended before the Real signature probe could be read.",
                (REAL_PROCESS_SOURCE,),
            ),
        )

    gates: list[RealEmissionGate] = []
    if rewrite_request is not None:
        gates.append(
            RealEmissionGate(
                "real_rewrite_not_implemented",
                (
                    f"Rewrite operation {rewrite_request.operation} for "
                    f"{rewrite_request.tag_name} is not implemented for Real files."
                ),
                (REAL_PROCESS_SOURCE,),
            )
        )
    if not allow_output_emission:
        gates.append(
            RealEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "Real transaction plans do not emit bytes unless explicitly allowed.",
                (REAL_NON_MUTATING_SOURCE,),
            )
        )

    if real_data.startswith(REALMEDIA_SIGNATURE):
        return build_rm_plan(real_data, tuple(gates))
    if real_data.startswith(REALAUDIO_SIGNATURE):
        return build_ra_plan(real_data, tuple(gates))
    if is_real_metafile(real_data):
        return build_metafile_plan(real_data, file_extension, tuple(gates))
    return unsupported_plan(
        real_data,
        None,
        RealEmissionGate(
            "unsupported_real_signature",
            "Input does not start with .RMF, .ra, pnm://, rtsp://, or http://.",
            (REAL_PROCESS_SOURCE,),
        ),
    )


plan_real_media_transaction = build_real_media_transaction_plan


def build_rm_plan(
    real_data: bytes, initial_gates: tuple[RealEmissionGate, ...]
) -> RealMediaTransactionPlan:
    header_size = int.from_bytes(real_data[4:8], "big")
    gates = list(initial_gates)
    if header_size < REAL_HEADER_SIZE or header_size > len(real_data):
        gates.append(
            RealEmissionGate(
                "invalid_realmedia_header_size",
                "The RealMedia header size cannot be used as the chunk traversal start.",
                (REAL_PROCESS_SOURCE,),
            )
        )
        return base_plan("unsupported", "RM", real_data, gates)

    chunks: list[RealChunkPlan] = []
    contents: list[RealContentDescriptionPlan] = []
    prop_fields: list[RealPropFieldPlan] = []
    streams: list[RealStreamPlan] = []
    metadata_surfaces: list[RealMetadataSurfacePlan] = []
    stream_mimes: list[str] = []
    offset = header_size

    while offset < len(real_data):
        if len(real_data) - offset < REAL_CHUNK_HEADER_SIZE:
            gates.append(
                RealEmissionGate(
                    "truncated_realmedia_chunk_header",
                    "Input ended before a complete RealMedia chunk header could be read.",
                    (REAL_PROCESS_SOURCE,),
                )
            )
            break
        chunk_id = real_data[offset : offset + 4]
        if chunk_id == REALMEDIA_NULL_CHUNK:
            break
        declared_size = int.from_bytes(real_data[offset + 4 : offset + 8], "big")
        version = int.from_bytes(real_data[offset + 8 : offset + 10], "big")
        route_kind = route_chunk_id(chunk_id)
        if declared_size & 0x80000000 or declared_size < REAL_CHUNK_HEADER_SIZE:
            gates.append(
                RealEmissionGate(
                    "invalid_realmedia_chunk_size",
                    f"Chunk {ascii_bytes(chunk_id)} has an invalid declared size.",
                    (REAL_PROCESS_SOURCE,),
                )
            )
            break
        payload_offset = offset + REAL_CHUNK_HEADER_SIZE
        payload_end = offset + declared_size
        if payload_end > len(real_data):
            gates.append(
                RealEmissionGate(
                    "truncated_realmedia_chunk_payload",
                    f"Chunk {ascii_bytes(chunk_id)} declares bytes beyond the input end.",
                    (REAL_PROCESS_SOURCE,),
                )
            )
            break
        payload = real_data[payload_offset:payload_end]
        chunk = RealChunkPlan(
            index=len(chunks),
            chunk_id=chunk_id,
            version=version,
            chunk_offset=offset,
            payload_offset=payload_offset,
            declared_size=declared_size,
            payload_length=len(payload),
            payload=payload,
            route_kind=route_kind,
            evidence_ids=chunk_sources(route_kind),
        )
        chunks.append(chunk)
        if route_kind == "content_description":
            content, gate = parse_content_description(chunk)
            contents.append(content)
            if gate is not None:
                gates.append(gate)
        elif route_kind == "properties":
            fields, gate = parse_prop_fields(payload)
            prop_fields.extend(fields)
            if gate is not None:
                gates.append(gate)
        elif route_kind == "media_properties":
            stream, gate = parse_mdpr_stream(chunk)
            streams.append(stream)
            if stream.mime_type and not stream.mime_type.startswith("logical-"):
                stream_mimes.append(stream.mime_type)
            if gate is not None:
                gates.append(gate)
        elif route_kind == "metadata":
            values, gate = parse_real_metadata(payload, dir_start=0, prefix="")
            metadata_surfaces.append(
                RealMetadataSurfacePlan(
                    chunk_index=chunk.index,
                    footer_offset=None,
                    values=values,
                    evidence_ids=(REAL_METADATA_PROCESS_SOURCE,),
                )
            )
            if gate is not None:
                gates.append(gate)
        offset = payload_end
        if chunk_id == REALMEDIA_STOP_CHUNK:
            break

    footer_surface, footer_gate = parse_metadata_footer(real_data)
    if footer_surface is not None:
        metadata_surfaces.append(footer_surface)
    if footer_gate is not None:
        gates.append(footer_gate)

    return RealMediaTransactionPlan(
        status="unsupported" if fatal_gates(tuple(gates)) else "planned",
        file_kind="RM",
        chunks=tuple(chunks),
        content_descriptions=tuple(contents),
        prop_fields=tuple(prop_fields),
        streams=tuple(streams),
        metadata_surfaces=tuple(metadata_surfaces),
        audio=None,
        metafile_entries=(),
        stream_mime_types=tuple(stream_mimes),
        output_emission_gates=unique_gates(tuple(gates)),
        source_bytes=real_data,
        evidence_ids=unique_sources(
            (
                REAL_PROCESS_SOURCE,
                REAL_MEDIA_TABLE_SOURCE,
                REAL_PROPERTIES_TABLE_SOURCE,
                REAL_MEDIA_PROPS_TABLE_SOURCE,
                REAL_CONTENT_SOURCE,
                REAL_METADATA_PROCESS_SOURCE,
                *(source for gate in gates for source in gate.evidence_ids),
            )
        ),
    )


def build_ra_plan(
    real_data: bytes, initial_gates: tuple[RealEmissionGate, ...]
) -> RealMediaTransactionPlan:
    gates = list(initial_gates)
    if len(real_data) < REAL_HEADER_SIZE:
        gates.append(
            RealEmissionGate(
                "truncated_realaudio_header",
                "Input ended before the RealAudio version fields could be read.",
                (REAL_PROCESS_SOURCE,),
            )
        )
        return base_plan("unsupported", "RA", real_data, gates)
    version = int.from_bytes(real_data[4:6], "big")
    table_name = realaudio_table_name(version)
    audio_sources = realaudio_sources(version)
    if table_name is None:
        gates.append(
            RealEmissionGate(
                "unsupported_realaudio_version",
                f"RealAudio pseudo-tag .ra{version} is not modeled by Real.pm.",
                (REAL_AUDIO_TABLE_SOURCE,),
            )
        )
    scalars, scalar_gate = parse_realaudio_scalars(
        version,
        real_data[REAL_HEADER_SIZE:],
        REAL_HEADER_SIZE,
    )
    if scalar_gate is not None:
        gates.append(scalar_gate)
    audio = RealAudioPlan(
        version=version,
        pseudo_tag=f".ra{version}",
        table_name=table_name,
        payload_offset=REAL_HEADER_SIZE,
        payload_length=max(0, len(real_data) - REAL_HEADER_SIZE),
        preserved_payload=real_data[REAL_HEADER_SIZE:],
        scalars=scalars,
        evidence_ids=audio_sources,
    )
    return RealMediaTransactionPlan(
        status="unsupported" if fatal_gates(tuple(gates)) else "planned",
        file_kind="RA",
        chunks=(),
        content_descriptions=(),
        prop_fields=(),
        streams=(),
        metadata_surfaces=(),
        audio=audio,
        metafile_entries=(),
        stream_mime_types=(),
        output_emission_gates=unique_gates(tuple(gates)),
        source_bytes=real_data,
        evidence_ids=unique_sources((REAL_PROCESS_SOURCE, REAL_AUDIO_TABLE_SOURCE, *audio_sources)),
    )


def build_metafile_plan(
    real_data: bytes,
    file_extension: str | None,
    initial_gates: tuple[RealEmissionGate, ...],
) -> RealMediaTransactionPlan:
    gates = list(initial_gates)
    file_kind: RealFileKind = "RPM" if file_extension and file_extension.upper() == "RPM" else "RAM"
    entries: list[RealMetafileEntryPlan] = []
    for raw_line in real_data.splitlines():
        if len(raw_line) > 256:
            break
        if not raw_line:
            continue
        if raw_line.startswith(b"http") and not REAL_METAFILE_HTTP_REAL_MEDIA.search(raw_line):
            gates.append(
                RealEmissionGate(
                    "unsupported_metafile_url",
                    "HTTP RAM/RPM entries must point at a Real media extension.",
                    (REAL_PROCESS_SOURCE,),
                )
            )
            return base_plan("unsupported", file_kind, real_data, gates)
        tag: RealMetafileTag = "url" if REAL_METAFILE_URL.match(raw_line) else "txt"
        entries.append(
            RealMetafileEntryPlan(
                index=len(entries),
                tag=tag,
                text=decode_real_string(raw_line),
                evidence_ids=(REAL_METAFILE_TABLE_SOURCE, REAL_PROCESS_SOURCE),
            )
        )
    return RealMediaTransactionPlan(
        status="planned",
        file_kind=file_kind,
        chunks=(),
        content_descriptions=(),
        prop_fields=(),
        streams=(),
        metadata_surfaces=(),
        audio=None,
        metafile_entries=tuple(entries),
        stream_mime_types=(),
        output_emission_gates=unique_gates(tuple(gates)),
        source_bytes=real_data,
        evidence_ids=unique_sources((REAL_PROCESS_SOURCE, REAL_METAFILE_TABLE_SOURCE)),
    )


def route_chunk_id(chunk_id: bytes) -> RealChunkRouteKind:
    if chunk_id == b"PROP":
        return "properties"
    if chunk_id == b"MDPR":
        return "media_properties"
    if chunk_id == b"CONT":
        return "content_description"
    if chunk_id == b"RJMD":
        return "metadata"
    if chunk_id == REALMEDIA_STOP_CHUNK:
        return "data_payload_preserved"
    return "unknown_preserved"


def chunk_sources(route_kind: RealChunkRouteKind) -> tuple[str, ...]:
    if route_kind == "properties":
        return (REAL_MEDIA_TABLE_SOURCE, REAL_PROPERTIES_TABLE_SOURCE, REAL_PROCESS_SOURCE)
    if route_kind == "media_properties":
        return (REAL_MEDIA_TABLE_SOURCE, REAL_MEDIA_PROPS_TABLE_SOURCE, REAL_PROCESS_SOURCE)
    if route_kind == "content_description":
        return (REAL_MEDIA_TABLE_SOURCE, REAL_CONTENT_SOURCE, REAL_PROCESS_SOURCE)
    if route_kind == "metadata":
        return (REAL_MEDIA_TABLE_SOURCE, REAL_METADATA_PROCESS_SOURCE, REAL_PROCESS_SOURCE)
    return (REAL_PROCESS_SOURCE,)


def parse_content_description(
    chunk: RealChunkPlan,
) -> tuple[RealContentDescriptionPlan, RealEmissionGate | None]:
    values: list[str | None] = []
    pos = 0
    gate: RealEmissionGate | None = None
    for _name in ("Title", "Author", "Copyright", "Comment"):
        if pos + 2 > len(chunk.payload):
            gate = RealEmissionGate(
                "malformed_real_content_description",
                "CONT ended before a length-prefixed text field was complete.",
                (REAL_CONTENT_SOURCE,),
            )
            values.append(None)
            continue
        size = int.from_bytes(chunk.payload[pos : pos + 2], "big")
        pos += 2
        if pos + size > len(chunk.payload):
            gate = RealEmissionGate(
                "malformed_real_content_description",
                "CONT text length extends beyond the chunk payload.",
                (REAL_CONTENT_SOURCE,),
            )
            values.append(None)
            continue
        values.append(decode_real_string(chunk.payload[pos : pos + size]))
        pos += size
    return (
        RealContentDescriptionPlan(
            chunk_index=chunk.index,
            title=values[0],
            author=values[1],
            copyright=values[2],
            comment=values[3],
            evidence_ids=(REAL_CONTENT_SOURCE,),
        ),
        gate,
    )


def parse_realaudio_scalars(
    version: int,
    payload: bytes,
    payload_offset: int,
) -> tuple[tuple[RealAudioScalarPlan, ...], RealEmissionGate | None]:
    if version == 3:
        return parse_realaudio_v3_scalars(payload, payload_offset), None
    if version == 4:
        return parse_realaudio_v4_scalars(payload, payload_offset), None
    if version == 5:
        return parse_realaudio_v5_scalars(payload, payload_offset), None
    return (), None


def parse_realaudio_v3_scalars(
    payload: bytes,
    payload_offset: int,
) -> tuple[RealAudioScalarPlan, ...]:
    scalars: list[RealAudioScalarPlan] = []
    if len(payload) >= 14:
        scalar_specs: tuple[
            tuple[str, int, int, RealAudioScalarFormat],
            ...,
        ] = (
            ("Channels", 0, 2, "int16u"),
            ("BytesPerMinute", 8, 2, "int16u"),
            ("AudioBytes", 10, 4, "int32u"),
        )
        for tag_name, offset, size, format_name in scalar_specs:
            scalars.append(
                real_audio_scalar(
                    "AudioV3",
                    tag_name,
                    format_name,
                    int.from_bytes(payload[offset : offset + size], "big"),
                    payload_offset + offset,
                    size,
                    REAL_AUDIO_V3_SOURCE,
                )
            )
    pos = 14
    for tag_name in ("Title", "Artist", "Copyright", "Comment"):
        if pos >= len(payload):
            break
        size = payload[pos]
        pos += 1
        if pos + size > len(payload):
            break
        scalars.append(
            real_audio_scalar(
                "AudioV3",
                tag_name,
                "string",
                decode_real_string(payload[pos : pos + size]),
                payload_offset + pos,
                size,
                REAL_AUDIO_V3_SOURCE,
            )
        )
        pos += size
    return tuple(scalars)


def parse_realaudio_v4_scalars(
    payload: bytes,
    payload_offset: int,
) -> tuple[RealAudioScalarPlan, ...]:
    specs: tuple[tuple[str, int, int], ...] = (
        ("AudioBytes", 20, 4),
        ("BytesPerMinute", 24, 4),
        ("AudioFrameSize", 34, 2),
        ("SampleRate", 40, 2),
        ("BitsPerSample", 44, 2),
        ("Channels", 46, 2),
    )
    scalars = [
        real_audio_scalar(
            "AudioV4",
            tag_name,
            "int32u" if size == 4 else "int16u",
            int.from_bytes(payload[offset : offset + size], "big"),
            payload_offset + offset,
            size,
            REAL_AUDIO_V4_SOURCE,
        )
        for tag_name, offset, size in specs
        if offset + size <= len(payload)
    ]
    pos = 48
    for _ in range(2):
        if pos >= len(payload):
            return tuple(scalars)
        size = payload[pos]
        pos += 1 + size
    pos += 3
    for tag_name in ("Title", "Artist", "Copyright", "Comment"):
        if pos >= len(payload):
            break
        size = payload[pos]
        pos += 1
        if pos + size > len(payload):
            break
        scalars.append(
            real_audio_scalar(
                "AudioV4",
                tag_name,
                "string",
                decode_real_string(payload[pos : pos + size]),
                payload_offset + pos,
                size,
                REAL_AUDIO_V4_SOURCE,
            )
        )
        pos += size
    return tuple(scalars)


def parse_realaudio_v5_scalars(
    payload: bytes,
    payload_offset: int,
) -> tuple[RealAudioScalarPlan, ...]:
    specs: tuple[tuple[str, int, int], ...] = (
        ("AudioBytes", 18, 4),
        ("BytesPerMinute", 22, 4),
        ("SampleRate", 38, 2),
        ("BitsPerSample", 42, 4),
        ("Channels", 46, 2),
    )
    return tuple(
        real_audio_scalar(
            "AudioV5",
            tag_name,
            "int32u" if size == 4 else "int16u",
            int.from_bytes(payload[offset : offset + size], "big"),
            payload_offset + offset,
            size,
            REAL_AUDIO_V5_SOURCE,
        )
        for tag_name, offset, size in specs
        if offset + size <= len(payload)
    )


def real_audio_scalar(
    table_name: str,
    tag_name: str,
    format_name: RealAudioScalarFormat,
    value: JsonValue,
    value_offset: int,
    value_size: int,
    source: str,
) -> RealAudioScalarPlan:
    return RealAudioScalarPlan(
        table_name=table_name,
        tag_name=tag_name,
        format_name=format_name,
        value=value,
        value_offset=value_offset,
        value_size=value_size,
        evidence_ids=(REAL_AUDIO_TABLE_SOURCE, source),
    )


def parse_prop_fields(
    payload: bytes,
) -> tuple[tuple[RealPropFieldPlan, ...], RealEmissionGate | None]:
    specs: tuple[tuple[str, Literal["int16u", "int32u"], int], ...] = (
        ("MaxBitrate", "int32u", 4),
        ("AvgBitrate", "int32u", 4),
        ("MaxPacketSize", "int32u", 4),
        ("AvgPacketSize", "int32u", 4),
        ("NumPackets", "int32u", 4),
        ("Duration", "int32u", 4),
        ("Preroll", "int32u", 4),
        ("IndexOffset", "int32u", 4),
        ("DataOffset", "int32u", 4),
        ("NumStreams", "int16u", 2),
        ("Flags", "int16u", 2),
    )
    fields: list[RealPropFieldPlan] = []
    pos = 0
    for name, format_name, size in specs:
        if pos + size > len(payload):
            return (
                tuple(fields),
                RealEmissionGate(
                    "malformed_real_properties",
                    "PROP ended before all Real.pm serial fields were available.",
                    (REAL_PROPERTIES_TABLE_SOURCE,),
                ),
            )
        fields.append(
            RealPropFieldPlan(
                name=name,
                format_name=format_name,
                value=int.from_bytes(payload[pos : pos + size], "big"),
                evidence_ids=(REAL_PROPERTIES_TABLE_SOURCE,),
            )
        )
        pos += size
    return tuple(fields), None


def parse_mdpr_stream(chunk: RealChunkPlan) -> tuple[RealStreamPlan, RealEmissionGate | None]:
    payload = chunk.payload
    gate: RealEmissionGate | None = None
    stream_number: int | None = None
    stream_name: str | None = None
    mime_type: str | None = None
    file_info_properties: tuple[RealNameValuePropertyPlan, ...] = ()
    pos = 0
    if len(payload) >= 2:
        stream_number = int.from_bytes(payload[:2], "big")
        pos = 2 + 7 * 4
    else:
        gate = malformed_properties_gate("MDPR ended before StreamNumber.")
    if gate is None and pos + 1 <= len(payload):
        name_len = payload[pos]
        pos += 1
        if pos + name_len <= len(payload):
            stream_name = decode_real_string(payload[pos : pos + name_len])
            pos += name_len
        else:
            gate = malformed_properties_gate("MDPR stream name extends beyond the payload.")
    elif gate is None:
        gate = malformed_properties_gate("MDPR ended before StreamNameLen.")
    if gate is None and pos + 1 <= len(payload):
        mime_len = payload[pos]
        pos += 1
        if pos + mime_len <= len(payload):
            mime_type = decode_real_string(payload[pos : pos + mime_len]).split("\x00", 1)[0]
            pos += mime_len
        else:
            gate = malformed_properties_gate("MDPR stream MIME type extends beyond the payload.")
    elif gate is None:
        gate = malformed_properties_gate("MDPR ended before StreamMimeLen.")
    if gate is None and mime_type == "logical-fileinfo" and pos + 8 <= len(payload):
        file_info_len = int.from_bytes(payload[pos : pos + 4], "big")
        file_info_len_2 = int.from_bytes(payload[pos + 4 : pos + 8], "big")
        pos += 8
        file_info_properties, gate = parse_logical_file_info(
            payload, pos, file_info_len, file_info_len_2
        )
    return (
        RealStreamPlan(
            chunk_index=chunk.index,
            stream_number=stream_number,
            stream_name=stream_name,
            mime_type=mime_type,
            preserved_payload=payload,
            file_info_properties=file_info_properties,
            evidence_ids=(REAL_MEDIA_PROPS_TABLE_SOURCE,),
        ),
        gate,
    )


def parse_logical_file_info(
    payload: bytes,
    pos: int,
    file_info_len: int,
    file_info_len_2: int,
) -> tuple[tuple[RealNameValuePropertyPlan, ...], RealEmissionGate | None]:
    del file_info_len
    if pos + 6 > len(payload):
        return (), malformed_properties_gate(
            "logical-fileinfo ended before version and stream counts."
        )
    pos += 2
    physical_streams = int.from_bytes(payload[pos : pos + 2], "big")
    pos += 2
    physical_bytes = physical_streams * 2 + physical_streams * 4
    if pos + physical_bytes + 2 > len(payload):
        return (), malformed_properties_gate(
            "logical-fileinfo physical stream arrays are truncated."
        )
    pos += physical_bytes
    num_rules = int.from_bytes(payload[pos : pos + 2], "big")
    pos += 2
    map_bytes = num_rules * 2
    if pos + map_bytes + 2 > len(payload):
        return (), malformed_properties_gate("logical-fileinfo rule map is truncated.")
    pos += map_bytes
    pos += 2
    property_length = file_info_len_2 - physical_streams * 6 - num_rules * 2 - 12
    if property_length < 0 or pos + property_length > len(payload):
        return (), malformed_properties_gate(
            "logical-fileinfo property bytes are outside the payload."
        )
    properties, malformed = parse_name_value_properties(payload[pos : pos + property_length])
    return properties, malformed


def parse_name_value_properties(
    payload: bytes,
) -> tuple[tuple[RealNameValuePropertyPlan, ...], RealEmissionGate | None]:
    properties: list[RealNameValuePropertyPlan] = []
    pos = 0
    while pos + 6 <= len(payload):
        start = pos
        size = int.from_bytes(payload[pos : pos + 4], "big")
        version = int.from_bytes(payload[pos + 4 : pos + 6], "big")
        if size < 6:
            return tuple(properties), malformed_properties_gate(
                "Real property size is smaller than its header."
            )
        if start + size > len(payload):
            return tuple(properties), malformed_properties_gate(
                "Real property size extends beyond the payload."
            )
        if version != 0:
            pos = start + size
            continue
        pos += 6
        if pos + 1 > len(payload):
            return tuple(properties), malformed_properties_gate(
                "Real property tag length is truncated."
            )
        tag_len = payload[pos]
        pos += 1
        if pos + tag_len > len(payload):
            return tuple(properties), malformed_properties_gate("Real property tag is truncated.")
        tag = decode_real_string(payload[pos : pos + tag_len])
        pos += tag_len
        if pos + 6 > len(payload):
            return tuple(properties), malformed_properties_gate(
                "Real property type and length are truncated."
            )
        property_type = int.from_bytes(payload[pos : pos + 4], "big")
        value_length = int.from_bytes(payload[pos + 4 : pos + 6], "big")
        pos += 6
        if pos + value_length > len(payload):
            return tuple(properties), malformed_properties_gate("Real property value is truncated.")
        value = payload[pos : pos + value_length]
        format_name = property_format(property_type)
        properties.append(
            RealNameValuePropertyPlan(
                tag=tag,
                property_type=property_type,
                format_name=format_name,
                value_length=value_length,
                value_bytes=value,
                int_values=read_int32_values(value) if format_name == "int32u" else (),
                text_value=decode_real_string(value) if format_name == "string" else None,
                evidence_ids=(REAL_PROPERTY_TYPE_SOURCE, REAL_PROPERTIES_PROCESS_SOURCE),
            )
        )
        pos = start + size
    if pos != len(payload):
        return tuple(properties), malformed_properties_gate(
            "Real property payload has a trailing partial record."
        )
    return tuple(properties), None


def parse_real_metadata(
    payload: bytes,
    *,
    dir_start: int,
    prefix: str,
) -> tuple[tuple[RealMetadataValuePlan, ...], RealEmissionGate | None]:
    values: list[RealMetadataValuePlan] = []
    pos = dir_start
    dir_end = len(payload)
    while True:
        if pos + 28 > dir_end:
            break
        start = pos
        size = int.from_bytes(payload[pos : pos + 4], "big")
        type_code = int.from_bytes(payload[pos + 4 : pos + 8], "big")
        flags = int.from_bytes(payload[pos + 8 : pos + 12], "big")
        value_pos = start + int.from_bytes(payload[pos + 12 : pos + 16], "big")
        sub_prop_pos = start + int.from_bytes(payload[pos + 16 : pos + 20], "big")
        num_sub_props = int.from_bytes(payload[pos + 20 : pos + 24], "big")
        name_len = int.from_bytes(payload[pos + 24 : pos + 28], "big")
        entry_end = start + size
        if entry_end > dir_end or start + 28 + name_len > dir_end:
            return tuple(values), malformed_metadata_gate(
                "Real metadata record extends beyond its directory."
            )
        if value_pos < start + 28 + name_len or value_pos + 4 > dir_end:
            return tuple(values), malformed_metadata_gate("Real metadata value pointer is invalid.")
        tag = decode_real_string(payload[start + 28 : start + 28 + name_len]).split("\x00", 1)[0]
        tag_path = f"{prefix}/{tag}" if prefix else tag
        value_length = int.from_bytes(payload[value_pos : value_pos + 4], "big")
        value_start = value_pos + 4
        value_end = value_start + value_length
        if value_end > dir_end:
            return tuple(values), malformed_metadata_gate(
                "Real metadata value extends beyond its directory."
            )
        format_name = metadata_format(type_code, value_length)
        value_bytes = payload[value_start:value_end]
        values.append(
            RealMetadataValuePlan(
                tag_path=tag_path,
                type_code=type_code,
                flags=flags,
                flag_names=metadata_flag_names(flags),
                format_name=format_name,
                value_length=value_length,
                value_bytes=value_bytes,
                int_value=metadata_int_value(value_bytes, format_name),
                text_value=decode_real_string(value_bytes) if format_name == "string" else None,
                evidence_ids=(
                    REAL_METADATA_FORMAT_SOURCE,
                    REAL_METADATA_FLAG_SOURCE,
                    REAL_METADATA_PROCESS_SOURCE,
                ),
            )
        )
        if num_sub_props:
            sub_dir_start = value_end + num_sub_props * 8
            if sub_prop_pos < start or sub_dir_start > entry_end:
                return tuple(values), malformed_metadata_gate(
                    "Real metadata subproperty pointers are invalid."
                )
            sub_values, gate = parse_real_metadata(
                payload[:entry_end], dir_start=sub_dir_start, prefix=tag_path
            )
            values.extend(sub_values)
            if gate is not None:
                return tuple(values), gate
        pos = entry_end
    if pos != dir_end:
        return tuple(values), malformed_metadata_gate(
            "Real metadata payload has trailing partial bytes."
        )
    return tuple(values), None


def parse_metadata_footer(
    real_data: bytes,
) -> tuple[RealMetadataSurfacePlan | None, RealEmissionGate | None]:
    if len(real_data) < REAL_METADATA_FOOTER_PROBE_SIZE:
        return None, None
    probe_offset = len(real_data) - REAL_METADATA_FOOTER_PROBE_SIZE
    probe = real_data[probe_offset : probe_offset + 12]
    if not probe.startswith(b"RMJE"):
        return None, None
    meta_size = int.from_bytes(probe[8:12], "big")
    meta_offset = len(real_data) - REAL_ID3V1_SIZE - meta_size - 12
    if meta_offset < 0 or meta_offset + meta_size > len(real_data):
        return (
            None,
            RealEmissionGate(
                "bad_metadata_footer",
                "RMJE footer metadata size points outside the input.",
                (REAL_PROCESS_SOURCE,),
            ),
        )
    metadata = real_data[meta_offset : meta_offset + meta_size]
    if not metadata.startswith(b"RJMD"):
        return (
            None,
            RealEmissionGate(
                "bad_metadata_footer",
                "RMJE footer did not point at an RJMD payload.",
                (REAL_PROCESS_SOURCE,),
            ),
        )
    values, gate = parse_real_metadata(metadata, dir_start=8, prefix="")
    return (
        RealMetadataSurfacePlan(
            chunk_index=None,
            footer_offset=meta_offset,
            values=values,
            evidence_ids=(REAL_PROCESS_SOURCE, REAL_METADATA_PROCESS_SOURCE),
        ),
        gate,
    )


def property_format(property_type: int) -> RealPropertyFormat:
    if property_type == 0:
        return "int32u"
    if property_type == 2:
        return "string"
    return "undef"


def metadata_format(type_code: int, value_length: int) -> RealMetadataFormat | None:
    if type_code in {1, 2, 6, 7, 8}:
        return "string"
    if type_code == 3:
        return "int32u" if value_length == 4 else "int8u"
    if type_code == 4:
        return "int32u"
    if type_code == 5:
        return "undef"
    return None


def metadata_int_value(value_bytes: bytes, format_name: RealMetadataFormat | None) -> int | None:
    if format_name == "int8u" and value_bytes:
        return value_bytes[0]
    if format_name == "int32u" and len(value_bytes) >= 4:
        return int.from_bytes(value_bytes[:4], "big")
    return None


def metadata_flag_names(flags: int) -> tuple[str, ...]:
    names: list[str] = []
    if flags & 1:
        names.append("Read Only")
    if flags & 2:
        names.append("Private")
    if flags & 4:
        names.append("Type Descriptor")
    return tuple(names)


def real_flag_names(flags: int) -> tuple[str, ...]:
    names: list[str] = []
    if flags & 1:
        names.append("Allow Recording")
    if flags & 2:
        names.append("Perfect Play")
    if flags & 4:
        names.append("Live")
    if flags & 8:
        names.append("Allow Download")
    return tuple(names)


def audio_scalar_names(audio: RealAudioPlan | None) -> list[str]:
    if audio is None:
        return []
    return [scalar.tag_name for scalar in audio.scalars]


def realaudio_table_name(version: int) -> str | None:
    if version == 3:
        return "AudioV3"
    if version == 4:
        return "AudioV4"
    if version == 5:
        return "AudioV5"
    return None


def realaudio_sources(version: int) -> tuple[str, ...]:
    if version == 3:
        return (REAL_AUDIO_TABLE_SOURCE, REAL_AUDIO_V3_SOURCE)
    if version == 4:
        return (REAL_AUDIO_TABLE_SOURCE, REAL_AUDIO_V4_SOURCE)
    if version == 5:
        return (REAL_AUDIO_TABLE_SOURCE, REAL_AUDIO_V5_SOURCE)
    return (REAL_AUDIO_TABLE_SOURCE,)


def is_real_metafile(real_data: bytes) -> bool:
    return real_data.startswith((b"pnm://", b"rtsp://", b"http://"))


def read_int32_values(value: bytes) -> tuple[int, ...]:
    return tuple(
        int.from_bytes(value[pos : pos + 4], "big")
        for pos in range(0, len(value) - len(value) % 4, 4)
    )


def malformed_properties_gate(reason: str) -> RealEmissionGate:
    return RealEmissionGate("malformed_real_properties", reason, (REAL_PROPERTIES_PROCESS_SOURCE,))


def malformed_metadata_gate(reason: str) -> RealEmissionGate:
    return RealEmissionGate("malformed_real_metadata", reason, (REAL_METADATA_PROCESS_SOURCE,))


def fatal_gates(gates: tuple[RealEmissionGate, ...]) -> bool:
    fatal_codes = {
        "unsupported_real_signature",
        "truncated_real_header",
        "invalid_realmedia_header_size",
        "truncated_realmedia_chunk_header",
        "invalid_realmedia_chunk_size",
        "truncated_realmedia_chunk_payload",
        "malformed_real_content_description",
        "malformed_real_properties",
        "malformed_real_metadata",
        "bad_metadata_footer",
        "truncated_realaudio_header",
        "unsupported_metafile_url",
    }
    return any(gate.code in fatal_codes for gate in gates)


def unsupported_plan(
    source_bytes: bytes,
    file_kind: RealFileKind | None,
    gate: RealEmissionGate,
) -> RealMediaTransactionPlan:
    return base_plan("unsupported", file_kind, source_bytes, [gate])


def base_plan(
    status: RealPlanStatus,
    file_kind: RealFileKind | None,
    source_bytes: bytes,
    gates: list[RealEmissionGate],
) -> RealMediaTransactionPlan:
    return RealMediaTransactionPlan(
        status=status,
        file_kind=file_kind,
        chunks=(),
        content_descriptions=(),
        prop_fields=(),
        streams=(),
        metadata_surfaces=(),
        audio=None,
        metafile_entries=(),
        stream_mime_types=(),
        output_emission_gates=unique_gates(tuple(gates)),
        source_bytes=source_bytes,
        evidence_ids=unique_sources(
            (REAL_PROCESS_SOURCE, *(source for gate in gates for source in gate.evidence_ids))
        ),
    )


def unique_gates(gates: tuple[RealEmissionGate, ...]) -> tuple[RealEmissionGate, ...]:
    seen: set[RealEmissionGateCode] = set()
    result: list[RealEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        result.append(gate)
    return tuple(result)


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for source in sources:
        key = source
        if key in seen:
            continue
        seen.add(key)
        result.append(source)
    return tuple(result)


def evidence_ids_to_json(sources: tuple[str, ...]) -> JsonArray:
    return list(sources)


def json_items(values: Iterable[JsonObject]) -> JsonArray:
    return list(values)


def json_strings(values: Iterable[str]) -> JsonArray:
    return [value for value in values]


def ascii_bytes(value: bytes) -> str:
    if not value:
        return ""
    try:
        return value.decode("ascii")
    except UnicodeDecodeError:
        return value.hex()


def decode_real_string(value: bytes) -> str:
    return "".join(chr(byte) if byte < 0x80 else "?" for byte in value).rstrip("\x00")
