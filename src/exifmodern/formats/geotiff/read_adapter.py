"""Read adapter for GeoTIFF key-directory blocks embedded in TIFF-like payloads."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.geotiff.key_directory_transaction_plan import (
    GeoTiffKeyDirectoryTransactionPlan,
    build_geotiff_key_directory_transaction_plan,
)
from exifmodern.formats.tiff.primitives import (
    TYPE_SIZES,
    Endian,
    IfdEntry,
    parse_ifd,
    parse_tiff_header,
)

GEOTIFF_DIRECTORY_TAG = 0x87AF
GEOTIFF_DOUBLE_PARAMS_TAG = 0x87B0
GEOTIFF_ASCII_PARAMS_TAG = 0x87B1


@dataclass(frozen=True)
class GeoTiffReadAdapterResult:
    plan: GeoTiffKeyDirectoryTransactionPlan | None
    diagnostics: tuple[str, ...]


def build_geotiff_read_adapter_result(tiff_payload: bytes) -> GeoTiffReadAdapterResult:
    """Extract GeoTIFF block values from IFD0 and delegate key expansion to the planner."""

    header = parse_tiff_header(tiff_payload)
    ifd0 = parse_ifd(tiff_payload, header.first_ifd_offset, header.endian)
    entries = {entry.tag_id: entry for entry in ifd0.entries}
    directory_entry = entries.get(GEOTIFF_DIRECTORY_TAG)
    if directory_entry is None:
        return GeoTiffReadAdapterResult(None, ("GeoJP2 TIFF payload has no GeoTiffDirectory",))

    key_directory = tiff_entry_raw_value(tiff_payload, directory_entry, header.endian)
    double_params = optional_tiff_entry_raw_value(
        tiff_payload,
        entries.get(GEOTIFF_DOUBLE_PARAMS_TAG),
        header.endian,
    )
    ascii_params = optional_tiff_entry_raw_value(
        tiff_payload,
        entries.get(GEOTIFF_ASCII_PARAMS_TAG),
        header.endian,
    )
    plan = build_geotiff_key_directory_transaction_plan(
        key_directory,
        geo_double_params=double_params,
        geo_ascii_params=ascii_params,
        endian=header.endian,
    )
    diagnostics = tuple(
        f"GeoTIFF key expansion blocker: {blocker.code}: {blocker.detail}"
        for blocker in plan.blockers
    )
    return GeoTiffReadAdapterResult(plan, diagnostics)


def optional_tiff_entry_raw_value(
    data: bytes,
    entry: IfdEntry | None,
    endian: Endian,
) -> bytes | None:
    if entry is None:
        return None
    return tiff_entry_raw_value(data, entry, endian)


def tiff_entry_raw_value(data: bytes, entry: IfdEntry, endian: Endian) -> bytes:
    field_size = TYPE_SIZES.get(entry.field_type)
    if field_size is None:
        raise ValueError(f"Unsupported TIFF field type for GeoTIFF block: {entry.field_type}")
    byte_count = field_size * entry.count
    if byte_count <= 4:
        return entry.value_offset.to_bytes(4, endian)[:byte_count]
    value_end = entry.value_offset + byte_count
    if value_end > len(data):
        raise ValueError(f"Truncated TIFF GeoTIFF block at offset {entry.value_offset}")
    return data[entry.value_offset : value_end]
