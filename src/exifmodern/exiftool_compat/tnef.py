"""TNEF compatibility adapters."""

from __future__ import annotations

from exifmodern.exiftool_compat.binary import binary_text_bytes, uint32_little_endian
from exifmodern.exiftool_compat.types import (
    ExifToolScalarReference,
    ExifToolValue,
    scalar_value,
    string_value,
)

RTF_UNCOMPRESSED_MAGIC = 0x414C454D
RTF_COMPRESSED_MAGIC = 0x75465A4C
RTF_DICTIONARY = (
    "{\\rtf1\\ansi\\mac\\deff0\\deftab720{\\fonttbl;}"
    "{\\f0\\fnil \\froman \\fswiss \\fmodern "
    "\\fscript \\fdecor MS Sans SerifSymbolArialTimes"
    " New RomanCourier{\\colortbl\\red0\\green0\\blue0"
    "\r\n"
    "\\par \\pard\\plain\\f0\\fs20\\b\\i\\u\\tab\\tx"
)


def decompress_rtf(values: list[ExifToolValue]) -> ExifToolValue:
    if len(values) != 2:
        return ExifToolScalarReference("")
    compressed = string_value(scalar_value(values[1], "TNEF compressed RTF payload"))
    return ExifToolScalarReference(decompressed_rtf(compressed))


def decompressed_rtf(compressed: str) -> str:
    if len(compressed) <= 16:
        return ""
    data = binary_text_bytes(compressed)
    compression = uint32_little_endian(data, 8)
    if compression == RTF_UNCOMPRESSED_MAGIC:
        return compressed[16:]
    if compression != RTF_COMPRESSED_MAGIC:
        return ""
    dictionary = list(RTF_DICTIONARY)
    cursor = 16
    dictionary_cursor = len(dictionary)
    rendered: list[str] = []
    while cursor < len(data):
        control = data[cursor]
        cursor += 1
        bit_index = 0
        while bit_index < 8 and cursor < len(data):
            if control & (1 << bit_index):
                if cursor + 2 > len(data):
                    return "".join(rendered)
                reference = (data[cursor] << 8) | data[cursor + 1]
                cursor += 2
                offset = reference >> 4
                length = (reference & 0x0F) + 2
                if offset == dictionary_cursor % 4096 or offset % 4096 >= len(dictionary):
                    return "".join(rendered)
                for _ in range(length):
                    character = dictionary[offset % 4096]
                    dictionary_set(dictionary, dictionary_cursor % 4096, character)
                    dictionary_cursor += 1
                    rendered.append(character)
                    offset += 1
            else:
                character = chr(data[cursor])
                cursor += 1
                dictionary_set(dictionary, dictionary_cursor % 4096, character)
                dictionary_cursor += 1
                rendered.append(character)
            bit_index += 1
    return "".join(rendered)


def dictionary_set(dictionary: list[str], index: int, character: str) -> None:
    if index < len(dictionary):
        dictionary[index] = character
        return
    while len(dictionary) < index:
        dictionary.append("\0")
    dictionary.append(character)
