"""JPEG composed SetNewValuesFromFile copy routing.

This module is intentionally bounded to JPEG-owned metadata block routes. It
does not project RAW/JPEG MakerNotes into a destination EXIF tree because that
requires source-specific relocation semantics from ExifTool's MakerNote fixups.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

from exifmodern.formats.icc.materializer import materialize_source_icc_profile
from exifmodern.formats.jpeg.app_segments.xmp import XMP_APP1_PREFIX
from exifmodern.formats.jpeg.container import read_jpeg_segment_probes, scan_jpeg_segments
from exifmodern.formats.jpeg.exact_rewrite_io import read_exact_sidecar_payload
from exifmodern.formats.jpeg.exif_app1 import (
    EXIF_APP1_PREFIX,
    encode_app1_segment,
    exif_app1_insertion_offset,
    find_exif_app1_segment_or_none,
    segment_payload,
)
from exifmodern.formats.jpeg.iptc_app13_writer import (
    existing_iptc_resource_data,
    rewrite_jpeg_iptc_application_block_creating_if_needed,
)
from exifmodern.formats.jpeg.makernote_relocation_plan import (
    build_canon_cr2_jpeg_makernote_relocation_plan,
    build_nikon_d70_jpeg_makernote_relocation_plan,
)
from exifmodern.formats.jpeg.segment_writer import encode_jpeg_segment
from exifmodern.formats.jpeg.xmp_app1 import (
    encode_xmp_app1_segment,
    first_standard_xmp_app1_segment,
    xmp_app1_insertion_offset,
)
from exifmodern.formats.jpeg.xmp_property_writer import (
    rewrite_jpeg_xmp_properties_creating_if_needed,
)
from exifmodern.formats.photoshop.reader import (
    PHOTOSHOP_APP13_PREFIX,
    parse_photoshop_resources,
)
from exifmodern.formats.tiff.primitives import parse_ifd, parse_tiff_header, read_entry_value
from exifmodern.formats.xmp.copy_from_file_plan import (
    EXIF_TO_XMP_MAPPINGS,
    ExifSourceTag,
    ExifToXmpMapping,
    exif_source_tags,
    xmp_assignment_values_for_source_tag,
)
from exifmodern.formats.xmp.property_write import (
    XMP_NAMESPACE_URIS,
    XmpPropertySpec,
    XmpPropertyWritePlan,
    XmpTextListPropertyWrite,
    XmpTextPropertyWrite,
)
from exifmodern.media_source import FileMediaSource

type JpegComposedCopyGroup = Literal["EXIF", "XMP", "IPTC", "ICC_Profile", "Ducky"]
type JpegComposedCopySourceKind = Literal[
    "jpeg",
    "exif_sidecar",
    "xmp_sidecar",
    "icc_profile",
    "canon_cr2_tiff_raw",
    "nikon_nef_tiff_raw",
    "unsupported",
]
type JpegComposedCopyMaterializationKind = Literal[
    "jpeg_exif_app1_tiff_payload",
    "jpeg_xmp_app1_packet",
    "jpeg_photoshop_iptc_resource",
    "icc_profile_payload",
    "jpeg_ducky_app12_payload",
]
type JpegComposedXmpProjectionMode = Literal["replace", "append"]
type JpegComposedCopyBlockerCode = Literal[
    "source_file_missing",
    "target_not_jpeg",
    "unsupported_copy_route",
    "unsupported_copy_source_kind",
    "source_metadata_missing",
    "requires_tag_level_copy_projection",
    "requires_wildcard_copy_projection",
    "requires_exclusion_copy_projection",
    "requires_alternate_file_copy_projection",
    "requires_cross_format_tags_from_file_expansion",
    "requires_raw_tiff_to_jpeg_exif_materializer",
    "requires_jpeg_composed_writer_contract_for_raw_makernote_projection",
    "requires_jpeg_composed_writer_contract_for_nikon_makernote_projection",
    "requires_jpeg_composed_writer_contract_for_jpeg_makernote_projection",
]

JPEG_SUFFIXES = frozenset({".jpg", ".jpeg", ".jpe"})
ICC_APP2_PREFIX = b"ICC_PROFILE\x00"
DUCKY_APP12_PREFIX = b"Ducky"
ICC_APP2_PAYLOAD_OVERHEAD = len(ICC_APP2_PREFIX) + 2
JPEG_SEGMENT_MAX_PAYLOAD = 0xFFFF - 2
ICC_APP2_MAX_CHUNK_BYTES = JPEG_SEGMENT_MAX_PAYLOAD - ICC_APP2_PAYLOAD_OVERHEAD
MAKER_NOTE_TAG_ID = 0x927C
MAKE_TAG_ID = 0x010F
EXIF_IFD_POINTER_TAG_ID = 0x8769

SETNEWVALUES_SOURCE_EVIDENCE = (
    "jpeg.composed-copy.set-new-values-from-file",
    "jpeg.composed-copy.alternate-file",
    "jpeg.composed-copy.write-info",
    "jpeg.composed-copy.jpeg-rewrite",
    "jpeg.composed-copy.jpeg-main-table",
    "jpeg.composed-copy.ducky-write",
    "jpeg.composed-copy.writer-tests",
    "jpeg.composed-copy.canonraw-test7",
    "jpeg.composed-copy.nikon-test4",
)
JPEG_COMPOSED_CREATION_GROUP_ORDER: tuple[JpegComposedCopyGroup, ...] = (
    "EXIF",
    "IPTC",
    "XMP",
    "ICC_Profile",
    "Ducky",
)


@dataclass(frozen=True)
class JpegComposedCopyRoute:
    group: JpegComposedCopyGroup
    raw: str
    order_index: int


@dataclass(frozen=True)
class JpegComposedMaterializedRoute:
    group: JpegComposedCopyGroup
    kind: JpegComposedCopyMaterializationKind
    payload: bytes
    source_detail: str


@dataclass(frozen=True)
class JpegComposedXmpProjectionAssignment:
    property_name: str
    value: str
    mode: JpegComposedXmpProjectionMode
    route: str
    source_detail: str


@dataclass(frozen=True)
class JpegComposedXmpProjectionResult:
    assignments: tuple[JpegComposedXmpProjectionAssignment, ...]
    blockers: tuple[JpegComposedCopyBlocker, ...]


@dataclass(frozen=True)
class JpegComposedCopyBlocker:
    code: JpegComposedCopyBlockerCode
    route: str
    detail: str
    evidence_ids: tuple[str, ...] = SETNEWVALUES_SOURCE_EVIDENCE


@dataclass(frozen=True)
class JpegComposedCopyPlan:
    source_path: Path
    target_path: Path
    source_kind: JpegComposedCopySourceKind
    routes: tuple[JpegComposedCopyRoute, ...]
    materialized_routes: tuple[JpegComposedMaterializedRoute, ...]
    xmp_projection_assignments: tuple[JpegComposedXmpProjectionAssignment, ...] = ()
    blockers: tuple[JpegComposedCopyBlocker, ...] = ()
    evidence_ids: tuple[str, ...] = SETNEWVALUES_SOURCE_EVIDENCE

    @property
    def can_execute(self) -> bool:
        return not self.blockers and bool(
            self.materialized_routes or self.xmp_projection_assignments
        )

    @property
    def remaining_unsupported_routes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(blocker.code for blocker in self.blockers))


def build_jpeg_composed_setnewvalues_from_file_plan(
    source_path: Path,
    target_path: Path,
    copy_tags: tuple[str, ...] = (),
    alternate_files: Mapping[str, Path] | None = None,
) -> JpegComposedCopyPlan:
    source_kind = _source_kind(source_path)
    routes = _copy_routes(copy_tags)
    materialized: list[JpegComposedMaterializedRoute] = []
    blockers: list[JpegComposedCopyBlocker] = []
    xmp_assignments: list[JpegComposedXmpProjectionAssignment] = []

    if not source_path.is_file():
        blockers.append(
            JpegComposedCopyBlocker(
                code="source_file_missing",
                route=source_path.as_posix(),
                detail="SetNewValuesFromFile source path does not exist.",
            )
        )
    if target_path.suffix.lower() not in JPEG_SUFFIXES:
        blockers.append(
            JpegComposedCopyBlocker(
                code="target_not_jpeg",
                route=target_path.as_posix(),
                detail="Shared composed copy routing in this module writes only JPEG targets.",
            )
        )

    if blockers:
        return JpegComposedCopyPlan(
            source_path=source_path,
            target_path=target_path,
            source_kind=source_kind,
            routes=routes,
            materialized_routes=(),
            xmp_projection_assignments=(),
            blockers=tuple(blockers),
        )

    blockers.extend(_unsupported_copy_tag_blockers(copy_tags))
    if copy_tags and _has_explicit_all_copy_route(copy_tags):
        blockers.extend(_implicit_all_source_blockers(source_path, source_kind))

    if not copy_tags:
        blockers.extend(_implicit_all_source_blockers(source_path, source_kind))
        if source_kind in {"canon_cr2_tiff_raw", "nikon_nef_tiff_raw"}:
            return JpegComposedCopyPlan(
                source_path=source_path,
                target_path=target_path,
                source_kind=source_kind,
                routes=routes,
                materialized_routes=(),
                xmp_projection_assignments=(),
                blockers=tuple(blockers),
            )

    for route in routes:
        route_result = _materialize_route(source_path, source_kind, route)
        if isinstance(route_result, JpegComposedCopyBlocker):
            if route_result.code != "source_metadata_missing":
                blockers.append(route_result)
            continue
        materialized.append(route_result)

    if copy_tags:
        projection_result = _materialize_xmp_projection_assignments(
            source_path,
            copy_tags,
            alternate_files or {},
        )
        xmp_assignments.extend(projection_result.assignments)
        blockers.extend(projection_result.blockers)

    return JpegComposedCopyPlan(
        source_path=source_path,
        target_path=target_path,
        source_kind=source_kind,
        routes=routes,
        materialized_routes=tuple(materialized),
        xmp_projection_assignments=tuple(xmp_assignments),
        blockers=tuple(blockers),
    )


def rewrite_jpeg_composed_setnewvalues_from_file(
    target_data: bytes,
    plan: JpegComposedCopyPlan,
) -> bytes:
    if not plan.can_execute:
        blockers = ", ".join(plan.remaining_unsupported_routes) or "no materialized routes"
        raise ValueError(f"JPEG composed copy plan is not executable: {blockers}")

    rewritten = target_data
    route_by_group = _materialized_route_by_group(plan.materialized_routes)
    for group in JPEG_COMPOSED_CREATION_GROUP_ORDER:
        route = route_by_group.get(group)
        if route is None:
            continue
        if group == "EXIF":
            rewritten = rewrite_jpeg_exif_payload(rewritten, EXIF_APP1_PREFIX + route.payload)
        elif group == "IPTC":
            rewritten = rewrite_jpeg_iptc_application_block_creating_if_needed(
                rewritten,
                route.payload,
            ).data
        elif group == "XMP":
            rewritten = rewrite_jpeg_xmp_payload(rewritten, XMP_APP1_PREFIX + route.payload)
        elif group == "ICC_Profile":
            rewritten = rewrite_jpeg_icc_profile(rewritten, route.payload)
        elif group == "Ducky":
            rewritten = rewrite_jpeg_ducky_payload(rewritten, route.payload)
    if plan.xmp_projection_assignments:
        result = rewrite_jpeg_xmp_properties_creating_if_needed(
            rewritten,
            _xmp_projection_write_plan(plan.xmp_projection_assignments),
        )
        rewritten = result.data
    return rewritten


def rewrite_jpeg_exif_payload(jpeg_data: bytes, exif_app1_payload: bytes) -> bytes:
    segment = find_exif_app1_segment_or_none(jpeg_data)
    rewritten_segment = encode_app1_segment(exif_app1_payload)
    if segment is None:
        insertion_offset = exif_app1_insertion_offset(jpeg_data)
        return jpeg_data[:insertion_offset] + rewritten_segment + jpeg_data[insertion_offset:]
    segment_end = segment.payload_offset + segment.payload_length
    return jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:]


def rewrite_jpeg_xmp_payload(jpeg_data: bytes, xmp_app1_payload: bytes) -> bytes:
    segment = first_standard_xmp_app1_segment(jpeg_data)
    rewritten_segment = encode_xmp_app1_segment(xmp_app1_payload)
    if segment is None:
        insertion_offset = xmp_app1_insertion_offset(jpeg_data)
        return jpeg_data[:insertion_offset] + rewritten_segment + jpeg_data[insertion_offset:]
    segment_end = segment.payload_offset + segment.payload_length
    return jpeg_data[: segment.offset] + rewritten_segment + jpeg_data[segment_end:]


def rewrite_jpeg_icc_profile(jpeg_data: bytes, icc_profile: bytes) -> bytes:
    stripped = _delete_jpeg_icc_profile(jpeg_data)
    insertion_offset = icc_app2_insertion_offset(stripped)
    encoded = b"".join(encode_jpeg_icc_profile_segments(icc_profile))
    return stripped[:insertion_offset] + encoded + stripped[insertion_offset:]


def rewrite_jpeg_ducky_payload(jpeg_data: bytes, ducky_payload: bytes) -> bytes:
    stripped = _delete_jpeg_ducky(jpeg_data)
    if not ducky_payload:
        return stripped
    insertion_offset = ducky_app12_insertion_offset(stripped)
    encoded = encode_jpeg_segment(0xEC, ducky_payload)
    return stripped[:insertion_offset] + encoded + stripped[insertion_offset:]


def encode_jpeg_icc_profile_segments(icc_profile: bytes) -> tuple[bytes, ...]:
    if not icc_profile:
        return ()
    chunks = tuple(
        icc_profile[offset : offset + ICC_APP2_MAX_CHUNK_BYTES]
        for offset in range(0, len(icc_profile), ICC_APP2_MAX_CHUNK_BYTES)
    )
    if len(chunks) > 255:
        raise ValueError("ICC_Profile requires more than 255 JPEG APP2 chunks.")
    total = len(chunks)
    return tuple(
        encode_jpeg_segment(
            0xE2,
            ICC_APP2_PREFIX + bytes((index, total)) + chunk,
        )
        for index, chunk in enumerate(chunks, start=1)
    )


def icc_app2_insertion_offset(jpeg_data: bytes) -> int:
    insertion_offset = 2
    for segment in scan_jpeg_segments(jpeg_data):
        payload = segment_payload(jpeg_data, segment)
        if segment.marker == 0xE0:
            insertion_offset = segment.payload_offset + segment.payload_length
            continue
        if segment.marker == 0xE1 and (
            payload.startswith(EXIF_APP1_PREFIX) or payload.startswith(XMP_APP1_PREFIX)
        ):
            insertion_offset = segment.payload_offset + segment.payload_length
            continue
        if segment.marker == 0xED:
            insertion_offset = segment.payload_offset + segment.payload_length
            continue
        break
    return insertion_offset


def ducky_app12_insertion_offset(jpeg_data: bytes) -> int:
    insertion_offset = 2
    for segment in scan_jpeg_segments(jpeg_data):
        payload = segment_payload(jpeg_data, segment)
        if segment.marker == 0xE0:
            insertion_offset = segment.payload_offset + segment.payload_length
            continue
        if segment.marker == 0xE1 and (
            payload.startswith(EXIF_APP1_PREFIX) or payload.startswith(XMP_APP1_PREFIX)
        ):
            insertion_offset = segment.payload_offset + segment.payload_length
            continue
        if segment.marker == 0xE2 and payload.startswith(ICC_APP2_PREFIX):
            insertion_offset = segment.payload_offset + segment.payload_length
            continue
        if segment.marker == 0xED and payload.startswith(PHOTOSHOP_APP13_PREFIX):
            insertion_offset = segment.payload_offset + segment.payload_length
            continue
        break
    return insertion_offset


def _delete_jpeg_icc_profile(jpeg_data: bytes) -> bytes:
    rewritten = jpeg_data
    deleted_so_far = 0
    for segment in scan_jpeg_segments(jpeg_data):
        payload = segment_payload(jpeg_data, segment)
        if segment.marker != 0xE2 or not payload.startswith(ICC_APP2_PREFIX):
            continue
        original_segment_end = segment.payload_offset + segment.payload_length
        rewritten_start = segment.offset - deleted_so_far
        deleted_length = original_segment_end - segment.offset
        rewritten = rewritten[:rewritten_start] + rewritten[rewritten_start + deleted_length :]
        deleted_so_far += deleted_length
    return rewritten


def _delete_jpeg_ducky(jpeg_data: bytes) -> bytes:
    rewritten = jpeg_data
    deleted_so_far = 0
    for segment in scan_jpeg_segments(jpeg_data):
        payload = segment_payload(jpeg_data, segment)
        if segment.marker != 0xEC or not payload.startswith(DUCKY_APP12_PREFIX):
            continue
        original_segment_end = segment.payload_offset + segment.payload_length
        rewritten_start = segment.offset - deleted_so_far
        deleted_length = original_segment_end - segment.offset
        rewritten = rewritten[:rewritten_start] + rewritten[rewritten_start + deleted_length :]
        deleted_so_far += deleted_length
    return rewritten


def _copy_routes(copy_tags: tuple[str, ...]) -> tuple[JpegComposedCopyRoute, ...]:
    if not copy_tags:
        return (
            JpegComposedCopyRoute("EXIF", "<implicit All copy route>", 0),
            JpegComposedCopyRoute("IPTC", "<implicit All copy route>", 1),
            JpegComposedCopyRoute("XMP", "<implicit All copy route>", 2),
            JpegComposedCopyRoute("ICC_Profile", "<implicit All copy route>", 3),
            JpegComposedCopyRoute("Ducky", "<implicit All copy route>", 4),
        )
    routes: list[JpegComposedCopyRoute] = []
    for index, tag in enumerate(copy_tags):
        if _is_exclusion_copy_route(tag):
            continue
        if _is_explicit_all_copy_route(tag):
            routes.extend(
                JpegComposedCopyRoute(group, tag, index)
                for group in JPEG_COMPOSED_CREATION_GROUP_ORDER
            )
            continue
        group = _copy_group(tag)
        if group is None:
            continue
        routes.append(JpegComposedCopyRoute(group, tag, index))
    return tuple(routes)


def _copy_group(tag: str) -> JpegComposedCopyGroup | None:
    normalized = tag.strip().removeprefix("-").lower()
    if "<" in normalized or ">" in normalized or "=" in normalized:
        return None
    group, separator, requested_tag = normalized.partition(":")
    if separator and requested_tag not in {"all", "*"}:
        return None
    if group == "exif":
        return "EXIF"
    if group == "xmp":
        return "XMP"
    if group in {"iptc", "photoshop"}:
        return "IPTC"
    if group in {"icc", "icc_profile"}:
        return "ICC_Profile"
    if group == "ducky":
        return "Ducky"
    if group in {"all", "*"}:
        return "EXIF"
    return None


def _is_exclusion_copy_route(tag: str) -> bool:
    return tag.strip().startswith("-") and _copy_group(tag) is None


def _is_explicit_all_copy_route(tag: str) -> bool:
    normalized = tag.strip().removeprefix("-").lower()
    return normalized in {"all", "*", "all:all", "all:*", "*:all", "*:*"}


def _has_explicit_all_copy_route(copy_tags: tuple[str, ...]) -> bool:
    return any(
        _is_explicit_all_copy_route(tag) and not _is_exclusion_copy_route(tag) for tag in copy_tags
    )


def _unsupported_copy_tag_blockers(
    copy_tags: tuple[str, ...],
) -> tuple[JpegComposedCopyBlocker, ...]:
    blockers: list[JpegComposedCopyBlocker] = []
    for tag in copy_tags:
        if _is_exclusion_copy_route(tag):
            blockers.append(
                JpegComposedCopyBlocker(
                    code="requires_exclusion_copy_projection",
                    route=tag,
                    detail=(
                        "SetNewValuesFromFile exclusion selectors affect the source tag "
                        "matching set before values are written. The bounded JPEG composed "
                        "block writer cannot safely translate exclusions into whole-block "
                        "copy/delete operations."
                    ),
                )
            )
            continue
        if _is_explicit_all_copy_route(tag):
            continue
        if _copy_group(tag) is not None:
            continue
        if _is_supported_xmp_projection_route(tag):
            continue
        normalized = tag.strip().removeprefix("-").lower()
        if not normalized:
            continue
        if _has_alternate_file_selector(normalized):
            blockers.append(
                JpegComposedCopyBlocker(
                    code="requires_alternate_file_copy_projection",
                    route=tag,
                    detail=(
                        "SetAlternateFile/FileNUM copy selectors require public source-graph "
                        "fanout before JPEG composed block projection can execute them."
                    ),
                )
            )
            continue
        if "*" in normalized or "?" in normalized:
            blockers.append(
                JpegComposedCopyBlocker(
                    code="requires_wildcard_copy_projection",
                    route=tag,
                    detail=(
                        "Wildcard SetNewValuesFromFile routes must expand to concrete "
                        "source and owned destination tags before this block writer runs."
                    ),
                )
            )
            continue
        if "<" in normalized or ">" in normalized or "=" in normalized:
            blockers.append(
                JpegComposedCopyBlocker(
                    code="requires_tag_level_copy_projection",
                    route=tag,
                    detail=(
                        "Redirected or assigned copy routes need tag-level value projection; "
                        "this module only materializes owned whole JPEG metadata blocks."
                    ),
                )
            )
            continue
        blockers.append(
            JpegComposedCopyBlocker(
                code="requires_tag_level_copy_projection",
                route=tag,
                detail=(
                    "Unqualified exact copy routes must resolve to concrete owned "
                    "destination tags before JPEG composed block writing."
                ),
            )
        )
    return tuple(blockers)


def _materialize_xmp_projection_assignments(
    source_path: Path,
    copy_tags: tuple[str, ...],
    alternate_files: Mapping[str, Path],
) -> JpegComposedXmpProjectionResult:
    source_cache: dict[str, dict[tuple[str, str], ExifSourceTag]] = {}
    assignments: list[JpegComposedXmpProjectionAssignment] = []
    blockers: list[JpegComposedCopyBlocker] = []
    for route in copy_tags:
        projection = _xmp_projection_route(route)
        if projection is None:
            continue
        source_key, source_group, source_pattern, destination_group, property_pattern, mode = (
            projection
        )
        source_detail_path = _projection_source_path(source_key, source_path, alternate_files)
        if source_detail_path is None:
            blockers.append(
                JpegComposedCopyBlocker(
                    code="requires_alternate_file_copy_projection",
                    route=route,
                    detail=f"Alternate source {source_key} is not bound for this copy route.",
                )
            )
            continue
        source_detail = source_detail_path.as_posix()
        try:
            source_tags = source_cache.setdefault(
                source_detail,
                exif_source_tags(source_detail_path),
            )
        except ValueError as exc:
            blockers.append(
                JpegComposedCopyBlocker(
                    code="unsupported_copy_source_kind",
                    route=route,
                    detail=str(exc),
                )
            )
            continue
        route_assignments = _xmp_projection_assignments_for_route(
            source_tags,
            source_group,
            source_pattern,
            destination_group,
            property_pattern,
            mode,
            route,
            source_detail,
        )
        if not route_assignments and (
            "*" in source_pattern
            or "?" in source_pattern
            or property_pattern in {"*", "all"}
            or "*" in property_pattern
            or "?" in property_pattern
        ):
            blockers.append(
                JpegComposedCopyBlocker(
                    code="requires_wildcard_copy_projection",
                    route=route,
                    detail="Wildcard source route did not resolve to an owned XMP destination tag.",
                )
            )
            continue
        assignments.extend(route_assignments)
    return JpegComposedXmpProjectionResult(tuple(assignments), tuple(blockers))


def _is_supported_xmp_projection_route(route: str) -> bool:
    projection = _xmp_projection_route(route)
    if projection is None:
        return False
    _, source_group, source_pattern, destination_group, property_pattern, _ = projection
    return any(
        _mapping_matches_source(mapping, source_group, source_pattern)
        and _destination_properties_for_mapping(mapping, destination_group, property_pattern)
        for mapping in EXIF_TO_XMP_MAPPINGS
    )


def _xmp_projection_route(
    route: str,
) -> tuple[str, str, str, str, str, JpegComposedXmpProjectionMode] | None:
    raw = route.strip()
    if not raw:
        return None
    mode: JpegComposedXmpProjectionMode = "replace"
    if raw.startswith("+"):
        mode = "append"
        raw = raw[1:].strip()
    if "<" in raw:
        destination, _, source = raw.partition("<")
    elif ">" in raw:
        source, _, destination = raw.partition(">")
    else:
        return None
    destination = destination.strip()
    source = source.strip()
    if not destination or not source or "$" in source.replace("$file", ""):
        return None
    source_key = ""
    source_group = ""
    source_pattern = ""
    source_parts = source.split(":", 1)
    if len(source_parts) == 2 and _normalized_file_group(source_parts[0]) is not None:
        source_key = _normalized_file_group(source_parts[0]) or ""
        source_selector = source_parts[1]
    else:
        source_selector = source
    if ":" in source_selector:
        source_group, _, source_pattern = source_selector.partition(":")
    else:
        source_group, source_pattern = "EXIF", source_selector
    destination_group, separator, destination_pattern = destination.partition(":")
    if separator != ":":
        destination_group, destination_pattern = "XMP", destination_group
    if not _destination_is_xmp(destination_group):
        return None
    if not source_pattern or any(marker in source_pattern for marker in "<>="):
        return None
    return (
        source_key,
        source_group.lower(),
        "all" if source_pattern.lower() == "all" else source_pattern,
        destination_group,
        "all" if destination_pattern.lower() == "all" else destination_pattern,
        mode,
    )


def _projection_source_path(
    source_key: str,
    source_path: Path,
    alternate_files: Mapping[str, Path],
) -> Path | None:
    if not source_key:
        return source_path
    return alternate_files.get(source_key) or alternate_files.get(source_key.lower())


def _normalized_file_group(value: str) -> str | None:
    normalized = value.strip().removeprefix("$").lower()
    if normalized.startswith("file") and normalized[4:].isdecimal():
        return normalized
    return None


def _destination_is_xmp(group: str) -> bool:
    normalized = group.lower()
    return normalized == "xmp" or normalized.startswith("xmp-")


def _xmp_projection_assignments_for_route(
    source_tags: dict[tuple[str, str], ExifSourceTag],
    source_group: str,
    source_pattern: str,
    destination_group: str,
    property_pattern: str,
    mode: JpegComposedXmpProjectionMode,
    route: str,
    source_detail: str,
) -> tuple[JpegComposedXmpProjectionAssignment, ...]:
    assignments: list[JpegComposedXmpProjectionAssignment] = []
    for mapping in EXIF_TO_XMP_MAPPINGS:
        if not _mapping_matches_source(mapping, source_group, source_pattern):
            continue
        destination_properties = _destination_properties_for_mapping(
            mapping,
            destination_group,
            property_pattern,
        )
        if not destination_properties:
            continue
        source_tag = source_tags.get((mapping.source_group, mapping.source_name))
        if source_tag is None:
            continue
        values = xmp_assignment_values_for_source_tag(source_tag, mapping)
        for property_name in destination_properties:
            assignments.extend(
                JpegComposedXmpProjectionAssignment(
                    property_name=property_name,
                    value=value,
                    mode=mode,
                    route=route,
                    source_detail=source_detail,
                )
                for value in values
            )
    return tuple(assignments)


def _mapping_matches_source(
    mapping: ExifToXmpMapping,
    source_group: str,
    source_pattern: str,
) -> bool:
    if source_group not in {"", "all", "*", "exif"}:
        group_match = {
            "ifd0": "IFD0",
            "exififd": "ExifIFD",
            "gps": "GPS",
            "interopifd": "InteropIFD",
        }.get(source_group)
        if group_match != mapping.source_group:
            return False
    return _selector_matches_name(source_pattern, mapping.source_name)


def _property_matches_destination(property_name: str, property_pattern: str) -> bool:
    if property_pattern in {"*", "all"}:
        return True
    _, _, property_tag = property_name.partition(":")
    return _selector_matches_name(property_pattern, property_tag)


def _destination_properties_for_mapping(
    mapping: ExifToXmpMapping,
    destination_group: str,
    property_pattern: str,
) -> tuple[str, ...]:
    if property_pattern in {"*", "all"}:
        return (mapping.property_name,)
    resolved = _explicit_destination_property(destination_group, property_pattern)
    return (resolved,) if resolved is not None else ()


def _explicit_destination_property(destination_group: str, destination_tag: str) -> str | None:
    normalized_group = destination_group.lower()
    tag = _canonical_xmp_tag_name(destination_tag)
    if normalized_group in {"xmp", "xmp-dc"} and tag in {"Subject", "Contributor", "Type"}:
        return f"XMP-dc:{tag}"
    if normalized_group == "xmp-tiff" and tag in {
        "Make",
        "Model",
        "XResolution",
        "YResolution",
        "ResolutionUnit",
        "YCbCrPositioning",
        "Orientation",
    }:
        return f"XMP-tiff:{tag}"
    if normalized_group == "xmp-exif" and tag in {
        "ExposureTime",
        "FNumber",
        "ISO",
        "DateTimeOriginal",
        "CreateDate",
    }:
        return f"XMP-exif:{tag}"
    return None


def _canonical_xmp_tag_name(value: str) -> str:
    normalized = value.replace("-", "").replace("_", "").lower()
    names = {
        "subject": "Subject",
        "contributor": "Contributor",
        "type": "Type",
        "make": "Make",
        "model": "Model",
        "xresolution": "XResolution",
        "yresolution": "YResolution",
        "resolutionunit": "ResolutionUnit",
        "ycbcrpositioning": "YCbCrPositioning",
        "orientation": "Orientation",
        "exposuretime": "ExposureTime",
        "fnumber": "FNumber",
        "iso": "ISO",
        "datetimeoriginal": "DateTimeOriginal",
        "createdate": "CreateDate",
    }
    return names.get(normalized, value)


def _selector_matches_name(pattern: str, name: str) -> bool:
    normalized = "*" if pattern.lower() == "all" else pattern
    return normalized == "*" or fnmatchcase(name.lower(), normalized.lower())


def _xmp_projection_write_plan(
    assignments: tuple[JpegComposedXmpProjectionAssignment, ...],
) -> XmpPropertyWritePlan:
    values_by_property: dict[str, list[str]] = {}
    for assignment in assignments:
        if assignment.mode == "replace":
            values_by_property[assignment.property_name] = [assignment.value]
        else:
            values_by_property.setdefault(assignment.property_name, []).append(assignment.value)
    steps: list[XmpTextPropertyWrite | XmpTextListPropertyWrite] = []
    generated_specs: list[XmpPropertySpec] = []
    for property_name, values in values_by_property.items():
        spec = _projection_xmp_property_spec(property_name, len(values) > 1)
        generated_specs.append(spec)
        if spec.value_shape in {"bag_text", "seq_text"}:
            steps.append(XmpTextListPropertyWrite(property_name, tuple(values)))
        else:
            steps.append(XmpTextPropertyWrite(property_name, values[-1]))
    return _with_ref_arg(
        XmpPropertyWritePlan,
        (),
        steps=tuple(steps),
        generated_specs=tuple(generated_specs),
    )


def _projection_xmp_property_spec(property_name: str, multiple_values: bool) -> XmpPropertySpec:
    group, _, tag = property_name.partition(":")
    prefix = group.removeprefix("XMP-")
    if property_name in {"XMP-dc:Subject", "XMP-dc:Contributor", "XMP-dc:Type"}:
        return _with_ref_arg(
            XmpPropertySpec,
            (),
            property_name=property_name,
            namespace_prefix="dc",
            namespace_uri=XMP_NAMESPACE_URIS["dc"],
            element_name=tag.lower(),
            value_shape="bag_text",
            rdf_container="Bag",
        )
    return _with_ref_arg(
        XmpPropertySpec,
        (),
        property_name=property_name,
        namespace_prefix=prefix,
        namespace_uri=XMP_NAMESPACE_URIS[prefix],
        element_name=tag,
        value_shape="bag_text" if multiple_values else "simple_text",
        rdf_container="Bag" if multiple_values else None,
    )


def _with_ref_arg[T](  # type: ignore[explicit-any,no-untyped-def]
    builder: Callable[..., T],
    refs: tuple[()],
    **kwargs,
) -> T:
    return builder(**kwargs, evidence_ids=refs)


def _has_alternate_file_selector(normalized_route: str) -> bool:
    return "$file" in normalized_route or any(
        part.startswith("file") and part[4:].isdecimal()
        for side in normalized_route.replace("<", ":").replace(">", ":").split(":")
        for part in side.split()
    )


def _source_kind(source_path: Path) -> JpegComposedCopySourceKind:
    suffix = source_path.suffix.lower()
    if suffix in JPEG_SUFFIXES:
        return "jpeg"
    if suffix == ".exif":
        return "exif_sidecar"
    if suffix == ".xmp":
        return "xmp_sidecar"
    if suffix in {".icc", ".icm"}:
        return "icc_profile"
    if suffix == ".cr2":
        return "canon_cr2_tiff_raw"
    if suffix == ".nef":
        return "nikon_nef_tiff_raw"
    return "unsupported"


def _materialize_route(
    source_path: Path,
    source_kind: JpegComposedCopySourceKind,
    route: JpegComposedCopyRoute,
) -> JpegComposedMaterializedRoute | JpegComposedCopyBlocker:
    try:
        if route.group == "EXIF":
            if source_kind not in {"jpeg", "exif_sidecar"}:
                return _unsupported_source_blocker(route, source_kind)
            payload = _source_exif_tiff_payload(source_path, source_kind)
            return JpegComposedMaterializedRoute(
                group="EXIF",
                kind="jpeg_exif_app1_tiff_payload",
                payload=payload,
                source_detail=source_path.as_posix(),
            )
        if route.group == "XMP":
            if source_kind not in {"jpeg", "xmp_sidecar"}:
                return _unsupported_source_blocker(route, source_kind)
            return JpegComposedMaterializedRoute(
                group="XMP",
                kind="jpeg_xmp_app1_packet",
                payload=_source_xmp_packet(source_path, source_kind),
                source_detail=source_path.as_posix(),
            )
        if route.group == "IPTC":
            if source_kind != "jpeg":
                return _unsupported_source_blocker(route, source_kind)
            return JpegComposedMaterializedRoute(
                group="IPTC",
                kind="jpeg_photoshop_iptc_resource",
                payload=_source_iptc_resource(source_path),
                source_detail=source_path.as_posix(),
            )
        if route.group == "ICC_Profile":
            return JpegComposedMaterializedRoute(
                group="ICC_Profile",
                kind="icc_profile_payload",
                payload=materialize_source_icc_profile(source_path),
                source_detail=source_path.as_posix(),
            )
        if route.group == "Ducky":
            if source_kind != "jpeg":
                return _unsupported_source_blocker(route, source_kind)
            return JpegComposedMaterializedRoute(
                group="Ducky",
                kind="jpeg_ducky_app12_payload",
                payload=_source_ducky_payload(source_path),
                source_detail=source_path.as_posix(),
            )
    except ValueError as exc:
        return JpegComposedCopyBlocker(
            code="source_metadata_missing",
            route=route.raw,
            detail=str(exc),
        )
    return JpegComposedCopyBlocker(
        code="unsupported_copy_route",
        route=route.raw,
        detail="Route is outside the bounded JPEG composed copy groups.",
    )


def _unsupported_source_blocker(
    route: JpegComposedCopyRoute,
    source_kind: JpegComposedCopySourceKind,
) -> JpegComposedCopyBlocker:
    if source_kind in {"canon_cr2_tiff_raw", "nikon_nef_tiff_raw"} and route.group == "EXIF":
        return JpegComposedCopyBlocker(
            code="requires_raw_tiff_to_jpeg_exif_materializer",
            route=route.raw,
            detail=(
                "RAW TIFF wrappers require value-level EXIF projection before writing a "
                "JPEG APP1 EXIF segment; blindly copying the RAW TIFF payload would "
                "preserve RAW image offsets and MakerNote state."
            ),
        )
    return JpegComposedCopyBlocker(
        code="unsupported_copy_source_kind",
        route=route.raw,
        detail=f"{route.group} copy is not materialized from source kind {source_kind}.",
    )


def _implicit_all_source_blockers(
    source_path: Path,
    source_kind: JpegComposedCopySourceKind,
) -> tuple[JpegComposedCopyBlocker, ...]:
    if source_kind == "canon_cr2_tiff_raw":
        relocation_plan = build_canon_cr2_jpeg_makernote_relocation_plan(source_path)
        evidence = relocation_plan.byte_evidence
        blocker = relocation_plan.primary_blocker
        return (
            JpegComposedCopyBlocker(
                code="requires_cross_format_tags_from_file_expansion",
                route="<implicit All copy route>",
                detail="CanonRaw.t test 7 copies all CR2 source tags into Writer.jpg.",
            ),
            JpegComposedCopyBlocker(
                code="requires_jpeg_composed_writer_contract_for_raw_makernote_projection",
                route="<implicit All copy route>",
                detail=(
                    f"{blocker.reason} Source MakerNote byte range is "
                    f"{evidence.raw_makernote_offset}.."
                    f"{evidence.raw_makernote_end_offset} "
                    f"({evidence.raw_makernote_length} bytes). "
                    f"{blocker.unsafe_partial_write_policy}"
                ),
            ),
        )
    if source_kind == "nikon_nef_tiff_raw":
        return (
            JpegComposedCopyBlocker(
                code="requires_cross_format_tags_from_file_expansion",
                route="<implicit All copy route>",
                detail="NEF all-tag copy requires source-specific TIFF RAW value projection.",
            ),
        )
    if source_kind == "jpeg":
        maker_note = _jpeg_maker_note_projection_blocker(source_path)
        return (maker_note,) if maker_note is not None else ()
    if source_kind == "unsupported":
        return (
            JpegComposedCopyBlocker(
                code="unsupported_copy_source_kind",
                route="<implicit All copy route>",
                detail="Implicit all-tag copy source is outside bounded JPEG copy materializers.",
            ),
        )
    return ()


def _source_exif_tiff_payload(
    source_path: Path,
    source_kind: JpegComposedCopySourceKind,
) -> bytes:
    if source_kind == "exif_sidecar":
        source_data = read_exact_sidecar_payload(source_path)
        if not source_data:
            raise ValueError("EXIF sidecar source is empty.")
        return source_data
    source = FileMediaSource(source_path)
    for probe in read_jpeg_segment_probes(source_path):
        if probe.marker != 0xE1 or not probe.payload_prefix.startswith(EXIF_APP1_PREFIX):
            continue
        payload = source.read_at(probe.payload_offset, probe.payload_length)
        return payload[len(EXIF_APP1_PREFIX) :]
    raise ValueError("JPEG source does not contain an EXIF APP1 segment.")


def _source_xmp_packet(source_path: Path, source_kind: JpegComposedCopySourceKind) -> bytes:
    if source_kind == "xmp_sidecar":
        source_data = read_exact_sidecar_payload(source_path)
        if not source_data:
            raise ValueError("XMP sidecar source is empty.")
        return source_data
    source = FileMediaSource(source_path)
    for probe in read_jpeg_segment_probes(source_path):
        if probe.marker != 0xE1 or not probe.payload_prefix.startswith(XMP_APP1_PREFIX):
            continue
        payload = source.read_at(probe.payload_offset, probe.payload_length)
        return payload[len(XMP_APP1_PREFIX) :]
    raise ValueError("JPEG source does not contain a standard XMP APP1 segment.")


def _source_iptc_resource(source_path: Path) -> bytes:
    source = FileMediaSource(source_path)
    for probe in read_jpeg_segment_probes(source_path):
        if probe.marker != 0xED:
            continue
        if not probe.payload_prefix.startswith(PHOTOSHOP_APP13_PREFIX):
            continue
        payload = source.read_at(probe.payload_offset, probe.payload_length)
        resources = parse_photoshop_resources(payload)
        iptc = existing_iptc_resource_data(resources)
        if iptc:
            return iptc
    raise ValueError("JPEG source does not contain a Photoshop IPTC resource.")


def _source_ducky_payload(source_path: Path) -> bytes:
    source = FileMediaSource(source_path)
    for probe in read_jpeg_segment_probes(source_path):
        if probe.marker != 0xEC:
            continue
        if probe.payload_prefix.startswith(DUCKY_APP12_PREFIX):
            return source.read_at(probe.payload_offset, probe.payload_length)
    raise ValueError("JPEG source does not contain a Ducky APP12 segment.")


def _materialized_route_by_group(
    routes: tuple[JpegComposedMaterializedRoute, ...],
) -> dict[JpegComposedCopyGroup, JpegComposedMaterializedRoute]:
    route_by_group: dict[JpegComposedCopyGroup, JpegComposedMaterializedRoute] = {}
    for route in routes:
        route_by_group[route.group] = route
    return route_by_group


def _jpeg_maker_note_projection_blocker(source_path: Path) -> JpegComposedCopyBlocker | None:
    try:
        tiff_payload = _source_exif_tiff_payload(source_path, "jpeg")
        make, has_maker_note = _tiff_make_and_makernote(tiff_payload)
    except ValueError:
        return None
    if not has_maker_note:
        return None
    if make.upper().startswith("NIKON"):
        try:
            relocation_plan = build_nikon_d70_jpeg_makernote_relocation_plan(source_path)
        except ValueError:
            relocation_plan = None
        if relocation_plan is not None:
            evidence = relocation_plan.byte_evidence
            blocker = relocation_plan.primary_blocker
            detail = (
                f"{blocker.reason} Source MakerNote byte range is "
                f"{evidence.raw_makernote_offset}.."
                f"{evidence.raw_makernote_end_offset} "
                f"({evidence.raw_makernote_length} bytes); raw Main IFD length is "
                f"{evidence.raw_main_ifd_length} bytes. "
                f"{blocker.unsafe_partial_write_policy}"
            )
        else:
            detail = (
                "Implicit all-tag Nikon JPEG copy includes MakerNotes; exact "
                "relocation must be handled by a source-specific MakerNote writer route."
            )
        return JpegComposedCopyBlocker(
            code="requires_jpeg_composed_writer_contract_for_nikon_makernote_projection",
            route="<implicit All copy route>",
            detail=detail,
        )
    return JpegComposedCopyBlocker(
        code="requires_jpeg_composed_writer_contract_for_jpeg_makernote_projection",
        route="<implicit All copy route>",
        detail=(
            "Implicit all-tag JPEG copy includes MakerNotes; relocation must be "
            "handled by a source-specific MakerNote writer route."
        ),
    )


def _tiff_make_and_makernote(tiff_data: bytes) -> tuple[str, bool]:
    header = parse_tiff_header(tiff_data)
    ifd0 = parse_ifd(tiff_data, header.first_ifd_offset, header.endian)
    make = ""
    exif_ifd_offset = 0
    for entry in ifd0.entries:
        if entry.tag_id == MAKE_TAG_ID:
            value = read_entry_value(tiff_data, entry, header.endian)
            make = value if isinstance(value, str) else ""
        elif entry.tag_id == EXIF_IFD_POINTER_TAG_ID:
            value = read_entry_value(tiff_data, entry, header.endian)
            exif_ifd_offset = value if isinstance(value, int) else 0
    if not exif_ifd_offset:
        return make, False
    exif_ifd = parse_ifd(tiff_data, exif_ifd_offset, header.endian)
    return make, any(entry.tag_id == MAKER_NOTE_TAG_ID for entry in exif_ifd.entries)
