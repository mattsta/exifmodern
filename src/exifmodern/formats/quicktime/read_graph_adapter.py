"""QuickTime/ISO BMFF public read-graph adapter.

The adapter mirrors ExifTool's top-level ``ProcessMOV`` entry behavior: identify
the file from bounded atom/header data, emit file identity tags, and avoid
loading media payloads such as ``mdat`` during dispatch.
"""

from __future__ import annotations

import math
import struct
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from exifmodern.formats.quicktime.atoms import QT_ATOM_HEADER_SIZE, QT_EXTENDED_ATOM_HEADER_SIZE
from exifmodern.formats.quicktime.metadata_atoms import (
    ITEM_LIST_TAGS,
    KEYS_TAGS,
    USER_DATA_TAGS,
    QuickTimeMetadataTag,
    atom_type_from_key_index,
    parse_item_list_data_atoms,
    parse_keys_payload,
    parse_user_data_text_value,
    unpack_quicktime_language,
)
from exifmodern.formats.tiff.primitives import (
    Endian,
    Ifd,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
    read_entry_value,
    read_exif_ifd_values,
    read_gps_ifd_values,
    read_ifd0_values,
    read_ifd1_values,
)
from exifmodern.json_types import JsonValue
from exifmodern.read_graph import (
    BinaryTagValue,
    ReadGraph,
    ReadTag,
    TagProvenance,
    TagValue,
    add_graph_derived_composite_tags,
    current_dispatch_read_graph_runtime_options,
)

if TYPE_CHECKING:
    from exifmodern.formats.panasonic.read_makernote import PanasonicMakerNoteReadResult
    from exifmodern.formats.sanyo import SanyoVideoMetadataPlan

QUICKTIME_MAX_EAGER_PAYLOAD_BYTES = 32 * 1024 * 1024
QUICKTIME_H264_MAX_SAMPLES = 16
QUICKTIME_H264_MAX_SAMPLE_BYTES = 1024 * 1024
QUICKTIME_H264_MAX_TOTAL_SAMPLE_BYTES = 2 * 1024 * 1024
QUICKTIME_FRAGMENT_AUXILIARY_SAMPLE_BOXES = frozenset({"saio", "saiz", "secn", "senc"})
QUICKTIME_H264_FRAGMENT_TERMINAL_SOURCE_EVIDENCE = (
    "../exiftool/lib/Image/ExifTool/QuickTime.pm lines 1298-1332 define "
    "MovieFragment/TrackFragment routing and identify secn/saio auxiliary sample "
    "encryption boxes inside traf.",
    "../exiftool/lib/Image/ExifTool/QuickTimeStream.pl lines 1304-1455 ProcessSamples "
    "range-checks mdat sample bytes and dispatches H264 NAL units only after sample "
    "offset/size state is resolved.",
)
QUICKTIME_H264_FRAGMENT_TERMINAL_DECISIONS = (
    "quicktime_h264_fragment_auxiliary_encrypted_sample_boxes_blocked",
    "quicktime_h264_fragment_unbounded_or_out_of_mdat_sample_read_blocked",
)
PANASONIC_SOURCE_TABLE = "Image::ExifTool::Panasonic::Main"
QUICKTIME_TOP_LEVEL_ATOMS = frozenset(
    {"free", "skip", "wide", "ftyp", "pnot", "PICT", "pict", "moov", "mdat", "junk", "uuid"}
)
QUICKTIME_CONTAINER_ATOMS = frozenset(
    {
        "moov",
        "moof",
        "trak",
        "traf",
        "mdia",
        "minf",
        "stbl",
        "udta",
        "meta",
        "ilst",
        "edts",
        "dinf",
        "gmhd",
        "tref",
        "tapt",
    }
)
QUICKTIME_MAJOR_BRANDS = {
    "avis": "AV1 Image Sequence (.AVIF)",
    "avio": "AV1 Intra-Only Image (.AVIF)",
    "avc1": "MP4 Base w/ AVC ext [ISO 14496-12:2005]",
    "f4v ": "Video for Adobe Flash Player 9+ (.F4V)",
    "iso2": "MP4 Base Media v2 [ISO 14496-12:2005]",
    "iso3": "MP4 Base Media v3",
    "iso4": "MP4 Base Media v4",
    "iso5": "MP4 Base Media v5",
    "iso6": "MP4 Base Media v6",
    "iso7": "MP4 Base Media v7",
    "iso8": "MP4 Base Media v8",
    "iso9": "MP4 Base Media v9",
    "isom": "MP4 Base Media v1 [IS0 14496-12:2003]",
    "miaf": "Multi-Image Application Format (.AVIF)",
    "M4A ": "Apple iTunes AAC-LC (.M4A) Audio",
    "M4B ": "Apple iTunes AAC-LC (.M4B) Audio Book",
    "M4P ": "Apple iTunes AAC-LC (.M4P) AES Protected Audio",
    "M4V ": "Apple iTunes Video (.M4V) Video",
    "mp41": "MP4 v1 [ISO 14496-1:ch13]",
    "mp42": "MP4 v2 [ISO 14496-14]",
    "qt  ": "Apple QuickTime (.MOV/QT)",
}
QUICKTIME_ITEM_LIST_TAGS = {tag.atom_id: tag for tag in ITEM_LIST_TAGS.values()}
QUICKTIME_ITUNES_INFO_TABLE = "Image::ExifTool::QuickTime::iTunesInfo"
QUICKTIME_USER_DATA_TAGS = {
    **{tag.atom_id: tag for tag in USER_DATA_TAGS.values()},
    "\xa9xyz": QuickTimeMetadataTag(
        "UserData", "GPSCoordinates", "\xa9xyz", item_list_format="gps_iso6709"
    ),
}
QUICKTIME_KEYS_TAGS = {tag.key_id: tag for tag in KEYS_TAGS.values() if tag.key_id is not None}
QUICKTIME_VENDOR_IDS = {
    "appl": "Apple",
    "FFMP": "FFmpeg",
}
QUICKTIME_MOVIE_HEADER_TABLE = "Image::ExifTool::QuickTime::MovieHeader"
QUICKTIME_TRACK_HEADER_TABLE = "Image::ExifTool::QuickTime::TrackHeader"
QUICKTIME_MEDIA_HEADER_TABLE = "Image::ExifTool::QuickTime::MediaHeader"
QUICKTIME_HANDLER_TABLE = "Image::ExifTool::QuickTime::Handler"
QUICKTIME_SAMPLE_TABLE = "Image::ExifTool::QuickTime::SampleTable"
QUICKTIME_TRACK_REF_TABLE = "Image::ExifTool::QuickTime::TrackRef"
QUICKTIME_TRACK_APERTURE_TABLE = "Image::ExifTool::QuickTime::TrackAperture"
QUICKTIME_TCMEDIA_INFO_TABLE = "Image::ExifTool::QuickTime::TCMediaInfo"
QUICKTIME_AUDIO_SAMPLE_DESC_TABLE = "Image::ExifTool::QuickTime::AudioSampleDesc"
QUICKTIME_VISUAL_SAMPLE_DESC_TABLE = "Image::ExifTool::QuickTime::VisualSampleDesc"
QUICKTIME_PREVIEW_TABLE = "Image::ExifTool::QuickTime::Preview"
QUICKTIME_RIGHTS_TABLE = "Image::ExifTool::QuickTime::Rights"
QUICKTIME_STREAM_TABLE = "Image::ExifTool::QuickTime::Stream"
QUICKTIME_KEYS_TABLE = "Image::ExifTool::QuickTime::Keys"
QUICKTIME_XMP_TABLE_PREFIX = "Image::ExifTool::XMP::"
QUICKTIME_GSPHERICAL_TABLE = "Image::ExifTool::Google::GSpherical"
QUICKTIME_TIMED_METADATA_MAX_SAMPLES = 16
QUICKTIME_TIMED_METADATA_MAX_SAMPLE_BYTES = 1024 * 1024
QUICKTIME_SPHERICAL_VIDEO_UUID = bytes.fromhex("ffcc8263f8554a938814587a02521fdd")
QUICKTIME_GRAPHICS_MODES = {
    0x00: "srcCopy",
    0x01: "srcOr",
    0x02: "srcXor",
    0x03: "srcBic",
    0x04: "notSrcCopy",
    0x05: "notSrcOr",
    0x06: "notSrcXor",
    0x07: "notSrcBic",
    0x08: "patCopy",
    0x09: "patOr",
    0x0A: "patXor",
    0x0B: "patBic",
    0x0C: "notPatCopy",
    0x0D: "notPatOr",
    0x0E: "notPatXor",
    0x0F: "notPatBic",
    0x20: "blend",
    0x21: "addPin",
    0x22: "addOver",
    0x23: "subPin",
    0x24: "transparent",
    0x25: "addMax",
    0x26: "subOver",
    0x27: "addMin",
    0x31: "grayishTextOr",
    0x32: "hilite",
    0x40: "ditherCopy",
    0x100: "Alpha",
    0x101: "White Alpha",
}
QUICKTIME_EXTENSION_FILE_TYPES = {
    ".3g2": ("3G2", "3g2", "video/3gpp2"),
    ".3gp": ("3GP", "3gp", "video/3gpp"),
    ".f4v": ("F4V", "f4v", "video/mp4"),
    ".heic": ("HEIC", "heic", "image/heic"),
    ".m4a": ("M4A", "m4a", "audio/mp4"),
    ".m4v": ("M4V", "m4v", "video/x-m4v"),
    ".mov": ("MOV", "mov", "video/quicktime"),
    ".mp4": ("MP4", "mp4", "video/mp4"),
}
QUICKTIME_SAMPLE_TABLE_BINARY_TAGS = {
    "ctts": "CompositionTimeToSample",
    "stsc": "SampleToChunk",
    "stsz": "SampleSizes",
    "stz2": "CompactSampleSizes",
    "stco": "ChunkOffset",
    "co64": "ChunkOffset64",
    "stss": "SyncSampleTable",
    "stsh": "ShadowSyncSampleTable",
    "padb": "SamplePaddingBits",
    "stdp": "SampleDegradationPriority",
    "sdtp": "IdependentAndDisposableSamples",
    "sbgp": "SampleToGroup",
    "sgpd": "SampleGroupDescription",
    "subs": "Sub-sampleInformation",
    "cslg": "CompositionToDecodeTimelineMapping",
    "stps": "PartialSyncSamples",
}
QUICKTIME_SUPPORTED_VIDEO_SAMPLE_CHILDREN = frozenset(
    {"avcC", "hvcC", "btrt", "pasp", "colr", "fiel", "gama", "clap", "esds"}
)
QUICKTIME_SUPPORTED_AUDIO_SAMPLE_CHILDREN = frozenset(
    {"btrt", "wave", "chan", "damr", "esds", "pinf", "sinf", "SA3D"}
)
QUICKTIME_SUPPORTED_HINT_SAMPLE_CHILDREN = frozenset({"tims", "tsro", "snro"})
QUICKTIME_SUPPORTED_META_SAMPLE_CHILDREN = frozenset({"keys", "btrt"})
QUICKTIME_SUPPORTED_OTHER_SAMPLE_CHILDREN = frozenset(
    {"avcC", "esds", "ftab", "name", "mrlh", "mrlv", "mrld"}
)
QUICKTIME_HEVC_PROFILE_IDC = {
    0: "No Profile",
    1: "Main",
    2: "Main 10",
    3: "Main Still Picture",
    4: "Format Range Extensions",
    5: "High Throughput",
    6: "Multiview Main",
    7: "Scalable Main",
    8: "3D Main",
    9: "Screen Content Coding Extensions",
    10: "Scalable Format Range Extensions",
    11: "High Throughput Screen Content Coding Extensions",
}
QUICKTIME_HEVC_CHROMA_FORMAT = {
    0: "Monochrome",
    1: "4:2:0",
    2: "4:2:2",
    3: "4:4:4",
}
QUICKTIME_HEVC_CONSTANT_FRAME_RATE = {
    0: "Unknown",
    1: "Constant Frame Rate",
    2: "Each Temporal Layer is Constant Frame Rate",
}
QUICKTIME_CHANNEL_LAYOUT_FLAGS = {
    0: "UseDescriptions",
    1: "UseBitmap",
    100: "Mono",
    101: "Stereo",
    102: "StereoHeadphones",
    103: "MatrixStereo",
    121: "MPEG_5_1_A",
    126: "MPEG_7_1_A",
    0xFFFF: "Unknown",
}
QUICKTIME_CHANNEL_LABELS = {
    0xFFFFFFFF: "Unknown",
    0: "Unused",
    1: "Left",
    2: "Right",
    3: "Center",
    4: "LFEScreen",
    5: "LeftSurround",
    6: "RightSurround",
    42: "Mono",
    100: "UseCoordinates",
}
QUICKTIME_CHANNEL_TYPE_BITS = (
    "Left",
    "Right",
    "Center",
    "LFEScreen",
    "LeftSurround",
    "RightSurround",
    "LeftCenter",
    "RightCenter",
    "CenterSurround",
    "LeftSurroundDirect",
    "RightSurroundDirect",
    "TopCenterSurround",
    "VerticalHeightLeft",
    "VerticalHeightCenter",
    "VerticalHeightRight",
    "TopBackLeft",
    "TopBackCenter",
    "TopBackRight",
)
QUICKTIME_COLOR_PRIMARIES = {
    1: "BT.709",
    2: "Unspecified",
    4: "BT.470 System M (historical)",
    5: "BT.470 System B, G (historical)",
    6: "BT.601",
    7: "SMPTE 240",
    8: "Generic film (color filters using illuminant C)",
    9: "BT.2020, BT.2100",
    10: "SMPTE 428 (CIE 1931 XYZ)",
    11: "SMPTE RP 431-2",
    12: "SMPTE EG 432-1",
    22: "EBU Tech. 3213-E",
}
QUICKTIME_TRANSFER_CHARACTERISTICS = {
    0: "For future use (0)",
    1: "BT.709",
    2: "Unspecified",
    3: "For future use (3)",
    4: "BT.470 System M (historical)",
    5: "BT.470 System B, G (historical)",
    6: "BT.601",
    7: "SMPTE 240 M",
    8: "Linear",
    9: "Logarithmic (100 : 1 range)",
    10: "Logarithmic (100 * Sqrt(10) : 1 range)",
    11: "IEC 61966-2-4",
    12: "BT.1361",
    13: "sRGB or sYCC",
    14: "BT.2020 10-bit systems",
    15: "BT.2020 12-bit systems",
    16: "SMPTE ST 2084, ITU BT.2100 PQ",
    17: "SMPTE ST 428",
    18: "BT.2100 HLG, ARIB STD-B67",
}
QUICKTIME_MATRIX_COEFFICIENTS = {
    0: "Identity matrix",
    1: "BT.709",
    2: "Unspecified",
    3: "For future use (3)",
    4: "US FCC 73.628",
    5: "BT.470 System B, G (historical)",
    6: "BT.601",
    7: "SMPTE 240 M",
    8: "YCgCo",
    9: "BT.2020 non-constant luminance, BT.2100 YCbCr",
    10: "BT.2020 constant luminance",
    11: "SMPTE ST 2085 YDzDx",
    12: "Chromaticity-derived non-constant luminance",
    13: "Chromaticity-derived constant luminance",
    14: "BT.2100 ICtCp",
}
QUICKTIME_YES_NO = {
    0: "No",
    1: "Yes",
}
QUICKTIME_PLAY_GAP = {
    0: "Insert Gap",
    1: "No Gap",
}
QUICKTIME_APPLE_STORE_ACCOUNT_TYPE = {
    0: "iTunes",
    1: "AOL",
}
QUICKTIME_CONTENT_RATING = {
    0: "None",
    1: "Explicit",
    2: "Clean",
    4: "Explicit (old)",
}
QUICKTIME_MEDIA_TYPE = {
    0: "Movie (old)",
    1: "Normal (Music)",
    2: "Audiobook",
    5: "Whacked Bookmark",
    6: "Music Video",
    9: "Movie",
    10: "TV Show",
    11: "Booklet",
    14: "Ringtone",
    21: "Podcast",
    23: "iTunes U",
}
QUICKTIME_ITUNES_INFO_TAGS = {
    "iTunNORM": "VolumeNormalization",
    "iTunSMPB": "iTunSMPB",
    "iTunes_CDDB_1": "CDDB1Info",
    "iTunes_CDDB_TrackNumber": "CDDBTrackNumber",
    "DISCNUMBER": "DiscNumber",
    "TRACKNUMBER": "TrackNumber",
    "ARTISTS": "Artists",
    "CATALOGNUMBER": "CatalogNumber",
    "RATING": "Rating",
    "MEDIA": "Media",
    "SCRIPT": "Script",
    "BARCODE": "Barcode",
}
QUICKTIME_RIGHTS_TAGS = {
    "veID": ("ItemVendorID", False),
    "plat": ("Platform", False),
    "aver": ("VersionRestrictions", False),
    "tran": ("TransactionID", False),
    "song": ("ItemID", False),
    "tool": ("ItemTool", True),
    "medi": ("MediaFlags", False),
    "mode": ("ModeFlags", False),
}
QUICKTIME_TIMED_METADATA_FORMATS = {
    1: "string",
    23: "float",
    24: "double",
    65: "int8s",
    66: "int16s",
    67: "int32s",
    74: "int64s",
    75: "int8u",
    76: "int16u",
    77: "int32u",
    78: "int64u",
}
QUICKTIME_USER_DATA_CONTROL_TAGS = {
    "WLOC": ("WindowLocation", "int16u_pair", "Video"),
    "LOOP": ("LoopStyle", "loop_style", "Video"),
    "SelO": ("PlaySelection", "int8u", "Video"),
    "AllF": ("PlayAllFrames", "int8u", "Video"),
    "tnam": ("TrackName", "itext4", "Video"),
}
QUICKTIME_USER_DATA_3GP_TEXT_TAGS = {
    "cprt": ("Copyright", "Author"),
    "auth": ("Author", "Author"),
    "titl": ("Title", "Video"),
    "dscp": ("Description", "Video"),
    "perf": ("Performer", "Video"),
    "gnre": ("Genre", "Video"),
    "albm": ("Album", "Video"),
    "coll": ("CollectionName", "Video"),
}
QUICKTIME_USER_DATA_MANUFACTURER_PREFIXES = {
    b"FUJIFILM DIGITAL CAMERA\x00": "FujiFilmTags",
    b"EASTMAN KODAK COMPANY": "KodakTags",
    b"KONICA MINOLTA DIGITAL CAMERA": "KonicaMinoltaTags",
    b"MINOLTA DIGITAL CAMERA": "MinoltaTags",
    b"NIKON DIGITAL CAMERA\x00": "NikonTags",
    b"OLYMPUS DIGITAL CAMERA\x00": "OlympusTags",
    b"OLYMPUS DIGITAL CAMERA": "OlympusTags",
    b"PENTAX DIGITAL CAMERA\x00": "PentaxTags",
    b"SAMSUNG DIGITAL CAMERA\x00": "SamsungTags",
    b"SANYO DIGITAL CAMERA\x00": "SanyoTags",
}
type QuickTimeUserDataScalarFormat = Literal[
    "string", "hex", "strip_version_header", "binary", "bytes_text"
]
type QuickTimeUserDataScalarTag = tuple[str, QuickTimeUserDataScalarFormat, str]
type QuickTimeGSphericalValueFormat = Literal["boolean", "integer", "real", "string"]
type QuickTimeGSphericalTag = tuple[str, QuickTimeGSphericalValueFormat, str]
QUICKTIME_USER_DATA_MANUFACTURER_SCALAR_TAGS: dict[str, QuickTimeUserDataScalarTag] = {
    # Image::ExifTool::QuickTime::UserData direct manufacturer atoms.
    "CNCV": ("CompressorVersion", "string", "Video"),
    "CNMN": ("Model", "string", "Camera"),
    "CNFV": ("FirmwareVersion", "string", "Camera"),
    "pmcc": ("GarminSettings", "strip_version_header", "Video"),
    "GoPr": ("GoProType", "bytes_text", "Video"),
    "FIRM": ("FirmwareVersion", "bytes_text", "Camera"),
    "LENS": ("LensSerialNumber", "bytes_text", "Camera"),
    "CAME": ("SerialNumberHash", "hex", "Camera"),
    "MUID": ("MediaUID", "hex", "Video"),
    "FOV\0": ("FieldOfView", "bytes_text", "Video"),
    "\xa9dji": ("UserData_dji", "binary", "Video"),
    "\xa9res": ("UserData_res", "binary", "Video"),
    "\xa9uid": ("UserData_uid", "binary", "Video"),
    "\xa9mdl": ("Model", "string", "Camera"),
    "fsid": ("OriginalFilePath", "bytes_text", "Video"),
}
QUICKTIME_USER_DATA_LOOP_STYLE = {
    1: "Normal",
    2: "Palindromic",
}
QUICKTIME_GSPHERICAL_TAGS: dict[str, QuickTimeGSphericalTag] = {
    "Spherical": ("Spherical", "boolean", "Image"),
    "Stitched": ("Stitched", "boolean", "Image"),
    "StitchingSoftware": ("StitchingSoftware", "string", "Image"),
    "ProjectionType": ("ProjectionType", "string", "Image"),
    "StereoMode": ("StereoMode", "string", "Image"),
    "SourceCount": ("SourceCount", "integer", "Image"),
    "InitialViewHeadingDegrees": ("InitialViewHeadingDegrees", "real", "Image"),
    "InitialViewPitchDegrees": ("InitialViewPitchDegrees", "real", "Image"),
    "InitialViewRollDegrees": ("InitialViewRollDegrees", "real", "Image"),
    "Timestamp": ("TimeStamp", "integer", "Time"),
    "FullPanoWidthPixels": ("FullPanoWidthPixels", "integer", "Image"),
    "FullPanoHeightPixels": ("FullPanoHeightPixels", "integer", "Image"),
    "CroppedAreaImageWidthPixels": ("CroppedAreaImageWidthPixels", "integer", "Image"),
    "CroppedAreaImageHeightPixels": ("CroppedAreaImageHeightPixels", "integer", "Image"),
    "CroppedAreaLeftPixels": ("CroppedAreaLeftPixels", "integer", "Image"),
    "CroppedAreaTopPixels": ("CroppedAreaTopPixels", "integer", "Image"),
}


@dataclass(frozen=True)
class QuickTimeAtomSpan:
    atom_type: str
    offset: int
    header_size: int
    payload_size: int
    payload: bytes
    children: tuple[QuickTimeAtomSpan, ...] = ()

    @property
    def payload_offset(self) -> int:
        return self.offset + self.header_size


@dataclass
class QuickTimeReadState:
    movie_time_scale: int | None = None
    movie_duration_ticks: int | None = None
    media_data_size: int = 0
    media_data_seen: bool = False
    mdat_ranges: tuple[QuickTimeMdatPayloadRange, ...] = ()
    primary_image_width: int | None = None
    primary_image_height: int | None = None
    first_video_matrix: tuple[float, ...] | None = None
    h264_sample_description_seen: bool = False
    movie_fragment_seen: bool = False
    h264_track_ids: tuple[int, ...] = ()
    h264_track_avc_configuration_payloads: dict[int, bytes] = dataclass_field(default_factory=dict)
    h264_avc_configuration_payload: bytes | None = None
    h264_sample_ranges_planned: bool = False
    h264_sample_bytes_read: int = 0
    atom_walk_cache: dict[int, tuple[QuickTimeAtomSpan, ...]] = dataclass_field(
        default_factory=dict
    )
    panasonic_pana_embedded_exif_tag_cache: dict[bytes, tuple[ReadTag, ...]] = dataclass_field(
        default_factory=dict
    )


@dataclass(frozen=True)
class QuickTimeMdatPayloadRange:
    offset: int
    size: int

    @property
    def end_offset(self) -> int:
        return self.offset + self.size


@dataclass(frozen=True)
class QuickTimeSampleByteRange:
    sample_index: int
    chunk_index: int
    offset: int
    size: int
    track_id: int | None = None

    @property
    def end_offset(self) -> int:
        return self.offset + self.size


@dataclass(frozen=True)
class QuickTimeTimedMetadataKey:
    local_id: str
    tag_id: str
    value_format: str


