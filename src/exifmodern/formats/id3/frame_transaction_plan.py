"""Source-backed ID3 frame transaction and database planning.

This module models ExifTool's ID3 read-time responsibilities without mutating
files.  It validates ID3v2 and ID3v1 containers, walks ID3v2 frame headers,
routes frames through an ExifTool-shaped frame database, preserves unknown
frames in the plan, and exposes explicit gates before identity-only emission.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ID3V2_HEADER_SIZE = 10
ID3V1_TRAILER_SIZE = 128
ID3V1_MARKER = b"TAG"
ID3V2_MARKER = b"ID3"

type Id3VersionName = Literal["ID3v1", "ID3v2_2", "ID3v2_3", "ID3v2_4"]
type Id3FrameRouteKind = Literal[
    "text",
    "user_defined_text",
    "comment",
    "url",
    "user_defined_url",
    "picture",
    "private",
    "subdirectory",
    "binary",
    "counter",
    "popularimeter",
    "ownership",
    "relative_volume",
    "known_preserve",
    "version_mismatch_preserve",
    "unknown_preserve",
]
type Id3FrameActionKind = Literal["parse", "preserve"]
type Id3FrameSizeEncoding = Literal["id3v2_2_24bit", "uint32", "syncsafe", "uint32_fallback"]
type Id3BinaryPreservationKind = Literal["unknown_frame_payload"]
type Id3EmissionGateCode = Literal[
    "no_id3_metadata",
    "truncated_id3v2_header",
    "invalid_id3v2_header_size",
    "unsupported_id3v2_version",
    "truncated_id3v2_payload",
    "id3v2_header_unsynchronization",
    "id3v2_extended_header",
    "id3v2_footer",
    "truncated_id3v2_extended_header",
    "invalid_id3v2_extended_header_size",
    "truncated_id3v2_frame_header",
    "truncated_id3v2_frame_payload",
    "invalid_id3v2_frame_size",
    "id3v2_frame_unsynchronization",
    "identity_emission_only",
]

ID3_SYNCSAFE_SOURCE = "id3.syncsafe_size"
ID3_HEADER_SOURCE = "id3.header"
ID3_BLOCKER_SOURCE = "id3.container_blockers"
ID3V1_TABLE_SOURCE = "id3.v1_table"
ID3V1_TRAILER_SOURCE = "id3.v1_trailer"
ID3V2_2_TABLE_SOURCE = "id3.v2_2_table"
ID3V2_COMMON_TABLE_SOURCE = "id3.v2_common_table"
ID3V2_4_TABLE_SOURCE = "id3.v2_4_table"
ID3_FRAME_TRAVERSAL_SOURCE = "id3.frame_traversal"
ID3_FRAME_ROUTING_SOURCE = "id3.frame_routing"
ID3_PRIVATE_SOURCE = "id3.private_frame"
ID3_UNKNOWN_FRAME_SOURCE = "id3.unknown_frame"

ID3_FRAME_TRANSACTION_SOURCES = (
    ID3_SYNCSAFE_SOURCE,
    ID3_HEADER_SOURCE,
    ID3_BLOCKER_SOURCE,
    ID3V1_TABLE_SOURCE,
    ID3V1_TRAILER_SOURCE,
    ID3V2_2_TABLE_SOURCE,
    ID3V2_COMMON_TABLE_SOURCE,
    ID3V2_4_TABLE_SOURCE,
    ID3_FRAME_TRAVERSAL_SOURCE,
    ID3_FRAME_ROUTING_SOURCE,
    ID3_PRIVATE_SOURCE,
    ID3_UNKNOWN_FRAME_SOURCE,
)

_V2_2_FRAME_TAGS: dict[str, str] = {
    "CNT": "PlayCounter",
    "COM": "Comment",
    "IPL": "InvolvedPeople",
    "PIC": "Picture",
    "POP": "Popularimeter",
    "SLT": "SynLyrics",
    "TAL": "Album",
    "TBP": "BeatsPerMinute",
    "TCM": "Composer",
    "TCO": "Genre",
    "TCP": "Compilation",
    "TCR": "Copyright",
    "TDA": "Date",
    "TEN": "EncodedBy",
    "TLA": "Language",
    "TP1": "Artist",
    "TP2": "Band",
    "TPA": "PartOfSet",
    "TRK": "Track",
    "TT1": "Grouping",
    "TT2": "Title",
    "TXX": "UserDefinedText",
    "TYE": "Year",
    "ULT": "Lyrics",
    "WAF": "FileURL",
    "WAR": "ArtistURL",
    "WCP": "CopyrightURL",
    "WPB": "PublisherURL",
    "WXX": "UserDefinedURL",
    "RVA": "RelativeVolumeAdjustment",
    "GP1": "Grouping",
    "MVI": "MovementNumber",
    "MVN": "MovementName",
    "ITU": "iTunesU",
    "PCS": "Podcast",
}
_V2_COMMON_FRAME_TAGS: dict[str, str] = {
    "APIC": "Picture",
    "COMM": "Comment",
    "GEOB": "GeneralEncapsulatedObject",
    "MCDI": "MusicCDIdentifier",
    "OWNE": "Ownership",
    "PCNT": "PlayCounter",
    "POPM": "Popularimeter",
    "PRIV": "Private",
    "SYLT": "SynLyrics",
    "TALB": "Album",
    "TBPM": "BeatsPerMinute",
    "TCMP": "Compilation",
    "TCOM": "Composer",
    "TCON": "Genre",
    "TCOP": "Copyright",
    "TENC": "EncodedBy",
    "TEXT": "Lyricist",
    "TIT1": "Grouping",
    "TIT2": "Title",
    "TIT3": "Subtitle",
    "TPE1": "Artist",
    "TPE2": "Band",
    "TPOS": "PartOfSet",
    "TPUB": "Publisher",
    "TRCK": "Track",
    "TSRC": "ISRC",
    "TSSE": "EncoderSettings",
    "TXXX": "UserDefinedText",
    "USER": "TermsOfUse",
    "USLT": "Lyrics",
    "WCOM": "CommercialURL",
    "WCOP": "CopyrightURL",
    "WOAF": "FileURL",
    "WOAR": "ArtistURL",
    "WOAS": "SourceURL",
    "WORS": "InternetRadioStationURL",
    "WPAY": "PaymentURL",
    "WPUB": "PublisherURL",
    "WXXX": "UserDefinedURL",
    "ITNU": "iTunesU",
    "PCST": "Podcast",
    "WFED": "PodcastURL",
    "GRP1": "Grouping",
    "MVIN": "MovementNumber",
    "MVNM": "MovementName",
}
_V2_3_ONLY_FRAME_TAGS: dict[str, str] = {
    "IPLS": "InvolvedPeople",
    "TDAT": "Date",
    "TIME": "Time",
    "TORY": "OriginalReleaseYear",
    "TRDA": "RecordingDates",
    "TSIZ": "Size",
    "TYER": "Year",
}
_V2_4_ONLY_FRAME_TAGS: dict[str, str] = {
    "RVA2": "RelativeVolumeAdjustment",
    "TDEN": "EncodingTime",
    "TDOR": "OriginalReleaseTime",
    "TDRC": "RecordingTime",
    "TDRL": "ReleaseTime",
    "TDTG": "TaggingTime",
    "TIPL": "InvolvedPeople",
    "TMCL": "MusicianCredits",
    "TMOO": "Mood",
    "TPRO": "ProducedNotice",
    "TSOA": "AlbumSortOrder",
    "TSOP": "PerformerSortOrder",
    "TSOT": "TitleSortOrder",
    "TSST": "SetSubtitle",
}
_BINARY_FRAME_IDS = frozenset(("MCDI", "ITNU", "PCST", "ITU", "PCS"))
_SUBDIRECTORY_FRAME_IDS = frozenset(("GEOB", "SLT", "SYLT"))


@dataclass(frozen=True)
class Id3FrameDefinitionPlan:
    frame_id: str
    tag_name: str
    versions: tuple[Id3VersionName, ...]
    route_kind: Id3FrameRouteKind
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Id3FrameDatabasePlan:
    version_name: Id3VersionName
    frame_id_width: int
    frame_header_size: int
    definitions: tuple[Id3FrameDefinitionPlan, ...]
    unknown_frames_preserved: bool
    evidence_ids: tuple[str, ...]

    def definition_for(self, frame_id: str) -> Id3FrameDefinitionPlan | None:
        for definition in self.definitions:
            if definition.frame_id == frame_id:
                return definition
        return None


@dataclass(frozen=True)
class Id3FrameRoutingPlan:
    frame_id: str
    tag_name: str
    route_kind: Id3FrameRouteKind
    action: Id3FrameActionKind
    valid_for_version: bool
    known_in_other_version: bool
    unknown_preserved: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Id3UnknownFrameBinaryPreservationPlan:
    frame_id: str
    sanitized_frame_id: str
    tag_name: str
    payload_offset: int
    payload_size: int
    payload: bytes
    value_kind: Id3BinaryPreservationKind
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Id3FrameFlagPlan:
    compression: bool
    encryption: bool
    group_identity: bool
    unsynchronization: bool
    data_length_indicator: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Id3FramePlan:
    index: int
    frame_id: str
    header_offset: int
    payload_offset: int
    payload_size: int
    encoded_size: int
    size_encoding: Id3FrameSizeEncoding
    raw_flags: int
    flags: Id3FrameFlagPlan
    routing: Id3FrameRoutingPlan
    binary_preservation: Id3UnknownFrameBinaryPreservationPlan | None
    evidence_ids: tuple[str, ...]

    @property
    def end_offset(self) -> int:
        return self.payload_offset + self.payload_size


@dataclass(frozen=True)
class Id3v2HeaderPlan:
    present: bool
    major_version: int | None
    revision: int | None
    version_name: Id3VersionName | None
    flags: int
    tag_size: int | None
    payload_offset: int | None
    payload_size: int | None
    payload_end_offset: int | None
    has_unsynchronization: bool
    has_extended_header: bool
    has_footer: bool
    extended_header_size: int | None
    frame_data_offset: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Id3v1FieldPlan:
    name: str
    value_offset: int
    value_size: int
    value: bytes
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Id3v1TrailerPlan:
    present: bool
    offset: int | None
    fields: tuple[Id3v1FieldPlan, ...]
    evidence_ids: tuple[str, ...]

    def field(self, name: str) -> Id3v1FieldPlan | None:
        for field in self.fields:
            if field.name == name:
                return field
        return None


@dataclass(frozen=True)
class Id3EmissionGate:
    code: Id3EmissionGateCode
    passed: bool
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Id3FrameTransactionPlan:
    input_size: int
    id3v2_header: Id3v2HeaderPlan
    id3v2_database: Id3FrameDatabasePlan | None
    id3v2_frames: tuple[Id3FramePlan, ...]
    id3v1_trailer: Id3v1TrailerPlan
    output_emission_gates: tuple[Id3EmissionGate, ...]
    output_data: bytes | None
    evidence_ids: tuple[str, ...] = ID3_FRAME_TRANSACTION_SOURCES

    @property
    def can_emit(self) -> bool:
        return all(gate.passed for gate in self.output_emission_gates)

    @property
    def failed_gates(self) -> tuple[Id3EmissionGate, ...]:
        return tuple(gate for gate in self.output_emission_gates if not gate.passed)

    @property
    def frame_routes(self) -> tuple[Id3FrameRouteKind, ...]:
        return tuple(frame.routing.route_kind for frame in self.id3v2_frames)

    @property
    def unknown_binary_preservations(self) -> tuple[Id3UnknownFrameBinaryPreservationPlan, ...]:
        return tuple(
            frame.binary_preservation
            for frame in self.id3v2_frames
            if frame.binary_preservation is not None
        )

    def emit(self) -> bytes:
        if self.output_data is None or not self.can_emit:
            failed = ", ".join(gate.code for gate in self.failed_gates)
            raise Id3FrameTransactionBlocked(f"ID3 frame transaction cannot be emitted: {failed}")
        return self.output_data


class Id3FrameTransactionBlocked(ValueError):
    """Raised when an ID3 frame transaction is not emit-able."""


def decode_id3_syncsafe_size(raw_size: bytes) -> int | None:
    """Decode ExifTool's ID3 syncsafe integer shape."""

    if len(raw_size) != 4:
        return None
    value = int.from_bytes(raw_size, "big")
    if value & 0x80808080:
        return None
    return (
        (value & 0x0000007F)
        | ((value & 0x00007F00) >> 1)
        | ((value & 0x007F0000) >> 2)
        | ((value & 0x7F000000) >> 3)
    )


