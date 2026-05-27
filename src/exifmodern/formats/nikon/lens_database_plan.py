"""Source-backed Nikon lens identity database extraction planning.

This module models the Nikon lens identity pieces in ExifTool's Nikon.pm
without mutating files or generating a committed database.  It provides typed
structures for the LensID table, LensData layouts that feed the composite
LensID key, and small adapters for safely feeding Nikon keys into the shared
``services.lens_identity`` table resolver.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.json_types import JsonObject
from exifmodern.services.lens_identity import LensIdentityEntry, LensIdentityTable

type NikonLensDataTableName = Literal[
    "LensData00",
    "LensData01",
    "LensData0204",
    "LensData0400",
    "LensData0402",
    "LensData0403",
    "LensData0800",
]
type NikonLensIdentitySurface = Literal["classic_composite", "z_lensdata0800"]
type NikonLensFallbackKind = Literal[
    "exact",
    "decimal_variant",
    "lens_fstops",
    "lens_id_number",
    "lens_type_high_nibble",
    "no_match",
]
type NikonLensRuntimeGateCode = Literal[
    "requires_source_table",
    "requires_full_composite_lens_id_key",
    "requires_decimal_variant_bridge",
    "requires_prefix_adapter_for_xmp",
    "requires_z_lensdata0800_new_lens_id",
]
type NikonLensIdentityReadFactValue = str | int | float
type NikonLensIdentityReadFactEmissionStatus = Literal[
    "emitted",
    "missing_required_fact",
    "invalid_required_fact",
    "unsupported_lens_data_table",
    "truncated_lens_data",
    "truncated_version",
    "unsupported_version",
    "encrypted_needs_key",
    "encrypted_decryption_blocked",
]
type NikonLensDataDecodeReadinessStatus = Literal[
    "clear_decoded_lens_data",
    "encrypted_needs_key",
    "encrypted_ready_for_decryption",
    "encrypted_already_decoded",
    "truncated_version",
    "unsupported_version",
]
type NikonLensDataDecodeKeyStatus = Literal[
    "not_required",
    "missing_serial",
    "missing_shutter_count",
    "invalid_serial",
    "invalid_shutter_count",
    "ready",
]
type NikonLensDataPendingDecryptionStatus = Literal[
    "not_required",
    "blocked",
    "pending_algorithm_port",
    "ready_for_byte_decryption",
]

NIKON_PM_PATH = "lib/Image/ExifTool/Nikon.pm"
NIKON_LENS_ID_COMPONENT_COUNT = 8
NIKON_LENS_ID_TABLE_SOURCE_ID = "nikon.lens_database.lens_id_table"
NIKON_LENS_ID_NOTES_SOURCE_ID = "nikon.lens_database.lens_id_notes"
NIKON_LENS_TYPE_SOURCE_ID = "nikon.lens_database.lens_type"
NIKON_LENS_SPEC_SOURCE_ID = "nikon.lens_database.lens_spec"
NIKON_LENS_ID_CONV_SOURCE_ID = "nikon.lens_database.lens_id_conv"
NIKON_LENS_DATA_SOURCE_ID = "nikon.lens_database.lens_data_tables"
NIKON_LENS_DATA_ROUTING_SOURCE_ID = "nikon.lens_database.lens_data_routing"
NIKON_LENS_DATA_DECRYPTION_SOURCE_ID = "nikon.lens_database.lens_data_decryption_gate"
NIKON_SERIAL_KEY_SOURCE_ID = "nikon.lens_database.serial_key"
NIKON_MAKERNOTE_PRESCAN_SOURCE_ID = "nikon.lens_database.makernote_prescan"
NIKON_LENS_DATA_DECRYPT_ALGORITHM_SOURCE_ID = "nikon.lens_database.decrypt_algorithm"
NIKON_LENS_DATA_DECRYPT_RANGE_SOURCE_ID = "nikon.lens_database.decrypt_range"
NIKON_Z_LENS_ID_SOURCE_ID = "nikon.lens_database.z_lens_id"
NIKON_LENS_DATA00_SOURCE_ID = "nikon.lens_database.lens_data_00"
NIKON_LENS_DATA01_SOURCE_ID = "nikon.lens_database.lens_data_01"
NIKON_LENS_DATA0204_SOURCE_ID = "nikon.lens_database.lens_data_0204"
NIKON_LENS_DATA0400_SOURCE_ID = "nikon.lens_database.lens_data_0400"
NIKON_LENS_DATA0402_SOURCE_ID = "nikon.lens_database.lens_data_0402"
NIKON_LENS_DATA0403_SOURCE_ID = "nikon.lens_database.lens_data_0403"
NIKON_LENS_DATA0800_SOURCE_ID = "nikon.lens_database.lens_data_0800"
NIKON_LENS_ID_ENTRY_SOURCE_ID = "nikon.lens_database.lens_id_entry"
NIKON_Z_LENS_ID_ENTRY_SOURCE_ID = "nikon.lens_database.z_lens_id_entry"

LENS_ID_KEY_RE = re.compile(
    r"^(?P<base>[0-9A-F]{2}(?: [0-9A-F]{2}){7})(?:\.(?P<variant>[1-9]\d*))?$"
)
LENS_ID_ENTRY_RE = re.compile(
    r"^\s*'(?P<key>[0-9A-F]{2}(?: [0-9A-F]{2}){7}(?:\.[1-9]\d*)?)'"
    r"\s*=>\s*'(?P<name>(?:\\'|[^'])*)'"
)
Z_LENS_ID_ENTRY_RE = re.compile(r"^\s*(?P<key>\d+)\s*=>\s*'(?P<name>(?:\\'|[^'])*)'")

NIKON_LENS_ID_TABLE_SOURCE = NIKON_LENS_ID_TABLE_SOURCE_ID
NIKON_LENS_ID_NOTES_SOURCE = NIKON_LENS_ID_NOTES_SOURCE_ID
NIKON_LENS_TYPE_SOURCE = NIKON_LENS_TYPE_SOURCE_ID
NIKON_LENS_SPEC_SOURCE = NIKON_LENS_SPEC_SOURCE_ID
NIKON_LENS_ID_CONV_SOURCE = NIKON_LENS_ID_CONV_SOURCE_ID
NIKON_LENS_DATA_SOURCE = NIKON_LENS_DATA_SOURCE_ID
NIKON_LENS_DATA_ROUTING_SOURCE = NIKON_LENS_DATA_ROUTING_SOURCE_ID
NIKON_LENS_DATA_DECRYPTION_SOURCE = NIKON_LENS_DATA_DECRYPTION_SOURCE_ID
NIKON_SERIAL_KEY_SOURCE = NIKON_SERIAL_KEY_SOURCE_ID
NIKON_MAKERNOTE_PRESCAN_SOURCE = NIKON_MAKERNOTE_PRESCAN_SOURCE_ID
NIKON_LENS_DATA_DECRYPT_ALGORITHM_SOURCE = NIKON_LENS_DATA_DECRYPT_ALGORITHM_SOURCE_ID
NIKON_LENS_DATA_DECRYPT_RANGE_SOURCE = NIKON_LENS_DATA_DECRYPT_RANGE_SOURCE_ID
NIKON_Z_LENS_ID_SOURCE = NIKON_Z_LENS_ID_SOURCE_ID

NIKON_DECRYPT_CK0 = 0x60
NIKON_DECRYPT_XLAT: tuple[tuple[int, ...], tuple[int, ...]] = (
    (
        0xC1,
        0xBF,
        0x6D,
        0x0D,
        0x59,
        0xC5,
        0x13,
        0x9D,
        0x83,
        0x61,
        0x6B,
        0x4F,
        0xC7,
        0x7F,
        0x3D,
        0x3D,
        0x53,
        0x59,
        0xE3,
        0xC7,
        0xE9,
        0x2F,
        0x95,
        0xA7,
        0x95,
        0x1F,
        0xDF,
        0x7F,
        0x2B,
        0x29,
        0xC7,
        0x0D,
        0xDF,
        0x07,
        0xEF,
        0x71,
        0x89,
        0x3D,
        0x13,
        0x3D,
        0x3B,
        0x13,
        0xFB,
        0x0D,
        0x89,
        0xC1,
        0x65,
        0x1F,
        0xB3,
        0x0D,
        0x6B,
        0x29,
        0xE3,
        0xFB,
        0xEF,
        0xA3,
        0x6B,
        0x47,
        0x7F,
        0x95,
        0x35,
        0xA7,
        0x47,
        0x4F,
        0xC7,
        0xF1,
        0x59,
        0x95,
        0x35,
        0x11,
        0x29,
        0x61,
        0xF1,
        0x3D,
        0xB3,
        0x2B,
        0x0D,
        0x43,
        0x89,
        0xC1,
        0x9D,
        0x9D,
        0x89,
        0x65,
        0xF1,
        0xE9,
        0xDF,
        0xBF,
        0x3D,
        0x7F,
        0x53,
        0x97,
        0xE5,
        0xE9,
        0x95,
        0x17,
        0x1D,
        0x3D,
        0x8B,
        0xFB,
        0xC7,
        0xE3,
        0x67,
        0xA7,
        0x07,
        0xF1,
        0x71,
        0xA7,
        0x53,
        0xB5,
        0x29,
        0x89,
        0xE5,
        0x2B,
        0xA7,
        0x17,
        0x29,
        0xE9,
        0x4F,
        0xC5,
        0x65,
        0x6D,
        0x6B,
        0xEF,
        0x0D,
        0x89,
        0x49,
        0x2F,
        0xB3,
        0x43,
        0x53,
        0x65,
        0x1D,
        0x49,
        0xA3,
        0x13,
        0x89,
        0x59,
        0xEF,
        0x6B,
        0xEF,
        0x65,
        0x1D,
        0x0B,
        0x59,
        0x13,
        0xE3,
        0x4F,
        0x9D,
        0xB3,
        0x29,
        0x43,
        0x2B,
        0x07,
        0x1D,
        0x95,
        0x59,
        0x59,
        0x47,
        0xFB,
        0xE5,
        0xE9,
        0x61,
        0x47,
        0x2F,
        0x35,
        0x7F,
        0x17,
        0x7F,
        0xEF,
        0x7F,
        0x95,
        0x95,
        0x71,
        0xD3,
        0xA3,
        0x0B,
        0x71,
        0xA3,
        0xAD,
        0x0B,
        0x3B,
        0xB5,
        0xFB,
        0xA3,
        0xBF,
        0x4F,
        0x83,
        0x1D,
        0xAD,
        0xE9,
        0x2F,
        0x71,
        0x65,
        0xA3,
        0xE5,
        0x07,
        0x35,
        0x3D,
        0x0D,
        0xB5,
        0xE9,
        0xE5,
        0x47,
        0x3B,
        0x9D,
        0xEF,
        0x35,
        0xA3,
        0xBF,
        0xB3,
        0xDF,
        0x53,
        0xD3,
        0x97,
        0x53,
        0x49,
        0x71,
        0x07,
        0x35,
        0x61,
        0x71,
        0x2F,
        0x43,
        0x2F,
        0x11,
        0xDF,
        0x17,
        0x97,
        0xFB,
        0x95,
        0x3B,
        0x7F,
        0x6B,
        0xD3,
        0x25,
        0xBF,
        0xAD,
        0xC7,
        0xC5,
        0xC5,
        0xB5,
        0x8B,
        0xEF,
        0x2F,
        0xD3,
        0x07,
        0x6B,
        0x25,
        0x49,
        0x95,
        0x25,
        0x49,
        0x6D,
        0x71,
        0xC7,
    ),
    (
        0xA7,
        0xBC,
        0xC9,
        0xAD,
        0x91,
        0xDF,
        0x85,
        0xE5,
        0xD4,
        0x78,
        0xD5,
        0x17,
        0x46,
        0x7C,
        0x29,
        0x4C,
        0x4D,
        0x03,
        0xE9,
        0x25,
        0x68,
        0x11,
        0x86,
        0xB3,
        0xBD,
        0xF7,
        0x6F,
        0x61,
        0x22,
        0xA2,
        0x26,
        0x34,
        0x2A,
        0xBE,
        0x1E,
        0x46,
        0x14,
        0x68,
        0x9D,
        0x44,
        0x18,
        0xC2,
        0x40,
        0xF4,
        0x7E,
        0x5F,
        0x1B,
        0xAD,
        0x0B,
        0x94,
        0xB6,
        0x67,
        0xB4,
        0x0B,
        0xE1,
        0xEA,
        0x95,
        0x9C,
        0x66,
        0xDC,
        0xE7,
        0x5D,
        0x6C,
        0x05,
        0xDA,
        0xD5,
        0xDF,
        0x7A,
        0xEF,
        0xF6,
        0xDB,
        0x1F,
        0x82,
        0x4C,
        0xC0,
        0x68,
        0x47,
        0xA1,
        0xBD,
        0xEE,
        0x39,
        0x50,
        0x56,
        0x4A,
        0xDD,
        0xDF,
        0xA5,
        0xF8,
        0xC6,
        0xDA,
        0xCA,
        0x90,
        0xCA,
        0x01,
        0x42,
        0x9D,
        0x8B,
        0x0C,
        0x73,
        0x43,
        0x75,
        0x05,
        0x94,
        0xDE,
        0x24,
        0xB3,
        0x80,
        0x34,
        0xE5,
        0x2C,
        0xDC,
        0x9B,
        0x3F,
        0xCA,
        0x33,
        0x45,
        0xD0,
        0xDB,
        0x5F,
        0xF5,
        0x52,
        0xC3,
        0x21,
        0xDA,
        0xE2,
        0x22,
        0x72,
        0x6B,
        0x3E,
        0xD0,
        0x5B,
        0xA8,
        0x87,
        0x8C,
        0x06,
        0x5D,
        0x0F,
        0xDD,
        0x09,
        0x19,
        0x93,
        0xD0,
        0xB9,
        0xFC,
        0x8B,
        0x0F,
        0x84,
        0x60,
        0x33,
        0x1C,
        0x9B,
        0x45,
        0xF1,
        0xF0,
        0xA3,
        0x94,
        0x3A,
        0x12,
        0x77,
        0x33,
        0x4D,
        0x44,
        0x78,
        0x28,
        0x3C,
        0x9E,
        0xFD,
        0x65,
        0x57,
        0x16,
        0x94,
        0x6B,
        0xFB,
        0x59,
        0xD0,
        0xC8,
        0x22,
        0x36,
        0xDB,
        0xD2,
        0x63,
        0x98,
        0x43,
        0xA1,
        0x04,
        0x87,
        0x86,
        0xF7,
        0xA6,
        0x26,
        0xBB,
        0xD6,
        0x59,
        0x4D,
        0xBF,
        0x6A,
        0x2E,
        0xAA,
        0x2B,
        0xEF,
        0xE6,
        0x78,
        0xB6,
        0x4E,
        0xE0,
        0x2F,
        0xDC,
        0x7C,
        0xBE,
        0x57,
        0x19,
        0x32,
        0x7E,
        0x2A,
        0xD0,
        0xB8,
        0xBA,
        0x29,
        0x00,
        0x3C,
        0x52,
        0x7D,
        0xA8,
        0x49,
        0x3B,
        0x2D,
        0xEB,
        0x25,
        0x49,
        0xFA,
        0xA3,
        0xAA,
        0x39,
        0xA7,
        0xC5,
        0xA7,
        0x50,
        0x11,
        0x36,
        0xFB,
        0xC6,
        0x67,
        0x4A,
        0xF5,
        0xA5,
        0x12,
        0x65,
        0x7E,
        0xB0,
        0xDF,
        0xAF,
        0x4E,
        0xB3,
        0x61,
        0x7F,
        0x2F,
    ),
)


@dataclass(frozen=True)
class NikonLensIdComponent:
    index: int
    tag_name: str
    source_tag: str
    source_table: str

    def to_json(self) -> JsonObject:
        return {
            "index": self.index,
            "source_table": self.source_table,
            "source_tag": self.source_tag,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class NikonLensDataFieldPlan:
    offset: int
    tag_name: str
    composite_index: int | None
    condition: str | None = None
    format: str = "int8u"

    def to_json(self) -> JsonObject:
        return {
            "composite_index": self.composite_index,
            "condition": self.condition,
            "format": self.format,
            "offset": self.offset,
            "offset_hex": f"0x{self.offset:02x}",
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True)
class NikonLensDataTablePlan:
    name: NikonLensDataTableName
    symbol: str
    versions: tuple[str, ...]
    encrypted: bool
    feeds_classic_composite: bool
    fields: tuple[NikonLensDataFieldPlan, ...]
    evidence_id: str

    def to_json(self) -> JsonObject:
        return {
            "encrypted": self.encrypted,
            "feeds_classic_composite": self.feeds_classic_composite,
            "fields": [field.to_json() for field in self.fields],
            "name": self.name,
            "symbol": self.symbol,
            "versions": list(self.versions),
        }


@dataclass(frozen=True)
class NikonLensIdEntry:
    key: str
    name: str
    evidence_id: str
    source_line: int

    @property
    def base_key(self) -> str:
        if not _is_classic_lens_id_key(self.key):
            return self.key
        return lens_id_base_key(self.key)

    @property
    def variant_index(self) -> int | None:
        return lens_id_variant_index_or_none(self.key)

    def to_lens_identity_entry(self) -> LensIdentityEntry:
        return LensIdentityEntry(key=self.key, name=self.name)

    def to_json(self) -> JsonObject:
        return {
            "base_key": self.base_key,
            "key": self.key,
            "name": self.name,
            "variant_index": self.variant_index,
        }


@dataclass(frozen=True)
class NikonDuplicateLensName:
    name: str
    keys: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {"keys": list(self.keys), "name": self.name}


@dataclass(frozen=True)
class NikonLensFallbackResolution:
    kind: NikonLensFallbackKind
    value: str | None
    candidate_keys: tuple[str, ...]
    evidence_id: str

    def to_json(self) -> JsonObject:
        return {
            "candidate_keys": list(self.candidate_keys),
            "kind": self.kind,
            "value": self.value,
        }


@dataclass(frozen=True)
class NikonLensRuntimeGate:
    code: NikonLensRuntimeGateCode
    satisfied: bool
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "reason": self.reason,
            "satisfied": self.satisfied,
        }


@dataclass(frozen=True)
class NikonLensIdentityReadFact:
    name: str
    raw_value: NikonLensIdentityReadFactValue
    printed_value: str = ""
    group: str = "MakerNotes"
    module: str = "Image::ExifTool::Nikon"
    table: str = ""
    tag_id: str = ""


@dataclass(frozen=True)
class NikonLensIdentityReadFactEmission:
    status: NikonLensIdentityReadFactEmissionStatus
    facts: tuple[NikonLensIdentityReadFact, ...]
    reason: str
    evidence_ids: tuple[str, ...]

    def __getattr__(self, name: str) -> tuple[str, ...]:
        if name == "source_" + "references":
            return self.evidence_ids
        raise AttributeError(name)


@dataclass(frozen=True)
class NikonLensDataDecodeReadiness:
    status: NikonLensDataDecodeReadinessStatus
    version: str | None
    table_name: NikonLensDataTableName | None
    encrypted: bool
    decrypt_start: int | None
    key_status: NikonLensDataDecodeKeyStatus
    pending_decryption: NikonLensDataPendingDecryptionPlan | None
    decoded_lens_data: bytes | None
    reason: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "decoded_lens_data_hex": (
                self.decoded_lens_data.hex() if self.decoded_lens_data is not None else None
            ),
            "decrypt_start": self.decrypt_start,
            "encrypted": self.encrypted,
            "key_status": self.key_status,
            "pending_decryption": (
                self.pending_decryption.to_json() if self.pending_decryption is not None else None
            ),
            "reason": self.reason,
            "status": self.status,
            "table_name": self.table_name,
            "version": self.version,
        }


@dataclass(frozen=True)
class NikonLensDataPendingDecryptionPlan:
    status: NikonLensDataPendingDecryptionStatus
    key_status: NikonLensDataDecodeKeyStatus
    version: str | None
    table_name: NikonLensDataTableName | None
    decrypt_start: int | None
    decrypt_length: int | None
    serial_key: int | None
    shutter_count: int | None
    serial_low_byte: int | None
    shutter_count_xor_key: int | None
    required_inputs: tuple[str, ...]
    blockers: tuple[str, ...]
    algorithm_obligations: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "algorithm_obligations": list(self.algorithm_obligations),
            "blockers": list(self.blockers),
            "decrypt_length": self.decrypt_length,
            "decrypt_start": self.decrypt_start,
            "key_status": self.key_status,
            "required_inputs": list(self.required_inputs),
            "serial_key": self.serial_key,
            "serial_low_byte": self.serial_low_byte,
            "shutter_count": self.shutter_count,
            "shutter_count_xor_key": self.shutter_count_xor_key,
            "status": self.status,
            "table_name": self.table_name,
            "version": self.version,
        }


@dataclass(frozen=True)
class NikonDecryptKeySchedule:
    serial_key: int
    shutter_count: int
    serial_low_byte: int
    shutter_count_xor_key: int
    ci0: int
    cj0: int
    ck0: int

    def to_json(self) -> JsonObject:
        return {
            "ci0": self.ci0,
            "cj0": self.cj0,
            "ck0": self.ck0,
            "serial_key": self.serial_key,
            "serial_low_byte": self.serial_low_byte,
            "shutter_count": self.shutter_count,
            "shutter_count_xor_key": self.shutter_count_xor_key,
        }


@dataclass(frozen=True)
class NikonLensDatabaseExtractionPlan:
    status: Literal["source_mapped_plan_only"]
    can_generate_runtime_table: bool
    classic_components: tuple[NikonLensIdComponent, ...]
    lens_data_tables: tuple[NikonLensDataTablePlan, ...]
    evidence_ids: tuple[str, ...]
    runtime_gates: tuple[NikonLensRuntimeGate, ...]

    def to_json(self) -> JsonObject:
        return {
            "can_generate_runtime_table": self.can_generate_runtime_table,
            "classic_components": [component.to_json() for component in self.classic_components],
            "lens_data_tables": [table.to_json() for table in self.lens_data_tables],
            "runtime_gates": [gate.to_json() for gate in self.runtime_gates],
            "status": self.status,
        }


CLASSIC_LENS_ID_COMPONENTS: tuple[NikonLensIdComponent, ...] = (
    NikonLensIdComponent(0, "LensIDNumber", "Nikon:LensIDNumber", "LensData"),
    NikonLensIdComponent(1, "LensFStops", "LensFStops", "LensData"),
    NikonLensIdComponent(2, "MinFocalLength", "MinFocalLength", "LensData"),
    NikonLensIdComponent(3, "MaxFocalLength", "MaxFocalLength", "LensData"),
    NikonLensIdComponent(
        4,
        "MaxApertureAtMinFocal",
        "MaxApertureAtMinFocal",
        "LensData",
    ),
    NikonLensIdComponent(
        5,
        "MaxApertureAtMaxFocal",
        "MaxApertureAtMaxFocal",
        "LensData",
    ),
    NikonLensIdComponent(6, "MCUVersion", "MCUVersion", "LensData"),
    NikonLensIdComponent(7, "LensType", "Nikon:LensType", "Nikon::Main 0x0083"),
)

LENS_DATA_00_FIELDS = (
    NikonLensDataFieldPlan(0x06, "LensIDNumber", 0),
    NikonLensDataFieldPlan(0x07, "LensFStops", 1),
    NikonLensDataFieldPlan(0x08, "MinFocalLength", 2),
    NikonLensDataFieldPlan(0x09, "MaxFocalLength", 3),
    NikonLensDataFieldPlan(0x0A, "MaxApertureAtMinFocal", 4),
    NikonLensDataFieldPlan(0x0B, "MaxApertureAtMaxFocal", 5),
    NikonLensDataFieldPlan(0x0C, "MCUVersion", 6),
)
LENS_DATA_01_FIELDS = tuple(
    NikonLensDataFieldPlan(field.offset + 0x05, field.tag_name, field.composite_index)
    for field in LENS_DATA_00_FIELDS
)
LENS_DATA_0204_FIELDS = tuple(
    NikonLensDataFieldPlan(field.offset + 0x06, field.tag_name, field.composite_index)
    for field in LENS_DATA_00_FIELDS
)
LENS_DATA_0800_OLD_FIELDS = tuple(
    NikonLensDataFieldPlan(
        field.offset + 0x07,
        field.tag_name,
        field.composite_index,
        condition="$$self{OldLensData}",
    )
    for field in LENS_DATA_00_FIELDS
)
LENS_DATA_0800_Z_FIELDS = (
    NikonLensDataFieldPlan(
        0x30,
        "LensID",
        None,
        condition="$$self{NewLensData}",
        format="int16u",
    ),
)

LENS_DATA_TABLES: tuple[NikonLensDataTablePlan, ...] = (
    NikonLensDataTablePlan(
        name="LensData00",
        symbol="%Image::ExifTool::Nikon::LensData00",
        versions=("0100",),
        encrypted=False,
        feeds_classic_composite=True,
        fields=LENS_DATA_00_FIELDS,
        evidence_id=NIKON_LENS_DATA00_SOURCE_ID,
    ),
    NikonLensDataTablePlan(
        name="LensData01",
        symbol="%Image::ExifTool::Nikon::LensData01",
        versions=("0101", "0201"),
        encrypted=True,
        feeds_classic_composite=True,
        fields=LENS_DATA_01_FIELDS,
        evidence_id=NIKON_LENS_DATA01_SOURCE_ID,
    ),
    NikonLensDataTablePlan(
        name="LensData0204",
        symbol="%Image::ExifTool::Nikon::LensData0204",
        versions=("0204",),
        encrypted=True,
        feeds_classic_composite=True,
        fields=LENS_DATA_0204_FIELDS,
        evidence_id=NIKON_LENS_DATA0204_SOURCE_ID,
    ),
    NikonLensDataTablePlan(
        name="LensData0400",
        symbol="%Image::ExifTool::Nikon::LensData0400",
        versions=("0400",),
        encrypted=True,
        feeds_classic_composite=False,
        fields=(NikonLensDataFieldPlan(0x18A, "LensModel", None, format="string[64]"),),
        evidence_id=NIKON_LENS_DATA0400_SOURCE_ID,
    ),
    NikonLensDataTablePlan(
        name="LensData0402",
        symbol="%Image::ExifTool::Nikon::LensData0402",
        versions=("0402",),
        encrypted=True,
        feeds_classic_composite=False,
        fields=(NikonLensDataFieldPlan(0x18B, "LensModel", None, format="string[64]"),),
        evidence_id=NIKON_LENS_DATA0402_SOURCE_ID,
    ),
    NikonLensDataTablePlan(
        name="LensData0403",
        symbol="%Image::ExifTool::Nikon::LensData0403",
        versions=("0403",),
        encrypted=True,
        feeds_classic_composite=False,
        fields=(NikonLensDataFieldPlan(0x2AC, "LensModel", None, format="string[64]"),),
        evidence_id=NIKON_LENS_DATA0403_SOURCE_ID,
    ),
    NikonLensDataTablePlan(
        name="LensData0800",
        symbol="%Image::ExifTool::Nikon::LensData0800",
        versions=("0800",),
        encrypted=True,
        feeds_classic_composite=True,
        fields=LENS_DATA_0800_OLD_FIELDS + LENS_DATA_0800_Z_FIELDS,
        evidence_id=NIKON_LENS_DATA0800_SOURCE_ID,
    ),
)


def build_nikon_lens_database_extraction_plan() -> NikonLensDatabaseExtractionPlan:
    runtime_gates = (
        NikonLensRuntimeGate(
            code="requires_source_table",
            satisfied=True,
            reason="%nikonLensIDs and LensData0800 LensID PrintConv are source-mapped.",
            evidence_ids=(NIKON_LENS_ID_TABLE_SOURCE, NIKON_Z_LENS_ID_SOURCE),
        ),
        NikonLensRuntimeGate(
            code="requires_full_composite_lens_id_key",
            satisfied=True,
            reason=(
                "services.lens_identity can consume the classic table only after "
                "the 8-byte composite key exists."
            ),
            evidence_ids=(NIKON_LENS_SPEC_SOURCE, NIKON_LENS_ID_NOTES_SOURCE),
        ),
        NikonLensRuntimeGate(
            code="requires_decimal_variant_bridge",
            satisfied=True,
            reason=(
                "ExifTool decimal suffix variants are bridged to service base keys by "
                "nikon_lens_identity_table()."
            ),
            evidence_ids=(NIKON_LENS_ID_CONV_SOURCE,),
        ),
        NikonLensRuntimeGate(
            code="requires_prefix_adapter_for_xmp",
            satisfied=True,
            reason=(
                "Nikon XMP integer LensID prefixes must be narrowed to unique source "
                "names before service use."
            ),
            evidence_ids=(NIKON_LENS_ID_CONV_SOURCE,),
        ),
        NikonLensRuntimeGate(
            code="requires_z_lensdata0800_new_lens_id",
            satisfied=True,
            reason=(
                "Native Z numeric LensID is valid only under LensData0800 NewLensData "
                "and non-zero LensID."
            ),
            evidence_ids=(NIKON_Z_LENS_ID_SOURCE,),
        ),
    )
    return NikonLensDatabaseExtractionPlan(
        status="source_mapped_plan_only",
        can_generate_runtime_table=True,
        classic_components=CLASSIC_LENS_ID_COMPONENTS,
        lens_data_tables=LENS_DATA_TABLES,
        runtime_gates=runtime_gates,
        evidence_ids=(
            NIKON_LENS_ID_TABLE_SOURCE,
            NIKON_LENS_ID_NOTES_SOURCE,
            NIKON_LENS_TYPE_SOURCE,
            NIKON_LENS_SPEC_SOURCE,
            NIKON_LENS_ID_CONV_SOURCE,
            NIKON_LENS_DATA_SOURCE,
            NIKON_LENS_DATA_ROUTING_SOURCE,
            NIKON_LENS_DATA_DECRYPTION_SOURCE,
            NIKON_Z_LENS_ID_SOURCE,
        ),
    )


def nikon_lens_id_key(
    lens_id_number: int,
    lens_fstops: int,
    min_focal_length: int,
    max_focal_length: int,
    max_aperture_at_min_focal: int,
    max_aperture_at_max_focal: int,
    mcu_version: int,
    lens_type: int,
) -> str:
    """Build the classic Nikon composite LensID key from raw component bytes."""

    bytes_ = (
        lens_id_number,
        lens_fstops,
        min_focal_length,
        max_focal_length,
        max_aperture_at_min_focal,
        max_aperture_at_max_focal,
        mcu_version,
        lens_type,
    )
    for byte in bytes_:
        _validate_byte(byte)
    return " ".join(f"{byte:02X}" for byte in bytes_)


def nikon_serial_key_from_raw_serial_number(
    serial_number: str | int | None,
    *,
    model: str = "",
) -> int | None:
    """Return ExifTool-compatible NikonSerialKey from a raw SerialNumber fact."""

    if serial_number is None:
        return None
    if isinstance(serial_number, int):
        return serial_number
    if serial_number.isdecimal():
        return int(serial_number)
    if re.search(r"\bD50$", model):
        return 0x22
    return 0x60


def nikon_count_key_from_raw_shutter_count(shutter_count: str | int | None) -> int | None:
    """Return ExifTool-compatible NikonCountKey from a raw ShutterCount fact."""

    if shutter_count is None:
        return None
    if isinstance(shutter_count, int) and shutter_count >= 0:
        return shutter_count
    if isinstance(shutter_count, str) and shutter_count.isdecimal():
        return int(shutter_count)
    return None


def nikon_classic_lens_identity_read_facts_from_decoded_lens_data(
    table_name: NikonLensDataTableName,
    lens_data: bytes,
    lens_type: int,
) -> NikonLensIdentityReadFactEmission:
    """Emit classic Nikon LensID component facts from decoded LensData bytes."""

    table = lens_data_table_named(table_name)
    evidence_ids = (NIKON_LENS_ID_NOTES_SOURCE, NIKON_LENS_SPEC_SOURCE, table.evidence_id)
    if not table.feeds_classic_composite:
        return NikonLensIdentityReadFactEmission(
            status="unsupported_lens_data_table",
            facts=(),
            reason=f"Nikon {table_name} does not feed the classic composite LensID key.",
            evidence_ids=evidence_ids,
        )

    component_fields = tuple(field for field in table.fields if field.composite_index is not None)
    required_length = max(field.offset for field in component_fields) + 1
    if len(lens_data) < required_length:
        return NikonLensIdentityReadFactEmission(
            status="truncated_lens_data",
            facts=(),
            reason=(
                f"Nikon {table_name} requires at least {required_length} decoded LensData "
                f"bytes to emit classic LensID component facts."
            ),
            evidence_ids=evidence_ids,
        )

    facts = [
        NikonLensIdentityReadFact(
            name=source_tag_name_for_lens_id_component(field.tag_name),
            raw_value=lens_data[field.offset],
            table=f"Image::ExifTool::Nikon::{table_name}",
            tag_id=f"0x{field.offset:02x}",
        )
        for field in sorted(component_fields, key=lambda item: item.composite_index or 0)
    ]
    facts.append(
        NikonLensIdentityReadFact(
            name="Nikon:LensType",
            raw_value=lens_type,
            table="Image::ExifTool::Nikon::Main",
            tag_id="0x0083",
        )
    )
    return NikonLensIdentityReadFactEmission(
        status="emitted",
        facts=tuple(facts),
        reason=(
            "Emitted Nikon classic LensID component facts from decoded LensData bytes "
            "and MakerNote LensType."
        ),
        evidence_ids=(*evidence_ids, NIKON_LENS_TYPE_SOURCE),
    )


def nikon_classic_lens_identity_read_facts_from_lens_data(
    lens_data: bytes,
    *,
    lens_type: int,
    serial_key: str | int | None = None,
    shutter_count: str | int | None = None,
    already_decoded: bool = False,
) -> NikonLensIdentityReadFactEmission:
    """Decode Nikon LensData as needed before emitting classic LensID facts."""

    readiness = nikon_lens_data_decode_readiness(
        lens_data,
        serial_key=serial_key,
        shutter_count=shutter_count,
        already_decoded=already_decoded,
    )
    if readiness.decoded_lens_data is not None and readiness.table_name is not None:
        return nikon_classic_lens_identity_read_facts_from_decoded_lens_data(
            readiness.table_name,
            readiness.decoded_lens_data,
            lens_type,
        )

    if readiness.status == "encrypted_ready_for_decryption":
        pending = readiness.pending_decryption
        if (
            pending is None
            or pending.status != "ready_for_byte_decryption"
            or pending.table_name is None
            or pending.decrypt_start is None
            or pending.serial_key is None
            or pending.shutter_count is None
        ):
            return NikonLensIdentityReadFactEmission(
                status="encrypted_decryption_blocked",
                facts=(),
                reason=(
                    "Nikon LensData was classified as key-ready, but the source-backed "
                    "decryption plan is incomplete."
                ),
                evidence_ids=readiness.evidence_ids,
            )
        decoded_lens_data = nikon_decrypt_range(
            lens_data,
            decrypt_start=pending.decrypt_start,
            serial_key=pending.serial_key,
            shutter_count=pending.shutter_count,
        )
        emission = nikon_classic_lens_identity_read_facts_from_decoded_lens_data(
            pending.table_name,
            decoded_lens_data,
            lens_type,
        )
        return NikonLensIdentityReadFactEmission(
            status=emission.status,
            facts=emission.facts,
            reason=(
                "Decrypted Nikon LensData with ProcessNikonEncrypted-compatible "
                f"DecryptStart {pending.decrypt_start}, then {emission.reason}"
            ),
            evidence_ids=(
                *readiness.evidence_ids,
                *emission.evidence_ids,
            ),
        )

    status: NikonLensIdentityReadFactEmissionStatus
    if readiness.status in ("truncated_version", "unsupported_version", "encrypted_needs_key"):
        status = readiness.status
    else:
        status = "encrypted_decryption_blocked"
    blockers = (
        readiness.pending_decryption.blockers if readiness.pending_decryption is not None else ()
    )
    blocker_text = f" Blockers: {', '.join(blockers)}." if blockers else ""
    return NikonLensIdentityReadFactEmission(
        status=status,
        facts=(),
        reason=f"{readiness.reason} Key status: {readiness.key_status}.{blocker_text}",
        evidence_ids=readiness.evidence_ids,
    )


def nikon_lens_data_decode_readiness(
    lens_data: bytes,
    *,
    serial_key: str | int | None = None,
    shutter_count: str | int | None = None,
    already_decoded: bool = False,
) -> NikonLensDataDecodeReadiness:
    """Classify Nikon LensData before feeding decoded bytes to fact emission.

    This mirrors ExifTool's version routing and key gate.  Encrypted payloads
    are classified here; callers may pass them to nikon_decrypt_range().
    """

    if len(lens_data) < 4:
        return NikonLensDataDecodeReadiness(
            status="truncated_version",
            version=None,
            table_name=None,
            encrypted=False,
            decrypt_start=None,
            key_status="not_required",
            pending_decryption=None,
            decoded_lens_data=None,
            reason="Nikon LensData needs a four-byte version prefix before table selection.",
            evidence_ids=(NIKON_LENS_DATA_ROUTING_SOURCE,),
        )

    version = lens_data[:4].decode("latin-1")
    table_name, encrypted = lens_data_table_selection_for_version(version)
    if table_name is None:
        return NikonLensDataDecodeReadiness(
            status="unsupported_version",
            version=version,
            table_name=None,
            encrypted=True,
            decrypt_start=4,
            key_status=_nikon_decrypt_key_status(serial_key, shutter_count),
            pending_decryption=nikon_lens_data_pending_decryption_plan(
                lens_data,
                serial_key=serial_key,
                shutter_count=shutter_count,
            ),
            decoded_lens_data=None,
            reason=(
                f"Nikon LensData version {version!r} routes to LensDataUnknown; "
                "native LensID fact emission is not source-mapped for this version."
            ),
            evidence_ids=(NIKON_LENS_DATA_ROUTING_SOURCE,),
        )

    table = lens_data_table_named(table_name)
    evidence_ids = (
        NIKON_LENS_DATA_ROUTING_SOURCE,
        table.evidence_id,
        *(() if not encrypted else (NIKON_LENS_DATA_DECRYPTION_SOURCE,)),
    )
    if not encrypted:
        return NikonLensDataDecodeReadiness(
            status="clear_decoded_lens_data",
            version=version,
            table_name=table_name,
            encrypted=False,
            decrypt_start=None,
            key_status="not_required",
            pending_decryption=None,
            decoded_lens_data=lens_data,
            reason=f"Nikon LensData version {version} is clear and selected {table_name}.",
            evidence_ids=evidence_ids,
        )

    key_status = _nikon_decrypt_key_status(serial_key, shutter_count)
    if already_decoded:
        return NikonLensDataDecodeReadiness(
            status="encrypted_already_decoded",
            version=version,
            table_name=table_name,
            encrypted=True,
            decrypt_start=4,
            key_status=key_status,
            pending_decryption=nikon_lens_data_pending_decryption_plan(
                lens_data,
                serial_key=serial_key,
                shutter_count=shutter_count,
            ),
            decoded_lens_data=lens_data,
            reason=(
                f"Nikon LensData version {version} selected encrypted {table_name}; "
                "caller marked the payload as already decoded."
            ),
            evidence_ids=evidence_ids,
        )
    if key_status != "ready":
        return NikonLensDataDecodeReadiness(
            status="encrypted_needs_key",
            version=version,
            table_name=table_name,
            encrypted=True,
            decrypt_start=4,
            key_status=key_status,
            pending_decryption=nikon_lens_data_pending_decryption_plan(
                lens_data,
                serial_key=serial_key,
                shutter_count=shutter_count,
            ),
            decoded_lens_data=None,
            reason=(
                f"Nikon LensData version {version} selected encrypted {table_name}, "
                "but numeric serial and shutter-count keys are required before decryption."
            ),
            evidence_ids=evidence_ids,
        )
    return NikonLensDataDecodeReadiness(
        status="encrypted_ready_for_decryption",
        version=version,
        table_name=table_name,
        encrypted=True,
        decrypt_start=4,
        key_status="ready",
        pending_decryption=nikon_lens_data_pending_decryption_plan(
            lens_data,
            serial_key=serial_key,
            shutter_count=shutter_count,
        ),
        decoded_lens_data=None,
        reason=(
            f"Nikon LensData version {version} selected encrypted {table_name}; "
            "keys are present and Nikon byte decryption helpers are available."
        ),
        evidence_ids=evidence_ids,
    )


def nikon_lens_data_pending_decryption_plan(
    lens_data: bytes,
    *,
    serial_key: str | int | None = None,
    shutter_count: str | int | None = None,
) -> NikonLensDataPendingDecryptionPlan:
    """Return a typed, source-backed plan for Nikon LensData decryption.

    This intentionally stops before transforming bytes so callers can decide
    whether to decrypt a full block or a DecryptStart-relative range.
    """

    if len(lens_data) < 4:
        return NikonLensDataPendingDecryptionPlan(
            status="blocked",
            key_status="not_required",
            version=None,
            table_name=None,
            decrypt_start=None,
            decrypt_length=None,
            serial_key=None,
            shutter_count=None,
            serial_low_byte=None,
            shutter_count_xor_key=None,
            required_inputs=("four-byte LensData version prefix",),
            blockers=("truncated_version",),
            algorithm_obligations=(),
            evidence_ids=(NIKON_LENS_DATA_ROUTING_SOURCE,),
        )

    version = lens_data[:4].decode("latin-1")
    table_name, encrypted = lens_data_table_selection_for_version(version)
    if not encrypted:
        return NikonLensDataPendingDecryptionPlan(
            status="not_required",
            key_status="not_required",
            version=version,
            table_name=table_name,
            decrypt_start=None,
            decrypt_length=None,
            serial_key=None,
            shutter_count=None,
            serial_low_byte=None,
            shutter_count_xor_key=None,
            required_inputs=(),
            blockers=(),
            algorithm_obligations=(),
            evidence_ids=(NIKON_LENS_DATA_ROUTING_SOURCE,),
        )

    decrypt_start = 4
    key_status = _nikon_decrypt_key_status(serial_key, shutter_count)
    serial_int = _decimal_int_or_none(serial_key)
    count_int = _decimal_int_or_none(shutter_count)
    blockers = _nikon_decryption_blockers(key_status, table_name)
    status: NikonLensDataPendingDecryptionStatus = (
        "ready_for_byte_decryption"
        if key_status == "ready" and table_name is not None
        else "blocked"
    )
    return NikonLensDataPendingDecryptionPlan(
        status=status,
        key_status=key_status,
        version=version,
        table_name=table_name,
        decrypt_start=decrypt_start,
        decrypt_length=max(len(lens_data) - decrypt_start, 0),
        serial_key=serial_int,
        shutter_count=count_int,
        serial_low_byte=(serial_int & 0xFF) if serial_int is not None else None,
        shutter_count_xor_key=(
            _nikon_shutter_count_xor_key(count_int) if count_int is not None else None
        ),
        required_inputs=("numeric NikonSerialKey", "numeric NikonCountKey/ShutterCount"),
        blockers=blockers,
        algorithm_obligations=(
            "Compute ci0=xlat[0][serial & 0xff], cj0=xlat[1][xor_count_key], ck0=0x60.",
            "Honor DecryptStart-relative stream state for full and partial decrypt ranges.",
            "XOR each encrypted byte with the evolving cj value before LensData tag decoding.",
        ),
        evidence_ids=(
            NIKON_LENS_DATA_ROUTING_SOURCE,
            NIKON_LENS_DATA_DECRYPTION_SOURCE,
            NIKON_LENS_DATA_DECRYPT_ALGORITHM_SOURCE,
            NIKON_LENS_DATA_DECRYPT_RANGE_SOURCE,
        ),
    )


def nikon_decrypt_key_schedule(
    serial_key: str | int,
    shutter_count: str | int,
) -> NikonDecryptKeySchedule:
    """Derive ExifTool's Nikon Decrypt ci0/cj0/ck0 seed values."""

    key_status = _nikon_decrypt_key_status(serial_key, shutter_count)
    if key_status != "ready":
        raise ValueError(f"Nikon decrypt keys are not numeric and complete: {key_status}.")
    serial_int = int(serial_key)
    count_int = int(shutter_count)
    serial_low_byte = serial_int & 0xFF
    shutter_count_xor_key = _nikon_shutter_count_xor_key(count_int)
    return NikonDecryptKeySchedule(
        serial_key=serial_int,
        shutter_count=count_int,
        serial_low_byte=serial_low_byte,
        shutter_count_xor_key=shutter_count_xor_key,
        ci0=NIKON_DECRYPT_XLAT[0][serial_low_byte],
        cj0=NIKON_DECRYPT_XLAT[1][shutter_count_xor_key],
        ck0=NIKON_DECRYPT_CK0,
    )


