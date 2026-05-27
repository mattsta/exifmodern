"""Olympus maker-note PrintConv domain adapters."""

from __future__ import annotations

import re

from exifmodern.formats.maker_notes.context import MakerNoteRuntimeContext
from exifmodern.services.maker_note_database.print_helpers import (
    convert_indexed_values,
    mapped_integer_value,
)
from exifmodern.services.maker_note_database.print_scalar import (
    decode_bits,
    parse_int,
    perl_truthy,
    split_integer_words,
)
from exifmodern.services.maker_note_tables import MakerNoteTagLocation


def is_olympus_print_domain_location(location: MakerNoteTagLocation) -> bool:
    if location.module.module != "Image::ExifTool::Olympus":
        return False
    if location.table.name == "CameraSettings":
        return location.entry.print_conv_kind in {"array", "scalar"} and location.entry.name in {
            "FocusMode",
            "FocusProcess",
            "FlashControlMode",
            "Gradation",
            "PictureMode",
            "ArtFilter",
            "MagicFilter",
            "ToneLevel",
            "ArtFilterEffect",
            "ColorCreatorEffect",
            "MonochromeProfileSettings",
            "ColorProfileSettings",
            "DriveMode",
            "ISOAutoSettings",
        }
    return (
        (
            location.table.name == "RawDevelopment2"
            and location.entry.name == "RawDevArtFilter"
            and location.entry.print_conv_kind == "array"
        )
        or (
            location.table.name == "ImageProcessing"
            and location.entry.name == "MultipleExposureMode"
            and location.entry.print_conv_kind == "array"
        )
        or (
            location.table.name == "Main"
            and location.entry.name == "SpecialMode"
            and location.entry.print_conv_kind == "code"
        )
        or (
            location.table.name == "FocusInfo"
            and location.entry.name == "ImageStabilization"
            and location.entry.print_conv_kind == "scalar"
        )
    )


def is_olympus_model_dependent_custom_saturation_location(
    location: MakerNoteTagLocation,
) -> bool:
    return (
        location.module.module == "Image::ExifTool::Olympus"
        and location.table.name == "CameraSettings"
        and location.entry.name == "CustomSaturation"
        and location.entry.print_conv_kind == "scalar"
    )


def is_olympus_camera_type_quality_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Olympus"
        and location.table.name == "Main"
        and location.entry.name == "Quality"
        and location.entry.print_conv_kind == "code"
        and location.entry.tag_id == "513"
    )


def olympus_print_domain_conversion(
    location: MakerNoteTagLocation,
    raw_value: str,
) -> str | None:
    tag_name = location.entry.name
    if location.table.name == "CameraSettings":
        if tag_name == "DriveMode":
            return olympus_drive_mode(raw_value)
        return olympus_camera_settings_array_print(tag_name, raw_value)
    if location.table.name == "RawDevelopment2" and tag_name == "RawDevArtFilter":
        return olympus_first_value_filter(raw_value)
    if location.table.name == "ImageProcessing" and tag_name == "MultipleExposureMode":
        return olympus_multiple_exposure_mode(raw_value)
    if location.table.name == "Main" and tag_name == "SpecialMode":
        return olympus_special_mode(raw_value)
    if location.table.name == "FocusInfo" and tag_name == "ImageStabilization":
        return olympus_focus_info_image_stabilization(raw_value)
    return None


def olympus_custom_saturation(
    raw_value: str,
    runtime_context: MakerNoteRuntimeContext,
) -> str | None:
    values = split_integer_words(raw_value)
    model = runtime_context.self_string(("Model",))
    if values is None or len(values) < 3 or model is None:
        return None
    first, minimum, maximum = values[:3]
    if re.match(r"^E-1\b", model):
        return f"CS{first - minimum} (min CS0, max CS{maximum - minimum})"
    return f"{first} (min {minimum}, max {maximum})"


OLYMPUS_QUALITY_SX: dict[int, str] = {
    0: "SQ (Low)",
    1: "HQ (Normal)",
    2: "SHQ (Fine)",
    6: "RAW",
}

OLYMPUS_QUALITY_DEFAULT: dict[int, str] = {
    1: "SQ (Low)",
    2: "HQ (Normal)",
    3: "SHQ (Fine)",
    4: "RAW",
    5: "Medium-Fine",
    6: "Small-Fine",
    33: "Uncompressed",
}


def olympus_quality(
    raw_value: str,
    runtime_context: MakerNoteRuntimeContext,
) -> str | None:
    value = parse_int(raw_value)
    camera_type = runtime_context.self_string(("CameraType",))
    if value is None or camera_type is None:
        return None
    mapping = OLYMPUS_QUALITY_DEFAULT
    if re.match(r"^(SX(?!151\b)|D4322)", camera_type):
        mapping = OLYMPUS_QUALITY_SX
    return mapping.get(value, f"Unknown ({value})")