@dataclass(frozen=True)
class QuickTimeSampleTiming:
    sample_time: float | None
    sample_duration: float | None


@dataclass(frozen=True)
class QuickTimeTrackFragmentHeader:
    track_id: int
    base_data_offset: int | None
    default_sample_size: int | None
    default_base_is_moof: bool


def is_quicktime_prefix(data: bytes) -> bool:
    if len(data) < QT_ATOM_HEADER_SIZE:
        return False
    atom_type = data[4:8].decode("latin-1", errors="replace")
    return atom_type in QUICKTIME_TOP_LEVEL_ATOMS


def build_quicktime_read_graph(data: bytes, path: Path, source_file: str) -> ReadGraph:
    tags = _system_tags(path, source_file)
    diagnostics: list[str] = []
    file_type, extension, mime_type = _quicktime_file_type(path, b"")
    state = QuickTimeReadState()
    runtime_options = current_dispatch_read_graph_runtime_options()
    try:
        atoms = _read_top_level_atoms(path)
        file_type_atom = _first_atom(atoms, "ftyp")
        if file_type_atom is not None:
            parsed_file_type = _append_file_type_atom_tags(tags, file_type_atom, path, diagnostics)
            if parsed_file_type is not None:
                file_type, extension, mime_type = parsed_file_type
        elif len(data) >= QT_ATOM_HEADER_SIZE and data[4:8] == b"ftyp":
            diagnostics.append("Truncated QuickTime ftyp atom.")
        tags.extend(_file_type_tags(file_type, extension, mime_type, "quicktime-atom-header"))
        _append_quicktime_atom_tags(tags, atoms, state, diagnostics, path, file_type)
        _append_quicktime_composite_tags(tags, state)
        add_graph_derived_composite_tags(tags, {}, path)
        _append_extract_embedded_warning_tag(tags, state, runtime_options.extract_embedded_level)
        _append_extract_embedded_diagnostics(
            diagnostics,
            state,
            runtime_options.extract_embedded_level,
        )
    except OSError as exc:
        diagnostics.append(f"QuickTime atom traversal failed: {exc}")
    except ValueError as exc:
        diagnostics.append(str(exc))
    if not any(tag.name == "FileType" and tag.provenance.group == "File" for tag in tags):
        tags.extend(_file_type_tags(file_type, extension, mime_type, "quicktime-atom-header"))
    return ReadGraph(1, int(time.time()), source_file, tags, diagnostics)


def _read_top_level_atoms(path: Path) -> tuple[QuickTimeAtomSpan, ...]:
    spans: list[QuickTimeAtomSpan] = []
    file_size = path.stat().st_size
    with path.open("rb") as file:
        offset = 0
        while offset + QT_ATOM_HEADER_SIZE <= file_size:
            file.seek(offset)
            header = file.read(QT_ATOM_HEADER_SIZE)
            if len(header) < QT_ATOM_HEADER_SIZE:
                break
            atom_size = int.from_bytes(header[:4], "big")
            atom_type = header[4:8].decode("latin-1", errors="replace")
            header_size = QT_ATOM_HEADER_SIZE
            if atom_size == 0:
                total_size = file_size - offset
            elif atom_size == 1:
                extended_size_bytes = file.read(QT_ATOM_HEADER_SIZE)
                if len(extended_size_bytes) < QT_ATOM_HEADER_SIZE:
                    raise ValueError("Truncated QuickTime extended atom header.")
                total_size = int.from_bytes(extended_size_bytes, "big")
                header_size = QT_EXTENDED_ATOM_HEADER_SIZE
            else:
                total_size = atom_size
            if total_size < header_size:
                raise ValueError(f"Invalid QuickTime atom length for {atom_type!r}.")
            payload_size = total_size - header_size
            payload = b""
            children: tuple[QuickTimeAtomSpan, ...] = ()
            if atom_type != "mdat" and payload_size <= QUICKTIME_MAX_EAGER_PAYLOAD_BYTES:
                file.seek(offset + header_size)
                payload = file.read(payload_size)
                if atom_type in QUICKTIME_CONTAINER_ATOMS:
                    children = _parse_child_atoms(payload, 0)
            spans.append(
                QuickTimeAtomSpan(
                    atom_type=atom_type,
                    offset=offset,
                    header_size=header_size,
                    payload_size=payload_size,
                    payload=payload,
                    children=children,
                )
            )
            offset += total_size
            if total_size == 0:
                break
    return tuple(spans)


def _parse_child_atoms(data: bytes, base_offset: int) -> tuple[QuickTimeAtomSpan, ...]:
    spans: list[QuickTimeAtomSpan] = []
    offset = 4 if data[:4] == b"\x00\x00\x00\x00" else 0
    while offset + QT_ATOM_HEADER_SIZE <= len(data):
        atom_size = int.from_bytes(data[offset : offset + 4], "big")
        atom_type = data[offset + 4 : offset + 8].decode("latin-1", errors="replace")
        header_size = QT_ATOM_HEADER_SIZE
        if atom_size == 0:
            total_size = len(data) - offset
        elif atom_size == 1:
            if offset + QT_EXTENDED_ATOM_HEADER_SIZE > len(data):
                break
            total_size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header_size = QT_EXTENDED_ATOM_HEADER_SIZE
        else:
            total_size = atom_size
        if total_size < header_size or offset + total_size > len(data):
            break
        payload_offset = offset + header_size
        payload = data[payload_offset : offset + total_size]
        children: tuple[QuickTimeAtomSpan, ...] = ()
        if atom_type in QUICKTIME_CONTAINER_ATOMS:
            children = _parse_child_atoms(payload, base_offset + payload_offset)
        spans.append(
            QuickTimeAtomSpan(
                atom_type=atom_type,
                offset=base_offset + offset,
                header_size=header_size,
                payload_size=total_size - header_size,
                payload=payload,
                children=children,
            )
        )
        offset += total_size
    return tuple(spans)


def _append_quicktime_atom_tags(
    tags: list[ReadTag],
    atoms: tuple[QuickTimeAtomSpan, ...],
    state: QuickTimeReadState,
    diagnostics: list[str],
    path: Path,
    file_type: str,
) -> None:
    state.mdat_ranges = tuple(
        QuickTimeMdatPayloadRange(atom.payload_offset, atom.payload_size)
        for atom in atoms
        if atom.atom_type == "mdat"
    )
    movie_fragments: list[QuickTimeAtomSpan] = []
    state.movie_fragment_seen = any(atom.atom_type == "moof" for atom in atoms)
    for atom in atoms:
        if atom.atom_type == "mdat":
            state.media_data_seen = True
            state.media_data_size += atom.payload_size
            tags.append(_quicktime_tag("MediaDataSize", atom.payload_size, "mdat-size"))
            tags.append(_quicktime_tag("MediaDataOffset", atom.payload_offset, "mdat-offset"))
            continue
        if atom.atom_type == "pnot":
            _append_preview_atom_tags(tags, atom.payload, diagnostics)
        elif atom.atom_type == "moov":
            _append_movie_tags(tags, atom, state, diagnostics, path, file_type)
        elif atom.atom_type == "moof":
            movie_fragments.append(atom)
    if (
        movie_fragments
        and state.h264_sample_description_seen
        and current_dispatch_read_graph_runtime_options().extract_embedded_level > 1
    ):
        _append_h264_fragment_stream_tags(tags, tuple(movie_fragments), state, diagnostics, path)


def _append_file_type_atom_tags(
    tags: list[ReadTag],
    atom: QuickTimeAtomSpan,
    path: Path,
    diagnostics: list[str],
) -> tuple[str, str, str] | None:
    if len(atom.payload) < 8:
        diagnostics.append("Truncated QuickTime ftyp atom.")
        return None
    major_brand = atom.payload[:4].decode("latin-1", errors="replace")
    compatible_brands = _compatible_brands(atom.payload[8:])
    tags.append(
        _read_tag(
            "MajorBrand",
            QUICKTIME_MAJOR_BRANDS.get(major_brand, major_brand),
            "QuickTime",
            "Image::ExifTool::QuickTime::FileType",
            "MajorBrand",
            "quicktime-ftyp-header",
            family_2_group="Video",
        )
    )
    tags.append(
        _read_tag(
            "MinorVersion",
            _minor_version(atom.payload[4:8]),
            "QuickTime",
            "Image::ExifTool::QuickTime::FileType",
            "MinorVersion",
            "quicktime-ftyp-header",
            family_2_group="Video",
        )
    )
    if compatible_brands:
        tags.append(
            _read_tag(
                "CompatibleBrands",
                compatible_brands,
                "QuickTime",
                "Image::ExifTool::QuickTime::FileType",
                "CompatibleBrands",
                "quicktime-ftyp-header",
                family_2_group="Video",
            )
        )
    return _quicktime_file_type(path, atom.payload)


def _append_movie_tags(
    tags: list[ReadTag],
    moov: QuickTimeAtomSpan,
    state: QuickTimeReadState,
    diagnostics: list[str],
    path: Path,
    file_type: str,
) -> None:
    moov_atoms = _walk_atoms_cached(state, moov.children)
    has_audio_track = any(
        _track_handler_type_from_atoms(_walk_atoms_cached(state, atom.children)) == "soun"
        for atom in moov.children
    )
    for atom in moov.children:
        if atom.atom_type == "mvhd":
            _append_movie_header_tags(tags, atom.payload, state)
    _append_movie_metadata_tags(tags, moov_atoms, diagnostics, file_type, state)
    if has_audio_track:
        _append_primary_audio_handler_tags(tags, moov, state)
    track_index = 0
    for atom in moov.children:
        if atom.atom_type == "trak":
            track_index += 1
            _append_track_tags(
                tags,
                atom,
                state,
                diagnostics,
                path,
                track_group=f"Track{track_index}",
            )


def _append_primary_audio_handler_tags(
    tags: list[ReadTag],
    moov: QuickTimeAtomSpan,
    state: QuickTimeReadState,
) -> None:
    for track in moov.children:
        track_atoms = _walk_atoms_cached(state, track.children)
        if track.atom_type != "trak" or _track_handler_type_from_atoms(track_atoms) != "soun":
            continue
        for atom in track_atoms:
            if atom.atom_type == "hdlr":
                _append_handler_tags(tags, atom.payload)
                return


def _append_movie_header_tags(
    tags: list[ReadTag],
    payload: bytes,
    state: QuickTimeReadState,
) -> None:
    if len(payload) < 100:
        return
    version = payload[0]
    tags.append(
        _quicktime_tag(
            "MovieHeaderVersion",
            version,
            "mvhd",
            table_name=QUICKTIME_MOVIE_HEADER_TABLE,
        )
    )
    if version == 1:
        if len(payload) < 112:
            return
        create = int.from_bytes(payload[4:12], "big")
        modify = int.from_bytes(payload[12:20], "big")
        time_scale = int.from_bytes(payload[20:24], "big")
        duration = int.from_bytes(payload[24:32], "big")
        cursor = 32
    else:
        create = int.from_bytes(payload[4:8], "big")
        modify = int.from_bytes(payload[8:12], "big")
        time_scale = int.from_bytes(payload[12:16], "big")
        duration = int.from_bytes(payload[16:20], "big")
        cursor = 20
    state.movie_time_scale = time_scale
    state.movie_duration_ticks = duration
    tags.extend(
        (
            _quicktime_tag(
                "CreateDate",
                _quicktime_time(create),
                "mvhd",
                table_name=QUICKTIME_MOVIE_HEADER_TABLE,
                family_2_group="Time",
            ),
            _quicktime_tag(
                "ModifyDate",
                _quicktime_time(modify),
                "mvhd",
                table_name=QUICKTIME_MOVIE_HEADER_TABLE,
                family_2_group="Time",
            ),
            _quicktime_tag(
                "TimeScale",
                time_scale,
                "mvhd",
                table_name=QUICKTIME_MOVIE_HEADER_TABLE,
            ),
            _quicktime_tag(
                "Duration",
                _duration(duration, time_scale),
                "mvhd",
                table_name=QUICKTIME_MOVIE_HEADER_TABLE,
                family_2_group="Video",
            ),
            _quicktime_tag(
                "PreferredRate",
                _compact_number(_fixed_signed(payload[cursor : cursor + 4], 16)),
                "mvhd",
                table_name=QUICKTIME_MOVIE_HEADER_TABLE,
            ),
            _quicktime_tag(
                "PreferredVolume",
                _percent(_fixed_unsigned(payload[cursor + 4 : cursor + 6], 8)),
                "mvhd",
                table_name=QUICKTIME_MOVIE_HEADER_TABLE,
            ),
            _quicktime_tag(
                "MatrixStructure",
                _matrix_text(_matrix(payload[cursor + 16 : cursor + 52])),
                "mvhd",
                table_name=QUICKTIME_MOVIE_HEADER_TABLE,
                family_2_group="Video",
            ),
        )
    )
    preview_cursor = cursor + 52
    names = (
        "PreviewTime",
        "PreviewDuration",
        "PosterTime",
        "SelectionTime",
        "SelectionDuration",
        "CurrentTime",
        "NextTrackID",
    )
    for index, name in enumerate(names):
        start = preview_cursor + index * 4
        if start + 4 <= len(payload):
            value = int.from_bytes(payload[start : start + 4], "big")
            rendered: TagValue = value if name == "NextTrackID" else _duration(value, time_scale)
            tags.append(
                _quicktime_tag(
                    name,
                    rendered,
                    "mvhd",
                    table_name=QUICKTIME_MOVIE_HEADER_TABLE,
                    family_2_group="Video",
                )
            )


def _append_preview_atom_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
) -> None:
    if len(payload) < 12:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_preview_atom",
            "truncated pnot Preview payload",
        )
        return
    tags.extend(
        (
            _quicktime_tag(
                "PreviewDate",
                _quicktime_time(int.from_bytes(payload[0:4], "big")),
                "pnot",
                table_name=QUICKTIME_PREVIEW_TABLE,
                family_2_group="Time",
            ),
            _quicktime_tag(
                "PreviewVersion",
                int.from_bytes(payload[4:6], "big"),
                "pnot",
                table_name=QUICKTIME_PREVIEW_TABLE,
                family_2_group="Image",
            ),
            _quicktime_tag(
                "PreviewAtomType",
                payload[6:10].decode("latin-1", errors="replace"),
                "pnot",
                table_name=QUICKTIME_PREVIEW_TABLE,
                family_2_group="Image",
            ),
            _quicktime_tag(
                "PreviewAtomIndex",
                int.from_bytes(payload[10:12], "big"),
                "pnot",
                table_name=QUICKTIME_PREVIEW_TABLE,
                family_2_group="Image",
            ),
        )
    )


def _append_track_tags(
    tags: list[ReadTag],
    trak: QuickTimeAtomSpan,
    state: QuickTimeReadState,
    diagnostics: list[str],
    path: Path,
    *,
    track_group: str,
) -> None:
    track_tags_start = len(tags)
    track_atoms = _walk_atoms_cached(state, trak.children)
    handler_type = _track_handler_type_from_atoms(track_atoms)
    track_id = _track_id_from_atoms(track_atoms)
    media_time_scale = _track_media_time_scale_from_atoms(track_atoms)
    track_h264_avcc = (
        _h264_avc_configuration_payload_from_atoms(track_atoms) if handler_type == "vide" else None
    )
    for atom in track_atoms:
        if atom.atom_type == "hdlr":
            _append_handler_tags(tags, atom.payload)
        elif atom.atom_type == "tkhd":
            _append_track_header_tags(tags, atom.payload, state)
        elif atom.atom_type == "mdhd":
            _append_media_header_tags(tags, atom.payload)
        elif atom.atom_type == "elng":
            _append_extended_language_tag(tags, atom.payload)
        elif atom.atom_type == "vmhd":
            _append_video_header_tags(tags, atom.payload)
        elif atom.atom_type == "smhd":
            _append_audio_header_tags(tags, atom.payload)
        elif atom.atom_type == "hmhd":
            _append_hint_header_tags(tags, atom.payload)
        elif atom.atom_type == "gmin":
            _append_generic_media_info_tags(tags, atom.payload)
        elif atom.atom_type == "tref":
            _append_track_reference_tags(tags, atom)
        elif atom.atom_type in {"clef", "prof", "enof"}:
            _append_track_aperture_tag(tags, atom)
        elif atom.atom_type == "tmcd":
            _append_timecode_media_tags(tags, atom, diagnostics)
        elif atom.atom_type == "dref":
            _append_data_reference_tags(tags, atom.payload, diagnostics)
        elif atom.atom_type == "stsd":
            _append_sample_description_tags(tags, atom.payload, handler_type, state, diagnostics)
        elif atom.atom_type == "uuid":
            _append_spherical_video_uuid_tags(tags, atom.payload, diagnostics)
        elif atom.atom_type == "stts" and handler_type == "vide":
            _append_time_to_sample_tags(tags, atom.payload, media_time_scale)
        elif atom.atom_type in QUICKTIME_SAMPLE_TABLE_BINARY_TAGS:
            _append_sample_table_binary_tag(tags, atom)
    if handler_type == "meta":
        _append_timed_metadata_sample_tags(
            tags,
            trak,
            track_atoms,
            media_time_scale,
            diagnostics,
            path,
        )
    elif (
        handler_type == "vide"
        and track_h264_avcc is not None
        and not state.movie_fragment_seen
        and current_dispatch_read_graph_runtime_options().extract_embedded_level > 1
    ):
        _append_h264_sample_stream_tags(tags, track_atoms, state, diagnostics, path)
    if handler_type == "vide" and track_h264_avcc is not None and track_id is not None:
        state.h264_track_ids = (*state.h264_track_ids, track_id)
        state.h264_track_avc_configuration_payloads[track_id] = track_h264_avcc
    for index in range(track_tags_start, len(tags)):
        tags[index] = _with_track_family_1_group(tags[index], track_group)


def _append_track_header_tags(
    tags: list[ReadTag],
    payload: bytes,
    state: QuickTimeReadState,
) -> None:
    if len(payload) < 84:
        return
    version = payload[0]
    tags.append(
        _quicktime_tag(
            "TrackHeaderVersion",
            version,
            "tkhd",
            table_name=QUICKTIME_TRACK_HEADER_TABLE,
        )
    )
    if version == 1:
        if len(payload) < 96:
            return
        create = int.from_bytes(payload[4:12], "big")
        modify = int.from_bytes(payload[12:20], "big")
        track_id = int.from_bytes(payload[20:24], "big")
        duration = int.from_bytes(payload[28:36], "big")
        cursor = 36
    else:
        create = int.from_bytes(payload[4:8], "big")
        modify = int.from_bytes(payload[8:12], "big")
        track_id = int.from_bytes(payload[12:16], "big")
        duration = int.from_bytes(payload[20:24], "big")
        cursor = 24
    time_scale = state.movie_time_scale or 0
    matrix_offset = cursor + 16
    matrix = _matrix(payload[matrix_offset : matrix_offset + 36])
    width = _fixed_unsigned(payload[matrix_offset + 36 : matrix_offset + 40], 16)
    height = _fixed_unsigned(payload[matrix_offset + 40 : matrix_offset + 44], 16)
    if width > 0 and height > 0 and state.primary_image_width is None:
        state.primary_image_width = int(width)
        state.primary_image_height = int(height)
        state.first_video_matrix = matrix
    tags.extend(
        (
            _quicktime_tag(
                "TrackCreateDate",
                _quicktime_time(create),
                "tkhd",
                table_name=QUICKTIME_TRACK_HEADER_TABLE,
                family_2_group="Time",
            ),
            _quicktime_tag(
                "TrackModifyDate",
                _quicktime_time(modify),
                "tkhd",
                table_name=QUICKTIME_TRACK_HEADER_TABLE,
                family_2_group="Time",
            ),
            _quicktime_tag("TrackID", track_id, "tkhd", table_name=QUICKTIME_TRACK_HEADER_TABLE),
            _quicktime_tag(
                "TrackDuration",
                _duration(duration, time_scale),
                "tkhd",
                table_name=QUICKTIME_TRACK_HEADER_TABLE,
                family_2_group="Video",
            ),
            _quicktime_tag(
                "TrackLayer",
                int.from_bytes(payload[cursor + 8 : cursor + 10], "big"),
                "tkhd",
                table_name=QUICKTIME_TRACK_HEADER_TABLE,
            ),
            _quicktime_tag(
                "TrackVolume",
                _percent(_fixed_unsigned(payload[cursor + 12 : cursor + 14], 8)),
                "tkhd",
                table_name=QUICKTIME_TRACK_HEADER_TABLE,
            ),
            _quicktime_tag(
                "MatrixStructure",
                _matrix_text(matrix),
                "tkhd",
                table_name=QUICKTIME_TRACK_HEADER_TABLE,
                family_2_group="Video",
            ),
        )
    )
    if width > 0 and height > 0:
        tags.extend(
            (
                _quicktime_tag(
                    "ImageWidth",
                    int(width),
                    "tkhd",
                    table_name=QUICKTIME_TRACK_HEADER_TABLE,
                    family_2_group="Image",
                ),
                _quicktime_tag(
                    "ImageHeight",
                    int(height),
                    "tkhd",
                    table_name=QUICKTIME_TRACK_HEADER_TABLE,
                    family_2_group="Image",
                ),
            )
        )


def _append_media_header_tags(tags: list[ReadTag], payload: bytes) -> None:
    if len(payload) < 24:
        return
    version = payload[0]
    tags.append(
        _quicktime_tag(
            "MediaHeaderVersion",
            version,
            "mdhd",
            table_name=QUICKTIME_MEDIA_HEADER_TABLE,
        )
    )
    if version == 1:
        if len(payload) < 36:
            return
        create = int.from_bytes(payload[4:12], "big")
        modify = int.from_bytes(payload[12:20], "big")
        time_scale = int.from_bytes(payload[20:24], "big")
        duration = int.from_bytes(payload[24:32], "big")
        language = int.from_bytes(payload[32:34], "big")
    else:
        create = int.from_bytes(payload[4:8], "big")
        modify = int.from_bytes(payload[8:12], "big")
        time_scale = int.from_bytes(payload[12:16], "big")
        duration = int.from_bytes(payload[16:20], "big")
        language = int.from_bytes(payload[20:22], "big")
    tags.extend(
        (
            _quicktime_tag(
                "MediaCreateDate",
                _quicktime_time(create),
                "mdhd",
                table_name=QUICKTIME_MEDIA_HEADER_TABLE,
                family_2_group="Time",
            ),
            _quicktime_tag(
                "MediaModifyDate",
                _quicktime_time(modify),
                "mdhd",
                table_name=QUICKTIME_MEDIA_HEADER_TABLE,
                family_2_group="Time",
            ),
            _quicktime_tag(
                "MediaTimeScale",
                time_scale,
                "mdhd",
                table_name=QUICKTIME_MEDIA_HEADER_TABLE,
            ),
            _quicktime_tag(
                "MediaDuration",
                _duration(duration, time_scale),
                "mdhd",
                table_name=QUICKTIME_MEDIA_HEADER_TABLE,
                family_2_group="Video",
            ),
        )
    )
    if language:
        tags.append(
            _quicktime_tag(
                "MediaLanguageCode",
                _language_code(language),
                "mdhd",
                table_name=QUICKTIME_MEDIA_HEADER_TABLE,
            )
        )


def _append_extended_language_tag(tags: list[ReadTag], payload: bytes) -> None:
    value = payload.rstrip(b"\0").decode("utf-8", errors="replace")
    if value:
        tags.append(_quicktime_tag("ExtendedLanguageTag", value, "elng"))


def _append_time_to_sample_tags(
    tags: list[ReadTag],
    payload: bytes,
    media_time_scale: int | None,
) -> None:
    entries = _time_to_sample_entries(payload)
    if entries is None:
        return
    total_samples = sum(sample_count for sample_count, _ in entries)
    total_ticks = sum(sample_count * sample_duration for sample_count, sample_duration in entries)
    if media_time_scale and total_samples and total_ticks:
        frame_rate = total_samples * media_time_scale / total_ticks
        tags.append(
            _quicktime_tag(
                "VideoFrameRate",
                _rounded_number(frame_rate),
                "stts",
                table_name=QUICKTIME_SAMPLE_TABLE,
                family_2_group="Video",
            )
        )
    if _quicktime_should_emit_unknown_tags():
        tags.append(
            _quicktime_tag(
                "TimeToSampleTable",
                BinaryTagValue(payload),
                "stts",
                table_name=QUICKTIME_SAMPLE_TABLE,
                family_2_group="Video",
            )
        )


