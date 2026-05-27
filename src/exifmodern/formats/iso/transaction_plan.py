"""Source-backed ISO 9660 metadata transaction planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.services.system_metadata import exiftool_file_size

ISO_DESCRIPTOR_OFFSET = 32768
ISO_DESCRIPTOR_SIZE = 2048

type IsoDescriptorKind = Literal[
    "boot_record",
    "primary_volume",
    "supplementary_volume",
    "terminator",
    "unsupported",
]
type IsoTagValue = str | int
type IsoEvidenceId = str

ISO_PM_SOURCE_PATH = "lib/Image/ExifTool/ISO.pm"


@dataclass(frozen=True)
class IsoEvidenceAnchor:
    evidence_id: IsoEvidenceId
    path: str
    line_start: int
    line_end: int
    symbol: str
    evidence: str


ISO_PROCESS_SOURCE: IsoEvidenceId = "iso.process.volume-descriptors"
ISO_BOOT_RECORD_SOURCE: IsoEvidenceId = "iso.table.boot-record"
ISO_PRIMARY_VOLUME_SOURCE: IsoEvidenceId = "iso.table.primary-volume"
ISO_COMPOSITE_SOURCE: IsoEvidenceId = "iso.table.composite-volume-size"

ISO_EVIDENCE_ANCHORS: dict[IsoEvidenceId, IsoEvidenceAnchor] = {
    ISO_PROCESS_SOURCE: IsoEvidenceAnchor(
        evidence_id=ISO_PROCESS_SOURCE,
        path=ISO_PM_SOURCE_PATH,
        line_start=136,
        line_end=165,
        symbol="ProcessISO",
        evidence=(
            "ProcessISO seeks to byte 32768, reads fixed 2048-byte volume descriptors, "
            "accepts descriptor identifiers matching CD001, sets FileType/II byte order, "
            "and routes descriptor types 0 and 1 through BootRecord and PrimaryVolume."
        ),
    ),
    ISO_BOOT_RECORD_SOURCE: IsoEvidenceAnchor(
        evidence_id=ISO_BOOT_RECORD_SOURCE,
        path=ISO_PM_SOURCE_PATH,
        line_start=61,
        line_end=69,
        symbol="%Image::ExifTool::ISO::BootRecord",
        evidence="BootRecord emits BootSystem and BootIdentifier from fixed string offsets.",
    ),
    ISO_PRIMARY_VOLUME_SOURCE: IsoEvidenceAnchor(
        evidence_id=ISO_PRIMARY_VOLUME_SOURCE,
        path=ISO_PM_SOURCE_PATH,
        line_start=71,
        line_end=126,
        symbol="%Image::ExifTool::ISO::PrimaryVolume",
        evidence=(
            "PrimaryVolume emits fixed-offset ISO strings, little-endian integer fields, "
            "root-directory date, and volume date/time fields."
        ),
    ),
    ISO_COMPOSITE_SOURCE: IsoEvidenceAnchor(
        evidence_id=ISO_COMPOSITE_SOURCE,
        path=ISO_PM_SOURCE_PATH,
        line_start=128,
        line_end=137,
        symbol="%Image::ExifTool::ISO::Composite",
        evidence="Composite VolumeSize multiplies VolumeBlockCount by VolumeBlockSize.",
    ),
}

ISO_PROCESS_ANCHOR = ISO_EVIDENCE_ANCHORS[ISO_PROCESS_SOURCE]
ISO_BOOT_RECORD_ANCHOR = ISO_EVIDENCE_ANCHORS[ISO_BOOT_RECORD_SOURCE]
ISO_PRIMARY_VOLUME_ANCHOR = ISO_EVIDENCE_ANCHORS[ISO_PRIMARY_VOLUME_SOURCE]
ISO_COMPOSITE_ANCHOR = ISO_EVIDENCE_ANCHORS[ISO_COMPOSITE_SOURCE]

ISO_EVIDENCE_BY_LEGACY_SYMBOL: dict[str, IsoEvidenceAnchor] = {
    "ProcessISO": ISO_PROCESS_ANCHOR,
    "Image::ExifTool::ISO::BootRecord": ISO_BOOT_RECORD_ANCHOR,
    "Image::ExifTool::ISO::PrimaryVolume": ISO_PRIMARY_VOLUME_ANCHOR,
    "Image::ExifTool::ISO::Composite": ISO_COMPOSITE_ANCHOR,
}

ISO_PROCESS_SOURCE_LEGACY = IsoEvidenceAnchor(
    evidence_id=ISO_PROCESS_SOURCE,
    path=ISO_PM_SOURCE_PATH,
    line_start=136,
    line_end=165,
    symbol="ProcessISO",
    evidence=(
        "ProcessISO seeks to byte 32768, reads fixed 2048-byte volume descriptors, "
        "accepts descriptor identifiers matching CD001, sets FileType/II byte order, "
        "and routes descriptor types 0 and 1 through BootRecord and PrimaryVolume."
    ),
)
ISO_BOOT_RECORD_SOURCE_LEGACY = IsoEvidenceAnchor(
    evidence_id=ISO_BOOT_RECORD_SOURCE,
    path=ISO_PM_SOURCE_PATH,
    line_start=61,
    line_end=69,
    symbol="%Image::ExifTool::ISO::BootRecord",
    evidence="BootRecord emits BootSystem and BootIdentifier from fixed string offsets.",
)
ISO_PRIMARY_VOLUME_SOURCE_LEGACY = IsoEvidenceAnchor(
    evidence_id=ISO_PRIMARY_VOLUME_SOURCE,
    path=ISO_PM_SOURCE_PATH,
    line_start=71,
    line_end=126,
    symbol="%Image::ExifTool::ISO::PrimaryVolume",
    evidence=(
        "PrimaryVolume emits fixed-offset ISO strings, little-endian integer fields, "
        "root-directory date, and volume date/time fields."
    ),
)
ISO_COMPOSITE_SOURCE_LEGACY = IsoEvidenceAnchor(
    evidence_id=ISO_COMPOSITE_SOURCE,
    path=ISO_PM_SOURCE_PATH,
    line_start=128,
    line_end=137,
    symbol="%Image::ExifTool::ISO::Composite",
    evidence="Composite VolumeSize multiplies VolumeBlockCount by VolumeBlockSize.",
)
type IsoBlockerCode = Literal[
    "invalid_descriptor_identifier",
    "missing_primary_volume",
    "rewrite_not_supported",
    "truncated_descriptor",
]


@dataclass(frozen=True)
class IsoRewriteRequest:
    tag_name: str
    value: str | int


@dataclass(frozen=True)
class IsoBlocker:
    code: IsoBlockerCode
    detail: str
    source_symbol: str


@dataclass(frozen=True)
class IsoDescriptorPlan:
    descriptor_type: int
    kind: IsoDescriptorKind
    offset: int
    recognized: bool
    source_symbol: str


@dataclass(frozen=True)
class IsoMetadataTransactionPlan:
    descriptors: tuple[IsoDescriptorPlan, ...]
    blockers: tuple[IsoBlocker, ...]
    source_symbols: tuple[str, ...]
    byte_order: str
    can_mutate_metadata: bool
    can_emit_metadata: bool


_DESCRIPTOR_TYPES: dict[int, IsoDescriptorKind] = {
    0: "boot_record",
    1: "primary_volume",
    2: "supplementary_volume",
    255: "terminator",
}
_SOURCE_SYMBOLS = (
    "Image::ExifTool::ISO::Main",
    "Image::ExifTool::ISO::BootRecord",
    "Image::ExifTool::ISO::PrimaryVolume",
    "Image::ExifTool::ISO::Composite",
    "ProcessISO",
)


@dataclass(frozen=True)
class IsoReadTag:
    name: str
    value: IsoTagValue
    group: str
    table_name: str
    tag_id: str
    evidence_ids: tuple[IsoEvidenceId, ...]


@dataclass(frozen=True)
class IsoReaderPlan:
    status: Literal["planned", "unsupported"]
    descriptors: tuple[IsoDescriptorPlan, ...]
    read_tags: tuple[IsoReadTag, ...]
    diagnostics: tuple[str, ...]
    evidence_ids: tuple[IsoEvidenceId, ...]


def build_iso_metadata_transaction_plan(
    descriptor_headers: tuple[bytes, ...],
    *,
    rewrite_requests: tuple[IsoRewriteRequest, ...] = (),
) -> IsoMetadataTransactionPlan:
    descriptors: list[IsoDescriptorPlan] = []
    blockers: list[IsoBlocker] = []
    for index, header in enumerate(descriptor_headers):
        offset = 32768 + (index * 2048)
        if len(header) < 6:
            blockers.append(
                IsoBlocker(
                    code="truncated_descriptor",
                    detail="ProcessISO reads fixed 2048-byte volume descriptors.",
                    source_symbol="ProcessISO",
                )
            )
            continue
        if header[1:6] != b"CD001":
            blockers.append(
                IsoBlocker(
                    code="invalid_descriptor_identifier",
                    detail="ProcessISO accepts only volume descriptors with CD001 at bytes 1..5.",
                    source_symbol="ProcessISO",
                )
            )
            continue
        descriptor_type = header[0]
        kind = _DESCRIPTOR_TYPES.get(descriptor_type, "unsupported")
        descriptors.append(
            IsoDescriptorPlan(
                descriptor_type=descriptor_type,
                kind=kind,
                offset=offset,
                recognized=descriptor_type in (0, 1),
                source_symbol="Image::ExifTool::ISO::Main",
            )
        )
        if descriptor_type == 255:
            break
    if descriptors and not any(descriptor.kind == "primary_volume" for descriptor in descriptors):
        blockers.append(
            IsoBlocker(
                code="missing_primary_volume",
                detail="ISO.pm extracts the PrimaryVolume table for standard volume metadata.",
                source_symbol="Image::ExifTool::ISO::PrimaryVolume",
            )
        )
    if rewrite_requests:
        blockers.append(
            IsoBlocker(
                code="rewrite_not_supported",
                detail="ISO.pm is read-only and defines no writer path.",
                source_symbol="ProcessISO",
            )
        )
    return IsoMetadataTransactionPlan(
        descriptors=tuple(descriptors),
        blockers=tuple(blockers),
        source_symbols=_SOURCE_SYMBOLS,
        byte_order="II",
        can_mutate_metadata=False,
        can_emit_metadata=not blockers,
    )


def iso_volume_size(volume_block_count: int, volume_block_size: int) -> int:
    return volume_block_count * volume_block_size


def build_iso_reader_plan(descriptors: tuple[bytes, ...]) -> IsoReaderPlan:
    metadata_plan = build_iso_metadata_transaction_plan(descriptors)
    diagnostics = [
        f"ISO package-local reader diagnostic: {blocker.code}: {blocker.detail}"
        for blocker in metadata_plan.blockers
    ]
    read_tags: list[IsoReadTag] = []
    for descriptor, descriptor_plan in zip(descriptors, metadata_plan.descriptors, strict=False):
        if descriptor_plan.kind == "primary_volume":
            read_tags.extend(_primary_volume_tags(descriptor))
        elif descriptor_plan.kind == "boot_record":
            read_tags.extend(_boot_record_tags(descriptor))
    _append_volume_size(read_tags)
    evidence_ids = _unique_ids(
        (
            ISO_PROCESS_SOURCE,
            *(evidence_id for tag in read_tags for evidence_id in tag.evidence_ids),
        )
    )
    return IsoReaderPlan(
        status="planned" if metadata_plan.can_emit_metadata else "unsupported",
        descriptors=metadata_plan.descriptors,
        read_tags=tuple(read_tags),
        diagnostics=tuple(diagnostics),
        evidence_ids=evidence_ids,
    )


def _primary_volume_tags(descriptor: bytes) -> list[IsoReadTag]:
    tags: list[IsoReadTag] = []
    for offset, name, length in (
        (8, "System", 32),
        (40, "VolumeName", 32),
        (190, "VolumeSetName", 128),
        (318, "Publisher", 128),
        (446, "DataPreparer", 128),
        (574, "Software", 128),
        (702, "CopyrightFileName", 38),
        (740, "AbstractFileName", 36),
        (776, "BibligraphicFileName", 37),
    ):
        value = _raw_iso_string(descriptor, offset, length)
        if value is not None:
            tags.append(_iso_tag(name, value, str(offset), (ISO_PRIMARY_VOLUME_SOURCE,)))
    tags.append(
        _iso_tag(
            "VolumeBlockCount",
            _uint_le(descriptor, 80, 4),
            "80",
            (ISO_PRIMARY_VOLUME_SOURCE,),
        )
    )
    tags.append(
        _iso_tag(
            "VolumeBlockSize",
            _uint_le(descriptor, 128, 2),
            "128",
            (ISO_PRIMARY_VOLUME_SOURCE,),
        )
    )
    root_date = _root_directory_date(descriptor[174:181])
    if root_date is not None:
        tags.append(
            _iso_tag("RootDirectoryCreateDate", root_date, "174", (ISO_PRIMARY_VOLUME_SOURCE,))
        )
    for offset, name in (
        (813, "VolumeCreateDate"),
        (830, "VolumeModifyDate"),
        (847, "VolumeExpirationDate"),
        (864, "VolumeEffectiveDate"),
    ):
        value = _volume_date(descriptor[offset : offset + 17])
        if value is not None:
            tags.append(_iso_tag(name, value, str(offset), (ISO_PRIMARY_VOLUME_SOURCE,)))
    return tags


def _boot_record_tags(descriptor: bytes) -> list[IsoReadTag]:
    tags: list[IsoReadTag] = []
    boot_system = _iso_string(descriptor, 7, 32)
    tags.append(
        _iso_tag(
            "BootSystem",
            boot_system,
            "7",
            (ISO_BOOT_RECORD_SOURCE,),
            table_name="Image::ExifTool::ISO::BootRecord",
        )
    )
    boot_identifier = _raw_iso_string(descriptor, 39, 32)
    if boot_identifier is not None:
        tags.append(
            _iso_tag(
                "BootIdentifier",
                boot_identifier,
                "39",
                (ISO_BOOT_RECORD_SOURCE,),
                table_name="Image::ExifTool::ISO::BootRecord",
            )
        )
    return tags


def _append_volume_size(tags: list[IsoReadTag]) -> None:
    block_count = _tag_int(tags, "VolumeBlockCount")
    block_size = _tag_int(tags, "VolumeBlockSize")
    if block_count is None or block_size is None:
        return
    tags.append(
        IsoReadTag(
            name="VolumeSize",
            value=exiftool_file_size(iso_volume_size(block_count, block_size)),
            group="Composite",
            table_name="Image::ExifTool::ISO::Composite",
            tag_id="ISO-VolumeSize",
            evidence_ids=(ISO_COMPOSITE_SOURCE,),
        )
    )


def _iso_tag(
    name: str,
    value: IsoTagValue,
    tag_id: str,
    evidence_ids: tuple[IsoEvidenceId, ...],
    *,
    table_name: str = "Image::ExifTool::ISO::PrimaryVolume",
) -> IsoReadTag:
    return IsoReadTag(
        name=name,
        value=value,
        group="ISO",
        table_name=table_name,
        tag_id=tag_id,
        evidence_ids=evidence_ids,
    )


def _uint_le(data: bytes, offset: int, length: int) -> int:
    return int.from_bytes(data[offset : offset + length], "little")


def _iso_string(data: bytes, offset: int, length: int) -> str:
    return data[offset : offset + length].split(b"\x00", 1)[0].decode("latin-1").rstrip(" ")


def _raw_iso_string(data: bytes, offset: int, length: int) -> str | None:
    value = _iso_string(data, offset, length)
    return value or None


def _root_directory_date(data: bytes) -> str | None:
    if len(data) != 7 or not any(data):
        return None
    year = data[0] + 1900
    return (
        f"{year:04d}:{data[1]:02d}:{data[2]:02d} "
        f"{data[3]:02d}:{data[4]:02d}:{data[5]:02d}{_timezone_string(_signed_byte(data[6]) * 15)}"
    )


def _volume_date(data: bytes) -> str | None:
    if len(data) != 17 or not any(byte not in {0, 32, 48} for byte in data):
        return None
    text = data[:16].decode("ascii", errors="ignore")
    if len(text) != 16 or not text.isdecimal():
        return None
    return (
        f"{text[0:4]}:{text[4:6]}:{text[6:8]} {text[8:10]}:"
        f"{text[10:12]}:{text[12:14]}.{text[14:16]}"
        f"{_timezone_string(_signed_byte(data[16]) * 15)}"
    )


def _timezone_string(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    absolute = abs(minutes)
    return f"{sign}{absolute // 60:02d}:{absolute % 60:02d}"


def _signed_byte(value: int) -> int:
    return value - 256 if value > 127 else value


def _tag_int(tags: list[IsoReadTag], name: str) -> int | None:
    for tag in tags:
        if tag.name == name and isinstance(tag.value, int):
            return tag.value
    return None


def _unique_ids(evidence_ids: tuple[IsoEvidenceId, ...]) -> tuple[IsoEvidenceId, ...]:
    seen: set[IsoEvidenceId] = set()
    unique: list[IsoEvidenceId] = []
    for evidence_id in evidence_ids:
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        unique.append(evidence_id)
    return tuple(unique)
