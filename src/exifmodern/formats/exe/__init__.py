"""Windows EXE/PE resource metadata planning."""

import time
from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.exe.debug_codeview_plan import (
    ExeDebugCodeViewPlan,
    build_exe_debug_codeview_plan,
)
from exifmodern.formats.exe.mach_o_header_plan import (
    MachOHeaderPlan,
    build_mach_o_header_plan,
)
from exifmodern.formats.exe.mach_o_override_plan import (
    MachOOverridePlan,
    build_mach_o_override_plan,
)
from exifmodern.formats.exe.resource_transaction_plan import (
    ExeResourceTransactionPlan,
    ExeVersionStringWriteRequest,
    PeVersionInfoPlan,
    build_exe_resource_transaction_plan,
)
from exifmodern.formats.exe.scalar_header_plan import (
    ExeScalarHeaderPlan,
    build_exe_scalar_header_plan,
)
from exifmodern.formats.exe.subformat_plan import (
    ExeSubformatPlan,
    build_exe_subformat_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance

__all__ = [
    "ExeDebugCodeViewPlan",
    "ExeResourceTransactionPlan",
    "ExeScalarHeaderPlan",
    "ExeSubformatPlan",
    "ExeVersionStringWriteRequest",
    "MachOHeaderPlan",
    "MachOOverridePlan",
    "build_exe_debug_codeview_plan",
    "build_exe_read_graph",
    "build_exe_resource_transaction_plan",
    "build_exe_scalar_header_plan",
    "build_exe_subformat_plan",
    "build_mach_o_header_plan",
    "build_mach_o_override_plan",
    "invoke_exe",
]

EXE_HEADER_READ_LIMIT = 65536

_ELF_OBJECT_FILE_TYPES = {
    0: "None",
    1: "Relocatable file",
    2: "Executable file",
    3: "Shared object file",
    4: "Core file",
}
_ELF_CPU_TYPES = {
    0: "None",
    3: "i386",
    40: "Arm (up to Armv7/AArch32)",
    62: "AMD x86-64",
    183: "Arm 64-bits (Armv8/AArch64)",
    243: "RISC-V",
}
_PE_MACHINE_TYPES = {
    0x0000: "Unknown",
    0x014C: "Intel 386 or later, and compatibles",
    0x8664: "AMD AMD64",
    0xAA64: "ARM64 little endian",
}
_PE_IMAGE_FILE_CHARACTERISTICS = {
    0: "No relocs",
    1: "Executable",
    2: "No line numbers",
    3: "No symbols",
    4: "Aggressive working-set trim",
    5: "Large address aware",
    7: "Bytes reversed lo",
    8: "32-bit",
    9: "No debug",
    10: "Removable run from swap",
    11: "Net run from swap",
    12: "System file",
    13: "DLL",
    14: "Uniprocessor only",
    15: "Bytes reversed hi",
}
_PE_SUBSYSTEMS = {
    0: "Unknown",
    1: "Native",
    2: "Windows GUI",
    3: "Windows command line",
    5: "OS/2 command line",
    7: "POSIX command line",
    9: "Windows CE GUI",
    10: "EFI application",
    11: "EFI boot service",
    12: "EFI runtime driver",
    13: "EFI ROM",
    14: "XBOX",
}
_PE_FILE_FLAGS = {
    0: "Debug",
    1: "Pre-release",
    2: "Patched",
    3: "Private build",
    4: "Info inferred",
    5: "Special build",
}
_PE_FILE_OS = {
    0x00001: "Win16",
    0x00002: "PM-16",
    0x00003: "PM-32",
    0x00004: "Win32",
    0x10000: "DOS",
    0x20000: "OS/2 16-bit",
    0x30000: "OS/2 32-bit",
    0x40000: "Windows NT",
    0x10001: "Windows 16-bit",
    0x10004: "Windows 32-bit",
    0x20002: "OS/2 16-bit PM-16",
    0x30003: "OS/2 32-bit PM-32",
    0x40004: "Windows NT 32-bit",
}
_PE_OBJECT_FILE_TYPES = {
    0: "Unknown",
    1: "Executable application",
    2: "Dynamic link library",
    3: "Driver",
    4: "Font",
    5: "VxD",
    7: "Static library",
}
_PE_LANGUAGE_CODES = {
    "0409": "English (U.S.)",
}
_PE_CHARACTER_SETS = {
    "0000": "ASCII",
    "03A4": "Windows, Japan (Shift - JIS X-0208)",
    "03A8": "Windows, Chinese (Simplified)",
    "03B5": "Windows, Korea (Shift - KSC 5601)",
    "03B6": "Windows, Taiwan (Big5)",
    "04B0": "Unicode",
    "04E2": "Windows, Latin2 (Eastern European)",
    "04E3": "Windows, Cyrillic",
    "04E4": "Windows, Latin1",
    "04E5": "Windows, Greek",
    "04E6": "Windows, Turkish",
    "04E7": "Windows, Hebrew",
    "04E8": "Windows, Arabic",
}
_PE_STRING_TAG_NAMES = {
    "OriginalFilename": "OriginalFileName",
}

type ExeEvidenceIds = tuple[str, ...]


def _exe_provenance(
    *,
    group: str,
    table_name: str,
    tag_id: str | None,
    evidence_ids: ExeEvidenceIds,
    family_1_group: str | None = None,
    family_2_group: str | None = None,
    family_3_group: str | None = None,
    duplicate_instance_ordinal: int | None = None,
) -> TagProvenance:
    from exifmodern.read_graph import TagProvenance

    return TagProvenance(
        group=group,
        table_name=table_name,
        tag_id=tag_id,
        source=_exe_evidence_text(evidence_ids),
        family_0_group=group,
        family_1_group=group if family_1_group is None else family_1_group,
        family_2_group=_exe_family_2_group(group) if family_2_group is None else family_2_group,
        family_3_group=family_3_group,
        duplicate_instance_ordinal=duplicate_instance_ordinal,
    )


def _exe_evidence_text(evidence_ids: ExeEvidenceIds) -> str:
    if not evidence_ids:
        return "package-local-reader-plan"
    return evidence_ids[0]


def _exe_family_2_group(group: str) -> str:
    if group in {"Audio", "Video", "Image"}:
        return group
    return "Other"


def build_exe_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_exe_subformat_plan(data)
    plan_refs = plan.provenance
    diagnostics: list[str] = [f"EXE package-local reader status: {plan.status}"]
    diagnostics.extend(
        f"EXE package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    )
    table_name = plan.source_table or "Image::ExifTool::EXE::Main"
    tags: list[ReadTag] = [
        ReadTag(
            name="ExeSubformat",
            value=_read_value(plan.kind),
            provenance=_exe_provenance(
                group="EXE",
                table_name=table_name,
                tag_id="kind",
                evidence_ids=plan_refs,
            ),
            schema=None,
        ),
        ReadTag(
            name="ExeRoute",
            value=_read_value(plan.route),
            provenance=_exe_provenance(
                group="EXE",
                table_name=table_name,
                tag_id="route",
                evidence_ids=plan_refs,
            ),
            schema=None,
        ),
    ]
    tags.extend(_file_identity_tags(plan.kind, data, table_name, plan_refs))
    if plan.chm_header is not None:
        tags.append(
            ReadTag(
                name="ChmVersion",
                value=_read_value(plan.chm_header.version),
                provenance=_exe_provenance(
                    group="EXE",
                    table_name=table_name,
                    tag_id="chm_version",
                    evidence_ids=plan_refs,
                ),
                schema=None,
            )
        )
        tags.append(
            ReadTag(
                name="ChmLanguageCode",
                value=_read_value(plan.chm_header.language_code_hex),
                provenance=_exe_provenance(
                    group="EXE",
                    table_name=table_name,
                    tag_id="chm_language_code",
                    evidence_ids=plan_refs,
                ),
                schema=None,
            )
        )
    if plan.route == "mach_o_table":
        tags.extend(_mach_o_tags(data))
    if plan.route == "pe_resource_reader":
        resource_plan = build_exe_resource_transaction_plan(data)
        diagnostics.append(f"EXE PE resource reader status: {resource_plan.status}")
        diagnostics.extend(_pe_resource_diagnostics(resource_plan))
        diagnostics.extend(
            f"EXE PE resource reader gate: {gate.code}: {gate.reason}"
            for gate in resource_plan.output_emission_gates
            if gate.code
            not in {
                "non_mutating_plan_requires_explicit_emission",
                "no_exiftool_write_behavior",
            }
        )
        tags.extend(_pe_resource_tags(resource_plan))
    if plan.route == "elf_table":
        tags.extend(_elf_tags(data))
    if plan.route == "ar_table":
        scalar_plan = build_exe_scalar_header_plan(data)
        scalar_refs = scalar_plan.provenance
        if scalar_plan.ar_header is not None:
            tags.append(
                ReadTag(
                    name="CreateDate",
                    value=_read_value(
                        _format_local_unix_time(scalar_plan.ar_header.create_date_raw)
                    ),
                    provenance=_exe_provenance(
                        group="EXE",
                        table_name="Image::ExifTool::EXE::AR",
                        tag_id="16",
                        evidence_ids=scalar_refs,
                    ),
                    schema=None,
                )
            )
        tags.extend(_ar_embedded_mach_o_tags(data))
    return _graph(source_file, tags, diagnostics)


def _pe_resource_diagnostics(resource_plan: ExeResourceTransactionPlan) -> list[str]:
    resources: list[str] = []
    seen_resource_types: set[str] = set()
    for resource in resource_plan.resources:
        if resource.level != 0:
            continue
        resource_type = resource.resource_type_name or "Unknown"
        if resource_type in seen_resource_types:
            continue
        seen_resource_types.add(resource_type)
        resources.append(f"EXE PE resource diagnostic: {resource_type} resource")
    return resources


def _pe_resource_tags(resource_plan: ExeResourceTransactionPlan) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _read_value
    from exifmodern.read_graph import ReadTag

    pe_header = resource_plan.pe_header
    if pe_header is None:
        return []
    tags: list[ReadTag] = []
    header_values: list[tuple[str, str, str | int | float | None]] = [
        ("MachineType", "0", _render_map(_PE_MACHINE_TYPES, pe_header.machine)),
        ("TimeStamp", "2", _format_local_unix_time(str(pe_header.timestamp))),
        (
            "ImageFileCharacteristics",
            "9",
            _render_bitmask(_PE_IMAGE_FILE_CHARACTERISTICS, pe_header.characteristics),
        ),
        ("PEType", "10", pe_header.pe_type),
        ("LinkerVersion", "11", _numeric_version_value(pe_header.linker_version)),
        ("CodeSize", "12", pe_header.code_size),
        ("InitializedDataSize", "14", pe_header.initialized_data_size),
        ("UninitializedDataSize", "16", pe_header.uninitialized_data_size),
        ("EntryPoint", "18", _render_hex(pe_header.entry_point)),
        ("OSVersion", "30", _numeric_version_value(pe_header.os_version)),
        ("ImageVersion", "32", _numeric_version_value(pe_header.image_version)),
        ("SubsystemVersion", "34", _numeric_version_value(pe_header.subsystem_version)),
        (
            "Subsystem",
            "44",
            _render_map(_PE_SUBSYSTEMS, pe_header.subsystem)
            if pe_header.subsystem is not None
            else None,
        ),
    ]
    tags.extend(
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_exe_provenance(
                group="EXE",
                table_name="Image::ExifTool::EXE::Main",
                tag_id=tag_id,
                evidence_ids=pe_header.evidence_ids,
            ),
            schema=None,
        )
        for name, tag_id, value in header_values
        if value is not None
    )
    if resource_plan.version_info is not None:
        tags.extend(_pe_version_tags(resource_plan.version_info))
    return tags


def _pe_version_tags(version_info: PeVersionInfoPlan) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _read_value
    from exifmodern.read_graph import ReadTag

    tags: list[ReadTag] = []
    fixed_values: list[tuple[str, str, str | int | None]] = [
        ("FileVersionNumber", "2", version_info.file_version_number),
        ("ProductVersionNumber", "4", version_info.product_version_number),
        ("FileFlagsMask", "6", _render_hex(version_info.file_flags_mask)),
        (
            "FileFlags",
            "7",
            _render_bitmask(_PE_FILE_FLAGS, version_info.file_flags)
            if version_info.file_flags is not None
            else None,
        ),
        (
            "FileOS",
            "8",
            _render_map(_PE_FILE_OS, version_info.file_os)
            if version_info.file_os is not None
            else None,
        ),
        (
            "ObjectFileType",
            "9",
            _render_map(_PE_OBJECT_FILE_TYPES, version_info.object_file_type)
            if version_info.object_file_type is not None
            else None,
        ),
        ("FileSubtype", "10", version_info.file_subtype),
    ]
    tags.extend(
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_exe_provenance(
                group="EXE",
                table_name="Image::ExifTool::EXE::PEVersion",
                tag_id=tag_id,
                evidence_ids=version_info.evidence_ids,
            ),
            schema=None,
        )
        for name, tag_id, value in fixed_values
        if value is not None
    )
    first_string = version_info.strings[0] if version_info.strings else None
    if first_string is not None and first_string.language_code is not None:
        tags.append(
            ReadTag(
                name="LanguageCode",
                value=_read_value(
                    _PE_LANGUAGE_CODES.get(first_string.language_code, first_string.language_code)
                ),
                provenance=_exe_provenance(
                    group="EXE",
                    table_name="Image::ExifTool::EXE::PEString",
                    tag_id="LanguageCode",
                    evidence_ids=first_string.evidence_ids,
                ),
                schema=None,
            )
        )
    if first_string is not None and first_string.character_set is not None:
        tags.append(
            ReadTag(
                name="CharacterSet",
                value=_read_value(
                    _PE_CHARACTER_SETS.get(first_string.character_set, first_string.character_set)
                ),
                provenance=_exe_provenance(
                    group="EXE",
                    table_name="Image::ExifTool::EXE::PEString",
                    tag_id="CharacterSet",
                    evidence_ids=first_string.evidence_ids,
                ),
                schema=None,
            )
        )
    tags.extend(
        ReadTag(
            name=_PE_STRING_TAG_NAMES.get(string.tag, string.tag),
            value=_read_value(string.value),
            provenance=_exe_provenance(
                group="EXE",
                table_name="Image::ExifTool::EXE::PEString",
                tag_id=string.tag,
                evidence_ids=string.evidence_ids,
            ),
            schema=None,
        )
        for string in version_info.strings
    )
    return tags


