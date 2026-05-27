"""PostScript/EPS DSC transaction planning public API."""

import re
from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
from exifmodern.evidence_compat import install_evidence_reference_compat
from exifmodern.formats.icc.reader import parse_icc_header_tags, parse_icc_profile_tags
from exifmodern.formats.photoshop.reader import (
    parse_current_iptc_digest_tags,
    parse_photoshop_iptc_tags,
    parse_photoshop_print_scale_tags,
    parse_photoshop_resolution_tags,
    parse_photoshop_slice_tags,
    parse_photoshop_tags,
    parse_photoshop_version_tags,
)
from exifmodern.formats.postscript.dsc_transaction_plan import (
    POSTSCRIPT_HEADER_SOURCE,
    POSTSCRIPT_ICC_SOURCE,
    POSTSCRIPT_IMAGE_SIZE_SOURCE,
    POSTSCRIPT_IPTC_SOURCE,
    POSTSCRIPT_NESTED_DISPATCH_SOURCE,
    POSTSCRIPT_PHOTOSHOP_SOURCE,
    POSTSCRIPT_TAG_TABLE_SOURCE,
    POSTSCRIPT_XMP_SOURCE,
    build_postscript_dsc_transaction_plan,
    split_physical_lines,
)
from exifmodern.formats.xmp.reader import parse_xmp_packet
from exifmodern.json_types import JsonArray, JsonValue, json_string_array_or_none
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

__all__ = (
    "build_postscript_dsc_transaction_plan",
    "build_postscript_read_graph",
    "invoke_postscript",
)

_POSTSCRIPT_HEADER_PROBE_SIZE = 256
_POSTSCRIPT_SECTION_SCAN_LIMIT = 16 * 1024 * 1024


def build_postscript_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_postscript_dsc_transaction_plan(data)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"PostScript package-local reader status: {plan.status}")
    diagnostics.extend(
        f"PostScript package-local reader gate: {gate.code}" for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = _postscript_file_tags(source_file, plan.header.document_kind)
    nested_tags, nested_diagnostics = _postscript_nested_tags(
        data,
        plan.header.ps_data_start,
        plan.header.ps_data_end,
    )
    tags.extend(tag for tag in nested_tags if tag.provenance.group == "File")
    emitted_priority_zero_tags: set[str] = set()
    for ordinal, comment in enumerate(plan.comments):
        name = _postscript_tag_name(comment.tag)
        if comment.priority_zero_first_wins and name in emitted_priority_zero_tags:
            continue
        emitted_priority_zero_tags.add(name)
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(comment.decoded_value),
                provenance=_provenance(
                    group="PostScript",
                    table_name="Image::ExifTool::PostScript::Main",
                    tag_id=comment.tag,
                    evidence_ids=comment.evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    tags.extend(tag for tag in nested_tags if tag.provenance.group != "File")
    diagnostics.extend(nested_diagnostics)
    tags.extend(
        _postscript_composite_tags(
            plan.bounding_box.derived_width,
            plan.bounding_box.derived_height,
        )
    )
    return _graph(source_file, tags, diagnostics)


def _postscript_tag_name(tag_id: str) -> str:
    if tag_id == "CreationDate":
        return "CreateDate"
    if tag_id == "ModDate":
        return "ModifyDate"
    return tag_id


def _postscript_file_tags(source_file: str, document_kind: str) -> list[ReadTag]:
    if document_kind == "eps":
        values = (
            ("FileType", "EPS", "FileType"),
            ("FileTypeExtension", "eps", "FileTypeExtension"),
            ("MIMEType", "application/postscript", "MIMEType"),
        )
    elif document_kind == "ai":
        values = (
            ("FileType", "AI", "FileType"),
            ("FileTypeExtension", "ai", "FileTypeExtension"),
            ("MIMEType", "application/postscript", "MIMEType"),
        )
    else:
        values = (
            ("FileType", "PS", "FileType"),
            ("FileTypeExtension", "ps", "FileTypeExtension"),
            ("MIMEType", "application/postscript", "MIMEType"),
        )
    return [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::File",
                tag_id=tag_id,
                evidence_ids=(POSTSCRIPT_HEADER_SOURCE,),
            ),
            schema=None,
        )
        for name, value, tag_id in values
    ]


