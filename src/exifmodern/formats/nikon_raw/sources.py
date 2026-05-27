"""Semantic evidence identifiers for Nikon NEF mutation planning."""

from __future__ import annotations

from exifmodern.json_types import JsonObject

type EvidenceId = str

NIKON_TYPE2_SOURCE: EvidenceId = "nikon_raw.nikon.type2"
NIKON_PREVIEW_IFD_SOURCE: EvidenceId = "nikon_raw.nikon.preview_ifd"
NIKON_PREVIEW_IFD_POINTER_SOURCE: EvidenceId = "nikon_raw.nikon.preview_ifd_pointer"
NIKON_PROCESS_SOURCE: EvidenceId = "nikon_raw.nikon.process_nikon"
MAKER_NOTES_NIKON_TYPE2_LOCATION_SOURCE: EvidenceId = "nikon_raw.maker_notes.type2_location"
NIKON_CAPTURE_MAKERNOTE_SOURCE: EvidenceId = "nikon_raw.nikon.capture_makernote"
NIKON_CAPTURE_TAGS_SOURCE: EvidenceId = "nikon_raw.nikon_capture.tags"
NIKON_CAPTURE_WRITE_SOURCE: EvidenceId = "nikon_raw.nikon_capture.write"
IPTC_CAPTION_ABSTRACT_SOURCE: EvidenceId = "nikon_raw.iptc.caption_abstract"
EXIF_IPTC_NAA_SOURCE: EvidenceId = "nikon_raw.exif.iptc_naa"
WRITE_IPTC_SOURCE: EvidenceId = "nikon_raw.write_iptc.do_write_iptc"
WRITE_EXIF_MAKERNOTE_REWRITE_SOURCE: EvidenceId = "nikon_raw.write_exif.makernote_rewrite"
WRITE_EXIF_MAKERNOTE_FIXUP_SOURCE: EvidenceId = "nikon_raw.write_exif.makernote_fixup"
WRITE_EXIF_IMAGE_DATA_FIXUP_SOURCE: EvidenceId = "nikon_raw.write_exif.image_data_fixup"
EXIF_IMAGE_DATA_OFFSET_PAIR_SOURCE: EvidenceId = "nikon_raw.exif.strip_offsets"
EXIF_IMAGE_DATA_BYTE_COUNT_SOURCE: EvidenceId = "nikon_raw.exif.strip_byte_counts"
EXIF_TILE_IMAGE_DATA_SOURCE: EvidenceId = "nikon_raw.exif.tile_image_data"
WRITE_EXIF_IMAGE_DATA_COPY_SOURCE: EvidenceId = "nikon_raw.write_exif.image_data_copy"
WRITE_EXIF_REBUILD_MAKERNOTES_SOURCE: EvidenceId = "nikon_raw.write_exif.rebuild_makernotes"
WRITE_EXIF_VALUE_FIXUP_SOURCE: EvidenceId = "nikon_raw.write_exif.value_fixup"
WRITE_EXIF_MAKERNOTE_PADDING_SOURCE: EvidenceId = "nikon_raw.write_exif.makernote_padding"


def unique_evidence_ids(evidence_ids: tuple[EvidenceId, ...]) -> tuple[EvidenceId, ...]:
    seen: set[EvidenceId] = set()
    unique: list[EvidenceId] = []
    for evidence_id in evidence_ids:
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        unique.append(evidence_id)
    return tuple(unique)


def evidence_id_to_json(evidence_id: EvidenceId) -> JsonObject:
    return {"evidence_id": evidence_id}
