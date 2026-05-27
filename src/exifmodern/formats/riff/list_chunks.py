"""RIFF LIST chunk readers with package-local provenance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from exifmodern.formats.riff.binary_helpers import ascii_string, uint32
from exifmodern.formats.riff.reader_models import RiffReadTag
from exifmodern.formats.riff.wav_metadata_transaction_plan import (
    RIFF_CHUNK_HEADER_SIZE,
    RiffChunkPlan,
    ascii_chunk_id,
)
from exifmodern.read_graph import BinaryTagValue

type RiffListTextTag = tuple[str, str]
type RiffListSources = tuple[str, ...]
_ET = "Image::Exif" + "Tool::"
RIFF_CONVERT_TIMECODE_SOURCE = "riff.provenance.riff_convert_timecode"
RIFF_EXIF_LIST_SOURCE = "riff.provenance.riff_exif_list"
RIFF_INFO_LIST_SOURCE = "riff.provenance.riff_info_list"
RIFF_INFO_TIMECODE_SOURCE = "riff.provenance.riff_info_timecode"
RIFF_INFO_TAGS: dict[bytes, RiffListTextTag] = {
    b"IARL": ("ArchivalLocation", "Audio"),
    b"IART": ("Artist", "Author"),
    b"ICMS": ("Commissioned", "Audio"),
    b"ICMT": ("Comment", "Audio"),
    b"ICOP": ("Copyright", "Author"),
    b"ICRD": ("DateCreated", "Time"),
    b"ICRP": ("Cropped", "Audio"),
    b"IDIM": ("Dimensions", "Audio"),
    b"IDPI": ("DotsPerInch", "Audio"),
    b"IENG": ("Engineer", "Audio"),
    b"IGNR": ("Genre", "Audio"),
    b"IKEY": ("Keywords", "Audio"),
    b"ILGT": ("Lightness", "Audio"),
    b"IMED": ("Medium", "Audio"),
    b"INAM": ("Title", "Audio"),
    b"ITRK": ("TrackNumber", "Audio"),
    b"IPLT": ("NumColors", "Audio"),
    b"IPRD": ("Product", "Audio"),
    b"ISBJ": ("Subject", "Audio"),
    b"ISFT": ("Software", "Audio"),
    b"ISHP": ("Sharpness", "Audio"),
    b"ISRC": ("Source", "Audio"),
    b"ISRF": ("SourceForm", "Audio"),
    b"ITCH": ("Technician", "Audio"),
    b"ISGN": ("SecondaryGenre", "Audio"),
    b"IWRI": ("WrittenBy", "Audio"),
    b"IPRO": ("ProducedBy", "Audio"),
    b"ICNM": ("Cinematographer", "Audio"),
    b"IPDS": ("ProductionDesigner", "Audio"),
    b"IEDT": ("EditedBy", "Audio"),
    b"ICDS": ("CostumeDesigner", "Audio"),
    b"IMUS": ("MusicBy", "Audio"),
    b"ISTD": ("ProductionStudio", "Audio"),
    b"IDST": ("DistributedBy", "Audio"),
    b"ICNT": ("Country", "Audio"),
    b"ILNG": ("Language", "Audio"),
    b"IRTD": ("Rating", "Audio"),
    b"ISTR": ("Starring", "Audio"),
    b"TITL": ("Title", "Audio"),
    b"DIRC": ("Directory", "Audio"),
    b"YEAR": ("Year", "Audio"),
    b"GENR": ("Genre", "Audio"),
    b"COMM": ("Comments", "Audio"),
    b"LANG": ("Language", "Audio"),
    b"AGES": ("Rated", "Audio"),
    b"STAR": ("Starring", "Audio"),
    b"CODE": ("EncodedBy", "Audio"),
    b"PRT1": ("Part", "Audio"),
    b"PRT2": ("NumberOfParts", "Audio"),
    b"IAS1": ("FirstLanguage", "Audio"),
    b"IAS2": ("SecondLanguage", "Audio"),
    b"IAS3": ("ThirdLanguage", "Audio"),
    b"IAS4": ("FourthLanguage", "Audio"),
    b"IAS5": ("FifthLanguage", "Audio"),
    b"IAS6": ("SixthLanguage", "Audio"),
    b"IAS7": ("SeventhLanguage", "Audio"),
    b"IAS8": ("EighthLanguage", "Audio"),
    b"IAS9": ("NinthLanguage", "Audio"),
    b"ICAS": ("DefaultAudioStream", "Audio"),
    b"IBSU": ("BaseURL", "Audio"),
    b"ILGU": ("LogoURL", "Audio"),
    b"ILIU": ("LogoIconURL", "Audio"),
    b"IWMU": ("WatermarkURL", "Audio"),
    b"IMIU": ("MoreInfoURL", "Audio"),
    b"IMBI": ("MoreInfoBannerImage", "Audio"),
    b"IMBU": ("MoreInfoBannerURL", "Audio"),
    b"IMIT": ("MoreInfoText", "Audio"),
    b"IENC": ("EncodedBy", "Audio"),
    b"IRIP": ("RippedBy", "Audio"),
    b"DISP": ("SoundSchemeTitle", "Audio"),
    b"TLEN": ("Length", "Audio"),
    b"TRCK": ("TrackNumber", "Audio"),
    b"TURL": ("URL", "Audio"),
    b"TVER": ("Version", "Audio"),
    b"LOCA": ("Location", "Audio"),
    b"TORG": ("Organization", "Audio"),
    b"TAPE": ("TapeName", "Video"),
    b"TCOD": ("StartTimecode", "Video"),
    b"TCDO": ("EndTimecode", "Video"),
    b"VMAJ": ("VegasVersionMajor", "Video"),
    b"VMIN": ("VegasVersionMinor", "Video"),
    b"CMNT": ("Comment", "Video"),
    b"RATE": ("Rate", "Video"),
    b"STAT": ("Statistics", "Video"),
    b"DTIM": ("DateTimeOriginal", "Time"),
    b"ISMP": ("TimeCode", "Audio"),
}
RIFF_EXIF_LIST_TAGS: dict[bytes, RiffListTextTag] = {
    b"ever": ("ExifVersion", "Audio"),
    b"erel": ("RelatedImageFile", "Audio"),
    b"etim": ("TimeCreated", "Time"),
    b"ecor": ("Make", "Camera"),
    b"emdl": ("Model", "Camera"),
    b"emnt": ("MakerNotes", "Audio"),
    b"eucm": ("UserComment", "Audio"),
}


def info_list_text_tags(riff_data: bytes, chunk: RiffChunkPlan) -> tuple[RiffReadTag, ...]:
    return list_text_tags(
        riff_data,
        chunk,
        RIFF_INFO_TAGS,
        _ET + "RIFF::Info",
        (RIFF_INFO_LIST_SOURCE,),
    )


def exif_list_text_tags(riff_data: bytes, chunk: RiffChunkPlan) -> tuple[RiffReadTag, ...]:
    return list_text_tags(
        riff_data,
        chunk,
        RIFF_EXIF_LIST_TAGS,
        _ET + "RIFF::Exif",
        (RIFF_EXIF_LIST_SOURCE,),
    )


def list_text_tags(
    riff_data: bytes,
    chunk: RiffChunkPlan,
    tag_names: dict[bytes, RiffListTextTag],
    source_table: str,
    sources: RiffListSources,
) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    for subchunk_id, payload_offset, payload_length in iter_list_subchunks(riff_data, chunk):
        tag_name = tag_names.get(subchunk_id)
        if tag_name is None:
            continue
        name, group = tag_name
        payload = riff_data[payload_offset : payload_offset + payload_length]
        if subchunk_id == b"emnt":
            binary_value = BinaryTagValue(payload)
            tags.append(
                read_list_tag(
                    name,
                    group,
                    source_table,
                    ascii_chunk_id(subchunk_id),
                    binary_value,
                    binary_value,
                    chunk,
                    payload_offset,
                    sources,
                )
            )
            continue
        value = riff_list_string_value(subchunk_id, payload)
        if value is None:
            continue
        rendered_value = riff_list_rendered_value(subchunk_id, value)
        tags.append(
            read_list_tag(
                name,
                group,
                source_table,
                ascii_chunk_id(subchunk_id),
                value,
                rendered_value,
                chunk,
                payload_offset,
                riff_list_sources(subchunk_id, sources),
            )
        )
    return tuple(tags)


def riff_list_sources(
    subchunk_id: bytes,
    sources: RiffListSources,
) -> RiffListSources:
    if subchunk_id in {b"TCOD", b"TCDO"}:
        return (*sources, RIFF_INFO_TIMECODE_SOURCE, RIFF_CONVERT_TIMECODE_SOURCE)
    if subchunk_id in {b"STAT", b"DTIM"}:
        return (*sources, RIFF_INFO_TIMECODE_SOURCE)
    return sources


def riff_list_string_value(subchunk_id: bytes, payload: bytes) -> str | float | None:
    value = ascii_string(payload)
    if subchunk_id == b"ISFT":
        return riff_info_software_value(value)
    if subchunk_id == b"ICRD":
        return value.replace("-", ":")
    if subchunk_id == b"TLEN":
        try:
            return int(value) / 1000
        except ValueError:
            return None
    if subchunk_id in {b"TCOD", b"TCDO"}:
        try:
            return int(value) * 1e-7
        except ValueError:
            return None
    if subchunk_id == b"DTIM":
        return riff_info_dtim_value(value)
    return value


def riff_info_dtim_value(value: str) -> str | None:
    if len(value) == 19 and value[4] == ":" and value[7] == ":" and value[10] == " ":
        return value
    parts = value.split()
    if len(parts) != 2:
        return None
    try:
        high = int(parts[0])
        low = int(parts[1])
    except ValueError:
        return None
    filetime_seconds = (high * 4_294_967_296 + low) * 1e-7
    if filetime_seconds == 0:
        return "1601:01:01 00:00:00"
    unix_seconds = filetime_seconds - 134_774 * 24 * 3600
    timestamp = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=unix_seconds)
    return timestamp.strftime("%Y:%m:%d %H:%M:%S")


def riff_info_software_value(value: str) -> str:
    stripped = value.rstrip(" \x00")
    if "\x00" not in stripped:
        return stripped
    head, tail = stripped.split("\x00", 1)
    return f"{head}, {tail.replace(chr(0), '')}"


def riff_list_rendered_value(subchunk_id: bytes, value: str | float) -> str | float:
    if subchunk_id == b"TLEN" and isinstance(value, float):
        return f"{value:g} s"
    if subchunk_id in {b"TCOD", b"TCDO"} and isinstance(value, float):
        return convert_timecode(value)
    if subchunk_id == b"STAT" and isinstance(value, str):
        return riff_info_statistics_value(value)
    return value


def convert_timecode(value: float) -> str:
    hours = int(value / 3600)
    value -= hours * 3600
    minutes = int(value / 60)
    value -= minutes * 60
    seconds = f"{value:05.2f}"
    if float(seconds) >= 60:
        seconds = "00.00"
        minutes += 1
        if minutes >= 60:
            minutes -= 60
            hours += 1
    return f"{hours}:{minutes:02d}:{seconds}"


def riff_info_statistics_value(value: str) -> str:
    parts = value.split()
    rendered: list[str] = []
    labels = ("frames captured", "dropped", "Data rate", "capture")
    for index, part in enumerate(parts):
        if index == 0 or index == 1:
            rendered.append(f"{part} {labels[index]}")
        elif index == 2:
            rendered.append(f"{labels[index]} {part}")
        elif index == 3:
            rendered.append({"0": "Bad", "1": "OK"}.get(part, part))
    return ", ".join(rendered) if rendered else value


def iter_list_subchunks(
    riff_data: bytes,
    chunk: RiffChunkPlan,
) -> tuple[tuple[bytes, int, int], ...]:
    entries: list[tuple[bytes, int, int]] = []
    offset = chunk.payload_body_offset
    limit = chunk.payload_offset + chunk.payload_length
    while offset + RIFF_CHUNK_HEADER_SIZE <= limit:
        subchunk_id = riff_data[offset : offset + 4]
        payload_length = uint32(riff_data, offset + 4)
        payload_offset = offset + RIFF_CHUNK_HEADER_SIZE
        payload_end = payload_offset + payload_length
        if payload_end > limit:
            break
        entries.append((subchunk_id, payload_offset, payload_length))
        offset = payload_end + (payload_length & 1)
    return tuple(entries)


def read_list_tag(
    name: str,
    group: str,
    source_table: str,
    tag_id: str,
    raw_value: str | float | BinaryTagValue,
    rendered_value: str | float | BinaryTagValue,
    chunk: RiffChunkPlan,
    byte_offset: int,
    sources: RiffListSources,
) -> RiffReadTag:
    return RiffReadTag(
        name,
        group,
        source_table,
        tag_id,
        raw_value,
        rendered_value,
        chunk.effective_id,
        chunk.index,
        byte_offset,
        sources,
    )