def invoke_exe(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    with path.open("rb") as file:
        data = file.read(EXE_HEADER_READ_LIMIT)
    return build_exe_read_graph(data, source_file)


def _file_identity_tags(
    kind: str,
    data: bytes,
    table_name: str,
    evidence_ids: tuple[str, ...],
) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _read_value
    from exifmodern.read_graph import ReadTag

    identity = _file_identity(kind, data)
    if identity is None:
        return []
    file_type, extension, mime_type = identity
    return [
        ReadTag(
            name="FileType",
            value=_read_value(file_type),
            provenance=_exe_provenance(
                group="File",
                table_name=table_name,
                tag_id="FileType",
                evidence_ids=evidence_ids,
            ),
            schema=None,
        ),
        ReadTag(
            name="FileTypeExtension",
            value=_read_value(extension),
            provenance=_exe_provenance(
                group="File",
                table_name=table_name,
                tag_id="FileTypeExtension",
                evidence_ids=evidence_ids,
            ),
            schema=None,
        ),
        ReadTag(
            name="MIMEType",
            value=_read_value(mime_type),
            provenance=_exe_provenance(
                group="File",
                table_name=table_name,
                tag_id="MIMEType",
                evidence_ids=evidence_ids,
            ),
            schema=None,
        ),
    ]


def _file_identity(kind: str, data: bytes) -> tuple[str, str, str] | None:
    if kind == "mach_o":
        mach_o_plan = build_mach_o_header_plan(data)
        if mach_o_plan.thin_header is not None:
            override = build_mach_o_override_plan(mach_o_plan.thin_header.mach_file_type)
            if override.description is not None and override.extension is not None:
                return (
                    override.description,
                    override.extension.lower(),
                    "application/octet-stream",
                )
        return ("Mach-O executable", "", "application/octet-stream")
    if kind == "mach_o_fat":
        mach_o_plan = build_mach_o_header_plan(data)
        object_file_type = _fat_mach_o_object_file_type(data, mach_o_plan)
        if object_file_type is not None:
            override = build_mach_o_override_plan(object_file_type, fat_binary=True)
            if override.description is not None and override.extension is not None:
                return (
                    override.description,
                    override.extension.lower(),
                    "application/octet-stream",
                )
        return ("Mach-O fat binary executable", "", "application/octet-stream")
    if kind == "elf":
        scalar_plan = build_exe_scalar_header_plan(data)
        if scalar_plan.elf_header is not None and scalar_plan.elf_header.file_type == 3:
            return ("ELF shared library", "so", "application/octet-stream")
        if scalar_plan.elf_header is not None and scalar_plan.elf_header.file_type == 1:
            return ("ELF object file", "o", "application/octet-stream")
        return ("ELF executable", "", "application/octet-stream")
    if kind == "ar":
        mach_o_header = _first_embedded_mach_o_header(data)
        if mach_o_header is not None:
            return ("Mach-O static library", "a", "application/octet-stream")
        return ("Static library", "a", "application/octet-stream")
    if kind == "pe_or_dos_exe":
        return ("Win32 EXE", "exe", "application/octet-stream")
    return None


def _mach_o_tags(data: bytes) -> list[ReadTag]:
    plan = build_mach_o_header_plan(data)
    return _mach_o_plan_tags(plan, include_object_type=True)


def _ar_embedded_mach_o_tags(data: bytes) -> list[ReadTag]:
    header = _first_embedded_mach_o_header(data)
    if header is None:
        return []
    return _mach_o_plan_tags(build_mach_o_header_plan(header), include_object_type=False)


def _mach_o_plan_tags(plan: MachOHeaderPlan, *, include_object_type: bool) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _read_value
    from exifmodern.read_graph import ReadTag

    if plan.thin_header is None:
        return []
    header = plan.thin_header
    tag_values: list[tuple[str, str, str]] = [
        ("CPUArchitecture", "0", header.bit_depth),
        ("CPUByteOrder", "1", _render_byte_order(header.byte_order)),
        ("CPUType", "3", header.cpu_type_description),
        ("CPUSubtype", "4", header.cpu_subtype_description),
    ]
    if include_object_type:
        tag_values.append(("ObjectFileType", "5", header.mach_file_type_description))
        tag_values.append(("ObjectFlags", "6", ", ".join(header.mach_flag_descriptions)))
    return [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_exe_provenance(
                group="EXE",
                table_name="Image::ExifTool::EXE::MachO",
                tag_id=tag_id,
                evidence_ids=plan.evidence_ids,
            ),
            schema=None,
        )
        for name, tag_id, value in tag_values
    ]


