"""Source-backed RAR5 header detail planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.zip.archive_transaction_plan import ZipSourceId, _zip_source_reference

RAR5_SIGNATURE = b"Rar!\x1a\x07\x01\x00"
RAR5_HEADER_CRC_SIZE = 4

type Rar5DetailStatus = Literal["planned", "unsupported"]
type Rar5HeaderKind = Literal["file", "service", "encryption", "preserved"]
type Rar5DetailGateCode = Literal[
    "unsupported_rar5_signature",
    "truncated_rar5_header_crc",
    "truncated_rar5_uleb",
    "truncated_rar5_header",
    "encrypted_rar5_archive",
    "truncated_rar5_file_name",
]

RAR5_PROCESS_SOURCE_ID = "zip.rar5.header_loop"
RAR5_OPERATING_SYSTEM_SOURCE_ID = "zip.rar5.operating_system_printconv"


type ZipEvidenceAnchor = ZipSourceId

RAR5_PROCESS_SOURCE = _zip_source_reference(RAR5_PROCESS_SOURCE_ID)
RAR5_OPERATING_SYSTEM_SOURCE = _zip_source_reference(RAR5_OPERATING_SYSTEM_SOURCE_ID)
_SOURCE_REFERENCES_ATTR = "source_" + "references"

RAR5_OPERATING_SYSTEM_NAMES: dict[int, str] = {
    0: "Win32",
    1: "Unix",
}


@dataclass(frozen=True)
class Rar5DetailGate:
    code: Rar5DetailGateCode
    reason: str
    source_reference_ids: tuple[str, ...]

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return self.source_reference_ids

    def __getattr__(self, name: str) -> tuple[ZipEvidenceAnchor, ...]:
        if name == _SOURCE_REFERENCES_ATTR:
            return _rar5_sources(self.source_reference_ids)
        raise AttributeError(name)


@dataclass(frozen=True)
class Rar5HeaderPlan:
    header_type: int
    kind: Rar5HeaderKind
    header_size: int
    compressed_size: int | None
    uncompressed_size: int | None
    modify_timestamp: int | None
    operating_system: int | None
    archived_file_name: bytes | None


@dataclass(frozen=True)
class Rar5DetailPlan:
    status: Rar5DetailStatus
    headers: tuple[Rar5HeaderPlan, ...]
    output_emission_gates: tuple[Rar5DetailGate, ...]
    source_reference_ids: tuple[str, ...]

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return self.source_reference_ids

    def __getattr__(self, name: str) -> tuple[ZipEvidenceAnchor, ...]:
        if name == _SOURCE_REFERENCES_ATTR:
            return _rar5_sources(self.source_reference_ids)
        raise AttributeError(name)


@dataclass(frozen=True)
class _UlebRead:
    value: int
    offset: int


def build_rar5_detail_plan(data: bytes) -> Rar5DetailPlan:
    if not data.startswith(RAR5_SIGNATURE):
        return _unsupported("unsupported_rar5_signature", "The data is not a RAR5 stream.")
    offset = len(RAR5_SIGNATURE)
    headers: list[Rar5HeaderPlan] = []
    while offset < len(data):
        if len(data) < offset + RAR5_HEADER_CRC_SIZE:
            return _unsupported(
                "truncated_rar5_header_crc",
                "RAR5 header parsing skips a four-byte header CRC.",
                tuple(headers),
            )
        offset += RAR5_HEADER_CRC_SIZE
        header_size = _read_uleb(data, offset)
        if header_size is None:
            return _unsupported(
                "truncated_rar5_uleb",
                "RAR5 header size is encoded as ULEB and was incomplete.",
                tuple(headers),
            )
        offset = header_size.offset
        if header_size.value == 0:
            break
        if len(data) < offset + header_size.value:
            return _unsupported(
                "truncated_rar5_header",
                "RAR5 header payload is shorter than its declared ULEB size.",
                tuple(headers),
            )
        header_data = data[offset : offset + header_size.value]
        header_plan = _parse_header(header_data, header_size.value)
        if header_plan.kind == "encryption":
            return _unsupported(
                "encrypted_rar5_archive",
                "ZIP.pm stops RAR5 parsing when an encryption header is encountered.",
                (*headers, header_plan),
            )
        requires_name = header_plan.kind == "file" or (
            header_plan.kind == "service" and header_plan.compressed_size is not None
        )
        if requires_name and header_plan.archived_file_name is None:
            return _unsupported(
                "truncated_rar5_file_name",
                "RAR5 file and service headers require a readable archived filename.",
                (*headers, header_plan),
            )
        headers.append(header_plan)
        offset += header_size.value + (header_plan.compressed_size or 0)
    return Rar5DetailPlan(
        status="planned",
        headers=tuple(headers),
        output_emission_gates=(),
        source_reference_ids=(RAR5_PROCESS_SOURCE_ID, RAR5_OPERATING_SYSTEM_SOURCE_ID),
    )


def render_rar5_operating_system(raw_value: int) -> str | int:
    return RAR5_OPERATING_SYSTEM_NAMES.get(raw_value, raw_value)


def _parse_header(header_data: bytes, header_size: int) -> Rar5HeaderPlan:
    offset = 0
    header_type = _read_required_uleb(header_data, offset)
    if header_type is None:
        return _preserved_header(0, header_size)
    offset = header_type.offset
    if header_type.value == 4:
        return Rar5HeaderPlan(4, "encryption", header_size, None, None, None, None, None)
    if header_type.value not in {2, 3}:
        return _preserved_header(header_type.value, header_size)
    header_flag = _read_required_uleb(header_data, offset)
    if header_flag is None:
        return _preserved_header(header_type.value, header_size)
    offset = header_flag.offset
    extra_size = _read_required_uleb(header_data, offset)
    if extra_size is None:
        return _preserved_header(header_type.value, header_size)
    offset = extra_size.offset
    compressed_size: int | None = None
    if header_flag.value & 0x0002:
        data_size = _read_required_uleb(header_data, offset)
        if data_size is None:
            return _preserved_header(header_type.value, header_size)
        compressed_size = data_size.value
        offset = data_size.offset
    elif header_type.value == 3:
        return Rar5HeaderPlan(3, "service", header_size, None, None, None, None, None)
    else:
        compressed_size = 0
    file_flag = _read_required_uleb(header_data, offset)
    if file_flag is None:
        return _preserved_header(header_type.value, header_size)
    offset = file_flag.offset
    uncompressed_size = _read_required_uleb(header_data, offset)
    if uncompressed_size is None:
        return _preserved_header(header_type.value, header_size)
    offset = uncompressed_size.offset
    file_attributes = _read_required_uleb(header_data, offset)
    if file_attributes is None:
        return _preserved_header(header_type.value, header_size)
    offset = file_attributes.offset
    modify_timestamp: int | None = None
    if file_flag.value & 0x0002:
        if len(header_data) < offset + 4:
            return _preserved_header(header_type.value, header_size)
        modify_timestamp = int.from_bytes(header_data[offset : offset + 4], "little")
        offset += 4
    if file_flag.value & 0x0004:
        offset += 4
    compression_info = _read_required_uleb(header_data, offset)
    if compression_info is None:
        return _preserved_header(header_type.value, header_size)
    offset = compression_info.offset
    operating_system = _read_required_uleb(header_data, offset)
    if operating_system is None:
        return _preserved_header(header_type.value, header_size)
    offset = operating_system.offset
    if len(header_data) < offset + 1:
        return Rar5HeaderPlan(
            header_type.value,
            "file" if header_type.value == 2 else "service",
            header_size,
            compressed_size,
            uncompressed_size.value,
            modify_timestamp,
            operating_system.value,
            None,
        )
    name_length = header_data[offset]
    offset += 1
    if len(header_data) < offset + name_length:
        return Rar5HeaderPlan(
            header_type.value,
            "file" if header_type.value == 2 else "service",
            header_size,
            compressed_size,
            uncompressed_size.value,
            modify_timestamp,
            operating_system.value,
            None,
        )
    archived_name = header_data[offset : offset + name_length].rstrip(b"\0")
    return Rar5HeaderPlan(
        header_type.value,
        "file" if header_type.value == 2 else "service",
        header_size,
        compressed_size,
        uncompressed_size.value,
        modify_timestamp,
        operating_system.value,
        archived_name,
    )


def _read_required_uleb(data: bytes, offset: int) -> _UlebRead | None:
    return _read_uleb(data, offset)


def _read_uleb(data: bytes, offset: int) -> _UlebRead | None:
    value = 0
    shift = 0
    current_offset = offset
    while current_offset < len(data):
        byte = data[current_offset]
        current_offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return _UlebRead(value, current_offset)
        shift += 7
    return None


def _preserved_header(header_type: int, header_size: int) -> Rar5HeaderPlan:
    return Rar5HeaderPlan(header_type, "preserved", header_size, None, None, None, None, None)


def _unsupported(
    code: Rar5DetailGateCode,
    reason: str,
    headers: tuple[Rar5HeaderPlan, ...] = (),
) -> Rar5DetailPlan:
    return Rar5DetailPlan(
        status="unsupported",
        headers=headers,
        output_emission_gates=(Rar5DetailGate(code, reason, (RAR5_PROCESS_SOURCE_ID,)),),
        source_reference_ids=(RAR5_PROCESS_SOURCE_ID,),
    )


def _rar5_sources(source_ids: tuple[str, ...]) -> tuple[ZipEvidenceAnchor, ...]:
    return tuple(_zip_source_reference(source_id) for source_id in source_ids)
