"""Runtime rendering for maker-note PrintConv maps and scalar expressions."""

from __future__ import annotations

import json
from pathlib import Path

from exifmodern.formats.maker_notes.context import (
    EMPTY_MAKER_NOTE_RUNTIME_CONTEXT,
    MakerNoteRuntimeBoundary,
    MakerNoteRuntimeContext,
)
from exifmodern.services.maker_note_database import print_fuji_panasonic as _print_fuji_panasonic
from exifmodern.services.maker_note_database import print_helpers as _print_helpers
from exifmodern.services.maker_note_database import print_models as _print_models
from exifmodern.services.maker_note_database import print_nikon as _print_nikon
from exifmodern.services.maker_note_database import print_olympus as _print_olympus
from exifmodern.services.maker_note_database import print_pentax as _print_pentax
from exifmodern.services.maker_note_database import print_scalar as _print_scalar
from exifmodern.services.maker_note_tables import (
    MakerNoteTableRepository,
    MakerNoteTagLocation,
    load_maker_note_table_repository,
)

maker_note_scalar_print_conversion_adapter_supported = (
    _print_scalar.maker_note_scalar_print_conversion_adapter_supported
)
render_scalar_string_print_conversion = _print_scalar.render_scalar_string_print_conversion
decode_bits = _print_scalar.decode_bits
parse_float = _print_scalar.parse_float
parse_int = _print_scalar.parse_int
perl_truthy = _print_scalar.perl_truthy
split_integer_words = _print_scalar.split_integer_words
IndexedPrintConverter = _print_helpers.IndexedPrintConverter
convert_indexed_values = _print_helpers.convert_indexed_values
format_perl_float = _print_helpers.format_perl_float
mapped_float_key_value = _print_helpers.mapped_float_key_value
mapped_integer_value = _print_helpers.mapped_integer_value
mapped_integer_value_with_unknown = _print_helpers.mapped_integer_value_with_unknown
mapped_string_value_with_unknown = _print_helpers.mapped_string_value_with_unknown
is_fuji_main_print_domain_location = _print_fuji_panasonic.is_fuji_main_print_domain_location
fuji_main_print_domain_conversion = _print_fuji_panasonic.fuji_main_print_domain_conversion
fuji_internal_serial_number = _print_fuji_panasonic.fuji_internal_serial_number
pack_hex_string = _print_fuji_panasonic.pack_hex_string
fuji_image_stabilization_type = _print_fuji_panasonic.fuji_image_stabilization_type
fuji_image_stabilization_mode = _print_fuji_panasonic.fuji_image_stabilization_mode
fuji_face_element_type = _print_fuji_panasonic.fuji_face_element_type
is_panasonic_print_domain_location = _print_fuji_panasonic.is_panasonic_print_domain_location
panasonic_print_domain_conversion = _print_fuji_panasonic.panasonic_print_domain_conversion
panasonic_internal_serial_number = _print_fuji_panasonic.panasonic_internal_serial_number
panasonic_time_since_power_on = _print_fuji_panasonic.panasonic_time_since_power_on
is_nikon_print_domain_location = _print_nikon.is_nikon_print_domain_location
is_nikon_z9_self_state_print_location = _print_nikon.is_nikon_z9_self_state_print_location
nikon_print_domain_conversion = _print_nikon.nikon_print_domain_conversion
nikon_z9_self_state_print_conversion = _print_nikon.nikon_z9_self_state_print_conversion
nikon_z9_focus_shift_shooting = _print_nikon.nikon_z9_focus_shift_shooting
nikon_z9_af_area_initial_x_position = _print_nikon.nikon_z9_af_area_initial_x_position
nikon_z9_af_area_initial_y_position = _print_nikon.nikon_z9_af_area_initial_y_position
perl_round = _print_nikon.perl_round
print_lens_info = _print_nikon.print_lens_info
is_float_text = _print_nikon.is_float_text
NIKON_RETOUCH_VALUES = _print_nikon.NIKON_RETOUCH_VALUES
nikon_retouch_history_print = _print_nikon.nikon_retouch_history_print
nikon_format_string = _print_nikon.nikon_format_string
is_olympus_print_domain_location = _print_olympus.is_olympus_print_domain_location
is_olympus_model_dependent_custom_saturation_location = (
    _print_olympus.is_olympus_model_dependent_custom_saturation_location
)
is_olympus_camera_type_quality_location = _print_olympus.is_olympus_camera_type_quality_location
olympus_print_domain_conversion = _print_olympus.olympus_print_domain_conversion
olympus_custom_saturation = _print_olympus.olympus_custom_saturation
OLYMPUS_QUALITY_SX = _print_olympus.OLYMPUS_QUALITY_SX
OLYMPUS_QUALITY_DEFAULT = _print_olympus.OLYMPUS_QUALITY_DEFAULT
olympus_quality = _print_olympus.olympus_quality
olympus_camera_settings_array_print = _print_olympus.olympus_camera_settings_array_print
OLYMPUS_FILTERS = _print_olympus.OLYMPUS_FILTERS
OLYMPUS_PICTURE_MODE = _print_olympus.OLYMPUS_PICTURE_MODE
OLYMPUS_ISO_AUTO = _print_olympus.OLYMPUS_ISO_AUTO
olympus_first_value_map = _print_olympus.olympus_first_value_map
olympus_first_value_filter = _print_olympus.olympus_first_value_filter
olympus_focus_mode = _print_olympus.olympus_focus_mode
olympus_focus_mode_primary = _print_olympus.olympus_focus_mode_primary
olympus_focus_mode_secondary = _print_olympus.olympus_focus_mode_secondary
olympus_gradation = _print_olympus.olympus_gradation
olympus_tone_level = _print_olympus.olympus_tone_level
olympus_art_filter_effect = _print_olympus.olympus_art_filter_effect
olympus_indexed_prefixes = _print_olympus.olympus_indexed_prefixes
olympus_monochrome_profile_settings = _print_olympus.olympus_monochrome_profile_settings
olympus_iso_auto_value = _print_olympus.olympus_iso_auto_value
olympus_multiple_exposure_mode = _print_olympus.olympus_multiple_exposure_mode
olympus_special_mode = _print_olympus.olympus_special_mode
indexed_olympus_value = _print_olympus.indexed_olympus_value
olympus_focus_info_image_stabilization = _print_olympus.olympus_focus_info_image_stabilization
olympus_drive_mode = _print_olympus.olympus_drive_mode
OLYMPUS_DRIVE_SHOOTING_MODE = _print_olympus.OLYMPUS_DRIVE_SHOOTING_MODE
olympus_drive_mode_shutter = _print_olympus.olympus_drive_mode_shutter
is_pentax_af_info_k3iii_print_location = _print_pentax.is_pentax_af_info_k3iii_print_location
is_pentax_main_print_location = _print_pentax.is_pentax_main_print_location
is_pentax_af_info_k3iii_area_location = _print_pentax.is_pentax_af_info_k3iii_area_location
pentax_color_temp_print = _print_pentax.pentax_color_temp_print
pentax_main_print_conversion = _print_pentax.pentax_main_print_conversion
pentax_array_print = _print_pentax.pentax_array_print
raw_string = _print_pentax.raw_string
pentax_auto_bracketing_print = _print_pentax.pentax_auto_bracketing_print
pentax_metering_segments = _print_pentax.pentax_metering_segments
pentax_picture_mode = _print_pentax.pentax_picture_mode
pentax_picture_mode_51 = _print_pentax.pentax_picture_mode_51
pentax_drive_mode = _print_pentax.pentax_drive_mode
pentax_timer_mode = _print_pentax.pentax_timer_mode
pentax_remote_mode = _print_pentax.pentax_remote_mode
pentax_multi_exposure_mode = _print_pentax.pentax_multi_exposure_mode
pentax_flash_mode = _print_pentax.pentax_flash_mode
pentax_external_flash_mode = _print_pentax.pentax_external_flash_mode
pentax_saturation = _print_pentax.pentax_saturation
pentax_contrast = _print_pentax.pentax_contrast
pentax_sharpness = _print_pentax.pentax_sharpness
off_on_value = _print_pentax.off_on_value
pentax_dynamic_range_mode = _print_pentax.pentax_dynamic_range_mode
pentax_fine_sharpness_mode = _print_pentax.pentax_fine_sharpness_mode
pentax_high_iso_noise_reduction = _print_pentax.pentax_high_iso_noise_reduction
pentax_high_iso_noise_reduction_active = _print_pentax.pentax_high_iso_noise_reduction_active
pentax_high_iso_noise_reduction_start = _print_pentax.pentax_high_iso_noise_reduction_start
pentax_face_detect_max = _print_pentax.pentax_face_detect_max
pentax_faces_detected = _print_pentax.pentax_faces_detected
pentax_iso_auto_min_speed_mode = _print_pentax.pentax_iso_auto_min_speed_mode
pentax_blur_control_mode = _print_pentax.pentax_blur_control_mode
pentax_hdr_mode = _print_pentax.pentax_hdr_mode
pentax_auto_align = _print_pentax.pentax_auto_align
pentax_hdr_ev = _print_pentax.pentax_hdr_ev
print_exposure_time = _print_pentax.print_exposure_time
pentax_af_areas_k3iii = _print_pentax.pentax_af_areas_k3iii
PENTAX_K3III_AF_POINTS = _print_pentax.PENTAX_K3III_AF_POINTS
pentax_af_info_k3iii_print = _print_pentax.pentax_af_info_k3iii_print
pentax_af_point_names_k3iii = _print_pentax.pentax_af_point_names_k3iii
pentax_af_point_values_k3iii = _print_pentax.pentax_af_point_values_k3iii
pentax_af_point_value_name = _print_pentax.pentax_af_point_value_name
MakerNotePrintConversionStatus = _print_models.MakerNotePrintConversionStatus
MakerNotePrintConversionRequest = _print_models.MakerNotePrintConversionRequest
MakerNotePrintConversionMatch = _print_models.MakerNotePrintConversionMatch
MakerNotePrintConversionResult = _print_models.MakerNotePrintConversionResult
vm_value_to_print_string = _print_models.vm_value_to_print_string
maker_note_print_conversion_summary = _print_models.maker_note_print_conversion_summary
maker_note_print_conversion_request_to_json = (
    _print_models.maker_note_print_conversion_request_to_json
)
maker_note_print_conversion_matches_to_json = (
    _print_models.maker_note_print_conversion_matches_to_json
)