def olympus_camera_settings_array_print(tag_name: str, raw_value: str) -> str | None:
    if tag_name == "FocusMode":
        return olympus_focus_mode(raw_value)
    if tag_name == "FocusProcess":
        return olympus_first_value_map(raw_value, {0: "AF Not Used", 1: "AF Used"})
    if tag_name == "FlashControlMode":
        return olympus_first_value_map(
            raw_value,
            {0: "Off", 3: "TTL", 4: "Auto", 5: "Manual"},
        )
    if tag_name == "Gradation":
        return olympus_gradation(raw_value)
    if tag_name == "PictureMode":
        return olympus_first_value_map(raw_value, OLYMPUS_PICTURE_MODE)
    if tag_name in {"ArtFilter", "MagicFilter"}:
        return olympus_first_value_filter(raw_value)
    if tag_name == "ToneLevel":
        return olympus_tone_level(raw_value)
    if tag_name == "ArtFilterEffect":
        return olympus_art_filter_effect(raw_value)
    if tag_name == "ColorCreatorEffect":
        return olympus_indexed_prefixes(raw_value, {0: "Color", 3: "Strength"})
    if tag_name == "MonochromeProfileSettings":
        return olympus_monochrome_profile_settings(raw_value)
    if tag_name == "ColorProfileSettings":
        return olympus_indexed_prefixes(
            raw_value,
            {
                0: "Min",
                1: "Max",
                2: "Yellow",
                3: "Orange",
                4: "Orange-red",
                5: "Red",
                6: "Magenta",
                7: "Violet",
                8: "Blue",
                9: "Blue-cyan",
                10: "Cyan",
                11: "Green-cyan",
                12: "Green",
                13: "Yellow-green",
            },
        )
    if tag_name == "ISOAutoSettings":
        return convert_indexed_values(
            raw_value.split(),
            (olympus_iso_auto_value, olympus_iso_auto_value),
        )
    return None


OLYMPUS_FILTERS: dict[int, str] = {
    0: "Off",
    1: "Soft Focus",
    2: "Pop Art",
    3: "Pale & Light Color",
    4: "Light Tone",
    5: "Pin Hole",
    6: "Grainy Film",
    8: "Underwater",
    9: "Diorama",
    10: "Cross Process",
    12: "Fish Eye",
    13: "Drawing",
    14: "Gentle Sepia",
    15: "Pale & Light Color II",
    16: "Pop Art II",
    17: "Pin Hole II",
    18: "Pin Hole III",
    19: "Grainy Film II",
    20: "Dramatic Tone",
    21: "Punk",
    22: "Soft Focus 2",
    23: "Sparkle",
    24: "Watercolor",
    25: "Key Line",
    26: "Key Line II",
    27: "Miniature",
    28: "Reflection",
    29: "Fragmented",
    31: "Cross Process II",
    32: "Dramatic Tone II",
    33: "Watercolor I",
    34: "Watercolor II",
    35: "Diorama II",
    36: "Vintage",
    37: "Vintage II",
    38: "Vintage III",
    39: "Partial Color",
    40: "Partial Color II",
    41: "Partial Color III",
    42: "Bleach Bypass",
    43: "Bleach Bypass II",
    44: "Instant Film",
}

OLYMPUS_PICTURE_MODE: dict[int, str] = {
    1: "Vivid",
    2: "Natural",
    3: "Muted",
    4: "Portrait",
    5: "i-Enhance",
    6: "e-Portrait",
    7: "Color Creator",
    8: "Underwater",
    9: "Color Profile 1",
    10: "Color Profile 2",
    11: "Color Profile 3",
    12: "Monochrome Profile 1",
    13: "Monochrome Profile 2",
    14: "Monochrome Profile 3",
    17: "Art Mode",
    18: "Monochrome Profile 4",
    256: "Monotone",
    512: "Sepia",
}

OLYMPUS_ISO_AUTO: dict[int, str] = {
    0: "n/a",
    0x0600: "200",
    0x0655: "250",
    0x06AA: "320",
    0x0700: "400",
    0x0755: "500",
    0x07AA: "640",
    0x0800: "800",
    0x0855: "1000",
    0x08AA: "1250",
    0x0900: "1600",
    0x0955: "2000",
    0x09AA: "2500",
    0x0A00: "3200",
    0x0A55: "4000",
    0x0AAA: "5000",
    0x0B00: "6400",
    0x0B55: "8000",
    0x0BAA: "10000",
    0x0C00: "12800",
    0x0C55: "16000",
    0x0CAA: "20000",
    0x0D00: "25600",
    0x0D55: "32000",
    0x0DAA: "40000",
    0x0E00: "51200",
    0x0E55: "64000",
    0x0EAA: "80000",
    0x0F00: "102400",
}


