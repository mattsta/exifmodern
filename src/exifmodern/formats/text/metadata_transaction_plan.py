"""Source-backed, non-mutating TXT/CSV metadata transaction plans.

The modeled behavior is grounded in ExifTool's Text implementation:
``/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/Text.pm``. Text.pm has no
writer; it deduces file-level TXT/CSV characteristics from source bytes. This
planner therefore preserves all bytes, describes extraction routes, and gates
byte emission or requested rewrites behind explicit blockers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

TEXT_PM_SOURCE_PATH = "lib/Image/ExifTool/Text.pm"
TEXT_STAT_LIMIT_BYTES = 20_000_000
TEXT_CSV_ROW_LIMIT = 1000

type TextFileType = Literal["TXT", "CSV"]
type TextPlanStatus = Literal["planned", "blocked"]
type TextEncodingName = Literal[
    "us-ascii",
    "utf-8",
    "iso-8859-1",
    "unknown-8bit",
    "utf-16le",
    "utf-16be",
    "utf-32le",
    "utf-32be",
]
type TextNewlineSequence = Literal["\r\n", "\r", "\n", ""]
type TextNewlineLabel = Literal["Windows CRLF", "Macintosh CR", "Unix LF", "(none)"]
type TextDelimiter = Literal["", ",", ";", "\t"]
type TextDelimiterLabel = Literal["(none)", "Comma", "Semicolon", "Tab"]
type TextQuoting = Literal["", '"', "'"]
type TextQuotingLabel = Literal["(none)", "Double quotes", "Single quotes"]
type TextRouteKind = Literal[
    "mime_encoding",
    "byte_order_mark",
    "newlines",
    "csv_statistics",
    "text_statistics",
    "unknown_line_preservation",
]
type TextRouteAction = Literal[
    "extract",
    "skip_fast_scan",
    "skip_multibyte_unicode",
    "skip_large_text_file",
    "preserve",
]
type TextGateCode = Literal[
    "empty_text_data",
    "binary_control_character_without_unicode_bom",
    "output_emission_requires_explicit_opt_in",
    "text_metadata_rewrite_not_supported",
]
type TextRewriteOperation = Literal["replace", "delete", "insert"]

TEXT_TABLE_SOURCE = "text.table"
TEXT_EMPTY_SOURCE = "text.empty"
TEXT_ENCODING_SOURCE = "text.encoding"
TEXT_FAST_SOURCE = "text.fast"
TEXT_CSV_SOURCE = "text.csv"
TEXT_LINE_WORD_SOURCE = "text.line.word"
TEXT_READ_ONLY_SOURCE = "text.read.only"

TEXT_TRANSACTION_SOURCES = (
    TEXT_TABLE_SOURCE,
    TEXT_EMPTY_SOURCE,
    TEXT_ENCODING_SOURCE,
    TEXT_FAST_SOURCE,
    TEXT_CSV_SOURCE,
    TEXT_LINE_WORD_SOURCE,
    TEXT_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class TextEmissionGate:
    code: TextGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TextRewriteRequest:
    tag_name: str
    operation: TextRewriteOperation
    replacement_value: str | None = None


@dataclass(frozen=True)
class TextMetadataRoutePlan:
    kind: TextRouteKind
    tag_names: tuple[str, ...]
    action: TextRouteAction
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TextEncodingPlan:
    encoding: TextEncodingName | None
    is_utf8_state: int | None
    has_byte_order_mark: bool | None
    first_weird_control_offset: int | None
    first_weird_control_byte: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TextNewlinePlan:
    sequence: TextNewlineSequence
    label: TextNewlineLabel
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TextLineBoundaryPlan:
    index: int
    start_offset: int
    end_offset: int
    newline: TextNewlineSequence
    raw_bytes: bytes
    preserves_unknown_line: bool
    key_value_boundary_offset: int | None
    extracted_tag_name: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TextUnknownLinePreservationPlan:
    line_count: int
    raw_source_length: int
    key_value_metadata_extraction_supported: bool
    lines: tuple[TextLineBoundaryPlan, ...]
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TextCsvStatisticsPlan:
    delimiter: TextDelimiter
    delimiter_label: TextDelimiterLabel
    quoting: TextQuoting
    quoting_label: TextQuotingLabel
    row_count: int | None
    column_count: int
    row_count_capped: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TextStatisticsPlan:
    line_count: int | None
    word_count: int | None
    skipped_reason: TextRouteAction | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TextMetadataTransactionPlan:
    status: TextPlanStatus
    file_type: TextFileType
    encoding: TextEncodingPlan
    newlines: TextNewlinePlan
    routes: tuple[TextMetadataRoutePlan, ...]
    unknown_line_preservation: TextUnknownLinePreservationPlan
    csv_statistics: TextCsvStatisticsPlan | None
    text_statistics: TextStatisticsPlan | None
    rewrite_requests: tuple[TextRewriteRequest, ...]
    output_emission_gates: tuple[TextEmissionGate, ...]
    output_bytes: bytes | None
    evidence_ids: tuple[str, ...] = TEXT_TRANSACTION_SOURCES

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
            raise ValueError(f"Text metadata transaction output is gated: {gate_codes}")
        return self.output_bytes


@dataclass(frozen=True)
class _EncodingResult:
    plan: TextEncodingPlan
    newline: TextNewlineSequence
    gate: TextEmissionGate | None


def build_text_metadata_transaction_plan(
    data: bytes,
    *,
    file_type: TextFileType = "TXT",
    fast_scan: int = 0,
    rewrite_requests: tuple[TextRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> TextMetadataTransactionPlan:
    """Build a non-mutating plan for ExifTool-compatible TXT/CSV metadata."""

    encoding_result = _classify_encoding(data)
    gates: list[TextEmissionGate] = []
    if encoding_result.gate is not None:
        gates.append(encoding_result.gate)

    if not allow_output_emission:
        gates.append(
            TextEmissionGate(
                code="output_emission_requires_explicit_opt_in",
                reason=(
                    "Text metadata transaction plans preserve bytes unless emission is "
                    "explicitly allowed."
                ),
                evidence_ids=(TEXT_READ_ONLY_SOURCE,),
            )
        )

    if rewrite_requests:
        gates.append(
            TextEmissionGate(
                code="text_metadata_rewrite_not_supported",
                reason=(
                    "Text.pm derives metadata from analysis and provides no source-backed "
                    "TXT/CSV metadata writer."
                ),
                evidence_ids=(TEXT_READ_ONLY_SOURCE,),
            )
        )

    newline_plan = TextNewlinePlan(
        sequence=encoding_result.newline,
        label=_newline_label(encoding_result.newline),
        evidence_ids=(TEXT_TABLE_SOURCE, TEXT_ENCODING_SOURCE),
    )
    preservation = _build_line_preservation(data)

    csv_statistics: TextCsvStatisticsPlan | None = None
    text_statistics: TextStatisticsPlan | None = None
    if encoding_result.gate is None:
        if file_type == "CSV":
            csv_statistics = _build_csv_statistics(data, encoding_result.plan, fast_scan)
        else:
            text_statistics = _build_text_statistics(data, encoding_result.plan, fast_scan)

    routes = _build_routes(file_type, fast_scan, len(data), encoding_result.plan)
    structural_gate_codes = {"empty_text_data", "binary_control_character_without_unicode_bom"}
    status: TextPlanStatus = (
        "blocked" if any(gate.code in structural_gate_codes for gate in gates) else "planned"
    )
    output_bytes = data if status == "planned" and allow_output_emission and not gates else None
    return TextMetadataTransactionPlan(
        status=status,
        file_type=file_type,
        encoding=encoding_result.plan,
        newlines=newline_plan,
        routes=routes,
        unknown_line_preservation=preservation,
        csv_statistics=csv_statistics,
        text_statistics=text_statistics,
        rewrite_requests=rewrite_requests,
        output_emission_gates=tuple(gates),
        output_bytes=output_bytes,
    )


plan_text_metadata_transaction = build_text_metadata_transaction_plan


def _classify_encoding(data: bytes) -> _EncodingResult:
    if not data:
        return _EncodingResult(
            plan=TextEncodingPlan(None, None, None, None, None, (TEXT_EMPTY_SOURCE,)),
            newline="",
            gate=TextEmissionGate(
                code="empty_text_data",
                reason="ExifTool does not call empty data a text file.",
                evidence_ids=(TEXT_EMPTY_SOURCE,),
            ),
        )

    control = _first_weird_control(data)
    if control is not None:
        offset, byte = control
        unicode_encoding = _unicode_bom_encoding(data)
        if unicode_encoding is None:
            return _EncodingResult(
                plan=TextEncodingPlan(
                    None,
                    None,
                    None,
                    offset,
                    byte,
                    (TEXT_ENCODING_SOURCE,),
                ),
                newline="",
                gate=TextEmissionGate(
                    code="binary_control_character_without_unicode_bom",
                    reason=(
                        "ExifTool treats unusual control bytes as probably not text "
                        "unless a UTF-16/UTF-32 BOM is present."
                    ),
                    evidence_ids=(TEXT_ENCODING_SOURCE,),
                ),
            )
        return _EncodingResult(
            plan=TextEncodingPlan(
                unicode_encoding,
                None,
                True,
                offset,
                byte,
                (TEXT_ENCODING_SOURCE,),
            ),
            newline=_encoded_newline(data, unicode_encoding),
            gate=None,
        )

    utf8_state = _is_utf8_state(data)
    if utf8_state == 0:
        encoding: TextEncodingName = "us-ascii"
        has_bom: bool | None = None
    elif utf8_state > 0:
        encoding = "utf-8"
        has_bom = data.startswith(b"\xef\xbb\xbf")
    elif not _has_c1_control(data):
        encoding = "iso-8859-1"
        has_bom = None
    else:
        encoding = "unknown-8bit"
        has_bom = None

    return _EncodingResult(
        plan=TextEncodingPlan(
            encoding,
            utf8_state,
            has_bom,
            None,
            None,
            (TEXT_ENCODING_SOURCE,),
        ),
        newline=_raw_newline(data),
        gate=None,
    )


def _first_weird_control(data: bytes) -> tuple[int, int] | None:
    for offset, byte in enumerate(data):
        if byte <= 0x06 or 0x0E <= byte <= 0x1A or 0x1C <= byte <= 0x1F or byte == 0x7F:
            return offset, byte
    return None


def _unicode_bom_encoding(data: bytes) -> TextEncodingName | None:
    if data.startswith(b"\xff\xfe\x00\x00"):
        return "utf-32le"
    if data.startswith(b"\x00\x00\xfe\xff"):
        return "utf-32be"
    if data.startswith(b"\xff\xfe"):
        return "utf-16le"
    if data.startswith(b"\xfe\xff"):
        return "utf-16be"
    return None


def _encoded_newline(data: bytes, encoding: TextEncodingName) -> TextNewlineSequence:
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        text = data.decode(encoding, errors="ignore")
    return _first_newline_in_text(text)


def _raw_newline(data: bytes) -> TextNewlineSequence:
    crlf = data.find(b"\r\n")
    cr = data.find(b"\r")
    lf = data.find(b"\n")
    candidates: list[tuple[int, TextNewlineSequence]] = []
    if crlf >= 0:
        candidates.append((crlf, "\r\n"))
    if cr >= 0:
        candidates.append((cr, "\r"))
    if lf >= 0:
        candidates.append((lf, "\n"))
    if not candidates:
        return ""
    return min(candidates, key=lambda item: item[0])[1]


def _first_newline_in_text(text: str) -> TextNewlineSequence:
    crlf = text.find("\r\n")
    cr = text.find("\r")
    lf = text.find("\n")
    candidates: list[tuple[int, TextNewlineSequence]] = []
    if crlf >= 0:
        candidates.append((crlf, "\r\n"))
    if cr >= 0:
        candidates.append((cr, "\r"))
    if lf >= 0:
        candidates.append((lf, "\n"))
    if not candidates:
        return ""
    return min(candidates, key=lambda item: item[0])[1]


def _is_utf8_state(data: bytes) -> int:
    if data.startswith(b"\xef\xbb\xbf"):
        payload = data[3:]
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError:
            return -1
        return 1
    if all(byte < 0x80 for byte in data):
        return 0
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return -1
    return 1


def _has_c1_control(data: bytes) -> bool:
    return any(0x80 <= byte <= 0x9F for byte in data)


def _newline_label(sequence: TextNewlineSequence) -> TextNewlineLabel:
    if sequence == "\r\n":
        return "Windows CRLF"
    if sequence == "\r":
        return "Macintosh CR"
    if sequence == "\n":
        return "Unix LF"
    return "(none)"


def _delimiter_label(delimiter: TextDelimiter) -> TextDelimiterLabel:
    if delimiter == ",":
        return "Comma"
    if delimiter == ";":
        return "Semicolon"
    if delimiter == "\t":
        return "Tab"
    return "(none)"


def _quoting_label(quoting: TextQuoting) -> TextQuotingLabel:
    if quoting == '"':
        return "Double quotes"
    if quoting == "'":
        return "Single quotes"
    return "(none)"


def _build_line_preservation(data: bytes) -> TextUnknownLinePreservationPlan:
    lines: list[TextLineBoundaryPlan] = []
    offset = 0
    for raw_line in data.splitlines(keepends=True):
        newline = _line_newline(raw_line)
        lines.append(
            TextLineBoundaryPlan(
                index=len(lines),
                start_offset=offset,
                end_offset=offset + len(raw_line),
                newline=newline,
                raw_bytes=raw_line,
                preserves_unknown_line=True,
                key_value_boundary_offset=None,
                extracted_tag_name=None,
                evidence_ids=(TEXT_TABLE_SOURCE, TEXT_LINE_WORD_SOURCE),
            )
        )
        offset += len(raw_line)
    if offset < len(data):
        raw_line = data[offset:]
        lines.append(
            TextLineBoundaryPlan(
                index=len(lines),
                start_offset=offset,
                end_offset=len(data),
                newline="",
                raw_bytes=raw_line,
                preserves_unknown_line=True,
                key_value_boundary_offset=None,
                extracted_tag_name=None,
                evidence_ids=(TEXT_TABLE_SOURCE, TEXT_LINE_WORD_SOURCE),
            )
        )
    return TextUnknownLinePreservationPlan(
        line_count=len(lines),
        raw_source_length=len(data),
        key_value_metadata_extraction_supported=False,
        lines=tuple(lines),
        reason=(
            "Text.pm derives aggregate TXT/CSV file characteristics; it does not "
            "interpret arbitrary lines as key/value metadata."
        ),
        evidence_ids=(TEXT_TABLE_SOURCE, TEXT_LINE_WORD_SOURCE),
    )


def _line_newline(raw_line: bytes) -> TextNewlineSequence:
    if raw_line.endswith(b"\r\n"):
        return "\r\n"
    if raw_line.endswith(b"\r"):
        return "\r"
    if raw_line.endswith(b"\n"):
        return "\n"
    return ""


def _build_csv_statistics(
    data: bytes,
    encoding: TextEncodingPlan,
    fast_scan: int,
) -> TextCsvStatisticsPlan | None:
    if fast_scan or encoding.is_utf8_state is None:
        return None
    text = _decode_8bit_text(data, encoding)
    lines = text.splitlines(keepends=True)
    if not lines:
        lines = [text]

    delimiter: TextDelimiter = ""
    quote: TextQuoting = ""
    column_count = 1
    row_count: int | None = 0
    for line in lines:
        if row_count is None:
            break
        if row_count == 0:
            delimiter, column_count, quote = _first_csv_line_shape(line)
        elif quote == "":
            quote = _find_quote(line, delimiter)
        row_count += 1
        if row_count == TEXT_CSV_ROW_LIMIT:
            row_count = None
            break

    return TextCsvStatisticsPlan(
        delimiter=delimiter,
        delimiter_label=_delimiter_label(delimiter),
        quoting=quote,
        quoting_label=_quoting_label(quote),
        row_count=row_count,
        column_count=column_count,
        row_count_capped=row_count is None,
        evidence_ids=(TEXT_CSV_SOURCE,),
    )


def _first_csv_line_shape(line: str) -> tuple[TextDelimiter, int, TextQuoting]:
    counts = {",": line.count(","), ";": line.count(";"), "\t": line.count("\t")}
    delimiter: TextDelimiter
    if counts[","] > counts[";"] and counts[","] > counts["\t"]:
        delimiter = ","
    elif counts[";"] > counts["\t"]:
        delimiter = ";"
    elif counts["\t"]:
        delimiter = "\t"
    else:
        return "", 1, ""

    adjusted_count = counts[delimiter]
    quote: TextQuoting = ""
    body = line.rstrip("\r\n")
    delimiter_pattern = re.escape(delimiter)
    quoted_pattern = rf"(^|{delimiter_pattern})([\"'])(.*?)\2(?={delimiter_pattern}|$)"
    quoted_field = re.compile(quoted_pattern, re.DOTALL)
    for match in quoted_field.finditer(body):
        quote = _quote_from_match(match.group(2))
        adjusted_count -= match.group(3).count(delimiter)
    return delimiter, adjusted_count + 1, quote


def _find_quote(line: str, delimiter: TextDelimiter) -> TextQuoting:
    if delimiter == "":
        return ""
    body = line.rstrip("\r\n")
    delimiter_pattern = re.escape(delimiter)
    quoted_pattern = rf"(^|{delimiter_pattern})([\"'])(.*?)\2(?={delimiter_pattern}|$)"
    quoted_field = re.search(quoted_pattern, body, re.DOTALL)
    if quoted_field is None:
        return ""
    return _quote_from_match(quoted_field.group(2))


def _quote_from_match(value: str) -> TextQuoting:
    if value == '"':
        return '"'
    if value == "'":
        return "'"
    return ""


def _build_text_statistics(
    data: bytes,
    encoding: TextEncodingPlan,
    fast_scan: int,
) -> TextStatisticsPlan:
    if fast_scan:
        return TextStatisticsPlan(None, None, "skip_fast_scan", (TEXT_FAST_SOURCE,))
    if encoding.is_utf8_state is None:
        return TextStatisticsPlan(None, None, "skip_multibyte_unicode", (TEXT_FAST_SOURCE,))
    if len(data) > TEXT_STAT_LIMIT_BYTES:
        return TextStatisticsPlan(None, None, "skip_large_text_file", (TEXT_LINE_WORD_SOURCE,))
    text = _decode_8bit_text(data, encoding)
    lines = text.splitlines(keepends=True)
    line_count = len(lines) if lines else (1 if text else 0)
    return TextStatisticsPlan(
        line_count=line_count,
        word_count=len(re.findall(r"\S+", text)),
        skipped_reason=None,
        evidence_ids=(TEXT_LINE_WORD_SOURCE,),
    )


def _decode_8bit_text(data: bytes, encoding: TextEncodingPlan) -> str:
    if encoding.encoding == "utf-8":
        return data.decode("utf-8", errors="replace")
    return data.decode("latin-1")


def _build_routes(
    file_type: TextFileType,
    fast_scan: int,
    data_length: int,
    encoding: TextEncodingPlan,
) -> tuple[TextMetadataRoutePlan, ...]:
    routes: list[TextMetadataRoutePlan] = [
        TextMetadataRoutePlan(
            kind="mime_encoding",
            tag_names=("MIMEEncoding",),
            action="extract",
            reason="ProcessTXT always handles MIMEEncoding after text classification.",
            evidence_ids=(TEXT_ENCODING_SOURCE,),
        )
    ]
    post_encoding_action: TextRouteAction = "extract" if fast_scan < 3 else "skip_fast_scan"
    routes.append(
        TextMetadataRoutePlan(
            kind="byte_order_mark",
            tag_names=("ByteOrderMark",),
            action=post_encoding_action,
            reason="ByteOrderMark is emitted only after the FastScan level-3 early exit.",
            evidence_ids=(TEXT_FAST_SOURCE,),
        )
    )
    routes.append(
        TextMetadataRoutePlan(
            kind="newlines",
            tag_names=("Newlines",),
            action=post_encoding_action,
            reason="Newlines is emitted only after the FastScan level-3 early exit.",
            evidence_ids=(TEXT_FAST_SOURCE, TEXT_ENCODING_SOURCE),
        )
    )

    stats_action: TextRouteAction
    if fast_scan:
        stats_action = "skip_fast_scan"
    elif encoding.is_utf8_state is None:
        stats_action = "skip_multibyte_unicode"
    elif file_type == "TXT" and data_length > TEXT_STAT_LIMIT_BYTES:
        stats_action = "skip_large_text_file"
    else:
        stats_action = "extract"

    if file_type == "CSV":
        routes.append(
            TextMetadataRoutePlan(
                kind="csv_statistics",
                tag_names=("Delimiter", "Quoting", "ColumnCount", "RowCount"),
                action=stats_action,
                reason="CSV statistics are generated only after fast-scan and 8-bit gates.",
                evidence_ids=(TEXT_CSV_SOURCE, TEXT_FAST_SOURCE),
            )
        )
    else:
        routes.append(
            TextMetadataRoutePlan(
                kind="text_statistics",
                tag_names=("LineCount", "WordCount"),
                action=stats_action,
                reason="TXT line and word statistics are generated only after source gates.",
                evidence_ids=(TEXT_LINE_WORD_SOURCE, TEXT_FAST_SOURCE),
            )
        )

    routes.append(
        TextMetadataRoutePlan(
            kind="unknown_line_preservation",
            tag_names=("UnknownLine",),
            action="preserve",
            reason="Text.pm does not parse arbitrary line key/value metadata.",
            evidence_ids=(TEXT_TABLE_SOURCE, TEXT_LINE_WORD_SOURCE),
        )
    )
    return tuple(routes)