def build_id3_frame_transaction_plan(data: bytes) -> Id3FrameTransactionPlan:
    return plan_id3_frame_transaction(data)


def plan_id3_frame_transaction(data: bytes) -> Id3FrameTransactionPlan:
    gates: list[Id3EmissionGate] = []
    id3v2_header, header_gates = _parse_id3v2_header(data)
    gates.extend(header_gates)

    database: Id3FrameDatabasePlan | None = None
    frames: tuple[Id3FramePlan, ...] = ()
    id3v2_payload_available = (
        id3v2_header.payload_end_offset is not None and id3v2_header.payload_end_offset <= len(data)
    )
    if id3v2_header.present and id3v2_header.version_name is not None and id3v2_payload_available:
        database = build_id3_frame_database_plan(id3v2_header.version_name)
        frames, frame_gates = _scan_id3v2_frames(data, id3v2_header, database)
        gates.extend(frame_gates)

    id3v1_trailer = _parse_id3v1_trailer(data)
    if not id3v2_header.present and not id3v1_trailer.present:
        gates.append(
            Id3EmissionGate(
                code="no_id3_metadata",
                passed=False,
                reason=(
                    "source bytes contain neither a leading ID3v2 header nor a trailing ID3v1 TAG"
                ),
                evidence_ids=(ID3_HEADER_SOURCE, ID3V1_TRAILER_SOURCE),
            )
        )

    failed = tuple(gates)
    output_data = data if not failed else None
    if output_data is not None:
        gates.append(
            Id3EmissionGate(
                code="identity_emission_only",
                passed=True,
                reason="planner emission is non-mutating and returns the original byte sequence",
                evidence_ids=(ID3_FRAME_TRAVERSAL_SOURCE, ID3_UNKNOWN_FRAME_SOURCE),
            )
        )

    return Id3FrameTransactionPlan(
        input_size=len(data),
        id3v2_header=id3v2_header,
        id3v2_database=database,
        id3v2_frames=frames,
        id3v1_trailer=id3v1_trailer,
        output_emission_gates=tuple(gates),
        output_data=output_data,
    )


