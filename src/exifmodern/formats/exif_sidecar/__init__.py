"""EXIF sidecar copy-from-file planning and writing."""

# No SIGNATURES export: builder is a copy-strategy materializer
# (`materialize_exif_sidecar_copy_from_file_plan`), not a reader.
# Drop SIGNATURES until a real `.exv` reader lands.
