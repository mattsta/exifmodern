"""XMP destination adapter for public Geotag writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exifmodern.file_transaction import (
    BackupPolicy,
    FileWriteTransactionResult,
    write_bytes_in_place_transactionally,
)
from exifmodern.formats.geotag.write_effects import GeotagWriteEffects
from exifmodern.formats.jpeg.xmp_property_writer import (
    JpegXmpPropertyRewriteResult,
    rewrite_jpeg_xmp_properties_creating_if_needed,
)
from exifmodern.formats.xmp.property_write import (
    XmpPropertyDelete,
    XmpPropertySpec,
    XmpPropertyWritePlan,
    XmpPropertyWriteStep,
    XmpTextPropertyWrite,
)
from exifmodern.formats.xmp.sidecar_writer import rewrite_xmp_sidecar_file_properties_in_place
from exifmodern.write_plan import (
    AsciiWriteValue,
    ExifGpsWritePlan,
    RationalArrayWriteValue,
    RationalWriteValue,
)

XMP_EXIF_NAMESPACE = "http://ns.adobe.com/exif/1.0/"

GEOTAG_SET_GEO_VALUES_EVIDENCE_ID = "geotag.xmp.set_geo_values_destination_writes"
GEOTAG_XMP_DOC_EVIDENCE_ID = "geotag.xmp.destination_documentation"
XMP_GPS_TABLE_EVIDENCE_ID = "geotag.xmp.gps_writable_properties"
XMP_GPS_COORDINATE_CONVERSION_EVIDENCE_ID = "geotag.xmp.gps_coordinate_conversion"


@dataclass(frozen=True)
class GeotagXmpSidecarRewriteResult:
    data: bytes
    changed_xmp_properties: int
    deleted_xmp_properties: int
    transaction: FileWriteTransactionResult | None = None


@dataclass(frozen=True)
class GeotagJpegXmpRewriteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    changed_xmp_properties: int
    deleted_xmp_properties: int
    transaction: FileWriteTransactionResult | None = None


def build_geotag_xmp_property_write_plan(effects: GeotagWriteEffects) -> XmpPropertyWritePlan:
    selected_fix = effects.application_result.selected_fix
    if selected_fix is None:
        return geotag_xmp_property_write_plan(
            steps=(),
            generated_specs=GEOTAG_XMP_PROPERTY_SPECS,
        )
    steps: list[XmpTextPropertyWrite] = []
    if selected_fix.latitude is not None:
        steps.append(
            XmpTextPropertyWrite(
                "XMP-exif:GPSLatitude",
                xmp_gps_coordinate_value(selected_fix.latitude, "N", "S"),
            )
        )
    if selected_fix.longitude is not None:
        steps.append(
            XmpTextPropertyWrite(
                "XMP-exif:GPSLongitude",
                xmp_gps_coordinate_value(selected_fix.longitude, "E", "W"),
            )
        )
    if selected_fix.altitude is not None:
        steps.append(XmpTextPropertyWrite("XMP-exif:GPSAltitude", str(abs(selected_fix.altitude))))
        steps.append(
            XmpTextPropertyWrite(
                "XMP-exif:GPSAltitudeRef",
                "1" if selected_fix.altitude < 0 else "0",
            )
        )
    gps_datetime = xmp_gps_datetime_value(effects.application_result.write_plan)
    if gps_datetime is not None:
        steps.append(XmpTextPropertyWrite("XMP-exif:GPSDateTime", gps_datetime))
    if selected_fix.track is not None:
        steps.append(XmpTextPropertyWrite("XMP-exif:GPSTrack", str(selected_fix.track)))
        steps.append(XmpTextPropertyWrite("XMP-exif:GPSTrackRef", "T"))
    if selected_fix.speed is not None:
        steps.append(XmpTextPropertyWrite("XMP-exif:GPSSpeed", str(selected_fix.speed)))
        steps.append(XmpTextPropertyWrite("XMP-exif:GPSSpeedRef", "N"))
    if selected_fix.image_direction is not None:
        steps.append(
            XmpTextPropertyWrite("XMP-exif:GPSImgDirection", str(selected_fix.image_direction))
        )
        steps.append(XmpTextPropertyWrite("XMP-exif:GPSImgDirectionRef", "T"))
    dop_values = selected_fix.gps_dop_write_values()
    if dop_values is not None:
        steps.append(XmpTextPropertyWrite("XMP-exif:GPSMeasureMode", str(dop_values[0])))
        steps.append(XmpTextPropertyWrite("XMP-exif:GPSDOP", str(dop_values[1])))
    return geotag_xmp_property_write_plan(
        steps=tuple(steps),
        generated_specs=GEOTAG_XMP_PROPERTY_SPECS,
    )


def build_delete_geotag_xmp_property_write_plan() -> XmpPropertyWritePlan:
    return geotag_xmp_property_write_plan(
        steps=tuple(XmpPropertyDelete(spec.property_name) for spec in GEOTAG_XMP_PROPERTY_SPECS),
        generated_specs=GEOTAG_XMP_PROPERTY_SPECS,
    )


def rewrite_xmp_sidecar_file_geotag_in_place(
    target_path: Path,
    effects: GeotagWriteEffects,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> GeotagXmpSidecarRewriteResult:
    plan = build_geotag_xmp_property_write_plan(effects)
    result = rewrite_xmp_sidecar_file_properties_in_place(
        target_path,
        plan,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return GeotagXmpSidecarRewriteResult(
        data=result.data,
        changed_xmp_properties=result.changed_xmp_properties,
        deleted_xmp_properties=result.deleted_xmp_properties,
        transaction=result.transaction,
    )


def delete_xmp_sidecar_file_geotag_in_place(
    target_path: Path,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> GeotagXmpSidecarRewriteResult:
    result = rewrite_xmp_sidecar_file_properties_in_place(
        target_path,
        build_delete_geotag_xmp_property_write_plan(),
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return GeotagXmpSidecarRewriteResult(
        data=result.data,
        changed_xmp_properties=result.changed_xmp_properties,
        deleted_xmp_properties=result.deleted_xmp_properties,
        transaction=result.transaction,
    )


def rewrite_jpeg_file_embedded_xmp_geotag_in_place(
    target_path: Path,
    effects: GeotagWriteEffects,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> GeotagJpegXmpRewriteResult:
    result = rewrite_jpeg_xmp_properties_creating_if_needed(
        target_path.read_bytes(),
        build_geotag_xmp_property_write_plan(effects),
    )
    return _jpeg_xmp_rewrite_result_with_transaction(
        target_path,
        result,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )


def delete_jpeg_file_embedded_xmp_geotag_in_place(
    target_path: Path,
    backup_policy: BackupPolicy = "create_backup",
    backup_suffix: str = "_original",
    preserve_file_times: bool = False,
) -> GeotagJpegXmpRewriteResult:
    result = rewrite_jpeg_xmp_properties_creating_if_needed(
        target_path.read_bytes(),
        build_delete_geotag_xmp_property_write_plan(),
    )
    return _jpeg_xmp_rewrite_result_with_transaction(
        target_path,
        result,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )


def _jpeg_xmp_rewrite_result_with_transaction(
    target_path: Path,
    result: JpegXmpPropertyRewriteResult,
    backup_policy: BackupPolicy,
    backup_suffix: str,
    preserve_file_times: bool,
) -> GeotagJpegXmpRewriteResult:
    transaction = write_bytes_in_place_transactionally(
        target_path,
        result.data,
        backup_policy,
        backup_suffix,
        preserve_file_times,
    )
    return GeotagJpegXmpRewriteResult(
        data=result.data,
        original_app1_payload_length=result.original_app1_payload_length,
        rewritten_app1_payload_length=result.rewritten_app1_payload_length,
        changed_xmp_properties=result.changed_xmp_properties,
        deleted_xmp_properties=result.deleted_xmp_properties,
        transaction=transaction,
    )


def xmp_gps_coordinate_value(value: float, positive_ref: str, negative_ref: str) -> str:
    ref = negative_ref if value < 0 else positive_ref
    magnitude = abs(value)
    degrees = int(magnitude)
    minutes = (magnitude - degrees) * 60
    minutes_text = f"{minutes:.8f}".rstrip("0").rstrip(".")
    return f"{degrees},{minutes_text}{ref}"


def xmp_gps_datetime_value(write_plan: ExifGpsWritePlan | None) -> str | None:
    if write_plan is None:
        return None
    date_stamp: str | None = None
    time_stamp: str | None = None
    for step in write_plan.steps:
        if step.tag_name == "GPSDateStamp" and isinstance(step.value, AsciiWriteValue):
            date_stamp = step.value.text
        if step.tag_name == "GPSTimeStamp" and isinstance(step.value, RationalArrayWriteValue):
            time_stamp = xmp_gps_time_from_rationals(step.value)
    if date_stamp is None or time_stamp is None:
        return None
    return f"{date_stamp} {time_stamp}"


def xmp_gps_time_from_rationals(value: RationalArrayWriteValue) -> str | None:
    if len(value.values) != 3:
        return None
    hour = rational_float(value.values[0])
    minute = rational_float(value.values[1])
    second = rational_float(value.values[2])
    if hour is None or minute is None or second is None:
        return None
    second_int = int(second)
    fractional = second - second_int
    suffix = ""
    if fractional > 0:
        suffix = f"{fractional:.6f}"[1:].rstrip("0")
    return f"{int(hour):02d}:{int(minute):02d}:{second_int:02d}{suffix}"


def rational_float(value: RationalWriteValue) -> float | None:
    if value.denominator == 0:
        return None
    return value.numerator / value.denominator


def geotag_xmp_property_spec(property_name: str, element_name: str) -> XmpPropertySpec:
    return XmpPropertySpec(
        property_name=property_name,
        namespace_prefix="exif",
        namespace_uri=XMP_EXIF_NAMESPACE,
        element_name=element_name,
        value_shape="simple_text",
        evidence_ids=(XMP_GPS_TABLE_EVIDENCE_ID,),
    )


def geotag_xmp_property_write_plan(
    *,
    steps: tuple[XmpPropertyWriteStep, ...],
    generated_specs: tuple[XmpPropertySpec, ...],
) -> XmpPropertyWritePlan:
    return XmpPropertyWritePlan(
        steps=steps,
        generated_specs=generated_specs,
        evidence_ids=GEOTAG_XMP_EVIDENCE_IDS,
    )


GEOTAG_XMP_EVIDENCE_IDS = (
    GEOTAG_SET_GEO_VALUES_EVIDENCE_ID,
    GEOTAG_XMP_DOC_EVIDENCE_ID,
    XMP_GPS_TABLE_EVIDENCE_ID,
    XMP_GPS_COORDINATE_CONVERSION_EVIDENCE_ID,
)
GEOTAG_XMP_PROPERTY_SPECS = (
    geotag_xmp_property_spec("XMP-exif:GPSLatitude", "GPSLatitude"),
    geotag_xmp_property_spec("XMP-exif:GPSLongitude", "GPSLongitude"),
    geotag_xmp_property_spec("XMP-exif:GPSAltitude", "GPSAltitude"),
    geotag_xmp_property_spec("XMP-exif:GPSAltitudeRef", "GPSAltitudeRef"),
    geotag_xmp_property_spec("XMP-exif:GPSDateTime", "GPSTimeStamp"),
    geotag_xmp_property_spec("XMP-exif:GPSTrack", "GPSTrack"),
    geotag_xmp_property_spec("XMP-exif:GPSTrackRef", "GPSTrackRef"),
    geotag_xmp_property_spec("XMP-exif:GPSSpeed", "GPSSpeed"),
    geotag_xmp_property_spec("XMP-exif:GPSSpeedRef", "GPSSpeedRef"),
    geotag_xmp_property_spec("XMP-exif:GPSImgDirection", "GPSImgDirection"),
    geotag_xmp_property_spec("XMP-exif:GPSImgDirectionRef", "GPSImgDirectionRef"),
    geotag_xmp_property_spec("XMP-exif:GPSMeasureMode", "GPSMeasureMode"),
    geotag_xmp_property_spec("XMP-exif:GPSDOP", "GPSDOP"),
)
