"""Literal and interpolation parsing helpers for safe-expression compilation."""

from __future__ import annotations

from lark import Token

from exifmodern.safe_expression.ast import (
    CurrentItemTransliterationStatement,
    InputSubstitutionStatement,
    LocalArrayName,
    RegexLiteral,
    RuntimeContextKey,
    RuntimeContextPath,
    SafeInputName,
    StaticRuntimeContextKey,
    StringLiteral,
    StringTemplateCurrentItem,
    StringTemplateLiteral,
    StringTemplateLocalArrayValue,
    StringTemplateLocalScalarContextValue,
    StringTemplateLocalScalarValue,
    StringTemplateSegment,
    StringTemplateValue,
    ValInterpolatedString,
)
from exifmodern.safe_expression.bytecode import VmScalar
from exifmodern.safe_expression.errors import SafeExpressionCompileError


def number_literal(value: Token) -> int | float:
    text = str(value)
    if "." in text or "e" in text or "E" in text:
        return float(text)
    return int(text)


def string_ast_literal(value: Token) -> StringLiteral | ValInterpolatedString:
    decoded = decoded_string_literal(value)
    if "$" not in decoded and "@" not in decoded:
        return StringLiteral(decoded)
    return ValInterpolatedString(interpolation_segments(decoded))


def decoded_string_literal(value: Token) -> str:
    text = str(value)
    if len(text) < 2:
        raise SafeExpressionCompileError("Malformed string literal.")
    if text[0] == "'":
        return decoded_single_quoted_string_literal(text)
    return bytes(text[1:-1], "utf-8").decode("unicode_escape")


def decoded_single_quoted_string_literal(text: str) -> str:
    decoded = ""
    index = 1
    while index < len(text) - 1:
        character = text[index]
        if character != "\\":
            decoded += character
            index += 1
            continue
        if index + 1 >= len(text) - 1:
            decoded += "\\"
            index += 1
            continue
        escaped = text[index + 1]
        if escaped in {"\\", "'"}:
            decoded += escaped
        else:
            decoded += "\\" + escaped
        index += 2
    return decoded


def regex_pattern_literal(value: Token) -> RegexLiteral:
    text = str(value)
    if len(text) < 2 or text[0] != "/":
        raise SafeExpressionCompileError("Malformed regex literal.")
    slash_index = text.rfind("/")
    if slash_index == 0:
        raise SafeExpressionCompileError("Malformed regex literal.")
    flags = text[slash_index + 1 :]
    unsupported_flags = set(flags) - {"i", "s"}
    if unsupported_flags:
        raise SafeExpressionCompileError(f"Unsupported regex flags: {flags}")
    return RegexLiteral(
        pattern=text[1:slash_index],
        ignore_case="i" in flags,
        dot_matches_newline="s" in flags,
    )


def substitution_statement(value: Token) -> InputSubstitutionStatement:
    text = str(value)
    if not text.startswith("s/"):
        raise SafeExpressionCompileError("Malformed substitution statement.")
    pattern_end = substitution_delimiter_index(text, 2)
    replacement_end = substitution_delimiter_index(text, pattern_end + 1)
    flags = text[replacement_end + 1 :]
    unsupported_flags = set(flags) - {"g", "i", "s"}
    if unsupported_flags:
        raise SafeExpressionCompileError(f"Unsupported substitution flags: {flags}")
    return InputSubstitutionStatement(
        pattern=text[2:pattern_end],
        replacement=perl_replacement_text(text[pattern_end + 1 : replacement_end]),
        global_substitution="g" in flags,
        ignore_case="i" in flags,
        dot_matches_newline="s" in flags,
    )


def transliteration_statement(value: Token) -> CurrentItemTransliterationStatement:
    text = str(value)
    if not text.startswith("tr/"):
        raise SafeExpressionCompileError("Malformed transliteration statement.")
    source_end = substitution_delimiter_index(text, 3)
    replacement_end = substitution_delimiter_index(text, source_end + 1)
    flags = text[replacement_end + 1 :]
    if flags:
        raise SafeExpressionCompileError(f"Unsupported transliteration flags: {flags}")
    source_chars = expanded_transliteration_chars(text[3:source_end])
    replacement_chars = expanded_transliteration_chars(text[source_end + 1 : replacement_end])
    if not source_chars or not replacement_chars:
        raise SafeExpressionCompileError("Transliteration requires source and replacement chars.")
    return CurrentItemTransliterationStatement(
        source_chars=source_chars,
        replacement_chars=replacement_chars,
    )


def expanded_transliteration_chars(value: str) -> str:
    expanded: list[str] = []
    index = 0
    while index < len(value):
        if index + 2 < len(value) and value[index + 1] == "-":
            start = ord(value[index])
            end = ord(value[index + 2])
            if start <= end:
                expanded.extend(chr(codepoint) for codepoint in range(start, end + 1))
                index += 3
                continue
        expanded.append(value[index])
        index += 1
    return "".join(expanded)


def substitution_delimiter_index(text: str, start: int) -> int:
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == "/":
            return index
    raise SafeExpressionCompileError("Malformed substitution statement.")


def perl_replacement_text(text: str) -> str:
    for index in range(1, 10):
        text = text.replace(f"${index}", rf"\{index}")
    return text


def qw_list_values(value: Token) -> list[VmScalar]:
    text = str(value)
    if not text.startswith("qw(") or not text.endswith(")"):
        raise SafeExpressionCompileError("Malformed qw list literal.")
    return [part for part in text[3:-1].split() if part]