def run_maker_note_print_conversion(
    maker_note_package: Path,
    request: MakerNotePrintConversionRequest,
) -> MakerNotePrintConversionResult:
    repository = load_maker_note_table_repository(maker_note_package)
    return render_maker_note_print_conversion(repository, request)


def render_maker_note_print_conversion(
    repository: MakerNoteTableRepository,
    request: MakerNotePrintConversionRequest,
) -> MakerNotePrintConversionResult:
    candidates = repository.tag_entry_locations_for(
        vendor=request.vendor,
        module=request.module,
        table=request.table,
        tag_name=request.tag_name,
        tag_id=request.tag_id,
    )
    matches = tuple(
        render_maker_note_print_conversion_match(location, request) for location in candidates
    )
    limited_matches = matches if request.limit is None else matches[: request.limit]
    return MakerNotePrintConversionResult(
        request=request,
        repository=repository,
        candidate_count=len(candidates),
        matches=limited_matches,
    )


def write_maker_note_print_conversion_result(
    maker_note_package: Path,
    request: MakerNotePrintConversionRequest,
    output: Path,
) -> MakerNotePrintConversionResult:
    result = run_maker_note_print_conversion(maker_note_package, request)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def render_maker_note_print_conversion_match(
    location: MakerNoteTagLocation,
    request: MakerNotePrintConversionRequest,
) -> MakerNotePrintConversionMatch:
    printed_value = maker_note_print_conversion_value(location, request)
    return MakerNotePrintConversionMatch(
        location=location,
        status=maker_note_print_conversion_status(location, request, printed_value),
        printed_value=printed_value,
    )


