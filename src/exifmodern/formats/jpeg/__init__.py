"""JPEG format implementation packages."""

# No SIGNATURES export: builder `read_jpeg_dimensions` returns a dimensions
# struct, not tags. Dispatcher should use the JPEG container pipeline in
# `exifmodern.formats.jpeg.container`, not register this package as a direct
# trie handler.
