"""Source-grounded XISF metadata transaction plans.

ExifTool's XISF module is a reader. It validates the XISF0100 signature, reads a
little-endian XML header length at offset 8, parses that XML through the XMP
reader with XISF-specific property attribute handling, derives dimensions from
ImageGeometry, and has no XISF writer. This planner mirrors those responsibilities
without adding mutation behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from xml.etree import ElementTree

XISF_SIGNATURE = b"XISF0100"
XISF_PREAMBLE_SIZE = 16
XISF_XML_LENGTH_OFFSET = 8
XISF_PM_SOURCE_PATH = "lib/Image/ExifTool/XISF.pm"

type XisfPlanStatus = Literal["planned", "unsupported"]
type XisfRewriteOperation = Literal["insert", "replace", "delete"]
type XisfRewriteTarget = Literal["xml_header", "image_attribute", "property", "image_payload"]
type XisfActionKind = Literal[
    "validate_signature_header",
    "extract_xml_header",
    "parse_xml_header",
    "route_image_attribute",
    "route_property",
    "derive_geometry_tags",
    "preserve_xml_header",
    "preserve_image_payload",
    "block_requested_rewrite",
]
type XisfEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_xisf_preamble",
    "unsupported_xisf_signature",
    "truncated_xisf_xml_header",
    "malformed_xisf_xml_header",
    "rewrite_requested_requires_xisf_writer",
]

XISF_DESCRIPTION_SOURCE = "xisf.description"
XISF_MAIN_TABLE_SOURCE = "xisf.main.table"
XISF_PROPERTY_ATTR_SOURCE = "xisf.property.attr"
XISF_PROCESS_GATE_SOURCE = "xisf.process.gate"
XISF_XML_PROCESS_SOURCE = "xisf.xml.process"
XISF_GEOMETRY_SOURCE = "xisf.geometry"
XISF_READ_ONLY_SOURCE = "xisf.read.only"

XISF_TRANSACTION_SOURCES = (
    XISF_DESCRIPTION_SOURCE,
    XISF_MAIN_TABLE_SOURCE,
    XISF_PROPERTY_ATTR_SOURCE,
    XISF_PROCESS_GATE_SOURCE,
    XISF_XML_PROCESS_SOURCE,
    XISF_GEOMETRY_SOURCE,
    XISF_READ_ONLY_SOURCE,
)

IMAGE_ATTRIBUTE_TAGS: dict[str, str] = {
    "geometry": "ImageGeometry",
    "sampleFormat": "ImageSampleFormat",
    "bounds": "ImageBounds",
    "imageType": "ImageType",
    "colorSpace": "ColorSpace",
    "location": "ImageLocation",
    "resolutionHorizontal": "XResolution",
    "resolutionVertical": "YResolution",
    "resolutionUnit": "ResolutionUnit",
    "ICCProfile": "ICC_Profile",
    "ICCProfileLocation": "ICCProfileLocation",
    "pixelStorage": "ImagePixelStorage",
    "offset": "ImagePixelOffset",
    "orientation": "Orientation",
    "id": "ImageID",
    "uuid": "UUID",
    "data": "ImageData",
}
IMAGE_ATTRIBUTE_SOURCE_KEYS: dict[str, str] = {
    "geometry": "ImageGeometry",
    "sampleFormat": "ImageSampleFormat",
    "bounds": "ImageBounds",
    "imageType": "ImageImageType",
    "colorSpace": "ImageColorSpace",
    "location": "ImageLocation",
    "resolutionHorizontal": "ImageResolutionHorizontal",
    "resolutionVertical": "ImageResolutionVertical",
    "resolutionUnit": "ImageResolutionUnit",
    "ICCProfile": "ImageICCProfile",
    "ICCProfileLocation": "ImageICCProfileLocation",
    "pixelStorage": "ImagePixelStorage",
    "offset": "ImageOffset",
    "orientation": "ImageOrientation",
    "id": "ImageId",
    "uuid": "ImageUuid",
    "data": "ImageData",
}
PROPERTY_RENAMES: dict[str, str] = {
    "CreationTime": "CreateDate",
    "OriginalCreationTime": "DateTimeOriginal",
}
IGNORED_XML_PROPERTIES = frozenset(("xisf", "Metadata", "Property"))


@dataclass(frozen=True)
class XisfRewriteRequest:
    target: XisfRewriteTarget
    operation: XisfRewriteOperation
    payload: bytes | None = None
    property_name: str | None = None


@dataclass(frozen=True)
class XisfOutputEmissionGate:
    code: XisfEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class XisfHeaderValidationPlan:
    signature: bytes
    declared_xml_header_length: int | None
    preamble_bytes_read: int
    xml_header_range: tuple[int, int] | None
    reason: XisfEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_exiftool_accepted(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class XisfXmlHeaderPlan:
    header_range: tuple[int, int] | None
    declared_length: int | None
    available_length: int
    xml_bytes: bytes
    root_name: str | None
    reason: XisfEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class XisfImageAttributePlan:
    image_index: int
    xml_attribute: str
    source_key: str
    routed_tag: str
    value: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class XisfPropertyPlan:
    xml_element: str
    raw_id: str
    routed_tag: str
    value: str | None
    type_name: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class XisfImageDescriptorPlan:
    image_attributes: tuple[XisfImageAttributePlan, ...]
    properties: tuple[XisfPropertyPlan, ...]
    image_geometry: str | None
    image_width: str | None
    image_height: str | None
    num_planes: str | None
    sample_format: str | None
    color_space: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class XisfPayloadPlan:
    payload_range: tuple[int, int] | None
    action: Literal["preserve"]
    evidence_ids: tuple[str, ...]

    @property
    def payload_length(self) -> int | None:
        if self.payload_range is None:
            return None
        start, end = self.payload_range
        return end - start


@dataclass(frozen=True)
class XisfActionPlan:
    kind: XisfActionKind
    target: str
    byte_range: tuple[int, int] | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class XisfMetadataTransactionPlan:
    status: XisfPlanStatus
    source_data: bytes
    header_validation: XisfHeaderValidationPlan
    xml_header: XisfXmlHeaderPlan
    image_descriptor: XisfImageDescriptorPlan
    image_payload: XisfPayloadPlan
    actions: tuple[XisfActionPlan, ...]
    output_emission_gates: tuple[XisfOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"XISF metadata transaction output is gated: {gate_codes}")
        return self.source_data


def build_xisf_metadata_transaction_plan(
    xisf_data: bytes,
    *,
    rewrite_requests: tuple[XisfRewriteRequest, ...] = (),
    allow_output_emission: bool = False,
) -> XisfMetadataTransactionPlan:
    """Build a preserve-only XISF metadata transaction plan from in-memory bytes."""

    gates: list[XisfOutputEmissionGate] = []
    header_validation = build_xisf_header_validation_plan(xisf_data)
    if header_validation.reason is not None:
        gates.append(
            XisfOutputEmissionGate(
                code=header_validation.reason,
                reason="Input does not satisfy ExifTool's XISF signature/header gate.",
                evidence_ids=header_validation.evidence_ids,
            )
        )

    xml_header = build_xisf_xml_header_plan(xisf_data, header_validation)
    if xml_header.reason is not None:
        gates.append(
            XisfOutputEmissionGate(
                code=xml_header.reason,
                reason="XISF XML header cannot be read and parsed with ExifTool-equivalent bounds.",
                evidence_ids=xml_header.evidence_ids,
            )
        )

    image_descriptor = build_xisf_image_descriptor_plan(xml_header)
    image_payload = build_xisf_payload_plan(xisf_data, header_validation, xml_header)
    actions = build_xisf_actions(
        header_validation,
        xml_header,
        image_descriptor,
        image_payload,
        rewrite_requests,
    )
    if rewrite_requests:
        gates.append(
            XisfOutputEmissionGate(
                code="rewrite_requested_requires_xisf_writer",
                reason="XISF.pm provides read behavior only, so requested rewrites are blocked.",
                evidence_ids=(XISF_READ_ONLY_SOURCE,),
            )
        )
    add_non_mutating_gate(gates, allow_output_emission)
    unique_gates = unique_emission_gates(tuple(gates))
    status: XisfPlanStatus = "unsupported" if structural_gate_present(unique_gates) else "planned"
    sources = unique_sources(
        (
            *XISF_TRANSACTION_SOURCES,
            *header_validation.evidence_ids,
            *xml_header.evidence_ids,
            *image_descriptor.evidence_ids,
            *image_payload.evidence_ids,
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in unique_gates for source in gate.evidence_ids),
        )
    )
    return XisfMetadataTransactionPlan(
        status=status,
        source_data=xisf_data,
        header_validation=header_validation,
        xml_header=xml_header,
        image_descriptor=image_descriptor,
        image_payload=image_payload,
        actions=actions,
        output_emission_gates=unique_gates,
        evidence_ids=sources,
    )


def build_xisf_header_validation_plan(xisf_data: bytes) -> XisfHeaderValidationPlan:
    preamble_bytes_read = min(len(xisf_data), XISF_PREAMBLE_SIZE)
    signature = xisf_data[: len(XISF_SIGNATURE)]
    if len(xisf_data) < XISF_PREAMBLE_SIZE:
        return XisfHeaderValidationPlan(
            signature=signature,
            declared_xml_header_length=None,
            preamble_bytes_read=preamble_bytes_read,
            xml_header_range=None,
            reason="truncated_xisf_preamble",
            evidence_ids=(XISF_PROCESS_GATE_SOURCE,),
        )
    declared_length = read_u32le(xisf_data, XISF_XML_LENGTH_OFFSET)
    xml_header_range = (XISF_PREAMBLE_SIZE, XISF_PREAMBLE_SIZE + declared_length)
    if xisf_data[: len(XISF_SIGNATURE)] != XISF_SIGNATURE:
        return XisfHeaderValidationPlan(
            signature=signature,
            declared_xml_header_length=declared_length,
            preamble_bytes_read=preamble_bytes_read,
            xml_header_range=xml_header_range,
            reason="unsupported_xisf_signature",
            evidence_ids=(XISF_PROCESS_GATE_SOURCE,),
        )
    return XisfHeaderValidationPlan(
        signature=signature,
        declared_xml_header_length=declared_length,
        preamble_bytes_read=preamble_bytes_read,
        xml_header_range=xml_header_range,
        reason=None,
        evidence_ids=(XISF_PROCESS_GATE_SOURCE,),
    )


def build_xisf_xml_header_plan(
    xisf_data: bytes,
    validation: XisfHeaderValidationPlan,
) -> XisfXmlHeaderPlan:
    if not validation.is_exiftool_accepted or validation.xml_header_range is None:
        return XisfXmlHeaderPlan(
            header_range=None,
            declared_length=validation.declared_xml_header_length,
            available_length=0,
            xml_bytes=b"",
            root_name=None,
            reason=None,
            evidence_ids=(XISF_XML_PROCESS_SOURCE,),
        )

    start, end = validation.xml_header_range
    available_length = max(0, min(len(xisf_data), end) - start)
    if len(xisf_data) < end:
        return XisfXmlHeaderPlan(
            header_range=(start, len(xisf_data)),
            declared_length=validation.declared_xml_header_length,
            available_length=available_length,
            xml_bytes=xisf_data[start:],
            root_name=None,
            reason="truncated_xisf_xml_header",
            evidence_ids=(XISF_PROCESS_GATE_SOURCE,),
        )

    xml_bytes = xisf_data[start:end]
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return XisfXmlHeaderPlan(
            header_range=(start, end),
            declared_length=validation.declared_xml_header_length,
            available_length=available_length,
            xml_bytes=xml_bytes,
            root_name=None,
            reason="malformed_xisf_xml_header",
            evidence_ids=(XISF_XML_PROCESS_SOURCE,),
        )
    return XisfXmlHeaderPlan(
        header_range=(start, end),
        declared_length=validation.declared_xml_header_length,
        available_length=available_length,
        xml_bytes=xml_bytes,
        root_name=local_name(root.tag),
        reason=None,
        evidence_ids=(XISF_PROCESS_GATE_SOURCE, XISF_XML_PROCESS_SOURCE),
    )


def build_xisf_image_descriptor_plan(xml_header: XisfXmlHeaderPlan) -> XisfImageDescriptorPlan:
    if xml_header.reason is not None or not xml_header.xml_bytes:
        return XisfImageDescriptorPlan(
            image_attributes=(),
            properties=(),
            image_geometry=None,
            image_width=None,
            image_height=None,
            num_planes=None,
            sample_format=None,
            color_space=None,
            evidence_ids=(XISF_MAIN_TABLE_SOURCE, XISF_XML_PROCESS_SOURCE),
        )

    root = ElementTree.fromstring(xml_header.xml_bytes)
    image_attributes = tuple(extract_image_attributes(root))
    properties = tuple(extract_properties(root))
    image_geometry = first_attribute_value(image_attributes, "ImageGeometry")
    image_width, image_height, num_planes = split_geometry(image_geometry)
    return XisfImageDescriptorPlan(
        image_attributes=image_attributes,
        properties=properties,
        image_geometry=image_geometry,
        image_width=image_width,
        image_height=image_height,
        num_planes=num_planes,
        sample_format=first_attribute_value(image_attributes, "ImageSampleFormat"),
        color_space=first_attribute_value(image_attributes, "ColorSpace"),
        evidence_ids=(
            XISF_MAIN_TABLE_SOURCE,
            XISF_PROPERTY_ATTR_SOURCE,
            XISF_XML_PROCESS_SOURCE,
            XISF_GEOMETRY_SOURCE,
        ),
    )


def build_xisf_payload_plan(
    xisf_data: bytes,
    validation: XisfHeaderValidationPlan,
    xml_header: XisfXmlHeaderPlan,
) -> XisfPayloadPlan:
    if not validation.is_exiftool_accepted or xml_header.header_range is None:
        return XisfPayloadPlan(
            payload_range=None,
            action="preserve",
            evidence_ids=(XISF_READ_ONLY_SOURCE,),
        )
    _start, end = xml_header.header_range
    if xml_header.reason is not None:
        return XisfPayloadPlan(
            payload_range=None,
            action="preserve",
            evidence_ids=(XISF_READ_ONLY_SOURCE,),
        )
    return XisfPayloadPlan(
        payload_range=(end, len(xisf_data)),
        action="preserve",
        evidence_ids=(XISF_READ_ONLY_SOURCE,),
    )


def build_xisf_actions(
    validation: XisfHeaderValidationPlan,
    xml_header: XisfXmlHeaderPlan,
    descriptor: XisfImageDescriptorPlan,
    payload: XisfPayloadPlan,
    rewrite_requests: tuple[XisfRewriteRequest, ...],
) -> tuple[XisfActionPlan, ...]:
    actions: list[XisfActionPlan] = [
        XisfActionPlan(
            kind="validate_signature_header",
            target="xisf_preamble",
            byte_range=(0, validation.preamble_bytes_read),
            reason="Validate the 16-byte preamble and XISF0100 signature.",
            evidence_ids=validation.evidence_ids,
        )
    ]
    if xml_header.header_range is not None:
        actions.append(
            XisfActionPlan(
                kind="extract_xml_header",
                target="xml_header",
                byte_range=xml_header.header_range,
                reason="Extract the source-declared XML header bytes.",
                evidence_ids=xml_header.evidence_ids,
            )
        )
    if xml_header.reason is None and xml_header.header_range is not None:
        actions.append(
            XisfActionPlan(
                kind="parse_xml_header",
                target=xml_header.root_name or "xml_header",
                byte_range=xml_header.header_range,
                reason="Route XML header content through XISF/XMP-style metadata handling.",
                evidence_ids=(XISF_XML_PROCESS_SOURCE,),
            )
        )
    for attribute in descriptor.image_attributes:
        actions.append(
            XisfActionPlan(
                kind="route_image_attribute",
                target=f"{attribute.source_key}->{attribute.routed_tag}",
                byte_range=xml_header.header_range,
                reason="Route an Image XML attribute through the XISF main table.",
                evidence_ids=attribute.evidence_ids,
            )
        )
    for property_plan in descriptor.properties:
        actions.append(
            XisfActionPlan(
                kind="route_property",
                target=f"{property_plan.raw_id}->{property_plan.routed_tag}",
                byte_range=xml_header.header_range,
                reason="Route an id/value property with XISF property attribute rules.",
                evidence_ids=property_plan.evidence_ids,
            )
        )
    if descriptor.image_geometry is not None:
        actions.append(
            XisfActionPlan(
                kind="derive_geometry_tags",
                target="ImageWidth/ImageHeight/NumPlanes",
                byte_range=xml_header.header_range,
                reason="Derive image dimensions from the colon-delimited ImageGeometry value.",
                evidence_ids=(XISF_GEOMETRY_SOURCE,),
            )
        )
    if xml_header.header_range is not None and xml_header.reason is None:
        actions.append(
            XisfActionPlan(
                kind="preserve_xml_header",
                target="xml_header",
                byte_range=xml_header.header_range,
                reason="Keep the XML header bytes unchanged.",
                evidence_ids=(XISF_READ_ONLY_SOURCE,),
            )
        )
    if payload.payload_range is not None:
        actions.append(
            XisfActionPlan(
                kind="preserve_image_payload",
                target="image_payload",
                byte_range=payload.payload_range,
                reason="Keep every byte after the XML header unchanged.",
                evidence_ids=payload.evidence_ids,
            )
        )
    for request in rewrite_requests:
        target_detail: str = request.target
        if request.property_name is not None:
            target_detail = f"{target_detail}:{request.property_name}"
        actions.append(
            XisfActionPlan(
                kind="block_requested_rewrite",
                target=f"{request.operation}:{target_detail}",
                byte_range=None,
                reason="XISF.pm does not define write behavior for this requested mutation.",
                evidence_ids=(XISF_READ_ONLY_SOURCE,),
            )
        )
    return tuple(actions)


def extract_image_attributes(root: ElementTree.Element[str]) -> tuple[XisfImageAttributePlan, ...]:
    attributes: list[XisfImageAttributePlan] = []
    image_index = 0
    for element in root.iter():
        if local_name(element.tag) != "Image":
            continue
        for raw_name, value in element.attrib.items():
            name = local_name(raw_name)
            routed_tag = IMAGE_ATTRIBUTE_TAGS.get(name)
            source_key = IMAGE_ATTRIBUTE_SOURCE_KEYS.get(name)
            if routed_tag is None or source_key is None:
                continue
            attributes.append(
                XisfImageAttributePlan(
                    image_index=image_index,
                    xml_attribute=name,
                    source_key=source_key,
                    routed_tag=routed_tag,
                    value=value,
                    evidence_ids=(XISF_MAIN_TABLE_SOURCE, XISF_XML_PROCESS_SOURCE),
                )
            )
        image_index += 1
    return tuple(attributes)


def extract_properties(root: ElementTree.Element[str]) -> tuple[XisfPropertyPlan, ...]:
    properties: list[XisfPropertyPlan] = []
    for element in root.iter():
        attrs = {local_name(name): value for name, value in element.attrib.items()}
        raw_id = attrs.get("id")
        if raw_id is None:
            continue
        element_name = local_name(element.tag)
        if element_name in IGNORED_XML_PROPERTIES:
            routed_id = raw_id.removeprefix("XISF:")
            properties.append(
                XisfPropertyPlan(
                    xml_element=element_name,
                    raw_id=raw_id,
                    routed_tag=PROPERTY_RENAMES.get(routed_id, routed_id),
                    value=attrs.get("value"),
                    type_name=attrs.get("type"),
                    evidence_ids=(XISF_PROPERTY_ATTR_SOURCE, XISF_MAIN_TABLE_SOURCE),
                )
            )
    return tuple(properties)


def first_attribute_value(
    attributes: tuple[XisfImageAttributePlan, ...],
    routed_tag: str,
) -> str | None:
    for attribute in attributes:
        if attribute.routed_tag == routed_tag:
            return attribute.value
    return None


def split_geometry(geometry: str | None) -> tuple[str | None, str | None, str | None]:
    if geometry is None:
        return (None, None, None)
    parts = geometry.split(":")
    width = parts[0] if len(parts) > 0 else None
    height = parts[1] if len(parts) > 1 else None
    planes = parts[2] if len(parts) > 2 else None
    return (width, height, planes)


def local_name(name: str) -> str:
    if name.startswith("{"):
        _namespace, _, local = name.partition("}")
        return local
    return name


def read_u32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def add_non_mutating_gate(
    gates: list[XisfOutputEmissionGate],
    allow_output_emission: bool,
) -> None:
    if allow_output_emission:
        return
    gates.append(
        XisfOutputEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="The XISF plan is preserve-only; callers must opt in before emitting bytes.",
            evidence_ids=(XISF_READ_ONLY_SOURCE,),
        )
    )


def structural_gate_present(gates: tuple[XisfOutputEmissionGate, ...]) -> bool:
    return any(
        gate.code
        in {
            "truncated_xisf_preamble",
            "unsupported_xisf_signature",
            "truncated_xisf_xml_header",
            "malformed_xisf_xml_header",
        }
        for gate in gates
    )


def unique_emission_gates(
    gates: tuple[XisfOutputEmissionGate, ...],
) -> tuple[XisfOutputEmissionGate, ...]:
    seen: set[XisfEmissionGateCode] = set()
    unique: list[XisfOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for source in sources:
        key = source
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return tuple(unique)
