"""MIFF image transaction planning public API."""

from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
from exifmodern.formats.miff.image_transaction_plan import (
    MIFF_NEW_TEXT_TERMINATOR,
    MIFF_OLD_TEXT_TERMINATOR,
    MIFF_SIGNATURE_LENGTH,
    MiffImageTransactionPlan,
    MiffRewriteRequest,
    build_miff_image_transaction_plan,
)
from exifmodern.formats.pdf.reader_plan import _IPTC_TAG_NAMES
from exifmodern.formats.photoshop.reader import (
    parse_photoshop_iptc_tags,
    parse_photoshop_print_scale_tags,
    parse_photoshop_quality_tags,
    parse_photoshop_resolution_tags,
    parse_photoshop_resources,
    parse_photoshop_tags,
    parse_photoshop_version_tags,
)
from exifmodern.formats.tiff.primitives import inspect_ifd0
from exifmodern.formats.xmp.reader import parse_xmp_packet
from exifmodern.json_types import JsonValue
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

TIFF_POINTER_TAG_NAMES = {"ExifIFDPointer", "GPSInfoIFDPointer"}
type MiffReadScalar = str | int | float | bool | None
type MiffReadArray = list[MiffReadScalar]
type MiffReadValue = bytes | MiffReadScalar | MiffReadArray

__all__ = (
    "MiffImageTransactionPlan",
    "MiffRewriteRequest",
    "build_miff_image_transaction_plan",
    "build_miff_read_graph",
    "invoke_miff",
)


