"""Typed facade for exact-name ExifTool helper compatibility adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from exifmodern.exiftool_compat.asf import get_guid
from exifmodern.exiftool_compat.canon import (
    camera_iso,
    canon_ev,
    canon_ev_inv,
    print_af_points_1d,
    print_focal_range,
)
from exifmodern.exiftool_compat.canon_vrd import tone_curve_print, tone_curve_print_inv
from exifmodern.exiftool_compat.composite import (
    canon_file_number as composite_canon_file_number,
)
from exifmodern.exiftool_compat.composite import depth_of_field as composite_depth_of_field
from exifmodern.exiftool_compat.composite import field_of_view as composite_field_of_view
from exifmodern.exiftool_compat.composite import xmp_flash_value as composite_xmp_flash_value
from exifmodern.exiftool_compat.core import (
    convert_bitrate,
    convert_date_time,
    convert_duration,
    convert_file_size,
    convert_time_span,
    convert_unix_time,
    decode_bits,
    get_unix_time,
    print_hex,
    time_zone_string,
    to_float,
)
from exifmodern.exiftool_compat.exif import (
    calc_scale_factor_35efl,
    calculate_lv,
    convert_exif_text,
    convert_fraction,
    convert_parameter,
    decode_cfa_pattern,
    encode_exif_text,
    exif_date,
    exif_time,
    get_cfa_pattern,
    print_cfa_pattern,
    print_exposure_time,
    print_fnumber,
    print_fraction,
    red_blue_balance,
)
from exifmodern.exiftool_compat.exif import (
    identify_raw_file_compression as exif_identify_raw_file_compression,
)
from exifmodern.exiftool_compat.flir import get_image_type as flir_get_image_type
from exifmodern.exiftool_compat.fujifilm import (
    raf_layout_dimensions as fujifilm_raf_layout_dimensions,
)
from exifmodern.exiftool_compat.garmin import gps_hundredths as garmin_gps_hundredths
from exifmodern.exiftool_compat.gopro import add_units as gopro_add_units
from exifmodern.exiftool_compat.gopro import (
    system_time_list_update as gopro_system_time_list_update,
)
from exifmodern.exiftool_compat.gps import (
    convert_time_stamp as gps_convert_time_stamp,
)
from exifmodern.exiftool_compat.gps import (
    geolocate_print_conv_inv,
    gps_to_degrees,
    gps_to_dms,
    print_time_stamp,
)
from exifmodern.exiftool_compat.icc_profile import hex_id
from exifmodern.exiftool_compat.id3 import convert_id3v1_text, print_genre
from exifmodern.exiftool_compat.iptc import (
    convert_picture_number,
    inv_convert_picture_number,
    inverse_date_or_time,
    iptc_date,
    iptc_time,
)
from exifmodern.exiftool_compat.jpeg2000 import process_jxl_codestream
from exifmodern.exiftool_compat.kodak import calculate_rgb_levels
from exifmodern.exiftool_compat.lif import timestamp_list as lif_timestamp_list
from exifmodern.exiftool_compat.lnk import dos_time
from exifmodern.exiftool_compat.minolta import convert_white_balance
from exifmodern.exiftool_compat.minolta_raw import convert_wb_mode
from exifmodern.exiftool_compat.moi import aspect_ratio as moi_aspect_ratio
from exifmodern.exiftool_compat.nikon import (
    auto_capture_area_bits as nikon_auto_capture_area_bits,
)
from exifmodern.exiftool_compat.nikon import (
    auto_capture_trigger_bits as nikon_auto_capture_trigger_bits,
)
from exifmodern.exiftool_compat.nikon import (
    focus_shift_frame as nikon_focus_shift_frame,
)
from exifmodern.exiftool_compat.nikon import (
    lens_drive_end as nikon_lens_drive_end,
)
from exifmodern.exiftool_compat.nikon import (
    lens_drive_end_update as nikon_lens_drive_end_update,
)
from exifmodern.exiftool_compat.nikon import (
    nikon_print_pc,
    nikon_print_pc_inv,
    nikon_print_pc_inv2,
)
from exifmodern.exiftool_compat.nikon import (
    z9_af_area_x as nikon_z9_af_area_x,
)
from exifmodern.exiftool_compat.nikon import (
    z9_af_area_y as nikon_z9_af_area_y,
)
from exifmodern.exiftool_compat.olympus import (
    extender_status,
    print_af_areas,
)
from exifmodern.exiftool_compat.olympus import (
    panorama_direction as olympus_panorama_direction,
)
from exifmodern.exiftool_compat.panasonic import pana_thumb_type as panasonic_pana_thumb_type
from exifmodern.exiftool_compat.pdf import convert_pdf_date
from exifmodern.exiftool_compat.pentax import (
    decode_af_points as pentax_decode_af_points,
)
from exifmodern.exiftool_compat.pentax import pentax_ev, pentax_ev_inv
from exifmodern.exiftool_compat.phase_one import sensor_calibration as phase_one_sensor_calibration
from exifmodern.exiftool_compat.photoshop import convert_pascal_string
from exifmodern.exiftool_compat.postscript import image_size as postscript_image_size
from exifmodern.exiftool_compat.quicktime import (
    ar_drone_telemetry as quicktime_ar_drone_telemetry,
)
from exifmodern.exiftool_compat.quicktime import calc_rotation as quicktime_calc_rotation
from exifmodern.exiftool_compat.quicktime import calc_sample_rate as quicktime_calc_sample_rate
from exifmodern.exiftool_compat.quicktime import camm6_timestamp as quicktime_camm6_timestamp
from exifmodern.exiftool_compat.quicktime import (
    free_payload_offsets as quicktime_free_payload_offsets,
)
from exifmodern.exiftool_compat.quicktime import (
    handler_type_update as quicktime_handler_type_update,
)
from exifmodern.exiftool_compat.reconyx import hyperfire_datetime as reconyx_hyperfire_datetime
from exifmodern.exiftool_compat.riff import anmf_frame_duration as riff_anmf_frame_duration
from exifmodern.exiftool_compat.riff import calc_duration as riff_calc_duration
from exifmodern.exiftool_compat.riff import convert_riff_date
from exifmodern.exiftool_compat.samsung import crypt as samsung_crypt
from exifmodern.exiftool_compat.samsung import (
    encryption_key_update as samsung_encryption_key_update,
)
from exifmodern.exiftool_compat.sony import print_inv_lens_spec
from exifmodern.exiftool_compat.tiff import make_tiff_header
from exifmodern.exiftool_compat.tnef import decompress_rtf as tnef_decompress_rtf
from exifmodern.exiftool_compat.types import (
    ExifToolCompatibilityError,
    ExifToolEffectResult,
    ExifToolHashEntry,
    ExifToolHashReference,
    ExifToolScalar,
    ExifToolScalarReference,
    ExifToolValue,
)
from exifmodern.exiftool_compat.xmp import (
    convert_xmp_date,
    decode_base64,
    encode_base64,
    format_xmp_date,
)

__all__ = [
    "EXIFTOOL_FUNCTION_SIGNATURES",
    "ExifToolCompatibilityError",
    "ExifToolEffectResult",
    "ExifToolFunction",
    "ExifToolFunctionName",
    "ExifToolFunctionSignature",
    "ExifToolHashEntry",
    "ExifToolHashReference",
    "ExifToolScalar",
    "ExifToolScalarReference",
    "ExifToolValue",
    "evaluate_exiftool_effect_function",
    "evaluate_exiftool_function",
    "exiftool_function_has_effects",
    "exiftool_signature_or_none",
]

type ExifToolFunction = Literal[
    "calculate_lv",
    "calc_scale_factor_35efl",
    "camera_iso",
    "canon_ev",
    "canon_ev_inv",
    "convert_bitrate",
    "convert_date_time",
    "composite_canon_file_number",
    "composite_depth_of_field",
    "composite_field_of_view",
    "composite_xmp_flash_value",
    "convert_duration",
    "convert_exif_text",
    "convert_file_size",
    "convert_fraction",
    "convert_id3v1_text",
    "convert_parameter",
    "convert_picture_number",
    "convert_riff_date",
    "convert_time_span",
    "convert_unix_time",
    "convert_white_balance",
    "convert_wb_mode",
    "convert_xmp_date",
    "decode_bits",
    "decode_base64",
    "decode_cfa_pattern",
    "dos_time",
    "encode_exif_text",
    "encode_base64",
    "exif_date",
    "exif_time",
    "exif_identify_raw_file_compression",
    "flir_get_image_type",
    "format_xmp_date",
    "fujifilm_raf_layout_dimensions",
    "get_cfa_pattern",
    "get_guid",
    "get_unix_time",
    "garmin_gps_hundredths",
    "gps_convert_time_stamp",
    "gps_geolocate_print_conv_inv",
    "gps_to_dms",
    "gps_to_degrees",
    "gopro_add_units",
    "gopro_system_time_list_update",
    "hex_id",
    "inv_convert_picture_number",
    "inverse_date_or_time",
    "iptc_date",
    "iptc_time",
    "jpeg2000_process_jxl_codestream",
    "kodak_calculate_rgb_levels",
    "lif_timestamp_list",
    "make_tiff_header",
    "moi_aspect_ratio",
    "olympus_extender_status",
    "olympus_panorama_direction",
    "nikon_print_pc",
    "nikon_print_pc_inv",
    "nikon_print_pc_inv2",
    "nikon_auto_capture_trigger_bits",
    "nikon_auto_capture_area_bits",
    "nikon_lens_drive_end",
    "nikon_lens_drive_end_update",
    "nikon_focus_shift_frame",
    "nikon_z9_af_area_x",
    "nikon_z9_af_area_y",
    "pentax_ev",
    "pentax_ev_inv",
    "pentax_decode_af_points",
    "phase_one_sensor_calibration",
    "panasonic_pana_thumb_type",
    "pdf_convert_pdf_date",
    "print_af_points_1d",
    "print_af_areas",
    "print_cfa_pattern",
    "print_hex",
    "print_exposure_time",
    "print_fnumber",
    "print_focal_range",
    "print_fraction",
    "print_genre",
    "photoshop_convert_pascal_string",
    "postscript_image_size",
    "print_inv_lens_spec",
    "quicktime_calc_rotation",
    "quicktime_ar_drone_telemetry",
    "quicktime_camm6_timestamp",
    "quicktime_calc_sample_rate",
    "quicktime_free_payload_offsets",
    "quicktime_handler_type_update",
    "red_blue_balance",
    "reconyx_hyperfire_datetime",
    "riff_calc_duration",
    "riff_anmf_frame_duration",
    "samsung_crypt",
    "samsung_encryption_key_update",
    "print_time_stamp",
    "time_zone_string",
    "tnef_decompress_rtf",
    "tone_curve_print",
    "tone_curve_print_inv",
    "to_float",
]
type ExifToolFunctionName = Literal[
    "ConvertBitrate",
    "ConvertDateTime",
    "ConvertDuration",
    "ConvertFileSize",
    "ConvertTimeSpan",
    "GetUnixTime",
    "ConvertUnixTime",
    "Image::ExifTool::ASF::GetGUID",
    "Image::ExifTool::ConvertUnixTime",
    "Image::ExifTool::DecodeBits",
    "Image::ExifTool::TimeZoneString",
    "Image::ExifTool::Canon::CameraISO",
    "Image::ExifTool::Canon::CanonEv",
    "Image::ExifTool::Canon::CanonEvInv",
    "Image::ExifTool::Canon::PrintAFPoints1D",
    "Image::ExifTool::Canon::PrintFocalRange",
    "Image::ExifTool::CanonVRD::ToneCurvePrint",
    "Image::ExifTool::CanonVRD::ToneCurvePrintInv",
    "Image::ExifTool::Exif::ConvertExifText",
    "Image::ExifTool::Exif::CalculateLV",
    "Image::ExifTool::Exif::CalcScaleFactor35efl",
    "Image::ExifTool::Exif::EncodeExifText",
    "Image::ExifTool::Exif::ConvertFraction",
    "Image::ExifTool::Exif::ConvertParameter",
    "Image::ExifTool::Exif::DecodeCFAPattern",
    "Image::ExifTool::Exif::ExifDate",
    "Image::ExifTool::Exif::ExifTime",
    "Image::ExifTool::Exif::GetCFAPattern",
    "Image::ExifTool::Exif::PrintExposureTime",
    "Image::ExifTool::Exif::PrintCFAPattern",
    "Image::ExifTool::Exif::PrintFNumber",
    "Image::ExifTool::Exif::PrintFraction",
    "Image::ExifTool::Exif::RedBlueBalance",
    "Image::ExifTool::FLIR::GetImageType",
    "Image::ExifTool::GPS::PrintTimeStamp",
    "Image::ExifTool::GPS::ConvertTimeStamp",
    "Image::ExifTool::GPS::ToDMS",
    "Image::ExifTool::GPS::ToDegrees",
    "Image::ExifTool::GoPro::AddUnits",
    "Image::ExifTool::ID3::ConvertID3v1Text",
    "Image::ExifTool::ID3::PrintGenre",
    "Image::ExifTool::ICC_Profile::HexID",
    "Image::ExifTool::IPTC::ConvertPictureNumber",
    "Image::ExifTool::IPTC::InvConvertPictureNumber",
    "Image::ExifTool::IPTC::InverseDateOrTime",
    "Image::ExifTool::IPTC::IptcDate",
    "Image::ExifTool::IPTC::IptcTime",
    "Image::ExifTool::Jpeg2000::ProcessJXLCodestream",
    "Image::ExifTool::Kodak::CalculateRGBLevels",
    "Image::ExifTool::LNK::DOSTime",
    "Image::ExifTool::MakeTiffHeader",
    "Image::ExifTool::Minolta::ConvertWhiteBalance",
    "Image::ExifTool::MinoltaRaw::ConvertWBMode",
    "Image::ExifTool::Nikon::PrintPC",
    "Image::ExifTool::Nikon::PrintPCInv",
    "Image::ExifTool::Nikon::PrintPCInv2",
    "Image::ExifTool::Olympus::ExtenderStatus",
    "Image::ExifTool::Olympus::PrintAFAreas",
    "Image::ExifTool::Pentax::PentaxEv",
    "Image::ExifTool::Pentax::PentaxEvInv",
    "Image::ExifTool::Pentax::DecodeAFPoints",
    "Image::ExifTool::PDF::ConvertPDFDate",
    "Image::ExifTool::Photoshop::ConvertPascalString",
    "Image::ExifTool::PostScript::ImageSize",
    "Image::ExifTool::QuickTime::CalcRotation",
    "Image::ExifTool::QuickTime::CalcSampleRate",
    "Image::ExifTool::RIFF::CalcDuration",
    "Image::ExifTool::RIFF::ConvertRIFFDate",
    "Image::ExifTool::Samsung::Crypt",
    "Image::ExifTool::Sony::PrintInvLensSpec",
    "Image::ExifTool::XMP::ConvertXMPDate",
    "Image::ExifTool::XMP::DecodeBase64",
    "Image::ExifTool::XMP::EncodeBase64",
    "Image::ExifTool::XMP::FormatXMPDate",
    "PrintHex",
    "TimeZoneString",
    "ToFloat",
    "MakeTiffHeader",
]
type SingleArgumentHelper = Callable[[ExifToolScalar], ExifToolScalar]
type MultiArgumentHelper = Callable[[list[ExifToolScalar]], ExifToolScalar]
type ReferenceArgumentHelper = Callable[[list[ExifToolValue]], ExifToolValue]
type EffectArgumentHelper = Callable[[list[ExifToolValue]], ExifToolEffectResult]


@dataclass(frozen=True)
class ExifToolFunctionSignature:
    perl_name: ExifToolFunctionName
    vm_function: ExifToolFunction
    minimum_arguments: int
    maximum_arguments: int


EXIFTOOL_FUNCTION_SIGNATURES: tuple[ExifToolFunctionSignature, ...] = (
    ExifToolFunctionSignature("ConvertBitrate", "convert_bitrate", 1, 1),
    ExifToolFunctionSignature("ConvertDateTime", "convert_date_time", 1, 1),
    ExifToolFunctionSignature("ConvertDuration", "convert_duration", 1, 1),
    ExifToolFunctionSignature("ConvertFileSize", "convert_file_size", 1, 1),
    ExifToolFunctionSignature("ConvertTimeSpan", "convert_time_span", 1, 2),
    ExifToolFunctionSignature("ConvertUnixTime", "convert_unix_time", 1, 3),
    ExifToolFunctionSignature("GetUnixTime", "get_unix_time", 1, 2),
    ExifToolFunctionSignature("Image::ExifTool::ASF::GetGUID", "get_guid", 1, 1),
    ExifToolFunctionSignature("Image::ExifTool::ConvertUnixTime", "convert_unix_time", 1, 3),
    ExifToolFunctionSignature("Image::ExifTool::DecodeBits", "decode_bits", 2, 3),
    ExifToolFunctionSignature("Image::ExifTool::TimeZoneString", "time_zone_string", 1, 1),
    ExifToolFunctionSignature("Image::ExifTool::Canon::CameraISO", "camera_iso", 1, 2),
    ExifToolFunctionSignature("Image::ExifTool::Canon::CanonEv", "canon_ev", 1, 1),
    ExifToolFunctionSignature("Image::ExifTool::Canon::CanonEvInv", "canon_ev_inv", 1, 1),
    ExifToolFunctionSignature(
        "Image::ExifTool::Canon::PrintAFPoints1D",
        "print_af_points_1d",
        1,
        1,
    ),
    ExifToolFunctionSignature("Image::ExifTool::Canon::PrintFocalRange", "print_focal_range", 2, 3),
    ExifToolFunctionSignature(
        "Image::ExifTool::CanonVRD::ToneCurvePrint", "tone_curve_print", 1, 1
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::CanonVRD::ToneCurvePrintInv",
        "tone_curve_print_inv",
        1,
        1,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::Exif::ConvertExifText",
        "convert_exif_text",
        2,
        4,
    ),
    ExifToolFunctionSignature("Image::ExifTool::Exif::CalculateLV", "calculate_lv", 3, 3),
    ExifToolFunctionSignature(
        "Image::ExifTool::Exif::CalcScaleFactor35efl",
        "calc_scale_factor_35efl",
        3,
        20,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::Exif::EncodeExifText",
        "encode_exif_text",
        2,
        2,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::Exif::ConvertFraction",
        "convert_fraction",
        1,
        1,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::Exif::ConvertParameter",
        "convert_parameter",
        1,
        1,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::Exif::DecodeCFAPattern",
        "decode_cfa_pattern",
        2,
        2,
    ),
    ExifToolFunctionSignature("Image::ExifTool::Exif::ExifDate", "exif_date", 1, 1),
    ExifToolFunctionSignature("Image::ExifTool::Exif::ExifTime", "exif_time", 1, 1),
    ExifToolFunctionSignature("Image::ExifTool::Exif::GetCFAPattern", "get_cfa_pattern", 1, 1),
    ExifToolFunctionSignature(
        "Image::ExifTool::Exif::PrintExposureTime",
        "print_exposure_time",
        1,
        1,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::Exif::PrintCFAPattern",
        "print_cfa_pattern",
        1,
        1,
    ),
    ExifToolFunctionSignature("Image::ExifTool::Exif::PrintFNumber", "print_fnumber", 1, 1),
    ExifToolFunctionSignature(
        "Image::ExifTool::Exif::PrintFraction",
        "print_fraction",
        1,
        1,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::Exif::RedBlueBalance",
        "red_blue_balance",
        2,
        10,
    ),
    ExifToolFunctionSignature("Image::ExifTool::FLIR::GetImageType", "flir_get_image_type", 3, 3),
    ExifToolFunctionSignature("Image::ExifTool::GPS::PrintTimeStamp", "print_time_stamp", 1, 1),
    ExifToolFunctionSignature(
        "Image::ExifTool::GPS::ConvertTimeStamp",
        "gps_convert_time_stamp",
        1,
        1,
    ),
    ExifToolFunctionSignature("Image::ExifTool::GPS::ToDMS", "gps_to_dms", 2, 4),
    ExifToolFunctionSignature("Image::ExifTool::GPS::ToDegrees", "gps_to_degrees", 1, 3),
    ExifToolFunctionSignature("Image::ExifTool::GoPro::AddUnits", "gopro_add_units", 3, 3),
    ExifToolFunctionSignature("Image::ExifTool::ID3::ConvertID3v1Text", "convert_id3v1_text", 2, 2),
    ExifToolFunctionSignature("Image::ExifTool::ID3::PrintGenre", "print_genre", 1, 1),
    ExifToolFunctionSignature("Image::ExifTool::ICC_Profile::HexID", "hex_id", 1, 1),
    ExifToolFunctionSignature(
        "Image::ExifTool::IPTC::ConvertPictureNumber",
        "convert_picture_number",
        1,
        1,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::IPTC::InvConvertPictureNumber",
        "inv_convert_picture_number",
        1,
        1,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::IPTC::InverseDateOrTime",
        "inverse_date_or_time",
        2,
        2,
    ),
    ExifToolFunctionSignature("Image::ExifTool::IPTC::IptcDate", "iptc_date", 1, 1),
    ExifToolFunctionSignature("Image::ExifTool::IPTC::IptcTime", "iptc_time", 1, 1),
    ExifToolFunctionSignature(
        "Image::ExifTool::Jpeg2000::ProcessJXLCodestream",
        "jpeg2000_process_jxl_codestream",
        2,
        2,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::Kodak::CalculateRGBLevels",
        "kodak_calculate_rgb_levels",
        9,
        11,
    ),
    ExifToolFunctionSignature("Image::ExifTool::LNK::DOSTime", "dos_time", 1, 1),
    ExifToolFunctionSignature("Image::ExifTool::MakeTiffHeader", "make_tiff_header", 4, 6),
    ExifToolFunctionSignature(
        "Image::ExifTool::Minolta::ConvertWhiteBalance",
        "convert_white_balance",
        1,
        1,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::MinoltaRaw::ConvertWBMode",
        "convert_wb_mode",
        1,
        1,
    ),
    ExifToolFunctionSignature("Image::ExifTool::Nikon::PrintPC", "nikon_print_pc", 1, 4),
    ExifToolFunctionSignature("Image::ExifTool::Nikon::PrintPCInv", "nikon_print_pc_inv", 1, 2),
    ExifToolFunctionSignature("Image::ExifTool::Nikon::PrintPCInv2", "nikon_print_pc_inv2", 1, 2),
    ExifToolFunctionSignature(
        "Image::ExifTool::Olympus::ExtenderStatus",
        "olympus_extender_status",
        3,
        3,
    ),
    ExifToolFunctionSignature("Image::ExifTool::Olympus::PrintAFAreas", "print_af_areas", 1, 1),
    ExifToolFunctionSignature("Image::ExifTool::Pentax::PentaxEv", "pentax_ev", 1, 1),
    ExifToolFunctionSignature("Image::ExifTool::Pentax::PentaxEvInv", "pentax_ev_inv", 1, 1),
    ExifToolFunctionSignature(
        "Image::ExifTool::Pentax::DecodeAFPoints",
        "pentax_decode_af_points",
        4,
        5,
    ),
    ExifToolFunctionSignature("Image::ExifTool::PDF::ConvertPDFDate", "pdf_convert_pdf_date", 1, 1),
    ExifToolFunctionSignature(
        "Image::ExifTool::Photoshop::ConvertPascalString",
        "photoshop_convert_pascal_string",
        2,
        2,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::PostScript::ImageSize",
        "postscript_image_size",
        2,
        2,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::QuickTime::CalcRotation",
        "quicktime_calc_rotation",
        1,
        1,
    ),
    ExifToolFunctionSignature(
        "Image::ExifTool::QuickTime::CalcSampleRate",
        "quicktime_calc_sample_rate",
        2,
        2,
    ),
    ExifToolFunctionSignature("Image::ExifTool::RIFF::CalcDuration", "riff_calc_duration", 3, 5),
    ExifToolFunctionSignature("Image::ExifTool::RIFF::ConvertRIFFDate", "convert_riff_date", 1, 1),
    ExifToolFunctionSignature("Image::ExifTool::Samsung::Crypt", "samsung_crypt", 4, 999),
    ExifToolFunctionSignature(
        "Image::ExifTool::Sony::PrintInvLensSpec",
        "print_inv_lens_spec",
        1,
        3,
    ),
    ExifToolFunctionSignature("Image::ExifTool::XMP::ConvertXMPDate", "convert_xmp_date", 1, 2),
    ExifToolFunctionSignature("Image::ExifTool::XMP::DecodeBase64", "decode_base64", 1, 1),
    ExifToolFunctionSignature("Image::ExifTool::XMP::EncodeBase64", "encode_base64", 1, 2),
    ExifToolFunctionSignature("Image::ExifTool::XMP::FormatXMPDate", "format_xmp_date", 1, 1),
    ExifToolFunctionSignature("PrintHex", "print_hex", 1, 1),
    ExifToolFunctionSignature("TimeZoneString", "time_zone_string", 1, 1),
    ExifToolFunctionSignature("ToFloat", "to_float", 1, 999),
    ExifToolFunctionSignature("MakeTiffHeader", "make_tiff_header", 4, 6),
)

SINGLE_ARGUMENT_HELPERS: dict[ExifToolFunction, SingleArgumentHelper] = {
    "canon_ev": canon_ev,
    "canon_ev_inv": canon_ev_inv,
    "convert_bitrate": convert_bitrate,
    "convert_duration": convert_duration,
    "convert_file_size": convert_file_size,
    "convert_parameter": convert_parameter,
    "convert_picture_number": convert_picture_number,
    "convert_riff_date": convert_riff_date,
    "convert_white_balance": convert_white_balance,
    "convert_wb_mode": convert_wb_mode,
    "convert_fraction": convert_fraction,
    "decode_base64": decode_base64,
    "dos_time": dos_time,
    "exif_date": exif_date,
    "exif_time": exif_time,
    "format_xmp_date": format_xmp_date,
    "get_cfa_pattern": get_cfa_pattern,
    "get_guid": get_guid,
    "gps_convert_time_stamp": gps_convert_time_stamp,
    "hex_id": hex_id,
    "inv_convert_picture_number": inv_convert_picture_number,
    "iptc_date": iptc_date,
    "iptc_time": iptc_time,
    "pentax_ev": pentax_ev,
    "pentax_ev_inv": pentax_ev_inv,
    "pdf_convert_pdf_date": convert_pdf_date,
    "print_af_areas": print_af_areas,
    "print_af_points_1d": print_af_points_1d,
    "print_cfa_pattern": print_cfa_pattern,
    "print_exposure_time": print_exposure_time,
    "print_fnumber": print_fnumber,
    "print_fraction": print_fraction,
    "print_genre": print_genre,
    "print_time_stamp": print_time_stamp,
    "time_zone_string": time_zone_string,
    "tone_curve_print": tone_curve_print,
    "tone_curve_print_inv": tone_curve_print_inv,
    "print_hex": print_hex,
}

MULTI_ARGUMENT_HELPERS: dict[ExifToolFunction, MultiArgumentHelper] = {
    "calculate_lv": calculate_lv,
    "camera_iso": camera_iso,
    "convert_date_time": convert_date_time,
    "convert_unix_time": convert_unix_time,
    "convert_exif_text": convert_exif_text,
    "decode_bits": decode_bits,
    "encode_exif_text": encode_exif_text,
    "convert_id3v1_text": convert_id3v1_text,
    "convert_time_span": convert_time_span,
    "convert_xmp_date": convert_xmp_date,
    "encode_base64": encode_base64,
    "get_unix_time": get_unix_time,
    "gps_to_degrees": gps_to_degrees,
    "gps_to_dms": gps_to_dms,
    "gps_geolocate_print_conv_inv": geolocate_print_conv_inv,
    "inverse_date_or_time": inverse_date_or_time,
    "kodak_calculate_rgb_levels": calculate_rgb_levels,
    "make_tiff_header": make_tiff_header,
    "nikon_print_pc": nikon_print_pc,
    "nikon_print_pc_inv": nikon_print_pc_inv,
    "nikon_print_pc_inv2": nikon_print_pc_inv2,
    "olympus_extender_status": extender_status,
    "pentax_decode_af_points": pentax_decode_af_points,
    "photoshop_convert_pascal_string": convert_pascal_string,
    "print_inv_lens_spec": print_inv_lens_spec,
    "print_focal_range": print_focal_range,
    "red_blue_balance": red_blue_balance,
    "to_float": to_float,
}

REFERENCE_ARGUMENT_HELPERS: dict[ExifToolFunction, ReferenceArgumentHelper] = {
    "calc_scale_factor_35efl": calc_scale_factor_35efl,
    "decode_cfa_pattern": decode_cfa_pattern,
    "flir_get_image_type": flir_get_image_type,
    "gopro_add_units": gopro_add_units,
    "postscript_image_size": postscript_image_size,
    "quicktime_calc_rotation": quicktime_calc_rotation,
    "quicktime_ar_drone_telemetry": quicktime_ar_drone_telemetry,
    "quicktime_calc_sample_rate": quicktime_calc_sample_rate,
    "quicktime_free_payload_offsets": quicktime_free_payload_offsets,
    "composite_canon_file_number": composite_canon_file_number,
    "composite_depth_of_field": composite_depth_of_field,
    "composite_field_of_view": composite_field_of_view,
    "composite_xmp_flash_value": composite_xmp_flash_value,
    "garmin_gps_hundredths": garmin_gps_hundredths,
    "fujifilm_raf_layout_dimensions": fujifilm_raf_layout_dimensions,
    "lif_timestamp_list": lif_timestamp_list,
    "moi_aspect_ratio": moi_aspect_ratio,
    "nikon_auto_capture_area_bits": nikon_auto_capture_area_bits,
    "nikon_auto_capture_trigger_bits": nikon_auto_capture_trigger_bits,
    "nikon_lens_drive_end": nikon_lens_drive_end,
    "nikon_focus_shift_frame": nikon_focus_shift_frame,
    "nikon_z9_af_area_x": nikon_z9_af_area_x,
    "nikon_z9_af_area_y": nikon_z9_af_area_y,
    "olympus_panorama_direction": olympus_panorama_direction,
    "phase_one_sensor_calibration": phase_one_sensor_calibration,
    "quicktime_camm6_timestamp": quicktime_camm6_timestamp,
    "reconyx_hyperfire_datetime": reconyx_hyperfire_datetime,
    "riff_calc_duration": riff_calc_duration,
    "samsung_crypt": samsung_crypt,
    "tnef_decompress_rtf": tnef_decompress_rtf,
}

EFFECT_ARGUMENT_HELPERS: dict[ExifToolFunction, EffectArgumentHelper] = {
    "exif_identify_raw_file_compression": exif_identify_raw_file_compression,
    "gopro_system_time_list_update": gopro_system_time_list_update,
    "jpeg2000_process_jxl_codestream": process_jxl_codestream,
    "nikon_lens_drive_end_update": nikon_lens_drive_end_update,
    "panasonic_pana_thumb_type": panasonic_pana_thumb_type,
    "quicktime_handler_type_update": quicktime_handler_type_update,
    "riff_anmf_frame_duration": riff_anmf_frame_duration,
    "samsung_encryption_key_update": samsung_encryption_key_update,
}


def exiftool_signature_or_none(name: str) -> ExifToolFunctionSignature | None:
    for signature in EXIFTOOL_FUNCTION_SIGNATURES:
        if name == signature.perl_name:
            return signature
    return None


def evaluate_exiftool_function(
    function: ExifToolFunction,
    values: list[ExifToolValue],
) -> ExifToolValue:
    reference_argument_helper = REFERENCE_ARGUMENT_HELPERS.get(function)
    if reference_argument_helper is not None:
        return reference_argument_helper(values)
    scalar_values = exiftool_scalar_values(function, values)
    multi_argument_helper = MULTI_ARGUMENT_HELPERS.get(function)
    if multi_argument_helper is not None:
        return multi_argument_helper(scalar_values)
    single_argument_helper = SINGLE_ARGUMENT_HELPERS.get(function)
    if single_argument_helper is not None:
        return single_argument_helper(single_exiftool_argument(function, scalar_values))
    raise ExifToolCompatibilityError(f"Unsupported ExifTool function: {function}")


def evaluate_exiftool_effect_function(
    function: ExifToolFunction,
    values: list[ExifToolValue],
) -> ExifToolEffectResult | None:
    effect_argument_helper = EFFECT_ARGUMENT_HELPERS.get(function)
    if effect_argument_helper is None:
        return None
    return effect_argument_helper(values)


def exiftool_function_has_effects(function: ExifToolFunction) -> bool:
    return function in EFFECT_ARGUMENT_HELPERS


def exiftool_scalar_values(
    function: ExifToolFunction,
    values: list[ExifToolValue],
) -> list[ExifToolScalar]:
    scalar_values: list[ExifToolScalar] = []
    for value in values:
        if isinstance(value, (tuple, ExifToolHashReference, ExifToolScalarReference)):
            raise ExifToolCompatibilityError(
                f"ExifTool function {function} does not accept reference arguments."
            )
        scalar_values.append(value)
    return scalar_values


def single_exiftool_argument(
    function: ExifToolFunction,
    values: list[ExifToolScalar],
) -> ExifToolScalar:
    if len(values) != 1:
        raise ExifToolCompatibilityError(
            f"ExifTool function {function} expected 1 argument, got {len(values)}."
        )
    return values[0]