def _postscript_composite_tags(width: int | None, height: int | None) -> list[ReadTag]:
    if width is None or height is None:
        return []
    megapixels = round((width * height) / 1_000_000, 6)
    values: tuple[tuple[str, int | float | str], ...] = (
        ("ImageHeight", height),
        ("ImageWidth", width),
        ("ImageSize", f"{width}x{height}"),
        ("Megapixels", megapixels),
    )
    return [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_provenance(
                group="Composite",
                table_name="Image::ExifTool::PostScript::Composite",
                tag_id=name,
                evidence_ids=(POSTSCRIPT_TAG_TABLE_SOURCE, POSTSCRIPT_IMAGE_SIZE_SOURCE),
            ),
            schema=None,
        )
        for name, value in values
    ]


def _postscript_nested_tags(
    data: bytes,
    ps_data_start: int,
    ps_data_end: int | None,
) -> tuple[list[ReadTag], list[str]]:
    tags: list[ReadTag] = []
    diagnostics: list[str] = []
    for ordinal, block in enumerate(_postscript_nested_blocks(data, ps_data_start, ps_data_end)):
        kind, payload = block
        if kind == "photoshop":
            block_tags, block_diagnostics = _postscript_photoshop_tags(payload, ordinal)
        elif kind == "icc_profile":
            block_tags, block_diagnostics = _postscript_icc_tags(payload, ordinal)
        else:
            block_tags, block_diagnostics = _postscript_xmp_tags(payload, ordinal)
        tags.extend(block_tags)
        diagnostics.extend(block_diagnostics)
    return tags, diagnostics


def _postscript_nested_blocks(
    data: bytes,
    ps_data_start: int,
    ps_data_end: int | None,
) -> list[tuple[str, bytes]]:
    lines = split_physical_lines(data, ps_data_start, ps_data_end)
    blocks: list[tuple[str, bytes]] = []
    mode = ""
    end_token = ""
    payload = bytearray()
    for line in lines:
        if mode:
            if not end_token:
                payload.extend(line.raw)
                if re.search(rb"<\?xpacket end=.(w|r).\?>(\n|\r|$)", line.raw):
                    blocks.append((mode, bytes(payload)))
                    mode = ""
                    payload = bytearray()
                continue
            if re.match(rf"^{re.escape(end_token)}\s*$", line.text, flags=re.IGNORECASE):
                if mode in {"photoshop", "icc_profile"}:
                    blocks.append((mode, bytes.fromhex(payload.decode("ascii"))))
                else:
                    blocks.append((mode, bytes(payload)))
                mode = ""
                end_token = ""
                payload = bytearray()
                continue
            if mode == "xmp":
                payload.extend(line.raw)
            else:
                payload.extend(_hex_text_bytes(line.text))
            continue
        begin = re.match(
            r"^(%{1,2})(Begin|begin)(_xml_packet|Photoshop|ICCProfile)(?::|\s|$)",
            line.text,
            flags=re.IGNORECASE,
        )
        if begin:
            suffix = begin.group(3)
            normalized = suffix.lower().lstrip("_")
            if normalized == "xml_packet":
                mode = "xmp"
            elif normalized == "photoshop":
                mode = "photoshop"
            else:
                mode = "icc_profile"
            end_word = "end" if begin.group(2) == "begin" else "End"
            end_token = f"{begin.group(1)}{end_word}{suffix}"
            payload = bytearray()
            continue
        if line.raw.startswith(b"<?xpacket begin="):
            payload = bytearray(line.raw)
            mode = "xmp"
            end_token = ""
            if re.search(rb"<\?xpacket end=.(w|r).\?>(\n|\r|$)", line.raw):
                blocks.append(("xmp", bytes(payload)))
                mode = ""
                payload = bytearray()
    return blocks


def _hex_text_bytes(text: str) -> bytes:
    return "".join(char for char in text if char in "0123456789ABCDEFabcdef").encode("ascii")