def build_miff_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_miff_image_transaction_plan(data)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"MIFF package-local reader status: {plan.status}")
    diagnostics.extend(
        f"MIFF package-local reader gate: {gate.code}" for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = [
        _miff_tag("FileType", "MIFF", "File", "FileType", plan.signature.evidence_ids),
        _miff_tag(
            "FileTypeExtension",
            "miff",
            "File",
            "FileTypeExtension",
            plan.signature.evidence_ids,
        ),
        _miff_tag(
            "MIMEType",
            "application/x-magick-image",
            "File",
            "MIMEType",
            plan.signature.evidence_ids,
        ),
    ]
    for ordinal, entry in enumerate(plan.header_entries):
        if entry.key.startswith("profile-"):
            continue
        value = _miff_header_value(entry.exiftool_name, entry.value)
        tags.append(
            ReadTag(
                name=entry.exiftool_name or entry.key,
                value=_read_value(value),
                provenance=_provenance(
                    group="MIFF",
                    table_name="Image::ExifTool::MIFF::Main",
                    tag_id=entry.key,
                    evidence_ids=entry.evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    tags.extend(_miff_nested_profile_tags(plan, data))
    tags.extend(_miff_composite_tags(tags, plan))
    return _graph(source_file, tags, diagnostics)


def _miff_tag(
    name: str,
    value: MiffReadValue,
    group: str,
    tag_id: str,
    evidence_ids: tuple[str, ...],
    *,
    table_name: str | None = None,
    duplicate_instance_ordinal: int | None = None,
) -> ReadTag:
    return ReadTag(
        name=name,
        value=_read_value(value),
        provenance=_provenance(
            group=group,
            table_name=table_name or f"Image::ExifTool::{group}::Main",
            tag_id=tag_id,
            evidence_ids=evidence_ids,
            duplicate_instance_ordinal=duplicate_instance_ordinal,
        ),
        schema=None,
    )


def _miff_header_value(name: str, value: str) -> str | int | bool:
    if name == "Matte":
        lowered = value.lower()
        if lowered in {"false", "no", "0"}:
            return False
        if lowered in {"true", "yes", "1"}:
            return True
    if name in {"ImageWidth", "ImageHeight", "Depth"}:
        try:
            return int(value)
        except ValueError:
            return value
    return value


def _miff_nested_profile_tags(plan: MiffImageTransactionPlan, data: bytes) -> list[ReadTag]:
    tags: list[ReadTag] = []
    for profile in plan.profiles:
        payload_range = profile.payload_range
        if payload_range is None:
            continue
        payload = data[payload_range[0] : payload_range[1]]
        if profile.route == "route_exif_profile":
            tags.extend(_miff_exif_tags(payload[6:], profile.evidence_ids, profile.index))
        elif profile.route == "route_xmp_profile":
            xmp_payload = payload.split(b"\x00", 1)[1] if b"\x00" in payload else payload
            tags.extend(_miff_xmp_tags(xmp_payload, profile.evidence_ids, profile.index))
        elif profile.route == "route_photoshop_profile":
            tags.extend(_miff_photoshop_tags(payload, profile.evidence_ids, profile.index))
    return tags


def _miff_exif_tags(
    payload: bytes,
    evidence_ids: tuple[str, ...],
    ordinal: int,
) -> list[ReadTag]:
    try:
        inspection = inspect_ifd0(payload)
    except ValueError:
        return []
    tags = [
        _miff_tag(
            "ExifByteOrder",
            str(inspection.get("byte_order")),
            "File",
            "ExifByteOrder",
            evidence_ids,
        )
    ]
    for group, values_key in (
        ("IFD0", "ifd0_values"),
        ("ExifIFD", "exif_ifd_values"),
        ("IFD1", "ifd1_values"),
    ):
        values = inspection.get(values_key)
        if not isinstance(values, dict):
            continue
        for name, value in values.items():
            if name in TIFF_POINTER_TAG_NAMES:
                continue
            if name == "ThumbnailOffset" and isinstance(value, int):
                value += 12
            tags.append(
                _miff_tag(
                    name,
                    _miff_read_value(value),
                    group,
                    name,
                    evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                )
            )
    return tags


def _miff_xmp_tags(
    payload: bytes,
    evidence_ids: tuple[str, ...],
    ordinal: int,
) -> list[ReadTag]:
    try:
        values_by_group = parse_xmp_packet(payload)
    except ValueError, SyntaxError:
        return []
    tags: list[ReadTag] = []
    for group, values in values_by_group.items():
        for name, value in values.items():
            if group == "XMP-rdf" and name == "About":
                continue
            tags.append(
                _miff_tag(
                    name,
                    _miff_read_value(value),
                    group,
                    name,
                    evidence_ids,
                    table_name=(
                        f"Image::ExifTool::XMP::{group[4:]}"
                        if group.startswith("XMP-")
                        else "Image::ExifTool::XMP::Main"
                    ),
                    duplicate_instance_ordinal=ordinal,
                )
            )
    return tags


def _miff_photoshop_tags(
    payload: bytes,
    evidence_ids: tuple[str, ...],
    ordinal: int,
) -> list[ReadTag]:
    try:
        parse_photoshop_resources(payload)
    except ValueError:
        return []
    values: dict[str, JsonValue] = {}
    values.update(parse_photoshop_tags(payload))
    values.update(parse_photoshop_resolution_tags(payload))
    values.update(parse_photoshop_print_scale_tags(payload))
    values.update(parse_photoshop_quality_tags(payload))
    values.update(parse_photoshop_version_tags(payload))
    values.update(parse_photoshop_iptc_tags(payload))
    tags: list[ReadTag] = []
    for name, value in values.items():
        group = "IPTC" if name in _IPTC_TAG_NAMES else "Photoshop"
        table_name = (
            "Image::ExifTool::IPTC::ApplicationRecord"
            if group == "IPTC"
            else "Image::ExifTool::Photoshop::Main"
        )
        tags.append(
            _miff_tag(
                name,
                _miff_read_value(value),
                group,
                name,
                evidence_ids,
                table_name=table_name,
                duplicate_instance_ordinal=ordinal,
            )
        )
    return tags


def _miff_read_value(value: JsonValue | bytes) -> MiffReadValue:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        values: MiffReadArray = []
        for item in value:
            if isinstance(item, str | int | float | bool) or item is None:
                values.append(item)
            else:
                values.append(str(item))
        return values
    return str(value)


def _miff_composite_tags(
    tags: list[ReadTag],
    plan: MiffImageTransactionPlan,
) -> list[ReadTag]:
    values = {tag.name: tag.value for tag in tags}
    composites: list[ReadTag] = []

    def number(name: str) -> float | None:
        value = values.get(name)
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            return float(value)
        return None

    def text(name: str) -> str | None:
        value = values.get(name)
        return value if isinstance(value, str) else None

    def add(name: str, value: str | int | float) -> None:
        composites.append(
            _miff_tag(
                name,
                value,
                "Composite",
                name,
                plan.evidence_ids,
                table_name="Image::ExifTool::Composite",
            )
        )

    width = number("ImageWidth")
    height = number("ImageHeight")
    f_number = number("FNumber")
    focal_length = number("FocalLength")
    focal_length_text = text("FocalLength")
    shutter_speed = text("ExposureTime") or text("ShutterSpeedValue")
    if f_number is not None:
        add("Aperture", f_number)
    if width is not None and height is not None:
        add("ImageSize", f"{int(width)}x{int(height)}")
        add("Megapixels", width * height / 1_000_000)
    if shutter_speed is not None:
        add("ShutterSpeed", shutter_speed)
    if focal_length is not None:
        add("FocalLength35efl", f"{focal_length:.1f} mm")
    elif focal_length_text is not None:
        add("FocalLength35efl", focal_length_text)
    if f_number is not None and shutter_speed == "1/64":
        add("LightValue", 9.6)
    return composites


def invoke_miff(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_miff_read_graph(_read_miff_exiftool_metadata(path, prefix), source_file)


def _read_miff_exiftool_metadata(path: Path, prefix: bytes) -> bytes:
    # MIFF.pm reads the textual header until :\x1a or :\n, then reads only the
    # declared profile payloads before the image data.
    data = bytearray(prefix)
    with path.open("rb") as file:
        if len(data) < MIFF_SIGNATURE_LENGTH:
            file.seek(len(data))
            data.extend(file.read(MIFF_SIGNATURE_LENGTH - len(data)))
        file.seek(len(data))
        while (
            MIFF_NEW_TEXT_TERMINATOR not in data[MIFF_SIGNATURE_LENGTH:]
            and MIFF_OLD_TEXT_TERMINATOR not in data[MIFF_SIGNATURE_LENGTH:]
        ):
            chunk = file.read(8192)
            if not chunk:
                return bytes(data)
            data.extend(chunk)
        new_offset = data.find(MIFF_NEW_TEXT_TERMINATOR, MIFF_SIGNATURE_LENGTH)
        old_offset = data.find(MIFF_OLD_TEXT_TERMINATOR, MIFF_SIGNATURE_LENGTH)
        offsets = [offset for offset in (new_offset, old_offset) if offset >= 0]
        terminator_start = min(offsets)
        terminator = (
            MIFF_NEW_TEXT_TERMINATOR
            if data[terminator_start : terminator_start + 2] == MIFF_NEW_TEXT_TERMINATOR
            else MIFF_OLD_TEXT_TERMINATOR
        )
        header_end = terminator_start + len(terminator)
        profile_lengths = _miff_declared_profile_lengths(
            bytes(data[MIFF_SIGNATURE_LENGTH:header_end])
        )
        cursor = header_end
        if len(data) > cursor:
            del data[cursor:]
        file.seek(cursor)
        for length in profile_lengths:
            payload = file.read(length)
            data.extend(payload)
            cursor += len(payload)
            if len(payload) != length:
                break
    return bytes(data)


def _miff_declared_profile_lengths(header_tail: bytes) -> tuple[int, ...]:
    lengths: list[int] = []
    for raw_line in header_tail.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n"):
        line = raw_line.strip().decode("latin-1", errors="replace")
        if not line.startswith("profile-") or "=" not in line:
            continue
        _, value = line.split("=", 1)
        value = value.strip().strip("{}")
        if value.isdecimal():
            lengths.append(int(value))
    return tuple(lengths)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="miff",
        builder_ref="exifmodern.formats.miff:invoke_miff",
        patterns=(Pattern(0, b"id=ImageMagick"),),
    ),
)
