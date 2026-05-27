"""Source-backed scalar maker-note PrintConv expression adapters."""

from __future__ import annotations

import re


def maker_note_scalar_print_conversion_adapter_supported(expression: str) -> bool:
    return (
        expression.strip()
        in {
            "$val =~ tr/ /./; $val",
            "$val=~tr/ /./;$val",
            "$val=~tr/ /./; $val",
            "$val=~tr/ /x/; $val",
            "$val =~ tr/ /x/; $val",
            "$val=~tr/ /:/; $val",
            "$val =~ tr/ /:/; $val",
            '$val=~s/ / x /;"$val um"',
            '$val =~ s/ / x /;"$val um"',
            "$_=$val;s/^(\\d{2})/$1\\./;s/^0//;$_",
            "$_=$val;s/^0 //;s/^1 (\\d+)/Hi $1/;$_",
            "$_=$val;s/(\\d+)(\\d{4})/$1-$2/;$_",
            "$_=$val,s/(\\d+)(\\d{4})/$1-$2/,$_",
            '$val =~ tr/012 /RGB/d; join " ", $val =~ /....../g',
            'unpack "H*", pack "C*", split " ", $val',
            "$val and $val =~ s/^(\\d)/\\+$1/; $val",
            '"$val C"',
            '"$val m"',
            '"$val km/h"',
            '"$val fps"',
            '"$val%"',
            '"$val K"',
            '"$val mm"',
            'sprintf("%.1f C", $val)',
            'sprintf("%.1f C",$val)',
            'sprintf("%.2f dB", $val)',
            'sprintf("%.2f V",$val)',
            'sprintf("%.1f",$val)',
            'sprintf("%.2f",$val)',
            'sprintf("%.0f",$val)',
            'sprintf("%.4d",$val)',
            'sprintf("%.3d",$val)',
            'sprintf("%3d",$val)',
            'sprintf("%+.1f",$val)',
            '$val ? sprintf("%+.1f",$val) : 0',
            '$val ? sprintf("%.1f",$val) : $val',
            '$val > 0 ? "+$val" : $val',
            '$val eq "9999:99:99 00:00:00" ? "(not set)" : $val',
            '$val=~/\\./ or $val.=".0"; $val',
            "$val =~ s/(\\d)of(\\d)/$1 of $2/; $val",
            "Image::ExifTool::DecodeBits($val, undef, 16)",
        }
        or is_canon_firmware_revision_expression(
            expression.strip(),
        )
        or is_casio_main_firmware_date_expression(
            expression.strip(),
        )
        or is_casio_type2_firmware_date_expression(
            expression.strip(),
        )
        or is_olympus_panorama_mode_expression(
            expression.strip(),
        )
        or is_panasonic_leica_internal_serial_expression(
            expression.strip(),
        )
        or is_decode_bits_print_expression(expression.strip())
        or is_nikon_lens_type_expression(expression.strip())
    )


