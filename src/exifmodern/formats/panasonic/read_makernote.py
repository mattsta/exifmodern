"""Panasonic MakerNote reader slice backed by ExifTool Panasonic.pm."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from exifmodern.formats.jpeg.container import (
    exiftool_binary_summary,
    read_exif_app1,
    tiff_ascii_tag_value,
    tiff_entry_raw_value_location,
    tiff_long_tag_value,
)
from exifmodern.formats.maker_notes import render_maker_note_package_print_value
from exifmodern.formats.maker_notes.context import MakerNoteRuntimeContext, maker_note_self_context
from exifmodern.formats.tiff.primitives import (
    Endian,
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
)
from exifmodern.public_interface.unknown import (
    ProcessBinaryDataKnownSpan,
    ProcessBinaryDataUnknownReadResult,
    ProcessBinaryDataUnknownReadTag,
    ProcessBinaryDataUnknownTablePolicy,
    process_binarydata_unknown_tags_from_payload,
)

type PanasonicRawValue = (
    int | str | float | bytes | Fraction | list[int] | list[Fraction | None] | None
)


@dataclass(frozen=True)
class PanasonicMakerNoteField:
    name: str
    value: str | int | float
    tag_id: int
    family_2_group: str = "Camera"


@dataclass(frozen=True)
class PanasonicMakerNoteReadResult:
    fields: tuple[PanasonicMakerNoteField, ...]
    diagnostics: tuple[str, ...]


PANASONIC_SOURCE_TABLE = "Image::ExifTool::Panasonic::Main"
PANASONIC_TIMEINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "panasonic-timeinfo-process-binarydata-unknown"
)
PANASONIC_LEICA_SERIALINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "panasonic-leica-serialinfo-process-binarydata-unknown"
)
PANASONIC_LEICA5_FOCUSINFO_PROCESS_BINARYDATA_UNKNOWN_SOURCE = (
    "panasonic-leica5-focusinfo-process-binarydata-unknown"
)
PANASONIC_TIMEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "panasonic.read.timeinfo_route",
    "panasonic.read.timeinfo_binarydata_policy",
    "panasonic.read.timeinfo_unknown_scan",
    "panasonic.read.timeinfo_unknown_prefix",
)
PANASONIC_LEICA_SERIALINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "panasonic.read.leica3_route",
    "panasonic.read.leica_serialinfo_route",
    "panasonic.read.leica_serialinfo_binarydata_policy",
    "panasonic.read.leica_serialinfo_unknown_scan",
)
PANASONIC_LEICA5_FOCUSINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "panasonic.read.leica5_route",
    "panasonic.read.leica5_focusinfo_route",
    "panasonic.read.leica5_focusinfo_binarydata_policy",
    "panasonic.read.leica5_focusinfo_format_scan",
    "panasonic.read.leica5_focusinfo_unknown_synthesis",
)
PANASONIC_LEICA5_SHOTINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE = (
    "panasonic.read.leica5_route",
    "panasonic.read.leica5_shotinfo_route",
    "panasonic.read.leica5_shotinfo_binarydata_policy",
)
type PanasonicTimeInfoUnknownReadTag = ProcessBinaryDataUnknownReadTag
type PanasonicTimeInfoUnknownReadResult = ProcessBinaryDataUnknownReadResult
type PanasonicLeicaSerialInfoUnknownReadTag = ProcessBinaryDataUnknownReadTag
type PanasonicLeicaSerialInfoUnknownReadResult = ProcessBinaryDataUnknownReadResult
type PanasonicLeica5FocusInfoUnknownReadTag = ProcessBinaryDataUnknownReadTag
type PanasonicLeica5FocusInfoUnknownReadResult = ProcessBinaryDataUnknownReadResult
_PANASONIC_TIMEINFO_TAG = 0x2003
_PANASONIC_LEICA3_SERIALINFO_TAG = 0x000B
_PANASONIC_LEICA5_FOCUSINFO_TAG = 0x040A
_PANASONIC_LEICA5_SHOTINFO_TAG = 0x0410
_PANASONIC_TIMEINFO_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Panasonic_TimeInfo",
    first_entry=0,
    increment=1,
    known_spans=(
        ProcessBinaryDataKnownSpan(start_index=0, entry_count=8),
        ProcessBinaryDataKnownSpan(start_index=16, entry_count=4),
    ),
    evidence_ids=PANASONIC_TIMEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)
_PANASONIC_LEICA_SERIALINFO_UNKNOWN_POLICY = ProcessBinaryDataUnknownTablePolicy(
    tag_prefix="Leica_SerialInfo",
    first_entry=0,
    increment=1,
    known_spans=(ProcessBinaryDataKnownSpan(start_index=4, entry_count=8),),
    evidence_ids=PANASONIC_LEICA_SERIALINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
)
_TAG_NAMES = {
    0x0001: "ImageQuality",
    0x0002: "FirmwareVersion",
    0x0003: "WhiteBalance",
    0x0007: "FocusMode",
    0x000F: "AFAreaMode",
    0x001A: "ImageStabilization",
    0x001C: "MacroMode",
    0x001F: "ShootingMode",
    0x0020: "Audio",
    0x0021: "DataDump",
    0x0023: "WhiteBalanceBias",
    0x0024: "FlashBias",
    0x0025: "InternalSerialNumber",
    0x0026: "PanasonicExifVersion",
    0x0027: "VideoFrameRate",
    0x0028: "ColorEffect",
    0x0029: "TimeSincePowerOn",
    0x002A: "BurstMode",
    0x002B: "SequenceNumber",
    0x002C: "ContrastMode",
    0x002D: "NoiseReduction",
    0x002E: "SelfTimer",
    0x0030: "Rotation",
    0x0031: "AFAssistLamp",
    0x0032: "ColorMode",
    0x0033: "BabyAge",
    0x0034: "OpticalZoomMode",
    0x0035: "ConversionLens",
    0x0036: "TravelDay",
    0x0038: "BatteryLevel",
    0x0039: "Contrast",
    0x003A: "WorldTimeLocation",
    0x003B: "TextStamp",
    0x003C: "ProgramISO",
    0x003D: "AdvancedSceneType",
    0x003E: "TextStamp",
    0x003F: "FacesDetected",
    0x0040: "Saturation",
    0x0041: "Sharpness",
    0x0042: "FilmMode",
    0x0043: "JPEGQuality",
    0x0044: "ColorTempKelvin",
    0x0045: "BracketSettings",
    0x0046: "WBShiftAB",
    0x0047: "WBShiftGM",
    0x0048: "FlashCurtain",
    0x004B: "PanasonicImageWidth",
    0x004C: "PanasonicImageHeight",
    0x004D: "AFPointPosition",
    0x004E: "FaceDetInfo",
    0x0051: "LensType",
    0x0052: "LensSerialNumber",
    0x0053: "AccessoryType",
    0x0054: "AccessorySerialNumber",
    0x005D: "IntelligentExposure",
    0x0060: "LensFirmwareVersion",
    0x0061: "FaceRecInfo",
    0x0062: "FlashWarning",
    0x0065: "Title",
    0x0066: "BabyName",
    0x0067: "Location",
    0x0069: "Country",
    0x006B: "State",
    0x006D: "City",
    0x006F: "Landmark",
    0x0070: "IntelligentResolution",
    0x0076: "MergedImages",
    0x0077: "BurstSpeed",
    0x0079: "IntelligentD-Range",
    0x007C: "ClearRetouch",
    0x0080: "City2",
    0x0089: "PhotoStyle",
    0x008A: "ShadingCompensation",
    0x008B: "WBShiftIntelligentAuto",
    0x008C: "AccelerometerZ",
    0x008D: "AccelerometerX",
    0x008E: "AccelerometerY",
    0x008F: "CameraOrientation",
    0x0090: "RollAngle",
    0x0091: "PitchAngle",
    0x0092: "WBShiftCreativeControl",
    0x0093: "SweepPanoramaDirection",
    0x0094: "SweepPanoramaFieldOfView",
    0x0096: "TimerRecording",
    0x009D: "InternalNDFilter",
    0x009E: "HDR",
    0x009F: "ShutterType",
    0x00A1: "FilterEffect",
    0x00A3: "ClearRetouchValue",
    0x00AB: "TouchAE",
    0x00AC: "MonochromeFilterEffect",
    0x00AD: "HighlightShadow",
    0x00AF: "TimeStamp",
    0x00B3: "VideoBurstResolution",
    0x00B4: "MultiExposure",
    0x00B9: "RedEyeRemoval",
    0x00BB: "VideoBurstMode",
    0x00BC: "DiffractionCorrection",
    0x00BD: "FocusBracket",
    0x00BF: "PostFocusMerging",
    0x00C1: "VideoPreburst",
    0x00C5: "LensTypeModel",
    0x00CA: "SensorType",
    0x00D2: "MonochromeGrainEffect",
    0x00D4: "HybridLogGamma",
    0x00D6: "NoiseReductionStrength",
    0x00DE: "AFAreaSize",
    0x00E4: "LensTypeModel",
    0x00E8: "MinimumISO",
    0x00E9: "AFSubjectDetection",
    0x00EE: "DynamicRangeBoost",
    0x00F1: "LUT1Name",
    0x00F3: "LUT1Opacity",
    0x00F4: "LUT2Name",
    0x00F5: "LUT2Opacity",
    0x8000: "MakerNoteVersion",
    0x8001: "SceneMode",
    0x8002: "HighlightWarning",
    0x8003: "DarkFocusEnvironment",
    0x8004: "WBRedLevel",
    0x8005: "WBGreenLevel",
    0x8006: "WBBlueLevel",
    0x8008: "TextStamp",
    0x8009: "TextStamp",
    0x8010: "BabyAge",
}
_TAG_FAMILY_2_GROUPS = {
    0x0067: "Location",
    0x0069: "Location",
    0x006B: "Location",
    0x006D: "Location",
    0x006F: "Location",
}
_PACKAGE_PRINT_TAGS = frozenset(
    {
        "AFAreaMode",
        "AFAssistLamp",
        "Audio",
        "BatteryLevel",
        "BracketSettings",
        "BurstMode",
        "CameraOrientation",
        "ClearRetouch",
        "ColorEffect",
        "ColorMode",
        "ConversionLens",
        "ContrastMode",
        "DarkFocusEnvironment",
        "DiffractionCorrection",
        "DynamicRangeBoost",
        "FilterEffect",
        "FilmMode",
        "FlashCurtain",
        "FlashWarning",
        "FocusMode",
        "HDR",
        "HighlightWarning",
        "HybridLogGamma",
        "ImageQuality",
        "ImageStabilization",
        "IntelligentD-Range",
        "IntelligentExposure",
        "IntelligentResolution",
        "JPEGQuality",
        "MacroMode",
        "MonochromeFilterEffect",
        "MonochromeGrainEffect",
        "MultiExposure",
        "NoiseReduction",
        "OpticalZoomMode",
        "PostFocusMerging",
        "PhotoStyle",
        "RedEyeRemoval",
        "Rotation",
        "SceneMode",
        "SelfTimer",
        "SensorType",
        "ShadingCompensation",
        "ShootingMode",
        "ShutterType",
        "SweepPanoramaDirection",
        "TextStamp",
        "TimerRecording",
        "TouchAE",
        "VideoBurstMode",
        "VideoBurstResolution",
        "VideoPreburst",
        "VideoFrameRate",
        "WhiteBalance",
        "WorldTimeLocation",
    }
)
_STATIC_PRINT_CONV: dict[str, dict[str | int, str]] = {
    # Semantic evidence: panasonic.read.main_printconv_tables.
    "ImageQuality": {
        1: "TIFF",
        2: "High",
        3: "Normal",
        6: "Very High",
        7: "RAW",
        9: "Motion Picture",
        11: "Full HD Movie",
        12: "4k Movie",
    },
    "WhiteBalance": {
        1: "Auto",
        2: "Daylight",
        3: "Cloudy",
        4: "Incandescent",
        5: "Manual",
        8: "Flash",
        10: "Black & White",
        11: "Manual 2",
        12: "Shade",
        13: "Kelvin",
        14: "Manual 3",
        15: "Manual 4",
        19: "Auto (cool)",
    },
    "FocusMode": {
        1: "Auto",
        2: "Manual",
        4: "Auto, Focus button",
        5: "Auto, Continuous",
        6: "AF-S",
        7: "AF-C",
        8: "AF-F",
    },
    "AFAreaMode": {
        "0 1": "9-area",
        "0 16": "3-area (high speed)",
        "0 23": "23-area",
        "0 49": "49-area",
        "0 225": "225-area",
        "1 0": "Spot Focusing",
        "1 1": "5-area",
        "16": "Normal?",
        "16 0": "1-area",
        "16 16": "1-area (high speed)",
        "16 32": "1-area +",
        "16 225": "225-area 2",
        "17 0": "Full Area",
        "32 0": "Tracking",
        "32 1": "3-area (left)?",
        "32 2": "3-area (center)?",
        "32 3": "3-area (right)?",
        "32 16": "Zone",
        "32 18": "Zone (horizontal/vertical)",
        "64 0": "Face Detect",
        "64 1": "Face Detect (animal detect on)",
        "64 2": "Face Detect (animal detect off)",
        "128 0": "Pinpoint focus",
        "240 0": "Tracking",
    },
    "ImageStabilization": {
        2: "On, Optical",
        3: "Off",
        4: "On, Mode 2",
        5: "On, Optical Panning",
        6: "On, Body-only",
        7: "On, Body-only Panning",
        9: "Dual IS",
        10: "Dual IS Panning",
        11: "Dual2 IS",
        12: "Dual2 IS Panning",
    },
    "MacroMode": {1: "On", 2: "Off", 0x101: "Tele-Macro", 0x201: "Macro Zoom"},
    "ShootingMode": {
        1: "Normal",
        2: "Portrait",
        3: "Scenery",
        4: "Sports",
        5: "Night Portrait",
        6: "Program",
        7: "Aperture Priority",
        8: "Shutter Priority",
        9: "Macro",
        10: "Spot",
        11: "Manual",
        12: "Movie Preview",
        13: "Panning",
        14: "Simple",
        15: "Color Effects",
        16: "Self Portrait",
        17: "Economy",
        18: "Fireworks",
        19: "Party",
        20: "Snow",
        21: "Night Scenery",
        22: "Food",
        23: "Baby",
        24: "Soft Skin",
        25: "Candlelight",
        26: "Starry Night",
        27: "High Sensitivity",
        28: "Panorama Assist",
        29: "Underwater",
        30: "Beach",
        31: "Aerial Photo",
        32: "Sunset",
        33: "Pet",
        34: "Intelligent ISO",
        35: "Clipboard",
        36: "High Speed Continuous Shooting",
        37: "Intelligent Auto",
        39: "Multi-aspect",
        41: "Transform",
        42: "Flash Burst",
        43: "Pin Hole",
        44: "Film Grain",
        45: "My Color",
        46: "Photo Frame",
        48: "Movie",
        51: "HDR",
        52: "Peripheral Defocus",
        55: "Handheld Night Shot",
        57: "3D",
        59: "Creative Control",
        60: "Intelligent Auto Plus",
        62: "Panorama",
        63: "Glass Through",
        64: "HDR",
        66: "Digital Filter",
        67: "Clear Portrait",
        68: "Silky Skin",
        69: "Backlit Softness",
        70: "Clear in Backlight",
        71: "Relaxing Tone",
        72: "Sweet Child's Face",
        73: "Distinct Scenery",
        74: "Bright Blue Sky",
        75: "Romantic Sunset Glow",
        76: "Vivid Sunset Glow",
        77: "Glistening Water",
        78: "Clear Nightscape",
        79: "Cool Night Sky",
        80: "Warm Glowing Nightscape",
        81: "Artistic Nightscape",
        82: "Glittering Illuminations",
        83: "Clear Night Portrait",
        84: "Soft Image of a Flower",
        85: "Appetizing Food",
        86: "Cute Dessert",
        87: "Freeze Animal Motion",
        88: "Clear Sports Shot",
        89: "Monochrome",
        90: "Creative Control",
        92: "Handheld Night Shot",
    },
    "Audio": {1: "Yes", 2: "No", 3: "Stereo"},
    "VideoFrameRate": {0: "n/a"},
    "ColorEffect": {
        1: "Off",
        2: "Warm",
        3: "Cool",
        4: "Black & White",
        5: "Sepia",
        6: "Happy",
        8: "Vivid",
    },
    "BurstMode": {
        0: "Off",
        1: "On",
        2: "Auto Exposure Bracketing (AEB)",
        3: "Focus Bracketing",
        4: "Unlimited",
        8: "White Balance Bracketing",
        17: "On (with flash)",
        18: "Aperture Bracketing",
    },
    "ContrastMode": {
        0x00: "Normal",
        0x01: "Low",
        0x02: "High",
        0x05: "Normal 2",
        0x06: "Medium Low",
        0x07: "Medium High",
        0x0D: "High Dynamic",
        0x18: "Dynamic Range (film-like)",
        0x2E: "Match Filter Effects Toy",
        0x37: "Match Photo Style L. Monochrome",
        0x100: "Low",
        0x110: "Normal",
        0x120: "High",
    },
    "NoiseReduction": {
        0: "Standard",
        1: "Low (-1)",
        2: "High (+1)",
        3: "Lowest (-2)",
        4: "Highest (+2)",
        5: "+5",
        6: "+6",
        65531: "-5",
        65532: "-4",
        65533: "-3",
        65534: "-2",
        65535: "-1",
    },
    "SelfTimer": {
        0: "Off (0)",
        1: "Off",
        2: "10 s",
        3: "2 s",
        4: "10 s / 3 pictures",
        258: "2 s after shutter pressed",
        266: "10 s after shutter pressed",
        778: "3 photos after 10 s",
    },
    "Rotation": {
        1: "Horizontal (normal)",
        3: "Rotate 180",
        6: "Rotate 90 CW",
        8: "Rotate 270 CW",
    },
    "AFAssistLamp": {
        1: "Fired",
        2: "Enabled but Not Used",
        3: "Disabled but Required",
        4: "Disabled and Not Required",
    },
    "ColorMode": {0: "Normal", 1: "Natural", 2: "Vivid"},
    "OpticalZoomMode": {1: "Standard", 2: "Extended"},
    "ConversionLens": {1: "Off", 2: "Wide", 3: "Telephoto", 4: "Macro"},
    "BatteryLevel": {
        1: "Full",
        2: "Medium",
        3: "Low",
        4: "Near Empty",
        7: "Near Full",
        8: "Medium Low",
        256: "n/a",
    },
    "WorldTimeLocation": {1: "Home", 2: "Destination"},
    "TextStamp": {1: "Off", 2: "On"},
    "FilmMode": {
        0: "n/a",
        1: "Standard (color)",
        2: "Dynamic (color)",
        3: "Nature (color)",
        4: "Smooth (color)",
        5: "Standard (B&W)",
        6: "Dynamic (B&W)",
        7: "Smooth (B&W)",
        10: "Nostalgic",
        11: "Vibrant",
    },
    "JPEGQuality": {
        0: "n/a (Movie)",
        2: "High",
        3: "Standard",
        6: "Very High",
        255: "n/a (RAW only)",
    },
    "BracketSettings": {
        0: "No Bracket",
        1: "3 Images, Sequence 0/-/+",
        2: "3 Images, Sequence -/0/+",
        3: "5 Images, Sequence 0/-/+",
        4: "5 Images, Sequence -/0/+",
        5: "7 Images, Sequence 0/-/+",
        6: "7 Images, Sequence -/0/+",
    },
    "FlashCurtain": {0: "n/a", 1: "1st", 2: "2nd"},
    "IntelligentExposure": {0: "Off", 1: "Low", 2: "Standard", 3: "High"},
    "FlashWarning": {0: "No", 1: "Yes (flash required but disabled)"},
    "IntelligentResolution": {0: "Off", 1: "Low", 2: "Standard", 3: "High", 4: "Extended"},
    "IntelligentD-Range": {0: "Off", 1: "Low", 2: "Standard", 3: "High"},
    "ClearRetouch": {0: "Off", 1: "On"},
    "PhotoStyle": {
        0: "Auto",
        1: "Standard or Custom",
        2: "Vivid",
        3: "Natural",
        4: "Monochrome",
        5: "Scenery",
        6: "Portrait",
        8: "Cinelike D",
        9: "Cinelike V",
        11: "L. Monochrome",
        12: "Like709",
        15: "L. Monochrome D",
        17: "V-Log",
        18: "Cinelike D2",
    },
    "ShadingCompensation": {0: "Off", 1: "On"},
    "CameraOrientation": {
        0: "Normal",
        1: "Rotate CW",
        2: "Rotate 180",
        3: "Rotate CCW",
        4: "Tilt Upwards",
        5: "Tilt Downwards",
    },
    "SweepPanoramaDirection": {
        0: "Off",
        1: "Left to Right",
        2: "Right to Left",
        3: "Top to Bottom",
        4: "Bottom to Top",
    },
    "TimerRecording": {
        0: "Off",
        1: "Time Lapse",
        2: "Stop-motion Animation",
        3: "Focus Bracketing",
    },
    "HDR": {
        0: "Off",
        100: "1 EV",
        200: "2 EV",
        300: "3 EV",
        32868: "1 EV (Auto)",
        32968: "2 EV (Auto)",
        33068: "3 EV (Auto)",
    },
    "ShutterType": {0: "Mechanical", 1: "Electronic", 2: "Hybrid"},
    "FilterEffect": {
        "0 0": "Off",
        "0 1": "Expressive",
        "0 2": "Retro",
        "0 4": "High Key",
        "0 8": "Sepia",
        "0 16": "High Dynamic",
        "0 32": "Miniature Effect",
        "0 256": "Low Key",
        "0 512": "Toy Effect",
        "0 1024": "Dynamic Monochrome",
        "0 2048": "Soft Focus",
        "0 4096": "Impressive Art",
        "0 8192": "Cross Process",
        "0 16384": "One Point Color",
        "0 32768": "Star Filter",
        "0 524288": "Old Days",
        "0 1048576": "Sunshine",
        "0 2097152": "Bleach Bypass",
        "0 4194304": "Toy Pop",
        "0 8388608": "Fantasy",
        "0 33554432": "Monochrome",
        "0 67108864": "Rough Monochrome",
        "0 134217728": "Silky Monochrome",
    },
    "TouchAE": {0: "Off", 1: "On"},
    "MonochromeFilterEffect": {0: "Off", 1: "Yellow", 2: "Orange", 3: "Red", 4: "Green"},
    "VideoBurstResolution": {1: "Off or 4K", 4: "6K"},
    "MultiExposure": {0: "n/a", 1: "Off", 2: "On"},
    "RedEyeRemoval": {0: "Off", 1: "On"},
    "VideoBurstMode": {
        0x01: "Off",
        0x04: "Post Focus",
        0x18: "4K Burst",
        0x28: "4K Burst (Start/Stop)",
        0x48: "4K Pre-burst",
        0x108: "Loop Recording",
        0x408: "Focus Stacking",
        0x810: "6K Burst",
        0x820: "6K Burst (Start/Stop)",
        0x1001: "High Resolution Mode",
    },
    "DiffractionCorrection": {0: "Off", 1: "Auto"},
    "PostFocusMerging": {"0 0": "Post Focus Auto Merging or None"},
    "VideoPreburst": {0: "No", 1: "4K or 6K"},
    "SensorType": {0: "Multi-aspect", 1: "Standard"},
    "MonochromeGrainEffect": {0: "Off", 1: "Low", 2: "Standard", 3: "High"},
    "HybridLogGamma": {0: "Off", 1: "On"},
    "AFSubjectDetection": {
        0: "n/a",
        1: "Human Eye/Face/Body",
        2: "Animal",
        3: "Human Eye/Face",
        4: "Animal Body",
        5: "Animal Eye/Body",
        6: "Car",
        7: "Motorcycle",
        8: "Car (main part priority)",
        9: "Motorcycle (helmet priority)",
        10: "Train",
        11: "Train (main part priority)",
        12: "Airplane",
        13: "Airplane (nose priority)",
    },
    "DynamicRangeBoost": {0: "Off", 1: "On"},
    "SceneMode": {
        0: "Off",
        1: "Normal",
        2: "Portrait",
        3: "Scenery",
        4: "Sports",
        5: "Night Portrait",
        6: "Program",
        7: "Aperture Priority",
        8: "Shutter Priority",
        9: "Macro",
        10: "Spot",
        11: "Manual",
        12: "Movie Preview",
        13: "Panning",
        14: "Simple",
        15: "Color Effects",
        16: "Self Portrait",
        17: "Economy",
        18: "Fireworks",
        19: "Party",
        20: "Snow",
        21: "Night Scenery",
        22: "Food",
        23: "Baby",
        24: "Soft Skin",
        25: "Candlelight",
        26: "Starry Night",
        27: "High Sensitivity",
        28: "Panorama Assist",
        29: "Underwater",
        30: "Beach",
        31: "Aerial Photo",
        32: "Sunset",
        33: "Pet",
        34: "Intelligent ISO",
        35: "Clipboard",
        36: "High Speed Continuous Shooting",
        37: "Intelligent Auto",
        39: "Multi-aspect",
        41: "Transform",
        42: "Flash Burst",
        43: "Pin Hole",
        44: "Film Grain",
        45: "My Color",
        46: "Photo Frame",
        48: "Movie",
        51: "HDR",
        52: "Peripheral Defocus",
        55: "Handheld Night Shot",
        57: "3D",
        59: "Creative Control",
        60: "Intelligent Auto Plus",
        62: "Panorama",
        63: "Glass Through",
        64: "HDR",
        66: "Digital Filter",
        67: "Clear Portrait",
        68: "Silky Skin",
        69: "Backlit Softness",
        70: "Clear in Backlight",
        71: "Relaxing Tone",
        72: "Sweet Child's Face",
        73: "Distinct Scenery",
        74: "Bright Blue Sky",
        75: "Romantic Sunset Glow",
        76: "Vivid Sunset Glow",
        77: "Glistening Water",
        78: "Clear Nightscape",
        79: "Cool Night Sky",
        80: "Warm Glowing Nightscape",
        81: "Artistic Nightscape",
        82: "Glittering Illuminations",
        83: "Clear Night Portrait",
        84: "Soft Image of a Flower",
        85: "Appetizing Food",
        86: "Cute Dessert",
        87: "Freeze Animal Motion",
        88: "Clear Sports Shot",
        89: "Monochrome",
        90: "Creative Control",
        92: "Handheld Night Shot",
    },
    "HighlightWarning": {0: "Disabled", 1: "No", 2: "Yes"},
    "DarkFocusEnvironment": {1: "No", 2: "Yes"},
}
_PARAMETER_PRINT_TAGS = frozenset({"Contrast", "Saturation", "Sharpness"})
_RAW_OR_NA_TAGS = frozenset({"ProgramISO", "TravelDay"})
_SCALAR_TAGS = frozenset(
    {
        "AdvancedSceneType",
        "AccelerometerX",
        "AccelerometerY",
        "AccelerometerZ",
        "BurstSpeed",
        "ColorTempKelvin",
        "FacesDetected",
        "FocusBracket",
        "InternalNDFilter",
        "LUT1Opacity",
        "LUT2Opacity",
        "MergedImages",
        "MinimumISO",
        "NoiseReductionStrength",
        "PanasonicImageHeight",
        "PanasonicImageWidth",
        "SequenceNumber",
        "SweepPanoramaFieldOfView",
        "WBBlueLevel",
        "WBGreenLevel",
        "WBRedLevel",
        "WBShiftAB",
        "WBShiftCreativeControl",
        "WBShiftGM",
        "WBShiftIntelligentAuto",
    }
)
_SIGNED_SHORT_TAGS = frozenset(
    {
        "AccelerometerX",
        "AccelerometerY",
        "AccelerometerZ",
        "FlashBias",
        "FocusBracket",
        "PitchAngle",
        "RollAngle",
        "WBShiftAB",
        "WBShiftIntelligentAuto",
        "WBShiftGM",
        "WhiteBalanceBias",
    }
)
_TRIMMED_STRING_TAGS = frozenset(
    {
        "AccessorySerialNumber",
        "AccessoryType",
        "BabyName",
        "City",
        "City2",
        "Country",
        "Landmark",
        "LensSerialNumber",
        "LensType",
        "Location",
        "LUT1Name",
        "LUT2Name",
        "State",
        "Title",
    }
)
_NOT_SET_AGE = "9999:99:99 00:00:00"


def read_panasonic_maker_note_from_jpeg(path: Path) -> PanasonicMakerNoteReadResult:
    context_result = _panasonic_maker_note_context_from_jpeg(path)
    return _panasonic_maker_note_read_result(context_result)


def read_panasonic_maker_note_from_tiff_data(tiff_data: bytes) -> PanasonicMakerNoteReadResult:
    context_result = _panasonic_maker_note_context_from_tiff_data(tiff_data)
    return _panasonic_maker_note_read_result(context_result)


def read_panasonic_maker_note_from_parsed_tiff_data(
    tiff_data: bytes,
    ifd0: Ifd,
    exif_ifd: Ifd,
    endian: Endian,
) -> PanasonicMakerNoteReadResult:
    context_result = _panasonic_maker_note_context_from_parsed_tiff_data(
        tiff_data,
        ifd0,
        exif_ifd,
        endian,
    )
    return _panasonic_maker_note_read_result(context_result)


def _panasonic_maker_note_read_result(
    context_result: _PanasonicMakerNoteContext | PanasonicMakerNoteReadResult,
) -> PanasonicMakerNoteReadResult:
    if isinstance(context_result, PanasonicMakerNoteReadResult):
        return context_result
    context = _runtime_context(context_result.make, context_result.model)
    return PanasonicMakerNoteReadResult(
        tuple(
            field
            for entry in context_result.maker_ifd.entries
            for field in _fields_for_entry(
                context_result.data,
                entry,
                context,
            )
        ),
        (
            "Panasonic MakerNote bridge ready: MakerNotes.pm MakerNotePanasonic routed "
            "Panasonic header to Panasonic.pm Main.",
        ),
    )


def collect_panasonic_timeinfo_process_binary_unknown_read_tags(
    path: Path,
) -> PanasonicTimeInfoUnknownReadResult:
    context_result = _panasonic_maker_note_context_from_jpeg(path)
    if isinstance(context_result, PanasonicMakerNoteReadResult):
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=tuple(
                diagnostic.replace(
                    "Panasonic MakerNote blocked",
                    "Panasonic TimeInfo ProcessBinaryData unknown discovery blocked",
                )
                for diagnostic in context_result.diagnostics
            ),
            evidence_ids=PANASONIC_TIMEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    entry = next(
        (
            candidate
            for candidate in context_result.maker_ifd.entries
            if candidate.tag_id == _PANASONIC_TIMEINFO_TAG
        ),
        None,
    )
    if entry is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                "Panasonic TimeInfo ProcessBinaryData unknown discovery blocked: "
                "missing TimeInfo tag 0x2003.",
            ),
            evidence_ids=PANASONIC_TIMEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    raw_location = tiff_entry_raw_value_location(context_result.data, entry, "little")
    if raw_location is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                "Panasonic TimeInfo ProcessBinaryData unknown discovery blocked: "
                "raw value is truncated.",
            ),
            evidence_ids=PANASONIC_TIMEINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    _, payload = raw_location
    result = process_binarydata_unknown_tags_from_payload(
        payload,
        _PANASONIC_TIMEINFO_UNKNOWN_POLICY,
    )
    return ProcessBinaryDataUnknownReadResult(
        tags=result.tags,
        diagnostics=tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                "Panasonic TimeInfo ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        evidence_ids=result.evidence_ids,
    )


def collect_panasonic_leica_serialinfo_process_binary_unknown_read_tags(
    path: Path,
) -> PanasonicLeicaSerialInfoUnknownReadResult:
    context_result = _panasonic_leica3_maker_note_context_from_jpeg(path)
    if isinstance(context_result, PanasonicMakerNoteReadResult):
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=tuple(
                diagnostic.replace(
                    "Panasonic Leica3 MakerNote blocked",
                    "Panasonic Leica3 SerialInfo ProcessBinaryData unknown discovery blocked",
                )
                for diagnostic in context_result.diagnostics
            ),
            evidence_ids=PANASONIC_LEICA_SERIALINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    entry = next(
        (
            candidate
            for candidate in context_result.maker_ifd.entries
            if candidate.tag_id == _PANASONIC_LEICA3_SERIALINFO_TAG
        ),
        None,
    )
    if entry is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(),
            evidence_ids=PANASONIC_LEICA_SERIALINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    raw_location = tiff_entry_raw_value_location(
        context_result.data,
        entry,
        context_result.byte_order,
    )
    if raw_location is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                "Panasonic Leica3 SerialInfo ProcessBinaryData unknown discovery blocked: "
                "raw value is truncated.",
            ),
            evidence_ids=PANASONIC_LEICA_SERIALINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    _, payload = raw_location
    result = process_binarydata_unknown_tags_from_payload(
        payload,
        _PANASONIC_LEICA_SERIALINFO_UNKNOWN_POLICY,
    )
    return ProcessBinaryDataUnknownReadResult(
        tags=result.tags,
        diagnostics=tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                "Panasonic Leica3 SerialInfo ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        evidence_ids=result.evidence_ids,
    )


def collect_panasonic_leica5_focusinfo_process_binary_unknown_read_tags(
    path: Path,
) -> PanasonicLeica5FocusInfoUnknownReadResult:
    context_result = _panasonic_leica5_maker_note_context_from_jpeg(path)
    if isinstance(context_result, PanasonicMakerNoteReadResult):
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=tuple(
                diagnostic.replace(
                    "Panasonic Leica5 MakerNote blocked",
                    "Panasonic Leica5 FocusInfo ProcessBinaryData unknown discovery blocked",
                )
                for diagnostic in context_result.diagnostics
            ),
            evidence_ids=PANASONIC_LEICA5_FOCUSINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    entry = next(
        (
            candidate
            for candidate in context_result.maker_ifd.entries
            if candidate.tag_id == _PANASONIC_LEICA5_FOCUSINFO_TAG
        ),
        None,
    )
    if entry is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(),
            evidence_ids=PANASONIC_LEICA5_FOCUSINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    raw_location = tiff_entry_raw_value_location(
        context_result.data,
        entry,
        context_result.byte_order,
    )
    if raw_location is None:
        return ProcessBinaryDataUnknownReadResult(
            tags=(),
            diagnostics=(
                "Panasonic Leica5 FocusInfo ProcessBinaryData unknown discovery blocked: "
                "raw value is truncated.",
            ),
            evidence_ids=PANASONIC_LEICA5_FOCUSINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        )
    _, payload = raw_location
    result = process_binarydata_unknown_tags_from_payload(
        payload,
        _panasonic_leica5_focusinfo_unknown_policy(context_result.byte_order),
    )
    return ProcessBinaryDataUnknownReadResult(
        tags=result.tags,
        diagnostics=tuple(
            diagnostic.replace(
                "ProcessBinaryData unknown discovery",
                "Panasonic Leica5 FocusInfo ProcessBinaryData unknown discovery",
            )
            for diagnostic in result.diagnostics
        ),
        evidence_ids=result.evidence_ids,
    )


def collect_panasonic_leica5_shotinfo_process_binary_unknown_diagnostics(
    path: Path,
) -> tuple[str, ...]:
    context_result = _panasonic_leica5_maker_note_context_from_jpeg(path)
    if isinstance(context_result, PanasonicMakerNoteReadResult):
        return tuple(
            diagnostic.replace(
                "Panasonic Leica5 MakerNote blocked",
                "Panasonic Leica5 ShotInfo ProcessBinaryData unknown discovery blocked",
            )
            for diagnostic in context_result.diagnostics
        )
    entry = next(
        (
            candidate
            for candidate in context_result.maker_ifd.entries
            if candidate.tag_id == _PANASONIC_LEICA5_SHOTINFO_TAG
        ),
        None,
    )
    if entry is None:
        return ()
    raw_location = tiff_entry_raw_value_location(
        context_result.data,
        entry,
        context_result.byte_order,
    )
    if raw_location is None:
        return (
            "Panasonic Leica5 ShotInfo ProcessBinaryData unknown discovery blocked: "
            "raw value is truncated.",
        )
    return (
        "Panasonic Leica5 ShotInfo ProcessBinaryData unknown discovery blocked: "
        "ShotInfo has no table FORMAT, so ExifTool scans default int8u entries, but "
        "declared FileIndex at index 0 uses tag-local int16u. Table-local nextIndex "
        "semantics are required before exposing unknown bytes.",
    )


def _panasonic_leica5_focusinfo_unknown_policy(
    endian: Endian,
) -> ProcessBinaryDataUnknownTablePolicy:
    return ProcessBinaryDataUnknownTablePolicy(
        tag_prefix="Leica_FocusInfo",
        first_entry=0,
        increment=2,
        known_spans=(ProcessBinaryDataKnownSpan(start_index=0, entry_count=2),),
        evidence_ids=PANASONIC_LEICA5_FOCUSINFO_PROCESS_BINARYDATA_SOURCE_EVIDENCE,
        byte_order=endian,
    )


@dataclass(frozen=True)
class _PanasonicMakerNoteContext:
    data: bytes
    maker_ifd: Ifd
    make: str | None
    model: str | None
    byte_order: Endian = "little"


def _panasonic_maker_note_context_from_jpeg(
    path: Path,
) -> _PanasonicMakerNoteContext | PanasonicMakerNoteReadResult:
    exif = read_exif_app1(path)
    return _panasonic_maker_note_context_from_tiff_data(exif.tiff_data)


def _panasonic_maker_note_context_from_tiff_data(
    tiff_data: bytes,
) -> _PanasonicMakerNoteContext | PanasonicMakerNoteReadResult:
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    exif_ifd_offset = tiff_long_tag_value(tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic MakerNote blocked: missing ExifIFD pointer.",)
        )
    exif_ifd = parse_ifd(tiff_data, exif_ifd_offset, header.endian)
    return _panasonic_maker_note_context_from_parsed_tiff_data(
        tiff_data,
        ifd0,
        exif_ifd,
        header.endian,
    )


def _panasonic_maker_note_context_from_parsed_tiff_data(
    tiff_data: bytes,
    ifd0: Ifd,
    exif_ifd: Ifd,
    endian: Endian,
) -> _PanasonicMakerNoteContext | PanasonicMakerNoteReadResult:
    make = tiff_ascii_tag_value(tiff_data, ifd0.entries, 0x010F, endian)
    model = tiff_ascii_tag_value(tiff_data, ifd0.entries, 0x0110, endian)
    entry = next((candidate for candidate in exif_ifd.entries if candidate.tag_id == 0x927C), None)
    if entry is None:
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic MakerNote blocked: missing tag 0x927c.",)
        )
    raw_location = tiff_entry_raw_value_location(tiff_data, entry, endian)
    if raw_location is None:
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic MakerNote blocked: raw value is truncated.",)
        )
    maker_offset, raw = raw_location
    if make is None or not make.startswith("Panasonic"):
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic MakerNote blocked: IFD0 Make did not select Panasonic.",)
        )
    if not raw.startswith(b"Panasonic"):
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic MakerNote blocked: missing Panasonic header.",)
        )
    try:
        maker_ifd = parse_ifd(tiff_data, maker_offset + 12, "little")
    except ValueError as exc:
        return PanasonicMakerNoteReadResult((), (f"Panasonic MakerNote blocked: {exc}",))
    return _PanasonicMakerNoteContext(tiff_data, maker_ifd, make, model)


def _panasonic_leica3_maker_note_context_from_jpeg(
    path: Path,
) -> _PanasonicMakerNoteContext | PanasonicMakerNoteReadResult:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    model = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x0110, header.endian)
    exif_ifd_offset = tiff_long_tag_value(exif.tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic Leica3 MakerNote blocked: missing ExifIFD pointer.",)
        )
    exif_ifd = parse_ifd(exif.tiff_data, exif_ifd_offset, header.endian)
    entry = next((candidate for candidate in exif_ifd.entries if candidate.tag_id == 0x927C), None)
    if entry is None:
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic Leica3 MakerNote blocked: missing tag 0x927c.",)
        )
    raw_location = tiff_entry_raw_value_location(exif.tiff_data, entry, header.endian)
    if raw_location is None:
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic Leica3 MakerNote blocked: raw value is truncated.",)
        )
    maker_offset, raw = raw_location
    if make is None or not make.startswith("Leica Camera AG"):
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic Leica3 MakerNote blocked: IFD0 Make did not select Leica3.",)
        )
    if model in {"S2", "LEICA M (Typ 240)"} or raw.startswith(b"LEICA"):
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic Leica3 MakerNote blocked: MakerNotes.pm Leica3 condition failed.",)
        )
    try:
        maker_ifd = parse_ifd(exif.tiff_data, maker_offset, header.endian)
    except ValueError as exc:
        return PanasonicMakerNoteReadResult((), (f"Panasonic Leica3 MakerNote blocked: {exc}",))
    return _PanasonicMakerNoteContext(exif.tiff_data, maker_ifd, make, model, header.endian)


def _panasonic_leica5_maker_note_context_from_jpeg(
    path: Path,
) -> _PanasonicMakerNoteContext | PanasonicMakerNoteReadResult:
    exif = read_exif_app1(path)
    header = parse_tiff_header(exif.tiff_data)
    ifd0 = parse_ifd(exif.tiff_data, header.first_ifd_offset, header.endian)
    make = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x010F, header.endian)
    model = tiff_ascii_tag_value(exif.tiff_data, ifd0.entries, 0x0110, header.endian)
    exif_ifd_offset = tiff_long_tag_value(exif.tiff_data, ifd0.entries, 0x8769, header.endian)
    if exif_ifd_offset is None:
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic Leica5 MakerNote blocked: missing ExifIFD pointer.",)
        )
    exif_ifd = parse_ifd(exif.tiff_data, exif_ifd_offset, header.endian)
    entry = next((candidate for candidate in exif_ifd.entries if candidate.tag_id == 0x927C), None)
    if entry is None:
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic Leica5 MakerNote blocked: missing tag 0x927c.",)
        )
    raw_location = tiff_entry_raw_value_location(exif.tiff_data, entry, header.endian)
    if raw_location is None:
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic Leica5 MakerNote blocked: raw value is truncated.",)
        )
    maker_offset, raw = raw_location
    if not raw.startswith((b"LEICA\x00\x01\x00", b"LEICA\x00\x04\x00", b"LEICA\x00\x05\x00")):
        return PanasonicMakerNoteReadResult(
            (), ("Panasonic Leica5 MakerNote blocked: MakerNotes.pm Leica5 condition failed.",)
        )
    try:
        maker_ifd = parse_ifd(exif.tiff_data, maker_offset + 8, header.endian)
    except ValueError as exc:
        return PanasonicMakerNoteReadResult((), (f"Panasonic Leica5 MakerNote blocked: {exc}",))
    return _PanasonicMakerNoteContext(exif.tiff_data, maker_ifd, make, model, header.endian)


def _field(
    raw: bytes,
    entry: IfdEntry,
    runtime_context: MakerNoteRuntimeContext | None = None,
) -> PanasonicMakerNoteField:
    context = runtime_context or _runtime_context(None, None)
    name = _TAG_NAMES[entry.tag_id]
    value = read_entry_value(raw, entry, "little")
    if name in _SIGNED_SHORT_TAGS and isinstance(value, int):
        value = _signed_16(value)
    if name == "FirmwareVersion" and isinstance(value, bytes):
        rendered: str | int | float = ".".join(str(part) for part in value)
    elif name == "DataDump":
        rendered = exiftool_binary_summary(entry.count)
    elif name in {"WhiteBalanceBias", "FlashBias"} and isinstance(value, int):
        rendered = value // 3 if value % 3 == 0 else value / 3
    elif name == "InternalSerialNumber" and isinstance(value, bytes):
        rendered = _internal_serial_number(value)
    elif (name == "PanasonicExifVersion" and isinstance(value, bytes)) or (
        name == "MakerNoteVersion" and isinstance(value, bytes)
    ):
        rendered = value.decode("ascii", errors="replace")
    elif name == "TimeSincePowerOn" and isinstance(value, int):
        rendered = _time_since_power_on(value)
    elif name in {"RollAngle", "PitchAngle"} and isinstance(value, int):
        angle = value / 10
        if name == "PitchAngle":
            angle = -angle
        rendered = _number_value(angle)
    elif name == "WBShiftCreativeControl" and isinstance(value, int):
        rendered = _signed_8(value)
    elif name == "LensTypeModel" and isinstance(value, int):
        rendered = _lens_type_model(value)
    elif name == "AFAreaSize" and isinstance(value, list):
        rendered = _af_area_size(value)
    elif name == "ClearRetouchValue" and isinstance(value, int | Fraction) and value == 0:
        rendered = "undef"
    elif name == "HighlightShadow" and isinstance(value, list):
        rendered = _joined_values(value)
    elif name == "TimeStamp" and isinstance(value, str):
        rendered = value
    elif name == "BabyAge" and isinstance(value, str):
        rendered = "(not set)" if value == _NOT_SET_AGE else value
    elif name == "AFPointPosition" and isinstance(value, list):
        rendered = _af_point_position(value)
    elif name == "LensFirmwareVersion":
        rendered = _lens_firmware_version(value)
    elif name in _TRIMMED_STRING_TAGS:
        rendered = _string_value(value).strip()
    elif name in _PARAMETER_PRINT_TAGS and isinstance(value, int):
        rendered = _print_parameter(value)
    elif name in _RAW_OR_NA_TAGS and isinstance(value, int):
        rendered = "n/a" if value in {65535, 65534} else value
    elif name in _SCALAR_TAGS and isinstance(value, int):
        rendered = value
    else:
        rendered = _package_or_raw(name, value, context)
    return PanasonicMakerNoteField(
        name,
        rendered,
        entry.tag_id,
        _TAG_FAMILY_2_GROUPS.get(entry.tag_id, "Camera"),
    )


def _fields_for_entry(
    raw: bytes,
    entry: IfdEntry,
    runtime_context: MakerNoteRuntimeContext,
) -> tuple[PanasonicMakerNoteField, ...]:
    if entry.tag_id == _PANASONIC_TIMEINFO_TAG:
        return _time_info_fields(raw, entry)
    if entry.tag_id not in _TAG_NAMES:
        return ()
    if entry.tag_id == 0x004E:
        return _face_det_info_fields(raw, entry)
    if entry.tag_id == 0x0061:
        return _face_rec_info_fields(raw, entry)
    return (_field(raw, entry, runtime_context),)


def _time_info_fields(raw: bytes, entry: IfdEntry) -> tuple[PanasonicMakerNoteField, ...]:
    raw_location = tiff_entry_raw_value_location(raw, entry, "little")
    if raw_location is None:
        return ()
    _, payload = raw_location
    if len(payload) < 20:
        return ()
    # Semantic evidence: panasonic.read.timeinfo_tag16_seconds.
    # `TimeLapseShotNumber`, Format int32u, little-endian ProcessBinaryData.
    return (
        PanasonicMakerNoteField(
            "TimeLapseShotNumber",
            int.from_bytes(payload[16:20], "little"),
            16,
            "Image",
        ),
    )


def _runtime_context(make: str | None, model: str | None) -> MakerNoteRuntimeContext:
    return MakerNoteRuntimeContext(
        values=(
            maker_note_self_context(("Make",), make or ""),
            maker_note_self_context(("Model",), model or ""),
        )
    )


def _package_or_raw(
    tag_name: str,
    value: PanasonicRawValue,
    runtime_context: MakerNoteRuntimeContext,
) -> str | int | float:
    if tag_name in _PACKAGE_PRINT_TAGS:
        raw_key = _package_raw_key(value)
        static_value = _static_print(tag_name, raw_key)
        if static_value is not None:
            return static_value
        package_value = _package_print(tag_name, raw_key, runtime_context)
        if package_value is not None:
            return package_value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, bytes):
        return value.decode("ascii", errors="replace")
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, list):
        return " ".join("" if part is None else str(part) for part in value)
    return "" if value is None else str(value)


def _package_raw_key(value: PanasonicRawValue) -> str | int:
    if isinstance(value, list):
        return " ".join("" if part is None else str(part) for part in value)
    if isinstance(value, bytes):
        return value.decode("ascii", errors="replace")
    if isinstance(value, float | Fraction):
        return str(value)
    if value is None:
        return ""
    return value


def _package_print(
    tag_name: str,
    raw_value: int | str,
    runtime_context: MakerNoteRuntimeContext,
) -> str | None:
    return render_maker_note_package_print_value(
        module="Image::ExifTool::Panasonic",
        table="Main",
        tag_name=tag_name,
        raw_value=raw_value,
        runtime_context=runtime_context,
    )


def _static_print(tag_name: str, raw_value: int | str) -> str | None:
    values = _STATIC_PRINT_CONV.get(tag_name)
    if values is None:
        return None
    direct = values.get(raw_value)
    if direct is not None:
        return direct
    if isinstance(raw_value, str) and raw_value.isdecimal():
        return values.get(int(raw_value))
    return None


def _internal_serial_number(raw_value: bytes) -> str:
    serial = raw_value.rstrip(b"\x00").decode("ascii", errors="replace")
    if len(serial) < 13:
        return serial
    year = int(serial[3:5])
    full_year = year + (2000 if year < 70 else 1900)
    return f"({serial[:3]}) {full_year}:{serial[5:7]}:{serial[7:9]} no. {serial[9:13]}"


def _face_det_info_fields(raw: bytes, entry: IfdEntry) -> tuple[PanasonicMakerNoteField, ...]:
    raw_location = tiff_entry_raw_value_location(raw, entry, "little")
    if raw_location is None:
        return ()
    _, payload = raw_location
    if len(payload) < 2:
        return ()
    fields: list[PanasonicMakerNoteField] = [
        PanasonicMakerNoteField("NumFacePositions", int.from_bytes(payload[0:2], "little"), 0x004E)
    ]
    face_count = min(fields[0].value if isinstance(fields[0].value, int) else 0, 5)
    for index in range(face_count):
        start = 2 + index * 8
        end = start + 8
        if end > len(payload):
            break
        values = [
            int.from_bytes(payload[offset : offset + 2], "little")
            for offset in range(start, end, 2)
        ]
        fields.append(
            PanasonicMakerNoteField(
                f"Face{index + 1}Position",
                " ".join(str(value) for value in values),
                0x004E,
                "Image",
            )
        )
    return tuple(fields)


def _face_rec_info_fields(raw: bytes, entry: IfdEntry) -> tuple[PanasonicMakerNoteField, ...]:
    raw_location = tiff_entry_raw_value_location(raw, entry, "little")
    if raw_location is None:
        return ()
    _, payload = raw_location
    if len(payload) < 2:
        return ()
    fields: list[PanasonicMakerNoteField] = [
        PanasonicMakerNoteField("FacesRecognized", int.from_bytes(payload[0:2], "little"), 0x0061)
    ]
    face_count = min(fields[0].value if isinstance(fields[0].value, int) else 0, 3)
    for index in range(face_count):
        base = 4 + index * 48
        name = _payload_string(payload, base, 20)
        position = _payload_u16_list(payload, base + 20, 4)
        age = _payload_string(payload, base + 28, 20)
        if name is not None:
            fields.append(PanasonicMakerNoteField(f"RecognizedFace{index + 1}Name", name, 0x0061))
        if position is not None:
            fields.append(
                PanasonicMakerNoteField(
                    f"RecognizedFace{index + 1}Position",
                    " ".join(str(value) for value in position),
                    0x0061,
                    "Image",
                )
            )
        if age is not None:
            fields.append(PanasonicMakerNoteField(f"RecognizedFace{index + 1}Age", age, 0x0061))
    return tuple(fields)


def _payload_string(payload: bytes, offset: int, length: int) -> str | None:
    if offset + length > len(payload):
        return None
    return payload[offset : offset + length].rstrip(b"\x00 ").decode("utf-8", errors="replace")


def _payload_u16_list(payload: bytes, offset: int, count: int) -> list[int] | None:
    byte_count = count * 2
    if offset + byte_count > len(payload):
        return None
    return [
        int.from_bytes(payload[index : index + 2], "little")
        for index in range(offset, offset + byte_count, 2)
    ]


def _signed_16(value: int) -> int:
    return value - 0x10000 if value >= 0x8000 else value


def _signed_8(value: int) -> int:
    return value - 0x100 if value >= 0x80 else value


def _number_value(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _lens_type_model(value: int) -> str:
    swapped = f"{value:04x}"
    return f"{int(swapped[2:4], 16)} {int(swapped[0:2], 16)}"


def _joined_values(values: Sequence[int | Fraction | None]) -> str:
    return " ".join("" if value is None else str(_scalar_number(value)) for value in values)


def _scalar_number(value: int | Fraction) -> int | float:
    if isinstance(value, int):
        return value
    if value.denominator == 1:
        return value.numerator
    return float(value)


def _string_value(value: PanasonicRawValue) -> str:
    if isinstance(value, bytes):
        return value.rstrip(b"\x00").decode("utf-8", errors="replace")
    return "" if value is None else str(value)


def _lens_firmware_version(value: PanasonicRawValue) -> str | int | float:
    if isinstance(value, bytes):
        return ".".join(str(part) for part in value)
    if isinstance(value, list):
        return ".".join(str(part) for part in value)
    return _package_or_raw("LensFirmwareVersion", value, _runtime_context(None, None))


def _af_point_position(values: Sequence[int | Fraction | None]) -> str:
    if len(values) < 2 or values[0] is None or values[1] is None:
        return "n/a"
    x_position = values[0]
    y_position = values[1]
    if x_position == 16777216 and y_position == 16777216:
        return "none"
    if float(x_position) >= 4194303.9:
        return "n/a"
    return f"{float(x_position):.2g} {float(y_position):.2g}"


def _af_area_size(values: Sequence[int | Fraction | None]) -> str:
    if len(values) < 2 or values[0] is None or values[1] is None:
        return "n/a"
    if float(values[0]) >= 4194303.9:
        return "n/a"
    return " ".join(str(_scalar_number(value)) for value in values if value is not None)


def _print_parameter(value: int) -> str:
    if value == 0:
        return "Normal"
    if value in {1, 2}:
        return f"+{value}"
    if value in {65534, 65535}:
        return f"-{65536 - value}"
    return str(value)


def _time_since_power_on(raw_centiseconds: int) -> str:
    seconds = raw_centiseconds / 100
    days = int(seconds // (24 * 3600))
    seconds -= days * 24 * 3600
    hours = int(seconds // 3600)
    seconds -= hours * 3600
    minutes = int(seconds // 60)
    seconds -= minutes * 60
    day_prefix = f"{days} days " if days else ""
    return f"{day_prefix}{hours:02d}:{minutes:02d}:{seconds:05.2f}"
