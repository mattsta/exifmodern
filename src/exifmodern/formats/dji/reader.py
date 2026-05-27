"""Package-local DJI metadata scalar reader surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.dji.metadata_transaction_plan import (
    DJI_INFO_SOURCE,
    DJI_MAIN_SOURCE,
    DJI_SETTINGS_TABLE_SOURCE,
    DJI_THERMAL_SOURCE,
    DJI_XMP_SOURCE,
    DjiEvidenceId,
    DjiMainTagInput,
    DjiMetadataTransactionPlan,
    DjiScalarValue,
    DjiThermalTable,
    build_dji_metadata_transaction_plan,
)


@dataclass(frozen=True)
class DjiReadTag:
    name: str
    value: DjiScalarValue
    group0: str
    group2: str
    source_table: str
    tag_id: str
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[DjiEvidenceId, ...]


@dataclass(frozen=True)
class DjiReadBlocker:
    code: str
    route_kind: str | None
    reason: str
    byte_range: tuple[int, int] | None
    evidence_ids: tuple[DjiEvidenceId, ...]


@dataclass(frozen=True)
class DjiReaderResult:
    plan: DjiMetadataTransactionPlan
    tags: tuple[DjiReadTag, ...]
    blockers: tuple[DjiReadBlocker, ...]


def read_dji_metadata_scalars(
    *,
    main_entries: tuple[DjiMainTagInput, ...] = (),
    main_payload: bytes | None = None,
    info_payload: bytes | None = None,
    info_dir_start: int = 0,
    info_dir_len: int | None = None,
    settings_payload: bytes | None = None,
    thermal_payload: bytes | None = None,
    thermal_table: DjiThermalTable = "ThermalParams",
    xmp_properties: dict[str, DjiScalarValue] | None = None,
) -> DjiReaderResult:
    plan = build_dji_metadata_transaction_plan(
        main_entries=main_entries,
        main_payload=main_payload,
        info_payload=info_payload,
        info_dir_start=info_dir_start,
        info_dir_len=info_dir_len,
        settings_payload=settings_payload,
        thermal_payload=thermal_payload,
        thermal_table=thermal_table,
        xmp_properties=xmp_properties,
        allow_output_emission=True,
    )
    tags: list[DjiReadTag] = []
    for route in plan.main_routes:
        if route.value is not None:
            tags.append(
                _tag(
                    route.tag_name,
                    route.value,
                    "MakerNotes",
                    "Camera",
                    "Main",
                    route.source_name,
                    route.byte_range,
                    route.evidence_ids or (DJI_MAIN_SOURCE,),
                )
            )
    for route in plan.info_routes:
        if route.value is not None:
            tags.append(
                _tag(
                    route.tag_name,
                    route.value,
                    "MakerNotes",
                    "Camera",
                    "Info",
                    route.source_name,
                    route.byte_range,
                    route.evidence_ids or (DJI_INFO_SOURCE,),
                )
            )
    for route in plan.settings_routes:
        if route.value is not None:
            tags.append(
                _tag(
                    route.tag_name,
                    route.value,
                    "MakerNotes",
                    "Camera",
                    "Glamour",
                    route.source_name,
                    route.byte_range,
                    route.evidence_ids or (DJI_SETTINGS_TABLE_SOURCE,),
                )
            )
    for field in plan.thermal_fields:
        tags.append(
            _tag(
                field.tag_name,
                field.value,
                "APP4",
                "Image",
                field.table,
                f"0x{field.offset:02x}",
                field.byte_range,
                field.evidence_ids or (DJI_THERMAL_SOURCE,),
            )
        )
    for route in plan.xmp_routes:
        if route.value is not None:
            tags.append(
                _tag(
                    route.tag_name,
                    route.value,
                    "XMP",
                    _group2_for_responsibility(route.responsibility),
                    "XMP",
                    route.source_name,
                    route.byte_range,
                    route.evidence_ids or (DJI_XMP_SOURCE,),
                )
            )
    blockers = tuple(
        DjiReadBlocker(
            blocker.code,
            blocker.route_kind,
            blocker.reason,
            blocker.byte_range,
            blocker.evidence_ids,
        )
        for blocker in plan.blockers
    )
    return DjiReaderResult(plan=plan, tags=tuple(tags), blockers=blockers)


def _tag(
    name: str,
    value: DjiScalarValue,
    group0: str,
    group2: str,
    table_suffix: str,
    tag_id: str,
    byte_range: tuple[int, int] | None,
    evidence_ids: tuple[DjiEvidenceId, ...],
) -> DjiReadTag:
    return DjiReadTag(
        name=name,
        value=value,
        group0=group0,
        group2=group2,
        source_table=f"Image::ExifTool::DJI::{table_suffix}",
        tag_id=tag_id,
        byte_range=byte_range,
        evidence_ids=evidence_ids,
    )


def _group2_for_responsibility(responsibility: str) -> str:
    if responsibility == "gps_metadata":
        return "Location"
    if responsibility == "time_metadata":
        return "Time"
    if responsibility == "video_metadata":
        return "Video"
    return "Camera"
