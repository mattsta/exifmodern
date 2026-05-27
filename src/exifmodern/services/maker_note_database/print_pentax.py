"""Pentax maker-note PrintConv domain adapters."""

from __future__ import annotations

import re

from exifmodern.services.maker_note_database.print_helpers import (
    IndexedPrintConverter,
    convert_indexed_values,
    format_perl_float,
    mapped_float_key_value,
    mapped_integer_value_with_unknown,
    mapped_string_value_with_unknown,
)
from exifmodern.services.maker_note_database.print_scalar import (
    parse_float,
    parse_int,
    perl_truthy,
    split_integer_words,
)
from exifmodern.services.maker_note_tables import MakerNoteTagLocation


def is_pentax_af_info_k3iii_print_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Pentax"
        and location.table.name == "AFInfo"
        and location.entry.print_conv_kind == "code"
        and location.entry.name in {"AFPointValues", "AFPointsSelected", "AFPointsUnknown"}
    )


def is_pentax_main_print_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Pentax"
        and location.table.name == "Main"
        and location.entry.name
        in {
            "AutoBracketing",
            "PictureMode",
            "DriveMode",
            "FlashMode",
            "Saturation",
            "Contrast",
            "Sharpness",
            "DynamicRangeExpansion",
            "FineSharpness",
            "HighISONoiseReduction",
            "FaceDetect",
            "ISOAutoMinSpeed",
            "BlurControl",
            "HDR",
            "AEMeteringSegments",
            "FlashMeteringSegments",
            "SlaveFlashMeteringSegments",
        }
    )


def is_pentax_af_info_k3iii_area_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Pentax"
        and location.table.name == "AFInfoK3III"
        and location.entry.name == "AFAreas"
        and location.entry.print_conv_kind == "code"
    )


def pentax_color_temp_print(raw_value: str) -> str:
    current = re.sub(r" ([1-9])", r" +\1", raw_value)
    return re.sub(r" 0", "  0", current)


def pentax_main_print_conversion(tag_name: str, tag_id: str, raw_value: str) -> str | None:
    if tag_name == "AutoBracketing":
        return pentax_auto_bracketing_print(raw_value)
    if tag_name == "PictureMode":
        if tag_id == "51":
            return pentax_picture_mode_51(raw_value)
        return pentax_array_print(raw_value, (pentax_picture_mode,))
    if tag_name == "DriveMode":
        return pentax_array_print(
            raw_value,
            (pentax_drive_mode, pentax_timer_mode, pentax_remote_mode, pentax_multi_exposure_mode),
        )
    if tag_name == "FlashMode":
        return pentax_array_print(raw_value, (pentax_flash_mode, pentax_external_flash_mode))
    if tag_name == "Saturation":
        return pentax_array_print(raw_value, (pentax_saturation,))
    if tag_name == "Contrast":
        return pentax_array_print(raw_value, (pentax_contrast,))
    if tag_name == "Sharpness":
        return pentax_array_print(raw_value, (pentax_sharpness,))
    if tag_name == "DynamicRangeExpansion":
        return pentax_array_print(raw_value, (off_on_value, pentax_dynamic_range_mode))
    if tag_name == "FineSharpness":
        return pentax_array_print(raw_value, (off_on_value, pentax_fine_sharpness_mode))
    if tag_name == "HighISONoiseReduction":
        return pentax_array_print(
            raw_value,
            (
                pentax_high_iso_noise_reduction,
                pentax_high_iso_noise_reduction_active,
                pentax_high_iso_noise_reduction_start,
            ),
        )
    if tag_name == "FaceDetect":
        return pentax_array_print(raw_value, (pentax_face_detect_max, pentax_faces_detected))
    if tag_name == "ISOAutoMinSpeed":
        return pentax_array_print(raw_value, (pentax_iso_auto_min_speed_mode, print_exposure_time))
    if tag_name == "BlurControl":
        return pentax_array_print(
            raw_value,
            (pentax_blur_control_mode, raw_string, raw_string, raw_string),
        )
    if tag_name == "HDR":
        return pentax_array_print(raw_value, (pentax_hdr_mode, pentax_auto_align, pentax_hdr_ev))
    if tag_name in {"AEMeteringSegments", "FlashMeteringSegments", "SlaveFlashMeteringSegments"}:
        return pentax_metering_segments(raw_value)
    return None


