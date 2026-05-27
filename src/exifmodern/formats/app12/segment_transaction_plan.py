"""APP12 segment transaction planning grounded in ExifTool APP12.pm."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

DUCKY_MAGIC = b"Ducky"
DUCKY_MAGIC_LENGTH = 5
DUCKY_TERMINATOR = b"\x00\x00"

type App12PlanStatus = Literal["planned", "blocked", "unsupported"]
type App12SegmentKind = Literal["ducky", "picture_info", "unknown"]
type App12RewriteGroup = Literal["Ducky", "PictureInfo"]
type App12RewriteAction = Literal["write", "delete", "create"]
type App12DuckyTagName = Literal["Quality", "Comment", "Copyright"]
type App12DuckyValue = int | str
type App12ConvertedValue = int | float | str | None
type App12DuckyBlockAction = Literal[
    "preserve",
    "replace",
    "delete",
    "create",
    "preserve_unknown",
]
type App12EmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "invalid_ducky_block_length",
    "ducky_write_requires_ducky_segment",
    "picture_info_write_not_defined",
    "unsupported_ducky_tag",
    "invalid_ducky_quality_value",
    "invalid_ducky_text_value",
    "unrecognized_app12_segment",
]
type App12PictureInfoRouteKind = Literal[
    "observed_table_tag",
    "dynamic_camera_section_tag",
    "dynamic_image_tag",
]
type App12DuckyConversionStatus = Literal[
    "converted",
    "unknown_tag",
    "invalid_quality_length",
    "missing_text_count",
]

APP12_PICTURE_INFO_TABLE_SOURCE = "app12.picture.info.table"
APP12_DUCKY_TABLE_SOURCE = "app12.ducky.table"
APP12_WRITE_DUCKY_SOURCE = "app12.write.ducky"
APP12_PROCESS_DUCKY_SOURCE = "app12.process.ducky"
APP12_PROCESS_PICTURE_INFO_SOURCE = "app12.process.picture.info"

PICTURE_INFO_TOKEN_RE = re.compile(
    r"(\[.*?\]|[\w#-]+=[\x20-\x7e]+?(?=\s*([\n\r\0]|[\w#-]+=|\[|$)))"
)
PICTURE_INFO_SECTION_RE = re.compile(r"\[(\S+) ?Info\]", re.IGNORECASE)

PICTURE_INFO_TAGS: dict[str, tuple[str, str]] = {
    "FNumber": ("FNumber", "Image"),
    "Aperture": ("Aperture", "Image"),
    "TimeDate": ("DateTimeOriginal", "Time"),
    "Shutter": ("ExposureTime", "Image"),
    "shtr": ("ExposureTime", "Image"),
    "Serial#": ("SerialNumber", "Camera"),
    "Flash": ("Flash", "Image"),
    "Macro": ("Macro", "Image"),
    "StrobeTime": ("StrobeTime", "Image"),
    "Ytarget": ("YTarget", "Image"),
    "ylevel": ("YLevel", "Image"),
    "FocusPos": ("FocusPos", "Image"),
    "FocusMode": ("FocusMode", "Image"),
    "Quality": ("Quality", "Image"),
    "ExpBias": ("ExposureCompensation", "Image"),
    "FWare": ("FirmwareVersion", "Image"),
    "Resolution": ("Resolution", "Image"),
    "Protect": ("Protect", "Image"),
    "ContTake": ("ContTake", "Image"),
    "ImageSize": ("ImageSize", "Image"),
    "ColorMode": ("ColorMode", "Image"),
    "Zoom": ("Zoom", "Image"),
    "ZoomPos": ("ZoomPos", "Image"),
    "LightS": ("LightS", "Image"),
    "Type": ("CameraType", "Camera"),
    "Version": ("Version", "Camera"),
    "ID": ("ID", "Camera"),
}

DUCKY_TAG_NAMES: dict[int, App12DuckyTagName] = {
    1: "Quality",
    2: "Comment",
    3: "Copyright",
}
DUCKY_TAG_IDS: dict[App12DuckyTagName, int] = {
    "Quality": 1,
    "Comment": 2,
    "Copyright": 3,
}


@dataclass(frozen=True)
class App12SegmentRewriteRequest:
    group: App12RewriteGroup
    tag_name: str
    action: App12RewriteAction
    value: App12DuckyValue | None = None


@dataclass(frozen=True)
class App12EmissionGate:
    code: App12EmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class App12PictureInfoTagPlan:
    index: int
    raw_name: str
    tag_name: str
    raw_value: str
    converted_value: App12ConvertedValue
    section: str
    group_2: str
    route_kind: App12PictureInfoRouteKind
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class App12DuckyBlockPlan:
    index: int
    tag_id: int
    tag_name: str | None
    header_offset: int
    value_offset: int
    declared_length: int
    end_offset: int
    value: bytes
    converted_value: App12ConvertedValue
    text_character_count: int | None
    conversion_status: App12DuckyConversionStatus
    action: App12DuckyBlockAction
    replacement_value: bytes | None
    evidence_ids: tuple[str, ...]

    @property
    def encoded_length(self) -> int:
        return 4 + self.declared_length


@dataclass(frozen=True)
class App12SegmentTransactionPlan:
    status: App12PlanStatus
    segment_kind: App12SegmentKind
    source_payload: bytes
    picture_info_tags: tuple[App12PictureInfoTagPlan, ...]
    ducky_blocks: tuple[App12DuckyBlockPlan, ...]
    output_payload: bytes
    output_emission_gates: tuple[App12EmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            code = "unsupported_app12_plan"
            if self.output_emission_gates:
                code = self.output_emission_gates[0].code
            raise ValueError(code)
        return self.output_payload


@dataclass(frozen=True)
class ParsedDuckyBlocks:
    blocks: tuple[App12DuckyBlockPlan, ...]
    gates: tuple[App12EmissionGate, ...]


def build_app12_segment_transaction_plan(
    segment_payload: bytes,
    rewrite_requests: Sequence[App12SegmentRewriteRequest] = (),
    *,
    allow_output_emission: bool = False,
) -> App12SegmentTransactionPlan:
    segment_kind = classify_app12_segment(segment_payload, rewrite_requests)
    if segment_kind == "ducky":
        return build_ducky_plan(segment_payload, rewrite_requests, allow_output_emission)
    if segment_kind == "picture_info":
        return build_picture_info_plan(segment_payload, rewrite_requests, allow_output_emission)
    return build_unknown_plan(segment_payload, allow_output_emission)


def classify_app12_segment(
    segment_payload: bytes, rewrite_requests: Sequence[App12SegmentRewriteRequest]
) -> App12SegmentKind:
    if segment_payload.startswith(DUCKY_MAGIC):
        return "ducky"
    if not segment_payload and any(request.group == "Ducky" for request in rewrite_requests):
        return "ducky"
    if parse_picture_info_tags(segment_payload):
        return "picture_info"
    return "unknown"


def build_ducky_plan(
    segment_payload: bytes,
    rewrite_requests: Sequence[App12SegmentRewriteRequest],
    allow_output_emission: bool,
) -> App12SegmentTransactionPlan:
    payload = segment_payload
    if not payload:
        payload = DUCKY_MAGIC
    parsed = parse_ducky_blocks(payload)
    gates = list(parsed.gates)
    gates.extend(validate_rewrite_requests_for_ducky(rewrite_requests))
    blocks, output_payload = plan_ducky_output(payload, parsed.blocks, rewrite_requests, gates)
    if not allow_output_emission:
        gates.append(non_mutating_gate())
    evidence_ids = evidence_ids_from(
        (
            APP12_DUCKY_TABLE_SOURCE,
            APP12_PROCESS_DUCKY_SOURCE,
            APP12_WRITE_DUCKY_SOURCE,
        )
    )
    status: App12PlanStatus = "planned"
    if parsed.gates:
        status = "blocked"
    return App12SegmentTransactionPlan(
        status=status,
        segment_kind="ducky",
        source_payload=segment_payload,
        picture_info_tags=(),
        ducky_blocks=blocks,
        output_payload=output_payload,
        output_emission_gates=tuple(gates),
        evidence_ids=evidence_ids,
    )


def build_picture_info_plan(
    segment_payload: bytes,
    rewrite_requests: Sequence[App12SegmentRewriteRequest],
    allow_output_emission: bool,
) -> App12SegmentTransactionPlan:
    tags = parse_picture_info_tags(segment_payload)
    gates: list[App12EmissionGate] = []
    if rewrite_requests:
        gates.append(
            App12EmissionGate(
                code="picture_info_write_not_defined",
                reason="APP12.pm defines ProcessAPP12 for PictureInfo but no write routine.",
                evidence_ids=(APP12_PROCESS_PICTURE_INFO_SOURCE,),
            )
        )
    if not allow_output_emission:
        gates.append(non_mutating_gate())
    return App12SegmentTransactionPlan(
        status="planned",
        segment_kind="picture_info",
        source_payload=segment_payload,
        picture_info_tags=tags,
        ducky_blocks=(),
        output_payload=segment_payload,
        output_emission_gates=tuple(gates),
        evidence_ids=evidence_ids_from(
            (APP12_PICTURE_INFO_TABLE_SOURCE, APP12_PROCESS_PICTURE_INFO_SOURCE)
        ),
    )


def build_unknown_plan(
    segment_payload: bytes, allow_output_emission: bool
) -> App12SegmentTransactionPlan:
    gates = [
        App12EmissionGate(
            code="unrecognized_app12_segment",
            reason="APP12.pm only recognizes Ducky blocks or PictureInfo key/value tokens.",
            evidence_ids=(APP12_PROCESS_DUCKY_SOURCE, APP12_PROCESS_PICTURE_INFO_SOURCE),
        )
    ]
    if not allow_output_emission:
        gates.append(non_mutating_gate())
    return App12SegmentTransactionPlan(
        status="unsupported",
        segment_kind="unknown",
        source_payload=segment_payload,
        picture_info_tags=(),
        ducky_blocks=(),
        output_payload=segment_payload,
        output_emission_gates=tuple(gates),
        evidence_ids=evidence_ids_from(
            (APP12_PROCESS_DUCKY_SOURCE, APP12_PROCESS_PICTURE_INFO_SOURCE)
        ),
    )


def parse_picture_info_tags(segment_payload: bytes) -> tuple[App12PictureInfoTagPlan, ...]:
    text = segment_payload.decode("latin-1", errors="replace")
    tags: list[App12PictureInfoTagPlan] = []
    section = ""
    for match in PICTURE_INFO_TOKEN_RE.finditer(text):
        token = match.group(1)
        if token.startswith("["):
            section_match = PICTURE_INFO_SECTION_RE.search(token)
            section = "" if section_match is None else section_match.group(1)
            continue
        raw_name, raw_value = token.split("=", 1)
        tag_name, group_2, route_kind = picture_info_route(raw_name, section)
        tags.append(
            App12PictureInfoTagPlan(
                index=len(tags),
                raw_name=raw_name,
                tag_name=tag_name,
                raw_value=raw_value,
                converted_value=convert_picture_info_value(raw_name, raw_value),
                section=section,
                group_2=group_2,
                route_kind=route_kind,
                evidence_ids=(APP12_PICTURE_INFO_TABLE_SOURCE,),
            )
        )
    return tuple(tags)


def picture_info_route(raw_name: str, section: str) -> tuple[str, str, App12PictureInfoRouteKind]:
    known = PICTURE_INFO_TAGS.get(raw_name)
    if known is not None:
        return known[0], known[1], "observed_table_tag"
    tag_name = raw_name[:1].upper() + raw_name[1:]
    if section.lower() == "camera":
        return tag_name, "Camera", "dynamic_camera_section_tag"
    return tag_name, "Image", "dynamic_image_tag"


def convert_picture_info_value(raw_name: str, raw_value: str) -> App12ConvertedValue:
    if raw_name == "TimeDate" and raw_value.isdecimal():
        return datetime.fromtimestamp(int(raw_value), UTC).strftime("%Y:%m:%d %H:%M:%S")
    if raw_name in {"Shutter", "shtr"}:
        return float(raw_value) * 1e-6
    if raw_name == "FNumber":
        stripped = raw_value.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ")
        return parse_float_or_text(stripped)
    if raw_name in {"Flash", "Macro"} and raw_value.isdecimal():
        value = int(raw_value)
        if value == 0:
            return "Off"
        if value == 1:
            return "On"
        return value
    if raw_name == "ImageSize":
        return raw_value.replace("-", "x")
    return parse_number_or_text(raw_value)


def parse_number_or_text(raw_value: str) -> int | float | str:
    if raw_value.isdecimal():
        return int(raw_value)
    return parse_float_or_text(raw_value)


def parse_float_or_text(raw_value: str) -> float | str:
    try:
        return float(raw_value)
    except ValueError:
        return raw_value


def parse_ducky_blocks(segment_payload: bytes) -> ParsedDuckyBlocks:
    offset = DUCKY_MAGIC_LENGTH
    blocks: list[App12DuckyBlockPlan] = []
    gates: list[App12EmissionGate] = []
    while offset + 4 <= len(segment_payload):
        header_offset = offset
        tag_id = int.from_bytes(segment_payload[offset : offset + 2], "big")
        declared_length = int.from_bytes(segment_payload[offset + 2 : offset + 4], "big")
        value_offset = offset + 4
        end_offset = value_offset + declared_length
        if end_offset > len(segment_payload):
            gates.append(
                App12EmissionGate(
                    code="invalid_ducky_block_length",
                    reason="Ducky block length extends past the APP12 payload.",
                    evidence_ids=(APP12_PROCESS_DUCKY_SOURCE, APP12_WRITE_DUCKY_SOURCE),
                )
            )
            break
        value = segment_payload[value_offset:end_offset]
        tag_name = DUCKY_TAG_NAMES.get(tag_id)
        converted_value, text_count, conversion_status = convert_ducky_value(tag_id, value)
        blocks.append(
            App12DuckyBlockPlan(
                index=len(blocks),
                tag_id=tag_id,
                tag_name=tag_name,
                header_offset=header_offset,
                value_offset=value_offset,
                declared_length=declared_length,
                end_offset=end_offset,
                value=value,
                converted_value=converted_value,
                text_character_count=text_count,
                conversion_status=conversion_status,
                action="preserve" if tag_name is not None else "preserve_unknown",
                replacement_value=None,
                evidence_ids=(APP12_DUCKY_TABLE_SOURCE, APP12_PROCESS_DUCKY_SOURCE),
            )
        )
        offset = end_offset
    return ParsedDuckyBlocks(tuple(blocks), tuple(gates))


def convert_ducky_value(
    tag_id: int, value: bytes
) -> tuple[App12ConvertedValue, int | None, App12DuckyConversionStatus]:
    if tag_id == 1:
        if len(value) != 4:
            return None, None, "invalid_quality_length"
        return int.from_bytes(value, "big"), None, "converted"
    if tag_id in {2, 3}:
        if len(value) < 4:
            return "", None, "missing_text_count"
        text_count = int.from_bytes(value[:4], "big")
        return value[4:].decode("utf-16-be", errors="replace"), text_count, "converted"
    return None, None, "unknown_tag"


def validate_rewrite_requests_for_ducky(
    rewrite_requests: Sequence[App12SegmentRewriteRequest],
) -> tuple[App12EmissionGate, ...]:
    gates: list[App12EmissionGate] = []
    for request in rewrite_requests:
        if request.group == "PictureInfo":
            gates.append(
                App12EmissionGate(
                    code="picture_info_write_not_defined",
                    reason="APP12.pm has no PictureInfo writer.",
                    evidence_ids=(APP12_PROCESS_PICTURE_INFO_SOURCE,),
                )
            )
            continue
        ducky_tag = requested_ducky_tag_name(request.tag_name)
        if ducky_tag is None:
            gates.append(
                App12EmissionGate(
                    code="unsupported_ducky_tag",
                    reason=(
                        "APP12.pm WriteDucky only has table entries for Quality, "
                        "Comment, and Copyright."
                    ),
                    evidence_ids=(APP12_DUCKY_TABLE_SOURCE,),
                )
            )
            continue
        tag_id = DUCKY_TAG_IDS[ducky_tag]
        if request.action != "delete":
            encoded_gate = validate_ducky_request_value(tag_id, request.value)
            if encoded_gate is not None:
                gates.append(encoded_gate)
    return tuple(gates)


def validate_ducky_request_value(
    tag_id: int, value: App12DuckyValue | None
) -> App12EmissionGate | None:
    if tag_id == 1:
        if not isinstance(value, int) or value < 0 or value > 0xFFFFFFFF:
            return App12EmissionGate(
                code="invalid_ducky_quality_value",
                reason="Ducky Quality writes use an unsigned 32-bit big-endian integer.",
                evidence_ids=(APP12_DUCKY_TABLE_SOURCE,),
            )
        return None
    if not isinstance(value, str) or len(value) > 0xFFFFFFFF:
        return App12EmissionGate(
            code="invalid_ducky_text_value",
            reason="Ducky text writes use a character count and UTF-16 big-endian text.",
            evidence_ids=(APP12_DUCKY_TABLE_SOURCE,),
        )
    return None


def requested_ducky_tag_name(tag_name: str) -> App12DuckyTagName | None:
    if tag_name == "Quality":
        return "Quality"
    if tag_name == "Comment":
        return "Comment"
    if tag_name == "Copyright":
        return "Copyright"
    return None


def plan_ducky_output(
    segment_payload: bytes,
    parsed_blocks: tuple[App12DuckyBlockPlan, ...],
    rewrite_requests: Sequence[App12SegmentRewriteRequest],
    gates: Sequence[App12EmissionGate],
) -> tuple[tuple[App12DuckyBlockPlan, ...], bytes]:
    if gates:
        return parsed_blocks, segment_payload
    ducky_requests = {
        DUCKY_TAG_IDS[ducky_tag]: request
        for request in rewrite_requests
        if request.group == "Ducky"
        for ducky_tag in (requested_ducky_tag_name(request.tag_name),)
        if ducky_tag is not None
    }
    output_blocks: list[bytes] = []
    planned_blocks: list[App12DuckyBlockPlan] = []
    done_tags: set[int] = set()
    for block in parsed_blocks:
        done_tags.add(block.tag_id)
        request = ducky_requests.get(block.tag_id)
        if request is None:
            output_blocks.append(encode_ducky_block(block.tag_id, block.value))
            planned_blocks.append(block)
            continue
        if request.action == "delete":
            planned_blocks.append(rewrite_block_action(block, "delete", None))
            continue
        if request.action == "create":
            output_blocks.append(encode_ducky_block(block.tag_id, block.value))
            planned_blocks.append(block)
            continue
        replacement_value = encode_ducky_request_value(block.tag_id, request.value)
        output_blocks.append(encode_ducky_block(block.tag_id, replacement_value))
        planned_blocks.append(rewrite_block_action(block, "replace", replacement_value))
    for tag_id in sorted(ducky_requests, reverse=True):
        if tag_id in done_tags:
            continue
        request = ducky_requests[tag_id]
        if request.action != "create":
            continue
        replacement_value = encode_ducky_request_value(tag_id, request.value)
        output_blocks.append(encode_ducky_block(tag_id, replacement_value))
        planned_blocks.append(created_ducky_block(tag_id, replacement_value))
    new_directory = b"".join(output_blocks)
    if new_directory:
        new_directory += DUCKY_TERMINATOR
    return tuple(planned_blocks), DUCKY_MAGIC + new_directory


def rewrite_block_action(
    block: App12DuckyBlockPlan,
    action: Literal["replace", "delete"],
    replacement_value: bytes | None,
) -> App12DuckyBlockPlan:
    return App12DuckyBlockPlan(
        index=block.index,
        tag_id=block.tag_id,
        tag_name=block.tag_name,
        header_offset=block.header_offset,
        value_offset=block.value_offset,
        declared_length=block.declared_length,
        end_offset=block.end_offset,
        value=block.value,
        converted_value=block.converted_value,
        text_character_count=block.text_character_count,
        conversion_status=block.conversion_status,
        action=action,
        replacement_value=replacement_value,
        evidence_ids=(APP12_WRITE_DUCKY_SOURCE,),
    )


def created_ducky_block(tag_id: int, value: bytes) -> App12DuckyBlockPlan:
    converted_value, text_count, conversion_status = convert_ducky_value(tag_id, value)
    return App12DuckyBlockPlan(
        index=-1,
        tag_id=tag_id,
        tag_name=DUCKY_TAG_NAMES[tag_id],
        header_offset=-1,
        value_offset=-1,
        declared_length=len(value),
        end_offset=-1,
        value=b"",
        converted_value=converted_value,
        text_character_count=text_count,
        conversion_status=conversion_status,
        action="create",
        replacement_value=value,
        evidence_ids=(APP12_WRITE_DUCKY_SOURCE,),
    )


def encode_ducky_block(tag_id: int, value: bytes) -> bytes:
    return tag_id.to_bytes(2, "big") + len(value).to_bytes(2, "big") + value


def encode_ducky_request_value(tag_id: int, value: App12DuckyValue | None) -> bytes:
    if tag_id == 1 and isinstance(value, int):
        return value.to_bytes(4, "big")
    if isinstance(value, str):
        encoded = value.encode("utf-16-be")
        return len(value).to_bytes(4, "big") + encoded
    raise ValueError("invalid_ducky_request_value")


def non_mutating_gate() -> App12EmissionGate:
    return App12EmissionGate(
        code="non_mutating_plan_requires_explicit_emission",
        reason="Plans do not emit bytes unless allow_output_emission is enabled.",
        evidence_ids=(APP12_PROCESS_DUCKY_SOURCE, APP12_PROCESS_PICTURE_INFO_SOURCE),
    )


def evidence_ids_from(references: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    output: list[str] = []
    for reference in references:
        if reference in seen:
            continue
        seen.add(reference)
        output.append(reference)
    return tuple(output)
