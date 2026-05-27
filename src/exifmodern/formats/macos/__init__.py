"""MacOS metadata transaction planning."""

import calendar
import plistlib
import time
from datetime import datetime
from pathlib import Path

from exifmodern.dispatch_helpers import _graph
from exifmodern.formats.macos.file_create_date_plan import (
    MacOSFileCreateDatePlan,
    build_macos_file_create_date_plan,
)
from exifmodern.formats.macos.mditem_output_plan import (
    MacOSMDItemOutputPlan,
    build_macos_mditem_output_plan,
)
from exifmodern.formats.macos.transaction_plan import (
    MACOS_MAX_RECORD_LENGTH,
    MACOS_SIDECAR_HEADER_LENGTH,
    MACOS_SIDECAR_RECORD_LENGTH,
    MacOSMDItemValue,
    MacOSRewriteRequest,
    MacOSXAttrPayload,
    build_macos_metadata_transaction_plan,
)
from exifmodern.formats.macos.xattr_output_plan import (
    MacOSXAttrOutputPlan,
    build_macos_xattr_output_plan,
)
from exifmodern.formats.macos.xattr_value_plan import (
    MacOSXAttrValuePlan,
    build_macos_xattr_value_plan,
)
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = [
    "MacOSFileCreateDatePlan",
    "MacOSMDItemOutputPlan",
    "MacOSMDItemValue",
    "MacOSRewriteRequest",
    "MacOSXAttrOutputPlan",
    "MacOSXAttrPayload",
    "MacOSXAttrValuePlan",
    "build_macos_file_create_date_plan",
    "build_macos_mditem_output_plan",
    "build_macos_metadata_transaction_plan",
    "build_macos_read_graph",
    "build_macos_xattr_output_plan",
    "build_macos_xattr_value_plan",
    "invoke_macos",
]