def _append_sample_table_binary_tag(tags: list[ReadTag], atom: QuickTimeAtomSpan) -> None:
    name = QUICKTIME_SAMPLE_TABLE_BINARY_TAGS.get(atom.atom_type)
    if name is None or not _is_valid_sample_table_payload(atom.atom_type, atom.payload):
        return
    if atom.atom_type == "stps":
        tags.append(
            _quicktime_tag(
                name,
                _partial_sync_samples(atom.payload),
                atom.atom_type,
                table_name=QUICKTIME_SAMPLE_TABLE,
                family_2_group="Video",
            )
        )
        return
    if not _quicktime_should_emit_unknown_tags():
        return
    tags.append(
        _quicktime_tag(
            name,
            BinaryTagValue(atom.payload),
            atom.atom_type,
            table_name=QUICKTIME_SAMPLE_TABLE,
            family_2_group="Video",
        )
    )


def _quicktime_should_emit_unknown_tags() -> bool:
    runtime_options = current_dispatch_read_graph_runtime_options()
    return runtime_options.unknown_tag_level > 0 or runtime_options.requests_request_all_hidden_tags


def _quicktime_should_emit_configuration_tags() -> bool:
    runtime_options = current_dispatch_read_graph_runtime_options()
    return (
        runtime_options.unknown_tag_level > 0
        or runtime_options.requests_request_all_hidden_tags
        or runtime_options.extract_embedded_level > 1
    )


def _is_valid_sample_table_payload(atom_type: str, payload: bytes) -> bool:
    if atom_type == "ctts":
        return _has_fixed_width_fullbox_entries(payload, 8)
    if atom_type == "stsc":
        return _has_fixed_width_fullbox_entries(payload, 12)
    if atom_type == "stsz":
        return _has_sample_size_entries(payload)
    if atom_type == "stz2":
        return len(payload) >= 12
    if atom_type == "stco":
        return _has_fixed_width_fullbox_entries(payload, 4)
    if atom_type == "co64":
        return _has_fixed_width_fullbox_entries(payload, 8)
    if atom_type in {
        "stss",
        "stsh",
        "padb",
        "stdp",
        "sdtp",
        "sbgp",
        "sgpd",
        "subs",
        "cslg",
        "stps",
    }:
        return len(payload) >= 4
    return False


def _has_fixed_width_fullbox_entries(payload: bytes, entry_size: int) -> bool:
    if len(payload) < 8:
        return False
    entry_count = int.from_bytes(payload[4:8], "big")
    return len(payload) >= 8 + entry_count * entry_size


def _has_sample_size_entries(payload: bytes) -> bool:
    if len(payload) < 12:
        return False
    sample_size = int.from_bytes(payload[4:8], "big")
    sample_count = int.from_bytes(payload[8:12], "big")
    if sample_size != 0:
        return True
    return len(payload) >= 12 + sample_count * 4


def _time_to_sample_entries(payload: bytes) -> tuple[tuple[int, int], ...] | None:
    if len(payload) < 8:
        return None
    entry_count = int.from_bytes(payload[4:8], "big")
    if entry_count == 0 or len(payload) < 8 + entry_count * 8:
        return None
    entries: list[tuple[int, int]] = []
    offset = 8
    for _ in range(entry_count):
        sample_count = int.from_bytes(payload[offset : offset + 4], "big")
        sample_duration = int.from_bytes(payload[offset + 4 : offset + 8], "big")
        entries.append((sample_count, sample_duration))
        offset += 8
    return tuple(entries)


def _partial_sync_samples(payload: bytes) -> str:
    return " ".join(
        str(int.from_bytes(payload[offset : offset + 4], "big"))
        for offset in range(8, len(payload) - 3, 4)
    )


def _append_audio_header_tags(tags: list[ReadTag], payload: bytes) -> None:
    if len(payload) < 6:
        return
    tags.append(
        _quicktime_tag(
            "Balance",
            _compact_number(_fixed_signed(payload[4:6], 8)),
            "smhd",
            family_2_group="Audio",
        )
    )


def _append_video_header_tags(tags: list[ReadTag], payload: bytes) -> None:
    if len(payload) < 12:
        return
    graphics_mode = int.from_bytes(payload[4:6], "big")
    op_color = tuple(int.from_bytes(payload[index : index + 2], "big") for index in (6, 8, 10))
    tags.append(
        _quicktime_tag(
            "GraphicsMode",
            QUICKTIME_GRAPHICS_MODES.get(graphics_mode, graphics_mode),
            "vmhd",
        )
    )
    tags.append(_quicktime_tag("OpColor", " ".join(str(value) for value in op_color), "vmhd"))


def _append_hint_header_tags(tags: list[ReadTag], payload: bytes) -> None:
    if len(payload) < 16:
        return
    tags.append(
        _quicktime_tag(
            "MaxPDUSize",
            int.from_bytes(payload[4:6], "big"),
            "hmhd",
        )
    )
    tags.append(
        _quicktime_tag(
            "AvgPDUSize",
            int.from_bytes(payload[6:8], "big"),
            "hmhd",
        )
    )
    tags.append(
        _quicktime_tag(
            "MaxBitrate",
            int.from_bytes(payload[8:12], "big"),
            "hmhd",
        )
    )
    tags.append(
        _quicktime_tag(
            "AvgBitrate",
            int.from_bytes(payload[12:16], "big"),
            "hmhd",
        )
    )


def _append_generic_media_info_tags(tags: list[ReadTag], payload: bytes) -> None:
    if len(payload) < 14:
        return
    graphics_mode = int.from_bytes(payload[4:6], "big")
    op_color = tuple(int.from_bytes(payload[index : index + 2], "big") for index in (6, 8, 10))
    tags.append(_quicktime_tag("GenMediaVersion", payload[0], "gmin"))
    tags.append(
        _quicktime_tag(
            "GenFlags",
            " ".join(str(value) for value in payload[1:4]),
            "gmin",
        )
    )
    tags.append(
        _quicktime_tag(
            "GenGraphicsMode",
            QUICKTIME_GRAPHICS_MODES.get(graphics_mode, graphics_mode),
            "gmin",
        )
    )
    tags.append(_quicktime_tag("GenOpColor", " ".join(str(value) for value in op_color), "gmin"))
    tags.append(
        _quicktime_tag(
            "GenBalance",
            _compact_number(_fixed_signed(payload[12:14], 8)),
            "gmin",
        )
    )


def _append_track_reference_tags(tags: list[ReadTag], track_ref: QuickTimeAtomSpan) -> None:
    for child in track_ref.children:
        if child.atom_type == "tmcd":
            value = _int32u_values(child.payload)
            if value is not None:
                tags.append(
                    _quicktime_tag(
                        "TimecodeTrack",
                        value,
                        "tmcd",
                        table_name=QUICKTIME_TRACK_REF_TABLE,
                    )
                )


def _append_track_aperture_tag(tags: list[ReadTag], atom: QuickTimeAtomSpan) -> None:
    names = {
        "clef": "CleanApertureDimensions",
        "prof": "ProductionApertureDimensions",
        "enof": "EncodedPixelsDimensions",
    }
    if len(atom.payload) < 12:
        return
    width = _fixed_unsigned(atom.payload[4:8], 16)
    height = _fixed_unsigned(atom.payload[8:12], 16)
    tags.append(
        _quicktime_tag(
            names[atom.atom_type],
            f"{_compact_number(width)}x{_compact_number(height)}",
            atom.atom_type,
            table_name=QUICKTIME_TRACK_APERTURE_TABLE,
            family_2_group="Video",
        )
    )


def _append_timecode_media_tags(
    tags: list[ReadTag],
    timecode_atom: QuickTimeAtomSpan,
    diagnostics: list[str],
) -> None:
    for child in _parse_child_atoms(timecode_atom.payload, timecode_atom.payload_offset):
        if child.atom_type == "tcmi":
            _append_timecode_media_info_tags(tags, child.payload, diagnostics)


def _append_timecode_media_info_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
) -> None:
    if len(payload) < 24:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_timecode_media_info",
            "truncated TimeCode tcmi payload",
        )
        return
    text_font = int.from_bytes(payload[4:6], "big")
    text_face = int.from_bytes(payload[6:8], "big")
    text_color = tuple(int.from_bytes(payload[index : index + 2], "big") for index in (12, 14, 16))
    background_color = tuple(
        int.from_bytes(payload[index : index + 2], "big") for index in (18, 20, 22)
    )
    tags.extend(
        (
            _quicktime_tag(
                "TextFont",
                "System" if text_font == 0 else text_font,
                "tcmi",
                table_name=QUICKTIME_TCMEDIA_INFO_TABLE,
            ),
            _quicktime_tag(
                "TextFace",
                _text_face(text_face),
                "tcmi",
                table_name=QUICKTIME_TCMEDIA_INFO_TABLE,
            ),
            _quicktime_tag(
                "TextSize",
                int.from_bytes(payload[8:10], "big"),
                "tcmi",
                table_name=QUICKTIME_TCMEDIA_INFO_TABLE,
            ),
            _quicktime_tag(
                "TextColor",
                " ".join(str(value) for value in text_color),
                "tcmi",
                table_name=QUICKTIME_TCMEDIA_INFO_TABLE,
            ),
            _quicktime_tag(
                "BackgroundColor",
                " ".join(str(value) for value in background_color),
                "tcmi",
                table_name=QUICKTIME_TCMEDIA_INFO_TABLE,
            ),
        )
    )
    if len(payload) > 24:
        tags.append(
            _quicktime_tag(
                "FontName",
                _pascal_string(payload[24:]),
                "tcmi",
                table_name=QUICKTIME_TCMEDIA_INFO_TABLE,
            )
        )


def _int32u_values(payload: bytes) -> int | str | None:
    if len(payload) < 4:
        return None
    values = tuple(
        int.from_bytes(payload[offset : offset + 4], "big")
        for offset in range(0, len(payload) - len(payload) % 4, 4)
    )
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return " ".join(str(value) for value in values)


def _text_face(value: int) -> str:
    if value == 0:
        return "Plain"
    names = ("Bold", "Italic", "Underline", "Outline", "Shadow", "Condense", "Extend")
    selected = tuple(name for bit, name in enumerate(names) if value & (1 << bit))
    return ", ".join(selected) if selected else str(value)


def _pascal_string(payload: bytes) -> str:
    if not payload:
        return ""
    size = payload[0]
    if size == 0:
        return ""
    return payload[1 : 1 + size].decode("utf-8", errors="replace")


def _append_data_reference_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
) -> None:
    if len(payload) < 8:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_data_reference",
            "truncated DataRef header",
        )
        return
    entries = _parse_child_atoms(payload[8:], 0)
    if not entries:
        return
    for entry in entries:
        if entry.atom_type in {"url ", "url\0"}:
            value = _data_reference_text(entry.payload, separator=None)
            if value:
                tags.append(_quicktime_tag("URL", value, entry.atom_type))
        elif entry.atom_type == "urn ":
            value = _data_reference_text(entry.payload, separator="; ")
            if value:
                tags.append(_quicktime_tag("URN", value, entry.atom_type))
        elif entry.atom_type == "alis":
            continue
        else:
            _append_quicktime_diagnostic(
                diagnostics,
                "unsupported_data_reference",
                f"unsupported DataRef atom {_printable_atom_id(entry.atom_type)!r}",
            )


def _data_reference_text(payload: bytes, *, separator: str | None) -> str | None:
    if len(payload) < 4 or int.from_bytes(payload[:4], "big") & 0x01:
        return None
    text_payload = payload[4:]
    if separator is not None:
        text_payload = text_payload.replace(b"\0", separator.encode("latin-1"), 1)
    return text_payload.split(b"\0", 1)[0].decode("latin-1", errors="replace")


def _append_handler_tags(tags: list[ReadTag], payload: bytes) -> None:
    handler_type = _handler_type(payload)
    if handler_type is None:
        return
    if len(payload) >= 8:
        handler_class = payload[4:8].decode("latin-1", errors="replace").strip("\0")
        if handler_class:
            tags.append(
                _quicktime_tag(
                    "HandlerClass",
                    _handler_class_description(handler_class),
                    "hdlr",
                    table_name=QUICKTIME_HANDLER_TABLE,
                )
            )
    tags.append(
        _quicktime_tag(
            "HandlerType",
            _handler_type_description(handler_type),
            "hdlr",
            table_name=QUICKTIME_HANDLER_TABLE,
        )
    )
    if len(payload) >= 16:
        vendor = payload[12:16].decode("latin-1", errors="replace").strip("\0")
        if vendor:
            tags.append(
                _quicktime_tag(
                    "HandlerVendorID",
                    QUICKTIME_VENDOR_IDS.get(vendor, vendor),
                    "hdlr",
                    table_name=QUICKTIME_HANDLER_TABLE,
                )
            )
    description = _pascal_or_c_string(payload[24:])
    if description:
        tags.append(
            _quicktime_tag(
                "HandlerDescription",
                description,
                "hdlr",
                table_name=QUICKTIME_HANDLER_TABLE,
            )
        )


def _append_sample_description_tags(
    tags: list[ReadTag],
    payload: bytes,
    handler_type: str,
    state: QuickTimeReadState,
    diagnostics: list[str],
) -> None:
    if len(payload) < 8:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_sample_description",
            "truncated stsd header",
        )
        return
    entry_count = int.from_bytes(payload[4:8], "big")
    offset = 8
    for entry_index in range(entry_count):
        if offset + 8 > len(payload):
            _append_quicktime_diagnostic(
                diagnostics,
                "unsupported_sample_description",
                f"truncated {handler_type or 'unknown'} stsd entry {entry_index + 1}",
            )
            return
        size = int.from_bytes(payload[offset : offset + 4], "big")
        sample_format = payload[offset + 4 : offset + 8].decode("latin-1", errors="replace")
        if size < 8 or offset + size > len(payload):
            _append_quicktime_diagnostic(
                diagnostics,
                "unsupported_sample_description",
                f"invalid {handler_type or 'unknown'} stsd entry {entry_index + 1} size",
            )
            return
        sample_payload = payload[offset + 8 : offset + size]
        if handler_type == "soun":
            _append_audio_sample_tags(tags, sample_format, sample_payload, diagnostics)
        elif handler_type == "vide":
            if sample_format in {"avc1", "avc3"} and _sample_payload_has_child(
                sample_payload, "avcC", min_binary_size=78
            ):
                state.h264_sample_description_seen = True
                if state.h264_avc_configuration_payload is None:
                    for child in _hybrid_child_atoms(sample_payload, min_binary_size=78):
                        if child.atom_type == "avcC" and len(child.payload) >= 7:
                            state.h264_avc_configuration_payload = child.payload
                            break
            _append_video_sample_tags(tags, sample_format, sample_payload, diagnostics)
        elif handler_type == "hint":
            _append_hint_sample_tags(tags, sample_format, sample_payload, diagnostics)
        elif handler_type == "meta":
            _append_meta_sample_tags(tags, sample_format, sample_payload, diagnostics)
        else:
            _append_other_sample_tags(tags, sample_format, sample_payload, diagnostics)
        offset += size


def _append_movie_metadata_tags(
    tags: list[ReadTag],
    moov_atoms: tuple[QuickTimeAtomSpan, ...],
    diagnostics: list[str],
    file_type: str,
    state: QuickTimeReadState,
) -> None:
    keys_by_meta_atom_id: dict[str, QuickTimeMetadataTag] = {}
    for atom in moov_atoms:
        if atom.atom_type == "hdlr" and _handler_type(atom.payload) in {"meta", "mdta", "mdir"}:
            _append_handler_tags(tags, atom.payload)
        elif atom.atom_type == "uuid":
            _append_spherical_video_uuid_tags(tags, atom.payload, diagnostics)
        elif atom.atom_type == "keys":
            keys_by_meta_atom_id = _keys_by_meta_atom_id(atom.payload, diagnostics)
        elif atom.atom_type == "ilst":
            _append_item_list_tags(tags, atom, keys_by_meta_atom_id, diagnostics)
        elif atom.atom_type == "udta":
            _append_user_data_tags(tags, atom, diagnostics, file_type, state)


def _sample_payload_has_child(payload: bytes, atom_type: str, *, min_binary_size: int) -> bool:
    return any(
        child.atom_type == atom_type
        for child in _hybrid_child_atoms(payload, min_binary_size=min_binary_size)
    )


def _append_item_list_tags(
    tags: list[ReadTag],
    item_list: QuickTimeAtomSpan,
    keys_by_meta_atom_id: dict[str, QuickTimeMetadataTag],
    diagnostics: list[str],
) -> None:
    for item in item_list.children:
        if item.atom_type == "----":
            _append_itunes_info_tags(tags, item, diagnostics)
            continue
        metadata_tag = QUICKTIME_ITEM_LIST_TAGS.get(item.atom_type)
        if metadata_tag is None:
            metadata_tag = keys_by_meta_atom_id.get(item.atom_type)
        if metadata_tag is None:
            diagnostics.append(
                f"Unsupported QuickTime ItemList/mdta atom {_printable_atom_id(item.atom_type)!r}."
            )
            continue
        for data_atom in parse_item_list_data_atoms(item.payload):
            value = _decode_quicktime_data_value(data_atom.value, metadata_tag.item_list_format)
            if value is None or value == "":
                tag_label = f"{metadata_tag.group}:{metadata_tag.name}"
                diagnostics.append(f"Unsupported QuickTime data payload for {tag_label}.")
                continue
            tag_name = metadata_tag.name
            language_code = _quicktime_data_atom_language_code(
                data_atom.country,
                data_atom.language,
            )
            if language_code is not None:
                tag_name = f"{tag_name}-{language_code}"
            tags.append(
                _quicktime_metadata_tag(metadata_tag, value, item.atom_type, tag_name=tag_name)
            )
            if language_code is not None:
                tags.append(_quicktime_metadata_tag(metadata_tag, value, item.atom_type))


def _append_itunes_info_tags(
    tags: list[ReadTag],
    item: QuickTimeAtomSpan,
    diagnostics: list[str],
) -> None:
    children = _parse_child_atoms(item.payload, item.payload_offset)
    namespace = ""
    tag_id = ""
    data_values: list[bytes] = []
    for child in children:
        if child.atom_type == "mean":
            namespace = _itunes_text_child_value(child.payload)
        elif child.atom_type == "name":
            tag_id = _itunes_text_child_value(child.payload)
        elif child.atom_type == "data" and len(child.payload) >= 8:
            data_values.append(child.payload[8:])
    if namespace != "com.apple.iTunes":
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_itunes_info",
            f"unsupported iTunesInfo namespace {namespace!r}",
        )
        return
    tag_name = QUICKTIME_ITUNES_INFO_TAGS.get(tag_id)
    if tag_name is None:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_itunes_info",
            f"unsupported iTunesInfo tag {tag_id!r}",
        )
        return
    for value in data_values:
        text = value.rstrip(b"\0").decode("utf-8", errors="replace")
        if tag_id in {"iTunNORM", "iTunSMPB"}:
            text = _strip_itunes_hex_padding(text)
        if text:
            tags.append(
                _read_tag(
                    tag_name,
                    text,
                    "iTunes",
                    QUICKTIME_ITUNES_INFO_TABLE,
                    tag_id,
                    "quicktime-metadata-atom",
                    family_0_group="QuickTime",
                    family_1_group="iTunes",
                    family_2_group="Audio",
                )
            )


def _itunes_text_child_value(payload: bytes) -> str:
    if len(payload) < 4:
        return ""
    return payload[4:].rstrip(b"\0").decode("utf-8", errors="replace")


def _strip_itunes_hex_padding(value: str) -> str:
    parts: list[str] = []
    for part in value.strip().split():
        parts.append(part.lstrip("0") or "0")
    return " ".join(parts)


def _append_user_data_tags(
    tags: list[ReadTag],
    user_data: QuickTimeAtomSpan,
    diagnostics: list[str],
    file_type: str,
    state: QuickTimeReadState,
) -> None:
    for item in user_data.children:
        if item.atom_type == "XMP_":
            _append_xmp_user_data_tags(tags, item, diagnostics)
            continue
        if item.atom_type in {"PANA", "LEIC"}:
            _append_panasonic_pana_user_data_tags(tags, item, state)
            continue
        control_tag = QUICKTIME_USER_DATA_CONTROL_TAGS.get(item.atom_type)
        if control_tag is not None:
            tag_name, value_format, family_2_group = control_tag
            value = _decode_user_data_control_value(item.payload, value_format)
            if value is None:
                _append_quicktime_diagnostic(
                    diagnostics,
                    "unsupported_user_data_control_payload",
                    f"unsupported UserData {item.atom_type} payload for {tag_name}",
                )
                continue
            tags.append(
                _read_tag(
                    tag_name,
                    value,
                    "UserData",
                    "Image::ExifTool::QuickTime::UserData",
                    item.atom_type,
                    "quicktime-metadata-atom",
                    family_0_group="QuickTime",
                    family_1_group="UserData",
                    family_2_group=family_2_group,
                )
            )
            continue
        text_3gp_tag = QUICKTIME_USER_DATA_3GP_TEXT_TAGS.get(item.atom_type)
        if text_3gp_tag is not None:
            tag_name, family_2_group = text_3gp_tag
            _append_3gp_user_data_text_tag(tags, item, tag_name, family_2_group, diagnostics)
            continue
        if item.atom_type == "rtng":
            _append_3gp_rating_tag(tags, item, diagnostics)
            continue
        if item.atom_type == "loci":
            _append_3gp_location_information_tag(tags, item, diagnostics)
            continue
        scalar_tag = QUICKTIME_USER_DATA_MANUFACTURER_SCALAR_TAGS.get(item.atom_type)
        if scalar_tag is not None:
            tag_name, value_format, family_2_group = scalar_tag
            value = _decode_user_data_manufacturer_scalar(item.payload, value_format)
            if value is None:
                _append_quicktime_diagnostic(
                    diagnostics,
                    "unsupported_user_data_manufacturer_payload",
                    f"unsupported UserData {item.atom_type} payload for {tag_name}",
                )
                continue
            tags.append(
                _read_tag(
                    tag_name,
                    value,
                    "UserData",
                    "Image::ExifTool::QuickTime::UserData",
                    item.atom_type,
                    "quicktime-metadata-atom",
                    family_0_group="QuickTime",
                    family_1_group="UserData",
                    family_2_group=family_2_group,
                )
            )
            continue
        metadata_tag = QUICKTIME_USER_DATA_TAGS.get(item.atom_type)
        if metadata_tag is None:
            if item.atom_type != "meta":
                manufacturer_tag = _matched_user_data_manufacturer_tag(item.payload)
                if manufacturer_tag is None:
                    atom_id = _printable_atom_id(item.atom_type)
                    diagnostics.append(f"Unsupported QuickTime UserData atom {atom_id!r}.")
                elif manufacturer_tag == "SanyoTags" and file_type in {"MOV", "MP4"}:
                    _append_sanyo_user_data_tags(tags, item.payload, file_type, diagnostics)
                elif manufacturer_tag == "PentaxTags":
                    _append_pentax_mov_user_data_tags(tags, item.payload, diagnostics, item)
                else:
                    _append_quicktime_diagnostic(
                        diagnostics,
                        "deferred_user_data_manufacturer_adapter",
                        (
                            f"{manufacturer_tag} matched in atom "
                            f"{_printable_atom_id(item.atom_type)!r}"
                        ),
                    )
            continue
        value = _decode_user_data_value(item.payload, metadata_tag)
        if value is None or value == "":
            diagnostics.append(f"Unsupported QuickTime UserData payload for {metadata_tag.name}.")
            continue
        tag_name = metadata_tag.name
        if metadata_tag.atom_id.startswith("\xa9"):
            parsed = parse_user_data_text_value(item.payload)
            language = unpack_quicktime_language(parsed[0]) if parsed is not None else None
            if language is not None:
                tag_name = f"{tag_name}-{language}"
        tags.append(_quicktime_metadata_tag(metadata_tag, value, item.atom_type, tag_name=tag_name))