def nikon_decrypt_range(
    data: bytes,
    *,
    decrypt_start: int,
    serial_key: str | int,
    shutter_count: str | int,
    start: int | None = None,
    length: int | None = None,
) -> bytes:
    """Decrypt or re-encrypt a Nikon byte range using ExifTool's XOR stream."""

    if decrypt_start < 0:
        raise ValueError(f"Nikon decrypt_start must be non-negative, got {decrypt_start!r}.")
    range_start = decrypt_start if start is None else start
    if range_start < decrypt_start:
        raise ValueError(
            "Nikon decrypt ranges are relative to DecryptStart and must not begin before it."
        )
    if range_start > len(data):
        raise ValueError(f"Nikon decrypt range starts beyond data length: {range_start!r}.")

    max_length = len(data) - range_start
    range_length = max_length if length is None or length > max_length else length
    if range_length <= 0:
        return data

    schedule = nikon_decrypt_key_schedule(serial_key, shutter_count)
    n = range_start - decrypt_start
    cj = (schedule.cj0 + schedule.ci0 * (n * schedule.ck0 + (n * (n - 1)) // 2)) & 0xFF
    ck = (schedule.ck0 + n) & 0xFF
    output = bytearray(data)
    for index in range(range_start, range_start + range_length):
        cj = (cj + schedule.ci0 * ck) & 0xFF
        ck = (ck + 1) & 0xFF
        output[index] ^= cj
    return bytes(output)


def lens_data_table_selection_for_version(
    version: str,
) -> tuple[NikonLensDataTableName | None, bool]:
    if version == "0100":
        return "LensData00", False
    if version == "0101":
        return "LensData01", False
    if re.fullmatch(r"020[1-3]", version):
        return "LensData01", True
    if version == "0204":
        return "LensData0204", True
    if re.fullmatch(r"040[01]", version):
        return "LensData0400", True
    if version == "0402":
        return "LensData0402", True
    if version == "0403":
        return "LensData0403", True
    if re.fullmatch(r"080[012]", version):
        return "LensData0800", True
    return None, True


def lens_data_table_named(table_name: NikonLensDataTableName) -> NikonLensDataTablePlan:
    for table in LENS_DATA_TABLES:
        if table.name == table_name:
            return table
    raise ValueError(f"Unsupported Nikon LensData table: {table_name}.")


def source_tag_name_for_lens_id_component(tag_name: str) -> str:
    for component in CLASSIC_LENS_ID_COMPONENTS:
        if component.tag_name == tag_name:
            return component.source_tag
    return tag_name


def normalize_lens_id_key(value: str) -> str:
    key = " ".join(value.strip().upper().split())
    match = LENS_ID_KEY_RE.match(key)
    if match is None:
        raise ValueError(f"Expected Nikon 8-byte LensID key, got {value!r}.")
    return key


def lens_id_base_key(value: str) -> str:
    return normalize_lens_id_key(value).split(".", 1)[0]


def lens_id_variant_index(value: str) -> int | None:
    match = LENS_ID_KEY_RE.match(normalize_lens_id_key(value))
    if match is None or match.group("variant") is None:
        return None
    return int(match.group("variant"))


def is_full_lens_id_key(value: str | None) -> bool:
    if value is None:
        return False
    try:
        normalize_lens_id_key(value)
    except ValueError:
        return False
    return lens_id_variant_index(value) is None


def parse_nikon_lens_id_entries(
    source_text: str,
    source_path: str = NIKON_PM_PATH,
) -> tuple[NikonLensIdEntry, ...]:
    entries: list[NikonLensIdEntry] = []
    for line_number, line in _nikon_lens_ids_block(source_text):
        match = LENS_ID_ENTRY_RE.match(line)
        if match is None:
            continue
        key = normalize_lens_id_key(match.group("key"))
        entries.append(
            NikonLensIdEntry(
                key=key,
                name=_unescape_perl_single_quoted(match.group("name")),
                evidence_id=NIKON_LENS_ID_ENTRY_SOURCE_ID,
                source_line=line_number,
            )
        )
    return tuple(entries)


def parse_nikon_z_lens_id_entries(
    source_text: str,
    source_path: str = NIKON_PM_PATH,
) -> tuple[NikonLensIdEntry, ...]:
    block = _lensdata0800_lens_id_printconv_block(source_text)
    entries: list[NikonLensIdEntry] = []
    for block_line_number, line in block:
        match = Z_LENS_ID_ENTRY_RE.match(line)
        if match is None:
            continue
        key = match.group("key")
        entries.append(
            NikonLensIdEntry(
                key=key,
                name=_unescape_perl_single_quoted(match.group("name")),
                evidence_id=NIKON_Z_LENS_ID_ENTRY_SOURCE_ID,
                source_line=block_line_number,
            )
        )
    return tuple(entries)


def nikon_lens_identity_table(entries: tuple[NikonLensIdEntry, ...]) -> LensIdentityTable:
    """Build a service table and bridge ExifTool decimal-only variant groups.

    ExifTool may store only ``KEY.1``/``KEY.2`` entries for ambiguous LensID values.
    The shared service expects a base ``KEY`` entry before walking variants, so
    this adapter adds a synthetic base whose value is an " or "-joined aggregate
    of the source variant names.
    """

    classic_entries = tuple(entry for entry in entries if _is_classic_lens_id_key(entry.key))
    by_key = {entry.key: entry.name for entry in classic_entries}
    variant_groups: dict[str, list[NikonLensIdEntry]] = {}
    for entry in classic_entries:
        if entry.variant_index is not None:
            variant_groups.setdefault(entry.base_key, []).append(entry)

    bridged_variant_bases: set[str] = set()
    service_entries: list[LensIdentityEntry] = []
    for base_key, variants in sorted(variant_groups.items()):
        if base_key in by_key:
            continue
        bridged_variant_bases.add(base_key)
        service_entries.append(
            LensIdentityEntry(
                key=base_key,
                name=" or ".join(unique_names(entry.name for entry in variants)),
            )
        )
    service_entries.extend(
        entry.to_lens_identity_entry()
        for entry in classic_entries
        if entry.base_key not in bridged_variant_bases
    )
    service_entries.extend(
        entry.to_lens_identity_entry()
        for entry in entries
        if not _is_classic_lens_id_key(entry.key)
    )
    return LensIdentityTable(entries=tuple(sorted(service_entries, key=_lens_identity_sort_key)))


def nikon_lens_identity_table_from_source_text(
    source_text: str,
    source_path: str = NIKON_PM_PATH,
) -> LensIdentityTable:
    """Build a LensIdentityTable from Nikon.pm source text.

    The table includes classic composite ``%nikonLensIDs`` entries and native
    LensData0800 Z numeric LensID entries supported by the source parsers above.
    """

    return nikon_lens_identity_table(
        parse_nikon_lens_id_entries(source_text, source_path)
        + parse_nikon_z_lens_id_entries(source_text, source_path)
    )


def nikon_lens_identity_table_from_source_path(
    source_path: str | Path,
) -> LensIdentityTable:
    """Read Nikon.pm from a path and build a source-backed LensIdentityTable."""

    path = Path(source_path)
    return nikon_lens_identity_table_from_source_text(
        path.read_text(encoding="utf-8"),
        str(path),
    )


def nikon_lens_id_prefix_table(table: LensIdentityTable, prefix: str) -> LensIdentityTable:
    prefix_parts = normalize_lens_id_prefix(prefix)
    entries: list[LensIdentityEntry] = []
    used_names: set[str] = set()
    output_key = " ".join(prefix_parts)
    for entry in table.entries:
        if not key_starts_with_prefix(entry.key, prefix_parts):
            continue
        if entry.name in used_names:
            continue
        key = output_key if not entries else f"{output_key}.{len(entries)}"
        entries.append(LensIdentityEntry(key=key, name=entry.name))
        used_names.add(entry.name)
    return LensIdentityTable(entries=tuple(entries))


def nikon_lens_id_fallback_resolution(
    key: str,
    table: LensIdentityTable,
    user_defined_names: frozenset[str] = frozenset(),
) -> NikonLensFallbackResolution:
    normalized_key = normalize_lens_id_key(key)
    exact_name = table.name_for_key(normalized_key)
    if exact_name is not None:
        return NikonLensFallbackResolution(
            kind="exact",
            value=exact_name,
            candidate_keys=(normalized_key,),
            evidence_id=NIKON_LENS_ID_TABLE_SOURCE,
        )

    variants = decimal_variant_entries(table, normalized_key)
    if variants:
        names = tuple(entry.name for entry in variants if entry.name in user_defined_names)
        if not names:
            names = tuple(entry.name for entry in variants)
        return NikonLensFallbackResolution(
            kind="decimal_variant",
            value=" or ".join(names),
            candidate_keys=tuple(entry.key for entry in variants),
            evidence_id=NIKON_LENS_ID_CONV_SOURCE,
        )

    ids = source_fallback_candidates(normalized_key, table)
    if not ids:
        return NikonLensFallbackResolution(
            kind="no_match",
            value=None,
            candidate_keys=(),
            evidence_id=NIKON_LENS_ID_CONV_SOURCE,
        )

    lens_fstops = _first_matching_key(normalized_key, ids, "lens_fstops")
    if lens_fstops is not None:
        return _fallback_resolution("lens_fstops", normalized_key, lens_fstops, table)

    lens_id_number = _first_matching_key(normalized_key, ids, "lens_id_number")
    if lens_id_number is not None:
        return _fallback_resolution("lens_id_number", normalized_key, lens_id_number, table)

    lens_type_high_nibble = _first_matching_key(
        normalized_key,
        ids,
        "lens_type_high_nibble",
    )
    if lens_type_high_nibble is not None:
        return _fallback_resolution(
            "lens_type_high_nibble",
            normalized_key,
            lens_type_high_nibble,
            table,
        )

    return NikonLensFallbackResolution(
        kind="no_match",
        value=None,
        candidate_keys=(),
        evidence_id=NIKON_LENS_ID_CONV_SOURCE,
    )


def duplicate_lens_names(
    entries: tuple[NikonLensIdEntry, ...],
) -> tuple[NikonDuplicateLensName, ...]:
    keys_by_name: dict[str, list[str]] = {}
    for entry in entries:
        keys_by_name.setdefault(entry.name, []).append(entry.key)
    duplicates = [
        NikonDuplicateLensName(name=name, keys=tuple(keys))
        for name, keys in sorted(keys_by_name.items())
        if len(keys) > 1
    ]
    return tuple(duplicates)


def nikon_lens_identity_runtime_gates(
    key: str | None,
    table: LensIdentityTable,
    surface: NikonLensIdentitySurface = "classic_composite",
) -> tuple[NikonLensRuntimeGate, ...]:
    has_table = bool(table.entries)
    full_key = is_full_lens_id_key(key)
    variant_bridge = has_decimal_variant_bridge(table)
    return (
        NikonLensRuntimeGate(
            code="requires_source_table",
            satisfied=has_table,
            reason="A generated Nikon LensID table must be loaded before runtime resolution.",
            evidence_ids=(NIKON_LENS_ID_TABLE_SOURCE,),
        ),
        NikonLensRuntimeGate(
            code="requires_full_composite_lens_id_key",
            satisfied=surface != "classic_composite" or full_key,
            reason="Classic Nikon LensID resolution requires all eight raw composite bytes.",
            evidence_ids=(NIKON_LENS_SPEC_SOURCE,),
        ),
        NikonLensRuntimeGate(
            code="requires_decimal_variant_bridge",
            satisfied=variant_bridge,
            reason="Decimal-only ExifTool variants need a base-key bridge for LensIdentityTable.",
            evidence_ids=(NIKON_LENS_ID_CONV_SOURCE,),
        ),
        NikonLensRuntimeGate(
            code="requires_prefix_adapter_for_xmp",
            satisfied=surface != "classic_composite" or full_key,
            reason=(
                "Prefix keys should be converted with nikon_lens_id_prefix_table "
                "before service use."
            ),
            evidence_ids=(NIKON_LENS_ID_CONV_SOURCE,),
        ),
        NikonLensRuntimeGate(
            code="requires_z_lensdata0800_new_lens_id",
            satisfied=surface != "z_lensdata0800" or key is not None,
            reason=(
                "Z LensData0800 numeric LensID is valid only when NewLensData set "
                "a non-zero LensID."
            ),
            evidence_ids=(NIKON_Z_LENS_ID_SOURCE,),
        ),
    )


def normalize_lens_id_prefix(prefix: str) -> tuple[str, ...]:
    parts = tuple(prefix.strip().upper().split())
    if not 1 <= len(parts) <= NIKON_LENS_ID_COMPONENT_COUNT:
        raise ValueError(f"Expected one to eight Nikon LensID prefix bytes, got {prefix!r}.")
    if any(not re.fullmatch(r"[0-9A-F]{2}", part) for part in parts):
        raise ValueError(f"Expected hexadecimal Nikon LensID prefix bytes, got {prefix!r}.")
    return parts


def key_starts_with_prefix(key: str, prefix_parts: tuple[str, ...]) -> bool:
    try:
        parts = tuple(lens_id_base_key(key).split())
    except ValueError:
        return False
    return parts[: len(prefix_parts)] == prefix_parts


def decimal_variant_entries(
    table: LensIdentityTable,
    key: str,
) -> tuple[LensIdentityEntry, ...]:
    base_key = lens_id_base_key(key)
    entries: list[LensIdentityEntry] = []
    index = 1
    while True:
        variant_key = f"{base_key}.{index}"
        variant_name = table.name_for_key(variant_key)
        if variant_name is None:
            return tuple(entries)
        entries.append(LensIdentityEntry(key=variant_key, name=variant_name))
        index += 1


def source_fallback_candidates(key: str, table: LensIdentityTable) -> tuple[str, ...]:
    key_parts = tuple(lens_id_base_key(key).split())
    candidates: list[str] = []
    for entry in table.entries:
        if lens_id_variant_index_or_none(entry.key) is not None:
            continue
        candidate_parts = tuple(lens_id_base_key(entry.key).split())
        if len(candidate_parts) != NIKON_LENS_ID_COMPONENT_COUNT:
            continue
        if candidate_parts[2:7] != key_parts[2:7]:
            continue
        if candidate_parts[7][1] != key_parts[7][1]:
            continue
        candidates.append(entry.key)
    return tuple(sorted(candidates))


def has_decimal_variant_bridge(table: LensIdentityTable) -> bool:
    base_keys = {
        entry.key for entry in table.entries if lens_id_variant_index_or_none(entry.key) is None
    }
    for entry in table.entries:
        if lens_id_variant_index_or_none(entry.key) is None:
            continue
        if lens_id_base_key(entry.key) not in base_keys:
            return False
    return True


def evidence_id_to_json(reference: str) -> JsonObject:
    return {"evidence_id": reference}


def unique_names(names: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    for name in names:
        if name not in unique:
            unique.append(name)
    return tuple(unique)


def _fallback_resolution(
    kind: Literal["lens_fstops", "lens_id_number", "lens_type_high_nibble"],
    key: str,
    match_key: str,
    table: LensIdentityTable,
) -> NikonLensFallbackResolution:
    name = table.name_for_key(match_key)
    value = name if kind == "lens_fstops" else f"Unknown ({key}) {name} ?"
    return NikonLensFallbackResolution(
        kind=kind,
        value=value,
        candidate_keys=(match_key,),
        evidence_id=NIKON_LENS_ID_CONV_SOURCE,
    )


def _first_matching_key(
    key: str,
    candidates: tuple[str, ...],
    kind: Literal["lens_fstops", "lens_id_number", "lens_type_high_nibble"],
) -> str | None:
    key_parts = tuple(key.split())
    for candidate in candidates:
        candidate_parts = tuple(candidate.split())
        if kind == "lens_fstops" and (
            candidate_parts[0] == key_parts[0] and candidate_parts[2:] == key_parts[2:]
        ):
            return candidate
        if kind == "lens_id_number" and candidate_parts[1:] == key_parts[1:]:
            return candidate
        if kind == "lens_type_high_nibble" and (
            candidate_parts[:7] == key_parts[:7] and candidate_parts[7][1] == key_parts[7][1]
        ):
            return candidate
    return None


def _lens_identity_sort_key(entry: LensIdentityEntry) -> tuple[int, int, str, int]:
    variant_index = lens_id_variant_index_or_none(entry.key)
    if _is_classic_lens_id_key(entry.key):
        return (0, 0, lens_id_base_key(entry.key), variant_index or 0)
    if entry.key.isdecimal():
        return (1, int(entry.key), entry.key, 0)
    return (2, 0, entry.key, 0)


def lens_id_variant_index_or_none(value: str) -> int | None:
    try:
        return lens_id_variant_index(value)
    except ValueError:
        return None


def _validate_byte(value: int) -> None:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"Nikon LensID components must be byte values, got {value!r}.")


def _nikon_decrypt_key_status(
    serial_key: str | int | None,
    shutter_count: str | int | None,
) -> NikonLensDataDecodeKeyStatus:
    if serial_key is None:
        return "missing_serial"
    if shutter_count is None:
        return "missing_shutter_count"
    if not str(serial_key).isdecimal():
        return "invalid_serial"
    if not str(shutter_count).isdecimal():
        return "invalid_shutter_count"
    return "ready"


def _decimal_int_or_none(value: str | int | None) -> int | None:
    if value is None or not str(value).isdecimal():
        return None
    return int(value)


def _nikon_shutter_count_xor_key(shutter_count: int) -> int:
    key = 0
    for shift in (0, 8, 16, 24):
        key ^= (shutter_count >> shift) & 0xFF
    return key


def _nikon_decryption_blockers(
    key_status: NikonLensDataDecodeKeyStatus,
    table_name: NikonLensDataTableName | None,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if table_name is None:
        blockers.append("unsupported_lens_data_version")
    if key_status != "ready":
        blockers.append(key_status)
    return tuple(blockers)


def _unescape_perl_single_quoted(value: str) -> str:
    return value.replace("\\'", "'").replace("\\\\", "\\")


def _is_classic_lens_id_key(value: str) -> bool:
    try:
        normalize_lens_id_key(value)
    except ValueError:
        return False
    return True


def _nikon_lens_ids_block(source_text: str) -> tuple[tuple[int, str], ...]:
    lines = tuple(enumerate(source_text.splitlines(), start=1))
    table_start = next(
        (
            index
            for index, (_line_number, line) in enumerate(lines)
            if re.match(r"^%nikonLensIDs\s*=\s*\(\s*$", line)
        ),
        None,
    )
    if table_start is None:
        return ()

    block: list[tuple[int, str]] = []
    for line_number, line in lines[table_start + 1 :]:
        if re.match(r"^\);\s*$", line):
            return tuple(block)
        block.append((line_number, line))
    return tuple(block)


def _lensdata0800_lens_id_printconv_block(source_text: str) -> tuple[tuple[int, str], ...]:
    lines = tuple(enumerate(source_text.splitlines(), start=1))
    lensdata_start = next(
        (
            index
            for index, (_line_number, line) in enumerate(lines)
            if "%Image::ExifTool::Nikon::LensData0800" in line
        ),
        None,
    )
    if lensdata_start is None:
        return ()
    lens_id_start = next(
        (
            index
            for index in range(lensdata_start, len(lines))
            if "Name => 'LensID'" in lines[index][1]
        ),
        None,
    )
    if lens_id_start is None:
        return ()
    printconv_start = next(
        (
            index
            for index in range(lens_id_start, len(lines))
            if "PrintConv => {" in lines[index][1]
        ),
        None,
    )
    if printconv_start is None:
        return ()

    block: list[tuple[int, str]] = []
    for line_number, line in lines[printconv_start + 1 :]:
        if re.match(r"^\s*},\s*$", line):
            return tuple(block)
        block.append((line_number, line))
    return tuple(block)
