"""MIE metadata readers."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from exifmodern.formats.mie.reader import (
    MIE_HEADER_SOURCE,
    MIE_PROCESS_SOURCE,
    MieReadTag,
    MieScalarValue,
    parse_mie_read_tags,
    parse_mie_tags,
)
from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph, ReadTag

__all__ = [
    "build_mie_read_graph",
    "invoke_mie",
    "parse_mie_read_tags",
    "parse_mie_tags",
]


def build_mie_read_graph(data: bytes, source_file: str) -> ReadGraph:
    # Deferred imports: this module is loaded transitively during
    # `exifmodern.read_graph` initialization (via JPEG trailer mie hook),
    # so importing dispatch_helpers / read_graph at top-level would
    # create a circular import.
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import BinaryTagValue, ReadTag

    diagnostics: list[str] = []
    try:
        parsed = parse_mie_read_tags(data)
    except ValueError as error:
        diagnostics.append(f"MIE package-local reader error: {error}")
        return _graph(source_file, [], diagnostics)
    tags = _file_tags(parsed)
    ordered_parsed = _exiftool_mie_output_order(parsed)
    for ordinal, tag in enumerate(ordered_parsed):
        value = (
            BinaryTagValue(tag.rendered_value, media_type=_binary_media_type(tag.name))
            if isinstance(tag.rendered_value, bytes)
            else _read_value(tag.rendered_value)
        )
        tags.append(
            ReadTag(
                name=tag.name,
                value=value,
                provenance=_provenance(
                    group=tag.group,
                    table_name=tag.source_table,
                    tag_id=tag.tag_id,
                    evidence_ids=tag.evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    tags.extend(_mie_composite_tags(ordered_parsed))
    return _graph(source_file, tags, diagnostics)


def _binary_media_type(tag_name: str) -> str | None:
    if tag_name in {"SubfileData", "ThumbnailImage"}:
        return "image/jpeg"
    return None


def _file_tags(parsed: tuple[MieReadTag, ...]) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    mime = _mie_mime_type(parsed)
    values = (
        ("FileType", "MIE", "FileType"),
        ("FileTypeExtension", "mie", "FileTypeExtension"),
        ("MIMEType", mime, "MIMEType"),
    )
    tags: list[ReadTag] = []
    for name, value, tag_id in values:
        tags.append(
            ReadTag(
                name=name,
                value=_read_value(value),
                provenance=_provenance(
                    group="File",
                    table_name="Image::ExifTool::File",
                    tag_id=tag_id,
                    evidence_ids=(MIE_HEADER_SOURCE, MIE_PROCESS_SOURCE),
                ),
                schema=None,
            )
        )
    return tags


def _mie_mime_type(parsed: tuple[MieReadTag, ...]) -> str:
    for tag in parsed:
        if tag.name == "SubfileMIMEType" and isinstance(tag.rendered_value, str):
            subtype = tag.rendered_value.rsplit("/", 1)[-1].replace("jpeg", "jpeg")
            return f"image/x-mie-{subtype}"
    return "application/x-mie"


_MIE_GROUP_OUTPUT_ORDER: dict[str, int] = {
    "MIE-Main": 0,
    "MIE-Camera": 1,
    "MIE-Flash": 2,
    "MIE-Lens": 3,
    "MIE-Orient": 4,
    "MIE-Doc": 5,
    "MIE-Geo": 6,
    "MIE-Image": 7,
    "MIE-Thumbnail": 8,
}


def _exiftool_mie_output_order(tags: tuple[MieReadTag, ...]) -> tuple[MieReadTag, ...]:
    indexed = tuple(enumerate(tags))
    return tuple(
        tag
        for _, tag in sorted(
            indexed,
            key=lambda item: (_MIE_GROUP_OUTPUT_ORDER.get(item[1].group, 99), item[0]),
        )
    )


def _mie_composite_tags(parsed: tuple[MieReadTag, ...]) -> list[ReadTag]:
    from exifmodern.dispatch_helpers import _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    values = {tag.name: tag.rendered_value for tag in parsed}
    composites: list[tuple[str, int | float | str]] = []
    f_number = _number_value(values.get("FNumber"))
    exposure_time = _number_value(values.get("ExposureTime"))
    iso = _number_value(values.get("ISO"))
    if f_number is not None:
        composites.append(("Aperture", f_number))
    if exposure_time is not None:
        composites.append(("ShutterSpeed", _exposure_time_value(exposure_time)))
    if f_number is not None and exposure_time is not None and iso is not None and exposure_time > 0:
        light_value = (2 * math.log2(f_number)) - math.log2(exposure_time)
        light_value -= math.log2(iso / 100)
        composites.append(("LightValue", round(light_value, 1)))
    image_size = values.get("ImageSize")
    megapixels = _megapixels_value(image_size)
    if megapixels is not None:
        composites.append(("Megapixels", megapixels))
    return [
        ReadTag(
            name=name,
            value=_read_value(value),
            provenance=_provenance(
                group="Composite",
                table_name="Image::ExifTool::Exif::Composite",
                tag_id=name,
                evidence_ids=(MIE_PROCESS_SOURCE,),
            ),
            schema=None,
        )
        for name, value in composites
    ]


def _number_value(value: MieScalarValue | None) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _exposure_time_value(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _megapixels_value(value: MieScalarValue | None) -> float | None:
    if not isinstance(value, str) or "x" not in value:
        return None
    width_text, height_text, *_ = value.split("x")
    if not width_text.isdecimal() or not height_text.isdecimal():
        return None
    megapixels = (int(width_text) * int(height_text)) / 1_000_000
    return round(megapixels, 6)


def invoke_mie(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_mie_read_graph(_read_mie_payload(path, prefix), source_file)


def _read_mie_payload(path: Path, prefix: bytes) -> bytes:
    # MIE.pm's top-level MIE file format is metadata payload, not a media stream
    # with image data after a header. Use an explicit-size file read so public
    # dispatch avoids Path.read_bytes while preserving the parser contract.
    size = path.stat().st_size
    data = bytearray(prefix[:size])
    if len(data) >= size:
        return bytes(data)
    with path.open("rb") as file:
        file.seek(len(data))
        data.extend(file.read(size - len(data)))
    return bytes(data)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="mie/big",
        builder_ref="exifmodern.formats.mie:invoke_mie",
        patterns=(Pattern(0, b"~\x10\x04"), Pattern(4, b"0MIE")),
        notes=("Byte at offset 3 is the variable data_length_code.",),
    ),
    Signature(
        format_id="mie/little",
        builder_ref="exifmodern.formats.mie:invoke_mie",
        patterns=(Pattern(0, b"~\x18\x04"), Pattern(4, b"0MIE")),
        notes=("Byte at offset 3 is the variable data_length_code.",),
    ),
)