def olympus_first_value_map(raw_value: str, mapping: dict[int, str]) -> str | None:
    return convert_indexed_values(
        raw_value.split(),
        (lambda value: mapped_integer_value(value, mapping),),
    )


def olympus_first_value_filter(raw_value: str) -> str | None:
    return olympus_first_value_map(raw_value, OLYMPUS_FILTERS)


def olympus_focus_mode(raw_value: str) -> str | None:
    return convert_indexed_values(
        raw_value.split(),
        (olympus_focus_mode_primary, olympus_focus_mode_secondary),
    )


def olympus_focus_mode_primary(raw_value: str) -> str | None:
    return mapped_integer_value(
        raw_value,
        {
            0: "Single AF",
            1: "Sequential shooting AF",
            2: "Continuous AF",
            3: "Multi AF",
            4: "Face Detect",
            10: "MF",
        },
    )


def olympus_focus_mode_secondary(raw_value: str) -> str | None:
    value = parse_int(raw_value)
    if value is None:
        return None
    if value == 0:
        return "(none)"
    return decode_bits(
        raw_value,
        (
            (0, "S-AF"),
            (2, "C-AF"),
            (4, "MF"),
            (5, "Face Detect"),
            (6, "Imager AF"),
            (7, "Live View Magnification Frame"),
            (8, "AF sensor"),
            (9, "Starry Sky AF"),
        ),
        bits_per_word=32,
    )


def olympus_gradation(raw_value: str) -> str | None:
    parts = raw_value.split()
    if len(parts) < 3:
        return None
    first = {
        "0 0 0": "n/a",
        "-1 -1 1": "Low Key",
        "0 -1 1": "Normal",
        "1 -1 1": "High Key",
    }.get(" ".join(parts[:3]), " ".join(parts[:3]))
    if len(parts) == 3:
        return first
    second = mapped_integer_value(parts[3], {0: "User-Selected", 1: "Auto-Override"})
    if second is None:
        second = parts[3]
    return " ".join((first, second, *parts[4:]))


def olympus_tone_level(raw_value: str) -> str | None:
    values = raw_value.split()
    converted: list[str] = []
    for index, value in enumerate(values):
        if index % 4 == 0:
            mapped = mapped_integer_value(
                value,
                {
                    0: "0",
                    -31999: "Highlights",
                    -31998: "Shadows",
                    -31997: "Midtones",
                },
            )
            if mapped is None:
                return None
            converted.append(mapped)
        else:
            converted.append(value)
    return " ".join(converted)


def olympus_art_filter_effect(raw_value: str) -> str | None:
    values = raw_value.split()
    converted: list[str] = []
    for index, value in enumerate(values):
        if index == 0:
            mapped = mapped_integer_value(value, OLYMPUS_FILTERS)
            if mapped is None:
                return None
            converted.append(mapped)
        elif index == 3:
            converted.append(f"Partial Color {value}")
        elif index == 4:
            mapped = mapped_integer_value(
                value,
                {
                    0x0000: "No Effect",
                    0x8010: "Star Light",
                    0x8020: "Pin Hole",
                    0x8030: "Frame",
                    0x8040: "Soft Focus",
                    0x8050: "White Edge",
                    0x8060: "B&W",
                    0x8080: "Blur Top and Bottom",
                    0x8081: "Blur Left and Right",
                },
            )
            if mapped is None:
                return None
            converted.append(mapped)
        elif index == 6:
            mapped = mapped_integer_value(
                value,
                {
                    0: "No Color Filter",
                    1: "Yellow Color Filter",
                    2: "Orange Color Filter",
                    3: "Red Color Filter",
                    4: "Green Color Filter",
                },
            )
            if mapped is None:
                return None
            converted.append(mapped)
        else:
            converted.append(value)
    return " ".join(converted)


def olympus_indexed_prefixes(raw_value: str, prefixes: dict[int, str]) -> str:
    return " ".join(
        f"{prefixes[index]} {value}" if index in prefixes else value
        for index, value in enumerate(raw_value.split())
    )