def _postscript_photoshop_tags(payload: bytes, ordinal: int) -> tuple[list[ReadTag], list[str]]:
    diagnostics: list[str] = []
    try:
        values = _postscript_photoshop_values(payload)
    except ValueError as exc:
        return [], [f"PostScript nested Photoshop diagnostic: {exc}"]
    tags: list[ReadTag] = []
    for name, value in values.items():
        tag_value = _postscript_json_scalar_or_string_list(value)
        if tag_value is None:
            continue
        if name == "CurrentIPTCDigest":
            group = "File"
            table_name = "Image::ExifTool::File"
        elif name in _POSTSCRIPT_IPTC_TAG_NAMES:
            group = "IPTC"
            table_name = "Image::ExifTool::IPTC::ApplicationRecord"
        else:
            group = "Photoshop"
            table_name = "Image::ExifTool::Photoshop::Main"
        tags.append(
            _postscript_nested_tag(
                name=name,
                value=tag_value,
                group=group,
                table_name=table_name,
                tag_id=_postscript_photoshop_tag_id(name),
                ordinal=ordinal,
            )
        )
    diagnostics.extend(
        f"PostScript nested metadata extracted: {kind}"
        for kind in ("Photoshop", "IPTC")
        if any(tag.provenance.group == kind for tag in tags)
    )
    return tags, diagnostics


def _postscript_photoshop_values(payload: bytes) -> dict[str, JsonValue]:
    values: dict[str, JsonValue] = {}
    values.update(parse_current_iptc_digest_tags(payload))
    values.update(parse_photoshop_iptc_tags(payload))
    values.update(parse_photoshop_tags(payload))
    values.update(parse_photoshop_resolution_tags(payload))
    values.update(parse_photoshop_print_scale_tags(payload))
    values.update(parse_photoshop_slice_tags(payload))
    values.update(parse_photoshop_version_tags(payload))
    return values


def _postscript_xmp_tags(payload: bytes, ordinal: int) -> tuple[list[ReadTag], list[str]]:
    try:
        values_by_group = parse_xmp_packet(payload)
    except (SyntaxError, ValueError) as exc:
        return [], [f"PostScript nested XMP diagnostic: {exc}"]
    toolkit = _postscript_xmp_toolkit(payload)
    if toolkit is not None:
        values_by_group.setdefault("XMP-x", {})["XMPToolkit"] = toolkit
    tags: list[ReadTag] = []
    for group in _postscript_xmp_group_order(values_by_group):
        values = values_by_group[group]
        for name, value in values.items():
            tag_value = _postscript_json_scalar_or_string_list(value)
            if tag_value is None:
                continue
            tags.append(
                _postscript_nested_tag(
                    name=name,
                    value=tag_value,
                    group=group,
                    table_name=_postscript_xmp_table_name(group),
                    tag_id=name,
                    ordinal=ordinal,
                )
            )
    return tags, ["PostScript nested metadata extracted: XMP"] if tags else []


def _postscript_xmp_group_order(values_by_group: dict[str, dict[str, JsonValue]]) -> list[str]:
    preferred = [
        "XMP-x",
        "XMP-rdf",
        "XMP-photoshop",
        "XMP-xmpBJ",
        "XMP-xmpMM",
        "XMP-xmpRights",
        "XMP-dc",
    ]
    ordered = [group for group in preferred if group in values_by_group]
    ordered.extend(group for group in values_by_group if group not in set(preferred))
    return ordered


def _postscript_xmp_toolkit(payload: bytes) -> str | None:
    match = re.search(rb"\bx:(?:xmp|xap)tk=['\"]([^'\"]+)['\"]", payload)
    if match is None:
        return None
    return match.group(1).decode("utf-8", errors="replace")


def _postscript_icc_tags(payload: bytes, ordinal: int) -> tuple[list[ReadTag], list[str]]:
    try:
        values = {**parse_icc_header_tags(payload), **parse_icc_profile_tags(payload)}
    except ValueError as exc:
        return [], [f"PostScript nested ICC_Profile diagnostic: {exc}"]
    tags: list[ReadTag] = []
    for name, value in values.items():
        tag_value = _postscript_json_scalar_or_string_list(value)
        if tag_value is None:
            continue
        tags.append(
            _postscript_nested_tag(
                name=name,
                value=tag_value,
                group=_postscript_icc_group_name(name),
                table_name=_postscript_icc_table_name(name),
                tag_id=name,
                ordinal=ordinal,
            )
        )
    return tags, ["PostScript nested metadata extracted: ICC_Profile"] if tags else []


def _postscript_nested_tag(
    *,
    name: str,
    value: str | int | float | bool | None | list[str],
    group: str,
    table_name: str,
    tag_id: str,
    ordinal: int,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=_read_value(value),
        provenance=_provenance(
            group=group,
            table_name=table_name,
            tag_id=tag_id,
            evidence_ids=_postscript_nested_sources(group),
            duplicate_instance_ordinal=ordinal,
        ),
        schema=None,
    )