def build_id3_frame_database_plan(version_name: Id3VersionName) -> Id3FrameDatabasePlan:
    frame_id_width = 3 if version_name == "ID3v2_2" else 4
    frame_header_size = 6 if version_name == "ID3v2_2" else 10
    definitions: list[Id3FrameDefinitionPlan] = []
    for frame_id, tag_name in _frame_tags_for_version(version_name).items():
        definitions.append(
            Id3FrameDefinitionPlan(
                frame_id=frame_id,
                tag_name=tag_name,
                versions=_versions_for_frame(frame_id),
                route_kind=_route_kind_for_known_frame(frame_id),
                evidence_ids=_table_sources_for_frame(version_name, frame_id),
            )
        )
    return Id3FrameDatabasePlan(
        version_name=version_name,
        frame_id_width=frame_id_width,
        frame_header_size=frame_header_size,
        definitions=tuple(definitions),
        unknown_frames_preserved=True,
        evidence_ids=_database_sources_for_version(version_name),
    )


def _parse_id3v2_header(data: bytes) -> tuple[Id3v2HeaderPlan, tuple[Id3EmissionGate, ...]]:
    gates: list[Id3EmissionGate] = []
    if not data.startswith(ID3V2_MARKER):
        return (
            Id3v2HeaderPlan(
                present=False,
                major_version=None,
                revision=None,
                version_name=None,
                flags=0,
                tag_size=None,
                payload_offset=None,
                payload_size=None,
                payload_end_offset=None,
                has_unsynchronization=False,
                has_extended_header=False,
                has_footer=False,
                extended_header_size=None,
                frame_data_offset=None,
                evidence_ids=(ID3_HEADER_SOURCE,),
            ),
            (),
        )
    if len(data) < ID3V2_HEADER_SIZE:
        return (
            Id3v2HeaderPlan(
                present=True,
                major_version=None,
                revision=None,
                version_name=None,
                flags=0,
                tag_size=None,
                payload_offset=None,
                payload_size=None,
                payload_end_offset=None,
                has_unsynchronization=False,
                has_extended_header=False,
                has_footer=False,
                extended_header_size=None,
                frame_data_offset=None,
                evidence_ids=(ID3_HEADER_SOURCE,),
            ),
            (
                Id3EmissionGate(
                    code="truncated_id3v2_header",
                    passed=False,
                    reason="leading ID3 marker is not followed by the complete 10-byte header",
                    evidence_ids=(ID3_HEADER_SOURCE,),
                ),
            ),
        )

    major_version = data[3]
    revision = data[4]
    flags = data[5]
    tag_size = decode_id3_syncsafe_size(data[6:10])
    version_name = _version_name_from_major(major_version)
    if tag_size is None:
        gates.append(
            Id3EmissionGate(
                code="invalid_id3v2_header_size",
                passed=False,
                reason="ID3v2 header size is not a valid syncsafe integer",
                evidence_ids=(ID3_HEADER_SOURCE, ID3_SYNCSAFE_SOURCE),
            )
        )
    if version_name is None:
        gates.append(
            Id3EmissionGate(
                code="unsupported_id3v2_version",
                passed=False,
                reason=f"ID3v2.{major_version}.{revision} is not supported by ExifTool ID3.pm",
                evidence_ids=(ID3_HEADER_SOURCE,),
            )
        )

    payload_offset = ID3V2_HEADER_SIZE if tag_size is not None else None
    payload_end_offset = ID3V2_HEADER_SIZE + tag_size if tag_size is not None else None
    if payload_end_offset is not None and payload_end_offset > len(data):
        gates.append(
            Id3EmissionGate(
                code="truncated_id3v2_payload",
                passed=False,
                reason="ID3v2 declared payload size extends beyond the source bytes",
                evidence_ids=(ID3_HEADER_SOURCE,),
            )
        )

    has_unsynchronization = bool(flags & 0x80)
    has_extended_header = bool(flags & 0x40)
    has_footer = bool(flags & 0x10)
    if has_unsynchronization:
        gates.append(
            Id3EmissionGate(
                code="id3v2_header_unsynchronization",
                passed=False,
                reason="global ID3v2 unsynchronization is parsed but not emitted by this planner",
                evidence_ids=(ID3_BLOCKER_SOURCE,),
            )
        )
    if has_extended_header:
        gates.append(
            Id3EmissionGate(
                code="id3v2_extended_header",
                passed=False,
                reason="ID3v2 extended headers are an explicit non-mutating emission blocker",
                evidence_ids=(ID3_BLOCKER_SOURCE,),
            )
        )
    if has_footer:
        gates.append(
            Id3EmissionGate(
                code="id3v2_footer",
                passed=False,
                reason="ID3v2 footers are an explicit non-mutating emission blocker",
                evidence_ids=(ID3_BLOCKER_SOURCE,),
            )
        )

    extended_header_size, frame_data_offset, ext_gates = _extended_header_plan(
        data, payload_offset, payload_end_offset, has_extended_header
    )
    gates.extend(ext_gates)

    return (
        Id3v2HeaderPlan(
            present=True,
            major_version=major_version,
            revision=revision,
            version_name=version_name,
            flags=flags,
            tag_size=tag_size,
            payload_offset=payload_offset,
            payload_size=tag_size,
            payload_end_offset=payload_end_offset,
            has_unsynchronization=has_unsynchronization,
            has_extended_header=has_extended_header,
            has_footer=has_footer,
            extended_header_size=extended_header_size,
            frame_data_offset=frame_data_offset,
            evidence_ids=(ID3_HEADER_SOURCE, ID3_BLOCKER_SOURCE, ID3_SYNCSAFE_SOURCE),
        ),
        tuple(gates),
    )


