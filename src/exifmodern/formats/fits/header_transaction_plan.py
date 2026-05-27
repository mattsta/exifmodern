"""Source-grounded, non-mutating FITS header/card transaction plans.

The planner mirrors the FITS reader in ExifTool's ``FITS.pm``: it validates the
initial ``SIMPLE`` card, parses fixed-width 80-byte cards until ``END``, models
``COMMENT``/``HISTORY`` and ``CONTINUE`` handling, preserves unknown data after
the padded header block, and keeps byte emission behind explicit gates.  It does
not rewrite FITS cards.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

FITS_CARD_SIZE = 80
FITS_BLOCK_SIZE = 2880
FITS_SIMPLE_PREFIX = "SIMPLE  =" + (" " * 20) + "T"
FITS_VALID_KEYWORD_CHARS = frozenset("-_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
FITS_EXPONENT_TRANSLATION = str.maketrans("DE", "ee")

type FitsPlanStatus = Literal["planned", "unsupported"]
type FitsHeaderKind = Literal["primary", "extension", "unsupported"]
type FitsCardKind = Literal[
    "keyword",
    "comment",
    "history",
    "continue",
    "end",
    "hierarchical",
    "ignored",
    "invalid",
]
type FitsValueKind = Literal[
    "quoted_string",
    "unquoted",
    "logical",
    "undefined",
    "commentary",
    "continuation",
    "end",
    "ignored",
]
type FitsActionKind = Literal[
    "validate_initial_card",
    "parse_80_byte_cards",
    "parse_keyword_value",
    "parse_commentary_card",
    "parse_continue_card",
    "preserve_hierarchical_card",
    "preserve_duplicate_keyword_order",
    "preserve_end_card",
    "preserve_header_padding",
    "preserve_data_blocks",
]
type FitsEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_initial_card",
    "unsupported_initial_card",
    "extension_header_without_primary_simple",
    "truncated_fits_header",
    "missing_end_card",
    "invalid_keyword",
    "truncated_header_padding",
]
type FitsRewriteBlockerCode = Literal[
    "fits_card_rewrite_not_implemented",
    "duplicate_keyword_order_must_be_preserved",
    "comment_history_cards_are_order_sensitive",
    "continue_cards_require_exact_card_reflow",
    "hierarchical_cards_are_preserve_only",
]
type FitsReadValue = str

FITS_TAG_TABLE_SOURCE = "fits.tag.table"
FITS_INITIAL_SIMPLE_SOURCE = "fits.initial.simple"
FITS_CARD_LOOP_SOURCE = "fits.card.loop"
FITS_COMMENT_HISTORY_SOURCE = "fits.comment.history"
FITS_TAG_ROUTING_SOURCE = "fits.tag.routing"
FITS_VALUE_PARSE_SOURCE = "fits.value.parse"

FITS_TRANSACTION_SOURCES = (
    FITS_TAG_TABLE_SOURCE,
    FITS_INITIAL_SIMPLE_SOURCE,
    FITS_CARD_LOOP_SOURCE,
    FITS_COMMENT_HISTORY_SOURCE,
    FITS_TAG_ROUTING_SOURCE,
    FITS_VALUE_PARSE_SOURCE,
)


@dataclass(frozen=True)
class FitsInitialCardPlan:
    header_kind: FitsHeaderKind
    keyword: str
    raw_value: str | None
    is_exiftool_primary_header: bool
    reason: FitsEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "header_kind": self.header_kind,
            "is_exiftool_primary_header": self.is_exiftool_primary_header,
            "keyword": self.keyword,
            "raw_value": self.raw_value,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FitsValueRecord:
    keyword: str
    value_kind: FitsValueKind
    raw_value: str
    value: str | None
    comment: str | None
    emits_metadata: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "comment": self.comment,
            "emits_metadata": self.emits_metadata,
            "keyword": self.keyword,
            "raw_value": self.raw_value,
            "value": self.value,
            "value_kind": self.value_kind,
        }


@dataclass(frozen=True)
class FitsCardPlan:
    index: int
    offset: int
    raw_card: bytes
    keyword: str
    card_kind: FitsCardKind
    has_assignment: bool
    value_record: FitsValueRecord | None
    occurrence_index: int | None
    duplicate_count: int
    warnings: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    @property
    def byte_range(self) -> tuple[int, int]:
        return (self.offset, self.offset + FITS_CARD_SIZE)

    @property
    def text(self) -> str:
        return decode_card(self.raw_card)

    def to_json(self) -> JsonObject:
        return {
            "byte_range": json_range(self.byte_range),
            "card_kind": self.card_kind,
            "duplicate_count": self.duplicate_count,
            "has_assignment": self.has_assignment,
            "index": self.index,
            "keyword": self.keyword,
            "occurrence_index": self.occurrence_index,
            "raw_card": self.text,
            "value_record": None if self.value_record is None else self.value_record.to_json(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class FitsDuplicateKeywordPlan:
    keyword: str
    card_indexes: tuple[int, ...]
    duplicate_count: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "card_indexes": list(self.card_indexes),
            "duplicate_count": self.duplicate_count,
            "keyword": self.keyword,
        }


@dataclass(frozen=True)
class FitsBoundaryPlan:
    header_card_range: tuple[int, int] | None
    end_card_range: tuple[int, int] | None
    header_padding_range: tuple[int, int] | None
    header_block_range: tuple[int, int] | None
    data_block_range: tuple[int, int] | None
    header_padding_is_complete: bool
    header_padding_is_blank: bool | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "data_block_range": json_range(self.data_block_range),
            "end_card_range": json_range(self.end_card_range),
            "header_block_range": json_range(self.header_block_range),
            "header_card_range": json_range(self.header_card_range),
            "header_padding_is_blank": self.header_padding_is_blank,
            "header_padding_is_complete": self.header_padding_is_complete,
            "header_padding_range": json_range(self.header_padding_range),
        }


@dataclass(frozen=True)
class FitsOutputEmissionGate:
    code: FitsEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FitsRewriteBlocker:
    code: FitsRewriteBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FitsActionPlan:
    kind: FitsActionKind
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
class FitsReadTagRecord:
    keyword: str
    name: str
    group: str
    value: FitsReadValue
    occurrence_index: int
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "group": self.group,
            "keyword": self.keyword,
            "name": self.name,
            "occurrence_index": self.occurrence_index,
            "value": self.value,
        }


@dataclass(frozen=True)
class FitsHeaderTransactionPlan:
    status: FitsPlanStatus
    source_data: bytes
    initial_card: FitsInitialCardPlan
    cards: tuple[FitsCardPlan, ...]
    read_tags: tuple[FitsReadTagRecord, ...]
    duplicate_keywords: tuple[FitsDuplicateKeywordPlan, ...]
    boundaries: FitsBoundaryPlan
    actions: tuple[FitsActionPlan, ...]
    rewrite_blockers: tuple[FitsRewriteBlocker, ...]
    output_emission_gates: tuple[FitsOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def can_rewrite_metadata(self) -> bool:
        return False

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"FITS header transaction output is gated: {gate_codes}")
        return self.source_data

    def to_json(self) -> JsonObject:
        return {
            "actions": json_object_array(action.to_json() for action in self.actions),
            "boundaries": self.boundaries.to_json(),
            "can_emit_output": self.can_emit_output,
            "can_rewrite_metadata": self.can_rewrite_metadata,
            "cards": json_object_array(card.to_json() for card in self.cards),
            "duplicate_keywords": json_object_array(
                duplicate.to_json() for duplicate in self.duplicate_keywords
            ),
            "initial_card": self.initial_card.to_json(),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "read_tags": json_object_array(read_tag.to_json() for read_tag in self.read_tags),
            "rewrite_blockers": json_object_array(
                blocker.to_json() for blocker in self.rewrite_blockers
            ),
            "status": self.status,
        }


def build_fits_header_transaction_plan(
    fits_data: bytes,
    *,
    allow_output_emission: bool = False,
) -> FitsHeaderTransactionPlan:
    """Build a non-mutating FITS header/card transaction plan from in-memory bytes."""

    gates: list[FitsOutputEmissionGate] = []
    initial_card = build_initial_card_plan(fits_data)
    if initial_card.reason is not None:
        gates.append(
            FitsOutputEmissionGate(
                code=initial_card.reason,
                reason="Input does not satisfy ExifTool's initial FITS SIMPLE card gate.",
                evidence_ids=initial_card.evidence_ids,
            )
        )

    cards = parse_fits_cards(fits_data, gates) if len(fits_data) >= FITS_CARD_SIZE else ()
    duplicate_keywords = build_duplicate_keyword_plans(cards)
    cards = apply_duplicate_indexes(cards, duplicate_keywords)
    read_tags = build_fits_read_tags(cards)
    boundaries = build_boundary_plan(fits_data, cards, gates)
    actions = build_actions(cards, duplicate_keywords, boundaries)
    rewrite_blockers = build_rewrite_blockers(cards, duplicate_keywords)
    add_non_mutating_gate(gates, allow_output_emission)
    unique_gate_tuple = unique_emission_gates(tuple(gates))
    status: FitsPlanStatus = (
        "unsupported" if structural_gate_present(unique_gate_tuple) else "planned"
    )
    evidence_ids = unique_evidence_ids(
        (
            *FITS_TRANSACTION_SOURCES,
            *(evidence_id for card in cards for evidence_id in card.evidence_ids),
            *(
                evidence_id
                for duplicate in duplicate_keywords
                for evidence_id in duplicate.evidence_ids
            ),
            *(evidence_id for gate in unique_gate_tuple for evidence_id in gate.evidence_ids),
            *(evidence_id for action in actions for evidence_id in action.evidence_ids),
            *(evidence_id for blocker in rewrite_blockers for evidence_id in blocker.evidence_ids),
        )
    )
    return FitsHeaderTransactionPlan(
        status=status,
        source_data=fits_data,
        initial_card=initial_card,
        cards=cards,
        read_tags=read_tags,
        duplicate_keywords=duplicate_keywords,
        boundaries=boundaries,
        actions=actions,
        rewrite_blockers=rewrite_blockers,
        output_emission_gates=unique_gate_tuple,
        evidence_ids=evidence_ids,
    )


def build_initial_card_plan(fits_data: bytes) -> FitsInitialCardPlan:
    if len(fits_data) < FITS_CARD_SIZE:
        return FitsInitialCardPlan(
            header_kind="unsupported",
            keyword="",
            raw_value=None,
            is_exiftool_primary_header=False,
            reason="truncated_initial_card",
            evidence_ids=(FITS_INITIAL_SIMPLE_SOURCE,),
        )

    first_card = decode_card(fits_data[:FITS_CARD_SIZE])
    keyword = first_card[:8].rstrip(" ")
    raw_value = first_card[10:] if first_card[8:10] == "= " else None
    if first_card.startswith(FITS_SIMPLE_PREFIX) or (
        keyword == "SIMPLE" and raw_value is not None and raw_value.lstrip().startswith("T")
    ):
        return FitsInitialCardPlan(
            header_kind="primary",
            keyword=keyword,
            raw_value=raw_value,
            is_exiftool_primary_header=True,
            reason=None,
            evidence_ids=(FITS_INITIAL_SIMPLE_SOURCE,),
        )
    if keyword == "XTENSION" and first_card[8:10] == "= ":
        return FitsInitialCardPlan(
            header_kind="extension",
            keyword=keyword,
            raw_value=raw_value,
            is_exiftool_primary_header=False,
            reason="extension_header_without_primary_simple",
            evidence_ids=(FITS_INITIAL_SIMPLE_SOURCE,),
        )
    return FitsInitialCardPlan(
        header_kind="unsupported",
        keyword=keyword,
        raw_value=raw_value,
        is_exiftool_primary_header=False,
        reason="unsupported_initial_card",
        evidence_ids=(FITS_INITIAL_SIMPLE_SOURCE,),
    )


def parse_fits_cards(
    fits_data: bytes,
    gates: list[FitsOutputEmissionGate],
) -> tuple[FitsCardPlan, ...]:
    cards: list[FitsCardPlan] = []
    pending_continuation: FitsContinuationState | None = None
    offset = 0
    found_end = False

    while offset + FITS_CARD_SIZE <= len(fits_data):
        card = fits_data[offset : offset + FITS_CARD_SIZE]
        text = decode_card(card)
        keyword = text[:8].rstrip(" ")
        card_evidence_ids: tuple[str, ...] = (FITS_CARD_LOOP_SOURCE,)

        if keyword != "CONTINUE" and pending_continuation is not None:
            cards = close_pending_continuation(cards, pending_continuation)
            pending_continuation = None

        if keyword == "END":
            cards.append(
                FitsCardPlan(
                    index=len(cards),
                    offset=offset,
                    raw_card=card,
                    keyword=keyword,
                    card_kind="end",
                    has_assignment=False,
                    value_record=FitsValueRecord(
                        keyword=keyword,
                        value_kind="end",
                        raw_value="",
                        value=None,
                        comment=None,
                        emits_metadata=False,
                        evidence_ids=(FITS_CARD_LOOP_SOURCE,),
                    ),
                    occurrence_index=None,
                    duplicate_count=0,
                    warnings=(),
                    evidence_ids=card_evidence_ids,
                )
            )
            found_end = True
            break

        if not fits_keyword_is_valid(keyword):
            gates.append(
                FitsOutputEmissionGate(
                    code="invalid_keyword",
                    reason="FITS keyword contains characters outside ExifTool's accepted set.",
                    evidence_ids=(FITS_CARD_LOOP_SOURCE,),
                )
            )
            cards.append(
                FitsCardPlan(
                    index=len(cards),
                    offset=offset,
                    raw_card=card,
                    keyword=keyword,
                    card_kind="invalid",
                    has_assignment=False,
                    value_record=None,
                    occurrence_index=None,
                    duplicate_count=0,
                    warnings=("Format error in FITS header",),
                    evidence_ids=card_evidence_ids,
                )
            )
            break

        if keyword == "CONTINUE":
            continue_card, pending_continuation = parse_continue_card(
                len(cards), offset, card, text, pending_continuation
            )
            cards.append(continue_card)
        elif keyword == "COMMENT" or keyword == "HISTORY":
            cards.append(parse_commentary_card(len(cards), offset, card, text, keyword))
        elif text[8:10] != "= ":
            cards.append(parse_ignored_card(len(cards), offset, card, text, keyword))
        else:
            parsed_card, pending_continuation = parse_keyword_card(len(cards), offset, card, text)
            cards.append(parsed_card)

        offset += FITS_CARD_SIZE

    if not found_end:
        if offset + FITS_CARD_SIZE > len(fits_data):
            gates.append(
                FitsOutputEmissionGate(
                    code="truncated_fits_header",
                    reason="Input ended before ExifTool could read the next 80-byte FITS card.",
                    evidence_ids=(FITS_CARD_LOOP_SOURCE,),
                )
            )
        gates.append(
            FitsOutputEmissionGate(
                code="missing_end_card",
                reason="No END card was found before the FITS header parse stopped.",
                evidence_ids=(FITS_CARD_LOOP_SOURCE,),
            )
        )

    return tuple(cards)


@dataclass(frozen=True)
class FitsContinuationState:
    keyword: str
    value: str
    card_index: int


def close_pending_continuation(
    cards: list[FitsCardPlan],
    pending_continuation: FitsContinuationState,
) -> list[FitsCardPlan]:
    updated: list[FitsCardPlan] = []
    for card in cards:
        if card.index != pending_continuation.card_index:
            updated.append(card)
            continue
        record = FitsValueRecord(
            keyword=pending_continuation.keyword,
            value_kind="quoted_string",
            raw_value=card.value_record.raw_value if card.value_record is not None else "",
            value=pending_continuation.value + "&",
            comment=None,
            emits_metadata=True,
            evidence_ids=(FITS_VALUE_PARSE_SOURCE,),
        )
        updated.append(
            replace(
                card,
                value_record=record,
                warnings=(*card.warnings, "Unclosed FITS CONTINUE value emitted with trailing &"),
            )
        )
    return updated


def parse_continue_card(
    index: int,
    offset: int,
    raw_card: bytes,
    text: str,
    pending_continuation: FitsContinuationState | None,
) -> tuple[FitsCardPlan, FitsContinuationState | None]:
    warnings: tuple[str, ...] = ()
    value_record: FitsValueRecord | None = None
    next_pending = pending_continuation
    if pending_continuation is None:
        warnings = ("Unexpected FITS CONTINUE keyword",)
    else:
        parsed_value = parse_assigned_value(pending_continuation.keyword, text[10:])
        if parsed_value.value_kind != "quoted_string" or parsed_value.value is None:
            warnings = ("Invalid FITS CONTINUE value",)
        elif parsed_value.value.endswith("&"):
            next_pending = FitsContinuationState(
                keyword=pending_continuation.keyword,
                value=pending_continuation.value + parsed_value.value[:-1],
                card_index=pending_continuation.card_index,
            )
            value_record = replace(parsed_value, value_kind="continuation", emits_metadata=False)
        else:
            value_record = replace(
                parsed_value,
                value=pending_continuation.value + parsed_value.value,
                emits_metadata=True,
            )
            next_pending = None

    return (
        FitsCardPlan(
            index=index,
            offset=offset,
            raw_card=raw_card,
            keyword="CONTINUE",
            card_kind="continue",
            has_assignment=False,
            value_record=value_record,
            occurrence_index=None,
            duplicate_count=0,
            warnings=warnings,
            evidence_ids=(FITS_CARD_LOOP_SOURCE, FITS_VALUE_PARSE_SOURCE),
        ),
        next_pending,
    )


def parse_commentary_card(
    index: int,
    offset: int,
    raw_card: bytes,
    text: str,
    keyword: str,
) -> FitsCardPlan:
    value = text[8:].rstrip(" ")
    return FitsCardPlan(
        index=index,
        offset=offset,
        raw_card=raw_card,
        keyword=keyword,
        card_kind="comment" if keyword == "COMMENT" else "history",
        has_assignment=False,
        value_record=FitsValueRecord(
            keyword=keyword,
            value_kind="commentary",
            raw_value=text[8:],
            value=value,
            comment=None,
            emits_metadata=True,
            evidence_ids=(FITS_COMMENT_HISTORY_SOURCE,),
        ),
        occurrence_index=None,
        duplicate_count=0,
        warnings=(),
        evidence_ids=(FITS_COMMENT_HISTORY_SOURCE,),
    )


def parse_ignored_card(
    index: int,
    offset: int,
    raw_card: bytes,
    text: str,
    keyword: str,
) -> FitsCardPlan:
    card_kind: FitsCardKind = "hierarchical" if keyword == "HIERARCH" else "ignored"
    evidence_ids = (FITS_CARD_LOOP_SOURCE, FITS_TAG_ROUTING_SOURCE)
    return FitsCardPlan(
        index=index,
        offset=offset,
        raw_card=raw_card,
        keyword=keyword,
        card_kind=card_kind,
        has_assignment=False,
        value_record=FitsValueRecord(
            keyword=keyword,
            value_kind="ignored",
            raw_value=text[8:],
            value=None,
            comment=None,
            emits_metadata=False,
            evidence_ids=evidence_ids,
        ),
        occurrence_index=None,
        duplicate_count=0,
        warnings=(),
        evidence_ids=evidence_ids,
    )


def parse_keyword_card(
    index: int,
    offset: int,
    raw_card: bytes,
    text: str,
) -> tuple[FitsCardPlan, FitsContinuationState | None]:
    keyword = text[:8].rstrip(" ")
    value_record = parse_assigned_value(keyword, text[10:])
    pending_continuation: FitsContinuationState | None = None
    if value_record.value_kind == "quoted_string" and value_record.value is not None:
        if value_record.value.endswith("&"):
            pending_continuation = FitsContinuationState(
                keyword=keyword,
                value=value_record.value[:-1],
                card_index=index,
            )
            value_record = replace(
                value_record,
                value=value_record.value[:-1],
                emits_metadata=False,
            )

    return (
        FitsCardPlan(
            index=index,
            offset=offset,
            raw_card=raw_card,
            keyword=keyword,
            card_kind="keyword",
            has_assignment=True,
            value_record=value_record,
            occurrence_index=None,
            duplicate_count=0,
            warnings=(),
            evidence_ids=(FITS_TAG_ROUTING_SOURCE, FITS_VALUE_PARSE_SOURCE),
        ),
        pending_continuation,
    )


def parse_assigned_value(keyword: str, raw_value: str) -> FitsValueRecord:
    quoted = parse_quoted_value(raw_value)
    if quoted is not None:
        return FitsValueRecord(
            keyword=keyword,
            value_kind="quoted_string",
            raw_value=raw_value,
            value=quoted.value,
            comment=quoted.comment,
            emits_metadata=True,
            evidence_ids=(FITS_VALUE_PARSE_SOURCE,),
        )

    value_text, comment = split_unquoted_value_and_comment(raw_value)
    if len(value_text) == 0:
        return FitsValueRecord(
            keyword=keyword,
            value_kind="undefined",
            raw_value=raw_value,
            value=None,
            comment=comment,
            emits_metadata=False,
            evidence_ids=(FITS_VALUE_PARSE_SOURCE,),
        )
    normalized = normalize_unquoted_value(value_text.lstrip(" "))
    value_kind: FitsValueKind = "logical" if normalized in {"T", "F"} else "unquoted"
    return FitsValueRecord(
        keyword=keyword,
        value_kind=value_kind,
        raw_value=raw_value,
        value=normalized,
        comment=comment,
        emits_metadata=True,
        evidence_ids=(FITS_VALUE_PARSE_SOURCE,),
    )


@dataclass(frozen=True)
class ParsedQuotedValue:
    value: str
    comment: str | None


def parse_quoted_value(raw_value: str) -> ParsedQuotedValue | None:
    if not raw_value.startswith("'"):
        return None

    chars: list[str] = []
    index = 1
    while index < len(raw_value):
        char = raw_value[index]
        if char != "'":
            chars.append(char)
            index += 1
            continue
        if index + 1 < len(raw_value) and raw_value[index + 1] == "'":
            chars.append("'")
            index += 2
            continue
        remainder = raw_value[index + 1 :]
        value = "".join(chars).rstrip(" ")
        return ParsedQuotedValue(value=value, comment=extract_comment(remainder))
    return None


def split_unquoted_value_and_comment(raw_value: str) -> tuple[str, str | None]:
    slash_index = raw_value.find("/")
    if slash_index < 0:
        return raw_value.rstrip(" "), None
    return raw_value[:slash_index].rstrip(" "), raw_value[slash_index + 1 :].strip(" ")


def extract_comment(remainder: str) -> str | None:
    slash_index = remainder.find("/")
    if slash_index < 0:
        return None
    comment = remainder[slash_index + 1 :].strip(" ")
    return comment or None


def normalize_unquoted_value(value: str) -> str:
    if re.fullmatch(r"[+-]?(?=\d|\.\d)\d*(\.\d*)?([ED]([+-]?\d+))?", value):
        return value.translate(FITS_EXPONENT_TRANSLATION)
    return value


def build_duplicate_keyword_plans(
    cards: tuple[FitsCardPlan, ...],
) -> tuple[FitsDuplicateKeywordPlan, ...]:
    indexes_by_keyword: dict[str, list[int]] = {}
    for card in cards:
        if card.value_record is None or not card.value_record.emits_metadata:
            continue
        indexes_by_keyword.setdefault(card.value_record.keyword, []).append(card.index)

    duplicates: list[FitsDuplicateKeywordPlan] = []
    for keyword, indexes in indexes_by_keyword.items():
        if len(indexes) < 2:
            continue
        duplicates.append(
            FitsDuplicateKeywordPlan(
                keyword=keyword,
                card_indexes=tuple(indexes),
                duplicate_count=len(indexes),
                evidence_ids=(FITS_VALUE_PARSE_SOURCE,),
            )
        )
    return tuple(duplicates)


def apply_duplicate_indexes(
    cards: tuple[FitsCardPlan, ...],
    duplicates: tuple[FitsDuplicateKeywordPlan, ...],
) -> tuple[FitsCardPlan, ...]:
    duplicate_by_keyword = {duplicate.keyword: duplicate for duplicate in duplicates}
    seen_by_keyword: dict[str, int] = {}
    updated: list[FitsCardPlan] = []
    for card in cards:
        if card.value_record is None or not card.value_record.emits_metadata:
            updated.append(card)
            continue
        duplicate = duplicate_by_keyword.get(card.value_record.keyword)
        if duplicate is None:
            updated.append(replace(card, occurrence_index=1, duplicate_count=1))
            continue
        occurrence_index = seen_by_keyword.get(card.value_record.keyword, 0) + 1
        seen_by_keyword[card.value_record.keyword] = occurrence_index
        updated.append(
            replace(
                card,
                occurrence_index=occurrence_index,
                duplicate_count=duplicate.duplicate_count,
            )
        )
    return tuple(updated)


def build_fits_read_tags(cards: tuple[FitsCardPlan, ...]) -> tuple[FitsReadTagRecord, ...]:
    read_tags: list[FitsReadTagRecord] = []
    for card in cards:
        record = card.value_record
        if record is None or not record.emits_metadata or record.value is None:
            continue
        read_tags.append(
            FitsReadTagRecord(
                keyword=record.keyword,
                name=fits_tag_name(record.keyword),
                group=fits_tag_group(record.keyword),
                value=record.value,
                occurrence_index=card.occurrence_index or 1,
                evidence_ids=record.evidence_ids,
            )
        )
    return tuple(read_tags)


def fits_tag_name(keyword: str) -> str:
    names = {
        "TELESCOP": "Telescope",
        "BACKGRND": "Background",
        "INSTRUME": "Instrument",
        "OBJECT": "Object",
        "OBSERVER": "Observer",
        "DATE": "CreateDate",
        "AUTHOR": "Author",
        "REFERENC": "Reference",
        "DATE-OBS": "ObservationDate",
        "TIME-OBS": "ObservationTime",
        "DATE-END": "ObservationDateEnd",
        "TIME-END": "ObservationTimeEnd",
        "RA_OBJ": "RaObj",
        "DEC_OBJ": "DecObj",
        "OBS_ID": "ObsId",
        "COMMENT": "Comment",
        "HISTORY": "History",
    }
    if keyword in names:
        return names[keyword]
    return keyword[:1].upper() + keyword[1:].lower().replace("_", "")


def fits_tag_group(keyword: str) -> str:
    if keyword in {"DATE", "DATE-OBS", "TIME-OBS", "DATE-END", "TIME-END"}:
        return "Time"
    if keyword == "AUTHOR":
        return "Author"
    return "Image"


def build_boundary_plan(
    fits_data: bytes,
    cards: tuple[FitsCardPlan, ...],
    gates: list[FitsOutputEmissionGate],
) -> FitsBoundaryPlan:
    end_card = next((card for card in cards if card.card_kind == "end"), None)
    if end_card is None:
        return FitsBoundaryPlan(
            header_card_range=(0, len(cards) * FITS_CARD_SIZE) if cards else None,
            end_card_range=None,
            header_padding_range=None,
            header_block_range=None,
            data_block_range=None,
            header_padding_is_complete=False,
            header_padding_is_blank=None,
            evidence_ids=(FITS_CARD_LOOP_SOURCE,),
        )

    header_cards_end = end_card.offset + FITS_CARD_SIZE
    header_block_end = round_up_to_fits_block(header_cards_end)
    padding_end = min(header_block_end, len(fits_data))
    padding_range = (header_cards_end, padding_end)
    padding_bytes = fits_data[header_cards_end:padding_end]
    padding_is_complete = len(fits_data) >= header_block_end
    padding_is_blank = all(byte == 0x20 for byte in padding_bytes)
    if not padding_is_complete:
        gates.append(
            FitsOutputEmissionGate(
                code="truncated_header_padding",
                reason="The FITS header ended before the required 2880-byte block boundary.",
                evidence_ids=(FITS_CARD_LOOP_SOURCE,),
            )
        )
    return FitsBoundaryPlan(
        header_card_range=(0, header_cards_end),
        end_card_range=end_card.byte_range,
        header_padding_range=padding_range,
        header_block_range=(0, header_block_end) if padding_is_complete else None,
        data_block_range=(header_block_end, len(fits_data)) if padding_is_complete else None,
        header_padding_is_complete=padding_is_complete,
        header_padding_is_blank=padding_is_blank,
        evidence_ids=(FITS_CARD_LOOP_SOURCE,),
    )


def build_actions(
    cards: tuple[FitsCardPlan, ...],
    duplicate_keywords: tuple[FitsDuplicateKeywordPlan, ...],
    boundaries: FitsBoundaryPlan,
) -> tuple[FitsActionPlan, ...]:
    actions: list[FitsActionPlan] = [
        FitsActionPlan(
            kind="validate_initial_card",
            target="SIMPLE",
            byte_range=(0, FITS_CARD_SIZE),
            reason="Validate ExifTool's primary FITS entry card.",
            evidence_ids=(FITS_INITIAL_SIMPLE_SOURCE,),
        ),
        FitsActionPlan(
            kind="parse_80_byte_cards",
            target="header_cards",
            byte_range=boundaries.header_card_range,
            reason="Read FITS header as fixed-width 80-byte records.",
            evidence_ids=(FITS_CARD_LOOP_SOURCE,),
        ),
    ]
    for card in cards:
        if card.value_record is not None and card.value_record.emits_metadata:
            if card.card_kind in {"comment", "history"}:
                actions.append(
                    FitsActionPlan(
                        kind="parse_commentary_card",
                        target=card.keyword,
                        byte_range=card.byte_range,
                        reason="Extract COMMENT/HISTORY text starting at column 9.",
                        evidence_ids=(FITS_COMMENT_HISTORY_SOURCE,),
                    )
                )
            elif card.card_kind == "continue":
                actions.append(
                    FitsActionPlan(
                        kind="parse_continue_card",
                        target=card.value_record.keyword,
                        byte_range=card.byte_range,
                        reason="Append quoted CONTINUE text to the pending FITS value.",
                        evidence_ids=(FITS_VALUE_PARSE_SOURCE,),
                    )
                )
            else:
                actions.append(
                    FitsActionPlan(
                        kind="parse_keyword_value",
                        target=card.value_record.keyword,
                        byte_range=card.byte_range,
                        reason="Extract an ExifTool-modeled FITS keyword value.",
                        evidence_ids=(FITS_TAG_ROUTING_SOURCE, FITS_VALUE_PARSE_SOURCE),
                    )
                )
        if card.card_kind == "hierarchical":
            actions.append(
                FitsActionPlan(
                    kind="preserve_hierarchical_card",
                    target=card.keyword,
                    byte_range=card.byte_range,
                    reason="ExifTool ignores non '= ' HIERARCH-style cards, so preserve bytes.",
                    evidence_ids=(FITS_TAG_ROUTING_SOURCE,),
                )
            )
        if card.card_kind == "end":
            actions.append(
                FitsActionPlan(
                    kind="preserve_end_card",
                    target="END",
                    byte_range=card.byte_range,
                    reason="Preserve the END marker that terminates ExifTool's header scan.",
                    evidence_ids=(FITS_CARD_LOOP_SOURCE,),
                )
            )

    for duplicate in duplicate_keywords:
        actions.append(
            FitsActionPlan(
                kind="preserve_duplicate_keyword_order",
                target=duplicate.keyword,
                byte_range=None,
                reason="Duplicate FITS keywords are order-sensitive card occurrences.",
                evidence_ids=duplicate.evidence_ids,
            )
        )
    if boundaries.header_padding_range is not None:
        actions.append(
            FitsActionPlan(
                kind="preserve_header_padding",
                target="header_padding",
                byte_range=boundaries.header_padding_range,
                reason="Preserve bytes between END and the next 2880-byte FITS block boundary.",
                evidence_ids=(FITS_CARD_LOOP_SOURCE,),
            )
        )
    if boundaries.data_block_range is not None:
        actions.append(
            FitsActionPlan(
                kind="preserve_data_blocks",
                target="data_blocks",
                byte_range=boundaries.data_block_range,
                reason="Preserve all bytes after the padded header block as FITS data blocks.",
                evidence_ids=(FITS_CARD_LOOP_SOURCE,),
            )
        )
    return tuple(actions)


def build_rewrite_blockers(
    cards: tuple[FitsCardPlan, ...],
    duplicate_keywords: tuple[FitsDuplicateKeywordPlan, ...],
) -> tuple[FitsRewriteBlocker, ...]:
    blockers = [
        FitsRewriteBlocker(
            code="fits_card_rewrite_not_implemented",
            reason=(
                "This surface plans FITS card preservation and extraction only; "
                "it has no serializer."
            ),
            evidence_ids=FITS_TRANSACTION_SOURCES,
        )
    ]
    if duplicate_keywords:
        blockers.append(
            FitsRewriteBlocker(
                code="duplicate_keyword_order_must_be_preserved",
                reason=(
                    "Duplicate keyword cards must remain ordered to preserve "
                    "ExifTool-visible values."
                ),
                evidence_ids=(FITS_VALUE_PARSE_SOURCE,),
            )
        )
    if any(card.card_kind in {"comment", "history"} for card in cards):
        blockers.append(
            FitsRewriteBlocker(
                code="comment_history_cards_are_order_sensitive",
                reason=(
                    "COMMENT and HISTORY records are free-text card streams, not scalar rewrites."
                ),
                evidence_ids=(FITS_COMMENT_HISTORY_SOURCE,),
            )
        )
    if any(card.card_kind == "continue" for card in cards):
        blockers.append(
            FitsRewriteBlocker(
                code="continue_cards_require_exact_card_reflow",
                reason="CONTINUE string values require exact 80-byte card reflow before mutation.",
                evidence_ids=(FITS_VALUE_PARSE_SOURCE,),
            )
        )
    if any(card.card_kind == "hierarchical" for card in cards):
        blockers.append(
            FitsRewriteBlocker(
                code="hierarchical_cards_are_preserve_only",
                reason=(
                    "ExifTool ignores HIERARCH-style cards without '= ', so they are preserve-only."
                ),
                evidence_ids=(FITS_TAG_ROUTING_SOURCE,),
            )
        )
    return tuple(blockers)


def add_non_mutating_gate(
    gates: list[FitsOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        FitsOutputEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="FITS header transaction plans are non-mutating unless emission is allowed.",
            evidence_ids=(FITS_INITIAL_SIMPLE_SOURCE,),
        )
    )


def structural_gate_present(gates: tuple[FitsOutputEmissionGate, ...]) -> bool:
    read_compatible_gates = {
        "non_mutating_plan_requires_explicit_emission",
        "truncated_header_padding",
    }
    return any(gate.code not in read_compatible_gates for gate in gates)


def fits_keyword_is_valid(keyword: str) -> bool:
    return all(char in FITS_VALID_KEYWORD_CHARS for char in keyword)


def decode_card(card: bytes) -> str:
    return card.decode("latin-1")


def round_up_to_fits_block(offset: int) -> int:
    return ((offset + FITS_BLOCK_SIZE - 1) // FITS_BLOCK_SIZE) * FITS_BLOCK_SIZE


def json_range(value: tuple[int, int] | None) -> JsonArray | None:
    return None if value is None else [value[0], value[1]]


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return list(values)


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


def unique_evidence_ids(references: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for reference in references:
        if reference in seen:
            continue
        seen.add(reference)
        unique.append(reference)
    return tuple(unique)


def unique_emission_gates(
    gates: tuple[FitsOutputEmissionGate, ...],
) -> tuple[FitsOutputEmissionGate, ...]:
    unique: list[FitsOutputEmissionGate] = []
    seen: set[FitsEmissionGateCode] = set()
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)
