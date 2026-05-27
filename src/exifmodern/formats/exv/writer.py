"""Source-backed EXV/JPEG segment writer primitives.

These helpers own the EXV stream wrapper and JPEG-style segment framing proven
by ExifTool. They can wrap already-materialized EXIF TIFF payload bytes, but
they do not synthesize EXIF/TIFF directories or project tag values.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import md5
from pathlib import Path
from typing import Literal

from exifmodern.exif_scalar_write_plan import ExifScalarWritePlan
from exifmodern.formats.app12.segment_transaction_plan import (
    App12DuckyTagName,
    App12DuckyValue,
    App12SegmentRewriteRequest,
    build_app12_segment_transaction_plan,
)
from exifmodern.formats.exif_sidecar.copy_from_file_plan import (
    source_backed_exif_tiff_payload,
)
from exifmodern.formats.icc.materializer import materialize_source_icc_profile
from exifmodern.formats.iptc.write_plan import IptcApplicationWritePlan
from exifmodern.formats.jpeg.app_segments.xmp import XMP_APP1_PREFIX, XMP_EXTENDED_APP1_PREFIX
from exifmodern.formats.jpeg.container import (
    JpegSegmentProbe,
    read_jpeg_segment_probes,
    scan_jpeg_segments,
)
from exifmodern.formats.jpeg.iptc_app13_writer import (
    rewrite_jpeg_iptc_application_creating_if_needed,
)
from exifmodern.formats.photoshop.app13_resource_writer import (
    PhotoshopApp13ResourceWritePlan,
    create_photoshop_app13_resource_section,
    rewrite_photoshop_app13_resource_section,
)
from exifmodern.formats.photoshop.reader import PHOTOSHOP_APP13_PREFIX
from exifmodern.formats.tiff.exif_scalar_rewriter import rewrite_exif_scalars_creating_if_needed
from exifmodern.formats.tiff.primitives import parse_tiff_header
from exifmodern.formats.xmp.packet import empty_xmp_packet
from exifmodern.formats.xmp.property_write import XmpPropertyWritePlan
from exifmodern.formats.xmp.sidecar_writer import rewrite_xmp_sidecar_properties
from exifmodern.media_source import FileMediaSource

EXV_SIGNATURE = b"\xff\x01Exiv2"
EXV_EOI = b"\xff\xd9"
EXIF_APP1_HEADER = b"Exif\x00\x00"
ICC_APP2_HEADER = b"ICC_PROFILE\x00"
MAX_JPEG_SEGMENT_DATA_LENGTH = 0xFFFD
JPEG_SEGMENT_LENGTH_SIZE = 2
XMP_EXTENDED_CHUNK_HEADER_LENGTH = len(XMP_EXTENDED_APP1_PREFIX) + 32 + 4 + 4

type ExvMultiSegmentKind = Literal["generic", "exif", "icc"]
type ExvDuckyAssignment = tuple[App12DuckyTagName, str]
type ExvSourceMetadataGroup = Literal[
    "EXIF",
    "Photoshop",
    "XMP",
    "ICC_Profile",
    "Comment",
    "JFIF",
    "JFXX",
    "CIFF",
    "FlashPix",
    "MPF",
    "Meta",
    "RMETA",
    "SEAL",
    "AROT",
    "JUMBF",
    "Ducky",
    "Adobe",
]


@dataclass(frozen=True)
class ExvSegment:
    marker: int
    payload: bytes


@dataclass(frozen=True)
class ExvParseResult:
    segments: tuple[ExvSegment, ...]
    eoi_offset: int
    ignored_trailer: bytes


def encode_exv_stream(segments: tuple[ExvSegment, ...]) -> bytes:
    """Encode an EXV stream from already-materialized JPEG-family segments."""

    encoded_segments = b"".join(
        encode_exv_segment(segment.marker, segment.payload) for segment in segments
    )
    return EXV_SIGNATURE + encoded_segments + EXV_EOI


def materialize_exv_from_exif_tiff_payload(tiff_payload: bytes) -> bytes:
    """Materialize minimal EXV selected output from owned EXIF TIFF bytes."""

    parse_tiff_header(tiff_payload)
    segments = encode_exv_multi_segments(
        marker=0xE1,
        header=EXIF_APP1_HEADER,
        payload=tiff_payload,
        kind="exif",
    )
    return encode_exv_stream(segments)


def materialize_exv_from_source_exif(source_path: Path) -> bytes:
    """Materialize EXV selected output by wrapping source-backed EXIF TIFF bytes."""

    tiff_payload, _materialization = source_backed_exif_tiff_payload(source_path)
    return materialize_exv_from_exif_tiff_payload(tiff_payload)


def materialize_exv_from_source_exif_with_scalar_plan(
    source_path: Path,
    plan: ExifScalarWritePlan,
) -> bytes:
    """Materialize EXV by mutating source EXIF TIFF bytes with owned scalar primitives."""

    tiff_payload, _materialization = source_backed_exif_tiff_payload(source_path)
    rewritten_tiff = rewrite_exif_scalars_creating_if_needed(tiff_payload, plan)
    return materialize_exv_from_exif_tiff_payload(rewritten_tiff)


def materialize_exv_from_source_iptc_application_plan(
    source_path: Path,
    plan: IptcApplicationWritePlan,
) -> bytes:
    """Materialize EXV APP13 bytes via the owned JPEG IPTC APP13 writer."""

    rewritten = rewrite_jpeg_iptc_application_creating_if_needed(source_path.read_bytes(), plan)
    segments = _source_photoshop_app13_segments_from_bytes(rewritten.data)
    if not segments:
        raise ValueError(f"No generated Photoshop APP13 payload found: {source_path}")
    return encode_exv_stream(segments)


def materialize_exv_from_source_photoshop_app13_plan(
    source_path: Path,
    plan: PhotoshopApp13ResourceWritePlan,
) -> bytes:
    """Materialize EXV APP13 bytes from source-backed simple Photoshop IRB writes."""

    source_sections = _source_photoshop_app13_resource_sections_from_probes(
        FileMediaSource(source_path),
        read_jpeg_segment_probes_or_empty(source_path),
    )
    if source_sections:
        rewritten_section = rewrite_photoshop_app13_resource_section(source_sections[0], plan)
    else:
        rewritten_section = create_photoshop_app13_resource_section(plan)
    return encode_exv_stream(write_photoshop_app13_segments(rewritten_section))


def materialize_exv_from_generated_xmp_plan(plan: XmpPropertyWritePlan) -> bytes:
    """Materialize EXV APP1 XMP bytes from an owned generated XMP write plan."""

    result = rewrite_xmp_sidecar_properties(empty_xmp_packet(), plan)
    return encode_exv_stream(write_generated_xmp_segments(result.data))


def materialize_exv_from_comment_value(comment: str) -> bytes:
    """Materialize EXV COM bytes from a public Comment assignment."""

    return encode_exv_stream((ExvSegment(marker=0xFE, payload=comment.encode()),))


def materialize_exv_from_source_ducky_assignments(
    source_path: Path,
    assignments: tuple[ExvDuckyAssignment, ...],
) -> bytes:
    """Materialize EXV APP12 Ducky bytes through the owned APP12 WriteDucky planner."""

    if not assignments:
        raise ValueError("missing_ducky_assignment")
    source_payload = _source_ducky_payload_or_empty(source_path)
    existing_plan = None
    if source_payload:
        existing_plan = build_app12_segment_transaction_plan(
            source_payload,
            allow_output_emission=True,
        )
        if not existing_plan.can_emit_output:
            raise ValueError(existing_plan.output_emission_gates[0].code)

    existing_blocks = () if existing_plan is None else existing_plan.ducky_blocks
    existing_tags = {block.tag_name for block in existing_blocks if block.tag_name is not None}
    rewrite_requests = tuple(
        App12SegmentRewriteRequest(
            group="Ducky",
            tag_name=tag_name,
            action="write" if tag_name in existing_tags else "create",
            value=_ducky_assignment_value(tag_name, value),
        )
        for tag_name, value in assignments
    )
    output_plan = build_app12_segment_transaction_plan(
        source_payload,
        rewrite_requests,
        allow_output_emission=True,
    )
    if not output_plan.can_emit_output:
        raise ValueError(output_plan.output_emission_gates[0].code)
    payload = output_plan.emit()
    if payload == b"Ducky":
        raise ValueError("empty_ducky_selected_output")
    return encode_exv_stream((ExvSegment(marker=0xEC, payload=payload),))


def materialize_exv_from_generated_xmp_packets(
    main_xmp_packet: bytes,
    *,
    extended_xmp_packet: bytes | None = None,
    extended_guid: str | None = None,
) -> bytes:
    """Materialize EXV APP1 XMP packet bytes using ExifTool WriteMultiXMP framing."""

    return encode_exv_stream(
        write_multi_xmp_segments(
            main_xmp_packet,
            extended_xmp_packet=extended_xmp_packet,
            extended_guid=extended_guid,
        )
    )


def materialize_exv_from_source_metadata(source_path: Path) -> bytes:
    """Materialize EXV from exact source-backed metadata payloads already owned locally."""

    core_segments = (
        *_source_exif_segments(source_path),
        *_source_photoshop_app13_segments(source_path),
        *_source_jpeg_xmp_segments(source_path),
        *_source_icc_segments(source_path),
        *_source_jpeg_comment_segments(source_path),
    )
    segments = core_segments or _source_jpeg_family_directory_segments(source_path)
    if not segments:
        raise ValueError(
            f"No source-backed EXIF/APP13/XMP/ICC/COM/JPEG-family payload found: {source_path}"
        )
    return encode_exv_stream(segments)


def materialize_exv_from_source_metadata_groups(
    source_path: Path,
    groups: tuple[ExvSourceMetadataGroup, ...],
) -> bytes:
    """Materialize EXV from exact source-backed metadata groups already owned locally."""

    segments: list[ExvSegment] = []
    for group in groups:
        if group == "EXIF":
            segments.extend(_source_exif_segments(source_path))
        elif group == "Photoshop":
            segments.extend(_source_photoshop_app13_segments(source_path))
        elif group == "XMP":
            segments.extend(_source_jpeg_xmp_segments(source_path))
        elif group == "ICC_Profile":
            segments.extend(_source_icc_segments(source_path))
        elif group == "Comment":
            segments.extend(_source_jpeg_comment_segments(source_path))
        elif group in {
            "JFIF",
            "JFXX",
            "CIFF",
            "FlashPix",
            "MPF",
            "Meta",
            "RMETA",
            "SEAL",
            "AROT",
            "JUMBF",
            "Ducky",
            "Adobe",
        }:
            segments.extend(_source_jpeg_family_directory_segments(source_path, group=group))
    if not segments:
        raise ValueError(
            "No source-backed EXIF/APP13/XMP/ICC/COM/JPEG-family payload found "
            "for requested groups: " + ", ".join(groups)
        )
    return encode_exv_stream(tuple(segments))


def _source_exif_segments(source_path: Path) -> tuple[ExvSegment, ...]:
    try:
        tiff_payload, _materialization = source_backed_exif_tiff_payload(source_path)
    except ValueError:
        return ()
    parse_tiff_header(tiff_payload)
    return encode_exv_multi_segments(
        marker=0xE1,
        header=EXIF_APP1_HEADER,
        payload=tiff_payload,
        kind="exif",
    )


def _source_jpeg_xmp_segments(source_path: Path) -> tuple[ExvSegment, ...]:
    source = FileMediaSource(source_path)
    try:
        probes = read_jpeg_segment_probes(
            source_path,
            prefix_length=XMP_EXTENDED_CHUNK_HEADER_LENGTH,
        )
    except ValueError:
        return ()
    segments: list[ExvSegment] = []
    for probe in probes:
        if probe.marker != 0xE1:
            continue
        if probe.payload_prefix.startswith((XMP_APP1_PREFIX, XMP_EXTENDED_APP1_PREFIX)):
            payload = source.read_at(probe.payload_offset, probe.payload_length)
            segments.append(ExvSegment(marker=0xE1, payload=payload))
    return tuple(segments)


def _source_jpeg_family_directory_segments(
    source_path: Path,
    *,
    group: ExvSourceMetadataGroup | None = None,
) -> tuple[ExvSegment, ...]:
    """Project source-backed JPEG directories that need no value-level rewriting."""

    source = FileMediaSource(source_path)
    try:
        probes = read_jpeg_segment_probes(source_path)
    except ValueError:
        return ()
    segments: list[ExvSegment] = []
    for probe in probes:
        if _is_source_backed_jpeg_family_directory_segment(
            probe.marker,
            probe.payload_prefix,
            group,
        ):
            payload = source.read_at(probe.payload_offset, probe.payload_length)
            segments.append(ExvSegment(marker=probe.marker, payload=payload))
    return tuple(segments)


def _is_source_backed_jpeg_family_directory_segment(
    marker: int,
    payload: bytes,
    group: ExvSourceMetadataGroup | None = None,
) -> bool:
    if marker == 0xE0:
        if group == "JFIF":
            return payload.startswith(b"JFIF\x00")
        if group == "JFXX":
            return payload.startswith(b"JFXX\x00\x10")
        if group == "CIFF":
            return _payload_is_ciff(payload)
        return group is None and (
            payload.startswith((b"JFIF\x00", b"JFXX\x00\x10")) or _payload_is_ciff(payload)
        )
    if marker == 0xE2:
        if group == "FlashPix":
            return payload.startswith(b"FPXR\x00")
        if group == "MPF":
            return payload.startswith(b"MPF\x00")
        return group is None and payload.startswith((b"FPXR\x00", b"MPF\x00"))
    if marker == 0xE3:
        return group in {None, "Meta"} and payload.startswith(
            (b"Meta\x00\x00", b"META\x00\x00", b"Exif\x00\x00")
        )
    if marker == 0xE5:
        return group in {None, "RMETA"} and payload.startswith(b"RMETA\x00")
    if marker in {0xE8, 0xE9}:
        return group in {None, "SEAL"} and payload.startswith(b"SEAL\x00")
    if marker == 0xEA:
        return group in {None, "AROT"} and payload.startswith(b"AROT\x00\x00")
    if marker == 0xEB:
        return group in {None, "JUMBF"} and payload.startswith(b"JP")
    if marker == 0xEC:
        return group in {None, "Ducky"} and payload.startswith(b"Ducky")
    if marker == 0xEE:
        return group in {None, "Adobe"} and payload.startswith(b"Adobe")
    return False


def _payload_is_ciff(payload: bytes) -> bool:
    return len(payload) >= 14 and payload[:2] in {b"II", b"MM"} and payload[6:14] == b"HEAPJPGM"


def _source_ducky_payload_or_empty(source_path: Path) -> bytes:
    source = FileMediaSource(source_path)
    try:
        probes = read_jpeg_segment_probes(source_path)
    except ValueError:
        return b""
    for probe in probes:
        if probe.marker != 0xEC:
            continue
        if probe.payload_prefix.startswith(b"Ducky"):
            return source.read_at(probe.payload_offset, probe.payload_length)
    return b""


def _ducky_assignment_value(
    tag_name: App12DuckyTagName,
    value: str,
) -> App12DuckyValue:
    if tag_name == "Quality":
        digits = _first_decimal_sequence(value)
        if not digits:
            raise ValueError("invalid_ducky_quality_value")
        quality = int(digits)
        if quality > 0xFFFFFFFF:
            raise ValueError("invalid_ducky_quality_value")
        return quality
    return value


def _first_decimal_sequence(value: str) -> str:
    digits: list[str] = []
    for character in value:
        if character.isdecimal():
            digits.append(character)
            continue
        if digits:
            break
    return "".join(digits)


def _source_photoshop_app13_segments(source_path: Path) -> tuple[ExvSegment, ...]:
    return _source_photoshop_app13_segments_from_probes(
        FileMediaSource(source_path),
        read_jpeg_segment_probes_or_empty(source_path),
    )


def _source_photoshop_app13_segments_from_bytes(data: bytes) -> tuple[ExvSegment, ...]:
    sections = _source_photoshop_app13_resource_sections_from_bytes(data)
    return tuple(
        segment for section in sections for segment in write_photoshop_app13_segments(section)
    )


def _source_photoshop_app13_segments_from_probes(
    source: FileMediaSource,
    probes: tuple[JpegSegmentProbe, ...],
) -> tuple[ExvSegment, ...]:
    sections = _source_photoshop_app13_resource_sections_from_probes(source, probes)
    return tuple(
        segment for section in sections for segment in write_photoshop_app13_segments(section)
    )


def _source_photoshop_app13_resource_sections_from_bytes(data: bytes) -> tuple[bytes, ...]:
    if not data.startswith(b"\xff\xd8"):
        return ()
    sections: list[bytes] = []
    previous_was_photoshop = False
    for source_segment in scan_jpeg_segments(data):
        if source_segment.marker != 0xED:
            previous_was_photoshop = False
            continue
        payload = data[
            source_segment.payload_offset : source_segment.payload_offset
            + source_segment.payload_length
        ]
        if payload.startswith(PHOTOSHOP_APP13_PREFIX):
            resource_section = payload[len(PHOTOSHOP_APP13_PREFIX) :]
            if previous_was_photoshop and sections:
                sections[-1] += resource_section
            else:
                sections.append(resource_section)
            previous_was_photoshop = True
            continue
        previous_was_photoshop = False
    return tuple(sections)


def _source_photoshop_app13_resource_sections_from_probes(
    source: FileMediaSource,
    probes: tuple[JpegSegmentProbe, ...],
) -> tuple[bytes, ...]:
    sections: list[bytes] = []
    previous_was_photoshop = False
    for probe in probes:
        if probe.marker != 0xED:
            previous_was_photoshop = False
            continue
        if probe.payload_prefix.startswith(PHOTOSHOP_APP13_PREFIX):
            payload = source.read_at(probe.payload_offset, probe.payload_length)
            resource_section = payload[len(PHOTOSHOP_APP13_PREFIX) :]
            if previous_was_photoshop and sections:
                sections[-1] += resource_section
            else:
                sections.append(resource_section)
            previous_was_photoshop = True
            continue
        previous_was_photoshop = False
    return tuple(sections)


def read_jpeg_segment_probes_or_empty(source_path: Path) -> tuple[JpegSegmentProbe, ...]:
    try:
        return read_jpeg_segment_probes(source_path)
    except ValueError:
        return ()


def _source_icc_segments(source_path: Path) -> tuple[ExvSegment, ...]:
    try:
        profile = materialize_source_icc_profile(source_path)
    except ValueError:
        return ()
    return encode_exv_multi_segments(
        marker=0xE2,
        header=ICC_APP2_HEADER,
        payload=profile,
        kind="icc",
    )


def write_multi_xmp_segments(
    main_xmp_packet: bytes,
    *,
    extended_xmp_packet: bytes | None = None,
    extended_guid: str | None = None,
) -> tuple[ExvSegment, ...]:
    """Frame standard and extended JPEG XMP APP1 segments like Writer.pl WriteMultiXMP."""

    standard_payload = XMP_APP1_PREFIX + main_xmp_packet
    if len(standard_payload) > MAX_JPEG_SEGMENT_DATA_LENGTH:
        raise ValueError("XMP block too large for JPEG segment.")
    if (extended_xmp_packet is None) != (extended_guid is None):
        raise ValueError("Extended XMP requires both packet bytes and a 32-character GUID.")

    segments = [ExvSegment(marker=0xE1, payload=standard_payload)]
    if extended_xmp_packet is None or extended_guid is None:
        return tuple(segments)
    if len(extended_guid) != 32 or not extended_guid.isalnum() or not extended_guid.isascii():
        raise ValueError("Extended XMP GUID must be 32 ASCII alphanumeric characters.")

    max_extended_chunk = MAX_JPEG_SEGMENT_DATA_LENGTH - XMP_EXTENDED_CHUNK_HEADER_LENGTH
    if max_extended_chunk <= 0:
        raise ValueError("Extended XMP APP1 header leaves no room for payload.")
    total_size = len(extended_xmp_packet)
    guid_bytes = extended_guid.encode("ascii")
    for offset in range(0, total_size, max_extended_chunk):
        chunk = extended_xmp_packet[offset : offset + max_extended_chunk]
        segments.append(
            ExvSegment(
                marker=0xE1,
                payload=(
                    XMP_EXTENDED_APP1_PREFIX
                    + guid_bytes
                    + total_size.to_bytes(4, "big")
                    + offset.to_bytes(4, "big")
                    + chunk
                ),
            )
        )
    return tuple(segments)


def write_generated_xmp_segments(packet: bytes) -> tuple[ExvSegment, ...]:
    """Frame generated XMP, using extended XMP when the standard packet overflows."""

    standard_payload = XMP_APP1_PREFIX + packet
    if len(standard_payload) <= MAX_JPEG_SEGMENT_DATA_LENGTH:
        return (ExvSegment(marker=0xE1, payload=standard_payload),)

    extended_guid = md5(packet).hexdigest().upper()
    standard_packet = _extended_xmp_pointer_packet(extended_guid)
    return write_multi_xmp_segments(
        standard_packet,
        extended_xmp_packet=packet,
        extended_guid=extended_guid,
    )


def write_photoshop_app13_segments(resource_section: bytes) -> tuple[ExvSegment, ...]:
    """Frame Photoshop APP13 resource-section bytes like Writer.pl WriteMultiSegment."""

    return encode_exv_multi_segments(
        marker=0xED,
        header=PHOTOSHOP_APP13_PREFIX,
        payload=resource_section,
    )


def _extended_xmp_pointer_packet(extended_guid: str) -> bytes:
    has_extended_xmp = f'xmpNote:HasExtendedXMP="{extended_guid}"'
    packet = f"""<?xpacket begin='' id='W5M0MpCehiHzreSzNTczkc9d'?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about="" xmlns:xmpNote="http://ns.adobe.com/xmp/note/" {has_extended_xmp} />
</rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>"""
    return packet.encode("utf-8")


def _source_jpeg_comment_segments(source_path: Path) -> tuple[ExvSegment, ...]:
    source = FileMediaSource(source_path)
    try:
        probes = read_jpeg_segment_probes(source_path, prefix_length=0)
    except ValueError:
        return ()
    return tuple(
        ExvSegment(
            marker=0xFE,
            payload=source.read_at(probe.payload_offset, probe.payload_length),
        )
        for probe in probes
        if probe.marker == 0xFE
    )


def encode_exv_segment(marker: int, payload: bytes) -> bytes:
    if marker < 0 or marker > 0xFF:
        raise ValueError(f"Invalid JPEG marker: 0x{marker:X}")
    segment_length = len(payload) + JPEG_SEGMENT_LENGTH_SIZE
    if segment_length > 0xFFFF:
        raise ValueError("EXV segment exceeds JPEG segment size limit.")
    return b"\xff" + bytes((marker,)) + segment_length.to_bytes(2, "big") + payload


def encode_exv_multi_segments(
    *,
    marker: int,
    header: bytes,
    payload: bytes,
    kind: ExvMultiSegmentKind = "generic",
) -> tuple[ExvSegment, ...]:
    """Split payload like ExifTool Writer.pl WriteMultiSegment."""

    if marker < 0 or marker > 0xFF:
        raise ValueError(f"Invalid JPEG marker: 0x{marker:X}")
    max_payload_length = MAX_JPEG_SEGMENT_DATA_LENGTH - len(header)
    if kind == "icc":
        max_payload_length -= 2
    if max_payload_length <= 0:
        raise ValueError("EXV segment header leaves no room for payload.")

    segment_count = max(1, (len(payload) + max_payload_length - 1) // max_payload_length)
    segments: list[ExvSegment] = []
    position = 0
    sequence = 0
    while position < len(payload) or not segments:
        sequence += 1
        chunk_size = min(max_payload_length, len(payload) - position)
        boundary = payload[position + max_payload_length : position + max_payload_length + 4]
        if (
            kind == "exif"
            and chunk_size == max_payload_length
            and position + max_payload_length <= len(payload) - 4
            and boundary in {b"MM\x00\x2a", b"II\x2a\x00"}
        ):
            chunk_size -= 1
        chunk = payload[position : position + chunk_size]
        position += chunk_size
        if kind == "icc":
            chunk = bytes((sequence, segment_count)) + chunk
        segments.append(ExvSegment(marker=marker, payload=header + chunk))
    return tuple(segments)


def parse_exv_stream(data: bytes) -> ExvParseResult:
    """Parse the EXV metadata segment envelope and report ignored trailer bytes."""

    if not data.startswith(EXV_SIGNATURE):
        raise ValueError("EXV stream must begin with 0xff01 Exiv2.")
    position = len(EXV_SIGNATURE)
    segments: list[ExvSegment] = []
    while position < len(data):
        if position + 2 > len(data):
            raise ValueError("Truncated EXV marker.")
        if data[position] != 0xFF:
            raise ValueError("EXV segment marker must start with 0xff.")
        marker = data[position + 1]
        if marker == 0xD9:
            trailer_offset = position + 2
            return ExvParseResult(
                segments=tuple(segments),
                eoi_offset=position,
                ignored_trailer=data[trailer_offset:],
            )
        if marker == 0x00 or marker == 0x01 or 0xD0 <= marker <= 0xD7:
            raise ValueError(f"Unsupported stand-alone EXV marker: 0xFF{marker:02X}.")
        if position + 4 > len(data):
            raise ValueError("Truncated EXV segment length.")
        segment_length = int.from_bytes(data[position + 2 : position + 4], "big")
        if segment_length < JPEG_SEGMENT_LENGTH_SIZE:
            raise ValueError("Invalid EXV segment length.")
        payload_offset = position + 4
        payload_end = payload_offset + segment_length - JPEG_SEGMENT_LENGTH_SIZE
        if payload_end > len(data):
            raise ValueError("Truncated EXV segment payload.")
        segments.append(ExvSegment(marker=marker, payload=data[payload_offset:payload_end]))
        position = payload_end
    raise ValueError("EXV stream is missing EOI marker.")


def rewrite_exv_without_trailer(data: bytes) -> bytes:
    """Re-emit EXV segments and EOI, matching ExifTool's trailer drop behavior."""

    parsed = parse_exv_stream(data)
    return encode_exv_stream(parsed.segments)
