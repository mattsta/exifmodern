"""Nikon maker-note PrintConv domain adapters."""

from __future__ import annotations

import math
import re

from exifmodern.formats.maker_notes.context import MakerNoteRuntimeContext
from exifmodern.services.maker_note_database.print_scalar import parse_int, split_integer_words
from exifmodern.services.maker_note_tables import MakerNoteTagLocation


def is_nikon_print_domain_location(location: MakerNoteTagLocation) -> bool:
    if location.module.module != "Image::ExifTool::Nikon":
        return False
    if location.table.name == "Main":
        return location.entry.name in {
            "SerialNumber",
            "Lens",
            "RetouchHistory",
            "NikonCaptureVersion",
        }
    if location.table.name == "NCTG":
        return location.entry.name in {"LensInfo", "Lens"}
    return location.table.name in {
        "PictureControl",
        "PictureControl2",
        "PictureControl3",
    } and location.entry.name in {"PictureControlName", "PictureControlBase"}


def is_nikon_z9_self_state_print_location(location: MakerNoteTagLocation) -> bool:
    return (
        location.module.module == "Image::ExifTool::Nikon"
        and location.table.name in {"Offset13InfoZ9", "SeqInfoZ9"}
        and location.entry.name
        in {"AFAreaInitialXPosition", "AFAreaInitialYPosition", "FocusShiftShooting"}
        and location.entry.print_conv_kind == "scalar"
    )


def nikon_print_domain_conversion(location: MakerNoteTagLocation, raw_value: str) -> str | None:
    if location.table.name == "Main" and location.entry.name in {
        "SerialNumber",
        "NikonCaptureVersion",
    }:
        return raw_value
    if location.entry.name in {"Lens", "LensInfo"}:
        return print_lens_info(raw_value)
    if location.table.name == "Main" and location.entry.name == "RetouchHistory":
        return nikon_retouch_history_print(raw_value)
    if location.table.name in {
        "PictureControl",
        "PictureControl2",
        "PictureControl3",
    } and location.entry.name in {"PictureControlName", "PictureControlBase"}:
        return nikon_format_string(raw_value)
    return None


def nikon_z9_self_state_print_conversion(
    tag_name: str,
    raw_value: str,
    runtime_context: MakerNoteRuntimeContext,
) -> str | None:
    if tag_name == "AFAreaInitialXPosition":
        return nikon_z9_af_area_initial_x_position(raw_value, runtime_context)
    if tag_name == "AFAreaInitialYPosition":
        return nikon_z9_af_area_initial_y_position(raw_value, runtime_context)
    if tag_name == "FocusShiftShooting":
        return nikon_z9_focus_shift_shooting(raw_value, runtime_context)
    return None


def nikon_z9_focus_shift_shooting(
    raw_value: str,
    runtime_context: MakerNoteRuntimeContext,
) -> str | None:
    value = parse_int(raw_value)
    if value is None:
        return None
    if value == 0:
        return "Off"
    if runtime_context.self_int(("PixelShiftActive",)) == 1:
        return f"On: Frame {value}"
    shots = runtime_context.self_int(("FocusShiftNumberShots",))
    if shots is None:
        return None
    return f"On: Frame {value} of {shots}"


def nikon_z9_af_area_initial_x_position(
    raw_value: str,
    runtime_context: MakerNoteRuntimeContext,
) -> str | None:
    value = parse_int(raw_value)
    image_area = runtime_context.self_int(("ImageArea",))
    af_area_mode = runtime_context.value_int(("AFAreaMode",))
    focus_box_width = runtime_context.self_int(("AFAreaInitialWidth",))
    if value is None or image_area is None or af_area_mode is None or focus_box_width is None:
        return None
    fx = 0
    dx = 1
    wide_screen = 4
    one_to_one = 8
    wide_s = 3
    auto = 6
    start = 502
    increment = 259
    if image_area == one_to_one:
        start += 5 * increment
    if value < 49 and image_area in {fx, wide_screen}:
        start -= increment
    if image_area == one_to_one and af_area_mode == auto:
        start -= increment
    if image_area == dx:
        start = 636
        increment = 388
        if af_area_mode == wide_s:
            start = 591
            increment = 393
        if af_area_mode == auto:
            start -= increment
    divisor = 3.99
    if value >= 50:
        divisor = 4.01
    if image_area in {dx, one_to_one}:
        divisor = 6
        focus_box_width = int(focus_box_width * 2 / 3)
    rounded_value = perl_round(value / divisor)
    skip_positions = int(focus_box_width / 2)
    return str(start + increment * (rounded_value + skip_positions - 1))