def _elf_tags(data: bytes) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_exe_scalar_header_plan(data)
    if plan.elf_header is None:
        return []
    plan_refs = plan.provenance
    header = plan.elf_header
    tag_values = (
        ("CPUArchitecture", "4", header.cpu_architecture),
        ("CPUByteOrder", "5", _render_byte_order(header.cpu_byte_order)),
        (
            "ObjectFileType",
            "16",
            _ELF_OBJECT_FILE_TYPES.get(header.file_type, f"Unknown ({header.file_type})"),
        ),
        ("CPUType", "18", _ELF_CPU_TYPES.get(header.cpu_type, f"Unknown ({header.cpu_type})")),
    )
    return [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_exe_provenance(
                group="EXE",
                table_name="Image::ExifTool::EXE::ELF",
                tag_id=tag_id,
                evidence_ids=plan_refs,
            ),
            schema=None,
        )
        for name, tag_id, value in tag_values
    ]


def _render_map(values: dict[int, str], value: int | None) -> str | None:
    if value is None:
        return None
    return values.get(value, f"Unknown ({value})")


def _render_bitmask(values: dict[int, str], mask: int) -> str:
    rendered = [text for bit, text in values.items() if mask & (1 << bit)]
    return ", ".join(rendered)


def _render_hex(value: int | None) -> str | None:
    if value is None:
        return None
    return f"0x{value:04x}"


