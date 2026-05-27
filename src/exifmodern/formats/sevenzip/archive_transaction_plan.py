"""Source-grounded, non-mutating 7Z archive transaction planning."""

from __future__ import annotations

import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.json_types import JsonArray, JsonObject

SEVENZIP_SIGNATURE = b"7z\xbc\xaf'\x1c"
SEVENZIP_SIGNATURE_SIZE = 6
SEVENZIP_START_HEADER_SIZE = 32
SEVENZIP_PM_SOURCE_PATH = "lib/Image/ExifTool/7Z.pm"

type SevenZipPlanStatus = Literal["planned", "unsupported"]
type SevenZipHeaderKind = Literal["normal", "encoded", "unknown", "missing"]
type SevenZipCoderAlgorithm = Literal["LZMA", "7zAES", "unsupported"]
type SevenZipArchiveResponsibility = Literal[
    "signature_validation",
    "version_tagging",
    "start_header_crc_preservation",
    "next_header_location",
    "next_header_crc_preservation",
    "normal_header_database",
    "encoded_header_database",
    "pack_info_preservation",
    "unpack_folder_metadata",
    "substreams_metadata",
    "files_info_database",
    "archive_file_property_database",
    "packed_stream_preservation",
    "unsupported_encryption_blocker",
    "unsupported_compression_blocker",
    "rewrite_blocker",
    "truncation_blocker",
    "crc_blocker",
    "output_emission_gate",
]
type SevenZipFilePropertyKind = Literal[
    "empty_stream",
    "empty_file",
    "name",
    "last_write_time",
    "attributes",
    "dummy",
    "unknown",
]
type SevenZipEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "truncated_signature",
    "unsupported_signature",
    "truncated_start_header",
    "start_header_crc_mismatch",
    "truncated_next_header",
    "next_header_crc_mismatch",
    "unknown_next_header_id",
    "invalid_header_pid",
    "truncated_header_database",
    "external_folder_blocker",
    "external_file_property_blocker",
    "encoded_header_decompression_required",
    "encrypted_header_blocker",
    "unsupported_compression_blocker",
    "archive_rewrite_not_implemented",
]

SEVENZIP_PROCESS_SOURCE = "sevenzip.process"
SEVENZIP_START_HEADER_SOURCE = "sevenzip.start_header"
SEVENZIP_NEXT_HEADER_SOURCE = "sevenzip.next_header"
SEVENZIP_ENCODED_HEADER_SOURCE = "sevenzip.encoded_header"
SEVENZIP_UINT64_SOURCE = "sevenzip.uint64"
SEVENZIP_BOOLEAN_SOURCE = "sevenzip.boolean"
SEVENZIP_PACK_INFO_SOURCE = "sevenzip.pack_info"
SEVENZIP_FOLDER_SOURCE = "sevenzip.folder"
SEVENZIP_CODERS_INFO_SOURCE = "sevenzip.coders_info"
SEVENZIP_UNPACK_INFO_SOURCE = "sevenzip.unpack_info"
SEVENZIP_SUBSTREAMS_SOURCE = "sevenzip.substreams"
SEVENZIP_STREAMS_INFO_SOURCE = "sevenzip.streams_info"
SEVENZIP_CODER_SOURCE = "sevenzip.coder"
SEVENZIP_FILE_INFO_SOURCE = "sevenzip.file_info"
SEVENZIP_EXTRACT_HEADER_SOURCE = "sevenzip.extract_header"
SEVENZIP_DISPLAY_FILES_SOURCE = "sevenzip.display_files"


@dataclass(frozen=True)
class SevenZipSignatureValidation:
    is_valid: bool
    signature_hex: str
    reason: SevenZipEmissionGateCode | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "is_valid": self.is_valid,
            "reason": self.reason,
            "signature_hex": self.signature_hex,
        }


@dataclass(frozen=True)
class SevenZipStartHeaderPlan:
    major_version: int | None
    minor_version: int | None
    file_version: str | None
    start_header_crc: int | None
    computed_start_header_crc: int | None
    next_header_offset: int | None
    next_header_size: int | None
    next_header_crc: int | None
    computed_next_header_crc: int | None
    next_header_absolute_offset: int | None
    is_valid: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "computed_next_header_crc": self.computed_next_header_crc,
            "computed_start_header_crc": self.computed_start_header_crc,
            "file_version": self.file_version,
            "is_valid": self.is_valid,
            "major_version": self.major_version,
            "minor_version": self.minor_version,
            "next_header_absolute_offset": self.next_header_absolute_offset,
            "next_header_crc": self.next_header_crc,
            "next_header_offset": self.next_header_offset,
            "next_header_size": self.next_header_size,
            "start_header_crc": self.start_header_crc,
        }


@dataclass(frozen=True)
class SevenZipPackedStreamPlan:
    index: int
    pack_position: int
    absolute_offset: int
    packed_size: int | None
    crc32: int | None
    crc_defined: bool
    preservation: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "absolute_offset": self.absolute_offset,
            "crc32": self.crc32,
            "crc_defined": self.crc_defined,
            "index": self.index,
            "pack_position": self.pack_position,
            "packed_size": self.packed_size,
            "preservation": self.preservation,
        }


@dataclass(frozen=True)
class SevenZipCoderPlan:
    index: int
    method_hex: str
    algorithm: SevenZipCoderAlgorithm
    num_in_streams: int
    num_out_streams: int
    properties_hex: str | None
    evidence_ids: tuple[str, ...]

    @property
    def is_encrypted(self) -> bool:
        return self.algorithm == "7zAES"

    @property
    def is_supported_for_header_decode(self) -> bool:
        return self.algorithm == "LZMA"

    def to_json(self) -> JsonObject:
        return {
            "algorithm": self.algorithm,
            "index": self.index,
            "is_encrypted": self.is_encrypted,
            "is_supported_for_header_decode": self.is_supported_for_header_decode,
            "method_hex": self.method_hex,
            "num_in_streams": self.num_in_streams,
            "num_out_streams": self.num_out_streams,
            "properties_hex": self.properties_hex,
        }


@dataclass(frozen=True)
class SevenZipFolderPlan:
    index: int
    coders: tuple[SevenZipCoderPlan, ...]
    bind_pairs: tuple[tuple[int, int], ...]
    packed_indices: tuple[int, ...]
    unpack_sizes: tuple[int, ...]
    crc32: int | None
    crc_defined: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "bind_pairs": [[in_index, out_index] for in_index, out_index in self.bind_pairs],
            "coders": json_object_array(coder.to_json() for coder in self.coders),
            "crc32": self.crc32,
            "crc_defined": self.crc_defined,
            "index": self.index,
            "packed_indices": list(self.packed_indices),
            "unpack_sizes": list(self.unpack_sizes),
        }


