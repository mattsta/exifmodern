"""Kyocera RAW metadata transaction planning and package-local read API."""

from collections.abc import Mapping
from math import log2
from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.kyocera_raw.metadata_transaction_plan import (
    KYOCERA_RAW_MAKE_BYTES,
    KYOCERA_RAW_MAKE_OFFSET,
    KyoceraRawFieldRewrite,
    KyoceraRawMetadataFieldPlan,
    KyoceraRawMetadataRewriteRequest,
    KyoceraRawMetadataTransactionPlan,
    build_kyocera_raw_metadata_transaction_plan,
)
from exifmodern.json_types import JsonValue
from exifmodern.signature_trie.signature import Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag

__all__ = (
    "KyoceraRawFieldRewrite",
    "KyoceraRawMetadataRewriteRequest",
    "KyoceraRawMetadataTransactionPlan",
    "build_kyocera_raw_metadata_transaction_plan",
    "build_kyocera_raw_read_graph",
    "invoke_kyocera_raw",
    "is_kyocera_raw_prefix",
)


def build_kyocera_raw_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_kyocera_raw_metadata_transaction_plan(data, allow_output_emission=True)
    diagnostics = [
        f"KyoceraRaw package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status != "planned":
        diagnostics.insert(0, f"KyoceraRaw package-local reader status: {plan.status}")

    tags: list[ReadTag] = []

    def add_tag(name: str, value: str | int | float, group: str, tag_id: str) -> None:
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group=group,
                    table_name="Image::ExifTool::KyoceraRaw::Main",
                    tag_id=tag_id,
                    evidence_ids=plan.evidence_ids,
                ),
                schema=None,
            )
        )

    if plan.status == "planned":
        add_tag("FileType", "RAW", "File", "FileType")
        add_tag("FileTypeExtension", "raw", "File", "FileTypeExtension")
        add_tag("MIMEType", "image/x-raw", "File", "MIMEType")
    for field in plan.metadata_fields:
        value = _render_kyocera_field(field.tag_name, field.display_value)
        if isinstance(value, list):
            value = " ".join(str(item) for item in value)
        if isinstance(value, str | int | float):
            add_tag(field.tag_name, value, "KyoceraRaw", str(field.offset))
    _add_kyocera_composite_tags(tags, plan)
    return _graph(source_file, tags, diagnostics)


def invoke_kyocera_raw(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    with path.open("rb") as file:
        data = file.read(156)
    return build_kyocera_raw_read_graph(data, source_file)


def is_kyocera_raw_prefix(prefix: bytes) -> bool:
    return (
        len(prefix) >= 156
        and prefix[KYOCERA_RAW_MAKE_OFFSET : KYOCERA_RAW_MAKE_OFFSET + len(KYOCERA_RAW_MAKE_BYTES)]
        == KYOCERA_RAW_MAKE_BYTES
    )


def _render_kyocera_field(name: str, value: JsonValue) -> JsonValue:
    if name == "ExposureTime" and isinstance(value, float) and value > 0:
        denominator = round(1 / value)
        if denominator > 0 and abs(value - (1 / denominator)) < 0.0001:
            return f"1/{denominator}"
    if name in {"FNumber", "MaxAperture"} and isinstance(value, float):
        return float(f"{value:.2g}")
    return value


def _add_kyocera_composite_tags(
    tags: list[ReadTag], plan: KyoceraRawMetadataTransactionPlan
) -> None:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    fields = {field.tag_name: field for field in plan.metadata_fields}

    def composite(name: str, value: str | int | float) -> None:
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group="Composite",
                    table_name="Image::ExifTool::Composite",
                    tag_id=name,
                    evidence_ids=plan.evidence_ids,
                ),
                schema=None,
            )
        )

    f_number = _number_field(fields, "FNumber")
    exposure_time = _number_field(fields, "ExposureTime")
    focal_length = _number_field(fields, "FocalLength", value_attr="parsed_value")
    white_balance = fields.get("WB_RGGBLevels")
    if f_number is not None:
        composite("Aperture", round(f_number, 1))
    if (
        white_balance is not None
        and isinstance(white_balance.display_value, list)
        and len(white_balance.display_value) >= 4
    ):
        green = _number_value(white_balance.display_value[1])
        red = _number_value(white_balance.display_value[0])
        blue = _number_value(white_balance.display_value[3])
        if green:
            if blue is not None:
                composite("BlueBalance", blue / green)
            if red is not None:
                composite("RedBalance", red / green)
    if exposure_time is not None and exposure_time > 0:
        shutter_speed = _render_kyocera_field("ExposureTime", exposure_time)
        if isinstance(shutter_speed, str | int | float):
            composite("ShutterSpeed", shutter_speed)
    if focal_length is not None:
        composite("FocalLength35efl", f"{focal_length:.1f} mm")
    if f_number is not None and exposure_time is not None and exposure_time > 0:
        composite("LightValue", round(log2((f_number * f_number) / exposure_time), 1))


def _number_field(
    fields: Mapping[str, KyoceraRawMetadataFieldPlan],
    name: str,
    *,
    value_attr: str = "display_value",
) -> float | None:
    field = fields.get(name)
    if field is None:
        return None
    if value_attr == "parsed_value":
        return _number_value(field.parsed_value)
    return _number_value(field.display_value)


def _number_value(value: JsonValue) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="kyocera_raw",
        builder_ref="exifmodern.formats.kyocera_raw:invoke_kyocera_raw",
        patterns=(),
        structural_check="exifmodern.formats.kyocera_raw:is_kyocera_raw_prefix",
        extensions=(".raw",),
    ),
)