def maker_note_print_conversion_status(
    location: MakerNoteTagLocation,
    request: MakerNotePrintConversionRequest,
    printed_value: str | None,
) -> MakerNotePrintConversionStatus:
    entry = location.entry
    if entry.print_conv_pair_count:
        if request.complete_only and not entry.has_complete_scalar_print_conv_map:
            return "partial_map_blocked"
        if printed_value is None:
            return "unknown_value"
        return "converted"
    if maker_note_domain_print_conversion_adapter_supported(location):
        if request.complete_only:
            return "partial_map_blocked"
        if printed_value is None:
            return "evaluation_error"
        return "converted"
    if entry.print_conv_kind != "scalar" or not entry.print_conv_text:
        return "not_declarative"
    if request.complete_only:
        return "partial_map_blocked"
    if printed_value is None:
        from exifmodern.safe_expression.compat_compiler import compile_safe_expression

        if compile_safe_expression(entry.print_conv_text) is None:
            return "unsupported_expression"
        return "evaluation_error"
    return "converted"


def maker_note_print_conversion_value(
    location: MakerNoteTagLocation,
    request: MakerNotePrintConversionRequest,
) -> str | None:
    entry = location.entry
    if entry.print_conv_pair_count:
        if request.complete_only and not entry.has_complete_scalar_print_conv_map:
            return None
        return entry.print_conversion_for(request.raw_value)
    if maker_note_domain_print_conversion_adapter_supported(location):
        if request.complete_only:
            return None
        return render_domain_string_print_conversion(
            location,
            request.raw_value,
            request.runtime_context,
        )
    if entry.print_conv_kind != "scalar" or not entry.print_conv_text or request.complete_only:
        return None
    adapter_value = render_scalar_string_print_conversion(entry.print_conv_text, request.raw_value)
    if adapter_value is not None:
        return adapter_value
    from exifmodern.safe_expression.compat_compiler import compile_safe_expression

    program = compile_safe_expression(entry.print_conv_text)
    if program is not None:
        from exifmodern.safe_expression.vm import SafeExpressionVmError, evaluate_program

        try:
            return vm_value_to_print_string(evaluate_program(program, {"$val": request.raw_value}))
        except SafeExpressionVmError:
            return None
    return None


