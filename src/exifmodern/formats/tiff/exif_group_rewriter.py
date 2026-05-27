"""Source-grounded TIFF EXIF group deletion primitives."""

from __future__ import annotations

from dataclasses import replace

from exifmodern.formats.tiff.mutation import (
    EXIF_IFD_POINTER,
    encode_tiff_mutation_model,
    parse_tiff_mutation_model,
    remove_raw_entry,
)


def delete_exif_ifd(tiff_data: bytes) -> bytes:
    parsed = parse_tiff_mutation_model(tiff_data)
    if parsed.exif_ifd is None:
        return tiff_data
    ifd0 = remove_raw_entry(parsed.ifd0, EXIF_IFD_POINTER)
    return encode_tiff_mutation_model(replace(parsed, ifd0=ifd0, exif_ifd=None))
