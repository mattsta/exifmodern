"""Source-backed MWG Composite read derivation.

The rules here mirror the read-side Composite definitions in ExifTool's
``lib/Image/ExifTool/MWG.pm`` for the focused MWG test trajectory.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exifmodern.formats.jpeg.container import read_jpeg_segment_probes
from exifmodern.media_source import FileMediaSource
from exifmodern.read_graph import ReadGraph, ReadTag, TagProvenance, TagValue

type MwgValue = str | int | float | bool | None | list[str] | list[int] | list[float] | list[bool]
type MwgSourceTag = tuple[str, str]
type MwgBlockerCode = Literal["missing_required_mwg_source"]

MWG_TABLE_NAME = "Image::ExifTool::MWG::Composite"
CURRENT_IPTC_DIGEST = ("File", "CurrentIPTCDigest")
STORED_IPTC_DIGEST = ("Photoshop", "IPTCDigest")
IPTC_GROUPS = frozenset(("IPTC",))
EXIF_IFD0_GROUPS = frozenset(("IFD0",))
EXIF_SUBIFD_GROUPS = frozenset(("ExifIFD",))
COMPOSITE_GROUPS = frozenset(("Composite",))
XMP_DC_GROUPS = frozenset(("XMP-dc",))
XMP_PHOTOSHOP_GROUPS = frozenset(("XMP-photoshop",))
XMP_XMP_GROUPS = frozenset(("XMP-xmp",))
XMP_IPTC_CORE_GROUPS = frozenset(("XMP-iptcCore",))
XMP_IPTC_EXT_GROUPS = frozenset(("XMP-iptcExt",))
JPEG_APP1 = 0xE1
JPEG_APP13 = 0xED
PHOTOSHOP_APP13_PREAMBLE = b"Photoshop 3.0\x00"
XMP_APP1_PREAMBLE = b"http://ns.adobe.com/xap/1.0/\x00"
PHOTOSHOP_IPTC_RESOURCE_ID = 0x0404
IPTC_APPLICATION_RECORD = 2
IPTC_DATE_CREATED = 55
IPTC_TIME_CREATED = 60
IPTC_DIGITAL_CREATION_DATE = 62
IPTC_DIGITAL_CREATION_TIME = 63
IPTC_SUB_LOCATION = 92


@dataclass(frozen=True)
class MwgDerivedTag:
    name: str
    value: MwgValue
    family_2_group: str
    source_tags: tuple[MwgSourceTag, ...]


@dataclass(frozen=True)
class MwgDerivationBlocker:
    code: MwgBlockerCode
    tag_name: str
    reason: str
    source_tags: tuple[MwgSourceTag, ...]
    source_reference: str


@dataclass(frozen=True)
class MwgDerivationResult:
    graph: ReadGraph
    blockers: tuple[MwgDerivationBlocker, ...]

    @property
    def can_render_exact_mwg(self) -> bool:
        return not self.blockers


@dataclass(frozen=True)
class GraphTagIndex:
    tags: tuple[ReadTag, ...]

    def first_value(self, groups: frozenset[str], name: str) -> MwgValue:
        for tag in self.tags:
            if tag.name == name and tag.provenance.group in groups:
                return mwg_value(tag.value)
        return None

    def has_value(self, groups: frozenset[str], name: str) -> bool:
        return self.first_value(groups, name) is not None

    def digest_value(self, source: MwgSourceTag) -> str | None:
        value = self.first_value(frozenset((source[0],)), source[1])
        return value if isinstance(value, str) else None


def derive_mwg_read_graph(graph: ReadGraph, source_path: Path | None = None) -> MwgDerivationResult:
    supplemental_tags = supplemental_mwg_source_tags(source_path)
    index = GraphTagIndex((*graph.tags, *supplemental_tags))
    derived = tuple(tag for tag in derive_mwg_tags(index) if tag.value is not None)
    blockers = build_source_blockers(index)
    mwg_tags = [read_tag_from_mwg_tag(tag) for tag in derived]
    return MwgDerivationResult(
        graph=ReadGraph(
            schema_version=graph.schema_version,
            generated_at_epoch=int(time.time()),
            source_file=graph.source_file,
            tags=[*graph.tags, *supplemental_tags, *mwg_tags],
            diagnostics=list(graph.diagnostics),
        ),
        blockers=blockers,
    )


def graph_with_mwg_canonical_iptc_composites(
    graph: ReadGraph,
    source_path: Path | None = None,
) -> ReadGraph:
    """Add IPTC date/time composites needed by the MWG.t full-record oracle.

    ExifTool defines these in IPTC.pm, and MWG.pm consumes the same source tags
    when deriving MWG CreateDate/DateTimeOriginal values.
    """

    existing = {(tag.provenance.group, tag.name) for tag in graph.tags}
    supplemental_tags = tuple(
        tag
        for tag in supplemental_mwg_source_tags(source_path)
        if (tag.provenance.group, tag.name) not in existing
    )
    index = GraphTagIndex((*graph.tags, *supplemental_tags))
    tags: list[ReadTag] = []
    if ("Composite", "DateTimeCreated") not in existing:
        value = required_joined_date_time(
            index.first_value(IPTC_GROUPS, "DateCreated"),
            index.first_value(IPTC_GROUPS, "TimeCreated"),
        )
        if value is not None:
            tags.append(iptc_composite_tag("DateTimeCreated", value))
    if ("Composite", "DigitalCreationDateTime") not in existing:
        value = required_joined_date_time(
            index.first_value(IPTC_GROUPS, "DigitalCreationDate"),
            index.first_value(IPTC_GROUPS, "DigitalCreationTime"),
        )
        if value is not None:
            tags.append(iptc_composite_tag("DigitalCreationDateTime", value))
    if not supplemental_tags and not tags:
        return graph
    return ReadGraph(
        schema_version=graph.schema_version,
        generated_at_epoch=graph.generated_at_epoch,
        source_file=graph.source_file,
        tags=[*graph.tags, *supplemental_tags, *tags],
        diagnostics=list(graph.diagnostics),
    )


def iptc_composite_tag(name: str, value: MwgValue) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group="Composite",
            table_name="Image::ExifTool::IPTC::Composite",
            tag_id=name,
            source="iptc-composite-derived",
            family_0_group="Composite",
            family_1_group="Composite",
            family_2_group="Time",
        ),
        schema=None,
    )


def derive_mwg_tags(index: GraphTagIndex) -> tuple[MwgDerivedTag, ...]:
    return (
        MwgDerivedTag(
            "City",
            location_value(index, "City", "City", "LocationShownCity", 32),
            "Location",
            (
                ("IPTC", "City"),
                ("XMP-photoshop", "City"),
                ("XMP-iptcExt", "LocationShownCity"),
            ),
        ),
        MwgDerivedTag(
            "Copyright",
            exif_xmp_iptc_value(
                index,
                ("IFD0", "Copyright"),
                ("IPTC", "CopyrightNotice"),
                ("XMP-dc", "Rights"),
                128,
            ),
            "Author",
            (
                ("IFD0", "Copyright"),
                ("IPTC", "CopyrightNotice"),
                ("XMP-dc", "Rights"),
            ),
        ),
        MwgDerivedTag(
            "Country",
            location_value(
                index,
                "Country-PrimaryLocationName",
                "Country",
                "LocationShownCountryName",
                64,
            ),
            "Location",
            (
                ("IPTC", "Country-PrimaryLocationName"),
                ("XMP-photoshop", "Country"),
                ("XMP-iptcExt", "LocationShownCountryName"),
            ),
        ),
        MwgDerivedTag("CreateDate", create_date_value(index), "Time", create_date_sources()),
        MwgDerivedTag(
            "Creator",
            creator_value(index),
            "Author",
            (("IFD0", "Artist"), ("IPTC", "By-line"), ("XMP-dc", "Creator")),
        ),
        MwgDerivedTag(
            "DateTimeOriginal",
            date_time_original_value(index),
            "Time",
            (
                ("Composite", "SubSecDateTimeOriginal"),
                ("ExifIFD", "DateTimeOriginal"),
                ("IPTC", "DateCreated"),
                ("IPTC", "TimeCreated"),
                ("XMP-photoshop", "DateCreated"),
            ),
        ),
        MwgDerivedTag(
            "Description",
            exif_xmp_iptc_value(
                index,
                ("IFD0", "ImageDescription"),
                ("IPTC", "Caption-Abstract"),
                ("XMP-dc", "Description"),
                2000,
            ),
            "Image",
            (
                ("IFD0", "ImageDescription"),
                ("IPTC", "Caption-Abstract"),
                ("XMP-dc", "Description"),
            ),
        ),
        MwgDerivedTag(
            "Keywords",
            keywords_value(index),
            "Image",
            (("IPTC", "Keywords"), ("XMP-dc", "Subject")),
        ),
        MwgDerivedTag(
            "Location",
            location_value(index, "Sub-location", "Location", "LocationShownSublocation", 32),
            "Location",
            (
                ("IPTC", "Sub-location"),
                ("XMP-iptcCore", "Location"),
                ("XMP-iptcExt", "LocationShownSublocation"),
            ),
        ),
        MwgDerivedTag("ModifyDate", modify_date_value(index), "Time", modify_date_sources()),
        MwgDerivedTag(
            "Orientation",
            index.first_value(EXIF_IFD0_GROUPS, "Orientation"),
            "Image",
            (("IFD0", "Orientation"),),
        ),
        MwgDerivedTag(
            "Rating",
            mwg_rating_value(index),
            "Image",
            (("XMP-xmp", "Rating"),),
        ),
        MwgDerivedTag(
            "State",
            location_value(index, "Province-State", "State", "LocationShownProvinceState", 32),
            "Location",
            (
                ("IPTC", "Province-State"),
                ("XMP-photoshop", "State"),
                ("XMP-iptcExt", "LocationShownProvinceState"),
            ),
        ),
    )


def read_tag_from_mwg_tag(tag: MwgDerivedTag) -> ReadTag:
    return ReadTag(
        name=tag.name,
        value=tag.value,
        provenance=TagProvenance(
            group="Composite",
            table_name=MWG_TABLE_NAME,
            tag_id=tag.name,
            source="mwg-composite-derived",
            family_1_group="MWG",
            family_2_group=tag.family_2_group,
        ),
        schema=None,
    )


def supplemental_mwg_source_tags(source_path: Path | None) -> tuple[ReadTag, ...]:
    if source_path is None or source_path.suffix.lower() not in {".jpg", ".jpeg"}:
        return ()
    try:
        values = supplemental_mwg_values_from_jpeg_file(source_path)
    except OSError, ValueError:
        return ()
    tags: list[ReadTag] = []
    for tag_name, value in values.iptc_values:
        tags.append(supplemental_source_tag("IPTC", tag_name, value, "mwg-jpeg-app13-iptc"))
    for tag_name, value in values.xmp_values:
        tags.append(supplemental_source_tag("XMP-xmp", tag_name, value, "mwg-jpeg-app1-xmp"))
    return tuple(tags)


def supplemental_source_tag(group: str, name: str, value: MwgValue, source: str) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group=group,
            table_name=f"Image::ExifTool::{group}",
            tag_id=name,
            source=source,
            family_1_group=group,
        ),
        schema=None,
    )


@dataclass(frozen=True)
class SupplementalMwgValues:
    iptc_values: tuple[tuple[str, MwgValue], ...]
    xmp_values: tuple[tuple[str, MwgValue], ...]


def supplemental_mwg_values_from_jpeg(data: bytes) -> SupplementalMwgValues:
    iptc_values: list[tuple[str, MwgValue]] = []
    xmp_values: list[tuple[str, MwgValue]] = []
    for marker, payload in jpeg_segments(data):
        if marker == JPEG_APP13 and payload.startswith(PHOTOSHOP_APP13_PREAMBLE):
            iptc_values.extend(iptc_values_from_photoshop_app13(payload))
        elif marker == JPEG_APP1 and payload.startswith(XMP_APP1_PREAMBLE):
            xmp_values.extend(xmp_values_from_app1(payload[len(XMP_APP1_PREAMBLE) :]))
    return SupplementalMwgValues(tuple(iptc_values), tuple(xmp_values))


def supplemental_mwg_values_from_jpeg_file(path: Path) -> SupplementalMwgValues:
    source = FileMediaSource(path)
    iptc_values: list[tuple[str, MwgValue]] = []
    xmp_values: list[tuple[str, MwgValue]] = []
    prefix_length = max(len(PHOTOSHOP_APP13_PREAMBLE), len(XMP_APP1_PREAMBLE))
    for segment in read_jpeg_segment_probes(path, prefix_length=prefix_length):
        if segment.marker not in {JPEG_APP1, JPEG_APP13}:
            continue
        if segment.marker == JPEG_APP13 and not segment.payload_prefix.startswith(
            PHOTOSHOP_APP13_PREAMBLE
        ):
            continue
        if segment.marker == JPEG_APP1 and not segment.payload_prefix.startswith(XMP_APP1_PREAMBLE):
            continue
        payload = source.read_at(segment.payload_offset, segment.payload_length)
        if segment.marker == JPEG_APP13 and payload.startswith(PHOTOSHOP_APP13_PREAMBLE):
            iptc_values.extend(iptc_values_from_photoshop_app13(payload))
        elif segment.marker == JPEG_APP1 and payload.startswith(XMP_APP1_PREAMBLE):
            xmp_values.extend(xmp_values_from_app1(payload[len(XMP_APP1_PREAMBLE) :]))
    return SupplementalMwgValues(tuple(iptc_values), tuple(xmp_values))


def jpeg_segments(data: bytes) -> tuple[tuple[int, bytes], ...]:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return ()
    segments: list[tuple[int, bytes]] = []
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            break
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0xD9, 0xDA}:
            break
        if offset + 2 > len(data):
            break
        segment_size = int.from_bytes(data[offset : offset + 2], "big")
        offset += 2
        if segment_size < 2:
            break
        payload_size = segment_size - 2
        payload_end = offset + payload_size
        if payload_end > len(data):
            break
        segments.append((marker, data[offset:payload_end]))
        offset = payload_end
    return tuple(segments)


def iptc_values_from_photoshop_app13(payload: bytes) -> tuple[tuple[str, MwgValue], ...]:
    values: list[tuple[str, MwgValue]] = []
    offset = len(PHOTOSHOP_APP13_PREAMBLE)
    while offset + 12 <= len(payload):
        if payload[offset : offset + 4] != b"8BIM":
            break
        resource_id = int.from_bytes(payload[offset + 4 : offset + 6], "big")
        offset += 6
        if offset >= len(payload):
            break
        name_size = payload[offset]
        offset += 1 + name_size
        if offset % 2 == 1:
            offset += 1
        if offset + 4 > len(payload):
            break
        resource_size = int.from_bytes(payload[offset : offset + 4], "big")
        offset += 4
        resource_end = offset + resource_size
        if resource_end > len(payload):
            break
        if resource_id == PHOTOSHOP_IPTC_RESOURCE_ID:
            values.extend(iptc_application_values(payload[offset:resource_end]))
        offset = resource_end + (resource_size % 2)
    return tuple(values)


def iptc_application_values(data: bytes) -> tuple[tuple[str, MwgValue], ...]:
    values: list[tuple[str, MwgValue]] = []
    offset = 0
    while offset + 5 <= len(data):
        if data[offset] != 0x1C:
            offset += 1
            continue
        record = data[offset + 1]
        dataset = data[offset + 2]
        size, value_offset = iptc_dataset_size(data, offset + 3)
        if size is None:
            break
        value_end = value_offset + size
        if value_end > len(data):
            break
        value = decode_iptc_text(data[value_offset:value_end])
        converted = iptc_application_value(dataset, value)
        if record == IPTC_APPLICATION_RECORD and converted is not None:
            values.append(converted)
        offset = value_end
    return tuple(values)


def iptc_dataset_size(data: bytes, offset: int) -> tuple[int | None, int]:
    if offset + 2 > len(data):
        return None, offset
    size = int.from_bytes(data[offset : offset + 2], "big")
    offset += 2
    if size & 0x8000 == 0:
        return size, offset
    length_size = size & 0x7FFF
    if length_size == 0 or length_size > 4 or offset + length_size > len(data):
        return None, offset
    return int.from_bytes(data[offset : offset + length_size], "big"), offset + length_size


def iptc_application_value(dataset: int, value: str) -> tuple[str, MwgValue] | None:
    if dataset == IPTC_DATE_CREATED:
        return "DateCreated", iptc_date_value(value)
    if dataset == IPTC_TIME_CREATED:
        return "TimeCreated", iptc_time_value(value)
    if dataset == IPTC_DIGITAL_CREATION_DATE:
        return "DigitalCreationDate", iptc_date_value(value)
    if dataset == IPTC_DIGITAL_CREATION_TIME:
        return "DigitalCreationTime", iptc_time_value(value)
    if dataset == IPTC_SUB_LOCATION:
        return "Sub-location", value
    return None


def decode_iptc_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def iptc_date_value(value: str) -> str:
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}:{value[4:6]}:{value[6:8]}"
    return value


def iptc_time_value(value: str) -> str:
    if len(value) >= 6 and value[:6].isdigit():
        suffix = normalized_time_zone(value[6:])
        return f"{value[:2]}:{value[2:4]}:{value[4:6]}{suffix}"
    return value


def normalized_time_zone(value: str) -> str:
    if len(value) == 5 and value[0] in {"-", "+"} and value[1:].isdigit():
        return f"{value[:3]}:{value[3:]}"
    return value


def mwg_rating_value(index: GraphTagIndex) -> MwgValue:
    value = index.first_value(XMP_XMP_GROUPS, "Rating")
    if isinstance(value, str):
        return numeric_xmp_value(value)
    return value


def xmp_values_from_app1(payload: bytes) -> tuple[tuple[str, MwgValue], ...]:
    text = payload.decode("utf-8", errors="replace")
    values: list[tuple[str, MwgValue]] = []
    modify_date = xmp_property_value(text, "ModifyDate")
    if modify_date is not None:
        values.append(("ModifyDate", normalized_xmp_date_time(modify_date)))
    rating = xmp_property_value(text, "Rating")
    if rating is not None:
        values.append(("Rating", numeric_xmp_value(rating)))
    return tuple(values)


def xmp_property_value(text: str, property_name: str) -> str | None:
    attribute = f"xmp:{property_name}="
    attribute_start = text.find(attribute)
    if attribute_start >= 0:
        value_start = attribute_start + len(attribute)
        if value_start < len(text) and text[value_start] in {"'", '"'}:
            quote = text[value_start]
            value_end = text.find(quote, value_start + 1)
            if value_end >= 0:
                return text[value_start + 1 : value_end]
    open_tag = f"<xmp:{property_name}>"
    close_tag = f"</xmp:{property_name}>"
    tag_start = text.find(open_tag)
    if tag_start >= 0:
        value_start = tag_start + len(open_tag)
        value_end = text.find(close_tag, value_start)
        if value_end >= 0:
            return text[value_start:value_end]
    return None


def normalized_xmp_date_time(value: str) -> str:
    text = value.replace("T", " ")
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        text = f"{text[:4]}:{text[5:7]}:{text[8:]}"
    return text


def numeric_xmp_value(value: str) -> str | int | float:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def build_source_blockers(index: GraphTagIndex) -> tuple[MwgDerivationBlocker, ...]:
    blockers: list[MwgDerivationBlocker] = []
    if needs_mwg_jpeg_xmp_dates(index) and not create_date_value(index):
        blockers.append(
            MwgDerivationBlocker(
                code="missing_required_mwg_source",
                tag_name="CreateDate",
                reason=(
                    "MWG.pm CreateDate derives from Composite:SubSecCreateDate, "
                    "EXIF:CreateDate, IPTC digital creation date/time, or "
                    "XMP-xmp:CreateDate; none are present in the modern graph."
                ),
                source_tags=create_date_sources(),
                source_reference="lib/Image/ExifTool/MWG.pm:153-197",
            )
        )
    if needs_mwg_jpeg_xmp_dates(index) and not modify_date_value(index):
        blockers.append(
            MwgDerivationBlocker(
                code="missing_required_mwg_source",
                tag_name="ModifyDate",
                reason=(
                    "MWG.pm ModifyDate derives from Composite:SubSecModifyDate, "
                    "EXIF:ModifyDate, or synchronized XMP-xmp:ModifyDate; none "
                    "are present in the modern graph."
                ),
                source_tags=modify_date_sources(),
                source_reference="lib/Image/ExifTool/MWG.pm:198-220",
            )
        )
    return tuple(blockers)


def needs_mwg_jpeg_xmp_dates(index: GraphTagIndex) -> bool:
    return index.has_value(COMPOSITE_GROUPS, "SubSecDateTimeOriginal") and not index.has_value(
        EXIF_SUBIFD_GROUPS, "CreateDate"
    )


def keywords_value(index: GraphTagIndex) -> MwgValue:
    iptc = index.first_value(IPTC_GROUPS, "Keywords")
    xmp = index.first_value(XMP_DC_GROUPS, "Subject")
    if digest_allows_xmp(index) and xmp is not None:
        return xmp
    return recover_truncated_iptc(iptc, xmp, 64)


def exif_xmp_iptc_value(
    index: GraphTagIndex,
    exif_tag: MwgSourceTag,
    iptc_tag: MwgSourceTag,
    xmp_tag: MwgSourceTag,
    limit: int,
) -> MwgValue:
    exif = index.first_value(frozenset((exif_tag[0],)), exif_tag[1])
    if populated_text(exif):
        return exif
    xmp = index.first_value(frozenset((xmp_tag[0],)), xmp_tag[1])
    if digest_allows_xmp(index) and xmp is not None:
        return xmp
    iptc = index.first_value(frozenset((iptc_tag[0],)), iptc_tag[1])
    return recover_truncated_iptc(iptc, xmp, limit)


def creator_value(index: GraphTagIndex) -> MwgValue:
    exif = index.first_value(EXIF_IFD0_GROUPS, "Artist")
    if populated_text(exif):
        return string_to_mwg_list(exif) if isinstance(exif, str) else exif
    xmp = index.first_value(XMP_DC_GROUPS, "Creator")
    if digest_allows_xmp(index) and xmp is not None:
        return xmp
    iptc = index.first_value(IPTC_GROUPS, "By-line")
    return recover_truncated_iptc(iptc, xmp, 32)


def date_time_original_value(index: GraphTagIndex) -> MwgValue:
    return first_populated(
        index.first_value(COMPOSITE_GROUPS, "SubSecDateTimeOriginal"),
        index.first_value(EXIF_SUBIFD_GROUPS, "DateTimeOriginal"),
        digest_guarded_xmp_value(index, XMP_PHOTOSHOP_GROUPS, "DateCreated"),
        joined_date_time(
            index.first_value(IPTC_GROUPS, "DateCreated"),
            index.first_value(IPTC_GROUPS, "TimeCreated"),
        ),
    )


def create_date_value(index: GraphTagIndex) -> MwgValue:
    return first_populated(
        index.first_value(COMPOSITE_GROUPS, "SubSecCreateDate"),
        index.first_value(EXIF_SUBIFD_GROUPS, "CreateDate"),
        digest_guarded_xmp_value(index, XMP_XMP_GROUPS, "CreateDate"),
        joined_date_time(
            index.first_value(IPTC_GROUPS, "DigitalCreationDate"),
            index.first_value(IPTC_GROUPS, "DigitalCreationTime"),
        ),
    )


def modify_date_value(index: GraphTagIndex) -> MwgValue:
    return first_populated(
        index.first_value(COMPOSITE_GROUPS, "SubSecModifyDate"),
        index.first_value(EXIF_IFD0_GROUPS, "ModifyDate"),
        digest_guarded_xmp_value(index, XMP_XMP_GROUPS, "ModifyDate"),
    )


def location_value(
    index: GraphTagIndex,
    iptc_name: str,
    legacy_xmp_name: str,
    extension_xmp_name: str,
    limit: int,
) -> MwgValue:
    extension_xmp = index.first_value(XMP_IPTC_EXT_GROUPS, extension_xmp_name)
    legacy_xmp = index.first_value(XMP_PHOTOSHOP_GROUPS | XMP_IPTC_CORE_GROUPS, legacy_xmp_name)
    xmp = extension_xmp if extension_xmp is not None else legacy_xmp
    if digest_allows_xmp(index) and xmp is not None:
        return xmp
    iptc = index.first_value(IPTC_GROUPS, iptc_name)
    return recover_truncated_iptc(iptc, xmp, limit)


def digest_guarded_xmp_value(index: GraphTagIndex, groups: frozenset[str], name: str) -> MwgValue:
    value = index.first_value(groups, name)
    if value is not None and digest_allows_xmp(index):
        return value
    return None


def digest_allows_xmp(index: GraphTagIndex) -> bool:
    current = index.digest_value(CURRENT_IPTC_DIGEST)
    stored = index.digest_value(STORED_IPTC_DIGEST)
    return current is None or stored is None or current == stored


def recover_truncated_iptc(iptc: MwgValue, xmp: MwgValue, limit: int) -> MwgValue:
    if xmp is None:
        return iptc
    if isinstance(iptc, list):
        xmp_values = xmp if isinstance(xmp, list) else [xmp]
        recovered: list[str] = []
        for index, value in enumerate(iptc):
            xmp_value = xmp_values[index] if index < len(xmp_values) else None
            recovered_value = recover_truncated_iptc(
                value if isinstance(value, str | int | float | bool) else None,
                xmp_value if isinstance(xmp_value, str | int | float | bool) else None,
                limit,
            )
            if isinstance(recovered_value, str):
                recovered.append(recovered_value)
        return recovered
    if isinstance(iptc, str) and len(iptc) == limit:
        xmp_text = xmp[0] if isinstance(xmp, list) and xmp else xmp
        if isinstance(xmp_text, str) and len(xmp_text) > limit and iptc == xmp_text[:limit]:
            return xmp_text
    return iptc


def string_to_mwg_list(value: str) -> str | list[str]:
    values: list[str] = []
    in_quotes = False
    for item in value.split("; "):
        was_quotes = in_quotes
        token = item
        if not in_quotes and token.startswith('"'):
            in_quotes = True
            token = token[1:]
        if in_quotes and ends_quoted_value(token):
            in_quotes = False
            token = token[:-1]
        token = token.replace('""', '"')
        if was_quotes and values:
            values[-1] = f"{values[-1]}; {token}"
        else:
            values.append(token)
    return values if len(values) > 1 else values[0]


def ends_quoted_value(value: str) -> bool:
    quote_count = 0
    for character in reversed(value):
        if character != '"':
            break
        quote_count += 1
    return quote_count % 2 == 1


def first_populated(*values: MwgValue) -> MwgValue:
    for value in values:
        if populated_text(value) or (not isinstance(value, str) and value is not None):
            return value
    return None


def joined_date_time(date: MwgValue, time_value: MwgValue) -> MwgValue:
    if not isinstance(date, str) or not date:
        return None
    if isinstance(time_value, str) and time_value:
        return f"{date} {time_value}"
    return date


def required_joined_date_time(date: MwgValue, time_value: MwgValue) -> MwgValue:
    if isinstance(date, str) and date and isinstance(time_value, str) and time_value:
        return f"{date} {time_value}"
    return None


def populated_text(value: MwgValue) -> bool:
    return isinstance(value, str) and bool(value.strip(" :"))


def mwg_value(value: TagValue) -> MwgValue:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return None


def create_date_sources() -> tuple[MwgSourceTag, ...]:
    return (
        ("Composite", "SubSecCreateDate"),
        ("ExifIFD", "CreateDate"),
        ("IPTC", "DigitalCreationDate"),
        ("IPTC", "DigitalCreationTime"),
        ("XMP-xmp", "CreateDate"),
    )


def modify_date_sources() -> tuple[MwgSourceTag, ...]:
    return (
        ("Composite", "SubSecModifyDate"),
        ("IFD0", "ModifyDate"),
        ("XMP-xmp", "ModifyDate"),
    )
