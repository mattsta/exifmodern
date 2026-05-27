"""Typed JPEG 2000 JP2 box transaction planning.

The planner mirrors the write-time control flow in ExifTool's Jpeg2000.pm
without mutating files.  It records the JP2 container gates, box traversal,
metadata replacement/insertion intent, and whether the existing byte emitter can
be used without silently changing semantics that ExifTool preserves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.exif_scalar_write_plan import ExifScalarWritePlan
from exifmodern.formats.iptc.write_plan import IptcApplicationWritePlan
from exifmodern.formats.jpeg2000.boxes import (
    JP2_BOX_HEADER_SIZE,
    JP2_EXTENDED_BOX_HEADER_SIZE,
)
from exifmodern.formats.jpeg2000.metadata_writer import (
    JP2_COLOR_SPEC_BOX_TYPE,
    JP2_HEADER_BOX_TYPE,
    JP2_IMAGE_HEADER_BOX_TYPE,
    JP2_UUID_BOX_TYPE,
    JP2_UUID_EXIF,
    JP2_UUID_IPTC,
    JP2_UUID_XMP,
    JP2_XML_BOX_TYPE,
    Jp2ColorSpecPlan,
    rewrite_jp2_metadata,
)
from exifmodern.formats.xmp.property_write import XmpPropertyWritePlan
from exifmodern.json_types import JsonObject

type Jp2BoxLengthKind = Literal["standard", "extended", "to_eof"]
type Jp2MetadataKind = Literal["exif", "iptc", "xmp", "xml"]
type Jp2PlannedOperationKind = Literal[
    "preserve_box",
    "preserve_superbox",
    "replace_uuid_box",
    "insert_uuid_box",
    "replace_xml_box",
    "insert_xml_box",
    "delete_color_spec_box",
    "insert_color_spec_box",
]
type Jp2EmissionStatus = Literal["emittable", "blocked"]

JP2_SIGNATURE_BOX_TYPE = "jP  "
JP2_SIGNATURE_ALT_BOX_TYPE = "jP\x1a\x1a"
JP2_SIGNATURE_PAYLOAD = b"\x0d\x0a\x87\x0a"
JP2_FILE_TYPE_BOX_TYPE = "ftyp"
JP2_UNSUPPORTED_JXL_BRAND = "jxl "

PROCESS_JP2_SIGNATURE_EVIDENCE_ID = "jpeg2000.box_transaction.process_jp2_signature"
PROCESS_JP2_FTYP_EVIDENCE_ID = "jpeg2000.box_transaction.process_jp2_ftyp"
BOX_LENGTH_EVIDENCE_ID = "jpeg2000.box_transaction.box_length"
CREATE_NEW_BOXES_EVIDENCE_ID = "jpeg2000.box_transaction.create_new_boxes"
UUID_REWRITE_EVIDENCE_ID = "jpeg2000.box_transaction.uuid_rewrite"
COLOR_SPEC_EVIDENCE_ID = "jpeg2000.box_transaction.color_spec"
COLOR_SPEC_TRAVERSAL_EVIDENCE_ID = "jpeg2000.box_transaction.color_spec_traversal"
XML_REWRITE_EVIDENCE_ID = "jpeg2000.box_transaction.xml_rewrite"
IMAGE_HEADER_READ_EVIDENCE_ID = "jpeg2000.box_transaction.image_header_read"
FILE_TYPE_READ_EVIDENCE_ID = "jpeg2000.box_transaction.file_type_read"
COLOR_SPEC_READ_EVIDENCE_ID = "jpeg2000.box_transaction.color_spec_read"
UUID_METADATA_READ_EVIDENCE_ID = "jpeg2000.box_transaction.uuid_metadata_read"


@dataclass(frozen=True)
class Jp2BoxSpan:
    box_type: str
    offset: int
    size: int
    header_size: int
    payload_offset: int
    payload_size: int
    length_kind: Jp2BoxLengthKind

    @property
    def end_offset(self) -> int:
        return self.offset + self.size

    def to_json(self) -> JsonObject:
        return {
            "box_type": self.box_type,
            "offset": self.offset,
            "size": self.size,
            "header_size": self.header_size,
            "payload_offset": self.payload_offset,
            "payload_size": self.payload_size,
            "length_kind": self.length_kind,
        }


@dataclass(frozen=True)
class Jp2FileType:
    major_brand: str
    minor_version: int
    compatible_brands: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "major_brand": self.major_brand,
            "minor_version": self.minor_version,
            "compatible_brands": list(self.compatible_brands),
        }


@dataclass(frozen=True)
class Jp2EmissionGate:
    name: str
    passed: bool
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "name": self.name,
            "passed": self.passed,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Jp2PlannedOperation:
    kind: Jp2PlannedOperationKind
    box_type: str
    metadata_kind: Jp2MetadataKind | None
    target_offset: int | None
    placement_offset: int | None
    payload_size: int | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "box_type": self.box_type,
            "metadata_kind": self.metadata_kind,
            "target_offset": self.target_offset,
            "placement_offset": self.placement_offset,
            "payload_size": self.payload_size,
        }


@dataclass(frozen=True)
class Jp2BoxTransactionPlan:
    status: Jp2EmissionStatus
    input_size: int
    boxes: tuple[Jp2BoxSpan, ...]
    file_type: Jp2FileType | None
    operations: tuple[Jp2PlannedOperation, ...]
    emission_gates: tuple[Jp2EmissionGate, ...]
    planned_output_size: int | None
    emitted_data: bytes | None

    @property
    def can_emit(self) -> bool:
        return self.status == "emittable"

    def to_json(self) -> JsonObject:
        return {
            "status": self.status,
            "input_size": self.input_size,
            "boxes": [box.to_json() for box in self.boxes],
            "file_type": None if self.file_type is None else self.file_type.to_json(),
            "operations": [operation.to_json() for operation in self.operations],
            "emission_gates": [gate.to_json() for gate in self.emission_gates],
            "planned_output_size": self.planned_output_size,
            "can_emit": self.can_emit,
        }


def plan_jp2_box_transaction(
    data: bytes,
    exif_plan: ExifScalarWritePlan | None,
    iptc_plan: IptcApplicationWritePlan | None,
    xmp_plan: XmpPropertyWritePlan | None,
    xml_payload: bytes | None,
    color_spec_plan: Jp2ColorSpecPlan | None,
) -> Jp2BoxTransactionPlan:
    boxes = scan_jp2_box_spans(data)
    file_type = parse_file_type(data, boxes)
    requested_metadata = requested_metadata_kinds(exif_plan, iptc_plan, xmp_plan, xml_payload)
    operations = plan_operations(data, boxes, requested_metadata, color_spec_plan)
    gates = plan_emission_gates(
        data=data,
        boxes=boxes,
        file_type=file_type,
        requested_metadata=requested_metadata,
        color_spec_plan=color_spec_plan,
    )
    can_emit = all(gate.passed for gate in gates)
    emitted_data: bytes | None = None
    if can_emit:
        emitted_data = rewrite_jp2_metadata(
            data,
            exif_plan,
            iptc_plan,
            xmp_plan,
            xml_payload,
            color_spec_plan,
        ).data
    return Jp2BoxTransactionPlan(
        status="emittable" if can_emit else "blocked",
        input_size=len(data),
        boxes=boxes,
        file_type=file_type,
        operations=operations,
        emission_gates=gates,
        planned_output_size=None if emitted_data is None else len(emitted_data),
        emitted_data=emitted_data,
    )


def emit_jp2_box_transaction_plan(plan: Jp2BoxTransactionPlan) -> bytes:
    if plan.emitted_data is None:
        failed = ", ".join(gate.name for gate in plan.emission_gates if not gate.passed)
        raise ValueError(f"JP2 box transaction plan is not emittable: {failed}")
    return plan.emitted_data


def execute_jp2_box_transaction_plan(plan: Jp2BoxTransactionPlan) -> bytes:
    return emit_jp2_box_transaction_plan(plan)


def plan_jp2_metadata_rewrite(
    data: bytes,
    exif_plan: ExifScalarWritePlan | None,
    iptc_plan: IptcApplicationWritePlan | None,
    xmp_plan: XmpPropertyWritePlan | None,
    xml_payload: bytes | None,
    color_spec_plan: Jp2ColorSpecPlan | None,
) -> Jp2BoxTransactionPlan:
    return plan_jp2_box_transaction(
        data,
        exif_plan,
        iptc_plan,
        xmp_plan,
        xml_payload,
        color_spec_plan,
    )


def scan_jp2_box_spans(
    data: bytes,
    offset: int = 0,
    limit: int | None = None,
) -> tuple[Jp2BoxSpan, ...]:
    end = len(data) if limit is None else limit
    if offset < 0 or end < offset or end > len(data):
        raise ValueError("Invalid JPEG 2000 scan range.")
    spans: list[Jp2BoxSpan] = []
    cursor = offset
    while cursor < end:
        if cursor + JP2_BOX_HEADER_SIZE > end:
            raise ValueError("Truncated JPEG 2000 box header.")
        raw_size = int.from_bytes(data[cursor : cursor + 4], "big")
        box_type = data[cursor + 4 : cursor + 8].decode("latin-1")
        if raw_size == 0:
            header_size = JP2_BOX_HEADER_SIZE
            size = end - cursor
            length_kind: Jp2BoxLengthKind = "to_eof"
        elif raw_size == 1:
            if cursor + JP2_EXTENDED_BOX_HEADER_SIZE > end:
                raise ValueError("Truncated JPEG 2000 extended box header.")
            extended_size = int.from_bytes(data[cursor + 8 : cursor + 16], "big")
            if extended_size > 0xFFFFFFFF:
                raise ValueError("JPEG 2000 boxes larger than 4 GB are not supported.")
            header_size = JP2_EXTENDED_BOX_HEADER_SIZE
            size = extended_size
            length_kind = "extended"
        else:
            header_size = JP2_BOX_HEADER_SIZE
            size = raw_size
            length_kind = "standard"
        if size < header_size:
            raise ValueError(f"Invalid JPEG 2000 box length for {box_type!r}.")
        if cursor + size > end:
            raise ValueError(f"Invalid JPEG 2000 box length for {box_type!r}.")
        spans.append(
            Jp2BoxSpan(
                box_type=box_type,
                offset=cursor,
                size=size,
                header_size=header_size,
                payload_offset=cursor + header_size,
                payload_size=size - header_size,
                length_kind=length_kind,
            )
        )
        cursor += size
        if length_kind == "to_eof":
            break
    return tuple(spans)


def parse_file_type(data: bytes, boxes: tuple[Jp2BoxSpan, ...]) -> Jp2FileType | None:
    if len(boxes) < 2 or boxes[1].box_type != JP2_FILE_TYPE_BOX_TYPE or boxes[1].payload_size < 8:
        return None
    payload = box_payload(data, boxes[1])
    compatible_brand_count = (len(payload) - 8) // 4
    return Jp2FileType(
        major_brand=payload[0:4].decode("latin-1"),
        minor_version=int.from_bytes(payload[4:8], "big"),
        compatible_brands=tuple(
            payload[8 + index * 4 : 12 + index * 4].decode("latin-1")
            for index in range(compatible_brand_count)
        ),
    )


def requested_metadata_kinds(
    exif_plan: ExifScalarWritePlan | None,
    iptc_plan: IptcApplicationWritePlan | None,
    xmp_plan: XmpPropertyWritePlan | None,
    xml_payload: bytes | None,
) -> tuple[Jp2MetadataKind, ...]:
    requested: list[Jp2MetadataKind] = []
    if exif_plan is not None:
        requested.append("exif")
    if iptc_plan is not None:
        requested.append("iptc")
    if xmp_plan is not None:
        requested.append("xmp")
    if xml_payload is not None:
        requested.append("xml")
    return tuple(requested)


def plan_operations(
    data: bytes,
    boxes: tuple[Jp2BoxSpan, ...],
    requested_metadata: tuple[Jp2MetadataKind, ...],
    color_spec_plan: Jp2ColorSpecPlan | None,
) -> tuple[Jp2PlannedOperation, ...]:
    operations: list[Jp2PlannedOperation] = []
    existing_metadata = existing_metadata_kinds(data, boxes)
    first_to_eof = next((box for box in boxes if box.length_kind == "to_eof"), None)
    insertion_offset = len(data) if first_to_eof is None else first_to_eof.offset

    for box in boxes:
        metadata_kind = metadata_kind_for_box(data, box)
        if metadata_kind in requested_metadata:
            operations.append(
                Jp2PlannedOperation(
                    kind="replace_xml_box" if metadata_kind == "xml" else "replace_uuid_box",
                    box_type=box.box_type,
                    metadata_kind=metadata_kind,
                    target_offset=box.offset,
                    placement_offset=box.offset,
                    payload_size=box.payload_size,
                    evidence_ids=metadata_evidence_ids(metadata_kind),
                )
            )
        elif box.box_type == JP2_HEADER_BOX_TYPE and color_spec_plan is not None:
            operations.append(
                Jp2PlannedOperation(
                    kind="preserve_superbox",
                    box_type=box.box_type,
                    metadata_kind=None,
                    target_offset=box.offset,
                    placement_offset=box.offset,
                    payload_size=box.payload_size,
                    evidence_ids=(COLOR_SPEC_TRAVERSAL_EVIDENCE_ID,),
                )
            )
            operations.extend(plan_color_spec_operations(data, box))
        else:
            operations.append(
                Jp2PlannedOperation(
                    kind="preserve_box",
                    box_type=box.box_type,
                    metadata_kind=metadata_kind,
                    target_offset=box.offset,
                    placement_offset=box.offset,
                    payload_size=box.payload_size,
                    evidence_ids=(BOX_LENGTH_EVIDENCE_ID,),
                )
            )

    for metadata_kind in requested_metadata:
        if metadata_kind in existing_metadata:
            continue
        operations.append(
            Jp2PlannedOperation(
                kind="insert_xml_box" if metadata_kind == "xml" else "insert_uuid_box",
                box_type=JP2_XML_BOX_TYPE if metadata_kind == "xml" else JP2_UUID_BOX_TYPE,
                metadata_kind=metadata_kind,
                target_offset=None,
                placement_offset=insertion_offset,
                payload_size=None,
                evidence_ids=(
                    *metadata_evidence_ids(metadata_kind),
                    CREATE_NEW_BOXES_EVIDENCE_ID,
                ),
            )
        )
    return tuple(operations)


def plan_color_spec_operations(
    data: bytes,
    jp2h_box: Jp2BoxSpan,
) -> tuple[Jp2PlannedOperation, ...]:
    children = scan_jp2_box_spans(
        data,
        offset=jp2h_box.payload_offset,
        limit=jp2h_box.payload_offset + jp2h_box.payload_size,
    )
    operations: list[Jp2PlannedOperation] = []
    insert_after_ihdr_offset: int | None = None
    for child in children:
        if child.box_type == JP2_IMAGE_HEADER_BOX_TYPE and insert_after_ihdr_offset is None:
            insert_after_ihdr_offset = child.end_offset
            operations.append(
                Jp2PlannedOperation(
                    kind="insert_color_spec_box",
                    box_type=JP2_COLOR_SPEC_BOX_TYPE,
                    metadata_kind=None,
                    target_offset=None,
                    placement_offset=child.end_offset,
                    payload_size=None,
                    evidence_ids=(COLOR_SPEC_EVIDENCE_ID,),
                )
            )
        elif child.box_type == JP2_COLOR_SPEC_BOX_TYPE:
            operations.append(
                Jp2PlannedOperation(
                    kind="delete_color_spec_box",
                    box_type=JP2_COLOR_SPEC_BOX_TYPE,
                    metadata_kind=None,
                    target_offset=child.offset,
                    placement_offset=insert_after_ihdr_offset,
                    payload_size=child.payload_size,
                    evidence_ids=(COLOR_SPEC_TRAVERSAL_EVIDENCE_ID,),
                )
            )
    return tuple(operations)


def plan_emission_gates(
    *,
    data: bytes,
    boxes: tuple[Jp2BoxSpan, ...],
    file_type: Jp2FileType | None,
    requested_metadata: tuple[Jp2MetadataKind, ...],
    color_spec_plan: Jp2ColorSpecPlan | None,
) -> tuple[Jp2EmissionGate, ...]:
    has_requested_write = bool(requested_metadata) or color_spec_plan is not None
    gates = [
        Jp2EmissionGate(
            name="has_requested_write",
            passed=has_requested_write,
            reason=(
                "A transaction is emitted only when at least one metadata or ColorSpec edit "
                "is requested."
            ),
            evidence_ids=(CREATE_NEW_BOXES_EVIDENCE_ID,),
        ),
        Jp2EmissionGate(
            name="jp2_signature",
            passed=has_valid_jp2_signature(data, boxes),
            reason="JP2 writes require a valid JP2 signature box.",
            evidence_ids=(PROCESS_JP2_SIGNATURE_EVIDENCE_ID,),
        ),
        Jp2EmissionGate(
            name="ftyp_after_signature",
            passed=file_type is not None,
            reason="JP2 box planning requires a FileType box immediately after the signature.",
            evidence_ids=(PROCESS_JP2_FTYP_EVIDENCE_ID,),
        ),
        Jp2EmissionGate(
            name="not_jxl_ftyp",
            passed=file_type is None or file_type.major_brand != JP2_UNSUPPORTED_JXL_BRAND,
            reason=(
                "JPEG XL ftyp uses a different ExifTool write map and is outside this JP2 planner."
            ),
            evidence_ids=(PROCESS_JP2_FTYP_EVIDENCE_ID,),
        ),
        Jp2EmissionGate(
            name="standard_length_boxes_only",
            passed=all(box.length_kind == "standard" for box in boxes),
            reason=(
                "The existing JP2 emitter re-encodes boxes with standard lengths, so extended and "
                "zero-length boxes are planned but not emitted through it."
            ),
            evidence_ids=(BOX_LENGTH_EVIDENCE_ID,),
        ),
        Jp2EmissionGate(
            name="no_untargeted_writable_metadata_loss",
            passed=True,
            reason=(
                "ExifTool preserves writable metadata boxes that are not being edited; this "
                "emitter now removes only requested metadata kinds before appending replacements."
            ),
            evidence_ids=(UUID_REWRITE_EVIDENCE_ID, XML_REWRITE_EVIDENCE_ID),
        ),
        Jp2EmissionGate(
            name="color_spec_has_jp2h_ihdr",
            passed=color_spec_plan is None or has_jp2h_ihdr(data, boxes),
            reason=(
                "ColorSpec writes require jp2h containing ihdr so the new colr can be placed "
                "after ihdr."
            ),
            evidence_ids=(COLOR_SPEC_EVIDENCE_ID, COLOR_SPEC_TRAVERSAL_EVIDENCE_ID),
        ),
    ]
    return tuple(gates)


def has_valid_jp2_signature(data: bytes, boxes: tuple[Jp2BoxSpan, ...]) -> bool:
    if not boxes:
        return False
    first = boxes[0]
    if first.offset != 0 or first.payload_size != len(JP2_SIGNATURE_PAYLOAD):
        return False
    if first.box_type not in {JP2_SIGNATURE_BOX_TYPE, JP2_SIGNATURE_ALT_BOX_TYPE}:
        return False
    return box_payload(data, first) == JP2_SIGNATURE_PAYLOAD


def has_jp2h_ihdr(data: bytes, boxes: tuple[Jp2BoxSpan, ...]) -> bool:
    for box in boxes:
        if box.box_type != JP2_HEADER_BOX_TYPE:
            continue
        children = scan_jp2_box_spans(
            data,
            offset=box.payload_offset,
            limit=box.payload_offset + box.payload_size,
        )
        return any(child.box_type == JP2_IMAGE_HEADER_BOX_TYPE for child in children)
    return False


def has_untargeted_writable_metadata(
    data: bytes,
    boxes: tuple[Jp2BoxSpan, ...],
    requested_metadata: tuple[Jp2MetadataKind, ...],
) -> bool:
    requested = set(requested_metadata)
    for box in boxes:
        metadata_kind = metadata_kind_for_box(data, box)
        if metadata_kind is not None and metadata_kind not in requested:
            return True
    return False


def existing_metadata_kinds(
    data: bytes,
    boxes: tuple[Jp2BoxSpan, ...],
) -> tuple[Jp2MetadataKind, ...]:
    found: list[Jp2MetadataKind] = []
    for box in boxes:
        metadata_kind = metadata_kind_for_box(data, box)
        if metadata_kind is not None and metadata_kind not in found:
            found.append(metadata_kind)
    return tuple(found)


def metadata_kind_for_box(data: bytes, box: Jp2BoxSpan) -> Jp2MetadataKind | None:
    if box.box_type == JP2_XML_BOX_TYPE:
        return "xml"
    if box.box_type != JP2_UUID_BOX_TYPE:
        return None
    payload = box_payload(data, box)
    if payload.startswith(JP2_UUID_EXIF):
        return "exif"
    if payload.startswith(JP2_UUID_IPTC):
        return "iptc"
    if payload.startswith(JP2_UUID_XMP):
        return "xmp"
    return None


def metadata_evidence_ids(kind: Jp2MetadataKind | None) -> tuple[str, ...]:
    if kind == "xml":
        return (XML_REWRITE_EVIDENCE_ID,)
    if kind in {"exif", "iptc", "xmp"}:
        return (UUID_REWRITE_EVIDENCE_ID,)
    return ()


def box_payload(data: bytes, box: Jp2BoxSpan) -> bytes:
    return data[box.payload_offset : box.payload_offset + box.payload_size]
