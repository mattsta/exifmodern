"""Package-local Google XMP/trailer scalar reader surfaces."""

from __future__ import annotations

import base64
import binascii
import gzip
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime

from exifmodern.formats.google.metadata_transaction_plan import (
    GOOGLE_HDRPLUS_SOURCE,
    EvidenceAnchor,
    GoogleMetadataTransactionPlan,
    GoogleMetadataValue,
    build_google_metadata_transaction_plan,
)
from exifmodern.formats.protobuf.metadata_transaction_plan import (
    ProtobufFieldDatabase,
    ProtobufFieldDefinition,
    ProtobufRecordPlan,
    build_protobuf_metadata_transaction_plan,
)


@dataclass(frozen=True)
class GoogleReadTag:
    name: str
    value: GoogleMetadataValue | int
    group0: str
    group2: str
    source_table: str
    tag_id: str
    xml_path: tuple[str, ...]
    payload_kind: str
    evidence_anchors: tuple[EvidenceAnchor, ...]


@dataclass(frozen=True)
class GoogleReadBlocker:
    code: str
    reason: str
    evidence_anchors: tuple[EvidenceAnchor, ...]


@dataclass(frozen=True)
class GoogleReaderResult:
    plan: GoogleMetadataTransactionPlan
    tags: tuple[GoogleReadTag, ...]
    blockers: tuple[GoogleReadBlocker, ...]


@dataclass(frozen=True)
class _GoogleHdrPlusTagSpec:
    tag_id: str
    name: str
    group2: str
    format_name: str | None
    value_scale: float | None
    evidence_anchors: tuple[EvidenceAnchor, ...]


def read_google_metadata_scalars(data: bytes) -> GoogleReaderResult:
    plan = build_google_metadata_transaction_plan(data)
    tags = [
        GoogleReadTag(
            name=property_plan.tag_name,
            value=property_plan.value,
            group0="XMP",
            group2=property_plan.group2,
            source_table=f"Image::ExifTool::Google::{property_plan.namespace}",
            tag_id=property_plan.property_id,
            xml_path=property_plan.xml_path,
            payload_kind=property_plan.payload_kind,
            evidence_anchors=property_plan.evidence_anchors,
        )
        for property_plan in plan.properties
        if property_plan.known
    ]
    for payload in plan.payload_preservations:
        if payload.decoded_size is not None:
            tags.append(
                GoogleReadTag(
                    name=f"{payload.name}ByteCount",
                    value=payload.decoded_size,
                    group0="XMP",
                    group2="Image",
                    source_table="Image::ExifTool::Google::payload-boundary",
                    tag_id=payload.source_property,
                    xml_path=(),
                    payload_kind=payload.payload_kind,
                    evidence_anchors=payload.evidence_anchors,
                )
            )
    tags.extend(hdrplus_tags_for_plan(plan))
    blockers = tuple(
        GoogleReadBlocker(blocker.code, blocker.reason, blocker.evidence_anchors)
        for blocker in plan.blockers
    )
    return GoogleReaderResult(plan=plan, tags=tuple(tags), blockers=blockers)


def hdrplus_tags_for_plan(plan: GoogleMetadataTransactionPlan) -> list[GoogleReadTag]:
    tags: list[GoogleReadTag] = []
    for property_plan in plan.properties:
        if property_plan.tag_name != "HDRPlusMakerNote":
            continue
        decoded = decode_hdrp_payload(value_as_text(property_plan.value))
        if decoded is None:
            continue
        protobuf_plan = build_protobuf_metadata_transaction_plan(
            decoded,
            field_database=HDRPLUS_PROTOBUF_DATABASE,
            allow_output_emission=True,
        )
        for record in flattened_protobuf_records(protobuf_plan.records):
            spec = HDRPLUS_TAG_SPECS.get(record.field_path)
            if spec is None:
                continue
            value = hdrplus_record_value(record, spec)
            if value is None:
                continue
            tags.append(
                GoogleReadTag(
                    name=spec.name,
                    value=value,
                    group0="MakerNotes",
                    group2=spec.group2,
                    source_table="Image::ExifTool::Google::HDRPlusMakerNote",
                    tag_id=spec.tag_id,
                    xml_path=property_plan.xml_path,
                    payload_kind="hdrp_protobuf",
                    evidence_anchors=spec.evidence_anchors,
                )
            )
    return tags


def decode_hdrp_payload(raw_text: str) -> bytes | None:
    raw_bytes = raw_text.encode("latin-1")
    if raw_bytes.startswith((b"HDRP\x02", b"HDRP\x03")):
        encoded = raw_bytes
    else:
        try:
            encoded = base64.b64decode(raw_text, validate=True)
        except binascii.Error:
            return None
    if not encoded.startswith((b"HDRP\x02", b"HDRP\x03")):
        return None
    encrypted = encoded[5:]
    try:
        return gzip.decompress(decrypt_hdrp_payload(encrypted))
    except OSError, EOFError, zlib.error:
        return None