def _append_pentax_mov_user_data_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
    item: QuickTimeAtomSpan,
) -> None:
    from exifmodern.formats.quicktime.pentax_mov import parse_pentax_mov_user_data

    fields = parse_pentax_mov_user_data(payload)
    if not fields:
        _append_quicktime_diagnostic(
            diagnostics,
            "deferred_user_data_manufacturer_adapter",
            f"PentaxTags matched in atom {_printable_atom_id(item.atom_type)!r}",
        )
        return
    for field in fields:
        tags.append(
            _read_tag(
                field.name,
                field.value,
                "MakerNotes",
                "Image::ExifTool::Pentax::MOV",
                field.tag_id,
                "quicktime-userdata-pentax-mov-payload",
                family_0_group="MakerNotes",
                family_1_group="Pentax",
                family_2_group=field.family_2_group,
            )
        )


def _append_sanyo_user_data_tags(
    tags: list[ReadTag],
    payload: bytes,
    file_type: str,
    diagnostics: list[str],
) -> None:
    from exifmodern.formats.sanyo import (
        build_sanyo_mov_metadata_plan,
        build_sanyo_mp4_metadata_plan,
    )

    plan = (
        build_sanyo_mov_metadata_plan(payload)
        if file_type == "MOV"
        else build_sanyo_mp4_metadata_plan(payload)
    )
    if not plan.fields:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_user_data_manufacturer_payload",
            f"unsupported Sanyo {file_type} payload",
        )
        return
    table_name = (
        "Image::ExifTool::Sanyo::MOV" if plan.surface == "mov" else "Image::ExifTool::Sanyo::MP4"
    )
    for field in plan.fields:
        tags.append(
            _read_tag(
                field.tag_name,
                _sanyo_video_tag_value(field.rendered_value),
                "MakerNotes",
                table_name,
                f"0x{field.offset:02x}",
                "quicktime-userdata-sanyo-manufacturer-payload",
                family_0_group="MakerNotes",
                family_1_group="Sanyo",
                family_2_group="Camera",
            )
        )
    _append_sanyo_thumbnail_diagnostics(plan, diagnostics)


def _sanyo_video_tag_value(value: int | float | str | tuple[int, ...]) -> TagValue:
    if isinstance(value, tuple):
        return " ".join(str(item) for item in value)
    return value


def _append_sanyo_thumbnail_diagnostics(
    plan: SanyoVideoMetadataPlan,
    diagnostics: list[str],
) -> None:
    for route in plan.thumbnail_routes:
        _append_quicktime_diagnostic(
            diagnostics,
            "deferred_sanyo_thumbnail_payload",
            (
                f"Sanyo {plan.surface.upper()} Thumbnail route 0x{route:02x} matched, "
                "but Image::ExifTool::Sanyo::Thumbnail binary extraction remains deferred"
            ),
        )


def _append_panasonic_pana_user_data_tags(
    tags: list[ReadTag],
    item: QuickTimeAtomSpan,
    state: QuickTimeReadState,
) -> None:
    from exifmodern.formats.panasonic.pana import parse_panasonic_pana_user_data

    for field in parse_panasonic_pana_user_data(
        item.payload,
        leica_atom=item.atom_type == "LEIC",
    ):
        tags.append(
            _read_tag(
                field.name,
                field.value,
                "MakerNotes",
                "Image::ExifTool::Panasonic::PANA",
                field.tag_id,
                "quicktime-metadata-atom",
                family_0_group="MakerNotes",
                family_1_group="MakerNotes",
                family_2_group=field.family_2_group,
            )
        )
    _append_panasonic_pana_embedded_exif_tags(tags, item.payload, state)


def _append_panasonic_pana_embedded_exif_tags(
    tags: list[ReadTag],
    payload: bytes,
    state: QuickTimeReadState,
) -> None:
    from exifmodern.formats.panasonic.pana import embedded_exif_from_panasonic_pana_user_data

    for embedded in embedded_exif_from_panasonic_pana_user_data(payload):
        cached_tags = state.panasonic_pana_embedded_exif_tag_cache.get(embedded.tiff_data)
        if cached_tags is None:
            decoded_tags: list[ReadTag] = []
            _append_tiff_value_group_tags(
                decoded_tags,
                read_ifd0_values,
                embedded.tiff_data,
                "IFD0",
                "Image::ExifTool::Exif::Main",
                "quicktime-pana-embedded-exif-ifd0",
                "IFD0",
            )
            _append_tiff_value_group_tags(
                decoded_tags,
                read_exif_ifd_values,
                embedded.tiff_data,
                "ExifIFD",
                "Image::ExifTool::Exif::Main",
                "quicktime-pana-embedded-exif-exififd",
                "ExifIFD",
            )
            _append_tiff_value_group_tags(
                decoded_tags,
                read_gps_ifd_values,
                embedded.tiff_data,
                "GPS",
                "Image::ExifTool::GPS::Main",
                "quicktime-pana-embedded-exif-gps",
                "GPS",
            )
            _append_tiff_value_group_tags(
                decoded_tags,
                read_ifd1_values,
                embedded.tiff_data,
                "IFD1",
                "Image::ExifTool::Exif::Main",
                "quicktime-pana-embedded-exif-ifd1",
                "IFD1",
            )
            _append_panasonic_pana_embedded_interop_and_printim_tags(
                decoded_tags,
                embedded.tiff_data,
            )
            maker_note = read_panasonic_maker_note_from_tiff_data(embedded.tiff_data)
            for field in maker_note.fields:
                decoded_tags.append(
                    _read_tag(
                        field.name,
                        field.value,
                        "MakerNotes",
                        PANASONIC_SOURCE_TABLE,
                        f"0x{field.tag_id:04x}",
                        "quicktime-pana-embedded-exif-panasonic-makernote",
                        family_0_group="MakerNotes",
                        family_1_group="Panasonic",
                        family_2_group=field.family_2_group,
                    )
                )
            cached_tags = tuple(decoded_tags)
            state.panasonic_pana_embedded_exif_tag_cache[embedded.tiff_data] = cached_tags
        tags.extend(cached_tags)


def read_panasonic_maker_note_from_tiff_data(tiff_data: bytes) -> PanasonicMakerNoteReadResult:
    from exifmodern.formats.panasonic.read_makernote import (
        read_panasonic_maker_note_from_tiff_data as read,
    )

    return read(tiff_data)


def _append_panasonic_pana_embedded_interop_and_printim_tags(
    tags: list[ReadTag],
    tiff_data: bytes,
) -> None:
    try:
        header = parse_tiff_header(tiff_data)
        ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    except ValueError:
        return
    tags.append(
        _read_tag(
            "ExifByteOrder",
            _tiff_byte_order_value(header.endian),
            "File",
            "Image::ExifTool::Exif::Main",
            "ExifByteOrder",
            "quicktime-pana-embedded-exif-byte-order",
            family_0_group="File",
            family_1_group="File",
            family_2_group="Image",
        )
    )
    printim_version = _embedded_printim_version(tiff_data, ifd0.entries, header.endian)
    if printim_version is not None:
        tags.append(
            _read_tag(
                "PrintIMVersion",
                printim_version,
                "PrintIM",
                "Image::ExifTool::PrintIM::Main",
                "PrintIMVersion",
                "quicktime-pana-embedded-exif-printim",
                family_0_group="PrintIM",
                family_1_group="PrintIM",
                family_2_group="Other",
            )
        )
    exif_ifd = _embedded_pointer_ifd(tiff_data, ifd0.entries, header.endian, 0x8769)
    if exif_ifd is None:
        return
    interop_ifd = _embedded_pointer_ifd(tiff_data, exif_ifd.entries, header.endian, 0xA005)
    if interop_ifd is None:
        return
    for name, tag_id, rendered in _embedded_interop_values(tiff_data, interop_ifd.entries):
        tags.append(
            _read_tag(
                name,
                rendered,
                "InteropIFD",
                "Image::ExifTool::Exif::Interop",
                f"0x{tag_id:04x}",
                "quicktime-pana-embedded-exif-interop",
                family_0_group="EXIF",
                family_1_group="InteropIFD",
                family_2_group="Image",
            )
        )


def _embedded_pointer_ifd(
    tiff_data: bytes,
    entries: Sequence[IfdEntry],
    endian: Endian,
    tag_id: int,
) -> Ifd | None:
    entry = next((candidate for candidate in entries if candidate.tag_id == tag_id), None)
    if entry is None:
        return None
    value = read_entry_value(tiff_data, entry, endian)
    if not isinstance(value, int):
        return None
    try:
        return parse_ifd(tiff_data, value, endian)
    except ValueError:
        return None


def _embedded_printim_version(
    tiff_data: bytes,
    entries: Sequence[IfdEntry],
    endian: Endian,
) -> str | None:
    entry = next((candidate for candidate in entries if candidate.tag_id == 0xC4A5), None)
    if entry is None:
        return None
    value = read_entry_value(tiff_data, entry, endian)
    if not isinstance(value, bytes) or not value.startswith(b"PrintIM\0"):
        return None
    return value[8:12].decode("ascii", errors="replace")


def _embedded_interop_values(
    tiff_data: bytes,
    entries: Sequence[IfdEntry],
) -> tuple[tuple[str, int, str], ...]:
    values: list[tuple[str, int, str]] = []
    for entry in entries:
        if entry.tag_id == 0x0001:
            raw = read_entry_value(tiff_data, entry, "little")
            if isinstance(raw, str):
                values.append(("InteropIndex", entry.tag_id, _interop_index_value(raw)))
        elif entry.tag_id == 0x0002:
            raw = read_entry_value(tiff_data, entry, "little")
            if isinstance(raw, bytes):
                values.append(
                    (
                        "InteropVersion",
                        entry.tag_id,
                        raw.rstrip(b"\0").decode("ascii", errors="replace"),
                    )
                )
    return tuple(values)


def _interop_index_value(value: str) -> str:
    if value == "R98":
        return "R98 - DCF basic file (sRGB)"
    if value == "R03":
        return "R03 - DCF option file (Adobe RGB)"
    if value == "THM":
        return "THM - DCF thumbnail file"
    return value


def _tiff_byte_order_value(endian: Endian) -> str:
    if endian == "little":
        return "Little-endian (Intel, II)"
    return "Big-endian (Motorola, MM)"


type QuickTimeEmbeddedTiffReader = Callable[[bytes], dict[str, JsonValue]]


def _append_tiff_value_group_tags(
    tags: list[ReadTag],
    reader: QuickTimeEmbeddedTiffReader,
    tiff_data: bytes,
    group: str,
    table_name: str,
    source: str,
    family_1_group: str,
) -> None:
    try:
        values = reader(tiff_data)
    except ValueError:
        return
    for name, value in values.items():
        tag_value = _embedded_tiff_tag_value(value)
        if tag_value is None:
            continue
        if name.endswith("IFDPointer"):
            continue
        tags.append(
            _read_tag(
                name,
                tag_value,
                group,
                table_name,
                name,
                source,
                family_0_group=group if group != "Panasonic" else "MakerNotes",
                family_1_group=family_1_group,
                family_2_group=_embedded_tiff_family_2_group(group, name),
            )
        )


def _embedded_tiff_tag_value(value: JsonValue) -> TagValue | None:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        scalars: list[str | int | float | bool | None] = []
        for item in value:
            if isinstance(item, str | int | float | bool) or item is None:
                scalars.append(item)
        if len(scalars) == len(value):
            return scalars
    return None


def _embedded_tiff_family_2_group(group: str, name: str) -> str:
    if group == "ExifIFD" and name in {
        "CreateDate",
        "DateTimeOriginal",
        "OffsetTime",
        "OffsetTimeDigitized",
        "OffsetTimeOriginal",
        "SubSecTime",
        "SubSecTimeDigitized",
        "SubSecTimeOriginal",
    }:
        return "Time"
    if group == "GPS":
        return "Location"
    if group == "IFD1" or name in {"ThumbnailOffset", "ThumbnailLength", "ThumbnailImage"}:
        return "Preview"
    return "Camera" if group in {"IFD0", "ExifIFD"} else "Image"


def _append_xmp_user_data_tags(
    tags: list[ReadTag],
    item: QuickTimeAtomSpan,
    diagnostics: list[str],
) -> None:
    from exifmodern.formats.xmp.reader import parse_xmp_packet

    try:
        groups = parse_xmp_packet(item.payload)
    except ValueError as exc:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_user_data_xmp_payload",
            str(exc),
        )
        return
    for group, values in groups.items():
        for name, value in values.items():
            tag_value = _tag_value(value)
            tags.append(
                _read_tag(
                    name,
                    tag_value,
                    group,
                    _xmp_table_name(group),
                    name,
                    "quicktime-userdata-xmp",
                    family_0_group="XMP",
                    family_1_group=group,
                    family_2_group=_xmp_family_2_group(name),
                )
            )


def _append_spherical_video_uuid_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
) -> None:
    if not payload.startswith(QUICKTIME_SPHERICAL_VIDEO_UUID):
        return
    xml_payload = payload[len(QUICKTIME_SPHERICAL_VIDEO_UUID) :].strip()
    if not xml_payload:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_spherical_video_xml",
            "truncated SphericalVideoXML UUID payload",
        )
        return
    try:
        root = ElementTree.fromstring(xml_payload)
    except ElementTree.ParseError as exc:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_spherical_video_xml",
            f"malformed SphericalVideoXML UUID payload: {exc}",
        )
        return
    for property_id, value in _gspherical_xml_properties(root):
        tag = QUICKTIME_GSPHERICAL_TAGS.get(property_id)
        if tag is None:
            continue
        tag_name, value_format, family_2_group = tag
        rendered = _decode_gspherical_value(value, value_format)
        tags.append(
            _read_tag(
                tag_name,
                rendered,
                "XMP",
                QUICKTIME_GSPHERICAL_TABLE,
                property_id,
                "quicktime-spherical-video-uuid",
                family_0_group="XMP",
                family_1_group="XMP-GSpherical",
                family_2_group=family_2_group,
            )
        )


def _gspherical_xml_properties(
    root: ElementTree.Element[str],
) -> tuple[tuple[str, str], ...]:
    properties: list[tuple[str, str]] = []
    for attr_name, attr_value in root.attrib.items():
        property_id = _gspherical_property_id(attr_name)
        if property_id is not None:
            properties.append((property_id, attr_value))
    for element in root.iter():
        property_id = _gspherical_property_id(element.tag)
        text = element.text.strip() if element.text else ""
        if property_id is not None and text:
            properties.append((property_id, text))
    return tuple(properties)


def _gspherical_property_id(expanded_name: str) -> str | None:
    if expanded_name.startswith("{http://ns.google.com/videos/1.0/spherical/}"):
        return expanded_name.rsplit("}", 1)[1]
    if expanded_name.startswith("GSpherical:"):
        return expanded_name.removeprefix("GSpherical:")
    return None


def _decode_gspherical_value(
    value: str,
    value_format: QuickTimeGSphericalValueFormat,
) -> TagValue:
    if value_format == "boolean":
        lowered = value.strip().lower()
        if lowered in {"true", "1"}:
            return True
        if lowered in {"false", "0"}:
            return False
        return value
    if value_format == "integer":
        try:
            return int(value)
        except ValueError:
            return value
    if value_format == "real":
        try:
            return _compact_number(float(value))
        except ValueError:
            return value
    return value


def _append_3gp_user_data_text_tag(
    tags: list[ReadTag],
    item: QuickTimeAtomSpan,
    tag_name: str,
    family_2_group: str,
    diagnostics: list[str],
) -> None:
    parsed = _parse_itext_payload(item.payload, 6)
    if parsed is None:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_user_data_3gp_payload",
            f"unsupported 3GP UserData {item.atom_type} payload for {tag_name}",
        )
        return
    language, value = parsed
    emitted_name = _language_tag_name(tag_name, language)
    tags.append(
        _read_tag(
            emitted_name,
            value,
            "UserData",
            "Image::ExifTool::QuickTime::UserData",
            item.atom_type,
            "quicktime-metadata-atom",
            family_0_group="QuickTime",
            family_1_group="UserData",
            family_2_group=family_2_group,
        )
    )


def _append_3gp_rating_tag(
    tags: list[ReadTag],
    item: QuickTimeAtomSpan,
    diagnostics: list[str],
) -> None:
    parsed = _parse_itext_payload(item.payload, 14, prefix_size=8)
    if parsed is None:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_user_data_3gp_payload",
            "unsupported 3GP UserData rtng payload for Rating",
        )
        return
    _, value = parsed
    if len(value) < 8:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_user_data_3gp_payload",
            "truncated 3GP UserData rtng value",
        )
        return
    entity = value[:4]
    criteria = value[4:8]
    rating = value[8:].strip()
    rendered = f"Entity={entity} Criteria={criteria} {rating}".rstrip()
    tags.append(
        _read_tag(
            "Rating",
            rendered,
            "UserData",
            "Image::ExifTool::QuickTime::UserData",
            "rtng",
            "quicktime-metadata-atom",
            family_0_group="QuickTime",
            family_1_group="UserData",
            family_2_group="Video",
        )
    )


def _append_3gp_location_information_tag(
    tags: list[ReadTag],
    item: QuickTimeAtomSpan,
    diagnostics: list[str],
) -> None:
    if len(item.payload) < 6:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_user_data_3gp_payload",
            "truncated 3GP UserData loci payload",
        )
        return
    value = _decode_location_information_payload(item.payload[6:])
    if value is None:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_user_data_3gp_payload",
            "unsupported 3GP UserData loci payload for LocationInformation",
        )
        return
    tags.append(
        _read_tag(
            "LocationInformation",
            value,
            "UserData",
            "Image::ExifTool::QuickTime::UserData",
            "loci",
            "quicktime-metadata-atom",
            family_0_group="QuickTime",
            family_1_group="UserData",
            family_2_group="Location",
        )
    )


def _keys_by_meta_atom_id(
    payload: bytes,
    diagnostics: list[str],
) -> dict[str, QuickTimeMetadataTag]:
    keys: dict[str, QuickTimeMetadataTag] = {}
    for index, key_id in enumerate(parse_keys_payload(payload), start=1):
        metadata_tag = QUICKTIME_KEYS_TAGS.get(key_id)
        if metadata_tag is None:
            metadata_tag = _dynamic_quicktime_key_tag(key_id)
        if metadata_tag is None:
            diagnostics.append(f"Unsupported QuickTime mdta key {key_id!r}.")
            continue
        keys[atom_type_from_key_index(index)] = metadata_tag
    return keys


def _dynamic_quicktime_key_tag(key_id: str) -> QuickTimeMetadataTag | None:
    """Mirror QuickTime.pm ProcessKeys dynamic tag creation for reasonable IDs."""
    if not _is_reasonable_quicktime_key_id(key_id):
        return None
    normalized = key_id.removeprefix("com.")
    name = _quicktime_dynamic_key_name(normalized)
    if len(name) < 2:
        name = f"Tag_{name}"
    return QuickTimeMetadataTag("Keys", name, "", key_id)


def _is_reasonable_quicktime_key_id(key_id: str) -> bool:
    if not key_id:
        return False
    return all(char.isalnum() or char in {"-", "_", ".", " "} for char in key_id)


def _quicktime_dynamic_key_name(key_id: str) -> str:
    name_parts: list[str] = []
    capitalize_next = True
    previous_was_lower = False
    for char in key_id:
        if char in {".", " "}:
            capitalize_next = True
            previous_was_lower = False
            continue
        if char == "_":
            capitalize_next = True
            name_parts.append(char)
            previous_was_lower = False
            continue
        if char == "-" or char.isdigit():
            name_parts.append(char)
            capitalize_next = False
            previous_was_lower = False
            continue
        if capitalize_next:
            name_parts.append(char.upper())
        elif previous_was_lower and char == "_":
            name_parts.append(char)
        else:
            name_parts.append(char)
        capitalize_next = False
        previous_was_lower = char.islower()
    return "".join(name_parts)


def _quicktime_data_atom_language_code(country: int, language: int) -> str | None:
    language_code = _quicktime_language_code_from_int(language)
    country_code = _quicktime_country_code_from_int(country)
    if language_code is None:
        return country_code
    if country_code is None:
        return language_code
    return f"{language_code}-{country_code}"


def _quicktime_language_code_from_int(language: int) -> str | None:
    if language == 0:
        return None
    chars = "".join(chr(((language >> shift) & 0x1F) + 0x60) for shift in (10, 5, 0))
    if chars.isalpha():
        return chars
    return None


def _quicktime_country_code_from_int(country: int) -> str | None:
    if country == 0:
        return None
    first = (country >> 8) & 0xFF
    second = country & 0xFF
    if 0x41 <= first <= 0x5A and 0x41 <= second <= 0x5A:
        return f"{chr(first)}{chr(second)}"
    return None


def _decode_user_data_value(payload: bytes, metadata_tag: QuickTimeMetadataTag) -> TagValue | None:
    if metadata_tag.atom_id.startswith("\xa9"):
        parsed = parse_user_data_text_value(payload)
        if parsed is None:
            return None
        _, value = parsed
        text = value.rstrip(b"\0").decode("utf-8", errors="replace")
    else:
        text = payload.rstrip(b"\0").decode("utf-8", errors="replace")
    if metadata_tag.item_list_format == "gps_iso6709":
        return _gps_coordinates_from_iso6709(text) or text
    return text


def _decode_user_data_control_value(payload: bytes, value_format: str) -> TagValue | None:
    if value_format == "int16u_pair":
        if len(payload) < 4:
            return None
        return f"{int.from_bytes(payload[:2], 'big')} {int.from_bytes(payload[2:4], 'big')}"
    if value_format == "loop_style":
        if len(payload) < 4:
            return None
        value = int.from_bytes(payload[:4], "big")
        return QUICKTIME_USER_DATA_LOOP_STYLE.get(value, value)
    if value_format == "int8u":
        if not payload:
            return None
        return payload[0]
    if value_format == "itext4":
        parsed = _parse_itext_payload(payload, 4)
        if parsed is None:
            return None
        return parsed[1]
    return None


def _parse_itext_payload(
    payload: bytes,
    header_size: int,
    *,
    prefix_size: int = 0,
) -> tuple[str | None, str] | None:
    if header_size < 4 or len(payload) < header_size:
        return None
    language_offset = header_size - 2
    language = _language_code(int.from_bytes(payload[language_offset:header_size], "big"))
    value_start = header_size
    value = payload[value_start:]
    if prefix_size:
        prefix_start = value_start - prefix_size - 2
        if prefix_start < 0:
            return None
        value = payload[prefix_start : value_start - 2] + value
    text = _decode_international_text(value)
    language_text = language if isinstance(language, str) and language != "und" else None
    return language_text, text.rstrip("\0")


def _decode_international_text(value: bytes) -> str:
    if value.startswith(b"\xfe\xff"):
        return value[2:].decode("utf-16-be", errors="replace")
    return value.decode("utf-8", errors="replace")


def _language_tag_name(tag_name: str, language: str | None) -> str:
    return f"{tag_name}-{language}" if language else tag_name


def _decode_location_information_payload(payload: bytes) -> str | None:
    name, offset = _read_null_terminated_international_text(payload, 0)
    if name is None or offset + 13 > len(payload):
        return None
    rendered = name or "(none)"
    role = payload[offset]
    longitude = _fixed_signed(payload[offset + 1 : offset + 5], 16)
    latitude = _fixed_signed(payload[offset + 5 : offset + 9], 16)
    altitude = _fixed_signed(payload[offset + 9 : offset + 13], 16)
    role_text = {
        0: "shooting",
        1: "real",
        2: "fictional",
        3: "reserved",
    }.get(role, f"unknown({role})")
    rendered += f" Role={role_text} Lat={latitude:.5f} Lon={longitude:.5f} Alt={altitude:.2f}"
    body, offset = _read_null_terminated_international_text(payload, offset + 13)
    if body is not None:
        rendered += f" Body={body}"
    notes, _ = _read_null_terminated_international_text(payload, offset)
    if notes is not None:
        rendered += f" Notes={notes}"
    return rendered


