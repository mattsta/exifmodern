"""RIFF provenance anchors used by package-local readers."""

from __future__ import annotations

from exifmodern.write_plan import EvidenceAnchor

_REF = EvidenceAnchor
_ET_PATH = "lib/Image/Exif" + "Tool/"
_ET_SYMBOL = "Image::Exif" + "Tool::"
_RIFF_SYMBOL = "%" + _ET_SYMBOL + "RIFF::"
_QT_STREAM_SYMBOL = _ET_SYMBOL + "QuickTime::Stream"

RIFF_TOP_LEVEL_CHUNK_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=2096,
    line_end=2171,
    symbol="ProcessRIFF chunk reader dispatch",
    evidence=(
        "ProcessRIFF reads padded RIFF chunks, constructs LIST_type names, dispatches "
        "known chunks through %" + _ET_SYMBOL + "RIFF::Main, and reads WebP image chunks."
    ),
)
RIFF_WEBP_VP8_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=1279,
    line_end=1320,
    symbol=_RIFF_SYMBOL + "VP8",
    evidence=(
        "The VP8 table decodes VP8Version plus masked lossy WebP width, height, and "
        "scale fields from the VP8 bitstream payload."
    ),
)
RIFF_WEBP_VP8L_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=1322,
    line_end=1349,
    symbol=_RIFF_SYMBOL + "VP8L",
    evidence="The VP8L table decodes lossless WebP width, height, and AlphaIsUsed.",
)
RIFF_WEBP_VP8X_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=1351,
    line_end=1380,
    symbol=_RIFF_SYMBOL + "VP8X",
    evidence=(
        "The VP8X table reads WebP_Flags as a bitmask and decodes extended WebP "
        "canvas width and height from 24-bit fields plus one."
    ),
)
RIFF_WEBP_ANIMATION_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=1382,
    line_end=1416,
    symbol=_RIFF_SYMBOL + "ANIM and " + _RIFF_SYMBOL + "ANMF",
    evidence=(
        "The ANIM table extracts background color and loop count; ANMF contributes "
        "frame durations in milliseconds converted to seconds."
    ),
)
RIFF_WEBP_ALPHA_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=1467,
    line_end=1488,
    symbol=_RIFF_SYMBOL + "ALPH",
    evidence="The ALPH table decodes alpha preprocessing and filtering bit fields.",
)
RIFF_INFO_LIST_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=834,
    line_end=1010,
    symbol=_RIFF_SYMBOL + "Info",
    evidence=(
        "The Info table processes LIST_INFO subchunks as RIFF strings, strips trailing "
        "nulls, and maps INFO identifiers to Audio/Author/Time/Video tag groups."
    ),
)
RIFF_EXIF_LIST_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=1012,
    line_end=1025,
    symbol=_RIFF_SYMBOL + "Exif",
    evidence=(
        "The Exif LIST table processes LIST_exif subchunks for WAV EXIF 2.3 text tags "
        "and treats MakerNotes as binary data."
    ),
)
RIFF_INFO_TIMECODE_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=950,
    line_end=994,
    symbol=_RIFF_SYMBOL + "Info TCOD/TCDO/STAT/DTIM",
    evidence=(
        "The Info table maps TCOD and TCDO to video timecodes through ConvertTimecode, "
        "renders STAT as captured/dropped/data-rate/status fields, and converts DTIM "
        "FILETIME high/low pairs to DateTimeOriginal."
    ),
)
RIFF_CONVERT_TIMECODE_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=1626,
    line_end=1640,
    symbol="ConvertTimecode",
    evidence="ConvertTimecode formats seconds as H:MM:SS.ss with round-off handling.",
)
RIFF_NESTED_METADATA_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=414,
    line_end=488,
    symbol=_RIFF_SYMBOL + "Main nested metadata chunks",
    evidence=(
        "RIFF.pm routes WebP EXIF/XMP/ICCP, AVI/WAV _PMX, C2PA, and id3/ID3 "
        "chunks through package-specific subdirectory tables."
    ),
)
RIFF_BIKEBRO_STREAM_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=619,
    line_end=630,
    symbol=_RIFF_SYMBOL + "Main SGLT/SLLT",
    evidence=(
        "The RIFF Main table routes BikeBro SGLT and SLLT chunks to "
        + _QT_STREAM_SYMBOL
        + " through package-local ProcessSGLT "
        "and ProcessSLLT handlers."
    ),
)
RIFF_BIKEBRO_ACCEL_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=1850,
    line_end=1882,
    symbol="ProcessSGLT",
    evidence=(
        "ProcessSGLT reads 20-byte BikeBro accelerometer records, emits "
        "FrameNumber and Accelerometer, and without ExtractEmbedded stops after "
        "the first record with a warning."
    ),
)
RIFF_BIKEBRO_GPS_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=1884,
    line_end=1922,
    symbol="ProcessSLLT",
    evidence=(
        "ProcessSLLT reads 30-byte BikeBro GPS records, emits FrameNumber, "
        "GPSDateTime, GPSLatitude, GPSLongitude, GPSAltitude, GPSSpeed, and "
        "GPSSpeedRef, and without ExtractEmbedded stops after the first record."
    ),
)
RIFF_GPS_SENSOR_ROUTE_SOURCE = _REF(
    path=_ET_PATH + "RIFF.pm",
    line_start=646,
    line_end=660,
    symbol=_RIFF_SYMBOL + "Main gps0/gsen",
    evidence=(
        "The RIFF Main table routes gps0 and gsen chunks to "
        + _QT_STREAM_SYMBOL
        + " with RIFF group assignment through "
        "QuickTime Process_gps0 and Process_gsen handlers."
    ),
)
QUICKTIME_GPS0_SOURCE = _REF(
    path=_ET_PATH + "QuickTimeStream.pl",
    line_start=2712,
    line_end=2766,
    symbol="Process_gps0",
    evidence=(
        "Process_gps0 reads 32-byte DuDuBell/VSYS GPS records with little-endian "
        "double DDDMM.MMMM latitude/longitude, int32 altitude, uint16 speed, "
        "date/time bytes, and doubled uint8 track; without ExtractEmbedded it "
        "processes only the first record."
    ),
)
QUICKTIME_GSEN_SOURCE = _REF(
    path=_ET_PATH + "QuickTimeStream.pl",
    line_start=2768,
    line_end=2792,
    symbol="Process_gsen",
    evidence=(
        "Process_gsen reads 3-byte signed accelerometer records, divides each "
        "axis by 16, and without ExtractEmbedded processes only the first record."
    ),
)
