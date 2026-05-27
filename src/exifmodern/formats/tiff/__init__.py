"""TIFF format mutation helpers."""

# SIGNATURES intentionally removed: the registered builder
# (exifmodern.formats.tiff.primitives:parse_tiff_header) returns the 8-byte header, not tags.
# TIFF dispatch is handled by the read graph and TIFF primitive package; this
# package must not register its own trie entries.