def _postscript_nested_sources(group: str) -> tuple[str, ...]:
    if group == "IPTC":
        return (
            POSTSCRIPT_NESTED_DISPATCH_SOURCE,
            POSTSCRIPT_PHOTOSHOP_SOURCE,
            POSTSCRIPT_IPTC_SOURCE,
        )
    if group.startswith("XMP"):
        return (POSTSCRIPT_NESTED_DISPATCH_SOURCE, POSTSCRIPT_XMP_SOURCE)
    if group.startswith("ICC"):
        return (POSTSCRIPT_NESTED_DISPATCH_SOURCE, POSTSCRIPT_ICC_SOURCE)
    return (POSTSCRIPT_NESTED_DISPATCH_SOURCE, POSTSCRIPT_PHOTOSHOP_SOURCE)


def _postscript_json_scalar_or_string_list(
    value: JsonValue,
) -> str | int | float | bool | None | list[str]:
    if isinstance(value, dict):
        return None
    if isinstance(value, list):
        return _postscript_json_string_array_or_none(value)
    return value


def _postscript_json_string_array_or_none(value: JsonArray) -> list[str] | None:
    return json_string_array_or_none(value)


def _postscript_xmp_table_name(group: str) -> str:
    if group.startswith("XMP-"):
        return f"Image::ExifTool::XMP::{group[4:]}"
    return "Image::ExifTool::XMP::Main"


def _postscript_icc_table_name(name: str) -> str:
    if name in {
        "ProfileCopyright",
        "ProfileDescription",
        "MediaWhitePoint",
        "MediaBlackPoint",
        "RedTRC",
        "GreenTRC",
        "BlueTRC",
        "RedMatrixColumn",
        "GreenMatrixColumn",
        "BlueMatrixColumn",
    }:
        return "Image::ExifTool::ICC_Profile::Main"
    return "Image::ExifTool::ICC_Profile::Header"


def _postscript_icc_group_name(name: str) -> str:
    if _postscript_icc_table_name(name) == "Image::ExifTool::ICC_Profile::Header":
        return "ICC-header"
    return "ICC_Profile"


def _postscript_photoshop_tag_id(name: str) -> str:
    return {
        "CurrentIPTCDigest": "CurrentIPTCDigest",
        "IPTCDigest": "0x0425",
        "XResolution": "0",
        "DisplayedUnitsX": "2",
        "YResolution": "4",
        "DisplayedUnitsY": "6",
        "PrintStyle": "0",
        "PrintPosition": "2",
        "PrintScale": "10",
        "GlobalAngle": "0x040d",
        "GlobalAltitude": "0x0419",
        "CopyrightFlag": "0x040a",
        "URL": "0x040b",
        "URL_List": "0x041e",
    }.get(name, name)


_POSTSCRIPT_IPTC_TAG_NAMES = frozenset(
    {
        "ApplicationRecordVersion",
        "ObjectName",
        "Urgency",
        "Category",
        "SupplementalCategories",
        "Keywords",
        "SpecialInstructions",
        "DateCreated",
        "By-line",
        "By-lineTitle",
        "City",
        "Province-State",
        "Country-PrimaryLocationName",
        "OriginalTransmissionReference",
        "Headline",
        "Credit",
        "Source",
        "CopyrightNotice",
        "Caption-Abstract",
        "Writer-Editor",
    }
)


def invoke_postscript(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_postscript_read_graph(_read_postscript_sections(path), source_file)


def _read_postscript_sections(path: Path) -> bytes:
    """Read bounded DSC/nested metadata sections like PostScript.pm's chunk loop."""
    with path.open("rb") as file:
        header = file.read(_POSTSCRIPT_HEADER_PROBE_SIZE)
        file.seek(0)
        body = file.read(_POSTSCRIPT_SECTION_SCAN_LIMIT)
    if body.startswith(header):
        return body
    return header + body


_POSTSCRIPT_BUILDER = "exifmodern.formats.postscript:invoke_postscript"

SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="postscript",
        builder_ref=_POSTSCRIPT_BUILDER,
        patterns=(Pattern(0, b"%!PS"),),
    ),
    Signature(
        format_id="postscript/dos_eps",
        builder_ref=_POSTSCRIPT_BUILDER,
        patterns=(Pattern(0, b"\xc5\xd0\xd3\xc6"),),
    ),
)


install_evidence_reference_compat(globals())
