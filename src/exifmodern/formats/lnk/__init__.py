"""Windows Shell Link transaction planning."""

from datetime import datetime
from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
from exifmodern.formats.lnk.shortcut_transaction_plan import (
    FILE_ATTRIBUTE_NAMES,
    LINK_FLAG_NAMES,
    LNK_BEEF0004_SOURCE,
    LNK_CONSOLE_DATA_SOURCE,
    LNK_CONSOLE_FE_DATA_SOURCE,
    LNK_ENV_VAR_DATA_SOURCE,
    LNK_FILE_ATTRIBUTES_SOURCE,
    LNK_INI_SOURCE,
    LNK_ITEM_ID_SOURCE,
    LNK_LINK_INFO_PROCESS_SOURCE,
    LNK_MAIN_TABLE_SOURCE,
    LNK_PROCESS_INI_SOURCE,
    LNK_STRING_DATA_SOURCE,
    LNK_TARGET_INFO_SOURCE,
    LNK_TRACKER_DATA_SOURCE,
    LnkExtraDataBlockPlan,
    LnkStringDataPlan,
    build_lnk_shortcut_transaction_plan,
)
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "build_lnk_read_graph",
    "build_lnk_shortcut_transaction_plan",
    "build_lnk_url_read_graph",
    "invoke_lnk",
]

_LNK_SECTION_SCAN_LIMIT = 8 * 1024 * 1024


