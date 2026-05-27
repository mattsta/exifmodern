"""Source-backed, non-mutating Google metadata transaction planning."""

from __future__ import annotations

import base64
import binascii
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject, JsonValue

GOOGLE_SOURCE_PATH = "lib/Image/ExifTool/Google.pm"

type GoogleSurfaceKind = Literal[
    "xmp_packet",
    "quicktime_gspherical_track",
    "jpeg_google_trailer",
]
type GoogleNamespace = Literal[
    "GAudio",
    "GImage",
    "GPano",
    "GSpherical",
    "GDepth",
    "GFocus",
    "GCamera",
    "GCreations",
    "Device",
    "GContainer",
    "GItem",
]
type GoogleValueKind = Literal["string", "integer", "real", "boolean", "date", "binary"]
type GooglePayloadKind = Literal[
    "none",
    "base64_binary",
    "hdrp_text",
    "hdrp_protobuf",
    "trailer_mime",
    "trailer_length",
    "trailer_padding",
    "trailer_uri",
]
type GoogleRole = Literal[
    "audio_metadata",
    "image_metadata",
    "video_metadata",
    "camera_metadata",
    "pixel_camera_metadata",
    "depth_metadata",
    "focus_metadata",
    "panorama_metadata",
    "time_metadata",
    "protobuf_metadata",
    "trailer_metadata",
    "unknown_payload",
]
type GoogleRouteAction = Literal[
    "route_google_xmp_property",
    "route_hdrp_makernote_payload",
    "route_protobuf_payload",
    "route_google_trailer_boundary",
    "preserve_unknown_google_property",
    "block_requested_rewrite",
    "route_source_backed_rewrite",
    "no_metadata_mutation",
]
type GoogleBlockerCode = Literal[
    "malformed_xmp_packet",
    "truncated_xmp_packet",
    "malformed_base64_payload",
    "unrecognized_hdrp_payload",
    "invalid_trailer_length",
    "unsupported_google_property",
]
type GoogleEmissionGateCode = Literal[
    "malformed_xmp_packet",
    "truncated_xmp_packet",
    "malformed_base64_payload",
    "unrecognized_hdrp_payload",
    "invalid_trailer_length",
    "unsupported_google_rewrite",
    "source_backed_rewrite_requires_downstream_writer",
    "raw_payload_preservation_required",
    "planner_is_non_mutating",
    "google_writer_not_implemented",
]
type GoogleRewriteOperation = Literal["replace_property", "delete_property", "insert_property"]
type GoogleMetadataValue = str | int | float | bool | bytes


@dataclass(frozen=True)
class EvidenceAnchor:
    path: str
    line_start: int
    line_end: int
    symbol: str
    evidence: str


GOOGLE_AUDIO_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=101,
    line_end=112,
    symbol="%Image::ExifTool::Google::GAudio",
    evidence="GAudio declares XMP-GAudio audio data and MIME tags with base64 conversion.",
)
GOOGLE_IMAGE_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=114,
    line_end=125,
    symbol="%Image::ExifTool::Google::GImage",
    evidence="GImage declares XMP-GImage image data and MIME tags with base64 conversion.",
)
GOOGLE_PANO_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=127,
    line_end=166,
    symbol="%Image::ExifTool::Google::GPano",
    evidence="GPano declares Google panorama XMP tags and their writable scalar formats.",
)
GOOGLE_SPHERICAL_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=168,
    line_end=208,
    symbol="%Image::ExifTool::Google::GSpherical",
    evidence=("GSpherical declares RDF/XML tags for Google spherical MP4 video track metadata."),
)
GOOGLE_DEPTH_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=210,
    line_end=252,
    symbol="%Image::ExifTool::Google::GDepth",
    evidence="GDepth declares depth-map XMP tags, base64 image payloads, and scalar fields.",
)
GOOGLE_FOCUS_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=254,
    line_end=264,
    symbol="%Image::ExifTool::Google::GFocus",
    evidence="GFocus declares focus metadata from Google depthmap images.",
)
GOOGLE_CAMERA_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=266,
    line_end=311,
    symbol="%Image::ExifTool::Google::GCamera",
    evidence=(
        "GCamera declares Pixel camera, motion photo, micro video, HDRP, "
        "ShotLogData, and HDRPlusMakerNote tags."
    ),
)
GOOGLE_CREATIONS_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=313,
    line_end=321,
    symbol="%Image::ExifTool::Google::GCreations",
    evidence="GCreations declares Google creations camera tags.",
)
GOOGLE_DEVICE_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=323,
    line_end=474,
    symbol="%Image::ExifTool::Google::Device",
    evidence=(
        "Device declares dynamic-depth containers, profiles, cameras, depth maps, "
        "imaging models, point clouds, pose, light estimates, and trailer triggers."
    ),
)
GOOGLE_CONTAINER_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=476,
    line_end=511,
    symbol="%Image::ExifTool::Google::GContainer",
    evidence=(
        "GContainer declares HDR image container directory items and trailer-trigger "
        "Mime/Length/Padding/URI boundaries."
    ),
)
GOOGLE_HDRPLUS_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=513,
    line_end=577,
    symbol="%Image::ExifTool::Google::HDRPlusMakerNote",
    evidence="HDRPlusMakerNote declares protobuf-format HDR-Plus maker-note fields.",
)
GOOGLE_SHOTLOG_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=579,
    line_end=589,
    symbol="%Image::ExifTool::Google::ShotLogData",
    evidence="ShotLogData declares protobuf fields stored as encoded HDRP payloads.",
)
GOOGLE_HDRP_TEXT_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=591,
    line_end=625,
    symbol="%Image::ExifTool::Google::HDRPMakerNote and PortraitReq",
    evidence="HDRPMakerNote and PortraitReq declare text-format encoded HDRP maker notes.",
)
GOOGLE_HDRP_PROCESS_SOURCE = EvidenceAnchor(
    path=GOOGLE_SOURCE_PATH,
    line_start=665,
    line_end=780,
    symbol="ProcessHDRP",
    evidence=(
        "ProcessHDRP accepts raw or base64 HDRP version 2/3 payloads, decrypts and "
        "gunzips them, then routes version 3 or IsProtobuf data through Protobuf."
    ),
)


