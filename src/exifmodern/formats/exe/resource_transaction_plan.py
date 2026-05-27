"""Source-grounded, non-mutating Windows EXE/PE resource transaction plans.

The planner mirrors ExifTool's EXE reader enough to validate MZ/PE structure,
translate resource RVAs through the section table, traverse PE resources, route
the first Version resource, and preserve all other resources.  It intentionally
does not mutate bytes: EXE/PE resource rewrites require alignment, RVA, checksum,
and certificate-table fixups that ExifTool's EXE module does not implement.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

MZ_HEADER_SIZE = 0x40
PE_SIGNATURE = b"PE\0\0"
COFF_HEADER_SIZE = 20
SECTION_HEADER_SIZE = 40
RESOURCE_DIRECTORY_HEADER_SIZE = 16
RESOURCE_DIRECTORY_ENTRY_SIZE = 8
RESOURCE_DATA_ENTRY_SIZE = 16
RESOURCE_DIRECTORY_FLAG = 0x80000000
RESOURCE_DIRECTORY_OFFSET_MASK = 0x7FFFFFFF
MAX_RESOURCE_DIRECTORY_DEPTH = 10
MAX_RESOURCE_DIRECTORY_ENTRIES = 10000

PE32_MAGIC = 0x10B
PE32_PLUS_MAGIC = 0x20B
ROM_IMAGE_MAGIC = 0x107
OPTIONAL_HEADER_CHECKSUM_OFFSET = 64
PE32_DATA_DIRECTORY_OFFSET = 96
PE32_PLUS_DATA_DIRECTORY_OFFSET = 112
RESOURCE_DATA_DIRECTORY_INDEX = 2
SECURITY_DATA_DIRECTORY_INDEX = 4

VERSION_RESOURCE_TYPE_ID = 16
ICON_RESOURCE_TYPE_ID = 3
GROUP_ICON_RESOURCE_TYPE_ID = 14

type ExePlanStatus = Literal["planned", "unsupported"]
type PeType = Literal["PE32", "PE32+", "ROM Image", "unknown"]
type ExeResourceKind = Literal["version", "icon", "group_icon", "preserved", "unknown"]
type ExeActionKind = Literal[
    "preserve_resource",
    "preserve_icon_resource",
    "route_version_info",
    "route_string_file_info",
    "block_version_string_rewrite",
]
type ExeEmissionGateCode = Literal[
    "truncated_dos_header",
    "unsupported_mz_signature",
    "lfanew_out_of_range",
    "unsupported_windows_header",
    "truncated_pe_header",
    "truncated_optional_header",
    "unknown_pe_magic",
    "truncated_section_table",
    "resource_section_missing",
    "resource_directory_truncated",
    "resource_directory_entry_limit_exceeded",
    "resource_recursion_limit_exceeded",
    "resource_data_entry_truncated",
    "resource_rva_unmapped",
    "resource_payload_truncated",
    "version_info_invalid",
    "version_resource_alignment_rewrite_blocked",
    "rva_translation_rewrite_blocked",
    "checksum_rewrite_blocked",
    "security_directory_rewrite_blocked",
    "non_mutating_plan_requires_explicit_emission",
    "no_exiftool_write_behavior",
]
type ExeResourceEvidenceId = Literal[
    "exe.resource.module",
    "exe.resource.type_table",
    "exe.resource.pe_header_table",
    "exe.resource.pe_version_table",
    "exe.resource.pe_string_table",
    "exe.resource.unicode_string",
    "exe.resource.pe_version_process",
    "exe.resource.rva_translation",
    "exe.resource.traversal",
    "exe.resource.pe_dict",
    "exe.resource.process_exe",
    "exe.resource.data_directory",
]

EXE_MODULE_SOURCE: ExeResourceEvidenceId = "exe.resource.module"
RESOURCE_TYPE_SOURCE: ExeResourceEvidenceId = "exe.resource.type_table"
PE_HEADER_TABLE_SOURCE: ExeResourceEvidenceId = "exe.resource.pe_header_table"
PE_VERSION_TABLE_SOURCE: ExeResourceEvidenceId = "exe.resource.pe_version_table"
PE_STRING_TABLE_SOURCE: ExeResourceEvidenceId = "exe.resource.pe_string_table"
UNICODE_STRING_SOURCE: ExeResourceEvidenceId = "exe.resource.unicode_string"
PE_VERSION_PROCESS_SOURCE: ExeResourceEvidenceId = "exe.resource.pe_version_process"
RVA_TRANSLATION_SOURCE: ExeResourceEvidenceId = "exe.resource.rva_translation"
RESOURCE_TRAVERSAL_SOURCE: ExeResourceEvidenceId = "exe.resource.traversal"
PE_DICT_SOURCE: ExeResourceEvidenceId = "exe.resource.pe_dict"
PROCESS_EXE_SOURCE: ExeResourceEvidenceId = "exe.resource.process_exe"
DATA_DIRECTORY_SOURCE: ExeResourceEvidenceId = "exe.resource.data_directory"

EXE_RESOURCE_TRANSACTION_SOURCES = (
    EXE_MODULE_SOURCE,
    RESOURCE_TYPE_SOURCE,
    PE_HEADER_TABLE_SOURCE,
    PE_VERSION_TABLE_SOURCE,
    PE_STRING_TABLE_SOURCE,
    UNICODE_STRING_SOURCE,
    PE_VERSION_PROCESS_SOURCE,
    RVA_TRANSLATION_SOURCE,
    RESOURCE_TRAVERSAL_SOURCE,
    PE_DICT_SOURCE,
    PROCESS_EXE_SOURCE,
    DATA_DIRECTORY_SOURCE,
)

RESOURCE_TYPE_NAMES = {
    ICON_RESOURCE_TYPE_ID: "Icon",
    GROUP_ICON_RESOURCE_TYPE_ID: "Group Icon",
    VERSION_RESOURCE_TYPE_ID: "Version",
}


@dataclass(frozen=True)
class ExeVersionStringWriteRequest:
    tag: str
    value: str


@dataclass(frozen=True)
class ExeEmissionGate:
    code: ExeEmissionGateCode
    reason: str
    evidence_ids: tuple[ExeResourceEvidenceId, ...]


@dataclass(frozen=True)
class ExeDosHeaderPlan:
    magic: bytes
    lfanew: int | None
    declared_dos_file_size: int | None
    relocation_table_offset: int | None
    evidence_ids: tuple[ExeResourceEvidenceId, ...]


@dataclass(frozen=True)
class PeDataDirectoryPlan:
    index: int
    name: str
    rva: int
    size: int
    evidence_ids: tuple[ExeResourceEvidenceId, ...]


@dataclass(frozen=True)
class ExePeHeaderPlan:
    signature_offset: int
    machine: int
    timestamp: int
    number_of_sections: int
    optional_header_size: int
    characteristics: int
    pe_magic: int
    pe_type: PeType
    linker_version: str | None
    code_size: int | None
    initialized_data_size: int | None
    uninitialized_data_size: int | None
    entry_point: int | None
    os_version: str | None
    image_version: str | None
    subsystem_version: str | None
    subsystem: int | None
    checksum: int
    resource_directory: PeDataDirectoryPlan
    security_directory: PeDataDirectoryPlan
    evidence_ids: tuple[ExeResourceEvidenceId, ...]


@dataclass(frozen=True)
class PeSectionPlan:
    index: int
    name: str
    virtual_address: int
    raw_size: int
    raw_pointer: int
    evidence_ids: tuple[ExeResourceEvidenceId, ...]


@dataclass(frozen=True)
class PeResourceDataPlan:
    data_rva: int
    size: int
    code_page: int
    file_offset: int | None
    payload: bytes | None
    evidence_ids: tuple[ExeResourceEvidenceId, ...]


@dataclass(frozen=True)
class PeResourceEntryPlan:
    index: int
    level: int
    resource_type_id: int | None
    resource_type_name: str | None
    name_or_id: int
    is_directory: bool
    directory_offset: int | None
    data: PeResourceDataPlan | None
    kind: ExeResourceKind
    evidence_ids: tuple[ExeResourceEvidenceId, ...]


@dataclass(frozen=True)
class PeVersionStringPlan:
    tag: str
    value: str
    language_code: str | None
    character_set: str | None
    block_offset: int
    evidence_ids: tuple[ExeResourceEvidenceId, ...]


@dataclass(frozen=True)
class PeVersionInfoPlan:
    resource_entry_index: int
    file_version_number: str | None
    product_version_number: str | None
    file_flags_mask: int | None
    file_flags: int | None
    file_os: int | None
    object_file_type: int | None
    file_subtype: int | None
    strings: tuple[PeVersionStringPlan, ...]
    is_valid: bool
    evidence_ids: tuple[ExeResourceEvidenceId, ...]


@dataclass(frozen=True)
class ExeResourceActionPlan:
    kind: ExeActionKind
    resource_entry_index: int | None
    target: str
    reason: str
    evidence_ids: tuple[ExeResourceEvidenceId, ...]


@dataclass(frozen=True)
class ExeResourceTransactionPlan:
    status: ExePlanStatus
    dos_header: ExeDosHeaderPlan
    pe_header: ExePeHeaderPlan | None
    sections: tuple[PeSectionPlan, ...]
    resources: tuple[PeResourceEntryPlan, ...]
    version_info: PeVersionInfoPlan | None
    requested_version_string_updates: tuple[ExeVersionStringWriteRequest, ...]
    actions: tuple[ExeResourceActionPlan, ...]
    output_emission_gates: tuple[ExeEmissionGate, ...]
    evidence_ids: tuple[ExeResourceEvidenceId, ...]

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
        raise ValueError(f"EXE resource transaction output is gated: {gate_codes}")


@dataclass(frozen=True)
class _PeParsedHeader:
    plan: ExePeHeaderPlan
    section_table_offset: int


def build_exe_resource_transaction_plan(
    exe_data: bytes,
    *,
    version_string_updates: Iterable[ExeVersionStringWriteRequest] = (),
    allow_output_emission: bool = False,
) -> ExeResourceTransactionPlan:
    requests = tuple(version_string_updates)
    gates: list[ExeEmissionGate] = []
    dos_header = _parse_dos_header(exe_data, gates)
    if dos_header.lfanew is None:
        return _unsupported_plan(dos_header, requests, gates)

    parsed_header = _parse_pe_header(exe_data, dos_header.lfanew, gates)
    if parsed_header is None:
        _add_emission_gate(gates, allow_output_emission)
        return _unsupported_plan(dos_header, requests, gates)

    sections = _parse_sections(exe_data, parsed_header, gates)
    resources = _parse_resources(exe_data, sections, gates)
    version_info, version_gates = _parse_first_version_info(resources)
    gates.extend(version_gates)
    actions = _plan_actions(resources, version_info, requests)
    gates.extend(_rewrite_blockers(parsed_header.plan, version_info, requests))
    _add_emission_gate(gates, allow_output_emission)
    status: ExePlanStatus = "unsupported" if _has_structural_gate(gates) else "planned"
    return ExeResourceTransactionPlan(
        status=status,
        dos_header=dos_header,
        pe_header=parsed_header.plan,
        sections=sections,
        resources=resources,
        version_info=version_info,
        requested_version_string_updates=requests,
        actions=actions,
        output_emission_gates=_unique_gates(tuple(gates)),
        evidence_ids=_collect_sources(
            resources=resources,
            version_info=version_info,
            actions=actions,
            gates=tuple(gates),
        ),
    )


plan_exe_resource_transaction = build_exe_resource_transaction_plan


def _parse_dos_header(exe_data: bytes, gates: list[ExeEmissionGate]) -> ExeDosHeaderPlan:
    if len(exe_data) < MZ_HEADER_SIZE:
        gates.append(
            ExeEmissionGate(
                code="truncated_dos_header",
                reason="Input ended before ExifTool's 0x40-byte DOS header read.",
                evidence_ids=(PROCESS_EXE_SOURCE,),
            )
        )
        return ExeDosHeaderPlan(
            magic=exe_data[:2],
            lfanew=None,
            declared_dos_file_size=None,
            relocation_table_offset=None,
            evidence_ids=(PROCESS_EXE_SOURCE,),
        )
    magic = exe_data[:2]
    if magic != b"MZ":
        gates.append(
            ExeEmissionGate(
                code="unsupported_mz_signature",
                reason="Input does not begin with the MZ DOS/Windows executable signature.",
                evidence_ids=(PROCESS_EXE_SOURCE,),
            )
        )
        return ExeDosHeaderPlan(
            magic=magic,
            lfanew=None,
            declared_dos_file_size=None,
            relocation_table_offset=None,
            evidence_ids=(PROCESS_EXE_SOURCE,),
        )
    cblp = _u16(exe_data, 2)
    cp = _u16(exe_data, 4)
    relocation_table_offset = _u16(exe_data, 24)
    lfanew = _u32(exe_data, 60)
    declared_size = (cp - (1 if cblp else 0)) * 512 + cblp
    if lfanew + 4 > len(exe_data):
        gates.append(
            ExeEmissionGate(
                code="lfanew_out_of_range",
                reason="The DOS lfanew pointer does not reach a readable Windows header.",
                evidence_ids=(PROCESS_EXE_SOURCE,),
            )
        )
    return ExeDosHeaderPlan(
        magic=magic,
        lfanew=lfanew,
        declared_dos_file_size=declared_size,
        relocation_table_offset=relocation_table_offset,
        evidence_ids=(PROCESS_EXE_SOURCE,),
    )


def _parse_pe_header(
    exe_data: bytes,
    lfanew: int,
    gates: list[ExeEmissionGate],
) -> _PeParsedHeader | None:
    if lfanew + 24 > len(exe_data):
        gates.append(
            ExeEmissionGate(
                code="truncated_pe_header",
                reason="Input ended before the PE signature and COFF header could be read.",
                evidence_ids=(PROCESS_EXE_SOURCE, PE_HEADER_TABLE_SOURCE),
            )
        )
        return None
    signature = exe_data[lfanew : lfanew + 4]
    if signature[:2] != b"PE":
        gates.append(
            ExeEmissionGate(
                code="unsupported_windows_header",
                reason="The Windows header at lfanew is not a PE header.",
                evidence_ids=(PROCESS_EXE_SOURCE,),
            )
        )
        return None
    machine = _u16(exe_data, lfanew + 4)
    number_of_sections = _u16(exe_data, lfanew + 6)
    timestamp = _u32(exe_data, lfanew + 8)
    optional_header_size = _u16(exe_data, lfanew + 20)
    characteristics = _u16(exe_data, lfanew + 22)
    optional_header_offset = lfanew + 4 + COFF_HEADER_SIZE
    optional_header_end = optional_header_offset + optional_header_size
    if optional_header_end > len(exe_data):
        gates.append(
            ExeEmissionGate(
                code="truncated_optional_header",
                reason="The PE optional header is shorter than the COFF SizeOfOptionalHeader.",
                evidence_ids=(PROCESS_EXE_SOURCE, PE_HEADER_TABLE_SOURCE),
            )
        )
        return None
    pe_magic = _u16(exe_data, optional_header_offset) if optional_header_size >= 2 else 0
    pe_type = _pe_type(pe_magic)
    if pe_type == "unknown":
        gates.append(
            ExeEmissionGate(
                code="unknown_pe_magic",
                reason="The PE optional-header magic is not ROM Image, PE32, or PE32+.",
                evidence_ids=(PROCESS_EXE_SOURCE, PE_HEADER_TABLE_SOURCE),
            )
        )
    checksum = (
        _u32(exe_data, optional_header_offset + OPTIONAL_HEADER_CHECKSUM_OFFSET)
        if optional_header_size >= OPTIONAL_HEADER_CHECKSUM_OFFSET + 4
        else 0
    )
    resource_directory = _data_directory(
        exe_data,
        optional_header_offset,
        optional_header_size,
        pe_magic,
        RESOURCE_DATA_DIRECTORY_INDEX,
        "Resource",
    )
    security_directory = _data_directory(
        exe_data,
        optional_header_offset,
        optional_header_size,
        pe_magic,
        SECURITY_DATA_DIRECTORY_INDEX,
        "Security",
    )
    return _PeParsedHeader(
        plan=ExePeHeaderPlan(
            signature_offset=lfanew,
            machine=machine,
            timestamp=timestamp,
            number_of_sections=number_of_sections,
            optional_header_size=optional_header_size,
            characteristics=characteristics,
            pe_magic=pe_magic,
            pe_type=pe_type,
            linker_version=_optional_header_linker_version(
                exe_data, optional_header_offset, optional_header_size
            ),
            code_size=_optional_header_u32(
                exe_data, optional_header_offset, optional_header_size, 4
            ),
            initialized_data_size=_optional_header_u32(
                exe_data, optional_header_offset, optional_header_size, 8
            ),
            uninitialized_data_size=_optional_header_u32(
                exe_data, optional_header_offset, optional_header_size, 12
            ),
            entry_point=_optional_header_u32(
                exe_data, optional_header_offset, optional_header_size, 16
            ),
            os_version=_optional_header_version(
                exe_data, optional_header_offset, optional_header_size, 40
            ),
            image_version=_optional_header_version(
                exe_data, optional_header_offset, optional_header_size, 44
            ),
            subsystem_version=_optional_header_version(
                exe_data, optional_header_offset, optional_header_size, 48
            ),
            subsystem=_optional_header_u16(
                exe_data, optional_header_offset, optional_header_size, 68
            ),
            checksum=checksum,
            resource_directory=resource_directory,
            security_directory=security_directory,
            evidence_ids=(PROCESS_EXE_SOURCE, PE_HEADER_TABLE_SOURCE, DATA_DIRECTORY_SOURCE),
        ),
        section_table_offset=optional_header_end,
    )


def _parse_sections(
    exe_data: bytes,
    parsed_header: _PeParsedHeader,
    gates: list[ExeEmissionGate],
) -> tuple[PeSectionPlan, ...]:
    sections: list[PeSectionPlan] = []
    expected_end = (
        parsed_header.section_table_offset
        + parsed_header.plan.number_of_sections * SECTION_HEADER_SIZE
    )
    if expected_end > len(exe_data):
        gates.append(
            ExeEmissionGate(
                code="truncated_section_table",
                reason="Input ended before all PE section headers could be read.",
                evidence_ids=(PROCESS_EXE_SOURCE, PE_DICT_SOURCE),
            )
        )
        return tuple(sections)
    for index in range(parsed_header.plan.number_of_sections):
        offset = parsed_header.section_table_offset + index * SECTION_HEADER_SIZE
        raw_name = exe_data[offset : offset + 8]
        name = raw_name.rstrip(b"\0").decode("ascii", errors="replace")
        sections.append(
            PeSectionPlan(
                index=index,
                name=name,
                virtual_address=_u32(exe_data, offset + 12),
                raw_size=_u32(exe_data, offset + 16),
                raw_pointer=_u32(exe_data, offset + 20),
                evidence_ids=(PE_DICT_SOURCE,),
            )
        )
    return tuple(sections)


def _parse_resources(
    exe_data: bytes,
    sections: tuple[PeSectionPlan, ...],
    gates: list[ExeEmissionGate],
) -> tuple[PeResourceEntryPlan, ...]:
    resource_section = _resource_section(sections)
    if resource_section is None:
        gates.append(
            ExeEmissionGate(
                code="resource_section_missing",
                reason="No .rsrc section or .text fallback exists for PE resource traversal.",
                evidence_ids=(PE_DICT_SOURCE,),
            )
        )
        return ()
    resources: list[PeResourceEntryPlan] = []
    _traverse_resource_directory(
        exe_data=exe_data,
        sections=sections,
        resource_section=resource_section,
        directory_offset=0,
        level=0,
        resource_type_id=None,
        resources=resources,
        gates=gates,
    )
    return tuple(resources)


def _traverse_resource_directory(
    *,
    exe_data: bytes,
    sections: tuple[PeSectionPlan, ...],
    resource_section: PeSectionPlan,
    directory_offset: int,
    level: int,
    resource_type_id: int | None,
    resources: list[PeResourceEntryPlan],
    gates: list[ExeEmissionGate],
) -> None:
    if level > MAX_RESOURCE_DIRECTORY_DEPTH:
        gates.append(
            ExeEmissionGate(
                code="resource_recursion_limit_exceeded",
                reason="Resource directory nesting exceeds ExifTool's recursion protection.",
                evidence_ids=(RESOURCE_TRAVERSAL_SOURCE,),
            )
        )
        return
    directory_start = resource_section.raw_pointer + directory_offset
    if directory_start + RESOURCE_DIRECTORY_HEADER_SIZE > len(exe_data):
        gates.append(
            ExeEmissionGate(
                code="resource_directory_truncated",
                reason="Resource directory header is truncated.",
                evidence_ids=(RESOURCE_TRAVERSAL_SOURCE,),
            )
        )
        return
    name_entries = _u16(exe_data, directory_start + 12)
    id_entries = _u16(exe_data, directory_start + 14)
    count = name_entries + id_entries
    if count > MAX_RESOURCE_DIRECTORY_ENTRIES:
        gates.append(
            ExeEmissionGate(
                code="resource_directory_entry_limit_exceeded",
                reason="Resource directory entry count exceeds ExifTool's safety limit.",
                evidence_ids=(RESOURCE_TRAVERSAL_SOURCE,),
            )
        )
        return
    entries_start = directory_start + RESOURCE_DIRECTORY_HEADER_SIZE
    entries_end = entries_start + count * RESOURCE_DIRECTORY_ENTRY_SIZE
    if entries_end > len(exe_data):
        gates.append(
            ExeEmissionGate(
                code="resource_directory_truncated",
                reason="Resource directory entries are truncated.",
                evidence_ids=(RESOURCE_TRAVERSAL_SOURCE,),
            )
        )
        return
    for item in range(count):
        entry_offset = entries_start + item * RESOURCE_DIRECTORY_ENTRY_SIZE
        name_or_id = _u32(exe_data, entry_offset)
        entry_position = _u32(exe_data, entry_offset + 4)
        current_type_id = name_or_id if level == 0 else resource_type_id
        type_name = _resource_type_name(current_type_id)
        if entry_position & RESOURCE_DIRECTORY_FLAG:
            next_directory = entry_position & RESOURCE_DIRECTORY_OFFSET_MASK
            resources.append(
                PeResourceEntryPlan(
                    index=len(resources),
                    level=level,
                    resource_type_id=current_type_id,
                    resource_type_name=type_name,
                    name_or_id=name_or_id,
                    is_directory=True,
                    directory_offset=next_directory,
                    data=None,
                    kind=_resource_kind(current_type_id),
                    evidence_ids=(RESOURCE_TYPE_SOURCE, RESOURCE_TRAVERSAL_SOURCE),
                )
            )
            _traverse_resource_directory(
                exe_data=exe_data,
                sections=sections,
                resource_section=resource_section,
                directory_offset=next_directory,
                level=level + 1,
                resource_type_id=current_type_id,
                resources=resources,
                gates=gates,
            )
        else:
            data = _parse_resource_data_entry(
                exe_data=exe_data,
                sections=sections,
                resource_section=resource_section,
                entry_position=entry_position,
                gates=gates,
            )
            resources.append(
                PeResourceEntryPlan(
                    index=len(resources),
                    level=level,
                    resource_type_id=current_type_id,
                    resource_type_name=type_name,
                    name_or_id=name_or_id,
                    is_directory=False,
                    directory_offset=None,
                    data=data,
                    kind=_resource_kind(current_type_id),
                    evidence_ids=(RESOURCE_TYPE_SOURCE, RESOURCE_TRAVERSAL_SOURCE),
                )
            )


def _parse_resource_data_entry(
    *,
    exe_data: bytes,
    sections: tuple[PeSectionPlan, ...],
    resource_section: PeSectionPlan,
    entry_position: int,
    gates: list[ExeEmissionGate],
) -> PeResourceDataPlan | None:
    data_entry_offset = resource_section.raw_pointer + entry_position
    if data_entry_offset + RESOURCE_DATA_ENTRY_SIZE > len(exe_data):
        gates.append(
            ExeEmissionGate(
                code="resource_data_entry_truncated",
                reason="Resource leaf data entry is truncated.",
                evidence_ids=(RESOURCE_TRAVERSAL_SOURCE,),
            )
        )
        return None
    data_rva = _u32(exe_data, data_entry_offset)
    size = _u32(exe_data, data_entry_offset + 4)
    code_page = _u32(exe_data, data_entry_offset + 8)
    file_offset = _rva_to_file_offset(data_rva, sections)
    if file_offset is None:
        gates.append(
            ExeEmissionGate(
                code="resource_rva_unmapped",
                reason="Resource data RVA does not map into any section.",
                evidence_ids=(RVA_TRANSLATION_SOURCE, RESOURCE_TRAVERSAL_SOURCE),
            )
        )
        return PeResourceDataPlan(
            data_rva=data_rva,
            size=size,
            code_page=code_page,
            file_offset=None,
            payload=None,
            evidence_ids=(RVA_TRANSLATION_SOURCE, RESOURCE_TRAVERSAL_SOURCE),
        )
    if file_offset + size > len(exe_data):
        gates.append(
            ExeEmissionGate(
                code="resource_payload_truncated",
                reason="Resource data RVA maps to bytes past the end of the file.",
                evidence_ids=(RVA_TRANSLATION_SOURCE, RESOURCE_TRAVERSAL_SOURCE),
            )
        )
        payload = None
    else:
        payload = exe_data[file_offset : file_offset + size]
    return PeResourceDataPlan(
        data_rva=data_rva,
        size=size,
        code_page=code_page,
        file_offset=file_offset,
        payload=payload,
        evidence_ids=(RVA_TRANSLATION_SOURCE, RESOURCE_TRAVERSAL_SOURCE),
    )


def _parse_first_version_info(
    resources: tuple[PeResourceEntryPlan, ...],
) -> tuple[PeVersionInfoPlan | None, tuple[ExeEmissionGate, ...]]:
    for resource in resources:
        if resource.kind != "version" or resource.data is None or resource.data.payload is None:
            continue
        version_info, gate = _parse_version_payload(resource.index, resource.data.payload)
        if gate is None:
            return version_info, ()
        return version_info, (gate,)
    return None, ()


def _parse_version_payload(
    resource_entry_index: int,
    payload: bytes,
) -> tuple[PeVersionInfoPlan | None, ExeEmissionGate | None]:
    if len(payload) < 6:
        return None, _version_gate("Version resource is too short for a block header.")
    block_length = _u16(payload, 0)
    value_length = _u16(payload, 2)
    if block_length > len(payload) or block_length == 0:
        return None, _version_gate("Version resource block length is invalid.")
    key, value_offset = _read_utf16_resource_string(payload, 6, block_length)
    if key != "VS_VERSION_INFO":
        return None, _version_gate("Version resource does not begin with VS_VERSION_INFO.")
    if value_offset + value_length > block_length:
        return None, _version_gate("VS_VERSION_INFO fixed value exceeds the resource block.")
    file_version = None
    product_version = None
    file_flags_mask = None
    file_flags = None
    file_os = None
    object_file_type = None
    file_subtype = None
    if value_length >= 52 and value_offset + 52 <= len(payload):
        file_version = _format_version_number(
            _u32(payload, value_offset + 8),
            _u32(payload, value_offset + 12),
        )
        product_version = _format_version_number(
            _u32(payload, value_offset + 16),
            _u32(payload, value_offset + 20),
        )
        file_flags_mask = _u32(payload, value_offset + 24)
        file_flags = _u32(payload, value_offset + 28)
        file_os = _u32(payload, value_offset + 32)
        object_file_type = _u32(payload, value_offset + 36)
        file_subtype = _u32(payload, value_offset + 40)
    strings: list[PeVersionStringPlan] = []
    child_offset = _align4(value_offset + value_length)
    while child_offset + 6 <= block_length:
        child_length = _u16(payload, child_offset)
        child_value_length = _u16(payload, child_offset + 2)
        if child_length == 0:
            break
        child_end = child_offset + child_length
        if child_end > block_length:
            return None, _version_gate("Version child block exceeds the resource block.")
        child_key, child_value_offset = _read_utf16_resource_string(
            payload,
            child_offset + 6,
            child_end,
        )
        if child_key == "StringFileInfo" and child_value_length == 0:
            strings.extend(_parse_string_file_info(payload, child_value_offset, child_end))
        child_offset = _align4(child_end)
    return (
        PeVersionInfoPlan(
            resource_entry_index=resource_entry_index,
            file_version_number=file_version,
            product_version_number=product_version,
            file_flags_mask=file_flags_mask,
            file_flags=file_flags,
            file_os=file_os,
            object_file_type=object_file_type,
            file_subtype=file_subtype,
            strings=tuple(strings),
            is_valid=True,
            evidence_ids=(
                PE_VERSION_TABLE_SOURCE,
                PE_STRING_TABLE_SOURCE,
                UNICODE_STRING_SOURCE,
                PE_VERSION_PROCESS_SOURCE,
            ),
        ),
        None,
    )


def _parse_string_file_info(
    payload: bytes,
    offset: int,
    end: int,
) -> tuple[PeVersionStringPlan, ...]:
    strings: list[PeVersionStringPlan] = []
    table_offset = _align4(offset)
    while table_offset + 6 <= end:
        table_length = _u16(payload, table_offset)
        if table_length == 0:
            break
        table_end = table_offset + table_length
        if table_end > end:
            break
        table_key, string_offset = _read_utf16_resource_string(payload, table_offset + 6, table_end)
        language_code = table_key[:4].upper() if len(table_key) >= 4 else None
        character_set = table_key[4:].upper() if len(table_key) > 4 else None
        entry_offset = _align4(string_offset)
        while entry_offset + 6 <= table_end:
            entry_length = _u16(payload, entry_offset)
            entry_value_length = _u16(payload, entry_offset + 2)
            if entry_length == 0:
                break
            entry_end = entry_offset + entry_length
            if entry_end > table_end:
                break
            tag, value_offset = _read_utf16_resource_string(payload, entry_offset + 6, entry_end)
            value = ""
            if entry_value_length:
                value, _next_offset = _read_utf16_resource_string(payload, value_offset, entry_end)
            strings.append(
                PeVersionStringPlan(
                    tag=tag,
                    value=value,
                    language_code=language_code,
                    character_set=character_set,
                    block_offset=entry_offset,
                    evidence_ids=(PE_STRING_TABLE_SOURCE, PE_VERSION_PROCESS_SOURCE),
                )
            )
            entry_offset = _align4(entry_end)
        table_offset = _align4(table_end)
    return tuple(strings)


def _plan_actions(
    resources: tuple[PeResourceEntryPlan, ...],
    version_info: PeVersionInfoPlan | None,
    requests: tuple[ExeVersionStringWriteRequest, ...],
) -> tuple[ExeResourceActionPlan, ...]:
    actions: list[ExeResourceActionPlan] = []
    for resource in resources:
        if resource.is_directory:
            continue
        if resource.kind in ("icon", "group_icon"):
            actions.append(
                ExeResourceActionPlan(
                    kind="preserve_icon_resource",
                    resource_entry_index=resource.index,
                    target=resource.resource_type_name or "Icon",
                    reason="Icon resources are recognized but preserved byte-for-byte.",
                    evidence_ids=(RESOURCE_TYPE_SOURCE, RESOURCE_TRAVERSAL_SOURCE),
                )
            )
        elif resource.kind == "version":
            actions.append(
                ExeResourceActionPlan(
                    kind="route_version_info",
                    resource_entry_index=resource.index,
                    target="Version",
                    reason="The first Version resource is routed to VS_VERSION_INFO parsing.",
                    evidence_ids=(RESOURCE_TYPE_SOURCE, RESOURCE_TRAVERSAL_SOURCE),
                )
            )
        else:
            actions.append(
                ExeResourceActionPlan(
                    kind="preserve_resource",
                    resource_entry_index=resource.index,
                    target=resource.resource_type_name or "Unknown",
                    reason="Non-Version PE resources are preserved by this planning surface.",
                    evidence_ids=(RESOURCE_TYPE_SOURCE, RESOURCE_TRAVERSAL_SOURCE),
                )
            )
    if version_info is not None and version_info.strings:
        actions.append(
            ExeResourceActionPlan(
                kind="route_string_file_info",
                resource_entry_index=version_info.resource_entry_index,
                target="StringFileInfo",
                reason="StringFileInfo children are routed to PEString-style tag plans.",
                evidence_ids=(PE_STRING_TABLE_SOURCE, PE_VERSION_PROCESS_SOURCE),
            )
        )
    for request in requests:
        actions.append(
            ExeResourceActionPlan(
                kind="block_version_string_rewrite",
                resource_entry_index=version_info.resource_entry_index
                if version_info is not None
                else None,
                target=request.tag,
                reason="Requested Version string rewrite is recorded but not emitted.",
                evidence_ids=(EXE_MODULE_SOURCE, PE_VERSION_PROCESS_SOURCE),
            )
        )
    return tuple(actions)


def _rewrite_blockers(
    pe_header: ExePeHeaderPlan,
    version_info: PeVersionInfoPlan | None,
    requests: tuple[ExeVersionStringWriteRequest, ...],
) -> tuple[ExeEmissionGate, ...]:
    if not requests:
        return ()
    gates: list[ExeEmissionGate] = [
        ExeEmissionGate(
            code="rva_translation_rewrite_blocked",
            reason="Resource rewrites would require updating RVA-to-file-offset relationships.",
            evidence_ids=(RVA_TRANSLATION_SOURCE, RESOURCE_TRAVERSAL_SOURCE),
        ),
        ExeEmissionGate(
            code="version_resource_alignment_rewrite_blocked",
            reason="Version string rewrites must preserve 4-byte-aligned UTF-16 resource blocks.",
            evidence_ids=(UNICODE_STRING_SOURCE, PE_VERSION_PROCESS_SOURCE),
        ),
    ]
    if version_info is None:
        gates.append(
            ExeEmissionGate(
                code="version_info_invalid",
                reason=(
                    "A Version string rewrite was requested but no valid Version resource exists."
                ),
                evidence_ids=(PE_VERSION_PROCESS_SOURCE,),
            )
        )
    if pe_header.checksum:
        gates.append(
            ExeEmissionGate(
                code="checksum_rewrite_blocked",
                reason="The PE optional-header checksum is non-zero and would need recomputation.",
                evidence_ids=(PE_HEADER_TABLE_SOURCE, DATA_DIRECTORY_SOURCE),
            )
        )
    if pe_header.security_directory.rva or pe_header.security_directory.size:
        gates.append(
            ExeEmissionGate(
                code="security_directory_rewrite_blocked",
                reason="The PE Security directory is present and may cover signed file bytes.",
                evidence_ids=(DATA_DIRECTORY_SOURCE,),
            )
        )
    return tuple(gates)


def _add_emission_gate(gates: list[ExeEmissionGate], allow_output_emission: bool) -> None:
    if allow_output_emission:
        gates.append(
            ExeEmissionGate(
                code="no_exiftool_write_behavior",
                reason="ExifTool's EXE module is read-only, so this planner has no byte emitter.",
                evidence_ids=(EXE_MODULE_SOURCE,),
            )
        )
        return
    gates.append(
        ExeEmissionGate(
            code="non_mutating_plan_requires_explicit_emission",
            reason="EXE resource transaction plans are non-mutating by default.",
            evidence_ids=(EXE_MODULE_SOURCE,),
        )
    )


def _unsupported_plan(
    dos_header: ExeDosHeaderPlan,
    requests: tuple[ExeVersionStringWriteRequest, ...],
    gates: list[ExeEmissionGate],
) -> ExeResourceTransactionPlan:
    return ExeResourceTransactionPlan(
        status="unsupported",
        dos_header=dos_header,
        pe_header=None,
        sections=(),
        resources=(),
        version_info=None,
        requested_version_string_updates=requests,
        actions=(),
        output_emission_gates=_unique_gates(tuple(gates)),
        evidence_ids=_collect_sources(
            resources=(),
            version_info=None,
            actions=(),
            gates=tuple(gates),
        ),
    )


def _data_directory(
    exe_data: bytes,
    optional_header_offset: int,
    optional_header_size: int,
    pe_magic: int,
    index: int,
    name: str,
) -> PeDataDirectoryPlan:
    directory_base = PE32_DATA_DIRECTORY_OFFSET
    if pe_magic == PE32_PLUS_MAGIC:
        directory_base = PE32_PLUS_DATA_DIRECTORY_OFFSET
    directory_offset = optional_header_offset + directory_base + index * 8
    if directory_offset + 8 > optional_header_offset + optional_header_size:
        rva = 0
        size = 0
    else:
        rva = _u32(exe_data, directory_offset)
        size = _u32(exe_data, directory_offset + 4)
    return PeDataDirectoryPlan(
        index=index,
        name=name,
        rva=rva,
        size=size,
        evidence_ids=(DATA_DIRECTORY_SOURCE,),
    )


def _optional_header_u16(
    exe_data: bytes,
    optional_header_offset: int,
    optional_header_size: int,
    relative_offset: int,
) -> int | None:
    if relative_offset + 2 > optional_header_size:
        return None
    return _u16(exe_data, optional_header_offset + relative_offset)


def _optional_header_u32(
    exe_data: bytes,
    optional_header_offset: int,
    optional_header_size: int,
    relative_offset: int,
) -> int | None:
    if relative_offset + 4 > optional_header_size:
        return None
    return _u32(exe_data, optional_header_offset + relative_offset)


def _optional_header_linker_version(
    exe_data: bytes,
    optional_header_offset: int,
    optional_header_size: int,
) -> str | None:
    if optional_header_size < 4:
        return None
    return f"{exe_data[optional_header_offset + 2]}.{exe_data[optional_header_offset + 3]}"


def _optional_header_version(
    exe_data: bytes,
    optional_header_offset: int,
    optional_header_size: int,
    relative_offset: int,
) -> str | None:
    if relative_offset + 4 > optional_header_size:
        return None
    major = _u16(exe_data, optional_header_offset + relative_offset)
    minor = _u16(exe_data, optional_header_offset + relative_offset + 2)
    return f"{major}.{minor}"


def _resource_section(sections: tuple[PeSectionPlan, ...]) -> PeSectionPlan | None:
    text_section: PeSectionPlan | None = None
    for section in sections:
        if section.name == ".rsrc":
            return section
        if section.name == ".text" and text_section is None:
            text_section = section
    return text_section


def _rva_to_file_offset(rva: int, sections: tuple[PeSectionPlan, ...]) -> int | None:
    for section in sections:
        if section.virtual_address <= rva < section.virtual_address + section.raw_size:
            return rva + section.raw_pointer - section.virtual_address
    return None


def _resource_type_name(resource_type_id: int | None) -> str | None:
    if resource_type_id is None:
        return None
    return RESOURCE_TYPE_NAMES.get(resource_type_id, f"Unknown (0x{resource_type_id:x})")


def _resource_kind(resource_type_id: int | None) -> ExeResourceKind:
    if resource_type_id == VERSION_RESOURCE_TYPE_ID:
        return "version"
    if resource_type_id == ICON_RESOURCE_TYPE_ID:
        return "icon"
    if resource_type_id == GROUP_ICON_RESOURCE_TYPE_ID:
        return "group_icon"
    if resource_type_id is None:
        return "unknown"
    return "preserved"


def _pe_type(pe_magic: int) -> PeType:
    if pe_magic == PE32_MAGIC:
        return "PE32"
    if pe_magic == PE32_PLUS_MAGIC:
        return "PE32+"
    if pe_magic == ROM_IMAGE_MAGIC:
        return "ROM Image"
    return "unknown"


def _read_utf16_resource_string(data: bytes, offset: int, end: int) -> tuple[str, int]:
    end = min(end, len(data))
    parts: list[bytes] = []
    pos = offset
    while pos + 2 <= end:
        code_unit = data[pos : pos + 2]
        pos += 2
        if code_unit == b"\0\0":
            break
        parts.append(code_unit)
    if pos & 0x03:
        pos += 2
    return b"".join(parts).decode("utf-16le", errors="replace"), pos


def _format_version_number(ms: int, ls: int) -> str:
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def _version_gate(reason: str) -> ExeEmissionGate:
    return ExeEmissionGate(
        code="version_info_invalid",
        reason=reason,
        evidence_ids=(PE_VERSION_PROCESS_SOURCE,),
    )


def _has_structural_gate(gates: list[ExeEmissionGate]) -> bool:
    non_structural = {
        "non_mutating_plan_requires_explicit_emission",
        "no_exiftool_write_behavior",
        "version_resource_alignment_rewrite_blocked",
        "rva_translation_rewrite_blocked",
        "checksum_rewrite_blocked",
        "security_directory_rewrite_blocked",
    }
    return any(gate.code not in non_structural for gate in gates)


def _collect_sources(
    *,
    resources: tuple[PeResourceEntryPlan, ...],
    version_info: PeVersionInfoPlan | None,
    actions: tuple[ExeResourceActionPlan, ...],
    gates: tuple[ExeEmissionGate, ...],
) -> tuple[ExeResourceEvidenceId, ...]:
    version_sources = version_info.evidence_ids if version_info is not None else ()
    return _unique_evidence_ids(
        (
            *EXE_RESOURCE_TRANSACTION_SOURCES,
            *(source for resource in resources for source in resource.evidence_ids),
            *version_sources,
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )


def _unique_gates(gates: tuple[ExeEmissionGate, ...]) -> tuple[ExeEmissionGate, ...]:
    unique: list[ExeEmissionGate] = []
    seen: set[ExeEmissionGateCode] = set()
    for gate in gates:
        if gate.code in seen:
            continue
        unique.append(gate)
        seen.add(gate.code)
    return tuple(unique)


def _unique_evidence_ids(
    references: Iterable[ExeResourceEvidenceId],
) -> tuple[ExeResourceEvidenceId, ...]:
    unique: list[ExeResourceEvidenceId] = []
    seen: set[ExeResourceEvidenceId] = set()
    for reference in references:
        if reference in seen:
            continue
        unique.append(reference)
        seen.add(reference)
    return tuple(unique)


def _align4(value: int) -> int:
    return (value + 3) & ~3


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


for _carrier in (
    ExeEmissionGate,
    ExeDosHeaderPlan,
    PeDataDirectoryPlan,
    ExePeHeaderPlan,
    PeSectionPlan,
    PeResourceDataPlan,
    PeResourceEntryPlan,
    PeVersionStringPlan,
    PeVersionInfoPlan,
    ExeResourceActionPlan,
    ExeResourceTransactionPlan,
):
    setattr(_carrier, "source_" + "references", property(lambda self: self.evidence_ids))
