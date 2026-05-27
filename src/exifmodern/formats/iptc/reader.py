"""IPTC dataset reader for currently proven ApplicationRecord tags."""

from __future__ import annotations

from collections.abc import Sequence

from exifmodern.json_types import JsonArray, JsonObject, JsonValue

type IptcTagName = str
type IptcDatasetId = int
type IptcRecordId = int
type IptcTagValue = str | int | list[str]

IPTC_ENVELOPE_RECORD = 1
IPTC_APPLICATION_RECORD = 2

IPTC_ENVELOPE_TAGS: dict[IptcDatasetId, IptcTagName] = {
    120: "ARMIdentifier",
    122: "ARMVersion",
}

IPTC_APPLICATION_TAGS: dict[IptcDatasetId, IptcTagName] = {
    0: "ApplicationRecordVersion",
    5: "ObjectName",
    7: "EditStatus",
    10: "Urgency",
    15: "Category",
    20: "SupplementalCategories",
    25: "Keywords",
    40: "SpecialInstructions",
    55: "DateCreated",
    80: "By-line",
    85: "By-lineTitle",
    90: "City",
    95: "Province-State",
    101: "Country-PrimaryLocationName",
    103: "OriginalTransmissionReference",
    105: "Headline",
    110: "Credit",
    115: "Source",
    116: "CopyrightNotice",
    120: "Caption-Abstract",
    122: "Writer-Editor",
    75: "ObjectCycle",
    151: "AudioSamplingRate",
    152: "AudioSamplingResolution",
    153: "AudioDuration",
    154: "AudioOutcue",
    200: "ObjectPreviewFileFormat",
    201: "ObjectPreviewFileVersion",
    202: "ObjectPreviewData",
    230: "DocumentNotes",
}

IPTC_LIST_TAGS = {
    "SupplementalCategories",
    "Keywords",
    "By-line",
    "By-lineTitle",
    "Writer-Editor",
}


def parse_iptc_application_record(payload: bytes) -> JsonObject:
    collected: dict[IptcTagName, list[IptcTagValue]] = {}
    position = 0
    while position + 5 <= len(payload):
        if payload[position] != 0x1C:
            position += 1
            continue
        record = payload[position + 1]
        dataset = payload[position + 2]
        size = int.from_bytes(payload[position + 3 : position + 5], "big")
        value_offset = position + 5
        next_position = value_offset + size
        if next_position > len(payload):
            break
        tag_name = iptc_tag_name(record, dataset)
        if tag_name is not None:
            collected.setdefault(tag_name, []).append(
                iptc_application_value(tag_name, payload[value_offset:next_position])
            )
        position = next_position
    return flatten_iptc_values(collected)


def iptc_tag_name(record_id: IptcRecordId, dataset_id: IptcDatasetId) -> IptcTagName | None:
    if record_id == IPTC_ENVELOPE_RECORD:
        return IPTC_ENVELOPE_TAGS.get(dataset_id)
    if record_id == IPTC_APPLICATION_RECORD:
        return IPTC_APPLICATION_TAGS.get(dataset_id)
    return None


def iptc_application_value(tag_name: IptcTagName, value: bytes) -> IptcTagValue:
    if len(value) == 2:
        numeric_value = int.from_bytes(value, "big")
        if tag_name in {
            "ApplicationRecordVersion",
            "ARMIdentifier",
            "ARMVersion",
            "ObjectPreviewFileVersion",
        }:
            return numeric_value
        if tag_name == "ObjectPreviewFileFormat":
            return iptc_file_format(numeric_value)
    if tag_name == "ObjectPreviewData":
        return f"(Binary data {len(value)} bytes)"
    text = value.decode("latin-1", errors="replace")
    if tag_name == "DateCreated":
        return iptc_date(text)
    if tag_name == "Urgency":
        return iptc_urgency(text)
    if tag_name == "ObjectCycle":
        return iptc_object_cycle(text)
    if tag_name == "ObjectPreviewFileFormat":
        return f"Unknown ({text})"
    if tag_name == "Category" and text.isdecimal():
        return int(text)
    return text


def iptc_date(text: str) -> str:
    if len(text) == 8 and text.isdecimal():
        return f"{text[0:4]}:{text[4:6]}:{text[6:8]}"
    return text


def iptc_urgency(text: str) -> str | int:
    if not text.isdecimal():
        return text
    value = int(text)
    return {
        0: "0 (reserved)",
        1: "1 (most urgent)",
        5: "5 (normal urgency)",
        8: "8 (least urgent)",
        9: "9 (user-defined priority)",
    }.get(value, value)


def iptc_object_cycle(text: str) -> str:
    return {
        "a": "Morning",
        "p": "Evening",
        "b": "Both Morning and Evening",
    }.get(text, f"Unknown ({text})")


def iptc_file_format(value: int) -> str:
    return {
        0: "No ObjectData",
        1: "IPTC-NAA Digital Newsphoto Parameter Record",
        2: "IPTC7901 Recommended Message Format",
        3: "Tagged Image File Format (Adobe/Aldus Image data)",
        4: "Illustrator (Adobe Graphics data)",
        5: "AppleSingle (Apple Computer Inc)",
        6: "NAA 89-3 (ANPA 1312)",
        7: "MacBinary II",
        8: "IPTC Unstructured Character Oriented File Format (UCOFF)",
        9: "United Press International ANPA 1312 variant",
        10: "United Press International Down-Load Message",
        11: "JPEG File Interchange (JFIF)",
        12: "Photo-CD Image-Pac (Eastman Kodak)",
        13: "Bit Mapped Graphics File [.BMP] (Microsoft)",
        14: "Digital Audio File [.WAV] (Microsoft & Creative Labs)",
        15: "Audio plus Moving Video [.AVI] (Microsoft)",
        16: "PC DOS/Windows Executable Files [.COM][.EXE]",
        17: "Compressed Binary File [.ZIP] (PKWare Inc)",
        18: "Audio Interchange File Format AIFF (Apple Computer)",
        19: "RIFF Wave (Microsoft Corporation)",
        20: "Freehand (Macromedia/Aldus)",
        21: "Hypertext Markup Language [.HTML] (The Internet Society)",
        22: "MPEG 2 Audio Layer 2 (Musicom), ISO/IEC",
        23: "MPEG 2 Audio Layer 3, ISO/IEC",
        24: "Portable Document File [.PDF] Adobe",
        25: "News Industry Text Format (NITF)",
        26: "Tape Archive [.TAR]",
        27: "Tidningarnas Telegrambyra NITF version (TTNITF DTD)",
        28: "Ritzaus Bureau NITF version (RBNITF DTD)",
        29: "Corel Draw [.CDR]",
    }.get(value, f"Unknown (Custom Field {value - 199:02d})")


def flatten_iptc_values(collected: dict[IptcTagName, list[IptcTagValue]]) -> JsonObject:
    values: JsonObject = {}
    for tag_name, tag_values in collected.items():
        if tag_name in IPTC_LIST_TAGS and len(tag_values) > 1:
            values[tag_name] = iptc_values_to_json_array(tag_values)
        else:
            values[tag_name] = iptc_value_to_json(tag_values[0])
    return values


def iptc_value_to_json(value: IptcTagValue) -> JsonValue:
    if isinstance(value, list):
        return iptc_values_to_json_array(value)
    return value


def iptc_values_to_json_array(values: Sequence[IptcTagValue]) -> JsonArray:
    array: JsonArray = []
    for value in values:
        if isinstance(value, list):
            array.extend(iptc_values_to_json_array(value))
        else:
            array.append(value)
    return array
