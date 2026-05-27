"""TNEF metadata transaction planning public API."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from struct import unpack_from
from typing import TYPE_CHECKING

from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.formats.tnef.metadata_transaction_plan import (
    TnefMapiPropertyPlan,
    TnefMetadataTransactionPlan,
    build_tnef_metadata_transaction_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag

type TnefPublicValue = bytes | bool | int | float | str

__all__ = (
    "TnefMetadataTransactionPlan",
    "build_tnef_metadata_transaction_plan",
    "build_tnef_read_graph",
    "invoke_tnef",
)


_TNEF_TABLE = "Image::ExifTool::TNEF::Main"
_TNEF_MAPI_TABLE = "Image::ExifTool::TNEF::MsgProps"
_WINDOWS_LATIN_1 = "Windows Latin 1 (Western European)"
_FILETIME_UNIX_EPOCH_DELTA = 11644473600
_MAPI_NAMED_PROP_NAMES = {"00062008_00008554": "AppVersion"}
_TNEF_ATTRIBUTE_SCAN_LIMIT = 8 * 1024 * 1024


def build_tnef_read_graph(data: bytes, source_file: str) -> ReadGraph:
    """Translate a TNEF metadata transaction plan into decoded ExifTool-compatible tags."""
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    plan = build_tnef_metadata_transaction_plan(data, allow_output_emission=True)
    diagnostics = [
        f"TNEF package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    ]
    if plan.status != "planned":
        diagnostics.insert(0, f"TNEF package-local reader status: {plan.status}")

    tags: list[ReadTag] = []
    if plan.signature.is_valid:
        for name, value, tag_id in (
            ("FileType", "TNEF", "FileType"),
            ("FileTypeExtension", "tnef", "FileTypeExtension"),
            ("MIMEType", "application/vnd.ms-tnef", "MIMEType"),
        ):
            tags.append(
                ReadTag(
                    name=name,
                    value=_read_value(value),
                    provenance=_provenance(
                        group="File",
                        table_name="Image::ExifTool::File",
                        tag_id=tag_id,
                        evidence_ids=plan.evidence_ids,
                    ),
                    schema=None,
                )
            )
    for attribute in plan.attributes:
        attribute_value = _tnef_attribute_value(
            attribute.tag_name, data[slice(*attribute.payload_range)]
        )
        if attribute_value is None:
            continue
        tags.append(
            ReadTag(
                name=attribute.tag_name,
                value=_read_value(attribute_value),
                provenance=_provenance(
                    group="File",
                    table_name=_TNEF_TABLE,
                    tag_id=f"0x{attribute.tag_id:06x}",
                    evidence_ids=attribute.evidence_ids,
                    duplicate_instance_ordinal=attribute.index,
                ),
                schema=None,
            )
        )
    deferred_correlation_tags: list[ReadTag] = []
    for prop in plan.mapi_properties:
        tag_name = _tnef_mapi_tag_name(prop)
        mapi_value = _tnef_mapi_value(prop, data[slice(*prop.value_range)])
        if mapi_value is None:
            continue
        read_tag = ReadTag(
            name=tag_name,
            value=_read_value(mapi_value),
            provenance=_provenance(
                group="File",
                table_name=_TNEF_MAPI_TABLE,
                tag_id=prop.tag_key,
                evidence_ids=prop.evidence_ids,
                duplicate_instance_ordinal=prop.property_index,
            ),
            schema=None,
        )
        if tag_name == "CorrelationKey":
            deferred_correlation_tags.append(read_tag)
        else:
            tags.append(read_tag)
    tags.extend(deferred_correlation_tags)
    return _graph(source_file, tags, diagnostics)


def _tnef_attribute_value(name: str, payload: bytes) -> TnefPublicValue | None:
    if name == "TNEFVersion":
        return ".".join(str(part) for part in reversed(payload))
    if name == "CodePage" and len(payload) >= 4:
        code_page = int.from_bytes(payload[:4], "little")
        return _WINDOWS_LATIN_1 if code_page == 1252 else code_page
    if name == "Priority" and len(payload) >= 2:
        return {0: "Low", 1: "Normal", 2: "High"}.get(
            int.from_bytes(payload[:2], "little"),
            int.from_bytes(payload[:2], "little"),
        )
    if name in {"SentDate", "ReceivedDate", "MessageModifyDate"} and len(payload) >= 12:
        year, month, day, hour, minute, second = unpack_from("<6H", payload)
        return f"{year:04d}:{month:02d}:{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
    if name in {"MessageProps", "Subject"}:
        return None
    if name in {"MessageClass", "MessageID", "Subject"}:
        return _decode_ansi(payload)
    return _decode_ansi(payload) if payload else None


def _tnef_mapi_tag_name(prop: TnefMapiPropertyPlan) -> str:
    return _MAPI_NAMED_PROP_NAMES.get(prop.tag_key, prop.tag_name)


def _tnef_mapi_value(prop: TnefMapiPropertyPlan, payload: bytes) -> TnefPublicValue | None:
    tag_name = _tnef_mapi_tag_name(prop)
    is_unknown_named_property = "_" in tag_name and tag_name not in _MAPI_NAMED_PROP_NAMES.values()
    if tag_name.startswith("0x") or is_unknown_named_property:
        return None
    if prop.value_format == "int16s" and len(payload) >= 2:
        value = int.from_bytes(payload[:2], "little", signed=True)
        return bool(value) if prop.property_type == 0x0B else value
    if prop.value_format == "int32s" and len(payload) >= 4:
        return int.from_bytes(payload[:4], "little", signed=True)
    if prop.value_format == "int64u" and len(payload) >= 8:
        return _filetime_to_local_text(int.from_bytes(payload[:8], "little"))
    if prop.value_format == "int64s" and len(payload) >= 8:
        return int.from_bytes(payload[:8], "little", signed=True)
    if prop.value_format == "string":
        text_value = _decode_ansi(payload)
        if tag_name == "AppVersion":
            return _float_or_text(text_value)
        return text_value
    if prop.value_format == "Unicode":
        return payload.decode("utf-16-le", "replace").rstrip("\x00")
    if prop.value_format == "undef":
        if tag_name == "MessageBodyRTF":
            return _decompress_rtf(payload)
        if tag_name == "CorrelationKey":
            return _decode_ansi(payload)
        return payload
    if prop.value_format == "double" and len(payload) >= 8:
        return float(unpack_from("<d", payload)[0])
    if prop.value_format == "float" and len(payload) >= 4:
        return float(unpack_from("<f", payload)[0])
    return None


def _decode_ansi(payload: bytes) -> str:
    return payload.rstrip(b"\x00").decode("cp1252", "replace")


def _float_or_text(value: str) -> float | str:
    try:
        return float(value)
    except ValueError:
        return value


def _filetime_to_local_text(value: int) -> str:
    seconds = round(value / 10_000_000 - _FILETIME_UNIX_EPOCH_DELTA)
    instant = datetime.fromtimestamp(seconds).astimezone()
    return instant.strftime("%Y:%m:%d %H:%M:%S%z")[:-2] + ":" + instant.strftime("%z")[-2:]


def _decompress_rtf(compressed: bytes) -> bytes:
    if len(compressed) <= 16:
        return b""
    compression = int.from_bytes(compressed[8:12], "little")
    if compression == 0x414C454D:
        return compressed[16:]
    if compression != 0x75465A4C:
        return b""
    dictionary = bytearray(
        (
            r"{\rtf1\ansi\mac\deff0\deftab720{\fonttbl;}"
            r"{\f0\fnil \froman \fswiss \fmodern "
            r"\fscript \fdecor MS Sans SerifSymbolArialTimes"
            " New RomanCourier"
            r"{\colortbl\red0\green0\blue0"
            "\r\n"
            r"\par \pard\plain\f0\fs20\b\i\u\tab\tx"
        ).encode("latin1")
    )
    compressed_pos = 16
    dictionary_pos = len(dictionary)
    output = bytearray()
    while compressed_pos < len(compressed):
        control = compressed[compressed_pos]
        compressed_pos += 1
        for bit in range(8):
            if compressed_pos >= len(compressed):
                break
            if control & (1 << bit):
                if compressed_pos + 2 > len(compressed):
                    return bytes(output)
                reference = int.from_bytes(compressed[compressed_pos : compressed_pos + 2], "big")
                compressed_pos += 2
                offset = reference >> 4
                length = (reference & 0x0F) + 2
                if offset == dictionary_pos % 4096 or offset % 4096 >= len(dictionary):
                    return bytes(output)
                for _ in range(length):
                    byte = dictionary[offset % 4096]
                    _dictionary_set(dictionary, dictionary_pos % 4096, byte)
                    dictionary_pos += 1
                    output.append(byte)
                    offset += 1
            else:
                byte = compressed[compressed_pos]
                compressed_pos += 1
                _dictionary_set(dictionary, dictionary_pos % 4096, byte)
                dictionary_pos += 1
                output.append(byte)
    return bytes(output)


def _dictionary_set(dictionary: bytearray, index: int, value: int) -> None:
    if index < len(dictionary):
        dictionary[index] = value
    else:
        dictionary.append(value)


def invoke_tnef(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_tnef_read_graph(
        _read_bounded_prefix(path, _TNEF_ATTRIBUTE_SCAN_LIMIT),
        source_file,
    )


def _read_bounded_prefix(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        return file.read(byte_count)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="tnef",
        builder_ref="exifmodern.formats.tnef:invoke_tnef",
        patterns=(Pattern(0, b"\x78\x9f\x3e\x22"),),
    ),
)


install_evidence_reference_compat(globals())
