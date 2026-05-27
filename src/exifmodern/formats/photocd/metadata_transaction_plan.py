"""Source-backed, non-mutating PhotoCD metadata transaction plans.

ExifTool's PhotoCD module reads a 2048-byte Image Pac metadata window from file
offset 2048, requires the window to begin with ``PCD_IPI``, then processes
fixed-offset binary tags with big-endian numeric fields. This planner mirrors
those read responsibilities while preserving all input bytes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonValue

PHOTOCD_PM_SOURCE_PATH = "lib/Image/ExifTool/PhotoCD.pm"
PHOTOCD_METADATA_WINDOW_OFFSET = 2048
PHOTOCD_METADATA_WINDOW_SIZE = 2048
PHOTOCD_EXIFTOOL_DATA_POS = 4096
PHOTOCD_SIGNATURE = b"PCD_IPI"

type PhotoCdPlanStatus = Literal["planned", "unsupported"]
type PhotoCdRecordRole = Literal[
    "signature_header",
    "version_metadata",
    "time_metadata",
    "medium_metadata",
    "scan_metadata",
    "workstation_metadata",
    "character_metadata",
    "unknown_metadata",
    "finisher_metadata",
    "film_metadata",
    "rights_metadata",
    "image_size_resolution_metadata",
]
type PhotoCdActionKind = Literal[
    "preserve_leading_image_payload",
    "preserve_binary_metadata_window",
    "enumerate_exiftool_binary_record",
    "preserve_unknown_record",
    "preserve_unmodeled_metadata_range",
    "preserve_trailing_image_payload",
    "block_requested_rewrite",
]
type PhotoCdEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_signature_seek",
    "truncated_metadata_window",
    "unsupported_photocd_signature",
    "metadata_window_rewrite_required",
    "image_payload_rewrite_required",
]

PHOTOCD_MAIN_TABLE_SOURCE = "photocd.main.table"
PHOTOCD_SCAN_SOURCE = "photocd.scan"
PHOTOCD_SBA_SOURCE = "photocd.sba"
PHOTOCD_IMAGE_SIZE_SOURCE = "photocd.image.size"
PHOTOCD_PROCESS_SOURCE = "photocd.process"
PHOTOCD_READ_ONLY_SOURCE = "photocd.read.only"

PHOTOCD_TRANSACTION_SOURCES = (
    PHOTOCD_MAIN_TABLE_SOURCE,
    PHOTOCD_SCAN_SOURCE,
    PHOTOCD_SBA_SOURCE,
    PHOTOCD_IMAGE_SIZE_SOURCE,
    PHOTOCD_PROCESS_SOURCE,
    PHOTOCD_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class PhotoCdByteRange:
    start: int
    end: int
    reason: str

    def to_json(self) -> dict[str, JsonValue]:
        return {"end": self.end, "reason": self.reason, "start": self.start}


@dataclass(frozen=True)
class PhotoCdRecordDefinition:
    name: str
    offset: int
    length: int
    role: PhotoCdRecordRole
    evidence_ids: tuple[str, ...]
    requires_sba: bool = False
    requires_copyright_restriction: bool = False
    is_unknown: bool = False


@dataclass(frozen=True)
class PhotoCdRecordPlan:
    name: str
    role: PhotoCdRecordRole
    window_offset: int
    file_offset: int
    length: int
    raw_value: bytes
    parsed_value: str | int | float | None
    eligible: bool
    preserved: bool
    is_unknown: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "eligible": self.eligible,
            "file_offset": self.file_offset,
            "is_unknown": self.is_unknown,
            "length": self.length,
            "name": self.name,
            "parsed_value": self.parsed_value,
            "preserved": self.preserved,
            "raw_value_hex": self.raw_value.hex(),
            "role": self.role,
            "window_offset": self.window_offset,
        }


@dataclass(frozen=True)
class PhotoCdHeaderValidationPlan:
    signature_offset: int
    metadata_window_offset: int
    metadata_window_size: int
    exiftool_data_pos: int
    signature: bytes
    actual_file_size: int
    reason: PhotoCdEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    @property
    def is_supported_photocd(self) -> bool:
        return self.reason is None

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "actual_file_size": self.actual_file_size,
            "exiftool_data_pos": self.exiftool_data_pos,
            "is_supported_photocd": self.is_supported_photocd,
            "metadata_window_offset": self.metadata_window_offset,
            "metadata_window_size": self.metadata_window_size,
            "reason": self.reason,
            "signature": ascii_bytes(self.signature),
            "signature_offset": self.signature_offset,
        }


@dataclass(frozen=True)
class PhotoCdBinaryDirectoryPlan:
    dir_name: str
    data_pos: int
    byte_order: Literal["MM"]
    records: tuple[PhotoCdRecordPlan, ...]
    unknown_ranges: tuple[PhotoCdByteRange, ...]
    evidence_ids: tuple[str, ...]

    def records_by_name(self) -> dict[str, PhotoCdRecordPlan]:
        return {record.name: record for record in self.records}

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "byte_order": self.byte_order,
            "data_pos": self.data_pos,
            "dir_name": self.dir_name,
            "records": json_array(record.to_json() for record in self.records),
            "unknown_ranges": json_array(item.to_json() for item in self.unknown_ranges),
        }


@dataclass(frozen=True)
class PhotoCdImageMetadataPlan:
    orientation_code: int | None
    image_width: int | None
    image_height: int | None
    size_code: int | None
    compression_class: int | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "compression_class": self.compression_class,
            "image_height": self.image_height,
            "image_width": self.image_width,
            "orientation_code": self.orientation_code,
            "size_code": self.size_code,
        }


@dataclass(frozen=True)
class PhotoCdScanMetadataPlan:
    product_type: str | None
    scanner_vendor_id: str | None
    scanner_product_id: str | None
    scanner_firmware_version: str | None
    scanner_firmware_date: str | None
    scanner_serial_number: str | None
    scanner_pixel_size_micrometers: str | None
    image_workstation_make: str | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "image_workstation_make": self.image_workstation_make,
            "product_type": self.product_type,
            "scanner_firmware_date": self.scanner_firmware_date,
            "scanner_firmware_version": self.scanner_firmware_version,
            "scanner_pixel_size_micrometers": self.scanner_pixel_size_micrometers,
            "scanner_product_id": self.scanner_product_id,
            "scanner_serial_number": self.scanner_serial_number,
            "scanner_vendor_id": self.scanner_vendor_id,
        }


@dataclass(frozen=True)
class PhotoCdFilmMetadataPlan:
    has_sba: bool
    sba_revision: str | None
    sba_command: int | None
    film_id: int | None
    copyright_status: int | None
    copyright_file_name: str | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "copyright_file_name": self.copyright_file_name,
            "copyright_status": self.copyright_status,
            "film_id": self.film_id,
            "has_sba": self.has_sba,
            "sba_command": self.sba_command,
            "sba_revision": self.sba_revision,
        }


@dataclass(frozen=True)
class PhotoCdPayloadPreservationPlan:
    leading_image_payload: PhotoCdByteRange | None
    metadata_window: PhotoCdByteRange | None
    trailing_image_payload: PhotoCdByteRange | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "leading_image_payload": range_to_json(self.leading_image_payload),
            "metadata_window": range_to_json(self.metadata_window),
            "trailing_image_payload": range_to_json(self.trailing_image_payload),
        }


@dataclass(frozen=True)
class PhotoCdMetadataActionPlan:
    kind: PhotoCdActionKind
    byte_range_start: int | None
    byte_range_end: int | None
    input_payload_length: int | None
    planned_payload_length: int | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "byte_range_end": self.byte_range_end,
            "byte_range_start": self.byte_range_start,
            "input_payload_length": self.input_payload_length,
            "kind": self.kind,
            "planned_payload_length": self.planned_payload_length,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PhotoCdOutputEmissionGate:
    code: PhotoCdEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PhotoCdMetadataTransactionPlan:
    status: PhotoCdPlanStatus
    header: PhotoCdHeaderValidationPlan
    directory: PhotoCdBinaryDirectoryPlan
    image_metadata: PhotoCdImageMetadataPlan
    scan_metadata: PhotoCdScanMetadataPlan
    film_metadata: PhotoCdFilmMetadataPlan
    payload_preservation: PhotoCdPayloadPreservationPlan
    actions: tuple[PhotoCdMetadataActionPlan, ...]
    output_emission_gates: tuple[PhotoCdOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"PhotoCD metadata transaction output is gated: {gate_codes}")
        return self.original_bytes

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "actions": json_array(action.to_json() for action in self.actions),
            "can_emit_output": self.can_emit_output,
            "directory": self.directory.to_json(),
            "film_metadata": self.film_metadata.to_json(),
            "header": self.header.to_json(),
            "image_metadata": self.image_metadata.to_json(),
            "output_emission_gates": json_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "payload_preservation": self.payload_preservation.to_json(),
            "scan_metadata": self.scan_metadata.to_json(),
            "status": self.status,
        }


def build_photocd_metadata_transaction_plan(
    photocd_data: bytes,
    *,
    replacement_metadata_window: bytes | None = None,
    replacement_image_payload: bytes | None = None,
    allow_output_emission: bool = False,
) -> PhotoCdMetadataTransactionPlan:
    header = build_header_validation_plan(photocd_data)
    metadata_window = read_metadata_window(photocd_data, header)
    directory = build_binary_directory_plan(metadata_window)
    image_metadata = build_image_metadata_plan(directory)
    scan_metadata = build_scan_metadata_plan(directory)
    film_metadata = build_film_metadata_plan(directory)
    payload_preservation = build_payload_preservation_plan(photocd_data, header)
    gates = validation_gates(header)
    actions = build_actions(
        photocd_data,
        header,
        directory,
        payload_preservation,
        replacement_metadata_window,
        replacement_image_payload,
    )
    if replacement_metadata_window is not None:
        gates.append(
            PhotoCdOutputEmissionGate(
                code="metadata_window_rewrite_required",
                reason="PhotoCD.pm has no writer for replacing the fixed binary metadata window.",
                evidence_ids=(PHOTOCD_MAIN_TABLE_SOURCE, PHOTOCD_READ_ONLY_SOURCE),
            )
        )
    if replacement_image_payload is not None:
        gates.append(
            PhotoCdOutputEmissionGate(
                code="image_payload_rewrite_required",
                reason="PhotoCD.pm only reads metadata and does not rewrite image payload bytes.",
                evidence_ids=(PHOTOCD_PROCESS_SOURCE, PHOTOCD_READ_ONLY_SOURCE),
            )
        )
    if not allow_output_emission:
        gates.append(
            PhotoCdOutputEmissionGate(
                code="non_mutating_plan_requires_explicit_emission",
                reason="PhotoCD transaction plans require explicit output emission approval.",
                evidence_ids=(PHOTOCD_READ_ONLY_SOURCE,),
            )
        )
    status: PhotoCdPlanStatus = "unsupported" if any_validation_gate(gates) else "planned"
    sources = unique_sources(
        (
            *PHOTOCD_TRANSACTION_SOURCES,
            *header.evidence_ids,
            *directory.evidence_ids,
            *image_metadata.evidence_ids,
            *scan_metadata.evidence_ids,
            *film_metadata.evidence_ids,
            *payload_preservation.evidence_ids,
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return PhotoCdMetadataTransactionPlan(
        status=status,
        header=header,
        directory=directory,
        image_metadata=image_metadata,
        scan_metadata=scan_metadata,
        film_metadata=film_metadata,
        payload_preservation=payload_preservation,
        actions=actions,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
        original_bytes=photocd_data,
    )


def build_header_validation_plan(photocd_data: bytes) -> PhotoCdHeaderValidationPlan:
    signature = photocd_data[
        PHOTOCD_METADATA_WINDOW_OFFSET : PHOTOCD_METADATA_WINDOW_OFFSET + len(PHOTOCD_SIGNATURE)
    ]
    reason: PhotoCdEmissionGateCode | None = None
    if len(photocd_data) < PHOTOCD_METADATA_WINDOW_OFFSET:
        reason = "truncated_signature_seek"
    elif len(photocd_data) < PHOTOCD_METADATA_WINDOW_OFFSET + PHOTOCD_METADATA_WINDOW_SIZE:
        reason = "truncated_metadata_window"
    elif signature != PHOTOCD_SIGNATURE:
        reason = "unsupported_photocd_signature"
    return PhotoCdHeaderValidationPlan(
        signature_offset=PHOTOCD_METADATA_WINDOW_OFFSET,
        metadata_window_offset=PHOTOCD_METADATA_WINDOW_OFFSET,
        metadata_window_size=PHOTOCD_METADATA_WINDOW_SIZE,
        exiftool_data_pos=PHOTOCD_EXIFTOOL_DATA_POS,
        signature=signature,
        actual_file_size=len(photocd_data),
        reason=reason,
        evidence_ids=(PHOTOCD_PROCESS_SOURCE,),
    )


def read_metadata_window(
    photocd_data: bytes,
    header: PhotoCdHeaderValidationPlan,
) -> bytes:
    if header.reason is not None:
        return b""
    return photocd_data[
        PHOTOCD_METADATA_WINDOW_OFFSET : PHOTOCD_METADATA_WINDOW_OFFSET
        + PHOTOCD_METADATA_WINDOW_SIZE
    ]


def build_binary_directory_plan(metadata_window: bytes) -> PhotoCdBinaryDirectoryPlan:
    has_sba = metadata_window[225:228] == b"SBA" if len(metadata_window) >= 228 else False
    copyright_status = (
        read_u8(metadata_window, 331) if has_sba and len(metadata_window) > 331 else None
    )
    records = tuple(
        build_record_plan(definition, metadata_window, has_sba, copyright_status)
        for definition in PHOTOCD_RECORD_DEFINITIONS
    )
    known_ranges = tuple(
        PhotoCdByteRange(
            start=record.window_offset,
            end=record.window_offset + record.length,
            reason=record.name,
        )
        for record in records
        if record.eligible and record.length > 0
    )
    return PhotoCdBinaryDirectoryPlan(
        dir_name="PhotoCD",
        data_pos=PHOTOCD_EXIFTOOL_DATA_POS,
        byte_order="MM",
        records=records,
        unknown_ranges=unknown_ranges(known_ranges, PHOTOCD_METADATA_WINDOW_SIZE),
        evidence_ids=(PHOTOCD_PROCESS_SOURCE, PHOTOCD_MAIN_TABLE_SOURCE),
    )


def build_record_plan(
    definition: PhotoCdRecordDefinition,
    metadata_window: bytes,
    has_sba: bool,
    copyright_status: int | None,
) -> PhotoCdRecordPlan:
    eligible = True
    if definition.requires_sba and not has_sba:
        eligible = False
    if definition.requires_copyright_restriction and copyright_status != 1:
        eligible = False
    raw_value = metadata_window[definition.offset : definition.offset + definition.length]
    parsed_value = parse_record_value(definition.name, raw_value, has_sba)
    return PhotoCdRecordPlan(
        name=definition.name,
        role=definition.role,
        window_offset=definition.offset,
        file_offset=PHOTOCD_METADATA_WINDOW_OFFSET + definition.offset,
        length=definition.length,
        raw_value=raw_value,
        parsed_value=parsed_value,
        eligible=eligible,
        preserved=eligible,
        is_unknown=definition.is_unknown,
        evidence_ids=definition.evidence_ids,
    )


def build_image_metadata_plan(directory: PhotoCdBinaryDirectoryPlan) -> PhotoCdImageMetadataPlan:
    record = directory.records_by_name().get("Orientation")
    flags = record.raw_value[0] if record is not None and record.raw_value else None
    orientation_code = flags & 0x03 if flags is not None else None
    size_code = (flags & 0x0C) >> 2 if flags is not None else None
    compression_class = (flags & 0x60) >> 5 if flags is not None else None
    if orientation_code is None or size_code is None:
        image_width = None
        image_height = None
    else:
        scale = size_code * 2 or 1
        image_width = (512 if orientation_code & 0x01 else 768) * scale
        image_height = (768 if orientation_code & 0x01 else 512) * scale
    return PhotoCdImageMetadataPlan(
        orientation_code=orientation_code,
        image_width=image_width,
        image_height=image_height,
        size_code=size_code,
        compression_class=compression_class,
        evidence_ids=(PHOTOCD_IMAGE_SIZE_SOURCE,),
    )


def build_scan_metadata_plan(directory: PhotoCdBinaryDirectoryPlan) -> PhotoCdScanMetadataPlan:
    records = directory.records_by_name()
    return PhotoCdScanMetadataPlan(
        product_type=string_record(records, "ProductType"),
        scanner_vendor_id=string_record(records, "ScannerVendorID"),
        scanner_product_id=string_record(records, "ScannerProductID"),
        scanner_firmware_version=string_record(records, "ScannerFirmwareVersion"),
        scanner_firmware_date=string_record(records, "ScannerFirmwareDate"),
        scanner_serial_number=string_record(records, "ScannerSerialNumber"),
        scanner_pixel_size_micrometers=pixel_size_record(records),
        image_workstation_make=string_record(records, "ImageWorkstationMake"),
        evidence_ids=(PHOTOCD_SCAN_SOURCE,),
    )


def build_film_metadata_plan(directory: PhotoCdBinaryDirectoryPlan) -> PhotoCdFilmMetadataPlan:
    records = directory.records_by_name()
    has_sba_record = records.get("HasSBA")
    has_sba = has_sba_record.raw_value == b"SBA" if has_sba_record is not None else False
    return PhotoCdFilmMetadataPlan(
        has_sba=has_sba,
        sba_revision=string_record(records, "SceneBalanceAlgorithmRevision"),
        sba_command=int_record(records, "SceneBalanceAlgorithmCommand"),
        film_id=int_record(records, "SceneBalanceAlgorithmFilmID"),
        copyright_status=int_record(records, "CopyrightStatus"),
        copyright_file_name=string_record(records, "CopyrightFileName"),
        evidence_ids=(PHOTOCD_SBA_SOURCE,),
    )


def build_payload_preservation_plan(
    photocd_data: bytes,
    header: PhotoCdHeaderValidationPlan,
) -> PhotoCdPayloadPreservationPlan:
    leading = PhotoCdByteRange(
        start=0,
        end=min(len(photocd_data), PHOTOCD_METADATA_WINDOW_OFFSET),
        reason="Preserve bytes before the ExifTool PhotoCD metadata seek target.",
    )
    metadata_window = None
    trailing = None
    if header.reason is None:
        metadata_end = PHOTOCD_METADATA_WINDOW_OFFSET + PHOTOCD_METADATA_WINDOW_SIZE
        metadata_window = PhotoCdByteRange(
            start=PHOTOCD_METADATA_WINDOW_OFFSET,
            end=metadata_end,
            reason="Preserve the full fixed binary metadata window read by PhotoCD.pm.",
        )
        trailing = PhotoCdByteRange(
            start=metadata_end,
            end=len(photocd_data),
            reason="Preserve image payload bytes after the fixed metadata window.",
        )
    return PhotoCdPayloadPreservationPlan(
        leading_image_payload=leading,
        metadata_window=metadata_window,
        trailing_image_payload=trailing,
        evidence_ids=(PHOTOCD_PROCESS_SOURCE, PHOTOCD_READ_ONLY_SOURCE),
    )


def build_actions(
    photocd_data: bytes,
    header: PhotoCdHeaderValidationPlan,
    directory: PhotoCdBinaryDirectoryPlan,
    payload_preservation: PhotoCdPayloadPreservationPlan,
    replacement_metadata_window: bytes | None,
    replacement_image_payload: bytes | None,
) -> tuple[PhotoCdMetadataActionPlan, ...]:
    actions: list[PhotoCdMetadataActionPlan] = []
    leading = payload_preservation.leading_image_payload
    if leading is not None and leading.end > leading.start:
        actions.append(
            range_action("preserve_leading_image_payload", leading, PHOTOCD_PROCESS_SOURCE)
        )
    window = payload_preservation.metadata_window
    if window is not None:
        actions.append(
            range_action("preserve_binary_metadata_window", window, PHOTOCD_PROCESS_SOURCE)
        )
    for record in directory.records:
        if not record.eligible:
            continue
        actions.append(record_action(record))
    for item in directory.unknown_ranges:
        actions.append(
            PhotoCdMetadataActionPlan(
                kind="preserve_unmodeled_metadata_range",
                byte_range_start=PHOTOCD_METADATA_WINDOW_OFFSET + item.start,
                byte_range_end=PHOTOCD_METADATA_WINDOW_OFFSET + item.end,
                input_payload_length=item.end - item.start,
                planned_payload_length=item.end - item.start,
                reason="Preserve bytes that ExifTool's PhotoCD binary table does not name.",
                evidence_ids=(PHOTOCD_MAIN_TABLE_SOURCE, PHOTOCD_READ_ONLY_SOURCE),
            )
        )
    trailing = payload_preservation.trailing_image_payload
    if trailing is not None:
        actions.append(
            range_action("preserve_trailing_image_payload", trailing, PHOTOCD_PROCESS_SOURCE)
        )
    if replacement_metadata_window is not None or replacement_image_payload is not None:
        actions.append(
            PhotoCdMetadataActionPlan(
                kind="block_requested_rewrite",
                byte_range_start=0,
                byte_range_end=len(photocd_data),
                input_payload_length=len(photocd_data),
                planned_payload_length=None,
                reason="Requested PhotoCD byte changes are planned only as blocked work.",
                evidence_ids=(PHOTOCD_READ_ONLY_SOURCE,),
            )
        )
    return tuple(actions)


def record_action(record: PhotoCdRecordPlan) -> PhotoCdMetadataActionPlan:
    kind: PhotoCdActionKind = (
        "preserve_unknown_record" if record.is_unknown else "enumerate_exiftool_binary_record"
    )
    return PhotoCdMetadataActionPlan(
        kind=kind,
        byte_range_start=record.file_offset,
        byte_range_end=record.file_offset + record.length,
        input_payload_length=record.length,
        planned_payload_length=record.length,
        reason=f"Preserve ExifTool PhotoCD binary field {record.name}.",
        evidence_ids=record.evidence_ids,
    )


def range_action(
    kind: Literal[
        "preserve_leading_image_payload",
        "preserve_binary_metadata_window",
        "preserve_trailing_image_payload",
    ],
    byte_range: PhotoCdByteRange,
    evidence_id: str,
) -> PhotoCdMetadataActionPlan:
    return PhotoCdMetadataActionPlan(
        kind=kind,
        byte_range_start=byte_range.start,
        byte_range_end=byte_range.end,
        input_payload_length=byte_range.end - byte_range.start,
        planned_payload_length=byte_range.end - byte_range.start,
        reason=byte_range.reason,
        evidence_ids=(evidence_id, PHOTOCD_READ_ONLY_SOURCE),
    )


def validation_gates(header: PhotoCdHeaderValidationPlan) -> list[PhotoCdOutputEmissionGate]:
    gates: list[PhotoCdOutputEmissionGate] = []
    if header.reason is not None:
        gates.append(
            PhotoCdOutputEmissionGate(
                code=header.reason,
                reason="PhotoCD signature or fixed metadata window validation failed.",
                evidence_ids=header.evidence_ids,
            )
        )
    return gates


def any_validation_gate(gates: list[PhotoCdOutputEmissionGate]) -> bool:
    validation_codes = {
        "truncated_signature_seek",
        "truncated_metadata_window",
        "unsupported_photocd_signature",
    }
    return any(gate.code in validation_codes for gate in gates)


def parse_record_value(name: str, raw_value: bytes, has_sba: bool) -> str | int | float | None:
    if not raw_value:
        return None
    if name in {
        "ProductType",
        "ScannerVendorID",
        "ScannerProductID",
        "ScannerFirmwareVersion",
        "ScannerFirmwareDate",
        "ScannerSerialNumber",
        "ImageWorkstationMake",
        "PhotoFinisherName",
        "CopyrightFileName",
    }:
        return trim_photo_cd_string(raw_value)
    if name in {
        "SpecificationVersion",
        "AuthoringSoftwareRelease",
        "ImageMagnificationDescriptor",
        "SceneBalanceAlgorithmRevision",
    }:
        if name == "SceneBalanceAlgorithmRevision" and not has_sba:
            return None
        if raw_value == b"\xff\xff":
            return "n/a"
        return ".".join(str(byte) for byte in raw_value)
    if name in {"CreateDate", "ModifyDate"}:
        value = int.from_bytes(raw_value, "big")
        return None if value == 0xFFFFFFFF else value
    if name == "ScannerPixelSize":
        return ".".join(f"{byte:02x}" for byte in raw_value)
    if len(raw_value) == 1:
        return raw_value[0]
    if len(raw_value) == 2:
        return int.from_bytes(raw_value, "big")
    return raw_value.hex()


def string_record(records: dict[str, PhotoCdRecordPlan], name: str) -> str | None:
    record = records.get(name)
    if record is None or not record.eligible or not isinstance(record.parsed_value, str):
        return None
    return record.parsed_value


def int_record(records: dict[str, PhotoCdRecordPlan], name: str) -> int | None:
    record = records.get(name)
    if record is None or not record.eligible:
        return None
    return record.parsed_value if isinstance(record.parsed_value, int) else None


def pixel_size_record(records: dict[str, PhotoCdRecordPlan]) -> str | None:
    value = string_record(records, "ScannerPixelSize")
    return f"{value} micrometers" if value is not None else None


def read_u8(data: bytes, offset: int) -> int | None:
    if offset >= len(data):
        return None
    return data[offset]


def trim_photo_cd_string(value: bytes) -> str:
    return value.split(b"\x00", 1)[0].rstrip(b" ").decode("latin-1")


def unknown_ranges(
    known_ranges: tuple[PhotoCdByteRange, ...],
    window_size: int,
) -> tuple[PhotoCdByteRange, ...]:
    ranges = sorted((item.start, item.end) for item in known_ranges)
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    result: list[PhotoCdByteRange] = []
    cursor = 0
    for start, end in merged:
        if cursor < start:
            result.append(
                PhotoCdByteRange(
                    start=cursor,
                    end=start,
                    reason="No ExifTool PhotoCD tag table entry covers this byte range.",
                )
            )
        cursor = max(cursor, end)
    if cursor < window_size:
        result.append(
            PhotoCdByteRange(
                start=cursor,
                end=window_size,
                reason="No ExifTool PhotoCD tag table entry covers this byte range.",
            )
        )
    return tuple(result)


def range_to_json(byte_range: PhotoCdByteRange | None) -> dict[str, JsonValue] | None:
    return byte_range.to_json() if byte_range is not None else None


def ascii_bytes(value: bytes) -> str:
    return "".join(chr(byte) if 32 <= byte <= 126 else f"\\x{byte:02x}" for byte in value)


def evidence_ids_to_json(references: tuple[str, ...]) -> JsonArray:
    return list(references)


def json_array(values: Iterable[JsonValue]) -> JsonArray:
    return [value for value in values]


def unique_sources(references: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for reference in references:
        key = reference
        if key in seen:
            continue
        seen.add(key)
        unique.append(reference)
    return tuple(unique)


def unique_gates(
    gates: tuple[PhotoCdOutputEmissionGate, ...],
) -> tuple[PhotoCdOutputEmissionGate, ...]:
    seen: set[PhotoCdEmissionGateCode] = set()
    unique: list[PhotoCdOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


PHOTOCD_RECORD_DEFINITIONS = (
    PhotoCdRecordDefinition(
        "Signature",
        0,
        len(PHOTOCD_SIGNATURE),
        "signature_header",
        (PHOTOCD_PROCESS_SOURCE,),
    ),
    PhotoCdRecordDefinition(
        "SpecificationVersion",
        7,
        2,
        "version_metadata",
        (PHOTOCD_MAIN_TABLE_SOURCE,),
    ),
    PhotoCdRecordDefinition(
        "AuthoringSoftwareRelease",
        9,
        2,
        "version_metadata",
        (PHOTOCD_MAIN_TABLE_SOURCE,),
    ),
    PhotoCdRecordDefinition(
        "ImageMagnificationDescriptor",
        11,
        2,
        "image_size_resolution_metadata",
        (PHOTOCD_MAIN_TABLE_SOURCE,),
    ),
    PhotoCdRecordDefinition("CreateDate", 13, 4, "time_metadata", (PHOTOCD_MAIN_TABLE_SOURCE,)),
    PhotoCdRecordDefinition("ModifyDate", 17, 4, "time_metadata", (PHOTOCD_MAIN_TABLE_SOURCE,)),
    PhotoCdRecordDefinition("ImageMedium", 21, 1, "medium_metadata", (PHOTOCD_MAIN_TABLE_SOURCE,)),
    PhotoCdRecordDefinition("ProductType", 22, 20, "scan_metadata", (PHOTOCD_SCAN_SOURCE,)),
    PhotoCdRecordDefinition("ScannerVendorID", 42, 20, "scan_metadata", (PHOTOCD_SCAN_SOURCE,)),
    PhotoCdRecordDefinition("ScannerProductID", 62, 16, "scan_metadata", (PHOTOCD_SCAN_SOURCE,)),
    PhotoCdRecordDefinition(
        "ScannerFirmwareVersion",
        78,
        4,
        "scan_metadata",
        (PHOTOCD_SCAN_SOURCE,),
    ),
    PhotoCdRecordDefinition("ScannerFirmwareDate", 82, 8, "scan_metadata", (PHOTOCD_SCAN_SOURCE,)),
    PhotoCdRecordDefinition("ScannerSerialNumber", 90, 20, "scan_metadata", (PHOTOCD_SCAN_SOURCE,)),
    PhotoCdRecordDefinition("ScannerPixelSize", 110, 2, "scan_metadata", (PHOTOCD_SCAN_SOURCE,)),
    PhotoCdRecordDefinition(
        "ImageWorkstationMake",
        112,
        20,
        "workstation_metadata",
        (PHOTOCD_SCAN_SOURCE,),
    ),
    PhotoCdRecordDefinition(
        "CharacterSet",
        132,
        1,
        "character_metadata",
        (PHOTOCD_MAIN_TABLE_SOURCE,),
    ),
    PhotoCdRecordDefinition(
        "CharacterEscapeSequence",
        133,
        32,
        "unknown_metadata",
        (PHOTOCD_MAIN_TABLE_SOURCE,),
        is_unknown=True,
    ),
    PhotoCdRecordDefinition(
        "PhotoFinisherName",
        165,
        60,
        "finisher_metadata",
        (PHOTOCD_MAIN_TABLE_SOURCE,),
    ),
    PhotoCdRecordDefinition("HasSBA", 225, 3, "film_metadata", (PHOTOCD_SBA_SOURCE,)),
    PhotoCdRecordDefinition(
        "SceneBalanceAlgorithmRevision",
        228,
        2,
        "film_metadata",
        (PHOTOCD_SBA_SOURCE,),
        requires_sba=True,
    ),
    PhotoCdRecordDefinition(
        "SceneBalanceAlgorithmCommand",
        230,
        1,
        "film_metadata",
        (PHOTOCD_SBA_SOURCE,),
        requires_sba=True,
    ),
    PhotoCdRecordDefinition(
        "SceneBalanceAlgorithmFilmID",
        325,
        2,
        "film_metadata",
        (PHOTOCD_SBA_SOURCE,),
        requires_sba=True,
    ),
    PhotoCdRecordDefinition(
        "CopyrightStatus",
        331,
        1,
        "rights_metadata",
        (PHOTOCD_SBA_SOURCE,),
        requires_sba=True,
    ),
    PhotoCdRecordDefinition(
        "CopyrightFileName",
        332,
        12,
        "rights_metadata",
        (PHOTOCD_SBA_SOURCE,),
        requires_sba=True,
        requires_copyright_restriction=True,
    ),
    PhotoCdRecordDefinition(
        "Orientation",
        1538,
        1,
        "image_size_resolution_metadata",
        (PHOTOCD_IMAGE_SIZE_SOURCE,),
    ),
)
