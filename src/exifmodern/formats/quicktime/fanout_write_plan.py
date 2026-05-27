"""QuickTime broad write fan-out and blocker classification.

This module is deliberately format-local and non-mutating. It plans the
QuickTime metadata subset already handled by ``metadata_writer`` and emits typed
blockers for source-backed surfaces whose byte mutation is not implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.quicktime.metadata_atoms import (
    AUDIO_KEYS_TAGS,
    ITEM_LIST_TAGS,
    KEYS_TAGS,
    USER_DATA_TAGS,
    VIDEO_KEYS_TAGS,
    QuickTimeMetadataDeleteGroup,
    QuickTimeMetadataGroup,
    QuickTimeMetadataValue,
    QuickTimeMetadataWriteMode,
    QuickTimeMetadataWritePlan,
    normalize_quicktime_group,
    parse_quicktime_metadata_assignment,
)
from exifmodern.formats.quicktime.microsoft_metadata import (
    MicrosoftXtraAssignment,
    MicrosoftXtraBlocker,
    classify_microsoft_xtra_assignment,
    merge_microsoft_xtra_assignments,
)
from exifmodern.formats.quicktime.rotation_writer import (
    QuickTimeRotationWritePlan,
    build_quicktime_rotation_write_plan,
)
from exifmodern.formats.quicktime.track_header_dates import (
    QuickTimeHeaderDateTag,
    QuickTimeTrackHeaderDateAssignment,
)

type QuickTimeFanoutBlockerCode = Literal[
    "broad_all_delete_requires_full_atom_tree_writer",
    "xmp_fanout_requires_xmp_atom_writer",
    "microsoft_xtra_writer_pending",
    "three_gp_userdata_writer_pending",
    "unsupported_three_gp_language_country",
    "unsupported_quicktime_write_argument",
    "unsupported_quicktime_api_option",
    "unsupported_microsoft_tag",
    "invalid_microsoft_value",
    "unsupported_itemlist_binary_tag",
    "invalid_quicktime_rotation_value",
    "unsupported_quicktime_rotation_layout",
]
type QuickTimeBlockedSurface = Literal[
    "QuickTime:all",
    "XMP",
    "Microsoft",
    "UserData-3GP",
    "ItemList-Binary",
    "Rotation",
    "argument",
    "api",
]
type QuickTimeExecutableSurface = Literal[
    "ItemList",
    "ItemList-Binary",
    "UserData",
    "Keys",
    "AudioKeys",
    "VideoKeys",
    "XMP",
    "Microsoft",
    "UserData-3GP",
    "MovieHeader",
    "TrackHeader",
    "MediaHeader",
    "Rotation",
]
type QuickTimeFanoutPrerequisite = Literal[
    "complete_quicktime_tag_table_del_group_traversal",
    "quicktime_non_sample_offset_model_repair",
    "mov_xmp_user_data_atom_writer",
    "mp4_xmp_uuid_atom_writer",
    "xmp_packet_serializer",
]


@dataclass(frozen=True)
class QuickTimeFanoutEvidenceAnchor:
    path: str
    line_start: int
    line_end: int
    symbol: str
    evidence: str


@dataclass(frozen=True)
class QuickTimeFanoutBlocker:
    code: QuickTimeFanoutBlockerCode
    argument: str
    surface: QuickTimeBlockedSurface
    message: str
    source: QuickTimeFanoutEvidenceAnchor
    prerequisites: tuple[QuickTimeFanoutPrerequisite, ...] = ()


@dataclass(frozen=True)
class QuickTimeThreeGpAssignment:
    group: QuickTimeMetadataGroup
    name: str
    atom_id: str
    value: str
    source: QuickTimeFanoutEvidenceAnchor
    language_code: str | None = None


@dataclass(frozen=True)
class QuickTimeXmpAssignment:
    property_name: str
    value: str
    source: QuickTimeFanoutEvidenceAnchor


@dataclass(frozen=True)
class QuickTimeItemListBinaryAssignment:
    name: str
    atom_id: str
    path: str
    source: QuickTimeFanoutEvidenceAnchor


@dataclass(frozen=True)
class QuickTimeFanoutWritePlan:
    metadata_plan: QuickTimeMetadataWritePlan
    item_list_binary_assignments: tuple[QuickTimeItemListBinaryAssignment, ...] = ()
    xmp_assignments: tuple[QuickTimeXmpAssignment, ...] = ()
    delete_xmp_atoms: bool = False
    microsoft_assignments: tuple[MicrosoftXtraAssignment, ...] = ()
    three_gp_assignments: tuple[QuickTimeThreeGpAssignment, ...] = ()
    track_header_date_assignments: tuple[QuickTimeTrackHeaderDateAssignment, ...] = ()
    rotation_plan: QuickTimeRotationWritePlan | None = None
    blockers: tuple[QuickTimeFanoutBlocker, ...] = ()
    ignored_api_options: tuple[str, ...] = ()

    @property
    def has_safe_metadata_mutations(self) -> bool:
        return bool(self.metadata_plan.values or self.metadata_plan.delete_groups)

    @property
    def has_blockers(self) -> bool:
        return any(
            blocker.code != "broad_all_delete_requires_full_atom_tree_writer"
            for blocker in self.blockers
        )

    @property
    def executable_surfaces(self) -> tuple[QuickTimeExecutableSurface, ...]:
        surfaces: list[QuickTimeExecutableSurface] = []
        for value in self.metadata_plan.values:
            surfaces.append(value.group)
        for delete_group in self.metadata_plan.delete_groups:
            surfaces.append(delete_group.group)
        if self.item_list_binary_assignments:
            surfaces.append("ItemList-Binary")
        if self.xmp_assignments or self.delete_xmp_atoms:
            surfaces.append("XMP")
        if self.microsoft_assignments:
            surfaces.append("Microsoft")
        if self.three_gp_assignments:
            surfaces.append("UserData-3GP")
        for assignment in self.track_header_date_assignments:
            if assignment.tag_name in {"CreateDate", "ModifyDate"}:
                surfaces.append("MovieHeader")
            elif assignment.tag_name in {"TrackCreateDate", "TrackModifyDate"}:
                surfaces.append("TrackHeader")
            elif assignment.tag_name in {"MediaCreateDate", "MediaModifyDate"}:
                surfaces.append("MediaHeader")
        if self.rotation_plan is not None:
            surfaces.append("Rotation")
        deduped = set(surfaces)
        return tuple(surface for surface in EXECUTABLE_SURFACE_ORDER if surface in deduped)

    @property
    def blocked_surfaces(self) -> tuple[QuickTimeBlockedSurface, ...]:
        return dedupe_surfaces(tuple(blocker.surface for blocker in self.blockers))

    @property
    def blocked_prerequisites(self) -> tuple[QuickTimeFanoutPrerequisite, ...]:
        prerequisites: list[QuickTimeFanoutPrerequisite] = []
        for blocker in self.blockers:
            prerequisites.extend(blocker.prerequisites)
        return dedupe_surfaces(tuple(prerequisites))


QUICKTIME_DIR_MAP_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/WriteQuickTime.pl",
    line_start=15,
    line_end=23,
    symbol="%dirMap",
    evidence="QuickTime writes default to ItemList; Microsoft writes route to UserData/Xtra.",
)

QUICKTIME_DELETE_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/WriteQuickTime.pl",
    line_start=985,
    line_end=1600,
    symbol="WriteQuickTime delete group selection",
    evidence=(
        "WriteQuickTime selects DEL_GROUP per directory, recurses through writable "
        "subdirectories, applies special ItemList/UserData deletion, and deletes "
        "existing writable tag payloads through the normal tag write path."
    ),
)

QUICKTIME_OFFSET_REPAIR_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/WriteQuickTime.pl",
    line_start=1139,
    line_end=2118,
    symbol="WriteQuickTime ChunkOffset repair",
    evidence=(
        "WriteQuickTime records stco/co64/iloc/fragment/index/GPS/CTBO/uuid offset "
        "surfaces while rewriting atoms, then fixes offsets after final mdat positions "
        "are known; this runtime only supports finite top-level stco/co64 sample tables."
    ),
)

QUICKTIME_ITEMLIST_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=3478,
    line_end=3501,
    symbol="%Image::ExifTool::QuickTime::ItemList",
    evidence="ItemList is writable, preferred, and supports alternate-language metadata.",
)

QUICKTIME_ITEMLIST_BINARY_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=3546,
    line_end=3546,
    symbol="ItemList covr",
    evidence="ItemList covr is the writable binary CoverArt tag in the Preview family.",
)

QUICKTIME_ITEMLIST_PREVIEW_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=6618,
    line_end=6619,
    symbol="ItemList tnal/snal",
    evidence="ItemList tnal and snal are binary ThumbnailImage and PreviewImage tags.",
)

QUICKTIME_ITEMLIST_BINARY_FORMAT_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/WriteQuickTime.pl",
    line_start=340,
    line_end=347,
    symbol="FormatQTValue binary image flags",
    evidence=(
        "FormatQTValue marks ItemList data atoms as JPEG, PNG, or BMP by sniffing "
        "the binary payload before falling back to UTF-8."
    ),
)

QUICKTIME_USERDATA_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1582,
    line_end=1604,
    symbol="%Image::ExifTool::QuickTime::UserData",
    evidence="UserData is writable and preferred over Keys for same-named QuickTime tags.",
)

QUICKTIME_KEYS_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=6648,
    line_end=6672,
    symbol="%Image::ExifTool::QuickTime::Keys",
    evidence=(
        "Keys metadata is writable but not preferred when same-named ItemList/UserData tags exist."
    ),
)

QUICKTIME_XMP_FANOUT_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="t/QuickTime.t",
    line_start=96,
    line_end=115,
    symbol="QuickTime tests 8-9",
    evidence="After broad -all=, unqualified artist writes both QuickTime metadata and XMP Artist.",
)

QUICKTIME_PUBLISHER_FANOUT_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="t/QuickTime.t",
    line_start=181,
    line_end=188,
    symbol="QuickTime test 14 Publisher fan-out",
    evidence=(
        "The unqualified Publisher write creates both QuickTime ItemList Publisher "
        "and XMP dc:publisher in the generated MOV target."
    ),
)

QUICKTIME_XMP_LOCATION_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/WriteQuickTime.pl",
    line_start=14,
    line_end=40,
    symbol="%movMap/%mp4Map XMP routing",
    evidence=(
        "ExifTool routes MOV XMP through Movie/UserData/XMP_ and MP4 XMP through "
        "a top-level XMP uuid atom."
    ),
)

QUICKTIME_MICROSOFT_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=2208,
    line_end=2215,
    symbol="QuickTime UserData Xtra",
    evidence="The Xtra UserData atom is the QuickTime surface for Microsoft metadata.",
)

QUICKTIME_3GP_RATING_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1727,
    line_end=1736,
    symbol="UserData rtng",
    evidence="3GP Rating uses atom rtng with IText and ValueConvInv binary packing.",
)

QUICKTIME_3GP_LANG_TEXT_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=324,
    line_end=328,
    symbol="%langText3gp",
    evidence=(
        "3GP UserData language text tags use an IText 6-byte header: "
        "4-byte flags, 2-byte packed language, UTF-8 text, and trailing NUL."
    ),
)

QUICKTIME_3GP_CLASSIFICATION_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1736,
    line_end=1747,
    symbol="UserData clsf",
    evidence=(
        "3GP Classification uses atom clsf with ValueConvInv packing "
        "Entity=XXXX Index=### into entity plus a 16-bit index before IText framing."
    ),
)

QUICKTIME_3GP_LOCATION_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1773,
    line_end=1832,
    symbol="UserData loci",
    evidence="3GP LocationInformation uses atom loci and RawConvInv fixed-point binary packing.",
)

QUICKTIME_3GP_YEAR_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1834,
    line_end=1842,
    symbol="UserData yrrc",
    evidence='3GP Year uses atom yrrc with ValueConvInv pack("Nn",0,value).',
)

QUICKTIME_3GP_USER_RATING_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1843,
    line_end=1852,
    symbol="UserData urat",
    evidence='3GP UserRating uses atom urat with ValueConvInv pack("N2",0,value).',
)

QUICKTIME_TRACK_HEADER_DATE_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1490,
    line_end=1518,
    symbol="%Image::ExifTool::QuickTime::TrackHeader",
    evidence=(
        "TrackHeader stores writable TrackCreateDate and TrackModifyDate in the tkhd "
        "binary data structure, using 64-bit fields when TrackHeaderVersion is 1."
    ),
)

QUICKTIME_MOVIE_HEADER_DATE_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1340,
    line_end=1378,
    symbol="%Image::ExifTool::QuickTime::MovieHeader",
    evidence=(
        "MovieHeader stores writable CreateDate and ModifyDate in the mvhd binary "
        "data structure, using 64-bit fields when MovieHeaderVersion is 1."
    ),
)

QUICKTIME_MEDIA_HEADER_DATE_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=7236,
    line_end=7260,
    symbol="%Image::ExifTool::QuickTime::MediaHeader",
    evidence=(
        "MediaHeader stores writable MediaCreateDate and MediaModifyDate in the mdhd "
        "binary data structure, using 64-bit fields when MediaHeaderVersion is 1."
    ),
)

QUICKTIME_ROTATION_SOURCE = QuickTimeFanoutEvidenceAnchor(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=8629,
    line_end=8641,
    symbol="Composite Rotation WriteAlso",
    evidence=(
        "Composite Rotation is writable, protected, and writes QuickTime MatrixStructure "
        "for all tracks with a non-zero image size."
    ),
)

SAFE_BROAD_DELETE_GROUPS: tuple[QuickTimeMetadataGroup, ...] = (
    "ItemList",
    "UserData",
    "Keys",
    "AudioKeys",
    "VideoKeys",
)
EXECUTABLE_SURFACE_ORDER: tuple[QuickTimeExecutableSurface, ...] = (
    "ItemList",
    "ItemList-Binary",
    "UserData",
    "Keys",
    "AudioKeys",
    "VideoKeys",
    "XMP",
    "Microsoft",
    "UserData-3GP",
    "MovieHeader",
    "TrackHeader",
    "MediaHeader",
    "Rotation",
)

THREE_GP_USERDATA_TAGS: dict[str, tuple[str, QuickTimeFanoutEvidenceAnchor]] = {
    "album": ("albm", QUICKTIME_3GP_LANG_TEXT_SOURCE),
    "author": ("auth", QUICKTIME_3GP_LANG_TEXT_SOURCE),
    "classification": ("clsf", QUICKTIME_3GP_CLASSIFICATION_SOURCE),
    "collectionname": ("coll", QUICKTIME_3GP_LANG_TEXT_SOURCE),
    "copyright": ("cprt", QUICKTIME_3GP_LANG_TEXT_SOURCE),
    "description": ("dscp", QUICKTIME_3GP_LANG_TEXT_SOURCE),
    "genre": ("gnre", QUICKTIME_3GP_LANG_TEXT_SOURCE),
    "locationinformation": ("loci", QUICKTIME_3GP_LOCATION_SOURCE),
    "performer": ("perf", QUICKTIME_3GP_LANG_TEXT_SOURCE),
    "rating": ("rtng", QUICKTIME_3GP_RATING_SOURCE),
    "title": ("titl", QUICKTIME_3GP_LANG_TEXT_SOURCE),
    "userrating": ("urat", QUICKTIME_3GP_USER_RATING_SOURCE),
    "year": ("yrrc", QUICKTIME_3GP_YEAR_SOURCE),
}

ITEM_LIST_BINARY_TAGS: dict[str, tuple[str, QuickTimeFanoutEvidenceAnchor]] = {
    "coverart": ("covr", QUICKTIME_ITEMLIST_BINARY_SOURCE),
    "thumbnailimage": ("tnal", QUICKTIME_ITEMLIST_PREVIEW_SOURCE),
    "previewimage": ("snal", QUICKTIME_ITEMLIST_PREVIEW_SOURCE),
}


def plan_quicktime_fanout_write_args(args: tuple[str, ...]) -> QuickTimeFanoutWritePlan:
    values: list[QuickTimeMetadataValue] = []
    delete_groups: list[QuickTimeMetadataDeleteGroup] = []
    xmp_assignments: list[QuickTimeXmpAssignment] = []
    item_list_binary_assignments: list[QuickTimeItemListBinaryAssignment] = []
    delete_xmp_atoms = False
    microsoft_assignments: list[MicrosoftXtraAssignment] = []
    three_gp_assignments: list[QuickTimeThreeGpAssignment] = []
    track_header_date_assignments: list[QuickTimeTrackHeaderDateAssignment] = []
    rotation_plans: list[QuickTimeRotationWritePlan] = []
    blockers: list[QuickTimeFanoutBlocker] = []
    ignored_api_options: list[str] = []
    write_mode: QuickTimeMetadataWriteMode = "overwrite"
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-api":
            if index + 1 >= len(args):
                blockers.append(unsupported_argument_blocker(arg))
                index += 1
                continue
            api_value = args[index + 1]
            if api_value == "WriteMode=c":
                write_mode = "create"
            elif api_value in {
                "Composite=0",
                "Protected=1",
                "QuickTimeHandler=1",
                "QuickTimeHandler=0",
            }:
                ignored_api_options.append(api_value)
            else:
                blockers.append(unsupported_api_blocker(api_value))
            index += 2
            continue
        if not arg.startswith("-") or ("=" not in arg and "<=" not in arg):
            blockers.append(unsupported_argument_blocker(arg))
            index += 1
            continue
        if "<=" in arg:
            spec, value = arg[1:].split("<=", 1)
            handled_binary = classify_item_list_binary_assignment(
                arg,
                spec,
                value,
                item_list_binary_assignments,
                blockers,
            )
            if not handled_binary:
                blockers.append(unsupported_argument_blocker(arg))
            index += 1
            continue
        spec, value = arg[1:].split("=", 1)
        if spec.lower() == "all" and value == "":
            delete_groups.extend(
                QuickTimeMetadataDeleteGroup(group) for group in SAFE_BROAD_DELETE_GROUPS
            )
            delete_xmp_atoms = True
            blockers.append(broad_all_delete_blocker(arg))
            index += 1
            continue
        handled = classify_assignment(
            arg,
            spec,
            value,
            values,
            delete_groups,
            xmp_assignments,
            microsoft_assignments,
            three_gp_assignments,
            track_header_date_assignments,
            rotation_plans,
            blockers,
        )
        if not handled:
            blockers.append(unsupported_argument_blocker(arg))
        index += 1
    return QuickTimeFanoutWritePlan(
        metadata_plan=QuickTimeMetadataWritePlan(
            values=tuple(values),
            delete_groups=dedupe_delete_groups(tuple(delete_groups)),
            write_mode=write_mode,
        ),
        item_list_binary_assignments=tuple(item_list_binary_assignments),
        xmp_assignments=tuple(xmp_assignments),
        delete_xmp_atoms=delete_xmp_atoms,
        microsoft_assignments=merge_microsoft_xtra_assignments(tuple(microsoft_assignments)),
        three_gp_assignments=tuple(three_gp_assignments),
        track_header_date_assignments=tuple(track_header_date_assignments),
        rotation_plan=rotation_plans[-1] if rotation_plans else None,
        blockers=tuple(blockers),
        ignored_api_options=tuple(ignored_api_options),
    )


def classify_assignment(
    argument: str,
    spec: str,
    value: str,
    values: list[QuickTimeMetadataValue],
    delete_groups: list[QuickTimeMetadataDeleteGroup],
    xmp_assignments: list[QuickTimeXmpAssignment],
    microsoft_assignments: list[MicrosoftXtraAssignment],
    three_gp_assignments: list[QuickTimeThreeGpAssignment],
    track_header_date_assignments: list[QuickTimeTrackHeaderDateAssignment],
    rotation_plans: list[QuickTimeRotationWritePlan],
    blockers: list[QuickTimeFanoutBlocker],
) -> bool:
    group, tag = split_group_tag(spec)
    is_rotation, rotation_plan = classify_rotation_assignment(argument, group, tag, value, blockers)
    if is_rotation:
        if rotation_plan is not None:
            rotation_plans.append(rotation_plan)
        return True
    header_date = classify_header_date_assignment(group, tag, value)
    if header_date is not None:
        track_header_date_assignments.append(header_date)
        return True
    xmp_assignment = classify_explicit_xmp_assignment(group, tag, value)
    if xmp_assignment is not None:
        xmp_assignments.append(xmp_assignment)
        return True
    if group is not None and group.lower() == "microsoft":
        classified = classify_microsoft_xtra_assignment(tag, value)
        if isinstance(classified, MicrosoftXtraBlocker):
            blockers.append(microsoft_blocker(argument, classified))
        else:
            microsoft_assignments.append(classified)
        return True
    if is_three_gp_userdata_assignment(group, tag):
        three_gp = classify_three_gp_userdata_assignment(group, tag, value, blockers, argument)
        if three_gp is not None:
            three_gp_assignments.append(three_gp)
        return True
    if group is None:
        unqualified = canonical_preferred_quicktime_tag(tag)
        if unqualified is None:
            return False
        preferred_group, preferred_tag = unqualified
        values.append(
            QuickTimeMetadataValue(
                group=preferred_group,
                name=preferred_tag,
                value=value if value != "" else None,
            )
        )
        xmp_assignment = xmp_assignment_for_unqualified_tag(tag, value)
        if xmp_assignment is None:
            blockers.append(xmp_fanout_blocker(argument))
        else:
            xmp_assignments.append(xmp_assignment)
        return True
    direct = parse_quicktime_metadata_assignment(spec, value)
    if direct is not None:
        if isinstance(direct, QuickTimeMetadataDeleteGroup):
            delete_groups.append(direct)
        else:
            values.append(direct)
        return True
    parsed_spec = canonical_quicktime_assignment_spec(spec)
    if parsed_spec is None:
        return False
    parsed = parse_quicktime_metadata_assignment(parsed_spec, value)
    if parsed is None:
        return False
    if isinstance(parsed, QuickTimeMetadataDeleteGroup):
        delete_groups.append(parsed)
    else:
        values.append(parsed)
    return True


def classify_item_list_binary_assignment(
    argument: str,
    spec: str,
    path: str,
    item_list_binary_assignments: list[QuickTimeItemListBinaryAssignment],
    blockers: list[QuickTimeFanoutBlocker],
) -> bool:
    group, tag = split_group_tag(spec)
    if group is None or group.lower() == "itemlist" or group.lower() == "quicktime":
        canonical = binary_item_list_tag(tag)
    else:
        return False
    if canonical is None:
        blockers.append(unsupported_itemlist_binary_blocker(argument))
        return True
    name, atom_id, source = canonical
    item_list_binary_assignments.append(
        QuickTimeItemListBinaryAssignment(
            name=name,
            atom_id=atom_id,
            path=path,
            source=source,
        )
    )
    return True


def classify_rotation_assignment(
    argument: str,
    group: str | None,
    tag: str,
    value: str,
    blockers: list[QuickTimeFanoutBlocker],
) -> tuple[bool, QuickTimeRotationWritePlan | None]:
    if tag.lower() != "rotation":
        return False, None
    if group is not None and group.lower() != "quicktime":
        return False, None
    try:
        return True, build_quicktime_rotation_write_plan(value)
    except ValueError:
        blockers.append(invalid_rotation_blocker(argument, value))
        return True, None


def binary_item_list_tag(tag: str) -> tuple[str, str, QuickTimeFanoutEvidenceAnchor] | None:
    tag_name, language_code = split_language_suffix(tag)
    if language_code is not None:
        return None
    atom_source = ITEM_LIST_BINARY_TAGS.get(tag_name.lower())
    if atom_source is None:
        return None
    atom_id, source = atom_source
    if tag_name.lower() == "coverart":
        return "CoverArt", atom_id, source
    if tag_name.lower() == "thumbnailimage":
        return "ThumbnailImage", atom_id, source
    return "PreviewImage", atom_id, source


def canonical_preferred_quicktime_tag(tag: str) -> tuple[QuickTimeMetadataGroup, str] | None:
    tag_tables: tuple[tuple[QuickTimeMetadataGroup, tuple[str, ...]], ...] = (
        ("ItemList", tuple(ITEM_LIST_TAGS)),
        ("UserData", tuple(USER_DATA_TAGS)),
        ("Keys", tuple(KEYS_TAGS)),
    )
    for group, tags in tag_tables:
        canonical_tag = canonical_tag_from_table(tag, tuple(tags))
        if canonical_tag is not None:
            return group, canonical_tag
    return None


def xmp_assignment_for_unqualified_tag(tag: str, value: str) -> QuickTimeXmpAssignment | None:
    tag_lower = tag.lower()
    if tag_lower == "artist":
        return QuickTimeXmpAssignment(
            property_name="XMP-dc:Creator",
            value=value,
            source=QUICKTIME_XMP_FANOUT_SOURCE,
        )
    if tag_lower == "publisher":
        return QuickTimeXmpAssignment(
            property_name="XMP-dc:Publisher",
            value=value,
            source=QUICKTIME_PUBLISHER_FANOUT_SOURCE,
        )
    return None


def classify_explicit_xmp_assignment(
    group: str | None,
    tag: str,
    value: str,
) -> QuickTimeXmpAssignment | None:
    if group is None or group.lower() not in {"xmp", "xmp-dc"}:
        return None
    tag_name, _language_code = split_language_suffix(tag)
    if tag_name.lower() != "title":
        return None
    return QuickTimeXmpAssignment(
        property_name="XMP-dc:Title",
        value=value,
        source=QUICKTIME_XMP_LOCATION_SOURCE,
    )


def classify_header_date_assignment(
    group: str | None,
    tag: str,
    value: str,
) -> QuickTimeTrackHeaderDateAssignment | None:
    track_index: int | None = None
    tag_name = tag
    if group is None or group.lower() == "quicktime":
        tag_name = tag
    elif group.lower().startswith("track") and group[5:].isdigit():
        track_index = int(group[5:])
    else:
        return None
    canonical_tag = quicktime_header_date_tag_from_table(tag_name)
    if canonical_tag is None:
        return None
    if canonical_tag in {"CreateDate", "ModifyDate"} and track_index is not None:
        return None
    return QuickTimeTrackHeaderDateAssignment(
        tag_name=canonical_tag,
        value=value if value != "" else None,
        track_index=track_index,
    )


def quicktime_header_date_tag_from_table(tag: str) -> QuickTimeHeaderDateTag | None:
    canonical_tags: tuple[QuickTimeHeaderDateTag, ...] = (
        "CreateDate",
        "ModifyDate",
        "TrackCreateDate",
        "TrackModifyDate",
        "MediaCreateDate",
        "MediaModifyDate",
    )
    tag_lower = tag.lower()
    for canonical_tag in canonical_tags:
        if canonical_tag.lower() == tag_lower:
            return canonical_tag
    return None


def canonical_quicktime_assignment_spec(spec: str) -> str | None:
    group, tag = split_group_tag(spec)
    if group is None:
        return None
    normalized_group = normalize_quicktime_group(group)
    if normalized_group is None:
        return None
    if tag.lower() == "all":
        return f"{normalized_group}:all"
    if normalized_group == "QuickTime":
        preferred = canonical_preferred_quicktime_tag(tag)
        if preferred is None:
            return None
        return f"QuickTime:{preferred[1]}"
    if normalized_group == "ItemList":
        canonical_tag = canonical_tag_from_table(tag, tuple(ITEM_LIST_TAGS))
    elif normalized_group == "UserData":
        canonical_tag = canonical_tag_from_table(tag, tuple(USER_DATA_TAGS))
    elif normalized_group == "Keys":
        canonical_tag = canonical_tag_from_table(tag, tuple(KEYS_TAGS))
    elif normalized_group == "AudioKeys":
        canonical_tag = canonical_tag_from_table(tag, tuple(AUDIO_KEYS_TAGS))
    else:
        canonical_tag = canonical_tag_from_table(tag, tuple(VIDEO_KEYS_TAGS))
    if canonical_tag is None:
        return None
    return f"{normalized_group}:{canonical_tag}"


def canonical_tag_from_table(tag: str, canonical_tags: tuple[str, ...]) -> str | None:
    tag_name, language_code = split_language_suffix(tag)
    tag_lower = tag_name.lower()
    for canonical_tag in canonical_tags:
        if canonical_tag.lower() != tag_lower:
            continue
        if language_code is None:
            return canonical_tag
        return f"{canonical_tag}-{language_code}"
    return None


def split_language_suffix(tag: str) -> tuple[str, str | None]:
    pieces = tag.split("-")
    if len(pieces) >= 2 and len(pieces[-1]) in {2, 3}:
        language_start = len(pieces) - 1
        if len(pieces) >= 3 and len(pieces[-2]) == 3 and len(pieces[-1]) == 2:
            language_start = len(pieces) - 2
        name = "-".join(pieces[:language_start])
        language_code = "-".join(pieces[language_start:])
        if name:
            return name, language_code
    return tag, None


def split_group_tag(spec: str) -> tuple[str | None, str]:
    parts = spec.split(":", 1)
    if len(parts) == 1:
        return None, spec
    return parts[0], parts[1]


def classify_three_gp_userdata_assignment(
    group: str | None,
    tag: str,
    value: str,
    blockers: list[QuickTimeFanoutBlocker],
    argument: str,
) -> QuickTimeThreeGpAssignment | None:
    if group is None or group.lower() != "userdata":
        return None
    tag_name, language_code = split_language_suffix(tag)
    atom_source = THREE_GP_USERDATA_TAGS.get(tag_name.lower())
    if atom_source is None:
        return None
    atom_id, source = atom_source
    if three_gp_language_has_country(language_code):
        blockers.append(unsupported_three_gp_country_blocker(argument, source))
        return None
    return QuickTimeThreeGpAssignment(
        group="UserData",
        name=tag_name,
        atom_id=atom_id,
        value=value,
        source=source,
        language_code=language_code,
    )


def is_three_gp_userdata_assignment(group: str | None, tag: str) -> bool:
    if group is None or group.lower() != "userdata":
        return False
    tag_name, _language_code = split_language_suffix(tag)
    if canonical_tag_from_table(tag_name, tuple(USER_DATA_TAGS)) is not None:
        return False
    return tag_name.lower() in THREE_GP_USERDATA_TAGS


def three_gp_language_has_country(language_code: str | None) -> bool:
    if language_code is None:
        return False
    return len(language_code.replace("_", "-").split("-")) == 2


def dedupe_delete_groups(
    delete_groups: tuple[QuickTimeMetadataDeleteGroup, ...],
) -> tuple[QuickTimeMetadataDeleteGroup, ...]:
    deduped: list[QuickTimeMetadataDeleteGroup] = []
    seen: set[QuickTimeMetadataGroup] = set()
    for delete_group in delete_groups:
        if delete_group.group in seen:
            continue
        seen.add(delete_group.group)
        deduped.append(delete_group)
    return tuple(deduped)


def dedupe_surfaces[T: str](surfaces: tuple[T, ...]) -> tuple[T, ...]:
    deduped: list[T] = []
    seen: set[T] = set()
    for surface in surfaces:
        if surface in seen:
            continue
        seen.add(surface)
        deduped.append(surface)
    return tuple(deduped)


def broad_all_delete_blocker(argument: str) -> QuickTimeFanoutBlocker:
    return QuickTimeFanoutBlocker(
        code="broad_all_delete_requires_full_atom_tree_writer",
        argument=argument,
        surface="QuickTime:all",
        message=(
            "Broad -all= is only partially covered by the current QuickTime fan-out runtime; "
            "the executable subset is ItemList/UserData/Keys/track-Keys, MOV/MP4 XMP atoms, "
            "source-enumerated simple Movie/Meta/UserData atom deletion, and explicit "
            "Microsoft Xtra and 3GP UserData writes. Supported stco/co64 sample chunk "
            "offset tables are repaired before emitting metadata-size-changing writes, "
            "but ExifTool's full DEL_GROUP traversal and remaining non-sample offset "
            "models are not implemented."
        ),
        source=QUICKTIME_DELETE_SOURCE,
        prerequisites=(
            "complete_quicktime_tag_table_del_group_traversal",
            "quicktime_non_sample_offset_model_repair",
        ),
    )


def xmp_fanout_blocker(argument: str) -> QuickTimeFanoutBlocker:
    return QuickTimeFanoutBlocker(
        code="xmp_fanout_requires_xmp_atom_writer",
        argument=argument,
        surface="XMP",
        message=(
            "ExifTool fans this unqualified tag out to XMP in the QuickTime tests; "
            "the QuickTime-local metadata writer does not serialize XMP packets or mutate "
            "MOV XMP_ / MP4 XMP uuid atoms."
        ),
        source=QUICKTIME_XMP_LOCATION_SOURCE,
        prerequisites=(
            "mov_xmp_user_data_atom_writer",
            "mp4_xmp_uuid_atom_writer",
            "xmp_packet_serializer",
        ),
    )


def microsoft_writer_pending_blocker(argument: str) -> QuickTimeFanoutBlocker:
    return QuickTimeFanoutBlocker(
        code="microsoft_xtra_writer_pending",
        argument=argument,
        surface="Microsoft",
        message=(
            "Microsoft Xtra tag classification is source-backed, but Xtra atom mutation is pending."
        ),
        source=QUICKTIME_MICROSOFT_SOURCE,
    )


def three_gp_writer_pending_blocker(
    argument: str,
    source: QuickTimeFanoutEvidenceAnchor,
) -> QuickTimeFanoutBlocker:
    return QuickTimeFanoutBlocker(
        code="three_gp_userdata_writer_pending",
        argument=argument,
        surface="UserData-3GP",
        message=(
            "3GP UserData tag classification is source-backed, but binary payload "
            "mutation is pending."
        ),
        source=source,
    )


def unsupported_three_gp_country_blocker(
    argument: str,
    source: QuickTimeFanoutEvidenceAnchor,
) -> QuickTimeFanoutBlocker:
    return QuickTimeFanoutBlocker(
        code="unsupported_three_gp_language_country",
        argument=argument,
        surface="UserData-3GP",
        message=(
            "3GP UserData international text atoms use ExifTool's IText language field; "
            "country-code writes are explicitly rejected by the QuickTime writer."
        ),
        source=source,
    )


def unsupported_itemlist_binary_blocker(argument: str) -> QuickTimeFanoutBlocker:
    return QuickTimeFanoutBlocker(
        code="unsupported_itemlist_binary_tag",
        argument=argument,
        surface="ItemList-Binary",
        message=(
            "Only ItemList CoverArt, ThumbnailImage, and PreviewImage file-fed binary "
            "writes are source-backed for this QuickTime fan-out slice."
        ),
        source=QUICKTIME_ITEMLIST_BINARY_FORMAT_SOURCE,
    )


def invalid_rotation_blocker(argument: str, value: str) -> QuickTimeFanoutBlocker:
    return QuickTimeFanoutBlocker(
        code="invalid_quicktime_rotation_value",
        argument=argument,
        surface="Rotation",
        message=(
            f"QuickTime Rotation value {value!r} is not supported; this writer only "
            "accepts ExifTool-compatible quarter-turn values 0, 90, 180, or 270."
        ),
        source=QUICKTIME_ROTATION_SOURCE,
    )


def microsoft_blocker(
    argument: str,
    blocker: MicrosoftXtraBlocker,
) -> QuickTimeFanoutBlocker:
    return QuickTimeFanoutBlocker(
        code=blocker.code,
        argument=argument,
        surface="Microsoft",
        message=blocker.message,
        source=QUICKTIME_MICROSOFT_SOURCE,
    )


def unsupported_api_blocker(api_value: str) -> QuickTimeFanoutBlocker:
    return QuickTimeFanoutBlocker(
        code="unsupported_quicktime_api_option",
        argument=api_value,
        surface="api",
        message="QuickTime fan-out planning does not classify this API option.",
        source=QUICKTIME_DIR_MAP_SOURCE,
    )


def unsupported_argument_blocker(argument: str) -> QuickTimeFanoutBlocker:
    return QuickTimeFanoutBlocker(
        code="unsupported_quicktime_write_argument",
        argument=argument,
        surface="argument",
        message="QuickTime fan-out planning has no source-backed classification for this argument.",
        source=QUICKTIME_DIR_MAP_SOURCE,
    )
