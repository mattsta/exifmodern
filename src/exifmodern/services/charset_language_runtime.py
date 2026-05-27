"""Runtime charset and language resolution backed by canonical package data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.services.charset_language import (
    CharsetLanguageRepository,
    SourceCodepoints,
    load_charset_language_repository,
)
from exifmodern.services.charset_tables import (
    CharsetCodepointResult,
    CharsetDecodeRequest,
    CharsetEncodeRequest,
    CharsetGate,
    CharsetRoute,
    CharsetSpec,
    charset_spec,
    decode_source_codepoints,
    encode_unicode_codepoint,
    plan_decode_boundary,
    plan_encode_boundary,
)

type CharsetRuntimeStatus = Literal[
    "resolved",
    "resolved_with_replacement",
    "invalid_byte_order",
    "invalid_source_codepoints",
    "invalid_unicode_codepoint",
    "malformed_fixed_width",
    "malformed_utf8",
    "missing_charset_table",
    "unencodable_codepoint",
    "unsupported_charset",
    "unsupported_inverse",
]
type LanguageRuntimeStatus = Literal[
    "resolved",
    "missing_print_conversion",
    "missing_translation",
    "unsupported_language",
]

CHARSET_LOAD_SOURCE_ID = "charset.load"
CHARSET_DECOMPOSE_SOURCE_ID = "charset.decompose"
CHARSET_RECOMPOSE_SOURCE_ID = "charset.recompose"
CHARSET_RECOMPOSE_REPLACEMENT_SOURCE_ID = "charset.recompose.replacement"
LANGUAGE_LOAD_SOURCE_ID = "language.load"
LANGUAGE_DESCRIPTION_SOURCE_ID = "language.description"
LANGUAGE_ALT_DESCRIPTION_SOURCE_ID = "language.description.lang_alt"
LANGUAGE_PRINT_CONV_SOURCE_ID = "language.print_conv"
LANGUAGE_PRINT_CONV_BITMASK_SOURCE_ID = "language.print_conv.bitmask"


@dataclass(frozen=True)
class CharsetRuntimeResult:
    status: CharsetRuntimeStatus
    requested_charset: str
    charset_name: str | None
    source_codepoints: SourceCodepoints
    unicode_codepoints: tuple[int, ...]
    source_reference_ids: tuple[str, ...]
    gate: CharsetGate | None = None
    encoded_payload: bytes = b""
    replacement_count: int = 0
    replacement_codepoints: tuple[int, ...] = ()
    reason: str = ""

    @property
    def resolved(self) -> bool:
        return self.status in ("resolved", "resolved_with_replacement")


@dataclass(frozen=True)
class LanguageRuntimeRequest:
    language: str
    tag_name: str
    printed_value: str = ""
    tag_language_code: str = ""
    split_bitmask_print_value: bool = False


@dataclass(frozen=True)
class LanguageRuntimeResult:
    status: LanguageRuntimeStatus
    language: str
    tag_name: str
    description: str | None
    print_conversion: str | None
    source_reference_ids: tuple[str, ...]
    source_path: str | None = None
    printed_value: str = ""
    tag_language_code: str = ""
    used_lang_alt_base: bool = False
    split_bitmask_print_value: bool = False
    reason: str = ""

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"


@dataclass(frozen=True)
class CharsetLanguageRuntimeService:
    repository: CharsetLanguageRepository

    def decode_codepoints(
        self,
        charset: str,
        source_codepoints: SourceCodepoints,
    ) -> CharsetRuntimeResult:
        return resolve_charset_decode_runtime(self.repository, charset, source_codepoints)

    def decode_bytes(
        self,
        charset: str,
        payload: bytes,
        byte_order: Literal["II", "MM", "Unknown"] | None = None,
    ) -> CharsetRuntimeResult:
        return resolve_charset_payload_decode_runtime(
            self.repository,
            charset,
            payload,
            byte_order,
        )

    def encode_codepoint(
        self,
        charset: str,
        unicode_codepoint: int,
    ) -> CharsetRuntimeResult:
        return resolve_charset_encode_runtime(self.repository, charset, unicode_codepoint)

    def encode_codepoints(
        self,
        charset: str,
        unicode_codepoints: tuple[int, ...],
        byte_order: Literal["II", "MM"] | None = None,
    ) -> CharsetRuntimeResult:
        return resolve_charset_payload_encode_runtime(
            self.repository,
            charset,
            unicode_codepoints,
            byte_order,
        )

    def encode_codepoints_lossy(
        self,
        charset: str,
        unicode_codepoints: tuple[int, ...],
        byte_order: Literal["II", "MM"] | None = None,
    ) -> CharsetRuntimeResult:
        return resolve_charset_payload_encode_runtime(
            self.repository,
            charset,
            unicode_codepoints,
            byte_order,
            replace_unencodable=True,
        )

    def translate(self, request: LanguageRuntimeRequest) -> LanguageRuntimeResult:
        return resolve_language_runtime(self.repository, request)


def load_charset_language_runtime_service(package_path: Path) -> CharsetLanguageRuntimeService:
    return CharsetLanguageRuntimeService(load_charset_language_repository(package_path))


def resolve_charset_decode_runtime(
    repository: CharsetLanguageRepository,
    charset: str,
    source_codepoints: SourceCodepoints,
) -> CharsetRuntimeResult:
    result = decode_source_codepoints(repository, charset, source_codepoints)
    return charset_runtime_result(result, _charset_decode_source_ids(result))


def resolve_charset_encode_runtime(
    repository: CharsetLanguageRepository,
    charset: str,
    unicode_codepoint: int,
) -> CharsetRuntimeResult:
    result = encode_unicode_codepoint(repository, charset, unicode_codepoint)
    return charset_runtime_result(result, _charset_encode_source_ids(result))


def resolve_charset_payload_decode_runtime(
    repository: CharsetLanguageRepository,
    charset: str,
    payload: bytes,
    byte_order: Literal["II", "MM", "Unknown"] | None = None,
) -> CharsetRuntimeResult:
    plan = plan_decode_boundary(CharsetDecodeRequest(charset, payload, byte_order), repository)
    spec = None if plan.charset_name is None else charset_spec(plan.charset_name)
    if plan.gate is not None or spec is None:
        return charset_runtime_plan_result(
            charset,
            spec,
            (),
            (),
            plan.gate,
            _charset_source_ids_for_name(plan.charset_name, CHARSET_DECOMPOSE_SOURCE_ID),
        )
    result = _decode_payload_with_spec(repository, spec, payload, byte_order)
    if result.gate is not None:
        return charset_runtime_result(result, _charset_decode_source_ids(result))
    return charset_runtime_result(result, _charset_decode_source_ids(result))


def resolve_charset_payload_encode_runtime(
    repository: CharsetLanguageRepository,
    charset: str,
    unicode_codepoints: tuple[int, ...],
    byte_order: Literal["II", "MM"] | None = None,
    replace_unencodable: bool = False,
) -> CharsetRuntimeResult:
    plan = plan_encode_boundary(
        CharsetEncodeRequest(charset, unicode_codepoints, byte_order),
        repository,
    )
    spec = None if plan.charset_name is None else charset_spec(plan.charset_name)
    if plan.gate is not None or spec is None:
        return charset_runtime_plan_result(
            charset,
            spec,
            (),
            unicode_codepoints,
            plan.gate,
            _charset_source_ids_for_name(plan.charset_name, CHARSET_RECOMPOSE_SOURCE_ID),
        )
    encoded = _encode_payload_with_spec(
        repository,
        spec,
        unicode_codepoints,
        byte_order or "II",
        replace_unencodable,
    )
    if encoded.gate is not None:
        return charset_runtime_result(encoded, _charset_encode_source_ids(encoded))
    replacement_codepoints = _replacement_codepoints(encoded, unicode_codepoints)
    source_reference_ids = _charset_encode_source_ids(encoded)
    if replacement_codepoints:
        source_reference_ids = (*source_reference_ids, CHARSET_RECOMPOSE_REPLACEMENT_SOURCE_ID)
    return charset_runtime_result(
        encoded,
        source_reference_ids,
        encoded_payload=_payload_bytes(encoded.source_codepoints),
        replacement_codepoints=replacement_codepoints,
    )


def resolve_language_runtime(
    repository: CharsetLanguageRepository,
    request: LanguageRuntimeRequest,
) -> LanguageRuntimeResult:
    language = repository.language(request.language)
    if language is None:
        return language_runtime_result(
            request,
            "unsupported_language",
            None,
            None,
            None,
            False,
            f"Language {request.language!r} is not present in the charset/language package.",
        )
    description_lookup = language.description_lookup(
        request.tag_name,
        request.tag_language_code,
    )
    description = description_lookup.description
    print_conversion = (
        None
        if not request.printed_value
        else language.print_conversion_for(
            request.tag_name,
            request.printed_value,
            request.split_bitmask_print_value,
        )
    )
    if description is None and not request.printed_value:
        return language_runtime_result(
            request,
            "missing_translation",
            None,
            None,
            language.source_path,
            description_lookup.used_lang_alt_base,
            f"No localized Description exists for tag {request.tag_name!r}.",
        )
    if request.printed_value and print_conversion is None:
        return language_runtime_result(
            request,
            "missing_print_conversion",
            description,
            None,
            language.source_path,
            description_lookup.used_lang_alt_base,
            (
                f"No localized PrintConv exists for tag {request.tag_name!r} "
                f"value {request.printed_value!r}."
            ),
        )
    return language_runtime_result(
        request,
        "resolved",
        description,
        print_conversion,
        language.source_path,
        description_lookup.used_lang_alt_base,
    )


def charset_runtime_result(
    result: CharsetCodepointResult,
    source_reference_ids: tuple[str, ...],
    encoded_payload: bytes = b"",
    replacement_codepoints: tuple[int, ...] = (),
) -> CharsetRuntimeResult:
    return CharsetRuntimeResult(
        status=(
            "resolved_with_replacement"
            if result.gate is None and replacement_codepoints
            else _charset_runtime_status(result)
        ),
        requested_charset=result.requested_charset,
        charset_name=result.charset_name,
        source_codepoints=result.source_codepoints,
        unicode_codepoints=result.unicode_codepoints,
        gate=result.gate,
        encoded_payload=encoded_payload,
        replacement_count=len(replacement_codepoints),
        replacement_codepoints=replacement_codepoints,
        reason="" if result.gate is None else result.gate.message,
        source_reference_ids=source_reference_ids,
    )


def charset_runtime_plan_result(
    requested_charset: str,
    spec: CharsetSpec | None,
    source_codepoints: SourceCodepoints,
    unicode_codepoints: tuple[int, ...],
    gate: CharsetGate | None,
    source_reference_ids: tuple[str, ...],
) -> CharsetRuntimeResult:
    return CharsetRuntimeResult(
        status=_charset_runtime_status_from_gate(gate),
        requested_charset=requested_charset,
        charset_name=None if spec is None else spec.name,
        source_codepoints=source_codepoints,
        unicode_codepoints=unicode_codepoints,
        source_reference_ids=source_reference_ids,
        gate=gate,
        reason="" if gate is None else gate.message,
    )


def language_runtime_result(
    request: LanguageRuntimeRequest,
    status: LanguageRuntimeStatus,
    description: str | None,
    print_conversion: str | None,
    source_path: str | None,
    used_lang_alt_base: bool,
    reason: str = "",
) -> LanguageRuntimeResult:
    return LanguageRuntimeResult(
        status=status,
        language=request.language,
        tag_name=request.tag_name,
        printed_value=request.printed_value,
        tag_language_code=request.tag_language_code,
        used_lang_alt_base=used_lang_alt_base,
        split_bitmask_print_value=request.split_bitmask_print_value,
        description=description,
        print_conversion=print_conversion,
        reason=reason,
        source_path=source_path,
        source_reference_ids=language_source_ids(
            used_lang_alt_base,
            request.split_bitmask_print_value,
        ),
    )


def language_source_ids(
    used_lang_alt_base: bool,
    split_bitmask_print_value: bool,
) -> tuple[str, ...]:
    sources = [
        LANGUAGE_LOAD_SOURCE_ID,
        LANGUAGE_DESCRIPTION_SOURCE_ID,
        LANGUAGE_PRINT_CONV_SOURCE_ID,
    ]
    if used_lang_alt_base:
        sources.append(LANGUAGE_ALT_DESCRIPTION_SOURCE_ID)
    if split_bitmask_print_value:
        sources.append(LANGUAGE_PRINT_CONV_BITMASK_SOURCE_ID)
    return tuple(sources)


def _charset_runtime_status(result: CharsetCodepointResult) -> CharsetRuntimeStatus:
    return _charset_runtime_status_from_gate(result.gate)


def _charset_runtime_status_from_gate(gate: CharsetGate | None) -> CharsetRuntimeStatus:
    if gate is None:
        return "resolved"
    if gate.code in ("invalid_byte_order", "malformed_fixed_width", "malformed_utf8"):
        return gate.code
    if gate.code == "missing_translation_table":
        return "missing_charset_table"
    if gate.code == "invalid_codepoint":
        return "invalid_unicode_codepoint"
    if gate.code in (
        "invalid_source_codepoints",
        "unencodable_codepoint",
        "unsupported_charset",
        "unsupported_inverse",
    ):
        return gate.code
    return "unsupported_charset"


def _decode_payload_with_spec(
    repository: CharsetLanguageRepository,
    spec: CharsetSpec,
    payload: bytes,
    byte_order: Literal["II", "MM", "Unknown"] | None,
) -> CharsetCodepointResult:
    if spec.route == "utf8":
        return CharsetCodepointResult(
            requested_charset=spec.name,
            charset_name=spec.name,
            source_codepoints=tuple(payload),
            unicode_codepoints=tuple(ord(character) for character in payload.decode("utf-8")),
            supported=True,
            gate=None,
            source_symbols=("Image::ExifTool::Charset::Decompose",),
        )
    if spec.route == "fixed_one_byte":
        return _decode_payload_codepoints(repository, spec, tuple((byte,) for byte in payload))
    if spec.route in ("fixed_two_byte", "fixed_four_byte"):
        codepoints = _fixed_width_payload_codepoints(spec.route, payload, byte_order)
        if spec.name == "UTF16":
            codepoints = _compose_utf16_surrogates(codepoints)
        return CharsetCodepointResult(
            requested_charset=spec.name,
            charset_name=spec.name,
            source_codepoints=tuple(codepoints),
            unicode_codepoints=tuple(codepoints),
            supported=True,
            gate=None,
            source_symbols=("Image::ExifTool::Charset::Decompose",),
        )
    return _decode_payload_codepoints(
        repository,
        spec,
        _variable_width_source_codepoints(repository, spec, payload),
    )


def _decode_payload_codepoints(
    repository: CharsetLanguageRepository,
    spec: CharsetSpec,
    source_sequences: tuple[SourceCodepoints, ...],
) -> CharsetCodepointResult:
    decoded: list[int] = []
    source_codepoints: list[int] = []
    for sequence in source_sequences:
        result = decode_source_codepoints(repository, spec.name, sequence)
        if result.gate is not None:
            return result
        source_codepoints.extend(sequence)
        decoded.extend(result.unicode_codepoints)
    return CharsetCodepointResult(
        requested_charset=spec.name,
        charset_name=spec.name,
        source_codepoints=tuple(source_codepoints),
        unicode_codepoints=tuple(decoded),
        supported=True,
        gate=None,
        source_symbols=("Image::ExifTool::Charset::Decompose",),
    )


def _encode_payload_with_spec(
    repository: CharsetLanguageRepository,
    spec: CharsetSpec,
    unicode_codepoints: tuple[int, ...],
    byte_order: Literal["II", "MM"],
    replace_unencodable: bool,
) -> CharsetCodepointResult:
    packed_codepoints: list[int] = []
    for unicode_codepoint in unicode_codepoints:
        if spec.name == "UTF16" and 0x10000 <= unicode_codepoint < 0x10FFFF:
            packed_codepoints.extend(_decompose_utf16_surrogate(unicode_codepoint))
        else:
            packed_codepoints.append(unicode_codepoint)
    if spec.route == "utf8":
        return CharsetCodepointResult(
            requested_charset=spec.name,
            charset_name=spec.name,
            source_codepoints=tuple(_utf8_payload(unicode_codepoints)),
            unicode_codepoints=unicode_codepoints,
            supported=True,
            gate=None,
            source_symbols=("Image::ExifTool::Charset::Recompose",),
        )
    if spec.route == "fixed_one_byte":
        encoded: list[int] = []
        for codepoint in unicode_codepoints:
            result = encode_unicode_codepoint(repository, spec.name, codepoint)
            if result.gate is not None:
                if replace_unencodable and result.gate.code == "unencodable_codepoint":
                    encoded.append(ord("?"))
                    continue
                return result
            encoded.extend(result.source_codepoints)
        return CharsetCodepointResult(
            requested_charset=spec.name,
            charset_name=spec.name,
            source_codepoints=tuple(_truncate_at_null(tuple(encoded))),
            unicode_codepoints=unicode_codepoints,
            supported=True,
            gate=None,
            source_symbols=("Image::ExifTool::Charset::Recompose",),
        )
    if spec.route in ("fixed_two_byte", "fixed_four_byte"):
        packed = _fixed_width_payload_bytes(spec.route, tuple(packed_codepoints), byte_order)
        return CharsetCodepointResult(
            requested_charset=spec.name,
            charset_name=spec.name,
            source_codepoints=tuple(packed),
            unicode_codepoints=unicode_codepoints,
            supported=True,
            gate=None,
            source_symbols=("Image::ExifTool::Charset::Recompose",),
        )
    return CharsetCodepointResult(
        requested_charset=spec.name,
        charset_name=spec.name,
        source_codepoints=(),
        unicode_codepoints=unicode_codepoints,
        supported=False,
        gate=CharsetGate(
            code="unsupported_inverse",
            message=f"Byte-level inverse conversion is not implemented for {spec.name}.",
            source_symbol="Image::ExifTool::Charset::Recompose",
        ),
        source_symbols=("Image::ExifTool::Charset::Recompose",),
    )


def _fixed_width_payload_codepoints(
    route: CharsetRoute,
    payload: bytes,
    byte_order: Literal["II", "MM", "Unknown"] | None,
) -> tuple[int, ...]:
    byte_count = 4 if route == "fixed_four_byte" else 2
    payload, resolved_order = _strip_fixed_width_bom(route, payload, byte_order)
    return tuple(
        int.from_bytes(payload[index : index + byte_count], _byte_order_name(resolved_order))
        for index in range(0, len(payload), byte_count)
    )


def _fixed_width_payload_bytes(
    route: CharsetRoute,
    codepoints: tuple[int, ...],
    byte_order: Literal["II", "MM"],
) -> bytes:
    byte_count = 4 if route == "fixed_four_byte" else 2
    return b"".join(
        codepoint.to_bytes(byte_count, _byte_order_name(byte_order)) for codepoint in codepoints
    )


def _strip_fixed_width_bom(
    route: CharsetRoute,
    payload: bytes,
    byte_order: Literal["II", "MM", "Unknown"] | None,
) -> tuple[bytes, Literal["II", "MM"]]:
    if route == "fixed_four_byte":
        if payload.startswith(b"\x00\x00\xfe\xff"):
            return payload[4:], "MM"
        if payload.startswith(b"\xff\xfe\x00\x00"):
            return payload[4:], "II"
    if route == "fixed_two_byte":
        if payload.startswith(b"\xfe\xff"):
            return payload[2:], "MM"
        if payload.startswith(b"\xff\xfe"):
            return payload[2:], "II"
    resolved_order: Literal["II", "MM"]
    resolved_order = "MM" if byte_order == "MM" else "II"
    return payload, resolved_order


def _byte_order_name(byte_order: Literal["II", "MM"]) -> Literal["little", "big"]:
    return "big" if byte_order == "MM" else "little"


def _compose_utf16_surrogates(codepoints: tuple[int, ...]) -> tuple[int, ...]:
    composed: list[int] = []
    index = 0
    while index < len(codepoints):
        current = codepoints[index]
        if (
            index + 1 < len(codepoints)
            and (current & 0xFC00) == 0xD800
            and (codepoints[index + 1] & 0xFC00) == 0xDC00
        ):
            composed.append(0x10000 + ((current & 0x3FF) << 10) + (codepoints[index + 1] & 0x3FF))
            index += 2
        else:
            composed.append(current)
            index += 1
    return tuple(composed)


def _decompose_utf16_surrogate(codepoint: int) -> tuple[int, int]:
    shifted = codepoint - 0x10000
    return 0xD800 + ((shifted >> 10) & 0x3FF), 0xDC00 + (shifted & 0x3FF)


def _variable_width_source_codepoints(
    repository: CharsetLanguageRepository,
    spec: CharsetSpec,
    payload: bytes,
) -> tuple[SourceCodepoints, ...]:
    table = repository.charset(spec.name)
    if table is None:
        return tuple((byte,) for byte in payload)
    sequences: list[SourceCodepoints] = []
    index = 0
    while index < len(payload):
        if index + 1 < len(payload):
            two_byte = (payload[index], payload[index + 1])
            if table.unicode_for(two_byte) is not None:
                sequences.append(two_byte)
                index += 2
                continue
        sequences.append((payload[index],))
        index += 1
    return tuple(sequences)


def _utf8_payload(unicode_codepoints: tuple[int, ...]) -> bytes:
    return (
        "".join(chr(codepoint) for codepoint in unicode_codepoints)
        .encode("utf-8")
        .split(
            b"\x00",
            1,
        )[0]
    )


def _truncate_at_null(codepoints: tuple[int, ...]) -> tuple[int, ...]:
    if 0 in codepoints:
        return codepoints[: codepoints.index(0)]
    return codepoints


def _payload_bytes(source_codepoints: SourceCodepoints) -> bytes:
    return bytes(source_codepoints)


def _replacement_codepoints(
    result: CharsetCodepointResult,
    unicode_codepoints: tuple[int, ...],
) -> tuple[int, ...]:
    if result.charset_name is None:
        return ()
    spec = charset_spec(result.charset_name)
    if spec is None or spec.route != "fixed_one_byte":
        return ()
    replacements: list[int] = []
    for encoded_index, codepoint in enumerate(unicode_codepoints):
        if codepoint == 0:
            break
        if encoded_index >= len(result.source_codepoints):
            break
        if result.source_codepoints[encoded_index] == ord("?") and codepoint != ord("?"):
            replacements.append(codepoint)
    return tuple(replacements)


def _charset_source_ids_for_name(
    charset_name: str | None,
    operation_source_id: str,
) -> tuple[str, ...]:
    result = CharsetCodepointResult(
        requested_charset="" if charset_name is None else charset_name,
        charset_name=charset_name,
        source_codepoints=(),
        unicode_codepoints=(),
        supported=charset_name is not None,
        gate=None,
        source_symbols=(),
    )
    return _charset_source_ids(result, operation_source_id)


def _charset_decode_source_ids(
    result: CharsetCodepointResult,
) -> tuple[str, ...]:
    return _charset_source_ids(result, CHARSET_DECOMPOSE_SOURCE_ID)


def _charset_encode_source_ids(
    result: CharsetCodepointResult,
) -> tuple[str, ...]:
    return _charset_source_ids(result, CHARSET_RECOMPOSE_SOURCE_ID)


def _charset_source_ids(
    result: CharsetCodepointResult,
    operation_source_id: str,
) -> tuple[str, ...]:
    source_ids = [CHARSET_LOAD_SOURCE_ID, operation_source_id]
    spec = None if result.charset_name is None else charset_spec(result.charset_name)
    if spec is not None and spec.requires_table:
        charset_name = result.charset_name
        if charset_name is not None:
            source_ids.append(_charset_table_source_id(charset_name))
    return tuple(source_ids)


def _charset_table_source_id(charset_name: str) -> str:
    return f"charset.table.{charset_name}"