@dataclass(frozen=True)
class GooglePropertySpec:
    namespace: GoogleNamespace
    property_id: str
    tag_name: str
    group2: str
    value_kind: GoogleValueKind
    role: GoogleRole
    writable: bool
    payload_kind: GooglePayloadKind
    evidence_anchors: tuple[EvidenceAnchor, ...]


@dataclass(frozen=True)
class GoogleTablePlan:
    namespace: GoogleNamespace
    xmp_group: str
    group2: str
    property_count: int
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "group2": self.group2,
            "namespace": self.namespace,
            "property_count": self.property_count,
            "xmp_group": self.xmp_group,
        }


@dataclass(frozen=True)
class GoogleMetadataPropertyPlan:
    namespace: GoogleNamespace
    property_id: str
    tag_name: str
    group2: str
    role: GoogleRole
    value_kind: GoogleValueKind
    value: GoogleMetadataValue
    payload_kind: GooglePayloadKind
    known: bool
    writable: bool
    xml_path: tuple[str, ...]
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "group2": self.group2,
            "known": self.known,
            "namespace": self.namespace,
            "payload_kind": self.payload_kind,
            "property_id": self.property_id,
            "role": self.role,
            "tag_name": self.tag_name,
            "value": metadata_value_to_json(self.value),
            "value_kind": self.value_kind,
            "writable": self.writable,
            "xml_path": list(self.xml_path),
        }


@dataclass(frozen=True)
class GooglePayloadPreservationPlan:
    name: str
    payload_kind: GooglePayloadKind
    source_property: str
    raw_text: str
    decoded_size: int | None
    hdrp_version: int | None
    preserve_original: bool
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "decoded_size": self.decoded_size,
            "hdrp_version": self.hdrp_version,
            "name": self.name,
            "payload_kind": self.payload_kind,
            "preserve_original": self.preserve_original,
            "raw_text": self.raw_text,
            "source_property": self.source_property,
        }


@dataclass(frozen=True)
class GoogleTrailerBoundaryPlan:
    namespace: GoogleNamespace
    mime: str | None
    length: int | None
    padding: int | None
    uri: str | None
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "length": self.length,
            "mime": self.mime,
            "namespace": self.namespace,
            "padding": self.padding,
            "uri": self.uri,
        }