@dataclass(frozen=True)
class SevenZipStreamsInfoPlan:
    pack_position: int | None
    num_pack_streams: int
    packed_streams: tuple[SevenZipPackedStreamPlan, ...]
    folders: tuple[SevenZipFolderPlan, ...]
    num_unpack_streams_per_folder: tuple[int, ...]
    substream_unpack_sizes: tuple[int, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "folders": json_object_array(folder.to_json() for folder in self.folders),
            "num_pack_streams": self.num_pack_streams,
            "num_unpack_streams_per_folder": list(self.num_unpack_streams_per_folder),
            "pack_position": self.pack_position,
            "packed_streams": json_object_array(stream.to_json() for stream in self.packed_streams),
            "substream_unpack_sizes": list(self.substream_unpack_sizes),
        }


@dataclass(frozen=True)
class SevenZipArchiveFilePlan:
    index: int
    archived_file_name: str | None
    modify_date_windows_ticks: int | None
    attributes: int | None
    empty_stream: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "archived_file_name": self.archived_file_name,
            "attributes": self.attributes,
            "empty_stream": self.empty_stream,
            "index": self.index,
            "modify_date_windows_ticks": self.modify_date_windows_ticks,
        }


@dataclass(frozen=True)
class SevenZipFilePropertyPlan:
    property_id: int
    kind: SevenZipFilePropertyKind
    size: int
    external: bool | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "external": self.external,
            "kind": self.kind,
            "property_id": self.property_id,
            "size": self.size,
        }


@dataclass(frozen=True)
class SevenZipArchiveDatabasePlan:
    files: tuple[SevenZipArchiveFilePlan, ...]
    file_properties: tuple[SevenZipFilePropertyPlan, ...]
    streams_info: SevenZipStreamsInfoPlan | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "file_properties": json_object_array(
                property_plan.to_json() for property_plan in self.file_properties
            ),
            "files": json_object_array(file_plan.to_json() for file_plan in self.files),
            "streams_info": self.streams_info.to_json() if self.streams_info is not None else None,
        }


@dataclass(frozen=True)
class SevenZipNextHeaderPlan:
    kind: SevenZipHeaderKind
    property_id: int | None
    database: SevenZipArchiveDatabasePlan | None
    encoded_streams_info: SevenZipStreamsInfoPlan | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "database": self.database.to_json() if self.database is not None else None,
            "encoded_streams_info": (
                self.encoded_streams_info.to_json()
                if self.encoded_streams_info is not None
                else None
            ),
            "kind": self.kind,
            "property_id": self.property_id,
        }


@dataclass(frozen=True)
class SevenZipResponsibilityPlan:
    concern: SevenZipArchiveResponsibility
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SevenZipOutputEmissionGate:
    code: SevenZipEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SevenZipArchiveTransactionPlan:
    status: SevenZipPlanStatus
    original_bytes: bytes
    signature_validation: SevenZipSignatureValidation
    start_header: SevenZipStartHeaderPlan
    next_header: SevenZipNextHeaderPlan
    responsibilities: tuple[SevenZipResponsibilityPlan, ...]
    output_emission_gates: tuple[SevenZipOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"7Z archive transaction output is gated: {gate_codes}")
        return self.original_bytes

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "next_header": self.next_header.to_json(),
            "output_emission_gates": json_object_array(
                gate.to_json() for gate in self.output_emission_gates
            ),
            "responsibilities": json_object_array(
                responsibility.to_json() for responsibility in self.responsibilities
            ),
            "signature_validation": self.signature_validation.to_json(),
            "start_header": self.start_header.to_json(),
            "status": self.status,
        }


@dataclass(frozen=True)
class _FilesInfoParseResult:
    files: tuple[SevenZipArchiveFilePlan, ...]
    properties: tuple[SevenZipFilePropertyPlan, ...]


@dataclass(frozen=True)
class _UnpackInfoParseResult:
    folders: tuple[SevenZipFolderPlan, ...]
    num_folders: int


class _SevenZipParseError(ValueError):
    def __init__(
        self,
        code: SevenZipEmissionGateCode,
        reason: str,
        evidence_ids: tuple[str, ...],
    ) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.evidence_ids = evidence_ids


class _Reader:
    def __init__(self, data: bytes, base_offset: int = 0) -> None:
        self._data = data
        self._base_offset = base_offset
        self.offset = 0

    @property
    def remaining(self) -> int:
        return len(self._data) - self.offset

    @property
    def absolute_offset(self) -> int:
        return self._base_offset + self.offset

    def read(self, size: int, source: str) -> bytes:
        if size < 0 or self.offset + size > len(self._data):
            raise _SevenZipParseError(
                "truncated_header_database",
                "A 7Z header structure ended before the requested field was available.",
                (source,),
            )
        start = self.offset
        self.offset += size
        return self._data[start : start + size]

    def read_byte(self, source: str) -> int:
        return self.read(1, source)[0]

    def read_u32(self, source: str) -> int:
        return int.from_bytes(self.read(4, source), "little")

    def read_u64(self, source: str) -> int:
        return int.from_bytes(self.read(8, source), "little")

    def read_7z_uint64(self, source: str = SEVENZIP_UINT64_SOURCE) -> int:
        first = self.read_byte(source)
        if first == 0xFF:
            return self.read_u64(source)
        bounds = (0x7F, 0xBF, 0xDF, 0xEF, 0xF7, 0xFB, 0xFD, 0xFE)
        mask = 0x80
        value_length = 8
        for index, bound in enumerate(bounds):
            if first <= bound:
                value_length = index
                break
            mask >>= 1
        if value_length == 0:
            return first & (mask - 1)
        payload = self.read(value_length, source)
        value = int.from_bytes(payload.ljust(8, b"\0"), "little")
        high_part = first & (mask - 1)
        return value + (high_part << (value_length * 8))

    def read_booleans(
        self,
        count: int,
        check_all: bool,
        source: str = SEVENZIP_BOOLEAN_SOURCE,
    ) -> tuple[bool, ...]:
        if check_all:
            all_defined = self.read_byte(source)
            if all_defined != 0:
                return tuple(True for _ in range(count))
        values: list[bool] = []
        current = 0
        mask = 0
        for _ in range(count):
            if mask == 0:
                current = self.read_byte(source)
                mask = 0x80
            values.append(bool(current & mask))
            mask >>= 1
        return tuple(values)

    def read_utf16_name(self) -> str:
        chars = bytearray()
        for _ in range(65536):
            chunk = self.read(2, SEVENZIP_FILE_INFO_SOURCE)
            if chunk == b"\0\0":
                return chars.decode("utf-16le", errors="replace")
            chars.extend(chunk)
        return chars.decode("utf-16le", errors="replace")