def render_scalar_string_print_conversion(expression: str, raw_value: str) -> str | None:
    normalized = expression.strip()
    if normalized in (
        "$val =~ tr/ /./; $val",
        "$val=~tr/ /./;$val",
        "$val=~tr/ /./; $val",
    ):
        return raw_value.translate(str.maketrans(" ", "."))
    if normalized in (
        "$val=~tr/ /x/; $val",
        "$val =~ tr/ /x/; $val",
    ):
        return raw_value.translate(str.maketrans(" ", "x"))
    if normalized in (
        "$val=~tr/ /:/; $val",
        "$val =~ tr/ /:/; $val",
    ):
        return raw_value.translate(str.maketrans(" ", ":"))
    if normalized in (
        '$val=~s/ / x /;"$val um"',
        '$val =~ s/ / x /;"$val um"',
    ):
        return raw_value.replace(" ", " x ", 1) + " um"
    if normalized == "$_=$val;s/^(\\d{2})/$1\\./;s/^0//;$_":
        current = perl_substitute(raw_value, r"^(\d{2})", r"\1.", count=1)
        return perl_substitute(current, r"^0", "", count=1)
    if normalized == "$_=$val;s/^0 //;s/^1 (\\d+)/Hi $1/;$_":
        current = perl_substitute(raw_value, r"^0 ", "", count=1)
        return perl_substitute(current, r"^1 (\d+)", r"Hi \1", count=1)
    if normalized in (
        "$_=$val;s/(\\d+)(\\d{4})/$1-$2/;$_",
        "$_=$val,s/(\\d+)(\\d{4})/$1-$2/,$_",  # Canon.pm uses comma sequencing here.
    ):
        return perl_substitute(raw_value, r"(\d+)(\d{4})", r"\1-\2", count=1)
    if normalized == '$val =~ tr/012 /RGB/d; join " ", $val =~ /....../g':
        return fuji_x_trans_layout(raw_value)
    if normalized == 'unpack "H*", pack "C*", split " ", $val':
        return pack_decimal_bytes_as_hex(raw_value)
    if normalized == "$val and $val =~ s/^(\\d)/\\+$1/; $val":
        if not raw_value:
            return raw_value
        return perl_substitute(raw_value, r"^(\d)", r"+\1", count=1)
    if normalized in (
        '"$val C"',
        '"$val m"',
        '"$val km/h"',
        '"$val fps"',
        '"$val%"',
        '"$val K"',
        '"$val mm"',
    ):
        return append_literal_unit(normalized, raw_value)
    if normalized == 'sprintf("%.1f C", $val)':
        return format_numeric_print_value(raw_value, "%.1f C")
    if normalized == 'sprintf("%.1f C",$val)':
        return format_numeric_print_value(raw_value, "%.1f C")
    if normalized == 'sprintf("%.2f dB", $val)':
        return format_numeric_print_value(raw_value, "%.2f dB")
    if normalized == 'sprintf("%.2f V",$val)':
        return format_numeric_print_value(raw_value, "%.2f V")
    if normalized == 'sprintf("%.1f",$val)':
        return format_numeric_print_value(raw_value, "%.1f")
    if normalized == 'sprintf("%.2f",$val)':
        return format_numeric_print_value(raw_value, "%.2f")
    if normalized == 'sprintf("%.0f",$val)':
        return format_numeric_print_value(raw_value, "%.0f")
    if normalized == 'sprintf("%.4d",$val)':
        return format_integer_print_value(raw_value, "%04d")
    if normalized == 'sprintf("%.3d",$val)':
        return format_integer_print_value(raw_value, "%03d")
    if normalized == 'sprintf("%3d",$val)':
        return format_integer_print_value(raw_value, "%3d")
    if normalized == 'sprintf("%+.1f",$val)':
        return format_numeric_print_value(raw_value, "%+.1f")
    if normalized == '$val ? sprintf("%+.1f",$val) : 0':
        if not perl_truthy(raw_value):
            return "0"
        return format_numeric_print_value(raw_value, "%+.1f")
    if normalized == '$val ? sprintf("%.1f",$val) : $val':
        if not perl_truthy(raw_value):
            return raw_value
        return format_numeric_print_value(raw_value, "%.1f")
    if normalized == '$val > 0 ? "+$val" : $val':
        value = parse_float(raw_value)
        if value is None:
            return None
        if value > 0:
            return "+" + raw_value
        return raw_value
    if normalized == '$val eq "9999:99:99 00:00:00" ? "(not set)" : $val':
        if raw_value == "9999:99:99 00:00:00":
            return "(not set)"
        return raw_value
    if normalized == '$val=~/\\./ or $val.=".0"; $val':
        if "." in raw_value:
            return raw_value
        return raw_value + ".0"
    if normalized == "$val =~ s/(\\d)of(\\d)/$1 of $2/; $val":
        return perl_substitute(raw_value, r"(\d)of(\d)", r"\1 of \2", count=1)
    if normalized == "Image::ExifTool::DecodeBits($val, undef, 16)":
        return decode_bits(raw_value, (), bits_per_word=16)
    if is_canon_firmware_revision_expression(normalized):
        return canon_firmware_revision(raw_value)
    if is_casio_main_firmware_date_expression(normalized):
        return casio_main_firmware_date(raw_value)
    if is_casio_type2_firmware_date_expression(normalized):
        return casio_type2_firmware_date(raw_value)
    if is_olympus_panorama_mode_expression(normalized):
        return olympus_panorama_mode(raw_value)
    if is_panasonic_leica_internal_serial_expression(normalized):
        return panasonic_leica_internal_serial(raw_value)
    if is_nikon_lens_type_expression(normalized):
        return nikon_lens_type(raw_value, include_newer_bits="FT-1" in normalized)
    if is_decode_bits_print_expression(normalized):
        return decode_bits_print_expression(normalized, raw_value)
    return None


def perl_substitute(value: str, pattern: str, replacement: str, *, count: int) -> str:
    return re.sub(pattern, replacement, value, count=count)