def pentax_array_print(
    raw_value: str,
    converters: tuple[IndexedPrintConverter, ...],
) -> str | None:
    return convert_indexed_values(raw_value.split(), converters)


def raw_string(raw_value: str) -> str:
    return raw_value


def pentax_auto_bracketing_print(raw_value: str) -> str | None:
    values = raw_value.split()
    if not values:
        return None
    printed = list(values)
    first = parse_float(printed[0])
    if first is not None and first != 0 and "/" not in printed[0]:
        printed[0] = f"{first:.1f}"
    if len(printed) > 1:
        extended = parse_int(printed[1])
        if extended is None:
            return None
        if extended:
            bracket_type = extended >> 8
            bracket_step = extended & 0xFF
            labels = {
                1: "WB-BA",
                2: "WB-GM",
                3: "Saturation",
                4: "Sharpness",
                5: "Contrast",
                6: "Hue",
                7: "HighLowKey",
            }
            printed[1] = f"{labels.get(bracket_type, f'Unknown({bracket_type})')}+{bracket_step}"
        else:
            printed[1] = "No Extended Bracket"
    return " EV, ".join(printed)


def pentax_metering_segments(raw_value: str) -> str | None:
    values = split_integer_words(raw_value)
    if values is None:
        return None
    printed = (
        "n/a" if value == 255 else "0" if value == 0 else "%.1f" % (value / 8 - 6)
        for value in values
    )
    return " ".join(printed)


def pentax_picture_mode(raw_value: str) -> str | None:
    return mapped_float_key_value(
        raw_value,
        {
            "0": "Program",
            "0.1": "Av",
            "1": "Shutter Speed Priority",
            "1.1": "M",
            "2": "Program AE",
            "2.1": "Tv",
            "3": "Manual",
            "3.1": "USER",
            "5": "Portrait",
            "6": "Landscape",
            "8": "Sport",
            "9": "Night Scene",
            "11": "Soft",
            "12": "Surf & Snow",
            "13": "Candlelight",
            "14": "Autumn",
            "15": "Macro",
            "17": "Fireworks",
            "18": "Text",
            "19": "Panorama",
            "20": "3-D",
            "21": "Black & White",
            "22": "Sepia",
            "23": "Red",
            "24": "Pink",
            "25": "Purple",
            "26": "Blue",
            "27": "Green",
            "28": "Yellow",
            "30": "Self Portrait",
            "31": "Illustrations",
            "33": "Digital Filter",
            "35": "Night Scene Portrait",
            "37": "Museum",
            "38": "Food",
            "39": "Underwater",
            "40": "Green Mode",
            "49": "Light Pet",
            "50": "Dark Pet",
            "51": "Medium Pet",
            "53": "Underwater",
            "54": "Candlelight",
            "55": "Natural Skin Tone",
            "56": "Synchro Sound Record",
            "58": "Frame Composite",
            "59": "Report",
            "60": "Kids",
            "61": "Blur Reduction",
            "63": "Panorama 2",
            "65": "Half-length Portrait",
            "66": "Portrait 2",
            "74": "Digital Microscope",
            "75": "Blue Sky",
            "80": "Miniature",
            "81": "HDR",
            "83": "Fisheye",
            "85": "Digital Filter 4",
            "221": "P",
            "255": "PICT",
        },
    )


