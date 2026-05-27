"""Source-backed QuickTime metadata atom planning and encoding.

The supported tables and atom layouts are intentionally limited to the
ItemList/UserData/Keys surfaces used by upstream QuickTime metadata writes.
Source oracle anchors are tracked outside this production module.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.quicktime.atoms import (
    QuickTimeAtom,
    encode_quicktime_atom,
    read_quicktime_atoms,
)

type QuickTimeMetadataGroup = Literal[
    "ItemList",
    "UserData",
    "Keys",
    "AudioKeys",
    "VideoKeys",
]
type QuickTimeMetadataWriteMode = Literal["overwrite", "create"]
type QuickTimeItemListValueFormat = Literal[
    "utf8",
    "int8s",
    "int16s",
    "int8u",
    "int16u",
    "int32s",
    "int32u",
    "int64s",
    "int64u",
    "float",
    "double",
    "genre_id",
    "milliseconds_text",
    "gps_iso6709",
    "track_number",
    "disk_number",
    "yes_no_int8s",
    "play_gap",
    "apple_store_account_type",
    "content_rating",
    "media_type",
    "binary",
]

QT_MOVIE_ATOM = "moov"
QT_TRACK_ATOM = "trak"
QT_USER_DATA_ATOM = "udta"
QT_META_ATOM = "meta"
QT_ITEM_LIST_ATOM = "ilst"
QT_KEYS_ATOM = "keys"
QT_HANDLER_ATOM = "hdlr"
QT_DATA_ATOM = "data"
QT_UTF8_DATA_FLAGS = 0x01
QT_UNDEFINED_DATA_FLAGS = 0x00
QT_SIGNED_INTEGER_DATA_FLAGS = 0x15
QT_METADATA_NAMESPACE = "mdta"
QT_METADATA_HANDLER = "mdta"
QT_ITEM_LIST_HANDLER = "mdir"
QT_DEFAULT_COUNTRY = 0
QT_DEFAULT_LANGUAGE = 0


@dataclass(frozen=True)
class QuickTimeMetadataTag:
    group: QuickTimeMetadataGroup
    name: str
    atom_id: str
    key_id: str | None = None
    item_list_format: QuickTimeItemListValueFormat = "utf8"


@dataclass(frozen=True)
class QuickTimeMetadataValue:
    group: QuickTimeMetadataGroup
    name: str
    value: str | None
    language_code: str | None = None
    atom_id_override: str | None = None


@dataclass(frozen=True)
class QuickTimeMetadataDeleteGroup:
    group: QuickTimeMetadataGroup


@dataclass(frozen=True)
class QuickTimeMetadataWritePlan:
    values: tuple[QuickTimeMetadataValue, ...]
    delete_groups: tuple[QuickTimeMetadataDeleteGroup, ...] = ()
    write_mode: QuickTimeMetadataWriteMode = "overwrite"


@dataclass(frozen=True)
class ParsedQuickTimeWriteArgs:
    plan: QuickTimeMetadataWritePlan
    unsupported: tuple[str, ...]


@dataclass(frozen=True)
class QuickTimeDataAtom:
    flags: int
    country: int
    language: int
    value: bytes


ITEM_LIST_TAGS: dict[str, QuickTimeMetadataTag] = {
    "Album": QuickTimeMetadataTag("ItemList", "Album", "\xa9alb"),
    "AlbumID": QuickTimeMetadataTag("ItemList", "AlbumID", "plID", item_list_format="int32s"),
    "AlbumArtist": QuickTimeMetadataTag("ItemList", "AlbumArtist", "aART"),
    "AppleStoreAccount": QuickTimeMetadataTag("ItemList", "AppleStoreAccount", "apID"),
    "AppleStoreAccountType": QuickTimeMetadataTag(
        "ItemList", "AppleStoreAccountType", "akID", item_list_format="apple_store_account_type"
    ),
    "AppleStoreCatalogID": QuickTimeMetadataTag(
        "ItemList", "AppleStoreCatalogID", "cnID", item_list_format="int32s"
    ),
    "AppleStoreCountry": QuickTimeMetadataTag(
        "ItemList", "AppleStoreCountry", "sfID", item_list_format="int32s"
    ),
    "ArtDirector": QuickTimeMetadataTag("ItemList", "ArtDirector", "\xa9ard"),
    "Arranger": QuickTimeMetadataTag("ItemList", "Arranger", "\xa9arg"),
    "Artist": QuickTimeMetadataTag("ItemList", "Artist", "\xa9ART"),
    "ArtistID": QuickTimeMetadataTag("ItemList", "ArtistID", "atID", item_list_format="int32s"),
    "Author": QuickTimeMetadataTag("ItemList", "Author", "auth"),
    "Category": QuickTimeMetadataTag("ItemList", "Category", "catg"),
    "Comment": QuickTimeMetadataTag("ItemList", "Comment", "\xa9cmt"),
    "Conductor": QuickTimeMetadataTag("ItemList", "Conductor", "\xa9con"),
    "Composer": QuickTimeMetadataTag("ItemList", "Composer", "\xa9wrt"),
    "Copyright": QuickTimeMetadataTag("ItemList", "Copyright", "cprt"),
    "Compilation": QuickTimeMetadataTag(
        "ItemList", "Compilation", "cpil", item_list_format="yes_no_int8s"
    ),
    "Description": QuickTimeMetadataTag("ItemList", "Description", "\xa9des"),
    "ContentCreateDate": QuickTimeMetadataTag("ItemList", "ContentCreateDate", "\xa9day"),
    "Director": QuickTimeMetadataTag("ItemList", "Director", "\xa9dir"),
    "DiskNumber": QuickTimeMetadataTag(
        "ItemList", "DiskNumber", "disk", item_list_format="disk_number"
    ),
    "EncodedBy": QuickTimeMetadataTag("ItemList", "EncodedBy", "\xa9enc"),
    "Encoder": QuickTimeMetadataTag("ItemList", "Encoder", "\xa9too"),
    "ExecutiveProducer": QuickTimeMetadataTag("ItemList", "ExecutiveProducer", "\xa9xpd"),
    "Genre": QuickTimeMetadataTag("ItemList", "Genre", "\xa9gen"),
    "GenreID": QuickTimeMetadataTag("ItemList", "GenreID", "geID", item_list_format="int32s"),
    "EpisodeGlobalUniqueID": QuickTimeMetadataTag("ItemList", "EpisodeGlobalUniqueID", "egid"),
    "GoogleHostHeader": QuickTimeMetadataTag("ItemList", "GoogleHostHeader", "gshh"),
    "GooglePingMessage": QuickTimeMetadataTag("ItemList", "GooglePingMessage", "gspm"),
    "GooglePingURL": QuickTimeMetadataTag("ItemList", "GooglePingURL", "gspu"),
    "GoogleSourceData": QuickTimeMetadataTag("ItemList", "GoogleSourceData", "gssd"),
    "GoogleStartTime": QuickTimeMetadataTag("ItemList", "GoogleStartTime", "gsst"),
    "GoogleTrackDuration": QuickTimeMetadataTag(
        "ItemList", "GoogleTrackDuration", "gstd", item_list_format="milliseconds_text"
    ),
    "GPSCoordinates": QuickTimeMetadataTag(
        "ItemList", "GPSCoordinates", "\xa9xyz", item_list_format="gps_iso6709"
    ),
    "Grouping": QuickTimeMetadataTag("ItemList", "Grouping", "\xa9grp"),
    "HDVideo": QuickTimeMetadataTag("ItemList", "HDVideo", "hdvd", item_list_format="yes_no_int8s"),
    "iTunesU": QuickTimeMetadataTag("ItemList", "iTunesU", "itnu", item_list_format="yes_no_int8s"),
    "ISRC": QuickTimeMetadataTag("ItemList", "ISRC", "xid "),
    "Keyword": QuickTimeMetadataTag("ItemList", "Keyword", "keyw"),
    "LongDescription": QuickTimeMetadataTag("ItemList", "LongDescription", "ldes"),
    "Lyrics": QuickTimeMetadataTag("ItemList", "Lyrics", "\xa9lyr"),
    "MediaType": QuickTimeMetadataTag(
        "ItemList", "MediaType", "stik", item_list_format="media_type"
    ),
    "MovementCount": QuickTimeMetadataTag(
        "ItemList", "MovementCount", "\xa9mvc", item_list_format="int16s"
    ),
    "MovementName": QuickTimeMetadataTag("ItemList", "MovementName", "\xa9mvn"),
    "MovementNumber": QuickTimeMetadataTag(
        "ItemList", "MovementNumber", "\xa9mvi", item_list_format="int16s"
    ),
    "OriginalArtist": QuickTimeMetadataTag("ItemList", "OriginalArtist", "\xa9ope"),
    "Owner": QuickTimeMetadataTag("ItemList", "Owner", "ownr"),
    "Performer": QuickTimeMetadataTag("ItemList", "Performer", "perf"),
    "Podcast": QuickTimeMetadataTag("ItemList", "Podcast", "pcst", item_list_format="yes_no_int8s"),
    "PodcastURL": QuickTimeMetadataTag("ItemList", "PodcastURL", "purl"),
    "Producer": QuickTimeMetadataTag("ItemList", "Producer", "\xa9prd"),
    "Publisher": QuickTimeMetadataTag("ItemList", "Publisher", "\xa9pub"),
    "PurchaseDate": QuickTimeMetadataTag("ItemList", "PurchaseDate", "purd"),
    "Rating": QuickTimeMetadataTag("ItemList", "Rating", "rtng", item_list_format="content_rating"),
    "Soloist": QuickTimeMetadataTag("ItemList", "Soloist", "\xa9sol"),
    "SoundEngineer": QuickTimeMetadataTag("ItemList", "SoundEngineer", "\xa9sne"),
    "ShowMovement": QuickTimeMetadataTag(
        "ItemList", "ShowMovement", "shwm", item_list_format="yes_no_int8s"
    ),
    "SortAlbum": QuickTimeMetadataTag("ItemList", "SortAlbum", "soal"),
    "SortAlbumArtist": QuickTimeMetadataTag("ItemList", "SortAlbumArtist", "soaa"),
    "SortArtist": QuickTimeMetadataTag("ItemList", "SortArtist", "soar"),
    "SortComposer": QuickTimeMetadataTag("ItemList", "SortComposer", "soco"),
    "SortName": QuickTimeMetadataTag("ItemList", "SortName", "sonm"),
    "SortShow": QuickTimeMetadataTag("ItemList", "SortShow", "sosn"),
    "StoreDescription": QuickTimeMetadataTag("ItemList", "StoreDescription", "sdes"),
    "Subtitle": QuickTimeMetadataTag("ItemList", "Subtitle", "\xa9st3"),
    "Title": QuickTimeMetadataTag("ItemList", "Title", "\xa9nam"),
    "Track": QuickTimeMetadataTag("ItemList", "Track", "\xa9trk"),
    "TrackNumber": QuickTimeMetadataTag(
        "ItemList", "TrackNumber", "trkn", item_list_format="track_number"
    ),
    "TVEpisode": QuickTimeMetadataTag("ItemList", "TVEpisode", "tves", item_list_format="int32s"),
    "TVEpisodeID": QuickTimeMetadataTag("ItemList", "TVEpisodeID", "tven"),
    "TVNetworkName": QuickTimeMetadataTag("ItemList", "TVNetworkName", "tvnn"),
    "TVSeason": QuickTimeMetadataTag("ItemList", "TVSeason", "tvsn", item_list_format="int32u"),
    "TVShow": QuickTimeMetadataTag("ItemList", "TVShow", "tvsh"),
    "Work": QuickTimeMetadataTag("ItemList", "Work", "\xa9wrk"),
    "Year": QuickTimeMetadataTag("ItemList", "Year", "yrrc"),
    "Narrator": QuickTimeMetadataTag("ItemList", "Narrator", "\xa9nrt"),
    "ProductID": QuickTimeMetadataTag("ItemList", "ProductID", "prID"),
    "ReleaseDate": QuickTimeMetadataTag("ItemList", "ReleaseDate", "rldt"),
    "ProductVersion": QuickTimeMetadataTag("ItemList", "ProductVersion", "VERS"),
    "GUID": QuickTimeMetadataTag("ItemList", "GUID", "GUID"),
    "BeatsPerMinute": QuickTimeMetadataTag(
        "ItemList", "BeatsPerMinute", "tmpo", item_list_format="int16s"
    ),
    "CoverArt": QuickTimeMetadataTag("ItemList", "CoverArt", "covr", item_list_format="binary"),
    "PlayGap": QuickTimeMetadataTag("ItemList", "PlayGap", "pgap", item_list_format="play_gap"),
}

YES_NO_INT8S_VALUES = {
    "no": 0,
    "yes": 1,
}
PLAY_GAP_VALUES = {
    "insert gap": 0,
    "no gap": 1,
}
APPLE_STORE_ACCOUNT_TYPE_VALUES = {
    "itunes": 0,
    "aol": 1,
}
CONTENT_RATING_VALUES = {
    "none": 0,
    "explicit": 1,
    "clean": 2,
    "explicit (old)": 4,
}
MEDIA_TYPE_VALUES = {
    "movie (old)": 0,
    "normal (music)": 1,
    "audiobook": 2,
    "whacked bookmark": 5,
    "music video": 6,
    "movie": 9,
    "tv show": 10,
    "booklet": 11,
    "ringtone": 14,
    "podcast": 21,
    "itunes u": 23,
    "itunes  u": 23,
}

USER_DATA_TAGS: dict[str, QuickTimeMetadataTag] = {
    "Album": QuickTimeMetadataTag("UserData", "Album", "\xa9alb"),
    "Arranger": QuickTimeMetadataTag("UserData", "Arranger", "\xa9arg"),
    "ArrangerKeywords": QuickTimeMetadataTag("UserData", "ArrangerKeywords", "\xa9ark"),
    "Artist": QuickTimeMetadataTag("UserData", "Artist", "\xa9ART"),
    "Comment": QuickTimeMetadataTag("UserData", "Comment", "\xa9cmt"),
    "Composer": QuickTimeMetadataTag("UserData", "Composer", "\xa9com"),
    "ComposerKeywords": QuickTimeMetadataTag("UserData", "ComposerKeywords", "\xa9cok"),
    "ContentCreateDate": QuickTimeMetadataTag("UserData", "ContentCreateDate", "\xa9day"),
    "Copyright": QuickTimeMetadataTag("UserData", "Copyright", "\xa9cpy"),
    "Director": QuickTimeMetadataTag("UserData", "Director", "\xa9dir"),
    "Edit1": QuickTimeMetadataTag("UserData", "Edit1", "\xa9ed1"),
    "Edit2": QuickTimeMetadataTag("UserData", "Edit2", "\xa9ed2"),
    "Edit3": QuickTimeMetadataTag("UserData", "Edit3", "\xa9ed3"),
    "Edit4": QuickTimeMetadataTag("UserData", "Edit4", "\xa9ed4"),
    "Edit5": QuickTimeMetadataTag("UserData", "Edit5", "\xa9ed5"),
    "Edit6": QuickTimeMetadataTag("UserData", "Edit6", "\xa9ed6"),
    "Edit7": QuickTimeMetadataTag("UserData", "Edit7", "\xa9ed7"),
    "Edit8": QuickTimeMetadataTag("UserData", "Edit8", "\xa9ed8"),
    "Edit9": QuickTimeMetadataTag("UserData", "Edit9", "\xa9ed9"),
    "Encoder": QuickTimeMetadataTag("UserData", "Encoder", "\xa9too"),
    "Format": QuickTimeMetadataTag("UserData", "Format", "\xa9fmt"),
    "Genre": QuickTimeMetadataTag("UserData", "Genre", "\xa9gen"),
    "GPSCoordinates": QuickTimeMetadataTag(
        "UserData", "GPSCoordinates", "\xa9xyz", item_list_format="gps_iso6709"
    ),
    "Grouping": QuickTimeMetadataTag("UserData", "Grouping", "\xa9grp"),
    "Information": QuickTimeMetadataTag("UserData", "Information", "\xa9inf"),
    "ISRCCode": QuickTimeMetadataTag("UserData", "ISRCCode", "\xa9isr"),
    "Lyrics": QuickTimeMetadataTag("UserData", "Lyrics", "\xa9lyr"),
    "Make": QuickTimeMetadataTag("UserData", "Make", "\xa9mak"),
    "MakerURL": QuickTimeMetadataTag("UserData", "MakerURL", "\xa9mal"),
    "Model": QuickTimeMetadataTag("UserData", "Model", "\xa9mod"),
    "Name": QuickTimeMetadataTag("UserData", "Name", "name"),
    "PerformerKeywords": QuickTimeMetadataTag("UserData", "PerformerKeywords", "\xa9prk"),
    "PerformerURL": QuickTimeMetadataTag("UserData", "PerformerURL", "\xa9prl"),
    "Performers": QuickTimeMetadataTag("UserData", "Performers", "\xa9prf"),
    "Producer": QuickTimeMetadataTag("UserData", "Producer", "\xa9prd"),
    "ProducerKeywords": QuickTimeMetadataTag("UserData", "ProducerKeywords", "\xa9pdk"),
    "RecordLabelName": QuickTimeMetadataTag("UserData", "RecordLabelName", "\xa9lab"),
    "RecordLabelURL": QuickTimeMetadataTag("UserData", "RecordLabelURL", "\xa9lal"),
    "RecordingCopyright": QuickTimeMetadataTag("UserData", "RecordingCopyright", "\xa9phg"),
    "Requirements": QuickTimeMetadataTag("UserData", "Requirements", "\xa9req"),
    "SoftwareVersion": QuickTimeMetadataTag("UserData", "SoftwareVersion", "\xa9swr"),
    "SongWriter": QuickTimeMetadataTag("UserData", "SongWriter", "\xa9swf"),
    "SongWriterKeywords": QuickTimeMetadataTag("UserData", "SongWriterKeywords", "\xa9swk"),
    "SourceCredits": QuickTimeMetadataTag("UserData", "SourceCredits", "\xa9src"),
    "Subtitle": QuickTimeMetadataTag("UserData", "Subtitle", "\xa9snm"),
    "SubtitleKeywords": QuickTimeMetadataTag("UserData", "SubtitleKeywords", "\xa9snk"),
    "Title": QuickTimeMetadataTag("UserData", "Title", "\xa9nam"),
    "Track": QuickTimeMetadataTag("UserData", "Track", "\xa9trk"),
}

KEYS_TAGS: dict[str, QuickTimeMetadataTag] = {
    "Album": QuickTimeMetadataTag("Keys", "Album", "", "album"),
    "AndroidMake": QuickTimeMetadataTag("Keys", "AndroidMake", "", "com.android.manufacturer"),
    "AndroidModel": QuickTimeMetadataTag("Keys", "AndroidModel", "", "com.android.model"),
    "AndroidVersion": QuickTimeMetadataTag("Keys", "AndroidVersion", "", "com.android.version"),
    "AndroidCaptureFPS": QuickTimeMetadataTag(
        "Keys", "AndroidCaptureFPS", "", "com.android.capture.fps", item_list_format="float"
    ),
    "AndroidTimeZone": QuickTimeMetadataTag(
        "Keys", "AndroidTimeZone", "", "samsung.android.utc_offset"
    ),
    "Artist": QuickTimeMetadataTag("Keys", "Artist", "", "artist"),
    "Author": QuickTimeMetadataTag("Keys", "Author", "", "author"),
    "Brightness": QuickTimeMetadataTag("Keys", "Brightness", "", "player.movie.visual.brightness"),
    "CameraDirection": QuickTimeMetadataTag("Keys", "CameraDirection", "", "direction.facing"),
    "CameraMotion": QuickTimeMetadataTag("Keys", "CameraMotion", "", "direction.motion"),
    "Color": QuickTimeMetadataTag("Keys", "Color", "", "player.movie.visual.color"),
    "Comment": QuickTimeMetadataTag("Keys", "Comment", "", "comment"),
    "ContentIdentifier": QuickTimeMetadataTag(
        "Keys", "ContentIdentifier", "", "content.identifier"
    ),
    "Copyright": QuickTimeMetadataTag("Keys", "Copyright", "", "copyright"),
    "CreationDate": QuickTimeMetadataTag("Keys", "CreationDate", "", "creationdate"),
    "Description": QuickTimeMetadataTag("Keys", "Description", "", "description"),
    "Director": QuickTimeMetadataTag("Keys", "Director", "", "director"),
    "DisplayName": QuickTimeMetadataTag("Keys", "DisplayName", "", "displayname"),
    "EncodedWith": QuickTimeMetadataTag("Keys", "EncodedWith", "", "Encoded_With"),
    "Encoder": QuickTimeMetadataTag("Keys", "Encoder", "", "encoder"),
    "Genre": QuickTimeMetadataTag("Keys", "Genre", "", "genre"),
    "Information": QuickTimeMetadataTag("Keys", "Information", "", "information"),
    "Keywords": QuickTimeMetadataTag("Keys", "Keywords", "", "keywords"),
    "LocationAccuracyHorizontal": QuickTimeMetadataTag(
        "Keys", "LocationAccuracyHorizontal", "", "location.accuracy.horizontal"
    ),
    "LocationBody": QuickTimeMetadataTag("Keys", "LocationBody", "", "location.body"),
    "LocationDate": QuickTimeMetadataTag("Keys", "LocationDate", "", "location.date"),
    "LocationName": QuickTimeMetadataTag("Keys", "LocationName", "", "location.name"),
    "LocationNote": QuickTimeMetadataTag("Keys", "LocationNote", "", "location.note"),
    "LocationRole": QuickTimeMetadataTag("Keys", "LocationRole", "", "location.role"),
    "GPSCoordinates": QuickTimeMetadataTag(
        "Keys", "GPSCoordinates", "", "location.ISO6709", item_list_format="gps_iso6709"
    ),
    "Make": QuickTimeMetadataTag("Keys", "Make", "", "make"),
    "Model": QuickTimeMetadataTag("Keys", "Model", "", "model"),
    "PlayerVersion": QuickTimeMetadataTag("Keys", "PlayerVersion", "", "player.version"),
    "Producer": QuickTimeMetadataTag("Keys", "Producer", "", "producer"),
    "Publisher": QuickTimeMetadataTag("Keys", "Publisher", "", "publisher"),
    "Software": QuickTimeMetadataTag("Keys", "Software", "", "software"),
    "Tint": QuickTimeMetadataTag("Keys", "Tint", "", "player.movie.visual.tint"),
    "Contrast": QuickTimeMetadataTag("Keys", "Contrast", "", "player.movie.visual.contrast"),
    "AudioGain": QuickTimeMetadataTag("Keys", "AudioGain", "", "player.movie.audio.gain"),
    "Bass": QuickTimeMetadataTag("Keys", "Bass", "", "player.movie.audio.bass"),
    "Balance": QuickTimeMetadataTag("Keys", "Balance", "", "player.movie.audio.balance"),
    "PitchShift": QuickTimeMetadataTag("Keys", "PitchShift", "", "player.movie.audio.pitchshift"),
    "Mute": QuickTimeMetadataTag(
        "Keys", "Mute", "", "player.movie.audio.mute", item_list_format="int8u"
    ),
    "LivePhotoAuto": QuickTimeMetadataTag(
        "Keys", "LivePhotoAuto", "", "live-photo.auto", item_list_format="int8u"
    ),
    "LivePhotoVitalityScore": QuickTimeMetadataTag(
        "Keys", "LivePhotoVitalityScore", "", "live-photo.vitality-score", item_list_format="float"
    ),
    "LivePhotoVitalityScoringVersion": QuickTimeMetadataTag(
        "Keys",
        "LivePhotoVitalityScoringVersion",
        "",
        "live-photo.vitality-scoring-version",
        item_list_format="int64s",
    ),
    "ApplePhotosVariationIdentifier": QuickTimeMetadataTag(
        "Keys",
        "ApplePhotosVariationIdentifier",
        "",
        "apple.photos.variation-identifier",
        item_list_format="int64s",
    ),
    "Title": QuickTimeMetadataTag("Keys", "Title", "", "title"),
    "UserCollection": QuickTimeMetadataTag("Keys", "UserCollection", "", "collection.user"),
    "UserRating": QuickTimeMetadataTag("Keys", "UserRating", "", "rating.user"),
    "Version": QuickTimeMetadataTag("Keys", "Version", "", "version"),
    "XiaomiExifInfo": QuickTimeMetadataTag(
        "Keys", "XiaomiExifInfo", "", "xiaomi.exifInfo.videoinfo"
    ),
    "XiaomiHDR10": QuickTimeMetadataTag(
        "Keys", "XiaomiHDR10", "", "com.xiaomi.hdr10", item_list_format="int32s"
    ),
    "XiaomiPreviewVideoCover": QuickTimeMetadataTag(
        "Keys",
        "XiaomiPreviewVideoCover",
        "",
        "com.xiaomi.preview_video_cover",
        item_list_format="int32s",
    ),
    "Year": QuickTimeMetadataTag("Keys", "Year", "", "year"),
}

AUDIO_KEYS_TAGS: dict[str, QuickTimeMetadataTag] = {
    "Treble": QuickTimeMetadataTag("AudioKeys", "Treble", "", "player.movie.audio.treble"),
}

VIDEO_KEYS_TAGS: dict[str, QuickTimeMetadataTag] = {
    "LensModel": QuickTimeMetadataTag("VideoKeys", "LensModel", "", "camera.lens_model"),
}


def quicktime_metadata_tag(
    group: QuickTimeMetadataGroup,
    name: str,
) -> QuickTimeMetadataTag | None:
    if group == "ItemList":
        return ITEM_LIST_TAGS.get(name)
    if group == "UserData":
        return USER_DATA_TAGS.get(name)
    if group == "Keys":
        return KEYS_TAGS.get(name)
    if group == "AudioKeys":
        return AUDIO_KEYS_TAGS.get(name)
    return VIDEO_KEYS_TAGS.get(name)


def preferred_quicktime_metadata_group(name: str) -> QuickTimeMetadataGroup | None:
    if name in ITEM_LIST_TAGS:
        return "ItemList"
    if name in USER_DATA_TAGS:
        return "UserData"
    if name in KEYS_TAGS:
        return "Keys"
    return None


def parse_quicktime_metadata_write_args(args: tuple[str, ...]) -> ParsedQuickTimeWriteArgs:
    values: list[QuickTimeMetadataValue] = []
    delete_groups: list[QuickTimeMetadataDeleteGroup] = []
    unsupported: list[str] = []
    write_mode: QuickTimeMetadataWriteMode = "overwrite"
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-api":
            index += 2
            if index <= len(args):
                api_value = args[index - 1]
                if api_value == "WriteMode=c":
                    write_mode = "create"
                elif api_value not in {"QuickTimeHandler=1", "Composite=0", "Protected=1"}:
                    unsupported.append(f"Unsupported QuickTime API option: {api_value}")
            continue
        if not arg.startswith("-") or "=" not in arg:
            unsupported.append(f"Unsupported QuickTime write argument: {arg}")
            index += 1
            continue
        spec, value = arg[1:].split("=", 1)
        parsed = parse_quicktime_metadata_assignment(spec, value)
        if parsed is None:
            unsupported.append(f"Unsupported QuickTime metadata assignment: {arg}")
        elif isinstance(parsed, QuickTimeMetadataDeleteGroup):
            delete_groups.append(parsed)
        else:
            values.append(parsed)
        index += 1
    return ParsedQuickTimeWriteArgs(
        plan=QuickTimeMetadataWritePlan(
            values=tuple(values),
            delete_groups=tuple(delete_groups),
            write_mode=write_mode,
        ),
        unsupported=tuple(unsupported),
    )


def parse_quicktime_metadata_assignment(
    spec: str,
    value: str,
) -> QuickTimeMetadataValue | QuickTimeMetadataDeleteGroup | None:
    parts = spec.split(":")
    if len(parts) == 1:
        return None
    group_text = normalize_quicktime_group(parts[0])
    if group_text is None:
        return None
    if len(parts) == 2 and parts[1].lower() == "all" and value == "":
        if group_text == "QuickTime":
            return None
        return QuickTimeMetadataDeleteGroup(group_text)
    if len(parts) == 3 and group_text == "ItemList" and parts[1].startswith("ID-"):
        tag_name, language_code = split_tag_language(parts[2])
        if quicktime_metadata_tag(group_text, tag_name) is None:
            return None
        return QuickTimeMetadataValue(
            group=group_text,
            name=tag_name,
            value=value if value != "" else None,
            language_code=language_code,
            atom_id_override=parts[1][3:],
        )
    if len(parts) != 2:
        return None
    tag_name, language_code = split_tag_language(parts[1])
    if group_text == "QuickTime":
        preferred_group = preferred_quicktime_metadata_group(tag_name)
        if preferred_group is None:
            return None
        group_text = preferred_group
    if quicktime_metadata_tag(group_text, tag_name) is None:
        return None
    return QuickTimeMetadataValue(
        group=group_text,
        name=tag_name,
        value=value if value != "" else None,
        language_code=language_code,
    )


def normalize_quicktime_group(group: str) -> QuickTimeMetadataGroup | Literal["QuickTime"] | None:
    group_lower = group.lower()
    if group_lower == "quicktime":
        return "QuickTime"
    if group_lower == "itemlist":
        return "ItemList"
    if group_lower == "userdata":
        return "UserData"
    if group_lower == "keys":
        return "Keys"
    if group_lower == "audiokeys":
        return "AudioKeys"
    if group_lower == "videokeys":
        return "VideoKeys"
    return None


def split_tag_language(tag: str) -> tuple[str, str | None]:
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


def encode_item_list_value_atom(
    value: str,
    language_code: str | None = None,
    value_format: QuickTimeItemListValueFormat = "utf8",
) -> bytes:
    country, language = pack_quicktime_language_country(language_code)
    flags, value_bytes = encode_item_list_value_bytes(value, value_format)
    data_payload = (
        flags.to_bytes(4, "big")
        + country.to_bytes(2, "big")
        + language.to_bytes(2, "big")
        + value_bytes
    )
    return encode_quicktime_atom(QT_DATA_ATOM, data_payload)


def encode_item_list_value_bytes(
    value: str,
    value_format: QuickTimeItemListValueFormat,
) -> tuple[int, bytes]:
    if value_format == "utf8":
        return QT_UTF8_DATA_FLAGS, value.encode("utf-8")
    if value_format == "int8s":
        return QT_SIGNED_INTEGER_DATA_FLAGS, int(value).to_bytes(1, "big", signed=True)
    if value_format == "int16s":
        return QT_SIGNED_INTEGER_DATA_FLAGS, int(value).to_bytes(2, "big", signed=True)
    if value_format == "int8u":
        return 0x16, int(value).to_bytes(1, "big", signed=False)
    if value_format == "int16u":
        return 0x16, int(value).to_bytes(2, "big", signed=False)
    if value_format == "int32s":
        return QT_SIGNED_INTEGER_DATA_FLAGS, int(value).to_bytes(4, "big", signed=True)
    if value_format == "int32u":
        return 0x16, int(value).to_bytes(4, "big", signed=False)
    if value_format == "int64s":
        return QT_SIGNED_INTEGER_DATA_FLAGS, int(value).to_bytes(8, "big", signed=True)
    if value_format == "int64u":
        return 0x16, int(value).to_bytes(8, "big", signed=False)
    if value_format == "float":
        return 0x17, struct.pack(">f", float(value))
    if value_format == "double":
        return 0x18, struct.pack(">d", float(value))
    if value_format == "genre_id":
        return QT_UNDEFINED_DATA_FLAGS, int(value).to_bytes(2, "big", signed=False)
    if value_format == "milliseconds_text":
        return QT_UTF8_DATA_FLAGS, str(int(float(value) * 1000)).encode("utf-8")
    if value_format == "gps_iso6709":
        return QT_UTF8_DATA_FLAGS, encode_iso6709_coordinates(value).encode("utf-8")
    if value_format == "track_number":
        return QT_UNDEFINED_DATA_FLAGS, encode_number_pair(value, trailing_zero=True)
    if value_format == "yes_no_int8s":
        encoded = item_list_lookup_or_int(value, YES_NO_INT8S_VALUES)
        return QT_SIGNED_INTEGER_DATA_FLAGS, encoded.to_bytes(1, "big", signed=True)
    if value_format == "play_gap":
        encoded = item_list_lookup_or_int(value, PLAY_GAP_VALUES)
        return QT_SIGNED_INTEGER_DATA_FLAGS, encoded.to_bytes(1, "big", signed=True)
    if value_format == "apple_store_account_type":
        encoded = item_list_lookup_or_int(value, APPLE_STORE_ACCOUNT_TYPE_VALUES)
        return QT_SIGNED_INTEGER_DATA_FLAGS, encoded.to_bytes(1, "big", signed=True)
    if value_format == "content_rating":
        encoded = item_list_lookup_or_int(value, CONTENT_RATING_VALUES)
        return QT_SIGNED_INTEGER_DATA_FLAGS, encoded.to_bytes(1, "big", signed=True)
    if value_format == "media_type":
        encoded = item_list_lookup_or_int(value, MEDIA_TYPE_VALUES)
        return QT_SIGNED_INTEGER_DATA_FLAGS, encoded.to_bytes(1, "big", signed=True)
    return QT_UNDEFINED_DATA_FLAGS, encode_number_pair(value, trailing_zero=False)


def item_list_lookup_or_int(value: str, lookup: dict[str, int]) -> int:
    normalized = " ".join(value.strip().lower().split())
    if normalized in lookup:
        return lookup[normalized]
    return int(value)


ISO6709_RE = re.compile(r"^([-+]\d+(?:\.\d*)?){2,3}(?:CRS[^/]*)?/?$")


def encode_iso6709_coordinates(value: str) -> str:
    text = value.strip()
    if ISO6709_RE.fullmatch(text):
        return text
    parts = tuple(part.strip() for part in re.split(r",\s*|\s+", text) if part.strip())
    if len(parts) not in {2, 3}:
        raise ValueError(f"Expected latitude/longitude[/altitude] for QuickTime GPS: {value!r}.")
    coordinates = tuple(float(part) for part in parts)
    latitude, longitude = coordinates[0], coordinates[1]
    if abs(latitude) > 90:
        raise ValueError(f"Latitude out of range for QuickTime GPS: {value!r}.")
    if abs(longitude) > 180:
        raise ValueError(f"Longitude out of range for QuickTime GPS: {value!r}.")
    encoded = f"{format_iso6709_number(latitude, 2)}{format_iso6709_number(longitude, 3)}"
    if len(coordinates) == 3:
        encoded += format_iso6709_altitude(coordinates[2])
    return encoded + "/"


def format_iso6709_number(value: float, integer_digits: int) -> str:
    sign = "+" if value >= 0 else "-"
    magnitude = abs(value)
    integer = int(magnitude)
    fraction_text = f"{magnitude:.5f}".split(".", 1)[1].rstrip("0")
    if len(fraction_text) < 3:
        fraction_text += "0" * (3 - len(fraction_text))
    return f"{sign}{integer:0{integer_digits}d}.{fraction_text}"


def format_iso6709_altitude(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    magnitude = abs(value)
    fraction_text = f"{magnitude:.5f}".rstrip("0").rstrip(".")
    if "." not in fraction_text:
        fraction_text += ".000"
    return sign + fraction_text


def encode_number_pair(value: str, *, trailing_zero: bool) -> bytes:
    numbers = integers_from_text(value)
    if not 1 <= len(numbers) <= 2:
        raise ValueError(f"Expected one or two integers in QuickTime ItemList value: {value!r}.")
    current = numbers[0]
    total = numbers[1] if len(numbers) == 2 else 0
    payload = b"\x00\x00" + current.to_bytes(2, "big") + total.to_bytes(2, "big")
    if trailing_zero:
        return payload + b"\x00\x00"
    return payload


def integers_from_text(value: str) -> tuple[int, ...]:
    numbers: list[int] = []
    digits = ""
    for char in value:
        if char.isdigit():
            digits += char
            continue
        if digits:
            numbers.append(int(digits))
            digits = ""
    if digits:
        numbers.append(int(digits))
    return tuple(numbers)


def parse_item_list_data_atoms(payload: bytes) -> tuple[QuickTimeDataAtom, ...]:
    parsed: list[QuickTimeDataAtom] = []
    for atom in read_quicktime_atoms(payload):
        if atom.atom_type != QT_DATA_ATOM or len(atom.payload) < 8:
            continue
        parsed.append(
            QuickTimeDataAtom(
                flags=int.from_bytes(atom.payload[0:4], "big"),
                country=int.from_bytes(atom.payload[4:6], "big"),
                language=int.from_bytes(atom.payload[6:8], "big"),
                value=atom.payload[8:],
            )
        )
    return tuple(parsed)


def data_atom_matches_language(data_atom: QuickTimeDataAtom, language_code: str | None) -> bool:
    country, language = pack_quicktime_language_country(language_code)
    return data_atom.country == country and data_atom.language == language


def encode_user_data_text_value(value: str, language_code: str | None = None) -> bytes:
    country, language = pack_quicktime_language_country(language_code)
    if country:
        raise ValueError("UserData international text atoms do not support country codes.")
    value_bytes = value.encode("utf-8")
    return len(value_bytes).to_bytes(2, "big") + language.to_bytes(2, "big") + value_bytes


def parse_user_data_text_value(payload: bytes) -> tuple[int, bytes] | None:
    if len(payload) < 4:
        return None
    value_length = int.from_bytes(payload[0:2], "big")
    language = int.from_bytes(payload[2:4], "big")
    if value_length > len(payload) - 4:
        return None
    return language, payload[4 : 4 + value_length]


def encode_handler_atom(handler_type: str) -> QuickTimeAtom:
    if len(handler_type) != 4:
        raise ValueError("QuickTime handler type must be four characters.")
    payload = b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00" + handler_type.encode("latin-1")
    return QuickTimeAtom(QT_HANDLER_ATOM, payload + b"\x00" * 12)


def encode_keys_payload(key_ids: tuple[str, ...]) -> bytes:
    entries = b"".join(encode_key_entry(key_id) for key_id in key_ids)
    return b"\x00\x00\x00\x00" + len(key_ids).to_bytes(4, "big") + entries


def encode_key_entry(key_id: str) -> bytes:
    stored_key_id = stored_quicktime_key_id(key_id)
    entry_payload = QT_METADATA_NAMESPACE.encode("latin-1") + stored_key_id.encode("utf-8")
    return (len(entry_payload) + 4).to_bytes(4, "big") + entry_payload


def parse_keys_payload(payload: bytes) -> tuple[str, ...]:
    if len(payload) < 8:
        return ()
    count = int.from_bytes(payload[4:8], "big")
    key_ids: list[str] = []
    pos = 8
    while pos + 8 <= len(payload) and len(key_ids) < count:
        entry_size = int.from_bytes(payload[pos : pos + 4], "big")
        if entry_size < 8 or pos + entry_size > len(payload):
            break
        namespace = payload[pos + 4 : pos + 8].decode("latin-1")
        stored = payload[pos + 8 : pos + entry_size].split(b"\x00", 1)[0].decode("utf-8")
        key_ids.append(exiftool_key_id_from_stored_key(namespace, stored))
        pos += entry_size
    return tuple(key_ids)


def stored_quicktime_key_id(key_id: str) -> str:
    prefix = key_id.split(".", 1)[0]
    if prefix in {"com", "xiaomi", "samsung"}:
        return key_id
    return f"com.apple.quicktime.{key_id}"


def exiftool_key_id_from_stored_key(namespace: str, stored: str) -> str:
    if namespace != QT_METADATA_NAMESPACE:
        return stored or f"Tag_{namespace}"
    if stored.startswith("com.apple.quicktime."):
        return stored.removeprefix("com.apple.quicktime.")
    if stored.startswith("com."):
        return stored
    return stored.removeprefix("com.")


def pack_quicktime_language_country(language_code: str | None) -> tuple[int, int]:
    if language_code is None:
        return QT_DEFAULT_COUNTRY, QT_DEFAULT_LANGUAGE
    normalized = language_code.replace("_", "-")
    pieces = normalized.split("-")
    if len(pieces) == 1:
        language_text = pieces[0]
        country_text = ""
    elif len(pieces) == 2:
        language_text, country_text = pieces
    else:
        raise ValueError(f"Invalid QuickTime language code: {language_code!r}.")
    language = 0
    if language_text and language_text.lower() != "und":
        if len(language_text) != 3 or not language_text.isalpha():
            raise ValueError(f"Invalid QuickTime language code: {language_code!r}.")
        for char in language_text.lower():
            language = (language << 5) | (ord(char) - 0x60)
    country = 0
    if country_text and country_text.upper() != "ZZ":
        if len(country_text) != 2 or not country_text.isalpha():
            raise ValueError(f"Invalid QuickTime country code: {language_code!r}.")
        country = int.from_bytes(country_text.upper().encode("latin-1"), "big")
    return country, language


def unpack_quicktime_language(language: int) -> str | None:
    if language == 0:
        return None
    chars = "".join(chr(((language >> shift) & 0x1F) + 0x60) for shift in (10, 5, 0))
    if chars in {"und", "eng"}:
        return None
    if chars.isalpha():
        return chars
    return "err"


def atom_type_from_key_index(index: int) -> str:
    return index.to_bytes(4, "big").decode("latin-1")


def key_index_from_atom_type(atom_type: str) -> int:
    return int.from_bytes(atom_type.encode("latin-1"), "big")