def build_sevenzip_archive_transaction_plan(
    sevenzip_data: bytes,
    *,
    allow_output_emission: bool = False,
) -> SevenZipArchiveTransactionPlan:
    gates: list[SevenZipOutputEmissionGate] = []
    responsibilities: list[SevenZipResponsibilityPlan] = [
        responsibility(
            "signature_validation",
            "7Z archives must start with the exact six-byte 7z signature.",
            (SEVENZIP_PROCESS_SOURCE,),
        )
    ]
    signature_validation = validate_signature(sevenzip_data)
    if signature_validation.reason is not None:
        gates.append(
            gate(
                signature_validation.reason,
                "The 7Z signature is not usable.",
                signature_validation.evidence_ids,
            )
        )
        return finalize_plan(
            sevenzip_data,
            signature_validation,
            empty_start_header(),
            empty_next_header(),
            responsibilities,
            gates,
            allow_output_emission,
        )

    responsibilities.extend(
        (
            responsibility(
                "version_tagging",
                "7Z.pm exposes the major/minor version as FileVersion.",
                (SEVENZIP_PROCESS_SOURCE,),
            ),
            responsibility(
                "start_header_crc_preservation",
                "The start-header CRC protects the next-header location fields.",
                (SEVENZIP_START_HEADER_SOURCE,),
            ),
            responsibility(
                "next_header_location",
                "NextHeaderOffset and NextHeaderSize locate the archive database header.",
                (SEVENZIP_START_HEADER_SOURCE, SEVENZIP_NEXT_HEADER_SOURCE),
            ),
            responsibility(
                "next_header_crc_preservation",
                "The next-header CRC protects the header bytes that 7Z.pm parses.",
                (SEVENZIP_START_HEADER_SOURCE,),
            ),
        )
    )
    start_header = parse_start_header(sevenzip_data, gates)
    if start_header.next_header_absolute_offset is None or start_header.next_header_size is None:
        return finalize_plan(
            sevenzip_data,
            signature_validation,
            start_header,
            empty_next_header(),
            responsibilities,
            gates,
            allow_output_emission,
        )

    next_header = parse_next_header(sevenzip_data, start_header, gates, responsibilities)
    return finalize_plan(
        sevenzip_data,
        signature_validation,
        start_header,
        next_header,
        responsibilities,
        gates,
        allow_output_emission,
    )


plan_sevenzip_archive_transaction = build_sevenzip_archive_transaction_plan


def validate_signature(sevenzip_data: bytes) -> SevenZipSignatureValidation:
    if len(sevenzip_data) < SEVENZIP_SIGNATURE_SIZE:
        return SevenZipSignatureValidation(
            is_valid=False,
            signature_hex=sevenzip_data.hex(),
            reason="truncated_signature",
            evidence_ids=(SEVENZIP_PROCESS_SOURCE,),
        )
    signature = sevenzip_data[:SEVENZIP_SIGNATURE_SIZE]
    if signature != SEVENZIP_SIGNATURE:
        return SevenZipSignatureValidation(
            is_valid=False,
            signature_hex=signature.hex(),
            reason="unsupported_signature",
            evidence_ids=(SEVENZIP_PROCESS_SOURCE,),
        )
    return SevenZipSignatureValidation(
        is_valid=True,
        signature_hex=signature.hex(),
        reason=None,
        evidence_ids=(SEVENZIP_PROCESS_SOURCE,),
    )


def parse_start_header(
    sevenzip_data: bytes,
    gates: list[SevenZipOutputEmissionGate],
) -> SevenZipStartHeaderPlan:
    if len(sevenzip_data) < SEVENZIP_START_HEADER_SIZE:
        gates.append(
            gate(
                "truncated_start_header",
                "The 7Z start header is shorter than the fixed 32-byte header.",
                (SEVENZIP_START_HEADER_SOURCE,),
            )
        )
        return empty_start_header()
    major_version = sevenzip_data[6]
    minor_version = sevenzip_data[7]
    start_header_crc = int.from_bytes(sevenzip_data[8:12], "little")
    computed_start_header_crc = crc32_int(sevenzip_data[12:32])
    next_header_offset = int.from_bytes(sevenzip_data[12:20], "little")
    next_header_size = int.from_bytes(sevenzip_data[20:28], "little")
    next_header_crc = int.from_bytes(sevenzip_data[28:32], "little")
    absolute_offset = SEVENZIP_START_HEADER_SIZE + next_header_offset
    next_header_end = absolute_offset + next_header_size
    if start_header_crc != computed_start_header_crc:
        gates.append(
            gate(
                "start_header_crc_mismatch",
                "The stored start-header CRC does not match the next-header location fields.",
                (SEVENZIP_START_HEADER_SOURCE,),
            )
        )
    computed_next_header_crc: int | None = None
    if absolute_offset > len(sevenzip_data) or next_header_end > len(sevenzip_data):
        gates.append(
            gate(
                "truncated_next_header",
                "The next-header offset and size point past EOF.",
                (SEVENZIP_START_HEADER_SOURCE, SEVENZIP_NEXT_HEADER_SOURCE),
            )
        )
    else:
        computed_next_header_crc = crc32_int(sevenzip_data[absolute_offset:next_header_end])
        if next_header_crc != computed_next_header_crc:
            gates.append(
                gate(
                    "next_header_crc_mismatch",
                    "The stored next-header CRC does not match the parsed next-header bytes.",
                    (SEVENZIP_START_HEADER_SOURCE, SEVENZIP_NEXT_HEADER_SOURCE),
                )
            )
    return SevenZipStartHeaderPlan(
        major_version=major_version,
        minor_version=minor_version,
        file_version=f"7z v{major_version}.{minor_version:02d}",
        start_header_crc=start_header_crc,
        computed_start_header_crc=computed_start_header_crc,
        next_header_offset=next_header_offset,
        next_header_size=next_header_size,
        next_header_crc=next_header_crc,
        computed_next_header_crc=computed_next_header_crc,
        next_header_absolute_offset=absolute_offset,
        is_valid=not any(
            existing.code
            in {
                "truncated_start_header",
                "start_header_crc_mismatch",
                "truncated_next_header",
                "next_header_crc_mismatch",
            }
            for existing in gates
        ),
        evidence_ids=(SEVENZIP_PROCESS_SOURCE, SEVENZIP_START_HEADER_SOURCE),
    )