def maker_note_domain_print_conversion_adapter_supported(location: MakerNoteTagLocation) -> bool:
    return (
        is_pentax_color_temp_location(location)
        or is_pentax_main_print_location(location)
        or is_pentax_af_info_k3iii_area_location(location)
        or is_pentax_af_info_k3iii_print_location(location)
        or is_canon_custom_personal_funcs_location(location)
        or is_canon_custom_functions2_array_print_location(location)
        or is_canon_main_picture_style_array_location(location)
        or is_olympus_print_domain_location(location)
        or is_sony_lens_spec_print_location(location)
        or is_sony_hdr_array_print_location(location)
        or is_sony_datetime_print_location(location)
        or is_sony_limit_long_values_print_location(location)
        or is_nikon_print_domain_location(location)
        or is_fuji_main_print_domain_location(location)
        or is_panasonic_print_domain_location(location)
        or is_nikon_z9_self_state_print_location(location)
        or is_olympus_model_dependent_custom_saturation_location(location)
        or is_olympus_camera_type_quality_location(location)
    )


def maker_note_print_conversion_runtime_boundary(
    location: MakerNoteTagLocation,
) -> MakerNoteRuntimeBoundary:
    if (
        is_nikon_z9_self_state_print_location(location)
        or is_olympus_model_dependent_custom_saturation_location(location)
        or is_olympus_camera_type_quality_location(location)
    ):
        return "object_state_context"
    return "none"


def maker_note_domain_print_conversion_blocker_reason(
    location: MakerNoteTagLocation,
) -> str | None:
    return None


def is_pentax_color_temp_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Pentax"
        and location.table.name == "Main"
        and location.entry.value_conv_kind == "code"
        and location.entry.print_conv_kind == "code"
        and location.entry.name
        in {
            "ColorTempDaylight",
            "ColorTempShade",
            "ColorTempCloudy",
            "ColorTempTungsten",
            "ColorTempFluorescentD",
            "ColorTempFluorescentN",
            "ColorTempFluorescentW",
            "ColorTempFlash",
        }
    )


