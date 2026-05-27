"""Apple MakerNote adapters for the shared read graph contract."""

from __future__ import annotations

import time
from fractions import Fraction

from exifmodern.formats.apple.makernote_transaction_plan import (
    APPLE_RUNTIME_COMPOSITE_SOURCE,
    AppleByteOrder,
    AppleFieldPlan,
    AppleMakerNoteTransactionPlan,
    AppleRawValue,
    build_apple_makernote_payload_transaction_plan,
    build_apple_makernote_transaction_plan,
)
from exifmodern.formats.apple.plist_bridge import (
    ApplePlistDiagnostic,
    parse_aematrix_plist,
    parse_runtime_plist,
    unsupported_plist_field_diagnostic,
)
from exifmodern.formats.apple.reader import AppleMakerNoteSourceContext
from exifmodern.read_graph import BinaryTagValue, ReadGraph, ReadTag, TagProvenance, TagValue

type AppleRationalPair = tuple[int, int]
type AppleRationalTuple = tuple[AppleRationalPair, ...]


def build_apple_makernote_read_graph(
    maker_note_data: bytes,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    plan = build_apple_makernote_payload_transaction_plan(
        maker_note_data,
        allow_output_emission=True,
    )
    return apple_makernote_transaction_plan_to_read_graph(plan, source_file, generated_at_epoch)


def build_apple_makernote_read_graph_from_exif_tag(
    maker_note_data: bytes,
    source_context: AppleMakerNoteSourceContext,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    """Build an Apple graph from raw EXIF MakerNote tag 0x927c bytes."""

    byte_order = _context_byte_order(maker_note_data, source_context.byte_order)
    if source_context.exif_tag_id != 0x927C:
        plan = build_apple_makernote_transaction_plan(b"", byte_order=byte_order)
        return ReadGraph(
            schema_version=1,
            generated_at_epoch=(
                generated_at_epoch if generated_at_epoch is not None else int(time.time())
            ),
            source_file=source_context.source_file,
            tags=[],
            diagnostics=[
                "Apple package-local reader gate: unsupported_exif_tag: "
                f"expected EXIF tag 0x927c, got 0x{source_context.exif_tag_id:04x}",
                *_diagnostics(plan),
            ],
        )
    if source_context.byte_order is None or maker_note_data.startswith(b"Apple iOS\x00"):
        plan = build_apple_makernote_payload_transaction_plan(
            maker_note_data,
            allow_output_emission=True,
        )
    else:
        plan = build_apple_makernote_transaction_plan(
            maker_note_data,
            byte_order=source_context.byte_order,
            allow_output_emission=True,
        )
    return apple_makernote_transaction_plan_to_read_graph(
        plan,
        source_context.source_file,
        generated_at_epoch,
    )


def apple_makernote_transaction_plan_to_read_graph(
    plan: AppleMakerNoteTransactionPlan,
    source_file: str,
    generated_at_epoch: int | None = None,
) -> ReadGraph:
    epoch = generated_at_epoch if generated_at_epoch is not None else int(time.time())
    return ReadGraph(
        schema_version=1,
        generated_at_epoch=epoch,
        source_file=source_file,
        tags=_read_tags(plan),
        diagnostics=_diagnostics(plan),
    )


def _read_tags(plan: AppleMakerNoteTransactionPlan) -> list[ReadTag]:
    tags: list[ReadTag] = []
    for field in plan.fields:
        if _is_emittable_field(field):
            tags.append(_field_tag(field))
        if field.route == "runtime_subdirectory":
            tags.extend(_runtime_tags(field))
    tags.extend(_composite_tags(tags))
    return tags


def _is_emittable_field(field: AppleFieldPlan) -> bool:
    return field.raw_value is not None and field.route in {"main", "plist_value_conversion"}


def _field_tag(field: AppleFieldPlan) -> ReadTag:
    return ReadTag(
        name=field.tag_name,
        value=_render_value(field),
        provenance=TagProvenance(
            group="MakerNotes",
            table_name="Image::ExifTool::Apple::Main",
            tag_id=str(field.tag_id),
            source=_source_reference_text(field.source_reference_ids[0]),
            family_0_group="MakerNotes",
            family_1_group="Apple",
            family_2_group="Camera" if field.tag_name == "AccelerationVector" else "Image",
        ),
        schema=None,
    )


def _runtime_tags(field: AppleFieldPlan) -> list[ReadTag]:
    runtime_value, diagnostics = parse_runtime_plist(field.raw_payload)
    if diagnostics or runtime_value is None:
        return []
    return [
        _runtime_tag(field, "RunTimeFlags", "flags", _runtime_flags(runtime_value.flags)),
        _runtime_tag(field, "RunTimeValue", "value", runtime_value.value),
        _runtime_tag(field, "RunTimeEpoch", "epoch", runtime_value.epoch),
        _runtime_tag(field, "RunTimeScale", "timescale", runtime_value.timescale),
    ]


def _runtime_tag(
    field: AppleFieldPlan,
    name: str,
    tag_id: str,
    value: TagValue,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="MakerNotes",
            table_name="Image::ExifTool::Apple::RunTime",
            tag_id=tag_id,
            source=_source_reference_text(field.source_reference_ids[-1]),
            family_0_group="MakerNotes",
            family_1_group="Apple",
            family_2_group="Image",
        ),
        schema=None,
    )


def _composite_tags(tags: list[ReadTag]) -> list[ReadTag]:
    runtime_value = _numeric_tag_value(tags, "RunTimeValue")
    runtime_scale = _numeric_tag_value(tags, "RunTimeScale")
    if runtime_value is None or runtime_scale in {None, 0.0}:
        return []
    scale = runtime_scale
    if scale is None:
        return []
    return [
        ReadTag(
            name="RunTimeSincePowerUp",
            value=_duration_string(runtime_value / scale),
            provenance=TagProvenance(
                group="Composite",
                table_name="Image::ExifTool::Apple::Composite",
                tag_id="RunTimeSincePowerUp",
                source=_source_reference_text(APPLE_RUNTIME_COMPOSITE_SOURCE),
                family_0_group="Composite",
                family_1_group="Composite",
                family_2_group="Camera",
            ),
            schema=None,
        )
    ]


def _numeric_tag_value(tags: list[ReadTag], name: str) -> float | None:
    for tag in tags:
        if tag.name != name:
            continue
        value = tag.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)
    return None