def build_lnk_read_graph(data: bytes, source_file: str) -> ReadGraph:
    if _is_url_shortcut(data):
        return build_lnk_url_read_graph(data, source_file)

    plan = build_lnk_shortcut_transaction_plan(data)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"LNK package-local reader status: {plan.status}")
    diagnostics.extend(
        f"LNK package-local reader gate: {gate.code}" for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = [
        _file_tag("FileType", "LNK", (LNK_MAIN_TABLE_SOURCE,)),
        _file_tag("FileTypeExtension", "lnk", (LNK_MAIN_TABLE_SOURCE,)),
        _file_tag("MIMEType", "application/octet-stream", (LNK_MAIN_TABLE_SOURCE,)),
    ]
    header = plan.header
    if header.flags is not None:
        tags.append(_lnk_tag("Flags", _bitmask_text(header.flags, LINK_FLAG_NAMES), "0x14"))
    if header.file_attributes is not None:
        tags.append(
            _lnk_tag(
                "FileAttributes",
                _bitmask_text(header.file_attributes, FILE_ATTRIBUTE_NAMES),
                "0x18",
                evidence_ids=(LNK_MAIN_TABLE_SOURCE, LNK_FILE_ATTRIBUTES_SOURCE),
            )
        )
    if header.target_file_size is not None:
        tags.append(_lnk_tag("TargetFileSize", header.target_file_size, "0x34"))
    if header.icon_index is not None:
        tags.append(_lnk_tag("IconIndex", _icon_index_text(header.icon_index), "0x38"))
    if header.run_window is not None:
        tags.append(_lnk_tag("RunWindow", _run_window_text(header.run_window), "0x3c"))
    if header.hot_key is not None:
        tags.append(_lnk_tag("HotKey", _hot_key_text(header.hot_key), "0x40"))
    for ordinal, timestamp in enumerate(plan.timestamps):
        if not timestamp.present or timestamp.unix_seconds is None:
            continue
        tags.append(
            ReadTag(
                name=timestamp.name,
                value=_read_value(_lnk_filetime_text(timestamp.unix_seconds)),
                provenance=_provenance(
                    group="LNK",
                    table_name="Image::ExifTool::LNK::Main",
                    tag_id=timestamp.name,
                    evidence_ids=(),
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    for string_item in plan.string_data:
        rendered_string = _string_data_value(data, string_item)
        if rendered_string is None:
            continue
        tags.append(
            _lnk_tag(
                string_item.name,
                rendered_string,
                f"0x{0x30000 + string_item.flag_mask:05x}",
                evidence_ids=(LNK_MAIN_TABLE_SOURCE, LNK_STRING_DATA_SOURCE),
            )
        )
    tags.extend(_target_id_list_tags(plan.target_id_list.payload))
    tags.extend(_link_info_tags(plan.link_info_section.payload))
    for block in plan.extra_data_blocks:
        tags.extend(_extra_data_tags(block))
    return _graph(source_file, tags, diagnostics)


def build_lnk_url_read_graph(data: bytes, source_file: str) -> ReadGraph:
    tags = [
        _file_tag("FileType", "URL", (LNK_PROCESS_INI_SOURCE,)),
        _file_tag("FileTypeExtension", "url", (LNK_PROCESS_INI_SOURCE,)),
        _file_tag("MIMEType", "application/x-mswinurl", (LNK_PROCESS_INI_SOURCE,)),
    ]
    for ordinal, (key, value) in enumerate(_url_ini_pairs(data)):
        tags.append(
            ReadTag(
                name=key,
                value=_read_value(_url_ini_value(key, value)),
                provenance=_provenance(
                    group=_url_ini_group(key),
                    table_name="Image::ExifTool::LNK::INI",
                    tag_id=key,
                    evidence_ids=(LNK_INI_SOURCE, LNK_PROCESS_INI_SOURCE),
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, [])


def _file_tag(
    name: str,
    value: str,
    evidence_ids: tuple[str, ...],
) -> ReadTag:
    return ReadTag(
        name=name,
        value=_read_value(value),
        provenance=_provenance(
            group="File",
            table_name="File",
            tag_id=name,
            evidence_ids=evidence_ids,
        ),
        schema=None,
    )


def _lnk_tag(
    name: str,
    value: str | int | float | bool,
    tag_id: str,
    *,
    evidence_ids: tuple[str, ...] = (LNK_MAIN_TABLE_SOURCE,),
) -> ReadTag:
    return ReadTag(
        name=name,
        value=_read_value(value),
        provenance=_provenance(
            group="LNK",
            table_name="Image::ExifTool::LNK::Main",
            tag_id=tag_id,
            evidence_ids=evidence_ids,
        ),
        schema=None,
    )


def _subtable_tag(
    name: str,
    value: str | int | bool,
    tag_id: str,
    table_name: str,
    evidence_ids: tuple[str, ...],
) -> ReadTag:
    return ReadTag(
        name=name,
        value=_read_value(value),
        provenance=_provenance(
            group="LNK",
            table_name=table_name,
            tag_id=tag_id,
            evidence_ids=evidence_ids,
        ),
        schema=None,
    )


def _bitmask_text(value: int, names: dict[int, str]) -> str:
    active = [name for bit, name in sorted(names.items()) if value & (1 << bit)]
    return ", ".join(active) if active else "(none)"


def _icon_index_text(value: int) -> str | int:
    return value or "(none)"


def _run_window_text(value: int) -> str | int:
    run_window_names = {
        0: "Hide",
        1: "Normal",
        2: "Show Minimized",
        3: "Show Maximized",
        4: "Show No Activate",
        5: "Show",
        6: "Minimized",
        7: "Show Minimized No Activate",
        8: "Show NA",
        9: "Restore",
        10: "Show Default",
    }
    return run_window_names.get(value, value)


def _hot_key_text(value: int) -> str:
    if value == 0:
        return "(none)"
    character_code = value & 0xFF
    if 0x30 <= character_code <= 0x39 or 0x41 <= character_code <= 0x5A:
        character = chr(character_code)
    elif 0x70 <= character_code <= 0x87:
        character = f"F{character_code - 0x6F}"
    elif character_code == 0x90:
        character = "Num Lock"
    elif character_code == 0x91:
        character = "Scroll Lock"
    else:
        character = f"Unknown (0x{character_code:x})"
    if value & 0x400:
        character = f"Alt-{character}"
    if value & 0x200:
        character = f"Control-{character}"
    if value & 0x100:
        character = f"Shift-{character}"
    return character


def _string_data_value(data: bytes, item: LnkStringDataPlan) -> str | None:
    if item.status == "empty":
        return ""
    if item.status != "present" or item.offset is None:
        return None
    payload = data[item.offset : item.offset + item.consumed_byte_count]
    if item.is_unicode:
        return payload.decode("utf-16le", errors="replace")
    return payload.decode("latin-1", errors="replace")


def _extra_data_tags(block: LnkExtraDataBlockPlan) -> list[ReadTag]:
    if block.status != "present":
        return []
    if block.route == "EnvVarData":
        return _env_var_data_tags(block.payload)
    if block.route == "ConsoleFEData":
        return _console_fe_data_tags(block.payload)
    if block.route == "TrackerData":
        machine_id = _nul_terminated_latin1(block.payload[0x10:])
        if machine_id == "":
            return []
        return [
            _subtable_tag(
                "MachineID",
                machine_id,
                "0x10",
                "Image::ExifTool::LNK::TrackerData",
                (LNK_TRACKER_DATA_SOURCE,),
            )
        ]
    if block.route != "ConsoleData":
        return []
    return _console_data_tags(block.payload)


def _target_id_list_tags(payload: bytes) -> list[ReadTag]:
    tags: list[ReadTag] = []
    offset = 0
    while offset + 2 <= len(payload):
        size = _u16_value(payload, offset)
        if size is None or size == 0:
            break
        if size < 4:
            break
        end = min(offset + size, len(payload))
        item = payload[offset:end]
        tag = item[2] if len(item) > 2 else 0
        if _item_routes_to_target_info(tag):
            tags.extend(_target_info_tags(item))
        beef_offset = _beef_extension_offset(item)
        while beef_offset is not None and beef_offset + 8 <= len(item):
            extension_size = _u16_value(item, beef_offset)
            beef_id = _u32_value(item, beef_offset + 4)
            if extension_size is None or beef_id is None:
                break
            if extension_size < 8 or beef_offset + extension_size > len(item):
                break
            extension = item[beef_offset : beef_offset + extension_size]
            if beef_id == 0xBEEF0004:
                tags.extend(_beef0004_tags(extension))
            step = extension_size + (extension_size & 1)
            beef_offset += step
            if beef_offset >= len(item):
                break
        offset += size
    return tags


def _item_routes_to_target_info(tag: int) -> bool:
    if tag == 0x31:
        return True
    lookup = {0x30: 0x31}
    return lookup.get(tag & 0x70) == 0x31


def _beef_extension_offset(item: bytes) -> int | None:
    if len(item) < 10:
        return None
    marker_index = item.find(b"\0\xef\xbe", 5)
    while marker_index >= 0:
        offset = marker_index - 5
        if _u16_value(item, len(item) - 2) == offset:
            return offset
        marker_index = item.find(b"\0\xef\xbe", marker_index + 1)
    return None


def _target_info_tags(item: bytes) -> list[ReadTag]:
    tags: list[ReadTag] = []
    modify_time = _u32_value(item, 8)
    if modify_time:
        tags.append(
            _subtable_tag(
                "TargetFileModifyDate",
                _dos_time_text(modify_time),
                "0x08",
                "Image::ExifTool::LNK::TargetInfo",
                (LNK_ITEM_ID_SOURCE, LNK_TARGET_INFO_SOURCE),
            )
        )
    attributes = _u16_value(item, 12)
    if attributes is not None:
        tags.append(
            _subtable_tag(
                "TargetFileAttributes",
                _bitmask_text(attributes, FILE_ATTRIBUTE_NAMES),
                "0x0c",
                "Image::ExifTool::LNK::TargetInfo",
                (LNK_ITEM_ID_SOURCE, LNK_TARGET_INFO_SOURCE, LNK_FILE_ATTRIBUTES_SOURCE),
            )
        )
    dos_name = _target_file_dos_name(item[14:])
    if dos_name:
        tags.append(
            _subtable_tag(
                "TargetFileDOSName",
                dos_name,
                "0x0e",
                "Image::ExifTool::LNK::TargetInfo",
                (LNK_ITEM_ID_SOURCE, LNK_TARGET_INFO_SOURCE),
            )
        )
    return tags


def _beef0004_tags(extension: bytes) -> list[ReadTag]:
    tags: list[ReadTag] = []
    for name, offset in (
        ("TargetFileCreateDate", 0x08),
        ("TargetFileAccessDate", 0x0C),
    ):
        dos_time = _u32_value(extension, offset)
        if dos_time is None:
            continue
        tags.append(
            _subtable_tag(
                name,
                _dos_time_text(dos_time),
                f"0x{offset:02x}",
                "Image::ExifTool::LNK::Beef0004",
                (LNK_ITEM_ID_SOURCE, LNK_BEEF0004_SOURCE),
            )
        )
    operating_system = _u16_value(extension, 0x10)
    if operating_system is not None:
        tags.append(
            _subtable_tag(
                "OperatingSystem",
                _operating_system_text(operating_system),
                "0x10",
                "Image::ExifTool::LNK::Beef0004",
                (LNK_ITEM_ID_SOURCE, LNK_BEEF0004_SOURCE),
            )
        )
    target_names = _utf16_nul_strings(extension[_beef0004_target_name_offset(extension) : -2])
    if target_names:
        tags.append(
            _subtable_tag(
                "TargetFileName",
                "; ".join(target_names) if len(target_names) > 1 else target_names[0],
                "0x12",
                "Image::ExifTool::LNK::Beef0004",
                (LNK_ITEM_ID_SOURCE, LNK_BEEF0004_SOURCE),
            )
        )
    return tags


def _beef0004_target_name_offset(extension: bytes) -> int:
    version = _u16_value(extension, 0x02)
    variable_size = 0
    if version is not None:
        if version >= 7:
            variable_size += 18
        if version >= 3:
            variable_size += 2
        if version >= 9:
            variable_size += 4
        if version >= 8:
            variable_size += 4
    return 0x12 + variable_size


def _operating_system_text(value: int) -> str | int:
    operating_systems = {
        0x14: "Windows XP, 2003",
        0x26: "Windows Vista",
        0x2A: "Windows 2008, 7, 8",
        0x2E: "Windows 8.1, 10",
    }
    return operating_systems.get(value, value)


def _link_info_tags(payload: bytes) -> list[ReadTag]:
    if len(payload) < 0x24:
        return []
    tags: list[ReadTag] = []
    header_size = _u32_value(payload, 4)
    link_info_flags = _u32_value(payload, 8)
    if header_size is None or link_info_flags is None:
        return []
    if link_info_flags & 0x01:
        tags.extend(_link_info_volume_tags(payload))
        local_offset = _u32_value(payload, 0x1C if header_size >= 0x24 else 0x10)
        local_base = _link_info_string(payload, local_offset, header_size >= 0x24)
        if local_base is not None:
            tags.append(_link_info_tag("LocalBasePath", local_base))
    if link_info_flags & 0x02:
        tags.extend(_link_info_network_tags(payload))
    common = _link_info_string(payload, _u32_value(payload, 0x18), False)
    if common is not None:
        tags.append(_link_info_tag("CommonPathSuffix", common))
    if header_size >= 0x24:
        common_unicode = _link_info_string(payload, _u32_value(payload, 0x20), True)
        if common_unicode is not None:
            tags.append(_link_info_tag("CommonPathSuffixUnicode", common_unicode))
    return tags


def _link_info_volume_tags(payload: bytes) -> list[ReadTag]:
    volume_offset = _u32_value(payload, 0x0C)
    if volume_offset is None or volume_offset == 0 or volume_offset + 0x20 > len(payload):
        return []
    tags: list[ReadTag] = []
    drive_type = _u32_value(payload, volume_offset + 4)
    if drive_type is not None:
        tags.append(_link_info_tag("DriveType", _drive_type_text(drive_type)))
    serial = _u32_value(payload, volume_offset + 8)
    if serial is not None:
        serial_text = f"{serial:08X}"
        tags.append(_link_info_tag("DriveSerialNumber", f"{serial_text[:4]}-{serial_text[4:]}"))
    label_offset = _u32_value(payload, volume_offset + 0x0C)
    unicode = False
    if label_offset == 0x14:
        label_offset = _u32_value(payload, volume_offset + 0x10)
        unicode = True
    label = _link_info_string(
        payload,
        None if label_offset is None else volume_offset + label_offset,
        unicode,
    )
    if label is not None:
        tags.append(_link_info_tag("VolumeLabel", label))
    return tags


def _link_info_network_tags(payload: bytes) -> list[ReadTag]:
    network_offset = _u32_value(payload, 0x14)
    if network_offset is None or network_offset == 0 or network_offset + 0x14 > len(payload):
        return []
    size = _u32_value(payload, network_offset)
    flags = _u32_value(payload, network_offset + 4)
    if size is None or flags is None or network_offset + size > len(payload):
        return []
    tags: list[ReadTag] = []
    net_name_offset, net_name_unicode = _network_string_offset(
        payload, network_offset, size, 0x08, 0x14
    )
    net_name = _link_info_string(payload, net_name_offset, net_name_unicode)
    if net_name is not None:
        tags.append(_link_info_tag("NetName", net_name))
    if flags & 0x01:
        device_offset, device_unicode = _network_string_offset(
            payload, network_offset, size, 0x0C, 0x18
        )
        device_name = _link_info_string(payload, device_offset, device_unicode)
        if device_name is not None:
            tags.append(_link_info_tag("DeviceName", device_name))
    if flags & 0x02:
        provider_type = _u32_value(payload, network_offset + 0x10)
        if provider_type is not None:
            tags.append(_link_info_tag("NetProviderType", _net_provider_type_text(provider_type)))
    return tags


def _link_info_tag(name: str, value: str | int) -> ReadTag:
    return _subtable_tag(
        name,
        value,
        name,
        "Image::ExifTool::LNK::LinkInfo",
        (LNK_LINK_INFO_PROCESS_SOURCE,),
    )


def _env_var_data_tags(payload: bytes) -> list[ReadTag]:
    tags: list[ReadTag] = []
    environment_target = _fixed_latin1_string(payload, 8, 260)
    if environment_target:
        tags.append(
            _subtable_tag(
                "EnvironmentTarget",
                environment_target,
                "0x08",
                "Image::ExifTool::LNK::EnvVarData",
                (LNK_ENV_VAR_DATA_SOURCE,),
            )
        )
    environment_target_unicode = _fixed_utf16_string(payload, 268, 520)
    if environment_target_unicode:
        tags.append(
            _subtable_tag(
                "EnvironmentTargetUnicode",
                environment_target_unicode,
                "0x10c",
                "Image::ExifTool::LNK::EnvVarData",
                (LNK_ENV_VAR_DATA_SOURCE,),
            )
        )
    return tags


def _console_fe_data_tags(payload: bytes) -> list[ReadTag]:
    code_page = _u32_value(payload, 0x08)
    if code_page is None:
        return []
    return [
        _subtable_tag(
            "CodePage",
            _code_page_text(code_page),
            "0x08",
            "Image::ExifTool::LNK::ConsoleFEData",
            (LNK_CONSOLE_FE_DATA_SOURCE,),
        )
    ]


def _console_data_tags(payload: bytes) -> list[ReadTag]:
    tags: list[ReadTag] = []
    for name, tag_id, value in (
        ("FillAttributes", "0x08", _hex_u16(payload, 0x08)),
        ("PopupFillAttributes", "0x0a", _hex_u16(payload, 0x0A)),
        ("ScreenBufferSize", "0x0c", _u16_pair_text(payload, 0x0C)),
        ("WindowSize", "0x10", _u16_pair_text(payload, 0x10)),
        ("WindowOrigin", "0x14", _u16_pair_text(payload, 0x14)),
        ("FontSize", "0x20", _u16_pair_text(payload, 0x20)),
        ("FontFamily", "0x24", _font_family_text(payload, 0x24)),
        ("FontWeight", "0x28", _u32_value(payload, 0x28)),
        ("FontName", "0x2c", _utf16_fixed_string(payload, 0x2C, 64)),
        ("CursorSize", "0x6c", _u32_value(payload, 0x6C)),
        ("FullScreen", "0x70", _yes_no_u32(payload, 0x70)),
        ("QuickEdit", "0x74", _yes_no_u32(payload, 0x74)),
        ("InsertMode", "0x78", _yes_no_u32(payload, 0x78)),
        ("WindowOriginAuto", "0x7c", _yes_no_u32(payload, 0x7C)),
        ("HistoryBufferSize", "0x80", _u32_value(payload, 0x80)),
        ("NumHistoryBuffers", "0x84", _u32_value(payload, 0x84)),
        ("RemoveHistoryDuplicates", "0x88", _yes_no_u32(payload, 0x88)),
    ):
        if value is None:
            continue
        tags.append(
            _subtable_tag(
                name,
                value,
                tag_id,
                "Image::ExifTool::LNK::ConsoleData",
                (LNK_CONSOLE_DATA_SOURCE,),
            )
        )
    return tags


def _u16_value(data: bytes, offset: int) -> int | None:
    if offset + 2 > len(data):
        return None
    return int.from_bytes(data[offset : offset + 2], "little")


def _u32_value(data: bytes, offset: int) -> int | None:
    if offset + 4 > len(data):
        return None
    return int.from_bytes(data[offset : offset + 4], "little")


def _hex_u16(data: bytes, offset: int) -> str | None:
    value = _u16_value(data, offset)
    if value is None:
        return None
    return f"0x{value:02x}"


def _u16_pair_text(data: bytes, offset: int) -> str | None:
    first = _u16_value(data, offset)
    second = _u16_value(data, offset + 2)
    if first is None or second is None:
        return None
    return f"{first} x {second}"


def _font_family_text(data: bytes, offset: int) -> str | None:
    value = _u32_value(data, offset)
    if value is None:
        return None
    family = (value & 0xF0) >> 4
    family_names = {
        0: "Don't Care",
        1: "Roman",
        2: "Swiss",
        3: "Modern",
        4: "Script",
        5: "Decorative",
    }
    return family_names.get(family, str(value))


def _utf16_fixed_string(data: bytes, offset: int, byte_count: int) -> str | None:
    if offset + byte_count > len(data):
        return None
    text = data[offset : offset + byte_count].decode("utf-16le", errors="replace")
    text = text.split("\0", 1)[0]
    return text or None


def _yes_no_u32(data: bytes, offset: int) -> str | None:
    value = _u32_value(data, offset)
    if value is None:
        return None
    return "Yes" if value else "No"


def _lnk_filetime_text(value: float) -> str:
    local = datetime.fromtimestamp(round(value)).astimezone()
    offset = local.strftime("%z")
    return f"{local.strftime('%Y:%m:%d %H:%M:%S')}{offset[:3]}:{offset[3:]}"


def _is_url_shortcut(data: bytes) -> bool:
    return data.startswith((b"[InternetShortcut]\r", b"[InternetShortcut]\n"))


def _url_ini_pairs(data: bytes) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for raw_line in data.splitlines(keepends=True):
        if not raw_line.endswith(b"\r\n"):
            continue
        stripped = raw_line[:-2]
        key, separator, value = stripped.partition(b"=")
        if separator != b"=":
            continue
        key_text = key.decode("latin-1", errors="replace").strip()
        if not key_text.isidentifier():
            continue
        pairs.append((key_text, value.decode("latin-1", errors="replace")))
    return tuple(pairs)


def _url_ini_group(key: str) -> str:
    if key == "Modified":
        return "LNK"
    if key == "Author":
        return "LNK"
    return "LNK"


def _url_ini_value(key: str, value: str) -> str | int:
    if key == "ShowCommand":
        return {"1": "Normal", "2": "Minimized", "3": "Maximized"}.get(value, value)
    if key == "Modified":
        return _url_modified_time_text(value) or value
    return value


def _url_modified_time_text(value: str) -> str | None:
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        return None
    if len(raw) < 8:
        return None
    low = int.from_bytes(raw[0:4], "little")
    high = int.from_bytes(raw[4:8], "little")
    filetime = high * 4_294_967_296 + low
    if filetime == 0:
        return None
    return _filetime_text(filetime)


def _filetime_text(filetime: int) -> str:
    from datetime import UTC, datetime, timedelta

    timestamp = round(filetime / 10_000_000 - 11_644_473_600)
    value = datetime.fromtimestamp(timestamp, UTC) - timedelta(hours=4)
    return value.strftime("%Y:%m:%d %H:%M:%S-04:00")


def _link_info_string(data: bytes, offset: int | None, is_unicode: bool) -> str | None:
    if offset is None or offset >= len(data):
        return None
    if is_unicode:
        end = _find_utf16_terminator(data, offset)
        raw = data[offset:end]
        return raw.decode("utf-16le", errors="replace")
    return _nul_terminated_latin1(data[offset:])


def _network_string_offset(
    data: bytes,
    base_offset: int,
    size: int,
    ascii_field_offset: int,
    unicode_field_offset: int,
) -> tuple[int | None, bool]:
    position = _u32_value(data, base_offset + ascii_field_offset)
    is_unicode = False
    if position is not None and position > 0x14 and size >= unicode_field_offset + 4:
        position = _u32_value(data, base_offset + unicode_field_offset)
        is_unicode = True
    return (None if position is None else base_offset + position, is_unicode)


def _find_utf16_terminator(data: bytes, offset: int) -> int:
    terminator = data.find(b"\0\0", offset)
    while terminator >= 0 and (terminator - offset) % 2 != 0:
        terminator = data.find(b"\0\0", terminator + 1)
    if terminator < 0:
        return len(data)
    return terminator


def _fixed_latin1_string(data: bytes, offset: int, byte_count: int) -> str | None:
    if offset >= len(data):
        return None
    return _nul_terminated_latin1(data[offset : min(offset + byte_count, len(data))])


def _fixed_utf16_string(data: bytes, offset: int, byte_count: int) -> str | None:
    if offset >= len(data):
        return None
    end = min(offset + byte_count, len(data))
    raw = data[offset:end]
    terminator = _find_utf16_terminator(raw, 0)
    return raw[:terminator].decode("utf-16le", errors="replace")


def _target_file_dos_name(data: bytes) -> str | None:
    if len(data) >= 4 and 0x20 <= data[0] <= 0x7F and data[1] == 0 and 0x20 <= data[2] <= 0x7F:
        end = _find_utf16_terminator(data, 0)
        return data[:end].decode("utf-16le", errors="replace")
    return _nul_terminated_latin1(data)


def _utf16_nul_strings(data: bytes) -> tuple[str, ...]:
    values: list[str] = []
    start = 0
    while start < len(data):
        end = _find_utf16_terminator(data, start)
        if end <= start:
            break
        values.append(data[start:end].decode("utf-16le", errors="replace"))
        start = end + 2
    return tuple(value for value in values if value)


def _dos_time_text(value: int) -> str:
    year = ((value >> 9) & 0x7F) + 1980
    month = (value >> 5) & 0x0F
    day = value & 0x1F
    hour = (value >> 27) & 0x1F
    minute = (value >> 21) & 0x3F
    second = (value >> 15) & 0x3E
    return f"{year:04d}:{month:02d}:{day:02d} {hour:02d}:{minute:02d}:{second:02d}"


def _drive_type_text(value: int) -> str | int:
    names = {
        0: "Unknown",
        1: "Invalid Root Path",
        2: "Removable Media",
        3: "Fixed Disk",
        4: "Remote Drive",
        5: "CD-ROM",
        6: "Ram Disk",
    }
    return names.get(value, value)


def _net_provider_type_text(value: int) -> str:
    names = {
        0x010000: "MSNET",
        0x020000: "SMB",
        0x030000: "NETWARE",
        0x040000: "VINES",
        0x2E0000: "DAV",
        0x3F0000: "VMWARE",
        0x430000: "GOOGLE",
    }
    return names.get(value, f"0x{value:x}")


def _code_page_text(value: int) -> str | int:
    code_pages = {
        437: "DOS United States",
        932: "Windows Japanese (Shift-JIS)",
        936: "Windows Simplified Chinese (PRC, Singapore)",
        949: "Windows Korean (Unified Hangul Code)",
        950: "Windows Traditional Chinese (Taiwan)",
        1200: "Unicode UTF-16, little endian",
        1201: "Unicode UTF-16, big endian",
        1252: "Windows Latin 1 (Western European)",
        65001: "Unicode (UTF-8)",
    }
    return code_pages.get(value, value)


def _nul_terminated_latin1(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("latin-1", errors="replace")


def _nul_terminated_utf16(data: bytes) -> str:
    terminator = data.find(b"\0\0")
    raw = data if terminator < 0 else data[: terminator + (terminator % 2)]
    if len(raw) % 2:
        raw = raw[:-1]
    return raw.decode("utf-16le", errors="replace")


def invoke_lnk(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_lnk_read_graph(_read_bounded_prefix(path, _LNK_SECTION_SCAN_LIMIT), source_file)


def _read_bounded_prefix(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        return file.read(byte_count)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="lnk",
        builder_ref="exifmodern.formats.lnk:invoke_lnk",
        patterns=(
            Pattern(
                0,
                b"L\x00\x00\x00\x01\x14\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46",
            ),
        ),
    ),
    Signature(
        format_id="url/cr",
        builder_ref="exifmodern.formats.lnk:invoke_lnk",
        patterns=(Pattern(0, b"[InternetShortcut]\r"),),
        extensions=(".url",),
    ),
    Signature(
        format_id="url/lf",
        builder_ref="exifmodern.formats.lnk:invoke_lnk",
        patterns=(Pattern(0, b"[InternetShortcut]\n"),),
        extensions=(".url",),
    ),
)
