"""Source-backed QuickTime ``DEL_GROUP`` atom deletion primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.quicktime.atoms import (
    QuickTimeAtom,
    encode_quicktime_atoms,
    read_quicktime_atoms,
)
from exifmodern.formats.quicktime.metadata_atoms import (
    QT_META_ATOM,
    QT_MOVIE_ATOM,
    QT_TRACK_ATOM,
    QT_USER_DATA_ATOM,
)

QT_XMP_UUID = bytes.fromhex("be7acfcb97a942e89c71999491e3afac")

type QuickTimeDelGroupDeleteBlockerCode = Literal[
    "unsupported_edit_atom_delete",
    "unsupported_main_movie_fragment_delete",
    "unsupported_main_uuid_delete",
    "unsupported_media_atom_delete",
    "unsupported_media_info_atom_delete",
    "unsupported_gen_media_header_atom_delete",
    "unsupported_data_info_atom_delete",
    "unsupported_data_ref_atom_delete",
    "unsupported_meta_atom_delete",
    "unsupported_movie_atom_delete",
    "unsupported_other_meta_atom_delete",
    "unsupported_track_aperture_atom_delete",
    "unsupported_track_atom_delete",
    "unsupported_track_ref_atom_delete",
]
type QuickTimeAtomTraversalClass = Literal["simple", "subdirectory", "unsupported"]


@dataclass(frozen=True)
class QuickTimeDelGroupDeleteSource:
    path: str
    line_start: int
    line_end: int
    symbol: str
    evidence: str


@dataclass(frozen=True)
class QuickTimeDelGroupDeleteBlocker:
    code: QuickTimeDelGroupDeleteBlockerCode
    full_path: str
    atom_type: str
    message: str
    source: QuickTimeDelGroupDeleteSource


@dataclass(frozen=True)
class QuickTimeDelGroupDeleteResult:
    atoms: tuple[QuickTimeAtom, ...]
    changed_atoms: int
    deleted_paths: tuple[str, ...]
    blockers: tuple[QuickTimeDelGroupDeleteBlocker, ...]


QUICKTIME_USERDATA_DEL_GROUP_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/WriteQuickTime.pl",
    line_start=1204,
    line_end=1214,
    symbol="WriteQuickTime UserData DEL_GROUP deletion",
    evidence=(
        "When the UserData delete group is active, WriteQuickTime deletes ItemList "
        "children and UserData atoms that are not subdirectories."
    ),
)
QUICKTIME_USERDATA_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1582,
    line_end=2553,
    symbol="%Image::ExifTool::QuickTime::UserData",
    evidence=(
        "UserData defines writable simple text, numeric, 3GP, Apple, vendor, and "
        "third-party atoms separately from child subdirectories such as Meta, XMP_, "
        "Microsoft Xtra, and maker-note/vendor containers."
    ),
)
QUICKTIME_MOVIE_DEL_GROUP_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/WriteQuickTime.pl",
    line_start=1204,
    line_end=1214,
    symbol="WriteQuickTime generic DEL_GROUP deletion",
    evidence=(
        "When a delete group is active, WriteQuickTime deletes writable atoms that "
        "are not subdirectories while recursing into child atom tables."
    ),
)
QUICKTIME_MOVIE_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1198,
    line_end=1285,
    symbol="%Image::ExifTool::QuickTime::Movie",
    evidence=(
        "Movie defines iods as a simple binary atom separately from structural "
        "subdirectories such as trak, udta, meta, cmov, and meco."
    ),
)
QUICKTIME_MAIN_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=549,
    line_end=699,
    symbol="%Image::ExifTool::QuickTime::Main",
    evidence=(
        "Main defines moov, moof, meta, meco, ftyp, and uuid atom families; "
        "moof recurses to MovieFragment, while uuid has condition-specific "
        "subdirectories plus UUID-Unknown."
    ),
)
QUICKTIME_MOVIE_FRAGMENT_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1290,
    line_end=1325,
    symbol="%Image::ExifTool::QuickTime::MovieFragment",
    evidence=(
        "MovieFragment defines mfhd, traf, and meta subdirectories, but "
        "WriteQuickTime rejects movie fragments before writing."
    ),
)
QUICKTIME_OTHER_META_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=2940,
    line_end=2955,
    symbol="%Image::ExifTool::QuickTime::OtherMeta",
    evidence=(
        "OtherMeta defines only source-enumerated child subdirectories: mere "
        "MetaRelation and meta Meta."
    ),
)
QUICKTIME_TRACK_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1420,
    line_end=1487,
    symbol="%Image::ExifTool::QuickTime::Track",
    evidence=(
        "Track defines child subdirectories such as tkhd, mdia, udta, meta, tref, "
        "tapt, uuid, and meco and comments edts as an edits container containing "
        "elst; atom deletion outside those table entries remains unsupported in "
        "this runtime."
    ),
)
QUICKTIME_EDIT_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=1480,
    line_end=1480,
    symbol="%Image::ExifTool::QuickTime::Track edts comment",
    evidence=("Track comments edts as an edits container containing elst, the edit list atom."),
)
QUICKTIME_MEDIA_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=7215,
    line_end=7234,
    symbol="%Image::ExifTool::QuickTime::Media",
    evidence=(
        "Media defines mdhd, hdlr, and minf as child subdirectories and elng as "
        "a simple ExtendedLanguageTag atom."
    ),
)
QUICKTIME_MEDIA_INFO_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=7287,
    line_end=7322,
    symbol="%Image::ExifTool::QuickTime::MediaInfo",
    evidence=(
        "MediaInfo defines vmhd, smhd, hmhd, dinf, gmhd, hdlr, and stbl as child "
        "subdirectories and nmhd as a simple binary NullMediaHeader atom."
    ),
)
QUICKTIME_GEN_MEDIA_HEADER_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=8267,
    line_end=8278,
    symbol="%Image::ExifTool::QuickTime::GenMediaHeader",
    evidence=(
        "GenMediaHeader defines text as a simple binary atom separately from child "
        "subdirectories such as gmin and tmcd."
    ),
)
QUICKTIME_DATA_INFO_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=8253,
    line_end=8263,
    symbol="%Image::ExifTool::QuickTime::DataInfo",
    evidence=(
        "DataInfo defines dref as the source-enumerated DataRef child and notes "
        "that WriteQuickTime parses dref even though it does not change it."
    ),
)
QUICKTIME_DATA_REF_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=8355,
    line_end=8385,
    symbol="%Image::ExifTool::QuickTime::DataRef",
    evidence=(
        "DataRef defines url, url\\0, and urn entries as media data references; "
        "WriteQuickTime parses this table to decide whether media data is internal, "
        "external, or mixed."
    ),
)
QUICKTIME_TRACK_REF_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=3421,
    line_end=3446,
    symbol="%Image::ExifTool::QuickTime::TrackRef",
    evidence=(
        "TrackRef defines simple int32u track reference atoms such as chap, tmcd, "
        "mpod, cdsc, clcp, fall, folw, forc, scpt, ssrc, and sync."
    ),
)
QUICKTIME_TRACK_APERTURE_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=3450,
    line_end=3474,
    symbol="%Image::ExifTool::QuickTime::TrackAperture",
    evidence=("TrackAperture defines simple fixed32u dimension atoms clef, prof, and enof."),
)
QUICKTIME_META_TABLE_SOURCE = QuickTimeDelGroupDeleteSource(
    path="lib/Image/ExifTool/QuickTime.pm",
    line_start=2807,
    line_end=2955,
    symbol="%Image::ExifTool::QuickTime::Meta",
    evidence=(
        "Meta defines simple binary/value atoms separately from child "
        "subdirectories such as ilst, hdlr, dinf, keys, iprp, iref, xml, and grpl."
    ),
)

MOVIE_SOURCE_BACKED_SIMPLE_ATOMS = frozenset({"iods"})
MOVIE_PRESERVED_SUBDIRECTORY_ATOMS = frozenset(
    {
        "mvhd",
        "trak",
        "udta",
        "meta",
        "uuid",
        "cmov",
        "htka",
        "gps ",
        "meco",
    }
)
OTHER_META_PRESERVED_SUBDIRECTORY_ATOMS = frozenset({"mere", "meta"})
META_SOURCE_BACKED_SIMPLE_ATOMS = frozenset({"ipmc", "ipro", "bxml", "pitm", "free", "idat"})
META_PRESERVED_SUBDIRECTORY_ATOMS = frozenset(
    {
        "ilst",
        "hdlr",
        "dinf",
        "iloc",
        "iinf",
        "xml ",
        "keys",
        "iprp",
        "iref",
        "uuid",
        "grpl",
    }
)

USERDATA_SOURCE_BACKED_SIMPLE_ATOMS = frozenset(
    {
        "WLOC",
        "LOOP",
        "SelO",
        "AllF",
        "tnam",
        "hinv",
        "cprt",
        "auth",
        "titl",
        "dscp",
        "perf",
        "gnre",
        "albm",
        "coll",
        "rtng",
        "clsf",
        "kywd",
        "loci",
        "yrrc",
        "urat",
        "name",
        "angl",
        "clfn",
        "clid",
        "cmid",
        "cmnm",
        "date",
        "manu",
        "modl",
        "reel",
        "scen",
        "shot",
        "slno",
        "apmd",
        "kgtt",
        "chpl",
        "CNCV",
        "CNMN",
        "CNFV",
        "pmcc",
        "GoPr",
        "FIRM",
        "LENS",
        "CAME",
        "MUID",
        "FOV\x00",
        "fsid",
        "SNum",
        "ptch",
        "_yaw",
        "roll",
        "_cx_",
        "_cy_",
        "rads",
        "lvlm",
        "Lvlm",
        "adzc",
        "adze",
        "adzm",
        "RTHU",
        "@mak",
        "@mod",
        "@swr",
        "@day",
        "@xyz",
        "vndr",
        "SDLN",
        "cver",
        "vrot",
        "mcvr",
        "nail",
        "info",
        "time",
        "finm",
        "nbpl",
        "ccid",
        "icnu",
        "infu",
        "cdis",
        "albr",
        "cvru",
        "lrcu",
    }
)
USERDATA_SOURCE_BACKED_PREFIXES = ("\xa9",)
USERDATA_PRESERVED_SUBDIRECTORY_ATOMS = frozenset(
    {
        "meta",
        "ptv ",
        "hnti",
        "hinf",
        "XMP_",
        "Xtra",
        "MMA0",
        "MMA1",
        "NCDT",
        "scrn",
        "PANA",
        "LEIC",
        "PENT",
        "PXTH",
        "RDTA",
        "RDTB",
        "RDTC",
        "RDTG",
        "pose",
        "Glam",
        "DcMD",
        "CNTH",
        "CNOP",
        "QVMI",
        "FFMV",
        "MVTG",
        "GPMF",
        "btec",
        "htcb",
        "RDTL",
        "INFO",
        "@sec",
        "smta",
        "tags",
        "TTMD",
        "infi",
        "thmb",
        "PXMN",
        "RICO",
        "RMKN",
        "SIGM",
    }
)
TRACK_PRESERVED_SUBDIRECTORY_ATOMS = frozenset(
    {
        "tkhd",
        "udta",
        "mdia",
        "meta",
        "tref",
        "tapt",
        "edts",
        "uuid",
        "meco",
    }
)
EDIT_SOURCE_BACKED_SIMPLE_ATOMS = frozenset({"elst"})
TRACK_REF_SOURCE_BACKED_SIMPLE_ATOMS = frozenset(
    {"chap", "tmcd", "mpod", "cdsc", "clcp", "fall", "folw", "forc", "scpt", "ssrc", "sync"}
)
TRACK_APERTURE_SOURCE_BACKED_SIMPLE_ATOMS = frozenset({"clef", "prof", "enof"})
MEDIA_SOURCE_BACKED_SIMPLE_ATOMS = frozenset({"elng"})
MEDIA_PRESERVED_SUBDIRECTORY_ATOMS = frozenset({"mdhd", "hdlr", "minf"})
MEDIA_INFO_SOURCE_BACKED_SIMPLE_ATOMS = frozenset({"nmhd"})
MEDIA_INFO_PRESERVED_SUBDIRECTORY_ATOMS = frozenset(
    {"vmhd", "smhd", "hmhd", "dinf", "gmhd", "hdlr", "stbl"}
)
GEN_MEDIA_HEADER_SOURCE_BACKED_SIMPLE_ATOMS = frozenset({"text"})
GEN_MEDIA_HEADER_PRESERVED_SUBDIRECTORY_ATOMS = frozenset({"gmin", "tmcd"})
DATA_INFO_PRESERVED_SUBDIRECTORY_ATOMS = frozenset({"dref"})
DATA_REF_PRESERVED_REFERENCE_ATOMS = frozenset({"url ", "url\x00", "urn ", "alis"})


def delete_source_backed_broad_del_group_atoms(
    atoms: tuple[QuickTimeAtom, ...],
) -> QuickTimeDelGroupDeleteResult:
    rewritten_atoms: list[QuickTimeAtom] = []
    deleted_paths: list[str] = []
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    changed_atoms = 0
    for atom in atoms:
        if atom.atom_type == "meco":
            other_meta_result = delete_other_meta_simple_atoms(atom.payload, ("meco",))
            changed_atoms += other_meta_result.changed_atoms
            deleted_paths.extend(other_meta_result.deleted_paths)
            blockers.extend(other_meta_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(other_meta_result.atoms))
            )
            continue
        if atom.atom_type == "moof":
            blockers.append(unsupported_main_movie_fragment_delete_blocker("moof"))
            rewritten_atoms.append(atom)
            continue
        if atom.atom_type == "uuid":
            if not atom.payload.startswith(QT_XMP_UUID):
                blockers.append(unsupported_main_uuid_delete_blocker("uuid"))
            rewritten_atoms.append(atom)
            continue
        if atom.atom_type != QT_MOVIE_ATOM:
            rewritten_atoms.append(atom)
            continue
        movie_result = delete_movie_userdata_atoms(atom.payload)
        if movie_result.atoms == read_quicktime_atoms(atom.payload):
            rewritten_atoms.append(atom)
        else:
            changed_atoms += 1
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(movie_result.atoms))
            )
        changed_atoms += movie_result.changed_atoms
        deleted_paths.extend(movie_result.deleted_paths)
        blockers.extend(movie_result.blockers)
    return QuickTimeDelGroupDeleteResult(
        atoms=tuple(rewritten_atoms),
        changed_atoms=changed_atoms,
        deleted_paths=tuple(deleted_paths),
        blockers=tuple(blockers),
    )


def delete_movie_userdata_atoms(payload: bytes) -> QuickTimeDelGroupDeleteResult:
    movie_atoms = read_quicktime_atoms(payload)
    rewritten_atoms: list[QuickTimeAtom] = []
    deleted_paths: list[str] = []
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    changed_atoms = 0
    for atom in movie_atoms:
        full_path = f"moov/{atom.atom_type}"
        if atom.atom_type in MOVIE_SOURCE_BACKED_SIMPLE_ATOMS:
            deleted_paths.append(full_path)
            changed_atoms += 1
            continue
        if atom.atom_type == QT_USER_DATA_ATOM:
            user_data_result = delete_userdata_simple_atoms(atom.payload, ("moov", "udta"))
            changed_atoms += user_data_result.changed_atoms
            deleted_paths.extend(user_data_result.deleted_paths)
            blockers.extend(user_data_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(user_data_result.atoms))
            )
            continue
        if atom.atom_type == QT_META_ATOM:
            meta_result = delete_meta_simple_atoms(atom.payload, ("moov", "meta"))
            changed_atoms += meta_result.changed_atoms
            deleted_paths.extend(meta_result.deleted_paths)
            blockers.extend(meta_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(meta_result.atoms))
            )
            continue
        if atom.atom_type == "meco":
            other_meta_result = delete_other_meta_simple_atoms(atom.payload, ("moov", "meco"))
            changed_atoms += other_meta_result.changed_atoms
            deleted_paths.extend(other_meta_result.deleted_paths)
            blockers.extend(other_meta_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(other_meta_result.atoms))
            )
            continue
        if atom.atom_type == QT_TRACK_ATOM:
            track_result = delete_track_userdata_atoms(atom.payload)
            changed_atoms += track_result.changed_atoms
            deleted_paths.extend(track_result.deleted_paths)
            blockers.extend(track_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(track_result.atoms))
            )
            continue
        if atom.atom_type not in MOVIE_PRESERVED_SUBDIRECTORY_ATOMS:
            blockers.append(unsupported_movie_atom_delete_blocker(full_path, atom.atom_type))
        rewritten_atoms.append(atom)
    return QuickTimeDelGroupDeleteResult(
        atoms=tuple(rewritten_atoms),
        changed_atoms=changed_atoms,
        deleted_paths=tuple(deleted_paths),
        blockers=tuple(blockers),
    )


def delete_track_userdata_atoms(payload: bytes) -> QuickTimeDelGroupDeleteResult:
    track_atoms = read_quicktime_atoms(payload)
    rewritten_atoms: list[QuickTimeAtom] = []
    deleted_paths: list[str] = []
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    changed_atoms = 0
    for atom in track_atoms:
        full_path = f"moov/trak/{atom.atom_type}"
        if atom.atom_type == QT_USER_DATA_ATOM:
            user_data_result = delete_userdata_simple_atoms(atom.payload, ("moov", "trak", "udta"))
            changed_atoms += user_data_result.changed_atoms
            deleted_paths.extend(user_data_result.deleted_paths)
            blockers.extend(user_data_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(user_data_result.atoms))
            )
            continue
        if atom.atom_type == QT_META_ATOM:
            meta_result = delete_meta_simple_atoms(atom.payload, ("moov", "trak", "meta"))
            changed_atoms += meta_result.changed_atoms
            deleted_paths.extend(meta_result.deleted_paths)
            blockers.extend(meta_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(meta_result.atoms))
            )
            continue
        if atom.atom_type == "mdia":
            media_result = delete_media_simple_atoms(atom.payload)
            changed_atoms += media_result.changed_atoms
            deleted_paths.extend(media_result.deleted_paths)
            blockers.extend(media_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(media_result.atoms))
            )
            continue
        if atom.atom_type == "tref":
            track_ref_result = delete_track_ref_simple_atoms(atom.payload)
            changed_atoms += track_ref_result.changed_atoms
            deleted_paths.extend(track_ref_result.deleted_paths)
            blockers.extend(track_ref_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(track_ref_result.atoms))
            )
            continue
        if atom.atom_type == "tapt":
            track_aperture_result = delete_track_aperture_simple_atoms(atom.payload)
            changed_atoms += track_aperture_result.changed_atoms
            deleted_paths.extend(track_aperture_result.deleted_paths)
            blockers.extend(track_aperture_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(track_aperture_result.atoms))
            )
            continue
        if atom.atom_type == "edts":
            edit_result = delete_edit_simple_atoms(atom.payload)
            changed_atoms += edit_result.changed_atoms
            deleted_paths.extend(edit_result.deleted_paths)
            blockers.extend(edit_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(edit_result.atoms))
            )
            continue
        if atom.atom_type == "meco":
            other_meta_result = delete_other_meta_simple_atoms(
                atom.payload,
                ("moov", "trak", "meco"),
            )
            changed_atoms += other_meta_result.changed_atoms
            deleted_paths.extend(other_meta_result.deleted_paths)
            blockers.extend(other_meta_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(other_meta_result.atoms))
            )
            continue
        if atom.atom_type not in TRACK_PRESERVED_SUBDIRECTORY_ATOMS:
            blockers.append(unsupported_track_atom_delete_blocker(full_path, atom.atom_type))
        rewritten_atoms.append(atom)
    return QuickTimeDelGroupDeleteResult(
        atoms=tuple(rewritten_atoms),
        changed_atoms=changed_atoms,
        deleted_paths=tuple(deleted_paths),
        blockers=tuple(blockers),
    )


def delete_other_meta_simple_atoms(
    payload: bytes,
    parent_path: tuple[str, ...],
) -> QuickTimeDelGroupDeleteResult:
    other_meta_atoms = read_quicktime_atoms(payload)
    rewritten_atoms: list[QuickTimeAtom] = []
    deleted_paths: list[str] = []
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    changed_atoms = 0
    for atom in other_meta_atoms:
        full_path = "/".join((*parent_path, atom.atom_type))
        if atom.atom_type == QT_META_ATOM:
            meta_result = delete_meta_simple_atoms(atom.payload, (*parent_path, "meta"))
            changed_atoms += meta_result.changed_atoms
            deleted_paths.extend(meta_result.deleted_paths)
            blockers.extend(meta_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(meta_result.atoms))
            )
            continue
        if atom.atom_type not in OTHER_META_PRESERVED_SUBDIRECTORY_ATOMS:
            blockers.append(unsupported_other_meta_atom_delete_blocker(full_path, atom.atom_type))
        rewritten_atoms.append(atom)
    return QuickTimeDelGroupDeleteResult(
        atoms=tuple(rewritten_atoms),
        changed_atoms=changed_atoms,
        deleted_paths=tuple(deleted_paths),
        blockers=tuple(blockers),
    )


def delete_edit_simple_atoms(payload: bytes) -> QuickTimeDelGroupDeleteResult:
    edit_atoms = read_quicktime_atoms(payload)
    rewritten_atoms: list[QuickTimeAtom] = []
    deleted_paths: list[str] = []
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    for atom in edit_atoms:
        full_path = f"moov/trak/edts/{atom.atom_type}"
        match classify_edit_atom(atom.atom_type):
            case "simple":
                deleted_paths.append(full_path)
                continue
            case "unsupported":
                blockers.append(unsupported_edit_atom_delete_blocker(full_path, atom.atom_type))
        rewritten_atoms.append(atom)
    return QuickTimeDelGroupDeleteResult(
        atoms=tuple(rewritten_atoms),
        changed_atoms=len(deleted_paths),
        deleted_paths=tuple(deleted_paths),
        blockers=tuple(blockers),
    )


def delete_track_ref_simple_atoms(payload: bytes) -> QuickTimeDelGroupDeleteResult:
    track_ref_atoms = read_quicktime_atoms(payload)
    rewritten_atoms: list[QuickTimeAtom] = []
    deleted_paths: list[str] = []
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    for atom in track_ref_atoms:
        full_path = f"moov/trak/tref/{atom.atom_type}"
        match classify_track_ref_atom(atom.atom_type):
            case "simple":
                deleted_paths.append(full_path)
                continue
            case "unsupported":
                blockers.append(
                    unsupported_track_ref_atom_delete_blocker(full_path, atom.atom_type)
                )
        rewritten_atoms.append(atom)
    return QuickTimeDelGroupDeleteResult(
        atoms=tuple(rewritten_atoms),
        changed_atoms=len(deleted_paths),
        deleted_paths=tuple(deleted_paths),
        blockers=tuple(blockers),
    )


def delete_track_aperture_simple_atoms(payload: bytes) -> QuickTimeDelGroupDeleteResult:
    track_aperture_atoms = read_quicktime_atoms(payload)
    rewritten_atoms: list[QuickTimeAtom] = []
    deleted_paths: list[str] = []
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    for atom in track_aperture_atoms:
        full_path = f"moov/trak/tapt/{atom.atom_type}"
        match classify_track_aperture_atom(atom.atom_type):
            case "simple":
                deleted_paths.append(full_path)
                continue
            case "unsupported":
                blockers.append(
                    unsupported_track_aperture_atom_delete_blocker(full_path, atom.atom_type)
                )
        rewritten_atoms.append(atom)
    return QuickTimeDelGroupDeleteResult(
        atoms=tuple(rewritten_atoms),
        changed_atoms=len(deleted_paths),
        deleted_paths=tuple(deleted_paths),
        blockers=tuple(blockers),
    )


def delete_media_simple_atoms(payload: bytes) -> QuickTimeDelGroupDeleteResult:
    media_atoms = read_quicktime_atoms(payload)
    rewritten_atoms: list[QuickTimeAtom] = []
    deleted_paths: list[str] = []
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    changed_atoms = 0
    for atom in media_atoms:
        full_path = f"moov/trak/mdia/{atom.atom_type}"
        match classify_media_atom(atom.atom_type):
            case "simple":
                deleted_paths.append(full_path)
                changed_atoms += 1
                continue
            case "subdirectory":
                if atom.atom_type == "minf":
                    media_info_result = delete_media_info_simple_atoms(atom.payload)
                    changed_atoms += media_info_result.changed_atoms
                    deleted_paths.extend(media_info_result.deleted_paths)
                    blockers.extend(media_info_result.blockers)
                    rewritten_atoms.append(
                        QuickTimeAtom(
                            atom.atom_type,
                            encode_quicktime_atoms(media_info_result.atoms),
                        )
                    )
                    continue
            case "unsupported":
                blockers.append(unsupported_media_atom_delete_blocker(full_path, atom.atom_type))
        rewritten_atoms.append(atom)
    return QuickTimeDelGroupDeleteResult(
        atoms=tuple(rewritten_atoms),
        changed_atoms=changed_atoms,
        deleted_paths=tuple(deleted_paths),
        blockers=tuple(blockers),
    )


def delete_media_info_simple_atoms(payload: bytes) -> QuickTimeDelGroupDeleteResult:
    media_info_atoms = read_quicktime_atoms(payload)
    rewritten_atoms: list[QuickTimeAtom] = []
    deleted_paths: list[str] = []
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    for atom in media_info_atoms:
        full_path = f"moov/trak/mdia/minf/{atom.atom_type}"
        match classify_media_info_atom(atom.atom_type):
            case "simple":
                deleted_paths.append(full_path)
                continue
            case "subdirectory":
                if atom.atom_type == "gmhd":
                    gen_media_header_result = delete_gen_media_header_simple_atoms(atom.payload)
                    deleted_paths.extend(gen_media_header_result.deleted_paths)
                    blockers.extend(gen_media_header_result.blockers)
                    rewritten_atoms.append(
                        QuickTimeAtom(
                            atom.atom_type,
                            encode_quicktime_atoms(gen_media_header_result.atoms),
                        )
                    )
                    continue
                if atom.atom_type == "dinf":
                    data_info_result = preserve_data_info_reference_atoms(atom.payload)
                    deleted_paths.extend(data_info_result.deleted_paths)
                    blockers.extend(data_info_result.blockers)
                    rewritten_atoms.append(
                        QuickTimeAtom(
                            atom.atom_type,
                            encode_quicktime_atoms(data_info_result.atoms),
                        )
                    )
                    continue
            case "unsupported":
                blockers.append(
                    unsupported_media_info_atom_delete_blocker(full_path, atom.atom_type)
                )
        rewritten_atoms.append(atom)
    return QuickTimeDelGroupDeleteResult(
        atoms=tuple(rewritten_atoms),
        changed_atoms=len(deleted_paths),
        deleted_paths=tuple(deleted_paths),
        blockers=tuple(blockers),
    )


def delete_gen_media_header_simple_atoms(payload: bytes) -> QuickTimeDelGroupDeleteResult:
    gen_media_header_atoms = read_quicktime_atoms(payload)
    rewritten_atoms: list[QuickTimeAtom] = []
    deleted_paths: list[str] = []
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    for atom in gen_media_header_atoms:
        full_path = f"moov/trak/mdia/minf/gmhd/{atom.atom_type}"
        match classify_gen_media_header_atom(atom.atom_type):
            case "simple":
                deleted_paths.append(full_path)
                continue
            case "unsupported":
                blockers.append(
                    unsupported_gen_media_header_atom_delete_blocker(full_path, atom.atom_type)
                )
        rewritten_atoms.append(atom)
    return QuickTimeDelGroupDeleteResult(
        atoms=tuple(rewritten_atoms),
        changed_atoms=len(deleted_paths),
        deleted_paths=tuple(deleted_paths),
        blockers=tuple(blockers),
    )


def preserve_data_info_reference_atoms(payload: bytes) -> QuickTimeDelGroupDeleteResult:
    return preserve_data_info_reference_atoms_at_path(
        payload,
        ("moov", "trak", "mdia", "minf", "dinf"),
    )


def preserve_data_info_reference_atoms_at_path(
    payload: bytes,
    parent_path: tuple[str, ...],
) -> QuickTimeDelGroupDeleteResult:
    data_info_atoms = read_quicktime_atoms(payload)
    rewritten_atoms: list[QuickTimeAtom] = []
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    for atom in data_info_atoms:
        full_path = "/".join((*parent_path, atom.atom_type))
        if atom.atom_type == "dref":
            data_ref_result = preserve_data_ref_atoms_at_path(atom.payload, (*parent_path, "dref"))
            blockers.extend(data_ref_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_data_ref_payload(data_ref_result.atoms))
            )
            continue
        if atom.atom_type not in DATA_INFO_PRESERVED_SUBDIRECTORY_ATOMS:
            blockers.append(unsupported_data_info_atom_delete_blocker(full_path, atom.atom_type))
        rewritten_atoms.append(atom)
    return QuickTimeDelGroupDeleteResult(
        atoms=tuple(rewritten_atoms),
        changed_atoms=0,
        deleted_paths=(),
        blockers=tuple(blockers),
    )


def preserve_data_ref_atoms(payload: bytes) -> QuickTimeDelGroupDeleteResult:
    return preserve_data_ref_atoms_at_path(
        payload,
        ("moov", "trak", "mdia", "minf", "dinf", "dref"),
    )


def preserve_data_ref_atoms_at_path(
    payload: bytes,
    parent_path: tuple[str, ...],
) -> QuickTimeDelGroupDeleteResult:
    data_ref_atoms = read_data_ref_child_atoms(payload)
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    for atom in data_ref_atoms:
        if atom.atom_type not in DATA_REF_PRESERVED_REFERENCE_ATOMS:
            blockers.append(
                unsupported_data_ref_atom_delete_blocker(
                    "/".join((*parent_path, atom.atom_type)),
                    atom.atom_type,
                )
            )
    return QuickTimeDelGroupDeleteResult(
        atoms=data_ref_atoms,
        changed_atoms=0,
        deleted_paths=(),
        blockers=tuple(blockers),
    )


def read_data_ref_child_atoms(payload: bytes) -> tuple[QuickTimeAtom, ...]:
    if len(payload) < 8:
        return ()
    return read_quicktime_atoms(payload[8:])


def encode_data_ref_payload(atoms: tuple[QuickTimeAtom, ...]) -> bytes:
    return b"\x00\x00\x00\x00" + len(atoms).to_bytes(4, "big") + encode_quicktime_atoms(atoms)


def delete_meta_simple_atoms(
    payload: bytes,
    parent_path: tuple[str, ...],
) -> QuickTimeDelGroupDeleteResult:
    meta_atoms = read_quicktime_atoms(payload)
    rewritten_atoms: list[QuickTimeAtom] = []
    deleted_paths: list[str] = []
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    for atom in meta_atoms:
        full_path = "/".join((*parent_path, atom.atom_type))
        if atom.atom_type in META_SOURCE_BACKED_SIMPLE_ATOMS:
            deleted_paths.append(full_path)
            continue
        if atom.atom_type == "dinf":
            data_info_result = preserve_data_info_reference_atoms_at_path(
                atom.payload,
                (*parent_path, "dinf"),
            )
            blockers.extend(data_info_result.blockers)
            rewritten_atoms.append(
                QuickTimeAtom(atom.atom_type, encode_quicktime_atoms(data_info_result.atoms))
            )
            continue
        if atom.atom_type not in META_PRESERVED_SUBDIRECTORY_ATOMS:
            blockers.append(unsupported_meta_atom_delete_blocker(full_path, atom.atom_type))
        rewritten_atoms.append(atom)
    return QuickTimeDelGroupDeleteResult(
        atoms=tuple(rewritten_atoms),
        changed_atoms=len(deleted_paths),
        deleted_paths=tuple(deleted_paths),
        blockers=tuple(blockers),
    )


def delete_userdata_simple_atoms(
    payload: bytes,
    parent_path: tuple[str, ...],
) -> QuickTimeDelGroupDeleteResult:
    user_data_atoms = read_quicktime_atoms(payload)
    rewritten_atoms: list[QuickTimeAtom] = []
    deleted_paths: list[str] = []
    blockers: list[QuickTimeDelGroupDeleteBlocker] = []
    for atom in user_data_atoms:
        full_path = "/".join((*parent_path, atom.atom_type))
        if is_source_backed_userdata_simple_atom(atom.atom_type):
            deleted_paths.append(full_path)
            continue
        if atom.atom_type not in USERDATA_PRESERVED_SUBDIRECTORY_ATOMS:
            deleted_paths.append(full_path)
            continue
        rewritten_atoms.append(atom)
    return QuickTimeDelGroupDeleteResult(
        atoms=tuple(rewritten_atoms),
        changed_atoms=len(deleted_paths),
        deleted_paths=tuple(deleted_paths),
        blockers=tuple(blockers),
    )


def is_source_backed_userdata_simple_atom(atom_type: str) -> bool:
    return atom_type in USERDATA_SOURCE_BACKED_SIMPLE_ATOMS or atom_type.startswith(
        USERDATA_SOURCE_BACKED_PREFIXES
    )


def classify_edit_atom(atom_type: str) -> QuickTimeAtomTraversalClass:
    if atom_type in EDIT_SOURCE_BACKED_SIMPLE_ATOMS:
        return "simple"
    return "unsupported"


def classify_track_ref_atom(atom_type: str) -> QuickTimeAtomTraversalClass:
    if atom_type in TRACK_REF_SOURCE_BACKED_SIMPLE_ATOMS:
        return "simple"
    return "unsupported"


def classify_track_aperture_atom(atom_type: str) -> QuickTimeAtomTraversalClass:
    if atom_type in TRACK_APERTURE_SOURCE_BACKED_SIMPLE_ATOMS:
        return "simple"
    return "unsupported"


def classify_media_atom(atom_type: str) -> QuickTimeAtomTraversalClass:
    if atom_type in MEDIA_SOURCE_BACKED_SIMPLE_ATOMS:
        return "simple"
    if atom_type in MEDIA_PRESERVED_SUBDIRECTORY_ATOMS:
        return "subdirectory"
    return "unsupported"


def classify_media_info_atom(atom_type: str) -> QuickTimeAtomTraversalClass:
    if atom_type in MEDIA_INFO_SOURCE_BACKED_SIMPLE_ATOMS:
        return "simple"
    if atom_type in MEDIA_INFO_PRESERVED_SUBDIRECTORY_ATOMS:
        return "subdirectory"
    return "unsupported"


def classify_gen_media_header_atom(atom_type: str) -> QuickTimeAtomTraversalClass:
    if atom_type in GEN_MEDIA_HEADER_SOURCE_BACKED_SIMPLE_ATOMS:
        return "simple"
    if atom_type in GEN_MEDIA_HEADER_PRESERVED_SUBDIRECTORY_ATOMS:
        return "subdirectory"
    return "unsupported"


def unsupported_data_info_atom_delete_blocker(
    full_path: str,
    atom_type: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_data_info_atom_delete",
        full_path=full_path,
        atom_type=atom_type,
        message=(
            "Broad QuickTime -all= preserved this DataInfo atom because this runtime "
            "only recurses the source-enumerated DataRef child; the atom is not in "
            "the implemented QuickTime.pm DataInfo table slice."
        ),
        source=QUICKTIME_DATA_INFO_TABLE_SOURCE,
    )


def unsupported_data_ref_atom_delete_blocker(
    full_path: str,
    atom_type: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_data_ref_atom_delete",
        full_path=full_path,
        atom_type=atom_type,
        message=(
            "Broad QuickTime -all= preserved this DataRef atom because this runtime "
            "only preserves source-enumerated media data reference entries and does "
            "not guess rewrites for unsupported reference types."
        ),
        source=QUICKTIME_DATA_REF_TABLE_SOURCE,
    )


def unsupported_media_atom_delete_blocker(
    full_path: str,
    atom_type: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_media_atom_delete",
        full_path=full_path,
        atom_type=atom_type,
        message=(
            "Broad QuickTime -all= preserved this Media atom because this runtime "
            "only deletes source-enumerated simple Media atoms and recurses "
            "source-enumerated Media subdirectories; the atom is not in the "
            "implemented QuickTime.pm Media table slice."
        ),
        source=QUICKTIME_MEDIA_TABLE_SOURCE,
    )


def unsupported_main_movie_fragment_delete_blocker(
    full_path: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_main_movie_fragment_delete",
        full_path=full_path,
        atom_type="moof",
        message=(
            "Broad QuickTime -all= preserved this MovieFragment atom because "
            "WriteQuickTime explicitly rejects movie fragments during writing; "
            "native deletion through moof is not implemented."
        ),
        source=QUICKTIME_MOVIE_FRAGMENT_TABLE_SOURCE,
    )


def unsupported_main_uuid_delete_blocker(
    full_path: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_main_uuid_delete",
        full_path=full_path,
        atom_type="uuid",
        message=(
            "Broad QuickTime -all= preserved this top-level UUID atom because "
            "QuickTime.pm dispatches uuid by payload-specific conditions and this "
            "runtime only deletes the recognized XMP uuid through the XMP fan-out path."
        ),
        source=QUICKTIME_MAIN_TABLE_SOURCE,
    )


def unsupported_other_meta_atom_delete_blocker(
    full_path: str,
    atom_type: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_other_meta_atom_delete",
        full_path=full_path,
        atom_type=atom_type,
        message=(
            "Broad QuickTime -all= preserved this OtherMeta atom because this runtime "
            "only recurses source-enumerated OtherMeta subdirectories; the atom is not "
            "in the implemented QuickTime.pm OtherMeta table slice."
        ),
        source=QUICKTIME_OTHER_META_TABLE_SOURCE,
    )


def unsupported_edit_atom_delete_blocker(
    full_path: str,
    atom_type: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_edit_atom_delete",
        full_path=full_path,
        atom_type=atom_type,
        message=(
            "Broad QuickTime -all= preserved this Edit atom because this runtime "
            "only deletes source-enumerated simple Edit atoms; the atom is not in "
            "the implemented QuickTime.pm edts table slice."
        ),
        source=QUICKTIME_EDIT_TABLE_SOURCE,
    )


def unsupported_track_ref_atom_delete_blocker(
    full_path: str,
    atom_type: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_track_ref_atom_delete",
        full_path=full_path,
        atom_type=atom_type,
        message=(
            "Broad QuickTime -all= preserved this TrackRef atom because this runtime "
            "only deletes source-enumerated simple TrackRef atoms; the atom is not "
            "in the implemented QuickTime.pm TrackRef table slice."
        ),
        source=QUICKTIME_TRACK_REF_TABLE_SOURCE,
    )


def unsupported_track_aperture_atom_delete_blocker(
    full_path: str,
    atom_type: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_track_aperture_atom_delete",
        full_path=full_path,
        atom_type=atom_type,
        message=(
            "Broad QuickTime -all= preserved this TrackAperture atom because this runtime "
            "only deletes source-enumerated simple TrackAperture atoms; the atom is not "
            "in the implemented QuickTime.pm TrackAperture table slice."
        ),
        source=QUICKTIME_TRACK_APERTURE_TABLE_SOURCE,
    )


def unsupported_media_info_atom_delete_blocker(
    full_path: str,
    atom_type: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_media_info_atom_delete",
        full_path=full_path,
        atom_type=atom_type,
        message=(
            "Broad QuickTime -all= preserved this MediaInfo atom because this runtime "
            "only deletes source-enumerated simple MediaInfo atoms and preserves "
            "source-enumerated structural or offset-sensitive MediaInfo subdirectories; "
            "the atom is not in the implemented QuickTime.pm MediaInfo table slice."
        ),
        source=QUICKTIME_MEDIA_INFO_TABLE_SOURCE,
    )


def unsupported_gen_media_header_atom_delete_blocker(
    full_path: str,
    atom_type: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_gen_media_header_atom_delete",
        full_path=full_path,
        atom_type=atom_type,
        message=(
            "Broad QuickTime -all= preserved this GenMediaHeader atom because this runtime "
            "only deletes source-enumerated simple GenMediaHeader atoms and preserves "
            "source-enumerated structural GenMediaHeader subdirectories; the atom is not "
            "in the implemented QuickTime.pm GenMediaHeader table slice."
        ),
        source=QUICKTIME_GEN_MEDIA_HEADER_TABLE_SOURCE,
    )


def unsupported_track_atom_delete_blocker(
    full_path: str,
    atom_type: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_track_atom_delete",
        full_path=full_path,
        atom_type=atom_type,
        message=(
            "Broad QuickTime -all= preserved this Track atom because this runtime "
            "only recurses source-enumerated Track subdirectories; the atom is not "
            "in the implemented QuickTime.pm Track table slice."
        ),
        source=QUICKTIME_TRACK_TABLE_SOURCE,
    )


def unsupported_movie_atom_delete_blocker(
    full_path: str,
    atom_type: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_movie_atom_delete",
        full_path=full_path,
        atom_type=atom_type,
        message=(
            "Broad QuickTime -all= preserved this Movie atom because this runtime "
            "only deletes source-enumerated simple Movie atoms; the atom is not in "
            "the implemented QuickTime.pm Movie table slice."
        ),
        source=QUICKTIME_MOVIE_TABLE_SOURCE,
    )


def unsupported_meta_atom_delete_blocker(
    full_path: str,
    atom_type: str,
) -> QuickTimeDelGroupDeleteBlocker:
    return QuickTimeDelGroupDeleteBlocker(
        code="unsupported_meta_atom_delete",
        full_path=full_path,
        atom_type=atom_type,
        message=(
            "Broad QuickTime -all= preserved this Meta atom because this runtime "
            "only deletes source-enumerated simple Meta atoms; the atom is not in "
            "the implemented QuickTime.pm Meta table slice."
        ),
        source=QUICKTIME_META_TABLE_SOURCE,
    )