def _extended_header_plan(
    data: bytes,
    payload_offset: int | None,
    payload_end_offset: int | None,
    has_extended_header: bool,
) -> tuple[int | None, int | None, tuple[Id3EmissionGate, ...]]:
    if payload_offset is None:
        return None, None, ()
    if not has_extended_header:
        return None, payload_offset, ()
    if payload_end_offset is None or payload_offset + 4 > min(payload_end_offset, len(data)):
        return (
            None,
            None,
            (
                Id3EmissionGate(
                    code="truncated_id3v2_extended_header",
                    passed=False,
                    reason="extended header flag is set but no four-byte length is available",
                    evidence_ids=(ID3_BLOCKER_SOURCE,),
                ),
            ),
        )
    extended_header_size = decode_id3_syncsafe_size(data[payload_offset : payload_offset + 4])
    if extended_header_size is None:
        return (
            None,
            None,
            (
                Id3EmissionGate(
                    code="invalid_id3v2_extended_header_size",
                    passed=False,
                    reason="extended header length is not a valid syncsafe integer",
                    evidence_ids=(ID3_BLOCKER_SOURCE, ID3_SYNCSAFE_SOURCE),
                ),
            ),
        )
    frame_data_offset = payload_offset + extended_header_size
    if payload_end_offset is not None and frame_data_offset > payload_end_offset:
        return (
            extended_header_size,
            None,
            (
                Id3EmissionGate(
                    code="truncated_id3v2_extended_header",
                    passed=False,
                    reason="extended header length extends beyond the ID3v2 payload",
                    evidence_ids=(ID3_BLOCKER_SOURCE,),
                ),
            ),
        )
    return extended_header_size, frame_data_offset, ()


