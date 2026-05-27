"""Source-grounded, non-mutating MIFF image transaction plans.

ExifTool's MIFF module validates the suggested ImageMagick header, parses the
text section into arbitrary key/value tags, queues profile lengths, then reads
profile payloads before the image payload. This planner mirrors those read
responsibilities and never rewrites MIFF bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MIFF_SIGNATURE = b"id=ImageMagick"
MIFF_SIGNATURE_LENGTH = 14
MIFF_NEW_TEXT_TERMINATOR = b":\x1a"
MIFF_OLD_TEXT_TERMINATOR = b":\n"
MIFF_EXIF_APP1_HEADER = b"Exif\x00\x00"
MIFF_XMP_APP1_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"

type MiffPlanStatus = Literal["planned", "unsupported"]
type MiffTerminatorKind = Literal["new_text_section", "old_text_section", "missing"]
type MiffHeaderEntryAction = Literal[
    "extract_standard_tag",
    "extract_arbitrary_tag",
    "queue_profile",
]
type MiffCommentAction = Literal["skip_comment"]
type MiffMetadataRole = Literal[
    "id",
    "image_width",
    "image_height",
    "class",
    "colors",
    "colorspace",
    "compression",
    "depth",
    "signature",
    "profile",
    "standard_metadata",
    "arbitrary_metadata",
]
type MiffProfileRoute = Literal[
    "route_icc_profile",
    "route_photoshop_profile",
    "route_exif_profile",
    "route_xmp_profile",
    "preserve_unknown_profile",
    "block_invalid_profile_length",
    "block_truncated_profile",
]
type MiffRewriteOperation = Literal["insert", "replace", "delete"]
type MiffActionKind = Literal[
    "validate_signature",
    "parse_header_entries",
    "extract_image_attributes",
    "skip_comment",
    "read_profile_payload",
    "preserve_profile_payload",
    "preserve_image_payload",
    "block_requested_rewrite",
]
type MiffEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_miff_signature",
    "unsupported_miff_signature",
    "missing_miff_text_terminator",
    "unrecognized_miff_header_data",
    "unterminated_miff_comment",
    "unterminated_miff_braced_value",
    "invalid_miff_profile_length",
    "truncated_miff_profile",
    "rewrite_requested_requires_miff_writer",
]

MIFF_PM_SOURCE_PATH = "lib/Image/ExifTool/MIFF.pm"

MIFF_DESCRIPTION_SOURCE = "miff_description"
MIFF_MAIN_TABLE_SOURCE = "miff_main_table"
MIFF_SIGNATURE_SOURCE = "miff_signature"
MIFF_TEXT_TERMINATOR_SOURCE = "miff_text_terminator"
MIFF_HEADER_PARSE_SOURCE = "miff_header_parse"
MIFF_DYNAMIC_TAG_SOURCE = "miff_dynamic_tag"
MIFF_PROFILE_LENGTH_SOURCE = "miff_profile_length"
MIFF_PROFILE_ROUTE_SOURCE = "miff_profile_route"
MIFF_UNKNOWN_PROFILE_SOURCE = "miff_unknown_profile"

MIFF_TRANSACTION_SOURCES = (
    MIFF_DESCRIPTION_SOURCE,
    MIFF_MAIN_TABLE_SOURCE,
    MIFF_SIGNATURE_SOURCE,
    MIFF_TEXT_TERMINATOR_SOURCE,
    MIFF_HEADER_PARSE_SOURCE,
    MIFF_DYNAMIC_TAG_SOURCE,
    MIFF_PROFILE_LENGTH_SOURCE,
    MIFF_PROFILE_ROUTE_SOURCE,
    MIFF_UNKNOWN_PROFILE_SOURCE,
)

MIFF_STANDARD_TAGS: dict[str, tuple[str, MiffMetadataRole]] = {
    "background-color": ("BackgroundColor", "standard_metadata"),
    "blue-primary": ("BluePrimary", "standard_metadata"),
    "border-color": ("BorderColor", "standard_metadata"),
    "matt-color": ("MattColor", "standard_metadata"),
    "class": ("Class", "class"),
    "colors": ("Colors", "colors"),
    "colorspace": ("ColorSpace", "colorspace"),
    "columns": ("ImageWidth", "image_width"),
    "compression": ("Compression", "compression"),
    "delay": ("Delay", "standard_metadata"),
    "depth": ("Depth", "depth"),
    "dispose": ("Dispose", "standard_metadata"),
    "gamma": ("Gamma", "standard_metadata"),
    "green-primary": ("GreenPrimary", "standard_metadata"),
    "id": ("ID", "id"),
    "iterations": ("Iterations", "standard_metadata"),
    "label": ("Label", "standard_metadata"),
    "matte": ("Matte", "standard_metadata"),
    "montage": ("Montage", "standard_metadata"),
    "packets": ("Packets", "standard_metadata"),
    "page": ("Page", "standard_metadata"),
    "red-primary": ("RedPrimary", "standard_metadata"),
    "rendering-intent": ("RenderingIntent", "standard_metadata"),
    "resolution": ("Resolution", "standard_metadata"),
    "rows": ("ImageHeight", "image_height"),
    "scene": ("Scene", "standard_metadata"),
    "signature": ("Signature", "signature"),
    "units": ("Units", "standard_metadata"),
    "white-point": ("WhitePoint", "standard_metadata"),
}


@dataclass(frozen=True)
class MiffOutputEmissionGate:
    code: MiffEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MiffSignatureValidationPlan:
    required_prefix: bytes
    actual_prefix: bytes
    is_valid: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MiffHeaderBoundaryPlan:
    text_start_offset: int
    text_end_offset: int | None
    terminator_start_offset: int | None
    terminator_end_offset: int | None
    terminator_kind: MiffTerminatorKind
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MiffHeaderEntryPlan:
    index: int
    key: str
    exiftool_name: str
    value: str
    role: MiffMetadataRole
    action: MiffHeaderEntryAction
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MiffCommentPlan:
    index: int
    token_count: int
    terminated: bool
    action: MiffCommentAction
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MiffImageAttributesPlan:
    image_width: str | None
    image_height: str | None
    image_class: str | None
    colors: str | None
    colorspace: str | None
    compression: str | None
    depth: str | None
    signature: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MiffProfilePlan:
    index: int
    type_name: str
    declared_length_text: str
    declared_length: int | None
    payload_offset: int | None
    payload_end_offset: int | None
    payload_length: int | None
    route: MiffProfileRoute
    evidence_ids: tuple[str, ...]

    @property
    def payload_range(self) -> tuple[int, int] | None:
        if self.payload_offset is None or self.payload_end_offset is None:
            return None
        return (self.payload_offset, self.payload_end_offset)


@dataclass(frozen=True)
class MiffImageDataPlan:
    start_offset: int | None
    end_offset: int
    action: Literal["preserve"]
    evidence_ids: tuple[str, ...]

    @property
    def payload_length(self) -> int | None:
        if self.start_offset is None:
            return None
        return self.end_offset - self.start_offset


@dataclass(frozen=True)
class MiffRewriteRequest:
    target: str
    operation: MiffRewriteOperation
    value: bytes | None = None


@dataclass(frozen=True)
class MiffActionPlan:
    kind: MiffActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MiffImageTransactionPlan:
    status: MiffPlanStatus
    source_data: bytes
    signature: MiffSignatureValidationPlan
    header_boundary: MiffHeaderBoundaryPlan
    header_entries: tuple[MiffHeaderEntryPlan, ...]
    comments: tuple[MiffCommentPlan, ...]
    image_attributes: MiffImageAttributesPlan
    profiles: tuple[MiffProfilePlan, ...]
    image_data: MiffImageDataPlan
    rewrite_requests: tuple[MiffRewriteRequest, ...]
    actions: tuple[MiffActionPlan, ...]
    output_emission_gates: tuple[MiffOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"MIFF image transaction output is gated: {gate_codes}")
        return self.source_data


@dataclass(frozen=True)
class _HeaderParsePlan:
    entries: tuple[MiffHeaderEntryPlan, ...]
    comments: tuple[MiffCommentPlan, ...]
    gates: tuple[MiffOutputEmissionGate, ...]
    actions: tuple[MiffActionPlan, ...]


def build_miff_image_transaction_plan(
    miff_data: bytes,
    *,
    rewrite_requests: tuple[MiffRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> MiffImageTransactionPlan:
    """Build a source-backed MIFF image transaction plan."""

    gates: list[MiffOutputEmissionGate] = []
    actions: list[MiffActionPlan] = []
    signature = MiffSignatureValidationPlan(
        required_prefix=MIFF_SIGNATURE,
        actual_prefix=miff_data[:MIFF_SIGNATURE_LENGTH],
        is_valid=miff_data.startswith(MIFF_SIGNATURE),
        evidence_ids=(MIFF_SIGNATURE_SOURCE,),
    )
    header_boundary = _header_boundary(miff_data)

    if len(miff_data) < MIFF_SIGNATURE_LENGTH:
        gates.append(
            MiffOutputEmissionGate(
                code="truncated_miff_signature",
                reason="ExifTool's MIFF reader requires a 14-byte initial signature read.",
                evidence_ids=(MIFF_SIGNATURE_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=miff_data,
            signature=signature,
            header_boundary=header_boundary,
            header_entries=(),
            comments=(),
            image_attributes=_image_attributes(()),
            profiles=(),
            image_data=_image_data(None, len(miff_data)),
            rewrite_requests=rewrite_requests,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    if not signature.is_valid:
        gates.append(
            MiffOutputEmissionGate(
                code="unsupported_miff_signature",
                reason="Input does not satisfy ExifTool's id=ImageMagick MIFF gate.",
                evidence_ids=(MIFF_SIGNATURE_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=miff_data,
            signature=signature,
            header_boundary=header_boundary,
            header_entries=(),
            comments=(),
            image_attributes=_image_attributes(()),
            profiles=(),
            image_data=_image_data(None, len(miff_data)),
            rewrite_requests=rewrite_requests,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    actions.append(
        MiffActionPlan(
            kind="validate_signature",
            target="MIFF",
            byte_range=(0, MIFF_SIGNATURE_LENGTH),
            reason="Input satisfied ExifTool's MIFF signature gate.",
            evidence_ids=(MIFF_SIGNATURE_SOURCE,),
        )
    )

    if header_boundary.terminator_start_offset is None:
        gates.append(
            MiffOutputEmissionGate(
                code="missing_miff_text_terminator",
                reason=(
                    "The MIFF text section terminator is absent, so the image payload "
                    "boundary cannot be planned safely."
                ),
                evidence_ids=(MIFF_TEXT_TERMINATOR_SOURCE,),
            )
        )
        return _final_plan(
            status="unsupported",
            source_data=miff_data,
            signature=signature,
            header_boundary=header_boundary,
            header_entries=(),
            comments=(),
            image_attributes=_image_attributes(()),
            profiles=(),
            image_data=_image_data(None, len(miff_data)),
            rewrite_requests=rewrite_requests,
            actions=tuple(actions),
            gates=gates,
            allow_output_emission=allow_output_emission,
        )

    terminator_start = header_boundary.terminator_start_offset
    terminator_end = header_boundary.terminator_end_offset
    if terminator_end is None:
        raise AssertionError("MIFF terminator end is required after terminator discovery")
    parse_plan = _parse_header(miff_data[MIFF_SIGNATURE_LENGTH:terminator_start])
    gates.extend(parse_plan.gates)
    actions.extend(parse_plan.actions)
    image_attributes = _image_attributes(parse_plan.entries)
    actions.append(
        MiffActionPlan(
            kind="extract_image_attributes",
            target="MIFF::Main image attributes",
            byte_range=(0, terminator_end),
            reason=(
                "Image dimensions, class, colors, colorspace, compression, depth, "
                "and signature were collected from MIFF::Main keys."
            ),
            evidence_ids=(MIFF_MAIN_TABLE_SOURCE, MIFF_DYNAMIC_TAG_SOURCE),
        )
    )

    profiles, profile_gates, profile_actions, image_start = _profile_plans(
        miff_data,
        terminator_end,
        parse_plan.entries,
    )
    gates.extend(profile_gates)
    actions.extend(profile_actions)
    image_data = _image_data(image_start, len(miff_data))
    if image_start is not None:
        actions.append(
            MiffActionPlan(
                kind="preserve_image_payload",
                target="image_payload",
                byte_range=(image_start, len(miff_data)),
                reason="ExifTool's MIFF reader preserves bytes after text and profile data.",
                evidence_ids=(MIFF_TEXT_TERMINATOR_SOURCE, MIFF_PROFILE_LENGTH_SOURCE),
            )
        )

    for request in rewrite_requests:
        gates.append(
            MiffOutputEmissionGate(
                code="rewrite_requested_requires_miff_writer",
                reason=(
                    f"MIFF {request.operation} for {request.target} was requested, but "
                    "ExifTool's MIFF module has no writer."
                ),
                evidence_ids=(MIFF_DESCRIPTION_SOURCE,),
            )
        )
        actions.append(
            MiffActionPlan(
                kind="block_requested_rewrite",
                target=request.target,
                byte_range=None,
                reason="MIFF rewrites are blocked until a source-backed writer exists.",
                evidence_ids=(MIFF_DESCRIPTION_SOURCE,),
            )
        )

    structural_codes = {
        "missing_miff_text_terminator",
        "unrecognized_miff_header_data",
        "unterminated_miff_comment",
        "unterminated_miff_braced_value",
        "invalid_miff_profile_length",
        "truncated_miff_profile",
    }
    status: MiffPlanStatus = (
        "unsupported" if any(gate.code in structural_codes for gate in gates) else "planned"
    )
    return _final_plan(
        status=status,
        source_data=miff_data,
        signature=signature,
        header_boundary=header_boundary,
        header_entries=parse_plan.entries,
        comments=parse_plan.comments,
        image_attributes=image_attributes,
        profiles=profiles,
        image_data=image_data,
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        gates=gates,
        allow_output_emission=allow_output_emission,
    )


plan_miff_image_transaction = build_miff_image_transaction_plan


def _header_boundary(miff_data: bytes) -> MiffHeaderBoundaryPlan:
    new_offset = miff_data.find(MIFF_NEW_TEXT_TERMINATOR, MIFF_SIGNATURE_LENGTH)
    if new_offset >= 0:
        return MiffHeaderBoundaryPlan(
            text_start_offset=MIFF_SIGNATURE_LENGTH,
            text_end_offset=new_offset,
            terminator_start_offset=new_offset,
            terminator_end_offset=new_offset + len(MIFF_NEW_TEXT_TERMINATOR),
            terminator_kind="new_text_section",
            evidence_ids=(MIFF_TEXT_TERMINATOR_SOURCE,),
        )
    old_offset = miff_data.find(MIFF_OLD_TEXT_TERMINATOR, MIFF_SIGNATURE_LENGTH)
    if old_offset >= 0:
        return MiffHeaderBoundaryPlan(
            text_start_offset=MIFF_SIGNATURE_LENGTH,
            text_end_offset=old_offset,
            terminator_start_offset=old_offset,
            terminator_end_offset=old_offset + len(MIFF_OLD_TEXT_TERMINATOR),
            terminator_kind="old_text_section",
            evidence_ids=(MIFF_TEXT_TERMINATOR_SOURCE,),
        )
    return MiffHeaderBoundaryPlan(
        text_start_offset=MIFF_SIGNATURE_LENGTH,
        text_end_offset=None,
        terminator_start_offset=None,
        terminator_end_offset=None,
        terminator_kind="missing",
        evidence_ids=(MIFF_TEXT_TERMINATOR_SOURCE,),
    )


def _parse_header(header_tail: bytes) -> _HeaderParsePlan:
    entries: list[MiffHeaderEntryPlan] = []
    comments: list[MiffCommentPlan] = []
    gates: list[MiffOutputEmissionGate] = []
    actions: list[MiffActionPlan] = []
    tokens = [MIFF_SIGNATURE.decode("ascii"), *_latin1(header_tail).split()]
    mode: Literal["normal", "comment", "value"] = "normal"
    comment_token_count = 0
    comment_index = 0
    value_key = ""
    value_text = ""

    for token in tokens:
        if mode == "comment":
            comment_token_count += 1
            if token.endswith("}"):
                comments.append(
                    MiffCommentPlan(
                        index=comment_index,
                        token_count=comment_token_count,
                        terminated=True,
                        action="skip_comment",
                        evidence_ids=(MIFF_HEADER_PARSE_SOURCE,),
                    )
                )
                actions.append(
                    MiffActionPlan(
                        kind="skip_comment",
                        target=f"comment:{comment_index}",
                        byte_range=None,
                        reason="Brace comments are skipped by ExifTool's MIFF parser.",
                        evidence_ids=(MIFF_HEADER_PARSE_SOURCE,),
                    )
                )
                mode = "normal"
            continue

        if token.startswith("{"):
            mode = "comment"
            comment_token_count = 1
            comment_index = len(comments)
            if token.endswith("}"):
                comments.append(
                    MiffCommentPlan(
                        index=comment_index,
                        token_count=comment_token_count,
                        terminated=True,
                        action="skip_comment",
                        evidence_ids=(MIFF_HEADER_PARSE_SOURCE,),
                    )
                )
                actions.append(
                    MiffActionPlan(
                        kind="skip_comment",
                        target=f"comment:{comment_index}",
                        byte_range=None,
                        reason="Brace comments are skipped by ExifTool's MIFF parser.",
                        evidence_ids=(MIFF_HEADER_PARSE_SOURCE,),
                    )
                )
                mode = "normal"
            continue

        if mode == "value":
            value_text = f"{value_text} {token}"
            if not token.endswith("}"):
                continue
            mode = "normal"
            entries.append(_entry_plan(len(entries), value_key, _strip_braces(value_text)))
            continue

        if token.startswith(":"):
            break

        if "=" not in token:
            gates.append(
                MiffOutputEmissionGate(
                    code="unrecognized_miff_header_data",
                    reason="ExifTool stops MIFF parsing when a header token is not recognized.",
                    evidence_ids=(MIFF_HEADER_PARSE_SOURCE,),
                )
            )
            break

        key, value = token.rsplit("=", 1)
        if not key or not value:
            gates.append(
                MiffOutputEmissionGate(
                    code="unrecognized_miff_header_data",
                    reason="ExifTool requires key=value tokens in the MIFF text section.",
                    evidence_ids=(MIFF_HEADER_PARSE_SOURCE,),
                )
            )
            break
        if value.startswith("{"):
            mode = "value"
            value_key = key
            value_text = value
            continue
        entries.append(_entry_plan(len(entries), key, value))

    if mode == "comment":
        comments.append(
            MiffCommentPlan(
                index=comment_index,
                token_count=comment_token_count,
                terminated=False,
                action="skip_comment",
                evidence_ids=(MIFF_HEADER_PARSE_SOURCE,),
            )
        )
        gates.append(
            MiffOutputEmissionGate(
                code="unterminated_miff_comment",
                reason="A MIFF brace comment began but did not terminate.",
                evidence_ids=(MIFF_HEADER_PARSE_SOURCE,),
            )
        )
    if mode == "value":
        gates.append(
            MiffOutputEmissionGate(
                code="unterminated_miff_braced_value",
                reason="A MIFF braced value began but did not terminate.",
                evidence_ids=(MIFF_HEADER_PARSE_SOURCE,),
            )
        )

    if entries:
        actions.append(
            MiffActionPlan(
                kind="parse_header_entries",
                target="MIFF::Main",
                byte_range=(0, MIFF_SIGNATURE_LENGTH + len(header_tail)),
                reason="MIFF key/value entries were parsed using ExifTool's text rules.",
                evidence_ids=(MIFF_HEADER_PARSE_SOURCE, MIFF_DYNAMIC_TAG_SOURCE),
            )
        )

    return _HeaderParsePlan(
        entries=tuple(entries),
        comments=tuple(comments),
        gates=tuple(gates),
        actions=tuple(actions),
    )


def _entry_plan(index: int, key: str, value: str) -> MiffHeaderEntryPlan:
    if key.startswith("profile-"):
        exiftool_name = _profile_name(key)
        return MiffHeaderEntryPlan(
            index=index,
            key=key,
            exiftool_name=exiftool_name,
            value=value,
            role="profile",
            action="queue_profile",
            evidence_ids=(MIFF_MAIN_TABLE_SOURCE, MIFF_DYNAMIC_TAG_SOURCE),
        )
    known = MIFF_STANDARD_TAGS.get(key)
    if known is None:
        return MiffHeaderEntryPlan(
            index=index,
            key=key,
            exiftool_name=key,
            value=value,
            role="arbitrary_metadata",
            action="extract_arbitrary_tag",
            evidence_ids=(MIFF_DYNAMIC_TAG_SOURCE,),
        )
    exiftool_name, role = known
    return MiffHeaderEntryPlan(
        index=index,
        key=key,
        exiftool_name=exiftool_name,
        value=value,
        role=role,
        action="extract_standard_tag",
        evidence_ids=(MIFF_MAIN_TABLE_SOURCE, MIFF_DYNAMIC_TAG_SOURCE),
    )


def _image_attributes(entries: tuple[MiffHeaderEntryPlan, ...]) -> MiffImageAttributesPlan:
    values = {entry.role: entry.value for entry in entries if entry.role != "standard_metadata"}
    return MiffImageAttributesPlan(
        image_width=values.get("image_width"),
        image_height=values.get("image_height"),
        image_class=values.get("class"),
        colors=values.get("colors"),
        colorspace=values.get("colorspace"),
        compression=values.get("compression"),
        depth=values.get("depth"),
        signature=values.get("signature"),
        evidence_ids=(MIFF_MAIN_TABLE_SOURCE,),
    )


def _profile_plans(
    miff_data: bytes,
    payload_cursor: int | None,
    entries: tuple[MiffHeaderEntryPlan, ...],
) -> tuple[
    tuple[MiffProfilePlan, ...],
    tuple[MiffOutputEmissionGate, ...],
    tuple[MiffActionPlan, ...],
    int | None,
]:
    if payload_cursor is None:
        return (), (), (), None
    profiles: list[MiffProfilePlan] = []
    gates: list[MiffOutputEmissionGate] = []
    actions: list[MiffActionPlan] = []
    cursor = payload_cursor
    for entry in entries:
        if entry.role != "profile":
            continue
        type_name = entry.key.removeprefix("profile-")
        if not entry.value.isdecimal():
            plan = MiffProfilePlan(
                index=len(profiles),
                type_name=type_name,
                declared_length_text=entry.value,
                declared_length=None,
                payload_offset=None,
                payload_end_offset=None,
                payload_length=None,
                route="block_invalid_profile_length",
                evidence_ids=(MIFF_PROFILE_LENGTH_SOURCE,),
            )
            profiles.append(plan)
            gates.append(
                MiffOutputEmissionGate(
                    code="invalid_miff_profile_length",
                    reason=f"MIFF {type_name} profile length is not decimal.",
                    evidence_ids=(MIFF_PROFILE_LENGTH_SOURCE,),
                )
            )
            break
        length = int(entry.value)
        end_offset = cursor + length
        if end_offset > len(miff_data):
            profiles.append(
                MiffProfilePlan(
                    index=len(profiles),
                    type_name=type_name,
                    declared_length_text=entry.value,
                    declared_length=length,
                    payload_offset=cursor,
                    payload_end_offset=None,
                    payload_length=None,
                    route="block_truncated_profile",
                    evidence_ids=(MIFF_PROFILE_LENGTH_SOURCE,),
                )
            )
            gates.append(
                MiffOutputEmissionGate(
                    code="truncated_miff_profile",
                    reason=f"MIFF {type_name} profile ended before {length} bytes could be read.",
                    evidence_ids=(MIFF_PROFILE_LENGTH_SOURCE,),
                )
            )
            return tuple(profiles), tuple(gates), tuple(actions), None

        payload = miff_data[cursor:end_offset]
        route, sources = _profile_route(type_name, payload)
        profiles.append(
            MiffProfilePlan(
                index=len(profiles),
                type_name=type_name,
                declared_length_text=entry.value,
                declared_length=length,
                payload_offset=cursor,
                payload_end_offset=end_offset,
                payload_length=length,
                route=route,
                evidence_ids=sources,
            )
        )
        actions.append(
            MiffActionPlan(
                kind="read_profile_payload",
                target=f"profile-{type_name}",
                byte_range=(cursor, end_offset),
                reason="Profile bytes were read after the MIFF text section.",
                evidence_ids=(MIFF_PROFILE_LENGTH_SOURCE,),
            )
        )
        actions.append(
            MiffActionPlan(
                kind="preserve_profile_payload",
                target=f"profile-{type_name}",
                byte_range=(cursor, end_offset),
                reason="MIFF profile payload bytes are preserved by this non-mutating plan.",
                evidence_ids=sources,
            )
        )
        cursor = end_offset
    return tuple(profiles), tuple(gates), tuple(actions), cursor


def _profile_route(
    type_name: str,
    payload: bytes,
) -> tuple[MiffProfileRoute, tuple[str, ...]]:
    if type_name == "icc":
        return "route_icc_profile", (MIFF_PROFILE_ROUTE_SOURCE,)
    if type_name == "iptc" and payload.startswith(b"8BIM"):
        return "route_photoshop_profile", (MIFF_PROFILE_ROUTE_SOURCE,)
    if type_name in {"APP1", "exif", "xmp"}:
        if payload.startswith(MIFF_EXIF_APP1_HEADER):
            return "route_exif_profile", (MIFF_PROFILE_ROUTE_SOURCE,)
        if payload.startswith(MIFF_XMP_APP1_HEADER):
            return "route_xmp_profile", (MIFF_PROFILE_ROUTE_SOURCE,)
    return "preserve_unknown_profile", (MIFF_PROFILE_ROUTE_SOURCE, MIFF_UNKNOWN_PROFILE_SOURCE)


def _profile_name(key: str) -> str:
    profile_type = key.removeprefix("profile-")
    if profile_type == "APP1":
        return "APP1_Profile"
    if profile_type == "exif":
        return "EXIF_Profile"
    if profile_type == "icc":
        return "ICC_Profile"
    if profile_type == "iptc":
        return "IPTC_Profile"
    if profile_type == "xmp":
        return "XMP_Profile"
    return key


def _image_data(start_offset: int | None, end_offset: int) -> MiffImageDataPlan:
    return MiffImageDataPlan(
        start_offset=start_offset,
        end_offset=end_offset,
        action="preserve",
        evidence_ids=(MIFF_TEXT_TERMINATOR_SOURCE, MIFF_PROFILE_LENGTH_SOURCE),
    )


def _final_plan(
    *,
    status: MiffPlanStatus,
    source_data: bytes,
    signature: MiffSignatureValidationPlan,
    header_boundary: MiffHeaderBoundaryPlan,
    header_entries: tuple[MiffHeaderEntryPlan, ...],
    comments: tuple[MiffCommentPlan, ...],
    image_attributes: MiffImageAttributesPlan,
    profiles: tuple[MiffProfilePlan, ...],
    image_data: MiffImageDataPlan,
    rewrite_requests: tuple[MiffRewriteRequest, ...],
    actions: tuple[MiffActionPlan, ...],
    gates: list[MiffOutputEmissionGate],
    allow_output_emission: bool,
) -> MiffImageTransactionPlan:
    if status == "planned" and not allow_output_emission:
        gates.append(
            MiffOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="MIFF planning is non-mutating; callers must opt in before bytes emit.",
                evidence_ids=(MIFF_DESCRIPTION_SOURCE,),
            )
        )
    return MiffImageTransactionPlan(
        status=status,
        source_data=source_data,
        signature=signature,
        header_boundary=header_boundary,
        header_entries=header_entries,
        comments=comments,
        image_attributes=image_attributes,
        profiles=profiles,
        image_data=image_data,
        rewrite_requests=rewrite_requests,
        actions=actions,
        output_emission_gates=tuple(gates),
        evidence_ids=_unique_sources(
            (
                *MIFF_TRANSACTION_SOURCES,
                *signature.evidence_ids,
                *header_boundary.evidence_ids,
                *image_attributes.evidence_ids,
                *image_data.evidence_ids,
                *(source for entry in header_entries for source in entry.evidence_ids),
                *(source for comment in comments for source in comment.evidence_ids),
                *(source for profile in profiles for source in profile.evidence_ids),
                *(source for action in actions for source in action.evidence_ids),
                *(source for gate in gates for source in gate.evidence_ids),
            )
        ),
    )


def _strip_braces(value: str) -> str:
    value = value.removeprefix("{")
    value = value.removesuffix("}")
    return value


def _latin1(data: bytes) -> str:
    return data.decode("latin-1")


def _unique_sources(references: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)