@dataclass(frozen=True)
class GoogleActionPlan:
    action: GoogleRouteAction
    property_id: str | None
    reason: str
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "property_id": self.property_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GoogleTransactionBlocker:
    code: GoogleBlockerCode
    reason: str
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GoogleEmissionGate:
    code: GoogleEmissionGateCode
    reason: str
    blocks_emission: bool
    evidence_anchors: tuple[EvidenceAnchor, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocks_emission": self.blocks_emission,
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GoogleRewriteRequest:
    operation: GoogleRewriteOperation
    namespace: GoogleNamespace
    property_id: str
    value: GoogleMetadataValue | None = None


@dataclass(frozen=True)
class GoogleMetadataTransactionPlan:
    surface_kind: GoogleSurfaceKind
    raw_packet: bytes
    tables: tuple[GoogleTablePlan, ...]
    properties: tuple[GoogleMetadataPropertyPlan, ...]
    payload_preservations: tuple[GooglePayloadPreservationPlan, ...]
    trailer_boundaries: tuple[GoogleTrailerBoundaryPlan, ...]
    actions: tuple[GoogleActionPlan, ...]
    blockers: tuple[GoogleTransactionBlocker, ...]
    output_emission_gates: tuple[GoogleEmissionGate, ...]
    rewrite_requests: tuple[GoogleRewriteRequest, ...]
    evidence_anchors: tuple[EvidenceAnchor, ...]

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def unknown_properties(self) -> tuple[GoogleMetadataPropertyPlan, ...]:
        return tuple(property_plan for property_plan in self.properties if not property_plan.known)

    @property
    def protobuf_payloads(self) -> tuple[GooglePayloadPreservationPlan, ...]:
        return tuple(
            payload
            for payload in self.payload_preservations
            if payload.payload_kind == "hdrp_protobuf"
        )

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        raise ValueError(f"Google metadata transaction output is gated: {gate_codes}")

    def to_json(self) -> JsonObject:
        return {
            "actions": [action.to_json() for action in self.actions],
            "blockers": [blocker.to_json() for blocker in self.blockers],
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "payload_preservations": [payload.to_json() for payload in self.payload_preservations],
            "properties": [property_plan.to_json() for property_plan in self.properties],
            "raw_packet_hex": self.raw_packet.hex(),
            "rewrite_requests": [
                {
                    "namespace": request.namespace,
                    "operation": request.operation,
                    "property_id": request.property_id,
                    "value": metadata_value_to_json(request.value),
                }
                for request in self.rewrite_requests
            ],
            "surface_kind": self.surface_kind,
            "tables": [table.to_json() for table in self.tables],
            "trailer_boundaries": [boundary.to_json() for boundary in self.trailer_boundaries],
        }


def build_google_metadata_transaction_plan(
    data: bytes,
    *,
    surface_kind: GoogleSurfaceKind = "xmp_packet",
    rewrite_requests: tuple[GoogleRewriteRequest, ...] = (),
) -> GoogleMetadataTransactionPlan:
    """Build a Google metadata plan without mutating bytes."""

    properties, parse_actions, blockers = parse_google_xmp_properties(data)
    payloads, payload_blockers = payload_preservations_for(properties)
    trailer_boundaries, trailer_blockers = trailer_boundaries_for(properties)
    all_blockers = (*blockers, *payload_blockers, *trailer_blockers)
    actions = [
        *parse_actions,
        *actions_for_payloads(payloads),
        *actions_for_trailers(trailer_boundaries),
        *actions_for_rewrites(rewrite_requests),
        GoogleActionPlan(
            "no_metadata_mutation",
            None,
            "Planner records Google.pm routing and payload preservation only.",
            (GOOGLE_HDRP_PROCESS_SOURCE,),
        ),
    ]
    gates = [
        *gates_for_blockers(all_blockers),
        *gates_for_rewrites(rewrite_requests),
        *default_output_gates(),
    ]
    tables = table_plans()
    sources = unique_evidence_anchors(
        (
            *(source for table in tables for source in table.evidence_anchors),
            *(source for property_plan in properties for source in property_plan.evidence_anchors),
            *(source for payload in payloads for source in payload.evidence_anchors),
            *(source for boundary in trailer_boundaries for source in boundary.evidence_anchors),
            *(source for action in actions for source in action.evidence_anchors),
            *(source for blocker in all_blockers for source in blocker.evidence_anchors),
            *(source for gate in gates for source in gate.evidence_anchors),
        )
    )
    return GoogleMetadataTransactionPlan(
        surface_kind=surface_kind,
        raw_packet=data,
        tables=tables,
        properties=properties,
        payload_preservations=payloads,
        trailer_boundaries=trailer_boundaries,
        actions=tuple(actions),
        blockers=all_blockers,
        output_emission_gates=unique_gates(tuple(gates)),
        rewrite_requests=rewrite_requests,
        evidence_anchors=sources,
    )


def parse_google_xmp_properties(
    data: bytes,
) -> tuple[
    tuple[GoogleMetadataPropertyPlan, ...],
    tuple[GoogleActionPlan, ...],
    tuple[GoogleTransactionBlocker, ...],
]:
    if not data.strip():
        return (), (), ()
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        code: GoogleBlockerCode = (
            "truncated_xmp_packet" if looks_truncated_xml(data) else "malformed_xmp_packet"
        )
        return (
            (),
            (),
            (
                GoogleTransactionBlocker(
                    code,
                    f"Google XMP/RDF XML could not be parsed: {error}.",
                    (
                        GOOGLE_PANO_SOURCE,
                        GOOGLE_SPHERICAL_SOURCE,
                        GOOGLE_CAMERA_SOURCE,
                        GOOGLE_DEVICE_SOURCE,
                        GOOGLE_CONTAINER_SOURCE,
                    ),
                ),
            ),
        )

    properties: list[GoogleMetadataPropertyPlan] = []
    actions: list[GoogleActionPlan] = []
    collect_properties(root, (), properties, actions)
    return tuple(properties), tuple(actions), ()


def collect_properties(
    element: ET.Element[str],
    parent_path: tuple[str, ...],
    properties: list[GoogleMetadataPropertyPlan],
    actions: list[GoogleActionPlan],
) -> None:
    element_name = expanded_name(element.tag)
    path = (*parent_path, element_name.local_name)
    for attr_name, attr_value in element.attrib.items():
        add_property(expanded_name(attr_name), attr_value, (*path, "@"), properties, actions)
    text = element.text.strip() if element.text is not None else ""
    if text:
        add_property(element_name, text, path, properties, actions)
    for child in list(element):
        collect_properties(child, path, properties, actions)


def add_property(
    name: ExpandedName,
    text: str,
    path: tuple[str, ...],
    properties: list[GoogleMetadataPropertyPlan],
    actions: list[GoogleActionPlan],
) -> None:
    namespace = namespace_for_uri(name.namespace_uri)
    if namespace is None:
        return
    spec = property_spec_for(namespace, name.local_name)
    if spec is None:
        source = evidence_anchor_for_namespace(namespace)
        properties.append(
            GoogleMetadataPropertyPlan(
                namespace=namespace,
                property_id=name.local_name,
                tag_name=f"{namespace}{name.local_name}",
                group2=group2_for_namespace(namespace),
                role="unknown_payload",
                value_kind="string",
                value=text,
                payload_kind="none",
                known=False,
                writable=False,
                xml_path=path,
                evidence_anchors=(source,),
            )
        )
        actions.append(
            GoogleActionPlan(
                "preserve_unknown_google_property",
                name.local_name,
                "Google namespace property is not declared in Google.pm and is preserved only.",
                (source,),
            )
        )
        return
    value = convert_value(text, spec.value_kind)
    properties.append(
        GoogleMetadataPropertyPlan(
            namespace=spec.namespace,
            property_id=spec.property_id,
            tag_name=spec.tag_name,
            group2=spec.group2,
            role=spec.role,
            value_kind=spec.value_kind,
            value=value,
            payload_kind=spec.payload_kind,
            known=True,
            writable=spec.writable,
            xml_path=path,
            evidence_anchors=spec.evidence_anchors,
        )
    )
    action: GoogleRouteAction = (
        "route_google_trailer_boundary"
        if spec.payload_kind in TRAILER_PAYLOAD_KINDS
        else "route_google_xmp_property"
    )
    actions.append(
        GoogleActionPlan(
            action,
            spec.property_id,
            f"Route {spec.namespace}:{spec.property_id} through its Google.pm table.",
            spec.evidence_anchors,
        )
    )


@dataclass(frozen=True)
class ExpandedName:
    namespace_uri: str | None
    local_name: str


def expanded_name(value: str) -> ExpandedName:
    if value.startswith("{"):
        namespace_uri, _, local_name = value[1:].partition("}")
        return ExpandedName(namespace_uri, local_name)
    if ":" in value:
        prefix, _, local_name = value.partition(":")
        return ExpandedName(prefix, local_name)
    return ExpandedName(None, value)


def convert_value(text: str, value_kind: GoogleValueKind) -> GoogleMetadataValue:
    if value_kind == "integer":
        try:
            return int(text)
        except ValueError:
            return text
    if value_kind == "real":
        try:
            return float(text)
        except ValueError:
            return text
    if value_kind == "boolean":
        lowered = text.strip().lower()
        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0"):
            return False
        return text
    return text


def payload_preservations_for(
    properties: tuple[GoogleMetadataPropertyPlan, ...],
) -> tuple[tuple[GooglePayloadPreservationPlan, ...], tuple[GoogleTransactionBlocker, ...]]:
    payloads: list[GooglePayloadPreservationPlan] = []
    blockers: list[GoogleTransactionBlocker] = []
    for property_plan in properties:
        if property_plan.payload_kind == "base64_binary":
            decoded_size, blocker = decoded_base64_size(property_plan)
            if blocker is not None:
                blockers.append(blocker)
            payloads.append(
                GooglePayloadPreservationPlan(
                    property_plan.tag_name,
                    property_plan.payload_kind,
                    property_plan.property_id,
                    value_as_text(property_plan.value),
                    decoded_size,
                    None,
                    True,
                    property_plan.evidence_anchors,
                )
            )
        if property_plan.payload_kind in ("hdrp_text", "hdrp_protobuf"):
            decoded_size, version, blocker = hdrp_payload_boundary(property_plan)
            if blocker is not None:
                blockers.append(blocker)
            payloads.append(
                GooglePayloadPreservationPlan(
                    property_plan.tag_name,
                    property_plan.payload_kind,
                    property_plan.property_id,
                    value_as_text(property_plan.value),
                    decoded_size,
                    version,
                    True,
                    (*property_plan.evidence_anchors, GOOGLE_HDRP_PROCESS_SOURCE),
                )
            )
    return tuple(payloads), tuple(blockers)


def decoded_base64_size(
    property_plan: GoogleMetadataPropertyPlan,
) -> tuple[int | None, GoogleTransactionBlocker | None]:
    raw_text = value_as_text(property_plan.value)
    try:
        decoded = base64.b64decode(raw_text, validate=True)
    except binascii.Error as error:
        return None, GoogleTransactionBlocker(
            "malformed_base64_payload",
            (
                f"{property_plan.tag_name} is declared as base64 payload but could "
                f"not decode: {error}."
            ),
            property_plan.evidence_anchors,
        )
    return len(decoded), None


def hdrp_payload_boundary(
    property_plan: GoogleMetadataPropertyPlan,
) -> tuple[int | None, int | None, GoogleTransactionBlocker | None]:
    raw_text = value_as_text(property_plan.value)
    raw_bytes = raw_text.encode("latin-1")
    decoded = raw_bytes
    if not raw_bytes.startswith((b"HDRP\x02", b"HDRP\x03")):
        try:
            decoded = base64.b64decode(raw_text, validate=True)
        except binascii.Error as error:
            return (
                None,
                None,
                GoogleTransactionBlocker(
                    "malformed_base64_payload",
                    f"{property_plan.tag_name} HDRP payload could not base64-decode: {error}.",
                    (*property_plan.evidence_anchors, GOOGLE_HDRP_PROCESS_SOURCE),
                ),
            )
    if not decoded.startswith((b"HDRP\x02", b"HDRP\x03")):
        return (
            len(decoded),
            None,
            GoogleTransactionBlocker(
                "unrecognized_hdrp_payload",
                f"{property_plan.tag_name} payload does not start with HDRP version 2 or 3.",
                (*property_plan.evidence_anchors, GOOGLE_HDRP_PROCESS_SOURCE),
            ),
        )
    return len(decoded), decoded[4], None


def trailer_boundaries_for(
    properties: tuple[GoogleMetadataPropertyPlan, ...],
) -> tuple[tuple[GoogleTrailerBoundaryPlan, ...], tuple[GoogleTransactionBlocker, ...]]:
    item_properties = [
        property_plan
        for property_plan in properties
        if property_plan.namespace in ("GItem", "Device")
        and property_plan.payload_kind in TRAILER_PAYLOAD_KINDS
    ]
    if not item_properties:
        return (), ()
    mime = first_text_value(item_properties, "Mime")
    length_value = first_text_value(item_properties, "Length")
    padding_value = first_text_value(item_properties, "Padding")
    uri = first_text_value(item_properties, "URI") or first_text_value(item_properties, "DataURI")
    length, length_blocker = non_negative_int_value("Length", length_value)
    padding, padding_blocker = non_negative_int_value("Padding", padding_value)
    evidence_anchors = unique_evidence_anchors(
        tuple(
            source for property_plan in item_properties for source in property_plan.evidence_anchors
        )
    )
    blockers = tuple(
        blocker for blocker in (length_blocker, padding_blocker) if blocker is not None
    )
    namespace = item_properties[0].namespace
    return (
        (
            GoogleTrailerBoundaryPlan(
                namespace,
                mime,
                length,
                padding,
                uri,
                evidence_anchors,
            ),
        ),
        blockers,
    )


def first_text_value(
    properties: list[GoogleMetadataPropertyPlan],
    property_id: str,
) -> str | None:
    for property_plan in properties:
        if property_plan.property_id == property_id:
            return value_as_text(property_plan.value)
    return None


def non_negative_int_value(
    property_id: str,
    value: str | None,
) -> tuple[int | None, GoogleTransactionBlocker | None]:
    if value is None:
        return None, None
    try:
        parsed = int(value)
    except ValueError:
        return None, GoogleTransactionBlocker(
            "invalid_trailer_length",
            f"Google trailer {property_id} value is not an integer.",
            (GOOGLE_DEVICE_SOURCE, GOOGLE_CONTAINER_SOURCE),
        )
    if parsed < 0:
        return None, GoogleTransactionBlocker(
            "invalid_trailer_length",
            f"Google trailer {property_id} value is negative.",
            (GOOGLE_DEVICE_SOURCE, GOOGLE_CONTAINER_SOURCE),
        )
    return parsed, None


def actions_for_payloads(
    payloads: tuple[GooglePayloadPreservationPlan, ...],
) -> tuple[GoogleActionPlan, ...]:
    actions: list[GoogleActionPlan] = []
    for payload in payloads:
        action: GoogleRouteAction = (
            "route_protobuf_payload"
            if payload.payload_kind == "hdrp_protobuf"
            else "route_hdrp_makernote_payload"
        )
        if payload.payload_kind == "base64_binary":
            action = "route_google_xmp_property"
        actions.append(
            GoogleActionPlan(
                action,
                payload.source_property,
                f"Preserve encoded payload for {payload.name}; planner does not rewrite it.",
                payload.evidence_anchors,
            )
        )
    return tuple(actions)


def actions_for_trailers(
    boundaries: tuple[GoogleTrailerBoundaryPlan, ...],
) -> tuple[GoogleActionPlan, ...]:
    return tuple(
        GoogleActionPlan(
            "route_google_trailer_boundary",
            "Mime",
            "Google.pm uses item Mime values as ProcessGoogleTrailer triggers.",
            boundary.evidence_anchors,
        )
        for boundary in boundaries
    )


def actions_for_rewrites(
    rewrite_requests: tuple[GoogleRewriteRequest, ...],
) -> tuple[GoogleActionPlan, ...]:
    actions: list[GoogleActionPlan] = []
    for request in rewrite_requests:
        spec = property_spec_for(request.namespace, request.property_id)
        if spec is not None and spec.writable:
            actions.append(
                GoogleActionPlan(
                    "route_source_backed_rewrite",
                    request.property_id,
                    "Rewrite target is declared writable by Google.pm, but no writer is emitted.",
                    spec.evidence_anchors,
                )
            )
        else:
            source = (
                spec.evidence_anchors
                if spec is not None
                else (evidence_anchor_for_namespace(request.namespace),)
            )
            actions.append(
                GoogleActionPlan(
                    "block_requested_rewrite",
                    request.property_id,
                    "Rewrite target is not a Google.pm-backed writable property.",
                    source,
                )
            )
    return tuple(actions)


def gates_for_blockers(
    blockers: tuple[GoogleTransactionBlocker, ...],
) -> tuple[GoogleEmissionGate, ...]:
    return tuple(
        GoogleEmissionGate(
            blocker_to_gate_code(blocker.code),
            blocker.reason,
            True,
            blocker.evidence_anchors,
        )
        for blocker in blockers
    )


def gates_for_rewrites(
    rewrite_requests: tuple[GoogleRewriteRequest, ...],
) -> tuple[GoogleEmissionGate, ...]:
    gates: list[GoogleEmissionGate] = []
    for request in rewrite_requests:
        spec = property_spec_for(request.namespace, request.property_id)
        if spec is not None and spec.writable:
            gates.append(
                GoogleEmissionGate(
                    "source_backed_rewrite_requires_downstream_writer",
                    (
                        f"{request.namespace}:{request.property_id} is source-backed, "
                        "but this slice does not emit XMP or trailer bytes."
                    ),
                    True,
                    spec.evidence_anchors,
                )
            )
        else:
            source = (
                spec.evidence_anchors
                if spec is not None
                else (evidence_anchor_for_namespace(request.namespace),)
            )
            gates.append(
                GoogleEmissionGate(
                    "unsupported_google_rewrite",
                    (
                        f"{request.namespace}:{request.property_id} is not a supported "
                        "Google.pm rewrite."
                    ),
                    True,
                    source,
                )
            )
    return tuple(gates)


def default_output_gates() -> tuple[GoogleEmissionGate, ...]:
    return (
        GoogleEmissionGate(
            "raw_payload_preservation_required",
            "Encoded XMP, HDRP/protobuf, and trailer payloads must be preserved byte-for-byte.",
            True,
            (GOOGLE_HDRP_PROCESS_SOURCE, GOOGLE_CONTAINER_SOURCE, GOOGLE_DEVICE_SOURCE),
        ),
        GoogleEmissionGate(
            "planner_is_non_mutating",
            "This transaction plan is intentionally non-mutating by default.",
            True,
            (GOOGLE_CAMERA_SOURCE, GOOGLE_CONTAINER_SOURCE),
        ),
        GoogleEmissionGate(
            "google_writer_not_implemented",
            "No Google.pm-backed output writer is implemented in this slice.",
            True,
            (GOOGLE_CAMERA_SOURCE, GOOGLE_SPHERICAL_SOURCE, GOOGLE_CONTAINER_SOURCE),
        ),
    )


def blocker_to_gate_code(code: GoogleBlockerCode) -> GoogleEmissionGateCode:
    if code == "malformed_xmp_packet":
        return "malformed_xmp_packet"
    if code == "truncated_xmp_packet":
        return "truncated_xmp_packet"
    if code == "malformed_base64_payload":
        return "malformed_base64_payload"
    if code == "unrecognized_hdrp_payload":
        return "unrecognized_hdrp_payload"
    if code == "invalid_trailer_length":
        return "invalid_trailer_length"
    return "unsupported_google_rewrite"


def looks_truncated_xml(data: bytes) -> bool:
    stripped = data.rstrip()
    return stripped.startswith(b"<") and not stripped.endswith(b">")


TRAILER_PAYLOAD_KINDS = frozenset(
    {"trailer_mime", "trailer_length", "trailer_padding", "trailer_uri"}
)
GOOGLE_NAMESPACES: tuple[GoogleNamespace, ...] = (
    "GAudio",
    "GImage",
    "GPano",
    "GSpherical",
    "GDepth",
    "GFocus",
    "GCamera",
    "GCreations",
    "Device",
    "GContainer",
    "GItem",
)


def table_plans() -> tuple[GoogleTablePlan, ...]:
    return tuple(
        GoogleTablePlan(
            namespace,
            f"XMP-{namespace}",
            group2_for_namespace(namespace),
            len(PROPERTY_SPECS_BY_NAMESPACE.get(namespace, {})),
            (evidence_anchor_for_namespace(namespace),),
        )
        for namespace in GOOGLE_NAMESPACES
    )


def property_spec_for(namespace: GoogleNamespace, property_id: str) -> GooglePropertySpec | None:
    namespace_specs = PROPERTY_SPECS_BY_NAMESPACE.get(namespace)
    if namespace_specs is None:
        return None
    return namespace_specs.get(property_id)


def namespace_for_uri(uri: str | None) -> GoogleNamespace | None:
    if uri is None:
        return None
    return GOOGLE_URI_NAMESPACES.get(uri)


def evidence_anchor_for_namespace(namespace: GoogleNamespace) -> EvidenceAnchor:
    return {
        "GAudio": GOOGLE_AUDIO_SOURCE,
        "GImage": GOOGLE_IMAGE_SOURCE,
        "GPano": GOOGLE_PANO_SOURCE,
        "GSpherical": GOOGLE_SPHERICAL_SOURCE,
        "GDepth": GOOGLE_DEPTH_SOURCE,
        "GFocus": GOOGLE_FOCUS_SOURCE,
        "GCamera": GOOGLE_CAMERA_SOURCE,
        "GCreations": GOOGLE_CREATIONS_SOURCE,
        "Device": GOOGLE_DEVICE_SOURCE,
        "GContainer": GOOGLE_CONTAINER_SOURCE,
        "GItem": GOOGLE_CONTAINER_SOURCE,
    }[namespace]


def group2_for_namespace(namespace: GoogleNamespace) -> str:
    return {
        "GAudio": "Audio",
        "GImage": "Image",
        "GPano": "Image",
        "GSpherical": "Image",
        "GDepth": "Image",
        "GFocus": "Image",
        "GCamera": "Camera",
        "GCreations": "Camera",
        "Device": "Camera",
        "GContainer": "Image",
        "GItem": "Image",
    }[namespace]


def value_as_text(value: GoogleMetadataValue | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("latin-1")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def metadata_value_to_json(value: GoogleMetadataValue | None) -> JsonValue:
    if value is None:
        return None
    if isinstance(value, bytes):
        return {"hex": value.hex()}
    return value


def unique_evidence_anchors(references: tuple[EvidenceAnchor, ...]) -> tuple[EvidenceAnchor, ...]:
    unique: list[EvidenceAnchor] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


def unique_gates(gates: tuple[GoogleEmissionGate, ...]) -> tuple[GoogleEmissionGate, ...]:
    unique: list[GoogleEmissionGate] = []
    seen: set[tuple[GoogleEmissionGateCode, str]] = set()
    for gate in gates:
        key = (gate.code, gate.reason)
        if key not in seen:
            seen.add(key)
            unique.append(gate)
    return tuple(unique)


def evidence_anchor_to_json(reference: EvidenceAnchor) -> JsonObject:
    return {
        "evidence": reference.evidence,
        "line_end": reference.line_end,
        "line_start": reference.line_start,
        "path": reference.path,
        "symbol": reference.symbol,
    }


def evidence_anchors_to_json(references: tuple[EvidenceAnchor, ...]) -> JsonArray:
    return [evidence_anchor_to_json(reference) for reference in references]


def spec(
    namespace: GoogleNamespace,
    property_id: str,
    tag_name: str | None,
    value_kind: GoogleValueKind,
    role: GoogleRole,
    writable: bool,
    payload_kind: GooglePayloadKind,
    source: EvidenceAnchor,
) -> GooglePropertySpec:
    return GooglePropertySpec(
        namespace,
        property_id,
        tag_name or property_id,
        group2_for_namespace(namespace),
        value_kind,
        role,
        writable,
        payload_kind,
        (source,),
    )


def specs_by_namespace(
    specs: tuple[GooglePropertySpec, ...],
) -> dict[GoogleNamespace, dict[str, GooglePropertySpec]]:
    grouped: dict[GoogleNamespace, dict[str, GooglePropertySpec]] = {}
    for property_spec in specs:
        grouped.setdefault(property_spec.namespace, {})[property_spec.property_id] = property_spec
    return grouped


GOOGLE_URI_NAMESPACES: dict[str, GoogleNamespace] = {
    "GAudio": "GAudio",
    "GImage": "GImage",
    "GPano": "GPano",
    "GSpherical": "GSpherical",
    "GDepth": "GDepth",
    "GFocus": "GFocus",
    "GCamera": "GCamera",
    "GCreations": "GCreations",
    "GContainer": "GContainer",
    "GItem": "GItem",
    "Device": "Device",
    "http://ns.google.com/photos/1.0/audio/": "GAudio",
    "http://ns.google.com/photos/1.0/image/": "GImage",
    "http://ns.google.com/photos/1.0/panorama/": "GPano",
    "http://ns.google.com/videos/1.0/spherical/": "GSpherical",
    "http://ns.google.com/photos/1.0/depthmap/": "GDepth",
    "http://ns.google.com/photos/1.0/focus/": "GFocus",
    "http://ns.google.com/photos/1.0/camera/": "GCamera",
    "http://ns.google.com/photos/1.0/creations/": "GCreations",
    "http://ns.google.com/photos/1.0/container/": "GContainer",
    "http://ns.google.com/photos/1.0/container/item/": "GItem",
    "http://ns.google.com/photos/dd/1.0/device/": "Device",
    "http://ns.google.com/photos/dd/1.0/container/": "Device",
    "http://ns.google.com/photos/dd/1.0/item/": "Device",
    "http://ns.google.com/photos/dd/1.0/profile/": "Device",
    "http://ns.google.com/photos/dd/1.0/camera/": "Device",
    "http://ns.google.com/photos/dd/1.0/depthmap/": "Device",
    "http://ns.google.com/photos/dd/1.0/image/": "Device",
    "http://ns.google.com/photos/dd/1.0/imagingmodel/": "Device",
    "http://ns.google.com/photos/dd/1.0/pointcloud/": "Device",
    "http://ns.google.com/photos/dd/1.0/lightestimate/": "Device",
    "http://ns.google.com/photos/dd/1.0/vendorinfo/": "Device",
    "http://ns.google.com/photos/dd/1.0/appinfo/": "Device",
    "http://ns.google.com/photos/dd/1.0/earthpose/": "Device",
    "http://ns.google.com/photos/dd/1.0/pose/": "Device",
    "http://ns.google.com/photos/dd/1.0/plane/": "Device",
}

PROPERTY_SPECS_BY_NAMESPACE = specs_by_namespace(
    (
        spec(
            "GAudio",
            "Data",
            "AudioData",
            "binary",
            "audio_metadata",
            False,
            "base64_binary",
            GOOGLE_AUDIO_SOURCE,
        ),
        spec(
            "GAudio",
            "Mime",
            "AudioMimeType",
            "string",
            "audio_metadata",
            False,
            "none",
            GOOGLE_AUDIO_SOURCE,
        ),
        spec(
            "GImage",
            "Data",
            "ImageData",
            "binary",
            "image_metadata",
            False,
            "base64_binary",
            GOOGLE_IMAGE_SOURCE,
        ),
        spec(
            "GImage",
            "Mime",
            "ImageMimeType",
            "string",
            "image_metadata",
            False,
            "none",
            GOOGLE_IMAGE_SOURCE,
        ),
        spec(
            "GPano",
            "UsePanoramaViewer",
            None,
            "boolean",
            "panorama_metadata",
            True,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GPano",
            "CaptureSoftware",
            None,
            "string",
            "panorama_metadata",
            False,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GPano",
            "StitchingSoftware",
            None,
            "string",
            "panorama_metadata",
            False,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GPano",
            "ProjectionType",
            None,
            "string",
            "panorama_metadata",
            False,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GPano",
            "PoseHeadingDegrees",
            None,
            "real",
            "panorama_metadata",
            True,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GPano",
            "PosePitchDegrees",
            None,
            "real",
            "panorama_metadata",
            True,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GPano",
            "PoseRollDegrees",
            None,
            "real",
            "panorama_metadata",
            True,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GPano",
            "InitialViewHeadingDegrees",
            None,
            "real",
            "panorama_metadata",
            True,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GPano",
            "InitialViewPitchDegrees",
            None,
            "real",
            "panorama_metadata",
            True,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GPano",
            "InitialViewRollDegrees",
            None,
            "real",
            "panorama_metadata",
            True,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GPano",
            "FirstPhotoDate",
            None,
            "date",
            "time_metadata",
            True,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GPano",
            "LastPhotoDate",
            None,
            "date",
            "time_metadata",
            True,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GPano",
            "FullPanoWidthPixels",
            None,
            "real",
            "image_metadata",
            True,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GPano",
            "FullPanoHeightPixels",
            None,
            "real",
            "image_metadata",
            True,
            "none",
            GOOGLE_PANO_SOURCE,
        ),
        spec(
            "GSpherical",
            "Spherical",
            None,
            "boolean",
            "video_metadata",
            True,
            "none",
            GOOGLE_SPHERICAL_SOURCE,
        ),
        spec(
            "GSpherical",
            "Stitched",
            None,
            "boolean",
            "video_metadata",
            True,
            "none",
            GOOGLE_SPHERICAL_SOURCE,
        ),
        spec(
            "GSpherical",
            "ProjectionType",
            None,
            "string",
            "video_metadata",
            False,
            "none",
            GOOGLE_SPHERICAL_SOURCE,
        ),
        spec(
            "GSpherical",
            "StereoMode",
            None,
            "string",
            "video_metadata",
            False,
            "none",
            GOOGLE_SPHERICAL_SOURCE,
        ),
        spec(
            "GSpherical",
            "SourceCount",
            None,
            "integer",
            "video_metadata",
            True,
            "none",
            GOOGLE_SPHERICAL_SOURCE,
        ),
        spec(
            "GSpherical",
            "Timestamp",
            "TimeStamp",
            "integer",
            "time_metadata",
            True,
            "none",
            GOOGLE_SPHERICAL_SOURCE,
        ),
        spec(
            "GSpherical",
            "FullPanoWidthPixels",
            None,
            "integer",
            "video_metadata",
            True,
            "none",
            GOOGLE_SPHERICAL_SOURCE,
        ),
        spec(
            "GSpherical",
            "FullPanoHeightPixels",
            None,
            "integer",
            "video_metadata",
            True,
            "none",
            GOOGLE_SPHERICAL_SOURCE,
        ),
        spec(
            "GDepth", "Format", None, "string", "depth_metadata", True, "none", GOOGLE_DEPTH_SOURCE
        ),
        spec("GDepth", "Near", None, "real", "depth_metadata", True, "none", GOOGLE_DEPTH_SOURCE),
        spec("GDepth", "Far", None, "real", "depth_metadata", True, "none", GOOGLE_DEPTH_SOURCE),
        spec("GDepth", "Mime", None, "string", "depth_metadata", True, "none", GOOGLE_DEPTH_SOURCE),
        spec(
            "GDepth",
            "Data",
            "DepthImage",
            "binary",
            "depth_metadata",
            True,
            "base64_binary",
            GOOGLE_DEPTH_SOURCE,
        ),
        spec(
            "GDepth",
            "Confidence",
            None,
            "binary",
            "depth_metadata",
            True,
            "base64_binary",
            GOOGLE_DEPTH_SOURCE,
        ),
        spec(
            "GDepth",
            "ImageWidth",
            None,
            "real",
            "image_metadata",
            True,
            "none",
            GOOGLE_DEPTH_SOURCE,
        ),
        spec(
            "GDepth",
            "ImageHeight",
            None,
            "real",
            "image_metadata",
            True,
            "none",
            GOOGLE_DEPTH_SOURCE,
        ),
        spec(
            "GFocus",
            "BlurAtInfinity",
            None,
            "real",
            "focus_metadata",
            True,
            "none",
            GOOGLE_FOCUS_SOURCE,
        ),
        spec(
            "GFocus",
            "FocalDistance",
            None,
            "real",
            "focus_metadata",
            True,
            "none",
            GOOGLE_FOCUS_SOURCE,
        ),
        spec(
            "GFocus",
            "FocalPointX",
            None,
            "real",
            "focus_metadata",
            True,
            "none",
            GOOGLE_FOCUS_SOURCE,
        ),
        spec(
            "GFocus",
            "FocalPointY",
            None,
            "real",
            "focus_metadata",
            True,
            "none",
            GOOGLE_FOCUS_SOURCE,
        ),
        spec(
            "GCamera",
            "BurstID",
            None,
            "string",
            "camera_metadata",
            False,
            "none",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "BurstPrimary",
            None,
            "string",
            "camera_metadata",
            False,
            "none",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "PortraitRequest",
            None,
            "binary",
            "camera_metadata",
            True,
            "hdrp_text",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "PortraitVersion",
            None,
            "string",
            "camera_metadata",
            False,
            "none",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "SpecialTypeID",
            None,
            "string",
            "camera_metadata",
            False,
            "none",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "hdrp_makernote",
            "HDRPMakerNote",
            "binary",
            "camera_metadata",
            True,
            "hdrp_text",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "MicroVideo",
            None,
            "integer",
            "camera_metadata",
            True,
            "none",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "MicroVideoVersion",
            None,
            "integer",
            "camera_metadata",
            True,
            "none",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "MicroVideoOffset",
            None,
            "integer",
            "camera_metadata",
            True,
            "none",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "MicroVideoPresentationTimestampUs",
            None,
            "integer",
            "camera_metadata",
            True,
            "none",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "shot_log_data",
            "ShotLogData",
            "binary",
            "protobuf_metadata",
            True,
            "hdrp_protobuf",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "HdrPlusMakernote",
            "HDRPlusMakerNote",
            "binary",
            "protobuf_metadata",
            True,
            "hdrp_protobuf",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "MotionPhoto",
            None,
            "integer",
            "camera_metadata",
            True,
            "none",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "MotionPhotoVersion",
            None,
            "integer",
            "camera_metadata",
            True,
            "none",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCamera",
            "MotionPhotoPresentationTimestampUs",
            None,
            "integer",
            "camera_metadata",
            True,
            "none",
            GOOGLE_CAMERA_SOURCE,
        ),
        spec(
            "GCreations",
            "CameraBurstID",
            None,
            "string",
            "camera_metadata",
            False,
            "none",
            GOOGLE_CREATIONS_SOURCE,
        ),
        spec(
            "GCreations",
            "Type",
            None,
            "string",
            "camera_metadata",
            False,
            "none",
            GOOGLE_CREATIONS_SOURCE,
        ),
        spec(
            "Device",
            "Mime",
            None,
            "string",
            "trailer_metadata",
            False,
            "trailer_mime",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "Length",
            None,
            "integer",
            "trailer_metadata",
            True,
            "trailer_length",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "Padding",
            None,
            "integer",
            "trailer_metadata",
            True,
            "trailer_padding",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "DataURI",
            None,
            "string",
            "trailer_metadata",
            False,
            "trailer_uri",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "DepthURI",
            None,
            "string",
            "depth_metadata",
            False,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "ConfidenceURI",
            None,
            "string",
            "depth_metadata",
            False,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec("Device", "Near", None, "real", "depth_metadata", True, "none", GOOGLE_DEVICE_SOURCE),
        spec("Device", "Far", None, "real", "depth_metadata", True, "none", GOOGLE_DEVICE_SOURCE),
        spec(
            "Device",
            "FocalTableEntryCount",
            None,
            "integer",
            "pixel_camera_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "FocalLengthX",
            None,
            "real",
            "pixel_camera_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "FocalLengthY",
            None,
            "real",
            "pixel_camera_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "ImageHeight",
            None,
            "integer",
            "pixel_camera_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "ImageWidth",
            None,
            "integer",
            "pixel_camera_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "PixelAspectRatio",
            None,
            "real",
            "pixel_camera_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "PrincipalPointX",
            None,
            "real",
            "pixel_camera_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "PrincipalPointY",
            None,
            "real",
            "pixel_camera_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "Skew",
            None,
            "real",
            "pixel_camera_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "Metric",
            None,
            "boolean",
            "pixel_camera_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "PositionX",
            None,
            "real",
            "pixel_camera_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "PositionY",
            None,
            "real",
            "pixel_camera_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "PositionZ",
            None,
            "real",
            "pixel_camera_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "Device",
            "Timestamp",
            "TimeStamp",
            "integer",
            "time_metadata",
            True,
            "none",
            GOOGLE_DEVICE_SOURCE,
        ),
        spec(
            "GContainer",
            "Directory",
            "ContainerDirectory",
            "string",
            "trailer_metadata",
            False,
            "none",
            GOOGLE_CONTAINER_SOURCE,
        ),
        spec(
            "GItem",
            "Mime",
            None,
            "string",
            "trailer_metadata",
            False,
            "trailer_mime",
            GOOGLE_CONTAINER_SOURCE,
        ),
        spec(
            "GItem",
            "Semantic",
            None,
            "string",
            "trailer_metadata",
            False,
            "none",
            GOOGLE_CONTAINER_SOURCE,
        ),
        spec(
            "GItem",
            "Length",
            None,
            "integer",
            "trailer_metadata",
            True,
            "trailer_length",
            GOOGLE_CONTAINER_SOURCE,
        ),
        spec(
            "GItem",
            "Label",
            None,
            "string",
            "trailer_metadata",
            False,
            "none",
            GOOGLE_CONTAINER_SOURCE,
        ),
        spec(
            "GItem",
            "Padding",
            None,
            "integer",
            "trailer_metadata",
            True,
            "trailer_padding",
            GOOGLE_CONTAINER_SOURCE,
        ),
        spec(
            "GItem",
            "URI",
            None,
            "string",
            "trailer_metadata",
            False,
            "trailer_uri",
            GOOGLE_CONTAINER_SOURCE,
        ),
    )
)