def pentax_picture_mode_51(raw_value: str) -> str | None:
    values = raw_value.split()
    if len(values) < 2:
        return None
    mode = mapped_string_value_with_unknown(
        " ".join(values[:2]),
        {
            "0 0": "Program",
            "0 1": "Hi-speed Program",
            "0 2": "DOF Program",
            "0 3": "MTF Program",
            "0 4": "Standard",
            "0 5": "Portrait",
            "0 6": "Landscape",
            "0 7": "Macro",
            "0 8": "Sport",
            "0 9": "Night Scene Portrait",
            "0 10": "No Flash",
            "0 11": "Night Scene",
            "0 12": "Surf & Snow",
            "0 13": "Text",
            "0 14": "Sunset",
            "0 15": "Kids",
            "0 16": "Pet",
            "0 17": "Candlelight",
            "0 18": "Museum",
            "0 19": "Food",
            "0 20": "Stage Lighting",
            "0 21": "Night Snap",
            "0 23": "Blue Sky",
            "0 24": "Sunset",
            "0 26": "Night Scene HDR",
            "0 27": "HDR",
            "0 28": "Quick Macro",
            "0 29": "Forest",
            "0 30": "Backlight Silhouette",
            "0 31": "Max. Aperture Priority",
            "0 32": "DOF",
            "1 4": "Auto PICT (Standard)",
            "1 5": "Auto PICT (Portrait)",
            "1 6": "Auto PICT (Landscape)",
            "1 7": "Auto PICT (Macro)",
            "1 8": "Auto PICT (Sport)",
            "2 0": "Program (HyP)",
            "2 1": "Hi-speed Program (HyP)",
            "2 2": "DOF Program (HyP)",
            "2 3": "MTF Program (HyP)",
            "2 22": "Shallow DOF (HyP)",
            "3 0": "Green Mode",
            "4 0": "Shutter Speed Priority",
            "4 2": "Shutter Speed Priority 2",
            "4 31": "Shutter Speed Priority 31",
            "5 0": "Aperture Priority",
            "5 2": "Aperture Priority 2",
            "5 31": "Aperture Priority 31",
            "6 0": "Program Tv Shift",
            "7 0": "Program Av Shift",
            "8 0": "Manual",
            "9 0": "Bulb",
            "10 0": "Aperture Priority, Off-Auto-Aperture",
            "11 0": "Manual, Off-Auto-Aperture",
            "12 0": "Bulb, Off-Auto-Aperture",
            "13 0": "Shutter & Aperture Priority AE",
            "14 0": "Shutter Priority AE",
            "15 0": "Sensitivity Priority AE",
            "16 0": "Flash X-Sync Speed AE",
            "17 0": "Flash X-Sync Speed",
            "18 0": "Auto Program (Normal)",
            "18 1": "Auto Program (Hi-speed)",
            "18 2": "Auto Program (DOF)",
            "18 3": "Auto Program (MTF)",
            "18 22": "Auto Program (Shallow DOF)",
            "19 0": "Astrotracer",
            "20 22": "Blur Control",
            "24 0": "Aperture Priority (Adv.Hyp)",
            "25 0": "Manual Exposure (Adv.Hyp)",
            "26 0": "Shutter and Aperture Priority (TAv)",
            "249 0": "Movie (TAv)",
            "250 0": "Movie (TAv, Auto Aperture)",
            "251 0": "Movie (Manual)",
            "252 0": "Movie (Manual, Auto Aperture)",
            "253 0": "Movie (Av)",
            "254 0": "Movie (Av, Auto Aperture)",
            "255 0": "Movie (P, Auto Aperture)",
            "255 4": "Video (4)",
        },
    )
    if len(values) == 2:
        return mode
    ev_step = mapped_integer_value_with_unknown(values[2], {0: "1/2 EV steps", 1: "1/3 EV steps"})
    if ev_step is None:
        return None
    return f"{mode} {ev_step}"


def pentax_drive_mode(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value,
        {
            0: "Single-frame",
            1: "Continuous",
            2: "Continuous (Lo)",
            3: "Burst",
            4: "Continuous (Medium)",
            5: "Continuous (Low)",
            255: "Video",
        },
    )


def pentax_timer_mode(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value,
        {
            0: "No Timer",
            1: "Self-timer (12 s)",
            2: "Self-timer (2 s)",
            15: "Video",
            16: "Mirror Lock-up",
            255: "n/a",
        },
    )


def pentax_remote_mode(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value,
        {
            0: "Shutter Button",
            1: "Remote Control (3 s delay)",
            2: "Remote Control",
            4: "Remote Continuous Shooting",
        },
    )


def pentax_multi_exposure_mode(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value,
        {
            0x00: "Single Exposure",
            0x01: "Multiple Exposure",
            0x02: "Composite Average",
            0x03: "Composite Additive",
            0x04: "Composite Bright",
            0x08: "Interval Shooting",
            0x0A: "Interval Composite Average",
            0x0B: "Interval Composite Additive",
            0x0C: "Interval Composite Bright",
            0x0F: "Interval Movie",
            0x10: "HDR",
            0x20: "HDR Strong 1",
            0x30: "HDR Strong 2",
            0x40: "HDR Strong 3",
            0x50: "HDR Manual",
            0xE0: "HDR Auto",
            0xFF: "Video",
        },
    )