def parse_next_header(
    sevenzip_data: bytes,
    start_header: SevenZipStartHeaderPlan,
    gates: list[SevenZipOutputEmissionGate],
    responsibilities: list[SevenZipResponsibilityPlan],
) -> SevenZipNextHeaderPlan:
    if start_header.next_header_absolute_offset is None or start_header.next_header_size is None:
        return empty_next_header()
    start = start_header.next_header_absolute_offset
    end = start + start_header.next_header_size
    if start >= len(sevenzip_data) or end > len(sevenzip_data) or start == end:
        return empty_next_header()
    next_header_bytes = sevenzip_data[start:end]
    property_id = next_header_bytes[0]
    reader = _Reader(next_header_bytes[1:], start + 1)
    try:
        if property_id == 0x01:
            responsibilities.append(
                responsibility(
                    "normal_header_database",
                    "Normal 7Z headers carry streams info and files info directly.",
                    (SEVENZIP_NEXT_HEADER_SOURCE, SEVENZIP_EXTRACT_HEADER_SOURCE),
                )
            )
            database = parse_archive_database(reader, gates, responsibilities)
            return SevenZipNextHeaderPlan(
                kind="normal",
                property_id=property_id,
                database=database,
                encoded_streams_info=None,
                evidence_ids=(SEVENZIP_NEXT_HEADER_SOURCE, SEVENZIP_EXTRACT_HEADER_SOURCE),
            )
        if property_id == 0x17:
            responsibilities.append(
                responsibility(
                    "encoded_header_database",
                    "Encoded 7Z headers first describe packed streams and coder folders.",
                    (SEVENZIP_ENCODED_HEADER_SOURCE, SEVENZIP_STREAMS_INFO_SOURCE),
                )
            )
            streams_info = parse_streams_info(reader, gates, responsibilities)
            gates.append(
                gate(
                    "encoded_header_decompression_required",
                    (
                        "The encoded header database is preserve-only until a writer performs "
                        "decode/rebuild."
                    ),
                    (SEVENZIP_ENCODED_HEADER_SOURCE,),
                )
            )
            return SevenZipNextHeaderPlan(
                kind="encoded",
                property_id=property_id,
                database=None,
                encoded_streams_info=streams_info,
                evidence_ids=(SEVENZIP_ENCODED_HEADER_SOURCE, SEVENZIP_STREAMS_INFO_SOURCE),
            )
    except _SevenZipParseError as error:
        gates.append(gate(error.code, error.reason, error.evidence_ids))
        return SevenZipNextHeaderPlan(
            kind="unknown",
            property_id=property_id,
            database=None,
            encoded_streams_info=None,
            evidence_ids=error.evidence_ids,
        )
    gates.append(
        gate(
            "unknown_next_header_id",
            (
                "7Z.pm only dispatches normal header 0x01 and encoded header 0x17, "
                f"not 0x{property_id:02x}."
            ),
            (SEVENZIP_NEXT_HEADER_SOURCE, SEVENZIP_ENCODED_HEADER_SOURCE),
        )
    )
    return SevenZipNextHeaderPlan(
        kind="unknown",
        property_id=property_id,
        database=None,
        encoded_streams_info=None,
        evidence_ids=(SEVENZIP_NEXT_HEADER_SOURCE, SEVENZIP_ENCODED_HEADER_SOURCE),
    )


def parse_archive_database(
    reader: _Reader,
    gates: list[SevenZipOutputEmissionGate],
    responsibilities: list[SevenZipResponsibilityPlan],
) -> SevenZipArchiveDatabasePlan:
    streams_info: SevenZipStreamsInfoPlan | None = None
    files: tuple[SevenZipArchiveFilePlan, ...] = ()
    properties: tuple[SevenZipFilePropertyPlan, ...] = ()
    property_id = reader.read_byte(SEVENZIP_EXTRACT_HEADER_SOURCE)
    if property_id == 0x04:
        streams_info = parse_streams_info(reader, gates, responsibilities)
        property_id = reader.read_byte(SEVENZIP_EXTRACT_HEADER_SOURCE)
    if property_id == 0x05:
        responsibilities.append(
            responsibility(
                "files_info_database",
                "FilesInfo is the database for archived file names, dates and attributes.",
                (SEVENZIP_FILE_INFO_SOURCE, SEVENZIP_DISPLAY_FILES_SOURCE),
            )
        )
        files_info = parse_files_info(reader, gates)
        files = files_info.files
        properties = files_info.properties
        if properties:
            responsibilities.append(
                responsibility(
                    "archive_file_property_database",
                    "FileInfo properties form the archive file metadata database.",
                    (SEVENZIP_FILE_INFO_SOURCE,),
                )
            )
        property_id = reader.read_byte(SEVENZIP_EXTRACT_HEADER_SOURCE)
    if property_id != 0x00:
        raise _SevenZipParseError(
            "invalid_header_pid",
            f"ExtractHeaderInfo expected end property ID 0x00, not 0x{property_id:02x}.",
            (SEVENZIP_EXTRACT_HEADER_SOURCE,),
        )
    return SevenZipArchiveDatabasePlan(
        files=files,
        file_properties=properties,
        streams_info=streams_info,
        evidence_ids=unique_sources(
            (
                SEVENZIP_EXTRACT_HEADER_SOURCE,
                *(streams_info.evidence_ids if streams_info is not None else ()),
                *(source for file_plan in files for source in file_plan.evidence_ids),
                *(source for property_plan in properties for source in property_plan.evidence_ids),
            )
        ),
    )


