"""Source-grounded JPEG digest transaction planning.

The planner preserves the JPEG byte stream and records the ExifTool route used
to calculate JPEGDigest: DQT payloads indexed by table id plus the first usable
SOF component sampling key. APP and COM segments are classified as boundaries
but never included in the digest input.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

JPEG_DIGEST_SOURCE_PATH = "lib/Image/ExifTool/JPEGDigest.pm"
EXIFTOOL_JPEG_SOURCE_PATH = "lib/Image/ExifTool.pm"
JPEG_SEGMENT_TABLE_SOURCE_PATH = "lib/Image/ExifTool/JPEG.pm"

SOF_MARKERS = frozenset(
    {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
)
STANDALONE_MARKERS = frozenset({0x01, *range(0xD0, 0xD8), 0xD8, 0xD9})
EMPTY_DQT_DIGEST = "d41d8cd98f00b204e9800998ecf8427e"

type JpegDigestPlanStatus = Literal["planned", "unsupported"]
type JpegDigestBoundaryClass = Literal[
    "app_segment",
    "comment_segment",
    "quantization_table_segment",
    "start_of_frame_segment",
    "scan_start",
    "image_end",
    "standalone_marker",
    "other_metadata_segment",
]
type JpegDigestRoute = Literal[
    "exclude_app_metadata",
    "exclude_comment_metadata",
    "include_dqt_payload",
    "derive_subsampling_key",
    "stop_before_entropy_scan",
    "stop_at_image_end",
    "exclude_standalone_marker",
    "exclude_other_metadata",
]
type JpegDigestActionKind = Literal[
    "validate_jpeg_signature",
    "classify_app_segment_boundary",
    "classify_comment_segment_boundary",
    "record_dqt_payload",
    "derive_sof_subsampling",
    "preserve_excluded_segment",
    "stop_before_entropy_scan",
    "calculate_jpeg_digest",
    "block_requested_rewrite",
]
type JpegDigestGateCode = Literal[
    "invalid_jpeg_signature",
    "truncated_jpeg_segment_length",
    "invalid_jpeg_segment_length",
    "truncated_jpeg_segment_payload",
    "truncated_jpeg_marker",
    "truncated_start_of_frame",
    "empty_dqt_segment_not_digestable",
    "missing_jpeg_sos",
    "missing_sof_subsampling_for_digest",
    "jpeg_digest_rewrite_not_supported",
    "non_mutating_plan_requires_explicit_emission",
]
type JpegDigestRewriteTarget = Literal[
    "jpeg_digest",
    "jpeg_quality_estimate",
    "dqt_segment",
    "sof_segment",
    "app_segment",
    "comment_segment",
]
type JpegDigestRewriteOperation = Literal["insert", "replace", "delete", "set"]
type JpegDigestKnownDescription = Literal[
    "No DQT defined",
    "Independent JPEG Group library (used by many applications), Quality 75",
    "Adobe Photoshop, Save for web, Quality 10",
]
type JpegQualityEstimateValue = int | Literal["<unknown>"]

JPEG_DIGEST_PRINT_CONV_SOURCE = "jpeg.digest.print.conv"
JPEG_DIGEST_ESTIMATE_SOURCE = "jpeg.digest.estimate"
JPEG_DIGEST_CALCULATE_SOURCE = "jpeg.digest.calculate"
JPEG_SOF_SUBSAMPLING_SOURCE = "jpeg.sof.subsampling"
JPEG_DQT_CAPTURE_SOURCE = "jpeg.dqt.capture"
JPEG_DIGEST_DISPATCH_SOURCE = "jpeg.digest.dispatch"
JPEG_SEGMENT_BOUNDARY_SOURCE = "jpeg.segment.boundary"

KNOWN_DIGEST_DESCRIPTIONS: dict[str, JpegDigestKnownDescription] = {
    EMPTY_DQT_DIGEST: "No DQT defined",
    "2851eea5e15f1b977c1496a77c884b4f": (
        "Independent JPEG Group library (used by many applications), Quality 75"
    ),
    "301158b292e3232856a765486da26fa6:221111": ("Adobe Photoshop, Save for web, Quality 10"),
}


@dataclass(frozen=True)
class JpegDigestRewriteRequest:
    target: JpegDigestRewriteTarget
    operation: JpegDigestRewriteOperation
    payload: bytes | None = None


@dataclass(frozen=True)
class JpegDigestEmissionGate:
    code: JpegDigestGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class JpegDigestAction:
    kind: JpegDigestActionKind
    byte_range: tuple[int, int] | None
    route: JpegDigestRoute | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class JpegDigestSegmentPlan:
    index: int
    marker: int
    marker_name: str
    byte_range: tuple[int, int]
    payload_range: tuple[int, int]
    payload_length: int
    boundary_class: JpegDigestBoundaryClass
    digest_route: JpegDigestRoute
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class JpegDigestDqtPlan:
    segment_index: int
    table_id: int
    payload: bytes
    byte_range: tuple[int, int]
    digest_route: Literal["include_dqt_payload", "exclude_other_metadata"]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class JpegDigestSofPlan:
    segment_index: int
    marker: int
    byte_range: tuple[int, int]
    bits_per_sample: int
    image_height: int
    image_width: int
    color_components: int
    subsampling_key: str | None
    ycbcr_subsampling: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParsedJpegDigestSegments:
    segments: tuple[JpegDigestSegmentPlan, ...]
    dqt_segments: tuple[JpegDigestDqtPlan, ...]
    sof: JpegDigestSofPlan | None
    actions: tuple[JpegDigestAction, ...]
    gates: tuple[JpegDigestEmissionGate, ...]
    found_sos: bool


@dataclass(frozen=True)
class JpegDigestTransactionPlan:
    status: JpegDigestPlanStatus
    source_data: bytes
    segments: tuple[JpegDigestSegmentPlan, ...]
    dqt_segments: tuple[JpegDigestDqtPlan, ...]
    sof: JpegDigestSofPlan | None
    digest_input_payloads: tuple[bytes, ...]
    digest_base_md5: str | None
    jpeg_digest: str | None
    jpeg_quality_estimate: JpegQualityEstimateValue | None
    digest_description: str | None
    actions: tuple[JpegDigestAction, ...]
    output_emission_gates: tuple[JpegDigestEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            code = "unsupported_jpeg_digest_plan"
            if self.output_emission_gates:
                code = self.output_emission_gates[0].code
            raise ValueError(code)
        return self.source_data


def build_jpeg_digest_transaction_plan(
    jpeg_data: bytes,
    rewrite_requests: Sequence[JpegDigestRewriteRequest] = (),
    *,
    allow_output_emission: bool = False,
) -> JpegDigestTransactionPlan:
    parsed = parse_jpeg_digest_segments(jpeg_data)
    gates = list(parsed.gates)
    actions = list(parsed.actions)
    if rewrite_requests:
        gates.append(rewrite_not_supported_gate())
        actions.append(
            JpegDigestAction(
                kind="block_requested_rewrite",
                byte_range=None,
                route=None,
                evidence_ids=(JPEG_DIGEST_CALCULATE_SOURCE,),
            )
        )
    digest_input_payloads = ordered_digest_payloads(parsed.dqt_segments)
    digest_base_md5, digest_value, description = digest_values(digest_input_payloads, parsed.sof)
    quality_estimate = jpeg_quality_estimate(parsed.dqt_segments)
    if digest_input_payloads and parsed.sof is not None and parsed.sof.subsampling_key is None:
        gates.append(
            JpegDigestEmissionGate(
                code="missing_sof_subsampling_for_digest",
                reason="JPEGDigest.pm requires a SOF subsampling key before emitting JPEGDigest.",
                evidence_ids=(JPEG_DIGEST_CALCULATE_SOURCE, JPEG_SOF_SUBSAMPLING_SOURCE),
            )
        )
    if not allow_output_emission:
        gates.append(non_mutating_gate())
    if digest_value is not None:
        actions.append(
            JpegDigestAction(
                kind="calculate_jpeg_digest",
                byte_range=None,
                route="include_dqt_payload",
                evidence_ids=(JPEG_DIGEST_CALCULATE_SOURCE,),
            )
        )
    status: JpegDigestPlanStatus = "planned"
    if parsed.gates:
        status = "unsupported"
    return JpegDigestTransactionPlan(
        status=status,
        source_data=jpeg_data,
        segments=parsed.segments,
        dqt_segments=parsed.dqt_segments,
        sof=parsed.sof,
        digest_input_payloads=digest_input_payloads,
        digest_base_md5=digest_base_md5,
        jpeg_digest=digest_value,
        jpeg_quality_estimate=quality_estimate,
        digest_description=description,
        actions=tuple(actions),
        output_emission_gates=tuple(gates),
        evidence_ids=source_refs(
            (
                JPEG_DIGEST_PRINT_CONV_SOURCE,
                JPEG_DIGEST_ESTIMATE_SOURCE,
                JPEG_DIGEST_CALCULATE_SOURCE,
                JPEG_SOF_SUBSAMPLING_SOURCE,
                JPEG_DQT_CAPTURE_SOURCE,
                JPEG_DIGEST_DISPATCH_SOURCE,
                JPEG_SEGMENT_BOUNDARY_SOURCE,
            )
        ),
    )


def parse_jpeg_digest_segments(jpeg_data: bytes) -> ParsedJpegDigestSegments:
    actions: list[JpegDigestAction] = [
        JpegDigestAction(
            kind="validate_jpeg_signature",
            byte_range=(0, min(2, len(jpeg_data))),
            route=None,
            evidence_ids=(JPEG_SEGMENT_BOUNDARY_SOURCE,),
        )
    ]
    if not jpeg_data.startswith(b"\xff\xd8"):
        return parsed_with_gate(
            jpeg_data,
            actions,
            "invalid_jpeg_signature",
            "JPEG parsing requires the SOI marker ff d8.",
        )

    segments: list[JpegDigestSegmentPlan] = []
    dqt_by_id: dict[int, JpegDigestDqtPlan] = {}
    sof: JpegDigestSofPlan | None = None
    gates: list[JpegDigestEmissionGate] = []
    offset = 2
    found_sos = False
    while offset < len(jpeg_data):
        marker_offset = find_next_marker(jpeg_data, offset)
        if marker_offset is None:
            break
        if marker_offset + 1 >= len(jpeg_data):
            gates.append(
                gate(
                    "truncated_jpeg_marker",
                    "A JPEG marker prefix was present without a marker byte.",
                    (JPEG_SEGMENT_BOUNDARY_SOURCE,),
                )
            )
            break
        marker = jpeg_data[marker_offset + 1]
        offset = marker_offset + 2
        if marker in STANDALONE_MARKERS:
            segment = standalone_segment(len(segments), marker, marker_offset, offset)
            segments.append(segment)
            actions.append(preserve_action(segment))
            if marker == 0xD9:
                break
            continue
        if offset + 2 > len(jpeg_data):
            gates.append(
                gate(
                    "truncated_jpeg_segment_length",
                    "The JPEG marker is missing its two-byte segment length.",
                    (JPEG_SEGMENT_BOUNDARY_SOURCE,),
                )
            )
            break
        segment_length = int.from_bytes(jpeg_data[offset : offset + 2], "big")
        if segment_length < 2:
            gates.append(
                gate(
                    "invalid_jpeg_segment_length",
                    "JPEG segment lengths include the length word and must be at least two.",
                    (JPEG_SEGMENT_BOUNDARY_SOURCE,),
                )
            )
            break
        payload_offset = offset + 2
        payload_length = segment_length - 2
        segment_end = payload_offset + payload_length
        if segment_end > len(jpeg_data):
            gates.append(
                gate(
                    "truncated_jpeg_segment_payload",
                    "The declared JPEG segment payload extends past the byte stream.",
                    (JPEG_SEGMENT_BOUNDARY_SOURCE,),
                )
            )
            break
        segment = classified_segment(
            len(segments),
            marker,
            marker_offset,
            payload_offset,
            payload_length,
            segment_end,
        )
        segments.append(segment)
        actions.extend(actions_for_segment(segment))
        payload = jpeg_data[payload_offset:segment_end]
        if marker == 0xDA:
            found_sos = True
            break
        if marker == 0xDB:
            if payload:
                table_id = payload[0] & 0x0F
                dqt_plan = JpegDigestDqtPlan(
                    segment_index=segment.index,
                    table_id=table_id,
                    payload=payload,
                    byte_range=segment.byte_range,
                    digest_route=(
                        "include_dqt_payload" if table_id < 4 else "exclude_other_metadata"
                    ),
                    evidence_ids=(JPEG_DQT_CAPTURE_SOURCE, JPEG_DIGEST_CALCULATE_SOURCE),
                )
                if table_id < 4:
                    dqt_by_id[table_id] = dqt_plan
            else:
                gates.append(
                    gate(
                        "empty_dqt_segment_not_digestable",
                        "ProcessJPEG only saves DQT data when the DQT payload is non-empty.",
                        (JPEG_DQT_CAPTURE_SOURCE,),
                    )
                )
        if marker in SOF_MARKERS and sof is None:
            if payload_length < 6:
                gates.append(
                    gate(
                        "truncated_start_of_frame",
                        (
                            "ProcessJPEG ignores SOF sizing and subsampling when the "
                            "payload is under six bytes."
                        ),
                        (JPEG_SOF_SUBSAMPLING_SOURCE,),
                    )
                )
            else:
                sof = sof_plan(segment, payload)
        offset = segment_end
    if not found_sos and not gates:
        gates.append(
            gate(
                "missing_jpeg_sos",
                "ProcessJPEG warns when EOI is reached without a JPEG SOS marker.",
                (JPEG_SEGMENT_BOUNDARY_SOURCE,),
            )
        )
    dqt_segments = tuple(dqt_by_id[index] for index in sorted(dqt_by_id))
    return ParsedJpegDigestSegments(
        segments=tuple(segments),
        dqt_segments=dqt_segments,
        sof=sof,
        actions=tuple(actions),
        gates=tuple(gates),
        found_sos=found_sos,
    )


def digest_values(
    digest_payloads: tuple[bytes, ...],
    sof: JpegDigestSofPlan | None,
) -> tuple[str | None, str | None, str | None]:
    if not digest_payloads:
        return EMPTY_DQT_DIGEST, EMPTY_DQT_DIGEST, jpeg_digest_description(EMPTY_DQT_DIGEST)
    base = hashlib.md5(b"\x00".join(digest_payloads)).hexdigest()
    description = jpeg_digest_description(base)
    if description is not None:
        return base, base, description
    if sof is None or sof.subsampling_key is None:
        return base, None, None
    digest = f"{base}:{sof.subsampling_key}"
    return base, digest, jpeg_digest_description(digest)


def jpeg_digest_description(digest: str) -> str | None:
    return KNOWN_DIGEST_DESCRIPTIONS.get(digest)


def ordered_digest_payloads(dqt_segments: tuple[JpegDigestDqtPlan, ...]) -> tuple[bytes, ...]:
    return tuple(
        segment.payload for segment in dqt_segments if segment.digest_route == "include_dqt_payload"
    )


def jpeg_quality_estimate(
    dqt_segments: tuple[JpegDigestDqtPlan, ...],
) -> JpegQualityEstimateValue | None:
    qtbls = jpeg_quality_quantization_tables(dqt_segments)
    if not qtbls:
        return None
    quantization_sum = sum(sum(table) for table in qtbls)
    qval = qtbls[0][2] + qtbls[0][53]
    if len(qtbls) > 1:
        qval += qtbls[1][0] + qtbls[1][63]
        hash_thresholds = (
            1020,
            1015,
            932,
            848,
            780,
            735,
            702,
            679,
            660,
            645,
            632,
            623,
            613,
            607,
            600,
            594,
            589,
            585,
            581,
            571,
            555,
            542,
            529,
            514,
            494,
            474,
            457,
            439,
            424,
            410,
            397,
            386,
            373,
            364,
            351,
            341,
            334,
            324,
            317,
            309,
            299,
            294,
            287,
            279,
            274,
            267,
            262,
            257,
            251,
            247,
            243,
            237,
            232,
            227,
            222,
            217,
            213,
            207,
            202,
            198,
            192,
            188,
            183,
            177,
            173,
            168,
            163,
            157,
            153,
            148,
            143,
            139,
            132,
            128,
            125,
            119,
            115,
            108,
            104,
            99,
            94,
            90,
            84,
            79,
            74,
            70,
            64,
            59,
            55,
            49,
            45,
            40,
            34,
            30,
            25,
            20,
            15,
            11,
            6,
            4,
        )
        sum_thresholds = (
            32640,
            32635,
            32266,
            31495,
            30665,
            29804,
            29146,
            28599,
            28104,
            27670,
            27225,
            26725,
            26210,
            25716,
            25240,
            24789,
            24373,
            23946,
            23572,
            22846,
            21801,
            20842,
            19949,
            19121,
            18386,
            17651,
            16998,
            16349,
            15800,
            15247,
            14783,
            14321,
            13859,
            13535,
            13081,
            12702,
            12423,
            12056,
            11779,
            11513,
            11135,
            10955,
            10676,
            10392,
            10208,
            9928,
            9747,
            9564,
            9369,
            9193,
            9017,
            8822,
            8639,
            8458,
            8270,
            8084,
            7896,
            7710,
            7527,
            7347,
            7156,
            6977,
            6788,
            6607,
            6422,
            6236,
            6054,
            5867,
            5684,
            5495,
            5305,
            5128,
            4945,
            4751,
            4638,
            4442,
            4248,
            4065,
            3888,
            3698,
            3509,
            3326,
            3139,
            2957,
            2775,
            2586,
            2405,
            2216,
            2037,
            1846,
            1666,
            1483,
            1297,
            1109,
            927,
            735,
            554,
            375,
            201,
            128,
        )
    else:
        hash_thresholds = (
            510,
            505,
            422,
            380,
            355,
            338,
            326,
            318,
            311,
            305,
            300,
            297,
            293,
            291,
            288,
            286,
            284,
            283,
            281,
            280,
            279,
            278,
            277,
            273,
            262,
            251,
            243,
            233,
            225,
            218,
            211,
            205,
            198,
            193,
            186,
            181,
            177,
            172,
            168,
            164,
            158,
            156,
            152,
            148,
            145,
            142,
            139,
            136,
            133,
            131,
            129,
            126,
            123,
            120,
            118,
            115,
            113,
            110,
            107,
            105,
            102,
            100,
            97,
            94,
            92,
            89,
            87,
            83,
            81,
            79,
            76,
            74,
            70,
            68,
            66,
            63,
            61,
            57,
            55,
            52,
            50,
            48,
            44,
            42,
            39,
            37,
            34,
            31,
            29,
            26,
            24,
            21,
            18,
            16,
            13,
            11,
            8,
            6,
            3,
            2,
        )
        sum_thresholds = (
            16320,
            16315,
            15946,
            15277,
            14655,
            14073,
            13623,
            13230,
            12859,
            12560,
            12240,
            11861,
            11456,
            11081,
            10714,
            10360,
            10027,
            9679,
            9368,
            9056,
            8680,
            8331,
            7995,
            7668,
            7376,
            7084,
            6823,
            6562,
            6345,
            6125,
            5939,
            5756,
            5571,
            5421,
            5240,
            5086,
            4976,
            4829,
            4719,
            4616,
            4463,
            4393,
            4280,
            4166,
            4092,
            3980,
            3909,
            3835,
            3755,
            3688,
            3621,
            3541,
            3467,
            3396,
            3323,
            3247,
            3170,
            3096,
            3021,
            2952,
            2874,
            2804,
            2727,
            2657,
            2583,
            2509,
            2437,
            2362,
            2290,
            2211,
            2136,
            2068,
            1996,
            1915,
            1858,
            1773,
            1692,
            1620,
            1552,
            1477,
            1398,
            1326,
            1251,
            1179,
            1109,
            1031,
            961,
            884,
            814,
            736,
            667,
            592,
            518,
            441,
            369,
            292,
            221,
            151,
            86,
            64,
        )
    for index, hash_threshold in enumerate(hash_thresholds):
        sum_threshold = sum_thresholds[index]
        if qval < hash_threshold and quantization_sum < sum_threshold:
            continue
        if (qval <= hash_threshold and quantization_sum <= sum_threshold) or index >= 50:
            return index + 1
        break
    return "<unknown>"


def jpeg_quality_quantization_tables(
    dqt_segments: tuple[JpegDigestDqtPlan, ...],
) -> tuple[tuple[int, ...], ...]:
    tables: list[tuple[int, ...]] = []
    for segment in dqt_segments:
        payload = segment.payload
        offset = 1
        while offset + 64 <= len(payload):
            tables.append(tuple(payload[offset : offset + 64]))
            if len(tables) >= 4:
                return tuple(tables)
            offset += 65
    return tuple(tables)


def classified_segment(
    index: int,
    marker: int,
    marker_offset: int,
    payload_offset: int,
    payload_length: int,
    segment_end: int,
) -> JpegDigestSegmentPlan:
    boundary_class, route = classify_marker(marker)
    return JpegDigestSegmentPlan(
        index=index,
        marker=marker,
        marker_name=marker_name(marker),
        byte_range=(marker_offset, segment_end),
        payload_range=(payload_offset, segment_end),
        payload_length=payload_length,
        boundary_class=boundary_class,
        digest_route=route,
        evidence_ids=evidence_ids_for_marker(marker),
    )


def standalone_segment(
    index: int,
    marker: int,
    marker_offset: int,
    marker_end: int,
) -> JpegDigestSegmentPlan:
    boundary_class: JpegDigestBoundaryClass = "standalone_marker"
    route: JpegDigestRoute = "exclude_standalone_marker"
    if marker == 0xD9:
        boundary_class = "image_end"
        route = "stop_at_image_end"
    return JpegDigestSegmentPlan(
        index=index,
        marker=marker,
        marker_name=marker_name(marker),
        byte_range=(marker_offset, marker_end),
        payload_range=(marker_end, marker_end),
        payload_length=0,
        boundary_class=boundary_class,
        digest_route=route,
        evidence_ids=(JPEG_SEGMENT_BOUNDARY_SOURCE,),
    )


def classify_marker(marker: int) -> tuple[JpegDigestBoundaryClass, JpegDigestRoute]:
    if 0xE0 <= marker <= 0xEF:
        return "app_segment", "exclude_app_metadata"
    if marker == 0xFE:
        return "comment_segment", "exclude_comment_metadata"
    if marker == 0xDB:
        return "quantization_table_segment", "include_dqt_payload"
    if marker in SOF_MARKERS:
        return "start_of_frame_segment", "derive_subsampling_key"
    if marker == 0xDA:
        return "scan_start", "stop_before_entropy_scan"
    return "other_metadata_segment", "exclude_other_metadata"


def evidence_ids_for_marker(marker: int) -> tuple[str, ...]:
    if marker == 0xDB:
        return (JPEG_DQT_CAPTURE_SOURCE, JPEG_DIGEST_CALCULATE_SOURCE, JPEG_SEGMENT_BOUNDARY_SOURCE)
    if marker in SOF_MARKERS:
        return (JPEG_SOF_SUBSAMPLING_SOURCE, JPEG_SEGMENT_BOUNDARY_SOURCE)
    return (JPEG_SEGMENT_BOUNDARY_SOURCE,)


def actions_for_segment(segment: JpegDigestSegmentPlan) -> tuple[JpegDigestAction, ...]:
    if segment.digest_route == "exclude_app_metadata":
        return (
            JpegDigestAction(
                kind="classify_app_segment_boundary",
                byte_range=segment.byte_range,
                route=segment.digest_route,
                evidence_ids=segment.evidence_ids,
            ),
            preserve_action(segment),
        )
    if segment.digest_route == "exclude_comment_metadata":
        return (
            JpegDigestAction(
                kind="classify_comment_segment_boundary",
                byte_range=segment.byte_range,
                route=segment.digest_route,
                evidence_ids=segment.evidence_ids,
            ),
            preserve_action(segment),
        )
    if segment.digest_route == "include_dqt_payload":
        return (
            JpegDigestAction(
                kind="record_dqt_payload",
                byte_range=segment.byte_range,
                route=segment.digest_route,
                evidence_ids=segment.evidence_ids,
            ),
        )
    if segment.digest_route == "derive_subsampling_key":
        return (
            JpegDigestAction(
                kind="derive_sof_subsampling",
                byte_range=segment.byte_range,
                route=segment.digest_route,
                evidence_ids=segment.evidence_ids,
            ),
        )
    if segment.digest_route == "stop_before_entropy_scan":
        return (
            JpegDigestAction(
                kind="stop_before_entropy_scan",
                byte_range=segment.byte_range,
                route=segment.digest_route,
                evidence_ids=segment.evidence_ids,
            ),
        )
    return (preserve_action(segment),)


def preserve_action(segment: JpegDigestSegmentPlan) -> JpegDigestAction:
    return JpegDigestAction(
        kind="preserve_excluded_segment",
        byte_range=segment.byte_range,
        route=segment.digest_route,
        evidence_ids=segment.evidence_ids,
    )


def sof_plan(segment: JpegDigestSegmentPlan, payload: bytes) -> JpegDigestSofPlan:
    bits_per_sample = payload[0]
    image_height = int.from_bytes(payload[1:3], "big")
    image_width = int.from_bytes(payload[3:5], "big")
    color_components = payload[5]
    subsampling_key: str | None = None
    ycbcr_subsampling: str | None = None
    if color_components == 3 and len(payload) >= 15:
        sampling_bytes = (payload[7], payload[10], payload[13])
        subsampling_key = "".join(f"{sampling_byte:02x}" for sampling_byte in sampling_bytes)
        ycbcr_subsampling = ycbcr_sampling_text(sampling_bytes)
    return JpegDigestSofPlan(
        segment_index=segment.index,
        marker=segment.marker,
        byte_range=segment.byte_range,
        bits_per_sample=bits_per_sample,
        image_height=image_height,
        image_width=image_width,
        color_components=color_components,
        subsampling_key=subsampling_key,
        ycbcr_subsampling=ycbcr_subsampling,
        evidence_ids=(JPEG_SOF_SUBSAMPLING_SOURCE,),
    )


def ycbcr_sampling_text(sampling_bytes: tuple[int, int, int]) -> str | None:
    horizontal = tuple(sampling_byte >> 4 for sampling_byte in sampling_bytes)
    vertical = tuple(sampling_byte & 0x0F for sampling_byte in sampling_bytes)
    h_min = min(horizontal)
    v_min = min(vertical)
    if h_min == 0 or v_min == 0:
        return None
    return f"{max(horizontal) // h_min} {max(vertical) // v_min}"


def find_next_marker(data: bytes, offset: int) -> int | None:
    cursor = offset
    while cursor + 1 < len(data):
        if data[cursor] != 0xFF:
            cursor += 1
            continue
        while cursor + 1 < len(data) and data[cursor + 1] == 0xFF:
            cursor += 1
        if cursor + 1 >= len(data):
            return None
        if data[cursor + 1] == 0x00:
            cursor += 2
            continue
        return cursor
    return None


def marker_name(marker: int) -> str:
    if marker == 0xD8:
        return "SOI"
    if marker == 0xD9:
        return "EOI"
    if marker == 0xDA:
        return "SOS"
    if marker == 0xDB:
        return "DQT"
    if marker == 0xFE:
        return "COM"
    if 0xE0 <= marker <= 0xEF:
        return f"APP{marker - 0xE0}"
    if marker in SOF_MARKERS:
        return f"SOF{marker - 0xC0}"
    return f"0xFF{marker:02X}"


def parsed_with_gate(
    jpeg_data: bytes,
    actions: list[JpegDigestAction],
    code: JpegDigestGateCode,
    reason: str,
) -> ParsedJpegDigestSegments:
    return ParsedJpegDigestSegments(
        segments=(),
        dqt_segments=(),
        sof=None,
        actions=tuple(actions),
        gates=(gate(code, reason, (JPEG_SEGMENT_BOUNDARY_SOURCE,)),),
        found_sos=False,
    )


def gate(
    code: JpegDigestGateCode,
    reason: str,
    evidence_ids: tuple[str, ...],
) -> JpegDigestEmissionGate:
    return JpegDigestEmissionGate(
        code=code,
        reason=reason,
        evidence_ids=evidence_ids,
    )


def rewrite_not_supported_gate() -> JpegDigestEmissionGate:
    return JpegDigestEmissionGate(
        code="jpeg_digest_rewrite_not_supported",
        reason="JPEGDigest.pm calculates Extra tags and does not define a JPEG digest writer.",
        evidence_ids=(JPEG_DIGEST_CALCULATE_SOURCE,),
    )


def non_mutating_gate() -> JpegDigestEmissionGate:
    return JpegDigestEmissionGate(
        code="non_mutating_plan_requires_explicit_emission",
        reason="The default JPEG digest transaction plan is preserve-only.",
        evidence_ids=(JPEG_DIGEST_CALCULATE_SOURCE,),
    )


def source_refs(references: tuple[str, ...]) -> tuple[str, ...]:
    deduped: list[str] = []
    for reference in references:
        if reference not in deduped:
            deduped.append(reference)
    return tuple(deduped)