def _read_null_terminated_international_text(
    payload: bytes,
    offset: int,
) -> tuple[str | None, int]:
    if offset > len(payload):
        return None, offset
    if payload[offset : offset + 2] == b"\xfe\xff":
        cursor = offset + 2
        while cursor + 1 < len(payload):
            if payload[cursor : cursor + 2] == b"\0\0":
                text = payload[offset + 2 : cursor].decode("utf-16-be", errors="replace")
                return text, cursor + 2
            cursor += 2
        return None, len(payload)
    terminator = payload.find(b"\0", offset)
    if terminator < 0:
        return None, len(payload)
    return payload[offset:terminator].decode("utf-8", errors="replace"), terminator + 1


def _matched_user_data_manufacturer_tag(payload: bytes) -> str | None:
    for prefix, tag_name in QUICKTIME_USER_DATA_MANUFACTURER_PREFIXES.items():
        if payload.startswith(prefix):
            return tag_name
    return None


def _decode_user_data_manufacturer_scalar(
    payload: bytes,
    value_format: QuickTimeUserDataScalarFormat,
) -> TagValue | None:
    if value_format == "binary":
        if not payload:
            return None
        return BinaryTagValue(payload)
    if value_format == "hex":
        if not payload:
            return None
        return payload.hex()
    if value_format == "strip_version_header":
        if len(payload) <= 4:
            return None
        return _decode_null_terminated_text(payload[4:])
    if value_format == "string":
        return _decode_null_terminated_text(payload)
    if value_format == "bytes_text":
        return _decode_null_terminated_text(payload)
    return None


def _decode_null_terminated_text(payload: bytes) -> str | None:
    if not payload:
        return None
    value = payload.split(b"\0", 1)[0].decode("utf-8", errors="replace")
    return value or None


def _decode_quicktime_data_value(
    value: bytes,
    value_format: str,
) -> TagValue | None:
    if not value:
        return None
    if value_format == "int8s":
        return int.from_bytes(value[:1], "big", signed=True)
    if value_format == "int16s":
        return int.from_bytes(value[:2], "big", signed=True)
    if value_format == "int8u":
        return int.from_bytes(value[:1], "big", signed=False)
    if value_format == "int16u":
        return int.from_bytes(value[:2], "big", signed=False)
    if value_format == "int32s":
        return int.from_bytes(value[:4], "big", signed=True)
    if value_format == "int32u":
        return int.from_bytes(value[:4], "big", signed=False)
    if value_format == "int64s":
        return int.from_bytes(value[:8], "big", signed=True)
    if value_format == "int64u":
        return int.from_bytes(value[:8], "big", signed=False)
    if value_format == "float" and len(value) >= 4:
        return _compact_number(struct.unpack(">f", value[:4])[0])
    if value_format == "double" and len(value) >= 8:
        return _compact_number(struct.unpack(">d", value[:8])[0])
    if value_format in {"track_number", "disk_number"}:
        return _decode_number_pair(value)
    if value_format == "yes_no_int8s":
        return _lookup_int_value(value, lookup=QUICKTIME_YES_NO)
    if value_format == "play_gap":
        return _lookup_int_value(value, lookup=QUICKTIME_PLAY_GAP)
    if value_format == "apple_store_account_type":
        return _lookup_int_value(value, lookup=QUICKTIME_APPLE_STORE_ACCOUNT_TYPE)
    if value_format == "content_rating":
        return _lookup_int_value(value, lookup=QUICKTIME_CONTENT_RATING)
    if value_format == "media_type":
        return _lookup_int_value(value, lookup=QUICKTIME_MEDIA_TYPE)
    if value_format == "binary":
        return BinaryTagValue(value)
    text = value.rstrip(b"\0").decode("utf-8", errors="replace")
    if value_format == "milliseconds_text" and text.isdigit():
        return _duration(int(text), 1000)
    if value_format == "gps_iso6709":
        return _gps_coordinates_from_iso6709(text) or text
    return text


def _lookup_int_value(
    value: bytes,
    *,
    lookup: dict[int, str],
) -> int | str | None:
    if not value:
        return None
    number = int.from_bytes(value[:1], "big", signed=False)
    return lookup.get(number, number)


def _decode_number_pair(value: bytes) -> str | None:
    if len(value) < 6:
        return None
    current = int.from_bytes(value[2:4], "big")
    total = int.from_bytes(value[4:6], "big")
    return f"{current} of {total}" if total else str(current)


def _gps_coordinates_from_iso6709(value: str) -> str | None:
    text = value.strip().removesuffix("/")
    if not text or text[0] not in "+-":
        return None
    parts: list[str] = []
    start = 0
    for index in range(1, len(text)):
        if text[index] in "+-":
            parts.append(text[start:index])
            start = index
    parts.append(text[start:])
    if len(parts) < 2:
        return None
    try:
        numbers = tuple(float(part) for part in parts[:3])
    except ValueError:
        return None
    return ", ".join(_compact_number(number) for number in numbers)


def _printable_atom_id(atom_type: str) -> str:
    return "".join(
        char if 0x20 <= ord(char) <= 0x7E else f"\\x{ord(char):02x}" for char in atom_type
    )


def _quicktime_metadata_tag(
    metadata_tag: QuickTimeMetadataTag,
    value: TagValue,
    tag_id: str,
    *,
    tag_name: str | None = None,
) -> ReadTag:
    group = metadata_tag.group
    return _read_tag(
        tag_name or metadata_tag.name,
        value,
        group,
        f"Image::ExifTool::QuickTime::{group}",
        tag_id,
        "quicktime-metadata-atom",
        family_2_group=_quicktime_metadata_family_2(metadata_tag.name),
    )


def _quicktime_metadata_family_2(name: str) -> str:
    return {
        "Album": "Audio",
        "AlbumArtist": "Author",
        "Artist": "Audio",
        "BeatsPerMinute": "Audio",
        "Comment": "Audio",
        "Compilation": "Audio",
        "Composer": "Audio",
        "Author": "Author",
        "Copyright": "Author",
        "CreationDate": "Time",
        "ContentCreateDate": "Time",
        "DiskNumber": "Audio",
        "Encoder": "Audio",
        "Genre": "Audio",
        "Grouping": "Audio",
        "Lyrics": "Audio",
        "PlayGap": "Audio",
        "Title": "Audio",
        "TrackNumber": "Audio",
        "LocationDate": "Time",
        "GPSCoordinates": "Location",
        "LocationBody": "Location",
        "LocationName": "Location",
        "LocationNote": "Location",
        "LocationRole": "Location",
        "CameraDirection": "Location",
        "CameraMotion": "Location",
        "Make": "Camera",
        "Model": "Camera",
    }.get(name, "Video")


def _xmp_table_name(group: str) -> str:
    if group.startswith("XMP-"):
        return f"{QUICKTIME_XMP_TABLE_PREFIX}{group[4:]}"
    return "Image::ExifTool::XMP::Main"


def _xmp_family_2_group(name: str) -> str:
    return {
        "CreateDate": "Time",
        "DateCreated": "Time",
        "MetadataDate": "Time",
        "ModifyDate": "Time",
        "Title": "Image",
    }.get(name, "Other")


def _append_audio_sample_tags(
    tags: list[ReadTag],
    audio_format: str,
    payload: bytes,
    diagnostics: list[str],
) -> None:
    tags.append(
        _quicktime_tag(
            "AudioFormat",
            audio_format,
            "stsd",
            table_name=QUICKTIME_AUDIO_SAMPLE_DESC_TABLE,
            family_2_group="Audio",
        )
    )
    if len(payload) < 28:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_audio_sample_payload",
            f"truncated AudioSampleDesc for {audio_format!r}",
        )
        return
    vendor = payload[12:16].decode("latin-1", errors="replace").strip("\0")
    if vendor and audio_format != "mp4s":
        tags.append(
            _quicktime_tag(
                "AudioVendorID",
                QUICKTIME_VENDOR_IDS.get(vendor, vendor),
                "stsd",
                table_name=QUICKTIME_AUDIO_SAMPLE_DESC_TABLE,
                family_2_group="Audio",
            )
        )
    tags.append(
        _quicktime_tag(
            "AudioChannels",
            int.from_bytes(payload[16:18], "big"),
            "stsd",
            table_name=QUICKTIME_AUDIO_SAMPLE_DESC_TABLE,
            family_2_group="Audio",
        )
    )
    tags.append(
        _quicktime_tag(
            "AudioBitsPerSample",
            int.from_bytes(payload[18:20], "big"),
            "stsd",
            table_name=QUICKTIME_AUDIO_SAMPLE_DESC_TABLE,
            family_2_group="Audio",
        )
    )
    tags.append(
        _quicktime_tag(
            "AudioSampleRate",
            int(_fixed_unsigned(payload[24:28], 16)),
            "stsd",
            table_name=QUICKTIME_AUDIO_SAMPLE_DESC_TABLE,
            family_2_group="Audio",
        )
    )
    for child in _hybrid_child_atoms(payload, min_binary_size=28):
        if child.atom_type == "btrt":
            _append_child_bitrate_tags(tags, child.payload, family_2_group="Audio")
        elif child.atom_type == "wave":
            _append_wave_tags(tags, child.payload, diagnostics)
        elif child.atom_type == "chan":
            _append_channel_layout_tags(tags, child.payload, diagnostics)
        elif child.atom_type == "damr":
            _append_decode_config_tags(tags, child.payload, diagnostics)
        elif child.atom_type == "esds":
            _append_unknown_child_binary_tag(
                tags,
                child,
                table_name=QUICKTIME_AUDIO_SAMPLE_DESC_TABLE,
                family_2_group="Audio",
            )
        elif child.atom_type in {"pinf", "sinf"}:
            _append_protection_info_tags(
                tags,
                child.payload,
                diagnostics,
                parent_atom=child.atom_type,
            )
        elif child.atom_type == "SA3D":
            _append_spatial_audio_tags(tags, child.payload, diagnostics)
        elif child.atom_type in {"alac", "dac3"}:
            _append_quicktime_diagnostic(
                diagnostics,
                "deferred_audio_sample_child",
                (
                    f"deferred AudioSampleDesc child atom "
                    f"{_printable_atom_id(child.atom_type)!r} subdirectory adapter; "
                    "QuickTime.pm records this codec payload in AudioSampleDesc comments but "
                    "defines no local tag table"
                ),
            )
        elif child.atom_type not in QUICKTIME_SUPPORTED_AUDIO_SAMPLE_CHILDREN:
            _append_quicktime_diagnostic(
                diagnostics,
                "unsupported_audio_sample_child",
                f"unsupported AudioSampleDesc child atom {_printable_atom_id(child.atom_type)!r}",
            )


def _append_video_sample_tags(
    tags: list[ReadTag],
    compressor_id: str,
    payload: bytes,
    diagnostics: list[str],
) -> None:
    tags.append(
        _quicktime_tag(
            "CompressorID",
            compressor_id,
            "stsd",
            table_name=QUICKTIME_VISUAL_SAMPLE_DESC_TABLE,
            family_2_group="Image",
        )
    )
    if len(payload) < 78:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_video_sample_payload",
            f"truncated VisualSampleDesc for {compressor_id!r}",
        )
        return
    vendor = payload[12:16].decode("latin-1", errors="replace").strip("\0")
    if vendor:
        tags.append(
            _quicktime_tag(
                "VendorID",
                QUICKTIME_VENDOR_IDS.get(vendor, vendor),
                "stsd",
                table_name=QUICKTIME_VISUAL_SAMPLE_DESC_TABLE,
                family_2_group="Image",
            )
        )
    tags.extend(
        (
            _quicktime_tag(
                "SourceImageWidth",
                int.from_bytes(payload[24:26], "big"),
                "stsd",
                table_name=QUICKTIME_VISUAL_SAMPLE_DESC_TABLE,
                family_2_group="Image",
            ),
            _quicktime_tag(
                "SourceImageHeight",
                int.from_bytes(payload[26:28], "big"),
                "stsd",
                table_name=QUICKTIME_VISUAL_SAMPLE_DESC_TABLE,
                family_2_group="Image",
            ),
            _quicktime_tag(
                "XResolution",
                int(_fixed_unsigned(payload[28:32], 16)),
                "stsd",
                table_name=QUICKTIME_VISUAL_SAMPLE_DESC_TABLE,
                family_2_group="Image",
            ),
            _quicktime_tag(
                "YResolution",
                int(_fixed_unsigned(payload[32:36], 16)),
                "stsd",
                table_name=QUICKTIME_VISUAL_SAMPLE_DESC_TABLE,
                family_2_group="Image",
            ),
            _quicktime_tag(
                "BitDepth",
                int.from_bytes(payload[74:76], "big"),
                "stsd",
                table_name=QUICKTIME_VISUAL_SAMPLE_DESC_TABLE,
                family_2_group="Image",
            ),
        )
    )
    compressor_name = _compressor_name(payload[42:74])
    if compressor_name:
        tags.append(
            _quicktime_tag(
                "CompressorName",
                compressor_name,
                "stsd",
                table_name=QUICKTIME_VISUAL_SAMPLE_DESC_TABLE,
                family_2_group="Video",
            )
        )
    _append_video_child_tags(tags, payload, diagnostics)


def _append_video_child_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
) -> None:
    for child in _hybrid_child_atoms(payload, min_binary_size=78):
        if child.atom_type == "avcC":
            _append_avc_configuration_tags(tags, child.payload, diagnostics)
        elif child.atom_type == "hvcC":
            _append_hevc_configuration_tags(tags, child.payload, diagnostics)
        elif child.atom_type == "btrt":
            _append_child_bitrate_tags(tags, child.payload, family_2_group="Video")
        elif child.atom_type == "pasp" and len(child.payload) >= 8:
            h_spacing = int.from_bytes(child.payload[:4], "big")
            v_spacing = int.from_bytes(child.payload[4:8], "big")
            tags.append(
                _quicktime_tag(
                    "PixelAspectRatio",
                    f"{h_spacing}:{v_spacing}",
                    "pasp",
                    table_name=QUICKTIME_VISUAL_SAMPLE_DESC_TABLE,
                    family_2_group="Video",
                )
            )
        elif child.atom_type == "colr":
            _append_color_tags(tags, child.payload, diagnostics)
        elif child.atom_type == "fiel" and len(child.payload) >= 2:
            order = "Progressive" if child.payload[0] == 1 else str(child.payload[0])
            tags.append(
                _quicktime_tag(
                    "VideoFieldOrder",
                    f"{order}; {child.payload[1]}",
                    "fiel",
                    table_name=QUICKTIME_VISUAL_SAMPLE_DESC_TABLE,
                    family_2_group="Video",
                )
            )
        elif child.atom_type == "gama" and len(child.payload) >= 4:
            tags.append(
                _quicktime_tag(
                    "Gamma",
                    _compact_number(_fixed_unsigned(child.payload[:4], 16)),
                    "gama",
                    table_name=QUICKTIME_VISUAL_SAMPLE_DESC_TABLE,
                    family_2_group="Video",
                )
            )
        elif child.atom_type == "clap":
            _append_clean_aperture_tags(tags, child.payload, diagnostics)
        elif child.atom_type == "esds":
            _append_unknown_child_binary_tag(
                tags,
                child,
                table_name=QUICKTIME_VISUAL_SAMPLE_DESC_TABLE,
                family_2_group="Video",
            )
        elif child.atom_type not in QUICKTIME_SUPPORTED_VIDEO_SAMPLE_CHILDREN:
            _append_quicktime_diagnostic(
                diagnostics,
                "unsupported_video_sample_child",
                f"unsupported VisualSampleDesc child atom {_printable_atom_id(child.atom_type)!r}",
            )


def _append_hint_sample_tags(
    tags: list[ReadTag],
    hint_format: str,
    payload: bytes,
    diagnostics: list[str],
) -> None:
    tags.append(_quicktime_tag("HintFormat", hint_format, "stsd", family_2_group="Video"))
    if len(payload) < 16:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_hint_sample_payload",
            f"truncated HintSampleDesc for {hint_format!r}",
        )
        return
    tags.append(
        _quicktime_tag(
            "HintTrackVersion",
            int.from_bytes(payload[8:10], "big"),
            "stsd",
            family_2_group="Video",
        )
    )
    tags.append(
        _quicktime_tag(
            "MaxPacketSize",
            int.from_bytes(payload[12:16], "big"),
            "stsd",
            family_2_group="Video",
        )
    )
    for child in _hybrid_child_atoms(payload, min_binary_size=16):
        if child.atom_type in {"tims", "tsro", "snro"}:
            _append_int32_child_tag(
                tags,
                child.payload,
                {
                    "tims": "RTPTimeScale",
                    "tsro": "TimestampRandomOffset",
                    "snro": "SequenceNumberRandomOffset",
                }[child.atom_type],
                child.atom_type,
                diagnostics,
                diagnostic_label="HintSampleDesc",
            )
        elif child.atom_type not in QUICKTIME_SUPPORTED_HINT_SAMPLE_CHILDREN:
            _append_quicktime_diagnostic(
                diagnostics,
                "unsupported_hint_sample_child",
                f"unsupported HintSampleDesc child atom {_printable_atom_id(child.atom_type)!r}",
            )


def _append_meta_sample_tags(
    tags: list[ReadTag],
    meta_format: str,
    payload: bytes,
    diagnostics: list[str],
) -> None:
    tags.append(_quicktime_tag("MetaFormat", meta_format, "stsd", family_2_group="Video"))
    meta_type = _metadata_sample_type(payload)
    if meta_type:
        tags.append(_quicktime_tag("MetaType", meta_type, "stsd", family_2_group="Video"))
    for child in _hybrid_child_atoms(payload, min_binary_size=16):
        if child.atom_type == "btrt":
            _append_child_bitrate_tags(tags, child.payload, family_2_group="Video")
        elif child.atom_type == "keys":
            continue
        elif child.atom_type not in QUICKTIME_SUPPORTED_META_SAMPLE_CHILDREN:
            _append_quicktime_diagnostic(
                diagnostics,
                "unsupported_meta_sample_child",
                f"unsupported MetaSampleDesc child atom {_printable_atom_id(child.atom_type)!r}",
            )


def _append_timed_metadata_sample_tags(
    tags: list[ReadTag],
    trak: QuickTimeAtomSpan,
    track_atoms: tuple[QuickTimeAtomSpan, ...],
    media_time_scale: int | None,
    diagnostics: list[str],
    path: Path,
) -> None:
    meta_format, keys = _meta_sample_description_keys(track_atoms, diagnostics)
    if not keys:
        return
    if meta_format != "mebx":
        _append_quicktime_diagnostic(
            diagnostics,
            "deferred_meta_sample_child",
            (
                f"deferred MetaSampleDesc child atom 'keys' for MetaFormat {meta_format!r}; "
                "QuickTimeStream.pl ProcessSamples only routes this bounded adapter through "
                "Process_mebx"
            ),
        )
        return
    sample_plan = _timed_metadata_sample_plan(track_atoms, media_time_scale, diagnostics)
    if sample_plan is None:
        _append_quicktime_diagnostic(
            diagnostics,
            "deferred_meta_sample_child",
            (
                "deferred MetaSampleDesc child atom 'keys' adapter; QuickTime.pm "
                "ProcessSamples requires stco/co64, stsc and stsz/stz2 sample tables before "
                "timed metadata samples can be read"
            ),
        )
        return
    for sample_index, (sample_offset, sample_size, timing) in enumerate(sample_plan):
        if sample_index >= QUICKTIME_TIMED_METADATA_MAX_SAMPLES:
            _append_quicktime_diagnostic(
                diagnostics,
                "deferred_meta_sample_child",
                (
                    "deferred remaining mebx timed metadata samples after bounded "
                    f"{QUICKTIME_TIMED_METADATA_MAX_SAMPLES} sample limit"
                ),
            )
            return
        if sample_size > QUICKTIME_TIMED_METADATA_MAX_SAMPLE_BYTES:
            _append_quicktime_diagnostic(
                diagnostics,
                "deferred_meta_sample_child",
                (
                    f"deferred mebx timed metadata sample {sample_index + 1}; sample size "
                    f"{sample_size} exceeds bounded "
                    f"{QUICKTIME_TIMED_METADATA_MAX_SAMPLE_BYTES} byte limit"
                ),
            )
            continue
        try:
            with path.open("rb") as file:
                file.seek(sample_offset)
                sample = file.read(sample_size)
        except OSError as exc:
            _append_quicktime_diagnostic(
                diagnostics,
                "deferred_meta_sample_child",
                f"deferred mebx timed metadata sample {sample_index + 1}; seek/read failed: {exc}",
            )
            continue
        if len(sample) != sample_size:
            _append_quicktime_diagnostic(
                diagnostics,
                "deferred_meta_sample_child",
                f"deferred mebx timed metadata sample {sample_index + 1}; truncated sample data",
            )
            continue
        emitted = _append_mebx_sample_tags(tags, sample, keys, diagnostics)
        if emitted:
            if timing.sample_time is not None:
                tags.append(
                    _quicktime_table_tag(
                        "SampleTime",
                        _duration_from_seconds(timing.sample_time),
                        "SampleTime",
                        QUICKTIME_STREAM_TABLE,
                    )
                )
            if timing.sample_duration is not None:
                tags.append(
                    _quicktime_table_tag(
                        "SampleDuration",
                        _duration_from_seconds(timing.sample_duration),
                        "SampleDuration",
                        QUICKTIME_STREAM_TABLE,
                    )
                )


def _meta_sample_description_keys(
    track_atoms: tuple[QuickTimeAtomSpan, ...],
    diagnostics: list[str],
) -> tuple[str | None, dict[str, QuickTimeTimedMetadataKey]]:
    for atom in track_atoms:
        if atom.atom_type != "stsd" or len(atom.payload) < 8:
            continue
        entry_count = int.from_bytes(atom.payload[4:8], "big")
        offset = 8
        for _ in range(entry_count):
            if offset + 8 > len(atom.payload):
                return None, {}
            size = int.from_bytes(atom.payload[offset : offset + 4], "big")
            if size < 8 or offset + size > len(atom.payload):
                return None, {}
            meta_format = atom.payload[offset + 4 : offset + 8].decode("latin-1", errors="replace")
            sample_payload = atom.payload[offset + 8 : offset + size]
            keys: dict[str, QuickTimeTimedMetadataKey] = {}
            for child in _hybrid_child_atoms(sample_payload, min_binary_size=16):
                if child.atom_type == "keys":
                    keys.update(_timed_metadata_keys(child.payload, diagnostics))
            if keys:
                return meta_format, keys
            offset += size
    return None, {}


def _timed_metadata_keys(
    payload: bytes,
    diagnostics: list[str],
) -> dict[str, QuickTimeTimedMetadataKey]:
    keys: dict[str, QuickTimeTimedMetadataKey] = {}
    offset = 0
    while offset + QT_ATOM_HEADER_SIZE < len(payload):
        size = int.from_bytes(payload[offset : offset + 4], "big")
        if size < QT_ATOM_HEADER_SIZE or offset + size > len(payload):
            break
        local_id = payload[offset + 4 : offset + 8].decode("latin-1", errors="replace")
        entry_payload = payload[offset + 8 : offset + size]
        tag_id: str | None = None
        value_format: str | None = None
        for child in _parse_child_atoms(entry_payload, 0):
            if child.atom_type == "keyd":
                tag_id = _timed_metadata_key_id(child.payload)
            elif child.atom_type == "dtyp":
                value_format = _timed_metadata_format(child.payload)
        if tag_id is not None and value_format is not None:
            keys[local_id] = QuickTimeTimedMetadataKey(local_id, tag_id, value_format)
        offset += size
    if payload and not keys:
        _append_quicktime_diagnostic(
            diagnostics,
            "deferred_meta_sample_child",
            (
                "deferred MetaSampleDesc child atom 'keys' adapter; no complete keyd/dtyp "
                "timed metadata key entries were found"
            ),
        )
    return keys


def _timed_metadata_key_id(payload: bytes) -> str:
    value = payload.rstrip(b"\0").decode("latin-1", errors="replace")
    for prefix in ("mdtacom.apple.quicktime.", "fielcom.apple.quicktime."):
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return value or f"Tag_{payload.decode('latin-1', errors='replace')}"