def _duration_string(seconds: float) -> str:
    if seconds == 0:
        return "0 s"
    sign = "-" if seconds < 0 else ""
    time_value = abs(seconds)
    if time_value < 30:
        return f"{sign}{time_value:.2f} s"
    rounded = int(time_value + 0.5)
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 24:
        days, hours = divmod(hours, 24)
        return f"{sign}{days} days {hours}:{minutes:02d}:{secs:02d}"
    return f"{sign}{hours}:{minutes:02d}:{secs:02d}"


def _render_value(field: AppleFieldPlan) -> TagValue:
    if field.route == "plist_value_conversion":
        if field.tag_name == "AEMatrix":
            plist_value, diagnostics = parse_aematrix_plist(field.raw_payload)
            if not diagnostics and plist_value is not None:
                return BinaryTagValue(plist_value)
        return BinaryTagValue(field.raw_payload)
    value = field.raw_value
    if value is None:
        return ""
    if field.tag_name in {"AEStable", "AFStable"}:
        return _yes_no(_single_int(value))
    if field.tag_name == "HDRImageType":
        int_value = _single_int(value)
        if int_value is None:
            return _scalar_or_string(value)
        return {3: "HDR Image", 4: "Original Image"}.get(int_value, f"Unknown ({int_value})")
    if field.tag_name == "ImageCaptureType":
        int_value = _single_int(value)
        if int_value is None:
            return _scalar_or_string(value)
        return {
            1: "ProRAW",
            2: "Portrait",
            10: "Photo",
            11: "Manual Focus",
            12: "Scene",
        }.get(int_value, f"Unknown ({int_value})")
    if field.tag_name == "CameraType":
        int_value = _single_int(value)
        if int_value is None:
            return _scalar_or_string(value)
        return {
            0: "Back Wide Angle",
            1: "Back Normal",
            6: "Front",
        }.get(int_value, f"Unknown ({int_value})")
    if field.tag_name == "AFPerformance":
        return _af_performance(value)
    if field.tag_name == "FocusDistanceRange":
        return _focus_distance_range(value)
    if field.tag_name == "AccelerationVector":
        return _rational_tuple_string(value)
    return _scalar_or_string(value)


