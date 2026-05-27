"""Capture One EIP/COS metadata transaction planning.

The planner mirrors the read responsibilities in
``/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/CaptureOne.pm``.  It does
not rewrite bytes by default; it records how COS sidecars, EIP manifests,
embedded image payloads, and opaque archive members must be preserved or routed.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import Literal
from xml.etree.ElementTree import Element, ParseError, fromstring

from exifmodern.formats.zip import ZipArchiveTransactionPlan, build_zip_archive_transaction_plan

CAPTURE_ONE_SOURCE_PATH = "lib/Image/ExifTool/CaptureOne.pm"
CAPTURE_ONE_IMAGE_EXTENSIONS = frozenset((".iiq", ".jpg", ".jpeg", ".tif", ".tiff"))
CAPTURE_ONE_ROUTED_EXTENSIONS = CAPTURE_ONE_IMAGE_EXTENSIONS | frozenset((".cos",))
CAPTURE_ONE_MAX_DELEGATE_PAYLOAD_BYTES = 8 * 1024 * 1024


def _zip_evidence_ids(evidence_ids: tuple[str, ...]) -> tuple[str, ...]:
    return evidence_ids


type CaptureOnePlanStatus = Literal["planned", "blocked", "unsupported"]
type CaptureOneInputKind = Literal["cos", "eip", "unknown"]
type CaptureOneMemberBoundary = Literal[
    "manifest",
    "settings_sidecar",
    "embedded_image_payload",
    "preview_or_payload",
    "opaque_payload",
]
type CaptureOneRouteAction = Literal[
    "parse_manifest",
    "parse_cos_settings",
    "delegate_embedded_image_metadata",
    "preserve_preview_or_payload",
    "preserve_opaque_payload",
]
type CaptureOneRoutingMode = Literal["standalone_cos", "manifest", "fallback", "unrouted"]
type CaptureOneTagAction = Literal["preserve_source_tag", "preserve_dynamic_tag"]
type CaptureOneGroup2 = Literal["Image", "Time"]
type CaptureOneGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "unrecognized_capture_one_input",
    "malformed_cos_xml",
    "zip_container_blocker",
    "member_payload_unavailable",
    "cos_tag_rewrite_not_source_backed",
    "eip_member_rewrite_not_source_backed",
]

CAPTURE_ONE_TABLE_SOURCE = "capture.one.table"
CAPTURE_ONE_ATTR_SOURCE = "capture.one.attr"
CAPTURE_ONE_FOUND_SOURCE = "capture.one.found"
CAPTURE_ONE_PROCESS_COS_SOURCE = "capture.one.process.cos"
CAPTURE_ONE_EIP_MANIFEST_SOURCE = "capture.one.eip.manifest"
CAPTURE_ONE_EIP_MEMBER_SOURCE = "capture.one.eip.member"
CAPTURE_ONE_EIP_FALLBACK_SOURCE = "capture.one.eip.fallback"
CAPTURE_ONE_EIP_COS_SOURCE = "capture.one.eip.cos"
CAPTURE_ONE_EIP_IMAGE_SOURCE = "capture.one.eip.image"
CAPTURE_ONE_READ_ONLY_SOURCE = "capture.one.read.only"

CAPTURE_ONE_TRANSACTION_SOURCES = (
    CAPTURE_ONE_TABLE_SOURCE,
    CAPTURE_ONE_ATTR_SOURCE,
    CAPTURE_ONE_FOUND_SOURCE,
    CAPTURE_ONE_PROCESS_COS_SOURCE,
    CAPTURE_ONE_EIP_MANIFEST_SOURCE,
    CAPTURE_ONE_EIP_MEMBER_SOURCE,
    CAPTURE_ONE_EIP_FALLBACK_SOURCE,
    CAPTURE_ONE_EIP_COS_SOURCE,
    CAPTURE_ONE_EIP_IMAGE_SOURCE,
    CAPTURE_ONE_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class CaptureOneCosTagRewrite:
    tag_name: str
    value: str


@dataclass(frozen=True)
class CaptureOneEipMemberRewrite:
    file_name: str
    payload: bytes


@dataclass(frozen=True)
class CaptureOneRewriteRequest:
    cos_tags: tuple[CaptureOneCosTagRewrite, ...] = ()
    eip_members: tuple[CaptureOneEipMemberRewrite, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(self.cos_tags or self.eip_members)


@dataclass(frozen=True)
class CaptureOneEmissionGate:
    code: CaptureOneGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class CaptureOneCosTagPlan:
    tag_name: str
    value: str
    xml_path: str
    group_0: Literal["XML"]
    group_1: Literal["XML"]
    group_2: CaptureOneGroup2
    action: CaptureOneTagAction
    is_source_declared: bool
    hidden: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class CaptureOneCosPlan:
    source_name: str | None
    payload_length: int
    tags: tuple[CaptureOneCosTagPlan, ...]
    gates: tuple[CaptureOneEmissionGate, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class CaptureOneManifestPlan:
    selected_member: str | None
    candidate_members: tuple[str, ...]
    raw_paths: tuple[str, ...]
    settings_paths: tuple[str, ...]
    routed_paths: tuple[str, ...]
    found_image: bool
    routing_mode: CaptureOneRoutingMode
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class CaptureOneMemberRoutePlan:
    file_name: str
    document_number: int
    boundary: CaptureOneMemberBoundary
    action: CaptureOneRouteAction
    routed: bool
    payload_length: int | None
    cos_plan: CaptureOneCosPlan | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class CaptureOneMetadataTransactionPlan:
    status: CaptureOnePlanStatus
    input_kind: CaptureOneInputKind
    routing_mode: CaptureOneRoutingMode
    original_bytes: bytes
    cos_plan: CaptureOneCosPlan | None
    manifest: CaptureOneManifestPlan | None
    member_routes: tuple[CaptureOneMemberRoutePlan, ...]
    output_emission_gates: tuple[CaptureOneEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Capture One transaction output is gated: {gate_codes}")
        return self.original_bytes


def build_capture_one_metadata_transaction_plan(
    source_bytes: bytes,
    *,
    source_name: str | None = None,
    rewrite_request: CaptureOneRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> CaptureOneMetadataTransactionPlan:
    gates: list[CaptureOneEmissionGate] = []
    gates.extend(_rewrite_gates(rewrite_request))

    input_kind = _detect_input_kind(source_bytes, source_name)
    if input_kind == "cos":
        cos_plan = _build_cos_plan(source_bytes, source_name)
        gates.extend(cos_plan.gates)
        if not allow_output_emission:
            gates.append(_non_mutating_gate())
        status = _status_from_gates(gates)
        return CaptureOneMetadataTransactionPlan(
            status=status,
            input_kind="cos",
            routing_mode="standalone_cos",
            original_bytes=source_bytes,
            cos_plan=cos_plan,
            manifest=None,
            member_routes=(),
            output_emission_gates=_unique_gates(tuple(gates)),
            evidence_ids=_unique_evidence_ids(
                (
                    *cos_plan.evidence_ids,
                    *(evidence_id for gate in gates for evidence_id in gate.evidence_ids),
                )
            ),
        )

    if input_kind == "eip":
        return _build_eip_plan(
            source_bytes,
            gates=tuple(gates),
            allow_output_emission=allow_output_emission,
        )

    gates.append(
        CaptureOneEmissionGate(
            "unrecognized_capture_one_input",
            "Input is neither a COS XML sidecar nor an EIP ZIP package.",
            (CAPTURE_ONE_PROCESS_COS_SOURCE, CAPTURE_ONE_EIP_MANIFEST_SOURCE),
        )
    )
    if not allow_output_emission:
        gates.append(_non_mutating_gate())
    return CaptureOneMetadataTransactionPlan(
        status="unsupported",
        input_kind="unknown",
        routing_mode="unrouted",
        original_bytes=source_bytes,
        cos_plan=None,
        manifest=None,
        member_routes=(),
        output_emission_gates=_unique_gates(tuple(gates)),
        evidence_ids=_unique_evidence_ids(
            (
                *CAPTURE_ONE_TRANSACTION_SOURCES,
                *(evidence_id for gate in gates for evidence_id in gate.evidence_ids),
            )
        ),
    )


plan_capture_one_metadata_transaction = build_capture_one_metadata_transaction_plan


def _build_eip_plan(
    source_bytes: bytes,
    *,
    gates: tuple[CaptureOneEmissionGate, ...],
    allow_output_emission: bool,
) -> CaptureOneMetadataTransactionPlan:
    mutable_gates = list(gates)
    zip_plan = build_zip_archive_transaction_plan(
        source_bytes,
        allow_output_emission=True,
    )
    zip_gates = _capture_one_zip_gates(zip_plan)
    mutable_gates.extend(zip_gates)
    if zip_gates:
        if not allow_output_emission:
            mutable_gates.append(_non_mutating_gate())
        return CaptureOneMetadataTransactionPlan(
            status="blocked",
            input_kind="eip",
            routing_mode="unrouted",
            original_bytes=source_bytes,
            cos_plan=None,
            manifest=None,
            member_routes=(),
            output_emission_gates=_unique_gates(tuple(mutable_gates)),
            evidence_ids=_unique_evidence_ids(
                (
                    *CAPTURE_ONE_TRANSACTION_SOURCES,
                    *(evidence_id for gate in mutable_gates for evidence_id in gate.evidence_ids),
                    *_zip_evidence_ids(zip_plan.evidence_ids),
                )
            ),
        )

    archive = zipfile.ZipFile(BytesIO(source_bytes))
    manifest = _build_manifest_plan(archive.namelist(), archive)
    routes, route_gates = _build_member_routes(archive, manifest)
    mutable_gates.extend(route_gates)
    if not allow_output_emission:
        mutable_gates.append(_non_mutating_gate())

    return CaptureOneMetadataTransactionPlan(
        status=_status_from_gates(mutable_gates),
        input_kind="eip",
        routing_mode=manifest.routing_mode,
        original_bytes=source_bytes,
        cos_plan=None,
        manifest=manifest,
        member_routes=routes,
        output_emission_gates=_unique_gates(tuple(mutable_gates)),
        evidence_ids=_unique_evidence_ids(
            (
                *CAPTURE_ONE_TRANSACTION_SOURCES,
                *manifest.evidence_ids,
                *(evidence_id for route in routes for evidence_id in route.evidence_ids),
                *(
                    evidence_id
                    for route in routes
                    if route.cos_plan
                    for evidence_id in route.cos_plan.evidence_ids
                ),
                *(evidence_id for gate in mutable_gates for evidence_id in gate.evidence_ids),
                *_zip_evidence_ids(zip_plan.evidence_ids),
            )
        ),
    )


def _build_manifest_plan(
    names: list[str],
    archive: zipfile.ZipFile,
) -> CaptureOneManifestPlan:
    candidates = tuple(sorted(name for name in names if re.fullmatch(r"manifest\d*\.xml", name)))
    selected = candidates[-1] if candidates else None
    raw_paths: tuple[str, ...] = ()
    settings_paths: tuple[str, ...] = ()
    routed_paths: tuple[str, ...] = ()
    found_image = False
    routing_mode: CaptureOneRoutingMode = "fallback"

    if selected is not None:
        try:
            manifest_text = archive.read(selected).decode("utf-8", errors="replace")
        except KeyError, RuntimeError, NotImplementedError, zipfile.BadZipFile:
            manifest_text = ""
        raw_list: list[str] = []
        settings_list: list[str] = []
        routed_list: list[str] = []
        for match in re.finditer(r"<(RawPath|SettingsPath)>(.*?)</\1>", manifest_text, re.DOTALL):
            path = match.group(2)
            if _lower_suffix(path) not in CAPTURE_ONE_ROUTED_EXTENSIONS:
                continue
            routed_list.append(path)
            if match.group(1) == "RawPath":
                raw_list.append(path)
            else:
                settings_list.append(path)
            if _lower_suffix(path) != ".cos":
                found_image = True
        raw_paths = tuple(raw_list)
        settings_paths = tuple(settings_list)
        routed_paths = tuple(dict.fromkeys(routed_list))
        if found_image:
            routing_mode = "manifest"

    return CaptureOneManifestPlan(
        selected_member=selected,
        candidate_members=candidates,
        raw_paths=raw_paths,
        settings_paths=settings_paths,
        routed_paths=routed_paths if found_image else (),
        found_image=found_image,
        routing_mode=routing_mode,
        evidence_ids=(CAPTURE_ONE_EIP_MANIFEST_SOURCE,),
    )


def _build_member_routes(
    archive: zipfile.ZipFile,
    manifest: CaptureOneManifestPlan,
) -> tuple[tuple[CaptureOneMemberRoutePlan, ...], tuple[CaptureOneEmissionGate, ...]]:
    routes: list[CaptureOneMemberRoutePlan] = []
    gates: list[CaptureOneEmissionGate] = []
    routed_paths = frozenset(manifest.routed_paths)
    for index, info in enumerate(archive.infolist(), start=1):
        name = info.filename
        routed = _is_routed_member(name, routed_paths, manifest.routing_mode)
        boundary = _member_boundary(name, routed)
        action = _route_action(boundary, routed)
        payload_length: int | None = info.file_size
        cos_plan: CaptureOneCosPlan | None = None
        route_evidence_ids = _route_evidence_ids(boundary, routed, manifest.routing_mode)
        if routed and _lower_suffix(name) == ".cos":
            payload, payload_gate = _read_member_payload(archive, name)
            if payload_gate is not None:
                gates.append(payload_gate)
                payload_length = None
            else:
                cos_plan = _build_cos_plan(payload, name)
                gates.extend(cos_plan.gates)
        routes.append(
            CaptureOneMemberRoutePlan(
                file_name=name,
                document_number=index,
                boundary=boundary,
                action=action,
                routed=routed,
                payload_length=payload_length,
                cos_plan=cos_plan,
                evidence_ids=route_evidence_ids,
            )
        )
    return tuple(routes), tuple(gates)


def _build_cos_plan(cos_bytes: bytes, source_name: str | None) -> CaptureOneCosPlan:
    parse_bytes = cos_bytes.rstrip(b"\x00\r\n\t ")
    try:
        root = fromstring(parse_bytes)
    except ParseError as exc:
        gate = CaptureOneEmissionGate(
            "malformed_cos_xml",
            f"COS XML parsing failed: {exc}.",
            (CAPTURE_ONE_PROCESS_COS_SOURCE,),
        )
        return CaptureOneCosPlan(
            source_name=source_name,
            payload_length=len(cos_bytes),
            tags=(),
            gates=(gate,),
            evidence_ids=(
                CAPTURE_ONE_TABLE_SOURCE,
                CAPTURE_ONE_ATTR_SOURCE,
                CAPTURE_ONE_FOUND_SOURCE,
                CAPTURE_ONE_PROCESS_COS_SOURCE,
            ),
        )

    tags = tuple(_iter_cos_tags(root, ()))
    return CaptureOneCosPlan(
        source_name=source_name,
        payload_length=len(cos_bytes),
        tags=tags,
        gates=(),
        evidence_ids=_unique_evidence_ids(
            (
                CAPTURE_ONE_TABLE_SOURCE,
                CAPTURE_ONE_ATTR_SOURCE,
                CAPTURE_ONE_FOUND_SOURCE,
                CAPTURE_ONE_PROCESS_COS_SOURCE,
                *(evidence_id for tag in tags for evidence_id in tag.evidence_ids),
            )
        ),
    )


def _iter_cos_tags(
    element: Element,
    parents: tuple[str, ...],
) -> tuple[CaptureOneCosTagPlan, ...]:
    current_name = _local_xml_name(element.tag)
    path = (*parents, current_name)
    tags: list[CaptureOneCosTagPlan] = []
    tag_name, value, evidence_ids = _cos_property(element)
    if tag_name:
        source_declared = tag_name == "ColorCorrections"
        group_2: CaptureOneGroup2 = "Time" if _is_date_like_tag(tag_name) else "Image"
        tags.append(
            CaptureOneCosTagPlan(
                tag_name=tag_name,
                value=value,
                xml_path="/".join(path),
                group_0="XML",
                group_1="XML",
                group_2=group_2,
                action="preserve_source_tag" if source_declared else "preserve_dynamic_tag",
                is_source_declared=source_declared,
                hidden=source_declared,
                evidence_ids=evidence_ids,
            )
        )
    for child in list(element):
        tags.extend(_iter_cos_tags(child, path))
    return tuple(tags)


def _cos_property(element: Element) -> tuple[str, str, tuple[str, ...]]:
    text = element.text.strip() if element.text is not None else ""
    if not text and "K" in element.attrib and "V" in element.attrib:
        return (
            element.attrib["K"],
            element.attrib["V"],
            (CAPTURE_ONE_ATTR_SOURCE, CAPTURE_ONE_FOUND_SOURCE),
        )
    if text:
        return (_local_xml_name(element.tag), text, (CAPTURE_ONE_FOUND_SOURCE,))
    return ("", "", (CAPTURE_ONE_FOUND_SOURCE,))


def _is_routed_member(
    name: str,
    manifest_paths: frozenset[str],
    routing_mode: CaptureOneRoutingMode,
) -> bool:
    if routing_mode == "manifest":
        return name in manifest_paths
    suffix = _lower_suffix(name)
    if suffix in CAPTURE_ONE_IMAGE_EXTENSIONS:
        return "/" not in name
    return suffix == ".cos" and name.lower().startswith("captureone/")


def _member_boundary(name: str, routed: bool) -> CaptureOneMemberBoundary:
    if re.fullmatch(r"manifest\d*\.xml", name):
        return "manifest"
    suffix = _lower_suffix(name)
    if routed and suffix == ".cos":
        return "settings_sidecar"
    if routed and suffix in CAPTURE_ONE_IMAGE_EXTENSIONS:
        return "embedded_image_payload"
    if suffix in CAPTURE_ONE_IMAGE_EXTENSIONS or "preview" in name.lower():
        return "preview_or_payload"
    return "opaque_payload"


def _route_action(
    boundary: CaptureOneMemberBoundary,
    routed: bool,
) -> CaptureOneRouteAction:
    if boundary == "manifest":
        return "parse_manifest"
    if routed and boundary == "settings_sidecar":
        return "parse_cos_settings"
    if routed and boundary == "embedded_image_payload":
        return "delegate_embedded_image_metadata"
    if boundary == "preview_or_payload":
        return "preserve_preview_or_payload"
    return "preserve_opaque_payload"


def _route_evidence_ids(
    boundary: CaptureOneMemberBoundary,
    routed: bool,
    routing_mode: CaptureOneRoutingMode,
) -> tuple[str, ...]:
    evidence_ids: list[str] = [CAPTURE_ONE_EIP_MEMBER_SOURCE]
    if boundary == "manifest":
        evidence_ids.append(CAPTURE_ONE_EIP_MANIFEST_SOURCE)
    if routing_mode == "fallback":
        evidence_ids.append(CAPTURE_ONE_EIP_FALLBACK_SOURCE)
    if routed and boundary == "settings_sidecar":
        evidence_ids.append(CAPTURE_ONE_EIP_COS_SOURCE)
    if routed and boundary == "embedded_image_payload":
        evidence_ids.append(CAPTURE_ONE_EIP_IMAGE_SOURCE)
    return _unique_evidence_ids(tuple(evidence_ids))


def _read_member_payload(
    archive: zipfile.ZipFile,
    name: str,
) -> tuple[bytes, CaptureOneEmissionGate | None]:
    try:
        info = archive.getinfo(name)
        if info.file_size > CAPTURE_ONE_MAX_DELEGATE_PAYLOAD_BYTES:
            return b"", CaptureOneEmissionGate(
                "member_payload_unavailable",
                (
                    f"Routed EIP member {name!r} is {info.file_size} bytes, which exceeds "
                    "the bounded delegate payload limit of "
                    f"{CAPTURE_ONE_MAX_DELEGATE_PAYLOAD_BYTES}."
                ),
                (CAPTURE_ONE_EIP_MEMBER_SOURCE,),
            )
        return archive.read(name), None
    except (KeyError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        return b"", CaptureOneEmissionGate(
            "member_payload_unavailable",
            f"Routed EIP member {name!r} could not be extracted: {exc}.",
            (CAPTURE_ONE_EIP_MEMBER_SOURCE,),
        )


def _capture_one_zip_gates(
    zip_plan: ZipArchiveTransactionPlan,
) -> tuple[CaptureOneEmissionGate, ...]:
    gates: list[CaptureOneEmissionGate] = []
    for gate in zip_plan.output_emission_gates:
        if gate.code == "non_mutating_plan_requires_explicit_emission":
            continue
        gates.append(
            CaptureOneEmissionGate(
                "zip_container_blocker",
                f"EIP ZIP validation failed through {gate.code}: {gate.reason}",
                (CAPTURE_ONE_EIP_MEMBER_SOURCE, *_zip_evidence_ids(gate.evidence_ids)),
            )
        )
    return tuple(gates)


def _rewrite_gates(
    rewrite_request: CaptureOneRewriteRequest | None,
) -> tuple[CaptureOneEmissionGate, ...]:
    if rewrite_request is None or not rewrite_request.has_changes:
        return ()
    gates: list[CaptureOneEmissionGate] = []
    if rewrite_request.cos_tags:
        gates.append(
            CaptureOneEmissionGate(
                "cos_tag_rewrite_not_source_backed",
                "CaptureOne.pm reads COS tags but does not declare a COS writer.",
                (CAPTURE_ONE_READ_ONLY_SOURCE, CAPTURE_ONE_PROCESS_COS_SOURCE),
            )
        )
    if rewrite_request.eip_members:
        gates.append(
            CaptureOneEmissionGate(
                "eip_member_rewrite_not_source_backed",
                "CaptureOne.pm reads EIP package members but does not declare an EIP writer.",
                (CAPTURE_ONE_READ_ONLY_SOURCE, CAPTURE_ONE_EIP_MEMBER_SOURCE),
            )
        )
    return tuple(gates)


def _detect_input_kind(source_bytes: bytes, source_name: str | None) -> CaptureOneInputKind:
    lower_name = source_name.lower() if source_name is not None else ""
    stripped = source_bytes.lstrip()
    if lower_name.endswith(".cos") or stripped.startswith(b"<"):
        return "cos"
    if lower_name.endswith(".eip") or source_bytes.startswith(b"PK"):
        return "eip"
    return "unknown"


def _status_from_gates(gates: list[CaptureOneEmissionGate]) -> CaptureOnePlanStatus:
    if any(
        gate.code
        in {
            "unrecognized_capture_one_input",
            "malformed_cos_xml",
            "zip_container_blocker",
            "member_payload_unavailable",
        }
        for gate in gates
    ):
        return "blocked"
    if any(
        gate.code in {"cos_tag_rewrite_not_source_backed", "eip_member_rewrite_not_source_backed"}
        for gate in gates
    ):
        return "unsupported"
    return "planned"


def _non_mutating_gate() -> CaptureOneEmissionGate:
    return CaptureOneEmissionGate(
        "non_mutating_plan_requires_explicit_emission",
        (
            "Capture One transaction plans preserve evidence_id bytes unless emission is "
            "explicitly allowed."
        ),
        (CAPTURE_ONE_READ_ONLY_SOURCE,),
    )


def _is_date_like_tag(tag_name: str) -> bool:
    sanitized = re.sub(r"[^-_a-zA-Z0-9]", "", tag_name[:1].upper() + tag_name[1:])
    return re.search(r"Date(?![a-z])", sanitized) is not None


def _lower_suffix(name: str) -> str:
    dot_offset = name.rfind(".")
    if dot_offset < 0:
        return ""
    return name[dot_offset:].lower()


def _local_xml_name(name: str) -> str:
    if "}" in name:
        return name.rsplit("}", 1)[1]
    return name


def _unique_evidence_ids(evidence_ids: tuple[str, ...]) -> tuple[str, ...]:
    unique: dict[str, str] = {}
    for evidence_id in evidence_ids:
        unique[evidence_id] = evidence_id
    return tuple(unique.values())


def _unique_gates(gates: tuple[CaptureOneEmissionGate, ...]) -> tuple[CaptureOneEmissionGate, ...]:
    unique: dict[tuple[CaptureOneGateCode, str], CaptureOneEmissionGate] = {}
    for gate in gates:
        unique[(gate.code, gate.reason)] = gate
    return tuple(unique.values())
