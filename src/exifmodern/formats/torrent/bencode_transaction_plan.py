"""Source-grounded, non-mutating BitTorrent bencode transaction planning.

The planner mirrors ExifTool's Torrent.pm read path: decode bencode integers,
byte strings, lists, and dictionaries; accept only top-level torrent dictionaries
with announce/created-by/info evidence; flatten nested tags with list indices;
and preserve original bytes for emission only behind an explicit gate.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.json_types import JsonArray, JsonObject, JsonValue

BINARY_STRING_LIMIT = 256
TORRENT_INFO_HASH_HEX_LENGTH = 40

type TorrentPlanStatus = Literal["planned", "unsupported"]
type BencodeValueKind = Literal["dictionary", "list", "integer", "string", "binary"]
type TorrentActionKind = Literal[
    "decode_dictionary",
    "decode_list",
    "decode_integer",
    "decode_string",
    "extract_tag",
    "preserve_info_bytes",
    "compute_info_hash",
]
type TorrentOutputGateCode = Literal[
    "empty_input",
    "bad_format",
    "bad_dictionary_key",
    "truncated_byte_string",
    "truncated_container",
    "extra_trailing_data",
    "not_torrent_dictionary",
    "non_mutating_plan_requires_explicit_emission",
]
type TorrentRewriteGateCode = Literal[
    "torrent_writer_not_implemented",
    "bencode_rewrite_not_implemented",
    "info_hash_recalculation_required",
    "raw_info_dict_boundary_required",
]
type TorrentTagTable = Literal["main", "info", "files", "profiles"]

TORRENT_MAIN_SOURCE = "torrent.main"
TORRENT_INFO_SOURCE = "torrent.info"
TORRENT_FILES_SOURCE = "torrent.files"
TORRENT_READ_BENCODE_SOURCE = "torrent.read_bencode"
TORRENT_BYTE_STRING_SOURCE = "torrent.byte_string"
TORRENT_EXTRACT_TAGS_SOURCE = "torrent.extract_tags"
TORRENT_PROCESS_SOURCE = "torrent.process"
TORRENT_NON_MUTATING_SOURCE = "torrent.non_mutating"
TORRENT_INFO_HASH_SOURCE = "torrent.info_hash"

TORRENT_TRANSACTION_SOURCES = (
    TORRENT_MAIN_SOURCE,
    TORRENT_INFO_SOURCE,
    TORRENT_FILES_SOURCE,
    TORRENT_READ_BENCODE_SOURCE,
    TORRENT_BYTE_STRING_SOURCE,
    TORRENT_EXTRACT_TAGS_SOURCE,
    TORRENT_PROCESS_SOURCE,
)


@dataclass(frozen=True)
class TorrentBencodeValuePlan:
    kind: BencodeValueKind
    byte_range: tuple[int, int]
    display_value: JsonValue
    raw_bytes: bytes | None
    byte_size: int | None
    child_count: int | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": json_range(self.byte_range),
            "byte_size": self.byte_size,
            "child_count": self.child_count,
            "display_value": self.display_value,
            "kind": self.kind,
            "raw_bytes_hex": None if self.raw_bytes is None else self.raw_bytes.hex(),
        }


@dataclass(frozen=True)
class TorrentMetadataResponsibility:
    tag_id: str
    generated_name: str
    path_components: tuple[str, ...]
    table: TorrentTagTable
    value: TorrentBencodeValuePlan
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "generated_name": self.generated_name,
            "path_components": list(self.path_components),
            "table": self.table,
            "tag_id": self.tag_id,
            "value": self.value.to_json(),
        }


@dataclass(frozen=True)
class TorrentInfoHashResponsibility:
    info_dict_range: tuple[int, int]
    sha1_hex: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "info_dict_range": json_range(self.info_dict_range),
            "sha1_hex": self.sha1_hex,
        }


@dataclass(frozen=True)
class TorrentRawBoundaryPlan:
    source_range: tuple[int, int]
    top_level_range: tuple[int, int] | None
    info_dict_range: tuple[int, int] | None
    raw_preservation_range: tuple[int, int]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "info_dict_range": json_range(self.info_dict_range),
            "raw_preservation_range": json_range(self.raw_preservation_range),
            "source_range": json_range(self.source_range),
            "top_level_range": json_range(self.top_level_range),
        }


@dataclass(frozen=True)
class TorrentTraversalPlan:
    kind: BencodeValueKind
    path: str
    byte_range: tuple[int, int]
    child_count: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": json_range(self.byte_range),
            "child_count": self.child_count,
            "kind": self.kind,
            "path": self.path,
        }


@dataclass(frozen=True)
class TorrentActionPlan:
    kind: TorrentActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": json_range(self.byte_range),
            "kind": self.kind,
            "reason": self.reason,
            "target": self.target,
        }


@dataclass(frozen=True)
class TorrentOutputEmissionGate:
    code: TorrentOutputGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TorrentRewriteGate:
    code: TorrentRewriteGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TorrentBencodeTransactionPlan:
    status: TorrentPlanStatus
    source_data: bytes
    root_value: TorrentBencodeValuePlan | None
    boundaries: TorrentRawBoundaryPlan
    metadata_responsibilities: tuple[TorrentMetadataResponsibility, ...]
    info_hash: TorrentInfoHashResponsibility | None
    traversal: tuple[TorrentTraversalPlan, ...]
    actions: tuple[TorrentActionPlan, ...]
    rewrite_gates: tuple[TorrentRewriteGate, ...]
    output_emission_gates: tuple[TorrentOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Torrent bencode transaction output is gated: {gate_codes}")
        return self.source_data

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "boundaries": self.boundaries.to_json(),
            "can_emit_output": self.can_emit_output,
            "info_hash": None if self.info_hash is None else self.info_hash.to_json(),
            "metadata_responsibilities": json_object_array(
                responsibility.to_json() for responsibility in self.metadata_responsibilities
            ),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "rewrite_gates": json_object_array(gate.to_json() for gate in self.rewrite_gates),
            "root_value": None if self.root_value is None else self.root_value.to_json(),
            "status": self.status,
            "traversal": json_object_array(item.to_json() for item in self.traversal),
        }


@dataclass(frozen=True)
class _BencodeString:
    raw_bytes: bytes
    byte_range: tuple[int, int]
    value_range: tuple[int, int]
    plan: TorrentBencodeValuePlan


@dataclass(frozen=True)
class _BencodeInteger:
    value: int
    byte_range: tuple[int, int]
    plan: TorrentBencodeValuePlan


@dataclass(frozen=True)
class _BencodeList:
    values: tuple[BencodeNode, ...]
    byte_range: tuple[int, int]
    plan: TorrentBencodeValuePlan


@dataclass(frozen=True)
class _BencodeDictEntry:
    key: _BencodeString
    value: BencodeNode


@dataclass(frozen=True)
class _BencodeDict:
    entries: tuple[_BencodeDictEntry, ...]
    byte_range: tuple[int, int]
    plan: TorrentBencodeValuePlan

    def value_for_key(self, key: bytes) -> BencodeNode | None:
        for entry in self.entries:
            if entry.key.raw_bytes == key:
                return entry.value
        return None


type BencodeNode = _BencodeString | _BencodeInteger | _BencodeList | _BencodeDict


@dataclass(frozen=True)
class _ParseFailure:
    code: TorrentOutputGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class _ParseResult:
    node: BencodeNode | None
    next_offset: int
    failure: _ParseFailure | None


@dataclass(frozen=True)
class _TableTagInfo:
    name: str | None
    subdirectory: TorrentTagTable | None
    join_path: bool
    evidence_ids: tuple[str, ...]


TAG_TABLES: dict[TorrentTagTable, dict[str, _TableTagInfo]] = {
    "main": {
        "announce": _TableTagInfo(None, None, False, (TORRENT_MAIN_SOURCE,)),
        "announce-list": _TableTagInfo("AnnounceList1", None, False, (TORRENT_MAIN_SOURCE,)),
        "comment": _TableTagInfo(None, None, False, (TORRENT_MAIN_SOURCE,)),
        "created by": _TableTagInfo("Creator", None, False, (TORRENT_MAIN_SOURCE,)),
        "creation date": _TableTagInfo("CreateDate", None, False, (TORRENT_MAIN_SOURCE,)),
        "encoding": _TableTagInfo(None, None, False, (TORRENT_MAIN_SOURCE,)),
        "info": _TableTagInfo("Info", "info", False, (TORRENT_MAIN_SOURCE, TORRENT_INFO_SOURCE)),
        "url-list": _TableTagInfo("URLList1", None, False, (TORRENT_MAIN_SOURCE,)),
    },
    "info": {
        "file-duration": _TableTagInfo("File1Duration", None, False, (TORRENT_INFO_SOURCE,)),
        "file-media": _TableTagInfo("File1Media", None, False, (TORRENT_INFO_SOURCE,)),
        "files": _TableTagInfo(
            "Files", "files", False, (TORRENT_INFO_SOURCE, TORRENT_FILES_SOURCE)
        ),
        "length": _TableTagInfo(None, None, False, (TORRENT_INFO_SOURCE,)),
        "md5sum": _TableTagInfo("MD5Sum", None, False, (TORRENT_INFO_SOURCE,)),
        "name": _TableTagInfo(None, None, False, (TORRENT_INFO_SOURCE,)),
        "name.utf-8": _TableTagInfo("NameUTF-8", None, False, (TORRENT_INFO_SOURCE,)),
        "piece length": _TableTagInfo("PieceLength", None, False, (TORRENT_INFO_SOURCE,)),
        "pieces": _TableTagInfo("Pieces", None, False, (TORRENT_INFO_SOURCE,)),
        "private": _TableTagInfo(None, None, False, (TORRENT_INFO_SOURCE,)),
        "profiles": _TableTagInfo("Profiles", "profiles", False, (TORRENT_INFO_SOURCE,)),
    },
    "files": {
        "length": _TableTagInfo("File1Length", None, False, (TORRENT_FILES_SOURCE,)),
        "md5sum": _TableTagInfo("File1MD5Sum", None, False, (TORRENT_FILES_SOURCE,)),
        "path": _TableTagInfo("File1Path", None, True, (TORRENT_FILES_SOURCE,)),
        "path.utf-8": _TableTagInfo("File1PathUTF-8", None, True, (TORRENT_FILES_SOURCE,)),
    },
    "profiles": {
        "width": _TableTagInfo("Profile1Width", None, False, (TORRENT_INFO_SOURCE,)),
        "height": _TableTagInfo("Profile1Height", None, False, (TORRENT_INFO_SOURCE,)),
        "acodec": _TableTagInfo("Profile1AudioCodec", None, False, (TORRENT_INFO_SOURCE,)),
        "vcodec": _TableTagInfo("Profile1VideoCodec", None, False, (TORRENT_INFO_SOURCE,)),
    },
}


def build_torrent_bencode_transaction_plan(
    torrent_data: bytes,
    *,
    allow_output_emission: bool = False,
) -> TorrentBencodeTransactionPlan:
    """Build a source-backed, non-mutating BitTorrent metadata transaction plan."""

    gates: list[TorrentOutputEmissionGate] = []
    actions: list[TorrentActionPlan] = []
    traversal: list[TorrentTraversalPlan] = []
    boundaries = TorrentRawBoundaryPlan(
        source_range=(0, len(torrent_data)),
        top_level_range=None,
        info_dict_range=None,
        raw_preservation_range=(0, len(torrent_data)),
        evidence_ids=(TORRENT_READ_BENCODE_SOURCE,),
    )

    if not torrent_data:
        gates.append(
            output_gate("empty_input", "Bencode input is empty.", (TORRENT_READ_BENCODE_SOURCE,))
        )
        add_non_mutating_gate(gates, allow_output_emission)
        return unsupported_plan(torrent_data, None, boundaries, gates, actions, traversal)

    parser = _BencodeParser(torrent_data)
    result = parser.parse_value(0)
    actions.extend(parser.actions)
    traversal.extend(parser.traversal)
    if result.failure is not None:
        gates.append(
            output_gate(result.failure.code, result.failure.reason, result.failure.evidence_ids)
        )
        add_non_mutating_gate(gates, allow_output_emission)
        return unsupported_plan(torrent_data, None, boundaries, gates, actions, traversal)
    if result.node is None:
        gates.append(
            output_gate(
                "bad_format", "No bencode value was decoded.", (TORRENT_READ_BENCODE_SOURCE,)
            )
        )
        add_non_mutating_gate(gates, allow_output_emission)
        return unsupported_plan(torrent_data, None, boundaries, gates, actions, traversal)
    if result.next_offset != len(torrent_data):
        gates.append(
            output_gate(
                "extra_trailing_data",
                "Bytes remain after the first bencode value.",
                (TORRENT_READ_BENCODE_SOURCE,),
            )
        )

    root = result.node
    boundaries = TorrentRawBoundaryPlan(
        source_range=(0, len(torrent_data)),
        top_level_range=root.plan.byte_range,
        info_dict_range=info_dict_range(root),
        raw_preservation_range=(0, len(torrent_data)),
        evidence_ids=(TORRENT_READ_BENCODE_SOURCE, TORRENT_PROCESS_SOURCE),
    )

    if not isinstance(root, _BencodeDict) or not is_torrent_dictionary(root):
        gates.append(
            output_gate(
                "not_torrent_dictionary",
                (
                    "ProcessTorrent requires a top-level dictionary with announce, "
                    "created by, or info."
                ),
                (TORRENT_PROCESS_SOURCE,),
            )
        )
        add_non_mutating_gate(gates, allow_output_emission)
        return unsupported_plan(torrent_data, root.plan, boundaries, gates, actions, traversal)

    responsibilities = extract_tags(root)
    for responsibility in responsibilities:
        actions.append(
            TorrentActionPlan(
                kind="extract_tag",
                target=responsibility.tag_id,
                byte_range=responsibility.value.byte_range,
                reason="ExifTool ExtractTags handles this scalar metadata value.",
                evidence_ids=responsibility.evidence_ids,
            )
        )

    info_hash = build_info_hash_responsibility(torrent_data, root)
    if info_hash is not None:
        actions.append(
            TorrentActionPlan(
                kind="preserve_info_bytes",
                target="info",
                byte_range=info_hash.info_dict_range,
                reason=(
                    "The raw info dictionary bytes are the preservation boundary "
                    "for info-hash stability."
                ),
                evidence_ids=info_hash.evidence_ids,
            )
        )
        actions.append(
            TorrentActionPlan(
                kind="compute_info_hash",
                target="info-hash",
                byte_range=info_hash.info_dict_range,
                reason=(
                    "SHA-1 over the raw bencoded info dictionary is planned without mutating bytes."
                ),
                evidence_ids=info_hash.evidence_ids,
            )
        )

    add_non_mutating_gate(gates, allow_output_emission)
    status: TorrentPlanStatus = (
        "planned" if not gates or only_non_mutating_gate(gates) else "unsupported"
    )
    evidence_ids = unique_evidence_ids(
        (
            *TORRENT_TRANSACTION_SOURCES,
            *(source for item in responsibilities for source in item.evidence_ids),
            *(source for item in actions for source in item.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return TorrentBencodeTransactionPlan(
        status=status,
        source_data=torrent_data,
        root_value=root.plan,
        boundaries=boundaries,
        metadata_responsibilities=responsibilities,
        info_hash=info_hash,
        traversal=tuple(traversal),
        actions=tuple(actions),
        rewrite_gates=rewrite_gates(info_hash is not None),
        output_emission_gates=tuple(gates),
        evidence_ids=evidence_ids,
    )


class _BencodeParser:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.actions: list[TorrentActionPlan] = []
        self.traversal: list[TorrentTraversalPlan] = []

    def parse_value(self, offset: int) -> _ParseResult:
        if offset >= len(self.data):
            return _ParseResult(
                None,
                offset,
                _ParseFailure(
                    "truncated_container",
                    "Unexpected end of bencode data.",
                    (TORRENT_READ_BENCODE_SOURCE,),
                ),
            )
        token = self.data[offset]
        if token == ord("i"):
            return self.parse_integer(offset)
        if token == ord("l"):
            return self.parse_list(offset)
        if token == ord("d"):
            return self.parse_dictionary(offset)
        if token == ord("e"):
            return _ParseResult(
                None,
                offset,
                _ParseFailure(
                    "bad_format", "Unexpected bencode end marker.", (TORRENT_READ_BENCODE_SOURCE,)
                ),
            )
        if ord("0") <= token <= ord("9"):
            return self.parse_string(offset)
        return _ParseResult(
            None,
            offset,
            _ParseFailure(
                "bad_format",
                "Bencode token is not an integer, list, dictionary, or byte string.",
                (TORRENT_READ_BENCODE_SOURCE,),
            ),
        )

    def parse_integer(self, offset: int) -> _ParseResult:
        end = self.data.find(b"e", offset + 1)
        if end < 0:
            return _ParseResult(
                None,
                offset,
                _ParseFailure(
                    "bad_format",
                    "Bencode integer is missing its terminating 'e'.",
                    (TORRENT_READ_BENCODE_SOURCE,),
                ),
            )
        raw_digits = self.data[offset + 1 : end]
        if re.fullmatch(rb"-?\d+", raw_digits) is None:
            return _ParseResult(
                None,
                offset,
                _ParseFailure(
                    "bad_format",
                    "Bencode integer payload is not decimal digits.",
                    (TORRENT_READ_BENCODE_SOURCE,),
                ),
            )
        value = int(raw_digits)
        byte_range = (offset, end + 1)
        plan = TorrentBencodeValuePlan(
            kind="integer",
            byte_range=byte_range,
            display_value=value,
            raw_bytes=None,
            byte_size=None,
            child_count=None,
            evidence_ids=(TORRENT_READ_BENCODE_SOURCE,),
        )
        self.actions.append(
            TorrentActionPlan(
                kind="decode_integer",
                target=str(value),
                byte_range=byte_range,
                reason="ReadBencode returns the integer digits between i and e.",
                evidence_ids=(TORRENT_READ_BENCODE_SOURCE,),
            )
        )
        return _ParseResult(
            _BencodeInteger(value=value, byte_range=byte_range, plan=plan), end + 1, None
        )

    def parse_string(self, offset: int) -> _ParseResult:
        colon = self.data.find(b":", offset)
        if colon < 0:
            return _ParseResult(
                None,
                offset,
                _ParseFailure(
                    "truncated_byte_string",
                    "Bencode byte string length is missing ':'.",
                    (TORRENT_BYTE_STRING_SOURCE,),
                ),
            )
        length_digits = self.data[offset:colon]
        if re.fullmatch(rb"\d+", length_digits) is None:
            return _ParseResult(
                None,
                offset,
                _ParseFailure(
                    "bad_format",
                    "Bencode byte string length is not decimal digits.",
                    (TORRENT_BYTE_STRING_SOURCE,),
                ),
            )
        length = int(length_digits)
        value_start = colon + 1
        value_end = value_start + length
        if value_end > len(self.data):
            return _ParseResult(
                None,
                offset,
                _ParseFailure(
                    "truncated_byte_string",
                    "Bencode byte string extends beyond input bytes.",
                    (TORRENT_BYTE_STRING_SOURCE,),
                ),
            )
        raw_bytes = self.data[value_start:value_end]
        kind, display_value, preserved_bytes = decode_bencode_string_value(raw_bytes)
        byte_range = (offset, value_end)
        plan = TorrentBencodeValuePlan(
            kind=kind,
            byte_range=byte_range,
            display_value=display_value,
            raw_bytes=preserved_bytes,
            byte_size=len(raw_bytes),
            child_count=None,
            evidence_ids=(TORRENT_BYTE_STRING_SOURCE,),
        )
        self.actions.append(
            TorrentActionPlan(
                kind="decode_string",
                target=f"{length} bytes",
                byte_range=byte_range,
                reason=(
                    "ReadBencode decodes short ASCII/UTF-8 strings and preserves binary strings."
                ),
                evidence_ids=(TORRENT_BYTE_STRING_SOURCE,),
            )
        )
        return _ParseResult(
            _BencodeString(
                raw_bytes=raw_bytes,
                byte_range=byte_range,
                value_range=(value_start, value_end),
                plan=plan,
            ),
            value_end,
            None,
        )

    def parse_list(self, offset: int) -> _ParseResult:
        values: list[BencodeNode] = []
        current = offset + 1
        while True:
            if current >= len(self.data):
                return _ParseResult(
                    None,
                    current,
                    _ParseFailure(
                        "truncated_container",
                        "Bencode list is missing its terminating 'e'.",
                        (TORRENT_READ_BENCODE_SOURCE,),
                    ),
                )
            if self.data[current] == ord("e"):
                end = current + 1
                byte_range = (offset, end)
                plan = TorrentBencodeValuePlan(
                    kind="list",
                    byte_range=byte_range,
                    display_value=f"list[{len(values)}]",
                    raw_bytes=None,
                    byte_size=None,
                    child_count=len(values),
                    evidence_ids=(TORRENT_READ_BENCODE_SOURCE,),
                )
                self.actions.append(
                    TorrentActionPlan(
                        kind="decode_list",
                        target=f"{len(values)} items",
                        byte_range=byte_range,
                        reason="ReadBencode recursively decodes list items until an end marker.",
                        evidence_ids=(TORRENT_READ_BENCODE_SOURCE,),
                    )
                )
                self.traversal.append(
                    TorrentTraversalPlan(
                        kind="list",
                        path="",
                        byte_range=byte_range,
                        child_count=len(values),
                        evidence_ids=(TORRENT_EXTRACT_TAGS_SOURCE,),
                    )
                )
                return _ParseResult(
                    _BencodeList(values=tuple(values), byte_range=byte_range, plan=plan), end, None
                )
            result = self.parse_value(current)
            if result.failure is not None or result.node is None:
                return result
            values.append(result.node)
            current = result.next_offset

    def parse_dictionary(self, offset: int) -> _ParseResult:
        entries: list[_BencodeDictEntry] = []
        current = offset + 1
        while True:
            if current >= len(self.data):
                return _ParseResult(
                    None,
                    current,
                    _ParseFailure(
                        "truncated_container",
                        "Bencode dictionary is missing its terminating 'e'.",
                        (TORRENT_READ_BENCODE_SOURCE,),
                    ),
                )
            if self.data[current] == ord("e"):
                end = current + 1
                byte_range = (offset, end)
                plan = TorrentBencodeValuePlan(
                    kind="dictionary",
                    byte_range=byte_range,
                    display_value=f"dict[{len(entries)}]",
                    raw_bytes=None,
                    byte_size=None,
                    child_count=len(entries),
                    evidence_ids=(TORRENT_READ_BENCODE_SOURCE,),
                )
                self.actions.append(
                    TorrentActionPlan(
                        kind="decode_dictionary",
                        target=f"{len(entries)} pairs",
                        byte_range=byte_range,
                        reason=(
                            "ReadBencode recursively decodes dictionary key/value "
                            "pairs until an end marker."
                        ),
                        evidence_ids=(TORRENT_READ_BENCODE_SOURCE,),
                    )
                )
                self.traversal.append(
                    TorrentTraversalPlan(
                        kind="dictionary",
                        path="",
                        byte_range=byte_range,
                        child_count=len(entries),
                        evidence_ids=(TORRENT_EXTRACT_TAGS_SOURCE,),
                    )
                )
                return _ParseResult(
                    _BencodeDict(entries=tuple(entries), byte_range=byte_range, plan=plan),
                    end,
                    None,
                )
            key_result = self.parse_value(current)
            if key_result.failure is not None or key_result.node is None:
                return key_result
            if not isinstance(key_result.node, _BencodeString):
                return _ParseResult(
                    None,
                    current,
                    _ParseFailure(
                        "bad_dictionary_key",
                        "Bencode dictionary keys must be byte strings.",
                        (TORRENT_READ_BENCODE_SOURCE,),
                    ),
                )
            value_result = self.parse_value(key_result.next_offset)
            if value_result.failure is not None or value_result.node is None:
                return value_result
            entries.append(_BencodeDictEntry(key=key_result.node, value=value_result.node))
            current = value_result.next_offset


def decode_bencode_string_value(
    raw_bytes: bytes,
) -> tuple[Literal["string", "binary"], JsonValue, bytes | None]:
    if len(raw_bytes) > BINARY_STRING_LIMIT:
        return "binary", f"Binary data {len(raw_bytes)} bytes", raw_bytes
    if all(byte == 9 or 0x20 <= byte <= 0x7E for byte in raw_bytes):
        return "string", raw_bytes.decode("ascii"), None
    try:
        return "string", raw_bytes.decode("utf-8"), None
    except UnicodeDecodeError:
        return "binary", f"Binary data {len(raw_bytes)} bytes", raw_bytes


def is_torrent_dictionary(node: _BencodeDict) -> bool:
    return (
        node.value_for_key(b"announce") is not None
        or node.value_for_key(b"created by") is not None
        or node.value_for_key(b"info") is not None
    )


def info_dict_range(node: BencodeNode) -> tuple[int, int] | None:
    if not isinstance(node, _BencodeDict):
        return None
    info = node.value_for_key(b"info")
    if isinstance(info, _BencodeDict):
        return info.byte_range
    return None


def build_info_hash_responsibility(
    data: bytes,
    root: _BencodeDict,
) -> TorrentInfoHashResponsibility | None:
    info = root.value_for_key(b"info")
    if not isinstance(info, _BencodeDict):
        return None
    start, end = info.byte_range
    sha1_hex = hashlib.sha1(data[start:end]).hexdigest()
    return TorrentInfoHashResponsibility(
        info_dict_range=info.byte_range,
        sha1_hex=sha1_hex,
        evidence_ids=(
            TORRENT_INFO_SOURCE,
            TORRENT_INFO_HASH_SOURCE,
            TORRENT_NON_MUTATING_SOURCE,
        ),
    )


def extract_tags(root: _BencodeDict) -> tuple[TorrentMetadataResponsibility, ...]:
    responsibilities: list[TorrentMetadataResponsibility] = []
    extract_dictionary_tags(
        root,
        "main",
        None,
        None,
        (),
        (),
        responsibilities,
    )
    return tuple(responsibilities)


def extract_dictionary_tags(
    dictionary: _BencodeDict,
    table: TorrentTagTable,
    base_id: str | None,
    base_name: str | None,
    indices: tuple[int, ...],
    path_components: tuple[str, ...],
    responsibilities: list[TorrentMetadataResponsibility],
) -> None:
    for entry in sorted(dictionary.entries, key=lambda item: item.key.raw_bytes):
        tag = decode_key(entry.key.raw_bytes)
        tag_info = table_tag_info(table, tag, base_name)
        tag_id = f"{base_id}/{tag}" if base_id is not None else tag
        extract_value_for_tag(
            entry.value,
            table,
            tag,
            tag_id,
            tag_info,
            indices,
            (*path_components, tag),
            responsibilities,
        )


def extract_value_for_tag(
    value: BencodeNode,
    table: TorrentTagTable,
    tag: str,
    tag_id: str,
    tag_info: _TableTagInfo,
    indices: tuple[int, ...],
    path_components: tuple[str, ...],
    responsibilities: list[TorrentMetadataResponsibility],
) -> None:
    if isinstance(value, _BencodeList):
        if tag_info.join_path:
            joined = join_path_list(value)
            plan = TorrentBencodeValuePlan(
                kind="string",
                byte_range=value.byte_range,
                display_value=joined,
                raw_bytes=None,
                byte_size=None,
                child_count=len(value.values),
                evidence_ids=(TORRENT_EXTRACT_TAGS_SOURCE, *tag_info.evidence_ids),
            )
            append_scalar_responsibility(
                responsibilities,
                table,
                tag_id,
                tag_info,
                indices,
                path_components,
                plan,
            )
            return
        for index, child in enumerate(expand_list_values(value), start=1):
            extract_value_for_tag(
                child,
                table,
                tag,
                tag_id,
                tag_info,
                (*indices, index),
                path_components,
                responsibilities,
            )
        return

    indexed_tag_id, indexed_name = indexed_tag_identity(tag_id, tag_info.name, indices)
    if isinstance(value, _BencodeDict):
        if tag_info.subdirectory is not None:
            extract_dictionary_tags(
                value,
                tag_info.subdirectory,
                None,
                None,
                indices,
                path_components,
                responsibilities,
            )
            return
        extract_dictionary_tags(
            value,
            table,
            indexed_tag_id,
            indexed_name,
            indices,
            path_components,
            responsibilities,
        )
        return
    append_scalar_responsibility(
        responsibilities,
        table,
        tag_id,
        tag_info,
        indices,
        path_components,
        value.plan,
    )


def expand_list_values(value: _BencodeList) -> tuple[BencodeNode, ...]:
    expanded: list[BencodeNode] = []
    for child in value.values:
        if isinstance(child, _BencodeList):
            expanded.extend(expand_list_values(child))
        else:
            expanded.append(child)
    return tuple(expanded)


def append_scalar_responsibility(
    responsibilities: list[TorrentMetadataResponsibility],
    table: TorrentTagTable,
    tag_id: str,
    tag_info: _TableTagInfo,
    indices: tuple[int, ...],
    path_components: tuple[str, ...],
    value: TorrentBencodeValuePlan,
) -> None:
    indexed_tag_id, indexed_name = indexed_tag_identity(tag_id, tag_info.name, indices)
    planned_value = digest_value_plan(tag_id, value)
    evidence_ids = unique_evidence_ids(
        (TORRENT_EXTRACT_TAGS_SOURCE, *tag_info.evidence_ids, *planned_value.evidence_ids)
    )
    responsibilities.append(
        TorrentMetadataResponsibility(
            tag_id=indexed_tag_id,
            generated_name=indexed_name,
            path_components=path_components,
            table=table,
            value=planned_value,
            evidence_ids=evidence_ids,
        )
    )


def digest_value_plan(tag_id: str, value: TorrentBencodeValuePlan) -> TorrentBencodeValuePlan:
    if tag_id != "pieces" or value.raw_bytes is not None:
        return value
    if not isinstance(value.display_value, str):
        return value
    return TorrentBencodeValuePlan(
        kind="binary",
        byte_range=value.byte_range,
        display_value=f"Binary data {value.byte_size} bytes",
        raw_bytes=value.display_value.encode("utf-8"),
        byte_size=value.byte_size,
        child_count=value.child_count,
        evidence_ids=unique_evidence_ids(
            (*value.evidence_ids, TORRENT_INFO_SOURCE, TORRENT_INFO_HASH_SOURCE)
        ),
    )


def table_tag_info(table: TorrentTagTable, tag_id: str, base_name: str | None) -> _TableTagInfo:
    known = TAG_TABLES[table].get(tag_id)
    if known is not None:
        name = known.name if known.name is not None else sanitize_tag_name(tag_id, None)
        return _TableTagInfo(name, known.subdirectory, known.join_path, known.evidence_ids)
    return _TableTagInfo(
        sanitize_tag_name(tag_id, base_name),
        None,
        False,
        (TORRENT_EXTRACT_TAGS_SOURCE,),
    )


def sanitize_tag_name(tag: str, base_name: str | None) -> str:
    name = tag[:1].upper() + tag[1:]
    name = re.sub(r"[^-_a-zA-Z0-9]+(.?)", lambda match: match.group(1).upper(), name)
    if len(name) < 2 or not re.match(r"^[A-Z]", name):
        name = f"Tag{name}"
    if base_name is not None:
        name = f"{base_name}{name}"
    return name


def indexed_tag_identity(
    tag_id: str,
    name: str | None,
    indices: tuple[int, ...],
) -> tuple[str, str]:
    generated_name = (
        name if name is not None else sanitize_tag_name(tag_id.rsplit("/", maxsplit=1)[-1], None)
    )
    if not indices:
        return tag_id, generated_name
    indexed_tag_id = f"{tag_id}{'_'.join(str(index) for index in indices)}"
    indexed_name = generated_name
    remaining_indices = list(indices)
    while "1" in indexed_name and remaining_indices:
        indexed_name = indexed_name.replace("1", str(remaining_indices.pop(0)), 1)
    for index in remaining_indices:
        if indexed_name[-1:].isdigit():
            indexed_name = f"{indexed_name}_"
        indexed_name = f"{indexed_name}{index}"
    return indexed_tag_id, indexed_name


def decode_key(raw_key: bytes) -> str:
    try:
        return raw_key.decode("utf-8")
    except UnicodeDecodeError:
        return raw_key.hex()


def join_path_list(value: _BencodeList) -> str:
    parts: list[str] = []
    for child in value.values:
        if (
            isinstance(child, _BencodeString)
            and isinstance(child.plan.display_value, str)
            and child.plan.kind == "string"
        ):
            parts.append(child.plan.display_value)
        elif isinstance(child, _BencodeInteger):
            parts.append(str(child.value))
        else:
            parts.append("(Binary data)")
    return "/".join(parts)


def output_gate(
    code: TorrentOutputGateCode,
    reason: str,
    sources: tuple[str, ...],
) -> TorrentOutputEmissionGate:
    return TorrentOutputEmissionGate(code=code, reason=reason, evidence_ids=sources)


def add_non_mutating_gate(
    gates: list[TorrentOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        output_gate(
            "non_mutating_plan_requires_explicit_emission",
            "This planner is non-mutating; byte-for-byte emission requires explicit opt-in.",
            (TORRENT_NON_MUTATING_SOURCE,),
        )
    )


def only_non_mutating_gate(gates: list[TorrentOutputEmissionGate]) -> bool:
    return len(gates) == 1 and gates[0].code == "non_mutating_plan_requires_explicit_emission"


def rewrite_gates(has_info_hash: bool) -> tuple[TorrentRewriteGate, ...]:
    gates = [
        TorrentRewriteGate(
            code="torrent_writer_not_implemented",
            reason=(
                "ExifTool Torrent.pm is read-only and this planner does not "
                "rewrite torrent metadata."
            ),
            evidence_ids=(TORRENT_PROCESS_SOURCE, TORRENT_NON_MUTATING_SOURCE),
        ),
        TorrentRewriteGate(
            code="bencode_rewrite_not_implemented",
            reason=(
                "Rewriting bencode requires canonical dictionary/string "
                "regeneration outside this planner."
            ),
            evidence_ids=(TORRENT_READ_BENCODE_SOURCE, TORRENT_NON_MUTATING_SOURCE),
        ),
    ]
    if has_info_hash:
        gates.append(
            TorrentRewriteGate(
                code="info_hash_recalculation_required",
                reason="Changing the info dictionary changes the SHA-1 info hash.",
                evidence_ids=(TORRENT_INFO_HASH_SOURCE, TORRENT_NON_MUTATING_SOURCE),
            )
        )
        gates.append(
            TorrentRewriteGate(
                code="raw_info_dict_boundary_required",
                reason=(
                    "The exact bencoded info dictionary bytes must be preserved "
                    "for stable info-hash planning."
                ),
                evidence_ids=(TORRENT_INFO_HASH_SOURCE, TORRENT_NON_MUTATING_SOURCE),
            )
        )
    return tuple(gates)


def unsupported_plan(
    torrent_data: bytes,
    root_value: TorrentBencodeValuePlan | None,
    boundaries: TorrentRawBoundaryPlan,
    gates: list[TorrentOutputEmissionGate],
    actions: list[TorrentActionPlan],
    traversal: list[TorrentTraversalPlan],
) -> TorrentBencodeTransactionPlan:
    evidence_ids = unique_evidence_ids(
        (
            *TORRENT_TRANSACTION_SOURCES,
            *(source for gate in gates for source in gate.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
        )
    )
    return TorrentBencodeTransactionPlan(
        status="unsupported",
        source_data=torrent_data,
        root_value=root_value,
        boundaries=boundaries,
        metadata_responsibilities=(),
        info_hash=None,
        traversal=tuple(traversal),
        actions=tuple(actions),
        rewrite_gates=rewrite_gates(False),
        output_emission_gates=tuple(gates),
        evidence_ids=evidence_ids,
    )


def json_range(value: tuple[int, int] | None) -> JsonArray | None:
    return None if value is None else [value[0], value[1]]


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return [value for value in values]


def unique_evidence_ids(references: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


install_evidence_reference_compat(globals())