def _scan_id3v2_frames(
    data: bytes,
    header: Id3v2HeaderPlan,
    database: Id3FrameDatabasePlan,
) -> tuple[tuple[Id3FramePlan, ...], tuple[Id3EmissionGate, ...]]:
    if header.frame_data_offset is None or header.payload_end_offset is None:
        return (), ()
    offset = header.frame_data_offset
    end_offset = min(header.payload_end_offset, len(data))
    frames: list[Id3FramePlan] = []
    gates: list[Id3EmissionGate] = []
    while offset < end_offset:
        if offset + database.frame_header_size > end_offset:
            if data[offset:end_offset].strip(b"\x00"):
                gates.append(
                    Id3EmissionGate(
                        code="truncated_id3v2_frame_header",
                        passed=False,
                        reason=(
                            "non-padding bytes remain after the final complete ID3v2 frame header"
                        ),
                        evidence_ids=(ID3_FRAME_TRAVERSAL_SOURCE,),
                    )
                )
            break
        payload_size: int | None
        if database.version_name == "ID3v2_2":
            frame_id_bytes = data[offset : offset + 3]
            if frame_id_bytes == b"\x00\x00\x00":
                break
            frame_id = frame_id_bytes.decode("latin-1")
            payload_size = int.from_bytes(data[offset + 3 : offset + 6], "big")
            raw_flags = 0
            size_encoding: Id3FrameSizeEncoding = "id3v2_2_24bit"
        else:
            frame_id_bytes = data[offset : offset + 4]
            if frame_id_bytes == b"\x00\x00\x00\x00":
                break
            frame_id = frame_id_bytes.decode("latin-1")
            payload_size, size_encoding = _decode_v23_v24_frame_size(
                data[offset + 4 : offset + 8], database.version_name
            )
            raw_flags = int.from_bytes(data[offset + 8 : offset + 10], "big")
            if payload_size is None:
                gates.append(
                    Id3EmissionGate(
                        code="invalid_id3v2_frame_size",
                        passed=False,
                        reason=f"frame {frame_id!r} does not contain a valid syncsafe size",
                        evidence_ids=(ID3_FRAME_TRAVERSAL_SOURCE, ID3_SYNCSAFE_SOURCE),
                    )
                )
                break

        payload_offset = offset + database.frame_header_size
        if payload_offset + payload_size > end_offset:
            gates.append(
                Id3EmissionGate(
                    code="truncated_id3v2_frame_payload",
                    passed=False,
                    reason=f"frame {frame_id!r} payload extends beyond the ID3v2 tag payload",
                    evidence_ids=(ID3_FRAME_TRAVERSAL_SOURCE,),
                )
            )
            break

        flags = _decode_frame_flags(raw_flags, database.version_name)
        if flags.unsynchronization:
            gates.append(
                Id3EmissionGate(
                    code="id3v2_frame_unsynchronization",
                    passed=False,
                    reason=f"frame {frame_id!r} uses per-frame unsynchronization",
                    evidence_ids=(ID3_FRAME_ROUTING_SOURCE, ID3_BLOCKER_SOURCE),
                )
            )
        routing = route_id3_frame(database, frame_id)
        binary_preservation = _unknown_frame_binary_preservation_plan(
            data, frame_id, payload_offset, payload_size, routing
        )
        frames.append(
            Id3FramePlan(
                index=len(frames),
                frame_id=frame_id,
                header_offset=offset,
                payload_offset=payload_offset,
                payload_size=payload_size,
                encoded_size=database.frame_header_size + payload_size,
                size_encoding=size_encoding,
                raw_flags=raw_flags,
                flags=flags,
                routing=routing,
                binary_preservation=binary_preservation,
                evidence_ids=(ID3_FRAME_TRAVERSAL_SOURCE, *routing.evidence_ids),
            )
        )
        offset = payload_offset + payload_size
    return tuple(frames), tuple(gates)


