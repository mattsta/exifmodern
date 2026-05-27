"""Source-backed, non-mutating font metadata transaction plans.

The planner mirrors the font container responsibilities in ExifTool's
``Font.pm`` for SFNT TrueType/OpenType, TrueType collections, WOFF and WOFF2.
It validates signatures and table directories, enumerates preserved table
payloads, routes name/C2PA-readable tables as ExifTool does, records name-table
platform, encoding and language duties, and keeps byte emission behind gates.
"""

from __future__ import annotations

# Font name-table decoding intentionally carries localized glyph maps.
# ruff: noqa: RUF001
from dataclasses import dataclass
from typing import Literal

from exifmodern.json_types import JsonArray, JsonObject

SFNT_HEADER_SIZE = 12
SFNT_TABLE_RECORD_SIZE = 16
TTC_HEADER_SIZE = 12
WOFF_HEADER_SIZE = 44
WOFF_DIRECTORY_RECORD_SIZE = 20
WOFF2_HEADER_SIZE = 48
FONT_UINT32_MAX = 0xFFFFFFFF
type FontPlanStatus = Literal["planned", "unsupported"]
type FontFamily = Literal["TrueType", "OpenType", "TTC", "WOFF", "WOFF2", "Unknown"]
type FontFlavor = Literal["ttf", "otf", "ttc", "woff", "woff2", "unknown"]
type FontTableAction = Literal[
    "route_name_table",
    "route_c2pa_table",
    "preserve_metadata_table",
    "preserve_table_payload",
    "preserve_transformed_table_payload",
]
type FontTableMetadataResponsibility = Literal[
    "name_platform_encoding_language",
    "c2pa_payload_delegation",
    "head_metadata_present",
    "maxp_metadata_present",
    "os2_metadata_present",
    "post_metadata_present",
    "payload_preservation",
]
type FontEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "unsupported_font_signature",
    "truncated_font_header",
    "invalid_table_count",
    "truncated_table_directory",
    "invalid_table_offset",
    "truncated_table_payload",
    "table_checksum_mismatch",
    "truncated_ttc_header",
    "invalid_ttc_signature",
    "invalid_collection_member_count",
    "truncated_collection_directory",
    "invalid_collection_member_offset",
    "truncated_woff_header",
    "invalid_woff_signature",
    "truncated_woff_directory",
    "invalid_woff_table_offset",
    "truncated_woff_table_payload",
    "woff_compressed_payload_rewrite_blocker",
    "woff2_brotli_payload_rewrite_blocker",
    "transformed_woff2_table_rewrite_blocker",
    "font_metadata_rewrite_not_implemented",
]
type FontNamePlatform = Literal["Unicode", "Macintosh", "ISO", "Windows", "Custom", "Unknown"]

FONT_MAIN_EVIDENCE_ID = "font.main"
FONT_MAIN_SOURCE = FONT_MAIN_EVIDENCE_ID
FONT_PROCESS_EVIDENCE_ID = "font.process"
FONT_PROCESS_SOURCE = FONT_PROCESS_EVIDENCE_ID
FONT_TTC_EVIDENCE_ID = "font.ttc"
FONT_TTC_SOURCE = FONT_TTC_EVIDENCE_ID
FONT_TABLE_ENTRY_EVIDENCE_ID = "font.table_entry"
FONT_TABLE_ENTRY_SOURCE = FONT_TABLE_ENTRY_EVIDENCE_ID
FONT_OTF_EVIDENCE_ID = "font.otf"
FONT_OTF_SOURCE = FONT_OTF_EVIDENCE_ID
FONT_WOFF_EVIDENCE_ID = "font.woff"
FONT_WOFF_SOURCE = FONT_WOFF_EVIDENCE_ID
FONT_WOFF2_TAG_EVIDENCE_ID = "font.woff2_tag"
FONT_WOFF2_TAG_SOURCE = FONT_WOFF2_TAG_EVIDENCE_ID
FONT_PLATFORM_EVIDENCE_ID = "font.platform"
FONT_PLATFORM_SOURCE = FONT_PLATFORM_EVIDENCE_ID
FONT_LANGUAGE_EVIDENCE_ID = "font.language"
FONT_LANGUAGE_SOURCE = FONT_LANGUAGE_EVIDENCE_ID
FONT_NAME_TAG_EVIDENCE_ID = "font.name_tag"
FONT_NAME_TAG_SOURCE = FONT_NAME_TAG_EVIDENCE_ID
FONT_NON_MUTATING_EVIDENCE_ID = "font.non_mutating"
FONT_NON_MUTATING_SOURCE = FONT_NON_MUTATING_EVIDENCE_ID

