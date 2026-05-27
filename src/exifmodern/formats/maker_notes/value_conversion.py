"""Runtime rendering for scalar maker-note ValueConv expressions."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, assert_never

from exifmodern.formats.maker_notes.context import (
    EMPTY_MAKER_NOTE_RUNTIME_CONTEXT,
    MakerNoteRuntimeBoundary,
    MakerNoteRuntimeContext,
    maker_note_runtime_context_to_json,
)
from exifmodern.json_types import JsonArray, JsonObject, JsonValue
from exifmodern.safe_expression.vm import (
    ArrayReferenceValue,
    HashReferenceValue,
    SafeExpressionVmError,
    ScalarReferenceValue,
    VmScalar,
    VmValue,
    evaluate_program,
)
from exifmodern.services.maker_note_tables import (
    MakerNoteTableRepository,
    MakerNoteTagLocation,
    load_maker_note_table_repository,
)
from exifmodern.services.queries.maker_note import locations_to_json

type MakerNoteValueConversionStatus = Literal[
    "converted",
    "missing_entry",
    "not_scalar_value_conversion",
    "unsupported_expression",
    "evaluation_error",
]


@dataclass(frozen=True)
class MakerNoteValueConversionRequest:
    raw_value: str
    vendor: str = ""
    module: str = ""
    table: str = ""
    tag_name: str = ""
    tag_id: str = ""
    runtime_context: MakerNoteRuntimeContext = EMPTY_MAKER_NOTE_RUNTIME_CONTEXT
    limit: int | None = None


@dataclass(frozen=True)
class MakerNoteValueConversionMatch:
    location: MakerNoteTagLocation
    status: MakerNoteValueConversionStatus
    converted_value: JsonValue
    error: str

    @property
    def converted(self) -> bool:
        return self.status == "converted"


@dataclass(frozen=True)
class MakerNoteDomainValueConversion:
    converted_value: JsonValue


@dataclass(frozen=True)
class MakerNoteValueConversionResult:
    request: MakerNoteValueConversionRequest
    repository: MakerNoteTableRepository
    candidate_count: int
    matches: tuple[MakerNoteValueConversionMatch, ...]

    @property
    def converted_count(self) -> int:
        return sum(1 for match in self.matches if match.converted)

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "request": maker_note_value_conversion_request_to_json(self.request),
            "source_count": self.repository.source_count,
            "table_count": self.repository.table_count,
            "tag_entry_count": self.repository.tag_entry_count,
            "candidate_count": self.candidate_count,
            "match_count": len(self.matches),
            "converted_count": self.converted_count,
            "matches": maker_note_value_conversion_matches_to_json(self.matches),
        }


def run_maker_note_value_conversion(
    maker_note_package: Path,
    request: MakerNoteValueConversionRequest,
) -> MakerNoteValueConversionResult:
    repository = load_maker_note_table_repository(maker_note_package)
    return render_maker_note_value_conversion(repository, request)


def render_maker_note_value_conversion(
    repository: MakerNoteTableRepository,
    request: MakerNoteValueConversionRequest,
) -> MakerNoteValueConversionResult:
    candidates = repository.tag_entry_locations_for(
        vendor=request.vendor,
        module=request.module,
        table=request.table,
        tag_name=request.tag_name,
        tag_id=request.tag_id,
    )
    matches = tuple(
        render_maker_note_value_conversion_match(
            location,
            request.raw_value,
            request.runtime_context,
        )
        for location in candidates
    )
    limited_matches = matches if request.limit is None else matches[: request.limit]
    return MakerNoteValueConversionResult(
        request=request,
        repository=repository,
        candidate_count=len(candidates),
        matches=limited_matches,
    )


def render_maker_note_value_conversion_match(
    location: MakerNoteTagLocation,
    raw_value: str,
    runtime_context: MakerNoteRuntimeContext = EMPTY_MAKER_NOTE_RUNTIME_CONTEXT,
) -> MakerNoteValueConversionMatch:
    entry = location.entry
    domain_value = render_domain_value_conversion(location, raw_value, runtime_context)
    if domain_value is not None:
        return MakerNoteValueConversionMatch(
            location=location,
            status="converted",
            converted_value=domain_value.converted_value,
            error="",
        )
    if maker_note_domain_value_conversion_adapter_supported(location):
        return MakerNoteValueConversionMatch(
            location=location,
            status="evaluation_error",
            converted_value=None,
            error="domain adapter returned no value",
        )
    if entry.value_conv_kind != "scalar" or not entry.value_conv_text:
        return MakerNoteValueConversionMatch(
            location=location,
            status="not_scalar_value_conversion",
            converted_value=None,
            error="",
        )
    adapter_value = render_scalar_value_conversion(entry.value_conv_text, raw_value)
    if adapter_value is not None:
        return MakerNoteValueConversionMatch(
            location=location,
            status="converted",
            converted_value=adapter_value,
            error="",
        )
    from exifmodern.safe_expression.compat_compiler import compile_safe_expression

    program = compile_safe_expression(entry.value_conv_text)
    if program is None:
        return MakerNoteValueConversionMatch(
            location=location,
            status="unsupported_expression",
            converted_value=None,
            error="",
        )
    try:
        converted = evaluate_program(program, {"$val": raw_value})
    except SafeExpressionVmError as exc:
        return MakerNoteValueConversionMatch(
            location=location,
            status="evaluation_error",
            converted_value=None,
            error=str(exc),
        )
    return MakerNoteValueConversionMatch(
        location=location,
        status="converted",
        converted_value=vm_value_to_json(converted),
        error="",
    )


def maker_note_scalar_value_conversion_adapter_supported(expression: str) -> bool:
    return (
        expression.strip()
        in {
            "PrintHex($val)",
            'my ($a,$b,$c)=unpack("c3",$val); $c ? $a*($b/$c) : 0',
            'my ($a,$b,$c)=unpack("C3",$val); $c ? $a*($b/$c) : 0',
            'my @v=reverse split(" ",$val);"@v"',
            'substr($val, 2, unpack("C",$val))',
            '$_=sprintf("%.4x",$val); s/(..)(..)/$2 $1/; $_',
            "$val =~ tr/\\0//d; $val",
            "$val=~tr/\\0/\\n/; $val",
            "$val=~tr/ /./; $val",
            "$val=~s{/}{:}g; $val",
            "$val=~tr/./:/; $val=~s/(\\d+:\\d+:\\d+):/$1 /; $val",
            'join ".", $val =~ /../g',
            'join " ", unpack "H2H2", $val',
            'my @v=split(" ",$val); $_*=15 foreach @v; "$v[1] $v[0] $v[3] $v[2]"',
            '$_=$val; /^[\\x00-\\x09]/ and $_=join("",unpack("CCCC",$_)); $_',
            'unpack("n", $val)',
            "$val=~s/( 0)+$//; $val",
            '$val=~s/ 1$// ? -$val/10 : "n/a"',
            '$val =~ s/ 1$// ? $val / 10 : "n/a"',
            "$val =~ /(\\d{2})(\\d{2})(\\d{2})/ ? ($1 * 60 + $2) * 60 + $3 : undef",
            "$val =~ s/^8 //; $val",
            "$val =~ s/(\\d{2})/$1./; $val",
            "$val =~ s/ 0$//; $val",
            "$val =~ s/\\s+$//; $val",
            "$val =~ s/^(\\d{2})(\\d{2})/$1:$2:/; $val",
            "$val =~ s/Qual:\\s*//, $val",
            'length($val)==4 ? sprintf("%.4d:%.2d:%.2d",unpack("nC2",$val)) : "Unknown ($val)"',
            'length($val)>=3 ? sprintf("%.2d:%.2d:%.2d",unpack("C3",$val)) : "Unknown ($val)"',
            '$self->Options("Unknown") ? $val : $val & 0x7ff',
            'my @a=unpack("x1H4H2H2H2H2H2",$val); "$a[0]:$a[1]:$a[2] $a[3]:$a[4]:$a[5]"',
            'my @a = join " ", map { $_ / 100} split " "',
        }
        or is_olympus_wav_datetime_value_expression(expression.strip())
        or is_sony_datetime_vc_expression(expression.strip())
        or is_pentax_manufacture_date_expression(expression.strip())
    )


def maker_note_domain_value_conversion_adapter_supported(location: MakerNoteTagLocation) -> bool:
    return (
        is_pentax_kelvin_wb_location(location)
        or is_pentax_color_temp_location(location)
        or is_pentax_firmware_id_location(location)
        or is_pentax_auto_bracketing_location(location)
        or is_pentax_iso_auto_min_speed_location(location)
        or is_sony_meter_info9_location(location)
        or is_sony_lens_spec_value_location(location)
        or is_sony_extra_info_battery_location(location)
        or is_sony_iso_info_location(location)
        or is_minolta_ae_metering_segments_location(location)
        or is_canon_raw_measured_rggb_location(location)
        or is_canon_composite_file_number_location(location)
        or is_pentax_shutter_count_location(location)
    )


def maker_note_value_conversion_runtime_boundary(
    location: MakerNoteTagLocation,
) -> MakerNoteRuntimeBoundary:
    if is_minolta_tiff_metering_image_location(location) or is_sony_tiff_metering_image_location(
        location
    ):
        return "binary_tiff_output"
    if is_pentax_shutter_count_location(location):
        return "object_state_context"
    return "none"


def maker_note_domain_value_conversion_blocker_reason(
    location: MakerNoteTagLocation,
) -> str | None:
    if is_minolta_tiff_metering_image_location(location):
        return "requires ExifTool Binary option and TIFF header/binary output state"
    if is_sony_tiff_metering_image_location(location):
        return "requires ExifTool Binary option and TIFF header/binary output state"
    return None


def render_domain_value_conversion(
    location: MakerNoteTagLocation,
    raw_value: str,
    runtime_context: MakerNoteRuntimeContext = EMPTY_MAKER_NOTE_RUNTIME_CONTEXT,
) -> MakerNoteDomainValueConversion | None:
    if is_pentax_kelvin_wb_location(location):
        converted = pentax_kelvin_wb(raw_value)
        if converted is not None:
            return MakerNoteDomainValueConversion(converted_value=converted)
    if is_pentax_color_temp_location(location):
        return MakerNoteDomainValueConversion(converted_value=pentax_color_temp(raw_value))
    if is_pentax_firmware_id_location(location):
        return MakerNoteDomainValueConversion(converted_value=pentax_firmware_id(raw_value))
    if is_pentax_auto_bracketing_location(location):
        converted = pentax_auto_bracketing_value(raw_value)
        if converted is not None:
            return MakerNoteDomainValueConversion(converted_value=converted)
    if is_pentax_iso_auto_min_speed_location(location):
        converted = pentax_iso_auto_min_speed_value(raw_value)
        if converted is not None:
            return MakerNoteDomainValueConversion(converted_value=converted)
    if is_sony_meter_info9_location(location):
        meter_info = sony_meter_info9(raw_value, location.entry.name)
        if meter_info is not None:
            return MakerNoteDomainValueConversion(converted_value=meter_info)
    if is_sony_lens_spec_value_location(location):
        lens_spec = sony_lens_spec(raw_value)
        if lens_spec is not None:
            return MakerNoteDomainValueConversion(converted_value=lens_spec)
    if is_sony_extra_info_battery_location(location):
        battery_value = sony_extra_info_battery_value(raw_value, location.entry.name)
        if battery_value is not None:
            return MakerNoteDomainValueConversion(converted_value=battery_value)
    if is_sony_iso_info_location(location):
        iso_value = sony_iso_setting_2010(raw_value)
        if iso_value is not None:
            return MakerNoteDomainValueConversion(converted_value=iso_value)
    if is_minolta_ae_metering_segments_location(location):
        segments = minolta_ae_metering_segments(raw_value)
        if segments is not None:
            return MakerNoteDomainValueConversion(converted_value=segments)
    if is_canon_raw_measured_rggb_location(location):
        measured_rggb = canon_swap_words(raw_value)
        if measured_rggb is not None:
            return MakerNoteDomainValueConversion(converted_value=measured_rggb)
    if is_canon_composite_file_number_location(location):
        file_number = canon_composite_file_number(raw_value)
        if file_number is not None:
            return MakerNoteDomainValueConversion(converted_value=file_number)
    if is_pentax_shutter_count_location(location):
        shutter_count = pentax_shutter_count(raw_value, runtime_context)
        if shutter_count is not None:
            return MakerNoteDomainValueConversion(converted_value=shutter_count)
    return None


def is_pentax_kelvin_wb_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Pentax"
        and location.table.name == "KelvinWB"
        and location.entry.value_conv_kind == "code"
        and location.entry.format == "int16u[4]"
        and location.entry.name.startswith("KelvinWB_")
    )


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


def is_pentax_firmware_id_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Pentax"
        and location.table.name == "Main"
        and location.entry.value_conv_kind == "code"
        and location.entry.name in {"DSPFirmwareVersion", "CPUFirmwareVersion"}
    )


def is_pentax_auto_bracketing_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Pentax"
        and location.table.name == "Main"
        and location.entry.name == "AutoBracketing"
        and location.entry.value_conv_kind == "array"
    )


def is_pentax_iso_auto_min_speed_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Pentax"
        and location.table.name == "Main"
        and location.entry.name == "ISOAutoMinSpeed"
        and location.entry.value_conv_kind == "array"
    )


def is_sony_meter_info9_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Sony"
        and location.table.name == "MeterInfo9"
        and location.entry.value_conv_kind == "code"
        and location.entry.format in {"undef[90]", "undef[110]"}
        and (
            location.entry.name.startswith("MeterInfo1Row")
            or location.entry.name.startswith("MeterInfo2Row")
        )
    )


def is_sony_lens_spec_value_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Sony"
        and location.entry.name == "LensSpec"
        and location.entry.value_conv_kind == "code"
        and location.entry.print_conv_kind == "code"
        and location.entry.format in {"undef", "undef[8]"}
    )


def is_sony_extra_info_battery_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Sony"
        and location.table.name == "ExtraInfo"
        and location.entry.value_conv_kind == "code"
        and location.entry.format == "undef[4]"
        and location.entry.name in {"BatteryUnknown", "BatteryVoltage"}
    )


def is_sony_iso_info_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Sony"
        and location.table.name == "ISOInfo"
        and location.entry.value_conv_kind == "hash"
        and location.entry.name in {"ISOSetting", "ISOAutoMin", "ISOAutoMax"}
    )


def is_minolta_ae_metering_segments_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Minolta"
        and location.table.name == "WBInfoA100"
        and location.entry.name == "AEMeteringSegments"
        and location.entry.value_conv_kind == "code"
        and location.entry.format == "int8u[40]"
    )


def is_canon_raw_measured_rggb_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Canon"
        and location.table.name
        in {"ColorData2", "ColorData3", "ColorData4", "ColorData6", "ColorData7"}
        and location.entry.name in {"RawMeasuredRGGB", "MeasuredRGGBData"}
        and location.entry.value_conv_kind == "code"
        and location.entry.format == "int32u[4]"
    )


def is_canon_composite_file_number_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Canon"
        and location.table.name == "Composite"
        and location.entry.name == "FileNumber"
        and location.entry.value_conv_kind == "scalar"
    )


def is_minolta_tiff_metering_image_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Minolta"
        and location.table.name == "WBInfoA100"
        and location.entry.name == "TiffMeteringImage"
        and location.entry.value_conv_kind == "code"
        and location.entry.format == "undef[9600]"
    )


def is_sony_tiff_metering_image_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Sony"
        and location.entry.name == "TiffMeteringImage"
        and location.entry.value_conv_kind == "code"
        and location.table.name in {"FocusInfo", "MoreInfo", "Tag940e"}
    )


def is_pentax_shutter_count_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Pentax"
        and location.table.name == "Main"
        and location.entry.name == "ShutterCount"
        and location.entry.value_conv_kind == "code"
        and location.entry.tag_id == "93"
    )


def render_scalar_value_conversion(expression: str, raw_value: str) -> JsonValue:
    normalized = expression.strip()
    if normalized == "PrintHex($val)":
        return print_hex(raw_value)
    if normalized == 'my ($a,$b,$c)=unpack("c3",$val); $c ? $a*($b/$c) : 0':
        return packed_nikon_fraction(raw_value, signed=True)
    if normalized == 'my ($a,$b,$c)=unpack("C3",$val); $c ? $a*($b/$c) : 0':
        return packed_nikon_fraction(raw_value, signed=False)
    if normalized == 'my @v=reverse split(" ",$val);"@v"':
        return " ".join(reversed(raw_value.split()))
    if normalized == 'substr($val, 2, unpack("C",$val))':
        if not raw_value:
            return ""
        return raw_value[2 : 2 + ord(raw_value[0])]
    if normalized == '$_=sprintf("%.4x",$val); s/(..)(..)/$2 $1/; $_':
        try:
            value = int(float(raw_value))
        except ValueError:
            return None
        formatted = f"{value:04x}"
        return formatted[2:4] + " " + formatted[0:2]
    if normalized == "$val =~ tr/\\0//d; $val":
        return raw_value.replace("\x00", "")
    if normalized == "$val=~tr/\\0/\\n/; $val":
        return raw_value.replace("\x00", "\n")
    if normalized == "$val=~tr/ /./; $val":
        return raw_value.replace(" ", ".")
    if normalized == "$val=~s{/}{:}g; $val":
        return raw_value.replace("/", ":")
    if normalized == "$val=~tr/./:/; $val=~s/(\\d+:\\d+:\\d+):/$1 /; $val":
        return replace_casio_qvci_datetime_separator(raw_value)
    if normalized == 'join ".", $val =~ /../g':
        return ".".join(raw_value[index : index + 2] for index in range(0, len(raw_value) - 1, 2))
    if normalized == 'join " ", unpack "H2H2", $val':
        return sony_lens_spec_feature_bytes(raw_value)
    if normalized == 'my @v=split(" ",$val); $_*=15 foreach @v; "$v[1] $v[0] $v[3] $v[2]"':
        return sony_face_position(raw_value)
    if normalized == '$_=$val; /^[\\x00-\\x09]/ and $_=join("",unpack("CCCC",$_)); $_':
        return nikon_maker_note_version(raw_value)
    if normalized == 'unpack("n", $val)':
        return unpack_big_endian_uint16(raw_value)
    if normalized == "$val=~s/( 0)+$//; $val":
        return trim_nikon_retouch_history(raw_value)
    if normalized == '$val=~s/ 1$// ? -$val/10 : "n/a"':
        return olympus_level_angle(raw_value, negate=True)
    if normalized == '$val =~ s/ 1$// ? $val / 10 : "n/a"':
        return olympus_level_angle(raw_value, negate=False)
    if normalized == "$val =~ /(\\d{2})(\\d{2})(\\d{2})/ ? ($1 * 60 + $2) * 60 + $3 : undef":
        return olympus_dss_duration_seconds(raw_value)
    if normalized == "$val =~ s/^8 //; $val":
        return perl_substitute(raw_value, r"^8 ", "", count=1)
    if normalized == "$val =~ s/(\\d{2})/$1./; $val":
        return perl_substitute(raw_value, r"(\d{2})", r"\1.", count=1)
    if normalized == "$val =~ s/ 0$//; $val":
        return perl_substitute(raw_value, r" 0$", "", count=1)
    if normalized == "$val =~ s/\\s+$//; $val":
        return perl_substitute(raw_value, r"\s+$", "", count=1)
    if normalized == "$val =~ s/^(\\d{2})(\\d{2})/$1:$2:/; $val":
        return perl_substitute(raw_value, r"^(\d{2})(\d{2})", r"\1:\2:", count=1)
    if normalized == "$val =~ s/Qual:\\s*//, $val":
        return perl_substitute(raw_value, r"Qual:\s*", "", count=1)
    if (
        normalized
        == 'length($val)==4 ? sprintf("%.4d:%.2d:%.2d",unpack("nC2",$val)) : "Unknown ($val)"'
    ):
        return pentax_date(raw_value)
    if (
        normalized
        == 'length($val)>=3 ? sprintf("%.2d:%.2d:%.2d",unpack("C3",$val)) : "Unknown ($val)"'
    ):
        return pentax_time(raw_value)
    if normalized == '$self->Options("Unknown") ? $val : $val & 0x7ff':
        return pentax_af_point_mask(raw_value)
    if normalized == 'my @a=unpack("x1H4H2H2H2H2H2",$val); "$a[0]:$a[1]:$a[2] $a[3]:$a[4]:$a[5]"':
        return sony_rtmd_datetime(raw_value)
    if normalized == 'my @a = join " ", map { $_ / 100} split " "':
        return garmin_velocity(raw_value)
    if is_sony_datetime_vc_expression(normalized):
        return sony_datetime_vc(raw_value)
    if is_olympus_wav_datetime_value_expression(normalized):
        return olympus_wav_datetime(raw_value)
    if is_pentax_manufacture_date_expression(normalized):
        return pentax_manufacture_date(raw_value)
    return None


def garmin_velocity(raw_value: str) -> str | None:
    converted: list[str] = []
    for value in raw_value.split():
        parsed = parse_integer_word(value)
        if parsed is None:
            return None
        converted.append(format_perl_number(parsed / 100))
    return " ".join(converted)


def packed_nikon_fraction(raw_value: str, *, signed: bool) -> float | int:
    values = tuple(ord(character) for character in raw_value[:3])
    if len(values) < 3:
        return 0
    first, second, third = values
    if signed and first > 127:
        first -= 256
    if not third:
        return 0
    return first * (second / third)


def replace_casio_qvci_datetime_separator(raw_value: str) -> str:
    colon_value = raw_value.replace(".", ":")
    return reformat_first_datetime_colon(colon_value)


def reformat_first_datetime_colon(value: str) -> str:
    parts = value.split(":", 3)
    if len(parts) < 4:
        return value
    return parts[0] + ":" + parts[1] + ":" + parts[2] + " " + parts[3]


def perl_substitute(value: str, pattern: str, replacement: str, *, count: int) -> str:
    return re.sub(pattern, replacement, value, count=count)


def print_hex(raw_value: str) -> str:
    return " ".join(f"{ord(character):02x}" for character in raw_value)


def sony_lens_spec_feature_bytes(raw_value: str) -> str:
    return " ".join(f"{ord(character):02x}" for character in raw_value[:2])


def sony_face_position(raw_value: str) -> str | None:
    values = split_numeric_words(raw_value)
    if len(values) < 4:
        return None
    scaled = tuple(value * 15 for value in values[:4])
    reordered = (scaled[1], scaled[0], scaled[3], scaled[2])
    return " ".join(format_perl_number(value) for value in reordered)


def nikon_maker_note_version(raw_value: str) -> str:
    if raw_value and "\x00" <= raw_value[0] <= "\x09":
        return "".join(str(ord(character)) for character in raw_value[:4])
    return raw_value


def unpack_big_endian_uint16(raw_value: str) -> int | None:
    if len(raw_value) < 2:
        return None
    return ord(raw_value[0]) * 256 + ord(raw_value[1])


def trim_nikon_retouch_history(raw_value: str) -> str:
    while raw_value.endswith(" 0"):
        raw_value = raw_value[:-2]
    return raw_value


def olympus_level_angle(raw_value: str, *, negate: bool) -> float | int | str:
    if not raw_value.endswith(" 1"):
        return "n/a"
    value_text = raw_value[:-2]
    try:
        value = float(value_text) / 10
    except ValueError:
        return "n/a"
    if negate:
        value = -value
    return format_numeric_json_value(value)


def olympus_dss_duration_seconds(raw_value: str) -> int | None:
    match = re.search(r"(\d{2})(\d{2})(\d{2})", raw_value)
    if match is None:
        return None
    hours, minutes, seconds = (int(part) for part in match.groups())
    return (hours * 60 + minutes) * 60 + seconds


def is_olympus_wav_datetime_value_expression(expression: str) -> bool:
    return (
        "return undef unless $val =~ /^(\\d{2})(\\d{2})(\\d{2})(\\d{2})(\\d{2})(\\d{2})$/;"
        in expression
        and 'my $y = $1 < 70 ? "20$1" : "19$1";' in expression
        and 'return "$y:$2:$3 $4:$5:$6";' in expression
    )


def olympus_wav_datetime(raw_value: str) -> str | None:
    match = re.fullmatch(r"(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", raw_value)
    if match is None:
        return None
    year, month, day, hour, minute, second = match.groups()
    year_prefix = "20" if int(year) < 70 else "19"
    return f"{year_prefix}{year}:{month}:{day} {hour}:{minute}:{second}"


def is_sony_datetime_vc_expression(expression: str) -> bool:
    return (
        "my @v = unpack('vC*', $val);" in expression
        and 'return sprintf("%.4d:%.2d:%.2d %.2d:%.2d:%.2d", @v)' in expression
    )


def sony_datetime_vc(raw_value: str) -> str | None:
    if len(raw_value) < 7:
        return None
    year = little_endian_uint16(raw_value, 0)
    return (
        f"{year:04d}:{ord(raw_value[2]):02d}:{ord(raw_value[3]):02d} "
        f"{ord(raw_value[4]):02d}:{ord(raw_value[5]):02d}:{ord(raw_value[6]):02d}"
    )


def split_numeric_words(raw_value: str) -> tuple[float, ...]:
    try:
        return tuple(float(part) for part in raw_value.split())
    except ValueError:
        return ()


def format_numeric_json_value(value: float) -> float | int:
    if value.is_integer():
        return int(value)
    return value


def format_perl_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)


def pentax_af_point_mask(raw_value: str) -> int | None:
    try:
        return int(float(raw_value)) & 0x7FF
    except ValueError:
        return None


def pentax_date(raw_value: str) -> str:
    if len(raw_value) != 4:
        return f"Unknown ({raw_value})"
    year = ord(raw_value[0]) * 256 + ord(raw_value[1])
    return f"{year:04d}:{ord(raw_value[2]):02d}:{ord(raw_value[3]):02d}"


def pentax_time(raw_value: str) -> str:
    if len(raw_value) < 3:
        return f"Unknown ({raw_value})"
    return f"{ord(raw_value[0]):02d}:{ord(raw_value[1]):02d}:{ord(raw_value[2]):02d}"


def pentax_shutter_count(
    raw_value: str,
    runtime_context: MakerNoteRuntimeContext,
) -> int | None:
    encrypted_count = parse_integer_word(raw_value)
    pentax_date_value = runtime_context.self_string(("PentaxDate",))
    pentax_time_value = runtime_context.self_string(("PentaxTime",))
    if (
        encrypted_count is None
        or pentax_date_value is None
        or pentax_time_value is None
        or len(pentax_date_value) != 4
        or len(pentax_time_value) < 3
    ):
        return None
    date = big_endian_integer(pentax_date_value[:4])
    time = big_endian_integer(pentax_time_value[:3] + "\0")
    return encrypted_count ^ date ^ (0xFFFFFFFF - time)


def big_endian_integer(raw_value: str) -> int:
    value = 0
    for character in raw_value:
        value = value * 256 + ord(character)
    return value


def is_pentax_manufacture_date_expression(expression: str) -> bool:
    return (
        '$val =~ /^(\\d{4})(\\d{2})(\\d{2})$/ and return "$1:$2:$3";' in expression
        and '$val =~ /^(\\d)(\\d{2})(\\d{2})$/ and return "200$1:$2:$3";' in expression
        and 'return "Unknown ($val)";' in expression
    )


def pentax_manufacture_date(raw_value: str) -> str:
    full_match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", raw_value)
    if full_match is not None:
        year, month, day = full_match.groups()
        return f"{year}:{month}:{day}"
    short_match = re.fullmatch(r"(\d)(\d{2})(\d{2})", raw_value)
    if short_match is not None:
        year, month, day = short_match.groups()
        return f"200{year}:{month}:{day}"
    return f"Unknown ({raw_value})"


def pentax_firmware_id(raw_value: str) -> str:
    if len(raw_value) != 4:
        return raw_value
    return " ".join(str(ord(character) ^ 0xFF) for character in raw_value)


def pentax_auto_bracketing_value(raw_value: str) -> str | None:
    values = raw_value.split()
    if not values:
        return None
    first_value = parse_integer_word(values[0])
    if first_value is None:
        return None
    converted = [pentax_auto_bracketing_step_value(first_value), *values[1:]]
    return " ".join(converted)


def pentax_auto_bracketing_step_value(value: int) -> str:
    if value < 10:
        return format_perl_number(value / 3)
    if value < 20:
        return format_perl_number(value - 9.5)
    if value & 0x1000:
        return f"{value - 0x1000}/2"
    if value & 0x2000:
        return f"{value - 0x2000}/3"
    return str(value)


def pentax_iso_auto_min_speed_value(raw_value: str) -> str | None:
    values = raw_value.split()
    if len(values) < 2:
        return None
    speed_code = parse_integer_word(values[1])
    if speed_code is None:
        return None
    converted = [values[0], format_perl_number(pentax_iso_auto_min_speed_seconds(speed_code))]
    converted.extend(values[2:])
    return " ".join(converted)


def pentax_iso_auto_min_speed_seconds(value: int) -> float | int:
    if not value:
        return 0
    return format_numeric_json_value(math.exp(-pentax_ev(value - 68) * math.log(2)))


def pentax_ev(value: int) -> float:
    adjusted = value
    adjusted_fraction = float(value)
    if adjusted & 0x01:
        sign = -1 if adjusted < 0 else 1
        fraction = (adjusted * sign) & 0x07
        if fraction == 0x03:
            adjusted_fraction += sign * (8 / 3 - fraction)
        elif fraction == 0x05:
            adjusted_fraction += sign * (16 / 3 - fraction)
    return adjusted_fraction / 8


def pentax_kelvin_wb(raw_value: str) -> str | None:
    values = split_numeric_words(raw_value)
    if len(values) < 4:
        return None
    converted = (
        53190 - values[0],
        values[1],
        values[2] / 8192,
        values[3] / 8192,
    )
    return " ".join(format_perl_number(value) for value in converted)


def pentax_color_temp(raw_value: str) -> str:
    if len(raw_value) != 4:
        return raw_value
    kelvin_raw = ord(raw_value[0]) * 256 + ord(raw_value[1])
    shift_byte = ord(raw_value[3])
    amber_blue_shift = signed_nibble(shift_byte & 0x0F)
    green_magenta_shift = signed_nibble(shift_byte >> 4)
    return " ".join(
        (
            str(53190 - kelvin_raw),
            str(amber_blue_shift),
            str(green_magenta_shift),
        )
    )


def signed_nibble(value: int) -> int:
    return value - 16 if value >= 8 else value


def sony_lens_spec(raw_value: str) -> str | None:
    if len(raw_value) != 8:
        return None
    values = (
        f"{ord(raw_value[0]):02x}",
        str(int(bytes_to_hex(raw_value, 1, 2), 16)),
        str(int(bytes_to_hex(raw_value, 3, 2), 16)),
        format_perl_number(sony_lens_spec_aperture(bytes_to_hex(raw_value, 5, 1))),
        format_perl_number(sony_lens_spec_aperture(bytes_to_hex(raw_value, 6, 1))),
        f"{ord(raw_value[7]):02x}",
    )
    return " ".join(values)


def bytes_to_hex(raw_value: str, offset: int, count: int) -> str:
    return "".join(f"{ord(character):02x}" for character in raw_value[offset : offset + count])


def sony_lens_spec_aperture(hex_byte: str) -> float:
    text = re.sub(r"([a-f])", lambda match: str(int(match.group(1), 16)), hex_byte, count=1)
    return float(text) / 10


def sony_meter_info9(raw_value: str, tag_name: str) -> str | None:
    if tag_name.startswith("MeterInfo1Row"):
        return sony_meter_info_row(raw_value, expected_length=90, triplet_count=9)
    if tag_name.startswith("MeterInfo2Row"):
        return sony_meter_info_row(raw_value, expected_length=110, triplet_count=11)
    return None


def sony_meter_info_row(
    raw_value: str,
    *,
    expected_length: int,
    triplet_count: int,
) -> str | None:
    if len(raw_value) != expected_length:
        return None
    values: list[int] = []
    offset = 0
    for _ in range(triplet_count):
        values.append(little_endian_uint16(raw_value, offset))
        values.append(little_endian_uint32(raw_value, offset + 2))
        values.append(little_endian_uint32(raw_value, offset + 6))
        offset += 10
    return " ".join(str(value) for value in values)


def little_endian_uint16(raw_value: str, offset: int) -> int:
    return ord(raw_value[offset]) | (ord(raw_value[offset + 1]) << 8)


def little_endian_uint32(raw_value: str, offset: int) -> int:
    return (
        ord(raw_value[offset])
        | (ord(raw_value[offset + 1]) << 8)
        | (ord(raw_value[offset + 2]) << 16)
        | (ord(raw_value[offset + 3]) << 24)
    )


def sony_extra_info_battery_value(raw_value: str, tag_name: str) -> float | int | None:
    if len(raw_value) != 4:
        return None
    converted = ord(raw_value[0]) + (ord(raw_value[3]) << 8)
    if tag_name == "BatteryVoltage":
        return format_numeric_json_value(converted / 118)
    return converted


def sony_iso_setting_2010(raw_value: str) -> str | int | None:
    value = parse_integer_word(raw_value)
    if value is None:
        return None
    iso_values: dict[int, str | int] = {
        0: "Auto",
        5: 25,
        7: 40,
        8: 50,
        9: 64,
        10: 80,
        11: 100,
        12: 125,
        13: 160,
        14: 200,
        15: 250,
        16: 320,
        17: 400,
        18: 500,
        19: 640,
        20: 800,
        21: 1000,
        22: 1250,
        23: 1600,
        24: 2000,
        25: 2500,
        26: 3200,
        27: 4000,
        28: 5000,
        29: 6400,
        30: 8000,
        31: 10000,
        32: 12800,
        33: 16000,
        34: 20000,
        35: 25600,
        36: 32000,
        37: 40000,
        38: 51200,
        39: 64000,
        40: 80000,
        41: 102400,
        42: 128000,
        43: 160000,
        44: 204800,
        45: 256000,
        46: 320000,
        47: 409600,
    }
    return iso_values.get(value)


def minolta_ae_metering_segments(raw_value: str) -> str | None:
    converted: list[str] = []
    for part in raw_value.split():
        value = parse_integer_word(part)
        if value is None:
            return None
        converted.append(format_perl_number((value - 106) / 8))
    return " ".join(converted)


def canon_swap_words(raw_value: str) -> str | None:
    swapped: list[str] = []
    for part in raw_value.split():
        value = parse_integer_word(part)
        if value is None:
            return None
        swapped.append(str(((value >> 16) | (value << 16)) & 0xFFFFFFFF))
    return " ".join(swapped)


def canon_composite_file_number(raw_value: str) -> str | None:
    values = raw_value.split()
    if len(values) < 2:
        return None
    directory_index = parse_integer_word(values[0])
    file_index = parse_integer_word(values[1])
    if directory_index is None or file_index is None:
        return None
    if file_index == 10000:
        file_index = 1
        directory_index += 1
    return f"{directory_index:03d}{file_index:04d}"


def parse_integer_word(raw_value: str) -> int | None:
    try:
        value = float(raw_value)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return int(value)


def sony_rtmd_datetime(raw_value: str) -> str | None:
    if len(raw_value) < 8:
        return None
    return (
        f"{bytes_to_hex(raw_value, 1, 2)}:{bytes_to_hex(raw_value, 3, 1)}:"
        f"{bytes_to_hex(raw_value, 4, 1)} {bytes_to_hex(raw_value, 5, 1)}:"
        f"{bytes_to_hex(raw_value, 6, 1)}:{bytes_to_hex(raw_value, 7, 1)}"
    )


def write_maker_note_value_conversion_result(
    maker_note_package: Path,
    request: MakerNoteValueConversionRequest,
    output: Path,
) -> MakerNoteValueConversionResult:
    result = run_maker_note_value_conversion(maker_note_package, request)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def maker_note_value_conversion_summary(
    result: MakerNoteValueConversionResult,
) -> JsonObject:
    return {
        "candidate_count": result.candidate_count,
        "match_count": len(result.matches),
        "converted_count": result.converted_count,
        "source_count": result.repository.source_count,
        "table_count": result.repository.table_count,
        "tag_entry_count": result.repository.tag_entry_count,
    }


def maker_note_value_conversion_request_to_json(
    request: MakerNoteValueConversionRequest,
) -> JsonObject:
    return {
        "raw_value": request.raw_value,
        "vendor": request.vendor,
        "module": request.module,
        "table": request.table,
        "tag_name": request.tag_name,
        "tag_id": request.tag_id,
        "runtime_context": maker_note_runtime_context_to_json(request.runtime_context),
        "limit": request.limit,
    }


def maker_note_value_conversion_matches_to_json(
    matches: tuple[MakerNoteValueConversionMatch, ...],
) -> JsonArray:
    return [
        {
            "status": match.status,
            "converted": match.converted,
            "converted_value": match.converted_value,
            "error": match.error,
            "location": locations_to_json((match.location,))[0],
        }
        for match in matches
    ]


def vm_value_to_json(value: VmValue) -> JsonValue:
    if isinstance(value, list):
        return [vm_scalar_to_json(item) for item in value]
    return vm_scalar_to_json(value)


def vm_scalar_to_json(value: VmScalar) -> JsonValue:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, ScalarReferenceValue):
        return {"scalar_reference": vm_scalar_to_json(value.value)}
    if isinstance(value, ArrayReferenceValue):
        return {"array_reference": [vm_scalar_to_json(item) for item in value.values]}
    if isinstance(value, HashReferenceValue):
        return {
            "hash_reference": [
                {"key": entry.key, "value": vm_scalar_to_json(entry.value)}
                for entry in value.entries
            ]
        }
    return assert_never(value)
