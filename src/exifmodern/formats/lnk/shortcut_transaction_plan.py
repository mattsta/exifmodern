"""Source-grounded Windows Shell Link transaction planning.

The planner mirrors the read choreography in ExifTool's ``LNK.pm``: validate
the Shell Link header, expose the header fields and flag-routed sections,
preserve raw section bytes, route known ExtraData blocks, and record truncation
or offset hazards as explicit gates. It does not implement LNK mutation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

LNK_HEADER_MIN_SIZE = 0x4C
LNK_SHELL_LINK_CLSID = b"\x01\x14\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46"

type LnkPlanStatus = Literal["planned", "unsupported"]
type LnkHeaderStatus = Literal["valid", "truncated", "invalid_signature", "invalid_size"]
type LnkSectionKind = Literal["target_id_list", "link_info"]
type LnkSectionStatus = Literal["absent", "present", "truncated", "invalid"]
type LnkStringName = Literal[
    "Description",
    "RelativePath",
    "WorkingDirectory",
    "CommandLineArguments",
    "IconFileName",
]
type LnkStringStatus = Literal["absent", "present", "empty", "truncated", "invalid"]
type LnkExtraDataRoute = Literal[
    "UnknownData",
    "EnvVarData",
    "ConsoleData",
    "TrackerData",
    "ConsoleFEData",
    "SpecialFolderData",
    "DarwinData",
    "IconEnvData",
    "ShimData",
    "PropertyStoreData",
    "KnownFolderData",
    "VistaIDListData",
]
type LnkExtraDataStatus = Literal["present", "truncated", "skipped"]
type LnkBlockResponsibilityKind = Literal["console", "tracker", "console_fe", "environment"]
type LnkEmissionGateCode = Literal[
    "non_mutating_plan_requires_explicit_emission",
    "lnk_rewrite_not_supported",
    "truncated_lnk_header",
    "unsupported_lnk_signature",
    "invalid_lnk_header_size",
    "truncated_lnk_header_extension",
    "missing_target_id_list",
    "truncated_target_id_list",
    "missing_link_information",
    "invalid_link_information",
    "truncated_link_information",
    "link_info_too_short",
    "link_info_network_offset_exceeds_block",
    "invalid_string_data",
    "truncated_string_data",
    "truncated_extra_data",
]

LNK_FILE_ATTRIBUTES_SOURCE = "lnk.file_attributes.bitmask"
LNK_FILE_TIME_SOURCE = "lnk.filetime.conversion"
LNK_MAIN_TABLE_SOURCE = "lnk.main_table.tags"
LNK_HEADER_SOURCE = "lnk.process.header_validation"
LNK_TARGET_ID_LIST_SOURCE = "lnk.process.target_id_list"
LNK_LINK_INFO_READ_SOURCE = "lnk.process.link_info_read"
LNK_STRING_DATA_SOURCE = "lnk.process.string_data"
LNK_EXTRA_DATA_SOURCE = "lnk.process.extra_data"
LNK_OVERLAY_SOURCE = "lnk.process.overlay_warning"
LNK_LINK_INFO_PROCESS_SOURCE = "lnk.process_link_info"
LNK_UNKNOWN_DATA_SOURCE = "lnk.unknown_data"
LNK_CONSOLE_DATA_SOURCE = "lnk.console_data"
LNK_TRACKER_DATA_SOURCE = "lnk.tracker_data"
LNK_CONSOLE_FE_DATA_SOURCE = "lnk.console_fe_data"
LNK_ENV_VAR_DATA_SOURCE = "lnk.env_var_data"
LNK_INI_SOURCE = "lnk.ini_table"
LNK_PROCESS_INI_SOURCE = "lnk.process_ini"
LNK_ITEM_ID_SOURCE = "lnk.item_id"
LNK_TARGET_INFO_SOURCE = "lnk.target_info"
LNK_BEEF0004_SOURCE = "lnk.beef0004"

LNK_TRANSACTION_SOURCES = (
    LNK_FILE_ATTRIBUTES_SOURCE,
    LNK_FILE_TIME_SOURCE,
    LNK_MAIN_TABLE_SOURCE,
    LNK_HEADER_SOURCE,
    LNK_TARGET_ID_LIST_SOURCE,
    LNK_LINK_INFO_READ_SOURCE,
    LNK_STRING_DATA_SOURCE,
    LNK_EXTRA_DATA_SOURCE,
    LNK_OVERLAY_SOURCE,
    LNK_LINK_INFO_PROCESS_SOURCE,
    LNK_UNKNOWN_DATA_SOURCE,
    LNK_CONSOLE_DATA_SOURCE,
    LNK_TRACKER_DATA_SOURCE,
    LNK_CONSOLE_FE_DATA_SOURCE,
    LNK_ENV_VAR_DATA_SOURCE,
    LNK_INI_SOURCE,
    LNK_PROCESS_INI_SOURCE,
    LNK_ITEM_ID_SOURCE,
    LNK_TARGET_INFO_SOURCE,
    LNK_BEEF0004_SOURCE,
)

LINK_FLAG_NAMES: dict[int, str] = {
    0: "IDList",
    1: "LinkInfo",
    2: "Description",
    3: "RelativePath",
    4: "WorkingDir",
    5: "CommandArgs",
    6: "IconFile",
    7: "Unicode",
    8: "NoLinkInfo",
    9: "ExpString",
    10: "SeparateProc",
    12: "DarwinID",
    13: "RunAsUser",
    14: "ExpIcon",
    15: "NoPidAlias",
    17: "RunWithShim",
    18: "NoLinkTrack",
    19: "TargetMetadata",
    20: "NoLinkPathTracking",
    21: "NoKnownFolderTracking",
    22: "NoKnownFolderAlias",
    23: "LinkToLink",
    24: "UnaliasOnSave",
    25: "PreferEnvPath",
    26: "KeepLocalIDList",
}
FILE_ATTRIBUTE_NAMES: dict[int, str] = {
    0: "Read-only",
    1: "Hidden",
    2: "System",
    3: "Volume",
    4: "Directory",
    5: "Archive",
    6: "Encrypted?",
    7: "Normal",
    8: "Temporary",
    9: "Sparse",
    10: "Reparse point",
    11: "Compressed",
    12: "Offline",
    13: "Not indexed",
    14: "Encrypted",
}
STRING_ROUTES: tuple[tuple[int, LnkStringName, int], ...] = (
    (0, "Description", 0x04),
    (1, "RelativePath", 0x08),
    (2, "WorkingDirectory", 0x10),
    (3, "CommandLineArguments", 0x20),
    (4, "IconFileName", 0x40),
)
EXTRA_DATA_ROUTES: dict[int, LnkExtraDataRoute] = {
    0xA0000001: "EnvVarData",
    0xA0000002: "ConsoleData",
    0xA0000003: "TrackerData",
    0xA0000004: "ConsoleFEData",
    0xA0000005: "SpecialFolderData",
    0xA0000006: "DarwinData",
    0xA0000007: "IconEnvData",
    0xA0000008: "ShimData",
    0xA0000009: "PropertyStoreData",
    0xA000000B: "KnownFolderData",
    0xA000000C: "VistaIDListData",
}
STRUCTURAL_GATE_CODES: set[LnkEmissionGateCode] = {
    "truncated_lnk_header",
    "unsupported_lnk_signature",
    "invalid_lnk_header_size",
    "truncated_lnk_header_extension",
    "missing_target_id_list",
    "truncated_target_id_list",
    "missing_link_information",
    "invalid_link_information",
    "truncated_link_information",
    "link_info_too_short",
    "link_info_network_offset_exceeds_block",
    "invalid_string_data",
    "truncated_string_data",
    "truncated_extra_data",
}


@dataclass(frozen=True)
class LnkShortcutRewriteRequest:
    requested_tags: tuple[str, ...]


@dataclass(frozen=True)
class LnkHeaderPlan:
    status: LnkHeaderStatus
    header_size: int | None
    shell_link_class_id: bytes | None
    flags: int | None
    file_attributes: int | None
    target_file_size: int | None
    icon_index: int | None
    run_window: int | None
    hot_key: int | None
    header_range: tuple[int, int] | None
    blocker_code: LnkEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LnkFlagResponsibilityPlan:
    bit: int
    name: str
    present: bool
    responsibility: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LnkFileAttributePlan:
    raw_value: int | None
    active_attributes: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LnkTimestampPlan:
    name: str
    raw_filetime: int | None
    unix_seconds: float | None
    present: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LnkSectionPlan:
    kind: LnkSectionKind
    status: LnkSectionStatus
    offset: int | None
    end_offset: int | None
    declared_size: int | None
    available_size: int
    payload: bytes
    blocker_code: LnkEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LnkLinkInfoRoutePlan:
    name: str
    present: bool
    offset: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LnkLinkInfoPlan:
    present: bool
    status: LnkSectionStatus
    header_size: int | None
    link_info_flags: int | None
    routes: tuple[LnkLinkInfoRoutePlan, ...]
    blocker_code: LnkEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LnkStringDataPlan:
    name: LnkStringName
    flag_mask: int
    status: LnkStringStatus
    offset: int | None
    end_offset: int | None
    declared_character_count: int | None
    consumed_byte_count: int
    is_unicode: bool
    limited_to_windows_count: bool
    blocker_code: LnkEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LnkExtraDataBlockPlan:
    index: int
    status: LnkExtraDataStatus
    offset: int
    end_offset: int
    declared_size: int
    signature: int | None
    route: LnkExtraDataRoute
    payload: bytes
    preserve_unknown: bool
    blocker_code: LnkEmissionGateCode | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LnkExtraDataTerminatorPlan:
    offset: int | None
    declared_size: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LnkBlockResponsibilityPlan:
    kind: LnkBlockResponsibilityKind
    block_index: int
    fields: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LnkOverlayPlan:
    offset: int
    size: int
    has_non_zero_bytes: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LnkOutputEmissionGate:
    code: LnkEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class LnkShortcutTransactionPlan:
    status: LnkPlanStatus
    input_size: int
    header: LnkHeaderPlan
    flag_responsibilities: tuple[LnkFlagResponsibilityPlan, ...]
    file_attributes: LnkFileAttributePlan
    timestamps: tuple[LnkTimestampPlan, ...]
    target_id_list: LnkSectionPlan
    link_info_section: LnkSectionPlan
    link_info: LnkLinkInfoPlan
    string_data: tuple[LnkStringDataPlan, ...]
    extra_data_blocks: tuple[LnkExtraDataBlockPlan, ...]
    extra_data_terminator: LnkExtraDataTerminatorPlan
    block_responsibilities: tuple[LnkBlockResponsibilityPlan, ...]
    overlay: LnkOverlayPlan
    output_emission_gates: tuple[LnkOutputEmissionGate, ...]
    evidence_ids: tuple[str, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"LNK shortcut transaction output is gated: {gate_codes}")
        return self.original_bytes


def build_lnk_shortcut_transaction_plan(
    lnk_data: bytes,
    *,
    requested_rewrite: LnkShortcutRewriteRequest | None = None,
    allow_output_emission: bool = False,
) -> LnkShortcutTransactionPlan:
    header = _header_plan(lnk_data)
    flags = header.flags or 0
    offset = (
        header.header_size if header.status == "valid" and header.header_size is not None else 0
    )
    gates: list[LnkOutputEmissionGate] = []
    if header.blocker_code is not None:
        gates.append(_gate(header.blocker_code, header.evidence_ids))

    target_id_list = _absent_section("target_id_list", LNK_TARGET_ID_LIST_SOURCE)
    if header.status == "valid" and flags & 0x01:
        target_id_list = _target_id_list_plan(lnk_data, offset)
        offset = target_id_list.end_offset or len(lnk_data)
        if target_id_list.blocker_code is not None:
            gates.append(_gate(target_id_list.blocker_code, target_id_list.evidence_ids))

    link_info_section = _absent_section("link_info", LNK_LINK_INFO_READ_SOURCE)
    link_info = _absent_link_info()
    if header.status == "valid" and flags & 0x02:
        link_info_section = _link_info_section_plan(lnk_data, offset)
        offset = link_info_section.end_offset or len(lnk_data)
        if link_info_section.blocker_code is not None:
            gates.append(_gate(link_info_section.blocker_code, link_info_section.evidence_ids))
        link_info = _link_info_plan(link_info_section)
        if link_info.blocker_code is not None:
            gates.append(_gate(link_info.blocker_code, link_info.evidence_ids))

    strings, offset, string_gates = _string_data_plans(lnk_data, flags, offset)
    gates.extend(string_gates)
    extra_blocks, terminator, overlay, extra_gates = _extra_data_plans(lnk_data, offset)
    gates.extend(extra_gates)

    if requested_rewrite is not None and requested_rewrite.requested_tags:
        gates.append(
            LnkOutputEmissionGate(
                "lnk_rewrite_not_supported",
                (
                    "LNK.pm exposes Shell Link data through reader routing only; "
                    "no LNK writer is modeled."
                ),
                (LNK_HEADER_SOURCE, LNK_MAIN_TABLE_SOURCE),
            )
        )
    if not allow_output_emission:
        gates.append(
            LnkOutputEmissionGate(
                "non_mutating_plan_requires_explicit_emission",
                "LNK shortcut transaction plans are preserve-only unless emission is explicit.",
                (LNK_HEADER_SOURCE,),
            )
        )

    unique_gates = _unique_gates(gates)
    status: LnkPlanStatus = "unsupported" if _has_structural_gate(unique_gates) else "planned"
    block_responsibilities = _block_responsibilities(extra_blocks)
    return LnkShortcutTransactionPlan(
        status=status,
        input_size=len(lnk_data),
        header=header,
        flag_responsibilities=_flag_responsibilities(flags),
        file_attributes=_file_attributes_plan(header.file_attributes),
        timestamps=_timestamp_plans(lnk_data, header.status),
        target_id_list=target_id_list,
        link_info_section=link_info_section,
        link_info=link_info,
        string_data=strings,
        extra_data_blocks=extra_blocks,
        extra_data_terminator=terminator,
        block_responsibilities=block_responsibilities,
        overlay=overlay,
        output_emission_gates=unique_gates,
        evidence_ids=_unique_sources(
            (
                *LNK_TRANSACTION_SOURCES,
                *header.evidence_ids,
                *target_id_list.evidence_ids,
                *link_info_section.evidence_ids,
                *link_info.evidence_ids,
                *(source for item in strings for source in item.evidence_ids),
                *(source for item in extra_blocks for source in item.evidence_ids),
                *(source for item in block_responsibilities for source in item.evidence_ids),
                *(source for item in unique_gates for source in item.evidence_ids),
            )
        ),
        original_bytes=lnk_data,
    )


plan_lnk_shortcut_transaction = build_lnk_shortcut_transaction_plan


def _header_plan(data: bytes) -> LnkHeaderPlan:
    if len(data) < LNK_HEADER_MIN_SIZE:
        return LnkHeaderPlan(
            status="truncated",
            header_size=None,
            shell_link_class_id=None,
            flags=None,
            file_attributes=None,
            target_file_size=None,
            icon_index=None,
            run_window=None,
            hot_key=None,
            header_range=None,
            blocker_code="truncated_lnk_header",
            evidence_ids=(LNK_HEADER_SOURCE,),
        )
    header_size = _u32(data, 0)
    class_id = data[4:20]
    if class_id != LNK_SHELL_LINK_CLSID:
        return _invalid_header(
            "invalid_signature",
            header_size,
            class_id,
            "unsupported_lnk_signature",
        )
    if header_size < LNK_HEADER_MIN_SIZE:
        return _invalid_header("invalid_size", header_size, class_id, "invalid_lnk_header_size")
    if header_size > len(data):
        return _invalid_header(
            "truncated",
            header_size,
            class_id,
            "truncated_lnk_header_extension",
        )
    return LnkHeaderPlan(
        status="valid",
        header_size=header_size,
        shell_link_class_id=class_id,
        flags=_u32(data, 0x14),
        file_attributes=_u32(data, 0x18),
        target_file_size=_u32(data, 0x34),
        icon_index=_u32(data, 0x38),
        run_window=_u32(data, 0x3C),
        hot_key=_u32(data, 0x40),
        header_range=(0, header_size),
        blocker_code=None,
        evidence_ids=(LNK_HEADER_SOURCE, LNK_MAIN_TABLE_SOURCE),
    )


def _invalid_header(
    status: LnkHeaderStatus,
    header_size: int,
    class_id: bytes,
    blocker_code: LnkEmissionGateCode,
) -> LnkHeaderPlan:
    return LnkHeaderPlan(
        status=status,
        header_size=header_size,
        shell_link_class_id=class_id,
        flags=None,
        file_attributes=None,
        target_file_size=None,
        icon_index=None,
        run_window=None,
        hot_key=None,
        header_range=None,
        blocker_code=blocker_code,
        evidence_ids=(LNK_HEADER_SOURCE,),
    )


def _flag_responsibilities(flags: int) -> tuple[LnkFlagResponsibilityPlan, ...]:
    plans: list[LnkFlagResponsibilityPlan] = []
    for bit, name in LINK_FLAG_NAMES.items():
        plans.append(
            LnkFlagResponsibilityPlan(
                bit=bit,
                name=name,
                present=bool(flags & (1 << bit)),
                responsibility=_flag_responsibility(bit),
                evidence_ids=(LNK_MAIN_TABLE_SOURCE,),
            )
        )
    return tuple(plans)


def _flag_responsibility(bit: int) -> str:
    if bit == 0:
        return "route Target ID List to ItemID"
    if bit == 1:
        return "route LinkInfo subdirectory"
    if 2 <= bit <= 6:
        return "route counted StringData field"
    if bit == 7:
        return "decode counted strings as UTF-16LE"
    return "preserve structural LinkFlags bit"


def _file_attributes_plan(value: int | None) -> LnkFileAttributePlan:
    if value is None:
        return LnkFileAttributePlan(None, (), (LNK_FILE_ATTRIBUTES_SOURCE,))
    return LnkFileAttributePlan(
        raw_value=value,
        active_attributes=tuple(
            name for bit, name in FILE_ATTRIBUTE_NAMES.items() if value & (1 << bit)
        ),
        evidence_ids=(LNK_FILE_ATTRIBUTES_SOURCE, LNK_MAIN_TABLE_SOURCE),
    )


def _timestamp_plans(data: bytes, header_status: LnkHeaderStatus) -> tuple[LnkTimestampPlan, ...]:
    if header_status != "valid":
        return tuple(
            LnkTimestampPlan(name, None, None, False, (LNK_FILE_TIME_SOURCE, LNK_MAIN_TABLE_SOURCE))
            for name in ("CreateDate", "AccessDate", "ModifyDate")
        )
    return (
        _timestamp_plan("CreateDate", _u64(data, 0x1C)),
        _timestamp_plan("AccessDate", _u64(data, 0x24)),
        _timestamp_plan("ModifyDate", _u64(data, 0x2C)),
    )


def _timestamp_plan(name: str, raw: int) -> LnkTimestampPlan:
    unix_seconds = None if raw == 0 else (raw / 10_000_000) - 11_644_473_600
    return LnkTimestampPlan(
        name=name,
        raw_filetime=raw,
        unix_seconds=unix_seconds,
        present=raw != 0,
        evidence_ids=(LNK_FILE_TIME_SOURCE, LNK_MAIN_TABLE_SOURCE),
    )


def _absent_section(kind: LnkSectionKind, source: str) -> LnkSectionPlan:
    return LnkSectionPlan(kind, "absent", None, None, None, 0, b"", None, (source,))


def _target_id_list_plan(data: bytes, offset: int) -> LnkSectionPlan:
    if offset + 2 > len(data):
        return LnkSectionPlan(
            "target_id_list",
            "truncated",
            offset,
            len(data),
            None,
            0,
            b"",
            "missing_target_id_list",
            (LNK_TARGET_ID_LIST_SOURCE,),
        )
    declared_size = _u16(data, offset)
    payload_offset = offset + 2
    end = payload_offset + declared_size
    if end > len(data):
        return LnkSectionPlan(
            "target_id_list",
            "truncated",
            payload_offset,
            len(data),
            declared_size,
            max(0, len(data) - payload_offset),
            data[payload_offset:],
            "truncated_target_id_list",
            (LNK_TARGET_ID_LIST_SOURCE,),
        )
    return LnkSectionPlan(
        "target_id_list",
        "present",
        payload_offset,
        end,
        declared_size,
        declared_size,
        data[payload_offset:end],
        None,
        (LNK_TARGET_ID_LIST_SOURCE, LNK_MAIN_TABLE_SOURCE),
    )


def _link_info_section_plan(data: bytes, offset: int) -> LnkSectionPlan:
    if offset + 4 > len(data):
        return LnkSectionPlan(
            "link_info",
            "truncated",
            offset,
            len(data),
            None,
            0,
            b"",
            "missing_link_information",
            (LNK_LINK_INFO_READ_SOURCE,),
        )
    declared_size = _u32(data, offset)
    if declared_size < 4:
        return LnkSectionPlan(
            "link_info",
            "invalid",
            offset,
            offset + 4,
            declared_size,
            4,
            data[offset : offset + 4],
            "invalid_link_information",
            (LNK_LINK_INFO_READ_SOURCE,),
        )
    end = offset + declared_size
    if end > len(data):
        return LnkSectionPlan(
            "link_info",
            "truncated",
            offset,
            len(data),
            declared_size,
            max(0, len(data) - offset),
            data[offset:],
            "truncated_link_information",
            (LNK_LINK_INFO_READ_SOURCE,),
        )
    return LnkSectionPlan(
        "link_info",
        "present",
        offset,
        end,
        declared_size,
        declared_size,
        data[offset:end],
        None,
        (LNK_LINK_INFO_READ_SOURCE, LNK_LINK_INFO_PROCESS_SOURCE),
    )


def _absent_link_info() -> LnkLinkInfoPlan:
    return LnkLinkInfoPlan(False, "absent", None, None, (), None, (LNK_LINK_INFO_PROCESS_SOURCE,))


def _link_info_plan(section: LnkSectionPlan) -> LnkLinkInfoPlan:
    if section.status != "present":
        return LnkLinkInfoPlan(
            section.status != "absent",
            section.status,
            None,
            None,
            (),
            section.blocker_code,
            section.evidence_ids,
        )
    data = section.payload
    if len(data) < 0x24:
        return LnkLinkInfoPlan(
            True,
            "invalid",
            None,
            None,
            (),
            "link_info_too_short",
            (LNK_LINK_INFO_PROCESS_SOURCE,),
        )
    header_size = _u32(data, 4)
    link_info_flags = _u32(data, 8)
    routes = [
        LnkLinkInfoRoutePlan(
            "VolumeID",
            bool(link_info_flags & 0x01),
            _offset_if_in_range(data, 0x0C),
            (LNK_LINK_INFO_PROCESS_SOURCE,),
        ),
        LnkLinkInfoRoutePlan(
            "LocalBasePath",
            bool(link_info_flags & 0x01),
            _offset_if_in_range(data, 0x1C if header_size >= 0x24 else 0x10),
            (LNK_LINK_INFO_PROCESS_SOURCE,),
        ),
        LnkLinkInfoRoutePlan(
            "CommonNetworkRelLink",
            bool(link_info_flags & 0x02),
            _offset_if_in_range(data, 0x14),
            (LNK_LINK_INFO_PROCESS_SOURCE,),
        ),
        LnkLinkInfoRoutePlan(
            "CommonPathSuffix",
            True,
            _offset_if_in_range(data, 0x18),
            (LNK_LINK_INFO_PROCESS_SOURCE,),
        ),
    ]
    if header_size >= 0x24:
        routes.append(
            LnkLinkInfoRoutePlan(
                "CommonPathSuffixUnicode",
                True,
                _offset_if_in_range(data, 0x20),
                (LNK_LINK_INFO_PROCESS_SOURCE,),
            )
        )
    blocker = _link_info_offset_blocker(data, link_info_flags)
    return LnkLinkInfoPlan(
        True,
        "present" if blocker is None else "invalid",
        header_size,
        link_info_flags,
        tuple(routes),
        blocker,
        (LNK_LINK_INFO_PROCESS_SOURCE,),
    )


def _link_info_offset_blocker(data: bytes, link_info_flags: int) -> LnkEmissionGateCode | None:
    if not link_info_flags & 0x02:
        return None
    off = _u32(data, 0x14)
    if off == 0 or off + 0x14 > len(data):
        return None
    size = _u32(data, off)
    if off + size > len(data):
        return "link_info_network_offset_exceeds_block"
    return None


def _offset_if_in_range(data: bytes, field_offset: int) -> int | None:
    if field_offset + 4 > len(data):
        return None
    offset = _u32(data, field_offset)
    return offset if 0 < offset < len(data) else None


def _string_data_plans(
    data: bytes,
    flags: int,
    offset: int,
) -> tuple[tuple[LnkStringDataPlan, ...], int, tuple[LnkOutputEmissionGate, ...]]:
    plans: list[LnkStringDataPlan] = []
    gates: list[LnkOutputEmissionGate] = []
    current_offset = offset
    is_unicode = bool(flags & 0x80)
    for index, name, mask in STRING_ROUTES:
        if not flags & mask:
            plans.append(
                LnkStringDataPlan(
                    name,
                    mask,
                    "absent",
                    None,
                    None,
                    None,
                    0,
                    is_unicode,
                    False,
                    None,
                    (LNK_STRING_DATA_SOURCE,),
                )
            )
            continue
        plan = _one_string_plan(data, current_offset, index, name, mask, is_unicode)
        plans.append(plan)
        if plan.blocker_code is not None:
            gates.append(_gate(plan.blocker_code, plan.evidence_ids))
            current_offset = len(data)
            break
        current_offset = plan.end_offset or current_offset
    return tuple(plans), current_offset, tuple(gates)


def _one_string_plan(
    data: bytes,
    offset: int,
    index: int,
    name: LnkStringName,
    mask: int,
    is_unicode: bool,
) -> LnkStringDataPlan:
    if offset + 2 > len(data):
        return LnkStringDataPlan(
            name,
            mask,
            "invalid",
            offset,
            len(data),
            None,
            0,
            is_unicode,
            False,
            "invalid_string_data",
            (LNK_STRING_DATA_SOURCE,),
        )
    declared_chars = _u16(data, offset)
    payload_offset = offset + 2
    if declared_chars == 0:
        return LnkStringDataPlan(
            name,
            mask,
            "empty",
            payload_offset,
            payload_offset,
            declared_chars,
            0,
            is_unicode,
            False,
            None,
            (LNK_STRING_DATA_SOURCE,),
        )
    effective_chars = declared_chars
    limited = False
    if index != 3 and effective_chars >= 260:
        limited = True
        effective_chars = min(effective_chars, 260)
    consumed = effective_chars * (2 if is_unicode else 1)
    end = payload_offset + consumed
    if end > len(data):
        return LnkStringDataPlan(
            name,
            mask,
            "truncated",
            payload_offset,
            len(data),
            declared_chars,
            max(0, len(data) - payload_offset),
            is_unicode,
            limited,
            "truncated_string_data",
            (LNK_STRING_DATA_SOURCE,),
        )
    return LnkStringDataPlan(
        name,
        mask,
        "present",
        payload_offset,
        end,
        declared_chars,
        consumed - ((2 if is_unicode else 1) if limited else 0),
        is_unicode,
        limited,
        None,
        (LNK_STRING_DATA_SOURCE,),
    )


def _extra_data_plans(
    data: bytes,
    offset: int,
) -> tuple[
    tuple[LnkExtraDataBlockPlan, ...],
    LnkExtraDataTerminatorPlan,
    LnkOverlayPlan,
    tuple[LnkOutputEmissionGate, ...],
]:
    blocks: list[LnkExtraDataBlockPlan] = []
    gates: list[LnkOutputEmissionGate] = []
    current_offset = offset
    terminator = LnkExtraDataTerminatorPlan(None, None, (LNK_EXTRA_DATA_SOURCE,))
    while current_offset + 4 <= len(data):
        declared_size = _u32(data, current_offset)
        if declared_size < 4:
            terminator = LnkExtraDataTerminatorPlan(
                current_offset,
                declared_size,
                (LNK_EXTRA_DATA_SOURCE,),
            )
            current_offset += 4
            break
        end = current_offset + declared_size
        if end > len(data):
            block = LnkExtraDataBlockPlan(
                len(blocks),
                "truncated",
                current_offset,
                len(data),
                declared_size,
                None,
                "UnknownData",
                data[current_offset:],
                True,
                "truncated_extra_data",
                (LNK_EXTRA_DATA_SOURCE,),
            )
            blocks.append(block)
            gates.append(_gate("truncated_extra_data", block.evidence_ids))
            current_offset = len(data)
            break
        if declared_size <= 8:
            blocks.append(
                LnkExtraDataBlockPlan(
                    len(blocks),
                    "skipped",
                    current_offset,
                    end,
                    declared_size,
                    None,
                    "UnknownData",
                    data[current_offset:end],
                    True,
                    None,
                    (LNK_EXTRA_DATA_SOURCE, LNK_UNKNOWN_DATA_SOURCE),
                )
            )
            current_offset = end
            continue
        signature = _u32(data, current_offset + 4)
        route = EXTRA_DATA_ROUTES.get(signature, "UnknownData")
        evidence_ids = _extra_data_sources(route)
        blocks.append(
            LnkExtraDataBlockPlan(
                len(blocks),
                "present",
                current_offset,
                end,
                declared_size,
                signature,
                route,
                data[current_offset:end],
                route == "UnknownData",
                None,
                evidence_ids,
            )
        )
        current_offset = end
    overlay_bytes = data[current_offset:]
    overlay = LnkOverlayPlan(
        current_offset,
        len(overlay_bytes),
        any(byte != 0 for byte in overlay_bytes),
        (LNK_OVERLAY_SOURCE,),
    )
    return tuple(blocks), terminator, overlay, tuple(gates)


def _extra_data_sources(route: LnkExtraDataRoute) -> tuple[str, ...]:
    if route == "ConsoleData":
        return (LNK_EXTRA_DATA_SOURCE, LNK_CONSOLE_DATA_SOURCE)
    if route == "TrackerData":
        return (LNK_EXTRA_DATA_SOURCE, LNK_TRACKER_DATA_SOURCE)
    if route == "ConsoleFEData":
        return (LNK_EXTRA_DATA_SOURCE, LNK_CONSOLE_FE_DATA_SOURCE)
    if route == "EnvVarData":
        return (LNK_EXTRA_DATA_SOURCE, LNK_ENV_VAR_DATA_SOURCE)
    if route == "UnknownData":
        return (LNK_EXTRA_DATA_SOURCE, LNK_UNKNOWN_DATA_SOURCE)
    return (LNK_EXTRA_DATA_SOURCE, LNK_UNKNOWN_DATA_SOURCE)


def _block_responsibilities(
    blocks: tuple[LnkExtraDataBlockPlan, ...],
) -> tuple[LnkBlockResponsibilityPlan, ...]:
    plans: list[LnkBlockResponsibilityPlan] = []
    for block in blocks:
        if block.route == "ConsoleData":
            plans.append(
                LnkBlockResponsibilityPlan(
                    "console",
                    block.index,
                    (
                        "FillAttributes",
                        "PopupFillAttributes",
                        "ScreenBufferSize",
                        "WindowSize",
                        "FontName",
                        "QuickEdit",
                        "HistoryBufferSize",
                    ),
                    (LNK_CONSOLE_DATA_SOURCE,),
                )
            )
        elif block.route == "TrackerData":
            plans.append(
                LnkBlockResponsibilityPlan(
                    "tracker",
                    block.index,
                    ("MachineID",),
                    (LNK_TRACKER_DATA_SOURCE,),
                )
            )
        elif block.route == "ConsoleFEData":
            plans.append(
                LnkBlockResponsibilityPlan(
                    "console_fe",
                    block.index,
                    ("CodePage",),
                    (LNK_CONSOLE_FE_DATA_SOURCE,),
                )
            )
        elif block.route == "EnvVarData":
            plans.append(
                LnkBlockResponsibilityPlan(
                    "environment",
                    block.index,
                    ("EnvironmentTarget", "EnvironmentTargetUnicode"),
                    (LNK_ENV_VAR_DATA_SOURCE,),
                )
            )
    return tuple(plans)


def _gate(
    code: LnkEmissionGateCode,
    sources: tuple[str, ...],
) -> LnkOutputEmissionGate:
    return LnkOutputEmissionGate(code, _gate_reason(code), sources)


def _gate_reason(code: LnkEmissionGateCode) -> str:
    reasons: dict[LnkEmissionGateCode, str] = {
        "non_mutating_plan_requires_explicit_emission": (
            "Emission must be explicitly allowed for this preserve-only plan."
        ),
        "lnk_rewrite_not_supported": (
            "LNK mutation is not modeled by the ported ExifTool reader behavior."
        ),
        "truncated_lnk_header": (
            "The input is shorter than the 0x4c Shell Link header read by ProcessLNK."
        ),
        "unsupported_lnk_signature": (
            "The Shell Link class identifier does not match the LNK.pm header gate."
        ),
        "invalid_lnk_header_size": (
            "The header size is smaller than the 0x4c minimum accepted by ProcessLNK."
        ),
        "truncated_lnk_header_extension": (
            "The declared Shell Link header extension exceeds the input."
        ),
        "missing_target_id_list": (
            "The IDList flag is set but the uint16 target list size is missing."
        ),
        "truncated_target_id_list": (
            "The IDList flag is set but the declared target list bytes are truncated."
        ),
        "missing_link_information": (
            "The LinkInfo flag is set but the uint32 LinkInfo size is missing."
        ),
        "invalid_link_information": "The LinkInfo size is smaller than the four-byte size field.",
        "truncated_link_information": "The declared LinkInfo block exceeds the input.",
        "link_info_too_short": "ProcessLinkInfo requires at least 0x24 bytes.",
        "link_info_network_offset_exceeds_block": (
            "The CommonNetworkRelLink size exceeds its LinkInfo block."
        ),
        "invalid_string_data": "A flag-gated counted string is missing its uint16 count.",
        "truncated_string_data": "A flag-gated counted string payload is truncated.",
        "truncated_extra_data": "A declared ExtraData block exceeds the input.",
    }
    return reasons[code]


def _unique_gates(gates: Iterable[LnkOutputEmissionGate]) -> tuple[LnkOutputEmissionGate, ...]:
    unique: list[LnkOutputEmissionGate] = []
    seen: set[LnkEmissionGateCode] = set()
    for gate in gates:
        if gate.code in seen:
            continue
        unique.append(gate)
        seen.add(gate.code)
    return tuple(unique)


def _has_structural_gate(gates: tuple[LnkOutputEmissionGate, ...]) -> bool:
    return any(gate.code in STRUCTURAL_GATE_CODES for gate in gates)


def _unique_sources(sources: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source in seen:
            continue
        unique.append(source)
        seen.add(source)
    return tuple(unique)


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def _u64(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 8], "little")