def olympus_monochrome_profile_settings(raw_value: str) -> str | None:
    values = raw_value.split()
    if not values:
        return ""
    first = mapped_integer_value(
        values[0],
        {
            0: "No Filter",
            1: "Yellow Filter",
            2: "Orange Filter",
            3: "Red Filter",
            4: "Magenta Filter",
            5: "Blue Filter",
            6: "Cyan Filter",
            7: "Green Filter",
            8: "Yellow-green Filter",
        },
    )
    if first is None:
        return None
    converted = [first, *values[1:]]
    if len(converted) > 3:
        converted[3] = "Strength " + converted[3]
    return " ".join(converted)


def olympus_iso_auto_value(raw_value: str) -> str | None:
    return mapped_integer_value(raw_value, OLYMPUS_ISO_AUTO)


def olympus_multiple_exposure_mode(raw_value: str) -> str | None:
    return olympus_first_value_map(
        raw_value,
        {
            0: "Off",
            1: "Live Composite",
            2: "On (2 frames)",
            3: "On (3 frames)",
        },
    )


def olympus_special_mode(raw_value: str) -> str:
    values = raw_value.split()
    if len(values) < 3:
        return raw_value
    mode = indexed_olympus_value(values[0], ("Normal", "Unknown (1)", "Fast", "Panorama"))
    panorama = indexed_olympus_value(
        values[2],
        ("(none)", "Left to Right", "Right to Left", "Bottom to Top", "Top to Bottom"),
    )
    return f"{mode}, Sequence: {values[1]}, Panorama: {panorama}"


def indexed_olympus_value(raw_value: str, values: tuple[str, ...]) -> str:
    index = parse_int(raw_value)
    if index is None or index < 0 or index >= len(values):
        return f"Unknown ({raw_value})"
    return values[index]


def olympus_focus_info_image_stabilization(raw_value: str) -> str:
    if raw_value.startswith("\x00\x00\x00\x00"):
        return "Off"
    byte_44 = ord(raw_value[44]) if len(raw_value) > 44 else 0
    mode = "Mode 1" if byte_44 & 0x01 else "Mode 2"
    return "On, " + mode


def olympus_drive_mode(raw_value: str) -> str | None:
    values = raw_value.split()
    if not values:
        return None
    mode = parse_int(values[0])
    if mode is None:
        return None
    shot = "" if len(values) < 2 or not perl_truthy(values[1]) else ", Shot " + values[1]
    shutter = olympus_drive_mode_shutter(values)
    if mode == 5 and len(values) >= 3:
        bracketing = decode_bits(
            values[2],
            (
                (0, "AE"),
                (1, "WB"),
                (2, "FL"),
                (3, "MF"),
                (4, "ISO"),
                (5, "AE Auto"),
                (6, "Focus"),
            ),
            bits_per_word=32,
        )
        if bracketing is None:
            return None
        mode_text = bracketing.replace(", ", "+") + " Bracketing"
    elif len(values) >= 6 and perl_truthy(values[5]):
        shooting_mode = mapped_integer_value(values[5], OLYMPUS_DRIVE_SHOOTING_MODE)
        mode_text = shooting_mode if shooting_mode is not None else f"Unknown ({values[5]})"
    else:
        mode_text = {
            0: "Single Shot",
            1: "Continuous Shooting",
            2: "Exposure Bracketing",
            3: "White Balance Bracketing",
            4: "Exposure+WB Bracketing",
        }.get(mode, f"Unknown ({values[0]})")
    return mode_text + shot + shutter


OLYMPUS_DRIVE_SHOOTING_MODE: dict[int, str] = {
    0x01: "Single Shot",
    0x02: "Sequential L",
    0x03: "Sequential H",
    0x07: "Sequential",
    0x11: "Single Shot",
    0x12: "Sequential L",
    0x13: "Sequential H",
    0x14: "Self-Timer 12 sec",
    0x15: "Self-Timer 2 sec",
    0x16: "Custom Self-Timer",
    0x17: "Sequential",
    0x21: "Single Shot",
    0x22: "Sequential L",
    0x23: "Sequential H",
    0x24: "Self-Timer 2 sec",
    0x25: "Self-Timer 12 sec",
    0x26: "Custom Self-Timer",
    0x27: "Sequential",
    0x28: "Sequential SH1",
    0x29: "Sequential SH2",
    0x30: "HighRes Shot",
    0x41: "ProCap H",
    0x42: "ProCap L",
    0x43: "ProCap",
    0x48: "ProCap SH1",
    0x49: "ProCap SH2",
}


def olympus_drive_mode_shutter(values: list[str]) -> str:
    if len(values) < 5:
        return ""
    shutter = parse_int(values[4])
    if shutter is None or shutter == 4:
        return ""
    return "; " + {0: "Mechanical shutter", 2: "Anti-shock"}.get(
        shutter,
        f"Unknown ({values[4]})",
    )