def fuji_x_trans_layout(raw_value: str) -> str:
    translation_table: dict[str, str | int | None] = {
        "0": "R",
        "1": "G",
        "2": "B",
        " ": None,
    }
    translated = raw_value.translate(str.maketrans(translation_table))
    return " ".join(translated[index : index + 6] for index in range(0, len(translated) - 5, 6))


def pack_decimal_bytes_as_hex(raw_value: str) -> str | None:
    values: list[int] = []
    for part in raw_value.split():
        try:
            values.append(int(part) % 256)
        except ValueError:
            return None
    return "".join(f"{value:02x}" for value in values)


def append_literal_unit(expression: str, raw_value: str) -> str:
    suffix = expression.removeprefix('"$val').removesuffix('"')
    return raw_value + suffix


def format_numeric_print_value(raw_value: str, format_pattern: str) -> str | None:
    value = parse_float(raw_value)
    if value is None:
        return None
    return format_pattern % value


def format_integer_print_value(raw_value: str, format_pattern: str) -> str | None:
    value = parse_float(raw_value)
    if value is None:
        return None
    return format_pattern % int(value)


def parse_float(raw_value: str) -> float | None:
    try:
        return float(raw_value)
    except ValueError:
        return None


def parse_int(raw_value: str) -> int | None:
    value = parse_float(raw_value)
    if value is None:
        return None
    return int(value)


def perl_truthy(raw_value: str) -> bool:
    return raw_value not in ("", "0")


def is_decode_bits_print_expression(expression: str) -> bool:
    return "Image::ExifTool::DecodeBits($val," in expression and "=>" in expression


def decode_bits_print_expression(expression: str, raw_value: str) -> str | None:
    if "return 'All' if $val eq 255;" in expression and raw_value == "255":
        return "All"
    lookup = decode_bits_lookup(expression)
    if not lookup:
        return None
    return decode_bits(raw_value, lookup, bits_per_word=32)


def decode_bits_lookup(expression: str) -> tuple[tuple[int, str], ...]:
    matches = re.findall(r"^\s*(\d+)\s*=>\s*'([^']+)'", expression, flags=re.MULTILINE)
    return tuple((int(index), label) for index, label in matches)


def decode_bits(
    raw_value: str,
    lookup: tuple[tuple[int, str], ...],
    *,
    bits_per_word: int,
) -> str | None:
    values = split_integer_words(raw_value)
    if values is None:
        return None
    lookup_map = dict(lookup)
    labels: list[str] = []
    bit_offset = 0
    for value in values:
        for bit_index in range(bits_per_word):
            if value & (1 << bit_index):
                decoded_index = bit_offset + bit_index
                if lookup:
                    labels.append(lookup_map.get(decoded_index, f"[{decoded_index}]"))
                else:
                    labels.append(str(decoded_index))
        bit_offset += bits_per_word
    if not labels:
        return "(none)"
    return (", " if lookup else ",").join(labels)


def split_integer_words(raw_value: str) -> tuple[int, ...] | None:
    values: list[int] = []
    for part in raw_value.split():
        try:
            values.append(int(float(part)))
        except ValueError:
            return None
    return tuple(values)


def is_nikon_lens_type_expression(expression: str) -> bool:
    return (
        "Image::ExifTool::DecodeBits($val," in expression
        and "0 => 'MF'," in expression
        and "s/,//g; s/\\bD G\\b/G/;" in expression
        and 'put "E" at the start' in expression
        and 'put "1" at start' in expression
    )


def nikon_lens_type(raw_value: str, *, include_newer_bits: bool) -> str | None:
    try:
        value = int(float(raw_value))
    except ValueError:
        return None
    if value == 0:
        return "AF"
    lookup = (
        (0, "MF"),
        (1, "D"),
        (2, "G"),
        (3, "VR"),
        (4, "1"),
        (5, "FT-1"),
        (6, "E"),
        (7, "AF-P"),
    )
    decoded = decode_bits(raw_value, lookup if include_newer_bits else lookup[:7], bits_per_word=32)
    if decoded is None:
        return None
    current = decoded.replace(",", "")
    current = re.sub(r"\bD G\b", "G", current)
    if re.search(r" E\b", current):
        current = re.sub(r" E\b", "", current, count=1)
        current = re.sub(r"^(G )?", "E ", current, count=1)
    if " 1" in current:
        current = current.replace(" 1", "", 1)
        current = "1 " + current
    if include_newer_bits and "FT-1 " in current:
        current = current.replace("FT-1 ", "", 1)
        current += " FT-1"
    return current


