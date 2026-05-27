"""Source-backed 7Z archive scalar reader plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.formats.sevenzip.archive_transaction_plan import (
    SEVENZIP_DISPLAY_FILES_SOURCE,
    SEVENZIP_FILE_INFO_SOURCE,
    SEVENZIP_PROCESS_SOURCE,
    SevenZipArchiveTransactionPlan,
    build_sevenzip_archive_transaction_plan,
)
from exifmodern.json_types import JsonObject

type SevenZipReaderStatus = Literal["planned", "unsupported"]
type SevenZipReaderDiagnosticCode = Literal["malformed_7z_archive", "unsupported_7z_archive"]
type SevenZipScalarValue = str | int | float

SEVENZIP_READER_SOURCES = (
    SEVENZIP_PROCESS_SOURCE,
    SEVENZIP_FILE_INFO_SOURCE,
    SEVENZIP_DISPLAY_FILES_SOURCE,
)
FILETIME_UNIX_EPOCH_OFFSET_SECONDS = 11_644_473_600


@dataclass(frozen=True)
class SevenZipReaderDiagnostic:
    code: SevenZipReaderDiagnosticCode
    detail: str
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class SevenZipReadTag:
    name: str
    group: str
    source_table: str
    tag_id: str
    raw_value: SevenZipScalarValue
    rendered_value: SevenZipScalarValue
    file_index: int | None
    evidence_ids: tuple[str, ...]

    def to_json(self) -> JsonObject:
        return {
            "file_index": self.file_index,
            "group": self.group,
            "name": self.name,
            "raw_value": self.raw_value,
            "rendered_value": self.rendered_value,
            "source_table": self.source_table,
            "tag_id": self.tag_id,
        }


@dataclass(frozen=True)
class SevenZipReaderPlan:
    status: SevenZipReaderStatus
    archive: SevenZipArchiveTransactionPlan
    tags: tuple[SevenZipReadTag, ...]
    diagnostics: tuple[SevenZipReaderDiagnostic, ...]
    evidence_ids: tuple[str, ...]

    @property
    def file_count(self) -> int:
        if self.archive.next_header.database is None:
            return 0
        return len(self.archive.next_header.database.files)

    def tags_by_name(self) -> dict[str, tuple[SevenZipReadTag, ...]]:
        names = {tag.name for tag in self.tags}
        return {name: tuple(tag for tag in self.tags if tag.name == name) for name in names}

    def to_json(self) -> JsonObject:
        return {
            "diagnostics": [diagnostic.to_json() for diagnostic in self.diagnostics],
            "file_count": self.file_count,
            "status": self.status,
            "tags": [tag.to_json() for tag in self.tags],
        }


def build_sevenzip_reader_plan(sevenzip_data: bytes) -> SevenZipReaderPlan:
    archive = build_sevenzip_archive_transaction_plan(sevenzip_data, allow_output_emission=True)
    diagnostics = tuple(
        SevenZipReaderDiagnostic(
            code=(
                "malformed_7z_archive"
                if gate.code.startswith("truncated") or "crc" in gate.code
                else "unsupported_7z_archive"
            ),
            detail=gate.code,
            evidence_ids=gate.evidence_ids,
        )
        for gate in archive.output_emission_gates
    )
    tags: list[SevenZipReadTag] = []
    if archive.start_header.file_version is not None:
        tags.append(
            _tag(
                "FileVersion",
                "FileVersion",
                archive.start_header.file_version,
                archive.start_header.file_version,
                None,
                "Other",
                (SEVENZIP_PROCESS_SOURCE,),
            )
        )
    if archive.next_header.database is not None:
        for file_plan in archive.next_header.database.files:
            if file_plan.modify_date_windows_ticks is not None:
                unix_time = _filetime_to_unix_seconds(file_plan.modify_date_windows_ticks)
                tags.append(
                    _tag(
                        "ModifyDate",
                        "ModifyDate",
                        unix_time,
                        unix_time,
                        file_plan.index,
                        "Time",
                    )
                )
            if file_plan.archived_file_name is not None:
                tags.append(
                    _tag(
                        "ArchivedFileName",
                        "ArchivedFileName",
                        file_plan.archived_file_name,
                        file_plan.archived_file_name,
                        file_plan.index,
                        "Other",
                    )
                )
    return SevenZipReaderPlan(
        status="unsupported" if diagnostics or archive.status == "unsupported" else "planned",
        archive=archive,
        tags=tuple(tags),
        diagnostics=diagnostics,
        evidence_ids=SEVENZIP_READER_SOURCES,
    )


def _tag(
    name: str,
    tag_id: str,
    raw_value: SevenZipScalarValue,
    rendered_value: SevenZipScalarValue,
    file_index: int | None,
    group: str,
    sources: tuple[str, ...] = (SEVENZIP_DISPLAY_FILES_SOURCE,),
) -> SevenZipReadTag:
    return SevenZipReadTag(
        name=name,
        group=group,
        source_table="Image::ExifTool::ZIP::RAR5",
        tag_id=tag_id,
        raw_value=raw_value,
        rendered_value=rendered_value,
        file_index=file_index,
        evidence_ids=sources,
    )


def _filetime_to_unix_seconds(filetime_ticks: int) -> float:
    return filetime_ticks / 10_000_000.0 - FILETIME_UNIX_EPOCH_OFFSET_SECONDS


plan_sevenzip_reader = build_sevenzip_reader_plan


install_evidence_reference_compat(globals())