def route_id3_frame(database: Id3FrameDatabasePlan, frame_id: str) -> Id3FrameRoutingPlan:
    definition = database.definition_for(frame_id)
    if definition is not None:
        return Id3FrameRoutingPlan(
            frame_id=frame_id,
            tag_name=definition.tag_name,
            route_kind=definition.route_kind,
            action="parse",
            valid_for_version=True,
            known_in_other_version=False,
            unknown_preserved=False,
            evidence_ids=(*definition.evidence_ids, ID3_FRAME_ROUTING_SOURCE),
        )

    other_definition = _definition_in_other_version(database.version_name, frame_id)
    if other_definition is not None:
        return Id3FrameRoutingPlan(
            frame_id=frame_id,
            tag_name=other_definition.tag_name,
            route_kind="version_mismatch_preserve",
            action="preserve",
            valid_for_version=False,
            known_in_other_version=True,
            unknown_preserved=False,
            evidence_ids=(*other_definition.evidence_ids, ID3_UNKNOWN_FRAME_SOURCE),
        )

    return Id3FrameRoutingPlan(
        frame_id=frame_id,
        tag_name=f"ID3_{sanitize_unknown_id3_frame_id(frame_id)}",
        route_kind="unknown_preserve",
        action="preserve",
        valid_for_version=False,
        known_in_other_version=False,
        unknown_preserved=True,
        evidence_ids=(ID3_UNKNOWN_FRAME_SOURCE,),
    )


