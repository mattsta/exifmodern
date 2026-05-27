"""Non-mutating Lytro LFP metadata transaction planning."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonValue

type LytroEvidenceId = str

LYTRO_SIGNATURE = b"\x89LFP\r\n\x1a\n"
LFP_FILE_HEADER_SIZE = 16
LFP_SEGMENT_HEADER_SIZE = 16
LFP_SEGMENT_ID_SIZE = 80
LFP_SEGMENT_PREFIX_SIZE = LFP_SEGMENT_HEADER_SIZE + LFP_SEGMENT_ID_SIZE
LFP_MAX_READ_PAYLOAD_SIZE = 20_000_000

type LytroPlanStatus = Literal["planned", "unsupported"]
type LytroSegmentKind = Literal[
    "json_metadata",
    "embedded_image",
    "large_payload_preserve",
    "unknown_payload_preserve",
]
type LytroMetadataRouteKind = Literal["known_table", "dynamic_json"]
type LytroGroup2 = Literal["Camera", "Image", "Time", "Preview"]
type LytroResponsibilityKind = Literal[
    "container",
    "camera_metadata",
    "time_metadata",
    "image_metadata",
    "depth_metadata",
    "focus_metadata",
    "preview_payload",
    "unknown_payload",
]
type LytroRewriteTarget = Literal[
    "container",
    "json_metadata",
    "embedded_image",
    "tag",
]
type LytroRewriteOperation = Literal["insert", "replace", "delete"]
type LytroActionKind = Literal[
    "validate_lfp_header",
    "scan_lfp_segment",
    "route_json_metadata",
    "route_embedded_image",
    "preserve_payload",
    "preserve_unknown_tag",
    "block_requested_rewrite",
    "no_metadata_mutation",
]
type LytroBlockerCode = Literal[
    "truncated_lfp_header",
    "invalid_lfp_header",
    "truncated_lfp_segment_header",
    "malformed_lfp_segment_header",
    "invalid_lfp_segment_size",
    "truncated_lfp_segment_id",
    "truncated_lfp_segment_payload",
    "truncated_lfp_large_payload",
    "malformed_json_metadata",
    "invalid_lfp_metadata",
    "rewrite_requested_requires_lytro_writer",
]
type LytroEmissionGateCode = Literal[
    "truncated_lfp_header",
    "invalid_lfp_header",
    "truncated_lfp_segment_header",
    "malformed_lfp_segment_header",
    "invalid_lfp_segment_size",
    "truncated_lfp_segment_id",
    "truncated_lfp_segment_payload",
    "truncated_lfp_large_payload",
    "malformed_json_metadata",
    "invalid_lfp_metadata",
    "rewrite_requested_requires_lytro_writer",
    "non_mutating_plan_requires_explicit_emission",
]

LYTRO_MAIN_TABLE_SOURCE = "lytro.main-table"
LYTRO_EXTRACT_TAGS_SOURCE = "lytro.extract-tags"
LYTRO_PROCESS_LFP_SOURCE = "lytro.process-lfp"
LYTRO_TRANSACTION_SOURCES = (
    LYTRO_MAIN_TABLE_SOURCE,
    LYTRO_EXTRACT_TAGS_SOURCE,
    LYTRO_PROCESS_LFP_SOURCE,
)


@dataclass(frozen=True)
class LytroTagDefinition:
    tag_name: str
    group2: LytroGroup2
    responsibility: LytroResponsibilityKind
    evidence_ids: tuple[LytroEvidenceId, ...] = (LYTRO_MAIN_TABLE_SOURCE,)


LYTRO_KNOWN_TAGS: dict[str, LytroTagDefinition] = {
    "Type": LytroTagDefinition("CameraType", "Camera", "camera_metadata"),
    "CameraMake": LytroTagDefinition("Make", "Camera", "camera_metadata"),
    "CameraModel": LytroTagDefinition("Model", "Camera", "camera_metadata"),
    "CameraSerialNumber": LytroTagDefinition("SerialNumber", "Camera", "camera_metadata"),
    "CameraFirmware": LytroTagDefinition("FirmwareVersion", "Camera", "camera_metadata"),
    "DevicesAccelerometerSampleArrayTime": LytroTagDefinition(
        "AccelerometerTime",
        "Camera",
        "camera_metadata",
    ),
    "DevicesAccelerometerSampleArrayX": LytroTagDefinition(
        "AccelerometerX",
        "Camera",
        "camera_metadata",
    ),
    "DevicesAccelerometerSampleArrayY": LytroTagDefinition(
        "AccelerometerY",
        "Camera",
        "camera_metadata",
    ),
    "DevicesAccelerometerSampleArrayZ": LytroTagDefinition(
        "AccelerometerZ",
        "Camera",
        "camera_metadata",
    ),
    "DevicesClockZuluTime": LytroTagDefinition("DateTimeOriginal", "Time", "time_metadata"),
    "DevicesLensFNumber": LytroTagDefinition("FNumber", "Camera", "camera_metadata"),
    "DevicesLensFocalLength": LytroTagDefinition("FocalLength", "Camera", "camera_metadata"),
    "DevicesLensTemperature": LytroTagDefinition(
        "LensTemperature",
        "Camera",
        "camera_metadata",
    ),
    "DevicesSocTemperature": LytroTagDefinition("SocTemperature", "Camera", "camera_metadata"),
    "DevicesShutterFrameExposureDuration": LytroTagDefinition(
        "FrameExposureTime",
        "Camera",
        "camera_metadata",
    ),
    "DevicesShutterPixelExposureDuration": LytroTagDefinition(
        "ExposureTime",
        "Camera",
        "camera_metadata",
    ),
    "DevicesSensorPixelPitch": LytroTagDefinition(
        "FocalPlaneXResolution",
        "Camera",
        "camera_metadata",
    ),
    "DevicesSensorSensorSerial": LytroTagDefinition(
        "SensorSerialNumber",
        "Camera",
        "camera_metadata",
    ),
    "DevicesSensorIso": LytroTagDefinition("ISO", "Camera", "camera_metadata"),
    "ImageLimitExposureBias": LytroTagDefinition(
        "ImageLimitExposureBias",
        "Image",
        "image_metadata",
    ),
    "ImageModulationExposureBias": LytroTagDefinition(
        "ImageModulationExposureBias",
        "Image",
        "image_metadata",
    ),
    "ImageOrientation": LytroTagDefinition("Orientation", "Image", "image_metadata"),
}


@dataclass(frozen=True)
class LytroRewriteRequest:
    target: LytroRewriteTarget
    operation: LytroRewriteOperation
    tag_path: str | None = None
    payload: bytes | None = None


@dataclass(frozen=True)
class LytroTransactionBlocker:
    code: LytroBlockerCode
    reason: str
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[LytroEvidenceId, ...]


@dataclass(frozen=True)
class LytroOutputEmissionGate:
    code: LytroEmissionGateCode
    reason: str
    evidence_ids: tuple[LytroEvidenceId, ...]


@dataclass(frozen=True)
class LytroHeaderValidationPlan:
    signature_range: tuple[int, int]
    signature: bytes
    reason: LytroBlockerCode | None
    evidence_ids: tuple[LytroEvidenceId, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class LytroMetadataTagPlan:
    raw_path: str
    tag_name: str
    value: JsonValue
    converted_value: JsonValue
    print_value: str | None
    group2: LytroGroup2
    responsibility: LytroResponsibilityKind
    route_kind: LytroMetadataRouteKind
    is_list: bool
    preserves_unknown: bool
    evidence_ids: tuple[LytroEvidenceId, ...]


@dataclass(frozen=True)
class LytroSegmentPlan:
    index: int
    marker: bytes
    identifier: str
    size: int
    kind: LytroSegmentKind
    header_range: tuple[int, int]
    id_range: tuple[int, int]
    payload_range: tuple[int, int]
    padding_range: tuple[int, int]
    payload_preserved: bool
    metadata_tags: tuple[LytroMetadataTagPlan, ...]
    evidence_ids: tuple[LytroEvidenceId, ...]


@dataclass(frozen=True)
class LytroActionPlan:
    kind: LytroActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[LytroEvidenceId, ...]


@dataclass(frozen=True)
class LytroMetadataTransactionPlan:
    status: LytroPlanStatus
    source_payload: bytes
    header_validation: LytroHeaderValidationPlan
    segments: tuple[LytroSegmentPlan, ...]
    rewrite_requests: tuple[LytroRewriteRequest, ...]
    actions: tuple[LytroActionPlan, ...]
    blockers: tuple[LytroTransactionBlocker, ...]
    output_emission_gates: tuple[LytroOutputEmissionGate, ...]
    evidence_ids: tuple[LytroEvidenceId, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    @property
    def metadata_tags(self) -> tuple[LytroMetadataTagPlan, ...]:
        return tuple(tag for segment in self.segments for tag in segment.metadata_tags)

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Lytro metadata transaction output is gated: {gate_codes}")
        return self.source_payload


def build_lytro_metadata_transaction_plan(
    source_payload: bytes,
    *,
    rewrite_requests: tuple[LytroRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> LytroMetadataTransactionPlan:
    blockers: list[LytroTransactionBlocker] = []
    actions: list[LytroActionPlan] = []
    header_validation = _build_header_validation(source_payload, blockers, actions)
    segments: tuple[LytroSegmentPlan, ...] = ()
    if header_validation.is_exiftool_accepted:
        segments = _scan_segments(source_payload, blockers, actions)

    for request in rewrite_requests:
        blocker = LytroTransactionBlocker(
            code="rewrite_requested_requires_lytro_writer",
            reason=(
                "Lytro.pm is a read-only extractor in this slice; requested "
                f"{request.operation} for {request.target} is intentionally gated."
            ),
            byte_range=None,
            evidence_ids=(LYTRO_PROCESS_LFP_SOURCE,),
        )
        blockers.append(blocker)
        actions.append(
            LytroActionPlan(
                kind="block_requested_rewrite",
                target=request.tag_path or request.target,
                byte_range=None,
                reason=blocker.reason,
                evidence_ids=blocker.evidence_ids,
            )
        )

    if not rewrite_requests:
        actions.append(
            LytroActionPlan(
                kind="no_metadata_mutation",
                target="lytro_lfp",
                byte_range=(0, len(source_payload)),
                reason="No rewrite request was supplied; the plan preserves source bytes.",
                evidence_ids=LYTRO_TRANSACTION_SOURCES,
            )
        )

    status: LytroPlanStatus = "unsupported" if _has_structural_blocker(blockers) else "planned"
    gates = _build_output_gates(blockers, allow_output_emission)
    return LytroMetadataTransactionPlan(
        status=status,
        source_payload=source_payload,
        header_validation=header_validation,
        segments=segments,
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        blockers=tuple(blockers),
        output_emission_gates=gates,
        evidence_ids=LYTRO_TRANSACTION_SOURCES,
    )


def _build_header_validation(
    source_payload: bytes,
    blockers: list[LytroTransactionBlocker],
    actions: list[LytroActionPlan],
) -> LytroHeaderValidationPlan:
    signature = source_payload[: min(len(source_payload), LFP_FILE_HEADER_SIZE)]
    reason: LytroBlockerCode | None = None
    if len(source_payload) < LFP_FILE_HEADER_SIZE:
        reason = "truncated_lfp_header"
        blockers.append(
            LytroTransactionBlocker(
                code=reason,
                reason="ProcessLFP requires 16 bytes before accepting a Lytro LFP file.",
                byte_range=(0, len(source_payload)),
                evidence_ids=(LYTRO_PROCESS_LFP_SOURCE,),
            )
        )
    elif not source_payload.startswith(LYTRO_SIGNATURE):
        reason = "invalid_lfp_header"
        blockers.append(
            LytroTransactionBlocker(
                code=reason,
                reason="ProcessLFP accepts only files beginning with the Lytro LFP signature.",
                byte_range=(0, LFP_FILE_HEADER_SIZE),
                evidence_ids=(LYTRO_PROCESS_LFP_SOURCE,),
            )
        )
    actions.append(
        LytroActionPlan(
            kind="validate_lfp_header",
            target="lytro_lfp_header",
            byte_range=(0, min(len(source_payload), LFP_FILE_HEADER_SIZE)),
            reason="Validate the source header using ProcessLFP's LFP signature check.",
            evidence_ids=(LYTRO_PROCESS_LFP_SOURCE,),
        )
    )
    return LytroHeaderValidationPlan(
        signature_range=(0, min(len(source_payload), LFP_FILE_HEADER_SIZE)),
        signature=signature,
        reason=reason,
        evidence_ids=(LYTRO_PROCESS_LFP_SOURCE,),
    )


def _scan_segments(
    source_payload: bytes,
    blockers: list[LytroTransactionBlocker],
    actions: list[LytroActionPlan],
) -> tuple[LytroSegmentPlan, ...]:
    segments: list[LytroSegmentPlan] = []
    offset = LFP_FILE_HEADER_SIZE
    index = 0
    source_size = len(source_payload)
    while offset < source_size:
        header_end = offset + LFP_SEGMENT_HEADER_SIZE
        if header_end > source_size:
            _append_blocker(
                blockers,
                "truncated_lfp_segment_header",
                "A trailing partial LFP segment header cannot be scanned safely.",
                (offset, source_size),
            )
            break
        header = source_payload[offset:header_end]
        if not header.startswith(b"\x89LF"):
            _append_blocker(
                blockers,
                "malformed_lfp_segment_header",
                "ProcessLFP warns on a segment header that does not begin with 0x89 LF.",
                (offset, header_end),
            )
            break
        size = int.from_bytes(header[12:16], "big")
        if size & 0x80000000:
            _append_blocker(
                blockers,
                "invalid_lfp_segment_size",
                "ProcessLFP rejects segment sizes with the high bit set.",
                (offset + 12, offset + 16),
            )
            break
        id_start = header_end
        id_end = id_start + LFP_SEGMENT_ID_SIZE
        if id_end > source_size:
            _append_blocker(
                blockers,
                "truncated_lfp_segment_id",
                "ProcessLFP requires the 80-byte LFP segment identifier before payload routing.",
                (id_start, source_size),
            )
            break
        payload_start = id_end
        payload_end = payload_start + size
        if payload_end > source_size:
            code: LytroBlockerCode = (
                "truncated_lfp_large_payload"
                if size > LFP_MAX_READ_PAYLOAD_SIZE
                else "truncated_lfp_segment_payload"
            )
            _append_blocker(
                blockers,
                code,
                "The LFP segment payload ends beyond the available source bytes.",
                (payload_start, source_size),
            )
            break
        payload = source_payload[payload_start:payload_end]
        pad = 16 - (size % 16)
        padding_start = payload_end
        padding_end = padding_start if pad == 16 else min(padding_start + pad, source_size)
        segment = _build_segment_plan(
            index,
            header,
            source_payload[id_start:id_end],
            payload,
            (offset, header_end),
            (id_start, id_end),
            (payload_start, payload_end),
            (padding_start, padding_end),
            actions,
            blockers,
        )
        segments.append(segment)
        index += 1
        offset = padding_end
    return tuple(segments)


def _build_segment_plan(
    index: int,
    header: bytes,
    identifier_payload: bytes,
    payload: bytes,
    header_range: tuple[int, int],
    id_range: tuple[int, int],
    payload_range: tuple[int, int],
    padding_range: tuple[int, int],
    actions: list[LytroActionPlan],
    blockers: list[LytroTransactionBlocker],
) -> LytroSegmentPlan:
    metadata_tags: tuple[LytroMetadataTagPlan, ...] = ()
    kind: LytroSegmentKind = "unknown_payload_preserve"
    identifier = _identifier_text(identifier_payload)
    if len(payload) > LFP_MAX_READ_PAYLOAD_SIZE:
        kind = "large_payload_preserve"
    elif _is_json_metadata(payload):
        kind = "json_metadata"
        metadata_tags = _extract_json_tags(payload, blockers, actions)
        actions.append(
            LytroActionPlan(
                kind="route_json_metadata",
                target=f"segment:{index}:JSONMetadata",
                byte_range=payload_range,
                reason="ProcessLFP handles JSONMetadata before recursively extracting tags.",
                evidence_ids=(LYTRO_MAIN_TABLE_SOURCE, LYTRO_EXTRACT_TAGS_SOURCE),
            )
        )
    elif payload.startswith(b"\xff\xd8\xff"):
        kind = "embedded_image"
        actions.append(
            LytroActionPlan(
                kind="route_embedded_image",
                target=f"segment:{index}:EmbeddedImage",
                byte_range=payload_range,
                reason="ProcessLFP routes JPEG payloads to EmbeddedImage in the Preview group.",
                evidence_ids=(LYTRO_MAIN_TABLE_SOURCE, LYTRO_PROCESS_LFP_SOURCE),
            )
        )
    actions.append(
        LytroActionPlan(
            kind="scan_lfp_segment",
            target=f"segment:{index}:{identifier}",
            byte_range=(header_range[0], payload_range[1]),
            reason="Record the source segment boundary and preserve its payload bytes.",
            evidence_ids=(LYTRO_PROCESS_LFP_SOURCE,),
        )
    )
    actions.append(
        LytroActionPlan(
            kind="preserve_payload",
            target=f"segment:{index}:{kind}",
            byte_range=payload_range,
            reason="This Lytro slice is non-mutating and preserves segment payload bytes.",
            evidence_ids=(LYTRO_PROCESS_LFP_SOURCE,),
        )
    )
    return LytroSegmentPlan(
        index=index,
        marker=header[:4],
        identifier=identifier,
        size=int.from_bytes(header[12:16], "big"),
        kind=kind,
        header_range=header_range,
        id_range=id_range,
        payload_range=payload_range,
        padding_range=padding_range,
        payload_preserved=True,
        metadata_tags=metadata_tags,
        evidence_ids=(LYTRO_PROCESS_LFP_SOURCE,),
    )


def _extract_json_tags(
    payload: bytes,
    blockers: list[LytroTransactionBlocker],
    actions: list[LytroActionPlan],
) -> tuple[LytroMetadataTagPlan, ...]:
    try:
        decoded = payload.decode("utf-8")
        metadata: JsonValue = json.loads(decoded, parse_float=str)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        blockers.append(
            LytroTransactionBlocker(
                code="malformed_json_metadata",
                reason=f"ReadJSONObject could not parse JSONMetadata: {error}",
                byte_range=None,
                evidence_ids=(LYTRO_PROCESS_LFP_SOURCE, LYTRO_EXTRACT_TAGS_SOURCE),
            )
        )
        return ()
    if not isinstance(metadata, dict):
        blockers.append(
            LytroTransactionBlocker(
                code="invalid_lfp_metadata",
                reason="ExtractTags requires a JSON metadata hash.",
                byte_range=None,
                evidence_ids=(LYTRO_EXTRACT_TAGS_SOURCE,),
            )
        )
        return ()
    tags: list[LytroMetadataTagPlan] = []
    _extract_tags_from_mapping(metadata, "", tags, actions)
    return tuple(tags)


def _extract_tags_from_mapping(
    metadata: dict[str, JsonValue],
    parent: str,
    tags: list[LytroMetadataTagPlan],
    actions: list[LytroActionPlan],
) -> None:
    for key in metadata:
        tag_path = parent + _ucfirst(key)
        value = metadata[key]
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _extract_tags_from_mapping(item, tag_path, tags, actions)
                else:
                    _append_tag_plan(tag_path, item, is_list=True, tags=tags, actions=actions)
        elif isinstance(value, dict):
            _extract_tags_from_mapping(value, tag_path, tags, actions)
        else:
            _append_tag_plan(tag_path, value, is_list=False, tags=tags, actions=actions)


def _append_tag_plan(
    tag_path: str,
    value: JsonValue,
    *,
    is_list: bool,
    tags: list[LytroMetadataTagPlan],
    actions: list[LytroActionPlan],
) -> None:
    known = LYTRO_KNOWN_TAGS.get(tag_path)
    if known is None:
        tag_name, group2 = _dynamic_tag_name_and_group(tag_path)
        responsibility = _dynamic_responsibility(tag_name, group2)
        evidence_ids: tuple[LytroEvidenceId, ...] = (LYTRO_EXTRACT_TAGS_SOURCE,)
        route_kind: LytroMetadataRouteKind = "dynamic_json"
        preserves_unknown = True
        actions.append(
            LytroActionPlan(
                kind="preserve_unknown_tag",
                target=tag_path,
                byte_range=None,
                reason="ExtractTags dynamically adds JSON leaves missing from the Lytro table.",
                evidence_ids=evidence_ids,
            )
        )
    else:
        tag_name = known.tag_name
        group2 = known.group2
        responsibility = known.responsibility
        evidence_ids = known.evidence_ids
        route_kind = "known_table"
        preserves_unknown = False
    converted_value = _converted_value(tag_path, value)
    tags.append(
        LytroMetadataTagPlan(
            raw_path=tag_path,
            tag_name=tag_name,
            value=value,
            converted_value=converted_value,
            print_value=_print_value(tag_path, converted_value),
            group2=group2,
            responsibility=responsibility,
            route_kind=route_kind,
            is_list=is_list,
            preserves_unknown=preserves_unknown,
            evidence_ids=evidence_ids,
        )
    )


def _dynamic_tag_name_and_group(tag_path: str) -> tuple[str, LytroGroup2]:
    name = _sanitize_dynamic_name(tag_path).replace(
        "ParametersVendorContentComLytroTags",
        "",
        1,
    )
    if name.startswith("Devices"):
        return name.removeprefix("Devices"), "Camera"
    return name, "Image"


def _dynamic_responsibility(
    tag_name: str,
    group2: LytroGroup2,
) -> LytroResponsibilityKind:
    if group2 == "Camera":
        return "camera_metadata"
    lowered = tag_name.lower()
    if lowered.startswith("depth"):
        return "depth_metadata"
    if lowered.startswith("focus"):
        return "focus_metadata"
    return "image_metadata"


def _converted_value(tag_path: str, value: JsonValue) -> JsonValue:
    number = _number_value(value)
    if tag_path == "DevicesClockZuluTime" and isinstance(value, str):
        return _convert_xmp_datetime(value)
    if tag_path == "DevicesLensFocalLength" and number is not None:
        return number * 1000
    if tag_path == "DevicesSensorPixelPitch" and number is not None and number != 0:
        return 25.4 / number / 1000
    return value


def _print_value(tag_path: str, value: JsonValue) -> str | None:
    number = _number_value(value)
    if tag_path == "DevicesClockZuluTime" and isinstance(value, str):
        return value
    if tag_path == "DevicesLensFNumber" and number is not None:
        return f"{number:.1f}"
    if tag_path == "DevicesLensFocalLength" and number is not None:
        return f"{number:.1f} mm"
    if tag_path in {"DevicesLensTemperature", "DevicesSocTemperature"} and number is not None:
        return f"{number:.1f} C"
    if (
        tag_path in {"DevicesShutterFrameExposureDuration", "DevicesShutterPixelExposureDuration"}
        and number is not None
    ):
        return _print_exposure_time(number)
    if tag_path in {"ImageLimitExposureBias", "ImageModulationExposureBias"} and number is not None:
        return f"{number:+.1f}"
    if tag_path == "ImageOrientation" and value == 1:
        return "Horizontal (normal)"
    return None


def _convert_xmp_datetime(value: str) -> str:
    match = re.fullmatch(
        r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)(Z|[+-]\d{2}:?\d{2})?",
        value,
    )
    if match is None:
        return value
    year, month, day, clock, zone = match.groups()
    rendered_zone = "" if zone is None else zone
    return f"{year}:{month}:{day} {clock}{rendered_zone}"


def _print_exposure_time(value: float) -> str:
    if value <= 0:
        return str(value)
    reciprocal = round(1 / value)
    if reciprocal > 1 and abs(value - (1 / reciprocal)) < 0.00001:
        return f"1/{reciprocal}"
    if value < 1:
        return f"{value:.3g}"
    return f"{value:.1f}"


def _sanitize_dynamic_name(tag_path: str) -> str:
    def replacement(match: re.Match[str]) -> str:
        next_character = match.group(1)
        return next_character.upper()

    return re.sub(r"[^-_a-zA-Z0-9](.?)", replacement, tag_path)


def _identifier_text(identifier_payload: bytes) -> str:
    prefix = identifier_payload.split(b"\x00", 1)[0]
    return prefix.decode("utf-8", errors="replace")


def _is_json_metadata(payload: bytes) -> bool:
    return re.match(rb'^\{\s+"', payload) is not None


def _number_value(value: JsonValue) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _ucfirst(value: str) -> str:
    if not value:
        return value
    return value[0].upper() + value[1:]


def _append_blocker(
    blockers: list[LytroTransactionBlocker],
    code: LytroBlockerCode,
    reason: str,
    byte_range: tuple[int, int],
) -> None:
    blockers.append(
        LytroTransactionBlocker(
            code=code,
            reason=reason,
            byte_range=byte_range,
            evidence_ids=(LYTRO_PROCESS_LFP_SOURCE,),
        )
    )


def _has_structural_blocker(blockers: list[LytroTransactionBlocker]) -> bool:
    return any(blocker.code != "rewrite_requested_requires_lytro_writer" for blocker in blockers)


def _build_output_gates(
    blockers: list[LytroTransactionBlocker],
    allow_output_emission: bool,
) -> tuple[LytroOutputEmissionGate, ...]:
    gates = [
        LytroOutputEmissionGate(
            code=blocker.code,
            reason=blocker.reason,
            evidence_ids=blocker.evidence_ids,
        )
        for blocker in blockers
    ]
    if not gates and not allow_output_emission:
        gates.append(
            LytroOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="Lytro plans preserve bytes unless output emission is explicitly enabled.",
                evidence_ids=LYTRO_TRANSACTION_SOURCES,
            )
        )
    return tuple(gates)
