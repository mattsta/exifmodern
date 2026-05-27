"""Typed, non-mutating JPEG XL metadata box transaction plans.

The behavior here is grounded in ExifTool's JPEG 2000/JPEG XL implementation:
``/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/Jpeg2000.pm``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.exif_scalar_write_plan import ExifScalarWritePlan
from exifmodern.formats.jpeg2000.boxes import Jp2Box, encode_jp2_boxes
from exifmodern.formats.jxl.metadata_writer import (
    JXL_CODESTREAM_MAGIC,
    JXL_CONTAINER_SIGNATURE,
    JXL_EXIF_PREFIX,
    JXL_IMAGE_DATA_BOX_TYPES,
    JXL_METADATA_BOX_TYPES,
    first_box_payload,
    jxl_exif_payload,
    parse_jxl_container,
    upsert_metadata_box,
)
from exifmodern.formats.xmp.mutation import apply_xmp_property_write_plan
from exifmodern.formats.xmp.property_write import XmpPropertyWritePlan
from exifmodern.json_types import JsonObject

JP2_BOX_HEADER_SIZE = 8
JP2_UINT32_MAX = 0xFFFFFFFF

JXL_BOX_TRANSACTION_ORACLE_REFERENCES = (
    "/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/Jpeg2000.pm:38 "
    "declares JXL image-data box IDs jbrd/jxlp/jxlc.",
    "/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/Jpeg2000.pm:62-66 "
    "maps JXL IFD0 to Exif and XMP to xml .",
    "/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/Jpeg2000.pm:134-137 "
    "states JXL writes EXIF and XMP and can read/write Brotli metadata.",
    "/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/Jpeg2000.pm:469-484 "
    "parses JXL Exif with a four-byte leading offset word.",
    "/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/Jpeg2000.pm:485-507 "
    "identifies brob as Brotli EXIF/XMP/JUMB metadata.",
    "/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/Jpeg2000.pm:903-945 "
    "creates JXL Exif/xml boxes and pads Exif with four zero bytes.",
    "/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/Jpeg2000.pm:1252-1308 "
    "rewrites brob through Brotli-aware paths.",
    "/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/Jpeg2000.pm:1603-1648 "
    "validates JXL signature/codestream input and wraps codestreams on write.",
)

JxlSourceKind = Literal["container", "codestream", "invalid"]
JxlBoxAction = Literal["preserve", "insert", "replace", "wrap_codestream"]
JxlRemovalReason = Literal["delete_all_metadata", "replace_metadata"]
JxlLengthEncoding = Literal["uint32", "unsupported_gt_4gb"]
JxlMetadataKind = Literal["exif", "xmp", "brotli-exif", "brotli-xmp", "brotli-jumb", "unknown"]


@dataclass(frozen=True)
class JxlPlanIssue:
    code: str
    message: str
    oracle_reference: str

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "message": self.message,
            "oracle_reference": self.oracle_reference,
        }


@dataclass(frozen=True)
class JxlOutputBoxPlan:
    output_index: int
    box_type: str
    action: JxlBoxAction
    payload_length: int
    encoded_length: int
    length_encoding: JxlLengthEncoding
    source_index: int | None = None
    metadata_kind: JxlMetadataKind | None = None

    def to_json(self) -> JsonObject:
        return {
            "output_index": self.output_index,
            "box_type": self.box_type,
            "action": self.action,
            "payload_length": self.payload_length,
            "encoded_length": self.encoded_length,
            "length_encoding": self.length_encoding,
            "source_index": self.source_index,
            "metadata_kind": self.metadata_kind,
        }


@dataclass(frozen=True)
class JxlRemovedBoxPlan:
    source_index: int
    box_type: str
    reason: JxlRemovalReason
    payload_length: int
    metadata_kind: JxlMetadataKind | None = None

    def to_json(self) -> JsonObject:
        return {
            "source_index": self.source_index,
            "box_type": self.box_type,
            "reason": self.reason,
            "payload_length": self.payload_length,
            "metadata_kind": self.metadata_kind,
        }


@dataclass(frozen=True)
class JxlBoxTransactionPlan:
    source_kind: JxlSourceKind
    input_box_types: tuple[str, ...]
    output_boxes: tuple[JxlOutputBoxPlan, ...]
    removed_boxes: tuple[JxlRemovedBoxPlan, ...]
    issues: tuple[JxlPlanIssue, ...]
    output_jp2_boxes: tuple[Jp2Box, ...]
    wrapped_codestream: bool
    changed_exif_properties: int
    changed_xmp_properties: int
    deleted_metadata_boxes: int
    oracle_references: tuple[str, ...] = JXL_BOX_TRANSACTION_ORACLE_REFERENCES

    @property
    def blockers(self) -> tuple[JxlPlanIssue, ...]:
        return self.issues

    @property
    def can_emit(self) -> bool:
        if self.issues:
            return False
        return all(box.length_encoding == "uint32" for box in self.output_boxes)

    @property
    def output_box_types(self) -> tuple[str, ...]:
        return tuple(box.box_type for box in self.output_boxes)

    def emit(self) -> bytes:
        """Return planned bytes, or fail if validation/blocker gates are closed."""
        if not self.can_emit:
            issue_codes = ", ".join(issue.code for issue in self.issues) or "unsupported_box_length"
            raise JxlBoxTransactionBlocked(f"JXL box transaction cannot be emitted: {issue_codes}")
        return JXL_CONTAINER_SIGNATURE + encode_jp2_boxes(self.output_jp2_boxes)

    def to_json(self) -> JsonObject:
        return {
            "source_kind": self.source_kind,
            "input_box_types": list(self.input_box_types),
            "output_boxes": [box.to_json() for box in self.output_boxes],
            "removed_boxes": [box.to_json() for box in self.removed_boxes],
            "issues": [issue.to_json() for issue in self.issues],
            "wrapped_codestream": self.wrapped_codestream,
            "changed_exif_properties": self.changed_exif_properties,
            "changed_xmp_properties": self.changed_xmp_properties,
            "deleted_metadata_boxes": self.deleted_metadata_boxes,
            "can_emit": self.can_emit,
            "oracle_references": list(self.oracle_references),
        }


class JxlBoxTransactionBlocked(ValueError):
    """Raised when a JXL box transaction plan is intentionally not emit-able."""


def build_jxl_box_transaction_plan(
    data: bytes,
    exif_plan: ExifScalarWritePlan | None = None,
    xmp_plan: XmpPropertyWritePlan | None = None,
    *,
    delete_all_metadata: bool = False,
    allow_codestream_wrap: bool = False,
) -> JxlBoxTransactionPlan:
    """Build a non-mutating plan for uncompressed JXL EXIF/XMP box emission."""
    source_kind = _detect_source_kind(data)
    if source_kind == "invalid":
        return _blocked_plan(
            source_kind=source_kind,
            code="unsupported_jxl_signature",
            message="Expected a JPEG XL ISO BMFF signature or bare JPEG XL codestream magic.",
            oracle_reference=JXL_BOX_TRANSACTION_ORACLE_REFERENCES[-1],
        )

    if source_kind == "codestream" and not allow_codestream_wrap:
        return _blocked_plan(
            source_kind=source_kind,
            code="codestream_wrap_requires_approval",
            message=(
                "Bare JPEG XL codestream writes require explicit wrapping approval; "
                "ExifTool only wraps on write when minor errors are ignored."
            ),
            oracle_reference=JXL_BOX_TRANSACTION_ORACLE_REFERENCES[-1],
        )

    try:
        container = parse_jxl_container(data)
    except ValueError as exc:
        return _blocked_plan(
            source_kind=source_kind,
            code="invalid_jxl_container",
            message=str(exc),
            oracle_reference=JXL_BOX_TRANSACTION_ORACLE_REFERENCES[-1],
        )

    source_boxes = container.boxes
    issues = _container_validation_issues(source_kind, source_boxes)
    issues += _compressed_metadata_blockers(
        source_boxes,
        writes_exif=exif_plan is not None,
        writes_xmp=xmp_plan is not None,
        delete_all_metadata=delete_all_metadata,
    )

    output_boxes = source_boxes
    removed_boxes: list[JxlRemovedBoxPlan] = []
    if delete_all_metadata:
        output_boxes = tuple(
            box for box in source_boxes if box.box_type not in JXL_METADATA_BOX_TYPES
        )
        removed_boxes.extend(
            JxlRemovedBoxPlan(
                source_index=index,
                box_type=box.box_type,
                reason="delete_all_metadata",
                payload_length=len(box.payload),
                metadata_kind=_metadata_kind(box),
            )
            for index, box in enumerate(source_boxes)
            if box.box_type in JXL_METADATA_BOX_TYPES
        )

    changed_exif_properties = 0
    if exif_plan is not None:
        removed_boxes.extend(
            _replacement_removals(source_boxes, "Exif", already_removed=removed_boxes)
        )
        output_boxes = upsert_metadata_box(
            output_boxes,
            Jp2Box("Exif", JXL_EXIF_PREFIX + jxl_exif_payload(output_boxes, exif_plan)),
        )
        changed_exif_properties = len(exif_plan.steps)

    changed_xmp_properties = 0
    if xmp_plan is not None:
        removed_boxes.extend(
            _replacement_removals(source_boxes, "xml ", already_removed=removed_boxes)
        )
        existing_payload = first_box_payload(output_boxes, "xml ")
        xmp_source = existing_payload if existing_payload is not None else _empty_xmp_packet()
        xmp_result = apply_xmp_property_write_plan(xmp_source, xmp_plan)
        output_boxes = upsert_metadata_box(output_boxes, Jp2Box("xml ", xmp_result.packet))
        changed_xmp_properties = xmp_result.changed_properties

    output_plan = _output_box_plan(
        source_kind=source_kind,
        source_boxes=source_boxes,
        output_boxes=output_boxes,
    )
    issues += tuple(
        JxlPlanIssue(
            code="unsupported_box_length",
            message=(
                f"Box {box.box_type!r} is larger than the supported 32-bit JP2/JXL length field."
            ),
            oracle_reference=JXL_BOX_TRANSACTION_ORACLE_REFERENCES[7],
        )
        for box in output_plan
        if box.length_encoding != "uint32"
    )

    return JxlBoxTransactionPlan(
        source_kind=source_kind,
        input_box_types=(
            ("codestream",)
            if source_kind == "codestream"
            else tuple(box.box_type for box in source_boxes)
        ),
        output_boxes=output_plan,
        removed_boxes=tuple(removed_boxes),
        issues=issues,
        output_jp2_boxes=output_boxes,
        wrapped_codestream=container.wrapped_codestream,
        changed_exif_properties=changed_exif_properties,
        changed_xmp_properties=changed_xmp_properties,
        deleted_metadata_boxes=sum(
            1 for removed in removed_boxes if removed.reason == "delete_all_metadata"
        ),
    )


plan_jxl_box_transaction = build_jxl_box_transaction_plan


def _detect_source_kind(data: bytes) -> JxlSourceKind:
    if data.startswith(JXL_CONTAINER_SIGNATURE):
        return "container"
    if data.startswith(JXL_CODESTREAM_MAGIC):
        return "codestream"
    return "invalid"


def _blocked_plan(
    *,
    source_kind: JxlSourceKind,
    code: str,
    message: str,
    oracle_reference: str,
) -> JxlBoxTransactionPlan:
    return JxlBoxTransactionPlan(
        source_kind=source_kind,
        input_box_types=(),
        output_boxes=(),
        removed_boxes=(),
        issues=(JxlPlanIssue(code=code, message=message, oracle_reference=oracle_reference),),
        output_jp2_boxes=(),
        wrapped_codestream=False,
        changed_exif_properties=0,
        changed_xmp_properties=0,
        deleted_metadata_boxes=0,
    )


def _container_validation_issues(
    source_kind: JxlSourceKind, boxes: tuple[Jp2Box, ...]
) -> tuple[JxlPlanIssue, ...]:
    if source_kind == "codestream":
        return ()
    issues: list[JxlPlanIssue] = []
    if not boxes or boxes[0].box_type != "ftyp":
        issues.append(
            JxlPlanIssue(
                code="missing_jxl_ftyp",
                message="JPEG XL container metadata writes require the first box to be ftyp.",
                oracle_reference=JXL_BOX_TRANSACTION_ORACLE_REFERENCES[-1],
            )
        )
    elif not boxes[0].payload.startswith(b"jxl "):
        issues.append(
            JxlPlanIssue(
                code="unsupported_jxl_brand",
                message="JPEG XL container ftyp brand must start with 'jxl '.",
                oracle_reference=JXL_BOX_TRANSACTION_ORACLE_REFERENCES[-1],
            )
        )
    if not any(box.box_type in JXL_IMAGE_DATA_BOX_TYPES for box in boxes):
        issues.append(
            JxlPlanIssue(
                code="missing_jxl_image_data",
                message="JPEG XL container metadata writes require jxlc, jxlp, or jbrd image data.",
                oracle_reference=JXL_BOX_TRANSACTION_ORACLE_REFERENCES[0],
            )
        )
    return tuple(issues)


def _compressed_metadata_blockers(
    boxes: tuple[Jp2Box, ...],
    *,
    writes_exif: bool,
    writes_xmp: bool,
    delete_all_metadata: bool,
) -> tuple[JxlPlanIssue, ...]:
    if delete_all_metadata:
        return ()
    issues: list[JxlPlanIssue] = []
    for box in boxes:
        if box.box_type != "brob":
            continue
        kind = _metadata_kind(box)
        if kind == "brotli-exif" and writes_exif:
            issues.append(
                JxlPlanIssue(
                    code="compressed_exif_requires_brotli",
                    message=(
                        "Existing Brotli-compressed EXIF would need Brotli-aware rewrite; "
                        "this plan only emits uncompressed Exif boxes."
                    ),
                    oracle_reference=JXL_BOX_TRANSACTION_ORACLE_REFERENCES[6],
                )
            )
        elif kind == "brotli-xmp" and writes_xmp:
            issues.append(
                JxlPlanIssue(
                    code="compressed_xmp_requires_brotli",
                    message=(
                        "Existing Brotli-compressed XMP would need Brotli-aware rewrite; "
                        "this plan only emits uncompressed xml  boxes."
                    ),
                    oracle_reference=JXL_BOX_TRANSACTION_ORACLE_REFERENCES[6],
                )
            )
    return tuple(issues)


def _replacement_removals(
    source_boxes: tuple[Jp2Box, ...],
    box_type: str,
    *,
    already_removed: list[JxlRemovedBoxPlan],
) -> tuple[JxlRemovedBoxPlan, ...]:
    removed_indexes = {box.source_index for box in already_removed}
    return tuple(
        JxlRemovedBoxPlan(
            source_index=index,
            box_type=box.box_type,
            reason="replace_metadata",
            payload_length=len(box.payload),
            metadata_kind=_metadata_kind(box),
        )
        for index, box in enumerate(source_boxes)
        if box.box_type == box_type and index not in removed_indexes
    )


def _output_box_plan(
    *,
    source_kind: JxlSourceKind,
    source_boxes: tuple[Jp2Box, ...],
    output_boxes: tuple[Jp2Box, ...],
) -> tuple[JxlOutputBoxPlan, ...]:
    classification_source_boxes = () if source_kind == "codestream" else source_boxes
    consumed_source_indexes: set[int] = set()
    planned: list[JxlOutputBoxPlan] = []
    for output_index, output_box in enumerate(output_boxes):
        source_index = (
            None
            if source_kind == "codestream"
            else _matching_source_index(
                output_box,
                classification_source_boxes,
                consumed_source_indexes=consumed_source_indexes,
            )
        )
        if source_index is not None:
            consumed_source_indexes.add(source_index)
            action: JxlBoxAction = "preserve"
        elif source_kind == "codestream" and output_box.box_type == "jxlc":
            action = "wrap_codestream"
        elif any(box.box_type == output_box.box_type for box in classification_source_boxes):
            action = "replace"
        else:
            action = "insert"
        planned.append(
            JxlOutputBoxPlan(
                output_index=output_index,
                box_type=output_box.box_type,
                action=action,
                source_index=source_index,
                payload_length=len(output_box.payload),
                encoded_length=len(output_box.payload) + JP2_BOX_HEADER_SIZE,
                length_encoding=_length_encoding(output_box),
                metadata_kind=_metadata_kind(output_box),
            )
        )
    return tuple(planned)


def _matching_source_index(
    output_box: Jp2Box,
    source_boxes: tuple[Jp2Box, ...],
    *,
    consumed_source_indexes: set[int],
) -> int | None:
    for index, source_box in enumerate(source_boxes):
        if index in consumed_source_indexes:
            continue
        if source_box == output_box:
            return index
    return None


def _length_encoding(box: Jp2Box) -> JxlLengthEncoding:
    return (
        "uint32"
        if len(box.payload) + JP2_BOX_HEADER_SIZE <= JP2_UINT32_MAX
        else "unsupported_gt_4gb"
    )


def _metadata_kind(box: Jp2Box) -> JxlMetadataKind | None:
    if box.box_type == "Exif":
        return "exif"
    if box.box_type == "xml ":
        return "xmp"
    if box.box_type != "brob":
        return None
    prefix = box.payload[:4].lower()
    if prefix == b"exif":
        return "brotli-exif"
    if prefix == b"xml ":
        return "brotli-xmp"
    if prefix == b"jumb":
        return "brotli-jumb"
    return "unknown"


def _empty_xmp_packet() -> bytes:
    from exifmodern.formats.xmp.packet import empty_xmp_packet

    return empty_xmp_packet()