def nikon_z9_af_area_initial_y_position(
    raw_value: str,
    runtime_context: MakerNoteRuntimeContext,
) -> str | None:
    value = parse_int(raw_value)
    image_area = runtime_context.self_int(("ImageArea",))
    af_area_mode = runtime_context.value_int(("AFAreaMode",))
    focus_box_height = runtime_context.self_int(("AFAreaInitialHeight",))
    if value is None or image_area is None or af_area_mode is None or focus_box_height is None:
        return None
    dx = 1
    wide_screen = 4
    wide_s = 3
    start = 424
    increment = 291
    if image_area == wide_screen and value > 0:
        start += increment
    if image_area == dx:
        start = 572
        increment = 436
        if af_area_mode == wide_s:
            start = 542
            increment = 442
    divisor = 6.67
    if image_area == dx:
        divisor = 10.01
        focus_box_height = int(focus_box_height * 2 / 3)
    if image_area == wide_screen:
        divisor = 8.01
    rounded_value = perl_round(value / divisor)
    skip_positions = int(focus_box_height / 2)
    return str(start + increment * (rounded_value + skip_positions - 1))


def perl_round(value: float) -> int:
    if value < 0:
        return math.ceil(value - 0.5)
    return math.floor(value + 0.5)


def print_lens_info(raw_value: str) -> str:
    values = raw_value.split()
    if len(values) != 4:
        return raw_value
    converted: list[str] = []
    for value in values:
        if is_float_text(value):
            converted.append(value)
        elif value in {"inf", "undef"}:
            converted.append("?")
        else:
            return raw_value
    focal = converted[0]
    if converted[1] != "0" and converted[1] != converted[0]:
        focal += f"-{converted[1]}"
    aperture = converted[2]
    if converted[3] != "0" and converted[3] != converted[2]:
        aperture += f"-{converted[3]}"
    return f"{focal}mm f/{aperture}"


def is_float_text(value: str) -> bool:
    return re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value) is not None


NIKON_RETOUCH_VALUES: dict[int, str] = {
    0: "None",
    3: "B & W",
    4: "Sepia",
    5: "Trim",
    6: "Small Picture",
    7: "D-Lighting",
    8: "Red Eye",
    9: "Cyanotype",
    10: "Sky Light",
    11: "Warm Tone",
    12: "Color Custom",
    13: "Image Overlay",
    14: "Red Intensifier",
    15: "Green Intensifier",
    16: "Blue Intensifier",
    17: "Cross Screen",
    18: "Quick Retouch",
    19: "NEF Processing",
    23: "Distortion Control",
    25: "Fisheye",
    26: "Straighten",
    29: "Perspective Control",
    30: "Color Outline",
    31: "Soft Filter",
    32: "Resize",
    33: "Miniature Effect",
    34: "Skin Softening",
    35: "Selected Frame",
    37: "Color Sketch",
    38: "Selective Color",
    39: "Glamour",
    40: "Drawing",
    44: "Pop",
    45: "Toy Camera Effect 1",
    46: "Toy Camera Effect 2",
    47: "Cross Process (red)",
    48: "Cross Process (blue)",
    49: "Cross Process (green)",
    50: "Cross Process (yellow)",
    51: "Super Vivid",
    52: "High-contrast Monochrome",
    53: "High Key",
    54: "Low Key",
}


def nikon_retouch_history_print(raw_value: str) -> str | None:
    values = split_integer_words(raw_value)
    if values is None:
        return None
    return " ".join(NIKON_RETOUCH_VALUES.get(value, f"Unknown ({value})") for value in values[:10])


def nikon_format_string(raw_value: str, *, limit: int = 60) -> str:
    if len(raw_value) > limit and limit >= 5:
        return raw_value[: limit - 5] + "[...]"
    formatted = re.sub(r"\s+$", "", raw_value)
    if re.search(r"[AEIOUY]", formatted) is None:
        return formatted
    current = re.sub(
        r"\b([AEIOUY])([A-Z]+)",
        lambda match: match.group(1) + match.group(2).lower(),
        formatted,
    )
    if current != formatted:
        current = re.sub(r"\bAf\b", "AF", current)
        current = re.sub(r"  +.$", "", current, flags=re.DOTALL)
    current = re.sub(
        r"\b([A-Z])([A-Z]*[AEIOUY][A-Z]*)",
        lambda match: match.group(1) + match.group(2).lower(),
        current,
    )
    return re.sub(r"\bRaw\b", "RAW", current)
