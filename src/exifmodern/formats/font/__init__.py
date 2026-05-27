"""Font metadata transaction planning."""

from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.font.metadata_transaction_plan import (
    FONT_PROCESS_SOURCE,
    build_font_metadata_transaction_plan,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = (
    "build_font_metadata_transaction_plan",
    "build_font_read_graph",
    "invoke_font",
    "is_font_prefix",
)

_FONT_DIRECTORY_SCAN_LIMIT = 8 * 1024 * 1024


def is_font_prefix(prefix: bytes) -> bool:
    """Structural gate for generic Font.pm signatures."""
    from exifmodern.formats.font.metadata_transaction_plan import inspect_font

    if _is_dfont_prefix(prefix):
        return True
    if _font_special_kind(prefix) is not None:
        return True
    parts = inspect_font(prefix)
    # Font.pm validates the SFNT wrapper and then routes selected tables such as
    # "name"; unrelated table offset/checksum problems do not prevent extraction.
    return parts.signature_validation.is_supported and bool(parts.name_records)


def build_font_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value, _references
    from exifmodern.read_graph import ReadTag

    diagnostics: list[str] = []
    tags: list[ReadTag] = []

    def _add_file(name: str, value: str | int) -> None:
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group="File",
                    table_name="Image::ExifTool::File",
                    tag_id=name,
                    references=(FONT_PROCESS_SOURCE,),
                ),
                schema=None,
            )
        )

    def _add_main(name: str, value: str | int | float | bool) -> None:
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group="Font",
                    table_name="Image::ExifTool::Font::Main",
                    tag_id=name,
                    references=(FONT_PROCESS_SOURCE,),
                ),
                schema=None,
            )
        )

    def _add_font_table(name: str, value: str | int | float | bool, table: str) -> None:
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group="Font",
                    table_name=table,
                    tag_id=name,
                    references=(FONT_PROCESS_SOURCE,),
                ),
                schema=None,
            )
        )

    def _add_postscript(name: str, value: str) -> None:
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group="PostScript",
                    table_name="Image::ExifTool::PostScript::Main",
                    tag_id=name,
                    references=(FONT_PROCESS_SOURCE,),
                ),
                schema=None,
            )
        )

    special_kind = _font_special_kind(data)
    if special_kind == "afm":
        _add_file("FileType", "AFM")
        _add_file("FileTypeExtension", "afm")
        _add_file("MIMEType", "application/x-font-afm")
        for name, value in _read_afm_tags(data).items():
            if name == "Comment":
                _add_file(name, str(value))
            else:
                _add_font_table(name, value, "Image::ExifTool::Font::AFM")
        return _graph(source_file, tags, diagnostics)
    if special_kind in {"pfa", "pfb"}:
        _add_file("FileType", special_kind.upper())
        _add_file("FileTypeExtension", special_kind)
        _add_file("MIMEType", "application/x-font-type1")
        type1 = _read_type1_tags(data, special_kind)
        comment = type1.get("Comment")
        if isinstance(comment, str):
            _add_file("Comment", comment)
        for name in ("Title", "CreateDate", "Creator"):
            postscript_value = type1.get(name)
            if isinstance(postscript_value, str):
                _add_postscript(name, postscript_value)
        for name, type1_value in type1.items():
            if name in {"Comment", "Title", "CreateDate", "Creator"}:
                continue
            if isinstance(type1_value, str | int | float | bool):
                _add_font_table(name, type1_value, "Image::ExifTool::Font::PSInfo")
        return _graph(source_file, tags, diagnostics)
    if special_kind == "pfm":
        _add_file("FileType", "PFM")
        _add_file("FileTypeExtension", "pfm")
        _add_file("MIMEType", "application/x-font-type1")
        for name, value in _read_pfm_tags(data).items():
            _add_font_table(name, value, "Image::ExifTool::Font::PFM")
        return _graph(source_file, tags, diagnostics)
    if _is_dfont_prefix(data):
        from exifmodern.formats.rsrc.resource_transaction_plan import (
            build_rsrc_resource_transaction_plan,
        )

        rsrc_plan = build_rsrc_resource_transaction_plan(data, allow_output_emission=True)
        if rsrc_plan.status != "planned":
            diagnostics.append(f"Font DFONT RSRC reader status: {rsrc_plan.status}")
        _add_file("FileType", "DFONT")
        _add_file("FileTypeExtension", "dfont")
        _add_file("MIMEType", "application/x-dfont")
        for resource in rsrc_plan.resources:
            if resource.resource_type != "sfnt" or resource.data.payload is None:
                continue
            sfnt_plan = build_font_metadata_transaction_plan(resource.data.payload)
            diagnostics.extend(
                f"Font DFONT sfnt reader gate: {gate.code}: {gate.reason}"
                for gate in sfnt_plan.output_emission_gates
                if gate.blocks_emission
                and gate.code != "non_mutating_plan_requires_explicit_emission"
            )
            for record in sfnt_plan.name_records:
                if record.tag_name is None:
                    continue
                tag_name = record.tag_name
                if record.language and record.language != "en":
                    tag_name = f"{tag_name}-{record.language}"
                tags.append(
                    ReadTag(
                        name=tag_name,
                        value=_read_value(record.value_text),
                        provenance=_provenance(
                            group="Font",
                            table_name="Image::ExifTool::Font::Name",
                            tag_id=str(record.name_id),
                            references=(*_references(resource), *_references(record)),
                            duplicate_instance_ordinal=record.table_index,
                        ),
                        schema=None,
                    )
                )
        for responsibility in rsrc_plan.responsibilities:
            if responsibility.tag_name != "ApplicationVersion":
                continue
            for value in responsibility.decoded_values:
                tags.append(
                    ReadTag(
                        name="ApplicationVersion",
                        value=_read_value(value),
                        provenance=_provenance(
                            group="RSRC",
                            table_name="Image::ExifTool::RSRC::Main",
                            tag_id=responsibility.tag_key,
                            references=_references(responsibility),
                        ),
                        schema=None,
                    )
                )
        return _graph(source_file, tags, diagnostics)

    plan = build_font_metadata_transaction_plan(data)
    if plan.status != "planned":
        diagnostics.append(f"Font package-local reader status: {plan.status}")
    diagnostics.extend(
        f"Font package-local reader gate: {gate.code}: {gate.reason}"
        for gate in plan.output_emission_gates
    )

    if plan.signature_validation.is_supported:
        _add_file("FileType", plan.signature_validation.flavor.upper())
        _add_file("FileTypeExtension", plan.signature_validation.flavor)
        mime_type = _font_mime_type(plan.signature_validation.flavor)
        if mime_type is not None:
            _add_file("MIMEType", mime_type)
    if plan.collection_members:
        _add_main("NumFonts", len(plan.collection_members))
    woff_version = _woff_version(data)
    if woff_version is not None:
        _add_main("WOFFVersion", woff_version)

    for record in plan.name_records:
        if record.tag_name is None:
            continue
        tag_name = record.tag_name
        if record.language and record.language not in {"en", "en-US"}:
            tag_name = f"{tag_name}-{record.language}"
        tags.append(
            ReadTag(
                name=tag_name,
                value=_read_value(record.value_text),
                provenance=_provenance(
                    group="Font",
                    table_name="Image::ExifTool::Font::Name",
                    tag_id=str(record.name_id),
                    references=_references(record),
                    duplicate_instance_ordinal=record.table_index,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def _font_special_kind(data: bytes) -> str | None:
    prefix = data[:32]
    if prefix.startswith(b"StartFontMetrics"):
        return "afm"
    if prefix.startswith((b"%!PS-AdobeFont-", b"%!PS-Bitstream", b"%!FontType1-")):
        return "pfa"
    if len(data) >= 6 and data[0:2] == b"\x80\x01" and data[6:18].startswith(b"%!PS-Adobe"):
        return "pfb"
    if _is_pfm_font(data):
        return "pfm"
    return None


def _is_dfont_prefix(data: bytes) -> bool:
    if len(data) < 16:
        return False
    data_offset = int.from_bytes(data[0:4], "big")
    map_offset = int.from_bytes(data[4:8], "big")
    data_length = int.from_bytes(data[8:12], "big")
    map_length = int.from_bytes(data[12:16], "big")
    return (
        data_offset >= 0x10
        and map_offset >= 0x10
        and data_length > 0
        and map_length >= 30
        and data_offset + data_length <= map_offset
    )


def _read_afm_tags(data: bytes) -> dict[str, str | int | float | bool]:
    tag_names = {
        "Creation Date": "CreateDate",
        "FontName": "FontName",
        "FullName": "FullName",
        "FamilyName": "FontFamily",
        "Weight": "Weight",
        "Version": "Version",
        "Notice": "Notice",
        "EncodingScheme": "EncodingScheme",
        "MappingScheme": "MappingScheme",
        "EscChar": "EscChar",
        "CharacterSet": "CharacterSet",
        "Characters": "Characters",
        "IsBaseFont": "IsBaseFont",
        "IsFixedV": "IsFixedV",
        "CapHeight": "CapHeight",
        "XHeight": "XHeight",
        "Ascender": "Ascender",
        "Descender": "Descender",
    }
    tags: dict[str, str | int | float | bool] = {}
    comments: list[str] = []
    for raw_line in data.decode("latin-1", errors="replace").splitlines():
        if " " not in raw_line:
            continue
        tag, value = raw_line.split(" ", 1)
        if tag.startswith("Start") and tag not in {"StartDirection", "StartFontMetrics"}:
            break
        if tag == "Comment" and value.startswith("Creation Date: "):
            tag = "Creation Date"
            value = value.removeprefix("Creation Date: ")
        if value.startswith("(") and value.endswith(")"):
            value = value[1:-1]
        if tag == "Comment":
            comments.append(value)
            continue
        name = tag_names.get(tag)
        if name is None:
            continue
        tags[name] = _font_scalar(value)
    if comments:
        tags["Comment"] = "\n".join(comments)
    return tags


def _read_type1_tags(data: bytes, kind: str) -> dict[str, str | int | float | bool]:
    ps_data = data
    if kind == "pfb" and len(data) >= 6:
        segment_length = int.from_bytes(data[2:6], "little")
        ps_data = data[6 : 6 + segment_length]
    text = ps_data.decode("latin-1", errors="replace")
    tags: dict[str, str | int | float | bool] = {}
    comment_lines: list[str] = ["1"]
    collecting_comments = True
    for line in text.splitlines():
        if line.startswith("%%Title:"):
            tags["Title"] = line.split(":", 1)[1].strip()
        elif line.startswith("%%CreationDate:"):
            tags["CreateDate"] = line.split(":", 1)[1].strip()
        elif line.startswith("%%Creator:"):
            tags["Creator"] = line.split(":", 1)[1].strip()
        elif collecting_comments and line.startswith("% "):
            comment_lines.append(line[2:])
        elif collecting_comments and not line.startswith("%"):
            collecting_comments = False
    if len(comment_lines) > 1:
        tags["Comment"] = "\n".join(comment_lines)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("currentdict end"):
            break
        if not stripped.startswith("/"):
            continue
        parts = stripped[1:].split(None, 1)
        if len(parts) != 2:
            continue
        raw_name, raw_value = parts
        name = {
            "FamilyName": "FontFamily",
            "version": "Version",
            "isFixedPitch": "IsFixedPitch",
        }.get(raw_name, raw_name)
        if name not in {
            "FullName",
            "FontFamily",
            "Weight",
            "ItalicAngle",
            "IsFixedPitch",
            "UnderlinePosition",
            "UnderlineThickness",
            "Copyright",
            "Notice",
            "Version",
            "FontName",
            "FontType",
            "FSType",
        }:
            continue
        tags[name] = _font_scalar(_postscript_value(raw_value))
    return tags


def _postscript_value(raw_value: str) -> str:
    if raw_value.startswith("("):
        end = raw_value.find(") readonly")
        if end < 0:
            end = raw_value.find(")")
        return _unescape_postscript(raw_value[1:end])
    value = raw_value.removesuffix(" def")
    value = value.removesuffix(" readonly")
    value = value.strip()
    return value.removeprefix("/")


def _unescape_postscript(value: str) -> str:
    replacements = {
        "\\050": "(",
        "\\051": ")",
        "\\012": "\n",
        "\\.": ".",
        "\\\\": "\\",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value


def _is_pfm_font(data: bytes) -> bool:
    if len(data) < 117 or data[:2] not in {b"\x00\x01", b"\x00\x02"}:
        return False
    file_size = int.from_bytes(data[2:6], "little")
    if file_size != len(data):
        return False
    device_offset = int.from_bytes(data[101:105], "little")
    device = data[device_offset : device_offset + 11].lower()
    return device == b"postscript\x00"


def _read_pfm_tags(data: bytes) -> dict[str, str | int | float | bool]:
    tags: dict[str, str | int | float | bool] = {
        "PFMVersion": _pfm_version(int.from_bytes(data[0:2], "little")),
        "Copyright": _nul_string(data[6:66]),
        "FontType": int.from_bytes(data[66:68], "little"),
        "PointSize": int.from_bytes(data[68:70], "little"),
        "YResolution": int.from_bytes(data[70:72], "little"),
        "XResolution": int.from_bytes(data[72:74], "little"),
        "Ascent": int.from_bytes(data[74:76], "little"),
        "InternalLeading": int.from_bytes(data[76:78], "little"),
        "ExternalLeading": int.from_bytes(data[78:80], "little"),
        "Italic": data[80],
        "Underline": data[81],
        "Strikeout": data[82],
        "Weight": int.from_bytes(data[83:85], "little"),
        "CharacterSet": data[85],
        "PixWidth": int.from_bytes(data[86:88], "little"),
        "PixHeight": int.from_bytes(data[88:90], "little"),
        "PitchAndFamily": data[90],
        "AvgWidth": int.from_bytes(data[91:93], "little"),
        "MaxWidth": int.from_bytes(data[93:95], "little"),
        "FirstChar": data[95],
        "LastChar": data[96],
        "DefaultChar": data[97],
        "BreakChar": data[98],
        "WidthBytes": int.from_bytes(data[99:101], "little"),
    }
    name_offset = int.from_bytes(data[105:109], "little")
    names = data[name_offset : name_offset + 256].split(b"\0")
    if len(names) >= 2:
        tags["FontName"] = names[0].decode("latin-1", errors="replace")
        tags["PostScriptFontName"] = names[1].decode("latin-1", errors="replace")
    return tags


def _font_scalar(value: str) -> str | int | float | bool:
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        integer = int(value)
    except ValueError:
        integer = None
    if integer is not None:
        return integer
    try:
        return float(value)
    except ValueError:
        return value


def _pfm_version(value: int) -> float:
    major = value >> 8
    minor = value & 0xFF
    return float(f"{major}.{minor:02x}")


def _nul_string(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("latin-1", errors="replace")


def _woff_version(data: bytes) -> str | None:
    if data.startswith(b"wOFF") and len(data) >= 24:
        major = int.from_bytes(data[20:22], "big")
        minor = int.from_bytes(data[22:24], "big")
        return f"{major}.{minor}"
    if data.startswith(b"wOF2") and len(data) >= 28:
        major = int.from_bytes(data[24:26], "big")
        minor = int.from_bytes(data[26:28], "big")
        return f"{major}.{minor}"
    return None


def _font_mime_type(flavor: str) -> str | None:
    return {
        "ttf": "application/font-ttf",
        "otf": "application/vnd.ms-opentype",
        "ttc": "application/font-sfnt",
        "woff": "font/woff",
        "woff2": "font/woff2",
    }.get(flavor)


def invoke_font(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    data = _read_bounded_prefix(path, _FONT_DIRECTORY_SCAN_LIMIT)
    return build_font_read_graph(data, source_file)


def _read_bounded_prefix(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        return file.read(byte_count)


_FONT_BUILDER = "exifmodern.formats.font:invoke_font"

SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="font/ttf",
        builder_ref=_FONT_BUILDER,
        patterns=(Pattern(0, b"\x00\x01\x00\x00"),),
        weak=True,
        structural_check="exifmodern.formats.font:is_font_prefix",
        notes=("collides with TIFF-shaped headers; needs extension hint",),
    ),
    Signature(
        format_id="font/otf",
        builder_ref=_FONT_BUILDER,
        patterns=(Pattern(0, b"OTTO"),),
    ),
    Signature(
        format_id="font/ttc",
        builder_ref=_FONT_BUILDER,
        patterns=(Pattern(0, b"ttcf"),),
        structural_check="exifmodern.formats.font:is_font_prefix",
    ),
    Signature(
        format_id="font/true",
        builder_ref=_FONT_BUILDER,
        patterns=(Pattern(0, b"true"),),
        structural_check="exifmodern.formats.font:is_font_prefix",
    ),
    Signature(
        format_id="font/typ1",
        builder_ref=_FONT_BUILDER,
        patterns=(Pattern(0, b"typ1"),),
        structural_check="exifmodern.formats.font:is_font_prefix",
    ),
    Signature(
        format_id="font/woff",
        builder_ref=_FONT_BUILDER,
        patterns=(Pattern(0, b"wOFF"),),
        structural_check="exifmodern.formats.font:is_font_prefix",
    ),
    Signature(
        format_id="font/woff2",
        builder_ref=_FONT_BUILDER,
        patterns=(Pattern(0, b"wOF2"),),
        structural_check="exifmodern.formats.font:is_font_prefix",
    ),
    Signature(
        format_id="font/type1_adobe",
        builder_ref=_FONT_BUILDER,
        patterns=(Pattern(0, b"%!PS-AdobeFont-"),),
    ),
    Signature(
        format_id="font/type1_bitstream",
        builder_ref=_FONT_BUILDER,
        patterns=(Pattern(0, b"%!PS-Bitstream"),),
    ),
    Signature(
        format_id="font/type1_fonttype",
        builder_ref=_FONT_BUILDER,
        patterns=(Pattern(0, b"%!FontType1-"),),
    ),
    Signature(
        format_id="font/pfb-type1",
        builder_ref=_FONT_BUILDER,
        patterns=(Pattern(0, b"\x80\x01"), Pattern(6, b"%!PS-Adobe")),
        structural_check="exifmodern.formats.font:is_font_prefix",
    ),
    Signature(
        format_id="font/afm",
        builder_ref=_FONT_BUILDER,
        patterns=(),
        structural_check="exifmodern.formats.font:is_font_prefix",
        extensions=(".afm",),
        notes=(
            "Font.pm ProcessFont detects Start(Comp|Master)?FontMetrics plus a "
            "version number; use extension fallback because the token is textual "
            "and not unique enough for global magic dispatch.",
        ),
    ),
    Signature(
        format_id="font/pfm",
        builder_ref=_FONT_BUILDER,
        patterns=(),
        structural_check="exifmodern.formats.font:is_font_prefix",
        extensions=(".pfm",),
        notes=(
            "Font.pm ProcessFont validates PFM by version bytes, file length, "
            "and a PostScript DeviceType string before dispatch.",
        ),
    ),
    Signature(
        format_id="font/dfont",
        builder_ref=_FONT_BUILDER,
        patterns=(),
        structural_check="exifmodern.formats.font:is_font_prefix",
        extensions=(".dfont",),
        notes=(
            "RSRC.pm treats sfnt resources as DFONT files and delegates the "
            "payload to Font.pm ProcessOTF.",
        ),
    ),
)