def interpolation_segments(template: str) -> list[StringTemplateSegment]:
    segments: list[StringTemplateSegment] = []
    index = 0
    while index < len(template):
        if template[index] not in {"$", "@"}:
            literal_start = index
            while index < len(template) and template[index] not in {"$", "@"}:
                index += 1
            segments.append(StringTemplateLiteral(template[literal_start:index]))
            continue
        if (
            template[index] == "@"
            and index + 1 < len(template)
            and local_name_start(template[index + 1])
        ):
            local_value, index = local_array_interpolation_value_at(template, index)
            if local_value is not None:
                segments.append(local_value)
                continue
        if template[index] == "@":
            segments.append(StringTemplateLiteral("@"))
            index += 1
            continue
        scalar_value, index = interpolation_value_at(template, index)
        segments.append(scalar_value)
    return segments


def interpolation_value_at(template: str, index: int) -> tuple[StringTemplateSegment, int]:
    if template.startswith("$_", index):
        next_index = index + len("$_")
        if next_index < len(template) and invalid_interpolation_suffix(template[next_index]):
            raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
        return StringTemplateCurrentItem(), next_index
    local_context_value = local_scalar_context_interpolation_value_at(template, index)
    if local_context_value is not None:
        return local_context_value
    if template.startswith("$val", index):
        return indexed_interpolation_value(template, index, "$val")
    if template.startswith("$prt", index):
        return indexed_interpolation_value(template, index, "$prt")
    local_value = local_array_indexed_interpolation_value_at(template, index)
    if local_value is not None:
        return local_value
    local_scalar_value = local_scalar_interpolation_value_at(template, index)
    if local_scalar_value is not None:
        return local_scalar_value
    raise SafeExpressionCompileError("Unsupported Perl string interpolation.")


def indexed_interpolation_value(
    template: str,
    index: int,
    input_name: SafeInputName,
) -> tuple[StringTemplateValue, int]:
    next_index = index + len(input_name)
    if next_index >= len(template):
        return StringTemplateValue(input_name, None), next_index
    if template[next_index] == "[":
        close_index = template.find("]", next_index + 1)
        if close_index < 0:
            raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
        index_text = template[next_index + 1 : close_index]
        if not index_text.isdigit():
            raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
        return StringTemplateValue(input_name, int(index_text)), close_index + 1
    if invalid_interpolation_suffix(template[next_index]):
        raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
    return StringTemplateValue(input_name, None), next_index


def local_array_interpolation_value_at(
    template: str,
    index: int,
) -> tuple[StringTemplateLocalArrayValue | None, int]:
    next_index = index + 1
    name, next_index = local_name_at(template, next_index)
    if next_index < len(template) and invalid_interpolation_suffix(template[next_index]):
        return None, index
    return StringTemplateLocalArrayValue(name, None), next_index


def local_array_indexed_interpolation_value_at(
    template: str,
    index: int,
) -> tuple[StringTemplateLocalArrayValue, int] | None:
    if index + 1 >= len(template) or not local_name_start(template[index + 1]):
        return None
    name, next_index = local_name_at(template, index + 1)
    if next_index >= len(template) or template[next_index] != "[":
        return None
    close_index = template.find("]", next_index + 1)
    if close_index < 0:
        raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
    index_text = template[next_index + 1 : close_index]
    if not index_text.isdigit():
        raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
    return StringTemplateLocalArrayValue(name, int(index_text)), close_index + 1


def local_scalar_interpolation_value_at(
    template: str,
    index: int,
) -> tuple[StringTemplateLocalScalarValue, int] | None:
    if index + 1 >= len(template) or not local_name_start(template[index + 1]):
        return None
    name, next_index = local_name_at(template, index + 1)
    if next_index < len(template) and invalid_interpolation_suffix(template[next_index]):
        raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
    return StringTemplateLocalScalarValue(name), next_index


def local_scalar_context_interpolation_value_at(
    template: str,
    index: int,
) -> tuple[StringTemplateLocalScalarContextValue, int] | None:
    if not template.startswith("$$", index):
        return None
    name, next_index = local_name_at(template, index + 2)
    keys: list[RuntimeContextKey] = []
    while next_index < len(template) and template[next_index] == "{":
        close_index = template.find("}", next_index + 1)
        if close_index < 0:
            raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
        key = template[next_index + 1 : close_index]
        if not key or not all(context_key_character(character) for character in key):
            raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
        keys.append(StaticRuntimeContextKey(key))
        next_index = close_index + 1
    if not keys:
        raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
    if next_index < len(template) and invalid_interpolation_suffix(template[next_index]):
        raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
    return StringTemplateLocalScalarContextValue(
        name=name,
        path=RuntimeContextPath(keys),
    ), next_index


def local_name_at(template: str, index: int) -> tuple[LocalArrayName, int]:
    if index >= len(template) or not local_name_start(template[index]):
        raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
    name_start = index
    index += 1
    while index < len(template) and local_name_part(template[index]):
        index += 1
    return template[name_start:index], index


def local_name_start(character: str) -> bool:
    return character == "_" or character.isalpha()


def local_name_part(character: str) -> bool:
    return character == "_" or character.isalnum()


def context_key_character(character: str) -> bool:
    return character == "_" or character == ":" or character.isalnum()


def validate_val_interpolation_template(template: str) -> None:
    index = 0
    while index < len(template):
        if template[index] != "$":
            index += 1
            continue
        if not template.startswith("$val", index):
            raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
        next_index = index + len("$val")
        if next_index < len(template) and invalid_interpolation_suffix(template[next_index]):
            raise SafeExpressionCompileError("Unsupported Perl string interpolation.")
        index = next_index


def invalid_interpolation_suffix(character: str) -> bool:
    return character == "[" or character == "_" or character.isalnum()