def build_macos_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_macos_metadata_transaction_plan(data)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"MacOS package-local reader status: {plan.status}")
    diagnostics.extend(
        f"MacOS package-local reader blocker: {blocker.code}" for blocker in plan.malformed_blockers
    )
    tags: list[ReadTag] = []
    tags.extend(_file_identity_tags(plan.evidence_ids))
    for ordinal, route in enumerate(plan.routes):
        rendered = _route_rendered_value(route.tag_name, route.payload, route.binary)
        tags.append(
            ReadTag(
                name=route.tag_name,
                value=rendered,
                provenance=_macos_provenance(
                    group2=route.group2,
                    table_name="Image::ExifTool::MacOS::Main",
                    tag_id=route.tag_id,
                    evidence_ids=route.evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


type MacOSRenderedValue = str | int | list[str] | BinaryTagValue


def _file_identity_tags(evidence_ids: tuple[str, ...]) -> list[ReadTag]:
    return [
        ReadTag(
            name="FileType",
            value="MacOS",
            provenance=_file_provenance(
                table_name="Image::ExifTool::MacOS::Main",
                tag_id="FileType",
                evidence_ids=evidence_ids,
            ),
            schema=None,
        ),
        ReadTag(
            name="FileTypeExtension",
            value="macos",
            provenance=_file_provenance(
                table_name="Image::ExifTool::MacOS::Main",
                tag_id="FileTypeExtension",
                evidence_ids=evidence_ids,
            ),
            schema=None,
        ),
        ReadTag(
            name="MIMEType",
            value="application/unknown",
            provenance=_file_provenance(
                table_name="Image::ExifTool::MacOS::Main",
                tag_id="MIMEType",
                evidence_ids=evidence_ids,
            ),
            schema=None,
        ),
    ]


def _route_rendered_value(
    tag_name: str,
    payload: bytes,
    binary: bool,
) -> MacOSRenderedValue:
    if not payload:
        return 0
    if tag_name == "RSRC":
        return len(payload)
    if tag_name == "XAttrQuarantine":
        return _render_quarantine(payload)
    if tag_name == "XAttrLastUsedDate":
        return _render_last_used_date(payload)
    if payload.startswith(b"bplist0"):
        decoded = _decode_bplist(payload)
        if decoded is not None:
            return decoded
    if binary:
        return BinaryTagValue(payload)
    return payload.decode("utf-8", errors="replace")


def _render_quarantine(payload: bytes) -> str:
    parts = payload.decode("utf-8", errors="replace").split(";")
    if len(parts) < 3:
        return payload.decode("utf-8", errors="replace")
    timestamp = int(parts[1], 16)
    return f"Flags={parts[0]} set at {_format_utc_time(timestamp)} by {parts[2]}"


def _render_last_used_date(payload: bytes) -> str:
    if len(payload) < 4:
        return payload.decode("utf-8", errors="replace")
    timestamp = int.from_bytes(payload[:4], "little")
    return _format_utc_time(timestamp)


def _decode_bplist(payload: bytes) -> str | list[str] | None:
    try:
        decoded = plistlib.loads(payload)
    except plistlib.InvalidFileException, ValueError, TypeError, OverflowError:
        return None
    if isinstance(decoded, datetime):
        return _format_utc_datetime_as_local(decoded)
    if isinstance(decoded, str):
        return decoded
    if isinstance(decoded, list):
        values: list[str] = []
        for item in decoded:
            if isinstance(item, datetime):
                values.append(_format_utc_datetime_as_local(item))
            elif isinstance(item, str):
                values.append(item)
            else:
                return None
        return values
    return None


def _format_utc_datetime_as_local(value: datetime) -> str:
    return _format_local_time(calendar.timegm(value.timetuple()), include_zone=True)


def _format_local_time(timestamp: int, *, include_zone: bool) -> str:
    parts = time.localtime(timestamp)
    rendered = (
        f"{parts.tm_year:04d}:{parts.tm_mon:02d}:{parts.tm_mday:02d} "
        f"{parts.tm_hour:02d}:{parts.tm_min:02d}:{parts.tm_sec:02d}"
    )
    if not include_zone:
        return rendered
    offset = time.strftime("%z", parts)
    if len(offset) != 5:
        return rendered
    return f"{rendered}{offset[:3]}:{offset[3:]}"


def _format_utc_time(timestamp: int) -> str:
    parts = time.gmtime(timestamp)
    return (
        f"{parts.tm_year:04d}:{parts.tm_mon:02d}:{parts.tm_mday:02d} "
        f"{parts.tm_hour:02d}:{parts.tm_min:02d}:{parts.tm_sec:02d}"
    )


def _macos_provenance(
    *,
    group2: str,
    table_name: str,
    tag_id: str | None,
    evidence_ids: tuple[str, ...],
    duplicate_instance_ordinal: int | None = None,
) -> TagProvenance:
    source = _semantic_source(evidence_ids)
    return TagProvenance(
        group=group2,
        table_name=table_name,
        tag_id=tag_id,
        source=source,
        family_0_group="File",
        family_1_group="MacOS",
        family_2_group=group2,
        duplicate_instance_ordinal=duplicate_instance_ordinal,
    )


def _file_provenance(
    *,
    table_name: str,
    tag_id: str | None,
    evidence_ids: tuple[str, ...],
) -> TagProvenance:
    source = _semantic_source(evidence_ids)
    return TagProvenance(
        group="File",
        table_name=table_name,
        tag_id=tag_id,
        source=source,
        family_0_group="File",
        family_1_group="File",
        family_2_group="Other",
    )


def _semantic_source(evidence_ids: tuple[str, ...]) -> str:
    if not evidence_ids:
        return "package-local-reader-plan"
    return evidence_ids[0]


def invoke_macos(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_macos_read_graph(_read_macos_exiftool_records(path, prefix), source_file)


def _read_macos_exiftool_records(path: Path, prefix: bytes) -> bytes:
    # MacOS.pm reads the AppleDouble header, the entry table, then seeks to each
    # record and reads only records whose declared length is at most 100 MB.
    data = bytearray(prefix)
    with path.open("rb") as file:
        if len(data) < MACOS_SIDECAR_HEADER_LENGTH:
            file.seek(len(data))
            data.extend(file.read(MACOS_SIDECAR_HEADER_LENGTH - len(data)))
        if len(data) < MACOS_SIDECAR_HEADER_LENGTH:
            return bytes(data)
        entries = int.from_bytes(data[0x18:0x1A], "big")
        table_size = entries * MACOS_SIDECAR_RECORD_LENGTH
        table_end = MACOS_SIDECAR_HEADER_LENGTH + table_size
        if len(data) < table_end:
            file.seek(len(data))
            data.extend(file.read(table_end - len(data)))
        if len(data) < table_end:
            return bytes(data)
        for index in range(entries):
            pos = MACOS_SIDECAR_HEADER_LENGTH + index * MACOS_SIDECAR_RECORD_LENGTH
            offset = int.from_bytes(data[pos + 4 : pos + 8], "big")
            length = int.from_bytes(data[pos + 8 : pos + 12], "big")
            if length > MACOS_MAX_RECORD_LENGTH:
                break
            end = offset + length
            if len(data) < end:
                data.extend(b"\0" * (end - len(data)))
            file.seek(offset)
            record = file.read(length)
            data[offset : offset + len(record)] = record
            if len(record) != length:
                break
    return bytes(data)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="macos/appledouble",
        builder_ref="exifmodern.formats.macos:invoke_macos",
        patterns=(Pattern(0, b"\x00\x05\x16\x07"),),
        notes=("AppleDouble v2 magic; ._FILENAME sidecar files",),
    ),
    Signature(
        format_id="macos",
        builder_ref="exifmodern.formats.macos:invoke_macos",
        patterns=(
            Pattern(0, b"\x00\x05\x16\x07"),
            Pattern(6, b"\x00\x00Mac OS X        "),
        ),
        notes=("ExifTool MacOS magic for AppleDouble files carrying Mac OS X metadata.",),
    ),
)
