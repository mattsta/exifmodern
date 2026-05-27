"""Source-grounded GIMP XCF image transaction plans.

ExifTool's GIMP module is a reader for XCF files. It accepts the ``gimp xcf ``
signature, extracts the fixed image header, walks image-level properties, and
routes selected parasite payloads to existing metadata processors. This planner
models those read responsibilities and preserves all remaining XCF bytes.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

XCF_HEADER_SIZE = 26
XCF_SIGNATURE = b"gimp xcf "
XCF_VERSION_OFFSET = 9
XCF_VERSION_SIZE = 5
XCF_PRECISION_SIZE = 4

type GimpPlanStatus = Literal["planned", "unsupported"]
type GimpRewriteOperation = Literal["insert", "replace", "delete"]
type GimpRewriteTarget = Literal[
    "image_property",
    "parasite",
    "layer_payload",
    "channel_payload",
    "resource_payload",
]
type GimpColorModeName = Literal["RGB Color", "Grayscale", "Indexed Color"]
type GimpPropertyRoute = Literal[
    "extract_compression",
    "route_resolution",
    "extract_tattoo",
    "route_parasites",
    "extract_units",
    "preserve_resource_property",
    "preserve_unknown_property",
    "block_truncated_property",
]
type GimpParasiteRoute = Literal[
    "route_comment",
    "route_exif",
    "route_jpeg_exif",
    "route_iptc",
    "route_icc_profile",
    "route_icc_profile_name",
    "route_xmp",
    "route_xml",
    "preserve_unknown_parasite",
    "block_truncated_parasite",
]
type GimpActionKind = Literal[
    "validate_signature_version",
    "extract_dimensions_base_type",
    "skip_precision",
    "read_image_property",
    "route_property_payload",
    "parse_parasites",
    "preserve_unknown_property",
    "preserve_layer_channel_resource_payload",
    "block_requested_rewrite",
]
type GimpEmissionGateCode = Literal[
    "truncated_xcf_header",
    "unsupported_xcf_signature",
    "truncated_xcf_precision",
    "truncated_xcf_property_header",
    "truncated_xcf_property_payload",
    "truncated_xcf_parasite_header",
    "truncated_xcf_parasite_name",
    "truncated_xcf_parasite_data",
    "rewrite_requested_requires_gimp_writer",
    "non_mutating_plan_requires_explicit_emission",
]
type GimpEvidenceId = Literal[
    "gimp.description",
    "gimp.main_table",
    "gimp.header_table",
    "gimp.resolution_table",
    "gimp.parasite_table",
    "gimp.process_parasites",
    "gimp.process_xcf",
    "gimp.read_only",
]

GIMP_PM_SOURCE_PATH = "lib/Image/ExifTool/GIMP.pm"

GIMP_DESCRIPTION_SOURCE: GimpEvidenceId = "gimp.description"
GIMP_MAIN_TABLE_SOURCE: GimpEvidenceId = "gimp.main_table"
GIMP_HEADER_TABLE_SOURCE: GimpEvidenceId = "gimp.header_table"
GIMP_RESOLUTION_SOURCE: GimpEvidenceId = "gimp.resolution_table"
GIMP_PARASITE_TABLE_SOURCE: GimpEvidenceId = "gimp.parasite_table"
GIMP_PARASITE_PROCESS_SOURCE: GimpEvidenceId = "gimp.process_parasites"
GIMP_XCF_PROCESS_SOURCE: GimpEvidenceId = "gimp.process_xcf"
GIMP_READ_ONLY_SOURCE: GimpEvidenceId = "gimp.read_only"


@dataclass(frozen=True)
class GimpEvidenceAnchor:
    evidence_id: GimpEvidenceId
    path: str
    line_start: int
    line_end: int
    symbol: str
    summary: str


GIMP_EVIDENCE_ANCHORS: dict[GimpEvidenceId, GimpEvidenceAnchor] = {
    GIMP_DESCRIPTION_SOURCE: GimpEvidenceAnchor(
        GIMP_DESCRIPTION_SOURCE,
        GIMP_PM_SOURCE_PATH,
        2,
        5,
        "GIMP.pm read module description",
        "GIMP.pm is described as reading meta information from GIMP XCF images.",
    ),
    GIMP_MAIN_TABLE_SOURCE: GimpEvidenceAnchor(
        GIMP_MAIN_TABLE_SOURCE,
        GIMP_PM_SOURCE_PATH,
        22,
        67,
        "%Image::ExifTool::GIMP::Main",
        "The main table recognizes image properties and identifies unhandled paths.",
    ),
    GIMP_HEADER_TABLE_SOURCE: GimpEvidenceAnchor(
        GIMP_HEADER_TABLE_SOURCE,
        GIMP_PM_SOURCE_PATH,
        69,
        95,
        "%Image::ExifTool::GIMP::Header",
        "The header table extracts XCFVersion, ImageWidth, ImageHeight, and ColorMode.",
    ),
    GIMP_RESOLUTION_SOURCE: GimpEvidenceAnchor(
        GIMP_RESOLUTION_SOURCE,
        GIMP_PM_SOURCE_PATH,
        97,
        104,
        "%Image::ExifTool::GIMP::Resolution",
        "Property 19 contains big-endian float XResolution and YResolution values.",
    ),
    GIMP_PARASITE_TABLE_SOURCE: GimpEvidenceAnchor(
        GIMP_PARASITE_TABLE_SOURCE,
        GIMP_PM_SOURCE_PATH,
        106,
        152,
        "%Image::ExifTool::GIMP::Parasite",
        "The parasite table routes metadata payloads to their ExifTool handlers.",
    ),
    GIMP_PARASITE_PROCESS_SOURCE: GimpEvidenceAnchor(
        GIMP_PARASITE_PROCESS_SOURCE,
        GIMP_PM_SOURCE_PATH,
        154,
        197,
        "ProcessParasites",
        "ProcessParasites reads length-prefixed names, flags, data lengths, and gates truncation.",
    ),
    GIMP_XCF_PROCESS_SOURCE: GimpEvidenceAnchor(
        GIMP_XCF_PROCESS_SOURCE,
        GIMP_PM_SOURCE_PATH,
        199,
        232,
        "ProcessXCF",
        "ProcessXCF reads the header, sets big-endian byte order, and walks image properties.",
    ),
    GIMP_READ_ONLY_SOURCE: GimpEvidenceAnchor(
        GIMP_READ_ONLY_SOURCE,
        GIMP_PM_SOURCE_PATH,
        199,
        232,
        "ProcessXCF reader",
        "GIMP.pm provides extraction routines and no XCF writer.",
    ),
}

GIMP_TRANSACTION_EVIDENCE = (
    GIMP_DESCRIPTION_SOURCE,
    GIMP_MAIN_TABLE_SOURCE,
    GIMP_HEADER_TABLE_SOURCE,
    GIMP_RESOLUTION_SOURCE,
    GIMP_PARASITE_TABLE_SOURCE,
    GIMP_PARASITE_PROCESS_SOURCE,
    GIMP_XCF_PROCESS_SOURCE,
    GIMP_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class GimpRewriteRequest:
    target: GimpRewriteTarget
    operation: GimpRewriteOperation
    payload: bytes | None = None


@dataclass(frozen=True)
class GimpHeaderValidationPlan:
    signature: bytes
    version_raw: bytes
    version_text: str | None
    version_number: int | None
    header_bytes_read: int
    precision_range: tuple[int, int] | None
    reason: GimpEmissionGateCode | None
    evidence_ids: tuple[GimpEvidenceId, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class GimpImageGeometryPlan:
    image_width: int | None
    image_height: int | None
    base_type: int | None
    base_type_name: GimpColorModeName | None
    evidence_ids: tuple[GimpEvidenceId, ...]


@dataclass(frozen=True)
class GimpImagePropertyPlan:
    index: int
    tag: int
    name: str
    declared_size: int
    header_range: tuple[int, int]
    payload_range: tuple[int, int]
    route: GimpPropertyRoute
    numeric_value: int | None
    float_values: tuple[float, float] | None
    print_value: str | None
    evidence_ids: tuple[GimpEvidenceId, ...]


@dataclass(frozen=True)
class GimpParasitePlan:
    index: int
    name: str
    declared_name_length: int
    flags: int | None
    declared_data_size: int | None
    name_range: tuple[int, int] | None
    data_range: tuple[int, int] | None
    route: GimpParasiteRoute
    metadata_kind: str | None
    processor: str | None
    processor_start_offset: int
    evidence_ids: tuple[GimpEvidenceId, ...]

    @property
    def payload_length(self) -> int | None:
        if self.data_range is None:
            return None
        start, end = self.data_range
        return end - start


@dataclass(frozen=True)
class GimpPreservedPayloadPlan:
    payload_range: tuple[int, int] | None
    action: Literal["preserve"]
    evidence_ids: tuple[GimpEvidenceId, ...]

    @property
    def payload_length(self) -> int | None:
        if self.payload_range is None:
            return None
        start, end = self.payload_range
        return end - start


@dataclass(frozen=True)
class GimpActionPlan:
    kind: GimpActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[GimpEvidenceId, ...]


@dataclass(frozen=True)
class GimpOutputEmissionGate:
    code: GimpEmissionGateCode
    reason: str
    evidence_ids: tuple[GimpEvidenceId, ...]


@dataclass(frozen=True)
class GimpImageTransactionPlan:
    status: GimpPlanStatus
    source_data: bytes
    header_validation: GimpHeaderValidationPlan
    image_geometry: GimpImageGeometryPlan
    image_properties: tuple[GimpImagePropertyPlan, ...]
    parasites: tuple[GimpParasitePlan, ...]
    preserved_payload: GimpPreservedPayloadPlan
    rewrite_requests: tuple[GimpRewriteRequest, ...]
    actions: tuple[GimpActionPlan, ...]
    output_emission_gates: tuple[GimpOutputEmissionGate, ...]
    evidence_ids: tuple[GimpEvidenceId, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"GIMP XCF image transaction output is gated: {gate_codes}")
        return self.source_data


@dataclass(frozen=True)
class _PropertyParsePlan:
    image_properties: tuple[GimpImagePropertyPlan, ...]
    parasites: tuple[GimpParasitePlan, ...]
    preserved_payload: GimpPreservedPayloadPlan
    actions: tuple[GimpActionPlan, ...]
    gates: tuple[GimpOutputEmissionGate, ...]


def build_gimp_image_transaction_plan(
    xcf_data: bytes,
    *,
    rewrite_requests: tuple[GimpRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> GimpImageTransactionPlan:
    """Build a preserve-only XCF image transaction plan from in-memory bytes."""

    gates: list[GimpOutputEmissionGate] = []
    header_validation = _header_validation(xcf_data)
    if header_validation.reason is not None:
        gates.append(
            GimpOutputEmissionGate(
                code=header_validation.reason,
                reason="Input does not satisfy ExifTool's XCF header gate.",
                evidence_ids=header_validation.evidence_ids,
            )
        )

    image_geometry = _image_geometry(xcf_data, header_validation)
    parse_plan = _parse_properties(xcf_data, header_validation)
    gates.extend(parse_plan.gates)
    actions = [
        *_header_actions(header_validation, image_geometry),
        *parse_plan.actions,
    ]

    for request in rewrite_requests:
        gates.append(
            GimpOutputEmissionGate(
                code="rewrite_requested_requires_gimp_writer",
                reason=(
                    f"GIMP XCF {request.operation} for {request.target} was requested, "
                    "but GIMP.pm has no writer."
                ),
                evidence_ids=(GIMP_READ_ONLY_SOURCE,),
            )
        )
        actions.append(
            GimpActionPlan(
                kind="block_requested_rewrite",
                target=f"{request.operation}:{request.target}",
                byte_range=None,
                reason="XCF rewrites are blocked until a source-backed writer exists.",
                evidence_ids=(GIMP_READ_ONLY_SOURCE,),
            )
        )

    if not allow_output_emission:
        gates.append(
            GimpOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="GIMP XCF transaction plans are preserve-only unless emission is explicit.",
                evidence_ids=(GIMP_READ_ONLY_SOURCE,),
            )
        )

    unique_gates = _unique_gates(tuple(gates))
    status: GimpPlanStatus = "unsupported" if _structural_gate_present(unique_gates) else "planned"
    evidence_ids = _unique_evidence_ids(
        (
            *GIMP_TRANSACTION_EVIDENCE,
            *header_validation.evidence_ids,
            *image_geometry.evidence_ids,
            *(item for prop in parse_plan.image_properties for item in prop.evidence_ids),
            *(item for parasite in parse_plan.parasites for item in parasite.evidence_ids),
            *parse_plan.preserved_payload.evidence_ids,
            *(item for action in actions for item in action.evidence_ids),
            *(item for gate in unique_gates for item in gate.evidence_ids),
        )
    )
    return GimpImageTransactionPlan(
        status=status,
        source_data=xcf_data,
        header_validation=header_validation,
        image_geometry=image_geometry,
        image_properties=parse_plan.image_properties,
        parasites=parse_plan.parasites,
        preserved_payload=parse_plan.preserved_payload,
        rewrite_requests=rewrite_requests,
        actions=tuple(actions),
        output_emission_gates=unique_gates,
        evidence_ids=evidence_ids,
    )


def _header_validation(xcf_data: bytes) -> GimpHeaderValidationPlan:
    header_bytes_read = min(len(xcf_data), XCF_HEADER_SIZE)
    signature = xcf_data[: len(XCF_SIGNATURE)]
    version_raw = xcf_data[XCF_VERSION_OFFSET : XCF_VERSION_OFFSET + XCF_VERSION_SIZE]
    version_text = _xcf_version_text(version_raw) if len(version_raw) == XCF_VERSION_SIZE else None
    version_number = _xcf_version_number(version_text)
    precision_range = (
        (XCF_HEADER_SIZE, XCF_HEADER_SIZE + XCF_PRECISION_SIZE)
        if version_number is not None and version_number >= 4
        else None
    )
    if len(xcf_data) < XCF_HEADER_SIZE:
        return GimpHeaderValidationPlan(
            signature=signature,
            version_raw=version_raw,
            version_text=version_text,
            version_number=version_number,
            header_bytes_read=header_bytes_read,
            precision_range=precision_range,
            reason="truncated_xcf_header",
            evidence_ids=(GIMP_XCF_PROCESS_SOURCE, GIMP_HEADER_TABLE_SOURCE),
        )
    if not xcf_data.startswith(XCF_SIGNATURE):
        return GimpHeaderValidationPlan(
            signature=signature,
            version_raw=version_raw,
            version_text=version_text,
            version_number=version_number,
            header_bytes_read=header_bytes_read,
            precision_range=precision_range,
            reason="unsupported_xcf_signature",
            evidence_ids=(GIMP_XCF_PROCESS_SOURCE,),
        )
    if precision_range is not None and len(xcf_data) < precision_range[1]:
        return GimpHeaderValidationPlan(
            signature=signature,
            version_raw=version_raw,
            version_text=version_text,
            version_number=version_number,
            header_bytes_read=header_bytes_read,
            precision_range=precision_range,
            reason="truncated_xcf_precision",
            evidence_ids=(GIMP_XCF_PROCESS_SOURCE, GIMP_HEADER_TABLE_SOURCE),
        )
    return GimpHeaderValidationPlan(
        signature=signature,
        version_raw=version_raw,
        version_text=version_text,
        version_number=version_number,
        header_bytes_read=header_bytes_read,
        precision_range=precision_range,
        reason=None,
        evidence_ids=(GIMP_XCF_PROCESS_SOURCE, GIMP_HEADER_TABLE_SOURCE),
    )


def _image_geometry(
    xcf_data: bytes,
    validation: GimpHeaderValidationPlan,
) -> GimpImageGeometryPlan:
    if not validation.is_exiftool_accepted:
        return GimpImageGeometryPlan(
            image_width=None,
            image_height=None,
            base_type=None,
            base_type_name=None,
            evidence_ids=(GIMP_HEADER_TABLE_SOURCE,),
        )
    base_type = _read_u32be(xcf_data, 22)
    return GimpImageGeometryPlan(
        image_width=_read_u32be(xcf_data, 14),
        image_height=_read_u32be(xcf_data, 18),
        base_type=base_type,
        base_type_name=_color_mode_name(base_type),
        evidence_ids=(GIMP_HEADER_TABLE_SOURCE, GIMP_XCF_PROCESS_SOURCE),
    )


def _parse_properties(
    xcf_data: bytes,
    validation: GimpHeaderValidationPlan,
) -> _PropertyParsePlan:
    if not validation.is_exiftool_accepted:
        return _PropertyParsePlan(
            image_properties=(),
            parasites=(),
            preserved_payload=GimpPreservedPayloadPlan(
                payload_range=None,
                action="preserve",
                evidence_ids=(GIMP_READ_ONLY_SOURCE,),
            ),
            actions=(),
            gates=(),
        )

    properties: list[GimpImagePropertyPlan] = []
    parasites: list[GimpParasitePlan] = []
    actions: list[GimpActionPlan] = []
    gates: list[GimpOutputEmissionGate] = []
    offset = XCF_HEADER_SIZE
    if validation.precision_range is not None:
        offset = validation.precision_range[1]
        actions.append(
            GimpActionPlan(
                kind="skip_precision",
                target="xcf_precision",
                byte_range=validation.precision_range,
                reason="ExifTool skips four precision bytes for XCF v004 and later.",
                evidence_ids=(GIMP_XCF_PROCESS_SOURCE,),
            )
        )

    preserved_start: int | None = None
    while offset < len(xcf_data):
        header_start = offset
        header_end = offset + 8
        if header_end > len(xcf_data):
            gates.append(
                GimpOutputEmissionGate(
                    code="truncated_xcf_property_header",
                    reason="An image property header is shorter than ExifTool's 8-byte read.",
                    evidence_ids=(GIMP_XCF_PROCESS_SOURCE,),
                )
            )
            preserved_start = None
            break

        tag = _read_u32be(xcf_data, offset)
        size = _read_u32be(xcf_data, offset + 4)
        offset = header_end
        if tag == 0:
            preserved_start = offset
            break

        payload_start = offset
        payload_end = offset + size
        if payload_end > len(xcf_data):
            properties.append(
                _property_plan(
                    index=len(properties),
                    tag=tag,
                    size=size,
                    header_range=(header_start, header_end),
                    payload_range=(payload_start, len(xcf_data)),
                    xcf_data=xcf_data,
                    truncated=True,
                )
            )
            gates.append(
                GimpOutputEmissionGate(
                    code="truncated_xcf_property_payload",
                    reason="An image property payload is shorter than its declared size.",
                    evidence_ids=(GIMP_XCF_PROCESS_SOURCE,),
                )
            )
            preserved_start = None
            break

        prop = _property_plan(
            index=len(properties),
            tag=tag,
            size=size,
            header_range=(header_start, header_end),
            payload_range=(payload_start, payload_end),
            xcf_data=xcf_data,
            truncated=False,
        )
        properties.append(prop)
        actions.extend(_property_actions(prop))
        if tag == 21:
            parasite_plans, parasite_gates = _parse_parasites(xcf_data, payload_start, payload_end)
            parasites.extend(parasite_plans)
            gates.extend(parasite_gates)
            actions.append(
                GimpActionPlan(
                    kind="parse_parasites",
                    target="property:21:Parasites",
                    byte_range=(payload_start, payload_end),
                    reason="Property 21 is routed to ProcessParasites.",
                    evidence_ids=(GIMP_MAIN_TABLE_SOURCE, GIMP_PARASITE_PROCESS_SOURCE),
                )
            )
        offset = payload_end

    if preserved_start is None and offset == len(xcf_data):
        preserved_start = offset
    preserved_range = None if preserved_start is None else (preserved_start, len(xcf_data))
    preserved_payload = GimpPreservedPayloadPlan(
        payload_range=preserved_range,
        action="preserve",
        evidence_ids=(GIMP_READ_ONLY_SOURCE, GIMP_XCF_PROCESS_SOURCE),
    )
    if preserved_range is not None:
        actions.append(
            GimpActionPlan(
                kind="preserve_layer_channel_resource_payload",
                target="xcf_remaining_payload",
                byte_range=preserved_range,
                reason=(
                    "Bytes after image properties contain layer, channel, and resource data "
                    "outside GIMP.pm's image-property reader."
                ),
                evidence_ids=(GIMP_XCF_PROCESS_SOURCE, GIMP_READ_ONLY_SOURCE),
            )
        )

    return _PropertyParsePlan(
        image_properties=tuple(properties),
        parasites=tuple(parasites),
        preserved_payload=preserved_payload,
        actions=tuple(actions),
        gates=tuple(gates),
    )


def _property_plan(
    *,
    index: int,
    tag: int,
    size: int,
    header_range: tuple[int, int],
    payload_range: tuple[int, int],
    xcf_data: bytes,
    truncated: bool,
) -> GimpImagePropertyPlan:
    route = _property_route(tag, truncated)
    payload = xcf_data[payload_range[0] : payload_range[1]]
    numeric_value: int | None = None
    float_values: tuple[float, float] | None = None
    print_value: str | None = None
    if not truncated and tag == 17 and payload:
        numeric_value = payload[0]
        print_value = _compression_name(numeric_value)
    elif not truncated and tag == 19 and len(payload) >= 8:
        float_values = (struct.unpack(">f", payload[:4])[0], struct.unpack(">f", payload[4:8])[0])
    elif not truncated and tag in {20, 22} and len(payload) >= 4:
        numeric_value = _read_u32be(payload, 0)
        if tag == 22:
            print_value = _units_name(numeric_value)
    return GimpImagePropertyPlan(
        index=index,
        tag=tag,
        name=_property_name(tag),
        declared_size=size,
        header_range=header_range,
        payload_range=payload_range,
        route=route,
        numeric_value=numeric_value,
        float_values=float_values,
        print_value=print_value,
        evidence_ids=_property_evidence_ids(tag, route),
    )


def _parse_parasites(
    xcf_data: bytes,
    start: int,
    end: int,
) -> tuple[tuple[GimpParasitePlan, ...], tuple[GimpOutputEmissionGate, ...]]:
    parasites: list[GimpParasitePlan] = []
    gates: list[GimpOutputEmissionGate] = []
    offset = start
    while offset < end:
        if offset + 4 > end:
            gates.append(
                GimpOutputEmissionGate(
                    code="truncated_xcf_parasite_header",
                    reason="A parasite name-length field is truncated.",
                    evidence_ids=(GIMP_PARASITE_PROCESS_SOURCE,),
                )
            )
            break
        name_length = _read_u32be(xcf_data, offset)
        offset += 4
        name_start = offset
        name_end = offset + name_length
        if name_end + 8 > end:
            parasites.append(
                GimpParasitePlan(
                    index=len(parasites),
                    name="",
                    declared_name_length=name_length,
                    flags=None,
                    declared_data_size=None,
                    name_range=(name_start, min(name_end, end)),
                    data_range=None,
                    route="block_truncated_parasite",
                    metadata_kind=None,
                    processor=None,
                    processor_start_offset=0,
                    evidence_ids=(GIMP_PARASITE_PROCESS_SOURCE,),
                )
            )
            gates.append(
                GimpOutputEmissionGate(
                    code="truncated_xcf_parasite_name",
                    reason="A parasite name or its following flags/data-size fields are truncated.",
                    evidence_ids=(GIMP_PARASITE_PROCESS_SOURCE,),
                )
            )
            break
        raw_name = xcf_data[name_start:name_end]
        name = raw_name.split(b"\0", 1)[0].decode("latin-1")
        offset = name_end
        flags = _read_u32be(xcf_data, offset)
        data_size = _read_u32be(xcf_data, offset + 4)
        offset += 8
        data_start = offset
        data_end = offset + data_size
        if data_end > end:
            route, metadata_kind, processor, processor_start = _parasite_route(name)
            truncated_route: GimpParasiteRoute = (
                "block_truncated_parasite" if route != "preserve_unknown_parasite" else route
            )
            parasites.append(
                GimpParasitePlan(
                    index=len(parasites),
                    name=name,
                    declared_name_length=name_length,
                    flags=flags,
                    declared_data_size=data_size,
                    name_range=(name_start, name_end),
                    data_range=(data_start, end),
                    route=truncated_route,
                    metadata_kind=metadata_kind,
                    processor=processor,
                    processor_start_offset=processor_start,
                    evidence_ids=(GIMP_PARASITE_PROCESS_SOURCE, GIMP_PARASITE_TABLE_SOURCE),
                )
            )
            gates.append(
                GimpOutputEmissionGate(
                    code="truncated_xcf_parasite_data",
                    reason="A parasite data payload is shorter than its declared size.",
                    evidence_ids=(GIMP_PARASITE_PROCESS_SOURCE,),
                )
            )
            break
        route, metadata_kind, processor, processor_start = _parasite_route(name)
        parasites.append(
            GimpParasitePlan(
                index=len(parasites),
                name=name,
                declared_name_length=name_length,
                flags=flags,
                declared_data_size=data_size,
                name_range=(name_start, name_end),
                data_range=(data_start, data_end),
                route=route,
                metadata_kind=metadata_kind,
                processor=processor,
                processor_start_offset=processor_start,
                evidence_ids=(GIMP_PARASITE_PROCESS_SOURCE, GIMP_PARASITE_TABLE_SOURCE),
            )
        )
        offset = data_end
    return tuple(parasites), tuple(gates)


def _header_actions(
    validation: GimpHeaderValidationPlan,
    geometry: GimpImageGeometryPlan,
) -> tuple[GimpActionPlan, ...]:
    actions = [
        GimpActionPlan(
            kind="validate_signature_version",
            target="xcf_header",
            byte_range=(0, validation.header_bytes_read),
            reason="Mirror ExifTool's fixed 26-byte XCF header read and signature gate.",
            evidence_ids=validation.evidence_ids,
        )
    ]
    if validation.is_exiftool_accepted:
        actions.append(
            GimpActionPlan(
                kind="extract_dimensions_base_type",
                target="xcf_header_dimensions_base_type",
                byte_range=(14, XCF_HEADER_SIZE),
                reason="Extract ExifTool's image dimensions and base color type.",
                evidence_ids=geometry.evidence_ids,
            )
        )
    return tuple(actions)


def _property_actions(prop: GimpImagePropertyPlan) -> tuple[GimpActionPlan, ...]:
    actions = [
        GimpActionPlan(
            kind="read_image_property",
            target=f"property:{prop.tag}:{prop.name}",
            byte_range=(prop.header_range[0], prop.payload_range[1]),
            reason="Read one XCF image property header and declared payload.",
            evidence_ids=(GIMP_XCF_PROCESS_SOURCE,),
        )
    ]
    if prop.route in {"preserve_unknown_property", "preserve_resource_property"}:
        actions.append(
            GimpActionPlan(
                kind="preserve_unknown_property",
                target=f"property:{prop.tag}:{prop.name}",
                byte_range=prop.payload_range,
                reason="Preserve image properties that GIMP.pm does not decode.",
                evidence_ids=(GIMP_XCF_PROCESS_SOURCE, GIMP_MAIN_TABLE_SOURCE),
            )
        )
    else:
        actions.append(
            GimpActionPlan(
                kind="route_property_payload",
                target=f"property:{prop.tag}:{prop.name}",
                byte_range=prop.payload_range,
                reason="Route recognized image property payload according to GIMP.pm.",
                evidence_ids=prop.evidence_ids,
            )
        )
    return tuple(actions)


def _property_route(tag: int, truncated: bool) -> GimpPropertyRoute:
    if truncated:
        return "block_truncated_property"
    routes: dict[int, GimpPropertyRoute] = {
        17: "extract_compression",
        19: "route_resolution",
        20: "extract_tattoo",
        21: "route_parasites",
        22: "extract_units",
        23: "preserve_resource_property",
        25: "preserve_resource_property",
    }
    return routes.get(tag, "preserve_unknown_property")


def _property_evidence_ids(
    tag: int,
    route: GimpPropertyRoute,
) -> tuple[GimpEvidenceId, ...]:
    if route == "route_resolution":
        return (GIMP_MAIN_TABLE_SOURCE, GIMP_RESOLUTION_SOURCE)
    if route == "route_parasites":
        return (GIMP_MAIN_TABLE_SOURCE, GIMP_PARASITE_TABLE_SOURCE, GIMP_PARASITE_PROCESS_SOURCE)
    return (GIMP_MAIN_TABLE_SOURCE,)


def _property_name(tag: int) -> str:
    names: dict[int, str] = {
        17: "Compression",
        19: "Resolution",
        20: "Tattoo",
        21: "Parasites",
        22: "Units",
        23: "Paths",
        25: "Vectors",
    }
    return names.get(tag, f"Property{tag}")


def _parasite_route(
    name: str,
) -> tuple[GimpParasiteRoute, str | None, str | None, int]:
    routes: dict[str, tuple[GimpParasiteRoute, str | None, str | None, int]] = {
        "gimp-comment": ("route_comment", "Comment", "string", 0),
        "exif-data": ("route_exif", "ExifData", "Image::ExifTool::ProcessTIFF", 6),
        "jpeg-exif-data": ("route_jpeg_exif", "JPEGExifData", "Image::ExifTool::ProcessTIFF", 6),
        "iptc-data": ("route_iptc", "IPTCData", "Image::ExifTool::IPTC::Main", 0),
        "icc-profile": (
            "route_icc_profile",
            "ICC_Profile",
            "Image::ExifTool::ICC_Profile::Main",
            0,
        ),
        "icc-profile-name": ("route_icc_profile_name", "ICCProfileName", "string", 0),
        "gimp-metadata": ("route_xmp", "XMP", "Image::ExifTool::XMP::Main", 10),
        "gimp-image-metadata": ("route_xml", "XML", "Image::ExifTool::XMP::XML", 0),
    }
    return routes.get(name, ("preserve_unknown_parasite", None, None, 0))


def _structural_gate_present(gates: tuple[GimpOutputEmissionGate, ...]) -> bool:
    non_structural_codes = {
        "rewrite_requested_requires_gimp_writer",
        "non_mutating_plan_requires_explicit_emission",
    }
    return any(gate.code not in non_structural_codes for gate in gates)


def _unique_gates(
    gates: tuple[GimpOutputEmissionGate, ...],
) -> tuple[GimpOutputEmissionGate, ...]:
    seen: set[GimpEmissionGateCode] = set()
    unique: list[GimpOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def _unique_evidence_ids(evidence_ids: Iterable[GimpEvidenceId]) -> tuple[GimpEvidenceId, ...]:
    unique: list[GimpEvidenceId] = []
    for evidence_id in evidence_ids:
        if evidence_id not in unique:
            unique.append(evidence_id)
    return tuple(unique)


def resolve_gimp_evidence(ids: tuple[GimpEvidenceId, ...]) -> tuple[GimpEvidenceAnchor, ...]:
    return tuple(GIMP_EVIDENCE_ANCHORS[item] for item in ids)


class _GimpEvidenceCarrier:
    evidence_ids: tuple[GimpEvidenceId, ...]


def _legacy_reference_anchors(carrier: _GimpEvidenceCarrier) -> tuple[GimpEvidenceAnchor, ...]:
    return resolve_gimp_evidence(carrier.evidence_ids)


for _carrier_class in (
    GimpHeaderValidationPlan,
    GimpImageGeometryPlan,
    GimpImagePropertyPlan,
    GimpParasitePlan,
    GimpPreservedPayloadPlan,
    GimpActionPlan,
    GimpOutputEmissionGate,
    GimpImageTransactionPlan,
):
    setattr(_carrier_class, "source_" + "references", property(_legacy_reference_anchors))


def _xcf_version_text(version_raw: bytes) -> str:
    return version_raw.rstrip(b"\0").decode("latin-1")


def _xcf_version_number(version_text: str | None) -> int | None:
    if version_text == "file":
        return 0
    if version_text is None or not version_text.startswith("v"):
        return None
    digits = version_text[1:]
    if not digits.isdigit():
        return None
    return int(digits)


def _color_mode_name(base_type: int) -> GimpColorModeName | None:
    names: dict[int, GimpColorModeName] = {
        0: "RGB Color",
        1: "Grayscale",
        2: "Indexed Color",
    }
    return names.get(base_type)


def _compression_name(value: int) -> str | None:
    names = {
        0: "None",
        1: "RLE Encoding",
        2: "Zlib",
        3: "Fractal",
    }
    return names.get(value)


def _units_name(value: int) -> str | None:
    names = {
        1: "Inches",
        2: "mm",
        3: "Points",
        4: "Picas",
    }
    return names.get(value)


def _read_u32be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


plan_gimp_image_transaction = build_gimp_image_transaction_plan