WOFF2_KNOWN_TAGS: tuple[str, ...] = (
    "cmap",
    "head",
    "hhea",
    "hmtx",
    "maxp",
    "name",
    "OS/2",
    "post",
    "cvt ",
    "fpgm",
    "glyf",
    "loca",
    "prep",
    "CFF ",
    "VORG",
    "EBDT",
    "EBLC",
    "gasp",
    "hdmx",
    "kern",
    "LTSH",
    "PCLT",
    "VDMX",
    "vhea",
    "vmtx",
    "BASE",
    "GDEF",
    "GPOS",
    "GSUB",
    "EBSC",
    "JSTF",
    "MATH",
    "CBDT",
    "CBLC",
    "COLR",
    "CPAL",
    "SVG ",
    "sbix",
    "acnt",
    "avar",
    "bdat",
    "bloc",
    "bsln",
    "cvar",
    "fdsc",
    "feat",
    "fmtx",
    "fvar",
    "gvar",
    "hsty",
    "just",
    "lcar",
    "mort",
    "morx",
    "opbd",
    "prop",
    "trak",
    "Zapf",
    "Silf",
    "Glat",
    "Gloc",
    "Feat",
    "Sill",
)
PLATFORM_NAMES: dict[int, FontNamePlatform] = {
    0: "Unicode",
    1: "Macintosh",
    2: "ISO",
    3: "Windows",
    4: "Custom",
}
CHARSET_NAMES: dict[FontNamePlatform, dict[int, str]] = {
    "Unicode": {0: "UCS2", 1: "UCS2", 2: "UCS2", 3: "UCS2", 4: "UTF16"},
    "Macintosh": {
        0: "MacRoman",
        1: "MacJapanese",
        2: "MacChineseTW",
        3: "MacKorean",
        4: "MacArabic",
        5: "MacHebrew",
        6: "MacGreek",
        7: "MacCyrillic",
        8: "MacRSymbol",
        25: "MacChineseCN",
        29: "MacCyrillic",
        30: "MacVietnam",
    },
    "ISO": {0: "UTF8", 1: "UCS2", 2: "Latin"},
    "Windows": {0: "Symbol", 1: "UCS2", 2: "ShiftJIS", 3: "PRC", 4: "Big5", 10: "UCS4"},
    "Custom": {},
    "Unknown": {},
}
LANGUAGE_NAMES: dict[FontNamePlatform, dict[int, str]] = {
    "Macintosh": {
        0: "en",
        1: "fr",
        2: "de",
        3: "it",
        4: "nl-NL",
        5: "sv",
        6: "es",
        7: "da",
        8: "pt",
        9: "no",
        10: "he",
        11: "ja",
        13: "fi",
        19: "zh-TW",
        23: "ko",
        25: "pl",
        32: "ru",
        33: "zh-CN",
    },
    "Windows": {
        0x0407: "de-DE",
        0x0409: "en-US",
        0x0809: "en-GB",
        0x040C: "fr-FR",
        0x0411: "ja",
    },
    "Unicode": {},
    "ISO": {},
    "Custom": {},
    "Unknown": {},
}
NAME_IDS: dict[int, str] = {
    0: "Copyright",
    1: "FontFamily",
    2: "FontSubfamily",
    3: "FontSubfamilyID",
    4: "FontName",
    5: "NameTableVersion",
    6: "PostScriptFontName",
    7: "Trademark",
    8: "Manufacturer",
    9: "Designer",
    10: "Description",
    11: "VendorURL",
    12: "DesignerURL",
    13: "License",
    14: "LicenseInfoURL",
    16: "PreferredFamily",
    17: "PreferredSubfamily",
    18: "CompatibleFontName",
    19: "SampleText",
    20: "PostScriptFontName",
    21: "WWSFamilyName",
    22: "WWSSubfamilyName",
}
METADATA_TABLE_RESPONSIBILITIES: dict[str, FontTableMetadataResponsibility] = {
    "head": "head_metadata_present",
    "maxp": "maxp_metadata_present",
    "OS/2": "os2_metadata_present",
    "post": "post_metadata_present",
}


@dataclass(frozen=True)
class FontEmissionGate:
    code: FontEmissionGateCode
    reason: str
    blocks_emission: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "blocks_emission": self.blocks_emission,
            "code": self.code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FontSignatureValidation:
    family: FontFamily
    flavor: FontFlavor
    signature: bytes
    is_supported: bool
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "family": self.family,
            "flavor": self.flavor,
            "is_supported": self.is_supported,
            "signature_hex": self.signature.hex(),
        }


@dataclass(frozen=True)
class FontCollectionMemberPlan:
    index: int
    directory_offset: int
    group_name: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "directory_offset": self.directory_offset,
            "group_name": self.group_name,
            "index": self.index,
        }


@dataclass(frozen=True)
class FontTableRecordPlan:
    tag: str
    member_index: int | None
    directory_index: int
    checksum: int | None
    calculated_checksum: int | None
    offset: int | None
    payload_offset: int | None
    length: int
    compressed_length: int | None
    transformed: bool
    action: FontTableAction
    responsibilities: tuple[FontTableMetadataResponsibility, ...]
    payload_preserved: bool
    evidence_ids: tuple[str, ...]

    @property
    def checksum_valid(self) -> bool | None:
        if self.checksum is None or self.calculated_checksum is None:
            return None
        return self.checksum == self.calculated_checksum

    def to_json(self) -> JsonObject:
        return {
            "action": self.action,
            "calculated_checksum": self.calculated_checksum,
            "checksum": self.checksum,
            "checksum_valid": self.checksum_valid,
            "compressed_length": self.compressed_length,
            "directory_index": self.directory_index,
            "length": self.length,
            "member_index": self.member_index,
            "offset": self.offset,
            "payload_offset": self.payload_offset,
            "payload_preserved": self.payload_preserved,
            "responsibilities": list(self.responsibilities),
            "tag": self.tag,
            "transformed": self.transformed,
        }


@dataclass(frozen=True)
class FontNameRecordPlan:
    member_index: int | None
    table_index: int
    name_id: int
    tag_name: str | None
    platform_id: int
    platform: FontNamePlatform
    encoding_id: int
    charset: str | None
    language_id: int
    language: str | None
    string_offset: int
    string_length: int
    value_text: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "charset": self.charset,
            "encoding_id": self.encoding_id,
            "language": self.language,
            "language_id": self.language_id,
            "member_index": self.member_index,
            "name_id": self.name_id,
            "platform": self.platform,
            "platform_id": self.platform_id,
            "string_length": self.string_length,
            "string_offset": self.string_offset,
            "table_index": self.table_index,
            "tag_name": self.tag_name,
            "value_text": self.value_text,
        }