def _unknown_frame_binary_preservation_plan(
    data: bytes,
    frame_id: str,
    payload_offset: int,
    payload_size: int,
    routing: Id3FrameRoutingPlan,
) -> Id3UnknownFrameBinaryPreservationPlan | None:
    if routing.route_kind != "unknown_preserve" or not routing.unknown_preserved:
        return None
    sanitized_frame_id = sanitize_unknown_id3_frame_id(frame_id)
    return Id3UnknownFrameBinaryPreservationPlan(
        frame_id=frame_id,
        sanitized_frame_id=sanitized_frame_id,
        tag_name=f"ID3_{sanitized_frame_id}",
        payload_offset=payload_offset,
        payload_size=payload_size,
        payload=data[payload_offset : payload_offset + payload_size],
        value_kind="unknown_frame_payload",
        evidence_ids=(ID3_UNKNOWN_FRAME_SOURCE, ID3_FRAME_ROUTING_SOURCE),
    )


def _parse_id3v1_trailer(data: bytes) -> Id3v1TrailerPlan:
    if len(data) < ID3V1_TRAILER_SIZE or data[-ID3V1_TRAILER_SIZE:-125] != ID3V1_MARKER:
        return Id3v1TrailerPlan(
            present=False,
            offset=None,
            fields=(),
            evidence_ids=(ID3V1_TRAILER_SOURCE, ID3V1_TABLE_SOURCE),
        )
    offset = len(data) - ID3V1_TRAILER_SIZE
    trailer = data[offset:]
    fields = [
        Id3v1FieldPlan("Title", offset + 3, 30, trailer[3:33], (ID3V1_TABLE_SOURCE,)),
        Id3v1FieldPlan("Artist", offset + 33, 30, trailer[33:63], (ID3V1_TABLE_SOURCE,)),
        Id3v1FieldPlan("Album", offset + 63, 30, trailer[63:93], (ID3V1_TABLE_SOURCE,)),
        Id3v1FieldPlan("Year", offset + 93, 4, trailer[93:97], (ID3V1_TABLE_SOURCE,)),
        Id3v1FieldPlan("Comment", offset + 97, 30, trailer[97:127], (ID3V1_TABLE_SOURCE,)),
    ]
    if trailer[125] == 0 and trailer[126] != 0:
        fields.append(
            Id3v1FieldPlan("Track", offset + 125, 2, trailer[125:127], (ID3V1_TABLE_SOURCE,))
        )
    fields.append(Id3v1FieldPlan("Genre", offset + 127, 1, trailer[127:128], (ID3V1_TABLE_SOURCE,)))
    return Id3v1TrailerPlan(
        present=True,
        offset=offset,
        fields=tuple(fields),
        evidence_ids=(ID3V1_TRAILER_SOURCE, ID3V1_TABLE_SOURCE),
    )


def _decode_v23_v24_frame_size(
    raw_size: bytes, version_name: Id3VersionName
) -> tuple[int | None, Id3FrameSizeEncoding]:
    value = int.from_bytes(raw_size, "big")
    if version_name == "ID3v2_4" and value > 0x7F and not value & 0x80808080:
        return decode_id3_syncsafe_size(raw_size), "syncsafe"
    if version_name == "ID3v2_4" and value & 0x80808080:
        return value, "uint32_fallback"
    return value, "uint32"


def _decode_frame_flags(raw_flags: int, version_name: Id3VersionName) -> Id3FrameFlagPlan:
    if version_name == "ID3v2_4":
        return Id3FrameFlagPlan(
            compression=bool(raw_flags & 0x08),
            encryption=bool(raw_flags & 0x04),
            group_identity=bool(raw_flags & 0x40),
            unsynchronization=bool(raw_flags & 0x02),
            data_length_indicator=bool(raw_flags & 0x01),
            evidence_ids=(ID3_FRAME_ROUTING_SOURCE,),
        )
    if version_name == "ID3v2_3":
        return Id3FrameFlagPlan(
            compression=bool(raw_flags & 0x80),
            encryption=bool(raw_flags & 0x40),
            group_identity=bool(raw_flags & 0x20),
            unsynchronization=False,
            data_length_indicator=False,
            evidence_ids=(ID3_FRAME_ROUTING_SOURCE,),
        )
    return Id3FrameFlagPlan(
        compression=False,
        encryption=False,
        group_identity=False,
        unsynchronization=False,
        data_length_indicator=False,
        evidence_ids=(ID3_FRAME_TRAVERSAL_SOURCE,),
    )