def decrypt_hdrp_payload(encrypted: bytes) -> bytes:
    pad = (8 - (len(encrypted) % 8)) & 0x07
    padded = encrypted + (b"\0" * pad)
    if not padded:
        return b""
    words = list(struct.unpack(f"<{len(padded) // 4}I", padded))
    high = 0x2515606B
    low = 0x4A7791CD
    index = 0
    while index < len(words):
        low ^= (low >> 12) | ((high & 0xFFF) << 20)
        low &= 0xFFFFFFFF
        high ^= high >> 12
        high &= 0xFFFFFFFF
        high ^= ((high & 0x7F) << 25) | (low >> 7)
        high &= 0xFFFFFFFF
        low ^= (low & 0x7F) << 25
        low &= 0xFFFFFFFF
        low ^= (low >> 27) | ((high & 0x7FFFFFF) << 5)
        low &= 0xFFFFFFFF
        high ^= high >> 27
        high &= 0xFFFFFFFF
        key = (((high << 32) | low) * 0x2545F4914F6CDD1D) & 0xFFFFFFFFFFFFFFFF
        high = (key >> 32) & 0xFFFFFFFF
        low = key & 0xFFFFFFFF
        words[index] ^= low
        index += 1
        if index < len(words):
            words[index] ^= high
            index += 1
    decrypted = struct.pack(f"<{len(words)}I", *(word & 0xFFFFFFFF for word in words))
    return decrypted[:-pad] if pad else decrypted


def flattened_protobuf_records(
    records: tuple[ProtobufRecordPlan, ...],
) -> tuple[ProtobufRecordPlan, ...]:
    flattened: list[ProtobufRecordPlan] = []
    for record in records:
        flattened.append(record)
        flattened.extend(flattened_protobuf_records(record.nested_records))
    return tuple(flattened)


def hdrplus_record_value(
    record: ProtobufRecordPlan,
    spec: _GoogleHdrPlusTagSpec,
) -> GoogleMetadataValue | None:
    if spec.format_name == "unsigned":
        if record.value.value_varint is None or record.value.value_varint.value is None:
            return None
        if spec.name == "CreateDate":
            return exiftool_local_datetime(record.value.value_varint.value, milliseconds=False)
        if spec.name == "SoftwareDate":
            software_timestamp = record.value.value_varint.value / 1000
            return exiftool_local_datetime(software_timestamp, milliseconds=True)
        return record.value.value_varint.value
    if spec.format_name == "float":
        if len(record.value.raw_payload) != 4:
            return None
        value = float(struct.unpack("<f", record.value.raw_payload)[0])
        if spec.value_scale is not None:
            value /= spec.value_scale
        if spec.name == "ExposureTimeMin":
            return f"{value:.15g}"
        return value
    if spec.format_name == "binary":
        return record.value.raw_payload
    if record.tag.wire_type == 2:
        return record.value.raw_payload.decode("ascii", errors="replace")
    return record.value.display_value


def value_as_text(value: GoogleMetadataValue) -> str:
    if isinstance(value, bytes):
        return value.decode("latin-1")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def exiftool_local_datetime(timestamp: int | float, *, milliseconds: bool) -> str:
    local = datetime.fromtimestamp(timestamp).astimezone()
    offset = local.strftime("%z")
    formatted_offset = f"{offset[:3]}:{offset[3:]}" if offset else ""
    if milliseconds:
        millisecond = local.microsecond // 1000
        return local.strftime("%Y:%m:%d %H:%M:%S") + f".{millisecond:03d}{formatted_offset}"
    return local.strftime("%Y:%m:%d %H:%M:%S") + formatted_offset


def hdrplus_spec(
    tag_id: str,
    name: str,
    group2: str,
    format_name: str | None = None,
    value_scale: float | None = None,
) -> _GoogleHdrPlusTagSpec:
    return _GoogleHdrPlusTagSpec(
        tag_id,
        name,
        group2,
        format_name,
        value_scale,
        (GOOGLE_HDRPLUS_SOURCE,),
    )


HDRPLUS_TAG_SPECS: dict[str, _GoogleHdrPlusTagSpec] = {
    "1-1": hdrplus_spec("1-1", "ImageName", "Image"),
    "1-2": hdrplus_spec("1-2", "ImageData", "Image", "binary"),
    "2": hdrplus_spec("2", "TimeLogText", "Image", "binary"),
    "3": hdrplus_spec("3", "SummaryText", "Image", "binary"),
    "9-3": hdrplus_spec("9-3", "FrameCount", "Image", "unsigned"),
    "9-36-1": hdrplus_spec("9-36-1", "CreateDate", "Time", "unsigned"),
    "12-1": hdrplus_spec("12-1", "DeviceMake", "Device"),
    "12-2": hdrplus_spec("12-2", "DeviceModel", "Device"),
    "12-3": hdrplus_spec("12-3", "DeviceCodename", "Device"),
    "12-4": hdrplus_spec("12-4", "DeviceHardwareRevision", "Device"),
    "12-6": hdrplus_spec("12-6", "HDRPSoftware", "Device"),
    "12-7": hdrplus_spec("12-7", "AndroidRelease", "Device"),
    "12-8": hdrplus_spec("12-8", "SoftwareDate", "Time", "unsigned", 1000.0),
    "12-9": hdrplus_spec("12-9", "Application", "Device"),
    "12-10": hdrplus_spec("12-10", "AppVersion", "Device"),
    "12-12-1": hdrplus_spec("12-12-1", "ExposureTimeMin", "Camera", "float", 1000.0),
    "12-12-2": hdrplus_spec("12-12-2", "ExposureTimeMax", "Camera", "float", 1000.0),
    "12-13-1": hdrplus_spec("12-13-1", "ISOMin", "Camera", "float"),
    "12-13-2": hdrplus_spec("12-13-2", "ISOMax", "Camera", "float"),
    "12-14": hdrplus_spec("12-14", "MaxAnalogISO", "Camera", "float"),
}

HDRPLUS_PROTOBUF_DATABASE = ProtobufFieldDatabase(
    tuple(
        ProtobufFieldDefinition(
            tag=tag_id,
            name=spec.name,
        )
        for tag_id, spec in HDRPLUS_TAG_SPECS.items()
    )
)