def render_domain_string_print_conversion(
    location: MakerNoteTagLocation,
    raw_value: str,
    runtime_context: MakerNoteRuntimeContext = EMPTY_MAKER_NOTE_RUNTIME_CONTEXT,
) -> str | None:
    if is_pentax_color_temp_location(location):
        return pentax_color_temp_print(raw_value)
    if is_pentax_main_print_location(location):
        return pentax_main_print_conversion(location.entry.name, location.entry.tag_id, raw_value)
    if is_pentax_af_info_k3iii_area_location(location):
        return pentax_af_areas_k3iii(raw_value)
    if is_pentax_af_info_k3iii_print_location(location):
        return pentax_af_info_k3iii_print(location.entry.name, raw_value)
    if is_canon_custom_personal_funcs_location(location):
        return canon_custom_personal_func(raw_value)
    if is_canon_custom_functions2_array_print_location(location):
        return canon_custom_functions2_array_print(location.entry.tag_id, raw_value)
    if is_canon_main_picture_style_array_location(location):
        return canon_main_picture_style_array_print(raw_value)
    if is_olympus_print_domain_location(location):
        return olympus_print_domain_conversion(location, raw_value)
    if is_sony_lens_spec_print_location(location):
        return sony_lens_spec_print(raw_value)
    if is_sony_hdr_array_print_location(location):
        return sony_hdr_array_print(raw_value)
    if is_sony_datetime_print_location(location):
        return raw_value
    if is_sony_limit_long_values_print_location(location):
        return limit_long_values(raw_value, limit=60)
    if is_nikon_print_domain_location(location):
        return nikon_print_domain_conversion(location, raw_value)
    if is_fuji_main_print_domain_location(location):
        return fuji_main_print_domain_conversion(location.entry.name, raw_value)
    if is_panasonic_print_domain_location(location):
        return panasonic_print_domain_conversion(location.entry.name, raw_value)
    if is_nikon_z9_self_state_print_location(location):
        return nikon_z9_self_state_print_conversion(location.entry.name, raw_value, runtime_context)
    if is_olympus_model_dependent_custom_saturation_location(location):
        return olympus_custom_saturation(raw_value, runtime_context)
    if is_olympus_camera_type_quality_location(location):
        return olympus_quality(raw_value, runtime_context)
    return None


def is_canon_custom_personal_funcs_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::CanonCustom"
        and location.table.name == "PersonalFuncs"
        and location.entry.print_conv_kind == "code"
        and location.entry.name.startswith("PF")
    )


def is_canon_custom_functions2_array_print_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::CanonCustom"
        and location.table.name == "Functions2"
        and location.entry.print_conv_kind == "array"
        and location.entry.tag_id
        in {
            "270",
            "272",
            "273",
            "1287",
            "1298",
            "1309",
            "1553",
            "1801",
            "1807",
        }
    )


def is_canon_main_picture_style_array_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Canon"
        and location.table.name == "Main"
        and location.entry.name in {"PictureStyleUserDef", "PictureStylePC"}
        and location.entry.tag_id in {"16392", "16393"}
        and location.entry.print_conv_kind == "array"
    )


def is_sony_lens_spec_print_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Sony"
        and location.entry.name in {"LensSpec", "LensSpecFeatures"}
        and location.entry.print_conv_kind == "code"
    )


def is_sony_hdr_array_print_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Sony"
        and location.table.name == "Main"
        and location.entry.name == "HDR"
        and location.entry.print_conv_kind == "array"
    )


def is_sony_datetime_print_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Sony"
        and location.entry.name in {"SonyDateTime", "DateTime"}
        and location.entry.print_conv_kind == "scalar"
        and location.entry.print_conv_text == "$self->ConvertDateTime($val)"
    )


def is_sony_limit_long_values_print_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Sony"
        and location.table.name == "Main"
        and location.entry.value_conv_kind == "scalar"
        and location.entry.value_conv_text == "PrintHex($val)"
        and location.entry.print_conv_kind == "code"
    )