def _version_name_from_major(major_version: int) -> Id3VersionName | None:
    if major_version == 2:
        return "ID3v2_2"
    if major_version == 3:
        return "ID3v2_3"
    if major_version == 4:
        return "ID3v2_4"
    return None


def _frame_tags_for_version(version_name: Id3VersionName) -> dict[str, str]:
    if version_name == "ID3v2_2":
        return dict(_V2_2_FRAME_TAGS)
    if version_name == "ID3v2_3":
        return _V2_COMMON_FRAME_TAGS | _V2_3_ONLY_FRAME_TAGS
    if version_name == "ID3v2_4":
        return _V2_COMMON_FRAME_TAGS | _V2_4_ONLY_FRAME_TAGS
    return {}


def _versions_for_frame(frame_id: str) -> tuple[Id3VersionName, ...]:
    versions: list[Id3VersionName] = []
    for version_name in ("ID3v2_2", "ID3v2_3", "ID3v2_4"):
        if frame_id in _frame_tags_for_version(version_name):
            versions.append(version_name)
    return tuple(versions)


def _database_sources_for_version(version_name: Id3VersionName) -> tuple[str, ...]:
    if version_name == "ID3v2_2":
        return (ID3V2_2_TABLE_SOURCE, ID3_FRAME_ROUTING_SOURCE)
    if version_name == "ID3v2_3":
        return (ID3V2_COMMON_TABLE_SOURCE, ID3_FRAME_ROUTING_SOURCE)
    if version_name == "ID3v2_4":
        return (ID3V2_COMMON_TABLE_SOURCE, ID3V2_4_TABLE_SOURCE, ID3_FRAME_ROUTING_SOURCE)
    return (ID3V1_TABLE_SOURCE,)


def _table_sources_for_frame(version_name: Id3VersionName, frame_id: str) -> tuple[str, ...]:
    if version_name == "ID3v2_2":
        return (ID3V2_2_TABLE_SOURCE,)
    if frame_id in _V2_4_ONLY_FRAME_TAGS:
        return (ID3V2_4_TABLE_SOURCE,)
    return (ID3V2_COMMON_TABLE_SOURCE,)


def _route_kind_for_known_frame(frame_id: str) -> Id3FrameRouteKind:
    if frame_id in ("TXX", "TXXX"):
        return "user_defined_text"
    if frame_id.startswith("T") or frame_id in ("IPL", "IPLS", "GP1", "GRP1", "MVI", "MVN"):
        return "text"
    if frame_id in ("WXX", "WXXX"):
        return "user_defined_url"
    if frame_id.startswith("W"):
        return "url"
    if frame_id in ("COM", "COMM", "ULT", "USLT", "USER"):
        return "comment"
    if frame_id in ("PIC", "APIC"):
        return "picture"
    if frame_id == "PRIV":
        return "private"
    if frame_id in ("CNT", "PCNT"):
        return "counter"
    if frame_id in ("POP", "POPM"):
        return "popularimeter"
    if frame_id == "OWNE":
        return "ownership"
    if frame_id in ("RVA", "RVAD", "RVA2"):
        return "relative_volume"
    if frame_id in _SUBDIRECTORY_FRAME_IDS:
        return "subdirectory"
    if frame_id in _BINARY_FRAME_IDS:
        return "binary"
    return "known_preserve"


def _definition_in_other_version(
    version_name: Id3VersionName, frame_id: str
) -> Id3FrameDefinitionPlan | None:
    for other_version in ("ID3v2_2", "ID3v2_3", "ID3v2_4"):
        if other_version == version_name:
            continue
        database = build_id3_frame_database_plan(other_version)
        definition = database.definition_for(frame_id)
        if definition is not None:
            return definition
    return None


def sanitize_unknown_id3_frame_id(frame_id: str) -> str:
    sanitized = "".join(char for char in frame_id if char in _UNKNOWN_FRAME_ID_SAFE_CHARS)
    return sanitized or "unknown"


_UNKNOWN_FRAME_ID_SAFE_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)
