"""JPEG container boundary for Canon CustomFunctions2 writes."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.canon.custom_functions import (
    CanonCustomFunctionWritePlan,
    rewrite_canon_custom_functions_in_tiff,
)
from exifmodern.formats.jpeg.exif_app1 import (
    EXIF_APP1_PREFIX,
    encode_app1_segment,
    find_exif_app1_segment,
    segment_payload,
)


@dataclass(frozen=True)
class JpegCanonCustomFunctionRewriteResult:
    data: bytes
    original_app1_payload_length: int
    rewritten_app1_payload_length: int
    changed_canon_custom_properties: int


def rewrite_jpeg_canon_custom_functions(
    jpeg_data: bytes,
    plan: CanonCustomFunctionWritePlan,
) -> JpegCanonCustomFunctionRewriteResult:
    segment = find_exif_app1_segment(jpeg_data)
    payload = segment_payload(jpeg_data, segment)
    mutation_result = rewrite_canon_custom_functions_in_tiff(
        payload[len(EXIF_APP1_PREFIX) :],
        plan,
    )
    if mutation_result.changed_properties == 0:
        return JpegCanonCustomFunctionRewriteResult(
            data=jpeg_data,
            original_app1_payload_length=segment.payload_length,
            rewritten_app1_payload_length=segment.payload_length,
            changed_canon_custom_properties=0,
        )
    rewritten_payload = EXIF_APP1_PREFIX + mutation_result.data
    rewritten_segment = encode_app1_segment(rewritten_payload)
    segment_end = segment.payload_offset + segment.payload_length
    return JpegCanonCustomFunctionRewriteResult(
        data=jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:],
        original_app1_payload_length=segment.payload_length,
        rewritten_app1_payload_length=len(rewritten_payload),
        changed_canon_custom_properties=mutation_result.changed_properties,
    )