def _timed_metadata_format(payload: bytes) -> str:
    if len(payload) < 4:
        return "undef"
    namespace = int.from_bytes(payload[:4], "big")
    if namespace == 0 and len(payload) >= 8:
        data_type = int.from_bytes(payload[4:8], "big")
        return QUICKTIME_TIMED_METADATA_FORMATS.get(data_type, "undef")
    return "undef"


def _timed_metadata_sample_plan(
    track_atoms: tuple[QuickTimeAtomSpan, ...],
    media_time_scale: int | None,
    diagnostics: list[str],
) -> tuple[tuple[int, int, QuickTimeSampleTiming], ...] | None:
    sample_sizes: tuple[int, ...] = ()
    chunk_offsets: tuple[int, ...] = ()
    sample_to_chunk: tuple[tuple[int, int, int], ...] = ()
    time_entries: tuple[tuple[int, int], ...] = ()
    for atom in track_atoms:
        if atom.atom_type == "stsz":
            sample_sizes = _sample_sizes(atom.payload)
        elif atom.atom_type == "stco":
            chunk_offsets = _chunk_offsets(atom.payload, field_size=4)
        elif atom.atom_type == "co64":
            chunk_offsets = _chunk_offsets(atom.payload, field_size=8)
        elif atom.atom_type == "stsc":
            sample_to_chunk = _sample_to_chunk_entries(atom.payload)
        elif atom.atom_type == "stts":
            time_entries = _time_to_sample_entries(atom.payload) or ()
    if not sample_sizes or not chunk_offsets or not sample_to_chunk:
        return None
    starts = _sample_start_offsets(sample_sizes, chunk_offsets, sample_to_chunk)
    if len(starts) != len(sample_sizes):
        _append_quicktime_diagnostic(
            diagnostics,
            "deferred_meta_sample_child",
            "deferred mebx timed metadata samples; sample start/size count mismatch",
        )
        return None
    timings = _sample_timings(len(sample_sizes), time_entries, media_time_scale)
    return tuple(
        (sample_offset, sample_sizes[index], timings[index])
        for index, sample_offset in enumerate(starts)
    )


def _append_h264_sample_stream_tags(
    tags: list[ReadTag],
    track_atoms: tuple[QuickTimeAtomSpan, ...],
    state: QuickTimeReadState,
    diagnostics: list[str],
    path: Path,
) -> None:
    avcc = _h264_avc_configuration_payload_from_atoms(track_atoms)
    if avcc is None:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_sample_parse_blocked",
            "deferred H264 sample parsing; no avcC payload was available",
        )
        return
    ranges = _h264_sample_byte_ranges(track_atoms, state.mdat_ranges, diagnostics)
    if not ranges:
        return
    state.h264_sample_ranges_planned = True
    tags.extend(_h264_sample_range_tags(ranges))
    _append_h264_ranges_as_stream_tags(tags, ranges, avcc, state, diagnostics, path)


def _append_h264_fragment_stream_tags(
    tags: list[ReadTag],
    movie_fragments: tuple[QuickTimeAtomSpan, ...],
    state: QuickTimeReadState,
    diagnostics: list[str],
    path: Path,
) -> None:
    avcc = state.h264_avc_configuration_payload
    if avcc is None:
        return
    ranges = _h264_fragment_sample_byte_ranges(movie_fragments, state, diagnostics)
    if not ranges:
        return
    state.h264_sample_ranges_planned = True
    tags.extend(_h264_sample_range_tags(ranges))
    _append_h264_ranges_as_stream_tags(
        tags,
        ranges,
        avcc,
        state,
        diagnostics,
        path,
        avcc_by_track_id=state.h264_track_avc_configuration_payloads,
    )


def _append_h264_ranges_as_stream_tags(
    tags: list[ReadTag],
    ranges: tuple[QuickTimeSampleByteRange, ...],
    avcc: bytes,
    state: QuickTimeReadState,
    diagnostics: list[str],
    path: Path,
    *,
    avcc_by_track_id: dict[int, bytes] | None = None,
) -> None:
    if len(ranges) > QUICKTIME_H264_MAX_SAMPLES:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_sample_parse_blocked",
            (
                f"deferred H264 sample parsing after planning {len(ranges)} ranges; "
                f"bounded parser currently allows {QUICKTIME_H264_MAX_SAMPLES} samples"
            ),
        )
        return
    total_size = sum(sample_range.size for sample_range in ranges)
    if total_size > QUICKTIME_H264_MAX_TOTAL_SAMPLE_BYTES:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_sample_parse_blocked",
            (
                f"deferred H264 sample parsing for {total_size} bytes of samples; bounded "
                f"parser currently allows {QUICKTIME_H264_MAX_TOTAL_SAMPLE_BYTES} bytes"
            ),
        )
        return
    annex_b_samples: list[bytes] = []
    for sample_range in ranges:
        if sample_range.size > QUICKTIME_H264_MAX_SAMPLE_BYTES:
            _append_quicktime_diagnostic(
                diagnostics,
                "quicktime_h264_sample_parse_blocked",
                (
                    f"deferred H264 sample {sample_range.sample_index}; sample size "
                    f"{sample_range.size} exceeds bounded {QUICKTIME_H264_MAX_SAMPLE_BYTES} bytes"
                ),
            )
            return
        sample = _read_exact_sample(path, sample_range, diagnostics)
        if sample is None:
            return
        sample_avcc = avcc
        if sample_range.track_id is not None and avcc_by_track_id:
            sample_avcc = avcc_by_track_id.get(sample_range.track_id, avcc)
        hdr_len = (sample_avcc[4] & 0x03) + 1
        state.h264_sample_bytes_read += len(sample)
        annex_b_samples.append(
            _quicktime_h264_sample_to_annex_b(sample, hdr_len, sample_range, diagnostics)
        )
    h264_data = b"".join(annex_b_samples)
    if not h264_data:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_sample_parse_blocked",
            "deferred H264 sample parsing; no complete length-prefixed NAL units were found",
        )
        return
    from exifmodern.formats.h264.stream_transaction_plan import build_h264_stream_transaction_plan

    plan = build_h264_stream_transaction_plan(h264_data)
    tags.extend(
        (
            _quicktime_table_tag(
                "H264SampleCount",
                len(ranges),
                "ProcessSamples",
                QUICKTIME_STREAM_TABLE,
            ),
            _quicktime_table_tag(
                "H264SampleByteCount",
                state.h264_sample_bytes_read,
                "ProcessSamples",
                QUICKTIME_STREAM_TABLE,
            ),
            _quicktime_table_tag(
                "H264NALUnitCount",
                len(plan.nal_units),
                "ParseH264Video",
                QUICKTIME_STREAM_TABLE,
            ),
        )
    )
    for read_tag in plan.read_tags:
        tags.append(
            _read_tag(
                read_tag.name,
                _tag_value(read_tag.value),
                read_tag.group,
                read_tag.table_name,
                read_tag.tag_id,
                "quicktime-h264-sample-dispatch",
                family_2_group=read_tag.group,
            )
        )
    blocking_gates = [
        gate.code
        for gate in plan.output_emission_gates
        if gate.code != "non_mutating_plan_requires_explicit_emission"
    ]
    if plan.status == "unsupported" or blocking_gates:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_sample_parse_blocked",
            (
                "bounded QuickTimeStream H264 sample dispatch found unsupported H264 "
                f"state: {', '.join(blocking_gates) or plan.status}"
            ),
        )


def _h264_avc_configuration_payload_from_atoms(
    track_atoms: tuple[QuickTimeAtomSpan, ...],
) -> bytes | None:
    for atom in track_atoms:
        if atom.atom_type != "stsd" or len(atom.payload) < 8:
            continue
        entry_count = int.from_bytes(atom.payload[4:8], "big")
        offset = 8
        for _ in range(entry_count):
            if offset + 8 > len(atom.payload):
                return None
            size = int.from_bytes(atom.payload[offset : offset + 4], "big")
            sample_format = atom.payload[offset + 4 : offset + 8].decode(
                "latin-1", errors="replace"
            )
            if size < 8 or offset + size > len(atom.payload):
                return None
            sample_payload = atom.payload[offset + 8 : offset + size]
            if sample_format in {"avc1", "avc3"}:
                for child in _hybrid_child_atoms(sample_payload, min_binary_size=78):
                    if child.atom_type == "avcC" and len(child.payload) >= 7:
                        return child.payload
            offset += size
    return None


def _h264_sample_byte_ranges(
    track_atoms: tuple[QuickTimeAtomSpan, ...],
    mdat_ranges: tuple[QuickTimeMdatPayloadRange, ...],
    diagnostics: list[str],
) -> tuple[QuickTimeSampleByteRange, ...]:
    sample_sizes: tuple[int, ...] = ()
    chunk_offsets: tuple[int, ...] = ()
    sample_to_chunk: tuple[tuple[int, int, int], ...] = ()
    for atom in track_atoms:
        if atom.atom_type == "stsz":
            sample_sizes = _sample_sizes(atom.payload)
        elif atom.atom_type == "stz2":
            sample_sizes = _compact_sample_sizes(atom.payload)
        elif atom.atom_type == "stco":
            chunk_offsets = _chunk_offsets(atom.payload, field_size=4)
        elif atom.atom_type == "co64":
            chunk_offsets = _chunk_offsets(atom.payload, field_size=8)
        elif atom.atom_type == "stsc":
            sample_to_chunk = _sample_to_chunk_entries(atom.payload)
    if not sample_sizes or not chunk_offsets or not sample_to_chunk:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_sample_parse_blocked",
            (
                "deferred H264 sample parsing; ProcessSamples requires stco/co64, "
                "stsc and stsz/stz2 sample tables"
            ),
        )
        return ()
    ranges = _sample_byte_ranges(sample_sizes, chunk_offsets, sample_to_chunk)
    if len(ranges) != len(sample_sizes):
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_sample_parse_blocked",
            "deferred H264 sample parsing; sample start/size count mismatch",
        )
        return ()
    for sample_range in ranges:
        if not _sample_range_inside_mdat(sample_range, mdat_ranges):
            _append_quicktime_diagnostic(
                diagnostics,
                "quicktime_h264_sample_parse_blocked",
                (
                    f"deferred H264 sample {sample_range.sample_index}; byte range "
                    f"{sample_range.offset}:{sample_range.size} is outside finite top-level mdat"
                ),
            )
            return ()
    return ranges


def _h264_fragment_sample_byte_ranges(
    movie_fragments: tuple[QuickTimeAtomSpan, ...],
    state: QuickTimeReadState,
    diagnostics: list[str],
) -> tuple[QuickTimeSampleByteRange, ...]:
    ranges: list[QuickTimeSampleByteRange] = []
    h264_track_ids = set(state.h264_track_ids)
    for moof in movie_fragments:
        for traf in (child for child in moof.children if child.atom_type == "traf"):
            auxiliary_boxes = sorted(
                {child.atom_type for child in traf.children}
                & QUICKTIME_FRAGMENT_AUXILIARY_SAMPLE_BOXES
            )
            if auxiliary_boxes:
                _append_quicktime_diagnostic(
                    diagnostics,
                    "quicktime_h264_fragment_parse_blocked",
                    (
                        "deferred H264 fragment parsing; traf contains auxiliary/encrypted "
                        f"sample boxes {', '.join(auxiliary_boxes)}"
                    ),
                )
                continue
            tfhd = _track_fragment_header(traf, moof.offset, diagnostics)
            if tfhd is None:
                continue
            if h264_track_ids and tfhd.track_id not in h264_track_ids:
                continue
            traf_ranges = _track_fragment_run_ranges(
                traf,
                tfhd,
                moof.offset,
                first_sample_index=len(ranges) + 1,
                diagnostics=diagnostics,
            )
            ranges.extend(traf_ranges)
    if not ranges:
        return ()
    for sample_range in ranges:
        if not _sample_range_inside_mdat(sample_range, state.mdat_ranges):
            _append_quicktime_diagnostic(
                diagnostics,
                "quicktime_h264_fragment_parse_blocked",
                (
                    f"deferred H264 fragment sample {sample_range.sample_index}; byte range "
                    f"{sample_range.offset}:{sample_range.size} is outside finite top-level mdat"
                ),
            )
            return ()
    return tuple(ranges)


def _track_fragment_header(
    traf: QuickTimeAtomSpan,
    moof_offset: int,
    diagnostics: list[str],
) -> QuickTimeTrackFragmentHeader | None:
    tfhd = next((child for child in traf.children if child.atom_type == "tfhd"), None)
    if tfhd is None:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_fragment_parse_blocked",
            "deferred H264 fragment parsing; traf does not contain tfhd",
        )
        return None
    if len(tfhd.payload) < 8:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_fragment_parse_blocked",
            "deferred H264 fragment parsing; truncated tfhd payload",
        )
        return None
    flags = int.from_bytes(tfhd.payload[1:4], "big")
    cursor = 8
    track_id = int.from_bytes(tfhd.payload[4:8], "big")
    base_data_offset: int | None = None
    default_sample_size: int | None = None
    if flags & 0x000001:
        if cursor + 8 > len(tfhd.payload):
            return None
        base_data_offset = int.from_bytes(tfhd.payload[cursor : cursor + 8], "big")
        cursor += 8
    if flags & 0x000002:
        cursor += 4
    if flags & 0x000008:
        cursor += 4
    if flags & 0x000010:
        if cursor + 4 > len(tfhd.payload):
            return None
        default_sample_size = int.from_bytes(tfhd.payload[cursor : cursor + 4], "big")
        cursor += 4
    if flags & 0x000020:
        cursor += 4
    if cursor > len(tfhd.payload):
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_fragment_parse_blocked",
            "deferred H264 fragment parsing; truncated tfhd optional fields",
        )
        return None
    return QuickTimeTrackFragmentHeader(
        track_id=track_id,
        base_data_offset=base_data_offset,
        default_sample_size=default_sample_size,
        default_base_is_moof=bool(flags & 0x020000),
    )


def _track_fragment_run_ranges(
    traf: QuickTimeAtomSpan,
    tfhd: QuickTimeTrackFragmentHeader,
    moof_offset: int,
    *,
    first_sample_index: int,
    diagnostics: list[str],
) -> tuple[QuickTimeSampleByteRange, ...]:
    ranges: list[QuickTimeSampleByteRange] = []
    base_offset = tfhd.base_data_offset
    if base_offset is None and tfhd.default_base_is_moof:
        base_offset = moof_offset
    if base_offset is None:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_fragment_parse_blocked",
            (
                "deferred H264 fragment parsing; tfhd lacks base-data-offset and "
                "default-base-is-moof"
            ),
        )
        return ()
    run_data_start = base_offset
    for trun in (child for child in traf.children if child.atom_type == "trun"):
        parsed = _track_run_sample_sizes(trun.payload, tfhd.default_sample_size, diagnostics)
        if parsed is None:
            return ()
        data_offset, sample_sizes = parsed
        sample_start = run_data_start + data_offset
        for sample_size in sample_sizes:
            ranges.append(
                QuickTimeSampleByteRange(
                    sample_index=first_sample_index + len(ranges),
                    chunk_index=1,
                    offset=sample_start,
                    size=sample_size,
                    track_id=tfhd.track_id,
                )
            )
            sample_start += sample_size
        run_data_start = sample_start
    if not ranges:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_fragment_parse_blocked",
            "deferred H264 fragment parsing; traf does not contain trun sample sizes",
        )
    return tuple(ranges)


def _track_run_sample_sizes(
    payload: bytes,
    default_sample_size: int | None,
    diagnostics: list[str],
) -> tuple[int, tuple[int, ...]] | None:
    if len(payload) < 8:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_fragment_parse_blocked",
            "deferred H264 fragment parsing; truncated trun payload",
        )
        return None
    flags = int.from_bytes(payload[1:4], "big")
    sample_count = int.from_bytes(payload[4:8], "big")
    cursor = 8
    data_offset = 0
    if flags & 0x000001:
        if cursor + 4 > len(payload):
            return None
        data_offset = int.from_bytes(payload[cursor : cursor + 4], "big", signed=True)
        cursor += 4
    if flags & 0x000004:
        cursor += 4
    sample_sizes: list[int] = []
    for _ in range(sample_count):
        if flags & 0x000100:
            cursor += 4
        if flags & 0x000200:
            if cursor + 4 > len(payload):
                return None
            sample_sizes.append(int.from_bytes(payload[cursor : cursor + 4], "big"))
            cursor += 4
        elif default_sample_size is not None:
            sample_sizes.append(default_sample_size)
        else:
            _append_quicktime_diagnostic(
                diagnostics,
                "quicktime_h264_fragment_parse_blocked",
                (
                    "deferred H264 fragment parsing; trun omits sample-size entries "
                    "and tfhd has no default sample size"
                ),
            )
            return None
        if flags & 0x000400:
            cursor += 4
        if flags & 0x000800:
            cursor += 4
        if cursor > len(payload):
            return None
    return data_offset, tuple(sample_sizes)


def _h264_sample_range_tags(ranges: tuple[QuickTimeSampleByteRange, ...]) -> tuple[ReadTag, ...]:
    return (
        _quicktime_table_tag(
            "H264SampleByteRanges",
            [f"{sample_range.offset}:{sample_range.size}" for sample_range in ranges],
            "ProcessSamples",
            QUICKTIME_STREAM_TABLE,
        ),
    )


def _read_exact_sample(
    path: Path,
    sample_range: QuickTimeSampleByteRange,
    diagnostics: list[str],
) -> bytes | None:
    try:
        with path.open("rb") as file:
            file.seek(sample_range.offset)
            sample = file.read(sample_range.size)
    except OSError as exc:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_sample_parse_blocked",
            f"deferred H264 sample {sample_range.sample_index}; seek/read failed: {exc}",
        )
        return None
    if len(sample) != sample_range.size:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_h264_sample_parse_blocked",
            f"deferred H264 sample {sample_range.sample_index}; truncated sample data",
        )
        return None
    return sample


def _quicktime_h264_sample_to_annex_b(
    sample: bytes,
    hdr_len: int,
    sample_range: QuickTimeSampleByteRange,
    diagnostics: list[str],
) -> bytes:
    annex_b = bytearray()
    pos = 0
    while pos + hdr_len <= len(sample):
        nal_len = int.from_bytes(sample[pos : pos + hdr_len], "big")
        nal_start = pos + hdr_len
        nal_end = nal_start + nal_len
        if nal_end > len(sample):
            _append_quicktime_diagnostic(
                diagnostics,
                "quicktime_h264_sample_parse_blocked",
                (
                    f"stopped H264 sample {sample_range.sample_index} NAL scan at byte {pos}; "
                    "length-prefixed NAL runs past declared sample size"
                ),
            )
            break
        annex_b.extend(b"\0\0\0\x01")
        annex_b.extend(sample[nal_start:nal_end])
        pos = nal_end
    return bytes(annex_b)


def _sample_byte_ranges(
    sample_sizes: tuple[int, ...],
    chunk_offsets: tuple[int, ...],
    sample_to_chunk: tuple[tuple[int, int, int], ...],
) -> tuple[QuickTimeSampleByteRange, ...]:
    ranges: list[QuickTimeSampleByteRange] = []
    stsc_index = 0
    next_chunk = sample_to_chunk[1][0] if len(sample_to_chunk) > 1 else len(chunk_offsets) + 1
    samples_per_chunk = sample_to_chunk[0][1]
    for chunk_index, chunk_start in enumerate(chunk_offsets, start=1):
        if chunk_index >= next_chunk and stsc_index + 1 < len(sample_to_chunk):
            stsc_index += 1
            samples_per_chunk = sample_to_chunk[stsc_index][1]
            next_chunk = (
                sample_to_chunk[stsc_index + 1][0]
                if stsc_index + 1 < len(sample_to_chunk)
                else len(chunk_offsets) + 1
            )
        sample_start = chunk_start
        for _ in range(samples_per_chunk):
            if len(ranges) >= len(sample_sizes):
                return tuple(ranges)
            sample_index = len(ranges)
            sample_size = sample_sizes[sample_index]
            ranges.append(
                QuickTimeSampleByteRange(
                    sample_index=sample_index + 1,
                    chunk_index=chunk_index,
                    offset=sample_start,
                    size=sample_size,
                )
            )
            sample_start += sample_size
    return tuple(ranges)


def _sample_range_inside_mdat(
    sample_range: QuickTimeSampleByteRange,
    mdat_ranges: tuple[QuickTimeMdatPayloadRange, ...],
) -> bool:
    return any(
        sample_range.offset >= mdat.offset and sample_range.end_offset <= mdat.end_offset
        for mdat in mdat_ranges
    )


def _sample_sizes(payload: bytes) -> tuple[int, ...]:
    if len(payload) < 12:
        return ()
    sample_size = int.from_bytes(payload[4:8], "big")
    sample_count = int.from_bytes(payload[8:12], "big")
    if sample_size:
        return (sample_size,) * sample_count
    if len(payload) < 12 + sample_count * 4:
        return ()
    return tuple(
        int.from_bytes(payload[offset : offset + 4], "big")
        for offset in range(12, 12 + sample_count * 4, 4)
    )


def _compact_sample_sizes(payload: bytes) -> tuple[int, ...]:
    if len(payload) < 12:
        return ()
    field_size = payload[7]
    sample_count = int.from_bytes(payload[8:12], "big")
    if field_size == 4:
        byte_count = (sample_count + 1) // 2
        if len(payload) < 12 + byte_count:
            return ()
        sizes: list[int] = []
        for value in payload[12 : 12 + byte_count]:
            sizes.append(value >> 4)
            if len(sizes) < sample_count:
                sizes.append(value & 0x0F)
        return tuple(sizes)
    if field_size == 8:
        if len(payload) < 12 + sample_count:
            return ()
        return tuple(payload[12 : 12 + sample_count])
    if field_size == 16:
        if len(payload) < 12 + sample_count * 2:
            return ()
        return tuple(
            int.from_bytes(payload[offset : offset + 2], "big")
            for offset in range(12, 12 + sample_count * 2, 2)
        )
    return ()


def _chunk_offsets(payload: bytes, *, field_size: int) -> tuple[int, ...]:
    if len(payload) < 8:
        return ()
    count = int.from_bytes(payload[4:8], "big")
    if len(payload) < 8 + count * field_size:
        return ()
    return tuple(
        int.from_bytes(payload[offset : offset + field_size], "big")
        for offset in range(8, 8 + count * field_size, field_size)
    )


def _sample_to_chunk_entries(payload: bytes) -> tuple[tuple[int, int, int], ...]:
    if len(payload) < 8:
        return ()
    count = int.from_bytes(payload[4:8], "big")
    if len(payload) < 8 + count * 12:
        return ()
    entries: list[tuple[int, int, int]] = []
    for offset in range(8, 8 + count * 12, 12):
        entries.append(
            (
                int.from_bytes(payload[offset : offset + 4], "big"),
                int.from_bytes(payload[offset + 4 : offset + 8], "big"),
                int.from_bytes(payload[offset + 8 : offset + 12], "big"),
            )
        )
    return tuple(entries)


def _sample_start_offsets(
    sample_sizes: tuple[int, ...],
    chunk_offsets: tuple[int, ...],
    sample_to_chunk: tuple[tuple[int, int, int], ...],
) -> tuple[int, ...]:
    starts: list[int] = []
    stsc_index = 0
    next_chunk = sample_to_chunk[1][0] if len(sample_to_chunk) > 1 else len(chunk_offsets) + 1
    samples_per_chunk = sample_to_chunk[0][1]
    for chunk_index, chunk_start in enumerate(chunk_offsets, start=1):
        if chunk_index >= next_chunk and stsc_index + 1 < len(sample_to_chunk):
            stsc_index += 1
            samples_per_chunk = sample_to_chunk[stsc_index][1]
            next_chunk = (
                sample_to_chunk[stsc_index + 1][0]
                if stsc_index + 1 < len(sample_to_chunk)
                else len(chunk_offsets) + 1
            )
        sample_start = chunk_start
        for _ in range(samples_per_chunk):
            if len(starts) >= len(sample_sizes):
                return tuple(starts)
            starts.append(sample_start)
            sample_start += sample_sizes[len(starts) - 1]
    return tuple(starts)