def _yes_no(value: int | None) -> str | int | None:
    if value == 0:
        return "No"
    if value == 1:
        return "Yes"
    return value


def _runtime_flags(value: int) -> str | int:
    labels = {
        0: "Valid",
        1: "Has been rounded",
        2: "Positive infinity",
        3: "Negative infinity",
        4: "Indefinite",
    }
    names = [label for bit, label in labels.items() if value & (1 << bit)]
    if names:
        return ", ".join(names)
    return value


def _single_int(value: AppleRawValue) -> int | None:
    if isinstance(value, tuple) and len(value) == 1 and isinstance(value[0], int):
        return value[0]
    if isinstance(value, int):
        return value
    return None


def _focus_distance_range(value: AppleRawValue) -> str:
    rational_values = _rational_tuple(value)
    if rational_values is None or len(rational_values) != 2:
        return _rational_tuple_string(value)
    distances = sorted(_fraction_float(item) for item in rational_values)
    return f"{distances[0]:.2f} - {distances[1]:.2f} m"


def _af_performance(value: AppleRawValue) -> str | int:
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or not isinstance(value[0], int)
        or not isinstance(value[1], int)
    ):
        rendered = _scalar_or_string(value)
        if isinstance(rendered, int | str):
            return rendered
        return str(rendered)
    packed_focus = value[1]
    return f"{value[0]} {packed_focus >> 28} {packed_focus & 0x0FFFFFFF}"


def _rational_tuple_string(value: AppleRawValue) -> str:
    rational_values = _rational_tuple(value)
    if rational_values is None:
        rendered = _scalar_or_string(value)
        return str(rendered)
    return " ".join(f"{_fraction_float(item):.10g}" for item in rational_values)


def _rational_tuple(value: AppleRawValue) -> AppleRationalTuple | None:
    if not isinstance(value, tuple):
        return None
    pairs: list[AppleRationalPair] = []
    for item in value:
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], int)
            or not isinstance(item[1], int)
        ):
            return None
        pairs.append((item[0], item[1]))
    return tuple(pairs)


def _fraction_float(value: tuple[int, int]) -> float:
    numerator, denominator = value
    if denominator == 0:
        return 0.0
    return float(Fraction(numerator, denominator))


def _scalar_or_string(value: AppleRawValue) -> TagValue:
    if isinstance(value, tuple):
        if len(value) == 1 and isinstance(value[0], int):
            return value[0]
        if all(isinstance(item, int) for item in value):
            return " ".join(str(item) for item in value)
    if isinstance(value, bytes):
        return BinaryTagValue(value)
    if isinstance(value, str | int):
        return value
    return str(value)


def _diagnostics(plan: AppleMakerNoteTransactionPlan) -> list[str]:
    diagnostics = [
        f"Apple package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
        if gate.code != "non_mutating_plan_requires_explicit_emission"
    ]
    for field in plan.fields:
        diagnostics.extend(_plist_diagnostics(field))
    return diagnostics


def _plist_diagnostics(field: AppleFieldPlan) -> list[str]:
    plist_diagnostics: tuple[ApplePlistDiagnostic, ...] = ()
    if field.route == "runtime_subdirectory":
        _, plist_diagnostics = parse_runtime_plist(field.raw_payload)
    elif field.route == "plist_value_conversion":
        if field.tag_name == "AEMatrix":
            _, plist_diagnostics = parse_aematrix_plist(field.raw_payload)
        else:
            plist_diagnostics = (unsupported_plist_field_diagnostic(field.tag_name),)
    return [
        f"Apple package-local reader diagnostic: {diagnostic.code}: {diagnostic.reason}"
        for diagnostic in plist_diagnostics
    ]


def _source_reference_text(reference_id: str) -> str:
    return reference_id


def _context_byte_order(
    maker_note_data: bytes,
    fallback_byte_order: AppleByteOrder | None,
) -> AppleByteOrder:
    if maker_note_data.startswith(b"Apple iOS\x00"):
        return "little"
    return fallback_byte_order or "little"