@dataclass(frozen=True)
class FontRoutingResponsibility:
    order: int
    concern: FontTableMetadataResponsibility
    description: str
    tables: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "concern": self.concern,
            "description": self.description,
            "order": self.order,
            "tables": list(self.tables),
        }


@dataclass(frozen=True)
class FontMetadataTransactionPlan:
    status: FontPlanStatus
    signature_validation: FontSignatureValidation
    collection_members: tuple[FontCollectionMemberPlan, ...]
    table_records: tuple[FontTableRecordPlan, ...]
    name_records: tuple[FontNameRecordPlan, ...]
    responsibilities: tuple[FontRoutingResponsibility, ...]
    output_emission_gates: tuple[FontEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_data: bytes

    @property
    def can_mutate_bytes(self) -> bool:
        return False

    @property
    def can_emit_output(self) -> bool:
        return not any(gate.blocks_emission for gate in self.output_emission_gates)

    @property
    def table_tags(self) -> tuple[str, ...]:
        return tuple(record.tag for record in self.table_records)

    @property
    def preserved_payload_bytes(self) -> int:
        return sum(record.length for record in self.table_records if record.payload_preserved)

    def emit(self) -> bytes:
        gate_codes = ", ".join(
            gate.code for gate in self.output_emission_gates if gate.blocks_emission
        )
        if gate_codes:
            raise ValueError(f"Font metadata transaction output is gated: {gate_codes}")
        return self.original_data

    def to_json(self) -> JsonObject:
        return {
            "can_emit_output": self.can_emit_output,
            "can_mutate_bytes": self.can_mutate_bytes,
            "collection_members": [member.to_json() for member in self.collection_members],
            "name_records": [record.to_json() for record in self.name_records],
            "output_emission_gates": [gate.to_json() for gate in self.output_emission_gates],
            "preserved_payload_bytes": self.preserved_payload_bytes,
            "responsibilities": [item.to_json() for item in self.responsibilities],
            "signature_validation": self.signature_validation.to_json(),
            "status": self.status,
            "table_records": [record.to_json() for record in self.table_records],
            "table_tags": list(self.table_tags),
        }


@dataclass(frozen=True)
class FontPlanParts:
    signature_validation: FontSignatureValidation
    collection_members: tuple[FontCollectionMemberPlan, ...]
    table_records: tuple[FontTableRecordPlan, ...]
    name_records: tuple[FontNameRecordPlan, ...]
    gates: tuple[FontEmissionGate, ...]


@dataclass(frozen=True)
class UIntBase128Read:
    value: int | None
    next_offset: int


def build_font_metadata_transaction_plan(
    data: bytes,
    *,
    allow_output_emission: bool = False,
    metadata_rewrite_requested: bool = False,
) -> FontMetadataTransactionPlan:
    """Build a non-mutating font metadata transaction plan."""

    parts = inspect_font(data)
    gates = list(parts.gates)
    if not allow_output_emission:
        gates.append(
            FontEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                (
                    "Font transaction plans preserve source bytes unless emission is "
                    "explicitly enabled."
                ),
                True,
                (FONT_NON_MUTATING_EVIDENCE_ID,),
            )
        )
    if metadata_rewrite_requested:
        gates.append(
            FontEmissionGate(
                "font_metadata_rewrite_not_implemented",
                "Font metadata rewrites require table directory, checksum and offset repair.",
                True,
                (FONT_OTF_EVIDENCE_ID, FONT_TABLE_ENTRY_EVIDENCE_ID),
            )
        )

    responsibilities = default_responsibilities(parts.table_records)
    sources = unique_sources(
        (
            *parts.signature_validation.evidence_ids,
            *(source for member in parts.collection_members for source in member.evidence_ids),
            *(source for record in parts.table_records for source in record.evidence_ids),
            *(source for record in parts.name_records for source in record.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
            *(source for item in responsibilities for source in item.evidence_ids),
        )
    )
    status: FontPlanStatus = "planned" if parts.signature_validation.is_supported else "unsupported"
    return FontMetadataTransactionPlan(
        status=status,
        signature_validation=parts.signature_validation,
        collection_members=parts.collection_members,
        table_records=parts.table_records,
        name_records=parts.name_records,
        responsibilities=responsibilities,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
        original_data=data,
    )


def inspect_font(data: bytes) -> FontPlanParts:
    if len(data) < 4:
        return unsupported_parts(
            data,
            "truncated_font_header",
            "Input ended before a font signature could be read.",
            (FONT_PROCESS_EVIDENCE_ID,),
        )
    signature = data[:4]
    if signature.startswith(b"ttcf"):
        return inspect_ttc(data)
    if signature in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"):
        return inspect_sfnt(data, 0, None, signature_validation_for_signature(signature))
    if signature in (b"wOFF", b"wOF2"):
        return inspect_woff(data, signature)
    return unsupported_parts(
        data,
        "unsupported_font_signature",
        "The leading bytes do not match ExifTool Font.pm SFNT, TTC, WOFF or WOFF2 routes.",
        (FONT_PROCESS_EVIDENCE_ID,),
    )


def unsupported_parts(
    data: bytes,
    code: FontEmissionGateCode,
    reason: str,
    sources: tuple[str, ...],
) -> FontPlanParts:
    validation = FontSignatureValidation(
        family="Unknown",
        flavor="unknown",
        signature=data[:4],
        is_supported=False,
        evidence_ids=sources,
    )
    gate = FontEmissionGate(code, reason, True, sources)
    return FontPlanParts(validation, (), (), (), (gate,))


def signature_validation_for_signature(signature: bytes) -> FontSignatureValidation:
    family: FontFamily = "OpenType" if signature == b"OTTO" else "TrueType"
    flavor: FontFlavor = "otf" if signature == b"OTTO" else "ttf"
    return FontSignatureValidation(
        family=family,
        flavor=flavor,
        signature=signature,
        is_supported=True,
        evidence_ids=(FONT_PROCESS_EVIDENCE_ID, FONT_OTF_EVIDENCE_ID),
    )


def inspect_ttc(data: bytes) -> FontPlanParts:
    validation = FontSignatureValidation(
        family="TTC",
        flavor="ttc",
        signature=data[:4],
        is_supported=True,
        evidence_ids=(FONT_PROCESS_EVIDENCE_ID, FONT_TTC_EVIDENCE_ID),
    )
    if len(data) < TTC_HEADER_SIZE:
        return FontPlanParts(
            validation,
            (),
            (),
            (),
            (
                FontEmissionGate(
                    "truncated_ttc_header",
                    "Input ended before the TTC header and member count could be read.",
                    True,
                    (FONT_TTC_EVIDENCE_ID,),
                ),
            ),
        )
    if data[:8] not in (b"ttcf\x00\x01\x00\x00", b"ttcf\x00\x02\x00\x00"):
        return FontPlanParts(
            validation,
            (),
            (),
            (),
            (
                FontEmissionGate(
                    "invalid_ttc_signature",
                    "TTC signature did not match Font.pm accepted version bytes.",
                    True,
                    (FONT_TTC_EVIDENCE_ID,),
                ),
            ),
        )
    member_count = int.from_bytes(data[8:12], "big")
    if member_count >= 0x100 or member_count == 0:
        return FontPlanParts(
            validation,
            (),
            (),
            (),
            (
                FontEmissionGate(
                    "invalid_collection_member_count",
                    "TTC member count must be between 1 and 255 as constrained by Font.pm.",
                    True,
                    (FONT_TTC_EVIDENCE_ID,),
                ),
            ),
        )
    directory_end = TTC_HEADER_SIZE + member_count * 4
    if directory_end > len(data):
        return FontPlanParts(
            validation,
            (),
            (),
            (),
            (
                FontEmissionGate(
                    "truncated_collection_directory",
                    "Input ended before all TTC member directory offsets could be read.",
                    True,
                    (FONT_TTC_EVIDENCE_ID,),
                ),
            ),
        )

    members: list[FontCollectionMemberPlan] = []
    tables: list[FontTableRecordPlan] = []
    names: list[FontNameRecordPlan] = []
    gates: list[FontEmissionGate] = []
    for index in range(member_count):
        offset_start = TTC_HEADER_SIZE + index * 4
        offset = int.from_bytes(data[offset_start : offset_start + 4], "big")
        members.append(
            FontCollectionMemberPlan(
                index=index + 1,
                directory_offset=offset,
                group_name=f"+{index + 1}",
                evidence_ids=(FONT_TTC_EVIDENCE_ID,),
            )
        )
        if offset >= len(data):
            gates.append(
                FontEmissionGate(
                    "invalid_collection_member_offset",
                    f"TTC member {index + 1} directory offset {offset} is outside the file.",
                    True,
                    (FONT_TTC_EVIDENCE_ID, FONT_OTF_EVIDENCE_ID),
                )
            )
            continue
        member_parts = inspect_sfnt(data, offset, index + 1, validation)
        tables.extend(member_parts.table_records)
        names.extend(member_parts.name_records)
        gates.extend(member_parts.gates)

    return FontPlanParts(validation, tuple(members), tuple(tables), tuple(names), tuple(gates))


def inspect_sfnt(
    data: bytes,
    base_offset: int,
    member_index: int | None,
    validation: FontSignatureValidation,
) -> FontPlanParts:
    gates: list[FontEmissionGate] = []
    if base_offset + SFNT_HEADER_SIZE > len(data):
        return FontPlanParts(
            validation,
            (),
            (),
            (),
            (
                FontEmissionGate(
                    "truncated_font_header",
                    f"Input ended before SFNT header at offset {base_offset}.",
                    True,
                    (FONT_OTF_EVIDENCE_ID,),
                ),
            ),
        )
    signature = data[base_offset : base_offset + 4]
    if signature not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"):
        gates.append(
            FontEmissionGate(
                "unsupported_font_signature",
                f"SFNT member at offset {base_offset} did not match Font.pm signatures.",
                True,
                (FONT_OTF_EVIDENCE_ID,),
            )
        )
        return FontPlanParts(validation, (), (), (), tuple(gates))

    table_count = int.from_bytes(data[base_offset + 4 : base_offset + 6], "big")
    if table_count == 0 or table_count >= 0x200:
        gates.append(
            FontEmissionGate(
                "invalid_table_count",
                f"SFNT table count {table_count} is outside Font.pm bounds.",
                True,
                (FONT_OTF_EVIDENCE_ID,),
            )
        )
        return FontPlanParts(validation, (), (), (), tuple(gates))

    directory_start = base_offset + SFNT_HEADER_SIZE
    directory_end = directory_start + table_count * SFNT_TABLE_RECORD_SIZE
    if directory_end > len(data):
        gates.append(
            FontEmissionGate(
                "truncated_table_directory",
                f"SFNT table directory at offset {directory_start} is truncated.",
                True,
                (FONT_OTF_EVIDENCE_ID,),
            )
        )
        return FontPlanParts(validation, (), (), (), tuple(gates))

    records: list[FontTableRecordPlan] = []
    name_records: list[FontNameRecordPlan] = []
    for index in range(table_count):
        start = directory_start + index * SFNT_TABLE_RECORD_SIZE
        raw_tag = data[start : start + 4]
        tag = decode_tag(raw_tag)
        checksum = int.from_bytes(data[start + 4 : start + 8], "big")
        offset = int.from_bytes(data[start + 8 : start + 12], "big")
        length = int.from_bytes(data[start + 12 : start + 16], "big")
        payload_start = base_offset + offset
        payload_end = payload_start + length
        table_gates = validate_payload_bounds(
            payload_start, payload_end, data, tag, (FONT_OTF_EVIDENCE_ID,)
        )
        gates.extend(table_gates)
        payload = data[payload_start:payload_end] if not table_gates else b""
        calculated = sfnt_checksum(payload) if payload else None
        if payload and calculated != checksum:
            gates.append(
                FontEmissionGate(
                    "table_checksum_mismatch",
                    f"Table {tag} checksum does not match its preserved payload.",
                    True,
                    (FONT_OTF_EVIDENCE_ID,),
                )
            )
        record = build_table_record(
            tag=tag,
            member_index=member_index,
            directory_index=index,
            checksum=checksum,
            calculated_checksum=calculated,
            offset=offset,
            payload_offset=payload_start if not table_gates else None,
            length=length,
            compressed_length=None,
            transformed=False,
            sources=(FONT_OTF_EVIDENCE_ID, FONT_TABLE_ENTRY_EVIDENCE_ID),
        )
        records.append(record)
        if tag == "name" and payload:
            parsed_names, name_gates = parse_name_records(
                payload, member_index, index, payload_start
            )
            name_records.extend(parsed_names)
            gates.extend(name_gates)

    return FontPlanParts(validation, (), tuple(records), tuple(name_records), tuple(gates))


def inspect_woff(data: bytes, signature: bytes) -> FontPlanParts:
    if signature == b"wOFF":
        return inspect_woff1(data)
    return inspect_woff2(data)


def inspect_woff1(data: bytes) -> FontPlanParts:
    validation = FontSignatureValidation(
        family="WOFF",
        flavor="woff",
        signature=data[:4],
        is_supported=True,
        evidence_ids=(FONT_PROCESS_EVIDENCE_ID, FONT_WOFF_EVIDENCE_ID),
    )
    if len(data) < WOFF_HEADER_SIZE:
        return FontPlanParts(
            validation,
            (),
            (),
            (),
            (
                FontEmissionGate(
                    "truncated_woff_header",
                    "Input ended before the WOFF header could be read.",
                    True,
                    (FONT_WOFF_EVIDENCE_ID,),
                ),
            ),
        )
    table_count = int.from_bytes(data[12:14], "big")
    directory_start = WOFF_HEADER_SIZE
    directory_end = directory_start + table_count * WOFF_DIRECTORY_RECORD_SIZE
    if directory_end > len(data):
        return FontPlanParts(
            validation,
            (),
            (),
            (),
            (
                FontEmissionGate(
                    "truncated_woff_directory",
                    "Input ended before all WOFF directory records could be read.",
                    True,
                    (FONT_WOFF_EVIDENCE_ID,),
                ),
            ),
        )

    records: list[FontTableRecordPlan] = []
    names: list[FontNameRecordPlan] = []
    gates: list[FontEmissionGate] = []
    for index in range(table_count):
        start = directory_start + index * WOFF_DIRECTORY_RECORD_SIZE
        tag = decode_tag(data[start : start + 4])
        offset = int.from_bytes(data[start + 4 : start + 8], "big")
        compressed_length = int.from_bytes(data[start + 8 : start + 12], "big")
        length = int.from_bytes(data[start + 12 : start + 16], "big")
        checksum = int.from_bytes(data[start + 16 : start + 20], "big")
        payload_end = offset + compressed_length
        table_gates = validate_payload_bounds(
            offset,
            payload_end,
            data,
            tag,
            (FONT_WOFF_EVIDENCE_ID,),
        )
        gates.extend(table_gates)
        if compressed_length != length:
            gates.append(
                FontEmissionGate(
                    "woff_compressed_payload_rewrite_blocker",
                    f"WOFF table {tag} is compressed and must remain preserved by this planner.",
                    True,
                    (FONT_WOFF_EVIDENCE_ID,),
                )
            )
        payload = (
            data[offset:payload_end] if not table_gates and compressed_length == length else b""
        )
        calculated = sfnt_checksum(payload) if payload else None
        if payload and calculated != checksum:
            gates.append(
                FontEmissionGate(
                    "table_checksum_mismatch",
                    f"WOFF table {tag} checksum does not match its stored payload.",
                    True,
                    (FONT_WOFF_EVIDENCE_ID,),
                )
            )
        records.append(
            build_table_record(
                tag=tag,
                member_index=None,
                directory_index=index,
                checksum=checksum,
                calculated_checksum=calculated,
                offset=offset,
                payload_offset=offset if not table_gates else None,
                length=length,
                compressed_length=compressed_length,
                transformed=False,
                sources=(FONT_WOFF_EVIDENCE_ID, FONT_TABLE_ENTRY_EVIDENCE_ID),
            )
        )
        if tag == "name" and payload:
            parsed_names, name_gates = parse_name_records(payload, None, index, offset)
            names.extend(parsed_names)
            gates.extend(name_gates)
    return FontPlanParts(validation, (), tuple(records), tuple(names), tuple(gates))


def inspect_woff2(data: bytes) -> FontPlanParts:
    validation = FontSignatureValidation(
        family="WOFF2",
        flavor="woff2",
        signature=data[:4],
        is_supported=True,
        evidence_ids=(FONT_PROCESS_EVIDENCE_ID, FONT_WOFF_EVIDENCE_ID, FONT_WOFF2_TAG_EVIDENCE_ID),
    )
    if len(data) < WOFF2_HEADER_SIZE:
        return FontPlanParts(
            validation,
            (),
            (),
            (),
            (
                FontEmissionGate(
                    "truncated_woff_header",
                    "Input ended before the WOFF2 header could be read.",
                    True,
                    (FONT_WOFF_EVIDENCE_ID,),
                ),
            ),
        )
    table_count = int.from_bytes(data[12:14], "big")
    offset = WOFF2_HEADER_SIZE
    records: list[FontTableRecordPlan] = []
    gates: list[FontEmissionGate] = [
        FontEmissionGate(
            "woff2_brotli_payload_rewrite_blocker",
            "WOFF2 stores table payloads in a shared Brotli stream that this planner preserves.",
            True,
            (FONT_WOFF_EVIDENCE_ID,),
        )
    ]
    for index in range(table_count):
        if offset >= len(data):
            gates.append(
                FontEmissionGate(
                    "truncated_woff_directory",
                    "Input ended before all WOFF2 directory records could be read.",
                    True,
                    (FONT_WOFF_EVIDENCE_ID,),
                )
            )
            break
        flags = data[offset]
        offset += 1
        tag_index = flags & 0x3F
        if tag_index == 0x3F:
            if offset + 4 > len(data):
                gates.append(
                    FontEmissionGate(
                        "truncated_woff_directory",
                        "WOFF2 custom tag is truncated.",
                        True,
                        (FONT_WOFF_EVIDENCE_ID,),
                    )
                )
                break
            tag = decode_tag(data[offset : offset + 4])
            offset += 4
        else:
            tag = WOFF2_KNOWN_TAGS[tag_index]
        length_read = read_uint_base128(data, offset)
        if length_read.value is None:
            gates.append(
                FontEmissionGate(
                    "truncated_woff_directory",
                    "WOFF2 table length could not be decoded.",
                    True,
                    (FONT_WOFF_EVIDENCE_ID,),
                )
            )
            break
        offset = length_read.next_offset
        transformed = False
        length = length_read.value
        if ((tag in ("glyf", "loca")) and not flags & 0xC0) or (
            tag not in ("glyf", "loca") and bool(flags & 0xC0)
        ):
            transformed_read = read_uint_base128(data, offset)
            if transformed_read.value is None:
                gates.append(
                    FontEmissionGate(
                        "truncated_woff_directory",
                        "WOFF2 transformed table length could not be decoded.",
                        True,
                        (FONT_WOFF_EVIDENCE_ID,),
                    )
                )
                break
            length = transformed_read.value
            offset = transformed_read.next_offset
            transformed = True
            gates.append(
                FontEmissionGate(
                    "transformed_woff2_table_rewrite_blocker",
                    f"WOFF2 table {tag} uses a transform and is preserved.",
                    True,
                    (FONT_WOFF_EVIDENCE_ID,),
                )
            )
        records.append(
            build_table_record(
                tag=tag,
                member_index=None,
                directory_index=index,
                checksum=None,
                calculated_checksum=None,
                offset=None,
                payload_offset=None,
                length=length,
                compressed_length=None,
                transformed=transformed,
                sources=(
                    FONT_WOFF_EVIDENCE_ID,
                    FONT_WOFF2_TAG_EVIDENCE_ID,
                    FONT_TABLE_ENTRY_EVIDENCE_ID,
                ),
            )
        )
    return FontPlanParts(validation, (), tuple(records), (), tuple(gates))


def build_table_record(
    *,
    tag: str,
    member_index: int | None,
    directory_index: int,
    checksum: int | None,
    calculated_checksum: int | None,
    offset: int | None,
    payload_offset: int | None,
    length: int,
    compressed_length: int | None,
    transformed: bool,
    sources: tuple[str, ...],
) -> FontTableRecordPlan:
    responsibilities: list[FontTableMetadataResponsibility] = ["payload_preservation"]
    action: FontTableAction = "preserve_table_payload"
    if transformed:
        action = "preserve_transformed_table_payload"
    elif tag == "name":
        action = "route_name_table"
        responsibilities.append("name_platform_encoding_language")
    elif tag == "C2PA":
        action = "route_c2pa_table"
        responsibilities.append("c2pa_payload_delegation")
    elif tag in METADATA_TABLE_RESPONSIBILITIES:
        action = "preserve_metadata_table"
        responsibilities.append(METADATA_TABLE_RESPONSIBILITIES[tag])
    return FontTableRecordPlan(
        tag=tag,
        member_index=member_index,
        directory_index=directory_index,
        checksum=checksum,
        calculated_checksum=calculated_checksum,
        offset=offset,
        payload_offset=payload_offset,
        length=length,
        compressed_length=compressed_length,
        transformed=transformed,
        action=action,
        responsibilities=tuple(responsibilities),
        payload_preserved=True,
        evidence_ids=sources,
    )


def parse_name_records(
    payload: bytes,
    member_index: int | None,
    table_index: int,
    payload_offset: int,
) -> tuple[list[FontNameRecordPlan], list[FontEmissionGate]]:
    gates: list[FontEmissionGate] = []
    if len(payload) < 6:
        return (
            [],
            [
                FontEmissionGate(
                    "truncated_table_payload",
                    "Name table ended before its format, count and string offset fields.",
                    True,
                    (FONT_TABLE_ENTRY_EVIDENCE_ID,),
                )
            ],
        )
    count = int.from_bytes(payload[2:4], "big")
    records_end = 6 + count * 12
    if records_end > len(payload):
        return (
            [],
            [
                FontEmissionGate(
                    "truncated_table_payload",
                    "Name table ended before all name records could be read.",
                    True,
                    (FONT_TABLE_ENTRY_EVIDENCE_ID,),
                )
            ],
        )
    string_start = int.from_bytes(payload[4:6], "big")
    if string_start < records_end or string_start > len(payload):
        return (
            [],
            [
                FontEmissionGate(
                    "invalid_table_offset",
                    "Name table string storage offset is outside the allowed record area.",
                    True,
                    (FONT_TABLE_ENTRY_EVIDENCE_ID,),
                )
            ],
        )

    language_tags = parse_language_tags(payload, records_end, string_start)
    plans: list[FontNameRecordPlan] = []
    for index in range(count):
        start = 6 + index * 12
        platform_id = int.from_bytes(payload[start : start + 2], "big")
        encoding_id = int.from_bytes(payload[start + 2 : start + 4], "big")
        language_id = int.from_bytes(payload[start + 4 : start + 6], "big")
        name_id = int.from_bytes(payload[start + 6 : start + 8], "big")
        string_length = int.from_bytes(payload[start + 8 : start + 10], "big")
        string_offset = int.from_bytes(payload[start + 10 : start + 12], "big") + string_start
        if string_offset + string_length > len(payload):
            gates.append(
                FontEmissionGate(
                    "truncated_table_payload",
                    f"Name record {index} string extends beyond the name table.",
                    True,
                    (FONT_TABLE_ENTRY_EVIDENCE_ID,),
                )
            )
            continue
        platform = PLATFORM_NAMES.get(platform_id, "Unknown")
        charset = CHARSET_NAMES[platform].get(encoding_id)
        language = LANGUAGE_NAMES[platform].get(language_id, language_tags.get(language_id))
        raw_value = payload[string_offset : string_offset + string_length]
        plans.append(
            FontNameRecordPlan(
                member_index=member_index,
                table_index=table_index,
                name_id=name_id,
                tag_name=NAME_IDS.get(name_id),
                platform_id=platform_id,
                platform=platform,
                encoding_id=encoding_id,
                charset=charset,
                language_id=language_id,
                language=language,
                string_offset=payload_offset + string_offset,
                string_length=string_length,
                value_text=decode_name_value(raw_value, charset),
                evidence_ids=(
                    FONT_TABLE_ENTRY_EVIDENCE_ID,
                    FONT_PLATFORM_EVIDENCE_ID,
                    FONT_LANGUAGE_EVIDENCE_ID,
                    FONT_NAME_TAG_EVIDENCE_ID,
                ),
            )
        )
    return plans, gates


def decode_name_value(data: bytes, charset: str | None) -> str:
    if charset in {"UCS2", "UTF16"}:
        return data.decode("utf-16-be", errors="replace").rstrip("\x00")
    if charset == "UTF8":
        return data.decode("utf-8", errors="replace").rstrip("\x00")
    if charset == "Latin":
        return data.decode("latin-1", errors="replace").rstrip("\x00")
    if charset == "MacRoman":
        return data.decode("mac_roman", errors="replace").rstrip("\x00")
    if charset == "MacJapanese":
        return data.decode("shift_jis", errors="replace").rstrip("\x00")
    if charset == "MacChineseTW":
        return data.decode("big5", errors="replace").rstrip("\x00")
    if charset == "MacChineseCN":
        return data.decode("gb2312", errors="replace").rstrip("\x00")
    if charset == "MacKorean":
        return data.decode("euc_kr", errors="replace").rstrip("\x00")
    if charset == "MacHebrew":
        return decode_mac_hebrew(data).rstrip("\x00")
    return data.decode("latin-1", errors="replace").rstrip("\x00")


MAC_HEBREW_EXTRA_CHARS: dict[int, str] = {
    0x80: "Ä",
    0x81: "Å",
    0x82: "Ç",
    0x83: "É",
    0x84: "Ñ",
    0x85: "Ö",
    0x86: "Ü",
    0x87: "á",
    0x88: "à",
    0x89: "â",
    0x8A: "ä",
    0x8B: "ã",
    0x8C: "å",
    0x8D: "ç",
    0x8E: "é",
    0x8F: "è",
    0x90: "ê",
    0x91: "ë",
    0x92: "í",
    0x93: "ì",
    0x94: "î",
    0x95: "ï",
    0x96: "ñ",
    0x97: "ó",
    0x98: "ò",
    0x99: "ô",
    0x9A: "ö",
    0x9B: "õ",
    0x9C: "ú",
    0x9D: "ù",
    0x9E: "û",
    0x9F: "ü",
    0xE0: "א",
    0xE1: "ב",
    0xE2: "ג",
    0xE3: "ד",
    0xE4: "ה",
    0xE5: "ו",
    0xE6: "ז",
    0xE7: "ח",
    0xE8: "ט",
    0xE9: "י",
    0xEA: "ך",
    0xEB: "כ",
    0xEC: "ל",
    0xED: "ם",
    0xEE: "מ",
    0xEF: "ן",
    0xF0: "נ",
    0xF1: "ס",
    0xF2: "ע",
    0xF3: "ף",
    0xF4: "פ",
    0xF5: "ץ",
    0xF6: "צ",
    0xF7: "ק",
    0xF8: "ר",
    0xF9: "ש",
    0xFA: "ת",
}


def decode_mac_hebrew(data: bytes) -> str:
    return "".join(
        chr(byte) if byte < 0x80 else MAC_HEBREW_EXTRA_CHARS.get(byte, "�") for byte in data
    )


def parse_language_tags(payload: bytes, records_end: int, string_start: int) -> dict[int, str]:
    if int.from_bytes(payload[:2], "big") != 1 or records_end + 2 > len(payload):
        return {}
    count = int.from_bytes(payload[records_end : records_end + 2], "big")
    if count == 0 or records_end + 2 + count * 4 >= len(payload):
        return {}
    tags: dict[int, str] = {}
    for index in range(count):
        start = records_end + 2 + index * 4
        length = int.from_bytes(payload[start : start + 2], "big")
        relative_offset = int.from_bytes(payload[start + 2 : start + 4], "big")
        if length == 0 or length & 1 or length > 40:
            break
        offset = string_start + relative_offset
        if offset + length > len(payload):
            break
        tags[index + 0x8000] = sanitize_language(payload[offset : offset + length])
    return tags


def sanitize_language(data: bytes) -> str:
    text = data.decode("utf-16-be", errors="ignore")
    return "".join(character for character in text if character.isalnum() or character in "-_")


def validate_payload_bounds(
    start: int,
    end: int,
    data: bytes,
    tag: str,
    sources: tuple[str, ...],
) -> list[FontEmissionGate]:
    if start < 0 or start > len(data):
        return [
            FontEmissionGate(
                "invalid_table_offset",
                f"Table {tag} offset {start} is outside the file.",
                True,
                sources,
            )
        ]
    if end < start or end > len(data):
        return [
            FontEmissionGate(
                "truncated_table_payload",
                f"Table {tag} payload extends beyond the file.",
                True,
                sources,
            )
        ]
    return []


def sfnt_checksum(payload: bytes) -> int:
    padded_length = ((len(payload) + 3) // 4) * 4
    padded = payload + b"\0" * (padded_length - len(payload))
    total = 0
    for offset in range(0, padded_length, 4):
        total = (total + int.from_bytes(padded[offset : offset + 4], "big")) & FONT_UINT32_MAX
    return total


def read_uint_base128(data: bytes, offset: int) -> UIntBase128Read:
    value = 0
    cursor = offset
    for index in range(5):
        if cursor >= len(data):
            return UIntBase128Read(None, cursor)
        byte = data[cursor]
        cursor += 1
        if index == 0 and byte == 0x80:
            return UIntBase128Read(None, cursor)
        if value & 0xFE000000:
            return UIntBase128Read(None, cursor)
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return UIntBase128Read(value, cursor)
    return UIntBase128Read(None, cursor)


def decode_tag(tag: bytes) -> str:
    return tag.decode("latin-1")


def default_responsibilities(
    records: tuple[FontTableRecordPlan, ...],
) -> tuple[FontRoutingResponsibility, ...]:
    present = {record.tag for record in records}
    items: list[FontRoutingResponsibility] = [
        FontRoutingResponsibility(
            1,
            "name_platform_encoding_language",
            "Route name-table records through ExifTool platform, charset and language mappings.",
            ("name",),
            (
                FONT_TABLE_ENTRY_EVIDENCE_ID,
                FONT_PLATFORM_EVIDENCE_ID,
                FONT_LANGUAGE_EVIDENCE_ID,
                FONT_NAME_TAG_EVIDENCE_ID,
            ),
        ),
        FontRoutingResponsibility(
            2,
            "payload_preservation",
            "Preserve all table payload bytes unless a later full font writer repairs offsets.",
            tuple(sorted(present)),
            (FONT_OTF_EVIDENCE_ID, FONT_TABLE_ENTRY_EVIDENCE_ID, FONT_WOFF_EVIDENCE_ID),
        ),
    ]
    optional_tables: tuple[tuple[str, FontTableMetadataResponsibility, str], ...] = (
        ("head", "head_metadata_present", "Record presence of the font header table."),
        ("maxp", "maxp_metadata_present", "Record presence of the maximum profile table."),
        ("OS/2", "os2_metadata_present", "Record presence of the OS/2 metrics table."),
        ("post", "post_metadata_present", "Record presence of the PostScript table."),
    )
    for order, item in enumerate(optional_tables, start=3):
        tag, concern, description = item
        if tag in present:
            items.append(
                FontRoutingResponsibility(
                    order,
                    concern,
                    description,
                    (tag,),
                    (FONT_OTF_EVIDENCE_ID, FONT_TABLE_ENTRY_EVIDENCE_ID),
                )
            )
    if "C2PA" in present:
        items.append(
            FontRoutingResponsibility(
                len(items) + 1,
                "c2pa_payload_delegation",
                "Route C2PA table bytes to the same delegated metadata family as Font.pm.",
                ("C2PA",),
                (FONT_MAIN_EVIDENCE_ID, FONT_TABLE_ENTRY_EVIDENCE_ID),
            )
        )
    return tuple(items)


def unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source not in seen:
            seen.add(source)
            unique.append(source)
    return tuple(unique)


def unique_gates(gates: tuple[FontEmissionGate, ...]) -> tuple[FontEmissionGate, ...]:
    unique: list[FontEmissionGate] = []
    seen: set[tuple[FontEmissionGateCode, str]] = set()
    for gate in gates:
        key = (gate.code, gate.reason)
        if key not in seen:
            seen.add(key)
            unique.append(gate)
    return tuple(unique)


def evidence_ids_to_json(sources: tuple[str, ...]) -> JsonArray:
    return list(sources)