def parse_streams_info(
    reader: _Reader,
    gates: list[SevenZipOutputEmissionGate],
    responsibilities: list[SevenZipResponsibilityPlan],
) -> SevenZipStreamsInfoPlan:
    pack_position: int | None = None
    pack_sizes: tuple[int, ...] = ()
    pack_crcs: tuple[int | None, ...] = ()
    pack_crc_defined: tuple[bool, ...] = ()
    folders: tuple[SevenZipFolderPlan, ...] = ()
    num_unpack_streams_per_folder: tuple[int, ...] = ()
    substream_unpack_sizes: tuple[int, ...] = ()
    property_id = reader.read_byte(SEVENZIP_STREAMS_INFO_SOURCE)
    if property_id == 0x06:
        responsibilities.append(
            responsibility(
                "pack_info_preservation",
                "PackInfo records packed stream locations, sizes and optional CRCs.",
                (SEVENZIP_PACK_INFO_SOURCE,),
            )
        )
        pack_position, pack_sizes, pack_crc_defined, pack_crcs = parse_pack_info(reader)
        property_id = reader.read_byte(SEVENZIP_STREAMS_INFO_SOURCE)
    if property_id == 0x07:
        responsibilities.append(
            responsibility(
                "unpack_folder_metadata",
                "UnpackInfo records folders, coders, bind pairs, unpack sizes and CRCs.",
                (SEVENZIP_UNPACK_INFO_SOURCE, SEVENZIP_FOLDER_SOURCE, SEVENZIP_CODERS_INFO_SOURCE),
            )
        )
        unpack_info = parse_unpack_info(reader, gates)
        folders = unpack_info.folders
        property_id = reader.read_byte(SEVENZIP_STREAMS_INFO_SOURCE)
    if property_id == 0x08:
        responsibilities.append(
            responsibility(
                "substreams_metadata",
                "SubstreamsInfo records per-folder stream counts, sizes and CRCs.",
                (SEVENZIP_SUBSTREAMS_SOURCE,),
            )
        )
        num_unpack_streams_per_folder, substream_unpack_sizes = parse_substreams_info(
            reader,
            folders,
        )
        property_id = reader.read_byte(SEVENZIP_STREAMS_INFO_SOURCE)
    if property_id != 0x00:
        raise _SevenZipParseError(
            "invalid_header_pid",
            f"ReadStreamsInfo expected end property ID 0x00, not 0x{property_id:02x}.",
            (SEVENZIP_STREAMS_INFO_SOURCE,),
        )
    packed_streams = tuple(
        SevenZipPackedStreamPlan(
            index=index,
            pack_position=pack_position if pack_position is not None else 0,
            absolute_offset=SEVENZIP_START_HEADER_SIZE
            + (pack_position if pack_position is not None else 0)
            + sum(pack_sizes[:index]),
            packed_size=size,
            crc32=pack_crcs[index] if index < len(pack_crcs) else None,
            crc_defined=pack_crc_defined[index] if index < len(pack_crc_defined) else False,
            preservation="preserve_packed_stream_without_rewrite",
            evidence_ids=(SEVENZIP_PACK_INFO_SOURCE, SEVENZIP_ENCODED_HEADER_SOURCE),
        )
        for index, size in enumerate(pack_sizes)
    )
    if packed_streams:
        responsibilities.append(
            responsibility(
                "packed_stream_preservation",
                "Packed streams are preserved at their 32-byte-header-relative pack positions.",
                (SEVENZIP_PACK_INFO_SOURCE, SEVENZIP_ENCODED_HEADER_SOURCE),
            )
        )
    return SevenZipStreamsInfoPlan(
        pack_position=pack_position,
        num_pack_streams=len(pack_sizes),
        packed_streams=packed_streams,
        folders=folders,
        num_unpack_streams_per_folder=num_unpack_streams_per_folder,
        substream_unpack_sizes=substream_unpack_sizes,
        evidence_ids=unique_sources(
            (
                SEVENZIP_STREAMS_INFO_SOURCE,
                SEVENZIP_PACK_INFO_SOURCE,
                SEVENZIP_UNPACK_INFO_SOURCE,
                SEVENZIP_SUBSTREAMS_SOURCE,
                *(source for folder in folders for source in folder.evidence_ids),
                *(source for stream in packed_streams for source in stream.evidence_ids),
            )
        ),
    )


def parse_pack_info(
    reader: _Reader,
) -> tuple[int, tuple[int, ...], tuple[bool, ...], tuple[int | None, ...]]:
    pack_position = reader.read_7z_uint64()
    num_streams = reader.read_7z_uint64()
    property_id = reader.read_byte(SEVENZIP_PACK_INFO_SOURCE)
    pack_sizes: list[int] = []
    crc_defined: tuple[bool, ...] = tuple(False for _ in range(num_streams))
    crcs: list[int | None] = [None for _ in range(num_streams)]
    if property_id == 0x09:
        for _ in range(num_streams):
            pack_sizes.append(reader.read_7z_uint64())
        property_id = reader.read_byte(SEVENZIP_PACK_INFO_SOURCE)
        if property_id == 0x0A:
            crc_defined = reader.read_booleans(num_streams, True)
            for index, is_defined in enumerate(crc_defined):
                if is_defined:
                    crcs[index] = reader.read_u32(SEVENZIP_PACK_INFO_SOURCE)
            property_id = reader.read_byte(SEVENZIP_PACK_INFO_SOURCE)
    if property_id != 0x00:
        raise _SevenZipParseError(
            "invalid_header_pid",
            f"ReadPackInfo expected end property ID 0x00, not 0x{property_id:02x}.",
            (SEVENZIP_PACK_INFO_SOURCE,),
        )
    return pack_position, tuple(pack_sizes), crc_defined, tuple(crcs)