def pentax_flash_mode(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value,
        {
            0x000: "Auto, Did not fire",
            0x001: "Off, Did not fire",
            0x002: "On, Did not fire",
            0x003: "Auto, Did not fire, Red-eye reduction",
            0x005: "On, Did not fire, Wireless (Master)",
            0x100: "Auto, Fired",
            0x102: "On, Fired",
            0x103: "Auto, Fired, Red-eye reduction",
            0x104: "On, Red-eye reduction",
            0x105: "On, Wireless (Master)",
            0x106: "On, Wireless (Control)",
            0x108: "On, Soft",
            0x109: "On, Slow-sync",
            0x10A: "On, Slow-sync, Red-eye reduction",
            0x10B: "On, Trailing-curtain Sync",
        },
    )


def pentax_external_flash_mode(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value,
        {
            0x000: "n/a - Off-Auto-Aperture",
            0x03F: "Internal",
            0x100: "External, Auto",
            0x23F: "External, Flash Problem",
            0x300: "External, Manual",
            0x304: "External, P-TTL Auto",
            0x305: "External, Contrast-control Sync",
            0x306: "External, High-speed Sync",
            0x30C: "External, Wireless",
            0x30D: "External, Wireless, High-speed Sync",
        },
    )


def pentax_saturation(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value,
        {
            0: "-2 (low)",
            1: "0 (normal)",
            2: "+2 (high)",
            3: "-1 (medium low)",
            4: "+1 (medium high)",
            5: "-3 (very low)",
            6: "+3 (very high)",
            7: "-4 (minimum)",
            8: "+4 (maximum)",
            65535: "None",
        },
    )


def pentax_contrast(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value,
        {
            0: "-2 (low)",
            1: "0 (normal)",
            2: "+2 (high)",
            3: "-1 (medium low)",
            4: "+1 (medium high)",
            5: "-3 (very low)",
            6: "+3 (very high)",
            7: "-4 (minimum)",
            8: "+4 (maximum)",
            65535: "n/a",
        },
    )


def pentax_sharpness(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value,
        {
            0: "-2 (soft)",
            1: "0 (normal)",
            2: "+2 (hard)",
            3: "-1 (medium soft)",
            4: "+1 (medium hard)",
            5: "-3 (very soft)",
            6: "+3 (very hard)",
            7: "-4 (minimum)",
            8: "+4 (maximum)",
        },
    )