def is_canon_firmware_revision_expression(expression: str) -> bool:
    return (
        'my $rev = sprintf("%.8x", $val);' in expression
        and "my %r = ( a => 'Alpha ', b => 'Beta ', '0' => '' );" in expression
        and 'return "$rel$v1.$v2 rev $r1.$r2",' in expression
    )


def canon_firmware_revision(raw_value: str) -> str | None:
    value = parse_float(raw_value)
    if value is None:
        return None
    revision = f"{int(value):08x}"
    match = re.fullmatch(r"(.)(.)(..)0?(.+)(..)", revision)
    if match is None:
        return None
    release, version_major, version_minor, revision_major, revision_minor = match.groups()
    release_text = {"a": "Alpha ", "b": "Beta ", "0": ""}.get(release, f"Unknown({release}) ")
    return f"{release_text}{version_major}.{version_minor} rev {revision_major}.{revision_minor}"


def is_casio_main_firmware_date_expression(expression: str) -> bool:
    return (
        r"if (/^(\d{2})(\d{2})\0\0(\d{2})(\d{2})\0\0(\d{2})(.{2})\0{2}$/)" in expression
        and "my $sec = $6;" in expression
        and 'return "Unknown ($_)";' in expression
    )


def is_casio_type2_firmware_date_expression(expression: str) -> bool:
    return (
        r"if (/^(\d{2})(\d{2})\0\0(\d{2})(\d{2})\0\0(\d{2})\0{4}$/)" in expression
        and 'return "$yr:$2:$3 $4:$5";' in expression
        and 'return "Unknown ($_)";' in expression
    )


def casio_main_firmware_date(raw_value: str) -> str:
    match = re.fullmatch(
        r"(\d{2})(\d{2})\x00\x00(\d{2})(\d{2})\x00\x00(\d{2})(.{2})\x00{2}",
        raw_value,
        re.DOTALL,
    )
    if match is not None:
        year, month, day, hour, minute, second = match.groups()
        year_value = int(year) + (2000 if int(year) < 70 else 1900)
        value = f"{year_value}:{month}:{day} {hour}:{minute}"
        if re.fullmatch(r"\d{2}", second):
            value += f":{second}"
        return value
    return "Unknown (" + raw_value.replace("\x00", ".").rstrip(".") + ")"


def casio_type2_firmware_date(raw_value: str) -> str:
    match = re.fullmatch(r"(\d{2})(\d{2})\x00\x00(\d{2})(\d{2})\x00\x00(\d{2})\x00{4}", raw_value)
    if match is not None:
        year, month, day, hour, minute = match.groups()
        year_value = int(year) + (2000 if int(year) < 70 else 1900)
        return f"{year_value}:{month}:{day} {hour}:{minute}"
    return "Unknown (" + raw_value.replace("\x00", ".").rstrip(".") + ")"


def is_olympus_panorama_mode_expression(expression: str) -> bool:
    return (
        "my ($a,$b) = split ' ',$val;" in expression
        and "return 'Off' unless $a;" in expression
        and "return(($a{$a} || \"Unknown ($a)\") . ', Shot ' . $b);" in expression
    )


def olympus_panorama_mode(raw_value: str) -> str:
    parts = raw_value.split()
    if not parts or parts[0] == "0":
        return "Off"
    direction = {
        "1": "Left to Right",
        "2": "Right to Left",
        "3": "Bottom to Top",
        "4": "Top to Bottom",
    }.get(parts[0], f"Unknown ({parts[0]})")
    shot = parts[1] if len(parts) > 1 else ""
    return direction + ", Shot " + shot


def is_panasonic_leica_internal_serial_expression(expression: str) -> bool:
    return (
        r"return $val unless $val=~/^(.{3})(\d{2})(\d{2})(\d{2})(\d{4})/;" in expression
        and 'return "($1) $yr:$3:$4 no. $5";' in expression
    )


def panasonic_leica_internal_serial(raw_value: str) -> str:
    match = re.match(r"(.{3})(\d{2})(\d{2})(\d{2})(\d{4})", raw_value, re.DOTALL)
    if match is None:
        return raw_value
    prefix, year, month, day, number = match.groups()
    year_value = int(year) + (2000 if int(year) < 70 else 1900)
    return f"({prefix}) {year_value}:{month}:{day} no. {number}"