def _numeric_version_value(value: str | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _render_byte_order(byte_order: str) -> str:
    if byte_order == "little":
        return "Little endian"
    if byte_order == "big":
        return "Big endian"
    return "Unknown"


def _format_local_unix_time(raw_timestamp: str) -> str:
    try:
        timestamp = int(raw_timestamp)
    except ValueError:
        return raw_timestamp
    parts = time.localtime(timestamp)
    offset = time.strftime("%z", parts)
    timezone_text = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else ""
    return (
        f"{parts.tm_year:04d}:{parts.tm_mon:02d}:{parts.tm_mday:02d} "
        f"{parts.tm_hour:02d}:{parts.tm_min:02d}:{parts.tm_sec:02d}{timezone_text}"
    )


def _fat_mach_o_object_file_type(data: bytes, plan: MachOHeaderPlan) -> int | None:
    first_arch = plan.fat_architectures[0] if plan.fat_architectures else None
    if first_arch is None:
        return None
    header = data[first_arch.file_offset : first_arch.file_offset + 16]
    nested = build_mach_o_header_plan(header + b"\x00" * 12)
    if nested.thin_header is not None:
        return nested.thin_header.mach_file_type
    if header.startswith(b"!<arch>\n"):
        return -1
    return None


def _first_embedded_mach_o_header(data: bytes) -> bytes | None:
    position = 8
    remaining_members = 10
    while remaining_members > 0 and position + 60 <= len(data):
        header = data[position : position + 60]
        if header[58:60] != b"`\n":
            return None
        name = header[:16].decode("ascii", errors="replace")
        payload_start = position + 60
        if name.startswith("#1/"):
            name_length_text = name[3:].strip()
            if not name_length_text.isdecimal():
                return None
            name_length = int(name_length_text)
            if name_length > 256:
                return None
            payload_start += name_length
        size_text = header[48:58].decode("ascii", errors="replace").strip()
        if not size_text.isdecimal():
            return None
        member_size = int(size_text)
        mach_header = data[payload_start : payload_start + 28]
        if build_mach_o_header_plan(mach_header).thin_header is not None:
            return mach_header
        position += 60 + member_size
        if position & 1:
            position += 1
        remaining_members -= 1
    return None


_EXE_BUILDER = "exifmodern.formats.exe:invoke_exe"

SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="exe/mz",
        builder_ref=_EXE_BUILDER,
        patterns=(Pattern(0, b"MZ"),),
    ),
    Signature(
        format_id="exe/macho_fat",
        builder_ref=_EXE_BUILDER,
        patterns=(Pattern(0, b"\xca\xfe\xba\xbe"),),
    ),
    Signature(
        format_id="exe/macho_be_32",
        builder_ref=_EXE_BUILDER,
        patterns=(Pattern(0, b"\xfe\xed\xfa\xce"),),
    ),
    Signature(
        format_id="exe/macho_be_64",
        builder_ref=_EXE_BUILDER,
        patterns=(Pattern(0, b"\xfe\xed\xfa\xcf"),),
    ),
    Signature(
        format_id="exe/macho_le_32",
        builder_ref=_EXE_BUILDER,
        patterns=(Pattern(0, b"\xce\xfa\xed\xfe"),),
    ),
    Signature(
        format_id="exe/macho_le_64",
        builder_ref=_EXE_BUILDER,
        patterns=(Pattern(0, b"\xcf\xfa\xed\xfe"),),
    ),
    Signature(
        format_id="exe/elf",
        builder_ref=_EXE_BUILDER,
        patterns=(Pattern(0, b"\x7fELF"),),
    ),
    Signature(
        format_id="exe/peff",
        builder_ref=_EXE_BUILDER,
        patterns=(Pattern(0, b"Joy!peff"),),
    ),
    Signature(
        format_id="exe/ar",
        builder_ref=_EXE_BUILDER,
        patterns=(Pattern(0, b"!<arch>\n"),),
    ),
    Signature(
        format_id="exe/chm",
        builder_ref=_EXE_BUILDER,
        patterns=(
            Pattern(0, b"ITSF"),
            Pattern(24, b"\x10\xfd\x01\x7c\xaa\x7b\xd0\x11\x9e\x0c\x00\xa0\xc9\x22\xe6\xec"),
        ),
    ),
)