def parse_unpack_info(
    reader: _Reader,
    gates: list[SevenZipOutputEmissionGate],
) -> _UnpackInfoParseResult:
    property_id = reader.read_byte(SEVENZIP_UNPACK_INFO_SOURCE)
    if property_id != 0x0B:
        raise _SevenZipParseError(
            "invalid_header_pid",
            f"ReadUnpackInfo expected folder ID 0x0b, not 0x{property_id:02x}.",
            (SEVENZIP_UNPACK_INFO_SOURCE,),
        )
    num_folders = reader.read_7z_uint64()
    external = reader.read_byte(SEVENZIP_UNPACK_INFO_SOURCE)
    if external != 0:
        gates.append(
            gate(
                "external_folder_blocker",
                "7Z.pm only reads folders inline when the external folder flag is zero.",
                (SEVENZIP_UNPACK_INFO_SOURCE,),
            )
        )
        return _UnpackInfoParseResult(folders=(), num_folders=num_folders)
    folders = [parse_folder(reader, index) for index in range(num_folders)]
    property_id = reader.read_byte(SEVENZIP_CODERS_INFO_SOURCE)
    if property_id != 0x0C:
        raise _SevenZipParseError(
            "invalid_header_pid",
            f"RetrieveCodersInfo expected unpack size ID 0x0c, not 0x{property_id:02x}.",
            (SEVENZIP_CODERS_INFO_SOURCE,),
        )
    folders = [
        folder_with_unpack_sizes(
            folder,
            tuple(
                reader.read_7z_uint64()
                for coder in folder.coders
                for _ in range(coder.num_out_streams)
            ),
        )
        for folder in folders
    ]
    property_id = reader.read_byte(SEVENZIP_CODERS_INFO_SOURCE)
    if property_id == 0x0A:
        defined = reader.read_booleans(num_folders, True)
        crc_values: list[int | None] = [None for _ in range(num_folders)]
        for index, is_defined in enumerate(defined):
            if is_defined:
                crc_values[index] = reader.read_u32(SEVENZIP_CODERS_INFO_SOURCE)
        folders = [
            folder_with_crc(folder, defined[index], crc_values[index])
            for index, folder in enumerate(folders)
        ]
        property_id = reader.read_byte(SEVENZIP_CODERS_INFO_SOURCE)
    if property_id != 0x00:
        raise _SevenZipParseError(
            "invalid_header_pid",
            f"RetrieveCodersInfo expected end property ID 0x00, not 0x{property_id:02x}.",
            (SEVENZIP_CODERS_INFO_SOURCE,),
        )
    return _UnpackInfoParseResult(folders=tuple(folders), num_folders=num_folders)


def parse_folder(reader: _Reader, index: int) -> SevenZipFolderPlan:
    num_coders = reader.read_7z_uint64()
    coders: list[SevenZipCoderPlan] = []
    total_in = 0
    total_out = 0
    for coder_index in range(num_coders):
        first = reader.read_byte(SEVENZIP_FOLDER_SOURCE)
        method_size = first & 0x0F
        is_complex = bool(first & 0x10)
        has_attributes = bool(first & 0x20)
        method = reader.read(method_size, SEVENZIP_FOLDER_SOURCE) if method_size > 0 else b"\0"
        if is_complex:
            num_in_streams = reader.read_7z_uint64()
            num_out_streams = reader.read_7z_uint64()
        else:
            num_in_streams = 1
            num_out_streams = 1
        total_in += num_in_streams
        total_out += num_out_streams
        properties: bytes | None = None
        if has_attributes:
            properties_length = reader.read_7z_uint64()
            properties = reader.read(properties_length, SEVENZIP_FOLDER_SOURCE)
        coders.append(
            SevenZipCoderPlan(
                index=coder_index,
                method_hex=method.hex(),
                algorithm=coder_algorithm(method),
                num_in_streams=num_in_streams,
                num_out_streams=num_out_streams,
                properties_hex=properties.hex() if properties is not None else None,
                evidence_ids=(SEVENZIP_FOLDER_SOURCE, SEVENZIP_CODER_SOURCE),
            )
        )
    bind_pairs: list[tuple[int, int]] = []
    for _ in range(total_out - 1):
        bind_pairs.append((reader.read_7z_uint64(), reader.read_7z_uint64()))
    num_packed_streams = total_in - len(bind_pairs)
    if num_packed_streams == 1:
        bound_in_indices = {in_index for in_index, _ in bind_pairs}
        packed_indices = tuple(index for index in range(total_in) if index not in bound_in_indices)
    else:
        packed_indices = tuple(reader.read_7z_uint64() for _ in range(num_packed_streams))
    return SevenZipFolderPlan(
        index=index,
        coders=tuple(coders),
        bind_pairs=tuple(bind_pairs),
        packed_indices=packed_indices,
        unpack_sizes=(),
        crc32=None,
        crc_defined=False,
        evidence_ids=(SEVENZIP_FOLDER_SOURCE, SEVENZIP_CODER_SOURCE),
    )


