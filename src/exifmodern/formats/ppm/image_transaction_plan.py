"""Source-grounded, non-mutating Netpbm PPM/PGM/PBM transaction plans.

The planner mirrors ExifTool's PPM.pm header reader and comment rewrite model:
P1 through P6 are accepted, the magic digit selects PBM/PGM/PPM plus ASCII or
binary raster routing, comments are recognized only in the header locations
handled by ProcessPPM, and the raster tail is preserved from the parsed header
boundary. PAM/P7 is surfaced as an unsupported Netpbm route because PPM.pm
accepts only P1 through P6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PPM_WHITESPACE = b" \t\n\r\f\v"
PPM_SUPPORTED_MAGICS = b"123456"
PPM_COMMENT_PREFIX = 35

PPM_DESCRIPTION_SOURCE = "ppm.description"
PPM_HEADER_READ_SOURCE = "ppm.header_read"
PPM_COMMENT_SOURCE = "ppm.comment"
PPM_DIMENSION_SOURCE = "ppm.dimension"
PPM_MAXVAL_COMMENT_SOURCE = "ppm.maxval_comment"
PPM_NUMERIC_VALIDATION_SOURCE = "ppm.numeric_validation"
PPM_COMMENT_CLEANUP_SOURCE = "ppm.comment_cleanup"
PPM_REWRITE_SOURCE = "ppm.rewrite"
PPM_FOUND_TAG_SOURCE = "ppm.found_tags"

PPM_TRANSACTION_SOURCES = (
    PPM_DESCRIPTION_SOURCE,
    PPM_HEADER_READ_SOURCE,
    PPM_COMMENT_SOURCE,
    PPM_DIMENSION_SOURCE,
    PPM_MAXVAL_COMMENT_SOURCE,
    PPM_NUMERIC_VALIDATION_SOURCE,
    PPM_COMMENT_CLEANUP_SOURCE,
    PPM_REWRITE_SOURCE,
    PPM_FOUND_TAG_SOURCE,
)


@dataclass(frozen=True)
class PpmOutputEmissionGate:
    code: Literal[
        "non_mutating_plan_requires_explicit_emission",
        "truncated_ppm_header",
        "unsupported_netpbm_magic",
        "unsupported_pam_magic",
        "truncated_pam_header",
        "malformed_numeric_header",
        "rewrite_requested_requires_ppm_writer",
    ]
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PpmMagicPlan:
    magic: bytes
    magic_number: int | None
    family: Literal["PBM", "PGM", "PPM", "PAM"] | None
    encoding: Literal["ascii", "binary"] | None
    supported_by_oracle: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PpmHeaderFieldPlan:
    name: Literal["ImageWidth", "ImageHeight", "MaxVal"]
    raw_value: str | None
    value: int | None
    byte_range: tuple[int, int] | None
    required: bool
    action: Literal["extract", "skip_for_pbm", "missing"]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PpmCommentPlan:
    raw_segments: tuple[str, ...]
    cleaned_value: str | None
    is_seal: bool
    tag_emitted_as_comment: bool
    byte_ranges: tuple[tuple[int, int], ...]
    action: Literal["absent", "extract_comment", "route_seal"]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PpmPamHeaderFieldPlan:
    key: str
    raw_value: str
    byte_range: tuple[int, int]
    numeric_value: int | None


@dataclass(frozen=True)
class PpmPamHeaderPlan:
    present: bool
    supported_by_oracle: bool
    header_fields: tuple[PpmPamHeaderFieldPlan, ...]
    tuple_type: str | None
    header_end_offset: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PpmRasterDataPlan:
    start_offset: int | None
    end_offset: int
    observed_length: int | None
    action: Literal["preserve", "unavailable"]
    validation_model: Literal[
        "copied_without_raster_length_check",
        "unavailable_for_unsupported_header",
    ]
    evidence_ids: tuple[str, ...]

    @property
    def byte_range(self) -> tuple[int, int] | None:
        if self.start_offset is None:
            return None
        return (self.start_offset, self.end_offset)


@dataclass(frozen=True)
class PpmRewriteRequest:
    target: Literal["comment", "seal"]
    operation: Literal["replace", "delete"]
    value: str | None = None


@dataclass(frozen=True)
class PpmActionPlan:
    kind: Literal[
        "validate_magic",
        "route_variant",
        "extract_comment",
        "extract_dimensions",
        "extract_maxval",
        "skip_maxval_for_pbm",
        "preserve_raster_data",
        "block_pam_route",
        "block_requested_rewrite",
    ]
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PpmImageTransactionPlan:
    status: Literal["planned", "unsupported"]
    source_data: bytes
    magic: PpmMagicPlan
    comment: PpmCommentPlan
    image_width: PpmHeaderFieldPlan
    image_height: PpmHeaderFieldPlan
    maxval: PpmHeaderFieldPlan
    pam_header: PpmPamHeaderPlan
    raster_data: PpmRasterDataPlan
    rewrite_requests: tuple[PpmRewriteRequest, ...]
    actions: tuple[PpmActionPlan, ...]
    output_emission_gates: tuple[PpmOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"PPM image transaction output is gated: {gate_codes}")
        return self.source_data


@dataclass(frozen=True)
class _CommentRead:
    segment: str
    raw_range: tuple[int, int]
    next_offset: int


@dataclass(frozen=True)
class _TokenRead:
    raw_value: str
    value_range: tuple[int, int]
    next_offset: int


def build_ppm_image_transaction_plan(
    ppm_data: bytes,
    *,
    rewrite_requests: tuple[PpmRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> PpmImageTransactionPlan:
    """Build a source-backed PPM/PGM/PBM transaction plan."""

    gates: list[PpmOutputEmissionGate] = []
    actions: list[PpmActionPlan] = []
    pam_header = _empty_pam_header()

    if _looks_like_pam(ppm_data):
        magic = PpmMagicPlan(
            magic=ppm_data[:2],
            magic_number=7,
            family="PAM",
            encoding="binary",
            supported_by_oracle=False,
            evidence_ids=(PPM_HEADER_READ_SOURCE,),
        )
        pam_header, pam_gate = _parse_pam_header(ppm_data)
        gates.append(
            PpmOutputEmissionGate(
                code="unsupported_pam_magic",
                reason="ExifTool's PPM.pm magic gate accepts only P1 through P6, not PAM/P7.",
                evidence_ids=(PPM_HEADER_READ_SOURCE,),
            )
        )
        if pam_gate is not None:
            gates.append(pam_gate)
        actions.append(
            PpmActionPlan(
                kind="block_pam_route",
                target="PAM",
                byte_range=(0, pam_header.header_end_offset)
                if pam_header.header_end_offset is not None
                else None,
                reason=(
                    "PAM header responsibilities are surfaced but blocked because "
                    "PPM.pm does not accept P7."
                ),
                evidence_ids=(PPM_HEADER_READ_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=ppm_data,
            magic=magic,
            comment=_empty_comment(),
            image_width=_missing_field("ImageWidth", True),
            image_height=_missing_field("ImageHeight", True),
            maxval=_missing_field("MaxVal", False),
            pam_header=pam_header,
            raster_data=_unavailable_raster(ppm_data),
            rewrite_requests=rewrite_requests,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    magic_error = _unsupported_magic_gate(ppm_data)
    if magic_error is not None:
        gates.append(magic_error)
        magic = PpmMagicPlan(
            magic=ppm_data[:2],
            magic_number=None,
            family=None,
            encoding=None,
            supported_by_oracle=False,
            evidence_ids=(PPM_HEADER_READ_SOURCE,),
        )
        return _final_plan(
            status="unsupported",
            source_data=ppm_data,
            magic=magic,
            comment=_empty_comment(),
            image_width=_missing_field("ImageWidth", True),
            image_height=_missing_field("ImageHeight", True),
            maxval=_missing_field("MaxVal", False),
            pam_header=pam_header,
            raster_data=_unavailable_raster(ppm_data),
            rewrite_requests=rewrite_requests,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    magic_number = ppm_data[1] - 48
    family = _family_for_magic_number(magic_number)
    encoding: Literal["ascii", "binary"] = "ascii" if magic_number <= 3 else "binary"
    magic = PpmMagicPlan(
        magic=ppm_data[:2],
        magic_number=magic_number,
        family=family,
        encoding=encoding,
        supported_by_oracle=True,
        evidence_ids=(PPM_HEADER_READ_SOURCE, PPM_DIMENSION_SOURCE),
    )
    actions.append(
        PpmActionPlan(
            kind="validate_magic",
            target=f"P{magic_number}",
            byte_range=(0, 3),
            reason="Input satisfied ExifTool's P1 through P6 magic gate.",
            evidence_ids=(PPM_HEADER_READ_SOURCE,),
        )
    )
    actions.append(
        PpmActionPlan(
            kind="route_variant",
            target=f"{family}:{encoding}",
            byte_range=(0, 2),
            reason="Magic digit routes Netpbm family and ASCII/binary variant.",
            evidence_ids=(PPM_DIMENSION_SOURCE,),
        )
    )

    cursor = _skip_whitespace(ppm_data, 2)
    comment_segments: list[str] = []
    comment_ranges: list[tuple[int, int]] = []
    if cursor < len(ppm_data) and ppm_data[cursor] == PPM_COMMENT_PREFIX:
        comment_read = _read_comment_block(ppm_data, cursor)
        if comment_read is None:
            gates.append(_truncated_header_gate("The leading PPM comment is incomplete."))
            return _unsupported_ppm_plan(
                ppm_data,
                magic,
                _empty_comment(),
                rewrite_requests,
                actions,
                gates,
                allow_output_emission,
            )
        comment_segments.append(comment_read.segment)
        comment_ranges.append(comment_read.raw_range)
        cursor = comment_read.next_offset

    width_token = _read_token(ppm_data, cursor)
    if width_token is None:
        gates.append(_truncated_header_gate("ExifTool could not read ImageWidth."))
        return _unsupported_ppm_plan(
            ppm_data,
            magic,
            _build_comment(comment_segments, comment_ranges),
            rewrite_requests,
            actions,
            gates,
            allow_output_emission,
        )
    cursor = width_token.next_offset
    height_token = _read_token(ppm_data, cursor)
    if height_token is None:
        gates.append(_truncated_header_gate("ExifTool could not read ImageHeight."))
        return _unsupported_ppm_plan(
            ppm_data,
            magic,
            _build_comment(comment_segments, comment_ranges),
            rewrite_requests,
            actions,
            gates,
            allow_output_emission,
        )
    cursor = height_token.next_offset
    image_width = _field_from_token("ImageWidth", width_token, True)
    image_height = _field_from_token("ImageHeight", height_token, True)
    actions.append(
        PpmActionPlan(
            kind="extract_dimensions",
            target="ImageWidth/ImageHeight",
            byte_range=(width_token.value_range[0], height_token.value_range[1]),
            reason=(
                "ImageWidth and ImageHeight are the first two non-whitespace "
                "header tokens after comments."
            ),
            evidence_ids=(PPM_DIMENSION_SOURCE, PPM_NUMERIC_VALIDATION_SOURCE),
        )
    )

    maxval = _missing_field("MaxVal", family != "PBM")
    if family == "PBM":
        maxval = PpmHeaderFieldPlan(
            name="MaxVal",
            raw_value=None,
            value=None,
            byte_range=None,
            required=False,
            action="skip_for_pbm",
            evidence_ids=(PPM_MAXVAL_COMMENT_SOURCE,),
        )
        actions.append(
            PpmActionPlan(
                kind="skip_maxval_for_pbm",
                target="MaxVal",
                byte_range=None,
                reason="ExifTool stops after dimensions for PBM because PBM has no MaxVal token.",
                evidence_ids=(PPM_DIMENSION_SOURCE, PPM_MAXVAL_COMMENT_SOURCE),
            )
        )
    else:
        if cursor < len(ppm_data) and ppm_data[cursor] == PPM_COMMENT_PREFIX:
            comment_read = _read_comment_block(ppm_data, cursor)
            if comment_read is None:
                gates.append(_truncated_header_gate("The pre-MaxVal PPM comment is incomplete."))
                return _unsupported_ppm_plan(
                    ppm_data,
                    magic,
                    _build_comment(comment_segments, comment_ranges),
                    rewrite_requests,
                    actions,
                    gates,
                    allow_output_emission,
                )
            comment_segments.append(comment_read.segment)
            comment_ranges.append(comment_read.raw_range)
            cursor = comment_read.next_offset
        maxval_token = _read_token(ppm_data, cursor)
        if maxval_token is None:
            gates.append(_truncated_header_gate("ExifTool could not read MaxVal."))
            return _unsupported_ppm_plan(
                ppm_data,
                magic,
                _build_comment(comment_segments, comment_ranges),
                rewrite_requests,
                actions,
                gates,
                allow_output_emission,
            )
        cursor = maxval_token.next_offset
        maxval = _field_from_token("MaxVal", maxval_token, True)
        actions.append(
            PpmActionPlan(
                kind="extract_maxval",
                target="MaxVal",
                byte_range=maxval_token.value_range,
                reason=(
                    "PGM and PPM images carry MaxVal after dimensions and any "
                    "recognized pre-MaxVal comment."
                ),
                evidence_ids=(PPM_MAXVAL_COMMENT_SOURCE, PPM_NUMERIC_VALIDATION_SOURCE),
            )
        )

    comment = _build_comment(comment_segments, comment_ranges)
    if comment.action in {"extract_comment", "route_seal"}:
        actions.append(
            PpmActionPlan(
                kind="extract_comment",
                target="Comment" if comment.tag_emitted_as_comment else "XMP::SEAL",
                byte_range=(comment_ranges[0][0], comment_ranges[-1][1]),
                reason=(
                    "Comments are cleaned with the same marker stripping and SEAL "
                    "routing as PPM.pm."
                ),
                evidence_ids=(
                    PPM_COMMENT_SOURCE,
                    PPM_COMMENT_CLEANUP_SOURCE,
                    PPM_FOUND_TAG_SOURCE,
                ),
            )
        )

    numeric_gate = _numeric_gate((image_width, image_height, maxval))
    if numeric_gate is not None:
        gates.append(numeric_gate)
        return _final_plan(
            status="unsupported",
            source_data=ppm_data,
            magic=magic,
            comment=comment,
            image_width=image_width,
            image_height=image_height,
            maxval=maxval,
            pam_header=pam_header,
            raster_data=_unavailable_raster(ppm_data),
            rewrite_requests=rewrite_requests,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    raster_data = PpmRasterDataPlan(
        start_offset=cursor,
        end_offset=len(ppm_data),
        observed_length=len(ppm_data) - cursor,
        action="preserve",
        validation_model="copied_without_raster_length_check",
        evidence_ids=(PPM_REWRITE_SOURCE,),
    )
    actions.append(
        PpmActionPlan(
            kind="preserve_raster_data",
            target="raster_data",
            byte_range=(cursor, len(ppm_data)),
            reason=(
                "ExifTool writes the parsed header and then copies all remaining "
                "image bytes unchanged."
            ),
            evidence_ids=(PPM_REWRITE_SOURCE,),
        )
    )

    for request in rewrite_requests:
        gates.append(
            PpmOutputEmissionGate(
                code="rewrite_requested_requires_ppm_writer",
                reason=(
                    f"PPM {request.operation} for {request.target} needs normalized header "
                    "rewrite support before this planner may emit bytes."
                ),
                evidence_ids=(PPM_REWRITE_SOURCE,),
            )
        )
        actions.append(
            PpmActionPlan(
                kind="block_requested_rewrite",
                target=request.target,
                byte_range=None,
                reason="Comment rewrites are planned but not emitted by the non-mutating planner.",
                evidence_ids=(PPM_REWRITE_SOURCE,),
            )
        )

    return _final_plan(
        status="planned",
        source_data=ppm_data,
        magic=magic,
        comment=comment,
        image_width=image_width,
        image_height=image_height,
        maxval=maxval,
        pam_header=pam_header,
        raster_data=raster_data,
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        gates=gates,
        allow_output_emission=allow_output_emission,
    )


def _looks_like_pam(ppm_data: bytes) -> bool:
    return len(ppm_data) >= 2 and ppm_data[:2] == b"P7"


def _unsupported_magic_gate(ppm_data: bytes) -> PpmOutputEmissionGate | None:
    if len(ppm_data) < 3:
        return _truncated_header_gate(
            "ExifTool could not read a complete PPM magic plus whitespace."
        )
    if ppm_data[:1] == b"P" and ppm_data[1:2] in PPM_SUPPORTED_MAGICS:
        if ppm_data[2] not in PPM_WHITESPACE:
            return _truncated_header_gate(
                "ExifTool requires whitespace after the P1 through P6 magic."
            )
        return None
    return PpmOutputEmissionGate(
        code="unsupported_netpbm_magic",
        reason="Input does not match ExifTool's /^P([1-6])\\s+/ PPM magic gate.",
        evidence_ids=(PPM_HEADER_READ_SOURCE,),
    )


def _skip_whitespace(data: bytes, offset: int) -> int:
    cursor = offset
    while cursor < len(data) and data[cursor] in PPM_WHITESPACE:
        cursor += 1
    return cursor


def _read_token(data: bytes, offset: int) -> _TokenRead | None:
    if offset >= len(data) or data[offset] in PPM_WHITESPACE:
        return None
    token_start = offset
    cursor = offset
    while cursor < len(data) and data[cursor] not in PPM_WHITESPACE:
        cursor += 1
    if cursor >= len(data):
        return None
    token_end = cursor
    cursor = _skip_whitespace(data, cursor)
    return _TokenRead(
        raw_value=data[token_start:token_end].decode("latin-1"),
        value_range=(token_start, token_end),
        next_offset=cursor,
    )


def _read_comment_block(data: bytes, hash_offset: int) -> _CommentRead | None:
    cursor = hash_offset + 1
    if cursor < len(data) and data[cursor] == 32:
        cursor += 1
    segment_start = cursor
    first_end = _find_line_end(data, cursor)
    if first_end is None:
        return None
    cursor = first_end + 1
    while cursor < len(data) and data[cursor] == PPM_COMMENT_PREFIX:
        line_end = _find_line_end(data, cursor)
        if line_end is None:
            return None
        cursor = line_end + 1
    segment_end = cursor
    cursor = _skip_whitespace(data, cursor)
    return _CommentRead(
        segment=data[segment_start:segment_end].decode("latin-1"),
        raw_range=(hash_offset, segment_end),
        next_offset=cursor,
    )


def _find_line_end(data: bytes, offset: int) -> int | None:
    cursor = offset
    while cursor < len(data):
        if data[cursor] in b"\n\r":
            return cursor
        cursor += 1
    return None


def _field_from_token(
    name: Literal["ImageWidth", "ImageHeight", "MaxVal"],
    token: _TokenRead,
    required: bool,
) -> PpmHeaderFieldPlan:
    return PpmHeaderFieldPlan(
        name=name,
        raw_value=token.raw_value,
        value=int(token.raw_value) if token.raw_value.isdecimal() else None,
        byte_range=token.value_range,
        required=required,
        action="extract",
        evidence_ids=(PPM_DIMENSION_SOURCE, PPM_NUMERIC_VALIDATION_SOURCE)
        if name != "MaxVal"
        else (PPM_MAXVAL_COMMENT_SOURCE, PPM_NUMERIC_VALIDATION_SOURCE),
    )


def _missing_field(
    name: Literal["ImageWidth", "ImageHeight", "MaxVal"],
    required: bool,
) -> PpmHeaderFieldPlan:
    return PpmHeaderFieldPlan(
        name=name,
        raw_value=None,
        value=None,
        byte_range=None,
        required=required,
        action="missing",
        evidence_ids=(PPM_DIMENSION_SOURCE,) if name != "MaxVal" else (PPM_MAXVAL_COMMENT_SOURCE,),
    )


def _build_comment(
    segments: list[str],
    byte_ranges: list[tuple[int, int]],
) -> PpmCommentPlan:
    if not segments:
        return _empty_comment()
    raw = "".join(segments)
    cleaned_lines = []
    for line in raw.splitlines():
        if line.startswith("# "):
            cleaned_lines.append(line[2:])
        elif line.startswith("#"):
            cleaned_lines.append(line[1:])
        else:
            cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines).rstrip("\n\r")
    is_seal = cleaned.startswith("<seal seal=")
    return PpmCommentPlan(
        raw_segments=tuple(segments),
        cleaned_value=cleaned,
        is_seal=is_seal,
        tag_emitted_as_comment=not is_seal,
        byte_ranges=tuple(byte_ranges),
        action="route_seal" if is_seal else "extract_comment",
        evidence_ids=(
            PPM_COMMENT_SOURCE,
            PPM_MAXVAL_COMMENT_SOURCE,
            PPM_COMMENT_CLEANUP_SOURCE,
        ),
    )


def _empty_comment() -> PpmCommentPlan:
    return PpmCommentPlan(
        raw_segments=(),
        cleaned_value=None,
        is_seal=False,
        tag_emitted_as_comment=False,
        byte_ranges=(),
        action="absent",
        evidence_ids=(PPM_COMMENT_SOURCE, PPM_COMMENT_CLEANUP_SOURCE),
    )


def _numeric_gate(
    fields: tuple[PpmHeaderFieldPlan, PpmHeaderFieldPlan, PpmHeaderFieldPlan],
) -> PpmOutputEmissionGate | None:
    malformed = [field.name for field in fields if field.required and field.value is None]
    if not malformed:
        return None
    return PpmOutputEmissionGate(
        code="malformed_numeric_header",
        reason=f"ExifTool requires decimal numeric tokens for {', '.join(malformed)}.",
        evidence_ids=(PPM_NUMERIC_VALIDATION_SOURCE,),
    )


def _family_for_magic_number(magic_number: int) -> Literal["PBM", "PGM", "PPM"]:
    if magic_number % 3 == 1:
        return "PBM"
    if magic_number % 3 == 2:
        return "PGM"
    return "PPM"


def _parse_pam_header(
    pam_data: bytes,
) -> tuple[PpmPamHeaderPlan, PpmOutputEmissionGate | None]:
    fields: list[PpmPamHeaderFieldPlan] = []
    tuple_type: str | None = None
    cursor = _skip_whitespace(pam_data, 2)
    while cursor < len(pam_data):
        line_start = cursor
        line_end = _find_line_end(pam_data, cursor)
        if line_end is None:
            return (
                PpmPamHeaderPlan(
                    present=True,
                    supported_by_oracle=False,
                    header_fields=tuple(fields),
                    tuple_type=tuple_type,
                    header_end_offset=None,
                    evidence_ids=(PPM_HEADER_READ_SOURCE,),
                ),
                PpmOutputEmissionGate(
                    code="truncated_pam_header",
                    reason="PAM/P7 input did not include an ENDHDR line.",
                    evidence_ids=(PPM_HEADER_READ_SOURCE,),
                ),
            )
        raw_line = pam_data[line_start:line_end].decode("latin-1").strip()
        cursor = line_end + 1
        if raw_line == "ENDHDR":
            return (
                PpmPamHeaderPlan(
                    present=True,
                    supported_by_oracle=False,
                    header_fields=tuple(fields),
                    tuple_type=tuple_type,
                    header_end_offset=cursor,
                    evidence_ids=(PPM_HEADER_READ_SOURCE,),
                ),
                None,
            )
        if not raw_line or raw_line.startswith("#"):
            continue
        key, raw_value = _split_pam_line(raw_line)
        if key == "TUPLTYPE":
            tuple_type = raw_value
        fields.append(
            PpmPamHeaderFieldPlan(
                key=key,
                raw_value=raw_value,
                byte_range=(line_start, line_end),
                numeric_value=int(raw_value) if raw_value.isdecimal() else None,
            )
        )
    return (
        PpmPamHeaderPlan(
            present=True,
            supported_by_oracle=False,
            header_fields=tuple(fields),
            tuple_type=tuple_type,
            header_end_offset=None,
            evidence_ids=(PPM_HEADER_READ_SOURCE,),
        ),
        PpmOutputEmissionGate(
            code="truncated_pam_header",
            reason="PAM/P7 input ended before ENDHDR.",
            evidence_ids=(PPM_HEADER_READ_SOURCE,),
        ),
    )


def _split_pam_line(raw_line: str) -> tuple[str, str]:
    parts = raw_line.split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _empty_pam_header() -> PpmPamHeaderPlan:
    return PpmPamHeaderPlan(
        present=False,
        supported_by_oracle=False,
        header_fields=(),
        tuple_type=None,
        header_end_offset=None,
        evidence_ids=(PPM_HEADER_READ_SOURCE,),
    )


def _unavailable_raster(ppm_data: bytes) -> PpmRasterDataPlan:
    return PpmRasterDataPlan(
        start_offset=None,
        end_offset=len(ppm_data),
        observed_length=None,
        action="unavailable",
        validation_model="unavailable_for_unsupported_header",
        evidence_ids=(PPM_REWRITE_SOURCE,),
    )


def _truncated_header_gate(reason: str) -> PpmOutputEmissionGate:
    return PpmOutputEmissionGate(
        code="truncated_ppm_header",
        reason=reason,
        evidence_ids=(PPM_HEADER_READ_SOURCE,),
    )


def _unsupported_ppm_plan(
    ppm_data: bytes,
    magic: PpmMagicPlan,
    comment: PpmCommentPlan,
    rewrite_requests: tuple[PpmRewriteRequest, ...],
    actions: list[PpmActionPlan],
    gates: list[PpmOutputEmissionGate],
    allow_output_emission: bool,
) -> PpmImageTransactionPlan:
    return _final_plan(
        status="unsupported",
        source_data=ppm_data,
        magic=magic,
        comment=comment,
        image_width=_missing_field("ImageWidth", True),
        image_height=_missing_field("ImageHeight", True),
        maxval=_missing_field("MaxVal", magic.family != "PBM"),
        pam_header=_empty_pam_header(),
        raster_data=_unavailable_raster(ppm_data),
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        gates=gates,
        allow_output_emission=allow_output_emission,
    )


def _final_plan(
    *,
    status: Literal["planned", "unsupported"],
    source_data: bytes,
    magic: PpmMagicPlan,
    comment: PpmCommentPlan,
    image_width: PpmHeaderFieldPlan,
    image_height: PpmHeaderFieldPlan,
    maxval: PpmHeaderFieldPlan,
    pam_header: PpmPamHeaderPlan,
    raster_data: PpmRasterDataPlan,
    rewrite_requests: tuple[PpmRewriteRequest, ...],
    actions: tuple[PpmActionPlan, ...],
    gates: list[PpmOutputEmissionGate],
    allow_output_emission: bool,
) -> PpmImageTransactionPlan:
    if not allow_output_emission:
        gates.append(
            PpmOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="PPM transaction plans are non-mutating unless emission is explicit.",
                evidence_ids=(PPM_REWRITE_SOURCE,),
            )
        )
    unique_gates = _unique_gates(tuple(gates))
    evidence_ids = _unique_sources(
        (
            *PPM_TRANSACTION_SOURCES,
            *magic.evidence_ids,
            *comment.evidence_ids,
            *image_width.evidence_ids,
            *image_height.evidence_ids,
            *maxval.evidence_ids,
            *pam_header.evidence_ids,
            *raster_data.evidence_ids,
            *(source for gate in unique_gates for source in gate.evidence_ids),
            *(source for action in actions for source in action.evidence_ids),
        )
    )
    return PpmImageTransactionPlan(
        status=status,
        source_data=source_data,
        magic=magic,
        comment=comment,
        image_width=image_width,
        image_height=image_height,
        maxval=maxval,
        pam_header=pam_header,
        raster_data=raster_data,
        rewrite_requests=rewrite_requests,
        actions=actions,
        output_emission_gates=unique_gates,
        evidence_ids=evidence_ids,
    )


def _unique_gates(gates: tuple[PpmOutputEmissionGate, ...]) -> tuple[PpmOutputEmissionGate, ...]:
    unique: list[PpmOutputEmissionGate] = []
    seen: set[str] = set()
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def _unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source in seen:
            continue
        seen.add(source)
        unique.append(source)
    return tuple(unique)