def _sample_timings(
    sample_count: int,
    time_entries: tuple[tuple[int, int], ...],
    media_time_scale: int | None,
) -> tuple[QuickTimeSampleTiming, ...]:
    if not time_entries or not media_time_scale:
        return tuple(QuickTimeSampleTiming(None, None) for _ in range(sample_count))
    timings: list[QuickTimeSampleTiming] = []
    sample_time = 0
    for entry_count, duration in time_entries:
        for _ in range(entry_count):
            if len(timings) >= sample_count:
                return tuple(timings)
            timings.append(
                QuickTimeSampleTiming(sample_time / media_time_scale, duration / media_time_scale)
            )
            sample_time += duration
    while len(timings) < sample_count:
        timings.append(QuickTimeSampleTiming(None, None))
    return tuple(timings)


def _append_mebx_sample_tags(
    tags: list[ReadTag],
    sample: bytes,
    keys: dict[str, QuickTimeTimedMetadataKey],
    diagnostics: list[str],
) -> bool:
    emitted = False
    offset = 0
    while offset + QT_ATOM_HEADER_SIZE <= len(sample):
        size = int.from_bytes(sample[offset : offset + 4], "big")
        if size < QT_ATOM_HEADER_SIZE or offset + size > len(sample):
            break
        local_id = sample[offset + 4 : offset + 8].decode("latin-1", errors="replace")
        key = keys.get(local_id)
        if key is None:
            _append_quicktime_diagnostic(
                diagnostics,
                "unsupported_meta_sample_child",
                f"no key information for mebx ID {_printable_atom_id(local_id)!r}",
            )
            offset += size
            continue
        raw_value = sample[offset + 8 : offset + size]
        value = _decode_timed_metadata_value(raw_value, key.value_format)
        if value is not None:
            tags.append(_timed_metadata_tag(key, value))
            emitted = True
        offset += size
    return emitted


def _decode_timed_metadata_value(value: bytes, value_format: str) -> TagValue | None:
    if value_format == "string":
        return value.rstrip(b"\0").decode("utf-8", errors="replace")
    if value_format == "int8s" and len(value) >= 1:
        return int.from_bytes(value[:1], "big", signed=True)
    if value_format == "int16s" and len(value) >= 2:
        return int.from_bytes(value[:2], "big", signed=True)
    if value_format == "int32s" and len(value) >= 4:
        return int.from_bytes(value[:4], "big", signed=True)
    if value_format == "int64s" and len(value) >= 8:
        return int.from_bytes(value[:8], "big", signed=True)
    if value_format == "int8u" and len(value) >= 1:
        return int.from_bytes(value[:1], "big")
    if value_format == "int16u" and len(value) >= 2:
        return int.from_bytes(value[:2], "big")
    if value_format == "int32u" and len(value) >= 4:
        return int.from_bytes(value[:4], "big")
    if value_format == "int64u" and len(value) >= 8:
        return int.from_bytes(value[:8], "big")
    if value_format == "float" and len(value) >= 4:
        values = tuple(
            _compact_number(struct.unpack(">f", value[offset : offset + 4])[0])
            for offset in range(0, len(value) - len(value) % 4, 4)
        )
        return values[0] if len(values) == 1 else " ".join(values)
    if value_format == "double" and len(value) >= 8:
        values = tuple(
            _compact_number(struct.unpack(">d", value[offset : offset + 8])[0])
            for offset in range(0, len(value) - len(value) % 8, 8)
        )
        return values[0] if len(values) == 1 else " ".join(values)
    return None


def _timed_metadata_tag(key: QuickTimeTimedMetadataKey, value: TagValue) -> ReadTag:
    metadata_tag = QUICKTIME_KEYS_TAGS.get(key.tag_id)
    tag_name = (
        metadata_tag.name if metadata_tag is not None else _dynamic_timed_metadata_name(key.tag_id)
    )
    rendered = value
    if (
        metadata_tag is not None
        and metadata_tag.item_list_format == "gps_iso6709"
        and isinstance(value, str)
    ):
        rendered = _gps_coordinates_from_iso6709(value) or value
    return _read_tag(
        tag_name,
        rendered,
        "Keys",
        QUICKTIME_KEYS_TABLE,
        key.tag_id,
        "quicktime-timed-metadata-sample",
        family_0_group="QuickTime",
        family_1_group="Keys",
        family_2_group=_quicktime_metadata_family_2(tag_name),
    )


def _dynamic_timed_metadata_name(tag_id: str) -> str:
    name = ""
    capitalize_next = True
    for char in tag_id:
        if char in {"-", "."}:
            capitalize_next = True
            continue
        name += char.upper() if capitalize_next else char
        capitalize_next = False
    return name or "Tag"


def _duration_from_seconds(seconds: float) -> str:
    return _duration(int(seconds * 1_000_000), 1_000_000)


def _append_other_sample_tags(
    tags: list[ReadTag],
    other_format: str,
    payload: bytes,
    diagnostics: list[str],
) -> None:
    tags.append(_quicktime_tag("OtherFormat", other_format, "stsd", family_2_group="Video"))
    if other_format == "tmcd" and len(payload) >= 24:
        tags.append(
            _quicktime_tag(
                "PlaybackFrameRate",
                _rational64_unsigned(payload[16:24]),
                "stsd",
                family_2_group="Video",
            )
        )
    min_binary_size = _other_sample_binary_size(other_format)
    for child in _hybrid_child_atoms(payload, min_binary_size=min_binary_size):
        if child.atom_type == "name":
            if len(child.payload) >= 4:
                tags.append(
                    _quicktime_tag(
                        "OtherName",
                        child.payload[4:].rstrip(b"\0").decode("utf-8", errors="replace"),
                        "name",
                        family_2_group="Video",
                    )
                )
            else:
                _append_quicktime_diagnostic(
                    diagnostics,
                    "truncated_other_sample_child",
                    "truncated OtherSampleDesc name payload",
                )
        elif child.atom_type == "ftab":
            if len(child.payload) >= 5:
                tags.append(
                    _quicktime_tag(
                        "FontTable",
                        BinaryTagValue(child.payload[5:]),
                        "ftab",
                        family_2_group="Video",
                    )
                )
            else:
                _append_quicktime_diagnostic(
                    diagnostics,
                    "truncated_other_sample_child",
                    "truncated OtherSampleDesc ftab payload",
                )
        elif child.atom_type in {"avcC", "esds", "mrlh", "mrlv", "mrld"}:
            _append_quicktime_diagnostic(
                diagnostics,
                "deferred_other_sample_child",
                (
                    f"deferred OtherSampleDesc child atom "
                    f"{_printable_atom_id(child.atom_type)!r} subdirectory adapter"
                ),
            )
        elif child.atom_type not in QUICKTIME_SUPPORTED_OTHER_SAMPLE_CHILDREN:
            _append_quicktime_diagnostic(
                diagnostics,
                "unsupported_other_sample_child",
                f"unsupported OtherSampleDesc child atom {_printable_atom_id(child.atom_type)!r}",
            )


def _append_int32_child_tag(
    tags: list[ReadTag],
    payload: bytes,
    name: str,
    tag_id: str,
    diagnostics: list[str],
    *,
    diagnostic_label: str,
) -> None:
    if len(payload) < 4:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_hint_sample_child",
            f"truncated {diagnostic_label} {tag_id} payload",
        )
        return
    tags.append(
        _quicktime_tag(
            name,
            int.from_bytes(payload[:4], "big"),
            tag_id,
            family_2_group="Video",
        )
    )


def _metadata_sample_type(payload: bytes) -> str | None:
    marker = b"application"
    start = payload.find(marker)
    if start < 0:
        return None
    return payload[start:].split(b"\0", 1)[0].decode("latin-1", errors="replace")


def _other_sample_binary_size(other_format: str) -> int:
    return {
        "avc1": 78,
        "mp4a": 28,
        "mp4s": 8,
        "tmcd": 26,
    }.get(other_format, 8)


def _hybrid_child_atoms(payload: bytes, *, min_binary_size: int) -> tuple[QuickTimeAtomSpan, ...]:
    """Mirror QuickTime.pm ProcessHybrid's bounded child-atom discovery."""
    end = len(payload)
    pos = max(0, min_binary_size)
    while pos <= end - QT_ATOM_HEADER_SIZE:
        try_offset = pos
        while try_offset <= end - QT_ATOM_HEADER_SIZE:
            atom_type = payload[try_offset + 4 : try_offset + 8].decode("latin-1", errors="replace")
            if not _is_well_behaved_atom_id(atom_type):
                break
            atom_size = int.from_bytes(payload[try_offset : try_offset + 4], "big")
            if atom_size + try_offset == end:
                return _parse_child_atoms(payload[pos:], 0)
            if (
                atom_size < QT_ATOM_HEADER_SIZE
                or atom_size + try_offset > end - QT_ATOM_HEADER_SIZE
            ):
                break
            try_offset += atom_size
        pos += 1
    return ()


def _is_well_behaved_atom_id(atom_type: str) -> bool:
    return all(char == " " or char == "_" or char.isalnum() for char in atom_type)


def _append_child_bitrate_tags(
    tags: list[ReadTag],
    payload: bytes,
    *,
    family_2_group: str,
) -> None:
    if len(payload) < 12:
        return
    tags.append(
        _quicktime_tag(
            "BufferSize",
            int.from_bytes(payload[:4], "big"),
            "btrt",
            table_name="Image::ExifTool::QuickTime::Bitrate",
            family_2_group=family_2_group,
        )
    )
    tags.append(
        _quicktime_tag(
            "MaxBitrate",
            int.from_bytes(payload[4:8], "big"),
            "btrt",
            table_name="Image::ExifTool::QuickTime::Bitrate",
            family_2_group=family_2_group,
        )
    )
    tags.append(
        _quicktime_tag(
            "AverageBitrate",
            int.from_bytes(payload[8:12], "big"),
            "btrt",
            table_name="Image::ExifTool::QuickTime::Bitrate",
            family_2_group=family_2_group,
        )
    )


def _append_unknown_child_binary_tag(
    tags: list[ReadTag],
    child: QuickTimeAtomSpan,
    *,
    table_name: str,
    family_2_group: str,
) -> None:
    if not _quicktime_should_emit_unknown_tags():
        return
    tags.append(
        _quicktime_tag(
            f"Unknown {child.atom_type}",
            BinaryTagValue(child.payload),
            child.atom_type,
            table_name=table_name,
            family_2_group=family_2_group,
        )
    )


def _append_avc_configuration_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
) -> None:
    if not _quicktime_should_emit_configuration_tags():
        return
    if len(payload) < 7:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_video_sample_child",
            "truncated AVCConfiguration payload",
        )
        return
    tags.append(
        _quicktime_tag(
            "AVCConfiguration",
            BinaryTagValue(payload),
            "avcC",
            family_2_group="Video",
        )
    )
    tags.append(
        _quicktime_tag(
            "AVCNALUnitLengthSize",
            (payload[4] & 0x03) + 1,
            "avcC",
            family_2_group="Video",
        )
    )


def _append_hevc_configuration_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
) -> None:
    if not _quicktime_should_emit_configuration_tags():
        return
    if len(payload) < 22:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_video_sample_child",
            "truncated HEVCConfiguration payload",
        )
        return
    general_profile_space = payload[1] & 0xC0
    general_tier_flag = (payload[1] & 0x20) >> 5
    general_profile_idc = payload[1] & 0x1F
    average_frame_rate = int.from_bytes(payload[19:21], "big") / 256
    tags.extend(
        (
            _quicktime_tag("HEVCConfigurationVersion", payload[0], "hvcC", family_2_group="Video"),
            _quicktime_tag(
                "GeneralProfileSpace",
                "Conforming" if general_profile_space == 0 else general_profile_space,
                "hvcC",
                family_2_group="Video",
            ),
            _quicktime_tag(
                "GeneralTierFlag",
                "High Tier" if general_tier_flag else "Main Tier",
                "hvcC",
                family_2_group="Video",
            ),
            _quicktime_tag(
                "GeneralProfileIDC",
                QUICKTIME_HEVC_PROFILE_IDC.get(general_profile_idc, general_profile_idc),
                "hvcC",
                family_2_group="Video",
            ),
            _quicktime_tag(
                "GenProfileCompatibilityFlags",
                int.from_bytes(payload[2:6], "big"),
                "hvcC",
                family_2_group="Video",
            ),
            _quicktime_tag(
                "ConstraintIndicatorFlags",
                " ".join(str(value) for value in payload[6:12]),
                "hvcC",
                family_2_group="Video",
            ),
            _quicktime_tag(
                "GeneralLevelIDC",
                f"{payload[12]} (level {_compact_number(payload[12] / 30)})",
                "hvcC",
                family_2_group="Video",
            ),
            _quicktime_tag(
                "MinSpatialSegmentationIDC",
                int.from_bytes(payload[13:15], "big") & 0x0FFF,
                "hvcC",
                family_2_group="Video",
            ),
            _quicktime_tag(
                "ParallelismType",
                payload[15] & 0x03,
                "hvcC",
                family_2_group="Video",
            ),
            _quicktime_tag(
                "ChromaFormat",
                QUICKTIME_HEVC_CHROMA_FORMAT.get(payload[16] & 0x03, payload[16] & 0x03),
                "hvcC",
                family_2_group="Video",
            ),
            _quicktime_tag("BitDepthLuma", (payload[17] & 0x07) + 8, "hvcC"),
            _quicktime_tag("BitDepthChroma", (payload[18] & 0x07) + 8, "hvcC"),
            _quicktime_tag(
                "AverageFrameRate",
                _compact_number(average_frame_rate),
                "hvcC",
                family_2_group="Video",
            ),
            _quicktime_tag(
                "ConstantFrameRate",
                QUICKTIME_HEVC_CONSTANT_FRAME_RATE.get((payload[21] & 0xC0) >> 6, 0),
                "hvcC",
                family_2_group="Video",
            ),
            _quicktime_tag(
                "NumTemporalLayers",
                (payload[21] & 0x38) >> 3,
                "hvcC",
                family_2_group="Video",
            ),
            _quicktime_tag(
                "TemporalIDNested",
                "Yes" if payload[21] & 0x04 else "No",
                "hvcC",
                family_2_group="Video",
            ),
        )
    )


def _append_clean_aperture_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
) -> None:
    if len(payload) < 32:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_video_sample_child",
            "truncated CleanAperture payload",
        )
        return
    for index, name in enumerate(
        (
            "CleanApertureWidth",
            "CleanApertureHeight",
            "CleanApertureOffsetX",
            "CleanApertureOffsetY",
        )
    ):
        start = index * 8
        tags.append(
            _quicktime_tag(
                name,
                _rational64_signed(payload[start : start + 8]),
                "clap",
                family_2_group="Video",
            )
        )


def _append_wave_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
) -> None:
    for child in _parse_child_atoms(payload, 0):
        if child.atom_type == "frma":
            if len(child.payload) < 4:
                _append_quicktime_diagnostic(
                    diagnostics,
                    "truncated_audio_sample_child",
                    "truncated Wave frma payload",
                )
                continue
            tags.append(
                _quicktime_tag(
                    "PurchaseFileFormat",
                    child.payload[:4].decode("latin-1", errors="replace"),
                    "frma",
                    family_2_group="Audio",
                )
            )
        elif child.atom_type == "enda":
            if len(child.payload) < 2:
                _append_quicktime_diagnostic(
                    diagnostics,
                    "truncated_audio_sample_child",
                    "truncated Wave enda payload",
                )
                continue
            value = int.from_bytes(child.payload[:2], "big")
            tags.append(
                _quicktime_tag(
                    "Endianness",
                    "Little-endian (Intel, II)" if value == 1 else "Big-endian (Motorola, MM)",
                    "enda",
                    family_2_group="Audio",
                )
            )
        else:
            _append_quicktime_diagnostic(
                diagnostics,
                "unsupported_audio_sample_child",
                f"unsupported Wave child atom {_printable_atom_id(child.atom_type)!r}",
            )


def _append_decode_config_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
) -> None:
    if len(payload) < 5:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_audio_sample_child",
            "truncated AMR DecodeConfig payload",
        )
        return
    tags.append(
        _quicktime_tag(
            "EncoderVendor",
            payload[:4].decode("latin-1", errors="replace"),
            "damr",
            family_2_group="Audio",
        )
    )
    tags.append(_quicktime_tag("EncoderVersion", payload[4], "damr", family_2_group="Audio"))


def _append_protection_info_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
    *,
    parent_atom: str,
) -> None:
    for child in _parse_child_atoms(payload, 0):
        if child.atom_type == "frma":
            if len(child.payload) < 4:
                _append_quicktime_diagnostic(
                    diagnostics,
                    "truncated_audio_sample_child",
                    f"truncated ProtectionInfo {parent_atom} frma payload",
                )
                continue
            tags.append(
                _quicktime_table_tag(
                    "OriginalFormat",
                    child.payload[:4].decode("latin-1", errors="replace"),
                    "frma",
                    "Image::ExifTool::QuickTime::ProtectionInfo",
                    family_2_group="Audio",
                )
            )
        elif child.atom_type == "enda":
            if len(child.payload) < 2:
                _append_quicktime_diagnostic(
                    diagnostics,
                    "truncated_audio_sample_child",
                    f"truncated ProtectionInfo {parent_atom} enda payload",
                )
                continue
            value = int.from_bytes(child.payload[:2], "big")
            tags.append(
                _quicktime_table_tag(
                    "Endianness",
                    "Little-endian (Intel, II)" if value == 1 else "Big-endian (Motorola, MM)",
                    "enda",
                    "Image::ExifTool::QuickTime::ProtectionInfo",
                    family_2_group="Audio",
                )
            )
        elif child.atom_type == "schm":
            _append_scheme_type_tags(tags, child.payload, diagnostics)
        elif child.atom_type == "schi":
            _append_scheme_info_tags(tags, child.payload, diagnostics, parent_atom=parent_atom)
        else:
            _append_quicktime_diagnostic(
                diagnostics,
                "unsupported_audio_sample_child",
                (
                    f"unsupported ProtectionInfo {parent_atom} child atom "
                    f"{_printable_atom_id(child.atom_type)!r}"
                ),
            )


def _append_scheme_type_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
) -> None:
    if len(payload) < 10:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_audio_sample_child",
            "truncated ProtectionInfo schm SchemeType payload",
        )
        return
    scheme_type = payload[4:8].decode("latin-1", errors="replace")
    tags.append(
        _quicktime_table_tag(
            "SchemeType",
            scheme_type,
            "schm",
            "Image::ExifTool::QuickTime::SchemeType",
            family_2_group="Audio",
        )
    )
    tags.append(
        _quicktime_table_tag(
            "SchemeVersion",
            int.from_bytes(payload[8:10], "big"),
            "schm",
            "Image::ExifTool::QuickTime::SchemeType",
            family_2_group="Audio",
        )
    )
    if len(payload) > 10:
        tags.append(
            _quicktime_table_tag(
                "SchemeURL",
                payload[10:].rstrip(b"\0").decode("latin-1", errors="replace"),
                "schm",
                "Image::ExifTool::QuickTime::SchemeType",
                family_2_group="Audio",
            )
        )


def _append_scheme_info_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
    *,
    parent_atom: str,
) -> None:
    for child in _parse_child_atoms(payload, 0):
        if child.atom_type == "user":
            tags.append(
                _quicktime_table_tag(
                    "UserID",
                    f"0x{child.payload.hex()}",
                    "user",
                    "Image::ExifTool::QuickTime::SchemeInfo",
                    family_2_group="Author",
                )
            )
        elif child.atom_type == "cert":
            tags.append(
                _quicktime_table_tag(
                    "Certificate",
                    f"0x{child.payload.hex()}",
                    "cert",
                    "Image::ExifTool::QuickTime::SchemeInfo",
                    family_2_group="Audio",
                )
            )
        elif child.atom_type == "key ":
            tags.append(
                _quicktime_table_tag(
                    "KeyID",
                    f"0x{child.payload.hex()}",
                    "key ",
                    "Image::ExifTool::QuickTime::SchemeInfo",
                    family_2_group="Audio",
                )
            )
        elif child.atom_type == "iviv":
            tags.append(
                _quicktime_table_tag(
                    "InitializationVector",
                    child.payload.hex(),
                    "iviv",
                    "Image::ExifTool::QuickTime::SchemeInfo",
                    family_2_group="Audio",
                )
            )
        elif child.atom_type == "name":
            tags.append(
                _quicktime_table_tag(
                    "UserName",
                    child.payload.rstrip(b"\0").decode("latin-1", errors="replace"),
                    "name",
                    "Image::ExifTool::QuickTime::SchemeInfo",
                    family_2_group="Author",
                )
            )
        elif child.atom_type == "righ":
            _append_rights_tags(tags, child.payload)
        else:
            _append_quicktime_diagnostic(
                diagnostics,
                "unsupported_audio_sample_child",
                (
                    f"unsupported ProtectionInfo {parent_atom} schi SchemeInfo child atom "
                    f"{_printable_atom_id(child.atom_type)!r}"
                ),
            )


def _append_rights_tags(tags: list[ReadTag], payload: bytes) -> None:
    for offset in range(0, len(payload) - 7, 8):
        tag_id = payload[offset : offset + 4].decode("latin-1", errors="replace")
        if tag_id == "\0\0\0\0":
            break
        tag_info = QUICKTIME_RIGHTS_TAGS.get(tag_id)
        if tag_info is None:
            continue
        name, is_string = tag_info
        raw_value = payload[offset + 4 : offset + 8]
        value: TagValue
        if is_string:
            value = raw_value.rstrip(b"\0").decode("latin-1", errors="replace")
        else:
            value = f"0x{raw_value.hex()}"
        tags.append(
            _quicktime_table_tag(
                name,
                value,
                tag_id,
                QUICKTIME_RIGHTS_TABLE,
                family_2_group="Audio",
            )
        )


def _append_spatial_audio_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
) -> None:
    if len(payload) < 12:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_audio_sample_child",
            "truncated SpatialAudio payload",
        )
        return
    ambisonic_channels = int.from_bytes(payload[8:12], "big")
    expected_size = 12 + ambisonic_channels * 4
    if len(payload) < expected_size:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_audio_sample_child",
            "truncated SpatialAudio channel map payload",
        )
        return
    tags.extend(
        (
            _quicktime_table_tag(
                "SpatialAudioVersion",
                payload[0],
                "SA3D",
                "Image::ExifTool::QuickTime::SpatialAudio",
                family_2_group="Audio",
            ),
            _quicktime_table_tag(
                "AmbisonicType",
                "Periphonic" if payload[1] == 0 else payload[1],
                "SA3D",
                "Image::ExifTool::QuickTime::SpatialAudio",
                family_2_group="Audio",
            ),
            _quicktime_table_tag(
                "AmbisonicOrder",
                int.from_bytes(payload[2:6], "big"),
                "SA3D",
                "Image::ExifTool::QuickTime::SpatialAudio",
                family_2_group="Audio",
            ),
            _quicktime_table_tag(
                "AmbisonicChannelOrdering",
                "ACN" if payload[6] == 0 else payload[6],
                "SA3D",
                "Image::ExifTool::QuickTime::SpatialAudio",
                family_2_group="Audio",
            ),
            _quicktime_table_tag(
                "AmbisonicNormalization",
                "SN3D" if payload[7] == 0 else payload[7],
                "SA3D",
                "Image::ExifTool::QuickTime::SpatialAudio",
                family_2_group="Audio",
            ),
            _quicktime_table_tag(
                "AmbisonicChannels",
                ambisonic_channels,
                "SA3D",
                "Image::ExifTool::QuickTime::SpatialAudio",
                family_2_group="Audio",
            ),
        )
    )
    channel_map = [
        int.from_bytes(payload[offset : offset + 4], "big")
        for offset in range(12, expected_size, 4)
    ]
    tags.append(
        _quicktime_table_tag(
            "AmbisonicChannelMap",
            " ".join(str(value) for value in channel_map),
            "SA3D",
            "Image::ExifTool::QuickTime::SpatialAudio",
            family_2_group="Audio",
        )
    )


