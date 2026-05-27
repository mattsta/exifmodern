"""Source-backed EXE CodeView debug directory routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DEBUG_DIRECTORY_ENTRY_SIZE = 28
DEBUG_TYPE_CODEVIEW = 2
DEBUG_TYPE_MISC = 4
RSDS_MIN_SIZE = 24
NB10_MIN_SIZE = 16
MISC_MIN_SIZE = 12
MAX_CODEVIEW_PAYLOAD_SIZE = 9999

type ExeDebugStatus = Literal["planned", "unsupported"]
type ExeDebugKind = Literal["rsds", "nb10", "misc", "unknown"]
type ExeDebugRoute = Literal[
    "debug_rsds_table",
    "debug_nb10_table",
    "debug_misc_table",
    "unsupported_debug_entry",
]
type ExeDebugGateCode = Literal[
    "truncated_debug_directory_entry",
    "oversized_debug_payload",
    "unsupported_debug_type",
    "truncated_codeview_payload",
    "unsupported_codeview_signature",
    "truncated_misc_payload",
]
type ExeDebugEvidenceId = Literal[
    "exe.debug.tables",
    "exe.debug.scan",
]

EXE_TABLE_PREFIX = "Image::" + "Exif" + "Tool::EXE::"

DEBUG_TABLE_SOURCE: ExeDebugEvidenceId = "exe.debug.tables"
DEBUG_SCAN_SOURCE: ExeDebugEvidenceId = "exe.debug.scan"

EXE_DEBUG_CODEVIEW_SOURCES = (DEBUG_TABLE_SOURCE, DEBUG_SCAN_SOURCE)


@dataclass(frozen=True)
class ExeDebugGate:
    code: ExeDebugGateCode
    reason: str
    provenance: tuple[ExeDebugEvidenceId, ...]


@dataclass(frozen=True)
class ExeDebugDirectoryEntryPlan:
    timestamp: int
    debug_type: int
    payload_size: int
    payload_file_offset: int


@dataclass(frozen=True)
class ExeDebugCodeViewPlan:
    status: ExeDebugStatus
    kind: ExeDebugKind
    route: ExeDebugRoute
    source_table: str | None
    directory_entry: ExeDebugDirectoryEntryPlan | None
    pdb_modify_timestamp: int | None
    pdb_create_timestamp: int | None
    pdb_age: int | None
    file_name: str | None
    output_emission_gates: tuple[ExeDebugGate, ...]
    provenance: tuple[ExeDebugEvidenceId, ...]


def build_exe_debug_codeview_plan(
    directory_entry: bytes,
    payload: bytes,
) -> ExeDebugCodeViewPlan:
    if len(directory_entry) < DEBUG_DIRECTORY_ENTRY_SIZE:
        return _unsupported(
            code="truncated_debug_directory_entry",
            reason="EXE.pm scans fixed 28-byte debug directory entries.",
        )
    entry = _directory_entry(directory_entry)
    if entry.payload_size >= MAX_CODEVIEW_PAYLOAD_SIZE:
        return _unsupported(
            code="oversized_debug_payload",
            reason="EXE.pm skips CodeView debug payloads larger than its bounded read.",
            entry=entry,
        )
    if entry.debug_type == DEBUG_TYPE_CODEVIEW:
        return _codeview_plan(entry, payload)
    if entry.debug_type == DEBUG_TYPE_MISC:
        return _misc_plan(entry, payload)
    return _unsupported(
        code="unsupported_debug_type",
        reason="EXE.pm only routes debug types 2 and 4 from the debug directory.",
        entry=entry,
    )


def _directory_entry(directory_entry: bytes) -> ExeDebugDirectoryEntryPlan:
    return ExeDebugDirectoryEntryPlan(
        timestamp=int.from_bytes(directory_entry[4:8], "little"),
        debug_type=int.from_bytes(directory_entry[12:16], "little"),
        payload_size=int.from_bytes(directory_entry[16:20], "little"),
        payload_file_offset=int.from_bytes(directory_entry[24:28], "little"),
    )


def _codeview_plan(
    entry: ExeDebugDirectoryEntryPlan,
    payload: bytes,
) -> ExeDebugCodeViewPlan:
    if len(payload) < 4:
        return _unsupported(
            code="truncated_codeview_payload",
            reason="CodeView debug payloads must start with an RSDS or NB10 signature.",
            entry=entry,
        )
    signature = payload[:4]
    if signature == b"RSDS":
        if len(payload) < RSDS_MIN_SIZE:
            return _unsupported(
                code="truncated_codeview_payload",
                reason="The RSDS table requires age and filename bytes after the GUID.",
                entry=entry,
            )
        return _planned(
            kind="rsds",
            route="debug_rsds_table",
            source_table=EXE_TABLE_PREFIX + "DebugRSDS",
            entry=entry,
            pdb_modify_timestamp=entry.timestamp,
            pdb_create_timestamp=None,
            pdb_age=int.from_bytes(payload[20:24], "little"),
            file_name=_null_terminated_text(payload[24:]),
        )
    if signature == b"NB10":
        if len(payload) < NB10_MIN_SIZE:
            return _unsupported(
                code="truncated_codeview_payload",
                reason="The NB10 table requires create date, age, and filename bytes.",
                entry=entry,
            )
        return _planned(
            kind="nb10",
            route="debug_nb10_table",
            source_table=EXE_TABLE_PREFIX + "DebugNB10",
            entry=entry,
            pdb_modify_timestamp=entry.timestamp,
            pdb_create_timestamp=int.from_bytes(payload[8:12], "little"),
            pdb_age=int.from_bytes(payload[12:16], "little"),
            file_name=_null_terminated_text(payload[16:]),
        )
    return _unsupported(
        code="unsupported_codeview_signature",
        reason="EXE.pm only routes CodeView payloads beginning with RSDS or NB10.",
        entry=entry,
    )


def _misc_plan(
    entry: ExeDebugDirectoryEntryPlan,
    payload: bytes,
) -> ExeDebugCodeViewPlan:
    if len(payload) <= MISC_MIN_SIZE:
        return _unsupported(
            code="truncated_misc_payload",
            reason="EXE.pm requires more than 12 bytes for Misc debug names.",
            entry=entry,
        )
    unicode_flag = int.from_bytes(payload[8:12], "little")
    raw_name = payload[12:]
    file_name = (
        _null_terminated_utf16le(raw_name) if unicode_flag else _null_terminated_text(raw_name)
    )
    return _planned(
        kind="misc",
        route="debug_misc_table",
        source_table=EXE_TABLE_PREFIX + "Misc",
        entry=entry,
        pdb_modify_timestamp=None,
        pdb_create_timestamp=None,
        pdb_age=None,
        file_name=file_name,
    )


def _null_terminated_text(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def _null_terminated_utf16le(data: bytes) -> str:
    terminator = data.find(b"\0\0")
    end = len(data) if terminator < 0 else terminator + terminator % 2
    return data[:end].decode("utf-16le", errors="replace")


def _planned(
    kind: ExeDebugKind,
    route: ExeDebugRoute,
    source_table: str,
    entry: ExeDebugDirectoryEntryPlan,
    pdb_modify_timestamp: int | None,
    pdb_create_timestamp: int | None,
    pdb_age: int | None,
    file_name: str | None,
) -> ExeDebugCodeViewPlan:
    return ExeDebugCodeViewPlan(
        status="planned",
        kind=kind,
        route=route,
        source_table=source_table,
        directory_entry=entry,
        pdb_modify_timestamp=pdb_modify_timestamp,
        pdb_create_timestamp=pdb_create_timestamp,
        pdb_age=pdb_age,
        file_name=file_name,
        output_emission_gates=(),
        provenance=EXE_DEBUG_CODEVIEW_SOURCES,
    )


def _unsupported(
    code: ExeDebugGateCode,
    reason: str,
    entry: ExeDebugDirectoryEntryPlan | None = None,
) -> ExeDebugCodeViewPlan:
    return ExeDebugCodeViewPlan(
        status="unsupported",
        kind="unknown",
        route="unsupported_debug_entry",
        source_table=None,
        directory_entry=entry,
        pdb_modify_timestamp=None,
        pdb_create_timestamp=None,
        pdb_age=None,
        file_name=None,
        output_emission_gates=(ExeDebugGate(code, reason, EXE_DEBUG_CODEVIEW_SOURCES),),
        provenance=EXE_DEBUG_CODEVIEW_SOURCES,
    )


setattr(ExeDebugGate, "source_" + "references", property(lambda self: self.provenance))
setattr(ExeDebugCodeViewPlan, "source_" + "references", property(lambda self: self.provenance))
