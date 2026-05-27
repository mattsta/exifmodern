"""Source-backed, non-mutating JSON metadata transaction plans.

This planner mirrors ExifTool's JSON.pm read path: JSON.pm delegates token
parsing to Import::ReadJSON, wraps a top-level object as a one-item database,
ignores non-object top-level array items, flattens nested structures into tag
paths, and never describes a byte-mutating JSON writer.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.json_types import JsonArray, JsonObject, JsonValue

JSON_SOURCE_PATH = "lib/Image/ExifTool/JSON.pm"
IMPORT_SOURCE_PATH = "lib/Image/ExifTool/Import.pm"
READ_CHUNK_SIZE = 65_536

type JsonPlanStatus = Literal["planned", "blocked", "unsupported"]
type JsonSignatureKind = Literal["object", "array", "scalar", "empty", "unknown"]
type JsonValueKind = Literal["array", "binary", "boolean", "dict", "null", "number", "string"]
type JsonTopLevelModel = Literal[
    "single_database_object",
    "database_object_array",
    "unsupported_scalar",
    "unsupported_empty",
]
type JsonTraversalAction = Literal[
    "wrap_top_level_hash",
    "iterate_top_level_array",
    "skip_top_level_array_item",
    "default_source_file",
    "case_fix_source_file",
    "skip_auto_source_file",
    "traverse_hash",
    "traverse_array",
    "emit_scalar_tag",
    "skip_missing_value",
    "preserve_raw_token",
]
type JsonEscapeKind = Literal["unicode_escape", "named_escape", "passthrough_escape"]
type JsonEmissionGateCode = Literal[
    "empty_input",
    "parse_error",
    "truncated_string",
    "truncated_object",
    "truncated_array",
    "top_level_scalar_not_database",
    "top_level_array_without_hash_objects",
    "output_emission_requires_explicit_opt_in",
]
type JsonRewriteBlockerCode = Literal[
    "json_writer_not_implemented",
    "raw_token_layout_preservation_required",
    "flattened_tag_paths_are_not_invertible",
]

JSON_MAIN_SOURCE = "json.main"
JSON_FOUND_TAG_SOURCE = "json.found_tag"
JSON_PROCESS_TAG_SOURCE = "json.process_tag"
JSON_PROCESS_SOURCE = "json.process"
IMPORT_JSON_TOKEN_SOURCE = "json.import_json_token"
IMPORT_JSON_DATABASE_SOURCE = "json.import_json_database"
IMPORT_JSON_CHARSET_SOURCE = "json.import_json_charset"

JSON_TRANSACTION_SOURCES = (
    JSON_MAIN_SOURCE,
    JSON_FOUND_TAG_SOURCE,
    JSON_PROCESS_TAG_SOURCE,
    JSON_PROCESS_SOURCE,
    IMPORT_JSON_TOKEN_SOURCE,
    IMPORT_JSON_DATABASE_SOURCE,
    IMPORT_JSON_CHARSET_SOURCE,
)


@dataclass(frozen=True)
class JsonEmissionGate:
    code: JsonEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class JsonRewriteBlocker:
    code: JsonRewriteBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class JsonSignaturePlan:
    accepted: bool
    kind: JsonSignatureKind
    has_utf8_bom: bool
    sniffed_length: int
    first_token_offset: int | None
    first_token: str | None
    read_chunk_size: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "accepted": self.accepted,
            "first_token": self.first_token,
            "first_token_offset": self.first_token_offset,
            "has_utf8_bom": self.has_utf8_bom,
            "kind": self.kind,
            "read_chunk_size": self.read_chunk_size,
            "sniffed_length": self.sniffed_length,
        }


@dataclass(frozen=True)
class JsonRawBoundaryPlan:
    source_range: tuple[int, int]
    sniff_range: tuple[int, int]
    bom_range: tuple[int, int] | None
    root_value_range: tuple[int, int] | None
    raw_preservation_range: tuple[int, int]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "bom_range": json_range(self.bom_range),
            "raw_preservation_range": json_range(self.raw_preservation_range),
            "root_value_range": json_range(self.root_value_range),
            "sniff_range": json_range(self.sniff_range),
            "source_range": json_range(self.source_range),
        }


@dataclass(frozen=True)
class JsonRootPlan:
    value_kind: JsonValueKind | None
    top_level_model: JsonTopLevelModel
    database_object_count: int
    skipped_top_level_items: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "database_object_count": self.database_object_count,
            "skipped_top_level_items": self.skipped_top_level_items,
            "top_level_model": self.top_level_model,
            "value_kind": self.value_kind,
        }


@dataclass(frozen=True)
class JsonEscapePlan:
    kind: JsonEscapeKind
    raw_escape: str
    decoded_text: str
    byte_range: tuple[int, int]
    charset: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": json_range(self.byte_range),
            "charset": self.charset,
            "decoded_text": self.decoded_text,
            "kind": self.kind,
            "raw_escape": self.raw_escape,
        }


@dataclass(frozen=True)
class JsonValuePlan:
    kind: JsonValueKind
    display_value: JsonValue
    raw_text: str
    raw_bytes: bytes | None
    byte_range: tuple[int, int]
    charset: str | None
    escape_sequences: tuple[JsonEscapePlan, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "byte_range": json_range(self.byte_range),
            "charset": self.charset,
            "display_value": self.display_value,
            "escape_sequences": json_object_array(
                escape.to_json() for escape in self.escape_sequences
            ),
            "kind": self.kind,
            "raw_bytes_hex": None if self.raw_bytes is None else self.raw_bytes.hex(),
            "raw_text": self.raw_text,
        }


@dataclass(frozen=True)
class JsonDatabaseEntryPlan:
    source_file: str
    tag_id: str
    generated_name: str
    path_components: tuple[str, ...]
    value: JsonValuePlan
    flat: bool
    list_item: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "flat": self.flat,
            "generated_name": self.generated_name,
            "list_item": self.list_item,
            "path_components": list(self.path_components),
            "source_file": self.source_file,
            "tag_id": self.tag_id,
            "value": self.value.to_json(),
        }


@dataclass(frozen=True)
class JsonTraversalPlan:
    action: JsonTraversalAction
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "byte_range": json_range(self.byte_range),
            "reason": self.reason,
            "target": self.target,
        }


@dataclass(frozen=True)
class JsonMetadataTransactionPlan:
    status: JsonPlanStatus
    signature: JsonSignaturePlan
    boundaries: JsonRawBoundaryPlan
    root: JsonRootPlan
    database_entries: tuple[JsonDatabaseEntryPlan, ...]
    traversal: tuple[JsonTraversalPlan, ...]
    rewrite_blockers: tuple[JsonRewriteBlocker, ...]
    output_emission_gates: tuple[JsonEmissionGate, ...]
    output_bytes: bytes | None
    evidence_ids: tuple[str, ...] = JSON_TRANSACTION_SOURCES

    @property
    def can_emit_output(self) -> bool:
        return (
            self.status == "planned"
            and not self.output_emission_gates
            and self.output_bytes is not None
        )

    def emit(self) -> bytes:
        if not self.can_emit_output or self.output_bytes is None:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"JSON metadata transaction output is gated: {gate_codes}")
        return self.output_bytes

    def to_json(self) -> JsonObject:
        return {
            "boundaries": self.boundaries.to_json(),
            "can_emit_output": self.can_emit_output,
            "database_entries": json_object_array(
                entry.to_json() for entry in self.database_entries
            ),
            "output_emission_gates": json_object_array(
                gate_to_json(gate) for gate in self.output_emission_gates
            ),
            "rewrite_blockers": json_object_array(
                blocker_to_json(blocker) for blocker in self.rewrite_blockers
            ),
            "root": self.root.to_json(),
            "signature": self.signature.to_json(),
            "status": self.status,
            "traversal": json_object_array(item.to_json() for item in self.traversal),
        }


@dataclass(frozen=True)
class _JsonScalarNode:
    kind: Literal["binary", "boolean", "null", "number", "string"]
    display_value: str
    raw_text: str
    raw_bytes: bytes | None
    start: int
    end: int
    charset: str | None
    escapes: tuple[JsonEscapePlan, ...]


@dataclass(frozen=True)
class _JsonArrayNode:
    items: tuple[_JsonNode, ...]
    start: int
    end: int


@dataclass(frozen=True)
class _JsonObjectMember:
    key: str
    key_range: tuple[int, int]
    value: _JsonNode


@dataclass(frozen=True)
class _JsonObjectNode:
    members: tuple[_JsonObjectMember, ...]
    start: int
    end: int


type _JsonNode = _JsonScalarNode | _JsonArrayNode | _JsonObjectNode


@dataclass(frozen=True)
class _ParseFailure:
    code: JsonEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class _ParseResult:
    node: _JsonNode | None
    failure: _ParseFailure | None
    bom_range: tuple[int, int] | None


@dataclass(frozen=True)
class _StringParseResult:
    value: str
    raw_text: str
    raw_bytes: bytes | None
    start: int
    end: int
    escapes: tuple[JsonEscapePlan, ...]
    failure: _ParseFailure | None


@dataclass(frozen=True)
class _DatabaseObject:
    source_file: str
    node: _JsonObjectNode


def build_json_metadata_transaction_plan(
    data: bytes,
    *,
    allow_output_emission: bool = False,
    missing_tag_value: str | None = None,
    charset: str = "UTF8",
) -> JsonMetadataTransactionPlan:
    """Build a source-grounded, non-mutating JSON metadata transaction plan."""

    signature = _sniff_signature(data)
    parser = _JsonParser(data, charset)
    parsed = parser.parse()
    gates: list[JsonEmissionGate] = []
    traversal: list[JsonTraversalPlan] = []
    database_entries: list[JsonDatabaseEntryPlan] = []

    root_range: tuple[int, int] | None = None
    root_kind: JsonValueKind | None = None
    root_model: JsonTopLevelModel = "unsupported_empty"
    database_objects: tuple[_DatabaseObject, ...] = ()
    skipped_items = 0

    if parsed.failure is not None:
        gates.append(parse_gate(parsed.failure))
    elif parsed.node is None:
        gates.append(
            JsonEmissionGate(
                code="empty_input",
                reason="ReadJSONObject reaches EOF before any JSON token is available.",
                evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
            )
        )
    else:
        root_range = node_range(parsed.node)
        root_kind = node_kind(parsed.node)
        root_model, database_objects, skipped_items = _database_objects_from_root(
            parsed.node,
            traversal,
        )
        if root_model == "unsupported_scalar":
            gates.append(
                JsonEmissionGate(
                    code="top_level_scalar_not_database",
                    reason=(
                        "ReadJSON requires a HASH or ARRAY of HASH entries; a scalar "
                        "top-level JSON token is a format error."
                    ),
                    evidence_ids=(IMPORT_JSON_DATABASE_SOURCE,),
                )
            )
        elif root_model == "database_object_array" and not database_objects:
            gates.append(
                JsonEmissionGate(
                    code="top_level_array_without_hash_objects",
                    reason=(
                        "ReadJSON ignores non-HASH array items and reports no valid JSON objects."
                    ),
                    evidence_ids=(IMPORT_JSON_DATABASE_SOURCE,),
                )
            )
        else:
            _collect_database_entries(
                database_objects,
                database_entries,
                traversal,
                missing_tag_value,
                charset,
            )

    if not allow_output_emission:
        gates.append(
            JsonEmissionGate(
                code="output_emission_requires_explicit_opt_in",
                reason=(
                    "JSON metadata transaction plans preserve bytes only when emission "
                    "is explicitly allowed by the caller."
                ),
                evidence_ids=(JSON_PROCESS_SOURCE,),
            )
        )

    boundaries = JsonRawBoundaryPlan(
        source_range=(0, len(data)),
        sniff_range=(0, min(len(data), READ_CHUNK_SIZE)),
        bom_range=parsed.bom_range,
        root_value_range=root_range,
        raw_preservation_range=(0, len(data)),
        evidence_ids=(IMPORT_JSON_TOKEN_SOURCE, JSON_PROCESS_SOURCE),
    )
    root = JsonRootPlan(
        value_kind=root_kind,
        top_level_model=root_model,
        database_object_count=len(database_objects),
        skipped_top_level_items=skipped_items,
        evidence_ids=(IMPORT_JSON_DATABASE_SOURCE, JSON_PROCESS_SOURCE),
    )
    rewrite_blockers = (
        JsonRewriteBlocker(
            code="json_writer_not_implemented",
            reason="JSON.pm is a read module and does not provide a source-grounded JSON writer.",
            evidence_ids=(JSON_PROCESS_SOURCE,),
        ),
        JsonRewriteBlocker(
            code="raw_token_layout_preservation_required",
            reason=(
                "Import::ReadJSON parses tokens into values while preserving no "
                "canonical rewrite layout for whitespace, ordering, or escapes."
            ),
            evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
        ),
        JsonRewriteBlocker(
            code="flattened_tag_paths_are_not_invertible",
            reason=(
                "ProcessTag flattens nested hashes and repeats array values as list "
                "entries, which is not enough information for an inverse JSON rewrite."
            ),
            evidence_ids=(JSON_PROCESS_TAG_SOURCE,),
        ),
    )
    blocking_codes = {
        "empty_input",
        "parse_error",
        "truncated_string",
        "truncated_object",
        "truncated_array",
        "top_level_scalar_not_database",
        "top_level_array_without_hash_objects",
    }
    status: JsonPlanStatus
    if any(gate.code in blocking_codes for gate in gates):
        status = (
            "unsupported" if any(gate.code.startswith("top_level") for gate in gates) else "blocked"
        )
    else:
        status = "planned"
    output_bytes = data if status == "planned" and allow_output_emission else None

    return JsonMetadataTransactionPlan(
        status=status,
        signature=signature,
        boundaries=boundaries,
        root=root,
        database_entries=tuple(database_entries),
        traversal=tuple(traversal),
        rewrite_blockers=rewrite_blockers,
        output_emission_gates=tuple(gates),
        output_bytes=output_bytes,
    )


plan_json_metadata_transaction = build_json_metadata_transaction_plan


class _JsonParser:
    def __init__(self, data: bytes, charset: str) -> None:
        self._data = data
        self._text = data.decode("latin-1")
        self._length = len(data)
        self._position = 0
        self._charset = charset
        self._bom_range: tuple[int, int] | None = None

    def parse(self) -> _ParseResult:
        if self._data.startswith(b"\xef\xbb\xbf"):
            self._bom_range = (0, 3)
            self._position = 3
        self._skip_whitespace()
        if self._position >= self._length:
            return _ParseResult(None, None, self._bom_range)
        node = self._parse_value()
        if node.failure is not None:
            return _ParseResult(None, node.failure, self._bom_range)
        return _ParseResult(node.node, None, self._bom_range)

    def _parse_value(self) -> _NodeResult:
        self._skip_whitespace()
        if self._position >= self._length:
            return _NodeResult(
                None,
                _ParseFailure(
                    code="parse_error",
                    reason="Expected a JSON value but reached EOF.",
                    evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
                ),
            )
        token = self._text[self._position]
        if token == "{":
            return self._parse_object()
        if token == "[":
            return self._parse_array()
        if token == '"':
            string = self._parse_string()
            if string.failure is not None:
                return _NodeResult(None, string.failure)
            kind: Literal["binary", "string"] = (
                "binary" if string.raw_bytes is not None else "string"
            )
            return _NodeResult(
                _JsonScalarNode(
                    kind=kind,
                    display_value=string.value,
                    raw_text=string.raw_text,
                    raw_bytes=string.raw_bytes,
                    start=string.start,
                    end=string.end,
                    charset=self._charset,
                    escapes=string.escapes,
                ),
                None,
            )
        return self._parse_unquoted_scalar()

    def _parse_object(self) -> _NodeResult:
        start = self._position
        self._position += 1
        members: list[_JsonObjectMember] = []
        self._skip_whitespace()
        if self._consume("}"):
            return _NodeResult(_JsonObjectNode(tuple(members), start, self._position), None)
        while True:
            self._skip_whitespace()
            if self._position >= self._length:
                return _NodeResult(
                    None,
                    _ParseFailure(
                        code="truncated_object",
                        reason="Object started but EOF was reached before a closing '}'.",
                        evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
                    ),
                )
            if self._text[self._position] != '"':
                return _NodeResult(
                    None,
                    _ParseFailure(
                        code="parse_error",
                        reason="Object member key is not a quoted JSON string.",
                        evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
                    ),
                )
            key = self._parse_string()
            if key.failure is not None:
                return _NodeResult(None, key.failure)
            self._skip_whitespace()
            if not self._consume(":"):
                return _NodeResult(
                    None,
                    _ParseFailure(
                        code="parse_error",
                        reason="Object member key was not followed by ':'.",
                        evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
                    ),
                )
            value = self._parse_value()
            if value.failure is not None:
                return value
            if value.node is None:
                return _NodeResult(
                    None,
                    _ParseFailure(
                        code="parse_error",
                        reason="Object member value was empty.",
                        evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
                    ),
                )
            members.append(_JsonObjectMember(key.value, (key.start, key.end), value.node))
            self._skip_whitespace()
            if self._consume("}"):
                return _NodeResult(_JsonObjectNode(tuple(members), start, self._position), None)
            if self._position >= self._length:
                return _NodeResult(
                    None,
                    _ParseFailure(
                        code="truncated_object",
                        reason="Object member was not followed by ',' or a closing '}' before EOF.",
                        evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
                    ),
                )
            if not self._consume(","):
                return _NodeResult(
                    None,
                    _ParseFailure(
                        code="parse_error",
                        reason="Object member was not followed by ',' or '}'.",
                        evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
                    ),
                )
            self._skip_whitespace()
            if self._consume("}"):
                return _NodeResult(_JsonObjectNode(tuple(members), start, self._position), None)

    def _parse_array(self) -> _NodeResult:
        start = self._position
        self._position += 1
        items: list[_JsonNode] = []
        self._skip_whitespace()
        if self._consume("]"):
            return _NodeResult(_JsonArrayNode(tuple(items), start, self._position), None)
        while True:
            value = self._parse_value()
            if value.failure is not None:
                return value
            if value.node is not None:
                items.append(value.node)
            self._skip_whitespace()
            if self._consume("]"):
                return _NodeResult(_JsonArrayNode(tuple(items), start, self._position), None)
            if not self._consume(","):
                return _NodeResult(
                    None,
                    _ParseFailure(
                        code="truncated_array" if self._position >= self._length else "parse_error",
                        reason="Array item was not followed by ',' or ']'.",
                        evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
                    ),
                )
            self._skip_whitespace()
            if self._consume("]"):
                return _NodeResult(_JsonArrayNode(tuple(items), start, self._position), None)

    def _parse_string(self) -> _StringParseResult:
        start = self._position
        self._position += 1
        raw_chars: list[str] = []
        value_chars: list[str] = []
        escapes: list[JsonEscapePlan] = []
        while self._position < self._length:
            current = self._text[self._position]
            if current == '"':
                self._position += 1
                raw_text = "".join(raw_chars)
                value = "".join(value_chars)
                raw_bytes = _decode_exiftool_base64(value)
                return _StringParseResult(
                    value=value if raw_bytes is None else raw_bytes.decode("latin-1"),
                    raw_text=raw_text,
                    raw_bytes=raw_bytes,
                    start=start,
                    end=self._position,
                    escapes=tuple(escapes),
                    failure=None,
                )
            if current == "\\":
                escape_start = self._position
                self._position += 1
                if self._position >= self._length:
                    return _StringParseResult(
                        "",
                        "",
                        None,
                        start,
                        self._position,
                        (),
                        _ParseFailure(
                            code="truncated_string",
                            reason="String ended immediately after an escape prefix.",
                            evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
                        ),
                    )
                escape_char = self._text[self._position]
                if escape_char == "u":
                    unicode_text = self._text[self._position + 1 : self._position + 5]
                    if len(unicode_text) < 4 or not re.fullmatch(r"[0-9a-fA-F]{4}", unicode_text):
                        return _StringParseResult(
                            "",
                            "",
                            None,
                            start,
                            self._position,
                            (),
                            _ParseFailure(
                                code="truncated_string",
                                reason="Unicode escape did not contain four hexadecimal digits.",
                                evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
                            ),
                        )
                    raw_escape = "\\u" + unicode_text
                    decoded = chr(int(unicode_text, 16))
                    raw_chars.append(raw_escape)
                    value_chars.append(decoded)
                    self._position += 5
                    escapes.append(
                        JsonEscapePlan(
                            kind="unicode_escape",
                            raw_escape=raw_escape,
                            decoded_text=decoded,
                            byte_range=(escape_start, self._position),
                            charset=self._charset,
                            evidence_ids=(IMPORT_JSON_CHARSET_SOURCE,),
                        )
                    )
                    continue
                decoded = _JSON_ESCAPES.get(escape_char, escape_char)
                raw_escape = "\\" + escape_char
                raw_chars.append(raw_escape)
                value_chars.append(decoded)
                self._position += 1
                escapes.append(
                    JsonEscapePlan(
                        kind=(
                            "named_escape" if escape_char in _JSON_ESCAPES else "passthrough_escape"
                        ),
                        raw_escape=raw_escape,
                        decoded_text=decoded,
                        byte_range=(escape_start, self._position),
                        charset=self._charset,
                        evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
                    )
                )
                continue
            raw_chars.append(current)
            value_chars.append(current)
            self._position += 1
        return _StringParseResult(
            "",
            "",
            None,
            start,
            self._position,
            (),
            _ParseFailure(
                code="truncated_string",
                reason="String started but EOF was reached before a closing quote.",
                evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
            ),
        )

    def _parse_unquoted_scalar(self) -> _NodeResult:
        start = self._position
        while self._position < self._length and self._text[self._position] not in " \t\r\n:,}]":
            self._position += 1
        raw = self._text[start : self._position]
        if not raw:
            return _NodeResult(
                None,
                _ParseFailure(
                    code="parse_error",
                    reason="Expected a scalar token.",
                    evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
                ),
            )
        kind: Literal["boolean", "null", "number", "string"]
        if raw in {"true", "false"}:
            kind = "boolean"
        elif raw == "null":
            kind = "null"
        elif _looks_numeric(raw):
            kind = "number"
        else:
            kind = "string"
        return _NodeResult(
            _JsonScalarNode(
                kind=kind,
                display_value=raw,
                raw_text=raw,
                raw_bytes=None,
                start=start,
                end=self._position,
                charset=None,
                escapes=(),
            ),
            None,
        )

    def _skip_whitespace(self) -> None:
        while self._position < self._length and self._text[self._position] in " \t\r\n":
            self._position += 1

    def _consume(self, token: str) -> bool:
        if self._position < self._length and self._text[self._position] == token:
            self._position += 1
            return True
        return False


@dataclass(frozen=True)
class _NodeResult:
    node: _JsonNode | None
    failure: _ParseFailure | None


_JSON_ESCAPES = {
    "t": "\t",
    "n": "\n",
    "r": "\r",
    "b": "\b",
    "f": "\f",
}


def _sniff_signature(data: bytes) -> JsonSignaturePlan:
    has_bom = data.startswith(b"\xef\xbb\xbf")
    offset = 3 if has_bom else 0
    while offset < len(data) and chr(data[offset]) in " \t\r\n":
        offset += 1
    if offset >= len(data):
        return JsonSignaturePlan(
            accepted=False,
            kind="empty",
            has_utf8_bom=has_bom,
            sniffed_length=min(len(data), READ_CHUNK_SIZE),
            first_token_offset=None,
            first_token=None,
            read_chunk_size=READ_CHUNK_SIZE,
            evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
        )
    token = chr(data[offset])
    if token == "{":
        kind: JsonSignatureKind = "object"
    elif token == "[":
        kind = "array"
    elif token == '"' or token in "-0123456789tfn":
        kind = "scalar"
    else:
        kind = "unknown"
    return JsonSignaturePlan(
        accepted=kind != "empty" and kind != "unknown",
        kind=kind,
        has_utf8_bom=has_bom,
        sniffed_length=min(len(data), READ_CHUNK_SIZE),
        first_token_offset=offset,
        first_token=token,
        read_chunk_size=READ_CHUNK_SIZE,
        evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
    )


def _database_objects_from_root(
    node: _JsonNode,
    traversal: list[JsonTraversalPlan],
) -> tuple[JsonTopLevelModel, tuple[_DatabaseObject, ...], int]:
    if isinstance(node, _JsonObjectNode):
        traversal.append(
            JsonTraversalPlan(
                action="wrap_top_level_hash",
                target="$",
                byte_range=(node.start, node.end),
                reason="ReadJSON wraps a top-level HASH as a one-item database array.",
                evidence_ids=(IMPORT_JSON_DATABASE_SOURCE,),
            )
        )
        return "single_database_object", (_database_object_for_node(node, traversal),), 0
    if isinstance(node, _JsonArrayNode):
        traversal.append(
            JsonTraversalPlan(
                action="iterate_top_level_array",
                target="$",
                byte_range=(node.start, node.end),
                reason="ReadJSON iterates top-level ARRAY items and keeps only HASH entries.",
                evidence_ids=(IMPORT_JSON_DATABASE_SOURCE,),
            )
        )
        objects: list[_DatabaseObject] = []
        skipped = 0
        for index, item in enumerate(node.items):
            if isinstance(item, _JsonObjectNode):
                objects.append(_database_object_for_node(item, traversal))
            else:
                skipped += 1
                traversal.append(
                    JsonTraversalPlan(
                        action="skip_top_level_array_item",
                        target=f"$[{index}]",
                        byte_range=node_range(item),
                        reason=(
                            "ReadJSON ignores top-level ARRAY items that are not HASH references."
                        ),
                        evidence_ids=(IMPORT_JSON_DATABASE_SOURCE,),
                    )
                )
        return "database_object_array", tuple(objects), skipped
    return "unsupported_scalar", (), 0


def _database_object_for_node(
    node: _JsonObjectNode,
    traversal: list[JsonTraversalPlan],
) -> _DatabaseObject:
    exact = _find_member(node, "SourceFile")
    if exact is not None:
        source_file = _source_file_value(exact.value)
        return _DatabaseObject(source_file, node)
    folded = _find_member_case_insensitive(node, "SourceFile")
    if folded is not None:
        traversal.append(
            JsonTraversalPlan(
                action="case_fix_source_file",
                target=folded.key,
                byte_range=folded.key_range,
                reason=(
                    'ReadJSON fixes the key case to "SourceFile" when a '
                    "case-insensitive match exists."
                ),
                evidence_ids=(IMPORT_JSON_DATABASE_SOURCE,),
            )
        )
        return _DatabaseObject(_source_file_value(folded.value), node)
    traversal.append(
        JsonTraversalPlan(
            action="default_source_file",
            target="SourceFile",
            byte_range=None,
            reason='ReadJSON assumes SourceFile "*" when no SourceFile key exists.',
            evidence_ids=(IMPORT_JSON_DATABASE_SOURCE,),
        )
    )
    return _DatabaseObject("*", node)


def _collect_database_entries(
    database_objects: tuple[_DatabaseObject, ...],
    entries: list[JsonDatabaseEntryPlan],
    traversal: list[JsonTraversalPlan],
    missing_tag_value: str | None,
    charset: str,
) -> None:
    by_source_file: dict[str, _JsonObjectNode] = {}
    for item in database_objects:
        by_source_file[item.source_file] = item.node
    for source_file in sorted(by_source_file):
        node = by_source_file[source_file]
        for member in node.members:
            if member.key == "SourceFile" and _source_file_value(member.value) == "*":
                traversal.append(
                    JsonTraversalPlan(
                        action="skip_auto_source_file",
                        target="SourceFile",
                        byte_range=node_range(member.value),
                        reason='ProcessJSON ignores generated SourceFile when its value is "*".',
                        evidence_ids=(JSON_PROCESS_SOURCE,),
                    )
                )
                continue
            if member.key.lower() == "sourcefile" and member.key != "SourceFile":
                continue
            if _matches_missing_value(member.value, missing_tag_value):
                traversal.append(
                    JsonTraversalPlan(
                        action="skip_missing_value",
                        target=member.key,
                        byte_range=node_range(member.value),
                        reason="ReadJSON converts top-level MissingTagValue matches to undef.",
                        evidence_ids=(IMPORT_JSON_DATABASE_SOURCE, JSON_PROCESS_TAG_SOURCE),
                    )
                )
                continue
            _process_tag(
                source_file,
                member.key,
                (member.key,),
                member.value,
                entries,
                traversal,
                flat=False,
                list_item=False,
                charset=charset,
            )


def _process_tag(
    source_file: str,
    tag: str,
    path_components: tuple[str, ...],
    node: _JsonNode,
    entries: list[JsonDatabaseEntryPlan],
    traversal: list[JsonTraversalPlan],
    *,
    flat: bool,
    list_item: bool,
    charset: str,
) -> None:
    if isinstance(node, _JsonObjectNode):
        traversal.append(
            JsonTraversalPlan(
                action="traverse_hash",
                target=tag,
                byte_range=(node.start, node.end),
                reason="ProcessTag expands HASH values into flattened child tag paths.",
                evidence_ids=(JSON_PROCESS_TAG_SOURCE,),
            )
        )
        for member in node.members:
            child_tag = _flatten_child_tag(tag, member.key)
            _process_tag(
                source_file,
                child_tag,
                (*path_components, member.key),
                member.value,
                entries,
                traversal,
                flat=True,
                list_item=list_item,
                charset=charset,
            )
        return
    if isinstance(node, _JsonArrayNode):
        traversal.append(
            JsonTraversalPlan(
                action="traverse_array",
                target=tag,
                byte_range=(node.start, node.end),
                reason="ProcessTag repeats ARRAY values under the same tag with the List flag.",
                evidence_ids=(JSON_PROCESS_TAG_SOURCE,),
            )
        )
        for item in node.items:
            _process_tag(
                source_file,
                tag,
                path_components,
                item,
                entries,
                traversal,
                flat=flat,
                list_item=True,
                charset=charset,
            )
        return
    value = JsonValuePlan(
        kind=node.kind,
        display_value=node.display_value,
        raw_text=node.raw_text,
        raw_bytes=node.raw_bytes,
        byte_range=(node.start, node.end),
        charset=node.charset or charset if node.kind == "string" else node.charset,
        escape_sequences=node.escapes,
        evidence_ids=(
            IMPORT_JSON_CHARSET_SOURCE if node.escapes else IMPORT_JSON_TOKEN_SOURCE,
            JSON_PROCESS_TAG_SOURCE,
        ),
    )
    entries.append(
        JsonDatabaseEntryPlan(
            source_file=source_file,
            tag_id=_found_tag_id(tag),
            generated_name=_generated_tag_name(tag),
            path_components=path_components,
            value=value,
            flat=flat,
            list_item=list_item,
            evidence_ids=(JSON_FOUND_TAG_SOURCE, JSON_PROCESS_TAG_SOURCE),
        )
    )
    traversal.append(
        JsonTraversalPlan(
            action="emit_scalar_tag",
            target=tag,
            byte_range=(node.start, node.end),
            reason="ProcessTag emits defined scalar values with FoundTag.",
            evidence_ids=(JSON_PROCESS_TAG_SOURCE, JSON_FOUND_TAG_SOURCE),
        )
    )
    traversal.append(
        JsonTraversalPlan(
            action="preserve_raw_token",
            target=tag,
            byte_range=(node.start, node.end),
            reason="The transaction planner preserves the original scalar token bytes.",
            evidence_ids=(IMPORT_JSON_TOKEN_SOURCE,),
        )
    )


def _flatten_child_tag(parent: str, child: str) -> str:
    prefix = "_" if child[:1].isdigit() and parent[-1:].isdigit() else ""
    candidate = parent + prefix + child[:1].upper() + child[1:]
    return re.sub(
        r"([^a-zA-Z])([a-z])",
        lambda match: match.group(1) + match.group(2).upper(),
        candidate,
    )


def _found_tag_id(tag: str) -> str:
    match = re.fullmatch(
        r"settings\w{8}-\w{4}-\w{4}-\w{4}-\w{12}(Data|Metadata.+)",
        tag,
    )
    if match is not None:
        return "ON1_Settings" + match.group(1)
    return tag


def _generated_tag_name(tag: str) -> str:
    name = _found_tag_id(tag).replace(":", "_")
    name = re.sub(r"^c2pa", "C2PA", name, flags=re.IGNORECASE)
    words = re.split(r"[^0-9A-Za-z]+", name)
    return "".join(word[:1].upper() + word[1:] for word in words if word)


def _source_file_value(node: _JsonNode) -> str:
    if isinstance(node, _JsonScalarNode):
        return node.display_value
    return "*"


def _matches_missing_value(node: _JsonNode, missing_tag_value: str | None) -> bool:
    return (
        missing_tag_value is not None
        and isinstance(node, _JsonScalarNode)
        and node.display_value == missing_tag_value
    )


def _find_member(node: _JsonObjectNode, key: str) -> _JsonObjectMember | None:
    for member in node.members:
        if member.key == key:
            return member
    return None


def _find_member_case_insensitive(node: _JsonObjectNode, key: str) -> _JsonObjectMember | None:
    folded = key.lower()
    for member in node.members:
        if member.key.lower() == folded:
            return member
    return None


def _decode_exiftool_base64(value: str) -> bytes | None:
    if re.fullmatch(r"base64:[A-Za-z0-9+/]*={0,2}", value) is None:
        return None
    if len(value) % 4 != 3:
        return None
    try:
        return base64.b64decode(value[7:], validate=True)
    except binascii.Error:
        return None


def _looks_numeric(value: str) -> bool:
    return re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", value) is not None


def node_kind(node: _JsonNode) -> JsonValueKind:
    if isinstance(node, _JsonObjectNode):
        return "dict"
    if isinstance(node, _JsonArrayNode):
        return "array"
    return node.kind


def node_range(node: _JsonNode) -> tuple[int, int]:
    return (node.start, node.end)


def parse_gate(failure: _ParseFailure) -> JsonEmissionGate:
    return JsonEmissionGate(
        code=failure.code,
        reason=failure.reason,
        evidence_ids=failure.evidence_ids,
    )


def json_range(value: tuple[int, int] | None) -> JsonArray | None:
    if value is None:
        return None
    return [value[0], value[1]]


def gate_to_json(gate: JsonEmissionGate) -> JsonObject:
    return {
        "code": gate.code,
        "reason": gate.reason,
    }


def blocker_to_json(blocker: JsonRewriteBlocker) -> JsonObject:
    return {
        "code": blocker.code,
        "reason": blocker.reason,
    }


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return list(values)


install_evidence_reference_compat(globals())
