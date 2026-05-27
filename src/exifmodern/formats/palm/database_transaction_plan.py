"""Source-grounded, non-mutating Palm/PDB metadata transaction planning."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

PALM_MIN_EXIFTOOL_READ_SIZE = 86
PALM_BASE_HEADER_SIZE = 78
PALM_RECORD_ENTRY_SIZE = 8
PALM_RESOURCE_ENTRY_SIZE = 10
PALM_RESOURCE_DATABASE_ATTRIBUTE = 0x0001
PALM_TIME_OFFSET = (66 * 365 + 17) * 24 * 3600
type PalmEvidenceId = str

PALM_TYPE_NAMES: dict[bytes, str] = {
    b".pdfADBE": "Adobe Reader",
    b"TEXtREAd": "PalmDOC",
    b"BVokBDIC": "BDicty",
    b"DB99DBOS": "DB (Database program)",
    b"PNRdPPrs": "eReader",
    b"DataPPrs": "eReader",
    b"vIMGView": "FireViewer (ImageViewer)",
    b"PmDBPmDB": "HanDBase",
    b"InfoINDB": "InfoView",
    b"ToGoToGo": "iSilo",
    b"SDocSilX": "iSilo 3",
    b"JbDbJBas": "JFile",
    b"JfDbJFil": "JFile Pro",
    b"DATALSdb": "LIST",
    b"Mdb1Mdb1": "MobileDB",
    b"BOOKMOBI": "Mobipocket",
    b"DataPlkr": "Plucker",
    b"DataSprd": "QuickSheet",
    b"SM01SMem": "SuperMemo",
    b"TEXtTlDc": "TealDoc",
    b"InfoTlIf": "TealInfo",
    b"DataTlMl": "TealMeal",
    b"DataTlPt": "TealPaint",
    b"dataTDBP": "ThinkDB",
    b"TdatTide": "Tides",
    b"ToRaTRPW": "TomeRaider",
    b"zTXTGPlm": "Weasel",
    b"BDOCWrdS": "WordSmith",
}

type PalmPlanStatus = Literal["planned", "unsupported"]
type PalmEntryListKind = Literal["record", "resource"]
type PalmAuxiliaryInfoKind = Literal["application_info", "sort_info"]
type PalmActionKind = Literal[
    "preserve_header",
    "preserve_entry_list",
    "preserve_application_info",
    "preserve_sort_info",
    "preserve_record_payload",
    "preserve_resource_payload",
    "preserve_mobi_record_payload",
    "rewrite_header_blocked",
    "rewrite_application_info_blocked",
    "rewrite_sort_info_blocked",
    "rewrite_record_payload_blocked",
    "rewrite_resource_payload_blocked",
]
type PalmEmissionGateCode = Literal[
    "truncated_palm_header",
    "unsupported_palm_type_creator",
    "truncated_entry_list",
    "duplicate_region_offset",
    "region_offset_out_of_range",
    "truncated_mobi_header",
    "invalid_mobi_header",
    "invalid_mobi_extended_header",
    "truncated_mobi_extended_header",
    "header_rewrite_required",
    "application_info_rewrite_required",
    "sort_info_rewrite_required",
    "record_payload_rewrite_required",
    "resource_payload_rewrite_required",
    "planner_is_non_mutating",
]

PALM_TYPE_SOURCE: PalmEvidenceId = "palm.type_table"
PALM_TIME_SOURCE: PalmEvidenceId = "palm.datetime_table"
PALM_MAIN_SOURCE: PalmEvidenceId = "palm.main_table"
PALM_PROCESS_SOURCE: PalmEvidenceId = "palm.process_pdb"
PALM_MOBI_SOURCE: PalmEvidenceId = "palm.process_pdb_mobi"
PALM_EXTH_SOURCE: PalmEvidenceId = "palm.process_pdb_exth"
PALM_EXTH_ENTRY_SOURCE: PalmEvidenceId = "palm.process_exth_entry_loop"
PALM_READ_ONLY_SOURCE: PalmEvidenceId = "palm.read_only_module"

PALM_TRANSACTION_SOURCES = (
    PALM_TYPE_SOURCE,
    PALM_TIME_SOURCE,
    PALM_MAIN_SOURCE,
    PALM_PROCESS_SOURCE,
    PALM_READ_ONLY_SOURCE,
)


@dataclass(frozen=True)
class PalmPayloadMutation:
    index: int
    payload: bytes


@dataclass(frozen=True)
class PalmAuxiliaryInfoMutation:
    kind: PalmAuxiliaryInfoKind
    payload: bytes


@dataclass(frozen=True)
class PalmDatabaseMutationRequest:
    database_name: str | None = None
    attributes: int | None = None
    version: int | None = None
    create_timestamp: int | None = None
    modify_timestamp: int | None = None
    last_backup_timestamp: int | None = None
    database_type: bytes | None = None
    creator: bytes | None = None
    auxiliary_info: tuple[PalmAuxiliaryInfoMutation, ...] = ()
    record_payloads: tuple[PalmPayloadMutation, ...] = ()
    resource_payloads: tuple[PalmPayloadMutation, ...] = ()

    @property
    def has_header_changes(self) -> bool:
        return (
            self.database_name is not None
            or self.attributes is not None
            or self.version is not None
            or self.create_timestamp is not None
            or self.modify_timestamp is not None
            or self.last_backup_timestamp is not None
            or self.database_type is not None
            or self.creator is not None
        )


@dataclass(frozen=True)
class PalmTimestampPlan:
    tag_name: str
    raw_value: int | None
    unix_seconds: int | None
    evidence_ids: tuple[PalmEvidenceId, ...]


@dataclass(frozen=True)
class PalmHeaderPlan:
    database_name: str | None
    raw_database_name: bytes
    attributes: int | None
    version: int | None
    create_timestamp: PalmTimestampPlan
    modify_timestamp: PalmTimestampPlan
    last_backup_timestamp: PalmTimestampPlan
    modification_number: int | None
    application_info_offset: int | None
    sort_info_offset: int | None
    database_type: bytes
    creator: bytes
    type_creator_id: bytes
    recognized_type_name: str | None
    unique_id_seed: int | None
    next_record_list_id: int | None
    entry_count: int | None
    entry_list_kind: PalmEntryListKind | None
    evidence_ids: tuple[PalmEvidenceId, ...]


@dataclass(frozen=True)
class PalmRecordEntryPlan:
    index: int
    table_offset: int
    payload_offset: int
    attributes: int
    unique_id: int
    payload_end_offset: int | None
    payload_length: int | None
    preserved: bool
    evidence_ids: tuple[PalmEvidenceId, ...]


@dataclass(frozen=True)
class PalmResourceEntryPlan:
    index: int
    table_offset: int
    resource_type: bytes
    resource_id: int
    payload_offset: int
    payload_end_offset: int | None
    payload_length: int | None
    preserved: bool
    evidence_ids: tuple[PalmEvidenceId, ...]


@dataclass(frozen=True)
class PalmEntryListPlan:
    kind: PalmEntryListKind | None
    declared_count: int | None
    entry_size: int | None
    list_start_offset: int
    list_end_offset: int | None
    records: tuple[PalmRecordEntryPlan, ...]
    resources: tuple[PalmResourceEntryPlan, ...]
    evidence_ids: tuple[PalmEvidenceId, ...]


@dataclass(frozen=True)
class PalmAuxiliaryInfoPlan:
    kind: PalmAuxiliaryInfoKind
    offset: int | None
    end_offset: int | None
    length: int | None
    present: bool
    preserved: bool
    evidence_ids: tuple[PalmEvidenceId, ...]


@dataclass(frozen=True)
class PalmMobiPlan:
    should_process: bool
    first_record_offset: int | None
    header_length: int | None
    code_page: int | None
    book_name_offset: int | None
    book_name_length: int | None
    book_name: str | None
    exth_present: bool
    exth_offset: int | None
    exth_size: int | None
    exth_entry_count: int | None
    exth_entries_seen: int
    evidence_ids: tuple[PalmEvidenceId, ...]


@dataclass(frozen=True)
class PalmActionPlan:
    kind: PalmActionKind
    byte_range_start: int | None
    byte_range_end: int | None
    input_payload_length: int | None
    planned_payload_length: int | None
    reason: str
    evidence_ids: tuple[PalmEvidenceId, ...]


@dataclass(frozen=True)
class PalmOutputEmissionGate:
    code: PalmEmissionGateCode
    reason: str
    evidence_ids: tuple[PalmEvidenceId, ...]


@dataclass(frozen=True)
class PalmDatabaseTransactionPlan:
    status: PalmPlanStatus
    header: PalmHeaderPlan
    entry_list: PalmEntryListPlan
    application_info: PalmAuxiliaryInfoPlan
    sort_info: PalmAuxiliaryInfoPlan
    mobi: PalmMobiPlan
    actions: tuple[PalmActionPlan, ...]
    output_emission_gates: tuple[PalmOutputEmissionGate, ...]
    evidence_ids: tuple[PalmEvidenceId, ...]
    original_bytes: bytes

    @property
    def can_emit_output(self) -> bool:
        return self.status == "planned" and not self.output_emission_gates

    def emit(self) -> bytes:
        if not self.can_emit_output:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"Palm database transaction output is gated: {gate_codes}")
        return self.original_bytes


@dataclass(frozen=True)
class PalmRegionPlan:
    name: str
    offset: int
    end_offset: int | None
    length: int | None


def build_palm_database_transaction_plan(
    palm_data: bytes,
    *,
    mutation: PalmDatabaseMutationRequest | None = None,
    allow_output_emission: bool = False,
) -> PalmDatabaseTransactionPlan:
    request = mutation if mutation is not None else PalmDatabaseMutationRequest()
    header = build_header_plan(palm_data)
    entry_list = build_entry_list_plan(palm_data, header)
    regions = build_region_plans(palm_data, header, entry_list)
    entry_list = apply_entry_payload_boundaries(entry_list, regions)
    application_info = build_auxiliary_plan(
        "application_info",
        header.application_info_offset,
        regions,
    )
    sort_info = build_auxiliary_plan("sort_info", header.sort_info_offset, regions)
    mobi = build_mobi_plan(palm_data, header)
    gates = validation_gates(palm_data, header, entry_list, regions, mobi)
    actions = build_actions(entry_list, application_info, sort_info, mobi, request)
    gates.extend(rewrite_gates(request))
    if not allow_output_emission:
        gates.append(
            PalmOutputEmissionGate(
                code="planner_is_non_mutating",
                reason="Palm transaction plans preserve input bytes unless emission is allowed.",
                evidence_ids=(PALM_READ_ONLY_SOURCE,),
            )
        )
    status: PalmPlanStatus = "unsupported" if has_blocking_gate(gates) else "planned"
    sources = unique_sources(
        (
            *PALM_TRANSACTION_SOURCES,
            *header.evidence_ids,
            *entry_list.evidence_ids,
            *application_info.evidence_ids,
            *sort_info.evidence_ids,
            *mobi.evidence_ids,
            *(source for action in actions for source in action.evidence_ids),
            *(source for gate in gates for source in gate.evidence_ids),
        )
    )
    return PalmDatabaseTransactionPlan(
        status=status,
        header=header,
        entry_list=entry_list,
        application_info=application_info,
        sort_info=sort_info,
        mobi=mobi,
        actions=actions,
        output_emission_gates=unique_gates(tuple(gates)),
        evidence_ids=sources,
        original_bytes=palm_data,
    )


def build_header_plan(palm_data: bytes) -> PalmHeaderPlan:
    attributes = read_u16be(palm_data, 32)
    version = read_u16be(palm_data, 34)
    database_type = read_bytes(palm_data, 60, 4)
    creator = read_bytes(palm_data, 64, 4)
    type_creator_id = database_type + creator
    entry_count = read_u16be(palm_data, 76)
    entry_list_kind = entry_kind(attributes)
    raw_name = read_bytes(palm_data, 0, 32)
    return PalmHeaderPlan(
        database_name=decode_palm_name(raw_name) if len(raw_name) == 32 else None,
        raw_database_name=raw_name,
        attributes=attributes,
        version=version,
        create_timestamp=timestamp_plan("CreateDate", read_u32be(palm_data, 36)),
        modify_timestamp=timestamp_plan("ModifyDate", read_u32be(palm_data, 40)),
        last_backup_timestamp=timestamp_plan("LastBackupDate", read_u32be(palm_data, 44)),
        modification_number=read_u32be(palm_data, 48),
        application_info_offset=read_u32be(palm_data, 52),
        sort_info_offset=read_u32be(palm_data, 56),
        database_type=database_type,
        creator=creator,
        type_creator_id=type_creator_id,
        recognized_type_name=PALM_TYPE_NAMES.get(type_creator_id),
        unique_id_seed=read_u32be(palm_data, 68),
        next_record_list_id=read_u32be(palm_data, 72),
        entry_count=entry_count,
        entry_list_kind=entry_list_kind,
        evidence_ids=(PALM_MAIN_SOURCE, PALM_PROCESS_SOURCE, PALM_TYPE_SOURCE),
    )


def build_entry_list_plan(palm_data: bytes, header: PalmHeaderPlan) -> PalmEntryListPlan:
    kind = header.entry_list_kind
    declared_count = header.entry_count
    entry_size = entry_size_for_kind(kind)
    list_end = (
        PALM_BASE_HEADER_SIZE + declared_count * entry_size
        if declared_count is not None and entry_size is not None
        else None
    )
    records: list[PalmRecordEntryPlan] = []
    resources: list[PalmResourceEntryPlan] = []
    if kind == "record" and declared_count is not None:
        for index in range(declared_count):
            entry_offset = PALM_BASE_HEADER_SIZE + index * PALM_RECORD_ENTRY_SIZE
            if entry_offset + PALM_RECORD_ENTRY_SIZE > len(palm_data):
                break
            records.append(build_record_entry(palm_data, index, entry_offset))
    if kind == "resource" and declared_count is not None:
        for index in range(declared_count):
            entry_offset = PALM_BASE_HEADER_SIZE + index * PALM_RESOURCE_ENTRY_SIZE
            if entry_offset + PALM_RESOURCE_ENTRY_SIZE > len(palm_data):
                break
            resources.append(build_resource_entry(palm_data, index, entry_offset))
    return PalmEntryListPlan(
        kind=kind,
        declared_count=declared_count,
        entry_size=entry_size,
        list_start_offset=PALM_BASE_HEADER_SIZE,
        list_end_offset=list_end,
        records=tuple(records),
        resources=tuple(resources),
        evidence_ids=(PALM_PROCESS_SOURCE,),
    )


def build_record_entry(palm_data: bytes, index: int, entry_offset: int) -> PalmRecordEntryPlan:
    return PalmRecordEntryPlan(
        index=index,
        table_offset=entry_offset,
        payload_offset=read_required_u32be(palm_data, entry_offset),
        attributes=palm_data[entry_offset + 4],
        unique_id=read_required_u24be(palm_data, entry_offset + 5),
        payload_end_offset=None,
        payload_length=None,
        preserved=True,
        evidence_ids=(PALM_PROCESS_SOURCE,),
    )


def build_resource_entry(palm_data: bytes, index: int, entry_offset: int) -> PalmResourceEntryPlan:
    return PalmResourceEntryPlan(
        index=index,
        table_offset=entry_offset,
        resource_type=palm_data[entry_offset : entry_offset + 4],
        resource_id=read_required_u16be(palm_data, entry_offset + 4),
        payload_offset=read_required_u32be(palm_data, entry_offset + 6),
        payload_end_offset=None,
        payload_length=None,
        preserved=True,
        evidence_ids=(PALM_PROCESS_SOURCE,),
    )


def build_region_plans(
    palm_data: bytes,
    header: PalmHeaderPlan,
    entry_list: PalmEntryListPlan,
) -> tuple[PalmRegionPlan, ...]:
    base_regions: list[tuple[str, int | None]] = [
        ("application_info", header.application_info_offset),
        ("sort_info", header.sort_info_offset),
    ]
    base_regions.extend(
        (f"record:{entry.index}", entry.payload_offset) for entry in entry_list.records
    )
    base_regions.extend(
        (f"resource:{entry.index}", entry.payload_offset) for entry in entry_list.resources
    )
    offsets = sorted({offset for _, offset in base_regions if offset is not None and offset != 0})
    regions: list[PalmRegionPlan] = []
    for name, offset in base_regions:
        if offset is None or offset == 0:
            continue
        end_offset = next_larger_offset(offsets, offset)
        if end_offset is None:
            end_offset = len(palm_data)
        length = end_offset - offset if offset <= end_offset else None
        regions.append(
            PalmRegionPlan(name=name, offset=offset, end_offset=end_offset, length=length)
        )
    return tuple(regions)


def apply_entry_payload_boundaries(
    entry_list: PalmEntryListPlan,
    regions: tuple[PalmRegionPlan, ...],
) -> PalmEntryListPlan:
    records = tuple(
        replace(
            record,
            payload_end_offset=region.end_offset if region is not None else None,
            payload_length=region.length if region is not None else None,
        )
        for record in entry_list.records
        for region in (find_region(regions, f"record:{record.index}"),)
    )
    resources = tuple(
        replace(
            resource,
            payload_end_offset=region.end_offset if region is not None else None,
            payload_length=region.length if region is not None else None,
        )
        for resource in entry_list.resources
        for region in (find_region(regions, f"resource:{resource.index}"),)
    )
    return replace(entry_list, records=records, resources=resources)


def build_auxiliary_plan(
    kind: PalmAuxiliaryInfoKind,
    offset: int | None,
    regions: tuple[PalmRegionPlan, ...],
) -> PalmAuxiliaryInfoPlan:
    region = find_region(regions, kind)
    return PalmAuxiliaryInfoPlan(
        kind=kind,
        offset=offset,
        end_offset=region.end_offset if region is not None else None,
        length=region.length if region is not None else None,
        present=offset is not None and offset != 0,
        preserved=offset is not None and offset != 0 and region is not None,
        evidence_ids=(PALM_MAIN_SOURCE,),
    )


def build_mobi_plan(palm_data: bytes, header: PalmHeaderPlan) -> PalmMobiPlan:
    should_process = header.recognized_type_name == "Mobipocket" and (
        header.entry_count is not None and header.entry_count > 0
    )
    if not should_process:
        return PalmMobiPlan(
            should_process=False,
            first_record_offset=None,
            header_length=None,
            code_page=None,
            book_name_offset=None,
            book_name_length=None,
            book_name=None,
            exth_present=False,
            exth_offset=None,
            exth_size=None,
            exth_entry_count=None,
            exth_entries_seen=0,
            evidence_ids=(PALM_MOBI_SOURCE,),
        )
    first_record_offset = read_u32be(palm_data, 78)
    if first_record_offset is None or first_record_offset + 274 > len(palm_data):
        return empty_mobi_parse(first_record_offset)
    record = palm_data[first_record_offset : first_record_offset + 274]
    if record[16:20] != b"MOBI":
        return empty_mobi_parse(first_record_offset)
    header_length = read_required_u32be(record, 20) + 16
    code_page = read_required_u32be(record, 28)
    book_name_offset = read_required_u32be(record, 84)
    book_name_length = read_required_u32be(record, 88)
    book_name = read_mobi_book_name(
        palm_data,
        first_record_offset,
        book_name_offset,
        book_name_length,
    )
    exth_flag = read_required_u32be(record, 128)
    exth_present = (exth_flag & 0x40) != 0
    if not exth_present:
        return PalmMobiPlan(
            should_process=True,
            first_record_offset=first_record_offset,
            header_length=header_length,
            code_page=code_page,
            book_name_offset=book_name_offset,
            book_name_length=book_name_length,
            book_name=book_name,
            exth_present=False,
            exth_offset=None,
            exth_size=None,
            exth_entry_count=None,
            exth_entries_seen=0,
            evidence_ids=(PALM_MOBI_SOURCE,),
        )
    exth_offset = first_record_offset + header_length
    exth_header = palm_data[exth_offset : exth_offset + 12]
    if len(exth_header) < 12 or exth_header[:4] != b"EXTH":
        return PalmMobiPlan(
            should_process=True,
            first_record_offset=first_record_offset,
            header_length=header_length,
            code_page=code_page,
            book_name_offset=book_name_offset,
            book_name_length=book_name_length,
            book_name=book_name,
            exth_present=True,
            exth_offset=exth_offset,
            exth_size=None,
            exth_entry_count=None,
            exth_entries_seen=0,
            evidence_ids=(PALM_MOBI_SOURCE, PALM_EXTH_SOURCE),
        )
    exth_size = read_required_u32be(exth_header, 4)
    exth_entry_count = read_required_u32be(exth_header, 8)
    exth_entries_seen = count_exth_entries(palm_data[exth_offset + 12 : exth_offset + exth_size])
    return PalmMobiPlan(
        should_process=True,
        first_record_offset=first_record_offset,
        header_length=header_length,
        code_page=code_page,
        book_name_offset=book_name_offset,
        book_name_length=book_name_length,
        book_name=book_name,
        exth_present=True,
        exth_offset=exth_offset,
        exth_size=exth_size,
        exth_entry_count=exth_entry_count,
        exth_entries_seen=exth_entries_seen,
        evidence_ids=(PALM_MOBI_SOURCE, PALM_EXTH_SOURCE, PALM_EXTH_ENTRY_SOURCE),
    )


def empty_mobi_parse(first_record_offset: int | None) -> PalmMobiPlan:
    return PalmMobiPlan(
        should_process=True,
        first_record_offset=first_record_offset,
        header_length=None,
        code_page=None,
        book_name_offset=None,
        book_name_length=None,
        book_name=None,
        exth_present=False,
        exth_offset=None,
        exth_size=None,
        exth_entry_count=None,
        exth_entries_seen=0,
        evidence_ids=(PALM_MOBI_SOURCE,),
    )


def validation_gates(
    palm_data: bytes,
    header: PalmHeaderPlan,
    entry_list: PalmEntryListPlan,
    regions: tuple[PalmRegionPlan, ...],
    mobi: PalmMobiPlan,
) -> list[PalmOutputEmissionGate]:
    gates: list[PalmOutputEmissionGate] = []
    if len(palm_data) < PALM_MIN_EXIFTOOL_READ_SIZE:
        gates.append(
            PalmOutputEmissionGate(
                code="truncated_palm_header",
                reason="Palm.pm requires the initial 86-byte read to succeed.",
                evidence_ids=(PALM_PROCESS_SOURCE,),
            )
        )
    if len(header.type_creator_id) == 8 and header.recognized_type_name is None:
        gates.append(
            PalmOutputEmissionGate(
                code="unsupported_palm_type_creator",
                reason="The 8-byte type/creator ID is absent from the Palm.pm table.",
                evidence_ids=(PALM_TYPE_SOURCE, PALM_PROCESS_SOURCE),
            )
        )
    if entry_list.list_end_offset is not None and entry_list.list_end_offset > len(palm_data):
        gates.append(
            PalmOutputEmissionGate(
                code="truncated_entry_list",
                reason="The declared Palm entry list extends beyond available bytes.",
                evidence_ids=(PALM_PROCESS_SOURCE,),
            )
        )
    gates.extend(region_gates(regions, entry_list.list_end_offset, len(palm_data)))
    gates.extend(mobi_gates(palm_data, mobi))
    return gates


def region_gates(
    regions: tuple[PalmRegionPlan, ...],
    list_end_offset: int | None,
    data_length: int,
) -> list[PalmOutputEmissionGate]:
    gates: list[PalmOutputEmissionGate] = []
    seen_offsets: set[int] = set()
    duplicate_offsets: set[int] = set()
    for region in regions:
        if region.offset in seen_offsets:
            duplicate_offsets.add(region.offset)
        seen_offsets.add(region.offset)
        if list_end_offset is not None and (
            region.offset < list_end_offset or region.offset > data_length
        ):
            gates.append(
                PalmOutputEmissionGate(
                    code="region_offset_out_of_range",
                    reason=f"{region.name} offset {region.offset} is outside the payload area.",
                    evidence_ids=(PALM_PROCESS_SOURCE,),
                )
            )
    for offset in sorted(duplicate_offsets):
        gates.append(
            PalmOutputEmissionGate(
                code="duplicate_region_offset",
                reason=f"Multiple Palm regions begin at offset {offset}.",
                evidence_ids=(PALM_PROCESS_SOURCE,),
            )
        )
    return gates


def mobi_gates(palm_data: bytes, mobi: PalmMobiPlan) -> list[PalmOutputEmissionGate]:
    if not mobi.should_process:
        return []
    if mobi.first_record_offset is None or mobi.first_record_offset + 274 > len(palm_data):
        return [
            PalmOutputEmissionGate(
                code="truncated_mobi_header",
                reason="Palm.pm requires 274 bytes at the first record offset for MOBI.",
                evidence_ids=(PALM_MOBI_SOURCE,),
            )
        ]
    if palm_data[mobi.first_record_offset + 16 : mobi.first_record_offset + 20] != b"MOBI":
        return [
            PalmOutputEmissionGate(
                code="invalid_mobi_header",
                reason="Palm.pm requires the MOBI marker 16 bytes into the first record.",
                evidence_ids=(PALM_MOBI_SOURCE,),
            )
        ]
    if not mobi.exth_present:
        return []
    if mobi.exth_offset is None or mobi.exth_size is None or mobi.exth_size <= 12:
        return [
            PalmOutputEmissionGate(
                code="invalid_mobi_extended_header",
                reason="Palm.pm requires an EXTH marker and a size greater than 12.",
                evidence_ids=(PALM_EXTH_SOURCE,),
            )
        ]
    if mobi.exth_offset + mobi.exth_size > len(palm_data):
        return [
            PalmOutputEmissionGate(
                code="truncated_mobi_extended_header",
                reason="The declared MOBI EXTH header extends beyond available bytes.",
                evidence_ids=(PALM_EXTH_SOURCE,),
            )
        ]
    return []


def rewrite_gates(request: PalmDatabaseMutationRequest) -> list[PalmOutputEmissionGate]:
    gates: list[PalmOutputEmissionGate] = []
    if request.has_header_changes:
        gates.append(
            PalmOutputEmissionGate(
                code="header_rewrite_required",
                reason="Palm header writes are planned but no writer is implemented.",
                evidence_ids=(PALM_MAIN_SOURCE, PALM_READ_ONLY_SOURCE),
            )
        )
    for auxiliary in request.auxiliary_info:
        gates.append(
            PalmOutputEmissionGate(
                code=(
                    "application_info_rewrite_required"
                    if auxiliary.kind == "application_info"
                    else "sort_info_rewrite_required"
                ),
                reason=f"{auxiliary.kind} replacement would require Palm region rebuilding.",
                evidence_ids=(PALM_MAIN_SOURCE, PALM_READ_ONLY_SOURCE),
            )
        )
    if request.record_payloads:
        gates.append(
            PalmOutputEmissionGate(
                code="record_payload_rewrite_required",
                reason="Record payload edits require Palm offset table rebuilding.",
                evidence_ids=(PALM_PROCESS_SOURCE, PALM_READ_ONLY_SOURCE),
            )
        )
    if request.resource_payloads:
        gates.append(
            PalmOutputEmissionGate(
                code="resource_payload_rewrite_required",
                reason="Resource payload edits require Palm offset table rebuilding.",
                evidence_ids=(PALM_PROCESS_SOURCE, PALM_READ_ONLY_SOURCE),
            )
        )
    return gates


def build_actions(
    entry_list: PalmEntryListPlan,
    application_info: PalmAuxiliaryInfoPlan,
    sort_info: PalmAuxiliaryInfoPlan,
    mobi: PalmMobiPlan,
    request: PalmDatabaseMutationRequest,
) -> tuple[PalmActionPlan, ...]:
    actions: list[PalmActionPlan] = [
        PalmActionPlan(
            kind="preserve_header",
            byte_range_start=0,
            byte_range_end=PALM_BASE_HEADER_SIZE,
            input_payload_length=PALM_BASE_HEADER_SIZE,
            planned_payload_length=PALM_BASE_HEADER_SIZE,
            reason="Palm.pm processes the existing header bytes.",
            evidence_ids=(PALM_PROCESS_SOURCE, PALM_MAIN_SOURCE),
        )
    ]
    if entry_list.list_end_offset is not None:
        actions.append(
            PalmActionPlan(
                kind="preserve_entry_list",
                byte_range_start=entry_list.list_start_offset,
                byte_range_end=entry_list.list_end_offset,
                input_payload_length=entry_list.list_end_offset - entry_list.list_start_offset,
                planned_payload_length=entry_list.list_end_offset - entry_list.list_start_offset,
                reason="Palm entry offsets are preserved by this non-mutating plan.",
                evidence_ids=(PALM_PROCESS_SOURCE,),
            )
        )
    actions.extend(auxiliary_actions(application_info, sort_info))
    actions.extend(record_actions(entry_list.records))
    actions.extend(resource_actions(entry_list.resources))
    if mobi.should_process:
        actions.append(
            PalmActionPlan(
                kind="preserve_mobi_record_payload",
                byte_range_start=mobi.first_record_offset,
                byte_range_end=None,
                input_payload_length=None,
                planned_payload_length=None,
                reason="Palm.pm reads MOBI metadata from the first record payload.",
                evidence_ids=(PALM_MOBI_SOURCE,),
            )
        )
    actions.extend(rewrite_actions(request))
    return tuple(actions)


def auxiliary_actions(
    application_info: PalmAuxiliaryInfoPlan,
    sort_info: PalmAuxiliaryInfoPlan,
) -> tuple[PalmActionPlan, ...]:
    actions: list[PalmActionPlan] = []
    for info in (application_info, sort_info):
        if not info.present:
            continue
        actions.append(
            PalmActionPlan(
                kind=(
                    "preserve_application_info"
                    if info.kind == "application_info"
                    else "preserve_sort_info"
                ),
                byte_range_start=info.offset,
                byte_range_end=info.end_offset,
                input_payload_length=info.length,
                planned_payload_length=info.length,
                reason=f"{info.kind} bytes are present and preserved.",
                evidence_ids=info.evidence_ids,
            )
        )
    return tuple(actions)


def record_actions(records: tuple[PalmRecordEntryPlan, ...]) -> tuple[PalmActionPlan, ...]:
    return tuple(
        PalmActionPlan(
            kind="preserve_record_payload",
            byte_range_start=record.payload_offset,
            byte_range_end=record.payload_end_offset,
            input_payload_length=record.payload_length,
            planned_payload_length=record.payload_length,
            reason=f"Record {record.index} payload bytes are preserved.",
            evidence_ids=record.evidence_ids,
        )
        for record in records
    )


def resource_actions(resources: tuple[PalmResourceEntryPlan, ...]) -> tuple[PalmActionPlan, ...]:
    return tuple(
        PalmActionPlan(
            kind="preserve_resource_payload",
            byte_range_start=resource.payload_offset,
            byte_range_end=resource.payload_end_offset,
            input_payload_length=resource.payload_length,
            planned_payload_length=resource.payload_length,
            reason=f"Resource {resource.index} payload bytes are preserved.",
            evidence_ids=resource.evidence_ids,
        )
        for resource in resources
    )


def rewrite_actions(request: PalmDatabaseMutationRequest) -> tuple[PalmActionPlan, ...]:
    actions: list[PalmActionPlan] = []
    if request.has_header_changes:
        actions.append(
            PalmActionPlan(
                kind="rewrite_header_blocked",
                byte_range_start=0,
                byte_range_end=PALM_BASE_HEADER_SIZE,
                input_payload_length=PALM_BASE_HEADER_SIZE,
                planned_payload_length=PALM_BASE_HEADER_SIZE,
                reason="Header change requested; emission is gated until a writer exists.",
                evidence_ids=(PALM_MAIN_SOURCE, PALM_READ_ONLY_SOURCE),
            )
        )
    for auxiliary in request.auxiliary_info:
        actions.append(
            PalmActionPlan(
                kind=(
                    "rewrite_application_info_blocked"
                    if auxiliary.kind == "application_info"
                    else "rewrite_sort_info_blocked"
                ),
                byte_range_start=None,
                byte_range_end=None,
                input_payload_length=None,
                planned_payload_length=len(auxiliary.payload),
                reason=f"{auxiliary.kind} rewrite requested; output is gated.",
                evidence_ids=(PALM_MAIN_SOURCE, PALM_READ_ONLY_SOURCE),
            )
        )
    actions.extend(
        PalmActionPlan(
            kind="rewrite_record_payload_blocked",
            byte_range_start=None,
            byte_range_end=None,
            input_payload_length=None,
            planned_payload_length=len(payload.payload),
            reason=f"Record {payload.index} rewrite requested; output is gated.",
            evidence_ids=(PALM_PROCESS_SOURCE, PALM_READ_ONLY_SOURCE),
        )
        for payload in request.record_payloads
    )
    actions.extend(
        PalmActionPlan(
            kind="rewrite_resource_payload_blocked",
            byte_range_start=None,
            byte_range_end=None,
            input_payload_length=None,
            planned_payload_length=len(payload.payload),
            reason=f"Resource {payload.index} rewrite requested; output is gated.",
            evidence_ids=(PALM_PROCESS_SOURCE, PALM_READ_ONLY_SOURCE),
        )
        for payload in request.resource_payloads
    )
    return tuple(actions)


def timestamp_plan(tag_name: str, raw_value: int | None) -> PalmTimestampPlan:
    unix_seconds = None if raw_value is None else palm_timestamp_to_unix(raw_value)
    return PalmTimestampPlan(
        tag_name=tag_name,
        raw_value=raw_value,
        unix_seconds=unix_seconds,
        evidence_ids=(PALM_TIME_SOURCE, PALM_MAIN_SOURCE),
    )


def palm_timestamp_to_unix(raw_value: int) -> int:
    if raw_value >= PALM_TIME_OFFSET:
        return raw_value - PALM_TIME_OFFSET
    return raw_value


def entry_kind(attributes: int | None) -> PalmEntryListKind | None:
    if attributes is None:
        return None
    if attributes & PALM_RESOURCE_DATABASE_ATTRIBUTE:
        return "resource"
    return "record"


def entry_size_for_kind(kind: PalmEntryListKind | None) -> int | None:
    if kind == "record":
        return PALM_RECORD_ENTRY_SIZE
    if kind == "resource":
        return PALM_RESOURCE_ENTRY_SIZE
    return None


def read_mobi_book_name(
    palm_data: bytes,
    record_offset: int,
    book_name_offset: int,
    book_name_length: int,
) -> str:
    start = record_offset + book_name_offset
    end = start + book_name_length
    if start < 0 or end > len(palm_data):
        return "<err>"
    return palm_data[start:end].decode("utf-8", errors="replace")


def count_exth_entries(payload: bytes) -> int:
    count = 0
    offset = 0
    while offset + 8 <= len(payload):
        length = read_required_u32be(payload, offset + 4)
        if length < 8 or offset + length > len(payload):
            break
        count += 1
        offset += length
    return count


def find_region(regions: tuple[PalmRegionPlan, ...], name: str) -> PalmRegionPlan | None:
    for region in regions:
        if region.name == name:
            return region
    return None


def next_larger_offset(offsets: list[int], offset: int) -> int | None:
    for candidate in offsets:
        if candidate > offset:
            return candidate
    return None


def decode_palm_name(raw_name: bytes) -> str:
    return raw_name.split(b"\x00", 1)[0].decode("latin-1")


def read_bytes(data: bytes, offset: int, length: int) -> bytes:
    if offset + length > len(data):
        return b""
    return data[offset : offset + length]


def read_u16be(data: bytes, offset: int) -> int | None:
    if offset + 2 > len(data):
        return None
    return read_required_u16be(data, offset)


def read_required_u16be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def read_u32be(data: bytes, offset: int) -> int | None:
    if offset + 4 > len(data):
        return None
    return read_required_u32be(data, offset)


def read_required_u24be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 3], "big")


def read_required_u32be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def has_blocking_gate(gates: list[PalmOutputEmissionGate]) -> bool:
    non_blocking = {"planner_is_non_mutating"}
    return any(gate.code not in non_blocking for gate in gates)


def unique_gates(
    gates: tuple[PalmOutputEmissionGate, ...],
) -> tuple[PalmOutputEmissionGate, ...]:
    seen: set[PalmEmissionGateCode] = set()
    unique: list[PalmOutputEmissionGate] = []
    for gate in gates:
        if gate.code in seen:
            continue
        seen.add(gate.code)
        unique.append(gate)
    return tuple(unique)


def unique_sources(sources: tuple[PalmEvidenceId, ...]) -> tuple[PalmEvidenceId, ...]:
    seen: set[PalmEvidenceId] = set()
    unique: list[PalmEvidenceId] = []
    for source in sources:
        if source in seen:
            continue
        seen.add(source)
        unique.append(source)
    return tuple(unique)
