"""QuickTime sample chunk-offset repair for preserved media data.

ExifTool records ``stco``/``co64`` table locations while rebuilding metadata,
computes final ``mdat`` data offsets, then patches table entries that pointed
inside the original media chunks. This module implements only that bounded
sample-table primitive; ItemInfo, GPS, movie-fragment, segment-index, auxiliary,
and CR3 CTBO offset models remain separate blockers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.quicktime.atom_transaction_plan import (
    parse_atom_header,
)

type QuickTimeSampleChunkOffsetAtom = Literal["stco", "co64"]
type QuickTimeSampleChunkOffsetRepairStatus = Literal["ready", "not_needed", "blocked"]
type QuickTimeSampleChunkOffsetBlockerCode = Literal[
    "unsupported_sample_chunk_offset_path",
    "invalid_sample_chunk_offset_table",
    "unsupported_mdat_layout",
    "mdat_payload_changed",
    "sample_chunk_offset_outside_mdat",
    "sample_chunk_offset_negative_after_repair",
    "stco_offset_width_promotion",
]

SUPPORTED_SAMPLE_CHUNK_OFFSET_PATHS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("moov", "trak", "mdia", "minf", "stbl", "stco"),
        ("moov", "trak", "mdia", "minf", "stbl", "co64"),
    }
)
SAMPLE_CHUNK_OFFSET_SCAN_CONTAINERS = frozenset({"moov", "trak", "mdia", "minf", "stbl"})

WRITE_QUICKTIME_OFFSET_DISCOVERY_SOURCE = "quicktime.sample_chunk_offset.discovery"
WRITE_QUICKTIME_CHUNK_OFFSET_RECORD_SOURCE = "quicktime.sample_chunk_offset.record_shape"
WRITE_QUICKTIME_MDAT_POSITION_SOURCE = "quicktime.sample_chunk_offset.mdat_position"
WRITE_QUICKTIME_RECORDED_OFFSET_FIXUP_SOURCE = "quicktime.sample_chunk_offset.fixup"
QUICKTIME_SAMPLE_CHUNK_TABLE_SOURCE = "quicktime.sample_chunk_offset.tables"


@dataclass(frozen=True)
class QuickTimeSampleChunkOffsetTable:
    atom_type: QuickTimeSampleChunkOffsetAtom
    full_path: str
    atom_offset: int
    payload_offset: int
    payload_size: int
    entry_count: int
    entry_size: int

    @property
    def entry_table_offset(self) -> int:
        return self.payload_offset + 8


@dataclass(frozen=True)
class QuickTimeSampleChunkOffsetBlocker:
    code: QuickTimeSampleChunkOffsetBlockerCode
    full_path: str
    message: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class QuickTimeSampleChunkOffsetInspection:
    tables: tuple[QuickTimeSampleChunkOffsetTable, ...]
    blockers: tuple[QuickTimeSampleChunkOffsetBlocker, ...]


@dataclass(frozen=True)
class QuickTimeMdatOffsetDelta:
    index: int
    original_data_offset: int
    original_data_end: int
    rewritten_data_offset: int
    delta: int


@dataclass(frozen=True)
class QuickTimeTopLevelMdatChunk:
    offset: int
    header_size: int
    data_offset: int
    data_size: int | None
    extends_to_eof: bool


@dataclass(frozen=True)
class QuickTimeSampleChunkOffsetEntryRepair:
    full_path: str
    table_entry_offset: int
    atom_type: QuickTimeSampleChunkOffsetAtom
    original_value: int
    repaired_value: int
    mdat_index: int


@dataclass(frozen=True)
class QuickTimeSampleChunkOffsetRepairPlan:
    status: QuickTimeSampleChunkOffsetRepairStatus
    tables: tuple[QuickTimeSampleChunkOffsetTable, ...]
    mdat_deltas: tuple[QuickTimeMdatOffsetDelta, ...]
    entry_repairs: tuple[QuickTimeSampleChunkOffsetEntryRepair, ...]
    blockers: tuple[QuickTimeSampleChunkOffsetBlocker, ...]
    evidence_ids: tuple[str, ...]

    @property
    def supported_for_modern_mutation(self) -> bool:
        return self.status != "blocked"


@dataclass(frozen=True)
class QuickTimeSampleChunkOffsetRepairResult:
    data: bytes
    plan: QuickTimeSampleChunkOffsetRepairPlan

    @property
    def repaired_entry_count(self) -> int:
        return sum(
            entry.original_value != entry.repaired_value for entry in self.plan.entry_repairs
        )


def is_supported_sample_chunk_offset_path(full_path: str) -> bool:
    return tuple(full_path.split("/")) in SUPPORTED_SAMPLE_CHUNK_OFFSET_PATHS


def inspect_sample_chunk_offset_tables(data: bytes) -> QuickTimeSampleChunkOffsetInspection:
    tables, blockers = read_sample_chunk_offset_tables(data, 0, len(data), ())
    return QuickTimeSampleChunkOffsetInspection(tables=tuple(tables), blockers=tuple(blockers))


def plan_sample_chunk_offset_repair(
    original_data: bytes,
    rewritten_data: bytes,
) -> QuickTimeSampleChunkOffsetRepairPlan:
    inspection = inspect_sample_chunk_offset_tables(rewritten_data)
    mdat_deltas, mdat_blockers = compute_mdat_deltas(original_data, rewritten_data)
    blockers = [*inspection.blockers, *mdat_blockers]
    entry_repairs: list[QuickTimeSampleChunkOffsetEntryRepair] = []
    if not blockers:
        for table in inspection.tables:
            repairs, table_blockers = plan_table_entry_repairs(
                rewritten_data,
                table,
                mdat_deltas,
            )
            entry_repairs.extend(repairs)
            blockers.extend(table_blockers)
    entry_repairs_tuple = tuple(entry_repairs)
    blockers_tuple = tuple(blockers)
    status = sample_chunk_offset_repair_status(
        tables=inspection.tables,
        mdat_deltas=mdat_deltas,
        entry_repairs=entry_repairs_tuple,
        blockers=blockers_tuple,
    )
    return QuickTimeSampleChunkOffsetRepairPlan(
        status=status,
        tables=inspection.tables,
        mdat_deltas=tuple(mdat_deltas),
        entry_repairs=entry_repairs_tuple,
        blockers=blockers_tuple,
        evidence_ids=(
            WRITE_QUICKTIME_OFFSET_DISCOVERY_SOURCE,
            WRITE_QUICKTIME_CHUNK_OFFSET_RECORD_SOURCE,
            WRITE_QUICKTIME_MDAT_POSITION_SOURCE,
            WRITE_QUICKTIME_RECORDED_OFFSET_FIXUP_SOURCE,
            QUICKTIME_SAMPLE_CHUNK_TABLE_SOURCE,
        ),
    )


def repair_sample_chunk_offsets_after_rewrite(
    original_data: bytes,
    rewritten_data: bytes,
) -> QuickTimeSampleChunkOffsetRepairResult:
    plan = plan_sample_chunk_offset_repair(original_data, rewritten_data)
    if plan.status == "blocked":
        return QuickTimeSampleChunkOffsetRepairResult(data=rewritten_data, plan=plan)
    patched = bytearray(rewritten_data)
    for entry in plan.entry_repairs:
        width = 8 if entry.atom_type == "co64" else 4
        patched[entry.table_entry_offset : entry.table_entry_offset + width] = (
            entry.repaired_value.to_bytes(width, "big")
        )
    return QuickTimeSampleChunkOffsetRepairResult(data=bytes(patched), plan=plan)


def read_sample_chunk_offset_tables(
    data: bytes,
    start: int,
    end: int,
    parent_path: tuple[str, ...],
) -> tuple[list[QuickTimeSampleChunkOffsetTable], list[QuickTimeSampleChunkOffsetBlocker]]:
    tables: list[QuickTimeSampleChunkOffsetTable] = []
    blockers: list[QuickTimeSampleChunkOffsetBlocker] = []
    cursor = start
    while cursor < end:
        atom_type, size, _header_size, payload_offset, payload_size, _extends_to_eof = (
            parse_atom_header(data, cursor, end)
        )
        path = (*parent_path, atom_type)
        if atom_type in ("stco", "co64"):
            table = parse_sample_chunk_offset_table(
                data,
                sample_chunk_offset_atom(atom_type),
                path,
                cursor,
                payload_offset,
                payload_size,
            )
            if table is None:
                blockers.append(
                    QuickTimeSampleChunkOffsetBlocker(
                        code="invalid_sample_chunk_offset_table",
                        full_path="/".join(path),
                        message=f"Invalid QuickTime sample chunk-offset table at {'/'.join(path)}.",
                        evidence_ids=(
                            WRITE_QUICKTIME_RECORDED_OFFSET_FIXUP_SOURCE,
                            QUICKTIME_SAMPLE_CHUNK_TABLE_SOURCE,
                        ),
                    )
                )
            elif path in SUPPORTED_SAMPLE_CHUNK_OFFSET_PATHS:
                tables.append(table)
            else:
                blockers.append(
                    QuickTimeSampleChunkOffsetBlocker(
                        code="unsupported_sample_chunk_offset_path",
                        full_path="/".join(path),
                        message=(
                            "Only moov/trak/mdia/minf/stbl stco/co64 sample tables are "
                            f"eligible for bounded repair, not {'/'.join(path)}."
                        ),
                        evidence_ids=(WRITE_QUICKTIME_OFFSET_DISCOVERY_SOURCE,),
                    )
                )
        if atom_type in SAMPLE_CHUNK_OFFSET_SCAN_CONTAINERS:
            child_tables, child_blockers = read_sample_chunk_offset_tables(
                data,
                payload_offset,
                payload_offset + payload_size,
                path,
            )
            tables.extend(child_tables)
            blockers.extend(child_blockers)
        cursor += size
    return tables, blockers


def sample_chunk_offset_atom(atom_type: str) -> QuickTimeSampleChunkOffsetAtom:
    if atom_type == "stco":
        return "stco"
    if atom_type == "co64":
        return "co64"
    raise ValueError(f"Unsupported sample chunk offset atom {atom_type!r}.")


def parse_sample_chunk_offset_table(
    data: bytes,
    atom_type: QuickTimeSampleChunkOffsetAtom,
    path: tuple[str, ...],
    atom_offset: int,
    payload_offset: int,
    payload_size: int,
) -> QuickTimeSampleChunkOffsetTable | None:
    if payload_size < 8:
        return None
    entry_size = 8 if atom_type == "co64" else 4
    entry_count = int.from_bytes(data[payload_offset + 4 : payload_offset + 8], "big")
    if payload_size - 8 < entry_count * entry_size:
        return None
    return QuickTimeSampleChunkOffsetTable(
        atom_type=atom_type,
        full_path="/".join(path),
        atom_offset=atom_offset,
        payload_offset=payload_offset,
        payload_size=payload_size,
        entry_count=entry_count,
        entry_size=entry_size,
    )


def compute_mdat_deltas(
    original_data: bytes,
    rewritten_data: bytes,
) -> tuple[list[QuickTimeMdatOffsetDelta], list[QuickTimeSampleChunkOffsetBlocker]]:
    original_mdats = read_top_level_mdat_chunks(original_data)
    rewritten_mdats = read_top_level_mdat_chunks(rewritten_data)
    if len(original_mdats) != len(rewritten_mdats) or not original_mdats:
        return [], [unsupported_mdat_layout_blocker("mdat")]
    deltas: list[QuickTimeMdatOffsetDelta] = []
    blockers: list[QuickTimeSampleChunkOffsetBlocker] = []
    for index, original_mdat in enumerate(original_mdats):
        rewritten_mdat = rewritten_mdats[index]
        if original_mdat.data_size is None or rewritten_mdat.data_size is None:
            blockers.append(unsupported_mdat_layout_blocker("mdat"))
            continue
        original_payload = mdat_payload(original_data, original_mdat)
        rewritten_payload = mdat_payload(rewritten_data, rewritten_mdat)
        if original_payload != rewritten_payload:
            blockers.append(
                QuickTimeSampleChunkOffsetBlocker(
                    code="mdat_payload_changed",
                    full_path="mdat",
                    message=(
                        "Sample chunk-offset repair currently requires preserved mdat payloads."
                    ),
                    evidence_ids=(WRITE_QUICKTIME_MDAT_POSITION_SOURCE,),
                )
            )
            continue
        deltas.append(
            QuickTimeMdatOffsetDelta(
                index=index,
                original_data_offset=original_mdat.data_offset,
                original_data_end=original_mdat.data_offset + original_mdat.data_size,
                rewritten_data_offset=rewritten_mdat.data_offset,
                delta=rewritten_mdat.data_offset - original_mdat.data_offset,
            )
        )
    return deltas, blockers


def unsupported_mdat_layout_blocker(full_path: str) -> QuickTimeSampleChunkOffsetBlocker:
    return QuickTimeSampleChunkOffsetBlocker(
        code="unsupported_mdat_layout",
        full_path=full_path,
        message="Sample chunk-offset repair requires matching finite top-level mdat chunks.",
        evidence_ids=(
            WRITE_QUICKTIME_MDAT_POSITION_SOURCE,
            WRITE_QUICKTIME_RECORDED_OFFSET_FIXUP_SOURCE,
        ),
    )


def read_top_level_mdat_chunks(data: bytes) -> tuple[QuickTimeTopLevelMdatChunk, ...]:
    chunks: list[QuickTimeTopLevelMdatChunk] = []
    cursor = 0
    while cursor < len(data):
        atom_type, size, header_size, payload_offset, payload_size, extends_to_eof = (
            parse_atom_header(data, cursor, len(data))
        )
        if atom_type == "mdat":
            chunks.append(
                QuickTimeTopLevelMdatChunk(
                    offset=cursor,
                    header_size=header_size,
                    data_offset=payload_offset,
                    data_size=None if extends_to_eof else payload_size,
                    extends_to_eof=extends_to_eof,
                )
            )
        cursor += size
    return tuple(chunks)


def mdat_payload(data: bytes, chunk: QuickTimeTopLevelMdatChunk) -> bytes:
    data_size = chunk.data_size
    if data_size is None:
        return b""
    return data[chunk.data_offset : chunk.data_offset + data_size]


def plan_table_entry_repairs(
    data: bytes,
    table: QuickTimeSampleChunkOffsetTable,
    mdat_deltas: list[QuickTimeMdatOffsetDelta],
) -> tuple[
    list[QuickTimeSampleChunkOffsetEntryRepair],
    list[QuickTimeSampleChunkOffsetBlocker],
]:
    repairs: list[QuickTimeSampleChunkOffsetEntryRepair] = []
    blockers: list[QuickTimeSampleChunkOffsetBlocker] = []
    for entry_index in range(table.entry_count):
        entry_offset = table.entry_table_offset + entry_index * table.entry_size
        original_value = int.from_bytes(data[entry_offset : entry_offset + table.entry_size], "big")
        mdat_delta = matching_mdat_delta(original_value, mdat_deltas)
        if mdat_delta is None:
            blockers.append(
                QuickTimeSampleChunkOffsetBlocker(
                    code="sample_chunk_offset_outside_mdat",
                    full_path=table.full_path,
                    message=(
                        f"Sample chunk offset {original_value} in {table.full_path} does not "
                        "point inside preserved media data."
                    ),
                    evidence_ids=(WRITE_QUICKTIME_RECORDED_OFFSET_FIXUP_SOURCE,),
                )
            )
            continue
        repaired_value = original_value + mdat_delta.delta
        if repaired_value < 0:
            blockers.append(
                QuickTimeSampleChunkOffsetBlocker(
                    code="sample_chunk_offset_negative_after_repair",
                    full_path=table.full_path,
                    message=f"Sample chunk offset in {table.full_path} would become negative.",
                    evidence_ids=(WRITE_QUICKTIME_RECORDED_OFFSET_FIXUP_SOURCE,),
                )
            )
        elif table.atom_type == "stco" and repaired_value > 0xFFFFFFFF:
            blockers.append(
                QuickTimeSampleChunkOffsetBlocker(
                    code="stco_offset_width_promotion",
                    full_path=table.full_path,
                    message="ExifTool refuses to promote stco offsets to 64 bits during fixup.",
                    evidence_ids=(WRITE_QUICKTIME_RECORDED_OFFSET_FIXUP_SOURCE,),
                )
            )
        else:
            repairs.append(
                QuickTimeSampleChunkOffsetEntryRepair(
                    full_path=table.full_path,
                    table_entry_offset=entry_offset,
                    atom_type=table.atom_type,
                    original_value=original_value,
                    repaired_value=repaired_value,
                    mdat_index=mdat_delta.index,
                )
            )
    return repairs, blockers


def matching_mdat_delta(
    original_value: int,
    mdat_deltas: list[QuickTimeMdatOffsetDelta],
) -> QuickTimeMdatOffsetDelta | None:
    for delta in mdat_deltas:
        if original_value < delta.original_data_offset or original_value >= delta.original_data_end:
            continue
        return delta
    return None


def sample_chunk_offset_repair_status(
    *,
    tables: tuple[QuickTimeSampleChunkOffsetTable, ...],
    mdat_deltas: list[QuickTimeMdatOffsetDelta],
    entry_repairs: tuple[QuickTimeSampleChunkOffsetEntryRepair, ...],
    blockers: tuple[QuickTimeSampleChunkOffsetBlocker, ...],
) -> QuickTimeSampleChunkOffsetRepairStatus:
    if blockers:
        return "blocked"
    if not tables or not entry_repairs or all(delta.delta == 0 for delta in mdat_deltas):
        return "not_needed"
    return "ready"