def _append_channel_layout_tags(
    tags: list[ReadTag],
    payload: bytes,
    diagnostics: list[str],
) -> None:
    if len(payload) < 8:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_audio_sample_child",
            "truncated AudioChannelLayout payload",
        )
        return
    layout_flags = int.from_bytes(payload[4:6], "big")
    audio_channels = int.from_bytes(payload[6:8], "big")
    tags.append(
        _quicktime_tag(
            "LayoutFlags",
            QUICKTIME_CHANNEL_LAYOUT_FLAGS.get(layout_flags, layout_flags),
            "chan",
            family_2_group="Audio",
        )
    )
    if layout_flags not in {0, 1}:
        tags.append(_quicktime_tag("AudioChannels", audio_channels, "chan", family_2_group="Audio"))
        return
    if layout_flags != 1:
        return
    if len(payload) < 16:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_audio_sample_child",
            "truncated AudioChannelLayout bitmap payload",
        )
        return
    channel_types = int.from_bytes(payload[8:12], "big")
    tags.append(
        _quicktime_tag(
            "AudioChannelTypes",
            _channel_type_bitmask(channel_types),
            "chan",
            family_2_group="Audio",
        )
    )
    description_count = int.from_bytes(payload[12:16], "big")
    tags.append(
        _quicktime_tag(
            "NumChannelDescriptions",
            description_count,
            "chan",
            family_2_group="Audio",
        )
    )
    max_descriptions = min(description_count, 8)
    if len(payload) < 16 + max_descriptions * 20:
        _append_quicktime_diagnostic(
            diagnostics,
            "truncated_audio_sample_child",
            "truncated AudioChannelLayout channel description payload",
        )
        return
    for index in range(max_descriptions):
        start = 16 + index * 20
        channel_number = index + 1
        label = int.from_bytes(payload[start : start + 4], "big")
        flags = int.from_bytes(payload[start + 4 : start + 8], "big")
        coordinates = struct.unpack(">fff", payload[start + 8 : start + 20])
        tags.append(
            _quicktime_tag(
                f"Channel{channel_number}Label",
                QUICKTIME_CHANNEL_LABELS.get(label, label),
                "chan",
                family_2_group="Audio",
            )
        )
        tags.append(
            _quicktime_tag(
                f"Channel{channel_number}Flags",
                _channel_description_flags(flags),
                "chan",
                family_2_group="Audio",
            )
        )
        tags.append(
            _quicktime_tag(
                f"Channel{channel_number}Coordinates",
                " ".join(_compact_number(value) for value in coordinates),
                "chan",
                family_2_group="Audio",
            )
        )


def _append_color_tags(tags: list[ReadTag], payload: bytes, diagnostics: list[str]) -> None:
    if len(payload) < 4:
        return
    color_profile = payload[:4].decode("latin-1", errors="replace")
    if payload[:4] in {b"prof", b"rICC"}:
        _append_embedded_icc_profile_tags(tags, payload[4:], diagnostics)
        return
    if len(payload) < 10 or payload[:4] not in {b"nclc", b"nclx"}:
        return
    primaries = int.from_bytes(payload[4:6], "big")
    transfer = int.from_bytes(payload[6:8], "big")
    matrix = int.from_bytes(payload[8:10], "big")
    color_table = "Image::ExifTool::QuickTime::ColorRep"
    tags.append(
        _quicktime_tag(
            "ColorProfiles",
            color_profile,
            "colr",
            table_name=color_table,
            family_2_group="Video",
        )
    )
    tags.append(
        _quicktime_tag(
            "ColorPrimaries",
            QUICKTIME_COLOR_PRIMARIES.get(primaries, primaries),
            "colr",
            table_name=color_table,
            family_2_group="Video",
        )
    )
    tags.append(
        _quicktime_tag(
            "TransferCharacteristics",
            QUICKTIME_TRANSFER_CHARACTERISTICS.get(transfer, transfer),
            "colr",
            table_name=color_table,
            family_2_group="Video",
        )
    )
    tags.append(
        _quicktime_tag(
            "MatrixCoefficients",
            QUICKTIME_MATRIX_COEFFICIENTS.get(matrix, matrix),
            "colr",
            table_name=color_table,
            family_2_group="Video",
        )
    )
    if color_profile == "nclx" and len(payload) >= 11:
        tags.append(
            _quicktime_tag(
                "VideoFullRangeFlag",
                "Full" if payload[10] & 0x80 else "Limited",
                "colr",
                table_name=color_table,
                family_2_group="Video",
            )
        )


def _append_embedded_icc_profile_tags(
    tags: list[ReadTag],
    profile: bytes,
    diagnostics: list[str],
) -> None:
    from exifmodern.formats.icc import parse_icc_header_tags, parse_icc_profile_tags

    try:
        parsed = parse_icc_header_tags(profile, strict_declared_length=True)
        parsed.update(parse_icc_profile_tags(profile, strict_declared_length=True))
    except ValueError as exc:
        _append_quicktime_diagnostic(
            diagnostics,
            "unsupported_color_profile_payload",
            f"unsupported colr ICC_Profile payload: {exc}",
        )
        return
    for name, value in parsed.items():
        tags.append(
            _read_tag(
                name,
                _tag_value(value),
                "ICC_Profile",
                "Image::ExifTool::ICC_Profile::Main",
                name,
                "quicktime-color-profile",
                family_0_group="ICC_Profile",
                family_1_group="ICC_Profile",
                family_2_group="Image",
            )
        )


def _append_quicktime_diagnostic(
    diagnostics: list[str],
    diagnostic_type: str,
    detail: str,
) -> None:
    diagnostics.append(f"QuickTime:{diagnostic_type}:{detail}.")


def _append_extract_embedded_diagnostics(
    diagnostics: list[str],
    state: QuickTimeReadState,
    extract_embedded_level: int,
) -> None:
    if extract_embedded_level <= 0:
        return
    if extract_embedded_level == 1:
        _append_quicktime_diagnostic(
            diagnostics,
            "extract_embedded_bounded_atom_traversal",
            (
                "bounded QuickTime movie/track/media/sample-description traversal executed "
                "without reading mdat media payloads"
            ),
        )
        return
    if state.h264_sample_description_seen and state.h264_sample_bytes_read:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_embedded_video_recursive_dispatch_partial",
            (
                "bounded QuickTimeStream.pl H264 dispatch read declared sample bytes "
                "from finite mdat ranges; broader fragmented/encrypted/unbounded media "
                "payload recursion remains deferred"
            ),
        )
    elif state.h264_sample_description_seen:
        _append_quicktime_diagnostic(
            diagnostics,
            "quicktime_embedded_video_recursive_dispatch_deferred",
            (
                "numeric -ee levels above 1 require ExifTool QuickTimeStream.pl H264 "
                "stream parsing from avcC/sample-table state; this reader exposes the "
                "bounded atom/sample-description metadata but keeps media payload "
                "recursion deferred"
            ),
        )


def _append_extract_embedded_warning_tag(
    tags: list[ReadTag],
    state: QuickTimeReadState,
    extract_embedded_level: int,
) -> None:
    if extract_embedded_level > 0 or not (
        state.h264_sample_description_seen or _has_h264_compressor_tag(tags)
    ):
        return
    # Source: ../exiftool/lib/Image/ExifTool/QuickTime.pm ProcessMOV emits this
    # minor warning for H.264 media where `-ee` may recurse into mdat samples.
    tags.append(
        _read_tag(
            "Warning",
            "[minor] The ExtractEmbedded option may find more tags in the media data",
            "ExifTool",
            "Image::ExifTool",
            "Warning",
            "quicktime-extract-embedded-warning",
            family_0_group="ExifTool",
            family_1_group="ExifTool",
            family_2_group="Other",
        )
    )


def _has_h264_compressor_tag(tags: list[ReadTag]) -> bool:
    return any(tag.name == "CompressorID" and tag.value in {"avc1", "avc3"} for tag in tags)


def _append_quicktime_composite_tags(tags: list[ReadTag], state: QuickTimeReadState) -> None:
    if state.primary_image_width is not None and state.primary_image_height is not None:
        width = state.primary_image_width
        height = state.primary_image_height
        megapixels = round(width * height / 1_000_000, 1)
        tags.append(
            _quicktime_tag(
                "ImageSize",
                f"{width}x{height}",
                "Composite",
                group="Composite",
                family_2_group="Image",
            )
        )
        tags.append(
            _quicktime_tag(
                "Megapixels", megapixels, "Composite", group="Composite", family_2_group="Image"
            )
        )
    if state.media_data_seen and state.movie_duration_ticks is not None and state.movie_time_scale:
        seconds = state.movie_duration_ticks / state.movie_time_scale
        if seconds:
            bitrate = int(state.media_data_size * 8 / seconds + 0.5)
            tags.append(
                _quicktime_tag(
                    "AvgBitrate",
                    _bitrate(bitrate),
                    "Composite",
                    group="Composite",
                    family_2_group="Video",
                )
            )
    if state.first_video_matrix is not None:
        rotation = _rotation_from_matrix(state.first_video_matrix)
        if rotation is not None:
            tags.append(
                _quicktime_tag(
                    "Rotation",
                    int(rotation) if rotation.is_integer() else rotation,
                    "Composite",
                    group="Composite",
                    family_2_group="Video",
                )
            )
    _append_quicktime_gps_composite_tags(tags)


def _append_quicktime_gps_composite_tags(tags: list[ReadTag]) -> None:
    coordinates = _quicktime_gps_coordinates_from_tags(tags)
    if coordinates is None:
        return
    latitude, longitude, altitude = coordinates
    rendered_latitude = _quicktime_gps_dms(latitude, "N", "S")
    rendered_longitude = _quicktime_gps_dms(longitude, "E", "W")
    tags.append(
        _quicktime_tag(
            "GPSLatitude",
            rendered_latitude,
            "Composite",
            group="Composite",
            family_2_group="Location",
        )
    )
    tags.append(
        _quicktime_tag(
            "GPSLongitude",
            rendered_longitude,
            "Composite",
            group="Composite",
            family_2_group="Location",
        )
    )
    if altitude is not None:
        tags.append(
            _quicktime_tag(
                "GPSAltitude",
                f"{_compact_number(abs(altitude))} m",
                "Composite",
                group="Composite",
                family_2_group="Location",
            )
        )
        tags.append(
            _quicktime_tag(
                "GPSAltitudeRef",
                "Below Sea Level" if altitude < 0 else "Above Sea Level",
                "Composite",
                group="Composite",
                family_2_group="Location",
            )
        )
    tags.append(
        _quicktime_tag(
            "GPSPosition",
            f"{rendered_latitude}, {rendered_longitude}",
            "Composite",
            group="Composite",
            family_2_group="Location",
        )
    )


def _quicktime_gps_coordinates_from_tags(
    tags: list[ReadTag],
) -> tuple[float, float, float | None] | None:
    for tag in tags:
        if tag.name == "GPSCoordinates" and isinstance(tag.value, str):
            coordinates = _parse_quicktime_gps_coordinates(tag.value)
            if coordinates is not None:
                return coordinates
    for tag in tags:
        if tag.name == "LocationInformation" and isinstance(tag.value, str):
            coordinates = _parse_quicktime_location_information_coordinates(tag.value)
            if coordinates is not None:
                return coordinates
    return None


def _parse_quicktime_gps_coordinates(value: str) -> tuple[float, float, float | None] | None:
    parts = [part.strip() for part in value.replace(" ", ",").split(",") if part.strip()]
    if len(parts) < 2:
        return None
    try:
        latitude = float(parts[0])
        longitude = float(parts[1])
        altitude = float(parts[2]) if len(parts) > 2 else None
    except ValueError:
        return None
    return latitude, longitude, altitude


def _parse_quicktime_location_information_coordinates(
    value: str,
) -> tuple[float, float, float | None] | None:
    latitude = _quicktime_labeled_float(value, "Lat=")
    longitude = _quicktime_labeled_float(value, "Lon=")
    altitude = _quicktime_labeled_float(value, "Alt=")
    if latitude is None or longitude is None:
        return None
    return latitude, longitude, altitude


def _quicktime_labeled_float(value: str, label: str) -> float | None:
    start = value.find(label)
    if start < 0:
        return None
    cursor = start + len(label)
    end = cursor
    while end < len(value) and value[end] in "+-.0123456789":
        end += 1
    if end == cursor:
        return None
    try:
        return float(value[cursor:end])
    except ValueError:
        return None


def _quicktime_gps_dms(value: float, positive_ref: str, negative_ref: str) -> str:
    reference = negative_ref if value < 0 else positive_ref
    absolute = abs(value)
    degrees = int(absolute)
    minutes_float = (absolute - degrees) * 60
    minutes = int(minutes_float)
    seconds = round((minutes_float - minutes) * 60, 2)
    if seconds >= 60:
        seconds = 0
        minutes += 1
    if minutes >= 60:
        minutes = 0
        degrees += 1
    return f"{degrees} deg {minutes}' {seconds:.2f}\" {reference}"


def _compatible_brands(data: bytes) -> list[str]:
    brands: list[str] = []
    for offset in range(0, len(data) - len(data) % 4, 4):
        brand = data[offset : offset + 4].decode("latin-1", errors="replace")
        if brand and "\0" not in brand:
            brands.append(brand)
    return brands


def _minor_version(data: bytes) -> str:
    if len(data) < 4:
        return ""
    major = int.from_bytes(data[:2], "big")
    minor = data[2]
    patch = data[3]
    return f"{major:x}.{minor:x}.{patch:x}"


def _quicktime_file_type(path: Path, payload: bytes) -> tuple[str, str, str]:
    suffix = path.suffix.lower()
    if suffix in QUICKTIME_EXTENSION_FILE_TYPES:
        return QUICKTIME_EXTENSION_FILE_TYPES[suffix]
    brands = _compatible_brands(payload[8:]) if len(payload) >= 12 else []
    if len(payload) >= 4:
        brands.insert(0, payload[:4].decode("latin-1", errors="replace"))
    if "qt  " in brands:
        return "MOV", "mov", "video/quicktime"
    if "f4v " in brands:
        return "F4V", "f4v", "video/mp4"
    return "MP4", "mp4", "video/mp4"


def _walk_atoms(atoms: tuple[QuickTimeAtomSpan, ...]) -> tuple[QuickTimeAtomSpan, ...]:
    walked: list[QuickTimeAtomSpan] = []
    for atom in atoms:
        walked.append(atom)
        walked.extend(_walk_atoms(atom.children))
    return tuple(walked)


def _walk_atoms_cached(
    state: QuickTimeReadState,
    atoms: tuple[QuickTimeAtomSpan, ...],
) -> tuple[QuickTimeAtomSpan, ...]:
    cache_key = id(atoms)
    walked = state.atom_walk_cache.get(cache_key)
    if walked is None:
        walked = _walk_atoms(atoms)
        state.atom_walk_cache[cache_key] = walked
    return walked


def _first_atom(atoms: tuple[QuickTimeAtomSpan, ...], atom_type: str) -> QuickTimeAtomSpan | None:
    for atom in atoms:
        if atom.atom_type == atom_type:
            return atom
    return None


def _track_handler_type_from_atoms(track_atoms: tuple[QuickTimeAtomSpan, ...]) -> str:
    for atom in track_atoms:
        if atom.atom_type == "hdlr":
            return _handler_type(atom.payload) or ""
    return ""


def _track_id_from_atoms(track_atoms: tuple[QuickTimeAtomSpan, ...]) -> int | None:
    for atom in track_atoms:
        if atom.atom_type == "tkhd" and len(atom.payload) >= 24:
            if atom.payload[0] == 1:
                if len(atom.payload) < 36:
                    return None
                return int.from_bytes(atom.payload[20:24], "big")
            return int.from_bytes(atom.payload[12:16], "big")
    return None


def _track_media_time_scale_from_atoms(track_atoms: tuple[QuickTimeAtomSpan, ...]) -> int | None:
    for atom in track_atoms:
        if atom.atom_type == "mdhd":
            return _media_time_scale(atom.payload)
    return None


def _media_time_scale(payload: bytes) -> int | None:
    if len(payload) < 24:
        return None
    if payload[0] == 1:
        if len(payload) < 36:
            return None
        return int.from_bytes(payload[20:24], "big")
    return int.from_bytes(payload[12:16], "big")


def _quicktime_time(value: int) -> str:
    if value == 0:
        return "0000:00:00 00:00:00"
    # QuickTime timestamps are seconds since 1904-01-01. Full timezone/local
    # conversion is a later raw/print-conversion seam; preserve deterministic UTC.
    unix_seconds = value - ((66 * 365 + 17) * 24 * 3600)
    return time.strftime("%Y:%m:%d %H:%M:%S", time.gmtime(unix_seconds))


def _duration(ticks: int, time_scale: int) -> str:
    if time_scale <= 0:
        return str(ticks)
    seconds = ticks / time_scale
    return f"{seconds:.2f} s" if seconds != int(seconds) else f"{int(seconds)} s"


def _fixed_unsigned(data: bytes, fraction_bits: int) -> float:
    if not data:
        return 0.0
    return int.from_bytes(data, "big") / float(1 << fraction_bits)


def _fixed_signed(data: bytes, fraction_bits: int) -> float:
    if not data:
        return 0.0
    return int.from_bytes(data, "big", signed=True) / float(1 << fraction_bits)


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _matrix(data: bytes) -> tuple[float, ...]:
    values: list[float] = []
    for index in range(9):
        start = index * 4
        raw = int.from_bytes(data[start : start + 4], "big", signed=True)
        fraction_bits = 30 if index in {2, 5, 8} else 16
        values.append(raw / float(1 << fraction_bits))
    return tuple(values)


def _matrix_text(matrix: tuple[float, ...]) -> str:
    return " ".join(_compact_number(value) for value in matrix)


def _compact_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _rounded_number(value: float) -> int | float:
    rounded = math.floor(value * 1000 + 0.5) / 1000
    return int(rounded) if rounded == int(rounded) else rounded


def _rotation_from_matrix(matrix: tuple[float, ...]) -> float | None:
    if len(matrix) < 2 or (matrix[0] == 0 and matrix[1] == 0):
        return None

    angle = math.atan2(matrix[1], matrix[0]) * 180 / math.pi
    if angle < 0:
        angle += 360
    return round(angle, 3)


def _handler_type(payload: bytes) -> str | None:
    if len(payload) < 12:
        return None
    return payload[8:12].decode("latin-1", errors="replace")


def _handler_type_description(handler_type: str) -> str:
    return {
        "alis": "Alias Data",
        "crsm": "Clock Reference",
        "hint": "Hint Track",
        "ipsm": "IPMP",
        "m7sm": "MPEG-7 Stream",
        "vide": "Video Track",
        "soun": "Audio Track",
        "meta": "NRT Metadata",
        "mdir": "Metadata",
        "mdta": "Metadata Tags",
        "mjsm": "MPEG-J",
        "ocsm": "Object Content",
        "odsm": "Object Descriptor",
        "priv": "Private",
        "sdsm": "Scene Description",
        "subp": "Subpicture",
        "text": "Text",
        "tmcd": "Time Code",
        "url ": "URL",
        "nrtm": "Non-Real Time Metadata",
        "pict": "Picture",
        "camm": "Camera Metadata",
        "psmd": "Panasonic Static Metadata",
        "data": "Data",
        "sbtl": "Subtitle",
    }.get(handler_type, handler_type)


def _handler_class_description(handler_class: str) -> str:
    return {
        "mhlr": "Media Handler",
        "dhlr": "Data Handler",
    }.get(handler_class, handler_class)


def _language_code(value: int) -> str | int:
    if value in {0, 0x7FFF}:
        return "und"
    if value < 0x400:
        return value
    return "".join(chr(((value >> shift) & 0x1F) + 0x60) for shift in (10, 5, 0))


def _compressor_name(data: bytes) -> str:
    return _pascal_or_c_string(data)


def _pascal_or_c_string(data: bytes) -> str:
    if not data:
        return ""
    length = data[0]
    if length < len(data) and length < 32:
        return data[1 : 1 + length].decode("latin-1", errors="replace")
    return data.split(b"\0", 1)[0].decode("latin-1", errors="replace")


def _rational64_signed(data: bytes) -> str:
    numerator = int.from_bytes(data[:4], "big", signed=True)
    denominator = int.from_bytes(data[4:8], "big", signed=True)
    if denominator == 0:
        return f"{numerator}/0"
    return _compact_number(numerator / denominator)


def _rational64_unsigned(data: bytes) -> str:
    numerator = int.from_bytes(data[:4], "big")
    denominator = int.from_bytes(data[4:8], "big")
    if denominator == 0:
        return f"{numerator}/0"
    return _compact_number(numerator / denominator)


def _channel_type_bitmask(value: int) -> str:
    labels: list[str] = []
    for bit, label in enumerate(QUICKTIME_CHANNEL_TYPE_BITS):
        if value & (1 << bit):
            labels.append(label)
    return ", ".join(labels) if labels else "0"


def _channel_description_flags(value: int) -> str:
    labels: list[str] = []
    for bit, label in enumerate(("Rectangular", "Spherical", "Meters")):
        if value & (1 << bit):
            labels.append(label)
    return ", ".join(labels) if labels else "0"


def _bitrate(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} Mbps"
    if value >= 1_000:
        return f"{value / 1_000:.0f} kbps"
    return f"{value} bps"


def _system_tags(path: Path, source_file: str) -> list[ReadTag]:
    from exifmodern.services.system_metadata import read_system_tags

    return [
        _read_tag(
            name,
            _tag_value(value),
            "System",
            "Image::ExifTool::Extra",
            name,
            "filesystem",
            family_1_group="System",
            family_2_group="Time" if name.endswith("Date") else "Other",
        )
        for name, value in read_system_tags(path, source_file).items()
    ]


def _tag_value(value: JsonValue) -> TagValue:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            if not isinstance(item, str):
                return str(value)
            strings.append(item)
        return strings
    return str(value)


def _file_type_tags(
    file_type: str,
    extension: str,
    mime_type: str,
    source: str,
) -> list[ReadTag]:
    return [
        _read_tag("FileType", file_type, "File", "Image::ExifTool::File", None, source),
        _read_tag(
            "FileTypeExtension",
            extension,
            "File",
            "Image::ExifTool::File",
            None,
            source,
        ),
        _read_tag("MIMEType", mime_type, "File", "Image::ExifTool::File", None, source),
    ]


def _read_tag(
    name: str,
    value: TagValue,
    group: str,
    table_name: str,
    tag_id: str | None,
    source: str,
    *,
    family_0_group: str | None = None,
    family_1_group: str | None = None,
    family_2_group: str = "Other",
) -> ReadTag:
    return ReadTag(
        name=name,
        value=value,
        provenance=TagProvenance(
            group,
            table_name,
            tag_id,
            source,
            family_0_group=family_0_group or ("File" if group in {"File", "System"} else group),
            family_1_group=family_1_group or group,
            family_2_group=family_2_group,
        ),
        schema=None,
    )


def _quicktime_tag(
    name: str,
    value: TagValue,
    tag_id: str | None,
    *,
    group: str = "QuickTime",
    table_name: str | None = None,
    family_2_group: str = "Video",
) -> ReadTag:
    return _read_tag(
        name,
        value,
        group,
        table_name
        or (
            "Image::ExifTool::QuickTime::Main"
            if group == "QuickTime"
            else "Image::ExifTool::Composite"
        ),
        tag_id,
        "quicktime-atom-traversal",
        family_2_group=family_2_group,
    )


def _quicktime_table_tag(
    name: str,
    value: TagValue,
    tag_id: str | None,
    table_name: str,
    *,
    family_2_group: str = "Video",
) -> ReadTag:
    return _read_tag(
        name,
        value,
        "QuickTime",
        table_name,
        tag_id,
        "quicktime-atom-traversal",
        family_2_group=family_2_group,
    )


def _with_track_family_1_group(tag: ReadTag, track_group: str) -> ReadTag:
    provenance = tag.provenance
    if provenance.group != "QuickTime" or provenance.family_1_group != "QuickTime":
        return tag
    return replace(
        tag,
        provenance=replace(
            provenance,
            family_1_group=track_group,
        ),
    )