def parse_substreams_info(
    reader: _Reader,
    folders: tuple[SevenZipFolderPlan, ...],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    property_id = reader.read_byte(SEVENZIP_SUBSTREAMS_SOURCE)
    if property_id == 0x0D:
        num_unpack_streams = tuple(reader.read_7z_uint64() for _ in folders)
        property_id = reader.read_byte(SEVENZIP_SUBSTREAMS_SOURCE)
    else:
        num_unpack_streams = tuple(1 for _ in folders)
    unpack_sizes: list[int] = []
    if property_id == 0x09:
        for stream_count in num_unpack_streams:
            for _ in range(1, stream_count):
                unpack_sizes.append(reader.read_7z_uint64())
        property_id = reader.read_byte(SEVENZIP_SUBSTREAMS_SOURCE)
    num_digests = sum(
        stream_count
        for folder, stream_count in zip(folders, num_unpack_streams, strict=True)
        if stream_count != 1 or not folder.crc_defined
    )
    if property_id == 0x0A:
        defined = reader.read_booleans(num_digests, True)
        for is_defined in defined:
            if is_defined:
                reader.read_u32(SEVENZIP_SUBSTREAMS_SOURCE)
        property_id = reader.read_byte(SEVENZIP_SUBSTREAMS_SOURCE)
    if property_id != 0x00:
        raise _SevenZipParseError(
            "invalid_header_pid",
            f"ReadSubstreamsInfo expected end property ID 0x00, not 0x{property_id:02x}.",
            (SEVENZIP_SUBSTREAMS_SOURCE,),
        )
    return num_unpack_streams, tuple(unpack_sizes)


def parse_files_info(
    reader: _Reader,
    gates: list[SevenZipOutputEmissionGate],
) -> _FilesInfoParseResult:
    num_files = reader.read_7z_uint64()
    file_builders = [
        SevenZipArchiveFilePlan(
            index=index,
            archived_file_name=None,
            modify_date_windows_ticks=None,
            attributes=None,
            empty_stream=False,
            evidence_ids=(SEVENZIP_FILE_INFO_SOURCE, SEVENZIP_DISPLAY_FILES_SOURCE),
        )
        for index in range(num_files)
    ]
    properties: list[SevenZipFilePropertyPlan] = []
    while True:
        property_id = reader.read_byte(SEVENZIP_FILE_INFO_SOURCE)
        if property_id == 0x00:
            return _FilesInfoParseResult(files=tuple(file_builders), properties=tuple(properties))
        size = reader.read_7z_uint64()
        payload = reader.read(size, SEVENZIP_FILE_INFO_SOURCE)
        property_reader = _Reader(payload, reader.absolute_offset - size)
        property_plan, file_builders = apply_file_property(
            property_id,
            size,
            property_reader,
            file_builders,
            gates,
        )
        properties.append(property_plan)


def apply_file_property(
    property_id: int,
    size: int,
    property_reader: _Reader,
    files: list[SevenZipArchiveFilePlan],
    gates: list[SevenZipOutputEmissionGate],
) -> tuple[SevenZipFilePropertyPlan, list[SevenZipArchiveFilePlan]]:
    kind = file_property_kind(property_id)
    external: bool | None = None
    if property_id == 0x0E:
        empty_streams = property_reader.read_booleans(len(files), False)
        files = [
            replace_file(file_plan, empty_stream=empty_streams[file_plan.index])
            for file_plan in files
        ]
    elif property_id == 0x11:
        external = property_reader.read_byte(SEVENZIP_FILE_INFO_SOURCE) != 0
        if external:
            gates.append(external_property_gate("name"))
        else:
            names = tuple(property_reader.read_utf16_name() for _ in files)
            files = [
                replace_file(file_plan, archived_file_name=names[file_plan.index])
                for file_plan in files
            ]
    elif property_id == 0x14:
        defined = property_reader.read_booleans(len(files), True)
        external = property_reader.read_byte(SEVENZIP_FILE_INFO_SOURCE) != 0
        if external:
            gates.append(external_property_gate("last write time"))
        else:
            ticks: list[int | None] = []
            for is_defined in defined:
                ticks.append(
                    property_reader.read_u64(SEVENZIP_FILE_INFO_SOURCE) if is_defined else None
                )
            files = [
                replace_file(file_plan, modify_date_windows_ticks=ticks[file_plan.index])
                for file_plan in files
            ]
    elif property_id == 0x15:
        defined = property_reader.read_booleans(len(files), True)
        external = property_reader.read_byte(SEVENZIP_FILE_INFO_SOURCE) != 0
        if external:
            gates.append(external_property_gate("attributes"))
        else:
            attributes: list[int | None] = []
            for is_defined in defined:
                attributes.append(
                    property_reader.read_u32(SEVENZIP_FILE_INFO_SOURCE) >> 8 if is_defined else None
                )
            files = [
                replace_file(file_plan, attributes=attributes[file_plan.index])
                for file_plan in files
            ]
    return (
        SevenZipFilePropertyPlan(
            property_id=property_id,
            kind=kind,
            size=size,
            external=external,
            evidence_ids=(SEVENZIP_FILE_INFO_SOURCE, SEVENZIP_BOOLEAN_SOURCE),
        ),
        files,
    )


def finalize_plan(
    sevenzip_data: bytes,
    signature_validation: SevenZipSignatureValidation,
    start_header: SevenZipStartHeaderPlan,
    next_header: SevenZipNextHeaderPlan,
    responsibilities: list[SevenZipResponsibilityPlan],
    gates: list[SevenZipOutputEmissionGate],
    allow_output_emission: bool,
) -> SevenZipArchiveTransactionPlan:
    append_coder_blockers(next_header, gates, responsibilities)
    if not allow_output_emission:
        gates.append(
            gate(
                "non_mutating_plan_requires_explicit_emission",
                (
                    "7Z archive transaction plans are non-mutating unless emission is "
                    "explicitly allowed."
                ),
                (SEVENZIP_EXTRACT_HEADER_SOURCE,),
            )
        )
        responsibilities.append(
            responsibility(
                "output_emission_gate",
                "Output emission is gated unless the caller explicitly opts in.",
                (SEVENZIP_EXTRACT_HEADER_SOURCE,),
            )
        )
    if any(gate_item.code == "archive_rewrite_not_implemented" for gate_item in gates):
        responsibilities.append(
            responsibility(
                "rewrite_blocker",
                "A full 7Z archive rewrite engine is outside this non-mutating planner.",
                (SEVENZIP_EXTRACT_HEADER_SOURCE,),
            )
        )
    for gate_item in gates:
        if gate_item.code in {
            "truncated_signature",
            "truncated_start_header",
            "truncated_next_header",
            "truncated_header_database",
        }:
            responsibilities.append(
                responsibility(
                    "truncation_blocker",
                    "Truncated 7Z structures block safe archive emission.",
                    gate_item.evidence_ids,
                )
            )
        if gate_item.code in {"start_header_crc_mismatch", "next_header_crc_mismatch"}:
            responsibilities.append(
                responsibility(
                    "crc_blocker",
                    "CRC mismatches block safe archive emission.",
                    gate_item.evidence_ids,
                )
            )
    output_gates = unique_gates(tuple(gates))
    sources = unique_sources(
        (
            *signature_validation.evidence_ids,
            *start_header.evidence_ids,
            *next_header_sources(next_header),
            *(source for item in responsibilities for source in item.evidence_ids),
            *(source for item in output_gates for source in item.evidence_ids),
        )
    )
    return SevenZipArchiveTransactionPlan(
        status="unsupported" if structural_gate_exists(output_gates) else "planned",
        original_bytes=sevenzip_data,
        signature_validation=signature_validation,
        start_header=start_header,
        next_header=next_header,
        responsibilities=unique_responsibilities(tuple(responsibilities)),
        output_emission_gates=output_gates,
        evidence_ids=sources,
    )


def append_coder_blockers(
    next_header: SevenZipNextHeaderPlan,
    gates: list[SevenZipOutputEmissionGate],
    responsibilities: list[SevenZipResponsibilityPlan],
) -> None:
    streams_infos = (
        (next_header.encoded_streams_info,)
        if next_header.encoded_streams_info is not None
        else ((next_header.database.streams_info,) if next_header.database is not None else ())
    )
    for streams_info in streams_infos:
        if streams_info is None:
            continue
        for folder in streams_info.folders:
            for coder in folder.coders:
                if coder.is_encrypted:
                    gates.append(
                        gate(
                            "encrypted_header_blocker",
                            (
                                "7Z.pm warns and stops decompressor construction for 7zAES "
                                "encrypted coders."
                            ),
                            (SEVENZIP_CODER_SOURCE,),
                        )
                    )
                    responsibilities.append(
                        responsibility(
                            "unsupported_encryption_blocker",
                            "Encrypted 7Z coder chains cannot be safely rewritten by this planner.",
                            (SEVENZIP_CODER_SOURCE,),
                        )
                    )
                elif not coder.is_supported_for_header_decode:
                    gates.append(
                        gate(
                            "unsupported_compression_blocker",
                            (
                                "7Z.pm only identifies native LZMA and 7zAES methods for header "
                                "decoding."
                            ),
                            (SEVENZIP_CODER_SOURCE,),
                        )
                    )
                    responsibilities.append(
                        responsibility(
                            "unsupported_compression_blocker",
                            "Unknown 7Z coder methods are preserve-only and block rewrite.",
                            (SEVENZIP_CODER_SOURCE,),
                        )
                    )


def next_header_sources(next_header: SevenZipNextHeaderPlan) -> tuple[str, ...]:
    return unique_sources(
        (
            *next_header.evidence_ids,
            *(next_header.database.evidence_ids if next_header.database is not None else ()),
            *(
                next_header.encoded_streams_info.evidence_ids
                if next_header.encoded_streams_info is not None
                else ()
            ),
        )
    )


def folder_with_unpack_sizes(
    folder: SevenZipFolderPlan,
    unpack_sizes: tuple[int, ...],
) -> SevenZipFolderPlan:
    return SevenZipFolderPlan(
        index=folder.index,
        coders=folder.coders,
        bind_pairs=folder.bind_pairs,
        packed_indices=folder.packed_indices,
        unpack_sizes=unpack_sizes,
        crc32=folder.crc32,
        crc_defined=folder.crc_defined,
        evidence_ids=folder.evidence_ids,
    )


def folder_with_crc(
    folder: SevenZipFolderPlan,
    crc_defined: bool,
    crc32: int | None,
) -> SevenZipFolderPlan:
    return SevenZipFolderPlan(
        index=folder.index,
        coders=folder.coders,
        bind_pairs=folder.bind_pairs,
        packed_indices=folder.packed_indices,
        unpack_sizes=folder.unpack_sizes,
        crc32=crc32,
        crc_defined=crc_defined,
        evidence_ids=folder.evidence_ids,
    )


def replace_file(
    file_plan: SevenZipArchiveFilePlan,
    *,
    archived_file_name: str | None = None,
    modify_date_windows_ticks: int | None = None,
    attributes: int | None = None,
    empty_stream: bool | None = None,
) -> SevenZipArchiveFilePlan:
    return SevenZipArchiveFilePlan(
        index=file_plan.index,
        archived_file_name=(
            file_plan.archived_file_name if archived_file_name is None else archived_file_name
        ),
        modify_date_windows_ticks=(
            file_plan.modify_date_windows_ticks
            if modify_date_windows_ticks is None
            else modify_date_windows_ticks
        ),
        attributes=file_plan.attributes if attributes is None else attributes,
        empty_stream=file_plan.empty_stream if empty_stream is None else empty_stream,
        evidence_ids=file_plan.evidence_ids,
    )


def coder_algorithm(method: bytes) -> SevenZipCoderAlgorithm:
    if method == b"\x03\x01\x01":
        return "LZMA"
    if method == b"\x06\xf1\x07\x01":
        return "7zAES"
    return "unsupported"


def file_property_kind(property_id: int) -> SevenZipFilePropertyKind:
    if property_id == 0x0E:
        return "empty_stream"
    if property_id == 0x0F:
        return "empty_file"
    if property_id == 0x11:
        return "name"
    if property_id == 0x14:
        return "last_write_time"
    if property_id == 0x15:
        return "attributes"
    if property_id == 0x19:
        return "dummy"
    return "unknown"


def crc32_int(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def empty_start_header() -> SevenZipStartHeaderPlan:
    return SevenZipStartHeaderPlan(
        major_version=None,
        minor_version=None,
        file_version=None,
        start_header_crc=None,
        computed_start_header_crc=None,
        next_header_offset=None,
        next_header_size=None,
        next_header_crc=None,
        computed_next_header_crc=None,
        next_header_absolute_offset=None,
        is_valid=False,
        evidence_ids=(SEVENZIP_START_HEADER_SOURCE,),
    )


def empty_next_header() -> SevenZipNextHeaderPlan:
    return SevenZipNextHeaderPlan(
        kind="missing",
        property_id=None,
        database=None,
        encoded_streams_info=None,
        evidence_ids=(SEVENZIP_NEXT_HEADER_SOURCE,),
    )


def gate(
    code: SevenZipEmissionGateCode,
    reason: str,
    evidence_ids: tuple[str, ...],
) -> SevenZipOutputEmissionGate:
    return SevenZipOutputEmissionGate(
        code=code,
        reason=reason,
        evidence_ids=evidence_ids,
    )


def external_property_gate(property_name: str) -> SevenZipOutputEmissionGate:
    return gate(
        "external_file_property_blocker",
        f"7Z.pm only reads inline {property_name} properties with external flag zero.",
        (SEVENZIP_FILE_INFO_SOURCE,),
    )


def responsibility(
    concern: SevenZipArchiveResponsibility,
    reason: str,
    evidence_ids: tuple[str, ...],
) -> SevenZipResponsibilityPlan:
    return SevenZipResponsibilityPlan(
        concern=concern,
        reason=reason,
        evidence_ids=evidence_ids,
    )


def structural_gate_exists(gates: tuple[SevenZipOutputEmissionGate, ...]) -> bool:
    return any(
        gate_item.code != "non_mutating_plan_requires_explicit_emission" for gate_item in gates
    )


def unique_gates(
    gates: tuple[SevenZipOutputEmissionGate, ...],
) -> tuple[SevenZipOutputEmissionGate, ...]:
    unique: list[SevenZipOutputEmissionGate] = []
    seen: set[SevenZipEmissionGateCode] = set()
    for gate_item in gates:
        if gate_item.code not in seen:
            unique.append(gate_item)
            seen.add(gate_item.code)
    return tuple(unique)


def unique_responsibilities(
    responsibilities: tuple[SevenZipResponsibilityPlan, ...],
) -> tuple[SevenZipResponsibilityPlan, ...]:
    unique: list[SevenZipResponsibilityPlan] = []
    seen: set[SevenZipArchiveResponsibility] = set()
    for item in responsibilities:
        if item.concern not in seen:
            unique.append(item)
            seen.add(item.concern)
    return tuple(unique)


def unique_sources(sources: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    for source in sources:
        if source not in unique:
            unique.append(source)
    return tuple(unique)


def json_object_array(values: Iterable[JsonObject]) -> JsonArray:
    return [value for value in values]


install_evidence_reference_compat(globals())