def sony_lens_spec_print(raw_value: str) -> str:
    values = raw_value.split()
    printed: str | None = None
    if len(values) == 2:
        first_flags, second_flags = values
        printed = ""
    elif len(values) >= 6:
        first_flags, short_focal, long_focal, short_aperture, long_aperture, second_flags = values[
            :6
        ]
        if sony_lens_spec_numbers_valid(short_focal, long_focal, short_aperture, long_aperture):
            focal_range = sony_lens_spec_range(short_focal, long_focal)
            aperture_range = sony_lens_spec_range(short_aperture, long_aperture)
            printed = f"{focal_range}mm F{aperture_range}"
    else:
        first_flags = ""
        second_flags = ""
    if printed is None:
        return f"Unknown ({raw_value})"
    return sony_lens_spec_add_features(printed, first_flags, second_flags)


def sony_lens_spec_numbers_valid(
    short_focal: str,
    long_focal: str,
    short_aperture: str,
    long_aperture: str,
) -> bool:
    short_focal_value = parse_float(short_focal)
    long_focal_value = parse_float(long_focal)
    short_aperture_value = parse_float(short_aperture)
    long_aperture_value = parse_float(long_aperture)
    if (
        short_focal_value is None
        or long_focal_value is None
        or short_aperture_value is None
        or long_aperture_value is None
    ):
        return False
    return (
        short_focal_value != 0
        and short_aperture_value != 0
        and (long_focal_value == 0 or long_focal_value >= short_focal_value)
        and (long_aperture_value == 0 or long_aperture_value >= short_aperture_value)
    )


def sony_lens_spec_range(first_value: str, second_value: str) -> str:
    if second_value != first_value and second_value != "0":
        return f"{first_value}-{second_value}"
    return first_value


def sony_lens_spec_add_features(printed: str, first_flags: str, second_flags: str) -> str:
    flags = sony_lens_spec_flags(first_flags, second_flags)
    for mask, labels, prefix in sony_lens_feature_rules():
        bits = mask & flags
        if not bits and bits not in labels:
            continue
        label = labels.get(bits, f"Unknown({bits:04x})")
        printed = (f"{label} {printed}" if prefix else f"{printed} {label}") if printed else label
    return printed


def sony_lens_spec_flags(first_flags: str, second_flags: str) -> int:
    try:
        return int(first_flags + second_flags, 16)
    except ValueError:
        return 0


def sony_lens_feature_rules() -> tuple[tuple[int, dict[int, str], bool], ...]:
    return (
        (0x4000, {0x4000: "PZ"}, True),
        (0x0300, {0x0100: "DT", 0x0200: "FE", 0x0300: "E"}, True),
        (0x00E0, {0x0020: "STF", 0x0040: "Reflex", 0x0060: "Macro", 0x0080: "Fisheye"}, False),
        (0x000C, {0x0004: "ZA", 0x0008: "G"}, False),
        (0x0003, {0x0001: "SSM", 0x0002: "SAM"}, False),
        (0x8000, {0x8000: "OSS"}, False),
        (0x2000, {0x2000: "LE"}, False),
        (0x0800, {0x0800: "II"}, False),
    )


def sony_hdr_array_print(raw_value: str) -> str | None:
    values = raw_value.split()
    if not values:
        return None
    return convert_indexed_values(values, (sony_hdr_level_print, sony_hdr_image_print))


def sony_hdr_level_print(raw_value: str) -> str | None:
    value = parse_hex_or_decimal_int(raw_value)
    if value is None:
        return None
    return {
        0x00: "Off",
        0x01: "Auto",
        0x10: "1.0 EV",
        0x11: "1.5 EV",
        0x12: "2.0 EV",
        0x13: "2.5 EV",
        0x14: "3.0 EV",
        0x15: "3.5 EV",
        0x16: "4.0 EV",
        0x17: "4.5 EV",
        0x18: "5.0 EV",
        0x19: "5.5 EV",
        0x1A: "6.0 EV",
    }.get(value)


def sony_hdr_image_print(raw_value: str) -> str | None:
    value = parse_hex_or_decimal_int(raw_value)
    if value is None:
        return None
    return {
        0: "Uncorrected image",
        1: "HDR image (good)",
        2: "HDR image (fail 1)",
        3: "HDR image (fail 2)",
    }.get(value)


def parse_hex_or_decimal_int(raw_value: str) -> int | None:
    try:
        return int(raw_value, 0)
    except ValueError:
        value = parse_float(raw_value)
        if value is None:
            return None
        return int(value)


