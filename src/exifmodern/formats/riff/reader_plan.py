"""Source-backed RIFF/WAV/AVI/WebP scalar reader plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from exifmodern.formats.riff.binary_helpers import (
    ascii_string,
    broadcast_umid,
    fixed_string,
    float_le,
    int32,
    signed_int8,
    uint16,
    uint32,
    uint64,
)
from exifmodern.formats.riff.list_chunks import (
    exif_list_text_tags,
    info_list_text_tags,
    iter_list_subchunks,
)
from exifmodern.formats.riff.quicktime_stream_reader import quicktime_stream_route_and_tags
from exifmodern.formats.riff.reader_models import (
    RiffNestedMetadataRoute,
    RiffNestedRouteStatus,
    RiffReaderPlan,
    RiffReaderStatus,
    RiffReadTag,
    RiffRenderedValue,
    RiffTagValue,
    riff_rendered_value_from_tag_value,
    riff_tag_value_from_json,
)
from exifmodern.formats.riff.wav_metadata_transaction_plan import (
    RIFF_CHUNK_HEADER_SIZE,
    RiffChunkPlan,
    RiffEmissionGate,
    RiffSignatureValidationPlan,
    ascii_chunk_id,
    enumerate_riff_chunks,
    unique_gates,
    unique_sources,
    validate_riff_signature,
)
from exifmodern.formats.riff.webp_chunks import webp_chunk_tags
from exifmodern.formats.riff.webp_constants import VP8_CHUNK_ID, VP8L_CHUNK_ID, VP8X_CHUNK_ID
from exifmodern.formats.tiff.primitives import (
    parse_tiff_header,
    read_exif_ifd_values,
    read_gps_ifd_values,
    read_ifd0_values,
)
from exifmodern.json_types import JsonArray, JsonObject, JsonValue
from exifmodern.read_graph import BinaryTagValue

__all__ = [
    "RiffNestedMetadataRoute",
    "RiffNestedRouteStatus",
    "RiffReadTag",
    "RiffReaderPlan",
    "RiffReaderStatus",
    "RiffRenderedValue",
    "RiffTagValue",
    "build_riff_reader_plan",
]

RIFF_HEADER_READER_SOURCE = "riff.reader.riff_header_reader"
RIFF_TOP_LEVEL_CHUNK_SOURCE = "riff.reader.riff_top_level_chunk"
RIFF_DATE_SOURCE = "riff.reader.riff_date"
RIFF_AUDIO_FORMAT_SOURCE = "riff.reader.riff_audio_format"
RIFF_BROADCAST_EXT_SOURCE = "riff.reader.riff_broadcast_ext"
RIFF_DS64_SOURCE = "riff.reader.riff_ds64"
RIFF_FACT_SOURCE = "riff.reader.riff_fact"
RIFF_SAMPLER_SOURCE = "riff.reader.riff_sampler"
RIFF_INSTRUMENT_SOURCE = "riff.reader.riff_instrument"
RIFF_CSET_SOURCE = "riff.reader.riff_cset"
RIFF_AVI_HEADER_SOURCE = "riff.reader.riff_avi_header"
RIFF_BMP_FORMAT_SOURCE = "riff.reader.riff_bmp_format"
RIFF_STREAM_HEADER_SOURCE = "riff.reader.riff_stream_header"
RIFF_TDAT_LIST_SOURCE = "riff.reader.riff_tdat_list"
RIFF_TDAT_TABLE_SOURCE = "riff.reader.riff_tdat_table"
RIFF_OPEN_DML_SOURCE = "riff.reader.riff_open_dml"
RIFF_COMPOSITE_SOURCE = "riff.reader.riff_composite"
EXIF_DATETIME_ORIGINAL_COMPOSITE_SOURCE = "riff.reader.exif_datetime_original_composite"
RIFF_CALC_DURATION_SOURCE = "riff.reader.riff_calc_duration"
RIFF_EXIF_BYTE_ORDER_SOURCE = "riff.reader.riff_exif_byte_order"
RIFF_NESTED_METADATA_SOURCE = "riff.reader.riff_nested_metadata"
RIFF_BINARY_CHUNK_SOURCE = "riff.reader.riff_binary_chunk"
RIFF_ACIDIZER_SOURCE = "riff.reader.riff_acidizer"
RIFF_ASSOCIATED_DATA_LIST_SOURCE = "riff.reader.riff_associated_data_list"
RIFF_PROPRIETARY_AVI_LIST_SOURCE = "riff.reader.riff_proprietary_avi_list"
NIKON_AVI_ROUTE_SOURCE = "riff.reader.nikon_avi_route"
NIKON_AVI_TAGS_SOURCE = "riff.reader.nikon_avi_tags"
NIKON_AVI_PROCESS_SOURCE = "riff.reader.nikon_avi_process"
PENTAX_AVI_ROUTE_SOURCE = "riff.reader.pentax_avi_route"
RIFF_JUNK_ROUTE_SOURCE = "riff.reader.riff_junk_route"
PENTAX_JUNK_SOURCE = "riff.reader.pentax_junk"
PENTAX_JUNK2_SOURCE = "riff.reader.pentax_junk2"
OLYMPUS_AVI_JUNK_SOURCE = "riff.reader.olympus_avi_junk"
CASIO_JUNK_EXIF_SOURCE = "riff.reader.casio_junk_exif"
RICOH_AVI_JUNK_SOURCE = "riff.reader.ricoh_avi_junk"
LUCAS_JUNK_SOURCE = "riff.reader.lucas_junk"
QUICKTIME_STREAM_SOURCE = "riff.reader.quicktime_stream"
RIFF_C2PA_JUMBF_SOURCE = "riff.reader.riff_c2pa_jumbf"
RIFF_MIME_TYPES: dict[str, str] = {
    "WAV": "audio/x-wav",
    "AVI": "video/x-msvideo",
    "WEBP": "image/webp",
}
RIFF_FILE_TYPE_EXTENSIONS: dict[str, str] = {
    "AVI": "avi",
    "LA": "la",
    "OFR": "ofr",
    "PAC": "pac",
    "WAV": "wav",
    "WEBP": "webp",
    "WV": "wv",
}
RIFF_FORM_FILE_TYPES: dict[bytes, str] = {
    b"WAVE": "WAV",
    b"AVI ": "AVI",
    b"WEBP": "WEBP",
    b"LA02": "LA",
    b"LA03": "LA",
    b"LA04": "LA",
    b"OFR ": "OFR",
    b"LPAC": "PAC",
    b"wvpk": "WV",
}
AUDIO_ENCODING_DESCRIPTIONS: dict[int, str] = {
    0x01: "Microsoft PCM",
    0x03: "Microsoft IEEE float",
    0x55: "MP3",
    0xFF: "AAC",
    0xFFFE: "Extensible",
}
STREAM_TYPE_DESCRIPTIONS: dict[str, str] = {
    "auds": "Audio",
    "mids": "MIDI",
    "txts": "Text",
    "vids": "Video",
    "iavs": "Interleaved Audio+Video",
}
ACIDIZER_FLAG_DESCRIPTIONS: tuple[tuple[int, str], ...] = (
    (0x01, "One shot"),
    (0x02, "Root note set"),
    (0x04, "Stretch"),
    (0x08, "Disk-based"),
    (0x10, "High octave"),
)
ACIDIZER_ROOT_NOTE_DESCRIPTIONS: dict[int, str] = {
    0x30: "C",
    0x31: "C#",
    0x32: "D",
    0x33: "D#",
    0x34: "E",
    0x35: "F",
    0x36: "F#",
    0x37: "G",
    0x38: "G#",
    0x39: "A",
    0x3A: "A#",
    0x3B: "B",
    0x3C: "High C",
    0x3D: "High C#",
    0x3E: "High D",
    0x3F: "High D#",
    0x40: "High E",
    0x41: "High F",
    0x42: "High F#",
    0x43: "High G",
    0x44: "High G#",
    0x45: "High A",
    0x46: "High A#",
    0x47: "High B",
}
EXIF_TAG_IDS: dict[str, str] = {
    "ImageDescription": "0x010E",
    "Make": "0x010F",
    "Model": "0x0110",
    "Orientation": "0x0112",
    "XResolution": "0x011A",
    "YResolution": "0x011B",
    "ResolutionUnit": "0x0128",
    "Software": "0x0131",
    "ModifyDate": "0x0132",
    "Artist": "0x013B",
    "Copyright": "0x8298",
    "YCbCrPositioning": "0x0213",
    "ExifIFDPointer": "0x8769",
    "GPSInfoIFDPointer": "0x8825",
    "ISO": "0x8827",
    "DateTimeOriginal": "0x9003",
    "CreateDate": "0x9004",
    "UserComment": "0x9286",
    "ExifImageWidth": "0xA002",
    "ExifImageHeight": "0xA003",
    "GPSLatitudeRef": "0x0001",
    "GPSLatitude": "0x0002",
    "GPSLongitudeRef": "0x0003",
    "GPSLongitude": "0x0004",
    "GPSAltitudeRef": "0x0005",
    "GPSAltitude": "0x0006",
}
RIFF_XMP_CHUNKS = {"_PMX", "XMP ", "XMP\x00"}
XMP_GROUP_SOURCE_TABLES: dict[str, str] = {
    "XMP-dc": "Image::ExifTool::XMP::dc",
    "XMP-x": "Image::ExifTool::XMP::x",
    "XMP-xmp": "Image::ExifTool::XMP::xmp",
    "XMP-xmpDM": "Image::ExifTool::XMP::xmpDM",
}
XMP_TAG_IDS: dict[str, str] = {
    "Creator": "creator",
    "MetadataDate": "MetadataDate",
    "XMPToolkit": "xmptk",
}
PENTAX_AVI_ROUTE_SOURCES = (
    RIFF_NESTED_METADATA_SOURCE,
    RIFF_PROPRIETARY_AVI_LIST_SOURCE,
    PENTAX_AVI_ROUTE_SOURCE,
)
PENTAX_AVI_TABLE = "Image::ExifTool::Pentax::AVI"
PENTAX_AVI_MAKERNOTE_TABLE = "Image::ExifTool::Pentax::Main"
PENTAX_AVI_MAKERNOTE_START = 10
PENTAX_AVI_MAKERNOTE_BYTE_ORDER = "Unknown"
PENTAX_AVI_MAKERNOTE_SUBCHUNKS = {b"hymn", b"mknt"}
PENTAX_JUNK_TABLE = "Image::ExifTool::Pentax::Junk"
PENTAX_JUNK2_TABLE = "Image::ExifTool::Pentax::Junk2"
OLYMPUS_AVI_JUNK_TABLE = "Image::ExifTool::Olympus::AVI"
CASIO_JUNK_EXIF_TABLE = "Image::ExifTool::Exif::Main"
RICOH_AVI_JUNK_TABLE = "Image::ExifTool::Ricoh::AVI"
LUCAS_JUNK_TABLE = "Image::ExifTool::QuickTime::Stream"
PENTAX_JUNK_RS1000_PREFIX = b"IIII\x01\x00"
PENTAX_JUNK2_RZ18_PREFIX = b"PENTDigital Camera"
RIFF_JUMBF_TAG_IDS: dict[str, str] = {
    "JUMDType": "type",
    "JUMDLabel": "label",
}
RIFF_JUMBF_JSON_TAG_IDS: dict[str, str] = {
    "Title": "Title",
    "Location": "Location",
    "Copyright": "Copyright",
}
type RiffBinaryChunkTag = tuple[str, str]
RIFF_BINARY_CHUNK_TAGS: dict[bytes, RiffBinaryChunkTag] = {
    b"JUNQ": ("OldXMP", "RIFF"),
    b"cue ": ("CuePoints", "RIFF"),
    b"plst": ("Playlist", "RIFF"),
}
RIFF_ASSOCIATED_DATA_TAGS: dict[bytes, str] = {
    b"labl": "CuePointLabel",
    b"note": "CuePointNote",
    b"ltxt": "LabeledText",
}
NIKON_AVI_ROUTE_SOURCES = (
    RIFF_NESTED_METADATA_SOURCE,
    RIFF_PROPRIETARY_AVI_LIST_SOURCE,
    NIKON_AVI_ROUTE_SOURCE,
    NIKON_AVI_TAGS_SOURCE,
    NIKON_AVI_PROCESS_SOURCE,
)
NIKON_AVI_TABLE_SOURCES = (NIKON_AVI_ROUTE_SOURCE, NIKON_AVI_TAGS_SOURCE, NIKON_AVI_PROCESS_SOURCE)
NIKON_AVI_TAG_TABLE = "Image::ExifTool::Nikon::AVITags"
NIKON_AVI_VERSION_TABLE = "Image::ExifTool::Nikon::AVIVers"
NikonAVIFormat = Literal[
    "string",
    "undef",
    "int8u",
    "int16u",
    "int32s",
    "rational64u",
    "rational64s",
]


@dataclass(frozen=True)
class NikonAVIRecordDef:
    name: str
    format: NikonAVIFormat
    group: str = "Camera"
    hidden_unknown: bool = False
    null_strip: bool = False
    value_conv: str | None = None
    print_conv: str | None = None


NIKON_AVI_VERS_RECORDS: dict[int, NikonAVIRecordDef] = {
    0x01: NikonAVIRecordDef("MakerNoteType", "string", "Video"),
    0x02: NikonAVIRecordDef("MakerNoteVersion", "int8u", "Video", value_conv="reverse_dot"),
}
NIKON_AVI_TAG_RECORDS: dict[int, NikonAVIRecordDef] = {
    0x03: NikonAVIRecordDef("Make", "string"),
    0x04: NikonAVIRecordDef("Model", "string"),
    0x05: NikonAVIRecordDef("Software", "undef", null_strip=True),
    0x06: NikonAVIRecordDef("Equipment", "string"),
    0x07: NikonAVIRecordDef("Orientation", "int16u", "Image", print_conv="orientation"),
    0x08: NikonAVIRecordDef("ExposureTime", "rational64u", "Image", print_conv="exposure_time"),
    0x09: NikonAVIRecordDef("FNumber", "rational64u", "Image", print_conv="one_decimal"),
    0x0A: NikonAVIRecordDef("ExposureCompensation", "rational64s", "Image", print_conv="fraction"),
    0x0B: NikonAVIRecordDef(
        "MaxApertureValue", "rational64u", value_conv="apex_aperture", print_conv="one_decimal"
    ),
    0x0C: NikonAVIRecordDef("MeteringMode", "int16u", print_conv="metering_mode"),
    0x0D: NikonAVIRecordDef("Nikon_AVITags_0x000d", "int16u", hidden_unknown=True),
    0x0E: NikonAVIRecordDef("Nikon_AVITags_0x000e", "int16u", hidden_unknown=True),
    0x0F: NikonAVIRecordDef("FocalLength", "rational64u", print_conv="focal_length"),
    0x10: NikonAVIRecordDef("XResolution", "rational64u", "Image"),
    0x11: NikonAVIRecordDef("YResolution", "rational64u", "Image"),
    0x12: NikonAVIRecordDef("ResolutionUnit", "int16u", "Image", print_conv="resolution_unit"),
    0x13: NikonAVIRecordDef("DateTimeOriginal", "string", "Time", print_conv="datetime"),
    0x14: NikonAVIRecordDef("CreateDate", "string", "Time", print_conv="datetime"),
    0x15: NikonAVIRecordDef("Nikon_AVITags_0x0015", "int16u", hidden_unknown=True),
    0x16: NikonAVIRecordDef("Duration", "rational64u", print_conv="seconds"),
    0x17: NikonAVIRecordDef("Nikon_AVITags_0x0017", "int16u", hidden_unknown=True),
    0x18: NikonAVIRecordDef("FocusMode", "string"),
    0x19: NikonAVIRecordDef("Nikon_AVITags_0x0019", "int32s", hidden_unknown=True),
    0x1B: NikonAVIRecordDef("DigitalZoom", "rational64u"),
    0x1C: NikonAVIRecordDef("Nikon_AVITags_0x001c", "rational64u", hidden_unknown=True),
    0x1D: NikonAVIRecordDef("ColorMode", "string"),
    0x1E: NikonAVIRecordDef("Sharpness", "string"),
    0x1F: NikonAVIRecordDef("WhiteBalance", "string"),
    0x20: NikonAVIRecordDef("NoiseReduction", "string"),
    0x801A: NikonAVIRecordDef("Nikon_AVITags_0x801a", "int32s", hidden_unknown=True),
}


def build_riff_reader_plan(
    riff_data: bytes,
    *,
    extract_embedded_level: int = 0,
    include_hidden_unknowns: bool = False,
) -> RiffReaderPlan:
    validation = validate_riff_signature(riff_data)
    gates: list[RiffEmissionGate] = []
    if validation.reason in {
        "truncated_riff_header",
        "unsupported_riff_signature",
        "unsupported_riff_form_type",
    }:
        gates.append(
            RiffEmissionGate(
                validation.reason,
                "RIFF header is not a supported reader input.",
                validation.evidence_ids,
            )
        )
        return reader_plan("unsupported", validation, (), (), (), gates)

    chunks, chunk_gates = enumerate_riff_chunks(riff_data)
    gates.extend(chunk_gates)
    tags: list[RiffReadTag] = []
    nested_routes: list[RiffNestedMetadataRoute] = []
    tags.extend(header_tags(validation))
    for chunk in chunks:
        payload = riff_data[chunk.payload_offset : chunk.payload_offset + chunk.payload_length]
        tags.extend(chunk_tags(riff_data, chunk, payload))
        route, nested_tags = nested_metadata_route_and_tags(
            riff_data,
            chunk,
            payload,
            extract_embedded_level=extract_embedded_level,
            include_hidden_unknowns=include_hidden_unknowns,
        )
        if route is not None:
            nested_routes.append(route)
            tags.extend(nested_tags)
    tags.extend(composite_tags(riff_data, tuple(chunks), tuple(tags)))
    return reader_plan(
        "unsupported" if gates else "planned",
        validation,
        chunks,
        tuple(nested_routes),
        tuple(tags),
        gates,
    )


def reader_plan(
    status: RiffReaderStatus,
    validation: RiffSignatureValidationPlan,
    chunks: tuple[RiffChunkPlan, ...],
    nested_routes: tuple[RiffNestedMetadataRoute, ...],
    tags: tuple[RiffReadTag, ...],
    gates: list[RiffEmissionGate],
) -> RiffReaderPlan:
    unique_gate_tuple = unique_gates(tuple(gates))
    return RiffReaderPlan(
        status=status,
        signature_validation=validation,
        chunks=chunks,
        nested_metadata_routes=nested_routes,
        tags=tags,
        output_emission_gates=unique_gate_tuple,
        evidence_ids=unique_sources(
            (
                RIFF_HEADER_READER_SOURCE,
                RIFF_TOP_LEVEL_CHUNK_SOURCE,
                *validation.evidence_ids,
                *(source for chunk in chunks for source in chunk.evidence_ids),
                *(source for route in nested_routes for source in route.evidence_ids),
                *(source for tag in tags for source in tag.evidence_ids),
                *(source for gate in unique_gate_tuple for source in gate.evidence_ids),
            )
        ),
    )


def header_tags(validation: RiffSignatureValidationPlan) -> tuple[RiffReadTag, ...]:
    file_type = RIFF_FORM_FILE_TYPES.get(validation.form_type, validation.family)
    if validation.is_rf64 and file_type != "unknown":
        file_type = f"{file_type} (RF64)"
    tags = [
        read_tag(
            "FileType",
            "File",
            "Image::ExifTool::RIFF::Main",
            "RIFF.FormType",
            validation.family,
            file_type,
            "RIFF",
            None,
            8,
            (RIFF_HEADER_READER_SOURCE,),
        )
    ]
    mime = RIFF_MIME_TYPES.get(validation.family)
    if mime is not None:
        tags.append(
            read_tag(
                "MIMEType",
                "File",
                "Image::ExifTool::RIFF::Main",
                "RIFF.MIMEType",
                validation.family,
                mime,
                "RIFF",
                None,
                8,
                (RIFF_HEADER_READER_SOURCE,),
            )
        )
    extension = RIFF_FILE_TYPE_EXTENSIONS.get(validation.family)
    if extension is not None:
        tags.append(
            read_tag(
                "FileTypeExtension",
                "File",
                "Image::ExifTool::RIFF::Main",
                "RIFF.FileTypeExtension",
                validation.family,
                extension,
                "RIFF",
                None,
                8,
                (RIFF_HEADER_READER_SOURCE,),
            )
        )
    return tuple(tags)


def chunk_tags(riff_data: bytes, chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    if chunk.chunk_id in RIFF_BINARY_CHUNK_TAGS:
        padded_payload = riff_data[chunk.payload_offset : chunk.padded_end_offset]
        return binary_chunk_tags(chunk, padded_payload)
    if chunk.chunk_id == b"IDIT":
        return riff_idit_tags(chunk, payload)
    if chunk.effective_id == "fmt ":
        return audio_format_tags(chunk, payload)
    if chunk.effective_id == "bext":
        return broadcast_extension_tags(chunk, payload)
    if chunk.effective_id == "ds64":
        return ds64_tags(chunk, payload)
    if chunk.effective_id == "fact":
        return fact_tags(chunk, payload)
    if chunk.effective_id == "smpl":
        return sampler_tags(chunk, payload)
    if chunk.effective_id == "inst":
        return instrument_tags(chunk, payload)
    if chunk.effective_id == "CSET":
        return cset_tags(chunk, payload)
    if chunk.effective_id == "acid":
        return acidizer_tags(chunk, payload)
    if chunk.effective_id in {"LIST_INFO", "LIST_INF0"}:
        return info_list_text_tags(riff_data, chunk)
    if chunk.effective_id == "LIST_exif":
        return exif_list_text_tags(riff_data, chunk)
    if chunk.effective_id == "LIST_hdrl":
        return hdrl_tags(riff_data, chunk)
    if chunk.chunk_id in {VP8_CHUNK_ID, VP8L_CHUNK_ID, VP8X_CHUNK_ID, b"ANIM", b"ANMF", b"ALPH"}:
        return webp_chunk_tags(chunk, payload)
    return ()


def binary_chunk_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    tag = RIFF_BINARY_CHUNK_TAGS.get(chunk.chunk_id)
    if tag is None:
        return ()
    name, group = tag
    return (
        chunk_read_tag(
            name,
            group,
            "Image::ExifTool::RIFF::Main",
            ascii_chunk_id(chunk.chunk_id),
            payload,
            payload,
            chunk,
            0,
            (RIFF_TOP_LEVEL_CHUNK_SOURCE, RIFF_BINARY_CHUNK_SOURCE),
        ),
    )


def riff_idit_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    return (
        idit_read_tag(
            payload,
            "IDIT",
            chunk.index,
            chunk.payload_offset,
            (RIFF_TOP_LEVEL_CHUNK_SOURCE, RIFF_DATE_SOURCE),
        ),
    )


def idit_read_tag(
    payload: bytes,
    chunk_id: str,
    chunk_index: int | None,
    byte_offset: int,
    sources: tuple[str, ...],
) -> RiffReadTag:
    value = payload.rstrip(b"\x00\r\n").decode("latin-1")
    rendered = convert_riff_date(value)
    return read_tag(
        "DateTimeOriginal",
        "Time",
        "Image::ExifTool::RIFF::Main",
        "IDIT",
        value,
        rendered,
        chunk_id,
        chunk_index,
        byte_offset,
        sources,
    )


def convert_riff_date(value: str) -> str:
    months = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    parts = value.split()
    if len(parts) >= 5:
        month = months.get(parts[1].lower())
        if month is not None:
            return f"{int(parts[4]):04d}:{month:02d}:{int(parts[2]):02d} {parts[3]}"
    return value


def audio_format_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    if len(payload) >= 2:
        encoding = uint16(payload, 0)
        tags.append(
            chunk_read_tag(
                "Encoding",
                "Audio",
                "Image::ExifTool::RIFF::AudioFormat",
                "0",
                encoding,
                AUDIO_ENCODING_DESCRIPTIONS.get(encoding, f"Unknown (0x{encoding:04x})"),
                chunk,
                0,
                (RIFF_AUDIO_FORMAT_SOURCE,),
            )
        )
    if len(payload) >= 4:
        tags.append(audio_uint_tag("NumChannels", "1", uint16(payload, 2), chunk, 2))
    if len(payload) >= 8:
        tags.append(audio_uint_tag("SampleRate", "2", uint32(payload, 4), chunk, 4))
    if len(payload) >= 12:
        tags.append(audio_uint_tag("AvgBytesPerSec", "4", uint32(payload, 8), chunk, 8))
    if len(payload) >= 16:
        tags.append(audio_uint_tag("BitsPerSample", "7", uint16(payload, 14), chunk, 14))
    return tuple(tags)


def broadcast_extension_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    if len(payload) >= 256:
        tags.append(broadcast_string_tag("Description", "0", payload, 0, 256, chunk))
    if len(payload) >= 288:
        tags.append(broadcast_string_tag("Originator", "256", payload, 256, 32, chunk))
    if len(payload) >= 320:
        tags.append(broadcast_string_tag("OriginatorReference", "288", payload, 288, 32, chunk))
    if len(payload) >= 338:
        raw_date = fixed_string(payload, 320, 18)
        rendered_date = raw_date.replace("-", ":", 2)
        if len(rendered_date) >= 10 and rendered_date[4] == ":" and rendered_date[7] == ":":
            rendered_date = f"{rendered_date[:10]} {rendered_date[10:].lstrip()}"
        tags.append(
            chunk_read_tag(
                "DateTimeOriginal",
                "Time",
                "Image::ExifTool::RIFF::BroadcastExt",
                "320",
                raw_date,
                rendered_date,
                chunk,
                320,
                (RIFF_BROADCAST_EXT_SOURCE,),
            )
        )
    if len(payload) >= 346:
        low = uint32(payload, 338)
        high = uint32(payload, 342)
        value = low + high * 4_294_967_296
        tags.append(
            chunk_read_tag(
                "TimeReference",
                "Audio",
                "Image::ExifTool::RIFF::BroadcastExt",
                "338",
                value,
                value,
                chunk,
                338,
                (RIFF_BROADCAST_EXT_SOURCE,),
            )
        )
    if len(payload) >= 348:
        tags.append(
            chunk_read_tag(
                "BWFVersion",
                "Audio",
                "Image::ExifTool::RIFF::BroadcastExt",
                "346",
                uint16(payload, 346),
                uint16(payload, 346),
                chunk,
                346,
                (RIFF_BROADCAST_EXT_SOURCE,),
            )
        )
    if len(payload) >= 412:
        umid = broadcast_umid(payload[348:412])
        tags.append(
            chunk_read_tag(
                "BWF_UMID",
                "Audio",
                "Image::ExifTool::RIFF::BroadcastExt",
                "348",
                umid,
                umid,
                chunk,
                348,
                (RIFF_BROADCAST_EXT_SOURCE,),
            )
        )
    if len(payload) > 602:
        coding_history = payload[602:].decode("latin-1").rstrip("\x00")
        tags.append(
            chunk_read_tag(
                "CodingHistory",
                "Audio",
                "Image::ExifTool::RIFF::BroadcastExt",
                "602",
                coding_history,
                coding_history,
                chunk,
                602,
                (RIFF_BROADCAST_EXT_SOURCE,),
            )
        )
    return tuple(tags)


def broadcast_string_tag(
    name: str,
    tag_id: str,
    payload: bytes,
    offset: int,
    length: int,
    chunk: RiffChunkPlan,
) -> RiffReadTag:
    value = fixed_string(payload, offset, length)
    return chunk_read_tag(
        name,
        "Audio",
        "Image::ExifTool::RIFF::BroadcastExt",
        tag_id,
        value,
        value,
        chunk,
        offset,
        (RIFF_BROADCAST_EXT_SOURCE,),
    )


def ds64_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    if len(payload) >= 8:
        tags.append(ds64_size_tag("RIFFSize64", "0", uint64(payload, 0), chunk, 0))
    if len(payload) >= 16:
        tags.append(ds64_size_tag("DataSize64", "1", uint64(payload, 8), chunk, 8))
    if len(payload) >= 24:
        value = uint64(payload, 16)
        tags.append(
            chunk_read_tag(
                "NumberOfSamples64",
                "Audio",
                "Image::ExifTool::RIFF::DS64",
                "2",
                value,
                value,
                chunk,
                16,
                (RIFF_DS64_SOURCE,),
            )
        )
    return tuple(tags)


def ds64_size_tag(
    name: str,
    tag_id: str,
    value: int,
    chunk: RiffChunkPlan,
    offset: int,
) -> RiffReadTag:
    return chunk_read_tag(
        name,
        "Audio",
        "Image::ExifTool::RIFF::DS64",
        tag_id,
        value,
        exiftool_file_size(value),
        chunk,
        offset,
        (RIFF_DS64_SOURCE,),
    )


def fact_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    if len(payload) < 4:
        return ()
    value = uint32(payload, 0)
    return (
        chunk_read_tag(
            "NumberOfSamples",
            "Audio",
            "Image::ExifTool::RIFF::Main",
            "fact",
            value,
            value,
            chunk,
            0,
            (RIFF_FACT_SOURCE,),
        ),
    )


def sampler_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    definitions: tuple[tuple[int, str], ...] = (
        (0, "Manufacturer"),
        (4, "Product"),
        (8, "SamplePeriod"),
        (12, "MIDIUnityNote"),
        (16, "MIDIPitchFraction"),
    )
    for offset, name in definitions:
        if len(payload) >= offset + 4:
            value = uint32(payload, offset)
            tags.append(sampler_uint_tag(name, str(offset // 4), value, value, chunk, offset))
    if len(payload) >= 24:
        value = uint32(payload, 20)
        rendered = {0: "none", 24: "24 fps", 25: "25 fps", 29: "29 fps", 30: "30 fps"}.get(
            value,
            value,
        )
        tags.append(sampler_uint_tag("SMPTEFormat", "5", value, rendered, chunk, 20))
    if len(payload) >= 28:
        value = uint32(payload, 24)
        tags.append(sampler_uint_tag("SMPTEOffset", "6", value, smpte_offset(value), chunk, 24))
    if len(payload) >= 32:
        value = uint32(payload, 28)
        tags.append(sampler_uint_tag("NumSampleLoops", "7", value, value, chunk, 28))
    if len(payload) >= 36:
        value = uint32(payload, 32)
        tags.append(sampler_uint_tag("SamplerDataLen", "8", value, value, chunk, 32))
    if len(payload) > 40:
        sampler_data = BinaryTagValue(payload[40:])
        tags.append(
            chunk_read_tag(
                "SamplerData",
                "Audio",
                "Image::ExifTool::RIFF::Sampler",
                "9",
                sampler_data,
                sampler_data,
                chunk,
                40,
                (RIFF_SAMPLER_SOURCE,),
            )
        )
    return tuple(tags)


def sampler_uint_tag(
    name: str,
    tag_id: str,
    raw_value: int,
    rendered_value: int | str,
    chunk: RiffChunkPlan,
    offset: int,
) -> RiffReadTag:
    return chunk_read_tag(
        name,
        "Audio",
        "Image::ExifTool::RIFF::Sampler",
        tag_id,
        raw_value,
        rendered_value,
        chunk,
        offset,
        (RIFF_SAMPLER_SOURCE,),
    )


def smpte_offset(value: int) -> str:
    text = f"{value:08x}"
    return f"{text[0:2]}:{text[2:4]}:{text[4:6]}:{text[6:8]}"


def instrument_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    names = (
        "UnshiftedNote",
        "FineTune",
        "Gain",
        "LowNote",
        "HighNote",
        "LowVelocity",
        "HighVelocity",
    )
    tags: list[RiffReadTag] = []
    for offset, name in enumerate(names):
        if len(payload) < offset + 1:
            break
        value = signed_int8(payload[offset])
        tags.append(
            chunk_read_tag(
                name,
                "Audio",
                "Image::ExifTool::RIFF::Instrument",
                str(offset),
                value,
                value,
                chunk,
                offset,
                (RIFF_INSTRUMENT_SOURCE,),
            )
        )
    return tuple(tags)


def cset_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    names = ("CodePage", "CountryCode", "LanguageCode", "Dialect")
    tags: list[RiffReadTag] = []
    for index, name in enumerate(names):
        offset = index * 2
        if len(payload) < offset + 2:
            break
        value = uint16(payload, offset)
        tags.append(
            chunk_read_tag(
                name,
                "Other",
                "Image::ExifTool::RIFF::CSET",
                str(index),
                value,
                value,
                chunk,
                offset,
                (RIFF_CSET_SOURCE,),
            )
        )
    return tuple(tags)


def acidizer_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    if len(payload) >= 4:
        flags = uint32(payload, 0)
        tags.append(
            acidizer_tag(
                "AcidizerFlags",
                "0",
                flags,
                tuple(name for bit, name in ACIDIZER_FLAG_DESCRIPTIONS if flags & bit),
                chunk,
                0,
            )
        )
    if len(payload) >= 6:
        root_note = uint16(payload, 4)
        tags.append(
            acidizer_tag(
                "RootNote",
                "4",
                root_note,
                ACIDIZER_ROOT_NOTE_DESCRIPTIONS.get(root_note, root_note),
                chunk,
                4,
            )
        )
    if len(payload) >= 16:
        beats = uint32(payload, 12)
        tags.append(acidizer_tag("Beats", "12", beats, beats, chunk, 12))
    if len(payload) >= 20:
        denominator = uint16(payload, 16)
        numerator = uint16(payload, 18)
        tags.append(
            acidizer_tag(
                "Meter",
                "16",
                (denominator, numerator),
                f"{numerator}/{denominator}",
                chunk,
                16,
            )
        )
    if len(payload) >= 24:
        tempo = float_le(payload, 20)
        tags.append(acidizer_tag("Tempo", "20", tempo, tempo, chunk, 20))
    return tuple(tags)


def acidizer_tag(
    name: str,
    tag_id: str,
    raw_value: RiffTagValue,
    rendered_value: RiffRenderedValue,
    chunk: RiffChunkPlan,
    offset: int,
) -> RiffReadTag:
    return chunk_read_tag(
        name,
        "Audio",
        "Image::ExifTool::RIFF::Acidizer",
        tag_id,
        raw_value,
        rendered_value,
        chunk,
        offset,
        (RIFF_ACIDIZER_SOURCE,),
    )


def hdrl_tags(riff_data: bytes, chunk: RiffChunkPlan) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    for subchunk_id, payload_offset, payload_length in iter_list_subchunks(riff_data, chunk):
        payload = riff_data[payload_offset : payload_offset + payload_length]
        if subchunk_id == b"avih":
            tags.extend(avi_header_tags(chunk, payload, payload_offset))
        elif subchunk_id == b"LIST":
            list_type = riff_data[payload_offset : payload_offset + 4]
            if list_type == b"strl":
                tags.extend(
                    stream_list_tags(riff_data, payload_offset, payload_length, chunk.index)
                )
            elif list_type == b"odml":
                tags.extend(open_dml_tags(riff_data, payload_offset, payload_length, chunk.index))
        elif subchunk_id == b"IDIT":
            tags.append(
                idit_read_tag(
                    payload,
                    "IDIT",
                    chunk.index,
                    payload_offset,
                    (RIFF_TOP_LEVEL_CHUNK_SOURCE, RIFF_DATE_SOURCE),
                )
            )
    return tuple(tags)


def open_dml_tags(
    riff_data: bytes,
    payload_offset: int,
    payload_length: int,
    parent_index: int,
) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    offset = payload_offset + 4
    limit = payload_offset + payload_length
    while offset + RIFF_CHUNK_HEADER_SIZE <= limit:
        subchunk_id = riff_data[offset : offset + 4]
        length = uint32(riff_data, offset + 4)
        start = offset + RIFF_CHUNK_HEADER_SIZE
        end = start + length
        if end > limit:
            break
        if subchunk_id == b"dmlh" and length >= 4:
            value = uint32(riff_data, start)
            tags.append(
                read_tag(
                    "TotalFrameCount",
                    "Video",
                    "Image::ExifTool::RIFF::ExtAVIHdr",
                    "0",
                    value,
                    value,
                    "dmlh",
                    parent_index,
                    start,
                    (RIFF_OPEN_DML_SOURCE,),
                )
            )
        offset = end + (length & 1)
    return tuple(tags)


def avi_header_tags(
    chunk: RiffChunkPlan,
    payload: bytes,
    absolute_offset: int,
) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    if len(payload) >= 4:
        raw_frame_rate = uint32(payload, 0)
        if raw_frame_rate:
            frame_rate = round(1_000_000 / raw_frame_rate, 3)
            tags.append(
                avi_tag("FrameRate", "0", raw_frame_rate, frame_rate, chunk, absolute_offset)
            )
    if len(payload) >= 8:
        max_data_rate = uint32(payload, 4)
        tags.append(
            avi_tag(
                "MaxDataRate",
                "1",
                max_data_rate,
                byte_rate(max_data_rate),
                chunk,
                absolute_offset + 4,
            )
        )
    if len(payload) >= 20:
        tags.append(
            avi_int_tag("FrameCount", "4", uint32(payload, 16), chunk, absolute_offset + 16)
        )
    if len(payload) >= 28:
        tags.append(
            avi_int_tag("StreamCount", "6", uint32(payload, 24), chunk, absolute_offset + 24)
        )
    if len(payload) >= 36:
        tags.append(
            avi_int_tag("ImageWidth", "8", uint32(payload, 32), chunk, absolute_offset + 32)
        )
    if len(payload) >= 40:
        tags.append(
            avi_int_tag("ImageHeight", "9", uint32(payload, 36), chunk, absolute_offset + 36)
        )
    return tuple(tags)


def stream_list_tags(
    riff_data: bytes,
    payload_offset: int,
    payload_length: int,
    parent_index: int,
) -> tuple[RiffReadTag, ...]:
    if payload_length < 4 or riff_data[payload_offset : payload_offset + 4] != b"strl":
        return ()
    tags: list[RiffReadTag] = []
    offset = payload_offset + 4
    limit = payload_offset + payload_length
    stream_type = ""
    while offset + RIFF_CHUNK_HEADER_SIZE <= limit:
        subchunk_id = riff_data[offset : offset + 4]
        length = uint32(riff_data, offset + 4)
        start = offset + RIFF_CHUNK_HEADER_SIZE
        end = start + length
        if end > limit:
            break
        payload = riff_data[start:end]
        if subchunk_id == b"strh":
            stream_tags, stream_type = stream_header_tags(payload, start, parent_index)
            tags.extend(stream_tags)
        elif subchunk_id == b"strf":
            tags.extend(stream_format_tags(payload, start, parent_index, stream_type))
        elif subchunk_id == b"strn":
            value = ascii_string(payload)
            if value:
                tags.append(
                    read_tag(
                        "StreamName",
                        "Video",
                        "Image::ExifTool::RIFF::Stream",
                        "strn",
                        value,
                        value,
                        "strn",
                        parent_index,
                        start,
                        (RIFF_STREAM_HEADER_SOURCE,),
                    )
                )
        offset = end + (length & 1)
    return tuple(tags)


def stream_header_tags(
    payload: bytes,
    absolute_offset: int,
    parent_index: int,
) -> tuple[tuple[RiffReadTag, ...], str]:
    tags: list[RiffReadTag] = []
    stream_type = ascii_string(payload[0:4]) if len(payload) >= 4 else ""
    if stream_type:
        tags.append(
            read_tag(
                "StreamType",
                "Video",
                "Image::ExifTool::RIFF::StreamHeader",
                "0",
                stream_type,
                STREAM_TYPE_DESCRIPTIONS.get(stream_type, stream_type),
                "strh",
                parent_index,
                absolute_offset,
                (RIFF_STREAM_HEADER_SOURCE,),
            )
        )
    if len(payload) >= 8:
        codec = ascii_string(payload[4:8])
        name = "Codec"
        if stream_type == "auds":
            name = "AudioCodec"
        elif stream_type == "vids":
            name = "VideoCodec"
        tags.append(
            read_tag(
                name,
                "Video",
                "Image::ExifTool::RIFF::StreamHeader",
                "1",
                codec,
                codec,
                "strh",
                parent_index,
                absolute_offset + 4,
                (RIFF_STREAM_HEADER_SOURCE,),
            )
        )
    if len(payload) >= 28:
        rate = rational_inverse(payload, 20)
        if rate is not None:
            name = "StreamSampleRate"
            if stream_type == "auds":
                name = "AudioSampleRate"
            elif stream_type == "vids":
                name = "VideoFrameRate"
            tags.append(
                read_tag(
                    name,
                    "Video",
                    "Image::ExifTool::RIFF::StreamHeader",
                    "5",
                    rate,
                    round(rate, 3 if stream_type != "auds" else 2),
                    "strh",
                    parent_index,
                    absolute_offset + 20,
                    (RIFF_STREAM_HEADER_SOURCE,),
                )
            )
    if len(payload) >= 36:
        name = "StreamSampleCount"
        if stream_type == "auds":
            name = "AudioSampleCount"
        elif stream_type == "vids":
            name = "VideoFrameCount"
        tags.append(
            read_tag(
                name,
                "Video",
                "Image::ExifTool::RIFF::StreamHeader",
                "8",
                uint32(payload, 32),
                uint32(payload, 32),
                "strh",
                parent_index,
                absolute_offset + 32,
                (RIFF_STREAM_HEADER_SOURCE,),
            )
        )
    if len(payload) >= 44:
        quality = uint32(payload, 40)
        tags.append(
            read_tag(
                "Quality",
                "Video",
                "Image::ExifTool::RIFF::StreamHeader",
                "10",
                quality,
                "Default" if quality == 0xFFFFFFFF else quality,
                "strh",
                parent_index,
                absolute_offset + 40,
                (RIFF_STREAM_HEADER_SOURCE,),
            )
        )
    if len(payload) >= 48:
        sample_size = uint32(payload, 44)
        if sample_size:
            rendered: str | int = (
                f"{sample_size} byte" if sample_size == 1 else f"{sample_size} bytes"
            )
        else:
            rendered = "Variable"
        tags.append(
            read_tag(
                "SampleSize",
                "Video",
                "Image::ExifTool::RIFF::StreamHeader",
                "11",
                sample_size,
                rendered,
                "strh",
                parent_index,
                absolute_offset + 44,
                (RIFF_STREAM_HEADER_SOURCE,),
            )
        )
    return tuple(tags), stream_type


def stream_format_tags(
    payload: bytes,
    absolute_offset: int,
    parent_index: int,
    stream_type: str,
) -> tuple[RiffReadTag, ...]:
    if stream_type == "vids":
        return bmp_format_tags(payload, absolute_offset, parent_index)
    if stream_type == "auds":
        return stream_audio_format_tags(payload, absolute_offset, parent_index)
    return ()


def stream_audio_format_tags(
    payload: bytes,
    absolute_offset: int,
    parent_index: int,
) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    if len(payload) >= 2:
        encoding = uint16(payload, 0)
        tags.append(
            read_tag(
                "Encoding",
                "Audio",
                "Image::ExifTool::RIFF::AudioFormat",
                "0",
                encoding,
                AUDIO_ENCODING_DESCRIPTIONS.get(encoding, f"Unknown (0x{encoding:04x})"),
                "strf",
                parent_index,
                absolute_offset,
                (RIFF_STREAM_HEADER_SOURCE, RIFF_AUDIO_FORMAT_SOURCE),
            )
        )
    if len(payload) >= 4:
        tags.append(
            stream_audio_uint_tag(
                "NumChannels",
                "1",
                uint16(payload, 2),
                absolute_offset + 2,
                parent_index,
            )
        )
    if len(payload) >= 8:
        tags.append(
            stream_audio_uint_tag(
                "SampleRate",
                "2",
                uint32(payload, 4),
                absolute_offset + 4,
                parent_index,
            )
        )
    if len(payload) >= 12:
        tags.append(
            stream_audio_uint_tag(
                "AvgBytesPerSec",
                "4",
                uint32(payload, 8),
                absolute_offset + 8,
                parent_index,
            )
        )
    if len(payload) >= 16:
        tags.append(
            stream_audio_uint_tag(
                "BitsPerSample",
                "7",
                uint16(payload, 14),
                absolute_offset + 14,
                parent_index,
            )
        )
    return tuple(tags)


def stream_audio_uint_tag(
    name: str,
    tag_id: str,
    value: int,
    absolute_offset: int,
    parent_index: int,
) -> RiffReadTag:
    return read_tag(
        name,
        "Audio",
        "Image::ExifTool::RIFF::AudioFormat",
        tag_id,
        value,
        value,
        "strf",
        parent_index,
        absolute_offset,
        (RIFF_STREAM_HEADER_SOURCE, RIFF_AUDIO_FORMAT_SOURCE),
    )


def bmp_format_tags(
    payload: bytes,
    absolute_offset: int,
    parent_index: int,
) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    if len(payload) >= 4:
        version = uint32(payload, 0)
        tags.append(
            bmp_tag(
                "BMPVersion",
                "0",
                version,
                bmp_version(version),
                absolute_offset,
                parent_index,
            )
        )
    if len(payload) >= 8:
        tags.append(
            bmp_tag(
                "ImageWidth",
                "4",
                uint32(payload, 4),
                uint32(payload, 4),
                absolute_offset + 4,
                parent_index,
            )
        )
    if len(payload) >= 12:
        height = int32(payload, 8)
        tags.append(
            bmp_tag(
                "ImageHeight",
                "8",
                height,
                abs(height),
                absolute_offset + 8,
                parent_index,
            )
        )
    if len(payload) >= 14:
        tags.append(
            bmp_tag(
                "Planes",
                "12",
                uint16(payload, 12),
                uint16(payload, 12),
                absolute_offset + 12,
                parent_index,
            )
        )
    if len(payload) >= 16:
        tags.append(
            bmp_tag(
                "BitDepth",
                "14",
                uint16(payload, 14),
                uint16(payload, 14),
                absolute_offset + 14,
                parent_index,
            )
        )
    if len(payload) >= 20:
        compression = uint32(payload, 16)
        tags.append(
            bmp_tag(
                "Compression",
                "16",
                compression,
                bmp_compression(compression),
                absolute_offset + 16,
                parent_index,
            )
        )
    if len(payload) >= 24:
        tags.append(
            bmp_tag(
                "ImageLength",
                "20",
                uint32(payload, 20),
                uint32(payload, 20),
                absolute_offset + 20,
                parent_index,
            )
        )
    if len(payload) >= 28:
        tags.append(
            bmp_tag(
                "PixelsPerMeterX",
                "24",
                uint32(payload, 24),
                uint32(payload, 24),
                absolute_offset + 24,
                parent_index,
            )
        )
    if len(payload) >= 32:
        tags.append(
            bmp_tag(
                "PixelsPerMeterY",
                "28",
                uint32(payload, 28),
                uint32(payload, 28),
                absolute_offset + 28,
                parent_index,
            )
        )
    if len(payload) >= 36:
        colors = uint32(payload, 32)
        tags.append(
            bmp_tag(
                "NumColors",
                "32",
                colors,
                "Use BitDepth" if colors == 0 else colors,
                absolute_offset + 32,
                parent_index,
            )
        )
    if len(payload) >= 40:
        colors = uint32(payload, 36)
        tags.append(
            bmp_tag(
                "NumImportantColors",
                "36",
                colors,
                "All" if colors == 0 else colors,
                absolute_offset + 36,
                parent_index,
            )
        )
    return tuple(tags)


def bmp_tag(
    name: str,
    tag_id: str,
    raw_value: RiffTagValue,
    rendered_value: RiffRenderedValue,
    absolute_offset: int,
    parent_index: int,
) -> RiffReadTag:
    return read_tag(
        name,
        "Image",
        "Image::ExifTool::BMP::Main",
        tag_id,
        raw_value,
        rendered_value,
        "strf",
        parent_index,
        absolute_offset,
        (RIFF_STREAM_HEADER_SOURCE, RIFF_BMP_FORMAT_SOURCE),
    )


def bmp_version(value: int) -> str | int:
    return {
        40: "Windows V3",
        68: "AVI BMP structure?",
        108: "Windows V4",
        124: "Windows V5",
    }.get(value, value)


def bmp_compression(value: int) -> str | int:
    if value > 256:
        return value.to_bytes(4, "little").decode("latin-1").rstrip("\x00")
    return {
        0: "None",
        1: "8-Bit RLE",
        2: "4-Bit RLE",
        3: "Bitfields",
        4: "JPEG",
        5: "PNG",
    }.get(value, value)


def composite_tags(
    riff_data: bytes,
    chunks: tuple[RiffChunkPlan, ...],
    tags: tuple[RiffReadTag, ...],
) -> tuple[RiffReadTag, ...]:
    output: list[RiffReadTag] = []
    image_size = composite_image_size(tags)
    if image_size is not None:
        width, height = image_size
        output.append(
            composite_read_tag(
                "ImageSize",
                "Composite",
                "Exif-ImageSize",
                f"{width}x{height}",
                f"{width}x{height}",
                (RIFF_COMPOSITE_SOURCE,),
            )
        )
        megapixels = width * height / 1_000_000
        output.append(
            composite_read_tag(
                "Megapixels",
                "Composite",
                "Exif-Megapixels",
                megapixels,
                rounded_megapixels(megapixels),
                (RIFF_COMPOSITE_SOURCE,),
            )
        )
    duration = composite_duration(riff_data, chunks, tags)
    if duration is not None:
        output.append(
            composite_read_tag(
                "Duration",
                "Composite",
                "RIFF-Duration",
                duration,
                convert_duration(duration),
                (RIFF_COMPOSITE_SOURCE, RIFF_CALC_DURATION_SOURCE),
            )
        )
    date_time_original = composite_date_time_original(tags)
    if date_time_original is not None:
        output.append(
            composite_read_tag(
                "DateTimeOriginal",
                "Composite",
                "Exif-DateTimeOriginal",
                date_time_original,
                date_time_original,
                (EXIF_DATETIME_ORIGINAL_COMPOSITE_SOURCE,),
                source_table="Image::ExifTool::Exif::Composite",
            )
        )
    return tuple(output)


def composite_image_size(tags: tuple[RiffReadTag, ...]) -> tuple[int, int] | None:
    width = latest_numeric_tag_value(tags, "ImageWidth", "Image")
    height = latest_numeric_tag_value(tags, "ImageHeight", "Image")
    if width is None or height is None:
        width = latest_numeric_tag_value_for_any_group(tags, "ImageWidth")
        height = latest_numeric_tag_value_for_any_group(tags, "ImageHeight")
    if width is None or height is None or width <= 0 or height <= 0:
        return None
    return int(width), int(height)


def latest_numeric_tag_value(
    tags: tuple[RiffReadTag, ...],
    name: str,
    group: str,
) -> float | None:
    for tag in reversed(tags):
        if tag.name != name or tag.group != group:
            continue
        value = tag.rendered_value
        if isinstance(value, (int, float)):
            return value
    return None


def latest_numeric_tag_value_for_any_group(
    tags: tuple[RiffReadTag, ...],
    name: str,
) -> float | None:
    for tag in reversed(tags):
        if tag.name != name:
            continue
        value = tag.rendered_value
        if isinstance(value, (int, float)):
            return value
    return None


def composite_duration(
    riff_data: bytes,
    chunks: tuple[RiffChunkPlan, ...],
    tags: tuple[RiffReadTag, ...],
) -> float | None:
    header_duration = header_video_duration(tags)
    if header_duration is not None:
        return header_duration
    avg_bytes_per_sec = latest_numeric_tag_value(tags, "AvgBytesPerSec", "Audio")
    if avg_bytes_per_sec is None or avg_bytes_per_sec == 0:
        return None
    if latest_numeric_tag_value(tags, "FrameCount", "Video") is not None:
        return None
    if latest_numeric_tag_value(tags, "VideoFrameCount", "Video") is not None:
        return None
    data_length = riff_data_length(chunks) or len(riff_data)
    return data_length / avg_bytes_per_sec


def header_video_duration(tags: tuple[RiffReadTag, ...]) -> float | None:
    frame_rate = latest_numeric_tag_value(tags, "FrameRate", "Video")
    frame_count = latest_numeric_tag_value(tags, "FrameCount", "Video")
    if frame_rate is None or frame_rate == 0 or frame_count is None:
        return None
    duration = frame_count / frame_rate
    video_frame_rate = latest_numeric_tag_value(tags, "VideoFrameRate", "Video")
    video_frame_count = latest_numeric_tag_value(tags, "VideoFrameCount", "Video")
    if video_frame_rate is None or video_frame_rate == 0 or video_frame_count is None:
        return duration
    stream_duration = video_frame_count / video_frame_rate
    ratio = duration / stream_duration if stream_duration else 0
    if 1.9 < ratio < 3.1:
        return stream_duration
    return duration


def riff_data_length(chunks: tuple[RiffChunkPlan, ...]) -> int | None:
    for chunk in chunks:
        if chunk.effective_id == "data":
            return chunk.payload_length
    return None


def composite_date_time_original(tags: tuple[RiffReadTag, ...]) -> str | None:
    if any(tag.name == "DateTimeOriginal" for tag in tags):
        return None
    date_created = latest_string_tag_value(tags, "DateCreated")
    time_created = latest_string_tag_value(tags, "TimeCreated")
    if date_created is None or time_created is None:
        return None
    return f"{date_created} {time_created}"


def latest_string_tag_value(tags: tuple[RiffReadTag, ...], name: str) -> str | None:
    for tag in reversed(tags):
        if tag.name != name:
            continue
        value = tag.rendered_value
        if isinstance(value, str):
            return value
    return None


def rounded_megapixels(value: float) -> float:
    if value < 0.001:
        return round(value, 6)
    return round(value, 3)


def convert_duration(value: float) -> str:
    return f"{value:.2f} s"


def composite_read_tag(
    name: str,
    group: str,
    tag_id: str,
    raw_value: RiffTagValue,
    rendered_value: RiffRenderedValue,
    sources: tuple[str, ...],
    source_table: str = "Image::ExifTool::RIFF::Composite",
) -> RiffReadTag:
    return read_tag(
        name,
        group,
        source_table,
        tag_id,
        raw_value,
        rendered_value,
        "Composite",
        None,
        0,
        sources,
    )


def nested_metadata_route_and_tags(
    riff_data: bytes,
    chunk: RiffChunkPlan,
    payload: bytes,
    *,
    extract_embedded_level: int = 0,
    include_hidden_unknowns: bool = False,
) -> tuple[RiffNestedMetadataRoute | None, tuple[RiffReadTag, ...]]:
    effective_id = chunk.effective_id
    if effective_id == "EXIF":
        tiff_payload = webp_exif_tiff_payload(payload)
        if tiff_payload is None:
            return (
                nested_route(
                    chunk,
                    "Image::ExifTool::Exif::Main",
                    "webp_exif_tiff",
                    "unsupported_payload",
                    "EXIF chunk does not match RIFF.pm WebP TIFF header conditions.",
                    0,
                ),
                (),
            )
        tags = exif_nested_tags(chunk, tiff_payload)
        return (
            nested_route(
                chunk,
                "Image::ExifTool::Exif::Main",
                "webp_exif_tiff",
                "extracted" if tags else "extraction_ready",
                "Route WebP EXIF chunk bytes to TIFF/EXIF parsing.",
                len(tags),
            ),
            tags,
        )
    if effective_id in RIFF_XMP_CHUNKS:
        tags = xmp_nested_tags(chunk, payload)
        return (
            nested_route(
                chunk,
                "Image::ExifTool::XMP::Main",
                "xmp_packet",
                "extracted" if tags else "extraction_ready",
                "Route RIFF XMP chunk bytes to XMP packet parsing.",
                len(tags),
            ),
            tags,
        )
    if effective_id == "JUNK":
        (
            tags,
            target_table,
            payload_kind,
            junk_status,
            detail,
            route_details,
        ) = riff_junk_route_and_tags(chunk, payload)
        return (
            nested_route(
                chunk,
                target_table,
                payload_kind,
                junk_status,
                detail,
                len(tags),
                (RIFF_NESTED_METADATA_SOURCE, RIFF_JUNK_ROUTE_SOURCE, *riff_junk_sources(payload)),
                route_details,
            ),
            tags,
        )
    if effective_id == "ICCP":
        tags = icc_nested_tags(chunk, payload)
        return (
            nested_route(
                chunk,
                "Image::ExifTool::ICC_Profile::Main",
                "icc_profile",
                "extracted" if tags else "extraction_ready",
                "Route WebP ICCP chunk bytes to ICC profile parsing.",
                len(tags),
            ),
            tags,
        )
    if effective_id == "LIST_Tdat":
        return (
            nested_route(
                chunk,
                "Image::ExifTool::RIFF::Tdat",
                "riff_process_chunks_adobe_tdat",
                "extraction_ready",
                (
                    "RIFF.pm delegates Adobe LIST_Tdat to the Tdat ProcessChunks table; "
                    "no source-backed scalar subchunk definitions are present."
                ),
                0,
                (RIFF_TDAT_LIST_SOURCE, RIFF_TDAT_TABLE_SOURCE),
                tdat_route_details(riff_data, chunk),
            ),
            (),
        )
    if effective_id == "LIST_adtl":
        tags, detail, route_details = associated_data_list_tags(riff_data, chunk)
        return (
            nested_route(
                chunk,
                "Image::ExifTool::RIFF::Main",
                "riff_associated_data_list",
                "extracted" if tags else "unsupported_payload",
                detail,
                len(tags),
                (RIFF_NESTED_METADATA_SOURCE, RIFF_ASSOCIATED_DATA_LIST_SOURCE),
                route_details,
            ),
            tags,
        )
    if effective_id == "C2PA":
        tags = c2pa_jumbf_nested_tags(chunk, payload)
        status: RiffNestedRouteStatus = "extracted" if tags else "unsupported_payload"
        detail = "Route RIFF C2PA chunk bytes to JUMBF/Jpeg2000 box parsing."
        if not tags:
            detail = "C2PA chunk did not contain deterministic JUMBF/JUMD or JSON tags."
        return (
            nested_route(
                chunk,
                "Image::ExifTool::Jpeg2000::Main",
                "jumbf/c2pa_payload",
                status,
                detail,
                len(tags),
                (RIFF_NESTED_METADATA_SOURCE, RIFF_C2PA_JUMBF_SOURCE),
            ),
            tags,
        )
    if effective_id in {"id3 ", "ID3 "}:
        from exifmodern.formats.riff.id3_payload_reader import read_riff_id3_payload

        id3_result = read_riff_id3_payload(payload)
        tags = tuple(
            chunk_read_tag(
                tag.name,
                tag.group,
                tag.source_table,
                tag.tag_id,
                tag.raw_value,
                tag.rendered_value,
                chunk,
                tag.relative_offset,
                (RIFF_NESTED_METADATA_SOURCE, *tag.evidence_ids),
            )
            for tag in id3_result.tags
        )
        return (
            nested_route(
                chunk,
                "Image::ExifTool::ID3::Main",
                "id3_payload",
                id3_result.status,
                id3_result.detail,
                len(tags),
                (RIFF_NESTED_METADATA_SOURCE, *id3_result.evidence_ids),
            ),
            tags,
        )
    quicktime_stream_route = quicktime_stream_route_and_tags(
        chunk,
        payload,
        extract_embedded_level=extract_embedded_level,
    )
    if quicktime_stream_route is not None:
        return quicktime_stream_route
    if effective_id == "LIST_ncdt":
        tags, detail = nikon_avi_list_tags(
            riff_data,
            chunk,
            include_hidden_unknowns=include_hidden_unknowns,
        )
        return (
            nested_route(
                chunk,
                "Image::ExifTool::Nikon::AVI",
                "riff_process_chunks_nikon_avi_first_pass",
                "extracted" if tags else "unsupported_payload",
                detail,
                len(tags),
                NIKON_AVI_ROUTE_SOURCES,
            ),
            tags,
        )
    if effective_id in {"LIST_hydt", "LIST_pntx"}:
        detail, route_details = pentax_avi_route_detail(riff_data, chunk)
        return (
            nested_route(
                chunk,
                PENTAX_AVI_TABLE,
                "riff_process_chunks_pentax_avi_makernotes",
                "adapter_missing",
                detail,
                0,
                PENTAX_AVI_ROUTE_SOURCES,
                route_details,
            ),
            (),
        )
    return None, ()


def riff_junk_sources(payload: bytes) -> tuple[str, ...]:
    if payload.startswith(b"OLYMDigital Camera"):
        return (OLYMPUS_AVI_JUNK_SOURCE,)
    if payload.startswith(b"QVMI"):
        return (CASIO_JUNK_EXIF_SOURCE,)
    if payload.startswith(b"ucmt"):
        return (RICOH_AVI_JUNK_SOURCE,)
    if payload.startswith(PENTAX_JUNK_RS1000_PREFIX):
        return (PENTAX_JUNK_SOURCE,)
    if payload.startswith(PENTAX_JUNK2_RZ18_PREFIX):
        return (PENTAX_JUNK2_SOURCE,)
    if payload.startswith((b"0GDA", b"0GPS")):
        return (LUCAS_JUNK_SOURCE, QUICKTIME_STREAM_SOURCE)
    return ()


def riff_junk_route_and_tags(
    chunk: RiffChunkPlan, payload: bytes
) -> tuple[
    tuple[RiffReadTag, ...],
    str,
    str,
    RiffNestedRouteStatus,
    str,
    JsonObject,
]:
    if payload.startswith(b"OLYMDigital Camera"):
        tags, unsupported = olympus_junk_tags(chunk, payload)
        status: RiffNestedRouteStatus = "extracted" if tags else "unsupported_payload"
        detail = "extracted source-backed Olympus AVI JUNK scalar fields."
        if unsupported:
            detail += " Unsupported: " + "; ".join(unsupported)
        if not tags:
            detail = "Olympus AVI JUNK payload did not contain complete scalar fields."
            if unsupported:
                detail += " Unsupported: " + "; ".join(unsupported)
        return (
            tags,
            OLYMPUS_AVI_JUNK_TABLE,
            "riff_junk_olympus_avi",
            status,
            detail,
            {
                "condition": "$$valPt =~ /^OLYMDigital Camera/",
                "source_table": OLYMPUS_AVI_JUNK_TABLE,
                "unsupported": list(unsupported),
            },
        )
    if payload.startswith(b"QVMI"):
        tags, unsupported = casio_junk_exif_tags(chunk, payload)
        status = "extracted" if tags else "unsupported_payload"
        detail = "extracted source-backed Casio QVMI JUNK EXIF fields."
        if unsupported:
            detail += " Unsupported: " + "; ".join(unsupported)
        if not tags:
            detail = "Casio QVMI JUNK payload did not contain parseable Start 10 BigEndian EXIF."
            if unsupported:
                detail += " Unsupported: " + "; ".join(unsupported)
        return (
            tags,
            CASIO_JUNK_EXIF_TABLE,
            "riff_junk_casio_exif_start_10_big_endian",
            status,
            detail,
            {
                "byte_order": "BigEndian",
                "condition": "$$valPt =~ /^QVMI/",
                "source_table": CASIO_JUNK_EXIF_TABLE,
                "start": 10,
                "unsupported": list(unsupported),
            },
        )
    if payload.startswith(b"ucmt"):
        tags, unsupported = ricoh_junk_tags(chunk, payload)
        status = "extracted" if tags else "unsupported_payload"
        detail = "extracted source-backed Ricoh AVI JUNK subchunk fields."
        if unsupported:
            detail += " Unsupported: " + "; ".join(unsupported)
        if not tags:
            detail = "Ricoh AVI JUNK payload did not contain supported subchunk scalars."
            if unsupported:
                detail += " Unsupported: " + "; ".join(unsupported)
        return (
            tags,
            RICOH_AVI_JUNK_TABLE,
            "riff_junk_ricoh_avi_process_chunks",
            status,
            detail,
            {
                "condition": "$$valPt =~ /^ucmt/",
                "process_proc": "Image::ExifTool::RIFF::ProcessChunks",
                "source_table": RICOH_AVI_JUNK_TABLE,
                "unsupported": list(unsupported),
            },
        )
    if payload.startswith(PENTAX_JUNK_RS1000_PREFIX):
        tags, unsupported = pentax_junk_tags(chunk, payload)
        detail = "extracted source-backed Pentax Optio RS1000 JUNK scalar fields."
        status = "extracted"
        if unsupported:
            detail += " Unsupported: " + "; ".join(unsupported)
        if not tags:
            status = "unsupported_payload"
            detail = "Pentax Optio RS1000 JUNK payload did not contain complete scalar fields."
            if unsupported:
                detail += " Unsupported: " + "; ".join(unsupported)
        return (
            tags,
            PENTAX_JUNK_TABLE,
            "riff_junk_pentax_rs1000",
            status,
            detail,
            {
                "condition": "$$valPt =~ /^IIII\\x01\\0/",
                "source_table": PENTAX_JUNK_TABLE,
                "unsupported": list(unsupported),
            },
        )
    if payload.startswith(PENTAX_JUNK2_RZ18_PREFIX):
        tags, unsupported = pentax_junk2_tags(chunk, payload)
        status = "extracted" if tags else "unsupported_payload"
        detail = "extracted source-backed Pentax Optio RZ18 JUNK scalar fields."
        if unsupported:
            detail += " Unsupported: " + "; ".join(unsupported)
        if not tags:
            detail = "Pentax Optio RZ18 JUNK payload did not contain complete scalar fields."
            if unsupported:
                detail += " Unsupported: " + "; ".join(unsupported)
        return (
            tags,
            PENTAX_JUNK2_TABLE,
            "riff_junk_pentax_rz18",
            status,
            detail,
            {
                "condition": "$$valPt =~ /^PENTDigital Camera/",
                "source_table": PENTAX_JUNK2_TABLE,
                "unsupported": list(unsupported),
            },
        )
    if payload.startswith((b"0GDA", b"0GPS")):
        tags, unsupported = lucas_junk_tags(chunk, payload)
        status = "extracted" if tags else "unsupported_payload"
        detail = "extracted source-backed Lucas timed GPS/accelerometer JUNK records."
        if unsupported:
            detail += " Unsupported: " + "; ".join(unsupported)
        if not tags:
            detail = "Lucas JUNK payload did not contain complete 0GDA or 0GPS records."
            if unsupported:
                detail += " Unsupported: " + "; ".join(unsupported)
        return (
            tags,
            LUCAS_JUNK_TABLE,
            "riff_junk_lucas_process_lucas",
            status,
            detail,
            {
                "condition": "$$valPt =~ /^0G(DA|PS)/",
                "process_proc": "Image::ExifTool::RIFF::ProcessLucas",
                "requires_extract_embedded": True,
                "source_table": LUCAS_JUNK_TABLE,
                "unsupported": list(unsupported),
            },
        )
    text = payload.rstrip(b"\x00")
    if text and all(0x20 <= byte < 0x7F for byte in text):
        value = text.decode("latin-1")
        tag = chunk_read_tag(
            "TextJunk",
            "Video",
            "Image::ExifTool::RIFF::Main",
            "JUNK",
            value,
            value,
            chunk,
            0,
            (RIFF_JUNK_ROUTE_SOURCE,),
        )
        return (
            (tag,),
            "Image::ExifTool::RIFF::Main",
            "riff_junk_text",
            "extracted",
            "extracted source-backed ASCII TextJunk payload.",
            {
                "condition": "$val =~ /^([^\\0-\\x1f\\x7f-\\xff]+)\\0*$/",
                "source_table": "Image::ExifTool::RIFF::Main",
            },
        )
    return (
        (),
        "Image::ExifTool::RIFF::Main",
        "riff_junk_conditional_dispatch",
        "unsupported_payload",
        (
            "JUNK payload did not match source-backed Olympus, Casio QVMI EXIF, Ricoh, "
            "Pentax RS1000, Pentax RZ18, Lucas, or ASCII TextJunk conditions."
        ),
        {
            "deferred_adapters": [
                "Image::ExifTool::Olympus::AVI ThumbInfo",
                "Image::ExifTool::Exif::Main Casio malformed Start 10 BigEndian",
                "Image::ExifTool::Ricoh::AVI mnrt/thum",
                "Image::ExifTool::QuickTime::Stream ProcessLucas truncated records",
            ],
            "source_table": "Image::ExifTool::RIFF::Main",
            "unsupported_reason": "junk_payload_condition_not_promoted",
        },
    )


def riff_junk_deferred_adapter(payload: bytes) -> str | None:
    return None


def olympus_junk_tags(
    chunk: RiffChunkPlan, payload: bytes
) -> tuple[tuple[RiffReadTag, ...], tuple[str, ...]]:
    tags: list[RiffReadTag] = []
    unsupported: list[str] = []
    for offset, name, length, group in (
        (0x12, "Make", 24, "Camera"),
        (0x2C, "Model", 24, "Camera"),
        (0x83, "DateTime1", 24, "Time"),
        (0x9D, "DateTime2", 24, "Time"),
    ):
        if len(payload) >= offset + length:
            value = fixed_string(payload, offset, length)
            tags.append(
                olympus_junk_tag(name, group, f"0x{offset:04x}", value, value, chunk, offset)
            )
        else:
            unsupported.append(
                f"{name} string[{length}] at 0x{offset:02x} requires {offset + length} bytes"
            )
    if len(payload) >= 0x5E + 8:
        f_number = rational64u(payload, 0x5E)
        if f_number is None:
            unsupported.append("FNumber rational64u denominator is zero")
        else:
            tags.append(
                olympus_junk_tag(
                    "FNumber",
                    "Camera",
                    "0x005e",
                    f_number,
                    f"{f_number:.1f}",
                    chunk,
                    0x5E,
                )
            )
    else:
        unsupported.append("FNumber rational64u at 0x5e requires 102 bytes")
    if len(payload) > 0x129:
        unsupported.append("ThumbInfo subdirectory Image::ExifTool::Olympus::thmb2 deferred")
    return tuple(tags), tuple(unsupported)


def olympus_junk_tag(
    name: str,
    group: str,
    tag_id: str,
    raw_value: RiffTagValue,
    rendered_value: RiffRenderedValue,
    chunk: RiffChunkPlan,
    offset: int,
) -> RiffReadTag:
    return chunk_read_tag(
        name,
        group,
        OLYMPUS_AVI_JUNK_TABLE,
        tag_id,
        raw_value,
        rendered_value,
        chunk,
        offset,
        (RIFF_JUNK_ROUTE_SOURCE, OLYMPUS_AVI_JUNK_SOURCE),
    )


def casio_junk_exif_tags(
    chunk: RiffChunkPlan, payload: bytes
) -> tuple[tuple[RiffReadTag, ...], tuple[str, ...]]:
    if len(payload) <= 10:
        return (), ("Casio QVMI Start 10 EXIF payload is missing",)
    tiff_payload = payload[10:]
    tags: list[RiffReadTag] = []
    try:
        header = parse_tiff_header(tiff_payload)
    except ValueError as exc:
        return (), (f"Casio QVMI Start 10 EXIF header rejected: {exc}",)
    if header.endian != "big":
        return (), ("Casio QVMI Start 10 EXIF payload is not BigEndian",)
    tags.append(
        chunk_read_tag(
            "ExifByteOrder",
            "File",
            CASIO_JUNK_EXIF_TABLE,
            "ExifByteOrder",
            "MM",
            header.byte_order,
            chunk,
            10,
            (RIFF_JUNK_ROUTE_SOURCE, CASIO_JUNK_EXIF_SOURCE, RIFF_EXIF_BYTE_ORDER_SOURCE),
        )
    )
    for group, values in exif_group_values(tiff_payload):
        for name, value in values.items():
            tag_value = riff_tag_value_from_json(value)
            if tag_value is None and value is not None:
                continue
            tags.append(
                chunk_read_tag(
                    name,
                    group,
                    CASIO_JUNK_EXIF_TABLE,
                    EXIF_TAG_IDS.get(name, name),
                    tag_value,
                    riff_rendered_value_from_tag_value(tag_value),
                    chunk,
                    10,
                    (RIFF_JUNK_ROUTE_SOURCE, CASIO_JUNK_EXIF_SOURCE),
                )
            )
    return tuple(tags), ()


def ricoh_junk_tags(
    chunk: RiffChunkPlan, payload: bytes
) -> tuple[tuple[RiffReadTag, ...], tuple[str, ...]]:
    tags: list[RiffReadTag] = []
    unsupported: list[str] = []
    offset = 0
    while offset + RIFF_CHUNK_HEADER_SIZE <= len(payload):
        subchunk_id = payload[offset : offset + 4]
        subchunk_len = uint32(payload, offset + 4)
        value_offset = offset + RIFF_CHUNK_HEADER_SIZE
        value_end = value_offset + subchunk_len
        if value_end > len(payload):
            unsupported.append(
                f"{ascii_chunk_id(subchunk_id)} declares {subchunk_len} bytes with "
                f"only {max(0, len(payload) - value_offset)} available"
            )
            break
        value = payload[value_offset:value_end]
        if subchunk_id == b"ucmt":
            comment = ricoh_comment_value(value)
            tags.append(
                chunk_read_tag(
                    "Comment",
                    "Video",
                    RICOH_AVI_JUNK_TABLE,
                    "ucmt",
                    comment,
                    comment,
                    chunk,
                    value_offset,
                    (RIFF_JUNK_ROUTE_SOURCE, RICOH_AVI_JUNK_SOURCE),
                )
            )
        elif subchunk_id == b"rdc2":
            hex_value = value.hex()
            tags.append(
                chunk_read_tag(
                    "RicohRDC2",
                    "Video",
                    RICOH_AVI_JUNK_TABLE,
                    "rdc2",
                    hex_value,
                    hex_value,
                    chunk,
                    value_offset,
                    (RIFF_JUNK_ROUTE_SOURCE, RICOH_AVI_JUNK_SOURCE),
                )
            )
        elif subchunk_id == b"thum":
            unsupported.append("ThumbnailImage binary payload deferred")
        elif subchunk_id == b"mnrt":
            unsupported.append("MakerNoteRicoh subdirectory Start $valuePtr + 8 deferred")
        else:
            unsupported.append(f"{ascii_chunk_id(subchunk_id)} subchunk is not promoted")
        offset = value_end + (subchunk_len & 1)
    return tuple(tags), tuple(unsupported)


def ricoh_comment_value(value: bytes) -> str:
    if value.startswith(b"Unicode\x00"):
        value = value[len(b"Unicode\x00") :]
    elif value.startswith(b"ASCII\x00\x00\x00"):
        value = value[len(b"ASCII\x00\x00\x00") :]
    return value.replace(b"\x00", b"").decode("latin-1", errors="replace").rstrip()


def lucas_junk_tags(
    chunk: RiffChunkPlan, payload: bytes
) -> tuple[tuple[RiffReadTag, ...], tuple[str, ...]]:
    tags: list[RiffReadTag] = []
    unsupported: list[str] = []
    offset = 0
    while offset + 4 <= len(payload):
        record_id = payload[offset : offset + 4]
        if record_id not in {b"0GDA", b"0GPS"}:
            next_gda = payload.find(b"0GDA", offset + 1)
            next_gps = payload.find(b"0GPS", offset + 1)
            next_offsets = tuple(value for value in (next_gda, next_gps) if value >= 0)
            if not next_offsets:
                break
            offset = min(next_offsets)
            continue
        record_body_offset = offset + 4
        record_len = 24 if record_id == b"0GDA" else 48
        if record_body_offset + record_len > len(payload):
            unsupported.append(
                f"{ascii_chunk_id(record_id)} record requires {record_len} bytes after ID"
            )
            break
        sample_time = uint64(payload, record_body_offset) / 1000
        tags.append(
            lucas_junk_tag(
                "SampleDateTime",
                "Time",
                "SampleDateTime",
                sample_time,
                sample_time,
                chunk,
                record_body_offset,
            )
        )
        if record_id == b"0GDA":
            accelerometer = lucas_accelerometer(payload, record_body_offset + 8)
            tags.append(
                lucas_junk_tag(
                    "Accelerometer",
                    "Location",
                    "Accelerometer",
                    accelerometer,
                    accelerometer,
                    chunk,
                    record_body_offset + 8,
                )
            )
            offset = record_body_offset + record_len
            continue
        nmea_len = uint32(payload, record_body_offset + 8)
        nmea_offset = record_body_offset + record_len
        nmea_end = nmea_offset + nmea_len
        if nmea_end > len(payload):
            unsupported.append(
                f"0GPS NMEA block declares {nmea_len} bytes with "
                f"only {max(0, len(payload) - nmea_offset)} available"
            )
            break
        tags.extend(lucas_gps_tags(chunk, payload[nmea_offset:nmea_end], nmea_offset))
        offset = nmea_end
    return tuple(tags), tuple(unsupported)


def lucas_junk_tag(
    name: str,
    group: str,
    tag_id: str,
    raw_value: RiffTagValue,
    rendered_value: RiffRenderedValue,
    chunk: RiffChunkPlan,
    offset: int,
) -> RiffReadTag:
    return chunk_read_tag(
        name,
        group,
        LUCAS_JUNK_TABLE,
        tag_id,
        raw_value,
        rendered_value,
        chunk,
        offset,
        (RIFF_JUNK_ROUTE_SOURCE, LUCAS_JUNK_SOURCE, QUICKTIME_STREAM_SOURCE),
    )


def lucas_accelerometer(payload: bytes, offset: int) -> str:
    values = tuple(int32(payload, offset + index * 4) / 256 for index in range(3))
    return " ".join(f"{value:g}" for value in values)


def lucas_gps_tags(
    chunk: RiffChunkPlan, nmea_payload: bytes, absolute_offset: int
) -> tuple[RiffReadTag, ...]:
    time_value = ""
    date_value = ""
    latitude: float | None = None
    longitude: float | None = None
    speed = ""
    satellites = ""
    dop = ""
    altitude = ""
    for sentence in lucas_nmea_sentences(nmea_payload):
        fields = sentence.split(",")
        if len(fields) < 3:
            continue
        if fields[0] == "GC":
            time_value = fields[1]
            if len(fields) >= 8:
                date_value = fields[2]
                satellites = fields[5]
                dop = fields[6]
                altitude = fields[7]
        elif fields[0] == "GA":
            time_value = fields[1]
            if len(fields) >= 8 and fields[2] == "A":
                latitude = lucas_degrees(fields[3], fields[6])
                longitude = lucas_degrees(fields[4], fields[7])
                speed = fields[5]
    tags: list[RiffReadTag] = []
    if time_value:
        time_tag = f"{time_value[0:2]}:{time_value[2:4]}:{time_value[4:6]}Z"
        if date_value and len(date_value) >= 6:
            rendered_date = f"20{date_value[4:6]}:{date_value[2:4]}:{date_value[0:2]}"
            tags.append(
                lucas_junk_tag(
                    "GPSDateTime",
                    "Time",
                    "GPSDateTime",
                    f"{rendered_date} {time_tag}",
                    f"{rendered_date} {time_tag}",
                    chunk,
                    absolute_offset,
                )
            )
        else:
            tags.append(
                lucas_junk_tag(
                    "GPSTimeStamp",
                    "Time",
                    "GPSTimeStamp",
                    time_tag,
                    time_tag,
                    chunk,
                    absolute_offset,
                )
            )
    if latitude is not None and longitude is not None:
        tags.append(
            lucas_junk_tag(
                "GPSLatitude", "Location", "GPSLatitude", latitude, latitude, chunk, absolute_offset
            )
        )
        tags.append(
            lucas_junk_tag(
                "GPSLongitude",
                "Location",
                "GPSLongitude",
                longitude,
                longitude,
                chunk,
                absolute_offset,
            )
        )
    if speed:
        tags.append(
            lucas_junk_tag(
                "GPSSpeed", "Location", "GPSSpeed", int(speed), int(speed), chunk, absolute_offset
            )
        )
    if altitude:
        tags.append(
            lucas_junk_tag(
                "GPSAltitude",
                "Location",
                "GPSAltitude",
                int(altitude),
                int(altitude),
                chunk,
                absolute_offset,
            )
        )
    if satellites:
        tags.append(
            lucas_junk_tag(
                "GPSSatellites",
                "Location",
                "GPSSatellites",
                satellites,
                satellites,
                chunk,
                absolute_offset,
            )
        )
    if dop:
        tags.append(
            lucas_junk_tag(
                "GPSDOP", "Location", "GPSDOP", float(dop), float(dop), chunk, absolute_offset
            )
        )
    return tuple(tags)


def lucas_nmea_sentences(payload: bytes) -> tuple[str, ...]:
    sentences: list[str] = []
    for raw in payload.split(b"$"):
        sentence = raw.split(b"\r", 1)[0].split(b"\n", 1)[0].split(b"\x00", 1)[0]
        if sentence.startswith((b"GC,", b"GA,")):
            sentences.append(sentence.decode("latin-1", errors="replace"))
    return tuple(sentences)


def lucas_degrees(value: str, ref: str) -> float | None:
    try:
        numeric = float(value)
    except ValueError:
        return None
    degrees = int(numeric / 100)
    decimal = degrees + (numeric - degrees * 100) / 60
    return -decimal if ref in {"S", "W"} else decimal


def pentax_junk_tags(
    chunk: RiffChunkPlan, payload: bytes
) -> tuple[tuple[RiffReadTag, ...], tuple[str, ...]]:
    if len(payload) < 0x0C + 32:
        return (), (f"Model string[32] at 0x0c requires 44 bytes, found {len(payload)}",)
    value = fixed_string(payload, 0x0C, 32)
    return (
        (
            chunk_read_tag(
                "Model",
                "Camera",
                PENTAX_JUNK_TABLE,
                "0x000c",
                value,
                value,
                chunk,
                0x0C,
                (RIFF_JUNK_ROUTE_SOURCE, PENTAX_JUNK_SOURCE),
            ),
        ),
        (),
    )


def pentax_junk2_tags(
    chunk: RiffChunkPlan, payload: bytes
) -> tuple[tuple[RiffReadTag, ...], tuple[str, ...]]:
    tags: list[RiffReadTag] = []
    unsupported: list[str] = []
    for offset, name, length, group in (
        (0x12, "Make", 24, "Camera"),
        (0x2C, "Model", 24, "Camera"),
        (0x83, "DateTime1", 24, "Time"),
        (0x9D, "DateTime2", 24, "Time"),
    ):
        if len(payload) >= offset + length:
            string_value = fixed_string(payload, offset, length)
            tags.append(
                pentax_junk2_tag(
                    name,
                    group,
                    f"0x{offset:04x}",
                    string_value,
                    string_value,
                    chunk,
                    offset,
                )
            )
        else:
            unsupported.append(
                f"{name} string[{length}] at 0x{offset:02x} requires {offset + length} bytes"
            )
    if len(payload) >= 0x5E + 8:
        rational_value = rational64u(payload, 0x5E)
        if rational_value is None:
            unsupported.append("FNumber rational64u denominator is zero")
        else:
            tags.append(
                pentax_junk2_tag(
                    "FNumber",
                    "Camera",
                    "0x005e",
                    rational_value,
                    f"{rational_value:.1f}",
                    chunk,
                    0x5E,
                )
            )
    else:
        unsupported.append("FNumber rational64u at 0x5e requires 102 bytes")
    for offset, name, size in (
        (0x12B, "ThumbnailWidth", 2),
        (0x12D, "ThumbnailHeight", 2),
        (0x12F, "ThumbnailLength", 4),
    ):
        if len(payload) >= offset + size:
            integer_value = uint16(payload, offset) if size == 2 else uint32(payload, offset)
            tags.append(
                pentax_junk2_tag(
                    name,
                    "Camera",
                    f"0x{offset:04x}",
                    integer_value,
                    integer_value,
                    chunk,
                    offset,
                )
            )
        else:
            unsupported.append(f"{name} at 0x{offset:03x} requires {offset + size} bytes")
    thumbnail_length = uint32(payload, 0x12F) if len(payload) >= 0x133 else 0
    if thumbnail_length:
        if len(payload) >= 0x133 + thumbnail_length:
            thumbnail = payload[0x133 : 0x133 + thumbnail_length]
            if thumbnail.startswith(b"\xff\xd8"):
                binary = BinaryTagValue(thumbnail, media_type="image/jpeg", file_extension="jpg")
                tags.append(
                    pentax_junk2_tag(
                        "ThumbnailImage",
                        "Preview",
                        "0x0133",
                        binary,
                        binary,
                        chunk,
                        0x133,
                    )
                )
            else:
                unsupported.append("ThumbnailImage ValidateImage rejected non-JPEG payload")
        else:
            unsupported.append(
                f"ThumbnailImage declares {thumbnail_length} bytes with only "
                f"{max(0, len(payload) - 0x133)} available"
            )
    return tuple(tags), tuple(unsupported)


def pentax_junk2_tag(
    name: str,
    group: str,
    tag_id: str,
    raw_value: RiffTagValue,
    rendered_value: RiffRenderedValue,
    chunk: RiffChunkPlan,
    offset: int,
) -> RiffReadTag:
    return chunk_read_tag(
        name,
        group,
        PENTAX_JUNK2_TABLE,
        tag_id,
        raw_value,
        rendered_value,
        chunk,
        offset,
        (RIFF_JUNK_ROUTE_SOURCE, PENTAX_JUNK2_SOURCE),
    )


def rational64u(payload: bytes, offset: int) -> float | None:
    numerator = uint32(payload, offset)
    denominator = uint32(payload, offset + 4)
    if denominator == 0:
        return None
    return numerator / denominator


def pentax_avi_route_detail(riff_data: bytes, chunk: RiffChunkPlan) -> tuple[str, JsonObject]:
    maker_note_subchunks: JsonArray = []
    unsupported_subchunks: JsonArray = []
    list_type = chunk.effective_id.removeprefix("LIST_")
    offset = chunk.payload_body_offset
    limit = chunk.payload_offset + chunk.payload_length
    stopped_on_truncated_subchunk = False
    while offset + RIFF_CHUNK_HEADER_SIZE <= limit:
        subchunk_id = riff_data[offset : offset + 4]
        payload_length = uint32(riff_data, offset + 4)
        payload_offset = offset + RIFF_CHUNK_HEADER_SIZE
        payload_end = payload_offset + payload_length
        subchunk_name = ascii_chunk_id(subchunk_id)
        if payload_end > limit:
            unsupported_subchunks.append(
                {
                    "available_payload_length": max(0, limit - payload_offset),
                    "declared_payload_length": payload_length,
                    "subchunk_id": subchunk_name,
                    "unsupported_reason": "truncated_subchunk_payload",
                }
            )
            stopped_on_truncated_subchunk = True
            break
        if subchunk_id in PENTAX_AVI_MAKERNOTE_SUBCHUNKS:
            maker_note_subchunks.append(
                pentax_avi_makernote_subchunk_detail(
                    subchunk_name,
                    payload_offset,
                    payload_length,
                )
            )
        else:
            unsupported_subchunks.append(
                {
                    "payload_length": payload_length,
                    "subchunk_id": subchunk_name,
                    "unsupported_reason": "not_defined_in_Image::ExifTool::Pentax::AVI",
                }
            )
        offset = payload_end + (payload_length & 1)
    if offset < limit and not stopped_on_truncated_subchunk:
        unsupported_subchunks.append(
            {
                "available_header_bytes": limit - offset,
                "unsupported_reason": "trailing_partial_subchunk_header",
            }
        )
    details: JsonObject = {
        "adapter_missing": True,
        "byte_order": PENTAX_AVI_MAKERNOTE_BYTE_ORDER,
        "list_type": list_type,
        "maker_note_payload_start": PENTAX_AVI_MAKERNOTE_START,
        "maker_note_subchunks": maker_note_subchunks,
        "process_proc": "Image::ExifTool::RIFF::ProcessChunks",
        "source_table": PENTAX_AVI_TABLE,
        "target_table": PENTAX_AVI_MAKERNOTE_TABLE,
        "unsupported_reason": "pentax_riff_avi_makernote_adapter_missing",
        "unsupported_subchunks": unsupported_subchunks,
    }
    facts = pentax_avi_route_facts(maker_note_subchunks)
    detail = (
        f"RIFF.pm delegates {chunk.effective_id} subchunks to {PENTAX_AVI_TABLE} via "
        f"ProcessChunks; {facts} Adapter missing: Pentax MakerNotes parsing for RIFF AVI "
        "is not implemented."
    )
    if unsupported_subchunks:
        detail += " Unsupported: " + "; ".join(
            pentax_avi_unsupported_detail(item) for item in unsupported_subchunks
        )
    return detail, details


def tdat_route_details(riff_data: bytes, chunk: RiffChunkPlan) -> JsonObject:
    subchunks: JsonArray = []
    for subchunk_id, payload_offset, payload_length in iter_list_subchunks(riff_data, chunk):
        subchunks.append(
            {
                "payload_length": payload_length,
                "payload_offset": payload_offset,
                "subchunk_id": ascii_chunk_id(subchunk_id),
            }
        )
    return {
        "process_proc": "Image::ExifTool::RIFF::ProcessChunks",
        "source_table": "Image::ExifTool::RIFF::Tdat",
        "subchunks": subchunks,
        "unsupported_reason": "tdat_table_has_no_source_backed_scalar_tag_definitions",
    }


def associated_data_list_tags(
    riff_data: bytes, chunk: RiffChunkPlan
) -> tuple[tuple[RiffReadTag, ...], str, JsonObject]:
    tags: list[RiffReadTag] = []
    supported_subchunks: JsonArray = []
    unsupported_subchunks: JsonArray = []
    offset = chunk.payload_body_offset
    limit = chunk.payload_offset + chunk.payload_length
    stopped_on_truncated_subchunk = False
    while offset + RIFF_CHUNK_HEADER_SIZE <= limit:
        subchunk_id = riff_data[offset : offset + 4]
        payload_length = uint32(riff_data, offset + 4)
        payload_offset = offset + RIFF_CHUNK_HEADER_SIZE
        payload_end = payload_offset + payload_length
        subchunk_name = ascii_chunk_id(subchunk_id)
        if payload_end > limit:
            unsupported_subchunks.append(
                {
                    "available_payload_length": max(0, limit - payload_offset),
                    "declared_payload_length": payload_length,
                    "subchunk_id": subchunk_name,
                    "unsupported_reason": "truncated_subchunk_payload",
                }
            )
            stopped_on_truncated_subchunk = True
            break
        payload = riff_data[payload_offset:payload_end]
        tag_name = RIFF_ASSOCIATED_DATA_TAGS.get(subchunk_id)
        if tag_name is None:
            unsupported_subchunks.append(
                {
                    "payload_length": payload_length,
                    "subchunk_id": subchunk_name,
                    "unsupported_reason": "not_defined_in_Image::ExifTool::RIFF::Main_adtl",
                }
            )
        else:
            parsed = associated_data_value(subchunk_id, payload)
            if parsed is None:
                unsupported_subchunks.append(
                    {
                        "payload_length": payload_length,
                        "subchunk_id": subchunk_name,
                        "tag_name": tag_name,
                        "unsupported_reason": "payload_shorter_than_source_valueconv_layout",
                    }
                )
            else:
                tags.append(
                    read_tag(
                        tag_name,
                        "RIFF",
                        "Image::ExifTool::RIFF::Main",
                        subchunk_name,
                        parsed,
                        parsed,
                        chunk.effective_id,
                        chunk.index,
                        payload_offset,
                        (RIFF_ASSOCIATED_DATA_LIST_SOURCE,),
                    )
                )
                supported_subchunks.append(
                    {
                        "payload_length": payload_length,
                        "payload_offset": payload_offset,
                        "subchunk_id": subchunk_name,
                        "tag_name": tag_name,
                    }
                )
        offset = payload_end + (payload_length & 1)
    if offset < limit and not stopped_on_truncated_subchunk:
        unsupported_subchunks.append(
            {
                "available_header_bytes": limit - offset,
                "unsupported_reason": "trailing_partial_subchunk_header",
            }
        )
    details: JsonObject = {
        "process_proc": "Image::ExifTool::RIFF::ProcessChunks",
        "source_table": "Image::ExifTool::RIFF::Main",
        "supported_subchunks": supported_subchunks,
        "unsupported_subchunks": unsupported_subchunks,
    }
    if tags and unsupported_subchunks:
        detail = "extracted source-backed RIFF associated-data cue text; unsupported: " + "; ".join(
            associated_data_unsupported_detail(item) for item in unsupported_subchunks
        )
    elif tags:
        detail = "extracted source-backed RIFF associated-data cue text."
    elif unsupported_subchunks:
        detail = (
            "no source-backed RIFF associated-data cue text extracted; unsupported: "
            + "; ".join(associated_data_unsupported_detail(item) for item in unsupported_subchunks)
        )
    else:
        detail = "LIST_adtl contained no associated-data subchunks."
    return tuple(tags), detail, details


def associated_data_value(subchunk_id: bytes, payload: bytes) -> str | None:
    if subchunk_id in {b"labl", b"note"}:
        if len(payload) < 4:
            return None
        cue_point_id = uint32(payload, 0)
        text = payload[4:].rstrip(b"\x00").decode("latin-1")
        return f"{cue_point_id} {text}"
    if subchunk_id == b"ltxt":
        if len(payload) < 18:
            return None
        cue_point_id = uint32(payload, 0)
        sample_length = uint32(payload, 4)
        purpose = payload[8:12].decode("latin-1")
        country = uint16(payload, 12)
        language = uint16(payload, 14)
        dialect = uint16(payload, 16)
        codepage = uint16(payload, 18) if len(payload) >= 20 else 0
        text = payload[18:].rstrip(b"\x00").decode("latin-1")
        return (
            f"{cue_point_id} {sample_length} '{purpose}' "
            f"{country} {language} {dialect} {codepage} {text}"
        )
    return None


def associated_data_unsupported_detail(item: JsonValue) -> str:
    if not isinstance(item, dict):
        return "unknown unsupported associated-data subchunk"
    reason = item.get("unsupported_reason")
    subchunk_id = item.get("subchunk_id")
    if reason == "truncated_subchunk_payload" and isinstance(subchunk_id, str):
        declared = item.get("declared_payload_length")
        available = item.get("available_payload_length")
        if isinstance(declared, int) and isinstance(available, int):
            return f"{subchunk_id} declares {declared} bytes with only {available} available"
    if reason == "payload_shorter_than_source_valueconv_layout" and isinstance(subchunk_id, str):
        return f"{subchunk_id} payload shorter than source ValueConv layout"
    if reason == "not_defined_in_Image::ExifTool::RIFF::Main_adtl" and isinstance(subchunk_id, str):
        return f"{subchunk_id} subchunk"
    if reason == "trailing_partial_subchunk_header":
        available_header_bytes = item.get("available_header_bytes")
        if isinstance(available_header_bytes, int):
            return f"trailing {available_header_bytes} byte partial subchunk header"
    return (
        str(reason) if isinstance(reason, str) else "unknown unsupported associated-data subchunk"
    )


def pentax_avi_makernote_subchunk_detail(
    subchunk_id: str,
    payload_offset: int,
    payload_length: int,
) -> JsonObject:
    maker_note_payload_length = max(0, payload_length - PENTAX_AVI_MAKERNOTE_START)
    detail: JsonObject = {
        "base": "$start",
        "byte_order": PENTAX_AVI_MAKERNOTE_BYTE_ORDER,
        "maker_note_payload_length": maker_note_payload_length,
        "maker_note_payload_offset": payload_offset + PENTAX_AVI_MAKERNOTE_START,
        "payload_length": payload_length,
        "payload_offset": payload_offset,
        "start": PENTAX_AVI_MAKERNOTE_START,
        "subchunk_id": subchunk_id,
        "tag_name": "MakerNotes",
        "target_table": PENTAX_AVI_MAKERNOTE_TABLE,
    }
    if payload_length < PENTAX_AVI_MAKERNOTE_START:
        detail["unsupported_reason"] = "maker_note_payload_shorter_than_start_10"
    return detail


def pentax_avi_route_facts(maker_note_subchunks: JsonArray) -> str:
    subchunk_ids: list[str] = []
    for item in maker_note_subchunks:
        if not isinstance(item, dict):
            continue
        subchunk_id = item.get("subchunk_id")
        if isinstance(subchunk_id, str):
            subchunk_ids.append(subchunk_id)
    if not subchunk_ids:
        return (
            "no hymn/mknt MakerNotes subchunk was available for the "
            f"{PENTAX_AVI_MAKERNOTE_TABLE} Start 10, Base $start, ByteOrder Unknown handoff."
        )
    return (
        f"{', '.join(subchunk_ids)} routes MakerNotes to {PENTAX_AVI_MAKERNOTE_TABLE} "
        "with Start 10, Base $start, ByteOrder Unknown."
    )


def pentax_avi_unsupported_detail(item: JsonValue) -> str:
    if not isinstance(item, dict):
        return "unknown unsupported Pentax AVI subchunk"
    reason = item.get("unsupported_reason")
    subchunk_id = item.get("subchunk_id")
    if reason == "maker_note_payload_shorter_than_start_10" and isinstance(subchunk_id, str):
        payload_length = item.get("payload_length")
        if isinstance(payload_length, int):
            return (
                f"{subchunk_id} MakerNotes payload shorter than Start 10 ({payload_length} bytes)"
            )
    if reason == "truncated_subchunk_payload" and isinstance(subchunk_id, str):
        declared = item.get("declared_payload_length")
        available = item.get("available_payload_length")
        if isinstance(declared, int) and isinstance(available, int):
            return f"{subchunk_id} declares {declared} bytes with only {available} available"
    if reason == "not_defined_in_Image::ExifTool::Pentax::AVI" and isinstance(subchunk_id, str):
        return f"{subchunk_id} subchunk"
    if reason == "trailing_partial_subchunk_header":
        available_header_bytes = item.get("available_header_bytes")
        if isinstance(available_header_bytes, int):
            return f"trailing {available_header_bytes} byte partial subchunk header"
    return str(reason) if isinstance(reason, str) else "unknown unsupported Pentax AVI subchunk"


def nikon_avi_list_tags(
    riff_data: bytes,
    chunk: RiffChunkPlan,
    *,
    include_hidden_unknowns: bool = False,
) -> tuple[tuple[RiffReadTag, ...], str]:
    tags: list[RiffReadTag] = []
    unsupported: list[str] = []
    saw_supported_directory = False
    for subchunk_id, payload_offset, payload_length in iter_list_subchunks(riff_data, chunk):
        payload = riff_data[payload_offset : payload_offset + payload_length]
        if subchunk_id == b"nctg":
            saw_supported_directory = True
            record_tags, record_unsupported = nikon_avi_record_tags(
                payload,
                chunk,
                payload_offset,
                NIKON_AVI_TAG_RECORDS,
                NIKON_AVI_TAG_TABLE,
                include_hidden_unknowns=include_hidden_unknowns,
            )
            tags.extend(record_tags)
            unsupported.extend(f"nctg {item}" for item in record_unsupported)
        elif subchunk_id == b"ncvr":
            saw_supported_directory = True
            record_tags, record_unsupported = nikon_avi_record_tags(
                payload,
                chunk,
                payload_offset,
                NIKON_AVI_VERS_RECORDS,
                NIKON_AVI_VERSION_TABLE,
                include_hidden_unknowns=include_hidden_unknowns,
            )
            tags.extend(record_tags)
            unsupported.extend(f"ncvr {item}" for item in record_unsupported)
        elif subchunk_id in {b"ncth", b"ncvw"}:
            name = "ThumbnailImage" if subchunk_id == b"ncth" else "PreviewImage"
            unsupported.append(f"{ascii_chunk_id(subchunk_id)} binary {name}")
        else:
            unsupported.append(f"{ascii_chunk_id(subchunk_id)} subchunk")
    if tags and unsupported:
        return (
            tuple(tags),
            "extracted supported Nikon AVI scalar records; unsupported: " + "; ".join(unsupported),
        )
    if tags:
        return tuple(tags), "extracted supported Nikon AVI scalar records from nctg/ncvr."
    if unsupported:
        return (), "no supported Nikon AVI scalar records; unsupported: " + "; ".join(unsupported)
    if saw_supported_directory:
        return (), "Nikon AVI nctg/ncvr directories contained no complete supported records."
    return (), "LIST_ncdt did not contain Nikon AVI nctg or ncvr directories."


def nikon_avi_record_tags(
    payload: bytes,
    parent_chunk: RiffChunkPlan,
    payload_offset: int,
    records: dict[int, NikonAVIRecordDef],
    source_table: str,
    *,
    include_hidden_unknowns: bool = False,
) -> tuple[tuple[RiffReadTag, ...], tuple[str, ...]]:
    tags: list[RiffReadTag] = []
    unsupported: list[str] = []
    pos = 0
    stopped_on_truncated_record = False
    while pos + 4 <= len(payload):
        tag_id = uint16(payload, pos)
        size = uint16(payload, pos + 2)
        record_start = pos + 4
        record_end = record_start + size
        tag_label = f"record 0x{tag_id:04x}"
        if record_end > len(payload):
            unsupported.append(
                f"{tag_label} declares {size} bytes "
                f"with only {len(payload) - record_start} available"
            )
            stopped_on_truncated_record = True
            break
        record_def = records.get(tag_id)
        record_payload = payload[record_start:record_end]
        if record_def is None:
            unsupported.append(f"{tag_label} unknown")
        elif record_def.hidden_unknown and not include_hidden_unknowns:
            unsupported.append(f"{tag_label} hidden unknown {record_def.name}")
        else:
            parsed = nikon_avi_parse_record_value(record_payload, record_def)
            if parsed is None:
                unsupported.append(
                    f"{tag_label} {record_def.name} malformed for {record_def.format}"
                )
            else:
                raw_value, rendered_value = parsed
                tags.append(
                    read_tag(
                        record_def.name,
                        record_def.group,
                        source_table,
                        f"0x{tag_id:04x}",
                        raw_value,
                        rendered_value,
                        parent_chunk.effective_id,
                        parent_chunk.index,
                        payload_offset + record_start,
                        NIKON_AVI_TABLE_SOURCES,
                    )
                )
        pos = record_end
    if pos < len(payload) and not stopped_on_truncated_record:
        unsupported.append(f"trailing {len(payload) - pos} byte partial record header")
    return tuple(tags), tuple(unsupported)


def nikon_avi_parse_record_value(
    payload: bytes, record_def: NikonAVIRecordDef
) -> tuple[RiffTagValue, RiffRenderedValue] | None:
    match record_def.format:
        case "string":
            raw_value: RiffTagValue = ascii_string(payload)
        case "undef":
            value = payload.decode("latin-1")
            raw_value = value.replace("\x00", "") if record_def.null_strip else value
        case "int8u":
            values = tuple(payload)
            raw_value = values[0] if len(values) == 1 else values
        case "int16u":
            if len(payload) != 2:
                return None
            raw_value = uint16(payload, 0)
        case "int32s":
            if len(payload) != 4:
                return None
            raw_value = int32(payload, 0)
        case "rational64u":
            if len(payload) != 8:
                return None
            denominator = uint32(payload, 4)
            raw_value = None if denominator == 0 else uint32(payload, 0) / denominator
        case "rational64s":
            if len(payload) != 8:
                return None
            denominator = int32(payload, 4)
            raw_value = None if denominator == 0 else int32(payload, 0) / denominator
    rendered_value = nikon_avi_rendered_value(raw_value, record_def)
    return raw_value, rendered_value


def nikon_avi_rendered_value(
    raw_value: RiffTagValue, record_def: NikonAVIRecordDef
) -> RiffRenderedValue:
    value: RiffTagValue = raw_value
    if record_def.value_conv == "reverse_dot" and isinstance(raw_value, tuple):
        return ".".join(str(item) for item in reversed(raw_value))
    if record_def.value_conv == "apex_aperture" and isinstance(raw_value, (int, float)):
        value = 2 ** (raw_value / 2)
    if record_def.print_conv == "orientation" and isinstance(value, int):
        return {
            1: "Horizontal (normal)",
            2: "Mirror horizontal",
            3: "Rotate 180",
            4: "Mirror vertical",
            5: "Mirror horizontal and rotate 270 CW",
            6: "Rotate 90 CW",
            7: "Mirror horizontal and rotate 90 CW",
            8: "Rotate 270 CW",
        }.get(value, str(value))
    if record_def.print_conv == "exposure_time" and isinstance(value, (int, float)):
        return f"1/{round(1 / value):g}" if 0 < value < 0.5 else f"{value:g}"
    if record_def.print_conv == "one_decimal" and isinstance(value, (int, float)):
        return f"{value:.1f}"
    if record_def.print_conv == "fraction" and isinstance(value, (int, float)):
        return f"{value:g}"
    if record_def.print_conv == "focal_length" and isinstance(value, (int, float)):
        return f"{value:.1f} mm"
    if record_def.print_conv == "metering_mode" and isinstance(value, int):
        return {
            0: "Unknown",
            1: "Average",
            2: "Center-weighted average",
            3: "Spot",
            4: "Multi-spot",
            5: "Multi-segment",
            6: "Partial",
            255: "Other",
        }.get(value, str(value))
    if record_def.print_conv == "resolution_unit" and isinstance(value, int):
        return {1: "None", 2: "inches", 3: "cm"}.get(value, str(value))
    if record_def.print_conv == "datetime" and isinstance(value, str):
        return value.replace("-", ":", 2)
    if record_def.print_conv == "seconds" and isinstance(value, (int, float)):
        return f"{value:g} s"
    return riff_rendered_value_from_tag_value(value)


def webp_exif_tiff_payload(payload: bytes) -> bytes | None:
    if payload.startswith((b"II\x2a\x00", b"MM\x00\x2a")):
        return payload
    if payload.startswith((b"Exif\x00\x00II\x2a\x00", b"Exif\x00\x00MM\x00\x2a")):
        return payload[6:]
    return None


def exif_nested_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    byte_order = exif_byte_order_tag(chunk, payload)
    if byte_order is not None:
        tags.append(byte_order)
    for group, values in exif_group_values(payload):
        for name, value in values.items():
            tag_value = riff_tag_value_from_json(value)
            if tag_value is None and value is not None:
                continue
            tags.append(
                chunk_read_tag(
                    name,
                    group,
                    "Image::ExifTool::Exif::Main",
                    EXIF_TAG_IDS.get(name, name),
                    tag_value,
                    riff_rendered_value_from_tag_value(tag_value),
                    chunk,
                    0,
                    (RIFF_NESTED_METADATA_SOURCE,),
                )
            )
    return tuple(tags)


def exif_byte_order_tag(chunk: RiffChunkPlan, payload: bytes) -> RiffReadTag | None:
    try:
        header = parse_tiff_header(payload)
    except ValueError:
        return None
    marker = "MM" if header.endian == "big" else "II"
    return chunk_read_tag(
        "ExifByteOrder",
        "File",
        "Image::ExifTool::Exif::Main",
        "ExifByteOrder",
        marker,
        header.byte_order,
        chunk,
        0,
        (RIFF_NESTED_METADATA_SOURCE, RIFF_EXIF_BYTE_ORDER_SOURCE),
    )


def exif_group_values(payload: bytes) -> tuple[tuple[str, JsonObject], ...]:
    groups: list[tuple[str, JsonObject]] = []
    try:
        ifd0_values = read_ifd0_values(payload)
    except ValueError:
        ifd0_values = {}
    groups.append(("IFD0", ifd0_values))
    try:
        exif_values = read_exif_ifd_values(payload)
    except ValueError:
        exif_values = {}
    groups.append(("ExifIFD", exif_values))
    try:
        gps_values = read_gps_ifd_values(payload)
    except ValueError:
        gps_values = {}
    groups.append(("GPS", gps_values))
    return tuple(groups)


def xmp_nested_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    from exifmodern.formats.xmp.reader import parse_xmp_packet

    try:
        values_by_group = parse_xmp_packet(payload)
    except ValueError, SyntaxError:
        return ()
    tags: list[RiffReadTag] = []
    for group, values in values_by_group.items():
        for name, value in values.items():
            tag_value = riff_tag_value_from_json(value)
            if tag_value is None and value is not None:
                continue
            tags.append(
                chunk_read_tag(
                    name,
                    group,
                    xmp_source_table(group),
                    xmp_tag_id(name),
                    tag_value,
                    riff_rendered_value_from_tag_value(tag_value),
                    chunk,
                    0,
                    (RIFF_NESTED_METADATA_SOURCE,),
                )
            )
    return tuple(tags)


def xmp_source_table(group: str) -> str:
    return XMP_GROUP_SOURCE_TABLES.get(group, "Image::ExifTool::XMP::Main")


def xmp_tag_id(name: str) -> str:
    return XMP_TAG_IDS.get(name, name[0].lower() + name[1:] if name else name)


def icc_nested_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    from exifmodern.formats.icc.reader import parse_icc_header_tags, parse_icc_profile_tags

    tags: list[RiffReadTag] = []
    try:
        values = {**parse_icc_header_tags(payload), **parse_icc_profile_tags(payload)}
    except ValueError:
        return ()
    for name, value in values.items():
        tag_value = riff_tag_value_from_json(value)
        if tag_value is None and value is not None:
            continue
        source_table = "Image::ExifTool::ICC_Profile::Header"
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
            source_table = "Image::ExifTool::ICC_Profile::Main"
        tags.append(
            chunk_read_tag(
                name,
                "ICC_Profile",
                source_table,
                name,
                tag_value,
                riff_rendered_value_from_tag_value(tag_value),
                chunk,
                0,
                (RIFF_NESTED_METADATA_SOURCE,),
            )
        )
    return tuple(tags)


def c2pa_jumbf_nested_tags(chunk: RiffChunkPlan, payload: bytes) -> tuple[RiffReadTag, ...]:
    from exifmodern.formats.jumbf.reader import collect_jumbf_box_tags, read_boxes

    jumbf_values: JsonObject = {}
    json_values: JsonObject = {}
    for box in read_boxes(payload):
        collect_jumbf_box_tags(box, jumbf_values, json_values, record_jumd=True)
    tags: list[RiffReadTag] = []
    tags.extend(
        jumbf_group_tags(
            chunk,
            "JUMBF",
            "Image::ExifTool::Jpeg2000::JUMD",
            RIFF_JUMBF_TAG_IDS,
            jumbf_values,
        )
    )
    tags.extend(
        jumbf_group_tags(
            chunk,
            "JSON",
            "Image::ExifTool::JSON::Main",
            RIFF_JUMBF_JSON_TAG_IDS,
            json_values,
        )
    )
    return tuple(tags)


def jumbf_group_tags(
    chunk: RiffChunkPlan,
    group: str,
    source_table: str,
    tag_ids: dict[str, str],
    values: JsonObject,
) -> tuple[RiffReadTag, ...]:
    tags: list[RiffReadTag] = []
    for name, value in values.items():
        tag_value = riff_tag_value_from_json(value)
        if tag_value is None and value is not None:
            continue
        tags.append(
            chunk_read_tag(
                name,
                group,
                source_table,
                tag_ids.get(name, name),
                tag_value,
                riff_rendered_value_from_tag_value(tag_value),
                chunk,
                0,
                (RIFF_NESTED_METADATA_SOURCE, RIFF_C2PA_JUMBF_SOURCE),
            )
        )
    return tuple(tags)


def nested_route(
    chunk: RiffChunkPlan,
    target_table: str,
    payload_kind: str,
    status: RiffNestedRouteStatus,
    detail: str,
    extracted_tag_count: int,
    evidence_ids: tuple[str, ...] = (RIFF_NESTED_METADATA_SOURCE,),
    route_details: JsonObject | None = None,
) -> RiffNestedMetadataRoute:
    return RiffNestedMetadataRoute(
        chunk_id=chunk.effective_id,
        chunk_index=chunk.index,
        byte_offset=chunk.payload_offset,
        payload_length=chunk.payload_body_length,
        target_table=target_table,
        payload_kind=payload_kind,
        status=status,
        detail=detail,
        extracted_tag_count=extracted_tag_count,
        evidence_ids=evidence_ids,
        route_details={} if route_details is None else route_details,
    )


def audio_uint_tag(
    name: str,
    tag_id: str,
    value: int,
    chunk: RiffChunkPlan,
    offset: int,
) -> RiffReadTag:
    return chunk_read_tag(
        name,
        "Audio",
        "Image::ExifTool::RIFF::AudioFormat",
        tag_id,
        value,
        value,
        chunk,
        offset,
        (RIFF_AUDIO_FORMAT_SOURCE,),
    )


def avi_int_tag(
    name: str,
    tag_id: str,
    value: int,
    chunk: RiffChunkPlan,
    offset: int,
) -> RiffReadTag:
    return avi_tag(name, tag_id, value, value, chunk, offset)


def avi_tag(
    name: str,
    tag_id: str,
    raw_value: RiffTagValue,
    rendered_value: RiffRenderedValue,
    chunk: RiffChunkPlan,
    absolute_offset: int,
) -> RiffReadTag:
    return read_tag(
        name,
        "Video",
        "Image::ExifTool::RIFF::AVIHeader",
        tag_id,
        raw_value,
        rendered_value,
        "avih",
        chunk.index,
        absolute_offset,
        (RIFF_AVI_HEADER_SOURCE,),
    )


def chunk_read_tag(
    name: str,
    group: str,
    source_table: str,
    tag_id: str,
    raw_value: RiffTagValue,
    rendered_value: RiffRenderedValue,
    chunk: RiffChunkPlan,
    offset: int,
    sources: tuple[str, ...],
) -> RiffReadTag:
    return read_tag(
        name,
        group,
        source_table,
        tag_id,
        raw_value,
        rendered_value,
        ascii_chunk_id(chunk.chunk_id),
        chunk.index,
        chunk.payload_offset + offset,
        sources,
    )


def read_tag(
    name: str,
    group: str,
    source_table: str,
    tag_id: str,
    raw_value: RiffTagValue,
    rendered_value: RiffRenderedValue,
    chunk_id: str,
    chunk_index: int | None,
    byte_offset: int,
    sources: tuple[str, ...],
) -> RiffReadTag:
    return RiffReadTag(
        name=name,
        group=group,
        source_table=source_table,
        tag_id=tag_id,
        raw_value=raw_value,
        rendered_value=rendered_value,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        byte_offset=byte_offset,
        evidence_ids=sources,
    )


def rational_inverse(payload: bytes, offset: int) -> float | None:
    scale = uint32(payload, offset)
    rate = uint32(payload, offset + 4)
    if scale == 0:
        return None
    return rate / scale


def byte_rate(value: int) -> str:
    unit = "kB/s"
    scaled = value / 1000
    if scaled > 9999:
        scaled /= 1000
        unit = "MB/s"
    return f"{scaled:.4g} {unit}"


def exiftool_file_size(size_bytes: int) -> str:
    if size_bytes < 2000:
        return f"{size_bytes} bytes"
    if size_bytes < 10000:
        return f"{size_bytes / 1000:.1f} kB"
    if size_bytes < 2_000_000:
        return f"{size_bytes / 1000:.0f} kB"
    if size_bytes < 10_000_000:
        return f"{size_bytes / 1_000_000:.1f} MB"
    if size_bytes < 2_000_000_000:
        return f"{size_bytes / 1_000_000:.0f} MB"
    if size_bytes < 10_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f} GB"
    return f"{size_bytes / 1_000_000_000:.0f} GB"