def off_on_value(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(raw_value, {0: "Off", 1: "On"})


def pentax_dynamic_range_mode(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(raw_value, {0: "0", 1: "Enabled", 2: "Auto"})


def pentax_fine_sharpness_mode(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(raw_value, {0: "Normal", 2: "Extra fine"})


def pentax_high_iso_noise_reduction(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value, {0: "Off", 1: "Weakest", 2: "Weak", 3: "Strong", 4: "Medium", 255: "Auto"}
    )


def pentax_high_iso_noise_reduction_active(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value,
        {
            0: "Inactive",
            1: "Active",
            2: "Active (Weak)",
            3: "Active (Strong)",
            4: "Active (Medium)",
        },
    )


def pentax_high_iso_noise_reduction_start(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value, {48: "ISO>400", 56: "ISO>800", 64: "ISO>1600", 72: "ISO>3200"}
    )


def pentax_face_detect_max(raw_value: str) -> str | None:
    value = parse_int(raw_value)
    if value is None:
        return None
    return f"On ({raw_value} faces max)" if value else "Off"


def pentax_faces_detected(raw_value: str) -> str:
    return f"{raw_value} faces detected"


def pentax_iso_auto_min_speed_mode(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value, {1: "Shutter Speed Control", 2: "Auto Slow", 3: "Auto Standard", 4: "Auto Fast"}
    )


def pentax_blur_control_mode(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value, {0: "Off", 1: "Low", 2: "Medium", 3: "High"}
    )


def pentax_hdr_mode(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value, {0: "Off", 1: "HDR Auto", 2: "HDR 1", 3: "HDR 2", 4: "HDR 3", 5: "HDR Advanced"}
    )


def pentax_auto_align(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(raw_value, {0: "Auto-align Off", 1: "Auto-align On"})


def pentax_hdr_ev(raw_value: str) -> str | None:
    return mapped_integer_value_with_unknown(
        raw_value, {0: "n/a", 4: "1 EV", 8: "2 EV", 12: "3 EV"}
    )


def print_exposure_time(raw_value: str) -> str | None:
    value = parse_float(raw_value)
    if value is None:
        return None
    if value <= 0:
        return "0"
    if value < 1:
        denominator = round(1 / value)
        if denominator:
            return f"1/{denominator}"
    return format_perl_float(value)


def pentax_af_areas_k3iii(raw_value: str) -> str | None:
    values = split_integer_words(raw_value)
    if values is None:
        return None
    if not values:
        return "(none)"
    areas: list[str] = []
    for index in range(0, len(values) - 6, 7):
        flags = values[index + 6]
        labels: list[str] = []
        if flags & 0x10 == 0x10:
            labels.append("central")
        if flags & 0x08 == 0:
            labels.append("peripheral")
        if flags & 0x04 == 0x04:
            labels.append("in-focus")
        suffix = f"({','.join(labels)})" if labels else ""
        areas.append(f"{values[index + 2]},{values[index + 3]}{suffix}")
    if not areas:
        return "(none)"
    return " ".join(areas)


PENTAX_K3III_AF_POINTS: tuple[str, ...] = (
    "C1",
    "E1",
    "G1",
    "I1",
    "K1",
    "C3",
    "E3",
    "G3",
    "I3",
    "K3",
    "C5",
    "E5",
    "G5",
    "I5",
    "K5",
    "C7",
    "E7",
    "G7",
    "I7",
    "K7",
    "C9",
    "E9",
    "G9",
    "I9",
    "K9",
    "A5",
    "M5",
    "B3",
    "L3",
    "B5",
    "L5",
    "B7",
    "L7",
    "B1",
    "L1",
    "B9",
    "L9",
    "A3",
    "M3",
    "A7",
    "M7",
    "D1",
    "F1",
    "H1",
    "J1",
    "D3",
    "F3",
    "H3",
    "J3",
    "D5",
    "F5",
    "H5",
    "J5",
    "D7",
    "F7",
    "H7",
    "J7",
    "D9",
    "F9",
    "H9",
    "J9",
    "C2",
    "E2",
    "G2",
    "I2",
    "K2",
    "C4",
    "E4",
    "G4",
    "I4",
    "K4",
    "C6",
    "E6",
    "G6",
    "I6",
    "K6",
    "C8",
    "E8",
    "G8",
    "I8",
    "K8",
    "B2",
    "L2",
    "B4",
    "L4",
    "B6",
    "L6",
    "B8",
    "L8",
    "A1",
    "M1",
    "A2",
    "M2",
    "A4",
    "M4",
    "A6",
    "M6",
    "A8",
    "M8",
    "A9",
    "M9",
)


def pentax_af_info_k3iii_print(tag_name: str, raw_value: str) -> str | None:
    if tag_name == "AFPointValues":
        return pentax_af_point_values_k3iii(raw_value)
    if tag_name in {"AFPointsSelected", "AFPointsUnknown"}:
        return pentax_af_point_names_k3iii(raw_value)
    return None


def pentax_af_point_names_k3iii(raw_value: str) -> str:
    points = tuple(
        PENTAX_K3III_AF_POINTS[index]
        if index < len(PENTAX_K3III_AF_POINTS)
        else f"Unknown({index})"
        for index, value in enumerate(raw_value.split())
        if perl_truthy(value)
    )
    if not points:
        return "(none)"
    return ",".join(sorted(points))


def pentax_af_point_values_k3iii(raw_value: str) -> str:
    values: list[str | None] = list(raw_value.split())
    printed_values: list[str] = []
    for index, value in enumerate(values):
        if value is None or not perl_truthy(value):
            continue
        printed_value = pentax_af_point_value_name(index) + value
        paired_index = index + 28
        if paired_index < len(values):
            paired_value = values[paired_index]
            if paired_value is not None and perl_truthy(paired_value):
                printed_value += "/" + paired_value
                values[paired_index] = None
        printed_values.append(printed_value)
    if not printed_values:
        return "(none)"
    return ",".join(sorted(printed_values))


def pentax_af_point_value_name(index: int) -> str:
    if index < len(PENTAX_K3III_AF_POINTS):
        return PENTAX_K3III_AF_POINTS[index] + "="
    paired_index = index - 28
    if 0 <= paired_index < len(PENTAX_K3III_AF_POINTS):
        return PENTAX_K3III_AF_POINTS[paired_index] + "=/"
    return f"Unknown({index})="