def limit_long_values(raw_value: str, *, limit: int) -> str:
    if len(raw_value) > limit and limit >= 5:
        return raw_value[: limit - 5] + "[...]"
    return raw_value


def canon_custom_personal_func(raw_value: str) -> str:
    if not perl_truthy(raw_value):
        return "Off"
    value = parse_float(raw_value)
    if value == 1:
        return "On"
    return f"On ({raw_value})"


def canon_custom_functions2_array_print(tag_id: str, raw_value: str) -> str | None:
    values = raw_value.split()
    if tag_id in {"270", "272", "273"}:
        return convert_indexed_values(values, (disable_enable_value,), repeat_last=True)
    if tag_id == "1287":
        return convert_indexed_values(values, (af_microadjustment_mode,), repeat_last=False)
    if tag_id == "1298":
        return convert_indexed_values(values, (select_af_area_mode, flags_hex_value))
    if tag_id == "1309":
        return convert_indexed_values(values, (vf_display_illumination_7d, on_off_value))
    if tag_id == "1553":
        return convert_indexed_values(values, (disable_enable_value, shots_value))
    if tag_id == "1801":
        return convert_indexed_values(values, (lock_microphone_button,), repeat_last=False)
    if tag_id == "1807":
        return convert_indexed_values(
            values,
            (multi_function_lock_mode, bitmask_multi_function_lock),
        )
    return None


def canon_main_picture_style_array_print(raw_value: str) -> str | None:
    return convert_indexed_values(
        raw_value.split(),
        (canon_picture_style, canon_picture_style, canon_picture_style),
    )


def canon_picture_style(raw_value: str) -> str | None:
    return mapped_integer_value(
        raw_value,
        {
            0x21: "User Def. 1",
            0x22: "User Def. 2",
            0x23: "User Def. 3",
            0x41: "PC 1",
            0x42: "PC 2",
            0x43: "PC 3",
            0x81: "Standard",
            0x82: "Portrait",
            0x83: "Landscape",
            0x84: "Neutral",
            0x85: "Faithful",
            0x86: "Monochrome",
            0x87: "Auto",
            0x88: "Fine Detail",
            0xFF: "n/a",
            0xFFFF: "n/a",
        },
    )


def disable_enable_value(raw_value: str) -> str | None:
    return mapped_integer_value(raw_value, {0: "Disable", 1: "Enable"})


def on_off_value(raw_value: str) -> str | None:
    return mapped_integer_value(raw_value, {0: "On", 1: "Off"})


def af_microadjustment_mode(raw_value: str) -> str | None:
    return mapped_integer_value(
        raw_value,
        {
            0: "Disable",
            1: "Adjust all by same amount",
            2: "Adjust by lens",
        },
    )


def select_af_area_mode(raw_value: str) -> str | None:
    return mapped_integer_value(
        raw_value,
        {
            0: "Disable",
            1: "Enable",
            2: "Register",
            3: "Select AF-modes",
        },
    )


def vf_display_illumination_7d(raw_value: str) -> str | None:
    return mapped_integer_value(raw_value, {0: "Auto", 1: "Enable", 2: "Disable"})


def lock_microphone_button(raw_value: str) -> str | None:
    return mapped_integer_value(
        raw_value,
        {
            0: "Protect (hold:record memo)",
            1: "Record memo (protect:disable)",
            2: "Play memo (hold:record memo)",
            3: "Rating (protect/memo:disable)",
        },
    )


def multi_function_lock_mode(raw_value: str) -> str | None:
    return mapped_integer_value(
        raw_value,
        {
            0: "Off",
            1: "On",
            2: "On (quick control dial)",
            3: "On (main dial and quick control dial)",
        },
    )


def flags_hex_value(raw_value: str) -> str | None:
    value = parse_int(raw_value)
    if value is None:
        return None
    return f"Flags 0x{value:x}"


def shots_value(raw_value: str) -> str | None:
    value = parse_int(raw_value)
    if value is None:
        return None
    return f"{value} shots"


def bitmask_multi_function_lock(raw_value: str) -> str | None:
    return decode_bits(
        raw_value,
        (
            (0, "Main dial"),
            (1, "Quick control dial"),
            (2, "Multi-controller"),
        ),
        bits_per_word=32,
    )
