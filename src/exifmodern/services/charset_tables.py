"""ExifTool-compatible charset routing and boundary planning.

The source of truth for charset types and aliases is ExifTool's
``lib/Image/ExifTool/Charset.pm`` and ``%charsetName`` in ``ExifTool.pm``.
This module deliberately plans compatibility boundaries instead of inventing
codec behavior for charsets whose conversion tables are external data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.services.charset_language import CharsetLanguageRepository, SourceCodepoints

type CharsetAction = Literal["decode", "encode"]
type CharsetGateCode = Literal[
    "invalid_byte_order",
    "invalid_codepoint",
    "invalid_source_codepoints",
    "malformed_fixed_width",
    "malformed_utf8",
    "missing_translation_table",
    "unencodable_codepoint",
    "unsupported_charset",
    "unsupported_inverse",
]
type CharsetRoute = Literal[
    "fixed_four_byte",
    "fixed_one_byte",
    "fixed_two_byte",
    "utf8",
    "variable_width",
]
type CharsetByteOrder = Literal["II", "MM", "Unknown"]


@dataclass(frozen=True)
class CharsetGate:
    code: CharsetGateCode
    message: str
    source_symbol: str


@dataclass(frozen=True)
class CharsetResolution:
    requested_name: str
    charset_name: str | None
    alias_used: bool
    gate: CharsetGate | None

    @property
    def supported(self) -> bool:
        return self.gate is None


@dataclass(frozen=True)
class CharsetSpec:
    name: str
    source_type: int
    route: CharsetRoute
    requires_table: bool
    remaps_ascii_range: bool
    inverse_supported: bool
    source_path: str | None


@dataclass(frozen=True)
class CharsetDecodeRequest:
    charset: str
    payload: bytes
    byte_order: CharsetByteOrder | None = None


@dataclass(frozen=True)
class CharsetEncodeRequest:
    charset: str
    unicode_codepoints: tuple[int, ...]
    byte_order: CharsetByteOrder | None = None


@dataclass(frozen=True)
class CharsetBoundaryPlan:
    action: CharsetAction
    requested_charset: str
    charset_name: str | None
    route: CharsetRoute | None
    source_type: int | None
    source_path: str | None
    requires_table: bool
    inverse_supported: bool
    supported: bool
    gate: CharsetGate | None
    byte_order: CharsetByteOrder | None
    truncates_at_null: bool
    source_symbols: tuple[str, ...]


@dataclass(frozen=True)
class CharsetCodepointResult:
    requested_charset: str
    charset_name: str | None
    source_codepoints: SourceCodepoints
    unicode_codepoints: tuple[int, ...]
    supported: bool
    gate: CharsetGate | None
    source_symbols: tuple[str, ...]


_SOURCE_CHARSET_TYPES: dict[str, int] = {
    "UTF8": 0x100,
    "ASCII": 0x100,
    "Arabic": 0x101,
    "Baltic": 0x101,
    "Cyrillic": 0x101,
    "Greek": 0x101,
    "Hebrew": 0x101,
    "Latin": 0x101,
    "Latin2": 0x101,
    "DOSLatinUS": 0x101,
    "DOSLatin1": 0x101,
    "DOSCyrillic": 0x101,
    "MacCroatian": 0x101,
    "MacCyrillic": 0x101,
    "MacGreek": 0x101,
    "MacIceland": 0x101,
    "MacLatin2": 0x101,
    "MacRoman": 0x101,
    "MacRomanian": 0x101,
    "MacTurkish": 0x101,
    "Thai": 0x101,
    "Turkish": 0x101,
    "Vietnam": 0x101,
    "MacArabic": 0x103,
    "PDFDoc": 0x181,
    "Unicode": 0x200,
    "UCS2": 0x200,
    "UTF16": 0x200,
    "Symbol": 0x201,
    "JIS": 0x201,
    "UCS4": 0x400,
    "MacChineseCN": 0x803,
    "MacChineseTW": 0x803,
    "MacHebrew": 0x803,
    "MacKorean": 0x803,
    "MacRSymbol": 0x803,
    "MacThai": 0x803,
    "MacJapanese": 0x883,
    "ShiftJIS": 0x883,
}

_PUBLIC_CHARSET_ALIASES: dict[str, str] = {
    "utf8": "UTF8",
    "cp65001": "UTF8",
    "utf-8": "UTF8",
    "latin": "Latin",
    "cp1252": "Latin",
    "latin1": "Latin",
    "latin2": "Latin2",
    "cp1250": "Latin2",
    "cyrillic": "Cyrillic",
    "cp1251": "Cyrillic",
    "russian": "Cyrillic",
    "greek": "Greek",
    "cp1253": "Greek",
    "turkish": "Turkish",
    "cp1254": "Turkish",
    "hebrew": "Hebrew",
    "cp1255": "Hebrew",
    "arabic": "Arabic",
    "cp1256": "Arabic",
    "baltic": "Baltic",
    "cp1257": "Baltic",
    "vietnam": "Vietnam",
    "cp1258": "Vietnam",
    "thai": "Thai",
    "cp874": "Thai",
    "doslatinus": "DOSLatinUS",
    "cp437": "DOSLatinUS",
    "doslatin1": "DOSLatin1",
    "cp850": "DOSLatin1",
    "doscyrillic": "DOSCyrillic",
    "cp866": "DOSCyrillic",
    "macroman": "MacRoman",
    "cp10000": "MacRoman",
    "mac": "MacRoman",
    "roman": "MacRoman",
    "maclatin2": "MacLatin2",
    "cp10029": "MacLatin2",
    "maccyrillic": "MacCyrillic",
    "cp10007": "MacCyrillic",
    "macgreek": "MacGreek",
    "cp10006": "MacGreek",
    "macturkish": "MacTurkish",
    "cp10081": "MacTurkish",
    "macromanian": "MacRomanian",
    "cp10010": "MacRomanian",
    "maciceland": "MacIceland",
    "cp10079": "MacIceland",
    "maccroatian": "MacCroatian",
    "cp10082": "MacCroatian",
}
_SOURCE_CHARSET_BY_CASEFOLD = {name.casefold(): name for name in _SOURCE_CHARSET_TYPES}
_CHARSET_NAME_SYMBOL = "Image::ExifTool::charsetName"
_RECOMPOSE_SYMBOL = "Image::ExifTool::Charset::Recompose"
_DECOMPOSE_SYMBOL = "Image::ExifTool::Charset::Decompose"


def resolve_charset_name(name: str) -> CharsetResolution:
    normalized = name.strip()
    if not normalized:
        return CharsetResolution(
            requested_name=name,
            charset_name=None,
            alias_used=False,
            gate=_gate(
                "unsupported_charset",
                "Charset name is empty after whitespace trimming.",
                _CHARSET_NAME_SYMBOL,
            ),
        )
    alias = _PUBLIC_CHARSET_ALIASES.get(normalized.casefold())
    if alias is not None:
        return CharsetResolution(
            requested_name=name,
            charset_name=alias,
            alias_used=alias != normalized,
            gate=None,
        )
    source_name = _SOURCE_CHARSET_BY_CASEFOLD.get(normalized.casefold())
    if source_name is not None:
        return CharsetResolution(
            requested_name=name,
            charset_name=source_name,
            alias_used=source_name != normalized,
            gate=None,
        )
    return CharsetResolution(
        requested_name=name,
        charset_name=None,
        alias_used=False,
        gate=_gate(
            "unsupported_charset",
            f"Charset {name!r} is not present in ExifTool charset sources.",
            _CHARSET_NAME_SYMBOL,
        ),
    )


def charset_spec(name: str) -> CharsetSpec | None:
    resolution = resolve_charset_name(name)
    if resolution.charset_name is None:
        return None
    source_type = _SOURCE_CHARSET_TYPES[resolution.charset_name]
    requires_table = bool(source_type & 0x001)
    return CharsetSpec(
        name=resolution.charset_name,
        source_type=source_type,
        route=_route_for_source_type(source_type),
        requires_table=requires_table,
        remaps_ascii_range=bool(source_type & 0x080),
        inverse_supported=not bool(source_type & 0x802),
        source_path=(
            f"lib/Image/ExifTool/Charset/{resolution.charset_name}.pm" if requires_table else None
        ),
    )


def plan_decode_boundary(
    request: CharsetDecodeRequest,
    repository: CharsetLanguageRepository | None = None,
) -> CharsetBoundaryPlan:
    return _plan_boundary(
        action="decode",
        requested_charset=request.charset,
        payload=request.payload,
        unicode_codepoints=(),
        byte_order=request.byte_order,
        repository=repository,
    )


def plan_encode_boundary(
    request: CharsetEncodeRequest,
    repository: CharsetLanguageRepository | None = None,
) -> CharsetBoundaryPlan:
    return _plan_boundary(
        action="encode",
        requested_charset=request.charset,
        payload=b"",
        unicode_codepoints=request.unicode_codepoints,
        byte_order=request.byte_order,
        repository=repository,
    )


def decode_source_codepoints(
    repository: CharsetLanguageRepository,
    charset: str,
    source_codepoints: SourceCodepoints,
) -> CharsetCodepointResult:
    spec = charset_spec(charset)
    if spec is None:
        return _codepoint_result(
            charset,
            None,
            source_codepoints,
            (),
            resolve_charset_name(charset).gate,
        )
    gate = _codepoint_source_gate(spec, source_codepoints)
    if gate is not None:
        return _codepoint_result(charset, spec.name, source_codepoints, (), gate)
    table = repository.charset(spec.name)
    if spec.requires_table and table is None:
        return _codepoint_result(
            charset,
            spec.name,
            source_codepoints,
            (),
            _missing_table_gate(spec),
        )
    mapped = None if table is None else table.unicode_for(source_codepoints)
    if mapped is not None:
        return _codepoint_result(charset, spec.name, source_codepoints, (mapped,), None)
    if spec.route == "fixed_one_byte" and len(source_codepoints) == 1:
        return _codepoint_result(
            charset,
            spec.name,
            source_codepoints,
            (source_codepoints[0],),
            None,
        )
    if spec.route == "variable_width" and len(source_codepoints) == 1:
        return _codepoint_result(
            charset,
            spec.name,
            source_codepoints,
            (source_codepoints[0],),
            None,
        )
    return _codepoint_result(
        charset,
        spec.name,
        source_codepoints,
        (),
        _gate(
            "invalid_source_codepoints",
            f"No source mapping exists for {source_codepoints!r} in {spec.name}.",
            _DECOMPOSE_SYMBOL,
        ),
    )


def encode_unicode_codepoint(
    repository: CharsetLanguageRepository,
    charset: str,
    unicode_codepoint: int,
) -> CharsetCodepointResult:
    spec = charset_spec(charset)
    if spec is None:
        return _codepoint_result(charset, None, (), (), resolve_charset_name(charset).gate)
    gate = _unicode_codepoint_gate(unicode_codepoint)
    if gate is not None:
        return _codepoint_result(charset, spec.name, (), (), gate)
    if not spec.inverse_supported:
        return _codepoint_result(charset, spec.name, (), (), _unsupported_inverse_gate(spec))
    table = repository.charset(spec.name)
    if spec.requires_table and table is None:
        return _codepoint_result(charset, spec.name, (), (), _missing_table_gate(spec))
    if table is not None:
        for source_codepoints, mapped_codepoint in table.mappings.items():
            if mapped_codepoint == unicode_codepoint:
                return _codepoint_result(
                    charset,
                    spec.name,
                    source_codepoints,
                    (unicode_codepoint,),
                    None,
                )
    if spec.route == "fixed_one_byte" and unicode_codepoint < 0x100:
        if table is None or table.unicode_for((unicode_codepoint,)) is None:
            return _codepoint_result(
                charset,
                spec.name,
                (unicode_codepoint,),
                (unicode_codepoint,),
                None,
            )
    return _codepoint_result(
        charset,
        spec.name,
        (),
        (unicode_codepoint,),
        _gate(
            "unencodable_codepoint",
            f"Unicode codepoint U+{unicode_codepoint:04X} is not encodable as {spec.name}.",
            _RECOMPOSE_SYMBOL,
        ),
    )


def _plan_boundary(
    action: CharsetAction,
    requested_charset: str,
    payload: bytes,
    unicode_codepoints: tuple[int, ...],
    byte_order: CharsetByteOrder | None,
    repository: CharsetLanguageRepository | None,
) -> CharsetBoundaryPlan:
    byte_order_gate = _byte_order_gate(byte_order)
    resolution = resolve_charset_name(requested_charset)
    spec = None if resolution.charset_name is None else charset_spec(resolution.charset_name)
    gate = byte_order_gate or resolution.gate
    if spec is not None and gate is None:
        if action == "encode" and not spec.inverse_supported:
            gate = _unsupported_inverse_gate(spec)
        elif (
            spec.requires_table and repository is not None and repository.charset(spec.name) is None
        ):
            gate = _missing_table_gate(spec)
        elif action == "decode":
            gate = _decode_payload_gate(spec, payload)
        else:
            gate = _unicode_codepoints_gate(unicode_codepoints)
    return CharsetBoundaryPlan(
        action=action,
        requested_charset=requested_charset,
        charset_name=None if spec is None else spec.name,
        route=None if spec is None else spec.route,
        source_type=None if spec is None else spec.source_type,
        source_path=None if spec is None else spec.source_path,
        requires_table=False if spec is None else spec.requires_table,
        inverse_supported=False if spec is None else spec.inverse_supported,
        supported=gate is None,
        gate=gate,
        byte_order=byte_order,
        truncates_at_null=_truncates_at_null(action, spec),
        source_symbols=(_DECOMPOSE_SYMBOL if action == "decode" else _RECOMPOSE_SYMBOL,),
    )


def _decode_payload_gate(spec: CharsetSpec, payload: bytes) -> CharsetGate | None:
    if spec.route == "utf8":
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError:
            return _gate(
                "malformed_utf8",
                f"Malformed UTF-8 payload cannot be decoded as {spec.name}.",
                _DECOMPOSE_SYMBOL,
            )
    width = _fixed_width_size(spec.route)
    if width is not None and _payload_unit_remainder(payload, width) != 0:
        return _gate(
            "malformed_fixed_width",
            f"{spec.name} payload length is not divisible by its {width}-byte unit size.",
            _DECOMPOSE_SYMBOL,
        )
    return None


def _byte_order_gate(byte_order: CharsetByteOrder | None) -> CharsetGate | None:
    if byte_order in (None, "II", "MM", "Unknown"):
        return None
    return _gate(
        "invalid_byte_order",
        f"Byte order {byte_order!r} is not one of II, MM or Unknown.",
        _DECOMPOSE_SYMBOL,
    )


def _unicode_codepoints_gate(codepoints: tuple[int, ...]) -> CharsetGate | None:
    for codepoint in codepoints:
        gate = _unicode_codepoint_gate(codepoint)
        if gate is not None:
            return gate
    return None


def _unicode_codepoint_gate(codepoint: int) -> CharsetGate | None:
    if codepoint < 0 or codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
        return _gate(
            "invalid_codepoint",
            f"Unicode codepoint {codepoint!r} is outside scalar-value boundaries.",
            _RECOMPOSE_SYMBOL,
        )
    return None


def _codepoint_source_gate(
    spec: CharsetSpec,
    source_codepoints: SourceCodepoints,
) -> CharsetGate | None:
    if not source_codepoints:
        return _gate(
            "invalid_source_codepoints",
            "Source codepoint sequence is empty.",
            _DECOMPOSE_SYMBOL,
        )
    for source_codepoint in source_codepoints:
        if source_codepoint < 0 or source_codepoint > 0xFF:
            return _gate(
                "invalid_source_codepoints",
                f"Source byte {source_codepoint!r} is outside 8-bit boundaries.",
                _DECOMPOSE_SYMBOL,
            )
    if spec.route == "fixed_one_byte" and len(source_codepoints) != 1:
        return _gate(
            "invalid_source_codepoints",
            f"{spec.name} uses one-byte fixed-width source codepoints.",
            _DECOMPOSE_SYMBOL,
        )
    if spec.route != "variable_width" and len(source_codepoints) != 1:
        return _gate(
            "invalid_source_codepoints",
            f"{spec.name} does not use variable-width table source codepoints.",
            _DECOMPOSE_SYMBOL,
        )
    return None


def _route_for_source_type(source_type: int) -> CharsetRoute:
    if source_type == 0x100:
        return "utf8"
    if source_type & 0x100:
        return "fixed_one_byte"
    if source_type & 0x200:
        return "fixed_two_byte"
    if source_type & 0x400:
        return "fixed_four_byte"
    return "variable_width"


def _fixed_width_size(route: CharsetRoute) -> int | None:
    if route == "fixed_two_byte":
        return 2
    if route == "fixed_four_byte":
        return 4
    return None


def _payload_unit_remainder(payload: bytes, width: int) -> int:
    if width == 2 and (payload.startswith(b"\xfe\xff") or payload.startswith(b"\xff\xfe")):
        return len(payload[2:]) % width
    if width == 4 and (
        payload.startswith(b"\x00\x00\xfe\xff") or payload.startswith(b"\xff\xfe\x00\x00")
    ):
        return len(payload[4:]) % width
    return len(payload) % width


def _truncates_at_null(action: CharsetAction, spec: CharsetSpec | None) -> bool:
    if action != "encode" or spec is None:
        return False
    return spec.route in {"utf8", "fixed_one_byte"}


def _missing_table_gate(spec: CharsetSpec) -> CharsetGate:
    return _gate(
        "missing_translation_table",
        f"{spec.name} requires {spec.source_path} before source-backed conversion.",
        "Image::ExifTool::Charset::LoadCharset",
    )


def _unsupported_inverse_gate(spec: CharsetSpec) -> CharsetGate:
    return _gate(
        "unsupported_inverse",
        f"ExifTool Recompose does not support inverse conversion for {spec.name}.",
        _RECOMPOSE_SYMBOL,
    )


def _codepoint_result(
    requested_charset: str,
    charset_name: str | None,
    source_codepoints: SourceCodepoints,
    unicode_codepoints: tuple[int, ...],
    gate: CharsetGate | None,
) -> CharsetCodepointResult:
    return CharsetCodepointResult(
        requested_charset=requested_charset,
        charset_name=charset_name,
        source_codepoints=source_codepoints,
        unicode_codepoints=unicode_codepoints,
        supported=gate is None,
        gate=gate,
        source_symbols=(_DECOMPOSE_SYMBOL, _RECOMPOSE_SYMBOL),
    )


def _gate(code: CharsetGateCode, message: str, source_symbol: str) -> CharsetGate:
    return CharsetGate(code=code, message=message, source_symbol=source_symbol)
